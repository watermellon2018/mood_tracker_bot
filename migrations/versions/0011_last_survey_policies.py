"""перевод "дневных итоговых" вопросов в last_survey_of_day

Revision ID: 0011
Revises: 0010
Create Date: 2026-05-22

Большая группа опциональных вопросов сформулирована как итог дня
("сегодня", "за день", "прошёл день"). Раньше часть из них имела
ask_policy='per_survey' (задавались в каждом опросе), часть —
'once_per_day' (задавались в любом опросе, но один раз). Теперь все они
переезжают в 'last_survey_of_day' с target='current_day': задаются только
в last/single слоте, не переносятся между днями.

Источник правды для логики — bot.constants_questions.QUESTION_POLICIES.
Эта миграция синхронизирует question_catalog с конфигом для отчётности и
сценариев фильтрации через SQL.

Старые ответы в survey_answers (включая legacy caffeine ['Мало','Умеренно',...])
не трогаем — answer_numeric (индекс 0..4) совместим со схемой новых вариантов,
аналитика по индексу не сломается.
"""
from alembic import op
import sqlalchemy as sa


revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


LAST_SURVEY_CODES = [
    "anhedonia",
    "concentration",
    "productivity",
    "social_activity",
    "obsessive_thoughts",
    "hypomania",
    "impulsivity",
    "risky_behavior",
    "spending",
    "physical_activity",
    "substances",
    "caffeine",
    "aggression_conflicts",
    "therapy",
    "menstrual_cycle",
    "suicidal_thoughts",
]


def upgrade() -> None:
    # Один UPDATE на все коды — IN (...).
    codes_sql = ", ".join(f"'{c}'" for c in LAST_SURVEY_CODES)
    op.execute(
        sa.text(
            "UPDATE question_catalog "
            "SET ask_policy = 'last_survey_of_day', "
            "    answer_target_date_policy = 'current_day', "
            "    updated_at = NOW() "
            f"WHERE code IN ({codes_sql})"
        )
    )


def downgrade() -> None:
    # Возврат к политикам, действовавшим до 0011 (см. 0009 POLICY_SEED):
    # caffeine/substances/therapy/menstrual_cycle были once_per_day,
    # spending/physical_activity оставались last_survey_of_day,
    # остальные — per_survey (default).
    op.execute(
        sa.text(
            "UPDATE question_catalog "
            "SET ask_policy = 'once_per_day', "
            "    answer_target_date_policy = 'current_day', "
            "    updated_at = NOW() "
            "WHERE code IN ('caffeine','substances','therapy','menstrual_cycle')"
        )
    )
    op.execute(
        sa.text(
            "UPDATE question_catalog "
            "SET ask_policy = 'per_survey', "
            "    answer_target_date_policy = 'current_day', "
            "    updated_at = NOW() "
            "WHERE code IN ("
            "  'anhedonia','concentration','productivity','social_activity',"
            "  'obsessive_thoughts','hypomania','impulsivity','risky_behavior',"
            "  'aggression_conflicts','suicidal_thoughts'"
            ")"
        )
    )
    # spending и physical_activity уже были last_survey_of_day — не трогаем.
