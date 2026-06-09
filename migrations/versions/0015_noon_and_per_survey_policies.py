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
Рантайм читает политику оттуда; эта миграция синхронизирует question_catalog
для отчётности и SQL-фильтрации.

ВАЖНО: в 0009 на ask_policy заведён CHECK-констрейнт chk_question_ask_policy
(whitelist значений). Новое значение 'last_or_after_noon' в него не входит,
поэтому констрейнт ПЕРЕСОЗДАЁТСЯ с расширенным списком ДО UPDATE — иначе
UPDATE падает с CheckViolation. DROP IF EXISTS + ADD делает шаг идемпотентным.
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

# Допустимые значения ask_policy ПОСЛЕ этой миграции (старые 4 из 0009 +
# новый last_or_after_noon).
ASK_POLICY_VALUES_NEW = (
    "per_survey",
    "once_per_day",
    "first_survey_until_answered",
    "last_survey_of_day",
    "last_or_after_noon",
)

# Список из 0009 — для downgrade.
ASK_POLICY_VALUES_OLD = (
    "per_survey",
    "once_per_day",
    "first_survey_until_answered",
    "last_survey_of_day",
)


def _set_ask_policy_constraint(values: tuple[str, ...]) -> None:
    """Пересоздаёт chk_question_ask_policy с заданным whitelist."""
    op.execute(
        "ALTER TABLE question_catalog "
        "DROP CONSTRAINT IF EXISTS chk_question_ask_policy"
    )
    ask_list = ", ".join(f"'{v}'" for v in values)
    op.execute(
        "ALTER TABLE question_catalog ADD CONSTRAINT chk_question_ask_policy "
        f"CHECK (ask_policy IN ({ask_list}))"
    )


def upgrade() -> None:
    # 1. Сначала расширяем CHECK, чтобы UPDATE с новым значением прошёл.
    _set_ask_policy_constraint(ASK_POLICY_VALUES_NEW)

    # 2. productivity/concentration/hypomania/physical_activity -> last_or_after_noon.
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
    # 3. obsessive_thoughts -> per_survey.
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
    # 1. Возврат кодов к состоянию после 0011: все пять были last_survey_of_day.
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
    # 2. Сужаем CHECK обратно к списку из 0009 (теперь ни одна строка не
    # использует last_or_after_noon, так что констрейнт наложится без ошибки).
    _set_ask_policy_constraint(ASK_POLICY_VALUES_OLD)
