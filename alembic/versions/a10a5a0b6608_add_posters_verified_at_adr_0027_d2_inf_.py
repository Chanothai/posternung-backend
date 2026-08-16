"""add posters.verified_at (ADR-0027 D2 · INF-28)

ลายเซ็นของคนว่า "หยิบใบจริงขึ้นมาตรวจครบทุกมิติแล้ว" — `NULL` = ยังไม่เคยมีใครตรวจ
**ไม่ใช่** ตรวจแล้วไม่ผ่าน · ไม่มี `server_default` โดยตั้งใจ แนวเดียวกับ `published_at`
(ADR-0013 D1) และ `sold_at` (ADR-0025 D1): แถวเดิมทุกแถวต้องเป็น `NULL` เพราะยังไม่มี
ใครเซ็นจริง การใส่ default = ปลอมลายเซ็นให้ 117 แถวย้อนหลัง

🔴 **ไม่มี CHECK ในไฟล์นี้ และนั่นคือมติ ไม่ใช่การลืม** (ADR-0027 **D4**)
`ck_posters_published_requires_verified` (`published_at IS NULL OR verified_at IS NOT NULL`)
ลงพร้อมคอลัมน์ไม่ได้ — วันนี้มี **116 แถวที่ละเมิด** (publish อยู่แล้วแต่ยังไม่มีใครเซ็น)
⇒ `ADD CONSTRAINT` จะล้มที่การ validate แถวเดิม · และ `NOT VALID` **ก็ไม่ใช่ทางออก**
เพราะ PostgreSQL ยังบังคับ constraint ที่ `NOT VALID` กับทุก **UPDATE** ⇒ 116 แถวนั้นจะ
แก้อะไรไม่ได้เลยสักคอลัมน์ **รวมถึงเส้นที่ 5 ซึ่งเป็นเครื่องมือเดียวที่พาแถวพวกนั้นกลับมา
ถูกต้องได้** — ด่านที่ล็อกเครื่องมือซ่อมไว้ข้างนอกคือด่านที่ผิด

CHECK จะลงใน migration แยกพร้อม **ขั้นถอนแถวค้าง** ซึ่งเป็นคำสั่งแยกของเจ้าของ
จนกว่าจะถึงตอนนั้น invariant บังคับแค่ที่ `poster_service.is_publishable()` (ฝั่ง Python)
**ห้ามอ้างว่าครอบระดับ DB แล้ว**

Revision ID: a10a5a0b6608
Revises: a1f4d7b93e28
Create Date: 2026-08-16 16:11:46.255312
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a10a5a0b6608"
down_revision: Union[str, Sequence[str], None] = "a1f4d7b93e28"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "posters",
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("posters", "verified_at")
