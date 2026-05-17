---
adr: 0010
title: Account Settings Caching — Request-Scoped Cache via flask.g
status: Accepted
date: 2026-05-16
deciders: architect agent
---

## Context

The current `get_category_map()` service function issues a database query on every call. The Transaction Engine (Phase 3a+) will call the Account Settings service once per transaction during categorization, which means a single CSV upload with 200 rows could produce 200 database round-trips for a piece of data that does not change mid-request.

The [Phase 2 roadmap](../roadmap.md#phase-2--account-settings-service-1-2-weeks) explicitly requires: "Caching layer: load a user's category map once per request, not per transaction."

The [architecture doc](../architecture.md#account-settings) specifies: "a user's category map is loaded once per request, not per transaction. The cache key includes a version stamp that bumps on any write, so cache invalidation is implicit."

The app runs on Render's free tier: single dyno, single process, single thread per request (Gunicorn with one worker is the Phase 1 deployment). The cache must be correct when multiple users are served by the same process.

## Options considered

### Option A — Flask `g` object (request-scoped cache)

Store the loaded category data in `flask.g` keyed by `user_id` on first access within a request. `g` is request-scoped: it is created fresh at the start of each request and discarded at the end. It is naturally evicted with no TTL logic. Multiple users in the same process are correctly isolated because each request gets its own `g`.

**Pros:**
- Zero additional dependencies.
- No TTL complexity — the cache cannot go stale within a request because the request lifecycle is shorter than any mutation window.
- Correct for multi-user workloads: `g` is per-request, not per-process.
- Cache invalidation is trivially "delete the key from g" on any write call; since the current request issued the write, the deleted key is immediately re-populated on the next read within the same request.
- Works correctly under the existing single-worker deployment and under future scaled deployments without modification.

**Cons:**
- Does not cache across requests. Every new request pays one DB query. For a personal finance app where the category map changes infrequently, this is the correct trade-off — stale cross-request caches are a correctness risk, not a performance optimization.
- `flask.g` is only available inside a Flask application context. Service functions called outside a request context (e.g., from a CLI command) must handle the `RuntimeError` gracefully, the same way the existing `_load_seed_map()` fallback already does.

### Option B — Flask-Caching with SimpleCache (process-scoped, TTL-based)

Add the `Flask-Caching` library. Configure `SimpleCache` (in-memory, process-scoped). Cache `get_category_map` results keyed by `user_id` with a short TTL (e.g., 60 seconds). Invalidation calls `cache.delete(key)` on writes.

**Pros:**
- Survives across multiple requests to the same process — a second request within the TTL window pays no DB cost.
- `Flask-Caching` is a well-maintained library with a clean decorator API.

**Cons:**
- Adds a dependency. The caching problem does not require a library when `flask.g` is available.
- TTL introduces a staleness window. If two requests overlap and one writes while the other has the old value cached, the second request uses stale data for up to TTL seconds. For a personal finance app this is unlikely but the bug is real.
- `SimpleCache` is process-local, so it does not survive process restarts or scale beyond one worker — the same constraint as Option A, but with more code.
- Explicit cache invalidation via `cache.delete()` must be called in every write path. Missing a call means stale data survives until TTL expiry. Option A avoids this class of bug entirely because the cache does not outlive the request.

### Option C — Thread-local cache

Store the map in a `threading.local()` object. Manually reset it at the start of each request via a `before_request` hook.

**Pros:** Zero dependencies.

**Cons:** Flask's request context (`g`) already provides exactly this abstraction, with lifecycle hooks managed by Flask. Implementing it manually with `threading.local()` duplicates Flask internals, adds a `before_request` hook that must not be forgotten, and provides no advantage over Option A.

## Decision

We will choose **Option A — Flask `g` object**.

The two reasons that carried the decision: (1) `g` is the idiomatic Flask mechanism for exactly this pattern — per-request memoization — and requires zero new dependencies or TTL reasoning; (2) request-scoped cache invalidation is implicit (the cache evicts itself when the response completes), which eliminates the class of "forgot to invalidate" bugs that TTL-based or explicit-delete caches introduce.

## Implementation contract

The following rules are binding for all Phase 2 implementation:

**Cache key:** `g._category_cache` is a dict keyed by `user_id` (string). Each value is the fully-loaded list of categories with their keywords, as returned by `list_categories()`.

**Read path:** Every service function that reads categories must check `g._category_cache.get(user_id)` before issuing a DB query. If the key is absent, query the DB, store the result in `g._category_cache[user_id]`, and return it.

**Write path:** Every service function that mutates categories or keywords (create, rename, delete, add keyword, remove keyword, import, seed) must delete `g._category_cache.pop(user_id, None)` after committing the transaction. The next read within the same request will re-populate from the DB.

**Outside request context:** Service functions must handle the case where `flask.g` is unavailable (e.g., CLI commands, tests without an app context) by falling through to a direct DB query with no caching. Wrap the `g` access in a `try/except RuntimeError` or check `has_request_context()`.

**Cache shape:** The cache stores the output of `list_categories(user_id)` — a list of dicts with `id`, `name`, and `keywords`. `get_category_map()` derives its `{name: [keyword, ...]}` return value from this cached structure rather than issuing a separate query. This means both `get_category_map` and `list_categories` share one cache entry per user per request.

## Consequences

- **Positive:** No new library dependencies.
- **Positive:** A CSV upload with 200 transactions pays one DB query for the category map regardless of how many times the service is called during the request.
- **Positive:** Cache correctness is guaranteed by the request lifecycle — no staleness window, no missed invalidation bugs from cross-request state.
- **Negative:** Each new request pays one DB query even if the category map has not changed since the previous request. This is acceptable: the category map changes infrequently, and the alternative (process-scoped cache) introduces staleness risk without measurable performance benefit at the current scale.
- **Negative:** The `flask.g` dependency means service functions are not entirely decoupled from the Flask runtime. The mitigation is the `try/except RuntimeError` fallback documented above, which is already the pattern used in the existing `_load_seed_map()` function.
- **Follow-up:** If the app ever moves to a multi-worker deployment where the category map is mutated by one worker and read by another in the same request window, this cache is still correct — `g` is per-request, not per-process. No architectural change is needed for that scenario.
- **Follow-up:** If a future phase introduces background jobs that call Account Settings service functions outside a request context, those callers must not assume `g` is available. The `has_request_context()` guard covers this.
