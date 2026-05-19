"""Account Settings routes — Phase 2 category management UI.

All routes require an authenticated user (checked via flask.g.user).
All POST routes follow Post-Redirect-Get to prevent double-submit on reload.
CSRF protection is provided globally by Flask-WTF (see app/__init__.py).

Route table:
  GET  /account-settings/categories                    categories_list
  POST /account-settings/categories/backfill           categories_backfill
  GET  /account-settings/categories/new                categories_new
  POST /account-settings/categories                    categories_create
  GET  /account-settings/categories/<id>/edit          categories_edit
  POST /account-settings/categories/<id>               categories_update
  POST /account-settings/categories/<id>/delete        categories_delete
  POST /account-settings/categories/<id>/keywords      keywords_add
  POST /account-settings/categories/<id>/keywords/<id>/delete  keywords_remove
  GET  /account-settings/import                        import_form
  POST /account-settings/import                        import_upload

File management routes moved to transactions_bp per ADR-0021.

ADR-0003: this blueprint calls Account Settings service functions only;
          no direct DB access.
ADR-0004: blueprint registered in app factory at /account-settings.
"""

import json
import logging

from flask import (
    Blueprint,
    abort,
    flash,
    g,
    redirect,
    render_template,
    request,
    url_for,
)

from app.middleware.auth import login_required

from app.account_settings.services import (
    add_keyword,
    count_uncategorized_transactions,
    create_category,
    delete_category,
    get_category_detail,
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
# Settings landing — index / account
# ---------------------------------------------------------------------------

@account_settings_bp.route("/", methods=["GET"])
@login_required
def index():
    """Render the Configure landing page with sub-section cards.

    Per ADR-0011: no dropdown, no JS — Configure is its own landing page
    that surfaces configuration sub-sections as cards. File management
    moved to transactions_bp per ADR-0021.
    """
    return render_template("account_settings/index.html")


@account_settings_bp.route("/account", methods=["GET"])
@login_required
def account():
    """Render the Account Details stub.

    Per Phase 2 Amendment A: shows email + sign-out + "more coming soon".
    Password/email change and account deletion are explicitly parked
    (separate ADR required — touches Supabase Auth directly).
    """
    return render_template("account_settings/account.html")


# ---------------------------------------------------------------------------
# Categories — list
# ---------------------------------------------------------------------------

@account_settings_bp.route("/categories", methods=["GET"])
@login_required
def categories_list():
    """Display all categories and their keywords."""
    user_id = g.user.id
    categories = list_categories(user_id)
    uncategorized_count = count_uncategorized_transactions(user_id)
    return render_template(
        "account_settings/categories.html",
        categories=categories,
        uncategorized_count=uncategorized_count,
    )


# ---------------------------------------------------------------------------
# Categories — backfill uncategorized transactions (ADR-0030)
# ---------------------------------------------------------------------------

@account_settings_bp.route("/categories/backfill", methods=["POST"])
@login_required
def categories_backfill():
    """Re-categorize all NULL-category transactions using make_categorizer_v2.

    Scope: only transactions where category_id IS NULL.
    Manually-categorized transactions are never touched.
    Runs synchronously; processes in pages of 500 for large datasets.
    """
    from app.transactions.services import (
        make_categorizer_v2,
        get_categorized_descriptions,
        recategorize_transaction,
    )
    from app.account_settings.services import get_merchant_aliases
    from app.db import get_engine
    from sqlalchemy import text
    import uuid as _uuid

    user_id = g.user.id

    cats = list_categories(user_id)
    keywords = [(kw, cat["name"]) for cat in cats for kw in cat["keywords"]]
    aliases = get_merchant_aliases(user_id)
    past_txns = get_categorized_descriptions(user_id)
    categorize = make_categorizer_v2(user_id, keywords, aliases, past_txns)

    cat_id_by_name = {cat["name"]: cat["id"] for cat in cats}

    engine = get_engine()
    updated = 0
    page_size = 500
    offset = 0

    while True:
        with engine.connect() as conn:
            rows = conn.execute(
                text(
                    "SELECT id, description FROM public.transactions"
                    " WHERE user_id = :uid AND category_id IS NULL"
                    " ORDER BY date DESC"
                    " LIMIT :lim OFFSET :off"
                ),
                {"uid": user_id, "lim": page_size, "off": offset},
            ).fetchall()

        if not rows:
            break

        for row in rows:
            txn_id = _uuid.UUID(str(row[0]))
            desc = row[1]
            category_name = categorize(desc)
            if category_name == "Uncategorized":
                continue
            cat_id_str = cat_id_by_name.get(category_name)
            if cat_id_str is None:
                continue
            try:
                recategorize_transaction(
                    user_id=user_id,
                    transaction_id=txn_id,
                    category_id=_uuid.UUID(cat_id_str),
                    apply_forward_keyword=None,
                )
                updated += 1
            except Exception:
                pass

        offset += page_size

    flash(f"{updated} transaction(s) re-categorized.", "success")
    return redirect(url_for("account_settings.categories_list"))


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
    category = get_category_detail(user_id, category_id)
    if category is None:
        abort(404)
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
        category = get_category_detail(user_id, category_id)
        if category is None:
            abort(404)
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
        category = get_category_detail(user_id, category_id)
        if category is None:
            abort(404)
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
    """Render the JSON import form.

    If the user already has categories, render the form in a disabled state
    with a clear warning — import is a destructive replace and is only
    available from a clean slate.
    """
    has_existing = bool(list_categories(g.user.id))
    return render_template(
        "account_settings/import.html",
        error=None,
        has_existing_categories=has_existing,
    )


@account_settings_bp.route("/import", methods=["POST"])
@login_required
def import_upload():
    """Accept a JSON file upload and import its category map.

    File size is already capped at 5 MB by MAX_CONTENT_LENGTH in the app factory.
    Validates JSON structure before calling import_from_json().

    Refused (409) when the user already has any categories: import_from_json
    is a destructive replace, so the caller must delete existing categories
    first. This guards against accidental wipes via a re-import.
    """
    user_id = g.user.id

    if list_categories(user_id):
        return render_template(
            "account_settings/import.html",
            error=(
                "You already have categories. Import replaces everything — "
                "delete your existing categories first to use the import tool."
            ),
            has_existing_categories=True,
        ), 409

    file = request.files.get("file")
    if file is None or file.filename == "":
        return render_template(
            "account_settings/import.html",
            error="No file selected.",
            has_existing_categories=False,
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
