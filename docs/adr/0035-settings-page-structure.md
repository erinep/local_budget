# ADR 0035 - Settings Page Structure — Blueprint, URL Namespace, Navigation, and Email-Change Flow

- **Status:** Accepted
- **Date:** 2026-05-23
- **Phase:** P5c
- **Deciders:** architect agent

## Context

Phase 5c consolidates user settings into a single navigable area. Currently the only configuration surface is the Account Settings module, whose routes live under `/account-settings/` (owned by the `account_settings` blueprint). Phase 5c adds Profile, Accounts, and Security sub-pages alongside the existing Categories page. Without pinning the URL namespace, blueprint ownership, navigation pattern, and email-change security behavior now, each new sub-page will relitigate these questions.

Prior decisions that constrain this ADR: [ADR-0004](0004-flask-blueprint-layout.md) established that `settings_bp` owns the `/settings` prefix; [ADR-0011](0011-navigation-and-landing-page-contract.md) established that configuration surfaces are nested under Settings and that `GET /account-settings/` is the current Settings landing page. Phase 5c extends that surface without invalidating either decision.

Relevant risks: `Auth implementation has security flaws` (P1, Very High impact) governs the email-change flow; `Scope creep in Intelligence Layer` (P5, High likelihood) reminds us to keep the settings surface focused on configuration, not features.

## Options considered

### Option A - New thin `settings` blueprint owns `/settings/*`; `account_settings` blueprint stays at `/account-settings/`

Introduce a new `settings` blueprint (per ADR-0004's pre-recorded table entry) registered at prefix `/settings`. It owns the index and all sub-page routes: `/settings/profile`, `/settings/categories`, `/settings/accounts`, `/settings/security`. A redirect shim from `/account-settings/` to `/settings/` preserves existing nav links. The `account_settings` blueprint continues to own the domain service layer (category rules, keyword management) but its routes are either moved to `settings_bp` or remain at `/account-settings/categories` with a redirect from `/settings/categories`.

Pros: stable, purpose-built URL namespace; `account_settings` remains a domain service, not a presentation owner for unrelated sub-pages; redirect shims are simple and reversible; follows the ADR-0004 convention.

Cons: two blueprints temporarily serve overlapping concerns during the transition; redirect shims add a small maintenance obligation.

### Option B - Extend `account_settings` blueprint to own all `/settings/*` routes

Rename the `account_settings` blueprint's prefix from `/account-settings` to `/settings` and add Profile, Accounts, and Security routes inside it. Old URLs get 301 redirects.

Pros: no new blueprint; all settings routes live in one file.

Cons: `account_settings` was designed to own category rules and user preferences, not auth surfaces like password change or session management. Expanding it to own Security conflates two distinct concerns and violates "one job per module." Future agents reading `app/account_settings/routes.py` would find password-change logic sitting next to keyword CRUD, which is a maintenance trap.

### Option C - Keep each sub-page in its owning module blueprint; `/settings` is a nav shell only

`/settings/profile` is served by `auth_bp`, `/settings/categories` by `account_settings_bp`, `/settings/accounts` by `transactions_bp`, `/settings/security` by `auth_bp`. A thin `settings` blueprint renders only the index page and provides the shared layout.

Pros: each sub-page is co-located with its domain logic.

Cons: the URL `/settings/categories` is registered inside `account_settings_bp` while `/settings/accounts` is inside `transactions_bp` — cross-blueprint URL ownership under a shared prefix is fragile and hard to reason about. The shared settings layout template must be imported by each module, creating a presentation coupling. This option trades blueprint purity for URL clarity and comes out worse on both.

### Option D - No new blueprint; `/settings` index served by `home_bp` with direct links to existing module URLs

`home_bp` renders a `/settings` index that links to `/account-settings/categories`, `/auth/profile`, etc. Each module retains its own URL.

Pros: zero new routes beyond the index; fastest to ship.

Cons: the URL namespace is fragmented (settings sub-pages live at inconsistent paths), which will confuse users and frustrate future deep-linking. ADR-0011's rule — configuration surfaces are nested under Settings — implies a unified `/settings/` namespace, not a link aggregator at `/settings` with scattered URLs behind it.

## Decision

We will choose **Option A** — a new thin `settings` blueprint at prefix `/settings` owns the index and all settings sub-page routes, with redirect shims from the existing `/account-settings/` paths.

The two reasons that carried the decision: (1) ADR-0004 pre-recorded `settings_bp` at prefix `/settings` for exactly this moment — using it now is mechanical application of a prior decision, not a new design choice; (2) Option B's expansion of `account_settings` would give a domain service blueprint ownership over auth surfaces (password change, session management), violating the "one job per module" principle in `docs/architecture.md`.

**What is now true about the system at Phase 5c exit:**

**Blueprint ownership.** `settings_bp = Blueprint("settings", __name__, url_prefix="/settings")` is introduced in `app/settings/routes.py`. It owns all routes listed below. The `account_settings` blueprint continues to own the category-rule and keyword-management service layer; its routes at `/account-settings/categories` remain live and are the canonical URL for that feature in v1.

**Canonical URL structure.**

| Sub-page | Canonical URL | Route owner | Notes |
|---|---|---|---|
| Settings index | `GET /settings/` | `settings_bp` | Cards for each sub-page |
| Profile | `GET /settings/profile`, `POST /settings/profile` | `settings_bp` | Display name; email change (see below) |
| Categories | `GET /settings/categories` | `settings_bp` | 302 redirect to `/account-settings/categories` in v1; move fully in 5d or 6 |
| Accounts | `GET /settings/accounts` | `settings_bp` | New in 5c |
| Security | `GET /settings/security`, `POST /settings/security` | `settings_bp` | Password change, active sessions |

**URL migration.** The existing `/account-settings/` routes are removed outright. All references in templates, `url_for()` calls, and nav links are updated to the new `/settings/` paths in the same PR. No redirect shims — this is a personal app with no external users, bookmarks, or published links to protect.

**Navigation.** The header's `Settings` link (established in ADR-0011) now targets `/settings/` instead of `/account-settings/`. The `/settings/` index renders sub-page cards using a sidebar-tab layout (see Navigation pattern below).

**Navigation pattern.** A left sidebar with tab links (Profile, Categories, Accounts, Security) is used on `/settings/*` pages. The sidebar is rendered by a shared `settings_layout` template block included in each sub-page template. On narrow viewports the sidebar collapses to a horizontal scrollable tab row. No JavaScript required; active tab is highlighted via a Jinja2 `request.path` comparison. This pattern is simpler than a card grid (which forces the user to return to the index between sub-pages) and works in server-rendered Jinja2 without any client-side routing.

**Email change flow.** Email change requires re-verification. When a user submits a new email address via `POST /settings/profile`:
1. The new address is stored as `pending_email` on the user record, not applied immediately.
2. A confirmation link is sent to the new address via Supabase Auth's email-change flow.
3. The current email and session remain valid until the user clicks the confirmation link.
4. On confirmation, Supabase updates the canonical email; the session is invalidated and the user is prompted to log in with the new address.
5. If the user does not confirm within 24 hours, `pending_email` is cleared and no change is applied.

This flow is required because email is the login credential. Allowing an unverified address change would let an attacker with momentary access to a logged-in session lock the legitimate user out permanently. The session-invalidation-on-confirmation step is a deliberate cost: it is the correct security behavior for a credential change, and it is clearly documented to the user in the UI ("You will be signed out after confirming your new email address").

## Consequences

- Positive: `/settings/*` is a stable, unified URL namespace for all current and future configuration sub-pages. Adding a new sub-page in Phase 6 (e.g., notifications, data export) requires only a new route in `settings_bp` and a new sidebar entry — no structural decision needed.
- Positive: `account_settings` blueprint stays focused on its domain (category rules, keywords, merchant aliases). Security and profile routes have a natural home in `settings_bp` without polluting the domain layer.
- Positive: removing `/account-settings/` outright is simpler than maintaining redirect shims — all references are updated in one PR with no ongoing maintenance cost.
- Positive: the re-verification email-change flow protects against session-hijack-driven account takeover at the cost of a minor UX friction point.
- Negative: `account_settings` blueprint retains its service layer but loses its routes entirely; any test assertions on `/account-settings/` paths must be updated to `/settings/`.
- Negative: the sidebar layout introduces a shared template dependency (`settings_layout` block) that all settings sub-page templates must extend. If a sub-page template deviates from the layout, the sidebar disappears silently. Implementation must enforce this via a base template, not a convention.
- Follow-ups required: (1) Account lifecycle ADR (archive vs. delete semantics for Accounts sub-page) — resolved in ADR-0034; (2) update `base.html` Settings header link and all `url_for()` calls from `/account-settings/` to `/settings/` as part of the 5c implementation PR.

## Notes

ADR-0004's blueprint table pre-recorded `settings_bp` at prefix `/settings` — this ADR is the implementation of that decision, not a deviation from it. ADR-0011 established that the header's Settings entry targets the Account Settings module landing; this ADR moves that target from `/account-settings/` to `/settings/` and adds a redirect shim so the transition is invisible to users.

The email-change re-verification requirement is driven by the `Auth implementation has security flaws` risk row in [risks.md](../risks.md) (P1, Very High impact). Any loosening of this requirement (e.g., allowing email change without re-verification) must be treated as an auth-surface change, requires its own ADR, and is subject to the security review gate described in `CLAUDE.md`.
