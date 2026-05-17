# Risks

Living risk register. Each row names a failure mode, the phases it applies to, and the concrete mitigation. Add rows as new risks surface; edit existing rows when mitigations land.

## How to use this file

- For phase-scoped work, **filter by the Phase(s) column** to the current phase plus any rows tagged `All`.
- When a mitigation lands, edit the row to reflect the new state. Do not delete rows; risks downgrade rather than disappear.
- New risks are added at the bottom or grouped near related risks. There is no required order.

**Phase notation.** `P0`, `P1`, `P3a`, etc. refer to the phases in [roadmap.md](roadmap.md). `P1+` means "Phase 1 onward." `All` means cross-cutting from Phase 0.

## Register

| Risk | Phase(s) | Likelihood | Impact | Mitigation |
|---|---|---|---|---|
| Schema design locks in early mistakes | P1+ | Medium | High | ADRs + migration tooling from Phase 1; small reversible changes; multi-account-per-user designed into the schema even if UI is deferred |
| Auth implementation has security flaws | P1 | Medium | Very High | Supabase Auth rather than rolling own; CSRF on every state-changing route including upload; rate-limited auth endpoints; security review before public launch |
| Cross-module API contract drift | P3a+ | Medium | High | Contract tests at the service-layer boundary, independent of routes; explicit version on the Transaction Engine read API; downstream modules pin to a contract version and update deliberately |
| Read API performance degrades with history size | P3a, P3c, P4+ | Medium | Medium | Index design reviewed when the transactions schema lands; benchmark the aggregation methods against a synthetic year of data before Phase 4 ships; introduce precomputed monthly aggregates if linear scans are too slow |
| Categorization feedback writers conflict | P3b, P5 | Medium | Medium | Single write path through Account Settings for both "apply rule forward" corrections and smart-categorization corrections; conflict-resolution rule (most-recent-wins, with provenance) documented in an ADR |
| Background-job infrastructure missing when needed | P4, P5 | Medium | High | Hosting decision (Render paid vs Fly.io vs split web/worker) resolved before Phase 4 ends so Phase 5 has somewhere to run; documented in an ADR; alerting framework built to be queue-agnostic |
| PII leakage in structured logs | P0+ | Medium | High | Log scrubber for transaction descriptions, amounts, and email addresses introduced with structured logging in Phase 0; CI lint rule preventing raw transaction objects in log statements; sample log review on every reviewer-agent pass |
| LLM endpoints exposed to runaway cost | P5 | Medium | Medium | Per-user daily call cap on smart-categorization; merchant-level caching with a long TTL; circuit breaker if monthly cost crosses a configured threshold; hard budget cap on monthly summary jobs |
| Timezone handling drift between upload and storage | P3a+ | Medium | Medium | Store all timestamps in UTC; one canonical conversion layer when rendering to user-local time; ADR documenting the convention; tests covering DST transitions |
| Account deletion incomplete across modules | P1+ (design P3a) | Medium | High (compliance) | Cross-module deletion runbook designed alongside Phase 3a's retention-policy decision; soft-delete with a single purge job rather than scattered hard-deletes; periodic audit query verifying deletion completeness |
| Backups exist but restore is never tested | P1+ | Medium | Very High | Quarterly restore drill into a scratch database with checksum verification of a known-good row set; runbook documented and rehearsed |
| Reviewer agent gives false passes or false fails | All | Medium | High | Reviewer agent calibrated against a fixture suite of known-good and known-bad PRs; human spot-check rate tuned per phase (highest in Phase 1, lower by Phase 4); reviewer's pass/fail rationale logged for audit |
| Supabase platform risk (pricing, availability, lock-in) | P1+ | Low | High | Schema and application code stay portable to vanilla Postgres; Supabase-specific surface confined to the auth integration with a documented migration path to Flask-Login + Postgres |
| Scope creep in Intelligence Layer | P5 | High | Medium | Each intelligence feature is its own ticket and ships before the next is started; alerting before insights, insights before smart categorization, NLQ explicitly a stretch goal |
| Solo developer burnout / context loss | All | High | High | Phase 0 hardening (structured logging, ADRs, modular layout) makes returning to the project easier; agent orchestration model documented so work can be picked up by a fresh agent without onboarding |
| Data loss during a migration cutover | P1+ | Low | Very High | Always migrate to a copy first; verify with checksums and row counts; cut over only after verification; rollback plan rehearsed before each migration |
| GET /auth/logout is CSRF-vulnerable (side-effect on GET) | P1+ | Low | Low | A cross-origin `<img src="/auth/logout">` could log a user out. Acceptable for a personal single-user app with no untrusted content; convert to POST + CSRF token before opening to multiple users. Accepted tradeoff in Phase 1 (ADR-0006). |
| Google OAuth PKCE verifier lost under multi-worker deployments | P1.5 | Low | Medium | Supabase SDK stores the PKCE verifier in the module-level client singleton's in-memory storage. If Gunicorn uses multiple workers, the callback may hit a different worker and fail. Render free tier uses 1 worker — acceptable now. If workers are scaled, migrate OAuth initiation/callback to use a shared store (e.g., signed cookie or DB) for the verifier. |
