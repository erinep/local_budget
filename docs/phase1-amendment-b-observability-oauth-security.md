# Phase 1 Amendment B — Observability, Google OAuth, and Security Audit

**Status:** In Progress (See Item 3-4)  
**Date:** 2026-05-10  
**Context:** After Amendment A closes the five auth-flow gaps, the following Phase 1 and Phase 1.5 work items remain before Phase 2 can begin. This document tracks them in priority order.

---

## Item 1 — Sentry error tracking

**Why it's here:** Explicitly listed in the Phase 1 roadmap. A stub was wired into `app/__init__.py` during Phase 0 with a comment "Activated in Phase 1". It is still commented out.

**What to do:**

1. Add `sentry-sdk[flask]` to `requirements.txt`.

2. Uncomment and complete the Sentry block in `app/__init__.py`:

```python
sentry_dsn = os.environ.get("SENTRY_DSN", None)
if sentry_dsn:
    import sentry_sdk
    from sentry_sdk.integrations.flask import FlaskIntegration
    sentry_sdk.init(
        dsn=sentry_dsn,
        integrations=[FlaskIntegration()],
        traces_sample_rate=0.1,
        send_default_pii=False,   # never send PII to Sentry
    )
```

3. Set `SENTRY_DSN` in Render environment variables (get the DSN from the Sentry project settings).

4. Add `SENTRY_DSN` to the `.env.example` file (value blank) so future contributors know to set it.

**Acceptance:** Intentionally trigger a `1/0` error on a local dev route, verify the event appears in the Sentry dashboard.

---

## Item 2 — JSON structured logging

**Why it's here:** Phase 0 roadmap specified "Python `logging` with a JSON formatter". The `PIIScrubber` filter was added correctly, but the formatter in `app/__init__.py` (line 112-114) uses a plain-text format string, not JSON. This makes log parsing brittle in Render's log aggregator and any future log-forwarding tool.

**What to do:**

Replace the `logging.Formatter` in `create_app()` with a JSON formatter. The existing `PIIScrubber` filter should be kept — it attaches to the handler, not the formatter, so the two are independent.

```python
import json as _json

class _JSONFormatter(logging.Formatter):
    def format(self, record):
        self.format(record)  # fills in exc_text etc.
        return _json.dumps({
            "time":    self.formatTime(record, self.datefmt),
            "level":   record.levelname,
            "logger":  record.name,
            "message": record.getMessage(),
            **({"exc": self.formatException(record.exc_info)} if record.exc_info else {}),
        })
```

Alternatively, use `python-json-logger` (a lightweight, well-maintained package) to avoid rolling a custom formatter:

```python
from pythonjsonlogger import jsonlogger
handler.setFormatter(jsonlogger.JsonFormatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
```

Either approach satisfies the requirement. Prefer `python-json-logger` to avoid maintaining a custom formatter.

**Acceptance:** Start the dev server, make a request, confirm the log line is valid JSON with `time`, `level`, `logger`, and `message` fields.

---

## Item 3 — Google OAuth (Phase 1.5)

**Why it's here:** Deferred from Phase 1 per ADR-0008. This is its own thin vertical slice. No schema changes are required — Supabase Auth handles the OAuth identity internally.

**What to do:**

### 3a. Google Cloud Console setup (manual, one-time)

1. Create (or reuse) a Google Cloud project.
2. Enable the Google Identity API.
3. Create an OAuth 2.0 client ID with the authorized redirect URI:  
   `https://your-app.onrender.com/auth/callback` (Supabase handles this, so the exact URL is the one in Supabase → Authentication → Providers → Google).
4. Copy the Client ID and Client Secret into Supabase → Authentication → Providers → Google.

### 3b. New service function in `app/auth/services.py`

```python
def sign_in_with_google() -> str:
    """Initiate Google OAuth sign-in.

    Returns the Supabase OAuth redirect URL. The caller redirects the user
    to this URL; Supabase handles the Google handshake and calls back to
    /auth/callback with a code and state parameter.

    Raises AuthError on failure.
    """
```

Implementation: `supabase.auth.sign_in_with_oauth({"provider": "google", "options": {"redirect_to": CALLBACK_URL}})`

### 3c. New routes in `app/auth/routes.py`

```
GET /auth/google
    → call sign_in_with_google()
    → redirect to the returned OAuth URL

GET /auth/callback?code=...&state=...
    → Supabase exchanges the code for a session automatically via the JS SDK,
      but the Python server-side approach uses the implicit flow:
      the redirect comes back with an access_token in the URL fragment (#).
    → The simpler Supabase Python approach: exchange via
      supabase.auth.exchange_code_for_session({"auth_code": code})
    → Write the session with _write_session()
    → Redirect to transactions.upload
```

**Note on the callback:** Supabase's Python SDK v2 supports PKCE. The callback URL receives `code` as a query parameter (not a fragment hash), which can be exchanged server-side. This is the approach to use — it avoids any JavaScript dependency.

### 3d. Template update

Add a "Sign in with Google" button to `login.html` and `signup.html` pointing to `url_for('auth.google_login')`.

**Acceptance:** Sign in with a Google account, land on the upload page, verify `user_id` is in the Flask session.

---

## Item 4 — Security audit (gate before Phase 2)

**Why it's here:** The risks register rates "Auth implementation has security flaws" as Medium likelihood / Very High impact, and explicitly calls for a security review before public launch. This is the right checkpoint: auth is fully implemented and manual testing has passed, but Phase 2 has not started yet.

**Scope:** Auth surface only. This is not a full penetration test — it is a structured code review against a checklist. A reviewer agent can execute most of this; the manual items are called out.

### Checklist

**Session & cookies**
- [ ] `SESSION_COOKIE_HTTPONLY = True` is set (prevents JavaScript access to the session cookie)
- [ ] `SESSION_COOKIE_SAMESITE = "Lax"` is set (CSRF defense in depth on top of Flask-WTF)
- [ ] `SESSION_COOKIE_SECURE = True` is set in production (HTTPS only)
- [ ] `SECRET_KEY` is a high-entropy random value in production (not the dev fallback)
- [ ] `reset_access_token` is popped from the session immediately after a successful password update

**CSRF**
- [ ] Every POST, PUT, PATCH, DELETE route has CSRF protection enabled
- [ ] The CSRF test suite passes with `WTF_CSRF_ENABLED = True`
- [ ] `WTF_CSRF_ENABLED = False` appears only in test fixtures, never in production config

**Auth flows**
- [ ] Login with wrong credentials returns 401 (not 200 with an error message only)
- [ ] Signup with an already-registered email returns a generic error (no user enumeration)
- [ ] Password reset confirmation is shown regardless of whether the email is registered (no enumeration)
- [ ] `/auth/update-password` without a valid `reset_access_token` in session redirects (not 500)
- [ ] All transaction routes redirect unauthenticated requests to `/auth/login`

**Tokens & storage**
- [ ] Refresh tokens are stored server-side in `user_sessions`, never in the cookie
- [ ] `access_token` is never written to the Flask session except for the short-lived `reset_access_token` (which is scoped to the password-reset flow only)
- [ ] PII scrubber is active — no email addresses or amounts appear in log output
- [ ] Sentry is configured with `send_default_pii=False`

**Dependencies**
- [ ] `sentry-sdk`, `supabase`, `flask-wtf`, `sqlalchemy`, `psycopg2` are pinned to specific versions in `requirements.txt`
- [ ] No known CVEs in any dependency at the versions pinned (run `pip-audit` or check PyPI advisories)

**Manual checks**
- [ ] Open the browser devtools → Application → Cookies; confirm the session cookie has `HttpOnly` and `Secure` flags set in production
- [ ] Confirm Render is serving the app over HTTPS only (HTTP → HTTPS redirect is on)
- [ ] Attempt to replay a logged-out session cookie — confirm the app rejects it

**Outcome:** A written pass/fail against every checklist item. Any fail is a blocker for Phase 2. Minor findings (informational, not exploitable) are logged in `docs/risks.md` with a mitigation plan.

---

## Implementation order

1. Sentry integration (Item 1) — low effort, high safety value
2. JSON structured logging (Item 2) — low effort, finishes the Phase 0 logging spec
3. Google OAuth (Item 3) — self-contained Phase 1.5 vertical slice
4. Security audit (Item 4) — gate; nothing merges to Phase 2 until this passes

---

## Exit criteria for Amendment B

- [X] Sentry receives error events from the production app
- [ ] Log lines are valid JSON with no PII visible
- [ ] A user can sign up and sign in with a Google account
- [ ] All security checklist items are checked; blockers resolved
- [ ] Phase 1 is marked **Shipped** in `docs/roadmap.md` and `CLAUDE.md`
