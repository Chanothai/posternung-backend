"""poster detail attributes (ADR-0009)

Revision ID: 97a20572ba79
Revises: 1c27334bcdf9
Create Date: 2026-08-03 01:13:52.851287

เพิ่ม 9 คอลัมน์เชิงพรรณนาลง `posters` ตาม ADR-0009 D1: `poster_type` ·
`release_region` · `release_date` · `copyright_year` · `size_format` · `year` ·
`restoration_status` · `restoration_note` · `needs_review`

🔴 ทุก enum ใหม่ (nullable) **ไม่มี server_default** โดยตั้งใจ — ADR-0009 D2 นิยาม
`NULL` = ยังไม่มีใครตรวจ ต่างจาก `UNKNOWN` = คนตรวจแล้วตัดสินไม่ได้ ถาวร ตั้ง default
เป็น `UNKNOWN` จะเท่ากับอ้างว่าทุกแถวถูกคนตรวจมาแล้วซึ่งเป็นเท็จ

**ไม่มีการ backfill ข้อมูลเดิม 118 แถว** — ทุกคอลัมน์ใหม่เกิดเป็น NULL ตามตั้งใจ
ยกเว้น `needs_review` ที่เป็น NOT NULL server_default 'true' (ธงคุณภาพข้อมูล ไม่ใช่
ข้อมูลเชิงพรรณนา — ยังใช้ server_default ปกติตาม poster-database §4 ข้อ 4)

ทุก `PgEnum` ในโปรเจกต์นี้ตั้ง `create_type=False` (ดู `app/models/poster.py`) —
autogenerate จึงไม่สร้าง/ลบ TYPE ให้ ต้องเรียก `.create()/.drop()` เองตาม
skill `poster-database` §5 (แก้จาก autogenerate scaffold ที่ inline ENUM ไว้ตรง
`add_column` ซึ่งจะพยายาม CREATE TYPE ซ้ำเอง)
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "97a20572ba79"
down_revision: Union[str, Sequence[str], None] = "1c27334bcdf9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# --- Enum types ใหม่ (create_type=False เพื่อให้ downgrade→upgrade วนซ้ำได้) ---
poster_type = postgresql.ENUM(
    "TEASER",
    "ADVANCE",
    "THEATRICAL",
    "RERELEASE",
    "UNKNOWN",
    name="poster_type",
    create_type=False,
)
release_region = postgresql.ENUM(
    "TH",
    "US",
    "JP",
    "UK",
    "INTL",
    "UNKNOWN",
    name="release_region",
    create_type=False,
)
size_format = postgresql.ENUM(
    "ONE_SHEET",
    "HALF_SHEET",
    "INSERT",
    "QUAD",
    "OTHER",
    "UNKNOWN",
    name="size_format",
    create_type=False,
)
restoration_status = postgresql.ENUM(
    "NONE",
    "RESTORED",
    "LINEN_BACKED",
    "UNKNOWN",
    name="restoration_status",
    create_type=False,
)


def upgrade() -> None:
    """Upgrade schema."""
    bind = op.get_bind()

    # สร้าง enum types ก่อน add_column (create_type=False จึงไม่ถูกสร้างซ้ำโดย add_column)
    poster_type.create(bind, checkfirst=True)
    release_region.create(bind, checkfirst=True)
    size_format.create(bind, checkfirst=True)
    restoration_status.create(bind, checkfirst=True)

    op.add_column("posters", sa.Column("poster_type", poster_type, nullable=True))
    op.add_column("posters", sa.Column("release_region", release_region, nullable=True))
    op.add_column("posters", sa.Column("release_date", sa.Date(), nullable=True))
    op.add_column(
        "posters", sa.Column("copyright_year", sa.SmallInteger(), nullable=True)
    )
    op.add_column("posters", sa.Column("size_format", size_format, nullable=True))
    op.add_column("posters", sa.Column("year", sa.SmallInteger(), nullable=True))
    op.add_column(
        "posters",
        sa.Column("restoration_status", restoration_status, nullable=True),
    )
    op.add_column("posters", sa.Column("restoration_note", sa.Text(), nullable=True))
    op.add_column(
        "posters",
        sa.Column("needs_review", sa.Boolean(), server_default="true", nullable=False),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("posters", "needs_review")
    op.drop_column("posters", "restoration_note")
    op.drop_column("posters", "restoration_status")
    op.drop_column("posters", "year")
    op.drop_column("posters", "size_format")
    op.drop_column("posters", "copyright_year")
    op.drop_column("posters", "release_date")
    op.drop_column("posters", "release_region")
    op.drop_column("posters", "poster_type")

    bind = op.get_bind()
    restoration_status.drop(bind, checkfirst=True)
    size_format.drop(bind, checkfirst=True)
    release_region.drop(bind, checkfirst=True)
    poster_type.drop(bind, checkfirst=True)
