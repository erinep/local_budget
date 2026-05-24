# Phase 5d — Information Architecture

**Type:** Design note (not an ADR)
**Date:** 2026-05-24

## Questions the report should answer

1. **Where did my money go?** — Category breakdown for any period (donut/bar)
2. **How much do I spend per month?** — Total spend trend over time (line graph)
3. **How does this month compare?** — MoM and YoY delta per category
4. **Am I on track with my budget?** — Budget progress alongside actual spend
5. **What are my biggest expenses?** — Top-N transactions or merchants for a period

These questions define the widget catalog. Each widget answers one question in isolation so the dashboard can be composed from any subset.

## Widget catalog v1

| Widget | Key | Answers | Status |
|---|---|---|---|
| Monthly spending line graph | `monthly_totals` | Q2 | **In progress — first widget** |
| Category breakdown | `category_breakdown` | Q1 | Next |
| MoM comparison | `mom_comparison` | Q3 | Backlog |
| Budget progress | `budget_progress` | Q4 | Backlog |
| Top transactions | `top_transactions` | Q5 | Backlog |
| Savings rate | `savings_rate` | — | Backlog |

After the first widget ships, evaluate what's actually useful in daily use before building the next. The catalog order above is a starting point, not a commitment.

## Layout

Single-column `.section-stack` for now. The stretch custom-dashboard builder (ADR-0039 §7) adds drag/reorder via HTMX fragment swaps and persists layout JSON — deferred until the catalog has at least three widgets worth reordering.

## Period controls

All widgets accept `?months=N` (default 12) parsed at the route boundary and passed to the assembler. A date-range picker (custom `date_from` / `date_to`) lands once the category breakdown widget is built — that's when multiple widgets sharing a single period control becomes worth the UI investment.

## Drilldown

Clicking a chart segment routes to `/transactions?date_from=…&date_to=…&category_id=…` using the Transaction History URL contract (Phase 3b). The dashboard template owns the click handler; individual widget fragments do not.

## Migration path

The old `/intelligence/report` page stays until the new dashboard covers Q1 + Q2 (category breakdown + monthly totals). At that point:
1. Update the nav "Report" link from `/intelligence/report` → `/intelligence/dashboard`
2. Delete `templates/intelligence/report.html` and `static/report_charts.js` (ADR-0038 Follow-up §5)
3. The old `/intelligence/report` URL gets a 301 redirect to `/intelligence/dashboard`
