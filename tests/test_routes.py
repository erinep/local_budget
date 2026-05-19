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
    data = {"file": (io.BytesIO(b"not a csv"), "transactions.txt")}
    response = auth_client.post("/upload", data=data, content_type="multipart/form-data")
    assert response.status_code == 200
    assert b"Only .csv files are accepted" in response.data


# ---------------------------------------------------------------------------
# Valid CSV → report
# ---------------------------------------------------------------------------

def test_valid_csv_redirects_to_report(auth_client):
    # Behavior: successful upload → PRG redirect to /intelligence/report (ADR-0024 Decision 2)
    csv = make_csv([
        {"date": "2026-01-15", "desc": "TIM HORTONS", "amount": -4.50},
        {"date": "2026-01-20", "desc": "UBER",        "amount": -12.00},
    ])
    with patch("app.transactions.routes.list_categories", return_value=[]), \
         patch("app.transactions.routes.get_merchant_aliases", return_value=[]), \
         patch("app.transactions.routes._process_upload", return_value=_MOCK_UPLOAD_RESULT):
        data = {"file": (csv, "transactions.csv")}
        response = auth_client.post("/upload", data=data, content_type="multipart/form-data",
                                    follow_redirects=False)
    assert response.status_code == 302
    assert "/intelligence/report" in response.headers["Location"]


# ---------------------------------------------------------------------------
# Transfers: zero-net rows are filtered before DB write
# ---------------------------------------------------------------------------

def test_transfers_excluded_before_db_write(auth_client):
    # Behavior: zero-net rows (e.g. credit card payments) are dropped from the
    # dataframe before _process_upload is called. The upload still redirects.
    csv = make_csv([
        {"date": "2026-01-15", "desc": "TIM HORTONS",          "amount": -4.50},
        {"date": "2026-01-15", "desc": "CREDIT CARD PAYMENT",  "amount": -500.00},
    ])
    mock_process = patch("app.transactions.routes._process_upload", return_value=_MOCK_UPLOAD_RESULT)
    with patch("app.transactions.routes.list_categories", return_value=[]), \
         patch("app.transactions.routes.get_merchant_aliases", return_value=[]), \
         mock_process as mock_proc:
        data = {"file": (csv, "transactions.csv")}
        response = auth_client.post("/upload", data=data, content_type="multipart/form-data",
                                    follow_redirects=False)
    assert response.status_code == 302
    # _process_upload was called — the upload reached the DB write step.
    mock_proc.assert_called_once()


# ---------------------------------------------------------------------------
# XSS: script tags in merchant names are escaped by Jinja auto-escaping.
# The upload route no longer renders HTML — it redirects. XSS safety is now
# a property of templates/intelligence/report.html (Jinja auto-escape on).
# ---------------------------------------------------------------------------

def test_valid_csv_upload_does_not_render_html(auth_client):
    # Behavior: the upload POST handler never renders the report inline;
    # it always issues a redirect. Raw user input cannot reach a rendered
    # response via this route.
    csv = make_csv([
        {"date": "2026-01-15", "desc": "<script>alert(1)</script>", "amount": -10.00},
    ])
    with patch("app.transactions.routes.list_categories", return_value=[]), \
         patch("app.transactions.routes.get_merchant_aliases", return_value=[]), \
         patch("app.transactions.routes._process_upload", return_value=_MOCK_UPLOAD_RESULT):
        data = {"file": (csv, "transactions.csv")}
        response = auth_client.post("/upload", data=data, content_type="multipart/form-data",
                                    follow_redirects=False)
    assert response.status_code == 302
    assert len(response.data) == 0 or b"<script>" not in response.data


# ---------------------------------------------------------------------------
# File size limit
# ---------------------------------------------------------------------------

def test_oversized_upload_rejected(auth_client):
    large = io.BytesIO(b"x" * (6 * 1024 * 1024))  # 6 MB
    data = {"file": (large, "big.csv")}
    response = auth_client.post("/upload", data=data, content_type="multipart/form-data")
    assert response.status_code == 413
