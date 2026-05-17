# Phase 2 Amendment A — Navigation, Landing Page, and Legacy Cleanup

**Status:** Draft — pending decisions (Gap 3 resolved: Option B confirmed)
**Date:** 2026-05-17
**Context:** Phase 2 shipped the Account Settings service, schema, routes, and templates. Manual review surfaced three gaps that block calling Phase 2 "done" against its roadmap exit criteria: (1) legacy references to `custom_categories.json` still live in the app factory, contradicting "the keyword JSON files are deprecated"; (2) the user-facing IA has no entry point to the new Categories UI, blocking "users can add, rename, and delete categories and keywords entirely through the UI"; (3) the default landing page (`/upload`) was inherited from Phase 0 and was never re-evaluated against the now-larger surface area.

This document is a **decision and planning artifact**, not an implementation spec. Each section names the problem, lays out options with trade-offs, and ends with a **Decision needed** prompt. The implementation tickets at the bottom should only be written once the decisions are made.

Governing ADRs: ADR-0004 (Blueprint layout), ADR-0005 (Category map DI), ADR-0009 (Schema normalization), ADR-0010 (Caching). New ADR likely required: ADR-0011 — Navigation and Landing Page Contract (see [Cross-cutting](#cross-cutting--does-this-warrant-an-adr)).

---

## Gap 1 — Legacy `custom_categories.json` references in the app factory

### What's there today

[app/__init__.py:102-103](app/__init__.py#L102-L103) loads two JSON files into app config at startup:

```python
app.config["CUSTOM_CATEGORY_MAP"] = _load_json("custom_categories.json")
app.config["GENERIC_CATEGORY_MAP"] = _load_json("generic_categories.json")
```

**Important distinction:**
- `GENERIC_CATEGORY_MAP` is **still active** — `seed_defaults` reads it on first login per [docs/phase2-contract.md](docs/phase2-contract.md) §2.11. Do not touch this load.
- `CUSTOM_CATEGORY_MAP` is **dead config** — nothing in the service layer reads it, and the contract explicitly states the import utility (`POST /account-settings/import`) is the only migration path for users with an existing custom file.

The roadmap exit criterion for Phase 2 says "the keyword JSON files are deprecated." That's specifically about the per-user custom file; the generic seed file stays.

### Options

| Option | What it means | Trade-off |
|---|---|---|
| **A. Delete the `CUSTOM_CATEGORY_MAP` config key** | Remove the load. Leave `generic_categories.json` and its config key untouched. | Cleanest. Forces the contract to be the only truth. Anything still referencing it breaks loudly. |
| **B. Keep loading, mark deprecated with a comment** | Add a `# DEPRECATED — remove in Phase 3` comment. | Avoids a coordinated cleanup but extends the lifetime of misleading code. Comments rot. |
| **C. Convert to a one-shot auto-import on first login** | If `custom_categories.json` exists at the repo root, auto-import it via `import_from_json` on first login, then set a sentinel. | Preserves the original "it just worked" UX, but contradicts the contract and adds hidden behavior. |

**Recommendation:** **A**, with a follow-up sub-decision on the file itself.

### Sub-question — what happens to `custom_categories.json` on disk?

- **A1.** Delete the file from the repo. Anyone who needs it gets it from git history.
- **A2.** Move it to `samples/custom_categories.example.json` so a new self-hosting user has something to feed the import UI.
- **A3.** Leave it in place but stop loading it.

**Recommendation:** **A2** — move it to `samples/` and update [README.md](README.md) to point at the import UI as the on-ramp.

### Verification step (must happen after this ticket)

Because Phase 2 changed the source of truth for category data (file → DB) and the upload page is currently the only working surface, end-to-end-test the upload flow once cleanup lands:
1. Log in as a fresh user → confirm `seed_defaults` populates from `GENERIC_CATEGORY_MAP`.
2. Upload a CSV → confirm the categorization output uses the DB-backed map, not the deleted file.
3. Edit a category via the new UI → re-upload the same CSV → confirm the new keyword is reflected.

### Decision needed

1. Pick A, B, or C for the config load.
2. If A, pick A1, A2, or A3 for the file on disk.

---

## Gap 2 — No UI entry point to Account Settings / Categories

### What's there today

[templates/base.html:11-22](templates/base.html#L11-L22) defines a header with two elements: the brand link (which always points at `transactions.upload`) and, if logged in, an email + sign-out link. There is no link to `/account-settings/categories`. The only way to reach the new UI is to type the URL by hand.

This directly blocks the Phase 2 exit criterion "users can add, rename, and delete categories and keywords entirely through the UI."

### The IA proposal in the user's notes

> "Settings" > "Categories", and then you can put some stubs for other pages. "Settings" > "Account Details" and "Settings" > "Budget"

Reasonable shape, but two questions inside it are load-bearing.

### Question 2a — should "Budget" live under Settings?

**Arguments for "Budget under Settings":**
- It's a configuration surface (budget targets, periods, thresholds). That's settings-shaped.
- Keeps the top-level nav simple while small.

**Arguments against:**
- Per [CLAUDE.md](CLAUDE.md) and [docs/architecture.md](docs/architecture.md), Budgeting is a **core module**, peer to Transactions. Burying it under Settings signals it's secondary.
- Phase 4 builds Budgeting as a first-class destination (actual-vs-budget views, drilldowns, proposed budgets). At that point Budget needs its own top-level entry, and we'll be re-doing the nav.
- Mixing "edit my preferences" with "view my financial picture" muddies the metaphor.

**Recommendation:** **Do not** put Budget under Settings. Budget is a peer destination. For Phase 2, leave it off the nav entirely (it doesn't exist yet); when Phase 4 starts, add it as a top-level item. Listing it as a stub under Settings now sets the wrong expectation and creates IA debt.

### Question 2b — Settings as dropdown vs. dedicated landing page

| Option | Description | Trade-off |
|---|---|---|
| **A. Dropdown menu in header** | `Settings ▾` opens a menu with `Categories`, `Account Details`. | Fastest path for power users. Requires JS or a CSS-only disclosure. Stubs become visible menu items immediately. |
| **B. `Settings` link → landing page** | Header has `Settings` link. The page is a list of sub-sections (cards or side nav). | No JS. Stubs can show as "Coming soon" cards without polluting a menu. Sub-section URLs are siblings (`/account-settings/categories`, `/account-settings/account`), matching the blueprint shape. Easier to extend. |
| **C. Hybrid** | Header link to landing page + a dropdown for power users. | Most flexible, most code, easy to drift out of sync. |

**Recommendation:** **B**. A `GET /account-settings/` index renders a settings landing page with cards for each sub-section. Cards link to `Categories` (live) and `Account Details` (stub). No dropdown, no JS, no Budget.

### Question 2c — what does the "Account Details" stub contain?

Bare minimum to be honest about what exists:
- The user's email (read from `g.user.email`).
- A "Sign out" button.
- A "More coming soon" placeholder block.

Anything beyond that (password change, delete account, email change) is a separate work item and probably an ADR-worthy surface — it touches Supabase Auth directly and has security implications.

### Decision needed

1. Confirm: **Budget is not under Settings.** It is a future top-level destination.
2. Pick dropdown (A), landing page (B), or hybrid (C) for Settings IA.
3. Confirm the minimal contents of the Account Details stub, or expand the scope.

---

## Gap 3 — Landing page choice (`/upload` is the default destination)

### What's there today

[app/__init__.py:144-156](app/__init__.py#L144-L156) registers `auth_bp`, `account_settings_bp`, and `transactions_bp`. The brand link in [templates/base.html:12](templates/base.html#L12) points at `transactions.upload`. After login (Phase 1), the user lands on `/upload`. This was correct in Phase 0 when "upload a CSV and get a report" was the entire product. It is no longer obviously correct.

### Why this needs a deliberate call now

In Phase 3, `/upload` is no longer the only way to see transactions — there will be a history view, persistence, and editing. In Phase 4 there's a budget view. If we leave `/upload` as the post-login destination through those phases, two things happen:
- New users land on a tool, not a dashboard, and have no sense of the product's shape.
- Every phase quietly debates "should the landing change yet?" without ever deciding.

Pinning a landing-page contract now — even a temporary one — means each phase changes it deliberately, with intent.

### Options for the Phase 2 landing page

| Option | Lands on | Pros | Cons |
|---|---|---|---|
| **A. Keep `/upload`** | The upload form. | Zero work. Matches today. | Doesn't reflect the now-larger surface. Sets the wrong tone going into Phase 3. |
| **B. New `/` dashboard, minimal** | A home page with cards: "Upload transactions," "Manage categories." | Establishes the dashboard pattern early. Each future module adds a card with no nav rework. Cheap (one template). | Adds a route and template. Slight redirect cost for habitual users — but one click through. |
| **C. Land on Transactions index (placeholder for Phase 3)** | A "Your transactions" page that in Phase 2 has no data — just an upload prompt. | Lines up with where Phase 3 takes us. | Half-baked in Phase 2; effectively `/upload` with extra chrome. Risk of throwaway work. |

**Decision (2026-05-17): Option B — minimal dashboard at `/`.** A minimal dashboard is the smallest commitment that establishes the right metaphor. It's two cards in a grid today. In Phase 3 the "Upload" card becomes "Transactions" with a count; in Phase 4 a "Budget" card joins. The dashboard grows without re-deciding the landing each phase.

### Sub-question — what is the brand link's destination?

If we go with B, the brand link in the header should point at the new dashboard, not `transactions.upload`. The post-login redirect in the auth flow needs the same change.

### Decision needed

1. ~~Pick A, B, or C for the landing page.~~ **Resolved: Option B.**
2. Open: confirm URL — `/` (root, recommended) or `/home` (explicit). Architect to pick when authoring ADR-0011.
3. Confirmed: the brand-link destination and the post-login redirect both move to the new landing.

---

## Gap 4 — Generic categories don't appear in the UI (behavior unverified)

### What we know

`GENERIC_CATEGORY_MAP` is loaded from `generic_categories.json` in [app/__init__.py:103](app/__init__.py#L103) and per [docs/phase2-contract.md](docs/phase2-contract.md) §2.11 is consumed by `seed_defaults` on first login. The expectation is: a brand-new user logs in, `seed_defaults` runs, the generic map is imported into their `categories` + `category_keywords` rows, and they show up in the Categories UI from then on.

### What the user observed

Generic categories are not visible in the UI for the current logged-in user. Unclear whether this is:
- A seeding bug (`seed_defaults` never ran, or ran with an empty map).
- A "user predates `seed_defaults`" issue (the current account was created in Phase 1 before `seed_defaults` existed, so it has no rows and nothing back-fills).
- Working as designed and the user's account simply has no categories yet because the seed never had anything to load (config not populated, file missing, etc.).
- A separate backend path that reads `GENERIC_CATEGORY_MAP` directly (e.g. as a fallback in the categorizer) that's masking the missing UI rows during upload.

### Investigation work item (not yet started — do not chase during this conversation)

Before Phase 2 closes, validate the full lifecycle of `GENERIC_CATEGORY_MAP`:

1. **Where is it read?** Grep the codebase for `GENERIC_CATEGORY_MAP`. Confirm `seed_defaults` is the only consumer. If anything else reads it (categorizer fallback, transaction engine), that's a finding — document it and decide whether that path is intended or vestigial.
2. **Does `seed_defaults` actually run?** Verify it's called at the right point in the auth flow (likely first-login, possibly every login as a no-op per the contract). Confirm via logs or a manual fresh-signup test that a new user's `categories` table is populated.
3. **What about existing accounts?** If the current account predates `seed_defaults`, decide the remediation: a one-shot back-fill on next login (idempotent — `seed_defaults` is a no-op if rows exist, so this needs a different trigger), a manual import via the import UI, or nothing (just document that pre-Phase-2 accounts need to use the import flow).
4. **Is `generic_categories.json` actually populated?** Confirm the file on disk has the expected map and that `_load_json` is finding it.

### Why this is in scope for Amendment A

This gap is adjacent to Gap 1 (legacy JSON cleanup) and shares the same risk surface: the boundary between file-backed and DB-backed category data. Cleaning up `CUSTOM_CATEGORY_MAP` without validating `GENERIC_CATEGORY_MAP` would mean shipping cleanup against an unverified seed path.

### Decision needed

None right now — this is an investigation item. The outcome of the investigation may produce a new ticket (e.g. "back-fill seed for pre-Phase-2 accounts") or simply a documentation update.

---

## Cross-cutting — does this warrant an ADR?

A new ADR (**ADR-0011 — Navigation and Landing Page Contract**) is the right shape if:
- We adopt the dashboard pattern (option B in Gap 3), since it sets a precedent every future phase will follow.
- We codify that Budget is a peer top-level module, not a Settings sub-page, since that contradicts the "stuff it under Settings" instinct that will keep coming up.

If both decisions land as recommended, **write ADR-0011 before opening implementation tickets.** The ADR is short — it just pins the contract: "Post-login lands on `/`. The header exposes top-level modules. Settings is itself a top-level module that contains configuration sub-pages. Cross-module destinations (Transactions, Budget) are top-level; configuration surfaces nest under Settings."

---

## Implementation tickets (draft — do not start until decisions above are made)

These are sized for individual implementation-agent runs. Each assumes decisions resolve to the recommendations above.

### Ticket 1 — Purge `CUSTOM_CATEGORY_MAP` from app factory
- Remove the `CUSTOM_CATEGORY_MAP` load from [app/__init__.py:102](app/__init__.py#L102). **Leave `GENERIC_CATEGORY_MAP` untouched.**
- Move `custom_categories.json` to `samples/custom_categories.example.json` (or delete; see decision).
- Update [README.md](README.md) to point at the import UI for users with an existing file.
- Grep the codebase and tests for any remaining `CUSTOM_CATEGORY_MAP` or `custom_categories.json` references and clean them up.
- Run the verification checklist in Gap 1 (login → seed → upload → edit → re-upload).

### Ticket 2 — Settings index page and nav
- Add `GET /account-settings/` route → renders a settings landing template.
- Template lists cards/links for "Categories" (live) and "Account Details" (stub).
- Add a stub `GET /account-settings/account` route + template showing email + a "More coming soon" block.
- Update [templates/base.html](templates/base.html) header to include a `Settings` link (visible only when authenticated).
- No JS. No dropdown. No Budget link.

### Ticket 3 — Dashboard landing page
- Add `GET /` route. Decide whether it belongs in a new `home_bp` blueprint or extends an existing one — flag for the architect agent per ADR-0004.
- Template: cards for Upload and Categories. Each is a plain link.
- Update [templates/base.html:12](templates/base.html#L12) brand link to point at the new landing.
- Update the post-login redirect in `app/auth/routes.py` to land on `/`.
- Update any tests that asserted `/upload` as the post-login destination.

### Ticket 4 — Validate generic-category seeding lifecycle (Gap 4)
- Grep for all consumers of `GENERIC_CATEGORY_MAP`; confirm `seed_defaults` is the only one (or document any other path).
- Verify `seed_defaults` actually fires for new signups and populates `categories`/`category_keywords` rows.
- Determine remediation for accounts that predate `seed_defaults` (back-fill on next login, manual import via UI, or documented as expected).
- Confirm `generic_categories.json` is present and non-empty.
- Output: a short findings note appended to this amendment (or a follow-up ticket if remediation work is needed).

### Ticket 5 — ADR-0011 — Navigation and Landing Page Contract
- Write **before** tickets 2 and 3. (Ticket numbering: this is now ticket 5; it still gates tickets 2 and 3.)
- Pin: post-login destination, top-level vs. Settings-nested classification rule, header composition rule, future-module expectations.
- Reference this amendment as the context document.

---

## Exit criteria for Amendment A

- [ ] `CUSTOM_CATEGORY_MAP` no longer loaded. `GENERIC_CATEGORY_MAP` still loaded and feeding `seed_defaults`. Sample file (if kept) lives under `samples/`. README updated.
- [ ] A logged-in user sees a `Settings` link in the header and can reach Categories from the UI without typing a URL.
- [ ] Account Details stub exists and is honest about what's coming.
- [ ] Landing-page decision recorded in ADR-0011 and reflected in code (route, brand link, post-login redirect all agree).
- [ ] Budget does **not** appear in the nav anywhere — deferred to Phase 4.
- [ ] End-to-end upload → categorize → edit → re-upload verified after legacy cleanup.
- [ ] Generic-category seeding lifecycle validated; findings recorded; remediation (if any) scoped.
- [ ] Phase 2 roadmap exit criteria can be checked off: "Users can add, rename, and delete categories and keywords entirely through the UI. The keyword JSON files are deprecated."

---

## Open questions parked for later (not blocking Phase 2)

- **Account Details scope:** password change, email change, account deletion all touch Supabase Auth directly. Each needs its own decision and likely an ADR.
- **Dashboard content beyond links:** counts, recent activity, anomalies — Intelligence-layer territory (Phase 5). The Phase 2 dashboard is intentionally inert.
- **Mobile nav:** the current header is desktop-shaped. A responsive treatment is a separate styling pass, not an IA decision.
