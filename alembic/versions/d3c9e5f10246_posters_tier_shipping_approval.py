"""posters: tier · shipping_fee · ด่านอนุมัติ listing (BR-L3 · BR-L6 · INF-32 AC-4/AC-9)

**สี่คอลัมน์ใหม่ + สองด่าน**

`tier` — BR-L3 บังคับเลือก **ไม่มีค่า `UNKNOWN`** ⇒ ลงเป็น `NULL` ทั้ง 113 แถวก่อน
🔴 **ตั้งใจไม่ backfill** — proposal §6 **Q2** เป็นข้อเท็จจริงของของจริงที่มีแต่เจ้าของรู้
เจ้าของสั่ง 2026-08-22 ให้ทำใบงานให้ติ๊กเอง (`tier-entry.csv`) และจะส่งกลับใน 2 วัน
**เดาแล้วผิด = ข้อมูลผิดขึ้นจอ 113 แถว** ซึ่งแพงกว่าการรอมาก · `NULL` ที่นี่แปลว่า
"ยังไม่มีใครกรอก" ไม่ใช่ "ไม่แน่ใจ" (ADR-0009 D2 เป็น precedent ของหลักนี้)

`approved_at` / `approved_by` / `rejection_reason` — ด่านของ BR-L6
🔴 **คนละอย่างกับ `verified_at` โดยสิ้นเชิง** (ADR-0028 Consequence 2):
`verified_at` = คนของร้านหยิบ **ใบจริง** ขึ้นมาตรวจครบทุกมิติแล้วเซ็นรับ
`approved_at`  = แอดมินดู **รูปกับข้อมูล** แล้วอนุญาตให้ขึ้นขาย
ของผู้ขายภายนอกเราไม่มีทางจับใบจริง ⇒ **ห้าม reuse `verified_at` เป็นด่านอนุมัติ**
ทำเมื่อไหร่ = "เคยมีคนจับของจริง" เสียความหมายถาวรทั้งแคตตาล็อก

### backfill `approved_at` ของ 113 แถวเดิม — เลือก `created_at` ไม่ใช่ `now()`

แถวเดิมทั้งหมดเป็นของร้านเราเอง (ADR-0028 D3 backfill ไปเป็น house account แล้ว)
ซึ่ง **ไม่เคยมีเหตุการณ์ "อนุมัติ" เกิดขึ้นจริง** — การใส่ `now()` จะอ่านเหมือนว่า
มีคนกดอนุมัติ 113 ใบพร้อมกันตอนรัน migration ซึ่งเป็นเท็จ · ใช้ `created_at` แทน
เพราะอ่านได้ว่า "ของร้านเราเอง ถือว่าอนุมัติตั้งแต่วันที่นำเข้า" ซึ่งเป็นสิ่งที่เกิดขึ้นจริง

🔴 **`approved_by` เป็น `NULL` ทุกแถวโดยตั้งใจ** — ไม่มีคนกด จึงไม่มีชื่อใครให้ใส่
(แนวเดียวกับ `verified_at` ของ ADR-0027 ที่ไม่ใส่ `server_default` เพราะ
"การใส่ default = ปลอมลายเซ็นให้แถวเดิมย้อนหลัง")

Revision ID: d3c9e5f10246
Revises: c2b8d4e0f135
Create Date: 2026-08-22 10:50:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "d3c9e5f10246"
down_revision: Union[str, Sequence[str], None] = "c2b8d4e0f135"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "posters",
        sa.Column(
            "tier",
            postgresql.ENUM(name="poster_tier", create_type=False),
            nullable=True,
        ),
    )
    op.add_column(
        "posters",
        sa.Column(
            "shipping_fee",
            sa.Numeric(precision=10, scale=2),
            server_default="0",
            nullable=False,
        ),
    )
    op.add_column(
        "posters", sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        "posters",
        sa.Column("approved_by", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.add_column("posters", sa.Column("rejection_reason", sa.Text(), nullable=True))
    op.create_foreign_key(
        "fk_posters_approved_by_users",
        "posters",
        "users",
        ["approved_by"],
        ["id"],
        ondelete="SET NULL",
    )

    # backfill ก่อนลง CHECK — ไม่งั้น ADD CONSTRAINT ล้มที่การ validate แถวเดิม
    # (บทเรียนตรงจาก ADR-0027 D4 ซึ่ง `ck_posters_published_requires_verified`
    #  ลงไม่ได้เพราะมี 116 แถวละเมิด และ NOT VALID ก็ไม่ใช่ทางออก)
    result = op.get_bind().execute(
        sa.text(
            "UPDATE posters SET approved_at = created_at "
            "WHERE approved_at IS NULL AND status IN "
            "('available', 'reserved', 'sold')"
        )
    )
    print(f"  backfill posters.approved_at = created_at → {result.rowcount} แถว")

    op.create_check_constraint(
        "ck_posters_sellable_requires_approved_at",
        "posters",
        "status NOT IN ('available', 'reserved', 'sold') OR approved_at IS NOT NULL",
    )
    op.create_check_constraint(
        "ck_posters_rejected_requires_reason",
        "posters",
        "status <> 'rejected' OR rejection_reason IS NOT NULL",
    )
    op.create_check_constraint(
        "ck_posters_shipping_fee_non_negative", "posters", "shipping_fee >= 0"
    )

    op.create_index(
        "ix_posters_pending_review",
        "posters",
        ["updated_at"],
        postgresql_where=sa.text("status = 'pending_review'"),
    )
    op.create_index("ix_posters_seller_status", "posters", ["seller_id", "status"])


def downgrade() -> None:
    """Downgrade schema.

    🔴 **ค่าที่คนติ๊กใน `tier` หายถาวร** — ไม่มีที่ไหนเก็บสำเนา (ใบงาน `tier-entry.csv`
    อยู่นอก git ตาม `.gitignore`) · ถ้ารัน downgrade หลังจากกรอกใบงานแล้ว
    ต้องกรอกใหม่ทั้ง 113 แถว **อ่านข้อนี้ก่อน downgrade ไม่ใช่รันแล้วค่อยรู้**
    """
    op.drop_index("ix_posters_seller_status", table_name="posters")
    op.drop_index("ix_posters_pending_review", table_name="posters")
    op.drop_constraint("ck_posters_shipping_fee_non_negative", "posters", type_="check")
    op.drop_constraint("ck_posters_rejected_requires_reason", "posters", type_="check")
    op.drop_constraint(
        "ck_posters_sellable_requires_approved_at", "posters", type_="check"
    )
    op.drop_constraint("fk_posters_approved_by_users", "posters", type_="foreignkey")
    op.drop_column("posters", "rejection_reason")
    op.drop_column("posters", "approved_by")
    op.drop_column("posters", "approved_at")
    op.drop_column("posters", "shipping_fee")
    op.drop_column("posters", "tier")
