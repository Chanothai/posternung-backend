"""index oauth_identities.provider_user_id for uid-only account linking

Revision ID: b8e3d1f74c25
Revises: a7c4e91b2d38
Create Date: 2026-07-27 00:00:00.000000

`firebase_login()` ค้น identity ด้วย Firebase uid อย่างเดียว (ข้าม provider) เพื่อจับคู่
บัญชีที่ user ทำ linkWithCredential ผูกหลาย sign-in method เข้า uid เดียวกัน

unique constraint เดิมเป็น (provider, provider_user_id) — Postgres ใช้ composite index
ได้เฉพาะเมื่อ query แตะคอลัมน์นำหน้า (provider) การค้นด้วย provider_user_id เดี่ยวๆ จึง
ต้องมี index ของตัวเอง ไม่งั้นกลายเป็น seq scan ทุก login ที่ยังไม่เคย link provider นั้น
"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b8e3d1f74c25"
down_revision: Union[str, Sequence[str], None] = "a7c4e91b2d38"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_index(
        "ix_oauth_identities_provider_user_id",
        "oauth_identities",
        ["provider_user_id"],
        unique=False,
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_oauth_identities_provider_user_id", table_name="oauth_identities")
