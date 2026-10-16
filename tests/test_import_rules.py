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
