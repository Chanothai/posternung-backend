"""SCR-07 รอบ A5 — `POST /listings/{poster_id}/reserve` ระดับ HTTP (ADR-0037 Amendment 5)

* **A5-D1** ผู้ซื้อคนเดิมกดซ้ำ → `200` + reservation เดิม (ไม่ใช่ 409 · ไม่ใช่แถวใหม่)
* **A5-D4** ผู้ซื้อที่สั่งซื้อใบนี้ไปแล้ว (reservation `converted`) → `409 BUYER_HAS_LIVE_ORDER`
  + `details[order_no]` · ผู้เรียกคนอื่น → `409 POSTER_NOT_AVAILABLE` **ไม่มี details**
* **A5-D3 เชิงลบ** reservation ของตัวเองหมดอายุแล้ว → `201` แถวใหม่ (ไม่ใช่ 200 แถวเก่า)

สองเคสแรกยิงผ่าน `real_client` (session ต่อ request · ADR-0037 D5) เพราะต้องพิสูจน์ว่า
request ที่สอง**อ่านของที่ request แรก commit จริง**แล้วตัดสินได้ถูก — ไม่ใช่เห็นผ่าน
identity map ของ session เดียวกัน ⇒ ต้องเก็บกวาดเองด้วย marker (ดู docstring ของ fixture)
· เคสหมดอายุเป็นลำดับเหตุการณ์เดียว ใช้ `client` + จัดฉากทางเดียวกับ AC-16
(`test_reserve_listing_endpoint_race.py`) — **ไม่ `UPDATE status` เอง**
"""

from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime
from decimal import Decimal

from httpx import AsyncClient
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.core import security
from app.models.enums import PosterCondition, PosterStatus, ReservationStatus
from app.models.order import Order
from app.models.poster import Poster
from app.models.poster_attribute_review import PosterAttributeReview
from app.models.reservation import Reservation
from app.models.seller import SellerProfile
from app.models.user import User
from tests.conftest import TEST_DATABASE_URL

PUBLISHED_AT = datetime(2026, 1, 1, tzinfo=UTC)
VERIFIED_AT = datetime(2026, 1, 1, 6, 0, tzinfo=UTC)
APPROVED_AT = datetime(2026, 1, 2, tzinfo=UTC)

EMAIL_MARKER = "http-a5-%@example.test"
POSTER_MARKER = "HTTP A5 Target"
SELLER_MARKER = "ร้านจองซ้ำ HTTP A5"

ORDER_NO_PATTERN = re.compile(r"^PN-\d{6}-\d{4}$")

_ADDRESS_BODY = {
    "recipient_name": "ทดสอบ ระบบ",
    "recipient_phone": "0812345678",
    "address_line": "123 ถนนทดสอบ",
    "sub_district": "แขวงทดสอบ",
    "district": "เขตทดสอบ",
    "province": "กรุงเทพมหานคร",
    "postal_code": "10110",
}


def _auth(user_id: uuid.UUID) -> dict[str, str]:
    return {"Authorization": f"Bearer {security.create_access_token(str(user_id))}"}


async def _cleanup(engine) -> None:
    async with AsyncSession(engine, expire_on_commit=False) as session:
        poster_ids = select(Poster.id).where(Poster.title == POSTER_MARKER)
        # orders ก่อน (FK RESTRICT ไป reservations/posters/users) — shipping detail และ
        # status history หายตาม CASCADE ของ orders
        await session.execute(delete(Order).where(Order.poster_id.in_(poster_ids)))
        await session.execute(
            delete(Reservation).where(Reservation.poster_id.in_(poster_ids))
        )
        await session.execute(delete(Poster).where(Poster.title == POSTER_MARKER))
        await session.execute(
            delete(SellerProfile).where(SellerProfile.display_name == SELLER_MARKER)
        )
        await session.execute(delete(User).where(User.email.like(EMAIL_MARKER)))
        await session.commit()


async def _seed(engine) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID]:
    async with AsyncSession(engine, expire_on_commit=False) as session:
        seller_user = User(
            email=f"http-a5-seller-{uuid.uuid4().hex[:8]}@example.test",
            is_verified=True,
        )
        buyer = User(
            email=f"http-a5-buyer-{uuid.uuid4().hex[:8]}@example.test",
            is_verified=True,
        )
        other = User(
            email=f"http-a5-other-{uuid.uuid4().hex[:8]}@example.test",
            is_verified=True,
        )
        session.add_all([seller_user, buyer, other])
        await session.flush()

        seller = SellerProfile(
            user_id=seller_user.id,
            display_name=SELLER_MARKER,
            real_name="ผู้ขายทดสอบ",
            bank_name="ธนาคารทดสอบ",
            bank_account_name="ผู้ขายทดสอบ",
            bank_account_no="0000000000",
        )
        session.add(seller)
        await session.flush()

        poster = Poster(
            seller_id=seller.id,
            approved_at=APPROVED_AT,
            title=POSTER_MARKER,
            price=Decimal("4500.00"),
            shipping_fee=Decimal("0.00"),
            condition_grade=PosterCondition.very_fine,
            status=PosterStatus.available,
            published_at=PUBLISHED_AT,
            verified_at=VERIFIED_AT,
        )
        session.add(poster)
        await session.flush()
        await session.commit()
        return poster.id, buyer.id, other.id


async def _reservation_count(engine, poster_id: uuid.UUID) -> int:
    async with AsyncSession(engine, expire_on_commit=False) as session:
        return await session.scalar(
            select(func.count(Reservation.id)).where(Reservation.poster_id == poster_id)
        )


async def _status_audit_count(engine, poster_id: uuid.UUID) -> int:
    async with AsyncSession(engine, expire_on_commit=False) as session:
        return await session.scalar(
            select(func.count(PosterAttributeReview.id)).where(
                PosterAttributeReview.poster_id == poster_id,
                PosterAttributeReview.field == "status",
            )
        )


# ══════════════════════════════════════════════════════════════════════════
# A5-D1 — 200 + reservation เดิม
# ══════════════════════════════════════════════════════════════════════════


async def test_reserving_twice_returns_200_with_the_very_same_reservation(
    real_client: AsyncClient,
) -> None:
    engine = create_async_engine(TEST_DATABASE_URL)
    try:
        await _cleanup(engine)
        poster_id, buyer_id, _ = await _seed(engine)
        url = f"/api/v1/listings/{poster_id}/reserve"

        first = await real_client.post(url, headers=_auth(buyer_id))
        assert first.status_code == 201, first.text
        audit_after_first = await _status_audit_count(engine, poster_id)

        again = await real_client.post(url, headers=_auth(buyer_id))

        assert again.status_code == 200, again.text
        # แถวเดิมทุกฟิลด์ — closed-world บน body ทั้งก้อน ไม่ใช่แค่ id
        assert again.json() == first.json()
        assert again.json()["expires_at"] == first.json()["expires_at"]
        assert again.json()["status"] == "active"
        # ไม่มี insert ซ้ำ · ไม่มีร่องรอยสถานะใหม่ (listing ไม่ได้เปลี่ยนสถานะรอบสอง)
        assert await _reservation_count(engine, poster_id) == 1
        assert await _status_audit_count(engine, poster_id) == audit_after_first
    finally:
        await _cleanup(engine)
        await engine.dispose()


# ══════════════════════════════════════════════════════════════════════════
# A5-D4 — BUYER_HAS_LIVE_ORDER เฉพาะผู้ซื้อคนเดิม
# ══════════════════════════════════════════════════════════════════════════


async def test_the_buyer_with_a_live_order_gets_buyer_has_live_order_and_others_do_not(
    real_client: AsyncClient,
) -> None:
    engine = create_async_engine(TEST_DATABASE_URL)
    try:
        await _cleanup(engine)
        poster_id, buyer_id, other_id = await _seed(engine)
        url = f"/api/v1/listings/{poster_id}/reserve"

        reserved = await real_client.post(url, headers=_auth(buyer_id))
        assert reserved.status_code == 201, reserved.text
        ordered = await real_client.post(
            "/api/v1/orders",
            headers=_auth(buyer_id),
            json={
                "reservation_id": reserved.json()["id"],
                "shipping_address": _ADDRESS_BODY,
            },
        )
        assert ordered.status_code == 201, ordered.text
        order_no = ordered.json()["order_no"]
        assert ORDER_NO_PATTERN.fullmatch(order_no)

        mine = await real_client.post(url, headers=_auth(buyer_id))

        assert mine.status_code == 409, mine.text
        body = mine.json()
        # envelope ตาม `ErrorResponse` ของสัญญา — closed-world บนคีย์
        assert set(body.keys()) == {"error_code", "message", "details"}
        assert body["error_code"] == "BUYER_HAS_LIVE_ORDER"
        assert body["details"] == [{"field": "order_no", "message": order_no}]
        # ไม่มีแถวจองเพิ่ม (reservation เดิมถูก converted ไปแล้ว)
        assert await _reservation_count(engine, poster_id) == 1

        theirs = await real_client.post(url, headers=_auth(other_id))

        assert theirs.status_code == 409, theirs.text
        other_body = theirs.json()
        assert other_body["error_code"] == "POSTER_NOT_AVAILABLE"
        # 🔴 security-baseline §5 — ไม่มี details เลย ไม่ใช่ details ว่าง และ order_no
        # ของคนอื่นต้องไม่อยู่ที่ไหนใน response ทั้งก้อน
        assert other_body["details"] is None
        assert order_no not in theirs.text
        assert str(buyer_id) not in theirs.text
        assert await _reservation_count(engine, poster_id) == 1
    finally:
        await _cleanup(engine)
        await engine.dispose()


# ══════════════════════════════════════════════════════════════════════════
# A5-D3 เชิงลบ — หมดอายุแล้ว ผู้ซื้อคนเดิมได้ 201 แถวใหม่ (lazy-expire ยังคุ้ม)
# ══════════════════════════════════════════════════════════════════════════


async def test_an_expired_reservation_of_the_same_buyer_gets_a_fresh_201(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """จัดฉากทางเดียวกับ AC-16 — แถว active ที่หมดอายุแล้วค้างอยู่ใน DB โดยไม่มีใครล้าง
    · ต่างจาก AC-16 ตรงที่**ผู้กดคือเจ้าของแถวเก่าเอง** ⇒ ถ้า `release_due_reservations()`
    หายไป สาขา A5-D1 จะคืนแถวเก่าเป็น 200 แทน (นี่คือ mutation m4 ที่เทสนี้ต้องจับ)"""
    seller_owner = User(
        email=f"a5exp-seller-{uuid.uuid4().hex[:8]}@example.test", is_verified=True
    )
    db_session.add(seller_owner)
    await db_session.flush()
    seller = SellerProfile(
        user_id=seller_owner.id,
        display_name="ร้าน A5 expired",
        real_name="ผู้ขายทดสอบ",
        bank_name="ธนาคารทดสอบ",
        bank_account_name="ผู้ขายทดสอบ",
        bank_account_no="0000000000",
    )
    db_session.add(seller)
    await db_session.flush()
    poster = Poster(
        seller_id=seller.id,
        approved_at=APPROVED_AT,
        title="A5 Expired Target",
        price=Decimal("1000.00"),
        shipping_fee=Decimal("0.00"),
        condition_grade=PosterCondition.very_fine,
        status=PosterStatus.reserved,  # ของยังค้าง reserved — ไม่มีใครมาล้างก่อน
        published_at=PUBLISHED_AT,
        verified_at=VERIFIED_AT,
    )
    db_session.add(poster)
    await db_session.flush()
    buyer = User(
        email=f"a5exp-buyer-{uuid.uuid4().hex[:8]}@example.test", is_verified=True
    )
    db_session.add(buyer)
    await db_session.flush()

    stale = Reservation(
        poster_id=poster.id,
        user_id=buyer.id,  # 🔴 เจ้าของแถวเก่าคือคนที่จะกดใหม่
        status=ReservationStatus.active,
        expires_at=datetime(2026, 1, 1, tzinfo=UTC),  # หมดอายุไปนานแล้ว
    )
    db_session.add(stale)
    await db_session.commit()

    res = await client.post(
        f"/api/v1/listings/{poster.id}/reserve", headers=_auth(buyer.id)
    )

    assert res.status_code == 201, res.text
    body = res.json()
    assert body["id"] != str(stale.id)
    assert body["user_id"] == str(buyer.id)
    assert body["status"] == "active"
    assert datetime.fromisoformat(body["expires_at"]) > datetime.now(UTC)
    await db_session.refresh(stale)
    assert stale.status is ReservationStatus.expired
