"""productivity/concentration/hypomania/physical_activity -> last_or_after_noon,
obsessive_thoughts -> per_survey

Revision ID: 0015
Revises: 0014
Create Date: 2026-06-09

Часть «дневных итоговых» вопросов, переведённых в last_survey_of_day в
миграции 0011, на практике осмысленна уже с середины дня — нет смысла ждать
самого последнего опроса. Они переезжают в новую политику
'last_or_after_noon': задаются в последнем (last/single) опросе ИЛИ в любом
опросе, открытом не раньше 12:00 локального времени пользователя.

obsessive_thoughts — это вопрос про состояние «сейчас» (как тревога), а не
итог дня, поэтому возвращается в 'per_survey' (задаётся в каждом опросе).

Источник правды для логики — bot.constants_questions.QUESTION_POLICIES.
Рантайм читает политику оттуда; эта миграция лишь синхронизирует
question_catalog для отчётности и SQL-фильтрации. CHECK-ограничения на
ask_policy нет — новое значение в колонку String(64) пишется свободно.
"""
from alembic import op
import sqlalchemy as sa


revision = "0015"
down_revision = "0014"
branch_labels = None
depends_on = None


# Коды, переезжающие в last_or_after_noon.
NOON_CODES = [
    "productivity",
    "concentration",
    "hypomania",
    "physical_activity",
]


def upgrade() -> None:
    codes_sql = ", ".join(f"'{c}'" for c in NOON_CODES)
    op.execute(
        sa.text(
            "UPDATE question_catalog "
            "SET ask_policy = 'last_or_after_noon', "
            "    answer_target_date_policy = 'current_day', "
            "    updated_at = NOW() "
            f"WHERE code IN ({codes_sql})"
        )
    )
    op.execute(
        sa.text(
            "UPDATE question_catalog "
            "SET ask_policy = 'per_survey', "
            "    answer_target_date_policy = 'current_day', "
            "    updated_at = NOW() "
            "WHERE code = 'obsessive_thoughts'"
        )
    )


def downgrade() -> None:
    # Возврат к состоянию после 0011: все пять кодов были last_survey_of_day.
    codes = NOON_CODES + ["obsessive_thoughts"]
    codes_sql = ", ".join(f"'{c}'" for c in codes)
    op.execute(
        sa.text(
            "UPDATE question_catalog "
            "SET ask_policy = 'last_survey_of_day', "
            "    answer_target_date_policy = 'current_day', "
            "    updated_at = NOW() "
            f"WHERE code IN ({codes_sql})"
        )
    )
