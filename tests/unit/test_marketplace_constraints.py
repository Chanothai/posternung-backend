"""DB-level constraint test ของ schema marketplace (INF-32) — ADR-0028 · ADR-0029 · ADR-0030

ทรงเดียวกับ `test_poster_sold_at_constraint.py` และ `test_poster_publication_constraint.py`:
**ยิงตรงเข้า session ไม่ผ่าน service** เพราะกฎทุกข้อในไฟล์นี้จงใจอยู่ที่ระดับ DB
— ถ้าเทสเรียกผ่าน service มันจะพิสูจน์แค่ว่า service ทำถูก ไม่ได้พิสูจน์ว่ากฎยังยืน
เมื่อมีคนเขียนตารางตรง (ซึ่งสคริปต์ operator ทั้ง 8 เส้นทำอยู่จริงทุกวัน)

**ถ้าใคร drop constraint ทิ้ง เทสในไฟล์นี้ต้องแดงทันที** — นั่นคือหน้าที่เดียวของมัน
"""

import uuid
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import OrderStatus, PaymentStatus, PosterStatus
from app.models.order import Order
from app.models.payment import Payment
from app.models.poster import Poster
from app.models.seller import HOUSE_SELLER_ID, SellerProfile
from app.models.user import User
from tests.support import HOUSE_APPROVED_AT

NOW = datetime(2026, 3, 1, tzinfo=UTC)


async def _a_user(db_session: AsyncSession, label: str) -> uuid.UUID:
    user = User(email=f"{label}-{uuid.uuid4().hex[:8]}@example.test", is_verified=True)
    db_session.add(user)
    await db_session.flush()
    return user.id


async def _a_poster(db_session: AsyncSession, title: str = "The Matrix") -> uuid.UUID:
    poster = Poster(
        seller_id=HOUSE_SELLER_ID,
        approved_at=HOUSE_APPROVED_AT,
        title=title,
        price=Decimal("500"),
    )
    db_session.add(poster)
    await db_session.flush()
    return poster.id


def _an_order(*, poster_id: uuid.UUID, buyer_id: uuid.UUID, **over: object) -> Order:
    """ออร์เดอร์ที่ถูกกฎทุกข้อ — เทสแต่ละตัวพังมันทีละข้อเพื่อพิสูจน์ว่าด่านจับได้"""
    fields: dict[str, object] = {
        "order_no": f"PN-260301-{uuid.uuid4().hex[:4]}",
        "poster_id": poster_id,
        "buyer_id": buyer_id,
        "seller_id": HOUSE_SELLER_ID,
        "item_price": Decimal("500.00"),
        "shipping_fee": Decimal("150.00"),
        "total_amount": Decimal("650.00"),
        "commission_rate_bps": 1000,
        "commission_amount": Decimal("50.00"),
        "seller_payout_amount": Decimal("600.00"),
        "item_title": "The Matrix",
    }
    fields.update(over)
    return Order(**fields)  # type: ignore[arg-type]


# ══════════════════════════════════════════════════════════════════════
# ADR-0029 D3 — ด่านกันสลิปปลอม · ข้อที่สำคัญที่สุดในไฟล์นี้
# ══════════════════════════════════════════════════════════════════════


async def test_a_payment_cannot_be_verified_without_checking_the_bank_statement(
    db_session: AsyncSession,
) -> None:
    """🔴 ADR-0029 D3 — ยืนยันเงินเข้าได้ต่อเมื่อแอดมิน**เห็นยอดในบัญชีจริง**แล้วเท่านั้น

    เหตุผลที่ต้องเป็น CHECK ระดับ DB ไม่ใช่ `if` ใน service: สลิปปลอมทำง่ายกว่าที่
    คนส่วนใหญ่คิดมาก และ **ความเสียหายย้อนกลับไม่ได้** (ของถูกส่งออกไปแล้ว) ⇒ ด่านต้อง
    อยู่ในระบบ ไม่ใช่ในความมีวินัยของคนที่กำลังรีบ
    """
    buyer = await _a_user(db_session, "buyer")
    poster = await _a_poster(db_session)
    order = _an_order(poster_id=poster, buyer_id=buyer)
    db_session.add(order)
    await db_session.flush()

    db_session.add(
        Payment(
            order_id=order.id,
            status=PaymentStatus.VERIFIED,
            amount_expected=Decimal("650.00"),
            bank_statement_checked=False,  # 🔴 ยังไม่ได้เปิดดูยอดจริง
            verified_by=buyer,
            verified_at=NOW,
        )
    )

    with pytest.raises(
        IntegrityError, match="ck_payments_verified_requires_bank_statement_checked"
    ):
        await db_session.flush()


async def test_a_payment_verified_after_checking_the_statement_is_accepted(
    db_session: AsyncSession,
) -> None:
    """ด่านต้องปล่อยเคสที่ถูกต้องผ่าน — ไม่งั้นเทสข้างบนผ่านเพราะอะไรก็ตามที่ผิด"""
    buyer = await _a_user(db_session, "buyer")
    poster = await _a_poster(db_session)
    order = _an_order(poster_id=poster, buyer_id=buyer)
    db_session.add(order)
    await db_session.flush()

    db_session.add(
        Payment(
            order_id=order.id,
            status=PaymentStatus.VERIFIED,
            amount_expected=Decimal("650.00"),
            bank_statement_checked=True,
            verified_by=buyer,
            verified_at=NOW,
        )
    )
    await db_session.flush()  # ต้องไม่ระเบิด


# ══════════════════════════════════════════════════════════════════════
# INF-32 AC-6 — ชั้นที่ 3 ของการกันซื้อซ้อน
# ══════════════════════════════════════════════════════════════════════


async def test_one_poster_cannot_have_two_live_orders(
    db_session: AsyncSession,
) -> None:
    """🔴 ของชิ้นเดียวมีออร์เดอร์ที่ยังไม่จบพร้อมกัน 2 ใบไม่ได้

    เป็นชั้นที่ 3 ต่อจาก row-lock และ `uq_active_reservation_per_poster`
    (`database-design.md` §6) · สองชั้นแรกคุ้ม **การจอง** ชั้นนี้คุ้ม **ออร์เดอร์**
    ซึ่งเป็นคนละแถวคนละตาราง — ถ้ามีบั๊กที่สร้างออร์เดอร์โดยไม่ผ่านการจอง
    สองชั้นแรกมองไม่เห็นเลย
    """
    buyer_a = await _a_user(db_session, "buyer-a")
    buyer_b = await _a_user(db_session, "buyer-b")
    poster = await _a_poster(db_session)

    db_session.add(_an_order(poster_id=poster, buyer_id=buyer_a))
    await db_session.flush()

    db_session.add(_an_order(poster_id=poster, buyer_id=buyer_b))
    with pytest.raises(IntegrityError, match="uq_live_order_per_poster"):
        await db_session.flush()


async def test_a_second_order_is_allowed_after_the_first_one_was_cancelled(
    db_session: AsyncSession,
) -> None:
    """BR-B4 — จองหลุดแล้วของกลับไปขายใหม่ได้ ⇒ ออร์เดอร์ใบใหม่ต้องสร้างได้

    ด่านที่กันซ้ำโดยไม่ยอมให้ขายรอบสองคือด่านที่ทำให้ของขายไม่ออกตลอดกาล
    """
    buyer_a = await _a_user(db_session, "buyer-a")
    buyer_b = await _a_user(db_session, "buyer-b")
    poster = await _a_poster(db_session)

    db_session.add(
        _an_order(
            poster_id=poster,
            buyer_id=buyer_a,
            status=OrderStatus.CANCELLED,
            cancellation_reason="ชำระไม่ทันใน 60 นาที",
        )
    )
    await db_session.flush()

    db_session.add(_an_order(poster_id=poster, buyer_id=buyer_b))
    await db_session.flush()  # ต้องไม่ระเบิด


# ══════════════════════════════════════════════════════════════════════
# กฎที่เหลือของ orders
# ══════════════════════════════════════════════════════════════════════


async def test_buying_from_yourself_is_not_blocked_at_the_db_layer(
    db_session: AsyncSession,
) -> None:
    """🔴 **บันทึกความจริง ไม่ใช่การอวยพร** — DB ไม่ได้กันเคสนี้ และกันไม่ได้ด้วย

    `buyer_id` ชี้ `users.id` · `seller_id` ชี้ `seller_profiles.id` ⇒ CHECK ที่เทียบ
    สองคอลัมน์นี้ตรง ๆ **ไม่มีทางเป็นเท็จ** · ร่างแรกของ INF-32 มี CHECK ชื่อ
    `ck_orders_buyer_is_not_seller` อยู่จริงและ **ผ่านทุกเทสโดยไม่เคยจับอะไรได้เลย**
    ซึ่งอันตรายกว่าไม่มี เพราะอ่านแล้วเหมือนมีด่าน — ถอดออกแล้ว 2026-08-22

    **ด่านจริงเป็นงานของ INF-33** (service รู้จัก `seller_profiles.user_id`)
    เทสนี้จะต้อง**แดง**ในวันที่ด่านนั้นถูกเพิ่มเข้ามาถูกที่ ซึ่งเป็นสัญญาณให้มาลบเทสนี้
    ทิ้ง ไม่ใช่สัญญาณว่าอะไรพัง

    ทำไมต้องกัน: BR-D4 ใช้ "จำนวนธุรกรรมสำเร็จ + คะแนนรีวิว" เป็นสัญญาณความน่าเชื่อถือ
    ⇒ ซื้อของตัวเองได้ = ปั่นความน่าเชื่อถือได้ฟรี
    """
    house = await db_session.get(SellerProfile, HOUSE_SELLER_ID)
    assert house is not None
    poster = await _a_poster(db_session)

    db_session.add(_an_order(poster_id=poster, buyer_id=house.user_id))
    await db_session.flush()  # ผ่านได้ — นี่คือช่องที่ยังเปิดอยู่จริง


async def test_the_total_must_equal_item_price_plus_shipping(
    db_session: AsyncSession,
) -> None:
    """ยอดที่ไม่ตรงกับส่วนประกอบของมันคือยอดที่ไม่มีใครอธิบายได้ตอนลูกค้าทัก"""
    buyer = await _a_user(db_session, "buyer")
    poster = await _a_poster(db_session)

    db_session.add(
        _an_order(
            poster_id=poster,
            buyer_id=buyer,
            total_amount=Decimal("600.00"),  # 500 + 150 ต้องได้ 650
            # ปรับ payout ให้สอดคล้องกับ total ที่ผิด เพื่อให้ **ด่านเดียว** ที่ทำงาน
            # คือด่านที่เทสนี้ตั้งใจพิสูจน์ (ไม่งั้น ck_orders_payout_... ยิงก่อน
            # แล้วเทสจะเขียวด้วยเหตุผลผิด — `test-quality` §3)
            seller_payout_amount=Decimal("550.00"),
        )
    )
    with pytest.raises(IntegrityError, match="ck_orders_total_is_item_plus_shipping"):
        await db_session.flush()


async def test_delivered_at_always_records_who_confirmed_it(
    db_session: AsyncSession,
) -> None:
    """🔴 ADR-0020 **A4-D1** — "ค่าที่คนกรอกต้องรู้ว่าใครกรอก"

    A4-D1 ขยาย actor จาก 1 เป็น 3 (`BUYER` · `SYSTEM_AUTO` · `ADMIN`) แต่**ไม่ได้ผ่อน
    ข้อบังคับว่าต้องบันทึกว่าใคร** — `SYSTEM_AUTO` คือกลุ่มที่ต้องนับแยกเพราะแปลว่า
    ไม่มีมนุษย์คนไหนยืนยันว่าของถึงจริง (SCR-15 AC-7)
    """
    buyer = await _a_user(db_session, "buyer")
    poster = await _a_poster(db_session)

    db_session.add(
        _an_order(
            poster_id=poster,
            buyer_id=buyer,
            status=OrderStatus.SHIPPED,
            delivered_at=NOW,  # ตั้งเวลาแต่ไม่บอกว่าใครกด
        )
    )
    with pytest.raises(IntegrityError, match="ck_orders_delivered_at_pairs_with_actor"):
        await db_session.flush()


# ══════════════════════════════════════════════════════════════════════
# BR-L6 — ด่านอนุมัติ listing
# ══════════════════════════════════════════════════════════════════════


async def test_a_poster_cannot_be_sellable_without_being_approved(
    db_session: AsyncSession,
) -> None:
    """BR-L6 — ทุก listing ต้องผ่านแอดมินอนุมัติก่อนขึ้นขาย

    🔴 ต้องอยู่ระดับ DB เพราะเส้นทางนำเข้าของ operator ทั้ง 8 เส้นเขียน `posters`
    ตรง ๆ ไม่ผ่าน service เลย (เหตุผลตัวเดียวกับ ADR-0013 D3 และ ADR-0025 D2)
    """
    db_session.add(
        Poster(
            seller_id=HOUSE_SELLER_ID,
            title="ยังไม่ผ่านการอนุมัติ",
            price=Decimal("100"),
            status=PosterStatus.available,
            approved_at=None,
        )
    )
    with pytest.raises(
        IntegrityError, match="ck_posters_sellable_requires_approved_at"
    ):
        await db_session.flush()


async def test_a_draft_poster_does_not_need_approval_yet(
    db_session: AsyncSession,
) -> None:
    """`draft` / `pending_review` ยังไม่ขึ้นขาย จึงยังไม่ต้องมี `approved_at`

    ถ้าด่านบังคับตั้งแต่ `draft` ผู้ขายจะสร้างร่างของตัวเองไม่ได้เลย
    """
    db_session.add(
        Poster(
            seller_id=HOUSE_SELLER_ID,
            title="ร่างของผู้ขาย",
            price=Decimal("100"),
            status=PosterStatus.draft,
            approved_at=None,
        )
    )
    await db_session.flush()  # ต้องไม่ระเบิด
