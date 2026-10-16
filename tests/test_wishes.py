"""Wishes: each owner's list in its own order, and the parents' family plan with a running total."""

import pytest

from app import database, models
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


def move(client, headers, wish_id, direction, which="own"):
    return client.post(
        f"{BASE_URL}/wishes/{wish_id}/move", json={"list": which, "direction": direction}, headers=headers
    )


def pin(client, headers, wish_id):
    return client.post(f"{BASE_URL}/wishes/{wish_id}/family-plan", headers=headers)


def plan(client, headers):
    return client.get(f"{BASE_URL}/wishes/family-plan", headers=headers)


class TestOwnOrder:
    def test_move_up_and_down(self, client, family):
        a, b, c = (wish(client, family["mum"], n, family["mum_id"]) for n in "ABC")
        assert move(client, family["mum"], c["id"], "up").status_code == 200
        assert names(client, family["mum"]) == ["A", "C", "B"]
        move(client, family["mum"], a["id"], "down")
        assert names(client, family["mum"]) == ["C", "A", "B"]

    def test_top_and_bottom_are_no_ops(self, client, family):
        a, b = (wish(client, family["mum"], n, family["mum_id"]) for n in "AB")
        assert move(client, family["mum"], a["id"], "up").status_code == 200
        assert move(client, family["mum"], b["id"], "down").status_code == 200
        assert names(client, family["mum"]) == ["A", "B"]

    def test_lists_are_separate(self, client, family):
        share(client, family["dad"], family["mum_id"], "EDIT")
        a, b, c = (wish(client, family["mum"], n, family["mum_id"]) for n in "ABC")
        client.delete(f"{BASE_URL}/wishes/{b['id']}", headers=family["mum"])  # mum's list: A=1, C=3
        for name in ("X", "Y"):
            wish(client, family["mum"], name, family["dad_id"])  # dad's list: X=1, Y=2
        move(client, family["mum"], c["id"], "up")  # swaps with A, not with dad's Y
        positions = {r["name"]: r["position"] for r in client.get(f"{BASE_URL}/wishes", headers=family["mum"]).json()}
        assert positions == {"C": 1, "A": 3, "X": 1, "Y": 2}

    def test_view_share_cannot_move(self, client, family):
        dads = wish(client, family["dad"], "Drill", family["dad_id"])
        share(client, family["dad"], family["mum_id"], "VIEW")
        assert move(client, family["mum"], dads["id"], "up").status_code == 403

    def test_owner_change_goes_to_the_end(self, client, family):
        share(client, family["dad"], family["mum_id"], "EDIT")
        wish(client, family["mum"], "His", family["dad_id"])
        mine = wish(client, family["mum"], "Mine", family["mum_id"])
        body = {"name": "Mine", "owner_id": family["dad_id"]}
        moved = client.put(f"{BASE_URL}/wishes/{mine['id']}", json=body, headers=family["mum"]).json()
        assert moved["position"] == 2


class TestFamilyPlan:
    def test_pin_order_and_running_total(self, client, family):
        a = wish(client, family["mum"], "Bike", family["mum_id"], estimate=800)
        b = wish(client, family["mum"], "Lamp", family["mum_id"], estimate=120, best_price=99.5)
        sofa = wish(client, family["mum"], "Sofa", split_id=family["split"], estimate=1500)
        assert sofa["in_family_plan"] is True
        pin(client, family["mum"], a["id"])
        pin(client, family["mum"], b["id"])
        assert pin(client, family["mum"], b["id"]).status_code == 200  # already in: no change
        # Dad doesn't see mum's personal wishes (no share), so he can't move them
        assert move(client, family["dad"], b["id"], "up", "family").status_code == 404
        move(client, family["mum"], b["id"], "up", "family")
        rows = plan(client, family["mum"]).json()
        assert [(r["name"], r["running_total"]) for r in rows] == [
            ("Sofa", 1500.0),
            ("Lamp", 1599.5),
            ("Bike", 2399.5),
        ]
        assert [r["name"] for r in plan(client, family["dad"]).json()] == ["Sofa"]

    def test_remove_from_plan(self, client, family):
        a = wish(client, family["mum"], "Bike", family["mum_id"])
        pin(client, family["mum"], a["id"])
        assert client.delete(f"{BASE_URL}/wishes/{a['id']}/family-plan", headers=family["mum"]).status_code == 200
        assert plan(client, family["mum"]).json() == []

    def test_common_wish_stays_in_plan(self, client, family):
        sofa = wish(client, family["mum"], "Sofa", split_id=family["split"])
        response = client.delete(f"{BASE_URL}/wishes/{sofa['id']}/family-plan", headers=family["mum"])
        assert response.status_code == 400
        assert response.json()["detail"] == "Common wishes are always in the family plan"

    def test_hidden_wishes_keep_their_place(self, client, family):
        # Dad pins his own wish without sharing it: mum doesn't see it, and her moves skip it
        first = wish(client, family["mum"], "First", split_id=family["split"])
        hidden = wish(client, family["dad"], "Hidden", family["dad_id"])
        pin(client, family["dad"], hidden["id"])
        last = wish(client, family["mum"], "Last", split_id=family["split"])
        assert [r["name"] for r in plan(client, family["mum"]).json()] == ["First", "Last"]
        move(client, family["mum"], last["id"], "up", "family")
        assert [r["name"] for r in plan(client, family["mum"]).json()] == ["Last", "First"]
        assert [r["name"] for r in plan(client, family["dad"]).json()] == ["Last", "Hidden", "First"]
        assert first["id"] != hidden["id"]

    def test_view_share_parent_may_reorder_plan_not_pin(self, client, family):
        dads = wish(client, family["dad"], "Drill", family["dad_id"])
        share(client, family["dad"], family["mum_id"], "VIEW")
        assert pin(client, family["mum"], dads["id"]).status_code == 403
        pin(client, family["dad"], dads["id"])
        wish(client, family["mum"], "Sofa", split_id=family["split"])
        assert move(client, family["mum"], dads["id"], "down", "family").status_code == 200

    def test_children_have_no_plan(self, client, family):
        kid = register(client, "kid", role="CHILD", by=family["mum"])
        game = wish(client, kid, "Game", user_id(client, family["mum"], "kid"))
        assert plan(client, kid).status_code == 403
        assert pin(client, kid, game["id"]).status_code == 403

    def test_move_needs_plan(self, client, family):
        a = wish(client, family["mum"], "Bike", family["mum_id"])
        response = move(client, family["mum"], a["id"], "up", "family")
        assert response.status_code == 400 and response.json()["detail"] == "Not in the family plan"


class TestBought:
    def test_bought_leaves_lists_and_comes_back(self, client, family):
        a, b, c = (wish(client, family["mum"], n, family["mum_id"], estimate=10) for n in "ABC")
        pin(client, family["mum"], b["id"])
        response = client.post(
            f"{BASE_URL}/wishes/{b['id']}/bought", json={"bought_on": "2026-10-10"}, headers=family["mum"]
        )
        assert response.json()["bought_on"] == "2026-10-10"
        assert plan(client, family["mum"]).json() == []
        move(client, family["mum"], c["id"], "up")  # skips the bought wish
        rows = {r["name"]: r["position"] for r in client.get(f"{BASE_URL}/wishes", headers=family["mum"]).json()}
        assert rows["C"] < rows["A"]
        client.delete(f"{BASE_URL}/wishes/{b['id']}/bought", headers=family["mum"])
        assert [r["name"] for r in plan(client, family["mum"]).json()] == ["B"]

    def test_bought_defaults_to_today(self, client, family):
        a = wish(client, family["mum"], "Bike", family["mum_id"])
        assert client.post(f"{BASE_URL}/wishes/{a['id']}/bought", json={}, headers=family["mum"]).json()["bought_on"]

    def test_bought_wish_cannot_move(self, client, family):
        a = wish(client, family["mum"], "Bike", family["mum_id"])
        client.post(f"{BASE_URL}/wishes/{a['id']}/bought", json={}, headers=family["mum"])
        assert move(client, family["mum"], a["id"], "up").status_code == 400


class TestCleanup:
    def test_wishes_go_with_their_owner(self, client, family):
        kid = register(client, "kid", role="CHILD", by=family["mum"])
        kid_id = user_id(client, family["mum"], "kid")
        wish(client, kid, "Game", kid_id)
        assert client.delete(f"{BASE_URL}/users/{kid_id}", headers=family["mum"]).status_code == 200
        with database.SessionLocal() as db:
            assert db.query(models.Wish).count() == 0

    def test_split_in_use_by_a_wish(self, client, family):
        wish(client, family["mum"], "Sofa", split_id=family["split"])
        response = client.delete(f"{BASE_URL}/splits/{family['split']}", headers=family["mum"])
        assert response.status_code == 409
