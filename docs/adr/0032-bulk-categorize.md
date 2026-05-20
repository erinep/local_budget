# ADR 0032 - Bulk Categorization on Transaction History

- **Status:** Accepted
- **Date:** 2026-05-20
- **Phase:** P5c
- **Deciders:** erin

## Context

Single-edit (ADR-0020) requires one full navigation per transaction. A user who imports a new merchant for the first time may have dozens of uncategorized transactions from that merchant. Fixing them one at a time is the primary remaining friction in the categorization flow. The transaction history view already has filtering and pagination; bulk categorization should compose naturally with those filters.

## Options considered

### Option A - Checkbox selection with sticky action bar

Each history row gets a leading checkbox. A select-all checkbox lives in the table header. An action bar sits between the filter card and the table, sticky at the top of the viewport as the user scrolls. The bar is hidden until at least one checkbox is checked (shown via a small JS snippet). Bar contents: selection count, category dropdown, Apply button, Deselect all.

The table is wrapped in a scrollable container (`overflow-y: auto; height: calc(100vh - offset); min-height: 300px`) so the page does not grow unboundedly on large transaction lists.

Checkboxes carry the HTML `form` attribute pointing to the action bar form, so they submit with the action bar without JS mirroring or wrapping the whole table in a single form.

**Pros.** Familiar pattern (Gmail, Notion, Linear). Composes with existing filters. Plain HTML form submission works without JS — JS only handles show/hide and the indeterminate select-all state.

**Cons.** Selection is scoped to the current page only (up to 50 rows). Cross-page "select all N matching" is not supported in v1.

### Option B - Filter-based bulk apply (no checkboxes)

A single "Apply category to all matching" button appears in the filter card. It applies the chosen category to all transactions matching the current filter, with no row-level selection.

**Pros.** No checkbox UI. Works entirely without JavaScript.

**Cons.** All-or-nothing within a filter set. User cannot pick a subset of filtered results. Less familiar pattern.

### Option C - Dedicated bulk edit page

History rows have checkboxes; an "Edit selected" button navigates to a separate page showing selected transactions with a shared category dropdown.

**Pros.** Full page for confirmation.

**Cons.** Selection state must survive a page transition. Extra navigation cost.

## Decision

We will choose **Option A** — checkbox column with a sticky action bar and scrollable table.

The form attribute approach makes the submission work without JS, and the sticky bar pattern is well understood. Option B's all-or-nothing scope is a meaningful product limitation. Option C's extra navigation defeats the purpose.

Selection is scoped to the current page (v1). Cross-page "select all N matching" is deferred.

## Route and service contracts

### `POST /transactions/bulk-categorize`

Registered on `transactions_bp`. Auth-gated. CSRF-protected.

Form fields: `transaction_ids[]` (list of UUID strings), `category_id` (UUID string).

Handler validates category ownership, calls `bulk_categorize_transactions`, flashes result, redirects to `/transactions?uncategorized=1`.

Flash format: `"N transaction(s) categorized. M merchant alias(es) written. Visit Account Settings to review aliases."`

### `bulk_categorize_transactions(user_id, transaction_ids, category_id)`

Added to `app/transactions/services.py`. Validates category ownership, fetches descriptions, runs per-row UPDATE inside a single `engine.begin()` transaction, writes merchant aliases via `normalize_description` with `ON CONFLICT DO NOTHING`. Returns `BulkCategorizationResult(updated_count, alias_count)`. Raises `CategoryNotFound` if category does not belong to user.

## Consequences

- Positive: Users can fix a batch of same-merchant transactions in two clicks.
- Positive: `bulk_categorize_transactions` consolidates batch UPDATE logic currently duplicated in the backfill route.
- Negative: JS is load-bearing for the action bar show/hide and selection count. Without JS the bar is always visible and the count label is absent; the form still submits correctly.
- Negative: Scrollable table container may appear partially empty on short transaction lists. `min-height: 300px` mitigates collapse.
- Follow-ups required: Cross-page "select all N matching" (deferred). Refactor `categories_backfill` to call `bulk_categorize_transactions`.

## Notes

Merchant aliases are written silently for every selected transaction, consistent with single-edit and backfill behavior. The success flash directs users to Account Settings (plain text, v1) to review aliases via ADR-0031.
