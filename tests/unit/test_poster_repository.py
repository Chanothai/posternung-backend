"""Unit test ของ `poster_repository.get_for_update()` — พบจาก `code-critic` รอบ 1
ของ `/feature INF-24` (H1 · H2)

H1: `get_for_update()` ล็อกแถวจริง แต่ถ้าผู้เรียก session เดียวกันเคยโหลดแถวนั้นมาก่อน
(เช่น `sold_entry.py` เรียก `get_by_id()` เพื่อพรีวิวก่อนเรียก `mark_sold()`)
SQLAlchemy identity map จะคืน object เดิมโดยไม่ refresh attribute ให้ ทำให้
`mark_sold()` ตัดสินใจด้วยค่าก่อนล็อก ไม่ใช่ค่าหลังล็อก — `populate_existing=True`
คือตัวแก้ (ดู docstring ของ `get_for_update()`)

H2: `stock-integrity §Test บังคับ` — ต้อง verify ว่าใช้ `FOR UPDATE` จริง ไม่ใช่แค่
เช็ค `if` เทสระดับ source เพราะเทส concurrency เต็มรูป (สอง request ยิงพร้อมกันผ่าน
HTTP) เป็นของ `SCR-06` ที่ยังไม่มี endpoint ให้ยิงในรอบนี้
"""

from __future__ import annotations

import ast
import inspect
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import PosterCondition, PosterStatus
from app.models.poster import Poster
from tests.support import HOUSE_APPROVED_AT, HOUSE_SELLER_ID
from app.repositories import poster_repository

PUBLISHED_AT = datetime(2026, 1, 1, tzinfo=UTC)
# ck_posters_published_requires_verified (ADR-0027 A3-D1 · INF-38) — ต่างจาก
# PUBLISHED_AT โดยตั้งใจ
VERIFIED_AT = datetime(2026, 1, 1, 6, 0, tzinfo=UTC)


async def _make_available_poster(session: AsyncSession) -> Poster:
    poster = Poster(
        seller_id=HOUSE_SELLER_ID,
        approved_at=HOUSE_APPROVED_AT,
        title="Repository test",
        price=Decimal("100"),
        status=PosterStatus.available,
        condition_grade=PosterCondition.very_good,
        published_at=PUBLISHED_AT,
        verified_at=VERIFIED_AT,
    )
    session.add(poster)
    await session.flush()
    return poster


async def test_get_for_update_uses_with_for_update() -> None:
    """H2 — เทสระดับ source: ถอด `.with_for_update()` ออกจากฟังก์ชันนี้เมื่อไหร่
    เทสนี้ต้องแดง (ยืนยันแล้วด้วยมือ — ดูรายงาน GATE)
    """
    tree = ast.parse(inspect.getsource(poster_repository.get_for_update))
    called_methods = {
        node.func.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }
    assert "with_for_update" in called_methods


async def test_get_for_update_sees_fresh_value_even_if_object_already_loaded(
    db_session: AsyncSession,
) -> None:
    """H1 — จำลองสภาพที่ `sold_entry.py` ทำอยู่ทุกครั้ง: โหลดแถวมาก่อนหนึ่งครั้ง
    (`get_by_id()`) แล้วมีคนอื่นเปลี่ยนค่าจริงใน DB (จำลองด้วย Core UPDATE ตรง —
    เลียนแบบเส้นทางที่ไม่ผ่าน ORM identity map เดียวกับที่
    `test_poster_sold_at_constraint.py` ใช้) แล้วค่อยเรียก `get_for_update()` ใน
    session เดียวกัน — ต้องเห็นค่าล่าสุดจาก DB ไม่ใช่ค่าที่ cache ไว้ตั้งแต่ตอนโหลดครั้งแรก

    🔴 ถ้าถอด `populate_existing=True` ออก เทสนี้ต้องแดง (ยืนยันแล้วด้วยมือ — ดูรายงาน
    GATE): `locked` จะเป็น object เดิมจาก identity map และ `.status` จะยังเป็น
    `available` ทั้งที่ DB จริงเป็น `sold` ไปแล้ว
    """
    poster = await _make_available_poster(db_session)

    # จำลอง "อีก process หนึ่งเปลี่ยนค่าไปแล้ว" โดยไม่ผ่าน ORM ของ object ที่โหลดไว้ —
    # ทำให้ poster (object ที่ค้างใน identity map) ไม่รู้จักค่าที่เพิ่งเปลี่ยน
    sold_at = datetime(2026, 2, 1, tzinfo=UTC)
    await db_session.execute(
        update(Poster.__table__)
        .where(Poster.__table__.c.id == poster.id)
        .values(status=PosterStatus.sold.value, sold_at=sold_at)
    )

    locked = await poster_repository.get_for_update(db_session, poster.id)

    assert locked is poster  # ยืนยันว่าเจอ identity-map hit จริง (object เดิม)
    assert locked.status == PosterStatus.sold
    assert locked.sold_at == sold_at


async def test_get_for_update_returns_none_for_missing_poster(
    db_session: AsyncSession,
) -> None:
    import uuid

    assert await poster_repository.get_for_update(db_session, uuid.uuid4()) is None
