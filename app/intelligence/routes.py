"""Intelligence Layer routes — report and future intelligence features.

Blueprint: intelligence_bp, url_prefix="/intelligence" (ADR-0004, ADR-0024).

Route table:
  GET /intelligence/report    report    Render the full report for the authenticated user.
"""

from flask import Blueprint, flash, g, redirect, render_template, url_for

from app.intelligence.services import build_report_view_model
from app.middleware.auth import login_required

intelligence_bp = Blueprint("intelligence", __name__, url_prefix="/intelligence")


@intelligence_bp.route("/report", endpoint="report")
@login_required
def report():
    """Render the spending report for the authenticated user.

    Assembles the view model from the Transaction Engine service layer and
    renders templates/intelligence/report.html. Redirects to the upload page
    with an informational flash message if the user has no transactions.
    """
    view_model = build_report_view_model(g.user.id)

    if view_model is None:
        flash("Upload a file to see your report.", "info")
        return redirect(url_for("transactions.upload"))

    return render_template("intelligence/report.html", **view_model)
