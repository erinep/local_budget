---
adr: 0019
title: History View Route, Filter Subset, and Pagination Contract
status: Accepted
date: 2026-05-18
phase: P3b
deciders: erin
---

## Context

Phase 3b ships a transaction history view that surfaces the persisted transaction store to the user. The read API it consumes is pinned by ADR-0017 (`get_transactions`, `TransactionFilters`, `TransactionPage`). Three decisions need to be pinned before implementation: (1) which URL hosts the history view and where it lives in the navigation, (2) which filter subset does the Phase 3b UI expose, and (3) how does offset pagination translate into a UI control.

Governing constraints:

- **ADR-0011** (navigation contract): Phase 3 adds a `Transactions` top-level header link. The existing `transactions_bp` (URL prefix `/`) gains an index route. No new blueprint required.
- **ADR-0004** (blueprint layout): `transactions_bp` is the Transaction Engine's blueprint. Its existing prefix is `/`; new routes in Phase 3b are added to the same blueprint.
- **ADR-0017**: all filters (`date_from`, `date_to`, `category_id`, `account_id`, `search`, `uncategorized_only`, `limit`, `offset`) are available in the API. The UI need not expose all of them to satisfy Phase 3b's exit criterion.

Relevant risk: "Read API performance degrades with history size" — the filter and pagination choices directly affect which indexes are hit. Index design was settled in the ADR-0016 schema migration and referenced in ADR-0017; this ADR selects which paths the UI exercises.

## Options considered

### Option A — Route at /transactions, expose all filters

The history index lives at `GET /transactions` (added to `transactions_bp`). The UI exposes date range, category dropdown, description search, and uncategorized toggle — every filter the API supports except `account_id` (deferred, only one account exists in Phase 3b's UI).

**Pros.** Maximally useful for the user on day one. No filter-extension ADR needed before Phase 4.

**Cons.** Date pickers, a category dropdown populated from Account Settings, a search box, and a toggle are four distinct UI widgets to ship in one slice. The exit criterion is "users can browse their full transaction history and fix miscategorizations." Date range, category, and search are each independently useful; building all four in Phase 3b is wider than necessary.

### Option B — Route at /transactions, expose category filter and search only

The history index lives at `GET /transactions`. The UI exposes a category dropdown and a description search field. Date range and uncategorized toggle are deferred to a follow-up within Phase 3b or Phase 3c.

**Pros.** Narrower slice. The two most immediately useful filters for recategorization work (category to find miscategorized rows, search to find a specific merchant) are both present. The date range can be added in a subsequent PR without changing the route or the API.

**Cons.** Users with large histories cannot narrow by date. However, the default sort (most-recent first) and pagination mean stale rows are naturally below the fold. This is acceptable for Phase 3b's primary use case.

### Option C — Route at /history, expose category filter and search

Same filter set as Option B but at `/history` instead of `/transactions`.

**Pros.** URL makes the page's purpose explicit.

**Cons.** ADR-0011 explicitly names the Phase 3 header link `Transactions` and says the existing `transactions_bp` gains an index route. A `/history` URL creates a mismatch between the nav label and the URL. The canonical URL for the Transaction Engine's index should be `/transactions` to match the module and the blueprint.

## Decision

We will choose **Option B** — route at `GET /transactions`, with date range, category, and search filters exposed in Phase 3b. The `uncategorized_only` toggle and `account_id` filter are deferred.

The reasons that carried this decision: (1) `/transactions` is the correct URL per ADR-0011's navigation contract — the header link says `Transactions` and the blueprint already owns the `/` prefix; adding an explicit `/transactions` path to `transactions_bp` is a mechanical addition with no structural change; (2) date range is included because it is the most common narrowing operation for a personal finance history view and its UI widget (two date inputs) is lightweight to ship alongside the category dropdown and search field; (3) `uncategorized_only` and `account_id` are deferred because `uncategorized_only` is fully covered by the category filter set to "None" in the UI, and `account_id` has no utility until the multi-account UI ships.

## Route contract

```
GET /transactions
```

Registered on `transactions_bp` in `app/transactions/routes.py`. Auth-gated — redirects to login if no session.

**Query parameters accepted by the route:**

| Parameter | Maps to | Type | Validation |
|---|---|---|---|
| `date_from` | `TransactionFilters.date_from` | ISO 8601 date string (`YYYY-MM-DD`) | Optional. If present and not parseable as a date, treat as absent (no error to user — silently ignore). |
| `date_to` | `TransactionFilters.date_to` | ISO 8601 date string (`YYYY-MM-DD`) | Optional. Same handling. |
| `category_id` | `TransactionFilters.category_id` | UUID string | Optional. If present and not a valid UUID, treat as absent. |
| `search` | `TransactionFilters.search` | string | Optional. Passed as-is; the service normalizes empty string to None. |
| `page` | Derived (`offset = (page-1) * limit`) | positive integer | Optional. Default 1. If < 1 or non-integer, use 1. |

**Fixed values (not user-configurable in Phase 3b):**

| Field | Value | Reason |
|---|---|---|
| `limit` | 50 | Default from ADR-0017. Sufficient for Phase 3b. Configurable per-user is a future enhancement. |
| `uncategorized_only` | `False` | Category dropdown covers this use case adequately. |
| `account_id` | `None` | Multi-account UI deferred. |

**Route handler responsibility:**

1. Parse query parameters. Invalid values are silently treated as absent (no HTTP 400 to the user — the history view is best-effort filtered).
2. Construct `TransactionFilters` from parsed values.
3. Call `get_transactions(user_id, filters)` from `app/transactions/services`.
4. Load the user's category list from `account_settings.services.list_categories(user_id)` to populate the category dropdown. This call is separate from the transaction query; it hits the Account Settings cache (ADR-0010) so it is not an additional DB round-trip on a warm cache.
5. Render the template with the page data, pagination context, and active filter values (so the form shows what is currently applied).

**Pagination UI contract:**

The route passes the following to the template:

```python
{
    "page": page,              # current page number (1-indexed)
    "total_pages": ceil(total_count / limit),
    "total_count": total_count,
    "has_prev": page > 1,
    "has_next": page < total_pages,
    "prev_url": url_for("transactions.history", page=page-1, **current_filters),
    "next_url": url_for("transactions.history", page=page+1, **current_filters),
}
```

The template renders Previous/Next controls. It also renders a "Showing X–Y of Z transactions" summary using `offset + 1` through `min(offset + limit, total_count)`. No page-number list is rendered in Phase 3b — Previous/Next is sufficient for the typical use case and keeps the template simple.

**Filter persistence across pages:**

Active filters are preserved in pagination links via `url_for` kwargs. When the user clicks Next, the same `date_from`, `date_to`, `category_id`, and `search` parameters are included in the URL. The route reads all filter state from the query string on every request — no server-side session storage for filter state.

**Navigation integration (ADR-0011 follow-up):**

- The `Transactions` link in the header targets `url_for("transactions.history")` (the route's endpoint name, using `transactions_bp`'s name prefix).
- The dashboard's Upload card (ADR-0011 §6.1) evolves to also show a "View history" link to `/transactions`. This is a template change only; no new route.

## Consequences

- **Positive.** A single route, no new blueprint, no structural change — mechanically consistent with ADR-0004 and ADR-0011.
- **Positive.** Date range + category + search covers the primary filtering needs of the exit criterion: users can find miscategorized transactions by category or merchant name, and narrow by date if the history is long.
- **Positive.** Offset/page URL parameter is user-shareable and browser-back-navigable. Filter state is fully in the URL.
- **Negative.** No `uncategorized_only` toggle in Phase 3b. The workaround is to select no category in the dropdown (which returns all transactions) and rely on the category column being visually absent for uncategorized rows. If testing reveals this is insufficient, the toggle can be added as a checkbox with no API change.
- **Negative.** `limit` is fixed at 50. Power users with dense histories cannot request more. This is a known limitation, acceptable for Phase 3b.
- **Follow-up.** Update `base.html` to add the `Transactions` top-level header link (per ADR-0011 §6.1). Update the home blueprint's dashboard template to add a "View history" link.
- **Follow-up.** The route's endpoint name must be `transactions.history` so that `url_for("transactions.history")` works consistently across templates and pagination links. The implementation agent must register the route with `@transactions_bp.route("/transactions", endpoint="history")` or the equivalent.
