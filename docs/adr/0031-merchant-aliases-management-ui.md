# ADR 0031 - Merchant Aliases Management UI

- **Status:** Accepted
- **Date:** 2026-05-18
- **Phase:** P5b
- **Deciders:** erin

## Context

`merchant_aliases` was introduced in ADR-0029 as a write-only store populated automatically during recategorization (ADR-0018 amendment). Users have no current way to inspect or remove aliases. This becomes a problem when a mis-categorization writes an incorrect alias that then silently overrides the keyword scan on every future upload. The user cannot diagnose or fix this without direct database access.

The fix is a read+delete management page in Account Settings, consistent with how keywords are managed on the category edit page. Edit (rename) is explicitly deferred — the normalized name is derived from the transaction description and has no user-editable meaning; the correct action for a wrong alias is to delete it and re-correct the source transaction.

## Decision

Add a **Merchant Aliases** sub-page to Account Settings with:

- A table listing all aliases for the user, sorted by category name then normalized name.
- A delete button per row. No edit. Confirmation dialog on delete.
- A link card on the Configure landing page (`/account-settings/`).

No new schema or migration is required. The `merchant_aliases` table and its ownership chain (`alias.category_id → categories.user_id`) already exist (ADR-0029).

## New service functions

Both are added to `app/account_settings/services.py`:

```python
def list_merchant_aliases_detail(user_id: str) -> list[dict]:
    """Return all aliases for user_id with ids, for display and delete.

    Result shape: [{"id": str, "normalized_name": str, "category_id": str, "category_name": str}, ...]
    Ordered by category_name ASC, normalized_name ASC.
    """
    ...


def delete_merchant_alias(user_id: str, alias_id: str) -> None:
    """Delete a merchant alias scoped to user_id.

    Validates that the alias belongs to a category owned by user_id.

    Raises:
        ValueError("Alias not found")
    """
    ...
```

The existing `get_merchant_aliases(user_id)` is unchanged — it is the upload-path reader and returns lightweight tuples with no IDs, which is the right shape for the categorizer factory.

## New routes

Added to `app/account_settings/routes.py`:

| Method | Path | Endpoint | Description |
|---|---|---|---|
| `GET` | `/account-settings/aliases` | `aliases_list` | Render the aliases list page |
| `POST` | `/account-settings/aliases/<alias_id>/delete` | `aliases_delete` | Delete one alias; redirect to `aliases_list` |

Both require `@login_required`. The delete route validates ownership via `delete_merchant_alias`; a `ValueError` (alias not found or belongs to another user) becomes a `404 abort`.

## Tenant isolation

`delete_merchant_alias` JOINs through `categories WHERE user_id = :uid` before deleting, ensuring a user cannot delete another user's alias by guessing an alias UUID.

## Consequences

- **Positive.** Users can diagnose and correct bad aliases without database access.
- **Positive.** No schema change; fits entirely within the existing service-layer pattern.
- **Negative.** No edit; a wrong alias requires delete + re-correct. This is acceptable: the normalized name is derived from the raw description, so editing it directly would create an alias that no future transaction could ever match.
- **Follow-up.** If aliases grow large (hundreds per user), consider adding a search/filter field. Not in scope now.
