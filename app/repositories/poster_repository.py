"""Poster table access — thin DB layer (ไม่มี business logic)."""

import uuid
from collections.abc import Sequence
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.enums import PosterCondition, PosterStatus
from app.models.poster import Poster


def graded_only(stmt):
    """ตัดโปสเตอร์ที่ยังไม่มี `condition_grade` ออกจากทุก query ของหน้าร้าน

    🔴 **ไม่ใช่ filter ที่ผู้ใช้เลือกได้** — เป็นข้อบังคับของ BR-05 ที่ว่าทุกที่ที่แสดง
    ราคาต้องแสดงสภาพคู่กันเสมอ · โปสเตอร์ที่ไม่มีเกรดจึงไม่มีทางแสดงให้ถูกกฎได้เลย
    ทางเดียวที่เหลือคือไม่แสดง

    ทำไมอยู่ที่ชั้น repository ทั้งที่เป็น business rule: `list_with_filters()` นับ
    `total` และตัดหน้าด้วย `LIMIT/OFFSET` ใน SQL — ถ้ากรองทีหลังที่ชั้น service
    จำนวนต่อหน้าจะไม่เท่ากันและ `total` จะโกหก · คู่ Python ของ predicate เดียวกันนี้
    คือ `poster_service.is_publishable()` และมีเทสล็อกว่าสองตัวต้องตอบตรงกัน

    ที่มาของกฎ: ADR-0003 §ช่องโหว่ที่ต้องปิด (`condition_grade` เป็น NULL ได้) ซึ่ง
    ADR-0005 §ต้องทำตามมา บันทึกไว้ว่า "ยังไม่มีโค้ดบังคับ" · เลือกกรองแทนการแก้
    `status` เพราะ `poster_status` ไม่มีค่าที่แปลว่า "ยังไม่พร้อมขาย"
    (available/reserved/sold เท่านั้น) การเขียนค่าใดค่าหนึ่งลงไปคือการโกหกสถานะสต็อก
    — สถานะ "ยังไม่ publish" เป็นการตัดสินใจที่ ADR-0009 §ต้องทำตามมา ยังค้างอยู่
    """
    return stmt.where(Poster.condition_grade.isnot(None))


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

    count_stmt = graded_only(_apply_filters(select(func.count(Poster.id)), **filters))
    total = (await session.execute(count_stmt)).scalar_one()

    list_stmt = graded_only(_apply_filters(select(Poster), **filters))
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
