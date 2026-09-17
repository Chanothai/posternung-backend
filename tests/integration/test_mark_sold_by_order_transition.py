"""Integration test: order เข้า `COMPLETED` → `GET /posters/{id}` ผ่าน HTTP จริง
(INF-33 AC-4 สไลซ์ B · ทรงเดียวกับ ADR-0025 §Verification ข้อ 3 · ดู
`tests/integration/test_mark_sold_transition.py` สำหรับทางเข้าที่ 1 — `mark_sold()`)

🔴 ยังไม่มี endpoint HTTP ของ `apply_order_transition()` (INF-41 ยัง not_started) —
เส้นทางสร้างสถานะจึงเรียก `order_service` ตรง ๆ ผ่าน `db_session` เดียวกับที่ `client`
fixture ใช้ (ดู docstring ของ fixture `client` ใน `tests/conftest.py`) แล้วค่อยยิง
`GET` จริงผ่าน HTTP — โค้ดที่ตัดสินใจ (`mark_sold_by_order()`) จึงยังอยู่บนเส้นทาง
ระหว่าง action กับ assertion จริง ไม่ใช่การจัดฉาก `status` ด้วยมือ (`test-quality` §3.1)
"""

import uuid
from datetime import UTC, datetime
from decimal import Decimal

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import OrderStatus, PosterCondition, PosterStatus
from app.models.poster import Poster
from app.models.seller import SellerProfile
from app.models.user import User
from app.schemas.order import ShippingAddressInput
from app.services import order_service

API = "/api/v1/posters"
PUBLISHED_AT = datetime(2026, 1, 1, tzinfo=UTC)
APPROVED_AT = datetime(2026, 1, 2, tzinfo=UTC)
VERIFIED_AT = datetime(2026, 1, 1, 6, 0, tzinfo=UTC)
NOW = datetime(2026, 3, 2, 4, 0, tzinfo=UTC)

_ADDRESS = ShippingAddressInput(
    recipient_name="ทดสอบ ระบบ",
    recipient_phone="0812345678",
    address_line="123 ถนนทดสอบ",
    sub_district="แขวงทดสอบ",
    district="เขตทดสอบ",
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
        title="Order Completed Target",
        price=Decimal("100"),
        condition_grade=PosterCondition.very_good,
        status=PosterStatus.available,
        published_at=PUBLISHED_AT,
        verified_at=VERIFIED_AT,
    )
    session.add(poster)
    await session.flush()
    return poster


async def test_order_completing_then_get_detail_returns_200_with_sold_state(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """order เดินผ่านประตูจริงจนถึง `COMPLETED` → `GET` ต้องตอบ 200 + `status: sold`
    + `sold_at` ตรงกับ `orders.completed_at` โดยไม่มีการจัดฉากค่าใน `posters` ด้วยมือ
    """
    seller = await _a_seller(db_session)
    poster = await _a_listing(db_session, seller)
    buyer = await _a_user(db_session, "buyer")

    reservation, _ = await order_service.reserve_listing(
        db_session, poster.id, buyer_user_id=buyer.id, at=NOW
    )
    order = await order_service.create_order(
        db_session,
        reservation.id,
        buyer_user_id=buyer.id,
        shipping_address=_ADDRESS,
        at=NOW,
    )
    for step in (
        OrderStatus.PAYMENT_REVIEW,
        OrderStatus.AWAITING_SHIPMENT,
        OrderStatus.SHIPPED,
        OrderStatus.COMPLETED,
    ):
        await order_service.apply_order_transition(
            db_session,
            order.id,
            to_status=step,
            actor_user_id=buyer.id,
            reason=None,
            at=NOW,
        )
    await db_session.commit()

    assert order.status is OrderStatus.COMPLETED
    assert poster.status is PosterStatus.sold
    assert poster.sold_at == order.completed_at == NOW

    res = await client.get(f"{API}/{poster.id}")

    assert res.status_code == 200, res.text
    body = res.json()
    assert body["id"] == str(poster.id)
    assert body["status"] == "sold"
    assert body["sold_at"] == "2026-03-02T04:00:00Z"
    assert "published_at" not in body  # ADR-0013 D5 — ธงภายใน ห้ามออก public API
