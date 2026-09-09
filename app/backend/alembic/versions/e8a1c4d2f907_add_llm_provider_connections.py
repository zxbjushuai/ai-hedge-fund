"""add managed LLM provider connections and model cache

Revision ID: e8a1c4d2f907
Revises: d5e78f9a1b2c
Create Date: 2026-09-08
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "e8a1c4d2f907"
down_revision: Union[str, None] = "d5e78f9a1b2c"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "llm_provider_connections",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("provider_type", sa.String(length=20), nullable=False),
        sa.Column("base_url", sa.String(length=500), nullable=False),
        sa.Column("api_key", sa.Text(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("last_tested_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_test_status", sa.String(length=20), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("last_synced_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
    )
    op.create_index("ix_llm_provider_connections_id", "llm_provider_connections", ["id"])
    op.create_index("ix_llm_provider_connections_name", "llm_provider_connections", ["name"])
    op.create_index("ix_llm_provider_connections_provider_type", "llm_provider_connections", ["provider_type"])
    op.create_table(
        "llm_provider_models",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("connection_id", sa.Integer(), nullable=False),
        sa.Column("model_id", sa.String(length=200), nullable=False),
        sa.Column("display_name", sa.String(length=200), nullable=False),
        sa.Column("source", sa.String(length=20), nullable=False, server_default="remote"),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("available", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["connection_id"], ["llm_provider_connections.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("connection_id", "model_id", name="uq_llm_provider_model"),
    )
    op.create_index("ix_llm_provider_models_id", "llm_provider_models", ["id"])
    op.create_index("ix_llm_provider_models_connection_id", "llm_provider_models", ["connection_id"])

    connection = op.get_bind()
    legacy = connection.execute(sa.text(
        "SELECT provider, key_value FROM api_keys "
        "WHERE is_active = 1 AND provider IN ('OPENAI_API_KEY', 'ANTHROPIC_API_KEY')"
    )).fetchall()
    mappings = {
        "OPENAI_API_KEY": ("OpenAI Default", "openai", "https://api.openai.com/v1"),
        "ANTHROPIC_API_KEY": ("Anthropic Default", "anthropic", "https://api.anthropic.com"),
    }
    for provider, key_value in legacy:
        name, provider_type, base_url = mappings[provider]
        connection.execute(sa.text(
            "INSERT INTO llm_provider_connections "
            "(name, provider_type, base_url, api_key, enabled) "
            "VALUES (:name, :provider_type, :base_url, :api_key, 1)"
        ), {"name": name, "provider_type": provider_type, "base_url": base_url, "api_key": key_value})


def downgrade() -> None:
    # The migration is intentionally additive; retain connection secrets and model cache.
    pass
