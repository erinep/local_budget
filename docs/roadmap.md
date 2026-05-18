# Roadmap

Phases, work items, and exit criteria. Updated as phases ship.

## Status

| Phase | Title | Status | Target | Shipped |
|---|---|---|---|---|
| 0 | Foundation Hardening | Shipped | 1–2 weeks | 2026-05-10 |
| 1 | Persistence & Authentication | Shipped | 2–3 weeks | 2026-05-16 |
| 2 | Account Settings Service | Shipped | 1–2 weeks | 2026-05-17 |
| 3a | Transaction Engine — Persistence | Shipped | 2 weeks | 2026-05-18 |
| 3b | Transaction Engine — History & Editing | Shipped | 1–2 weeks | 2026-05-18 |
| 3c | Transaction Engine — Aggregation API | Shipped | 1 week | 2026-05-18 |
| 4 | Budgeting Module | Shipped | 2–3 weeks | 2026-05-18 |
| 5a | Intelligence Layer — Report Page | Shipped | (delivered with 3c) | 2026-05-18 |
| 5b | Categorizer v2 | Not started | 2–3 weeks | — |
| 5c | Account Management & User Settings | Not started | 1–2 weeks | — |
| 5d | Reporting Overhaul | Not started | 3–4 weeks | — |
| 5e | Public-Release Hardening | Not started | 3–4 weeks | — |

Update the Status, Target, and Shipped columns when a phase moves. Update the **Current phase** field in [`../CLAUDE.md`](../CLAUDE.md) when a phase ships.

## Phase 0 — Foundation Hardening (1–2 weeks)

**Goal.** Prepare the codebase for growth before adding any new features.

**Work items.**
- Refactor `app.py` into modular structure (`routes/`, `services/`, `models/`) using Flask blueprints.
- Extract pure logic (categorize, net_amount, serialize) into a `services/` package.
- Introduce a dependency-injection pattern so category maps are passed in rather than imported as globals.
- Add structured logging (Python `logging` with a JSON formatter) and a PII scrubber for transaction data.
- Add error-tracking integration point (Sentry, free tier).
- Document architecture decisions in this `docs/` directory and start the [ADR](adr/) trail.

**Exit criteria.** The app behaves identically, but the structure can absorb new modules without rewriting routes. All tests still pass.

## Phase 1 — Persistence & Authentication (2–3 weeks)

**Goal.** Establish the data and identity foundation everything else depends on.

**Work items.**
- Choose database (recommendation: PostgreSQL via Supabase for managed auth + DB).
- Define initial schema: `users`, `sessions`.
- Integrate authentication: email/password + Google OAuth via Supabase Auth.
- Add login, logout, signup, password-reset flows.
- Add session middleware to existing routes; CSRF protection on every state-changing route, including upload.
- Migrate `custom_categories.json` to a per-user database table (Account Settings v0).
- Add database migration tooling (Alembic if SQLAlchemy, or Supabase migrations).
- Add Sentry error tracking.

**Exit criteria.** Users can sign up, log in, and continue to use the existing CSV report flow. Their custom categories persist between sessions.

**Decisions to resolve before this phase starts.** See [Open decisions](#open-decisions).

## Phase 2 — Account Settings Service (1–2 weeks)

**Goal.** Promote category management from a JSON file into a first-class service with a UI.

**Work items.**
- Schema: `categories` (id, user_id, name), `category_keywords` (id, category_id, keyword).
- CRUD UI for users to manage their own categories and keywords.
- Seed new accounts with the existing generic category map as defaults.
- Migration utility for users who want to upload their existing `custom_categories.json`.
- Caching layer: load a user's category map once per request, not per transaction.

**Exit criteria.** Users can add, rename, and delete categories and keywords entirely through the UI. The keyword JSON files are deprecated.

## Phase 3 — Transaction Engine v2

Three vertical slices, each independently shippable, with PRs sized for review and contracts that downstream phases can consume directly.

### Phase 3a — Persistence (2 weeks)

**Goal.** Move from in-memory upload processing to a persisted store. Ship a meaningful slice on its own.

**Work items.**
- Schema: `transactions` (id, user_id, date, description, amount, category_id, source_file_id), `uploads` (id, user_id, filename, uploaded_at).
- Upload writes to DB; existing report reads from DB instead of processing the upload in memory.
- Deduplication logic — uploading the same CSV twice does not double-count.
- Minimal read API surface, only what 3a's own consumers need:
  - `get_transactions(user_id, filters)` — paginated, filterable list (date range, category, search).
  - `get_transaction(user_id, transaction_id)` — single record fetch.
- API contract documented and tested independently of the route layer, so it can be reused across HTTP, background jobs, and future surfaces.

**Exit criteria.** A logged-in user's transactions persist between uploads and don't double-count on re-upload. The existing report still works, now backed by the database. This is a meaningful shipped slice on its own.

**Decisions to resolve.** Idempotency strategy, multi-account-per-user, and data retention — see [Open decisions](#open-decisions). All three are foundational and must land in ADRs before this phase ships.

### Phase 3b — History & Editing (1–2 weeks)

**Goal.** Surface the persisted history to the user and let them correct categorizations.

**Work items.**
- Transaction history view (paginated, filterable by date/category, search).
- Transaction edit capability — recategorize a single transaction, with the option to apply the same rule going forward (this writes a new keyword into Account Settings, closing the categorization feedback loop).
- No new API methods needed — both features consume the 3a surface.

**Exit criteria.** Users can browse their full transaction history and fix miscategorizations without editing JSON.

### Phase 3c — Aggregation API (1 week)

**Goal.** Extend the Transaction Engine read API with the aggregation methods Phase 4 will consume. Sequenced immediately before Phase 4 so each method is designed against a known consumer.

**Work items.**
- `get_spend_by_category(user_id, period)` — aggregate spend per category for a given period (drives Budgeting's actual-vs-budget views).
- `get_spend_history(user_id, category_id, periods)` — historical aggregates per category (drives budget proposals and trend insights).
- Performance: ensure these methods are index-friendly; add covering indexes if benchmarks warrant.
- Methods documented and tested at the service layer, independently of any route.

**Exit criteria.** The Transaction Engine's read API is sufficient for Phase 4 to consume without further extension. Each method has at least one consumer wired up before merge.

## Phase 4 — Budgeting Module (2–3 weeks) ✓ Shipped 2026-05-18

**Goal.** Add budget targets and actual-vs-budget tracking.

**Shipped work items.**
- Schema: `budgets` (id, user_id, category_id, amount) — global standing targets per category (ADR-0026).
- Budget configuration UI (`/budgets/configure`) — set and delete standing targets.
- Actual-vs-budget progress view (`/budgets/`) — monthly navigation, UNDER / NEAR / OVER status indicators.
- Propose-Budgets engine (`/budgets/propose`) — reads 3 months of spend history and suggests targets per category; gaps-only or replace-all apply modes.
- Budgets read aggregate data from the Transaction Engine via `get_spend_by_category` (ADR-0025 / ADR-0026).

**Exit criteria met.** Users can configure monthly budget targets per category, see actual-vs-budget progress in real time, and generate proposals from spend history.

## Phase 5 — Intelligence Layer & Platform Maturity

Phase 5 is split into four independently-shippable sub-phases, sequenced 5b → 5c → 5d → 5e. Phase 5a (the report page) shipped alongside Phase 3c per [ADR-0024](adr/0024-intelligence-layer-report-ownership.md).

The Intelligence Layer's charter is narrowed for Phase 5: read-only presentation and exploration only. No background jobs, no outbound LLM calls, no alerting, no anomaly detection. The "AI question" survives only inside 5b, evaluated against measured value vs. cost. Anomaly detection and narrative summaries are deferred to a hypothetical Phase 6, with no commitment.

### Phase 5a — Report Page ✓ Shipped 2026-05-18

Delivered as part of Phase 3c. Stable GET route at `/intelligence/report`, view-model assembled from the Phase 3c aggregation API, chart rendering via the existing `report_charts.js`. See [ADR-0024](adr/0024-intelligence-layer-report-ownership.md). This sub-phase is the structural placement of the Intelligence Layer; the **product** redesign of the report happens in 5d.

### Phase 5b — Categorizer v2 (2–3 weeks)

**Goal.** Replace the current uppercase-substring categorizer with a layered system that uses the user's own correction history as the source of truth, and reduces the burden of maintaining keyword lists.

**Architectural ground rules.**

- Description normalization lives in the categorizer factory (`app/transactions/services.py`). The normalization function is also exported as a standalone helper for the history view's render layer.
- Account Settings owns categorization rules. Categories own their keywords (existing, [ADR-0009](adr/0009-account-settings-schema-normalization.md)) and own their merchant aliases (new). Single write path preserved ([ADR-0005](adr/0005-category-map-dependency-injection.md)).
- Local embeddings (Tier 6 below) are gated on a measured residual from the test harness. Hosted embeddings and LLM classification are out of scope for this sub-phase.

**Work items.**

1. Tiered categorizer:
   - Tier 1 — Description normalization (strip processor prefixes like `SQ *`, `PAYPAL *`, `TST*`; strip trailing store numbers; strip city/state suffixes; collapse whitespace).
   - Tier 2 — Merchant memory: exact match against a `merchant_aliases` table.
   - Tier 3 — Token-overlap (Jaccard or TF-IDF cosine) against the user's past categorized transactions.
   - Tier 4 — Existing keyword list, retained for bootstrap and explicit overrides.
   - Tier 5 — Confidence threshold → `Uncategorized` (no guessing).
   - Tier 6 — Local embeddings (deferred; in scope only if Tiers 1–5 leave an unacceptable residual on the harness).
2. `merchant_aliases` schema under Account Settings.
3. Alias write path — the Phase 3b recategorize flow writes aliases automatically when the user opts into "apply going forward."
4. Categorization test harness — a labeled fixture set so changes can be measured rather than vibes-tested. Baseline the current accuracy before any rewrite.
5. Backfill behavior on categorizer upgrade (see open decisions).

**ADRs needed.** Categorizer strategy ADR (the fallback chain + the measurement gate for Tier 6); `merchant_aliases` schema ADR; backfill / re-categorization ADR.

**Exit criteria.** Novel merchant names get a confident category without manual keyword maintenance. The test harness exists and reports a measured accuracy number that beats the pre-rewrite baseline.

**Open decisions to resolve in ADRs.**

- **Cold-start strategy.** The app should categorize well from the first upload, not only after the user has trained it. Options: invest in a richer curated seed keyword list; ship a curated generic merchant corpus that pre-populates `merchant_aliases` for new users; or accept iterative training and design the first-upload UX accordingly.
- **Backfill on categorizer upgrade.** Do existing stored transactions get re-categorized when the categorizer changes? Options: never; on user demand; one-time automatic on upgrade.
- **Confidence threshold value.** Quantitative; punt to the harness.

### Phase 5c — Account Management & User Settings (1–2 weeks)

**Goal.** Surface the already-persisted accounts to the user and consolidate settings into a single navigable area.

**Work items.**

1. Account management UI — list, rename, archive accounts. No hard delete in v1 (cross-module purge belongs to 5e).
2. Settings consolidation page — single `/settings` entry point with sub-pages: Profile, Categories (existing, link in), Accounts (new), Security (password change, sessions).
3. Profile management — display name, email change with verification.

**ADRs needed.** Account lifecycle ADR — archive vs. delete semantics; archived-account visibility in reports and budgets.

**Exit criteria.** A user can manage their accounts and identity entirely through the UI without touching the database.

**Open decisions.** Archived-account visibility in reports/budgets (hidden by default, toggle, or hard-excluded). Resolved in the lifecycle ADR.

### Phase 5d — Reporting Overhaul (3–4 weeks)

**Goal.** Rebuild the report from the ground up. The 5a report was a structural placement exercise; 5d is a designed product. The Intelligence Layer's narrowed charter is the starting point.

**Work items.**

1. Information-architecture pass first. Define what questions the report should answer ("Where did my money go last month?", "How does this month compare to last?", "Which categories are trending up?"). Output is a design note in `docs/`, not an ADR.
2. Widget contract — typed view-model shape per widget type, extending [ADR-0024](adr/0024-intelligence-layer-report-ownership.md)'s hybrid rendering decision so new chart types extend rather than rewrite.
3. Widget catalog — at minimum: category breakdown (donut), trend (line/area), MoM and YoY comparison, top-N merchants per category, budget progress, savings rate. Decide v1 vs. later.
4. Report controls — custom date range, category include/exclude filter, period granularity.
5. Drilldown — clicking any chart slice routes to `/transactions` with prefilled filters. Reuses Phase 3b APIs.
6. Export — CSV of the current report view. PDF deferred.
7. Stretch: custom dashboard builder. Persisted as `dashboard_layouts (user_id, layout JSON)`. Feature-flagged until the widget catalog is stable.

**ADRs needed.** Widget contract ADR (extends [ADR-0024](adr/0024-intelligence-layer-report-ownership.md)); chart library decision ADR (ADR-0024 deferred this; 5d forces it); dashboard-layout schema ADR (if stretch ships).

**Exit criteria.** Report answers a defined set of questions, charts are drilldown-enabled, the user can scope to any period. The current report page is replaced, not extended.

**Open decisions.** Chart library — keep extending `static/report_charts.js`, or adopt Chart.js / Observable Plot / similar. Drop or migrate the existing `report.html`. Dashboard-builder scope (stretch vs. promote to in-scope).

### Phase 5e — Public-Release Hardening (3–4 weeks)

**Goal.** Technical readiness gate before the app could accept external signups. The decision to actually open signups is separate from this work.

**Work items.**

1. **Security audit** (~1 week) — threat model the system; dependency scan (`pip-audit`, Dependabot) to zero high/critical; secrets management review; OWASP Top 10 walkthrough; rate-limit all auth endpoints; security headers (CSP, HSTS, X-Frame-Options); resolve deferred risks from [`risks.md`](risks.md) that the public-release bar requires (GET-logout CSRF, PKCE-under-multi-worker, un-skip DB-gated upload-dedup integration tests).
2. **Operational hardening** (~1 week) — first quarterly restore drill; uptime monitoring; Sentry alerting rules that actually page; final hosting decision (resolves the long-standing open decision).
3. **Account tier foundation** (~3–5 days) — schema only: `plans (id, code, name, limits JSON)`, `user_plans (user_id, plan_id, started_at)`. Default everyone to "free." Feature-flag-by-tier helper exists; no features gated yet. No tiers actually defined.
4. **Payment processing foundation** (~3–5 days) — Stripe scaffolding: webhook receiver with signed verification, `stripe_customer_id` column on users. No checkout, no SKUs. Test mode only.
5. **Account-deletion compliance** (~3 days) — implement the cross-module purge job referenced in [`risks.md`](risks.md). Soft-delete + nightly purge. Data-export endpoint (`/settings/export` → ZIP of CSVs).

**ADRs needed (4–6).** Threat model summary; hosting decision; account-tier schema; Stripe boundary; account-deletion runbook; data-export contract.

**Exit criteria.** No known critical security or compliance gap. The app *could* be opened to external signups.

**Open decisions.** All audit findings become decisions of their own. Stripe scaffolding in 5e vs. deferred — revisit at packet start.

## Open decisions

These should be resolved before the phases that depend on them. Each becomes an ADR when decided.

| Decision | Resolve before | Notes |
|---|---|---|
| Hosted (Supabase) vs self-managed (Render Postgres + Flask-Login) | Phase 1 starts | Supabase reduces auth burden meaningfully. |
| Cookie-based vs token-based sessions | Phase 1 starts | Cookie sessions are simpler for a server-rendered Flask app. |
| Idempotency strategy for re-uploads (hash-based vs date+amount+description) | Phase 3a starts | Affects schema and dedup logic. |
| Multi-account-per-user — design for it now? | Phase 3a starts | Designing for it now is cheap; bolting it on later is expensive. Recommendation: yes, design schema for it even if UI ships later. |
| Data retention policy — what happens when a user deletes their account | Phase 3a starts | Affects the cross-module deletion runbook. |
| Hosting platform | Phase 5e | Render free tier is fine through 5d; multi-worker / paid plan needed once 5e opens the door to external signups. Options: Render paid, Fly.io, or split into Render web + separate worker. Phase 5's narrowed charter (no background jobs, no LLM endpoints) removes the prior forcing function but the public-release bar still requires resolving this. |
| Public launch — personal use vs open to others | Before any public signup flow | Changes the security and compliance bar significantly. 5e produces the technical readiness gate; this decision is the product gate. |
| Mobile experience — PWA vs React Native vs none | By Phase 3 | Affects how the API is shaped. |

## Out of scope

This plan does not cover:

- Marketing, distribution, or user acquisition.
- Mobile-native applications (PWA is implicit in the web app).
- Multi-currency or non-CAD support — architectural extension, not a phase. Worth a dedicated ADR before any non-CAD data enters the system.
- Bank API integration (Plaid, etc.) — significant compliance work, deserves its own plan.
- Sharing budgets with a partner / multi-user accounts — out of scope until Phase 5+.
