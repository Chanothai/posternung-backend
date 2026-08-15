"""poster_splits — คีย์กันรันซ้ำย้ายไป piece_no (ADR-0024 A-D5 · INF-25)

Revision ID: b4e9c2f81a37
Revises: a7c3f9e21d84
Create Date: 2026-08-15 00:00:00.000000

ถอด `uq_poster_splits_parent_reason` (พิสูจน์แล้วว่าผูกด่านกันรันซ้ำไว้กับ `reason`
ซึ่ง workflow จริงบังคับให้เปลี่ยนทุกรอบ — แก้คำผิดใน `reason` แล้วรันไฟล์เดิมซ้ำสร้าง
ลูกเกินมาได้โดยไม่มีอะไรฟ้อง ดู `screens.yaml` INF-22 G2) แทนด้วยคอลัมน์ `piece_no` +
`uq_poster_splits_parent_piece` — "ชิ้นที่เท่าไหร่ของพ่อคนนี้" เริ่มที่ 2 (แถวพ่อเอง
คือชิ้นที่ 1 ตาม ADR-0019 D1) เพิ่ม `ck_poster_splits_piece_no_min` ล็อกไว้ที่ระดับ DB
ว่าไม่มีวันเห็นค่า 0/1

🔴 **ไม่มี data migration** — พิสูจน์แล้วที่ GATE 1 ของ INF-25 (2026-08-15) ว่า
`poster_splits` เป็น 0 แถวจริงทั้ง dev (`alembic_version = a7c3f9e21d84` = head ตอนนั้น)
และ sit (ตารางยังไม่มีอยู่เลย) — คอลัมน์ `piece_no` จึงประกาศ `nullable=False` ได้ทันที
ไม่ต้อง backfill

🔴 **ห้ามแก้ `a7c3f9e21d84_poster_splits_adr_0024_d2.py`** — ไฟล์นั้น apply ลง dev แล้ว
และ merge เข้า `develop` แล้ว (ต่างจากตอน code-critic รอบ 4 ที่ยังไม่ merge/apply ที่ไหน
— ห้ามอ้าง precedent นั้นซ้ำ) migration นี้จึงเป็น revision **ใหม่ต่อจาก head** ที่
`ALTER` ตารางที่มีอยู่แล้วแทน
"""

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "b4e9c2f81a37"
down_revision: Union[str, Sequence[str], None] = "a7c3f9e21d84"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_constraint(
        "uq_poster_splits_parent_reason", "poster_splits", type_="unique"
    )
    op.add_column(
        "poster_splits",
        sa.Column("piece_no", sa.Integer(), nullable=False),
    )
    op.create_unique_constraint(
        "uq_poster_splits_parent_piece",
        "poster_splits",
        ["parent_poster_id", "piece_no"],
    )
    op.create_check_constraint(
        "ck_poster_splits_piece_no_min",
        "poster_splits",
        "piece_no >= 2",
    )


def downgrade() -> None:
    op.drop_constraint("ck_poster_splits_piece_no_min", "poster_splits", type_="check")
    op.drop_constraint("uq_poster_splits_parent_piece", "poster_splits", type_="unique")
    op.drop_column("poster_splits", "piece_no")
    op.create_unique_constraint(
        "uq_poster_splits_parent_reason",
        "poster_splits",
        ["parent_poster_id", "reason"],
    )
