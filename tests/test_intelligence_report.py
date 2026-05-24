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
from app.intelligence.widgets.category_totals import CategoryTotalItem, CategoryTotalsVM
from app.intelligence.widgets.category_profile import CategoryProfileRow, CategoryProfileVM

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
_PATCH_BUILD_CTOT = "app.intelligence.widgets.category_totals.build_category_totals"
_PATCH_BUILD_CP   = "app.intelligence.widgets.category_profile.build_category_profile"

_FAKE_CTOT_VM = CategoryTotalsVM(
    title="Category Totals",
    items=[
        CategoryTotalItem(label="Groceries", spend=400.0, is_uncategorized=False),
        CategoryTotalItem(label="Uncategorized", spend=50.0, is_uncategorized=True),
    ],
    period_months=12,
    category_amounts={
        "Groceries": {"labels": ["Superstore", "Metro", "Loblaws"], "values": [120.0, 80.0, 60.0]},
        "Uncategorized": {"labels": ["Unknown"], "values": [50.0]},
    },
)

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

_ALL_WIDGET_PATCHES = [
    (_PATCH_BUILD_CT,   _FAKE_CT_VM),
    (_PATCH_BUILD_CTOT, _FAKE_CTOT_VM),
    (_PATCH_BUILD_CP,   _FAKE_CP_VM),
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
