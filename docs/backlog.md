# Backlog

Small improvements, UX polish, and bugs that don't belong to a specific phase. Work these in whenever bandwidth allows — they don't block phase progress but they do affect daily usability.

## How to use this file

- Add items as they surface. No required order.
- Move items to a phase work-items list if they grow into something bigger.
- Update Status to **Closed** and note the PR when resolved. Don't delete rows — they're useful history.

---

| # | Status | Area | Item | Notes |
|---|---|---|---|---|
| 1 | Open | Upload | Upload feedback — spinner on submit, status on success | Disable the submit button and show a spinner on click; flash a success message (N transactions imported, M duplicates skipped) on redirect. Template/JS only — no server changes. |
| 2 | Open | Budgets | Show allocated total on the budget page | Running sum of all budget targets so the user knows how much of their expected spend is covered. |
| 3 | Open | Budgets | Overhaul budget configuration UI | Current flow (select category dropdown + submit at top) is too many clicks. Replace with an inline edit field next to each category row — one action per row, no separate submit. |
| 4 | Open | Settings | Fix settings page layout for typical screen sizes | Boxes/cards are not well-optimised for the viewport. Needs a layout pass. |
| 5 | Closed (#49, #50) | Upload | Fix upload timeout + graceful error handling | Per-row INSERT loop timed out gunicorn on Render free tier. Replaced with unnest bulk INSERT (ADR-0033). OperationalError now surfaces as a user-facing message. |
| 6 | Open | Transactions | Bulk category updates | Checkbox selection on history view with sticky action bar — apply one category to many transactions at once. Design decided in ADR-0032 (Phase 5c). |
| 7 | Open | UX (all) | Audit and improve weak or missing user feedback across the app | Do a pass over all forms, actions, and state-changing routes. Look for: silent redirects with no confirmation, missing flash messages, buttons that give no response on click, and error states that show a raw 500 or nothing. Fix gaps with light JS (disable-on-submit, spinners) and flash messages. No backend changes needed for most of these. |
| 8 | Open | Categorization | Write ADR defining behavior when category rules change | Gap in current ADRs: (1) keyword removed — existing transactions keep their category_id, implicit inaction but never stated; (2) keyword added — backfill only covers NULL rows, no path to re-examine already-categorized transactions that may now belong elsewhere; (3) merchant alias removed — same gap as keyword removed; (4) category deleted — ON DELETE CASCADE is defined on aliases/keywords (ADR-0029) but FK behavior on transactions.category_id is not stated in any ADR (SET NULL vs RESTRICT vs CASCADE). ADR must weigh intelligent-but-conservative remapping (user-triggered, scoped) vs aggressive auto-remap (risky, silently overwrites corrections). Preference: never touch non-NULL rows without explicit user action; offer a targeted "apply rule to history" flow for new rules only. |
| 9 | Open | Transactions | Upload new file button on Transactions page | Add a prominent "Upload new file" button/link to the transaction history page so users can start an upload without navigating to Settings → Files. |
| 10 | Open | Upload | Idempotency check blocks re-upload to a different account | The file hash dedup check (ADR-0013) rejects a file that was already uploaded under a different account, even when the user legitimately wants to import the same CSV into a new account. The check should be scoped to (user_id, account_id, file_hash) rather than (user_id, file_hash) alone. |
