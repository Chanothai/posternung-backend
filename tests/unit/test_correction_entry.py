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
    rows_that_already_break_one_row_one_piece,
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
            values={"is_unique": False},
            reasons={"is_unique": WHY_UNIQUE},
            lineno=3,
        ),
        _row(poster_uuid=PID3, values={}, reasons={}, lineno=4),
    ]
    plans = plan_writes(
        rows,
        {
            PID: _state(),
            PID2: _state(condition_grade=PosterCondition.mint),
            PID3: _state(),
        },
    )
    written: set[str] = set()
    for plan in plans:
        assert set(plan.field_writes) <= set(WRITABLE_FIELDS)
        written |= set(plan.field_writes)
    assert written == set(WRITABLE_FIELDS)


# --------------------------------------------------------------------------
# ADR-0019 D1 — `is_unique = N` ได้เฉพาะเกรด `mint`
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "grade",
    [g for g in PosterCondition if g is not PosterCondition.mint],
    ids=lambda g: g.value,
)
def test_marking_a_row_as_multi_piece_is_blocked_on_every_grade_below_mint(
    grade: PosterCondition,
) -> None:
    """🔴 ADR-0019 **D1** — *"ไม่มีข้อยกเว้น ไม่มีดุลพินิจ"* · parametrize ทั้ง enum
    เพื่อไม่ให้ใครเปิดช่องให้เกรดใดเกรดหนึ่งทีหลังโดยไม่มีอะไรฟ้อง

    ผลวันนี้: `N` เขียนไม่ได้เลยแม้แถวเดียวเพราะทั้งตารางไม่มีใบไหนเป็น `mint`
    — **นั่นคือผลที่ถูกต้อง ไม่ใช่บั๊ก**
    """
    plan = plan_writes(
        [_row(values={"is_unique": False}, reasons={"is_unique": WHY_UNIQUE})],
        {PID: _state(condition_grade=grade)},
    )[0]
    assert plan.action is RowAction.BLOCKED
    assert plan.blockers
    assert "ADR-0019 D1" in plan.blockers[0]
    assert "mint" in plan.blockers[0]


def test_marking_a_mint_row_as_multi_piece_is_allowed() -> None:
    """🔴 ด้านที่ต้องไม่พัง — ด่านที่ปฏิเสธทุกเกรดก็ยังเขียวถ้าไม่มีเทสตัวนี้"""
    plan = plan_writes(
        [_row(values={"is_unique": False}, reasons={"is_unique": WHY_UNIQUE})],
        {PID: _state(condition_grade=PosterCondition.mint)},
    )[0]
    assert plan.action is RowAction.WRITE
    assert plan.blockers == ()
    assert plan.overwrites == {"is_unique": ("True", "False")}


def test_the_grade_written_in_this_same_round_is_what_the_gate_looks_at() -> None:
    """ยกเกรดขึ้น `mint` และประกาศหลายชิ้นในแถวเดียวกันต้องผ่าน — ด่านที่ดูแต่ค่าเดิม
    จะปฏิเสธการแก้ที่ถูกต้อง (และด่านที่ดูแต่ค่าใหม่จะปล่อยการแก้ที่ผิด)"""
    plan = plan_writes(
        [
            _row(
                values={
                    "condition_grade": PosterCondition.mint,
                    "is_unique": False,
                },
                reasons={"condition_grade": WHY_GRADE, "is_unique": WHY_UNIQUE},
            )
        ],
        {PID: _state()},
    )[0]
    assert plan.action is RowAction.WRITE


def test_downgrading_a_mint_row_while_declaring_multi_piece_is_blocked() -> None:
    """ทิศตรงข้าม — ค่าเดิมเป็น `mint` แต่รอบนี้ลดเกรดลง ต้องถูกปฏิเสธ"""
    plan = plan_writes(
        [
            _row(
                values={
                    "condition_grade": PosterCondition.near_mint,
                    "is_unique": False,
                },
                reasons={"condition_grade": WHY_GRADE, "is_unique": WHY_UNIQUE},
            )
        ],
        {PID: _state(condition_grade=PosterCondition.mint)},
    )[0]
    assert plan.action is RowAction.BLOCKED


def test_setting_is_unique_to_yes_is_never_blocked_by_the_grade() -> None:
    """`Y` = ของชิ้นเดียว ซึ่งถูกต้องทุกเกรดตาม D1"""
    plan = plan_writes(
        [_row(values={"is_unique": True}, reasons={"is_unique": WHY_UNIQUE})],
        {PID: _state(condition_grade=PosterCondition.poor, is_unique=False)},
    )[0]
    assert plan.action is RowAction.WRITE
    assert plan.blockers == ()


def test_a_row_that_already_breaks_d1_is_only_a_warning_never_a_blocker() -> None:
    """🔴 สภาพนี้มีอยู่ใน DB ก่อนสคริปต์นี้เกิด (ADR-0019 — 31 แถว) · ด่านปฏิเสธจะ
    ปฏิเสธใบงานที่ถูกต้องตั้งแต่รันครั้งแรก และปิดทางเดียวที่มีในการ**แก้**สภาพนั้น"""
    plans = plan_writes([_row()], {PID: _state(is_unique=False)})
    assert plans[0].action is RowAction.WRITE
    assert plans[0].blockers == ()
    assert rows_that_already_break_one_row_one_piece(plans) == [(2, "fine")]


def test_a_compliant_row_produces_no_warning() -> None:
    plans = plan_writes([_row()], {PID: _state()})
    assert rows_that_already_break_one_row_one_piece(plans) == []


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
                    "is_unique": False,
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
        {PID: _state(), PID2: _state(is_unique=False)},
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
                    "is_unique": False,
                },
                reasons={"condition_grade": WHY_GRADE, "is_unique": WHY_UNIQUE},
            )
        ],
        {PID: _state()},
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


async def _run_applier(
    monkeypatch,
    tmp_path,
    sheet_rows,
    *,
    commit: bool = True,
    state: dict | None = None,
    fields: list[str] | None = None,
):
    """เรียก `run()` จริง โดยแทนเฉพาะ **ทางเข้าออก DB** — ตรรกะทั้งหมดเป็นของจริง"""
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
            if spy is not None:
                values.update(spy.writes)
            out[pid] = mod.PosterState(values=values)
        return out

    monkeypatch.setattr(db_mod, "async_session_maker", lambda: session)
    monkeypatch.setattr(mod, "_load_state", fake_load_state)

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


async def test_a_blocked_row_stops_the_whole_run_before_commit_has_any_effect(
    monkeypatch, tmp_path, capsys
):
    """🔴 ADR-0019 D1 ที่ **runtime** — `--commit` ถูกส่งมาแล้วก็ยังต้องไม่มีอะไรลง

    ด่านนี้ต้องรู้สถานะ DB จึงอยู่ใน `plan_writes()` ไม่ใช่ `parse_rows()` —
    แต่ยัง **ไม่มีที่ไหน rollback** เพราะ `run()` คืน 1 ก่อนถึงลูปเขียน
    """
    rc, session, posters = await _run_applier(
        monkeypatch,
        tmp_path,
        [
            _raw(condition_grade="fine", condition_grade_reason=WHY_GRADE),
            _raw(poster_uuid=str(PID2), is_unique="N", is_unique_reason=WHY_UNIQUE),
        ],
        state={PID: _state(), PID2: _state()},
    )
    assert rc == 1
    assert session.added == []
    assert session.committed is False
    assert all(spy.writes == {} for spy in posters.values())
    out = capsys.readouterr().out
    assert "ปฏิเสธทั้งไฟล์" in out
    # แม้แถวแรกจะถูกต้องทุกอย่างก็ต้องไม่ถูกเขียน (fail-closed)
    assert posters[PID].writes == {}


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
