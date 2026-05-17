"""Home (dashboard) blueprint routes.

ADR-0011 — Navigation and Landing Page Contract. The dashboard is the
post-login landing surface at ``/`` and a cross-module composition surface;
it owns no data and renders inert links to other modules' surfaces in
Phase 2. In later phases it gains counts (Phase 3), a Budget card
(Phase 4), and narrative summaries (Phase 5).

This blueprint is intentionally outside ADR-0004's enumerated module list
because the dashboard is a presentation surface, not an architectural
module. See ADR-0011 point 5 for the rationale.

All routes require an authenticated user (ADR-0006).
"""

from flask import Blueprint, render_template

from app.middleware.auth import login_required

home_bp = Blueprint("home", __name__)


@home_bp.route("/", methods=["GET"])
@login_required
def index():
    """Render the post-login dashboard.

    Phase 2: two inert cards linking to Upload and Categories. Future phases
    extend this template without changing the URL or contract.
    """
    return render_template("home/index.html")
