# ADR 0043 - Radar Budget Comparison Ring

- **Status:** Accepted
- **Date:** 2026-05-30
- **Phase:** P5d
- **Deciders:** erin p

## Context

The Category Radar widget (Phase 5d, ADR-0039) shows spending shape as a spider chart with a "Compare prev. month" overlay. The overlay draws a prior month's polygon in a contrasting colour so the user can see how the shape shifted. In practice this is shallow: the prior month is an arbitrary reference with no normative meaning — it does not tell the user whether spending is good or bad, only that it changed. The Budgeting Module (ADR-0025) already holds standing monthly budget targets per category. Those targets are the natural reference shape for a spending radar — they represent what the user decided to allow themselves to spend. Replacing the prior-month overlay with a budget ring makes the visual answer "am I inside or outside my plan?" instead of "how does this month compare to last month?"

[ADR-0003](0003-module-communication-service-layer-only.md) requires cross-module reads to go through the service layer. The Intelligence Layer must call `get_budgets()` from `app.budgets.services`, not query `public.budgets` directly.

## Options considered

### Option A - Keep prior-month overlay, add budget ring alongside

Show all three: current month, prior month, budget. Three polygons on a radar chart are hard to read; the added overlay would obscure the budget comparison that carries the real information.

### Option B - Replace prior-month overlay with budget ring (selected)

Remove the "Compare prev. month" toggle. Always render the budget ring as a dashed grey polygon when the user has at least one budget set. Current-month actual is the primary filled polygon. Axis labels are coloured green (under 80% of budget), amber (80–100%), or red (over budget). Prior months accessed via the month pill strip show actual spend vs. the same standing budget targets (budget targets are not month-specific).

### Option C - Replace radar entirely with a budget-progress bar chart

Drop the radar format. More readable on small screens. Loses the spending-shape gestalt that makes the radar widget worth having, and duplicates the Budget page. Rejected.

## Decision

**Option B** — replace the prior-month overlay with a budget ring. The budget is the only reference that answers "is this good?" The radar becomes a spatial budget-progress view rather than a month-over-month diff.

**What is now true about the system.**

1. `build_category_radar` calls `get_budgets(user_id)` (one additional query) and attaches `budget_data: list[float]` and `has_budgets: bool` to `CategoryRadarVM`.
2. `budget_data` is aligned to `CategoryRadarVM.labels`. Value is the standing monthly budget target (float) for that category, or `0.0` if no budget is set.
3. The radar JS renders a second dashed dataset using `budget_data` when `has_budgets` is true. The dataset uses `borderDash`, no fill, and a muted colour so it reads as a guideline rather than a competing series.
4. Axis label colours are computed per render from the selected month's actual vs. the budget target: green < 80%, amber 80–100%, red > 100%. Labels for unbudgeted axes render in the default text colour.
5. The "Compare prev. month" button and all overlay-toggle logic are removed from the template and the dashboard JS.
6. If the user has no budgets set, the radar renders with no budget ring and a brief prompt to visit the Budget page.

## Consequences

- **Positive.** The radar now answers a question the user cares about ("am I on track?") rather than showing an arbitrary month diff.
- **Positive.** Axis colour coding gives an at-a-glance status without reading any numbers.
- **Positive.** The Intelligence Layer reads from the Budgets service layer — consistent with ADR-0003, no new cross-cutting concern.
- **Negative.** One extra DB query per radar render (`get_budgets`). The query is a simple SELECT on a small table (one row per budget category) so the cost is negligible.
- **Negative.** Users with no budgets get a degraded experience until they set targets. The fallback message directs them to the Budget page.
- **Follow-ups required.** Update `_FAKE_CR_VM` in `tests/test_intelligence_report.py` to include new `budget_data` and `has_budgets` fields.

## Notes

Budget targets in this system are standing global targets (not month-specific). The budget ring therefore shows the same polygon regardless of which month pill is selected. Only the actual polygon changes when the user switches months.
