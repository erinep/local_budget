"""Route tests for the Intelligence Layer dashboard (ADR-0039).

Tests:
  GET /intelligence/dashboard  — auth gate, 200 path, template content.
  GET /intelligence/report     — 301 permanent redirect to /intelligence/dashboard.
  GET /intelligence/widgets/monthly_totals — HTMX fragment, auth gate, 200 path.
"""

from __future__ import annotations

from decimal import Decimal
from unittest.mock import patch

import pytest

from app.intelligence.widgets.monthly_totals import MonthlyPoint, MonthlyTotalsVM

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

_PATCH_BUILD = "app.intelligence.widgets.monthly_totals.build_monthly_totals"


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
        with patch(_PATCH_BUILD, return_value=_FAKE_VM):
            response = authenticated_client.get("/intelligence/dashboard")
        assert response.status_code == 200

    def test_response_contains_dashboard_content(self, authenticated_client):
        with patch(_PATCH_BUILD, return_value=_FAKE_VM):
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
