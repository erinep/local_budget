# Backlog

Small improvements, UX polish, and bugs that don't belong to a specific phase. Work these in whenever bandwidth allows — they don't block phase progress but they do affect daily usability.

## How to use this file

- Add items as they surface. No required order.
- Move items to a phase work-items list if they grow into something bigger.
- Mark items **Done** and note the PR when resolved. Don't delete resolved rows — they're useful history.

---

## Open

| # | Area | Item | Notes |
|---|---|---|---|
| 1 | Transactions | Upload status indicator on the transactions page | User needs feedback on whether a recent upload succeeded, is processing, or failed. |
| 2 | Budgets | Show allocated total on the budget page | Running sum of all budget targets so the user knows how much of their expected spend is covered. |
| 3 | Budgets | Overhaul budget configuration UI | Current flow (select category dropdown + submit at top) is too many clicks. Replace with an inline edit field next to each category row — one action per row, no separate submit. |
| 4 | Settings | Fix settings page layout for typical screen sizes | Boxes/cards are not well-optimised for the viewport. Needs a layout pass. |
| 5 | Upload | Graceful error handling for upload failures | Root cause was per-row DB inserts timing out gunicorn (fixed in #49). Error now surfaces as a user-facing message. |
| 6 | Upload | Client-side loading spinner on file submit | Disable the submit button and show a spinner the moment the form is submitted so the user knows their click registered. Template/JS only — no server changes. |
| 7 | UX (all) | Audit and improve weak or missing user feedback across the app | Do a pass over all forms, actions, and state-changing routes. Look for: silent redirects with no confirmation, missing flash messages, buttons that give no response on click, and error states that show a raw 500 or nothing. Fix gaps with light JS (disable-on-submit, spinners) and flash messages. No backend changes needed for most of these. |

## Done

| # | Area | Item | PR |
|---|---|---|---|
| 5 | Upload | Fix upload timeout (per-row INSERT → unnest bulk INSERT) + OperationalError handling | #49 |
