"""Transfers between the family's own accounts: imported with a direction, deletable, Settle up untouched."""

import pytest

from helpers import (
    add_member,
    BASE_URL,
    add_transaction,
    balance,
    category_id,
    create_account,
    register,
    user_id,
    remove_from_hub,
)
from test_import import csv_file, preview, upload

HEADER = "date,account,category,amount,direction,description,for,item"


@pytest.fixture
def mum(client):
    headers = register(client, "mum")
    return {
        "headers": headers,
        "bank": create_account(client, headers, "Bank"),
        "migros": create_account(client, headers, "Migros"),
    }


def import_file(client, headers, *lines):
    response = upload(client, headers, csv_file(*lines, header=HEADER), path="import")
    assert response.status_code == 200, response.text
    return response.json()


def transfer_id(client, headers, account):
    rows = client.get(f"{BASE_URL}/accounts/{account}/transactions", headers=headers).json()
    return next(t["id"] for t in rows if t["category_id"] == category_id(client, "Transfer"))


class TestSeed:
    def test_new_categories(self, client):
        types = {c["name"]: c["type"] for c in client.get(f"{BASE_URL}/categories").json()}
        assert types["Transfer"] == "TRANSFER"
        assert types["Unsorted"] == "EXPENSE"
        assert types["Reimbursements"] == "INCOME"


class TestImport:
    def test_both_directions(self, client, mum):
        result = import_file(
            client,
            mum["headers"],
            "2026-09-01,Bank,Transfer,84.30,out,Migros,,",
            "2026-09-01,Migros,Transfer,84.30,in,From bank,,",
        )
        assert result == {"imported": 2, "skipped": 0}
        assert balance(client, mum["headers"], mum["bank"]) == -84.30
        assert balance(client, mum["headers"], mum["migros"]) == 84.30

    def test_direction_case_and_spaces(self, client, mum):
        rows = preview(client, mum["headers"], csv_file("2026-09-01,Bank,transfer,5, OUT ,,,", header=HEADER))["rows"]
        assert rows[0]["status"] == "ok"

    @pytest.mark.parametrize(
        "line, error",
        [
            ("2026-09-01,Bank,Transfer,5,,,,", "direction is required for a transfer (in or out)"),
            ("2026-09-01,Bank,Transfer,5,sideways,,,", "direction 'sideways': use in or out"),
            ("2026-09-01,Bank,Groceries,5,out,,,", "direction is only for transfers"),
            ("2026-09-01,Bank,Settle up,5,out,,,", "Settle up can't be imported; use the Common tab"),
        ],
    )
    def test_errors(self, client, mum, line, error):
        rows = preview(client, mum["headers"], csv_file(line, header=HEADER))["rows"]
        assert rows[0]["status"] == "error"
        assert error in rows[0]["errors"]

    def test_transfer_takes_no_tags(self, client, mum):
        add_member(client, "Kim")
        rows = preview(client, mum["headers"], csv_file("2026-09-01,Bank,Transfer,5,out,,Kim,", header=HEADER))["rows"]
        assert "A transfer can't be for a child, shared or linked to an investment" in rows[0]["errors"]

    def test_duplicate_by_day_amount_and_direction(self, client, mum):
        import_file(client, mum["headers"], "2026-09-01,Bank,Transfer,5,out,,,")
        rows = preview(
            client,
            mum["headers"],
            csv_file("2026-09-01,Bank,Transfer,5,out,,,", "2026-09-01,Bank,Transfer,5,in,,,", header=HEADER),
        )["rows"]
        assert [r["status"] for r in rows] == ["duplicate", "ok"]

    def test_schema(self, client, mum):
        schema = client.get(f"{BASE_URL}/import/schema", headers=mum["headers"]).json()
        props = schema["properties"]["transactions"]["items"]["properties"]
        assert "Transfer" in props["category"]["enum"] and "Settle up" not in props["category"]["enum"]
        assert props["direction"]["enum"] == ["in", "out"]
        assert schema["x-category-types"]["Transfer"] == "TRANSFER"
        assert schema["x-category-types"]["Groceries"] == "EXPENSE"
        assert schema["x-category-types"]["Salary"] == "INCOME"
        assert "Settle up" not in schema["x-category-types"]


class TestEditAndDelete:
    def test_delete_restores_balance(self, client, mum):
        import_file(client, mum["headers"], "2026-09-01,Bank,Transfer,84.30,out,,,")
        transaction = transfer_id(client, mum["headers"], mum["bank"])
        assert client.delete(f"{BASE_URL}/transactions/{transaction}", headers=mum["headers"]).status_code == 200
        assert balance(client, mum["headers"], mum["bank"]) == 0

    def test_description_and_date_editable(self, client, mum):
        import_file(client, mum["headers"], "2026-09-01,Bank,Transfer,84.30,out,,,")
        transaction = transfer_id(client, mum["headers"], mum["bank"])
        response = client.put(
            f"{BASE_URL}/transactions/{transaction}",
            json={"description": "To Migros", "date": "2026-09-02T12:00:00Z"},
            headers=mum["headers"],
        )
        assert response.status_code == 200, response.text
        assert response.json()["amount"] == -84.30
        assert balance(client, mum["headers"], mum["bank"]) == -84.30

    @pytest.mark.parametrize(
        "change", [{"amount": 10}, {"category_id": "Groceries"}, {"description": "x", "amount": 84.30}]
    )
    def test_amount_and_category_fixed(self, client, mum, change):
        import_file(client, mum["headers"], "2026-09-01,Bank,Transfer,84.30,out,,,")
        transaction = transfer_id(client, mum["headers"], mum["bank"])
        if "category_id" in change:
            change = {"category_id": category_id(client, change["category_id"])}
        response = client.put(f"{BASE_URL}/transactions/{transaction}", json=change, headers=mum["headers"])
        assert response.status_code == 400

    def test_nothing_becomes_a_transfer(self, client, mum):
        expense = add_transaction(client, mum["headers"], mum["bank"], category_id(client, "Groceries"), 5).json()
        response = client.put(
            f"{BASE_URL}/transactions/{expense['id']}",
            json={"category_id": category_id(client, "Transfer")},
            headers=mum["headers"],
        )
        assert response.status_code == 400

    def test_form_cannot_book_a_transfer(self, client, mum):
        response = add_transaction(client, mum["headers"], mum["bank"], category_id(client, "Transfer"), 5)
        assert response.status_code == 400


class TestSettleUpUnchanged:
    @pytest.fixture
    def settled(self, client):
        mum = register(client, "mum")
        dad = register(client, "dad")
        remove_from_hub("Admin")
        mum_account, dad_account = create_account(client, mum, "Mum bank"), create_account(client, dad, "Dad bank")
        response = client.post(
            f"{BASE_URL}/settlements",
            json={
                "from_user_id": user_id(client, mum, "dad"),
                "to_user_id": user_id(client, mum, "mum"),
                "amount": 50,
                "from_account_id": dad_account,
                "to_account_id": mum_account,
            },
            headers=dad,
        )
        assert response.status_code == 200, response.text
        rows = client.get(f"{BASE_URL}/accounts/{mum_account}/transactions", headers=mum).json()
        return mum, rows[0]["id"]

    def test_cannot_delete(self, client, settled):
        headers, transaction = settled
        assert client.delete(f"{BASE_URL}/transactions/{transaction}", headers=headers).status_code == 400

    def test_cannot_edit(self, client, settled):
        headers, transaction = settled
        response = client.put(f"{BASE_URL}/transactions/{transaction}", json={"description": "x"}, headers=headers)
        assert response.status_code == 400
