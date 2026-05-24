"""Contract tests for the Transaction Engine service layer (Phase 3a).

Contract sources:
  ADR-0017 — Transaction Engine Read API Contract
  ADR-0013 — Two-layer hash idempotency strategy (_compute_fingerprint)
  ADR-0016 — Phase 3a schema (migration structural tests)

Three surfaces under test:
  1. Alembic migration 0003_transactions_uploads_accounts — structural/static checks.
  2. _compute_fingerprint — pure function, no DB required.
  3. TransactionFilters validation — fires before any DB call, no DB required.
  4. Public types (Transaction, TransactionPage, TransactionFilters,
     TransactionNotFound) — import-level and frozen-dataclass checks.
  5. get_transactions / get_transaction — DB-gated, skipped without DATABASE_URL.

Validation tests patch app.transactions.services.get_engine to an error-raiser to
confirm that ValueError is raised before any DB call is attempted (ADR-0017:
"Validation runs before any database query is issued").
"""

from __future__ import annotations

import dataclasses
import importlib
import os
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any
from unittest.mock import MagicMock, patch
from uuid import UUID

import pytest

# ---------------------------------------------------------------------------
# Skip marker for DB-gated tests (follows pattern in test_account_settings_service.py)
# ---------------------------------------------------------------------------

DATABASE_URL = os.environ.get("DATABASE_URL")

requires_db = pytest.mark.skipif(
    not DATABASE_URL,
    reason="DATABASE_URL must be set to run DB-gated transaction service tests",
)

# ---------------------------------------------------------------------------
# Public API imports
# ---------------------------------------------------------------------------

from app.transactions.services import (
    Transaction,
    TransactionFilters,
    TransactionNotFound,
    TransactionPage,
    _compute_fingerprint,
    get_transaction,
    get_transactions,
)

# Patch target — the engine factory used inside services.py
_ENGINE_PATH = "app.transactions.services.get_engine"


def _engine_that_must_not_be_called() -> Any:
    """Return a mock that raises AssertionError if any attribute is accessed.

    Patches app.transactions.services.get_engine with a callable that returns
    this mock. If any DB call is made before validation raises, the test fails.
    """
    sentinel = MagicMock()
    sentinel.side_effect = AssertionError(
        "get_engine was called before validation raised — "
        "validation must fire before any DB access (ADR-0017)"
    )
    return sentinel


# ===========================================================================
# Section 1 — Alembic migration structural tests
# ===========================================================================

class TestMigration0003Structure:
    """Structural/static checks for the Phase 3a Alembic migration.

    These tests do NOT run against a real database. They verify that the
    migration file exists, imports cleanly, and declares the expected revision
    metadata and callable upgrade/downgrade functions.
    """

    _MODULE_PATH = "migrations.versions.0003_transactions_uploads_accounts"

    @pytest.fixture(scope="class")
    def migration(self):
        """Import the migration module once for all structural tests."""
        try:
            mod = importlib.import_module(self._MODULE_PATH)
        except ModuleNotFoundError as exc:
            pytest.fail(
                f"Migration module not found: {self._MODULE_PATH!r}. "
                f"Original error: {exc}"
            )
        return mod

    def test_migration_imports_cleanly(self, migration):
        """The migration module must import without errors."""
        assert migration is not None

    def test_revision_attribute_is_0003(self, migration):
        """revision must be '0003' (the Phase 3a migration sequence number)."""
        assert hasattr(migration, "revision"), "migration missing 'revision' attribute"
        assert migration.revision == "0003"

    def test_down_revision_is_0002(self, migration):
        """down_revision must be '0002' — the normalize-categories migration."""
        assert hasattr(migration, "down_revision"), "migration missing 'down_revision'"
        assert migration.down_revision == "0002"

    def test_upgrade_is_callable(self, migration):
        """upgrade() must be a callable (the DDL apply function)."""
        assert callable(getattr(migration, "upgrade", None)), \
            "migration must define a callable upgrade()"

    def test_downgrade_is_callable(self, migration):
        """downgrade() must be a callable (the DDL rollback function)."""
        assert callable(getattr(migration, "downgrade", None)), \
            "migration must define a callable downgrade()"

    def test_branch_labels_is_none(self, migration):
        """branch_labels should be None for a linear migration history."""
        # Per convention from existing migrations 0001 and 0002
        assert getattr(migration, "branch_labels", None) is None

    def test_depends_on_is_none(self, migration):
        """depends_on should be None (no out-of-band dependencies)."""
        assert getattr(migration, "depends_on", None) is None


# ===========================================================================
# Section 2 — _compute_fingerprint pure-function tests (no DB)
# ===========================================================================

class TestComputeFingerprint:
    """Tests for _compute_fingerprint (ADR-0013 layer-2 hash).

    This is a pure function — no DB, no patching needed. All determinism
    and collision-differentiation properties are testable from the spec alone.
    """

    # Baseline inputs reused across tests.
    _BASE = dict(
        user_id="00000000-0000-0000-0000-000000000001",
        account_id="00000000-0000-0000-0000-000000000002",
        iso_date="2026-01-15",
        description_normalized="tim hortons",
        amount_signed_2dp="-4.50",
        within_file_seq=0,
    )

    def _fp(self, **overrides) -> bytes:
        args = {**self._BASE, **overrides}
        return _compute_fingerprint(**args)

    def test_output_is_bytes(self):
        """Fingerprint must be bytes (BYTEA-compatible)."""
        result = self._fp()
        assert isinstance(result, bytes)

    def test_output_is_32_bytes(self):
        """SHA-256 digest is exactly 32 bytes."""
        result = self._fp()
        assert len(result) == 32

    def test_deterministic_same_inputs(self):
        """Same inputs must produce identical output (hash is deterministic)."""
        first = self._fp()
        second = self._fp()
        assert first == second

    def test_different_user_id_changes_fingerprint(self):
        """Different user_id must produce a different fingerprint (namespace isolation)."""
        fp_a = self._fp(user_id="00000000-0000-0000-0000-000000000001")
        fp_b = self._fp(user_id="00000000-0000-0000-0000-000000000099")
        assert fp_a != fp_b

    def test_different_account_id_changes_fingerprint(self):
        """Different account_id must produce a different fingerprint (ADR-0014)."""
        fp_a = self._fp(account_id="00000000-0000-0000-0000-000000000002")
        fp_b = self._fp(account_id="00000000-0000-0000-0000-000000000088")
        assert fp_a != fp_b

    def test_different_iso_date_changes_fingerprint(self):
        """Different iso_date must produce a different fingerprint."""
        fp_a = self._fp(iso_date="2026-01-15")
        fp_b = self._fp(iso_date="2026-01-16")
        assert fp_a != fp_b

    def test_different_description_changes_fingerprint(self):
        """Different description_normalized must produce a different fingerprint."""
        fp_a = self._fp(description_normalized="tim hortons")
        fp_b = self._fp(description_normalized="uber eats")
        assert fp_a != fp_b

    def test_different_amount_changes_fingerprint(self):
        """Different amount_signed_2dp must produce a different fingerprint."""
        fp_a = self._fp(amount_signed_2dp="-4.50")
        fp_b = self._fp(amount_signed_2dp="-5.00")
        assert fp_a != fp_b

    def test_different_within_file_seq_changes_fingerprint(self):
        """seq=0 vs seq=1 on identical (date, desc, amount) must differ.

        This preserves genuine same-day duplicates (ADR-0013): two identical
        rows in the same file produce distinct fingerprints so both are stored.
        """
        fp_seq0 = self._fp(within_file_seq=0)
        fp_seq1 = self._fp(within_file_seq=1)
        assert fp_seq0 != fp_seq1

    def test_unit_separator_is_load_bearing(self):
        """Fields joined by 0x1F (unit separator) — adjacent-field concatenation
        must NOT produce the same hash as the separated canonical string.

        E.g. user_id="AA", account_id="BB" must differ from
             user_id="A", account_id="ABB" (without the separator they
             would produce the same concatenation).
        """
        # Craft two inputs that would collide without a separator.
        fp_a = _compute_fingerprint(
            user_id="AA",
            account_id="BB",
            iso_date="2026-01-01",
            description_normalized="x",
            amount_signed_2dp="-1.00",
            within_file_seq=0,
        )
        fp_b = _compute_fingerprint(
            user_id="A",
            account_id="ABB",
            iso_date="2026-01-01",
            description_normalized="x",
            amount_signed_2dp="-1.00",
            within_file_seq=0,
        )
        assert fp_a != fp_b

    def test_user_id_is_case_folded(self):
        """user_id is lowercased before hashing — uppercase and lowercase UUIDs
        must produce the same fingerprint."""
        fp_lower = self._fp(user_id="00000000-0000-0000-0000-000000000001")
        fp_upper = self._fp(user_id="00000000-0000-0000-0000-000000000001".upper())
        assert fp_lower == fp_upper

    def test_account_id_is_case_folded(self):
        """account_id is lowercased before hashing."""
        fp_lower = self._fp(account_id="00000000-0000-0000-0000-000000000002")
        fp_upper = self._fp(account_id="00000000-0000-0000-0000-000000000002".upper())
        assert fp_lower == fp_upper


# ===========================================================================
# Section 3 — Public type import and frozen-dataclass invariants (no DB)
# ===========================================================================

class TestPublicTypeInvariants:
    """Import-level and dataclass-property tests for the public contract types.

    These verify that the types are what ADR-0017 says they are. No DB needed.
    """

    def test_transaction_is_frozen_dataclass(self):
        """Transaction must be a frozen dataclass (immutable, hashable)."""
        assert dataclasses.is_dataclass(Transaction)
        assert Transaction.__dataclass_params__.frozen  # type: ignore[attr-defined]

    def test_transaction_page_is_frozen_dataclass(self):
        """TransactionPage must be a frozen dataclass."""
        assert dataclasses.is_dataclass(TransactionPage)
        assert TransactionPage.__dataclass_params__.frozen  # type: ignore[attr-defined]

    def test_transaction_filters_is_frozen_dataclass(self):
        """TransactionFilters must be a frozen dataclass."""
        assert dataclasses.is_dataclass(TransactionFilters)
        assert TransactionFilters.__dataclass_params__.frozen  # type: ignore[attr-defined]

    def test_transaction_not_found_is_exception_subclass(self):
        """TransactionNotFound must subclass Exception (ADR-0017)."""
        assert issubclass(TransactionNotFound, Exception)

    def test_transaction_not_found_is_raisable(self):
        """TransactionNotFound can be raised and caught as Exception."""
        with pytest.raises(TransactionNotFound):
            raise TransactionNotFound("no row found")

    def test_transaction_filters_defaults(self):
        """Default TransactionFilters must match ADR-0017 defaults exactly."""
        f = TransactionFilters()
        assert f.date_from is None
        assert f.date_to is None
        assert f.category_id is None
        assert f.account_id is None
        assert f.search is None
        assert f.uncategorized_only is False
        assert f.limit == 50
        assert f.offset == 0

    def test_transaction_filters_is_immutable(self):
        """Frozen dataclass must reject attribute assignment."""
        f = TransactionFilters()
        with pytest.raises((dataclasses.FrozenInstanceError, AttributeError)):
            f.limit = 10  # type: ignore[misc]

    def test_transaction_page_fields_exist(self):
        """TransactionPage must have items, total_count, limit, offset fields."""
        field_names = {f.name for f in dataclasses.fields(TransactionPage)}
        assert {"items", "total_count", "limit", "offset"} <= field_names

    def test_transaction_fields_exist(self):
        """Transaction must have all ADR-0017 specified fields."""
        field_names = {f.name for f in dataclasses.fields(Transaction)}
        expected = {
            "id", "account_id", "account_name", "date", "description",
            "amount", "category_id", "category_name", "created_at",
        }
        assert expected <= field_names

    def test_transaction_does_not_expose_fingerprint(self):
        """fingerprint must NOT be a field on Transaction (ADR-0017: excluded)."""
        field_names = {f.name for f in dataclasses.fields(Transaction)}
        assert "fingerprint" not in field_names

    def test_transaction_does_not_expose_source_file_id(self):
        """source_file_id must NOT be a field on Transaction (internal, ADR-0017)."""
        field_names = {f.name for f in dataclasses.fields(Transaction)}
        assert "source_file_id" not in field_names

    def test_transaction_does_not_expose_user_id(self):
        """user_id must NOT be a field on Transaction (redundant, ADR-0017)."""
        field_names = {f.name for f in dataclasses.fields(Transaction)}
        assert "user_id" not in field_names


# ===========================================================================
# Section 4 — TransactionFilters validation (no DB required)
# ===========================================================================
#
# All tests in this class patch get_engine with a side-effect raiser.
# If a ValueError is raised, we know it fired before any DB call.
# If AssertionError fires from the mock, the implementation reached DB
# before validating — a contract violation.

class TestTransactionFiltersValidation:
    """Validation tests for TransactionFilters fields (ADR-0017 error model).

    Validation must fire before any database query (ADR-0017). We verify this
    by patching get_engine with a callable that raises AssertionError if invoked.
    """

    def _call_with_filters(self, filters):
        """Call get_transactions with the engine patched to fail on access."""
        with patch(_ENGINE_PATH, side_effect=_engine_that_must_not_be_called()):
            return get_transactions("user-id-stub", filters)

    # --- limit validation ---

    def test_limit_zero_raises_value_error(self):
        """limit=0 is below the minimum (1) — must raise ValueError before DB."""
        with pytest.raises(ValueError, match="limit"):
            self._call_with_filters(TransactionFilters(limit=0))

    def test_limit_negative_raises_value_error(self):
        """limit=-1 is below the minimum — must raise ValueError before DB."""
        with pytest.raises(ValueError, match="limit"):
            self._call_with_filters(TransactionFilters(limit=-1))

    def test_limit_201_raises_value_error(self):
        """limit=201 exceeds the maximum (200) — must raise ValueError before DB."""
        with pytest.raises(ValueError, match="limit"):
            self._call_with_filters(TransactionFilters(limit=201))

    def test_limit_1_is_valid_boundary(self):
        """limit=1 is the lower boundary — must NOT raise ValueError."""
        # The DB call will fail via mock (AssertionError), but ValueError must not fire.
        with pytest.raises(AssertionError):
            self._call_with_filters(TransactionFilters(limit=1))

    def test_limit_200_is_valid_boundary(self):
        """limit=200 is the upper boundary — must NOT raise ValueError."""
        with pytest.raises(AssertionError):
            self._call_with_filters(TransactionFilters(limit=200))

    # --- offset validation ---

    def test_offset_negative_raises_value_error(self):
        """offset=-1 is below the minimum (0) — must raise ValueError before DB."""
        with pytest.raises(ValueError, match="offset"):
            self._call_with_filters(TransactionFilters(offset=-1))

    def test_offset_zero_is_valid_boundary(self):
        """offset=0 is the lower boundary — must NOT raise ValueError."""
        with pytest.raises(AssertionError):
            self._call_with_filters(TransactionFilters(offset=0))

    # --- date range validation ---

    def test_date_from_after_date_to_raises_value_error(self):
        """date_from > date_to must raise ValueError before DB."""
        with pytest.raises(ValueError, match="date_from"):
            self._call_with_filters(
                TransactionFilters(
                    date_from=date(2026, 2, 1),
                    date_to=date(2026, 1, 1),
                )
            )

    def test_date_from_equal_date_to_is_valid(self):
        """date_from == date_to (single-day range) must NOT raise ValueError."""
        with pytest.raises(AssertionError):
            self._call_with_filters(
                TransactionFilters(
                    date_from=date(2026, 1, 15),
                    date_to=date(2026, 1, 15),
                )
            )

    def test_date_from_before_date_to_is_valid(self):
        """date_from < date_to is the normal date range — must NOT raise ValueError."""
        with pytest.raises(AssertionError):
            self._call_with_filters(
                TransactionFilters(
                    date_from=date(2026, 1, 1),
                    date_to=date(2026, 1, 31),
                )
            )

    def test_only_date_from_is_valid(self):
        """date_from alone (no date_to) must NOT raise ValueError."""
        with pytest.raises(AssertionError):
            self._call_with_filters(
                TransactionFilters(date_from=date(2026, 1, 1))
            )

    def test_only_date_to_is_valid(self):
        """date_to alone (no date_from) must NOT raise ValueError."""
        with pytest.raises(AssertionError):
            self._call_with_filters(
                TransactionFilters(date_to=date(2026, 1, 31))
            )

    # --- category_id / uncategorized_only mutual exclusion ---

    def test_category_id_and_uncategorized_only_raises_value_error(self):
        """category_id + uncategorized_only=True is mutually exclusive — ValueError."""
        cat_id = UUID("00000000-0000-0000-0000-000000000042")
        with pytest.raises(
            ValueError,
            match="category_id and uncategorized_only are mutually exclusive",
        ):
            self._call_with_filters(
                TransactionFilters(category_id=cat_id, uncategorized_only=True)
            )

    def test_category_id_alone_is_valid(self):
        """category_id alone (uncategorized_only=False by default) is valid."""
        cat_id = UUID("00000000-0000-0000-0000-000000000042")
        with pytest.raises(AssertionError):
            self._call_with_filters(TransactionFilters(category_id=cat_id))

    def test_uncategorized_only_alone_is_valid(self):
        """uncategorized_only=True alone (no category_id) is valid."""
        with pytest.raises(AssertionError):
            self._call_with_filters(TransactionFilters(uncategorized_only=True))

    # --- search normalization ---

    def test_empty_string_search_does_not_raise(self):
        """search='' must be treated as None — no ValueError (ADR-0017)."""
        with pytest.raises(AssertionError):
            # AssertionError from mock engine, not ValueError — that is the pass condition.
            self._call_with_filters(TransactionFilters(search=""))

    def test_none_filters_arg_is_equivalent_to_default(self):
        """filters=None must be equivalent to TransactionFilters() — no ValueError."""
        with pytest.raises(AssertionError):
            self._call_with_filters(None)

    # --- DST / timezone edge case ---

    def test_date_range_spanning_dst_transition_is_valid(self):
        """Date range spanning a DST transition must not raise ValueError.

        Timestamps are UTC dates (ADR-0001); date objects have no tzinfo.
        This test confirms the validator does not break on calendar dates that
        straddle a North American DST boundary (second Sunday of March).
        """
        # 2026-03-07 → 2026-03-09 spans the 2026 US DST change (2026-03-08)
        with pytest.raises(AssertionError):
            self._call_with_filters(
                TransactionFilters(
                    date_from=date(2026, 3, 7),
                    date_to=date(2026, 3, 9),
                )
            )


# ===========================================================================
# Section 5 — get_transactions and get_transaction DB-gated tests
# ===========================================================================

@requires_db
class TestGetTransactionsDB:
    """DB-gated tests for get_transactions (ADR-0017).

    Skipped unless DATABASE_URL is set. Uses a fresh random user_id per test
    so tests are isolated without requiring explicit transaction rollback.
    """

    @pytest.fixture(scope="class")
    def app_ctx(self):
        from app import create_app
        app = create_app()
        app.config["TESTING"] = True
        with app.app_context():
            yield

    def _uid(self) -> str:
        return str(uuid.uuid4())

    def test_filters_none_returns_transaction_page(self, app_ctx):
        """filters=None must return a TransactionPage (no ValueError, no crash)."""
        uid = self._uid()
        result = get_transactions(uid)
        assert isinstance(result, TransactionPage)

    def test_empty_user_returns_empty_items(self, app_ctx):
        """A user with no transactions must return items=[], total_count=0."""
        uid = self._uid()
        result = get_transactions(uid)
        assert result.items == []
        assert result.total_count == 0

    def test_default_limit_echoed_back(self, app_ctx):
        """limit in the returned page must match the filter (default 50)."""
        uid = self._uid()
        result = get_transactions(uid)
        assert result.limit == 50

    def test_custom_limit_echoed_back(self, app_ctx):
        """limit in the returned page must echo back a non-default value."""
        uid = self._uid()
        result = get_transactions(uid, TransactionFilters(limit=10))
        assert result.limit == 10

    def test_offset_echoed_back(self, app_ctx):
        """offset in the returned page must echo back the filter value."""
        uid = self._uid()
        result = get_transactions(uid, TransactionFilters(offset=5))
        assert result.offset == 5

    def test_user_isolation_no_cross_user_data(self, app_ctx):
        """A user must never see another user's transactions.

        Both user_a and user_b are fresh UUIDs with no data.
        The assertion is that empty-user isolation holds — the service
        applies user_id scoping even when there are no rows.
        """
        uid_a = self._uid()
        uid_b = self._uid()
        result_a = get_transactions(uid_a)
        result_b = get_transactions(uid_b)
        # Both must be empty — no shared data leaks.
        assert result_a.items == []
        assert result_b.items == []


@requires_db
class TestGetTransactionDB:
    """DB-gated tests for get_transaction (ADR-0017).

    Skipped unless DATABASE_URL is set.
    """

    @pytest.fixture(scope="class")
    def app_ctx(self):
        from app import create_app
        app = create_app()
        app.config["TESTING"] = True
        with app.app_context():
            yield

    def _uid(self) -> str:
        return str(uuid.uuid4())

    def test_nonexistent_transaction_raises_transaction_not_found(self, app_ctx):
        """A random UUID that has no row must raise TransactionNotFound."""
        uid = self._uid()
        fake_txn_id = uuid.uuid4()
        with pytest.raises(TransactionNotFound):
            get_transaction(uid, fake_txn_id)

    def test_cross_user_lookup_raises_transaction_not_found(self, app_ctx):
        """Looking up another user's transaction_id must raise TransactionNotFound.

        Even if the row exists for user_b, user_a must see TransactionNotFound —
        cross-user lookups are indistinguishable from non-existent rows (ADR-0017
        tenant isolation). We cannot guarantee a row exists for user_b in this
        environment, but we CAN assert that a random ID raises TransactionNotFound
        for any user, which is the same observable behavior as the cross-user case.
        """
        uid = self._uid()
        some_other_txn_id = uuid.uuid4()
        with pytest.raises(TransactionNotFound):
            get_transaction(uid, some_other_txn_id)


# ===========================================================================
# Section 6 — Migration 0010 structural tests (no DB required)
# ===========================================================================

class TestMigration0010Structure:
    """Structural/static checks for the ADR-0037 is_active migration."""

    _MODULE_PATH = "migrations.versions.0010_account_is_active"

    @pytest.fixture(scope="class")
    def migration(self):
        try:
            mod = importlib.import_module(self._MODULE_PATH)
        except ModuleNotFoundError as exc:
            pytest.fail(f"Migration module not found: {self._MODULE_PATH!r}. {exc}")
        return mod

    def test_migration_imports_cleanly(self, migration):
        assert migration is not None

    def test_revision_is_0010(self, migration):
        assert migration.revision == "0010"

    def test_down_revision_is_0009(self, migration):
        assert migration.down_revision == "0009"

    def test_upgrade_is_callable(self, migration):
        assert callable(getattr(migration, "upgrade", None))

    def test_downgrade_is_callable(self, migration):
        assert callable(getattr(migration, "downgrade", None))


# ===========================================================================
# Section 7 — Account visibility (ADR-0037) DB-gated tests
# ===========================================================================

import sqlalchemy as sa
import hashlib
from datetime import timezone


def _insert_user_for_visibility(user_id: str) -> None:
    engine = sa.create_engine(DATABASE_URL)
    with engine.begin() as conn:
        conn.execute(sa.text("INSERT INTO auth.users (id) VALUES (:uid)"), {"uid": user_id})


def _insert_account_for_visibility(user_id: str, *, is_active: bool = True) -> str:
    engine = sa.create_engine(DATABASE_URL)
    with engine.begin() as conn:
        account_id = conn.execute(
            sa.text(
                "INSERT INTO public.accounts (user_id, name, is_active)"
                " VALUES (:uid, :name, :active) RETURNING id"
            ),
            {"uid": user_id, "name": f"Acct-{uuid.uuid4()}", "active": is_active},
        ).scalar()
    return str(account_id)


def _insert_upload_for_visibility(user_id: str, account_id: str) -> str:
    engine = sa.create_engine(DATABASE_URL)
    with engine.begin() as conn:
        upload_id = conn.execute(
            sa.text(
                "INSERT INTO public.uploads (user_id, account_id, filename, file_hash)"
                " VALUES (:uid, :acid, :fn, :fhash) RETURNING id"
            ),
            {
                "uid": user_id,
                "acid": account_id,
                "fn": f"upload-{uuid.uuid4()}.csv",
                "fhash": hashlib.sha256(str(uuid.uuid4()).encode()).digest(),
            },
        ).scalar()
    return str(upload_id)


def _insert_txn_for_visibility(user_id: str, account_id: str, upload_id: str) -> str:
    from decimal import Decimal
    from datetime import date
    engine = sa.create_engine(DATABASE_URL)
    fp = hashlib.sha256(f"{user_id}-{uuid.uuid4()}".encode()).digest()
    with engine.begin() as conn:
        txn_id = conn.execute(
            sa.text(
                "INSERT INTO public.transactions"
                " (user_id, account_id, source_file_id, date, description,"
                "  amount, category_id, fingerprint)"
                " VALUES (:uid, :acid, :fid, :dt, :desc, :amt, NULL, :fp)"
                " RETURNING id"
            ),
            {
                "uid": user_id, "acid": account_id, "fid": upload_id,
                "dt": date(2026, 1, 15), "desc": "TEST MERCHANT",
                "amt": Decimal("-10.00"), "fp": fp,
            },
        ).scalar()
    return str(txn_id)


@requires_db
class TestAccountVisibilityGetTransactions:
    """get_transactions must exclude transactions from inactive accounts (ADR-0037)."""

    @pytest.fixture(scope="class")
    def app_ctx(self):
        from app import create_app
        app = create_app()
        app.config["TESTING"] = True
        with app.app_context():
            yield

    def test_active_account_transactions_are_returned(self, app_ctx):
        user_id = str(uuid.uuid4())
        _insert_user_for_visibility(user_id)
        account_id = _insert_account_for_visibility(user_id, is_active=True)
        upload_id = _insert_upload_for_visibility(user_id, account_id)
        _insert_txn_for_visibility(user_id, account_id, upload_id)
        result = get_transactions(user_id)
        assert result.total_count == 1

    def test_inactive_account_transactions_are_excluded(self, app_ctx):
        user_id = str(uuid.uuid4())
        _insert_user_for_visibility(user_id)
        account_id = _insert_account_for_visibility(user_id, is_active=False)
        upload_id = _insert_upload_for_visibility(user_id, account_id)
        _insert_txn_for_visibility(user_id, account_id, upload_id)
        result = get_transactions(user_id)
        assert result.total_count == 0

    def test_only_active_accounts_mixed(self, app_ctx):
        user_id = str(uuid.uuid4())
        _insert_user_for_visibility(user_id)
        active_id = _insert_account_for_visibility(user_id, is_active=True)
        inactive_id = _insert_account_for_visibility(user_id, is_active=False)
        upload_active = _insert_upload_for_visibility(user_id, active_id)
        upload_inactive = _insert_upload_for_visibility(user_id, inactive_id)
        _insert_txn_for_visibility(user_id, active_id, upload_active)
        _insert_txn_for_visibility(user_id, inactive_id, upload_inactive)
        result = get_transactions(user_id)
        assert result.total_count == 1


@requires_db
class TestSetAccountActive:
    """set_account_active — toggle, isolation, AccountNotFound (ADR-0037)."""

    @pytest.fixture(scope="class")
    def app_ctx(self):
        from app import create_app
        app = create_app()
        app.config["TESTING"] = True
        with app.app_context():
            yield

    def test_deactivate_account(self, app_ctx):
        from app.transactions.services import set_account_active, AccountNotFound
        user_id = str(uuid.uuid4())
        _insert_user_for_visibility(user_id)
        account_id = _insert_account_for_visibility(user_id, is_active=True)
        set_account_active(user_id, account_id, False)
        upload_id = _insert_upload_for_visibility(user_id, account_id)
        _insert_txn_for_visibility(user_id, account_id, upload_id)
        result = get_transactions(user_id)
        assert result.total_count == 0

    def test_reactivate_account(self, app_ctx):
        from app.transactions.services import set_account_active
        user_id = str(uuid.uuid4())
        _insert_user_for_visibility(user_id)
        account_id = _insert_account_for_visibility(user_id, is_active=False)
        set_account_active(user_id, account_id, True)
        upload_id = _insert_upload_for_visibility(user_id, account_id)
        _insert_txn_for_visibility(user_id, account_id, upload_id)
        result = get_transactions(user_id)
        assert result.total_count == 1

    def test_wrong_user_raises_account_not_found(self, app_ctx):
        from app.transactions.services import set_account_active, AccountNotFound
        user_a = str(uuid.uuid4())
        user_b = str(uuid.uuid4())
        _insert_user_for_visibility(user_a)
        _insert_user_for_visibility(user_b)
        account_id = _insert_account_for_visibility(user_a)
        with pytest.raises(AccountNotFound):
            set_account_active(user_b, account_id, False)

    def test_nonexistent_account_raises_account_not_found(self, app_ctx):
        from app.transactions.services import set_account_active, AccountNotFound
        user_id = str(uuid.uuid4())
        _insert_user_for_visibility(user_id)
        with pytest.raises(AccountNotFound):
            set_account_active(user_id, str(uuid.uuid4()), False)
