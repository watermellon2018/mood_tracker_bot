"""custom_questions and custom_question_answers

Revision ID: 0006
Revises: 0005
Create Date: 2026-05-21

Пользовательские вопросы: пользователь создаёт свои вопросы и они появляются
в ежедневном опросе. Ответы привязываются к entry_id (как system optional
в survey_answers), а не к (user_id, log_date) — это единообразно с уже
существующим EAV и решает проблему повторных опросов в день естественно.
"""
from alembic import op
import sqlalchemy as sa


revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # custom_questions
    op.create_table(
        "custom_questions",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("question_text", sa.Text(), nullable=False),
        sa.Column("answer_type", sa.String(length=32), nullable=False),
        sa.Column(
            "is_enabled", sa.Boolean(), nullable=False, server_default=sa.true()
        ),
        sa.Column(
            "is_active", sa.Boolean(), nullable=False, server_default=sa.true()
        ),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
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
            "answer_type IN ('scale_0_10', 'boolean', 'text')",
            name="ck_custom_q_answer_type",
        ),
        sa.CheckConstraint(
            "char_length(question_text) BETWEEN 1 AND 150",
            name="ck_custom_q_text_length",
        ),
    )
    op.create_index(
        "ix_custom_questions_user_active",
        "custom_questions",
        ["user_id", "is_active"],
    )
    # Уникальность активного вопроса по нормализованному тексту в рамках юзера.
    op.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS uq_custom_q_user_text_active
        ON custom_questions (user_id, lower(trim(question_text)))
        WHERE is_active = true
        """
    )

    # custom_question_answers
    op.create_table(
        "custom_question_answers",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column(
            "entry_id",
            sa.Integer(),
            sa.ForeignKey("survey_entries.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "custom_question_id",
            sa.BigInteger(),
            sa.ForeignKey("custom_questions.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("answer_type", sa.String(length=32), nullable=False),
        sa.Column("answer_text", sa.Text(), nullable=True),
        sa.Column("answer_numeric", sa.Numeric(), nullable=True),
        sa.Column("answer_bool", sa.Boolean(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "answer_type IN ('scale_0_10', 'boolean', 'text')",
            name="ck_custom_a_answer_type",
        ),
    )
    op.create_index(
        "ix_custom_answers_entry_id",
        "custom_question_answers",
        ["entry_id"],
    )
    op.create_index(
        "ix_custom_answers_question_id",
        "custom_question_answers",
        ["custom_question_id"],
    )
    # Защита от дублей при повторном нажатии кнопок: одна пара (entry, question)
    # = один ответ.
    op.create_index(
        "uq_custom_answer_entry_question",
        "custom_question_answers",
        ["entry_id", "custom_question_id"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index(
        "uq_custom_answer_entry_question", table_name="custom_question_answers"
    )
    op.drop_index(
        "ix_custom_answers_question_id", table_name="custom_question_answers"
    )
    op.drop_index(
        "ix_custom_answers_entry_id", table_name="custom_question_answers"
    )
    op.drop_table("custom_question_answers")
    op.execute("DROP INDEX IF EXISTS uq_custom_q_user_text_active")
    op.drop_index(
        "ix_custom_questions_user_active", table_name="custom_questions"
    )
    op.drop_table("custom_questions")
