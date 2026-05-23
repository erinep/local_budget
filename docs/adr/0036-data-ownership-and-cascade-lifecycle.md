# ADR 0036 - Data Ownership Hierarchy and Delete Cascade Lifecycle

- **Status:** Accepted
- **Date:** 2026-05-23
- **Phase:** P5c
- **Deciders:** erin, architect agent

## Context

The ownership chain across the Transaction Engine tables has been established incrementally across several ADRs (ADR-0013, ADR-0014, ADR-0015, ADR-0016, ADR-0034). No single document defines the full hierarchy, what a delete at each level removes, and what survives. This ADR consolidates that picture before Phase 5c implementation begins, so that the account management UI and its delete flows are built against a clearly stated contract.

The primary question that prompted this ADR: **when an account is deleted, are its associated upload records also deleted?** The answer has consequences for the file management UI (ADR-0021) and for whether the file-hash dedup record (ADR-0013 Layer 1) is preserved after a delete.

## Ownership hierarchy

```
User (auth.users)
├── Account (public.accounts)          — a named transaction group (ADR-0034)
│   ├── Upload (public.uploads)        — one CSV file import
│   │   └── Transaction               — via source_file_id
│   └── Transaction (public.transactions) — via account_id
├── Category (public.categories)
│   ├── Keyword (public.category_keywords)
│   └── Merchant Alias (public.merchant_aliases)
└── Budget (public.budgets)
```

Transactions sit at the bottom of two parallel chains: they are owned by an account (via `account_id`) and by an upload (via `source_file_id`). Both FKs carry `ON DELETE CASCADE`. This is the intentional defense-in-depth established in ADR-0015: either path alone is sufficient to remove a transaction; both existing means a schema change to one path cannot silently orphan rows.

## Delete cascade behavior by operation

### Delete account

Removes: the account row, all uploads that belong to that account, all transactions that belong to those uploads (via `source_file_id` cascade), and all transactions that belong to that account directly (via `account_id` cascade).

Net result: **the account and everything associated with it is gone** — transactions, upload records, and the file-hash dedup history for those files.

### Delete upload

Removes: the upload row, all transactions sourced from that file (via `source_file_id` cascade).

The account is **not** affected. Other uploads on the same account are not affected.

Net result: one file's worth of transactions is removed. This is the existing "delete file" feature (ADR-0021).

### Delete user

Removes: all accounts (→ uploads → transactions), all categories (→ keywords → merchant aliases), all budgets. Everything the user owns, atomically. Governed by ADR-0015.

### Delete category

Removes: the category row, all keywords under it, all merchant aliases under it. Transactions that referenced this category have their `category_id` set to `NULL` (they become uncategorized) — `transactions.category_id` is nullable and does not carry `ON DELETE CASCADE`, it carries `ON DELETE SET NULL`.

### Delete budget target

Removes: the budget row only. No effect on transactions or categories.

## Dedup scope is per-account, intentionally

Dedup (ADR-0013) uses a fingerprint that includes `account_id`. The same transaction uploaded to two different accounts produces two different fingerprints and two separate rows. Cross-account dedup is not performed and is not desired — a transfer between a chequing and savings account would appear in both CSVs legitimately, and cross-account dedup would silently drop one side of it.

The Layer 1 file-hash check (ADR-0013) catches re-uploading the exact same file to the same account. It does not catch uploading the same file to a different account — that is treated as a new import, which is the correct behaviour.

## Flag: uploads are deleted with their account

When an account is deleted, its upload records are deleted alongside its transactions. This has two consequences worth calling out explicitly:

1. **File management UI (ADR-0021).** The uploads listed on `/files` are scoped per user. If an account is deleted, those uploads disappear from the file list silently. The user should be told in the account delete confirmation dialog that this will happen: "This will permanently delete N transactions across M uploads."

2. **File-hash dedup (ADR-0013 Layer 1).** The file hash is stored on the upload record. Deleting the upload erases the dedup record. If the user later re-uploads the same CSV file to a different account, the Layer 1 hash check will find no match and the file will be processed as new — transactions will be re-inserted under the new account. This is **intentional**: if the user deleted an account they are explicitly discarding that history, and allowing the file to be re-imported to a new account is the correct recovery path.

## Flag: uploads cannot be re-assigned between accounts

`uploads.account_id` is `NOT NULL` with no update path defined. An upload is permanently assigned to the account it was imported into. If the user wants transactions from a file to appear under a different account, the current path is: delete the original upload (removing those transactions), then re-upload the file under the correct account. There is no bulk-reassign operation. This is an acceptable limitation for v1; a future ADR would govern reassignment if it becomes needed.

## FK reference table

| Table | Column | References | On Delete |
|---|---|---|---|
| `public.accounts` | `user_id` | `auth.users(id)` | CASCADE |
| `public.uploads` | `user_id` | `auth.users(id)` | CASCADE |
| `public.uploads` | `account_id` | `public.accounts(id)` | CASCADE |
| `public.transactions` | `user_id` | `auth.users(id)` | CASCADE |
| `public.transactions` | `account_id` | `public.accounts(id)` | CASCADE |
| `public.transactions` | `source_file_id` | `public.uploads(id)` | CASCADE |
| `public.transactions` | `category_id` | `public.categories(id)` | SET NULL |
| `public.categories` | `user_id` | `auth.users(id)` | CASCADE |
| `public.category_keywords` | `category_id` | `public.categories(id)` | CASCADE |
| `public.merchant_aliases` | `category_id` | `public.categories(id)` | CASCADE |
| `public.budgets` | `user_id` | `auth.users(id)` | CASCADE |

## Consequences

- Positive: the full cascade chain is documented in one place. Implementation agents and future architects have a single reference rather than reconstructing it across five ADRs.
- Positive: the two flags above (uploads deleted with account; uploads not reassignable) are explicit decisions, not surprises discovered during implementation.
- Positive: `transactions.category_id SET NULL` is confirmed as the correct behavior — deleting a category uncategorizes transactions rather than removing them, which preserves financial history.
- Negative: the account delete confirmation dialog must query both transaction count and upload count to give the user an accurate warning. This is a minor extra query, not a structural concern.
- Follow-ups required: (1) Account delete confirmation dialog must surface both N transactions and M uploads in its warning text. (2) ADR-0021 (file management) should be updated with a note that upload records are removed when their parent account is deleted.
