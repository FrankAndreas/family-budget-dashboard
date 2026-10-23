"""Import preview: change a row's category, remember it as a rule, rules applied to fallback rows (issue #16)."""

import json
import re
import tomllib

import pytest

from helpers import BASE_URL, category_id, create_account, register
from test_import import upload

HEADER = "date,account,category,amount,direction,description,reference"


def csv(*lines):
    return "\n".join([HEADER, *lines]) + "\n"


@pytest.fixture
def mum(client):
    headers = register(client, "mum")
    create_account(client, headers, "Bank")
    return headers


def send(client, headers, content, changes=None, path="import/preview", **data):
    if changes is not None:
        data["changes"] = json.dumps(changes)
    return upload(client, headers, content, path=path, **data)


def rows(client, headers, content, changes=None):
    response = send(client, headers, content, changes)
    assert response.status_code == 200, response.text
    return response.json()["rows"]


def rules(client, headers):
    return client.get(f"{BASE_URL}/import/rules", headers=headers).json()


BAKERY = "2026-09-06,Bank,Unsorted,22.10,,Bäckerei Muster,bank:1"
REFUND = "2026-09-07,Bank,Other Income,15.00,,Rückzahlung Muster,bank:2"


class TestChanges:
    def test_expense_to_expense(self, client, mum):
        [row] = rows(client, mum, csv(BAKERY), {"2": {"category": "Groceries"}})
        assert row["status"] == "ok"
        assert (row["category"], row["file_category"], row["rule"]) == ("Groceries", "Unsorted", None)

    def test_to_transfer_takes_the_direction_from_the_sign(self, client, mum):
        out, back = rows(
            client, mum, csv(BAKERY, REFUND), {"2": {"category": "Transfer"}, "3": {"category": "transfer"}}
        )
        assert (out["status"], out["direction"]) == ("ok", "out")
        assert (back["status"], back["direction"]) == ("ok", "in")

    @pytest.mark.parametrize("target", ["Salary", "Settle up", "Nonsense"])
    def test_not_allowed(self, client, mum, target):
        [row] = rows(client, mum, csv(BAKERY), {"2": {"category": target}})
        assert row["status"] == "error"
        assert f"Can't change Unsorted to {target}" in row["errors"]

    def test_transfer_row_cant_change(self, client, mum):
        [row] = rows(client, mum, csv("2026-09-06,Bank,Transfer,5,out,Savings,"), {"2": {"category": "Groceries"}})
        assert "Can't change Transfer to Groceries" in row["errors"]

    def test_import_books_the_new_category(self, client, mum):
        response = send(client, mum, csv(BAKERY), {"2": {"category": "Groceries"}}, path="import")
        assert response.json() == {"imported": 1, "skipped": 0}
        booked = rows(client, mum, csv(BAKERY), {"2": {"category": "Groceries"}})
        assert booked[0]["status"] == "duplicate"  # same reference
        account = client.get(f"{BASE_URL}/accounts", headers=mum).json()[0]["id"]
        [t] = client.get(f"{BASE_URL}/accounts/{account}/transactions", headers=mum).json()
        assert t["category_id"] == category_id(client, "Groceries") and t["amount"] == -22.10

    def test_duplicate_check_uses_the_new_category(self, client, mum):
        no_ref = "2026-09-06,Bank,Unsorted,22.10,,Bäckerei Muster,"
        send(client, mum, csv(no_ref), {"2": {"category": "Groceries"}}, path="import")
        assert rows(client, mum, csv(no_ref))[0]["status"] == "ok"  # Unsorted: a different booking
        assert rows(client, mum, csv(no_ref), {"2": {"category": "Groceries"}})[0]["status"] == "duplicate"

    def test_bad_changes(self, client, mum):
        bad = upload(client, mum, csv(BAKERY), changes="{nope")
        assert bad.status_code == 400 and bad.json()["detail"] == "changes must be JSON"
        missing = send(client, mum, csv(BAKERY), {"9": {"category": "Groceries"}})
        assert missing.status_code == 400


class TestRemember:
    def test_import_saves_a_rule(self, client, mum):
        changes = {"2": {"category": "Groceries", "remember": " Bäckerei "}}
        assert send(client, mum, csv(BAKERY), changes, path="import").status_code == 200
        assert [(r["text"], r["category"]) for r in rules(client, mum)] == [("Bäckerei", "Groceries")]

    def test_preview_saves_nothing(self, client, mum):
        rows(client, mum, csv(BAKERY), {"2": {"category": "Groceries", "remember": "Bäckerei"}})
        assert rules(client, mum) == []

    def test_same_text_updates(self, client, mum):
        send(client, mum, csv(BAKERY), {"2": {"category": "Groceries", "remember": "Bäckerei"}}, path="import")
        other = "2026-09-08,Bank,Unsorted,9.00,,Bäckerei Zwei,bank:3"
        send(client, mum, csv(other), {"2": {"category": "Dining Out", "remember": "BÄCKEREI"}}, path="import")
        assert [(r["text"], r["category"]) for r in rules(client, mum)] == [("Bäckerei", "Dining Out")]

    @pytest.mark.parametrize("text", ["B", "x" * 121, "   "])
    def test_text_length(self, client, mum, text):
        [row] = rows(client, mum, csv(BAKERY), {"2": {"category": "Groceries", "remember": text}})
        assert "rule text: 2 to 120 characters" in row["errors"]

    def test_failed_import_saves_no_rule(self, client, mum):
        broken = "2026-09-09,Nowhere,Unsorted,5,,x,"
        changes = {"2": {"category": "Groceries", "remember": "Bäckerei"}}
        assert send(client, mum, csv(BAKERY, broken), changes, path="import").status_code == 400
        assert rules(client, mum) == []

    def test_children_cant_remember(self, client, mum):
        kid = register(client, "kid", role="CHILD", by=mum)
        create_account(client, kid, "Pocket")
        line = "2026-09-06,Pocket,Unsorted,3,,Kiosk,"
        response = send(client, kid, csv(line), {"2": {"category": "Groceries", "remember": "Kiosk"}})
        assert response.status_code == 403 and response.json()["detail"] == "Only parents can save import rules"


class TestApplying:
    @pytest.fixture
    def bakery_rule(self, client, mum):
        send(client, mum, csv(BAKERY), {"2": {"category": "Groceries", "remember": "bäckerei"}}, path="import")

    def test_fallback_rows_get_the_rule(self, client, mum, bakery_rule):
        [row] = rows(client, mum, csv("2026-10-01,Bank,Unsorted,8,,BÄCKEREI Muster Bahnhof,bank:9"))
        assert (row["category"], row["rule"], row["file_category"]) == ("Groceries", "bäckerei", "Unsorted")

    def test_only_fallback_rows(self, client, mum, bakery_rule):
        [row] = rows(client, mum, csv("2026-10-01,Bank,Dining Out,8,,Bäckerei Café,bank:9"))
        assert (row["category"], row["rule"]) == ("Dining Out", None)

    def test_sign_must_fit(self, client, mum, bakery_rule):
        [row] = rows(client, mum, csv("2026-10-01,Bank,Other Income,8,,Bäckerei refund,bank:9"))
        assert (row["category"], row["rule"]) == ("Other Income", None)

    def test_oldest_rule_first_and_change_wins(self, client, mum, bakery_rule):
        other = "2026-09-08,Bank,Unsorted,9.00,,Muster AG,bank:3"
        send(client, mum, csv(other), {"2": {"category": "Clothing", "remember": "Muster"}}, path="import")
        line = "2026-10-01,Bank,Unsorted,8,,Bäckerei Muster,bank:9"
        assert rows(client, mum, csv(line))[0]["category"] == "Groceries"
        changed = rows(client, mum, csv(line), {"2": {"category": "Healthcare"}})[0]
        assert (changed["category"], changed["rule"]) == ("Healthcare", None)

    def test_transfer_rule(self, client, mum):
        send(client, mum, csv(REFUND), {"2": {"category": "Transfer", "remember": "Rückzahlung"}}, path="import")
        [row] = rows(client, mum, csv("2026-10-02,Bank,Other Income,20,,Rückzahlung X,bank:8"))
        assert (row["category"], row["direction"]) == ("Transfer", "in")


class TestRulesApi:
    def test_list_delete_parents_only(self, client, mum):
        send(client, mum, csv(BAKERY), {"2": {"category": "Groceries", "remember": "Bäckerei"}}, path="import")
        [rule] = rules(client, mum)
        assert rule["category_type"] == "EXPENSE"
        kid = register(client, "kid", role="CHILD", by=mum)
        assert client.get(f"{BASE_URL}/import/rules", headers=kid).status_code == 403
        assert client.delete(f"{BASE_URL}/import/rules/{rule['id']}", headers=kid).status_code == 403
        assert client.delete(f"{BASE_URL}/import/rules/{rule['id']}", headers=mum).status_code == 200
        assert rules(client, mum) == []

    @pytest.mark.parametrize("text", ['Café "Zum Bären"', r"C:\Shop", "Shop (Zürich) 50% #1 a.b"])
    def test_toml_block(self, client, mum, text):
        line = f'2026-09-06,Bank,Unsorted,5,,"{text.replace(chr(34), chr(34) * 2)}",'
        response = send(client, mum, csv(line), {"2": {"category": "Groceries", "remember": text}}, path="import")
        assert response.status_code == 200, response.text
        [rule] = rules(client, mum)
        parsed = tomllib.loads(rule["toml"])["bank"]["rules"][0]
        assert parsed["category"] == "Groceries"
        assert re.search(parsed["match"], f"Einkauf {text.upper()} 01.09.2026", re.IGNORECASE)

    def test_toml_block_for_a_transfer(self, client, mum):
        send(client, mum, csv(BAKERY), {"2": {"category": "Transfer", "remember": "Bäckerei"}}, path="import")
        parsed = tomllib.loads(rules(client, mum)[0]["toml"])["bank"]["rules"][0]
        assert parsed == {"match": "Bäckerei", "action": "transfer"}

    def test_schema_lists_rules(self, client, mum):
        send(client, mum, csv(BAKERY), {"2": {"category": "Groceries", "remember": "Bäckerei"}}, path="import")
        schema = client.get(f"{BASE_URL}/import/schema", headers=mum).json()
        assert schema["x-rules"] == [{"contains": "Bäckerei", "category": "Groceries"}]


def add_rule(text, category_name, created_at):
    """A rule as the preview's "remember" saves it, with a fixed age."""
    from datetime import datetime

    from app import database, models

    with database.SessionLocal() as db:
        category = db.query(models.Category).filter(models.Category.name == category_name).one()
        db.add(models.ImportRule(text=text, category_id=category.id, created_at=datetime(2026, 1, created_at)))
        db.commit()


def booked_as(client, headers, *descriptions):
    lines = [f"2026-09-0{i + 1},Bank,Unsorted,10.00,,{d},m:{i}" for i, d in enumerate(descriptions)]
    return [row["category"] for row in rows(client, headers, csv(*lines))]


class TestMatching:
    def test_whole_words(self, client, mum):
        add_rule("CSS", "Healthcare", 1)
        assert booked_as(client, mum, "LSV CSS Versicherung", "ACCSSO Shop", "css") == [
            "Healthcare",
            "Unsorted",
            "Healthcare",
        ]

    def test_separators(self, client, mum):
        add_rule("BIKE-IMPORT", "Entertainment", 1)
        add_rule("H&M", "Clothing", 2)
        add_rule("S.OLIVER", "Clothing", 3)
        assert booked_as(client, mum, "Einkauf bike-import.ch", "H&M Stans", "s.Oliver Kriens", "H&MX") == [
            "Entertainment",
            "Clothing",
            "Clothing",
            "Unsorted",
        ]

    def test_longest_wins(self, client, mum):
        add_rule("DOSENBACH", "Clothing", 1)
        add_rule("DOSENBACH SPORT", "Entertainment", 2)
        assert booked_as(client, mum, "Dosenbach Sport Stans", "Dosenbach Stans") == ["Entertainment", "Clothing"]

    def test_equal_length_older_wins(self, client, mum):
        add_rule("Muster", "Groceries", 2)
        add_rule("muster", "Clothing", 1)
        assert booked_as(client, mum, "Bäckerei Muster") == ["Clothing"]


RULES = f"{BASE_URL}/import/rules"


class TestManage:
    def test_create_list_update_delete_rule(self, client, mum):
        groceries, clothing = category_id(client, "Groceries"), category_id(client, "Clothing")
        response = client.post(RULES, json={"text": " Coop ", "category_id": groceries}, headers=mum)
        assert response.status_code == 200, response.text
        rule = response.json()
        assert (rule["text"], rule["category_id"], rule["category"], rule["receipt_expected"]) == (
            "Coop",
            groceries,
            "Groceries",
            False,
        )
        assert [r["id"] for r in rules(client, mum)] == [rule["id"]]
        changed = client.put(
            f"{RULES}/{rule['id']}",
            json={"text": "Coop City", "category_id": clothing, "receipt_expected": True},
            headers=mum,
        ).json()
        assert (changed["text"], changed["category"], changed["receipt_expected"]) == ("Coop City", "Clothing", True)
        assert client.put(f"{RULES}/{rule['id']}", json={"receipt_expected": False}, headers=mum).json()["text"] == (
            "Coop City"
        )
        assert client.delete(f"{RULES}/{rule['id']}", headers=mum).status_code == 200
        assert rules(client, mum) == []
        assert client.put(f"{RULES}/{rule['id']}", json={"text": "x y"}, headers=mum).status_code == 404

    def test_rule_text_unique_ignoring_case(self, client, mum):
        groceries = category_id(client, "Groceries")
        client.post(RULES, json={"text": "Coop", "category_id": groceries}, headers=mum)
        response = client.post(RULES, json={"text": "COOP", "category_id": groceries}, headers=mum)
        assert response.status_code == 400
        assert response.json()["detail"] == "There is already a rule for this text"
        other = client.post(RULES, json={"text": "Denner", "category_id": groceries}, headers=mum).json()
        assert client.put(f"{RULES}/{other['id']}", json={"text": "coop"}, headers=mum).status_code == 400
        # Its own text in other spelling is fine
        assert client.put(f"{RULES}/{other['id']}", json={"text": "DENNER"}, headers=mum).status_code == 200

    def test_rule_text_length(self, client, mum):
        groceries = category_id(client, "Groceries")
        for text in ("a", "  a  ", "x" * 121):
            assert client.post(RULES, json={"text": text, "category_id": groceries}, headers=mum).status_code == 400

    def test_rule_categories(self, client, mum):
        ok = client.post(RULES, json={"text": "Übertrag", "category_id": category_id(client, "Transfer")}, headers=mum)
        assert ok.status_code == 200
        assert ok.json()["category_type"] == "TRANSFER"
        settle = client.post(
            RULES, json={"text": "Ausgleich", "category_id": category_id(client, "Settle up")}, headers=mum
        )
        assert settle.status_code == 400
        assert settle.json()["detail"] == "Rules can only set income, expense or Transfer categories"
        assert client.post(RULES, json={"text": "Lohn AG", "category_id": "nope"}, headers=mum).status_code == 404

    def test_rules_parents_only(self, client, mum):
        kid = register(client, "kid", role="CHILD", by=mum)
        groceries = category_id(client, "Groceries")
        rule = client.post(RULES, json={"text": "Coop", "category_id": groceries}, headers=mum).json()
        assert client.post(RULES, json={"text": "Migros", "category_id": groceries}, headers=kid).status_code == 403
        assert client.put(f"{RULES}/{rule['id']}", json={"text": "Migros"}, headers=kid).status_code == 403

    def test_remember_keeps_receipt_expected(self, client, mum):
        groceries = category_id(client, "Groceries")
        rule = client.post(
            RULES, json={"text": "Bäckerei", "category_id": groceries, "receipt_expected": True}, headers=mum
        ).json()
        response = send(
            client,
            mum,
            csv("2026-09-06,Bank,Other Income,5.00,,Bäckerei Gutschrift,bank:9"),
            {"2": {"category": "Salary", "remember": "bäckerei"}},
            path="import",
        )
        assert response.status_code == 200, response.text
        [saved] = rules(client, mum)
        assert (saved["id"], saved["category"], saved["receipt_expected"]) == (rule["id"], "Salary", True)
