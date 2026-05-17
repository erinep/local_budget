"""Account Settings routes — Phase 2 category management UI.

All routes require an authenticated user (checked via flask.g.user).
All POST routes follow Post-Redirect-Get to prevent double-submit on reload.
CSRF protection is provided globally by Flask-WTF (see app/__init__.py).

Route table:
  GET  /account-settings/categories                    categories_list
  GET  /account-settings/categories/new                categories_new
  POST /account-settings/categories                    categories_create
  GET  /account-settings/categories/<id>/edit          categories_edit
  POST /account-settings/categories/<id>               categories_update
  POST /account-settings/categories/<id>/delete        categories_delete
  POST /account-settings/categories/<id>/keywords      keywords_add
  POST /account-settings/categories/<id>/keywords/<id>/delete  keywords_remove
  GET  /account-settings/import                        import_form
  POST /account-settings/import                        import_upload

ADR-0003: this blueprint calls Account Settings service functions only;
          no direct DB access.
ADR-0004: blueprint registered in app factory at /account-settings.
"""

import json
import logging

from flask import (
    Blueprint,
    abort,
    g,
    redirect,
    render_template,
    request,
    url_for,
)

from app.middleware.auth import login_required

from app.account_settings.services import (
    add_keyword,
    create_category,
    delete_category,
    import_from_json,
    list_categories,
    remove_keyword,
    rename_category,
)

logger = logging.getLogger(__name__)

account_settings_bp = Blueprint(
    "account_settings", __name__, url_prefix="/account-settings"
)


# ---------------------------------------------------------------------------
# Helper: resolve a category from the user's list, or 404
# ---------------------------------------------------------------------------

def _get_category_or_404(user_id: str, category_id: str) -> dict:
    """Return the category dict for category_id if it belongs to user_id.

    Aborts with 404 if not found.  Uses list_categories() so the result is
    cache-warm; no extra DB call for subsequent service operations.
    """
    categories = list_categories(user_id)
    for cat in categories:
        if cat["id"] == category_id:
            return cat
    abort(404)


# ---------------------------------------------------------------------------
# Categories — list
# ---------------------------------------------------------------------------

@account_settings_bp.route("/categories", methods=["GET"])
@login_required
def categories_list():
    """Display all categories and their keywords."""
    user_id = g.user.id
    categories = list_categories(user_id)
    return render_template(
        "account_settings/categories.html",
        categories=categories,
    )


# ---------------------------------------------------------------------------
# Categories — new / create
# ---------------------------------------------------------------------------

@account_settings_bp.route("/categories/new", methods=["GET"])
@login_required
def categories_new():
    """Render the new-category form."""
    return render_template("account_settings/category_form.html", error=None)


@account_settings_bp.route("/categories", methods=["POST"])
@login_required
def categories_create():
    """Create a new category from the submitted form."""
    user_id = g.user.id
    name = request.form.get("name", "")

    try:
        create_category(user_id, name)
    except ValueError as exc:
        return render_template(
            "account_settings/category_form.html",
            error=str(exc),
        )

    return redirect(url_for("account_settings.categories_list"))


# ---------------------------------------------------------------------------
# Categories — edit / update / delete
# ---------------------------------------------------------------------------

@account_settings_bp.route("/categories/<category_id>/edit", methods=["GET"])
@login_required
def categories_edit(category_id: str):
    """Render the edit form for an existing category."""
    user_id = g.user.id
    category = _get_category_or_404(user_id, category_id)
    return render_template(
        "account_settings/category_edit.html",
        category=category,
        error=None,
    )


@account_settings_bp.route("/categories/<category_id>", methods=["POST"])
@login_required
def categories_update(category_id: str):
    """Rename an existing category."""
    user_id = g.user.id
    new_name = request.form.get("name", "")

    try:
        rename_category(user_id, category_id, new_name)
    except ValueError as exc:
        error_msg = str(exc)
        if "not found" in error_msg.lower():
            abort(404)
        # Re-fetch category for the re-render (cache may have been invalidated).
        category = _get_category_or_404(user_id, category_id)
        return render_template(
            "account_settings/category_edit.html",
            category=category,
            error=error_msg,
        )

    return redirect(url_for("account_settings.categories_edit", category_id=category_id))


@account_settings_bp.route("/categories/<category_id>/delete", methods=["POST"])
@login_required
def categories_delete(category_id: str):
    """Delete a category (and cascade its keywords)."""
    user_id = g.user.id

    try:
        delete_category(user_id, category_id)
    except ValueError:
        abort(404)

    return redirect(url_for("account_settings.categories_list"))


# ---------------------------------------------------------------------------
# Keywords — add / remove
# ---------------------------------------------------------------------------

@account_settings_bp.route("/categories/<category_id>/keywords", methods=["POST"])
@login_required
def keywords_add(category_id: str):
    """Add a keyword to a category."""
    user_id = g.user.id
    keyword = request.form.get("keyword", "")

    try:
        add_keyword(user_id, category_id, keyword)
    except ValueError as exc:
        error_msg = str(exc)
        if "not found" in error_msg.lower():
            abort(404)
        category = _get_category_or_404(user_id, category_id)
        return render_template(
            "account_settings/category_edit.html",
            category=category,
            error=error_msg,
        )

    return redirect(url_for("account_settings.categories_edit", category_id=category_id))


@account_settings_bp.route(
    "/categories/<category_id>/keywords/<keyword_id>/delete", methods=["POST"]
)
@login_required
def keywords_remove(category_id: str, keyword_id: str):
    """Remove a keyword from a category."""
    user_id = g.user.id

    try:
        remove_keyword(user_id, category_id, keyword_id)
    except ValueError:
        abort(404)

    return redirect(url_for("account_settings.categories_edit", category_id=category_id))


# ---------------------------------------------------------------------------
# Import — form / upload
# ---------------------------------------------------------------------------

@account_settings_bp.route("/import", methods=["GET"])
@login_required
def import_form():
    """Render the JSON import form."""
    return render_template("account_settings/import.html", error=None)


@account_settings_bp.route("/import", methods=["POST"])
@login_required
def import_upload():
    """Accept a JSON file upload and import its category map.

    File size is already capped at 5 MB by MAX_CONTENT_LENGTH in the app factory.
    Validates JSON structure before calling import_from_json().
    """
    user_id = g.user.id

    file = request.files.get("file")
    if file is None or file.filename == "":
        return render_template(
            "account_settings/import.html",
            error="No file selected.",
        )

    raw_bytes = file.read()
    try:
        data = json.loads(raw_bytes)
    except json.JSONDecodeError:
        return render_template(
            "account_settings/import.html",
            error="File is not valid JSON.",
        )

    # Validate shape before calling the service (surface a clear error here).
    if not isinstance(data, dict):
        return render_template(
            "account_settings/import.html",
            error="Invalid category map format",
        )
    for key, val in data.items():
        if not isinstance(key, str):
            return render_template(
                "account_settings/import.html",
                error="Invalid category map format",
            )
        if not isinstance(val, list) or not all(isinstance(kw, str) for kw in val):
            return render_template(
                "account_settings/import.html",
                error="Invalid category map format",
            )

    try:
        import_from_json(user_id, data)
    except ValueError as exc:
        return render_template(
            "account_settings/import.html",
            error=str(exc),
        )

    return redirect(url_for("account_settings.categories_list"))
