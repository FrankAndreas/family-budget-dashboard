"""Wishes: each owner's list in its own order, and the parents' family plan with a running total."""

import pytest

from helpers import BASE_URL, create_split, register, user_id


@pytest.fixture
def family(client):
    mum = register(client, "mum")
    dad = register(client, "dad")
    client.put(f"{BASE_URL}/users/{user_id(client, mum, 'Admin')}", json={"is_active": False}, headers=mum)
    mum_id, dad_id = user_id(client, mum, "mum"), user_id(client, mum, "dad")
    split = create_split(client, mum, "Half", {mum_id: 50, dad_id: 50}).json()["id"]
    return {"mum": mum, "dad": dad, "mum_id": mum_id, "dad_id": dad_id, "split": split}


def add(client, headers, name, owner_id=None, split_id=None, **fields):
    body = {"name": name, "owner_id": owner_id, "split_id": split_id} | fields
    return client.post(f"{BASE_URL}/wishes", json=body, headers=headers)


def wish(client, headers, name, owner_id=None, split_id=None, **fields):
    response = add(client, headers, name, owner_id, split_id, **fields)
    assert response.status_code == 200, response.text
    return response.json()


def names(client, headers):
    return [w["name"] for w in client.get(f"{BASE_URL}/wishes", headers=headers).json()]


def share(client, headers, grantee_id, level):
    client.put(f"{BASE_URL}/shares/{grantee_id}", json={"level": level}, headers=headers)


class TestCrud:
    def test_create_edit_delete(self, client, family):
        created = wish(client, family["mum"], " Bike ", family["mum_id"], estimate=800)
        assert created["name"] == "Bike"
        assert created["price"] == 800 and created["can_edit"] is True and created["in_family_plan"] is False
        body = {
            "name": "E-bike",
            "owner_id": family["mum_id"],
            "estimate": 2500,
            "best_price": 2199.9,
            "best_shop": "Shop A",
            "best_url": "https://example.com/e-bike",
            "best_checked": "2026-10-01",
        }
        edited = client.put(f"{BASE_URL}/wishes/{created['id']}", json=body, headers=family["mum"]).json()
        assert edited["price"] == 2199.9 and edited["best_shop"] == "Shop A"
        assert client.delete(f"{BASE_URL}/wishes/{created['id']}", headers=family["mum"]).status_code == 200
        assert names(client, family["mum"]) == []

    def test_price_without_estimate(self, client, family):
        assert wish(client, family["mum"], "Something", family["mum_id"])["price"] is None

    @pytest.mark.parametrize(
        "fields",
        [{"name": ""}, {"name": "x" * 121}, {"estimate": -1}, {"best_price": -1}, {"best_url": "ftp://example.com"}],
    )
    def test_field_validation(self, client, family, fields):
        body = {"name": "Bike", "owner_id": family["mum_id"]} | fields
        assert client.post(f"{BASE_URL}/wishes", json=body, headers=family["mum"]).status_code == 422

    def test_owner_or_split(self, client, family):
        both = add(client, family["mum"], "Sofa", family["mum_id"], family["split"])
        assert both.status_code == 400 and both.json()["detail"] == "Choose either an owner or a split"
        assert add(client, family["mum"], "Sofa").status_code == 400
        assert add(client, family["mum"], "Sofa", split_id="nope").status_code == 400

    def test_new_wishes_at_the_end(self, client, family):
        for name in ("A", "B", "C"):
            wish(client, family["mum"], name, family["mum_id"])
        assert names(client, family["mum"]) == ["A", "B", "C"]


class TestVisibility:
    def test_private_without_share(self, client, family):
        dads = wish(client, family["dad"], "Drill", family["dad_id"])
        assert names(client, family["mum"]) == []
        assert client.delete(f"{BASE_URL}/wishes/{dads['id']}", headers=family["mum"]).status_code == 404
        assert add(client, family["mum"], "Drill", family["dad_id"]).status_code == 403

    def test_view_share_sees_but_cannot_change(self, client, family):
        dads = wish(client, family["dad"], "Drill", family["dad_id"])
        share(client, family["dad"], family["mum_id"], "VIEW")
        rows = client.get(f"{BASE_URL}/wishes", headers=family["mum"]).json()
        assert [(r["name"], r["can_edit"]) for r in rows] == [("Drill", False)]
        body = {"name": "Big drill", "owner_id": family["dad_id"]}
        assert client.put(f"{BASE_URL}/wishes/{dads['id']}", json=body, headers=family["mum"]).status_code == 403
        assert client.delete(f"{BASE_URL}/wishes/{dads['id']}", headers=family["mum"]).status_code == 403

    def test_edit_share_can_change(self, client, family):
        share(client, family["dad"], family["mum_id"], "EDIT")
        created = wish(client, family["mum"], "Drill", family["dad_id"])
        assert created["can_edit"] is True

    def test_common_wish_for_parents_only(self, client, family):
        wish(client, family["mum"], "Sofa", split_id=family["split"])
        assert names(client, family["dad"]) == ["Sofa"]
        kid = register(client, "kid", role="CHILD", by=family["mum"])
        assert names(client, kid) == []
        child = add(client, kid, "Sofa", split_id=family["split"])
        assert child.status_code == 403

    def test_child_own_list(self, client, family):
        kid = register(client, "kid", role="CHILD", by=family["mum"])
        kid_id = user_id(client, family["mum"], "kid")
        wish(client, kid, "Game", kid_id)
        wish(client, family["mum"], "Bike", family["mum_id"])
        assert names(client, kid) == ["Game"]
        # Parents see an allowance child's money unless the child turned privacy on
        assert "Game" in names(client, family["mum"])
