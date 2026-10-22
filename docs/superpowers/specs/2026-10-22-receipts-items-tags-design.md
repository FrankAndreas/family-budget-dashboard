# Receipts from photos, with items, tags and persons

Date: 2026-10-22. Status: draft, for review.

## Why

Typing in receipts is tedious, and categories alone can't answer questions like "what do my bicycles really cost me,
clothes included?". The user wants to photograph a receipt (e.g. Migros) and let an AI read and sort it, then see
spending by purpose and by person, not only by category.

## Goals

- **Receipt → booking:** a receipt (a **photo**, a **PDF** or an **e-mail** saved as `.eml`) becomes **one booking**
  (the receipt's total) with its **items** underneath. The AI (Infomaniak AI service) reads it and fills a preview;
  nothing is booked until the person confirms. The receipt itself is **kept as an attachment** of the booking.
- **Each item answers three questions:**

  | Field | Question | Example: bike shorts |
  |---|---|---|
  | Category | *what* is it? | Kleidung |
  | Tags (0..n) | *what for?* | Velo |
  | Person (0..1) | *for whom?* | Andreas |

- **Each item counts towards its own category** in budgets and Analytics; a receipt with bread and a cycling jersey
  counts partly as Lebensmittel, partly as Kleidung.
- **Totals by tag and by person**, e.g. "Velo this year: CHF 4'000", "Velo for Andreas".
- **Budgets per tag**, e.g. "Velo: CHF 4'000 per year", next to today's budgets per category.
- **Several tags per item, counted correctly:** an item counts **in full under each of its tags** (the bike shorts
  tagged Velo and Sport count CHF 80 in Velo *and* CHF 80 in Sport). Tag totals therefore overlap and are **never
  added up**; the overall total always comes from the categories, where each item has exactly one.

## Non-goals (first version)

- Hierarchical tags. A tag may later get one parent tag ("Sport" = Velo + Ski); not now.
- Tags the AI invents. The AI only picks from the family's own tag list; new tags are created by people.
- Items in CSV/JSON imports, in the JSON backup/restore and in the converter. (The analysis ZIP does get them.)
- A mailbox the app polls for forwarded receipts. E-mails come in as uploaded `.eml` files.
- Attachments in the analysis ZIP or the JSON backup (they live in the NAS data folder, see section 6).
- Income receipts. Items are expenses only.
- Reading bank statements or PDFs with the AI.

## Anti-goals (would make it a failure even if it works)

- The API token or product ID appearing in the repo, logs, error messages or the browser.
- Anything booked without the person confirming the preview.
- Data from the app (names, accounts, balances, other bookings) sent to the AI service. Only the photo, the category
  names and the tag names leave the NAS.
- Budgets or Analytics counting an itemized receipt twice (once as booking, once as items).

## Decided with the user

- Infomaniak AI service, authenticated with an **API token** (scope `ai-tools`) and the AI product ID; not OAuth.
- On the user's machine both live in `pass` (`andreas/infomaniak_ai_api_token`, `andreas/infomaniak_ai_product_id`)
  and are never read, printed or logged directly.
- One booking per receipt; items each with their own category; flat tags from a pre-configured list only; a person per
  item from the family members (parents included, e.g. "Dad", "Andreas").
- The receipt (photo, PDF or e-mail) is stored with the booking.
- Budgets per tag are part of the first version.
- An item can have several tags; each tag counts it in full, and tag totals are never summed.
- A spending cap is set on the AI product in the Infomaniak Manager (outside the app).

## Feasibility (tested 2026-10-22, throwaway script)

- OpenAI-compatible API: `https://api.infomaniak.com/2/ai/<product_id>/openai/v1`, `Authorization: Bearer <token>`,
  `/chat/completions` with an `image_url` data URL.
- `google/gemma-4-31B-it` read a one-item receipt correctly in 3.4 s with ~580 input tokens;
  `mistralai/Mistral-Small-4-119B-2603` too, in 1.8 s with ~2'700 input tokens. A long Migros receipt (abbreviations,
  discount lines, quantities) is still to be tested; the model is configurable, so the choice doesn't block the build.

## 1. Data

New tables (Alembic migration 0008):

- `tags`: `id`, `name` (unique, case-insensitive, max 50), `icon` (optional emoji). Family-wide, like categories.
- `transaction_items`: `id`, `transaction_id` (FK, deleted with the booking), `position` (order on the receipt),
  `name` (max 120), `amount` (Money, positive = cost, negative = discount/deposit refund), `category_id` (FK, an
  EXPENSE category), `person_id` (FK users, optional).
- `transaction_item_tags`: `item_id`, `tag_id` (both FK, primary key together), so one item can have several tags.
- `attachments`: `id`, `transaction_id` (FK, deleted with the booking), `filename` (the original name, for display),
  `content_type` (`image/jpeg`, `image/png`, `application/pdf`, `message/rfc822`), `size`, `sha256`, `created_at`.
  The file itself is stored at `data/attachments/<attachment id>` (never under its original name). A booking can have
  several attachments (e.g. photo of both sides).
- `budgets` gets an optional `tag_id`: a budget is for **either** a category **or** a tag (exactly one of the two).

Rules:
- A booking **with items** is always an expense; its amount is minus the sum of its items (kept in sync on every
  change). Its own `category_id` is the category with the largest item total ("main category"), so lists, the
  transaction form and code that only knows bookings keep working.
- A booking without items behaves exactly as today.
- An itemized booking can still be shared with a split and linked to an investment (whole booking, as today). Its
  `member_id` (the "for child" tag) stays empty: the person sits on the items.
- Deleting a tag removes it from all items (the items stay). Deleting a category used by items is refused, like
  today for bookings; `usage_counts` counts items too. A removed family member's items lose the person.

## 2. Counting: budgets, Analytics, export

One place decides what counts: `reports.bookings` (today: one row per booking) becomes a list of **spending lines**:
one line per booking without items, one line per item for itemized bookings (amount, category, date, person, tags).

- **Budgets** (`budget_out`) and **Analytics** (`summary`: totals, by category, months, days) use the lines. Totals
  don't change for existing data.
- **Counting by tag:** for a tag, the lines that carry it are summed; a line with several tags is counted once **per
  tag** (never twice within the same tag). A category budget or total is unaffected, since each line has exactly one
  category. Tag totals are shown as a list, **without a sum**, with the note "An item with several tags counts in each
  of them". Overall totals (income, expenses, savings) never come from tags.
- **Budgets per tag:** `spent` = sum of the period's lines carrying the tag (in the budget owner's scope, like category
  budgets). A plain booking (no items) never carries a tag, so tag budgets only see itemized bookings.
- **Costs per child:** a line counts for a child if the booking's `member_id` or the item's `person_id` is a
  dependent child.
- **New in Analytics:** "Spending by tag" and "Spending by person" for the chosen range and scope (lines without a
  tag/person aren't listed).
- **Analysis ZIP:** new `items.csv` (`item_id`, `transaction_id`, `position`, `name`, `amount`, `category_id`,
  `category`, `person_id`, `person`, `tags` as `;`-separated names) and `tags.csv`; README explains them.
  `transactions.csv` is unchanged.

## 3. Reading a receipt (backend)

New module `app/receipt_ai.py`, endpoint `POST /api/v1/receipts/read` (multipart: `file`):

- **Config** (environment, read at start): `INFOMANIAK_AI_TOKEN`, `INFOMANIAK_AI_PRODUCT_ID`, `RECEIPT_AI_MODEL`
  (default `google/gemma-4-31B-it`). Missing token or product ID → feature off: `GET /api/v1/receipts/status` says
  `{"enabled": false}` and the frontend hides the button. Values are never logged; error messages name only the
  API path, never the URL with the product ID.
- **Accepted files** (max 10 MB): JPEG/PNG photos (the browser shrinks them to max 1600 px first), PDFs, and e-mails
  as `.eml`. What goes to the AI:
  - **Photo:** the image.
  - **PDF:** its text (`pypdf`) when it has a text layer, otherwise its pages rendered as images (`pypdfium2`), at
    most 5 pages.
  - **E-mail:** the text of the message (plain text, or HTML reduced to text, with the Python standard library's
    `email` package); a PDF or image attached to the mail is read as above instead when the body has no amounts.
  Other types → error "Diese Datei kann nicht gelesen werden".
- **Request to the AI:** the content above, a prompt (in the person's language) with the family's EXPENSE category
  names and tag names, asking for JSON: shop, date, total, items (name, amount, category, tags; several tags allowed).
  Temperature 0, timeout 60 s. The prompt tells the model to leave out loyalty-card and card numbers.
- **The answer is untrusted data:** parsed as JSON; amounts must be numbers; an unknown category → Unsortiert; unknown
  tags are dropped; names are cut to 120 characters; at most 100 items. The endpoint returns a **draft** (nothing
  saved): `shop`, `date`, `total`, `items`, and `difference` (total minus sum of items, if not 0).
- **Errors** in the person's language (messages catalog): AI not configured, image too large/not an image, AI service
  unreachable or timed out, answer not readable. The person can always fill the form by hand instead.
- **Limits:** only logged-in people; at most 30 reads per person per hour (protects the spending cap).
- **The file is kept for saving:** `receipts/read` stores it as a *pending* attachment (no booking yet) and returns its
  `attachment_id` with the draft. Booking the receipt links it; pending attachments older than 24 h are deleted (on
  start and once a day). A receipt can also be attached without the AI (feature off, or the person types it).

## 4. Saving a receipt (backend)

- `POST /api/v1/transactions` and `PUT /api/v1/transactions/{id}` accept an optional `items` list
  (`name`, `amount`, `category_id`, `person_id`, `tag_ids`). With items, `amount` and `category_id` of the request are
  ignored and computed (section 1). Checks: categories exist and are EXPENSE, persons exist and are visible to the
  caller, tags exist, sum of items > 0, at most 100 items. `PUT` with `items: []` turns it back into a plain booking
  (amount and category from the request).
- `GET` transactions returns `items` for itemized bookings, and `attachments` (id, filename, content type, size).
- Attachments: `POST /api/v1/transactions/{id}/attachments` (add a file to a booking), `GET
  /api/v1/attachments/{id}` (the file, with `Content-Disposition` and the stored content type; same visibility as the
  booking), `DELETE /api/v1/attachments/{id}` (same permissions as editing the booking). Booking creation accepts
  `attachment_ids` of pending attachments the same person uploaded. E-mails are served as downloads, never rendered
  as HTML in the app (no scripts or tracking images from mails run in the browser).
- Same permissions as bookings today (own accounts, or shared with "view and manage").
- Tags: `GET/POST/PUT/DELETE /api/v1/tags` (create/rename/delete: parents only, like categories); usage counts.
- Budgets: `POST/PUT /api/v1/budgets` accept `tag_id` instead of `category_id` (exactly one of the two, else 422).

## 5. Frontend

- **Accounts tab → Transactions card:** a new button "📷 Beleg" next to "+ Buchung hinzufügen" (only when the
  feature is on and the account is editable). It opens the receipt form:
  1. Choose a file or take a photo (`accept="image/*,application/pdf,.eml,message/rfc822"`; on the phone the camera
     is offered). The browser shrinks photos to max 1600 px JPEG before upload.
  2. "Wird gelesen…" while the AI works; then the **preview**: date, description (shop), account (preselected),
     person for the whole receipt (applies to all items, each item can change it), and the item list: name, amount,
     category (dropdown), tags (multi-select from the list), person, delete; "+ Position". Shows the sum, the
     receipt total and any difference in red; save is possible only when the sum is > 0.
  3. "Buchen" saves one booking with its items.
  Without AI (or after an error) the same form is filled by hand.
- **Transaction list:** an itemized booking shows "🧾 n Positionen"; clicking shows the items with category, tags,
  person. A booking with attachments shows "📎"; photos open as a preview, PDFs and e-mails download. "✎" opens the
  same item form for editing (add/remove attachments there too); a plain booking can be split into items there.
- **Settings → Tags** (parents): add, rename, icon, delete (with "used by n items"), like Settings → Categories.
- **Analytics:** two new cards, "Ausgaben nach Tag" (list without a sum, with the note that an item with several tags
  counts in each) and "Ausgaben nach Person".
- **Budgets tab:** "+ Budgetlimite festlegen" lets you choose a category **or** a tag; tag budgets show the tag's
  icon and name, with the same progress bar.
- All texts in `de.ts`/`en.ts`; dates via `format.ts`.

## 6. Deployment and secrets

- NAS: `INFOMANIAK_AI_TOKEN`, `INFOMANIAK_AI_PRODUCT_ID`, `RECEIPT_AI_MODEL` in the NAS `.env` (like `SECRET_KEY`),
  passed through `docker-compose.yml`; documented in `.env.example` and `README_DOCKER.md` (empty = feature off).
- The deploy script copies the values from `pass` into the NAS `.env` without printing them, only if the user asks
  for it (otherwise they edit `.env` on the NAS themselves).
- Local development: a run script exports both from `pass` into the backend's environment; no file with the token in
  the repo. Tests never call the real service: the AI client is replaced by a fake in tests.
- The NAS needs outgoing HTTPS to `api.infomaniak.com`.
- Attachments live in `data/attachments/` on the NAS volume (next to `budget.db`), so they survive updates. The
  update script's database backup does **not** cover them; the NAS's own backup of the `data/` folder must (to be
  checked during the deployment, `nas-update.sh` gets a note).

## 7. Tests

- Backend (pytest, TDD): an item with two tags counts in full in each tag total and in each tag budget, once in its
  category, and once in the overall total; items create/update/delete and the booking's computed amount and main category; validation
  (wrong category type, unknown tag/person, empty/negative sums, 100-item limit); permissions; budgets and Analytics
  count items not bookings (no double counting); by tag/by person; tags CRUD and deletion; `items.csv`; the
  `receipts/read` endpoint with a fake AI client: draft mapping, unknown category → Unsortiert, unknown tag dropped,
  difference, malformed AI answers, timeouts, feature off without config, rate limit; no token or product ID in any
  error message or log line; PDF with text, PDF without text (rendered), `.eml` with text body and with a PDF
  attachment, unsupported types; attachments: stored under their id, served only to people who may see the booking,
  deleted with the booking, pending ones cleaned up; tag budgets.
- Browser (Playwright, fake AI via an env switch on the e2e backend): photo → preview → correct an item, give it two
  tags → book → the booking shows its items and 📎; Analytics shows both tag totals; a tag budget shows the amount.

## Calls made by the builder (to check)

- E-mails come in as `.eml` uploads, not through a mailbox the app polls.
- Attachments are not in the analysis ZIP or the JSON backup; they rely on the NAS backup of `data/`.
- Pending attachments (read but not booked) are deleted after 24 h.
- Tags are family-wide and managed by parents, like categories; everyone who can book can use them.
- An itemized booking's own category is its largest item's category ("main category").
- Up to 30 AI reads per person and hour.

## Left to the builder

- Prompt wording and the JSON parsing details; image size limits within the bounds above.
- Exact layout of the receipt form and the Analytics cards, following the existing components.
- How the fake AI client is switched on for the browser tests.
