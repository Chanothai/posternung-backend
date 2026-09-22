"""DB-level constraint test ของ `posters` (ADR-0027 D1 · Amendment 3 A3-D1) —
พิสูจน์ว่า CHECK `ck_posters_published_requires_verified` ถูกบังคับจริงที่ชั้น DB
ไม่ใช่แค่คอมเมนต์ในโมเดล หรือ guard ฝั่ง Python ที่ `poster_service.is_publishable()`

ต้องยิงตรงเข้า session (ไม่ผ่าน service) เพราะกฎข้อนี้จงใจอยู่ที่ระดับ DB —
`scripts/seed/*.py` เขียน `insert()`/`update()` เข้าตารางตรง ๆ ไม่ผ่าน
`poster_service` เลย (เหตุผลเดียวกับ `ck_posters_published_requires_condition_grade`
ทุกตัวอักษร) เทสที่เรียกผ่าน service จึงพิสูจน์ข้อนี้ไม่ได้

ทรงเดียวกับ `test_poster_sold_at_constraint.py` / `test_poster_publication_constraint.py`
— ถ้าใคร drop constraint ทิ้ง หรือถอด `OR status = 'sold'` ออกจากนิพจน์ เทสชุดนี้ต้อง
แดงทันที (AC-4 · AC-5 — mutation พิสูจน์แล้วด้วยมือ ดูรายงาน GATE)
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

CONSTRAINT = "ck_posters_published_requires_verified"
PUBLISHED_AT = datetime(2026, 1, 1, tzinfo=UTC)
VERIFIED_AT = datetime(2026, 1, 1, 6, 0, tzinfo=UTC)
SOLD_AT = datetime(2026, 2, 1, tzinfo=UTC)


async def test_insert_published_without_verified_raises_integrity_error(
    db_session: AsyncSession,
) -> None:
    """INSERT ใบที่ `status=available` (ไม่ใช่ `sold`) แต่ตั้ง `published_at` โดยไม่มี
    `verified_at` → ถูกปฏิเสธที่ระดับ DB (AC-4 เชิงลบ)
    """
    db_session.add(
        Poster(
            seller_id=HOUSE_SELLER_ID,
            approved_at=HOUSE_APPROVED_AT,
            title="Published but unverified",
            price=Decimal("100"),
            condition_grade=PosterCondition.very_good,
            status=PosterStatus.available,
            published_at=PUBLISHED_AT,
            verified_at=None,
        )
    )

    with pytest.raises(IntegrityError, match=CONSTRAINT):
        await db_session.flush()


async def test_update_removing_verified_from_published_poster_raises_integrity_error(
    db_session: AsyncSession,
) -> None:
    """UPDATE ล้าง `verified_at` ออกจากใบที่ publish อยู่แล้ว (ไม่ใช่ `sold`) → ถูก
    ปฏิเสธเช่นกัน

    🔴 เคสนี้คือเหตุผลที่กฎต้องอยู่ที่ DB ไม่ใช่แค่ guard ตอนเขียน `published_at` —
    guard ที่ตรวจตอน publish อย่างเดียวมองไม่เห็นการล้าง `verified_at` ทีหลังเลย
    (ADR-0027 D6 — แก้มิติที่ลายเซ็นรับรองต้องล้างลายเซ็นในธุรกรรมเดียวกัน ซึ่งถ้าลืม
    ล้าง `published_at` คู่กัน CHECK ตัวนี้ต้องดังแทนที่จะปล่อยแถวละเมิด invariant เงียบ ๆ)
    """
    poster = Poster(
        seller_id=HOUSE_SELLER_ID,
        approved_at=HOUSE_APPROVED_AT,
        title="Published then unsigned",
        price=Decimal("100"),
        condition_grade=PosterCondition.very_good,
        status=PosterStatus.available,
        published_at=PUBLISHED_AT,
        verified_at=VERIFIED_AT,
    )
    db_session.add(poster)
    await db_session.flush()

    # ใช้ Core UPDATE ตรง ๆ เลียนแบบเส้นทางของ seeder ที่ไม่ผ่าน ORM/service
    stmt = (
        update(Poster.__table__)
        .where(Poster.__table__.c.id == poster.id)
        .values(verified_at=None)
    )

    with pytest.raises(IntegrityError, match=CONSTRAINT):
        await db_session.execute(stmt)
        await db_session.flush()


async def test_sold_and_published_without_verified_is_accepted(
    db_session: AsyncSession,
) -> None:
    """AC-4 เชิงบวก — แถว `sold` + `published` + ไม่ `verified` ต้องผ่าน

    ล็อกข้อยกเว้นของ Amendment 3 (A3-D1) ไว้โดยตรง — ไม่ให้ implementation รอบหลัง
    เผลอตัดทิ้ง (เช่นมีคนพยายาม "แก้ให้ตรงกับ D1 เป๊ะ" โดยลบ `OR status = 'sold'` ออก
    เพราะดูเหมือนทำให้กฎแน่นขึ้น — ADR-0027 A3-D2 ห้ามไว้ตรง ๆ เพราะของที่ขายไปแล้ว
    ไม่มีใครหยิบขึ้นมาตรวจได้อีก การเซ็นย้อนหลังคือตรายาง)
    """
    poster = Poster(
        seller_id=HOUSE_SELLER_ID,
        approved_at=HOUSE_APPROVED_AT,
        title="Sold, published, never verified",
        price=Decimal("100"),
        condition_grade=PosterCondition.very_good,
        status=PosterStatus.sold,
        published_at=PUBLISHED_AT,
        verified_at=None,
        sold_at=SOLD_AT,
    )
    db_session.add(poster)

    await db_session.flush()  # ต้องไม่ raise

    assert poster.id is not None
    assert poster.verified_at is None


@pytest.mark.parametrize(
    ("status", "published_at", "verified_at", "sold_at", "label"),
    [
        (
            PosterStatus.available,
            PUBLISHED_AT,
            VERIFIED_AT,
            None,
            "available + published + verified",
        ),
        (PosterStatus.available, None, None, None, "available + unpublished"),
        (
            PosterStatus.reserved,
            PUBLISHED_AT,
            VERIFIED_AT,
            None,
            "reserved + published + verified",
        ),
        (
            PosterStatus.sold,
            PUBLISHED_AT,
            VERIFIED_AT,
            SOLD_AT,
            "sold + published + verified (ไม่ได้พึ่งข้อยกเว้นเลย)",
        ),
        (
            PosterStatus.sold,
            PUBLISHED_AT,
            None,
            SOLD_AT,
            "sold + published + unverified (ข้อยกเว้น A3-D1)",
        ),
    ],
)
async def test_legal_combinations_are_accepted(
    db_session: AsyncSession,
    status: PosterStatus,
    published_at: datetime | None,
    verified_at: datetime | None,
    sold_at: datetime | None,
    label: str,
) -> None:
    """ห้าคู่ที่เหลือต้องผ่านหมด — constraint ต้องกันเฉพาะคู่ที่ผิดกฎ ไม่ใช่กันกว้างไป"""
    poster = Poster(
        seller_id=HOUSE_SELLER_ID,
        approved_at=HOUSE_APPROVED_AT,
        title=f"Legal: {label}",
        price=Decimal("100"),
        condition_grade=PosterCondition.very_good,
        status=status,
        published_at=published_at,
        verified_at=verified_at,
        sold_at=sold_at,
    )
    db_session.add(poster)

    await db_session.flush()  # ต้องไม่ raise

    assert poster.id is not None
    assert poster.verified_at == verified_at
