"""posters.sold_at + CHECK ว่า sold ต้องมี sold_at เสมอ (ADR-0025 · INF-24)

Revision ID: 760b692b6062
Revises: b4e9c2f81a37
Create Date: 2026-08-15 19:45:11.823259

แกนที่สาม (`status` = วงจรสต็อก · `published_at` = ความพร้อมขาย ·
**`sold_at` = เมื่อไหร่ที่ของขายออกไปจริง**) — ต่างจาก `published_at` ตรงที่
`sold_at` ออก public API (ADR-0013 §Amendment 2026-08-13 A-D3) เพราะเป็นข้อเท็จจริง
ของสินค้า (คู่กับ `price`) ไม่ใช่ธง ops ของ workflow

**ไม่มี `server_default` และไม่ backfill** — ใบที่ขายไปก่อนหน้านี้ไม่มีใครรู้เวลาจริง
การเดาคือการประดิษฐ์ประวัติ (ADR-0025 AC-8) · `sold` = 0 แถวทั้ง dev และ sit
(วัดจริง 2026-08-15 ที่ GATE 1 ของ INF-24) ⇒ นิพจน์ CHECK เป็น TRUE ทุกแถวโดยไม่ต้อง
ดูค่า `status` เลย ⇒ `ADD CONSTRAINT` validate ผ่านทันที ไม่ต้องใช้ `NOT VALID`
(เช็คด้วย `SELECT count(*) FROM posters WHERE status = 'sold' AND sold_at IS NULL;`
→ ต้องได้ 0 ก่อนรัน migration นี้)

ลำดับใน `upgrade()` สำคัญ: `add_column` ต้องมาก่อน `create_check_constraint`
เพราะนิพจน์อ้างคอลัมน์ที่ยังไม่มี · `downgrade()` จึงต้องกลับด้าน

ไม่แตะ enum `poster_status` เลย และไม่แตะ `published_at`/`reservations`
(ADR-0025 D2 · D3 · A-D1)
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "760b692b6062"
down_revision: Union[str, Sequence[str], None] = "b4e9c2f81a37"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

CONSTRAINT_NAME = "ck_posters_sold_requires_sold_at"
# ต้องตรงกับ `Poster.__table_args__` เป๊ะ — ถ้าประกาศแต่ในไฟล์นี้
# `Base.metadata.create_all` จะไม่มี constraint และเทสจะเขียวทั้งที่ของจริงไม่มีกฎ
CONSTRAINT_EXPR = "status <> 'sold' OR sold_at IS NOT NULL"


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "posters",
        sa.Column("sold_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_check_constraint(CONSTRAINT_NAME, "posters", CONSTRAINT_EXPR)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint(CONSTRAINT_NAME, "posters", type_="check")
    op.drop_column("posters", "sold_at")
