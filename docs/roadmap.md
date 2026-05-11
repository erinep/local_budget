# Roadmap

Phases, work items, and exit criteria. Updated as phases ship.

## Status

| Phase | Title | Status | Target | Shipped |
|---|---|---|---|---|
| 0 | Foundation Hardening | Shipped | 1–2 weeks | 2026-05-10 |
| 1 | Persistence & Authentication | In progress | 2–3 weeks | — |
| 2 | Account Settings Service | Not started | 1–2 weeks | — |
| 3a | Transaction Engine — Persistence | Not started | 2 weeks | — |
| 3b | Transaction Engine — History & Editing | Not started | 1–2 weeks | — |
| 3c | Transaction Engine — Aggregation API | Not started | 1 week | — |
| 4 | Budgeting Module | Not started | 2–3 weeks | — |
| 5 | Intelligence Layer | Not started | 3–4 weeks, ongoing | — |

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
- Schema: `transactions` (id, user_id, date, description, amount, category_id, source_file_id), `uploads` (id, user_id, filename, uploaded_at, row_count).
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

## Phase 4 — Budgeting Module (2–3 weeks)

**Goal.** Add budget targets and actual-vs-budget tracking.

**Work items.**
- Schema: `budgets` (id, user_id, category_id, amount, period, start_date).
- Budget configuration UI.
- "Propose a budget" feature that reads transaction history and suggests realistic targets per category.
- Period-based actual-vs-budget views (current month, prior month, trailing average).
- Visual progress indicators per category (under, near limit, over).

**Exit criteria.** Users can configure monthly budgets per category and see their progress in real time.

**Note.** Budgeting consumes the Transaction Engine read API — specifically the aggregation methods added in Phase 3c — for both the initial proposal and ongoing actual-vs-budget tracking. The budget targets themselves are user-owned and live in the Budgeting Module's own tables; the Transaction Engine is read-only from here. The actual-vs-budget computation is the Budgeting Module's own responsibility, since that arithmetic is core to what a budget feature is.

## Phase 5 — Intelligence Layer (3–4 weeks, ongoing)

**Goal.** Produce language and surface anomalies that wouldn't be visible from raw data alone.

Work is ordered by priority. Each item ships independently before the next is started.

### 1. Alerting framework

- Schema: `alerts` (id, user_id, type, payload, created_at, dismissed_at).
- Rule engine for threshold alerts ("80% of food budget", "unusual transaction").
- In-app notification surface; email delivery deferred to post-launch.

### 2. Monthly insight summaries

- Claude API integration for generating narrative summaries.
- Background job that runs at month-end and writes to an `insights` table.
- Display in dashboard.

### 3. Smart categorization

- Replace keyword fallback with LLM categorization for uncategorized transactions.
- Capture user corrections; route them back through Account Settings' single write path.
- Cost control: cache merchant → category mappings aggressively.

### 4. Natural language queries (stretch goal)

- "How much did I spend on food last quarter?"
- Translate to SQL via Claude with strict query templates.
- Defer until earlier phases are stable.

**Exit criteria.** Users receive proactive alerts and a monthly summary written in plain language. Smart categorization handles new merchants without keyword updates.

**Hosting prerequisite.** Background jobs are required by item 2 and not available on the current Render free tier. The hosting decision must be resolved before Phase 4 ends — see [Open decisions](#open-decisions).

## Open decisions

These should be resolved before the phases that depend on them. Each becomes an ADR when decided.

| Decision | Resolve before | Notes |
|---|---|---|
| Hosted (Supabase) vs self-managed (Render Postgres + Flask-Login) | Phase 1 starts | Supabase reduces auth burden meaningfully. |
| Cookie-based vs token-based sessions | Phase 1 starts | Cookie sessions are simpler for a server-rendered Flask app. |
| Idempotency strategy for re-uploads (hash-based vs date+amount+description) | Phase 3a starts | Affects schema and dedup logic. |
| Multi-account-per-user — design for it now? | Phase 3a starts | Designing for it now is cheap; bolting it on later is expensive. Recommendation: yes, design schema for it even if UI ships later. |
| Data retention policy — what happens when a user deletes their account | Phase 3a starts | Affects the cross-module deletion runbook. |
| Hosting platform after Phase 2 | Phase 4 ends | Render free tier is fine through Phase 2 but not sufficient for Phase 5's background jobs. Options: Render paid, Fly.io, or split into Render web + separate worker. |
| Public launch — personal use vs open to others | Before any public signup flow | Changes the security and compliance bar significantly. |
| Mobile experience — PWA vs React Native vs none | By Phase 3 | Affects how the API is shaped. |

## Out of scope

This plan does not cover:

- Marketing, distribution, or user acquisition.
- Mobile-native applications (PWA is implicit in the web app).
- Multi-currency or non-CAD support — architectural extension, not a phase. Worth a dedicated ADR before any non-CAD data enters the system.
- Bank API integration (Plaid, etc.) — significant compliance work, deserves its own plan.
- Sharing budgets with a partner / multi-user accounts — out of scope until Phase 5+.
