"""Transaction Engine routes — upload, history, recategorize, files.

All routes require authentication (ADR-0006). The category map is loaded from
the Account Settings service, injecting the per-user map via the same factory
closure used in Phase 0 (ADR-0005). The call site is unchanged; only the
source of the map has moved from a JSON file to the database.

Phase 3a: the upload POST handler writes to the database via _process_upload
and redirects to GET /intelligence/report on success (ADR-0024).

Phase 3b: adds GET /transactions (history), GET/POST /transactions/<id>/edit
(recategorize UI) per ADR-0019 and ADR-0020; GET /files and
POST /files/<id>/delete (upload file management) per ADR-0021.

Route table:
  GET  /upload                            upload (GET renders form)
  POST /upload                            upload (POST processes CSV)
  GET  /transactions                      history
  GET  /transactions/<id>/edit            edit
  POST /transactions/<id>/edit            edit_post
  GET  /files                             files
  POST /files/<upload_id>/delete          files_delete
"""

import io
import uuid as _uuid_mod
from math import ceil

import pandas as pd
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
from sqlalchemy.exc import OperationalError

from app.account_settings.services import count_uncategorized_transactions, get_merchant_aliases, list_categories
from app.middleware.auth import login_required
from app.transactions.services import (
    CategoryNotFound,
    TransactionFilters,
    TransactionNotFound,
    UploadNotFound,
    _process_upload,
    get_accounts,
    get_transaction,
    get_transactions,
    get_uploads,
    delete_upload,
    make_categorizer_v2,
    net_amount,
    normalize_description,
    recategorize_transaction,
)

transactions_bp = Blueprint("transactions", __name__)


@transactions_bp.route("/upload", methods=["GET", "POST"])
@login_required
def upload():
    accounts = get_accounts(g.user.id)

    if request.method == "POST":
        file = request.files["file"]

        if not file.filename.lower().endswith(".csv"):
            return render_template("upload.html", accounts=accounts, error="Only .csv files are accepted.")

        # Validate submitted account_id belongs to this user.
        raw_account_id = request.form.get("account_id", "").strip()
        selected_account_id = None
        if raw_account_id:
            account_ids = {str(a.id) for a in accounts}
            if raw_account_id in account_ids:
                selected_account_id = raw_account_id

        # Read raw bytes for file-level hash (ADR-0013) before parsing.
        file_bytes = file.read()

        keywords = [
            (kw, cat["name"])
            for cat in list_categories(g.user.id)
            for kw in cat["keywords"]
        ]
        aliases = get_merchant_aliases(g.user.id)
        categorize = make_categorizer_v2(g.user.id, keywords, aliases)

        try:
            df = pd.read_csv(io.BytesIO(file_bytes), encoding="utf-8-sig")
        except Exception:
            return render_template(
                "upload.html",
                accounts=accounts,
                error="Could not parse the file. Make sure it is a valid CSV export.",
            )

        required_columns = {"Transaction Date", "Description 1", "CAD$"}
        missing = required_columns - set(df.columns)
        if missing:
            return render_template(
                "upload.html",
                accounts=accounts,
                error=(
                    f"Missing required column(s): {', '.join(sorted(missing))}. "
                    "Expected columns: Transaction Date, Description 1, CAD$."
                ),
            )

        df = df[["Transaction Date", "Description 1", "CAD$"]]

        df["Transaction Date"] = pd.to_datetime(
            df["Transaction Date"],
            format="mixed",
            errors="coerce",
        )

        df["Category"] = df["Description 1"].apply(categorize)
        df["Net"] = df.apply(net_amount, axis=1)

        df = df[df["Net"] != 0]
        df = df.dropna(subset=["Transaction Date"])

        # Phase 3a: persist upload and transactions to DB.
        try:
            result = _process_upload(
                user_id=g.user.id,
                filename=file.filename,
                file_bytes=file_bytes,
                df=df,
                account_id=selected_account_id,
            )
        except OperationalError:
            return render_template(
                "upload.html",
                accounts=accounts,
                error="Upload failed — database connection error. Please try again.",
            )

        if result["already_uploaded"]:
            return render_template(
                "upload.html",
                accounts=accounts,
                error="This file was already uploaded.",
            )

        if result["new_count"] == 0:
            # Edge case: all rows were duplicates and nothing remains.
            return render_template(
                "upload.html",
                accounts=accounts,
                error="No new transactions were found in this file.",
            )

        return redirect(url_for("intelligence.dashboard"))

    return render_template("upload.html", accounts=accounts)


# ---------------------------------------------------------------------------
# Phase 3b: Transaction history view (ADR-0019)
# ---------------------------------------------------------------------------

@transactions_bp.route("/transactions", endpoint="history")
@login_required
def history():
    """Render the paginated transaction history view with filters.

    Query parameters (all optional, silently ignored if invalid):
      date_from      — ISO date string (YYYY-MM-DD)
      date_to        — ISO date string (YYYY-MM-DD)
      category_id    — UUID string (ignored when uncategorized=1)
      search         — free-text substring search
      uncategorized  — "1" to show only uncategorized transactions
      page           — positive integer, default 1
    """
    import datetime

    # --- Parse query params (silently ignore invalid values) ---
    date_from = None
    raw_date_from = request.args.get("date_from", "").strip()
    if raw_date_from:
        try:
            date_from = datetime.date.fromisoformat(raw_date_from)
        except ValueError:
            pass

    date_to = None
    raw_date_to = request.args.get("date_to", "").strip()
    if raw_date_to:
        try:
            date_to = datetime.date.fromisoformat(raw_date_to)
        except ValueError:
            pass

    uncategorized_only = request.args.get("uncategorized", "").strip() == "1"

    # category_id and uncategorized_only are mutually exclusive (TransactionFilters
    # raises if both are set); uncategorized_only takes precedence.
    category_id = None
    if not uncategorized_only:
        raw_cat = request.args.get("category_id", "").strip()
        if raw_cat:
            try:
                category_id = _uuid_mod.UUID(raw_cat)
            except ValueError:
                pass

    search = request.args.get("search", "").strip() or None

    page = 1
    raw_page = request.args.get("page", "").strip()
    if raw_page:
        try:
            page = max(1, int(raw_page))
        except ValueError:
            pass

    limit = 50
    offset = (page - 1) * limit

    # --- Build filters and fetch ---
    filters = TransactionFilters(
        date_from=date_from,
        date_to=date_to,
        category_id=category_id,
        search=search,
        uncategorized_only=uncategorized_only,
        limit=limit,
        offset=offset,
    )
    page_result = get_transactions(g.user.id, filters)
    categories = list_categories(g.user.id)

    total_count = page_result.total_count
    total_pages = max(1, ceil(total_count / limit))
    page = min(page, total_pages)

    has_prev = page > 1
    has_next = page < total_pages

    # Build active filter kwargs for URL generation (only non-None / non-empty).
    active_filters = {}
    if date_from is not None:
        active_filters["date_from"] = date_from.isoformat()
    if date_to is not None:
        active_filters["date_to"] = date_to.isoformat()
    if category_id is not None:
        active_filters["category_id"] = str(category_id)
    if search:
        active_filters["search"] = search
    if uncategorized_only:
        active_filters["uncategorized"] = "1"

    prev_url = url_for("transactions.history", page=page - 1, **active_filters) if has_prev else None
    next_url = url_for("transactions.history", page=page + 1, **active_filters) if has_next else None

    if total_count == 0:
        showing_from = 0
        showing_to = 0
    else:
        showing_from = offset + 1
        showing_to = min(offset + limit, total_count)

    uncategorized_count = count_uncategorized_transactions(g.user.id)

    return render_template(
        "transactions/history.html",
        transactions=page_result.items,
        total_count=total_count,
        categories=categories,
        page=page,
        total_pages=total_pages,
        has_prev=has_prev,
        has_next=has_next,
        prev_url=prev_url,
        next_url=next_url,
        showing_from=showing_from,
        showing_to=showing_to,
        uncategorized_count=uncategorized_count,
        # active filter values for re-populating the form
        date_from=date_from.isoformat() if date_from else "",
        date_to=date_to.isoformat() if date_to else "",
        selected_category_id=str(category_id) if category_id else "",
        search=search or "",
        uncategorized_only=uncategorized_only,
    )


# ---------------------------------------------------------------------------
# Phase 3b: Recategorize edit page (ADR-0020)
# ---------------------------------------------------------------------------

@transactions_bp.route("/transactions/<id>/edit", endpoint="edit", methods=["GET"])
@login_required
def edit(id):
    """Render the recategorize edit page for a single transaction."""
    try:
        transaction_id = _uuid_mod.UUID(id)
    except ValueError:
        abort(400)

    try:
        txn = get_transaction(g.user.id, transaction_id)
    except TransactionNotFound:
        abort(404)

    categories = list_categories(g.user.id)
    next_url = request.args.get("next", "").strip()
    return render_template(
        "transactions/edit.html",
        txn=txn,
        categories=categories,
        next_url=next_url,
        keyword_suggestions=_keyword_suggestions(txn.description),
    )


def _keyword_suggestions(description: str) -> list:
    """Return ordered, deduplicated keyword pill suggestions for a transaction description."""
    import re as _re
    normalized = normalize_description(description)
    tokens = [t.strip() for t in _re.split(r'[\s*]+', normalized) if t.strip() and not t.strip().isdigit()]
    candidates = [normalized] + ([" ".join(tokens[:2])] if len(tokens) > 2 else []) + (tokens if len(tokens) > 1 else [])
    return list(dict.fromkeys(candidates))


def _safe_redirect_url(raw: str) -> str:
    """Return a safe relative URL from raw, stripping scheme/host. Defaults to history."""
    from urllib.parse import urlparse
    if raw:
        parsed = urlparse(raw)
        path = parsed.path
        if parsed.query:
            path += "?" + parsed.query
        if path.startswith("/"):
            return path
    return url_for("transactions.history")


@transactions_bp.route("/transactions/<id>/edit", endpoint="edit_post", methods=["POST"])
@login_required
def edit_post(id):
    """Handle the recategorize form submission."""
    try:
        transaction_id = _uuid_mod.UUID(id)
    except ValueError:
        abort(400)

    # --- Parse form fields ---
    raw_cat = request.form.get("category_id", "").strip()
    if raw_cat:
        try:
            category_id = _uuid_mod.UUID(raw_cat)
        except ValueError:
            abort(400)
    else:
        category_id = None

    keyword_raw = request.form.get("keyword", "").strip()
    apply_forward_keyword = keyword_raw if keyword_raw else None

    try:
        result = recategorize_transaction(
            user_id=g.user.id,
            transaction_id=transaction_id,
            category_id=category_id,
            apply_forward_keyword=apply_forward_keyword,
        )
    except TransactionNotFound:
        abort(404)
    except CategoryNotFound:
        # Re-render the form with the original transaction data.
        try:
            txn = get_transaction(g.user.id, transaction_id)
        except TransactionNotFound:
            abort(404)
        categories = list_categories(g.user.id)
        next_url = request.form.get("next", "").strip()
        flash("Category not found or no longer available.", "error")
        return render_template(
            "transactions/edit.html",
            txn=txn,
            categories=categories,
            next_url=next_url,
            keyword_suggestions=_keyword_suggestions(txn.description),
        )
    except Exception:
        # Keyword write failed after transaction was already committed (partial success).
        flash(
            "Transaction recategorized, but the keyword rule could not be saved."
            " You can add it manually in Category Settings.",
            "warning",
        )
        return redirect(_safe_redirect_url(request.form.get("next", "")))

    # --- Flash success message ---
    if result.keyword_written:
        flash("Transaction recategorized and keyword rule saved.", "success")
    elif result.keyword_conflict:
        flash("Transaction recategorized. (Keyword rule already existed.)", "success")
    else:
        flash("Transaction recategorized.", "success")

    return redirect(_safe_redirect_url(request.form.get("next", "")))


# ---------------------------------------------------------------------------
# Phase 3b: Upload file management (ADR-0021)
# ---------------------------------------------------------------------------

@transactions_bp.route("/files", endpoint="files", methods=["GET"])
@login_required
def files_list():
    return redirect(url_for("settings.files_list"))


@transactions_bp.route("/files/<upload_id>/delete", endpoint="files_delete", methods=["POST"])
@login_required
def files_delete(upload_id: str):
    """Delete an upload and cascade-delete all its transactions."""
    try:
        uid = _uuid_mod.UUID(upload_id)
    except (ValueError, AttributeError):
        abort(400)

    try:
        delete_upload(g.user.id, uid)
    except UploadNotFound:
        abort(404)

    flash("File deleted and all its transactions removed.", "success")
    return redirect(url_for("settings.files_list"))
