"""harness ระดับ `run()` ของเส้นที่ 5 — INF-29 (ADR-0027)

🔴 **ทำไมไฟล์นี้ต้องมี** — เหตุผลเดียวกับ `test_manual_entry_run_harness.py` (INF-30):
`test_correction_entry.py` มีเทสหลายร้อยตัวที่ยิงที่ `plan_writes()`/`audit_entries()`
ซึ่งเป็น pure ⇒ พิสูจน์ได้แค่ว่า *ตรรกะของด่านถูก* ไม่ได้พิสูจน์ว่า **ด่านถูกต่อเข้าสาย
จริง** — โดยเฉพาะ cascade ของ ADR-0027 D6 (มุตทีชัน 2/4/5) และด่าน sold (มุตทีชัน 3)
ซึ่งทั้งคู่ต้องรู้สถานะ DB สด ๆ (`_load_state()`) และต้องพิสูจน์ผ่านธุรกรรมจริง

## สิ่งที่ไฟล์นี้ทำ และไม่ทำ

- ✅ เรียก **`run()` ตัวจริง** ด้วยไฟล์ CSV จริงใน `tmp_path` และ `db_session` จริง
- ✅ assert ที่ **ผลลัพธ์ใน DB** (`verified_at`/`published_at`/`condition_grade` ·
  แถว `poster_attribute_reviews`) ไม่ใช่ที่ข้อความรายงาน
- ✅ `count_actual` อ่านจาก **ไฟล์ manual-entry.csv จริง** ใน `tmp_path` ผ่าน
  `manual_entry.load_count_actual_by_poster()` ตัวจริง (แทนเฉพาะ `mod.DEFAULT_MANUAL_CSV`
  ให้ชี้มาที่ไฟล์ทดสอบ — ไม่ mock ตัวฟังก์ชันเอง) เพื่อพิสูจน์เส้นทางอ่านข้ามไฟล์จริง
- ❌ **ไม่แตะตรรกะของเส้นที่ 5 แม้บรรทัดเดียว** — `scripts/seed/correction_entry.py`
  ต้องไม่ปรากฏใน `git diff --stat` ของงานที่แก้ไฟล์นี้ทีหลัง

⚠️ **ข้อจำกัดที่ต้องรู้** — harness ประกอบ `argparse.Namespace` เอง จึงไม่ครอบชั้น
argparse ของ `main()` (ทรงเดียวกับ INF-30 §G1 ที่เปิดไว้เป็น gap แยก)
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

from app.models.enums import PosterCondition, PosterImageKind, PosterStatus
from app.models.poster import Poster, PosterImage
from app.models.poster_attribute_review import PosterAttributeReview
from tests.support import HOUSE_APPROVED_AT, HOUSE_SELLER_ID
from scripts.seed import correction_entry as mod
from scripts.seed.correction_entry import CORRECTION_SHEET_COLUMNS, run
from scripts.seed.manual_entry import MANUAL_SHEET_COLUMNS

REVIEWED_AT = datetime(2026, 8, 16, 9, 0, tzinfo=UTC)
REVIEWED_BY = "chanothai.d"
# เวลาที่ "คนตรวจใบจริงแล้วเซ็นรับ/ถอน" รอบก่อนหน้า — ค่าคงที่ ไม่ใช่ now()
PAST_SIGNED_AT = datetime(2026, 8, 10, 10, 0, tzinfo=UTC)


class _SessionHandle:
    """ตัวแทน `async_session_maker()` ที่คืน **session ของเทส** แทนการเปิดใหม่

    🔴 นี่คือ **จุดเดียว** ที่ harness แทนของจริง — ทุกอย่างที่เหลือใน `run()` เป็น
    ของจริงทั้งหมด รวม `_check_schema()` · `_load_state()` ·
    `assert_no_row_targets_a_sold_poster()` · `assert_signable()` · `plan_writes()`
    · `session.commit()` (savepoint ตาม `join_transaction_mode` ของ fixture)
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
    path = tmp_path / "correction-entry.csv"
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(CORRECTION_SHEET_COLUMNS))
        writer.writeheader()
        for row in rows:
            writer.writerow({col: row.get(col, "") for col in CORRECTION_SHEET_COLUMNS})
    return path


def _manual_csv(tmp_path: Path, counts: dict[uuid.UUID, str]) -> Path:
    """ไฟล์ `manual-entry.csv` จริง — ด่านก่อนเซ็น (D3) อ่าน `count_actual` จากที่นี่
    ผ่าน `manual_entry.load_count_actual_by_poster()` ตัวจริง (ไม่ mock)"""
    path = tmp_path / "manual-entry.csv"
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(MANUAL_SHEET_COLUMNS))
        writer.writeheader()
        for poster_id, count_actual in counts.items():
            row = {col: "" for col in MANUAL_SHEET_COLUMNS}
            row["poster_uuid"] = str(poster_id)
            row["count_actual"] = count_actual
            writer.writerow(row)
    return path


@pytest.fixture
def use_test_manual_csv(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """ปริยาย = ไฟล์ manual-entry.csv ว่างเปล่า (ไม่มีแถวของใครเลย) — เทสที่ต้องการ
    ผลนับจริงเรียก `_manual_csv()` เองแล้วตั้งค่านี้ทับ"""
    default_path = _manual_csv(tmp_path, {})
    monkeypatch.setattr(mod, "DEFAULT_MANUAL_CSV", default_path)

    def set_counts(counts: dict[uuid.UUID, str]) -> None:
        monkeypatch.setattr(mod, "DEFAULT_MANUAL_CSV", _manual_csv(tmp_path, counts))

    return set_counts


def _args(
    path: Path, *, commit: bool, field: list[str] | None = None
) -> argparse.Namespace:
    return argparse.Namespace(
        file=path,
        field=field or [],
        commit=commit,
        reviewed_by=REVIEWED_BY,
        reviewed_at=REVIEWED_AT,
    )


async def _make_poster(
    session: AsyncSession,
    *,
    condition_grade: PosterCondition | None = PosterCondition.very_good,
    is_unique: bool = True,
    verified_at: datetime | None = None,
    published_at: datetime | None = None,
    status: PosterStatus = PosterStatus.available,
    image_kind: PosterImageKind | None = PosterImageKind.FRONT,
) -> Poster:
    # ck_posters_sold_requires_sold_at (ADR-0025 D2) — ใบที่ sold ต้องมี sold_at เสมอ
    sold_at = PAST_SIGNED_AT if status is PosterStatus.sold else None
    poster = Poster(
        seller_id=HOUSE_SELLER_ID,
        approved_at=HOUSE_APPROVED_AT,
        title=f"Harness {uuid.uuid4()}",
        price=Decimal("500"),
        condition_grade=condition_grade,
        is_unique=is_unique,
        verified_at=verified_at,
        published_at=published_at,
        status=status,
        sold_at=sold_at,
    )
    session.add(poster)
    await session.flush()
    if image_kind is not None:
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


def _row(poster: Poster, **over: str) -> dict[str, str]:
    row: dict[str, str] = {"poster_uuid": str(poster.id)}
    row.update(over)
    return row


async def _refresh(session: AsyncSession, poster_id: uuid.UUID) -> Poster:
    return await session.get(Poster, poster_id)


async def _audit_fields(session: AsyncSession, poster_id: uuid.UUID) -> list[str]:
    rows = await session.execute(
        select(PosterAttributeReview.field).where(
            PosterAttributeReview.poster_id == poster_id
        )
    )
    return sorted(rows.scalars().all())


# --------------------------------------------------------------------------
# ทางที่สำเร็จ — SIGN / WITHDRAW เดี่ยว ๆ (ตัวหลักที่ฆ่า mutation "ตัด plan_writes")
# --------------------------------------------------------------------------


async def test_commit_signs_a_poster_and_records_the_audit_row(
    db_session: AsyncSession,
    tmp_path: Path,
    use_test_session: None,
    use_test_manual_csv,
) -> None:
    """🔴 positive control ของทั้งไฟล์ — ถ้าไม่มีตัวนี้ ชุดข้างล่างเขียวได้ด้วย
    `run()` ที่ปฏิเสธทุกกรณี"""
    poster = await _make_poster(db_session, verified_at=None)
    use_test_manual_csv({poster.id: "1"})
    path = _sheet(
        tmp_path,
        [_row(poster, verified_at="SIGN", verified_at_reason="ตรวจครบทุกมิติแล้ว")],
    )

    rc = await run(_args(path, commit=True), "test")

    assert rc == 0
    refreshed = await _refresh(db_session, poster.id)
    assert refreshed.verified_at == REVIEWED_AT
    assert await _audit_fields(db_session, poster.id) == ["verified_at"]


async def test_dry_run_touches_nothing_in_the_database(
    db_session: AsyncSession,
    tmp_path: Path,
    use_test_session: None,
    use_test_manual_csv,
) -> None:
    poster = await _make_poster(db_session, verified_at=None)
    use_test_manual_csv({poster.id: "1"})
    path = _sheet(
        tmp_path,
        [_row(poster, verified_at="SIGN", verified_at_reason="ตรวจครบทุกมิติแล้ว")],
    )

    rc = await run(_args(path, commit=False), "test")

    assert rc == 0
    refreshed = await _refresh(db_session, poster.id)
    assert refreshed.verified_at is None
    assert await _audit_fields(db_session, poster.id) == []


async def test_commit_withdraws_a_published_poster(
    db_session: AsyncSession,
    tmp_path: Path,
    use_test_session: None,
    use_test_manual_csv,
) -> None:
    poster = await _make_poster(
        db_session, verified_at=PAST_SIGNED_AT, published_at=PAST_SIGNED_AT
    )
    use_test_manual_csv({})
    path = _sheet(
        tmp_path,
        [_row(poster, published_at="WITHDRAW", published_at_reason="พบว่าข้อมูลผิด")],
    )

    rc = await run(_args(path, commit=True), "test")

    assert rc == 0
    refreshed = await _refresh(db_session, poster.id)
    assert refreshed.published_at is None
    # ADR-0027 D6 ไม่มีการเขียน condition_grade/is_unique ในรอบนี้ → cascade ไม่ทำงาน
    # → verified_at ยังอยู่เหมือนเดิม (WITHDRAW ไม่แตะ verified_at เลย)
    assert refreshed.verified_at == PAST_SIGNED_AT
    assert await _audit_fields(db_session, poster.id) == ["published_at"]


# --------------------------------------------------------------------------
# มุตทีชัน 2/4/5 — นโยบายความสด (D6) เดินครบวงจาก CSV → run() → DB
# --------------------------------------------------------------------------


async def test_editing_the_grade_clears_signature_and_publication_in_one_commit(
    db_session: AsyncSession,
    tmp_path: Path,
    use_test_session: None,
    use_test_manual_csv,
) -> None:
    """🔴 มุตทีชัน 2 — ถอด cascade ออกทั้งก้อนต้องทำให้เทสนี้แดง"""
    poster = await _make_poster(
        db_session, verified_at=PAST_SIGNED_AT, published_at=PAST_SIGNED_AT
    )
    use_test_manual_csv({})
    path = _sheet(
        tmp_path,
        [_row(poster, condition_grade="fine", condition_grade_reason="ตรวจซ้ำพบตำหนิ")],
    )

    rc = await run(_args(path, commit=True), "test")

    assert rc == 0
    refreshed = await _refresh(db_session, poster.id)
    assert refreshed.condition_grade is PosterCondition.fine
    assert refreshed.verified_at is None
    assert refreshed.published_at is None
    assert await _audit_fields(db_session, poster.id) == [
        "condition_grade",
        "published_at",
        "verified_at",
    ]


async def test_the_cascade_still_clears_when_field_flag_narrows_to_grade_only(
    db_session: AsyncSession,
    tmp_path: Path,
    use_test_session: None,
    use_test_manual_csv,
) -> None:
    """🔴 มุตทีชัน 4 — `--field condition_grade` ต้องไม่กลายเป็นทางเลี่ยง D6"""
    poster = await _make_poster(
        db_session, verified_at=PAST_SIGNED_AT, published_at=PAST_SIGNED_AT
    )
    use_test_manual_csv({})
    path = _sheet(
        tmp_path,
        [_row(poster, condition_grade="fine", condition_grade_reason="ตรวจซ้ำพบตำหนิ")],
    )

    rc = await run(_args(path, commit=True, field=["condition_grade"]), "test")

    assert rc == 0
    refreshed = await _refresh(db_session, poster.id)
    assert refreshed.condition_grade is PosterCondition.fine
    assert refreshed.verified_at is None
    assert refreshed.published_at is None


async def test_sign_wins_over_the_cascade_in_the_same_row(
    db_session: AsyncSession,
    tmp_path: Path,
    use_test_session: None,
    use_test_manual_csv,
) -> None:
    """🔴 มุตทีชัน 5 — สลับลำดับ cascade กับ SIGN ต้องทำให้แถวจบด้วย verified_at
    ไม่เป็น NULL"""
    poster = await _make_poster(
        db_session,
        condition_grade=PosterCondition.very_good,  # ต้องมีเกรดเดิมที่ "fine" ต่างจากนี้
        verified_at=PAST_SIGNED_AT,  # เคยเซ็นมาแล้ว — cascade ต้องพยายามล้างค่านี้
        published_at=None,
    )
    use_test_manual_csv({poster.id: "1"})
    path = _sheet(
        tmp_path,
        [
            _row(
                poster,
                condition_grade="fine",
                condition_grade_reason="ตรวจซ้ำพบตำหนิ",
                verified_at="SIGN",
                verified_at_reason="ตรวจครบทุกมิติแล้วหลังแก้เกรด",
            )
        ],
    )

    rc = await run(_args(path, commit=True), "test")

    assert rc == 0
    refreshed = await _refresh(db_session, poster.id)
    assert refreshed.condition_grade is PosterCondition.fine
    assert refreshed.verified_at == REVIEWED_AT  # ไม่ใช่ NULL — SIGN ทับ cascade
    fields = await _audit_fields(db_session, poster.id)
    assert fields == ["condition_grade", "verified_at"]


# --------------------------------------------------------------------------
# มุตทีชัน 3 — ด่าน sold (ADR-0027 A-D11) เดินครบวงจาก CSV → run() → DB
# --------------------------------------------------------------------------


async def test_a_row_touching_a_sold_poster_blocks_the_whole_file(
    db_session: AsyncSession,
    tmp_path: Path,
    use_test_session: None,
    use_test_manual_csv,
) -> None:
    """🔴 มุตทีชัน 3 — แถวที่ถูกต้องในไฟล์เดียวกันต้องไม่ถูกเขียนเลย (fail-closed)"""
    good = await _make_poster(db_session, verified_at=None)
    sold = await _make_poster(db_session, status=PosterStatus.sold)
    use_test_manual_csv({good.id: "1"})
    path = _sheet(
        tmp_path,
        [
            _row(good, verified_at="SIGN", verified_at_reason="ตรวจครบทุกมิติแล้ว"),
            _row(
                sold,
                condition_grade="fine",
                condition_grade_reason="ตรวจซ้ำพบตำหนิ",
            ),
        ],
    )

    from scripts.seed.correction_entry import PrecheckError

    with pytest.raises(PrecheckError, match="A-D11"):
        await run(_args(path, commit=True), "test")

    refreshed_good = await _refresh(db_session, good.id)
    refreshed_sold = await _refresh(db_session, sold.id)
    assert refreshed_good.verified_at is None
    assert refreshed_sold.condition_grade is not PosterCondition.fine
    assert await _audit_fields(db_session, good.id) == []
    assert await _audit_fields(db_session, sold.id) == []


async def test_withdrawing_a_sold_poster_is_blocked_too(
    db_session: AsyncSession,
    tmp_path: Path,
    use_test_session: None,
    use_test_manual_csv,
) -> None:
    poster = await _make_poster(
        db_session, status=PosterStatus.sold, published_at=PAST_SIGNED_AT
    )
    use_test_manual_csv({})
    path = _sheet(
        tmp_path,
        [_row(poster, published_at="WITHDRAW", published_at_reason="พบว่าข้อมูลผิด")],
    )

    from scripts.seed.correction_entry import PrecheckError

    with pytest.raises(PrecheckError, match="A-D11"):
        await run(_args(path, commit=True), "test")

    refreshed = await _refresh(db_session, poster.id)
    assert refreshed.published_at == PAST_SIGNED_AT


# --------------------------------------------------------------------------
# ด่านก่อนเซ็น (ADR-0027 D3) เดินครบวงจาก CSV → run() → DB — รวมการอ่าน
# manual-entry.csv จริง (ไม่ mock ฟังก์ชัน)
# --------------------------------------------------------------------------


async def test_signing_without_a_front_photo_is_refused_end_to_end(
    db_session: AsyncSession,
    tmp_path: Path,
    use_test_session: None,
    use_test_manual_csv,
) -> None:
    poster = await _make_poster(db_session, image_kind=PosterImageKind.DEFECT)
    use_test_manual_csv({poster.id: "1"})
    path = _sheet(
        tmp_path,
        [_row(poster, verified_at="SIGN", verified_at_reason="ตรวจครบทุกมิติแล้ว")],
    )

    from scripts.seed.correction_entry import PrecheckError

    with pytest.raises(PrecheckError, match="ADR-0027 D3"):
        await run(_args(path, commit=True), "test")

    refreshed = await _refresh(db_session, poster.id)
    assert refreshed.verified_at is None


async def test_signing_without_a_count_row_in_manual_entry_csv_is_refused(
    db_session: AsyncSession,
    tmp_path: Path,
    use_test_session: None,
    use_test_manual_csv,
) -> None:
    """🔴 count_actual มาจากไฟล์จริง — ไม่มีแถวของ poster นี้เลยใน manual-entry.csv
    ⇒ UNKNOWN_COUNT ⇒ ปฏิเสธทั้งไฟล์"""
    poster = await _make_poster(db_session)
    use_test_manual_csv({})  # ไฟล์มีอยู่ แต่ไม่มีแถวของ poster นี้
    path = _sheet(
        tmp_path,
        [_row(poster, verified_at="SIGN", verified_at_reason="ตรวจครบทุกมิติแล้ว")],
    )

    from scripts.seed.correction_entry import PrecheckError

    with pytest.raises(PrecheckError, match="ADR-0027 D3"):
        await run(_args(path, commit=True), "test")

    refreshed = await _refresh(db_session, poster.id)
    assert refreshed.verified_at is None


async def test_signing_succeeds_when_the_real_manual_entry_csv_has_the_count(
    db_session: AsyncSession,
    tmp_path: Path,
    use_test_session: None,
    use_test_manual_csv,
) -> None:
    """positive control ของ §ด่านก่อนเซ็น — ยืนยันว่าการอ่านไฟล์จริงเดินสำเร็จได้"""
    poster = await _make_poster(db_session)
    use_test_manual_csv({poster.id: "1"})
    path = _sheet(
        tmp_path,
        [_row(poster, verified_at="SIGN", verified_at_reason="ตรวจครบทุกมิติแล้ว")],
    )

    rc = await run(_args(path, commit=True), "test")

    assert rc == 0
    refreshed = await _refresh(db_session, poster.id)
    assert refreshed.verified_at == REVIEWED_AT
