"""harness ระดับ `run()` ตัวแรกของเส้นที่ 3 — INF-30 (ปิด `known_gap` G1 ของ INF-27)

🔴 **ทำไมไฟล์นี้ต้องมี** — `tests/unit/test_manual_entry.py` มี 104 เทสและ
**ไม่มีตัวไหนเรียก `run()` เลยสักตัว** ทั้งที่เส้นที่ 3 เป็นเส้นที่เขียน `published_at`
ของทั้งร้าน · ผลที่วัดได้: mutation ที่ **ตัด `plan_writes()` ออกจาก `run()`** ทั้งก้อน
**รอด 1062 passed · 1 skipped (100%)** เมื่อ 2026-08-16 ก่อนไฟล์นี้เกิด

เทสเดิมทุกตัวยิงที่ `plan_writes()` ซึ่งเป็น pure ⇒ พิสูจน์ได้แค่ว่า *ตรรกะของด่านถูก*
ไม่ได้พิสูจน์ว่า **ด่านถูกต่อเข้าสายจริง** · นี่คือบทเรียนเดียวกับที่ `INF-21` G5 และ
`INF-22` G1 จ่ายไปแล้วสองครั้ง และเป็นเหตุผลที่ `INF-25` AC-8 เขียนกฎไว้ว่า
*"จุดต่อของด่านใหม่ทุกตัวต้องมีเทสที่วิ่งผ่าน `main()`/`run()` จริง"*

## สิ่งที่ไฟล์นี้ทำ และไม่ทำ

- ✅ เรียก **`run()` ตัวจริง** ด้วยไฟล์ CSV จริงใน `tmp_path` และ `db_session` จริง
- ✅ assert ที่ **ผลลัพธ์ใน DB** (`published_at` · แถว `poster_attribute_reviews`)
  ไม่ใช่ที่ข้อความรายงาน — *"รายงานถูก"* กับ *"เขียนจริง"* เป็นคนละเรื่อง และเป็นรูป
  ที่เทสเดิมพิสูจน์ไม่ได้เลย
- ✅ ครอบทั้ง **dry-run** และ **`--commit`** เพราะสองโหมดเดินคนละสาขาใน `run()`
- ✅ ตรวจ **exit code** ทุกตัว — `0`/`1` มีความหมายกับคนที่รันจริงและกับ runbook ของ sit
- ❌ **ไม่แตะตรรกะของเส้นที่ 3 แม้บรรทัดเดียว** (INF-30 AC-5) — `scripts/seed/manual_entry.py`
  ต้องไม่ปรากฏใน `git diff --stat` ของใบนี้

⚠️ **ข้อจำกัดที่ต้องรู้ ไม่ใช่ข้อแก้ตัว:** harness ประกอบ `argparse.Namespace` เอง จึง
**ไม่ครอบชั้น argparse ของ `main()`** (ค่า default · `choices` · ด่านบังคับของ `--commit`)
· ชั้นนั้นเป็นคนละจุดต่อและยังไม่มีเทส — ทรงเดียวกับที่ `INF-21` §G1 เคยเปิดไว้เป็น gap
แยกของตัวเอง · **ห้ามอ่านไฟล์นี้ว่าเส้นที่ 3 มีเทสระดับ CLI แล้ว**
"""

from __future__ import annotations

import argparse
import csv
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import PosterCondition, PosterImageKind
from app.models.poster import Poster, PosterImage
from app.models.poster_attribute_review import PosterAttributeReview
from tests.support import HOUSE_APPROVED_AT, HOUSE_SELLER_ID
from scripts.seed.manual_entry import MANUAL_SHEET_COLUMNS, run

REVIEWED_AT = datetime(2026, 8, 16, 9, 0, tzinfo=UTC)
REVIEWED_BY = "chanothai.d"
# เวลาที่ "คนเซ็นรับว่าตรวจใบจริงแล้ว" — ADR-0027 D1 · ค่าคงที่ ไม่ใช่ now()
VERIFIED_AT = datetime(2026, 8, 15, 10, 0, tzinfo=UTC)


class _SessionHandle:
    """ตัวแทน `async_session_maker()` ที่คืน **session ของเทส** แทนการเปิดใหม่

    `run()` เขียนว่า `async with async_session_maker() as session:` — ตัวนี้จึงต้องเป็น
    async context manager · **ไม่ปิด session ตอนออก** เพราะ `db_session` ของ
    `conftest.py` เป็นเจ้าของวงจรชีวิตเอง (ครอบ transaction แล้ว rollback ท้ายเทส)

    🔴 นี่คือ **จุดเดียว** ที่ harness แทนของจริง — ทุกอย่างที่เหลือใน `run()` เป็นของจริง
    ทั้งหมด รวม `_check_schema()` · `_load_state()` · `plan_writes()` · `_column_counts()`
    · `session.commit()` (ซึ่งเป็น savepoint ตาม `join_transaction_mode` ของ fixture)
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def __aenter__(self) -> AsyncSession:
        return self._session

    async def __aexit__(self, *exc: object) -> bool:
        return False


@pytest.fixture
def use_test_session(monkeypatch: pytest.MonkeyPatch, db_session: AsyncSession) -> None:
    import app.core.database as db_mod

    monkeypatch.setattr(
        db_mod, "async_session_maker", lambda: _SessionHandle(db_session)
    )


def _sheet(tmp_path: Path, rows: list[dict[str, Any]]) -> Path:
    """เขียนใบงานจริงลงดิสก์ — `run()` อ่านไฟล์นี้ด้วย `read_manual_sheet()` ตัวจริง"""
    path = tmp_path / "manual-entry.csv"
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(MANUAL_SHEET_COLUMNS))
        writer.writeheader()
        for row in rows:
            writer.writerow({col: row.get(col, "") for col in MANUAL_SHEET_COLUMNS})
    return path


def _args(path: Path, *, commit: bool) -> argparse.Namespace:
    return argparse.Namespace(
        file=path,
        allow_overwrite=[],
        commit=commit,
        reviewed_by=REVIEWED_BY,
        reviewed_at=REVIEWED_AT,
    )


async def _make_poster(
    session: AsyncSession,
    *,
    condition_grade: PosterCondition | None = PosterCondition.very_good,
    image_kind: PosterImageKind | None = PosterImageKind.FRONT,
    verified_at: datetime | None = VERIFIED_AT,
) -> Poster:
    """ใบที่ **ยังไม่ publish** — เส้นที่ 3 เป็นเส้นเดียวที่เปิดขายได้ จึงต้องเริ่มจาก NULL

    ‹2026-08-16 · INF-28› `verified_at` ปริยาย = **มีลายเซ็นแล้ว** ซึ่งเป็นสภาพปกติของ
    production หลัง ADR-0027 D1 · ถ้าปล่อยเป็น `NULL` จะไม่มีเทสไหนในไฟล์นี้เดินถึง
    เส้นทางเขียนจริงเลยสักตัว (test-quality §6) · เทสของด่านนั้นส่ง `None` เองให้เห็นชัด
    """
    poster = Poster(
        seller_id=HOUSE_SELLER_ID,
        approved_at=HOUSE_APPROVED_AT,
        title=f"Harness {uuid.uuid4()}",
        price=Decimal("500"),
        condition_grade=condition_grade,
        verified_at=verified_at,
    )
    session.add(poster)
    await session.flush()
    if image_kind is not None:
        # แถบ `sort_order` ต่อชนิด — ADR-0026 D5 · `server_default="0"` ใช้ได้เฉพาะ
        # `FRONT` เท่านั้น แถว BACK/DEFECT ที่ไม่ระบุจะชน `ck_poster_images_sort_order_band`
        # ซึ่งเป็นพฤติกรรมที่ถูกต้องของ constraint ไม่ใช่ปัญหาของ harness
        band = {
            PosterImageKind.FRONT: 0,
            PosterImageKind.BACK: 100,
            PosterImageKind.DEFECT: 200,
        }[image_kind]
        session.add(
            PosterImage(
                poster_id=poster.id,
                storage_key=f"posters/public/{poster.id}/{band:02d}-{image_kind.value.lower()}.jpg",
                kind=image_kind,
                sort_order=band,
                is_primary=image_kind is PosterImageKind.FRONT,
            )
        )
        await session.flush()
    return poster


async def _published_at(session: AsyncSession, poster_id: uuid.UUID) -> datetime | None:
    return await session.scalar(
        select(Poster.published_at).where(Poster.id == poster_id)
    )


async def _audit_fields(session: AsyncSession, poster_id: uuid.UUID) -> list[str]:
    rows = await session.execute(
        select(PosterAttributeReview.field).where(
            PosterAttributeReview.poster_id == poster_id
        )
    )
    return sorted(rows.scalars().all())


def _publish_row(poster: Poster, **over: Any) -> dict[str, Any]:
    """แถวใบงานที่ **ผ่านทุกด่าน** — เทสของแต่ละด่านพังมันทีละข้อ

    ค่าปริยายเป็นสภาพปกติของ production (test-quality §6) ไม่ใช่สภาพที่ทุกอย่างว่าง
    ไม่งั้นจะไม่มีเทสไหนเดินผ่านเส้นทางเขียนจริงเลยสักตัว
    """
    row: dict[str, Any] = {
        "poster_uuid": str(poster.id),
        "count_actual": "1",
        "publish": "Y",
    }
    row.update(over)
    return row


# --------------------------------------------------------------------------
# ทางที่สำเร็จ — ตัวที่ทำให้ mutation "ตัด plan_writes ออกจาก run()" ตาย
# --------------------------------------------------------------------------


async def test_commit_writes_published_at_and_the_audit_row_into_the_database(
    db_session: AsyncSession, tmp_path: Path, use_test_session: None
) -> None:
    """🔴 positive control ของทั้งไฟล์ และเป็นตัวหลักที่ฆ่า mutation ของ AC-1

    ถ้าไม่มีตัวนี้ ชุดข้างล่างเขียวได้ด้วย `run()` ที่ **ปฏิเสธทุกกรณี** — ซึ่งเป็น
    รูปเดียวกับ mutation ที่ตัด `plan_writes()` ทิ้งพอดี (ไม่มีแผน = ไม่เขียนอะไรเลย)

    assert ที่ DB ไม่ใช่ที่รายงาน: `published_at` ต้องเป็น **เวลาที่คนตัดสินใจ**
    (`--reviewed-at`) ไม่ใช่เวลาที่สคริปต์รัน (ADR-0015 D4 · หลักเดียวกับ ADR-0010 D5)
    """
    poster = await _make_poster(db_session)
    path = _sheet(tmp_path, [_publish_row(poster)])

    rc = await run(_args(path, commit=True), "test")

    assert rc == 0
    assert await _published_at(db_session, poster.id) == REVIEWED_AT
    assert await _audit_fields(db_session, poster.id) == ["published_at"]


async def test_dry_run_touches_nothing_in_the_database(
    db_session: AsyncSession, tmp_path: Path, use_test_session: None
) -> None:
    """โหมด dry-run เดินคนละสาขาใน `run()` — ต้องพิสูจน์แยก (AC-2)

    ใบงานเดียวกับเทสข้างบนเป๊ะ ต่างกันแค่ `--commit` ⇒ ความต่างของผลลัพธ์เป็นของ
    แฟล็กนั้นตัวเดียว ไม่ใช่ของอย่างอื่นที่บังเอิญต่าง
    """
    poster = await _make_poster(db_session)
    path = _sheet(tmp_path, [_publish_row(poster)])

    rc = await run(_args(path, commit=False), "test")

    assert rc == 0
    assert await _published_at(db_session, poster.id) is None
    assert await _audit_fields(db_session, poster.id) == []


async def test_a_grade_from_the_sheet_lands_together_with_the_publication(
    db_session: AsyncSession, tmp_path: Path, use_test_session: None
) -> None:
    """ใบที่ยังไม่มีเกรด + กรอกเกรดในแถวเดียวกับ `publish=Y` ⇒ เขียนทั้งคู่

    เส้นทางนี้คือสิ่งที่เปิดขายจริง 116 ใบเมื่อ 2026-08-07 — เทสเดิมพิสูจน์ได้แค่ว่า
    `plan_writes()` *วางแผน* ถูก ไม่ได้พิสูจน์ว่าค่าลง DB จริงทั้งสองตัว
    """
    poster = await _make_poster(db_session, condition_grade=None)
    path = _sheet(tmp_path, [_publish_row(poster, condition_grade="fine")])

    rc = await run(_args(path, commit=True), "test")

    assert rc == 0
    grade = await db_session.scalar(
        select(Poster.condition_grade).where(Poster.id == poster.id)
    )
    assert grade is PosterCondition.fine
    assert await _published_at(db_session, poster.id) == REVIEWED_AT
    assert await _audit_fields(db_session, poster.id) == [
        "condition_grade",
        "published_at",
    ]


# --------------------------------------------------------------------------
# ด่านทั้งสี่ — เดินครบวงจาก CSV → run() → DB (AC-3)
# --------------------------------------------------------------------------
#
# ทุกตัวยืนยันสามอย่างเสมอ: exit code = 1 (AC-4) · `published_at` ยัง NULL ใน DB ·
# ไม่มีแถว audit · **ไม่ assert ข้อความรายงานเลย** เพราะรายงานถูกแต่เขียนจริงเป็น
# คนละเรื่อง และถ้อยคำเป็นของ `_publish_blocker_message()` ซึ่งมีเทสของตัวเองอยู่แล้ว


async def _assert_blocked(
    session: AsyncSession, poster: Poster, path: Path, *, commit: bool = True
) -> None:
    rc = await run(_args(path, commit=commit), "test")
    assert rc == 1
    assert await _published_at(session, poster.id) is None
    assert await _audit_fields(session, poster.id) == []


async def test_publishing_without_a_grade_is_refused_end_to_end(
    db_session: AsyncSession, tmp_path: Path, use_test_session: None
) -> None:
    """BR-05 · ADR-0013 D3 — ด่านนี้มีคู่ระดับ DB แต่สคริปต์ต้องหยุดก่อนถึง DB"""
    poster = await _make_poster(db_session, condition_grade=None)
    await _assert_blocked(db_session, poster, _sheet(tmp_path, [_publish_row(poster)]))


async def test_publishing_without_a_front_photo_is_refused_end_to_end(
    db_session: AsyncSession, tmp_path: Path, use_test_session: None
) -> None:
    """BR-06 · ADR-0026 D8 — ด่านนี้**ไม่มีคู่ระดับ DB และจะไม่มี** (ไม่ทำ trigger)
    ⇒ ถ้าสายขาด ของขึ้นร้านโดยไม่มีรูปหน้าใบและไม่มีอะไรทักเลย"""
    poster = await _make_poster(db_session, image_kind=PosterImageKind.DEFECT)
    await _assert_blocked(db_session, poster, _sheet(tmp_path, [_publish_row(poster)]))


async def test_publishing_with_a_count_of_zero_is_refused_end_to_end(
    db_session: AsyncSession, tmp_path: Path, use_test_session: None
) -> None:
    """ADR-0019 D9 ข้อ 2 — เคส `THE MATRIX (ADVANCE 4K)` เป๊ะ ๆ: การนับบอกว่าไม่มีของ
    แต่ของขึ้นหน้าร้าน · ด่านนี้อยู่ที่สคริปต์ที่เดียวเช่นกัน"""
    poster = await _make_poster(db_session)
    path = _sheet(tmp_path, [_publish_row(poster, count_actual="0")])
    await _assert_blocked(db_session, poster, path)


async def test_publishing_many_pieces_on_a_non_mint_grade_is_refused_end_to_end(
    db_session: AsyncSession, tmp_path: Path, use_test_session: None
) -> None:
    """ADR-0019 D1 — เกรดต่ำกว่า mint ต้องเป็น 1 แถว 1 ชิ้นเสมอ ไม่มีดุลพินิจ"""
    poster = await _make_poster(db_session, condition_grade=PosterCondition.near_mint)
    path = _sheet(tmp_path, [_publish_row(poster, count_actual="3")])
    await _assert_blocked(db_session, poster, path)


async def test_publishing_an_unverified_poster_is_refused_end_to_end(
    db_session: AsyncSession, tmp_path: Path, use_test_session: None
) -> None:
    """ADR-0027 D1 (INF-28) — invariant `published ⇒ verified` เดินครบวงจาก CSV → DB

    🔴 **ด่านนี้ยังไม่มีคู่ระดับ DB** — CHECK `ck_posters_published_requires_verified`
    ลงพร้อมขั้นถอนแถวค้าง (ADR-0027 D4) ⇒ วันนี้ถ้าสายขาด ของขึ้นร้านโดยไม่มีใครตรวจ
    และ **ไม่มีอะไรทักเลยสักชั้น** · เทสตัวนี้จึงเป็นด่านเดียวที่มีในตอนนี้

    ‹เทสนี้เกิดได้เพราะ harness ของ INF-30 merge เข้ามาก่อน — ก่อนหน้านั้น
    ด่านระดับ `run()` ยิงไม่ได้เลย ซึ่งเป็นเหตุผลที่ลำดับ INF-30 → INF-28 ถูกบังคับ›
    """
    poster = await _make_poster(db_session, verified_at=None)
    await _assert_blocked(db_session, poster, _sheet(tmp_path, [_publish_row(poster)]))


async def test_many_pieces_on_mint_is_allowed_end_to_end(
    db_session: AsyncSession, tmp_path: Path, use_test_session: None
) -> None:
    """ประตูของ D1 เปิดอยู่จริง — ไม่งั้นเทสข้างบนเขียวได้ด้วยด่านที่ปฏิเสธจำนวน ≥2 หมด"""
    poster = await _make_poster(db_session, condition_grade=PosterCondition.mint)
    path = _sheet(tmp_path, [_publish_row(poster, count_actual="3")])

    rc = await run(_args(path, commit=True), "test")

    assert rc == 0
    assert await _published_at(db_session, poster.id) == REVIEWED_AT


async def test_one_bad_row_stops_the_whole_file_before_anything_is_written(
    db_session: AsyncSession, tmp_path: Path, use_test_session: None
) -> None:
    """🔴 fail-closed ระดับไฟล์ (ADR-0015 D4) — แถวที่ถูกต้องในไฟล์เดียวกัน **ต้องไม่ถูกเขียน**

    เทสเดิมพิสูจน์ได้แค่ว่า `plan_writes()` ใส่ `blockers` ให้แถวที่ผิด · สิ่งที่ยังไม่มี
    ใครพิสูจน์คือ **`run()` หยุดทั้งไฟล์จริงก่อนแตะ DB** ซึ่งเป็นสัญญาที่แพงที่สุดของเส้นนี้
    """
    good = await _make_poster(db_session)
    bad = await _make_poster(db_session, condition_grade=None)
    path = _sheet(tmp_path, [_publish_row(good), _publish_row(bad)])

    rc = await run(_args(path, commit=True), "test")

    assert rc == 1
    assert await _published_at(db_session, good.id) is None
    assert await _published_at(db_session, bad.id) is None
    assert await _audit_fields(db_session, good.id) == []
