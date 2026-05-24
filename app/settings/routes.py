"""Settings routes — Phase 5c unified settings surface.

All routes require authentication. All POST routes use Post-Redirect-Get.

Route table:
  GET  /settings/                              index
  GET  /settings/profile                       profile
  GET  /settings/categories                    categories (302 → /account-settings/categories)
  GET  /settings/accounts                      accounts_list
  POST /settings/accounts                      accounts_create
  POST /settings/accounts/<id>/rename          accounts_rename
  POST /settings/accounts/<id>/delete          accounts_delete
  GET  /settings/files                          files_list
  GET  /settings/security                      security

ADR-0035: new thin settings blueprint owns the /settings prefix.
ADR-0034: account CRUD lives here; service layer in transactions.services.
"""

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
from app.transactions.services import (
    AccountNotFound,
    create_account,
    delete_account,
    get_accounts,
    get_uploads,
    rename_account,
    set_account_active,
)
from app.account_settings.services import (
    count_uncategorized_transactions,
    list_categories,
    list_merchant_aliases_detail,
)

logger = logging.getLogger(__name__)

settings_bp = Blueprint("settings", __name__, url_prefix="/settings")


@settings_bp.route("/", methods=["GET"])
@login_required
def index():
    return redirect(url_for("settings.profile"))


@settings_bp.route("/profile", methods=["GET"])
@login_required
def profile():
    return render_template("settings/profile.html")


@settings_bp.route("/categories", methods=["GET"])
@login_required
def categories():
    user_id = g.user.id
    cats = list_categories(user_id)
    uncategorized_count = count_uncategorized_transactions(user_id)
    return render_template(
        "settings/categories.html",
        categories=cats,
        uncategorized_count=uncategorized_count,
    )


@settings_bp.route("/accounts", methods=["GET"])
@login_required
def accounts_list():
    accounts = get_accounts(g.user.id)
    return render_template("settings/accounts.html", accounts=accounts)


@settings_bp.route("/accounts", methods=["POST"])
@login_required
def accounts_create():
    name = request.form.get("name", "").strip()
    try:
        create_account(g.user.id, name)
    except ValueError as exc:
        accounts = get_accounts(g.user.id)
        return render_template(
            "settings/accounts.html",
            accounts=accounts,
            create_error=str(exc),
        )
    flash(f"Account '{name}' created.", "success")
    return redirect(url_for("settings.accounts_list"))


@settings_bp.route("/accounts/<account_id>/rename", methods=["POST"])
@login_required
def accounts_rename(account_id: str):
    new_name = request.form.get("name", "").strip()
    try:
        rename_account(g.user.id, account_id, new_name)
    except AccountNotFound:
        abort(404)
    except ValueError as exc:
        flash(str(exc), "error")
        return redirect(url_for("settings.accounts_list"))
    flash(f"Account renamed to '{new_name}'.", "success")
    return redirect(url_for("settings.accounts_list"))


@settings_bp.route("/accounts/<account_id>/delete", methods=["POST"])
@login_required
def accounts_delete(account_id: str):
    try:
        delete_account(g.user.id, account_id)
    except AccountNotFound:
        abort(404)
    flash("Account and all its transactions deleted.", "success")
    return redirect(url_for("settings.accounts_list"))


@settings_bp.route("/accounts/<account_id>/set-active", methods=["POST"])
@login_required
def accounts_set_active(account_id: str):
    is_active = request.form.get("is_active") == "true"
    try:
        set_account_active(g.user.id, account_id, is_active)
    except AccountNotFound:
        abort(404)
    return redirect(url_for("settings.accounts_list"))


@settings_bp.route("/aliases", methods=["GET"])
@login_required
def aliases():
    aliases = list_merchant_aliases_detail(g.user.id)
    return render_template("settings/aliases.html", aliases=aliases)


@settings_bp.route("/files", methods=["GET"])
@login_required
def files_list():
    uploads = get_uploads(g.user.id)
    return render_template("transactions/files.html", uploads=uploads)


@settings_bp.route("/security", methods=["GET"])
@login_required
def security():
    return render_template("settings/security.html")
