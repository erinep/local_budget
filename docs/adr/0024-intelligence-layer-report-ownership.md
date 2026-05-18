---
adr: 0024
title: Intelligence Layer Report Ownership — Module Assignment, URL Structure, and Rendering Architecture
status: Accepted
date: 2026-05-18
phase: P5 (structural groundwork laid in P3c)
deciders: erin
---

## Context

The existing report (`report.html`) is rendered as a side effect of `POST /upload` inside `transactions_bp`. There is no stable URL — a user cannot navigate to the report, link to it, or return to it after leaving. The data-building function `_build_report_from_db` lives in `app/transactions/routes.py`, performs a 200-row-capped `get_transactions` call, and does its own Python-level GROUP BY, duplicating aggregation logic that now belongs to `get_spend_by_category` and `get_spend_history` (ADR-0023, Phase 3c). The charts are rendered client-side by `static/report_charts.js` against data the server serializes into `data-chart` attributes.

Three structural problems must be resolved before Phase 5 work begins:

1. **Wrong module ownership.** The Transaction Engine's job is to persist transactions and expose a read API. Interpreting and presenting that data as visual insights is Intelligence Layer territory. Having `transactions_bp` own `report.html` violates the single-responsibility principle in [architecture.md](../architecture.md) and will create merge conflicts and coupling once the Intelligence Layer is actively developed.
2. **No stable URL.** Report-as-POST-side-effect is a UX and navigation dead end. The history view (`/transactions`) introduced in Phase 3b has its own GET route; the report must as well.
3. **`_build_report_from_db` is stale and silently incorrect.** The 200-row cap silently undercounts users with more than 200 transactions. It duplicates GROUP BY logic that ADR-0023 moved to the service layer. It must be replaced.

Binding constraints from prior ADRs:
- **ADR-0003** — no module may query another module's tables; the Intelligence Layer must read exclusively via `get_spend_by_category` and `get_spend_history`.
- **ADR-0004** — the Intelligence Layer blueprint (`intelligence_bp`, prefix `/intelligence`) was named when the blueprint layout was decided. Its introduction does not require a new structural decision.
- **ADR-0023** — `get_spend_by_category` and `get_spend_history` are the canonical aggregation surface; `_build_report_from_db` must be replaced with calls to these functions.

Relevant risks ([risks.md](../risks.md)): "Cross-module API contract drift" (High, P3a+) — the report must consume the Transaction Engine only through the Phase 3c API, never directly; "Scope creep in Intelligence Layer" (High, P5) — the report page is a concrete, bounded deliverable, not an open-ended intelligence feature.

## Decision 1 — Module ownership

**The Intelligence Layer owns the report page.** A new blueprint `intelligence_bp` (defined in `app/intelligence/routes.py`, URL prefix `/intelligence` per ADR-0004) owns the route, the template, and the data-assembly logic. `transactions_bp` retains no report-rendering code.

The data assembly function that replaces `_build_report_from_db` lives in `app/intelligence/services.py` and calls `get_spend_by_category` and `get_spend_history` from `app.transactions.services` — service-layer access only, consistent with ADR-0003.

`_build_report_from_db` in `app/transactions/routes.py` is deleted in the same PR that introduces `intelligence_bp`. No deprecation period is needed because it has no callers outside the upload handler.

## Decision 2 — Report URL structure

**The report is a stable GET route at `/intelligence/report`.**

`POST /upload` no longer renders `report.html`. On successful upload it issues a redirect to `GET /intelligence/report`. The report route reads from the database for the current user, assembles the view model, and renders the template. The URL is bookmarkable, navigable via the nav bar, and reachable independently of upload.

URL contract:

| Method | Path | Handler | Description |
|---|---|---|---|
| `GET` | `/intelligence/report` | `intelligence_bp` | Render the full report for the authenticated user. Returns 200 with `report.html`, or redirects to `/upload` with a flash message if the user has no transactions. |

`url_for('intelligence.report')` is the canonical reference in templates and redirects. The `transactions.upload` POST handler replaces its `render_template("report.html", ...)` call with `redirect(url_for('intelligence.report'))`.

## Decision 3 — Rendering architecture

**Hybrid: server assembles typed data from the service layer; client-side JS renders interactive charts.**

The three options were evaluated against the constraint that custom dashboards are a future goal.

### Option A — Pure server-side (Jinja, static SVG or image charts)

Server renders all output. Charts are generated as SVG or via a Python charting library. No client-side chart code.

**Pros.** No JS build step; simplest possible server. Works without JavaScript enabled.

**Cons.** Interactive charts (click-to-drilldown, hover tooltips, responsive sizing) are impractical with server-rendered SVG at this feature level. The existing `report_charts.js` already provides working interaction that would need to be rebuilt or abandoned. Custom dashboards that let users configure which charts appear and in what order require either a page reload per configuration change (hostile UX) or client-side state — at which point the approach becomes hybrid anyway. This option does not extend toward custom dashboards without major rework.

**Verdict:** Does not meet the custom-dashboard extensibility goal.

### Option B — Hybrid: server assembles typed data, JS renders charts (selected)

Server calls the Transaction Engine service layer, assembles a typed view model, and serializes it into the page (in `data-chart` attributes or a `<script type="application/json">` block). The chart-rendering JS reads the serialized data and draws the charts. No separate fetch required.

**Pros.** This is the current model — the rendering machinery in `report_charts.js` already works and only needs to be moved, not rewritten. The server-side boundary is clean: the view model is a pure data structure built from typed service-layer returns (`list[CategorySpend]`, `list[PeriodSpend]`). The JS layer is stateless — it reads data and renders; it does not query or mutate. Custom dashboards are feasible by extending the view model and adding new chart-host divs; the chart renderer can handle new data shapes without a rendering architecture change.

**Cons.** The full data set is serialized into the initial HTML response. For the scale of a personal finance app (one user's transactions), this is not a concern. If the data grows large enough to matter, moving to Option C (JSON endpoint) is a natural evolution that does not change the rendering contract.

**Verdict:** Fits the current Flask/Jinja stack, preserves working JS, enables custom dashboards by extension rather than rewrite. Selected.

### Option C — API-driven: JS fetches from a JSON endpoint

A JSON route (e.g., `GET /intelligence/report.json`) returns the view model. A JS frontend fetches it on page load and renders the charts.

**Pros.** Complete separation between data and presentation. JSON endpoint is reusable across surfaces (a future mobile PWA, a future custom dashboard that assembles its own data calls). Natural fit for custom dashboards where the client might request different data shapes.

**Cons.** Adds a round-trip on page load, a loading state, and error handling in JS. The JSON endpoint must be protected by the same auth middleware as the page route — adding a new auth surface. The current Flask app has no AJAX convention, no standard error envelope, and no content negotiation pattern; adding one requires a new ADR and cross-cutting work before Option C can ship. This is the right long-term direction but the wrong decision to make before Phase 5 even starts.

**Verdict:** Appropriate if and when a custom dashboard needs to compose data from multiple sources independently. A future ADR should revisit if Phase 5 ships a configurable dashboard.

### Option D — HTMX fragments

Server renders HTML fragments; HTMX replaces sections of the page on interaction.

**Pros.** Less client-side JS than a full fetch-and-render approach. Progressive enhancement.

**Cons.** Introduces a new dependency (HTMX) and a new rendering convention with no existing precedent in the codebase. The existing `report_charts.js` is a custom canvas-less SVG renderer that HTMX cannot replace without a full rewrite of the chart code. HTMX's value is in form interactions and partial updates, not in data visualization. This option would reduce JS complexity in some areas while leaving the chart-rendering problem entirely unsolved.

**Verdict:** Does not address the chart-rendering requirement; deferred.

## Decision 4 — `_build_report_from_db` fate

`_build_report_from_db` is deleted. It is replaced by a new function `build_report_view_model(user_id: str, period_months: int = 6) -> dict | None` in `app/intelligence/services.py`. The replacement:

- Calls `get_spend_by_category(user_id, period)` from `app.transactions.services` for overall spend totals.
- Calls `get_spend_history(user_id, category_id=None, periods=[...])` for monthly trend data. Because `get_spend_history` requires a `category_id`, the implementation builds per-month totals by calling `get_spend_by_category` once per month in the `periods` window, not `get_spend_history` directly. (See Notes for rationale.)
- Returns `None` if the user has no transactions; the caller redirects to `/upload` with a flash message.
- Removes the 200-row cap. The aggregation methods operate at the DB layer with no application-level row limit.
- Uses the `DateRange.for_month(year, month)` factory from ADR-0023 for month boundary arithmetic.

The signed-amount convention (`spend = abs(amount)` where `amount < 0`) is preserved unchanged from the existing code and from ADR-0023's sign convention.

The `merchants` section currently in `report.html` (unique description → category mapping) is moved to the Intelligence Layer template but defers to a future decision on whether it belongs in the Intelligence Layer or the Account Settings module. For now it is preserved by including it in the view model via a call to `get_transactions` — the existing ADR-0017 API — with a sufficiently large limit. This is explicitly temporary; when Account Settings owns merchant mapping (Phase 2 follow-up), this section migrates there.

## Decision 5 — Chart library

**The chart library decision is deferred.** `report_charts.js` is a custom renderer that covers the existing chart types (donut, grouped bar). It is not pinned to an external library, which means there is no upgrade or licensing decision to make. When the Intelligence Layer adds new chart types that the custom renderer cannot handle — or when Phase 5's custom dashboard work begins — that is the right moment to evaluate whether to extend the custom renderer or adopt a library (Chart.js, Observable Plot, or similar). A future ADR will cover that decision.

The existing `report_charts.js` is moved from `static/` to remain at `static/report_charts.js` (no path change needed — it is a static file, not module-scoped). The template `report.html` moves to `templates/intelligence/report.html` to co-locate with the Intelligence Layer blueprint.

## Consequences

- **Positive.** The Transaction Engine blueprint is free of presentation logic. Its `routes.py` shrinks by approximately 170 lines. The module now owns exactly what it should: upload processing and the read API surface.
- **Positive.** `/intelligence/report` is a stable, navigable, bookmarkable GET route. Users can return to the report after navigating away. The nav bar can link to it directly.
- **Positive.** The 200-row cap in `_build_report_from_db` is eliminated. Users with more than 200 transactions now see correct report data.
- **Positive.** The view model is built from the typed ADR-0023 service surface (`list[CategorySpend]`, `list[PeriodSpend]`) rather than from a raw `Transaction` list with manual GROUP BY. The data-assembly code is smaller, tested at the service layer, and not duplicating SQL the DB layer already handles.
- **Positive.** The hybrid rendering architecture preserves the working `report_charts.js` chart renderer with no rewrite. Moving to Option C (JSON endpoint) later is an additive change — it adds a `GET /intelligence/report.json` route without modifying the existing page route or template.
- **Negative.** `POST /upload` now issues a redirect to `GET /intelligence/report` rather than rendering inline. This is a minor UX change (one extra HTTP round-trip on upload success). It is the correct behavior for POST-redirect-GET and eliminates the "resubmit form?" browser warning on reload.
- **Negative.** `app/intelligence/` is introduced before Phase 5 is active. This is intentional — structural placement is a Phase 3c concern; intelligence features are Phase 5 concerns. The blueprint registers with `url_prefix="/intelligence"` and initially exposes only the report route.
- **Negative.** The `merchants` section in the report view model still calls `get_transactions` (ADR-0017) with a large limit. This is a known temporary coupling, explicitly labeled for removal when Account Settings owns merchant-category mapping.
- **Follow-up.** The implementation agent must register `intelligence_bp` in `create_app()` after `transactions_bp`, following the convention in ADR-0004.
- **Follow-up.** The implementation agent must move `templates/report.html` to `templates/intelligence/report.html` and update all `render_template` references.
- **Follow-up.** The test-writer agent must cover: `GET /intelligence/report` with no transactions (redirect to upload), with transactions (200 + correct chart data), and the `build_report_view_model` service function independently of the route.
- **Follow-up.** The `report_charts.js` file path does not change, but the `{% block scripts %}` include in `templates/intelligence/report.html` must reference it via `url_for('static', filename='report_charts.js')` — unchanged from the current template.
- **Follow-up.** When Phase 5 adds additional intelligence routes (alerts, monthly summaries), they are added to `intelligence_bp` without structural changes.
- **Follow-up.** If Phase 5 introduces a configurable dashboard where users select which charts appear, revisit Option C (API-driven JSON endpoint) at that time with a new ADR.

## Notes

**Why `get_spend_history` is not used for monthly trend data.** ADR-0023 defines `get_spend_history(user_id, category_id, periods)` as a per-category history function: it returns spend for one specific category across multiple periods. The trend chart on the report page requires all categories across multiple months — a "transpose" of `get_spend_history`'s shape. The correct approach is to call `get_spend_by_category` once per month in the window (e.g., six calls for a six-month window), collect the results, and pivot them into the trend chart structure. This is N small indexed queries on a personal-finance dataset and is acceptable. If a future phase requires a single-query multi-category multi-period aggregate, that is a new service method (requiring a new ADR), not a misuse of `get_spend_history`.

**On the URL prefix `/intelligence`.** ADR-0004 recorded this prefix when the blueprint table was established. The path `/intelligence/report` is explicit about what module owns it. A shorter path like `/report` could be used, but it would hide ownership and collide with any future top-level route with that name. Explicit prefix is preferred.

**Relationship to Phase 5 scope.** This ADR resolves structural placement only. It does not introduce LLM-backed features, alerts, anomaly detection, or any of the Phase 5 intelligence items. The Intelligence Layer blueprint starting with a report page is intentional: the module exists and has a real route before Phase 5 begins, so Phase 5 work lands in an established module with a known structure.
