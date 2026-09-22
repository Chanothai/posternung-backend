"""release_date_text (ADR-0009 D13 amendment)

Revision ID: 8ed5607ab0f5
Revises: 97a20572ba79
Create Date: 2026-08-03 20:27:38.000000

เพิ่ม `posters.release_date_text TEXT NULL` — ข้อความวันฉายตามที่พิมพ์บนใบ
(observed) คู่กับ `release_date DATE` ที่มีอยู่แล้ว (derived) ตาม ADR-0009 D13:
วันฉายที่พิมพ์บนใบจริงจำนวนมากไม่ครบสามส่วน (เช่น `SUMMER 2021`, `COMING SOON`)
ซึ่ง `DATE` เก็บไม่ได้ — คอลัมน์นี้กันไม่ให้ข้อมูลที่อ่านได้จริงจากใบหายไปตั้งแต่
ต้นทาง `release_date` ยังคงเป็นค่า derived ที่มี writer เดียวคือ
`app.core.release_date.parse_release_date_text` (D13 ข้อ 2)

nullable ไม่มี server_default — ADR-0009 D2: `NULL` = ยังไม่มีใครตรวจ (แนวเดียวกับ
คอลัมน์เชิงพรรณนาอีก 8 ตัวที่เพิ่มไปแล้วใน `97a20572ba79`) ไม่แตะ enum เดิม
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "8ed5607ab0f5"
down_revision: Union[str, Sequence[str], None] = "97a20572ba79"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("posters", sa.Column("release_date_text", sa.Text(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("posters", "release_date_text")
