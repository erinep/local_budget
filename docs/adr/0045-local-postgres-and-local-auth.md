# ADR 0045 - Local Postgres and Local Auth

Status: Accepted
Date: 2026-08-16

## Context

ADR-0002 selected Supabase for managed Postgres and Auth. The application has
kept database access portable by using `DATABASE_URL`, SQLAlchemy, and standard
Postgres SQL outside the auth boundary. The remaining provider coupling is
hosted auth and the assumption that Supabase creates `auth.users`.

The target deployment is now a Fedora server on a local LAN, with Postgres
running under rootless Podman.

## Decision

Move to local Postgres and local email/password auth.

1. `DATABASE_URL` remains the database connection boundary.
2. `auth.users(id)` remains the root user table to preserve existing foreign
   keys and cascade deletion.
3. `app/auth/services.py` owns local signup, login, session refresh, logout,
   password reset token verification, and password update.
4. Supabase SDK is removed from runtime dependencies.
5. Google OAuth is unavailable until a separate OAuth provider decision is
   made.
6. Password reset token delivery is deferred; local auth can create and verify
   tokens, but email delivery requires a separate operational decision.

## Consequences

Positive:

- The app can run entirely on a LAN-hosted Postgres database.
- Data ownership and cascade deletion semantics remain stable.
- The old auth-service boundary kept this migration mostly isolated.

Negative:

- The application now owns password hashing and reset-token security.
- OAuth and email delivery are no longer delegated to Supabase.
- Existing Supabase-era docs and tests need cleanup as follow-up work.

## Validation

- Structural tests ensure the Supabase SDK is not imported by application code.
- Auth service tests exercise local signup, login, session refresh, reset-token
  verification, and password update.
- Fresh local databases must run `alembic upgrade head`.
