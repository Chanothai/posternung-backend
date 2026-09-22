"""poster_images.kind — ชนิดของรูป (ADR-0026 · INF-27)

Revision ID: a1f4d7b93e28
Revises: 760b692b6062
Create Date: 2026-08-16 00:00:00.000000

เปิด **บางส่วน** ของ BLOCK 5.5 ที่ `ADR-0006` กันไว้เอง — `kind` มี 3 ค่า
`FRONT`/`BACK`/`DEFECT` เท่านั้น (ADR-0026 **D1**) ส่วน `corner`/`UV`/`raking`/`detail`
· US-16 (COA) · signed URL (ADR-0006 **D6**) **ยังไม่เปิดและไม่ถูกล้ม**

🔴 **backfill ทุกแถวเป็น `FRONT`** (D4) — 407 แถวที่มีอยู่คือรูปที่เคยใช้โชว์ใน list
มาก่อนมี `kind` · **ไม่มี unique-front** เพราะของจริงเฉลี่ย 3.48 รูปต่อใบ (3–7)
การบอกว่ามีได้ใบละรูปเดียวจะชน constraint ทันที 117 ครั้ง

🔴 **ไม่ต้อง renumber `sort_order` แม้แถวเดียว** (D5) — แถวเดิมมีค่า 0–6 และเป็น
`FRONT` ทั้งหมด จึงอยู่ในแถบ 0–99 อยู่แล้ว

ลำดับใน `upgrade()` สำคัญ: เพิ่มคอลัมน์แบบ nullable → backfill → บังคับ NOT NULL →
ค่อยใส่ CHECK · ใส่ CHECK ก่อน backfill = ล้มทันทีเพราะแถวเดิมยังไม่มีค่า
"""

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "a1f4d7b93e28"
down_revision: Union[str, Sequence[str], None] = "760b692b6062"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# ค่าต้องตรงกับ `PosterImageKind` ใน app/models/enums.py และกับ component
# `PosterImageKind` ใน ../workspace/docs/api/openapi.yaml เป๊ะ
poster_image_kind = postgresql.ENUM(
    "FRONT",
    "BACK",
    "DEFECT",
    name="poster_image_kind",
    create_type=False,
)


def upgrade() -> None:
    bind = op.get_bind()
    poster_image_kind.create(bind, checkfirst=True)

    op.add_column(
        "poster_images",
        sa.Column("kind", poster_image_kind, nullable=True),
    )
    # backfill ก่อนบังคับ NOT NULL — ADR-0026 D4
    op.execute("UPDATE poster_images SET kind = 'FRONT' WHERE kind IS NULL")
    op.alter_column("poster_images", "kind", nullable=False)

    # ADR-0026 D3 — ข้อความต้องตรงกับ __table_args__ ใน app/models/poster.py เป๊ะ
    op.create_check_constraint(
        "ck_poster_images_primary_is_front",
        "poster_images",
        "NOT is_primary OR kind = 'FRONT'",
    )
    # ADR-0026 D5 — แถบตายตัวต่อ kind
    op.create_check_constraint(
        "ck_poster_images_sort_order_band",
        "poster_images",
        "(kind = 'FRONT' AND sort_order BETWEEN 0 AND 99)"
        " OR (kind = 'BACK' AND sort_order BETWEEN 100 AND 199)"
        " OR (kind = 'DEFECT' AND sort_order BETWEEN 200 AND 299)",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_poster_images_sort_order_band", "poster_images", type_="check"
    )
    op.drop_constraint(
        "ck_poster_images_primary_is_front", "poster_images", type_="check"
    )
    op.drop_column("poster_images", "kind")

    bind = op.get_bind()
    poster_image_kind.drop(bind, checkfirst=True)
