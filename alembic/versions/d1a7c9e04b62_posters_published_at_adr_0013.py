"""posters.published_at + CHECK ว่าจะ publish ได้ต้องมีเกรด (ADR-0013)

Revision ID: d1a7c9e04b62
Revises: ce7536d4ddd5
Create Date: 2026-08-05 15:40:00.000000

แกนที่สองแยกจาก `status` (ADR-0013 D1): `status` = วงจรสต็อก ·
`published_at` = ความพร้อมขาย · NULL = ยังไม่เปิดขาย

**ไม่มี `server_default` และไม่ backfill** — ทุกแถวที่มีอยู่ได้ NULL ซึ่งทำให้
นิพจน์ของ CHECK เป็น TRUE ทุกแถวโดยไม่ต้องดู `condition_grade` เลย
`ADD CONSTRAINT` จึง validate ผ่านทันที ไม่ต้องใช้ `NOT VALID` (ADR-0013 §Verification ข้อ 2)

ลำดับใน `upgrade()` สำคัญ: `add_column` ต้องมาก่อน `create_check_constraint`
เพราะนิพจน์อ้างคอลัมน์ที่ยังไม่มี · `downgrade()` จึงต้องกลับด้าน

ไม่แตะ enum `poster_status` เลย (ADR-0013 D1 · Alt-1) และไม่เพิ่ม index (D8)
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d1a7c9e04b62"
down_revision: Union[str, Sequence[str], None] = "ce7536d4ddd5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

CONSTRAINT_NAME = "ck_posters_published_requires_condition_grade"
# ต้องตรงกับ `Poster.__table_args__` เป๊ะ — ถ้าประกาศแต่ในไฟล์นี้
# `Base.metadata.create_all` จะไม่มี constraint และเทสจะเขียวทั้งที่ของจริงไม่มีกฎ
CONSTRAINT_EXPR = "published_at IS NULL OR condition_grade IS NOT NULL"


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "posters",
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_check_constraint(CONSTRAINT_NAME, "posters", CONSTRAINT_EXPR)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint(CONSTRAINT_NAME, "posters", type_="check")
    op.drop_column("posters", "published_at")
