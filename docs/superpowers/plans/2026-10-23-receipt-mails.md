# Receipt Mails by Forwarding Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Receipt mails forwarded by family members to `invoice@frankfamily.xyz` land unopened in a parents' inbox in
the app; a parent releases one, the AI reads it, and it is booked with the existing receipt form.

**Architecture:** A Cloudflare Email Worker (`cloudflare/email-worker/`) accepts only mails Cloudflare marked
`dmarc=pass` and posts them through the tunnel (Access service token + shared secret) to `POST /api/v1/inbound`. The
backend (`app/inbox.py`) reads only the headers, matches `From:` against registered person addresses, and stores the raw
mail under `ATTACHMENTS_DIR/inbox/`. Release turns it into a pending attachment, reads it with the existing receipt
reading, and booking links it like any receipt attachment.

**Tech Stack:** FastAPI, SQLAlchemy 2, Alembic, pytest; React 19 + TypeScript + react-i18next; Cloudflare Workers
(TypeScript, Vitest, wrangler); Playwright.

**Spec:** `docs/superpowers/specs/2026-10-23-receipt-mails-design.md`

## Global Constraints

- Nothing in a received mail is decoded beyond its headers and MIME structure until a parent releases it (no Pillow,
  pypdf, pypdfium2, no AI on arrival).
- Only `POST /api/v1/inbound` works without a login; it needs `X-Inbound-Secret` equal to `INBOUND_SECRET`
  (`hmac.compare_digest`). `INBOUND_SECRET` empty → 503.
- Mail size limit 10 MB (`attachments.MAX_BYTES`); inbox retention 30 days.
- Inbox: parents only (children 403). Release counts against the releasing parent's hourly AI limit.
- Addresses: several per person, unique, stored lowercased.
- Never log or return the secret, the Access token, or mail content; log lines name only the path.
- No real mail addresses, receipts or bank data in tests or docs (public repo): use `example.ch` addresses.
- All user-facing texts in German and English (`app/messages.py`, `frontend/src/locales/de.ts`, `en.ts`);
  `npm run lint` runs the text check.
- Migrations: this plan adds 0011; `database_setup.HEAD = "0011"`.

## Review Focus

1. `From:` with a display name, upper case, or two addresses (`From: a@x.ch, b@y.ch`) → the single address,
   lowercased, is matched; two addresses → 403 (no person can be both). Test in Task 2.
2. A mail without `Message-ID` → a stable id from the SHA-256 of the raw mail, so a second delivery is still a
   duplicate. Test in Task 2.
3. Malformed or non-UTF-8 headers → stored with subject `?`, never a 500. Test in Task 2.
4. The forwarding person is removed or deactivated after arrival → the entry stays visible to parents, without an
   account suggestion. Test in Task 3.
5. Two parents release the same entry (or one releases twice) → each gets their own pending attachment; booking one
   marks the entry booked; the other pending attachment is swept after a day. Test in Task 3.

---

### Task 1: Person e-mail addresses and the inbox tables

**Files:**
- Modify: `backend/app/models.py` (new `UserEmail`, `InboxMail`)
- Create: `backend/app/migrations/versions/0011_receipt_mails.py`
- Modify: `backend/app/database_setup.py` (`HEAD = "0011"`)
- Create: `backend/app/emails_api.py`; Modify: `backend/app/main.py` (include router), `backend/app/schemas.py`,
  `backend/app/messages.py`
- Test: `tests/test_person_emails.py`

**Interfaces:**
- Produces:
  - `models.UserEmail`: `id`, `user_id` (FK users, ondelete CASCADE, index), `address` (unique, lowercased).
  - `models.InboxMail`: `id`, `person_id` (FK users, ondelete SET NULL, nullable), `from_addr`, `subject`,
    `sent_at` (nullable), `received_at`, `message_id` (unique), `attachment_names` (JSON list of str), `size`,
    `attachment_id` (FK attachments, ondelete SET NULL, nullable), `booked_at` (nullable).
  - `GET /api/v1/emails` → `[{id, user_id, address}]` (parents); `POST /api/v1/users/{user_id}/emails`
    `{address}` → the row; `DELETE /api/v1/emails/{id}` → `{"deleted": id}`.
  - `emails_api.person_for(db, address: str) -> Optional[models.User]`: the active person with that address.
  - Message keys: `only_parents_emails`, `email_invalid`, `email_taken`, `email_not_found`.

- [ ] **Step 1: Write the failing tests** in `tests/test_person_emails.py`:
  - `test_parent_adds_and_lists_addresses`: `POST /users/{mum}/emails {"address": "Mum@Example.CH"}` → 200,
    `address == "mum@example.ch"`; `GET /emails` lists it with `user_id == mum`.
  - `test_several_addresses_per_person` (two for mum → both listed).
  - `test_address_belongs_to_one_person`: same address for dad → 400 "That e-mail address is already registered".
  - `test_invalid_address`: `"not-an-address"` → 400 `email_invalid` text.
  - `test_children_cannot_manage`: child → 403 on GET/POST/DELETE.
  - `test_delete_address` and `test_removing_a_person_removes_their_addresses` (DELETE /users/{id}).
  - `test_person_for`: matches case-insensitively; an inactive person → `None`.
- [ ] **Step 2:** Run `pytest tests/test_person_emails.py -q -p no:warnings`. Expected: FAIL (404 / import error).
- [ ] **Step 3:** Add the models, migration 0011 (both tables, indexes, downgrade drops them), the router (parents
  only, `address` validated with a simple `^[^@\s]+@[^@\s]+\.[^@\s]+$` after `strip().lower()`), messages de/en.
- [ ] **Step 4:** Run the test file, then `pytest tests -q -p no:warnings`. Expected: all pass (the migration tests
  in `tests/test_database.py` compare the models with the migrations).
- [ ] **Step 5: Commit** `feat: e-mail addresses for family members (#57)`.

### Task 2: Receiving a mail (`POST /api/v1/inbound`)

**Files:**
- Create: `backend/app/inbox.py`; Modify: `backend/app/main.py` (router, startup log line
  `"Receipt mails: configured"` / `"not configured (INBOUND_SECRET empty)"`), `backend/app/messages.py`
- Test: `tests/test_inbound.py`, helper `tests/mails.py` (builds raw mails with the stdlib `email` package)

**Interfaces:**
- Consumes: `emails_api.person_for`, `models.InboxMail`, `attachments.directory()`, `attachments.MAX_BYTES`.
- Produces:
  - `inbox.inbox_dir() -> Path` = `attachments.directory() / "inbox"` (a subfolder, so `attachments.sweep`'s
    orphan-file cleanup, which only looks at files, leaves it alone).
  - `@dataclass MailSummary(from_addrs: list[str], subject: str, sent_at: Optional[datetime], message_id: str,
    attachment_names: list[str])`
  - `inbox.summary(raw: bytes) -> MailSummary`: headers and MIME part names only (`email.message_from_bytes` with
    `policy.default`, walk parts reading only `get_filename()`); missing `Message-ID` →
    `"sha256:" + hexdigest(raw)`; unreadable subject → `"?"`.
  - `inbox.receive(db, raw: bytes) -> Optional[models.InboxMail]` (None = duplicate; raises 403
    `inbound_sender_unknown` unless exactly one `From:` address belongs to an active person).
  - Endpoint responses: `{"status": "stored", "id": …}` / `{"status": "duplicate"}`.

- [ ] **Step 1: Write the failing tests** in `tests/test_inbound.py` (secret set with `monkeypatch.setenv`):
  - `test_off_without_secret` → 503; `test_wrong_secret` → 401; `test_too_big` (10 MB + 1) → 413.
  - `test_unknown_sender_is_refused` → 403, no `InboxMail`, no file in `inbox_dir()`.
  - `test_inactive_person_is_refused` → 403.
  - `test_registered_sender_lands_in_the_inbox`: `From: "Mum" <MUM@example.ch>`, a PDF attachment `beleg.pdf` →
    entry with `person_id == mum`, `from_addr == "mum@example.ch"`, `attachment_names == ["beleg.pdf"]`, raw file
    stored, `size == len(raw)`.
  - `test_two_from_addresses_are_refused` → 403 (Review Focus 1).
  - `test_duplicate_message_id` → second post `{"status": "duplicate"}`, one entry.
  - `test_no_message_id_is_still_deduplicated` (Review Focus 2).
  - `test_malformed_headers` (bytes `\xff` in the subject, broken `Date:`) → stored, subject `?` or decoded text,
    `sent_at` None (Review Focus 3).
  - `test_nothing_is_decoded_on_arrival`: monkeypatch `receipt_files.ai_content` and `PIL.Image.open` to raise;
    a mail with a broken PNG attachment → still 200.
  - `test_secret_never_in_response_or_log` (caplog).
- [ ] **Step 2:** Run `pytest tests/test_inbound.py -q -p no:warnings`. Expected: FAIL (404).
- [ ] **Step 3:** Implement `inbox.py` (`summary`, `receive`, the endpoint; size checked from `Content-Length` and
  the body, as in family-job-tracking's `inbox_api.receive_mail`), messages de/en, router and startup log in
  `main.py`.
- [ ] **Step 4:** Run the file, then the whole suite. Expected: all pass.
- [ ] **Step 5: Commit** `feat: receive forwarded receipt mails into an inbox (#57)`.

### Task 3: Inbox list, delete, release and booking

**Files:**
- Modify: `backend/app/inbox.py`, `backend/app/receipt_ai.py` (extract the reading), `backend/app/attachments.py`
  (`link` marks the inbox entry booked), `backend/app/main.py` (sweep), `backend/app/messages.py`
- Test: `tests/test_inbox.py`

**Interfaces:**
- Consumes: Task 2's `InboxMail` rows and files; `attachments.store`, `attachments.link`; `receipt_ai.take_read`.
- Produces:
  - `receipt_ai.read(db, user, filename: str, data: bytes) -> dict` → `{"draft": dict, "attachment_id": str}`:
    the body of today's `read_receipt` (check, `ai_content`, `take_read`, `store`, AI, `parse`);
    `read_receipt` calls it.
  - `GET /api/v1/inbox` → `[{id, person_id, person_name, from_addr, subject, sent_at, received_at,
    attachment_names, size, suggested_account_id}]`, unbooked entries, newest first, parents only.
  - `DELETE /api/v1/inbox/{id}` → `{"deleted": id}` (row and file).
  - `POST /api/v1/inbox/{id}/release` → `{"draft": dict | null, "attachment_id": str}`: AI configured →
    `receipt_ai.read(db, parent, "<subject>.eml", raw)`; otherwise `attachments.store(...)` and `draft: null`.
    Sets `InboxMail.attachment_id`.
  - `inbox.suggested_account(db, releaser, forwarder: Optional[models.User]) -> Optional[str]`: the account of the
    forwarder's most recent booking with items, else their first account (by name); `None` when the releaser can't
    write it or there is no forwarder.
  - `inbox.sweep(db, now=None) -> int`: deletes unbooked entries older than 30 days with their files; booked entries'
    files are removed when booked.
  - In `attachments.link`: an `InboxMail` whose `attachment_id` is the linked attachment gets `booked_at = now` and
    its inbox file removed.
  - Message keys: `only_parents_inbox`, `inbox_not_found`.

- [ ] **Step 1: Write the failing tests** in `tests/test_inbox.py` (use the `ai` fixture style of
  `tests/test_receipt_ai.py`, a `received(client, sender)` helper that posts to `/inbound`):
  - `test_parents_see_the_inbox_children_dont` (child → 403).
  - `test_listing_shows_headers_only` (fields above, newest first).
  - `test_delete` (row and file gone; second delete → 404).
  - `test_release_reads_with_the_ai`: draft items from the fake answer; `attachment_id` is a pending attachment of
    the releasing parent; the reading counted for that parent (`RECEIPT_AI_READS_PER_HOUR=1` → a second release by
    the same parent → 429, by the other parent → 200).
  - `test_release_without_ai` → `draft is None`, attachment stored, AI client never called.
  - `test_booking_marks_the_entry_booked`: book via `POST /transactions` with `items` and
    `attachment_ids=[attachment_id]` → entry gone from `GET /inbox`, booking has the `.eml` attachment, inbox file
    removed; posting the same mail again → duplicate.
  - `test_release_twice_and_two_parents` (Review Focus 5).
  - `test_account_suggestion`: forwarder's account of their latest itemized booking; none yet → first account;
    releaser can't write it → `None`.
  - `test_forwarder_removed_keeps_the_entry` (Review Focus 4): `DELETE /users/{dad}` → entry listed,
    `person_id None`, `suggested_account_id None`.
  - `test_sweep_after_30_days` (29 days kept, 31 days removed with file; booked entries not listed anyway).
- [ ] **Step 2:** Run `pytest tests/test_inbox.py -q -p no:warnings`. Expected: FAIL.
- [ ] **Step 3:** Implement as in Interfaces; call `inbox.sweep` next to `attachments.sweep` at startup and in
  `sweep_daily`.
- [ ] **Step 4:** Run the file, `tests/test_receipt_ai.py`, then the whole suite. Expected: all pass.
- [ ] **Step 5: Commit** `feat: release inbox mails to the receipt form (#57)`.

### Task 4: Frontend: addresses, inbox and release

**Files:**
- Create: `frontend/src/inbox.ts` (types `InboxMail`, hook `useInbox()` → `{mails, reload}`),
  `frontend/src/components/Inbox.tsx`, `frontend/src/components/EmailAddresses.tsx`
- Modify: `frontend/src/components/FamilyManager.tsx` (addresses per person), `frontend/src/components/ReceiptForm.tsx`,
  `frontend/src/pages/dashboard/Dashboard.tsx`, `frontend/src/locales/de.ts`, `frontend/src/locales/en.ts`
- Test: `e2e/tests/receipt-mails.spec.ts`, `e2e/playwright.config.ts` (`INBOUND_SECRET: 'e2e-inbound'`)

**Interfaces:**
- Consumes: Task 1 and Task 3 endpoints.
- Produces:
  - `ReceiptForm` new optional props: `draft?: Draft`, `attachment?: AttachmentInfo` (preset pending attachment,
    sent in `attachment_ids`). With them the form starts filled, exactly as after a file upload today.
  - `Inbox` (parents only, on the overview tab above the accounts, hidden when empty): heading
    `📥 {{count}} receipts waiting` / `📥 {{count}} Belege warten`; per entry forwarder, sender, subject, date,
    attachment names; an account select (accounts the parent may write; preselected `suggested_account_id`),
    **Release** and **Delete** (with confirm). Release posts `/inbox/{id}/release` and renders `ReceiptForm` with
    the chosen account, `draft` and `attachment`; saving reloads the inbox and the accounts.
  - Settings → Family: per person a list of addresses with add and remove.
- [ ] **Step 1: Write the failing browser test** `e2e/tests/receipt-mails.spec.ts`:
  `a forwarded receipt mail is released, read and booked`: new parent, account `Migros` (CLEARING), address
  `<parent.name>@example.ch` via `POST /users/{id}/emails`; post a raw mail from that address to
  `${BACKEND}/api/v1/inbound` with header `X-Inbound-Secret: e2e-inbound`; log in; expect
  `📥 1 receipts waiting` (or the plural form you define); select `Migros`; **Release**; expect
  `Name of item 2` = `Velo-Hose` (fake AI); **Book**; expect the inbox gone and the booking with `📎 1`.
- [ ] **Step 2:** Run `cd e2e && E2E_PYTHON=../.venv-e2e/bin/python npx playwright test receipt-mails`.
  Expected: FAIL (no inbox).
- [ ] **Step 3:** Implement the components and texts (de and en, keys under `inbox.*` and `family.emails*`).
- [ ] **Step 4:** Run `cd frontend && npm run lint && npm run type-check && npm run build`, then all browser tests.
  Expected: all pass.
- [ ] **Step 5: Commit** `feat: receipt mail inbox and e-mail addresses in the app (#57)`.

### Task 5: Cloudflare Email Worker with the DMARC check

**Files:**
- Create: `cloudflare/email-worker/` (`package.json`, `package-lock.json`, `tsconfig.json`, `vitest.config.ts`,
  `wrangler.toml`, `src/index.ts`, `src/notice.ts`, `test/index.test.ts`, `test/notice.test.ts`,
  `test/cloudflare-email.ts`), copied from `/home/andreas/work/family-job-tracking/cloudflare/email-worker` and adapted
  (name `family-budget-inbound`, path `/api/v1/inbound`, header `X-Family-Budget-Error`, texts in German)
- Modify: `.github/workflows/ci-cd.yml` (job `Email Worker Tests`: `npm ci`, `npm test`, `npm run type-check` in
  `cloudflare/email-worker`)

**Interfaces:**
- Consumes: Task 2's endpoint and its status codes (200 stored/duplicate, 403 unknown sender, 413, 5xx).
- Produces:
  - `export const AUTHSERV_ID: string` (Cloudflare's authserv-id, pinned in Step 0).
  - `export function dmarcPassed(rawHeaders: string, fromHeader: string): boolean`: takes the **first**
    `Authentication-Results` header (unfolded) in the raw header block; true only if its authserv-id is
    `AUTHSERV_ID`, it contains `dmarc=pass`, and its `header.from` equals the domain of the `From:` address.
  - `deliver(message, env, fetchImpl)`: `dmarcPassed` false → `setReject("Absender nicht bestätigt")`, no fetch;
    app 403 → `setReject("Nicht angenommen")`, **no** fallback; app unreachable, 5xx, 413, 401, 302 → fallback or
    reject, as in family-job-tracking.

- [ ] **Step 0: Pin Cloudflare's header with a real mail (needs the user).** Ask the user to add a temporary Email
  Routing rule forwarding a test address (e.g. `test@frankfamily.xyz`) to their own mailbox, send one mail to it from
  GMX, and paste the `Authentication-Results` / `ARC-Authentication-Results` lines from the received mail's source
  (addresses may be redacted). Pin `AUTHSERV_ID` and the header name from that; note the result in the ledger. The
  user removes the rule afterwards. Do not read the user's mailbox yourself.
- [ ] **Step 1: Write the failing tests** in `test/index.test.ts`: posts with `dmarc=pass` from Cloudflare's header
  (URL ends in `/api/v1/inbound`; secret, Access headers, `redirect: 'manual'`); rejects without posting for
  `dmarc=fail`, `dmarc=none`, no header, `header.from` of another domain, and a forged
  `Authentication-Results: evil.example; dmarc=pass` **below** Cloudflare's failing one; app 403 → reject, fallback
  not used; app 500/413/401/302 and unreachable → fallback (with `FALLBACK_ADDRESS`) or reject (without).
- [ ] **Step 2:** Run `cd cloudflare/email-worker && npm ci && npm test`. Expected: FAIL.
- [ ] **Step 3:** Implement `dmarcPassed` and the changes in `deliver`; read the raw mail once into an
  `ArrayBuffer`, take the header block (up to the first empty line) for the check, post the same bytes.
- [ ] **Step 4:** Run `npm test && npm run type-check`. Expected: PASS.
- [ ] **Step 5: Commit** `feat: Cloudflare Email Worker for receipt mails with DMARC check (#57)`.

### Task 6: Configuration and setup guide

**Files:**
- Modify: `.env.example`, `docker-compose.yml` (`INBOUND_SECRET=${INBOUND_SECRET:-}`), `README_DOCKER.md` (section
  "Receipt mails (Cloudflare Email Worker)"), `README.md` (one paragraph, link to it)
- Test: `tests/test_inbound.py::test_compose_passes_the_secret` (reads `docker-compose.yml`, asserts
  `INBOUND_SECRET` is passed to the backend), plus the existing documentation check in CI

**Interfaces:**
- Consumes: everything above.

- [ ] **Step 1: Write the failing test** `test_compose_passes_the_secret`. Step 2: run it, Expected: FAIL.
- [ ] **Step 3:** Write the guide, modeled on family-job-tracking's "Incoming e-mails" section, for
  `invoice@frankfamily.xyz`: `INBOUND_SECRET` in `.env`; Access service token `family-budget-inbound` with a
  Service Auth policy; a tunnel public hostname (e.g. `budget-inbound.<domain>`) whose ingress has `path:
  ^/api/v1/inbound$` and a catch-all `http_status:404`; an Access application on that hostname and path; the two
  `curl` checks; deploying the worker and `wrangler secret put` for `APP_URL`, `INBOUND_SECRET`,
  `CF_ACCESS_CLIENT_ID`, `CF_ACCESS_CLIENT_SECRET`, optional `FALLBACK_ADDRESS`; the Email Routing rule
  `invoice` → Worker; registering the parents' addresses in Settings → Family; a test with a real forwarded mail.
  Note that `data/attachments/inbox` is part of the attachments backup.
- [ ] **Step 4:** Run the test and the whole suite, lint, type-check, build, worker tests, browser tests.
  Expected: all pass.
- [ ] **Step 5: Commit** `docs: set up receipt mails (#57)`.
