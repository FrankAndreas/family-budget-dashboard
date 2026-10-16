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
| `month-check.spec.ts` | Accounts tab, clearing account, month check books the gap |
| `transfers.spec.ts` | bank converter output imported, transfer direction, deleting a transfer |
| `wishes.spec.ts` | wish lists, order, family plan with running total, search links, bought, best price |
| `import-rules.spec.ts` | category changed in the preview, remembered as a rule, used by the next import, the schema's `x-rules` |

New tests: one file per feature, start with `newParent()` and `login()` from `tests/helpers.ts`, and use invented
data only (the repository is public).
