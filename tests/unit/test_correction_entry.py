"""Unit tests ของ `scripts/seed/correction_entry.py` — ADR-0010 Amendment 2026-08-09

ไม่ต่อ DB จริง — เกือบทั้งหมดทำกับฟังก์ชัน pure (`parse_rows`, `parse_is_unique`,
`plan_writes`, `audit_entries`, `verify_corrections`) ซึ่งรับสถานะเข้ามาแทนการ query
เอง ตาม ship-backend-change §3

🔴 **สาม invariant ที่ AC-8 สั่งให้พิสูจน์ด้วย mutation — และที่ที่เทสไปยืน**

| # | mutation | ตรรกะอยู่ที่ | ตัวฆ่าในไฟล์นี้ |
|---|---|---|---|
| 1 | `value_before=None` เสมอ | `audit_entries()` **pure** | §audit — ทั้งเทส pure และเทส runtime ที่เก็บ kwargs จาก session ปลอม |
| 2 | ปล่อยแถวไม่มี `reason` ผ่าน | `parse_rows()` **pure** | §reason — ปฏิเสธ + **positive control** + `run()` ไม่แตะ session |
| 3 | เติมฟิลด์ที่สามเข้า allowlist | `WRITABLE_FIELDS` + fail-closed ในลูป + `choices` | §closed-world สามชั้น |

ตัวที่ (1) **เคยรอดเทสทั้ง 74 ตัวมาแล้วจริง** เมื่อ 2026-08-07 เพราะตรรกะนั้นอยู่ในลูป
ที่ต้องมี DB ถึงจะรันได้ — ที่นี่จึงบังคับว่ามันต้องเป็นฟังก์ชัน pure และมีเทสที่แตะ
มันตรง ๆ ไม่ใช่แตะผ่าน `run()` อย่างเดียว
"""

from __future__ import annotations

import argparse
import ast
import csv
import inspect
import sys
import uuid
from datetime import datetime
from pathlib import Path

import pytest

from app.models.enums import PosterCondition
from app.models.poster import Poster
from scripts.seed import correction_entry as mod
from scripts.seed import manual_entry as manual_mod
from scripts.seed.correction_entry import (
    CORRECTION_SHEET_COLUMNS,
    CURRENT_COLUMNS,
    IS_UNIQUE_ONLY_WRITABLE_VALUE,
    IS_UNIQUE_WORDS,
    REASON_COLUMNS,
    REQUIRED_COLUMNS,
    WRITABLE_FIELDS,
    AuditEntry,
    CorrectionRow,
    PosterState,
    PrecheckError,
    RowAction,
    assert_own_sheet,
    assert_schema_ready,
    audit_entries,
    field_specs,
    parse_is_unique,
    parse_rows,
    plan_writes,
    planned_field_counts,
    read_sheet,
    refuse_unwritable_value,
    render_value,
    rows_still_marked_as_multi_piece,
    verify_corrections,
)

PID = uuid.UUID("11111111-1111-1111-1111-111111111111")
PID2 = uuid.UUID("22222222-2222-2222-2222-222222222222")
PID3 = uuid.UUID("33333333-3333-3333-3333-333333333333")
REVIEWED_AT = datetime.fromisoformat("2026-08-08T20:00:00+07:00")

WHY_GRADE = "ดูใบจริงซ้ำ พบรอยพับที่มุมล่างขวาซึ่งไม่ได้บันทึกไว้รอบแรก"
WHY_UNIQUE = "นับใบจริงในกล่องแล้วมีใบเดียว"


def _raw(**over: str) -> dict[str, str]:
    row = {
        "poster_uuid": str(PID),
        "title": "Some Poster",
        "image_url": "https://example.invalid/a.jpg",
        "current_condition_grade": "near_mint",
        "current_is_unique": "True",
        "condition_grade": "",
        "condition_grade_reason": "",
        "is_unique": "",
        "is_unique_reason": "",
    }
    row.update(over)
    return row


def _row(**over: object) -> CorrectionRow:
    base: dict[str, object] = {
        "poster_uuid": PID,
        "values": {"condition_grade": PosterCondition.fine},
        "reasons": {"condition_grade": WHY_GRADE},
        "lineno": 2,
    }
    base.update(over)
    return CorrectionRow(**base)  # type: ignore[arg-type]


def _state(**over: object) -> PosterState:
    values: dict[str, object] = {
        "condition_grade": PosterCondition.near_mint,
        "is_unique": True,
    }
    values.update(over)
    return PosterState(values=values)


# --------------------------------------------------------------------------
# mutation 3 — closed-world สามชั้นว่าเขียนได้เฉพาะสองคอลัมน์ (AC-6)
# --------------------------------------------------------------------------

POSTER_COLUMNS = set(Poster.__table__.columns.keys())


def _names_the_module_mentions(module) -> set[str]:
    """ชื่อทุกตัวที่โมดูลเอ่ยถึงในซอร์ส — **string literal และ `<obj>.attr`**

    🔴 `ast.Attribute.attr` เป็น `str` ธรรมดา **ไม่ใช่ `ast.Constant`** — การสแกนหา
    เฉพาะ literal จึงมองไม่เห็น `poster.needs_review = False` เลยแม้แต่น้อย
    (พิสูจน์แล้วโดย `code-critic` 2026-08-08 บนเส้นที่ 4)
    """
    tree = ast.parse(inspect.getsource(module))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            names.add(node.value)
        elif isinstance(node, ast.Attribute):
            names.add(node.attr)
    return names


def test_the_only_poster_columns_this_module_names_are_the_ones_it_may_touch() -> None:
    """🔴 ชั้นที่ 1 จาก 3 — closed-world ระดับซอร์ส

    **จับได้:** ชื่อคอลัมน์ที่เขียนตรง ๆ ไม่ว่าจะมาทาง `poster.<col> = …` หรือทาง
    string literal ในทูเพิล/dict/`setattr` ใด ๆ · โดยเฉพาะ `status` และ
    `published_at` ซึ่ง skill `poster-database` §3 กับ ADR-0010 D8 ห้ามเส้นทางแบบนี้
    แตะตลอดกาล

    🔴 **จับไม่ได้: ชื่อที่ประกอบขึ้นตอนรัน** — ชั้นที่ปิดช่องนั้นคือ
    `test_run_writes_nothing_outside_the_writable_set`

    สองชื่อที่ติดมาโดยไม่ใช่การเขียน — ชั้นที่ 3 พิสูจน์ว่าไม่เคยถูกเซ็ต:
    · `title` = คอลัมน์ที่ใบงานแสดงให้คนอ่าน (อยู่ใน `CORRECTION_SHEET_COLUMNS`)
    · `id` = `Poster.id` ที่ `_load_state()` ใช้เป็นคีย์ตอน **อ่าน**
    """
    named = _names_the_module_mentions(mod) & POSTER_COLUMNS
    assert named == {*WRITABLE_FIELDS, "title", "id"}


def test_writable_set_is_exactly_the_two_columns_of_the_amendment() -> None:
    """🔴 ชั้นที่ 2 จาก 3 — ADR-0010 A-D2 ข้อ 6 · การเพิ่มฟิลด์ต้องผ่าน ADR ก่อน
    ไม่ใช่แก้ค่าคงที่เงียบ ๆ แล้วเทสเดิมยังเขียว"""
    assert WRITABLE_FIELDS == ("condition_grade", "is_unique")
    assert len(WRITABLE_FIELDS) == 2
    # ฟิลด์ที่เคยมีคนเสนอให้ยัดเข้ามา — ต้องไม่มีทางหลุดเข้าเงียบ ๆ
    for forbidden in ("status", "published_at", "price", "needs_review", "title"):
        assert forbidden not in WRITABLE_FIELDS


def test_every_writable_field_has_a_spec_and_vice_versa() -> None:
    assert set(field_specs()) == set(WRITABLE_FIELDS)


def test_the_cli_refuses_a_field_outside_the_allowlist(monkeypatch) -> None:
    """AC-6 ตัวอักษร — *"ปฏิเสธฟิลด์นอกรายการตั้งแต่ชั้น CLI"* · ต้องตกที่ argparse
    (`SystemExit(2)`) ไม่ใช่ไปตกทีหลังตอนจะเขียน"""
    monkeypatch.setattr(sys, "argv", ["correction_entry.py", "--field", "price"])
    with pytest.raises(SystemExit) as exc:
        mod.main()
    assert exc.value.code == 2


def test_the_cli_choices_are_the_allowlist_object_itself_not_a_copy() -> None:
    """ถ้า `choices` เป็นสำเนา วันที่ allowlist หด CLI จะยังรับฟิลด์เก่าอยู่เงียบ ๆ"""
    tree = ast.parse(inspect.getsource(mod.main))
    choices = [
        ast.unparse(kw.value)
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        for kw in node.keywords
        if kw.arg == "choices"
    ]
    assert "WRITABLE_FIELDS" in choices


def test_this_lane_does_not_widen_the_overwrite_flag_of_lane_three() -> None:
    """🔴 A-D4 ข้อ 3 — `--allow-overwrite` ต้องไม่เปลี่ยนเลยสักฟิลด์ · ทั้งสองชุด
    ต้องไม่ทับกัน ไม่งั้นจะมีสองเส้นทางเขียนฟิลด์เดียวกันคนละกฎ"""
    assert set(manual_mod.OVERWRITE_ELIGIBLE) == {"title", "year"}
    assert set(manual_mod.OVERWRITE_ELIGIBLE).isdisjoint(WRITABLE_FIELDS)


def test_the_grade_parser_is_the_same_object_as_lane_three_not_a_copy() -> None:
    """`exact_case=True` คือด่านที่ทำให้ `Fine` ไม่ถูกแปลงเป็น `fine` เงียบ ๆ
    (เกิดจริง 8 แถวเมื่อ 2026-08-07) — สำเนาที่ drift ได้ = ด่านที่หายไปครึ่งเดียว"""
    assert mod._enum_parser is manual_mod._enum_parser
    assert mod.render_value is manual_mod.render_value
    assert mod.TARGETS is manual_mod.TARGETS
    assert mod.assert_target is manual_mod.assert_target


def test_production_is_not_a_selectable_target() -> None:
    assert mod.TARGETS == ("dev", "sit")


# --------------------------------------------------------------------------
# ใบงาน — คอลัมน์ และ `current_*` ที่สคริปต์ห้ามอ่าน
# --------------------------------------------------------------------------


def test_the_sheet_has_a_reason_column_per_writable_field() -> None:
    """มติเจ้าของ 2026-08-09 — เหตุผลของเกรดกับของจำนวนเป็นคนละเรื่อง ก้อนเดียว
    ที่ถูกก๊อปลงสองแถว audit จะอ่านย้อนแล้วแยกไม่ออกว่าอธิบายอันไหน"""
    assert CORRECTION_SHEET_COLUMNS == (
        "poster_uuid",
        "title",
        "image_url",
        "current_condition_grade",
        "current_is_unique",
        "condition_grade",
        "condition_grade_reason",
        "is_unique",
        "is_unique_reason",
    )
    assert REASON_COLUMNS == ("condition_grade_reason", "is_unique_reason")
    assert len(REASON_COLUMNS) == len(WRITABLE_FIELDS)


def test_the_key_is_the_uuid_never_the_title() -> None:
    """🔴 ข้อมูลจริงมีชื่อซ้ำข้ามใบ (ใบ THEATRICAL กับ ADVANCE ของหนังเรื่องเดียวกัน)
    — คีย์ที่เป็นชื่อจะจับคู่ผิดใบแล้วทับเกรดของใบที่ไม่ได้ตรวจ"""
    assert REQUIRED_COLUMNS[0] == "poster_uuid"
    assert "title" not in REQUIRED_COLUMNS


class _RecordingRow(dict):
    """dict ที่จำว่าใครอ่านคีย์อะไรไปบ้าง — ทั้ง `row[k]` และ `row.get(k)`."""

    def __init__(self, data: dict, seen: set[str]) -> None:
        super().__init__(data)
        self.seen = seen

    def get(self, key, default=None):  # noqa: ANN001, ANN206
        self.seen.add(key)
        return super().get(key, default)

    def __getitem__(self, key):  # noqa: ANN001, ANN204
        self.seen.add(key)
        return super().__getitem__(key)


def test_parse_rows_reads_only_the_required_columns_never_the_current_ones() -> None:
    """🔴 `current_*` เป็นช่องช่วยจำของคน (precedent: `previous_note` ของเส้นที่ 4)

    ถ้าสคริปต์อ่านมัน ค่าที่ใช้ตัดสินว่า "ทับอะไร" จะมาจาก **ไฟล์ที่อาจเก่าไปแล้ว**
    แทนที่จะมาจาก DB สด ๆ — แล้ว `value_before` ใน audit จะบันทึกค่าที่ไม่เคยอยู่ใน DB

    🔴 **closed-world ที่ runtime ไม่ใช่การไล่ literal** — การไล่ literal ปล่อย
    `raw.get(CORRECTION_SHEET_COLUMNS[3])` และ `raw.get("current_" + name)` ผ่าน
    """
    seen: set[str] = set()
    rows = [
        _RecordingRow(
            _raw(condition_grade="fine", condition_grade_reason=WHY_GRADE), seen
        ),
        _RecordingRow(
            _raw(poster_uuid=str(PID2), is_unique="Y", is_unique_reason=WHY_UNIQUE),
            seen,
        ),
        _RecordingRow(_raw(poster_uuid=str(PID3)), seen),  # เว้นว่างทั้งหมด
    ]
    parse_rows(rows)  # type: ignore[arg-type]
    assert seen == set(REQUIRED_COLUMNS)
    assert seen.isdisjoint(CURRENT_COLUMNS)


def test_current_columns_have_no_place_to_land_in_the_parsed_row() -> None:
    """ชั้นโครงสร้าง — ไม่มีฟิลด์ให้เก็บ แปลว่าไม่มีชั้นไหนข้างล่างอ่านมันได้เลย"""
    fields = {f.name for f in CorrectionRow.__dataclass_fields__.values()}
    assert fields.isdisjoint(CURRENT_COLUMNS)
    assert set(CURRENT_COLUMNS).isdisjoint(REQUIRED_COLUMNS)


def test_missing_required_column_is_reported_by_name(tmp_path) -> None:
    path = tmp_path / "correction-entry.csv"
    path.write_text("poster_uuid,condition_grade\n", encoding="utf-8")
    with pytest.raises(PrecheckError, match="condition_grade_reason"):
        read_sheet(path)


# --------------------------------------------------------------------------
# mutation 2 — reason บังคับต่อค่า · ขาดแถวเดียว = ปฏิเสธทั้งไฟล์ (AC-2)
# --------------------------------------------------------------------------


def test_one_row_without_a_reason_rejects_the_whole_file() -> None:
    """🔴 **หัวใจของ AC-2** — ปฏิเสธ *ทั้งไฟล์* ไม่ใช่ข้ามแถวนั้น

    การข้ามแถวจะทำให้ไฟล์ที่คนกรอกผิดกติกา *เขียนบางส่วนสำเร็จ* ซึ่งอ่านย้อนแล้ว
    แยกไม่ออกว่าแถวไหนตั้งใจไม่แก้ กับแถวไหนตั้งใจแก้แต่ลืมเหตุผล
    """
    with pytest.raises(PrecheckError) as exc:
        parse_rows(
            [
                _raw(condition_grade="fine", condition_grade_reason=WHY_GRADE),
                _raw(poster_uuid=str(PID2), condition_grade="good"),  # ← ขาดเหตุผล
                _raw(
                    poster_uuid=str(PID3),
                    is_unique="Y",
                    is_unique_reason=WHY_UNIQUE,
                ),
            ]
        )
    text = str(exc.value)
    assert "condition_grade_reason ว่าง" in text
    assert "บรรทัด 3" in text
    assert "ไม่เขียนอะไรเลยทั้งไฟล์" in text


def test_the_very_same_file_with_the_reason_filled_in_produces_three_rows() -> None:
    """🔴 **positive control** — ถ้าไม่มีตัวนี้ ด่านที่ปฏิเสธ *ทุก* ไฟล์ก็ยังเขียว
    ทั้งชุด · ต่างจากเทสข้างบนแค่ช่องเดียวเท่านั้น"""
    rows = parse_rows(
        [
            _raw(condition_grade="fine", condition_grade_reason=WHY_GRADE),
            _raw(
                poster_uuid=str(PID2),
                condition_grade="good",
                condition_grade_reason="ตรวจซ้ำแล้วสีซีดกว่าที่บันทึกไว้",
            ),
            _raw(poster_uuid=str(PID3), is_unique="Y", is_unique_reason=WHY_UNIQUE),
        ]
    )
    assert len(rows) == 3
    assert [sorted(r.reasons) for r in rows] == [
        ["condition_grade"],
        ["condition_grade"],
        ["is_unique"],
    ]


def test_every_parsed_value_always_carries_a_reason_with_the_same_keys() -> None:
    """invariant ที่ `audit_entries()` พึ่ง — ถ้ามันแตก audit จะ `KeyError` ตอนรัน"""
    rows = parse_rows(
        [
            _raw(
                condition_grade="fine",
                condition_grade_reason=WHY_GRADE,
                is_unique="Y",
                is_unique_reason=WHY_UNIQUE,
            )
        ]
    )
    assert set(rows[0].values) == set(rows[0].reasons) == set(WRITABLE_FIELDS)


def test_a_reason_without_a_value_rejects_the_whole_file() -> None:
    """ข้อมูลขัดกันเอง ไม่ใช่ข้อมูลเพิ่ม — อธิบายการแก้ที่ไม่ได้เกิดขึ้นไม่ได้"""
    with pytest.raises(PrecheckError, match="ข้อมูลขัดกันเอง"):
        parse_rows([_raw(condition_grade_reason=WHY_GRADE)])


def test_both_blank_is_normal_and_produces_a_row_with_nothing_to_write() -> None:
    (row,) = parse_rows([_raw()])
    assert row.values == {}
    assert row.reasons == {}


def test_a_missing_reason_on_the_second_field_still_rejects_the_file() -> None:
    """ด่านต้องครอบทุกฟิลด์ใน allowlist ไม่ใช่แค่ฟิลด์แรก"""
    with pytest.raises(PrecheckError, match="is_unique_reason ว่าง"):
        parse_rows(
            [
                _raw(
                    condition_grade="fine",
                    condition_grade_reason=WHY_GRADE,
                    is_unique="Y",
                )
            ]
        )


def test_bad_uuid_rejects_the_file() -> None:
    with pytest.raises(PrecheckError, match="ไม่ใช่ UUID"):
        parse_rows([_raw(poster_uuid="not-a-uuid")])


def test_duplicate_poster_uuid_rejects_the_file() -> None:
    with pytest.raises(PrecheckError, match="ซ้ำกับแถวก่อนหน้า"):
        parse_rows(
            [
                _raw(condition_grade="fine", condition_grade_reason=WHY_GRADE),
                _raw(condition_grade="good", condition_grade_reason=WHY_GRADE),
            ]
        )


# --------------------------------------------------------------------------
# AC-7 — `is_unique` เป็น boolean ที่ปฏิเสธค่ากำกวมทั้งไฟล์
# --------------------------------------------------------------------------


@pytest.mark.parametrize("raw", ["Y", "y"])
def test_yes_parses_to_true(raw: str) -> None:
    assert parse_is_unique(raw) is True


@pytest.mark.parametrize("raw", ["N", "n"])
def test_no_parses_to_false(raw: str) -> None:
    assert parse_is_unique(raw) is False


def test_the_words_the_sheet_prints_are_the_words_the_parser_reads() -> None:
    """🔴 G7 — ฝั่งพิมพ์กับฝั่งอ่านต้องเป็น **ของชิ้นเดียวกัน** ไม่ใช่สองรายชื่อที่
    บังเอิญตรงกันวันนี้

    `IS_UNIQUE_TEXT` ต้อง derive จาก `IS_UNIQUE_WORDS` — ถ้าใครมาพิมพ์รายชื่อที่สอง
    ไว้เอง วันที่แก้ฝั่งหนึ่งอีกฝั่งจะเงียบ แล้วใบงานก็จะกลับไปสอนคำที่พาร์เซอร์
    ปฏิเสธอีกครั้ง (หลักเดียวกับที่โมดูลนี้ import `_enum_parser` ของเส้นที่ 3
    แทนการก๊อป) · พฤติกรรมปลายทางอยู่ที่ `test_make_correction_sheet.py` §round-trip
    """
    assert set(mod.IS_UNIQUE_TEXT) == set(IS_UNIQUE_WORDS.values())
    for value, word in mod.IS_UNIQUE_TEXT.items():
        assert parse_is_unique(word) is value


@pytest.mark.parametrize(
    "raw", ["1", "0", "true", "false", "True", "False", "yes", "no", "-", "ใช่"]
)
def test_ambiguous_values_are_refused_not_coerced(raw: str) -> None:
    """🔴 ค่าเหล่านี้ถูกปฏิเสธ **โดยเจตนา** ไม่ใช่เพราะยังไม่ได้รองรับ"""
    with pytest.raises(ValueError):
        parse_is_unique(raw)


@pytest.mark.parametrize("raw", ["1", "0"])
def test_the_error_explains_why_a_bare_number_is_the_dangerous_one(raw: str) -> None:
    """🔴 ข้อความต้องบอก *เหตุผล* ไม่ใช่แค่ว่าใช้ไม่ได้ — คนที่เพิ่งนับใบเสร็จแล้ว
    พิมพ์ `1` ต้องเข้าใจว่าทำไมช่องนี้ไม่รับตัวเลข ไม่งั้นจะเดาว่าเป็นบั๊ก

    `0` คือเคส `THE MATRIX (ADVANCE 4K)` เป๊ะ ๆ: `quantity = 0` จากไฟล์ export
    กลายเป็น `is_unique = false` แล้วของขึ้นหน้าร้านทั้งที่ไม่มีใครนับ (ADR-0019)
    """
    with pytest.raises(ValueError) as exc:
        parse_is_unique(raw)
    text = str(exc.value)
    assert "Y หรือ N" in text
    assert "โดยเจตนา" in text
    assert "นับ" in text


def test_a_bad_is_unique_value_rejects_the_whole_file_not_just_the_row() -> None:
    with pytest.raises(PrecheckError, match="is_unique —"):
        parse_rows(
            [
                _raw(condition_grade="fine", condition_grade_reason=WHY_GRADE),
                _raw(poster_uuid=str(PID2), is_unique="1", is_unique_reason=WHY_UNIQUE),
            ]
        )


def test_a_wrongly_cased_grade_rejects_the_whole_file() -> None:
    """BR-05 — ฟิลด์นี้ลูกค้าใช้ตัดสินใจซื้อ สคริปต์จึงไม่แปลงตัวพิมพ์ให้เอง"""
    with pytest.raises(PrecheckError, match="ตัวพิมพ์ไม่ตรง"):
        parse_rows([_raw(condition_grade="Fine", condition_grade_reason=WHY_GRADE)])


# --------------------------------------------------------------------------
# plan_writes — ทับ · ค่าเท่าเดิม · ปลายทางว่าง · ไม่มีใบ · --field
# --------------------------------------------------------------------------


def test_a_real_change_becomes_an_overwrite_with_both_sides_recorded() -> None:
    plan = plan_writes([_row()], {PID: _state()})[0]
    assert plan.action is RowAction.WRITE
    assert plan.field_writes == {"condition_grade": PosterCondition.fine}
    assert plan.overwrites == {"condition_grade": ("near_mint", "fine")}
    assert planned_field_counts([plan]) == {"condition_grade": 1, "is_unique": 0}


def test_the_same_value_again_is_not_a_write_and_leaves_no_audit() -> None:
    """🔴 ADR-0010 D8 — *ค่าเท่าเดิม = ไม่ใช่การเขียน* · ถ้านับเป็น write จะได้
    audit ปลอมที่บอกว่ามีคนแก้ทั้งที่ไม่มีอะไรเปลี่ยน และสคริปต์เลิก idempotent"""
    plan = plan_writes(
        [_row(values={"condition_grade": PosterCondition.near_mint})],
        {PID: _state()},
    )[0]
    assert plan.action is RowAction.SKIP_SAME
    assert plan.field_writes == {}
    assert plan.overwrites == {}
    assert plan.unchanged == {"condition_grade": "near_mint"}
    assert audit_entries(plan) == ()


def test_rerunning_the_same_sheet_writes_nothing_the_second_time() -> None:
    """idempotent — ผลพลอยได้ของกฎ *ค่าเท่าเดิมไม่ใช่การเขียน*"""
    rows = parse_rows([_raw(condition_grade="fine", condition_grade_reason=WHY_GRADE)])
    first = plan_writes(rows, {PID: _state()})
    assert planned_field_counts(first) == {"condition_grade": 1, "is_unique": 0}
    after = _state(condition_grade=PosterCondition.fine)
    second = plan_writes(rows, {PID: after})
    assert planned_field_counts(second) == dict.fromkeys(WRITABLE_FIELDS, 0)


def test_a_null_grade_is_skipped_and_pointed_at_lane_three() -> None:
    """🔴 นี่คือกลไกที่ทำให้ **AC-4 จริงโดยโครงสร้าง** — ฟิลด์เดียวที่เป็น `NULL`
    ได้ถูกกันออกตั้งแต่ตอนวางแผน `value_before` จึงไม่มีทางเป็น `None`

    เส้นนี้ *แก้* ไม่ใช่ *เติม* — การเติมช่องว่างเป็นงานของเส้นที่ 3 ซึ่งมี ADR-0015
    D6 คุมอยู่คนละชุดกัน
    """
    plan = plan_writes([_row()], {PID: _state(condition_grade=None)})[0]
    assert plan.action is RowAction.SKIP_NO_TARGET
    assert plan.field_writes == {}
    assert plan.no_target == ("condition_grade",)
    assert audit_entries(plan) == ()


def test_is_unique_is_still_correctable_on_a_poster_without_a_grade() -> None:
    """`is_unique` เป็น `NOT NULL` จึงมีค่าเดิมเสมอ — การข้าม *ทั้งแถว* เพราะเกรดว่าง
    จะปิดทางแก้ฟิลด์ที่ไม่ได้ขึ้นกับเกรดเลย (เคส `N` มีด่าน ADR-0019 D1 ของตัวเอง)"""
    plan = plan_writes(
        [_row(values={"is_unique": True}, reasons={"is_unique": WHY_UNIQUE})],
        {PID: _state(condition_grade=None, is_unique=False)},
    )[0]
    assert plan.action is RowAction.WRITE
    assert plan.overwrites == {"is_unique": ("False", "True")}


def test_a_poster_that_is_not_in_the_database_is_skipped_never_inserted() -> None:
    """ADR-0015 D5 ตกทอดมาทั้งดุ้น — UPDATE เท่านั้น"""
    plan = plan_writes([_row()], {})[0]
    assert plan.action is RowAction.SKIP_NOT_FOUND
    assert plan.field_writes == {}
    assert audit_entries(plan) == ()


def test_field_narrows_what_is_written_but_never_what_is_validated() -> None:
    """`--field` เลือกว่าจะ *เขียน* อะไร ไม่ใช่ว่าจะ *ตรวจ* อะไร — ถ้าผูกสองอย่างนี้
    เข้าด้วยกัน `--field condition_grade` จะกลายเป็นทางเลี่ยงด่าน reason ของอีกฟิลด์"""
    row = _row(
        values={"condition_grade": PosterCondition.fine, "is_unique": True},
        reasons={"condition_grade": WHY_GRADE, "is_unique": WHY_UNIQUE},
    )
    plan = plan_writes([row], {PID: _state(is_unique=False)}, ("condition_grade",))[0]
    assert set(plan.field_writes) == {"condition_grade"}
    assert set(plan.overwrites) == {"condition_grade"}


def test_field_defaults_to_both_columns() -> None:
    row = _row(
        values={"condition_grade": PosterCondition.fine, "is_unique": True},
        reasons={"condition_grade": WHY_GRADE, "is_unique": WHY_UNIQUE},
    )
    plan = plan_writes([row], {PID: _state(is_unique=False)})[0]
    assert set(plan.field_writes) == set(WRITABLE_FIELDS)


def test_plan_writes_never_plans_anything_outside_the_writable_set() -> None:
    """closed-world ที่ runtime ของชั้นวางแผน — ครอบทุกสาขาของ `plan_writes()`"""
    rows = [
        _row(),
        _row(
            poster_uuid=PID2,
            values={"is_unique": True},
            reasons={"is_unique": WHY_UNIQUE},
            lineno=3,
        ),
        _row(poster_uuid=PID3, values={}, reasons={}, lineno=4),
    ]
    plans = plan_writes(
        rows,
        {
            PID: _state(),
            PID2: _state(is_unique=False),
            PID3: _state(),
        },
    )
    written: set[str] = set()
    for plan in plans:
        assert set(plan.field_writes) <= set(WRITABLE_FIELDS)
        written |= set(plan.field_writes)
    assert written == set(WRITABLE_FIELDS)


# --------------------------------------------------------------------------
# ADR-0019 D5 · D6 — `is_unique = N` เขียนไม่ได้เลย **ไม่มีเงื่อนไข**
# --------------------------------------------------------------------------
#
# ‹กลับด้านจากรุ่นแรก 2026-08-09 หลัง code-critic รอบที่ 1› รุ่นแรกเทสว่า *"`N` ได้
# เฉพาะเกรด mint"* ตาม **D1** ซึ่งอ่าน ADR ไม่ครบ: **D5** ปิดท้ายว่า *"แม้ใบ `mint`
# ก็เก็บเป็น 1 แถว 1 ชิ้น — D1 คือสิทธิ์ที่ยังไม่มีเครื่องมือรองรับ"* และ **D6** เขียน
# หัวข้อว่า `is_unique` ต้องเป็น `true` **ทุกแถว** · เก็บบันทึกไว้เพราะการกลับด้าน
# คำตอบของเทสโดยไม่บอกว่า *อะไรเปลี่ยน* แยกไม่ออกจากการอ่อนข้อให้โค้ดที่พัง


def test_the_parser_still_reads_n_because_it_is_not_an_ambiguous_value() -> None:
    """🔴 **"อ่านไม่ออก" กับ "อ่านออกแต่ห้าม" ต้องแยกกัน** — AC-7 พูดถึงค่า*กำกวม*
    (`1`/`0`/`true`) ส่วน `N` ไม่กำกวมเลย มันชัดเจนแต่ไม่ได้รับอนุญาต ·
    ถ้ายุบสองอย่างเข้าด้วยกัน คนที่พิมพ์ `N` ถูกตามที่เข้าใจจะได้ข้อความว่าพิมพ์ผิด
    """
    assert parse_is_unique("N") is False
    assert parse_is_unique("n") is False


@pytest.mark.parametrize("grade", list(PosterCondition), ids=lambda g: g.value)
def test_writing_n_is_refused_on_every_grade_including_mint(
    grade: PosterCondition,
) -> None:
    """🔴 **ADR-0019 D5 · D6** — parametrize ทั้ง enum **รวม `mint`** เพื่อไม่ให้ใคร
    เปิดช่องให้เกรดใดเกรดหนึ่งทีหลังโดยไม่มีอะไรฟ้อง

    ด่านอยู่ที่ `parse_rows()` เพราะกฎนี้ **ไม่ต้องรู้สถานะ DB เลย** — ซึ่งเป็นเหตุผล
    เดียวกับที่เทสตัวนี้ส่งเกรดเข้าไปได้ทุกค่าโดยผลไม่เปลี่ยน
    """
    with pytest.raises(PrecheckError) as exc:
        parse_rows(
            [
                _raw(
                    condition_grade=grade.value,
                    condition_grade_reason=WHY_GRADE,
                    is_unique="N",
                    is_unique_reason=WHY_UNIQUE,
                )
            ]
        )
    text = str(exc.value)
    assert "อ่านออก" in text and "เขียนไม่ได้ในระบบวันนี้" in text
    assert "D5" in text and "D6" in text
    assert "amendment" in text
    assert "INF-22" in text
    assert "ห้ามทยอย" in text


def test_writing_n_is_refused_even_when_the_row_is_already_false() -> None:
    """`N` บนแถวที่เป็น `false` อยู่แล้วก็ยังปฏิเสธ — ไม่ปล่อยให้ไหลไปเป็น "ค่าเท่าเดิม"
    แล้วเงียบ · คนที่กรอก `N` เข้าใจโมเดลผิด และไฟล์ fail-closed มีไว้เพื่อบอกเขา"""
    with pytest.raises(PrecheckError, match="เขียนไม่ได้ในระบบวันนี้"):
        parse_rows([_raw(is_unique="N", is_unique_reason=WHY_UNIQUE)])


def test_writing_n_refuses_the_whole_file_not_just_that_row() -> None:
    with pytest.raises(PrecheckError) as exc:
        parse_rows(
            [
                _raw(condition_grade="fine", condition_grade_reason=WHY_GRADE),
                _raw(poster_uuid=str(PID2), is_unique="N", is_unique_reason=WHY_UNIQUE),
            ]
        )
    assert "ไม่เขียนอะไรเลยทั้งไฟล์" in str(exc.value)


def test_the_policy_gate_is_the_one_place_and_it_needs_no_database() -> None:
    """`refuse_unwritable_value()` เป็น pure — เรียกได้ตรง ๆ โดยไม่มี state ใด ๆ"""
    assert refuse_unwritable_value("is_unique", True) is None
    assert refuse_unwritable_value("condition_grade", PosterCondition.mint) is None
    assert refuse_unwritable_value("is_unique", False) is not None


def test_true_is_the_only_writable_value_of_is_unique() -> None:
    """ล็อกค่าคงที่ที่ด่านกับเทสอ้างร่วมกัน — ADR-0019 D6"""
    assert IS_UNIQUE_ONLY_WRITABLE_VALUE is True


def test_setting_is_unique_to_yes_is_never_refused_on_any_grade() -> None:
    """🔴 **positive control** — ด่านที่ปฏิเสธ `is_unique` ทุกค่าก็ยังเขียวถ้าไม่มีตัวนี้"""
    plan = plan_writes(
        [_row(values={"is_unique": True}, reasons={"is_unique": WHY_UNIQUE})],
        {PID: _state(condition_grade=PosterCondition.poor, is_unique=False)},
    )[0]
    assert plan.action is RowAction.WRITE
    assert plan.overwrites == {"is_unique": ("False", "True")}


def test_the_mint_plus_false_state_can_no_longer_be_produced_by_this_lane() -> None:
    """🔴 ปิด High อีกข้อของ critic — เดิมด่านยิงเฉพาะตอน *เขียน* `N` แถวที่เป็น
    `mint` + `is_unique=false` อยู่แล้วแล้วรอบนี้ลดเกรดอย่างเดียวจึงผ่านฉลุย

    วันนี้เคสนั้นสร้างจากเส้นนี้ไม่ได้อีก **เพราะ `false` เขียนไม่ได้เลย** ไม่ว่าจะ
    ทางไหน — แถวที่เป็น `mint` + `false` อยู่แล้วยังลดเกรดได้ (เป็นการแก้ที่ถูกต้อง)
    แต่ `is_unique` ของมันไม่มีทางถูกทำให้เป็น `false` โดยรอบนี้
    """
    plans = plan_writes(
        [_row()],  # ลดเกรดอย่างเดียว
        {PID: _state(condition_grade=PosterCondition.mint, is_unique=False)},
    )
    assert plans[0].action is RowAction.WRITE
    assert "is_unique" not in plans[0].field_writes
    # และเส้นทางที่จะทำให้มันเป็น false ถูกตัดตั้งแต่ก่อนถึงชั้นนี้
    with pytest.raises(PrecheckError):
        parse_rows(
            [
                _raw(
                    condition_grade="mint",
                    condition_grade_reason=WHY_GRADE,
                    is_unique="N",
                    is_unique_reason=WHY_UNIQUE,
                )
            ]
        )


def test_no_planned_write_of_is_unique_is_ever_false() -> None:
    """🔴 **assertion เชิงลบระดับแผน** — ครอบทุกแถวที่ผ่าน `parse_rows()` มาได้จริง"""
    rows = parse_rows(
        [
            _raw(is_unique="Y", is_unique_reason=WHY_UNIQUE),
            _raw(
                poster_uuid=str(PID2),
                condition_grade="mint",
                condition_grade_reason=WHY_GRADE,
                is_unique="y",
                is_unique_reason=WHY_UNIQUE,
            ),
        ]
    )
    plans = plan_writes(rows, {PID: _state(is_unique=False), PID2: _state()})
    for plan in plans:
        assert plan.field_writes.get("is_unique", True) is not False
        assert render_value(False) not in {a for _b, a in plan.overwrites.values()}


def test_rows_still_false_after_this_round_are_reported_as_a_warning_only() -> None:
    """🔴 warning ไม่ใช่ด่าน — สภาพนี้มีอยู่ใน DB ก่อนสคริปต์นี้เกิด · ด่านปฏิเสธจะ
    ปฏิเสธใบงานที่ถูกต้องตั้งแต่รันครั้งแรก และปิดทางเดียวที่มีในการ**แก้**สภาพนั้น"""
    plans = plan_writes([_row()], {PID: _state(is_unique=False)})
    assert plans[0].action is RowAction.WRITE
    assert rows_still_marked_as_multi_piece(plans) == (2,)


def test_a_row_this_round_is_fixing_is_not_listed_as_still_false() -> None:
    """🔴 ข้อความบอกว่า *จะยัง* เป็น false หลังรอบนี้ — แถวที่รอบนี้แก้เป็น `true`
    ต้องหลุดออกจากรายการ ไม่งั้นรายงานจะขัดกับสิ่งที่มันเพิ่งบอกว่าจะทำ"""
    plans = plan_writes(
        [_row(values={"is_unique": True}, reasons={"is_unique": WHY_UNIQUE})],
        {PID: _state(is_unique=False)},
    )
    assert plans[0].overwrites == {"is_unique": ("False", "True")}
    assert rows_still_marked_as_multi_piece(plans) == ()


@pytest.mark.parametrize("in_db", list(PosterCondition), ids=lambda g: f"db_{g.value}")
@pytest.mark.parametrize("new", list(PosterCondition), ids=lambda g: f"new_{g.value}")
def test_the_warning_never_looks_at_the_grade_at_all(
    in_db: PosterCondition, new: PosterCondition
) -> None:
    """🔴 หลัง **D5** เกรดไม่เกี่ยวกับความถูกผิดของ `is_unique` อีกต่อไป — `false`
    ผิด **ทุกเกรดรวม `mint`** · คำถามเดียวที่เหลือคือ *ยังเป็น false ไหม*

    รุ่นแรกอ่านเกรด**ใหม่ที่รอบนี้กำลังจะเขียน** แล้วสรุปว่า "มีมาก่อน" ซึ่งเป็นการ
    ยืนยันสาเหตุที่ตัวเองไม่รู้ (code-critic รอบที่ 1)

    🔴 **ต้อง parametrize เกรดที่อยู่ *ใน DB* ด้วย ไม่ใช่แค่เกรดใหม่** — mutation ที่
    เติม `and plan.current["condition_grade"] != "mint"` เข้าไปในตัวกรอง **รอดเทส
    ทั้งชุด 302 ตัว** ตอนที่เทสนี้ยัง fix เกรดใน DB ไว้เป็น `good` ตัวเดียว
    เพราะสาขาที่ mutation เปลี่ยนพฤติกรรมคือสาขา `mint` ซึ่งไม่มีเทสไหนเดินผ่านเลย
    """
    plans = plan_writes(
        [_row(values={"condition_grade": new}, reasons={"condition_grade": WHY_GRADE})],
        {PID: _state(condition_grade=in_db, is_unique=False)},
    )
    assert rows_still_marked_as_multi_piece(plans) == (2,)


def test_a_compliant_row_produces_no_warning() -> None:
    plans = plan_writes([_row()], {PID: _state()})
    assert rows_still_marked_as_multi_piece(plans) == ()


def test_a_poster_missing_from_the_database_is_not_warned_about() -> None:
    """ไม่รู้สถานะจริงของมัน จึงยืนยันอะไรไม่ได้ — เงียบดีกว่าเดา"""
    assert rows_still_marked_as_multi_piece(plan_writes([_row()], {})) == ()


# --------------------------------------------------------------------------
# mutation 1 — audit: `value_before` ต้องเป็นค่าเดิมจริง ห้าม None (AC-4)
# --------------------------------------------------------------------------


def test_audit_records_the_real_old_value_not_none() -> None:
    """🔴 **mutation ที่ AC-8 ข้อ 1 สั่งให้ฆ่า** — ตัวเดียวกับที่รอดเทส 74 ตัวเมื่อ
    2026-08-07 ตอนที่ตรรกะนี้ยังอยู่ในลูปที่ต้องมี DB"""
    plan = plan_writes([_row()], {PID: _state()})[0]
    (entry,) = audit_entries(plan)
    assert entry == AuditEntry(
        field="condition_grade",
        value_before="near_mint",
        value_after="fine",
        reason=WHY_GRADE,
    )


def test_no_audit_entry_of_this_lane_may_ever_have_a_null_value_before() -> None:
    """🔴 **assertion เชิงลบ** — เส้นนี้ทับ 100% ของการเขียน `None` จึงผิด *เสมอ*
    ไม่ใช่ "ยังไม่มีค่า" · ครอบทุกสาขาที่สร้างแถว audit ได้จริง"""
    plans = plan_writes(
        [
            _row(
                values={
                    "condition_grade": PosterCondition.mint,
                    "is_unique": True,
                },
                reasons={"condition_grade": WHY_GRADE, "is_unique": WHY_UNIQUE},
            ),
            _row(
                poster_uuid=PID2,
                values={"is_unique": True},
                reasons={"is_unique": WHY_UNIQUE},
                lineno=3,
            ),
        ],
        {PID: _state(is_unique=False), PID2: _state(is_unique=False)},
    )
    entries = [e for plan in plans for e in audit_entries(plan)]
    assert len(entries) == 3
    assert not any(e.value_before is None for e in entries)
    assert all(e.value_before for e in entries)
    assert {e.field for e in entries} == set(WRITABLE_FIELDS)


def test_every_audit_entry_carries_the_reason_of_its_own_field() -> None:
    """🔴 A-D2 ข้อ 2/3 — เหตุผลของเกรดต้องไม่ไปโผล่ในแถวของจำนวน · ก้อนเดียวที่ถูก
    ก๊อปลงสองแถวคือ audit ที่อ่านย้อนแล้วแยกไม่ออกว่าอธิบายอันไหน"""
    plan = plan_writes(
        [
            _row(
                values={
                    "condition_grade": PosterCondition.mint,
                    "is_unique": True,
                },
                reasons={"condition_grade": WHY_GRADE, "is_unique": WHY_UNIQUE},
            )
        ],
        {PID: _state(is_unique=False)},
    )[0]
    by_field = {e.field: e.reason for e in audit_entries(plan)}
    assert by_field == {"condition_grade": WHY_GRADE, "is_unique": WHY_UNIQUE}


def test_audit_entries_never_touch_a_session() -> None:
    """🔴 บทเรียนของ Amendment 2026-08-07 — ตรรกะที่ต้องมี DB ถึงจะรันได้คือตรรกะที่
    ไม่มีเทสไหนแตะ · ตัวนี้ล็อกที่ระดับซอร์สว่ามันยังเป็น pure อยู่

    ไล่ **ตัวระบุใน AST** ไม่ใช่ substring ในซอร์ส — docstring ที่อธิบายว่า
    *"ไม่แตะ session"* มีคำว่า `session` อยู่ในนั้นเอง เทสแบบ substring จึงแดง
    กับข้อความที่ยืนยันสิ่งที่มันตรวจพอดี
    """
    tree = ast.parse(inspect.getsource(mod.audit_entries))
    assert [n for n in ast.walk(tree) if isinstance(n, ast.Await)] == []
    assert [n for n in ast.walk(tree) if isinstance(n, ast.AsyncFunctionDef)] == []
    identifiers = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
    identifiers |= {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
    identifiers |= {
        arg.arg
        for n in ast.walk(tree)
        if isinstance(n, ast.arguments)
        for arg in n.args
    }
    for forbidden in ("session", "execute", "add", "commit", "get"):
        assert forbidden not in identifiers


def test_run_does_not_build_the_audit_row_inline() -> None:
    """🔴 AC-8 ข้อ 1 ตัวอักษร — *"ห้ามให้ `run()` ประกอบ `PosterAttributeReview(...)`
    จากตัวแปรในลูปเอง"* · ค่าทุกตัวที่แปรผันต่อฟิลด์ต้องมาจาก `audit_entries()`
    """
    tree = ast.parse(inspect.getsource(mod.run))
    calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "PosterAttributeReview"
    ]
    assert len(calls) == 1
    sources = {
        kw.arg: ast.unparse(kw.value)
        for kw in calls[0].keywords
        if kw.arg in ("field", "value_before", "value_after", "reason")
    }
    assert sources == {
        "field": "entry.field",
        "value_before": "entry.value_before",
        "value_after": "entry.value_after",
        "reason": "entry.reason",
    }


# --------------------------------------------------------------------------
# verify_corrections — assert ตัวเดียวที่เส้นนี้มี
# --------------------------------------------------------------------------


def test_verify_is_silent_when_every_value_landed() -> None:
    plans = plan_writes([_row()], {PID: _state()})
    assert (
        verify_corrections(plans, {PID: _state(condition_grade=PosterCondition.fine)})
        == []
    )


def test_verify_catches_a_write_that_never_landed() -> None:
    """🔴 กับดักที่ `count(<column>)` มองไม่เห็นเลย — ทับค่าที่ไม่ NULL ด้วยค่าที่ไม่
    NULL ตัวนับไม่ขยับสักหน่วยไม่ว่าจะสำเร็จหรือล้มเหลว"""
    plans = plan_writes([_row()], {PID: _state()})
    problems = verify_corrections(plans, {PID: _state()})
    assert len(problems) == 1
    assert "near_mint" in problems[0]
    assert "fine" in problems[0]


def test_verify_catches_a_poster_that_vanished_after_commit() -> None:
    plans = plan_writes([_row()], {PID: _state()})
    assert verify_corrections(plans, {}) == ["บรรทัด 2: อ่านใบกลับมาไม่เจอหลัง commit"]


def test_verify_says_nothing_about_rows_that_were_skipped() -> None:
    plans = plan_writes([_row()], {PID: _state(condition_grade=None)})
    assert verify_corrections(plans, {}) == []


# --------------------------------------------------------------------------
# ด่านก่อนเขียน — ใบงานของเส้นอื่น · schema ปลายทาง
# --------------------------------------------------------------------------


def test_the_sheets_of_lane_three_and_four_are_refused_by_name() -> None:
    """🔴 `poster_attribute_reviews.source` เก็บชื่อไฟล์ ซึ่งเป็น**สิ่งเดียว**ที่แยกว่า
    ค่าไหนมาจากรอบไหน (ADR-0014 D28)"""
    from scripts.seed.manual_entry import DEFAULT_MANUAL_CSV
    from scripts.seed.reference_entry import DEFAULT_REFERENCE_CSV

    with pytest.raises(PrecheckError, match="เส้นที่ 3"):
        assert_own_sheet(DEFAULT_MANUAL_CSV)
    with pytest.raises(PrecheckError, match="เส้นที่ 4"):
        assert_own_sheet(Path("/tmp") / DEFAULT_REFERENCE_CSV.name)


def test_our_own_sheet_passes_wherever_it_lives() -> None:
    assert assert_own_sheet(Path("/anywhere/correction-entry.csv")) is None
    assert assert_own_sheet(mod.DEFAULT_CORRECTION_CSV) is None


def test_schema_ready_passes_when_everything_is_there() -> None:
    assert assert_schema_ready([], True) is None


def test_missing_poster_columns_name_the_real_cause() -> None:
    with pytest.raises(PrecheckError, match="condition_grade") as exc:
        assert_schema_ready(["condition_grade"], True)
    assert "alembic upgrade head" in str(exc.value)


def test_a_target_without_the_reason_column_refuses_to_run() -> None:
    """🔴 ปลายทางที่ไม่มีที่เก็บเหตุผล = audit ที่บอกว่าใครแก้อะไร แต่ตอบไม่ได้ว่า
    ทำไม ซึ่งลบเหตุผลทั้งหมดที่เส้นนี้มีอยู่ (A-D2 ข้อ 2/3)"""
    with pytest.raises(PrecheckError, match="reason") as exc:
        assert_schema_ready([], False)
    assert "alembic upgrade head" in str(exc.value)


# --------------------------------------------------------------------------
# `run()` — closed-world ที่ runtime (ชั้นที่ 3) + ลำดับด่าน
# --------------------------------------------------------------------------


class _PosterSpy:
    """object แทน `Poster` ที่จำ **ทุก** attribute ที่ถูกเซ็ตลงไป

    🔴 ชั้นเดียวที่จับชื่อซึ่งประกอบขึ้นตอนรันได้ —
    `setattr(poster, "need" + "s_review", …)` · f-string · `"_".join([...])`
    """

    def __init__(self) -> None:
        object.__setattr__(self, "writes", {})

    def __setattr__(self, name: str, value: object) -> None:
        self.writes[name] = value
        object.__setattr__(self, name, value)


class _FakeSession:
    """พอสำหรับ `run()` — ไม่มี SQL สักบรรทัด (`scalar` ตอบด่าน schema)."""

    def __init__(self, posters: dict, *, has_reason: bool = True) -> None:
        self.posters = posters
        self.added: list = []
        self.committed = False
        self.has_reason = has_reason

    async def __aenter__(self) -> _FakeSession:
        return self

    async def __aexit__(self, *exc: object) -> bool:
        return False

    async def scalar(self, _stmt: object, _params: object = None) -> object:
        return 1 if self.has_reason else None

    async def get(self, _model: object, pk: object) -> object:
        return self.posters.get(pk)

    def add(self, obj: object) -> None:
        self.added.append(obj)

    async def commit(self) -> None:
        self.committed = True


def _write_sheet(tmp_path, rows: list[dict[str, str]]) -> Path:
    path = tmp_path / "correction-entry.csv"
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(CORRECTION_SHEET_COLUMNS))
        writer.writeheader()
        writer.writerows(rows)
    return path


def _install_fakes(
    monkeypatch,
    tmp_path,
    sheet_rows,
    *,
    state: dict | None = None,
    readback_reflects_writes: bool = True,
):
    """แทนเฉพาะ **ทางเข้าออก DB** ของ `run()` — ตรรกะทั้งหมดเป็นของจริง

    `readback_reflects_writes=False` = จำลอง DB ที่ commit ผ่านแต่ค่าไม่ลง ซึ่งเป็น
    เคสเดียวที่ `verify_corrections()` มีไว้จับ (ดู §G2)
    """
    import app.core.database as db_mod

    path = _write_sheet(tmp_path, sheet_rows)
    ids = [uuid.UUID(r["poster_uuid"]) for r in sheet_rows]
    posters = {pid: _PosterSpy() for pid in ids}
    session = _FakeSession(posters)
    current = state if state is not None else {pid: _state() for pid in ids}

    async def fake_load_state(_session, _ids):
        # 🔴 ต้องสะท้อนสิ่งที่ถูกเซ็ตลง object จริง ไม่ใช่คืนค่าเดิมทุกครั้ง —
        # `run()` เรียกซ้ำหลัง commit เพื่อ `verify_corrections()` · fake ที่คืนค่าเดิม
        # จะทำให้ด่านนั้นแดงเสมอ (และถ้าคืนค่าใหม่เสมอก็จะเขียวเสมอ ซึ่งแย่กว่า)
        out: dict = {}
        for pid, base in current.items():
            values = dict(base.values)
            spy = posters.get(pid)
            if spy is not None and readback_reflects_writes:
                values.update(spy.writes)
            out[pid] = mod.PosterState(values=values)
        return out

    monkeypatch.setattr(db_mod, "async_session_maker", lambda: session)
    monkeypatch.setattr(mod, "_load_state", fake_load_state)
    return path, session, posters


async def _run_applier(
    monkeypatch,
    tmp_path,
    sheet_rows,
    *,
    commit: bool = True,
    state: dict | None = None,
    fields: list[str] | None = None,
    readback_reflects_writes: bool = True,
):
    """เรียก `run()` จริง โดยแทนเฉพาะ **ทางเข้าออก DB** — ตรรกะทั้งหมดเป็นของจริง"""
    path, session, posters = _install_fakes(
        monkeypatch,
        tmp_path,
        sheet_rows,
        state=state,
        readback_reflects_writes=readback_reflects_writes,
    )

    args = argparse.Namespace(
        file=path,
        commit=commit,
        field=fields if fields is not None else [],
        reviewed_by="chanothai",
        reviewed_at=REVIEWED_AT,
    )
    rc = await mod.run(args, "fake/db  [--target dev]")
    return rc, session, posters


async def test_run_writes_nothing_outside_the_writable_set(monkeypatch, tmp_path):
    """🔴 ชั้นที่ 3 จาก 3 — closed-world ที่ **runtime**

    ครอบสิ่งที่ชั้นซอร์สจับไม่ได้: ชื่อ attribute ที่ประกอบขึ้นตอนรัน **และ**
    การเขียนที่เพิ่ม *นอก* ลูปของ `field_writes` ซึ่ง fail-closed ตัวนั้นไม่ครอบ
    """
    rc, _session, posters = await _run_applier(
        monkeypatch,
        tmp_path,
        [
            _raw(condition_grade="fine", condition_grade_reason=WHY_GRADE),
            _raw(poster_uuid=str(PID2), is_unique="Y", is_unique_reason=WHY_UNIQUE),
            _raw(poster_uuid=str(PID3)),  # เว้นว่างทั้งหมด — ต้องไม่ถูกแตะเลย
        ],
        state={
            PID: _state(),
            PID2: _state(is_unique=False),
            PID3: _state(),
        },
    )
    assert rc == 0
    written: set[str] = set()
    for spy in posters.values():
        assert set(spy.writes) <= set(WRITABLE_FIELDS)
        written |= set(spy.writes)
    assert written == set(WRITABLE_FIELDS)
    assert posters[PID3].writes == {}


async def test_run_records_the_real_value_before_and_the_reason(monkeypatch, tmp_path):
    """🔴 mutation 1 ที่ **runtime** — เก็บ kwargs จริงที่ถูกส่งเข้า ORM ผ่าน session
    ปลอม · เทส pure ข้างบนจับ `audit_entries()` ตัวนี้จับสายที่ต่อจากมันถึง DB"""
    _rc, session, _posters = await _run_applier(
        monkeypatch,
        tmp_path,
        [
            _raw(condition_grade="fine", condition_grade_reason=WHY_GRADE),
            _raw(poster_uuid=str(PID2), is_unique="Y", is_unique_reason=WHY_UNIQUE),
        ],
        state={PID: _state(), PID2: _state(is_unique=False)},
    )
    assert session.committed is True
    assert len(session.added) == 2
    by_poster = {e.poster_id: e for e in session.added}
    assert by_poster[PID].field == "condition_grade"
    assert by_poster[PID].value_before == "near_mint"
    assert by_poster[PID].value_after == "fine"
    assert by_poster[PID].reason == WHY_GRADE
    assert by_poster[PID2].value_before == "False"
    assert by_poster[PID2].value_after == "True"
    assert by_poster[PID2].reason == WHY_UNIQUE
    assert not any(e.value_before is None for e in session.added)
    assert all(e.reason for e in session.added)
    assert all(e.reviewed_by == "chanothai" for e in session.added)
    assert all(e.reviewed_at == REVIEWED_AT for e in session.added)
    assert {e.source for e in session.added} == {"correction-entry.csv"}


async def test_dry_run_touches_no_poster_and_records_no_audit(monkeypatch, tmp_path):
    rc, session, posters = await _run_applier(
        monkeypatch,
        tmp_path,
        [_raw(condition_grade="fine", condition_grade_reason=WHY_GRADE)],
        commit=False,
    )
    assert rc == 0
    assert session.added == []
    assert session.committed is False
    assert all(spy.writes == {} for spy in posters.values())


async def test_a_sheet_missing_one_reason_never_reaches_the_session(
    monkeypatch, tmp_path
):
    """🔴 mutation 2 ที่ **runtime** — precheck อยู่ *ก่อน* เปิด session ไม่ใช่ rollback

    ถ้ามีใครย้ายด่านไปหลัง session ทั้งไฟล์อาจเขียนบางส่วนแล้วค่อยถอย ซึ่งเป็นสภาพ
    ที่ต่างกันมากบน DB ที่รับเงินจริง
    """
    session = _FakeSession({})
    import app.core.database as db_mod

    monkeypatch.setattr(db_mod, "async_session_maker", lambda: session)
    path = _write_sheet(
        tmp_path,
        [
            _raw(condition_grade="fine", condition_grade_reason=WHY_GRADE),
            _raw(poster_uuid=str(PID2), condition_grade="good"),  # ← ขาดเหตุผล
        ],
    )
    args = argparse.Namespace(
        file=path,
        commit=True,
        field=[],
        reviewed_by="chanothai",
        reviewed_at=REVIEWED_AT,
    )
    with pytest.raises(PrecheckError, match="condition_grade_reason ว่าง"):
        await mod.run(args, "fake/db")
    assert session.added == []
    assert session.committed is False


@pytest.mark.parametrize(
    "grade", [PosterCondition.mint, PosterCondition.near_mint], ids=lambda g: g.value
)
@pytest.mark.parametrize("current_unique", [True, False], ids=["was_true", "was_false"])
@pytest.mark.parametrize(
    "fields",
    [None, ["is_unique"], ["condition_grade"]],
    ids=["both", "only_u", "only_g"],
)
async def test_nothing_can_ever_put_is_unique_false_on_a_poster_at_runtime(
    monkeypatch, tmp_path, grade, current_unique, fields
):
    """🔴 **เทสเชิงลบที่ critic สั่ง** — ระดับ runtime (`_PosterSpy`) ไม่ใช่แค่ระดับแผน

    กวาดทุกทางที่พอจะนึกออกว่าจะยัด `N` เข้าไปได้: **ทุกเกรดรวม `mint`** × ค่าเดิม
    `true`/`false` × `--field` ทั้งสามแบบ (ทั้งคู่ · `is_unique` เดี่ยว ·
    `condition_grade` เดี่ยว) · ทุกช่องต้องจบที่ `PrecheckError` **ก่อนเปิด session**
    และไม่มี `setattr` ลงบน poster สักตัว

    🔴 `--field condition_grade` ต้องไม่กลายเป็นทางลอด — ด่านนโยบายอยู่ที่
    `parse_rows()` ซึ่งตรวจ *ทั้งไฟล์* เสมอ เหมือนด่าน `reason` (ถ้าผูกกับ `--field`
    เมื่อไหร่ การเลือกฟิลด์จะกลายเป็นวิธีลักลอบใส่ `N` เข้าไฟล์โดยไม่มีอะไรฟ้อง)
    """
    import app.core.database as db_mod

    path = _write_sheet(
        tmp_path,
        [
            _raw(condition_grade="fine", condition_grade_reason=WHY_GRADE),
            _raw(
                poster_uuid=str(PID2),
                condition_grade=grade.value,
                condition_grade_reason=WHY_GRADE,
                is_unique="N",
                is_unique_reason=WHY_UNIQUE,
            ),
        ],
    )
    posters = {PID: _PosterSpy(), PID2: _PosterSpy()}
    session = _FakeSession(posters)

    async def fake_load_state(_session, _ids):
        return {
            PID: _state(),
            PID2: _state(condition_grade=grade, is_unique=current_unique),
        }

    monkeypatch.setattr(db_mod, "async_session_maker", lambda: session)
    monkeypatch.setattr(mod, "_load_state", fake_load_state)
    args = argparse.Namespace(
        file=path,
        commit=True,
        field=fields or [],
        reviewed_by="chanothai",
        reviewed_at=REVIEWED_AT,
    )

    with pytest.raises(PrecheckError, match="เขียนไม่ได้ในระบบวันนี้"):
        await mod.run(args, "fake/db")
    # fail-closed — แม้แถวแรกจะถูกต้องทุกอย่างก็ต้องไม่ถูกเขียน
    assert all(spy.writes == {} for spy in posters.values())
    assert session.added == []
    assert session.committed is False


async def test_run_refuses_the_other_lanes_sheet_before_touching_anything(
    monkeypatch, tmp_path
):
    from scripts.seed.manual_entry import DEFAULT_MANUAL_CSV

    path = _write_sheet(
        tmp_path, [_raw(condition_grade="fine", condition_grade_reason=WHY_GRADE)]
    )
    path.rename(tmp_path / DEFAULT_MANUAL_CSV.name)
    args = argparse.Namespace(
        file=tmp_path / DEFAULT_MANUAL_CSV.name,
        commit=True,
        field=[],
        reviewed_by="chanothai",
        reviewed_at=REVIEWED_AT,
    )
    with pytest.raises(PrecheckError, match="เส้นที่ 3"):
        await mod.run(args, "fake/db")


async def test_run_refuses_a_target_without_the_reason_column(monkeypatch, tmp_path):
    import app.core.database as db_mod

    path = _write_sheet(
        tmp_path, [_raw(condition_grade="fine", condition_grade_reason=WHY_GRADE)]
    )
    session = _FakeSession({PID: _PosterSpy()}, has_reason=False)
    monkeypatch.setattr(db_mod, "async_session_maker", lambda: session)
    args = argparse.Namespace(
        file=path,
        commit=True,
        field=[],
        reviewed_by="chanothai",
        reviewed_at=REVIEWED_AT,
    )
    with pytest.raises(PrecheckError, match="reason"):
        await mod.run(args, "fake/db")
    assert session.added == []
    assert session.committed is False


async def test_field_flag_narrows_what_run_actually_writes(monkeypatch, tmp_path):
    _rc, session, posters = await _run_applier(
        monkeypatch,
        tmp_path,
        [
            _raw(
                condition_grade="fine",
                condition_grade_reason=WHY_GRADE,
                is_unique="Y",
                is_unique_reason=WHY_UNIQUE,
            )
        ],
        state={PID: _state(is_unique=False)},
        fields=["is_unique"],
    )
    assert set(posters[PID].writes) == {"is_unique"}
    assert [e.field for e in session.added] == ["is_unique"]


# --------------------------------------------------------------------------
# dry-run ต้องแสดงพอให้คนยืนยันตัวเลขได้ (A-D2 ข้อ 5)
# --------------------------------------------------------------------------


async def test_dry_run_shows_before_arrow_after_with_the_reason_and_the_line_number(
    monkeypatch, tmp_path, capsys
):
    """A-D2 ข้อ 5 — dry-run ที่ไม่บอกว่ากำลังจะทับอะไรคือ dry-run ที่ใช้ตรวจไม่ได้"""
    await _run_applier(
        monkeypatch,
        tmp_path,
        [_raw(condition_grade="fine", condition_grade_reason=WHY_GRADE)],
        commit=False,
    )
    out = capsys.readouterr().out
    assert "บรรทัด    2" in out
    assert "'near_mint' → 'fine'" in out
    assert WHY_GRADE in out
    assert "จะทับค่าเดิม 1 ค่า" in out
    assert "DRY-RUN" in out


async def test_the_stale_row_warning_says_what_its_number_counts(
    monkeypatch, tmp_path, capsys
):
    """🔴 G4 — ตัวเลขต้องพกขอบเขตของตัวเองมาด้วยในประโยคเดียวกัน

    เลขนี้นับ **แถวในใบงานที่รันรอบนี้** ส่วน `BACKLOG.md` §0 และ ADR-0019 นับ
    **ทั้งร้าน** — สองเลขต่างกันได้โดยที่ทั้งคู่ถูก (ใบที่ยังไม่มีเกรดหลุดตัวกรอง
    ปริยายของใบงาน เช่นกรอบไฟ BL-82) · เกิดจริง: หน้าจอพิมพ์ 32 ขณะที่เอกสารพูดถึง 33
    แล้วไม่มีอะไรบนหน้าจอบอกว่าทำไม

    ความถูกต้องที่ล็อกไว้คือ **คนอ่านต้องไม่ต้องจำ** ว่าเลขไหนนับอะไร — เลขลอย ๆ
    ที่ต้องพึ่งความจำ อ่านผิดเมื่อไหร่ก็ได้ และคนที่อ่านผิดจะสรุปว่าทะเบียนผิด
    """
    await _run_applier(
        monkeypatch,
        tmp_path,
        [_raw(condition_grade="fine", condition_grade_reason=WHY_GRADE)],
        commit=False,
        state={PID: _state(is_unique=False)},
    )
    out = capsys.readouterr().out
    assert "1 แถวในใบงานนี้จะยังเป็น is_unique=false" in out
    assert "นับเฉพาะแถวในใบงานนี้ — ทั้งร้านมีได้มากกว่านี้" in out
    # 🔴 assertion เชิงลบคือตัวที่ฆ่าการย้อนกลับไปเป็นข้อความเดิมที่ไม่มีขอบเขต
    assert "1 แถวจะยังเป็น is_unique=false" not in out


# --------------------------------------------------------------------------
# G2 — จุดต่อของ `verify_corrections()` ใน `run()`
# --------------------------------------------------------------------------
#
# 🔴 ตัวฟังก์ชันมีเทสครบอยู่แล้วข้างบน (§verify) แต่ **การมีฟังก์ชันที่ถูกต้องอยู่
# เฉย ๆ ไม่ได้แปลว่ามันถูกต่อสาย** — mutation ที่ตัดสายทิ้งทำให้สคริปต์พิมพ์
# "ตรงทุกค่า" แล้วคืน 0 ทั้งที่ไม่ได้ตรวจอะไร และ `_report_counts()` แบบเส้นอื่น
# จับไม่ได้เลยเพราะเส้นนี้ทับค่า ตัวนับจึงไม่ขยับ (ดู docstring ของโมดูล)


async def test_a_write_that_never_landed_makes_run_return_one(
    monkeypatch, tmp_path, capsys
):
    """DB ที่ `commit()` ผ่านแต่ค่าไม่ลง — เส้นนี้ต้องบอกคนว่าต้องไปตรวจด้วยมือ"""
    rc, session, _posters = await _run_applier(
        monkeypatch,
        tmp_path,
        [_raw(condition_grade="fine", condition_grade_reason=WHY_GRADE)],
        readback_reflects_writes=False,
    )
    assert rc == 1
    # commit ไปแล้วจริง — สถานการณ์นี้ย้อนไม่ได้ การรายงานจึงเป็นสิ่งเดียวที่ทำได้
    assert session.committed is True
    out = capsys.readouterr().out
    assert "การทับไม่ลงตามแผน" in out
    assert "near_mint" in out
    assert "fine" in out
    # 🔴 assertion เชิงลบคือตัวที่ฆ่า mutation "ตัดสายไม่เรียก verify_corrections()"
    assert "ตรงทุกค่า" not in out


async def test_a_write_that_landed_returns_zero_and_says_it_read_the_values_back(
    monkeypatch, tmp_path, capsys
):
    """positive control ของคู่ข้างบน — ไม่งั้นเทสคู่นี้เขียวได้ด้วยการ 'คืน 1 เสมอ'"""
    rc, session, _posters = await _run_applier(
        monkeypatch,
        tmp_path,
        [_raw(condition_grade="fine", condition_grade_reason=WHY_GRADE)],
    )
    assert rc == 0
    assert session.committed is True
    out = capsys.readouterr().out
    assert "ตรงทุกค่า" in out
    assert "การทับไม่ลงตามแผน" not in out


# --------------------------------------------------------------------------
# G1 — ชั้น argparse ของ `main()` เอง
# --------------------------------------------------------------------------
#
# 🔴 เทสทุกตัวข้างบนประกอบ `argparse.Namespace` เองแล้ว **ข้ามชั้นนี้ไปทั้งชั้น** —
# ค่า default และด่านบังคับของ `--commit` จึงไม่มีอะไรล็อกเลย · ที่นี่เรียก `main()`
# ผ่าน `sys.argv` จริง ทางเดียวกับที่คนพิมพ์บน terminal

# `DATABASE_URL` ที่ผ่าน `assert_target(..., "dev")`: host local · ชื่อ database ไม่มี
# คำว่า prod/uat/stage/sit · **ตั้งเองแทนการพึ่ง `.env` ของเครื่องที่รันเทส**
FAKE_DEV_DATABASE_URL = "postgresql+asyncpg://u:p@localhost:5432/poster_nung_dev"
REVIEWED_AT_CLI = REVIEWED_AT.isoformat()


def _install_cli(
    monkeypatch,
    path: Path,
    *argv: str,
    database_url: str = FAKE_DEV_DATABASE_URL,
) -> None:
    """ต่อ `sys.argv` จริงเข้า `main()`

    `_load_env()` ถูกแทนด้วย no-op เพราะมันเป็น `os.environ.setdefault()` จากไฟล์
    `.env` ของเครื่องที่รัน — ผลของเทสจะขึ้นกับเครื่อง และคีย์ที่มันเติมค้างข้าม
    test ไปเรื่อย ๆ (ไม่มีใครถอนให้) · ค่า `DATABASE_URL` จึงตั้งตรง ๆ แทน

    `database_url` เปลี่ยนได้เพราะ §G5 ต้องยิงปลายทางต้องห้ามเข้ามาทางเดียวกับที่
    คนรันจริงจะได้มัน (env var) — ไม่ใช่ด้วยการเรียก `assert_target()` เอง
    """
    monkeypatch.setattr(mod, "_load_env", lambda _target: None)
    monkeypatch.setenv("DATABASE_URL", database_url)
    monkeypatch.setattr(
        sys, "argv", ["correction_entry.py", "--file", str(path), *argv]
    )


def test_main_without_commit_writes_nothing_even_with_the_reviewer_flags_present(
    monkeypatch, tmp_path, capsys
) -> None:
    """🔴 ตัวฆ่า mutation `--commit` → `action="store_true", default=True`

    ใส่ `--reviewed-by`/`--reviewed-at` มาครบ **โดยตั้งใจ** เพื่อให้ mutation ตัวนั้น
    ผ่านด่านบังคับของ `--commit` ไปได้ แล้วต้องไปตายที่ assertion เชิงลบข้างล่างแทน —
    ถ้าเทสนี้ไม่ใส่สองค่านั้น mutation จะตายด้วย `SystemExit(2)` ซึ่งพิสูจน์แค่ว่า
    *ด่านอื่น* ทำงาน ไม่ได้พิสูจน์ว่า dry-run ยังเป็น default (A-D2 ข้อ 5)
    """
    path, session, posters = _install_fakes(
        monkeypatch,
        tmp_path,
        [_raw(condition_grade="fine", condition_grade_reason=WHY_GRADE)],
    )
    _install_cli(
        monkeypatch,
        path,
        "--reviewed-by",
        "chanothai",
        "--reviewed-at",
        REVIEWED_AT_CLI,
    )

    assert mod.main() == 0
    assert session.added == []
    assert session.committed is False
    assert all(spy.writes == {} for spy in posters.values())
    out = capsys.readouterr().out
    assert "DRY-RUN" in out
    assert "ทับค่าเดิมแล้ว" not in out


def test_main_with_commit_but_without_reviewed_by_never_opens_a_session(
    monkeypatch, tmp_path, capsys
) -> None:
    """ADR-0010 D1 — เส้นนี้ทับค่าที่ลูกค้าอ่านไปแล้ว จึงต้องมีชื่อคนที่รับผิดชอบเสมอ"""
    path, session, posters = _install_fakes(
        monkeypatch,
        tmp_path,
        [_raw(condition_grade="fine", condition_grade_reason=WHY_GRADE)],
    )
    _install_cli(monkeypatch, path, "--commit", "--reviewed-at", REVIEWED_AT_CLI)

    with pytest.raises(SystemExit) as exc:
        mod.main()
    assert exc.value.code == 2
    # 🔴 ต้องเทียบกับ *ข้อความ* ไม่ใช่แค่ชื่อ flag — บรรทัด usage ของ argparse
    # มีชื่อ flag ทุกตัวอยู่แล้ว การหา "--reviewed-by" เฉย ๆ จึงจริงเสมอ
    assert "--commit ต้องระบุ --reviewed-by ด้วย" in capsys.readouterr().err
    assert session.added == []
    assert session.committed is False
    assert all(spy.writes == {} for spy in posters.values())


def test_main_with_commit_but_without_reviewed_at_never_opens_a_session(
    monkeypatch, tmp_path, capsys
) -> None:
    """ADR-0010 D5 — และการที่เทสนี้แดงได้ก็แปลว่า `--reviewed-at` ยังไม่มี default

    (ถ้ามี default เมื่อไหร่ `args.reviewed_at` จะไม่ว่าง ด่านนี้ก็ไม่ทำงานอีกเลย)
    """
    path, session, posters = _install_fakes(
        monkeypatch,
        tmp_path,
        [_raw(condition_grade="fine", condition_grade_reason=WHY_GRADE)],
    )
    _install_cli(monkeypatch, path, "--commit", "--reviewed-by", "chanothai")

    with pytest.raises(SystemExit) as exc:
        mod.main()
    assert exc.value.code == 2
    assert "--commit ต้องระบุ --reviewed-at ด้วย" in capsys.readouterr().err
    assert session.added == []
    assert session.committed is False
    assert all(spy.writes == {} for spy in posters.values())


def test_main_with_every_required_flag_goes_all_the_way_to_the_write(
    monkeypatch, tmp_path, capsys
) -> None:
    """🔴 positive control ของสามตัวข้างบน

    ถ้าไม่มีตัวนี้ ชุดเทสของชั้นนี้จะเขียวได้ด้วยสคริปต์ที่ **ปฏิเสธทุกกรณี** ·
    ตัวนี้ยังเป็นตัวเดียวที่พิสูจน์ว่าค่าที่คนพิมพ์เดินถึง audit จริง ไม่ได้ถูกแปลง
    หรือแทนที่ระหว่างทาง
    """
    path, session, posters = _install_fakes(
        monkeypatch,
        tmp_path,
        [_raw(condition_grade="fine", condition_grade_reason=WHY_GRADE)],
    )
    _install_cli(
        monkeypatch,
        path,
        "--commit",
        "--reviewed-by",
        "chanothai",
        "--reviewed-at",
        REVIEWED_AT_CLI,
    )

    assert mod.main() == 0
    assert session.committed is True
    assert posters[PID].writes == {"condition_grade": PosterCondition.fine}
    assert [e.field for e in session.added] == ["condition_grade"]
    assert session.added[0].reviewed_by == "chanothai"
    assert session.added[0].reviewed_at == REVIEWED_AT
    assert session.added[0].reason == WHY_GRADE
    out = capsys.readouterr().out
    assert "DRY-RUN" not in out
    assert "ทับค่าเดิมแล้ว 1 ค่า" in out


# --------------------------------------------------------------------------
# G5 — จุดต่อของ `assert_target()` ใน `main()`
# --------------------------------------------------------------------------
#
# 🔴 `assert_target()` มีเทสของ *ตัวฟังก์ชัน* อยู่แล้วที่ `test_seed_lane_shared_rules.py`
# แต่ **สายที่ต่อมันเข้า `main()` ของเส้นนี้ไม่เคยถูกแตะ** — เทส CLI ทุกตัวข้างบนใช้
# `FAKE_DEV_DATABASE_URL` ซึ่งผ่านด่านเสมอ จึงครอบแต่ทางบวก (รูปเดียวกับ G2 เป๊ะ)
#
# ด่านนี้เป็นชั้นเดียวที่กันไม่ให้สคริปต์ที่ทับ `condition_grade`/`is_unique` ยิงเข้า DB
# ที่ไม่ใช่ dev/sit — ADR-0010 D7 · ADR-0015 D8 (`production` ไม่มีให้เลือกและห้ามเพิ่ม)
#
# ที่นี่ล็อกสองอย่างที่ต่างกัน และต้องมีทั้งคู่:
#   (1) ปลายทางต้องห้าม **หยุดก่อนเปิด session** — ไม่ใช่แค่ exit code
#   (2) ค่าที่ถูกตรวจคือ `DATABASE_URL` **ของรอบนั้นจริง** ไม่ใช่ค่าคงที่ที่ผ่านเสมอ
#       (ข้อ 2 คือข้อที่เทส "พิสูจน์ว่าฟังก์ชันถูกเรียก" จับไม่ได้)

# ปลายทางที่ `assert_target(..., "dev")` ต้องปฏิเสธ — คนละกฎกันทั้งสามตัว
FORBIDDEN_TARGET_URLS = {
    # ADR-0010 D7 — ชื่อ database มีคำที่แปลว่า env จริงกว่าที่เลือกไว้
    "prod-in-db-name": "postgresql+asyncpg://u:p@localhost:5432/poster_nung_prod",
    # --target dev แต่ host ไม่ใช่เครื่องนี้
    "remote-host": "postgresql+asyncpg://u:p@db.example.invalid:5432/poster_nung_dev",
    # --target dev แต่ชื่อ database เป็นของ sit = สั่ง target ผิด
    "sit-db-under-dev": "postgresql+asyncpg://u:p@localhost:5432/poster_nung_sit",
}

# dev ที่ถูกกฎ แต่ **ต่างจาก `FAKE_DEV_DATABASE_URL` ทั้ง host และชื่อ database** —
# ความต่างนั้นคือสิ่งเดียวที่ทำให้ข้อ (2) ข้างบนพิสูจน์อะไรได้
G5_DEV_DATABASE_URL = "postgresql+asyncpg://u:p@127.0.0.1:5432/poster_nung_dev_g5"
G5_DEV_TARGET_LABEL = "127.0.0.1/poster_nung_dev_g5"


@pytest.mark.parametrize(
    "database_url",
    list(FORBIDDEN_TARGET_URLS.values()),
    ids=list(FORBIDDEN_TARGET_URLS),
)
def test_main_stops_at_the_target_guard_before_opening_any_session(
    monkeypatch, tmp_path, capsys, database_url
) -> None:
    """🔴 ตัวฆ่า mutation ที่ **ถอดการเรียก `assert_target()` ออกจาก `main()`**

    ให้ `--commit` และแฟล็กครบทุกตัว **โดยตั้งใจ** — ถ้าด่านนี้หายไป สคริปต์จะเดินต่อ
    จนเขียนจริง เทสจึงต้องตายที่ *ไม่มีอะไรถูกเขียน* ไม่ใช่ที่ exit code อย่างเดียว
    (บทเรียนจาก G1: `--commit default=True` ตายเพราะ `assert session.added == []`)
    """
    path, session, posters = _install_fakes(
        monkeypatch,
        tmp_path,
        [_raw(condition_grade="fine", condition_grade_reason=WHY_GRADE)],
    )
    _install_cli(
        monkeypatch,
        path,
        "--commit",
        "--reviewed-by",
        "chanothai",
        "--reviewed-at",
        REVIEWED_AT_CLI,
        database_url=database_url,
    )

    assert mod.main() == 1
    captured = capsys.readouterr()
    assert "precheck ไม่ผ่าน" in captured.err
    # พฤติกรรม ไม่ใช่แค่ status — ไม่มี session ไม่มี setattr ไม่มีแถว audit
    assert session.added == []
    assert session.committed is False
    assert all(spy.writes == {} for spy in posters.values())
    # และหยุด **ก่อน** รายงานของ `run()` ซึ่งบรรทัดแรกคือปลายทาง
    assert "ปลายทาง" not in captured.out
    assert "ทับค่าเดิมแล้ว" not in captured.out


def test_main_checks_the_database_url_of_this_very_run(
    monkeypatch, tmp_path, capsys
) -> None:
    """🔴 ตัวฆ่า mutation ที่ *คงการเรียกไว้* แต่ส่งค่าคงที่ที่ผ่านด่านเสมอเข้าไปแทน

    ตัวนั้นถอดด่านทิ้งเหมือนกันแต่ยังดูเหมือนมีด่านอยู่ครบ — เทสที่พิสูจน์แค่ว่า
    "ฟังก์ชันถูกเรียก" จับไม่ได้เลย · ที่ล็อกไว้คือ **อาร์กิวเมนต์ตัวแรก** ต้องเป็น
    `DATABASE_URL` ของรอบนั้นจริง และถูกตรวจ **ครั้งเดียว**

    ⚠️ ตัวนี้เดินบน `--target` ที่เป็น default จึง **ไม่ได้พิสูจน์อาร์กิวเมนต์ตัวที่สอง**
    — ครึ่งนั้นเป็นของ `test_main_passes_the_target_the_human_typed_not_a_constant`
    """
    seen: list[tuple[str, str]] = []
    real_assert_target = mod.assert_target

    def spy(database_url: str, target: str) -> str:
        seen.append((database_url, target))
        return real_assert_target(database_url, target)  # ของจริงยังทำงานเต็ม

    monkeypatch.setattr(mod, "assert_target", spy)
    path, _session, _posters = _install_fakes(
        monkeypatch,
        tmp_path,
        [_raw(condition_grade="fine", condition_grade_reason=WHY_GRADE)],
    )
    _install_cli(
        monkeypatch,
        path,
        "--commit",
        "--reviewed-by",
        "chanothai",
        "--reviewed-at",
        REVIEWED_AT_CLI,
        database_url=G5_DEV_DATABASE_URL,
    )

    assert mod.main() == 0
    assert seen == [(G5_DEV_DATABASE_URL, "dev")]
    capsys.readouterr()


def test_main_passes_the_target_the_human_typed_not_a_constant(
    monkeypatch, tmp_path, capsys
) -> None:
    """🔴 ครึ่งหลังของจุดต่อ — ตัวฆ่า mutation ที่ hardcode **อาร์กิวเมนต์ที่สอง**

    `assert_target(database_url, "dev")` รอดทุกเทสที่ส่ง `--target` เป็น default
    (คือทุกตัวก่อนหน้านี้ในไฟล์) · ผลจริงของ mutation นั้น: สั่ง `--target sit`
    บน url ของ dev แล้ว **สคริปต์เขียนลงเครื่องนี้จริง** พร้อมพิมพ์ป้าย `[--target sit]`
    ให้คนกดยืนยัน ⇒ ชั้น ADR-0015 D8 หายไปทั้งชั้นโดยที่หน้าจอยังบอกว่ากำลังเขียน SIT

    🔴 **ห้าม assert ข้อความ error ของเคสนี้** — มันต่างกันตามว่าเครื่องที่รันเทสมี
    `.env.sit` หรือไม่ (มี → "ไม่ตรงกับค่าใน .env.sit" · ไม่มี → "หา DATABASE_URL
    ใน .env.sit ไม่เจอ") · `rc == 1` กับ `seen` เหมือนกันทั้งสองสภาพ จึงเป็นสิ่งที่
    ล็อกได้โดยไม่ผูกกับเครื่อง
    """
    seen: list[tuple[str, str]] = []
    real_assert_target = mod.assert_target

    def spy(database_url: str, target: str) -> str:
        seen.append((database_url, target))
        return real_assert_target(database_url, target)  # ของจริงยังทำงานเต็ม

    monkeypatch.setattr(mod, "assert_target", spy)
    path, session, posters = _install_fakes(
        monkeypatch,
        tmp_path,
        [_raw(condition_grade="fine", condition_grade_reason=WHY_GRADE)],
    )
    _install_cli(
        monkeypatch,
        path,
        "--target",
        "sit",
        "--commit",
        "--reviewed-by",
        "chanothai",
        "--reviewed-at",
        REVIEWED_AT_CLI,
        database_url=G5_DEV_DATABASE_URL,
    )

    assert mod.main() == 1
    assert seen == [(G5_DEV_DATABASE_URL, "sit")]
    # พฤติกรรม ไม่ใช่แค่ status — url ของ dev ห้ามถูกเขียนเมื่อคนสั่งว่า sit
    assert session.added == []
    assert session.committed is False
    assert all(spy_poster.writes == {} for spy_poster in posters.values())
    assert "ปลายทาง" not in capsys.readouterr().out


def test_a_dev_url_that_passes_the_guard_still_reaches_the_write(
    monkeypatch, tmp_path, capsys
) -> None:
    """🔴 positive control ของทั้ง §G5

    ถ้าไม่มีตัวนี้ ชุดข้างบนเขียวได้ด้วยสคริปต์ที่ **ปฏิเสธทุกปลายทาง** ·
    ตัวนี้ยังเป็นตัวที่ยืนยันว่า *ป้ายปลายทางที่พิมพ์ออกมาถูก derive จาก
    `DATABASE_URL` ของรอบนั้น* — mutation ที่ส่งค่าคงที่เข้าด่านจะพิมพ์ป้ายของค่าคงที่นั้น
    """
    path, session, posters = _install_fakes(
        monkeypatch,
        tmp_path,
        [_raw(condition_grade="fine", condition_grade_reason=WHY_GRADE)],
    )
    _install_cli(
        monkeypatch,
        path,
        "--commit",
        "--reviewed-by",
        "chanothai",
        "--reviewed-at",
        REVIEWED_AT_CLI,
        database_url=G5_DEV_DATABASE_URL,
    )

    assert mod.main() == 0
    captured = capsys.readouterr()
    assert "precheck ไม่ผ่าน" not in captured.err
    assert f"ปลายทาง : {G5_DEV_TARGET_LABEL}  [--target dev]" in captured.out
    assert session.committed is True
    assert posters[PID].writes == {"condition_grade": PosterCondition.fine}
    assert [e.field for e in session.added] == ["condition_grade"]


# --------------------------------------------------------------------------
# G6 — จุดต่อของ `_load_env()` และ guard `DATABASE_URL` ใน `main()`
# --------------------------------------------------------------------------
#
# 🔴 มติ 2026-08-16: **เลือกทาง "เพิ่มเทสให้ mutation ตาย" ไม่ใช่ทาง "ยอมรับถาวร"**
# ทะเบียนเดิมบันทึกข้อนี้ว่าเป็นความไวของเทส ไม่ใช่บั๊ก (ถอดทั้งคู่ออกแล้วยัง
# fail-closed อยู่ที่ `assert_target()`) ซึ่งจริง — แต่ "fail-closed เหมือนกัน"
# ไม่ได้แปลว่า "เหมือนกัน":
#
#   ถอด `_load_env(args.target)`  → คนที่มี `.env` ครบอยู่แล้วรันไม่ได้เลย โดยได้
#                                    ข้อความว่าไม่พบ DATABASE_URL ทั้งที่ไฟล์มีอยู่
#   ถอด guard `if not database_url` → คนได้ "precheck ไม่ผ่าน" แทน ซึ่งชี้ไปผิดที่:
#                                    ไปแก้ปลายทาง ทั้งที่ปัญหาคือ env ยังไม่ถูกโหลด
#   hardcode `_load_env("dev")`    → สั่ง `--target sit` แล้วโหลด env ของ dev มาแทน
#
# เทสทุกตัวข้างบน (`_install_cli`) แทน `_load_env` ด้วย no-op **โดยตั้งใจ** และตั้ง
# `DATABASE_URL` ตรง ๆ — ซึ่งเป็นเหตุผลที่ทั้งชั้นนี้ไม่เคยถูกแตะ · ที่นี่ไม่ยกเลิก
# การแทนนั้น (การอ่าน `.env` ของเครื่องที่รันเทสทำให้ผลขึ้นกับเครื่อง) แต่แทนด้วย
# **ตัวปลอมที่ทำสิ่งที่ของจริงทำ คือเติม `DATABASE_URL` ตาม target ที่ได้รับ**
# แล้ววัดจากผลลัพธ์ว่าค่านั้นเดินถึงด่านจริงหรือไม่

# env ของแต่ละ target — ค่า **ต่างกัน** ทั้งสองตัว เพราะความต่างนั้นคือสิ่งเดียวที่
# ทำให้พิสูจน์ได้ว่า `main()` โหลดไฟล์ของ target ที่คนพิมพ์ ไม่ใช่ของ target อื่น
G6_ENV_FILE_URLS = {
    "dev": "postgresql+asyncpg://u:p@localhost:5432/poster_nung_dev_g6",
    "sit": "postgresql+asyncpg://u:p@localhost:5432/poster_nung_sit_g6",
}
G6_DEV_TARGET_LABEL = "localhost/poster_nung_dev_g6"


def _install_cli_with_env_file(
    monkeypatch,
    path: Path,
    *argv: str,
    env_file_urls: dict[str, str] | None = None,
) -> list[str]:
    """ทรงเดียวกับ `_install_cli` แต่ **ไม่ตั้ง `DATABASE_URL` ไว้ล่วงหน้า**

    ทางเดียวที่ค่านั้นจะมาถึง `main()` คือผ่าน `_load_env()` — ตรงกับของจริงที่อ่าน
    จากไฟล์ `.env`/`.env.<target>` · `env_file_urls=None` = ไฟล์มีอยู่แต่ **ไม่มีคีย์
    `DATABASE_URL`** ซึ่งเป็นสภาพที่เกิดจริงกับ `.env.sit` ที่กรอกไม่ครบ

    คืน list ที่บันทึก target ที่ `_load_env()` ถูกเรียกด้วย — ตามเกณฑ์ของ G5:
    อาร์กิวเมนต์ของทุกจุดต่อต้องมีอย่างน้อยหนึ่งเทสที่ค่าไม่ใช่ default
    """
    loaded: list[str] = []

    def fake_load_env(target: str) -> None:
        loaded.append(target)
        url = (env_file_urls or {}).get(target)
        if url is not None:
            monkeypatch.setenv("DATABASE_URL", url)

    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setattr(mod, "_load_env", fake_load_env)
    monkeypatch.setattr(
        sys, "argv", ["correction_entry.py", "--file", str(path), *argv]
    )
    return loaded


def test_main_gets_its_database_url_from_the_env_of_the_target(
    monkeypatch, tmp_path, capsys
) -> None:
    """🔴 ตัวฆ่า mutation ที่ **ถอด `_load_env(args.target)` ออกจาก `main()`**

    ไม่มีใครตั้ง `DATABASE_URL` ให้ล่วงหน้า — ถ้าบรรทัดนั้นหายไป สคริปต์จะไม่มีทาง
    รู้ปลายทางเลยและจบที่ `return 1` · ที่ล็อกไว้ไม่ใช่แค่ "ถูกเรียก" แต่คือ **ค่าที่
    มันเติมเข้ามาเดินไปถึงด่านและถึงป้ายปลายทางที่พิมพ์ออกจอ**
    """
    path, session, posters = _install_fakes(
        monkeypatch,
        tmp_path,
        [_raw(condition_grade="fine", condition_grade_reason=WHY_GRADE)],
    )
    loaded = _install_cli_with_env_file(
        monkeypatch,
        path,
        "--commit",
        "--reviewed-by",
        "chanothai",
        "--reviewed-at",
        REVIEWED_AT_CLI,
        env_file_urls=G6_ENV_FILE_URLS,
    )

    assert mod.main() == 0
    assert loaded == ["dev"]
    captured = capsys.readouterr()
    # ป้ายปลายทาง derive จาก url ที่ `_load_env()` เติมมา — ไม่ใช่จากค่าคงที่ที่ไหน
    assert f"ปลายทาง : {G6_DEV_TARGET_LABEL}  [--target dev]" in captured.out
    assert session.committed is True
    assert posters[PID].writes == {"condition_grade": PosterCondition.fine}


def test_main_loads_the_env_of_the_target_the_human_typed_not_a_constant(
    monkeypatch, tmp_path, capsys
) -> None:
    """🔴 ตัวฆ่า mutation ที่ hardcode **อาร์กิวเมนต์** เป็น `_load_env("dev")`

    ผลจริงของ mutation นั้น: สั่ง `--target sit` แล้วได้ `DATABASE_URL` ของ dev
    มานั่งอยู่ในมือ · ด่าน `assert_target()` ยังจับได้ก็จริง (เพราะชื่อ database
    ไม่ตรงกับ target) แต่ชั้นที่พังคือชั้นที่ *เลือกปลายทาง* ไม่ใช่ชั้นที่ตรวจ —
    และวันที่ชื่อ database ของสองปลายทางบังเอิญเข้ากันได้ ด่านนั้นจะไม่จับอีกเลย

    🔴 **ห้าม assert ข้อความ error ของเคสนี้** — ต่างกันตามว่าเครื่องที่รันเทสมี
    `.env.sit` ไหม (เหตุผลเต็มอยู่ที่ `test_main_passes_the_target_the_human_typed
    _not_a_constant` §G5) · `loaded` กับ url ที่ถูกส่งเข้าด่านเหมือนกันทั้งสองสภาพ
    """
    seen: list[tuple[str, str]] = []
    real_assert_target = mod.assert_target

    def spy(database_url: str, target: str) -> str:
        seen.append((database_url, target))
        return real_assert_target(database_url, target)

    monkeypatch.setattr(mod, "assert_target", spy)
    path, session, posters = _install_fakes(
        monkeypatch,
        tmp_path,
        [_raw(condition_grade="fine", condition_grade_reason=WHY_GRADE)],
    )
    loaded = _install_cli_with_env_file(
        monkeypatch,
        path,
        "--target",
        "sit",
        "--commit",
        "--reviewed-by",
        "chanothai",
        "--reviewed-at",
        REVIEWED_AT_CLI,
        env_file_urls=G6_ENV_FILE_URLS,
    )

    assert mod.main() == 1
    assert loaded == ["sit"]
    # url ที่เข้าด่านต้องเป็นของ **sit** — ของ dev แปลว่าโหลดไฟล์ผิดตัว
    assert seen == [(G6_ENV_FILE_URLS["sit"], "sit")]
    assert session.added == []
    assert session.committed is False
    assert all(spy_poster.writes == {} for spy_poster in posters.values())
    capsys.readouterr()


def test_main_names_the_missing_database_url_instead_of_blaming_the_target(
    monkeypatch, tmp_path, capsys
) -> None:
    """🔴 ตัวฆ่า mutation ที่ **ถอด guard `if not database_url` ออก**

    ถอดแล้วยัง fail-closed อยู่ (`assert_target("")` ไม่ผ่าน) — แต่สิ่งที่คนได้คือ
    "precheck ไม่ผ่าน" ซึ่งส่งคนไปแก้ *ปลายทาง* ทั้งที่ปลายทางไม่ได้ผิดอะไร ปัญหา
    คือ env ยังไม่ถูกโหลด · ด่านนี้จึงมีค่าที่ **การวินิจฉัย** ไม่ใช่ที่การหยุด
    assertion เชิงลบข้างล่างคือตัวที่แยกสองอย่างนี้ออกจากกัน
    """
    path, session, posters = _install_fakes(
        monkeypatch,
        tmp_path,
        [_raw(condition_grade="fine", condition_grade_reason=WHY_GRADE)],
    )
    loaded = _install_cli_with_env_file(
        monkeypatch,
        path,
        "--commit",
        "--reviewed-by",
        "chanothai",
        "--reviewed-at",
        REVIEWED_AT_CLI,
        env_file_urls=None,  # ไฟล์มีอยู่ แต่ไม่มีคีย์ DATABASE_URL
    )

    assert mod.main() == 1
    assert loaded == ["dev"]
    captured = capsys.readouterr()
    assert "ไม่พบ DATABASE_URL (target=dev)" in captured.err
    assert "precheck ไม่ผ่าน" not in captured.err
    assert session.added == []
    assert session.committed is False
    assert all(spy_poster.writes == {} for spy_poster in posters.values())
