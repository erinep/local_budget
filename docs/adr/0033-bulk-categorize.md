---
adr: 0033
title: Bulk Categorization — Selection UI, Action Bar, Route Contract
status: Draft
date: 2026-05-20
phase: P5c
deciders: erin
---

## Context

Single-edit (ADR-0020, overhauled per ADR-0032) requires one full navigation per transaction. A user who imports a new merchant for the first time — say a gym or grocery chain — may have dozens of uncategorized transactions from that merchant. Fixing them one at a time is the primary remaining friction in the categorization flow.

This ADR pins the design for page-level bulk categorization on the transaction history view.

## Decisions

### Selection model

Checkboxes on each row, plus a select-all checkbox in the table header. Selection is scoped to the current page only (up to 50 rows). Cross-page "select all N matching" is deferred to a later iteration.

The select-all checkbox in the header checks/unchecks all row checkboxes on the current page. It uses an indeterminate state when some but not all rows are checked.

No JavaScript is required for the checkbox mechanics themselves. The form submission works as plain HTML. JavaScript is used only for the action bar show/hide and the select-all indeterminate state.

### Action bar

A bar is hidden by default and appears when at least one checkbox is checked. It sits between the filter card and the table, sticky within the page using `position: sticky; top: <nav-height>` so it adheres to the top of the viewport as the user scrolls.

Bar contents (left to right):

- Selection count: "N selected"
- Category dropdown: populated from the user's categories, default "Select category"
- Apply button: disabled when no category is selected
- Deselect all: clears all checkboxes and hides the bar

The bar is shown/hidden by a small inline JS snippet listening to checkbox change events. Without JavaScript, the bar is always visible but the count label is absent.

### Table layout

The transaction table is wrapped in a scrollable container with `height: calc(100vh - var(--bulk-offset))` where `--bulk-offset` accounts for the nav bar, filter card, and action bar. This keeps the full page height used without magic pixel values. The table header row is sticky within the scroll container.

### Merchant aliases

Aliases are written silently for every selected transaction (same behavior as single-edit and backfill). The success flash message names the count of aliases written and links to the Aliases management page (ADR-0031):

> "12 transactions categorized. 5 merchant aliases written. Review aliases."

### Redirect after success

After a successful bulk categorize, redirect to the transaction history filtered to uncategorized-only (`/transactions?uncategorized=1`), so the user can continue working through remaining uncategorized transactions.

## Route contract

### `POST /transactions/bulk-categorize`

Registered on `transactions_bp`. Auth-gated. CSRF-protected.

**Form fields:**

| Field | Type | Notes |
|---|---|---|
| `transaction_ids` | list of UUID strings | One entry per checked row. Required; at least one. |
| `category_id` | UUID string | Required. |

**Handler behavior:**

1. Parse `category_id` from form. If absent or not a valid UUID, flash error and redirect back (no HTTP 400 — this is a form submission).
2. Parse `transaction_ids[]` from form. Filter to valid UUIDs; silently drop malformed values. If none remain, flash error and redirect back.
3. Call `bulk_categorize_transactions(user_id, transaction_ids, category_id)`.
4. On `CategoryNotFound`: flash error "Category not found." and redirect back.
5. On success: flash success message with counts, redirect to `/transactions?uncategorized=1`.

**Flash message format:**

> "N transaction(s) categorized. M merchant alias(es) written. Visit Account Settings to review aliases."

Plain text only. Linking within flash messages is not supported in v1.

### `GET /transactions/bulk-categorize`

Not registered. A GET to this URL should 405 or fall through to Flask's default 405 handling.

## Service contract

### `bulk_categorize_transactions(user_id, transaction_ids, category_id)`

Added to `app/transactions/services.py`.

```python
from dataclasses import dataclass

@dataclass
class BulkCategorizationResult:
    updated_count: int
    alias_count: int


def bulk_categorize_transactions(
    user_id: str,
    transaction_ids: list,   # list[uuid.UUID]
    category_id: uuid.UUID,
) -> BulkCategorizationResult:
    """Categorize a list of transactions in a single DB transaction.

    Only touches transactions where user_id matches (ownership enforced in WHERE).
    Writes merchant aliases via normalize_description for each updated transaction.
    Uses per-row UPDATE inside engine.begin() — same pattern as backfill route.

    Raises:
        CategoryNotFound: if category_id does not exist for this user.
    """
```

**Implementation notes:**

- Validate `category_id` ownership before touching transactions (one SELECT on `public.categories WHERE id = :cat_id AND user_id = :uid`). Raise `CategoryNotFound` if not found.
- Fetch descriptions for the selected transaction IDs in one SELECT (needed for alias generation).
- Run per-row UPDATE inside a single `engine.begin()` transaction. Each UPDATE includes `AND user_id = :uid` to enforce ownership — a user cannot categorize another user's transactions by guessing IDs.
- Run batch alias INSERT with `ON CONFLICT (category_id, normalized_name) DO NOTHING` for each updated transaction.
- Return `BulkCategorizationResult(updated_count, alias_count)`.

The function lives in `app/transactions/services.py` to respect ADR-0003 module boundaries (the Transaction Engine owns transaction writes). The backfill route in `app/account_settings/routes.py` currently duplicates this logic inline; once this service function exists, the backfill route should be refactored to call it.

## Template changes — `transactions/history.html`

### Checkbox column

Add a leading `<th>` with the select-all checkbox and a leading `<td>` with a per-row checkbox to each row.

```html
<!-- Header -->
<th style="width: 40px;">
    <input type="checkbox" id="select-all" aria-label="Select all on this page">
</th>

<!-- Each row -->
<td>
    <input type="checkbox" name="transaction_ids" value="{{ txn.id }}"
           class="row-check" form="bulk-form">
</td>
```

### Bulk action bar

Inserted between the filter card and the results card. Hidden by default via `display: none`; shown by JS when any row checkbox is checked.

```html
<form id="bulk-form" method="post" action="{{ url_for('transactions.bulk_categorize') }}" style="display: none;">
    <input type="hidden" name="csrf_token" value="{{ csrf_token() }}">
    <div style="/* sticky bar styles */">
        <span id="bulk-count">0 selected</span>
        <select name="category_id" id="bulk-category">
            <option value="">Select category</option>
            {% for cat in categories %}
            <option value="{{ cat.id }}">{{ cat.name }}</option>
            {% endfor %}
        </select>
        <button type="submit" id="bulk-apply" disabled>Apply</button>
        <button type="button" id="bulk-deselect">Deselect all</button>
    </div>
</form>
```

Each checkbox carries `form="bulk-form"`, associating it with the action bar form via the standard HTML `form` attribute. The checkboxes can sit anywhere in the DOM and will be included in the bulk form submission without any JavaScript. No JS mirroring needed.

### Scrollable table container

Wrap the existing `<div class="table-wrap">` in:

```html
<div style="overflow-y: auto; min-height: 300px; height: calc(100vh - var(--bulk-offset, 320px));">
    <!-- existing table-wrap and table -->
</div>
```

`--bulk-offset` is a CSS custom property set on `:root` or inline, accounting for nav height + filter card height + action bar height. `min-height: 300px` ensures the container does not collapse to near-empty on short transaction lists. Implementation agent should measure actual rendered heights and set a reasonable default for `--bulk-offset`.

### JS behavior

A single `<script>` block at the bottom of the template (or in `{% block scripts %}`):

- Listen to `change` on `.row-check` checkboxes: update count label, toggle Apply disabled state, show/hide bulk form, update select-all indeterminate state.
- Listen to `change` on `#select-all`: check/uncheck all `.row-check` checkboxes, trigger the above.
- Listen to `click` on `#bulk-deselect`: uncheck all, hide bar.
- On bulk form submit: copy checked transaction IDs into `#bulk-id-inputs` as hidden inputs.

No external libraries. Plain DOM APIs only.

## Module boundary check

`bulk_categorize_transactions` in `app/transactions/services.py` reads and writes `public.transactions` and `public.merchant_aliases`. Writing to `public.merchant_aliases` is currently done by `recategorize_transaction` (also in transactions services) and by the backfill route (inline, to be refactored). Writing aliases from the transaction service is acceptable because aliases are a direct consequence of categorization — they are not Account Settings data in the user-facing sense, even though they live in that schema. ADR-0003 is not violated as long as the write goes through the service layer.

If this feels like a boundary stretch, the alternative is a new service function in `app/account_settings/services.py` that accepts a list of `(normalized_name, category_id)` pairs. The transaction service calls it. Either is acceptable; implementation agent decides.

## What is deferred

- Cross-page "select all N matching" via `select_all=1` server-side shortcut.
- Linking within flash messages (the alias review link in the success flash).
- Bulk delete.
- Animated bar transition (slide-in vs instant show).

## Consequences

- **Positive.** Users can fix a batch of same-merchant transactions in two clicks: check all, pick category, apply.
- **Positive.** The service function `bulk_categorize_transactions` also cleans up the inline SQL in the backfill route.
- **Negative.** JavaScript is now load-bearing for the action bar. Without JS, the bar is visible but the selection count and select-all indeterminate state do not work. The form still submits correctly — only the UX polish degrades.
- **Negative.** The scrollable table container changes the visual weight of the history page. `min-height: 300px` prevents collapse on short lists but the container will still appear partially empty.
- **Follow-up.** Once `bulk_categorize_transactions` exists, refactor `categories_backfill` in `app/account_settings/routes.py` to call it instead of duplicating the batch UPDATE and alias INSERT logic inline.
