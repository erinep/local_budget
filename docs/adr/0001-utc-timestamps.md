# ADR 0001 - UTC Timestamps

- **Status:** Accepted
- **Date:** 2026-05-10
- **Phase:** All
- **Deciders:** Architect agent

## Context

Every module in this system produces or consumes timestamps: the Transaction Engine records when a transaction was imported and what date the bank reported; the Budgeting Module closes period boundaries; the Intelligence Layer fires alerts and stores insight artifacts; the audit log records sensitive user actions. A personal finance application is particularly sensitive to timezone mistakes — a transaction recorded at 11:45 PM local time may fall in the previous calendar day in UTC, and a budget period that opens at midnight has a different meaning depending on which midnight you mean.

Users may live in different timezones, travel, or change their timezone preferences after data is already stored. If timestamps are stored in any format other than UTC, historical data becomes ambiguous the moment the user's local time changes. This risk is called out explicitly in [risks.md](../risks.md) ("Timezone handling drift between upload and storage") and the CLAUDE.md constraint section names it as non-negotiable.

This ADR formalizes the convention so that every module author, every agent, and every future contributor has a single document to point to.

## Options considered

### Option A - Store all timestamps in UTC, convert only at render time

All timestamps are stored as UTC in the database. Conversion to the user's local timezone happens exactly once, in a single rendering utility, at the point where a timestamp is formatted for display in the UI or included in a user-facing API response. Everywhere else in the codebase — service layer, background jobs, comparisons, period arithmetic — timestamps are UTC datetime objects.

**Pros:**
- Storage is unambiguous. Every row means exactly one moment in time regardless of when or where it was written.
- Period boundary arithmetic (e.g., "all transactions in March") is deterministic: convert the period boundaries to UTC once, then query.
- DST transitions do not affect stored data or inter-module comparisons.
- No per-row metadata is needed; the convention is implicit in the column type.
- Consistent with PostgreSQL's `TIMESTAMPTZ` semantics, which stores UTC internally regardless of the session timezone.

**Cons:**
- Developers must remember to convert at render time and not earlier. A timestamp displayed raw without conversion will show the wrong local time to the user.
- Importing CSV bank exports that carry local times requires a documented parse step that applies a timezone assumption before the value is stored.

**Consequences:**
- One utility function or class is the only permitted site for UTC-to-local conversion. All routes and templates call it; nothing else does.

### Option B - Store local time alongside UTC (dual storage)

Each timestamp column has a UTC counterpart and a local-time counterpart. The local-time column stores the user's rendering-time value at the moment of write.

**Pros:**
- Queries that need the local date for display can read it directly without a conversion step.
- Reporting on "calendar day" aligns with the stored local date without arithmetic.

**Cons:**
- Two columns per timestamp doubles the storage surface and the schema complexity.
- The local-time column becomes stale if the user changes their timezone preference, requiring a backfill migration across every table.
- Inter-module comparisons must always use the UTC column, so the local column is only useful at render time — the same place Option A handles it with no extra storage.
- More columns means more opportunities for inconsistency (the two values disagree) and more schema drift risk.

### Option C - Store per-user timezone at write time (user-local storage)

Timestamps are stored in whatever the user's current timezone is. The user's timezone preference is recorded and used to interpret stored values.

**Pros:**
- Calendar-day semantics are natural at query time: a transaction stored at 11:45 PM is in the day the user experienced, not UTC.

**Cons:**
- When a user changes their timezone, every historical timestamp becomes ambiguous. Did the stored value mean local time under the old preference, or the new one? A migration is required every time.
- Inter-module comparisons require knowing which timezone each record was written under, which must be stored per-row or re-derived — this collapses back to Option B with additional fragility.
- Background jobs and server-side period logic run in a neutral timezone context; local-time storage forces the server to acquire the user's current preference for every comparison.
- The PostgreSQL `TIMESTAMP WITHOUT TIME ZONE` type that this option implies offers no protection against writes from code that forgot to apply the conversion.

## Decision

We will use **Option A**: all timestamps are stored and processed in UTC. Conversion to user-local time is permitted in exactly one place — a canonical rendering utility — and is forbidden everywhere else in the stack.

UTC storage is the only option that keeps historical data stable across timezone changes, eliminates ambiguity in period arithmetic, and keeps every module's internals free of timezone state. Option B's dual-storage adds schema complexity for a benefit that the rendering utility already provides. Option C's local-time storage makes historical data dependent on a mutable user preference, creating mandatory migrations on every timezone change.

What is now concretely true about this system:

1. **Database columns** that hold timestamps use `TIMESTAMPTZ` (or equivalent). Values written to the database are UTC.
2. **Service layer and background jobs** receive, compare, and pass UTC `datetime` objects. No conversion happens here.
3. **The canonical conversion layer** is a single utility (to be created in `app/utils/time.py` or equivalent) that accepts a UTC `datetime` and a user timezone string (IANA format, e.g., `"America/New_York"`) and returns a localized `datetime` for display. This is the only call site permitted to perform UTC-to-local conversion.
4. **Templates and route handlers** call the conversion utility when formatting a timestamp for output. They do not apply `timedelta` arithmetic or `strftime` to raw UTC values and present the result as local time.
5. **CSV import** that carries naive (no timezone offset) timestamps applies a documented timezone assumption (defaulting to UTC unless the user has specified otherwise) before persisting. This assumption is part of the import pipeline specification.

## Consequences

- **Positive:** All inter-module timestamp comparisons are safe. Period boundaries (budget months, alert windows, audit queries) are computed in UTC and are stable regardless of user timezone or DST transitions.
- **Positive:** The database schema is simpler — one column per timestamp, no per-row timezone metadata required.
- **Positive:** Background jobs (Intelligence Layer alerts, monthly summary generation) run entirely in UTC and do not need to acquire user timezone preferences for storage or comparison logic.
- **Positive:** DST transitions affect only the rendering utility, which is tested independently of domain logic.
- **Negative:** Developers must always convert at render time, not earlier in the stack. A timestamp logged, returned in an API response, or passed to a template without calling the conversion utility will display the wrong local time to the user. This is the single most common class of timezone bug in web applications and requires explicit discipline and code review attention.
- **Follow-up required:** The canonical conversion utility (`app/utils/time.py` or equivalent module path) must be created before any route or template that renders a timestamp. Its interface should be documented in the Transaction Engine API contract so downstream consumers know the expected call convention.
- **Follow-up required:** Tests covering DST boundary cases (spring-forward and fall-back transitions) must be written for the conversion utility before Phase 3a ships, per the mitigation in [risks.md](../risks.md).
- **Follow-up required:** The CSV import pipeline must document its timezone assumption for naive timestamps and expose it as a configurable user preference in Account Settings (Phase 2 or later).

## Notes

The risk row "Timezone handling drift between upload and storage" in [risks.md](../risks.md) names this ADR as the mitigation. That row is now partially fulfilled: the convention is documented. The remaining open items are the conversion utility implementation and the DST test suite, both tracked as follow-ups above.

PostgreSQL's `TIMESTAMPTZ` type stores UTC internally and applies the session timezone only during formatting. This means that even if application code forgets to enforce UTC on write, the database layer will preserve the correct moment in time as long as the session timezone is set consistently. This is belt-and-suspenders behavior, not a substitute for application-level discipline.
