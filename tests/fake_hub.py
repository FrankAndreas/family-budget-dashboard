"""A stand-in for the family hub in the backend tests: the hub client's own fake (family-hub/client), which answers
the client's requests as the hub does. Each person's token is "tok-<name>". Invented people only: the repository is
public."""

from family_hub_client.fake import FakeHub as _FakeHub
from family_hub_client.fake import token  # noqa: F401


class FakeHub(_FakeHub):
    """People speak English unless a test says otherwise (the tests find the English texts)."""

    def add(self, name: str, role: str = "PARENT", access: bool = True, language: str = "en", **extra) -> str:
        return super().add(name, role, access, language, **extra)


# The hub of the running test (set by conftest's autouse fixture)
current: FakeHub
