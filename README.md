# Family Budget

A self-hosted budget app for a family, running on a home NAS. It keeps two things apart:

- **Budget:** what the family spends per category and month, against the plan (Budgets, Analytics, Common budget,
  Yearly bills, Investments, Wishes).
- **Accounts:** whether each account matches reality: balances, transfers between own accounts, clearing accounts
  (e.g. Migros) with a monthly check.

Bookings come in by hand, or in bulk from bank and Migros exports through small converters and an import preview.

## Family model

- **Parents** log in with a 4-digit PIN. Each parent's money is private unless they share it with another parent
  (view, or view and manage) in Settings.
- **Common budget:** costs the parents share are split by a ratio (e.g. 50/50 or by income); the Common tab shows who
  owes whom and books settling up.
- **Children** either have an own allowance (own login, accounts and budgets) or are dependents whose costs are
  household expenses tagged with them.
- There's no sign-up: the first start creates the parent `Admin` (see [README_DOCKER.md](README_DOCKER.md)), and
  parents add everyone else.

## Stack

- **Backend:** Python 3.14, FastAPI, SQLAlchemy, SQLite; Alembic migrations applied on start-up
  (`backend/app/migrations`). Money is stored in integer cents; the API uses francs.
- **Frontend:** React 19, TypeScript, Vite, Tailwind 4.
- **Deployment:** two Docker images (GitHub Container Registry), a nightly update script for the NAS.

## Running it

- **On a NAS or any Docker host:** [README_DOCKER.md](README_DOCKER.md).
- **For development:**

  ```sh
  cd backend && pip install -r requirements.txt && uvicorn app.main:app --reload   # http://localhost:8000
  cd frontend && npm ci && npm run dev                                             # http://localhost:3000
  ```

  The first start logs the `Admin` PIN (or set `INITIAL_ADMIN_PIN`). The database is `backend/data/budget.db`
  unless `DATABASE_URL` says otherwise.

  The app speaks German and English: each person picks a language in **Settings → Logins**. `DEFAULT_LANGUAGE`
  (`de` if unset, or `en`) is the language of people who haven't picked one, of the login screen when the browser
  asks for neither, and of a new database's default categories.

## Tests

- **Backend:** `pip install -r tests/requirements.txt`, then `pytest` from the repository root (about 30 s).
- **Browser:** Playwright end-to-end tests in [e2e/](e2e/README.md).
- **Frontend:** `npm run lint`, `npm run type-check`, `npm run build` in `frontend/`.
- CI runs all of them on every pull request (`.github/workflows/`).

## Documentation

- [Import format](docs/import-format.md): the CSV/JSON files the import accepts, with the JSON Schema for tools.
- [Bank and Migros converters](tools/converters/README.md): from bank and receipt exports to import files.
- [Deployment and updates](README_DOCKER.md), including database updates and rolling back.
- Design specs and implementation plans: [docs/superpowers/](docs/superpowers/).
- Backlog: GitHub Issues.

## License

[MIT](LICENSE)
