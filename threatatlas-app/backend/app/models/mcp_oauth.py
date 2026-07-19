"""OAuth 2.1 authorization-server tables backing the browser-based MCP login
flow (RFC 6749/7636/7591). See app/mcp/oauth_provider.py for how these are
used to implement the mcp SDK's OAuthAuthorizationServerProvider Protocol.

Access/refresh tokens follow the existing ApiToken pattern: only a SHA-256
hash is stored, never the raw token. Client secrets are the exception — the
SDK's ClientAuthenticator compares client_secret by plaintext equality
(hmac.compare_digest), so it must be recoverable, not just hashed. That
reuses the same Fernet encrypt_secret()/decrypt_secret() helpers already used
for OIDCProviderConfig.client_secret_encrypted.
"""

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, JSON, String, Text
from sqlalchemy.sql import func

from app.database import Base


class McpOAuthClient(Base):
    """A dynamically-registered OAuth client (RFC 7591), e.g. Claude Code."""

    __tablename__ = "mcp_oauth_clients"

    client_id = Column(String(64), primary_key=True)
    # Nullable — public/PKCE-only clients (token_endpoint_auth_method="none")
    # are registered without a secret.
    client_secret_encrypted = Column(String(1024), nullable=True)
    client_secret_expires_at = Column(Integer, nullable=True)
    redirect_uris = Column(JSON, nullable=False)  # list[str]
    token_endpoint_auth_method = Column(String(32), nullable=False, default="client_secret_post")
    grant_types = Column(JSON, nullable=False)  # list[str]
    response_types = Column(JSON, nullable=False)  # list[str]
    scope = Column(String(256), nullable=True)
    client_name = Column(String(256), nullable=True)
    client_id_issued_at = Column(Integer, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class McpPendingAuthorization(Base):
    """Bridges the SDK's /authorize handler to our first-party login/consent
    page — created by ThreatAtlasOAuthProvider.authorize(), consumed by
    POST /oauth/consent. Short TTL, enforced on read."""

    __tablename__ = "mcp_pending_authorizations"

    id = Column(String(64), primary_key=True)
    client_id = Column(String(64), ForeignKey("mcp_oauth_clients.client_id", ondelete="CASCADE"), nullable=False)
    redirect_uri = Column(String(2048), nullable=False)
    redirect_uri_provided_explicitly = Column(Boolean, nullable=False, default=True)
    scopes = Column(JSON, nullable=False)  # list[str]
    code_challenge = Column(String(256), nullable=False)
    resource = Column(String(2048), nullable=True)
    state = Column(Text, nullable=True)
    expires_at = Column(DateTime(timezone=True), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class McpAuthorizationCode(Base):
    """A one-shot authorization code exchanged at /token for an access token."""

    __tablename__ = "mcp_authorization_codes"

    code = Column(String(128), primary_key=True)
    client_id = Column(String(64), ForeignKey("mcp_oauth_clients.client_id", ondelete="CASCADE"), nullable=False)
    subject = Column(String(64), nullable=False)  # User.id as str
    redirect_uri = Column(String(2048), nullable=False)
    redirect_uri_provided_explicitly = Column(Boolean, nullable=False, default=True)
    scopes = Column(JSON, nullable=False)  # list[str]
    code_challenge = Column(String(256), nullable=False)
    resource = Column(String(2048), nullable=True)
    expires_at = Column(DateTime(timezone=True), nullable=False)
    used = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class McpAccessToken(Base):
    """An issued MCP access token — looked up by re-hashing the incoming
    bearer token, never compared in plaintext."""

    __tablename__ = "mcp_access_tokens"

    token_hash = Column(String(128), primary_key=True)
    client_id = Column(String(64), ForeignKey("mcp_oauth_clients.client_id", ondelete="CASCADE"), nullable=False)
    subject = Column(String(64), nullable=False)
    scopes = Column(JSON, nullable=False)  # list[str]
    expires_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class McpRefreshToken(Base):
    """A refresh token, rotated on use like the SDK's default TokenHandler flow."""

    __tablename__ = "mcp_refresh_tokens"

    token_hash = Column(String(128), primary_key=True)
    client_id = Column(String(64), ForeignKey("mcp_oauth_clients.client_id", ondelete="CASCADE"), nullable=False)
    subject = Column(String(64), nullable=False)
    scopes = Column(JSON, nullable=False)  # list[str]
    expires_at = Column(DateTime(timezone=True), nullable=True)
    revoked = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
