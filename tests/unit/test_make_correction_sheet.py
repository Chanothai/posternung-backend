"""Unit tests ของ `scripts/seed/make_correction_sheet.py` — INF-21 (AC-1)

จุดสำคัญที่สุดที่ต้องล็อก: สคริปต์นี้ **ห้ามกรอกช่องของคนให้** ทั้งค่าใหม่และเหตุผล
· เครื่องที่เสนอเกรดใหม่ให้คนเซ็นคือเครื่องที่ตัดสินสภาพสินค้าแทนคน (ADR-0009 D6 ·
ADR-0014 D7) และเหตุผลที่เครื่องเขียนให้ไม่ใช่เหตุผล — มันคือข้อความที่ทำให้ audit
*ดูเหมือน* มีคนรู้เห็นทั้งที่ไม่มี (ADR-0010 A-D2 ข้อ 2)
"""

from __future__ import annotations

import ast
import csv
import inspect
import uuid
from datetime import UTC, datetime
from pathlib import Path

import pytest

from app.models.enums import PosterCondition
from scripts.seed import make_correction_sheet as mod
from scripts.seed.correction_entry import (
    CORRECTION_SHEET_COLUMNS,
    CURRENT_COLUMNS,
    KEEP_WORD,
    REASON_COLUMNS,
    WRITABLE_FIELDS,
    FieldMode,
    field_specs,
    parse_rows,
    read_sheet,
)
from scripts.seed.correction_entry import FIELD_MODES as _FIELD_MODES
from scripts.seed.make_correction_sheet import HUMAN_COLUMNS, build_sheet_rows

PID = uuid.UUID("11111111-1111-1111-1111-111111111111")
PID2 = uuid.UUID("22222222-2222-2222-2222-222222222222")

VALUE_FIELDS = tuple(f for f in WRITABLE_FIELDS if _FIELD_MODES[f] is FieldMode.VALUE)
COMMAND_FIELDS = tuple(
    f for f in WRITABLE_FIELDS if _FIELD_MODES[f] is FieldMode.COMMAND
)
SIGNED_SAMPLE = datetime(2026, 8, 15, 10, 0, tzinfo=UTC)


def _db_row(**over: object) -> dict:
    row: dict = {
        "id": PID,
        "title": "Some Poster",
        "condition_grade": PosterCondition.near_mint,
        "is_unique": True,
        "verified_at": None,
        "published_at": None,
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
    # `Y` ไม่ใช่ `True` — คำเดียวกับที่ช่องกรอกข้าง ๆ รับ (ดู §round-trip)
    assert row["current_is_unique"] == "Y"
    # ยังไม่เคยเซ็น/publish — ว่างเปล่า ไม่ใช่ KEEP (KEEP แปลว่า "มีค่าอยู่ อย่าแตะ")
    assert row["current_verified_at"] == ""
    assert row["current_published_at"] == ""


def test_a_row_that_is_not_unique_is_rendered_as_a_word_not_blank() -> None:
    """🔴 "แทนของหลายชิ้น" กับช่องว่างต้องแยกออกจากกัน — ช่องว่างอ่านได้ว่า *ไม่รู้*
    ซึ่งเป็นสภาพที่ `is_unique` (NOT NULL) ไม่มีวันเป็น"""
    (row,) = build_sheet_rows([_db_row(is_unique=False)], {}, include_all=True)
    assert row["current_is_unique"] == "N"
    assert row["current_is_unique"] != ""


def test_a_signed_poster_shows_keep_never_the_real_timestamp() -> None:
    """🔴 G7 (ADR-0027) — ห้ามพิมพ์วันที่จริงลงใบงานเด็ดขาด"""
    (row,) = build_sheet_rows(
        [_db_row(verified_at=SIGNED_SAMPLE, published_at=SIGNED_SAMPLE)],
        {},
        include_all=True,
    )
    assert row["current_verified_at"] == KEEP_WORD
    assert row["current_published_at"] == KEEP_WORD
    assert str(SIGNED_SAMPLE.year) not in row["current_verified_at"]
    assert str(SIGNED_SAMPLE.year) not in row["current_published_at"]


# --------------------------------------------------------------------------
# round-trip — ใบงานต้องสอนคำที่ตัวพาร์เซอร์ของมันเองอ่านออก (G7)
# --------------------------------------------------------------------------
#
# 🔴 เกิดจริง 2026-08-11 ตอนรัน `--commit` ครั้งแรก: ช่อง `current_is_unique` พิมพ์
# `True` (สเปรดชีตเขียนกลับเป็น `TRUE`) ขณะที่ `parse_is_unique()` รับ `Y`/`N` เท่านั้น
# **โดยเจตนา** ⇒ คนที่ก๊อปคำจากช่องที่อยู่ติดกัน — ซึ่งเป็นสิ่งที่ช่องนั้นมีไว้ให้ทำ —
# ถูกปฏิเสธทั้งไฟล์ 5/5 แถว เสียไปหนึ่งรอบเต็มก่อนจะเขียนอะไรได้สักค่า
#
# เทสสองตัวข้างล่างคือ **ด่านของชั้นนี้ ไม่ใช่การแก้ช่องเดียวที่เจอ** — มันวิ่งตาม
# `WRITABLE_FIELDS` ฟิลด์ที่สามที่ถูกเพิ่มเข้า allowlist วันหน้าจะถูกลากเข้ามาเอง
# โดยไม่ต้องมีใครนึกได้ว่าต้องมาต่อรายชื่อ


def _as_a_spreadsheet_would_save_it(text: str) -> str:
    """ข้อความในใบงานหลังถูกเปิด-เซฟด้วยสเปรดชีต

    สเปรดชีตอ่าน `True`/`False` เป็น *ค่า boolean ของมันเอง* แล้วเขียนกลับเป็น
    ตัวพิมพ์ใหญ่ ส่วนข้อความอื่น (`near_mint` · `Y` · ชื่อเรื่อง) ไม่ถูกแตะ —
    นี่คือสิ่งที่สังเกตได้จริงจากไฟล์ที่เจ้าของส่งกลับมา 2026-08-11

    ⚠️ เป็น **แบบจำลองของเครื่องมือนอกระบบ** ไม่ใช่โค้ดของโปรเจกต์ · การแปลงจริง
    ขึ้นกับโปรแกรมและ locale ที่คนใช้ พิสูจน์ด้วยเทสไม่ได้ (skill `test-quality` §5)
    · สิ่งที่เทสนี้ล็อกได้จริงคือ **ใบงานต้องรอดการแปลงรูปที่เคยทำพังมาแล้ว**
    """
    return text.upper() if text.lower() in ("true", "false") else text


# ค่าที่ **DB มีได้จริง** ต่อฟิลด์ VALUE — ประกอบจากโดเมนของฟิลด์เอง ไม่ใช่จากผลลัพธ์ที่
# สคริปต์พิมพ์อยู่วันนี้ (allowlist ที่ก๊อปจากผลลัพธ์พิสูจน์แค่ว่าโค้ดเท่ากับตัวเอง)
#
# 🔴 **แยกสองตระกูล VALUE/COMMAND** (ADR-0027 §AC-5) — ฟิลด์ VALUE พิมพ์ *ค่าเดิม*
# ใน `current_*` แล้วพาร์เซอร์ต้องอ่านกลับมาได้ *ค่าเดียวกันเป๊ะ* (round-trip แท้)
# ส่วนฟิลด์ COMMAND พิมพ์ `KEEP`/ว่างเปล่าเสมอ (G7 — ห้ามพิมพ์วันที่จริง) พาร์เซอร์
# ของมันคืน**คำสั่ง**ไม่ใช่ค่าปลายทาง จึงพิสูจน์ได้แค่ว่า *อ่านออก* ไม่ใช่ *ได้ค่าเดิม*
CURRENT_VALUE_CANDIDATES: dict[str, list[object]] = {
    "condition_grade": list(PosterCondition),
    "is_unique": [True, False],
}
# ค่าที่ DB มีได้จริงของฟิลด์ COMMAND — ใช้แค่ยืนยันว่า current_* readable ไม่ใช่
# เทียบค่าเท่าเดิม (ดู docstring ข้างบน) · 🔴 ไม่รวม `None` — ช่องว่างไม่ใช่คำสั่งที่
# `spec.parse()` ต้องอ่านออกตรง ๆ (blank แปลว่า "ยังไม่ได้กรอก" ซึ่งเป็นด่านของ
# `parse_rows()` ที่ข้ามก่อนถึงชั้น parse เลย — ทดสอบแยกที่
# `test_the_current_columns_show_what_is_about_to_be_overwritten`)
COMMAND_CURRENT_VALUE_CANDIDATES: dict[str, list[object]] = {
    "verified_at": [SIGNED_SAMPLE],
    "published_at": [SIGNED_SAMPLE],
}


def test_the_candidate_table_covers_every_writable_field() -> None:
    """closed-world — ฟิลด์ที่ห้าที่ถูกเพิ่มวันหน้าต้องทำให้เทสนี้แดงก่อน
    ไม่ใช่หลุดออกจากด่าน round-trip ไปเงียบ ๆ"""
    assert set(CURRENT_VALUE_CANDIDATES) == set(VALUE_FIELDS)
    assert set(COMMAND_CURRENT_VALUE_CANDIDATES) == set(COMMAND_FIELDS)
    assert (
        set(CURRENT_VALUE_CANDIDATES) | set(COMMAND_CURRENT_VALUE_CANDIDATES)
    ) == set(WRITABLE_FIELDS)


@pytest.mark.parametrize("field", VALUE_FIELDS)
def test_every_word_the_sheet_prints_is_a_word_its_own_parser_reads_back(
    field: str,
) -> None:
    """DB → ใบงาน → สเปรดชีต → พาร์เซอร์ **แล้วต้องได้ค่าเดิมกลับมา** (ฟิลด์ VALUE เท่านั้น)

    ไม่ใช่แค่ "อ่านออก" แต่ต้องได้ *ค่าเดิม* — generator ที่พิมพ์ `Y` ให้แถวที่
    `is_unique = False` อ่านออกทุกตัวแต่โกหกคนกรอก
    """
    spec = field_specs()[field]
    for value in CURRENT_VALUE_CANDIDATES[field]:
        (row,) = build_sheet_rows([_db_row(**{field: value})], {}, include_all=True)
        printed = _as_a_spreadsheet_would_save_it(row[f"current_{field}"])
        assert spec.parse(printed) == value, f"{field}: {printed!r}"


@pytest.mark.parametrize("field", COMMAND_FIELDS)
def test_the_current_column_of_a_command_field_is_always_readable(field: str) -> None:
    """ฟิลด์ COMMAND — พาร์เซอร์ต้องอ่าน `KEEP`/ว่างเปล่าได้โดยไม่ raise เสมอ (แต่
    ไม่เทียบว่าได้ *ค่าเดิม* กลับมา เพราะพาร์เซอร์คืนคำสั่งไม่ใช่ timestamp)"""
    spec = field_specs()[field]
    for value in COMMAND_CURRENT_VALUE_CANDIDATES[field]:
        (row,) = build_sheet_rows([_db_row(**{field: value})], {}, include_all=True)
        printed = _as_a_spreadsheet_would_save_it(row[f"current_{field}"])
        spec.parse(printed)  # ต้องไม่ raise


def test_a_filled_in_sheet_copied_from_the_column_next_door_is_accepted(
    tmp_path: Path,
) -> None:
    """เส้นทางเต็มของโรค (ฟิลด์ VALUE เท่านั้น) — ไม่ใช่แค่ฟังก์ชันเดียว

    generator ออกใบงาน → คนก๊อปค่าจาก `current_*` มาลงช่องกรอก (พร้อมเหตุผล) →
    ไฟล์ผ่านสเปรดชีต → `read_sheet()` + `parse_rows()` ของจริงต้องรับได้

    ใช้ `is_unique = True` เป็นสภาพตั้งต้นเพราะเป็นสภาพปกติของ production หลัง
    ADR-0019 D1 · แถวที่ยังเป็น `False` ถูกปฏิเสธด้วย **ด่านนโยบาย** ของ D5/D6
    ซึ่งถูกต้องและมีเทสของมันเองอยู่แล้ว (`test_correction_entry.py` §policy) —
    คนละเรื่องกับ "พาร์เซอร์อ่านคำไม่ออก" ที่ล็อกอยู่ตรงนี้

    🔴 **ไม่รวมฟิลด์ COMMAND** — ก๊อป `KEEP` มาแปะพร้อมเหตุผลเป็นคนละเรื่องกับ "ยืนยัน
    ค่าเดิม" ของฟิลด์ VALUE ข้างบน: `KEEP` ไม่มีค่าปลายทางให้ยืนยัน มันแปลว่า *ไม่ทำ
    อะไร* เฉยๆ (ADR-0027 D7 — ดู
    `test_copying_keep_with_a_reason_is_accepted_as_a_no_op` ด้านล่าง) จึงพิสูจน์
    คนละเรื่องกับเทสนี้
    """
    db_row = _db_row()
    rows = build_sheet_rows([db_row], {}, include_all=True)
    filled = []
    for row in rows:
        copied = dict(row)
        for field in VALUE_FIELDS:
            copied[field] = row[f"current_{field}"]
            copied[f"{field}_reason"] = "ตรวจซ้ำจากใบจริงแล้วยืนยันค่าเดิม"
        filled.append(
            {k: _as_a_spreadsheet_would_save_it(v) for k, v in copied.items()}
        )

    path = tmp_path / "correction-entry.csv"
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(CORRECTION_SHEET_COLUMNS))
        writer.writeheader()
        writer.writerows(filled)

    # 🔴 เทียบกับค่าที่ **DB มี** ไม่ใช่กับข้อความที่เทสเขียนลงไฟล์ — ค่าต้องเดินครบวง
    # แล้วกลับมาเท่าเดิม ทั้ง generator และ parser เป็นโค้ดจริงตลอดทาง
    (parsed,) = parse_rows(read_sheet(path))
    assert parsed.values == {name: db_row[name] for name in VALUE_FIELDS}


def test_copying_keep_with_a_reason_is_accepted_as_a_no_op(
    tmp_path: Path,
) -> None:
    """🔴 G2 (code-critic รอบ 1 ของ INF-29) — ฟิลด์ COMMAND ไม่มี "ยืนยันค่าเดิม"
    แบบฟิลด์ VALUE เพราะ `KEEP` ไม่ใช่ค่าปลายทาง มันแปลว่า *ไม่ทำอะไร* (ADR-0027 D7)
    การก๊อป `current_verified_at` มาแปะพร้อมเหตุผลจึงต้อง**ผ่านเงียบ ๆ เป็น no-op**
    ไม่ใช่ถูกปฏิเสธทั้งไฟล์ — รุ่นก่อนของ `refuse_unwritable_value()` ปฏิเสธ `KEEP`
    เหมือน `UNSIGN`/`PUBLISH` ซึ่งขัดกับ ADR-0027 D7 ตรง ๆ"""
    db_row = _db_row(verified_at=SIGNED_SAMPLE)
    (row,) = build_sheet_rows([db_row], {}, include_all=True)
    assert row["current_verified_at"] == KEEP_WORD

    filled = dict(row)
    filled["verified_at"] = row["current_verified_at"]  # ก๊อป KEEP มาแปะ
    filled["verified_at_reason"] = "ตรวจซ้ำจากใบจริงแล้วยืนยันค่าเดิม"

    path = tmp_path / "correction-entry.csv"
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(CORRECTION_SHEET_COLUMNS))
        writer.writeheader()
        writer.writerow(filled)

    (parsed,) = parse_rows(read_sheet(path))
    assert parsed.values == {}
    assert parsed.reasons == {}


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
