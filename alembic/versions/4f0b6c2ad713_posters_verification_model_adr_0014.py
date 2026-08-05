"""posters verification model — 3 คอลัมน์ + enum verification_status (ADR-0014)

Revision ID: 4f0b6c2ad713
Revises: d1a7c9e04b62
Create Date: 2026-08-05 18:20:00.000000

เพิ่ม `verification_status` (PG enum ใหม่) · `verification_note` · `reference_url`
ลง `posters` ตาม ADR-0014 D2 — **ทุกตัว nullable ไม่มี server_default**

`NULL` = ยังไม่มีใครเทียบใบนี้กับฐานข้อมูลอ้างอิง (D3) จึง**ไม่ backfill** อะไรเลย
คอลัมน์ใหม่เกิดมา NULL ทั้งตารางตามตั้งใจ · enum ไม่มีค่า `NOT_CHECKED` โดยเจตนา

**ไม่เพิ่ม CHECK และไม่เพิ่ม index** (D8) และไม่แตะ `is_authenticated` เลย (D4)

`create_type=False` ตาม convention ของ repo → autogenerate ไม่สร้าง/ลบ TYPE ให้
ต้อง `.create()` เองก่อน `add_column` และ `.drop()` หลัง drop คอลัมน์ทั้งหมดที่ใช้
type นั้น (skill `poster-database` §5 · §7)
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "4f0b6c2ad713"
down_revision: Union[str, Sequence[str], None] = "d1a7c9e04b62"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# ค่าต้องตรงกับ `VerificationStatus` ใน app/models/enums.py และกับ component
# `VerificationStatus` ใน ../workspace/docs/api/openapi.yaml เป๊ะ
verification_status = postgresql.ENUM(
    "REFERENCE_MATCHED",
    "DISCREPANCY_FOUND",
    "UNKNOWN",
    name="verification_status",
    create_type=False,
)


def upgrade() -> None:
    """Upgrade schema."""
    bind = op.get_bind()

    verification_status.create(bind, checkfirst=True)

    op.add_column(
        "posters",
        sa.Column("verification_status", verification_status, nullable=True),
    )
    op.add_column("posters", sa.Column("verification_note", sa.Text(), nullable=True))
    op.add_column("posters", sa.Column("reference_url", sa.Text(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("posters", "reference_url")
    op.drop_column("posters", "verification_note")
    op.drop_column("posters", "verification_status")

    bind = op.get_bind()
    verification_status.drop(bind, checkfirst=True)
