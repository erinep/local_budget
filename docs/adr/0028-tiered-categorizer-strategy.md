# ADR 0028 - Tiered Categorizer Strategy

- **Status:** Accepted
- **Date:** 2026-05-18
- **Phase:** P5b
- **Deciders:** Architect agent

## Context

Phase 5b (Categorizer v2) upgrades the single-pass keyword scan (`make_categorizer`, ADR-0005) with a multi-tier pipeline that uses normalization, merchant memory, and token overlap to reduce the volume of uncategorized transactions before falling through to the existing keyword list.

Two binding constraints:

- **ADR-0005** established the factory-closure pattern: the returned callable must remain `Callable[[str], str]` and must carry all data in-scope — no database calls inside the closure. Phase 5b extends the factory, not the closure's call contract.
- **ADR-0018** established that `recategorize_transaction` writes keywords through Account Settings' `add_keyword`. Smart-categorization writes must use the same path (the conflict-resolution rule and normalization live there). The categorizer tiers are read-only; writes belong to the caller.

Relevant risks: "LLM endpoint cost and latency" (`All`, High) — this ADR explicitly defers any embedding-based tier until the test harness proves it is needed, keeping the critical upload path free of LLM calls.

## Options considered

### Option A - Replace keyword scan with a single LLM call per transaction

Every description is sent to an LLM to infer category. Simple to implement; high accuracy out of the box.

**Pros.** Handles novelty well; no corpus needed.

**Cons.** Violates the LLM cost-control constraint in `CLAUDE.md` (per-user rate caps, circuit breakers). Upload time would scale with transaction count. Adds an external dependency to the critical upload path. Merchant-level caching would partially mitigate latency but not cost for first-time merchants.

### Option B - Jaccard similarity against all past transactions (no normalization tier)

Skip description normalization and jump directly to token-overlap matching.

**Pros.** Fewer moving parts.

**Cons.** Processor prefixes (`SQ *`, `PAYPAL *`) cause token pollution that artificially lowers Jaccard scores between identical merchants processed through different payment rails. Without normalization, merchant memory would need to store every prefix variant, multiplying alias storage.

### Option C - Five-tier pipeline: normalize → merchant alias → Jaccard → keyword scan → Uncategorized

Normalization strips processor noise first. Merchant aliases give a zero-corpus exact-match shortcut (Tier 2). Jaccard handles near-matches using correction history (Tier 3). Keyword scan (Tier 4) remains for new users and explicit rules. "Uncategorized" (Tier 5) replaces "Slush Fund" as the honest fallback. Embeddings are gated behind a harness check.

**Pros.** Normalization multiplies the value of every downstream tier. Tiers 2–3 improve automatically as the user corrects transactions; no manual rule-writing is required. Tier 4 (existing behavior) provides bootstrap accuracy for new users. The pipeline is entirely local: no LLM call on the critical path.

**Cons.** Five tiers require a more complex factory than the current one. The Jaccard threshold (0.3 default) needs empirical validation by the test harness.

### Option D - Token overlap only, no merchant alias table

Skip the merchant alias tier and rely solely on Jaccard.

**Pros.** No new schema table. Jaccard would eventually converge to the same result as an alias.

**Cons.** Jaccard on a single past transaction is noisy. An alias written after the first correction gives a confident exact match from the second occurrence onward; Jaccard only gives a probabilistic one. The alias table also enables the cold-start seed corpus (ADR-0029), which Jaccard cannot provide.

## Decision

We will choose **Option C — the five-tier pipeline** because normalization is a prerequisite for reliable matching at every downstream tier, and the merchant alias table provides a cold-start corpus that Jaccard cannot.

## Tier definitions

### Tier 1 — Description normalization

`normalize_description(desc: str) -> str` is a standalone helper exported from `app/transactions/services.py` alongside `make_categorizer_v2`.

Normalization steps applied in order:

1. Strip processor prefixes (case-insensitive, regex): `SQ *`, `PAYPAL *`, `TST*`, `SP *`, `PP*`, `WWW.`
2. Strip trailing store numbers: `#\d+` and ` \d{3,}` at end of string.
3. Strip city/state suffixes: ` [A-Z]{2,}\s+[A-Z]{2}$` (e.g., ` TORONTO ON`, ` VANCOUVER BC`).
4. Collapse multiple whitespace to a single space; strip leading and trailing whitespace.

`normalize_description` is called at both categorization time (on the incoming description) and at write time (on stored descriptions before building the token corpus). The function must be pure and side-effect-free.

### Tier 2 — Merchant memory (exact match)

After normalization, look up the normalized description in `merchant_aliases.normalized_name` scoped to the user's categories (via `category_id → categories.user_id`). If found, return the associated category name. Confidence is 1.0 (exact match). No further tiers are evaluated.

The alias list is pre-loaded by the caller before the factory is invoked — the closure does not query the database.

### Tier 3 — Token overlap (Jaccard similarity)

Tokenize the normalized description into lowercase alpha tokens of at least 3 characters. Compute Jaccard similarity against the normalized descriptions of all past categorized transactions for this user (pre-loaded by the caller).

```
Jaccard(A, B) = |A ∩ B| / |A ∪ B|
```

Take the category of the highest-scoring past transaction. If that score is >= 0.3 (default threshold), return the associated category name. If score < 0.3, fall through to Tier 4.

Jaccard is chosen over TF-IDF because it requires no stored vector representations and is computed at categorization time from description strings that are already stored. This keeps the factory data-contract simple: a list of `(normalized_desc, category_name)` tuples.

### Tier 4 — Keyword list

Existing behavior: uppercase substring scan of the description against `category_keywords` for this user. Retained for bootstrap (new users have no correction history for Tiers 2–3) and for explicit user-defined rules.

### Tier 5 — Fallback

If no tier matches, return `"Uncategorized"`. The category ID stored in `public.transactions` is `NULL` when the result is `"Uncategorized"`. This replaces the current `"Slush Fund"` string which is semantically misleading and not a real category row.

### Tier 6 — Local embeddings (gated, deferred)

Only in scope if the test harness shows that Tiers 1–5 leave more than 20% of transactions uncategorized after 3 months of user correction history. The harness owner measures this before any embedding work begins. No embedding code is written in Phase 5b.

## Public API contract

The following names are added to `app/transactions/services.py`. All prior names (including `make_categorizer`, renamed `make_categorizer_v1`) remain unchanged.

```python
def normalize_description(desc: str) -> str:
    """Strip processor prefixes, store numbers, city/state suffixes; collapse whitespace.

    Pure function. No database access. Called by the factory and by callers
    building the past-transactions corpus before invoking the factory.
    """
    ...


def make_categorizer_v2(
    user_id: str,
    keywords: list[tuple[str, str]],           # (keyword, category_name) from category_keywords
    aliases: list[tuple[str, str]],            # (normalized_name, category_name) from merchant_aliases
    past_transactions: list[tuple[str, str]],  # (normalized_desc, category_name) from transactions
) -> Callable[[str], str]:
    """Return a Tier 1–5 categorizer closure suitable for DataFrame.apply.

    All data is pre-loaded and passed in. The factory does not touch the database.
    The caller (upload route handler) is responsible for loading the three lists
    before calling the factory.

    The returned closure applies normalize_description to its input before any
    tier lookup, so callers do not need to pre-normalize incoming descriptions.

    Returns category_name as a str. Returns "Uncategorized" if no tier matches.
    """
    ...
```

**Caller contract:** The upload route handler must:

1. Load `keywords` from Account Settings (existing pattern via `get_category_map`).
2. Load `aliases` by querying `merchant_aliases` joined through `categories` for the user.
3. Load `past_transactions` as `(normalize_description(raw_desc), category_name)` tuples for all previously categorized transactions for the user (where `category_id IS NOT NULL`).
4. Call `make_categorizer_v2(user_id, keywords, aliases, past_transactions)` once per upload.
5. Pass the returned closure to `DataFrame.apply`.

## Deprecation of make_categorizer

`make_categorizer` (ADR-0005) is renamed to `make_categorizer_v1`. The rename is an alias only — the implementation is unchanged. `make_categorizer_v1` is retained for the duration of Phase 5b as a fallback shim while the test harness baselines accuracy. It is deleted after the harness confirms `make_categorizer_v2` meets or exceeds the baseline. The `make_categorizer` name must not appear in new code written after this ADR is accepted.

## Test harness

A pytest fixture file `tests/fixtures/categorizer_labeled.json` contains an array of `{"description": str, "expected_category": str}` objects. The harness runs each description through both `make_categorizer_v1` and `make_categorizer_v2` and reports accuracy as `correct / total`. The harness is committed before any v2 implementation code is written so the v1 baseline is on record. The Jaccard threshold (default 0.3) is tunable via a harness parameter; the harness reports accuracy at the chosen threshold.

## PII discipline

Transaction descriptions must not appear in log output at any tier. Log entries must contain only: the tier number reached and a boolean indicating whether a match was found. Category names must not appear in logs either. This extends the PII constraint from ADR-0018 to the categorization path.

## Consequences

- **Positive.** Normalization multiplies the accuracy of Tiers 2–4 by removing processor noise before any lookup.
- **Positive.** Merchant aliases improve automatically as the user corrects transactions; no manual rule authoring is required for Tier 2 accuracy.
- **Positive.** "Uncategorized" with a `NULL` `category_id` is a precise, queryable state; "Slush Fund" was neither.
- **Positive.** No LLM call on the upload critical path; Tier 6 is gated and deferred.
- **Negative.** The upload route handler must now load three data sets before categorizing (keywords, aliases, past transactions) instead of one. For large user histories this is a non-trivial pre-load.
- **Negative.** The Jaccard threshold is a tunable hyperparameter. The default (0.3) is a starting point; the harness may reveal it needs adjustment.
- **Follow-up required.** `make_categorizer_v1` must be deleted once the harness confirms v2 accuracy.
- **Follow-up required.** The upload route handler must be updated to call `make_categorizer_v2` with the expanded data contract. See ADR-0029 for the `merchant_aliases` schema.
- **Follow-up required.** ADR-0030 covers backfill of `NULL`-category transactions after the upgrade.

## Notes

The Jaccard threshold of 0.3 is a starting point based on the observation that two-token descriptions sharing one token yield Jaccard = 0.5, and that a shared-token rate below 30% more likely reflects a different merchant than a noisy variant. The harness is authoritative; this rationale is informational only.
