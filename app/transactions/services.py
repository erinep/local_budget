"""Pure, stateless service functions for the Transaction Engine.

No Flask imports. All functions are callable without an application context.
"""

from typing import Callable


NON_TRACKED_KEYWORDS = [
    "PAYMENT",
    "TRANSFER",
    "E-TRANSFER",
    "AUTOPAY",
    "THANK YOU",
    "CREDIT CARD PAYMENT",
]


def make_categorizer(custom_map: dict, generic_map: dict) -> Callable[[str], str]:
    """Return a single-argument callable suitable for DataFrame.apply.

    ADR 0005 — Option B (factory closure). The returned closure carries its own
    maps so the call site in the route handler does not change when map loading
    moves to the database in Phase 1.
    """
    def categorize(desc: str) -> str:
        desc = str(desc).upper()
        for category_map in (custom_map, generic_map):
            for category, keywords in category_map.items():
                for keyword in keywords:
                    if str(keyword).upper() in desc:
                        return category
        return "Slush Fund"

    return categorize


def net_amount(row) -> float:
    """Return the net spend for a transaction row.

    Payments, transfers, and other non-tracked keywords are zeroed out.
    Money-out (negative CAD$) becomes positive net spend.
    Money-in (positive CAD$, e.g. refunds) becomes negative net.
    """
    amount = row["CAD$"]
    desc = str(row["Description 1"]).upper()

    if any(keyword in desc for keyword in NON_TRACKED_KEYWORDS):
        return 0
    if amount > 0:
        return -amount
    return abs(amount)


def series_to_chart_data(series) -> list:
    """Convert a pandas Series of category totals to chart-ready dicts."""
    cleaned = series[series > 0].sort_values(ascending=False)
    return [
        {"label": str(label), "value": round(float(value), 2)}
        for label, value in cleaned.items()
    ]


def serialize_transactions(frame, *, sort_by) -> list:
    """Serialize a transactions DataFrame slice to a list of dicts for templates."""
    return (
        frame[["Transaction Date", "Description 1", "Category", "Net"]]
        .sort_values(sort_by, ascending=[False] * len(sort_by))
        .assign(
            **{
                "Transaction Date": lambda data: data["Transaction Date"].dt.strftime("%b %d, %Y"),
                "Net": lambda data: data["Net"].round(2),
            }
        )
        .rename(columns={"Description 1": "Description"})
        .to_dict("records")
    )
