# Orchestration

How AI agents work this codebase. Agent roles, parallelism rules, per-phase critical path, merge protocol.

The constraints of an agent-driven build are different from a human team's. Parallel capacity is effectively unbounded; the real bottleneck is *how many independent work surfaces exist* and *how clean the contracts between them are*. Generic "throw more agents at it" thinking produces merge conflicts and silent regressions. The discipline is to design the work so that fan-out is safe.

## Agent roles

Five roles cover this project. Each role is a hat, not a hire — the same model can wear different hats; what matters is the prompt context, the input artifact, and the verification gate. Subagent definitions live in [`../.claude/agents/`](../.claude/agents/).

1. **Architect agent.** Owns ADRs, schemas, API contracts, decision documents. Output is shape and text, not shipped code. Runs first in every phase; every other agent in that phase consumes its artifacts.
2. **Implementation agent.** Takes a contract or spec and writes the code on one bounded surface at a time — one route group, one service module, one migration. Never given the whole phase as input.
3. **Test-writer agent.** Writes tests against the *contract*, not the code. Can run in parallel with the implementation agent because both consume the same spec — and tests written against the spec catch implementation drift, where tests written against the code calcify it.
4. **Refactor agent.** Mechanical repository-wide changes (blueprint split, DI wiring, import path moves). Holds an exclusive write-lock on its scope for the duration; never overlaps with feature work in the same files.
5. **Reviewer agent.** Runs tests, reads the diff, checks against the ADR, flags security regressions. Gates every merge. Without this role, agent throughput compounds into drift; with it, parallelism is safe to lean on.

## Parallelism rules

- Two implementation agents may run concurrently if and only if their **write sets are disjoint**. Read sets may overlap freely.
- The architect agent's output is input to every implementation agent in its phase. **Sequential, no exceptions.**
- The test-writer agent fans out per-module — one agent per service or route group, working from the same spec the implementation agent has.
- The refactor agent never runs concurrently with feature work in its scope. Cheaper to pause, refactor, resume than to merge two large divergent diffs.
- The reviewer agent is the merge gate, scaled per-PR. It is the cheapest role to fan out and the most expensive to skip.
- When spawning agents with `isolation: "worktree"`, scope all output paths to the worktree root — absolute paths pointing back to the main repo defeat the isolation and cause silent collisions between parallel agents. A pre-launch hook (`.claude/hooks/check-worktree-isolation.ps1`) warns at spawn time if a prompt references the main repo path.

## Critical path through the plan

**Phase 0** is dominated by refactoring. Single refactor agent, sequential within the phase. The temptation to parallelize the blueprint split, the DI rewire, and the logging scaffolding is a trap — they touch the same files. Run them in series with a reviewer between each. Throughput here comes from *small PRs*, not concurrent ones.

**Phase 1** is the longest pole and intentionally not parallelized. Auth has a small surface and an expensive failure mode; the gain from splitting it is small and the risk of a gap between parallel pieces is large. One implementation agent. Two reviewer passes — one functional, one security-oriented. The architect's Supabase-vs-self-host ADR and the test-writer's auth scenarios can both run *before* the implementation agent picks up.

**Phase 2** is the first true fan-out point. Architect agent finishes the schema and category-management contract; then four agents run concurrently: backend CRUD, frontend UI, test suite per module, and the JSON-import migration utility. Reviewer gates each PR independently.

**Phase 3** benefits from the a/b/c split because each slice has a clean contract boundary.

- **3a:** architect → schema migration (single-writer) → backend implementation + test-writer in parallel against the API contract. The existing report's update to read from DB can fan out from the same contract.
- **3b:** history view backend + history view frontend run concurrently once the route shape is locked. Edit-with-rule-forward is a thin vertical slice — single agent, because the categorization-feedback path is shared with Phase 5's smart categorization and conflicts are expensive.
- **3c:** pure backend extension against a known consumer. Implementation agent + test-writer in parallel; nothing else moves.

**Phase 4** is the highest-parallelism phase in the plan. Budget schema lands first; then CRUD, proposal feature, and actual-vs-budget views all fan out concurrently against the locked 3c API. Four to five agents, one reviewer per PR, no contention because each works on a different surface.

**Phase 5** splits along temperament rather than along files:

- **Alerting framework** is mechanical and bounded. One implementation agent, reviewer gate, ship.
- **Monthly insight summaries** is prompt-engineering work. The architect agent prototypes the prompt, the implementation agent wires the background job, but the *evaluation* of summary quality is the one place a human judgment loop is non-negotiable. Do not let an agent grade its own narrative output.
- **Smart categorization** is similar: implement the fallback path mechanically, but the decision of which user corrections become permanent rules belongs upstream of any agent.
- **Natural language queries** is research-flavored. Time-box, treat agent output as a prototype, accept that the SQL safety story will not be right on the first pass and budget for iteration.

## Where parallelism actively hurts

1. **Schema migrations.** Two agents proposing competing migrations concurrently will conflict in ways that are silent until production. Migration is a single-writer surface, always.
2. **The categorization pipeline.** Phase 3b's "apply rule forward" and Phase 5's smart categorization both write into the same path. Sequence them; do not fan out.
3. **Authentication code.** One owner per change. A parallel-induced gap in the auth surface costs more than any throughput gain.

## Pull request protocol

Each agent that produces a reviewable unit of work opens its own PR. The coordinator decides merge order and when to spawn the reviewer.

**Branch naming:** `<agent-role>/kebab-task-summary` — e.g. `architect/phase0-adrs`, `implementation/phase0-blueprint-refactor`, `refactor/extract-services-package`.

**Who opens PRs:**
- **Architect** — one PR per phase batch for ADR-only work. ADRs that have a direct implementation travel in the same PR as that implementation.
- **Implementation** — one PR per vertical slice. Test-writer output is integrated into this branch before the PR is opened — no separate test PR.
- **Refactor** — one PR per behavior-preserving slice.
- **Test-writer** — does not open PRs. Commits output to the implementation branch.
- **Reviewer** — does not open PRs. Posts findings as a PR review comment and stops. Human approves and merges.

**Steps (all agents):**
1. `git checkout -b <role>/kebab-summary` — before writing any files
2. Stage and commit work
3. Open PR via `mcp__github__create_pull_request`:
   - Title: imperative, concise
   - Body: what was decided or built, which ADRs govern it, relevant roadmap phase, anything deferred
   - Label: `adr` / `implementation` / `refactor` as appropriate
   - Assignee: human owner
4. Spawn the reviewer agent against the opened PR

## Merge protocol

Each agent works on its own branch. The reviewer agent gates each PR independently. Merge order follows the dependency graph: architect's contracts first, then everything that consumed them. The existing CI pipeline (pytest + Render deploy on merge) remains the floor — the reviewer agent is *additive*, not a replacement.

## What stays human

Three choke points where bad agent decisions are expensive to reverse, and where the cost of human review is small relative to the cost of getting it wrong:

- Final approval on schema migrations before they hit production.
- Security review of the auth surface before public launch.
- Quality judgment on insight summaries and the smart-categorization confusion matrix.

Everything else is fair game for delegation.
