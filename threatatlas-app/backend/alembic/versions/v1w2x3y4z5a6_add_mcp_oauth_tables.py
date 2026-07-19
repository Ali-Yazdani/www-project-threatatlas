"""add mcp oauth tables

Revision ID: v1w2x3y4z5a6
Revises: t5u6v7w8x9y0
Create Date: 2026-07-17

"""
from alembic import op
import sqlalchemy as sa

revision = 'v1w2x3y4z5a6'
down_revision = 't5u6v7w8x9y0'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'mcp_oauth_clients',
        sa.Column('client_id', sa.String(length=64), primary_key=True),
        sa.Column('client_secret_encrypted', sa.String(length=1024), nullable=True),
        sa.Column('client_secret_expires_at', sa.Integer(), nullable=True),
        sa.Column('redirect_uris', sa.JSON(), nullable=False),
        sa.Column('token_endpoint_auth_method', sa.String(length=32), nullable=False, server_default='client_secret_post'),
        sa.Column('grant_types', sa.JSON(), nullable=False),
        sa.Column('response_types', sa.JSON(), nullable=False),
        sa.Column('scope', sa.String(length=256), nullable=True),
        sa.Column('client_name', sa.String(length=256), nullable=True),
        sa.Column('client_id_issued_at', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    )

    op.create_table(
        'mcp_pending_authorizations',
        sa.Column('id', sa.String(length=64), primary_key=True),
        sa.Column('client_id', sa.String(length=64), sa.ForeignKey('mcp_oauth_clients.client_id', ondelete='CASCADE'), nullable=False),
        sa.Column('redirect_uri', sa.String(length=2048), nullable=False),
        sa.Column('redirect_uri_provided_explicitly', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('scopes', sa.JSON(), nullable=False),
        sa.Column('code_challenge', sa.String(length=256), nullable=False),
        sa.Column('resource', sa.String(length=2048), nullable=True),
        sa.Column('state', sa.Text(), nullable=True),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    )

    op.create_table(
        'mcp_authorization_codes',
        sa.Column('code', sa.String(length=128), primary_key=True),
        sa.Column('client_id', sa.String(length=64), sa.ForeignKey('mcp_oauth_clients.client_id', ondelete='CASCADE'), nullable=False),
        sa.Column('subject', sa.String(length=64), nullable=False),
        sa.Column('redirect_uri', sa.String(length=2048), nullable=False),
        sa.Column('redirect_uri_provided_explicitly', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('scopes', sa.JSON(), nullable=False),
        sa.Column('code_challenge', sa.String(length=256), nullable=False),
        sa.Column('resource', sa.String(length=2048), nullable=True),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('used', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    )

    op.create_table(
        'mcp_access_tokens',
        sa.Column('token_hash', sa.String(length=128), primary_key=True),
        sa.Column('client_id', sa.String(length=64), sa.ForeignKey('mcp_oauth_clients.client_id', ondelete='CASCADE'), nullable=False),
        sa.Column('subject', sa.String(length=64), nullable=False),
        sa.Column('scopes', sa.JSON(), nullable=False),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    )

    op.create_table(
        'mcp_refresh_tokens',
        sa.Column('token_hash', sa.String(length=128), primary_key=True),
        sa.Column('client_id', sa.String(length=64), sa.ForeignKey('mcp_oauth_clients.client_id', ondelete='CASCADE'), nullable=False),
        sa.Column('subject', sa.String(length=64), nullable=False),
        sa.Column('scopes', sa.JSON(), nullable=False),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('revoked', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    )


def downgrade() -> None:
    op.drop_table('mcp_refresh_tokens')
    op.drop_table('mcp_access_tokens')
    op.drop_table('mcp_authorization_codes')
    op.drop_table('mcp_pending_authorizations')
    op.drop_table('mcp_oauth_clients')
