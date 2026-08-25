"""enum ชุด marketplace + ขยาย poster_status 4 ค่า (ADR-0028 · INF-32 AC-4)

🔴 **revision นี้แยกจากตัวที่ *ใช้* ค่าใหม่โดยตั้งใจ ไม่ใช่เพราะอยากได้ไฟล์เล็ก**
PostgreSQL ห้ามใช้ค่าที่เพิ่งเพิ่มด้วย `ALTER TYPE ... ADD VALUE` ในทรานแซกชันเดียวกับ
ที่เพิ่ม (`unsafe use of new value of enum type`) · alembic ห่อ `upgrade` ทั้งรันไว้ใน
ทรานแซกชันเดียว ⇒ ถ้าเขียนรวมไฟล์เดียวจะพังตอนรันครั้งแรกบนเครื่องที่ยังไม่มีค่าใหม่
**แต่ผ่านบนเครื่องที่รันมาแล้ว** ซึ่งเป็นความพังชนิดที่เห็นตอน deploy ไม่ใช่ตอน dev
→ ใช้ `autocommit_block()` ครอบ `ADD VALUE` ให้ commit ออกไปก่อน แล้ว revision ถัดไป
จึงใช้ค่าใหม่ได้

**ลำดับค่าใน enum มีความหมาย** — PostgreSQL เรียงตามลำดับที่ประกาศ ไม่ใช่ตามตัวอักษร
(ADR-0003 อธิบายเรื่องนี้ไว้กับ `poster_condition`) จึงใช้ `BEFORE`/`AFTER` วางให้ตรง
วงจรชีวิตจริง แทนที่จะต่อท้ายแล้วได้ `ORDER BY status` ที่ไม่มีความหมาย:

    draft → pending_review → rejected → available → reserved → sold → delisted

⚠️ **ขั้นนี้ย้อนไม่ได้แบบ in-place** — PostgreSQL ลบค่าออกจาก enum ไม่ได้
`downgrade()` จึงต้อง **สร้าง type ใหม่แล้วสลับ** และจะ**ปฏิเสธการทำงาน**ถ้ามีแถวไหน
ถืออยู่ในค่าที่กำลังจะหาย — ดีกว่าลบข้อมูลเงียบ ๆ

Revision ID: b1a7c3d9e024
Revises: a10a5a0b6608
Create Date: 2026-08-22 10:40:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "b1a7c3d9e024"
down_revision: Union[str, Sequence[str], None] = "a10a5a0b6608"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# --- enum ใหม่ทั้งหมด (create_type=False ทุกตัวตามธรรมเนียมของ repo นี้) ---
poster_tier = postgresql.ENUM(
    "ORIGINAL_VINTAGE",
    "ORIGINAL_MODERN",
    "REPRINT",
    name="poster_tier",
    create_type=False,
)
kyc_status = postgresql.ENUM(
    "PENDING", "APPROVED", "REJECTED", name="kyc_status", create_type=False
)
order_status = postgresql.ENUM(
    "AWAITING_PAYMENT",
    "PAYMENT_REVIEW",
    "AWAITING_SHIPMENT",
    "SHIPPED",
    "COMPLETED",
    "CANCELLED",
    "DISPUTED",
    "REFUNDED",
    name="order_status",
    create_type=False,
)
payment_status = postgresql.ENUM(
    "AWAITING",
    "CLAIMED",
    "VERIFIED",
    "REJECTED",
    name="payment_status",
    create_type=False,
)
delivery_confirm_actor = postgresql.ENUM(
    "BUYER",
    "SYSTEM_AUTO",
    "ADMIN",
    name="delivery_confirm_actor",
    create_type=False,
)
dispute_status = postgresql.ENUM(
    "OPEN",
    "RESOLVED_REFUND",
    "RESOLVED_RELEASE",
    "REJECTED",
    name="dispute_status",
    create_type=False,
)
payout_status = postgresql.ENUM(
    "QUEUED", "PAID", "FAILED", name="payout_status", create_type=False
)
notification_channel = postgresql.ENUM(
    "EMAIL", "LINE", name="notification_channel", create_type=False
)
notification_status = postgresql.ENUM(
    "PENDING", "SENT", "FAILED", name="notification_status", create_type=False
)

NEW_TYPES = (
    poster_tier,
    kyc_status,
    order_status,
    payment_status,
    delivery_confirm_actor,
    dispute_status,
    payout_status,
    notification_channel,
    notification_status,
)

# ค่าใหม่ของ poster_status + ตำแหน่งที่ต้องแทรก (ดู docstring)
POSTER_STATUS_ADDITIONS = (
    ("draft", "BEFORE", "available"),
    ("pending_review", "AFTER", "draft"),
    ("rejected", "AFTER", "pending_review"),
    ("delisted", "AFTER", "sold"),
)
POSTER_STATUS_ORIGINAL = ("available", "reserved", "sold")


def upgrade() -> None:
    """Upgrade schema."""
    bind = op.get_bind()
    for enum_type in NEW_TYPES:
        enum_type.create(bind, checkfirst=True)

    # 🔴 ต้อง commit ออกไปก่อน ไม่งั้น revision ถัดไปใช้ค่าใหม่ไม่ได้ (ดู docstring)
    with op.get_context().autocommit_block():
        for value, position, anchor in POSTER_STATUS_ADDITIONS:
            op.execute(
                f"ALTER TYPE poster_status ADD VALUE IF NOT EXISTS "
                f"'{value}' {position} '{anchor}'"
            )


def downgrade() -> None:
    """Downgrade schema.

    🔴 **ปฏิเสธการทำงานถ้ามีแถวถือค่าใหม่อยู่** — ทางเลือกคือลบข้อมูลเงียบ ๆ
    หรือหยุดแล้วบอกว่าทำไม · เลือกอย่างหลังเสมอ
    """
    bind = op.get_bind()
    new_values = tuple(value for value, _, _ in POSTER_STATUS_ADDITIONS)
    stuck = bind.execute(
        sa.text("SELECT count(*) FROM posters WHERE status::text = ANY(:vals)"),
        {"vals": list(new_values)},
    ).scalar_one()
    if stuck:
        raise RuntimeError(
            f"downgrade ไม่ได้ — มี {stuck} แถวใน posters ที่ status เป็นค่าใหม่ "
            f"({', '.join(new_values)})\n"
            "ย้ายแถวพวกนั้นกลับไปเป็น available/reserved/sold ก่อน แล้วค่อยรันใหม่"
        )

    # 🔴 **ต้องถอด CHECK ที่อ้าง `status` ออกก่อนสลับ type** — พบตอนรันจริง 2026-08-22:
    # หลัง `RENAME TYPE` นิพจน์ของ CHECK เดิมยังผูกกับ `poster_status_old` ทำให้
    # `ALTER COLUMN ... TYPE` ล้มด้วย `operator does not exist: poster_status <>
    # poster_status_old` · ตัวที่ติดคือ `ck_posters_sold_requires_sold_at` ซึ่งเป็นของ
    # **ADR-0025 D2 ไม่ใช่ของ revision นี้** ⇒ ต้องสร้างกลับให้เหมือนเดิมเป๊ะหลังสลับเสร็จ
    # (ADR-0025 กำกับไว้ว่า "ข้อความต้องตรงกับ migration เป๊ะ")
    # ‹CHECK ของ revision d3c9e5f10246 ไม่ต้องจัดการที่นี่ — downgrade ของมันรันไปก่อนแล้ว›
    op.drop_constraint("ck_posters_sold_requires_sold_at", "posters", type_="check")

    # PostgreSQL ลบค่าออกจาก enum ไม่ได้ → สร้าง type ใหม่แล้วสลับ
    # (ทรงเดียวกับ a7c31e5f9b04 / f4c8a1e07b93 ที่เคยทำกับ verification_status)
    joined = ", ".join(f"'{v}'" for v in POSTER_STATUS_ORIGINAL)
    op.execute("ALTER TYPE poster_status RENAME TO poster_status_old")
    op.execute(f"CREATE TYPE poster_status AS ENUM ({joined})")
    op.execute(
        "ALTER TABLE posters ALTER COLUMN status DROP DEFAULT, "
        "ALTER COLUMN status TYPE poster_status USING status::text::poster_status, "
        "ALTER COLUMN status SET DEFAULT 'available'::poster_status"
    )
    op.execute("DROP TYPE poster_status_old")
    op.create_check_constraint(
        "ck_posters_sold_requires_sold_at",
        "posters",
        "status <> 'sold' OR sold_at IS NOT NULL",
    )

    for enum_type in reversed(NEW_TYPES):
        enum_type.drop(bind, checkfirst=True)
