"""Bulk import of transactions from a CSV or JSON file written by an external tool."""

import json

import pytest

from helpers import (
    add_member,
    remove_from_hub,
    BASE_URL,
    add_transaction,
    balance,
    category_id,
    create_account,
    create_split,
    register,
    user_id,
)


class TestReference:
    def test_transaction_keeps_reference(self, client):
        headers = register(client, "p")
        account = create_account(client, headers)
        t = add_transaction(client, headers, account, category_id(client, "Groceries"), 5, reference="r1").json()
        assert t["reference"] == "r1"
        assert (
            add_transaction(client, headers, account, category_id(client, "Groceries"), 5).json()["reference"] is None
        )

    def test_reference_length_limited(self, client):
        headers = register(client, "p")
        account = create_account(client, headers)
        response = add_transaction(client, headers, account, category_id(client, "Groceries"), 5, reference="x" * 201)
        assert response.status_code == 422


HEADER = "date,account,category,amount,description,for,shared,item,reference"


def upload(client, headers, content, name="receipts.csv", path="import/preview", **data):
    body = content.encode("utf-8") if isinstance(content, str) else content
    return client.post(f"{BASE_URL}/{path}", files={"file": (name, body)}, data=data, headers=headers)


def preview(client, headers, content, name="receipts.csv"):
    response = upload(client, headers, content, name)
    assert response.status_code == 200, response.text
    return response.json()


def csv_file(*lines, header=HEADER):
    return "\n".join([header, *lines]) + "\n"


@pytest.fixture
def family(client):
    mum = register(client, "mum")
    dad = register(client, "dad")
    remove_from_hub("Admin")
    mum_id, dad_id = user_id(client, mum, "mum"), user_id(client, mum, "dad")
    add_member(client, "Timmy")
    return {
        "mum": mum,
        "dad": dad,
        "mum_id": mum_id,
        "dad_id": dad_id,
        "mum_account": create_account(client, mum, "Postfinance"),
        "dad_account": create_account(client, dad, "Postfinance"),
        "split": create_split(client, mum, "Equal 50/50", {mum_id: 50, dad_id: 50}).json()["id"],
    }


def transactions(client, headers, account):
    return client.get(f"{BASE_URL}/accounts/{account}/transactions", headers=headers).json()


class TestParsing:
    def test_csv_with_commas(self, client, family):
        result = preview(client, family["mum"], csv_file("2026-10-12,Postfinance,Groceries,84.30,Migros,,,,r1"))
        assert (result["ok"], result["duplicates"], result["errors"]) == (1, 0, 0)
        [row] = result["rows"]
        assert (row["line"], row["status"], row["account"], row["amount"]) == (2, "ok", "Postfinance", "84.30")
        assert transactions(client, family["mum"], family["mum_account"]) == []

    def test_csv_with_semicolons_bom_and_upper_case_header(self, client, family):
        content = "﻿Date;Account;Category;Amount;Description\n2026-10-12;postfinance ; GROCERIES;84.30;Coop\n\n"
        result = preview(client, family["mum"], content)
        assert (result["ok"], result["errors"]) == (1, 0)

    def test_json(self, client, family):
        content = json.dumps(
            {"transactions": [{"date": "2026-10-12", "account": "Postfinance", "category": "Groceries", "amount": 5}]}
        )
        result = preview(client, family["mum"], content, name="receipts.json")
        assert (result["ok"], result["rows"][0]["line"], result["rows"][0]["amount"]) == (1, 1, "5")

    def test_limits_and_bad_files(self, client, family):
        too_many = csv_file(*["2026-10-12,Postfinance,Groceries,1"] * 1001)
        assert upload(client, family["mum"], too_many).status_code == 400
        assert upload(client, family["mum"], b"x" * (1024 * 1024 + 1)).status_code == 400
        assert upload(client, family["mum"], "{not json", name="a.json").status_code == 400
        assert upload(client, family["mum"], b"\xff\xfe\x00bad").status_code == 400
        assert upload(client, family["mum"], HEADER + "\n").status_code == 400
        assert upload(client, family["mum"], json.dumps({"rows": []}), name="a.json").status_code == 400


class TestValidation:
    def errors(self, client, headers, *lines, header=HEADER):
        return [row["errors"] for row in preview(client, headers, csv_file(*lines, header=header))["rows"]]

    def test_field_errors(self, client, family):
        rows = self.errors(
            client,
            family["mum"],
            ",Postfinance,Groceries,5",
            "12.10.2026,Postfinance,Groceries,5",
            "2026-10-12,Postfinance,Groceries,",
            "2026-10-12,Postfinance,Groceries,0",
            "2026-10-12,Postfinance,Groceries,-5",
            '2026-10-12,Postfinance,Groceries,"84,30"',
            "2026-10-12,Nope,Groceries,5",
            "2026-10-12,Postfinance,Nope,5",
            "2026-10-12,Postfinance,Settle up,5",
            "2026-10-12,Postfinance,Groceries,5,,Nobody",
            "2026-10-12,Postfinance,Groceries,5,,,No split",
            "2026-10-12,Postfinance,Groceries,5,,,,No item",
            "2026-10-12,Postfinance,Salary,5,,,Equal 50/50",
            "2026-10-12,Postfinance,Groceries,5," + "x" * 201,
        )
        assert all(len(errors) == 1 for errors in rows), rows
        joined = [errors[0] for errors in rows]
        for expected, message in zip(
            [
                "date",
                "date",
                "amount",
                "amount",
                "amount",
                "amount",
                "Unknown account",
                "Unknown category",
                "Settle up",
                "Unknown child",
                "Unknown split",
                "Unknown investment",
                "Only expenses can be shared",
                "description",
            ],
            joined,
        ):
            assert expected in message, (expected, message)

    def test_error_status_and_counts(self, client, family):
        result = preview(
            client, family["mum"], csv_file("2026-10-12,Nope,Groceries,5", "2026-10-12,Postfinance,Groceries,5")
        )
        assert (result["ok"], result["errors"]) == (1, 1)
        assert result["rows"][0]["status"] == "error"

    def test_view_account_rejected(self, client, family):
        client.put(f"{BASE_URL}/shares/{family['mum_id']}", json={"level": "VIEW"}, headers=family["dad"])
        [errors] = self.errors(client, family["mum"], "2026-10-12,Postfinance,Groceries,5,,,,,", header=HEADER)
        assert errors == []  # own account with that name wins
        [errors] = self.errors(
            client, family["mum"], "2026-10-12,Postfinance,dad,Groceries,5", header="date,account,owner,category,amount"
        )
        assert "viewing only" in errors[0]

    def test_ambiguous_account_needs_owner(self, client, family):
        client.put(f"{BASE_URL}/shares/{family['mum_id']}", json={"level": "EDIT"}, headers=family["dad"])
        header = "date,account,owner,category,amount"
        own, dads = preview(
            client,
            family["mum"],
            csv_file("2026-10-12,Postfinance,,Groceries,5", "2026-10-12,Postfinance,Dad,Groceries,6", header=header),
        )["rows"]
        assert (own["errors"], dads["errors"]) == ([], [])
        # Neither account is mum's own: she has to say whose
        create_account(client, family["dad"], "Cash")
        teen = register(client, "teen", role="CHILD", by=family["mum"])
        create_account(client, teen, "Cash")
        client.put(f"{BASE_URL}/shares/{family['mum_id']}", json={"level": "EDIT"}, headers=teen)
        [errors] = self.errors(client, family["mum"], "2026-10-12,Cash,,Groceries,5", header=header)
        assert "Several accounts" in errors[0]
        [errors] = self.errors(client, family["mum"], "2026-10-12,Cash,teen,Groceries,5", header=header)
        assert errors == []

    def test_tags_shared_and_item_resolved(self, client, family):
        client.post(
            f"{BASE_URL}/assets",
            json={
                "name": "Car",
                "price": 100,
                "purchase_date": "2022-01-01",
                "lifespan_years": 8,
                "split_id": family["split"],
            },
            headers=family["mum"],
        )
        [row] = preview(
            client, family["mum"], csv_file("2026-10-12,Postfinance,Transportation,5,,timmy,equal 50/50,car,")
        )["rows"]
        assert row["status"] == "ok", row

    def test_child_cannot_share_or_tag(self, client, family):
        teen = register(client, "teen", role="CHILD", by=family["mum"])
        create_account(client, teen, "Pocket")
        [tagged, shared] = self.errors(
            client, teen, "2026-10-12,Pocket,Groceries,5,,Timmy", "2026-10-12,Pocket,Groceries,5,,,Equal 50/50"
        )
        assert tagged and shared


class TestDuplicates:
    def test_by_reference_and_by_day_amount_category(self, client, family):
        groceries = category_id(client, "Groceries")
        existing = add_transaction(
            client, family["mum"], family["mum_account"], groceries, 84.3, date="2026-10-12T15:00:00Z", reference="r1"
        ).json()
        add_transaction(client, family["mum"], family["mum_account"], groceries, 9, date="2026-10-01T08:00:00Z")
        rows = preview(
            client,
            family["mum"],
            csv_file(
                "2026-10-20,Postfinance,Groceries,1,,,,,r1",
                "2026-10-01,Postfinance,Groceries,9,,,,,",
                "2026-10-02,Postfinance,Groceries,9,,,,,",
                "2026-10-03,Postfinance,Groceries,3,,,,,r2",
                "2026-10-04,Postfinance,Groceries,4,,,,,r2",
            ),
        )["rows"]
        assert [r["status"] for r in rows] == ["duplicate", "duplicate", "ok", "ok", "duplicate"]
        assert rows[0]["duplicate_of"] == existing["id"]
        assert "2026-10-12" in rows[0]["note"]
        assert (rows[4]["duplicate_of"], "line 5" in rows[4]["note"]) == (None, True)


class TestBooking:
    def test_imports_rows_in_one_go(self, client, family):
        content = csv_file(
            "2026-10-12,Postfinance,Groceries,84.30,Migros,,Equal 50/50,,r1",
            "2026-10-13T08:00:00+02:00,Postfinance,Salary,100,,,,,",
        )
        response = upload(client, family["mum"], content, path="import")
        assert response.json() == {"imported": 2, "skipped": 0}
        booked = sorted(transactions(client, family["mum"], family["mum_account"]), key=lambda t: t["date"])
        assert [(t["amount"], t["date"], t["reference"]) for t in booked] == [
            (-84.3, "2026-10-12T12:00:00Z", "r1"),
            (100.0, "2026-10-13T06:00:00Z", None),
        ]
        assert booked[0]["split_shares"] == {family["mum_id"]: 50, family["dad_id"]: 50}
        assert balance(client, family["mum"], family["mum_account"]) == 15.7

    def test_duplicates_skipped_unless_included(self, client, family):
        content = csv_file("2026-10-12,Postfinance,Groceries,5,,,,,r1", "2026-10-12,Postfinance,Groceries,6,,,,,r1")
        assert upload(client, family["mum"], content, path="import").json() == {"imported": 1, "skipped": 1}
        assert upload(client, family["mum"], content, path="import").json() == {"imported": 0, "skipped": 2}
        result = upload(client, family["mum"], content, path="import", include_duplicates="2,3").json()
        assert result == {"imported": 2, "skipped": 0}
        assert len(transactions(client, family["mum"], family["mum_account"])) == 3

    def test_error_stores_nothing(self, client, family):
        content = csv_file(
            "2026-10-12,Postfinance,Groceries,5", "2026-10-12,Nope,Groceries,5", header="date,account,category,amount"
        )
        response = upload(client, family["mum"], content, path="import")
        assert response.status_code == 400
        assert response.json()["detail"]["rows"][1]["status"] == "error"
        assert transactions(client, family["mum"], family["mum_account"]) == []
        assert balance(client, family["mum"], family["mum_account"]) == 0


class TestSchemaAndTemplate:
    def test_schema_lists_valid_names(self, client, family):
        schema = client.get(f"{BASE_URL}/import/schema", headers=family["mum"]).json()
        item = schema["properties"]["transactions"]["items"]
        assert item["required"] == ["date", "account", "category", "amount"]
        props = item["properties"]
        assert props["account"]["enum"] == ["Postfinance"]
        assert "Groceries" in props["category"]["enum"] and "Settle up" not in props["category"]["enum"]
        assert props["for"]["enum"] == ["Timmy"]
        assert props["shared"]["enum"] == ["Equal 50/50"]
        assert all(p.get("description") for p in props.values())

    def test_child_schema_has_no_sharing(self, client, family):
        teen = register(client, "teen", role="CHILD", by=family["mum"])
        create_account(client, teen, "Pocket")
        props = client.get(f"{BASE_URL}/import/schema", headers=teen).json()["properties"]["transactions"]["items"][
            "properties"
        ]
        assert props["account"]["enum"] == ["Pocket"]
        assert "shared" not in props and "for" not in props

    def test_template(self, client, family):
        response = client.get(f"{BASE_URL}/import/template.csv", headers=family["mum"])
        assert response.status_code == 200
        lines = response.text.splitlines()
        assert lines[0] == HEADER
        assert len(lines) == 3
