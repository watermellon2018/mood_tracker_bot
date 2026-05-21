"""user_statistics_blocks: какие блоки статистики показывать в режиме 'selected'

Revision ID: 0008
Revises: 0007
Create Date: 2026-05-21

Одна универсальная таблица: (user_id, block_code) -> is_enabled. Если строки
нет — считаем включённым только для блоков из STATISTICS_DEFAULTS (см.
bot/constants_statistics.py). Это упрощает онбординг: ничего предзаполнять
не нужно.
"""
from alembic import op
import sqlalchemy as sa


revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "user_statistics_blocks",
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("block_code", sa.String(length=64), primary_key=True),
        sa.Column(
            "is_enabled", sa.Boolean(), nullable=False, server_default=sa.true()
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_table("user_statistics_blocks")
