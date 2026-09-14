"""split managed LLM vendor and wire protocol

Revision ID: f4c2a8d19e73
Revises: e8a1c4d2f907
Create Date: 2026-09-14
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "f4c2a8d19e73"
down_revision: Union[str, None] = "e8a1c4d2f907"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    connection = op.get_bind()
    inspector = sa.inspect(connection)
    columns = {
        column["name"]
        for column in inspector.get_columns("llm_provider_connections")
    }
    if "vendor" not in columns:
        op.add_column(
            "llm_provider_connections",
            sa.Column("vendor", sa.String(length=32), nullable=True),
        )
    if "protocol" not in columns:
        op.add_column(
            "llm_provider_connections",
            sa.Column("protocol", sa.String(length=40), nullable=True),
        )

    # The application can add these columns before Alembic runs so old local
    # databases remain bootable. Make the formal migration safe in that case.
    inspector = sa.inspect(connection)
    indexes = {
        index["name"]
        for index in inspector.get_indexes("llm_provider_connections")
    }
    if "ix_llm_provider_connections_vendor" not in indexes:
        op.create_index(
            "ix_llm_provider_connections_vendor",
            "llm_provider_connections",
            ["vendor"],
        )
    if "ix_llm_provider_connections_protocol" not in indexes:
        op.create_index(
            "ix_llm_provider_connections_protocol",
            "llm_provider_connections",
            ["protocol"],
        )

    connection.execute(sa.text("""
        UPDATE llm_provider_connections
        SET vendor = CASE provider_type
            WHEN 'opencode_go_responses' THEN 'opencode_go'
            WHEN 'modelscope_anthropic' THEN 'modelscope'
            WHEN 'openai_responses' THEN 'openai'
            ELSE provider_type
        END,
        protocol = CASE provider_type
            WHEN 'anthropic' THEN 'anthropic_messages'
            WHEN 'modelscope_anthropic' THEN 'anthropic_messages'
            WHEN 'opencode_go_responses' THEN 'openai_responses'
            WHEN 'openai_responses' THEN 'openai_responses'
            ELSE 'openai_chat_completions'
        END
        WHERE vendor IS NULL OR protocol IS NULL
    """))


def downgrade() -> None:
    # Additive compatibility migration: retain protocol information.
    pass
