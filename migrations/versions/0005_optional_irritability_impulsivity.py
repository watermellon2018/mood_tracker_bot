"""make irritability/impulsivity nullable, drop range CHECKs

Revision ID: 0005
Revises: 0004
Create Date: 2026-05-21

irritability и impulsivity переезжают из обязательных в опциональные вопросы
(они хранятся в QUESTION_DEFINITIONS и user_question_settings). Старые
исторические записи остаются — колонки сохраняются для совместимости,
но теперь могут быть NULL.

CHECK-констрейнты диапазонов 0..5 нельзя оставить с NULL-значениями
(они сработают на NULL? Нет, IS NULL → UNKNOWN, что для CHECK эквивалент TRUE).
Тем не менее уберём их, чтобы будущие апдейты не натыкались.
"""
from alembic import op
import sqlalchemy as sa


revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column("survey_entries", "irritability", nullable=True)
    op.alter_column("survey_entries", "impulsivity", nullable=True)
    op.drop_constraint("ck_irritability_range", "survey_entries", type_="check")
    op.drop_constraint("ck_impulsivity_range", "survey_entries", type_="check")


def downgrade() -> None:
    # Перед NOT NULL нужно заполнить дефолтом 0 (значит, прежние значения 0..5
    # сохраняются, NULL → 0). Это разрушительно для пользовательских данных,
    # но это downgrade, ожидаемо.
    op.execute("UPDATE survey_entries SET irritability = 0 WHERE irritability IS NULL")
    op.execute("UPDATE survey_entries SET impulsivity = 0 WHERE impulsivity IS NULL")
    op.alter_column("survey_entries", "irritability", nullable=False)
    op.alter_column("survey_entries", "impulsivity", nullable=False)
    op.create_check_constraint(
        "ck_irritability_range",
        "survey_entries",
        "irritability BETWEEN 0 AND 5",
    )
    op.create_check_constraint(
        "ck_impulsivity_range",
        "survey_entries",
        "impulsivity BETWEEN 0 AND 5",
    )
