# Scanning a pile of receipts with the phone

Status: approved in chat on 2026-10-24 (photo-taking part); details below marked "my call" are the author's.

## Why

Today a paper receipt gets into the app by photographing it, opening the mail app and forwarding the photo to the
receipt address (issue #57), or by uploading a file in the receipt form. The user collects receipts at home, in one
place, and goes through them **about once a week or late in the evening**, then throws the paper away. Sending every
receipt through the mail app is the slow part.

## What success looks like

At the table with the pile, on the home Wi-Fi: open the app on the phone, tap **📷 Scan receipts**, photograph one
receipt after another with one tap each, tap **Done**. Later, maybe on the same evening, go through the inbox: each
photo opens already read by the AI, check it, **Book & next**.

## Goals

- **Photograph the whole pile first, check afterwards** (the user's choice).
- **Photos only in the app**: they are stored on the NAS with the booking, not in the phone's gallery or Android's
  backup (the user's preference).
- **Nothing gets lost**: the paper is thrown away once it is photographed, so a photo that reached the inbox stays
  there until it is booked or a parent deletes it, whatever happens to the AI or the checking.
- Works on the phones in use: **Samsung and Google Pixel, both with Chrome**.

## Non-goals

- Taking photos away from home. The NAS is only reachable on the home network, and the receipts are processed at home.
  The mail route keeps working for the rare receipt on the way.
- A camera view inside the page (needs HTTPS, see "Camera" below). Only if the test on the phones shows photos landing
  in the gallery.
- Cropping, straightening or enhancing the photo in the app.
- Children scanning receipts. The inbox is for parents, as it is today.
- An installable app (home-screen icon, offline mode).

## Anti-goals

- A receipt photographed, the paper thrown away, and the photo gone: through an upload that silently failed, an
  automatic clean-up, or a failed AI reading.
- Copies of every receipt in the phone's photos.

## How it works

### Camera (my call)

The scan screen uses the browser's file input with the camera (`<input type="file" accept="image/*"
capture="environment">`): Chrome opens the phone's camera app, the photo comes back to the page, and the browser
keeps it as a temporary file only. This works over the NAS's plain `http://<NAS_IP>:8081`; a live camera view
in the page (`getUserMedia`) would not, because browsers allow it only on HTTPS.

Browsers don't let a page reopen the camera on its own, so each photo is one tap: **📷 Next receipt**.

On the Pixel, Google's camera normally doesn't save these photos to the gallery. On Samsung it is not certain.
**Acceptance includes a test on both phones** that no photo shows up in the gallery. If the Samsung saves copies, the
follow-up is HTTPS on the NAS plus a camera view in the page; that is a separate piece of work.

### Scan screen

- Parents only. Reached from a **📷 Scan receipts** button next to the existing receipt buttons, and on the inbox
  card.
- Shows a thumbnail per photo taken in this session, with its upload state (uploading, ✓, failed with **retry**).
- **Each photo is uploaded as soon as it is taken** (my call), not at Done: a closed tab or a dead battery then loses
  at most the photo being uploaded, and the failed state shows it.
- Before upload the browser scales the photo down so its long side is at most 2400 px, as JPEG (my call; phone photos
  are 3 to 8 MB, the app's limit per file is 10 MB, and the AI doesn't need more). The original file is never kept.
- **Done** returns to where the scan started; the photos are in the inbox.
- Usable at phone width. The rest of the app is not changed for phones by this work.

### Inbox

- Photos join the inbox next to the forwarded mails: one list for parents, newest first. A photo row shows who took it,
  when, and the AI's reading state (waiting, reading, read with shop and total, not read).
- **Photos are never removed automatically.** The 30-day clean-up of unreleased mails does not apply to them (my
  call, from the anti-goal). They leave the inbox when booked or when a parent deletes one (with a confirmation).
- The account is chosen per entry as for mails today, suggested from the person who took it (their account of their
  latest receipt, the same rule as for mails).
- Opening a photo opens today's receipt form with the AI's draft and the photo attached. Booking it marks the entry
  booked, as for mails. **Book & next** opens the next waiting entry; **Skip** leaves this one and opens the next.
  Cancel returns to the list.
- Checking goes through the photos **in the order they were taken** (my call: the pile's order), the mails after them.
- The account can be changed in the check view. Its default is the account of the receipt booked just before in
  this round, else the suggestion above (my call: a pile is often from one card).
- The same receipt photographed twice gives two entries; the app doesn't detect it (my call). Delete the extra one;
  a bank statement would show the double booking as a booking with no payment found.
- Other parents see and can check the same photos (the inbox is shared between parents today).

### Reading in the background (my call)

- When a photo arrives, the AI reads it in the background, one photo at a time, and the draft is kept with the entry,
  so opening it is instant.
- The AI reads in the language of the person who took the photo.
- A reading counts toward the hourly limit of the person who took the photo (default 30 per hour,
  `RECEIPT_AI_READS_PER_HOUR`). Photos over the limit wait and are read later in the background, or when opened.
- If the AI is off, unavailable or can't read the photo, the entry stays as "not read"; opening it tries once more,
  and if that fails too, the form opens empty with the photo attached for typing it in. The photo is never lost
  because of the AI.
- A reading interrupted by a restart of the backend is started again.

### Storage

- The photo files sit next to the waiting mails (`ATTACHMENTS_DIR/inbox`), so the attachment sweep leaves them alone,
  and they are in the NAS backup with the other attachments.
- Whether photos get their own table or share the mail entries' table is the builder's call. Either way the
  migration keeps all existing data: the NAS database can no longer be wiped.

## Constraints

- Repository is public: tests use invented receipts only (the fake AI's receipt, generated images), never real ones.
- The existing mail inbox, the receipt form with its "paid with this bank booking" offer, and the hourly AI limit keep
  working as today.
- German and English texts for everything new.
- Browser test with the fake AI (`RECEIPT_AI_FAKE=1`): photos fed to the camera input with `setInputFiles`, then
  checked and booked from the inbox.

## Left to the builder

- Data model and API shape for photo entries, and how the background reading is run and resumed.
- Exact wording, layout and icons, within the existing app's look.
- How the scale-down is done in the browser.
