"""drop local auth: otp_codes table, users.hashed_password, otp_purpose enum

Revision ID: a7c4e91b2d38
Revises: f1b2a3c4d5e6
Create Date: 2026-07-24 00:00:00.000000

Sign-in ทุกวิธีย้ายไป Firebase หมดแล้ว (POST /auth/firebase) — backend ไม่ทำ local
password/OTP อีกต่อไป จึงถอด schema ที่รองรับมันออก:
  - DROP TABLE otp_codes (+ index)
  - ALTER TABLE users DROP COLUMN hashed_password
  - DROP TYPE otp_purpose

⚠️ upgrade นี้ทำลายข้อมูล (destructive) — password hash และ OTP ที่ค้างอยู่หายถาวร
downgrade สร้าง schema กลับได้ แต่ **กู้ข้อมูลเดิมไม่ได้**: hashed_password ที่คืนมา
เป็น NULL ทุกแถว (คอลัมน์เดิมเป็น nullable อยู่แล้วหลัง migration 3d29b01d15de
จึงคืนสภาพ schema ได้ตรง) · บัญชีที่เคยมีแต่รหัสผ่าน local จะ login ไม่ได้อีก
ต้องผูก Firebase identity แทน
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "a7c4e91b2d38"
down_revision: Union[str, Sequence[str], None] = "f1b2a3c4d5e6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# create_type=False → คุม CREATE/DROP TYPE เองตาม convention ของ repo
otp_purpose = postgresql.ENUM(
    "registration", "login", name="otp_purpose", create_type=False
)


def upgrade() -> None:
    """Upgrade schema — ถอด local password/OTP ออกทั้งหมด."""
    op.drop_index("ix_otp_codes_user_created", table_name="otp_codes")
    op.drop_table("otp_codes")

    op.drop_column("users", "hashed_password")

    otp_purpose.drop(op.get_bind(), checkfirst=True)


def downgrade() -> None:
    """Downgrade schema — คืนโครงสร้าง (ไม่ใช่ข้อมูล) ให้เหมือนก่อน upgrade."""
    otp_purpose.create(op.get_bind(), checkfirst=True)

    # nullable=True ตรงกับสภาพหลัง 3d29b01d15de (ก่อนถูก drop) — แถวเดิมได้ NULL
    op.add_column(
        "users",
        sa.Column("hashed_password", sa.String(length=255), nullable=True),
    )

    op.create_table(
        "otp_codes",
        sa.Column(
            "id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False
        ),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("code_hash", sa.String(length=255), nullable=False),
        sa.Column(
            "purpose", otp_purpose, server_default="registration", nullable=False
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "attempt_count", sa.SmallInteger(), server_default="0", nullable=False
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_otp_codes_user_created",
        "otp_codes",
        ["user_id", "created_at"],
        unique=False,
    )
