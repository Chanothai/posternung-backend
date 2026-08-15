"""poster_splits (ADR-0024 D2)

Revision ID: a7c3f9e21d84
Revises: e2f7a0c3b9d1
Create Date: 2026-08-12 00:00:00.000000

ตาราง audit ของการแตกแถว — หนึ่งแถว = หนึ่งแถวลูกที่ถูกสร้างจากการแตกแถวพ่อ
(ADR-0024 D2 · ADR-0019 D8) เขียนด้วยมือแทน `--autogenerate` เพราะเป็นตารางใหม่ที่
ไม่มี PG enum เกี่ยวข้อง — ตรวจตรงกับ `app/models/poster_split.py` แล้ว

เป็นตารางแยกไม่ใช่คอลัมน์บน `posters` — เหตุผลเต็มอยู่ที่ docstring ของ model
(precedent ของ `poster_attribute_reviews` · `posters` ถูก query เพื่อ public response)

FK ทั้งสองฝั่ง `ondelete=CASCADE` — ถ้าแถวพ่อหรือลูกถูกลบ ร่องรอยของแถวนั้นไม่มี
ความหมายต่อ (หลักเดียวกับ `poster_attribute_reviews`)

🔴 **แก้ 2026-08-12 (code-critic รอบ 4 · INF-22 ก้อนที่ 1/2)** — `uq_poster_splits_child_poster`
เดิม (`child_poster_id`) **ไม่เคยเป็นด่านกันรันซ้ำได้จริง**: `child_poster_id` เป็น
`uuid.uuid4()` สดใหม่ทุกครั้งที่ `split_entry.py` insert แถวลูก การรันใบงานเดิมซ้ำจึง
ได้ child คนละ id เสมอ ⇒ constraint นี้ไม่มีวันยิง (พิสูจน์แล้วด้วย probe จริง:
รันใบเดิมสองครั้งได้ `poster_splits=2`) เพิ่ม `uq_poster_splits_parent_reason`
(`parent_poster_id`, `reason`) เป็นด่านจริง — ใบงานที่ไม่เปลี่ยนเนื้อหาแล้วรันซ้ำจะได้
`reason` เดิมของแถวเดิม ชนที่ระดับ DB ทันที ส่วนการแตกแถวพ่อเดียวกันหลายรอบโดยตั้งใจ
ยังทำได้ตราบใดที่แต่ละรอบเขียน `reason` ที่ต่างกัน (ซึ่งเป็นสิ่งที่ควรต่างกันอยู่แล้ว —
แต่ละชิ้นมีเหตุผลที่แตกออกมาของตัวเอง) `uq_poster_splits_child_poster` ยังอยู่
(กันกรณี insert ผิดพลาดชี้ child ซ้ำ) แต่ไม่ใช่ด่านหลักอีกต่อไป
"""

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "a7c3f9e21d84"
down_revision: Union[str, Sequence[str], None] = "e2f7a0c3b9d1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "poster_splits",
        sa.Column(
            "id",
            sa.UUID(),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("child_poster_id", sa.UUID(), nullable=False),
        sa.Column("parent_poster_id", sa.UUID(), nullable=False),
        sa.Column("reviewed_by", sa.String(length=120), nullable=False),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source", sa.String(length=255), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["child_poster_id"], ["posters.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["parent_poster_id"], ["posters.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("child_poster_id", name="uq_poster_splits_child_poster"),
        sa.UniqueConstraint(
            "parent_poster_id", "reason", name="uq_poster_splits_parent_reason"
        ),
    )
    op.create_index(
        "ix_poster_splits_parent",
        "poster_splits",
        ["parent_poster_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_poster_splits_parent", table_name="poster_splits")
    op.drop_table("poster_splits")
