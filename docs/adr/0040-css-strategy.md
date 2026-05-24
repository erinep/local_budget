# ADR 0040 - CSS Strategy

- **Status:** Accepted
- **Date:** 2026-05-24
- **Phase:** P5d (with cross-cutting effects through P6)
- **Deciders:** erin p

## Context

[Backlog](../backlog.md) item #12 calls for unified styling — replacing inline `style=` attributes (~260 occurrences across 24 templates) with a proper class system. [ADR-0038](0038-frontend-stack-for-reporting-overhaul.md) leans on CSS to carry responsive mobile/desktop layouts ("Mobile responsiveness is a CSS concern, not a framework concern"), but the current `static/styles.css` is a 975-line hand-rolled file with no naming convention and no shared design tokens, and most templates override it with inline styles anyway. Phase 5d will roughly double the template count via the widget catalog; without a strategy, the new widgets will accumulate the same debt the backlog item is trying to clear.

The question this ADR settles is twofold: (1) do we adopt a CSS framework, and (2) how do we get from "inline-styles-everywhere" to a usable class system without blocking 5d on a multi-week refactor.

Relevant prior decisions: [ADR-0038](0038-frontend-stack-for-reporting-overhaul.md) (no build step, no Node toolchain — the CSS strategy must respect this).

## Options considered

### Option A — Adopt Tailwind CSS

Utility-class framework. Either via the Play CDN (no build step, slower at runtime, large CSS payload) or via a small Node build step (fast, small payload, introduces tooling).

**Pros.** Velocity once familiar. Strong responsive primitives out of the box. Widely understood. Removes most of the "what should I name this class?" overhead.
**Cons.** Either adds a build step (violates [ADR-0038](0038-frontend-stack-for-reporting-overhaul.md)'s no-build posture) or uses the CDN (multi-megabyte CSS, slower first paint — wrong direction for the "renders quicker" goal). Templates become noisier (long `class="..."` strings). Learning curve and project-wide convention shift.

### Option B — Adopt a small framework (Pico.css, Bulma, or similar)

Drop-in semantic CSS that styles standard HTML elements with minimal class usage.

**Pros.** No build step. Less verbose than Tailwind in templates. Sensible defaults.
**Cons.** Hard to escape from once adopted — the framework's opinions are baked into every page. Customization typically means overriding the framework's CSS, which puts you back in the same "many specificity layers" problem the project already has. Mismatch with the existing visual identity in `styles.css` would force either a big-bang restyle or a long period of mixed appearance.

### Option C — Hand-rolled CSS with design tokens and a small set of primitives (selected)

Stay hand-rolled. Add CSS custom properties (`--color-text-muted`, `--space-4`, etc.) at the top of `static/styles.css` as design tokens. Define 5–7 named layout primitive classes (`.card`, `.button`, `.form-row`, `.data-table`, etc.) that use the tokens. New work — starting with the Phase 5d widgets — is built against these primitives. Existing templates are migrated opportunistically, not in a big sweep.

**Pros.** Matches [ADR-0038](0038-frontend-stack-for-reporting-overhaul.md)'s no-build posture. Lowest friction — no new tooling, no dependency, no convention shift. Tokens make later theming or dark-mode work cheap. The "build new work against primitives, migrate old work opportunistically" rule avoids a multi-week refactor blocking 5d.
**Cons.** Discipline-based, not framework-enforced — code review has to catch new inline styles in 5d work. Hand-rolled CSS at the long-term scale of the catalog (10+ widgets, several config pages) will eventually require more structure (BEM-like naming, layered organization) than this ADR pins. Acceptable cost — that structure can grow in as needed without re-deciding the strategy.

## Decision

**Option C — hand-rolled CSS with design tokens and a small set of primitives.**

**What is now true about the system.**

1. **No CSS framework, no build step, no preprocessor.** `static/styles.css` remains a single hand-rolled CSS file. Adding Tailwind, Pico, Bulma, PostCSS, Sass, or any related tooling is out of scope for this ADR and would require a new ADR to revisit.

2. **Design tokens live at the top of `static/styles.css`.** CSS custom properties defined at `:root` cover colors (brand, text, background, border, status), spacing scale (`--space-1` through `--space-8`), type scale (`--text-sm` through `--text-2xl`), border radius, and shadow. Tokens are named **semantically** (`--color-text-muted`), not literally (`--color-gray-600`), so values can change without renaming.

3. **A small catalog of layout primitives** lives below the tokens. Target 5–7 classes, identified by auditing the inline-style patterns that actually repeat. Initial candidates: `.card`, `.button`, `.button-secondary`, `.form-row`, `.data-table`, `.page-header`. A primitive only ships if it has at least three real use sites — no speculative classes.

4. **New work uses the primitives. No inline styles in new code.** This applies to every Phase 5d widget and every new template added from this point. Code review enforces.

5. **Existing templates migrate opportunistically.** When a template is touched for any other reason, its inline styles get converted in the same PR. A dedicated cleanup pass may happen at the end of 5d once the patterns are battle-tested; nothing forces it.

6. **The widget catalog from [ADR-0039](0039-widget-contract.md) is the first consumer.** The monthly-totals line graph widget (the first one to ship per ADR-0039 follow-up §1) builds against the primitives. It is the prototype that proves the system; subsequent widgets follow its pattern.

7. **Bootstrapping work is captured in [docs/work-packets/css-prep-tokens-and-primitives.md](../work-packets/css-prep-tokens-and-primitives.md).** That packet establishes the tokens and primitives without touching any existing template. Phase 5d widget work begins after it merges.

## Consequences

**Positive.**
- Phase 5d widgets are built on named classes, not inline styles. The backlog #12 problem stops growing.
- No build step, no new tooling, no dependency — consistent with [ADR-0038](0038-frontend-stack-for-reporting-overhaul.md)'s no-build posture.
- Tokens make responsive design, future theming, and dark mode cheap to add later.
- The opportunistic migration rule means 5d ships on schedule. The full backlog #12 cleanup happens gradually rather than as a multi-week blocker.

**Negative.**
- Discipline-enforced, not framework-enforced. A new inline `style=` attribute in a 5d PR is a code-review catch, not a build failure.
- Hand-rolled CSS will eventually need more structure (naming convention, file organization) than this ADR pins. That structure can grow in incrementally; if it ever needs to be formalized, write a follow-up ADR then.
- Existing inline styles remain in `styles.css` and across templates until opportunistically migrated. Visual inconsistency between migrated and not-yet-migrated pages will persist for some weeks.

**Follow-ups required.**
1. Execute the bootstrapping work packet ([docs/work-packets/css-prep-tokens-and-primitives.md](../work-packets/css-prep-tokens-and-primitives.md)) before Phase 5d widget work begins.
2. The first widget (monthly-totals line graph, [ADR-0039](0039-widget-contract.md) follow-up §1) is the prototype for "new work built against primitives." Subsequent widgets follow its pattern — no per-widget styling ADR required.
3. If a Phase 5d widget genuinely needs a layout the primitives don't cover, add a new primitive — don't fall back to inline styles. Update the primitive catalog in `styles.css` and note it in the PR.
4. Backlog #12's full "delete inline overrides" sweep stays open. Close it incrementally as templates are touched.
5. Revisit this ADR if (a) Tailwind or another framework starts looking unavoidable, (b) hand-rolled CSS hits an organizational ceiling, or (c) a future phase requires theming/dark-mode work that the tokens-as-defined don't cover.

## Notes

**Why not Tailwind.** The strongest argument for Tailwind is velocity. The strongest argument against is that it forces a build step (violating [ADR-0038](0038-frontend-stack-for-reporting-overhaul.md)) or a CDN payload (slowing first paint). At this project's scale — solo maintainer, modest template count — the velocity gain doesn't outweigh the tooling cost. If the project ever grows to a team or a much larger UI surface, this is the most likely trigger to revisit.

**Why the audit-then-name approach to primitives.** Naming classes before knowing what's actually repeated is how you end up with a `.box` that turns into a `.box-with-shadow` that turns into a `.box-with-shadow-and-padding` six months later. The work packet's "grep templates for repeated inline patterns first, then name the top 5–7" rule grounds the catalog in real use.
