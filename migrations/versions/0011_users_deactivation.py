"""users soft delete: is_active, blocked_bot_at, deleted_at, deactivation_reason

Revision ID: 0011
Revises: 0010
Create Date: 2026-05-28

Soft delete для пользователей. Когда Telegram возвращает Forbidden (бот
заблокирован пользователем) или BadRequest 'chat not found' / 'user is
deactivated', помечаем пользователя как inactive вместо удаления, чтобы:
  - сохранить исторические записи опросов;
  - не ломать FK-связи (entries, pendings, custom_questions, periods и т.д.);
  - можно было реактивировать пользователя при следующем /start.

Поля:
  - is_active BOOLEAN NOT NULL DEFAULT TRUE — основной флаг;
  - deleted_at, blocked_bot_at TIMESTAMP NULL — когда деактивировали;
  - deactivation_reason VARCHAR(64) NULL — почему;
  - partial index по WHERE is_active=true — scheduler выбирает только активных.

Все ALTER идемпотентны (IF NOT EXISTS / DROP IF EXISTS).
"""
from alembic import op


revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


REASONS = ("bot_blocked", "user_deactivated", "chat_not_found", "manual_delete")


def upgrade() -> None:
    op.execute(
        "ALTER TABLE users "
        "ADD COLUMN IF NOT EXISTS is_active BOOLEAN NOT NULL DEFAULT TRUE"
    )
    op.execute(
        "ALTER TABLE users "
        "ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMP WITH TIME ZONE"
    )
    op.execute(
        "ALTER TABLE users "
        "ADD COLUMN IF NOT EXISTS blocked_bot_at TIMESTAMP WITH TIME ZONE"
    )
    op.execute(
        "ALTER TABLE users "
        "ADD COLUMN IF NOT EXISTS deactivation_reason VARCHAR(64)"
    )

    op.execute(
        "ALTER TABLE users "
        "DROP CONSTRAINT IF EXISTS chk_users_deactivation_reason"
    )
    reasons_sql = ", ".join(f"'{r}'" for r in REASONS)
    op.execute(
        f"ALTER TABLE users ADD CONSTRAINT chk_users_deactivation_reason "
        f"CHECK ("
        f"  deactivation_reason IS NULL "
        f"  OR deactivation_reason IN ({reasons_sql})"
        f")"
    )

    # Partial index для scheduler-выборок: 99% запросов — только активные,
    # b-tree по узкому подмножеству эффективнее полного индекса по boolean.
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_users_active "
        "ON users (id) WHERE is_active = true"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_users_active")
    op.execute(
        "ALTER TABLE users "
        "DROP CONSTRAINT IF EXISTS chk_users_deactivation_reason"
    )
    op.execute("ALTER TABLE users DROP COLUMN IF EXISTS deactivation_reason")
    op.execute("ALTER TABLE users DROP COLUMN IF EXISTS blocked_bot_at")
    op.execute("ALTER TABLE users DROP COLUMN IF EXISTS deleted_at")
    op.execute("ALTER TABLE users DROP COLUMN IF EXISTS is_active")
