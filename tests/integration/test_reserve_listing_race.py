"""🔴 INF-33 **AC-6** — สองคนกดจองพร้อมกันจริง ๆ แล้วต้องได้คนเดียว (US-11 AC-2 · BR-B6)

## ทำไมเทสนี้ต้องอยู่ไฟล์ของตัวเองและไม่ใช้ fixture `db_session`

`db_session` ครอบทุกเทสด้วย **ทรานแซกชันเดียว** แล้ว rollback ทิ้ง ⇒ ข้อมูลที่มันสร้าง
**ไม่มีคอนเนกชันอื่นมองเห็นเลย** และการล็อกแถวข้ามทรานแซกชันก็จำลองไม่ได้
· เทสที่ "จำลอง" การแข่งด้วยการจัดฉากสถานะเองพิสูจน์ได้แค่ว่า `if` ทำงาน
ไม่ได้พิสูจน์ว่ากลไกกันซื้อซ้อนทำงาน (`test-quality` §3.1 · `stock-integrity` §Test บังคับ)

⇒ ไฟล์นี้เปิด **สองคอนเนกชันจริง** commit จริง แล้วเก็บกวาดเองใน `finally`

## สิ่งที่เทสนี้พิสูจน์ (และไม่พิสูจน์)

* ✅ สองทรานแซกชันที่ **ทับเวลากันจริง** (บังคับด้วย `asyncio.Barrier`) ได้ผลลัพธ์
  สำเร็จหนึ่ง ล้มหนึ่ง · ฝั่งที่ล้มได้ **error ของโดเมน ไม่ใช่ `IntegrityError` ดิบ**
* ✅ คำสั่งที่ยิงจริงมี `SELECT ... FOR UPDATE` บน `posters` — `stock-integrity`
  บังคับให้ verify ว่าใช้ row lock จริง ไม่ใช่แค่ `if` (ดักการเปลี่ยนเป็น
  conditional update เงียบ ๆ ซึ่งเป็นทางที่ `poster-database` §1 ปฏิเสธไปแล้ว)
* ❌ **ไม่ได้พิสูจน์ว่าไม่มีทางเกิด deadlock** ทุกกรณี — ลำดับล็อก `posters → orders`
  (ADR-0033 D3) เป็นสิ่งที่รักษาด้วยการรีวิวโค้ด เทสสองทรานแซกชันบนเส้นทางเดียว
  ครอบเรื่องนั้นไม่ได้
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import delete, event, select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.core.exceptions import AppError, PosterAlreadyReserved, PosterNotAvailable
from app.models.enums import PosterCondition, PosterStatus, ReservationStatus
from app.models.platform import NotificationOutbox
from app.models.poster import Poster
from app.models.poster_attribute_review import PosterAttributeReview
from app.models.reservation import Reservation
from app.models.seller import SellerProfile
from app.models.user import User
from app.services import order_service
from tests.conftest import TEST_DATABASE_URL

NOW = datetime(2026, 3, 3, 4, 0, tzinfo=UTC)
PUBLISHED_AT = datetime(2026, 1, 1, tzinfo=UTC)

# 🔴 เทสนี้ **commit จริง** ⇒ ต้องเก็บกวาดเอง · เก็บกวาดด้วย "ป้าย" ไม่ใช่ด้วย id
# ที่เพิ่งสร้าง เพราะรอบที่ล้ม *ระหว่าง* seed จะไม่มี id ให้ลบ แล้วแถวค้างจะไปทำให้
# เทสไฟล์อื่นที่นับจำนวนแถวแดงในรอบถัดไป (เกิดมาแล้วจริงระหว่างเขียนใบนี้)
EMAIL_MARKER = "race-%@example.test"
POSTER_MARKER = "Race Target"
SELLER_MARKER = "ร้านแข่งจอง"


async def _seed(engine) -> tuple[uuid.UUID, uuid.UUID, list[uuid.UUID]]:
    """สร้างของจริงแบบ commit — ต้องมองเห็นได้จากทุกคอนเนกชัน"""
    async with AsyncSession(engine, expire_on_commit=False) as session:
        seller_user = User(
            email=f"race-seller-{uuid.uuid4().hex[:8]}@example.test", is_verified=True
        )
        buyers = [
            User(
                email=f"race-buyer-{index}-{uuid.uuid4().hex[:8]}@example.test",
                is_verified=True,
            )
            for index in range(2)
        ]
        session.add_all([seller_user, *buyers])
        await session.flush()

        seller = SellerProfile(
            user_id=seller_user.id,
            display_name="ร้านแข่งจอง",
            real_name="ผู้ขายทดสอบ",
            bank_name="ธนาคารทดสอบ",
            bank_account_name="ผู้ขายทดสอบ",
            bank_account_no="0000000000",
        )
        session.add(seller)
        await session.flush()

        poster = Poster(
            seller_id=seller.id,
            approved_at=PUBLISHED_AT,
            title="Race Target",
            price=Decimal("4500.00"),
            shipping_fee=Decimal("150.00"),
            condition_grade=PosterCondition.very_fine,
            status=PosterStatus.available,
            published_at=PUBLISHED_AT,
        )
        session.add(poster)
        await session.flush()
        await session.commit()
        return poster.id, seller.id, [buyer.id for buyer in buyers] + [seller_user.id]


async def _cleanup(engine) -> None:
    """ลบทุกแถวที่ไฟล์นี้เคยสร้าง — เรียกทั้งก่อน seed และใน `finally`

    เรียงลำดับตาม FK: `posters.seller_id` เป็น `RESTRICT` และ `reservations.poster_id`
    ก็เป็น `RESTRICT` ⇒ ลบลูกก่อนแม่เสมอ
    """
    async with AsyncSession(engine, expire_on_commit=False) as session:
        user_ids = select(User.id).where(User.email.like(EMAIL_MARKER))
        poster_ids = select(Poster.id).where(Poster.title == POSTER_MARKER)

        await session.execute(
            delete(NotificationOutbox).where(
                NotificationOutbox.recipient_user_id.in_(user_ids)
            )
        )
        await session.execute(
            delete(PosterAttributeReview).where(
                PosterAttributeReview.poster_id.in_(poster_ids)
            )
        )
        await session.execute(
            delete(Reservation).where(Reservation.poster_id.in_(poster_ids))
        )
        await session.execute(delete(Poster).where(Poster.title == POSTER_MARKER))
        await session.execute(
            delete(SellerProfile).where(SellerProfile.display_name == SELLER_MARKER)
        )
        await session.execute(delete(User).where(User.email.like(EMAIL_MARKER)))
        await session.commit()


async def _attempt(
    engine, poster_id: uuid.UUID, buyer_id: uuid.UUID, barrier: asyncio.Barrier
) -> Exception | None:
    """เปิดทรานแซกชันของตัวเอง → รอให้อีกฝั่งพร้อม → แล้วค่อยยิงพร้อมกัน

    การรอที่ barrier **หลังเปิดทรานแซกชันแล้ว** คือสิ่งที่ทำให้สองฝั่งทับเวลากันจริง
    ถ้าไม่มี barrier ตัวแรกอาจจบและ commit ไปก่อนตัวที่สองเริ่ม ⇒ เทสจะเขียวโดย
    ไม่เคยมีการแข่งเกิดขึ้นเลย
    """
    async with AsyncSession(engine, expire_on_commit=False) as session:
        await session.execute(select(1))  # เปิดทรานแซกชันจริงบนคอนเนกชันนี้
        await barrier.wait()
        try:
            await order_service.reserve_listing(
                session, poster_id, buyer_user_id=buyer_id, at=NOW
            )
            await session.commit()
            return None
        except Exception as exc:  # noqa: BLE001 — เทสต้องดูว่าได้ error ชนิดไหน
            await session.rollback()
            return exc


async def test_two_simultaneous_reservations_leave_exactly_one_winner() -> None:
    engine = create_async_engine(TEST_DATABASE_URL)
    statements: list[str] = []

    @event.listens_for(engine.sync_engine, "before_cursor_execute")
    def _record(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement)

    try:
        await _cleanup(engine)  # กันแถวค้างจากรอบที่ล้มกลางทาง
        poster_id, _seller_id, user_ids = await _seed(engine)
        buyer_ids = user_ids[:2]
        barrier = asyncio.Barrier(len(buyer_ids))
        outcomes = await asyncio.gather(
            *(_attempt(engine, poster_id, buyer_id, barrier) for buyer_id in buyer_ids)
        )

        winners = [outcome for outcome in outcomes if outcome is None]
        losers = [outcome for outcome in outcomes if outcome is not None]
        assert len(winners) == 1, outcomes
        assert len(losers) == 1, outcomes

        # 🔴 ฝั่งที่แพ้ต้องได้ error ของโดเมน ไม่ใช่ IntegrityError ดิบ (= 500)
        assert isinstance(losers[0], AppError), repr(losers[0])
        assert isinstance(losers[0], (PosterNotAvailable, PosterAlreadyReserved)), repr(
            losers[0]
        )
        assert losers[0].status_code == 409, repr(losers[0])

        async with AsyncSession(engine, expire_on_commit=False) as session:
            reservations = (
                (
                    await session.execute(
                        select(Reservation).where(Reservation.poster_id == poster_id)
                    )
                )
                .scalars()
                .all()
            )
            poster = await session.get(Poster, poster_id)

        assert len(reservations) == 1, reservations
        assert reservations[0].status is ReservationStatus.active
        assert poster.status is PosterStatus.reserved

        locking = [
            statement
            for statement in statements
            if "FOR UPDATE" in statement.upper() and "posters" in statement
        ]
        assert locking, "ไม่พบ SELECT ... FOR UPDATE บน posters — row lock หายไป"
    finally:
        await _cleanup(engine)
        await engine.dispose()
