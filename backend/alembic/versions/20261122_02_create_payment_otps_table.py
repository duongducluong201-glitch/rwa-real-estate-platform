"""create payment_otps table for 2-step gmail otp payment verification

Revision ID: 20261122_02
Revises: 20261122_01
Create Date: 2026-11-22 15:48:00.000000
"""

from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "20261122_02"
down_revision: Union[str, None] = "20261122_01"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if "payment_otps" not in inspector.get_table_names():
        op.create_table(
            "payment_otps",
            sa.Column("id", sa.String(length=36), primary_key=True),
            sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("email", sa.String(length=255), nullable=False),
            sa.Column("otp_hash", sa.String(length=64), nullable=False),
            sa.Column("tx_type", sa.String(length=20), nullable=False),
            sa.Column("payload_json", sa.JSON(), nullable=False),
            sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("status", sa.String(length=20), nullable=False, server_default="pending"),
            sa.Column("expires_at", sa.DateTime(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        )
        op.create_index("ix_payment_otps_user_id", "payment_otps", ["user_id"], unique=False)
        op.create_index("ix_payment_otps_email", "payment_otps", ["email"], unique=False)
        op.create_index("ix_payment_otps_status", "payment_otps", ["status"], unique=False)


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if "payment_otps" in inspector.get_table_names():
        op.drop_index("ix_payment_otps_status", table_name="payment_otps")
        op.drop_index("ix_payment_otps_email", table_name="payment_otps")
        op.drop_index("ix_payment_otps_user_id", table_name="payment_otps")
        op.drop_table("payment_otps")
