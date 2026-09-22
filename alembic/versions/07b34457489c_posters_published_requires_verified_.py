"""posters CHECK ck_posters_published_requires_verified (ADR-0027 A3-D1 · INF-38)

Revision ID: 07b34457489c
Revises: b6f2d4a91c73
Create Date: 2026-08-29 00:00:00.000000

ลง CHECK ระดับ DB ของ invariant `published ⇒ verified` ที่ ADR-0027 D1 เขียนไว้ —
วันนี้บังคับแค่ฝั่ง Python (`poster_service.is_publishable()`) เท่านั้น
`UPDATE posters SET published_at = now()` ผ่าน psql ข้ามด่านนั้นได้ทั้งดุ้น

🔴 **ไม่ใช่ SQL ตรงตัวของ D4** — D4 เขียน
`CHECK (published_at IS NULL OR verified_at IS NOT NULL)` ซึ่ง**เดินไม่ได้จริง**
เพราะขัดกับ `A-D11` (ห้ามถอนใบ `status='sold'` ทุกกรณี) เอง: มีอย่างน้อย 1 แถว
(`ec3478a8` · THE MATRIX) ที่ `sold` ไปแล้วตั้งแต่ก่อน `published_at` เดินได้ โดยไม่มี
ใครเซ็น `verified_at` และจะไม่มีวันเซ็นได้อีก (A3-D2 — เซ็นย้อนหลังใบที่ขายแล้ว
คือตรายาง) ⇒ ADR-0027 **Amendment 3 (A3-D1)** แทนที่ SQL ของ D4 ด้วยข้อยกเว้นนี้:

    CHECK (published_at IS NULL OR verified_at IS NOT NULL OR status = 'sold')

readiness query ของ A3-D3 (ต้องได้ 0 ก่อนรัน migration นี้ — วัดจริงที่ GATE 1
ทั้ง dev และ sit หลังกู้ข้อมูล + WITHDRAW 115 ใบเมื่อ 2026-08-29):

    SELECT count(*) FROM posters
    WHERE published_at IS NOT NULL AND verified_at IS NULL AND status <> 'sold';

ไม่ใช้ `NOT VALID` (AC-3 · เหตุผลของ D4 ยังจริงทุกข้อ — PostgreSQL ยังบังคับ
constraint ที่ `NOT VALID` กับทุก UPDATE อยู่ดี ด่านที่ล็อกเครื่องมือซ่อมไว้ข้างนอก
คือด่านที่ผิด) — `ADD CONSTRAINT` ธรรมดา validate แถวเดิมทันทีตอน upgrade
"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "07b34457489c"
down_revision: Union[str, Sequence[str], None] = "b6f2d4a91c73"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

CONSTRAINT_NAME = "ck_posters_published_requires_verified"
# ต้องตรงกับ `Poster.__table_args__` เป๊ะ — ถ้าประกาศแต่ในไฟล์นี้
# `Base.metadata.create_all` จะไม่มี constraint และเทสจะเขียวทั้งที่ของจริงไม่มีกฎ
CONSTRAINT_EXPR = "published_at IS NULL OR verified_at IS NOT NULL OR status = 'sold'"


def upgrade() -> None:
    """Upgrade schema."""
    op.create_check_constraint(CONSTRAINT_NAME, "posters", CONSTRAINT_EXPR)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint(CONSTRAINT_NAME, "posters", type_="check")
