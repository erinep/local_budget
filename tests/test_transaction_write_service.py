"""Contract tests for recategorize_transaction, CategoryNotFound, and
RecategorizationResult (Phase 3b).

Contract sources:
  ADR-0018 — Transaction Engine Write API (recategorize_transaction)

Three surfaces under test:
  1. CategoryNotFound — exception type invariants (no DB required).
  2. RecategorizationResult — frozen dataclass invariants (no DB required).
  3. recategorize_transaction — DB-gated, skipped without DATABASE_URL.

DB-gated tests insert their own auth.users, accounts, uploads, and
transactions rows directly via SQLAlchemy so that each test is
self-contained without relying on upload pipeline internals.

PII note: descriptions, amounts, and fingerprints inserted here are
synthetic test fixtures only; no real financial data.
"""

from __future__ import annotations

import dataclasses
import hashlib
import os
import uuid
from datetime import date, timezone, datetime
from decimal import Decimal

import pytest

# ---------------------------------------------------------------------------
# Skip marker — same pattern as test_account_settings_service.py
# ---------------------------------------------------------------------------

DATABASE_URL = os.environ.get("DATABASE_URL")

pytestmark = pytest.mark.skipif(
    not DATABASE_URL,
    reason="DATABASE_URL must be set to run transaction write service tests",
)


# ---------------------------------------------------------------------------
# Section 1 — Non-DB type invariants
# (These run even without DATABASE_URL because pytestmark is module-level.
#  We work around that by collecting them into a class that does NOT carry
#  the module-level mark — they import only, so they are safe to run always.)
# ---------------------------------------------------------------------------

# Import the public types at module level so import errors surface cleanly.
from app.transactions.services import (
    CategoryNotFound,
    RecategorizationResult,
    Transaction,
    TransactionNotFound,
    recategorize_transaction,
)


class TestCategoryNotFoundType:
    """CategoryNotFound must be an Exception subclass (ADR-0018 public API)."""

    # These tests import only — no DATABASE_URL needed.
    # They run even if DATABASE_URL is absent because pytestmark is applied
    # to the module, but the fixture `app_ctx` is not used here.

    def test_is_exception_subclass(self):
        """CategoryNotFound must subclass Exception."""
        assert issubclass(CategoryNotFound, Exception)

    def test_is_raisable_and_catchable(self):
        """CategoryNotFound can be raised and caught as Exception."""
        with pytest.raises(CategoryNotFound):
            raise CategoryNotFound("no match")

    def test_is_distinct_from_transaction_not_found(self):
        """CategoryNotFound and TransactionNotFound are distinct types."""
        assert CategoryNotFound is not TransactionNotFound
        assert not issubclass(CategoryNotFound, TransactionNotFound)
        assert not issubclass(TransactionNotFound, CategoryNotFound)


class TestRecategorizationResultType:
    """RecategorizationResult must be a frozen dataclass (ADR-0018 public API)."""

    def test_is_frozen_dataclass(self):
        """RecategorizationResult must be a frozen dataclass."""
        assert dataclasses.is_dataclass(RecategorizationResult)
        assert RecategorizationResult.__dataclass_params__.frozen  # type: ignore[attr-defined]

    def test_has_transaction_field(self):
        """RecategorizationResult must have a 'transaction' field."""
        field_names = {f.name for f in dataclasses.fields(RecategorizationResult)}
        assert "transaction" in field_names

    def test_has_keyword_written_field(self):
        """RecategorizationResult must have a 'keyword_written' bool field."""
        field_names = {f.name for f in dataclasses.fields(RecategorizationResult)}
        assert "keyword_written" in field_names

    def test_has_keyword_conflict_field(self):
        """RecategorizationResult must have a 'keyword_conflict' bool field."""
        field_names = {f.name for f in dataclasses.fields(RecategorizationResult)}
        assert "keyword_conflict" in field_names

    def test_is_immutable(self):
        """Frozen dataclass must reject attribute assignment."""
        # Build a minimal Transaction to satisfy the field type.
        txn = Transaction(
            id=uuid.uuid4(),
            account_id=uuid.uuid4(),
            account_name="Test",
            date=date(2026, 1, 1),
            description="TEST",
            amount=Decimal("-1.00"),
            category_id=None,
            category_name=None,
            created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        )
        result = RecategorizationResult(
            transaction=txn,
            keyword_written=False,
            keyword_conflict=False,
        )
        with pytest.raises((dataclasses.FrozenInstanceError, AttributeError)):
            result.keyword_written = True  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Section 2 — DB-gated tests for recategorize_transaction
# ---------------------------------------------------------------------------

import sqlalchemy as sa


@pytest.fixture(scope="module")
def app_ctx():
    """Module-scoped Flask app context so service calls have current_app."""
    from app import create_app
    app = create_app()
    app.config["TESTING"] = True
    with app.app_context():
        yield


def _uid() -> str:
    """Insert a row into auth.users and return its UUID string.

    Mirrors the pattern in test_account_settings_service.py exactly.
    The categories and transactions tables carry ON DELETE CASCADE from
    auth.users, so creating a real auth.users row satisfies all FKs.
    """
    user_id = str(uuid.uuid4())
    engine = sa.create_engine(DATABASE_URL)
    with engine.begin() as conn:
        conn.execute(
            sa.text("INSERT INTO auth.users (id) VALUES (:uid)"),
            {"uid": user_id},
        )
    return user_id


def _make_fingerprint(user_id: str, seq: int = 0) -> bytes:
    """Return a unique, valid 32-byte fingerprint for test rows."""
    canonical = f"{user_id}\x1f{seq}\x1f2026-01-15\x1ftest merchant\x1f-1.00\x1f0"
    return hashlib.sha256(canonical.encode()).digest()


def _setup_transaction(
    user_id: str,
    category_id: str | None = None,
    seq: int = 0,
) -> str:
    """Insert account, upload, and transaction rows; return transaction UUID string.

    All rows are scoped to user_id. The transaction's category_id may be
    set to an existing category UUID or left None (uncategorized).
    """
    engine = sa.create_engine(DATABASE_URL)
    with engine.begin() as conn:
        # 1. Create account
        account_id = conn.execute(
            sa.text(
                "INSERT INTO public.accounts (user_id, name, kind, currency)"
                " VALUES (:uid, :name, 'checking', 'CAD')"
                " RETURNING id"
            ),
            {"uid": user_id, "name": f"TestAccount-{seq}-{uuid.uuid4()}"},
        ).scalar()

        # 2. Create upload
        upload_id = conn.execute(
            sa.text(
                "INSERT INTO public.uploads"
                " (user_id, account_id, filename, file_hash, row_count)"
                " VALUES (:uid, :acid, 'test.csv', :fhash, 1)"
                " RETURNING id"
            ),
            {
                "uid": user_id,
                "acid": str(account_id),
                "fhash": hashlib.sha256(f"file-{uuid.uuid4()}".encode()).digest(),
            },
        ).scalar()

        # 3. Create transaction
        fp = _make_fingerprint(user_id, seq)
        txn_id = conn.execute(
            sa.text(
                "INSERT INTO public.transactions"
                " (user_id, account_id, source_file_id, date, description,"
                "  amount, category_id, fingerprint)"
                " VALUES (:uid, :acid, :fid, :dt, :desc, :amt, :cat, :fp)"
                " RETURNING id"
            ),
            {
                "uid": user_id,
                "acid": str(account_id),
                "fid": str(upload_id),
                "dt": date(2026, 1, 15),
                "desc": "TEST MERCHANT",
                "amt": Decimal("-1.00"),
                "cat": category_id,
                "fp": fp,
            },
        ).scalar()

    return str(txn_id)


# ---------------------------------------------------------------------------
# (a) Successful recategorize-only
# ---------------------------------------------------------------------------

class TestRecategorizeOnly:
    """recategorize_transaction with no apply_forward_keyword — category updated only."""

    def test_returns_recategorization_result(self, app_ctx):
        """Must return a RecategorizationResult (not None, not dict)."""
        from app.account_settings.services import create_category

        user_id = _uid()
        cat = create_category(user_id, "Food")
        txn_id = _setup_transaction(user_id)

        result = recategorize_transaction(
            user_id=user_id,
            transaction_id=uuid.UUID(txn_id),
            category_id=uuid.UUID(cat["id"]),
        )

        assert isinstance(result, RecategorizationResult)

    def test_keyword_written_is_false(self, app_ctx):
        """No apply_forward_keyword provided — keyword_written must be False."""
        from app.account_settings.services import create_category

        user_id = _uid()
        cat = create_category(user_id, "Transport")
        txn_id = _setup_transaction(user_id, seq=1)

        result = recategorize_transaction(
            user_id=user_id,
            transaction_id=uuid.UUID(txn_id),
            category_id=uuid.UUID(cat["id"]),
        )

        assert result.keyword_written is False

    def test_keyword_conflict_is_false(self, app_ctx):
        """No keyword write attempted — keyword_conflict must be False."""
        from app.account_settings.services import create_category

        user_id = _uid()
        cat = create_category(user_id, "Utilities")
        txn_id = _setup_transaction(user_id, seq=2)

        result = recategorize_transaction(
            user_id=user_id,
            transaction_id=uuid.UUID(txn_id),
            category_id=uuid.UUID(cat["id"]),
        )

        assert result.keyword_conflict is False

    def test_transaction_category_id_is_updated(self, app_ctx):
        """After recategorize, the returned transaction must carry the new category_id."""
        from app.account_settings.services import create_category

        user_id = _uid()
        cat = create_category(user_id, "Groceries")
        txn_id = _setup_transaction(user_id, seq=3)

        result = recategorize_transaction(
            user_id=user_id,
            transaction_id=uuid.UUID(txn_id),
            category_id=uuid.UUID(cat["id"]),
        )

        assert result.transaction.category_id == uuid.UUID(cat["id"])


# ---------------------------------------------------------------------------
# (b) Successful recategorize with keyword write
# ---------------------------------------------------------------------------

class TestRecategorizeWithKeywordWrite:
    """recategorize_transaction with apply_forward_keyword writes a new keyword."""

    def test_keyword_written_is_true(self, app_ctx):
        """When apply_forward_keyword is new, keyword_written must be True."""
        from app.account_settings.services import create_category

        user_id = _uid()
        cat = create_category(user_id, "Coffee")
        txn_id = _setup_transaction(user_id, seq=10)

        result = recategorize_transaction(
            user_id=user_id,
            transaction_id=uuid.UUID(txn_id),
            category_id=uuid.UUID(cat["id"]),
            apply_forward_keyword="TIM HORTONS",
        )

        assert result.keyword_written is True

    def test_keyword_conflict_is_false_on_new_keyword(self, app_ctx):
        """Fresh keyword write — keyword_conflict must be False."""
        from app.account_settings.services import create_category

        user_id = _uid()
        cat = create_category(user_id, "Bakery")
        txn_id = _setup_transaction(user_id, seq=11)

        result = recategorize_transaction(
            user_id=user_id,
            transaction_id=uuid.UUID(txn_id),
            category_id=uuid.UUID(cat["id"]),
            apply_forward_keyword="BREADCO",
        )

        assert result.keyword_conflict is False

    def test_keyword_appears_in_account_settings(self, app_ctx):
        """After recategorize with keyword write, the keyword must be in Account Settings."""
        from app.account_settings.services import create_category, list_categories

        user_id = _uid()
        cat = create_category(user_id, "Burgers")
        txn_id = _setup_transaction(user_id, seq=12)

        recategorize_transaction(
            user_id=user_id,
            transaction_id=uuid.UUID(txn_id),
            category_id=uuid.UUID(cat["id"]),
            apply_forward_keyword="big mac",  # lowercase — add_keyword normalizes to uppercase
        )

        cats = list_categories(user_id)
        burgers = next(c for c in cats if c["name"] == "Burgers")
        assert "BIG MAC" in burgers["keywords"], (
            "Keyword must appear uppercased in Account Settings after apply_forward write"
        )


# ---------------------------------------------------------------------------
# (c) Recategorize with already-existing keyword (conflict)
# ---------------------------------------------------------------------------

class TestRecategorizeKeywordConflict:
    """apply_forward_keyword already exists — keyword_conflict=True, no exception."""

    def test_keyword_conflict_is_true(self, app_ctx):
        """Pre-existing keyword must set keyword_conflict=True."""
        from app.account_settings.services import create_category, add_keyword

        user_id = _uid()
        cat = create_category(user_id, "Sushi")
        add_keyword(user_id, cat["id"], "SUSHI WORLD")  # pre-insert the keyword
        txn_id = _setup_transaction(user_id, seq=20)

        result = recategorize_transaction(
            user_id=user_id,
            transaction_id=uuid.UUID(txn_id),
            category_id=uuid.UUID(cat["id"]),
            apply_forward_keyword="SUSHI WORLD",  # same keyword — already exists
        )

        assert result.keyword_conflict is True

    def test_keyword_written_is_false_on_conflict(self, app_ctx):
        """Conflict means no new write — keyword_written must be False."""
        from app.account_settings.services import create_category, add_keyword

        user_id = _uid()
        cat = create_category(user_id, "Ramen")
        add_keyword(user_id, cat["id"], "ICHIRAKU")
        txn_id = _setup_transaction(user_id, seq=21)

        result = recategorize_transaction(
            user_id=user_id,
            transaction_id=uuid.UUID(txn_id),
            category_id=uuid.UUID(cat["id"]),
            apply_forward_keyword="ICHIRAKU",
        )

        assert result.keyword_written is False

    def test_no_exception_on_conflict(self, app_ctx):
        """Keyword conflict must not raise — it is a documented non-error (ADR-0018)."""
        from app.account_settings.services import create_category, add_keyword

        user_id = _uid()
        cat = create_category(user_id, "Tacos")
        add_keyword(user_id, cat["id"], "TACO BELL")
        txn_id = _setup_transaction(user_id, seq=22)

        # Must not raise any exception.
        result = recategorize_transaction(
            user_id=user_id,
            transaction_id=uuid.UUID(txn_id),
            category_id=uuid.UUID(cat["id"]),
            apply_forward_keyword="TACO BELL",
        )

        assert isinstance(result, RecategorizationResult)


# ---------------------------------------------------------------------------
# (d) TransactionNotFound for unknown transaction_id
# ---------------------------------------------------------------------------

class TestTransactionNotFoundOnRecategorize:
    """recategorize_transaction must raise TransactionNotFound for unknown IDs."""

    def test_unknown_transaction_id_raises(self, app_ctx):
        """A random UUID that has no row must raise TransactionNotFound."""
        from app.account_settings.services import create_category

        user_id = _uid()
        cat = create_category(user_id, "Movies")

        with pytest.raises(TransactionNotFound):
            recategorize_transaction(
                user_id=user_id,
                transaction_id=uuid.uuid4(),  # does not exist
                category_id=uuid.UUID(cat["id"]),
            )

    def test_cross_user_transaction_raises_transaction_not_found(self, app_ctx):
        """A transaction belonging to user_b must be invisible to user_a (ADR-0018)."""
        from app.account_settings.services import create_category

        user_a = _uid()
        user_b = _uid()
        cat_a = create_category(user_a, "Gym")
        txn_b = _setup_transaction(user_b, seq=30)

        with pytest.raises(TransactionNotFound):
            recategorize_transaction(
                user_id=user_a,
                transaction_id=uuid.UUID(txn_b),
                category_id=uuid.UUID(cat_a["id"]),
            )


# ---------------------------------------------------------------------------
# (e) CategoryNotFound for category belonging to a different user
# ---------------------------------------------------------------------------

class TestCategoryNotFoundOnRecategorize:
    """recategorize_transaction must raise CategoryNotFound when category_id is foreign."""

    def test_other_users_category_raises_category_not_found(self, app_ctx):
        """category_id that belongs to user_b must raise CategoryNotFound for user_a."""
        from app.account_settings.services import create_category

        user_a = _uid()
        user_b = _uid()

        # user_b owns the category; user_a owns the transaction
        cat_b = create_category(user_b, "Yoga")
        txn_a = _setup_transaction(user_a, seq=40)

        with pytest.raises(CategoryNotFound):
            recategorize_transaction(
                user_id=user_a,
                transaction_id=uuid.UUID(txn_a),
                category_id=uuid.UUID(cat_b["id"]),
            )

    def test_nonexistent_category_id_raises_category_not_found(self, app_ctx):
        """A random UUID that has no category row must raise CategoryNotFound."""
        user_id = _uid()
        txn_id = _setup_transaction(user_id, seq=41)

        with pytest.raises(CategoryNotFound):
            recategorize_transaction(
                user_id=user_id,
                transaction_id=uuid.UUID(txn_id),
                category_id=uuid.uuid4(),  # does not exist
            )


# ---------------------------------------------------------------------------
# (f) category_id=None clears categorization
# ---------------------------------------------------------------------------

class TestRecategorizeClear:
    """category_id=None must set transactions.category_id to NULL (ADR-0020 addendum)."""

    def test_category_id_none_returns_result_with_null_category(self, app_ctx):
        """Result transaction must have category_id=None when cleared."""
        from app.account_settings.services import create_category

        user_id = _uid()
        cat = create_category(user_id, "Snacks")
        txn_id = _setup_transaction(user_id, category_id=cat["id"], seq=50)

        result = recategorize_transaction(
            user_id=user_id,
            transaction_id=uuid.UUID(txn_id),
            category_id=None,
        )

        assert result.transaction.category_id is None

    def test_keyword_write_skipped_when_category_id_is_none(self, app_ctx):
        """apply_forward_keyword is ignored when category_id is None (ADR-0020 addendum)."""
        user_id = _uid()
        txn_id = _setup_transaction(user_id, seq=51)

        result = recategorize_transaction(
            user_id=user_id,
            transaction_id=uuid.UUID(txn_id),
            category_id=None,
            apply_forward_keyword="SOME KEYWORD",  # must be ignored
        )

        # Keyword write must be skipped — no category to write to.
        assert result.keyword_written is False
        assert result.keyword_conflict is False

    def test_whitespace_only_keyword_treated_as_none(self, app_ctx):
        """apply_forward_keyword containing only whitespace must be treated as absent."""
        from app.account_settings.services import create_category

        user_id = _uid()
        cat = create_category(user_id, "Drinks")
        txn_id = _setup_transaction(user_id, seq=52)

        result = recategorize_transaction(
            user_id=user_id,
            transaction_id=uuid.UUID(txn_id),
            category_id=uuid.UUID(cat["id"]),
            apply_forward_keyword="   ",  # whitespace-only — must be treated as None
        )

        # No keyword write attempted.
        assert result.keyword_written is False
        assert result.keyword_conflict is False
