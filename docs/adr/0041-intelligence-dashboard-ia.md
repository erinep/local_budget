# ADR 0041 - Intelligence Dashboard Information Architecture

- **Status:** Accepted
- **Date:** 2026-05-24
- **Phase:** 5d
- **Deciders:** erin p

## Context

Phase 5d required defining what questions the dashboard should answer before building widgets. The 5a report was a structural placement exercise; 5d is a designed product. This ADR records the IA decisions, the widget catalog that resulted, and what was deferred — per the roadmap's requirement for a design note before code.

## Options considered

### Option A — Multiple report templates

Separate views for "monthly summary", "trends", "comparison", etc. Each answers one question in depth. User navigates between them.

Flexible, but fragments the experience and requires the user to know which template to consult. High surface area to maintain.

### Option B — Single persistent dashboard, widget-per-question

One dashboard at `/intelligence/dashboard`. Each widget is scoped to answer one question clearly. Widgets are independently assembled and can be composed or reordered without coupling.

Lower nav overhead, easier to scan, fits the read-only intelligence charter for Phase 5.

## Decision

We chose **Option B**. The dashboard answers three questions, with widgets assigned by primary responsibility:

1. **Where did my money go last month?** → Category Radar (12-month pill navigation, top-10 transactions, outlier flags).
2. **How does this month compare to last?** → Category Radar prev-month overlay (visual) + Category Movers (quantitative delta table, full months only to avoid MTD distortion).
3. **Which categories are trending up?** → Category Trends (line chart, 12-month trajectory per category + total overlay) for the long view; Category Movers (ranked absolute MoM delta) for the recent signal. The two are complementary: Trends shows direction over time, Movers surfaces the latest change.

A fifth widget — Category Profile — answers the operational question "Is my data clean?" and sits at the bottom of the dashboard as a secondary concern.

## Widget catalog

### Category Trends

Line chart showing monthly spend per category over 12 months, with a bold total-spend overlay. Each category is a separate line; a palette of 8 colours cycles across them. Interactive pill buttons beneath the chart toggle individual category lines; an "All" pill toggles the whole set; a checkbox shows or hides the total line. Answers the long-arc version of question 3.

### Category Radar

Spider chart with 7 axes — one per top-spending category (ranked by combined 12-month spend). A horizontal pill strip across the top lets the user select any of the 12 available months (current MTD + 11 prior complete months). Only the selected month's dataset is drawn. A "Compare prev. month" toggle in the top-right corner overlays the immediately preceding month in orange on the same axes, so shape differences are visible at a glance.

Alongside the chart, a fixed-width detail panel shows:
- Total outflow for the selected month
- Top 10 transactions by amount, with description, category chip, and dollar value
- An amber "unusual" badge on any transaction whose amount is ≥ 2 standard deviations above that category's 12-month per-transaction mean (sample std dev, n–1)

The overlay toggle tracks the active pill: switching months while the overlay is on always shows that month vs. the one before it.

### Category Movers

Ranked table comparing the last two complete calendar months (full months only — MTD is excluded to avoid distorted comparisons). Columns: category name, prior month spend, current month spend, delta (dollar amount + percentage). Sorted by absolute delta descending, top 10 shown. Red ▲ for increases, green ▼ for decreases. Categories that appear in only one month are included with a zero baseline for the absent month. Answers the recent-signal version of question 3.

### Category Profile

Per-category statistics table covering the selected period (default 12 months). For each category: transaction count, total spend, mean transaction value, standard deviation, coefficient of variation (std dev ÷ mean), and a consistency label — Consistent (CV < 0.5), Mixed (CV 0.5–1.0), Irregular (CV > 1.0). Uncategorized transactions are included as a separate row and flagged visually.

Summary header shows: total transactions, % categorized, % spend categorized, with two small pie charts (categorization health, spend coverage). Sits at the bottom of the dashboard as an operational health check rather than a primary spending insight.

## Consequences

- Positive: each widget has a clear job; easy to assess whether a new widget earns its place by checking which question it answers.
- Positive: Category Trends and Category Movers answer question 3 from different angles — trajectory vs. latest delta — without duplicating each other.
- Positive: the standalone Outlier Transactions, Subscription Detector, and Top Transactions widgets were removed as redundant once the Radar detail panel covered the same ground more contextually.
- Negative: custom date-range controls and period-granularity toggles are absent; the dashboard is locked to a rolling 12-month window. Sufficient for v1; can be revisited.
- Negative: drilldowns are not yet fully implemented. Category Profile row → `/transactions?category=X` is the one outstanding gap against the 5d exit criterion; tracked as in-progress.
- Follow-ups required: implement Category Profile drilldown (closes the 5d exit criterion); defer CSV export and custom dashboard builder indefinitely.

## Notes

Report controls (item 4 of the 5d work items) are implemented more rigidly than originally specced — the 12-month window is fixed rather than user-configurable. This was a deliberate scope reduction: the primary use cases are covered and a date-range picker adds UI complexity without answering a new question.

Items 6 (CSV export) and 7 (custom dashboard builder) are deferred indefinitely.
