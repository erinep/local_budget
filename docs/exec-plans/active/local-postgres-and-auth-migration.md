# Local Postgres And Auth Migration

Status: active
Owner: implementation agent
Started: 2026-08-16

## Goal

Move the application from Supabase-hosted database/auth assumptions to local
LAN Postgres with local email/password auth, while preserving existing
`user_id` ownership, cascade deletion, and route/session behavior.

## Non-Goals

- SQLite support.
- Public internet exposure for Postgres.
- Google OAuth replacement.
- Production email delivery for password reset.

## Current Coupling

- Application data already uses `DATABASE_URL` and standard SQLAlchemy/raw SQL.
- Existing tables reference `auth.users(id)`.
- Auth service methods are the boundary consumed by routes and middleware.

## Target Shape

- Postgres runs locally, commonly through rootless Podman on Fedora.
- `auth.users` is created by migrations and stores local credentials.
- `app/auth/services.py` implements local signup, login, refresh, logout, and
  password update behavior.
- Google OAuth raises a clear unavailable error until separately designed.
- Supabase SDK is removed from runtime dependencies.

## Steps

1. Add agent-facing repo map and current-system docs.
2. Add local Postgres runbook.
3. Add structural tests for dependency boundaries.
4. Add local `auth.users` migration support before foreign keys reference it.
5. Replace Supabase Auth service calls with local Postgres-backed auth.
6. Update tests/docs to reflect the new boundary.
7. Run focused auth/structure tests and the full suite.

## Validation Checklist

- `pytest tests/test_structural_boundaries.py -v`
- `pytest tests/test_auth_service.py tests/test_auth_routes.py tests/test_middleware.py -v`
- `pytest -v`
- Fresh local Postgres can run `alembic upgrade head`.

## Risks

- Editing early migrations affects existing deployed databases. The local-auth
  migration uses `CREATE SCHEMA IF NOT EXISTS` / `CREATE TABLE IF NOT EXISTS`
  style DDL where possible to keep Supabase-era databases from failing.
- Password reset without an email provider can only create/verify local tokens.
  Delivery needs a separate decision before broader use.
- OAuth removal changes user-facing behavior for the Google button if it is
  still visible.
