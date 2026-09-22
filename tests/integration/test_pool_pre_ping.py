"""🔴 INF-42 **AC-1/AC-2** — pool ต้องไม่แจก connection ที่ปลายทางตายไปแล้ว

## ทำไมต้องเป็น integration test กับ PostgreSQL จริง

อาการที่ใบนี้ปิดคือ `asyncpg InterfaceError: connection is closed` ซึ่งเกิดที่
**ชั้น socket ระหว่าง pool กับ server** · mock ไม่มีทางสร้างสถานะนั้นได้
เพราะสิ่งที่ต้องพิสูจน์คือ *SQLAlchemy ตรวจก่อนส่ง connection ให้ผู้เรียกจริงหรือไม่*
ไม่ใช่ว่าโค้ดของเราเรียกอะไร (`test-quality` §3.1)

## วิธีฆ่าที่ใช้ และทำไมถึงเชื่อได้ว่ามันตายจริง

ฆ่าจาก **อีก connection หนึ่ง** ด้วย `pg_terminate_backend(pid)` แล้ว
**ยืนยันซ้ำด้วย `pg_stat_activity` ว่า pid นั้นหายไปจริง** ก่อนจะ assert อะไรทั้งสิ้น
— ถ้าข้ามขั้นยืนยัน เทสจะเขียวได้แม้ในวันที่การฆ่าไม่สำเร็จ ซึ่งคือเทสที่พิสูจน์ว่า
"ไม่มีอะไรเกิดขึ้น" แทนที่จะพิสูจน์ว่าระบบทนได้

## สิ่งที่เทสนี้ **ไม่** พิสูจน์

❌ connection ที่ตาย **ระหว่าง** transaction — `pool_pre_ping` ตรวจเฉพาะจังหวะ
checkout เท่านั้น (INF-42 **AC-7**) · นั่นเป็นข้อจำกัดที่รู้ตัว ไม่ใช่ช่องที่ลืมปิด
"""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.core.database import POOL_KWARGS
from tests.conftest import TEST_DATABASE_URL


async def _backend_pid(engine) -> int:
    """pid ของ backend ที่ connection ตัวปัจจุบันใช้อยู่ — เบิกจาก pool ปกติ."""
    async with engine.connect() as conn:
        return await conn.scalar(text("SELECT pg_backend_pid()"))


async def test_pool_hands_out_a_live_connection_after_the_peer_is_killed() -> None:
    """เบิก → ฆ่า backend ตัวนั้นจากข้างนอก → เบิกซ้ำ **ต้องได้ผลลัพธ์ ไม่ใช่ error**

    รูปนี้คือรูปเดียวกับที่ทำให้ `POST /auth/firebase` ตอบ 500 เมื่อ 2026-09-10:
    connection ค้างอยู่ใน pool · ปลายทางหายไป · request ถัดไปหยิบมันมาใช้
    """
    # 🔴 `**POOL_KWARGS` ไม่ใช่ความสะดวก — เทสต้องผูกกับค่าที่แอปใช้จริง
    # ถ้าตั้ง `pool_pre_ping=True` ตรงนี้เอง เทสจะเขียวต่อไปแม้มีคนถอดมันออกจาก
    # `app/core/database.py` ⇒ mutation ของ AC-2 ไม่ตาย
    engine = create_async_engine(
        TEST_DATABASE_URL,
        # pool ตัวเล็กที่สุดที่ยังทดสอบได้: ขอ connection เดิมคืนมาแน่ ๆ
        pool_size=1,
        max_overflow=0,
        **POOL_KWARGS,
    )
    killer = create_async_engine(TEST_DATABASE_URL)
    try:
        pid = await _backend_pid(engine)

        # ฆ่าจากอีกคอนเนกชัน — คนละ pool คนละ engine
        async with killer.connect() as conn:
            await conn.execute(text("SELECT pg_terminate_backend(:pid)"), {"pid": pid})
            await conn.commit()

            # 🔴 ยืนยันว่าตายจริงก่อน assert อะไรต่อ (AC-1)
            still_there = await conn.scalar(
                text("SELECT 1 FROM pg_stat_activity WHERE pid = :pid"),
                {"pid": pid},
            )
        assert still_there is None, (
            f"backend pid={pid} ยังอยู่ — การฆ่าไม่สำเร็จ ⇒ เทสนี้ยังไม่ได้ทดสอบอะไรเลย "
            "อย่าอ่านผลเขียวของรอบนี้ว่าระบบทนได้"
        )

        # connection ที่เพิ่งตายยังอยู่ใน pool · รอบนี้คือรอบที่เคยได้ 500
        async with engine.connect() as conn:
            assert await conn.scalar(text("SELECT 1")) == 1
    finally:
        await engine.dispose()
        await killer.dispose()


async def test_the_app_engine_is_configured_with_pre_ping_and_no_recycle() -> None:
    """engine ตัวที่แอปใช้จริงต้องถูกตั้งค่า ไม่ใช่แค่ engine ที่เทสสร้างเอง

    เทสข้างบนพิสูจน์ว่า `pool_pre_ping` **ทำงาน** แต่มันสร้าง engine ของตัวเอง
    ⇒ ถ้าใครถอด flag ออกจาก `app/core/database.py` เทสนั้นยังเขียวอยู่ดี
    ข้อนี้จึงผูกกับ engine ตัวจริง
    """
    from app.core.database import engine as app_engine

    assert app_engine.pool._pre_ping is True, (
        "app/core/database.py ต้องตั้ง pool_pre_ping=True — ถ้าถอดออก "
        "pool จะแจก connection ที่ปลายทางตายแล้วอีกครั้ง (INF-42)"
    )
    # 🔴 ‹แก้ 2026-09-15 · INF-42 AC-3 ทาง (ก)› เดิมมี
    # `assert app_engine.pool._recycle == 3600` พร้อมข้อความว่า "ต้องมีเลขที่
    # อ้างผลวัดได้" — **assertion นั้นอ้างสิ่งที่ยังไม่มี** และตรึงเลขที่ไม่มีอะไร
    # เลือกมันไว้ให้คนรุ่นหลังเข้าใจผิดว่ามีผลวัดรองรับ
    #
    # `pool_recycle` ถูกถอดออกจากรอบนี้ทั้งก้อน ⇒ ยืนยัน **สถานะ "ไม่ตั้ง"** แทน
    # เพื่อให้การใส่เลขกลับเข้ามาเงียบ ๆ ทำไม่ได้ · ค่า `-1` คือค่าที่ SQLAlchemy
    # ใช้แทน "ไม่ recycle"
    assert app_engine.pool._recycle == -1, (
        "pool_recycle ต้องยัง 'ไม่ตั้ง' (INF-42 AC-3) — ใส่เลขกลับมาได้ก็ต่อเมื่อมี "
        "เพดานจริงของ production ที่วัดแล้วและเลขนั้นอ้างเพดานนั้นได้ "
        "ห้ามใส่เลข default ที่คนอื่นใช้กัน · เหตุผลเต็มอยู่ใน app/core/database.py"
    )
