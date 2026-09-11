"""add users and user_sessions

Identity for the hybrid tenancy model's shared instance. Creating the tables is
inert on its own: AUTH_ENABLED defaults false, so an existing single-operator
install behaves exactly as before (nginx Basic Auth plus the X-Api-Key operator
key) until the flag is turned on and a user is provisioned with
scripts/create_user.py.

Sessions are opaque rows rather than JWTs so they can actually be revoked —
this platform can reach a broker, so ending a session has to mean it. Only the
SHA-256 of each token is stored; a database dump must not hand over live
sessions.

No public registration route exists, so there is nothing to seed here.

Revision ID: 0030
Revises: 0029
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0030"
down_revision = "0029"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("email", sa.String(320), nullable=False),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("tier", sa.String(20), nullable=False, server_default="free"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
    )
    op.create_index("idx_users_email", "users", ["email"], unique=True)

    op.create_table(
        "user_sessions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("user_agent", sa.String(300), nullable=True),
        sa.Column("ip", sa.String(64), nullable=True),
    )
    op.create_index("idx_user_sessions_token_hash", "user_sessions", ["token_hash"], unique=True)
    op.create_index("idx_user_sessions_user", "user_sessions", ["user_id"])
    op.create_index("idx_user_sessions_expires", "user_sessions", ["expires_at"])


def downgrade() -> None:
    op.drop_index("idx_user_sessions_expires", table_name="user_sessions")
    op.drop_index("idx_user_sessions_user", table_name="user_sessions")
    op.drop_index("idx_user_sessions_token_hash", table_name="user_sessions")
    op.drop_table("user_sessions")
    op.drop_index("idx_users_email", table_name="users")
    op.drop_table("users")
