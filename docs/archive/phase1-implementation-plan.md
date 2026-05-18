# Phase 1 — Persistence & Authentication: Implementation Plan

**Status:** Complete  
**Date:** 2026-05-10  
**Governing ADRs:** 0001, 0002, 0003, 0004, 0005, 0006, 0007  
**Exit criteria:** Users can sign up, log in, and continue to use the existing CSV report flow. Custom categories persist between sessions.

---

## Module layout

Phase 1 adds the following structure to the existing codebase:

```
app/
  auth/
    __init__.py          # registers blueprint at /auth
    routes.py            # login, logout, signup, password-reset routes
    services.py          # Supabase Auth integration — the ONLY file that calls Supabase client SDK
  account_settings/
    __init__.py          # registers blueprint at /settings
    services.py          # get_category_map, save_category_map (v0 — DB-backed)
  middleware/
    __init__.py
    auth.py              # login_required decorator; populates g.user from flask.session
  transactions/          # EXISTING — changes only
    routes.py            # add @login_required to all routes
    services.py          # unchanged
migrations/
  env.py                 # Alembic env configuration
  script.py.mako         # Alembic script template
  versions/
    0001_initial.py      # first migration: user_sessions, custom_categories
alembic.ini
```

---

## Schema

Supabase Auth manages the `auth.users` table internally. The application owns the following tables in the `public` schema.

### `user_sessions`

Stores Supabase refresh tokens server-side (referenced by the signed Flask session cookie). Session revocation in future phases deletes the row.

```sql
CREATE TABLE public.user_sessions (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id     UUID NOT NULL,                  -- references auth.users(id)
    refresh_token TEXT NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at  TIMESTAMPTZ NOT NULL,
    last_used_at TIMESTAMPTZ
);

CREATE INDEX idx_user_sessions_user_id ON public.user_sessions(user_id);
CREATE INDEX idx_user_sessions_expires_at ON public.user_sessions(expires_at);
```

### `custom_categories` (Account Settings v0)

Replaces `custom_categories.json` with a per-user database table. Phase 2 will supersede this with normalised `categories` and `category_keywords` tables; this is the minimum viable persistence for Phase 1.

```sql
CREATE TABLE public.custom_categories (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id     UUID NOT NULL UNIQUE,           -- one row per user
    category_map JSONB NOT NULL DEFAULT '{}',  -- {"Category": ["keyword1", "keyword2"]}
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_custom_categories_user_id ON public.custom_categories(user_id);
```

**Note:** The JSONB column is intentional for Phase 1 — it is the minimal change to swap JSON file storage for DB storage without designing the full normalised schema (which belongs to Phase 2). The Phase 2 migration will move data out of this column and drop the table.

---

## Service contracts

All functions are in `app/auth/services.py` or `app/account_settings/services.py`. Type annotations use stdlib types.

### `app/auth/services.py`

This is the **only** file that imports or calls the Supabase client SDK (per ADR-0002).

```python
from dataclasses import dataclass
from datetime import datetime

@dataclass
class AuthUser:
    id: str          # UUID string
    email: str

@dataclass
class AuthSession:
    user: AuthUser
    access_token: str
    refresh_token: str
    expires_at: datetime

def sign_up(email: str, password: str) -> AuthUser:
    """Create a new Supabase Auth user. Raises AuthError on failure."""

def sign_in(email: str, password: str) -> AuthSession:
    """Sign in via Supabase Auth. Raises AuthError on invalid credentials."""

def sign_out(refresh_token: str) -> None:
    """Revoke the Supabase session. Deletes the user_sessions row."""

def refresh_session(refresh_token: str) -> AuthSession:
    """Exchange a refresh token for a new access token. Called by middleware."""

def get_user_from_session(user_id: str) -> AuthUser | None:
    """Fetch user details from Supabase Auth by user ID. Returns None if not found."""

def initiate_password_reset(email: str) -> None:
    """Trigger Supabase Auth password-reset email. Silent on unknown email (no enumeration)."""
```

### `app/account_settings/services.py`

```python
def get_category_map(user_id: str) -> dict[str, list[str]]:
    """
    Return the user's category map from custom_categories.
    Returns the default generic map if no row exists for user_id.
    """

def save_category_map(user_id: str, category_map: dict[str, list[str]]) -> None:
    """
    Upsert the user's category map. Sets updated_at to now() UTC.
    """
```

### `app/middleware/auth.py`

```python
from functools import wraps
from flask import session, g, redirect, url_for

def load_user() -> None:
    """
    Before-request hook. Reads flask.session["user_id"] and populates g.user.
    Called via app.before_request. Sets g.user = None if session is absent or expired.
    """

def login_required(f):
    """Decorator. Redirects to /auth/login if g.user is None."""
    @wraps(f)
    def decorated(*args, **kwargs):
        if g.user is None:
            return redirect(url_for("auth.login"))
        return f(*args, **kwargs)
    return decorated
```

---

## Routes

### New: `app/auth/routes.py` (blueprint prefix `/auth`)

| Method | Path | Description |
|---|---|---|
| GET | `/auth/login` | Render login form |
| POST | `/auth/login` | Submit credentials; on success write session and redirect to `/` |
| GET | `/auth/logout` | Clear session, call `sign_out`, redirect to `/auth/login` |
| GET | `/auth/signup` | Render signup form |
| POST | `/auth/signup` | Create account via `sign_up`; auto-sign-in; redirect to `/` |
| GET | `/auth/reset-password` | Render password-reset request form |
| POST | `/auth/reset-password` | Call `initiate_password_reset`; show confirmation |

All POST routes require a valid CSRF token (Flask-WTF).

### Changed: `app/transactions/routes.py`

Add `@login_required` to every route. Pass `get_category_map(g.user.id)` into the service layer instead of loading from file (this is the Phase 1 wire-up of ADR-0005's DI pattern against the database).

---

## Dependencies to add to `requirements.txt`

```
sqlalchemy>=2.0
alembic>=1.13
supabase>=2.0          # Supabase Python client — used only in app/auth/services.py
flask-wtf>=1.2         # CSRF protection + form validation
python-dotenv>=1.0     # load .env for local dev
sentry-sdk[flask]>=2.0 # error tracking
```

---

## Sequencing

Phase 1 uses **one implementation agent**, no parallelism (per orchestration.md — auth has expensive failure modes). Work items in order:

1. **Alembic setup** — add `alembic.ini`, `migrations/env.py`, `migrations/script.py.mako`. Wire `DATABASE_URL` from environment. No migration yet.
2. **Initial migration** — create `user_sessions` and `custom_categories` tables. Run `alembic upgrade head` locally against Supabase dev project. Human reviews the migration SQL before it touches any database.
3. **Auth integration module** — `app/auth/services.py` with `sign_up`, `sign_in`, `sign_out`, `refresh_session`, `get_user_from_session`. Unit-testable with a test Supabase project; no mocking of the auth client (per the risk of mock/prod divergence).
4. **Session middleware** — `app/middleware/auth.py`: `load_user` registered as `before_request`, `login_required` decorator. No routes wired yet.
5. **Auth routes** — `app/auth/routes.py`: login, logout, signup, password-reset. Register blueprint. Add Flask-WTF CSRF to all POSTs.
6. **Account Settings v0** — `app/account_settings/services.py`: `get_category_map`, `save_category_map`. Replace JSON file loading in the transaction routes.
7. **Wire `@login_required` to existing routes** — update `app/transactions/routes.py`. Confirm the CSV report flow still works end-to-end while logged in.
8. **Sentry integration** — add `sentry_sdk.init(...)` to `app/__init__.py`. Verify error events appear in Sentry dashboard.
9. **CI update** — add `alembic upgrade head` step to GitHub Actions workflow against a CI Supabase project (or Postgres service container).

---

## Decisions (resolved 2026-05-10)

| Question | Decision |
|---|---|
| Google OAuth | Deferred to Phase 1.5. Phase 1 ships email/password only. See ADR-0008. |
| CI database | Postgres service container in GitHub Actions. No Supabase project quota consumed in CI. |
| `custom_categories.json` migration | Seed into DB on first login via a one-time migration script (step 6a in sequencing). |
| Session expiry | 1 hour with silent refresh, matching Supabase Auth default. |

---

## Test surface (for test-writer agent)

The test-writer agent should write tests from this spec, not from the implementation. Key scenarios:

**Auth service (`app/auth/services.py`):**
- `sign_up` creates a user and returns `AuthUser`
- `sign_up` raises on duplicate email
- `sign_in` returns `AuthSession` with valid credentials
- `sign_in` raises `AuthError` on wrong password
- `sign_out` does not raise; subsequent session is invalid
- `get_user_from_session` returns `None` for unknown user_id

**Middleware (`app/middleware/auth.py`):**
- `load_user` populates `g.user` when session contains valid `user_id`
- `load_user` sets `g.user = None` when session is absent
- `login_required` redirects to `/auth/login` when `g.user` is None
- `login_required` calls the wrapped function when `g.user` is set

**Account Settings service (`app/account_settings/services.py`):**
- `get_category_map` returns default map for a user with no saved preferences
- `get_category_map` returns saved map for a user who has one
- `save_category_map` upserts (second save overwrites first)

**Routes (integration tests via Flask test client):**
- `POST /auth/login` with valid credentials sets session and redirects to `/`
- `POST /auth/login` with invalid credentials re-renders form with error, no session set
- `GET /auth/logout` clears session and redirects to `/auth/login`
- `POST /upload` without a session redirects to `/auth/login` (login_required gate)
- All POST routes reject requests missing CSRF token (403)
