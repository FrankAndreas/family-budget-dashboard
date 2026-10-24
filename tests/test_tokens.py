"""Login tokens: only HS256 tokens signed with our key are accepted, whatever JWT library signs them."""

import base64
import hashlib
import hmac
import json
from datetime import timedelta

from app import auth
from helpers import BASE_URL, admin_headers, register, user_id


def part(data):
    return base64.urlsafe_b64encode(json.dumps(data).encode()).rstrip(b"=").decode()


def token(claims, key=None, alg="HS256"):
    """A JWT built by hand, so the test doesn't depend on the library the app uses."""
    unsigned = f"{part({'alg': alg, 'typ': 'JWT'})}.{part(claims)}"
    if alg == "none":
        return f"{unsigned}."
    signature = hmac.new((key or auth.SECRET_KEY).encode(), unsigned.encode(), hashlib.sha256).digest()
    return f"{unsigned}.{base64.urlsafe_b64encode(signature).rstrip(b'=').decode()}"


def me(client, value):
    return client.get(f"{BASE_URL}/me", headers={"Authorization": f"Bearer {value}"}).status_code


def claims(client, **extra):
    register(client, "mum")
    expires = int((auth.now() + timedelta(hours=1) - auth.datetime(1970, 1, 1)).total_seconds())
    return {"sub": user_id(client, admin_headers(client), "mum"), "ver": 0, "exp": expires, **extra}


def test_token_signed_with_our_key_works(client):
    # Tokens issued before a library change stay valid: they are plain HS256
    assert me(client, token(claims(client))) == 200


def test_unsigned_token_refused(client):
    assert me(client, token(claims(client), alg="none")) == 401


def test_other_key_refused(client):
    assert me(client, token(claims(client), key="not-our-key")) == 401


def test_expired_token_refused(client):
    assert me(client, token(claims(client, exp=1000))) == 401


def test_garbage_refused(client):
    assert me(client, "not.a.token") == 401
