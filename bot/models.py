from datetime import datetime, time

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
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
        CheckConstraint(
            "irritability BETWEEN 0 AND 5", name="ck_irritability_range"
        ),
        CheckConstraint(
            "impulsivity BETWEEN 0 AND 5", name="ck_impulsivity_range"
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )

    mood: Mapped[int] = mapped_column(Integer, nullable=False)
    anxiety: Mapped[int] = mapped_column(Integer, nullable=False)
    energy: Mapped[int] = mapped_column(Integer, nullable=False)
    irritability: Mapped[int] = mapped_column(Integer, nullable=False)
    impulsivity: Mapped[int] = mapped_column(Integer, nullable=False)

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
