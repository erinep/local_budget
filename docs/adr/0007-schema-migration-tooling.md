---
adr: 0007
title: Schema Migration Tooling — Alembic
status: Accepted
date: 2026-05-10
deciders: erin p
---

## Context

Phase 1 introduces the first schema migrations. ADR-0002 chose Supabase as the database and auth provider but explicitly constrained Supabase-specific surface to the auth integration module. Migration tooling touches every schema change for the life of the project; the choice here has long-term consequences for portability and developer workflow.

The roadmap lists "database migration tooling (Alembic if SQLAlchemy, or Supabase migrations)" as an open decision to resolve before Phase 1 ships. This ADR resolves it.

## Options considered

### Option A — Alembic (with SQLAlchemy)

Alembic is the standard migration tool for SQLAlchemy-backed Python apps. It generates versioned migration scripts as Python files, applies them against any PostgreSQL connection string, and maintains a `alembic_version` table to track applied migrations.

**Pros:**
- Migrations are plain Python/SQL committed to the app repo alongside the code that depends on them. The schema and application code stay in sync in version history.
- Completely portable to any PostgreSQL host — no Supabase dependency at all.
- CI integration is straightforward: `alembic upgrade head` against a test database in the GitHub Actions workflow.
- SQLAlchemy models (if introduced later) can auto-generate migration scaffolds via `alembic revision --autogenerate`.
- Consistent with ADR-0002's portability constraint: no Supabase-specific surface in the migration layer.

**Cons:**
- Requires SQLAlchemy as an ORM/query layer, or at minimum as a connection factory. If the app uses raw `psycopg2` queries, SQLAlchemy is an additional dependency for tooling only.
- Alembic's local dev workflow requires a running PostgreSQL instance or a `.env`-configured connection to Supabase.

### Option B — Supabase CLI migrations

The Supabase CLI manages migrations as plain SQL files in a `supabase/migrations/` directory. `supabase db push` applies them to the linked Supabase project. `supabase db diff` generates migration SQL from schema changes.

**Pros:**
- Native integration with Supabase Dashboard; migrations applied via CLI match what the Dashboard shows.
- SQL-only format — no Python dependency for migration authoring.
- `supabase db reset` spins up a local Postgres instance via Docker for local dev.

**Cons:**
- Requires the Supabase CLI and Docker for local development. Docker is an additional system dependency not currently needed.
- `supabase db push` couples the deployment step to the Supabase CLI being installed in CI. This is Supabase-specific tooling on the CI path.
- Migrating away from Supabase would require translating the migration history into a format another tool understands — mild but real coupling.
- Violates the spirit of ADR-0002's portability constraint even if it does not violate the letter: the migration layer becomes Supabase-aware.

## Decision

**Option A — Alembic.**

Alembic keeps the migration layer fully portable, consistent with ADR-0002's portability constraint. The Supabase-specific surface remains bounded to the auth integration module. CI integration requires no Supabase CLI installation — only a `DATABASE_URL` environment variable pointing at the Supabase PostgreSQL connection string.

SQLAlchemy is added as a dependency for connection management and, optionally, query building. The app does not have to use the ORM pattern; raw SQL via `session.execute(text(...))` is acceptable and keeps the option of switching to `psycopg2` directly if SQLAlchemy becomes unwanted overhead.

## What is now true about the system

1. Alembic is the schema migration tool. Migration files live in `migrations/versions/`.
2. `alembic upgrade head` is the deployment step for schema changes. It runs against `DATABASE_URL` (the Supabase PostgreSQL connection string).
3. CI runs `alembic upgrade head` against a test database before running pytest.
4. The migration write-lock rule from orchestration.md applies: only one agent (or human) authors a new migration at a time. Concurrent migrations will conflict on the `alembic_version` table.
5. SQLAlchemy is added to `requirements.txt` for connection management. ORM models are optional and introduced only when their ergonomics justify the abstraction.
6. `alembic downgrade` provides a rollback path. Every migration must have a corresponding `downgrade()` function.

## Consequences

- **Positive:** Schema history is version-controlled alongside application code. Rollbacks are deterministic.
- **Positive:** No Supabase CLI or Docker required in CI or on developer machines — only a `DATABASE_URL`.
- **Positive:** Alembic works against any PostgreSQL host, preserving the migration path documented in ADR-0002.
- **Negative:** SQLAlchemy is a new dependency. Its connection pooling behavior must be configured correctly for Supabase's connection limits (use `pool_pre_ping=True`; set `pool_size` conservatively on the free tier).
- **Follow-up:** The `alembic.ini` and `migrations/env.py` must be committed in the first Phase 1 PR. The initial migration creates `user_sessions` and `custom_categories` (Account Settings v0).
- **Follow-up:** A CI step must be added to the GitHub Actions workflow: `alembic upgrade head` against a test Supabase project (or a local Postgres service container).
