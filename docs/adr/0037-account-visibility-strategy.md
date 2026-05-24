# ADR 0037 - Account Visibility Strategy

- **Status:** Accepted
- **Date:** 2026-05-23
- **Phase:** P5c
- **Deciders:** erin p

## Context

Users may have multiple accounts (ADR-0014) — e.g., a chequing account they use daily and a closed or dormant account they no longer want mixed into reports. There is currently no way to exclude an account from reporting without deleting it and losing its transaction history. The `accounts` table previously carried an `is_active` column that was dropped in the Phase 5c simplification migration (ADR-0034) before its reporting role was defined. This ADR re-introduces the column with a precise contract.

## Options considered

### Option A - `is_active` flag on the account, enforced by the Transaction Engine

Add `is_active BOOLEAN NOT NULL DEFAULT TRUE` to `public.accounts`. Every Transaction Engine read function that feeds reporting — `get_spend_by_category`, `get_spend_history`, `get_transactions`, `get_uploads` — filters to accounts where `is_active = TRUE` unless explicitly overridden. The UI toggle lives on the Accounts settings page. The flag is a property of the account itself, not of a particular view or session.

Pros: single enforcement point; consumers (Budget, Intelligence) get the filter for free; non-destructive (data is preserved); easy to reason about.
Cons: re-adds a column we just removed; "inactive" excludes historical transactions which may surprise users.

### Option B - Per-report account selector (session-scoped filter)

Let the user pick which accounts to include each time they load a report — stored as a query parameter or session variable, not persisted on the account row.

Pros: more flexible; doesn't touch history.
Cons: every report page needs its own filter UI; no persistent preference; no clear owner in the module hierarchy; significantly more implementation work.

### Option C - User-level `active_accounts` array

Add a `active_accounts UUID[]` column to the user profile. Transaction Engine reads this list and filters accordingly. Report pages can override it per-session.

Pros: user can select an arbitrary subset without changing account records.
Cons: complex to maintain (must clean up on account deletion); premature for current needs; array FK semantics are awkward in PostgreSQL.

## Decision

We will implement **Option A**. `is_active` on the account row is the right scope for the current problem: a user has an account they want to stop seeing across the app, and that preference should persist without per-session configuration.

The Transaction Engine enforces the filter internally. No consumer needs to pass an account filter; the default read path is always scoped to active accounts. The one exception is the Accounts settings page, which must show all accounts (active and inactive) so the user can toggle them.

### Extensibility contract

Option C is not ruled out — it is the natural upgrade path. To keep the door open, Transaction Engine read functions are written to accept an optional `account_ids: list[str] | None = None` parameter. When `None` (the default today), the function filters by `is_active = TRUE`. When a list is provided (future), it uses that list instead. This means the future upgrade is additive: pass a list derived from `users.active_accounts`, and the filter behaviour changes without rewriting the function body.

## Consequences

- Positive: users can exclude stale accounts from all reports with one toggle; no data is lost; Budget and Intelligence modules require no changes.
- Negative: re-introduces a column dropped in `0009_simplify_accounts.py`; requires a new migration; existing integration test fixtures must insert `is_active` or rely on the default.
- Follow-ups required:
  - Migration `0010_account_is_active.py`: add `is_active BOOLEAN NOT NULL DEFAULT TRUE` to `public.accounts`.
  - Update all Transaction Engine read functions to filter `is_active = TRUE` (via JOIN or subquery) and accept the optional `account_ids` override parameter.
  - Add toggle UI to `/settings/accounts`.
  - Update ADR-0034 to note that `is_active` was deferred, not permanently removed.

## Notes

The previous `is_active` column (dropped in the Phase 5c migration) had no defined contract — it was schema artefact from an earlier design. This ADR gives it a precise meaning: "include this account's transactions in all reporting and aggregation reads." It does not mean the account is open at the bank; it is purely an in-app visibility flag.
