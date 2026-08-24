"""orders · escrow · outbox · config — ตาราง 10 ตัวของ marketplace (INF-32)

**ADR ที่บังคับรูปร่างของ migration นี้ — อ่านก่อนแก้อะไรก็ตาม**

| ที่มา | บังคับอะไร |
|---|---|
| ADR-0020 **D5 · D12.1** | `order_shipping_details` เป็น **ตารางแยก** ห้ามยุบเป็นคอลัมน์ใน `orders` |
| ADR-0020 **D12.2** | `shipping_purged_at` · `delivered_at` · `delivered_confirmed_by` มี **ตั้งแต่ migration แรก** — เติมทีหลังแปลว่าออร์เดอร์ชุดแรกไม่มีนาฬิกาให้เริ่มนับ |
| ADR-0020 **A4-D1** | `delivered_confirmed_by` เป็น enum 3 ค่า (`BUYER` · `SYSTEM_AUTO` · `ADMIN`) |
| ADR-0020 **A4-D2** | 6 ฟิลด์ snapshot ของ BL-77 อยู่บน `orders` **ครบทั้ง 6 ไม่ลดสักฟิลด์** |
| ADR-0029 **D3** | `payments.bank_statement_checked` เป็น **CHECK ระดับ DB** ไม่ใช่ if ใน service |
| ADR-0029 **D6** | ห้ามมีคอลัมน์เลขบัตร/CVV/วันหมดอายุ/เลขบัญชีผู้ซื้อ |
| ADR-0030 **D5** | **ไม่มี `order_items`** — 1 ธุรกรรม = 1 ชิ้น |
| INF-32 **AC-6** | `uq_live_order_per_poster` = ชั้นที่ 3 ของการกันซื้อซ้อน |

🔴 **`platform_settings` ถูก seed ค่าตั้งต้นในไฟล์นี้** — เป็น config ของระบบ
ไม่ใช่ข้อมูลโปสเตอร์ · เจ้าของสั่ง 2026-08-22 ว่า "seed เฉพาะโครงสร้าง ยังไม่ต้อง seed
โปสเตอร์" ⇒ ค่าพวกนี้อยู่ในขอบเขต "โครงสร้าง" เพราะไม่มีมันแล้วระบบคำนวณอะไรไม่ได้เลย

Revision ID: e4d0f6021357
Revises: d3c9e5f10246
Create Date: 2026-08-22 10:55:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "e4d0f6021357"
down_revision: Union[str, Sequence[str], None] = "d3c9e5f10246"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _uuid_pk() -> sa.Column:
    return sa.Column(
        "id",
        postgresql.UUID(as_uuid=True),
        server_default=sa.text("gen_random_uuid()"),
        nullable=False,
    )


def _created_at() -> sa.Column:
    return sa.Column(
        "created_at",
        sa.DateTime(timezone=True),
        server_default=sa.text("now()"),
        nullable=False,
    )


def _updated_at() -> sa.Column:
    return sa.Column(
        "updated_at",
        sa.DateTime(timezone=True),
        server_default=sa.text("now()"),
        nullable=False,
    )


# ค่าตั้งต้นของ platform_settings — key ต้องตรงกับ docstring ของ PlatformSetting
DEFAULT_SETTINGS = (
    (
        "commission_rate_bps",
        "1000",
        "ค่าคอมมิชชั่นกลาง 10% (BR-L7) · ผู้ขายรุ่นก่อตั้ง 5% ตั้ง override "
        "ที่ seller_profiles.commission_rate_bps = 500",
    ),
    (
        "reservation_ttl_minutes",
        "60",
        "อายุการจอง (ADR-0030 D3) · ห้าม hardcode — ค่านี้จะถูกจูนหลัง beta แน่นอน",
    ),
    (
        "inspection_period_days",
        "7",
        "หน้าต่างตรวจรับ/แจ้งปัญหา (BR-P4 · BR-P6 · ADR-0020 A4-D1) "
        "🔴 ต้องไม่เกิน 90 — ADR-0020 D13/A4-D3",
    ),
    (
        "ship_by_business_days",
        "3",
        "ผู้ขายต้องส่งของภายในกี่วันทำการ (BR-P3) "
        "🔴 นิยามของ 'วันทำการ' ยังไม่ตัดสิน — INF-33 known_gap",
    ),
    (
        "platform_promptpay_id",
        "",
        "PromptPay ของบัญชีกลาง (ADR-0029 D1) 🔴 ว่างอยู่ — บัญชีกลางแยกยังไม่ถูกเปิด "
        "(ADR-0029 D2 · งานนอกโค้ด) ห้ามใส่เลขจริงลง migration เพราะ repo เป็น public",
    ),
)


def upgrade() -> None:
    """Upgrade schema."""
    # ── payouts ต้องมาก่อน orders เพราะ orders.payout_id อ้างถึง ──
    op.create_table(
        "payouts",
        _uuid_pk(),
        sa.Column("seller_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("batch_date", sa.Date(), nullable=False),
        sa.Column("amount", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("order_count", sa.Integer(), nullable=False),
        sa.Column(
            "status",
            postgresql.ENUM(name="payout_status", create_type=False),
            server_default="QUEUED",
            nullable=False,
        ),
        sa.Column("transfer_ref", sa.String(length=80), nullable=True),
        sa.Column("paid_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("paid_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        _created_at(),
        _updated_at(),
        sa.CheckConstraint("amount >= 0", name="ck_payouts_amount_non_negative"),
        sa.CheckConstraint(
            "status <> 'PAID' OR (paid_at IS NOT NULL AND paid_by IS NOT NULL)",
            name="ck_payouts_paid_requires_when_and_who",
        ),
        sa.ForeignKeyConstraint(
            ["seller_id"], ["seller_profiles.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(["paid_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_payouts_seller_batch", "payouts", ["seller_id", "batch_date"])

    # ── addresses (ชั้น ค ของ ADR-0020 D5) ──
    op.create_table(
        "addresses",
        _uuid_pk(),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("recipient_name", sa.String(length=120), nullable=False),
        sa.Column("recipient_phone", sa.String(length=20), nullable=False),
        sa.Column("address_line", sa.Text(), nullable=False),
        sa.Column("sub_district", sa.String(length=80), nullable=True),
        sa.Column("district", sa.String(length=80), nullable=True),
        sa.Column("province", sa.String(length=80), nullable=False),
        sa.Column("postal_code", sa.String(length=10), nullable=False),
        sa.Column("is_default", sa.Boolean(), server_default="false", nullable=False),
        _created_at(),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )

    # ── orders (ชั้น ก — ห้ามมีข้อมูลส่วนบุคคลแม้แต่ฟิลด์เดียว) ──
    op.create_table(
        "orders",
        _uuid_pk(),
        sa.Column("order_no", sa.String(length=20), nullable=False),
        sa.Column("poster_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("buyer_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("seller_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("reservation_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "status",
            postgresql.ENUM(name="order_status", create_type=False),
            server_default="AWAITING_PAYMENT",
            nullable=False,
        ),
        # --- เงิน (snapshot ทั้งหมด) ---
        sa.Column("item_price", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("shipping_fee", sa.Numeric(precision=10, scale=2), nullable=False),
        sa.Column("total_amount", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("commission_rate_bps", sa.Integer(), nullable=False),
        sa.Column(
            "commission_amount", sa.Numeric(precision=12, scale=2), nullable=False
        ),
        sa.Column(
            "seller_payout_amount", sa.Numeric(precision=12, scale=2), nullable=False
        ),
        # --- BL-77 snapshot 6 ฟิลด์ (ADR-0020 A4-D2) · `price` คือ item_price ข้างบน ---
        sa.Column("item_title", sa.String(length=255), nullable=False),
        sa.Column(
            "item_condition_grade",
            postgresql.ENUM(name="poster_condition", create_type=False),
            nullable=True,
        ),
        sa.Column("item_image_urls", postgresql.JSONB(), nullable=True),
        sa.Column(
            "item_verification_status",
            postgresql.ENUM(name="verification_status", create_type=False),
            nullable=True,
        ),
        sa.Column("item_reference_note", sa.Text(), nullable=True),
        # --- การส่งของ ---
        sa.Column("carrier", sa.String(length=80), nullable=True),
        sa.Column("tracking_no", sa.String(length=80), nullable=True),
        sa.Column("shipped_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ship_by_due_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("auto_confirm_due_at", sa.DateTime(timezone=True), nullable=True),
        # --- ADR-0020 D12.2 · A4-D1 ---
        sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "delivered_confirmed_by",
            postgresql.ENUM(name="delivery_confirm_actor", create_type=False),
            nullable=True,
        ),
        sa.Column("shipping_purged_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("payout_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("paid_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancellation_reason", sa.Text(), nullable=True),
        _created_at(),
        _updated_at(),
        # 🔴 ไม่มี CHECK "ผู้ซื้อ ≠ ผู้ขาย" ที่นี่ — เหตุผลเต็มอยู่ใน `app/models/order.py`
        # (สรุป: `buyer_id` ชี้ `users` · `seller_id` ชี้ `seller_profiles` ⇒ เทียบกันแล้ว
        #  ไม่มีทางเป็นเท็จ · ด่านจริงอยู่ที่ service — INF-33)
        sa.CheckConstraint("item_price >= 0", name="ck_orders_item_price_non_negative"),
        sa.CheckConstraint(
            "shipping_fee >= 0", name="ck_orders_shipping_fee_non_negative"
        ),
        sa.CheckConstraint(
            "total_amount = item_price + shipping_fee",
            name="ck_orders_total_is_item_plus_shipping",
        ),
        sa.CheckConstraint(
            "seller_payout_amount = total_amount - commission_amount",
            name="ck_orders_payout_is_total_minus_commission",
        ),
        sa.CheckConstraint(
            "(delivered_at IS NULL) = (delivered_confirmed_by IS NULL)",
            name="ck_orders_delivered_at_pairs_with_actor",
        ),
        sa.CheckConstraint(
            "status NOT IN ('CANCELLED', 'REFUNDED') OR cancellation_reason IS NOT NULL",
            name="ck_orders_cancelled_requires_reason",
        ),
        sa.ForeignKeyConstraint(["poster_id"], ["posters.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["buyer_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["seller_id"], ["seller_profiles.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["reservation_id"], ["reservations.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(["payout_id"], ["payouts.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("order_no", name="uq_orders_order_no"),
    )
    # 🔴 INF-32 AC-6 — ชั้นที่ 3 ของการกันซื้อซ้อน
    op.create_index(
        "uq_live_order_per_poster",
        "orders",
        ["poster_id"],
        unique=True,
        postgresql_where=sa.text(
            "status NOT IN ('COMPLETED', 'CANCELLED', 'REFUNDED')"
        ),
    )
    op.create_index("ix_orders_buyer_created", "orders", ["buyer_id", "created_at"])
    op.create_index("ix_orders_seller_status", "orders", ["seller_id", "status"])
    op.create_index(
        "ix_orders_payout_queue",
        "orders",
        ["seller_id"],
        postgresql_where=sa.text("status = 'COMPLETED' AND payout_id IS NULL"),
    )
    # ADR-0020 D14.3 — รายการ "ส่งแล้วรอยืนยัน" เรียงตามค้างนานสุด
    op.create_index(
        "ix_orders_awaiting_delivery_confirm",
        "orders",
        ["shipped_at"],
        postgresql_where=sa.text("status = 'SHIPPED' AND delivered_at IS NULL"),
    )

    # ── order_shipping_details (ชั้น ข — ข้อมูลส่วนบุคคลทั้งตาราง) ──
    op.create_table(
        "order_shipping_details",
        sa.Column("order_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("recipient_name", sa.String(length=120), nullable=False),
        sa.Column("recipient_phone", sa.String(length=20), nullable=False),
        sa.Column("address_line", sa.Text(), nullable=False),
        sa.Column("sub_district", sa.String(length=80), nullable=True),
        sa.Column("district", sa.String(length=80), nullable=True),
        sa.Column("province", sa.String(length=80), nullable=False),
        sa.Column("postal_code", sa.String(length=10), nullable=False),
        _created_at(),
        sa.ForeignKeyConstraint(["order_id"], ["orders.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("order_id"),
    )

    # ── order_status_history ──
    op.create_table(
        "order_status_history",
        _uuid_pk(),
        sa.Column("order_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("from_status", sa.String(length=40), nullable=True),
        sa.Column("to_status", sa.String(length=40), nullable=False),
        sa.Column("actor_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        _created_at(),
        sa.ForeignKeyConstraint(["order_id"], ["orders.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["actor_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_order_status_history_order_created",
        "order_status_history",
        ["order_id", "created_at"],
    )

    # ── payments ──
    op.create_table(
        "payments",
        _uuid_pk(),
        sa.Column("order_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "status",
            postgresql.ENUM(name="payment_status", create_type=False),
            server_default="AWAITING",
            nullable=False,
        ),
        sa.Column("amount_expected", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("amount_claimed", sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column("claimed_transferred_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("slip_image_key", sa.Text(), nullable=True),
        sa.Column(
            "bank_statement_checked",
            sa.Boolean(),
            server_default="false",
            nullable=False,
        ),
        sa.Column("verified_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("rejection_reason", sa.Text(), nullable=True),
        _created_at(),
        _updated_at(),
        sa.CheckConstraint(
            "amount_expected > 0", name="ck_payments_amount_expected_positive"
        ),
        # 🔴 ADR-0029 D3 — ด่านที่สำคัญที่สุดของตารางนี้
        sa.CheckConstraint(
            "status <> 'VERIFIED' OR bank_statement_checked",
            name="ck_payments_verified_requires_bank_statement_checked",
        ),
        sa.CheckConstraint(
            "status <> 'REJECTED' OR rejection_reason IS NOT NULL",
            name="ck_payments_rejected_requires_reason",
        ),
        sa.CheckConstraint(
            "status NOT IN ('VERIFIED', 'REJECTED') OR verified_by IS NOT NULL",
            name="ck_payments_decided_requires_actor",
        ),
        sa.ForeignKeyConstraint(["order_id"], ["orders.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["verified_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_payments_admin_queue",
        "payments",
        ["claimed_transferred_at"],
        postgresql_where=sa.text("status = 'CLAIMED'"),
    )
    op.create_index(
        "uq_open_payment_per_order",
        "payments",
        ["order_id"],
        unique=True,
        postgresql_where=sa.text("status IN ('AWAITING', 'CLAIMED')"),
    )

    # ── disputes ──
    op.create_table(
        "disputes",
        sa.Column("order_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("opened_by", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("reason_code", sa.String(length=40), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("evidence_image_keys", postgresql.JSONB(), nullable=True),
        sa.Column(
            "status",
            postgresql.ENUM(name="dispute_status", create_type=False),
            server_default="OPEN",
            nullable=False,
        ),
        sa.Column("resolution_note", sa.Text(), nullable=True),
        sa.Column("resolved_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        _created_at(),
        _updated_at(),
        sa.CheckConstraint(
            "status = 'OPEN' OR resolution_note IS NOT NULL",
            name="ck_disputes_resolved_requires_note",
        ),
        sa.CheckConstraint(
            "status = 'OPEN' OR resolved_by IS NOT NULL",
            name="ck_disputes_resolved_requires_actor",
        ),
        sa.ForeignKeyConstraint(["order_id"], ["orders.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["opened_by"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["resolved_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("order_id"),
    )

    # ── reviews · favorites ──
    op.create_table(
        "reviews",
        sa.Column("order_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("reviewer_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("seller_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("rating", sa.SmallInteger(), nullable=False),
        sa.Column("comment", sa.Text(), nullable=True),
        _created_at(),
        sa.CheckConstraint("rating BETWEEN 1 AND 5", name="ck_reviews_rating_range"),
        sa.ForeignKeyConstraint(["order_id"], ["orders.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["reviewer_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["seller_id"], ["seller_profiles.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("order_id"),
    )
    op.create_index("ix_reviews_seller_created", "reviews", ["seller_id", "created_at"])

    op.create_table(
        "favorites",
        _uuid_pk(),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("poster_id", postgresql.UUID(as_uuid=True), nullable=False),
        _created_at(),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["poster_id"], ["posters.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "uq_favorite_user_poster", "favorites", ["user_id", "poster_id"], unique=True
    )

    # ── platform_settings · notification_outbox ──
    op.create_table(
        "platform_settings",
        sa.Column("key", sa.String(length=60), nullable=False),
        sa.Column("value", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("updated_by", postgresql.UUID(as_uuid=True), nullable=True),
        _created_at(),
        _updated_at(),
        sa.ForeignKeyConstraint(["updated_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("key"),
    )
    op.get_bind().execute(
        sa.text(
            "INSERT INTO platform_settings (key, value, description) "
            "VALUES (:key, :value, :description)"
        ),
        [{"key": k, "value": v, "description": d} for k, v, d in DEFAULT_SETTINGS],
    )
    print(f"  seed platform_settings → {len(DEFAULT_SETTINGS)} คีย์")

    op.create_table(
        "notification_outbox",
        _uuid_pk(),
        sa.Column(
            "channel",
            postgresql.ENUM(name="notification_channel", create_type=False),
            nullable=False,
        ),
        sa.Column("recipient_user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("template_key", sa.String(length=60), nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=True),
        sa.Column(
            "status",
            postgresql.ENUM(name="notification_status", create_type=False),
            server_default="PENDING",
            nullable=False,
        ),
        sa.Column("attempts", sa.Integer(), server_default="0", nullable=False),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column(
            "send_after",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        _created_at(),
        sa.ForeignKeyConstraint(
            ["recipient_user_id"], ["users.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_notification_outbox_pending",
        "notification_outbox",
        ["send_after"],
        postgresql_where=sa.text("status = 'PENDING'"),
    )


def downgrade() -> None:
    """Downgrade schema.

    🔴 **ลบประวัติธุรกรรมทั้งหมด** — `order_status_history` คือสิ่งเดียวที่ใช้ตัดสิน
    ข้อพิพาทย้อนหลังได้ และ `orders.item_*` คือหลักฐานว่าลูกค้าเห็นอะไรตอนกดซื้อ
    (BL-77) · **ห้ามรันบนฐานที่มีธุรกรรมจริงแม้แต่รายการเดียว**
    """
    op.drop_table("notification_outbox")
    op.drop_table("platform_settings")
    op.drop_index("uq_favorite_user_poster", table_name="favorites")
    op.drop_table("favorites")
    op.drop_index("ix_reviews_seller_created", table_name="reviews")
    op.drop_table("reviews")
    op.drop_table("disputes")
    op.drop_index("uq_open_payment_per_order", table_name="payments")
    op.drop_index("ix_payments_admin_queue", table_name="payments")
    op.drop_table("payments")
    op.drop_index(
        "ix_order_status_history_order_created", table_name="order_status_history"
    )
    op.drop_table("order_status_history")
    op.drop_table("order_shipping_details")
    for index_name in (
        "ix_orders_awaiting_delivery_confirm",
        "ix_orders_payout_queue",
        "ix_orders_seller_status",
        "ix_orders_buyer_created",
        "uq_live_order_per_poster",
    ):
        op.drop_index(index_name, table_name="orders")
    op.drop_table("orders")
    op.drop_table("addresses")
    op.drop_index("ix_payouts_seller_batch", table_name="payouts")
    op.drop_table("payouts")
