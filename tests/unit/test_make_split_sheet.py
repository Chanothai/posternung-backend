"""Unit tests ของ `scripts/seed/make_split_sheet.py` — INF-22 (ADR-0024)

จุดสำคัญที่สุดที่ต้องล็อก (เหมือน `make_correction_sheet.py`): สคริปต์นี้ **ห้ามกรอก
ช่องของคนให้** — เครื่องที่เสนอเกรด/ราคาให้คนเซ็นคือเครื่องที่ตัดสินสภาพและราคาสินค้า
แทนคน (ADR-0009 D6) และตัวกรองปริยาย (`is_unique=false` + published) ต้องตรงกับ
ความหมายของ ADR-0019 D1/D2 — ไม่ใช่ "มีเกรดอยู่แล้ว" แบบเส้นที่ 5
"""

from __future__ import annotations

import ast
import inspect
import uuid
from datetime import UTC, datetime
from pathlib import Path

import pytest

from app.models.enums import PosterCondition
from scripts.seed import make_split_sheet as mod
from scripts.seed._shared import PrecheckError
from scripts.seed.make_split_sheet import (
    HUMAN_COLUMNS,
    build_sheet_rows,
    load_counted_parent_ids,
)
from scripts.seed.manual_entry import MANUAL_SHEET_COLUMNS
from scripts.seed.split_entry import SPLIT_SHEET_COLUMNS

PID = uuid.UUID("11111111-1111-1111-1111-111111111111")
PID2 = uuid.UUID("22222222-2222-2222-2222-222222222222")
PUBLISHED = datetime(2026, 1, 1, tzinfo=UTC)


def _db_row(**over: object) -> dict:
    row: dict = {
        "id": PID,
        "title": "The Matrix",
        "is_unique": False,
        "published_at": PUBLISHED,
        "condition_grade": PosterCondition.mint,
    }
    row.update(over)
    return row


# --------------------------------------------------------------------------
# เครื่องห้ามกรอกช่องของคน
# --------------------------------------------------------------------------


def test_the_three_human_columns_are_always_left_empty() -> None:
    """🔴 กฎที่สำคัญที่สุดของสคริปต์นี้"""
    rows = build_sheet_rows(
        [_db_row(), _db_row(id=PID2, title="Another")], {}, include_all=True
    )
    assert len(rows) == 2
    for row in rows:
        for column in HUMAN_COLUMNS:
            assert row[column] == "", column


def test_generator_never_writes_into_the_human_columns() -> None:
    """ล็อกที่ระดับซอร์ส — ถ้ามีใครเพิ่ม flag ให้เดาเกรด/ราคาที่ "น่าจะถูก"
    ต้องแดงทันที (closed-world บน `seen`)
    """
    tree = ast.parse(inspect.getsource(mod.build_sheet_rows))
    seen: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Dict):
            continue
        for key, value in zip(node.keys, node.values, strict=True):
            if isinstance(key, ast.Constant) and key.value in HUMAN_COLUMNS:
                assert isinstance(
                    value, ast.Constant
                ), f"{key.value} ถูกเติมด้วยนิพจน์ ไม่ใช่ค่าว่างคงที่"
                assert value.value == "", f"{key.value} ถูกกรอกค่าให้: {value.value!r}"
                seen.add(key.value)
    assert seen == set(HUMAN_COLUMNS)


def test_the_human_columns_match_split_entrys_own_definition() -> None:
    """ประกอบจากค่าคงที่ของ split_entry.py ไม่ใช่รายชื่อที่พิมพ์ไว้ — ฟิลด์ที่เพิ่มเข้า
    วันหน้าจะถูกล็อกทันทีโดยไม่ต้องมีใครนึกได้ว่าต้องมาต่อรายชื่อ"""
    from scripts.seed.split_entry import HUMAN_COLUMNS as SPLIT_ENTRY_HUMAN_COLUMNS

    assert set(HUMAN_COLUMNS) == set(SPLIT_ENTRY_HUMAN_COLUMNS)


def test_generator_never_reaches_for_the_current_time() -> None:
    source = ast.unparse(ast.parse(inspect.getsource(mod)))
    for forbidden in ("now(", "today(", "utcnow("):
        assert forbidden not in source, f"พบ {forbidden} ในซอร์ส"


def test_sheet_uses_the_column_list_shared_with_the_applier() -> None:
    (row,) = build_sheet_rows([_db_row()], {}, include_all=True)
    assert tuple(row) == SPLIT_SHEET_COLUMNS


# --------------------------------------------------------------------------
# image_url
# --------------------------------------------------------------------------


def test_image_url_comes_from_the_public_url_map_only() -> None:
    """ADR-0006 D5 — key ที่ไม่ public ถูกกรองทิ้งก่อนถึง build_media_url() (ที่ชั้น
    `load_from_db()` ไม่ใช่ในนี้) — ที่นี่ตรวจแค่ว่า build_sheet_rows() ใช้ map ที่ส่งมา
    """
    rows = build_sheet_rows(
        [_db_row(), _db_row(id=PID2, title="Another")],
        {PID: "https://cdn.invalid/a.jpg"},
        include_all=True,
    )
    by_id = {r["parent_poster_uuid"]: r for r in rows}
    assert by_id[str(PID)]["parent_image_url"] == "https://cdn.invalid/a.jpg"
    assert by_id[str(PID2)]["parent_image_url"] == ""


# --------------------------------------------------------------------------
# ใบไหนเข้าใบงาน — is_unique=false + published (ต่างจากเส้นที่ 5)
# --------------------------------------------------------------------------


def test_default_filter_is_is_unique_false_and_published() -> None:
    rows = build_sheet_rows([_db_row()], {}, include_all=False)
    assert len(rows) == 1


def test_a_unique_row_is_excluded_by_default() -> None:
    row = _db_row(is_unique=True)
    assert build_sheet_rows([row], {}, include_all=False) == []
    assert len(build_sheet_rows([row], {}, include_all=True)) == 1


def test_an_unpublished_row_is_excluded_by_default() -> None:
    row = _db_row(published_at=None)
    assert build_sheet_rows([row], {}, include_all=False) == []
    assert len(build_sheet_rows([row], {}, include_all=True)) == 1


def test_all_flag_includes_everything_regardless_of_filter() -> None:
    rows = [
        _db_row(id=PID, is_unique=True, published_at=None),
        _db_row(id=PID2, is_unique=False, published_at=PUBLISHED),
    ]
    assert len(build_sheet_rows(rows, {}, include_all=False)) == 1
    assert len(build_sheet_rows(rows, {}, include_all=True)) == 2


def test_rows_sort_by_title() -> None:
    rows = build_sheet_rows(
        [
            _db_row(id=PID, title="ZZZ"),
            _db_row(id=PID2, title="AAA"),
        ],
        {},
        include_all=True,
    )
    assert [r["parent_title"] for r in rows] == ["AAA", "ZZZ"]


# --------------------------------------------------------------------------
# ด่านที่ 1 ของ code-critic รอบ 4 — ต้องมีเกรดแล้ว (กันกรอบไฟ BL-82)
# --------------------------------------------------------------------------


def test_a_row_with_no_grade_is_excluded_by_default() -> None:
    row = _db_row(condition_grade=None)
    assert build_sheet_rows([row], {}, include_all=False) == []


def test_a_row_with_no_grade_is_excluded_even_with_all() -> None:
    """🔴 ตัวฆ่า mutation หลักของก้อนที่ 4 — ถ้าด่านนี้ถูกยกไปอยู่ใต้ `if not
    include_all` โดยไม่ตั้งใจ เทสนี้ต้องแดง (กรอบไฟของ BL-82 เข้าได้ผ่าน `--all`)
    """
    row = _db_row(condition_grade=None, is_unique=False, published_at=None)
    assert build_sheet_rows([row], {}, include_all=True) == []


def test_a_row_with_a_grade_still_passes_with_all() -> None:
    """ด้านที่ต้องไม่พัง — แถวที่มีเกรดจริงต้องไม่โดนด่านนี้กันด้วย"""
    row = _db_row(condition_grade=PosterCondition.very_good, published_at=None)
    assert len(build_sheet_rows([row], {}, include_all=True)) == 1


def test_every_published_row_in_the_default_pool_already_has_a_grade_by_construction() -> (
    None
):
    """เอกสารเป็นเทส — โปสเตอร์ที่ published ทุกใบมีเกรดอยู่แล้วจริงตาม CHECK
    `ck_posters_published_requires_condition_grade` (`app/models/poster.py`) ดังนั้น
    ด่านนี้ไม่มีวันกันแถวที่ถูกต้องออกจากตัวกรองปริยาย — ทดสอบด้วยการยืนยันว่าแถวปริยาย
    ทั่วไป (`_db_row()` ที่ไม่ได้ override) ยังผ่านด่านทั้งสองข้อพร้อมกัน
    """
    row = _db_row()
    assert len(build_sheet_rows([row], {}, include_all=False)) == 1


# --------------------------------------------------------------------------
# ด่านที่ 2 ของ code-critic รอบ 4 — ต้องมีผลนับแล้ว (ADR-0024 INF-22 AC-1)
# --------------------------------------------------------------------------


def test_counted_parent_ids_excludes_rows_not_in_the_set() -> None:
    row = _db_row()
    assert (
        build_sheet_rows([row], {}, include_all=False, counted_parent_ids=set()) == []
    )


def test_counted_parent_ids_includes_rows_in_the_set() -> None:
    row = _db_row()
    rows = build_sheet_rows([row], {}, include_all=False, counted_parent_ids={PID})
    assert len(rows) == 1


def test_counted_parent_ids_none_means_no_filtering_at_all() -> None:
    """ค่าเริ่มต้น (`None`) = ไม่กรองข้อนี้ — ใช้ในเทสอื่นที่ไม่สนเรื่องผลนับ"""
    row = _db_row()
    rows = build_sheet_rows([row], {}, include_all=False, counted_parent_ids=None)
    assert len(rows) == 1


def test_all_flag_does_not_bypass_the_counted_gate() -> None:
    """🔴 `--all` ข้ามได้แค่ตัวกรอง is_unique/published — ไม่ข้ามด่านผลนับ"""
    row = _db_row(is_unique=True, published_at=None)
    rows = build_sheet_rows(
        [row], {}, include_all=True, counted_parent_ids=set()  # ยังไม่ได้นับ
    )
    assert rows == []


# --------------------------------------------------------------------------
# load_counted_parent_ids — อ่าน count_actual จาก manual-entry.csv
# --------------------------------------------------------------------------

_MANUAL_REQUIRED_BLANKS = {
    "condition_grade": "",
    "year": "",
    "poster_type": "",
    "restoration_status": "",
    "tmdb_id": "",
    "width_in": "",
    "height_in": "",
    "publish": "",
    "title": "",
    "image_url": "",
    "note": "",
}


def _write_manual_csv(path: Path, rows: list[dict[str, str]]) -> None:
    import csv

    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(MANUAL_SHEET_COLUMNS))
        writer.writeheader()
        for row in rows:
            full = dict(_MANUAL_REQUIRED_BLANKS)
            full["poster_uuid"] = str(row.get("poster_uuid", ""))
            full["count_actual"] = row.get("count_actual", "")
            writer.writerow(full)


def test_load_counted_parent_ids_includes_rows_with_a_non_blank_count(
    tmp_path: Path,
) -> None:
    path = tmp_path / "manual-entry.csv"
    _write_manual_csv(path, [{"poster_uuid": str(PID), "count_actual": "3"}])
    assert load_counted_parent_ids(path) == {PID}


def test_load_counted_parent_ids_excludes_blank_count_rows(tmp_path: Path) -> None:
    """🔴 นี่คือเคสจริงของวันนี้ — count_actual ว่าง 117/117"""
    path = tmp_path / "manual-entry.csv"
    _write_manual_csv(
        path,
        [
            {"poster_uuid": str(PID), "count_actual": ""},
            {"poster_uuid": str(PID2), "count_actual": "0"},
        ],
    )
    assert load_counted_parent_ids(path) == {PID2}  # "0" ไม่ว่าง — นับได้ 0 คือค่าจริง


def test_load_counted_parent_ids_skips_rows_with_a_malformed_uuid_silently(
    tmp_path: Path,
) -> None:
    """รูปแบบผิดไม่ใช่หน้าที่เครื่องมือนี้ตัดสิน — ปล่อยให้เส้นที่ 3 ฟ้องตอน publish"""
    path = tmp_path / "manual-entry.csv"
    _write_manual_csv(path, [{"poster_uuid": "not-a-uuid", "count_actual": "1"}])
    assert load_counted_parent_ids(path) == set()


def test_load_counted_parent_ids_raises_when_the_file_is_missing(
    tmp_path: Path,
) -> None:
    with pytest.raises(PrecheckError):
        load_counted_parent_ids(tmp_path / "does-not-exist.csv")
