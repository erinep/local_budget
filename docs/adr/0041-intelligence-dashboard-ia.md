# ADR 0041 - Intelligence Dashboard Information Architecture

- **Status:** Accepted
- **Date:** 2026-05-24 (rewritten 2026-05-31)
- **Phase:** 5d
- **Deciders:** erin p

## Context

Phase 5d required defining what questions the dashboard should answer before building widgets. The 5a report was a structural placement exercise; 5d is a designed product. This ADR records the IA decisions, the widget catalog that shipped, and what was deferred.

## Options considered

### Option A — Multiple report templates

Separate views for "monthly summary", "trends", "comparison", etc. Each answers one question in depth. User navigates between them.

Flexible, but fragments the experience and requires the user to know which template to consult. High surface area to maintain.

### Option B — Single persistent dashboard, widget-per-question (selected)

One dashboard at `/intelligence/dashboard`. Each widget is scoped to answer one question clearly. Widgets are independently assembled and can be composed or reordered without coupling.

Lower nav overhead, easier to scan, fits the read-only intelligence charter for Phase 5.

## Decision

**Option B.** The dashboard answers four questions, with widgets assigned by primary responsibility:

1. **How has my spending per category trended over time?** → Category Trends (configurable date range + granularity, category line toggling, total overlay).
2. **Am I on track with my budget this month?** → Category Radar (actual spend as % of budget per category, visual budget target polygon, month navigation).
3. **Which categories changed most vs. last month?** → Category Movers (ranked MoM delta table).
4. **How consistent and well-categorized is my spending?** → Category Profile (per-category CV, consistency labels, categorization health summary).

## Widget catalog

### Category Trends

Line chart showing spend per category over a user-selected date range. Controls:
- **Date range picker**: This month / 3M / 6M / 12M / 24M. All ranges include the current month MTD as the final data point.
- **Granularity picker**: Daily / Weekly / Monthly. Drives the x-axis bucket size.
- **Category pills**: toggle individual category lines on/off. First click on any pill when all are active isolates that category; subsequent clicks toggle. An "All" pill resets to all visible.
- **Show total checkbox**: overlays a bold total-spend line across all categories; dims individual lines when active.

Category pill visibility and show-total state persist across picker changes via `localStorage` (no full-page reload — HTMX swaps the widget fragment only). Chart initialises via `htmx:afterSettle` + `requestAnimationFrame` to ensure correct container sizing.

Clicking any chart point routes to `/transactions` filtered to that period and category (drilldown).

Backed by `get_spend_by_category_grouped` — a single batched SQL query regardless of date range or granularity (ADR-0042). The prior N+1 per-month loop is eliminated.

### Category Radar

Spider chart with axes for the user's top spending categories that have a budget target set. Normalised to **% of budget**: each axis runs 0–N%, and the budget target is a regular grey polygon at 100% on every axis. The teal actual polygon shows how far the selected month's spend reaches on each axis.

A horizontal pill strip lets the user navigate between the current MTD month and the 11 prior complete months. The budget polygon is constant (standing targets, not month-specific); only the actual polygon changes.

**Why % of budget, not raw dollars:** raw dollar axes collapse all but the highest-spending category toward the centre when magnitude varies significantly across categories (e.g. $2,800 "fun" vs. $180 "food"). Normalising to budget makes all axes comparable and makes the chart immediately readable — inside the grey polygon means on track, outside means over.

**Unbudgeted categories:** axes are limited to categories with a budget target. Top-spending categories without a budget are excluded from the axes and listed in an amber warning strip at the bottom of the widget with a link to set budgets. Individual transactions in the detail panel are flagged with a red "no budget" pill if their category has no target.

The detail panel alongside the chart shows:
- Total outflow for the selected month
- Top 10 transactions by amount, with description, category chip, and dollar value
- An amber "unusual" badge on any transaction ≥ 2 standard deviations above that category's 12-month per-transaction mean

### Category Movers

Ranked table comparing the last two complete calendar months (MTD excluded to avoid distorted comparisons). Columns: category name, prior month, current month, delta (dollar + percentage). Sorted by absolute delta descending, top 10 shown.

### Category Profile

Per-category statistics table covering the selected period (default 12 months). Columns: transaction count, total spend, mean, standard deviation, coefficient of variation, consistency label (Consistent CV < 0.5 / Mixed 0.5–1.0 / Irregular > 1.0). Uncategorized spend is included as a separate flagged row.

Summary header: total transactions, % categorized, % spend categorized, two small pie charts (categorization health, spend coverage). Sits at the bottom of the dashboard as an operational health check.

## Consequences

- **Positive:** each widget has a clear job; straightforward to assess whether a new widget earns its place.
- **Positive:** Category Trends and Category Movers answer question 3 from complementary angles — trajectory over time vs. latest month delta.
- **Positive:** normalising the radar to % of budget makes it immediately readable regardless of magnitude spread across categories. The budget target is the natural reference shape — more meaningful than a prior-month overlay.
- **Positive:** HTMX fragment swaps + `localStorage` for picker state means picker changes feel instant and category visibility survives navigation.
- **Negative:** Category Movers is functional but visually thin — no bar chart, no click-through to transactions, no budget context. Flagged as a known weakness; improvement deferred.
- **Negative:** users with no budget targets get a degraded radar — axes collapse and the widget prompts them to set budgets. Acceptable given that budget setup is a prerequisite for meaningful radar use.
- **Follow-ups required:** Category Movers visual overhaul (deferred to backlog); CSV export and custom dashboard builder descoped from 5d.

## Notes

The "Compare prev. month" overlay originally specified in this ADR was replaced by the budget comparison ring. A prior-month overlay has no normative anchor — it shows change but not whether that change is good or bad. The budget polygon answers the question the overlay was trying to answer: "is this month's shape acceptable?" This decision was initially documented in ADR-0043; that ADR is retired and its substance is consolidated here.

`get_spend_by_category_grouped` (ADR-0042) is the query contract that makes the date-range and granularity pickers viable — flat query cost regardless of the selected window.
