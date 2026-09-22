"""🔴 ด่านบังคับก่อน SCR-07 AC-14/AC-16 (ADR-0037 D5) — เทสควบคุมที่ต้องผ่านก่อน
จะเขียนเทส race ระดับ HTTP ใด ๆ ที่พึ่ง fixture `real_client`

`real_client` (`tests/conftest.py`) ให้ทุก request session/connection ของตัวเอง —
ต่างจาก `client` ที่แชร์ `db_session` ตัวเดียวบนทรานแซกชันเดียว (พิสูจน์ concurrency
ไม่ได้เลยตามที่ docstring ของมันเขียนไว้) แต่ **การมี connection แยกกันไม่ได้แปลว่า
สอง request ที่ยิงผ่าน `asyncio.gather` จะ "ชน" กันจริงที่ระดับ DB** — ความเสี่ยงที่
ADR-0037 D5 เขียนไว้ล่วงหน้าคือ `ASGITransport` รันทุก request ใน event loop เดียว
ถ้ามีจุดไหนบล็อก loop ทั้งตัว (ไม่ `await` คืนการควบคุม) การชนจะไม่เกิดขึ้นจริง

ไฟล์นี้พิสูจน์โดย**วัด ไม่ใช่อ่านโค้ด** (`test-quality` §3.1):

1. ยิง request A (`POST /listings/{id}/reserve`) ก่อน — บังคับให้มันถือ row lock
   ของ `posters` ไว้นาน `HOLD_SECONDS` ด้วยการ monkeypatch
   `order_service.release_due_reservations` ให้ `asyncio.sleep()` ก่อนทำงานจริง
   (เรียกหลัง `get_for_update()` เสมอ ⇒ ล็อกแถวไปแล้วตอนที่หลับ)
2. ระหว่างที่ A กำลังหลับ (ยังไม่ commit) ยิง request B บนโปสเตอร์ **ใบเดียวกัน**
   ด้วยผู้ใช้อีกคน ผ่าน `asyncio.gather` (ทั้งคู่ยิงผ่าน `real_client`)
3. Poll `pg_locks`/`pg_stat_activity` ผ่าน connection ที่สาม (asyncpg ตรง ๆ ไม่ผ่าน
   SQLAlchemy) ระหว่างที่ A ถือ lock อยู่ — ต้องเห็น **backend ที่กำลังรอ lock จริง**
   (คำขอของ B กำลังรอจริง ไม่ใช่แค่ "ช้า" ด้วยเหตุผลอื่น)
4. วัดเวลาที่ A และ B ใช้ทั้งหมด — **B ต้องนานกว่า A อย่างมีนัยสำคัญ**
   (`elapsed_b >= elapsed_a + HOLD_SECONDS * 0.5`) 🔴 **ไม่ใช่ `elapsed_b >=
   HOLD_SECONDS` เฉย ๆ** (แก้ 2026-09-15 · code-critic รอบ 1 F5) — B เรียก
   `_slow_release_due_reservations` เหมือนกัน จึงมี sleep(HOLD_SECONDS) ของ
   ตัวเองอยู่แล้วไม่ว่าจะถูกบล็อกหรือไม่ ⇒ `elapsed_b >= HOLD_SECONDS` เป็นจริง
   เสมอและไม่มีอำนาจแยกแยะอะไรเลย จุดที่แยกแยะได้จริงคือ**ผลต่างระหว่าง A กับ B**:
   ถ้าไม่ถูกบล็อกทั้งคู่จะได้เวลาใกล้กัน (sleep คนละก้อนพร้อมกัน) ถ้าถูกบล็อก B ต้อง
   นานกว่า A ชัดเจน (รอ A ปล่อย lock ก่อน แล้วค่อยไปเจอ sleep ของตัวเองอีกที) —
   ข้อ 3 (`pg_locks`) ยังเป็นหลักฐานหลักอยู่ดี ข้อ 4 เป็นแค่หลักฐานเสริมที่ต้อง
   ออกแบบให้แยกแยะได้จริง ไม่ใช่ผ่านเฉย ๆ

🔴 **ถ้าข้อ 3 ไม่เจอ waiting lock เลย = พิสูจน์ไม่ได้ว่าชน** — เทส race ที่ใช้
`real_client` (`test_reserve_listing_endpoint_race.py`) เป็นโมฆะทั้งชุด ต้องรายงาน
ตามนั้น ห้ามอ้างว่าปิด AC-14/AC-16
"""

from __future__ import annotations

import asyncio
import time
import uuid
from datetime import UTC, datetime
from decimal import Decimal

import asyncpg
import pytest
from sqlalchemy import delete, select
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.core import security
from app.models.enums import PosterCondition, PosterStatus
from app.models.poster import Poster
from app.models.reservation import Reservation
from app.models.seller import SellerProfile
from app.models.user import User
from app.services import order_service
from tests.conftest import TEST_DATABASE_URL

_TEST_DB_URL = make_url(TEST_DATABASE_URL)

NOW = datetime(2026, 3, 3, 4, 0, tzinfo=UTC)
PUBLISHED_AT = datetime(2026, 1, 1, tzinfo=UTC)
VERIFIED_AT = datetime(2026, 1, 1, 6, 0, tzinfo=UTC)
APPROVED_AT = datetime(2026, 1, 2, tzinfo=UTC)

HOLD_SECONDS = 1.5

# ป้าย — เก็บกวาดด้วยชื่อ ไม่ใช่ id (เหมือน test_reserve_listing_race.py)
EMAIL_MARKER = "lockproof-%@example.test"
POSTER_MARKER = "Lock Proof Target"
SELLER_MARKER = "ร้านพิสูจน์ล็อก"


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
    """คืน (poster_id, buyer_a_id, buyer_b_id) — commit จริงเพื่อให้ HTTP request
    ที่ใช้ connection คนละตัวมองเห็น"""
    async with AsyncSession(engine, expire_on_commit=False) as session:
        seller_user = User(
            email=f"lockproof-seller-{uuid.uuid4().hex[:8]}@example.test",
            is_verified=True,
        )
        buyer_a = User(
            email=f"lockproof-buyer-a-{uuid.uuid4().hex[:8]}@example.test",
            is_verified=True,
        )
        buyer_b = User(
            email=f"lockproof-buyer-b-{uuid.uuid4().hex[:8]}@example.test",
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


async def _waiting_lock_seen_while_posters_row_is_held(deadline: float) -> bool:
    """Poll `pg_locks`/`pg_stat_activity` ผ่าน connection แยก (asyncpg ตรง ๆ) จนเจอ
    **ทั้งสองเงื่อนไขพร้อมกัน** หรือหมดเวลา — คืน True ถ้าเจอจริง:
    (1) มี backend ใน `poster_nung_test` **กำลังรอ lock อยู่จริง**
    (2) แถว `posters` **มี lock ที่ granted อยู่จริง** ในฐานเดียวกัน (มีคนถืออยู่)

    🔴 **`SELECT ... FOR UPDATE` ที่ถูกบล็อกไม่ได้โผล่เป็น `pg_locks.locktype =
    'tuple'`** อย่างที่คิดตอนแรก (พิสูจน์แล้วว่า query แบบนั้นไม่เจออะไรเลยทั้งที่
    `elapsed_b` วัดได้ว่ารอจริง ~1 วินาทีตาม `HOLD_SECONDS`) — กลไกจริงของ Postgres
    คือฝั่งที่ถูกบล็อกไปรอ **`locktype = 'transactionid'`** บน XID ของธุรกรรมที่ถือ
    row lock อยู่ (มาตรฐานเดียวกับ query หา "blocking session" ทั่วไป)

    🔴 **แก้ 2026-09-15 · code-critic รอบ 1 F6** — เวอร์ชันเดิม query ทั้ง cluster
    ไม่กรอง `database` และไม่กรองว่า lock ที่รอเกี่ยวกับตาราง `posters` จริงไหม
    (ชื่อฟังก์ชันเดิม `_waiting_tuple_lock_seen_on_posters` จึงอ้างเกินกว่าที่วัดจริง
    — โฮสต์ทดสอบนี้มีอีก database `poster_nung_db` อยู่ cluster เดียวกัน คิวรีเดิม
    จะนับ lock ของ database อื่นปนด้วยได้) ⇒ เวอร์ชันนี้ (ก) กรองทุก query ด้วย
    `d.datname = current_database()` (asyncpg เชื่อมเข้า `poster_nung_test` เสมออยู่
    แล้วในไฟล์นี้ แต่ query ต้อง join `pg_database`/`pg_stat_activity` เพื่อกรองด้วย
    ตัวมันเองด้วย ไม่ใช่พึ่งว่า connection อยู่ database ไหน) และ (ข) เพิ่มเงื่อนไข
    "มี granted lock บน `posters` จริง" คู่กับ "มีคนรอ lock อยู่จริง" — ในสถานการณ์
    ควบคุมของเทสนี้ (ไม่มีอะไรอื่นแตะ DB พร้อมกัน) สองเงื่อนไขนี้ร่วมกันเป็นหลักฐาน
    ที่ตรงชื่อฟังก์ชันจริง ๆ ว่าการรอเกี่ยวกับแถว `posters` ที่ถูกล็อกอยู่
    """
    conn = await asyncpg.connect(
        user=_TEST_DB_URL.username,
        password=_TEST_DB_URL.password,
        host=_TEST_DB_URL.host,
        port=_TEST_DB_URL.port,
        database=_TEST_DB_URL.database,
    )
    try:
        while time.monotonic() < deadline:
            posters_row_held = await conn.fetchval("""
                SELECT count(*) FROM pg_locks l
                JOIN pg_database d ON d.oid = l.database
                WHERE l.relation = 'posters'::regclass
                  AND l.granted
                  AND d.datname = current_database()
                """)
            waiting_backends = await conn.fetchval("""
                SELECT count(*) FROM pg_stat_activity
                WHERE wait_event_type = 'Lock' AND datname = current_database()
                """)
            if posters_row_held and waiting_backends:
                return True
            await asyncio.sleep(0.05)
        return False
    finally:
        await conn.close()


async def test_two_concurrent_http_reservations_produce_a_real_blocked_row_lock(
    real_client, monkeypatch: pytest.MonkeyPatch
) -> None:
    engine = create_async_engine(TEST_DATABASE_URL)
    original_release = order_service.release_due_reservations

    async def _slow_release_due_reservations(session, *, poster_id, at):
        # เรียกหลัง get_for_update() เสมอ (ดู reserve_listing()) ⇒ ตอนนี้ถือ row
        # lock ของ posters ไว้แล้ว — หลับโดยไม่ปล่อยทรานแซกชัน
        await asyncio.sleep(HOLD_SECONDS)
        return await original_release(session, poster_id=poster_id, at=at)

    monkeypatch.setattr(
        order_service, "release_due_reservations", _slow_release_due_reservations
    )

    try:
        await _cleanup(engine)
        poster_id, buyer_a_id, buyer_b_id = await _seed(engine)
        token_a = security.create_access_token(str(buyer_a_id))
        token_b = security.create_access_token(str(buyer_b_id))
        url = f"/api/v1/listings/{poster_id}/reserve"

        async def _timed_request(token: str) -> tuple[float, object]:
            started = time.monotonic()
            res = await real_client.post(
                url, headers={"Authorization": f"Bearer {token}"}
            )
            return time.monotonic() - started, res

        # request A ยิงก่อน ให้มันเข้าไปถือ lock แล้วเริ่มหลับก่อน B ยิงตาม
        task_a = asyncio.create_task(_timed_request(token_a))
        await asyncio.sleep(0.2)  # ให้ A ผ่าน get_for_update() แล้วเข้า sleep แน่ๆ

        # poll pg_locks ระหว่างที่ A ยังหลับอยู่ — ยังไม่ยิง B
        seen_before_b = await _waiting_lock_seen_while_posters_row_is_held(
            time.monotonic() + 0.3
        )

        task_b = asyncio.create_task(_timed_request(token_b))
        # poll อีกรอบระหว่างที่ A ยังหลับ (เหลือเวลาอีกพอสมควร) — ตอนนี้ B ควรกำลัง
        # รอ get_for_update() ของตัวเองอยู่
        seen_while_both_inflight = await _waiting_lock_seen_while_posters_row_is_held(
            time.monotonic() + max(HOLD_SECONDS - 0.3, 0.1)
        )

        (elapsed_a, res_a), (elapsed_b, res_b) = await asyncio.gather(task_a, task_b)
    finally:
        await _cleanup(engine)
        await engine.dispose()

    # ก่อน B ยิง ไม่ควรมี waiting lock เลย (มีแค่ A ถือ granted=true)
    assert (
        not seen_before_b
    ), "เจอ waiting tuple lock ทั้งที่ B ยังไม่ยิงเลย — สัญญาณของ query/marker ผิด"
    # 🔴 หัวใจของเทสนี้ — B ต้องเคยไปโผล่เป็น waiting lock ระหว่างที่ A ถือ row lock
    # อยู่จริง ถ้าไม่เจอ = พิสูจน์ไม่ได้ว่า real_client ทำให้สองคำขอชนกันจริง
    assert seen_while_both_inflight, (
        "ไม่เจอ waiting tuple lock ของ posters ระหว่างที่ A ถือ lock อยู่ — "
        "แปลว่าพิสูจน์ไม่ได้ว่า real_client ทำให้สอง request ชนกันจริงที่ระดับ DB "
        "(เทส race ที่พึ่ง fixture นี้เป็นโมฆะจนกว่าจะแก้ข้อนี้)"
    )
    # 🔴 แก้ 2026-09-15 · code-critic รอบ 1 F5 — assertion เดิม `elapsed_b >=
    # HOLD_SECONDS * 0.7` **ไม่มีอำนาจแยกแยะอะไรเลย** เพราะ B เองก็เรียก
    # `_slow_release_due_reservations` ซึ่ง sleep(HOLD_SECONDS) ของตัวเองอยู่แล้ว
    # ไม่ว่าจะโดนบล็อกจริงหรือไม่ก็ตาม ⇒ elapsed_b >= ~HOLD_SECONDS เป็นจริงเสมอ
    # แม้ A/B รันขนานกันเต็มที่โดยไม่มี row lock เลยสักนิด (ทั้งสองก็แค่ sleep
    # คนละก้อนพร้อมกัน)
    #
    # ท่อนที่**มีอำนาจแยกแยะจริง**คือเทียบกับ `elapsed_a`: ถ้าไม่มีการบล็อกกัน
    # A และ B ต่างก็มีแค่ sleep(HOLD_SECONDS) ของตัวเอง + overhead เท่า ๆ กัน
    # ⇒ `elapsed_a ≈ elapsed_b` แต่ถ้า B ต้องรอให้ A ปล่อย row lock ก่อน (แล้วค่อย
    # ไปเจอ sleep(HOLD_SECONDS) ของตัวเองอีกที) เวลาของ B ต้องยาวกว่า A **อย่างมี
    # นัยสำคัญ** (ประมาณ 2 เท่าของ HOLD_SECONDS ในทางปฏิบัติ) — ของจริงที่วัดได้ตอน
    # เขียนใบนี้: elapsed_a≈1.58s · elapsed_b≈2.54s (HOLD_SECONDS=1.5s)
    assert elapsed_b >= elapsed_a + HOLD_SECONDS * 0.5, (elapsed_a, elapsed_b)

    statuses = {res_a.status_code, res_b.status_code}
    assert statuses == {201, 409}, (
        res_a.status_code,
        res_a.text,
        res_b.status_code,
        res_b.text,
    )
