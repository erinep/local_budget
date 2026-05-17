import io
from unittest.mock import patch

import pytest
from conftest import make_csv


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# Category map returned by the mock so no database is needed in tests.
_MOCK_CATEGORY_MAP = {}


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
    with patch("app.transactions.routes.get_category_map", return_value=_MOCK_CATEGORY_MAP):
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
    with patch("app.transactions.routes.get_category_map", return_value=_MOCK_CATEGORY_MAP):
        data = {"file": (csv, "transactions.csv")}
        response = auth_client.post("/upload", data=data, content_type="multipart/form-data")
    assert response.status_code == 200
    # Payment should be filtered; only the coffee shows up
    assert b"CREDIT CARD PAYMENT" not in response.data


# ---------------------------------------------------------------------------
# XSS: script tags in merchant names are escaped
# ---------------------------------------------------------------------------

def test_xss_merchant_name_is_escaped(auth_client):
    csv = make_csv([
        {"date": "2026-01-15", "desc": "<script>alert(1)</script>", "amount": -10.00},
    ])
    with patch("app.transactions.routes.get_category_map", return_value=_MOCK_CATEGORY_MAP):
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
