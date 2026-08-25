"""ADR-0029 — เงิน: การอ้างว่าโอน · ข้อพิพาท · รอบจ่ายผู้ขาย

🔴 **`payments` เก็บ "การอ้างว่าโอน" ไม่ใช่ charge ของ provider** (ADR-0029 D1/D6)
ไม่มี charge id ไม่มี webhook ไม่มีค่าธรรมเนียม — Omise ถูกเลื่อนไป Phase 2

🔴 **ห้ามมีคอลัมน์ข้อมูลบัตร (เลขบัตร · รหัสหลังบัตร · วันหมดอายุ) หรือเลขบัญชี
ผู้ซื้อ เด็ดขาด** (`database-design.md` §9 · ADR-0029 D6) · เลขบัญชีที่ปรากฏบนสลิป
**ห้ามถูกดึงออกมาเก็บเป็นคอลัมน์** — เก็บแค่ไฟล์ภาพภายใต้ ADR-0020

ด่านที่คุ้มข้อนี้คือ `tests/unit/test_no_card_data_in_schema.py`
🔴 **ไม่ใช่ `grep` อย่างที่ `database-design.md` §9 เขียนไว้เดิม** — grep บนโฟลเดอร์
`app/` จับ**ข้อความในคอมเมนต์ของตัวเอง**ติดมาด้วย (พิสูจน์แล้ว 2026-08-22: บล็อกนี้
ทำให้ grep แดงทั้งที่ไม่มีคอลัมน์ผิดสักตัว) ⇒ ด่านที่ดังเพราะเอกสารพูดถึงกฎ
คือด่านที่คนจะเรียนรู้ที่จะเพิกเฉย · เทสตัวจริงอ่าน **ชื่อคอลัมน์ใน `Base.metadata`**
ซึ่งเป็นสิ่งที่กฎข้อนี้พูดถึงจริง ๆ
"""

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
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
from app.models.base import TimestampMixin, uuid_pk
from app.models.enums import DisputeStatus, PaymentStatus, PayoutStatus

payment_status_enum = PgEnum(PaymentStatus, name="payment_status", create_type=False)
dispute_status_enum = PgEnum(DisputeStatus, name="dispute_status", create_type=False)
payout_status_enum = PgEnum(PayoutStatus, name="payout_status", create_type=False)


class Payment(Base, TimestampMixin):
    __tablename__ = "payments"
    __table_args__ = (
        CheckConstraint(
            "amount_expected > 0", name="ck_payments_amount_expected_positive"
        ),
        # 🔴 **ด่านที่สำคัญที่สุดในตารางนี้** (ADR-0029 D3)
        # ยืนยันเงินเข้าได้ต่อเมื่อแอดมิน**เห็นยอดในบัญชีจริง**แล้วเท่านั้น
        # สลิปปลอมทำง่ายกว่าที่คนส่วนใหญ่คิดมาก — ด่านนี้ต้องอยู่ในระบบ
        # **ไม่ใช่ในความมีวินัยของคน** จึงเป็น CHECK ระดับ DB ไม่ใช่ if ใน service
        CheckConstraint(
            "status <> 'VERIFIED' OR bank_statement_checked",
            name="ck_payments_verified_requires_bank_statement_checked",
        ),
        CheckConstraint(
            "status <> 'REJECTED' OR rejection_reason IS NOT NULL",
            name="ck_payments_rejected_requires_reason",
        ),
        # ยืนยัน/ปฏิเสธแล้วต้องรู้ว่าใครกด (แนวเดียวกับ ADR-0020 A4-D1)
        CheckConstraint(
            "status NOT IN ('VERIFIED', 'REJECTED') OR verified_by IS NOT NULL",
            name="ck_payments_decided_requires_actor",
        ),
        # คิวยืนยันสลิปของแอดมิน (SCR-15 AC-1) — เรียงตามรอนานสุดขึ้นก่อน
        Index(
            "ix_payments_admin_queue",
            "claimed_transferred_at",
            postgresql_where=text("status = 'CLAIMED'"),
        ),
        # 1 ออร์เดอร์มีการชำระที่ยังไม่จบได้ใบเดียว — กันสร้างซ้ำตอนกดแจ้งโอนรัว ๆ
        Index(
            "uq_open_payment_per_order",
            "order_id",
            unique=True,
            postgresql_where=text("status IN ('AWAITING', 'CLAIMED')"),
        ),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    order_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("orders.id", ondelete="CASCADE"), nullable=False
    )
    status: Mapped[PaymentStatus] = mapped_column(
        payment_status_enum,
        nullable=False,
        server_default=PaymentStatus.AWAITING.value,
    )
    # ยอดที่ต้องโอน = orders.total_amount ตอนสร้าง (snapshot — ADR-0029 D1 QR ยอดตายตัว)
    amount_expected: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    # ยอดที่ผู้ซื้อ**อ้าง**ว่าโอน · ต่างจาก amount_expected ได้ = สัญญาณให้แอดมินดูละเอียด
    amount_claimed: Mapped[Decimal | None] = mapped_column(
        Numeric(12, 2), nullable=True
    )
    claimed_transferred_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # 🔴 key ใน private storage เท่านั้น ห้ามเป็น URL ที่เปิดได้ (ADR-0029 D6 · ADR-0020)
    slip_image_key: Mapped[str | None] = mapped_column(Text, nullable=True)

    # 🔴 ADR-0029 D3 — แอดมินติ๊กว่า "เห็นยอดในบัญชีจริงแล้ว" ไม่ใช่ "เห็นภาพสลิปแล้ว"
    bank_statement_checked: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false"
    )
    verified_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    verified_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    rejection_reason: Mapped[str | None] = mapped_column(Text, nullable=True)


class Dispute(Base, TimestampMixin):
    """BR-P6 — เปิดแล้ว **เงินถูกอายัดทันที** (ตัดออร์เดอร์ออกจากคิวจ่าย)

    🔴 SOP การตัดสินยังเป็นข้อความใน BUSINESS_RULES ไม่ใช่ขั้นตอนที่ระบบบังคับ —
    เดือนแรกแอดมินตัดสินเอง · SOP ต้องเขียนเสร็จ **ก่อนเคสแรก ไม่ใช่ระหว่างเคสแรก**
    (SCR-16 known_gap)
    """

    __tablename__ = "disputes"
    __table_args__ = (
        CheckConstraint(
            "status = 'OPEN' OR resolution_note IS NOT NULL",
            name="ck_disputes_resolved_requires_note",
        ),
        CheckConstraint(
            "status = 'OPEN' OR resolved_by IS NOT NULL",
            name="ck_disputes_resolved_requires_actor",
        ),
    )

    # 1 ออร์เดอร์ = 1 เคส · เปิดซ้ำไม่ได้ (เปิดใหม่ = เคสเดิมที่ยังไม่จบ)
    order_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("orders.id", ondelete="RESTRICT"), primary_key=True
    )
    opened_by: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    reason_code: Mapped[str] = mapped_column(String(40), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    # 🔴 key ของรูปหลักฐาน ไม่ใช่ URL · ADR-0020 D9 ห้าม log เนื้อหาในนี้
    evidence_image_keys: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    status: Mapped[DisputeStatus] = mapped_column(
        dispute_status_enum, nullable=False, server_default=DisputeStatus.OPEN.value
    )
    resolution_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    resolved_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    resolved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class Payout(Base, TimestampMixin):
    """BR-P5 · ADR-0029 D7 — ระบบ **คำนวณยอดและทำคิว** · คนโอนเอง

    ความสัมพันธ์กับออร์เดอร์อยู่ที่ `orders.payout_id` — **ไม่มีตาราง join**
    (1 ออร์เดอร์อยู่ได้รอบเดียว · ไม่มี many-to-many ให้ต้องรองรับ)
    """

    __tablename__ = "payouts"
    __table_args__ = (
        CheckConstraint("amount >= 0", name="ck_payouts_amount_non_negative"),
        CheckConstraint(
            "status <> 'PAID' OR (paid_at IS NOT NULL AND paid_by IS NOT NULL)",
            name="ck_payouts_paid_requires_when_and_who",
        ),
        Index("ix_payouts_seller_batch", "seller_id", "batch_date"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    seller_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("seller_profiles.id", ondelete="RESTRICT"), nullable=False
    )
    # รอบอังคาร/ศุกร์ (BR-P5) — เก็บเป็นวันที่ของรอบ ไม่ใช่เวลาที่สคริปต์รัน
    batch_date: Mapped[date] = mapped_column(Date, nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    order_count: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[PayoutStatus] = mapped_column(
        payout_status_enum, nullable=False, server_default=PayoutStatus.QUEUED.value
    )
    # อ้างอิงการโอนจริงจากธนาคาร — ใช้ตรวจย้อนตอนผู้ขายทักว่าไม่ได้รับเงิน
    transfer_ref: Mapped[str | None] = mapped_column(String(80), nullable=True)
    paid_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    paid_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
