"""seller_profiles + house account + posters.seller_id (ADR-0028 D2/D3 · INF-32 AC-3)

เดินตาม `docs/database-design.md` §8.3 **ขั้นที่ 1 ขั้นเดียวแล้วหยุด** (ADR-0028 D2) —
ไม่แยก `poster_editions` ไม่แยก `listings` เพราะของทุกชิ้น unique (BR-L2) ทำให้
`posters` เป็นตาราง listing อยู่แล้ว การแยกตอนนี้คือ 1:1 join เปล่า ๆ

ลำดับ backfill ที่ ADR-0001 เองทำนายไว้ว่าจะไม่เจ็บ และวันนี้เก็บเกี่ยวผลของมัน:

    1. สร้าง user + seller_profiles ของ "house account" 1 แถว
    2. เพิ่ม posters.seller_id เป็น NULL ก่อน
    3. UPDATE ทุกแถว = house  (ค่าเดียวกันหมด ไม่มีความกำกวม)
    4. SET NOT NULL

🔴 **house account ต้องมี `is_house_account = true`** — ใช้กันไม่ให้คิดคอมมิชชั่นและ
ไม่ให้เข้าคิว payout (proposal §6 Q3) ไม่ใช่ธงไว้แสดงผล

⚠️ ข้อมูลอ่อนไหวของ house account (`bank_account_no` · `real_name`) ใส่เป็น
**placeholder ที่อ่านแล้วรู้ว่ายังไม่จริง** — ADR-0029 D2 บังคับให้เปิดบัญชีกลางแยก
ซึ่งเป็นงานนอกโค้ดที่ยังไม่ได้ทำ **ห้ามใส่เลขบัญชีจริงลง migration** เพราะ migration
อยู่ใน git และ repo เป็น public

Revision ID: c2b8d4e0f135
Revises: b1a7c3d9e024
Create Date: 2026-08-22 10:45:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "c2b8d4e0f135"
down_revision: Union[str, Sequence[str], None] = "b1a7c3d9e024"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# 🔴 id เป็นค่าคงที่ ไม่ใช่ gen_random_uuid() — เหตุผลเต็มอยู่ที่ `app/models/seller.py`
# (สรุป: แถว singleton ที่ migration · เทส · สคริปต์ operator ทุกเส้นต้องอ้างถึงได้
#  จากทุก environment · id ที่ต่างกันแต่ละที่ = โค้ดที่ลืม query จะไปเจอแถวผิดเงียบ ๆ)
# ‹ไม่ import จาก app/ เพราะ migration ต้องรันได้แม้โมเดลเปลี่ยนไปแล้วในอนาคต›
HOUSE_USER_ID = "00000000-0000-4000-8000-000000000001"
HOUSE_SELLER_ID = "00000000-0000-4000-8000-000000000002"
HOUSE_EMAIL = "house@posternung.local"
HOUSE_DISPLAY_NAME = "Poster Nung"


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "seller_profiles",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("display_name", sa.String(length=80), nullable=False),
        sa.Column("real_name", sa.String(length=120), nullable=False),
        sa.Column("phone_verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("bank_name", sa.String(length=80), nullable=False),
        sa.Column("bank_account_name", sa.String(length=120), nullable=False),
        sa.Column("bank_account_no", sa.String(length=30), nullable=False),
        sa.Column("id_card_image_key", sa.Text(), nullable=True),
        sa.Column(
            "kyc_status",
            postgresql.ENUM(name="kyc_status", create_type=False),
            server_default="PENDING",
            nullable=False,
        ),
        sa.Column("kyc_reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("kyc_reviewed_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("kyc_rejection_reason", sa.Text(), nullable=True),
        sa.Column("commission_rate_bps", sa.Integer(), nullable=True),
        sa.Column(
            "is_house_account", sa.Boolean(), server_default="false", nullable=False
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "commission_rate_bps IS NULL OR "
            "(commission_rate_bps >= 0 AND commission_rate_bps <= 10000)",
            name="ck_seller_profiles_commission_rate_bps_range",
        ),
        sa.CheckConstraint(
            "kyc_status <> 'REJECTED' OR kyc_rejection_reason IS NOT NULL",
            name="ck_seller_profiles_rejected_requires_reason",
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["kyc_reviewed_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", name="uq_seller_profiles_user_id"),
    )

    # --- house account: user 1 แถว + seller_profile 1 แถว ---
    bind = op.get_bind()
    house_user_id = bind.execute(
        sa.text(
            "INSERT INTO users (id, email, is_verified) "
            "VALUES (:id, :email, true) "
            "ON CONFLICT (email) DO UPDATE SET is_verified = true RETURNING id"
        ),
        {"id": HOUSE_USER_ID, "email": HOUSE_EMAIL},
    ).scalar_one()
    house_seller_id = bind.execute(
        sa.text(
            "INSERT INTO seller_profiles ("
            "  id, user_id, display_name, real_name, bank_name, bank_account_name,"
            "  bank_account_no, kyc_status, is_house_account"
            ") VALUES ("
            "  :id, :user_id, :display_name, 'PLACEHOLDER — ยังไม่กรอกจริง',"
            "  'PLACEHOLDER', 'PLACEHOLDER', 'PLACEHOLDER',"
            "  'APPROVED', true"
            ") RETURNING id"
        ),
        {
            "id": HOUSE_SELLER_ID,
            "user_id": house_user_id,
            "display_name": HOUSE_DISPLAY_NAME,
        },
    ).scalar_one()

    # --- posters.seller_id: NULL → backfill → NOT NULL ---
    op.add_column(
        "posters",
        sa.Column("seller_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    result = bind.execute(
        sa.text("UPDATE posters SET seller_id = :seller_id"),
        {"seller_id": house_seller_id},
    )
    # ไม่ทิ้งเงียบ — คนรันต้องเห็นว่ากี่แถวถูก backfill (ธรรมเนียมของ scripts/seed/)
    print(f"  backfill posters.seller_id = house account → {result.rowcount} แถว")
    op.alter_column("posters", "seller_id", nullable=False)
    op.create_foreign_key(
        "fk_posters_seller_id_seller_profiles",
        "posters",
        "seller_profiles",
        ["seller_id"],
        ["id"],
        ondelete="RESTRICT",
    )


def downgrade() -> None:
    """Downgrade schema.

    ⚠️ ลบ house account ทิ้งด้วย — ถ้ามีผู้ขายรายอื่นสมัครไปแล้ว
    `drop_table` จะล้มที่ FK ของ `posters` เอง ซึ่งเป็นพฤติกรรมที่ต้องการ
    (ไม่ลบข้อมูลผู้ขายจริงเงียบ ๆ)
    """
    op.drop_constraint(
        "fk_posters_seller_id_seller_profiles", "posters", type_="foreignkey"
    )
    op.drop_column("posters", "seller_id")
    op.drop_table("seller_profiles")
    op.execute(
        sa.text("DELETE FROM users WHERE email = :email").bindparams(email=HOUSE_EMAIL)
    )
