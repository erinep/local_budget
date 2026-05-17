"""Contract tests for the Account Settings request-scoped cache (ADR-0010).

These tests validate the binding rules from ADR-0010:

  1. Cache hit within a request — list_categories called twice in one request
     issues only ONE category SELECT.
  2. Cache miss across requests — each HTTP request is isolated (flask.g
     does not leak across requests).
  3. Write invalidates the cache — a mutating call (create_category) clears
     the cached entry, so the next list_categories re-queries the DB.
  4. No-context fallback — list_categories must not raise when called
     outside a Flask request/app context (CLI / background-job path).
  5. User isolation within a request — list_categories(user_a) and
     list_categories(user_b) must each hit the DB; one user's cache entry
     must never serve another user's request.

Implementation approach:
  We patch ``app.account_settings.services.get_engine`` with a MagicMock
  that returns context-managed connections. The connections' ``execute``
  calls are routed through a side-effect that counts how many times the
  category SELECT statement is issued. We assert on call counts, never on
  raw SQL strings — except to discriminate between the category SELECT
  and the keyword SELECT, which is unavoidable.

We never read or modify production code in these tests; the contract under
test is ADR-0010 alone.
"""

from __future__ import annotations

import uuid
from contextlib import contextmanager
from unittest.mock import MagicMock, patch

import pytest

from app import create_app


SERVICES = "app.account_settings.services"


# ---------------------------------------------------------------------------
# Fake DB engine: counts category SELECTs and returns plausibly-shaped rows.
# ---------------------------------------------------------------------------

class FakeEngine:
    """Stand-in for a SQLAlchemy Engine that records category SELECT counts.

    Only ``list_categories`` and the cache helpers are exercised by these
    tests; the engine therefore needs to support two queries:

      * SELECT id, name FROM public.categories ...  (the cached query)
      * SELECT category_id, keyword FROM public.category_keywords ...

    Plus the INSERT issued by ``create_category`` via ``engine.begin()``.
    """

    def __init__(self) -> None:
        self.category_select_count = 0
        # Tracks per-user category rows returned. Empty list is fine for the
        # cache contract — list_categories will short-circuit and still
        # populate the cache (per ADR-0010 "shape" section).
        self.rows_by_user: dict[str, list] = {}

    # ----- query routing -------------------------------------------------

    def _execute(self, statement, params=None):  # noqa: D401 — mimic SA API
        sql = str(statement)
        result = MagicMock()

        if "FROM public.categories" in sql and "SELECT id, name" in sql:
            # The cached read path — count it.
            self.category_select_count += 1
            uid = (params or {}).get("uid")
            rows = self.rows_by_user.get(uid, [])
            result.fetchall.return_value = rows
            result.fetchone.return_value = rows[0] if rows else None
            return result

        if "FROM public.category_keywords" in sql:
            result.fetchall.return_value = []
            return result

        if "INSERT INTO public.categories" in sql:
            # create_category expects RETURNING id; fabricate one.
            new_id = str(uuid.uuid4())
            result.fetchone.return_value = (new_id,)
            return result

        # Default: behave like a no-op result.
        result.fetchall.return_value = []
        result.fetchone.return_value = None
        return result

    # ----- context-manager connections -----------------------------------

    @contextmanager
    def connect(self):
        yield _FakeConn(self)

    @contextmanager
    def begin(self):
        yield _FakeConn(self)


class _FakeConn:
    def __init__(self, engine: FakeEngine) -> None:
        self._engine = engine

    def execute(self, statement, params=None):
        return self._engine._execute(statement, params)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def app():
    """Minimal app for request/app-context-driven cache tests."""
    app = create_app()
    app.config["TESTING"] = True
    app.config["WTF_CSRF_ENABLED"] = False
    return app


@pytest.fixture
def fake_engine():
    return FakeEngine()


@pytest.fixture
def patched_engine(fake_engine):
    """Patch the engine factory used by the service module."""
    with patch(f"{SERVICES}.get_engine", return_value=fake_engine):
        yield fake_engine


# ---------------------------------------------------------------------------
# 1. Cache hit within a request
# ---------------------------------------------------------------------------

class TestCacheHitWithinRequest:
    def test_two_calls_one_request_one_db_query(self, app, patched_engine):
        """Behavior under test: two list_categories() calls inside the same
        request context must issue exactly ONE category SELECT (ADR-0010
        "Read path"). The second call must be served from g._category_cache.
        """
        from app.account_settings.services import list_categories

        user_id = str(uuid.uuid4())

        # Arrange + Act: a single request scope, two reads.
        with app.test_request_context("/"):
            list_categories(user_id)
            list_categories(user_id)

        # Assert: the second read was a cache hit, so only ONE SELECT.
        assert patched_engine.category_select_count == 1, (
            "Two list_categories() calls in one request must result in exactly "
            "one DB query (ADR-0010 read path)."
        )


# ---------------------------------------------------------------------------
# 2. Cache miss across requests — request isolation
# ---------------------------------------------------------------------------

class TestCacheMissAcrossRequests:
    def test_separate_request_contexts_each_hit_db(self, app, patched_engine):
        """Behavior under test: flask.g is request-scoped; a second, separate
        request must re-fetch from the DB. ADR-0010 explicitly rejects
        cross-request caching."""
        from app.account_settings.services import list_categories

        user_id = str(uuid.uuid4())

        with app.test_request_context("/"):
            list_categories(user_id)

        with app.test_request_context("/"):
            list_categories(user_id)

        assert patched_engine.category_select_count == 2, (
            "Each new request must trigger a fresh category SELECT — flask.g "
            "must not leak across requests."
        )


# ---------------------------------------------------------------------------
# 3. Write invalidates the cache
# ---------------------------------------------------------------------------

class TestWriteInvalidatesCache:
    def test_create_category_invalidates_cache(self, app, patched_engine):
        """Behavior under test: ADR-0010 write path requires every mutating
        function to pop the user_id from g._category_cache. So the sequence
        list → create → list must issue TWO category SELECTs (one before
        the write, one after the invalidation)."""
        from app.account_settings.services import create_category, list_categories

        user_id = str(uuid.uuid4())

        with app.test_request_context("/"):
            list_categories(user_id)                       # SELECT #1
            create_category(user_id, "Groceries")          # write -> invalidate
            list_categories(user_id)                       # SELECT #2

        assert patched_engine.category_select_count == 2, (
            "A mutating function (create_category) must invalidate the cache, "
            "forcing the next list_categories() to re-query the DB."
        )


# ---------------------------------------------------------------------------
# 4. No-context fallback — must not raise outside request context
# ---------------------------------------------------------------------------

class TestNoContextFallback:
    def test_list_categories_outside_request_context_does_not_raise(
        self, patched_engine
    ):
        """Behavior under test: ADR-0010 "Outside request context" rule.
        Service functions must fall through to a direct DB query (with no
        caching) when flask.g is unavailable. Calling list_categories from
        outside any Flask context must not raise RuntimeError."""
        from app.account_settings.services import list_categories

        user_id = str(uuid.uuid4())

        # Act + Assert: must not raise.
        result = list_categories(user_id)

        assert result == [], (
            "Outside a request context list_categories should return the DB "
            "result (here: empty list) cleanly, with no caching layer touched."
        )
        # Sanity: the DB was hit (no cache available to short-circuit).
        assert patched_engine.category_select_count == 1


# ---------------------------------------------------------------------------
# 5. User isolation within a single request
# ---------------------------------------------------------------------------

class TestUserIsolationWithinRequest:
    def test_two_users_in_one_request_each_hit_db(self, app, patched_engine):
        """Behavior under test: the cache is keyed by user_id (ADR-0010
        "Cache key"). list_categories(user_a) followed by list_categories
        (user_b) within one request must trigger TWO DB reads — user A's
        cached entry must never satisfy user B's call."""
        from app.account_settings.services import list_categories

        user_a = str(uuid.uuid4())
        user_b = str(uuid.uuid4())

        with app.test_request_context("/"):
            list_categories(user_a)
            list_categories(user_b)

        assert patched_engine.category_select_count == 2, (
            "list_categories(user_a) and list_categories(user_b) must each "
            "issue a DB query — the cache is keyed per-user."
        )
