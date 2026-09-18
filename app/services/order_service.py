"""**ประตูของเครื่อง order + เส้นทางเกิดของออร์เดอร์** — ADR-0033 (INF-33 สไลซ์ A + B)

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

## 🔴 สิ่งที่ **ยังตั้งใจไม่ทำ** (ห้ามอ่านว่าตกหล่น)

* **ฉายสถานะข้ามเครื่องเฉพาะขา `COMPLETED`** — `orders.status → COMPLETED` **พา**
  `posters.status → sold` แล้ว (INF-33 **AC-4** สไลซ์ B ผ่าน
  `poster_service.mark_sold_by_order()` — ดู `apply_order_transition()`) ส่วน
  `→ CANCELLED` **ยัง**ไม่ปล่อย listing กลับ `available` เอง (เส้นทางยกเลิกเป็นของ
  SCR-07/SCR-15 ซึ่ง proposal §4.2 ระบุผลข้างเคียงไว้คนละแบบต่อจังหวะ — คนละ
  ADR ที่ยังไม่มามอบหมายให้ไฟล์นี้)
  ⇒ **วันนี้ไม่มีผู้เรียกใดพา order ออกจาก `AWAITING_PAYMENT` เลย** นอกจาก
  `COMPLETED` เส้นที่เหลือผ่านประตูได้ก็จริงแต่ยังไม่มีเจ้าของเส้นทาง — คนที่เพิ่ม
  ผู้เรียกของเส้นเหล่านั้นต้องเพิ่มผลข้างเคียงของเครื่อง listing ในใบเดียวกัน
* **`ship_by_due_at` ยังไม่คำนวณ** (AC-7 · ADR-0032 — `app/core/business_days.py`
  ยังไม่มี) ปล่อยเป็น `NULL` · 🔴 **`auto_confirm_due_at` คำนวณแล้ว** ตั้งแต่
  INF-41 สไลซ์ A — `ship_order()` เขียนค่านี้ตอนเข้า `SHIPPED` (ADR-0032 D9: วัน
  ปฏิทิน ไม่ใช้ `business_days.py`) ถ้อยคำเดิมตรงนี้พูดถึงสองคอลัมน์รวมกัน
  ซึ่งไม่จริงอีกต่อไปตั้งแต่ตอนนี้
* **`payments` มีผู้เขียน `UPDATE` แล้ว — `verify_payment()`** (INF-41 สไลซ์ A ·
  ADR-0033 D5) `INSERT` ยังไม่มีผู้เขียนในรอบนี้เหมือนเดิม (ADR-0033 D7 —
  เส้นแจ้งโอนเป็นของ SCR-08) และเส้นปฏิเสธสลิป (`reject_payment()`) ยังรอ
  ADR-0033 Amendment 2 ก่อนจึงยังไม่ลง (INF-41 สไลซ์ B)
* **ไม่มี worker ส่งแจ้งเตือน** (AC-8) — แถวใน `notification_outbox` ค้างไว้ก่อน
  ตามเจตนาของ outbox pattern
* **`verify_payment()` / `ship_order()` / `complete_order()` ไม่มี endpoint HTTP** —
  ผู้เรียกวันนี้คือ `scripts/orders/order_ops.py` เท่านั้น (INF-41 · ADR-0035 D2 —
  แทน SCR-15 ใน Closed Beta) endpoint จริงเป็นของ Phase ถัดไป (`INF-35` gap2)
"""

import logging
import uuid
from datetime import datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import NamedTuple

from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import (
    BankStatementNotChecked,
    BuyerHasLiveOrder,
    BuyerIsSeller,
    OrderCancellationReasonRequired,
    OrderNotFound,
    OrderTransitionNotAllowed,
    PaymentNotClaimed,
    PosterAlreadyReserved,
    PosterNotAvailable,
    PosterNotFound,
    ReservationLimitExceeded,
    ReservationNotActive,
    ReservationNotFound,
    SellerProfileNotFound,
    TrackingNoRequired,
)
from app.core.state_machine import is_order_transition_allowed
from app.models.enums import (
    DeliveryConfirmActor,
    OrderStatus,
    PaymentStatus,
    PosterStatus,
    ReservationStatus,
)
from app.models.order import Order, OrderShippingDetail
from app.models.payment import Payment
from app.models.poster import Poster
from app.models.reservation import Reservation
from app.models.seller import SellerProfile
from app.repositories import (
    notification_repository,
    order_repository,
    payment_repository,
    platform_setting_repository,
    poster_repository,
    reservation_repository,
    seller_repository,
)
from app.schemas.order import ShippingAddressInput
from app.services import poster_service

logger = logging.getLogger(__name__)

# คีย์ใน `platform_settings` — 🔴 ค่าจริงอยู่ใน DB **ห้าม hardcode ตัวเลขที่นี่**
# (BR-L7 · ADR-0030 D3 · ADR-0033 OD-3)
SETTING_RESERVATION_TTL_MINUTES = "reservation_ttl_minutes"
SETTING_MAX_ACTIVE_RESERVATIONS = "max_active_reservations_per_user"
SETTING_COMMISSION_RATE_BPS = "commission_rate_bps"
# ADR-0020 A4-D1 · ADR-0032 D9 — วันปฏิทิน ไม่ใช้ business day (ship_order())
SETTING_INSPECTION_PERIOD_DAYS = "inspection_period_days"

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

    🔴 **`BuyerIsSeller` raise แบบไม่มี `details`** (code-critic รอบ 1 F2) —
    `ADR-0037` Amendment 2 **A2-D2** บังคับว่า *"บนทุก error ที่ไม่ใช่
    `VALIDATION_ERROR` details ต้องเป็น `{field, message}` ที่ parse ได้"* และ
    สัญญา (`docs/api/openapi.yaml`) เขียนตัวอย่างของ 403 นี้ไว้ตรง ๆ ทั้งสอง path
    ว่า `details: null` ⇒ เลือกทาง **ไม่มี `details`** แทนการยัด `{field:"poster_id",
    message:"<uuid>"}` เพราะ (1) ตรงกับตัวอย่างในสัญญาเป๊ะ ไม่ต้องแก้สัญญา
    (2) `poster_id`/`reservation_id` เป็นค่าที่ client ส่งมาเองอยู่แล้วในคำขอ
    การสะท้อนกลับไม่ได้ให้ข้อมูลใหม่ ตรงข้ามกับ `reserved_until`/`limit`/`expired_at`
    ที่ client ไม่รู้มาก่อน — เข้าเกณฑ์ minimal disclosure ของ security-baseline §5
    """
    seller = await _seller_of(session, poster)
    if seller.user_id == buyer_user_id:
        raise BuyerIsSeller()
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


class ReserveResult(NamedTuple):
    """ผลของ `reserve_listing()` — ADR-0037 A5-D1

    `created=True` = แถวจองใหม่ (API ตอบ 201) · `created=False` = แถว `active` เดิม
    ของผู้เรียกเอง (API ตอบ 200) · เป็น tuple ที่ unpack ได้ (`reservation, created = ...`)
    ⇒ service เป็นคนบอก ไม่ต้องให้ API เดาจาก `created_at` (นาฬิกา DB กับนาฬิกา
    แอปเป็นคนละตัว เทียบกันไม่ได้อย่างปลอดภัย)
    """

    reservation: Reservation
    created: bool


async def reserve_listing(
    session: AsyncSession,
    poster_id: uuid.UUID,
    *,
    buyer_user_id: uuid.UUID,
    at: datetime,
) -> ReserveResult:
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

    **idempotent ต่อ (buyer, poster)** (ADR-0037 A5-D1): ถ้าผู้เรียกถือ reservation
    `active` ของใบนี้อยู่แล้ว คืนแถวเดิมโดย **ไม่ insert · ไม่ต่อ `expires_at` ·
    ไม่เขียนร่องรอยใหม่** — ตัดสินใต้ `FOR UPDATE` เดิมและ*หลัง*ข้อ 2 ⇒ reservation
    ที่หมดอายุแล้วไม่เข้าทางนี้ (ได้แถวใหม่ตามปกติ)
    """
    poster = await poster_repository.get_for_update(session, poster_id)
    if poster is None:
        raise PosterNotFound()

    await release_due_reservations(session, poster_id=poster_id, at=at)

    if not poster_service.is_published(poster) or poster.approved_at is None:
        # ตอบเหมือนไม่มีแถวนี้ ด้วยเหตุผลเดียวกับ `get_poster_detail()`
        raise PosterNotFound()
    if poster.status is not PosterStatus.available:
        active_reservation = await reservation_repository.get_active_reservation(
            session, poster_id
        )
        if active_reservation is not None:
            if active_reservation.user_id == buyer_user_id:
                # ADR-0037 A5-D1 — ผู้ถือคือผู้เรียกเอง ⇒ คืนแถวเดิม ไม่ใช่ 409
                # (ยังใต้ FOR UPDATE และหลัง release_due_reservations() ⇒ แถวนี้ยังไม่หมดอายุ)
                return ReserveResult(active_reservation, created=False)
            # ADR-0037 D4 · Amendment 2 A2-D1 — ต้องบอกได้ว่าต้องรออีกนานแค่ไหน
            # 🔴 ห้ามแนบตัวตนผู้จองเด็ดขาด (security-baseline §5) — เอาแค่ reserved_until
            raise PosterNotAvailable(
                details=[
                    {
                        "field": "reserved_until",
                        "message": active_reservation.expires_at.isoformat(),
                    }
                ]
            )
        # ไม่มีแถว active = reservation ถูก converted เป็นออร์เดอร์แล้ว หรือของถูกขายไปแล้ว
        # ADR-0037 A5-D4 — ถ้าออร์เดอร์ที่ยังไม่จบเป็นของผู้เรียกเอง ต้องไม่เล่าว่า
        # "ผู้อื่นกำลังจอง" · ผู้เรียกคนอื่นได้ 409 เปล่า ๆ (ไม่มี "เวลาที่ต้องรอ" ให้บอก
        # และ order_no ของคนอื่นเป็นข้อมูลธุรกรรม — security-baseline §5)
        live_order = await order_repository.get_live_for_poster(session, poster_id)
        if live_order is not None and live_order.buyer_id == buyer_user_id:
            raise BuyerHasLiveOrder(
                details=[{"field": "order_no", "message": live_order.order_no}]
            )
        raise PosterNotAvailable()

    await assert_buyer_is_not_seller(session, poster, buyer_user_id)

    max_active = await platform_setting_repository.get_int(
        session, SETTING_MAX_ACTIVE_RESERVATIONS
    )
    active_count = await reservation_repository.count_active_for_user(
        session, buyer_user_id, at=at
    )
    if active_count >= max_active:
        # ADR-0037 Amendment 2 A2-D1 — {field, message} · message เป็นค่าเปล่าที่
        # int() กินได้ทั้งช่อง ไม่ใช่ประโยค
        raise ReservationLimitExceeded(
            details=[{"field": "limit", "message": str(max_active)}]
        )

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
        raise PosterAlreadyReserved(
            details=[{"field": "poster_id", "message": str(poster_id)}]
        ) from exc

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
    return ReserveResult(reservation, created=True)


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
    shipping_address: ShippingAddressInput,
    at: datetime,
) -> Order:
    """สร้างออร์เดอร์จากการจองที่ยัง `active` — **ไม่ `commit`**

    ลำดับล็อก `posters → orders` เหมือนกันทั้งไฟล์ (ADR-0033 D3) · การจองถูกพลิก
    เป็น `converted` ในทรานแซกชันเดียวกัน ⇒ ในเส้นทางปกติ **ไม่มีแถว `active`
    เหลือค้าง** ตอนที่ `mark_sold_by_order()` ตรวจ (INF-33 AC-4 สไลซ์ B ·
    ADR-0025 A1-D2 ข้อ 4)

    เงินทุกฟิลด์เป็น **snapshot ตอนสร้าง** (BR-L7) — แก้ config ทีหลังห้ามกระทบ
    ธุรกรรมที่เกิดไปแล้ว · `item_*` 6 ฟิลด์คือ snapshot ของ BL-77 (ADR-0020 A4-D2)
    ซึ่งเป็นหลักฐานตอนเกิดข้อพิพาท เพราะ **ผู้ขายแก้ listing ตัวเองได้**

    🔴 ด่านผู้ซื้อ ≠ ผู้ขายถูกเรียกซ้ำที่นี่โดยตั้งใจ (ADR-0033 OD-1 ทาง (ข)) —
    วันหน้าอาจมีเส้นทางสร้างออร์เดอร์ที่ไม่ผ่าน `reserve_listing()`

    🔴 **`shipping_address` เป็น keyword-only และ required — ห้าม optional**
    (ADR-0037 **D1** · คำสั่งเจ้าของ) ที่อยู่ถูกเขียนลง `order_shipping_details`
    **ในทรานแซกชันเดียวกับที่ล็อก `posters`** (สมอ + ลำดับล็อกเดิม ADR-0033 D3
    ไม่เปลี่ยน) — ถ้าเป็น optional จะมีเส้นทางสร้างออร์เดอร์ที่ไม่มีที่อยู่ได้เงียบ ๆ
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
        # ADR-0037 Amendment 2 A2-D1 — {field, message} · message parse ได้ตรง ๆ
        raise ReservationNotActive(
            details=[
                {"field": "expired_at", "message": reservation.expires_at.isoformat()}
            ]
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
        raise PosterNotAvailable(
            details=[{"field": "poster_id", "message": str(poster.id)}]
        ) from exc

    # ADR-0037 D1 — `order.id` เพิ่งมีค่าจริงหลัง flush ข้างบน (server-generated
    # UUID) ⇒ เขียน order_shipping_details ต้องมาหลังจุดนี้ แต่ยังอยู่ในทรานแซกชัน
    # เดียวกับที่ล็อก `posters` (สมอ + ลำดับล็อกเดิมของ ADR-0033 D3 ไม่เปลี่ยน)
    session.add(
        OrderShippingDetail(
            order_id=order.id,
            recipient_name=shipping_address.recipient_name,
            recipient_phone=shipping_address.recipient_phone,
            address_line=shipping_address.address_line,
            sub_district=shipping_address.sub_district,
            district=shipping_address.district,
            province=shipping_address.province,
            postal_code=shipping_address.postal_code,
        )
    )
    await session.flush()

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

    🔴 **ขา `COMPLETED` ฉายสถานะไปยังเครื่อง listing แล้ว** (INF-33 AC-4 สไลซ์ B) —
    หลัง `flush()` สถานะ `orders.status = COMPLETED` เรียก
    `poster_service.mark_sold_by_order()` ต่อทันทีในทรานแซกชันเดียวกัน (ก่อนคิว
    `notification_outbox` ของ `order_completed_*`) ส่วนขาอื่น (`CANCELLED` เป็นต้น)
    **ยัง**ไม่ฉาย — ดู §สิ่งที่ยังตั้งใจไม่ทำที่หัวไฟล์ · ผู้เรียกที่เพิ่มเส้นทางพา order
    ไปสถานะปลายทางอื่นต้องมาพร้อมผลข้างเคียงของเครื่อง listing ในใบเดียวกัน
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
    await session.flush()

    if to_status is OrderStatus.COMPLETED:
        # INF-33 AC-4 สไลซ์ B — ทางเข้าที่ 2 ของ `posters.status = sold` (ADR-0025
        # Amendment 1) — flush() ข้างบนเขียนไว้ **ชัดเจน** ก่อนเรียกจุดนี้ ไม่ใช่
        # เงื่อนไขความถูกต้อง (code-critic M2: autoflush ของ session ทำให้ SELECT
        # ... FOR UPDATE ของ mark_sold_by_order() เห็น status=COMPLETED ที่เพิ่งตั้ง
        # อยู่แล้วแม้ไม่มี flush() บรรทัดนี้) — วางไว้ให้อ่านออกโดยไม่ต้องพึ่ง
        # autoflush ของ session (จะพึ่ง = ผูกกับ config ที่ไม่ได้ประกาศตรงนี้)
        await poster_service.mark_sold_by_order(
            session,
            poster_id,
            order_id=order.id,
            actor_user_id=actor_user_id,
            at=at,
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


# ══════════════════════════════════════════════════════════════════════════
# เส้นทางแอดมิน (สคริปต์ operator) — INF-41 สไลซ์ A
# ══════════════════════════════════════════════════════════════════════════
#
# ผู้เรียกวันนี้คือ `scripts/orders/order_ops.py` เท่านั้น (ไม่มี endpoint HTTP —
# ดู §สิ่งที่ยังตั้งใจไม่ทำที่หัวไฟล์) ทั้งสามฟังก์ชันเป็น async · ไม่ `commit` ·
# ผู้เรียกคุม transaction boundary เหมือนฟังก์ชันอื่นทุกตัวในไฟล์นี้


async def verify_payment(
    session: AsyncSession,
    order_id: uuid.UUID,
    *,
    actor_user_id: uuid.UUID,
    bank_statement_checked: bool,
    at: datetime,
) -> Order:
    """เส้นที่ 1 — ยืนยันเงินเข้าจริง (BR-P2 · SCR-15 AC-3 · INF-41 AC-2)

    `PAYMENT_REVIEW → AWAITING_SHIPMENT` ผ่าน `apply_order_transition()` + เขียน
    `payments.bank_statement_checked` · `status → VERIFIED` · `verified_by` ·
    `verified_at` **ในทรานแซกชันเดียวกัน**

    🔴 **ด่าน `bank_statement_checked` ต้องมาก่อนเปิด lock/flush ใด ๆ ทั้งหมด**
    (SCR-15 AC-3 — สลิปเป็นแค่การอ้าง ADR-0029 D3 เงินเข้าจริงเท่านั้นที่นับ) —
    ปฏิเสธที่นี่ถูกกว่าเปิดทรานแซกชันแล้วทิ้ง

    ล็อก `posters → orders` เกิดขึ้นข้างใน `apply_order_transition()` (สมอ + ลำดับ
    เดิมของ ADR-0033 D3 — ฟังก์ชันนี้**ไม่ล็อกซ้ำเอง**) ส่วนแถว `payments` ถูกล็อก
    แยกผ่าน `payment_repository.get_claimed_for_order()` ซึ่งไม่อยู่ในสายล็อก
    `posters → orders` เลย (คนละตารางที่ไม่มีใครอื่นแตะพร้อมกัน)

    🔴 **idempotency ต่างจากอีกสองเส้นในไฟล์นี้** — เรียกซ้ำหลังยืนยันสำเร็จแล้วจะได้
    `PaymentNotClaimed` ไม่ใช่ `OrderTransitionNotAllowed` เพราะ payment ที่หาอยู่
    ใช้เงื่อนไข `status == CLAIMED` และรอบแรกได้พลิกเป็น `VERIFIED` ไปแล้ว —
    ทั้งสองคือ 409 ที่แปลว่า "ทำไปแล้ว ไม่มีอะไรให้ทำซ้ำ" เหมือนกัน ต่างแค่ error_code
    (บันทึกไว้ใน GATE 1 §จุดที่แผนขัดกับของจริง — แผนเดิมคาดว่าทุกเส้นได้ error
    เดียวกันตอน retry)
    """
    if not bank_statement_checked:
        raise BankStatementNotChecked()

    # 🔴 **ตัวแปรชื่อ `payment`** — ตัวสแกน AST ของ test_status_writer_invariant.py
    # จำแนกตารางจากชื่อตัวแปร ไม่ใช่ type (ดู docstring ของ
    # payment_repository.get_claimed_for_order())
    payment = await payment_repository.get_claimed_for_order(session, order_id)
    if payment is None:
        raise PaymentNotClaimed()

    payment.bank_statement_checked = True
    payment.status = PaymentStatus.VERIFIED
    payment.verified_by = actor_user_id
    payment.verified_at = at

    return await apply_order_transition(
        session,
        order_id,
        to_status=OrderStatus.AWAITING_SHIPMENT,
        actor_user_id=actor_user_id,
        reason="payment verified against bank statement",
        at=at,
    )


async def ship_order(
    session: AsyncSession,
    order_id: uuid.UUID,
    *,
    actor_user_id: uuid.UUID,
    tracking_no: str,
    carrier: str | None,
    at: datetime,
) -> Order:
    """เส้นที่ 3 — แอดมินกดส่งของแทนผู้ขาย (BR-P3/BR-P4 · INF-41 AC-4)

    `AWAITING_SHIPMENT → SHIPPED` ผ่าน `apply_order_transition()` — `actor_user_id`
    เป็น**แอดมิน**ที่รันสคริปต์ ไม่ใช่ `seller.user_id` (ต้องบันทึกว่าแอดมินกดแทนใคร
    เพราะ `SCR-14` Seller Hub อยู่นอกคิว Beta — ไม่มี UI ให้ผู้ขายกดเอง)

    ⚠️ **`SHIPPED` เป็นตัวเริ่มนาฬิกา `inspection_period_days`** (BR-P4 · ADR-0032
    A1-D3) — ถ้าเส้นนี้ไม่ทำงาน `complete_order()` ไม่มีวันถึงกำหนดและเงินไม่มีวัน
    ออกจาก escrow (INF-41 AC-4 หมายเหตุ) คำนวณ **ตอนนี้แล้วเก็บลงแถว** ห้าม
    คำนวณสดตอนอ่าน (ADR-0020 A4-D1) — หน่วยเป็น**วันปฏิทิน** ไม่ใช่ business day
    (ADR-0032 D9 ⇒ ไม่ต้องมี `app/core/business_days.py`)

    `tracking_no` ว่าง/whitespace ล้วน → ปฏิเสธ **ก่อนเขียนอะไรเลย**
    """
    if not (tracking_no or "").strip():
        raise TrackingNoRequired()

    inspection_period_days = await platform_setting_repository.get_int(
        session, SETTING_INSPECTION_PERIOD_DAYS
    )

    order = await apply_order_transition(
        session,
        order_id,
        to_status=OrderStatus.SHIPPED,
        actor_user_id=actor_user_id,
        reason="shipped by admin on behalf of seller",
        at=at,
    )
    order.tracking_no = tracking_no.strip()
    order.carrier = carrier
    order.shipped_at = at
    order.auto_confirm_due_at = at + timedelta(days=inspection_period_days)
    await session.flush()
    return order


async def complete_order(
    session: AsyncSession,
    order_id: uuid.UUID,
    *,
    actor_user_id: uuid.UUID,
    at: datetime,
) -> Order:
    """เส้นที่ 4 — ปิดออร์เดอร์ (INF-41 AC-5)

    `SHIPPED → COMPLETED` ผ่าน `apply_order_transition()` ซึ่งเรียก
    `poster_service.mark_sold_by_order()` **เองแล้ว**ตอน `to_status is COMPLETED`
    (INF-33 AC-4 สไลซ์ B) — **ห้ามเรียกซ้ำที่นี่** ดู docstring ของ
    `apply_order_transition()`

    เขียน `delivered_at`/`delivered_confirmed_by=ADMIN` เพิ่มจากสิ่งที่ประตูทำอยู่
    แล้ว — มติเจ้าของ (GATE 1 §10.2): ไม่เขียน = นาฬิกาล้าง 90 วันของชั้น ข
    (ADR-0020 D12.2 · A4-D1) ไม่เริ่ม · `ADMIN` เพราะไม่มี endpoint ให้ผู้ซื้อกด
    ยืนยันเองในรอบนี้ (ทรงเดียวกับเหตุผลที่ `ship_order()` ใช้ actor เป็นแอดมิน)
    """
    order = await apply_order_transition(
        session,
        order_id,
        to_status=OrderStatus.COMPLETED,
        actor_user_id=actor_user_id,
        reason=None,
        at=at,
    )
    order.delivered_at = at
    order.delivered_confirmed_by = DeliveryConfirmActor.ADMIN
    await session.flush()
    return order
