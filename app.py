import json
import os

import pandas as pd
from flask import Flask, render_template, request

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 5 * 1024 * 1024  # 5 MB

BASE_DIR = os.path.dirname(os.path.abspath(__file__))


def load_category_map(filename):
    path = os.path.join(BASE_DIR, filename)
    if not os.path.exists(path):
        return {}

    with open(path, "r") as f:
        return json.load(f)


GENERIC_CATEGORY_MAP = load_category_map("generic_categories.json")
CUSTOM_CATEGORY_MAP = load_category_map("custom_categories.json")
NON_TRACKED_KEYWORDS = [
    "PAYMENT",
    "TRANSFER",
    "E-TRANSFER",
    "AUTOPAY",
    "THANK YOU",
    "CREDIT CARD PAYMENT",
]


def categorize(desc):
    desc = str(desc).upper()

    for category_map in (CUSTOM_CATEGORY_MAP, GENERIC_CATEGORY_MAP):
        for category, keywords in category_map.items():
            for keyword in keywords:
                if str(keyword).upper() in desc:
                    return category

    return "Slush Fund"


def net_amount(row):
    amount = row["CAD$"]
    desc = str(row["Description 1"]).upper()

    if any(keyword in desc for keyword in NON_TRACKED_KEYWORDS):
        return 0
    if amount > 0:
        return -amount
    return abs(amount)


def series_to_chart_data(series):
    cleaned = series[series > 0].sort_values(ascending=False)
    return [
        {"label": str(label), "value": round(float(value), 2)}
        for label, value in cleaned.items()
    ]


def serialize_transactions(frame, *, sort_by):
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


@app.route("/", methods=["GET", "POST"])
def upload():
    if request.method == "POST":
        file = request.files["file"]

        if not file.filename.lower().endswith(".csv"):
            return render_template("upload.html", error="Only .csv files are accepted.")

        df = pd.read_csv(file, encoding="latin1")
        df = df[["Transaction Date", "Description 1", "CAD$"]]

        df["Transaction Date"] = pd.to_datetime(
            df["Transaction Date"],
            format="mixed",
            errors="coerce"
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


if __name__ == "__main__":
    app.run(debug=os.environ.get("FLASK_DEBUG", "").lower() == "true")
