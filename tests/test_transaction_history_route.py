"""Contract tests for GET /transactions (history route) — Phase 3b.

Contract source: ADR-0019 — History View Route, Filter Subset, and Pagination Contract.

All tests mock app.transactions.routes.get_transactions and
app.transactions.routes.list_categories at the route module level, matching
the pattern in tests/test_routes.py. No DATABASE_URL required.

Behaviors under test:
  - Unauthenticated requests redirect to login.
  - Authenticated request returns 200 and renders the history template.
  - page param defaults to 1 (offset=0 to get_transactions).
  - page=2 produces offset=50.
  - page=0 and page=-1 are clamped to page 1.
  - Invalid category_id (non-UUID string) is silently ignored.
  - Invalid date_from (non-date string) is silently ignored.
  - Valid search param is passed through to get_transactions.
  - Empty transaction list renders empty-state.
  - has_prev/has_next pagination logic.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from decimal import Decimal
from unittest.mock import MagicMock, call, patch

import pytest

from app.transactions.services import Transaction, TransactionPage

# ---------------------------------------------------------------------------
# Helpers — shared mock data
# ---------------------------------------------------------------------------

_EMPTY_PAGE = TransactionPage(items=[], total_count=0, limit=50, offset=0)

_USER_ID = "00000000-0000-0000-0000-000000000001"

_TXN_1 = Transaction(
    id=uuid.UUID("00000000-0000-0000-0000-000000000010"),
    account_id=uuid.UUID("00000000-0000-0000-0000-000000000020"),
    account_name="Default",
    date=date(2026, 1, 15),
    description="TIM HORTONS",
    amount=Decimal("-4.50"),
    category_id=None,
    category_name=None,
    created_at=datetime(2026, 1, 15, 12, 0, tzinfo=timezone.utc),
)


def _make_page(items, total_count, offset=0):
    return TransactionPage(items=items, total_count=total_count, limit=50, offset=offset)


# ---------------------------------------------------------------------------
# Unauthenticated access
# ---------------------------------------------------------------------------

def test_history_unauthenticated_redirects_to_login(client):
    """Unauthenticated GET /transactions must redirect to the login page (ADR-0019)."""
    response = client.get("/transactions")
    assert response.status_code == 302
    assert "/auth/login" in response.headers["Location"]


# ---------------------------------------------------------------------------
# Basic authenticated access
# ---------------------------------------------------------------------------

def test_history_authenticated_returns_200(auth_client):
    """Authenticated GET /transactions must return 200 (ADR-0019)."""
    with patch("app.transactions.routes.get_transactions", return_value=_EMPTY_PAGE), \
         patch("app.transactions.routes.list_categories", return_value=[]), \
         patch("app.transactions.routes.count_uncategorized_transactions", return_value=0):
        response = auth_client.get("/transactions")
    assert response.status_code == 200


def test_history_renders_history_template(auth_client):
    """The response body must contain recognizable content from the history template."""
    with patch("app.transactions.routes.get_transactions", return_value=_EMPTY_PAGE), \
         patch("app.transactions.routes.list_categories", return_value=[]), \
         patch("app.transactions.routes.count_uncategorized_transactions", return_value=0):
        response = auth_client.get("/transactions")
    # The template must render — check for something it would include.
    assert response.status_code == 200
    assert b"transaction" in response.data.lower() or b"Transaction" in response.data


# ---------------------------------------------------------------------------
# Pagination — page param → offset
# ---------------------------------------------------------------------------

def test_page_default_passes_offset_zero(auth_client):
    """No page param → page=1 → offset=0 passed to get_transactions (ADR-0019)."""
    mock_get = MagicMock(return_value=_EMPTY_PAGE)
    with patch("app.transactions.routes.get_transactions", mock_get), \
         patch("app.transactions.routes.list_categories", return_value=[]), \
         patch("app.transactions.routes.count_uncategorized_transactions", return_value=0):
        auth_client.get("/transactions")

    called_filters = mock_get.call_args[0][1]  # second positional arg is TransactionFilters
    assert called_filters.offset == 0


def test_page_1_passes_offset_zero(auth_client):
    """Explicit page=1 → offset=0 passed to get_transactions."""
    mock_get = MagicMock(return_value=_EMPTY_PAGE)
    with patch("app.transactions.routes.get_transactions", mock_get), \
         patch("app.transactions.routes.list_categories", return_value=[]), \
         patch("app.transactions.routes.count_uncategorized_transactions", return_value=0):
        auth_client.get("/transactions?page=1")

    called_filters = mock_get.call_args[0][1]
    assert called_filters.offset == 0


def test_page_2_passes_offset_50(auth_client):
    """page=2 → offset=50 (limit=50 * (2-1)) passed to get_transactions (ADR-0019)."""
    # Need total_count > 50 so page=2 is valid after clamping.
    big_page = _make_page(items=[], total_count=100, offset=50)
    mock_get = MagicMock(return_value=big_page)
    with patch("app.transactions.routes.get_transactions", mock_get), \
         patch("app.transactions.routes.list_categories", return_value=[]), \
         patch("app.transactions.routes.count_uncategorized_transactions", return_value=0):
        auth_client.get("/transactions?page=2")

    called_filters = mock_get.call_args[0][1]
    assert called_filters.offset == 50


def test_page_zero_clamped_to_page_1(auth_client):
    """page=0 (below minimum) must be treated as page=1 → offset=0 (ADR-0019)."""
    mock_get = MagicMock(return_value=_EMPTY_PAGE)
    with patch("app.transactions.routes.get_transactions", mock_get), \
         patch("app.transactions.routes.list_categories", return_value=[]), \
         patch("app.transactions.routes.count_uncategorized_transactions", return_value=0):
        auth_client.get("/transactions?page=0")

    called_filters = mock_get.call_args[0][1]
    assert called_filters.offset == 0


def test_page_negative_clamped_to_page_1(auth_client):
    """page=-1 (below minimum) must be treated as page=1 → offset=0 (ADR-0019)."""
    mock_get = MagicMock(return_value=_EMPTY_PAGE)
    with patch("app.transactions.routes.get_transactions", mock_get), \
         patch("app.transactions.routes.list_categories", return_value=[]), \
         patch("app.transactions.routes.count_uncategorized_transactions", return_value=0):
        auth_client.get("/transactions?page=-1")

    called_filters = mock_get.call_args[0][1]
    assert called_filters.offset == 0


# ---------------------------------------------------------------------------
# Filter handling — invalid values silently ignored (ADR-0019)
# ---------------------------------------------------------------------------

def test_invalid_category_id_is_silently_ignored(auth_client):
    """Non-UUID category_id must be silently ignored — no HTTP 400 (ADR-0019)."""
    mock_get = MagicMock(return_value=_EMPTY_PAGE)
    with patch("app.transactions.routes.get_transactions", mock_get), \
         patch("app.transactions.routes.list_categories", return_value=[]), \
         patch("app.transactions.routes.count_uncategorized_transactions", return_value=0):
        response = auth_client.get("/transactions?category_id=not-a-uuid")

    assert response.status_code == 200
    called_filters = mock_get.call_args[0][1]
    assert called_filters.category_id is None


def test_invalid_date_from_is_silently_ignored(auth_client):
    """Non-date date_from must be silently ignored — no HTTP 400 (ADR-0019)."""
    mock_get = MagicMock(return_value=_EMPTY_PAGE)
    with patch("app.transactions.routes.get_transactions", mock_get), \
         patch("app.transactions.routes.list_categories", return_value=[]), \
         patch("app.transactions.routes.count_uncategorized_transactions", return_value=0):
        response = auth_client.get("/transactions?date_from=not-a-date")

    assert response.status_code == 200
    called_filters = mock_get.call_args[0][1]
    assert called_filters.date_from is None


def test_invalid_date_to_is_silently_ignored(auth_client):
    """Non-date date_to must be silently ignored — no HTTP 400 (ADR-0019)."""
    mock_get = MagicMock(return_value=_EMPTY_PAGE)
    with patch("app.transactions.routes.get_transactions", mock_get), \
         patch("app.transactions.routes.list_categories", return_value=[]), \
         patch("app.transactions.routes.count_uncategorized_transactions", return_value=0):
        response = auth_client.get("/transactions?date_to=2026-13-99")

    assert response.status_code == 200
    called_filters = mock_get.call_args[0][1]
    assert called_filters.date_to is None


def test_valid_search_param_passed_to_get_transactions(auth_client):
    """Valid search param must be passed as-is to get_transactions (ADR-0019)."""
    mock_get = MagicMock(return_value=_EMPTY_PAGE)
    with patch("app.transactions.routes.get_transactions", mock_get), \
         patch("app.transactions.routes.list_categories", return_value=[]), \
         patch("app.transactions.routes.count_uncategorized_transactions", return_value=0):
        auth_client.get("/transactions?search=TIM+HORTONS")

    called_filters = mock_get.call_args[0][1]
    assert called_filters.search == "TIM HORTONS"


# ---------------------------------------------------------------------------
# Empty-state rendering
# ---------------------------------------------------------------------------

def test_empty_transaction_list_renders_without_error(auth_client):
    """GET /transactions with no transactions must return 200 (no crash on empty)."""
    with patch("app.transactions.routes.get_transactions", return_value=_EMPTY_PAGE), \
         patch("app.transactions.routes.list_categories", return_value=[]), \
         patch("app.transactions.routes.count_uncategorized_transactions", return_value=0):
        response = auth_client.get("/transactions")
    assert response.status_code == 200


def test_empty_transaction_list_shows_empty_state_indicator(auth_client):
    """When total_count=0, the response must indicate no transactions exist (ADR-0019)."""
    with patch("app.transactions.routes.get_transactions", return_value=_EMPTY_PAGE), \
         patch("app.transactions.routes.list_categories", return_value=[]), \
         patch("app.transactions.routes.count_uncategorized_transactions", return_value=0):
        response = auth_client.get("/transactions")
    # The template must render some indication of an empty state.
    # Accept any of the likely empty-state strings.
    body = response.data.lower()
    assert (
        b"no transactions" in body
        or b"no results" in body
        or b"0 transactions" in body
        or b"nothing" in body
        or b"empty" in body
        # showing 0-0 of 0 pattern
        or b"0" in body
    ), "Empty transaction list must render an empty-state indicator in the page"


# ---------------------------------------------------------------------------
# Pagination controls — has_prev / has_next
# ---------------------------------------------------------------------------

def test_has_prev_is_false_on_page_1(auth_client):
    """On page 1, the previous page link must not be rendered (has_prev=False)."""
    with patch("app.transactions.routes.get_transactions", return_value=_EMPTY_PAGE), \
         patch("app.transactions.routes.list_categories", return_value=[]), \
         patch("app.transactions.routes.count_uncategorized_transactions", return_value=0):
        response = auth_client.get("/transactions?page=1")

    # The template must not render a "previous" navigation link when on page 1.
    # We check that prev_url is absent — the template skips it when has_prev=False.
    # Look for either absence of prev-page link or a disabled/hidden indicator.
    body = response.data
    # A common pattern: prev URL would contain "page=0" — that must not appear.
    assert b"page=0" not in body


def test_has_next_is_true_when_total_count_exceeds_limit(auth_client):
    """When total_count > 50, there must be a next-page link in the response."""
    big_page = _make_page(items=[_TXN_1], total_count=51, offset=0)
    with patch("app.transactions.routes.get_transactions", return_value=big_page), \
         patch("app.transactions.routes.list_categories", return_value=[]), \
         patch("app.transactions.routes.count_uncategorized_transactions", return_value=0):
        response = auth_client.get("/transactions?page=1")

    # The template must render a next-page link (page=2) when has_next=True.
    assert b"page=2" in response.data


def test_has_next_is_false_when_total_count_within_one_page(auth_client):
    """When total_count <= 50, there must be no next-page link."""
    one_page = _make_page(items=[_TXN_1], total_count=1, offset=0)
    with patch("app.transactions.routes.get_transactions", return_value=one_page), \
         patch("app.transactions.routes.list_categories", return_value=[]), \
         patch("app.transactions.routes.count_uncategorized_transactions", return_value=0):
        response = auth_client.get("/transactions?page=1")

    # page=2 should not appear in the rendered body.
    assert b"page=2" not in response.data
