"""Transaction Engine routes — upload and report.

All routes require authentication (ADR-0006). The category map is loaded from
the Account Settings service, injecting the per-user map via the same factory
closure used in Phase 0 (ADR-0005). The call site is unchanged; only the
source of the map has moved from a JSON file to the database.

Phase 3a: the upload POST handler writes to the database via _process_upload
and renders the report from DB data via get_transactions (ADR-0016, ADR-0017).
"""

import io
from collections import defaultdict
from decimal import Decimal

import pandas as pd
from flask import Blueprint, current_app, g, render_template, request

from app.account_settings.services import get_category_map
from app.middleware.auth import login_required
from app.transactions.services import (
    TransactionFilters,
    _process_upload,
    get_transactions,
    make_categorizer,
    net_amount,
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
