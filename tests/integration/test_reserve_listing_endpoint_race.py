"""SCR-07 สไลซ์ A · A7 — AC-14 (race กันซื้อซ้อนที่ระดับ HTTP) และ AC-16
(lazy-expire ต้องจองใหม่ได้โดยไม่มีใครมาล้างก่อน) — ADR-0037 D5

🔴 **AC-14 ต้องผ่านด่าน A6 ก่อนเท่านั้น** (`test_real_client_concurrent_locking.py`)
— ไฟล์นั้นพิสูจน์แล้วว่า `real_client` ทำให้สอง request ชนกันจริงที่ระดับ DB
(`pg_stat_activity.wait_event_type = 'Lock'` ระหว่างที่อีกฝั่งถือ row lock อยู่)
ไฟล์นี้จึงใช้ fixture เดียวกันต่อได้โดยไม่ต้องพิสูจน์ซ้ำ

AC-16 ไม่ต้องการการชนกันข้าม connection (เป็นลำดับเหตุการณ์เดียว ไม่ใช่ race) —
ใช้ fixture `client` ธรรมดาได้เต็มที่
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy import delete, event, select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.core import security
from app.models.enums import PosterCondition, PosterStatus, ReservationStatus
from app.models.poster import Poster
from app.models.reservation import Reservation
from app.models.seller import SellerProfile
from app.models.user import User
from app.repositories import poster_repository
from tests.conftest import TEST_DATABASE_URL

PUBLISHED_AT = datetime(2026, 1, 1, tzinfo=UTC)
VERIFIED_AT = datetime(2026, 1, 1, 6, 0, tzinfo=UTC)
APPROVED_AT = datetime(2026, 1, 2, tzinfo=UTC)

EMAIL_MARKER = "http-race-%@example.test"
POSTER_MARKER = "HTTP Race Target"
SELLER_MARKER = "ร้านแข่งจอง HTTP"


async def _cleanup(engine) -> None:
    async with AsyncSession(engine, expire_on_commit=False) as session:
        poster_ids = select(Poster.id).where(Poster.title == POSTER_MARKER)
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
            email=f"http-race-seller-{uuid.uuid4().hex[:8]}@example.test",
            is_verified=True,
        )
        buyer_a = User(
            email=f"http-race-buyer-a-{uuid.uuid4().hex[:8]}@example.test",
            is_verified=True,
        )
        buyer_b = User(
            email=f"http-race-buyer-b-{uuid.uuid4().hex[:8]}@example.test",
            is_verified=True,
        )
        session.add_all([seller_user, buyer_a, buyer_b])
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
        return poster.id, buyer_a.id, buyer_b.id


# ══════════════════════════════════════════════════════════════════════════
# AC-14 — สอง request พร้อมกันผ่าน ASGI บนโปสเตอร์ใบเดียว
# ══════════════════════════════════════════════════════════════════════════


async def test_two_concurrent_http_requests_leave_exactly_one_winner(
    real_client: AsyncClient,
) -> None:
    engine = create_async_engine(TEST_DATABASE_URL)
    statements: list[str] = []

    @event.listens_for(real_client.test_engine.sync_engine, "before_cursor_execute")
    def _record(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement)

    try:
        await _cleanup(engine)
        poster_id, buyer_a_id, buyer_b_id = await _seed(engine)
        token_a = security.create_access_token(str(buyer_a_id))
        token_b = security.create_access_token(str(buyer_b_id))
        url = f"/api/v1/listings/{poster_id}/reserve"

        res_a, res_b = await asyncio.gather(
            real_client.post(url, headers={"Authorization": f"Bearer {token_a}"}),
            real_client.post(url, headers={"Authorization": f"Bearer {token_b}"}),
        )

        statuses = sorted([res_a.status_code, res_b.status_code])
        assert statuses == [201, 409], (res_a.text, res_b.text)

        loser = res_a if res_a.status_code == 409 else res_b
        assert loser.json()["error_code"] in (
            "POSTER_NOT_AVAILABLE",
            "POSTER_ALREADY_RESERVED",
        ), loser.text

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
        assert len(reservations) == 1, reservations
        assert reservations[0].status is ReservationStatus.active

        # 🔴 หัวใจของ mutation-proof — ไม่ใช่แค่เช็คผลลัพธ์ปลายทาง (ผลลัพธ์อาจดูถูก
        # โดยบังเอิญเพราะ uq_active_reservation_per_poster เป็นเกราะชั้นที่สอง)
        # ต้องยืนยันว่า *กลไกที่ใช้จริง* คือ row lock (`stock-integrity` — ห้ามเช็คแค่ if)
        locking = [
            s for s in statements if "FOR UPDATE" in s.upper() and "posters" in s
        ]
        assert locking, "ไม่พบ SELECT ... FOR UPDATE บน posters — row lock หายไป"
    finally:
        await _cleanup(engine)
        await engine.dispose()


async def test_removing_the_row_lock_breaks_the_for_update_proof(
    real_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """🔴 mutation ที่ต้องตาย (ADR-0037 §A7 · SCR-07 AC-14) — ทำให้ handler เข้าเส้น
    ที่ไม่มี row lock (`get_by_id()` แทน `get_for_update()`) แล้วพิสูจน์ว่าเทสข้างบน
    จับได้จริง (รันแยกในไฟล์นี้เพื่อไม่ต้องแก้ไฟล์จริงแล้วรีเวิร์ต — patch ใน process
    เดียวกันตามท่าที่ `test-quality` §2 แนะนำ)"""
    monkeypatch.setattr(
        poster_repository, "get_for_update", poster_repository.get_by_id
    )

    engine = create_async_engine(TEST_DATABASE_URL)
    statements: list[str] = []

    @event.listens_for(real_client.test_engine.sync_engine, "before_cursor_execute")
    def _record(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement)

    try:
        await _cleanup(engine)
        poster_id, buyer_a_id, buyer_b_id = await _seed(engine)
        token_a = security.create_access_token(str(buyer_a_id))
        token_b = security.create_access_token(str(buyer_b_id))
        url = f"/api/v1/listings/{poster_id}/reserve"

        await asyncio.gather(
            real_client.post(url, headers={"Authorization": f"Bearer {token_a}"}),
            real_client.post(url, headers={"Authorization": f"Bearer {token_b}"}),
        )

        locking = [
            s for s in statements if "FOR UPDATE" in s.upper() and "posters" in s
        ]
        # ต้อง "ไม่เจอ" — พิสูจน์ว่า mutation ลบ row lock ออกไปจริง
        assert not locking, "ยังเจอ FOR UPDATE ทั้งที่ patch get_for_update() ออกแล้ว"
    finally:
        await _cleanup(engine)
        await engine.dispose()


# ══════════════════════════════════════════════════════════════════════════
# AC-16 — reservation หมดอายุที่ไม่มีใครแตะเลย ต้องจองใหม่ได้ (lazy-expire)
# ══════════════════════════════════════════════════════════════════════════


async def test_an_untouched_expired_reservation_can_be_reserved_again(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """🔴 ห้ามเรียกอะไรมาล้างก่อน ห้าม `UPDATE` สถานะเอง — จุดทั้งหมดของเทสนี้คือ
    พิสูจน์ว่าเส้นทางจริง (`reserve_listing()` → `release_due_reservations()`)
    ปล่อยของเองได้โดยไม่มีใครช่วย (`test-quality` §3.1)"""
    seller_owner = User(
        email=f"ac16-seller-{uuid.uuid4().hex[:8]}@example.test", is_verified=True
    )
    db_session.add(seller_owner)
    await db_session.flush()
    seller = SellerProfile(
        user_id=seller_owner.id,
        display_name="ร้าน AC-16",
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
        title="AC-16 Target",
        price=Decimal("1000.00"),
        shipping_fee=Decimal("0.00"),
        condition_grade=PosterCondition.very_fine,
        status=PosterStatus.reserved,  # ของยังค้างเป็น reserved — ไม่มีใครมาล้างก่อน
        published_at=PUBLISHED_AT,
        verified_at=VERIFIED_AT,
    )
    db_session.add(poster)
    await db_session.flush()

    stale_buyer = User(
        email=f"ac16-buyer-a-{uuid.uuid4().hex[:8]}@example.test", is_verified=True
    )
    new_buyer = User(
        email=f"ac16-buyer-b-{uuid.uuid4().hex[:8]}@example.test", is_verified=True
    )
    db_session.add_all([stale_buyer, new_buyer])
    await db_session.flush()

    # จองหมดอายุไปแล้วนานมาก — จัดฉากตรง ๆ ระดับ DB (ไม่ผ่าน service) เพราะจุดสำคัญ
    # ของเทสนี้คือ "ไม่มีใครมาล้างก่อน" ไม่ใช่ประวัติว่าใครเคยจองยังไง
    stale = Reservation(
        poster_id=poster.id,
        user_id=stale_buyer.id,
        status=ReservationStatus.active,  # ยังเป็น active ใน DB — ไม่มีใครพลิกให้
        expires_at=datetime(2026, 1, 1, tzinfo=UTC),  # หมดอายุไปนานแล้ว
    )
    db_session.add(stale)
    await db_session.commit()

    res = await client.post(
        f"/api/v1/listings/{poster.id}/reserve",
        headers={
            "Authorization": f"Bearer {security.create_access_token(str(new_buyer.id))}"
        },
    )

    assert res.status_code == 201, res.text
    body = res.json()
    assert body["user_id"] == str(new_buyer.id)
    assert body["status"] == "active"


async def test_removing_lazy_expire_breaks_the_untouched_expired_reservation_case(
    client: AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """🔴 mutation ที่ต้องตาย — ถอด `release_due_reservations()` ออกจาก
    `reserve_listing()` แล้วเคสข้างบนต้องแดง (409 แทนที่จะเป็น 201)"""
    from app.services import order_service

    async def _noop_release(session, *, poster_id, at):
        return None

    monkeypatch.setattr(order_service, "release_due_reservations", _noop_release)

    seller_owner = User(
        email=f"ac16m-seller-{uuid.uuid4().hex[:8]}@example.test", is_verified=True
    )
    db_session.add(seller_owner)
    await db_session.flush()
    seller = SellerProfile(
        user_id=seller_owner.id,
        display_name="ร้าน AC-16 mutation",
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
        title="AC-16 Mutation Target",
        price=Decimal("1000.00"),
        shipping_fee=Decimal("0.00"),
        condition_grade=PosterCondition.very_fine,
        status=PosterStatus.reserved,
        published_at=PUBLISHED_AT,
        verified_at=VERIFIED_AT,
    )
    db_session.add(poster)
    await db_session.flush()
    stale_buyer = User(
        email=f"ac16m-buyer-a-{uuid.uuid4().hex[:8]}@example.test", is_verified=True
    )
    new_buyer = User(
        email=f"ac16m-buyer-b-{uuid.uuid4().hex[:8]}@example.test", is_verified=True
    )
    db_session.add_all([stale_buyer, new_buyer])
    await db_session.flush()
    db_session.add(
        Reservation(
            poster_id=poster.id,
            user_id=stale_buyer.id,
            status=ReservationStatus.active,
            expires_at=datetime(2026, 1, 1, tzinfo=UTC),
        )
    )
    await db_session.commit()

    res = await client.post(
        f"/api/v1/listings/{poster.id}/reserve",
        headers={
            "Authorization": f"Bearer {security.create_access_token(str(new_buyer.id))}"
        },
    )

    assert res.status_code != 201, "mutation ควรทำให้จองไม่ได้ แต่กลับสำเร็จ"
