"""Contract tests for Transaction Engine aggregation API (ADR-0023).

Contract source: ADR-0023 — Transaction Engine Aggregation API.

Two service functions under test:

    get_spend_by_category(user_id, period, account_id=None) -> list[CategorySpend]
    get_spend_history(user_id, category_id, periods)        -> list[PeriodSpend]

And three supporting types:

    DateRange     — frozen dataclass with date_from, date_to, __post_init__ guard,
                    for_month() classmethod
    CategorySpend — frozen dataclass: category_id, category_name, spend, transaction_count
    PeriodSpend   — frozen dataclass: period, categories, total_spend

Section 1: Type invariants (no DB required).
Section 2: get_spend_by_category DB-gated service tests.
Section 3: get_spend_history DB-gated service tests.
"""

from __future__ import annotations

import calendar
import dataclasses
import hashlib
import os
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal

import pytest

# ---------------------------------------------------------------------------
# DB-gated skip marker
# ---------------------------------------------------------------------------

DATABASE_URL = os.environ.get("DATABASE_URL")

requires_db = pytest.mark.skipif(
    not DATABASE_URL,
    reason="DATABASE_URL must be set to run DB-gated aggregation service tests",
)

# ---------------------------------------------------------------------------
# Public API imports
# ---------------------------------------------------------------------------

from app.transactions.services import (
    CategorySpend,
    DateRange,
    PeriodSpend,
    get_spend_by_category,
    get_spend_history,
)


# ===========================================================================
# Section 1 — Type invariants (no DB required)
# ===========================================================================


class TestDateRange:
    """DateRange frozen dataclass invariants (ADR-0023 public API)."""

    def test_is_frozen_dataclass(self):
        # DateRange must be a frozen dataclass so callers cannot mutate it
        assert dataclasses.is_dataclass(DateRange)
        assert DateRange.__dataclass_params__.frozen  # type: ignore[attr-defined]

    def test_date_from_greater_than_date_to_raises_value_error(self):
        # __post_init__ guard: date_from > date_to is invalid (ADR-0023 error model)
        with pytest.raises(ValueError):
            DateRange(date_from=date(2026, 2, 1), date_to=date(2026, 1, 1))

    def test_date_from_equal_date_to_is_valid_single_day_range(self):
        # Single-day ranges are valid; __post_init__ must not raise
        dr = DateRange(date_from=date(2026, 1, 15), date_to=date(2026, 1, 15))
        assert dr.date_from == dr.date_to

    def test_for_month_january_2026(self):
        # for_month() factory: January has 31 days
        dr = DateRange.for_month(2026, 1)
        assert dr.date_from == date(2026, 1, 1)
        assert dr.date_to == date(2026, 1, 31)

    def test_for_month_february_2026_non_leap_year(self):
        # 2026 is not a leap year — February ends on 28
        dr = DateRange.for_month(2026, 2)
        assert dr.date_from == date(2026, 2, 1)
        assert dr.date_to == date(2026, 2, 28)

    def test_for_month_february_2028_leap_year(self):
        # 2028 IS a leap year — February ends on 29
        dr = DateRange.for_month(2028, 2)
        assert dr.date_from == date(2028, 2, 1)
        assert dr.date_to == date(2028, 2, 29)

    def test_for_month_december(self):
        # December has 31 days
        dr = DateRange.for_month(2026, 12)
        assert dr.date_from == date(2026, 12, 1)
        assert dr.date_to == date(2026, 12, 31)

    def test_is_immutable(self):
        # Frozen dataclass must reject attribute assignment
        dr = DateRange(date_from=date(2026, 1, 1), date_to=date(2026, 1, 31))
        with pytest.raises((dataclasses.FrozenInstanceError, AttributeError)):
            dr.date_from = date(2026, 2, 1)  # type: ignore[misc]


class TestCategorySpend:
    """CategorySpend frozen dataclass invariants (ADR-0023 public API)."""

    def test_is_frozen_dataclass(self):
        assert dataclasses.is_dataclass(CategorySpend)
        assert CategorySpend.__dataclass_params__.frozen  # type: ignore[attr-defined]

    def test_is_immutable(self):
        cs = CategorySpend(
            category_id=uuid.uuid4(),
            category_name="Groceries",
            spend=Decimal("42.00"),
            transaction_count=3,
        )
        with pytest.raises((dataclasses.FrozenInstanceError, AttributeError)):
            cs.spend = Decimal("0.00")  # type: ignore[misc]

    def test_has_required_fields(self):
        field_names = {f.name for f in dataclasses.fields(CategorySpend)}
        assert field_names == {"category_id", "category_name", "spend", "transaction_count"}

    def test_category_id_and_name_can_be_none_for_uncategorized(self):
        # Uncategorized rows carry category_id=None, category_name=None (ADR-0023)
        cs = CategorySpend(
            category_id=None,
            category_name=None,
            spend=Decimal("10.00"),
            transaction_count=1,
        )
        assert cs.category_id is None
        assert cs.category_name is None


class TestPeriodSpend:
    """PeriodSpend frozen dataclass invariants (ADR-0023 public API)."""

    def test_is_frozen_dataclass(self):
        assert dataclasses.is_dataclass(PeriodSpend)
        assert PeriodSpend.__dataclass_params__.frozen  # type: ignore[attr-defined]

    def test_is_immutable(self):
        ps = PeriodSpend(
            period=DateRange(date(2026, 1, 1), date(2026, 1, 31)),
            categories=[],
            total_spend=Decimal("0"),
        )
        with pytest.raises((dataclasses.FrozenInstanceError, AttributeError)):
            ps.total_spend = Decimal("99.00")  # type: ignore[misc]

    def test_has_required_fields(self):
        field_names = {f.name for f in dataclasses.fields(PeriodSpend)}
        assert field_names == {"period", "categories", "total_spend"}


# ===========================================================================
# Section 2 — get_spend_by_category DB-gated tests
# ===========================================================================

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
    """Insert a fresh row into auth.users and return its UUID string."""
    user_id = str(uuid.uuid4())
    engine = sa.create_engine(DATABASE_URL)
    with engine.begin() as conn:
        conn.execute(
            sa.text("INSERT INTO auth.users (id) VALUES (:uid)"),
            {"uid": user_id},
        )
    return user_id


def _insert_account(user_id: str) -> str:
    """Insert an account row for user_id, return account_id as string."""
    engine = sa.create_engine(DATABASE_URL)
    with engine.begin() as conn:
        account_id = conn.execute(
            sa.text(
                "INSERT INTO public.accounts (user_id, name)"
                " VALUES (:uid, :name) RETURNING id"
            ),
            {"uid": user_id, "name": f"Acct-{uuid.uuid4()}"},
        ).scalar()
    return str(account_id)


def _insert_upload(user_id: str, account_id: str) -> str:
    """Insert an upload row, return upload_id as string."""
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


def _insert_transaction(
    user_id: str,
    account_id: str,
    upload_id: str,
    *,
    amount: Decimal = Decimal("-10.00"),
    txn_date: date = date(2026, 1, 15),
    category_id: str | None = None,
    description: str = "TEST MERCHANT",
) -> str:
    """Insert a single transaction row and return its UUID string."""
    engine = sa.create_engine(DATABASE_URL)
    fp = hashlib.sha256(f"{user_id}-{uuid.uuid4()}".encode()).digest()
    with engine.begin() as conn:
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
                "acid": account_id,
                "fid": upload_id,
                "dt": txn_date,
                "desc": description,
                "amt": amount,
                "cat": category_id,
                "fp": fp,
            },
        ).scalar()
    return str(txn_id)


def _insert_category(user_id: str, name: str) -> str:
    """Insert a category row for user_id and return category_id as string."""
    engine = sa.create_engine(DATABASE_URL)
    with engine.begin() as conn:
        cat_id = conn.execute(
            sa.text(
                "INSERT INTO public.categories (user_id, name)"
                " VALUES (:uid, :name) RETURNING id"
            ),
            {"uid": user_id, "name": name},
        ).scalar()
    return str(cat_id)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_JAN_2026 = DateRange.for_month(2026, 1)
_FEB_2026 = DateRange.for_month(2026, 2)


@requires_db
class TestGetSpendByCategory:
    """get_spend_by_category — coverage of all ADR-0023 behavioral clauses."""

    def test_returns_empty_list_for_user_with_no_transactions(self, app_ctx):
        # A user with no transactions must return [] (not None, not an exception)
        user_id = _uid()
        result = get_spend_by_category(user_id, _JAN_2026)
        assert result == []

    def test_returns_empty_list_when_transactions_outside_period(self, app_ctx):
        # Transactions exist, but none fall in the requested period
        user_id = _uid()
        account_id = _insert_account(user_id)
        upload_id = _insert_upload(user_id, account_id)
        # Insert into February — query for January
        _insert_transaction(
            user_id, account_id, upload_id,
            amount=Decimal("-20.00"),
            txn_date=date(2026, 2, 10),
        )
        result = get_spend_by_category(user_id, _JAN_2026)
        assert result == []

    def test_returns_correct_spend_and_count_for_single_transaction(self, app_ctx):
        # Single debit transaction; spend must equal abs(amount), count must be 1
        user_id = _uid()
        account_id = _insert_account(user_id)
        upload_id = _insert_upload(user_id, account_id)
        _insert_transaction(
            user_id, account_id, upload_id,
            amount=Decimal("-25.50"),
            txn_date=date(2026, 1, 10),
        )
        result = get_spend_by_category(user_id, _JAN_2026)
        assert len(result) == 1
        row = result[0]
        assert row.spend == Decimal("25.50")
        assert row.transaction_count == 1

    def test_credits_are_excluded(self, app_ctx):
        # Credits (amount > 0) must never appear in spend aggregates (ADR-0023 sign convention)
        user_id = _uid()
        account_id = _insert_account(user_id)
        upload_id = _insert_upload(user_id, account_id)
        _insert_transaction(
            user_id, account_id, upload_id,
            amount=Decimal("100.00"),  # credit
            txn_date=date(2026, 1, 5),
        )
        result = get_spend_by_category(user_id, _JAN_2026)
        assert result == [], "Credits must be excluded from spend aggregates"

    def test_zero_amount_transactions_are_excluded(self, app_ctx):
        # Zero-amount transactions must be excluded (ADR-0023 sign convention)
        user_id = _uid()
        account_id = _insert_account(user_id)
        upload_id = _insert_upload(user_id, account_id)
        _insert_transaction(
            user_id, account_id, upload_id,
            amount=Decimal("0.00"),
            txn_date=date(2026, 1, 5),
        )
        result = get_spend_by_category(user_id, _JAN_2026)
        assert result == [], "Zero-amount transactions must be excluded"

    def test_uncategorized_transactions_appear_with_none_ids(self, app_ctx):
        # Transactions with category_id IS NULL appear as a row with
        # category_id=None and category_name=None (ADR-0023 uncategorized contract)
        user_id = _uid()
        account_id = _insert_account(user_id)
        upload_id = _insert_upload(user_id, account_id)
        _insert_transaction(
            user_id, account_id, upload_id,
            amount=Decimal("-15.00"),
            txn_date=date(2026, 1, 10),
            category_id=None,
        )
        result = get_spend_by_category(user_id, _JAN_2026)
        assert len(result) == 1
        row = result[0]
        assert row.category_id is None
        assert row.category_name is None
        assert row.spend == Decimal("15.00")

    def test_results_ordered_by_spend_descending(self, app_ctx):
        # ORDER BY spend DESC: the highest-spend category must be first (ADR-0023)
        user_id = _uid()
        account_id = _insert_account(user_id)
        upload_id = _insert_upload(user_id, account_id)
        cat_small = _insert_category(user_id, "Small")
        cat_large = _insert_category(user_id, "Large")
        _insert_transaction(
            user_id, account_id, upload_id,
            amount=Decimal("-5.00"),
            txn_date=date(2026, 1, 2),
            category_id=cat_small,
        )
        _insert_transaction(
            user_id, account_id, upload_id,
            amount=Decimal("-50.00"),
            txn_date=date(2026, 1, 3),
            category_id=cat_large,
        )
        result = get_spend_by_category(user_id, _JAN_2026)
        assert len(result) == 2
        assert result[0].spend >= result[1].spend, (
            "Results must be ordered spend DESC"
        )
        assert result[0].spend == Decimal("50.00")
        assert result[1].spend == Decimal("5.00")

    def test_scoped_to_user_another_users_transactions_invisible(self, app_ctx):
        # User isolation: user_b must never see user_a's transactions (ADR-0003)
        user_a = _uid()
        user_b = _uid()
        account_a = _insert_account(user_a)
        upload_a = _insert_upload(user_a, account_a)
        _insert_transaction(
            user_a, account_a, upload_a,
            amount=Decimal("-99.00"),
            txn_date=date(2026, 1, 10),
        )
        result = get_spend_by_category(user_b, _JAN_2026)
        assert result == [], "User B must not see User A's transactions"

    def test_account_id_filter_restricts_to_one_account(self, app_ctx):
        # When account_id is provided, only transactions for that account are aggregated
        user_id = _uid()
        account_a = _insert_account(user_id)
        account_b = _insert_account(user_id)
        upload_a = _insert_upload(user_id, account_a)
        upload_b = _insert_upload(user_id, account_b)
        _insert_transaction(
            user_id, account_a, upload_a,
            amount=Decimal("-30.00"),
            txn_date=date(2026, 1, 5),
        )
        _insert_transaction(
            user_id, account_b, upload_b,
            amount=Decimal("-70.00"),
            txn_date=date(2026, 1, 6),
        )
        # Filter to account_a only
        result = get_spend_by_category(user_id, _JAN_2026, account_id=uuid.UUID(account_a))
        total_spend = sum(r.spend for r in result)
        assert total_spend == Decimal("30.00"), (
            "account_id filter must restrict aggregation to the specified account"
        )

    def test_account_id_none_includes_all_accounts(self, app_ctx):
        # account_id=None means all accounts (ADR-0023 parameter table)
        user_id = _uid()
        account_a = _insert_account(user_id)
        account_b = _insert_account(user_id)
        upload_a = _insert_upload(user_id, account_a)
        upload_b = _insert_upload(user_id, account_b)
        _insert_transaction(
            user_id, account_a, upload_a,
            amount=Decimal("-10.00"),
            txn_date=date(2026, 1, 5),
        )
        _insert_transaction(
            user_id, account_b, upload_b,
            amount=Decimal("-20.00"),
            txn_date=date(2026, 1, 6),
        )
        result = get_spend_by_category(user_id, _JAN_2026, account_id=None)
        total_spend = sum(r.spend for r in result)
        assert total_spend == Decimal("30.00"), (
            "account_id=None must include all accounts"
        )

    def test_multiple_categories_each_get_own_row_with_correct_totals(self, app_ctx):
        # Multiple categories: each appears as a separate CategorySpend row with
        # correct summed spend (GROUP BY t.category_id, c.name — ADR-0023 SQL shape)
        user_id = _uid()
        account_id = _insert_account(user_id)
        upload_id = _insert_upload(user_id, account_id)
        cat_groceries = _insert_category(user_id, "Groceries")
        cat_transit = _insert_category(user_id, "Transit")
        # Two groceries transactions
        _insert_transaction(
            user_id, account_id, upload_id,
            amount=Decimal("-40.00"),
            txn_date=date(2026, 1, 3),
            category_id=cat_groceries,
        )
        _insert_transaction(
            user_id, account_id, upload_id,
            amount=Decimal("-25.00"),
            txn_date=date(2026, 1, 7),
            category_id=cat_groceries,
        )
        # One transit transaction
        _insert_transaction(
            user_id, account_id, upload_id,
            amount=Decimal("-3.50"),
            txn_date=date(2026, 1, 9),
            category_id=cat_transit,
        )
        result = get_spend_by_category(user_id, _JAN_2026)
        by_cat = {r.category_name: r for r in result}
        assert "Groceries" in by_cat
        assert "Transit" in by_cat
        assert by_cat["Groceries"].spend == Decimal("65.00")
        assert by_cat["Groceries"].transaction_count == 2
        assert by_cat["Transit"].spend == Decimal("3.50")
        assert by_cat["Transit"].transaction_count == 1

    def test_mixed_debits_and_credits_only_debits_are_summed(self, app_ctx):
        # Mixed register: credits and debits in the same period for one category.
        # Only debits (amount < 0) must contribute to spend.
        user_id = _uid()
        account_id = _insert_account(user_id)
        upload_id = _insert_upload(user_id, account_id)
        cat_id = _insert_category(user_id, "Mixed")
        _insert_transaction(
            user_id, account_id, upload_id,
            amount=Decimal("-60.00"),
            txn_date=date(2026, 1, 5),
            category_id=cat_id,
        )
        _insert_transaction(
            user_id, account_id, upload_id,
            amount=Decimal("20.00"),  # credit — must be excluded
            txn_date=date(2026, 1, 6),
            category_id=cat_id,
        )
        result = get_spend_by_category(user_id, _JAN_2026)
        assert len(result) == 1
        assert result[0].spend == Decimal("60.00"), (
            "Credits must not reduce the spend aggregate"
        )
        assert result[0].transaction_count == 1, (
            "transaction_count must count only debit rows"
        )

    def test_date_range_boundary_dates_are_inclusive(self, app_ctx):
        # Transactions on date_from and date_to (the boundary dates) must be included
        user_id = _uid()
        account_id = _insert_account(user_id)
        upload_id = _insert_upload(user_id, account_id)
        # January 1 — date_from boundary
        _insert_transaction(
            user_id, account_id, upload_id,
            amount=Decimal("-10.00"),
            txn_date=date(2026, 1, 1),
        )
        # January 31 — date_to boundary
        _insert_transaction(
            user_id, account_id, upload_id,
            amount=Decimal("-10.00"),
            txn_date=date(2026, 1, 31),
        )
        result = get_spend_by_category(user_id, _JAN_2026)
        total = sum(r.spend for r in result)
        assert total == Decimal("20.00"), (
            "Both date_from and date_to boundary dates must be included (inclusive range)"
        )

    def test_dst_spanning_range_is_handled_correctly(self, app_ctx):
        # Date range spanning the 2026 North American DST transition (2026-03-08)
        # must not cause off-by-one errors. All timestamps are UTC dates (ADR-0001).
        user_id = _uid()
        account_id = _insert_account(user_id)
        upload_id = _insert_upload(user_id, account_id)
        _insert_transaction(
            user_id, account_id, upload_id,
            amount=Decimal("-12.00"),
            txn_date=date(2026, 3, 8),  # DST transition day
        )
        dst_range = DateRange(date_from=date(2026, 3, 7), date_to=date(2026, 3, 9))
        result = get_spend_by_category(user_id, dst_range)
        total = sum(r.spend for r in result)
        assert total == Decimal("12.00"), (
            "DST transition must not cause the transaction to be missed or double-counted"
        )


# ===========================================================================
# Section 3 — get_spend_history DB-gated tests
# ===========================================================================


@requires_db
class TestGetSpendHistory:
    """get_spend_history — coverage of all ADR-0023 behavioral clauses."""

    def test_raises_value_error_when_periods_is_empty(self, app_ctx):
        # ValueError("periods must be non-empty") must fire before any DB call (ADR-0023)
        user_id = _uid()
        with pytest.raises(ValueError, match="periods"):
            get_spend_history(user_id, category_id=None, periods=[])

    def test_returns_one_period_spend_per_input_period(self, app_ctx):
        # Return list length must always equal len(periods) (ADR-0023 parameter table)
        user_id = _uid()
        periods = [_JAN_2026, _FEB_2026]
        result = get_spend_history(user_id, category_id=None, periods=periods)
        assert len(result) == 2

    def test_period_with_no_transactions_returns_zero_spend_entry(self, app_ctx):
        # A period with no matching transactions must yield PeriodSpend with
        # categories=[] and total_spend=Decimal("0") — not omitted, not an exception
        user_id = _uid()
        result = get_spend_history(user_id, category_id=None, periods=[_JAN_2026])
        assert len(result) == 1
        ps = result[0]
        assert ps.categories == []
        assert ps.total_spend == Decimal("0")

    def test_total_spend_equals_sum_of_category_spends(self, app_ctx):
        # PeriodSpend.total_spend must equal sum(cs.spend for cs in categories)
        user_id = _uid()
        account_id = _insert_account(user_id)
        upload_id = _insert_upload(user_id, account_id)
        _insert_transaction(
            user_id, account_id, upload_id,
            amount=Decimal("-15.00"),
            txn_date=date(2026, 1, 10),
            category_id=None,
        )
        _insert_transaction(
            user_id, account_id, upload_id,
            amount=Decimal("-35.00"),
            txn_date=date(2026, 1, 15),
            category_id=None,
        )
        result = get_spend_history(user_id, category_id=None, periods=[_JAN_2026])
        assert len(result) == 1
        ps = result[0]
        computed_total = sum(cs.spend for cs in ps.categories)
        assert ps.total_spend == computed_total, (
            "total_spend convenience field must equal sum of CategorySpend.spend values"
        )

    def test_category_id_none_returns_only_uncategorized_transactions(self, app_ctx):
        # category_id=None means "uncategorized" — only category_id IS NULL rows (ADR-0023)
        user_id = _uid()
        account_id = _insert_account(user_id)
        upload_id = _insert_upload(user_id, account_id)
        cat_id = _insert_category(user_id, "Groceries")
        # Categorized transaction — must NOT appear
        _insert_transaction(
            user_id, account_id, upload_id,
            amount=Decimal("-50.00"),
            txn_date=date(2026, 1, 5),
            category_id=cat_id,
        )
        # Uncategorized transaction — must appear
        _insert_transaction(
            user_id, account_id, upload_id,
            amount=Decimal("-20.00"),
            txn_date=date(2026, 1, 10),
            category_id=None,
        )
        result = get_spend_history(user_id, category_id=None, periods=[_JAN_2026])
        assert len(result) == 1
        ps = result[0]
        assert ps.total_spend == Decimal("20.00"), (
            "category_id=None must return only uncategorized transactions"
        )

    def test_valid_category_id_returns_only_that_category(self, app_ctx):
        # When a valid UUID is passed as category_id, only rows for that category
        # are returned; other categories are excluded (ADR-0023 parameter table)
        user_id = _uid()
        account_id = _insert_account(user_id)
        upload_id = _insert_upload(user_id, account_id)
        cat_a = _insert_category(user_id, "Coffee")
        cat_b = _insert_category(user_id, "Transit")
        _insert_transaction(
            user_id, account_id, upload_id,
            amount=Decimal("-4.50"),
            txn_date=date(2026, 1, 3),
            category_id=cat_a,
        )
        _insert_transaction(
            user_id, account_id, upload_id,
            amount=Decimal("-3.00"),
            txn_date=date(2026, 1, 4),
            category_id=cat_b,
        )
        result = get_spend_history(
            user_id, category_id=uuid.UUID(cat_a), periods=[_JAN_2026]
        )
        assert len(result) == 1
        ps = result[0]
        assert ps.total_spend == Decimal("4.50"), (
            "Only transactions for the specified category_id must be returned"
        )

    def test_results_are_in_input_period_order(self, app_ctx):
        # The returned list must preserve the order of the input periods list (ADR-0023)
        user_id = _uid()
        account_id = _insert_account(user_id)
        upload_id = _insert_upload(user_id, account_id)
        _insert_transaction(
            user_id, account_id, upload_id,
            amount=Decimal("-10.00"),
            txn_date=date(2026, 1, 5),
            category_id=None,
        )
        _insert_transaction(
            user_id, account_id, upload_id,
            amount=Decimal("-20.00"),
            txn_date=date(2026, 2, 5),
            category_id=None,
        )
        # Pass periods in reverse chronological order
        periods = [_FEB_2026, _JAN_2026]
        result = get_spend_history(user_id, category_id=None, periods=periods)
        assert result[0].period == _FEB_2026
        assert result[1].period == _JAN_2026
        assert result[0].total_spend == Decimal("20.00")
        assert result[1].total_spend == Decimal("10.00")

    def test_multiple_periods_with_different_transaction_sets(self, app_ctx):
        # Each period must be aggregated independently with correct per-period totals
        user_id = _uid()
        account_id = _insert_account(user_id)
        upload_id = _insert_upload(user_id, account_id)
        cat_id = _insert_category(user_id, "Fuel")
        # January transaction
        _insert_transaction(
            user_id, account_id, upload_id,
            amount=Decimal("-60.00"),
            txn_date=date(2026, 1, 10),
            category_id=cat_id,
        )
        # February transaction
        _insert_transaction(
            user_id, account_id, upload_id,
            amount=Decimal("-45.00"),
            txn_date=date(2026, 2, 15),
            category_id=cat_id,
        )
        result = get_spend_history(
            user_id, category_id=uuid.UUID(cat_id), periods=[_JAN_2026, _FEB_2026]
        )
        assert len(result) == 2
        jan_ps = result[0]
        feb_ps = result[1]
        assert jan_ps.period == _JAN_2026
        assert jan_ps.total_spend == Decimal("60.00")
        assert feb_ps.period == _FEB_2026
        assert feb_ps.total_spend == Decimal("45.00")

    def test_scoped_to_user_another_users_transactions_invisible(self, app_ctx):
        # User isolation: user_b's history query must not include user_a's transactions
        user_a = _uid()
        user_b = _uid()
        account_a = _insert_account(user_a)
        upload_a = _insert_upload(user_a, account_a)
        _insert_transaction(
            user_a, account_a, upload_a,
            amount=Decimal("-100.00"),
            txn_date=date(2026, 1, 15),
            category_id=None,
        )
        result = get_spend_history(user_b, category_id=None, periods=[_JAN_2026])
        assert len(result) == 1
        assert result[0].total_spend == Decimal("0"), (
            "User B must not see User A's transactions in spend history"
        )

    def test_single_period_list_returns_single_period_spend(self, app_ctx):
        # len(periods) == 1 → len(result) == 1 (basic cardinality contract)
        user_id = _uid()
        result = get_spend_history(user_id, category_id=None, periods=[_JAN_2026])
        assert len(result) == 1

    def test_period_spend_carries_correct_period_reference(self, app_ctx):
        # Each PeriodSpend.period must reference the corresponding input DateRange object
        user_id = _uid()
        result = get_spend_history(user_id, category_id=None, periods=[_JAN_2026, _FEB_2026])
        assert result[0].period == _JAN_2026
        assert result[1].period == _FEB_2026

    def test_credits_excluded_from_spend_history(self, app_ctx):
        # Credits in scope of the category_id filter must still be excluded (ADR-0023)
        user_id = _uid()
        account_id = _insert_account(user_id)
        upload_id = _insert_upload(user_id, account_id)
        _insert_transaction(
            user_id, account_id, upload_id,
            amount=Decimal("200.00"),  # credit — must be excluded
            txn_date=date(2026, 1, 5),
            category_id=None,
        )
        result = get_spend_history(user_id, category_id=None, periods=[_JAN_2026])
        assert result[0].total_spend == Decimal("0"), (
            "Credits must be excluded from spend history aggregates"
        )

    def test_dst_transition_period_handled_correctly(self, app_ctx):
        # Period spanning 2026 North American DST transition must not drop or duplicate
        user_id = _uid()
        account_id = _insert_account(user_id)
        upload_id = _insert_upload(user_id, account_id)
        _insert_transaction(
            user_id, account_id, upload_id,
            amount=Decimal("-8.00"),
            txn_date=date(2026, 3, 8),  # DST transition day
            category_id=None,
        )
        dst_range = DateRange(date_from=date(2026, 3, 7), date_to=date(2026, 3, 9))
        result = get_spend_history(user_id, category_id=None, periods=[dst_range])
        assert result[0].total_spend == Decimal("8.00"), (
            "DST transition must not cause spend to be missed or double-counted in history"
        )
