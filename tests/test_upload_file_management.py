"""Contract tests for upload file management — service and routes (ADR-0021).

Contract source: ADR-0021 — Upload File Management Route Ownership.

Two surfaces under test:

1. Service functions (DB-gated, skipped without DATABASE_URL):
     get_uploads   — scoping, ordering, field correctness
     delete_upload — cascade, UploadNotFound, cross-user isolation

2. Route handlers (unit, mocked service, no DATABASE_URL required):
     GET  /files
     POST /files/<upload_id>/delete
"""

from __future__ import annotations

import dataclasses
import hashlib
import os
import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# DB-gated skip marker
# ---------------------------------------------------------------------------

DATABASE_URL = os.environ.get("DATABASE_URL")

requires_db = pytest.mark.skipif(
    not DATABASE_URL,
    reason="DATABASE_URL must be set to run DB-gated upload file management tests",
)

# ---------------------------------------------------------------------------
# Public API imports
# ---------------------------------------------------------------------------

from app.transactions.services import (
    Upload,
    UploadNotFound,
    delete_upload,
    get_uploads,
)

# ---------------------------------------------------------------------------
# Shared mock data for route tests
# ---------------------------------------------------------------------------

_USER_ID = "00000000-0000-0000-0000-000000000001"

_UPLOAD_1 = Upload(
    id=uuid.UUID("00000000-0000-0000-0000-000000000010"),
    filename="jan_2026.csv",
    uploaded_at=datetime(2026, 1, 15, 10, 0, tzinfo=timezone.utc),
    transaction_count=42,
    account_name="Chequing",
)

_UPLOAD_2 = Upload(
    id=uuid.UUID("00000000-0000-0000-0000-000000000020"),
    filename="feb_2026.csv",
    uploaded_at=datetime(2026, 2, 1, 9, 0, tzinfo=timezone.utc),
    transaction_count=18,
    account_name="Chequing",
)

# ---------------------------------------------------------------------------
# Section 1 — Upload type invariants (no DB required)
# ---------------------------------------------------------------------------


class TestUploadType:
    """Upload must be a frozen dataclass with the correct fields (ADR-0021 public API)."""

    def test_is_frozen_dataclass(self):
        assert dataclasses.is_dataclass(Upload)
        assert Upload.__dataclass_params__.frozen  # type: ignore[attr-defined]

    def test_has_required_fields(self):
        field_names = {f.name for f in dataclasses.fields(Upload)}
        assert field_names == {"id", "filename", "uploaded_at", "transaction_count", "account_name"}

    def test_is_immutable(self):
        u = Upload(
            id=uuid.uuid4(),
            filename="test.csv",
            uploaded_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
            transaction_count=5,
            account_name="Chequing",
        )
        with pytest.raises((dataclasses.FrozenInstanceError, AttributeError)):
            u.transaction_count = 99  # type: ignore[misc]


class TestUploadNotFoundType:
    """UploadNotFound must be an Exception subclass (ADR-0021 public API)."""

    def test_is_exception_subclass(self):
        assert issubclass(UploadNotFound, Exception)

    def test_is_raisable_and_catchable(self):
        with pytest.raises(UploadNotFound):
            raise UploadNotFound("not found")


# ---------------------------------------------------------------------------
# Section 2 — DB-gated service tests
# ---------------------------------------------------------------------------

import sqlalchemy as sa


@pytest.fixture(scope="module")
def app_ctx():
    """Module-scoped Flask app context so service calls have current_app."""
    from app import create_app
    app = create_app()
    app.config["TESTING"] = True
    with app.app_context():
        yield


def _uid() -> str:
    """Insert a row into auth.users and return its UUID string."""
    user_id = str(uuid.uuid4())
    engine = sa.create_engine(DATABASE_URL)
    with engine.begin() as conn:
        conn.execute(
            sa.text("INSERT INTO auth.users (id) VALUES (:uid)"),
            {"uid": user_id},
        )
    return user_id


def _insert_upload(
    user_id: str,
    filename: str = "test.csv",
    uploaded_at: datetime | None = None,
) -> tuple[str, str]:
    """Insert account + upload rows, return (account_id_str, upload_id_str)."""
    engine = sa.create_engine(DATABASE_URL)
    with engine.begin() as conn:
        account_id = conn.execute(
            sa.text(
                "INSERT INTO public.accounts (user_id, name)"
                " VALUES (:uid, :name) RETURNING id"
            ),
            {"uid": user_id, "name": f"Acct-{uuid.uuid4()}"},
        ).scalar()

        ts_clause = "NOW()" if uploaded_at is None else ":uploaded_at"
        params: dict = {
            "uid": user_id,
            "acid": str(account_id),
            "fn": filename,
            "fhash": hashlib.sha256(f"{uuid.uuid4()}".encode()).digest(),
        }
        if uploaded_at is not None:
            params["uploaded_at"] = uploaded_at

        upload_id = conn.execute(
            sa.text(
                f"INSERT INTO public.uploads"
                f" (user_id, account_id, filename, file_hash, uploaded_at)"
                f" VALUES (:uid, :acid, :fn, :fhash, {ts_clause})"
                f" RETURNING id"
            ),
            params,
        ).scalar()

    return str(account_id), str(upload_id)


def _insert_transaction(user_id: str, account_id: str, upload_id: str, seq: int = 0) -> str:
    """Insert a single transaction row, return its UUID string."""
    engine = sa.create_engine(DATABASE_URL)
    fp = hashlib.sha256(f"{user_id}-{seq}-{uuid.uuid4()}".encode()).digest()
    with engine.begin() as conn:
        txn_id = conn.execute(
            sa.text(
                "INSERT INTO public.transactions"
                " (user_id, account_id, source_file_id, date, description,"
                "  amount, category_id, fingerprint)"
                " VALUES (:uid, :acid, :fid, :dt, :desc, :amt, NULL, :fp)"
                " RETURNING id"
            ),
            {
                "uid": user_id,
                "acid": account_id,
                "fid": upload_id,
                "dt": date(2026, 1, 15),
                "desc": "TEST MERCHANT",
                "amt": Decimal("-1.00"),
                "fp": fp,
            },
        ).scalar()
    return str(txn_id)


def _row_exists(table: str, row_id: str) -> bool:
    engine = sa.create_engine(DATABASE_URL)
    with engine.connect() as conn:
        count = conn.execute(
            sa.text(f"SELECT COUNT(*) FROM public.{table} WHERE id = :rid"),
            {"rid": row_id},
        ).scalar()
    return count > 0


@requires_db
class TestGetUploads:
    """get_uploads — scoping, ordering, field correctness."""

    def test_returns_empty_for_new_user(self, app_ctx):
        user_id = _uid()
        result = get_uploads(user_id)
        assert result == []

    def test_returns_upload_for_user(self, app_ctx):
        user_id = _uid()
        _, upload_id = _insert_upload(user_id, filename="myfile.csv")
        result = get_uploads(user_id)
        assert len(result) == 1
        u = result[0]
        assert str(u.id) == upload_id
        assert u.filename == "myfile.csv"
        assert u.transaction_count == 0  # no transactions linked yet
        assert isinstance(u.uploaded_at, datetime)

    def test_scoped_to_user(self, app_ctx):
        user_a = _uid()
        user_b = _uid()
        _insert_upload(user_a, filename="a.csv")
        result_b = get_uploads(user_b)
        assert result_b == [], "User B must not see user A's uploads"

    def test_ordered_most_recent_first(self, app_ctx):
        user_id = _uid()
        older_ts = datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc)
        newer_ts = datetime(2026, 2, 1, 0, 0, tzinfo=timezone.utc)
        _insert_upload(user_id, filename="older.csv", uploaded_at=older_ts)
        _insert_upload(user_id, filename="newer.csv", uploaded_at=newer_ts)
        result = get_uploads(user_id)
        assert len(result) == 2
        assert result[0].filename == "newer.csv"
        assert result[1].filename == "older.csv"


@requires_db
class TestDeleteUpload:
    """delete_upload — cascade, not-found, cross-user isolation."""

    def test_removes_upload_row(self, app_ctx):
        user_id = _uid()
        _, upload_id = _insert_upload(user_id)
        assert _row_exists("uploads", upload_id)
        delete_upload(user_id, uuid.UUID(upload_id))
        assert not _row_exists("uploads", upload_id)

    def test_cascades_to_transactions(self, app_ctx):
        user_id = _uid()
        account_id, upload_id = _insert_upload(user_id)
        txn_id = _insert_transaction(user_id, account_id, upload_id)
        assert _row_exists("transactions", txn_id)
        delete_upload(user_id, uuid.UUID(upload_id))
        assert not _row_exists("transactions", txn_id), (
            "Transactions must be cascade-deleted when their source upload is deleted"
        )

    def test_raises_upload_not_found_for_wrong_user(self, app_ctx):
        user_a = _uid()
        user_b = _uid()
        _, upload_id = _insert_upload(user_a)
        with pytest.raises(UploadNotFound):
            delete_upload(user_b, uuid.UUID(upload_id))

    def test_raises_upload_not_found_for_missing_id(self, app_ctx):
        user_id = _uid()
        random_id = uuid.uuid4()
        with pytest.raises(UploadNotFound):
            delete_upload(user_id, random_id)

    def test_upload_still_exists_after_not_found_error(self, app_ctx):
        """Attempting deletion by the wrong user must not delete the row."""
        user_a = _uid()
        user_b = _uid()
        _, upload_id = _insert_upload(user_a)
        with pytest.raises(UploadNotFound):
            delete_upload(user_b, uuid.UUID(upload_id))
        assert _row_exists("uploads", upload_id), "Row must survive a cross-user delete attempt"


# ---------------------------------------------------------------------------
# Section 3 — Route tests (unit, mocked service, no DATABASE_URL required)
# ---------------------------------------------------------------------------

_GET_UPLOADS_PATH = "app.settings.routes.get_uploads"
_DELETE_UPLOAD_PATH = "app.transactions.routes.delete_upload"


class TestFilesListRoute:
    """GET /settings/files — auth gate, template, uploads passed through."""

    def test_unauthenticated_redirects_to_login(self, client):
        response = client.get("/settings/files", follow_redirects=False)
        assert response.status_code == 302
        assert "/auth/login" in response.headers.get("Location", "")

    def test_authenticated_returns_200(self, authenticated_client):
        with patch(_GET_UPLOADS_PATH, return_value=[]):
            response = authenticated_client.get("/settings/files")
        assert response.status_code == 200

    def test_renders_files_template(self, authenticated_client):
        with patch(_GET_UPLOADS_PATH, return_value=[]):
            response = authenticated_client.get("/settings/files")
        assert b"files" in response.data.lower()

    def test_passes_uploads_to_template(self, authenticated_client):
        with patch(_GET_UPLOADS_PATH, return_value=[_UPLOAD_1, _UPLOAD_2]):
            response = authenticated_client.get("/settings/files")
        assert b"jan_2026.csv" in response.data
        assert b"feb_2026.csv" in response.data

    def test_empty_upload_list_renders_without_error(self, authenticated_client):
        with patch(_GET_UPLOADS_PATH, return_value=[]):
            response = authenticated_client.get("/settings/files")
        assert response.status_code == 200
        assert b"No files uploaded yet" in response.data


class TestFilesDeleteRoute:
    """POST /files/<upload_id>/delete — auth, UUID validation, service errors, success."""

    _VALID_ID = str(_UPLOAD_1.id)

    def test_unauthenticated_redirects_to_login(self, client):
        response = client.post(f"/files/{self._VALID_ID}/delete", follow_redirects=False)
        assert response.status_code == 302
        assert "/auth/login" in response.headers.get("Location", "")

    def test_invalid_uuid_returns_400(self, authenticated_client):
        response = authenticated_client.post("/files/not-a-uuid/delete")
        assert response.status_code == 400

    def test_upload_not_found_returns_404(self, authenticated_client):
        with patch(_DELETE_UPLOAD_PATH, side_effect=UploadNotFound("gone")):
            response = authenticated_client.post(f"/files/{self._VALID_ID}/delete")
        assert response.status_code == 404

    def test_success_redirects_to_files_list(self, authenticated_client):
        with patch(_DELETE_UPLOAD_PATH, return_value=None):
            response = authenticated_client.post(
                f"/files/{self._VALID_ID}/delete",
                follow_redirects=False,
            )
        assert response.status_code == 302
        assert "/settings/files" in response.headers.get("Location", "")

    def test_success_flashes_success_message(self, authenticated_client):
        with patch(_DELETE_UPLOAD_PATH, return_value=None), \
             patch(_GET_UPLOADS_PATH, return_value=[]):
            response = authenticated_client.post(
                f"/files/{self._VALID_ID}/delete",
                follow_redirects=True,
            )
        assert b"File deleted" in response.data

    def test_calls_delete_upload_with_correct_args(self, authenticated_client):
        mock_delete = MagicMock(return_value=None)
        with patch(_DELETE_UPLOAD_PATH, mock_delete):
            authenticated_client.post(f"/files/{self._VALID_ID}/delete")
        mock_delete.assert_called_once()
        call_args = mock_delete.call_args
        # First positional arg is user_id (string), second is UUID.
        assert call_args[0][1] == uuid.UUID(self._VALID_ID)
