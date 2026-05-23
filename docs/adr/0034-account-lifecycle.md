# ADR 0034 - Accounts as Transaction Groups — Grouping, Dedup Scope, and Lifecycle

- **Status:** Accepted
- **Date:** 2026-05-23
- **Phase:** P5c
- **Deciders:** erin, architect agent

## Context

Phase 5c ships the account management UI. Before implementation starts, the underlying mental model must be pinned, because the original framing — modelling real-world financial accounts with archive/lifecycle semantics — was pulling the implementation toward complexity that doesn't belong in a reporting tool.

The reframing: what the app calls an "account" is better understood as a **transaction set** — a named bucket that a user assigns uploads to. Dedup runs within a set (the fingerprint tuple in ADR-0013 already includes `account_id` for exactly this reason). Reporting can filter to one set, several, or all combined. Users will name sets after their real financial accounts by convention ("TD Chequing", "Visa"), but the app does not need to model what a financial account *is* — only that transactions belong to a named group.

This framing resolves the archive problem: you don't archive a set, you either use it or delete it. If you cancelled a credit card, you stop uploading to that set. Its transactions stay in your history and remain visible in reports. There is no hidden state to manage.

[ADR-0014](0014-multi-account-per-user.md) established the `public.accounts` table and deferred lifecycle semantics to this phase. This ADR supersedes ADR-0014's `is_active`, `kind`, and `currency` columns and replaces the lifecycle model entirely. The table name `public.accounts` is retained internally for FK compatibility; user-facing language uses "account." Internally the concept is a logical grouping or set, but "account" is the term users will recognise and expect. Relevant risks: "Schema design locks in early mistakes" ([risks.md](../risks.md)).

## Options considered

### Option A - Retain financial account framing with archive semantics

Model sets as real-world financial accounts. Add `archived_at` to represent closed accounts. Hide archived-account transactions by default with a toggle on reports, budgets, and transaction history.

**Pros:** Familiar pattern from personal finance tools (YNAB, Monarch).

**Cons:** Archive is a third lifecycle state that sits between "active" and "deleted" and requires toggle UI on three separate surfaces. It attempts to replicate financial account lifecycle in a tool whose job is to aggregate and report on uploaded CSVs. The complexity is not earned by the use case.

### Option B - Sets with no archive; rename and delete only (chosen)

A set is a named grouping. The only lifecycle operations are rename and delete. Deleted sets cascade-remove their transactions. There is no archive state. Reports filter by set as a first-class concept — the user chooses which sets to include in any given view.

**Pros:** Honest about what the tool does. Eliminates archive state, visibility toggles, and the `archived_at` migration. Dedup scope (per-set) and reporting scope (filter by set) are the same concept expressed in two places. Simpler UI, simpler service layer, simpler schema.

**Cons:** A user who wants to "put away" an old set without deleting it has no dedicated UI affordance — they just stop uploading to it and filter it out in reports if needed. This is acceptable: the data is never hidden by default, so nothing is lost.

### Option C - Sets with soft-delete tombstone

Add a `deleted_at` column. Deleted sets become invisible but their data is retained for a grace period.

**Cons:** Directly contradicts ADR-0015's decision to reject soft-delete tombstones. Adds the same "hidden state" complexity as archive without the reversibility benefit. Rejected.

---

### Upload assignment — Option 1: Always prompt on upload

The upload form always shows a "which set?" dropdown. If only one set exists, it is pre-selected and requires no action. If multiple sets exist, the user picks before submitting.

**Pros:** Explicit. The user always knows which set an upload is going into. No silent assignment. Composes naturally with multiple sets.

**Cons:** Adds a required field to the upload form. For a user with one set, the dropdown is visual noise (though pre-selected, so zero extra clicks).

### Upload assignment — Option 2: Auto-assign to default, reassign after

Uploads silently go to the Default set. The user can later reassign transactions to a different set.

**Cons:** Reassigning transactions after the fact is a bulk-edit operation that doesn't exist in the current service layer. Silent assignment trains users to ignore set selection. Rejected.

### Upload assignment — Option 3: Conditional — prompt only when multiple sets exist

If the user has one set, auto-assign silently. If multiple sets exist, show the dropdown.

**Cons:** Conditional UI is harder to reason about. A user who adds a second set will suddenly see a new required field on a form they've used for months. Surprising behaviour is worse than consistent behaviour. Rejected.

## Decision

We will choose **Option B (sets with rename and delete only)** and **Upload Assignment Option 1 (always prompt)**.

**Schema.** The `public.accounts` table is simplified. The `is_active`, `kind`, and `currency` columns are dropped via migration. The retained shape is:

| Column | Type | Constraints |
|---|---|---|
| id | UUID | PRIMARY KEY DEFAULT gen_random_uuid() |
| user_id | UUID | NOT NULL, FK → auth.users(id) ON DELETE CASCADE |
| name | TEXT | NOT NULL |
| created_at | TIMESTAMPTZ | NOT NULL DEFAULT now() |

The `UNIQUE (user_id, name)` constraint from ADR-0014 is retained. Maximum name length: 100 characters, enforced at the service layer.

**Lifecycle operations.**

- *Create* — users can create a new named set from the settings UI. `get_or_create_default_account` (ADR-0014) continues to auto-create a "Default" set on first upload if none exists; the name "Default" is a starting point the user can rename.
- *Rename* — safe update to `accounts.name`. No effect on transactions, fingerprints, or FKs.
- *Delete* — `DELETE FROM public.accounts WHERE id = :id AND user_id = :uid`. The `ON DELETE CASCADE` on `transactions.account_id` and `uploads.account_id` (ADR-0014, ADR-0015) purges all associated transactions and uploads atomically. The UI shows a confirmation dialog: "Delete this set? This will permanently delete N transactions and cannot be undone." No archive, no grace period; consistent with ADR-0015's hard-cascade philosophy.

**Last-set guard.** Deleting the last set is permitted. `get_or_create_default_account` auto-creates a Default set on next upload. The confirmation dialog for a last-set delete includes: "This is your only set. Deleting it will remove all your transactions. A new default set will be created on your next upload."

**Upload assignment.** The upload form renders a "Set" dropdown populated from the user's sets. A single set is pre-selected with no extra clicks required. Multiple sets require an explicit selection. The selected set id is passed to `_process_upload` alongside `user_id`, `filename`, `file_bytes`, and `df`. The `get_or_create_default_account` fallback remains as a safety net for the programmatic upload path only.

**Reporting filter.** The Intelligence report, budget progress view, and transaction history each accept a `set_id` query parameter (optional). When absent, all sets are combined (current default behaviour). When present, results are scoped to that set. This replaces the `include_archived` toggle concept entirely. The existing `account_id` parameter on `get_spend_by_category` and `get_spend_history` (ADR-0023) already supports this — no API change needed, only the parameter name exposed in the URL and UI.

## Consequences

- Positive: Archive state is eliminated entirely. No visibility toggles, no `archived_at` migration, no hidden data to reason about.
- Positive: "Which set?" on upload is explicit and consistent regardless of how many sets the user has.
- Positive: The reporting filter (scope to one set vs. combine all) is a natural consequence of the set model and requires no new service layer work — the `account_id` filter already exists.
- Positive: Schema is simpler than ADR-0014 proposed: three columns dropped, no new columns added.
- Negative: A user who wants to "hide" an old set without deleting it has no dedicated affordance. They can simply stop uploading to it; it remains visible in reports unless they filter it out. This is a deliberate trade-off.
- Negative: The upload form now has a required "Set" field. For single-set users this is invisible (pre-selected), but it is a change to the upload UX.
- Follow-ups required: (1) Alembic migration dropping `is_active`, `kind`, and `currency` from `public.accounts`. (2) Update `get_or_create_default_account` to remove the `is_active` filter. (3) Update the upload route to pass `account_id` from the form rather than calling `get_or_create_default_account` on every upload. (4) Update the Intelligence report, budget progress, and transaction history routes to accept and propagate `set_id`. (5) Update ADR-0014 notes to reflect this supersession of `is_active`, `kind`, and `currency`.

## Notes

The internal table name `public.accounts` is retained to avoid a rename migration with cascading FK updates. User-facing surfaces (UI labels, flash messages, documentation) use "account" throughout. The internal mental model is a logical grouping; the user-facing word is "account" because that is what users expect to see in a finance tool.

ADR-0015's hard-cascade deletion model applies unchanged. The transitive cascade `accounts(id) → transactions ON DELETE CASCADE` was defined there and is reused here without modification.
