"""DB-level constraint test ของ `poster_splits` (ADR-0024 D2) — พิสูจน์ว่า
`uq_poster_splits_child_poster` ถูกบังคับจริงที่ชั้น DB ไม่ใช่แค่คอมเมนต์ในโมเดล

ทรงเดียวกับ `test_poster_publication_constraint.py` — ยิงตรงเข้า `db_session`
(ไม่ผ่าน `split_entry.py`) เพราะกฎข้อนี้ต้องเป็นด่านที่กันได้แม้มีคนเขียนเข้าตาราง
ตรง ๆ ไม่ผ่านสคริปต์เลยก็ตาม (ADR-0024 D2 ข้อ 3 — "ด่านจริงระดับ DB ไม่ใช่ระดับสคริปต์")
"""

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import PosterCondition
from app.models.poster import Poster
from app.models.poster_split import PosterSplit

REVIEWED_AT = datetime(2026, 8, 12, 10, 0, tzinfo=UTC)


async def _make_poster(session: AsyncSession, title: str) -> Poster:
    poster = Poster(
        title=title, price=Decimal("500"), condition_grade=PosterCondition.very_good
    )
    session.add(poster)
    await session.flush()
    return poster


async def test_two_splits_pointing_at_the_same_child_raise_integrity_error(
    db_session: AsyncSession,
) -> None:
    """🔴 ตัวฆ่า mutation หลัก — DROP `uq_poster_splits_child_poster` แล้วเทสนี้ต้องแดง"""
    parent = await _make_poster(db_session, "Parent")
    child = await _make_poster(db_session, "Child")

    db_session.add(
        PosterSplit(
            child_poster_id=child.id,
            parent_poster_id=parent.id,
            reviewed_by="chanothai",
            reviewed_at=REVIEWED_AT,
            source="split-entry.csv",
            reason="แรก",
        )
    )
    await db_session.flush()

    db_session.add(
        PosterSplit(
            child_poster_id=child.id,  # ซ้ำ — ควรถูกปฏิเสธ
            parent_poster_id=parent.id,
            reviewed_by="chanothai",
            reviewed_at=REVIEWED_AT,
            source="split-entry.csv",
            reason="รันซ้ำโดยไม่ตั้งใจ",
        )
    )

    with pytest.raises(IntegrityError, match="uq_poster_splits_child_poster"):
        await db_session.flush()


async def test_two_splits_with_the_same_parent_and_reason_raise_integrity_error(
    db_session: AsyncSession,
) -> None:
    """🔴 ตัวฆ่า mutation ของ `uq_poster_splits_parent_reason` (code-critic รอบ 4) —
    DROP constraint นี้แล้วเทสนี้ต้องแดง

    ยิงตรงเข้า `db_session` ไม่ผ่าน `split_entry.py` เลย — พิสูจน์ว่าด่าน layer 2
    ของสคริปต์ (`plan_writes()` BLOCKED_ALREADY_SPLIT) ไม่ใช่ด่านเดียว ต่อให้ใครเขียน
    เข้าตารางตรง ๆ ข้ามสคริปต์ไปเลย DB ก็ยังปฏิเสธ (หลักเดียวกับ docstring ของไฟล์นี้)
    """
    parent = await _make_poster(db_session, "Parent")
    child_one = await _make_poster(db_session, "Child 1")
    child_two = await _make_poster(db_session, "Child 2")

    db_session.add(
        PosterSplit(
            child_poster_id=child_one.id,
            parent_poster_id=parent.id,
            reviewed_by="chanothai",
            reviewed_at=REVIEWED_AT,
            source="split-entry.csv",
            reason="แยกใบที่สองออกมาเพราะต่างเกรดกัน",
        )
    )
    await db_session.flush()

    db_session.add(
        PosterSplit(
            child_poster_id=child_two.id,
            parent_poster_id=parent.id,
            reviewed_by="chanothai",
            reviewed_at=REVIEWED_AT,
            source="split-entry.csv",
            reason="แยกใบที่สองออกมาเพราะต่างเกรดกัน",  # ซ้ำเป๊ะ — ควรถูกปฏิเสธ
        )
    )

    with pytest.raises(IntegrityError, match="uq_poster_splits_parent_reason"):
        await db_session.flush()


async def test_the_same_parent_can_be_split_more_than_once(
    db_session: AsyncSession,
) -> None:
    """ด้านที่ต้องไม่พัง — `parent_poster_id` ไม่ unique เพราะพ่อแตกได้หลายรอบ
    (คนละแถวลูกคนละแถว) ถ้า mutation ทำให้ constraint ไปจับ parent แทน child
    เทสนี้ต้องแดง
    """
    parent = await _make_poster(db_session, "Parent")
    child_one = await _make_poster(db_session, "Child 1")
    child_two = await _make_poster(db_session, "Child 2")

    db_session.add(
        PosterSplit(
            child_poster_id=child_one.id,
            parent_poster_id=parent.id,
            reviewed_by="chanothai",
            reviewed_at=REVIEWED_AT,
            source="split-entry.csv",
            reason="ชิ้นแรก",
        )
    )
    db_session.add(
        PosterSplit(
            child_poster_id=child_two.id,
            parent_poster_id=parent.id,
            reviewed_by="chanothai",
            reviewed_at=REVIEWED_AT,
            source="split-entry.csv",
            reason="ชิ้นที่สอง",
        )
    )

    await db_session.flush()  # ต้องไม่ raise
