"""DB-level constraint test ของ `poster_splits` (ADR-0024 D2 · A-D5 · INF-25) —
พิสูจน์ว่า `uq_poster_splits_child_poster` · `uq_poster_splits_parent_piece` ·
`ck_poster_splits_piece_no_min` ถูกบังคับจริงที่ชั้น DB ไม่ใช่แค่คอมเมนต์ในโมเดล

ทรงเดียวกับ `test_poster_publication_constraint.py` — ยิงตรงเข้า `db_session`
(ไม่ผ่าน `split_entry.py`) เพราะกฎข้อนี้ต้องเป็นด่านที่กันได้แม้มีคนเขียนเข้าตาราง
ตรง ๆ ไม่ผ่านสคริปต์เลยก็ตาม (AC-3 ของ INF-25 — "ด่านสคริปต์มีไว้ให้ error อ่านรู้เรื่อง
ไม่ใช่ตัวกันจริง")

🔴 **`uq_poster_splits_parent_reason` ถูกถอดไปแล้ว (ADR-0024 A-D5)** — เทสของ
constraint นั้นถูกแทนที่ทั้งหมดในไฟล์นี้ด้วยเทสของ `uq_poster_splits_parent_piece`
"""

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy import text
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
            piece_no=2,
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
            piece_no=3,
            reviewed_by="chanothai",
            reviewed_at=REVIEWED_AT,
            source="split-entry.csv",
            reason="รันซ้ำโดยไม่ตั้งใจ",
        )
    )

    with pytest.raises(IntegrityError, match="uq_poster_splits_child_poster"):
        await db_session.flush()


async def test_two_splits_with_the_same_parent_and_piece_no_raise_integrity_error(
    db_session: AsyncSession,
) -> None:
    """🔴 ตัวฆ่า mutation ของ `uq_poster_splits_parent_piece` (ADR-0024 A-D5 · INF-25) —
    DROP constraint นี้แล้วเทสนี้ต้องแดง

    ยิงตรงเข้า `db_session` ไม่ผ่าน `split_entry.py` เลย — พิสูจน์ว่าด่านชั้นสคริปต์
    (`plan_writes()` SKIP_PIECE_TAKEN) ไม่ใช่ด่านเดียว ต่อให้ใครเขียนเข้าตารางตรง ๆ
    ข้ามสคริปต์ไปเลย DB ก็ยังปฏิเสธ
    """
    parent = await _make_poster(db_session, "Parent")
    child_one = await _make_poster(db_session, "Child 1")
    child_two = await _make_poster(db_session, "Child 2")

    db_session.add(
        PosterSplit(
            child_poster_id=child_one.id,
            parent_poster_id=parent.id,
            piece_no=2,
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
            piece_no=2,  # ซ้ำ — ควรถูกปฏิเสธ แม้ reason จะไม่ซ้ำเลยก็ตาม
            reviewed_by="chanothai",
            reviewed_at=REVIEWED_AT,
            source="split-entry.csv",
            reason="เหตุผลคนละอย่างกันโดยสิ้นเชิง",
        )
    )

    with pytest.raises(IntegrityError, match="uq_poster_splits_parent_piece"):
        await db_session.flush()


async def test_a_piece_no_of_one_violates_the_check_constraint(
    db_session: AsyncSession,
) -> None:
    """🔴 ตัวฆ่า mutation ของ `ck_poster_splits_piece_no_min` — แถวพ่อเองคือชิ้นที่ 1
    (ADR-0019 D1) ค่า 0/1 จึงเป็นการบันทึกสิ่งที่ขัดกับ D1 ลงตารางตรง ๆ
    """
    parent = await _make_poster(db_session, "Parent")
    child = await _make_poster(db_session, "Child")

    db_session.add(
        PosterSplit(
            child_poster_id=child.id,
            parent_poster_id=parent.id,
            piece_no=1,
            reviewed_by="chanothai",
            reviewed_at=REVIEWED_AT,
            source="split-entry.csv",
            reason="ผิด — ชิ้นที่ 1 คือแถวพ่อเอง",
        )
    )

    with pytest.raises(IntegrityError, match="ck_poster_splits_piece_no_min"):
        await db_session.flush()


async def test_the_same_reason_text_with_a_different_piece_no_is_allowed(
    db_session: AsyncSession,
) -> None:
    """🔴 assertion เชิงลบตาม AC-1 — `reason` ที่ซ้ำเป๊ะแต่ `piece_no` ต่าง ต้อง insert
    ผ่าน (ถ้ายังไม่ผ่านแปลว่า `reason` ยังเป็นส่วนหนึ่งของคีย์อยู่ — A-D5 สั่งถอดออกแล้ว)
    """
    parent = await _make_poster(db_session, "Parent")
    child_one = await _make_poster(db_session, "Child 1")
    child_two = await _make_poster(db_session, "Child 2")

    db_session.add(
        PosterSplit(
            child_poster_id=child_one.id,
            parent_poster_id=parent.id,
            piece_no=2,
            reviewed_by="chanothai",
            reviewed_at=REVIEWED_AT,
            source="split-entry.csv",
            reason="เหตุผลเดียวกันเป๊ะ",
        )
    )
    db_session.add(
        PosterSplit(
            child_poster_id=child_two.id,
            parent_poster_id=parent.id,
            piece_no=3,
            reviewed_by="chanothai",
            reviewed_at=REVIEWED_AT,
            source="split-entry.csv",
            reason="เหตุผลเดียวกันเป๊ะ",  # ซ้ำ text 100% กับแถวบน
        )
    )

    await db_session.flush()  # ต้องไม่ raise


async def test_the_same_parent_can_be_split_more_than_once(
    db_session: AsyncSession,
) -> None:
    """ด้านที่ต้องไม่พัง — `parent_poster_id` ไม่ unique เพราะพ่อแตกได้หลายรอบ
    (คนละแถวลูกคนละแถว) ถ้า mutation ทำให้ constraint ไปจับ parent เดี่ยว ๆ
    เทสนี้ต้องแดง
    """
    parent = await _make_poster(db_session, "Parent")
    child_one = await _make_poster(db_session, "Child 1")
    child_two = await _make_poster(db_session, "Child 2")

    db_session.add(
        PosterSplit(
            child_poster_id=child_one.id,
            parent_poster_id=parent.id,
            piece_no=2,
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
            piece_no=3,
            reviewed_by="chanothai",
            reviewed_at=REVIEWED_AT,
            source="split-entry.csv",
            reason="ชิ้นที่สอง",
        )
    )

    await db_session.flush()  # ต้องไม่ raise


async def test_no_constraint_or_index_references_reason_anymore(
    db_session: AsyncSession,
) -> None:
    """🔴 AC-1 บังคับ — พิสูจน์ด้วย query จริงต่อ `pg_indexes`/`information_schema`
    (ทรงเดียวกับที่ AC-1 สั่ง `\\d poster_splits`) ไม่ใช่ assert จาก `__table_args__`
    ของ SQLAlchemy ซึ่งพิสูจน์ได้แค่ว่าโค้ด Python เขียนถูก ไม่ใช่ว่า DB จริงตรงกัน
    (คลาสเดียวกับที่ project-gotchas §3 เตือนเรื่อง constraint ที่ประกาศใน
    __table_args__ แล้วลืมใส่ migration)
    """
    # ทุก index/constraint ของ poster_splits ที่มีคอลัมน์ reason อยู่ในนิยาม
    rows = (
        await db_session.execute(
            text(
                "SELECT indexname, indexdef FROM pg_indexes "
                "WHERE tablename = 'poster_splits' AND indexdef ILIKE '%reason%'"
            )
        )
    ).all()
    assert rows == [], f"ยังมี index/constraint ที่อ้าง reason อยู่: {rows}"

    # ยืนยันเพิ่มว่า constraint กันรันซ้ำตัวใหม่ (piece_no) มีอยู่จริง — ถ้าไม่มีเลย
    # เทสข้างบนจะผ่านด้วยเหตุผลผิด (ไม่มี constraint อะไรเลยก็ไม่มีใครอ้าง reason)
    piece_constraint = (
        await db_session.execute(
            text(
                "SELECT conname FROM pg_constraint "
                "WHERE conrelid = 'poster_splits'::regclass "
                "AND conname = 'uq_poster_splits_parent_piece'"
            )
        )
    ).scalar_one_or_none()
    assert piece_constraint == "uq_poster_splits_parent_piece"
