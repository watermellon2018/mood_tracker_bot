from datetime import date, datetime, time

from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    Time,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship


from bot.database import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    telegram_user_id: Mapped[int] = mapped_column(
        BigInteger, unique=True, nullable=False, index=True
    )
    timezone: Mapped[str] = mapped_column(
        String(64), nullable=False, default="Europe/Moscow"
    )
    timezone_set: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    settings: Mapped["UserSettings"] = relationship(
        back_populates="user", uselist=False, cascade="all, delete-orphan"
    )
    entries: Mapped[list["SurveyEntry"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    pendings: Mapped[list["PendingSurvey"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )


class UserSettings(Base):
    __tablename__ = "user_settings"
    __table_args__ = (
        CheckConstraint(
            "frequency_per_day BETWEEN 1 AND 13", name="ck_frequency_range"
        ),
        CheckConstraint("start_time < end_time", name="ck_time_range"),
        CheckConstraint(
            "reminder_delay_minutes BETWEEN 1 AND 1440",
            name="ck_reminder_delay_range",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), unique=True, nullable=False
    )
    frequency_per_day: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    start_time: Mapped[time] = mapped_column(Time, nullable=False, default=time(7, 0))
    end_time: Mapped[time] = mapped_column(Time, nullable=False, default=time(23, 0))
    notifications_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True
    )
    reminder_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True
    )
    reminder_delay_minutes: Mapped[int] = mapped_column(
        Integer, nullable=False, default=30
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    user: Mapped[User] = relationship(back_populates="settings")


class SurveyEntry(Base):
    __tablename__ = "survey_entries"
    __table_args__ = (
        CheckConstraint("mood BETWEEN 0 AND 10", name="ck_mood_range"),
        CheckConstraint("anxiety BETWEEN 0 AND 5", name="ck_anxiety_range"),
        CheckConstraint("energy BETWEEN 0 AND 5", name="ck_energy_range"),
        # irritability/impulsivity: исторические колонки, теперь NULL-able.
        # Эти вопросы вынесены в опциональные (QUESTION_DEFINITIONS) и пишутся
        # в survey_answers. CHECK-диапазон не сохраняется, чтобы не мешал NULL.
        CheckConstraint(
            "sleep_type IN ('main', 'additional', 'none')", name="ck_sleep_type"
        ),
        Index("ix_survey_entries_local_date", "user_id", "local_date"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )
    local_date: Mapped[date] = mapped_column(Date, nullable=False)
    sleep_type: Mapped[str] = mapped_column(
        String(16), nullable=False, default="main"
    )
    medication_filled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True
    )

    mood: Mapped[int] = mapped_column(Integer, nullable=False)
    anxiety: Mapped[int] = mapped_column(Integer, nullable=False)
    energy: Mapped[int] = mapped_column(Integer, nullable=False)
    irritability: Mapped[int | None] = mapped_column(Integer, nullable=True)
    impulsivity: Mapped[int | None] = mapped_column(Integer, nullable=True)

    sleep_duration_category: Mapped[str] = mapped_column(String(16), nullable=False)
    sleep_quality: Mapped[str] = mapped_column(String(16), nullable=False)
    hard_to_fall_asleep: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    early_wakeup: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    frequent_wakeups: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    little_sleep_but_feel_good: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    long_sleep_not_restored: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )

    medication_taken: Mapped[str] = mapped_column(String(16), nullable=False)

    comment: Mapped[str | None] = mapped_column(Text, nullable=True)

    source: Mapped[str] = mapped_column(String(16), nullable=False)

    user: Mapped[User] = relationship(back_populates="entries")


class PendingSurvey(Base):
    __tablename__ = "pending_surveys"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    sent_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    reminder_sent_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="pending", index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    user: Mapped[User] = relationship(back_populates="pendings")


class QuestionCatalog(Base):
    """Каталог вопросов опроса. Базовые вопросы помечены is_required=True
    и не могут быть отключены пользователем."""

    __tablename__ = "question_catalog"
    __table_args__ = (
        CheckConstraint(
            "category IN ('base','depression','anxiety','hypomania','lifestyle','health')",
            name="ck_qc_category",
        ),
    )

    code: Mapped[str] = mapped_column(String(64), primary_key=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    category: Mapped[str] = mapped_column(String(64), nullable=False)
    is_required: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_default_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class UserQuestionSettings(Base):
    """Включенные пользователем опциональные вопросы. Базовые сюда не пишутся."""

    __tablename__ = "user_question_settings"

    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    question_code: Mapped[str] = mapped_column(
        ForeignKey("question_catalog.code", ondelete="CASCADE"),
        primary_key=True,
    )
    is_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class SurveyAnswer(Base):
    """EAV-таблица для ответов на опциональные вопросы. К каждой survey_entries
    может относиться 0..N ответов. Базовые вопросы (mood/anxiety/...) хранятся
    в колонках SurveyEntry — для них SurveyAnswer не создаётся."""

    __tablename__ = "survey_answers"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    entry_id: Mapped[int] = mapped_column(
        ForeignKey("survey_entries.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    question_code: Mapped[str] = mapped_column(
        ForeignKey("question_catalog.code", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    answer_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    answer_numeric: Mapped[Decimal | None] = mapped_column(Numeric, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class CustomQuestion(Base):
    """Пользовательские вопросы. Архивирование через is_active=False (soft delete).
    Уникальный частичный индекс по lower(trim(question_text)) WHERE is_active=true
    создан в миграции 0006."""

    __tablename__ = "custom_questions"
    __table_args__ = (
        CheckConstraint(
            "answer_type IN ('scale_0_5', 'boolean', 'text')",
            name="ck_custom_q_answer_type",
        ),
        CheckConstraint(
            "char_length(question_text) BETWEEN 1 AND 150",
            name="ck_custom_q_text_length",
        ),
        Index("ix_custom_questions_user_active", "user_id", "is_active"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    question_text: Mapped[str] = mapped_column(Text, nullable=False)
    answer_type: Mapped[str] = mapped_column(String(32), nullable=False)
    is_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class CustomQuestionAnswer(Base):
    """Ответ на пользовательский вопрос. Привязка к entry_id (как survey_answers).
    Уникальность (entry_id, custom_question_id) защищает от дублей при двойном
    нажатии кнопок."""

    __tablename__ = "custom_question_answers"
    __table_args__ = (
        CheckConstraint(
            "answer_type IN ('scale_0_5', 'boolean', 'text')",
            name="ck_custom_a_answer_type",
        ),
        Index(
            "uq_custom_answer_entry_question",
            "entry_id",
            "custom_question_id",
            unique=True,
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    entry_id: Mapped[int] = mapped_column(
        ForeignKey("survey_entries.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    custom_question_id: Mapped[int] = mapped_column(
        ForeignKey("custom_questions.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    answer_type: Mapped[str] = mapped_column(String(32), nullable=False)
    answer_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    answer_numeric: Mapped[Decimal | None] = mapped_column(Numeric, nullable=True)
    answer_bool: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
