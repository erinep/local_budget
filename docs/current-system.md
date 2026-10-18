# Current System

Last updated: 2026-08-16

## Runtime

Local Budget Parser is a server-rendered Flask application. `wsgi.py` exposes
the app created by `app.create_app()`. Blueprints live under `app/*/routes.py`,
and most business logic lives in adjacent `services.py` modules.

## Database

The application targets PostgreSQL. `app.db.get_engine()` reads `DATABASE_URL`
and returns a cached SQLAlchemy engine. Alembic migrations are the schema source
of truth.

Postgres-specific features are intentional: schemas, UUID defaults,
`TIMESTAMPTZ`, `BYTEA`, `ON CONFLICT`, typed arrays, and aggregate/date
functions. SQLite is not a supported target.

## Authentication

Authentication is moving from Supabase Auth to a local Postgres-backed auth
service. The compatibility anchor is still `auth.users(id)`, because existing
application tables cascade from that row.

The route/session interface remains:

- `session["user_id"]`
- `session["email"]`
- `session["expires_at"]`
- refresh token stored server-side in `public.user_sessions`

Google OAuth is not part of the local-auth phase. It should stay explicitly
unavailable until a separate OAuth decision is made.

## Modules

| Module | HTTP Layer | Service Layer | Owns |
|---|---|---|---|
| Auth | `app/auth/routes.py` | `app/auth/services.py` | users, password auth, sessions |
| Account Settings | `app/account_settings/routes.py` | `app/account_settings/services.py` | categories, keywords, aliases, user prefs |
| Transactions | `app/transactions/routes.py` | `app/transactions/services.py` | accounts, uploads, transactions |
| Budgets | `app/budgets/routes.py` | `app/budgets/services.py` | budget targets |
| Intelligence | `app/intelligence/routes.py` | widget modules | read-only reports and widgets |

Routes may call service functions. Services should not import route modules or
Flask request/session globals.

## Local Development

For local LAN Postgres on Fedora/Podman, see
`docs/runbooks/local-postgres.md`.

Fresh local databases must have the local `auth` schema available before
migrations that reference `auth.users(id)` run. The migration chain creates it.

## Validation

Run `pytest -v` for the full fast suite. DB-gated tests skip when
`DATABASE_URL` is unset. Run those against a disposable local Postgres database
after schema or SQL changes.
