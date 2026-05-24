"""Route tests for the Intelligence Layer dashboard (ADR-0039).

Tests:
  GET /intelligence/dashboard  — auth gate, 200 path, template content.
  GET /intelligence/report     — 301 permanent redirect to /intelligence/dashboard.
  GET /intelligence/widgets/monthly_totals — HTMX fragment, auth gate, 200 path.
  GET /intelligence/widgets/category_trends — HTMX fragment, auth gate, 200 path.
"""

from __future__ import annotations

from decimal import Decimal
from unittest.mock import patch

import pytest

from app.intelligence.widgets.monthly_totals import MonthlyPoint, MonthlyTotalsVM
from app.intelligence.widgets.category_trends import CategoryTrendsVM
from app.intelligence.widgets.categorization_health import CategorizationHealthVM
from app.intelligence.widgets.category_totals import CategoryTotalItem, CategoryTotalsVM

# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

_USER_ID = "00000000-0000-0000-0000-000000000001"

_FAKE_VM = MonthlyTotalsVM(
    title="Monthly Spending",
    points=[
        MonthlyPoint(month="2026-04", label="Apr 2026", total=Decimal("1234.56")),
        MonthlyPoint(month="2026-05", label="May 2026", total=Decimal("987.00")),
    ],
    period_months=12,
)

_PATCH_BUILD    = "app.intelligence.widgets.monthly_totals.build_monthly_totals"
_FAKE_MT_POINTS = [
    MonthlyPoint(month="2026-04", label="Apr 2026", total=Decimal("520.0")),
    MonthlyPoint(month="2026-05", label="May 2026", total=Decimal("445.0")),
]
_FAKE_MT_VM = MonthlyTotalsVM(title="Monthly Spending", points=_FAKE_MT_POINTS, period_months=12)

_FAKE_CT_VM = CategoryTrendsVM(
    title="Spending by Category",
    labels=["Apr 2026", "May 2026"],
    datasets=[
        {"label": "Groceries", "data": [400.0, 350.0]},
        {"label": "Dining", "data": [120.0, 95.0]},
    ],
    period_months=12,
)

_PATCH_BUILD_CT   = "app.intelligence.widgets.category_trends.build_category_trends"
_PATCH_BUILD_CH   = "app.intelligence.widgets.categorization_health.build_categorization_health"
_PATCH_BUILD_CTOT = "app.intelligence.widgets.category_totals.build_category_totals"

_FAKE_CH_VM = CategorizationHealthVM(total=100, categorized=87, uncategorized=13, pct_categorized=87.0)

_FAKE_CTOT_VM = CategoryTotalsVM(
    title="Category Totals",
    items=[
        CategoryTotalItem(label="Groceries", spend=400.0, is_uncategorized=False),
        CategoryTotalItem(label="Uncategorized", spend=50.0, is_uncategorized=True),
    ],
    period_months=12,
)

_ALL_WIDGET_PATCHES = [
    (_PATCH_BUILD,    _FAKE_MT_VM),
    (_PATCH_BUILD_CT, _FAKE_CT_VM),
    (_PATCH_BUILD_CH, _FAKE_CH_VM),
    (_PATCH_BUILD_CTOT, _FAKE_CTOT_VM),
]


def _patch_all_widgets():
    from contextlib import ExitStack
    stack = ExitStack()
    for path, val in _ALL_WIDGET_PATCHES:
        stack.enter_context(patch(path, return_value=val))
    return stack


# ===========================================================================
# GET /intelligence/dashboard
# ===========================================================================

class TestDashboardRoute:
    """GET /intelligence/dashboard — auth gate and 200 path."""

    def test_unauthenticated_redirects_to_login(self, client):
        response = client.get("/intelligence/dashboard", follow_redirects=False)
        assert response.status_code == 302
        assert "/auth/login" in response.headers.get("Location", "")

    def test_authenticated_returns_200(self, authenticated_client):
        with _patch_all_widgets():
            response = authenticated_client.get("/intelligence/dashboard")
        assert response.status_code == 200

    def test_response_contains_dashboard_content(self, authenticated_client):
        with _patch_all_widgets():
            response = authenticated_client.get("/intelligence/dashboard")
        assert response.status_code == 200
        body = response.data.lower()
        assert b"dashboard" in body or b"spending" in body

    def test_route_registered(self, client):
        response = client.get("/intelligence/dashboard", follow_redirects=False)
        assert response.status_code != 404


# ===========================================================================
# GET /intelligence/report  (301 redirect)
# ===========================================================================

class TestReportRedirect:
    """GET /intelligence/report must return 301 → /intelligence/dashboard."""

    def test_returns_301(self, client):
        response = client.get("/intelligence/report", follow_redirects=False)
        assert response.status_code == 301

    def test_location_points_to_dashboard(self, client):
        response = client.get("/intelligence/report", follow_redirects=False)
        assert "/intelligence/dashboard" in response.headers.get("Location", "")

    def test_follows_to_dashboard(self, client):
        # Unauthenticated follow lands at login, but the redirect chain starts at /intelligence/dashboard.
        response = client.get("/intelligence/report", follow_redirects=True)
        assert b"login" in response.data.lower() or b"dashboard" in response.data.lower()


# ===========================================================================
# GET /intelligence/widgets/monthly_totals
# ===========================================================================

class TestMonthlyTotalsWidget:
    """HTMX fragment endpoint for monthly_totals widget."""

    def test_unauthenticated_redirects_to_login(self, client):
        response = client.get("/intelligence/widgets/monthly_totals", follow_redirects=False)
        assert response.status_code == 302
        assert "/auth/login" in response.headers.get("Location", "")

    def test_authenticated_returns_200(self, authenticated_client):
        with patch(_PATCH_BUILD, return_value=_FAKE_VM):
            response = authenticated_client.get("/intelligence/widgets/monthly_totals")
        assert response.status_code == 200

    def test_unknown_key_returns_404(self, authenticated_client):
        response = authenticated_client.get("/intelligence/widgets/nonexistent")
        assert response.status_code == 404


# ===========================================================================
# GET /intelligence/widgets/category_trends
# ===========================================================================

class TestCategoryTrendsWidget:
    """HTMX fragment endpoint for category_trends widget."""

    def test_unauthenticated_redirects_to_login(self, client):
        response = client.get("/intelligence/widgets/category_trends", follow_redirects=False)
        assert response.status_code == 302
        assert "/auth/login" in response.headers.get("Location", "")

    def test_authenticated_returns_200(self, authenticated_client):
        with patch(_PATCH_BUILD, return_value=_FAKE_MT_VM), \
             patch(_PATCH_BUILD_CT, return_value=_FAKE_CT_VM):
            response = authenticated_client.get("/intelligence/widgets/category_trends")
        assert response.status_code == 200

    def test_response_contains_chart_data(self, authenticated_client):
        with patch(_PATCH_BUILD, return_value=_FAKE_MT_VM), \
             patch(_PATCH_BUILD_CT, return_value=_FAKE_CT_VM):
            response = authenticated_client.get("/intelligence/widgets/category_trends")
        assert b"chart-category-trends" in response.data


# ===========================================================================
# GET /intelligence/widgets/categorization_health
# ===========================================================================

class TestCategorizationHealthWidget:
    """HTMX fragment endpoint for categorization_health widget."""

    def test_unauthenticated_redirects_to_login(self, client):
        response = client.get("/intelligence/widgets/categorization_health", follow_redirects=False)
        assert response.status_code == 302
        assert "/auth/login" in response.headers.get("Location", "")

    def test_authenticated_returns_200(self, authenticated_client):
        with patch(_PATCH_BUILD_CH, return_value=_FAKE_CH_VM):
            response = authenticated_client.get("/intelligence/widgets/categorization_health")
        assert response.status_code == 200

    def test_pct_displayed_in_response(self, authenticated_client):
        with patch(_PATCH_BUILD_CH, return_value=_FAKE_CH_VM):
            response = authenticated_client.get("/intelligence/widgets/categorization_health")
        assert b"87.0" in response.data


# ===========================================================================
# GET /intelligence/widgets/category_totals
# ===========================================================================

class TestCategoryTotalsWidget:
    """HTMX fragment endpoint for category_totals widget."""

    def test_unauthenticated_redirects_to_login(self, client):
        response = client.get("/intelligence/widgets/category_totals", follow_redirects=False)
        assert response.status_code == 302
        assert "/auth/login" in response.headers.get("Location", "")

    def test_authenticated_returns_200(self, authenticated_client):
        with patch(_PATCH_BUILD_CTOT, return_value=_FAKE_CTOT_VM):
            response = authenticated_client.get("/intelligence/widgets/category_totals")
        assert response.status_code == 200

    def test_response_contains_chart_canvas(self, authenticated_client):
        with patch(_PATCH_BUILD_CTOT, return_value=_FAKE_CTOT_VM):
            response = authenticated_client.get("/intelligence/widgets/category_totals")
        assert b"chart-category-totals" in response.data
