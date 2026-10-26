# Investments with several tags

Approved by the user in chat on 2026-10-26.

## Why

A bicycle is both getting around and a hobby: tagged **Mobility** and **Bike**, the Investments tab and Analytics
show it in both views. Receipt items can already carry several tags; investments could only carry one.

## What

- An investment has **any number of tags** (none, one, several), chosen in the form with checkboxes; "+ New tag…"
  stays.
- **Investments tab**: the investment shows in the group of **each** of its tags (both groups is the user's choice;
  no "group by" switch). Each group's totals include it. Without a tag it is in "No tag" as today.
- **The overall total counts each investment once**, so it can be less than the group totals added up; a note under it
  says so when an investment has several tags. The card names its other tags ("also in: Mobility").
- **Analytics and tag budgets**: bookings linked to the investment count in full under each of its tags, and its
  monthly set-aside counts under each of them, like a receipt item with several tags (totals per tag overlap).
- Deleting a tag removes it from its investments; the others stay. Settings counts the investment under each tag.

## Data

- New table `asset_tags` (asset_id, tag_id; both deleted with their row), migration 0019. Each existing
  `assets.tag_id` becomes one row, then the column is dropped. Downgrade keeps the first tag by name.
- API: `tag_ids` (list) replaces `tag_id` on input and output; an unknown tag is a 400, duplicates are dropped.
- Export `investments.csv`: `tag_ids` and `tags`, separated by `;` like the items' tags, replace `tag_id` and `tag`.

## My calls

- Checkboxes for the tags, not a multi-select list: easier on a phone.
- The card lists the other tags, not all of them: the group header already says the one it is in.
