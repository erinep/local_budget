---
adr: 0027
title: Propose-Budgets Feature Deferred from Phase 4
status: Accepted
date: 2026-05-18
phase: P4 → future
deciders: erin
---

## Context

Phase 4 implemented the Budgeting Module (ADR-0025 / ADR-0026), including:

- `public.budgets` schema with global standing targets per category
- Configure UI for setting and deleting targets
- Actual-vs-budget progress view with UNDER / NEAR / OVER status indicators

During Phase 4 implementation a `propose_budgets` engine was also built:

- `propose_budgets(user_id, target_year, target_month)` — looks back 3 months of spend history and computes a suggested target amount per category
- `apply_proposed_budgets(user_id, proposals, replace_existing)` — writes the proposals as standing targets
- Routes: `GET /budgets/propose` (preview) and `POST /budgets/propose` (apply)
- Template: `templates/budgets/propose.html`

The code is complete, tested, and wired into the navigation ("Propose Budgets" links appear on the configure and progress pages).

Before Phase 4 formally closed, the product direction changed: the proposal engine's keyword-based categorization model is under review. A future phase is tentatively planned to overhaul the categorizer — moving from keyword-search matching to a richer model (e.g., embeddings-based similarity, LLM classification, or a combination). Whether the proposal engine makes sense as-is, or should be redesigned in tandem with the categorizer, is not yet decided.

## Decision

**Formally defer the Propose-Budgets feature from Phase 4 exit criteria.** Phase 4 ships the schema, configure UI, and progress view. The proposal engine is an implementation artifact of the Phase 4 sprint, not a committed Phase 4 deliverable.

The code **remains in the codebase** — it is correct, covered by tests, and harmless. The "Propose Budgets" links remain visible in the UI.

The feature is assigned to a future phase to be revisited once the broader categorization strategy is settled.

## Rationale

Removing working, tested code purely to enforce a phase boundary is wasteful. The risk from shipping the proposal engine is low (it is a read-only preview step before any write). The deferral is a product scope decision, not a quality or stability concern.

The categorization overhaul question — keyword search vs. embeddings vs. LLM classification — is non-trivial and warrants its own ADR when a direction is chosen. Key trade-offs to evaluate at that time:

- **Embeddings (e.g., OpenAI/Anthropic embeddings API):** high accuracy on ambiguous merchants, but per-query cost and latency; must decide on caching strategy and whether to store vectors in-DB.
- **LLM classification (e.g., Claude Haiku):** flexible, zero-shot, handles novel merchant names well; cost controlled via merchant-level caching (ADR-0025 notes this). Already used in Phase 5's smart-categorization work item.
- **Keyword search (current):** zero cost, zero latency, fully deterministic; brittle on new or misspelled merchants.

Seasonal-variation budget proposals (different targets per month) are also out of scope per ADR-0026.

## Consequences

- Phase 4 exit criteria are met without the proposal engine.
- `propose_budgets`, `apply_proposed_budgets`, their routes, and their tests remain in the codebase under the `app/budgets/` module.
- A future ADR will decide the categorization strategy before any further work on smart categorization or proposal refinement.
- Phase 5 (Intelligence Layer) owns smart categorization as a work item; the propose-budgets feature may be refactored to build on that work.
