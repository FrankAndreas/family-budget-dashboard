"""Export for analysis: a ZIP of CSV files plus a README, limited to what the user can see."""

import csv
import io
import zipfile
from datetime import date

import pytest

from app import common_api
from helpers import BASE_URL, add_transaction, category_id, create_account, create_split, register, user_id

HEADERS = {
    "members.csv": "member_id,name,role,has_allowance,is_active",
    "categories.csv": "category_id,name,type",
    "accounts.csv": "account_id,name,type,iban,owner_id,owner,balance",
    "transactions.csv": "transaction_id,date,account_id,account,owner_id,owner,category_id,category,category_type,"
    "amount,description,for_member_id,for_member,split_id,split,investment_id,investment,reference,investment_purchase",
    "shared_expense_shares.csv": "transaction_id,date,payer_id,payer,amount,member_id,member,percent,share",
    "settlements.csv": "settlement_id,date,from_id,from,to_id,to,amount",
    "budgets.csv": "budget_id,owner_id,owner,category_id,category,tag_id,tag,limit,period",
    "items.csv": "item_id,transaction_id,position,name,amount,category_id,category,person_id,person,tags",
    "tags.csv": "tag_id,name,icon",
    "splits.csv": "split_id,name,member_id,member,percent",
    "investments.csv": "investment_id,name,owner_id,owner,split_id,split,price,purchase_date,lifespan_years,"
    "age_years,replacement_due,monthly_set_aside,follow_up_costs,total_cost,cost_per_year,notes,tag_ids,tags,archived_on,kind,lease_rate,lease_months,lease_final,lease_end,monthly_load",
    "planned_costs.csv": "planned_cost_id,name,category_id,category,amount,frequency,due_month,next_due,monthly,"
    "owner_id,owner,split_id,split,notes",
    "bank_rows.csv": "bank_row_id,account_id,account,booked_on,valuta_on,text,amount,balance,transaction_id,reference",
    "wishes.csv": "wish_id,name,owner_id,owner,split_id,split,estimate,best_price,best_shop,best_url,best_checked,"
    "price,position,family_position,bought_on,notes",
}


def export(client, headers):
    response = client.get(f"{BASE_URL}/export/analysis.zip", headers=headers)
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/zip"
    return zipfile.ZipFile(io.BytesIO(response.content))


def rows(archive, name):
    return list(csv.DictReader(io.StringIO(archive.read(name).decode("utf-8"))))


@pytest.fixture
def family(client, monkeypatch):
    monkeypatch.setattr(common_api, "today", lambda: date(2026, 10, 14))
    mum = register(client, "mum")
    dad = register(client, "dad")
    client.put(f"{BASE_URL}/users/{user_id(client, mum, 'Admin')}", json={"is_active": False}, headers=mum)
    mum_id, dad_id = user_id(client, mum, "mum"), user_id(client, mum, "dad")
    return {
        "mum": mum,
        "dad": dad,
        "mum_id": mum_id,
        "dad_id": dad_id,
        "mum_account": create_account(client, mum, "Mum bank"),
        "dad_account": create_account(client, dad, "Dad bank"),
        "split": create_split(client, mum, "Equal", {mum_id: 50, dad_id: 50}).json()["id"],
    }


def test_files_and_headers(client, family):
    archive = export(client, family["mum"])
    assert set(archive.namelist()) == set(HEADERS) | {"README.md"}
    for name, header in HEADERS.items():
        assert archive.read(name).decode("utf-8").splitlines()[0] == header


def test_readme_names_user_and_date(client, family):
    readme = export(client, family["mum"]).read("README.md").decode("utf-8")
    assert "mum" in readme
    assert date.today().isoformat() in readme
    assert "TRANSFER" in readme


def test_only_what_the_user_can_see(client, family):
    groceries = category_id(client, "Groceries")
    add_transaction(client, family["mum"], family["mum_account"], groceries, 10, date="2026-10-01T08:00:00Z")
    add_transaction(client, family["dad"], family["dad_account"], groceries, 20)
    archive = export(client, family["mum"])
    assert [a["name"] for a in rows(archive, "accounts.csv")] == ["Mum bank"]
    [t] = rows(archive, "transactions.csv")
    assert (t["account"], t["owner"], t["category"], t["category_type"]) == ("Mum bank", "mum", "Groceries", "EXPENSE")
    assert (t["amount"], t["date"]) == ("-10.0", "2026-10-01T08:00:00Z")

    client.put(f"{BASE_URL}/shares/{family['mum_id']}", json={"level": "VIEW"}, headers=family["dad"])
    archive = export(client, family["mum"])
    assert {a["name"] for a in rows(archive, "accounts.csv")} == {"Mum bank", "Dad bank"}
    assert len(rows(archive, "transactions.csv")) == 2


def test_child_gets_own_data_and_empty_common_files(client, family):
    teen = register(client, "teen", role="CHILD", by=family["mum"])
    account = create_account(client, teen, "Teen bank")
    add_transaction(client, teen, account, category_id(client, "Entertainment"), 5)
    archive = export(client, teen)
    assert [a["name"] for a in rows(archive, "accounts.csv")] == ["Teen bank"]
    assert len(rows(archive, "transactions.csv")) == 1
    for name in ("shared_expense_shares.csv", "settlements.csv", "splits.csv", "investments.csv", "planned_costs.csv"):
        assert rows(archive, name) == []


def test_private_child_hidden_from_parents(client, family):
    teen = register(client, "teen", role="CHILD", by=family["mum"])
    create_account(client, teen, "Teen bank")
    client.patch(f"{BASE_URL}/me/privacy", json={"privacy_enabled": True}, headers=teen)
    archive = export(client, family["mum"])
    assert "teen" not in {m["name"] for m in rows(archive, "members.csv")}
    assert "Teen bank" not in {a["name"] for a in rows(archive, "accounts.csv")}


def test_shared_expense_shares_and_settlement(client, family):
    expense = add_transaction(
        client, family["mum"], family["mum_account"], category_id(client, "Groceries"), 100, split_id=family["split"]
    ).json()
    client.post(
        f"{BASE_URL}/settlements",
        json={
            "from_user_id": family["dad_id"],
            "to_user_id": family["mum_id"],
            "amount": 50,
            "from_account_id": family["dad_account"],
            "to_account_id": family["mum_account"],
        },
        headers=family["dad"],
    )
    archive = export(client, family["mum"])
    shares = rows(archive, "shared_expense_shares.csv")
    assert {(s["member"], s["percent"], s["share"]) for s in shares} == {("mum", "50", "50.0"), ("dad", "50", "50.0")}
    assert {s["transaction_id"] for s in shares} == {expense["id"]}
    assert shares[0]["payer"] == "mum"
    [settlement] = rows(archive, "settlements.csv")
    assert (settlement["from"], settlement["to"], settlement["amount"]) == ("dad", "mum", "50.0")
    types = {t["category"]: t["category_type"] for t in rows(archive, "transactions.csv")}
    assert types["Settle up"] == "TRANSFER"
    [shared] = [t for t in rows(archive, "transactions.csv") if t["split"]]
    assert shared["split"] == "Equal"
    assert {(s["name"], s["member"], s["percent"]) for s in rows(archive, "splits.csv")} == {
        ("Equal", "mum", "50"),
        ("Equal", "dad", "50"),
    }


def test_investments_and_planned_costs(client, family):
    mobility = client.post(f"{BASE_URL}/tags", json={"name": "Mobility"}, headers=family["mum"]).json()
    car = client.post(
        f"{BASE_URL}/assets",
        json={
            "name": "Car",
            "price": 24000,
            "purchase_date": "2022-10-14",
            "lifespan_years": 8,
            "split_id": family["split"],
            "tag_ids": [mobility["id"]],
        },
        headers=family["mum"],
    ).json()
    add_transaction(
        client, family["mum"], family["mum_account"], category_id(client, "Transportation"), 600, asset_id=car["id"]
    )
    client.post(f"{BASE_URL}/assets/{car['id']}/archive", json={"archived_on": "2026-10-14"}, headers=family["mum"])
    client.post(
        f"{BASE_URL}/planned-costs",
        json={
            "name": "Insurance",
            "category_id": category_id(client, "Healthcare"),
            "amount": 1200,
            "frequency": "YEARLY",
            "due_month": 1,
            "owner_id": family["mum_id"],
        },
        headers=family["mum"],
    )
    archive = export(client, family["mum"])
    [investment] = rows(archive, "investments.csv")
    assert investment["split"] == "Equal"
    assert (investment["tags"], investment["archived_on"]) == ("Mobility", "2026-10-14")
    assert (investment["kind"], investment["lease_end"]) == ("PURCHASE", "")
    assert (investment["age_years"], investment["replacement_due"]) == ("4.0", "2030-10-14")
    assert (investment["follow_up_costs"], investment["total_cost"]) == ("600.0", "24600.0")
    [transaction] = [t for t in rows(archive, "transactions.csv") if t["investment"]]
    assert (transaction["investment"], transaction["investment_purchase"]) == ("Car", "False")
    [bill] = rows(archive, "planned_costs.csv")
    assert (bill["name"], bill["owner"], bill["next_due"], bill["monthly"]) == (
        "Insurance",
        "mum",
        "2027-01-01",
        "100.0",
    )
    # Dad can't see mum's personal bill
    assert rows(export(client, family["dad"]), "planned_costs.csv") == []


def test_wishes_follow_visibility(client):
    mum = register(client, "mum")
    dad = register(client, "dad")
    client.post(
        f"{BASE_URL}/wishes",
        json={"name": "Bike", "owner_id": user_id(client, mum, "mum"), "estimate": 800},
        headers=mum,
    )
    client.post(f"{BASE_URL}/wishes", json={"name": "Drill", "owner_id": user_id(client, dad, "dad")}, headers=dad)
    wishes = rows(export(client, mum), "wishes.csv")
    assert [(w["name"], w["price"]) for w in wishes] == [("Bike", "800.0")]


def test_items_and_tags_in_the_zip(client):
    from helpers import admin_headers

    admin = admin_headers(client)
    velo = client.post(f"{BASE_URL}/tags", json={"name": "Velo", "icon": "🚲"}, headers=admin).json()["id"]
    sport = client.post(f"{BASE_URL}/tags", json={"name": "Sport"}, headers=admin).json()["id"]
    mum = register(client, "mum")
    me = user_id(client, mum, "mum")
    account = create_account(client, mum)
    receipt = client.post(
        f"{BASE_URL}/transactions",
        json={
            "account_id": account,
            "items": [
                {"name": "Brot", "amount": 3.5, "category_id": category_id(client, "Groceries")},
                {
                    "name": "Velo-Hose",
                    "amount": 79.9,
                    "category_id": category_id(client, "Clothing"),
                    "person_id": me,
                    "tag_ids": [velo, sport],
                },
            ],
        },
        headers=mum,
    ).json()
    client.post(f"{BASE_URL}/budgets", json={"tag_id": velo, "limit": 4000, "period": "YEARLY"}, headers=mum)
    archive = export(client, mum)
    items = rows(archive, "items.csv")
    assert [
        (i["transaction_id"], i["position"], i["name"], i["amount"], i["category"], i["person"], i["tags"])
        for i in items
    ] == [
        (receipt["id"], "0", "Brot", "3.5", "Groceries", "", ""),
        (receipt["id"], "1", "Velo-Hose", "79.9", "Clothing", "mum", "Sport;Velo"),
    ]
    assert {(t["name"], t["icon"]) for t in rows(archive, "tags.csv")} == {("Velo", "🚲"), ("Sport", "")}
    assert rows(archive, "budgets.csv")[0]["tag"] == "Velo"
    readme = archive.read("README.md").decode()
    assert "`items.csv`" in readme and "`tags.csv`" in readme
    # Someone who can't see mum's accounts doesn't get her items
    dad = register(client, "dad")
    assert rows(export(client, dad), "items.csv") == []


def test_bank_rows_in_the_zip(client, family):
    # Invented IBAN and text (the repository is public)
    from test_bank_import import HOUSEHOLD, account, bank_file, line
    from test_import import upload

    household = account(client, family["mum"], "Household", HOUSEHOLD)
    content = bank_file(line("Einkauf TWINT Muster", "-84.30", booked="2026-09-05", saldo="915.70"))
    assert upload(client, family["mum"], content, name="export.csv", path="import").status_code == 200
    archive = export(client, family["mum"])
    [booking] = [t for t in rows(archive, "transactions.csv") if t["account"] == "Household"]
    [row] = rows(archive, "bank_rows.csv")
    assert (row["account_id"], row["account"], row["booked_on"], row["valuta_on"]) == (
        household,
        "Household",
        "2026-09-05",
        "2026-09-05",
    )
    assert (row["text"], row["amount"], row["balance"]) == ("Einkauf TWINT Muster", "-84.3", "915.7")
    assert (row["transaction_id"], row["reference"]) == (booking["transaction_id"], booking["reference"])
    # Dad can't see mum's accounts, so not their bank lines either
    assert rows(export(client, family["dad"]), "bank_rows.csv") == []
