"""Unit tests ของ `scripts/seed/make_reference_sheet.py` — ADR-0014 Amendment 3

จุดสำคัญที่สุดที่ต้องล็อก (AC-7): สคริปต์นี้ **ห้ามกรอก `reference_url`/`reference_note`
ให้** ถ้าเครื่องกรอกสองคอลัมน์นี้ = เครื่องตัดสินแทนคนว่าเจอแหล่งอ้างอิงหรือไม่
ซึ่ง ADR-0014 D7 ห้ามไว้ตลอดกาล
"""

from __future__ import annotations

import ast
import inspect
import uuid

import pytest

from app.models.enums import VerificationStatus
from scripts.seed import make_reference_sheet as mod
from scripts.seed.make_reference_sheet import (
    build_sheet_rows,
    load_previous_notes,
)
from scripts.seed.reference_entry import (
    DERIVED_FIELDS,
    NULL_ONLY_FIELDS,
    REFERENCE_SHEET_COLUMNS,
)

PID = uuid.UUID("11111111-1111-1111-1111-111111111111")
PID2 = uuid.UUID("22222222-2222-2222-2222-222222222222")
URL = "http://www.impawards.com/2021/no_time_to_die_ver15.html"

HUMAN_COLUMNS = ("reference_url", "reference_note")


def _db_row(**over: object) -> dict:
    row: dict = {
        "id": PID,
        "title": "Some Poster",
        **{name: None for name in NULL_ONLY_FIELDS},
    }
    row.update(over)
    return row


# --------------------------------------------------------------------------
# AC-7 — เครื่องห้ามกรอกช่องของคน
# --------------------------------------------------------------------------


def test_the_two_human_columns_are_always_left_empty() -> None:
    """🔴 กฎที่สำคัญที่สุดของสคริปต์นี้ (ADR-0014 D7)"""
    rows = build_sheet_rows(
        [_db_row(), _db_row(id=PID2, title="Another")],
        {},
        {str(PID): URL},
        include_complete=True,
    )
    assert len(rows) == 2
    assert all(r["reference_url"] == "" for r in rows)
    assert all(r["reference_note"] == "" for r in rows)


def test_generator_never_writes_into_the_two_human_columns() -> None:
    """ล็อกที่ระดับซอร์ส — ถ้ามีใครเพิ่ม flag ให้เติม `reference_url` อัตโนมัติ
    (หรือยัดค่าจาก `previous_note` ลงไปให้) ต้องแดงทันที

    closed-world: `seen` ต้องครบทั้งสองคอลัมน์ ไม่งั้นเทสจะผ่านฟรีเมื่อมีใครลบ
    คอลัมน์ออกจาก `build_sheet_rows()` ไปเฉย ๆ (แบบเดียวกับเทสของ `make_manual_sheet`)
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


def test_the_sheet_has_no_status_column_for_anyone_to_fill() -> None:
    """AC-3 · D22 — `verification_status` เป็นค่า derive ช่องให้กรอกเองจะกลายเป็น
    แหล่งความจริงที่สองทันที"""
    rows = build_sheet_rows([_db_row()], {}, {}, include_complete=True)
    assert tuple(rows[0]) == REFERENCE_SHEET_COLUMNS
    assert set(DERIVED_FIELDS).isdisjoint(rows[0])


def test_generator_never_reaches_for_the_current_time() -> None:
    source = ast.unparse(ast.parse(inspect.getsource(mod)))
    for forbidden in ("now(", "today(", "utcnow("):
        assert forbidden not in source, f"พบ {forbidden} ในซอร์ส"


# --------------------------------------------------------------------------
# D28 — previous_note ยกมาดิบ ๆ
# --------------------------------------------------------------------------


def test_previous_note_is_carried_over_verbatim() -> None:
    """🔴 D28 — ยกทั้งก้อน ห้ามแยกว่าท่อนไหนเป็น URL ท่อนไหนเป็นเหตุผล"""
    messy = "ไม่เจอวาเรียนต์นี้ ดู http://www.impawards.com/2021/x.html แทน"
    rows = build_sheet_rows(
        [_db_row(), _db_row(id=PID2, title="Another")],
        {},
        {str(PID): URL, str(PID2): messy},
        include_complete=True,
    )
    by_id = {r["poster_uuid"]: r for r in rows}
    assert by_id[str(PID)]["previous_note"] == URL
    assert by_id[str(PID2)]["previous_note"] == messy


def test_a_poster_without_a_previous_note_gets_an_empty_cell() -> None:
    rows = build_sheet_rows([_db_row()], {}, {}, include_complete=True)
    assert rows[0]["previous_note"] == ""


def test_previous_notes_are_read_from_the_manual_sheet(tmp_path) -> None:
    path = tmp_path / "manual-entry.csv"
    path.write_text(
        f"poster_uuid,title,note\n{PID},A,{URL}\n{PID2},B,\n",
        encoding="utf-8",
    )
    notes, problem = load_previous_notes(path)
    assert problem is None
    assert notes == {str(PID): URL}


def test_a_missing_manual_sheet_warns_instead_of_failing(tmp_path) -> None:
    """🔴 `manual-entry.csv` อยู่ใน `.gitignore` — การไม่มีเป็นสถานะปกติ"""
    notes, problem = load_previous_notes(tmp_path / "ไม่มีไฟล์นี้.csv")
    assert notes == {}
    assert problem and "ไม่มีไฟล์นี้.csv" in problem


def test_a_manual_sheet_without_the_note_column_warns_instead_of_failing(
    tmp_path,
) -> None:
    path = tmp_path / "manual-entry.csv"
    path.write_text(f"poster_uuid,title\n{PID},A\n", encoding="utf-8")
    notes, problem = load_previous_notes(path)
    assert notes == {}
    assert problem and "note" in problem


def test_the_sheet_is_still_built_when_there_are_no_previous_notes() -> None:
    rows = build_sheet_rows([_db_row()], {}, {}, include_complete=True)
    assert len(rows) == 1


# --------------------------------------------------------------------------
# ใบไหนเข้าใบงาน
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "existing",
    [
        {"reference_url": URL},
        {"reference_note": "ไม่เจอ"},
        {"verification_status": VerificationStatus.REFERENCE_FOUND},
    ],
)
def test_rows_that_the_applier_would_skip_are_dropped_unless_all_is_asked(
    existing: dict,
) -> None:
    """D29 — ใบที่ไม่ NULL ครบทั้งสามถูกข้ามตอน apply อยู่แล้ว การใส่มาในใบงาน
    คือการเชิญให้คนกรอกสิ่งที่ไม่มีวันถูกเขียน"""
    row = _db_row(**existing)
    assert build_sheet_rows([row], {}, {}, include_complete=False) == []
    assert len(build_sheet_rows([row], {}, {}, include_complete=True)) == 1


def test_untouched_rows_are_included_by_default() -> None:
    assert len(build_sheet_rows([_db_row()], {}, {}, include_complete=False)) == 1


def test_rows_with_a_previous_note_sort_first() -> None:
    """แถวที่คนก๊อปได้ทันทีขึ้นก่อน — หลักเดียวกับ STATUS_ORDER ของ make_review_sheet"""
    rows = build_sheet_rows(
        [_db_row(id=PID, title="AAA"), _db_row(id=PID2, title="ZZZ")],
        {},
        {str(PID2): URL},
        include_complete=False,
    )
    assert [r["poster_uuid"] for r in rows] == [str(PID2), str(PID)]


def test_image_url_comes_from_the_public_url_map_only() -> None:
    """ADR-0006 D5 — key ที่ไม่ public ถูกกรองทิ้งก่อนถึง build_media_url()"""
    rows = build_sheet_rows(
        [_db_row(), _db_row(id=PID2, title="Another")],
        {PID: "https://cdn.invalid/a.jpg"},
        {},
        include_complete=True,
    )
    by_id = {r["poster_uuid"]: r for r in rows}
    assert by_id[str(PID)]["image_url"] == "https://cdn.invalid/a.jpg"
    assert by_id[str(PID2)]["image_url"] == ""
