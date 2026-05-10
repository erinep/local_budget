---
adr: 0008
title: Google OAuth Deferred to Phase 1.5
status: Accepted
date: 2026-05-10
deciders: erin p
---

## Context

Phase 1 (Persistence & Authentication) originally listed "email/password + Google OAuth via Supabase Auth" as a single work item. Google OAuth requires:

- Registering a redirect URI in Google Cloud Console
- Supabase OAuth callback handling in the auth integration module
- Testing the OAuth flow end-to-end (separate from email/password testing)

This is manageable scope but is independent of the core auth infrastructure. Email/password auth satisfies the Phase 1 exit criteria on its own. Shipping them together adds risk to a phase that already has expensive failure modes (security surface).

## Decision

Google OAuth is deferred to **Phase 1.5** — a thin follow-on phase after Phase 1 exits and before Phase 2 begins.

Phase 1 ships: email/password sign-up, login, logout, password reset.  
Phase 1.5 ships: Google OAuth sign-in via Supabase, wired into the existing auth blueprint.

## What is now true about the system

1. The `app/auth/services.py` module will be designed to accommodate a future `sign_in_with_google() -> str` (returns OAuth redirect URL) without structural changes — the Supabase client already supports OAuth flows, so this is an additive function.
2. No Google Cloud Console project or OAuth client ID is required before Phase 1 ships.
3. Phase 1.5 is a single-agent vertical slice: one implementation PR, one reviewer pass, no schema changes required (Supabase Auth handles the OAuth identity internally).

## Consequences

- **Positive:** Phase 1 scope is tighter. Auth is delivered sooner with lower risk.
- **Positive:** The OAuth implementation benefits from the auth module being stable and reviewed before it is extended.
- **Negative:** Users (currently just the owner) must use email/password until Phase 1.5 ships. Acceptable for a personal app.
