---
adr: 0006
title: Session Strategy — Cookie-Based Server-Side Sessions
status: Accepted
date: 2026-05-10
deciders: erin p
---

## Context

Phase 1 introduces authentication via Supabase Auth, which issues JWTs on sign-in. The app is server-rendered Flask running on a single Render instance. We need a session strategy that:

- Populates `g.user` on every request so routes can enforce `@login_required`
- Protects state-changing routes from CSRF
- Is consistent with the ADR-0002 constraint that Supabase-specific surface is confined to the auth integration module

Two broad options exist: store session state in a signed cookie (client-side) or store it server-side and hand the client an opaque session ID.

## Options considered

### Option A — Flask signed cookie (default Flask sessions)

Flask's default session stores a signed, tamper-proof cookie containing the session payload. With Supabase Auth, the JWT (or a subset of its claims) is serialized into the cookie.

**Pros:**
- Zero infrastructure. No Redis, no database table, no extra dependency.
- Stateless on the server — no session store to manage or expire.
- Flask-WTF's CSRF protection works out of the box against cookie sessions.

**Cons:**
- Cookie size grows with the JWT payload (~500–1000 bytes). Flask's 4 KB cookie limit is not a concern at this scale.
- Revoking a session requires either short expiry or a denylist table — cookie contents are valid until they expire, regardless of server-side state.
- The JWT is present in the cookie; if the signing secret is compromised, all sessions are compromised until the secret rotates.

### Option B — Server-side session store (Flask-Session + database)

An opaque session ID is stored in the cookie. The session payload (user ID, expiry, Supabase refresh token) lives in a `sessions` table or Redis.

**Pros:**
- Sessions can be revoked instantly by deleting the row.
- Cookie contains no sensitive claims — just an opaque ID.
- Enables "active sessions" management if added to the UI later.

**Cons:**
- Requires a `sessions` table (or Redis) and hit on every request.
- More moving parts for a single-user personal app at Phase 1 scale.
- Flask-Session adds a dependency and requires configuration.

### Option C — Token-based (JWT in Authorization header or localStorage)

The client stores the Supabase JWT and sends it as a Bearer token. Flask validates the JWT on each request.

**Pros:**
- Stateless; no session store needed.
- Natural fit if the app ever grows a separate API consumer (mobile, etc.).

**Cons:**
- Does not work for server-rendered pages without JavaScript plumbing to attach headers.
- localStorage tokens are vulnerable to XSS; cookie storage requires `httpOnly` and reintroduces cookie mechanics.
- CSRF is not a concern (no cookies) but XSS risk increases.
- Not a natural fit for Flask's `render_template` pattern.

## Decision

**Option A — Flask signed cookie sessions.**

For a server-rendered Flask app at personal-project scale, signed cookies are the right default. Session revocation is not a Phase 1 requirement (single user, no "log out all devices" feature). If revocation becomes needed, a lightweight denylist column on the `users` table can be added without changing the session strategy.

The Supabase JWT is **not** stored verbatim in the cookie. The cookie holds: `user_id` (UUID), `email`, and `expires_at` (UTC timestamp). The Supabase refresh token is stored server-side in the `user_sessions` table for token refresh, accessed only inside the auth integration module.

## What is now true about the system

1. Flask's built-in session (signed cookie, `SECRET_KEY`) is the session mechanism.
2. On successful Supabase Auth sign-in, the auth service writes `user_id`, `email`, and `expires_at` to `flask.session`. The Supabase refresh token is stored in `user_sessions` (see ADR-0007 for migration).
3. A `@login_required` decorator reads `flask.session["user_id"]` and populates `flask.g.user`. If the session is absent or expired, it redirects to `/auth/login`.
4. Flask-WTF provides CSRF protection on all state-changing routes. The CSRF token is validated server-side against the signed session. No exceptions for upload or any POST route.
5. Session expiry mirrors Supabase Auth's access token TTL (default 1 hour). The auth integration module handles silent refresh when the session nears expiry.
6. The `SECRET_KEY` is a 32-byte random value stored as an environment variable, never committed to source control.

## Consequences

- **Positive:** No Redis, no extra infrastructure. Works on Render free tier without changes.
- **Positive:** Flask-WTF CSRF integration is straightforward with cookie sessions.
- **Negative:** Sessions cannot be individually revoked without a denylist. Acceptable at Phase 1; revisit if multi-device logout becomes a requirement.
- **Follow-up:** The `user_sessions` table (for refresh token storage) must be included in the Phase 1 migration. See the implementation plan.
- **Follow-up:** `SECRET_KEY` rotation invalidates all active sessions. Document in the runbook.
