---
adr: 0017
title: Transaction Engine Read API Contract — get_transactions and get_transaction
status: Accepted
date: 2026-05-17
phase: P3a
deciders: erin
---

## Context

Phase 3a introduces persisted transactions and the first two methods of the Transaction Engine read API: `get_transactions(user_id, filters)` and `get_transaction(user_id, transaction_id)`. The [roadmap](../roadmap.md#phase-3a--persistence-2-weeks) requires that "API contract documented and tested independently of the route layer, so it can be reused across HTTP, background jobs, and future surfaces without coupling to the route layer's request lifecycle." The [architecture doc](../architecture.md#transaction-engine) lists four eventual methods on this API; this ADR pins the two that Phase 3a owns. Phase 3c adds the remaining two (`get_spend_by_category`, `get_spend_history`) in a separate ADR.

[ADR-0003](0003-module-communication-service-layer-only.md) requires that the Transaction Engine's read API be the only surface other modules consume — direct table access from the Budgeting Module, Intelligence Layer, or any route is a bug. That makes this contract load-bearing: it must be specified precisely enough that the implementation agent, the test-writer agent, and Phase 3b consumers can all build against it without ambiguity, and stable enough that Phase 3b will not need to extend it.

The contract is bounded by three upstream decisions:

- [ADR-0013](0013-transaction-idempotency-strategy.md) pins the `fingerprint` column on `transactions`. The fingerprint is an internal dedup mechanism and MUST NOT leak to API callers.
- [ADR-0014](0014-multi-account-per-user.md) pins `account_id` as a `NOT NULL` FK on `transactions`. The read API accepts `account_id` as an optional filter from day one so Phase 3c does not need to retrofit the signature.
- [ADR-0015](0015-data-retention-on-account-deletion.md) confirms hard-cascade deletion semantics. The API has no responsibility for "soft-deleted" rows because no soft-delete state exists.

Relevant risks ([risks.md](../risks.md)): "Cross-module API contract drift" (High) — mitigated by pinning the contract before consumers exist; "Schema design locks in early mistakes" (High) — mitigated by keeping the contract independent of column-level details (the row shape exported by the API is deliberately narrower than the table's column list).

## Options considered

### Option A — Filter dataclass with explicit fields

The `filters` parameter is a `@dataclass(frozen=True)` (or `TypedDict`) with every supported filter enumerated as a named field. Callers construct the dataclass and pass it.

**Pros.** Self-documenting: the dataclass IS the contract. Type checkers catch unknown fields and wrong types. Adding a new filter in a future phase is a clear, reviewable change to the dataclass. Defaults are declared once. Test fixtures are trivial — construct the dataclass with the relevant fields, defaults cover the rest.

**Cons.** Slightly more ceremony than `**kwargs` at the call site. Forward-compatibility means new filters require dataclass changes (which is the point — the alternatives hide that change).

### Option B — `**kwargs` bag

`get_transactions(user_id, **filters)` accepts arbitrary keyword arguments and the implementation interprets what it understands.

**Pros.** Maximally flexible at the call site. No filter class to maintain.

**Cons.** No static contract — a typo (`catgegory_id=...`) silently filters nothing. Test writers cannot prove they have exercised every filter. Adding a new filter is invisible to callers; removing one breaks them silently. This is exactly the contract-drift failure mode that ADR-0003 was written to prevent.

### Option C — Fluent query-builder object

`engine.transactions(user_id).between(d1, d2).in_category(cat).search(s).page(50, 0).fetch()` — chained methods that build the query incrementally.

**Pros.** Readable at the call site. Each method is its own unit-testable surface.

**Cons.** A query-builder is a small DSL, which means a new mental model for every consumer and every test. It hides the contract behind the builder's method surface — and that surface either has to mirror the dataclass anyway (so why pay twice) or it diverges (so the contract is now spread across multiple methods). Overkill for the two-method 3a API and for the four-method final API.

### Option D — Pagination: offset vs. cursor

A sub-decision orthogonal to A–C. Offset pagination (`limit`, `offset`) is the standard SQL idiom. Cursor pagination (opaque continuation token over `(date, id)`) is more correct for very large result sets and stable under concurrent inserts.

**Cursor pros.** Stable: inserts at the head of the list do not shift rows under the user. O(1) per page, not O(offset). The right choice at large scale.

**Cursor cons.** Opaque token format becomes part of the contract; rotating it later is migration work. More plumbing in the service and the test surface. Total-count is harder to expose alongside cursors.

**Offset pros.** Trivial to implement and test. `total_count` is natural. Jumping to an arbitrary page is supported. Matches what the Phase 3b history view actually needs ("page 1 of 25").

**Offset cons.** O(offset) cost on very large pages — irrelevant at the per-user row counts a personal finance app generates over realistic time spans (low tens of thousands of rows even after several years).

## Decision

We will choose **Option A** for the filter shape and **offset pagination** for paging.

The two reasons that carried the decision: (1) a typed `Filters` dataclass makes every supported filter visible in one place that the test-writer agent can exhaustively cover, and any future filter addition becomes a single reviewable diff that consumers can react to — this is the explicit mitigation for the cross-module contract-drift risk; (2) offset pagination is correct for the realistic per-user dataset size of a personal finance app, supports the "showing 50 of 1,234" UI Phase 3b will build, and avoids encoding a cursor scheme into the contract before there is any consumer that would benefit from it.

## Public API surface

The Transaction Engine read API exports exactly the following names from `app/transactions/services.py` (or an equivalent service module). Everything else in the module is `_underscore_prefixed` and not part of the contract.

```python
# Types
TransactionFilters
TransactionPage
Transaction
TransactionNotFound  # exception

# Functions
get_transactions(user_id: str, filters: TransactionFilters | None = None) -> TransactionPage
get_transaction(user_id: str, transaction_id: UUID) -> Transaction
```

A change to any of the above is a contract change and requires a new ADR (or an explicit addendum to this one) before merging. Adding new names without removing or changing existing ones is permitted — that is the additive evolution path Phase 3c will use.

## Function signatures and types

All signatures use the standard library `uuid.UUID`, `datetime.date`, and `decimal.Decimal`. Type annotations are mandatory and enforced by the implementation agent's typing pass.

```python
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from uuid import UUID


@dataclass(frozen=True)
class TransactionFilters:
    date_from: date | None = None
    date_to: date | None = None
    category_id: UUID | None = None
    account_id: UUID | None = None
    search: str | None = None
    uncategorized_only: bool = False
    limit: int = 50
    offset: int = 0


@dataclass(frozen=True)
class Transaction:
    id: UUID
    account_id: UUID
    account_name: str
    date: date
    description: str
    amount: Decimal
    category_id: UUID | None
    category_name: str | None
    created_at: datetime  # UTC, per ADR-0001


@dataclass(frozen=True)
class TransactionPage:
    items: list[Transaction]
    total_count: int
    limit: int
    offset: int


class TransactionNotFound(Exception):
    """Raised by get_transaction when no row matches (user_id, transaction_id)."""


def get_transactions(
    user_id: str,
    filters: TransactionFilters | None = None,
) -> TransactionPage: ...


def get_transaction(
    user_id: str,
    transaction_id: UUID,
) -> Transaction: ...
```

`user_id` is typed as `str` to match the rest of the codebase's Supabase-UUID-as-string convention; the implementation accepts the canonical lowercase UUID string form. `transaction_id` is typed as `UUID` because route handlers parse it from URL segments where Python's `uuid.UUID(s)` already validates format.

`filters=None` is equivalent to `TransactionFilters()` — the no-filter case returns the most recent page of all of the user's transactions.

## Filter shape — field-by-field rules

| Field | Type | Default | Semantics |
|---|---|---|---|
| `date_from` | `date \| None` | `None` | Inclusive lower bound on `transactions.date`. UTC date per [ADR-0001](0001-utc-timestamps.md). `None` means no lower bound. |
| `date_to` | `date \| None` | `None` | Inclusive upper bound on `transactions.date`. UTC date. `None` means no upper bound. |
| `category_id` | `UUID \| None` | `None` | Match rows where `transactions.category_id = ?`. `None` means "no filter on category" — it does NOT mean "uncategorized." See `uncategorized_only` for that. |
| `account_id` | `UUID \| None` | `None` | Match rows where `transactions.account_id = ?`. `None` means all accounts. Present in 3a so Phase 3b/3c do not need to extend the signature ([ADR-0014](0014-multi-account-per-user.md)). |
| `search` | `str \| None` | `None` | Case-insensitive substring match on `transactions.description`. Normalization: both sides are compared after `str.casefold()`. Empty string is treated the same as `None` (no filter). |
| `uncategorized_only` | `bool` | `False` | When `True`, restrict to rows where `transactions.category_id IS NULL`. Composes with other filters but mutually exclusive with a non-`None` `category_id` — passing both raises `ValueError`. |
| `limit` | `int` | `50` | Maximum rows returned. Must satisfy `1 <= limit <= 200`. Out-of-range raises `ValueError`. |
| `offset` | `int` | `0` | Rows to skip before returning. Must satisfy `offset >= 0`. Negative raises `ValueError`. |

### Why `uncategorized_only` is a separate boolean, not a sentinel `category_id`

A sentinel like `UNCATEGORIZED = UUID("00000000-0000-0000-0000-000000000000")` would let `category_id` express both "filter by category X" and "filter to NULL." It is rejected because:

- `category_id` is typed as `UUID | None` and `None` already has a meaning (no filter). Reusing the same field with a magic UUID introduces a third semantic state hidden inside the type.
- A schema-level `category_id IS NULL` is a meaningful database condition; in 3a `transactions.category_id` is genuinely nullable for uncategorized rows. Naming the API filter after the underlying state (`uncategorized_only`) is clearer than encoding it in a separate UUID value.
- The `uncategorized_only` flag composes orthogonally with the other filters (date range, account, search) without overloading any of their types.

The mutual exclusivity check (`category_id is not None and uncategorized_only`) is a `ValueError` rather than a silent precedence rule because there is no defensible default behavior and ambiguity in a filter contract is exactly the kind of bug ADR-0003 warns against.

### Search normalization

The search filter performs `casefold()` on both the user-supplied query and the stored description for comparison. `casefold()` is the Unicode-correct lower-casing function (it handles e.g. German `ß`). The implementation may use Postgres `ILIKE` or `LOWER()` if and only if the comparison is provably equivalent for the ASCII subset the parser produces today; if non-ASCII descriptions ever enter the system, the comparator must be revisited. Search is substring, not prefix, not full-text. There is no support for regex, quoted phrases, or boolean operators in 3a.

## Return shapes

### `get_transactions` returns `TransactionPage`

| Field | Why |
|---|---|
| `items` | The page of transaction rows. Ordered per the sort rule below. |
| `total_count` | Count of rows matching the filters **before** `limit`/`offset` are applied. The Phase 3b history view needs this for "showing 50 of 1,234" UX, and computing it in the service avoids every consumer issuing a parallel `COUNT(*)` query. |
| `limit` | Echoed back from the request. Lets callers verify which limit was actually applied (defaults, clamping) without consulting the request object. |
| `offset` | Echoed back from the request. Same reason. |

**On including `total_count` now.** Including it in 3a costs one additional `COUNT(*)` query per call. The realistic alternative is to defer it and force every consumer to issue its own count query, which (a) duplicates the WHERE clause across consumer and service and (b) reintroduces direct cross-module SQL in any non-route consumer. The 3a cost is acceptable for the typical row counts and indexable WHERE clauses described under "Performance and indexes" below. If a future phase produces a consumer for which the count cost is measurably painful, an additional `include_total: bool = True` flag can be added without breaking the contract.

### `get_transaction` returns `Transaction` or raises `TransactionNotFound`

If no row matches `(user_id = ?, id = transaction_id)`, the function raises `TransactionNotFound`. This includes the case where the transaction exists but belongs to a different user — that lookup MUST behave identically to a non-existent row to avoid leaking existence of other users' data via timing or error type.

### The `Transaction` row shape

The shape exported to callers is deliberately narrower than the `transactions` table's column list:

- `id`, `account_id`, `date`, `description`, `amount`, `category_id`, `created_at` come directly from `transactions`.
- `account_name` comes from a join on `accounts.name`. Always present (the FK is `NOT NULL` per [ADR-0014](0014-multi-account-per-user.md)).
- `category_name` comes from a left join on `categories.name`. `None` when `category_id IS NULL`.

**Explicitly excluded from the row shape:**

- `fingerprint` — internal dedup mechanism per [ADR-0013](0013-transaction-idempotency-strategy.md). Leaking it would expose the canonicalization rule to callers and make it part of the contract. Stripped at the service-layer boundary.
- `source_file_id` — internal to the upload/dedup pipeline. Phase 3b's edit flow does not need it; if Phase 3b's history UI wants "uploaded from file X," that is a separate, additive method (`get_upload(...)`) not a column on this row shape.
- `user_id` — redundant on the row when every call already takes `user_id` as a parameter, and leaking it is a small surface-area smell.

## Tenant isolation

Every query issued by these functions MUST include `WHERE user_id = :user_id` as the first predicate. The `user_id` parameter is **required and positional** on both function signatures — it is not pulled from `flask.g`, the request context, or any thread-local. This is intentional per [ADR-0003](0003-module-communication-service-layer-only.md): the service layer is reusable from routes, background jobs, CLI tools, and tests, none of which share a single mechanism for "the current user." The caller proves who the user is; the service trusts the parameter and scopes accordingly.

Authentication is not the service layer's responsibility. A route handler authenticates the request, extracts the authenticated user's id, and passes it. A background job is responsible for proving the user id it operates on is legitimate. The service layer does not verify authentication and does not raise authorization errors — there is no `Forbidden` exception in this contract. Cross-user lookups are indistinguishable from non-existent rows by design (see `get_transaction` above).

## Sort order

`get_transactions` returns rows sorted by `(date DESC, created_at DESC, id DESC)`. The third tiebreak on `id` is required to make pagination deterministic when two rows share both `date` and `created_at` (possible for rows from the same upload). Without a fully deterministic sort, offset pagination can skip or duplicate rows across pages.

Sort order is **not configurable** in 3a. If Phase 3b's UI needs a different default (e.g., sort by amount), that becomes an additional `sort: SortOrder` field on `TransactionFilters` in a follow-up ADR. Locking the order now lets the test-writer pin pagination behavior precisely.

## Error model

| Condition | Behavior |
|---|---|
| `limit < 1` or `limit > 200` | `ValueError("limit must be between 1 and 200")` |
| `offset < 0` | `ValueError("offset must be >= 0")` |
| `date_from > date_to` (both non-`None`) | `ValueError("date_from must be <= date_to")` |
| `category_id is not None and uncategorized_only` | `ValueError("category_id and uncategorized_only are mutually exclusive")` |
| `search == ""` | Treated as `None`; no error. |
| `get_transaction`: row not found OR row belongs to a different user | `TransactionNotFound` (single exception type; identical handling) |
| Database connectivity, integrity, or other infrastructural failure | Propagates as the underlying exception (e.g., `sqlalchemy.exc.OperationalError`). The service does not wrap these. |

There is **no authorization error type** at this layer. There is no "permission denied" — the caller is responsible for proving the user id, and the service treats other users' data as not present. There is no `BadRequest` — `ValueError` is the Pythonic signal for argument validation and the route layer maps it to HTTP 400.

Validation runs before any database query is issued. The implementation must validate the `TransactionFilters` instance at the top of `get_transactions` and raise eagerly.

## Performance and indexes

The contract is shaped to be index-friendly for the queries it produces. The specific composite indexes are owned by the Phase 3a schema migration (the forthcoming `transactions` table ADR) and are referenced here so the test-writer can verify the queries hit them and so a future change to the index list is detectable as a contract change.

| Query pattern | Index relied on |
|---|---|
| Default page (no filters) | `(user_id, date DESC, created_at DESC, id DESC)` — the canonical "most recent N" index. |
| Date range filter | Same index; date predicate is a range scan on the second column. |
| Category filter | `(user_id, category_id, date DESC)` — supports both equality on `category_id` and the date sort. |
| Account filter | `(user_id, account_id, date DESC)` — analogous to category. |
| `uncategorized_only = True` | A partial index `(user_id, date DESC) WHERE category_id IS NULL` is the index-friendly choice; alternatively the planner uses the default user/date index with a `category_id IS NULL` filter. The schema ADR decides which. |
| Search filter | Substring search on `description` does not benefit from a btree. For 3a's scale (low tens of thousands of rows per user) a sequential scan inside the user partition is acceptable. If profiling later shows otherwise, a `pg_trgm` GIN index on `(user_id, description)` is the migration-time fix and does not change this contract. |
| `total_count` | Same index as the main query; the planner reuses it for the count. |
| `get_transaction` | Primary key on `id` plus `WHERE user_id = ?` — index-only via the primary key, then the user_id predicate filters at most one row. |

The exact `CREATE INDEX` statements live in the schema ADR for `transactions` and are not duplicated here. This ADR pins the *query shape*; the schema ADR pins the *index shape*; the test-writer's job is to verify they meet.

## Documentation and module surface discipline

The `app/transactions/services.py` module (or the equivalent location the implementation agent chooses, consistent with [ADR-0004](0004-flask-blueprint-layout.md)) exports the names listed under "Public API surface" above. Every other function, class, helper, or constant in that module is prefixed with an underscore and is not part of the contract.

The module docstring must:

1. Reference this ADR by number.
2. Reference [ADR-0003](0003-module-communication-service-layer-only.md) (service-layer-only).
3. State that direct queries against `transactions` from any other module are bugs.
4. Note that `fingerprint` and `source_file_id` are internal columns and never appear in the exported row shape.

The test-writer agent writes service-layer tests against these symbols directly — not via Flask test client routes. The route-layer tests are a separate, thinner surface that exercises HTTP plumbing and trusts the service contract.

## Interaction with Phase 3b and 3c

**Phase 3b** ("History & Editing") consumes this contract unchanged. The roadmap is explicit: *"No new API methods needed — both features consume the 3a surface."* The history view uses `get_transactions` with `TransactionFilters(date_from=..., date_to=..., category_id=..., search=..., limit=..., offset=...)`. The edit flow uses `get_transaction` to load the row before mutation. The mutation surface itself (recategorize, write-through to Account Settings) is a separate Phase 3b ADR; it is not part of this read API.

**Phase 3c** ("Aggregation API") adds `get_spend_by_category` and `get_spend_history` as new functions in the same module. Those functions accept their own filters object (likely a `SpendFilters` or extension thereof) — they do not modify `TransactionFilters`. The `account_id` filter is already present here precisely so 3c does not need to retrofit anything on the row-level API.

## Consequences

- **Positive.** The 3a implementation agent has a single typed surface to code against; the test-writer has a closed list of fields and error conditions to exhaust; Phase 3b can be planned without further architectural work on this surface.
- **Positive.** `fingerprint` and `source_file_id` are firewalled from callers, which keeps the dedup canonicalization (ADR-0013) and the upload pipeline as implementation details. Either can change without an API change.
- **Positive.** `account_id` is already plumbed through, so Phase 3b/3c inherit it with no retrofit.
- **Positive.** Tenant isolation is enforced at the parameter level — there is no implicit "current user" magic that could break under background-job invocation.
- **Negative.** Including `total_count` in every call costs one extra `COUNT(*)`. Mitigated by the index plan and by the option to add an `include_total: bool` flag later if profiling shows it.
- **Negative.** Offset pagination is not ideal at very large scale. Mitigated by the realistic per-user row counts and by the fact that a future move to cursor pagination would be a new ADR-pinned change, not an emergency.
- **Negative.** A frozen dataclass is slightly more ceremony than `**kwargs` at the call site. Mitigated by the explicit contract benefit and by every consumer having auto-completion against the field list.
- **Follow-up.** The schema ADR for `transactions` (forthcoming, owned by the migration agent in Phase 3a) MUST declare the composite indexes listed under "Performance and indexes" and reference back to this ADR. If the index list changes, this ADR is updated by addendum or superseded.
- **Follow-up.** Phase 3b's mutation surface (edit / recategorize) gets its own ADR. This ADR does not pin write methods.
- **Follow-up.** Phase 3c's aggregation methods get their own ADR. The `account_id` filter convention established here is the precedent.
- **Follow-up.** Status is **Proposed** until human review. This contract is consumed by Phase 3b, 3c, 4, and 5 — it is exactly the kind of cross-module surface where a second pair of eyes pays off.

## Notes

The four-method final shape of the Transaction Engine read API is listed in [architecture.md](../architecture.md#transaction-engine). This ADR pins methods 1 and 2; Phase 3c will pin methods 3 and 4 in a separate ADR. Any addition beyond those four — for example, a future `search_transactions` with full-text semantics — requires a new ADR, not an extension of this one.
