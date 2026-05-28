"""question policies: ask_policy / answer_target_date_policy + log_date

Revision ID: 0009
Revises: 0008
Create Date: 2026-05-21

Добавляет в каталог вопросов политики показа и привязки даты ответа:

- ask_policy:
    'per_survey'                  — спрашивать в каждом опросе (по умолчанию);
    'once_per_day'                — один раз в локальный день;
    'first_survey_until_answered' — спрашивать в первом опросе дня; пока не
                                    ответили — повторно в последующих опросах
                                    того же дня; на следующий день не
                                    переносится;
    'last_survey_of_day'          — только в последнем опросе дня.
- answer_target_date_policy:
    'current_day'  — ответ относится к текущему локальному дню (default);
    'previous_day' — ответ относится к вчерашнему дню (например, late_phone).

В survey_answers добавляется log_date — фактическая дата, к которой относится
ответ. Для большинства вопросов log_date = entry.local_date, но для late_phone
log_date = entry.local_date - 1.

Безопасность миграции:
- IF NOT EXISTS на колонки/индексы — повторное применение не падает.
- CHECK-констрейнты добавляются через try/except DROP, чтобы не дублироваться.
- Для seed используется UPDATE по коду (вопросы из 0004 уже в БД).
"""
from alembic import op
import sqlalchemy as sa


revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


ASK_POLICY_VALUES = (
    "per_survey",
    "once_per_day",
    "first_survey_until_answered",
    "last_survey_of_day",
)
TARGET_DATE_POLICY_VALUES = ("current_day", "previous_day")


# Политики по коду вопроса. Всё, чего нет в этой карте, остаётся
# per_survey + current_day (значения по умолчанию).
POLICY_SEED = {
    # once_per_day
    "sleep":            ("once_per_day", "current_day"),
    "medications":      ("once_per_day", "current_day"),
    "caffeine":         ("once_per_day", "current_day"),
    "substances":       ("once_per_day", "current_day"),
    "therapy":          ("once_per_day", "current_day"),
    "menstrual_cycle":  ("once_per_day", "current_day"),
    # first_survey_until_answered
    "late_phone":       ("first_survey_until_answered", "previous_day"),
    # last_survey_of_day
    "physical_activity": ("last_survey_of_day", "current_day"),
    "stress_events":     ("last_survey_of_day", "current_day"),
    "spending":          ("last_survey_of_day", "current_day"),
}


def upgrade() -> None:
    # 1. Добавляем колонки в question_catalog (idempotent).
    op.execute(
        "ALTER TABLE question_catalog "
        "ADD COLUMN IF NOT EXISTS ask_policy VARCHAR(64) "
        "NOT NULL DEFAULT 'per_survey'"
    )
    op.execute(
        "ALTER TABLE question_catalog "
        "ADD COLUMN IF NOT EXISTS answer_target_date_policy VARCHAR(64) "
        "NOT NULL DEFAULT 'current_day'"
    )

    # 2. CHECK-констрейнты (пересоздаём, чтобы повторное применение не упало).
    op.execute(
        "ALTER TABLE question_catalog "
        "DROP CONSTRAINT IF EXISTS chk_question_ask_policy"
    )
    op.execute(
        "ALTER TABLE question_catalog "
        "DROP CONSTRAINT IF EXISTS chk_answer_target_date_policy"
    )
    ask_list = ", ".join(f"'{v}'" for v in ASK_POLICY_VALUES)
    tgt_list = ", ".join(f"'{v}'" for v in TARGET_DATE_POLICY_VALUES)
    op.execute(
        f"ALTER TABLE question_catalog ADD CONSTRAINT chk_question_ask_policy "
        f"CHECK (ask_policy IN ({ask_list}))"
    )
    op.execute(
        f"ALTER TABLE question_catalog ADD CONSTRAINT chk_answer_target_date_policy "
        f"CHECK (answer_target_date_policy IN ({tgt_list}))"
    )

    # 3. Seed для вопросов с особыми политиками.
    for code, (ask, tgt) in POLICY_SEED.items():
        op.execute(
            sa.text(
                "UPDATE question_catalog SET ask_policy = :ask, "
                "answer_target_date_policy = :tgt WHERE code = :code"
            ).bindparams(ask=ask, tgt=tgt, code=code)
        )

    # 4. log_date в survey_answers. Для существующих строк инициализируем
    # значением даты соответствующей записи (entry.local_date).
    op.execute(
        "ALTER TABLE survey_answers ADD COLUMN IF NOT EXISTS log_date DATE"
    )
    op.execute(
        "UPDATE survey_answers a SET log_date = e.local_date "
        "FROM survey_entries e WHERE a.entry_id = e.id AND a.log_date IS NULL"
    )
    # После бэкфилла — делаем NOT NULL.
    op.execute("ALTER TABLE survey_answers ALTER COLUMN log_date SET NOT NULL")
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_survey_answers_qcode_logdate "
        "ON survey_answers (question_code, log_date)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_survey_answers_qcode_logdate")
    op.execute("ALTER TABLE survey_answers DROP COLUMN IF EXISTS log_date")
    op.execute(
        "ALTER TABLE question_catalog "
        "DROP CONSTRAINT IF EXISTS chk_answer_target_date_policy"
    )
    op.execute(
        "ALTER TABLE question_catalog "
        "DROP CONSTRAINT IF EXISTS chk_question_ask_policy"
    )
    op.execute(
        "ALTER TABLE question_catalog "
        "DROP COLUMN IF EXISTS answer_target_date_policy"
    )
    op.execute(
        "ALTER TABLE question_catalog DROP COLUMN IF EXISTS ask_policy"
    )
