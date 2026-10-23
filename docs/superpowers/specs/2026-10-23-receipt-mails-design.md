# Receipt mails by forwarding

Date: 2026-10-23. Status: draft, for review. Issue: #57.

## Why

Many receipts arrive by e-mail (webshop orders, invoices). Today a parent saves the mail as `.eml` and uploads it in
the receipt form. Instead, a parent should just **forward the mail to `invoice@frankfamily.xyz`** and later book it in
the app with the AI draft they already know from photos and PDFs (issue #56).

The app is otherwise reachable only in the home network. Taking mail from the internet adds an entry point, so the
design is mostly about **who can get a mail in** and **when its content is opened**.

## Goals

- **Forward → inbox:** a mail forwarded to `invoice@frankfamily.xyz` by a registered family member lands in an
  **inbox** in the app, assigned to the person who forwarded it.
- **Only verified senders:** the mail is taken only when the sender's address is registered for a person **and**
  the mail is authenticated (`dmarc=pass`). Everything else is rejected.
- **Manual release:** nothing in the mail is opened (no image or PDF decoding, no AI) until a **parent releases** it.
  Release starts the existing flow: the AI reads it, the parent checks the draft (items, tags, persons) and books it.
- **The mail is kept** as the booking's attachment, like a hand-uploaded `.eml` today.
- **Account suggestion:** at release the parent picks the account; the suggestion is the forwarding person's account.

## Non-goals (first version)

- Mails from shops directly to the address (only forwarded by family members; the shop's address is never on the
  allow list).
- Automatic AI reading on arrival.
- Notifications (push, e-mail) about new inbox mails; the inbox shows a counter in the app.
- Learning the account from the shop ("Galaxus → credit card").
- Children seeing or releasing inbox mails.
- `+tag` subaddresses (e.g. `invoice+velo@`) to preset tags or accounts.

## Anti-goals (would make it a failure even if it works)

- **A forged sender gets a mail in.** The `From:` line and the envelope sender are plain text; a check that only
  compares addresses is not a check.
- **Content from the internet is decoded or sent to the AI before a parent looked at the inbox entry.** Image and PDF
  decoders on the NAS are the attack surface (see the Pillow CVEs of 2026-10-23); the AI costs money and can be steered
  by a crafted mail.
- **The rest of the app becomes reachable from the internet.** Only the inbound endpoint is exposed, behind Cloudflare
  Access; login, API and frontend stay home-network only.
- **A mail is lost silently** (app down, mail too big): the sender gets a bounce, or it goes to a fallback address.
- Secrets (inbound secret, Access token) in the repo, in logs or in error messages.

## Decided with the user

- Forwarding to `invoice@frankfamily.xyz` (Cloudflare Email Routing) → Cloudflare Email Worker → Cloudflare Tunnel →
  NAS, the same way as in `/home/andreas/work/family-job-tracking`.
- Only registered e-mail addresses may send; the check happens at Cloudflare (Worker) with `dmarc=pass`; the app
  assigns the mail to the person ("only needs to assign it to the right releaser").
- Manual release in the inbox, then the AI reads.
- **All parents** see the inbox and may release or delete; children don't forward.
- At release the parent **picks the account**; the default comes from the **forwarding person** ("only the one who
  got the mail is the most likely owner of the bought items"), not from the shop.

## 1. Sender check: Worker and Cloudflare

**What Cloudflare does by itself.** Email Routing checks SPF, DKIM and DMARC on every incoming mail and writes the
result into an `Authentication-Results` header. It rejects a mail only when it fails the sender domain's DMARC policy
or fails both SPF and DKIM. With a domain policy of `p=none` (gmail.com and bluewin.ch on 2026-10-23; gmx.ch has
`p=quarantine`) a forged `From:` gets through, because SPF only checks the envelope sender, which the attacker
controls. Therefore:

**The Worker enforces `dmarc=pass`.** It reads the `Authentication-Results` header **that Cloudflare added** and
rejects the mail (`setReject`) unless it says `dmarc=pass` for the domain of the `From:` address.

- Only Cloudflare's own result counts. A mail can carry `Authentication-Results` headers of its own (forged, or from
  an earlier hop of a forwarded mail); the Worker must take the one Cloudflare added (its authserv-id, the topmost
  one) and ignore the others. How exactly Cloudflare's header looks in the Worker (`Authentication-Results` vs
  `ARC-Authentication-Results`, its authserv-id) is **verified with a real mail before the check is written**, and
  the test suite covers a mail with a forged extra header.
- `dmarc=pass` proves the domain, not the mailbox. Big providers (GMX, Gmail, Bluewin) don't let their users send with
  someone else's address, so the remaining gap is small and accepted.

**The allow list lives in the app.** The Worker keeps no list of addresses: it posts every mail that passed DMARC to
the app, and the app answers whether the `From:` address belongs to a registered person. If the app refuses
(unknown sender), the Worker rejects the mail with a neutral reason ("not accepted"), so the sender gets a bounce.
Addresses are maintained in one place, the app.

**Worker → NAS** as in family-job-tracking:
- Cloudflare Tunnel to a **separate hostname** (e.g. `budget-inbound.frankfamily.xyz`) whose tunnel ingress and Access
  application cover **only** the inbound path; every other path on it answers 404.
- Cloudflare Access with a **service token** (Service Auth policy) in front of that path.
- A shared **`INBOUND_SECRET`** in the `X-Inbound-Secret` header, compared in constant time by the app.
- The Worker sends the raw mail (`message/rfc822`) and the envelope recipient; `redirect: 'manual'` so a bad token
  isn't followed to the Access login page.

**When the app can't take a mail** (unreachable, refused, too big): as in family-job-tracking, the Worker forwards it to
an optional **fallback address** (a verified Email Routing destination outside the domain) with a header saying why,
plus a short note; without a fallback it rejects the mail. An unknown sender is **not** forwarded to the fallback;
it is only rejected.

## 2. Receiving (backend)

`POST /api/v1/inbound` (no login; secret as above):
- `INBOUND_SECRET` unset → 503 (feature off); wrong secret → 401.
- Size limit **10 MB**, the same as uploads (`attachments.MAX_BYTES`); larger → 413.
- Parses only the **headers** (Python's `email` package, no attachments decoded): `From:`, `Subject:`, `Date:`,
  `Message-ID:`, and the **names and types** of the attachments from the MIME structure.
- `From:` address (lowercased) not registered for an active person → 403, nothing stored.
- Same `Message-ID` already in the inbox or already booked from the inbox → 200 "duplicate", nothing stored.
- Otherwise the raw mail is stored as a file (in `ATTACHMENTS_DIR`, under an id) and an **inbox entry** is created:
  forwarding person, received at, sender, subject, date, Message-ID, attachment names, size.
- The response never contains or logs the mail's content or the secret.

## 3. Data

- **E-mail addresses of persons:** a person can have **several** addresses; an address belongs to **one** person
  (unique, stored lowercased). Any person may have addresses, though only parents are expected to forward.
- **Inbox entry** (pending mail): forwarding person (nullable if that person is removed later; the entry stays for
  the other parents), the header fields above, the stored file, created at. When booked, the entry is removed and the
  mail becomes an `Attachment` of the booking (content type `message/rfc822`).
- Migration 0011.

## 4. Inbox and release (backend and frontend)

**Inbox** (parents only; children get 403 and see nothing):
- A section on the Transactions page with a counter, e.g. "📥 2 Belege warten" / "📥 2 receipts waiting"; also a
  small badge where the parent sees it without opening Transactions (builder's choice where).
- Each entry shows forwarding person, sender, subject, date and attachment names, **without opening anything**.
- **Delete:** any parent; removes the entry and its file.
- **Release:** the parent picks the **account** (accounts they may write to; suggestion below), then the backend reads
  the stored mail with the existing receipt reading (`receipt_files.ai_content` for `message/rfc822`, the AI, the
  draft), counting against **the releasing parent's** hourly AI limit. The draft opens in the existing receipt form
  (items, tags, persons, total check). Booking it links the mail as the booking's attachment and removes the inbox
  entry. Cancelling the form leaves the entry in the inbox.
- Without the AI configured, release opens the receipt form empty with the mail attached, to type in by hand.
- **Account suggestion:** the account of the forwarding person on which that person's most recent receipt (a booking
  with items) was booked; if none, their first account; if that isn't writable for the releasing parent, no
  suggestion.

**Retention:** inbox entries older than **30 days** are deleted with their file by the existing daily sweep.

**E-mail addresses** are managed by parents in **Settings → Family**, per person (add, remove).

All texts German and English, through the existing message and locale files.

## 5. Deployment and secrets

- `.env`: `INBOUND_SECRET` (empty = receiving off). `.env.example`, `docker-compose.yml` and README_DOCKER document it.
- Worker code in `cloudflare/email-worker/` (TypeScript, Vitest), as in family-job-tracking; its secrets
  (`APP_URL`, `INBOUND_SECRET`, `CF_ACCESS_CLIENT_ID`, `CF_ACCESS_CLIENT_SECRET`, optional `FALLBACK_ADDRESS`) only via
  `wrangler secret put`; `wrangler.toml` holds no personal data.
- README_DOCKER gets a setup section modeled on family-job-tracking's "Incoming e-mails": Email Routing for
  `invoice@frankfamily.xyz`, tunnel hostname limited to the inbound path, Access application and service token, the
  two `curl` checks (without token → Cloudflare refuses; with token but without secret → 401 from the app), fallback
  address, and a test with a real forwarded mail from GMX.
- The startup log says whether receiving is configured (never the secret).

## 6. Tests

- **Worker (Vitest):** `dmarc=pass` from Cloudflare's header → posted to the app; `dmarc=fail`/`none`/missing →
  rejected and not posted; a forged extra `Authentication-Results: …dmarc=pass` in a mail Cloudflare marked as failing
  → rejected; app answers 403 → rejected, not forwarded to the fallback; app unreachable or 5xx → fallback (or reject
  without one); headers sent (secret, Access token, content type).
- **Backend (pytest):** secret missing/wrong; size limit; unknown sender → 403 and nothing stored; inactive person →
  403; registered address (any case) → inbox entry for that person; duplicate Message-ID; nothing is decoded on
  arrival (e.g. a mail whose attachment would make the image decoder fail is still stored); inbox visible to parents
  only; delete; release → draft, AI limit counted for the releasing parent, booking links the mail and removes the
  entry; release without AI; account suggestion rules; 30-day sweep; address uniqueness and management.
- **Browser test:** a mail posted to the inbound endpoint (fake AI) shows in the inbox; release, check the draft,
  book; the booking has the mail attached.

## Calls made by the builder (to check)

- The allow list lives in the app, not in the Worker (one place to maintain addresses).
- An unknown sender gets a bounce; it isn't forwarded to the fallback address.
- Several addresses per person; any person may have addresses.
- Inbox size limit 10 MB per mail, 30 days retention.
- Account suggestion: the forwarder's account of their latest receipt, else their first account.
- Duplicates by Message-ID.
- Without the AI, release opens an empty receipt form with the mail attached.

## Left to the builder

- Table and endpoint names beyond `POST /api/v1/inbound`; where the inbox badge sits besides the Transactions page.
- How release hands the draft to the receipt form (reuse of `ReceiptForm` with a preset attachment and draft).
- Worker structure and tests, following family-job-tracking's worker.
