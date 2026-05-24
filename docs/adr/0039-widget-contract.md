# ADR 0039 - Widget Contract

- **Status:** Accepted
- **Date:** 2026-05-24
- **Phase:** P5d
- **Deciders:** erin p

## Context

[ADR-0038](0038-frontend-stack-for-reporting-overhaul.md) pinned the rendering stack for Phase 5d (Jinja + HTMX + Alpine + chart library). It did not specify the function-level contract for an individual report widget — the assembler signature, return shape, or how the catalog is organized. [ADR-0024](0024-intelligence-layer-report-ownership.md) Decision 3 established the hybrid pattern at the page level (server assembles a typed view model, chart JS renders from it serialized into the page); this ADR generalizes that pattern to a *per-widget* contract so [roadmap](../roadmap.md#phase-5d---reporting-overhaul-34-weeks) §3's catalog can grow without per-widget architecture decisions.

The forcing function is [roadmap](../roadmap.md#phase-5d---reporting-overhaul-34-weeks) §2: "Widget contract — typed view-model shape per widget type, extending [ADR-0024](0024-intelligence-layer-report-ownership.md)'s hybrid rendering decision so new chart types extend rather than rewrite."

Relevant prior ADRs: [ADR-0003](0003-module-communication-service-layer-only.md) (widgets read through the Transaction Engine service layer only, not raw tables); [ADR-0023](0023-aggregation-api.md) (`get_spend_by_category`, `get_spend_history` are the inputs widgets compose from); [ADR-0024](0024-intelligence-layer-report-ownership.md) (Intelligence Layer owns the report; hybrid render).

## Options considered

### Option A — Generic view model (`dict[str, Any]` per widget)

Each widget assembler returns an untyped dict. Chart code reads keys by string. Templates read the same dict.

**Pros.** Zero ceremony to add a widget. No new dataclass per widget type.
**Cons.** No typing — a renamed key breaks rendering silently. No discoverability — "what fields does the trend widget produce?" is answered by grep, not by reading a type. Tests can assert against examples, not against a shape. The chart-data serialization step (into `data-chart` attributes per [ADR-0024](0024-intelligence-layer-report-ownership.md)) has no schema to validate against.

### Option B — Per-widget typed dataclass (selected)

Each widget type owns a module under `app/intelligence/widgets/<widget_key>.py`. The module exports a dataclass `<Name>VM`, a pure assembler `build_<name>(user_id, params) -> <Name>VM`, and points at a fragment template at `templates/intelligence/widgets/<key>.html`. The chart-data serialization (into `data-chart` attributes for the chart library) uses `dataclasses.asdict` plus a small encoder for `Decimal` / `date` / `DateRange`.

```python
# app/intelligence/widgets/category_breakdown.py
@dataclass
class CategoryBreakdownVM:
    title: str
    period: DateRange
    slices: list[CategorySlice]  # {category_id, name, amount, pct}
    total: Decimal

def build_category_breakdown(user_id: str, period: DateRange) -> CategoryBreakdownVM: ...
```

**Pros.** Typed, testable, self-documenting. The widget catalog in [roadmap](../roadmap.md#phase-5d---reporting-overhaul-34-weeks) §3 becomes a directory listing under `app/intelligence/widgets/`. Adding a widget is one module + one registry line + one fragment template. The chart-library serialization step has a real schema. The assembler is independently testable as a pure function.
**Cons.** One small dataclass module per widget — five to ten files instead of inline functions. Mild over-engineering for the first widget; the structure pays off as the catalog grows.

### Option C — Single discriminated union (`Widget = CategoryBreakdownVM | TrendVM | ...`)

Per-widget dataclasses *plus* a top-level union so callers can hold "any widget" generically.

**Pros.** Useful if the dashboard composer ever needs to hold a heterogeneous list at the type level.
**Cons.** Premature until the dashboard composer exists. Trivial to add later — write `Widget = ...` once the per-widget classes exist.

## Decision

**Option B — per-widget typed dataclass.** Each widget lives in `app/intelligence/widgets/<widget_key>.py` and exposes (a) a dataclass describing the view model, (b) a pure assembler function returning it from service-layer reads, (c) a fragment template at `templates/intelligence/widgets/<key>.html` that consumes the dataclass.

**What is now true about the system.**

1. **Widget directory structure.** `app/intelligence/widgets/` holds one module per widget type. `templates/intelligence/widgets/` holds the matching fragment templates.

2. **Widget registry.** A registry maps `widget_key → (dataclass, assembler, template_path)`. Adding a widget is: write the module, write the template, add one line to the registry.

3. **URL contract.**

   | Method | Path | Returns |
   |---|---|---|
   | `GET` | `/intelligence/widgets/<key>` | HTML fragment (HTMX-friendly) |
   | `GET` | `/intelligence/dashboard` | Full dashboard page composing widgets |
   | `POST` | `/intelligence/dashboard/layout` | Persist a user's widget layout (stretch only) |

   Widget configuration (period, filter, category scope) is passed as query parameters. The route parses them once at the boundary and passes typed arguments to the assembler.

4. **Discipline rule — data shaping lives in the assembler.** Templates do *presentation only*: Jinja loops, conditionals, classes. No arithmetic (`{% set total = ... %}`), no derived values, no formatting decisions that affect what the chart sees. If a value needs to be computed, the assembler computes it and the dataclass carries it. This rule is what keeps the contract useful and what makes adding alternate response surfaces (e.g., a JSON route) trivial later.

5. **Chart data serialization.** Chart widgets serialize their dataclass into a `data-chart` attribute on the fragment via `dataclasses.asdict` plus a small JSON encoder for `Decimal` / `date` / `DateRange`. The encoder is written once and reused across all widgets. This matches the [ADR-0024](0024-intelligence-layer-report-ownership.md) Decision 3 pattern at the widget level.

6. **Auth and CSRF.** Widget routes are `@login_required`. GETs are CSRF-exempt as they are throughout the app. The layout POST uses the existing CSRF token mechanism. No new auth surface.

7. **Dashboard composition (stretch).** If the custom-dashboard stretch ships, `dashboard_layouts (user_id, layout_json)` stores an ordered list of `{widget_key, params}` entries. The dashboard page renders the layout server-side using the HTML fragment for each widget; drag/reorder posts the new layout and HTMX-swaps the dashboard. No JSON API needed for this — composition is server-side per [ADR-0038](0038-frontend-stack-for-reporting-overhaul.md).

## Consequences

**Positive.**
- The widget catalog from [roadmap](../roadmap.md#phase-5d---reporting-overhaul-34-weeks) §3 becomes mechanical to grow: one module + one template + one registry line per widget. No reroll of rendering architecture per chart type.
- Each assembler is testable in isolation as a pure function — matches the pattern [ADR-0024](0024-intelligence-layer-report-ownership.md) Decision 3 established for `build_report_view_model`.
- The custom-dashboard stretch becomes a composition problem (loop the layout, render fragments), not an architecture problem.
- The "data shaping in the assembler, not the template" discipline keeps the option of adding a JSON surface later cheap — roughly one route plus a JSON encoder, no widget-by-widget retrofit. See Notes.

**Negative.**
- Per-widget dataclass modules add file count — five to ten small files in `app/intelligence/widgets/` once the catalog is built. For the first widget this is mild over-engineering; it pays off as the catalog grows.
- The "no logic in templates" rule is a discipline, not enforced by the framework. Code review has to catch violations.

**Follow-ups required.**
1. The first widget implementation (likely the category-breakdown migration of the existing donut) establishes the per-widget module template. Subsequent widgets follow it — no per-widget ADR required.
2. Update [architecture.md](../architecture.md) with a one-paragraph note on the widget directory and registry pattern when the first widget ships.
3. The existing `build_report_view_model` from [ADR-0024](0024-intelligence-layer-report-ownership.md) is *not* migrated to this contract in the same PR. It stays as-is until 5d's redesign replaces the report page; the old function is deleted when the old page is.
4. The dashboard-layout schema (`dashboard_layouts (user_id, layout_json)`) gets its own ADR if and when the stretch is promoted to in-scope.
5. If a real non-browser consumer ever appears (email digest, CLI, third-party), reopen this ADR or write a small extension ADR. Adding a JSON surface is expected to be roughly one route handler plus a one-time JSON encoder — see Notes.

## Notes

**Why no JSON route now.** A JSON surface would only be consumed by something non-browser: an email digest, a CLI, a third-party integration, or a client-composed dashboard widget. None of those are on the roadmap. The Mobile open decision has been resolved as a PWA wrapper, which consumes HTML responses through the service worker and does not need JSON. The custom-dashboard stretch composes server-side fragments via HTMX per [ADR-0038](0038-frontend-stack-for-reporting-overhaul.md) and does not need JSON either. Adding the JSON route speculatively would violate the project discipline in [CLAUDE.md](../../CLAUDE.md) ("Don't design for hypothetical future requirements").

**Why adding JSON later is cheap.** Because the assembler is a pure function returning a typed dataclass, a JSON route is one handler plus a one-time encoder:

```python
@bp.get("/widgets/<key>.json")
@login_required
def widget_json(key):
    widget = registry[key]
    vm = widget.assembler(g.user.id, parse_params(request.args, widget))
    return jsonify(dataclasses.asdict(vm))
```

Plus a `Decimal`/`date`/`DateRange` encoder written once. One PR, well under 100 lines including tests. No schema change, no auth change, no widget-by-widget retrofit. The discipline rule in Decision §4 (data shaping in the assembler, not the template) is what guarantees this stays cheap — any future JSON consumers see exactly what HTML consumers see because both surfaces read the same dataclass.

**Relationship to [ADR-0038](0038-frontend-stack-for-reporting-overhaul.md).** ADR-0038 chose the rendering stack (HTMX/Alpine/chart-lib). This ADR pins the data contract behind it. The HTML route here is what HTMX consumes per 0038. The two ADRs are layered, not competing.

**Relationship to [ADR-0024](0024-intelligence-layer-report-ownership.md) Decision 5 (chart library).** Still deferred. The widget catalog in [roadmap](../roadmap.md#phase-5d---reporting-overhaul-34-weeks) §3 names the chart types that drive the library choice (donut, line/area, grouped bar, progress bar). The chart-library ADR should follow the first one or two widget implementations, when the catalog needs are concrete.
