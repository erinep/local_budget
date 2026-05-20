---
adr: 0032
title: Categorization UX Overhaul — Bulk Edit and Single-Edit Improvements
status: Draft
date: 2026-05-19
phase: P5c
deciders: erin
---

## Context

Categorization is the core function of the application. The current flow (ADR-0020) chose a dedicated single-edit page for Phase 3b with an explicit note that "batch editing is a separable future enhancement." That moment has arrived.

Two distinct UX problems have been identified:

**Problem 1 — Single-edit is too slow.** Correcting a miscategorized transaction costs two full navigations (Edit → page load → fill form → submit → redirect back). The keyword pre-fill is the raw description string, which is rarely what the user wants to type as a pattern — the normalized merchant name would be more useful. The alias-always-saved behavior is invisible.

**Problem 2 — There is no path to correct many transactions at once.** A user who imports a new merchant for the first time (say, a new gym) may have dozens of uncategorized transactions from that merchant. The only current path is to edit each one individually, which is unacceptably slow.

The backfill route (`POST /account-settings/categories/backfill`) partially addresses this, but it operates on all uncategorized transactions at once and has no per-merchant granularity — the user cannot say "categorize all GOODLIFE transactions as Health without touching the others."

This ADR designs the target state for both problems and records what is deferred.

---

## Problem 1 — Single-edit improvements

### Current state

- User lands on `GET /transactions/<id>/edit`: a full page with a category `<select>`, a "save keyword pattern" checkbox, a keyword input pre-filled with the raw description, and a Submit button.
- Keyword pre-fill is the full raw description (`"SQ * GOODLIFE FITNESS 1234 TORONTO ON"`). The user must manually trim it to the useful core (`"GOODLIFE"`).
- Merchant alias is always written silently. The form note says "merchant is remembered automatically" but shows no confirmation of what was remembered.
- After submit, user returns to the history page (with filter state preserved via `?next=` per Amendment 2 of ADR-0020).

### What to improve

**Keyword recommendation.** The keyword input should be pre-filled with `normalize_description(description)` — the output of the existing normalization pass — rather than the raw description. This strips processor prefixes (`SQ *`, `PAYPAL *`, `TST*`), store numbers, and city/state suffixes. The raw description should still be shown as read-only context, but the input should start at the already-cleaned string.

Example: raw `"SQ * TIM HORTONS #4412 TORONTO ON"` → keyword pre-fill `"TIM HORTONS"`. This is nearly always correct and requires no editing.

**Alias visibility.** After saving, the success flash should name the alias that was written: `"Transaction saved. Merchant 'TIM HORTONS' will be recognized automatically from now on."` If an alias already existed (the `ON CONFLICT DO NOTHING` path), the flash should acknowledge that: `"Transaction saved. Merchant 'TIM HORTONS' was already in your history."` This requires the route to inspect whether an alias was inserted or already existed — the service currently does not return this information (see Consequences).

**Reduce clicks — inline modal option.** The single-edit page requires a full navigation. An inline modal over the history table would eliminate this — click Edit, modal opens, submit, modal closes, row updates. This requires JavaScript and conflicts with the no-JS constraint from ADR-0020. See the options section below.

### Options for single-edit interaction model

#### Option 1A — Keep dedicated page, improve content (no JS required)

Keep `GET/POST /transactions/<id>/edit` as-is. Apply keyword pre-fill improvement and alias visibility flash. Navigation cost unchanged (two full page loads per correction).

**Pros.** No JavaScript. No breaking change to the route contract. Low implementation risk.  
**Cons.** Still two navigations per correction. A user fixing 20 transactions in sequence makes 40 page loads.

#### Option 1B — Inline modal with no-JS fallback (JS progressive enhancement)

"Edit" link on history row opens a `<dialog>` element (HTML-native modal, no library). The dialog contains the same form as the dedicated page. JavaScript intercepts the form submit, posts via `fetch`, and closes the dialog on success — updating the row's category cell in-place. Without JavaScript, clicking "Edit" navigates to the dedicated edit page as before.

**Pros.** Zero navigations for JS users. Row updates in-place — the user never loses their scroll position or filter state. No-JS fallback preserved.  
**Cons.** Two code paths to test (JS and no-JS). The row's category cell must be updated client-side on success, which means either re-rendering the row from a JSON response or doing a targeted DOM update. Adds frontend complexity. The `<dialog>` element has good but not universal browser support (Firefox 98+, Chrome 37+, Safari 15.4+).

#### Option 1C — Inline edit row (no modal, no navigation)

Clicking "Edit" on a row replaces that row's cells with a `<select>` and a "Save" button, in-place. Submit via `fetch`. No page load, no modal.

**Pros.** Lowest navigation cost.  
**Cons.** Requires JavaScript. Inline keyword editing is very cramped in a table row. The alias-visibility flash has no natural home (a toast notification would be needed). Harder to add keyword recommendation input.

### Recommendation — single-edit

Adopt **Option 1B**. The `<dialog>` progressive-enhancement approach eliminates the primary friction (two full page loads) for users with JavaScript, while preserving the existing route contract as a no-JS fallback. The no-JS path continues to work exactly as it does today, so no regression risk for the existing test suite.

The keyword improvement (normalize pre-fill) and alias visibility flash apply to both the modal and the dedicated page, since they share the same form and route.

---

## Problem 2 — Bulk categorization

### What the user needs

- Select one or more transactions on the history view (with current filters applied).
- Apply a category to all selected transactions in one action.
- Merchant alias handling: write aliases for selected transactions without prompting per-row.
- "Select all matching" that works across pages (not just the visible 50).

### Options for bulk selection UI

#### Option 2A — Checkbox column + floating action bar (preferred by product)

Each history row gets a leading checkbox. A "select all on this page" checkbox lives in the table header. A sticky action bar (bottom of viewport or top of the results card) appears when ≥1 checkbox is checked, containing:

- A count indicator: "3 transactions selected"
- A "Select all N matching" link — extends selection to all results across all pages matching the current filter
- A category dropdown (populated from the user's categories)
- An "Apply Category" button
- A "Deselect all" link

Submitting the form sends selected transaction IDs + chosen category ID in a `POST /transactions/bulk-categorize` request.

**Pros.** The user described this pattern and it matches established conventions (Gmail, Notion, Linear). Filters compose naturally — the user can search for "GOODLIFE", select all 30 results across pages, and apply "Health" in one action.  
**Cons.** Requires JavaScript for the "select all N matching" behavior (the server cannot know which matching IDs to include without a second query). Without JavaScript, a plain form with checkboxes still works for visible-page selection, but "select all matching across pages" cannot function. The form POST with 50+ hidden checkbox values is inelegant but functional.  
**"Select all matching across pages" without JS:** The server can accept a flag `select_all_matching=1` plus the current filter parameters instead of explicit transaction IDs — the server then re-runs the filter query and applies the category to all results. This works with plain HTML (no JS needed for this part).

#### Option 2B — Filter-based bulk apply (no checkboxes)

Instead of selecting individual rows, the user uses the existing filters (date range, category, search) to scope transactions, then clicks "Apply category to all matching" — a new button that appears in the filter card. The action applies the chosen category to all transactions matching the current filter.

**Pros.** Simplest implementation. No checkbox UI. Works without JavaScript.  
**Cons.** All-or-nothing — the user cannot pick a subset of filtered results. If the filter matches 30 transactions but the user only wants to recategorize 25 of them, they cannot express that. Also less familiar UX pattern — users expect to select before acting.

#### Option 2C — Dedicated bulk edit page

History rows have checkboxes; "Edit selected" button navigates to a separate page showing the selected transactions with a shared category dropdown.

**Pros.** Full page for the bulk action — room for per-row confirmation.  
**Cons.** Extra navigation. Selection state must survive the page transition (e.g., via URL params or session). Complex to implement correctly.

### Recommendation — bulk edit

Adopt **Option 2A** with a hybrid server-side "select all matching" implementation:

- Checkboxes per row (plain HTML, works without JS).
- Floating action bar rendered by the template when any checkbox is checked — the bar is hidden via CSS (`display:none`) and shown with a small JS snippet (`querySelectorAll(':checked').length > 0`). Without JS, the bar is always visible but the count label is absent.
- "Select all N matching" posts the filter parameters to `/transactions/bulk-categorize` with `select_all=1` instead of individual IDs. The server re-runs the filter query and categorizes all results. This requires no JS.
- With JS: "Select all N matching" populates hidden checkboxes for all matching IDs (via a lightweight `GET /transactions/ids?<current-filters>` endpoint that returns a JSON array of IDs). This is an enhancement, not a requirement.

---

## Merchant alias behavior in bulk context

This is the hardest design question. In single-edit, one alias is written per transaction (the normalized description). In bulk, the user may select 30 transactions from 15 different merchants. Options:

### Option A — Write one alias per selected transaction, silently

Same behavior as single-edit, applied to every selected transaction. No per-merchant confirmation.

**Pros.** Consistent with single-edit. Zero extra UI.  
**Cons.** The user may not realize they are writing 30 aliases at once. If some of those transactions are genuinely one-off (a refund, an ATM fee that happened to match a search), the alias pollutes future categorization.

### Option B — Group by normalized merchant, confirm per group

After selecting and choosing a category, show a second step: a list of distinct normalized merchant names found in the selection, each with a checkbox defaulted to checked. The user unchecks merchants they do not want to persist. Submit writes aliases only for checked merchants.

**Pros.** Explicit. Prevents accidental alias pollution.  
**Cons.** Adds a second step to the bulk flow. Overhead for users who always want all aliases.

### Option C — Opt-out: write all aliases, surface a "review aliases written" link after

Write all aliases silently (Option A), but include a link in the success flash: "30 transactions categorized. 12 merchant aliases written — review them." The link goes to the existing Merchant Aliases management page (ADR-0031) where they can delete any incorrect ones.

**Pros.** Fast primary path. Review is available but not forced.  
**Cons.** Users may not follow the link. A bad alias can silently mis-categorize future uploads before it is caught.

### Option D — No aliases in bulk

Bulk categorization never writes merchant aliases. Aliases are only written through single-edit. The user uses bulk to make a fast first pass; aliases accumulate naturally through subsequent single-edit corrections.

**Pros.** Simplest. No risk of polluting aliases with bulk noise.  
**Cons.** Removes a significant time-saving: if the user bulk-categorizes 30 GOODLIFE transactions, they would expect future GOODLIFE transactions to be auto-categorized. Without aliases, they have to manually add a keyword in Category Settings or go through single-edit for the next upload.

### Recommendation — merchant aliases in bulk

**Option C** for v1. Silent alias writes (consistent with single-edit) with a "review aliases written" link in the success flash. This keeps the bulk flow to one step and surfaces the management tool (ADR-0031) in context. If user testing shows alias pollution is a real problem, promote to Option B.

---

## New routes required

| Method | Path | Description |
|---|---|---|
| `POST` | `/transactions/bulk-categorize` | Apply a category to selected transactions (by ID list or `select_all=1` + filter params) |
| `GET` | `/transactions/ids` | Return JSON array of transaction IDs matching current filter (JS enhancement only) |

`POST /transactions/bulk-categorize` accepts:
- `category_id` — UUID of category to apply (required)
- `transaction_ids[]` — list of transaction UUID strings (one or more required, unless `select_all=1`)
- `select_all` — `"1"` to apply to all filter-matching transactions (server re-runs query)
- Filter params when `select_all=1`: `date_from`, `date_to`, `category_id_filter`, `search`, `uncategorized`
- `next` — URL to redirect to after success (same `urlparse` host-stripping as backfill)

The route calls a new service function `bulk_categorize_transactions(user_id, transaction_ids, category_id)` in `app/transactions/services.py` — a batch UPDATE + batch alias INSERT, within a single transaction, using the same pattern as the backfill route post-fix (per-row UPDATE inside `engine.begin()`).

---

## What is deferred

- **Per-merchant confirmation step** (Option B above) — deferred to a later iteration if alias pollution proves to be a problem in practice.
- **JS-enhanced "select all matching" via `/transactions/ids`** — deferred; the server-side `select_all=1` path handles the use case without JavaScript.
- **Bulk keyword pattern entry** — not meaningful in bulk context (multiple descriptions, one pattern?). Deferred. The alias path covers the primary use case.
- **Bulk delete** — out of scope for now (deletion is a data-loss operation and deserves its own careful design).
- **Undo** — too complex for v1. The success flash should name the count so the user knows what happened.

---

## Implementation sequence

These can be implemented sequentially on a single branch:

1. **Single-edit improvements** — keyword pre-fill via `normalize_description`, alias-named flash message (requires service-layer change to return whether alias was inserted or already existed).
2. **Checkbox column + CSS-only action bar** — no JavaScript, works immediately.
3. **`POST /transactions/bulk-categorize`** — server-side bulk apply with `select_all=1` support.
4. **JS enhancements** — show/hide action bar dynamically, live selection count, "select all matching" via `/transactions/ids`.

Step 4 is the only JavaScript-dependent step and can be omitted or shipped later without affecting steps 1–3.

---

## Open questions before implementation

1. **Modal vs. dedicated page for single-edit** — Option 1B (modal) is recommended but requires a JS decision. Is JavaScript now an accepted requirement for the edit flow, or do we keep the no-JS constraint from ADR-0020? This gate must be resolved before implementation starts.
2. **"Select all matching" scope** — does `select_all=1` apply to the entire uncategorized set, or does it respect every active filter? Recommendation: respect all active filters, so the user can search for "GOODLIFE" and select all matching.
3. **Flash verbosity** — should the bulk success flash list the aliases written, or just the transaction count? Listing every alias is verbose for a 50-row bulk action. Recommendation: "30 transactions categorized, 8 merchant aliases written — [review]."
4. **Action bar position** — sticky bottom-of-viewport or top of the results card? Bottom-of-viewport is familiar (Gmail/Notion pattern) but requires CSS position:fixed. Top of results card requires less CSS but scrolls off-screen when the table is long. Recommendation: bottom-of-viewport sticky bar.

---

## Consequences

- **Positive.** Bulk categorization makes the application usable after a first import with many uncategorized transactions.
- **Positive.** Keyword pre-fill improvement reduces keyboard interaction per single-edit to near-zero in the common case.
- **Positive.** Both improvements are additive — no existing route contracts are broken.
- **Negative.** JavaScript is now de-facto required for a good experience (modal, live selection count, sticky bar show/hide). The no-JS constraint from ADR-0020 becomes a "no-JS fallback" guarantee rather than a "no-JS required" guarantee. This is a meaningful shift in the application's progressive enhancement posture.
- **Negative.** New service function `bulk_categorize_transactions` touches `public.transactions` directly (same as the backfill route). This must remain inside `app/transactions/services.py` to respect ADR-0003 module boundaries.
- **Follow-up.** `recategorize_transaction` (ADR-0018) should be updated to return whether an alias was inserted or already existed, so the single-edit flash can name the alias. This is a non-breaking change (add a return value).
