# Wishes: personal lists and a family plan

Date: 2026-10-16. Status: draft, for review.

## Goal

A place for things the family wants to buy, with a rough price and an order of priority:

- **My lists:** every person (and the common budget) has their own wish list in their own order.
- **Family plan:** one combined ranking of the wishes the parents plan together, with a running total.

Who sees which wishes follows the existing share settings; nothing new to configure.

Decided with the user:
- A wish belongs to one person or to the common budget (with a split), like yearly bills and investments.
- Priority is the order of the list, changed with ▲▼ (no priority numbers).
- A wish enters the family plan only explicitly ("📌 Add to family plan"); common wishes are always in it. Every
  parent who can see the family plan may reorder it.
- Prices: the rough estimate is typed in; for the best price there are **search links** (toppreise.ch, Galaxus,
  Google Shopping) and fields to note what was found. An automatic price search (search API or an AI with web
  search) is out of scope for now: it needs an API key and money, sends wish names to a third party, and the
  results need checking anyway.

## 1. Data

New table `wishes` (created on start-up by `create_all`; no change to existing tables):

| Column | Type | Notes |
|---|---|---|
| `id` | string (uuid) | |
| `name` | string | required, 1–120 characters |
| `estimate` | float, nullable | rough price in CHF, ≥ 0 |
| `notes` | string, nullable | up to 1000 characters |
| `owner_id` / `split_id` | string, nullable | exactly one of them, as for planned costs |
| `best_price`, `best_shop`, `best_url`, `best_checked` | float / string / string / date, all nullable | best offer found; `best_url` must start with `http://` or `https://` |
| `position` | integer | order in the owner's list (smaller = higher) |
| `family_position` | integer, nullable | order in the family plan; null = not in it |
| `bought_on` | date, nullable | set = bought |
| `created_at` | datetime | |

- A new wish goes to the end of its owner's list. A common wish also goes to the end of the family plan.
- Changing a wish's owner moves it to the end of the new owner's list.
- Positions only need to be ordered, not consecutive; moves swap the two positions.
- "Price" in sums and in the family plan = `best_price` if set, otherwise `estimate`, otherwise 0 (shown as "–").

## 2. Who sees and does what

Built on the existing rules (`common_api.visible_owner`, `privacy.access_level`):

- **See a wish:** personal wish → the viewer has any access to the owner's money (own, shared VIEW/EDIT, dependent
  child, allowance child without privacy). Common wish → the viewer is a parent.
- **Change a wish** (edit, delete, bought / back to open, ▲▼ in the owner's list, add to / remove from the family
  plan): write access to the owner (own, EDIT, dependent child); common wish → any parent.
- **Family plan:** parents only. Any parent may move any wish they can see in it.
- **Children with allowance** (with their own login) use "My lists" for their own wishes; they have no family plan
  and no common wishes. Dependent children's wishes are entered by parents, with the child as owner.
- **Hidden wishes keep their place.** Lists and the family plan only return wishes the viewer can see. A move
  swaps with the nearest wish *the viewer can see* in that direction; wishes in between that the viewer can't see
  keep their positions.
- **Bought wishes** stay in the table but leave both orders' visible lists: they appear in a collapsed "Bought"
  section of their owner's list, newest first, and are not in the family plan or its total. "Back to open" puts the
  wish back at its old positions (they were never cleared).

## 3. API (`backend/app/wishes_api.py`, prefix `/api/v1`)

- `GET /wishes` → every wish the user can see, open and bought, sorted by owner and `position`. Each row has the
  columns above plus `price` (the "price" rule), `can_edit` (bool), `in_family_plan` (bool).
- `GET /wishes/family-plan` → parents only: open wishes with `family_position` the user can see, sorted by
  `family_position`, each with `running_total` (sum of `price` up to and including this row; wishes the
  viewer can't see don't count).
- `POST /wishes`, `PUT /wishes/{id}`, `DELETE /wishes/{id}`: create, edit, delete. 404 if not visible, 403 if
  visible but not changeable.
- `POST /wishes/{id}/move` with `{"list": "own" | "family", "direction": "up" | "down"}`. At the top/bottom: no
  change, 200. `family` requires a parent and a wish in the family plan.
- `POST /wishes/{id}/family-plan` (add, to the end) and `DELETE /wishes/{id}/family-plan` (remove; not allowed for
  common wishes: 400 "Common wishes are always in the family plan").
- `POST /wishes/{id}/bought` with `{"bought_on": "YYYY-MM-DD"}` (default today) and `DELETE /wishes/{id}/bought`.

Errors (400): name missing or too long; estimate or best price negative; link without `http(s)://`; neither or
both of owner and split; split not found. A child can't create a common wish (403).

## 4. Screen: tab "🎁 Wishes"

On the budget side, for everyone (children see only their own list). `frontend/src/components/Wishes.tsx`, with
a switch at the top: **My lists** | **Family plan** (the switch only for parents).

**My lists**
- One card per owner: the user's own list first (always shown), then the other people and "Common" (only when
  they have wishes the user can see).
- Each row: ▲▼ (only with edit rights), name, estimate, best price (with shop, linked when there's a URL, and
  "checked <date>"), 📌 in the family plan, buttons 🔎 (search links), ✓ Bought, Edit, Delete.
- 🔎 opens a small menu with three links, each in a new tab, with the wish name as the search text:
  - toppreise.ch: `https://www.toppreise.ch/produktsuche?q=<name>`
  - Galaxus: `https://www.galaxus.ch/de/search?q=<name>`
  - Google Shopping: `https://www.google.com/search?udm=28&q=<name>`
  The links live in one constant so they're easy to change.
- "+ Add wish" form: name, estimate, owner (the same owner select as yearly bills: people the user can manage, and
  the splits for parents), notes; best price, shop, link, checked date are in the edit form.
- Each card ends with the total of its open wishes. "Bought (n)" below it, collapsed.

**Family plan**
- One ranked list: rank, ▲▼, name, owner ("Common" for a split), price, running total.
- An empty plan: "Nothing in the family plan yet. Use 📌 in My lists to add a wish."

## 5. Export

The analysis export ZIP gets `wishes.csv` (the wishes the user can see; same visibility as the API) and a short
section in its README. The JSON backup is not changed: it doesn't contain yearly bills or investments either.

## Testing

- **Backend (pytest, `tests/test_wishes.py`):** create, edit, delete; validation errors; new wish at the end; move
  up/down in the own list, top and bottom no-ops; family plan add/remove, common wish always in it and can't be
  removed; move in the family plan swaps with the nearest visible wish and leaves hidden ones in place; running
  total; bought and back to open (positions kept, leaves the plan's list and total); visibility: own, VIEW share
  (sees, can't change), EDIT share (can change), no share (404), child sees only own, child can't open the family
  plan or create a common wish; owner change moves to the end of the new list; export contains `wishes.csv`.
- **Frontend:** lint, type-check, build; browser test: add three wishes, reorder, pin two to the family plan,
  reorder the plan, running total, search links have the right URLs, mark bought, Bought section.

## Out of scope

- Automatic price search (search API or AI with web search).
- Linking a bought wish to its expense, or turning it into an investment.
- Wishes in the JSON backup (with yearly bills and investments, issue #17's area).
- Drag and drop (▲▼ only).
