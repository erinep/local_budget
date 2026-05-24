# ADR 0038 - Frontend Stack for Reporting Overhaul

- **Status:** Accepted
- **Date:** 2026-05-24
- **Phase:** P5d (with cross-cutting effects through P6)
- **Deciders:** erin p

## Context

Phase 5d ([roadmap](../roadmap.md)) rebuilds the report from the ground up: drilldown-enabled charts, custom date ranges, a widget catalog, MoM/YoY comparisons, and a possible custom-dashboard stretch. The current frontend is server-rendered Jinja templates plus one custom vanilla-JS renderer ([static/report_charts.js](../../static/report_charts.js)) that draws SVG donut and bar charts inline. There is no build step, no JS framework, and no JSON API surface — every route returns fully assembled HTML.

Two adjacent items force the decision now rather than later:

1. **Backlog item #13** ([backlog](../backlog.md)) — surfacing the account switcher in the global header and standardizing layout components needs a frontend approach before the work is worth doing. The current header is a flat list of `<a>` tags in [templates/base.html](../../templates/base.html); even a popover requires either a JS sprinkle or a framework convention.
2. **[ADR-0024](0024-intelligence-layer-report-ownership.md), Decision 5** explicitly deferred the chart-library decision to "when Phase 5's custom dashboard work begins." That moment is now. ADR-0024 also flagged Option C (JSON API) as the natural evolution if the page grows interactive.

Adjacent constraints from prior decisions: [ADR-0011](0011-navigation-and-landing-page-contract.md) (header contract assumes no JS, no dropdowns — must be revisited or amended if we add client-side interactivity); [ADR-0003](0003-module-communication-service-layer-only.md) (any JSON API still reads through the documented service layer, not raw tables); the Mobile experience open decision in [roadmap](../roadmap.md#open-decisions) ("PWA vs React Native vs none") which is currently unresolved and is downstream of this choice.

**How coupled is the frontend to the backend today?** Tightly, but cleanly. Routes return `render_template(...)` with a fully assembled view model; templates render that model directly with Jinja; only `report.html` ships a client-side chart by serializing data into `data-chart` attributes. There is no AJAX, no client state, no router. The coupling is conventional, not deep — service layers and view-model assembly are already separated from the route handlers ([ADR-0024](0024-intelligence-layer-report-ownership.md) Decision 3), so adding a JSON surface alongside the HTML one is an additive change.

**How hard would a frontend rewrite be?** Sized by file count: 24 templates, 1 JS file, 1 stylesheet. The templates are small and form-driven; the bulk of the app is server-side. A full SPA rewrite is feasible in calendar weeks, not months, but it would force the JSON API decision now, double the test surface (server tests + frontend tests), introduce a build pipeline, and shift session/auth handling.

## Options considered

### Option A — Stay with Jinja, add a chart library, no other changes

Keep Jinja templates and the vanilla-JS posture. Replace the custom `report_charts.js` renderer with a charting library (Chart.js or Observable Plot). Anything interactive (account switcher, filter UI, drilldown) is a small, ad-hoc `<script>` block in the relevant template.

**Pros.** Zero new framework. Zero build step. Charting library handles responsive sizing, tooltips, and accessibility for free — directly addresses "renders quicker" and "adapts to mobile/desktop." Lowest possible delta from today's stack. CI, deploy, session model, and test suite are all unchanged.

**Cons.** Every interactive surface (header popover, filter panel, drilldown, widget show/hide) becomes a bespoke script. By widget #5 or backlog item #15 the ad-hoc scripts become an unmaintained mini-framework. Custom-dashboard stretch in 5d would need real client state and would likely force a re-decision mid-phase.

**Consequences.** Solves the chart-rendering and responsiveness problems cleanly. Defers — does not solve — the interactivity problem behind backlog #13 and the dashboard-builder stretch.

### Option B — Jinja + HTMX + Alpine.js + chart library (recommended)

Keep Jinja as the rendering engine and the JSON-free posture. Add HTMX for server-driven partial updates (filter changes re-render a fragment server-side, account switcher swaps a header region, drilldown loads a transactions table fragment into a slot). Add Alpine.js for the small bits of pure client state (popover open/closed, tab selection, form-field toggles). Adopt a charting library for the report widgets.

**Pros.** No build step (both libraries are single `<script>` tags). Server stays the source of truth — view models, auth, CSRF, and session handling all unchanged. Header standardization (backlog #13) becomes a clean Alpine component. Filter/drilldown UX for the report comes from HTMX swapping server-rendered fragments — no JSON contract to design, no client router to maintain. Each module can adopt the patterns at its own pace; nothing forces a rewrite of working pages. Mobile responsiveness is a CSS concern, not a framework concern, which keeps the path to a PWA short.

**Cons.** Two new dependencies — small, but new conventions to learn and to document. HTMX fragment endpoints are a second response shape per route (full page vs. partial), which is a mild discipline cost. Custom dashboards with arbitrary client-composed widgets would still want a JSON API eventually (Option D territory), so this option doesn't *eliminate* a future API decision — it defers it until the dashboard builder forces it. ADR-0024 Option D was previously rejected for "introducing a new dependency with no existing precedent"; this ADR consciously overrides that, on the grounds that 5d's interactivity scope is what makes the dependency pay off.

**Consequences.** Header, filters, and drilldown stop being bespoke scripts. The widget contract in 5d can be a Jinja macro + a typed view model per widget, with HTMX handling re-renders. A future JSON API for a custom dashboard becomes additive (Option C in ADR-0024 still on the table), not a precondition.

### Option C — SPA frontend (React/Vue/Svelte), Flask becomes a JSON API

Strip the HTML rendering from Flask routes. Add a frontend project (likely Vite + React or Vite + Svelte), a JSON API surface across every module, and a build/deploy pipeline. Sessions handled via a token or via the existing cookie session against fetch endpoints.

**Pros.** Best ceiling for interactivity, animations, and a custom-dashboard builder. Cleanest path to a future mobile-native app that consumes the same JSON API (resolves the open Mobile decision in the same stroke). Frontend and backend teams could parallelize — irrelevant today, but a real option later.

**Cons.** Largest cost by far. Every existing template (auth, settings, budgets, transactions, intelligence) is rewritten. CSRF, session, and auth handling all need a new pattern. The current 23-test suite covers routes and pure functions; a frontend rewrite roughly doubles test surface (component tests + an integration layer). A build step, a deploy artifact, and likely a Render configuration change. ADR-0024's hybrid decision (Decision 3) would be fully superseded, not just amended. For a solo-maintained personal-finance app at this stage, this is overinvestment, and it forces the JSON API design before Phase 5d's product questions are settled.

**Consequences.** Right answer if the project's medium-term destination is "native mobile app with a separate frontend team." Wrong answer if the destination is "responsive web app with maybe a PWA wrapper" — which is what [roadmap](../roadmap.md) currently says is in scope.

### Option D — Hybrid islands (Jinja host, mounted SPA components only where needed)

Keep Jinja for the shell and most pages. Mount small React/Svelte/Preact "islands" inside specific pages that need rich interactivity (the report, the dashboard builder). Build step is scoped to those components only.

**Pros.** Pays the SPA cost only where it earns its keep. Header, settings, auth, and CRUD pages stay Jinja-simple. The report becomes a real interactive surface without rewriting every other module.

**Cons.** Two rendering paradigms in one codebase — a maintenance tax forever, and a confusing onboarding story. Still requires a build step and a JSON API (or a serialized-into-page-data pattern, which is what we already do for the chart). Islands frameworks (Astro et al.) are typically the host; bolting islands onto Jinja is a custom integration. The complexity of "two paradigms" tends to grow once the precedent is set.

**Consequences.** Plausible if the dashboard builder ships and proves to need true SPA behavior. Not the right *first* step — it should follow from Option B hitting a real ceiling, not precede it.

## Decision

**Proposed: Option B — Jinja + HTMX + Alpine.js + a charting library.** The recommended charting library is **Chart.js** (small, no-build, canvas-based, broad chart-type coverage including the widgets named in [roadmap](../roadmap.md#phase-5d---reporting-overhaul-34-weeks) §3); Observable Plot is the alternative if SVG output matters for accessibility or print export, with the trade-off being a larger payload.

The two reasons that carry the recommendation: (1) the things 5d and backlog #13 actually need — responsive widgets, drilldown, a header account switcher, filter/period controls that don't full-page-reload — are exactly the problems HTMX + Alpine + a chart library solve, without forcing a JSON API contract before the product questions in 5d are settled; (2) every other module (auth, settings, budgets, transactions CRUD) stays on the working Jinja stack, so the cost is scoped to the report and the header, not the whole app.

This explicitly **defers** the SPA-and-JSON-API decision until the 5d custom-dashboard stretch ships and demonstrably outgrows HTMX. The Mobile open decision in [roadmap](../roadmap.md#open-decisions) has since been resolved in favor of a PWA wrapper, which does not require a JSON API — a service worker caches HTML responses fine. Absent the dashboard-stretch trigger, Option B is sufficient.

## Consequences

**Positive.**
- Backlog #13 (account switcher in the header, standardized layout component) becomes implementable as an Alpine component + an HTMX swap, not a custom script.
- Phase 5d's drilldown, filter controls, and period switching can be server-rendered fragments — the widget contract is "a Jinja macro + a typed view model," extending [ADR-0024](0024-intelligence-layer-report-ownership.md) Decision 3 without contradicting it.
- Responsive mobile/desktop layouts become a CSS concern only — keeps the PWA path short if the Mobile open decision goes that way.
- No build step, no Node toolchain, no deploy-pipeline change. CI gates and Render deploy unchanged.
- Chart library replaces the custom `report_charts.js` renderer, addressing the "renders quicker" requirement and removing a maintenance liability.

**Negative.**
- Two new client dependencies (HTMX, Alpine.js) and one charting library. Each is a `<script>` tag, but each is also a new convention to document.
- Routes that serve both full pages and HTMX fragments need a discipline ("`HX-Request` header → return the fragment template; otherwise render the full page"). This is a small cross-cutting pattern that wants a one-paragraph note in [architecture.md](../architecture.md).
- [ADR-0011](0011-navigation-and-landing-page-contract.md) explicitly says "No dropdowns. No JavaScript." for the header. Adding the account switcher to the header violates the letter of that contract. ADR-0011 must be amended (not superseded — the *classification rule* is still good) to allow scoped interactivity in the header for cross-module controls.
- [ADR-0024](0024-intelligence-layer-report-ownership.md) Decision 3 rejected HTMX with the rationale "no existing precedent in the codebase." This ADR is the precedent. ADR-0024 is not superseded — its rendering decision was specifically about the chart payload, which is still server-assembled and serialized into the page; HTMX handles the *surrounding controls*, not the chart data itself.
- The custom-dashboard stretch in 5d can be implemented entirely with HTMX (server-side composition, fragment swaps on reorder); a JSON API is not required for it. The only scenarios that would force JSON are non-browser consumers (email digest, CLI, third-party) — none of which are on the roadmap.

**Follow-ups required.**
1. Amend [ADR-0011](0011-navigation-and-landing-page-contract.md) to allow scoped JS-driven controls in the header (the account switcher) while preserving the classification rule.
2. Pin the charting library in its own short ADR or as an extension to this one once 5d's widget catalog is finalized — the widget list in [roadmap](../roadmap.md#phase-5d---reporting-overhaul-34-weeks) §3 should drive that choice (donut + line/area + grouped bar + progress bar must all be covered out of the box).
3. Add a one-paragraph "HTMX fragment convention" note to [architecture.md](../architecture.md) when the first fragment route ships — what header to check, where the fragment template lives, how it's tested.
4. Revisit this ADR when (a) the 5d custom-dashboard stretch enters scope, or (b) the Mobile open decision is resolved. Either may promote Option D or Option C from "deferred" to "needed."
5. The existing `static/report_charts.js` is deleted in the same PR that introduces the chart library, per [ADR-0024](0024-intelligence-layer-report-ownership.md)'s "the current report page is replaced, not extended" exit criterion for 5d.

## Notes

**Why not just Option A.** Option A solves the chart problem and ignores the interactivity problem. Backlog #13 and the 5d controls (date range, category filter, period granularity, drilldown) are interactivity problems. Picking Option A means writing those as bespoke scripts and re-deciding this ADR within a few PRs.

**Why HTMX over a heavier framework.** HTMX is conceptually a server-rendered app with smarter forms. It keeps the existing mental model — routes return HTML, server owns state — and adds the ability to swap a fragment instead of reloading the page. The closest alternative (Turbo from the Hotwire stack) is similar in spirit; HTMX has the smaller surface area and broader adoption in the Python/Flask ecosystem.

**Why Alpine over plain JS for the popover bits.** Plain JS works fine for one popover. By the third or fourth small client-state surface (a popover, a tab group, a toggle, a confirm-on-click), the lack of a convention starts to cost. Alpine is the smallest viable convention — declarative attributes on the existing HTML, no build step, no virtual DOM.

**On the Mobile open decision.** Resolved in favor of a PWA wrapper around the responsive web app. A PWA does not require a JSON API — the service worker caches whatever the routes return, HTML included. This means Option B is sufficient for the Mobile path on its own merits, not merely as a deferral. A future pivot to a native app (not currently on the roadmap) would reopen the JSON-API question.
