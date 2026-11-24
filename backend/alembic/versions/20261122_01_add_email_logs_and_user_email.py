"""add email column to users and create email_logs table

Revision ID: 20261122_01
Revises:
Create Date: 2026-11-22 14:55:00.000000
"""

from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "20261122_01"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    # 1. Đảm bảo bảng users có cột email (VARCHAR(255), nullable=True)
    if "users" in inspector.get_table_names():
        user_cols = {c["name"] for c in inspector.get_columns("users")}
        if "email" not in user_cols:
            op.add_column("users", sa.Column("email", sa.String(length=255), nullable=True))
            op.create_index("ix_users_email", "users", ["email"], unique=True)

    # 2. Tạo bảng email_logs phục vụ kiểm toán gửi biên lai thanh toán MockUSDC
    if "email_logs" not in inspector.get_table_names():
        op.create_table(
            "email_logs",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
            sa.Column("recipient_email", sa.String(length=255), nullable=False),
            sa.Column("tx_hash", sa.String(length=66), nullable=False),
            sa.Column("tx_type", sa.String(length=40), nullable=False, server_default="PRIMARY_BUY"),
            sa.Column("subject", sa.String(length=255), nullable=False),
            sa.Column("status", sa.String(length=20), nullable=False, server_default="sent"),
            sa.Column("error_message", sa.Text(), nullable=True),
            sa.Column("sent_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        )
        op.create_index("ix_email_logs_user_id", "email_logs", ["user_id"], unique=False)
        op.create_index("ix_email_logs_recipient_email", "email_logs", ["recipient_email"], unique=False)
        op.create_index("ix_email_logs_tx_hash", "email_logs", ["tx_hash"], unique=False)


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if "email_logs" in inspector.get_table_names():
        op.drop_index("ix_email_logs_tx_hash", table_name="email_logs")
        op.drop_index("ix_email_logs_recipient_email", table_name="email_logs")
        op.drop_index("ix_email_logs_user_id", table_name="email_logs")
        op.drop_table("email_logs")
