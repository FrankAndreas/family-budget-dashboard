"""Month check on clearing accounts: each completed month's own bookings add up to 0; the gap is booked once."""

from helpers import BASE_URL, create_account, register


def clearing(client, headers, name="Migros"):
    return client.post(f"{BASE_URL}/accounts", json={"name": name, "type": "CLEARING"}, headers=headers).json()["id"]


class TestSetup:
    def test_unknown_expense_seeded(self, client):
        types = {c["name"]: c["type"] for c in client.get(f"{BASE_URL}/categories").json()}
        assert types["Unknown expense"] == "EXPENSE"

    def test_clearing_account_created_and_switched(self, client):
        headers = register(client, "mum")
        bank = create_account(client, headers, "Migros")
        assert client.put(f"{BASE_URL}/accounts/{bank}", json={"type": "CLEARING"}, headers=headers).status_code == 200
        created = clearing(client, headers, "Card")
        types = {a["id"]: a["type"] for a in client.get(f"{BASE_URL}/accounts", headers=headers).json()}
        assert types[bank] == "CLEARING" and types[created] == "CLEARING"
