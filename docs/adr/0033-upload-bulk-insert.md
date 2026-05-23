# ADR 0033 - Bulk INSERT for Upload Transaction Persistence

- **Status:** Accepted
- **Date:** 2026-05-23
- **Phase:** Fix (post-5b)
- **Deciders:** architect agent, erin p

## Context

`_process_upload` in `app/transactions/services.py` issued one `conn.execute()` per CSV row inside a Python for-loop, each a separate round-trip to a remote Supabase database. At ~75 ms per round-trip and 300–500 rows, this reliably exceeded gunicorn's 30-second request timeout on Render's free tier. A 44 KB real-world file confirmed the failure in production. The fix must preserve the existing `ON CONFLICT (user_id, fingerprint) DO NOTHING` dedup semantics (ADR-0013) and still yield an accurate `new_count`. No schema changes are permitted; the fix is entirely in the service and route layers.

## Options considered

### Option A - `executemany` with a single-row VALUES clause

Pass a list of parameter dicts to `conn.execute(text(...), list_of_dicts)`. SQLAlchemy's `insertmanyvalues` optimization would collapse these into batches.

**Problem:** SQLAlchemy 2.0's `insertmanyvalues` is explicitly disabled when `ON CONFLICT` is combined with `RETURNING` for the psycopg2 dialect. Without the optimization, psycopg2 `executemany` discards all `RETURNING` result sets, making `new_count` impossible to derive accurately.

### Option B - Dynamic multi-row VALUES with numbered params

Build the SQL string dynamically: `VALUES (:p0_uid, :p0_dt, ...), (:p1_uid, :p1_dt, ...)`. One round-trip, full `RETURNING` support.

**Problem:** N rows × 8 columns = up to 4,000 named placeholders for a 500-row file. Requires dynamic string construction, which is fragile and harder to audit.

### Option C - `INSERT ... SELECT FROM unnest(...)` (chosen)

Pass each column as a typed PostgreSQL array parameter and use parallel `unnest()` in the `SELECT` clause to expand them into rows. One fixed SQL string, one round-trip, full `RETURNING` support, no dynamic string construction.

## Decision

We will use **Option C — `INSERT ... SELECT FROM unnest(...)`**. The SQL is a fixed string (no dynamic construction), collapses N round-trips to 1, and returns all inserted IDs via `RETURNING id` so `new_count = len(result.fetchall())`. This is standard PostgreSQL and works with any psycopg2 version.

Array binding requirements:
- `dates`: `list[str]` in `YYYY-MM-DD` format, bound as `:dates::date[]`
- `descs`: `list[str]`, bound as `:descs::text[]`
- `amounts`: `list[float]`, bound as `:amounts::numeric[]`
- `cat_ids`: `list[str | None]` (UUID strings or `None`), bound as `:cat_ids::uuid[]`; `None` elements pass as SQL `NULL` within the array
- `fps`: each fingerprint byte string wrapped as `psycopg2.Binary(fp)`, bound as `:fps::bytea[]`

The `uid`, `aid`, `sfid` scalars remain as named params shared across all rows.

The bulk INSERT remains inside the same `engine.begin()` block that wraps the `uploads` row insert, preserving the existing transaction boundary.

## Consequences

- **Positive:** Upload latency drops from O(N × round-trip) to O(1 × round-trip). A 400-row CSV that previously timed out at ~30 s now completes in ~100–200 ms of DB time.
- **Positive:** `new_count` is derived from `RETURNING id` result length — no change to the return contract of `_process_upload`.
- **Negative:** Adds a `psycopg2` direct import to `services.py` (previously implicit via SQLAlchemy). This is already a transitive dependency; making it explicit is a minor coupling increase.
- **Follow-ups:** The route layer (`routes.py`) gains a `try/except OperationalError` guard around `_process_upload` to surface DB/timeout failures as a user-facing error message rather than a silent 500. This does not change the success path.

## Notes

The fingerprint pre-computation loop (`_compute_fingerprint` per row, building `fingerprints: list[bytes]`) is unchanged. The new array-building loop is a second pass over the DataFrame that prepares the unnest inputs; it does not replace or merge with the fingerprint loop.
