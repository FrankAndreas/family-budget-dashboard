"""The family hub (FrankAndreas/family-hub): who is logged in, and the people of this app (spec 2026-10-30, part B).

The hub's own client package (family-hub/client, "family-hub-client" in requirements.txt), set up with this app's key:
it asks the hub and keeps answers for a minute. The hub's tests keep it and its fake hub (tests/fake_hub.py) in step
with the hub. This app is home-only: its logins are the hub's token (the `hub_session` cookie), never logged."""

from family_hub_client import TIMEOUT_SECONDS, HubClient, HubPerson, HubUnavailable, Login, Session  # noqa: F401

client = HubClient(default_app_key="budget")
