# Local Budget Parser Agent Map

This file is the short entry point for coding agents. Treat it as a map, not
the source of every detail.

## Start Here

1. Read `docs/current-system.md` for the current runtime, module boundaries,
   database posture, and migration direction.
2. Read `docs/architecture.md` for stable module responsibilities.
3. Read `docs/adr/README.md` and the ADRs relevant to your change.
4. Read `docs/risks.md` before touching auth, uploads, transaction writes, or
   financial data deletion.
5. For local database work, read `docs/runbooks/local-postgres.md`.

`CLAUDE.md` is historical orientation. Prefer this file plus `docs/` for the
current agent-facing map.

## Common Commands

```bash
pytest -v
alembic upgrade head
flask --app wsgi:app run
```

DB-gated tests require `DATABASE_URL` to point at a migrated Postgres database.
Tests that do not need a live database should not depend on that variable.

## Architecture Rules

- Flask route modules own HTTP mechanics and call service functions.
- Service modules own business logic and database access.
- Service modules must not import Flask request/session/g objects.
- Route modules must not import other route modules.
- Database access goes through `app.db.get_engine`.
- Schema changes go through Alembic migrations only.
- `auth.users(id)` remains the root user row for cascade deletion.
- Supabase is no longer a runtime dependency. New auth work should target the
  local Postgres-backed auth service.

## Data Rules

- Never log raw transaction descriptions, filenames, emails, tokens, amounts,
  file hashes, or fingerprints.
- User-owned financial data must remain scoped by `user_id`.
- Data-writing service changes need regression tests.
- Preserve idempotency for uploads and transaction writes.

## When Adding Knowledge

Put durable decisions in ADRs, operational steps in `docs/runbooks/`, active
multi-step work in `docs/exec-plans/active/`, and current-state summaries in
`docs/current-system.md`.
