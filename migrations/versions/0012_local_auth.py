"""Add local auth compatibility objects.

Revision ID: 0012
Revises:     0011
Create Date: 2026-08-16 00:00:00.000000 UTC
"""

from typing import Sequence, Union

from alembic import op

revision: str = "0012"
down_revision: Union[str, None] = "0011"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")
    op.execute("CREATE SCHEMA IF NOT EXISTS auth")
    op.execute("""
        CREATE TABLE IF NOT EXISTS auth.users (
            id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            email         TEXT UNIQUE,
            password_hash TEXT,
            created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at    TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)
    op.execute("ALTER TABLE auth.users ADD COLUMN IF NOT EXISTS email TEXT")
    op.execute("ALTER TABLE auth.users ADD COLUMN IF NOT EXISTS password_hash TEXT")
    op.execute("ALTER TABLE auth.users ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ NOT NULL DEFAULT now()")
    op.execute("ALTER TABLE auth.users ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT now()")
    op.execute("""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1
                FROM pg_constraint
                WHERE conname = 'uq_auth_users_email'
                  AND conrelid = 'auth.users'::regclass
            ) THEN
                ALTER TABLE auth.users ADD CONSTRAINT uq_auth_users_email UNIQUE (email);
            END IF;
        END
        $$;
    """)

    op.execute("""
        CREATE TABLE IF NOT EXISTS public.password_reset_tokens (
            id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id    UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
            token_hash TEXT NOT NULL UNIQUE,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            expires_at TIMESTAMPTZ NOT NULL,
            used_at    TIMESTAMPTZ
        )
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_password_reset_tokens_user_id
        ON public.password_reset_tokens (user_id)
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_password_reset_tokens_expires_at
        ON public.password_reset_tokens (expires_at)
    """)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS public.idx_password_reset_tokens_expires_at")
    op.execute("DROP INDEX IF EXISTS public.idx_password_reset_tokens_user_id")
    op.execute("DROP TABLE IF EXISTS public.password_reset_tokens")
    op.execute("ALTER TABLE auth.users DROP COLUMN IF EXISTS password_hash")
