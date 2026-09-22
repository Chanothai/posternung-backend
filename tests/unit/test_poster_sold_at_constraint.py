"""DB-level constraint test ของ `posters` (ADR-0025 D2) — พิสูจน์ว่า CHECK
`ck_posters_sold_requires_sold_at` ถูกบังคับจริงที่ชั้น DB ไม่ใช่แค่คอมเมนต์ในโมเดล

ต้องยิงตรงเข้า session (ไม่ผ่าน service) เพราะกฎข้อนี้จงใจอยู่ที่ระดับ DB —
`scripts/seed/seed_posters.py --status sold` เขียน `insert()` เข้าตารางตรง ๆ ไม่ผ่าน
`poster_service.mark_sold()` เลย (ADR-0025 D2 — เหตุผลตัวเดียวกับ ADR-0013 D3 ทุก
ตัวอักษร) เทสที่เรียกผ่าน service จึงพิสูจน์ข้อนี้ไม่ได้

ทรงเดียวกับ `test_poster_publication_constraint.py` ที่ล็อก
`ck_posters_published_requires_condition_grade` ไว้แล้ว — ถ้าใคร drop constraint
ทิ้ง เทสชุดนี้ต้องแดงทันที (AC-2)
"""

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy import update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import PosterCondition, PosterStatus
from app.models.poster import Poster
from tests.support import HOUSE_APPROVED_AT, HOUSE_SELLER_ID

CONSTRAINT = "ck_posters_sold_requires_sold_at"
SOLD_AT = datetime(2026, 2, 1, tzinfo=UTC)


async def test_insert_sold_without_sold_at_raises_integrity_error(
    db_session: AsyncSession,
) -> None:
    """INSERT ใบที่ `status=sold` แต่ไม่ตั้ง `sold_at` → ถูกปฏิเสธที่ระดับ DB

    เคสนี้คือสิ่งที่ AC-2 เรียกว่า "ไม่มีทางได้แถวที่ sold แต่ sold_at เป็น NULL"
    """
    db_session.add(
        Poster(
            seller_id=HOUSE_SELLER_ID,
            approved_at=HOUSE_APPROVED_AT,
            title="Sold without sold_at",
            price=Decimal("100"),
            status=PosterStatus.sold,
            condition_grade=PosterCondition.very_good,
            sold_at=None,
        )
    )

    with pytest.raises(IntegrityError, match=CONSTRAINT):
        await db_session.flush()


async def test_update_to_sold_without_sold_at_raises_integrity_error(
    db_session: AsyncSession,
) -> None:
    """UPDATE พลิก `status` เป็น `sold` เปล่า ๆ โดยไม่แตะ `sold_at` → ถูกปฏิเสธเช่นกัน

    🔴 นี่คือเคสที่พิสูจน์ว่ากฎต้องอยู่ที่ DB ไม่ใช่แค่ guard ตอน `mark_sold()` เขียน —
    guard ที่ชั้น service มองไม่เห็นเส้นทางที่เขียน `posters` ตรง (`seed_posters.py`)
    เลย (ADR-0025 D2 · §Verification ข้อ 2)
    """
    poster = Poster(
        seller_id=HOUSE_SELLER_ID,
        approved_at=HOUSE_APPROVED_AT,
        title="Available then sold",
        price=Decimal("100"),
        status=PosterStatus.available,
        condition_grade=PosterCondition.very_good,
    )
    db_session.add(poster)
    await db_session.flush()

    # ใช้ Core UPDATE ตรง ๆ เลียนแบบเส้นทางของ seeder ที่ไม่ผ่าน ORM/service
    stmt = (
        update(Poster.__table__)
        .where(Poster.__table__.c.id == poster.id)
        .values(status=PosterStatus.sold.value)
    )

    with pytest.raises(IntegrityError, match=CONSTRAINT):
        await db_session.execute(stmt)
        await db_session.flush()


@pytest.mark.parametrize(
    ("status", "sold_at", "label"),
    [
        (PosterStatus.sold, SOLD_AT, "sold + sold_at ตั้งแล้ว"),
        (PosterStatus.available, None, "available + sold_at ว่าง"),
        (PosterStatus.reserved, None, "reserved + sold_at ว่าง"),
    ],
)
async def test_legal_combinations_are_accepted(
    db_session: AsyncSession,
    status: PosterStatus,
    sold_at: datetime | None,
    label: str,
) -> None:
    """สามคู่ที่เหลือต้องผ่านหมด — constraint ต้องกันเฉพาะคู่ที่ผิดกฎ ไม่ใช่กันกว้างไป"""
    poster = Poster(
        seller_id=HOUSE_SELLER_ID,
        approved_at=HOUSE_APPROVED_AT,
        title=f"Legal: {label}",
        price=Decimal("100"),
        status=status,
        condition_grade=PosterCondition.very_good,
        sold_at=sold_at,
    )
    db_session.add(poster)

    await db_session.flush()  # ต้องไม่ raise

    assert poster.id is not None
    assert poster.sold_at == sold_at


async def test_sold_at_has_no_server_default(db_session: AsyncSession) -> None:
    """ADR-0025 D2/D4 — ไม่มี `server_default` · แถวใหม่ (`status=available`) ต้องเป็น
    NULL เสมอ ถ้ามีใครเผลอใส่ `server_default=func.now()` ในรอบหลัง จะเป็นการ
    ประดิษฐ์เวลาที่ของขายออกไปให้ทุกแถวที่ import เข้ามา ซึ่ง AC-8 ห้ามไว้ตรง ๆ
    """
    poster = Poster(
        seller_id=HOUSE_SELLER_ID,
        approved_at=HOUSE_APPROVED_AT,
        title="Fresh row",
        price=Decimal("100"),
    )
    db_session.add(poster)
    await db_session.flush()
    await db_session.refresh(poster)

    assert poster.sold_at is None
