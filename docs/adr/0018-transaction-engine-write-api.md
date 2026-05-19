---
adr: 0018
title: Transaction Engine Write API — recategorize_transaction
status: Accepted
date: 2026-05-18
phase: P3b
deciders: erin
---

## Context

Phase 3b adds a write path to the Transaction Engine for the first time. ADR-0017 explicitly deferred mutation methods: "The mutation surface itself (recategorize, write-through to Account Settings) is a separate Phase 3b ADR; it is not part of this read API." Phase 3b allows a user to correct a miscategorized transaction and optionally apply the same rule going forward, which writes a new keyword to Account Settings.

Three binding constraints from prior ADRs and the risk register:

- **ADR-0003** (service-layer-only module communication): no module may write directly to another module's tables. The Transaction Engine MUST NOT write to `public.categories` or `public.category_keywords`. Cross-module writes flow through the owning module's service interface.
- **ADR-0017** (read API contract): the public surface of `app/transactions/services.py` is enumerated; anything added here extends that surface and must be documented with equal precision.
- **risks.md — "Categorization feedback writers conflict"** (P3b, Medium/Medium): the "apply forward" write and any future smart-categorization write must go through Account Settings' single write path with a documented conflict-resolution rule.

The architecture doc is explicit: Account Settings is "the single write path for any change to a user's category map." Any keyword created by the recategorize flow must flow through `app/account_settings/services.add_keyword`.

## Options considered

### Option A — Single function: recategorize_transaction always writes keyword when requested

`recategorize_transaction(user_id, transaction_id, category_id, apply_forward=False)` — one function. When `apply_forward=True` it calls `add_keyword` after updating the transaction row. Both happen inside the same request; they share a function call but separate database transactions (Transaction Engine commits its own row; Account Settings commits its keyword separately through its own `engine.begin()` block).

**Pros.** One call site for the route handler. Simple mental model: one action, one function. The `apply_forward` flag makes the feature discoverable in the signature.

**Cons.** The two side effects (update transaction, write keyword) have different failure modes. If the keyword write fails (e.g., keyword already exists, or the category_id is now invalid between calls), the transaction row has already been updated and there is no rollback across the two commits. The caller cannot suppress the keyword write without a new parameter.

**Consequence.** The single-transaction guarantee is impossible here without a shared transaction scope, which would violate ADR-0003 (the Transaction Engine cannot reach into Account Settings' connection or vice versa). The atomicity gap is unavoidable regardless of option; what differs is where it is made visible.

### Option B — Two separate functions: recategorize_transaction and let the route call add_keyword directly

`recategorize_transaction(user_id, transaction_id, category_id)` — pure transaction update. The route handler calls `add_keyword` separately when the user checked "apply forward."

**Pros.** Maximum composability. The route handler is fully in control of sequencing. The Transaction Engine's write function has no dependency on Account Settings.

**Cons.** ADR-0003 already allows the route layer to call multiple service functions; this is fine architecturally. However, the route handler now owns the "apply forward" logic rather than the service layer. Future callers (CLI tools, background jobs) must remember to call `add_keyword` themselves if they want the same behavior. The keyword write is also not "on behalf of" a transaction — the route passes a bare `category_id` and `keyword` with no provenance — so the conflict-resolution rule must be stated at the route layer, not the service layer.

**Consequence.** The categorization feedback risk mitigation ("conflict-resolution rule documented in an ADR") is harder to enforce when the coordination logic is split between two unrelated call sites.

### Option C — Recategorize function orchestrates both writes, with explicit error handling for the keyword step

`recategorize_transaction(user_id, transaction_id, category_id, apply_forward_keyword=None)` — the Transaction Engine function commits the transaction row update, then, if `apply_forward_keyword` is a non-None string, calls `account_settings.services.add_keyword`. Errors from the keyword step do not roll back the already-committed transaction update; they are surfaced to the caller as a distinct exception.

**Pros.** The coordination logic — "which module does what, in which order" — is documented in one place. Route handlers call one function and receive a clear result. The conflict-resolution rule (keyword already exists → not an error, treat as success) is encoded once in the service layer, not per-call-site. The Transaction Engine's dependency on Account Settings is explicit in the function signature and in this ADR, not hidden in route code.

**Cons.** The Transaction Engine imports from Account Settings — a cross-module import that ADR-0003 permits only via the service interface, which this satisfies. The partial-failure case (transaction updated, keyword write failed for a reason other than "already exists") must be documented.

**Consequence.** This option makes the atomicity gap explicit and names it. The route handler receives either full success or a structured result indicating which step failed, and can surface the appropriate message to the user.

## Decision

We will choose **Option C**.

The two reasons that carried the decision: (1) the categorization feedback risk explicitly requires a "conflict-resolution rule documented in an ADR" — encoding that rule inside the Transaction Engine's orchestrating function is the only way to ensure every caller (route, CLI, future background job) inherits it without reimplementation; (2) Option B places coordination logic in route handlers, which is not reusable across surfaces, and Option A hides the partial-failure gap behind a bool flag rather than naming it.

The cross-module import (`from app.account_settings import services as _account_settings_svc`) is permitted because it goes through the Account Settings service interface — it does not touch `public.categories` or `public.category_keywords` directly. ADR-0003 requires service-layer-only communication, not zero inter-module imports.

## Public API extension

The following names are added to `app/transactions/services.py`. They extend ADR-0017's public surface; all prior names remain unchanged. The underscore-prefixed convention and module docstring rules from ADR-0017 apply equally here.

```python
# New exception
class CategoryNotFound(Exception):
    """Raised by recategorize_transaction when category_id does not belong to user_id."""


# New result type
@dataclass(frozen=True)
class RecategorizationResult:
    transaction: Transaction      # Updated transaction row (post-commit state)
    keyword_written: bool         # True if apply_forward_keyword was written to Account Settings
    keyword_conflict: bool        # True if the keyword already existed (not an error)


# New function
def recategorize_transaction(
    user_id: str,
    transaction_id: UUID,
    category_id: UUID,
    apply_forward_keyword: str | None = None,
) -> RecategorizationResult: ...
```

## Function specification

### `recategorize_transaction`

**Arguments:**

| Parameter | Type | Required | Semantics |
|---|---|---|---|
| `user_id` | `str` | Yes | Authenticated user's UUID string. Scopes every query. |
| `transaction_id` | `UUID` | Yes | The transaction to update. |
| `category_id` | `UUID` | Yes | The new category. Must belong to `user_id`. |
| `apply_forward_keyword` | `str \| None` | No | If non-None and non-empty after stripping, write this string as a keyword on `category_id` via Account Settings. Default: `None` (no keyword written). |

**Execution sequence:**

1. Verify `transaction_id` belongs to `user_id`. If not, raise `TransactionNotFound` (identical behavior to `get_transaction` — no existence leak).
2. Verify `category_id` belongs to `user_id` by querying `public.categories WHERE id = :cid AND user_id = :uid`. If not found, raise `CategoryNotFound`.
3. Update `public.transactions SET category_id = :new_cat WHERE id = :txn AND user_id = :uid` inside `engine.begin()`. This commit is unconditional once steps 1 and 2 pass.
4. Re-fetch the updated row via `get_transaction(user_id, transaction_id)` to construct the return value.
5. If `apply_forward_keyword` is non-None and non-empty after `strip()`:
   a. Call `account_settings.services.add_keyword(user_id, str(category_id), apply_forward_keyword)`.
   b. If `add_keyword` raises `ValueError` with a message matching "already exists", set `keyword_conflict = True`, `keyword_written = False`, and continue — this is not an error.
   c. If `add_keyword` raises any other exception, propagate it to the caller. The transaction row has already been updated; the caller must decide how to surface this to the user.
6. Return `RecategorizationResult(transaction=<updated>, keyword_written=<bool>, keyword_conflict=<bool>)`.

**Error model:**

| Condition | Behavior |
|---|---|
| `transaction_id` not found or belongs to another user | `TransactionNotFound` (same as `get_transaction`) |
| `category_id` does not belong to `user_id` | `CategoryNotFound` |
| `apply_forward_keyword` is empty after strip | Treated as `None`; no keyword write attempted. |
| Keyword already exists in the target category | `keyword_conflict = True`, `keyword_written = False`; no exception raised. |
| `apply_forward_keyword` write fails for any other reason | Exception propagates; transaction row is already committed. |
| Database connectivity failure | Propagates as the underlying exception. No wrapping. |

**Atomicity and partial failure:**

The transaction row update (step 3) and the keyword write (step 5) commit in separate database transactions through separate service boundaries. This is unavoidable given ADR-0003's constraint that each module owns its own connection scope. The sequence is deliberately ordered so that the primary user action (fix the transaction) always commits before the secondary action (write a rule). The partial-failure case — transaction updated, keyword write failed — is surfaced as a propagated exception so the caller can log it and show the user a degraded-success message rather than silently losing either action.

**Conflict-resolution rule for "apply forward" writes (mitigating the categorization feedback risk):**

When a user recategorizes a transaction and requests "apply forward," the keyword is written with `add_keyword`, which normalizes the keyword to uppercase before inserting. If the same keyword already exists on the category (`keyword_conflict = True`), the write is a no-op and the result is success. This is the "most-recent-wins" rule: the user's intent (this keyword belongs to this category) is already satisfied by the existing row, so no conflict exists in practice. Future smart-categorization writes (Phase 5) must route through the same `add_keyword` path and inherit the same normalization and dedup behavior. The provenance of the write (user vs. smart-categorization) is not stored in Phase 3b; if that distinction becomes important in Phase 5, a `source` column on `category_keywords` is the migration-time fix and does not require changing this interface.

## Tenant isolation

Steps 1 and 2 both include `user_id` in their WHERE clauses. The update in step 3 also includes `WHERE user_id = :uid` to prevent a race condition between the ownership check and the update. This is the same isolation guarantee as `get_transaction`.

## Consequences

- **Positive.** The Transaction Engine exposes a single documented entry point for recategorization. Route handlers, CLI tools, and future background jobs all call the same function and inherit the same conflict-resolution rule.
- **Positive.** `CategoryNotFound` is a distinct exception from `TransactionNotFound`, so the route handler can surface targeted error messages to the user.
- **Positive.** The "already exists" keyword case is a documented non-error — the user's intent is satisfied even if the keyword was already there from a prior session.
- **Negative.** The transaction row update and keyword write are not atomic. A failed keyword write after a committed transaction update leaves the user needing to retry only the rule — not the categorization. The route handler must surface this to the user rather than swallowing it.
- **Negative.** The Transaction Engine imports from Account Settings. This is a deliberate, narrow cross-module dependency through the service interface. A future reviewer agent should flag any attempt to access `public.categories` or `public.category_keywords` directly from within `app/transactions/`.
- **Follow-up.** ADR-0017 must be updated by addendum to reference this ADR as the source of the write surface. The module docstring in `app/transactions/services.py` must be updated to list `recategorize_transaction`, `RecategorizationResult`, and `CategoryNotFound` in the Public API section.
- **Follow-up.** The test-writer agent must exercise: (a) successful recategorize-only, (b) successful recategorize with keyword write, (c) recategorize with already-existing keyword, (d) `TransactionNotFound` on unknown transaction, (e) `CategoryNotFound` on category belonging to a different user.

## Notes

The `apply_forward_keyword` parameter is the description string from the transaction (or a user-edited version of it), not the full description — the route handler extracts the relevant keyword from the form. ADR-0018 does not prescribe how the keyword is derived from the description; that is a UI contract in ADR-0020. The service function accepts whatever string the caller provides and normalizes it through `add_keyword`'s existing normalization logic (strip + uppercase).

**Amendment — merchant alias always saved on recategorization (2026-05-18):** The original spec in step 5 only wrote a merchant alias when `apply_forward_keyword` was also being written. In practice this meant the alias table was only populated when the user explicitly checked "apply forward," leaving the Tier 2 alias shortcut unused for the majority of corrections. **Resolution:** `add_merchant_alias` is now called unconditionally whenever `category_id is not None`, before the keyword branch. The alias write uses `ON CONFLICT DO NOTHING`, so re-categorizing the same merchant to the same category is a safe no-op. The keyword write path (step 5b onward) is unchanged. The risk that a mistaken correction writes a wrong alias applies equally to the keyword write; always-saving increases the frequency marginally but does not introduce a new failure mode, and the UX improvement — Tier 2 matching after the first correction — is significant.
