"""add users.is_admin (ADR-0031 D1 = A-1 · D8 · INF-35)

ที่เก็บสิทธิ์แอดมินเพียงที่เดียวของระบบ — ก่อนหน้านี้ `users` มี 4 คอลัมน์และ
**ไม่มีคอลัมน์สิทธิ์ใด ๆ** ส่วน JWT ที่เราออกเองมี 5 คีย์ก็ไม่มีที่เก็บสิทธิ์เช่นกัน
⇒ ระบบไม่มีแนวคิดเรื่องแอดมินเลย ทั้งที่ `BUSINESS_RULES.md` มอบอำนาจให้ "แอดมิน"
ไว้แล้ว 4 อย่างที่ย้อนกลับได้ยาก (BR-L6 · BR-P2 · BR-P6)

**backfill เกิดเองจาก `server_default` — ตั้งใจไม่เขียน `UPDATE` สักบรรทัด**
ทุกแถวเดิมได้ `false` = ไม่ใช่แอดมิน ซึ่งเป็นค่า fail-closed ที่ถูกต้องอยู่แล้ว
(ADR-0031 D8) · การตั้งแอดมินคนแรกเป็นงานของ `scripts/grant_admin.py` (D6)
ไม่ใช่ของ migration — migration ที่แจกสิทธิ์สูงสุดให้ใครคือสิ่งที่ไม่มีใครเห็น

🔴 **ต่างจาก `verified_at`/`published_at`/`sold_at` ตรงที่ใบนี้ *มี* `server_default`
และนั่นถูกต้อง** — คอลัมน์พวกนั้นเป็น "ลายเซ็นของคน" การใส่ default = ปลอมลายเซ็น
ย้อนหลัง ส่วนคอลัมน์นี้เป็น "สิทธิ์" ซึ่งค่าเริ่มต้นที่ปลอดภัยคือ *ปฏิเสธ* การปล่อยให้
เป็น NULL แล้วตีความทีหลังคือช่องที่ ADR-0031 D3 เขียนขึ้นมาปิดพอดี

`downgrade()` = `DROP COLUMN` — **ย้อนได้จริง** ต่างจาก `b1a7c3d9e024` ของ INF-32
ที่เป็น `ALTER TYPE ADD VALUE` (ย้อนไม่ได้) นี่คือเหตุผลที่ ADR-0031 D1 เลือก A-1
แทน A-2 (`users.role` เป็น PG enum)

⚠️ ปริมาณแถวตอนเขียน: dev = 1 แถว · **ยังไม่ได้นับฝั่ง SIT** (container `posternung-sit-db`
ดับอยู่) — ADR-0031 D8 สั่งให้นับก่อนรันจริงบน SIT

Revision ID: c9f4a2e07b18
Revises: e4d0f6021357
Create Date: 2026-08-25 14:20:11.482913
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c9f4a2e07b18"
down_revision: Union[str, Sequence[str], None] = "e4d0f6021357"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "users",
        sa.Column(
            "is_admin",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("users", "is_admin")
