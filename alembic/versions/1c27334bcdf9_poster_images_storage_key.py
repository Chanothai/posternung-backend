"""poster_images: replace url with storage_key + width_px/height_px (ADR-0006)

Revision ID: 1c27334bcdf9
Revises: b8e3d1f74c25
Create Date: 2026-08-01 00:00:00.000000

`poster_images.url` เก็บ URL เต็ม ผูกโฮสต์/path/วิธีเข้าถึงไว้ในค่าเดียว — ย้าย CDN/bucket
ต้อง UPDATE ทุกแถว, ก๊อปข้ามผู้ env ไม่ได้, ทำ signed URL ไม่ได้ (ADR-0006 §Context)

ตาราง `poster_images` ว่างจริงในทุก env (dev/sit/uat/production — ยืนยันแล้วที่ GATE 1
ของ ADR-0006) จึงทำเป็น migration เดียว ไม่ต้อง expand/contract และไม่ต้อง backfill —
เพิ่ม `storage_key` เป็น NOT NULL UNIQUE ได้ตรงๆ ในสเต็ปเดียว

⚠️ **downgrade() ใช้ได้เฉพาะตารางว่างเท่านั้น — ตั้งใจ ไม่ใช่ความผิดพลาด**
`storage_key` ไม่มีข้อมูลพอที่จะคำนวณกลับเป็น `url` เดิม (ไม่รู้ base URL ตอน migration
รันหรือ CDN ไหนที่เคยใช้) ถ้ามีข้อมูลจริงในตารางตอน downgrade แถวเหล่านั้นจะได้ `url`
เป็นค่าว่าง/placeholder ที่ผิด — ห้ามพึ่ง downgrade นี้เมื่อมีข้อมูลจริงแล้ว
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "1c27334bcdf9"
down_revision: Union[str, Sequence[str], None] = "b8e3d1f74c25"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.drop_column("poster_images", "url")
    op.add_column(
        "poster_images",
        sa.Column("storage_key", sa.String(length=512), nullable=False),
    )
    op.add_column("poster_images", sa.Column("width_px", sa.Integer(), nullable=True))
    op.add_column("poster_images", sa.Column("height_px", sa.Integer(), nullable=True))
    op.create_unique_constraint(
        "uq_poster_images_storage_key", "poster_images", ["storage_key"]
    )
    op.create_check_constraint(
        "ck_poster_images_dimensions_positive",
        "poster_images",
        "(width_px IS NULL OR width_px > 0) AND (height_px IS NULL OR height_px > 0)",
    )
    op.create_check_constraint(
        "ck_poster_images_dimensions_paired",
        "poster_images",
        "(width_px IS NULL) = (height_px IS NULL)",
    )


def downgrade() -> None:
    """Downgrade schema.

    ใช้ได้เฉพาะตอนตาราง `poster_images` ว่างเท่านั้น (ดู module docstring) — ไม่ backfill
    `url` ปลอมจาก `storage_key`.
    """
    op.drop_constraint(
        "ck_poster_images_dimensions_paired", "poster_images", type_="check"
    )
    op.drop_constraint(
        "ck_poster_images_dimensions_positive", "poster_images", type_="check"
    )
    op.drop_constraint("uq_poster_images_storage_key", "poster_images", type_="unique")
    op.drop_column("poster_images", "height_px")
    op.drop_column("poster_images", "width_px")
    op.drop_column("poster_images", "storage_key")
    op.add_column("poster_images", sa.Column("url", sa.Text(), nullable=False))
