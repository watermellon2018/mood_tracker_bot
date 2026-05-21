"""rename custom answer_type scale_0_10 -> scale_0_5

Revision ID: 0007
Revises: 0006
Create Date: 2026-05-21

Шкала ответа для custom-вопросов меняется с 0..10 на 0..5. Существующие записи
(если есть) переводим на новый код. CHECK-констрейнты пересоздаются с
обновлённым списком допустимых значений.
"""
from alembic import op


revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. Сначала разрешаем оба значения, чтобы UPDATE не упал на CHECK.
    op.execute(
        "ALTER TABLE custom_questions DROP CONSTRAINT IF EXISTS ck_custom_q_answer_type"
    )
    op.execute(
        "ALTER TABLE custom_question_answers DROP CONSTRAINT IF EXISTS ck_custom_a_answer_type"
    )

    # 2. Переименовываем существующие значения.
    op.execute(
        "UPDATE custom_questions SET answer_type = 'scale_0_5' "
        "WHERE answer_type = 'scale_0_10'"
    )
    op.execute(
        "UPDATE custom_question_answers SET answer_type = 'scale_0_5' "
        "WHERE answer_type = 'scale_0_10'"
    )

    # 3. На custom_question_answers числовые значения уже в диапазоне 0..10.
    # После сужения шкалы старые ответы могут быть >5 — обрезаем до 5,
    # чтобы будущий рассказ "среднее по шкале 0..5" не давал 7. Альтернатива —
    # удалять старые записи; обрезка консервативнее.
    op.execute(
        "UPDATE custom_question_answers SET answer_numeric = 5 "
        "WHERE answer_type = 'scale_0_5' AND answer_numeric > 5"
    )

    # 4. Восстанавливаем CHECK с новым списком.
    op.create_check_constraint(
        "ck_custom_q_answer_type",
        "custom_questions",
        "answer_type IN ('scale_0_5', 'boolean', 'text')",
    )
    op.create_check_constraint(
        "ck_custom_a_answer_type",
        "custom_question_answers",
        "answer_type IN ('scale_0_5', 'boolean', 'text')",
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE custom_questions DROP CONSTRAINT IF EXISTS ck_custom_q_answer_type"
    )
    op.execute(
        "ALTER TABLE custom_question_answers DROP CONSTRAINT IF EXISTS ck_custom_a_answer_type"
    )
    op.execute(
        "UPDATE custom_questions SET answer_type = 'scale_0_10' "
        "WHERE answer_type = 'scale_0_5'"
    )
    op.execute(
        "UPDATE custom_question_answers SET answer_type = 'scale_0_10' "
        "WHERE answer_type = 'scale_0_5'"
    )
    op.create_check_constraint(
        "ck_custom_q_answer_type",
        "custom_questions",
        "answer_type IN ('scale_0_10', 'boolean', 'text')",
    )
    op.create_check_constraint(
        "ck_custom_a_answer_type",
        "custom_question_answers",
        "answer_type IN ('scale_0_10', 'boolean', 'text')",
    )
