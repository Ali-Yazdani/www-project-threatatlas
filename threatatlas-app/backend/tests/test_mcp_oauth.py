"""Tests for the OAuth 2.1 authorization-code + PKCE browser-login flow
backing the /mcp server (app/mcp/oauth_provider.py, app/routers/mcp_oauth_ui.py).

Full happy path: dynamic client registration -> /authorize redirects to our
own first-party login page -> login -> consent -> /token exchange -> minted
access token works against /mcp. Plus the PKCE/replay/expiry edge cases the
SDK's TokenHandler enforces, and a refresh-token rotation round trip.

The shared TestClient fixture is session-scoped (see tests/conftest.py), so
its cookie jar persists across tests — every test that starts a browser
session clears cookies first to avoid inheriting a previous test's login.
"""

import base64
import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, urlparse

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models import User
from app.models.mcp_oauth import McpAuthorizationCode, McpOAuthClient
from tests.test_mcp_server import rpc_post

REDIRECT_URI = "https://client.example.com/callback"


def _pkce_pair() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(48)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
    return verifier, challenge


def _register_client(client: TestClient, auth_method: str = "none") -> dict:
    resp = client.post(
        "/register",
        json={
            "redirect_uris": [REDIRECT_URI],
            "token_endpoint_auth_method": auth_method,
            "client_name": "Test MCP Client",
        },
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def _authorize(client: TestClient, client_id: str, code_challenge: str, state: str = "xyz") -> str:
    """GET /authorize; returns the `req` id from the redirect to /oauth/login."""
    resp = client.get(
        "/authorize",
        params={
            "response_type": "code",
            "client_id": client_id,
            "redirect_uri": REDIRECT_URI,
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
            "state": state,
        },
        follow_redirects=False,
    )
    assert resp.status_code == 302, resp.text
    location = urlparse(resp.headers["location"])
    assert location.path == "/oauth/login"
    return parse_qs(location.query)["req"][0]


def _login(client: TestClient, req: str, email: str, password: str = "testpass123") -> None:
    resp = client.post("/oauth/login", data={"req": req, "email": email, "password": password})
    assert resp.status_code == 200, resp.text
    assert "Authorize access" in resp.text


def _consent(client: TestClient, req: str, action: str = "approve") -> str:
    resp = client.post("/oauth/consent", data={"req": req, "action": action}, follow_redirects=False)
    assert resp.status_code == 302, resp.text
    return resp.headers["location"]


def _exchange_code(client: TestClient, client_id: str, code: str, code_verifier: str) -> dict:
    return client.post(
        "/token",
        data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": REDIRECT_URI,
            "client_id": client_id,
            "code_verifier": code_verifier,
        },
    )


def _full_flow(client: TestClient, standard_user: User) -> dict:
    """Runs registration -> authorize -> login -> consent -> token exchange,
    returning the parsed /token JSON body."""
    client.cookies.clear()
    registration = _register_client(client)
    verifier, challenge = _pkce_pair()

    req = _authorize(client, registration["client_id"], challenge)
    _login(client, req, standard_user.email)
    location = _consent(client, req)

    query = parse_qs(urlparse(location).query)
    assert urlparse(location).path == "/callback"
    code = query["code"][0]
    assert query["state"][0] == "xyz"

    resp = _exchange_code(client, registration["client_id"], code, verifier)
    assert resp.status_code == 200, resp.text
    return resp.json()


# ── Happy path ───────────────────────────────────────────────────────────────

def test_full_oauth_flow_mints_working_access_token(client: TestClient, standard_user: User):
    tokens = _full_flow(client, standard_user)
    assert tokens["token_type"] == "Bearer"
    assert tokens["access_token"]
    assert tokens["refresh_token"]

    resp = rpc_post(
        client,
        {"Authorization": f"Bearer {tokens['access_token']}"},
        {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}},
    )
    assert resp.status_code == 200, resp.text
    tool_names = {t["name"] for t in resp.json()["result"]["tools"]}
    assert "list_products" in tool_names


def test_consent_deny_redirects_with_access_denied(client: TestClient, standard_user: User):
    client.cookies.clear()
    registration = _register_client(client)
    _verifier, challenge = _pkce_pair()

    req = _authorize(client, registration["client_id"], challenge)
    _login(client, req, standard_user.email)
    location = _consent(client, req, action="deny")

    query = parse_qs(urlparse(location).query)
    assert query["error"][0] == "access_denied"
    assert query["state"][0] == "xyz"


def test_refresh_token_rotation_round_trip(client: TestClient, standard_user: User):
    client.cookies.clear()
    registration = _register_client(client)
    verifier, challenge = _pkce_pair()

    req = _authorize(client, registration["client_id"], challenge)
    _login(client, req, standard_user.email)
    location = _consent(client, req)
    code = parse_qs(urlparse(location).query)["code"][0]

    first = _exchange_code(client, registration["client_id"], code, verifier)
    assert first.status_code == 200, first.text
    first_tokens = first.json()

    refreshed = client.post(
        "/token",
        data={
            "grant_type": "refresh_token",
            "refresh_token": first_tokens["refresh_token"],
            "client_id": registration["client_id"],
        },
    )
    assert refreshed.status_code == 200, refreshed.text
    new_tokens = refreshed.json()
    assert new_tokens["access_token"] != first_tokens["access_token"]
    assert new_tokens["refresh_token"] != first_tokens["refresh_token"]

    resp = rpc_post(
        client,
        {"Authorization": f"Bearer {new_tokens['access_token']}"},
        {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}},
    )
    assert resp.status_code == 200, resp.text

    # The old refresh token was rotated out — reusing it must fail.
    reused = client.post(
        "/token",
        data={
            "grant_type": "refresh_token",
            "refresh_token": first_tokens["refresh_token"],
            "client_id": registration["client_id"],
        },
    )
    assert reused.status_code == 400
    assert reused.json()["error"] == "invalid_grant"


# ── PKCE / replay / expiry edge cases ────────────────────────────────────────

def test_pkce_mismatch_rejected(client: TestClient, standard_user: User):
    client.cookies.clear()
    registration = _register_client(client)
    _verifier, challenge = _pkce_pair()

    req = _authorize(client, registration["client_id"], challenge)
    _login(client, req, standard_user.email)
    location = _consent(client, req)
    code = parse_qs(urlparse(location).query)["code"][0]

    wrong_verifier, _ = _pkce_pair()
    resp = _exchange_code(client, registration["client_id"], code, wrong_verifier)
    assert resp.status_code == 400
    assert resp.json()["error"] == "invalid_grant"


def test_used_authorization_code_rejected_on_replay(client: TestClient, standard_user: User):
    client.cookies.clear()
    registration = _register_client(client)
    verifier, challenge = _pkce_pair()

    req = _authorize(client, registration["client_id"], challenge)
    _login(client, req, standard_user.email)
    location = _consent(client, req)
    code = parse_qs(urlparse(location).query)["code"][0]

    first = _exchange_code(client, registration["client_id"], code, verifier)
    assert first.status_code == 200, first.text

    replay = _exchange_code(client, registration["client_id"], code, verifier)
    assert replay.status_code == 400
    assert replay.json()["error"] == "invalid_grant"


def test_expired_authorization_code_rejected(client: TestClient, standard_user: User, db: Session):
    client.cookies.clear()
    registration = _register_client(client)
    verifier, challenge = _pkce_pair()

    code = secrets.token_urlsafe(32)
    db.add(
        McpAuthorizationCode(
            code=code,
            client_id=registration["client_id"],
            subject=str(standard_user.id),
            redirect_uri=REDIRECT_URI,
            redirect_uri_provided_explicitly=True,
            scopes=["mcp"],
            code_challenge=challenge,
            expires_at=datetime.now(timezone.utc) - timedelta(minutes=1),
            used=False,
        )
    )
    db.flush()

    resp = _exchange_code(client, registration["client_id"], code, verifier)
    assert resp.status_code == 400
    body = resp.json()
    assert body["error"] == "invalid_grant"
    assert "expired" in body["error_description"]


# ── Legacy static-token fallback still works ─────────────────────────────────

def test_legacy_jwt_still_works_against_mcp(client: TestClient, user_headers: dict):
    resp = rpc_post(client, user_headers, {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}})
    assert resp.status_code == 200
    assert resp.json()["result"]["tools"]


def test_dynamically_registered_client_persisted(client: TestClient, db: Session):
    client.cookies.clear()
    registration = _register_client(client)
    row = db.query(McpOAuthClient).filter(McpOAuthClient.client_id == registration["client_id"]).first()
    assert row is not None
    assert row.redirect_uris == [REDIRECT_URI]
    assert row.token_endpoint_auth_method == "none"
