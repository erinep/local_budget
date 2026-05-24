"""Contract tests for the settings blueprint routes (ADR-0035, ADR-0037).

Service layer is mocked — these tests verify HTTP behaviour only.

Routes under test:
  GET  /settings/                           → 302 to /settings/profile
  GET  /settings/profile
  GET  /settings/accounts
  POST /settings/accounts                   accounts_create
  POST /settings/accounts/<id>/rename       accounts_rename
  POST /settings/accounts/<id>/delete       accounts_delete
  POST /settings/accounts/<id>/set-active   accounts_set_active  (ADR-0037)
  GET  /settings/files
  GET  /settings/security
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

_SVC = "app.settings.routes"

_VALID_ID = str(uuid.uuid4())

# ---------------------------------------------------------------------------
# Minimal Account stub matching the Account dataclass public shape
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class _Account:
    id: uuid.UUID
    name: str
    created_at: datetime
    transaction_count: int
    upload_count: int
    is_active: bool = True


_ACCOUNT_1 = _Account(
    id=uuid.UUID("00000000-0000-0000-0000-000000000001"),
    name="Chequing",
    created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    transaction_count=10,
    upload_count=2,
    is_active=True,
)

_ACCOUNT_INACTIVE = _Account(
    id=uuid.UUID("00000000-0000-0000-0000-000000000002"),
    name="Old Account",
    created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    transaction_count=5,
    upload_count=1,
    is_active=False,
)


# ===========================================================================
# Auth enforcement — every route must 302 unauthenticated clients
# ===========================================================================

class TestUnauthenticatedAccess:
    UNAUTHENTICATED_ROUTES = [
        ("GET",  "/settings/"),
        ("GET",  "/settings/profile"),
        ("GET",  "/settings/accounts"),
        ("POST", "/settings/accounts"),
        ("POST", f"/settings/accounts/{_VALID_ID}/rename"),
        ("POST", f"/settings/accounts/{_VALID_ID}/delete"),
        ("POST", f"/settings/accounts/{_VALID_ID}/set-active"),
        ("GET",  "/settings/files"),
        ("GET",  "/settings/security"),
    ]

    @pytest.mark.parametrize("method,url", UNAUTHENTICATED_ROUTES)
    def test_unauthenticated_gets_302(self, client, method, url):
        response = getattr(client, method.lower())(url, follow_redirects=False)
        assert response.status_code == 302
        assert "/auth/login" in response.headers.get("Location", "")


# ===========================================================================
# GET /settings/ — redirects to profile
# ===========================================================================

class TestSettingsIndex:
    def test_redirects_to_profile(self, authenticated_client):
        response = authenticated_client.get("/settings/", follow_redirects=False)
        assert response.status_code == 302
        assert "/settings/profile" in response.headers.get("Location", "")


# ===========================================================================
# GET /settings/accounts
# ===========================================================================

class TestAccountsList:
    def test_returns_200(self, authenticated_client):
        with patch(f"{_SVC}.get_accounts", return_value=[_ACCOUNT_1]):
            response = authenticated_client.get("/settings/accounts")
        assert response.status_code == 200

    def test_renders_account_name(self, authenticated_client):
        with patch(f"{_SVC}.get_accounts", return_value=[_ACCOUNT_1]):
            response = authenticated_client.get("/settings/accounts")
        assert b"Chequing" in response.data

    def test_inactive_account_shows_hidden_badge(self, authenticated_client):
        with patch(f"{_SVC}.get_accounts", return_value=[_ACCOUNT_INACTIVE]):
            response = authenticated_client.get("/settings/accounts")
        assert b"Hidden from reports" in response.data


# ===========================================================================
# POST /settings/accounts — create
# ===========================================================================

class TestAccountsCreate:
    def test_success_redirects_to_accounts(self, authenticated_client):
        mock_account = _ACCOUNT_1
        with patch(f"{_SVC}.create_account", return_value=mock_account):
            response = authenticated_client.post(
                "/settings/accounts",
                data={"name": "Savings"},
                follow_redirects=False,
            )
        assert response.status_code == 302
        assert "/settings/accounts" in response.headers.get("Location", "")

    def test_validation_error_renders_form(self, authenticated_client):
        with patch(f"{_SVC}.create_account", side_effect=ValueError("Name taken")), \
             patch(f"{_SVC}.get_accounts", return_value=[]):
            response = authenticated_client.post(
                "/settings/accounts",
                data={"name": ""},
            )
        assert response.status_code == 200
        assert b"Name taken" in response.data


# ===========================================================================
# POST /settings/accounts/<id>/rename
# ===========================================================================

class TestAccountsRename:
    def test_success_redirects(self, authenticated_client):
        with patch(f"{_SVC}.rename_account", return_value=None):
            response = authenticated_client.post(
                f"/settings/accounts/{_VALID_ID}/rename",
                data={"name": "New Name"},
                follow_redirects=False,
            )
        assert response.status_code == 302

    def test_not_found_returns_404(self, authenticated_client):
        from app.transactions.services import AccountNotFound
        with patch(f"{_SVC}.rename_account", side_effect=AccountNotFound("gone")):
            response = authenticated_client.post(
                f"/settings/accounts/{_VALID_ID}/rename",
                data={"name": "X"},
            )
        assert response.status_code == 404


# ===========================================================================
# POST /settings/accounts/<id>/delete
# ===========================================================================

class TestAccountsDelete:
    def test_success_redirects(self, authenticated_client):
        with patch(f"{_SVC}.delete_account", return_value=None):
            response = authenticated_client.post(
                f"/settings/accounts/{_VALID_ID}/delete",
                follow_redirects=False,
            )
        assert response.status_code == 302

    def test_not_found_returns_404(self, authenticated_client):
        from app.transactions.services import AccountNotFound
        with patch(f"{_SVC}.delete_account", side_effect=AccountNotFound("gone")):
            response = authenticated_client.post(
                f"/settings/accounts/{_VALID_ID}/delete",
            )
        assert response.status_code == 404


# ===========================================================================
# POST /settings/accounts/<id>/set-active  (ADR-0037)
# ===========================================================================

class TestAccountsSetActive:
    def test_deactivate_redirects_to_accounts(self, authenticated_client):
        with patch(f"{_SVC}.set_account_active", return_value=None):
            response = authenticated_client.post(
                f"/settings/accounts/{_VALID_ID}/set-active",
                data={"is_active": "false"},
                follow_redirects=False,
            )
        assert response.status_code == 302
        assert "/settings/accounts" in response.headers.get("Location", "")

    def test_activate_redirects_to_accounts(self, authenticated_client):
        with patch(f"{_SVC}.set_account_active", return_value=None):
            response = authenticated_client.post(
                f"/settings/accounts/{_VALID_ID}/set-active",
                data={"is_active": "true"},
                follow_redirects=False,
            )
        assert response.status_code == 302

    def test_deactivate_calls_service_with_false(self, authenticated_client):
        mock_fn = MagicMock(return_value=None)
        with patch(f"{_SVC}.set_account_active", mock_fn):
            authenticated_client.post(
                f"/settings/accounts/{_VALID_ID}/set-active",
                data={"is_active": "false"},
            )
        mock_fn.assert_called_once()
        _, _, flag = mock_fn.call_args[0]
        assert flag is False

    def test_activate_calls_service_with_true(self, authenticated_client):
        mock_fn = MagicMock(return_value=None)
        with patch(f"{_SVC}.set_account_active", mock_fn):
            authenticated_client.post(
                f"/settings/accounts/{_VALID_ID}/set-active",
                data={"is_active": "true"},
            )
        mock_fn.assert_called_once()
        _, _, flag = mock_fn.call_args[0]
        assert flag is True

    def test_not_found_returns_404(self, authenticated_client):
        from app.transactions.services import AccountNotFound
        with patch(f"{_SVC}.set_account_active", side_effect=AccountNotFound("gone")):
            response = authenticated_client.post(
                f"/settings/accounts/{_VALID_ID}/set-active",
                data={"is_active": "false"},
            )
        assert response.status_code == 404

    def test_missing_is_active_field_defaults_to_false(self, authenticated_client):
        mock_fn = MagicMock(return_value=None)
        with patch(f"{_SVC}.set_account_active", mock_fn):
            authenticated_client.post(
                f"/settings/accounts/{_VALID_ID}/set-active",
                data={},
            )
        _, _, flag = mock_fn.call_args[0]
        assert flag is False


# ===========================================================================
# GET /settings/files
# ===========================================================================

class TestSettingsFiles:
    def test_returns_200(self, authenticated_client):
        with patch(f"{_SVC}.get_uploads", return_value=[]):
            response = authenticated_client.get("/settings/files")
        assert response.status_code == 200


# ===========================================================================
# GET /settings/security
# ===========================================================================

class TestSettingsSecurity:
    def test_returns_200(self, authenticated_client):
        response = authenticated_client.get("/settings/security")
        assert response.status_code == 200
