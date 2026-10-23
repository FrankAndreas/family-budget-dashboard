"""Reading a receipt with the AI takes seconds; meanwhile the backend keeps answering others (issue #75)."""

import asyncio
import json
import time

import httpx
import pytest

from files import image_png
from helpers import BASE_URL, register

from app import main, receipt_ai


class SlowAi:
    def complete(self, content):
        # A blocking call, like the real urllib request to the AI service
        time.sleep(1.0)
        return json.dumps({"shop": "x", "date": "2026-10-20", "total": 1, "items": []})


def test_reading_does_not_block_other_requests(client, monkeypatch):
    monkeypatch.setenv("INFOMANIAK_AI_TOKEN", "t")
    monkeypatch.setenv("INFOMANIAK_AI_PRODUCT_ID", "p")
    monkeypatch.setattr(receipt_ai, "client_for", lambda settings: SlowAi())
    headers = register(client, "mum")

    async def scenario():
        transport = httpx.ASGITransport(app=main.app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as http:
            started = time.monotonic()
            reading = asyncio.create_task(
                http.post(f"{BASE_URL}/receipts/read", files={"file": ("beleg.png", image_png())}, headers=headers)
            )
            await asyncio.sleep(0.2)
            health = await http.get("/health")
            # The AI takes 1 s; answering /health must not wait for it
            waited = time.monotonic() - started
            assert (await reading).status_code == 200
            return health.status_code, waited

    status, waited = asyncio.run(scenario())
    assert status == 200
    assert waited < 0.8, f"/health answered after {waited:.2f} s, only once the AI reading was done"
