"""ADR-0028 D4 · ADR-0030 · ADR-0020 — คำสั่งซื้อ · ที่อยู่ · ร่องรอยการเปลี่ยนสถานะ

🔴 **แยกให้ชัด 3 ชั้นตาม ADR-0020 D5** (อ่านก่อนแตะไฟล์นี้ทุกครั้ง):

```
orders                    ← ชั้น ก  ไม่มีข้อมูลส่วนบุคคลเลยแม้แต่ฟิลด์เดียว
order_shipping_details    ← ชั้น ข  ข้อมูลส่วนบุคคลทั้งตาราง · ถูกลบเมื่อครบ 90 วัน
addresses                 ← ชั้น ค  สมุดที่อยู่ของผู้ใช้
```

**การล้าง = `DELETE FROM order_shipping_details` + stamp `orders.shipping_purged_at`**
🔴 **ห้าม `DELETE` แถว `orders` และห้ามล้างคอลัมน์ `item_*` เด็ดขาด** — ADR-0020
**Amendment 4 · A4-D2** อธิบายไว้ว่าทำเมื่อไหร่คือการทำลายหลักฐานที่ใช้ตัดสินข้อพิพาท

ADR-0030 D5 ตัด `order_items` ทิ้ง (1 ธุรกรรม = 1 ชิ้น) ⇒ 6 ฟิลด์ snapshot ของ BL-77
ย้ายขึ้นมาเป็นคอลัมน์ `item_*` บนตารางนี้ **ครบทั้ง 6 ไม่ลดสักฟิลด์** (A4-D2)
"""

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import ENUM as PgEnum
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.base import CreatedAtMixin, TimestampMixin, uuid_pk
from app.models.enums import (
    DeliveryConfirmActor,
    OrderStatus,
    PosterCondition,
    VerificationStatus,
)

order_status_enum = PgEnum(OrderStatus, name="order_status", create_type=False)
delivery_confirm_actor_enum = PgEnum(
    DeliveryConfirmActor, name="delivery_confirm_actor", create_type=False
)
poster_condition_enum = PgEnum(
    PosterCondition, name="poster_condition", create_type=False
)
verification_status_enum = PgEnum(
    VerificationStatus, name="verification_status", create_type=False
)

# สถานะที่ถือว่า "จบแล้ว" — ใช้ทั้งใน partial unique index และในตัวตัดสินของ service
# 🔴 ต้องตรงกับ WHERE ของ uq_live_order_per_poster ในไฟล์ migration เป๊ะ
TERMINAL_ORDER_STATUSES = ("COMPLETED", "CANCELLED", "REFUNDED")


class Address(Base, CreatedAtMixin):
    """ชั้น ค — สมุดที่อยู่ของผู้ใช้ (ADR-0020 D5)

    🔴 ที่อยู่ที่ใช้จริงในออร์เดอร์ถูก **คัดลอก** ไป `order_shipping_details`
    ไม่ใช่ FK มาที่นี่ — ผู้ใช้แก้/ลบที่อยู่ในสมุดได้ตลอด แต่ประวัติออร์เดอร์ต้องไม่เปลี่ยนตาม
    """

    __tablename__ = "addresses"

    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    recipient_name: Mapped[str] = mapped_column(String(120), nullable=False)
    recipient_phone: Mapped[str] = mapped_column(String(20), nullable=False)
    address_line: Mapped[str] = mapped_column(Text, nullable=False)
    sub_district: Mapped[str | None] = mapped_column(String(80), nullable=True)
    district: Mapped[str | None] = mapped_column(String(80), nullable=True)
    province: Mapped[str] = mapped_column(String(80), nullable=False)
    postal_code: Mapped[str] = mapped_column(String(10), nullable=False)
    is_default: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false"
    )


class Order(Base, TimestampMixin):
    """ชั้น ก — **ห้ามมีข้อมูลส่วนบุคคลในตารางนี้แม้แต่ฟิลด์เดียว** (ADR-0020 D5)"""

    __tablename__ = "orders"
    __table_args__ = (
        # 🔴 ชั้นที่ 3 ของการกันซื้อซ้อน ต่อจาก 2 ชั้นของ `reservations`
        # (row-lock + uq_active_reservation_per_poster — database-design.md §6)
        # ห้ามมีออร์เดอร์ที่ยังไม่จบมากกว่า 1 ใบต่อโปสเตอร์ 1 ใบ
        Index(
            "uq_live_order_per_poster",
            "poster_id",
            unique=True,
            postgresql_where=text(
                "status NOT IN ('COMPLETED', 'CANCELLED', 'REFUNDED')"
            ),
        ),
        Index("ix_orders_buyer_created", "buyer_id", "created_at"),
        Index("ix_orders_seller_status", "seller_id", "status"),
        # คิวจ่ายเงินอ่านจากตรงนี้ — ออร์เดอร์ที่ completed แล้วยังไม่เข้ารอบไหน
        Index(
            "ix_orders_payout_queue",
            "seller_id",
            postgresql_where=text("status = 'COMPLETED' AND payout_id IS NULL"),
        ),
        # ADR-0020 D14.3 — รายการ "ส่งแล้วรอยืนยัน" เรียงตามค้างนานสุด
        Index(
            "ix_orders_awaiting_delivery_confirm",
            "shipped_at",
            postgresql_where=text("status = 'SHIPPED' AND delivered_at IS NULL"),
        ),
        # 🔴 **ไม่มี CHECK "ผู้ซื้อ ≠ ผู้ขาย" ที่ระดับ DB — และนั่นคือข้อเท็จจริง ไม่ใช่การลืม**
        # ‹พบ 2026-08-22 จากเทสที่เขียนไว้ดักเอง · INF-32›
        # `buyer_id` ชี้ `users.id` ส่วน `seller_id` ชี้ `seller_profiles.id`
        # ⇒ CHECK `buyer_id <> seller_id` **ไม่มีทางเป็นเท็จ** เพราะเทียบ id ของคนละตาราง
        # เคยมี CHECK ชื่อนั้นอยู่จริงในร่างแรกและ **ผ่านทุกเทสโดยไม่เคยจับอะไรได้เลย**
        # ซึ่งอันตรายกว่าไม่มี เพราะอ่านแล้วเหมือนมีด่าน
        # → ด่านจริงต้องอยู่ที่ service (INF-33) ซึ่งรู้จัก `seller_profiles.user_id`
        #   **ห้ามอ้างว่ากฎนี้ครอบระดับ DB แล้ว** (ถ้อยคำเดียวกับ ADR-0027 D4)
        CheckConstraint("item_price >= 0", name="ck_orders_item_price_non_negative"),
        CheckConstraint(
            "shipping_fee >= 0", name="ck_orders_shipping_fee_non_negative"
        ),
        # BR-L7 — คอมมิชชั่นคิดจาก **ราคาสินค้าเท่านั้น ไม่คิดจากค่าส่ง**
        CheckConstraint(
            "total_amount = item_price + shipping_fee",
            name="ck_orders_total_is_item_plus_shipping",
        ),
        CheckConstraint(
            "seller_payout_amount = total_amount - commission_amount",
            name="ck_orders_payout_is_total_minus_commission",
        ),
        # ADR-0020 A4-D1 — ค่าที่คนกรอกต้องรู้ว่าใครกรอก · ทั้งคู่มีหรือไม่มีพร้อมกันเสมอ
        CheckConstraint(
            "(delivered_at IS NULL) = (delivered_confirmed_by IS NULL)",
            name="ck_orders_delivered_at_pairs_with_actor",
        ),
        # ยกเลิกแล้วต้องบอกได้ว่าทำไม (BR-P7 · ใช้ตัดสิน dispute ย้อนหลัง)
        CheckConstraint(
            "status NOT IN ('CANCELLED', 'REFUNDED') OR cancellation_reason IS NOT NULL",
            name="ck_orders_cancelled_requires_reason",
        ),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    # เลขที่คนอ่านออก ใช้คุยกับลูกค้า — `PN-YYMMDD-NNNN` (proposal §6 Q6)
    order_no: Mapped[str] = mapped_column(String(20), nullable=False, unique=True)

    # RESTRICT — ห้ามลบโปสเตอร์ที่เคยมีคนสั่งซื้อ (แนวเดียวกับ reservations)
    poster_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("posters.id", ondelete="RESTRICT"), nullable=False
    )
    buyer_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    # snapshot ผู้ขาย — listing เปลี่ยนมือได้ แต่ออร์เดอร์เก่าต้องรู้ว่าตอนนั้นขายโดยใคร
    seller_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("seller_profiles.id", ondelete="RESTRICT"), nullable=False
    )
    reservation_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("reservations.id", ondelete="RESTRICT"), nullable=True
    )

    status: Mapped[OrderStatus] = mapped_column(
        order_status_enum,
        nullable=False,
        server_default=OrderStatus.AWAITING_PAYMENT.value,
    )

    # --- เงิน · ทั้งหมดเป็น snapshot ตอนสร้าง ห้าม join ไปอ่านค่าปัจจุบัน (BR-L7) ---
    item_price: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    shipping_fee: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    total_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    # 🔴 อัตราที่ **ใช้จริงกับธุรกรรมนี้** — เปลี่ยน config ทีหลังห้ามกระทบแถวนี้
    commission_rate_bps: Mapped[int] = mapped_column(Integer, nullable=False)
    commission_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    seller_payout_amount: Mapped[Decimal] = mapped_column(
        Numeric(12, 2), nullable=False
    )

    # --- BL-77 snapshot 6 ฟิลด์ · ADR-0020 A4-D2 (ย้ายที่เก็บ หลักการไม่เปลี่ยน) ---
    # 🔴 คัดลอกตอนสร้างออร์เดอร์แล้ว **ไม่มีใครแก้อีกเลย** ตลอดอายุของแถว
    # เหตุผลหนักขึ้นใน marketplace: ของเป็นของคนอื่นซึ่ง**แก้ listing ตัวเองได้**
    # (SCR-13 AC-8) ⇒ ไม่ snapshot = ผู้ขายแก้หลักฐานหลังเกิดข้อพิพาทได้
    # 🔴 ห้ามพึ่ง poster_images.storage_key — ADR-0006 ให้ key เป็นของ *โปสเตอร์*
    # 🔴 `price` ของ BL-77 คือ `item_price` ในบล็อกเงินข้างบน — **ไม่มีคอลัมน์ซ้ำ**
    # (ค่าเดียวทำหน้าที่ทั้ง "ยอดที่เรียกเก็บ" และ "ราคาที่ลูกค้าเห็นตอนกดซื้อ"
    #  เพราะ 1 ธุรกรรม = 1 ชิ้น และไม่มีส่วนลดใน MVP — PHASE2 มีคูปองเมื่อไหร่ต้องแยก)
    item_title: Mapped[str] = mapped_column(String(255), nullable=False)
    item_condition_grade: Mapped[PosterCondition | None] = mapped_column(
        poster_condition_enum, nullable=True
    )
    item_image_urls: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    item_verification_status: Mapped[VerificationStatus | None] = mapped_column(
        verification_status_enum, nullable=True
    )
    item_reference_note: Mapped[str | None] = mapped_column(Text, nullable=True)

    # --- การส่งของ (BR-P3 · BR-P4) — ไม่ใช่ข้อมูลส่วนบุคคล จึงอยู่ชั้น ก ได้ ---
    carrier: Mapped[str | None] = mapped_column(String(80), nullable=True)
    tracking_no: Mapped[str | None] = mapped_column(String(80), nullable=True)
    shipped_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # BR-P3 — ผู้ขายต้องส่งภายใน 3 วันทำการหลังยืนยันเงิน · เลย = ยกเลิกอัตโนมัติ
    # 🔴 "วันทำการ" นับยังไงยังไม่ตัดสิน (INF-33 known_gap) — ตัวคำนวณต้องมีที่เดียว
    ship_by_due_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # BR-P4 — คำนวณตอนเข้า `SHIPPED` **แล้วเก็บลงแถว** ห้ามคำนวณสดตอนอ่าน
    # (ADR-0020 A4-D1) เพราะถ้าแก้ config ทีหลัง ออร์เดอร์ที่ส่งไปแล้วจะเปลี่ยน
    # กำหนดย้อนหลัง = เปลี่ยนสัญญาที่ให้ไว้กับผู้ใช้หลังจากที่เขาตกลงไปแล้ว
    auto_confirm_due_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # --- ADR-0020 D12.2 · A4-D1 — ต้องมีตั้งแต่ migration แรก ---
    # จุดเริ่มนับ 90 วันของการล้างชั้น ข · NULL = ยังไม่มีใครยืนยันว่าของถึง
    delivered_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    delivered_confirmed_by: Mapped[DeliveryConfirmActor | None] = mapped_column(
        delivery_confirm_actor_enum, nullable=True
    )
    # NULL = ยังไม่ล้าง · มีค่า = ล้างแล้วเมื่อไหร่ (ADR-0020 D5)
    shipping_purged_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # BR-P5 — อยู่ในรอบจ่ายไหน · NULL = ยังไม่เข้ารอบ
    payout_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("payouts.id", ondelete="SET NULL"), nullable=True
    )

    paid_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    cancelled_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    cancellation_reason: Mapped[str | None] = mapped_column(Text, nullable=True)


class OrderShippingDetail(Base, CreatedAtMixin):
    """ชั้น ข — **ข้อมูลส่วนบุคคลทั้งตาราง** (ADR-0020 D5 · D12.1)

    🔴 **ห้ามยุบเป็นคอลัมน์ใน `orders`** — เหตุผล 3 ข้อของ D5:
    1. คอลัมน์ใน `orders` ต้อง nullable ทั้งหมดเพื่อรองรับการล้าง ⇒ เสีย `NOT NULL` ถาวร
    2. **"ล้างแล้ว" กับ "ไม่เคยกรอก" หน้าตาเหมือนกันเป๊ะ** ถ้าเป็น NULL ในคอลัมน์เดียวกัน
       — ตอนสอบสวนข้อพิพาทมันคือคนละเรื่องกันคนละโลก
    3. เป็นขอบเขตเดียวให้จำกัดสิทธิ์การเข้าถึง (D8)
    """

    __tablename__ = "order_shipping_details"

    order_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("orders.id", ondelete="CASCADE"), primary_key=True
    )
    recipient_name: Mapped[str] = mapped_column(String(120), nullable=False)
    recipient_phone: Mapped[str] = mapped_column(String(20), nullable=False)
    address_line: Mapped[str] = mapped_column(Text, nullable=False)
    sub_district: Mapped[str | None] = mapped_column(String(80), nullable=True)
    district: Mapped[str | None] = mapped_column(String(80), nullable=True)
    province: Mapped[str] = mapped_column(String(80), nullable=False)
    postal_code: Mapped[str] = mapped_column(String(10), nullable=False)


class OrderStatusHistory(Base, CreatedAtMixin):
    """INF-33 AC-2/AC-3 — ร่องรอยที่ใช้ตัดสิน dispute

    🔴 **เขียนโดย transition function ที่เดียวเท่านั้น** — ห้ามมี
    `UPDATE orders SET status = ...` ที่อื่นในโค้ดเลย · มีเทสสแกน AST ทั้ง repo คุ้มอยู่
    (precedent: `tests/unit/test_release_date_invariant.py`)

    `actor_user_id` เป็น NULL แปลว่า **ระบบเปลี่ยนเอง** (scheduler) ไม่ใช่ "ไม่รู้ว่าใคร"
    """

    __tablename__ = "order_status_history"
    __table_args__ = (
        Index("ix_order_status_history_order_created", "order_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    order_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("orders.id", ondelete="CASCADE"), nullable=False
    )
    # เก็บเป็นข้อความไม่ใช่ enum — ประวัติต้องอ่านได้ต่อไปแม้ enum จะเปลี่ยนค่าในอนาคต
    from_status: Mapped[str | None] = mapped_column(String(40), nullable=True)
    to_status: Mapped[str] = mapped_column(String(40), nullable=False)
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
