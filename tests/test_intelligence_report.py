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

from app.intelligence.widgets.category_trends import CategoryTrendsVM
from app.intelligence.widgets.category_profile import CategoryProfileRow, CategoryProfileVM
from app.intelligence.widgets.category_radar import CategoryRadarVM, RadarMonthData, RadarTransaction
from app.intelligence.widgets.category_movers import CategoryMoversVM, MoverItem

# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

_USER_ID = "00000000-0000-0000-0000-000000000001"

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
_PATCH_BUILD_CP   = "app.intelligence.widgets.category_profile.build_category_profile"
_PATCH_BUILD_CR   = "app.intelligence.widgets.category_radar.build_category_radar"
_PATCH_BUILD_CM   = "app.intelligence.widgets.category_movers.build_category_movers"

_FAKE_CP_VM = CategoryProfileVM(
    title="Category Profile",
    rows=[
        CategoryProfileRow(label="Groceries", count=12, total=400.0, mean=33.33,
                           std_dev=5.0, cv=0.15, consistency="Consistent", is_uncategorized=False),
        CategoryProfileRow(label="Transportation", count=8, total=320.0, mean=40.0,
                           std_dev=55.0, cv=1.38, consistency="Irregular", is_uncategorized=False),
    ],
    period_months=12,
    total_txns=100,
    categorized_count=87,
    uncategorized_count=13,
    pct_categorized=87.0,
    consistent_count=1,
    mixed_count=0,
    irregular_count=1,
    total_spend=720.0,
    categorized_spend=400.0,
    uncategorized_spend=320.0,
    pct_spend_categorized=55.6,
)

_FAKE_RADAR_TXN = RadarTransaction(description="Grocery Run", category_name="Groceries", amount=120.0, is_outlier=False)

def _radar_month(label, data, is_current):
    return RadarMonthData(label=label, data=data, is_current=is_current,
                          total=sum(data), top_transactions=[_FAKE_RADAR_TXN])

_FAKE_CR_VM = CategoryRadarVM(
    title="Category Radar",
    labels=["Groceries", "Dining", "Transport"],
    months=[
        _radar_month("May (MTD)", [300.0, 80.0, 50.0], True),
        _radar_month("Apr",       [350.0, 95.0, 60.0], False),
        _radar_month("Mar",       [320.0, 90.0, 55.0], False),
        _radar_month("Feb",       [310.0, 85.0, 52.0], False),
        _radar_month("Jan",       [330.0, 92.0, 58.0], False),
        _radar_month("Dec",       [400.0, 120.0, 65.0], False),
        _radar_month("Nov",       [360.0, 100.0, 61.0], False),
        _radar_month("Oct",       [340.0, 88.0, 57.0], False),
        _radar_month("Sep",       [315.0, 82.0, 53.0], False),
        _radar_month("Aug",       [325.0, 87.0, 56.0], False),
        _radar_month("Jul",       [335.0, 91.0, 59.0], False),
        _radar_month("Jun",       [345.0, 94.0, 62.0], False),
    ],
)

import datetime as _dt

_FAKE_CM_VM = CategoryMoversVM(
    title="Category Movers",
    items=[
        MoverItem(category_name="Groceries",  current=420.0, prior=335.0, delta=85.0,  pct_change=25.4),
        MoverItem(category_name="Dining",     current=180.0, prior=210.0, delta=-30.0, pct_change=-14.3),
        MoverItem(category_name="Transport",  current=95.0,  prior=80.0,  delta=15.0,  pct_change=18.8),
    ],
    current_label="April 2026",
    prior_label="March 2026",
)

_ALL_WIDGET_PATCHES = [
    (_PATCH_BUILD_CT,   _FAKE_CT_VM),
    (_PATCH_BUILD_CP,   _FAKE_CP_VM),
    (_PATCH_BUILD_CR,   _FAKE_CR_VM),
    (_PATCH_BUILD_CM,   _FAKE_CM_VM),
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
# GET /intelligence/widgets/category_trends
# ===========================================================================

class TestCategoryTrendsWidget:
    """HTMX fragment endpoint for category_trends widget."""

    def test_unauthenticated_redirects_to_login(self, client):
        response = client.get("/intelligence/widgets/category_trends", follow_redirects=False)
        assert response.status_code == 302
        assert "/auth/login" in response.headers.get("Location", "")

    def test_authenticated_returns_200(self, authenticated_client):
        with patch(_PATCH_BUILD_CT, return_value=_FAKE_CT_VM):
            response = authenticated_client.get("/intelligence/widgets/category_trends")
        assert response.status_code == 200

    def test_response_contains_chart_data(self, authenticated_client):
        with patch(_PATCH_BUILD_CT, return_value=_FAKE_CT_VM):
            response = authenticated_client.get("/intelligence/widgets/category_trends")
        assert b"chart-category-trends" in response.data

    def test_unknown_key_returns_404(self, authenticated_client):
        response = authenticated_client.get("/intelligence/widgets/nonexistent")
        assert response.status_code == 404



# ===========================================================================
# GET /intelligence/widgets/category_profile
# ===========================================================================

class TestCategoryProfileWidget:
    """HTMX fragment endpoint for category_profile widget."""

    def test_unauthenticated_redirects_to_login(self, client):
        response = client.get("/intelligence/widgets/category_profile", follow_redirects=False)
        assert response.status_code == 302
        assert "/auth/login" in response.headers.get("Location", "")

    def test_authenticated_returns_200(self, authenticated_client):
        with patch(_PATCH_BUILD_CP, return_value=_FAKE_CP_VM):
            response = authenticated_client.get("/intelligence/widgets/category_profile")
        assert response.status_code == 200

    def test_consistency_badges_in_response(self, authenticated_client):
        with patch(_PATCH_BUILD_CP, return_value=_FAKE_CP_VM):
            response = authenticated_client.get("/intelligence/widgets/category_profile")
        assert b"Consistent" in response.data
        assert b"Irregular" in response.data

    def test_health_summary_in_response(self, authenticated_client):
        with patch(_PATCH_BUILD_CP, return_value=_FAKE_CP_VM):
            response = authenticated_client.get("/intelligence/widgets/category_profile")
        assert b"87.0" in response.data
        assert b"chart-categorization-health" in response.data


# ===========================================================================
# GET /intelligence/widgets/category_radar
# ===========================================================================

class TestCategoryRadarWidget:
    """HTMX fragment endpoint for category_radar widget."""

    def test_unauthenticated_redirects_to_login(self, client):
        response = client.get("/intelligence/widgets/category_radar", follow_redirects=False)
        assert response.status_code == 302
        assert "/auth/login" in response.headers.get("Location", "")

    def test_authenticated_returns_200(self, authenticated_client):
        with patch(_PATCH_BUILD_CR, return_value=_FAKE_CR_VM):
            response = authenticated_client.get("/intelligence/widgets/category_radar")
        assert response.status_code == 200

    def test_response_contains_chart_canvas(self, authenticated_client):
        with patch(_PATCH_BUILD_CR, return_value=_FAKE_CR_VM):
            response = authenticated_client.get("/intelligence/widgets/category_radar")
        assert b"chart-category-radar" in response.data


# ===========================================================================
# GET /intelligence/widgets/category_movers
# ===========================================================================

class TestCategoryMoversWidget:
    """HTMX fragment endpoint for category_movers widget."""

    def test_unauthenticated_redirects_to_login(self, client):
        response = client.get("/intelligence/widgets/category_movers", follow_redirects=False)
        assert response.status_code == 302
        assert "/auth/login" in response.headers.get("Location", "")

    def test_authenticated_returns_200(self, authenticated_client):
        with patch(_PATCH_BUILD_CM, return_value=_FAKE_CM_VM):
            response = authenticated_client.get("/intelligence/widgets/category_movers")
        assert response.status_code == 200

    def test_response_contains_categories_and_deltas(self, authenticated_client):
        with patch(_PATCH_BUILD_CM, return_value=_FAKE_CM_VM):
            response = authenticated_client.get("/intelligence/widgets/category_movers")
        assert b"Groceries" in response.data
        assert b"85.00" in response.data
        assert b"30.00" in response.data
