# ADR 0002 - Supabase for Database and Authentication

- **Status:** Accepted
- **Date:** 2026-05-10
- **Phase:** P1
- **Deciders:** Architect agent

## Context

Phase 1 (Persistence & Authentication) requires both a managed PostgreSQL database and a secure authentication system. The project is a solo-developer personal finance application; the implementation cost of rolling and maintaining auth infrastructure must be weighed against the operational ceiling of vendor-managed services. This decision was listed as an open item in [roadmap.md](../roadmap.md) and must be resolved before Phase 1 implementation begins. The relevant risk register row is "Supabase platform risk (pricing, availability, lock-in)" in [risks.md](../risks.md).

## Options considered

### Option A - Supabase (managed PostgreSQL + Supabase Auth)

A single provider supplying both the database and auth layer. Supabase Auth handles password hashing, JWT issuance, email verification, and Google OAuth out of the box. The database is standard PostgreSQL; Supabase exposes it directly via a connection string, making the schema portable to any Postgres host.

**Pros:**
- Auth correctness is the hardest part of Phase 1; delegating it to a maintained service eliminates an entire class of implementation risk flagged as Very High impact in risks.md.
- Single vendor for DB and auth means one dashboard, one connection string, one billing relationship.
- Google OAuth and email/password flows are pre-built, reducing Phase 1 scope by several tickets.
- Supabase CLI ships migration tooling that can double as the project's schema change mechanism.
- Encryption at rest and daily backups are provided by the platform, satisfying the architecture.md security requirements without custom configuration.
- Free tier is sufficient for personal use through Phase 4.

**Cons:**
- Free tier pauses projects that have been inactive for more than 7 days; this is a concrete operational risk for a personal project with irregular usage.
- Supabase-specific SDKs and Row-Level Security features, if adopted without discipline, create sticky coupling that makes future migration expensive.
- Single provider means a Supabase outage or pricing change affects both DB and auth simultaneously.
- Vendor lock-in risk if Supabase-specific query features are used in application code.

### Option B - Self-managed (Render PostgreSQL + Flask-Login or Flask-Security)

Render provides a managed PostgreSQL add-on. Flask-Login handles session management; Flask-Security or a custom implementation handles password hashing and OAuth.

**Pros:**
- No vendor that controls both DB and auth; each can be swapped independently.
- No free-tier pause risk on Render paid tier.
- No Supabase-specific surface at all; everything is vanilla Postgres and Python.

**Cons:**
- Rolling correct auth is the highest-risk item in Phase 1 (risks.md: "Auth implementation has security flaws", Likelihood: Medium, Impact: Very High). Flask-Login does not handle password hashing, email verification, password reset, or OAuth — each of these must be built and tested.
- Google OAuth integration via a Flask library (Authlib, Flask-Dance) requires additional setup, secret management, and callback handling.
- Render's free PostgreSQL tier is limited and the database is deleted after 90 days; the paid tier adds cost to a personal project.
- Operational surface is wider: database backups, encryption at rest, and connection pooling require explicit configuration.

### Option C - Auth0 for auth + self-managed Postgres

Auth0 handles authentication; the database runs on Render or another Postgres provider independently.

**Pros:**
- Auth0 is a mature, well-documented auth platform with broad OAuth and MFA support.
- Complete separation between the auth and database concerns; each can be migrated independently.
- Auth0's free tier supports up to 7,500 monthly active users, which is more than sufficient.

**Cons:**
- Two separate vendor relationships to manage (Auth0 + Postgres host) with different billing, dashboards, and failure modes.
- Auth0's free tier also has usage constraints; the pricing model is more complex than Supabase's.
- No database managed by Auth0; a Postgres host is still needed, so this option does not reduce total vendor count versus Option A — it increases it while removing the integrated convenience.
- Adds integration complexity: Auth0 JWTs must be validated against a separate JWKS endpoint; the Flask application owns the session bridge between Auth0 tokens and server-side session state.

## Decision

We will choose **Option A (Supabase)** because delegating authentication to a maintained service is the single most effective mitigation of the Very High impact auth-security risk, and because the portability constraint below keeps the lock-in surface bounded.

**What is now true about the system:**

1. Supabase provides the PostgreSQL database from Phase 1 onward.
2. Supabase Auth handles email/password and Google OAuth authentication.
3. The Supabase-specific surface is confined to a single auth integration module. The rest of the application talks to standard PostgreSQL via a connection string and writes queries that are portable to vanilla Postgres. No Supabase-specific query syntax, Row-Level Security policies, or Supabase client SDK calls appear outside the auth integration module.
4. The schema is designed and maintained in migration files that are portable to any Postgres host. Migration tooling (Alembic or Supabase CLI migrations) will be decided in a separate ADR before Phase 1 ships.
5. The documented migration path away from Supabase Auth is: replace the auth integration module with Flask-Login + a self-managed password store, re-issue sessions, and point the DB connection string at a new Postgres host. This path is feasible precisely because the portability constraint above is enforced.

## Consequences

- **Positive:** Auth correctness risk is offloaded to a maintained vendor. Google OAuth, email verification, and password reset are available without custom implementation. Encryption at rest and automated backups are provided. Phase 1 scope is smaller.
- **Positive:** The codebase retains a clear migration path because Supabase-specific surface is bounded by convention and enforced in code review.
- **Negative:** Supabase's free tier pauses projects inactive for more than 7 days. For a personal project with irregular usage this is a real operational nuisance — the first request after a pause incurs a cold-start delay of up to 30 seconds. The mitigation is a documented runbook: if pause latency becomes unacceptable, upgrade to the Supabase Pro tier or migrate the database to a Render paid instance (the portability constraint makes this tractable).
- **Negative:** Combining DB and auth in one provider means a single Supabase service disruption affects both. This risk is accepted given the low likelihood and the personal-use scale of the project.
- **Negative:** The team must resist the convenience of Supabase-specific features (RLS, realtime subscriptions, storage) that would increase coupling. This is a discipline constraint, not a technical one.
- **Follow-up required:** A separate ADR must decide between Alembic (SQLAlchemy-integrated) and the Supabase CLI migration tooling before Phase 1 ships. This is the schema migration tooling decision listed as a Phase 1 work item in roadmap.md.
- **Follow-up required:** The auth integration module boundary must be identified and documented before the first auth PR is merged, so reviewers can enforce the portability constraint from the start.

## Notes

The "Supabase platform risk (pricing, availability, lock-in)" row in risks.md captures the long-term version of this tradeoff. That row's mitigation — "Schema and application code stay portable to vanilla Postgres; Supabase-specific surface confined to the auth integration with a documented migration path to Flask-Login + Postgres" — is operationalised by this ADR's portability constraint.

The free-tier pause behavior is distinct from the platform risk and worth naming separately: it is not a financial or lock-in risk, it is an availability nuisance that affects day-to-day development. It does not appear as its own row in risks.md as of this writing; if it becomes a recurring problem during Phase 1 development it should be added.

The decision to resolve both DB and auth with one provider was deliberate. A two-provider arrangement (Option C) would require managing two billing relationships, two failure domains, and a more complex token-validation integration — costs that are not justified at personal-project scale.

**See also:** ADR-0012 (Supabase Mocking in Unit Tests) modifies the testing strategy for this decision. While ADR-0002 specifies that Supabase is the platform choice, ADR-0012 relaxes the requirement that unit tests call real Supabase—mocks are appropriate for fast, reliable unit test coverage; real integration tests are deferred. This does not change the portability constraint; it only clarifies how the boundary is tested.
