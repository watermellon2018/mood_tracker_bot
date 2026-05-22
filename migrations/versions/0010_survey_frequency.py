"""survey frequency type / days / last_notification_date

Revision ID: 0010
Revises: 0009
Create Date: 2026-05-22

Добавляет настройку, как часто пользователю присылать плановый опрос:
- daily        — каждый день (текущее поведение);
- weekly       — раз в 7 дней;
- biweekly     — раз в 14 дней;
- custom_days  — каждые survey_frequency_days дней (2..30).

Поля добавляются в user_settings (там уже сидят остальные настройки расписания).
last_survey_notification_date хранит дату последнего успешно отправленного
планового опроса в локальной TZ пользователя — её сравниваем с local_today
при следующей попытке.

Все ALTER идемпотентны (IF NOT EXISTS / DROP IF EXISTS), чтобы повторное
применение не падало.
"""
from alembic import op


revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


FREQUENCY_TYPES = ("daily", "weekly", "biweekly", "custom_days")


def upgrade() -> None:
    op.execute(
        "ALTER TABLE user_settings "
        "ADD COLUMN IF NOT EXISTS survey_frequency_type VARCHAR(32) "
        "NOT NULL DEFAULT 'daily'"
    )
    op.execute(
        "ALTER TABLE user_settings "
        "ADD COLUMN IF NOT EXISTS survey_frequency_days INTEGER"
    )
    op.execute(
        "ALTER TABLE user_settings "
        "ADD COLUMN IF NOT EXISTS last_survey_notification_date DATE"
    )

    op.execute(
        "ALTER TABLE user_settings "
        "DROP CONSTRAINT IF EXISTS chk_survey_frequency_type"
    )
    op.execute(
        "ALTER TABLE user_settings "
        "DROP CONSTRAINT IF EXISTS chk_survey_frequency_days"
    )
    types_sql = ", ".join(f"'{t}'" for t in FREQUENCY_TYPES)
    op.execute(
        f"ALTER TABLE user_settings ADD CONSTRAINT chk_survey_frequency_type "
        f"CHECK (survey_frequency_type IN ({types_sql}))"
    )
    op.execute(
        "ALTER TABLE user_settings ADD CONSTRAINT chk_survey_frequency_days "
        "CHECK ("
        "  survey_frequency_days IS NULL "
        "  OR (survey_frequency_days BETWEEN 2 AND 30)"
        ")"
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE user_settings DROP CONSTRAINT IF EXISTS chk_survey_frequency_days"
    )
    op.execute(
        "ALTER TABLE user_settings DROP CONSTRAINT IF EXISTS chk_survey_frequency_type"
    )
    op.execute(
        "ALTER TABLE user_settings "
        "DROP COLUMN IF EXISTS last_survey_notification_date"
    )
    op.execute(
        "ALTER TABLE user_settings DROP COLUMN IF EXISTS survey_frequency_days"
    )
    op.execute(
        "ALTER TABLE user_settings DROP COLUMN IF EXISTS survey_frequency_type"
    )
