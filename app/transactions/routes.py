"""Transaction Engine routes — upload, report, history, recategorize, files.

All routes require authentication (ADR-0006). The category map is loaded from
the Account Settings service, injecting the per-user map via the same factory
closure used in Phase 0 (ADR-0005). The call site is unchanged; only the
source of the map has moved from a JSON file to the database.

Phase 3a: the upload POST handler writes to the database via _process_upload
and renders the report from DB data via get_transactions (ADR-0016, ADR-0017).

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
from collections import defaultdict
from decimal import Decimal
from math import ceil

import pandas as pd
from flask import (
    Blueprint,
    abort,
    current_app,
    flash,
    g,
    redirect,
    render_template,
    request,
    url_for,
)

from app.account_settings.services import get_category_map, list_categories
from app.middleware.auth import login_required
from app.transactions.services import (
    CategoryNotFound,
    TransactionFilters,
    TransactionNotFound,
    UploadNotFound,
    _process_upload,
    get_transaction,
    get_transactions,
    get_uploads,
    delete_upload,
    make_categorizer,
    net_amount,
    recategorize_transaction,
)

transactions_bp = Blueprint("transactions", __name__)


def _build_report_from_db(user_id: str) -> dict:
    """Query the DB and build all template variables for report.html.

    Uses get_transactions with limit=200 (Phase 3a cap).
    Replicates the original pandas aggregations in pure Python.
    Returns a dict of template variables; does not render.
    """
    page = get_transactions(user_id, TransactionFilters(limit=200, offset=0))
    items = page.items  # list[Transaction]

    if not items:
        return None  # caller handles empty state

    # --- Helpers ---
    def _fmt_date(d) -> str:
        """Format a date or datetime as 'Jan 01, 2026'."""
        if hasattr(d, "strftime"):
            return d.strftime("%b %d, %Y")
        return str(d)

    def _month_key(d) -> str:
        """Return 'YYYY-MM' period string matching pandas Period('M') str."""
        if hasattr(d, "year"):
            return f"{d.year}-{d.month:02d}"
        return str(d)[:7]

    # --- Date range ---
    all_dates = [t.date for t in items]
    report_date_range = {
        "start": _fmt_date(min(all_dates)),
        "end": _fmt_date(max(all_dates)),
    }

    # --- Per-category totals (overall) ---
    # amount is signed: debits are negative (money out), credits positive.
    # The original route used net_amount which made spend positive.
    # In DB, amount is stored as-is from CAD$ (negative for debits).
    # To replicate the "positive = spend" convention for charts:
    #   spend = abs(amount) when amount < 0 (debit)
    # Credits (amount > 0, e.g. refunds) contribute negative spend.
    # This mirrors net_amount() semantics: debits → positive, credits → negative.
    category_totals: dict[str, float] = defaultdict(float)
    category_transactions: dict[str, list] = defaultdict(list)

    for t in items:
        cat = t.category_name or "Slush Fund"
        amount = float(t.amount)
        # Replicate net_amount: negative CAD$ → positive net spend
        net = abs(amount) if amount < 0 else -amount
        category_totals[cat] += net
        category_transactions[cat].append({
            "Transaction Date": _fmt_date(t.date),
            "Description": t.description,
            "Category": cat,
            "Net": round(net, 2),
        })

    # Sort categories by total spend descending.
    sorted_cats = sorted(
        [(cat, total) for cat, total in category_totals.items() if total > 0],
        key=lambda x: x[1],
        reverse=True,
    )

    overall_chart_data = []
    for cat, total in sorted_cats:
        cat_txns = sorted(
            category_transactions[cat],
            key=lambda x: (-x["Net"], x["Transaction Date"]),
        )
        overall_chart_data.append({
            "label": cat,
            "value": round(total, 2),
            "transactions": cat_txns,
        })

    # --- Monthly grouping ---
    # Group transactions by month, compute per-month category totals.
    month_items: dict[str, list] = defaultdict(list)
    for t in items:
        mk = _month_key(t.date)
        month_items[mk].append(t)

    # Sort months chronologically.
    sorted_months = sorted(month_items.keys())

    # Build trend chart data structures.
    all_categories: list[str] = list(
        dict.fromkeys(cat for cat, _ in sorted_cats)
    )

    # month → category → total (for trend chart)
    monthly_cat_totals: dict[str, dict[str, float]] = {}
    for mk in sorted_months:
        monthly_cat_totals[mk] = defaultdict(float)
        for t in month_items[mk]:
            cat = t.category_name or "Slush Fund"
            amount = float(t.amount)
            net = abs(amount) if amount < 0 else -amount
            monthly_cat_totals[mk][cat] += net

    trend_chart_data = {
        "labels": sorted_months,
        "datasets": [
            {
                "label": cat,
                "values": [
                    round(monthly_cat_totals[mk].get(cat, 0.0), 2)
                    for mk in sorted_months
                ],
            }
            for cat in all_categories
        ],
    }

    monthly_data = []
    for mk in sorted_months:
        txns_in_month = month_items[mk]

        # Per-month category totals for chart.
        month_cat_totals: dict[str, float] = defaultdict(float)
        for t in txns_in_month:
            cat = t.category_name or "Slush Fund"
            amount = float(t.amount)
            net = abs(amount) if amount < 0 else -amount
            month_cat_totals[cat] += net

        month_chart_data = [
            {"label": cat, "value": round(total, 2)}
            for cat, total in sorted(
                month_cat_totals.items(), key=lambda x: -x[1]
            )
            if total > 0
        ]

        # Serialize transactions for this month.
        month_txn_list = []
        for t in sorted(txns_in_month, key=lambda x: (-abs(float(x.amount)), str(x.date))):
            cat = t.category_name or "Slush Fund"
            amount = float(t.amount)
            net = abs(amount) if amount < 0 else -amount
            month_txn_list.append({
                "Transaction Date": _fmt_date(t.date),
                "Description": t.description,
                "Category": cat,
                "Net": round(net, 2),
            })

        monthly_data.append({
            "month": mk,
            "chart_data": month_chart_data,
            "transaction_count": len(month_txn_list),
            "transactions": month_txn_list,
        })

    # --- Merchants (unique description → category mapping) ---
    seen_descs: set[str] = set()
    merchants = []
    for t in sorted(items, key=lambda x: x.description):
        if t.description not in seen_descs:
            seen_descs.add(t.description)
            merchants.append({
                "Description 1": t.description,
                "Category": t.category_name or "Slush Fund",
            })

    return {
        "merchants": merchants,
        "monthly": monthly_data,
        "overall_chart_data": overall_chart_data,
        "report_date_range": report_date_range,
        "trend_chart_data": trend_chart_data,
    }


@transactions_bp.route("/upload", methods=["GET", "POST"])
@login_required
def upload():
    if request.method == "POST":
        file = request.files["file"]

        if not file.filename.lower().endswith(".csv"):
            return render_template("upload.html", error="Only .csv files are accepted.")

        # Read raw bytes for file-level hash (ADR-0013) before parsing.
        file_bytes = file.read()

        # ADR-0005: category map is injected via the make_categorizer factory.
        # Phase 1: the per-user map is loaded from the database via Account
        # Settings service (ADR-0003 — no direct table access here).
        custom_map = get_category_map(g.user.id)
        generic_map = current_app.config.get("GENERIC_CATEGORY_MAP", {})
        categorize = make_categorizer(custom_map, generic_map)

        df = pd.read_csv(io.BytesIO(file_bytes), encoding="latin1")
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
        result = _process_upload(
            user_id=g.user.id,
            filename=file.filename,
            file_bytes=file_bytes,
            df=df,
        )

        if result["already_uploaded"]:
            return render_template(
                "upload.html",
                error="This file was already uploaded.",
            )

        # Render report from DB data rather than the in-memory df.
        report_vars = _build_report_from_db(g.user.id)

        if report_vars is None:
            # Edge case: all rows were duplicates and nothing remains.
            return render_template(
                "upload.html",
                error="No new transactions were found in this file.",
            )

        return render_template("report.html", **report_vars)

    return render_template("upload.html")


# ---------------------------------------------------------------------------
# Phase 3b: Transaction history view (ADR-0019)
# ---------------------------------------------------------------------------

@transactions_bp.route("/transactions", endpoint="history")
@login_required
def history():
    """Render the paginated transaction history view with filters.

    Query parameters (all optional, silently ignored if invalid):
      date_from   — ISO date string (YYYY-MM-DD)
      date_to     — ISO date string (YYYY-MM-DD)
      category_id — UUID string
      search      — free-text substring search
      page        — positive integer, default 1
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

    category_id = None
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

    prev_url = url_for("transactions.history", page=page - 1, **active_filters) if has_prev else None
    next_url = url_for("transactions.history", page=page + 1, **active_filters) if has_next else None

    if total_count == 0:
        showing_from = 0
        showing_to = 0
    else:
        showing_from = offset + 1
        showing_to = min(offset + limit, total_count)

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
        # active filter values for re-populating the form
        date_from=date_from.isoformat() if date_from else "",
        date_to=date_to.isoformat() if date_to else "",
        selected_category_id=str(category_id) if category_id else "",
        search=search or "",
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
    return render_template("transactions/edit.html", txn=txn, categories=categories)


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

    apply_forward = request.form.get("apply_forward") == "1"
    keyword_raw = request.form.get("keyword", "")
    apply_forward_keyword = keyword_raw.strip() if apply_forward and keyword_raw.strip() else None

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
        flash("Category not found or no longer available.", "error")
        return render_template("transactions/edit.html", txn=txn, categories=categories)
    except Exception:
        # Keyword write failed after transaction was already committed (partial success).
        flash(
            "Transaction recategorized, but the keyword rule could not be saved."
            " You can add it manually in Category Settings.",
            "warning",
        )
        return redirect(url_for("transactions.history"))

    # --- Flash success message ---
    if result.keyword_written:
        flash("Transaction recategorized and keyword rule saved.", "success")
    elif result.keyword_conflict:
        flash("Transaction recategorized. (Keyword rule already existed.)", "success")
    else:
        flash("Transaction recategorized.", "success")

    return redirect(url_for("transactions.history"))


# ---------------------------------------------------------------------------
# Phase 3b: Upload file management (ADR-0021)
# ---------------------------------------------------------------------------

@transactions_bp.route("/files", endpoint="files", methods=["GET"])
@login_required
def files_list():
    """List all uploaded files for the authenticated user."""
    uploads = get_uploads(g.user.id)
    return render_template("transactions/files.html", uploads=uploads)


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
    return redirect(url_for("transactions.files"))
