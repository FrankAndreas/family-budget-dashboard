# Browser tests

End-to-end tests with [Playwright](https://playwright.dev): a real browser against the real backend and frontend.

Playwright starts both itself (`playwright.config.ts`):
- the backend on port 8100, with a fresh SQLite database in `e2e/.tmp/` and the admin PIN 1111;
- the frontend with Vite on port 3100.

A dev server on 8000/3000 and its data are never touched. Each test creates a parent of its own through the API, so
tests don't depend on each other.

## Run

Once:

```sh
python3 -m venv .venv-e2e && .venv-e2e/bin/pip install -r backend/requirements.txt   # from the repository root
cd frontend && npm ci && cd ..
cd e2e && npm ci && npx playwright install chromium
```

Then, in `e2e/`:

```sh
E2E_PYTHON=../.venv-e2e/bin/python npm test
```

`E2E_PYTHON` is any Python 3.11+ with the backend's packages (default: `python3`).

- `npx playwright test wishes`: one file.
- `npx playwright test --headed`: watch the browser.
- `npm run report`: the HTML report after a run.

On a failure, `test-results/` has a screenshot and a trace (`npx playwright show-trace <trace.zip>`).

## Tests

| File | Covers |
|---|---|
| `accounts.spec.ts` | accounts and bookings through the forms |
| `backup.spec.ts` | the backup leaves out view-only shared accounts |
| `bank-import.spec.ts` | bank statement upload: account by IBAN, rules, AI categories, balance check |
| `categories.spec.ts` | managing categories in Settings |
| `common-budget.spec.ts` | common budget with more than two parents |
| `german.spec.ts` | switching the app to German and back |
| `import-rules.spec.ts` | category changed in the preview, remembered as a rule, used by the next import, the schema's `x-rules` |
| `login-limit.spec.ts` | the login page shows the lock after too many wrong PINs |
| `logout-everywhere.spec.ts` | log out everywhere, changing one's own PIN |
| `month-check.spec.ts` | Accounts tab, clearing account, month check books the gap |
| `receipt-mails.spec.ts` | a forwarded receipt mail is released, read and booked |
| `receipt-onto-payment.spec.ts` | a receipt read after the statement goes onto the bank booking that paid it |
| `wrong-pins.spec.ts` | wrong PINs entered for a name are shown at its next login |
| `receipt-scan.spec.ts` | a pile of receipts scanned (one failed upload retried), with thumbnails and a duplicate flag, then checked against the photo and booked one after another; a pile scanned without the AI; a photo that can't be read; the other parent's photo explains the missing account |
| `phone-layout.spec.ts` | the overview at phone width: no sideways scrolling, compact summary cards, the tab row's "more tabs" arrow, one Scan button, amounts on one line, tap-sized edit and delete; Settings sections folded, the import rules folded with a search |
| `edit-far-down.spec.ts` | editing a booking, investment or yearly bill far down a long list brings the filled-in form into view; the owner list says why other people are missing |
| `investments.spec.ts` | investments grouped by tag with totals per group and overall, a due-soon marker, a new tag from the form, archived out of the totals and restored |
| `receipts.spec.ts` | receipt read by the AI, an item with two tags, analytics and a tag budget |
| `reconciliation.spec.ts` | a statement confirms a receipt typed in before it; badges and open points |
| `reports.spec.ts` | budget spending and analytics totals |
| `transfers.spec.ts` | bank converter output imported, transfer direction, deleting a transfer |
| `wishes.spec.ts` | wish lists, order, family plan with running total, search links, bought, best price |

New tests: one file per feature, start with `newParent()` and `login()` from `tests/helpers.ts`, and use invented
data only (the repository is public).
