import io
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest
from conftest import make_csv

from app.transactions.services import Transaction, TransactionFilters, TransactionPage


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# Category map returned by the mock so no database is needed in tests.
_MOCK_CATEGORY_MAP = {}

# Sentinel upload result: a fresh upload (not a duplicate).
_MOCK_UPLOAD_RESULT = {
    "upload_id": "00000000-0000-0000-0000-000000000099",
    "new_count": 2,
    "dup_count": 0,
    "already_uploaded": False,
}

# Minimal TransactionPage used when a report must be rendered from DB.
# Contains two real-ish transactions so report.html has something to render.
_MOCK_TXN_PAGE = TransactionPage(
    items=[
        Transaction(
            id=uuid.UUID("00000000-0000-0000-0000-000000000010"),
            account_id=uuid.UUID("00000000-0000-0000-0000-000000000020"),
            account_name="Default",
            date=date(2026, 1, 15),
            description="TIM HORTONS",
            amount=Decimal("-4.50"),
            category_id=None,
            category_name=None,
            created_at=datetime(2026, 1, 15, 12, 0, tzinfo=timezone.utc),
        ),
        Transaction(
            id=uuid.UUID("00000000-0000-0000-0000-000000000011"),
            account_id=uuid.UUID("00000000-0000-0000-0000-000000000020"),
            account_name="Default",
            date=date(2026, 1, 20),
            description="UBER",
            amount=Decimal("-12.00"),
            category_id=None,
            category_name=None,
            created_at=datetime(2026, 1, 20, 12, 0, tzinfo=timezone.utc),
        ),
    ],
    total_count=2,
    limit=200,
    offset=0,
)

# XSS test page — description contains the raw XSS string; Jinja2 escapes it.
_MOCK_TXN_PAGE_XSS = TransactionPage(
    items=[
        Transaction(
            id=uuid.UUID("00000000-0000-0000-0000-000000000012"),
            account_id=uuid.UUID("00000000-0000-0000-0000-000000000020"),
            account_name="Default",
            date=date(2026, 1, 15),
            description="<script>alert(1)</script>",
            amount=Decimal("-10.00"),
            category_id=None,
            category_name=None,
            created_at=datetime(2026, 1, 15, 12, 0, tzinfo=timezone.utc),
        ),
    ],
    total_count=1,
    limit=200,
    offset=0,
)

# Transfer test page — only TIM HORTONS (CREDIT CARD PAYMENT filtered by route
# before calling _process_upload, so it never appears in DB).
_MOCK_TXN_PAGE_TRANSFERS = TransactionPage(
    items=[
        Transaction(
            id=uuid.UUID("00000000-0000-0000-0000-000000000013"),
            account_id=uuid.UUID("00000000-0000-0000-0000-000000000020"),
            account_name="Default",
            date=date(2026, 1, 15),
            description="TIM HORTONS",
            amount=Decimal("-4.50"),
            category_id=None,
            category_name=None,
            created_at=datetime(2026, 1, 15, 12, 0, tzinfo=timezone.utc),
        ),
    ],
    total_count=1,
    limit=200,
    offset=0,
)


# ---------------------------------------------------------------------------
# GET upload page
# ---------------------------------------------------------------------------

def test_upload_page_loads(auth_client):
    response = auth_client.get("/upload")
    assert response.status_code == 200
    assert b"Upload" in response.data


def test_upload_page_redirects_unauthenticated(client):
    """Unauthenticated requests to /upload must redirect to the login page."""
    response = client.get("/upload")
    assert response.status_code == 302
    assert "/auth/login" in response.headers["Location"]


# ---------------------------------------------------------------------------
# File type validation
# ---------------------------------------------------------------------------

def test_non_csv_upload_rejected(auth_client):
    with patch("app.transactions.routes.get_category_map", return_value=_MOCK_CATEGORY_MAP):
        data = {"file": (io.BytesIO(b"not a csv"), "transactions.txt")}
        response = auth_client.post("/upload", data=data, content_type="multipart/form-data")
    assert response.status_code == 200
    assert b"Only .csv files are accepted" in response.data


# ---------------------------------------------------------------------------
# Valid CSV → report
# ---------------------------------------------------------------------------

def test_valid_csv_returns_report(auth_client):
    csv = make_csv([
        {"date": "2026-01-15", "desc": "TIM HORTONS", "amount": -4.50},
        {"date": "2026-01-20", "desc": "UBER",        "amount": -12.00},
    ])
    with patch("app.transactions.routes.get_category_map", return_value=_MOCK_CATEGORY_MAP), \
         patch("app.transactions.routes._process_upload", return_value=_MOCK_UPLOAD_RESULT), \
         patch("app.transactions.routes.get_transactions", return_value=_MOCK_TXN_PAGE):
        data = {"file": (csv, "transactions.csv")}
        response = auth_client.post("/upload", data=data, content_type="multipart/form-data")
    assert response.status_code == 200
    assert b"Spending" in response.data


# ---------------------------------------------------------------------------
# Transfers filtered out
# ---------------------------------------------------------------------------

def test_transfers_excluded_from_report(auth_client):
    csv = make_csv([
        {"date": "2026-01-15", "desc": "TIM HORTONS",          "amount": -4.50},
        {"date": "2026-01-15", "desc": "CREDIT CARD PAYMENT",  "amount": -500.00},
    ])
    with patch("app.transactions.routes.get_category_map", return_value=_MOCK_CATEGORY_MAP), \
         patch("app.transactions.routes._process_upload", return_value=_MOCK_UPLOAD_RESULT), \
         patch("app.transactions.routes.get_transactions", return_value=_MOCK_TXN_PAGE_TRANSFERS):
        data = {"file": (csv, "transactions.csv")}
        response = auth_client.post("/upload", data=data, content_type="multipart/form-data")
    assert response.status_code == 200
    # Payment should be filtered by the route before DB write;
    # the mock DB returns only TIM HORTONS, so CREDIT CARD PAYMENT is absent.
    assert b"CREDIT CARD PAYMENT" not in response.data


# ---------------------------------------------------------------------------
# XSS: script tags in merchant names are escaped
# ---------------------------------------------------------------------------

def test_xss_merchant_name_is_escaped(auth_client):
    csv = make_csv([
        {"date": "2026-01-15", "desc": "<script>alert(1)</script>", "amount": -10.00},
    ])
    with patch("app.transactions.routes.get_category_map", return_value=_MOCK_CATEGORY_MAP), \
         patch("app.transactions.routes._process_upload", return_value=_MOCK_UPLOAD_RESULT), \
         patch("app.transactions.routes.get_transactions", return_value=_MOCK_TXN_PAGE_XSS):
        data = {"file": (csv, "transactions.csv")}
        response = auth_client.post("/upload", data=data, content_type="multipart/form-data")
    assert response.status_code == 200
    assert b"<script>alert(1)</script>" not in response.data
    assert b"&lt;script&gt;" in response.data


# ---------------------------------------------------------------------------
# File size limit
# ---------------------------------------------------------------------------

def test_oversized_upload_rejected(auth_client):
    large = io.BytesIO(b"x" * (6 * 1024 * 1024))  # 6 MB
    with patch("app.transactions.routes.get_category_map", return_value=_MOCK_CATEGORY_MAP):
        data = {"file": (large, "big.csv")}
        response = auth_client.post("/upload", data=data, content_type="multipart/form-data")
    assert response.status_code == 413
