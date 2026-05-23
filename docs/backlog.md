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
| 5 | Upload | Graceful error handling for upload failures | A 44 KB file failed on upload — likely a timeout or memory limit on the Render free tier. Currently the error is not surfaced clearly to the user. Add a user-facing error message and a retry path. Investigate whether the root cause is a Render request timeout, memory cap, or something else before fixing. |

## Done

| # | Area | Item | PR |
|---|---|---|---|
