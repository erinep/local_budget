# ADR 0011 - Navigation and Landing Page Contract

- **Status:** Accepted
- **Date:** 2026-05-17
- **Phase:** P2 (forward-looking through P4)
- **Deciders:** Architect agent

## Context

Phase 2 shipped the Account Settings service, schema, routes, and templates. Manual review surfaced three IA gaps that block Phase 2 exit: the only path to the new Categories UI is typing a URL, the post-login landing remains `/upload` (a Phase 0 default), and there is no contract describing how future modules (Transactions index in Phase 3, Budgeting in Phase 4) plug into the header and the landing page. Without a contract, each future phase will re-litigate the nav.

See [`docs/phase2-amendment-a-navigation-and-cleanup.md`](../phase2-amendment-a-navigation-and-cleanup.md) for the full problem framing, option tables, and per-gap rationale. This ADR pins the decisions; the amendment retains the long-form reasoning.

Governing prior decisions: [ADR 0004](0004-flask-blueprint-layout.md) (blueprint layout — one blueprint per architectural module), [`docs/architecture.md`](../architecture.md) (Budgeting is a peer top-level module, not a configuration surface). Relevant roadmap: [Phase 2 exit criteria](../roadmap.md) — "users can add, rename, and delete categories and keywords entirely through the UI."

## Options considered

### Option A - Land on `/upload`, add a `Categories` link to the header

Keep the Phase 0 landing. Add a single direct link to `/account-settings/categories` so the Phase 2 UI is reachable.

**Pros:** Minimal work. No new routes, no new blueprint.
**Cons:** Doesn't establish a landing contract — every future phase re-asks the question. The header becomes a flat list of every module's primary URL with no organizing rule. Configuration links and core-module links sit at the same level.

### Option B - Dashboard landing at `/` + top-level/Settings-nested classification rule

Post-login redirects to `/`, served by a new `home_bp` blueprint. The header surfaces top-level modules (cross-module destinations: Transactions in P3, Budget in P4) and a single `Settings` entry. `Settings` is itself a top-level module whose landing page (`GET /account-settings/`) cards its configuration sub-sections (Categories live, Account Details stub). Budget is **not** a Settings sub-page — it is deferred to Phase 4 as a peer top-level module.

**Pros:** Pins a rule, not a one-off fix. Each future module decides "top-level or Settings-nested" by reference to the rule, not by re-debating the nav. Matches ADR-0004's "blueprints map to architectural modules" — Settings has its own landing because Account Settings is its own module. The dashboard is a stable cross-module composition surface for inert links today, richer summaries later.
**Cons:** Two new routes (`/` and `/account-settings/`) and a new blueprint. Slightly more code than Option A.

### Option C - Dashboard at `/home`, brand link → `/home`

Same as Option B but the landing is `/home` rather than root. `/` either 404s or permanently redirects.

**Pros:** Explicit URL ("this is the home page"). Avoids any ambiguity if `/` is ever needed for marketing or a public surface.
**Cons:** `/` is the canonical home for a web app. Pointing `/` anywhere other than the landing means a permanent redirect or a wasted route. Brand-link muscle memory expects `/` to be home. No marketing surface is planned in [roadmap.md](../roadmap.md), so the reservation has no payoff.

## Decision

We will choose **Option B**, with the landing URL pinned at `/`.

The two reasons that carried the decision: (1) the project needs a *rule* for nav classification, not a Phase 2 patch — without one, Phase 3 and Phase 4 each pay the same decision cost; (2) the rule that falls out — "cross-module destinations top-level, configuration nested under Settings" — is a direct extension of ADR-0004 and `docs/architecture.md`'s module model, so the IA matches the architecture instead of contradicting it.

**What is now true about the system:**

1. **Post-login landing destination is `/`.** Served by a new `home_bp` blueprint at `app/home/routes.py`, no URL prefix. The brand link in the header and the post-login redirect in `app/auth/routes.py` both target `/`.

2. **Header composition rule.** The header is rendered by `templates/base.html` and contains, in order:
   - **Brand link** (always visible) → `/`.
   - **Top-level module links** (auth-gated; only when `g.user` is present) → one link per top-level module that has shipped a user-facing surface. Phase 2: `Settings`. Phase 3 adds `Transactions`. Phase 4 adds `Budget`.
   - **Identity block** (auth-gated) → user email + Sign out.
   - No dropdowns. No JavaScript. No links to modules that have not shipped a surface.

3. **Top-level vs. Settings-nested classification rule.** A destination is **top-level** if it is a cross-module composition or a primary module surface a user navigates to in order to *see their financial picture* (Transactions, Budget, the future Intelligence-driven dashboard). A destination is **Settings-nested** if it is a configuration surface — the user goes there to *change how the system behaves for them* (Categories, Account Details, future preferences). Budget is explicitly top-level, not Settings-nested, because Budgeting is a peer module per `docs/architecture.md`.

4. **Settings IA shape.** `GET /account-settings/` renders a landing page with cards for each configuration sub-section. Sub-section URLs are siblings under the existing `settings_bp` prefix (e.g., `/account-settings/categories`, `/account-settings/account`). No dropdown menu. No JS. Stubs render as cards labeled "Coming soon" rather than as hidden menu items, so the user sees what exists and what is planned.

5. **`home_bp` blueprint.** `home_bp = Blueprint("home", __name__)`, registered with no URL prefix. This is a deliberate, small deviation from ADR-0004's table (which enumerates one blueprint per architectural module: Transaction Engine, Account Settings, Budgeting, Intelligence). The dashboard is a cross-module *presentation* surface that owns no data and does not belong inside any single module's blueprint. `home_bp` is the smallest, clearest home for it and the right place for future cross-module composition surfaces.

6. **Future-phase expectations.**
   - **Phase 3 (Transactions index):** adds a top-level `Transactions` link in the header. The existing `transactions_bp` (URL prefix `/`) gains an index route. The dashboard's Upload card evolves into a Transactions card showing a count or recent activity. No nav re-decision required.
   - **Phase 4 (Budget):** adds a top-level `Budget` link in the header and a `Budget` card to the dashboard. `budgeting_bp` is registered per ADR-0004. Budget does not appear under Settings.
   - **Phase 5 (Intelligence):** narrative summaries and anomaly callouts render *on the dashboard* (the `home_bp` template). The Intelligence layer remains read-only and additive; it does not get its own top-level link.
   - **New configuration surfaces** (preferences, password change, etc.) appear as new cards on `/account-settings/`. The rule is: if it is a configuration surface, it becomes a Settings card; if it is a destination, it becomes a top-level link.

## Consequences

**Positive:**
- Each future phase adds at most one header link and one dashboard card. The IA grows without re-deciding the nav.
- The classification rule is small enough to apply without an ADR every time a new surface appears.
- Settings IA matches the blueprint structure: `/account-settings/` is the module landing, sub-pages are siblings. Consistent with ADR-0004's directory convention.
- No JS required for nav. Mobile responsiveness is a separate styling concern, not an IA concern.
- The dashboard is a stable hook for the Intelligence layer (Phase 5) without requiring a new top-level surface.

**Negative:**
- One new blueprint (`home_bp`) outside ADR-0004's original table. Future readers must understand that `home_bp` exists because the dashboard is a cross-module composition surface, not a module of its own.
- A permanent extra hop for habitual Phase 0/1 users who type `/upload` directly — they get the dashboard, then click Upload. Acceptable cost; the dashboard is a single click through.
- The Phase 2 dashboard is intentionally inert (two cards). Until Phase 5 it carries no summaries or counts — readers who expect a rich dashboard from day one will see a thin one.

**Follow-ups required:**
1. Implementation tickets per the amendment: dashboard route + template (Ticket 3), Settings index + nav link (Ticket 2). Tickets 2 and 3 are gated by this ADR.
2. Update post-login redirect in `app/auth/routes.py` to `/`. Update any tests that assert `/upload` as the post-login destination.
3. When `transactions_bp` gains an index route in Phase 3, add the `Transactions` header link and update the dashboard's Upload card. No ADR required — it is mechanical application of this contract.
4. When `budgeting_bp` is introduced in Phase 4, add the `Budget` header link and dashboard card per ADR-0004's blueprint convention. No new IA ADR required unless the contract here is being changed.
5. Anything that touches Supabase Auth directly (password change, email change, account deletion under Account Details) is out of scope for this ADR and requires its own decision.

## Notes

The amendment ([`docs/phase2-amendment-a-navigation-and-cleanup.md`](../phase2-amendment-a-navigation-and-cleanup.md)) holds the full option tables, including the dropdown-vs-landing-page analysis for Settings IA and the rationale for keeping Budget out of Settings. This ADR deliberately stays short: the rule, the URLs, the blueprint placement, and the future-phase expectations. If a future phase needs to revisit the contract — for example, if the header outgrows a flat list — supersede this ADR rather than editing it.
