# Receipt Scan Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Parents photograph a pile of receipts on the phone in one go; the photos wait in the inbox, already read by the AI, and are checked and booked one after another.

**Architecture:** A new table `inbox_photos` (migration 0014) and a module `backend/app/scans.py` with its own routes under `/inbox/photos`. Files sit in `ATTACHMENTS_DIR/inbox` next to the waiting mails. A background runner reads waiting photos one at a time with the existing receipt AI. Opening a photo turns it into the parent's pending attachment, like releasing a mail, and booking that attachment marks the photo booked. In the frontend a scan screen in the inbox card uploads each photo right after it is taken; the inbox lists photos before mails and steps through them with **Book & next**.

**Tech Stack:** FastAPI, SQLAlchemy 2, Alembic, SQLite; React 19, TypeScript, react-i18next; pytest, Playwright.

**Spec:** `docs/superpowers/specs/2026-10-24-receipt-scan-design.md`

## Global Constraints

- Parents only; children get 403 (`inbox.require_parent`, message `only_parents_inbox`).
- Photos are never removed automatically: not by `inbox.sweep` (30 days), not by any orphan clean-up. They leave only when booked or deleted by a parent.
- Migrations keep all data (the NAS database can no longer be wiped); `database_setup.HEAD = "0014"`.
- Scale-down in the browser: long side at most **2400 px**, JPEG; the original file is never sent.
- The hourly AI limit counts for the person who took the photo (`receipt_ai.take_read`, default 30, `RECEIPT_AI_READS_PER_HOUR`); the AI reads in that person's language.
- German and English texts for everything new (`frontend/src/locales/{de,en}.ts`; `npm run lint` checks both have the same keys).
- Invented data only in tests: `files.image_png()`, the fake AI, tiny generated PNGs. The repo is public.
- The mail inbox, the receipt form (including "Paid with this bank booking") and `/receipts/read` keep working as today.

## Review Focus

1. **The inbox sweep deletes photo files.** `inbox.sweep` calls `attachments.remove_orphans(inbox_dir(), waiting)` with mail ids only, so every photo file older than an hour would go. Expected: photo files stay. Test: Task 1 `test_sweep_keeps_photos`.
2. **AI down or over the limit when the photos arrive.** Expected: the upload still succeeds, and the entry is `failed` or `waiting`, never lost. Opening it retries once, then gives an empty draft with the photo attached. Tests: Task 2 `test_ai_down_marks_failed_and_open_still_works`, `test_over_the_limit_waits`.
3. **Booking through the "paid with this bank booking" path (PUT) or with the AI off.** Expected: the photo entry is marked booked either way. Test: Task 1 `test_booking_onto_existing_booking_marks_photo_booked`.
4. **A backend restart while a photo is `reading`.** Expected: it goes back to `waiting` and is read again. Test: Task 2 `test_resume_after_restart`.
5. **A failed upload on the phone.** Expected: the thumbnail shows it as failed with a retry, and the photo is kept in the page until the retry succeeds. Test: Task 4 browser test, upload route made to fail once with `page.route`.

---

### Task 1: Photo entries: storage, routes, booking

**Files:**
- Modify: `backend/app/models.py` (new `InboxPhoto` after `InboxMail`)
- Create: `backend/app/migrations/versions/0014_inbox_photos.py`
- Modify: `backend/app/database_setup.py` (`HEAD = "0014"`)
- Create: `backend/app/scans.py`
- Modify: `backend/app/main.py` (include `scans.router` with prefix `/api/v1`)
- Modify: `backend/app/attachments.py` (`link`, `booked_from_inbox`)
- Modify: `backend/app/inbox.py` (`sweep` keeps photo files)
- Test: `tests/test_scans.py`

**Interfaces:**
- Produces:
  - `models.InboxPhoto`, table `inbox_photos`, with these columns:
    - `id` str uuid pk
    - `person_id` FK users `ondelete=SET NULL`, nullable
    - `taken_at` DateTime, default utcnow
    - `size` int
    - `sha256` str, indexed
    - `read_state` str, default `"waiting"`. The values are `"waiting" | "reading" | "read" | "failed"`.
    - `draft` JSON, nullable
    - `booked_at` DateTime, nullable
  - The file is `inbox.inbox_dir() / photo.id`.
  - `scans.get_photo(db, photo_id) -> models.InboxPhoto`: waiting (unbooked) only, else 404 `inbox_not_found`.
  - `scans.photo_out(db, user, photo) -> dict` with these keys:
    - `id`, `person_id`, `person_name`, `taken_at`, `read_state`
    - `shop`, `total`: from the draft, else null
    - `suggested_account_id`: `inbox.suggested_account(db, user, taker)`
  - Routes, all parents only:
    - `POST /inbox/photos`: multipart `file`, image/jpeg or image/png only, else 400 `file_type_unsupported`; at most `attachments.MAX_BYTES`. Answers `photo_out`.
    - `GET /inbox/photos`: unbooked, **oldest first**.
    - `DELETE /inbox/photos/{id}`: removes the row and its file; answers `{"deleted": id}`.
    - `POST /inbox/photos/{id}/open`: answers `{"draft": dict|None, "attachment_id": str, "attachment": attachments.out(...)}`. In this task it returns the stored draft (or None) and stores the photo as the opener's pending attachment, filename `beleg-<taken_at:YYYY-MM-DD>.jpg` (`.png` for PNG). Task 2 adds the retry.
  - `attachments.booked_from_inbox(db, sha256)` marks both unbooked `InboxMail` and `InboxPhoto` rows with that sha256 booked and deletes their inbox files. `attachments.link` calls it for **every** linked attachment, not only `message/rfc822`.

- [ ] **Step 1: Write the failing tests** in `tests/test_scans.py`. Use invented images only: `files.image_png(text)`, with a different `text` per photo so the hashes differ. The helpers are `scan(client, headers, data, name="scan.jpg")`, which posts to `/inbox/photos`, and `photos(client, headers)`.
  - `test_parents_scan_children_dont`: a parent's POST gives 200, and the entry's `read_state` is `"waiting"` when the AI is off (no `INFOMANIAK_*` env). A child's POST and GET give 403.
  - `test_only_images`: a PDF (`files.pdf_with_text(["x"])`) gives 400; more than `attachments.MAX_BYTES` bytes gives 400.
  - `test_listing_oldest_first_and_both_parents_see_it`: two scans by mum list in upload order, and dad (a second parent) sees the same two.
  - `test_delete_removes_file`: after DELETE the listing is empty and `(inbox.inbox_dir() / id).exists()` is False. A second DELETE gives 404.
  - `test_open_without_ai_then_book_marks_photo_booked`: open gives `draft is None`, and the attachment's `content_type` is `"image/png"`.
    - Booking `POST /transactions` with `attachment_ids=[attachment_id]` (items helper like `test_inbox.book`) leaves the listing empty.
    - The DB row has a `booked_at`, and the file is gone.
  - `test_booking_onto_existing_booking_marks_photo_booked`: after opening, `PUT /transactions/{existing}` with `items` and `attachment_ids` empties the listing.
  - `test_sweep_keeps_photos`: set the photo file's mtime two hours back (`os.utime`), then run `inbox.sweep(db, now=utcnow + 40 days)`. The file still exists, and the photo is still listed.
  - `test_suggested_account`: mum has a receipt booking on account "Mum bank", and the scan by mum suggests that account's id.
- [ ] **Step 2: Run** `pytest tests/test_scans.py -q -p no:warnings`. Expected: every test fails with 404 (no route) or an import error.
- [ ] **Step 3: Implement** the model, migration 0014 (create table plus `ix_inbox_photos_sha256`; downgrade drops them, in the style of 0011) and `HEAD`.
  - Add `scans.py` with the routes above. Use `inbox.require_parent`, `inbox.inbox_dir()` and `attachments.check` for the type; reject any type other than `image/jpeg` or `image/png`.
  - Change `attachments.link` and `booked_from_inbox`.
  - In `inbox.sweep`, pass the mail ids **plus all `InboxPhoto` ids** to `remove_orphans`.
- [ ] **Step 4: Run** `pytest tests/test_scans.py tests/test_inbox.py tests/test_attachments.py -q -p no:warnings`. Expected: all pass.
- [ ] **Step 5: Commit** with the message `feat: photos of receipts wait in the inbox until booked`.

### Task 2: Reading photos in the background

**Files:**
- Modify: `backend/app/receipt_ai.py` (split `read`)
- Modify: `backend/app/scans.py` (runner, upload schedules it, open retries)
- Modify: `backend/app/main.py` (resume at startup and every 15 min)
- Test: `tests/test_scans.py`

**Interfaces:**
- Consumes: Task 1's model, routes and `get_photo`.
- Produces:
  - `receipt_ai.ai_draft(db, filename, data) -> dict`: the lookups, prompt, client call and `parse` taken out of `read`. It raises the same `api_error`s (`file_type_unsupported` 400, `receipt_ai_unavailable` 502, `receipt_ai_unreadable` 502). `read()` becomes: check the file, `take_read`, `attachments.store`, `ai_draft`. Behaviour and order are unchanged; the existing tests prove it.
  - `scans.read_waiting() -> int`: reads with its own `database.SessionLocal()`, so it works in a background thread. It holds a module-level `threading.Lock` acquired **non-blocking**; when the lock is busy it returns 0.
    - It loops over unbooked `waiting` photos oldest first, skipping persons who hit the limit this run and photos whose `person_id` is None.
    - Per photo it sets `reading` and commits, then sets `i18n.set_current(i18n.user_language(taker))`.
    - It calls `take_read(db, taker.id, settings.reads_per_hour)`. A 429 sets the photo back to `waiting` and blocks that person for this run.
    - Then it calls `ai_draft`. Success sets `read` plus `draft`; any `HTTPException` sets `failed`.
    - It returns how many photos it read. It does nothing when `Settings.from_env().enabled` is false.
  - `scans.resume(db) -> None`: sets every `reading` photo back to `waiting`.
  - `POST /inbox/photos` adds `read_waiting` as a FastAPI `BackgroundTasks` task. The TestClient runs it before the call returns, so the tests see the result right away.
  - `POST /inbox/photos/{id}/open`: when the AI is enabled and `read_state != "read"`, it tries once with the **opener's** limit (`take_read` plus `ai_draft`, in `run_in_threadpool`). Success stores the draft and sets `read`; any `HTTPException` leaves the draft None. The answer always has the attachment.
  - `main.py`: at startup, after the sweeps, it calls `scans.resume(db)`. The lifespan loop runs `scans.read_waiting()` every 15 minutes in `asyncio.to_thread`, as a separate task next to `sweep_daily`, and once at startup.

- [ ] **Step 1: Write the failing tests** with the `ai` fixture pattern from `tests/test_inbox.py`: the env vars plus `monkeypatch.setattr(receipt_ai, "client_for", lambda s: fake)`.
  - `test_upload_reads_in_background`: after a scan, the listing shows `read_state == "read"`, `shop == "Migros"` and `total == 3.5`, and `fake.calls == 1`. Opening returns that draft **without** another AI call (`fake.calls == 1`).
  - `test_reads_in_takers_language`: dad's language is set to `"de"` (`PATCH /me` as in the existing language tests), and the prompt the fake receives contains German text. Use a fake that records `content`, and assert the prompt matches `receipt_ai.prompt(..., "de")`'s first words.
  - `test_ai_down_marks_failed_and_open_still_works`: when the fake raises `receipt_ai.AiUnavailable`, the entry is `failed`. Opening calls the fake once more (it still fails) and answers `draft is None` with an attachment. If the fake then answers, a second open gives the draft.
  - `test_over_the_limit_waits`: with `RECEIPT_AI_READS_PER_HOUR=1`, two scans by mum give `["read", "waiting"]`.
    - Opening the waiting one as dad uses **dad's** limit and reads it.
    - Calling `scans.read_waiting()` with mum still over the limit returns 0.
  - `test_resume_after_restart`: set a photo's `read_state = "reading"` in the DB. After `scans.resume(db)` and `scans.read_waiting()`, it is `read`.
  - `test_receipts_read_unchanged`: `POST /receipts/read` with `image_png()` still answers draft plus attachment, and counts one read.
- [ ] **Step 2: Run** `pytest tests/test_scans.py -q -p no:warnings`. Expected: the new tests fail (`read_state` stays `"waiting"`, no `resume`).
- [ ] **Step 3: Implement** the split, the runner, the open retry and the startup and loop hooks as in Interfaces.
- [ ] **Step 4: Run** `pytest tests/test_scans.py tests/test_receipt_ai.py tests/test_inbox.py tests/test_receipt_concurrency.py -q -p no:warnings`. Expected: all pass. Then run the full suite: `pytest -n auto -q -p no:warnings`.
- [ ] **Step 5: Commit** with the message `feat: the AI reads scanned receipts in the background`.

### Task 3: Scan screen

**Files:**
- Create: `frontend/src/scan.ts` (scale-down and upload)
- Create: `frontend/src/components/ScanReceipts.tsx`
- Modify: `frontend/src/components/Inbox.tsx` (always shown for parents; **📷 Scan receipts** button; scan view)
- Modify: `frontend/src/components/Transactions.tsx` (optional `onScan?: () => void` prop; a **📷 Scan receipts** button next to the receipt button, only when given)
- Modify: `frontend/src/pages/dashboard/Dashboard.tsx` (`scanning` state: passes `onScan` to Transactions for parents, then `scanning` and `onScanDone` to Inbox; scrolls to the top when scanning starts)
- Modify: `frontend/src/locales/en.ts`, `frontend/src/locales/de.ts` (keys under `scan.*`)

**Interfaces:**
- Consumes: `POST /api/v1/inbox/photos` (Task 1).
- Produces:
  - `scaleDown(file: File, maxSide = 2400): Promise<Blob>`: JPEG at quality 0.85 via `createImageBitmap` and a canvas. An image already within `maxSide` is still re-encoded as JPEG.
  - `uploadPhoto(blob: Blob): Promise<InboxPhoto>`: posts the multipart field `file` with filename `scan.jpg`.
  - `ScanReceipts({ onDone }: { onDone: () => void })`:
    - The input is `<input type="file" accept="image/*" capture="environment">` with the aria-label `t('scan.camera')` ("Receipt photo"), triggered by **📷 Next receipt** (`t('scan.next')`). The first tap reads **📷 First receipt**.
    - Thumbnails come from object URLs, with the states `uploading` / `done` / `failed`. A failed one shows **Retry** (`t('scan.retry')`) and keeps its Blob until it succeeds.
    - **Done (n)** (`t('scan.done', { count })`) calls `onDone`. It is disabled while an upload is running and asks to confirm if any upload failed (`t('scan.confirmFailed')`).
  - `InboxPhoto` type in `frontend/src/inbox.ts`, matching `photo_out`.

- [ ] **Step 1: Implement** `scan.ts`, `ScanReceipts.tsx` and the wiring. The Inbox card is always rendered for parents: when it's empty it shows only the title `t('inbox.titleEmpty')` ("📥 Inbox") and the scan button. Upload each photo as soon as its input `change` fires. The scan view and the inbox card must work at 360 px width without horizontal scrolling (the spec's "usable at phone width"); **Done** closes the scan view, and the inbox shows the new photos.
- [ ] **Step 2: Run** `cd frontend && npm run lint && npm run type-check && npm run build`. Expected: clean, including the de/en key check.
- [ ] **Step 3: Commit** with the message `feat: scan screen for photographing a pile of receipts`. Its browser test is in Task 4, which covers the whole flow.

### Task 4: Checking photos in the inbox, and the browser test

**Files:**
- Modify: `frontend/src/inbox.ts` (`usePhotos(enabled, version)`, `openPhoto(photo): Promise<Release>`, `deletePhoto(photo)`)
- Modify: `frontend/src/components/Inbox.tsx` (photo rows before mails; check view)
- Modify: `frontend/src/components/ReceiptForm.tsx` (optional props `submitLabel?: string`, `onSkip?: () => void`)
- Modify: `frontend/src/locales/en.ts`, `frontend/src/locales/de.ts`
- Create: `e2e/tests/receipt-scan.spec.ts`
- Modify: `e2e/README.md` (test table row)
- Modify: `README.md` or `README_DOCKER.md`, wherever receipts by mail are described: one paragraph on scanning, and the phone gallery test from the spec's acceptance.

**Interfaces:**
- Consumes: Task 1 and 2 routes; Task 3's `InboxPhoto`.
- Produces: the check flow.
  - **Photo row:** who took it and when, `read_state` text (`t('scan.state.<state>')`), shop and total when read. There's an account select (`t('scan.account', { n })`) defaulting to `lastAccount ?? suggested_account_id`, plus **Check** and **Delete** (with a confirmation).
  - **Check next** above the list opens the oldest photo with an account.
  - **Check view:**
    - An account select above the form, then `ReceiptForm` with the draft and attachment from `openPhoto`. The account select keeps the form (no `key` change).
    - The form shows `submitLabel = t('scan.bookNext')` ("Book & next") and **Skip**.
    - Booking sets `lastAccount` and opens the next unbooked photo after this one in the list. Skip opens the next without booking. When none is left, the view returns to the list. Cancel also returns to the list.
  - Mails keep their current rows and release flow below the photos.

- [ ] **Step 1: Write the browser test** `e2e/tests/receipt-scan.spec.ts` (fake AI; invented images):
  - Set up a new parent with a `BANK` account "Konto" and log in.
  - Tap **📷 Scan receipts** and feed two distinct 1×1 PNGs to `getByLabel('Receipt photo')`, one after another. The PNGs in base64:
    - black: `iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAIAAACQd1PeAAAADElEQVR4nGNgYGAAAAAEAAH2FzhVAAAAAElFTkSuQmCC`
    - red: `iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAIAAACQd1PeAAAADElEQVR4nGP4z8AAAAMBAQDJ/pLvAAAAAElFTkSuQmCC`
  - Make the **first** upload fail once with `page.route('**/api/v1/inbox/photos', ...)`, which aborts one call and continues the rest. Expect **Retry**, click it, and expect two done thumbnails.
  - Click **Done (2)** and expect two photo rows, both read, showing "Migros" and "CHF 83.40".
  - Click **Check next** and expect `Sum CHF 83.40`. Click **Book & next**, and the second photo opens. Click **Book & next** again.
  - Expect the photo rows gone, and `GET /accounts/{id}/transactions` to return 2 bookings, each with 2 items and 1 attachment.
  - `errors` is empty.
- [ ] **Step 2: Run** `cd e2e && E2E_PYTHON=../.venv-e2e/bin/python npx playwright test receipt-scan`. Expected: FAIL, because the check flow and rows don't exist yet (Task 3's screen exists).
- [ ] **Step 3: Implement** the hooks, rows, check view and ReceiptForm props as in Interfaces, the texts in de and en, and the README rows.
- [ ] **Step 4: Run** the new browser test (PASS), then the whole check:
  - `pytest -n auto -q -p no:warnings`
  - black, flake8 and mypy as in CI
  - `cd frontend && npm run lint && npm run type-check && npm run build`
  - `cd e2e && E2E_PYTHON=../.venv-e2e/bin/python npm test`

  Expected: everything green.
- [ ] **Step 5: Commit** with the message `feat: check scanned receipts one after another in the inbox`.

## After the PR

The user tests on the **Samsung and the Pixel**, on the home Wi-Fi after deploying, that photos taken with **📷 Scan receipts** don't show up in the phone's gallery. If the Samsung keeps copies, open an issue for HTTPS on the NAS plus an in-page camera (spec, "Camera").
