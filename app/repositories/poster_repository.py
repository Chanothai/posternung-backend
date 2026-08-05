"""Poster table access — thin DB layer (ไม่มี business logic)."""

import uuid
from collections.abc import Sequence
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.enums import PosterCondition, PosterStatus
from app.models.poster import Poster


def published_only(stmt):
    """เหลือเฉพาะใบที่มีคนกดเปิดขายแล้วในทุก query ของหน้าร้าน (ADR-0013 D2)

    🔴 **ไม่ใช่ filter ที่ผู้ใช้เลือกได้** — `published_at` คือแกน "ความพร้อมขาย"
    ที่แยกจาก `status` (แกนวงจรสต็อก) ตาม ADR-0013 D1 · ใบที่ยังไม่ publish คือใบที่
    มีของอยู่ในมือแต่ยังไม่ตั้งวางบนชั้น จึงต้องไม่ปรากฏต่อลูกค้าเลย

    **แทนที่ `graded_only()` ของ PR #44 ไม่ใช่ซ้อนทับ** — CHECK ระดับ DB
    `ck_posters_published_requires_condition_grade` ทำให้
    `published_at IS NOT NULL ⇒ condition_grade IS NOT NULL` เป็นจริงเสมอ
    การเติม `AND condition_grade IS NOT NULL` จึงกันอะไรไม่ได้เพิ่มแม้แต่แถวเดียว
    แต่ทำให้อ่านโค้ดแล้วแยกไม่ออกว่ากฎตัวไหนบังคับจริง (ADR-0013 D2 · Alt-4)
    ชั้นที่สองของกฎ BR-05 คือเทสที่ยิงตรงเข้า constraint
    (`tests/unit/test_poster_publication_constraint.py`) ไม่ใช่ `WHERE` ซ้ำ

    ทำไมอยู่ที่ชั้น repository ทั้งที่เป็น business rule: `list_with_filters()` นับ
    `total` และตัดหน้าด้วย `LIMIT/OFFSET` ใน SQL — ถ้ากรองทีหลังที่ชั้น service
    จำนวนต่อหน้าจะไม่เท่ากันและ `total` จะโกหก · คู่ Python ของ predicate เดียวกันนี้
    คือ `poster_service.is_published()` และมีเทสล็อกว่าสองตัวต้องตอบตรงกัน
    """
    return stmt.where(Poster.published_at.isnot(None))


def _apply_filters(
    stmt,
    *,
    era_decade: int | None,
    condition_grade: PosterCondition | None,
    min_price: Decimal | None,
    max_price: Decimal | None,
    in_stock_only: bool,
):
    if era_decade is not None:
        stmt = stmt.where(Poster.era_decade == era_decade)
    if condition_grade is not None:
        stmt = stmt.where(Poster.condition_grade == condition_grade)
    if min_price is not None:
        stmt = stmt.where(Poster.price >= min_price)
    if max_price is not None:
        stmt = stmt.where(Poster.price <= max_price)
    if in_stock_only:
        stmt = stmt.where(Poster.status == PosterStatus.available)
    return stmt


async def list_with_filters(
    session: AsyncSession,
    *,
    era_decade: int | None,
    condition_grade: PosterCondition | None,
    min_price: Decimal | None,
    max_price: Decimal | None,
    in_stock_only: bool,
    limit: int,
    offset: int,
) -> tuple[Sequence[Poster], int]:
    filters = {
        "era_decade": era_decade,
        "condition_grade": condition_grade,
        "min_price": min_price,
        "max_price": max_price,
        "in_stock_only": in_stock_only,
    }

    count_stmt = published_only(
        _apply_filters(select(func.count(Poster.id)), **filters)
    )
    total = (await session.execute(count_stmt)).scalar_one()

    list_stmt = published_only(_apply_filters(select(Poster), **filters))
    list_stmt = (
        list_stmt.options(selectinload(Poster.images))
        .order_by(Poster.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    posters = (await session.execute(list_stmt)).scalars().all()

    return posters, total


async def get_by_id(session: AsyncSession, poster_id: uuid.UUID) -> Poster | None:
    stmt = (
        select(Poster)
        .options(selectinload(Poster.images))
        .where(Poster.id == poster_id)
    )
    result = await session.execute(stmt)
    return result.scalar_one_or_none()
