"""DB-level constraint test ของ `posters` (ADR-0013 D3) — พิสูจน์ว่า CHECK
`ck_posters_published_requires_condition_grade` ถูกบังคับจริงที่ชั้น DB ไม่ใช่แค่
คอมเมนต์ในโมเดล

ต้องยิงตรงเข้า session (ไม่ผ่าน service) เพราะกฎข้อนี้จงใจอยู่ที่ระดับ DB —
`scripts/seed/seed_posters.py` เขียน `insert()`/`update()` เข้าตารางตรง ๆ ไม่ผ่าน
`poster_service` เลย (ADR-0013 D3) เทสที่เรียกผ่าน service จึงพิสูจน์ข้อนี้ไม่ได้

ทรงเดียวกับ `test_poster_image_constraints.py` ที่ล็อก constraint ของ `poster_images`
ไว้แล้ว · ตามที่ ADR-0013 D2 เขียนไว้ เทสชุดนี้ **คือ** ชั้นที่สองของกฎ BR-05
(แทนที่การเขียน `WHERE condition_grade IS NOT NULL` ซ้ำในหน้าร้าน) — ถ้าใคร drop
constraint ทิ้ง เทสชุดนี้ต้องแดงทันที
"""

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy import update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import PosterCondition
from app.models.poster import Poster
from tests.support import HOUSE_APPROVED_AT, HOUSE_SELLER_ID

CONSTRAINT = "ck_posters_published_requires_condition_grade"
PUBLISHED_AT = datetime(2026, 1, 1, tzinfo=UTC)
# ck_posters_published_requires_verified (ADR-0027 A3-D1 · INF-38) — เทสไฟล์นี้ล็อก
# เฉพาะ CONSTRAINT ของเกรดข้างบน ⇒ ทุกแถวข้างล่างต้องมี verified_at ด้วย ไม่งั้น
# constraint ใหม่จะแทรกมาทำให้ปฏิเสธ "ผิดเหตุผล" (constraint คนละตัวกับที่เทสอ้าง)
VERIFIED_AT = datetime(2026, 1, 1, 6, 0, tzinfo=UTC)


async def test_insert_published_without_grade_raises_integrity_error(
    db_session: AsyncSession,
) -> None:
    """INSERT ใบที่ไม่มีเกรดแต่ตั้ง published_at → ถูกปฏิเสธที่ระดับ DB

    `verified_at` ตั้งไว้ตรงนี้เพื่อให้แถวนี้ละเมิด **เฉพาะ** CONSTRAINT ของเกรด —
    ไม่งั้นจะชน `ck_posters_published_requires_verified` (INF-38) ไปพร้อมกันด้วย
    ซึ่งไม่ใช่สิ่งที่เทสนี้ตั้งใจพิสูจน์ (ดู `test_poster_verified_constraint.py`)
    """
    db_session.add(
        Poster(
            seller_id=HOUSE_SELLER_ID,
            approved_at=HOUSE_APPROVED_AT,
            title="Ungraded but published",
            price=Decimal("100"),
            condition_grade=None,
            published_at=PUBLISHED_AT,
            verified_at=VERIFIED_AT,
        )
    )

    with pytest.raises(IntegrityError, match=CONSTRAINT):
        await db_session.flush()


async def test_update_removing_grade_from_published_poster_raises_integrity_error(
    db_session: AsyncSession,
) -> None:
    """UPDATE ลบเกรดออกจากใบที่ publish ไปแล้ว → ถูกปฏิเสธเช่นกัน

    🔴 เคสนี้คือเหตุผลที่กฎต้องอยู่ที่ DB ไม่ใช่แค่ guard ตอน publish —
    guard ที่ตรวจตอนเขียน `published_at` อย่างเดียวมองไม่เห็นการแก้ `condition_grade`
    ทีหลังเลย (ADR-0013 D3 · §Verification ข้อ 1)
    """
    poster = Poster(
        seller_id=HOUSE_SELLER_ID,
        approved_at=HOUSE_APPROVED_AT,
        title="Published then ungraded",
        price=Decimal("100"),
        condition_grade=PosterCondition.very_good,
        published_at=PUBLISHED_AT,
        verified_at=VERIFIED_AT,
    )
    db_session.add(poster)
    await db_session.flush()

    # ใช้ Core UPDATE ตรง ๆ เลียนแบบเส้นทางของ seeder ที่ไม่ผ่าน ORM/service
    stmt = (
        update(Poster.__table__)
        .where(Poster.__table__.c.id == poster.id)
        .values(condition_grade=None)
    )

    with pytest.raises(IntegrityError, match=CONSTRAINT):
        await db_session.execute(stmt)
        await db_session.flush()


@pytest.mark.parametrize(
    ("condition_grade", "published_at", "verified_at", "label"),
    [
        # 🔴 ‹INF-38› คู่นี้ "graded + published" อยู่เดิม **ประกาศตัวเองว่าถูกกฎ**
        # โดยไม่มี verified_at — ไม่จริงอีกต่อไปหลัง ck_posters_published_requires_verified
        # (ADR-0027 A3-D1) ⇒ ต้องเติม verified_at เข้ามาด้วยถึงจะยังเป็นคู่ที่ถูกกฎ
        (
            PosterCondition.very_good,
            PUBLISHED_AT,
            VERIFIED_AT,
            "graded + published + verified",
        ),
        (PosterCondition.very_good, None, None, "graded + unpublished"),
        (None, None, None, "ungraded + unpublished"),
    ],
)
async def test_legal_combinations_are_accepted(
    db_session: AsyncSession,
    condition_grade: PosterCondition | None,
    published_at: datetime | None,
    verified_at: datetime | None,
    label: str,
) -> None:
    """สี่คู่ที่เหลือต้องผ่านหมด — constraint ต้องกันเฉพาะคู่ที่ผิดกฎ ไม่ใช่กันกว้างไป

    ถ้าเทสนี้แดง แปลว่านิพจน์ของ CHECK เข้มเกินและจะบล็อกงานปกติ เช่น การเก็บของ
    ที่ยังไม่ให้เกรด (117 แถวของ dev DB วันนี้คือคู่ที่สาม)
    """
    poster = Poster(
        seller_id=HOUSE_SELLER_ID,
        approved_at=HOUSE_APPROVED_AT,
        title=f"Legal: {label}",
        price=Decimal("100"),
        condition_grade=condition_grade,
        published_at=published_at,
        verified_at=verified_at,
    )
    db_session.add(poster)

    await db_session.flush()  # ต้องไม่ raise

    assert poster.id is not None
    assert poster.published_at == published_at


async def test_published_at_has_no_server_default(db_session: AsyncSession) -> None:
    """ADR-0013 D1 — ไม่มี `server_default` · แถวใหม่ต้องเป็น NULL เสมอ

    ถ้ามีใครเผลอใส่ `server_default=func.now()` ในรอบหลัง โปสเตอร์ทุกใบที่ import
    เข้ามาจะขึ้นหน้าร้านทันทีโดยไม่มีคนกดเปิดขาย ซึ่งเป็นสิ่งที่ D4 ห้ามไว้
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

    assert poster.published_at is None
