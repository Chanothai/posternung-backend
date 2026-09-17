"""Integration tests (HTTP-level) ของ SCR-07 สไลซ์ A — `POST /listings/{id}/reserve`
· `POST /orders` (ADR-0037)

ทุกเคสยิงผ่าน endpoint จริงด้วย fixture `client` (session/ทรานแซกชันเดียว rollback
ท้าย test — ใช้ได้เพราะเคสในไฟล์นี้ไม่ต้องพิสูจน์ concurrency ข้าม connection เลย)
เทส race ที่ต้องการการชนกันจริงอยู่ที่ `test_reserve_listing_endpoint_race.py`
(ใช้ fixture `real_client` แทน — ดูเหตุผลใน docstring ของมัน)
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import security
from app.models.enums import PosterCondition, PosterStatus, ReservationStatus
from app.models.order import OrderShippingDetail
from app.models.poster import Poster
from app.models.reservation import Reservation
from app.models.seller import SellerProfile
from app.models.user import User
from app.services import order_service

NOW_ISO_TOLERANT = datetime.now(UTC)  # แค่ใช้เทียบคร่าว ๆ ว่าเป็นเวลาจริง ไม่ hardcode
PUBLISHED_AT = datetime(2026, 1, 1, tzinfo=UTC)
APPROVED_AT = datetime(2026, 1, 2, tzinfo=UTC)
VERIFIED_AT = datetime(2026, 1, 1, 6, 0, tzinfo=UTC)

RESERVE_URL = "/api/v1/listings/{poster_id}/reserve"
ORDERS_URL = "/api/v1/orders"

_ADDRESS_BODY = {
    "recipient_name": "ทดสอบ ระบบ",
    "recipient_phone": "0812345678",
    "address_line": "123 ถนนทดสอบ",
    "sub_district": "แขวงทดสอบ",
    "district": "เขตทดสอบ",
    "province": "กรุงเทพมหานคร",
    "postal_code": "10110",
}


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


async def _a_listing(
    session: AsyncSession,
    seller: SellerProfile,
    *,
    status: PosterStatus = PosterStatus.available,
    published_at: datetime | None = PUBLISHED_AT,
    approved_at: datetime | None = APPROVED_AT,
    verified_at: datetime | None = VERIFIED_AT,
) -> Poster:
    poster = Poster(
        seller_id=seller.id,
        approved_at=approved_at,
        title="The Matrix",
        price=Decimal("4500.00"),
        shipping_fee=Decimal("0.00"),
        condition_grade=PosterCondition.very_fine,
        status=status,
        published_at=published_at,
        verified_at=verified_at,
    )
    session.add(poster)
    await session.flush()
    return poster


def _auth(user: User) -> dict[str, str]:
    return {"Authorization": f"Bearer {security.create_access_token(str(user.id))}"}


# ══════════════════════════════════════════════════════════════════════════
# POST /listings/{poster_id}/reserve
# ══════════════════════════════════════════════════════════════════════════


async def test_reserve_returns_201_with_the_reservation(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    seller = await _a_seller(db_session)
    poster = await _a_listing(db_session, seller)
    buyer = await _a_user(db_session, "buyer")

    res = await client.post(
        RESERVE_URL.format(poster_id=poster.id), headers=_auth(buyer)
    )

    assert res.status_code == 201, res.text
    body = res.json()
    assert set(body.keys()) == {
        "id",
        "poster_id",
        "user_id",
        "status",
        "expires_at",
        "created_at",
    }
    assert body["poster_id"] == str(poster.id)
    assert body["user_id"] == str(buyer.id)
    assert body["status"] == "active"
    # ISO ที่ parse ได้จริง ไม่ใช่แค่ "เป็น string"
    datetime.fromisoformat(body["expires_at"])
    datetime.fromisoformat(body["created_at"])


async def test_reserve_requires_auth(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    seller = await _a_seller(db_session)
    poster = await _a_listing(db_session, seller)

    res = await client.post(RESERVE_URL.format(poster_id=poster.id))

    assert res.status_code == 401
    assert res.json()["error_code"] == "UNAUTHORIZED"


async def test_reserve_rejects_the_seller_of_the_listing(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    seller = await _a_seller(db_session)
    poster = await _a_listing(db_session, seller)
    seller_user = await db_session.get(User, seller.user_id)

    res = await client.post(
        RESERVE_URL.format(poster_id=poster.id), headers=_auth(seller_user)
    )

    assert res.status_code == 403
    body = res.json()
    assert body["error_code"] == "BUYER_IS_SELLER"
    # ADR-0037 Amendment 2 A2-D2 + ตัวอย่างของสัญญา — 403 นี้ต้อง details: null เป๊ะ
    # ไม่ใช่ [{"poster_id": ...}] แบบที่ INF-33 เคยเขียนไว้ก่อนขึ้น wire รอบนี้
    assert body["details"] is None


async def test_reserve_treats_an_unpublished_listing_as_not_found(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """AC-12 เชิงลบ — `published_at IS NULL`"""
    seller = await _a_seller(db_session)
    poster = await _a_listing(db_session, seller, published_at=None)
    buyer = await _a_user(db_session, "buyer")

    res = await client.post(
        RESERVE_URL.format(poster_id=poster.id), headers=_auth(buyer)
    )

    assert res.status_code == 404
    assert res.json()["error_code"] == "POSTER_NOT_FOUND"


async def test_reserve_treats_an_unapproved_listing_as_not_found(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """AC-12 เชิงลบ — `approved_at IS NULL` (ADR-0028 Consequence 2)

    🔴 **หมายเหตุที่ต้องรู้**: DB มี CHECK `ck_posters_sellable_requires_approved_at`
    ที่บังคับว่า `status IN ('available','reserved','sold') ⇒ approved_at NOT NULL`
    เสมอ ⇒ ไม่มีทางสร้างแถว `status=available` ที่ `approved_at IS NULL` ได้จริง
    (ลองแล้วชน constraint) จึงต้องใช้ `status=pending_review` แทน (ของผู้ขายภายนอก
    ที่กด "เผยแพร่" เองก่อนแอดมินอนุมัติ — สถานการณ์จริงที่ ADR-0028 Consequence 2
    พูดถึง) ⇒ เคสนี้ยังพิสูจน์ AC-12 ได้ (404 เมื่อยังไม่อนุมัติ) แต่ **ไม่ได้แยกแยะ
    ระหว่างเงื่อนไข `is_published()` (status ไม่อยู่ในเซตสาธารณะ) กับเงื่อนไข
    `approved_at is None` ล้วน ๆ** เพราะทั้งสองเป็นจริงพร้อมกันในเคสเดียวที่สร้างได้จริง
    — บันทึกไว้ใน "สิ่งที่ผมไม่แน่ใจ" ของรายงานท้ายงาน
    """
    seller = await _a_seller(db_session)
    poster = await _a_listing(
        db_session,
        seller,
        status=PosterStatus.pending_review,
        published_at=PUBLISHED_AT,
        approved_at=None,
    )
    buyer = await _a_user(db_session, "buyer")

    res = await client.post(
        RESERVE_URL.format(poster_id=poster.id), headers=_auth(buyer)
    )

    assert res.status_code == 404
    assert res.json()["error_code"] == "POSTER_NOT_FOUND"


async def test_reserve_returns_404_for_a_poster_that_does_not_exist(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    buyer = await _a_user(db_session, "buyer")

    res = await client.post(
        RESERVE_URL.format(poster_id=uuid.uuid4()), headers=_auth(buyer)
    )

    assert res.status_code == 404
    assert res.json()["error_code"] == "POSTER_NOT_FOUND"


async def test_reserve_returns_409_with_reserved_until_when_already_taken(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    seller = await _a_seller(db_session)
    poster = await _a_listing(db_session, seller)
    first_buyer = await _a_user(db_session, "buyer-a")
    second_buyer = await _a_user(db_session, "buyer-b")

    first_res = await client.post(
        RESERVE_URL.format(poster_id=poster.id), headers=_auth(first_buyer)
    )
    assert first_res.status_code == 201, first_res.text
    reserved_until = first_res.json()["expires_at"]

    res = await client.post(
        RESERVE_URL.format(poster_id=poster.id), headers=_auth(second_buyer)
    )

    assert res.status_code == 409
    body = res.json()
    assert body["error_code"] == "POSTER_NOT_AVAILABLE"
    assert body["details"] is not None and len(body["details"]) == 1
    detail = body["details"][0]
    assert set(detail.keys()) == {"field", "message"}
    assert detail["field"] == "reserved_until"
    # เทียบเป็นค่าเวลาที่ parse แล้ว ไม่ใช่ string ตรงตัว — ReservationResponse
    # (Pydantic) serialize ด้วย "Z" ส่วน exception message มาจาก .isoformat() ตรง ๆ
    # ("+00:00") ทั้งคู่ parse ได้และเป็นเวลาเดียวกัน แต่หน้าตาต่างกัน
    assert datetime.fromisoformat(detail["message"]) == datetime.fromisoformat(
        reserved_until
    )
    # security-baseline §5 — ห้ามแนบตัวตนผู้จองเด็ดขาด
    assert str(first_buyer.id) not in res.text


# ══════════════════════════════════════════════════════════════════════════
# POST /orders
# ══════════════════════════════════════════════════════════════════════════


async def _a_reservation_via_service(
    session: AsyncSession, poster: Poster, buyer: User, *, at: datetime
) -> Reservation:
    reservation, _ = await order_service.reserve_listing(
        session, poster.id, buyer_user_id=buyer.id, at=at
    )
    return reservation


async def test_create_order_returns_201_with_no_address_fields_and_writes_shipping_detail(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    seller = await _a_seller(db_session)
    poster = await _a_listing(db_session, seller)
    buyer = await _a_user(db_session, "buyer")
    reservation = await _a_reservation_via_service(
        db_session, poster, buyer, at=datetime.now(UTC)
    )
    await db_session.commit()

    res = await client.post(
        ORDERS_URL,
        headers=_auth(buyer),
        json={
            "reservation_id": str(reservation.id),
            "shipping_address": _ADDRESS_BODY,
        },
    )

    assert res.status_code == 201, res.text
    body = res.json()
    assert set(body.keys()) == {
        "id",
        "order_no",
        "poster_id",
        "status",
        "item_price",
        "shipping_fee",
        "total_amount",
        "item_title",
        "created_at",
    }
    # 🔴 closed-world เชิงลบที่ระดับ wire จริง — ไม่ใช่แค่ระดับ Pydantic model_fields
    address_keys = set(_ADDRESS_BODY.keys()) | {"shipping_address"}
    assert not (set(body.keys()) & address_keys)
    assert res.text.find("recipient_name") == -1
    assert res.text.find("0812345678") == -1

    assert body["poster_id"] == str(poster.id)
    assert body["status"] == "AWAITING_PAYMENT"
    assert body["item_price"] == "4500.00"
    assert body["shipping_fee"] == "0.00"
    assert body["total_amount"] == "4500.00"

    order_id = uuid.UUID(body["id"])
    detail = await db_session.get(OrderShippingDetail, order_id)
    assert detail is not None
    assert detail.recipient_name == _ADDRESS_BODY["recipient_name"]
    assert detail.recipient_phone == _ADDRESS_BODY["recipient_phone"]
    assert detail.address_line == _ADDRESS_BODY["address_line"]
    assert detail.sub_district == _ADDRESS_BODY["sub_district"]
    assert detail.district == _ADDRESS_BODY["district"]
    assert detail.province == _ADDRESS_BODY["province"]
    assert detail.postal_code == _ADDRESS_BODY["postal_code"]


async def test_create_order_requires_auth(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    res = await client.post(
        ORDERS_URL,
        json={
            "reservation_id": str(uuid.uuid4()),
            "shipping_address": _ADDRESS_BODY,
        },
    )
    assert res.status_code == 401
    assert res.json()["error_code"] == "UNAUTHORIZED"


async def test_create_order_rejects_the_seller_of_the_listing(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """ด่านชั้นที่สอง (ADR-0033 OD-1 ทาง ข) — จัดฉาก reservation ตรง ๆ เพราะเส้นทาง
    ปกติ (`reserve_listing()`) ปฏิเสธผู้ขายไปตั้งแต่ต้นแล้ว (ดู test_order_service.py
    ที่ทำแบบเดียวกันสำหรับกฎเดียวกัน)"""
    seller = await _a_seller(db_session)
    poster = await _a_listing(db_session, seller)
    seller_user = await db_session.get(User, seller.user_id)
    reservation = Reservation(
        poster_id=poster.id,
        user_id=seller.user_id,
        status=ReservationStatus.active,
        expires_at=datetime.now(UTC) + timedelta(minutes=60),
    )
    db_session.add(reservation)
    await db_session.commit()

    res = await client.post(
        ORDERS_URL,
        headers=_auth(seller_user),
        json={
            "reservation_id": str(reservation.id),
            "shipping_address": _ADDRESS_BODY,
        },
    )

    assert res.status_code == 403
    body = res.json()
    assert body["error_code"] == "BUYER_IS_SELLER"
    assert body["details"] is None


async def test_create_order_treats_someone_elses_reservation_as_not_found(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """ownership — 404 ไม่ใช่ 403 (กัน enumeration — OWASP API1)"""
    seller = await _a_seller(db_session)
    poster = await _a_listing(db_session, seller)
    owner = await _a_user(db_session, "buyer-a")
    intruder = await _a_user(db_session, "buyer-b")
    reservation = await _a_reservation_via_service(
        db_session, poster, owner, at=datetime.now(UTC)
    )
    await db_session.commit()

    res = await client.post(
        ORDERS_URL,
        headers=_auth(intruder),
        json={
            "reservation_id": str(reservation.id),
            "shipping_address": _ADDRESS_BODY,
        },
    )

    assert res.status_code == 404
    assert res.json()["error_code"] == "RESERVATION_NOT_FOUND"


async def test_create_order_treats_an_unknown_reservation_as_not_found(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    buyer = await _a_user(db_session, "buyer")
    await db_session.commit()

    res = await client.post(
        ORDERS_URL,
        headers=_auth(buyer),
        json={
            "reservation_id": str(uuid.uuid4()),
            "shipping_address": _ADDRESS_BODY,
        },
    )

    assert res.status_code == 404
    assert res.json()["error_code"] == "RESERVATION_NOT_FOUND"


async def test_create_order_rejects_an_expired_reservation(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """AC-4 — หมดอายุระหว่างกรอกที่อยู่ ต้องแจ้งไม่ใช่ปล่อยให้จ่ายของที่ไม่มีแล้ว"""
    seller = await _a_seller(db_session)
    poster = await _a_listing(db_session, seller)
    buyer = await _a_user(db_session, "buyer")
    early = datetime(2026, 1, 1, tzinfo=UTC)
    reservation = await _a_reservation_via_service(db_session, poster, buyer, at=early)
    await db_session.commit()

    res = await client.post(
        ORDERS_URL,
        headers=_auth(buyer),
        json={
            "reservation_id": str(reservation.id),
            "shipping_address": _ADDRESS_BODY,
        },
    )

    assert res.status_code == 409
    assert res.json()["error_code"] == "RESERVATION_NOT_ACTIVE"


async def test_create_order_rejects_missing_required_address_fields(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """validation boundary — ขาด `recipient_name` (required) ต้อง 422 ไม่ใช่ 500"""
    buyer = await _a_user(db_session, "buyer")
    await db_session.commit()
    bad_address = {k: v for k, v in _ADDRESS_BODY.items() if k != "recipient_name"}

    res = await client.post(
        ORDERS_URL,
        headers=_auth(buyer),
        json={"reservation_id": str(uuid.uuid4()), "shipping_address": bad_address},
    )

    assert res.status_code == 422
    assert res.json()["error_code"] == "VALIDATION_ERROR"


async def test_create_order_rejects_an_oversized_recipient_name(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """validation boundary — เกิน maxLength 120 ตัวอักษรต้อง 422"""
    buyer = await _a_user(db_session, "buyer")
    await db_session.commit()
    bad_address = dict(_ADDRESS_BODY, recipient_name="ก" * 121)

    res = await client.post(
        ORDERS_URL,
        headers=_auth(buyer),
        json={"reservation_id": str(uuid.uuid4()), "shipping_address": bad_address},
    )

    assert res.status_code == 422
    assert res.json()["error_code"] == "VALIDATION_ERROR"


async def test_create_order_422_does_not_echo_the_submitted_address_values(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """🔴 code-critic รอบ 1 F4 (ปิด `BL-97`) — FastAPI/Pydantic 422 ปกติจะสรุป
    ข้อผิดพลาดด้วยข้อความทั่วไป ("String should have at most 120 characters")
    ไม่ echo ค่าที่กรอกกลับมา แต่**ไม่เคยมีเทสบังคับไว้เลย** ⇒ ถ้าวันหน้ามีใครเปลี่ยน
    error handler หรือ Pydantic behavior แล้วเริ่ม echo ขึ้นมา จะไม่มีอะไรจับได้

    ยิงด้วยชื่อไทยจริง/เบอร์จริง/ที่อยู่ไทยยาว ๆ ที่ไม่ซ้ำใคร (unlikely string)
    แล้ว assert เชิงลบว่าไม่มีค่าไหนโผล่ใน `res.text` ทั้งก้อน (closed-world บน
    response ทั้งตัว ไม่ใช่เช็คทีละฟิลด์) — ทั้งฟิลด์ที่ทำให้ validation ล้ม
    (`recipient_name` เกิน 120) และฟิลด์อื่นที่ valid ทุกตัว (ต้องไม่หลุดเหมือนกัน)
    """
    buyer = await _a_user(db_session, "buyer")
    await db_session.commit()

    recipient_name = "สมหญิง ทดสอบเอกลักษณ์ไม่ซ้ำ" * 6  # เกิน 120 ตัวอักษรแน่นอน
    recipient_phone = "0899998887"
    address_line = "88/8 ซอยลับเฉพาะทดสอบ ถนนพระราม9 unlikely-marker-xyz"
    province = "กรุงเทพมหานคร"

    res = await client.post(
        ORDERS_URL,
        headers=_auth(buyer),
        json={
            "reservation_id": str(uuid.uuid4()),
            "shipping_address": dict(
                _ADDRESS_BODY,
                recipient_name=recipient_name,
                recipient_phone=recipient_phone,
                address_line=address_line,
                province=province,
            ),
        },
    )

    assert res.status_code == 422
    assert res.json()["error_code"] == "VALIDATION_ERROR"
    for leaked in (recipient_name, recipient_phone, address_line):
        assert leaked not in res.text, f"422 echo ค่าที่กรอกกลับมา: {leaked!r}"


async def test_create_order_does_not_log_any_personal_data(
    client: AsyncClient,
    db_session: AsyncSession,
    caplog,
) -> None:
    """ADR-0020 D9 · SCR-07 AC-7 — ห้าม log ชื่อ/เบอร์/ที่อยู่ทุกชั้น พิสูจน์ด้วย
    mutation จริง ไม่ใช่อ่านโค้ด (ดูรายงานท้ายงาน §mutation — ยิง
    `logger.info("...", shipping_address.recipient_name)` เข้า `create_order()`
    ชั่วคราวแล้วดูว่าเทสนี้แดง ก่อนเชื่อว่ามันคุ้มครองอะไร)"""
    seller = await _a_seller(db_session)
    poster = await _a_listing(db_session, seller)
    buyer = await _a_user(db_session, "buyer")
    reservation = await _a_reservation_via_service(
        db_session, poster, buyer, at=datetime.now(UTC)
    )
    await db_session.commit()

    with caplog.at_level(logging.DEBUG):
        res = await client.post(
            ORDERS_URL,
            headers=_auth(buyer),
            json={
                "reservation_id": str(reservation.id),
                "shipping_address": _ADDRESS_BODY,
            },
        )

    assert res.status_code == 201, res.text
    all_log_text = "\n".join(record.getMessage() for record in caplog.records)
    for leak in (
        _ADDRESS_BODY["recipient_name"],
        _ADDRESS_BODY["recipient_phone"],
        _ADDRESS_BODY["address_line"],
    ):
        assert leak not in all_log_text, f"พบข้อมูลส่วนบุคคลหลุดเข้า log: {leak!r}"
