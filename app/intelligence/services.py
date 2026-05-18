"""Intelligence Layer service — report view model assembly.

Reads exclusively from the Transaction Engine service layer (ADR-0003).
No direct database access in this module.

Public API:
  build_report_view_model(user_id, period_months) -> dict | None

The view model dict shape is identical to what _build_report_from_db
returned in app/transactions/routes.py, so report_charts.js works
without changes (ADR-0024, Decision 3).

Sign convention: spend = abs(amount) when amount < 0 (debit).
Credits (amount > 0) contribute negative spend. This mirrors
net_amount() semantics from the Transaction Engine.

Referenced ADRs:
  ADR-0003: service-layer-only module communication
  ADR-0024: Intelligence Layer report ownership
"""

import datetime

from app.transactions.services import (
    DateRange,
    TransactionFilters,
    get_spend_by_category,
    get_transactions,
)


def _current_utc_year_month() -> tuple[int, int]:
    """Return (year, month) for the current UTC date."""
    now = datetime.datetime.now(datetime.timezone.utc)
    return now.year, now.month


def _previous_months(current_year: int, current_month: int, n: int) -> list[tuple[int, int]]:
    """Return the last n complete calendar months before the current month.

    Returns a list of (year, month) tuples in chronological order.
    E.g. if today is 2026-05-18, _previous_months(2026, 5, 6) returns:
    [(2025, 11), (2025, 12), (2026, 1), (2026, 2), (2026, 3), (2026, 4)]
    """
    months = []
    year, month = current_year, current_month
    for _ in range(n):
        month -= 1
        if month == 0:
            month = 12
            year -= 1
        months.append((year, month))
    return list(reversed(months))


def _load_all_transactions(user_id: str) -> list:
    """Load all transactions for a user by paginating get_transactions.

    The service layer caps individual calls at 200 rows (ADR-0017).
    This helper pages through until exhausted, returning the full list.
    """
    all_items = []
    offset = 0
    page_size = 200

    while True:
        page = get_transactions(user_id, TransactionFilters(limit=page_size, offset=offset))
        all_items.extend(page.items)
        if len(all_items) >= page.total_count:
            break
        offset += page_size

    return all_items


def build_report_view_model(user_id: str, period_months: int = 6) -> dict | None:
    """Assemble all template variables for templates/intelligence/report.html.

    Determines the last period_months complete calendar months before the
    current UTC month. Calls get_spend_by_category once per month in the
    window for DB-level aggregation (no application-level GROUP BY or row cap).
    Loads all transactions via paginated get_transactions for merchant table,
    per-category drill-down lists, per-month transaction lists, and date range.

    Returns:
        A dict with keys: merchants, monthly, overall_chart_data,
        report_date_range, trend_chart_data. Same shape as the old
        _build_report_from_db so report_charts.js works unchanged.
        Returns None if the user has no transactions.

    Args:
        user_id:       Authenticated user's UUID string.
        period_months: Number of complete calendar months to include.
                       Defaults to 6.
    """
    # --- Load all transactions (for merchant table, drilldowns, date range) ---
    items = _load_all_transactions(user_id)

    if not items:
        return None

    # --- Helpers ---
    def _fmt_date(d) -> str:
        if hasattr(d, "strftime"):
            return d.strftime("%b %d, %Y")
        return str(d)

    def _month_key(d) -> str:
        if hasattr(d, "year"):
            return f"{d.year}-{d.month:02d}"
        return str(d)[:7]

    # --- Date range from loaded transactions ---
    all_dates = [t.date for t in items]
    report_date_range = {
        "start": _fmt_date(min(all_dates)),
        "end": _fmt_date(max(all_dates)),
    }

    # --- Build per-month window using get_spend_by_category (DB aggregation) ---
    current_year, current_month = _current_utc_year_month()
    month_window = _previous_months(current_year, current_month, period_months)

    # Map month_key -> list[CategorySpend] from the DB aggregation layer.
    month_spend: dict[str, list] = {}
    for year, month in month_window:
        mk = f"{year}-{month:02d}"
        period = DateRange.for_month(year, month)
        month_spend[mk] = get_spend_by_category(user_id, period)

    # --- Build overall per-category totals by summing monthly results ---
    # category_name (with "Slush Fund" fallback) -> total spend (float)
    overall_totals: dict[str, float] = {}
    for spend_list in month_spend.values():
        for cs in spend_list:
            cat = cs.category_name or "Slush Fund"
            overall_totals[cat] = overall_totals.get(cat, 0.0) + float(cs.spend)

    # --- Build per-category transaction lists from loaded transactions ---
    # Used for the drill-down "transactions" field on overall_chart_data.
    # Sign convention: spend = abs(amount) for debits (amount < 0),
    # negative for credits — same as net_amount() in Transaction Engine.
    category_transactions: dict[str, list] = {}
    for t in items:
        cat = t.category_name or "Slush Fund"
        amount = float(t.amount)
        net = abs(amount) if amount < 0 else -amount
        if cat not in category_transactions:
            category_transactions[cat] = []
        category_transactions[cat].append({
            "Transaction Date": _fmt_date(t.date),
            "Description": t.description,
            "Category": cat,
            "Net": round(net, 2),
        })

    # --- Build overall_chart_data ---
    # Sort categories by total spend descending; skip categories with spend <= 0.
    sorted_cats = sorted(
        [(cat, total) for cat, total in overall_totals.items() if total > 0],
        key=lambda x: x[1],
        reverse=True,
    )

    overall_chart_data = []
    for cat, total in sorted_cats:
        cat_txns = sorted(
            category_transactions.get(cat, []),
            key=lambda x: (-x["Net"], x["Transaction Date"]),
        )
        overall_chart_data.append({
            "label": cat,
            "value": round(total, 2),
            "transactions": cat_txns,
        })

    # --- Build trend_chart_data ---
    # Labels are YYYY-MM keys in chronological order (window months only).
    sorted_month_keys = [f"{y}-{m:02d}" for y, m in month_window]
    all_categories = [cat for cat, _ in sorted_cats]

    trend_chart_data = {
        "labels": sorted_month_keys,
        "datasets": [
            {
                "label": cat,
                "values": [
                    round(
                        sum(
                            float(cs.spend)
                            for cs in month_spend.get(mk, [])
                            if (cs.category_name or "Slush Fund") == cat
                        ),
                        2,
                    )
                    for mk in sorted_month_keys
                ],
            }
            for cat in all_categories
        ],
    }

    # --- Build monthly_data ---
    # Group loaded transactions by month for per-month drilldowns.
    # Months are derived from the actual transaction dates (not just the window)
    # to preserve historical data outside the aggregation window.
    from collections import defaultdict

    month_items: dict[str, list] = defaultdict(list)
    for t in items:
        mk = _month_key(t.date)
        month_items[mk].append(t)

    all_transaction_months = sorted(month_items.keys())

    monthly_data = []
    for mk in all_transaction_months:
        txns_in_month = month_items[mk]

        # Per-month category chart data from DB aggregation if in window,
        # else computed from the loaded transactions for months outside the window.
        if mk in month_spend:
            month_cat_totals_raw = {
                (cs.category_name or "Slush Fund"): float(cs.spend)
                for cs in month_spend[mk]
            }
        else:
            month_cat_totals_raw = {}
            for t in txns_in_month:
                cat = t.category_name or "Slush Fund"
                amount = float(t.amount)
                net = abs(amount) if amount < 0 else -amount
                if net > 0:
                    month_cat_totals_raw[cat] = month_cat_totals_raw.get(cat, 0.0) + net

        month_chart_data = [
            {"label": cat, "value": round(total, 2)}
            for cat, total in sorted(
                month_cat_totals_raw.items(), key=lambda x: -x[1]
            )
            if total > 0
        ]

        # Per-month transaction list sorted by abs(amount) desc.
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

    # --- Build merchants (unique description -> category, sorted by description) ---
    seen_descs: set[str] = set()
    merchants = []
    for t in sorted(items, key=lambda x: x.description):
        if t.description not in seen_descs:
            seen_descs.add(t.description)
            merchants.append({
                "description": t.description,
                "Category": t.category_name or "Slush Fund",
            })

    return {
        "merchants": merchants,
        "monthly": monthly_data,
        "overall_chart_data": overall_chart_data,
        "report_date_range": report_date_range,
        "trend_chart_data": trend_chart_data,
    }
