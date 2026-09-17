"""migrate legacy OpenAI-labelled OpenCode Go connections

Revision ID: b7d9e2a4c631
Revises: f4c2a8d19e73
Create Date: 2026-09-14
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "b7d9e2a4c631"
down_revision: Union[str, None] = "f4c2a8d19e73"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Before OpenCode Go had a dedicated vendor, these connections were stored
    # as generic OpenAI rows and identified only by the official endpoint. Do
    # this historical inference once at the database boundary; runtime code
    # must trust the explicit vendor/protocol fields.
    op.get_bind().execute(sa.text("""
        UPDATE llm_provider_connections
        SET provider_type = 'opencode_go',
            vendor = 'opencode_go',
            protocol = 'openai_chat_completions'
        WHERE provider_type = 'openai'
          AND RTRIM(base_url, '/') = 'https://opencode.ai/zen/go/v1'
          AND (vendor IS NULL OR vendor = 'openai')
          AND (
              protocol IS NULL
              OR protocol = 'openai_chat_completions'
          )
    """))


def downgrade() -> None:
    # The original intent cannot be distinguished safely after migration.
    pass
