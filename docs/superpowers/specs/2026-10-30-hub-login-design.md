# The budget app on the family-hub login

Status: draft, 2026-10-30. Rollout step 2 of family-hub (`FrankAndreas/family-hub`, design
`docs/superpowers/specs/2026-10-29-family-hub-design.md` there). Part A changes the hub, part B this app.

## Why

The family has several self-hosted apps, each with its own people and PINs. family-hub (running on the NAS since
2026-10-30, at `https://home.local.<domain>`, port 8086) now holds the family's people, PINs and the login. This app
stops managing people itself: a new family member is added once, in the hub, and appears here by itself.

Today only the user has an account in this app on the NAS, and its data isn't important yet, so the switch needs no
careful migration.

## Goals

- One login: whoever is logged in to the hub is logged in here; no PIN screen in this app.
- People come from the hub. Adding a person, PINs, lockouts, roles and "log out everywhere" are the hub's.
- Who may use which app is set in the hub, per app. This app learns its people from the hub (pull, no push).
- App-specific details stay here: Jugendlohn or dependent (`has_allowance`), the privacy switch, receipt-mail
  addresses, shares, accounts, budgets.
- Someone who loses access (or is deactivated in the hub) is hidden here, their data kept. A parent may delete it here.
- A dependent child gets a read-only view of their own costs.

## Non-goals

- Hub-managed app settings (an app describing its settings for the hub to show). Decided against: settings like
  Jugendlohn change the app's data and rules, so they stay in the app.
- Push from the hub to the apps (webhooks).
- Access from outside: this app stays home-only (no tunnel route, except the receipt-mail path, which is unchanged).
- Migrating the other apps (meal-planer, jobs, chore): later, each with its own design.

## Anti-goals (would make it a failure even if it works)

- A person's data deleted because the hub changed. Only an explicit parent action in this app deletes data.
- A dependent child able to change anything, by the screen or by calling the API.
- A login token or cookie value in any log line.
- The real domain or NAS address in the repos (`<domain>`, `<NAS_IP>` placeholders only).

## Part A: the hub

1. **App key.** A tile gets an optional `app_key` (short, lowercase, unique, e.g. `budget`), set in the hub's
   Einstellungen → Apps. Only tiles with a key take part in access; a tile without one (a plain link) is shown to
   everyone as today.
2. **Access.** Per tile with a key, the list of people who may use it (checkboxes per person in the tile's form, and
   per tile in the person's form or one of the two; builder's choice). A new tile starts with no one; a new person
   starts with no app. Management stays home-only, parents only, like the rest.
3. **Start page.** Shows a person only the tiles without a key plus the ones they have access to.
4. **`GET /api/session?app=<key>`.** As today, plus: with `app`, the answer is `valid: false` when the person has no
   access to that app. Without `app`, unchanged (the README's contract stays valid).
5. **`GET /api/apps/<key>/people`.** Auth as `/api/session` (Bearer hub token, or the Cloudflare headers). Allowed
   for a person who has access to `<key>`. Returns every active person with access to `<key>`:
   `[{"id", "name", "role", "color", "language"}]` (no e-mail, no PIN data). 403 without access, 404 for an unknown
   key.
6. README "For apps" documents both.

## Part B: this app

### Logging in

- The browser sends the hub's cookie `hub_session` (domain `local.<domain>`, HttpOnly) to `budget.local.<domain>`.
  The backend reads it and asks the hub `GET <HUB_URL>/api/session?app=<HUB_APP_KEY>` with
  `Authorization: Bearer <cookie value>`. The answer is cached in memory for up to 60 s, keyed by a hash of the
  token. A hub that can't be reached: 503 with a clear message, never a login.
- New settings: `HUB_URL` (how the backend reaches the hub on the NAS, e.g. `http://<NAS_IP>:8086`),
  `HUB_PUBLIC_URL` (where browsers log in, `https://home.local.<domain>`), `HUB_APP_KEY` (default `budget`), `COOKIE_DOMAIN`. They go
  into the NAS compose.yaml's backend environment (README_DOCKER.md says so; a value only in `.env` doesn't reach the
  container).
- Not logged in, or no access: the frontend sends the browser to `<HUB_PUBLIC_URL>/?next=<this app's address>`.
- "Log out" in this app: the backend clears the `hub_session` cookie itself (same name, `Domain=local.<domain>`,
  path `/`; a site under `local.<domain>` may set it), so the browser is logged out of every app. New setting
  `COOKIE_DOMAIN` (as in the hub). My call: simpler than calling the hub across sites, which would need CORS there.
  "Log out everywhere" stays in the hub.
- The language is the hub person's language.
- The frontend no longer keeps a token in localStorage. Requests that change something carry a custom header (e.g.
  `X-Requested-With`) that the backend requires, so another site can't make the browser send them with the cookie
  (sibling apps share the site); the backend allows no cross-origin requests.
- The receipt-mail path (`/api/v1/inbound`, own secret) is unchanged.
- Removed: the PIN login, the seeded Admin with its initial PIN, `SECRET_KEY` signing, the lockout, "log out
  everywhere" here, `PATCH /me/language`, adding users, PINs, role changes, deactivating here. Their e2e specs
  (`login-limit`, `wrong-pins`, `logout-everywhere`) go; the hub has its own.

### People

- `users` gets `hub_id` (the hub person's id, unique). The app's own ids and all links to them stay.
- Pull: the app refreshes its people from `/api/apps/<key>/people` (with the visitor's token) at most once a
  minute, on the session check, and when a parent opens Einstellungen. A hub person without a `users` row gets one;
  name, role and colour follow the hub. Role is the hub's (parent/child).
- A person no longer in that list is hidden: not in people lists, owner choices, shares, splits to pick, the
  dashboard or reports, and can't log in here. Their rows stay. If they come back, everything is as before.
- Linking existing rows: the first refresh links a `users` row without `hub_id` to the hub person with the same name
  (case-insensitive). Rows that match no one stay unlinked and hidden (deletable as below).
- Einstellungen → people: shows the people from the hub with the app's own details (Jugendlohn or dependent, privacy,
  receipt-mail addresses). A note says people are added and removed in the hub.
- New children start as dependent (no Jugendlohn) until a parent switches them (my call: the safe default, since a
  dependent child only reads).
- "Removed in the hub": a section in Einstellungen, parents only, listing hidden people. "Delete data" there runs the
  existing removal (decide where investments and yearly bills go, then delete accounts, bookings, budgets, wishes;
  tags on household expenses are dropped). Not offered for anyone the hub still lists.

### A dependent child's view

- A child without Jugendlohn sees one page instead of the app: their own costs, read-only.
- Month picker; the month's total, the year's total; the month split by category (amount per category, largest
  first); the list of bookings tagged with them (`transactions.member_id`): date, what, category, amount, newest
  first.
- Not shown: receipt photos or attachments (they show the whole family's shopping), accounts, who paid.
- The backend refuses every change from a dependent child (403), whatever the screen shows, and every read beyond
  their own costs.
- Language and log out as everywhere.

### Testing

- The browser tests start a real hub next to the app (from a checkout of family-hub, like CI checks it out), log in
  there and use the app. Invented people and data only.
- Backend tests use a stub hub (the session and people answers), including: hub unreachable, access removed, person
  back, name linking, a dependent child trying to change things.

## Order

1. Part A in the hub (its own PR), deployed.
2. Part B: login and people pull; removed people hidden and deletable.
3. Part B: the dependent child's view.

## Left to the builder

How the session cache and the people refresh are built, the exact UI of the access checkboxes, the CSRF header's
name, how CI gets the hub, and where the frontend's redirect logic lives.
