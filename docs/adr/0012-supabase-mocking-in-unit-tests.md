# ADR 0012 - Supabase Mocking in Unit Tests

- **Status:** Accepted
- **Date:** 2026-05-17
- **Phase:** P2, P3a+
- **Deciders:** Architect agent

---

**⚠️ NOTE FOR FUTURE AGENTS:** This ADR supersedes ADR-0002's prohibition on mocking Supabase. If you encounter comments in the codebase referencing "Per ADR-0002: the Supabase client is NOT mocked", you can safely ignore them—this ADR-0012 is the current strategy. Update or remove those comments if you encounter them.

---

## Context

ADR-0002 mandated that Supabase tests call a real Supabase instance—no mocks—to verify behaviour through the service boundary and validate the portability constraint. However, a concrete problem has emerged: the `test_auth_service.py` test module is skipped entirely in CI when Supabase credentials are not configured, reducing test coverage visibility and blocking CI from catching errors in the auth service layer until a developer runs tests locally with credentials.

This creates a friction point for two reasons:
1. **Coverage gap in CI:** Auth service tests vanish from the CI report, making it unclear whether the auth surface has actually been tested.
2. **Slower feedback loop:** Developers must maintain local Supabase credentials or wait for human review to catch auth bugs.

Industry practice reconciles this by separating **unit tests** (mocked, fast, reliable, no credentials) from **integration tests** (real services, slower, optional for CI). The portability constraint in ADR-0002 is not undermined by mocking the Supabase client in unit tests—mocking does not create lock-in; it simply exempts unit tests from needing real credentials. A future decision to migrate away from Supabase would still reuse the unit tests (with updated mocks) and add new integration tests against the target platform.

## Options considered

### Option A - Continue requiring real Supabase for all tests

Call real Supabase in `test_auth_service.py`; tests are skipped in CI if credentials are absent.

**Pros:**
- Directly tests the portability boundary—the actual Supabase client and network calls.
- Catches integration surprises that mocks might miss (e.g., rate limits, API quirks).

**Cons:**
- Auth tests are invisible in CI, creating a false sense of coverage.
- Developers must maintain local test Supabase credentials to run the full test suite.
- Slower feedback loop: CI does not catch auth bugs until a human runs tests with credentials.
- The test suite is not hermetic—it depends on external state (Supabase availability, network, credentials).
- Adding new tests requires creating fixture data in the remote Supabase project; scaling is awkward.

### Option B - Mock Supabase in unit tests; optional integration tests in staging

Mock the Supabase client in `test_auth_service.py` using `unittest.mock`. Unit tests run in CI with full coverage. Add optional integration tests (separate module or flag) that call real Supabase in a staging environment, run on demand or nightly.

**Pros:**
- Unit tests run in CI without credentials; full test coverage is visible.
- Tests are fast and reliable; no network dependency or flaky timing.
- Mocking simplifies error simulation (e.g., "Supabase returns 500").
- Backward compatible: the portability constraint is still honoured. A future migration would replace mocks with mocks for the target platform, reuse the tests, and add new integration tests against the new provider.
- Aligns with industry best practice (unit vs. integration).
- Easier for contributors: they do not need to configure test Supabase credentials to run the test suite.

**Cons:**
- Mocks do not catch bugs specific to the real Supabase API (e.g., unusual response structure, undocumented error codes).
- Mocks may diverge from real Supabase behaviour if not kept in sync.
- If real integration tests are never written, the portability constraint becomes aspirational rather than validated.

### Option C - Hybrid: mock by default, real integration tests required before Phase 1 ships

Mock in unit tests for speed and CI visibility. Before the Phase 1 code goes to production, run a mandatory integration test suite against real Supabase to validate the boundary. Integration tests are then part of the pre-launch checklist but not part of every developer's workflow.

**Pros:**
- All of Option B's benefits.
- Adds a gate that requires real integration testing before production launch.
- Catches divergence between mocks and real Supabase before it affects users.

**Cons:**
- Requires discipline: the integration test suite must exist and be run on a schedule.
- Higher setup cost upfront (writing both mocks and real integration tests).
- Integration tests still require staging Supabase credentials and maintenance.

## Decision

We will choose **Option B (Mock Supabase in unit tests; optional integration tests in staging)** because:

1. **Unblocks CI:** Full test coverage is visible in every build, making test health transparent.
2. **Preserves portability:** Mocking does not lock us into Supabase. A future migration away from Supabase would reuse the mocked tests (with new mocks for the target platform) and optionally add new integration tests against the new provider.

The optional integration test suite is deferred: if future phases expose problems that mocks alone cannot catch, a new ADR can introduce a staging integration suite and a pre-launch validation gate.

**What is now true about the system:**

1. `test_auth_service.py` mocks the Supabase client using `unittest.mock.patch`.
2. Mocks replicate the interface and common error paths of `app.auth.services` (e.g., `AuthError` for invalid credentials, `AuthSession` with valid tokens).
3. Unit tests for all auth service functions run in CI without external dependencies or credentials.
4. The portability constraint from ADR-0002 is preserved: `app/auth/` is still the only module that imports Supabase. Application code uses abstract interfaces (AuthUser, AuthSession, etc.) that do not reference Supabase classes.
5. Comments in the codebase referencing "Per ADR-0002: the Supabase client is NOT mocked" are updated or removed to reflect this ADR.
6. If a future phase requires validating real Supabase behaviour (e.g., before public launch), a new ADR will propose and document a staging integration test suite.

## Consequences

- **Positive:** Test coverage is visible in CI for every commit. Developers do not need test Supabase credentials to run the full test suite locally.
- **Positive:** Tests are hermetic, fast, and reliable—no network dependency, no flaky timing, no external state.
- **Positive:** Error paths (e.g., "Supabase returns 500") are easier to simulate with mocks.
- **Positive:** The portability constraint is preserved. Replacing mocks when migrating away from Supabase is straightforward.
- **Negative:** Unit tests do not validate real Supabase behaviour. If real Supabase has quirks not captured in the mocks (e.g., unusual error response format), tests will not catch them until a human runs integration tests or code reaches production.
- **Negative:** Mocks must be maintained alongside the Supabase SDK. If the SDK's interface changes, mocks must be updated.
- **Follow-up required:** If Phase 5 or any pre-launch phase requires validating real Supabase behaviour, write a new ADR proposing a staging integration test suite and a pre-launch validation gate. That ADR should document which tests run in staging and how they are triggered.
- **Follow-up required:** Update or remove comments in `test_auth_service.py` (currently line 9-11) referencing ADR-0002's "no mocks" stance.

## Notes

The portability constraint from ADR-0002 is about application-layer separation, not test strategy. The constraint says: "The Supabase-specific surface is confined to a single auth integration module. The rest of the application talks to standard PostgreSQL via a connection string and writes queries that are portable to vanilla Postgres."

Mocking the Supabase client in unit tests does not violate this constraint. It is a testing implementation detail. When and if the project migrates away from Supabase, the application code stays the same (because it does not reference Supabase directly), and the unit tests can be run with new mocks targeting the new platform. The integration tests for the old platform become deprecated in favour of integration tests for the new platform.

This decision aligns with industry practice: unit tests are fast and mocked; integration tests are slower, optional, and run only on demand or in staging environments. This is the standard pattern in Spring Boot, Django, Node.js/Jest, and Rust/tokio testing frameworks.
