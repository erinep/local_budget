# ADR-0022 — Uploads: Replace Stored Row Count with Live Transaction Count

**Status:** Accepted  
**Date:** 2026-05-18  
**Phase:** P3b follow-up

---

## Context

`public.uploads.row_count` is set once at ingestion time and never updated. It records the number of rows parsed from the CSV, not the number of transactions currently linked to the upload.

This produces misleading UI in two real scenarios:

1. **Deduplication** — rows that match an existing fingerprint are silently skipped. The stored `row_count` reflects what was in the file, not what was actually inserted.
2. **Cascade delete** — if a user deletes a different upload whose transactions share `source_file_id` rows (e.g. a re-upload), the count on the surviving upload is unaffected even though its linked transactions changed.

The net effect: the Files page shows a row count that can diverge from the true number of transactions linked to that upload, and there is no way for the user to know they differ.

---

## Decision

Drop `uploads.row_count` and replace it with a live count derived from `public.transactions` at query time.

**Schema change:** Remove the `row_count` column from `public.uploads` via a new Alembic migration (`0004`).

**Service change:** Update `get_uploads` to compute the count via a `LEFT JOIN` + `COUNT`:

```sql
SELECT u.id, u.filename, u.uploaded_at, COUNT(t.id) AS transaction_count
FROM public.uploads u
JOIN public.accounts a ON a.id = u.account_id
LEFT JOIN public.transactions t ON t.source_file_id = u.id
WHERE a.user_id = :uid
GROUP BY u.id, u.filename, u.uploaded_at
ORDER BY u.uploaded_at DESC
```

**`Upload` dataclass:** Rename `row_count: int` → `transaction_count: int`. The field now means "transactions currently linked to this upload."

**UI:** Update `templates/transactions/files.html` column header from "Rows" to "Transactions".

---

## Options considered

### Option A — Keep `row_count`, add a second live-count column
Show both "originally imported" and "currently linked". Rejected: two counts side by side creates confusion; users would reasonably ask why they differ. The original ingested count has no user-facing value once the file is processed.

### Option B — Keep `row_count`, update it on every deduplication/delete
Maintain `row_count` as a materialized cache updated via triggers or service-layer bookkeeping. Rejected: extra write complexity with no benefit over the live join, which is trivially cheap for the scale of this application (one upload → at most thousands of transactions, not millions).

### Option C (chosen) — Drop `row_count`, compute live
Single source of truth. Count is always accurate. Query cost is negligible. No trigger or cache invalidation logic required.

---

## Consequences

- `Upload.row_count` is removed from the public API. Any callers (routes, templates, tests) must be updated to `Upload.transaction_count`.
- The Alembic migration is a **destructive column drop**. The stored value is lost, but it was already unreliable so there is no data loss of value.
- The Files page now shows the count a user can verify: "if I look at my transactions filtered by this upload, I should see this many rows."
- `test_upload_file_management.py` service tests that assert `u.row_count` must be updated to `u.transaction_count`.

---

## Migration

New migration `0004` (single operation):

```python
op.drop_column("uploads", "row_count", schema="public")
```

Downgrade:

```python
op.add_column("public.uploads", sa.Column("row_count", sa.Integer(), nullable=False, server_default="0"))
```
