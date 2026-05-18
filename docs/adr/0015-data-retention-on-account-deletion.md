---
adr: 0015
title: Data Retention on Account Deletion — Hard Cascade, No Grace Period
status: Accepted
date: 2026-05-17
phase: P3a
deciders: erin
---

## Context

The [roadmap's open decisions table](../roadmap.md#open-decisions) flags *"what happens when a user deletes their account"* as a decision to resolve before Phase 3a starts, because it affects the cross-module deletion runbook and the FK definitions on every per-user table introduced in 3a.

The architecture document is explicit: **"Financial data demands encryption at rest, secure auth, and minimal retention."** [CLAUDE.md](../../CLAUDE.md) names retention as a constraint to respect: *"retention policy documented per table."*

There are three deletion paths to consider, all of which must produce the same end state:

1. **Application-initiated** — the user clicks "delete my account" in a future UI (out of scope for 3a).
2. **Admin SQL** — operator runs `DELETE FROM auth.users WHERE id = …` directly.
3. **Supabase dashboard** — operator deletes the user via the hosted auth console. Supabase issues the `DELETE` on `auth.users` and our application code never runs.

Any deletion model that requires application code to run (e.g., a background-job purge) is silently bypassed by paths 2 and 3.

Relevant risks: "Account deletion incomplete across modules" (High impact, [risks.md](../risks.md)) and the PII/compliance posture trigger in [docs/adr/README.md](README.md#when-an-adr-is-required).

## Options considered

### Option A — Hard cascade now; no grace period

Every per-user table declares `user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE` (directly or transitively). Deletion of the `auth.users` row immediately and atomically deletes every dependent row in a single transaction. No tombstones. No background jobs. No recovery window.

**Pros:** Works identically under all three deletion paths. Zero application-code dependency. Database-enforced and atomic. Aligns with the "minimal retention" principle.

**Cons:** No recovery if a user deletes their account by mistake. Acceptable for a personal finance tool where the cost of an irreversible delete is bounded (the user can re-upload their CSVs), and where the alternative — soft-delete tombstones holding PII indefinitely — is the worse compliance posture.

### Option B — Soft-delete tombstones (`deleted_at` columns)

Add `deleted_at TIMESTAMPTZ` to every per-user table. Application code filters `WHERE deleted_at IS NULL` on every read. Rows are never physically removed.

**Pros:** Recoverable. Audit trail is preserved indefinitely.

**Cons:** Bypassed entirely by admin SQL and Supabase dashboard deletion paths. The `auth.users` row disappears, the dependent rows still exist with a now-orphaned `user_id` pointing at nothing. PII sits in the database forever, defeating the "minimal retention" principle. Every read in every module must remember to filter `deleted_at`; the first one that forgets leaks deleted data. This is the worst-of-all-worlds option for a system where the auth row is managed by an external provider.

### Option C — 30-day grace + scheduled purge job

`deleted_at` tombstones plus a background job that hard-deletes rows whose `deleted_at` is older than 30 days.

**Pros:** Recoverable for 30 days, then minimal retention is restored.

**Cons:** Phase 3a has no background-job infrastructure — that arrives with Phase 5. Building it now solely for retention is scope creep and contradicts the "ship vertical slices" principle. Same bypass problem as Option B for admin SQL and Supabase dashboard paths. The recovery story is also illusory: if Supabase reissues a deleted user's UUID (it does not, today, but this is not a guarantee we control), the recovery semantics break in surprising ways.

## Decision

We will choose **Option A — hard cascade now, no grace period, no soft-delete tombstones**. The two reasons that carried the decision: (1) cascade is the only model that works correctly under all three deletion paths including the two we do not control (admin SQL, Supabase dashboard), and (2) "minimal retention" of financial data is a stated architectural principle and Option B holds PII indefinitely.

## Cascade enumeration

Every per-user table in Phase 3a and every forward-looking per-user table MUST declare a path to `auth.users(id)` via `ON DELETE CASCADE`, either directly or transitively.

### Direct cascades on `auth.users(id)`

| Table | FK | Phase introduced |
|---|---|---|
| `public.categories` | `user_id` ON DELETE CASCADE | P1 (verify; see follow-ups) |
| `public.accounts` | `user_id` ON DELETE CASCADE | P3a |
| `public.uploads` | `user_id` ON DELETE CASCADE | P3a |
| `public.transactions` | `user_id` ON DELETE CASCADE | P3a |
| `public.budgets` | `user_id` ON DELETE CASCADE | P4 (forward-looking) |
| `public.alerts` | `user_id` ON DELETE CASCADE | P5 (forward-looking) |
| `public.insights` | `user_id` ON DELETE CASCADE | P5 (forward-looking) |

### Transitive cascades

| Table | FK | Behavior |
|---|---|---|
| `public.category_keywords` | `category_id` → `categories(id)` ON DELETE CASCADE | Already in place from [ADR-0009](0009-account-settings-schema-normalization.md) |
| `public.transactions` | `account_id` → `accounts(id)` ON DELETE CASCADE | Per [ADR-0014](0014-multi-account-per-user.md) |
| `public.uploads` | `account_id` → `accounts(id)` ON DELETE CASCADE | Per [ADR-0014](0014-multi-account-per-user.md) |
| `public.transactions` | `source_file_id` → `uploads(id)` ON DELETE CASCADE | P3a |

### Defense in depth on `transactions`

`transactions` carries **both** a direct `user_id` FK to `auth.users` and a `source_file_id` FK to `uploads`, both `ON DELETE CASCADE`. Either path is sufficient on its own. The redundancy is intentional: if a future migration changes one path, the other still enforces the cascade.

## Backups

Database backups (Supabase's automated daily backups) are **explicitly out of scope** for this cascade. Deletion of a user's account does not scrub their data from backup snapshots; those snapshots age out per Supabase's retention policy.

This is acceptable because:

- The architecture already accepts backups as a separate concern.
- The public privacy policy (a follow-up before any public signup flow) MUST disclose the backup retention window so users have informed consent.

## Cross-module deletion runbook (stub)

When a user is deleted, the operator (or in a later phase, the application) verifies that no orphaned rows remain. Verification queries to run post-delete (parameterize on the deleted `user_id`):

```sql
-- Should all return zero rows after deletion.
SELECT COUNT(*) FROM public.categories       WHERE user_id = :uid;
SELECT COUNT(*) FROM public.accounts         WHERE user_id = :uid;
SELECT COUNT(*) FROM public.uploads          WHERE user_id = :uid;
SELECT COUNT(*) FROM public.transactions     WHERE user_id = :uid;
-- And future tables:
-- SELECT COUNT(*) FROM public.budgets       WHERE user_id = :uid;
-- SELECT COUNT(*) FROM public.alerts        WHERE user_id = :uid;
-- SELECT COUNT(*) FROM public.insights      WHERE user_id = :uid;
```

If any of these return non-zero rows after an `auth.users` delete, the cascade chain is broken and a P0 bug should be filed. The runbook is expanded as later phases add tables.

## PII handling per table

| Table | What is stored | Retention |
|---|---|---|
| `public.categories` | User-defined category labels | Lifetime of user account; cascade on delete |
| `public.category_keywords` | User-defined merchant keywords | Lifetime of parent category; cascade |
| `public.accounts` | User-defined account labels and kind | Lifetime of user account; cascade |
| `public.uploads` | Original filename, file hash, row count, upload timestamp | Lifetime of user account; cascade |
| `public.transactions` | Date, description, amount, category assignment, fingerprint | Lifetime of user account; cascade |

PII in logs is scrubbed per the Phase 0 logging configuration; that is not changed by this ADR.

## Consequences

- **Positive:** Deletion works identically under application, admin SQL, and Supabase dashboard paths.
- **Positive:** "Minimal retention" of financial data is enforced at the database layer, not in application code.
- **Positive:** No background-job dependency in 3a.
- **Positive:** Defense-in-depth on `transactions` survives a single-FK migration mistake.
- **Negative:** No recovery from accidental account deletion. Mitigation: future self-serve deletion UI uses a double-confirmation dialog and surfaces the irreversibility clearly.
- **Negative:** No audit trail of what was deleted. Mitigation: the audit log follow-up below.
- **Follow-up:** Verify the existing `public.categories` table from Phase 1/2 declares `ON DELETE CASCADE` on its `user_id` FK to `auth.users(id)`. If not, fix it in the Phase 3a migration.
- **Follow-up:** Self-serve "delete my account" UI is out of scope for 3a. When it ships (likely Phase 3b or later), it MUST use a confirmation dialog that names the irreversibility explicitly.
- **Follow-up:** [Architecture cross-cutting concerns](../architecture.md#security) names an audit log for sensitive actions including account deletion. Implementing the audit log is deferred to the phase that introduces the deletion UI, with the table written in a way that survives the user row itself being deleted (i.e., the audit row does not FK to `auth.users`).
- **Follow-up:** Privacy policy must disclose the backup retention window before any public signup flow.
- **Follow-up:** Status is **Proposed** until human review. This ADR touches the High-impact deletion risk and the PII/compliance posture trigger and warrants a second pair of eyes.
