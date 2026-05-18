# Phase 2 — Account Settings Service Contract

This document is the binding contract for all Phase 2 implementation agents. It defines the service-layer API, error behavior, cache contract, and HTTP route shape that all four concurrent agents (backend CRUD, frontend UI, test-writer, JSON-import utility) must implement and test against.

No agent may change this contract unilaterally. Any deviation requires a new or amended ADR and a revision to this document.

**Governing ADRs:** ADR-0001 (UTC timestamps), ADR-0003 (service-layer-only cross-module calls), ADR-0004 (Flask blueprints), ADR-0005 (category map DI), ADR-0007 (Alembic migrations), ADR-0009 (schema normalization), ADR-0010 (request-scoped caching).

---

## 1. Schema (from ADR-0009)

### `public.categories`

```
id          UUID        PRIMARY KEY DEFAULT gen_random_uuid()
user_id     UUID        NOT NULL
name        TEXT        NOT NULL
created_at  TIMESTAMPTZ NOT NULL DEFAULT now()

UNIQUE (user_id, name)
INDEX idx_categories_user_id ON (user_id)
```

### `public.category_keywords`

```
id           UUID        PRIMARY KEY DEFAULT gen_random_uuid()
category_id  UUID        NOT NULL REFERENCES categories(id) ON DELETE CASCADE
keyword      TEXT        NOT NULL
created_at   TIMESTAMPTZ NOT NULL DEFAULT now()

UNIQUE (category_id, keyword)
INDEX idx_category_keywords_category_id ON (category_id)
```

`public.custom_categories` is dropped by migration 0002. It does not exist in Phase 2.

---

## 2. Service-Layer API

Module: `app/account_settings/services.py`

All functions in this module are the **only** permitted write path for category data. No other module, route handler, or utility script may issue INSERT, UPDATE, or DELETE against `public.categories` or `public.category_keywords` directly.

### 2.1 Cache contract (ADR-0010)

The cache lives in `flask.g._category_cache: dict[str, list[dict]]`, keyed by `user_id`.

- **Read path:** Check `g._category_cache.get(user_id)` before querying. On miss, query DB, populate cache, return result.
- **Write path:** After committing any mutation, call `g._category_cache.pop(user_id, None)`. The next read re-populates from DB.
- **Outside request context:** Fall through to a direct DB query. Do not raise; do not assume `g` is available. Use `from flask import has_request_context` to guard `g` access.

### 2.2 Shared types

```python
CategoryRow = dict  # {id: str, name: str, keywords: list[str]}
KeywordRow  = dict  # {id: str, keyword: str}
```

`id` values in return dicts are UUIDs serialized as lowercase hex strings with hyphens (standard UUID string format). Route handlers must not assume numeric IDs.

### 2.3 Function signatures and behavior

---

#### `get_category_map(user_id: str) -> dict[str, list[str]]`

Returns the user's full category map as `{category_name: [keyword, ...]}`, ordered by category name ascending. This is the shape the Transaction Engine and `make_categorizer` consume (ADR-0005).

Behavior:
- Derives its result from `list_categories(user_id)` — does not issue a separate DB query if the cache is already warm.
- If the user has no categories yet, returns `{}`. Does **not** auto-seed; callers that need seeding must call `seed_defaults` explicitly (see section 2.11).
- Returns a new dict on every call; callers may mutate the return value without affecting the cache.

Cache: read-through via `list_categories`. Cache invalidation is inherited from whatever mutation last ran.

Errors: none beyond DB connectivity errors (propagated as-is).

---

#### `save_category_map(user_id: str, category_map: dict[str, list[str]]) -> None`

Bulk-replaces the user's entire category set with the provided map. Equivalent to `import_from_json` (see 2.10); kept for backward compatibility and used by the import utility.

Behavior:
- Deletes all existing `categories` rows for `user_id` (keywords cascade via `ON DELETE CASCADE`).
- Inserts new `categories` and `category_keywords` rows from the provided map.
- Normalizes category names (strip whitespace) and keywords (strip whitespace, lowercase) before insertion.
- Deduplicates keywords within a category before insertion; silently drops duplicates.
- Runs inside a single transaction: either the full replace succeeds or the old data is unchanged.
- Invalidates the cache for `user_id`.

Errors:
- `ValueError` if `category_map` is not a dict.

Note: this function will be deprecated for the CRUD UI in favor of the granular methods below, but it is the authoritative implementation for bulk import and must remain stable through at least Phase 3.

---

#### `list_categories(user_id: str) -> list[CategoryRow]`

Returns all categories for the user, each with their keywords, ordered by `name` ascending.

```python
# Return shape
[
    {"id": "...", "name": "Food", "keywords": ["LOBLAWS", "METRO", "SOBEYS"]},
    {"id": "...", "name": "Transport", "keywords": ["PRESTO", "UBER"]},
    ...
]
```

Behavior:
- Cache-aware: returns from `g._category_cache[user_id]` if present; otherwise queries DB and populates cache.
- Returns `[]` if the user has no categories.
- Keywords within each category are ordered alphabetically.

Errors: none beyond DB connectivity.

---

#### `create_category(user_id: str, name: str) -> CategoryRow`

Inserts a new category for the user. Returns the created row.

```python
# Return shape
{"id": "...", "name": "Groceries", "keywords": []}
```

Behavior:
- Normalizes `name`: strip leading/trailing whitespace, collapse internal whitespace to a single space.
- Raises `ValueError("Category name cannot be empty")` if normalized name is empty.
- Raises `ValueError(f"Category '{name}' already exists")` if a category with the same normalized name already exists for this user. Case-sensitive match at the DB level (the `UNIQUE (user_id, name)` constraint). The service layer does not perform case-folding for uniqueness — two categories named "Food" and "food" are distinct at the DB layer but the UI should warn against this.
- Invalidates cache for `user_id`.

Errors: `ValueError` for name conflicts or empty names.

---

#### `rename_category(user_id: str, category_id: str, new_name: str) -> CategoryRow`

Renames a category. Returns the updated row (without keywords, since they are unchanged).

```python
# Return shape
{"id": "...", "name": "Dining Out"}
```

Behavior:
- Validates ownership: the category identified by `category_id` must belong to `user_id`. If not, raises `ValueError("Category not found")`. Do not reveal whether the category_id exists at all for other users.
- Normalizes `new_name` the same way as `create_category`.
- Raises `ValueError("Category name cannot be empty")` if normalized name is empty.
- Raises `ValueError(f"Category '{new_name}' already exists")` if `new_name` conflicts with an existing category for the user (same uniqueness semantics as `create_category`).
- Raises `ValueError("Category not found")` if `category_id` does not exist for `user_id`.
- Invalidates cache for `user_id`.

Errors: `ValueError` for ownership failure, name conflicts, or empty names.

---

#### `delete_category(user_id: str, category_id: str) -> None`

Deletes a category and all its keywords.

Behavior:
- Validates ownership: raises `ValueError("Category not found")` if `category_id` does not belong to `user_id`.
- Keywords are deleted automatically via `ON DELETE CASCADE`; the service does not need to issue a separate DELETE on `category_keywords`.
- Invalidates cache for `user_id`.

Errors: `ValueError` if category does not belong to user.

---

#### `add_keyword(user_id: str, category_id: str, keyword: str) -> KeywordRow`

Adds a keyword to an existing category.

```python
# Return shape
{"id": "...", "keyword": "LOBLAWS"}
```

Behavior:
- Validates ownership: `category_id` must belong to `user_id`. Raises `ValueError("Category not found")` if not.
- Normalizes `keyword`: strip whitespace, convert to uppercase. (Uppercase matches the categorization engine's behavior — `make_categorizer` uppercases descriptions before matching.)
- Raises `ValueError("Keyword cannot be empty")` if normalized keyword is empty.
- Raises `ValueError(f"Keyword '{keyword}' already exists in this category")` if the normalized keyword already exists in this category. Match is case-sensitive after normalization (both are uppercase, so this is effectively exact-match).
- Invalidates cache for `user_id`.

Errors: `ValueError` for ownership failure, empty keyword, or duplicate keyword.

---

#### `remove_keyword(user_id: str, category_id: str, keyword_id: str) -> None`

Removes a keyword from a category.

Behavior:
- Validates that `category_id` belongs to `user_id`. Raises `ValueError("Category not found")` if not.
- Validates that `keyword_id` belongs to `category_id`. Raises `ValueError("Keyword not found")` if not.
- Deletes the keyword row.
- Invalidates cache for `user_id`.

Errors: `ValueError` for ownership failures.

---

#### `import_from_json(user_id: str, category_map: dict[str, list[str]]) -> None`

Bulk-loads a category map (same shape as `get_category_map` output). Replaces the user's current categories and keywords entirely.

Behavior:
- Identical to `save_category_map` in behavior. `import_from_json` is the public-facing name used by the import utility route; `save_category_map` is the backward-compatible name used internally and by the Transaction Engine integration.
- Idempotent: calling twice with the same map produces the same result as calling once.
- Validates that `category_map` is a dict with string keys and list-of-string values. Raises `ValueError("Invalid category map format")` otherwise.
- Normalizes names and keywords (same normalization as granular methods above).
- Deduplicates keywords within each category before insertion.
- Runs inside a single transaction.
- Invalidates cache for `user_id`.

Errors: `ValueError` for format violations.

---

#### `seed_defaults(user_id: str) -> None`

Called on first login if the user has no categories. Loads the generic map and calls `import_from_json`.

Behavior:
- Checks whether the user has any rows in `public.categories`. If yes, returns immediately (no-op).
- If no rows exist, loads the generic category map from `current_app.config["GENERIC_CATEGORY_MAP"]`.
- Calls `import_from_json(user_id, generic_map)`.
- This function is a no-op if called on a user who already has categories, making it safe to call on every login without a separate "has this run?" flag.
- The `_SEED_FILE` fallback (`custom_categories.json`) is **deprecated** as of Phase 2. `seed_defaults` does not consult the file. The import utility (`import_from_json`) is the migration path for users who have a `custom_categories.json` they want to preserve.

Errors: none beyond DB connectivity. If `GENERIC_CATEGORY_MAP` is not configured, seeds with an empty map (no categories).

---

### 2.4 Ownership validation rule

Every function that accepts a `category_id` or `keyword_id` must validate ownership before performing any mutation or returning sensitive data. The validation query pattern is:

```sql
-- For category ownership:
SELECT id FROM public.categories WHERE id = :category_id AND user_id = :user_id

-- For keyword ownership (validates both category and keyword):
SELECT ck.id
FROM public.category_keywords ck
JOIN public.categories c ON c.id = ck.category_id
WHERE ck.id = :keyword_id AND c.user_id = :user_id
```

If the query returns no rows, raise `ValueError` with the message documented per function. Do not distinguish "ID does not exist" from "ID belongs to another user" in error messages — both return "not found."

---

## 3. HTTP Route Contract

Blueprint: `account_settings_bp`, registered at `/account-settings` (ADR-0004).

All routes require an authenticated user. The existing session middleware enforces this; routes do not need to re-check authentication. The session provides `user_id` (a UUID string) accessible as `session["user_id"]` or via whatever auth helper is established by the Phase 1 implementation.

All mutating routes (POST) follow the Post-Redirect-Get pattern: on success, redirect to the appropriate listing or detail page. On validation error, re-render the form with error messages.

All POST routes are protected by CSRF tokens (Flask-WTF or equivalent, already established in Phase 1).

### Route table

| Method | Path | Handler name | Description |
|---|---|---|---|
| GET | `/account-settings/categories` | `categories_list` | List all categories with their keywords |
| GET | `/account-settings/categories/new` | `categories_new` | Render blank new-category form |
| POST | `/account-settings/categories` | `categories_create` | Create a category; redirect to list on success |
| GET | `/account-settings/categories/<category_id>/edit` | `categories_edit` | Render edit form (rename + manage keywords) |
| POST | `/account-settings/categories/<category_id>` | `categories_update` | Rename category; redirect to edit page on success |
| POST | `/account-settings/categories/<category_id>/delete` | `categories_delete` | Delete category; redirect to list on success |
| POST | `/account-settings/categories/<category_id>/keywords` | `keywords_add` | Add keyword; redirect to edit page on success |
| POST | `/account-settings/categories/<category_id>/keywords/<keyword_id>/delete` | `keywords_remove` | Remove keyword; redirect to edit page on success |
| GET | `/account-settings/import` | `import_form` | Render JSON file upload form |
| POST | `/account-settings/import` | `import_upload` | Process uploaded JSON; redirect to list on success |

### Route detail

#### `GET /account-settings/categories`

Calls `list_categories(user_id)`. Renders a template that shows each category name and its keywords. Provides links to edit and delete each category, and a link to create a new category.

Template variable: `categories` — the list returned by `list_categories`.

#### `GET /account-settings/categories/new`

Renders a form with a single text input for the category name.

#### `POST /account-settings/categories`

Form field: `name` (text).

Calls `create_category(user_id, name)`. On success, redirects to `GET /account-settings/categories`. On `ValueError`, re-renders the new-category form with the error message.

#### `GET /account-settings/categories/<category_id>/edit`

Calls `list_categories(user_id)` and finds the category matching `category_id`. If the category does not belong to the user (or does not exist), returns HTTP 404.

Renders a form with: current category name (editable), list of current keywords (each with a remove button), and a text input to add a new keyword.

Template variables: `category` (a `CategoryRow`).

#### `POST /account-settings/categories/<category_id>`

Form field: `name` (text).

Calls `rename_category(user_id, category_id, name)`. On success, redirects to `GET /account-settings/categories/<category_id>/edit`. On `ValueError` indicating ownership failure, returns HTTP 404. On `ValueError` indicating name conflict or empty name, re-renders the edit form with the error message.

#### `POST /account-settings/categories/<category_id>/delete`

No form fields (beyond the CSRF token).

Calls `delete_category(user_id, category_id)`. On success, redirects to `GET /account-settings/categories`. On `ValueError` indicating ownership failure, returns HTTP 404.

#### `POST /account-settings/categories/<category_id>/keywords`

Form field: `keyword` (text).

Calls `add_keyword(user_id, category_id, keyword)`. On success, redirects to `GET /account-settings/categories/<category_id>/edit`. On `ValueError` indicating ownership failure, returns HTTP 404. On `ValueError` indicating duplicate or empty keyword, re-renders the edit form with the error message.

#### `POST /account-settings/categories/<category_id>/keywords/<keyword_id>/delete`

No form fields (beyond the CSRF token).

Calls `remove_keyword(user_id, category_id, keyword_id)`. On success, redirects to `GET /account-settings/categories/<category_id>/edit`. On `ValueError` indicating ownership failure (either category or keyword), returns HTTP 404.

#### `GET /account-settings/import`

Renders a file upload form. The form accepts a JSON file. Includes a note that importing will replace all existing categories and keywords.

#### `POST /account-settings/import`

Form field: `file` (file upload, `.json`).

Reads the uploaded file, parses it as JSON. On parse failure, re-renders the import form with an error message ("File is not valid JSON"). Validates the parsed data is a dict with string keys and list-of-string values; on format failure, re-renders with an error message. On valid input, calls `import_from_json(user_id, category_map)`. On success, redirects to `GET /account-settings/categories`. On `ValueError` from the service, re-renders the import form with the error message.

Maximum file size: 1 MB. Enforce via Flask's `MAX_CONTENT_LENGTH` or a manual size check before parsing. Return HTTP 413 if exceeded.

---

## 4. Error handling conventions

- Service-layer `ValueError` messages are safe to surface directly to the user in the UI. They do not contain system internals, stack traces, or other users' data.
- DB connectivity errors (SQLAlchemy `OperationalError`, etc.) are not caught by service functions; they propagate to the route handler, which lets Flask's error handler return HTTP 500. The Sentry integration (Phase 1) captures these.
- No route handler should expose a raw exception message to the user. The error handler must render a generic error page for unhandled exceptions.

---

## 5. Normalization rules (canonical reference)

These rules must be applied consistently in the service layer before any DB insert or comparison:

| Field | Rule |
|---|---|
| Category name | Strip leading/trailing whitespace. Collapse internal runs of whitespace to a single space. Do not change case. |
| Keyword | Strip leading/trailing whitespace. Convert to uppercase. |

The reason keywords are uppercased: the categorization engine (`make_categorizer`) uppercases transaction descriptions before matching. Storing keywords in uppercase ensures the matching behavior in the DB-backed path is identical to the file-backed path.

---

## 6. Inter-agent responsibilities

| Agent | Owns | Must not touch |
|---|---|---|
| Backend CRUD | `services.py`, `routes.py`, migration `0002_normalize_categories.py` | Templates, test files |
| Frontend UI | Jinja2 templates under `app/account_settings/templates/` | Service layer, migration files |
| Test-writer | All test files under `tests/account_settings/` | Service layer, templates, migration files |
| JSON-import utility | The `import_from_json` and `seed_defaults` service functions (consumption only, not modification) and the `import_form`/`import_upload` routes | Schema, other service functions |

The migration write-lock (ADR-0007) means only the backend CRUD agent authors `0002_normalize_categories.py`. All other agents work against the contract defined here; they do not need the migration to be applied to start work (use mocks or a test database fixture).

---

## 7. What the Transaction Engine reads (cross-module contract)

The Transaction Engine reads category data exclusively through `get_category_map(user_id)`. It receives `{category_name: [keyword, ...]}` and passes it to `make_categorizer` (ADR-0005). The Transaction Engine does not know about individual category IDs or the relational structure.

This interface is stable for Phase 3. Any change to `get_category_map`'s return shape requires a new ADR.
