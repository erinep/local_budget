# ADR 0003 - Module Communication via Service-Layer Interfaces Only

- **Status:** Accepted
- **Date:** 2026-05-10
- **Phase:** All (cross-cutting — applies from P1 onward when distinct modules exist)
- **Deciders:** Architect agent

## Context

Starting in Phase 1 the system grows from a single-file Flask app into four distinct modules: Account Settings, Transaction Engine, Budgeting Module, and Intelligence Layer. Each module owns a bounded slice of the schema. Without an explicit inter-module communication rule, the natural Python inclination is to import whatever model or query is convenient — a pattern that erases module boundaries silently and compounds with every new feature. The cross-module API contract drift risk in [risks.md](../risks.md) names this failure mode directly. This ADR establishes the rule that governs all inter-module data exchange from Phase 1 onward, prior to any module implementation beginning.

The Transaction Engine is the most-consumed module in the system: the Budgeting Module reads spend aggregates from it, and the Intelligence Layer reads both transactions and budget state. The stability of its read API is load-bearing for every downstream phase. See [roadmap.md](../roadmap.md) phases 3a, 3c, 4, and 5 for the consuming phases.

## Options considered

### Option A - Service-layer interfaces only

Each module exposes a documented set of Python functions (the service layer) as its public contract. No other module may import that module's ORM models or execute queries against its tables directly. Cross-module reads call only these functions.

**Pros.**
- Boundaries are enforced by convention and code review rather than process alone; violations are visible as import violations or misrouted queries.
- The service API is the single place to add caching, access control, and pagination — callers get these for free.
- The Transaction Engine read API (documented in [architecture.md](../architecture.md)) can be tested in isolation at the service layer, independent of any HTTP route, which keeps integration tests clean and reusable across web requests and future background jobs.
- Contract drift is detectable: if a consuming module imports a model it does not own, that is an unambiguous bug signal.

**Cons.**
- Requires discipline: Python does not enforce module privacy, so the boundary is maintained by convention and review rather than by the runtime.
- Introduces indirection — a caller must find and understand the service function rather than writing a direct query. This is minor but real.
- Service functions must be designed up-front rather than evolved opportunistically from queries that already exist in templates or routes.

### Option B - Shared schema reads (convention-only ownership)

Any module may query any table. Ownership is a documentation convention, not enforced at the code level. Developers are expected to follow the convention.

**Pros.**
- Zero up-front design cost — queries go where they are needed without indirection.
- Easier to prototype and iterate quickly in early phases.

**Cons.**
- Ownership is invisible to tools, linters, and reviewers. Drift is undetectable until production breakage.
- Schema changes in the Transaction Engine — a table rename, a column split, a new nullable — silently break every caller across all modules, not just the Transaction Engine's own code.
- Pagination, access control, and caching must be re-implemented or remembered at every call site; inconsistency is the default outcome.
- The cross-module API contract drift risk in [risks.md](../risks.md) names this failure mode explicitly. A medium-likelihood, high-impact event.
- The Intelligence Layer, which owns no canonical data and is supposed to be replaceable, becomes entangled with the Transaction Engine's schema. Replacing or pausing the Intelligence Layer is no longer safe.

### Option C - Event bus / message broker

Modules communicate by publishing domain events (e.g., `transaction.categorized`, `budget.period.closed`) to a shared bus. Downstream modules subscribe and maintain their own read models.

**Pros.**
- Strong decoupling: the producing module has zero knowledge of its consumers.
- Natural foundation for real-time alerting (Phase 5), audit logs, and future async processing.
- Write-side decoupling means a slow consumer cannot block the producer.

**Cons.**
- Introduces a new operational dependency (queue broker, worker process) before the system has any background-job infrastructure. Render free tier does not support persistent workers through Phase 2.
- Eventual consistency requires consumer modules to handle out-of-order or duplicate events. This complexity is unjustified when three of the four modules are web-request-scoped and synchronous.
- Debugging a broken aggregation requires tracing events across module boundaries rather than stepping through a single call stack.
- The system does not yet have the operational maturity (observability, on-call runbook, infrastructure budget) that justifies this architecture.

## Decision

We will choose **Option A** because it enforces module boundaries with minimal operational overhead and makes contract drift detectable rather than silent.

**What is now true about the system:**

No module may import another module's ORM models or execute queries directly against another module's tables. This applies to all inter-module access, including reads. Violations are bugs, not shortcuts. Cross-module reads go through the consuming module's service interface.

Specifically:
- The Budgeting Module reads from the Transaction Engine exclusively via `get_spend_by_category` and `get_spend_history` (added in Phase 3c). It does not query the `transactions` table directly.
- The Intelligence Layer reads from both the Transaction Engine and the Budgeting Module via their respective service-layer functions. It does not join across their tables.
- Account Settings is consumed by the Transaction Engine for categorization; the Transaction Engine calls the Account Settings service to load a user's category map — it does not query the `category_keywords` table directly.

Option C (event bus) is a valid future direction for write-side decoupling, particularly for Phase 5 alerting where threshold checks may need to run asynchronously. It is not chosen now because the system has no background-job infrastructure and no synchronous operations that would benefit from async decoupling at this scale. If Phase 5 alerting warrants it, a new ADR should be written to introduce an event bus as a complement to the service layer, not a replacement.

## Consequences

- **Positive:** Schema changes inside a module are local by construction. Renaming a column in `transactions` requires updating the Transaction Engine service layer and its tests — no other module is affected unless the service API signature changes.
- **Positive:** The Transaction Engine read API becomes the stable contract that Phase 4 and Phase 5 consume. Pinning that contract at the service layer means downstream agents can build against it without tracking schema internals.
- **Positive:** Caching, pagination, and access control are implemented once in the service function and inherited by all callers. The per-request category map cache documented in [architecture.md](../architecture.md) is an example of this pattern.
- **Positive:** Service-layer tests are independent of routes and reusable across HTTP handlers, background jobs, and future CLI tools.
- **Negative:** Service functions must be written before consumers can be written. This is a minor sequencing cost, not a blocking one — the functions are small and their signatures are defined in the roadmap.
- **Negative:** Python does not enforce module privacy. The boundary is maintained by code review, linting, and developer discipline. A `grep` for cross-module model imports should be part of reviewer-agent checks from Phase 3a onward.
- **Follow-ups required:** The Transaction Engine read API contract (`get_transactions`, `get_transaction`, `get_spend_by_category`, `get_spend_history`) must be documented precisely — with parameter types, return shapes, pagination contract, and error modes — before Phase 3a merges. That contract documentation lives in [architecture.md](../architecture.md) and is pinned here. Any change to the contract requires either a new ADR or an explicit addendum that downstream agents can discover.

## Notes

The module boundary rule is already stated as a first-class constraint in `CLAUDE.md`: "Modules talk only through documented APIs. Cross-module reads via service-layer interfaces. Direct database access into another module's tables is a bug, not a shortcut." This ADR exists to record why that rule was chosen over the alternatives, not merely to restate it.

The cross-module API contract drift risk ([risks.md](../risks.md)) calls for contract tests at the service-layer boundary, independent of routes, and an explicit version on the Transaction Engine read API. Those mitigations are compatible with this decision and are the responsibility of the test-writer agent when Phase 3a ships.
