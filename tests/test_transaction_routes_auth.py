"""Tests verifying that transaction routes enforce authentication.

Every route in the Transaction Engine blueprint (app/transactions/routes.py)
must redirect unauthenticated requests to /auth/login.  This is the
login_required enforcement contract from ADR-0006 applied to the transaction
surface.

These tests extend the existing route tests (test_routes.py) — they do NOT
replace them.  The existing tests use a client with CSRF disabled and no
session; the tests here verify that the absence of a session triggers a
redirect rather than serving the page.

Note: the existing test_routes.py tests will need to be updated once auth is
added to those routes (they currently test against an unauthenticated client
with CSRF disabled).  This file documents the authenticated contract; the
implementation agent must reconcile the two.
"""

import io

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_minimal_csv() -> io.BytesIO:
    content = b"Transaction Date,Description 1,CAD$\n2026-01-15,TIM HORTONS,-4.50\n"
    buf = io.BytesIO(content)
    buf.name = "transactions.csv"
    return buf


# ---------------------------------------------------------------------------
# GET / — upload/report landing page
# ---------------------------------------------------------------------------

class TestRootRouteRequiresAuth:
    def test_get_root_without_session_redirects_to_login(self, client):
        """GET / without a session must redirect to /auth/login.
        The root route is the main user-facing surface and must be protected."""
        response = client.get("/", follow_redirects=False)

        assert response.status_code in (302, 301), (
            f"Expected redirect, got {response.status_code}"
        )
        location = response.headers.get("Location", "")
        assert "/auth/login" in location, (
            f"Expected redirect to /auth/login, got Location: {location!r}"
        )

    def test_get_root_with_valid_session_is_not_redirected_to_login(
        self, authenticated_client
    ):
        """An authenticated client must NOT be redirected to /auth/login
        when accessing GET /."""
        response = authenticated_client.get("/", follow_redirects=False)
        location = response.headers.get("Location", "")
        assert "/auth/login" not in location, (
            f"Authenticated client was unexpectedly redirected to login; "
            f"Location: {location!r}"
        )


# ---------------------------------------------------------------------------
# POST /upload — CSV upload endpoint
# ---------------------------------------------------------------------------

class TestUploadRouteRequiresAuth:
    def test_post_upload_without_session_redirects_to_login(self, client):
        """POST /upload without a session must redirect to /auth/login.
        An unauthenticated upload must never be processed."""
        csv_file = make_minimal_csv()
        response = client.post(
            "/upload",
            data={"file": (csv_file, "transactions.csv")},
            content_type="multipart/form-data",
            follow_redirects=False,
        )

        assert response.status_code in (302, 301), (
            f"Expected redirect, got {response.status_code}"
        )
        location = response.headers.get("Location", "")
        assert "/auth/login" in location, (
            f"Expected redirect to /auth/login, got Location: {location!r}"
        )

    def test_post_to_root_without_session_redirects_to_login(self, client):
        """POST / (the legacy upload path) without a session must also redirect.
        This covers the case where the upload form posts to / instead of /upload."""
        csv_file = make_minimal_csv()
        response = client.post(
            "/",
            data={"file": (csv_file, "transactions.csv")},
            content_type="multipart/form-data",
            follow_redirects=False,
        )

        assert response.status_code in (302, 301), (
            f"Expected redirect, got {response.status_code}"
        )
        location = response.headers.get("Location", "")
        assert "/auth/login" in location, (
            f"Expected redirect to /auth/login, got Location: {location!r}"
        )


# ---------------------------------------------------------------------------
# All transaction routes — parametrized redirect check
# ---------------------------------------------------------------------------

# These are the routes known to exist in the Transaction Engine blueprint as of
# Phase 1.  Add new routes here as they are added to the blueprint.
TRANSACTION_ROUTES = [
    ("GET", "/"),
    ("POST", "/"),
]

# If /upload exists as a separate endpoint, include it:
UPLOAD_ROUTES = [
    ("POST", "/upload"),
]


@pytest.mark.parametrize("method,path", TRANSACTION_ROUTES + UPLOAD_ROUTES)
def test_transaction_route_redirects_unauthenticated(client, method, path):
    """Parametrized: every transaction route must redirect to /auth/login
    when the request has no session.  This test will catch any new route
    that is added without the login_required decorator."""
    if method == "GET":
        response = client.get(path, follow_redirects=False)
    elif method == "POST":
        response = client.post(
            path,
            data={"file": (make_minimal_csv(), "transactions.csv")},
            content_type="multipart/form-data",
            follow_redirects=False,
        )
    else:
        pytest.skip(f"Unsupported method {method}")

    assert response.status_code in (302, 301), (
        f"{method} {path} must redirect unauthenticated requests, "
        f"got status {response.status_code}"
    )
    location = response.headers.get("Location", "")
    assert "/auth/login" in location, (
        f"{method} {path} must redirect to /auth/login, got Location: {location!r}"
    )
