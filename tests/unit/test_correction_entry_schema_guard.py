"""ด่าน schema ของ `correction_entry._check_schema()` — เทสที่ระดับ DB จริง (INF-21 G3)

`AND table_schema = current_schema()` ในคำถามที่ยิงเข้า `information_schema.columns`
**พิสูจน์ด้วย session ปลอมไม่ได้** โดยไม่ไปนั่งอ่านตัว SQL เป็นสตริง ซึ่งเป็นการ
assert ว่าโค้ดเท่ากับตัวเอง (skill `test-quality` §3.1) · สิ่งที่บรรทัดนั้นกันคือ
**ตารางชื่อเดียวกันใน schema อื่นตอบแทน** ซึ่งเป็นพฤติกรรมของ PostgreSQL ล้วน ๆ
จึงต้องยิงเข้า DB จริง — หลักเดียวกับ `test_poster_publication_constraint.py`
(skill `test-quality` §6: กฎที่อยู่ระดับ DB ต้องเทสที่ระดับ DB)

ทำไมมันสำคัญกับเส้นนี้เป็นพิเศษ: ด่านนี้คือสิ่งเดียวที่กันไม่ให้สคริปต์เขียนทับค่าที่
ลูกค้าเห็นบนหน้าร้านไปแล้ว **ลงปลายทางที่ยังไม่มีที่เก็บเหตุผล** — ผลคือ audit ที่บอก
ว่าใครแก้อะไร แต่ตอบไม่ได้ว่าทำไม (ADR-0010 A-D2 ข้อ 2/3) · ด่านที่ตอบว่า "มีคอลัมน์
แล้ว" เพราะไปเจอตารางของ schema อื่น คือด่านที่ปล่อยผ่านทั้งที่ปลายทางยังไม่พร้อม

`db_session` ครอบทุกอย่างด้วย transaction เดียวแล้ว rollback ทิ้งเสมอ (`conftest.py`)
· DDL ของ PostgreSQL อยู่ใน transaction ได้ ทั้ง schema ที่สร้างและคอลัมน์ที่ถอด
จึงหายไปเองเมื่อเทสจบ ไม่ว่าจะผ่านหรือไม่ผ่าน
"""

from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.poster_attribute_review import PosterAttributeReview
from scripts.seed import correction_entry as mod
from scripts.seed.correction_entry import PrecheckError

TABLE = PosterAttributeReview.__tablename__
DECOY_SCHEMA = "inf21_g3_decoy"


async def _drop_the_reason_column(session: AsyncSession) -> None:
    """ทำให้ *ปลายทางจริง* ขาดคอลัมน์ — สภาพเดียวกับ DB ที่ยังไม่ `upgrade head`."""
    await session.execute(text(f"ALTER TABLE {TABLE} DROP COLUMN reason"))


async def _plant_a_same_named_table_in_another_schema(session: AsyncSession) -> None:
    """ตารางชื่อเดียวกัน **ที่มีคอลัมน์ครบ** ใน schema อื่นของ database เดียวกัน

    ไม่ใช่สถานการณ์สมมุติ: schema เก่าที่ยังไม่ได้ลบ · schema ของ tenant อื่น ·
    การ restore dump เข้า schema สำรอง — ทั้งหมดทำให้ database หนึ่งมีตารางชื่อนี้
    มากกว่าหนึ่งตัว และ `information_schema.columns` เห็นทุกตัวเท่ากันหมด
    """
    await session.execute(text(f"DROP SCHEMA IF EXISTS {DECOY_SCHEMA} CASCADE"))
    await session.execute(text(f"CREATE SCHEMA {DECOY_SCHEMA}"))
    await session.execute(text(f"CREATE TABLE {DECOY_SCHEMA}.{TABLE} (reason text)"))


async def test_the_guard_passes_on_a_target_that_really_has_the_column(
    db_session: AsyncSession,
) -> None:
    """positive control — ถ้าไม่มีตัวนี้ ชุดนี้เขียวได้ด้วยด่านที่ **ปฏิเสธทุกกรณี**

    `poster_nung_test` ถูก `alembic upgrade head` ไว้แล้ว จึงเป็นภาพของปลายทางที่พร้อม
    """
    assert await mod._check_schema(db_session) is None


async def test_a_target_missing_the_column_is_refused(
    db_session: AsyncSession,
) -> None:
    """ควบคุมอีกด้าน — ยืนยันว่าการถอดคอลัมน์ในเทสนี้ *มีผลจริง* กับด่าน

    ถ้าเทสนี้ไม่แดงตอนถอดคอลัมน์ แปลว่าเทสตัวล่างไม่ได้พิสูจน์อะไรเลย
    """
    await _drop_the_reason_column(db_session)
    with pytest.raises(PrecheckError, match="reason"):
        await mod._check_schema(db_session)


async def test_a_table_of_the_same_name_in_another_schema_cannot_answer_for_the_target(
    db_session: AsyncSession,
) -> None:
    """🔴 ตัวฆ่า mutation ที่ถอด `AND table_schema = current_schema()` ออก (G3)

    ปลายทางจริง **ไม่มี** คอลัมน์ `reason` แต่ database เดียวกันมีตารางชื่อเดียวกัน
    ที่ **มี** คอลัมน์นั้นอยู่ใน schema อื่น · ด่านต้องปฏิเสธ เพราะสิ่งที่มันถามคือ
    "ปลายทาง*ที่สคริปต์นี้จะเขียน*พร้อมหรือยัง" ไม่ใช่ "ใน database นี้มีใครสักคน
    มีคอลัมน์ชื่อนี้ไหม"

    ถอดบรรทัดนั้นออก → `SELECT 1` ไปเจอแถวของ schema ปลอม → ด่านตอบว่าพร้อม →
    สคริปต์เดินต่อไปเขียนทับค่าจริง แล้ว INSERT audit ล้มทีหลัง (หรือแย่กว่านั้น
    คือได้ audit ที่ไม่มีเหตุผล) ทั้งที่ด่านมีไว้กันเรื่องนี้โดยเฉพาะ
    """
    await _plant_a_same_named_table_in_another_schema(db_session)
    await _drop_the_reason_column(db_session)

    with pytest.raises(PrecheckError, match="reason"):
        await mod._check_schema(db_session)
