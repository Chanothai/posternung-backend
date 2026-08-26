"""**ประตูของเครื่อง order + เส้นทางเกิดของออร์เดอร์** — ADR-0033 (INF-33 สไลซ์ A)

```
app/core/state_machine.py          ← ตารางกฎ (pure data)
        ↑ อ่านโดย
app/services/order_service.py      ← ไฟล์นี้ · ผู้เขียน orders.status และ reservations.status
        ↓ เรียก
app/services/poster_service.py     ← ประตูของเครื่อง listing (ผู้เขียน posters.status)
```

## กฎที่ไฟล์นี้ต้องรักษา (ห้ามแยกออกจากกัน — ADR-0033 D2/D3)

1. **รับ `session` เข้ามาและไม่ `commit`** — ผู้เรียกคุม transaction boundary
   (เหมือนทุกฟังก์ชันของ `poster_service`)
2. **`order_status_history` + `notification_outbox` ถูกประกอบ *ในประตู*** ไม่ใช่
   ในผู้เรียก — ถ้าปล่อยให้ผู้เรียกประกอบ "ประตูเดียว" จะจริงแค่ครึ่งเดียว
   (คนเขียน `status` เป็นประตู แต่คนเขียน *ร่องรอย* เป็นใครก็ได้)
3. **`actor_user_id` · `reason` · `at` เป็นพารามิเตอร์** — ประตูห้ามอ่านนาฬิกาเอง ·
   `actor_user_id = None` แปลว่า **ระบบเปลี่ยนเอง**
4. **ล็อกแถว `posters` เป็นสมอเสมอ · ลำดับ `posters → orders` ห้ามสลับ** — invariant
   ที่ต้องรักษาเป็น invariant **ข้ามสองตาราง** (ตารางฉายของ ADR-0028 D4)
   ล็อกตารางเดียวกันสองทรานแซกชันที่แก้คนละตารางของคู่เดียวกันไม่ได้

## 🔴 สิ่งที่ **สไลซ์ A ตั้งใจไม่ทำ** (ห้ามอ่านว่าตกหล่น)

* **ไม่ฉายสถานะข้ามเครื่อง** — `orders.status → COMPLETED` **ไม่** พา
  `posters.status → sold` (INF-33 **AC-4** · `ADR-0025` Amendment 1 สั่งให้ลงมือ
  ใน **สไลซ์ B** ผ่าน `mark_sold_by_order()` ที่ยังไม่มี) และ `→ CANCELLED`
  **ไม่** ปล่อย listing กลับ `available` เอง (เส้นทางยกเลิกเป็นของ SCR-07/SCR-15
  ซึ่ง proposal §4.2 ระบุผลข้างเคียงไว้คนละแบบต่อจังหวะ)
  ⇒ **วันนี้ไม่มีผู้เรียกใดพา order ออกจาก `AWAITING_PAYMENT` เลย** เส้นพวกนั้น
  ผ่านประตูได้ก็จริงแต่ยังไม่มีเจ้าของเส้นทาง — คนที่เพิ่มผู้เรียกต้องเพิ่มผลข้างเคียง
  ของเครื่อง listing ในใบเดียวกัน
* **ไม่คำนวณ `ship_by_due_at` / `auto_confirm_due_at`** (AC-7 · ADR-0032 —
  `app/core/business_days.py` ยังไม่มี) ปล่อยเป็น `NULL`
* **ไม่สร้างแถว `payments`** — `payments.status` ต้องยังไม่มีผู้เขียนในรอบนี้
  (ADR-0033 D5) เส้นทางแจ้งโอนเป็นของ SCR-08
* **ไม่มี worker ส่งแจ้งเตือน** (AC-8) — แถวใน `notification_outbox` ค้างไว้ก่อน
  ตามเจตนาของ outbox pattern
"""

import logging
import uuid
from datetime import datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import (
    BuyerIsSeller,
    OrderCancellationReasonRequired,
    OrderNotFound,
    OrderTransitionNotAllowed,
    PosterAlreadyReserved,
    PosterNotAvailable,
    PosterNotFound,
    ReservationLimitExceeded,
    ReservationNotActive,
    ReservationNotFound,
    SellerProfileNotFound,
)
from app.core.state_machine import is_order_transition_allowed
from app.models.enums import (
    OrderStatus,
    PaymentStatus,
    PosterStatus,
    ReservationStatus,
)
from app.models.order import Order
from app.models.payment import Payment
from app.models.poster import Poster
from app.models.reservation import Reservation
from app.models.seller import SellerProfile
from app.repositories import (
    notification_repository,
    order_repository,
    platform_setting_repository,
    poster_repository,
    reservation_repository,
    seller_repository,
)
from app.services import poster_service

logger = logging.getLogger(__name__)

# คีย์ใน `platform_settings` — 🔴 ค่าจริงอยู่ใน DB **ห้าม hardcode ตัวเลขที่นี่**
# (BR-L7 · ADR-0030 D3 · ADR-0033 OD-3)
SETTING_RESERVATION_TTL_MINUTES = "reservation_ttl_minutes"
SETTING_MAX_ACTIVE_RESERVATIONS = "max_active_reservations_per_user"
SETTING_COMMISSION_RATE_BPS = "commission_rate_bps"

# สถานะที่แปลว่า "ผู้ซื้อกดแจ้งว่าโอนแล้ว" — BR-P9 · ADR-0029 D5 ข้อ 1
# `VERIFIED` อยู่ในเซตด้วยเพราะเงินเข้าจริงแล้วยิ่งห้ามปล่อยของ
_CLAIMED_PAYMENT_STATUSES = (PaymentStatus.CLAIMED, PaymentStatus.VERIFIED)

_MONEY = Decimal("0.01")


# ══════════════════════════════════════════════════════════════════════════
# ด่านที่ทั้งสองเส้นทางใช้ร่วมกัน
# ══════════════════════════════════════════════════════════════════════════


async def _seller_of(session: AsyncSession, poster: Poster) -> SellerProfile:
    seller = await seller_repository.get_by_id(session, poster.seller_id)
    if seller is None:
        raise SellerProfileNotFound(details=[{"poster_id": str(poster.id)}])
    return seller


async def assert_buyer_is_not_seller(
    session: AsyncSession, poster: Poster, buyer_user_id: uuid.UUID
) -> SellerProfile:
    """🔴 **ด่านเดียวของกฎ "ผู้ซื้อ ≠ ผู้ขาย"** — ADR-0033 **OD-1** (เจ้าของเคาะ (ข))

    **ทั้ง `reserve_listing()` และ `create_order()` เรียกฟังก์ชันนี้ตัวเดียวกัน
    ห้ามเขียนเงื่อนไขซ้ำสองที่** — เหตุผลเดียวกับที่ lazy-expire ต้องมีตัวเดียว
    (ADR-0033 §Consequences)

    เทียบด้วย `seller_profiles.user_id` และต้องอยู่ในทรานแซกชันเดียวกับ row lock
    🔴 **ห้ามเทียบ `posters.seller_id` กับ `buyer_id` ตรง ๆ** — คนละตาราง เป็นจริงเสมอ
    — **เหตุผลทั้งชุดอยู่ที่ `ADR-0033 D3` ห้ามก๊อปมาที่นี่**
    """
    seller = await _seller_of(session, poster)
    if seller.user_id == buyer_user_id:
        raise BuyerIsSeller(details=[{"poster_id": str(poster.id)}])
    return seller


async def _transfer_claimed_for(
    session: AsyncSession, reservation: Reservation
) -> bool:
    """ผู้ซื้อกด "แจ้งว่าโอนแล้ว" บนการจองใบนี้ไปแล้วหรือยัง (BR-P9 · ADR-0029 D5 ข้อ 1)

    กดแจ้งโอนเมื่อไหร่ = **หยุดนาฬิกาจองทันที** listing ค้างที่ `reserved`
    รอแอดมินตัดสิน **ห้ามปล่อยกลับ `available` อัตโนมัติ**

    วันนี้ยังไม่มีเส้นทางที่ทำให้เงื่อนไขนี้เป็นจริง (เส้นแจ้งโอนเป็นของ SCR-08 และ
    รอบนี้ไม่สร้างแถว `payments` เลย) — เขียนไว้ตั้งแต่แรกด้วยเหตุผลเดียวกับ
    `poster_service._pending_charge_for()`: ให้รอบที่มีเส้นทางจริงเป็นการ *เติมโค้ด*
    ไม่ใช่ *รื้อ* · 🔴 **ด่านนี้ต้องอยู่ที่เส้น lazy-expire ด้วย ไม่ใช่อยู่แค่ใน
    scheduler** เพราะ lazy-expire เป็นเส้นทางที่สองที่ปล่อยของได้จริง (ADR-0033 D4)
    """
    claimed = await session.scalar(
        select(func.count(Order.id))
        .join(Payment, Payment.order_id == Order.id, isouter=True)
        .where(
            Order.reservation_id == reservation.id,
            or_(
                Order.status == OrderStatus.PAYMENT_REVIEW,
                Payment.status.in_(_CLAIMED_PAYMENT_STATUSES),
            ),
        )
    )
    return bool(claimed)


async def release_due_reservations(
    session: AsyncSession, *, poster_id: uuid.UUID, at: datetime
) -> None:
    """ปิดการจองที่หมดอายุของโปสเตอร์ใบนี้ + คืนของขึ้นชั้น (ADR-0033 **D4**)

    🔴 **public โดยตั้งใจ — ผู้เรียกที่สองคือ scheduler ของ `ADR-0034`** (INF-33 AC-7)
    ซึ่ง ADR-0033 §Consequences บังคับว่า *"ต้องเรียกฟังก์ชันเดียวกันทั้งคู่ ห้ามเขียน
    เงื่อนไขซ้ำสองที่"* ⇒ ชื่อที่ขึ้นต้นด้วย `_` ส่งสัญญาณตรงข้ามกับมติข้อนั้น
    ‹เปลี่ยนชื่อ 2026-08-26 ตาม `code-critic`›

    `uq_active_reservation_per_poster` เป็น partial unique index บน `status='active'`
    ⇒ ถ้าแถวเก่ายังเป็น `active` **ไม่มีใครจองใบนั้นได้อีกเลย** จนกว่าจะมีคนพลิก
    เป็น `expired` · ถ้าปล่อยให้ scheduler เป็นคนเดียวที่พลิก จะมีช่วงเวลาที่ของ
    "ว่างแล้วแต่จองไม่ได้" ยาวเท่ากับคาบของ scheduler — และเป็นบั๊กที่เทสจัดฉาก
    จับไม่ได้เลยเพราะเทสตั้งสถานะเอง

    scheduler ของ ADR-0034 ยังต้องมีอยู่ (คืนของขึ้นหน้าร้าน + ยิงแจ้งเตือนโดย
    ไม่ต้องรอให้มีคนมาจอง) — **สองตัวนี้ไม่ซ้ำซ้อนกัน ตัวหนึ่งคือความถูกต้อง
    อีกตัวคือความทันเวลา** และทั้งคู่ต้องเรียกฟังก์ชันนี้ตัวเดียวกัน

    ผู้เรียกต้องล็อกแถว `posters` มาก่อนแล้ว (สมอของ ADR-0033 D3)
    """
    for reservation in await reservation_repository.list_active_for_poster(
        session, poster_id
    ):
        if reservation.expires_at > at:
            continue
        if await _transfer_claimed_for(session, reservation):
            logger.info(
                "reservation_id=%s: ไม่พลิกเป็น expired เพราะผู้ซื้อแจ้งโอนแล้ว (BR-P9)",
                reservation.id,
            )
            continue

        reservation.status = ReservationStatus.expired
        await session.flush()
        # คืนของขึ้นชั้น — ผ่านประตูของเครื่อง listing เท่านั้น (ADR-0025 D5)
        await poster_service.apply_listing_transition(
            session,
            poster_id,
            to_status=PosterStatus.available,
            actor_user_id=None,  # ระบบเปลี่ยนเอง
            reason="reservation expired",
            at=at,
        )


# ══════════════════════════════════════════════════════════════════════════
# เส้นทางเกิด: จอง → สร้างออร์เดอร์
# ══════════════════════════════════════════════════════════════════════════


async def reserve_listing(
    session: AsyncSession,
    poster_id: uuid.UUID,
    *,
    buyer_user_id: uuid.UUID,
    at: datetime,
) -> Reservation:
    """กด "ซื้อเลย" = จองทันที (BR-B1) — **ไม่ `commit`**

    ลำดับในทรานแซกชันเดียว **ห้ามสลับ**:

    1. `SELECT ... FOR UPDATE` แถว `posters` — สมอของทั้งระบบ (ADR-0033 D3 ·
       `stock-integrity` §มติที่ตัดสินแล้ว **ห้ามเปลี่ยนเป็น conditional update**)
    2. lazy-expire การจองที่หมดอายุของใบนี้ (ADR-0033 D4)
    3. listing ต้องขึ้นชั้นอยู่จริง: `available` + ผ่าน `published_only()` +
       มี `approved_at` (BR-L6)
    4. ผู้ซื้อ ≠ ผู้ขาย (ADR-0033 OD-1)
    5. เพดาน active reservation ต่อผู้ใช้ (ADR-0033 OD-3)
    6. สร้างแถวจอง + พา listing ไป `reserved` ผ่านประตูของเครื่อง listing

    TTL อ่านจาก `platform_settings.reservation_ttl_minutes` (ADR-0030 D3 = 60 นาที)
    🔴 **ห้าม hardcode** ทั้งเลข 60 และเพดานต่อผู้ใช้
    """
    poster = await poster_repository.get_for_update(session, poster_id)
    if poster is None:
        raise PosterNotFound()

    await release_due_reservations(session, poster_id=poster_id, at=at)

    if not poster_service.is_published(poster) or poster.approved_at is None:
        # ตอบเหมือนไม่มีแถวนี้ ด้วยเหตุผลเดียวกับ `get_poster_detail()`
        raise PosterNotFound()
    if poster.status is not PosterStatus.available:
        raise PosterNotAvailable()

    await assert_buyer_is_not_seller(session, poster, buyer_user_id)

    max_active = await platform_setting_repository.get_int(
        session, SETTING_MAX_ACTIVE_RESERVATIONS
    )
    active_count = await reservation_repository.count_active_for_user(
        session, buyer_user_id, at=at
    )
    if active_count >= max_active:
        raise ReservationLimitExceeded(details=[{"limit": max_active}])

    ttl_minutes = await platform_setting_repository.get_int(
        session, SETTING_RESERVATION_TTL_MINUTES
    )
    reservation = reservation_repository.create(
        session,
        poster_id=poster_id,
        user_id=buyer_user_id,
        expires_at=at + timedelta(minutes=ttl_minutes),
    )
    try:
        await session.flush()
    except IntegrityError as exc:
        # ชั้นที่ 2 ของการกันซื้อซ้อน — ห้ามปล่อยเป็น 500 (CLAUDE.md New API Checklist)
        if "uq_active_reservation_per_poster" not in str(exc.orig):
            raise
        raise PosterAlreadyReserved(details=[{"poster_id": str(poster_id)}]) from exc

    await poster_service.apply_listing_transition(
        session,
        poster_id,
        to_status=PosterStatus.reserved,
        actor_user_id=buyer_user_id,
        reason="buyer reserved the listing",
        at=at,
    )

    # BR-P8 — ฝั่งผู้ขายถูกแจ้งโดยประตูของเครื่อง listing แล้ว ที่นี่คือฝั่งผู้ซื้อ
    notification_repository.queue(
        session,
        recipient_user_id=buyer_user_id,
        template_key="listing_reserved_buyer",
        payload={
            "poster_id": str(poster_id),
            "reservation_id": str(reservation.id),
            "expires_at": reservation.expires_at.isoformat(),
        },
        send_after=at,
    )
    await session.flush()
    return reservation


def _commission_amount(item_price: Decimal, rate_bps: int) -> Decimal:
    """คอมมิชชั่นคิดจาก **ราคาสินค้าเท่านั้น ไม่คิดจากค่าส่ง** (BR-L7)"""
    return (item_price * Decimal(rate_bps) / Decimal(10000)).quantize(
        _MONEY, rounding=ROUND_HALF_UP
    )


async def _commission_rate_bps(session: AsyncSession, seller: SellerProfile) -> int:
    """อัตราที่ **ใช้จริงกับธุรกรรมนี้** — snapshot ลงแถว order ตอนสร้าง (BR-L7)

    ลำดับ: ร้านของเราเอง (ไม่คิดคอม · proposal §6 Q3) → override รายผู้ขาย →
    ค่ากลางจาก `platform_settings`
    """
    if seller.is_house_account:
        return 0
    if seller.commission_rate_bps is not None:
        return seller.commission_rate_bps
    return await platform_setting_repository.get_int(
        session, SETTING_COMMISSION_RATE_BPS
    )


async def create_order(
    session: AsyncSession,
    reservation_id: uuid.UUID,
    *,
    buyer_user_id: uuid.UUID,
    at: datetime,
) -> Order:
    """สร้างออร์เดอร์จากการจองที่ยัง `active` — **ไม่ `commit`**

    ลำดับล็อก `posters → orders` เหมือนกันทั้งไฟล์ (ADR-0033 D3) · การจองถูกพลิก
    เป็น `converted` ในทรานแซกชันเดียวกัน ⇒ ในเส้นทางปกติ **ไม่มีแถว `active`
    เหลือค้าง** ตอนที่ `mark_sold_by_order()` ของสไลซ์ B มาตรวจ (ADR-0025 A1-D2 ข้อ 4)

    เงินทุกฟิลด์เป็น **snapshot ตอนสร้าง** (BR-L7) — แก้ config ทีหลังห้ามกระทบ
    ธุรกรรมที่เกิดไปแล้ว · `item_*` 6 ฟิลด์คือ snapshot ของ BL-77 (ADR-0020 A4-D2)
    ซึ่งเป็นหลักฐานตอนเกิดข้อพิพาท เพราะ **ผู้ขายแก้ listing ตัวเองได้**

    🔴 ด่านผู้ซื้อ ≠ ผู้ขายถูกเรียกซ้ำที่นี่โดยตั้งใจ (ADR-0033 OD-1 ทาง (ข)) —
    วันหน้าอาจมีเส้นทางสร้างออร์เดอร์ที่ไม่ผ่าน `reserve_listing()`
    """
    reservation = await reservation_repository.get_by_id(session, reservation_id)
    if reservation is None:
        raise ReservationNotFound()

    # สมอต้องเป็นแถว `posters` เสมอ แม้ตัวที่กำลังจะเขียนคือ `orders` (D3)
    poster = await poster_repository.get_for_update(session, reservation.poster_id)
    if poster is None:
        raise PosterNotFound()

    if reservation.user_id != buyer_user_id:
        # ไม่บอกว่า "เป็นของคนอื่น" — ตอบเหมือนไม่มีใบนี้ (กันการไล่เดา id)
        raise ReservationNotFound()
    if reservation.status is not ReservationStatus.active:
        raise ReservationNotActive()
    if reservation.expires_at <= at:
        raise ReservationNotActive(
            details=[{"expired_at": reservation.expires_at.isoformat()}]
        )

    seller = await assert_buyer_is_not_seller(session, poster, buyer_user_id)

    # โหลดรูปเพื่อทำ snapshot — แถวเดียวกับที่ล็อกไว้แล้ว (identity map) แต่รอบนี้
    # มี `selectinload(images)` ติดมาด้วย · การแตะ `poster.images` โดยไม่โหลดก่อน
    # ในบริบท async คือ `MissingGreenlet` ไม่ใช่ lazy-load เงียบ ๆ
    poster = await poster_repository.get_by_id(session, reservation.poster_id)
    if poster is None:  # pragma: no cover — ล็อกแถวเดิมไว้แล้วในทรานแซกชันนี้
        raise PosterNotFound()

    item_price = poster.price
    shipping_fee = poster.shipping_fee
    total_amount = item_price + shipping_fee
    rate_bps = await _commission_rate_bps(session, seller)
    commission_amount = _commission_amount(item_price, rate_bps)

    order = Order(
        order_no=await order_repository.next_order_no(session, at=at),
        poster_id=poster.id,
        buyer_id=buyer_user_id,
        seller_id=seller.id,
        reservation_id=reservation.id,
        status=OrderStatus.AWAITING_PAYMENT,
        item_price=item_price,
        shipping_fee=shipping_fee,
        total_amount=total_amount,
        commission_rate_bps=rate_bps,
        commission_amount=commission_amount,
        seller_payout_amount=total_amount - commission_amount,
        item_title=poster.title,
        item_condition_grade=poster.condition_grade,
        # 🔴 รูปที่ลูกค้าเห็นตอนกดซื้อหายถาวรถ้าไม่ snapshot (BL-40 จะถ่ายใหม่ทั้งชุด)
        item_image_urls={"urls": poster_service.public_image_urls(poster)},
        item_verification_status=poster.verification_status,
        item_reference_note=poster.reference_note,
    )
    session.add(order)

    reservation.status = ReservationStatus.converted

    try:
        await session.flush()
    except IntegrityError as exc:
        # ชั้นที่ 3 ของการกันซื้อซ้อน (`uq_live_order_per_poster`) — 409 ไม่ใช่ 500
        if "uq_live_order_per_poster" not in str(exc.orig):
            raise
        raise PosterNotAvailable(details=[{"poster_id": str(poster.id)}]) from exc

    order_repository.add_status_history(
        session,
        order_id=order.id,
        from_status=None,  # แถวเกิดใหม่ ไม่ได้มาจากสถานะไหน
        to_status=order.status.value,
        actor_user_id=buyer_user_id,
        reason=None,
    )
    _queue_both_parties(
        session,
        order=order,
        seller_user_id=seller.user_id,
        event="order_created",
        from_status=None,
        at=at,
    )
    await session.flush()
    return order


# ══════════════════════════════════════════════════════════════════════════
# ประตูของเครื่อง order
# ══════════════════════════════════════════════════════════════════════════


def _queue_both_parties(
    session: AsyncSession,
    *,
    order: Order,
    seller_user_id: uuid.UUID,
    event: str,
    from_status: str | None,
    at: datetime,
) -> None:
    """BR-P8 — แจ้งเตือน **ทั้งสองฝ่าย** ทุกจุดเปลี่ยนสถานะ

    🔴 `payload` มีแต่ id กับสถานะ **ห้ามมีชื่อ/ที่อยู่/เบอร์** (ADR-0020 D9)
    """
    payload = {
        "order_id": str(order.id),
        "order_no": order.order_no,
        "poster_id": str(order.poster_id),
        "from_status": from_status,
        "to_status": order.status.value,
    }
    for role, user_id in (("buyer", order.buyer_id), ("seller", seller_user_id)):
        notification_repository.queue(
            session,
            recipient_user_id=user_id,
            template_key=f"{event}_{role}",
            payload=payload,
            send_after=at,
        )


async def apply_order_transition(
    session: AsyncSession,
    order_id: uuid.UUID,
    *,
    to_status: OrderStatus,
    actor_user_id: uuid.UUID | None,
    reason: str | None,
    at: datetime,
) -> Order:
    """**ประตูเดียวของ `orders.status`** — ADR-0033 D2 · INF-33 AC-1/AC-3

    ทำสามอย่างในทรานแซกชันเดียวเสมอ **ห้ามแยกออกจากกัน**: เขียนสถานะ ·
    `order_status_history` · `notification_outbox` ของทั้งสองฝ่าย

    🔴 ไป `CANCELLED`/`REFUNDED` **ต้องมี `reason`** — ถ้าไม่ตรวจก่อน `flush()`
    `ck_orders_cancelled_requires_reason` จะกลายเป็น `IntegrityError` ดิบ = 500

    🔴 **ประตูนี้ไม่ฉายสถานะไปยังเครื่อง listing** — ดู §สิ่งที่สไลซ์ A ตั้งใจไม่ทำ
    ที่หัวไฟล์ · ผู้เรียกที่พา order ไป `COMPLETED`/`CANCELLED` ต้องมาพร้อมผลข้างเคียง
    ของเครื่อง listing ในใบเดียวกัน (AC-4 = สไลซ์ B)
    """
    poster_id = await order_repository.get_poster_id(session, order_id)
    if poster_id is None:
        raise OrderNotFound()

    # สมอเสมอ · ลำดับ posters → orders ห้ามสลับ (ADR-0033 D3)
    poster = await poster_repository.get_for_update(session, poster_id)
    if poster is None:  # pragma: no cover — FK RESTRICT กันไว้แล้ว
        raise PosterNotFound()

    order = await order_repository.get_for_update(session, order_id)
    if order is None:  # pragma: no cover — อ่าน poster_id ของมันได้แปลว่ามีแถว
        raise OrderNotFound()

    from_status = order.status
    if not is_order_transition_allowed(from_status, to_status):
        raise OrderTransitionNotAllowed(
            details=[{"from_status": from_status.value, "to_status": to_status.value}]
        )

    needs_reason = to_status in (OrderStatus.CANCELLED, OrderStatus.REFUNDED)
    if needs_reason and not (reason or "").strip():
        raise OrderCancellationReasonRequired(details=[{"to_status": to_status.value}])

    seller = await _seller_of(session, poster)

    order.status = to_status
    if needs_reason:
        order.cancellation_reason = reason
    if to_status is OrderStatus.CANCELLED:
        order.cancelled_at = at
    if to_status is OrderStatus.COMPLETED:
        order.completed_at = at

    order_repository.add_status_history(
        session,
        order_id=order.id,
        from_status=from_status.value,
        to_status=to_status.value,
        actor_user_id=actor_user_id,
        reason=reason,
    )
    _queue_both_parties(
        session,
        order=order,
        seller_user_id=seller.user_id,
        event=f"order_{to_status.value.lower()}",
        from_status=from_status.value,
        at=at,
    )
    await session.flush()
    return order
