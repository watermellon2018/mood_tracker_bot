"""initial schema

Revision ID: 0001
Revises:
Create Date: 2026-05-17

"""
from alembic import op
import sqlalchemy as sa


revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("telegram_user_id", sa.BigInteger(), nullable=False),
        sa.Column(
            "timezone",
            sa.String(length=64),
            nullable=False,
            server_default="Europe/Moscow",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint("telegram_user_id", name="uq_users_telegram_user_id"),
    )
    op.create_index("ix_users_telegram_user_id", "users", ["telegram_user_id"])

    op.create_table(
        "user_settings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column(
            "frequency_per_day", sa.Integer(), nullable=False, server_default="3"
        ),
        sa.Column(
            "start_time", sa.Time(), nullable=False, server_default="07:00:00"
        ),
        sa.Column("end_time", sa.Time(), nullable=False, server_default="23:00:00"),
        sa.Column(
            "notifications_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
        sa.Column(
            "reminder_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
        sa.Column(
            "reminder_delay_minutes",
            sa.Integer(),
            nullable=False,
            server_default="30",
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
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("user_id", name="uq_user_settings_user_id"),
        sa.CheckConstraint(
            "frequency_per_day BETWEEN 1 AND 13", name="ck_frequency_range"
        ),
        sa.CheckConstraint("start_time < end_time", name="ck_time_range"),
        sa.CheckConstraint(
            "reminder_delay_minutes BETWEEN 1 AND 1440",
            name="ck_reminder_delay_range",
        ),
    )

    op.create_table(
        "survey_entries",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("mood", sa.Integer(), nullable=False),
        sa.Column("anxiety", sa.Integer(), nullable=False),
        sa.Column("energy", sa.Integer(), nullable=False),
        sa.Column("irritability", sa.Integer(), nullable=False),
        sa.Column("impulsivity", sa.Integer(), nullable=False),
        sa.Column("sleep_duration_category", sa.String(length=16), nullable=False),
        sa.Column("sleep_quality", sa.String(length=16), nullable=False),
        sa.Column(
            "hard_to_fall_asleep",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column(
            "early_wakeup",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column(
            "frequent_wakeups",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column(
            "little_sleep_but_feel_good",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column(
            "long_sleep_not_restored",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column("medication_taken", sa.String(length=16), nullable=False),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column("source", sa.String(length=16), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.CheckConstraint("mood BETWEEN 0 AND 10", name="ck_mood_range"),
        sa.CheckConstraint("anxiety BETWEEN 0 AND 5", name="ck_anxiety_range"),
        sa.CheckConstraint("energy BETWEEN 0 AND 5", name="ck_energy_range"),
        sa.CheckConstraint(
            "irritability BETWEEN 0 AND 5", name="ck_irritability_range"
        ),
        sa.CheckConstraint(
            "impulsivity BETWEEN 0 AND 5", name="ck_impulsivity_range"
        ),
    )
    op.create_index(
        "ix_survey_entries_user_id", "survey_entries", ["user_id"]
    )
    op.create_index(
        "ix_survey_entries_created_at", "survey_entries", ["created_at"]
    )

    op.create_table(
        "pending_surveys",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "reminder_sent_at", sa.DateTime(timezone=True), nullable=True
        ),
        sa.Column(
            "status",
            sa.String(length=16),
            nullable=False,
            server_default="pending",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
    )
    op.create_index(
        "ix_pending_surveys_user_id", "pending_surveys", ["user_id"]
    )
    op.create_index(
        "ix_pending_surveys_status", "pending_surveys", ["status"]
    )


def downgrade() -> None:
    op.drop_index("ix_pending_surveys_status", table_name="pending_surveys")
    op.drop_index("ix_pending_surveys_user_id", table_name="pending_surveys")
    op.drop_table("pending_surveys")
    op.drop_index("ix_survey_entries_created_at", table_name="survey_entries")
    op.drop_index("ix_survey_entries_user_id", table_name="survey_entries")
    op.drop_table("survey_entries")
    op.drop_table("user_settings")
    op.drop_index("ix_users_telegram_user_id", table_name="users")
    op.drop_table("users")
