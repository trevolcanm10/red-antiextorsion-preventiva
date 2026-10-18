"""Version user access tokens without replacing existing records.

Revision ID: 0002
Revises: 0001
"""
from alembic import op
import sqlalchemy as sa

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # PostgreSQL fills existing rows with 1 and retains the default for future inserts.
    op.add_column("users", sa.Column("auth_version", sa.Integer(), nullable=False,
                                     server_default=sa.text("1")))
    op.create_check_constraint(op.f("ck_users_auth_version_positive"), "users", "auth_version >= 1")


def downgrade() -> None:
    # Rolling back loses revocation history; never do so with the versioned API running.
    op.drop_constraint(op.f("ck_users_auth_version_positive"), "users", type_="check")
    op.drop_column("users", "auth_version")
