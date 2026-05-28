"""custom question frequency: ask_frequency_type / ask_every_n / last_asked_local_date

Revision ID: 0012
Revises: 0011
Create Date: 2026-05-28

Перенумеровано с 0009 → 0012 после мержа upstream-веток (0009_question_policies,
0010_survey_frequency, 0011_last_survey_policies), чтобы Alembic-граф был
линейным. Самой миграции это не меняет — таблицы и колонки те же.

Добавляет в custom_questions параметры частоты показа:

- ask_frequency_type:
    'every_survey' — в каждом опросе (default; сохраняет прежнее поведение);
    'nth_survey'   — только в N-м опросе локального дня (N = ask_every_n, 1..13);
    'every_n_days' — раз в N дней (N = ask_every_n, 2..30), показывается только
                     в последнем опросе дня;
    'weekly'       — раз в 7 дней, в последнем опросе дня;
    'biweekly'     — раз в 14 дней, в последнем опросе дня.

- ask_every_n — целое:
    для 'nth_survey'   = 1..13 (номер опроса дня);
    для 'every_n_days' = 2..30 (число дней между показами);
    для прочих типов   = NULL.

- last_asked_local_date — дата (локальная) последнего показа вопроса в опросе.
    Обновляется в момент показа в _init_survey, используется для частот
    'every_n_days' / 'weekly' / 'biweekly'.

Все ALTER идемпотентны (IF NOT EXISTS / DROP IF EXISTS).
"""
from alembic import op


revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None


FREQUENCY_TYPES = ("every_survey", "nth_survey", "every_n_days", "weekly", "biweekly")


def upgrade() -> None:
    op.execute(
        "ALTER TABLE custom_questions "
        "ADD COLUMN IF NOT EXISTS ask_frequency_type VARCHAR(32) "
        "NOT NULL DEFAULT 'every_survey'"
    )
    op.execute(
        "ALTER TABLE custom_questions "
        "ADD COLUMN IF NOT EXISTS ask_every_n INTEGER"
    )
    op.execute(
        "ALTER TABLE custom_questions "
        "ADD COLUMN IF NOT EXISTS last_asked_local_date DATE"
    )

    op.execute(
        "ALTER TABLE custom_questions "
        "DROP CONSTRAINT IF EXISTS ck_custom_q_ask_frequency_type"
    )
    op.execute(
        "ALTER TABLE custom_questions "
        "DROP CONSTRAINT IF EXISTS ck_custom_q_ask_every_n"
    )

    types_sql = ", ".join(f"'{t}'" for t in FREQUENCY_TYPES)
    op.execute(
        f"ALTER TABLE custom_questions ADD CONSTRAINT ck_custom_q_ask_frequency_type "
        f"CHECK (ask_frequency_type IN ({types_sql}))"
    )
    # ask_every_n: для nth_survey 1..13, для every_n_days 2..30, иначе NULL.
    op.execute(
        "ALTER TABLE custom_questions ADD CONSTRAINT ck_custom_q_ask_every_n "
        "CHECK ("
        "  (ask_frequency_type = 'nth_survey' AND ask_every_n BETWEEN 1 AND 13)"
        "  OR (ask_frequency_type = 'every_n_days' AND ask_every_n BETWEEN 2 AND 30)"
        "  OR (ask_frequency_type IN ('every_survey', 'weekly', 'biweekly')"
        "      AND ask_every_n IS NULL)"
        ")"
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE custom_questions "
        "DROP CONSTRAINT IF EXISTS ck_custom_q_ask_every_n"
    )
    op.execute(
        "ALTER TABLE custom_questions "
        "DROP CONSTRAINT IF EXISTS ck_custom_q_ask_frequency_type"
    )
    op.execute(
        "ALTER TABLE custom_questions "
        "DROP COLUMN IF EXISTS last_asked_local_date"
    )
    op.execute("ALTER TABLE custom_questions DROP COLUMN IF EXISTS ask_every_n")
    op.execute(
        "ALTER TABLE custom_questions DROP COLUMN IF EXISTS ask_frequency_type"
    )
