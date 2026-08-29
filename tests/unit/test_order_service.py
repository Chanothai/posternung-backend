"""ประตูของเครื่อง order + เส้นทางเกิดของออร์เดอร์ — INF-33 AC-1/AC-3 · ADR-0033

🔴 **ทุกเทสในไฟล์นี้ให้ service เป็นคนสร้างสถานะ ไม่จัดฉาก `status` ด้วยมือ**
(`test-quality` §3.1) — ยกเว้นจุดเดียวที่เขียนกำกับไว้ว่าทำไมต้องจัดฉาก
(เทสด่านผู้ซื้อ ≠ ผู้ขายของ `create_order()` ซึ่งเส้นทางปกติถูก `reserve_listing()`
ปฏิเสธไปก่อนแล้ว — เป็นการพิสูจน์ว่าด่านชั้นที่สองมีจริง ไม่ใช่พึ่งชั้นแรก)
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from sqlalchemy.exc import IntegrityError

from app.core.exceptions import (
    BuyerIsSeller,
    ListingTransitionNotAllowed,
    OrderCancellationReasonRequired,
    OrderTransitionNotAllowed,
    PosterNotAvailable,
    PosterNotFound,
    ReservationLimitExceeded,
    ReservationNotActive,
    ReservationNotFound,
)
from app.models.enums import (
    OrderStatus,
    PosterCondition,
    PosterStatus,
    ReservationStatus,
)
from app.models.order import Order, OrderStatusHistory
from app.models.platform import NotificationOutbox, PlatformSetting
from app.models.poster import Poster
from app.models.poster_attribute_review import PosterAttributeReview
from app.models.reservation import Reservation
from app.models.seller import SellerProfile
from app.models.user import User
from app.services import order_service, poster_service

NOW = datetime(2026, 3, 2, 4, 0, tzinfo=UTC)  # 11:00 ตามเวลาไทย
PUBLISHED_AT = datetime(2026, 1, 1, tzinfo=UTC)
APPROVED_AT = datetime(2026, 1, 2, tzinfo=UTC)
# ck_posters_published_requires_verified (ADR-0027 A3-D1 · INF-38) — ต่างจาก
# PUBLISHED_AT โดยตั้งใจ (มีแค่ NULL/ไม่ NULL เท่านั้นที่นับต่อกฎ)
VERIFIED_AT = datetime(2026, 1, 1, 6, 0, tzinfo=UTC)


async def _a_user(session: AsyncSession, label: str) -> User:
    user = User(email=f"{label}-{uuid.uuid4().hex[:8]}@example.test", is_verified=True)
    session.add(user)
    await session.flush()
    return user


async def _a_seller(
    session: AsyncSession, *, commission_rate_bps: int | None = None
) -> SellerProfile:
    """ผู้ขายจริง (ไม่ใช่ house account) — เส้นทางที่คิดคอมมิชชั่นจริง

    fixture default ต้องเป็น **เคสปกติของ production** (`test-quality` §6) ⇒ ใช้
    ผู้ขายรายอื่นที่ไม่ใช่ร้านเราเอง ไม่งั้นเส้นทางคำนวณคอมจะไม่เคยถูกรันเลย
    """
    owner = await _a_user(session, "seller")
    seller = SellerProfile(
        user_id=owner.id,
        display_name="ร้านทดสอบ",
        real_name="ผู้ขายทดสอบ",
        bank_name="ธนาคารทดสอบ",
        bank_account_name="ผู้ขายทดสอบ",
        bank_account_no="0000000000",
        commission_rate_bps=commission_rate_bps,
    )
    session.add(seller)
    await session.flush()
    return seller


async def _a_listing(
    session: AsyncSession,
    seller: SellerProfile,
    *,
    price: Decimal = Decimal("4500.00"),
    shipping_fee: Decimal = Decimal("150.00"),
    published_at: datetime | None = PUBLISHED_AT,
    # ck_posters_published_requires_verified (ADR-0027 A3-D1 · INF-38) — status
    # เป็น available เสมอในไฟล์นี้ (ไม่ใช่ sold) ⇒ published ต้องมีลายเซ็นคู่กันเสมอ
    # ไม่งั้นชนกับ CHECK ตัวใหม่ตั้งแต่ INSERT
    verified_at: datetime | None = VERIFIED_AT,
) -> Poster:
    assert not (
        published_at is not None and verified_at is None
    ), "listing แบบ available ที่ published ต้องมี verified_at คู่กันเสมอ (A3-D1)"
    poster = Poster(
        seller_id=seller.id,
        approved_at=APPROVED_AT,
        title="The Matrix",
        price=price,
        shipping_fee=shipping_fee,
        condition_grade=PosterCondition.very_fine,
        status=PosterStatus.available,
        published_at=published_at,
        verified_at=verified_at,
    )
    session.add(poster)
    await session.flush()
    return poster


async def _setting_int(session: AsyncSession, key: str) -> int:
    """อ่าน config ที่เทสต้องใช้ — 🔴 **ห้าม hardcode 60 หรือ 3 ในเทสเช่นกัน**
    (ADR-0030 D3 · ADR-0033 OD-3 · ถ้อยคำของ OD-3 ครอบ "ในโค้ดหรือเทส" ทั้งคู่)
    """
    setting = await session.get(PlatformSetting, key)
    assert setting is not None, f"migration ต้องใส่คีย์ {key} มาแล้ว"
    return int(setting.value)


async def _set_setting(session: AsyncSession, key: str, value: str) -> None:
    setting = await session.get(PlatformSetting, key)
    assert setting is not None, f"migration ต้องใส่คีย์ {key} มาแล้ว"
    setting.value = value
    await session.flush()


async def _count(session: AsyncSession, model) -> int:
    return await session.scalar(select(func.count()).select_from(model))


async def _outbox_for(session: AsyncSession, user_id: uuid.UUID) -> list[str]:
    rows = await session.execute(
        select(NotificationOutbox.template_key).where(
            NotificationOutbox.recipient_user_id == user_id
        )
    )
    return sorted(rows.scalars().all())


# ══════════════════════════════════════════════════════════════════════════
# เส้นทางจอง
# ══════════════════════════════════════════════════════════════════════════


async def test_reserving_moves_the_listing_and_notifies_both_parties(
    db_session: AsyncSession,
) -> None:
    """BR-B1 + BR-P8 — จองสำเร็จ listing ไป `reserved` และทั้งสองฝ่ายได้แจ้งเตือน"""
    seller = await _a_seller(db_session)
    poster = await _a_listing(db_session, seller)
    buyer = await _a_user(db_session, "buyer")

    reservation = await order_service.reserve_listing(
        db_session, poster.id, buyer_user_id=buyer.id, at=NOW
    )

    assert reservation.status is ReservationStatus.active
    assert poster.status is PosterStatus.reserved
    # TTL มาจาก config (ADR-0030 D3) ไม่ใช่เลขในโค้ด
    ttl_minutes = await _setting_int(db_session, "reservation_ttl_minutes")
    assert reservation.expires_at == NOW + timedelta(minutes=ttl_minutes)

    assert await _outbox_for(db_session, buyer.id) == ["listing_reserved_buyer"]
    assert await _outbox_for(db_session, seller.user_id) == ["listing_reserved_seller"]

    # ADR-0025 A1-D3 — ทุกครั้งที่ posters.status เปลี่ยน ต้องมีร่องรอยที่ค้นด้วย poster_id ได้
    audit = await db_session.scalar(
        select(func.count(PosterAttributeReview.id)).where(
            PosterAttributeReview.poster_id == poster.id,
            PosterAttributeReview.field == "status",
        )
    )
    assert audit == 1


async def test_the_seller_cannot_reserve_their_own_listing(
    db_session: AsyncSession,
) -> None:
    """🔴 INF-33 `known_gap` ข้อ 2 · ADR-0033 OD-1 — ด่านที่ `reserve` (ทาง (ข))

    ถ้าด่านอยู่ที่ `create_order` อย่างเดียว ผู้ขายจะกดจองของตัวเองค้างได้ 60 นาที
    (ของหายจากหน้าร้านโดยไม่มีใครซื้อได้) — เทสนี้จับกรณีนั้นตรง ๆ
    """
    seller = await _a_seller(db_session)
    poster = await _a_listing(db_session, seller)

    with pytest.raises(BuyerIsSeller):
        await order_service.reserve_listing(
            db_session, poster.id, buyer_user_id=seller.user_id, at=NOW
        )

    assert poster.status is PosterStatus.available  # ของยังอยู่บนหน้าร้าน
    assert await _count(db_session, Reservation) == 0


async def test_the_seller_cannot_create_an_order_for_their_own_listing(
    db_session: AsyncSession,
) -> None:
    """ด่านชั้นที่สองของ ADR-0033 OD-1 — ที่ `create_order()`

    🔴 **จุดเดียวในไฟล์นี้ที่จัดฉากแถวด้วยมือ และตั้งใจ**: เส้นทางปกติไปถึงตรงนี้ไม่ได้
    เพราะ `reserve_listing()` ปฏิเสธไปก่อนแล้ว · ถ้าไม่จัดฉาก เราจะพิสูจน์ไม่ได้เลยว่า
    ด่านชั้นที่สองมีอยู่จริง — และ ADR-0033 OD-1 เลือกทาง (ข) ก็เพราะวันหน้าจะมี
    เส้นทางสร้างออร์เดอร์ที่ไม่ผ่าน `reserve_listing()`
    """
    seller = await _a_seller(db_session)
    poster = await _a_listing(db_session, seller)
    ttl_minutes = await _setting_int(db_session, "reservation_ttl_minutes")
    reservation = Reservation(
        poster_id=poster.id,
        user_id=seller.user_id,
        status=ReservationStatus.active,
        expires_at=NOW + timedelta(minutes=ttl_minutes),
    )
    db_session.add(reservation)
    await db_session.flush()

    with pytest.raises(BuyerIsSeller):
        await order_service.create_order(
            db_session, reservation.id, buyer_user_id=seller.user_id, at=NOW
        )

    assert await _count(db_session, Order) == 0


async def test_a_different_buyer_can_reserve_and_then_order(
    db_session: AsyncSession,
) -> None:
    """เทสเชิงบวกคู่กับสองเทสข้างบน — คนอื่นทำได้ทั้งสองเส้น (ไม่ใช่ด่านที่กันทุกคน)"""
    seller = await _a_seller(db_session)
    poster = await _a_listing(db_session, seller)
    buyer = await _a_user(db_session, "buyer")

    reservation = await order_service.reserve_listing(
        db_session, poster.id, buyer_user_id=buyer.id, at=NOW
    )
    order = await order_service.create_order(
        db_session, reservation.id, buyer_user_id=buyer.id, at=NOW
    )

    assert order.status is OrderStatus.AWAITING_PAYMENT
    assert order.buyer_id == buyer.id
    assert order.seller_id == seller.id
    assert reservation.status is ReservationStatus.converted
    assert poster.status is PosterStatus.reserved  # ยังไม่ขาย จนกว่าจะ COMPLETED


async def test_the_reservation_cap_comes_from_platform_settings(
    db_session: AsyncSession,
) -> None:
    """ADR-0033 OD-3 — 🔴 เพดานอ่านจาก config **ห้าม hardcode เลข 3**

    เทสตั้งค่าเป็น 1 แล้วคาดว่าใบที่สองถูกปฏิเสธ · โค้ดที่ hardcode 3 จะปล่อยผ่าน
    ⇒ เทสนี้แดงทันทีถ้ามีใครเอาเลขกลับเข้าไปในโค้ด (และไม่มีเลข 3 อยู่ในเทสนี้เลย)
    """
    await _set_setting(db_session, "max_active_reservations_per_user", "1")
    seller = await _a_seller(db_session)
    first = await _a_listing(db_session, seller)
    second = await _a_listing(db_session, seller)
    buyer = await _a_user(db_session, "buyer")

    await order_service.reserve_listing(
        db_session, first.id, buyer_user_id=buyer.id, at=NOW
    )

    with pytest.raises(ReservationLimitExceeded):
        await order_service.reserve_listing(
            db_session, second.id, buyer_user_id=buyer.id, at=NOW
        )

    assert second.status is PosterStatus.available


async def test_the_reservation_ttl_comes_from_platform_settings(
    db_session: AsyncSession,
) -> None:
    """ADR-0030 D3 — 🔴 TTL เป็น config **ห้าม hardcode 60** (จะถูกจูนหลัง beta แน่นอน)"""
    await _set_setting(db_session, "reservation_ttl_minutes", "7")
    seller = await _a_seller(db_session)
    poster = await _a_listing(db_session, seller)
    buyer = await _a_user(db_session, "buyer")

    reservation = await order_service.reserve_listing(
        db_session, poster.id, buyer_user_id=buyer.id, at=NOW
    )

    assert reservation.expires_at == NOW + timedelta(minutes=7)


async def test_an_unpublished_listing_cannot_be_reserved(
    db_session: AsyncSession,
) -> None:
    """ADR-0013 D2 — ใบที่ยังไม่ถูกตั้งวางบนชั้นต้องไม่มีใครจองได้ และตอบเหมือนไม่มีแถว"""
    seller = await _a_seller(db_session)
    poster = await _a_listing(db_session, seller, published_at=None)
    buyer = await _a_user(db_session, "buyer")

    with pytest.raises(PosterNotFound):
        await order_service.reserve_listing(
            db_session, poster.id, buyer_user_id=buyer.id, at=NOW
        )

    assert await _count(db_session, Reservation) == 0


# ══════════════════════════════════════════════════════════════════════════
# lazy-expire (ADR-0033 D4 · BR-P9)
# ══════════════════════════════════════════════════════════════════════════


async def test_an_expired_reservation_is_released_without_waiting_for_a_scheduler(
    db_session: AsyncSession,
) -> None:
    """🔴 ADR-0033 **D4** — ถ้าปล่อยให้ scheduler เป็นคนเดียวที่พลิก จะมีช่วงเวลาที่ของ
    "ว่างแล้วแต่จองไม่ได้" ยาวเท่ากับคาบของ scheduler (partial unique index กันไว้)

    เทสนี้ไม่เรียก scheduler ใด ๆ — ผู้ซื้อคนที่สองมาจองหลัง TTL หมด แล้วต้องจองได้เลย
    """
    seller = await _a_seller(db_session)
    poster = await _a_listing(db_session, seller)
    first_buyer = await _a_user(db_session, "buyer-a")
    second_buyer = await _a_user(db_session, "buyer-b")

    stale = await order_service.reserve_listing(
        db_session, poster.id, buyer_user_id=first_buyer.id, at=NOW
    )
    later = stale.expires_at + timedelta(seconds=1)

    fresh = await order_service.reserve_listing(
        db_session, poster.id, buyer_user_id=second_buyer.id, at=later
    )

    assert stale.status is ReservationStatus.expired
    assert fresh.status is ReservationStatus.active
    assert fresh.user_id == second_buyer.id
    assert poster.status is PosterStatus.reserved


async def test_a_reservation_is_not_expired_once_the_buyer_says_they_transferred(
    db_session: AsyncSession,
) -> None:
    """🔴 **BR-P9 · ADR-0029 D5 ข้อ 1** — กดแจ้งโอนแล้ว = หยุดนาฬิกาจอง

    ของค้างที่ `reserved` รอแอดมินตัดสิน **ห้ามปล่อยกลับ `active` อัตโนมัติ**
    ไม่งั้นจะเกิดเคส "เงินเข้าบัญชีเรา ของไม่มีแล้ว" ซึ่งแก้ได้ด้วยคนเท่านั้น

    สถานะ `PAYMENT_REVIEW` ถูกสร้างโดย **ประตูจริง** ไม่ได้จัดฉากด้วยมือ
    """
    seller = await _a_seller(db_session)
    poster = await _a_listing(db_session, seller)
    first_buyer = await _a_user(db_session, "buyer-a")
    second_buyer = await _a_user(db_session, "buyer-b")

    reservation = await order_service.reserve_listing(
        db_session, poster.id, buyer_user_id=first_buyer.id, at=NOW
    )
    order = await order_service.create_order(
        db_session, reservation.id, buyer_user_id=first_buyer.id, at=NOW
    )
    # ผู้ซื้อกด "แจ้งว่าโอนแล้ว"
    await order_service.apply_order_transition(
        db_session,
        order.id,
        to_status=OrderStatus.PAYMENT_REVIEW,
        actor_user_id=first_buyer.id,
        reason=None,
        at=NOW,
    )
    # 🔴 การจองถูกพลิกเป็น converted ไปแล้วตอนสร้างออร์เดอร์ — จำลองเคสที่นาฬิกา
    # ยังเดินอยู่ด้วยการคืนสถานะ active เพื่อให้ด่าน BR-P9 เป็นสิ่งเดียวที่กันไว้
    reservation.status = ReservationStatus.active
    await db_session.flush()

    later = reservation.expires_at + timedelta(seconds=1)
    with pytest.raises(PosterNotAvailable):
        await order_service.reserve_listing(
            db_session, poster.id, buyer_user_id=second_buyer.id, at=later
        )

    assert reservation.status is ReservationStatus.active  # ไม่ถูกพลิกเป็น expired
    assert poster.status is PosterStatus.reserved  # ของไม่ถูกปล่อยกลับหน้าร้าน


# ══════════════════════════════════════════════════════════════════════════
# ออร์เดอร์: เลขที่ · เงิน · ร่องรอย
# ══════════════════════════════════════════════════════════════════════════


async def _reserve_and_order(
    session: AsyncSession, poster: Poster, buyer: User, *, at: datetime = NOW
) -> Order:
    reservation = await order_service.reserve_listing(
        session, poster.id, buyer_user_id=buyer.id, at=at
    )
    return await order_service.create_order(
        session, reservation.id, buyer_user_id=buyer.id, at=at
    )


async def test_order_snapshots_the_money_at_creation_time(
    db_session: AsyncSession,
) -> None:
    """BR-L7 — คอมมิชชั่นคิดจาก **ราคาสินค้าเท่านั้น ไม่คิดจากค่าส่ง**

    ใช้อัตรา override ของผู้ขาย (500 bps = 5% ผู้ขายรุ่นก่อตั้ง) เพื่อพิสูจน์ว่า
    อัตราที่ใช้จริงถูก snapshot ลงแถว ไม่ใช่ค่ากลางที่อ่านสดตอนอ่าน
    """
    seller = await _a_seller(db_session, commission_rate_bps=500)
    poster = await _a_listing(
        db_session, seller, price=Decimal("4500.00"), shipping_fee=Decimal("150.00")
    )
    buyer = await _a_user(db_session, "buyer")

    order = await _reserve_and_order(db_session, poster, buyer)

    assert order.item_price == Decimal("4500.00")
    assert order.shipping_fee == Decimal("150.00")
    assert order.total_amount == Decimal("4650.00")
    assert order.commission_rate_bps == 500
    assert order.commission_amount == Decimal("225.00")  # 5% ของ 4500 ไม่ใช่ของ 4650
    assert order.seller_payout_amount == Decimal("4425.00")
    assert order.item_title == poster.title
    assert order.item_condition_grade is poster.condition_grade


async def test_order_no_uses_the_bangkok_date_not_the_utc_date(
    db_session: AsyncSession,
) -> None:
    """🔴 ADR-0033 **D6** · ADR-0032 D5 — ผิดเฉพาะช่วง 17:00–23:59 UTC
    ซึ่งเป็นช่วงที่เทสที่รันกลางวันจับไม่ได้ ⇒ ต้องมีเทสที่ยิงเวลานั้นตรง ๆ
    """
    seller = await _a_seller(db_session)
    poster = await _a_listing(db_session, seller)
    buyer = await _a_user(db_session, "buyer")
    late_utc = datetime(2026, 3, 2, 17, 30, tzinfo=UTC)  # 3 มี.ค. 00:30 ตามเวลาไทย

    order = await _reserve_and_order(db_session, poster, buyer, at=late_utc)

    assert order.order_no.startswith("PN-260303-"), order.order_no


async def test_order_no_runs_in_sequence_within_the_same_thai_day(
    db_session: AsyncSession,
) -> None:
    """เลขรันมาจากการนับของจริงในตาราง ไม่ใช่ตัวนับแยกที่หลุด sync ได้"""
    seller = await _a_seller(db_session)
    buyer_one = await _a_user(db_session, "buyer-a")
    buyer_two = await _a_user(db_session, "buyer-b")

    first = await _reserve_and_order(
        db_session, await _a_listing(db_session, seller), buyer_one
    )
    second = await _reserve_and_order(
        db_session, await _a_listing(db_session, seller), buyer_two
    )

    assert first.order_no == "PN-260302-0001"
    assert second.order_no == "PN-260302-0002"


async def test_creating_an_order_writes_history_and_notifies_both_parties(
    db_session: AsyncSession,
) -> None:
    """INF-33 AC-3 — ร่องรอยและการแจ้งเตือนเกิดในทรานแซกชันเดียวกับสถานะ"""
    seller = await _a_seller(db_session)
    poster = await _a_listing(db_session, seller)
    buyer = await _a_user(db_session, "buyer")

    order = await _reserve_and_order(db_session, poster, buyer)

    history = (
        (
            await db_session.execute(
                select(OrderStatusHistory).where(
                    OrderStatusHistory.order_id == order.id
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(history) == 1
    assert history[0].from_status is None
    assert history[0].to_status == OrderStatus.AWAITING_PAYMENT.value
    assert history[0].actor_user_id == buyer.id

    assert "order_created_buyer" in await _outbox_for(db_session, buyer.id)
    assert "order_created_seller" in await _outbox_for(db_session, seller.user_id)


async def test_notification_payloads_carry_ids_only(db_session: AsyncSession) -> None:
    """🔴 **ADR-0020 D9** — `payload` ห้ามมีชื่อ/ที่อยู่/เบอร์/อีเมล

    closed-world บนคีย์ทั้งหมดที่ไหลเข้า outbox จากเส้นทางจริง (`test-quality` §4) —
    assertion เชิงลบแบบระบุชื่อจับได้เฉพาะคีย์ที่เราเดาถูก ส่วนความเสี่ยงจริงคือ
    คีย์ใหม่ที่ใครสักคนเพิ่มเข้ามาทีหลัง
    """
    seller = await _a_seller(db_session)
    poster = await _a_listing(db_session, seller)
    buyer = await _a_user(db_session, "buyer")

    await _reserve_and_order(db_session, poster, buyer)

    payloads = (
        (await db_session.execute(select(NotificationOutbox.payload))).scalars().all()
    )
    assert payloads, "ต้องมีแถวแจ้งเตือนเกิดขึ้นจริง ไม่งั้นเทสนี้ไม่ได้ตรวจอะไรเลย"
    keys = {key for payload in payloads for key in payload}
    assert keys == {
        "poster_id",
        "reservation_id",
        "expires_at",
        "from_status",
        "to_status",
        "order_id",
        "order_no",
    }


# ══════════════════════════════════════════════════════════════════════════
# ประตูของเครื่อง order
# ══════════════════════════════════════════════════════════════════════════


async def test_a_transition_outside_the_rulebook_leaves_no_trace_behind(
    db_session: AsyncSession,
) -> None:
    """INF-33 AC-1 — เส้นที่ไม่อยู่ในตารางกฎถูกปฏิเสธ **และไม่มีแถวร่องรอยเกิดขึ้นเลย**

    ถ้าประตูเขียน history/outbox ก่อนตรวจกฎ เทสนี้จะแดง — นั่นคือสิ่งที่มันคุ้ม
    """
    seller = await _a_seller(db_session)
    poster = await _a_listing(db_session, seller)
    buyer = await _a_user(db_session, "buyer")
    order = await _reserve_and_order(db_session, poster, buyer)

    history_before = await _count(db_session, OrderStatusHistory)
    outbox_before = await _count(db_session, NotificationOutbox)

    with pytest.raises(OrderTransitionNotAllowed):
        await order_service.apply_order_transition(
            db_session,
            order.id,
            to_status=OrderStatus.SHIPPED,  # ข้ามการจ่ายเงินทั้งขั้น
            actor_user_id=seller.user_id,
            reason=None,
            at=NOW,
        )

    assert order.status is OrderStatus.AWAITING_PAYMENT
    assert await _count(db_session, OrderStatusHistory) == history_before
    assert await _count(db_session, NotificationOutbox) == outbox_before


async def test_cancelling_without_a_reason_is_a_domain_error_not_a_db_error(
    db_session: AsyncSession,
) -> None:
    """🔴 ADR-0033 D2 — ถ้าไม่ตรวจก่อน `flush()` `ck_orders_cancelled_requires_reason`
    จะระเบิดเป็น `IntegrityError` ดิบ ซึ่งกลายเป็น **500**

    ตัวชี้ขาดว่าเราไม่เคยไปถึง CHECK คือ **ทรานแซกชันยังใช้งานต่อได้** หลัง error —
    `IntegrityError` จะทำให้ทรานแซกชันพังจน query ถัดไปทำไม่ได้
    """
    seller = await _a_seller(db_session)
    poster = await _a_listing(db_session, seller)
    buyer = await _a_user(db_session, "buyer")
    order = await _reserve_and_order(db_session, poster, buyer)

    with pytest.raises(OrderCancellationReasonRequired):
        await order_service.apply_order_transition(
            db_session,
            order.id,
            to_status=OrderStatus.CANCELLED,
            actor_user_id=buyer.id,
            reason="   ",
            at=NOW,
        )

    assert await _count(db_session, Order) == 1  # ทรานแซกชันยังไม่พัง
    assert order.status is OrderStatus.AWAITING_PAYMENT


async def test_cancelling_with_a_reason_records_who_why_and_when(
    db_session: AsyncSession,
) -> None:
    seller = await _a_seller(db_session)
    poster = await _a_listing(db_session, seller)
    buyer = await _a_user(db_session, "buyer")
    order = await _reserve_and_order(db_session, poster, buyer)

    await order_service.apply_order_transition(
        db_session,
        order.id,
        to_status=OrderStatus.CANCELLED,
        actor_user_id=buyer.id,
        reason="ผู้ซื้อขอยกเลิกก่อนโอน",
        at=NOW,
    )

    assert order.status is OrderStatus.CANCELLED
    assert order.cancellation_reason == "ผู้ซื้อขอยกเลิกก่อนโอน"
    assert order.cancelled_at == NOW

    # 🔴 **ห้ามเรียงด้วย `created_at`** — `server_default now()` คือเวลาของ *ทรานแซกชัน*
    # แถวที่เกิดในทรานแซกชันเดียวกันจึงมี timestamp เท่ากันเป๊ะ และลำดับที่ได้กลับมา
    # ไม่แน่นอน (เทสนี้เคยแดงแบบสุ่มจริงตอนเขียนใบนี้) ⇒ assert เป็น **เซตของคู่
    # (from → to)** ซึ่งบอกลำดับได้ในตัวและไม่ขึ้นกับการจัดเรียงของ DB
    history = (
        (
            await db_session.execute(
                select(OrderStatusHistory).where(
                    OrderStatusHistory.order_id == order.id
                )
            )
        )
        .scalars()
        .all()
    )
    assert {(row.from_status, row.to_status) for row in history} == {
        (None, OrderStatus.AWAITING_PAYMENT.value),
        (OrderStatus.AWAITING_PAYMENT.value, OrderStatus.CANCELLED.value),
    }
    cancelled_row = next(
        row for row in history if row.to_status == OrderStatus.CANCELLED.value
    )
    assert cancelled_row.reason == "ผู้ซื้อขอยกเลิกก่อนโอน"
    assert "order_cancelled_buyer" in await _outbox_for(db_session, buyer.id)
    assert "order_cancelled_seller" in await _outbox_for(db_session, seller.user_id)


async def test_a_system_transition_records_no_actor_rather_than_a_fake_one(
    db_session: AsyncSession,
) -> None:
    """`actor_user_id = None` แปลว่า **ระบบเปลี่ยนเอง** ไม่ใช่ "ไม่รู้ว่าใคร"
    (docstring ของ `OrderStatusHistory` เป็นเจ้าของนิยามนี้)
    """
    seller = await _a_seller(db_session)
    poster = await _a_listing(db_session, seller)
    buyer = await _a_user(db_session, "buyer")
    order = await _reserve_and_order(db_session, poster, buyer)

    await order_service.apply_order_transition(
        db_session,
        order.id,
        to_status=OrderStatus.CANCELLED,
        actor_user_id=None,
        reason="หมดเวลาจอง",
        at=NOW,
    )

    # เลือกแถวด้วย `to_status` ไม่ใช่ด้วยเวลา — ดูเหตุผลในเทสยกเลิกข้างบน
    cancelled_row = (
        (
            await db_session.execute(
                select(OrderStatusHistory).where(
                    OrderStatusHistory.order_id == order.id,
                    OrderStatusHistory.to_status == OrderStatus.CANCELLED.value,
                )
            )
        )
        .scalars()
        .one()
    )
    assert cancelled_row.actor_user_id is None


# ══════════════════════════════════════════════════════════════════════════
# ประตูของเครื่อง listing — ด่านที่กัน AC-4 ไม่ให้หลุดมาในสไลซ์นี้
# ══════════════════════════════════════════════════════════════════════════


async def test_the_listing_gate_refuses_to_write_sold(
    db_session: AsyncSession,
) -> None:
    """🔴 INF-33 **AC-4 ไม่อยู่ในสไลซ์นี้** — `sold` ต้องเขียน `sold_at` ในคำสั่งเดียวกัน
    (`ck_posters_sold_requires_sold_at`) ซึ่งเป็นสัญญาของ `mark_sold()` /
    `mark_sold_by_order()` (ADR-0025 D1 · A1-D1) ไม่ใช่ของประตูตัวนี้

    ถ้าด่านนี้หายไป ผลไม่ใช่ "ขายได้เร็วขึ้น" แต่เป็น `IntegrityError` ดิบ = 500
    """
    seller = await _a_seller(db_session)
    poster = await _a_listing(db_session, seller)
    buyer = await _a_user(db_session, "buyer")
    await order_service.reserve_listing(
        db_session, poster.id, buyer_user_id=buyer.id, at=NOW
    )

    with pytest.raises(ListingTransitionNotAllowed):
        await poster_service.apply_listing_transition(
            db_session,
            poster.id,
            to_status=PosterStatus.sold,
            actor_user_id=None,
            reason="ปิดการขาย",
            at=NOW,
        )

    assert poster.status is PosterStatus.reserved
    assert poster.sold_at is None


async def test_the_listing_gate_rejects_an_edge_outside_the_rulebook(
    db_session: AsyncSession,
) -> None:
    """`available → sold` ไม่มีในกราฟเลย (ต้องผ่าน `reserved` เสมอ — ADR-0028 D4)"""
    seller = await _a_seller(db_session)
    poster = await _a_listing(db_session, seller)

    with pytest.raises(ListingTransitionNotAllowed):
        await poster_service.apply_listing_transition(
            db_session,
            poster.id,
            to_status=PosterStatus.draft,
            actor_user_id=None,
            reason=None,
            at=NOW,
        )

    assert poster.status is PosterStatus.available


# ══════════════════════════════════════════════════════════════════════════
# 🔴 H1 (code-critic รอบ 1) — เพดานจองต้องไม่ล็อกผู้ใช้ถาวร
# ══════════════════════════════════════════════════════════════════════════


async def test_reservations_that_ran_out_of_time_stop_counting_against_the_cap(
    db_session: AsyncSession,
) -> None:
    """🔴 **H1** — แถวที่หมดเวลาแล้วแต่ยังไม่มีใครพลิกเป็น `expired` ต้อง **ไม่ถูกนับ**

    lazy-expire (ADR-0033 D4) พลิกให้เฉพาะโปสเตอร์ **ใบที่กำลังถูกจอง** ⇒ แถวเก่าของ
    ผู้ใช้คนนี้บนโปสเตอร์ใบอื่นยังเป็น `active` ค้างอยู่ตลอด · ถ้าเพดานนับด้วย
    `status` อย่างเดียว ผู้ใช้ที่ปล่อยจองหลุดครบเพดาน **จองอะไรไม่ได้อีกเลยตลอดกาล**
    · และจะอ้างว่า scheduler เก็บให้ไม่ได้ เพราะ scheduler เป็น AC-7 ที่ยังไม่มี

    เทสนี้พิสูจน์ **สองด้านในใบเดียว** ซึ่งเป็นสิ่งที่ทำให้มันไม่โมฆะ:
    ก่อนหมดเวลา = เพดานต้องยังยิง · หลังหมดเวลา = เพดานต้องปล่อยผ่าน
    (ถ้าเทสมีแต่ครึ่งหลัง การถอดเพดานทิ้งทั้งข้อก็ยังเขียว)
    """
    cap = await _setting_int(db_session, "max_active_reservations_per_user")
    ttl_minutes = await _setting_int(db_session, "reservation_ttl_minutes")
    seller = await _a_seller(db_session)
    posters = [await _a_listing(db_session, seller) for _ in range(cap + 1)]
    buyer = await _a_user(db_session, "buyer")

    for poster in posters[:cap]:
        await order_service.reserve_listing(
            db_session, poster.id, buyer_user_id=buyer.id, at=NOW
        )

    # ครึ่งแรก — ยังอยู่ในเวลา เพดานต้องยิง
    with pytest.raises(ReservationLimitExceeded):
        await order_service.reserve_listing(
            db_session, posters[cap].id, buyer_user_id=buyer.id, at=NOW
        )

    # ครึ่งหลัง — เลยเวลาของทุกใบแล้ว ต้องจองใบถัดไปได้ทันทีโดยไม่ต้องรอ scheduler
    later = NOW + timedelta(minutes=ttl_minutes + 1)
    reservation = await order_service.reserve_listing(
        db_session, posters[cap].id, buyer_user_id=buyer.id, at=later
    )

    assert reservation.status is ReservationStatus.active
    assert posters[cap].status is PosterStatus.reserved
    # แถวเก่ายัง `active` อยู่จริง — พิสูจน์ว่าที่ผ่านได้ไม่ใช่เพราะมีใครไปพลิกให้
    stale = (
        (
            await db_session.execute(
                select(Reservation).where(
                    Reservation.user_id == buyer.id,
                    Reservation.poster_id.in_([poster.id for poster in posters[:cap]]),
                )
            )
        )
        .scalars()
        .all()
    )
    assert [row.status for row in stale] == [ReservationStatus.active] * cap


# ══════════════════════════════════════════════════════════════════════════
# 🔴 H2 (code-critic รอบ 1) — ด่านของ create_order() ที่ยังไม่เคยถูกรัน
# ══════════════════════════════════════════════════════════════════════════


async def test_a_reservation_that_belongs_to_someone_else_is_reported_as_not_found(
    db_session: AsyncSession,
) -> None:
    """ownership — และ **ตอบ 404 เหมือนไม่มีใบนี้ ไม่ใช่ 403**

    การแยกรหัสจะยืนยันให้คนไล่เดา id ได้ว่าแถวนี้มีอยู่จริง (หลักเดียวกับที่
    `get_poster_detail()` ตอบ 404 กับใบที่ยังไม่ publish)
    """
    seller = await _a_seller(db_session)
    poster = await _a_listing(db_session, seller)
    owner = await _a_user(db_session, "buyer-a")
    intruder = await _a_user(db_session, "buyer-b")

    reservation = await order_service.reserve_listing(
        db_session, poster.id, buyer_user_id=owner.id, at=NOW
    )

    with pytest.raises(ReservationNotFound):
        await order_service.create_order(
            db_session, reservation.id, buyer_user_id=intruder.id, at=NOW
        )

    assert await _count(db_session, Order) == 0
    assert reservation.status is ReservationStatus.active  # ของยังอยู่กับเจ้าของเดิม


async def test_an_unknown_reservation_id_is_not_found(
    db_session: AsyncSession,
) -> None:
    with pytest.raises(ReservationNotFound):
        await order_service.create_order(
            db_session, uuid.uuid4(), buyer_user_id=uuid.uuid4(), at=NOW
        )


async def test_a_reservation_that_ran_out_of_time_cannot_become_an_order(
    db_session: AsyncSession,
) -> None:
    """หมดเวลาแล้วสร้างออร์เดอร์ไม่ได้ — ไม่ใช่ "ยังไม่มีใครพลิกก็ถือว่ายังใช้ได้"

    ตัวตัดสินคือ `expires_at` เทียบกับ `at` ที่ผู้เรียกส่งมา ไม่ใช่ `status`
    (แถวยังเป็น `active` อยู่ตอนที่ถูกปฏิเสธ — assert ไว้ด้านล่าง)
    """
    ttl_minutes = await _setting_int(db_session, "reservation_ttl_minutes")
    seller = await _a_seller(db_session)
    poster = await _a_listing(db_session, seller)
    buyer = await _a_user(db_session, "buyer")

    reservation = await order_service.reserve_listing(
        db_session, poster.id, buyer_user_id=buyer.id, at=NOW
    )
    too_late = NOW + timedelta(minutes=ttl_minutes + 1)

    with pytest.raises(ReservationNotActive):
        await order_service.create_order(
            db_session, reservation.id, buyer_user_id=buyer.id, at=too_late
        )

    assert reservation.status is ReservationStatus.active
    assert await _count(db_session, Order) == 0


async def test_a_reservation_cannot_be_converted_into_a_second_order(
    db_session: AsyncSession,
) -> None:
    """กดสร้างออร์เดอร์รัว ๆ ด้วยการจองใบเดิม — ใบที่สองต้องถูกปฏิเสธที่ `converted`"""
    seller = await _a_seller(db_session)
    poster = await _a_listing(db_session, seller)
    buyer = await _a_user(db_session, "buyer")

    reservation = await order_service.reserve_listing(
        db_session, poster.id, buyer_user_id=buyer.id, at=NOW
    )
    await order_service.create_order(
        db_session, reservation.id, buyer_user_id=buyer.id, at=NOW
    )

    with pytest.raises(ReservationNotActive):
        await order_service.create_order(
            db_session, reservation.id, buyer_user_id=buyer.id, at=NOW
        )

    assert await _count(db_session, Order) == 1


async def test_a_second_live_order_on_the_same_poster_is_a_409_not_a_500(
    db_session: AsyncSession,
) -> None:
    """🔴 **ชั้นที่ 3 ของการกันซื้อซ้อน** (`uq_live_order_per_poster` · INF-32)

    เส้นทางปกติมาถึงตรงนี้ไม่ได้ (การจองใบที่สองถูกกันตั้งแต่ชั้นที่ 1/2) จึงต้อง
    **จัดฉากแถวจอง** ให้ผู้ซื้อคนที่สอง — เขียนกำกับไว้ว่าจัดฉากเพราะอะไร ไม่ใช่
    เพราะสะดวก · ถ้าไม่ทดสอบเส้นนี้ การ map `IntegrityError → 409` จะไม่มีอะไรยืนยัน
    และจะกลายเป็น **500 เงียบ ๆ** ในวันที่ชั้นบนรั่ว

    `begin_nested()` ครอบไว้เพราะ `IntegrityError` ทำให้ทรานแซกชันปัจจุบันใช้ต่อไม่ได้
    จนกว่าจะย้อนกลับ — savepoint ทำให้เทส assert ต่อได้หลังจากนั้น
    """
    ttl_minutes = await _setting_int(db_session, "reservation_ttl_minutes")
    seller = await _a_seller(db_session)
    poster = await _a_listing(db_session, seller)
    first_buyer = await _a_user(db_session, "buyer-a")
    second_buyer = await _a_user(db_session, "buyer-b")

    reservation = await order_service.reserve_listing(
        db_session, poster.id, buyer_user_id=first_buyer.id, at=NOW
    )
    await order_service.create_order(
        db_session, reservation.id, buyer_user_id=first_buyer.id, at=NOW
    )

    # แถวจองของคนที่สอง — เกิดขึ้นได้จริงในตารางเพราะใบแรกเป็น `converted` ไปแล้ว
    # (`uq_active_reservation_per_poster` จึงไม่กัน) แต่ออร์เดอร์ใบเดิมยังไม่จบ
    queued = Reservation(
        poster_id=poster.id,
        user_id=second_buyer.id,
        status=ReservationStatus.active,
        expires_at=NOW + timedelta(minutes=ttl_minutes),
    )
    db_session.add(queued)
    await db_session.flush()

    with pytest.raises(PosterNotAvailable) as caught:
        async with db_session.begin_nested():
            await order_service.create_order(
                db_session, queued.id, buyer_user_id=second_buyer.id, at=NOW
            )

    assert caught.value.status_code == 409
    assert await _count(db_session, Order) == 1


async def test_the_constraint_names_that_the_409_mapping_depends_on_are_real(
    db_session: AsyncSession,
) -> None:
    """🔴 การ map `IntegrityError → 409` พึ่ง **substring ของ `str(exc.orig)`**
    ⇒ ถ้าชื่อ constraint เปลี่ยนหรือ driver เปลี่ยนรูปข้อความ การ map จะเงียบ ๆ
    กลายเป็น **500** โดยไม่มีเทสไหนแดง — เทสนี้ตรึงข้อเท็จจริงที่การ map พึ่งอยู่

    ยิงตรงเข้า DB ให้ constraint ระเบิดจริง แล้วอ่านข้อความที่ได้กลับมา
    (ไม่ผ่าน service เพราะสิ่งที่ตรวจคือ *ข้อความของ DB* ไม่ใช่พฤติกรรมของ service)
    """
    ttl_minutes = await _setting_int(db_session, "reservation_ttl_minutes")
    seller = await _a_seller(db_session)
    poster = await _a_listing(db_session, seller)
    buyer = await _a_user(db_session, "buyer")

    db_session.add(
        Reservation(
            poster_id=poster.id,
            user_id=buyer.id,
            status=ReservationStatus.active,
            expires_at=NOW + timedelta(minutes=ttl_minutes),
        )
    )
    await db_session.flush()

    with pytest.raises(IntegrityError) as reservation_clash:
        async with db_session.begin_nested():
            db_session.add(
                Reservation(
                    poster_id=poster.id,
                    user_id=buyer.id,
                    status=ReservationStatus.active,
                    expires_at=NOW + timedelta(minutes=ttl_minutes),
                )
            )
            await db_session.flush()
    assert "uq_active_reservation_per_poster" in str(reservation_clash.value.orig)

    db_session.add(_raw_order(poster, seller, buyer, "PN-260302-9001"))
    await db_session.flush()

    with pytest.raises(IntegrityError) as order_clash:
        async with db_session.begin_nested():
            db_session.add(_raw_order(poster, seller, buyer, "PN-260302-9002"))
            await db_session.flush()
    assert "uq_live_order_per_poster" in str(order_clash.value.orig)


def _raw_order(
    poster: Poster, seller: SellerProfile, buyer: User, order_no: str
) -> Order:
    """ออร์เดอร์ที่ผ่าน CHECK ทุกตัวของ `orders` — ใช้เฉพาะเทสที่ตรวจกฎ *ระดับ DB*"""
    return Order(
        order_no=order_no,
        poster_id=poster.id,
        buyer_id=buyer.id,
        seller_id=seller.id,
        status=OrderStatus.AWAITING_PAYMENT,
        item_price=Decimal("100.00"),
        shipping_fee=Decimal("0.00"),
        total_amount=Decimal("100.00"),
        commission_rate_bps=0,
        commission_amount=Decimal("0.00"),
        seller_payout_amount=Decimal("100.00"),
        item_title=poster.title,
    )
