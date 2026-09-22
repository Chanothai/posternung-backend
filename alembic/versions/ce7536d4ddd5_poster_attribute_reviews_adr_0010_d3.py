"""poster_attribute_reviews (ADR-0010 D3)

Revision ID: ce7536d4ddd5
Revises: 8ed5607ab0f5
Create Date: 2026-08-04 11:43:55.161323

ตาราง audit ของการนำค่าที่คนตรวจแล้วเข้า `posters` — append-only หนึ่งแถวต่อการเขียน
หนึ่งครั้งลงหนึ่งฟิลด์ของหนึ่งใบ ไม่มี UPDATE/DELETE จึงมีแต่ `created_at`
(= `applied_at` ตามที่ ADR-0010 D3 ระบุ) ไม่มี `updated_at`

เป็นตารางแยกไม่ใช่คอลัมน์บน `posters` เพราะ ADR-0009 §Open Decisions ข้อ 4 เขียนไว้เอง
ว่า "ถ้ารอบต่อไปมีฟิลด์ ops ตัวที่สอง ให้ทบทวนว่าถึงเวลาแยกตารางหรือยัง" —
`reviewed_by`/`reviewed_at` คือฟิลด์ ops ตัวที่สองนั้น

`field` เป็น `VARCHAR` ไม่ใช่ PG enum โดยตั้งใจ — allowlist ของ D4 จะขยายในรอบหลัง
การใช้ enum จะบังคับให้ recreate type ทุกครั้งที่เพิ่มฟิลด์ (poster-database §5)
โดยไม่ได้อะไรกลับมา · ไม่แตะ `posters` และไม่แตะ enum เดิมเลย

FK `ondelete=CASCADE` — ถ้าใบถูกลบ ร่องรอยการตรวจของใบนั้นไม่มีความหมายต่อ
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "ce7536d4ddd5"
down_revision: Union[str, Sequence[str], None] = "8ed5607ab0f5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "poster_attribute_reviews",
        sa.Column(
            "id",
            sa.UUID(),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("poster_id", sa.UUID(), nullable=False),
        sa.Column("field", sa.String(length=64), nullable=False),
        sa.Column("value_before", sa.Text(), nullable=True),
        sa.Column("value_after", sa.Text(), nullable=True),
        sa.Column("reviewed_by", sa.String(length=120), nullable=False),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source", sa.String(length=255), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["poster_id"], ["posters.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_poster_attribute_reviews_poster_field",
        "poster_attribute_reviews",
        ["poster_id", "field"],
        unique=False,
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(
        "ix_poster_attribute_reviews_poster_field",
        table_name="poster_attribute_reviews",
    )
    op.drop_table("poster_attribute_reviews")
