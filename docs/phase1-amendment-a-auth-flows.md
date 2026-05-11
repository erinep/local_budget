# Phase 1 Amendment A — Auth Flow Fixes and UI Polish

**Status:** In progress  
**Date:** 2026-05-10  
**Context:** After deploying the Phase 1 implementation, five gaps were found through manual testing. This amendment tracks the fixes before Phase 1 is considered done.

---

## Gap 1 — Sign-in always shows an error page (blocker)

**Root cause:** `_write_session` calls `store_refresh_token`, which hits the `user_sessions` DB table. That table doesn't exist until `alembic upgrade head` is run. Every login attempt throws a SQLAlchemy error → Flask 500 page.

**Fixes required:**

1. **Run the migration.** `alembic upgrade head` with `DATABASE_URL` set. This must happen before any other fix can be tested. On Render: add a release command or run it manually via the shell tab.

2. **Make `_write_session` fail gracefully.** Even after the migration runs, a future DB hiccup should not block the user from logging in. The refresh-token DB write is a best-effort enhancement (silent refresh), not a hard requirement for a functional session. Wrap `store_refresh_token` in a try/except that logs the error and continues:

```python
def _write_session(auth_session) -> None:
    session.clear()
    session["user_id"] = auth_session.user.id
    session["email"] = auth_session.user.email
    session["expires_at"] = auth_session.expires_at.isoformat()
    try:
        store_refresh_token(
            auth_session.user.id,
            auth_session.refresh_token,
            auth_session.expires_at,
        )
    except Exception:
        logger.warning("Could not persist refresh token; silent refresh will not be available.")
```

---

## Gap 2 — No logout button in the UI

**Root cause:** The logout route (`GET /auth/logout`) exists and works, but there is no link to it anywhere in the templates. Users have no way to log out.

**Fix:** Update `base.html` to show a logout link in the header when the user is authenticated. `g.user` is available in all templates via the `load_user` before-request hook.

```html
<header class="site-header">
    <a class="brand" href="{{ url_for('transactions.upload') }}">
        <span class="brand-mark">BP</span>
        <span class="brand-text">Budget Parser</span>
    </a>
    {% if g.user %}
    <nav class="site-nav">
        <span class="nav-email">{{ g.user.email }}</span>
        <a class="nav-link" href="{{ url_for('auth.logout') }}">Sign out</a>
    </nav>
    {% endif %}
</header>
```

---

## Gap 3 — Password reset flow is incomplete

**Root cause:** `POST /auth/reset-password` sends a Supabase reset email. The email contains a link back to the app (configured via Supabase → Authentication → URL Configuration → Redirect URLs). That link carries a `token_hash` and `type=recovery` as query parameters. The app has no route to handle this callback, so users land on a 404.

**Fix:** Add two things:

### 3a. Supabase configuration
In Supabase dashboard → Authentication → URL Configuration:
- **Site URL:** set to the Render app URL (e.g. `https://your-app.onrender.com`)
- **Redirect URLs:** add `https://your-app.onrender.com/auth/update-password`

In Supabase dashboard → Authentication → Email Templates → Reset Password, the link should point to `{{ .SiteURL }}/auth/update-password?token_hash={{ .TokenHash }}&type=recovery`.

### 3b. New route: `GET /auth/update-password` and `POST /auth/update-password`

```
GET  /auth/update-password?token_hash=...&type=recovery
     → verify the OTP token with Supabase
     → if valid: render a "set new password" form, store token_hash in session
     → if invalid/expired: render error with link back to /auth/reset-password

POST /auth/update-password
     → read new password from form
     → call supabase.auth.update_user(password=new_password) with the verified session
     → on success: redirect to /auth/login with a success flash message
     → on failure: re-render form with error
```

**New service function to add to `app/auth/services.py`:**

```python
def verify_recovery_token(token_hash: str) -> AuthSession:
    """Exchange a password-reset token_hash for an active session.
    Raises AuthError if the token is invalid or expired."""

def update_password(access_token: str, new_password: str) -> None:
    """Set a new password for the user identified by access_token.
    Raises AuthError on failure."""
```

---

## Gap 4 — Seeding from `custom_categories.json` needs verification

**Root cause:** `get_category_map` is supposed to seed from `custom_categories.json` on first login if no DB row exists for the user. This has not been tested against a real database.

**Fix:** Manual verification step — after the migration runs and login works:
1. Log in for the first time
2. Check the `custom_categories` table in Supabase: a row should exist for your `user_id`
3. Confirm the `category_map` JSONB column contains the contents of `custom_categories.json`

If seeding is not working, the fix is in `app/account_settings/services.py` in `_load_seed_map()`.

---

## Gap 5 — UI is unstyled and hard to use

**Root cause:** Templates use semantic CSS class names but the stylesheet (`static/styles.css`) has minimal or no styles for the auth pages. Auth forms are legible but visually rough.

**Scope:** Light pass only — not a redesign. Goals:
- Auth forms (`login.html`, `signup.html`, `reset_password.html`, `update_password.html`) are centered and readable on all screen sizes
- Error and success messages are visually distinct
- The logout link in the header is clearly visible
- The upload page and report page are not regressed

**Approach:** Extend the existing `styles.css` rather than introducing a CSS framework. The existing file already defines classes (`auth-card`, `auth-title`, `auth-error`, `btn-primary`, etc.) — they just need values.

---

## Implementation order

1. Run migration (Gap 1, step 1) — **prerequisite for everything**
2. Fix `_write_session` error handling (Gap 1, step 2)
3. Add logout button to `base.html` (Gap 2)
4. Add `update_password` route and service functions (Gap 3)
5. Configure Supabase URL settings (Gap 3a)
6. Verify seeding (Gap 4) — manual check, fix only if broken
7. CSS pass on auth pages (Gap 5)

---

## Exit criteria for Amendment A

- [ ] A user can sign up, land on the upload page, and use the app
- [ ] A user can log out and be redirected to the login page
- [ ] A user who forgot their password can reset it end-to-end without hitting a 404
- [ ] On first login, `custom_categories` table has a row with the user's category map
- [ ] Auth pages are readable and not embarrassing
