"""Contract tests for GET/POST /transactions/<id>/edit (recategorize UI) — Phase 3b.

Contract source: ADR-0020 — Recategorize UI Flow, Edit Page, Apply-Forward Checkbox, Redirect.

All tests mock get_transaction, list_categories, and recategorize_transaction at the
route module level (same pattern as tests/test_routes.py). No DATABASE_URL required.

Behaviors under test (GET):
  - Invalid UUID in <id> returns 400.
  - Unknown transaction (TransactionNotFound) returns 404.
  - Valid transaction returns 200 and renders the edit template.

Behaviors under test (POST):
  - Recategorize-only → redirect to /transactions with flash "Transaction recategorized."
  - Apply-forward with keyword → flash "Transaction recategorized and keyword rule saved."
  - Keyword conflict → flash "Transaction recategorized. (Keyword rule already existed.)"
  - Invalid UUID in <id> → 400.
  - TransactionNotFound from service → 404.
  - CategoryNotFound from service → re-renders form with error flash.
  - Keyword write exception (partial success) → redirect with warning flash.
  - Empty category_id (uncategorized) → service called with category_id=None.
  - apply_forward checked but keyword is empty/whitespace → apply_forward_keyword=None.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest

from app.transactions.services import (
    CategoryNotFound,
    RecategorizationResult,
    Transaction,
    TransactionNotFound,
)

# ---------------------------------------------------------------------------
# Shared test fixtures / helpers
# ---------------------------------------------------------------------------

_TXN_ID = "00000000-0000-0000-0000-000000000010"
_CAT_ID = "00000000-0000-0000-0000-000000000020"

_MOCK_TXN = Transaction(
    id=uuid.UUID(_TXN_ID),
    account_id=uuid.UUID("00000000-0000-0000-0000-000000000030"),
    account_name="Default",
    date=date(2026, 1, 15),
    description="TIM HORTONS",
    amount=Decimal("-4.50"),
    category_id=None,
    category_name=None,
    created_at=datetime(2026, 1, 15, 12, 0, tzinfo=timezone.utc),
)

_MOCK_CATEGORIES = [
    {"id": _CAT_ID, "name": "Food", "keywords": ["TIM HORTONS"]},
]

_MOCK_RESULT_NO_KEYWORD = RecategorizationResult(
    transaction=_MOCK_TXN,
    keyword_written=False,
    keyword_conflict=False,
)

_MOCK_RESULT_KEYWORD_WRITTEN = RecategorizationResult(
    transaction=_MOCK_TXN,
    keyword_written=True,
    keyword_conflict=False,
)

_MOCK_RESULT_KEYWORD_CONFLICT = RecategorizationResult(
    transaction=_MOCK_TXN,
    keyword_written=False,
    keyword_conflict=True,
)

_EDIT_URL = f"/transactions/{_TXN_ID}/edit"


def _make_empty_page():
    """Return an empty TransactionPage for mocking the history redirect destination."""
    from app.transactions.services import TransactionPage
    return TransactionPage(items=[], total_count=0, limit=50, offset=0)


# ---------------------------------------------------------------------------
# GET /transactions/<id>/edit
# ---------------------------------------------------------------------------

class TestEditGet:
    """GET /transactions/<id>/edit contract (ADR-0020)."""

    def test_invalid_uuid_returns_400(self, auth_client):
        """A non-UUID <id> must return HTTP 400 (ADR-0020)."""
        response = auth_client.get("/transactions/not-a-uuid/edit")
        assert response.status_code == 400

    def test_unknown_transaction_returns_404(self, auth_client):
        """get_transaction raising TransactionNotFound must produce HTTP 404."""
        with patch("app.transactions.routes.get_transaction",
                   side_effect=TransactionNotFound("no row")), \
             patch("app.transactions.routes.list_categories", return_value=_MOCK_CATEGORIES):
            response = auth_client.get(_EDIT_URL)
        assert response.status_code == 404

    def test_valid_transaction_returns_200(self, auth_client):
        """Valid transaction renders the edit template with HTTP 200."""
        with patch("app.transactions.routes.get_transaction",
                   return_value=_MOCK_TXN), \
             patch("app.transactions.routes.list_categories",
                   return_value=_MOCK_CATEGORIES):
            response = auth_client.get(_EDIT_URL)
        assert response.status_code == 200

    def test_edit_page_contains_transaction_description(self, auth_client):
        """The edit page must render the transaction's description."""
        with patch("app.transactions.routes.get_transaction",
                   return_value=_MOCK_TXN), \
             patch("app.transactions.routes.list_categories",
                   return_value=_MOCK_CATEGORIES):
            response = auth_client.get(_EDIT_URL)
        assert b"TIM HORTONS" in response.data

    def test_unauthenticated_get_redirects_to_login(self, client):
        """Unauthenticated GET must redirect to login — auth gate applies to edit."""
        response = client.get(_EDIT_URL)
        assert response.status_code == 302
        assert "/auth/login" in response.headers["Location"]


# ---------------------------------------------------------------------------
# POST /transactions/<id>/edit — invalid URL param
# ---------------------------------------------------------------------------

class TestEditPostInvalidUrlParam:
    """POST with a bad UUID in <id> must return 400 (ADR-0020 §POST step 1)."""

    def test_invalid_uuid_returns_400(self, auth_client):
        """Non-UUID <id> on POST must return HTTP 400."""
        response = auth_client.post(
            "/transactions/not-a-uuid/edit",
            data={"category_id": _CAT_ID},
        )
        assert response.status_code == 400


# ---------------------------------------------------------------------------
# POST — recategorize-only (no apply_forward)
# ---------------------------------------------------------------------------

class TestEditPostRecategorizeOnly:
    """POST without apply_forward checked — success flash 'Transaction recategorized.' (ADR-0020)."""

    def test_redirects_to_history(self, auth_client):
        """Successful recategorize-only must redirect to /transactions."""
        with patch("app.transactions.routes.get_transaction",
                   return_value=_MOCK_TXN), \
             patch("app.transactions.routes.recategorize_transaction",
                   return_value=_MOCK_RESULT_NO_KEYWORD), \
             patch("app.transactions.routes.list_categories",
                   return_value=_MOCK_CATEGORIES):
            response = auth_client.post(
                _EDIT_URL,
                data={"category_id": _CAT_ID},
            )
        assert response.status_code == 302
        assert "/transactions" in response.headers["Location"]

    def test_success_flash_message_recategorize_only(self, auth_client):
        """Flash message must be 'Transaction recategorized.' on recategorize-only."""
        with patch("app.transactions.routes.get_transaction",
                   return_value=_MOCK_TXN), \
             patch("app.transactions.routes.recategorize_transaction",
                   return_value=_MOCK_RESULT_NO_KEYWORD), \
             patch("app.transactions.routes.list_categories",
                   return_value=_MOCK_CATEGORIES), \
             patch("app.transactions.routes.get_transactions",
                   return_value=_make_empty_page()):
            # Follow the redirect to check the flash message in the next response.
            response = auth_client.post(
                _EDIT_URL,
                data={"category_id": _CAT_ID},
                follow_redirects=True,
            )
        assert b"Transaction recategorized." in response.data


# ---------------------------------------------------------------------------
# POST — apply-forward with keyword written
# ---------------------------------------------------------------------------

class TestEditPostApplyForwardKeyword:
    """POST with apply_forward=1 and a keyword → 'Transaction recategorized and keyword rule saved.'"""

    def test_redirects_to_history(self, auth_client):
        """Keyword-write success must redirect to /transactions."""
        with patch("app.transactions.routes.get_transaction",
                   return_value=_MOCK_TXN), \
             patch("app.transactions.routes.recategorize_transaction",
                   return_value=_MOCK_RESULT_KEYWORD_WRITTEN), \
             patch("app.transactions.routes.list_categories",
                   return_value=_MOCK_CATEGORIES):
            response = auth_client.post(
                _EDIT_URL,
                data={
                    "category_id": _CAT_ID,
                    "apply_forward": "1",
                    "keyword": "TIM HORTONS",
                },
            )
        assert response.status_code == 302

    def test_keyword_written_flash_message(self, auth_client):
        """Flash must be 'Transaction recategorized and keyword rule saved.' (ADR-0020)."""
        with patch("app.transactions.routes.get_transaction",
                   return_value=_MOCK_TXN), \
             patch("app.transactions.routes.recategorize_transaction",
                   return_value=_MOCK_RESULT_KEYWORD_WRITTEN), \
             patch("app.transactions.routes.list_categories",
                   return_value=_MOCK_CATEGORIES), \
             patch("app.transactions.routes.get_transactions",
                   return_value=_make_empty_page()):
            response = auth_client.post(
                _EDIT_URL,
                data={
                    "category_id": _CAT_ID,
                    "apply_forward": "1",
                    "keyword": "TIM HORTONS",
                },
                follow_redirects=True,
            )
        assert b"Transaction recategorized and keyword rule saved." in response.data

    def test_keyword_passed_to_service(self, auth_client):
        """apply_forward_keyword passed to recategorize_transaction must be the form value."""
        mock_recategorize = MagicMock(return_value=_MOCK_RESULT_KEYWORD_WRITTEN)
        with patch("app.transactions.routes.get_transaction",
                   return_value=_MOCK_TXN), \
             patch("app.transactions.routes.recategorize_transaction",
                   mock_recategorize), \
             patch("app.transactions.routes.list_categories",
                   return_value=_MOCK_CATEGORIES):
            auth_client.post(
                _EDIT_URL,
                data={
                    "category_id": _CAT_ID,
                    "apply_forward": "1",
                    "keyword": "TIM HORTONS",
                },
            )
        _, kwargs = mock_recategorize.call_args
        assert kwargs.get("apply_forward_keyword") == "TIM HORTONS"


# ---------------------------------------------------------------------------
# POST — keyword conflict
# ---------------------------------------------------------------------------

class TestEditPostKeywordConflict:
    """POST where keyword already exists → 'Transaction recategorized. (Keyword rule already existed.)'"""

    def test_keyword_conflict_flash_message(self, auth_client):
        """Flash must be conflict message when keyword_conflict=True (ADR-0020)."""
        with patch("app.transactions.routes.get_transaction",
                   return_value=_MOCK_TXN), \
             patch("app.transactions.routes.recategorize_transaction",
                   return_value=_MOCK_RESULT_KEYWORD_CONFLICT), \
             patch("app.transactions.routes.list_categories",
                   return_value=_MOCK_CATEGORIES), \
             patch("app.transactions.routes.get_transactions",
                   return_value=_make_empty_page()):
            response = auth_client.post(
                _EDIT_URL,
                data={
                    "category_id": _CAT_ID,
                    "apply_forward": "1",
                    "keyword": "TIM HORTONS",
                },
                follow_redirects=True,
            )
        assert b"Keyword rule already existed" in response.data

    def test_keyword_conflict_still_redirects(self, auth_client):
        """Keyword conflict must still redirect to /transactions (not re-render form)."""
        with patch("app.transactions.routes.get_transaction",
                   return_value=_MOCK_TXN), \
             patch("app.transactions.routes.recategorize_transaction",
                   return_value=_MOCK_RESULT_KEYWORD_CONFLICT), \
             patch("app.transactions.routes.list_categories",
                   return_value=_MOCK_CATEGORIES):
            response = auth_client.post(
                _EDIT_URL,
                data={
                    "category_id": _CAT_ID,
                    "apply_forward": "1",
                    "keyword": "TIM HORTONS",
                },
            )
        assert response.status_code == 302
        assert "/transactions" in response.headers["Location"]


# ---------------------------------------------------------------------------
# POST — TransactionNotFound from service → 404
# ---------------------------------------------------------------------------

class TestEditPostTransactionNotFound:
    """POST where service raises TransactionNotFound must return 404 (ADR-0020)."""

    def test_transaction_not_found_returns_404(self, auth_client):
        """TransactionNotFound from recategorize_transaction must produce HTTP 404."""
        with patch("app.transactions.routes.recategorize_transaction",
                   side_effect=TransactionNotFound("gone")), \
             patch("app.transactions.routes.list_categories",
                   return_value=_MOCK_CATEGORIES):
            response = auth_client.post(
                _EDIT_URL,
                data={"category_id": _CAT_ID},
            )
        assert response.status_code == 404


# ---------------------------------------------------------------------------
# POST — CategoryNotFound from service → re-render form with error flash
# ---------------------------------------------------------------------------

class TestEditPostCategoryNotFound:
    """POST where service raises CategoryNotFound → re-renders form with error (ADR-0020)."""

    def test_category_not_found_re_renders_form(self, auth_client):
        """CategoryNotFound must re-render the edit form (not redirect)."""
        with patch("app.transactions.routes.recategorize_transaction",
                   side_effect=CategoryNotFound("no cat")), \
             patch("app.transactions.routes.get_transaction",
                   return_value=_MOCK_TXN), \
             patch("app.transactions.routes.list_categories",
                   return_value=_MOCK_CATEGORIES):
            response = auth_client.post(
                _EDIT_URL,
                data={"category_id": _CAT_ID},
            )
        # Must render the form page, not redirect.
        assert response.status_code == 200

    def test_category_not_found_shows_error_flash(self, auth_client):
        """CategoryNotFound must flash 'Category not found or no longer available.' (ADR-0020)."""
        with patch("app.transactions.routes.recategorize_transaction",
                   side_effect=CategoryNotFound("no cat")), \
             patch("app.transactions.routes.get_transaction",
                   return_value=_MOCK_TXN), \
             patch("app.transactions.routes.list_categories",
                   return_value=_MOCK_CATEGORIES):
            response = auth_client.post(
                _EDIT_URL,
                data={"category_id": _CAT_ID},
                follow_redirects=True,
            )
        assert b"Category not found or no longer available" in response.data


# ---------------------------------------------------------------------------
# POST — Keyword write exception (partial success)
# ---------------------------------------------------------------------------

class TestEditPostPartialSuccess:
    """Keyword write fails after transaction committed → warning flash + redirect (ADR-0020)."""

    def test_keyword_write_exception_redirects(self, auth_client):
        """Any non-CategoryNotFound/non-TransactionNotFound exception → redirect."""
        with patch("app.transactions.routes.recategorize_transaction",
                   side_effect=RuntimeError("DB write failed")), \
             patch("app.transactions.routes.list_categories",
                   return_value=_MOCK_CATEGORIES):
            response = auth_client.post(
                _EDIT_URL,
                data={
                    "category_id": _CAT_ID,
                    "apply_forward": "1",
                    "keyword": "TIM HORTONS",
                },
            )
        assert response.status_code == 302
        assert "/transactions" in response.headers["Location"]

    def test_keyword_write_exception_shows_warning_flash(self, auth_client):
        """Partial success must flash the warning message from ADR-0020."""
        with patch("app.transactions.routes.recategorize_transaction",
                   side_effect=RuntimeError("DB write failed")), \
             patch("app.transactions.routes.list_categories",
                   return_value=_MOCK_CATEGORIES), \
             patch("app.transactions.routes.get_transactions",
                   return_value=_make_empty_page()):
            response = auth_client.post(
                _EDIT_URL,
                data={
                    "category_id": _CAT_ID,
                    "apply_forward": "1",
                    "keyword": "TIM HORTONS",
                },
                follow_redirects=True,
            )
        assert b"keyword rule could not be saved" in response.data.lower()


# ---------------------------------------------------------------------------
# POST — Empty category_id → service called with category_id=None
# ---------------------------------------------------------------------------

class TestEditPostUncategorized:
    """POST with empty category_id string → recategorize_transaction(category_id=None) (ADR-0020)."""

    def test_empty_category_id_calls_service_with_none(self, auth_client):
        """Empty category_id form field must pass category_id=None to the service."""
        mock_recategorize = MagicMock(return_value=_MOCK_RESULT_NO_KEYWORD)
        with patch("app.transactions.routes.get_transaction",
                   return_value=_MOCK_TXN), \
             patch("app.transactions.routes.recategorize_transaction",
                   mock_recategorize), \
             patch("app.transactions.routes.list_categories",
                   return_value=_MOCK_CATEGORIES):
            auth_client.post(
                _EDIT_URL,
                data={"category_id": ""},  # empty string → uncategorized
            )
        _, kwargs = mock_recategorize.call_args
        assert kwargs.get("category_id") is None

    def test_uncategorized_redirects_to_history(self, auth_client):
        """Uncategorized submission must redirect to /transactions on success."""
        with patch("app.transactions.routes.get_transaction",
                   return_value=_MOCK_TXN), \
             patch("app.transactions.routes.recategorize_transaction",
                   return_value=_MOCK_RESULT_NO_KEYWORD), \
             patch("app.transactions.routes.list_categories",
                   return_value=_MOCK_CATEGORIES):
            response = auth_client.post(
                _EDIT_URL,
                data={"category_id": ""},
            )
        assert response.status_code == 302
        assert "/transactions" in response.headers["Location"]


# ---------------------------------------------------------------------------
# POST — apply_forward checked but keyword is empty/whitespace → no keyword written
# ---------------------------------------------------------------------------

class TestEditPostApplyForwardEmptyKeyword:
    """apply_forward=1 but keyword is empty/whitespace → apply_forward_keyword=None (ADR-0020)."""

    def test_empty_keyword_passes_none_to_service(self, auth_client):
        """Empty keyword field with apply_forward=1 → apply_forward_keyword=None."""
        mock_recategorize = MagicMock(return_value=_MOCK_RESULT_NO_KEYWORD)
        with patch("app.transactions.routes.get_transaction",
                   return_value=_MOCK_TXN), \
             patch("app.transactions.routes.recategorize_transaction",
                   mock_recategorize), \
             patch("app.transactions.routes.list_categories",
                   return_value=_MOCK_CATEGORIES):
            auth_client.post(
                _EDIT_URL,
                data={
                    "category_id": _CAT_ID,
                    "apply_forward": "1",
                    "keyword": "",  # empty
                },
            )
        _, kwargs = mock_recategorize.call_args
        assert kwargs.get("apply_forward_keyword") is None

    def test_whitespace_keyword_passes_none_to_service(self, auth_client):
        """Whitespace-only keyword with apply_forward=1 → apply_forward_keyword=None."""
        mock_recategorize = MagicMock(return_value=_MOCK_RESULT_NO_KEYWORD)
        with patch("app.transactions.routes.get_transaction",
                   return_value=_MOCK_TXN), \
             patch("app.transactions.routes.recategorize_transaction",
                   mock_recategorize), \
             patch("app.transactions.routes.list_categories",
                   return_value=_MOCK_CATEGORIES):
            auth_client.post(
                _EDIT_URL,
                data={
                    "category_id": _CAT_ID,
                    "apply_forward": "1",
                    "keyword": "   ",  # whitespace-only
                },
            )
        _, kwargs = mock_recategorize.call_args
        assert kwargs.get("apply_forward_keyword") is None

    def test_apply_forward_absent_passes_none_to_service(self, auth_client):
        """apply_forward not in form body → apply_forward_keyword=None regardless of keyword."""
        mock_recategorize = MagicMock(return_value=_MOCK_RESULT_NO_KEYWORD)
        with patch("app.transactions.routes.get_transaction",
                   return_value=_MOCK_TXN), \
             patch("app.transactions.routes.recategorize_transaction",
                   mock_recategorize), \
             patch("app.transactions.routes.list_categories",
                   return_value=_MOCK_CATEGORIES):
            auth_client.post(
                _EDIT_URL,
                data={
                    "category_id": _CAT_ID,
                    # apply_forward absent — checkbox unchecked
                    "keyword": "TIM HORTONS",
                },
            )
        _, kwargs = mock_recategorize.call_args
        assert kwargs.get("apply_forward_keyword") is None
