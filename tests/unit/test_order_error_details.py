"""SCR-07 สไลซ์ A · A2 — รูปของ `ErrorResponse.details` บนสองเส้นของ ADR-0037

Amendment 2 A2-D1/A2-D2: ทุก error ที่ไม่ใช่ `VALIDATION_ERROR` บนสองเส้นนี้ต้องมี
`details` เป็น `[{"field": ..., "message": ...}]` และ `message` ต้องเป็น **ค่าเปล่า
ที่ `parse()` กินได้ทั้งช่อง** (ISO-8601 · เลขล้วน · UUID) **ห้ามเป็นประโยค**

🔴 ทุกเทสในไฟล์นี้ assert ทั้งรูปร่างของ dict (closed-world บนคีย์ — ต้องมีแค่
`field`/`message` เท่านั้น ไม่มีคีย์อื่นหลุดมา เช่นตัวตนผู้จอง) และ assert ว่า
`message` **parse ได้จริง** ด้วย `datetime.fromisoformat()`/`int()`/`uuid.UUID()`
ไม่ใช่แค่เช็คว่ามีค่า — เทสที่เช็คแค่ "มีค่า" จับ mutation "เปลี่ยนเป็นประโยคภาษาไทย"
ไม่ได้เลย (`test-quality` §3.1)
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import (
    PosterAlreadyReserved,
    PosterNotAvailable,
    ReservationLimitExceeded,
    ReservationNotActive,
)
from app.models.enums import PosterCondition, PosterStatus
from app.models.platform import PlatformSetting
from app.models.poster import Poster
from app.models.reservation import Reservation
from app.models.seller import SellerProfile
from app.models.user import User
from app.schemas.order import ShippingAddressInput
from app.services import order_service

NOW = datetime(2026, 3, 2, 4, 0, tzinfo=UTC)
PUBLISHED_AT = datetime(2026, 1, 1, tzinfo=UTC)
APPROVED_AT = datetime(2026, 1, 2, tzinfo=UTC)
VERIFIED_AT = datetime(2026, 1, 1, 6, 0, tzinfo=UTC)

_ADDRESS = ShippingAddressInput(
    recipient_name="ทดสอบ ระบบ",
    recipient_phone="0812345678",
    address_line="123 ถนนทดสอบ",
    province="กรุงเทพมหานคร",
    postal_code="10110",
)


async def _a_user(session: AsyncSession, label: str) -> User:
    user = User(email=f"{label}-{uuid.uuid4().hex[:8]}@example.test", is_verified=True)
    session.add(user)
    await session.flush()
    return user


async def _a_seller(session: AsyncSession) -> SellerProfile:
    owner = await _a_user(session, "seller")
    seller = SellerProfile(
        user_id=owner.id,
        display_name="ร้านทดสอบ",
        real_name="ผู้ขายทดสอบ",
        bank_name="ธนาคารทดสอบ",
        bank_account_name="ผู้ขายทดสอบ",
        bank_account_no="0000000000",
    )
    session.add(seller)
    await session.flush()
    return seller


async def _a_listing(session: AsyncSession, seller: SellerProfile) -> Poster:
    poster = Poster(
        seller_id=seller.id,
        approved_at=APPROVED_AT,
        title="The Matrix",
        price=Decimal("4500.00"),
        shipping_fee=Decimal("0.00"),
        condition_grade=PosterCondition.very_fine,
        status=PosterStatus.available,
        published_at=PUBLISHED_AT,
        verified_at=VERIFIED_AT,
    )
    session.add(poster)
    await session.flush()
    return poster


def _only_keys(detail: dict, *, expected: set[str]) -> None:
    """closed-world บนคีย์ของแถว details หนึ่งแถว — ห้ามมีคีย์อื่นหลุดมา
    (โดยเฉพาะตัวตนผู้จอง เช่น `user_id`/`buyer_id`/`email` — security-baseline §5)
    """
    assert set(detail.keys()) == expected, detail


async def test_poster_not_available_on_reserve_carries_a_parseable_reserved_until(
    db_session: AsyncSession,
) -> None:
    seller = await _a_seller(db_session)
    poster = await _a_listing(db_session, seller)
    first_buyer = await _a_user(db_session, "buyer-a")
    second_buyer = await _a_user(db_session, "buyer-b")

    reservation = await order_service.reserve_listing(
        db_session, poster.id, buyer_user_id=first_buyer.id, at=NOW
    )

    with pytest.raises(PosterNotAvailable) as caught:
        await order_service.reserve_listing(
            db_session, poster.id, buyer_user_id=second_buyer.id, at=NOW
        )

    details = caught.value.details
    assert details is not None and len(details) == 1
    row = details[0]
    _only_keys(row, expected={"field", "message"})
    assert row["field"] == "reserved_until"
    # 🔴 ต้อง parse ได้จริง ไม่ใช่แค่ "มีค่า" — ป้องกัน mutation ที่เปลี่ยนเป็นประโยค
    parsed = datetime.fromisoformat(row["message"])
    assert parsed == reservation.expires_at

    # security-baseline §5 — ห้ามแนบตัวตนผู้จอง (id ของ first_buyer ต้องไม่โผล่)
    assert str(first_buyer.id) not in row["message"]
    assert "user_id" not in row and "buyer_id" not in row


async def test_reservation_limit_exceeded_carries_a_parseable_int_limit(
    db_session: AsyncSession,
) -> None:
    setting = await db_session.get(PlatformSetting, "max_active_reservations_per_user")
    assert setting is not None
    setting.value = "1"
    await db_session.flush()

    seller = await _a_seller(db_session)
    first = await _a_listing(db_session, seller)
    second = await _a_listing(db_session, seller)
    buyer = await _a_user(db_session, "buyer")

    await order_service.reserve_listing(
        db_session, first.id, buyer_user_id=buyer.id, at=NOW
    )

    with pytest.raises(ReservationLimitExceeded) as caught:
        await order_service.reserve_listing(
            db_session, second.id, buyer_user_id=buyer.id, at=NOW
        )

    details = caught.value.details
    assert details is not None and len(details) == 1
    row = details[0]
    _only_keys(row, expected={"field", "message"})
    assert row["field"] == "limit"
    assert int(row["message"]) == 1


async def test_reservation_not_active_on_expired_order_carries_a_parseable_expired_at(
    db_session: AsyncSession,
) -> None:
    seller = await _a_seller(db_session)
    poster = await _a_listing(db_session, seller)
    buyer = await _a_user(db_session, "buyer")

    reservation = await order_service.reserve_listing(
        db_session, poster.id, buyer_user_id=buyer.id, at=NOW
    )
    too_late = reservation.expires_at + timedelta(seconds=1)

    with pytest.raises(ReservationNotActive) as caught:
        await order_service.create_order(
            db_session,
            reservation.id,
            buyer_user_id=buyer.id,
            shipping_address=_ADDRESS,
            at=too_late,
        )

    details = caught.value.details
    assert details is not None and len(details) == 1
    row = details[0]
    _only_keys(row, expected={"field", "message"})
    assert row["field"] == "expired_at"
    parsed = datetime.fromisoformat(row["message"])
    assert parsed == reservation.expires_at


async def test_poster_already_reserved_carries_a_parseable_uuid(
    db_session: AsyncSession,
) -> None:
    """ชั้นที่ 2 ของการกันซื้อซ้อน (`uq_active_reservation_per_poster`) — จัดฉาก
    แถวจองด้วยมือเพื่อบังคับให้ `flush()` ของ `reserve_listing()` ชน constraint
    ตรง ๆ (เส้นทางปกติมาไม่ถึงตรงนี้เพราะ `FOR UPDATE` กันไว้ก่อนแล้ว — เขียนกำกับ
    ไว้แบบเดียวกับ `test_order_service.py` ที่ทำเรื่องเดียวกัน)
    """
    seller = await _a_seller(db_session)
    poster = await _a_listing(db_session, seller)
    buyer = await _a_user(db_session, "buyer")

    # จัดฉากแถวจอง active ของ "คนอื่น" ตรง ๆ โดยไม่แตะ poster.status (ยังเป็น
    # available) ⇒ reserve_listing() เดินผ่านเช็ค status ไปเจอ IntegrityError ตอน
    # INSERT แถวของตัวเองแทน (ชนกับ uq_active_reservation_per_poster)
    db_session.add(
        Reservation(
            poster_id=poster.id,
            user_id=(await _a_user(db_session, "buyer-other")).id,
            status=order_service.ReservationStatus.active,
            expires_at=NOW + timedelta(minutes=60),
        )
    )
    await db_session.flush()

    with pytest.raises(PosterAlreadyReserved) as caught:
        async with db_session.begin_nested():
            await order_service.reserve_listing(
                db_session, poster.id, buyer_user_id=buyer.id, at=NOW
            )

    details = caught.value.details
    assert details is not None and len(details) == 1
    row = details[0]
    _only_keys(row, expected={"field", "message"})
    assert row["field"] == "poster_id"
    assert uuid.UUID(row["message"]) == poster.id
