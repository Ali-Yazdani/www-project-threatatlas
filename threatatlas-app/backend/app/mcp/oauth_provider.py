"""ThreatAtlasOAuthProvider — implements the mcp SDK's
OAuthAuthorizationServerProvider Protocol, backing the browser-login OAuth
2.1 flow for the /mcp server. See app/routers/mcp_oauth_ui.py for the
first-party login/consent page this delegates to via `authorize()`.

Every method reads the per-request DB session via get_mcp_db_session()
(app/mcp/context.py) rather than opening its own SessionLocal() — these
Protocol methods are called directly by the SDK's Starlette route handlers
(/authorize, /token, /register, /revoke), which live on the same
mcp.streamable_http_app() that McpDbSessionMiddleware wraps, so a session
opened through the get_db dependency-override (test isolation, transactional
fixtures) is already available by the time any of these run.

load_access_token() also accepts the pre-existing v1 static bearer tokens
(ta_ API tokens and JWTs, via resolve_user_from_bearer()) so nothing that
already works today breaks when this OAuth flow ships.
"""

import hashlib
import secrets
from datetime import datetime, timedelta, timezone

from mcp.server.auth.provider import (
    AccessToken,
    AuthorizationCode,
    AuthorizationParams,
    OAuthAuthorizationServerProvider,
    RefreshToken,
    TokenError,
    construct_redirect_uri,
)
from mcp.shared.auth import OAuthClientInformationFull, OAuthToken
from pydantic import AnyUrl

from app.auth.dependencies import ExpiredApiToken, resolve_user_from_bearer
from app.auth.secrets import decrypt_secret, encrypt_secret
from app.mcp.context import get_mcp_db_session
from app.models.mcp_oauth import (
    McpAccessToken,
    McpAuthorizationCode,
    McpOAuthClient,
    McpPendingAuthorization,
    McpRefreshToken,
)

ACCESS_TOKEN_TTL = timedelta(hours=1)
REFRESH_TOKEN_TTL = timedelta(days=30)
AUTH_CODE_TTL = timedelta(minutes=10)
PENDING_AUTHZ_TTL = timedelta(minutes=10)

# client_id attributed to tokens resolved via the legacy static-token fallback
# in load_access_token() — these were never dynamically registered.
LEGACY_CLIENT_ID = "legacy-static-token"


def _hash_token(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _client_from_row(row: McpOAuthClient) -> OAuthClientInformationFull:
    return OAuthClientInformationFull(
        client_id=row.client_id,
        client_secret=decrypt_secret(row.client_secret_encrypted) if row.client_secret_encrypted else None,
        client_id_issued_at=row.client_id_issued_at,
        client_secret_expires_at=row.client_secret_expires_at,
        redirect_uris=row.redirect_uris,
        token_endpoint_auth_method=row.token_endpoint_auth_method,
        grant_types=row.grant_types,
        response_types=row.response_types,
        scope=row.scope,
        client_name=row.client_name,
    )


class ThreatAtlasOAuthProvider(OAuthAuthorizationServerProvider[AuthorizationCode, RefreshToken, AccessToken]):
    """Backs /authorize, /token, /register, /revoke with Postgres-persisted
    clients/codes/tokens, and hands the user off to our own login/consent
    page instead of a third-party IdP."""

    async def get_client(self, client_id: str) -> OAuthClientInformationFull | None:
        db = get_mcp_db_session()
        row = db.query(McpOAuthClient).filter(McpOAuthClient.client_id == client_id).first()
        return _client_from_row(row) if row else None

    async def register_client(self, client_info: OAuthClientInformationFull) -> None:
        db = get_mcp_db_session()
        row = McpOAuthClient(
            client_id=client_info.client_id,
            client_secret_encrypted=encrypt_secret(client_info.client_secret) if client_info.client_secret else None,
            client_secret_expires_at=client_info.client_secret_expires_at,
            redirect_uris=[str(u) for u in (client_info.redirect_uris or [])],
            token_endpoint_auth_method=client_info.token_endpoint_auth_method or "client_secret_post",
            grant_types=list(client_info.grant_types),
            response_types=list(client_info.response_types),
            scope=client_info.scope,
            client_name=client_info.client_name,
            client_id_issued_at=client_info.client_id_issued_at,
        )
        db.add(row)
        db.commit()

    async def authorize(self, client: OAuthClientInformationFull, params: AuthorizationParams) -> str:
        db = get_mcp_db_session()
        pending = McpPendingAuthorization(
            id=secrets.token_urlsafe(32),
            client_id=client.client_id,
            redirect_uri=str(params.redirect_uri),
            redirect_uri_provided_explicitly=params.redirect_uri_provided_explicitly,
            scopes=params.scopes or [],
            code_challenge=params.code_challenge,
            resource=params.resource,
            state=params.state,
            expires_at=datetime.now(timezone.utc) + PENDING_AUTHZ_TTL,
        )
        db.add(pending)
        db.commit()
        return construct_redirect_uri("/oauth/login", req=pending.id)

    async def load_authorization_code(
        self, client: OAuthClientInformationFull, authorization_code: str
    ) -> AuthorizationCode | None:
        db = get_mcp_db_session()
        row = db.query(McpAuthorizationCode).filter(McpAuthorizationCode.code == authorization_code).first()
        if row is None or row.used:
            return None
        return AuthorizationCode(
            code=row.code,
            scopes=row.scopes,
            expires_at=row.expires_at.timestamp(),
            client_id=row.client_id,
            code_challenge=row.code_challenge,
            redirect_uri=AnyUrl(row.redirect_uri),
            redirect_uri_provided_explicitly=row.redirect_uri_provided_explicitly,
            resource=row.resource,
            subject=row.subject,
        )

    async def exchange_authorization_code(
        self, client: OAuthClientInformationFull, authorization_code: AuthorizationCode
    ) -> OAuthToken:
        db = get_mcp_db_session()
        row = db.query(McpAuthorizationCode).filter(McpAuthorizationCode.code == authorization_code.code).first()
        if row is None or row.used:
            raise TokenError(error="invalid_grant", error_description="authorization code already used")
        row.used = True

        access_token = secrets.token_urlsafe(32)
        refresh_token = secrets.token_urlsafe(32)
        now = datetime.now(timezone.utc)

        db.add(
            McpAccessToken(
                token_hash=_hash_token(access_token),
                client_id=client.client_id,
                subject=authorization_code.subject,
                scopes=authorization_code.scopes,
                expires_at=now + ACCESS_TOKEN_TTL,
            )
        )
        db.add(
            McpRefreshToken(
                token_hash=_hash_token(refresh_token),
                client_id=client.client_id,
                subject=authorization_code.subject,
                scopes=authorization_code.scopes,
                expires_at=now + REFRESH_TOKEN_TTL,
            )
        )
        db.commit()

        return OAuthToken(
            access_token=access_token,
            token_type="Bearer",
            expires_in=int(ACCESS_TOKEN_TTL.total_seconds()),
            scope=" ".join(authorization_code.scopes),
            refresh_token=refresh_token,
        )

    async def load_refresh_token(
        self, client: OAuthClientInformationFull, refresh_token: str
    ) -> RefreshToken | None:
        db = get_mcp_db_session()
        row = db.query(McpRefreshToken).filter(McpRefreshToken.token_hash == _hash_token(refresh_token)).first()
        if row is None or row.revoked:
            return None
        return RefreshToken(
            token=refresh_token,
            client_id=row.client_id,
            scopes=row.scopes,
            expires_at=int(row.expires_at.timestamp()) if row.expires_at else None,
            subject=row.subject,
        )

    async def exchange_refresh_token(
        self,
        client: OAuthClientInformationFull,
        refresh_token: RefreshToken,
        scopes: list[str],
    ) -> OAuthToken:
        db = get_mcp_db_session()
        row = db.query(McpRefreshToken).filter(McpRefreshToken.token_hash == _hash_token(refresh_token.token)).first()
        if row is None or row.revoked:
            raise TokenError(error="invalid_grant", error_description="refresh token no longer valid")
        # Rotate: revoke the used refresh token, mint a fresh pair.
        row.revoked = True

        new_access_token = secrets.token_urlsafe(32)
        new_refresh_token = secrets.token_urlsafe(32)
        now = datetime.now(timezone.utc)

        db.add(
            McpAccessToken(
                token_hash=_hash_token(new_access_token),
                client_id=client.client_id,
                subject=refresh_token.subject,
                scopes=scopes,
                expires_at=now + ACCESS_TOKEN_TTL,
            )
        )
        db.add(
            McpRefreshToken(
                token_hash=_hash_token(new_refresh_token),
                client_id=client.client_id,
                subject=refresh_token.subject,
                scopes=scopes,
                expires_at=now + REFRESH_TOKEN_TTL,
            )
        )
        db.commit()

        return OAuthToken(
            access_token=new_access_token,
            token_type="Bearer",
            expires_in=int(ACCESS_TOKEN_TTL.total_seconds()),
            scope=" ".join(scopes),
            refresh_token=new_refresh_token,
        )

    async def load_access_token(self, token: str) -> AccessToken | None:
        db = get_mcp_db_session()
        row = db.query(McpAccessToken).filter(McpAccessToken.token_hash == _hash_token(token)).first()
        if row is not None:
            if row.expires_at and row.expires_at < datetime.now(timezone.utc):
                return None
            return AccessToken(
                token=token,
                client_id=row.client_id,
                scopes=row.scopes,
                expires_at=int(row.expires_at.timestamp()) if row.expires_at else None,
                subject=row.subject,
            )

        # Legacy fallback: ta_ API tokens and JWTs minted before this
        # OAuth flow existed keep working against /mcp.
        try:
            user = resolve_user_from_bearer(token, db)
        except ExpiredApiToken:
            return None
        if user is None:
            return None
        return AccessToken(
            token=token,
            client_id=LEGACY_CLIENT_ID,
            scopes=["mcp"],
            expires_at=None,
            subject=str(user.id),
        )

    async def revoke_token(self, token: AccessToken | RefreshToken) -> None:
        db = get_mcp_db_session()
        if isinstance(token, AccessToken):
            db.query(McpAccessToken).filter(McpAccessToken.token_hash == _hash_token(token.token)).delete()
        else:
            db.query(McpRefreshToken).filter(McpRefreshToken.token_hash == _hash_token(token.token)).update(
                {"revoked": True}
            )
        db.commit()
