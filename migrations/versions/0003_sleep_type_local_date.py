"""add sleep_type, local_date, medication_filled + partial unique index

Revision ID: 0003
Revises: 0002
Create Date: 2026-05-21

"""
from alembic import op
import sqlalchemy as sa


revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Поля
    op.add_column(
        "survey_entries",
        sa.Column(
            "sleep_type",
            sa.String(length=16),
            nullable=False,
            server_default="main",
        ),
    )
    op.add_column(
        "survey_entries",
        sa.Column(
            "medication_filled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
    )
    op.add_column(
        "survey_entries",
        # Локальная дата записи в TZ пользователя на момент сохранения.
        # nullable=True для бэкфилла; после заполнения делаем NOT NULL.
        sa.Column("local_date", sa.Date(), nullable=True),
    )

    # Бэкфилл local_date из created_at + users.timezone.
    op.execute(
        """
        UPDATE survey_entries se
        SET local_date = (se.created_at AT TIME ZONE u.timezone)::date
        FROM users u
        WHERE se.user_id = u.id AND se.local_date IS NULL
        """
    )

    op.alter_column("survey_entries", "local_date", nullable=False)

    # Бэкфилл: оставляем sleep_type='main' только за самой ранней записью в день
    # (по created_at), остальные в этот же день -> 'none', чтобы уникальный индекс
    # не упал на исторических данных. Аналогично для medication_filled.
    op.execute(
        """
        WITH ranked AS (
            SELECT id,
                   ROW_NUMBER() OVER (
                       PARTITION BY user_id, local_date
                       ORDER BY created_at ASC, id ASC
                   ) AS rn
            FROM survey_entries
        )
        UPDATE survey_entries se
        SET sleep_type = 'none'
        FROM ranked
        WHERE se.id = ranked.id AND ranked.rn > 1
        """
    )
    op.execute(
        """
        WITH ranked AS (
            SELECT id,
                   ROW_NUMBER() OVER (
                       PARTITION BY user_id, local_date
                       ORDER BY created_at ASC, id ASC
                   ) AS rn
            FROM survey_entries
        )
        UPDATE survey_entries se
        SET medication_filled = false
        FROM ranked
        WHERE se.id = ranked.id AND ranked.rn > 1
        """
    )

    op.create_check_constraint(
        "ck_sleep_type",
        "survey_entries",
        "sleep_type IN ('main', 'additional', 'none')",
    )
    op.create_index(
        "ix_survey_entries_local_date",
        "survey_entries",
        ["user_id", "local_date"],
    )
    # Частичный уникальный индекс: только один main-сон в день на пользователя.
    op.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS uq_survey_main_sleep_per_day
        ON survey_entries (user_id, local_date)
        WHERE sleep_type = 'main'
        """
    )
    # Частичный уникальный индекс: только одна запись с medication_filled=true в день.
    op.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS uq_survey_medication_per_day
        ON survey_entries (user_id, local_date)
        WHERE medication_filled = true
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_survey_medication_per_day")
    op.execute("DROP INDEX IF EXISTS uq_survey_main_sleep_per_day")
    op.drop_index("ix_survey_entries_local_date", table_name="survey_entries")
    op.drop_constraint("ck_sleep_type", "survey_entries", type_="check")
    op.drop_column("survey_entries", "local_date")
    op.drop_column("survey_entries", "medication_filled")
    op.drop_column("survey_entries", "sleep_type")
