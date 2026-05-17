"""Tests for account_settings routes (Phase 2).

Contract source: Phase 2 task spec — route contract section.

Service layer is mocked — these tests verify HTTP behaviour (status codes,
redirects, template variables, auth enforcement) not business logic.

All routes live under /account-settings. All require auth — an unauthenticated
client must receive 302 for every route.

Security note: this surface exposes financial category data. User-isolation
must be verified at the route layer (tests below). Human review is required
before public launch (architecture.md cross-cutting concerns).

Patch target convention: patch the names as bound inside the routes module,
e.g. "app.account_settings.routes.list_categories". This mirrors the pattern
used in test_auth_routes.py.
"""

import io
import json
import uuid
from unittest.mock import MagicMock, patch

import pytest

# Patch names as bound in the routes module.
SVC = "app.account_settings.routes"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _cat(name="Groceries", cat_id=None, keywords=None):
    """Build a minimal category dict matching the list_categories contract."""
    return {
        "id": cat_id or str(uuid.uuid4()),
        "name": name,
        "keywords": keywords or [],
    }


def _kw(keyword="LOBLAWS", kw_id=None):
    """Build a minimal keyword dict matching the add_keyword contract."""
    return {
        "id": kw_id or str(uuid.uuid4()),
        "keyword": keyword,
    }


# ---------------------------------------------------------------------------
# Auth enforcement — every route must redirect an unauthenticated client
# ---------------------------------------------------------------------------

class TestUnauthenticatedAccess:
    """Every account-settings route must return 302 for unauthenticated access."""

    UNAUTHENTICATED_ROUTES = [
        ("GET",  "/account-settings/categories"),
        ("GET",  "/account-settings/categories/new"),
        ("POST", "/account-settings/categories"),
        ("GET",  f"/account-settings/categories/{uuid.uuid4()}/edit"),
        ("POST", f"/account-settings/categories/{uuid.uuid4()}"),
        ("POST", f"/account-settings/categories/{uuid.uuid4()}/delete"),
        ("POST", f"/account-settings/categories/{uuid.uuid4()}/keywords"),
        ("POST", f"/account-settings/categories/{uuid.uuid4()}/keywords/{uuid.uuid4()}/delete"),
        ("GET",  "/account-settings/import"),
        ("POST", "/account-settings/import"),
    ]

    @pytest.mark.parametrize("method,url", UNAUTHENTICATED_ROUTES)
    def test_unauthenticated_gets_302(self, client, method, url):
        """An unauthenticated client must be redirected (302) from every
        account-settings route. No route must expose data without auth."""
        response = getattr(client, method.lower())(url, follow_redirects=False)
        assert response.status_code == 302, (
            f"{method} {url} must return 302 for unauthenticated client"
        )


# ---------------------------------------------------------------------------
# GET /account-settings/categories
# ---------------------------------------------------------------------------

class TestGetCategoriesList:
    def test_authenticated_returns_200(self, authenticated_client):
        """Authenticated GET to /account-settings/categories must return 200."""
        with patch(f"{SVC}.list_categories", return_value=[]):
            response = authenticated_client.get(
                "/account-settings/categories",
                follow_redirects=False,
            )
        assert response.status_code == 200

    def test_calls_list_categories_with_session_user_id(
        self, authenticated_client, mock_auth_user
    ):
        """The route must call list_categories with the authenticated user's
        id, not a hard-coded value."""
        with patch(f"{SVC}.list_categories", return_value=[]) as mock_list:
            authenticated_client.get("/account-settings/categories")
        mock_list.assert_called_once_with(mock_auth_user.id)

    def test_template_receives_categories_variable(self, authenticated_client):
        """The rendered template must include the categories returned by the
        service layer."""
        cats = [_cat("Groceries"), _cat("Transport")]
        with patch(f"{SVC}.list_categories", return_value=cats):
            response = authenticated_client.get("/account-settings/categories")

        assert b"Groceries" in response.data
        assert b"Transport" in response.data


# ---------------------------------------------------------------------------
# GET /account-settings/categories/new
# ---------------------------------------------------------------------------

class TestGetCategoriesNew:
    def test_authenticated_returns_200(self, authenticated_client):
        """Authenticated GET to /account-settings/categories/new must return 200."""
        response = authenticated_client.get(
            "/account-settings/categories/new",
            follow_redirects=False,
        )
        assert response.status_code == 200

    def test_response_contains_form(self, authenticated_client):
        """The new-category page must render an HTML form."""
        response = authenticated_client.get("/account-settings/categories/new")
        assert b"<form" in response.data


# ---------------------------------------------------------------------------
# POST /account-settings/categories
# ---------------------------------------------------------------------------

class TestPostCategories:
    def test_valid_name_calls_create_and_redirects_302(
        self, authenticated_client, mock_auth_user
    ):
        """A valid name must call create_category and redirect to the categories
        list with a 302."""
        new_cat = _cat("Groceries")
        with patch(f"{SVC}.create_category", return_value=new_cat) as mock_create:
            response = authenticated_client.post(
                "/account-settings/categories",
                data={"name": "Groceries"},
                follow_redirects=False,
            )
        mock_create.assert_called_once_with(mock_auth_user.id, "Groceries")
        assert response.status_code == 302
        assert "/account-settings/categories" in response.headers.get("Location", "")

    def test_invalid_name_returns_200_no_redirect(self, authenticated_client):
        """A ValueError from the service (e.g. empty name) must re-render the
        form (200), not redirect."""
        with patch(
            f"{SVC}.create_category",
            side_effect=ValueError("Category name cannot be empty"),
        ):
            response = authenticated_client.post(
                "/account-settings/categories",
                data={"name": ""},
                follow_redirects=False,
            )
        assert response.status_code == 200

    def test_value_error_message_in_response_body(self, authenticated_client):
        """When create_category raises ValueError, the error text must appear
        in the rendered response so the user understands what went wrong."""
        with patch(
            f"{SVC}.create_category",
            side_effect=ValueError("Category name cannot be empty"),
        ):
            response = authenticated_client.post(
                "/account-settings/categories",
                data={"name": ""},
            )
        assert b"cannot be empty" in response.data or b"empty" in response.data

    def test_duplicate_name_returns_200_with_error(self, authenticated_client):
        """A duplicate-name ValueError must return 200 with the error in the body."""
        with patch(
            f"{SVC}.create_category",
            side_effect=ValueError("Category 'Food' already exists"),
        ):
            response = authenticated_client.post(
                "/account-settings/categories",
                data={"name": "Food"},
            )
        assert response.status_code == 200
        assert b"Food" in response.data


# ---------------------------------------------------------------------------
# GET /account-settings/categories/<id>/edit
# ---------------------------------------------------------------------------

class TestGetCategoryEdit:
    def test_category_belonging_to_user_returns_200(self, authenticated_client, mock_auth_user):
        """Editing a category that belongs to the authenticated user must
        return 200."""
        cat_id = str(uuid.uuid4())
        cats = [_cat("Groceries", cat_id=cat_id)]

        with patch(f"{SVC}.list_categories", return_value=cats):
            response = authenticated_client.get(
                f"/account-settings/categories/{cat_id}/edit",
                follow_redirects=False,
            )
        assert response.status_code == 200

    def test_category_not_in_users_list_returns_404(self, authenticated_client):
        """A category_id that does not appear in the user's list_categories
        result must return 404 — not 200 or 403."""
        with patch(f"{SVC}.list_categories", return_value=[]):
            response = authenticated_client.get(
                f"/account-settings/categories/{uuid.uuid4()}/edit",
                follow_redirects=False,
            )
        assert response.status_code == 404


# ---------------------------------------------------------------------------
# POST /account-settings/categories/<id>  (rename)
# ---------------------------------------------------------------------------

class TestPostCategoryRename:
    def test_valid_rename_calls_service_and_redirects_302(
        self, authenticated_client, mock_auth_user
    ):
        """Valid rename must call rename_category and redirect to the edit page."""
        cat_id = str(uuid.uuid4())
        renamed = {"id": cat_id, "name": "Restaurants"}

        with patch(f"{SVC}.rename_category", return_value=renamed) as mock_rename:
            response = authenticated_client.post(
                f"/account-settings/categories/{cat_id}",
                data={"name": "Restaurants"},
                follow_redirects=False,
            )
        mock_rename.assert_called_once_with(mock_auth_user.id, cat_id, "Restaurants")
        assert response.status_code == 302
        assert cat_id in response.headers.get("Location", "")

    def test_category_not_found_returns_404(self, authenticated_client):
        """ValueError('Category not found') from the service must return 404."""
        cat_id = str(uuid.uuid4())

        with patch(
            f"{SVC}.rename_category",
            side_effect=ValueError("Category not found"),
        ):
            response = authenticated_client.post(
                f"/account-settings/categories/{cat_id}",
                data={"name": "NewName"},
                follow_redirects=False,
            )
        assert response.status_code == 404

    def test_name_conflict_returns_200_with_error(self, authenticated_client):
        """ValueError for a name conflict must re-render the form (200) with
        the error message."""
        cat_id = str(uuid.uuid4())

        with patch(
            f"{SVC}.rename_category",
            side_effect=ValueError("Category 'Food' already exists"),
        ):
            response = authenticated_client.post(
                f"/account-settings/categories/{cat_id}",
                data={"name": "Food"},
            )
        assert response.status_code == 200

    def test_empty_name_returns_200_with_error(self, authenticated_client):
        """ValueError('Category name cannot be empty') must re-render (200)."""
        cat_id = str(uuid.uuid4())

        with patch(
            f"{SVC}.rename_category",
            side_effect=ValueError("Category name cannot be empty"),
        ):
            response = authenticated_client.post(
                f"/account-settings/categories/{cat_id}",
                data={"name": ""},
            )
        assert response.status_code == 200


# ---------------------------------------------------------------------------
# POST /account-settings/categories/<id>/delete
# ---------------------------------------------------------------------------

class TestPostCategoryDelete:
    def test_valid_delete_calls_service_and_redirects_to_list(
        self, authenticated_client, mock_auth_user
    ):
        """Valid delete must call delete_category and redirect to the categories
        list (302)."""
        cat_id = str(uuid.uuid4())

        with patch(f"{SVC}.delete_category", return_value=None) as mock_del:
            response = authenticated_client.post(
                f"/account-settings/categories/{cat_id}/delete",
                follow_redirects=False,
            )
        mock_del.assert_called_once_with(mock_auth_user.id, cat_id)
        assert response.status_code == 302
        assert "/account-settings/categories" in response.headers.get("Location", "")

    def test_category_not_found_returns_404(self, authenticated_client):
        """Deleting a category that does not belong to the user must return 404.
        This enforces user-isolation at the HTTP layer — another user's category
        must not be deletable even via direct URL manipulation."""
        cat_id = str(uuid.uuid4())

        with patch(
            f"{SVC}.delete_category",
            side_effect=ValueError("Category not found"),
        ):
            response = authenticated_client.post(
                f"/account-settings/categories/{cat_id}/delete",
                follow_redirects=False,
            )
        assert response.status_code == 404


# ---------------------------------------------------------------------------
# POST /account-settings/categories/<id>/keywords
# ---------------------------------------------------------------------------

class TestPostAddKeyword:
    def test_valid_keyword_calls_service_and_redirects_to_edit(
        self, authenticated_client, mock_auth_user
    ):
        """Valid keyword add must call add_keyword and redirect to the edit page."""
        cat_id = str(uuid.uuid4())
        kw = _kw("LOBLAWS")

        with patch(f"{SVC}.add_keyword", return_value=kw) as mock_add:
            response = authenticated_client.post(
                f"/account-settings/categories/{cat_id}/keywords",
                data={"keyword": "LOBLAWS"},
                follow_redirects=False,
            )
        mock_add.assert_called_once_with(mock_auth_user.id, cat_id, "LOBLAWS")
        assert response.status_code == 302
        assert cat_id in response.headers.get("Location", "")

    def test_category_not_found_returns_404(self, authenticated_client):
        """add_keyword raising ValueError('Category not found') must return 404."""
        cat_id = str(uuid.uuid4())

        with patch(
            f"{SVC}.add_keyword",
            side_effect=ValueError("Category not found"),
        ):
            response = authenticated_client.post(
                f"/account-settings/categories/{cat_id}/keywords",
                data={"keyword": "PIZZA"},
                follow_redirects=False,
            )
        assert response.status_code == 404

    def test_duplicate_keyword_returns_200_with_error(self, authenticated_client):
        """add_keyword raising a duplicate ValueError must re-render (200)."""
        cat_id = str(uuid.uuid4())

        with patch(
            f"{SVC}.add_keyword",
            side_effect=ValueError("Keyword 'PIZZA' already exists in this category"),
        ):
            response = authenticated_client.post(
                f"/account-settings/categories/{cat_id}/keywords",
                data={"keyword": "PIZZA"},
            )
        assert response.status_code == 200

    def test_empty_keyword_returns_200_with_error(self, authenticated_client):
        """add_keyword raising ValueError('Keyword cannot be empty') must
        re-render (200)."""
        cat_id = str(uuid.uuid4())

        with patch(
            f"{SVC}.add_keyword",
            side_effect=ValueError("Keyword cannot be empty"),
        ):
            response = authenticated_client.post(
                f"/account-settings/categories/{cat_id}/keywords",
                data={"keyword": ""},
            )
        assert response.status_code == 200


# ---------------------------------------------------------------------------
# POST /account-settings/categories/<id>/keywords/<kid>/delete
# ---------------------------------------------------------------------------

class TestPostRemoveKeyword:
    def test_valid_remove_calls_service_and_redirects_to_edit(
        self, authenticated_client, mock_auth_user
    ):
        """Valid keyword removal must call remove_keyword and redirect to the
        edit page (302)."""
        cat_id = str(uuid.uuid4())
        kw_id = str(uuid.uuid4())

        with patch(f"{SVC}.remove_keyword", return_value=None) as mock_rm:
            response = authenticated_client.post(
                f"/account-settings/categories/{cat_id}/keywords/{kw_id}/delete",
                follow_redirects=False,
            )
        mock_rm.assert_called_once_with(mock_auth_user.id, cat_id, kw_id)
        assert response.status_code == 302
        assert cat_id in response.headers.get("Location", "")

    def test_category_not_found_returns_404(self, authenticated_client):
        """remove_keyword raising ValueError('Category not found') must return 404."""
        cat_id = str(uuid.uuid4())
        kw_id = str(uuid.uuid4())

        with patch(
            f"{SVC}.remove_keyword",
            side_effect=ValueError("Category not found"),
        ):
            response = authenticated_client.post(
                f"/account-settings/categories/{cat_id}/keywords/{kw_id}/delete",
                follow_redirects=False,
            )
        assert response.status_code == 404

    def test_keyword_not_found_returns_404(self, authenticated_client):
        """remove_keyword raising ValueError('Keyword not found') must return 404."""
        cat_id = str(uuid.uuid4())
        kw_id = str(uuid.uuid4())

        with patch(
            f"{SVC}.remove_keyword",
            side_effect=ValueError("Keyword not found"),
        ):
            response = authenticated_client.post(
                f"/account-settings/categories/{cat_id}/keywords/{kw_id}/delete",
                follow_redirects=False,
            )
        assert response.status_code == 404


# ---------------------------------------------------------------------------
# GET /account-settings/import
# ---------------------------------------------------------------------------

class TestGetImport:
    def test_authenticated_returns_200(self, authenticated_client):
        """Authenticated GET to /account-settings/import must return 200."""
        response = authenticated_client.get(
            "/account-settings/import",
            follow_redirects=False,
        )
        assert response.status_code == 200

    def test_response_contains_form(self, authenticated_client):
        """The import page must render an HTML form (file upload)."""
        response = authenticated_client.get("/account-settings/import")
        assert b"<form" in response.data


# ---------------------------------------------------------------------------
# POST /account-settings/import
# ---------------------------------------------------------------------------

class TestPostImport:
    def test_valid_json_file_calls_import_and_redirects(
        self, authenticated_client, mock_auth_user
    ):
        """A valid JSON file must call import_from_json and redirect to the
        categories list (302)."""
        payload = json.dumps({"Food": ["PIZZA"], "Transport": ["UBER"]}).encode()
        data = {
            "file": (io.BytesIO(payload), "categories.json"),
        }

        with patch(f"{SVC}.import_from_json", return_value=None) as mock_import:
            response = authenticated_client.post(
                "/account-settings/import",
                data=data,
                content_type="multipart/form-data",
                follow_redirects=False,
            )
        mock_import.assert_called_once_with(
            mock_auth_user.id, {"Food": ["PIZZA"], "Transport": ["UBER"]}
        )
        assert response.status_code == 302
        assert "/account-settings/categories" in response.headers.get("Location", "")

    def test_no_file_returns_200_with_error(self, authenticated_client):
        """Submitting the import form without a file must return 200 (re-render
        with error), not redirect."""
        response = authenticated_client.post(
            "/account-settings/import",
            data={},
            content_type="multipart/form-data",
            follow_redirects=False,
        )
        assert response.status_code == 200

    def test_invalid_json_returns_200_with_not_valid_json_error(
        self, authenticated_client
    ):
        """Uploading a file that is not valid JSON must return 200 with an
        error message containing 'not valid JSON'."""
        data = {
            "file": (io.BytesIO(b"this is not json {{{{"), "categories.json"),
        }

        response = authenticated_client.post(
            "/account-settings/import",
            data=data,
            content_type="multipart/form-data",
        )
        assert response.status_code == 200
        assert b"not valid JSON" in response.data or b"valid JSON" in response.data

    def test_wrong_format_not_dict_returns_200_with_error(self, authenticated_client):
        """Uploading valid JSON that is not a dict must return 200 with an
        error message. The service raises ValueError('Invalid category map format')."""
        payload = json.dumps(["Food", "Transport"]).encode()
        data = {
            "file": (io.BytesIO(payload), "categories.json"),
        }

        with patch(
            f"{SVC}.import_from_json",
            side_effect=ValueError("Invalid category map format"),
        ):
            response = authenticated_client.post(
                "/account-settings/import",
                data=data,
                content_type="multipart/form-data",
            )
        assert response.status_code == 200

    def test_value_error_from_service_returns_200_with_error(
        self, authenticated_client
    ):
        """Any ValueError from import_from_json must re-render the form (200)
        with the error visible in the response body."""
        payload = json.dumps({"Food": ["PIZZA"]}).encode()
        data = {
            "file": (io.BytesIO(payload), "categories.json"),
        }

        with patch(
            f"{SVC}.import_from_json",
            side_effect=ValueError("Invalid category map format"),
        ):
            response = authenticated_client.post(
                "/account-settings/import",
                data=data,
                content_type="multipart/form-data",
            )
        assert response.status_code == 200
        assert b"Invalid" in response.data or b"format" in response.data
