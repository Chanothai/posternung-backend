"""Unit tests ของ `app.core.release_date.parse_release_date_text` —
ADR-0009 D13 ข้อ 2: ฟังก์ชันนี้เป็น writer เดียวของ `Poster.release_date` ต้องมี
unit test ครอบทุกรูปแบบที่เจอจริงจากรอบ `ai_suggest.py --limit` (ดู ADR-0009
§ผลรันครบชุด 116 ใบ) รวมถึงเคสกำกวมและเคส pivot ปีสองหลัก
"""

import ast
import inspect
from datetime import date

from app.core import release_date as release_date_module
from app.core.release_date import (
    TWO_DIGIT_YEAR_PIVOT,
    ReleaseDateParseStatus,
    _expand_two_digit_year,
    parse_release_date_text,
)

# --- รูปแบบตัวเลขที่แยกได้ไม่กำกวม (มีตัวเลขตัวใดตัวหนึ่ง > 12) ---


def test_mm_dot_dd_dot_yy() -> None:
    result = parse_release_date_text("11.16.12")
    assert result.status is ReleaseDateParseStatus.PARSED
    assert result.value == date(2012, 11, 16)


def test_dd_slash_mm_slash_yy() -> None:
    result = parse_release_date_text("20/7/23")
    assert result.status is ReleaseDateParseStatus.PARSED
    assert result.value == date(2023, 7, 20)


def test_dd_slash_mm_slash_yyyy() -> None:
    result = parse_release_date_text("20/7/2023")
    assert result.status is ReleaseDateParseStatus.PARSED
    assert result.value == date(2023, 7, 20)


def test_mm_slash_dd_slash_yy() -> None:
    result = parse_release_date_text("11/15/02")
    assert result.status is ReleaseDateParseStatus.PARSED
    assert result.value == date(2002, 11, 15)


def test_dd_space_mm_space_yyyy_is_parsed_not_unreadable() -> None:
    """'20 7 2023' จาก CSV จริง (uuid c10cfdef, confidence high) — 20 > 12 จึงไม่
    กำกวมเลยว่าใครคือวัน/เดือน แต่ก่อนแก้ regex รับแค่ `.`/`/` เป็นตัวคั่น ตัวคั่นเป็น
    ช่องว่างเลยหลุดไป UNREADABLE ทั้งที่ derive เป็น DATE ได้ (code-critic item 3)"""
    result = parse_release_date_text("20 7 2023")
    assert result.status is ReleaseDateParseStatus.PARSED
    assert result.value == date(2023, 7, 20)


# --- ตัวเลขสองกลุ่ม (เดือน/วัน) ไม่มีปี — เทียบเท่า "March 18" แต่เดือนเป็นตัวเลข ---


def test_numeric_month_dot_day_missing_year_is_incomplete() -> None:
    """'11.19' จาก CSV จริง — 19 > 12 เลยไม่กำกวมว่าใครคือเดือน (11) ใครคือวัน (19)
    แต่ไม่มีปี ต้องลงถังเดียวกับ 'March 18' (INCOMPLETE) ไม่ใช่ UNREADABLE
    (code-critic item 3 — ก่อนแก้ '.' สองกลุ่มไม่ถูก tokenize เป็นตัวเลขวันที่เลย)"""
    result = parse_release_date_text("11.19")
    assert result.status is ReleaseDateParseStatus.INCOMPLETE
    assert result.value is None


def test_numeric_month_dot_day_missing_year_is_incomplete_2() -> None:
    """'7.15' จาก CSV จริง — เหมือน test ด้านบน"""
    result = parse_release_date_text("7.15")
    assert result.status is ReleaseDateParseStatus.INCOMPLETE
    assert result.value is None


def test_numeric_month_day_ambiguous_order_without_year_is_ambiguous() -> None:
    """'5/6' ทั้งคู่ ≤ 12 และไม่เท่ากัน แยกไม่ได้ว่าใครคือวันใครคือเดือน (ไม่มีปีให้
    ด้วยซ้ำ) — เหมือนกรณี AMBIGUOUS ของรูปแบบสามกลุ่ม แค่ไม่มีปี"""
    result = parse_release_date_text("5/6")
    assert result.status is ReleaseDateParseStatus.AMBIGUOUS
    assert result.value is None


def test_numeric_month_day_equal_values_without_year_is_incomplete() -> None:
    """'5.5' วันและเดือนเท่ากัน ตีความแบบไหนก็ได้ผลลัพธ์เดียวกัน (ไม่กำกวม) แต่ยังขาด
    ปีอยู่ดี จึง INCOMPLETE ไม่ใช่ PARSED"""
    result = parse_release_date_text("5.5")
    assert result.status is ReleaseDateParseStatus.INCOMPLETE
    assert result.value is None


def test_numeric_month_day_out_of_range_without_year_is_unreadable() -> None:
    """'45.6' — 45 เกินขอบเขตวันที่เป็นไปได้จริง (>31) ไม่ใช่ปฏิทินจริงไม่ว่าจะตีความ
    แบบไหน"""
    result = parse_release_date_text("45.6")
    assert result.status is ReleaseDateParseStatus.UNREADABLE
    assert result.value is None


# --- พ.ศ. → ค.ศ. ---


def test_thai_day_month_buddhist_year_converted_to_gregorian() -> None:
    result = parse_release_date_text("10 มกราคม 2562")
    assert result.status is ReleaseDateParseStatus.PARSED
    assert result.value == date(2019, 1, 10)


# --- ชื่อเดือน + ปีสองหลัก: ต้องขยาย pivot เหมือนเส้นทางตัวเลข ห้ามคืนปีดิบ ---


def test_thai_month_with_two_digit_year_expands_via_pivot_not_bare_year() -> None:
    """บั๊กจริงที่ code-critic เจอ: '15 กุมภาพันธ์ 62' เคยได้ `date(62, 2, 15)`
    (0062-02-15) เพราะเส้นทางชื่อเดือนไม่ผ่าน `_resolve_year`/pivot เหมือนเส้นทาง
    ตัวเลข — ตอนนี้ต้องขยาย 62 ผ่าน pivot เดียวกับ `_expand_two_digit_year` (62 < 69
    → ค.ศ. 2062) ไม่ใช่ทิ้งไว้เป็นปีดิบที่ไม่สมเหตุสมผล"""
    result = parse_release_date_text("15 กุมภาพันธ์ 62")
    assert result.status is ReleaseDateParseStatus.PARSED
    assert result.value == date(2062, 2, 15)


def test_english_month_with_two_digit_year_expands_via_pivot_not_bare_year() -> None:
    """เคสภาษาอังกฤษคู่กับ test ด้านบน — pivot ต้องทำงานเหมือนกันไม่ว่าชื่อเดือนจะเป็น
    ไทยหรืออังกฤษ เพราะเส้นทางเดียวกัน (`_parse_named`) ใช้ `_expand_year_component`
    ร่วมกันทั้งคู่ (99 >= 69 → ค.ศ. 1999 ไม่ใช่ 0099)"""
    result = parse_release_date_text("February 15 99")
    assert result.status is ReleaseDateParseStatus.PARSED
    assert result.value == date(1999, 2, 15)


# --- ชื่อเดือนที่ไม่ครบ (ขาดวัน และ/หรือขาดปี) → INCOMPLETE ---


def test_english_month_and_day_missing_year_is_incomplete() -> None:
    result = parse_release_date_text("March 18")
    assert result.status is ReleaseDateParseStatus.INCOMPLETE
    assert result.value is None


def test_english_month_and_year_missing_day_is_incomplete() -> None:
    result = parse_release_date_text("MARCH 2022")
    assert result.status is ReleaseDateParseStatus.INCOMPLETE
    assert result.value is None


def test_thai_day_and_month_missing_year_is_incomplete() -> None:
    result = parse_release_date_text("15 กุมภาพันธ์")
    assert result.status is ReleaseDateParseStatus.INCOMPLETE
    assert result.value is None


def test_english_month_and_year_missing_day_is_incomplete_2() -> None:
    result = parse_release_date_text("February 2005")
    assert result.status is ReleaseDateParseStatus.INCOMPLETE
    assert result.value is None


def test_english_month_and_single_digit_day_missing_year_is_incomplete() -> None:
    result = parse_release_date_text("MAY 1")
    assert result.status is ReleaseDateParseStatus.INCOMPLETE
    assert result.value is None


def test_english_month_only_is_incomplete() -> None:
    result = parse_release_date_text("MARCH")
    assert result.status is ReleaseDateParseStatus.INCOMPLETE
    assert result.value is None


def test_english_month_only_is_incomplete_2() -> None:
    result = parse_release_date_text("JUNE")
    assert result.status is ReleaseDateParseStatus.INCOMPLETE
    assert result.value is None


def test_thai_weekday_prefix_stripped_before_parsing_day_month() -> None:
    result = parse_release_date_text("พุธที่ 15 กุมภาพันธ์")
    assert result.status is ReleaseDateParseStatus.INCOMPLETE
    assert result.value is None


# --- ไม่มีสัญญาณวันที่ที่จับได้เลย → UNREADABLE ---


def test_season_word_with_year_is_unreadable_not_incomplete() -> None:
    """'SUMMER' ไม่ใช่ชื่อเดือนที่ parser รู้จัก แม้จะมีปี 2021 ต่อท้าย ก็ไม่ถือว่า
    "รู้เดือนแต่ขาดวัน/ปี" — ต้องเป็น UNREADABLE ไม่ใช่ INCOMPLETE"""
    result = parse_release_date_text("SUMMER 2021")
    assert result.status is ReleaseDateParseStatus.UNREADABLE
    assert result.value is None


def test_coming_soon_is_unreadable() -> None:
    result = parse_release_date_text("COMING SOON")
    assert result.status is ReleaseDateParseStatus.UNREADABLE
    assert result.value is None


def test_invalid_calendar_date_is_unreadable() -> None:
    """31 กุมภาพันธ์ไม่มีจริง — ตัวเลขจับได้ครบแต่ไม่ใช่ปฏิทินจริง"""
    result = parse_release_date_text("31/02/2020")
    assert result.status is ReleaseDateParseStatus.UNREADABLE
    assert result.value is None


def test_both_numbers_over_twelve_is_unreadable() -> None:
    """ทั้งสองตัวเลข > 12 ไม่มีทางเป็นเดือนได้เลยสักตัว — ตัดสินไม่ได้แม้แต่จะเดา"""
    result = parse_release_date_text("13/25/99")
    assert result.status is ReleaseDateParseStatus.UNREADABLE
    assert result.value is None


def test_zero_cannot_be_day_or_month_is_unreadable_not_ambiguous() -> None:
    """'0/5/23' — 0 ไม่ valid ทั้งเป็นวันและเป็นเดือน ไม่มีการตีความไหนที่ valid เลย
    (ต่างจาก AMBIGUOUS ที่มีการตีความ valid สองทาง) — เคยเป็นบั๊ก: โค้ดเดิมเช็คแค่
    a>12/b>12 แล้วปล่อยเข้า branch AMBIGUOUS ทั้งที่ 0 ตัดสินได้ชัดว่าไม่ valid"""
    result = parse_release_date_text("0/5/23")
    assert result.status is ReleaseDateParseStatus.UNREADABLE
    assert result.value is None


def test_bare_year_only_is_unreadable_not_incomplete() -> None:
    """'2022' จาก CSV จริง — มีปีจับได้แต่ไม่มีชื่อเดือนที่ parser รู้จักเลย ไม่นับเป็น
    "รู้เดือนแต่ขาดวัน/ปี" ตามนิยามของ INCOMPLETE จึงยังเป็น UNREADABLE เหมือนเดิม
    (นี่คือ catch-all ตามนิยามใหม่ของ UNREADABLE ไม่ใช่ "ไม่มีอะไรจับได้เลย" ตรงตัว
    — ดู docstring ของ ReleaseDateParseStatus.UNREADABLE)"""
    result = parse_release_date_text("2022")
    assert result.status is ReleaseDateParseStatus.UNREADABLE
    assert result.value is None


# --- ไม่มี input เลย ---


def test_none_is_no_input() -> None:
    result = parse_release_date_text(None)
    assert result.status is ReleaseDateParseStatus.NO_INPUT
    assert result.value is None


def test_empty_string_is_no_input() -> None:
    result = parse_release_date_text("")
    assert result.status is ReleaseDateParseStatus.NO_INPUT
    assert result.value is None


def test_whitespace_only_is_no_input() -> None:
    result = parse_release_date_text("   ")
    assert result.status is ReleaseDateParseStatus.NO_INPUT
    assert result.value is None


# --- กำกวม: DD/MM ↔ MM/DD ที่ทั้งสองตัวเลข ≤ 12 ---


def test_ambiguous_dd_mm_vs_mm_dd_returns_ambiguous_not_a_guess() -> None:
    """05/06/23 — ทั้ง 5 และ 6 ≤ 12 เป็นได้ทั้ง DD/MM (5 มิ.ย.) และ MM/DD (6 พ.ค.)
    ต้องคืน AMBIGUOUS ห้ามเดาแล้วคืน DATE ใดๆ (ดู module docstring ของ release_date.py)
    """
    result = parse_release_date_text("05/06/23")
    assert result.status is ReleaseDateParseStatus.AMBIGUOUS
    assert result.value is None


def test_ambiguous_equal_day_and_month_is_not_actually_ambiguous() -> None:
    """05/05/23 — วันและเดือนเท่ากัน ตีความแบบไหนก็ได้ผลลัพธ์เดียวกัน จึง parse ได้"""
    result = parse_release_date_text("05/05/23")
    assert result.status is ReleaseDateParseStatus.PARSED
    assert result.value == date(2023, 5, 5)


# --- pivot ปีสองหลัก: ต้องเป็นค่าคงที่ ไม่ขึ้นกับเวลาปัจจุบัน ---


def test_two_digit_year_pivot_is_a_fixed_constant() -> None:
    """ล็อกค่า pivot ไว้ตรงๆ — กัน regression ถ้ามีใครเผลอเปลี่ยนเป็นการคำนวณจาก
    วันที่ปัจจุบันในอนาคต (ค่านี้ต้องไม่ขยับเองตามเวลาที่รันเทส)"""
    assert TWO_DIGIT_YEAR_PIVOT == 69


def test_expand_two_digit_year_below_pivot_maps_to_2000s() -> None:
    assert _expand_two_digit_year(0) == 2000
    assert _expand_two_digit_year(68) == 2068


def test_expand_two_digit_year_at_and_above_pivot_maps_to_1900s() -> None:
    assert _expand_two_digit_year(69) == 1969
    assert _expand_two_digit_year(99) == 1999


def test_expand_two_digit_year_returns_same_value_on_repeated_calls_in_one_process() -> (
    None
):
    """ล็อกว่า `_expand_two_digit_year`/`parse_release_date_text` เป็น pure function
    ที่คืนค่าเดิมทุกครั้งที่เรียกด้วย input เดิม **ภายในโปรเซสเดียวกัน**

    ⚠️ test นี้**ไม่ได้พิสูจน์**ว่าผลลัพธ์ time-independent จริง — เรียกฟังก์ชันเดิมซ้ำ
    ในโปรเซสเดียว วันที่ปัจจุบันไม่เปลี่ยนระหว่างสองการเรียกอยู่แล้วไม่ว่าฟังก์ชันจะผูก
    กับเวลาปัจจุบันหรือไม่ (code-critic พิสูจน์แล้วว่า monkeypatch ให้คำนวณ pivot จาก
    `date.today().year % 100 + 1` assertion ทั้งหมดของ test แบบนี้ก็ยังผ่านหมด) —
    การพิสูจน์ time-independence ตัวจริงอยู่ที่
    `test_year_expansion_pipeline_source_has_no_reference_to_current_time` ด้านล่าง
    ซึ่งตรวจที่ระดับซอร์สโค้ดแทน"""
    first = parse_release_date_text("11/15/02")
    second = parse_release_date_text("11/15/02")
    assert first.value == second.value == date(2002, 11, 15)


# ฟังก์ชันทั้งหมดที่อยู่ในสายคำนวณ/ใช้ปีจาก _expand_two_digit_year — ถ้าใครในนี้เผลอ
# เปลี่ยนไปคำนวณ pivot จาก datetime.now()/date.today() แทนค่าคงที่ TWO_DIGIT_YEAR_PIVOT
# test ด้านล่างต้องจับได้ (ต่างจาก test ด้านบนที่จับไม่ได้)
_YEAR_PIVOT_PIPELINE = (
    release_date_module._expand_two_digit_year,
    release_date_module._apply_buddhist_era,
    release_date_module._expand_year_component,
    release_date_module._resolve_year,
    release_date_module._parse_numeric,
    release_date_module._parse_numeric_month_day,
    release_date_module._parse_named,
    release_date_module.parse_release_date_text,
)
_FORBIDDEN_TIME_TOKENS = ("now", "today", "utcnow", "time.time")


def _code_only_source(fn: object) -> str:
    """คืน source ของฟังก์ชันแบบ "โค้ดล้วน" — ตัด docstring กับ comment ออกหมดด้วย
    `ast.unparse` (unparse ไม่เก็บ comment อยู่แล้วเพราะไม่ใช่ส่วนหนึ่งของ AST) ตัด
    docstring ออกเองเพิ่มอีกชั้น เพราะ `parse_release_date_text` มี docstring ที่พูดถึง
    `datetime.now()` ในเชิง **อธิบายว่าไม่ใช้** (ดู module) ถ้าไม่ตัดออกจะ false-positive
    ทันที ต้องดูเฉพาะโค้ดที่รันจริงเท่านั้น"""
    tree = ast.parse(inspect.getsource(fn))
    func_node = tree.body[0]
    body = func_node.body  # type: ignore[attr-defined]
    if (
        body
        and isinstance(body[0], ast.Expr)
        and isinstance(body[0].value, ast.Constant)
        and isinstance(body[0].value.value, str)
    ):
        func_node.body = body[1:]  # type: ignore[attr-defined]
    return ast.unparse(func_node).lower()


def test_year_expansion_pipeline_source_has_no_reference_to_current_time() -> None:
    """พิสูจน์ time-independence จริง (ไม่ใช่แค่เรียกซ้ำแล้วเทียบค่าแบบ test ด้านบน)
    ด้วยการตรวจซอร์สโค้ด (ไม่รวม docstring/comment) ตรงๆ ว่าทุกฟังก์ชันในสายคำนวณปี
    สองหลักไม่มีการอ้างถึงเวลาปัจจุบันเลย (`datetime.now()`, `date.today()`,
    `datetime.utcnow()`, `time.time()`)

    test นี้จะ **fail จริง** ถ้ามีใครเปลี่ยนโค้ดไปคำนวณ pivot จากเวลาปัจจุบัน — ต่างจาก
    test แบบเรียกซ้ำในโปรเซสเดียวที่พิสูจน์อะไรไม่ได้เลย (ดู docstring ของ test ด้านบน)
    """
    violations = []
    for fn in _YEAR_PIVOT_PIPELINE:
        source = _code_only_source(fn)
        for token in _FORBIDDEN_TIME_TOKENS:
            if token in source:
                violations.append(f"{fn.__name__}() มีคำว่า {token!r}")
    assert (
        violations == []
    ), "ฟังก์ชันในสายคำนวณปีสองหลักห้ามอ้างถึงเวลาปัจจุบัน: " + "; ".join(violations)
