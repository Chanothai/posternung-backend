"""Unit tests ของ `scripts/seed/make_correction_sheet.py` — INF-21 (AC-1)

จุดสำคัญที่สุดที่ต้องล็อก: สคริปต์นี้ **ห้ามกรอกช่องของคนให้** ทั้งค่าใหม่และเหตุผล
· เครื่องที่เสนอเกรดใหม่ให้คนเซ็นคือเครื่องที่ตัดสินสภาพสินค้าแทนคน (ADR-0009 D6 ·
ADR-0014 D7) และเหตุผลที่เครื่องเขียนให้ไม่ใช่เหตุผล — มันคือข้อความที่ทำให้ audit
*ดูเหมือน* มีคนรู้เห็นทั้งที่ไม่มี (ADR-0010 A-D2 ข้อ 2)
"""

from __future__ import annotations

import ast
import inspect
import uuid

from app.models.enums import PosterCondition
from scripts.seed import make_correction_sheet as mod
from scripts.seed.correction_entry import (
    CORRECTION_SHEET_COLUMNS,
    CURRENT_COLUMNS,
    REASON_COLUMNS,
    WRITABLE_FIELDS,
)
from scripts.seed.make_correction_sheet import HUMAN_COLUMNS, build_sheet_rows

PID = uuid.UUID("11111111-1111-1111-1111-111111111111")
PID2 = uuid.UUID("22222222-2222-2222-2222-222222222222")


def _db_row(**over: object) -> dict:
    row: dict = {
        "id": PID,
        "title": "Some Poster",
        "condition_grade": PosterCondition.near_mint,
        "is_unique": True,
    }
    row.update(over)
    return row


# --------------------------------------------------------------------------
# เครื่องห้ามกรอกช่องของคน
# --------------------------------------------------------------------------


def test_the_four_human_columns_are_always_left_empty() -> None:
    """🔴 กฎที่สำคัญที่สุดของสคริปต์นี้"""
    rows = build_sheet_rows(
        [_db_row(), _db_row(id=PID2, title="Another")], {}, include_all=True
    )
    assert len(rows) == 2
    for row in rows:
        for column in HUMAN_COLUMNS:
            assert row[column] == "", column


def test_generator_never_writes_into_the_four_human_columns() -> None:
    """ล็อกที่ระดับซอร์ส — ถ้ามีใครเพิ่ม flag ให้เติมเกรดที่ "น่าจะถูก" หรือเติม
    เหตุผลสำเร็จรูปให้ ต้องแดงทันที

    closed-world: `seen` ต้องครบทั้งสี่คอลัมน์ ไม่งั้นเทสจะผ่านฟรีเมื่อมีใครลบ
    คอลัมน์ออกจาก `build_sheet_rows()` ไปเฉย ๆ (แบบเดียวกับเทสของเส้นที่ 4)
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


def test_the_human_columns_are_the_value_and_the_reason_of_every_writable_field() -> (
    None
):
    """ประกอบจากทูเพิลของเส้นที่ 5 ไม่ใช่รายชื่อที่พิมพ์ไว้ — ฟิลด์ที่เพิ่มเข้า
    allowlist วันหน้าจะถูกล็อกทันทีโดยไม่ต้องมีใครนึกได้ว่าต้องมาต่อรายชื่อ"""
    assert set(HUMAN_COLUMNS) == set(WRITABLE_FIELDS) | set(REASON_COLUMNS)
    assert set(HUMAN_COLUMNS).isdisjoint(CURRENT_COLUMNS)


def test_generator_never_reaches_for_the_current_time() -> None:
    source = ast.unparse(ast.parse(inspect.getsource(mod)))
    for forbidden in ("now(", "today(", "utcnow("):
        assert forbidden not in source, f"พบ {forbidden} ในซอร์ส"


# --------------------------------------------------------------------------
# ช่องช่วยจำ `current_*`
# --------------------------------------------------------------------------


def test_the_current_columns_show_what_is_about_to_be_overwritten() -> None:
    (row,) = build_sheet_rows([_db_row()], {}, include_all=True)
    assert tuple(row) == CORRECTION_SHEET_COLUMNS
    assert row["current_condition_grade"] == "near_mint"
    assert row["current_is_unique"] == "True"


def test_a_row_that_is_not_unique_is_rendered_as_false_not_blank() -> None:
    """🔴 `False` กับช่องว่างต้องแยกออกจากกัน — ช่องว่างอ่านได้ว่า *ไม่รู้*
    ซึ่งเป็นสภาพที่ `is_unique` (NOT NULL) ไม่มีวันเป็น"""
    (row,) = build_sheet_rows([_db_row(is_unique=False)], {}, include_all=True)
    assert row["current_is_unique"] == "False"


def test_image_url_comes_from_the_public_url_map_only() -> None:
    """ADR-0006 D5 — key ที่ไม่ public ถูกกรองทิ้งก่อนถึง build_media_url()"""
    rows = build_sheet_rows(
        [_db_row(), _db_row(id=PID2, title="Another")],
        {PID: "https://cdn.invalid/a.jpg"},
        include_all=True,
    )
    by_id = {r["poster_uuid"]: r for r in rows}
    assert by_id[str(PID)]["image_url"] == "https://cdn.invalid/a.jpg"
    assert by_id[str(PID2)]["image_url"] == ""


# --------------------------------------------------------------------------
# ใบไหนเข้าใบงาน
# --------------------------------------------------------------------------


def test_a_poster_without_a_grade_is_dropped_by_default() -> None:
    """เส้นนี้ *แก้* ไม่ใช่ *เติม* — `correction_entry.py` ข้ามใบพวกนี้อยู่แล้ว
    การใส่มาในใบงานคือการเชิญให้คนกรอกสิ่งที่ไม่มีวันถูกเขียน"""
    row = _db_row(condition_grade=None)
    assert build_sheet_rows([row], {}, include_all=False) == []
    assert len(build_sheet_rows([row], {}, include_all=True)) == 1


def test_a_poster_with_a_grade_is_included_by_default() -> None:
    assert len(build_sheet_rows([_db_row()], {}, include_all=False)) == 1


def test_rows_that_break_one_row_one_piece_sort_first() -> None:
    """ADR-0019 บอกไว้แล้วว่าแถว `is_unique = false` คือแถวที่รู้อยู่แล้วว่าไม่ตรง
    กับมติ D1 — เป็นแถวที่คนลงมือได้ทันที จึงขึ้นบนสุด"""
    rows = build_sheet_rows(
        [
            _db_row(id=PID, title="AAA"),
            _db_row(id=PID2, title="ZZZ", is_unique=False),
        ],
        {},
        include_all=False,
    )
    assert [r["poster_uuid"] for r in rows] == [str(PID2), str(PID)]
