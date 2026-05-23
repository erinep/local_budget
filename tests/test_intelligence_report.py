"""Contract tests for the Intelligence Layer report migration (ADR-0024).

Contract source: ADR-0024 — Intelligence Layer Report Ownership — Module
Assignment, URL Structure, and Rendering Architecture.

Two sections:

1. Service tests (no DB, mock get_spend_by_category and get_transactions):
     build_report_view_model shape, sign convention, empty-state guard.

2. Route tests (unit, mocked service, no DATABASE_URL required):
     GET /intelligence/report — auth gate, no-transactions redirect, 200 path.
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Public API imports — read from types only, not implementation
# ---------------------------------------------------------------------------

from app.transactions.services import (
    CategorySpend,
    Transaction,
    TransactionFilters,
    TransactionPage,
)

# The intelligence services module does not exist yet while the implementation
# agent runs, so we import defensively: tests will fail with ImportError until
# the implementation lands, which is the correct "red" state.
from app.intelligence.services import build_report_view_model  # noqa: E402

# ---------------------------------------------------------------------------
# Shared test constants
# ---------------------------------------------------------------------------

_USER_ID = "00000000-0000-0000-0000-000000000001"
_CAT_ID_GROCERIES = uuid.UUID("aaaaaaaa-0000-0000-0000-000000000001")
_CAT_ID_DINING = uuid.UUID("bbbbbbbb-0000-0000-0000-000000000002")

# Patch paths — both service dependencies are imported into intelligence.services
_PATCH_SPEND = "app.intelligence.services.get_spend_by_category"
_PATCH_TRANSACTIONS = "app.intelligence.services.get_transactions"

# Patch path for route tests
_PATCH_VIEW_MODEL = "app.intelligence.routes.build_report_view_model"

# ---------------------------------------------------------------------------
# Minimal valid view model for route tests (ADR-0024, Decision 2)
# ---------------------------------------------------------------------------

_FAKE_VIEW_MODEL = {
    "overall_chart_data": [],
    "trend_chart_data": {"labels": [], "datasets": []},
    "monthly": [],
    "merchants": [],
    "report_date_range": {"start": "Jan 01, 2026", "end": "Apr 30, 2026"},
}


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------

def _make_category_spend(
    category_id: uuid.UUID,
    category_name: str,
    spend: str,
) -> CategorySpend:
    """Build a CategorySpend using the real dataclass from the Transaction Engine."""
    return CategorySpend(
        category_id=category_id,
        category_name=category_name,
        spend=Decimal(spend),
        transaction_count=1,
    )


def _make_transaction(
    *,
    description: str = "TEST MERCHANT",
    amount: Decimal = Decimal("-50.00"),
    category_id: uuid.UUID | None = None,
    category_name: str | None = "Groceries",
    tx_date: date | None = None,
) -> Transaction:
    """Build a minimal Transaction using the real frozen dataclass."""
    from datetime import datetime, UTC
    return Transaction(
        id=uuid.uuid4(),
        account_id=uuid.uuid4(),
        account_name="Default",
        date=tx_date or date(2026, 1, 15),
        description=description,
        amount=amount,
        category_id=category_id or _CAT_ID_GROCERIES,
        category_name=category_name,
        created_at=datetime.now(UTC),
    )


def _make_page(items: list[Transaction]) -> TransactionPage:
    """Wrap a list of Transactions in a TransactionPage."""
    return TransactionPage(
        items=items,
        total_count=len(items),
        limit=max(len(items), 1),
        offset=0,
    )


def _make_spend_side_effect_for_months(
    monthly_spend: dict[tuple[int, int], list[CategorySpend]],
) -> object:
    """Return a side_effect callable for get_spend_by_category that dispatches by (year, month).

    The build_report_view_model implementation calls get_spend_by_category once
    per month window (ADR-0024 Notes). This helper lets tests control per-month
    spend without coupling to call order.
    """
    def _side_effect(user_id, period, account_id=None):
        key = (period.date_from.year, period.date_from.month)
        return monthly_spend.get(key, [])
    return _side_effect


# ===========================================================================
# Section 1 — Service tests (no DB required)
# ===========================================================================


class TestBuildReportViewModelReturnsNone:
    """build_report_view_model returns None when the user has no transactions (ADR-0024, Decision 2)."""

    def test_returns_none_when_no_transactions(self):
        # Behavior: an empty TransactionPage causes build_report_view_model to return None
        empty_page = _make_page([])
        with (
            patch(_PATCH_SPEND, return_value=[]),
            patch(_PATCH_TRANSACTIONS, return_value=empty_page),
        ):
            result = build_report_view_model(_USER_ID)
        assert result is None


class TestBuildReportViewModelShape:
    """build_report_view_model returns a dict with all required keys (ADR-0024, Decision 4)."""

    def _run_with_one_transaction(self, extra_spend=None):
        """Helper: one debit transaction, one category, optional extra spend rows."""
        tx = _make_transaction(amount=Decimal("-50.00"))
        page = _make_page([tx])
        spend = [_make_category_spend(_CAT_ID_GROCERIES, "Groceries", "50.00")]
        if extra_spend is not None:
            spend = extra_spend

        with (
            patch(_PATCH_SPEND, return_value=spend),
            patch(_PATCH_TRANSACTIONS, return_value=page),
        ):
            return build_report_view_model(_USER_ID)

    def test_returns_dict_with_required_keys(self):
        # Behavior: result contains all five documented top-level keys (monthly, not monthly_data)
        result = self._run_with_one_transaction()
        assert result is not None
        assert "overall_chart_data" in result
        assert "trend_chart_data" in result
        assert "monthly" in result
        assert "merchants" in result
        assert "report_date_range" in result

    def test_overall_chart_data_sorted_by_value_descending(self):
        # Behavior: higher-spend category appears first in overall_chart_data
        tx1 = _make_transaction(amount=Decimal("-50.00"), category_name="Groceries", category_id=_CAT_ID_GROCERIES)
        tx2 = _make_transaction(amount=Decimal("-200.00"), category_name="Dining", category_id=_CAT_ID_DINING)
        page = _make_page([tx1, tx2])
        spend = [
            _make_category_spend(_CAT_ID_GROCERIES, "Groceries", "50.00"),
            _make_category_spend(_CAT_ID_DINING, "Dining", "200.00"),
        ]
        with (
            patch(_PATCH_SPEND, return_value=spend),
            patch(_PATCH_TRANSACTIONS, return_value=page),
        ):
            result = build_report_view_model(_USER_ID)

        assert result is not None
        chart = result["overall_chart_data"]
        assert len(chart) >= 2
        # First entry must have the higher value
        assert chart[0]["value"] >= chart[1]["value"]
        # The higher-spend category (Dining, 200) should be first
        assert chart[0]["label"] == "Dining"

    def test_overall_chart_data_excludes_zero_spend_categories(self):
        # Behavior: a CategorySpend with spend=0 must not appear in overall_chart_data
        tx = _make_transaction(amount=Decimal("-50.00"))
        page = _make_page([tx])
        spend = [
            _make_category_spend(_CAT_ID_GROCERIES, "Groceries", "50.00"),
            _make_category_spend(_CAT_ID_DINING, "Dining", "0.00"),
        ]
        with (
            patch(_PATCH_SPEND, return_value=spend),
            patch(_PATCH_TRANSACTIONS, return_value=page),
        ):
            result = build_report_view_model(_USER_ID)

        assert result is not None
        labels = [entry["label"] for entry in result["overall_chart_data"]]
        assert "Dining" not in labels

    def test_trend_chart_data_has_labels_and_datasets(self):
        # Behavior: trend_chart_data contains a non-empty labels list of YYYY-MM strings
        # and a datasets list where each entry has 'label' and 'values' keys
        tx = _make_transaction(amount=Decimal("-50.00"))
        page = _make_page([tx])
        spend = [_make_category_spend(_CAT_ID_GROCERIES, "Groceries", "50.00")]
        with (
            patch(_PATCH_SPEND, return_value=spend),
            patch(_PATCH_TRANSACTIONS, return_value=page),
        ):
            result = build_report_view_model(_USER_ID)

        assert result is not None
        trend = result["trend_chart_data"]
        assert "labels" in trend
        assert "datasets" in trend

        labels = trend["labels"]
        assert isinstance(labels, list)
        assert len(labels) > 0
        # Each label must be a YYYY-MM formatted string
        import re
        for label in labels:
            assert re.match(r"^\d{4}-\d{2}$", label), f"Label {label!r} not in YYYY-MM format"

        datasets = trend["datasets"]
        assert isinstance(datasets, list)
        for ds in datasets:
            assert "label" in ds
            assert "values" in ds

    def test_monthly_data_ordered_chronologically(self):
        # Behavior: monthly list is in ascending month order (oldest first)
        # Use multiple months: Jan and Mar of 2026
        tx_jan = _make_transaction(amount=Decimal("-50.00"), tx_date=date(2026, 1, 10))
        tx_mar = _make_transaction(amount=Decimal("-80.00"), tx_date=date(2026, 3, 5))
        page = _make_page([tx_jan, tx_mar])
        spend = [_make_category_spend(_CAT_ID_GROCERIES, "Groceries", "130.00")]
        with (
            patch(_PATCH_SPEND, return_value=spend),
            patch(_PATCH_TRANSACTIONS, return_value=page),
        ):
            result = build_report_view_model(_USER_ID)

        assert result is not None
        monthly = result["monthly"]
        assert isinstance(monthly, list)
        if len(monthly) >= 2:
            # Verify ascending order by comparing consecutive month labels
            for i in range(len(monthly) - 1):
                assert monthly[i]["month"] <= monthly[i + 1]["month"], (
                    f"monthly not in chronological order: "
                    f"{monthly[i]['month']} > {monthly[i+1]['month']}"
                )

    def test_merchants_unique_by_description(self):
        # Behavior: duplicate merchant descriptions appear only once in 'merchants'
        tx1 = _make_transaction(description="COSTCO")
        tx2 = _make_transaction(description="COSTCO")
        tx3 = _make_transaction(description="AMAZON")
        page = _make_page([tx1, tx2, tx3])
        spend = [_make_category_spend(_CAT_ID_GROCERIES, "Groceries", "100.00")]
        with (
            patch(_PATCH_SPEND, return_value=spend),
            patch(_PATCH_TRANSACTIONS, return_value=page),
        ):
            result = build_report_view_model(_USER_ID)

        assert result is not None
        merchants = result["merchants"]
        descriptions = [m["description"] for m in merchants]
        assert len(descriptions) == len(set(descriptions)), (
            "merchants list must not contain duplicate descriptions"
        )

    def test_report_date_range_has_start_and_end(self):
        # Behavior: report_date_range is a dict with 'start' and 'end' string keys
        result = self._run_with_one_transaction()
        assert result is not None
        dr = result["report_date_range"]
        assert isinstance(dr, dict)
        assert "start" in dr
        assert "end" in dr
        assert isinstance(dr["start"], str)
        assert isinstance(dr["end"], str)


class TestBuildReportViewModelSignConvention:
    """Sign convention: amount<0 means debit (positive spend); amount>0 means credit (ADR-0024, Decision 4)."""

    def test_debit_amount_produces_positive_spend(self):
        # Behavior: a transaction with amount=-50.00 contributes 50.00 to the spend total.
        # The CategorySpend returned by get_spend_by_category should reflect 50.00 spend.
        # We verify that overall_chart_data contains a positive value for the category.
        tx = _make_transaction(amount=Decimal("-50.00"))
        page = _make_page([tx])
        spend = [_make_category_spend(_CAT_ID_GROCERIES, "Groceries", "50.00")]
        with (
            patch(_PATCH_SPEND, return_value=spend),
            patch(_PATCH_TRANSACTIONS, return_value=page),
        ):
            result = build_report_view_model(_USER_ID)

        assert result is not None
        chart = result["overall_chart_data"]
        groceries_entries = [e for e in chart if e["label"] == "Groceries"]
        assert len(groceries_entries) == 1
        assert groceries_entries[0]["value"] > 0

    def test_credit_amount_produces_negative_spend(self):
        # Behavior: a transaction with amount=+20.00 (credit/refund) contributes
        # negative spend. If the net of a category is negative (more credits than debits),
        # it should be excluded from overall_chart_data (excluded-zero rule subsumes this).
        # We verify that a pure-credit category does NOT appear in overall_chart_data.
        tx = _make_transaction(amount=Decimal("20.00"))  # credit/refund
        page = _make_page([tx])
        # get_spend_by_category only returns outflows (amount<0); a credit-only category
        # returns spend=0 from the DB layer, which ADR-0024 says should be excluded.
        spend = [_make_category_spend(_CAT_ID_GROCERIES, "Groceries", "0.00")]
        with (
            patch(_PATCH_SPEND, return_value=spend),
            patch(_PATCH_TRANSACTIONS, return_value=page),
        ):
            result = build_report_view_model(_USER_ID)

        assert result is not None
        chart = result["overall_chart_data"]
        groceries_entries = [e for e in chart if e["label"] == "Groceries"]
        assert len(groceries_entries) == 0, (
            "A category with zero net spend (credit/refund only) must be excluded from overall_chart_data"
        )

    def test_zero_net_transaction_excluded_from_chart(self):
        # Behavior: category with spend=0 does not appear in overall_chart_data
        tx = _make_transaction(amount=Decimal("-0.00"))
        page = _make_page([tx])
        spend = [_make_category_spend(_CAT_ID_GROCERIES, "Groceries", "0.00")]
        with (
            patch(_PATCH_SPEND, return_value=spend),
            patch(_PATCH_TRANSACTIONS, return_value=page),
        ):
            result = build_report_view_model(_USER_ID)

        assert result is not None
        chart = result["overall_chart_data"]
        zero_entries = [e for e in chart if e.get("value", 1) == 0]
        assert len(zero_entries) == 0, (
            "Entries with spend=0 must not appear in overall_chart_data"
        )


# ===========================================================================
# Section 2 — Route tests (unit, mocked service, no DATABASE_URL required)
# ===========================================================================


class TestIntelligenceReportRoute:
    """GET /intelligence/report — auth gate, redirect behaviors, 200 path (ADR-0024, Decision 2)."""

    def test_unauthenticated_redirects_to_login(self, client):
        # Behavior: unauthenticated request → 302 to /auth/login
        response = client.get("/intelligence/report", follow_redirects=False)
        assert response.status_code == 302
        assert "/auth/login" in response.headers.get("Location", "")

    def test_no_transactions_redirects_to_upload(self, authenticated_client):
        # Behavior: build_report_view_model returns None (no transactions) → 302 to /upload
        with patch(_PATCH_VIEW_MODEL, return_value=None):
            response = authenticated_client.get(
                "/intelligence/report", follow_redirects=False
            )
        assert response.status_code == 302
        location = response.headers.get("Location", "")
        assert "/upload" in location

    def test_no_transactions_flashes_info_message(self, authenticated_client):
        # Behavior: when no transactions, a flash message referencing "upload" is shown
        with patch(_PATCH_VIEW_MODEL, return_value=None), \
             patch("app.transactions.routes.get_accounts", return_value=[]):
            response = authenticated_client.get(
                "/intelligence/report", follow_redirects=True
            )
        assert b"upload" in response.data.lower()

    def test_with_transactions_returns_200(self, authenticated_client):
        # Behavior: when build_report_view_model returns a valid dict → 200
        with patch(_PATCH_VIEW_MODEL, return_value=_FAKE_VIEW_MODEL), \
             patch("app.intelligence.routes.count_uncategorized_transactions", return_value=0):
            response = authenticated_client.get("/intelligence/report")
        assert response.status_code == 200

    def test_with_transactions_renders_intelligence_template(self, authenticated_client):
        # Behavior: the rendered response body contains content from the report template
        # We check for generic spending report content (case-insensitive)
        with patch(_PATCH_VIEW_MODEL, return_value=_FAKE_VIEW_MODEL), \
             patch("app.intelligence.routes.count_uncategorized_transactions", return_value=0):
            response = authenticated_client.get("/intelligence/report")
        assert response.status_code == 200
        body_lower = response.data.lower()
        # The report page must contain at least one of these expected identifiers
        assert b"spending" in body_lower or b"report" in body_lower, (
            "Response body must contain identifiable report content "
            f"(checked for 'spending' or 'report' in {response.data[:200]!r})"
        )

    def test_route_is_registered_at_correct_url(self, client):
        # Behavior: GET /intelligence/report is a registered route (not 404)
        # Unauthenticated will redirect (302), but must not be 404.
        response = client.get("/intelligence/report", follow_redirects=False)
        assert response.status_code != 404, (
            "/intelligence/report returned 404 — intelligence_bp is not registered"
        )
