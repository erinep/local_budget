# ADR 0004 - Flask Blueprint Layout and Application Factory

- **Status:** Accepted
- **Date:** 2026-05-10
- **Phase:** P0
- **Deciders:** Architect agent

## Context

The entire application lives in a single `app.py` (171 lines). Phase 0's first work item is to refactor into a modular structure using Flask blueprints so the codebase can absorb new modules without rewriting routes. See [roadmap.md](../roadmap.md) Phase 0 — Foundation Hardening.

The system is designed around four modules: Account Settings, Transaction Engine, Budgeting Module, and Intelligence Layer (see [architecture.md](../architecture.md)). Currently only the Transaction Engine equivalent exists as a stateless CSV upload-and-report flow. The blueprint layout chosen here must accommodate the full four-module shape without over-engineering for modules that do not yet exist.

A secondary constraint: the current test suite imports the `app` object directly (`from app import app as flask_app`). Any structural change must preserve a clear upgrade path for tests, documented explicitly so the implementation agent does not have to infer it.

Relevant risks: `Solo developer burnout / context loss` and `PII leakage in structured logs` (both P0, from [risks.md](../risks.md)) underscore the need for a layout a fresh agent can navigate without onboarding.

## Options considered

### Option A - One blueprint per architectural module, all registered from the start

Define all four module blueprints (`transactions_bp`, `settings_bp`, `budgeting_bp`, `intelligence_bp`) at Phase 0 exit. Most are empty shells — they register with a URL prefix and export nothing — but the namespace exists and future phases drop code into the correct package without structural surgery.

**Pros:**
- Module boundaries are explicit before any cross-module code is written; no ambiguity about where Phase 2 or Phase 3 code belongs.
- The full directory tree signals intent to any reader, including a fresh agent, immediately.
- Blueprint variable names and URL prefixes are decided once and referenced consistently across tests, templates, and `url_for` calls.

**Cons:**
- Four packages, three of which are empty shells, add visual noise in Phase 0 and Phase 1.
- Risk of wrong-shaped shells: if the Phase 2 or Phase 3 module boundary turns out to differ from the stub, the implementation agent inherits a misleading scaffold.
- Empty blueprints registered with prefixes that have no routes produce slightly confusing 404 behavior during development.

### Option B - One blueprint for the current feature only, expand as modules are added

Define a single `transactions_bp` blueprint covering the upload and report routes. Introduce `settings_bp`, `budgeting_bp`, and `intelligence_bp` only when the corresponding phase begins.

**Pros:**
- Zero dead code at Phase 0 exit; every registered blueprint has at least one live route.
- Simpler directory tree during the phases where most development happens (P0–P2).
- Avoids committing to a blueprint shape for modules whose scope is not yet fully understood.

**Cons:**
- Structural surgery is still required at Phase 2, Phase 3, and Phase 5 to add blueprints — not avoided, only deferred.
- Later agents must make a structural decision (naming, prefix, file path) that is better made once with full system context.
- Slightly increases the risk that Phase 3 code is placed in the wrong location under time pressure.

### Option C - Application factory only, defer blueprints to Phase 1

Introduce `create_app()` to support test isolation but keep all routes in a single module for Phase 0. Register blueprints only when the first real module boundary appears in Phase 1.

**Pros:**
- Minimal change to `app.py`; the Phase 0 refactor is almost entirely internal.
- Factory pattern is the single prerequisite for Phase 1 testability; it can be introduced without any route restructuring.

**Cons:**
- Phase 0's explicit goal is to produce a structure that "can absorb new modules without rewriting routes." Deferring blueprints means the exit criterion is not fully met.
- Pushes the blueprint naming and prefix decision into Phase 1, when auth middleware and schema work are also landing — poor timing for structural decisions.
- Does not deliver the modular layout (`routes/`, `services/`, `models/`) that the Phase 0 work items list by name.

## Decision

We will choose **Option B** — one blueprint for the current feature, with the application factory and directory layout designed to accept additional blueprints with no structural changes.

Option A's empty shells create false signal; a module that doesn't exist yet should not have a registered blueprint, because the prefix and internal structure may need to change once the module is actually designed. Option C does not satisfy the Phase 0 exit criterion. Option B delivers a clean, working blueprint for the one feature that exists, establishes the layout convention all future blueprints will follow, and defers registration of future blueprints to the phases when those modules are actually designed.

The one or two reasons that carried the decision: (1) a blueprint whose routes do not exist yet provides no structural value and may encode wrong assumptions; (2) the directory layout and factory pattern — not the count of blueprints — are the durable artifacts Phase 0 must produce.

**What is now true about the system at Phase 0 exit:**

One blueprint is registered: `transactions_bp`, URL prefix `/`, defined in `app/transactions/routes.py`.

The application factory `create_app()` is defined in `app/__init__.py` and is the single entry point for both the production server and the test suite.

The directory layout at Phase 0 exit:

```
app/
    __init__.py          # create_app() factory; registers blueprints and extensions
    transactions/
        __init__.py
        routes.py        # transactions_bp = Blueprint("transactions", __name__)
        services.py      # categorize(), net_amount(), serialize_transactions(), series_to_chart_data()
templates/
    upload.html
    report.html
tests/
    conftest.py          # uses create_app(); see Consequences
    ...
app.py                   # thin entry point: from app import create_app; app = create_app()
```

`models/` is not created in Phase 0 because there is no schema yet. It is introduced in Phase 1 alongside the database. An empty `models/` package added now would be as misleading as Option A's empty blueprints.

**Blueprint registration in `create_app()`:**

```python
from app.transactions.routes import transactions_bp
app.register_blueprint(transactions_bp)   # prefix "/", no url_prefix kwarg
```

**Future blueprints follow the same convention:**

| Module | Blueprint variable | Defined in | URL prefix |
|---|---|---|---|
| Transaction Engine | `transactions_bp` | `app/transactions/routes.py` | `/` |
| Account Settings | `settings_bp` | `app/settings/routes.py` | `/settings` |
| Budgeting Module | `budgeting_bp` | `app/budgeting/routes.py` | `/budgeting` |
| Intelligence Layer | `intelligence_bp` | `app/intelligence/routes.py` | `/intelligence` |

These are recorded now so they are decided once with full system context. They are not created until the corresponding phase begins.

## Consequences

**Positive:**
- The application factory enables true test isolation: each test can call `create_app()` with a test config and receive a fresh app instance, eliminating shared global state between test runs.
- Pure logic (categorize, net_amount, serialize_transactions, series_to_chart_data) extracted into `app/transactions/services.py` is independently testable without a running Flask app or HTTP context.
- The directory convention (`module/routes.py`, `module/services.py`) is established once. Every future phase follows the same pattern without a structural decision.
- Category map loading, currently a module-level side effect on import (`GENERIC_CATEGORY_MAP = load_category_map(...)`), moves inside `create_app()` or into service function signatures. This eliminates a global-state hazard that complicates test isolation.

**Negative:**
- `app.py` becomes a thin shim rather than the application itself. Developers accustomed to running `flask run` with `FLASK_APP=app.py` must ensure the entry point correctly calls `create_app()`. This is standard Flask practice but requires explicit documentation in the project README.
- The `transactions_bp` URL prefix is `/` (no prefix), meaning its routes are at the application root. When `settings_bp` is registered with `/settings` and later routes shadow the root, the ordering of `register_blueprint` calls in `create_app()` must be deliberate. The implementation agent must register `transactions_bp` first.

**Follow-ups required:**

1. **Test suite update (required, immediate).** All tests currently import the app object as `from app import app as flask_app`. After this change they must use:
   ```python
   from app import create_app
   flask_app = create_app()
   ```
   The `conftest.py` fixture must be updated as part of the same PR that introduces the factory. The implementation agent must not merge the refactor without updating `conftest.py`; the existing 23 tests are the verification gate.

2. **Category map injection.** `GENERIC_CATEGORY_MAP` and `CUSTOM_CATEGORY_MAP` are currently module-level globals loaded at import time. After refactoring, they must be loaded inside `create_app()` and passed to the service layer, not re-imported as globals. The exact injection pattern (config dict, dependency argument, or application context) is an implementation detail left to the implementation agent, but globals loaded at import time are incompatible with a factory pattern used for test isolation.

3. **`app.py` entry point.** The top-level `app.py` remains as a Render-compatible entry point. Its only content after the refactor:
   ```python
   from app import create_app
   app = create_app()
   ```
   Render's start command (`gunicorn app:app` or equivalent) continues to work unchanged.

4. **Future blueprint ADRs.** When `settings_bp`, `budgeting_bp`, or `intelligence_bp` are introduced, the implementation does not require a new ADR for the blueprint registration itself — this ADR's table establishes the convention. A new ADR is required only if a module's prefix, internal structure, or cross-module API contract diverges from the pattern recorded here.

## Notes

The decision to keep `models/` absent in Phase 0 is intentional and should not be read as an oversight. Introducing an empty `models/` package before the Phase 1 schema design would either sit empty (misleading) or tempt premature schema work. ADR 0002 (database and auth selection) and the Phase 1 roadmap work items establish when models are introduced.

The `transactions_bp` URL prefix of `/` preserves the existing URL structure (`/` for upload/report). This means no user-visible URL change and no template `url_for` call changes in Phase 0. Future blueprints use distinct prefixes and will not conflict.
