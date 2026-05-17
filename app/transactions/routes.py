"""Transaction Engine routes — upload and report.

All routes require authentication (ADR-0006). The category map is loaded from
the Account Settings service, injecting the per-user map via the same factory
closure used in Phase 0 (ADR-0005). The call site is unchanged; only the
source of the map has moved from a JSON file to the database.
"""

import pandas as pd
from flask import Blueprint, g, render_template, request

from app.account_settings.services import get_category_map
from app.middleware.auth import login_required
from app.transactions.services import (
    make_categorizer,
    net_amount,
    serialize_transactions,
    series_to_chart_data,
)

transactions_bp = Blueprint("transactions", __name__)


@transactions_bp.route("/upload", methods=["GET", "POST"])
@login_required
def upload():
    if request.method == "POST":
        file = request.files["file"]

        if not file.filename.lower().endswith(".csv"):
            return render_template("upload.html", error="Only .csv files are accepted.")

        # ADR-0005: category map is injected via the make_categorizer factory.
        # Phase 1: the per-user map is loaded from the database via Account
        # Settings service (ADR-0003 — no direct table access here).
        # The generic map from app.config is passed as the fallback so that any
        # category not in the user's custom map still gets classified correctly.
        from flask import current_app
        custom_map = get_category_map(g.user.id)
        generic_map = current_app.config.get("GENERIC_CATEGORY_MAP", {})
        categorize = make_categorizer(custom_map, generic_map)

        df = pd.read_csv(file, encoding="latin1")
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
        df["Month"] = df["Transaction Date"].dt.to_period("M")
        report_date_range = {
            "start": df["Transaction Date"].min().strftime("%b %d, %Y"),
            "end": df["Transaction Date"].max().strftime("%b %d, %Y"),
        }

        summary = df.groupby("Category")["Net"].sum().sort_values(ascending=False)
        monthly_pivot = (
            df.groupby(["Month", "Category"])["Net"]
            .sum()
            .unstack(fill_value=0)
            .sort_index()
        )
        monthly_pivot.index = monthly_pivot.index.astype(str)

        monthly_data = []
        for month, group in df.groupby("Month"):
            month_summary = group.groupby("Category")["Net"].sum().sort_values(ascending=False)
            month_transactions = serialize_transactions(group, sort_by=["Net", "Transaction Date"])
            monthly_data.append({
                "month": str(month),
                "chart_data": series_to_chart_data(month_summary),
                "transaction_count": len(month_transactions),
                "transactions": month_transactions,
            })

        merchants = (
            df[["Description 1", "Category"]]
            .drop_duplicates()
            .sort_values("Description 1")
        )

        trend_chart = {
            "labels": monthly_pivot.index.tolist(),
            "datasets": [
                {
                    "label": str(category),
                    "values": [round(float(value), 2) for value in monthly_pivot[category].tolist()],
                }
                for category in monthly_pivot.columns
            ],
        }

        overall_chart_data = []
        for category, value in summary[summary > 0].sort_values(ascending=False).items():
            category_transactions = serialize_transactions(
                df[df["Category"] == category],
                sort_by=["Net", "Transaction Date"],
            )
            overall_chart_data.append({
                "label": str(category),
                "value": round(float(value), 2),
                "transactions": category_transactions,
            })

        return render_template(
            "report.html",
            merchants=merchants.to_dict("records"),
            monthly=monthly_data,
            overall_chart_data=overall_chart_data,
            report_date_range=report_date_range,
            trend_chart_data=trend_chart,
        )

    return render_template("upload.html")
