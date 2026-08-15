"""Unit tests ของ `scripts/seed/make_split_sheet.py` — INF-22 (ADR-0024)

จุดสำคัญที่สุดที่ต้องล็อก (เหมือน `make_correction_sheet.py`): สคริปต์นี้ **ห้ามกรอก
ช่องของคนให้** — เครื่องที่เสนอเกรด/ราคาให้คนเซ็นคือเครื่องที่ตัดสินสภาพและราคาสินค้า
แทนคน (ADR-0009 D6) และตัวกรองปริยาย (`is_unique=false` + published) ต้องตรงกับ
ความหมายของ ADR-0019 D1/D2 — ไม่ใช่ "มีเกรดอยู่แล้ว" แบบเส้นที่ 5
"""

from __future__ import annotations

import ast
import csv
import inspect
import sys
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import PosterCondition
from app.models.poster import Poster
from app.models.poster_split import PosterSplit
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


def test_the_human_columns_are_split_entrys_object_not_a_copy() -> None:
    """`make_split_sheet.HUMAN_COLUMNS` ต้องเป็น **object เดียวกัน** กับของ
    `split_entry.py` ไม่ใช่ทูเพิลที่มีค่าเท่ากัน

    🔴 ‹INF-22 G5 · 2026-08-15› เทสตัวเดิมของหัวข้อนี้เทียบด้วย `set(...) == set(...)`
    ซึ่ง **ผ่านได้ทั้งกรณีที่ re-export จริงและกรณีที่พิมพ์รายชื่อซ้ำ** — จึงไม่เคยจับ
    ได้เลยว่าไฟล์นั้นพิมพ์ซ้ำอยู่จริงตลอดมา ทั้งที่คอมเมนต์ข้าง ๆ อ้างว่าไม่ซ้ำ
    · `is` แยกสองกรณีนั้นออกจากกันได้ เพราะทูเพิลลิเทอรัลคนละโมดูลเป็นคนละ object
    """
    from scripts.seed.split_entry import HUMAN_COLUMNS as SPLIT_ENTRY_HUMAN_COLUMNS

    assert HUMAN_COLUMNS is SPLIT_ENTRY_HUMAN_COLUMNS


def test_make_split_sheet_never_defines_its_own_human_columns() -> None:
    """ล็อกที่ระดับซอร์ส — คู่กับเทสข้างบน

    เทส `is` จับได้ว่า *วันนี้* ยังชี้ที่เดียวกัน แต่ถ้าวันหน้ามีคนประกาศทูเพิลใหม่
    ที่มีค่าเท่ากันทับ ข้อความ error ของ `is` จะอ่านไม่ออกว่าเกิดอะไรขึ้น · ตัวนี้บอกตรง ๆ
    (ทรงเดียวกับ `test_generator_never_writes_into_the_human_columns` ในไฟล์นี้)
    """
    tree = ast.parse(inspect.getsource(mod))
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        for target in node.targets:
            assert not (
                isinstance(target, ast.Name) and target.id == "HUMAN_COLUMNS"
            ), (
                "make_split_sheet.py ประกาศ HUMAN_COLUMNS เอง — ต้อง import จาก "
                "split_entry.py ซึ่งเป็นเจ้าของนิยาม (INF-22 G5)"
            )


def test_generator_never_reaches_for_the_current_time() -> None:
    source = ast.unparse(ast.parse(inspect.getsource(mod)))
    for forbidden in ("now(", "today(", "utcnow("):
        assert forbidden not in source, f"พบ {forbidden} ในซอร์ส"


def test_sheet_uses_the_column_list_shared_with_the_applier() -> None:
    (row,) = build_sheet_rows([_db_row()], {}, include_all=True)
    assert tuple(row) == SPLIT_SHEET_COLUMNS


# --------------------------------------------------------------------------
# piece_no — ADR-0024 A-D5 (INF-25) — เครื่องเติมให้ คนไม่ต้องพิมพ์เอง
# --------------------------------------------------------------------------


def test_piece_no_is_not_a_human_column() -> None:
    """🔴 ห้ามใส่ piece_no เข้า HUMAN_COLUMNS — จะบังคับให้ generator เขียนค่าว่าง
    (ผ่านเทส AST) และบังคับให้คนกรอกเลขชิ้นเอง ทั้งที่เครื่องต้องเป็นคนเติม
    """
    assert "piece_no" not in HUMAN_COLUMNS


def test_a_parent_with_no_children_yet_gets_piece_no_two() -> None:
    (row,) = build_sheet_rows([_db_row()], {}, include_all=True)
    assert row["piece_no"] == "2"


def test_a_parent_with_existing_children_gets_max_plus_one() -> None:
    (row,) = build_sheet_rows(
        [_db_row()], {}, include_all=True, next_piece_by_parent={PID: 5}
    )
    assert row["piece_no"] == "5"


def test_next_piece_by_parent_is_scoped_per_parent() -> None:
    rows = build_sheet_rows(
        [_db_row(id=PID), _db_row(id=PID2, title="Another")],
        {},
        include_all=True,
        next_piece_by_parent={PID: 7},
    )
    by_id = {r["parent_poster_uuid"]: r["piece_no"] for r in rows}
    assert by_id[str(PID)] == "7"
    assert by_id[str(PID2)] == "2"  # ไม่มีในเซต — ยังไม่มีลูก → 2


def test_next_piece_by_parent_none_means_everyone_gets_two() -> None:
    """ค่าเริ่มต้น (`None`) = ไม่มีประวัติเลย — ใช้ในเทสอื่นที่ไม่สนเรื่องนี้"""
    (row,) = build_sheet_rows(
        [_db_row()], {}, include_all=True, next_piece_by_parent=None
    )
    assert row["piece_no"] == "2"


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


# --------------------------------------------------------------------------
# main() — จุดต่อของ counted_parent_ids เข้า build_sheet_rows() (INF-22 High สุดท้าย)
# --------------------------------------------------------------------------
#
# 🔴 ด่านที่ 2 ข้างบน (`counted_parent_ids`) มีเทสของ `build_sheet_rows()` เองครบ
# ทุกกิ่งแล้ว แต่ **สายที่ต่อมันเข้า `main()` ไม่เคยถูกแตะเลย** เพราะไม่มีเทสตัวไหนใน
# ไฟล์นี้เรียก `mod.main()` มาก่อน — รูปเดียวกับ G5 ของ INF-21 เป๊ะ (ดู
# `test_correction_entry.py` §G5 — commit 98756d7/68cc030) mutation ที่ตัด
# `counted_parent_ids=counted_parent_ids` ออกจากอาร์กิวเมนต์ (แทนด้วย `None`) จะทำให้
# ด่าน "ต้องมีผลนับแล้ว" (ADR-0024 INF-22 AC-1) หายไปทั้งชั้นจาก CLI จริง แม้
# `build_sheet_rows()` เองจะยังถูกต้อง 100% ก็ตาม

DEV_URL_FOR_MAIN = "postgresql+asyncpg://u:p@localhost:5432/poster_nung_dev_test6"


def _install_split_sheet_cli(
    monkeypatch,
    out_path: Path,
    posters: list[dict],
    *argv: str,
    next_piece_by_parent: dict | None = None,
) -> None:
    """ต่อ `sys.argv` จริงเข้า `main()`

    `_load_env()` ถูกแทนด้วย no-op ด้วยเหตุผลเดียวกับ `_install_cli()` ของ
    `test_correction_entry.py` (`.env` ของเครื่องที่รันทำให้เทสไม่ deterministic) ·
    `load_from_db()` ถูกแทนด้วย fake ที่คืนค่าที่ควบคุมได้ทั้งหมด ไม่ต่อ DB จริง —
    ด่านที่เทสนี้ล็อกอยู่ *ปลายทาง* ของ `counted_parent_ids`/`next_piece_by_parent`
    ไม่ใช่การอ่าน DB · `next_piece_by_parent` เพิ่มเข้ามา 2026-08-15 (ADR-0024 A-D5 ·
    INF-25) — ค่าเริ่มต้น `{}` (ไม่มีพ่อไหนมีลูกอยู่แล้ว)
    """

    async def fake_load_from_db():
        return posters, {}, next_piece_by_parent or {}

    monkeypatch.setattr(mod, "_load_env", lambda _target: None)
    monkeypatch.setenv("DATABASE_URL", DEV_URL_FOR_MAIN)
    monkeypatch.setattr(mod, "load_from_db", fake_load_from_db)
    monkeypatch.setattr(
        sys, "argv", ["make_split_sheet.py", "--out", str(out_path), *argv]
    )


def _read_sheet(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def test_main_excludes_an_uncounted_poster_from_the_written_sheet(
    monkeypatch, tmp_path: Path
) -> None:
    """🔴 ตัวฆ่า mutation ที่ตัด `counted_parent_ids=counted_parent_ids` ออกจาก `main()`

    ใบพ่อผ่านทุกด่านอื่น (is_unique=false · published · มีเกรด) แต่ **ยังไม่มีผลนับ**
    (`count_actual` ว่างใน manual-entry.csv) — ถ้าด่านนี้หายไปจาก CLI จริง ใบนี้จะหลุด
    เข้าใบงานทั้งที่ยังไม่มีใครนับ (ADR-0024 INF-22 AC-1)
    """
    out_path = tmp_path / "split-sheet.csv"
    manual_csv = tmp_path / "manual-entry.csv"
    _write_manual_csv(manual_csv, [{"poster_uuid": str(PID), "count_actual": ""}])
    monkeypatch.setattr(mod, "DEFAULT_MANUAL_CSV", manual_csv)

    _install_split_sheet_cli(monkeypatch, out_path, [_db_row(id=PID)])

    assert mod.main() == 0
    assert _read_sheet(out_path) == []


def test_main_passes_the_counted_set_of_this_very_run_not_a_constant(
    monkeypatch, tmp_path: Path
) -> None:
    """🔴 ตัวฆ่า mutation ที่ *คงอาร์กิวเมนต์ไว้* แต่ส่งค่าคงที่ที่ผ่านด่านเสมอ (เช่น
    `set()` ว่าง หรือเซตคงที่) — เทสก่อนหน้าที่พิสูจน์แค่ "แถวถูกกรอง" จับ mutation
    แบบนี้ไม่ได้เสมอไป (บทเรียนเดียวกับ `test_main_checks_the_database_url_of_this_
    very_run` ของ G5) ตัวนี้ล็อกตรง ๆ ว่า **ค่าที่ `build_sheet_rows()` ได้รับคือผลจริง
    ของ `load_counted_parent_ids()` ในรอบนั้น** ไม่ใช่ค่าคงที่
    """
    out_path = tmp_path / "split-sheet.csv"
    manual_csv = tmp_path / "manual-entry.csv"
    _write_manual_csv(manual_csv, [{"poster_uuid": str(PID2), "count_actual": "3"}])
    monkeypatch.setattr(mod, "DEFAULT_MANUAL_CSV", manual_csv)

    seen: list[set | None] = []
    real_build_sheet_rows = mod.build_sheet_rows

    def spy(*args: object, **kwargs: object) -> list[dict[str, str]]:
        seen.append(kwargs.get("counted_parent_ids"))
        return real_build_sheet_rows(*args, **kwargs)

    monkeypatch.setattr(mod, "build_sheet_rows", spy)
    _install_split_sheet_cli(
        monkeypatch, out_path, [_db_row(id=PID), _db_row(id=PID2, title="Another")]
    )

    assert mod.main() == 0
    assert seen == [{PID2}]


def test_a_counted_poster_still_reaches_the_written_sheet(
    monkeypatch, tmp_path: Path
) -> None:
    """positive control ของทั้ง §main() — ถ้าไม่มีตัวนี้ ชุดข้างบนเขียวได้ด้วย `main()`
    ที่ปฏิเสธทุกใบเสมอ (รูปเดียวกับ `test_a_dev_url_that_passes_the_guard_still_
    reaches_the_write` ของ INF-21 G5) — ยืนยันว่าใบที่นับแล้วจริงยังถูกเขียนลงใบงานจริง
    """
    out_path = tmp_path / "split-sheet.csv"
    manual_csv = tmp_path / "manual-entry.csv"
    _write_manual_csv(manual_csv, [{"poster_uuid": str(PID), "count_actual": "2"}])
    monkeypatch.setattr(mod, "DEFAULT_MANUAL_CSV", manual_csv)

    _install_split_sheet_cli(monkeypatch, out_path, [_db_row(id=PID)])

    assert mod.main() == 0
    rows = _read_sheet(out_path)
    assert len(rows) == 1
    assert rows[0]["parent_poster_uuid"] == str(PID)


# --------------------------------------------------------------------------
# main() — จุดต่อของ next_piece_by_parent เข้า build_sheet_rows() (INF-25 · AC-8)
# --------------------------------------------------------------------------
#
# 🔴 ทรงเดียวกับ `test_main_passes_the_counted_set_of_this_very_run_not_a_constant`
# ข้างบน — ตัวสำคัญที่สุดตาม AC-8 ของ INF-25 คือมูลค่าของ `piece_no` ต้องมาจาก
# `load_from_db()` ของรอบนั้นจริง ไม่ใช่ `{}`/ค่าคงที่ที่ทำให้ทุกพ่อได้ 2 เสมอ


def test_main_passes_the_next_piece_of_this_very_run_not_a_constant(
    monkeypatch, tmp_path: Path
) -> None:
    """🔴 ตัวฆ่า mutation ที่ *คงอาร์กิวเมนต์ไว้* แต่ส่งค่าคงที่ที่ผ่านด่านเสมอ
    (เช่น `{}` ว่างเปล่า) — ต้องพิสูจน์ว่าค่าที่ `build_sheet_rows()` ได้รับคือผลจริง
    ของ `load_from_db()` ในรอบนั้น ไม่ใช่ค่าคงที่
    """
    out_path = tmp_path / "split-sheet.csv"
    manual_csv = tmp_path / "manual-entry.csv"
    _write_manual_csv(manual_csv, [{"poster_uuid": str(PID), "count_actual": "9"}])
    monkeypatch.setattr(mod, "DEFAULT_MANUAL_CSV", manual_csv)

    seen: list[dict | None] = []
    real_build_sheet_rows = mod.build_sheet_rows

    def spy(*args: object, **kwargs: object) -> list[dict[str, str]]:
        seen.append(kwargs.get("next_piece_by_parent"))
        return real_build_sheet_rows(*args, **kwargs)

    monkeypatch.setattr(mod, "build_sheet_rows", spy)
    _install_split_sheet_cli(
        monkeypatch,
        out_path,
        [_db_row(id=PID)],
        next_piece_by_parent={PID: 6},
    )

    assert mod.main() == 0
    assert seen == [{PID: 6}]


def test_main_writes_the_next_piece_value_into_the_sheet(
    monkeypatch, tmp_path: Path
) -> None:
    """positive control — ค่า piece_no ที่ main() ส่งเข้าไปจริงต้องลงไปอยู่ในไฟล์"""
    out_path = tmp_path / "split-sheet.csv"
    manual_csv = tmp_path / "manual-entry.csv"
    _write_manual_csv(manual_csv, [{"poster_uuid": str(PID), "count_actual": "9"}])
    monkeypatch.setattr(mod, "DEFAULT_MANUAL_CSV", manual_csv)

    _install_split_sheet_cli(
        monkeypatch, out_path, [_db_row(id=PID)], next_piece_by_parent={PID: 6}
    )

    assert mod.main() == 0
    rows = _read_sheet(out_path)
    assert len(rows) == 1
    assert rows[0]["piece_no"] == "6"


# --------------------------------------------------------------------------
# load_from_db() — ตัวฆ่า mutation M12 (รอบแก้ที่ 1 ของ code-critic)
# --------------------------------------------------------------------------
#
# 🔴 เทสทั้งหมดข้างบนของไฟล์นี้ fake `load_from_db()` ทิ้ง (`_install_split_sheet_cli`)
# ไม่มีตัวไหนเดิน SQL จริงของฟังก์ชันนี้เลย — `test_the_same_parent_can_be_split_
# across_four_real_runs` ของ `test_split_entry.py` ก็คำนวณ `max(taken)+1` เองในเทส
# ไม่เคยเรียกฟังก์ชันนี้จริง ⇒ สูตร `max_piece + 1` ไม่มีเทสตัวไหนแตะเลยสักตัว


class _SessionCtx:
    def __init__(self, session: object) -> None:
        self._session = session

    async def __aenter__(self) -> object:
        return self._session

    async def __aexit__(self, *exc_info: object) -> bool:
        return False


async def test_load_from_db_computes_max_plus_one_for_a_parent_with_children(
    db_session: AsyncSession, monkeypatch
) -> None:
    """🔴 ตัวฆ่า mutation M12 ตรง ๆ — `max_piece + 1` → `max_piece` เฉย ๆ ต้องแดง"""
    parent = Poster(
        title="The Matrix",
        price=Decimal("999.00"),
        condition_grade=PosterCondition.very_fine,
        is_unique=False,
    )
    db_session.add(parent)
    await db_session.flush()

    child = Poster(
        title="The Matrix", price=Decimal("500"), condition_grade=PosterCondition.mint
    )
    db_session.add(child)
    await db_session.flush()
    db_session.add(
        PosterSplit(
            child_poster_id=child.id,
            parent_poster_id=parent.id,
            piece_no=3,
            reviewed_by="chanothai",
            reviewed_at=datetime(2026, 8, 1, tzinfo=UTC),
            source="split-entry.csv",
            reason="รอบก่อนหน้า",
        )
    )
    await db_session.flush()

    import app.core.database as db_module

    monkeypatch.setattr(
        db_module, "async_session_maker", lambda: _SessionCtx(db_session)
    )

    _posters, _urls, next_piece_by_parent = await mod.load_from_db()

    assert next_piece_by_parent[parent.id] == 4  # max(3) + 1 — ไม่ใช่ 3 เฉย ๆ


async def test_load_from_db_omits_parents_with_no_children_from_the_map(
    db_session: AsyncSession, monkeypatch
) -> None:
    """ด้านที่ต้องไม่พัง — พ่อที่ยังไม่มีลูกเลยต้องไม่อยู่ใน dict (default = 2 อยู่ที่
    `build_sheet_rows()` ไม่ใช่ที่นี่)
    """
    parent = Poster(
        title="No Children Yet",
        price=Decimal("500.00"),
        condition_grade=PosterCondition.fine,
        is_unique=False,
    )
    db_session.add(parent)
    await db_session.flush()

    import app.core.database as db_module

    monkeypatch.setattr(
        db_module, "async_session_maker", lambda: _SessionCtx(db_session)
    )

    _posters, _urls, next_piece_by_parent = await mod.load_from_db()

    assert parent.id not in next_piece_by_parent


async def test_load_from_db_scopes_max_piece_per_parent(
    db_session: AsyncSession, monkeypatch
) -> None:
    """piece_no ของพ่อคนหนึ่งไม่ปนกับอีกคน — max ต้องคิดแยกต่อ parent_poster_id"""
    parent_a = Poster(
        title="Parent A",
        price=Decimal("100"),
        condition_grade=PosterCondition.mint,
        is_unique=False,
    )
    parent_b = Poster(
        title="Parent B",
        price=Decimal("200"),
        condition_grade=PosterCondition.mint,
        is_unique=False,
    )
    db_session.add_all([parent_a, parent_b])
    await db_session.flush()

    child_a = Poster(
        title="Parent A", price=Decimal("100"), condition_grade=PosterCondition.mint
    )
    child_b = Poster(
        title="Parent B", price=Decimal("200"), condition_grade=PosterCondition.mint
    )
    db_session.add_all([child_a, child_b])
    await db_session.flush()
    db_session.add_all(
        [
            PosterSplit(
                child_poster_id=child_a.id,
                parent_poster_id=parent_a.id,
                piece_no=2,
                reviewed_by="chanothai",
                reviewed_at=datetime(2026, 8, 1, tzinfo=UTC),
                source="split-entry.csv",
                reason="A",
            ),
            PosterSplit(
                child_poster_id=child_b.id,
                parent_poster_id=parent_b.id,
                piece_no=7,
                reviewed_by="chanothai",
                reviewed_at=datetime(2026, 8, 1, tzinfo=UTC),
                source="split-entry.csv",
                reason="B",
            ),
        ]
    )
    await db_session.flush()

    import app.core.database as db_module

    monkeypatch.setattr(
        db_module, "async_session_maker", lambda: _SessionCtx(db_session)
    )

    _posters, _urls, next_piece_by_parent = await mod.load_from_db()

    assert next_piece_by_parent[parent_a.id] == 3
    assert next_piece_by_parent[parent_b.id] == 8
