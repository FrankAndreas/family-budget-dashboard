# Asking about spending in plain words

Status: approach chosen in chat on 2026-11-27; waiting for the user's approval. Points marked "my call" are the
author's.

## Why

The user wants to type questions like "What did we spend on groceries this month?" or "How much for restaurants?"
and get the number, instead of finding it on the Analytics tab. The budget data lives in this app, so the question is
answered here, not in family-hub (decided in chat: the hub only knows people, logins and tiles).

## Goals

- An **"Ask" box on the Analytics tab** (my call), above the cards, for the scope picked there (ScopeSelector): the
  answer is about the same person's money the tab shows, with the same access check (`privacy.check_user_access`).
- Questions it answers: **sum of expenses (or income) by category, by tag, or in total, for a period**, and the
  **same compared with an earlier period** ("restaurants this month vs. last month").
- Periods: this/last month, a named month, this/last year, a named year, the last N months (my call).
- The answer is a short sentence with the **amount computed by the app**, plus what it understood (category/tag,
  period) so a misunderstanding is visible, e.g. "Restaurant, November 2026: CHF 312.40".
- German and English, in the person's language, like the rest of the app.

## Non-goals

- Free conversation, follow-up questions that refer to the previous answer, a chat history (my call: one question,
  one answer; a history can come later).
- Questions the query can't express ("why is October higher?", "which shop is the most expensive?"): the app says it
  can't answer that and lists what it can.
- The common budget tab and investments (only the Analytics scope).
- Asking from family-hub or from outside: the app stays home-only.
- Changing anything (booking, editing): read-only.

## Anti-goals

- **Transactions, amounts, bank texts or people's names sent to Infomaniak.** The prompt holds only the question, the
  family's category and tag names (in the person's language) and today's date.
- **A number the model made up**: every amount comes from the app's own computation.
- An answer that shows money the person can't see on the Analytics tab.

## Approaches

- **A. The AI turns the question into a query, the app computes** (chosen): the model answers with JSON such as
  `{"kind": "expense", "category": "Restaurant", "period": {"month": "2026-11"}, "compare": "previous"}`; the app
  checks it against the real names and computes the sum from `reports.lines`. Correct numbers, nothing private
  leaves the NAS; limited to what the query shape covers.
- B. Send the period's transactions to the AI and let it answer freely: any question, but private data leaves the NAS
  and models get sums wrong. Rejected.
- C. No AI, a filter box (category, tag, month) with a total: private and simple, but clicking instead of asking, and
  close to what Analytics already shows. Rejected.

## How it works

- **Backend**: `POST /api/v1/reports/ask` with `{question, user_id}` (question at most 300 characters, my call).
  Uses the existing Infomaniak client and settings from `receipt_ai.py` (token, product ID, model, `FakeClient` in
  tests); off when AI is off, and the box is then hidden.
- **Validating the model's answer**: untrusted. Category/tag names must match the family's (case-insensitive); an
  unknown name, a malformed period or invalid JSON gives "I didn't understand that" with examples, never a guess.
- **Computing**: from `reports.lines` with the period's Swiss-day bounds, so sums equal the Analytics cards (items
  count under each of their tags, refunds lower expenses, transfers excluded, as there).
- **Rate limit**: counts toward the existing AI reads per person and hour (my call: one budget for all AI use).
- **Frontend**: a text field with an "Ask" button on the Analytics tab, the answer below it; a link "show
  transactions" opens the Transactions view filtered to the category/tag and period if that filter exists, otherwise
  no link (left to the builder).

## Left to the builder

- Exact prompt wording and JSON schema; whether income questions need their own examples.
- Module split (e.g. `spending_ask.py` next to `receipt_ai.py`) and whether the Infomaniak client moves to a shared
  module.
- Wording and layout of the box and answers, in the app's look.
