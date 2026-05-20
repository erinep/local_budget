---
adr: 0020
title: Recategorize UI Flow — Edit Page, Apply-Forward Checkbox, Redirect
status: Accepted
date: 2026-05-18
phase: P3b
deciders: erin
---

## Context

Phase 3b lets a user correct a miscategorized transaction. The write API is pinned in ADR-0018 (`recategorize_transaction`). The history view route is pinned in ADR-0019 (`GET /transactions`). This ADR pins three remaining UI decisions: how the user triggers recategorization, what the "apply this rule going forward" option looks like, and where the user lands after submitting.

Governing constraints:

- **ADR-0003** (service-layer-only): the route handler calls `recategorize_transaction` from `app/transactions/services`; it never touches `public.transactions` or `public.category_keywords` directly.
- **ADR-0018** (write API): `recategorize_transaction(user_id, transaction_id, category_id, apply_forward_keyword=None)` — the keyword to write forward is a string passed by the caller, not derived inside the service.
- **ADR-0004** (blueprint layout): the edit route lives in `transactions_bp` under `app/transactions/routes.py`.
- **CLAUDE.md** constraint: no JavaScript is required by the nav contract (ADR-0011). The recategorize flow must function without JavaScript.

## Options considered

### Option A — Inline edit on the history row

Each history row has a category `<select>` and a Submit button rendered directly in the table. The user changes the dropdown and clicks Submit without leaving the history view. An optional "apply forward" checkbox is also in the row.

**Pros.** Zero navigation cost — the user stays on the history view. Fast for users correcting many transactions in sequence.

**Cons.** A table with 50 rows each containing a `<select>`, a checkbox, a keyword input, and a Submit button is visually dense, and each row-level form submission requires its own `<form>` tag wrapping a table row — which is invalid HTML (a `<form>` cannot be a child of `<tr>`). The "apply forward" UX also needs a keyword input (which keyword should trigger this category?), making the row even wider. No JavaScript means no progressive disclosure; all controls must render at once. This layout is impractical without JS-enabled hiding.

### Option B — Dedicated edit page per transaction

The history row has an "Edit" link (or button) that navigates to `GET /transactions/<id>/edit`. That page shows the transaction details (date, description, amount, current category) and an edit form with: a category `<select>`, an "apply this rule going forward" checkbox, and a keyword input that appears below the checkbox (present in the HTML always, styled visible only when checkbox is checked — or simply always visible and ignored server-side if the checkbox is unchecked). Submitting the form sends `POST /transactions/<id>/edit` and redirects back to the history view with a success flash message.

**Pros.** Clean HTML — one `<form>` per page, no table-row wrapping hack. Room to show the full transaction context. "Apply forward" keyword input fits naturally. Works with and without JavaScript. Edit page is independently linkable (shareable URL, bookmarkable).

**Cons.** Two-step flow for every correction: click Edit, fill form, submit, return to history. Users fixing many transactions in sequence pay two navigations each. Acceptable for Phase 3b; batch editing is a future enhancement.

### Option C — Modal dialog over the history view

A modal triggered by "Edit" on the history row. The modal contains the same form as Option B. Submitting the form closes the modal and refreshes the row (or the full page).

**Pros.** Single-page feel. No navigation cost.

**Cons.** Requires JavaScript for both modal display and the dynamic "show keyword input when checkbox is checked" behavior. CLAUDE.md and ADR-0011 avoid JS as a requirement. A no-JS fallback that reverts to the full-page edit route is feasible but doubles the implementation surface. Not worth the complexity for Phase 3b.

## Decision

We will choose **Option B** — a dedicated edit page at `GET/POST /transactions/<id>/edit`.

The two reasons that carried the decision: (1) it produces valid HTML without any JavaScript dependency, and the "apply forward" keyword input fits naturally alongside the category select on a dedicated page; (2) the two-navigation cost is acceptable for Phase 3b's primary use case (correcting a handful of miscategorized transactions), and batch editing is a separable future enhancement that does not require changing this route's contract.

## Route contract

### `GET /transactions/<id>/edit`

Registered on `transactions_bp`. Auth-gated. `<id>` is a UUID string.

**Handler behavior:**

1. Parse `transaction_id = UUID(id)`. If `id` is not a valid UUID string, return HTTP 400 (or redirect to `/transactions` with an error flash — implementation agent's choice, either is acceptable).
2. Call `get_transaction(user_id, transaction_id)`. If `TransactionNotFound` is raised, return HTTP 404.
3. Call `list_categories(user_id)` to populate the category `<select>`.
4. Render the edit template with the transaction data and the category list.

**Template contents:**

- Read-only display: transaction date, description, amount.
- `<select name="category_id">` populated with the user's categories. The current `category_id` is pre-selected. A "No category" / uncategorized option is included at the top.
- `<input type="checkbox" name="apply_forward" value="1">` labeled "Apply this rule going forward."
- `<input type="text" name="keyword">` for the keyword to write. Pre-populated with the transaction's description (the full description string). The user may edit it to a shorter keyword. This field is always rendered — the server uses it only when `apply_forward` is checked.
- Submit button labeled "Save".
- A cancel link returning to `GET /transactions` (preserving no filter state — the user arrived from a filtered page but the cancel link goes to the unfiltered history).

### `POST /transactions/<id>/edit`

**Handler behavior:**

1. Parse `transaction_id` from the URL. If invalid UUID, return HTTP 400.
2. Extract form fields: `category_id` (UUID string or empty/blank for "uncategorized"), `apply_forward` (present = True, absent = False), `keyword` (string, may be empty).
3. Validate: if `category_id` is non-empty, verify it parses as a UUID (HTTP 400 if not). The service will validate ownership.
4. Determine `apply_forward_keyword`:
   - If `apply_forward` is True and `keyword.strip()` is non-empty: pass `apply_forward_keyword=keyword.strip()`.
   - Otherwise: pass `apply_forward_keyword=None`.
5. Call `recategorize_transaction(user_id, transaction_id, category_id, apply_forward_keyword=apply_forward_keyword)`.
6. On success: flash a success message and redirect to `GET /transactions`.
7. On `TransactionNotFound`: return HTTP 404.
8. On `CategoryNotFound`: flash an error message ("Category not found or no longer available") and re-render the edit form with the original transaction data.
9. On any other exception from the keyword write step (propagated from `recategorize_transaction`): flash a partial-success message ("Transaction recategorized, but the keyword rule could not be saved — please try again from the category settings") and redirect to `GET /transactions`. The transaction update is already committed at this point.

**CSRF:** The `POST` route must be protected by the application's CSRF middleware (Flask-WTF or equivalent) per the cross-cutting security constraint in `CLAUDE.md` and `architecture.md`.

**"Apply forward" keyword derivation:**

The route handler pre-populates the keyword input with the full transaction description (`transaction.description`). The user edits it down to the relevant merchant substring before submitting. The route passes `keyword.strip()` to `recategorize_transaction` as `apply_forward_keyword`; the service normalizes it further via `add_keyword`'s own normalization (strip + uppercase). The route does NOT attempt to auto-extract a keyword from the description — that is an Intelligence Layer concern (Phase 5), not a Phase 3b concern.

**"No category" / uncategorized option:**

The `<select>` includes a leading option `<option value="">No category</option>`. When selected, `category_id` is submitted as an empty string. The route handler interprets empty string as `None` for the `category_id` argument. `recategorize_transaction` must accept `category_id = None` to clear the categorization. The function spec in ADR-0018 must be updated by addendum to handle `None` as a valid `category_id` value that sets `transactions.category_id` to `NULL`. In that case, step 5 (keyword write) is skipped regardless of `apply_forward` — writing a keyword with no target category is not meaningful.

## Flash message conventions

| Outcome | Flash category | Message text |
|---|---|---|
| Successful recategorize | `success` | "Transaction recategorized." |
| Successful recategorize + keyword written | `success` | "Transaction recategorized and keyword rule saved." |
| Keyword already existed (conflict) | `success` | "Transaction recategorized. (Keyword rule already existed.)" |
| Transaction not found | HTTP 404 | — |
| Category not found | `error` | "Category not found or no longer available." |
| Keyword write failed (partial success) | `warning` | "Transaction recategorized, but the keyword rule could not be saved. You can add it manually in Category Settings." |

## Navigation integration

- The history view (`GET /transactions`) renders an "Edit" link on each row: `<a href="{{ url_for('transactions.edit', id=txn.id) }}">Edit</a>`.
- After successful submission, the redirect goes to `url_for("transactions.history")` (the unfiltered history, page 1). Preserving filter state across the POST-redirect cycle requires passing filter parameters through the edit URL or through the session, which is out of scope for Phase 3b.
- The edit page's cancel link is `url_for("transactions.history")`.

## Consequences

- **Positive.** Valid HTML, no JavaScript required. Works on any browser and is compatible with future progressive enhancement if desired.
- **Positive.** The edit page's URL is stable and linkable. A user can bookmark a transaction edit page or share it with a developer for debugging.
- **Positive.** Keyword input is pre-filled with the full description, reducing friction — the user edits rather than types from scratch.
- **Positive.** The partial-success flash message surfaces the atomicity gap from ADR-0018 to the user in plain language, with a clear recovery path.
- **Negative.** Filter state is lost after the POST redirect. The user returns to the unfiltered history page 1. If they were filtering by category to find a batch of miscategorizations, they must re-apply the filter. This is acceptable for Phase 3b; filter persistence could be added via URL round-tripping in a later phase.
- **Negative.** The keyword input is always visible (not toggled by the checkbox). Without JavaScript, progressive disclosure is not possible without a separate page reload. The input is clearly labeled and logically subordinate to the checkbox in the form layout; the UX cost is acceptable.
- **Follow-up.** ADR-0018's function spec must be updated by addendum to document `category_id = None` as a valid value that clears categorization (sets `transactions.category_id` to `NULL`). The step 5 (keyword write) is skipped when `category_id` is `None`.
- **Follow-up.** The route endpoint name for the edit page must be `transactions.edit` so that `url_for("transactions.edit", id=txn.id)` works from the history template. The implementation agent registers the route with `@transactions_bp.route("/transactions/<id>/edit", endpoint="edit")`.
- **Follow-up.** The test-writer agent must exercise: (a) GET renders with pre-selected category, (b) POST recategorize-only redirects with success flash, (c) POST with apply-forward writes keyword and flashes correct message, (d) POST with invalid UUID returns 400, (e) POST with unknown transaction_id returns 404, (f) POST with category belonging to another user flashes category-not-found error, (g) CSRF token missing returns 400/403.

## Notes

The choice to redirect to the unfiltered history after submit (rather than the referrer URL) avoids the complexity of passing referrer state through the edit page without session storage. If user research reveals this is a significant friction point, the route can accept a `?next=` parameter and redirect to it after success — that is a single-line change in the route handler with no architectural impact.

**Amendment — edit form copy updated to reflect alias-always-saved behaviour (2026-05-19):** ADR-0018 was amended so that a merchant alias is always written on recategorization, regardless of whether the user checks "apply forward." The original checkbox label ("Apply this rule going forward") implied that nothing would be remembered without it, which was no longer true. Resolution: the checkbox is relabelled "Also save a keyword pattern" and prefaced by a note explaining that the merchant is remembered automatically. The keyword input label changes from "Keyword" to "Keyword pattern" and its hint is updated to guide users toward trimming the description to the core merchant name. No route or service changes — this is a template-only amendment.
