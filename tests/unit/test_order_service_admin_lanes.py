"""เส้นแอดมิน (INF-41 สไลซ์ A) — `verify_payment()` · `ship_order()` · `complete_order()`

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
    TrackingNoRequired,
)
from app.models.enums import (
    DeliveryConfirmActor,
    OrderStatus,
    PaymentStatus,
    PosterStatus,
)
from app.models.order import Order, OrderStatusHistory
from app.models.payment import Payment
from app.models.platform import NotificationOutbox, PlatformSetting
from app.models.poster import Poster
from app.models.user import User
from app.services import order_service
from tests.unit.test_order_service import (
    NOW,
    _a_listing,
    _a_seller,
    _a_user,
    _reserve_and_order,
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

    🔴 **ไม่ใช้ `db_session.begin_nested()` + `.rollback()`** — พิสูจน์แล้วว่า
    combo นี้ระเบิดเป็น `sqlalchemy.exc.MissingGreenlet` เมื่อ SAVEPOINT ที่ห่อ
    ครอบคำสั่งที่มี `SELECT ... FOR UPDATE` (จาก `apply_order_transition()`) ถูก
    rollback ทั้งที่ทำแบบเดียวกันกับ model ธรรมดา (ไม่มี `FOR UPDATE`) ผ่านสบาย —
    เจอจริงตอนเขียนใบนี้ รันซ้ำ 5 รอบแดงทุกรอบ ไม่ใช่ flaky (บันทึกไว้ใน
    "สิ่งที่ผมไม่แน่ใจ" ท้ายรายงาน)

    ใช้ **`db_session.rollback()` เปล่า** แทน (ทรงเดียวกับที่ `order_ops.dispatch()`
    เรียกจริงตอน commit ล้ม) — ยืนยันแล้วว่าไม่ระเบิด แต่rollback ระดับนี้ **ล้าง
    ทั้งทรานแซกชันของเทส** (seller/poster/buyer/order/payment ทั้งหมด ไม่ใช่แค่การ
    เปลี่ยนของ `verify_payment()`) ตรงกับคำเตือนใน `grant_admin.py` ("ห้ามใช้
    session.rollback() เป็นทางถอย ... จะล้างงานของคนเรียกทั้งทรานแซกชัน") — จึงพิสูจน์
    ได้แค่ *ทุกอย่างในทรานแซกชันนี้หายพร้อมกัน* (รวม payment กับ order) ไม่ใช่ *เฉพาะ
    การเขียนของ `verify_payment()`* แต่ก็ยังคุ้ม claim ของ AC-2 ได้ตรง: ถ้า `payment`
    กับ `order` ถูกเขียนคนละทรานแซกชันกันจริง จะมีแถวใดแถวหนึ่งรอดจาก rollback นี้ —
    เทสนี้พิสูจน์ว่าไม่มีเลยสักแถว
    """
    seller = await _a_seller(db_session)
    poster = await _a_listing(db_session, seller)
    buyer = await _a_user(db_session, "buyer")
    admin = await _an_admin(db_session)
    order = await _reserve_and_order(db_session, poster, buyer)
    await _advance_order(db_session, order, actor=buyer, to=OrderStatus.PAYMENT_REVIEW)
    payment = await _a_claimed_payment(db_session, order)
    order_id, payment_id = order.id, payment.id

    await order_service.verify_payment(
        db_session,
        order.id,
        actor_user_id=admin.id,
        bank_statement_checked=True,
        at=NOW,
    )
    await db_session.rollback()

    refreshed_order = await db_session.scalar(select(Order).where(Order.id == order_id))
    refreshed_payment = await db_session.scalar(
        select(Payment).where(Payment.id == payment_id)
    )
    assert refreshed_order is None
    assert refreshed_payment is None


async def test_verifying_payment_twice_is_rejected_the_second_time(
    db_session: AsyncSession,
) -> None:
    """🔴 idempotency ของเส้นนี้ **ต่างจากอีกสองเส้น** — ได้ `PaymentNotClaimed` ไม่ใช่
    `OrderTransitionNotAllowed` (เหตุผลเต็มอยู่ใน docstring ของ `verify_payment()`
    · จุดที่แผน gate1.md ขัดกับของจริงที่เจอตอนเขียน — ดูรายงานท้ายงาน)
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

    with pytest.raises(PaymentNotClaimed):
        await order_service.verify_payment(
            db_session,
            order.id,
            actor_user_id=admin.id,
            bank_statement_checked=True,
            at=NOW,
        )


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
