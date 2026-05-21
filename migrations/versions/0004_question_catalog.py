"""question_catalog, user_question_settings, survey_answers (EAV)

Revision ID: 0004
Revises: 0003
Create Date: 2026-05-21

Этап 1 фичи "Настройка вопросов опроса":
- каталог вопросов (5 базовых + 27 опциональных);
- настройки пользователя (только для опциональных, базовые всегда включены);
- EAV-таблица ответов на опциональные вопросы.

Сами шаги опроса для опциональных вопросов добавятся в этапе 2 — этап 1
даёт только UI настроек и каркас.
"""
from alembic import op
import sqlalchemy as sa


revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


CATALOG_ROWS = [
    # base / required
    ("mood",              "Настроение",                          "Базовый показатель настроения по шкале 0-10",        "base",       True,  True,  10),
    ("anxiety",           "Тревога",                             "Уровень тревоги 0-5",                                  "base",       True,  True,  20),
    ("sleep",             "Сон",                                 "Длительность и качество сна",                           "base",       True,  True,  30),
    ("energy",            "Энергия",                             "Уровень энергии 0-5",                                  "base",       True,  True,  40),
    ("comment",           "Комментарий",                         "Свободный текст",                                       "base",       True,  True,  900),
    # depression
    ("anhedonia",         "Ангедония / удовольствие от дня",     "",  "depression", False, False, 110),
    ("self_esteem_guilt", "Самооценка и чувство вины",           "",  "depression", False, False, 120),
    ("appetite",          "Аппетит",                             "",  "depression", False, False, 130),
    ("concentration",     "Концентрация",                        "",  "depression", False, False, 140),
    ("productivity",      "Продуктивность",                      "",  "depression", False, False, 150),
    ("social_activity",   "Социальная активность",               "",  "depression", False, False, 160),
    # anxiety
    ("panic_attacks",      "Панические атаки",                   "",  "anxiety",    False, False, 210),
    ("obsessive_thoughts", "Навязчивые мысли",                   "",  "anxiety",    False, False, 220),
    ("avoidance",          "Избегание",                          "",  "anxiety",    False, False, 230),
    ("somatic_anxiety",    "Телесные симптомы тревоги",          "",  "anxiety",    False, False, 240),
    # hypomania
    ("hypomania",             "Гипомания / признаки подъема",    "",  "hypomania",  False, False, 310),
    ("thought_speech_speed",  "Скорость мыслей и речи",          "",  "hypomania",  False, False, 320),
    ("irritability",          "Раздражительность",               "",  "hypomania",  False, False, 330),
    ("impulsivity",           "Импульсивность",                  "",  "hypomania",  False, False, 340),
    ("libido",                "Либидо",                          "",  "hypomania",  False, False, 350),
    ("risky_behavior",        "Рискованное поведение",           "",  "hypomania",  False, False, 360),
    ("spending",              "Траты и импульсивные покупки",    "",  "hypomania",  False, False, 370),
    # lifestyle
    ("physical_activity",     "Физическая активность",           "",  "lifestyle",  False, False, 410),
    ("substances",            "Алкоголь / вещества",             "",  "lifestyle",  False, False, 420),
    ("caffeine",              "Кофеин",                          "",  "lifestyle",  False, False, 430),
    ("late_phone",            "Телефон перед сном",              "",  "lifestyle",  False, False, 440),
    ("stress_events",         "Стрессовые события",              "",  "lifestyle",  False, False, 450),
    ("aggression_conflicts",  "Агрессия / конфликты",            "",  "lifestyle",  False, False, 460),
    # health
    ("medications",         "Прием лекарств",                    "",  "health",     False, False, 510),
    ("therapy",             "Психотерапия",                      "",  "health",     False, False, 520),
    ("menstrual_cycle",     "Менструальный цикл",                "",  "health",     False, False, 530),
    ("suicidal_thoughts",   "Суицидальные мысли / самоповреждение", "Чувствительный блок. Требует подтверждения перед включением.",
                                                                       "health",     False, False, 540),
]


def upgrade() -> None:
    # 1. question_catalog
    op.create_table(
        "question_catalog",
        sa.Column("code", sa.String(length=64), primary_key=True),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("category", sa.String(length=64), nullable=False),
        sa.Column("is_required", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column(
            "is_default_enabled", sa.Boolean(), nullable=False, server_default=sa.false()
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
            "category IN ('base','depression','anxiety','hypomania','lifestyle','health')",
            name="ck_qc_category",
        ),
    )

    # 2. user_question_settings
    op.create_table(
        "user_question_settings",
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column(
            "question_code",
            sa.String(length=64),
            sa.ForeignKey("question_catalog.code", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "is_enabled", sa.Boolean(), nullable=False, server_default=sa.false()
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
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("user_id", "question_code"),
    )

    # 3. survey_answers (EAV для опциональных ответов)
    op.create_table(
        "survey_answers",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column(
            "entry_id",
            sa.Integer(),
            sa.ForeignKey("survey_entries.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "question_code",
            sa.String(length=64),
            sa.ForeignKey("question_catalog.code", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("answer_value", sa.Text(), nullable=True),
        sa.Column("answer_numeric", sa.Numeric(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_survey_answers_entry_id", "survey_answers", ["entry_id"]
    )
    op.create_index(
        "ix_survey_answers_question_code", "survey_answers", ["question_code"]
    )

    # 4. seed question_catalog
    qc = sa.table(
        "question_catalog",
        sa.column("code", sa.String),
        sa.column("title", sa.String),
        sa.column("description", sa.Text),
        sa.column("category", sa.String),
        sa.column("is_required", sa.Boolean),
        sa.column("is_default_enabled", sa.Boolean),
        sa.column("is_active", sa.Boolean),
        sa.column("sort_order", sa.Integer),
    )
    op.bulk_insert(
        qc,
        [
            {
                "code": code,
                "title": title,
                "description": desc,
                "category": cat,
                "is_required": req,
                "is_default_enabled": dflt,
                "is_active": True,
                "sort_order": order,
            }
            for (code, title, desc, cat, req, dflt, order) in CATALOG_ROWS
        ],
    )


def downgrade() -> None:
    op.drop_index("ix_survey_answers_question_code", table_name="survey_answers")
    op.drop_index("ix_survey_answers_entry_id", table_name="survey_answers")
    op.drop_table("survey_answers")
    op.drop_table("user_question_settings")
    op.drop_table("question_catalog")
