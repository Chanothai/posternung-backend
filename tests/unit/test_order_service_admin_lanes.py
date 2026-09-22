"""เส้นแอดมิน — `verify_payment()` · `reject_payment()` (INF-41 สไลซ์ B ·
ADR-0033 Amendment 2) · `ship_order()` · `complete_order()` (สไลซ์ A)

🔴 **ทุกเทสในไฟล์นี้ให้ service เป็นคนสร้างสถานะของ `orders`/`posters` ไม่จัดฉาก
`status` ด้วยมือ** (`test-quality` §3.1) — ยกเว้นแถว `payments` ซึ่ง**ยังไม่มี service
ที่ INSERT** ในรอบนี้ (ADR-0033 D7) จึงจัดฉากตรงได้ (`_a_claimed_payment()`) เพราะ
ไม่ใช่สิ่งที่ฟังก์ชันที่ทดสอบต้องพิสูจน์ว่าสร้างถูก — มันแค่ต้อง *หา* แถวนั้นเจอ

fixture/helper ที่ใช้ร่วมกับ `test_order_service.py` **import มา ไม่ก๊อป**
(`_a_seller` · `_a_listing` · `_a_user` · `_reserve_and_order` · `_an_address` · `NOW`
· `PUBLISHED_AT`) — ทรงเดียวกับ `tests/unit/test_manual_entry_child_poster_publish_gate.py`
ที่ import ข้ามไฟล์เทสอยู่แล้ว
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import (
    BankStatementNotChecked,
    OrderTransitionNotAllowed,
    PaymentNotClaimed,
    PaymentRejectionReasonRequired,
    TrackingNoRequired,
)
from app.models.enums import (
    DeliveryConfirmActor,
    OrderStatus,
    PaymentStatus,
    PosterStatus,
    ReservationStatus,
)
from app.models.order import Order, OrderStatusHistory
from app.models.payment import Payment
from app.models.platform import NotificationOutbox, PlatformSetting
from app.models.poster import Poster
from app.models.poster_attribute_review import PosterAttributeReview
from app.models.reservation import Reservation
from app.models.seller import SellerProfile
from app.models.user import User
from app.services import order_service
from tests.unit.test_order_service import (
    NOW,
    _a_listing,
    _a_seller,
    _a_user,
    _an_address,
    _reserve_and_order,
    _sold_audit_rows,
)

_ORDER_PATH = (
    OrderStatus.PAYMENT_REVIEW,
    OrderStatus.AWAITING_SHIPMENT,
    OrderStatus.SHIPPED,
    OrderStatus.COMPLETED,
)


async def _an_admin(session: AsyncSession) -> User:
    admin = User(
        email=f"admin-{uuid.uuid4().hex[:8]}@example.test",
        is_verified=True,
        is_admin=True,
    )
    session.add(admin)
    await session.flush()
    return admin


async def _advance_order(
    session: AsyncSession,
    order: Order,
    *,
    actor: User,
    to: OrderStatus,
    at: datetime = NOW,
) -> None:
    """เดิน order ทีละก้าวผ่าน `apply_order_transition()` จนถึง `to` (รวมค่านั้น)

    ต่างจาก `_walk_order_to` ของ `test_order_service.py` ตรงที่รองรับปลายทางกลางทาง
    (`PAYMENT_REVIEW` / `AWAITING_SHIPMENT`) ไม่ใช่แค่สถานะจบ — ใช้เตรียมออร์เดอร์ให้
    อยู่ในสถานะที่เส้นแอดมินของ INF-41 ต้องการก่อนเรียกฟังก์ชันที่ทดสอบจริง
    """
    for step in _ORDER_PATH:
        await order_service.apply_order_transition(
            session,
            order.id,
            to_status=step,
            actor_user_id=actor.id,
            reason=None,
            at=at,
        )
        if step is to:
            return


async def _a_claimed_payment(
    session: AsyncSession, order: Order, *, at: datetime = NOW
) -> Payment:
    """แถว `payments` ที่ `status=CLAIMED` — จัดฉากตรง (ดู docstring หัวไฟล์)"""
    payment = Payment(
        order_id=order.id,
        status=PaymentStatus.CLAIMED,
        amount_expected=order.total_amount,
        amount_claimed=order.total_amount,
        claimed_transferred_at=at,
        bank_statement_checked=False,
    )
    session.add(payment)
    await session.flush()
    return payment


async def _history_rows(
    session: AsyncSession, order_id: uuid.UUID
) -> list[OrderStatusHistory]:
    result = await session.execute(
        select(OrderStatusHistory)
        .where(OrderStatusHistory.order_id == order_id)
        .order_by(OrderStatusHistory.created_at)
    )
    return list(result.scalars().all())


async def _outbox_templates_for(session: AsyncSession, user_id: uuid.UUID) -> list[str]:
    rows = await session.execute(
        select(NotificationOutbox.template_key).where(
            NotificationOutbox.recipient_user_id == user_id
        )
    )
    return sorted(rows.scalars().all())


async def _setting_int(session: AsyncSession, key: str) -> int:
    setting = await session.get(PlatformSetting, key)
    assert setting is not None, f"migration ต้องใส่คีย์ {key} มาแล้ว"
    return int(setting.value)


async def _set_setting(session: AsyncSession, key: str, value: str) -> None:
    setting = await session.get(PlatformSetting, key)
    assert setting is not None
    setting.value = value
    await session.flush()


# ══════════════════════════════════════════════════════════════════════════
# verify_payment() — เส้นที่ 1
# ══════════════════════════════════════════════════════════════════════════


async def test_verifying_payment_moves_the_order_and_writes_the_payment_fields(
    db_session: AsyncSession,
) -> None:
    seller = await _a_seller(db_session)
    poster = await _a_listing(db_session, seller)
    buyer = await _a_user(db_session, "buyer")
    admin = await _an_admin(db_session)
    order = await _reserve_and_order(db_session, poster, buyer)
    await _advance_order(db_session, order, actor=buyer, to=OrderStatus.PAYMENT_REVIEW)
    payment = await _a_claimed_payment(db_session, order)

    result = await order_service.verify_payment(
        db_session,
        order.id,
        actor_user_id=admin.id,
        bank_statement_checked=True,
        at=NOW,
    )

    assert result.status is OrderStatus.AWAITING_SHIPMENT
    assert payment.status is PaymentStatus.VERIFIED
    assert payment.bank_statement_checked is True
    assert payment.verified_by == admin.id
    assert payment.verified_at == NOW

    history = await _history_rows(db_session, order.id)
    last = history[-1]
    assert last.to_status == OrderStatus.AWAITING_SHIPMENT.value
    assert last.actor_user_id == admin.id
    assert last.reason == "payment verified against bank statement"

    assert "order_awaiting_shipment_buyer" in await _outbox_templates_for(
        db_session, buyer.id
    )
    assert "order_awaiting_shipment_seller" in await _outbox_templates_for(
        db_session, seller.user_id
    )


async def test_verifying_payment_without_the_flag_is_rejected_before_any_write(
    db_session: AsyncSession,
) -> None:
    """SCR-15 AC-3 — ปฏิเสธก่อนล็อก/flush ใด ๆ · assert ชนิด exception เป๊ะ ไม่ใช่
    `IntegrityError` ของ `ck_payments_verified_requires_bank_statement_checked`
    """
    seller = await _a_seller(db_session)
    poster = await _a_listing(db_session, seller)
    buyer = await _a_user(db_session, "buyer")
    admin = await _an_admin(db_session)
    order = await _reserve_and_order(db_session, poster, buyer)
    await _advance_order(db_session, order, actor=buyer, to=OrderStatus.PAYMENT_REVIEW)
    payment = await _a_claimed_payment(db_session, order)

    history_before = len(await _history_rows(db_session, order.id))

    with pytest.raises(BankStatementNotChecked):
        await order_service.verify_payment(
            db_session,
            order.id,
            actor_user_id=admin.id,
            bank_statement_checked=False,
            at=NOW,
        )

    assert order.status is OrderStatus.PAYMENT_REVIEW
    assert payment.status is PaymentStatus.CLAIMED
    assert len(await _history_rows(db_session, order.id)) == history_before


async def test_verifying_payment_without_a_claimed_row_is_rejected(
    db_session: AsyncSession,
) -> None:
    seller = await _a_seller(db_session)
    poster = await _a_listing(db_session, seller)
    buyer = await _a_user(db_session, "buyer")
    admin = await _an_admin(db_session)
    order = await _reserve_and_order(db_session, poster, buyer)
    await _advance_order(db_session, order, actor=buyer, to=OrderStatus.PAYMENT_REVIEW)
    # ไม่มี payment แถวไหนเลย

    with pytest.raises(PaymentNotClaimed):
        await order_service.verify_payment(
            db_session,
            order.id,
            actor_user_id=admin.id,
            bank_statement_checked=True,
            at=NOW,
        )

    assert order.status is OrderStatus.PAYMENT_REVIEW


async def test_verifying_payment_rolls_back_both_the_payment_and_the_order_together(
    db_session: AsyncSession,
) -> None:
    """AC-2 — ทรานแซกชันเดียว: rollback แล้วหายทั้งคู่ ไม่ใช่แค่ตัวใดตัวหนึ่ง

    🔴 **ใช้ SAVEPOINT (`begin_nested()`) จริง** — รอบก่อนวินิจฉัยผิดว่า
    `MissingGreenlet` มาจาก SAVEPOINT ที่ครอบคำสั่งซึ่งมี `SELECT ... FOR UPDATE`
    (ไม่ใช่) **สาเหตุจริงคือแตะ attribute ของ ORM object ที่ถูก expire หลัง
    rollback** — ตัวที่ระเบิดจริงในการทดลองรอบแรกคือ `order.status` (attribute ที่
    expire แล้วถูกอ่านแบบ sync บน object ที่ต้อง reload — ชนกับ async greenlet)
    ไม่ใช่ id ซึ่งถูกเก็บเป็นตัวแปรธรรมดาไว้ก่อน rollback อยู่แล้ว ⇒ กติกา: **เก็บ id
    ไว้ก่อน rollback แล้ว query ใหม่ทุกแถวหลัง rollback ห้ามอ่าน attribute ของ object
    เดิมอีกเลย** (ยืนยันด้วย `code-critic` รอบ 1 — scenario query ใหม่ผ่าน · scenario
    แตะ `order.status` ระเบิด · ถ้อยคำนี้แก้หลัง critic รอบ 2 Low-1)

    `begin_nested()` (ต่างจาก `db_session.rollback()` เปล่า) ทำให้ rollback
    ครอบ**เฉพาะการเขียนของ `verify_payment()`** ไม่ล้าง seller/poster/buyer/order/
    payment ที่ fixture สร้างไว้ก่อนหน้า ⇒ พิสูจน์ได้ตรงตามชื่อเทส: แถวยังอยู่
    แต่ค่ากลับไปเป็นค่าก่อนเรียก (`PAYMENT_REVIEW`/`CLAIMED`) ไม่ใช่หายไปทั้งแถว
    """
    seller = await _a_seller(db_session)
    poster = await _a_listing(db_session, seller)
    buyer = await _a_user(db_session, "buyer")
    admin = await _an_admin(db_session)
    order = await _reserve_and_order(db_session, poster, buyer)
    await _advance_order(db_session, order, actor=buyer, to=OrderStatus.PAYMENT_REVIEW)
    payment = await _a_claimed_payment(db_session, order)
    order_id, payment_id = order.id, payment.id  # เก็บก่อน rollback เสมอ

    async with db_session.begin_nested() as sp:
        await order_service.verify_payment(
            db_session,
            order_id,
            actor_user_id=admin.id,
            bank_statement_checked=True,
            at=NOW,
        )
        await sp.rollback()

    # ห้ามอ่าน order.status / payment.status ต่อจากนี้ — object เดิมถูก expire แล้ว
    refreshed_order = await db_session.scalar(select(Order).where(Order.id == order_id))
    refreshed_payment = await db_session.scalar(
        select(Payment).where(Payment.id == payment_id)
    )
    assert refreshed_order.status is OrderStatus.PAYMENT_REVIEW
    assert refreshed_payment.status is PaymentStatus.CLAIMED
    assert refreshed_payment.verified_by is None
    assert refreshed_payment.verified_at is None


async def test_verifying_payment_twice_is_rejected_the_second_time(
    db_session: AsyncSession,
) -> None:
    """idempotency — มติเจ้าของ GATE 1: *"reject/verify/ship/complete รันซ้ำ →
    OrderTransitionNotAllowed ทุกเส้น"* — `_lock_order_and_check_transition()`
    เช็คด้วย `is_order_transition_allowed()` **ก่อน**หา payment เสมอ (order ขยับไป
    `AWAITING_SHIPMENT` แล้วตั้งแต่รอบแรก ไม่ใช่ `PAYMENT_REVIEW` อีกต่อไป) ⇒ ไม่มี
    ทางไปถึงจุดที่หา payment ไม่เจอเลย
    """
    seller = await _a_seller(db_session)
    poster = await _a_listing(db_session, seller)
    buyer = await _a_user(db_session, "buyer")
    admin = await _an_admin(db_session)
    order = await _reserve_and_order(db_session, poster, buyer)
    await _advance_order(db_session, order, actor=buyer, to=OrderStatus.PAYMENT_REVIEW)
    await _a_claimed_payment(db_session, order)

    await order_service.verify_payment(
        db_session,
        order.id,
        actor_user_id=admin.id,
        bank_statement_checked=True,
        at=NOW,
    )

    with pytest.raises(OrderTransitionNotAllowed):
        await order_service.verify_payment(
            db_session,
            order.id,
            actor_user_id=admin.id,
            bank_statement_checked=True,
            at=NOW,
        )


# ══════════════════════════════════════════════════════════════════════════
# reject_payment() — เส้นที่ 2 (ADR-0033 Amendment 2 · A2-D1)
# ══════════════════════════════════════════════════════════════════════════


async def _rejectable_order(
    db_session: AsyncSession, *, ttl_minutes: int | None = None
) -> tuple[Order, Reservation]:
    """seller/poster/buyer/order ที่อยู่ `PAYMENT_REVIEW` พร้อมแถว payment `CLAIMED`
    — ตัวช่วยกลางของทุกเทส `reject_payment()` ในไฟล์นี้ · `ttl_minutes=None` = ปล่อย
    ตาม config ปกติ · ใส่ตัวเลขเพื่อบังคับ `reservation.expires_at` ให้เป็นอดีต
    (เทส "TTL เหลือ/หมด ผลเท่ากันเป๊ะ" — A2-D1)
    """
    seller = await _a_seller(db_session)
    poster = await _a_listing(db_session, seller)
    buyer = await _a_user(db_session, "buyer")
    order = await _reserve_and_order(db_session, poster, buyer)
    await _advance_order(db_session, order, actor=buyer, to=OrderStatus.PAYMENT_REVIEW)
    await _a_claimed_payment(db_session, order)

    reservation = await db_session.get(Reservation, order.reservation_id)
    assert reservation is not None
    if ttl_minutes is not None:
        reservation.expires_at = NOW + timedelta(minutes=ttl_minutes)
        await db_session.flush()
    return order, reservation


@pytest.mark.parametrize(
    "ttl_minutes", [60, -60], ids=["ttl_still_open", "ttl_expired"]
)
async def test_rejecting_payment_cancels_order_releases_listing_and_writes_payment_fields(
    db_session: AsyncSession, ttl_minutes: int
) -> None:
    """happy path — ครอบทั้งสองกรณี TTL เหลือ/หมด **ในเทสเดียวกัน** (parametrize)
    เพราะ A2-D1 บังคับว่าผลต้องเหมือนกันเป๊ะทุกฟิลด์ไม่ว่า TTL จะเหลือแค่ไหน
    (reservation ถูก `converted` ไปแล้วตั้งแต่สร้างออร์เดอร์ — ไม่มีนาฬิกาให้พึ่ง)
    """
    order, reservation = await _rejectable_order(db_session, ttl_minutes=ttl_minutes)
    admin = await _an_admin(db_session)
    payment = (
        await db_session.scalars(select(Payment).where(Payment.order_id == order.id))
    ).one()

    result = await order_service.reject_payment(
        db_session,
        order.id,
        actor_user_id=admin.id,
        reason="ลูกค้าโอนยอดไม่ตรง ติดต่อไม่ได้",
        at=NOW,
    )

    assert result.status is OrderStatus.CANCELLED
    assert result.cancellation_reason == "ลูกค้าโอนยอดไม่ตรง ติดต่อไม่ได้"

    assert payment.status is PaymentStatus.REJECTED
    assert payment.rejection_reason == "ลูกค้าโอนยอดไม่ตรง ติดต่อไม่ได้"
    assert payment.verified_by == admin.id  # "ผู้ตัดสิน" ไม่ใช่แค่กรณี VERIFIED
    assert payment.verified_at == NOW

    poster = await db_session.get(Poster, result.poster_id)
    assert poster.status is PosterStatus.available

    # reservation ไม่แตะเลย — ยังคง converted ไม่ว่า TTL จะเหลือหรือหมด (ข้อ 4)
    assert reservation.status is ReservationStatus.converted

    history = await _history_rows(db_session, order.id)
    last = history[-1]
    assert last.to_status == OrderStatus.CANCELLED.value
    assert last.actor_user_id == admin.id
    assert last.reason == "ลูกค้าโอนยอดไม่ตรง ติดต่อไม่ได้"

    # 🔴 `code-critic` รอบ 1 Medium-1 — A2-D1 ข้อ 3 บังคับว่า reason ของ
    # apply_listing_transition() ต้องบอกว่ามาจาก "ปฏิเสธสลิป" ไม่ใช่ข้อความของ
    # เส้น lazy-expire ("reservation expired") — มิวเทตส่ง reason="reservation
    # expired" เข้าไปแทนเคยรอด 21/21 เพราะไม่มีเทสอ่าน poster_attribute_reviews
    # ของฝั่ง listing เลย
    # 🔴 `created_at` ของแถวที่เกิดในทรานแซกชันเดียวกันเท่ากันเป๊ะ (server_default
    # now()) — เรียง desc() แล้ว limit(1) เจอแถวผิดได้ (พบจริงตอนเขียน: ได้แถว
    # "buyer reserved the listing" ของ `reserve_listing()` แทน) กรองด้วย
    # `value_after == "available"` แทน ซึ่งมีผู้เขียนเดียวในเทสนี้คือ reject_payment()
    listing_review = (
        await db_session.scalars(
            select(PosterAttributeReview).where(
                PosterAttributeReview.poster_id == poster.id,
                PosterAttributeReview.field == "status",
                PosterAttributeReview.value_after == "available",
            )
        )
    ).one()
    assert "rejected" in listing_review.reason.lower()
    assert listing_review.reason != "reservation expired"
    assert listing_review.reviewed_by == str(admin.id)

    seller = await db_session.get(SellerProfile, poster.seller_id)
    assert "order_cancelled_buyer" in await _outbox_templates_for(
        db_session, order.buyer_id
    )
    assert "listing_available_seller" in await _outbox_templates_for(
        db_session, seller.user_id
    )


async def test_a_different_buyer_can_reserve_and_order_after_a_rejection(
    db_session: AsyncSession,
) -> None:
    """🔴 A2-D1 — ไม่ใช่แค่ reserve ได้ ต้อง **`create_order()` สำเร็จจริง** ด้วย
    (การพิสูจน์แค่ reserve เคยพลาดจับ orphan ของ A1-D1 ไม่ได้ — ดู ADR-0033
    Amendment 2 §ทำไม A1-D1 ทำตามตัวอักษรไม่ได้ ข้อ 2)
    """
    order, _reservation = await _rejectable_order(db_session)
    admin = await _an_admin(db_session)
    await order_service.reject_payment(
        db_session,
        order.id,
        actor_user_id=admin.id,
        reason="ติดต่อผู้ซื้อไม่ได้",
        at=NOW,
    )

    other_buyer = await _a_user(db_session, "other-buyer")
    reservation, created = await order_service.reserve_listing(
        db_session, order.poster_id, buyer_user_id=other_buyer.id, at=NOW
    )
    assert created is True

    new_order = await order_service.create_order(
        db_session,
        reservation.id,
        buyer_user_id=other_buyer.id,
        shipping_address=_an_address(),
        at=NOW,
    )
    assert new_order.id != order.id
    assert new_order.buyer_id == other_buyer.id


async def test_the_same_buyer_can_reserve_again_after_a_rejection(
    db_session: AsyncSession,
) -> None:
    order, _reservation = await _rejectable_order(db_session)
    admin = await _an_admin(db_session)
    await order_service.reject_payment(
        db_session,
        order.id,
        actor_user_id=admin.id,
        reason="ติดต่อผู้ซื้อไม่ได้",
        at=NOW,
    )

    new_reservation, created = await order_service.reserve_listing(
        db_session, order.poster_id, buyer_user_id=order.buyer_id, at=NOW
    )
    assert created is True
    assert new_reservation.id != order.reservation_id


@pytest.mark.parametrize("blank", ["", "   "])
async def test_rejecting_payment_without_a_reason_is_refused_before_any_write(
    db_session: AsyncSession, blank: str
) -> None:
    order, reservation = await _rejectable_order(db_session)
    admin = await _an_admin(db_session)
    history_before = len(await _history_rows(db_session, order.id))

    with pytest.raises(PaymentRejectionReasonRequired):
        await order_service.reject_payment(
            db_session, order.id, actor_user_id=admin.id, reason=blank, at=NOW
        )

    assert order.status is OrderStatus.PAYMENT_REVIEW
    assert reservation.status is ReservationStatus.converted
    assert len(await _history_rows(db_session, order.id)) == history_before


async def test_rejecting_payment_without_a_claimed_row_is_rejected(
    db_session: AsyncSession,
) -> None:
    seller = await _a_seller(db_session)
    poster = await _a_listing(db_session, seller)
    buyer = await _a_user(db_session, "buyer")
    admin = await _an_admin(db_session)
    order = await _reserve_and_order(db_session, poster, buyer)
    await _advance_order(db_session, order, actor=buyer, to=OrderStatus.PAYMENT_REVIEW)
    # ไม่มี payment แถวไหนเลย

    with pytest.raises(PaymentNotClaimed):
        await order_service.reject_payment(
            db_session, order.id, actor_user_id=admin.id, reason="เหตุผล", at=NOW
        )

    assert order.status is OrderStatus.PAYMENT_REVIEW


async def test_rejecting_payment_twice_is_rejected_by_the_gate(
    db_session: AsyncSession,
) -> None:
    """idempotency — order เป็น `CANCELLED` แล้ว (สถานะจบ) รันซ้ำต้องได้
    `OrderTransitionNotAllowed` จาก `_lock_order_and_check_transition()` — ไม่มีทาง
    ไปถึงจุดที่หา payment เพราะเช็คนี้มาก่อนเสมอ
    """
    order, _reservation = await _rejectable_order(db_session)
    admin = await _an_admin(db_session)
    await order_service.reject_payment(
        db_session, order.id, actor_user_id=admin.id, reason="เหตุผลแรก", at=NOW
    )

    with pytest.raises(OrderTransitionNotAllowed):
        await order_service.reject_payment(
            db_session, order.id, actor_user_id=admin.id, reason="เหตุผลที่สอง", at=NOW
        )


async def test_rejecting_payment_rolls_back_all_three_tables_together(
    db_session: AsyncSession,
) -> None:
    """AC-3 — ทรานแซกชันเดียวครอบ `payments`/`orders`/`posters` ทั้งสามตาราง

    ทรงเดียวกับ `test_verifying_payment_rolls_back_both_the_payment_and_the_order_together`
    — SAVEPOINT จริง (`begin_nested()`) + เก็บ id ไว้ก่อน rollback + query ใหม่
    ทุกแถวหลัง rollback (ห้ามอ่าน attribute ของ object เดิมที่ถูก expire แล้ว —
    นั่นคือสาเหตุจริงของ `MissingGreenlet` รอบก่อน ไม่ใช่ SAVEPOINT/`FOR UPDATE`)
    ⇒ พิสูจน์ว่าทั้งสามตารางกลับเป็นค่าก่อนเรียก ไม่ใช่แค่ "หายไปทั้งแถว"
    """
    order, reservation = await _rejectable_order(db_session)
    admin = await _an_admin(db_session)
    payment = (
        await db_session.scalars(select(Payment).where(Payment.order_id == order.id))
    ).one()
    order_id = order.id
    payment_id = payment.id
    poster_id = order.poster_id
    reservation_id = reservation.id

    async with db_session.begin_nested() as sp:
        await order_service.reject_payment(
            db_session, order_id, actor_user_id=admin.id, reason="เหตุผล", at=NOW
        )
        await sp.rollback()

    refreshed_order = await db_session.scalar(select(Order).where(Order.id == order_id))
    refreshed_payment = await db_session.scalar(
        select(Payment).where(Payment.id == payment_id)
    )
    refreshed_poster = await db_session.scalar(
        select(Poster).where(Poster.id == poster_id)
    )
    refreshed_reservation = await db_session.scalar(
        select(Reservation).where(Reservation.id == reservation_id)
    )
    assert refreshed_order.status is OrderStatus.PAYMENT_REVIEW
    assert refreshed_payment.status is PaymentStatus.CLAIMED
    assert refreshed_poster.status is PosterStatus.reserved
    assert (
        refreshed_reservation.status is ReservationStatus.converted
    )  # ไม่เคยถูกแตะเลย


# ══════════════════════════════════════════════════════════════════════════
# ship_order() — เส้นที่ 3
# ══════════════════════════════════════════════════════════════════════════


async def test_shipping_writes_tracking_fields_and_starts_the_inspection_clock(
    db_session: AsyncSession,
) -> None:
    seller = await _a_seller(db_session)
    poster = await _a_listing(db_session, seller)
    buyer = await _a_user(db_session, "buyer")
    admin = await _an_admin(db_session)
    order = await _reserve_and_order(db_session, poster, buyer)
    await _advance_order(
        db_session, order, actor=buyer, to=OrderStatus.AWAITING_SHIPMENT
    )

    inspection_days = await _setting_int(db_session, "inspection_period_days")

    result = await order_service.ship_order(
        db_session,
        order.id,
        actor_user_id=admin.id,
        tracking_no="TH1234567890",
        carrier="Kerry",
        at=NOW,
    )

    assert result.status is OrderStatus.SHIPPED
    assert result.tracking_no == "TH1234567890"
    assert result.carrier == "Kerry"
    assert result.shipped_at == NOW
    assert result.auto_confirm_due_at == NOW + timedelta(days=inspection_days)

    history = await _history_rows(db_session, order.id)
    last = history[-1]
    assert last.actor_user_id == admin.id
    assert last.actor_user_id != seller.user_id
    assert last.reason == "shipped by admin on behalf of seller"


async def test_the_inspection_window_comes_from_platform_settings_not_a_hardcoded_number(
    db_session: AsyncSession,
) -> None:
    """🔴 ห้าม hardcode 7 — เปลี่ยน config เป็น 3 แล้วผลต้องตาม (ADR-0020 A4-D1)"""
    seller = await _a_seller(db_session)
    poster = await _a_listing(db_session, seller)
    buyer = await _a_user(db_session, "buyer")
    admin = await _an_admin(db_session)
    order = await _reserve_and_order(db_session, poster, buyer)
    await _advance_order(
        db_session, order, actor=buyer, to=OrderStatus.AWAITING_SHIPMENT
    )
    await _set_setting(db_session, "inspection_period_days", "3")

    result = await order_service.ship_order(
        db_session,
        order.id,
        actor_user_id=admin.id,
        tracking_no="TH1234567890",
        carrier=None,
        at=NOW,
    )

    assert result.auto_confirm_due_at == NOW + timedelta(days=3)


@pytest.mark.parametrize("blank", ["", "   "])
async def test_shipping_without_a_tracking_number_is_rejected_before_any_write(
    db_session: AsyncSession, blank: str
) -> None:
    seller = await _a_seller(db_session)
    poster = await _a_listing(db_session, seller)
    buyer = await _a_user(db_session, "buyer")
    admin = await _an_admin(db_session)
    order = await _reserve_and_order(db_session, poster, buyer)
    await _advance_order(
        db_session, order, actor=buyer, to=OrderStatus.AWAITING_SHIPMENT
    )

    with pytest.raises(TrackingNoRequired):
        await order_service.ship_order(
            db_session,
            order.id,
            actor_user_id=admin.id,
            tracking_no=blank,
            carrier=None,
            at=NOW,
        )

    assert order.status is OrderStatus.AWAITING_SHIPMENT
    assert order.tracking_no is None


async def test_shipping_twice_is_rejected_by_the_gate(db_session: AsyncSession) -> None:
    seller = await _a_seller(db_session)
    poster = await _a_listing(db_session, seller)
    buyer = await _a_user(db_session, "buyer")
    admin = await _an_admin(db_session)
    order = await _reserve_and_order(db_session, poster, buyer)
    await _advance_order(
        db_session, order, actor=buyer, to=OrderStatus.AWAITING_SHIPMENT
    )
    await order_service.ship_order(
        db_session,
        order.id,
        actor_user_id=admin.id,
        tracking_no="TH1234567890",
        carrier=None,
        at=NOW,
    )

    with pytest.raises(OrderTransitionNotAllowed):
        await order_service.ship_order(
            db_session,
            order.id,
            actor_user_id=admin.id,
            tracking_no="TH0000000000",
            carrier=None,
            at=NOW,
        )


# ══════════════════════════════════════════════════════════════════════════
# complete_order() — เส้นที่ 4
# ══════════════════════════════════════════════════════════════════════════


async def test_completing_sells_the_listing_and_records_delivery(
    db_session: AsyncSession,
) -> None:
    """🔴 `code-critic` รอบ 1 High — มิวเทตให้ `complete_order()` ส่ง
    `actor_user_id=None` เข้า `apply_order_transition()`/`mark_sold_by_order()`
    (แทน `actor_user_id` จริง) เคยรอด 86/86 เพราะไม่มีเทสตัวไหนอ่าน
    `order_status_history.actor_user_id` หรือ `poster_attribute_reviews.reviewed_by`
    ของเส้นนี้เลย — เพิ่มทั้งสองไว้ที่นี่
    """
    seller = await _a_seller(db_session)
    poster = await _a_listing(db_session, seller)
    buyer = await _a_user(db_session, "buyer")
    admin = await _an_admin(db_session)
    order = await _reserve_and_order(db_session, poster, buyer)
    await _advance_order(db_session, order, actor=buyer, to=OrderStatus.SHIPPED)

    result = await order_service.complete_order(
        db_session, order.id, actor_user_id=admin.id, at=NOW
    )

    assert result.status is OrderStatus.COMPLETED
    assert result.delivered_at == NOW
    assert result.delivered_confirmed_by is DeliveryConfirmActor.ADMIN
    poster_after = await db_session.get(Poster, poster.id)
    assert poster_after.status is PosterStatus.sold
    assert poster_after.sold_at == NOW

    history = await _history_rows(db_session, order.id)
    last = history[-1]
    assert last.to_status == OrderStatus.COMPLETED.value
    assert last.actor_user_id == admin.id

    # `PosterAttributeReview.reviewed_by` เป็นคอลัมน์ str (ไม่ใช่ UUID) —
    # mark_sold_by_order() เขียน str(actor_user_id) เสมอ (app/services/poster_service.py)
    sold_rows = await _sold_audit_rows(db_session, poster.id)
    assert len(sold_rows) == 1
    assert sold_rows[0].reviewed_by == str(admin.id)


async def test_completing_twice_does_not_sell_twice(db_session: AsyncSession) -> None:
    """🔴 idempotency — เรียกซ้ำต้องได้ `OrderTransitionNotAllowed` จาก gate ไม่ใช่ขาย
    ซ้ำ (เทสเดิมของ `test_order_service.py::test_completing_an_order_twice_does_not_sell_twice`
    ยังยืนเหมือนเดิม — นี่คือเทสของ **ผู้เรียกใหม่** `complete_order()` โดยตรง)
    """
    seller = await _a_seller(db_session)
    poster = await _a_listing(db_session, seller)
    buyer = await _a_user(db_session, "buyer")
    admin = await _an_admin(db_session)
    order = await _reserve_and_order(db_session, poster, buyer)
    await _advance_order(db_session, order, actor=buyer, to=OrderStatus.SHIPPED)
    await order_service.complete_order(
        db_session, order.id, actor_user_id=admin.id, at=NOW
    )

    with pytest.raises(OrderTransitionNotAllowed):
        await order_service.complete_order(
            db_session, order.id, actor_user_id=admin.id, at=NOW
        )

    poster_after = await db_session.get(Poster, poster.id)
    assert poster_after.status is PosterStatus.sold
    assert poster_after.sold_at == NOW
