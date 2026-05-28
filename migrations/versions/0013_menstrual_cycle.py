"""menstrual cycle: settings, periods, prediction state

Revision ID: 0013
Revises: 0012
Create Date: 2026-05-28

Перенумеровано с 0010 → 0013 после мержа upstream-веток, чтобы Alembic-граф
был линейным.

Менструальный цикл превращается из ежедневного вопроса в отдельную функцию:
- menstrual_cycle_settings — feature flag и параметры уведомлений на user_id;
- menstrual_periods — даты начала/окончания циклов;
- menstrual_cycle_prediction_state — анти-спам для прогнозных уведомлений.

Старый вопрос menstrual_cycle в question_catalog остаётся (is_active=true),
чтобы старые ответы в survey_answers продолжали валидироваться по FK, но из
ежедневного опроса он явно исключён в bot/handlers/survey.py.
Старые записи user_question_settings не трогаем — их игнорирует survey flow.

Все ALTER идемпотентны.
"""
from alembic import op
import sqlalchemy as sa


revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. menstrual_cycle_settings
    op.create_table(
        "menstrual_cycle_settings",
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "is_enabled", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
        sa.Column(
            "notify_before_predicted_start",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
        sa.Column(
            "notify_on_predicted_start",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
        sa.Column(
            "ask_period_end", sa.Boolean(), nullable=False, server_default=sa.true()
        ),
        sa.Column(
            "notify_days_before",
            sa.Integer(),
            nullable=False,
            server_default="2",
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
        sa.CheckConstraint(
            "notify_days_before BETWEEN 0 AND 7",
            name="ck_mcs_notify_days_before",
        ),
    )

    # 2. menstrual_periods
    op.create_table(
        "menstrual_periods",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("period_start_date", sa.Date(), nullable=False),
        sa.Column("period_end_date", sa.Date(), nullable=True),
        sa.Column(
            "source", sa.String(length=32), nullable=False, server_default="manual"
        ),
        sa.Column(
            "status", sa.String(length=32), nullable=False, server_default="confirmed"
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
        sa.CheckConstraint(
            "period_end_date IS NULL OR period_end_date >= period_start_date",
            name="ck_mp_dates",
        ),
        sa.CheckConstraint(
            "source IN ('manual', 'prediction_confirmed', 'imported')",
            name="ck_mp_source",
        ),
        sa.CheckConstraint(
            "status IN ('confirmed', 'open', 'archived')",
            name="ck_mp_status",
        ),
    )
    op.create_index(
        "ix_menstrual_periods_user_start",
        "menstrual_periods",
        ["user_id", "period_start_date"],
    )
    # Открытые периоды (период не закрыт). Помогает быстро найти "текущий".
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_menstrual_periods_user_open "
        "ON menstrual_periods (user_id) WHERE period_end_date IS NULL"
    )
    # Уникальность активного старта в один день.
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_menstrual_period_start "
        "ON menstrual_periods (user_id, period_start_date) "
        "WHERE status != 'archived'"
    )

    # 3. menstrual_cycle_prediction_state
    op.create_table(
        "menstrual_cycle_prediction_state",
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("predicted_next_start_date", sa.Date(), nullable=True),
        sa.Column("predicted_period_end_date", sa.Date(), nullable=True),
        sa.Column(
            "last_before_start_notification_date", sa.Date(), nullable=True
        ),
        sa.Column("last_start_check_date", sa.Date(), nullable=True),
        sa.Column("last_end_check_date", sa.Date(), nullable=True),
        sa.Column(
            "start_confirmation_active",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column(
            "end_confirmation_active",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
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
    op.drop_table("menstrual_cycle_prediction_state")
    op.execute("DROP INDEX IF EXISTS uq_menstrual_period_start")
    op.execute("DROP INDEX IF EXISTS ix_menstrual_periods_user_open")
    op.drop_index(
        "ix_menstrual_periods_user_start", table_name="menstrual_periods"
    )
    op.drop_table("menstrual_periods")
    op.drop_table("menstrual_cycle_settings")
