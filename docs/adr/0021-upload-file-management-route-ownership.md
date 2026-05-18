---
adr: 0021
title: Upload File Management Route Ownership — Transaction Engine Blueprint
status: Accepted
date: 2026-05-18
phase: P3b
deciders: erin
---

## Context

The Phase 3b UI redesign added a Files section to the Configure page that lists
uploaded files and lets the user delete them. The initial implementation placed
the delete route in `app/account_settings/routes.py` (the `account_settings_bp`
blueprint). This was a module boundary violation: uploads are Transaction Engine
data (`public.uploads`, ADR-0016); the service functions `get_uploads` and
`delete_upload` already live in `app/transactions/services.py`. Having account
settings own the mutation route for another module's table contradicts ADR-0003
(service-layer-only module communication) and ADR-0004 (blueprint ownership
follows module ownership).

Additionally, the initial implementation had a bug: `result.rowcount` was
checked outside the `with engine.begin()` context manager, making the rowcount
unreliable after the cursor closed.

## Options considered

### Option A — Keep routes in account_settings_bp, call transaction services

The delete route stays in `app/account_settings/routes.py`. Account Settings
imports `delete_upload` from the Transaction Engine service layer and calls it.

**Pros.** The Files section stays embedded on the Configure page; no navigation
change for the user.

**Cons.** Account Settings now owns a mutation route for Transaction Engine
data. This is exactly the cross-module coupling ADR-0003 prohibits at the route
layer. When a future developer searches for "who can delete uploads," they must
look in account settings, not transactions. Every new mutation on uploads would
face the same wrong-module question again.

### Option B — Move routes to transactions_bp, dedicated /files page

The list (`GET /files`) and delete (`POST /files/<id>/delete`) routes move to
`transactions_bp`. The Configure page is updated to show a "Files" card that
links to `/files`. The files page is standalone, owned entirely by the
Transaction Engine.

**Pros.** Clean ownership: the module that owns the data owns the routes. A
future developer looking for upload mutation finds it immediately in
`app/transactions/routes.py`. The `/files` URL is stable and independently
linkable. No cross-module route imports.

**Cons.** The user navigates from Configure → Files (one extra click). The
Files section is no longer embedded inline on Configure. Acceptable: the
primary use case (delete a bad upload) is infrequent, and the extra navigation
is a fair trade for clean ownership.

### Option C — Move routes to transactions_bp, keep embed in Configure

The Configure page renders the uploads table inline (still calls `get_uploads`
in the account_settings index route), but the delete form POSTs to a
`transactions_bp` route. Account Settings index still imports `get_uploads`.

**Pros.** No extra navigation click.

**Cons.** Account Settings still imports from Transaction Engine services for
read access. The Configure index route still has a DB call that silently
degrades (`except Exception: uploads = []`), hiding errors. The form action URL
straddling two blueprints is confusing.

## Decision

We will choose **Option B** — dedicated `/files` page owned entirely by
`transactions_bp`.

The two reasons that carried the decision: (1) ADR-0003 requires that the
module owning the data also owns the service interface; extending that principle
to routes makes ownership unambiguous and searchable; (2) the one-extra-click
cost is low relative to the long-term clarity gain, and the Configure page
retains a clear entry point via a Files card.

## Route contract

### `GET /files` (endpoint `transactions.files`)

Registered on `transactions_bp`. Auth-gated.

**Handler behavior:**

1. Call `get_uploads(user_id)` from `app/transactions/services`.
2. Render `templates/transactions/files.html` with `uploads` list.
3. No silent exception swallowing — if `get_uploads` raises (e.g., DB
   unavailable), let Flask's default error handler surface it. An empty list
   that silently hides a DB error is worse than a 500.

**Template contents:**

- Flash message block **above** the table so feedback is immediately visible
  after a delete redirect.
- Table columns: Filename | Uploaded (UTC) | Rows | Delete button.
- Empty state: "No files uploaded yet."

### `POST /files/<upload_id>/delete` (endpoint `transactions.files_delete`)

**Handler behavior:**

1. Parse `upload_id` as UUID. If invalid, return HTTP 400.
2. Call `delete_upload(user_id, UUID(upload_id))` from `app/transactions/services`.
3. On `UploadNotFound`: return HTTP 404. (The resource is gone; a flash
   redirect would mislead the user into thinking a delete occurred.)
4. On success: flash `"File deleted and all its transactions removed."` (category
   `success`) and redirect to `url_for("transactions.files")`.

**CSRF:** The POST route is protected by Flask-WTF's global CSRF middleware.
The template includes `<input type="hidden" name="csrf_token" value="{{ csrf_token() }}">`.

## Flash message conventions

| Outcome | Flash category | Message |
|---|---|---|
| Successful delete | `success` | "File deleted and all its transactions removed." |
| Upload not found | HTTP 404 | — |
| Invalid UUID | HTTP 400 | — |

## Configure page update

`GET /account-settings/` (`account_settings.index`) shows a "Files" card
linking to `url_for("transactions.files")`. It no longer embeds the uploads
table or calls `get_uploads`. The account settings index route reverts to a
simple `render_template("account_settings/index.html")` with no DB calls.

## Bug fix — `delete_upload` rowcount

The `UploadNotFound` check must occur **inside** the `with engine.begin()`
block, before the cursor closes:

```python
with engine.begin() as conn:
    result = conn.execute(text("DELETE ..."), params)
    if result.rowcount == 0:        # ← inside the block
        raise UploadNotFound(...)
```

## Consequences

- **Positive.** Upload management is fully contained in the Transaction Engine:
  schema (ADR-0016), service (`app/transactions/services.py`), and now routes
  (`app/transactions/routes.py`). Future changes to upload behavior have a
  single clear location.
- **Positive.** The Configure page is simpler: no DB call, no silent error
  swallowing, no cross-module import.
- **Positive.** The `/files` URL is independently linkable and bookmarkable.
  Flash messages appear above the table where they are immediately visible.
- **Negative.** One extra navigation click for the user (Configure → Files).
  Acceptable for an infrequent operation.
- **Follow-up.** The test-writer agent must exercise: (a) `get_uploads` scoping
  and ordering, (b) `delete_upload` cascade and `UploadNotFound`, (c) route
  auth, UUID validation, 404 on not-found, success redirect with flash.
- **Follow-up.** Remove `get_uploads`, `delete_upload`, `UploadNotFound` imports
  from `app/account_settings/routes.py` and the `delete_file` route.
