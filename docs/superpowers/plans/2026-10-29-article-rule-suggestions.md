# Article Rule Suggestions Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Article rules apply to every AI-read receipt; bookings (receipt form, photos, mails, Migros import) only
propose rules, as suggestions the parents review in Settings.

**Architecture:** A suggestions table next to the article rules; one function `article_rules.suggest()` called where
receipts are booked (`api.create_receipt`, `api.update_receipt`, `migros_import.run_migros`); one function
`article_rules.apply_to_draft()` called where an AI draft is handed out. Settings' ArticleRules gets the list.

**Tech Stack:** FastAPI, SQLAlchemy 2, Alembic, SQLite; React 19, TS; pytest, Playwright.

**Spec:** `docs/superpowers/specs/2026-10-29-article-rule-suggestions-design.md`

## Global Constraints

- Nothing enters `article_rules` except through Add / Add all (or the rules API by hand).
- A suggestion per article (`name_key` = name stripped, casefolded; unique); the latest booking wins.
- No suggestion for: discount lines (negative amount), Migros fallback lines, lines matching their rule exactly,
  bookings by children.
- Migration 0022, additive; `database_setup.HEAD = "0022"`.
- Parents only for the suggestions API (`import_rules.require_parent`).
- German and English for every new text; invented test data only.

## Review Focus

- A receipt edited again (update_receipt) with the same lines → the suggestion is updated, not duplicated.
- A suggestion for an article that got a rule meanwhile (added by hand) → Add updates that rule, never a second rule.
- A tag deleted while suggested → the suggestion stays without the tag.
- A child booking a receipt → no suggestions, no error.
- Add with a changed category that is not an expense → 400, suggestion kept.

---

### Task 1: Suggestions: table, record, API

**Files:** Modify `backend/app/models.py`, `backend/app/article_rules.py`, `backend/app/tags_api.py` (delete removes
links), `backend/app/categories_api.py` (deleting a category deletes its suggestions; not counted as usage),
`backend/app/database_setup.py`; Create `backend/app/migrations/versions/0022_article_rule_suggestions.py`;
Test `tests/test_article_suggestions.py`.

**Interfaces — Produces:**
- `models.ArticleRuleSuggestion` (`id, name, name_key unique, category_id, created_at, updated_at`, `tags` via
  `article_rule_suggestion_tags`, `tag_ids`).
- `article_rules.suggest(db, user, lines: list[tuple[str, str, list[str]]]) -> int` — (name, category_id, tag_ids)
  per line; returns how many suggestions were made or changed; parents only (a child: 0); skips lines matching their
  rule exactly; the caller commits.
- API: `GET /article-rules/suggestions` → `[{id, name, category_id, category, tag_ids, rule: {category, tag_ids} |
  null}]` newest first; `POST /article-rules/suggestions/{id}/add` body `{category_id?, tag_ids?}` → the rule;
  `POST /article-rules/suggestions/add-all`; `DELETE /article-rules/suggestions/{id}`.

- [ ] Tests first: `test_suggest_one_per_article_latest_wins`, `test_matching_rule_no_suggestion_differing_rule_suggests`,
  `test_child_makes_none`, `test_add_makes_or_updates_the_rule` (incl. a rule made meanwhile), `test_add_with_changes`,
  `test_add_non_expense_400_keeps_it`, `test_add_all`, `test_ignore`, `test_tag_and_category_delete`,
  `test_migration_0022`. Run → FAIL. Implement. Run full backend + linters → PASS. Commit
  `feat(rules): article rule suggestions`.

### Task 2: Bookings suggest; the Migros import no longer learns

**Files:** Modify `backend/app/api.py` (`create_receipt`, `update_receipt` call `suggest` with the item lines that
are not discounts), `backend/app/migros_import.py` (`run_migros` calls `suggest` with the booked non-discount,
non-fallback lines instead of `learn`; response `suggestions` replaces `rules`; preview `new_suggestions` replaces
`new_rules`); Test `tests/test_migros_import.py` (update), `tests/test_article_suggestions.py`.

- [ ] Tests first: `test_receipt_form_booking_suggests`, `test_editing_a_receipt_updates_its_suggestion`,
  Migros: imports make suggestions, no rules (`test_rule_then_ai_then_fallback`, `test_changed_article_updates_its_rule`
  rewritten: rule unchanged, suggestion present). Run → FAIL. Implement. Run full backend → PASS. Commit
  `feat(rules): bookings and the Migros import only suggest rules`.

### Task 3: Rules on AI drafts

**Files:** Modify `backend/app/article_rules.py` (`apply_to_draft(db, draft: Optional[dict]) -> Optional[dict]`:
items whose name has a rule get its category_id and tag_ids and `"source": "rule"`), `backend/app/receipt_ai.py`
(`read` returns the applied draft), `backend/app/scans.py` (open returns the applied draft, so rules made after the
photo was read count); Test `tests/test_article_suggestions.py`.

- [ ] Tests first: `test_ai_draft_takes_the_rule` (receipts/read with the fake AI's "Brot" and a rule "brot" →
  Other Expense, source rule), `test_scanned_photo_opened_after_a_new_rule`. Run → FAIL. Implement. PASS. Commit
  `feat(rules): article rules on every receipt the AI reads`.

### Task 4: Settings list, texts, receipt form label, e2e

**Files:** Modify `frontend/src/components/ArticleRules.tsx` (section "New suggestions (n)" with category select,
tag chips, "changes the rule", Add / Ignore per row, Add all), `frontend/src/components/MigrosImport.tsx` and
`frontend/src/migros.ts` (`new_suggestions`, result text), `frontend/src/components/ReceiptForm.tsx` (a draft line with
source rule shows "by article rule"), locales; Test `e2e/tests/migros-import.spec.ts` (suggestions instead of rules:
Add one with a change, Ignore one, Add all), `e2e/README.md`.

- [ ] E2E first → FAIL. Implement. lint, type-check, build, full e2e → PASS. Commit
  `feat(rules): review article suggestions in Settings`.

Rulings already taken (spec "my call"): the post-booking hint is only in the Migros import's result message; the
receipt form's save shows none (its save has no message today) — the Settings count shows them.
