"""Unit tests ของ `scripts/seed/split_entry.py` — เส้นที่ 6 (ADR-0024 · INF-22/INF-25)

🔴 **AC-3 ของ INF-22 บังคับสามชั้นเพื่อพิสูจน์ว่าแถวพ่อไม่ถูกแตะเลย — ทั้งสามชั้นอยู่ที่นี่**

| ชั้น | ตรวจอะไร | เทสในไฟล์นี้ |
|---|---|---|
| 1. ระดับซอร์ส (AST) | ไม่มี `ast.Attribute` ชื่อ `is_unique` เลย · ไม่มี `ast.Call` ชื่อ `update` เลย | §ชั้น 1 |
| 2. ระดับ runtime | session ปลอมพิสูจน์ว่า `run()` ไม่เคย `execute()` statement ชนิด `Update` และแถวลูกที่ `add()` เข้าไปมีแค่ 4 attribute ที่ตั้งใจ (`id`/`title`/`price`/`condition_grade`) | §ชั้น 2 |
| 3. อ่านค่าพ่อกลับมาเทียบ | สร้างพ่อจริงใน `db_session`, รัน `run()` เต็ม (`--commit` จำลอง), query กลับมาว่า `price`/`status`/`published_at`/`needs_review`/`condition_grade` ไม่ขยับ | §ชั้น 3 |

🔴 **INF-25 (ADR-0024 A-D5 · A-D6) เพิ่มคีย์ `piece_no` และเปลี่ยนพฤติกรรมชนคีย์จาก
"ปฏิเสธทั้งไฟล์" เป็น "ข้ามเฉพาะแถว + รายงานดัง"** — §ชั้น 4 เดิม (รันใบเดิมซ้ำ) แก้ให้
ตรงพฤติกรรมใหม่ เพิ่ม §ชั้น 5 (AC-2: แตกพ่อเดียวกันหลายรอบจริง) และ §ชั้น 6 (AC-3:
ตัดด่านชั้นสคริปต์ออกจากสายแล้วชน DB จริง)

ส่วนที่เหลือ (parse/plan) เป็นฟังก์ชัน pure ทั้งหมด ไม่ต้องมี DB — ตาม
ship-backend-change §3
"""

from __future__ import annotations

import argparse
import ast
import csv
import inspect
import sys
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.dml import Update

from app.models.enums import PosterCondition, PosterStatus
from app.models.poster import Poster
from app.models.poster_split import PosterSplit
from scripts.seed import manual_entry as manual_mod
from scripts.seed import split_entry as mod
from scripts.seed.correction_entry import DEFAULT_CORRECTION_CSV
from scripts.seed.manual_entry import DEFAULT_MANUAL_CSV, MANUAL_SHEET_COLUMNS
from scripts.seed.reference_entry import DEFAULT_REFERENCE_CSV
from scripts.seed.split_entry import (
    SPLIT_SHEET_COLUMNS,
    ParentState,
    PlannedSplit,
    PrecheckError,
    RowAction,
    SplitPayload,
    SplitRow,
    assert_own_sheet,
    assert_schema_ready,
    field_specs,
    parse_rows,
    plan_writes,
)

PARENT = uuid.UUID("11111111-1111-1111-1111-111111111111")
PARENT2 = uuid.UUID("22222222-2222-2222-2222-222222222222")


def _raw(**over: str) -> dict[str, str]:
    row = {
        "parent_poster_uuid": str(PARENT),
        "parent_title": "The Matrix",
        "parent_image_url": "https://example.invalid/a.jpg",
        "piece_no": "2",
        "condition_grade": "very_good",
        "price": "500",
        "reason": "แยกใบที่สองออกมาเพราะต่างเกรดกัน",
    }
    row.update(over)
    return row


# --------------------------------------------------------------------------
# field_specs — condition_grade / price
# --------------------------------------------------------------------------


def test_condition_grade_rejects_wrong_case() -> None:
    with pytest.raises(ValueError, match="ตัวพิมพ์ไม่ตรง"):
        field_specs()["condition_grade"].parse("Very_Good")


def test_condition_grade_accepts_exact_lowercase() -> None:
    assert field_specs()["condition_grade"].parse("mint") is PosterCondition.mint


def test_price_rejects_negative() -> None:
    with pytest.raises(ValueError, match="ติดลบ"):
        field_specs()["price"].parse("-1")


def test_price_rejects_non_numeric() -> None:
    with pytest.raises(ValueError, match="ไม่ใช่ตัวเลข"):
        field_specs()["price"].parse("abc")


def test_price_rejects_more_than_two_decimals() -> None:
    with pytest.raises(ValueError, match="ทศนิยมเกิน"):
        field_specs()["price"].parse("500.123")


def test_price_accepts_two_decimals() -> None:
    assert field_specs()["price"].parse("500.50") == Decimal("500.50")


def test_price_rejects_over_the_column_ceiling() -> None:
    with pytest.raises(ValueError, match="เกินเพดาน"):
        field_specs()["price"].parse("99999999999")


# --------------------------------------------------------------------------
# _parse_piece_no — ADR-0024 A-D5 (INF-25)
# --------------------------------------------------------------------------


def test_piece_no_accepts_two() -> None:
    assert mod._parse_piece_no("2") == 2


def test_piece_no_rejects_one() -> None:
    with pytest.raises(ValueError, match=">= 2"):
        mod._parse_piece_no("1")


def test_piece_no_rejects_zero() -> None:
    with pytest.raises(ValueError, match=">= 2"):
        mod._parse_piece_no("0")


def test_piece_no_rejects_non_integer() -> None:
    with pytest.raises(ValueError, match="ไม่ใช่จำนวนเต็ม"):
        mod._parse_piece_no("two")


def test_piece_no_accepts_larger_values() -> None:
    assert mod._parse_piece_no("11") == 11


# --------------------------------------------------------------------------
# parse_rows — pure, fail-closed ทั้งไฟล์
# --------------------------------------------------------------------------


def test_a_fully_filled_row_parses_into_a_payload() -> None:
    (row,) = parse_rows([_raw()])
    assert row.parent_poster_uuid == PARENT
    assert row.payload == SplitPayload(
        condition_grade=PosterCondition.very_good,
        price=Decimal("500"),
        reason="แยกใบที่สองออกมาเพราะต่างเกรดกัน",
        piece_no=2,
    )


def test_a_fully_blank_row_is_normal_not_an_error() -> None:
    """ยังไม่ได้กรอก — สถานะปกติของใบงานที่ทำไปครึ่งเดียว"""
    (row,) = parse_rows([_raw(condition_grade="", price="", reason="")])
    assert row.payload is None


def test_a_blank_row_does_not_require_a_valid_piece_no() -> None:
    """🔴 แถวว่างไม่ต้องมี piece_no ที่ถูกต้อง — ใบงานที่เพิ่ง generate ใหม่ยังไม่มีคน
    กรอกอะไรเลย piece_no ของแถวนั้นก็ไม่ควรถูกบังคับให้ผ่านด่านรูปแบบ
    """
    (row,) = parse_rows(
        [_raw(condition_grade="", price="", reason="", piece_no="not-a-number")]
    )
    assert row.payload is None


@pytest.mark.parametrize(
    "over",
    [
        {"condition_grade": "", "price": "500", "reason": "why"},
        {"condition_grade": "mint", "price": "", "reason": "why"},
        {"condition_grade": "mint", "price": "500", "reason": ""},
        {"condition_grade": "mint", "price": "", "reason": ""},
    ],
    ids=["missing_grade", "missing_price", "missing_reason", "missing_two"],
)
def test_partially_filled_rows_reject_the_whole_file(over: dict[str, str]) -> None:
    """🔴 เส้นนี้ไม่มีแนวคิด 'เติมทีหลัง' — ต่างจากเส้นที่ 3 ตรง ๆ"""
    with pytest.raises(PrecheckError, match="กรอกมาไม่ครบ"):
        parse_rows([_raw(**over)])


def test_bad_uuid_rejects_the_whole_file() -> None:
    with pytest.raises(PrecheckError, match="ไม่ใช่ UUID"):
        parse_rows([_raw(parent_poster_uuid="not-a-uuid")])


def test_duplicate_parent_uuid_rejects_the_whole_file() -> None:
    with pytest.raises(PrecheckError, match="ซ้ำกับแถวก่อนหน้า"):
        parse_rows([_raw(), _raw(reason="อีกเหตุผลหนึ่ง")])


def test_bad_grade_rejects_the_whole_file() -> None:
    with pytest.raises(PrecheckError, match="condition_grade"):
        parse_rows([_raw(condition_grade="not-a-grade")])


def test_bad_price_rejects_the_whole_file() -> None:
    with pytest.raises(PrecheckError, match="price"):
        parse_rows([_raw(price="not-a-number")])


def test_bad_piece_no_rejects_the_whole_file_when_the_row_is_filled() -> None:
    """🔴 ต่างจากแถวว่าง — เมื่อสามช่องของคนกรอกครบแล้ว piece_no ต้องถูกด้วย"""
    with pytest.raises(PrecheckError, match="piece_no"):
        parse_rows([_raw(piece_no="1")])


def test_one_good_row_does_not_save_a_bad_row_next_to_it() -> None:
    """fail-closed แปลว่าทั้งไฟล์ — ไม่ใช่แค่แถวที่ผิด"""
    with pytest.raises(PrecheckError):
        parse_rows(
            [
                _raw(parent_poster_uuid=str(PARENT)),
                _raw(parent_poster_uuid=str(PARENT2), price="not-a-number"),
            ]
        )


# --------------------------------------------------------------------------
# plan_writes — pure, รับสถานะพ่อ/piece_no ที่ใช้ไปแล้ว/ผลนับเข้ามา
# --------------------------------------------------------------------------


def _row(**over: object) -> SplitRow:
    base: dict[str, object] = {
        "lineno": 2,
        "parent_poster_uuid": PARENT,
        "payload": SplitPayload(
            condition_grade=PosterCondition.very_good,
            price=Decimal("500"),
            reason="เหตุผล",
            piece_no=2,
        ),
    }
    base.update(over)
    return SplitRow(**base)  # type: ignore[arg-type]


def _graded_parent(**over: object) -> ParentState:
    base: dict[str, object] = {
        "title": "The Matrix",
        "is_unique": False,
        "condition_grade": PosterCondition.very_good,
    }
    base.update(over)
    return ParentState(**base)  # type: ignore[arg-type]


def test_blank_row_is_skipped_before_touching_parents() -> None:
    (plan,) = plan_writes([_row(payload=None)], {}, {}, {})
    assert plan.action is RowAction.SKIP_BLANK


def test_parent_not_in_db_is_skipped_not_an_error() -> None:
    (plan,) = plan_writes([_row()], {}, {}, {})
    assert plan.action is RowAction.SKIP_NOT_FOUND


def test_parent_already_unique_is_skipped() -> None:
    """มีคนแก้ผ่านเส้นที่ 5 ไปแล้วระหว่างที่ใบงานนี้ยังค้างอยู่"""
    parents = {PARENT: _graded_parent(is_unique=True)}
    (plan,) = plan_writes([_row()], parents, {}, {})
    assert plan.action is RowAction.SKIP_NOT_ELIGIBLE
    assert plan.parent_title == "The Matrix"


def test_parent_with_no_grade_is_skipped() -> None:
    """🔴 AC-5 — กันกรอบไฟของ BL-82 หลุดเข้ามาจากใบงานที่แก้มือ"""
    parents = {PARENT: _graded_parent(condition_grade=None)}
    (plan,) = plan_writes([_row()], parents, {}, {})
    assert plan.action is RowAction.SKIP_PARENT_UNGRADED
    assert plan.parent_title == "The Matrix"


def test_a_taken_piece_no_is_skipped_not_the_whole_file() -> None:
    """🔴 ตัวฆ่า mutation หลักของ AC-4 (A-D6) — ชนคีย์ = ข้ามแถวนั้น ไม่ปฏิเสธทั้งไฟล์"""
    parents = {PARENT: _graded_parent()}
    taken = {PARENT: frozenset({2})}  # piece_no 2 ถูกใช้ไปแล้ว
    (plan,) = plan_writes([_row()], parents, taken, {PARENT: 5})
    assert plan.action is RowAction.SKIP_PIECE_TAKEN


def test_a_different_piece_no_for_the_same_parent_is_not_taken() -> None:
    """ด้านที่ต้องไม่พัง — piece_no ที่ยังไม่เคยใช้ต้องผ่านด่านนี้ไปต่อ"""
    parents = {PARENT: _graded_parent()}
    taken = {PARENT: frozenset({3, 4})}  # 2 ยังไม่เคยถูกใช้
    (plan,) = plan_writes([_row()], parents, taken, {PARENT: 5})
    assert plan.action is RowAction.WRITE


def test_taken_pieces_scoped_per_parent() -> None:
    """piece_no ที่ถูกใช้ของพ่อคนอื่นไม่เกี่ยวกับพ่อคนนี้"""
    parents = {PARENT: _graded_parent()}
    taken = {PARENT2: frozenset({2})}  # piece_no 2 ถูกใช้ แต่เป็นของพ่อคนละคน
    (plan,) = plan_writes([_row()], parents, taken, {PARENT: 5})
    assert plan.action is RowAction.WRITE


def test_no_count_at_all_is_skipped_not_an_error() -> None:
    """🔴 AC-6 — count_actual ไม่มีแถวของพ่อนี้เลยใน manual-entry.csv"""
    parents = {PARENT: _graded_parent()}
    (plan,) = plan_writes([_row()], parents, {}, {})
    assert plan.action is RowAction.SKIP_NOT_COUNTED


def test_a_none_count_value_is_skipped_not_an_error() -> None:
    """🔴 ค่าว่างใน count_actual (`None` จาก `load_count_actual_by_poster`) ก็ SKIP_NOT_COUNTED เหมือนกัน"""
    parents = {PARENT: _graded_parent()}
    (plan,) = plan_writes([_row()], parents, {}, {PARENT: None})
    assert plan.action is RowAction.SKIP_NOT_COUNTED


def test_piece_no_over_the_count_is_skipped() -> None:
    """🔴 AC-6 — piece_no 2 > count_actual 1 (ต่ำกว่าที่นับได้จริง)"""
    parents = {PARENT: _graded_parent()}
    (plan,) = plan_writes([_row()], parents, {}, {PARENT: 1})
    assert plan.action is RowAction.SKIP_OVER_COUNT
    assert plan.count_actual == 1


def test_piece_no_equal_to_the_count_is_allowed() -> None:
    """ขอบเขต — piece_no == count_actual ต้องผ่าน (สูตรคือ `piece_no <= count_actual`)"""
    parents = {PARENT: _graded_parent()}
    (plan,) = plan_writes([_row()], parents, {}, {PARENT: 2})
    assert plan.action is RowAction.WRITE


def test_eligible_parent_produces_a_write_plan() -> None:
    parents = {PARENT: _graded_parent()}
    (plan,) = plan_writes([_row()], parents, {}, {PARENT: 5})
    assert plan.action is RowAction.WRITE
    assert plan.parent_title == "The Matrix"


def test_planned_split_carries_the_original_row() -> None:
    parents = {PARENT: _graded_parent()}
    (plan,) = plan_writes([_row()], parents, {}, {PARENT: 5})
    assert isinstance(plan, PlannedSplit)
    assert plan.row.parent_poster_uuid == PARENT


def test_gate_order_ineligible_beats_ungraded() -> None:
    """ลำดับด่านต้องตรงตามแผน — SKIP_NOT_ELIGIBLE ต้องมาก่อน SKIP_PARENT_UNGRADED"""
    parents = {PARENT: ParentState(title="X", is_unique=True, condition_grade=None)}
    (plan,) = plan_writes([_row()], parents, {}, {PARENT: 5})
    assert plan.action is RowAction.SKIP_NOT_ELIGIBLE


def test_gate_order_ungraded_beats_piece_taken() -> None:
    """SKIP_PARENT_UNGRADED ต้องมาก่อน SKIP_PIECE_TAKEN"""
    parents = {PARENT: _graded_parent(condition_grade=None)}
    taken = {PARENT: frozenset({2})}
    (plan,) = plan_writes([_row()], parents, taken, {PARENT: 5})
    assert plan.action is RowAction.SKIP_PARENT_UNGRADED


def test_gate_order_piece_taken_beats_not_counted() -> None:
    """SKIP_PIECE_TAKEN ต้องมาก่อน SKIP_NOT_COUNTED/SKIP_OVER_COUNT"""
    parents = {PARENT: _graded_parent()}
    taken = {PARENT: frozenset({2})}
    (plan,) = plan_writes([_row()], parents, taken, {})
    assert plan.action is RowAction.SKIP_PIECE_TAKEN


# --------------------------------------------------------------------------
# _report() — AC-4 บังคับให้มีเทสล็อกข้อความ (ไม่ใช่แค่ล็อก action)
# --------------------------------------------------------------------------


def test_report_names_the_colliding_piece_no_and_says_the_row_was_not_created(
    capsys,
) -> None:
    """🔴 AC-4 บังคับตรง ๆ — รายงานต้องบอก `piece_no` ที่ชน และบอกว่าแถวนั้น
    **ไม่ถูกสร้าง** ให้ชัด (ราคาที่ยอมรับคือชิ้นที่ตั้งใจแตกจริงหายไปเงียบ ๆ ถ้าไม่มี
    ใครอ่านรายงาน — ต้องมีหัวข้อของตัวเองแยกจาก skip อื่น)
    """
    parents = {PARENT: _graded_parent()}
    taken = {PARENT: frozenset({2})}
    plans = plan_writes([_row()], parents, taken, {PARENT: 5})
    assert plans[0].action is RowAction.SKIP_PIECE_TAKEN

    mod._report(plans, "test-target", committed=True)
    out = capsys.readouterr().out

    assert "piece_no 2" in out
    assert "ถูกใช้ไปแล้ว" in out
    assert "ไม่ถูกสร้าง" in out


def test_report_gives_piece_taken_its_own_heading_separate_from_other_skips(
    capsys,
) -> None:
    """หัวข้อของ SKIP_PIECE_TAKEN ต้องแยกจากหัวข้ออื่น ไม่ใช่ปนกันจนหาไม่เจอ"""
    parents = {
        PARENT: _graded_parent(),
        PARENT2: _graded_parent(title="Another"),
    }
    taken = {PARENT: frozenset({2})}
    rows = [_row(), _row(parent_poster_uuid=PARENT2, lineno=3)]
    plans = plan_writes(rows, parents, taken, {PARENT: 5, PARENT2: 1})
    actions = {p.row.parent_poster_uuid: p.action for p in plans}
    assert actions[PARENT] is RowAction.SKIP_PIECE_TAKEN
    assert actions[PARENT2] is RowAction.SKIP_OVER_COUNT

    mod._report(plans, "test-target", committed=True)
    out = capsys.readouterr().out

    assert "piece_no ชนกับที่มีอยู่แล้ว" in out
    assert "piece_no เกินผลนับ" in out


def test_report_summary_line_counts_written_and_skipped_rows_correctly(
    capsys,
) -> None:
    """บรรทัดสรุปท้ายรายงาน — สร้างจริงกี่แถว ข้ามกี่แถว (item 9 ของก้อน 2)"""
    parents = {PARENT: _graded_parent()}
    taken = {PARENT: frozenset({2})}
    plans = plan_writes([_row(), _row(payload=None, lineno=3)], parents, taken, {})
    # แถวแรก SKIP_PIECE_TAKEN · แถวสอง SKIP_BLANK — ไม่มี WRITE เลย

    mod._report(plans, "test-target", committed=True)
    out = capsys.readouterr().out

    assert "สร้างจริง 0 แถว" in out
    assert "ข้ามทั้งหมด 2 แถว" in out


# --------------------------------------------------------------------------
# assert_own_sheet / assert_schema_ready
# --------------------------------------------------------------------------


def test_the_sheets_of_other_lanes_are_refused_by_name() -> None:
    for path, lane in (
        (DEFAULT_MANUAL_CSV, "เส้นที่ 3"),
        (DEFAULT_REFERENCE_CSV, "เส้นที่ 4"),
        (DEFAULT_CORRECTION_CSV, "เส้นที่ 5"),
    ):
        with pytest.raises(PrecheckError, match=lane):
            assert_own_sheet(path)


def test_our_own_sheet_passes_wherever_it_lives() -> None:
    assert_own_sheet(mod.DEFAULT_SPLIT_CSV) is None
    assert_own_sheet(mod.SEED_DIR / "some-other-name.csv") is None


def test_schema_ready_passes_when_the_table_exists() -> None:
    assert assert_schema_ready(True) is None


def test_schema_ready_refuses_when_the_table_is_missing() -> None:
    with pytest.raises(PrecheckError, match="poster_splits"):
        assert_schema_ready(False)


def test_load_count_actual_by_poster_is_the_same_object_as_lane_three_not_a_copy() -> (
    None
):
    """🔴 INF-29 ขั้นที่ 1 — ยกจาก `split_entry._load_counts()` ไปเป็นบ้านของมันเอง
    ที่ `manual_entry.py` แล้วให้เส้นที่ 5 (`correction_entry.py`) import ตัวเดียวกัน
    ด้วย ทรงเดียวกับ `_enum_parser`/`TARGETS`/`assert_target` ที่มีเทส identity อยู่แล้ว
    — สำเนาที่ drift ได้คือด่านที่หายไปครึ่งเดียวโดยไม่มีอะไรฟ้อง"""
    assert mod.load_count_actual_by_poster is manual_mod.load_count_actual_by_poster


# --------------------------------------------------------------------------
# load_count_actual_by_poster — อ่าน count_actual จาก manual-entry.csv (AC-6)
# --------------------------------------------------------------------------

_MANUAL_BLANKS = {
    "title": "",
    "image_url": "",
    "condition_grade": "",
    "year": "",
    "poster_type": "",
    "restoration_status": "",
    "tmdb_id": "",
    "width_in": "",
    "height_in": "",
    "publish": "",
    "note": "",
}


def _write_manual_csv(
    path: Path, rows: list[dict[str, str]], *, columns: tuple[str, ...] | None = None
) -> None:
    cols = columns if columns is not None else MANUAL_SHEET_COLUMNS
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(cols))
        writer.writeheader()
        for row in rows:
            full = {k: v for k, v in _MANUAL_BLANKS.items() if k in cols}
            full["poster_uuid"] = str(row.get("poster_uuid", ""))
            if "count_actual" in cols:
                full["count_actual"] = row.get("count_actual", "")
            writer.writerow(full)


def test_load_counts_raises_when_the_file_is_missing(tmp_path: Path) -> None:
    with pytest.raises(PrecheckError, match="ไม่พบใบงาน"):
        mod.load_count_actual_by_poster(tmp_path / "does-not-exist.csv")


def test_load_counts_raises_when_the_header_has_no_count_actual_column(
    tmp_path: Path,
) -> None:
    """🔴 ต่างจาก 'ยังไม่มีใครนับ' — คอลัมน์ไม่มีอยู่เลย ไม่ใช่มีอยู่แต่ว่าง"""
    path = tmp_path / "manual-entry.csv"
    columns = tuple(c for c in MANUAL_SHEET_COLUMNS if c != "count_actual")
    _write_manual_csv(path, [{"poster_uuid": str(PARENT)}], columns=columns)
    with pytest.raises(PrecheckError, match="count_actual"):
        mod.load_count_actual_by_poster(path)


def test_load_counts_returns_none_for_a_blank_value(tmp_path: Path) -> None:
    path = tmp_path / "manual-entry.csv"
    _write_manual_csv(path, [{"poster_uuid": str(PARENT), "count_actual": ""}])
    assert mod.load_count_actual_by_poster(path) == {PARENT: None}


def test_load_counts_returns_the_integer_value(tmp_path: Path) -> None:
    path = tmp_path / "manual-entry.csv"
    _write_manual_csv(path, [{"poster_uuid": str(PARENT), "count_actual": "3"}])
    assert mod.load_count_actual_by_poster(path) == {PARENT: 3}


def test_load_counts_returns_zero_as_zero_not_none(tmp_path: Path) -> None:
    """0 เป็นค่าจริง ('นับได้ 0 ชิ้น') ไม่ใช่ 'ยังไม่นับ'"""
    path = tmp_path / "manual-entry.csv"
    _write_manual_csv(path, [{"poster_uuid": str(PARENT), "count_actual": "0"}])
    assert mod.load_count_actual_by_poster(path) == {PARENT: 0}


def test_load_counts_treats_a_malformed_value_as_not_counted(tmp_path: Path) -> None:
    """รูปแบบผิด (ไม่ใช่จำนวนเต็ม ≥ 0) เป็นหน้าที่ของเส้นที่ 3 — เส้นนี้ปฏิบัติเหมือน
    ยังไม่นับ (fail-closed) แทนที่จะ raise ทั้งไฟล์
    """
    path = tmp_path / "manual-entry.csv"
    _write_manual_csv(path, [{"poster_uuid": str(PARENT), "count_actual": "-1"}])
    assert mod.load_count_actual_by_poster(path) == {PARENT: None}


def test_load_counts_skips_a_malformed_uuid_silently(tmp_path: Path) -> None:
    path = tmp_path / "manual-entry.csv"
    _write_manual_csv(path, [{"poster_uuid": "not-a-uuid", "count_actual": "3"}])
    assert mod.load_count_actual_by_poster(path) == {}


# --------------------------------------------------------------------------
# §ชั้น 1 — ระดับซอร์ส (AST)
# --------------------------------------------------------------------------


def _tree() -> ast.Module:
    return ast.parse(inspect.getsource(mod))


def _callee_name(node: ast.Call) -> str:
    func = node.func
    if isinstance(func, ast.Attribute):
        return func.attr
    if isinstance(func, ast.Name):
        return func.id
    return ""


def test_source_never_writes_is_unique_anywhere() -> None:
    """D3 — เส้นนี้ไม่เขียน `is_unique` ของใครเลย ทั้งพ่อและลูก

    🔴 ตรวจเฉพาะ `ast.Store` (เช่น `poster.is_unique = ...`) — `ParentState.is_unique`
    (field ของตัวเอง) และ `state.is_unique` (อ่านค่าเพื่อตัดสิน SKIP_NOT_ELIGIBLE)
    เป็นการ**อ่าน**ที่ตั้งใจและถูกต้องตาม D3 ไม่ใช่การเขียน — กวาดทั้งไฟล์ ไม่ใช่แค่
    ใน `run()` เพราะผิดที่ไหนในไฟล์นี้ก็ผิดหลักเดียวกัน
    """
    tree = _tree()
    written = {
        n.attr
        for n in ast.walk(tree)
        if isinstance(n, ast.Attribute) and isinstance(n.ctx, ast.Store)
    }
    # keyword ของ `Poster(...)` โดยเฉพาะ — คนละเรื่องกับ `ParentState(..., is_unique=...)`
    # ซึ่งเป็นการสร้าง dataclass ภายในของไฟล์นี้เอง ไม่ใช่การเขียนลง `posters`
    poster_kwargs = {
        kw.arg
        for n in ast.walk(tree)
        if isinstance(n, ast.Call) and _callee_name(n) == "Poster"
        for kw in n.keywords
        if kw.arg is not None
    }
    assert "is_unique" not in written
    assert "is_unique" not in poster_kwargs


def test_source_has_no_update_call_at_all() -> None:
    """ไม่มีคำสั่ง UPDATE บน `posters` เลยแม้แต่บรรทัดเดียว — เส้นนี้ INSERT อย่างเดียว"""
    calls = [
        ast.unparse(n)
        for n in ast.walk(_tree())
        if isinstance(n, ast.Call) and _callee_name(n) == "update"
    ]
    assert calls == []


def test_the_only_poster_attributes_ever_assigned_are_the_intended_four() -> None:
    """closed-world — ถ้าวันหลังมีใครเพิ่ม `poster.status = ...` เข้าไปในไฟล์นี้
    เทสนี้ต้องแดงทันที ไม่ต้องรอ mutation test มาจับ
    """
    tree = ast.parse(inspect.getsource(mod.run))
    assigned: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and isinstance(node.ctx, ast.Store):
            assigned.add(node.attr)
    # เฉพาะ attribute ที่ตั้งค่าจริงผ่าน `.attr = ` (ไม่ใช่ Poster(...) kwargs ซึ่งเป็น
    # ast.keyword ไม่ใช่ ast.Attribute) — ใน run() วันนี้ไม่มีการ setattr เลยสักบรรทัด
    # เพราะ Poster ใหม่ถูกสร้างผ่าน constructor kwargs ทั้งหมด (ดูเทส kwargs ด้านล่าง)
    assert assigned == set()


def test_the_child_poster_constructor_only_ever_receives_the_intended_four_kwargs() -> (
    None
):
    """D3/D4 — `Poster(...)` ใน `run()` ต้องมีแค่ `id`/`title`/`price`/`condition_grade`
    (piece_no ไปที่ `PosterSplit(...)` ไม่ใช่ `Poster(...)` — คนละแถวคนละตาราง)
    """
    tree = ast.parse(inspect.getsource(mod.run))
    calls = [
        n
        for n in ast.walk(tree)
        if isinstance(n, ast.Call) and _callee_name(n) == "Poster"
    ]
    assert len(calls) == 1
    kwargs = {kw.arg for kw in calls[0].keywords}
    assert kwargs == {"id", "title", "price", "condition_grade"}


def test_the_source_never_mentions_verified_at_anywhere() -> None:
    """🔴 AC-6(ข) ของ INF-29 (ADR-0027) — แถวลูกต้องเกิดพร้อม `verified_at = NULL`
    เสมอโดย**ไม่มี server_default** (ทรงเดียวกับ `published_at`) ด่านนี้กว้างกว่า
    `test_the_child_poster_constructor_only_ever_receives_the_intended_four_kwargs`
    ข้างบนหนึ่งขั้น — ไม่ใช่แค่ตรวจ kwargs ของ `Poster(...)` แต่กวาดทั้งไฟล์ว่าไม่มี
    string literal หรือ `.attr` ชื่อ `verified_at` โผล่เลยแม้แต่ที่เดียว (คำเตือน
    เดียวกับ `test_source_never_writes_is_unique_anywhere` — ผิดที่ไหนในไฟล์นี้ก็ผิด
    หลักเดียวกัน: เส้นที่ 6 ไม่มีสิทธิ์แตะมิติที่ลายเซ็นรับรอง)
    """
    tree = _tree()
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            names.add(node.value)
        elif isinstance(node, ast.Attribute):
            names.add(node.attr)
    assert "verified_at" not in names


def test_the_poster_split_constructor_receives_piece_no_from_the_payload() -> None:
    """🔴 ตัวฆ่า mutation ที่สำคัญที่สุดของ AC-8 — `piece_no` ต้องมาจาก
    `payload.piece_no` (ค่าจากไฟล์) ไม่ใช่นิพจน์อื่นที่คำนวณเอง (เช่น `len(taken)+2`)
    """
    tree = ast.parse(inspect.getsource(mod.run))
    calls = [
        n
        for n in ast.walk(tree)
        if isinstance(n, ast.Call) and _callee_name(n) == "PosterSplit"
    ]
    assert len(calls) == 1
    piece_no_kwarg = next(kw for kw in calls[0].keywords if kw.arg == "piece_no")
    assert ast.unparse(piece_no_kwarg.value) == "payload.piece_no"


# --------------------------------------------------------------------------
# §ชั้น 2 — ระดับ runtime ด้วย session ปลอม (ไม่ต้องมี DB จริง)
# --------------------------------------------------------------------------


def _write_sheet(path, rows: list[dict[str, str]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(SPLIT_SHEET_COLUMNS))
        writer.writeheader()
        writer.writerows(rows)


class _FakeResult:
    def __init__(self, rows: list[tuple]) -> None:
        self._rows = rows

    def all(self) -> list[tuple]:
        return self._rows


class _FakeSession:
    """session ปลอม — ไม่มี DB จริง ใช้พิสูจน์ *สิ่งที่ถูกเรียก* ระหว่าง `run()`

    ทรงเดียวกับ `_FakeSession`/`_PosterSpy` ของ `test_correction_entry.py` แต่เล็กกว่า
    เพราะเส้นนี้ไม่มีโหมด overwrite ให้ต้องจำลอง
    """

    def __init__(
        self,
        parent_rows: list[tuple],
        taken_piece_rows: list[tuple] | None = None,
    ) -> None:
        self._parent_rows = parent_rows
        self._taken_piece_rows = taken_piece_rows or []
        self.added: list[object] = []
        self.executed: list[object] = []
        self.committed = False
        self.rolled_back = False

    async def scalar(self, stmt: object, params: object = None) -> int:
        return 1  # _check_schema — ตารางมีอยู่เสมอในเทสชุดนี้

    async def execute(self, stmt: object) -> _FakeResult:
        self.executed.append(stmt)
        # ลำดับเรียกคงที่ตาม run(): _load_parents ก่อน แล้วค่อย _load_taken_pieces
        # (ทรงเดียวกับ precondition ของ _FakeSession อื่น ๆ ในโฟลเดอร์นี้ — เปราะบาง
        # ต่อการสลับลำดับใน run() โดยตั้งใจ เพราะทำให้ fake นี้เล็กพอจะอ่านออกทั้งไฟล์)
        if len(self.executed) == 1:
            return _FakeResult(self._parent_rows)
        return _FakeResult(self._taken_piece_rows)

    def add(self, obj: object) -> None:
        self.added.append(obj)

    async def commit(self) -> None:
        self.committed = True

    async def rollback(self) -> None:
        self.rolled_back = True


class _SessionCtx:
    def __init__(self, session: object) -> None:
        self._session = session

    async def __aenter__(self) -> object:
        return self._session

    async def __aexit__(self, *exc_info: object) -> bool:
        return False


def _install_counts(monkeypatch, tmp_path: Path, rows: list[dict[str, str]]) -> None:
    """`load_count_actual_by_poster()` อ่านไฟล์แยกจาก DB — ทุกเทสที่เรียก `run()` ต้องชี้
    `DEFAULT_MANUAL_CSV` ไปที่ fixture ของตัวเอง ไม่งั้นจะไปอ่านไฟล์จริงของเครื่อง
    """
    manual_csv = tmp_path / "manual-entry.csv"
    _write_manual_csv(manual_csv, rows)
    monkeypatch.setattr(mod, "DEFAULT_MANUAL_CSV", manual_csv)


# --------------------------------------------------------------------------
# จุดต่อของด่าน "ที่มีอยู่แล้ว" เข้า run()/main() จริง — AC-8
# (พบระหว่างทำ mutation testing: ทั้งสามจุดนี้เคยไม่มีเทสตัวไหนแตะสายเรียกจริง
# เลยแม้ตัวฟังก์ชันเองจะมีเทสครบทุกกิ่งแล้ว — รูปเดียวกับ G5 ที่ project-gotchas §3
# เตือนไว้)
# --------------------------------------------------------------------------


class _NoTableSession:
    """session ปลอมที่ตอบว่าตาราง poster_splits ไม่มีอยู่ — สำหรับตัวฆ่า mutation
    ของ `_check_schema()` ที่ถูกถอดออกจากสาย
    """

    async def scalar(self, stmt: object, params: object = None) -> int | None:
        return None  # ไม่มีตาราง


async def test_run_raises_when_the_table_is_missing(monkeypatch, tmp_path) -> None:
    """🔴 ตัวฆ่า mutation ของ `_check_schema()` — ถ้าถูกถอดออกจาก `run()` เทสนี้ต้องแดง
    เพราะจะไม่มี PrecheckError โยนออกมาอีกต่อไป
    """
    import app.core.database as db_module

    monkeypatch.setattr(
        db_module, "async_session_maker", lambda: _SessionCtx(_NoTableSession())
    )
    _install_counts(monkeypatch, tmp_path, [])

    sheet = tmp_path / "split-entry.csv"
    _write_sheet(sheet, [_raw()])

    args = argparse.Namespace(
        file=sheet,
        commit=True,
        reviewed_by="chanothai",
        reviewed_at=datetime(2026, 8, 12, 10, 0, tzinfo=UTC),
    )

    with pytest.raises(PrecheckError, match="poster_splits"):
        await mod.run(args, "fake-target")


async def test_run_refuses_a_sheet_that_belongs_to_another_lane(tmp_path) -> None:
    """🔴 ตัวฆ่า mutation ของ `assert_own_sheet()` — ถ้าถูกถอดออกจาก `run()`
    เทสนี้ต้องแดงเพราะจะไม่มี PrecheckError โยนออกมา (ไม่ต้องมี DB/ไฟล์ใบงานจริงเลย —
    ด่านนี้เช็คแค่ชื่อไฟล์ก่อนแตะอะไรอื่น)
    """
    args = argparse.Namespace(
        file=DEFAULT_MANUAL_CSV,  # ใบงานของเส้นที่ 3 ไม่ใช่ของเส้นนี้
        commit=False,
        reviewed_by=None,
        reviewed_at=None,
    )
    with pytest.raises(PrecheckError, match="เส้นที่ 3"):
        await mod.run(args, "fake-target")


def test_main_refuses_a_forbidden_target_before_opening_any_session(
    monkeypatch, tmp_path, capsys
) -> None:
    """🔴 ตัวฆ่า mutation ของ `assert_target()` — ถ้าถูกถอดออกจาก `main()` (หรือแทนที่
    ด้วยค่าคงที่ที่ผ่านเสมอ) เทสนี้ต้องแดง — ทรงเดียวกับ G5 ของ `test_correction_entry.py`

    🔴 ยืนยันด้วย **`run()` ไม่เคยถูกเรียกเลย** ไม่ใช่แค่ดู exit code/ข้อความ —
    ทั้งสองอย่างนั้นเหมือนกันได้จากสาเหตุอื่น (เช่น `--file` ชี้ไฟล์ที่ไม่มีอยู่จริง
    ก็ได้ `main() == 1` + "precheck ไม่ผ่าน" เหมือนกันเป๊ะ โดยไม่เกี่ยวกับ `assert_target`
    เลย — เทสรุ่นแรกที่เช็คแค่สองอย่างนี้พลาดจุดนี้ไป จึง SURVIVED ตอน mutation ถอด
    `assert_target()` ออกจริง)
    """
    forbidden_url = "postgresql+asyncpg://u:p@localhost:5432/poster_nung_prod"
    monkeypatch.setattr(mod, "_load_env", lambda _target: None)
    monkeypatch.setenv("DATABASE_URL", forbidden_url)

    called: list[str] = []

    async def fake_run(args: object, target_label: str) -> int:
        called.append(target_label)
        return 0

    monkeypatch.setattr(mod, "run", fake_run)
    monkeypatch.setattr(
        sys,
        "argv",
        ["split_entry.py", "--file", str(tmp_path / "split-entry.csv")],
    )

    assert mod.main() == 1
    err = capsys.readouterr().err
    assert "poster_nung_prod" in err  # ข้อความจริงของ assert_target_database()
    assert called == []  # run() ไม่เคยถูกเรียกเลย — หยุดก่อนเปิด session ใด ๆ


async def test_run_never_executes_an_update_and_only_sets_the_intended_child_fields(
    monkeypatch, tmp_path
) -> None:
    """🔴 ตัวฆ่า mutation หลักของ AC-3 — ถ้ามีใครแอบเพิ่ม `session.execute(update(...))`
    หรือ `poster.is_unique = True` เข้าไปใน `run()` เทสนี้ต้องแดง
    """
    parent_rows = [(PARENT, "The Matrix", False, PosterCondition.very_good)]
    fake_session = _FakeSession(parent_rows)

    import app.core.database as db_module

    monkeypatch.setattr(
        db_module, "async_session_maker", lambda: _SessionCtx(fake_session)
    )
    _install_counts(
        monkeypatch, tmp_path, [{"poster_uuid": str(PARENT), "count_actual": "5"}]
    )

    sheet = tmp_path / "split-entry.csv"
    _write_sheet(sheet, [_raw(parent_poster_uuid=str(PARENT))])

    args = argparse.Namespace(
        file=sheet,
        commit=True,
        reviewed_by="chanothai",
        reviewed_at=datetime(2026, 8, 12, 10, 0, tzinfo=UTC),
    )

    result = await mod.run(args, "fake-target")

    assert result == 0
    assert fake_session.committed is True
    # §ชั้น 2 ข้อ 1 — ไม่มี statement ชนิด Update เลยสักตัว
    assert not any(isinstance(e, Update) for e in fake_session.executed)

    added_posters = [o for o in fake_session.added if isinstance(o, Poster)]
    added_splits = [o for o in fake_session.added if isinstance(o, PosterSplit)]
    assert len(added_posters) == 1
    assert len(added_splits) == 1

    child = added_posters[0]
    # §ชั้น 2 ข้อ 2 — แถวลูกไม่ใช่แถวพ่อ (id ต่างกัน) และไม่มี attribute อื่นถูก set
    # นอกเหนือจากสี่ตัวที่ตั้งใจ (closed-world บน __dict__ ของ instance จริง)
    assert child.id != PARENT
    set_attrs = {k for k in vars(child) if not k.startswith("_sa_")}
    assert set_attrs == {"id", "title", "price", "condition_grade"}
    assert child.title == "The Matrix"
    assert child.price == Decimal("500")
    assert child.condition_grade is PosterCondition.very_good

    split = added_splits[0]
    assert split.parent_poster_id == PARENT
    assert split.child_poster_id == child.id
    assert split.piece_no == 2
    assert split.reason == "แยกใบที่สองออกมาเพราะต่างเกรดกัน"


async def test_run_does_not_write_anything_when_no_row_is_eligible(
    monkeypatch, tmp_path
) -> None:
    """ด้านที่ต้องไม่พัง — ถ้าพ่อ `is_unique=true` แล้ว (แก้ผ่านเส้นที่ 5 ไปแล้ว)
    ต้องไม่มีอะไรถูกสร้างเลย ไม่ใช่แค่ "ไม่มี Update" (ซึ่งเป็นจริงเสมออยู่แล้ว)
    """
    parent_rows = [(PARENT, "The Matrix", True, PosterCondition.very_good)]
    fake_session = _FakeSession(parent_rows)

    import app.core.database as db_module

    monkeypatch.setattr(
        db_module, "async_session_maker", lambda: _SessionCtx(fake_session)
    )
    _install_counts(
        monkeypatch, tmp_path, [{"poster_uuid": str(PARENT), "count_actual": "5"}]
    )

    sheet = tmp_path / "split-entry.csv"
    _write_sheet(sheet, [_raw(parent_poster_uuid=str(PARENT))])

    args = argparse.Namespace(
        file=sheet,
        commit=True,
        reviewed_by="chanothai",
        reviewed_at=datetime(2026, 8, 12, 10, 0, tzinfo=UTC),
    )

    result = await mod.run(args, "fake-target")

    assert result == 0
    assert fake_session.added == []
    # ยัง commit อยู่ (ไม่มีอะไรผิดพลาด แค่ไม่มีอะไรให้เขียน) — เทียบ session.added
    # ว่างเปล่าคือหลักฐานจริง ไม่ใช่ exit code


async def test_run_skips_only_the_colliding_row_when_the_piece_no_is_taken(
    monkeypatch, tmp_path
) -> None:
    """🔴 ด่านชั้นสคริปต์ (layer 2) ของ AC-4 — piece_no ที่ชนแล้วข้ามเฉพาะแถวนั้น
    ต่างจาก `BLOCKED_ALREADY_SPLIT` เดิมที่ปฏิเสธทั้งไฟล์ (ถูกถอดไปแล้ว — A-D6)
    """
    parent_rows = [(PARENT, "The Matrix", False, PosterCondition.very_good)]
    taken_piece_rows = [(PARENT, 2)]  # piece_no 2 ถูกใช้ไปแล้ว — ตรงกับ _raw()
    fake_session = _FakeSession(parent_rows, taken_piece_rows)

    import app.core.database as db_module

    monkeypatch.setattr(
        db_module, "async_session_maker", lambda: _SessionCtx(fake_session)
    )
    _install_counts(
        monkeypatch, tmp_path, [{"poster_uuid": str(PARENT), "count_actual": "5"}]
    )

    sheet = tmp_path / "split-entry.csv"
    _write_sheet(sheet, [_raw(parent_poster_uuid=str(PARENT))])

    args = argparse.Namespace(
        file=sheet,
        commit=True,
        reviewed_by="chanothai",
        reviewed_at=datetime(2026, 8, 12, 10, 0, tzinfo=UTC),
    )

    result = await mod.run(args, "fake-target")

    assert result == 0  # ไม่ใช่ 1 — ข้ามแถว ไม่ใช่ปฏิเสธทั้งไฟล์ (A-D6)
    assert fake_session.added == []
    assert fake_session.committed is True


async def test_run_prints_the_piece_taken_report_in_commit_mode(
    monkeypatch, tmp_path, capsys
) -> None:
    """🔴 High-1 (รอบแก้ที่ 1 ของ code-critic) — ตัวฆ่า mutation M18/M19:
    M18 ถอดบรรทัด `_report(plans, target_label, committed=args.commit)` ออกจาก
    `run()` ทั้งบรรทัด · M19 ย้าย `_report(...)` เข้าไปอยู่ใต้ `if not args.commit:`
    (⇒ โหมด `--commit` เงียบสนิท) — เทสรายงานเดิม (`test_report_...`) ยิง `capsys`
    ครอบ `mod._report(...)` ที่เรียก**ตรง** ไม่ได้ครอบ `run()` จริง จึงพิสูจน์ได้แค่ว่า
    รายงานหน้าตาถูก ไม่ได้พิสูจน์ว่ามันถูกเรียกจาก `run()` (ADR-0024 A-D6:
    "รายงานคือด่านเดียวที่เหลือ")

    🔴 ต้องรันในโหมด `--commit` โดยเฉพาะ — คู่กับ `..._in_dry_run_mode` ด้านล่าง
    ถ้ามีแค่ dry-run ตัวเดียว M19 (ย้ายเข้าไปใต้ `if not args.commit:`) จะยังรอด
    เพราะ dry-run ก็อยู่ใต้เงื่อนไขนั้นอยู่แล้วโดยบังเอิญ
    """
    parent_rows = [(PARENT, "The Matrix", False, PosterCondition.very_good)]
    taken_piece_rows = [(PARENT, 2)]  # piece_no 2 ถูกใช้ไปแล้ว — ตรงกับ _raw()
    fake_session = _FakeSession(parent_rows, taken_piece_rows)

    import app.core.database as db_module

    monkeypatch.setattr(
        db_module, "async_session_maker", lambda: _SessionCtx(fake_session)
    )
    _install_counts(
        monkeypatch, tmp_path, [{"poster_uuid": str(PARENT), "count_actual": "5"}]
    )

    sheet = tmp_path / "split-entry.csv"
    _write_sheet(sheet, [_raw(parent_poster_uuid=str(PARENT))])

    args = argparse.Namespace(
        file=sheet,
        commit=True,  # 🔴 จุดที่ M19 ทำให้เงียบ
        reviewed_by="chanothai",
        reviewed_at=datetime(2026, 8, 12, 10, 0, tzinfo=UTC),
    )

    result = await mod.run(args, "fake-target")
    assert result == 0

    out = capsys.readouterr().out
    assert "piece_no ชนกับที่มีอยู่แล้ว" in out
    assert "piece_no 2 ถูกใช้ไปแล้ว" in out
    assert "ไม่ถูกสร้าง" in out


async def test_run_prints_the_piece_taken_report_in_dry_run_mode(
    monkeypatch, tmp_path, capsys
) -> None:
    """ด้านคู่กันของเทสข้างบน — โหมด dry-run ก็ต้องเห็นรายงานเดียวกัน (M18 ถอด
    ทั้งบรรทัดกระทบทั้งสองโหมดพร้อมกัน — ตัวนี้ยืนยันว่าโหมด dry-run ไม่เคยเงียบ
    ตั้งแต่แรกอยู่แล้วด้วย)
    """
    parent_rows = [(PARENT, "The Matrix", False, PosterCondition.very_good)]
    taken_piece_rows = [(PARENT, 2)]
    fake_session = _FakeSession(parent_rows, taken_piece_rows)

    import app.core.database as db_module

    monkeypatch.setattr(
        db_module, "async_session_maker", lambda: _SessionCtx(fake_session)
    )
    _install_counts(
        monkeypatch, tmp_path, [{"poster_uuid": str(PARENT), "count_actual": "5"}]
    )

    sheet = tmp_path / "split-entry.csv"
    _write_sheet(sheet, [_raw(parent_poster_uuid=str(PARENT))])

    args = argparse.Namespace(
        file=sheet,
        commit=False,  # dry-run
        reviewed_by=None,
        reviewed_at=None,
    )

    result = await mod.run(args, "fake-target")
    assert result == 0

    out = capsys.readouterr().out
    assert "piece_no ชนกับที่มีอยู่แล้ว" in out
    assert "piece_no 2 ถูกใช้ไปแล้ว" in out
    assert "ไม่ถูกสร้าง" in out


async def test_run_skips_the_row_when_the_parent_has_no_count_yet(
    monkeypatch, tmp_path
) -> None:
    """🔴 AC-6 ที่ระดับ `run()` จริง (ไม่ใช่แค่ `plan_writes()` เดี่ยว ๆ) — ตัวฆ่า
    mutation ของ `load_count_actual_by_poster()` ที่ถูกถอด/แทนด้วยค่าที่ยอมทุกกรณี
    """
    parent_rows = [(PARENT, "The Matrix", False, PosterCondition.very_good)]
    fake_session = _FakeSession(parent_rows)

    import app.core.database as db_module

    monkeypatch.setattr(
        db_module, "async_session_maker", lambda: _SessionCtx(fake_session)
    )
    # count_actual ว่าง — ยังไม่มีใครนับ
    _install_counts(
        monkeypatch, tmp_path, [{"poster_uuid": str(PARENT), "count_actual": ""}]
    )

    sheet = tmp_path / "split-entry.csv"
    _write_sheet(sheet, [_raw(parent_poster_uuid=str(PARENT))])

    args = argparse.Namespace(
        file=sheet,
        commit=True,
        reviewed_by="chanothai",
        reviewed_at=datetime(2026, 8, 12, 10, 0, tzinfo=UTC),
    )

    result = await mod.run(args, "fake-target")

    assert result == 0
    assert fake_session.added == []


async def test_run_skips_the_row_when_the_piece_no_exceeds_the_count(
    monkeypatch, tmp_path
) -> None:
    """🔴 AC-6 ที่ระดับ `run()` จริง — piece_no 2 > count_actual 1"""
    parent_rows = [(PARENT, "The Matrix", False, PosterCondition.very_good)]
    fake_session = _FakeSession(parent_rows)

    import app.core.database as db_module

    monkeypatch.setattr(
        db_module, "async_session_maker", lambda: _SessionCtx(fake_session)
    )
    _install_counts(
        monkeypatch, tmp_path, [{"poster_uuid": str(PARENT), "count_actual": "1"}]
    )

    sheet = tmp_path / "split-entry.csv"
    _write_sheet(sheet, [_raw(parent_poster_uuid=str(PARENT))])  # piece_no 2

    args = argparse.Namespace(
        file=sheet,
        commit=True,
        reviewed_by="chanothai",
        reviewed_at=datetime(2026, 8, 12, 10, 0, tzinfo=UTC),
    )

    result = await mod.run(args, "fake-target")

    assert result == 0
    assert fake_session.added == []


async def test_run_passes_the_real_parents_taken_pieces_and_counts_to_plan_writes(
    monkeypatch, tmp_path
) -> None:
    """🔴 ตัวฆ่า mutation ที่ *คงอาร์กิวเมนต์ไว้* แต่ส่งค่าคงที่ว่างเปล่าแทนของจริง
    (เช่น `{}` ทุกตัว) — spy บน `plan_writes()` ยืนยันว่าค่าที่ได้รับคือผลจริงของ
    `_load_parents()`/`_load_taken_pieces()`/`load_count_actual_by_poster()` ในรอบนั้น (ทรงเดียวกับ
    `test_main_passes_the_counted_set_of_this_very_run_not_a_constant` ของ
    `make_split_sheet.py`)
    """
    parent_rows = [(PARENT, "The Matrix", False, PosterCondition.very_good)]
    taken_piece_rows = [(PARENT, 5)]  # piece_no 5 ถูกใช้ไปแล้ว — ไม่ชนกับแถวนี้ (2)
    fake_session = _FakeSession(parent_rows, taken_piece_rows)

    import app.core.database as db_module

    monkeypatch.setattr(
        db_module, "async_session_maker", lambda: _SessionCtx(fake_session)
    )
    _install_counts(
        monkeypatch, tmp_path, [{"poster_uuid": str(PARENT), "count_actual": "9"}]
    )

    seen: list[tuple] = []
    real_plan_writes = mod.plan_writes

    def spy(rows, parents, taken_pieces, counts):
        seen.append((parents, taken_pieces, counts))
        return real_plan_writes(rows, parents, taken_pieces, counts)

    monkeypatch.setattr(mod, "plan_writes", spy)

    sheet = tmp_path / "split-entry.csv"
    _write_sheet(sheet, [_raw(parent_poster_uuid=str(PARENT))])

    args = argparse.Namespace(
        file=sheet,
        commit=True,
        reviewed_by="chanothai",
        reviewed_at=datetime(2026, 8, 12, 10, 0, tzinfo=UTC),
    )

    result = await mod.run(args, "fake-target")

    assert result == 0
    assert len(seen) == 1
    parents_seen, taken_seen, counts_seen = seen[0]
    assert parents_seen[PARENT].title == "The Matrix"
    assert parents_seen[PARENT].condition_grade is PosterCondition.very_good
    assert taken_seen[PARENT] == frozenset({5})
    assert counts_seen[PARENT] == 9
    # ด้านบวก — ค่าจริงเหล่านี้ทำให้แถวผ่านจนถึง WRITE ได้
    assert len(fake_session.added) == 2


async def test_a_parent_with_no_grade_in_the_real_db_is_skipped_through_run(
    db_session: AsyncSession, monkeypatch, tmp_path
) -> None:
    """🔴 AC-5 ที่ระดับ DB จริง — ต่างจาก `test_parent_with_no_grade_is_skipped` ที่
    เรียก `plan_writes()` ตรง ๆ (ป้อน `ParentState` เอง) ตัวนี้พิสูจน์ทั้งสาย
    `_load_parents()` (select `Poster.condition_grade` จริง) → `plan_writes()` → `run()`
    — ถ้ามีใครเปลี่ยนคอลัมน์ที่ `_load_parents()` select ผิด (เช่น select `title` แทน
    `condition_grade`) เทสแบบ fake session จับไม่ได้เลยเพราะ fake ไม่ได้รันสถิติจริง
    ผ่าน SQL ตัวนี้เป็นเทสเดียวที่จับได้
    """
    parent = Poster(
        title="Ungraded Parent",
        price=Decimal("500.00"),
        condition_grade=None,  # ยังไม่มีเกรด — สถานะของกรอบไฟ BL-82
        is_unique=False,
    )
    db_session.add(parent)
    await db_session.flush()
    parent_id = parent.id

    import app.core.database as db_module

    monkeypatch.setattr(
        db_module, "async_session_maker", lambda: _SessionCtx(db_session)
    )
    _install_counts(
        monkeypatch, tmp_path, [{"poster_uuid": str(parent_id), "count_actual": "5"}]
    )

    sheet = tmp_path / "split-entry.csv"
    _write_sheet(sheet, [_raw(parent_poster_uuid=str(parent_id))])

    args = argparse.Namespace(
        file=sheet,
        commit=True,
        reviewed_by="chanothai",
        reviewed_at=datetime(2026, 8, 12, 10, 0, tzinfo=UTC),
    )

    result = await mod.run(args, "test-db")
    assert result == 0

    children = (
        (await db_session.execute(select(Poster).where(Poster.id != parent_id)))
        .scalars()
        .all()
    )
    assert children == []


# --------------------------------------------------------------------------
# §ชั้น 3 — อ่านค่าพ่อกลับมาเทียบ (DB จริงผ่าน db_session fixture)
# --------------------------------------------------------------------------


async def test_the_parent_row_is_byte_for_byte_unchanged_after_a_real_commit(
    db_session: AsyncSession, monkeypatch, tmp_path
) -> None:
    """🔴 นี่คือเทสที่สำคัญที่สุดของทั้งไฟล์ — พิสูจน์ด้วย DB จริง ไม่ใช่ mock

    สร้างพ่อที่มีค่า **ไม่ใช่ default ของคอลัมน์สักตัว** (status/published_at/
    needs_review ทุกตัวตั้งใจให้ต่างจาก server_default) เพื่อให้เทสนี้ไวต่อการเปลี่ยน
    จริง — ถ้าโค้ดเผลอ reset อะไรกลับไปหาค่า default โดยบังเอิญ เทสจะยังจับได้
    """
    parent = Poster(
        title="The Matrix (ADVANCE 4K)",
        price=Decimal("999.00"),
        condition_grade=PosterCondition.very_fine,
        is_unique=False,
        status=PosterStatus.reserved,
        published_at=datetime(2026, 8, 1, tzinfo=UTC),
        needs_review=False,
    )
    db_session.add(parent)
    await db_session.flush()
    parent_id = parent.id

    import app.core.database as db_module

    monkeypatch.setattr(
        db_module, "async_session_maker", lambda: _SessionCtx(db_session)
    )
    _install_counts(
        monkeypatch, tmp_path, [{"poster_uuid": str(parent_id), "count_actual": "5"}]
    )

    sheet = tmp_path / "split-entry.csv"
    _write_sheet(
        sheet,
        [
            _raw(
                parent_poster_uuid=str(parent_id),
                condition_grade="near_mint",
                price="1200",
                reason="ใบที่สองสภาพต่างจากใบแรกชัดเจน",
            )
        ],
    )

    args = argparse.Namespace(
        file=sheet,
        commit=True,
        reviewed_by="chanothai",
        reviewed_at=datetime(2026, 8, 12, 10, 0, tzinfo=UTC),
    )

    result = await mod.run(args, "test-db")
    assert result == 0

    # query กลับมาแบบ Core select (ไม่ผ่าน ORM identity map ของ `parent`) — พิสูจน์ที่
    # ระดับแถวจริงใน DB ไม่ใช่แค่ว่า python object เดิมไม่ถูกแตะ
    row = (
        await db_session.execute(
            select(
                Poster.price,
                Poster.status,
                Poster.published_at,
                Poster.needs_review,
                Poster.condition_grade,
                Poster.is_unique,
            ).where(Poster.id == parent_id)
        )
    ).one()

    assert row.price == Decimal("999.00")
    assert row.status is PosterStatus.reserved
    assert row.published_at == datetime(2026, 8, 1, tzinfo=UTC)
    assert row.needs_review is False
    assert row.condition_grade is PosterCondition.very_fine
    # is_unique ของพ่อยังเป็น false — เส้นนี้ไม่แก้มัน (D3: ต้องผ่านเส้นที่ 5 ต่างหาก)
    assert row.is_unique is False

    # ด้านบวก — แถวลูกต้องถูกสร้างจริงพร้อมค่าที่กรอก และ is_unique มาจาก
    # server_default (ไม่ใช่ทั้งไฟล์นี้ปฏิเสธเงียบ ๆ จนไม่มีอะไรเกิดขึ้นเลย)
    split_row = (
        await db_session.execute(
            select(PosterSplit).where(PosterSplit.parent_poster_id == parent_id)
        )
    ).scalar_one()
    child = (
        await db_session.execute(
            select(Poster).where(Poster.id == split_row.child_poster_id)
        )
    ).scalar_one()
    assert child.title == "The Matrix (ADVANCE 4K)"
    assert child.price == Decimal("1200.00")
    assert child.condition_grade is PosterCondition.near_mint
    assert child.is_unique is True
    assert child.status is PosterStatus.available
    assert child.needs_review is True
    assert child.published_at is None
    assert split_row.piece_no == 2


# --------------------------------------------------------------------------
# §ชั้น 4 — รันใบงานเดิมซ้ำ (DB จริง) — A-D6: ข้ามแถว ไม่ปฏิเสธทั้งไฟล์
# --------------------------------------------------------------------------


async def test_running_the_same_worksheet_twice_does_not_create_a_second_child(
    db_session: AsyncSession, monkeypatch, tmp_path
) -> None:
    """🔴 รูปแบบใหม่ของ probe ที่ code-critic ใช้จับ High-1 เดิม (poster_splits=2 ·
    children=2) — INF-25 เปลี่ยนพฤติกรรมจาก "ปฏิเสธทั้งไฟล์ (exit 1)" เป็น "ข้ามแถว
    + รายงาน (exit 0)" (A-D6) รันสองครั้งด้วยไฟล์เดียวกันที่**ไม่เปลี่ยนเนื้อหาเลย**
    (จำลอง "กรอกไว้แล้วลืมแล้วรันซ้ำ") — ครั้งที่สองต้องไม่สร้างอะไรเพิ่มเลย ทั้ง
    `poster_splits` และ `posters` (child) ต้องเหลือแค่ 1 แถวเหมือนเดิม ไม่ใช่ 2
    """
    parent = Poster(
        title="The Matrix",
        price=Decimal("999.00"),
        condition_grade=PosterCondition.very_fine,
        is_unique=False,
    )
    db_session.add(parent)
    await db_session.flush()
    parent_id = parent.id

    import app.core.database as db_module

    monkeypatch.setattr(
        db_module, "async_session_maker", lambda: _SessionCtx(db_session)
    )
    _install_counts(
        monkeypatch, tmp_path, [{"poster_uuid": str(parent_id), "count_actual": "5"}]
    )

    sheet = tmp_path / "split-entry.csv"
    _write_sheet(sheet, [_raw(parent_poster_uuid=str(parent_id))])

    args = argparse.Namespace(
        file=sheet,
        commit=True,
        reviewed_by="chanothai",
        reviewed_at=datetime(2026, 8, 12, 10, 0, tzinfo=UTC),
    )

    first = await mod.run(args, "test-db")
    assert first == 0

    # ไฟล์เดิม เนื้อหาเดิมเป๊ะ — เหมือนคนลืมว่ารันไปแล้วแล้วกดรันซ้ำ
    second = await mod.run(args, "test-db")
    assert (
        second == 0
    )  # 🔴 A-D6 — ไม่ใช่ 1 อีกต่อไป ข้ามแถวแล้วรายงาน ไม่ปฏิเสธทั้งไฟล์

    splits = (
        (
            await db_session.execute(
                select(PosterSplit).where(PosterSplit.parent_poster_id == parent_id)
            )
        )
        .scalars()
        .all()
    )
    children = (
        (await db_session.execute(select(Poster).where(Poster.id != parent_id)))
        .scalars()
        .all()
    )
    assert len(splits) == 1
    assert len(children) == 1


async def test_a_freshly_split_child_row_always_has_a_null_verified_at(
    db_session: AsyncSession, monkeypatch, tmp_path
) -> None:
    """🔴 AC-6(ข) ของ INF-29 (ADR-0027 D6) — แถวลูกจากเส้นที่ 6 เกิดพร้อม
    `verified_at = NULL` เสมอ

    ได้ฟรีจากการที่คอลัมน์ `verified_at` **ไม่มี `server_default`** (เหมือน
    `published_at`) และ `run()` ของไฟล์นี้ไม่เคย `set` มันเลย (พิสูจน์แยกที่
    `test_the_source_never_mentions_verified_at_anywhere`) — แต่ "ได้ฟรี" ไม่ใช่
    เหตุผลที่จะไม่มีเทสยืนยัน (skill `test-quality` — ต้องพิสูจน์ ไม่ใช่พึ่งว่าได้ฟรี)
    ยิงเข้า DB จริงเพื่อพิสูจน์ว่าคอลัมน์จริงในสคีมาไม่มี default ที่จะทำให้ข้อสมมติฐาน
    นี้ผิดอย่างเงียบ ๆ (ถ้าใครเผลอเพิ่ม server_default ในอนาคต แถวลูกจะยัง publish
    ไม่ได้อยู่ดีเพราะ NOT_VERIFIED — แต่ค่าที่อ่านได้จะไม่ใช่ NULL ซึ่งผิด invariant
    ที่ AC-6(ข) ล็อกไว้)
    """
    parent = Poster(
        title="The Matrix",
        price=Decimal("999.00"),
        condition_grade=PosterCondition.very_fine,
        is_unique=False,
    )
    db_session.add(parent)
    await db_session.flush()
    parent_id = parent.id

    import app.core.database as db_module

    monkeypatch.setattr(
        db_module, "async_session_maker", lambda: _SessionCtx(db_session)
    )
    _install_counts(
        monkeypatch, tmp_path, [{"poster_uuid": str(parent_id), "count_actual": "5"}]
    )

    sheet = tmp_path / "split-entry.csv"
    _write_sheet(sheet, [_raw(parent_poster_uuid=str(parent_id))])

    args = argparse.Namespace(
        file=sheet,
        commit=True,
        reviewed_by="chanothai",
        reviewed_at=datetime(2026, 8, 12, 10, 0, tzinfo=UTC),
    )

    result = await mod.run(args, "test-db")
    assert result == 0

    (child,) = (
        (await db_session.execute(select(Poster).where(Poster.id != parent_id)))
        .scalars()
        .all()
    )
    assert child.verified_at is None
    # positive control ในตัวเดียวกัน — ยืนยันว่าแถวนี้คือลูกที่ตั้งใจสร้างจริง
    # ไม่ใช่แถวที่ query ผิดพลาดไปเจอ · เกรดเป็นของ*ชิ้นนี้*จากใบงาน (_raw() default
    # = very_good) ไม่ใช่เกรดของพ่อ (very_fine) — คนละแหล่งกันตามหลัก D3
    assert child.condition_grade is PosterCondition.very_good
    assert child.title == "The Matrix"


async def test_new_rows_in_the_same_file_still_land_next_to_a_collision(
    db_session: AsyncSession, monkeypatch, tmp_path
) -> None:
    """🔴 AC-4 — แถวใหม่ในไฟล์เดียวกันยังลงต่อ แม้มีแถวอื่นชน piece_no"""
    parent_a = Poster(
        title="Parent A",
        price=Decimal("100"),
        condition_grade=PosterCondition.very_fine,
        is_unique=False,
    )
    parent_b = Poster(
        title="Parent B",
        price=Decimal("200"),
        condition_grade=PosterCondition.very_fine,
        is_unique=False,
    )
    db_session.add_all([parent_a, parent_b])
    await db_session.flush()

    # parent_a ถูกแตกไปแล้วด้วย piece_no 2 (จำลองรอบก่อนหน้า) — สร้าง child จริงก่อน
    # แล้วค่อยผูก PosterSplit เข้ากับ id ของมัน
    child_of_a = Poster(
        title="Parent A", price=Decimal("100"), condition_grade=PosterCondition.mint
    )
    db_session.add(child_of_a)
    await db_session.flush()
    db_session.add(
        PosterSplit(
            child_poster_id=child_of_a.id,
            parent_poster_id=parent_a.id,
            piece_no=2,
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
    _install_counts(
        monkeypatch,
        tmp_path,
        [
            {"poster_uuid": str(parent_a.id), "count_actual": "5"},
            {"poster_uuid": str(parent_b.id), "count_actual": "5"},
        ],
    )

    sheet = tmp_path / "split-entry.csv"
    _write_sheet(
        sheet,
        [
            _raw(parent_poster_uuid=str(parent_a.id)),  # piece_no 2 — ชนของเดิม
            _raw(
                parent_poster_uuid=str(parent_b.id), piece_no="2"
            ),  # พ่อคนละคน — ไม่ชน
        ],
    )

    args = argparse.Namespace(
        file=sheet,
        commit=True,
        reviewed_by="chanothai",
        reviewed_at=datetime(2026, 8, 12, 10, 0, tzinfo=UTC),
    )

    result = await mod.run(args, "test-db")
    assert result == 0

    splits_b = (
        (
            await db_session.execute(
                select(PosterSplit).where(PosterSplit.parent_poster_id == parent_b.id)
            )
        )
        .scalars()
        .all()
    )
    assert len(splits_b) == 1  # แถวใหม่ของ parent_b ยังลงต่อ แม้ parent_a ชน


# --------------------------------------------------------------------------
# §ชั้น 5 — AC-2: แตกพ่อเดียวกันหลายรอบจริง (~4 รอบ) บน DB ทดสอบ
# --------------------------------------------------------------------------


async def test_the_same_parent_can_be_split_across_four_real_runs(
    db_session: AsyncSession, monkeypatch, tmp_path
) -> None:
    """🔴 AC-2 บังคับ — ห้ามเทสรอบเดียวแล้วอนุมาน ต้องเดินครบ ~4 รอบจริงกับพ่อคนเดียว
    โดย regenerate `piece_no` ทีละรอบจากสถานะ DB สด ๆ (ทรงเดียวกับที่
    `make_split_sheet.py` ทำจริง — `max(piece_no)+1`)
    """
    parent = Poster(
        title="The Matrix",
        price=Decimal("999.00"),
        condition_grade=PosterCondition.very_fine,
        is_unique=False,
    )
    db_session.add(parent)
    await db_session.flush()
    parent_id = parent.id

    import app.core.database as db_module

    monkeypatch.setattr(
        db_module, "async_session_maker", lambda: _SessionCtx(db_session)
    )
    _install_counts(
        monkeypatch, tmp_path, [{"poster_uuid": str(parent_id), "count_actual": "10"}]
    )

    for round_no in range(4):
        taken = await mod._load_taken_pieces(db_session, [parent_id])
        next_piece = max(taken.get(parent_id, frozenset()), default=1) + 1

        sheet = tmp_path / f"split-entry-{round_no}.csv"
        _write_sheet(
            sheet,
            [
                _raw(
                    parent_poster_uuid=str(parent_id),
                    piece_no=str(next_piece),
                    reason=f"รอบที่ {round_no}",
                )
            ],
        )
        args = argparse.Namespace(
            file=sheet,
            commit=True,
            reviewed_by="chanothai",
            reviewed_at=datetime(2026, 8, 12, 10, 0, tzinfo=UTC),
        )
        result = await mod.run(args, "test-db")
        assert result == 0, f"รอบที่ {round_no} ควรสำเร็จ"

    splits = (
        (
            await db_session.execute(
                select(PosterSplit).where(PosterSplit.parent_poster_id == parent_id)
            )
        )
        .scalars()
        .all()
    )
    assert len(splits) == 4
    assert {s.piece_no for s in splits} == {2, 3, 4, 5}


async def test_generator_and_applier_round_trip_computes_the_real_next_piece(
    db_session: AsyncSession, monkeypatch, tmp_path
) -> None:
    """🔴 High-2 (รอบแก้ที่ 1 ของ code-critic) — ตัวฆ่า mutation M12: `make_split_sheet
    .load_from_db()` เปลี่ยน `max_piece + 1` → `max_piece` เฉย ๆ

    ต่างจาก `test_the_same_parent_can_be_split_across_four_real_runs` ข้างบนตรงที่
    ตัวนั้น**คำนวณ `piece_no` เองในเทส** (`max(taken)+1`) ไม่เคยเรียก generator จริงเลย
    — ทุกเทสของ `test_make_split_sheet.py` ก็ fake `load_from_db()` ทิ้งเหมือนกันหมด
    (`_install_split_sheet_cli`) ⇒ ไม่มีเทสไหนเดินวง **generator อ่าน DB จริง → เขียน
    piece_no ลงใบงาน → applier รัน → รอบถัดไป generator อ่านใหม่** เลยสักเทส —
    ถ้าสูตร `max+1` พังในโค้ดจริง (แต่ไม่พังใน CI เพราะไม่มีใครเดินวงนี้) รอบที่ 2
    เป็นต้นไปของทุกพ่อในของจริงจะได้เลขที่ชนของเดิม → ถูกข้ามทั้งหมด (SKIP_PIECE_TAKEN)
    → AC-2 พังในของจริงขณะที่ CI ยังเขียว
    """
    from scripts.seed import make_split_sheet as sheet_mod

    parent = Poster(
        title="The Matrix",
        price=Decimal("999.00"),
        condition_grade=PosterCondition.very_fine,
        is_unique=False,
    )
    db_session.add(parent)
    await db_session.flush()
    parent_id = parent.id

    import app.core.database as db_module

    monkeypatch.setattr(
        db_module, "async_session_maker", lambda: _SessionCtx(db_session)
    )
    _install_counts(
        monkeypatch, tmp_path, [{"poster_uuid": str(parent_id), "count_actual": "10"}]
    )

    piece_nos_seen: list[int] = []
    for round_no in range(3):
        # 🔴 เรียก generator จริง — ไม่คำนวณ piece_no เองในเทส
        posters, image_urls, next_piece_by_parent = await sheet_mod.load_from_db()
        rows = sheet_mod.build_sheet_rows(
            [p for p in posters if p["id"] == parent_id],
            image_urls,
            include_all=True,
            next_piece_by_parent=next_piece_by_parent,
        )
        assert len(rows) == 1, f"รอบที่ {round_no}: ควรเห็นพ่อคนนี้ 1 แถวในใบงาน"
        piece_no = int(rows[0]["piece_no"])
        piece_nos_seen.append(piece_no)

        sheet = tmp_path / f"split-entry-rt-{round_no}.csv"
        _write_sheet(
            sheet,
            [
                _raw(
                    parent_poster_uuid=str(parent_id),
                    piece_no=str(piece_no),
                    reason=f"round-trip {round_no}",
                )
            ],
        )
        args = argparse.Namespace(
            file=sheet,
            commit=True,
            reviewed_by="chanothai",
            reviewed_at=datetime(2026, 8, 12, 10, 0, tzinfo=UTC),
        )
        result = await mod.run(args, "test-db")
        assert result == 0, f"รอบที่ {round_no} ควรสำเร็จ"

    # 🔴 ตัวฆ่า M12 ตัวจริง — ถ้า max_piece+1 กลายเป็น max_piece เฉย ๆ รอบที่ 2/3
    # จะได้เลขซ้ำกับรอบก่อนหน้า (เลขเดิมที่ applier กันไว้แล้ว) ทำให้ list นี้มีเลขซ้ำ
    # และรอบนั้นจะ `assert result == 0` ผ่าน (A-D6 = ข้ามเงียบ ไม่ error) แต่จำนวน
    # splits ท้ายเทสจะไม่ครบ 3 — สองจุดนี้ดักได้ทั้งคู่
    assert piece_nos_seen == [2, 3, 4]

    splits = (
        (
            await db_session.execute(
                select(PosterSplit).where(PosterSplit.parent_poster_id == parent_id)
            )
        )
        .scalars()
        .all()
    )
    assert {s.piece_no for s in splits} == {2, 3, 4}


async def test_editing_only_the_reason_text_does_not_bypass_the_piece_no_gate(
    db_session: AsyncSession, monkeypatch, tmp_path
) -> None:
    """🔴 AC-1 ท่อนท้าย (รอบแก้ที่ 1 ของ code-critic) — เคสที่ทำให้ INF-25 เกิดขึ้นจริง
    (`screens.yaml` INF-22 **G2**): ก่อน A-D5 คีย์กันรันซ้ำผูกกับ `(parent, reason)`
    ⇒ แก้ **เฉพาะข้อความ `reason`** (เลขชิ้นเดิม) แล้วรันไฟล์เดิมซ้ำ สร้างลูกซ้ำได้
    โดยไม่มีอะไรฟ้อง — ตอนนี้คีย์คือ `(parent, piece_no)` ดังนั้นแก้ `reason` อย่าง
    เดียวโดย `piece_no` เดิม **ต้องยังถูกกัน**
    """
    parent = Poster(
        title="The Matrix",
        price=Decimal("999.00"),
        condition_grade=PosterCondition.very_fine,
        is_unique=False,
    )
    db_session.add(parent)
    await db_session.flush()
    parent_id = parent.id

    import app.core.database as db_module

    monkeypatch.setattr(
        db_module, "async_session_maker", lambda: _SessionCtx(db_session)
    )
    _install_counts(
        monkeypatch, tmp_path, [{"poster_uuid": str(parent_id), "count_actual": "5"}]
    )

    sheet1 = tmp_path / "split-entry.csv"
    _write_sheet(
        sheet1, [_raw(parent_poster_uuid=str(parent_id), reason="เหตุผลรอบแรก")]
    )
    args1 = argparse.Namespace(
        file=sheet1,
        commit=True,
        reviewed_by="chanothai",
        reviewed_at=datetime(2026, 8, 12, 10, 0, tzinfo=UTC),
    )
    first = await mod.run(args1, "test-db")
    assert first == 0

    # ไฟล์ใหม่ — piece_no เดิม (2, ค่า default ของ _raw()) แต่ reason ถูกแก้ใหม่ทั้ง
    # ข้อความ (จำลอง "แก้คำผิดแล้วรันซ้ำ" ซึ่งเป็นเคสที่ G2 พิสูจน์ว่าหลุดมาก่อน)
    sheet2 = tmp_path / "split-entry-edited.csv"
    _write_sheet(
        sheet2,
        [
            _raw(
                parent_poster_uuid=str(parent_id),
                reason="แก้คำผิดจากรอบแรก — ข้อความคนละอย่างเลย",
            )
        ],
    )
    args2 = argparse.Namespace(
        file=sheet2,
        commit=True,
        reviewed_by="chanothai",
        reviewed_at=datetime(2026, 8, 12, 10, 0, tzinfo=UTC),
    )
    second = await mod.run(args2, "test-db")
    assert second == 0  # A-D6 — ข้ามแถว (SKIP_PIECE_TAKEN) ไม่ปฏิเสธทั้งไฟล์

    splits = (
        (
            await db_session.execute(
                select(PosterSplit).where(PosterSplit.parent_poster_id == parent_id)
            )
        )
        .scalars()
        .all()
    )
    assert len(splits) == 1  # ยังกันไว้จริง — reason ที่ต่างกันไม่ทำให้ลูกซ้ำเกิด
    assert splits[0].reason == "เหตุผลรอบแรก"  # แถวเดิมไม่ถูกแตะ/ทับด้วย reason ใหม่


# --------------------------------------------------------------------------
# §ชั้น 6 — AC-3: ตัดด่านชั้นสคริปต์ออกจากสายแล้วต้องชน DB จริง + rollback สะอาด
# --------------------------------------------------------------------------


async def test_bypassing_the_script_level_gate_still_hits_the_db_constraint(
    db_session: AsyncSession, monkeypatch, tmp_path
) -> None:
    """🔴 AC-3 — ด่านชั้นสคริปต์ (`SKIP_PIECE_TAKEN`) มีไว้ให้ error อ่านรู้เรื่อง
    ไม่ใช่ตัวกันจริง พิสูจน์ด้วยการบังคับให้ `_load_taken_pieces` คืน `{}` เสมอ
    (ทรงเดียวกับ `taken_pieces={}` ที่ AC-3 สั่ง) แล้วยิง `run()` ตรง ๆ — ต้องชน
    `uq_poster_splits_parent_piece` ที่ระดับ DB และ rollback สะอาด (ไม่มี partial write)
    """
    parent = Poster(
        title="The Matrix",
        price=Decimal("999.00"),
        condition_grade=PosterCondition.very_fine,
        is_unique=False,
    )
    db_session.add(parent)
    await db_session.flush()
    parent_id = parent.id

    child = Poster(
        title="The Matrix", price=Decimal("500"), condition_grade=PosterCondition.mint
    )
    db_session.add(child)
    await db_session.flush()
    db_session.add(
        PosterSplit(
            child_poster_id=child.id,
            parent_poster_id=parent_id,
            piece_no=2,  # piece_no 2 ถูกใช้ไปแล้วจริงใน DB
            reviewed_by="chanothai",
            reviewed_at=datetime(2026, 8, 1, tzinfo=UTC),
            source="split-entry.csv",
            reason="รอบก่อนหน้า",
        )
    )
    # 🔴 ต้อง commit จริง ไม่ใช่แค่ flush — run() ที่ล้มเหลวด้านล่างจะ rollback()
    # ทั้งทรานแซกชัน ถ้าข้อมูล "รอบก่อนหน้า" นี้ยังไม่ commit มันจะหายไปด้วย ทำให้
    # การตรวจ "rollback สะอาด" ข้างล่างเทียบกับ baseline ที่ผิด
    await db_session.commit()

    import app.core.database as db_module

    monkeypatch.setattr(
        db_module, "async_session_maker", lambda: _SessionCtx(db_session)
    )
    _install_counts(
        monkeypatch, tmp_path, [{"poster_uuid": str(parent_id), "count_actual": "5"}]
    )

    # 🔴 ตัดด่านชั้นสคริปต์ออกจากสาย — บังคับให้ plan_writes() มองว่ายังไม่มี
    # piece_no ไหนถูกใช้เลย (ทรงเดียวกับ taken_pieces={} ตามที่ AC-3 สั่ง)
    async def _fake_load_taken_pieces(session: object, parent_ids: list) -> dict:
        return {}

    monkeypatch.setattr(mod, "_load_taken_pieces", _fake_load_taken_pieces)

    sheet = tmp_path / "split-entry.csv"
    _write_sheet(
        sheet, [_raw(parent_poster_uuid=str(parent_id), piece_no="2")]
    )  # ชนของเดิมตรง ๆ

    args = argparse.Namespace(
        file=sheet,
        commit=True,
        reviewed_by="chanothai",
        reviewed_at=datetime(2026, 8, 12, 10, 0, tzinfo=UTC),
    )

    result = await mod.run(args, "test-db")
    assert result == 1  # commit ล้มเหลว (IntegrityError) — ไม่ใช่ SKIP เงียบ ๆ

    # rollback สะอาด — ไม่มี child ใหม่ค้างอยู่ (แค่ตัวที่สร้างไว้ก่อนเทสเริ่ม)
    all_children = (
        (await db_session.execute(select(Poster).where(Poster.id != parent_id)))
        .scalars()
        .all()
    )
    assert len(all_children) == 1  # เฉพาะ child ที่สร้างไว้ก่อนเทส ไม่มีตัวใหม่เพิ่ม

    all_splits = (
        (
            await db_session.execute(
                select(PosterSplit).where(PosterSplit.parent_poster_id == parent_id)
            )
        )
        .scalars()
        .all()
    )
    assert len(all_splits) == 1  # ยังเป็นแถวเดิมแถวเดียว ไม่มีอะไรเพิ่ม
