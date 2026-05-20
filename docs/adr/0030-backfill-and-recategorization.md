# ADR 0030 - Backfill and Re-categorization on Categorizer Upgrade

- **Status:** Accepted
- **Date:** 2026-05-18
- **Phase:** P5b
- **Deciders:** Architect agent

## Context

ADR-0028 upgrades the categorizer from a single keyword scan (`make_categorizer_v1`) to a five-tier pipeline (`make_categorizer_v2`). Transactions uploaded before this upgrade retain their stored `category_id`, which may be `NULL` if v1 returned "Slush Fund" (now "Uncategorized"). A question arises: should the system automatically re-run categorization on existing transactions when the upgraded categorizer deploys, and if so, under what scope and trigger?

Two binding constraints:

- **ADR-0018** (recategorize write API): `recategorize_transaction` is the only sanctioned write path for changing a stored `category_id`. Any backfill operation must use this function or replicate its ownership checks and conflict-resolution rules. Bypassing it is a bug, not a shortcut.
- **CLAUDE.md Phase 5 narrowed charter**: background jobs are explicitly out of scope for Phase 5. The hosting decision for background job execution has not been resolved; any feature that requires a background job cannot ship until it is.

Relevant risk: "Automatic re-categorization silently overwrites user corrections" — if a user has manually corrected a transaction, automatic backfill on deploy must never touch it. `NULL` `category_id` rows are the only safe target for unsupervised re-categorization.

## Options considered

### Option A - Automatic backfill on every deploy

On startup (or via a migration hook), re-run the categorizer against all `NULL`-category transactions for every user. No user action required.

**Pros.** Users see improved categorization without doing anything.

**Cons.** Silently changes stored data on deploy. A transaction the user accepted as "Uncategorized" (e.g., a one-off charge they chose not to categorize) would be categorized without consent. The categorizer may make a wrong guess that the user now has to find and correct. On large datasets, startup backfill blocks the deploy or causes a long-running migration. Background job execution is out of scope for Phase 5.

### Option B - Never backfill; only new uploads benefit from v2

Old `NULL`-category transactions remain `NULL` indefinitely. Users who want better categorization must re-upload the same file.

**Pros.** No risk of silent overwrites. Zero implementation complexity beyond the upload path.

**Cons.** Users with months of uncategorized history see no benefit from the upgrade unless they re-upload. Re-uploading is blocked by the idempotency layer (ADR-0013) for already-seen transactions, so this option is not even practically available without special handling. Leaves historical data permanently in a degraded state.

### Option C - On-demand backfill triggered by the user

A "Re-categorize all uncategorized transactions" action on the Account Settings page. Scope is restricted to transactions where `category_id IS NULL`. Manually-categorized transactions (where `category_id IS NOT NULL`, whether set at upload time or via the edit flow) are never touched.

**Pros.** User controls the timing and consents to the operation. Manually-corrected transactions are never overwritten. Idempotent: a second run skips already-categorized rows. Safe to retry after partial failure.

**Cons.** Users must discover and trigger the action. Progress feedback is limited for large datasets given the synchronous constraint.

## Decision

We will choose **Option C — on-demand backfill triggered by the user** because automatic backfill silently overwrites data the user may have deliberately left uncategorized, and "never" leaves historical data in a permanently degraded state with no recovery path. On-demand is the only option that respects user intent and is reversible.

## Route specification

```
POST /settings/categories/backfill
```

- Auth-gated: requires an active session (`user_id` in session). Redirect to login if not authenticated.
- CSRF-protected: standard Flask-WTF token required on the POST body.
- Blueprint: `account_settings` blueprint (route lives in `app/account_settings/routes.py`).

## UI trigger

A button labeled "Re-categorize uncategorized transactions" on the Account Settings → Categories page. The button is shown only when the user has at least one transaction with `category_id IS NULL`. It submits a form to `POST /settings/categories/backfill`.

On completion, redirect to the same page with a flash message stating how many transactions were updated.

## Execution model

The route runs synchronously. Background jobs are out of scope for Phase 5 (CLAUDE.md constraint). For typical user datasets (< 5,000 uncategorized transactions) synchronous execution completes within a request timeout.

If the user has more than 5,000 uncategorized transactions, the route processes them in pages of 500. After each page, it commits and increments a running count. After the last page, it redirects with a flash showing the total updated count. No partial-page rollback on crash (see atomicity below).

The threshold of 5,000 is not a hard limit on the total backfill; it governs page size only. All qualifying transactions are processed in a single request across as many 500-row pages as needed.

## Scope

The backfill query:

```sql
SELECT id FROM public.transactions
WHERE user_id = :user_id
  AND category_id IS NULL
ORDER BY date DESC
```

Only rows where `category_id IS NULL` are candidates. Rows where `category_id IS NOT NULL` (whether set at upload, by the user manually, or by a previous backfill run) are skipped without exception. This is a hard invariant: the backfill route must never update a non-NULL `category_id`.

## Categorizer invocation

The backfill route builds `make_categorizer_v2` using the same pre-load contract as the upload route (ADR-0028): keywords, aliases, and past transactions are loaded once before the loop, not per transaction. The categorizer closure is called per row. If the result is `"Uncategorized"`, the row is skipped (no write performed). Only rows receiving a non-"Uncategorized" result are updated.

Updates use `recategorize_transaction` from `app/transactions/services.py` with `apply_forward_keyword=None` (no keyword write; the backfill is not a user correction). This ensures ownership checks and audit consistency are inherited from the existing write API.

## Atomicity

Each transaction update is committed individually by `recategorize_transaction`. If the route crashes mid-backfill, already-updated rows remain updated and the user can run backfill again safely. A second run skips rows that now have a non-NULL `category_id` (already updated by the first run). This is intentional idempotency, not an error.

Cross-page atomicity is not provided. There is no rollback of partially-completed backfills. This is acceptable because:

1. Every individual update is an improvement (NULL → a category); there is no valid "undo the whole run" need.
2. The user can retrigger the operation at any time.

## Relationship to the test harness

The test harness (ADR-0028) measures categorizer accuracy on a static labeled fixture set. Backfill accuracy on a given user's real data is a distinct measurement and is not tracked by the harness. The harness result is the basis for deciding whether to invest in Tier 6 (embeddings); the backfill volume is not that basis.

## What does not change

Transactions categorized at upload time (by v1 or v2) keep their stored `category_id` unless the user explicitly triggers backfill (scope: `NULL` only) or manually recategorizes via the edit flow (scope: one transaction at a time, any `category_id`). No automated process changes a stored `category_id` after this ADR is accepted.

## Consequences

- **Positive.** User explicitly consents to backfill; no silent overwrites of accepted state.
- **Positive.** Idempotent: safe to run multiple times. A crash mid-run leaves the dataset in a better state than before, never in a worse one.
- **Positive.** `recategorize_transaction` reuse ensures ownership checks are never bypassed.
- **Negative.** Users must discover and trigger the action. Large uncategorized datasets are processed synchronously, which is acceptable for Phase 5 but may need a background job in a later phase.
- **Negative.** No per-transaction undo for the backfill run. Users who want to reverse a specific auto-categorization must use the existing manual recategorize flow.
- **Follow-up required.** The "Re-categorize uncategorized transactions" button must be conditionally shown only when qualifying rows exist. The route handler must run the scope query to determine count before rendering the page.
- **Follow-up required.** If a future phase introduces background jobs, this backfill route is the natural candidate for migration to an async task. A new ADR would govern that change; this ADR's on-demand trigger and scope invariant remain authoritative until superseded.

## Notes

The 5,000-row threshold and 500-row page size are starting points based on a conservative estimate of Flask's default request timeout. If empirical testing reveals that the synchronous model is too slow for a realistic user dataset size, the implementation agent should report this before shipping, not after. The architect should be consulted before raising the threshold beyond what fits in a single request.

**Amendment — additional backfill CTA surfaces (2026-05-19):** The original spec placed the backfill button only on the Account Settings → Categories page, which required users to navigate away from their transactions to find it. Two additional surfaces are added; both submit to the same `POST /account-settings/categories/backfill` route and are conditionally rendered only when `uncategorized_count > 0`:

1. **Intelligence report page** (`GET /intelligence/report`): a yellow banner appears immediately below the page header when the report loads with uncategorized transactions. It offers "Auto-categorize now" (form POST) and "Review manually" (link to the uncategorized-only history filter). This is the natural discovery moment — the user has just uploaded a file and is looking at their report.
2. **Transaction history page** (`GET /transactions`) when filtered to uncategorized-only: a yellow banner appears above the results table offering "Auto-categorize now." This is the natural action surface when the user is already looking at uncategorized rows.

The Categories page button is unchanged. The `uncategorized_count` value is fetched by each route handler (`count_uncategorized_transactions(user_id)`) and passed to the template; no change to the backfill route itself.
