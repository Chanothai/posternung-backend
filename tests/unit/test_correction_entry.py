"""Unit tests ของ `scripts/seed/correction_entry.py` — ADR-0010 Amendment 2026-08-09
· ADR-0027 (INF-29 — เส้นที่ 5 เซ็นรับ + ถอนของ)

ไม่ต่อ DB จริง (ยกเว้น `test_correction_entry_run_harness.py` ที่แยกไฟล์) — เกือบทั้งหมด
ทำกับฟังก์ชัน pure ซึ่งรับสถานะเข้ามาแทนการ query เอง ตาม ship-backend-change §3

🔴 **มุตทีชันทั้ง 6 ตัวที่ AC-8 ของ INF-29 สั่งให้พิสูจน์ — และที่ที่เทสไปยืน**

| # | mutation | ตัวฆ่าในไฟล์นี้ |
|---|---|---|
| 1 | ยอมให้ `published_at` ถูก *ตั้ง* ค่า | §vocabulary (parser+refuse) + §run runtime spy (`test_run_never_sets_published_at_to_anything_but_none`) |
| 2 | ถอด cascade ของ D6 | §cascade (pure) + harness ระดับ DB |
| 3 | ยอมถอนใบที่ `sold` | §sold gate (pure) + harness (ไม่มีอะไรถูกเขียนเลย) |
| 4 | ให้ cascade ฟัง `--field` | §cascade `test_the_cascade_ignores_the_field_flag` + harness |
| 5 | สลับลำดับ cascade กับ SIGN ในแถวเดียว | §cascade `test_sign_tops_the_cascade_effect_on_verified_at` + harness |
| 6 | ด่านก่อนเซ็นคืน `()` เสมอ | §pre-sign gate — assert ชื่อ blocker เป็นตัว ๆ ไม่ใช่แค่ `!= ()` |
"""

from __future__ import annotations

import argparse
import ast
import csv
import inspect
import sys
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from app.models.enums import PosterCondition, PosterStatus
from app.models.poster import Poster
from app.services.poster_service import PublishBlocker
from scripts.seed import correction_entry as mod
from scripts.seed import manual_entry as manual_mod
from scripts.seed.correction_entry import (
    CORRECTION_SHEET_COLUMNS,
    CURRENT_COLUMNS,
    IS_UNIQUE_ONLY_WRITABLE_VALUE,
    IS_UNIQUE_WORDS,
    KEEP_WORD,
    NULL_BEFORE_ALLOWED,
    PUBLISHED_AT_ONLY_WRITABLE_VALUE,
    REASON_COLUMNS,
    REQUIRED_COLUMNS,
    VERIFIED_AT_ONLY_WRITABLE_VALUE,
    WRITABLE_FIELDS,
    AuditEntry,
    CorrectionRow,
    FieldMode,
    PosterState,
    PrecheckError,
    RowAction,
    assert_no_row_targets_a_sold_poster,
    assert_own_sheet,
    assert_schema_ready,
    assert_signable,
    audit_entries,
    field_specs,
    parse_is_unique,
    parse_rows,
    plan_writes,
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
# instant เดียวกันกับ REVIEWED_AT แต่เขียนคนละ offset — ใช้พิสูจน์ว่า verify_corrections
# เทียบความหมาย (instant) ไม่ใช่สตริง (จุดที่พังเงียบ #1 ของแผน architect)
REVIEWED_AT_UTC_SAME_INSTANT = REVIEWED_AT.astimezone(UTC)

WHY_GRADE = "ดูใบจริงซ้ำ พบรอยพับที่มุมล่างขวาซึ่งไม่ได้บันทึกไว้รอบแรก"
WHY_UNIQUE = "นับใบจริงในกล่องแล้วมีใบเดียว"
WHY_SIGN = "ตรวจครบทุกมิติแล้ว ของตรงกับที่บันทึกไว้ทุกอย่าง"
WHY_WITHDRAW = "พบว่าข้อมูลผิดหลังตรวจซ้ำ ดึงออกจากร้านก่อนแก้"


def _raw(**over: str) -> dict[str, str]:
    row = {
        "poster_uuid": str(PID),
        "title": "Some Poster",
        "image_url": "https://example.invalid/a.jpg",
        "current_condition_grade": "near_mint",
        "current_is_unique": "Y",
        "current_verified_at": "",
        "current_published_at": "",
        "condition_grade": "",
        "condition_grade_reason": "",
        "is_unique": "",
        "is_unique_reason": "",
        "verified_at": "",
        "verified_at_reason": "",
        "published_at": "",
        "published_at_reason": "",
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
    """ค่าปริยาย = ใบปกติที่ยังไม่เคยเซ็น/publish — `status`/`front_image_count`
    ไม่ใช่ `WRITABLE_FIELDS` จึงแยกออกมาก่อน `.update()` ที่เหลือ (ทรงเดียวกับ
    `manual_entry._make_poster` §test-quality §6: ค่าปริยายต้องเป็นเคสปกติของ
    production ไม่ใช่ทุกอย่างว่าง)
    """
    status = over.pop("status", PosterStatus.available)
    front_image_count = over.pop("front_image_count", 1)
    values: dict[str, object] = {
        "condition_grade": PosterCondition.near_mint,
        "is_unique": True,
        "verified_at": None,
        "published_at": None,
    }
    values.update(over)
    return PosterState(
        values=values, status=status, front_image_count=front_image_count
    )


def _plan(
    rows: list[CorrectionRow],
    current: dict[uuid.UUID, PosterState],
    fields: tuple[str, ...] = WRITABLE_FIELDS,
    *,
    signed_at: datetime = REVIEWED_AT,
) -> list[mod.PlannedWrite]:
    return plan_writes(rows, current, fields, signed_at=signed_at)


# --------------------------------------------------------------------------
# FIELD_MODES / vocabulary — ADR-0027 §AC-1 · §AC-2
# --------------------------------------------------------------------------


def test_field_modes_covers_exactly_the_writable_fields() -> None:
    assert set(mod.FIELD_MODES) == set(WRITABLE_FIELDS)
    assert mod.FIELD_MODES["condition_grade"] is FieldMode.VALUE
    assert mod.FIELD_MODES["is_unique"] is FieldMode.VALUE
    assert mod.FIELD_MODES["verified_at"] is FieldMode.COMMAND
    assert mod.FIELD_MODES["published_at"] is FieldMode.COMMAND


@pytest.mark.parametrize("raw", ["sign", "SIGN", "Sign"])
def test_sign_is_readable_on_any_case(raw: str) -> None:
    assert field_specs()["verified_at"].parse(raw) == "SIGN"


@pytest.mark.parametrize("raw", ["keep", "KEEP", "unsign", "UNSIGN"])
def test_verified_at_reads_keep_and_unsign_without_raising(raw: str) -> None:
    """อ่านออก — ต่างจากด่านนโยบายที่ปฏิเสธการ *เขียน* (ดู §policy)"""
    value = field_specs()["verified_at"].parse(raw)
    assert value in ("KEEP", "UNSIGN")


def test_verified_at_rejects_an_unknown_word() -> None:
    with pytest.raises(ValueError, match="ช่องเซ็นรับ"):
        field_specs()["verified_at"].parse("PUBLISH")


@pytest.mark.parametrize("raw", ["withdraw", "WITHDRAW"])
def test_withdraw_is_readable_on_any_case(raw: str) -> None:
    assert field_specs()["published_at"].parse(raw) == "WITHDRAW"


@pytest.mark.parametrize("raw", ["keep", "KEEP", "publish", "PUBLISH"])
def test_published_at_reads_keep_and_publish_without_raising(raw: str) -> None:
    value = field_specs()["published_at"].parse(raw)
    assert value in ("KEEP", "PUBLISH")


def test_published_at_rejects_an_unknown_word() -> None:
    with pytest.raises(ValueError, match="ช่องถอนของ"):
        field_specs()["published_at"].parse("SIGN")


# --------------------------------------------------------------------------
# มุตทีชัน 1 — `refuse_unwritable_value`: SIGN/WITHDRAW เขียนได้ ที่เหลือเขียนไม่ได้
# --------------------------------------------------------------------------


def test_sign_is_the_only_writable_value_of_verified_at() -> None:
    assert refuse_unwritable_value("verified_at", "SIGN") is None
    assert VERIFIED_AT_ONLY_WRITABLE_VALUE == "SIGN"


def test_unsign_is_refused_for_verified_at() -> None:
    reason = refuse_unwritable_value("verified_at", "UNSIGN")
    assert reason is not None
    assert "เขียนไม่ได้" in reason


def test_keep_is_a_no_op_writable_value_of_verified_at() -> None:
    """🔴 G2 (code-critic รอบ 1 ของ INF-29) — KEEP = "ไม่ทำอะไร" (ADR-0027 D7) ไม่ใช่
    error เหมือน UNSIGN · รุ่นก่อนปฏิเสธ KEEP เหมือนกัน ทำให้คนก๊อป current_verified_at
    มาแปะโดนปฏิเสธทั้งไฟล์"""
    assert refuse_unwritable_value("verified_at", "KEEP") is None
    assert refuse_unwritable_value("verified_at", KEEP_WORD) is None


def test_withdraw_is_the_only_writable_value_of_published_at() -> None:
    assert refuse_unwritable_value("published_at", "WITHDRAW") is None
    assert PUBLISHED_AT_ONLY_WRITABLE_VALUE == "WITHDRAW"


def test_publish_is_refused_for_published_at() -> None:
    reason = refuse_unwritable_value("published_at", "PUBLISH")
    assert reason is not None
    assert "เขียนไม่ได้" in reason


def test_keep_is_a_no_op_writable_value_of_published_at() -> None:
    """🔴 G2 — คู่แฝดของ verified_at ข้างบน"""
    assert refuse_unwritable_value("published_at", "KEEP") is None
    assert refuse_unwritable_value("published_at", KEEP_WORD) is None


def test_publish_refusal_names_lane_three_as_the_only_setter() -> None:
    """🔴 มุตทีชัน 1 (parser layer) — ข้อความต้องชี้ไปที่เส้นที่ 3 ไม่ใช่แค่บอกว่าใช้ไม่ได้"""
    reason = refuse_unwritable_value("published_at", "PUBLISH")
    assert reason is not None
    assert "manual_entry.py" in reason


def test_refusal_of_condition_grade_is_never_triggered() -> None:
    """condition_grade ไม่มีด่านนโยบายของตัวเอง — ทุกค่าที่ parse ผ่านมาได้เขียนได้"""
    assert refuse_unwritable_value("condition_grade", PosterCondition.mint) is None


# --------------------------------------------------------------------------
# closed-world สามชั้นว่าเขียนได้เฉพาะสี่คอลัมน์ (AC-1)
# --------------------------------------------------------------------------

POSTER_COLUMNS = set(Poster.__table__.columns.keys())


def _names_the_module_mentions(module) -> set[str]:
    """ชื่อทุกตัวที่โมดูลเอ่ยถึงในซอร์ส — **string literal และ `<obj>.attr`**

    🔴 `ast.Attribute.attr` เป็น `str` ธรรมดา **ไม่ใช่ `ast.Constant`** — การสแกนหา
    เฉพาะ literal จึงมองไม่เห็น `poster.needs_review = False` เลยแม้แต่น้อย
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

    🔴 **`status` ต้องอยู่ในเซตนี้ได้แล้ว** (ต่างจากรุ่นก่อน INF-29) — ด่าน sold
    (A-D11) ต้องอ่าน `poster.status`/`Poster.status` ได้ · **ยังห้าม `needs_review`**
    · ชดเชยด้านที่อ่อนลงนี้ด้วยเทส runtime ที่ `_PosterSpy` ยืนยันว่า `status` ไม่เคย
    ถูก `setattr` เลยตลอดชุดเทสของ `run()` ข้างล่าง
    """
    named = _names_the_module_mentions(mod) & POSTER_COLUMNS
    assert named == {*WRITABLE_FIELDS, "title", "id", "status"}


def test_writable_set_is_exactly_the_four_columns_of_adr_0027() -> None:
    """🔴 ADR-0027 D7 คือการแก้ ADR-0010 A-D2 ข้อ 6 — การเพิ่มฟิลด์ต้องผ่าน ADR ก่อน
    ไม่ใช่แก้ค่าคงที่เงียบ ๆ แล้วเทสเดิมยังเขียว"""
    assert WRITABLE_FIELDS == (
        "condition_grade",
        "is_unique",
        "verified_at",
        "published_at",
    )
    assert len(WRITABLE_FIELDS) == 4
    for forbidden in ("status", "price", "needs_review", "title"):
        assert forbidden not in WRITABLE_FIELDS


def test_every_writable_field_has_a_spec_and_vice_versa() -> None:
    assert set(field_specs()) == set(WRITABLE_FIELDS)


def test_the_cli_refuses_a_field_outside_the_allowlist(monkeypatch) -> None:
    monkeypatch.setattr(sys, "argv", ["correction_entry.py", "--field", "price"])
    with pytest.raises(SystemExit) as exc:
        mod.main()
    assert exc.value.code == 2


def test_the_cli_choices_are_the_allowlist_object_itself_not_a_copy() -> None:
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
    assert set(manual_mod.OVERWRITE_ELIGIBLE) == {"title", "year"}
    assert set(manual_mod.OVERWRITE_ELIGIBLE).isdisjoint(WRITABLE_FIELDS)


def test_the_grade_parser_is_the_same_object_as_lane_three_not_a_copy() -> None:
    assert mod._enum_parser is manual_mod._enum_parser
    assert mod.render_value is manual_mod.render_value
    assert mod.TARGETS is manual_mod.TARGETS
    assert mod.assert_target is manual_mod.assert_target
    assert mod.load_count_actual_by_poster is manual_mod.load_count_actual_by_poster


def test_publish_blockers_is_the_same_object_as_poster_service() -> None:
    """ADR-0026 D8 — ด่านก่อนเซ็นต้องเรียกของจริง ไม่ใช่ก๊อปเงื่อนไขมาเขียนซ้ำ"""
    from app.services.poster_service import publish_blockers as real

    assert mod.publish_blockers is real


def test_production_is_not_a_selectable_target() -> None:
    assert mod.TARGETS == ("dev", "sit")


# --------------------------------------------------------------------------
# ใบงาน — คอลัมน์ (ประกอบจาก WRITABLE_FIELDS ไม่ hardcode)
# --------------------------------------------------------------------------


def test_the_sheet_has_a_reason_column_per_writable_field() -> None:
    assert CORRECTION_SHEET_COLUMNS == (
        "poster_uuid",
        "title",
        "image_url",
        "current_condition_grade",
        "current_is_unique",
        "current_verified_at",
        "current_published_at",
        "condition_grade",
        "condition_grade_reason",
        "is_unique",
        "is_unique_reason",
        "verified_at",
        "verified_at_reason",
        "published_at",
        "published_at_reason",
    )
    assert REASON_COLUMNS == (
        "condition_grade_reason",
        "is_unique_reason",
        "verified_at_reason",
        "published_at_reason",
    )
    assert len(REASON_COLUMNS) == len(WRITABLE_FIELDS)
    assert CURRENT_COLUMNS == (
        "current_condition_grade",
        "current_is_unique",
        "current_verified_at",
        "current_published_at",
    )


def test_the_key_is_the_uuid_never_the_title() -> None:
    assert REQUIRED_COLUMNS[0] == "poster_uuid"
    assert "title" not in REQUIRED_COLUMNS


class _RecordingRow(dict):
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
    fields = {f.name for f in CorrectionRow.__dataclass_fields__.values()}
    assert fields.isdisjoint(CURRENT_COLUMNS)
    assert set(CURRENT_COLUMNS).isdisjoint(REQUIRED_COLUMNS)


def test_missing_required_column_is_reported_by_name(tmp_path) -> None:
    path = tmp_path / "correction-entry.csv"
    path.write_text("poster_uuid,condition_grade\n", encoding="utf-8")
    with pytest.raises(PrecheckError, match="condition_grade_reason"):
        read_sheet(path)


def test_an_old_two_column_sheet_is_refused_with_a_hint_to_regenerate(
    tmp_path,
) -> None:
    """🔴 จุดที่พังเงียบ #5 ของแผน — ใบงานรุ่นเก่า (ก่อน INF-29) ถูกปฏิเสธทั้งไฟล์
    เพราะ REQUIRED_COLUMNS โต ข้อความต้องบอกทางออก (regenerate)"""
    path = tmp_path / "correction-entry.csv"
    path.write_text(
        "poster_uuid,condition_grade,condition_grade_reason,is_unique,"
        "is_unique_reason\n",
        encoding="utf-8",
    )
    with pytest.raises(PrecheckError, match="verified_at_reason"):
        read_sheet(path)


# --------------------------------------------------------------------------
# reason บังคับต่อค่า · ขาดแถวเดียว = ปฏิเสธทั้งไฟล์ (AC-2 เดิม — ครอบ 4 ฟิลด์)
# --------------------------------------------------------------------------


def test_one_row_without_a_reason_rejects_the_whole_file() -> None:
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


def test_sign_without_a_reason_rejects_the_whole_file() -> None:
    with pytest.raises(PrecheckError, match="verified_at_reason ว่าง"):
        parse_rows([_raw(verified_at="SIGN")])


def test_withdraw_without_a_reason_rejects_the_whole_file() -> None:
    with pytest.raises(PrecheckError, match="published_at_reason ว่าง"):
        parse_rows([_raw(published_at="WITHDRAW")])


def test_the_very_same_file_with_the_reason_filled_in_produces_four_field_rows() -> (
    None
):
    rows = parse_rows(
        [
            _raw(
                condition_grade="fine",
                condition_grade_reason=WHY_GRADE,
                is_unique="Y",
                is_unique_reason=WHY_UNIQUE,
                verified_at="SIGN",
                verified_at_reason=WHY_SIGN,
                published_at="WITHDRAW",
                published_at_reason=WHY_WITHDRAW,
            )
        ]
    )
    assert len(rows) == 1
    assert set(rows[0].values) == set(WRITABLE_FIELDS)
    assert rows[0].values["verified_at"] == "SIGN"
    assert rows[0].values["published_at"] == "WITHDRAW"


def test_every_parsed_value_always_carries_a_reason_with_the_same_keys() -> None:
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
    assert (
        set(rows[0].values) == set(rows[0].reasons) == {"condition_grade", "is_unique"}
    )


def test_a_reason_without_a_value_rejects_the_whole_file() -> None:
    with pytest.raises(PrecheckError, match="ข้อมูลขัดกันเอง"):
        parse_rows([_raw(condition_grade_reason=WHY_GRADE)])


def test_both_blank_is_normal_and_produces_a_row_with_nothing_to_write() -> None:
    (row,) = parse_rows([_raw()])
    assert row.values == {}
    assert row.reasons == {}


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


def test_a_keep_typed_with_a_reason_is_accepted_as_a_no_op() -> None:
    """🔴 G2 (code-critic รอบ 1 ของ INF-29) — KEEP = "ไม่ทำอะไร" (ADR-0027 D7) ·
    รุ่นก่อนปฏิเสธค่านี้ทั้งไฟล์เหมือน N ของ is_unique ซึ่งผิด: คนที่ก๊อป
    current_verified_at (คำช่วยจำที่ render_current_value() ตั้งใจให้ก๊อปได้) มาแปะ
    พร้อมเหตุผลควรผ่านเงียบ ๆ ไม่ใช่ถูกปฏิเสธ — การมีเหตุผลติดมาไม่ใช่ข้อมูลขัดกันเอง
    เพราะ KEEP ไม่มีการเขียนให้เหตุผลอธิบาย"""
    (row,) = parse_rows([_raw(verified_at="KEEP", verified_at_reason=WHY_SIGN)])
    assert row.values == {}
    assert row.reasons == {}


def test_a_keep_typed_without_a_reason_is_also_accepted_as_a_no_op() -> None:
    """KEEP ไม่บังคับเหตุผลเลย — ต่างจากทุกฟิลด์อื่นที่กรอกค่าแล้วไม่กรอกเหตุผล = error"""
    (row,) = parse_rows([_raw(published_at="KEEP")])
    assert row.values == {}
    assert row.reasons == {}


def test_unsign_typed_with_a_reason_rejects_the_whole_file() -> None:
    with pytest.raises(PrecheckError, match="UNSIGN"):
        parse_rows([_raw(verified_at="UNSIGN", verified_at_reason=WHY_SIGN)])


def test_publish_typed_with_a_reason_rejects_the_whole_file() -> None:
    with pytest.raises(PrecheckError, match="PUBLISH"):
        parse_rows([_raw(published_at="PUBLISH", published_at_reason=WHY_WITHDRAW)])


# --------------------------------------------------------------------------
# is_unique = N — เหมือนเดิมทุกประการ (ยังไม่แตะ)
# --------------------------------------------------------------------------


@pytest.mark.parametrize("raw", ["Y", "y"])
def test_yes_parses_to_true(raw: str) -> None:
    assert parse_is_unique(raw) is True


@pytest.mark.parametrize("raw", ["N", "n"])
def test_no_parses_to_false(raw: str) -> None:
    assert parse_is_unique(raw) is False


def test_the_words_the_sheet_prints_are_the_words_the_parser_reads() -> None:
    assert set(mod.IS_UNIQUE_TEXT) == set(IS_UNIQUE_WORDS.values())
    for value, word in mod.IS_UNIQUE_TEXT.items():
        assert parse_is_unique(word) is value


@pytest.mark.parametrize(
    "raw", ["1", "0", "true", "false", "True", "False", "yes", "no", "-", "ใช่"]
)
def test_ambiguous_values_are_refused_not_coerced(raw: str) -> None:
    with pytest.raises(ValueError):
        parse_is_unique(raw)


def test_writing_n_is_refused_on_every_grade_including_mint() -> None:
    for grade in PosterCondition:
        with pytest.raises(PrecheckError, match="เขียนไม่ได้ในระบบวันนี้"):
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


def test_setting_is_unique_to_yes_is_never_refused() -> None:
    assert IS_UNIQUE_ONLY_WRITABLE_VALUE is True
    plan = _plan(
        [_row(values={"is_unique": True}, reasons={"is_unique": WHY_UNIQUE})],
        {PID: _state(condition_grade=PosterCondition.poor, is_unique=False)},
    )[0]
    assert plan.action is RowAction.WRITE
    assert plan.overwrites["is_unique"] == ("False", "True")


def test_rows_still_false_after_this_round_are_reported_as_a_warning_only() -> None:
    plans = _plan([_row()], {PID: _state(is_unique=False)})
    assert plans[0].action is RowAction.WRITE
    assert rows_still_marked_as_multi_piece(plans) == (2,)


def test_a_row_this_round_is_fixing_is_not_listed_as_still_false() -> None:
    plans = _plan(
        [_row(values={"is_unique": True}, reasons={"is_unique": WHY_UNIQUE})],
        {PID: _state(is_unique=False)},
    )
    assert rows_still_marked_as_multi_piece(plans) == ()


# --------------------------------------------------------------------------
# plan_writes — VALUE fields: ทับ · ค่าเท่าเดิม · ปลายทางว่าง · ไม่มีใบ · --field
# --------------------------------------------------------------------------


def test_a_real_change_becomes_an_overwrite_with_both_sides_recorded() -> None:
    plan = _plan([_row()], {PID: _state()})[0]
    assert plan.action is RowAction.WRITE
    assert plan.field_writes == {"condition_grade": PosterCondition.fine}
    assert plan.overwrites == {"condition_grade": ("near_mint", "fine")}


def test_the_same_value_again_is_not_a_write_and_leaves_no_audit() -> None:
    plan = _plan(
        [_row(values={"condition_grade": PosterCondition.near_mint})],
        {PID: _state()},
    )[0]
    assert plan.action is RowAction.SKIP_SAME
    assert plan.field_writes == {}
    assert plan.unchanged == {"condition_grade": "near_mint"}
    assert audit_entries(plan) == ()


def test_a_null_grade_is_skipped_and_pointed_at_lane_three() -> None:
    plan = _plan([_row()], {PID: _state(condition_grade=None)})[0]
    assert plan.action is RowAction.SKIP_NO_TARGET
    assert plan.field_writes == {}
    assert plan.no_target == ("condition_grade",)
    assert audit_entries(plan) == ()


def test_a_poster_that_is_not_in_the_database_is_skipped_never_inserted() -> None:
    plan = _plan([_row()], {})[0]
    assert plan.action is RowAction.SKIP_NOT_FOUND
    assert plan.field_writes == {}
    assert audit_entries(plan) == ()


def test_field_narrows_what_is_written_but_never_what_is_validated() -> None:
    row = _row(
        values={"condition_grade": PosterCondition.fine, "is_unique": True},
        reasons={"condition_grade": WHY_GRADE, "is_unique": WHY_UNIQUE},
    )
    plan = _plan([row], {PID: _state(is_unique=False)}, ("condition_grade",))[0]
    assert set(plan.field_writes) == {"condition_grade"}


def test_field_defaults_to_all_four_columns() -> None:
    row = _row(
        values={"condition_grade": PosterCondition.fine, "is_unique": True},
        reasons={"condition_grade": WHY_GRADE, "is_unique": WHY_UNIQUE},
    )
    plan = _plan([row], {PID: _state(is_unique=False)})[0]
    assert set(plan.field_writes) == {"condition_grade", "is_unique"}


# --------------------------------------------------------------------------
# plan_writes — SIGN (verified_at)
# --------------------------------------------------------------------------


def test_signing_a_never_verified_poster_writes_verified_at_with_a_null_before() -> (
    None
):
    row = _row(values={"verified_at": "SIGN"}, reasons={"verified_at": WHY_SIGN})
    plan = _plan([row], {PID: _state(verified_at=None)})[0]
    assert plan.action is RowAction.WRITE
    assert plan.field_writes == {"verified_at": REVIEWED_AT}
    assert plan.overwrites == {"verified_at": ("", render_value(REVIEWED_AT))}


def test_re_signing_with_a_new_instant_overwrites_the_old_signature() -> None:
    old = REVIEWED_AT - timedelta(days=1)
    row = _row(values={"verified_at": "SIGN"}, reasons={"verified_at": WHY_SIGN})
    plan = _plan([row], {PID: _state(verified_at=old)})[0]
    assert plan.action is RowAction.WRITE
    assert plan.field_writes == {"verified_at": REVIEWED_AT}
    assert plan.overwrites["verified_at"][0] == render_value(old)


def test_re_signing_with_the_exact_same_instant_is_idempotent() -> None:
    """ADR-0027 §จุดปะทะ — SIGN บนแถวที่เซ็นแล้วด้วยเวลาเดียวกัน = SKIP_SAME
    (ไม่มี audit ปลอม)"""
    row = _row(values={"verified_at": "SIGN"}, reasons={"verified_at": WHY_SIGN})
    plan = _plan([row], {PID: _state(verified_at=REVIEWED_AT)})[0]
    assert plan.action is RowAction.SKIP_SAME
    assert plan.field_writes == {}
    assert audit_entries(plan) == ()


def test_signing_is_never_blocked_by_the_field_flag_scoped_elsewhere() -> None:
    row = _row(values={"verified_at": "SIGN"}, reasons={"verified_at": WHY_SIGN})
    plan = _plan([row], {PID: _state()}, ("verified_at",))[0]
    assert plan.field_writes == {"verified_at": REVIEWED_AT}


def test_signing_is_excluded_when_field_narrows_to_something_else() -> None:
    row = _row(values={"verified_at": "SIGN"}, reasons={"verified_at": WHY_SIGN})
    plan = _plan([row], {PID: _state()}, ("condition_grade",))[0]
    assert "verified_at" not in plan.field_writes


# --------------------------------------------------------------------------
# plan_writes — WITHDRAW (published_at)
# --------------------------------------------------------------------------


def test_withdrawing_an_unpublished_poster_has_nothing_to_withdraw() -> None:
    row = _row(
        values={"published_at": "WITHDRAW"}, reasons={"published_at": WHY_WITHDRAW}
    )
    plan = _plan([row], {PID: _state(published_at=None)})[0]
    assert plan.action is RowAction.SKIP_NO_TARGET
    assert plan.no_target == ("published_at",)
    assert plan.field_writes == {}
    assert audit_entries(plan) == ()


def test_withdrawing_a_published_poster_clears_it_to_null() -> None:
    published = REVIEWED_AT - timedelta(days=10)
    row = _row(
        values={"published_at": "WITHDRAW"}, reasons={"published_at": WHY_WITHDRAW}
    )
    plan = _plan([row], {PID: _state(published_at=published)})[0]
    assert plan.action is RowAction.WRITE
    assert plan.field_writes == {"published_at": None}
    assert plan.overwrites["published_at"] == (render_value(published), "")


def test_the_value_before_a_withdrawal_is_never_null() -> None:
    """AC-7 — `value_before` ของการถอน ห้ามเป็น NULL"""
    published = REVIEWED_AT - timedelta(days=1)
    row = _row(
        values={"published_at": "WITHDRAW"}, reasons={"published_at": WHY_WITHDRAW}
    )
    plan = _plan([row], {PID: _state(published_at=published)})[0]
    (entry,) = audit_entries(plan)
    assert entry.value_before is not None
    assert entry.value_before != ""


# --------------------------------------------------------------------------
# มุตทีชัน 2/4/5 — นโยบายความสด (ADR-0027 D6 cascade)
# --------------------------------------------------------------------------


def test_changing_the_grade_clears_a_signature_and_a_publication_in_one_pass() -> None:
    verified = REVIEWED_AT - timedelta(days=5)
    published = REVIEWED_AT - timedelta(days=5)
    plan = _plan(
        [_row()],  # เปลี่ยนแค่ condition_grade
        {PID: _state(verified_at=verified, published_at=published)},
    )[0]
    assert plan.action is RowAction.WRITE
    assert plan.field_writes["condition_grade"] == PosterCondition.fine
    assert plan.field_writes["verified_at"] is None
    assert plan.field_writes["published_at"] is None
    assert plan.overwrites["verified_at"] == (render_value(verified), "")
    assert plan.overwrites["published_at"] == (render_value(published), "")


def test_changing_is_unique_also_triggers_the_cascade() -> None:
    verified = REVIEWED_AT - timedelta(days=5)
    row = _row(values={"is_unique": True}, reasons={"is_unique": WHY_UNIQUE})
    plan = _plan([row], {PID: _state(is_unique=False, verified_at=verified)})[0]
    assert plan.field_writes["verified_at"] is None


def test_the_cascade_does_nothing_when_there_was_nothing_signed_or_published() -> None:
    """ไม่มีอะไรให้ล้าง — ไม่มี overwrite ปลอมของ verified_at/published_at"""
    plan = _plan([_row()], {PID: _state(verified_at=None, published_at=None)})[0]
    assert "verified_at" not in plan.field_writes
    assert "published_at" not in plan.field_writes


def test_the_cascade_ignores_the_field_flag() -> None:
    """🔴 มุตทีชัน 4 — `--field condition_grade` ยังต้องล้างลายเซ็น ไม่งั้นแฟล็กนี้
    กลายเป็นทางเลี่ยง D6"""
    verified = REVIEWED_AT - timedelta(days=5)
    published = REVIEWED_AT - timedelta(days=5)
    plan = _plan(
        [_row()],
        {PID: _state(verified_at=verified, published_at=published)},
        ("condition_grade",),
    )[0]
    assert plan.field_writes["verified_at"] is None
    assert plan.field_writes["published_at"] is None


def test_the_cascade_produces_its_own_auto_declared_audit_reason() -> None:
    verified = REVIEWED_AT - timedelta(days=5)
    plan = _plan([_row()], {PID: _state(verified_at=verified)})[0]
    entries = {e.field: e for e in audit_entries(plan)}
    assert "อัตโนมัติ" in entries["verified_at"].reason
    assert "ADR-0027 D6" in entries["verified_at"].reason
    assert "condition_grade" in entries["verified_at"].reason


def test_sign_tops_the_cascade_effect_on_verified_at() -> None:
    """🔴 มุตทีชัน 5 — SIGN ในแถวเดียวกับที่แก้เกรด ต้องจบด้วย verified_at = signed_at
    ไม่ใช่ NULL (cascade ต้องไม่ชนะ SIGN)"""
    verified = REVIEWED_AT - timedelta(days=5)
    row = _row(
        values={
            "condition_grade": PosterCondition.fine,
            "verified_at": "SIGN",
        },
        reasons={"condition_grade": WHY_GRADE, "verified_at": WHY_SIGN},
    )
    plan = _plan([row], {PID: _state(verified_at=verified)})[0]
    assert plan.field_writes["verified_at"] == REVIEWED_AT
    (verified_entry,) = [e for e in audit_entries(plan) if e.field == "verified_at"]
    # เหตุผลของคนต้องชนะ ไม่ใช่ข้อความอัตโนมัติของ cascade
    assert verified_entry.reason == WHY_SIGN
    assert verified_entry.value_before == render_value(verified)


def test_sign_still_wins_even_when_the_new_instant_equals_the_old_one() -> None:
    """เคสขอบ — cascade รับประกันว่าแถวเปลี่ยนอยู่แล้ว จึงไม่ตรวจค่าเท่าเดิมของ SIGN
    เมื่อเกิดร่วมกับ cascade (ต่างจากตอน SIGN เดี่ยว ๆ ซึ่งยัง idempotent ตามปกติ)"""
    row = _row(
        values={"condition_grade": PosterCondition.fine, "verified_at": "SIGN"},
        reasons={"condition_grade": WHY_GRADE, "verified_at": WHY_SIGN},
    )
    plan = _plan([row], {PID: _state(verified_at=REVIEWED_AT)})[0]
    assert plan.field_writes["verified_at"] == REVIEWED_AT
    assert "verified_at" not in plan.unchanged


def test_withdraw_in_the_same_row_as_a_grade_change_keeps_the_users_reason() -> None:
    published = REVIEWED_AT - timedelta(days=5)
    row = _row(
        values={
            "condition_grade": PosterCondition.fine,
            "published_at": "WITHDRAW",
        },
        reasons={"condition_grade": WHY_GRADE, "published_at": WHY_WITHDRAW},
    )
    plan = _plan([row], {PID: _state(published_at=published)})[0]
    (entry,) = [e for e in audit_entries(plan) if e.field == "published_at"]
    assert entry.reason == WHY_WITHDRAW


# --------------------------------------------------------------------------
# audit_entries — NULL_BEFORE_ALLOWED + assertion เชิงลบ
# --------------------------------------------------------------------------


def test_null_before_allowed_is_exactly_verified_at() -> None:
    assert NULL_BEFORE_ALLOWED == ("verified_at",)


def test_audit_records_the_real_old_value_not_none_for_a_grade_overwrite() -> None:
    plan = _plan([_row()], {PID: _state()})[0]
    (entry,) = audit_entries(plan)
    assert entry == AuditEntry(
        field="condition_grade",
        value_before="near_mint",
        value_after="fine",
        reason=WHY_GRADE,
    )


def test_a_fresh_signature_is_the_one_case_with_a_null_value_before() -> None:
    row = _row(values={"verified_at": "SIGN"}, reasons={"verified_at": WHY_SIGN})
    plan = _plan([row], {PID: _state(verified_at=None)})[0]
    (entry,) = audit_entries(plan)
    assert entry.value_before is None


def test_no_other_field_may_ever_carry_a_null_value_before() -> None:
    plans = _plan(
        [
            _row(
                values={"condition_grade": PosterCondition.mint, "is_unique": True},
                reasons={"condition_grade": WHY_GRADE, "is_unique": WHY_UNIQUE},
            ),
            _row(
                poster_uuid=PID2,
                values={
                    "published_at": "WITHDRAW",
                },
                reasons={"published_at": WHY_WITHDRAW},
                lineno=3,
            ),
        ],
        {
            PID: _state(is_unique=False),
            PID2: _state(published_at=REVIEWED_AT - timedelta(days=1)),
        },
    )
    entries = [e for plan in plans for e in audit_entries(plan)]
    for entry in entries:
        if entry.field != "verified_at":
            assert entry.value_before is not None
            assert entry.value_before != ""


def test_null_before_guard_raises_for_any_field_other_than_verified_at() -> None:
    """🔴 G4 (code-critic รอบ 1 ของ INF-29) — เทสเชิงลบของ raise ที่กัน
    `value_before = NULL` นอก `NULL_BEFORE_ALLOWED` (มี `# pragma: no cover` มาก่อน
    เพราะไม่เคยมีเทสไหนป้อนสภาพนี้ตรง ๆ) `plan_writes()` ปกติกันสภาพนี้ไม่ให้เกิดโดย
    โครงสร้างอยู่แล้ว — เทสนี้จึงป้อน `PlannedWrite` สังเคราะห์ตรงเข้า `audit_entries()`
    (ข้าม `plan_writes()`) เพื่อพิสูจน์ว่า *ถ้า* โครงสร้างพังในอนาคต ฟังก์ชันนี้ยัง
    fail-closed แทนที่จะปล่อยผ่านเงียบ ๆ

    มุตทีชันใหม่ #8 ของ INF-29 — ถอด `raise` ตัวนี้ทิ้งต้องทำให้เทสนี้แดง
    """
    plan = mod.PlannedWrite(
        row=_row(
            values={"condition_grade": PosterCondition.fine},
            reasons={"condition_grade": WHY_GRADE},
        ),
        action=RowAction.WRITE,
        field_writes={"condition_grade": PosterCondition.fine},
        overwrites={"condition_grade": ("", "fine")},
        unchanged={},
        no_target=(),
        current={},
    )
    with pytest.raises(AssertionError, match="NULL_BEFORE_ALLOWED"):
        audit_entries(plan)


def test_every_audit_entry_carries_the_reason_of_its_own_field() -> None:
    plan = _plan(
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
    """🔴 ไม่มี `await`/session — `.get(name)` ที่ฟังก์ชันนี้เรียกคือ `dict.get()` ของ
    `plan.row.reasons` (pure) ไม่ใช่ `session.get()` จึง**ไม่**อยู่ในรายการต้องห้าม
    (ต่างจากรุ่นก่อน INF-29 ที่ยังไม่มีการเรียก `.get()` เลยในฟังก์ชันนี้)"""
    tree = ast.parse(inspect.getsource(mod.audit_entries))
    assert [n for n in ast.walk(tree) if isinstance(n, ast.Await)] == []
    identifiers = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
    identifiers |= {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
    for forbidden in ("session", "execute", "add", "commit"):
        assert forbidden not in identifiers


def test_run_does_not_build_the_audit_row_inline() -> None:
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
# verify_corrections — เทียบความหมาย ไม่ใช่สตริง (จุดที่พังเงียบ #1)
# --------------------------------------------------------------------------


def test_verify_is_silent_when_a_grade_landed() -> None:
    plans = _plan([_row()], {PID: _state()})
    after = {PID: _state(condition_grade=PosterCondition.fine)}
    assert verify_corrections(plans, after, signed_at=REVIEWED_AT) == []


def test_verify_catches_a_write_that_never_landed() -> None:
    plans = _plan([_row()], {PID: _state()})
    problems = verify_corrections(plans, {PID: _state()}, signed_at=REVIEWED_AT)
    assert len(problems) == 1
    assert "near_mint" in problems[0]
    assert "fine" in problems[0]


def test_verify_catches_a_poster_that_vanished_after_commit() -> None:
    plans = _plan([_row()], {PID: _state()})
    assert verify_corrections(plans, {}, signed_at=REVIEWED_AT) == [
        "บรรทัด 2: อ่านใบกลับมาไม่เจอหลัง commit"
    ]


def test_verify_says_nothing_about_rows_that_were_skipped() -> None:
    plans = _plan([_row()], {PID: _state(condition_grade=None)})
    assert verify_corrections(plans, {}, signed_at=REVIEWED_AT) == []


def test_verify_accepts_a_verified_at_read_back_with_a_different_offset() -> None:
    """🔴 จุดที่พังเงียบ #1 — DB คืน timestamptz เป็น UTC เสมอ ต่าง offset จาก
    `--reviewed-at` ที่คนพิมพ์ (+07:00) แต่เป็น**instant เดียวกัน** — ต้องไม่ false-positive
    """
    row = _row(values={"verified_at": "SIGN"}, reasons={"verified_at": WHY_SIGN})
    plans = _plan([row], {PID: _state(verified_at=None)})
    after = {PID: _state(verified_at=REVIEWED_AT_UTC_SAME_INSTANT)}
    assert verify_corrections(plans, after, signed_at=REVIEWED_AT) == []


def test_verify_catches_a_signature_that_landed_as_the_wrong_instant() -> None:
    row = _row(values={"verified_at": "SIGN"}, reasons={"verified_at": WHY_SIGN})
    plans = _plan([row], {PID: _state(verified_at=None)})
    after = {PID: _state(verified_at=REVIEWED_AT - timedelta(hours=1))}
    problems = verify_corrections(plans, after, signed_at=REVIEWED_AT)
    assert len(problems) == 1
    assert "verified_at" in problems[0]


def test_verify_accepts_a_withdrawal_that_landed_as_none() -> None:
    published = REVIEWED_AT - timedelta(days=1)
    row = _row(
        values={"published_at": "WITHDRAW"}, reasons={"published_at": WHY_WITHDRAW}
    )
    plans = _plan([row], {PID: _state(published_at=published)})
    after = {PID: _state(published_at=None)}
    assert verify_corrections(plans, after, signed_at=REVIEWED_AT) == []


def test_verify_catches_a_withdrawal_that_did_not_actually_clear() -> None:
    published = REVIEWED_AT - timedelta(days=1)
    row = _row(
        values={"published_at": "WITHDRAW"}, reasons={"published_at": WHY_WITHDRAW}
    )
    plans = _plan([row], {PID: _state(published_at=published)})
    after = {PID: _state(published_at=published)}  # ไม่ได้ล้างจริง
    problems = verify_corrections(plans, after, signed_at=REVIEWED_AT)
    assert len(problems) == 1
    assert "published_at" in problems[0]


# --------------------------------------------------------------------------
# มุตทีชัน 3 — ด่าน sold (ADR-0027 A-D11)
# --------------------------------------------------------------------------


def test_a_row_touching_a_sold_poster_rejects_the_whole_file() -> None:
    row = _row()  # แค่แก้เกรด — ไม่ใช่ WITHDRAW เลย
    with pytest.raises(PrecheckError, match="status = sold") as exc:
        assert_no_row_targets_a_sold_poster(
            [row], {PID: _state(status=PosterStatus.sold)}
        )
    assert "A-D11" in str(exc.value)


def test_withdraw_on_a_sold_poster_is_also_rejected() -> None:
    row = _row(
        values={"published_at": "WITHDRAW"}, reasons={"published_at": WHY_WITHDRAW}
    )
    with pytest.raises(PrecheckError, match="A-D11"):
        assert_no_row_targets_a_sold_poster(
            [row], {PID: _state(status=PosterStatus.sold)}
        )


def test_a_row_touching_an_available_poster_passes_the_sold_gate() -> None:
    assert (
        assert_no_row_targets_a_sold_poster(
            [_row()], {PID: _state(status=PosterStatus.available)}
        )
        is None
    )


def test_a_blank_row_never_trips_the_sold_gate_even_on_a_sold_poster() -> None:
    """แถวว่างไม่มีอะไรจะเขียนอยู่แล้ว — ด่านไม่ควรพังทั้งไฟล์เพราะแถวที่ไม่ได้ทำอะไร"""
    blank = _row(values={}, reasons={})
    assert (
        assert_no_row_targets_a_sold_poster(
            [blank], {PID: _state(status=PosterStatus.sold)}
        )
        is None
    )


def test_a_missing_poster_never_trips_the_sold_gate() -> None:
    assert assert_no_row_targets_a_sold_poster([_row()], {}) is None


def test_one_sold_row_blocks_a_file_that_also_has_a_valid_row() -> None:
    good = _row()
    bad = _row(poster_uuid=PID2, lineno=3)
    with pytest.raises(PrecheckError, match="A-D11"):
        assert_no_row_targets_a_sold_poster(
            [good, bad],
            {
                PID: _state(status=PosterStatus.available),
                PID2: _state(status=PosterStatus.sold),
            },
        )


# --------------------------------------------------------------------------
# มุตทีชัน 6 — ด่านก่อนเซ็น (ADR-0027 D3) — ตั้งชื่อ blocker เป็นตัว ๆ (บทเรียน INF-28)
# --------------------------------------------------------------------------


def _sign_row(**over: object) -> CorrectionRow:
    base = {
        "values": {"verified_at": "SIGN"},
        "reasons": {"verified_at": WHY_SIGN},
    }
    base.update(over)
    return _row(**base)


def test_a_fully_ready_poster_signs_cleanly() -> None:
    assert (
        assert_signable(
            [_sign_row()],
            {PID: _state()},
            {PID: 1},
            signed_at=REVIEWED_AT,
        )
        is None
    )


def test_signing_without_a_grade_is_blocked_by_name() -> None:
    """🔴 บทเรียน INF-28 — assert ชื่อ blocker เป็นตัว ๆ ไม่ใช่แค่ `!= ()`"""
    with pytest.raises(PrecheckError) as exc:
        assert_signable(
            [_sign_row()],
            {PID: _state(condition_grade=None)},
            {PID: 1},
            signed_at=REVIEWED_AT,
        )
    assert PublishBlocker.NO_CONDITION_GRADE.value in str(exc.value)


def test_signing_with_is_unique_false_is_blocked_by_name() -> None:
    with pytest.raises(PrecheckError) as exc:
        assert_signable(
            [_sign_row()],
            {PID: _state(is_unique=False)},
            {PID: 1},
            signed_at=REVIEWED_AT,
        )
    assert PublishBlocker.NOT_UNIQUE.value in str(exc.value)


def test_signing_with_an_unknown_count_is_blocked_by_name() -> None:
    with pytest.raises(PrecheckError) as exc:
        assert_signable([_sign_row()], {PID: _state()}, {}, signed_at=REVIEWED_AT)
    assert PublishBlocker.UNKNOWN_COUNT.value in str(exc.value)


def test_signing_with_a_zero_count_is_blocked_by_name() -> None:
    with pytest.raises(PrecheckError) as exc:
        assert_signable([_sign_row()], {PID: _state()}, {PID: 0}, signed_at=REVIEWED_AT)
    assert PublishBlocker.COUNT_IS_ZERO.value in str(exc.value)


def test_signing_with_multiple_count_on_non_mint_is_blocked_by_name() -> None:
    with pytest.raises(PrecheckError) as exc:
        assert_signable(
            [_sign_row()],
            {PID: _state(condition_grade=PosterCondition.near_mint)},
            {PID: 3},
            signed_at=REVIEWED_AT,
        )
    assert PublishBlocker.COUNT_MULTIPLE_ON_NON_MINT.value in str(exc.value)


def test_multiple_count_is_allowed_on_mint() -> None:
    """positive control — ประตูของ ADR-0019 D1 ยังเปิดอยู่จริงสำหรับ mint"""
    assert (
        assert_signable(
            [_sign_row()],
            {PID: _state(condition_grade=PosterCondition.mint)},
            {PID: 3},
            signed_at=REVIEWED_AT,
        )
        is None
    )


def test_signing_without_a_front_photo_is_blocked_by_name() -> None:
    with pytest.raises(PrecheckError) as exc:
        assert_signable(
            [_sign_row()],
            {PID: _state(front_image_count=0)},
            {PID: 1},
            signed_at=REVIEWED_AT,
        )
    assert PublishBlocker.NO_FRONT_IMAGE.value in str(exc.value)


def test_signing_with_unknown_is_unique_is_blocked_by_name() -> None:
    """🔴 G3 (code-critic รอบ 1 ของ INF-29) — closed-world เดิมขาดตัวนี้ (6/8 ตัว) ·
    `is_unique = None` ไม่มีทางเกิดจริงใน DB (NOT NULL) แต่ readiness ประกอบจาก
    `row.values.get(...) หรือ state.values.get(...)` ซึ่งเทสสังเคราะห์ state ตรง ๆ
    ได้ เพื่อพิสูจน์ว่า UNKNOWN_IS_UNIQUE (fail-closed ของ ADR-0027 D5) มีชื่อบล็อกเกอร์
    ต่อเข้าด่านนี้จริง ไม่ใช่แค่ทฤษฎีที่ publish_blockers() มี"""
    with pytest.raises(PrecheckError) as exc:
        assert_signable(
            [_sign_row()],
            {PID: _state(is_unique=None)},
            {PID: 1},
            signed_at=REVIEWED_AT,
        )
    assert PublishBlocker.UNKNOWN_IS_UNIQUE.value in str(exc.value)


def test_signing_with_unknown_front_image_count_is_blocked_by_name() -> None:
    """🔴 G3 — คู่แฝดของด้านบนสำหรับ UNKNOWN_FRONT_IMAGE_COUNT"""
    with pytest.raises(PrecheckError) as exc:
        assert_signable(
            [_sign_row()],
            {PID: _state(front_image_count=None)},
            {PID: 1},
            signed_at=REVIEWED_AT,
        )
    assert PublishBlocker.UNKNOWN_FRONT_IMAGE_COUNT.value in str(exc.value)


def test_not_verified_is_never_reported_by_the_pre_sign_gate() -> None:
    """NOT_VERIFIED ถูกตัดออกเสมอ — เป็นสิ่งที่แถวนี้กำลังจะแก้พอดี ไม่ใช่บล็อกตัวเอง"""
    with pytest.raises(PrecheckError) as exc:
        assert_signable(
            [_sign_row()],
            {PID: _state(condition_grade=None)},
            {PID: 1},
            signed_at=REVIEWED_AT,
        )
    assert PublishBlocker.NOT_VERIFIED.value not in str(exc.value)


def test_the_readiness_used_for_signing_reflects_the_grade_written_this_round() -> None:
    """กันติดลูป — เกรดที่เพิ่งกรอกในแถวเดียวกันต้องนับด้วย ไม่ใช่แค่ค่าที่มีอยู่ใน DB"""
    row = _sign_row(
        values={"condition_grade": PosterCondition.fine, "verified_at": "SIGN"},
        reasons={"condition_grade": WHY_GRADE, "verified_at": WHY_SIGN},
    )
    assert (
        assert_signable(
            [row],
            {PID: _state(condition_grade=None)},
            {PID: 1},
            signed_at=REVIEWED_AT,
        )
        is None
    )


def test_a_row_that_does_not_sign_is_never_checked_by_the_pre_sign_gate() -> None:
    assert (
        assert_signable(
            [_row()], {PID: _state(condition_grade=None)}, {}, signed_at=REVIEWED_AT
        )
        is None
    )


def test_counts_none_is_safe_when_nothing_signs() -> None:
    assert (
        assert_signable([_row()], {PID: _state()}, None, signed_at=REVIEWED_AT) is None
    )


def test_sign_blocker_hints_cover_every_blocker_except_not_verified() -> None:
    """🔴 G3 — closed-world: `_SIGN_BLOCKER_HINTS` ต้องครอบทุกตัวใน `PublishBlocker`
    ยกเว้น `NOT_VERIFIED` (ที่ `assert_signable()` ตัดออกเองเสมอ) ไม่งั้น blocker
    ตัวที่สิบวันหน้าจะตกไปที่ fallback (`blocker.value` ดิบ) เงียบ ๆ โดยไม่มีอะไรฟ้อง"""
    assert set(mod._SIGN_BLOCKER_HINTS) == set(PublishBlocker) - {
        PublishBlocker.NOT_VERIFIED
    }


# --------------------------------------------------------------------------
# G1 (code-critic รอบ 1 ของ INF-29) — ด่าน --reviewed-at บังคับเมื่อมีแถวสั่ง SIGN
# ไม่ว่าโหมดไหน · มุตทีชันใหม่ #7 ของ INF-29 — ถอดด่านนี้ทิ้งต้องทำให้เทสนี้แดง
# --------------------------------------------------------------------------


def test_reviewed_at_missing_blocks_a_sign_row() -> None:
    with pytest.raises(PrecheckError, match="--reviewed-at"):
        mod.assert_reviewed_at_present_when_signing([_sign_row()], None)


def test_reviewed_at_missing_is_fine_when_nothing_signs() -> None:
    """แถวที่ไม่ได้สั่ง SIGN ไม่เกี่ยวกับด่านนี้เลย — ทรงเดียวกับ
    test_a_row_that_does_not_sign_is_never_checked_by_the_pre_sign_gate"""
    assert mod.assert_reviewed_at_present_when_signing([_row()], None) is None


def test_reviewed_at_present_is_always_fine_even_with_a_sign_row() -> None:
    assert (
        mod.assert_reviewed_at_present_when_signing([_sign_row()], REVIEWED_AT) is None
    )


# --------------------------------------------------------------------------
# ด่านก่อนเขียน — ใบงานของเส้นอื่น · schema ปลายทาง (เหมือนเดิม)
# --------------------------------------------------------------------------


def test_the_sheets_of_lane_three_and_four_are_refused_by_name() -> None:
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
    with pytest.raises(PrecheckError, match="reason") as exc:
        assert_schema_ready([], False)
    assert "alembic upgrade head" in str(exc.value)


# --------------------------------------------------------------------------
# `run()` — closed-world ที่ runtime + ลำดับด่าน + มุตทีชัน 1/2/3/4/5 ที่ runtime
# --------------------------------------------------------------------------


class _PosterSpy:
    def __init__(self) -> None:
        object.__setattr__(self, "writes", {})

    def __setattr__(self, name: str, value: object) -> None:
        self.writes[name] = value
        object.__setattr__(self, name, value)


class _FakeSession:
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
    counts: dict[uuid.UUID, int] | None = None,
    readback_reflects_writes: bool = True,
):
    import app.core.database as db_mod

    path = _write_sheet(tmp_path, sheet_rows)
    ids = [uuid.UUID(r["poster_uuid"]) for r in sheet_rows]
    posters = {pid: _PosterSpy() for pid in ids}
    session = _FakeSession(posters)
    current = state if state is not None else {pid: _state() for pid in ids}

    async def fake_load_state(_session, _ids):
        out: dict = {}
        for pid, base in current.items():
            values = dict(base.values)
            spy = posters.get(pid)
            if spy is not None and readback_reflects_writes:
                values.update({k: v for k, v in spy.writes.items() if k in values})
            out[pid] = mod.PosterState(
                values=values,
                status=base.status,
                front_image_count=base.front_image_count,
            )
        return out

    default_counts = counts if counts is not None else {pid: 1 for pid in ids}

    def fake_load_counts(_path):
        return default_counts

    monkeypatch.setattr(db_mod, "async_session_maker", lambda: session)
    monkeypatch.setattr(mod, "_load_state", fake_load_state)
    monkeypatch.setattr(mod, "load_count_actual_by_poster", fake_load_counts)
    return path, session, posters


async def _run_applier(
    monkeypatch,
    tmp_path,
    sheet_rows,
    *,
    commit: bool = True,
    state: dict | None = None,
    fields: list[str] | None = None,
    counts: dict[uuid.UUID, int] | None = None,
    readback_reflects_writes: bool = True,
):
    path, session, posters = _install_fakes(
        monkeypatch,
        tmp_path,
        sheet_rows,
        state=state,
        counts=counts,
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
    assert written == {"condition_grade", "is_unique"}
    assert posters[PID3].writes == {}


async def test_run_never_sets_published_at_to_anything_but_none(monkeypatch, tmp_path):
    """🔴 มุตทีชัน 1 ที่ runtime — spy จับ **ทุกครั้ง** ที่มีการเซ็ต `published_at`
    ผ่าน `setattr` แล้วยืนยันว่าเป็น `None` เสมอ ไม่ว่าจะมาจาก WITHDRAW เองหรือ cascade
    """
    published = REVIEWED_AT - timedelta(days=10)
    verified = REVIEWED_AT - timedelta(days=10)
    rc, _session, posters = await _run_applier(
        monkeypatch,
        tmp_path,
        [
            _raw(published_at="WITHDRAW", published_at_reason=WHY_WITHDRAW),  # explicit
            _raw(
                poster_uuid=str(PID2),
                condition_grade="fine",
                condition_grade_reason=WHY_GRADE,
            ),  # cascade
        ],
        state={
            PID: _state(published_at=published),
            PID2: _state(verified_at=verified, published_at=published),
        },
    )
    assert rc == 0
    for spy in posters.values():
        if "published_at" in spy.writes:
            assert spy.writes["published_at"] is None


async def test_run_records_the_real_value_before_and_the_reason(monkeypatch, tmp_path):
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
    by_poster = {e.poster_id: e for e in session.added}
    assert by_poster[PID].value_before == "near_mint"
    assert by_poster[PID].value_after == "fine"
    assert by_poster[PID2].value_before == "False"
    assert by_poster[PID2].value_after == "True"
    assert all(e.reviewed_by == "chanothai" for e in session.added)
    assert all(e.reviewed_at == REVIEWED_AT for e in session.added)
    assert {e.source for e in session.added} == {"correction-entry.csv"}


async def test_signing_writes_verified_at_and_records_a_null_before(
    monkeypatch, tmp_path
):
    rc, session, posters = await _run_applier(
        monkeypatch,
        tmp_path,
        [_raw(verified_at="SIGN", verified_at_reason=WHY_SIGN)],
        state={PID: _state(verified_at=None)},
    )
    assert rc == 0
    assert posters[PID].writes == {"verified_at": REVIEWED_AT}
    (entry,) = session.added
    assert entry.value_before is None
    assert entry.value_after == render_value(REVIEWED_AT)
    assert entry.reason == WHY_SIGN


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


async def test_the_sold_gate_runs_before_the_session_is_touched(monkeypatch, tmp_path):
    """🔴 มุตทีชัน 3 ที่ runtime — ปฏิเสธก่อนแตะ session แม้เป็น dry-run"""
    with pytest.raises(PrecheckError, match="A-D11"):
        await _run_applier(
            monkeypatch,
            tmp_path,
            [_raw(condition_grade="fine", condition_grade_reason=WHY_GRADE)],
            commit=False,
            state={PID: _state(status=PosterStatus.sold)},
        )


async def test_the_sold_gate_blocks_commit_too(monkeypatch, tmp_path):
    path, session, posters = _install_fakes(
        monkeypatch,
        tmp_path,
        [_raw(condition_grade="fine", condition_grade_reason=WHY_GRADE)],
        state={PID: _state(status=PosterStatus.sold)},
    )
    args = argparse.Namespace(
        file=path,
        commit=True,
        field=[],
        reviewed_by="chanothai",
        reviewed_at=REVIEWED_AT,
    )
    with pytest.raises(PrecheckError, match="A-D11"):
        await mod.run(args, "fake/db")
    assert session.added == []
    assert session.committed is False
    assert all(spy.writes == {} for spy in posters.values())


async def test_the_pre_sign_gate_blocks_the_whole_file_before_any_write(
    monkeypatch, tmp_path
):
    path, session, posters = _install_fakes(
        monkeypatch,
        tmp_path,
        [
            _raw(condition_grade="fine", condition_grade_reason=WHY_GRADE),
            _raw(
                poster_uuid=str(PID2),
                verified_at="SIGN",
                verified_at_reason=WHY_SIGN,
            ),
        ],
        state={PID: _state(), PID2: _state(condition_grade=None)},
        counts={PID2: 1},
    )
    args = argparse.Namespace(
        file=path,
        commit=True,
        field=[],
        reviewed_by="chanothai",
        reviewed_at=REVIEWED_AT,
    )
    with pytest.raises(PrecheckError, match="ADR-0027 D3"):
        await mod.run(args, "fake/db")
    assert session.added == []
    assert all(spy.writes == {} for spy in posters.values())


async def test_signing_never_reads_the_manual_entry_csv_when_no_row_signs(
    monkeypatch, tmp_path
):
    """§AC-4 — อ่านเฉพาะเมื่อมีแถวที่สั่ง SIGN เท่านั้น"""
    calls: list[Path] = []

    def fail_if_called(path):
        calls.append(path)
        raise AssertionError("ไม่ควรถูกเรียกเลยเพราะไม่มีแถวไหนสั่ง SIGN")

    rc, _session, _posters = await _run_applier(
        monkeypatch,
        tmp_path,
        [_raw(condition_grade="fine", condition_grade_reason=WHY_GRADE)],
    )
    assert rc == 0
    # ติดตั้ง fakes ใหม่รอบสอง แต่แทน load_count_actual_by_poster ด้วยตัวที่ raise
    # ทับตัวที่ _install_fakes ตั้งไว้ — ยืนยันว่าไม่มีแถวไหนของรอบนี้เรียกมันเลย
    path, session, posters = _install_fakes(
        monkeypatch,
        tmp_path,
        [_raw(condition_grade="fine", condition_grade_reason=WHY_GRADE)],
    )
    monkeypatch.setattr(mod, "load_count_actual_by_poster", fail_if_called)
    args = argparse.Namespace(
        file=path,
        commit=True,
        field=[],
        reviewed_by="chanothai",
        reviewed_at=REVIEWED_AT,
    )
    rc = await mod.run(args, "fake/db")
    assert rc == 0
    assert calls == []


async def test_a_sheet_missing_one_reason_never_reaches_the_session(
    monkeypatch, tmp_path
):
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


async def test_a_write_that_never_landed_makes_run_return_one(
    monkeypatch, tmp_path, capsys
):
    rc, session, _posters = await _run_applier(
        monkeypatch,
        tmp_path,
        [_raw(condition_grade="fine", condition_grade_reason=WHY_GRADE)],
        readback_reflects_writes=False,
    )
    assert rc == 1
    assert session.committed is True
    out = capsys.readouterr().out
    assert "การทับไม่ลงตามแผน" in out


async def test_a_write_that_landed_returns_zero(monkeypatch, tmp_path, capsys):
    rc, session, _posters = await _run_applier(
        monkeypatch,
        tmp_path,
        [_raw(condition_grade="fine", condition_grade_reason=WHY_GRADE)],
    )
    assert rc == 0
    assert session.committed is True
    out = capsys.readouterr().out
    assert "ตรงทุกค่า" in out


# --------------------------------------------------------------------------
# CLI — main() ผ่าน sys.argv จริง (เฉพาะจุดที่เปลี่ยนจาก 2 → 4 ฟิลด์)
# --------------------------------------------------------------------------

FAKE_DEV_DATABASE_URL = "postgresql+asyncpg://u:p@localhost:5432/poster_nung_dev"
REVIEWED_AT_CLI = REVIEWED_AT.isoformat()


def _install_cli(
    monkeypatch,
    path: Path,
    *argv: str,
    database_url: str = FAKE_DEV_DATABASE_URL,
) -> None:
    monkeypatch.setattr(mod, "_load_env", lambda _target: None)
    monkeypatch.setenv("DATABASE_URL", database_url)
    monkeypatch.setattr(
        sys, "argv", ["correction_entry.py", "--file", str(path), *argv]
    )


def test_main_without_commit_writes_nothing_even_with_the_reviewer_flags_present(
    monkeypatch, tmp_path, capsys
) -> None:
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
    out = capsys.readouterr().out
    assert "DRY-RUN" in out


def test_main_with_commit_but_without_reviewed_by_never_opens_a_session(
    monkeypatch, tmp_path, capsys
) -> None:
    path, session, posters = _install_fakes(
        monkeypatch,
        tmp_path,
        [_raw(condition_grade="fine", condition_grade_reason=WHY_GRADE)],
    )
    _install_cli(monkeypatch, path, "--commit", "--reviewed-at", REVIEWED_AT_CLI)

    with pytest.raises(SystemExit) as exc:
        mod.main()
    assert exc.value.code == 2
    assert "--commit ต้องระบุ --reviewed-by ด้วย" in capsys.readouterr().err
    assert session.added == []


def test_main_with_every_required_flag_goes_all_the_way_to_the_write(
    monkeypatch, tmp_path, capsys
) -> None:
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
    out = capsys.readouterr().out
    assert "DRY-RUN" not in out


# --------------------------------------------------------------------------
# G1 (code-critic รอบ 1 ของ INF-29) — dry-run ต้องเดิน parsing path ของ main() เอง
# ไม่ใช่แค่ได้ datetime จาก fixture ที่ยัดมาให้ — root cause ของ G1 คือ
# `_args()` ของ test_correction_entry_run_harness.py ยัด datetime ตรง ๆ ให้
# reviewed_at เสมอทั้งสองโหมด ไม่มีเทสไหนเดินผ่าน parsing path ของ main() จริงเลย
# --------------------------------------------------------------------------


def test_dry_run_parses_reviewed_at_through_mains_own_argv_path(
    monkeypatch, tmp_path, capsys
) -> None:
    """เรียก `main()` ตัวจริงด้วย `--reviewed-at` เป็น **string** จาก argv ในโหมด
    dry-run พร้อมแถวสั่ง `SIGN` แล้วยืนยันว่า `plan_writes()`/`assert_signable()`
    เห็น `datetime` ไม่ใช่ `str` ดิบ (อาการเดิมของ G1: `signed_at` เป็น str ทำให้
    `render_value()` เทียบผิดจน SIGN ของใบที่ยังไม่เคยเซ็นรายงานเป็น `SKIP_SAME`)
    """
    path, session, posters = _install_fakes(
        monkeypatch,
        tmp_path,
        [_raw(verified_at="SIGN", verified_at_reason=WHY_SIGN)],
    )

    captured: dict[str, object] = {}
    real_plan_writes = mod.plan_writes
    real_assert_signable = mod.assert_signable

    def spy_plan_writes(rows, current, fields=WRITABLE_FIELDS, *, signed_at):
        captured["plan_writes_signed_at"] = signed_at
        return real_plan_writes(rows, current, fields, signed_at=signed_at)

    def spy_assert_signable(rows, current, counts, *, signed_at):
        captured["assert_signable_signed_at"] = signed_at
        return real_assert_signable(rows, current, counts, signed_at=signed_at)

    monkeypatch.setattr(mod, "plan_writes", spy_plan_writes)
    monkeypatch.setattr(mod, "assert_signable", spy_assert_signable)
    _install_cli(monkeypatch, path, "--reviewed-at", REVIEWED_AT_CLI)

    assert mod.main() == 0

    assert isinstance(captured["assert_signable_signed_at"], datetime)
    assert captured["assert_signable_signed_at"] == REVIEWED_AT
    assert isinstance(captured["plan_writes_signed_at"], datetime)
    assert captured["plan_writes_signed_at"] == REVIEWED_AT

    # dry-run ยังไม่เขียนอะไรลง DB จริง
    assert session.added == []
    assert session.committed is False
    out = capsys.readouterr().out
    assert "DRY-RUN" in out


def test_dry_run_rejects_a_sign_row_with_no_reviewed_at_end_to_end(
    monkeypatch, tmp_path, capsys
) -> None:
    """🔴 มุตทีชันใหม่ #7 ของ INF-29 ที่ระดับ `main()` — ถอดด่าน
    `assert_reviewed_at_present_when_signing()` ทิ้งต้องทำให้เทสนี้แดง (rc กลับมา
    เป็น 0 แทนที่จะเป็น 1) เดิม (ก่อนแก้ G1) เคสนี้ไม่มีทาง error เลยในโหมด dry-run
    เพราะ parsing/validation ของ --reviewed-at อยู่แค่ใน `if args.commit:`"""
    path, session, posters = _install_fakes(
        monkeypatch,
        tmp_path,
        [_raw(verified_at="SIGN", verified_at_reason=WHY_SIGN)],
    )
    _install_cli(monkeypatch, path)  # ไม่ใส่ --reviewed-at เลย

    rc = mod.main()

    assert rc == 1
    assert session.added == []
    assert session.committed is False
    err = capsys.readouterr().err
    assert "--reviewed-at" in err


# --------------------------------------------------------------------------
# G5 — จุดต่อของ `assert_target()` ใน `main()`
# --------------------------------------------------------------------------
#
# 🔴 `assert_target()` มีเทสของ *ตัวฟังก์ชัน* อยู่แล้วที่ `test_seed_lane_shared_rules.py`
# แต่ **สายที่ต่อมันเข้า `main()` ของเส้นนี้ไม่เคยถูกแตะ** — เทส CLI ทุกตัวข้างบนใช้
# `FAKE_DEV_DATABASE_URL` ซึ่งผ่านด่านเสมอ จึงครอบแต่ทางบวก
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
    assert session.added == []
    assert session.committed is False
    assert all(spy.writes == {} for spy in posters.values())
    assert "ปลายทาง" not in captured.out
    assert "ทับค่าเดิมแล้ว" not in captured.out


def test_main_checks_the_database_url_of_this_very_run(
    monkeypatch, tmp_path, capsys
) -> None:
    """🔴 ตัวฆ่า mutation ที่ *คงการเรียกไว้* แต่ส่งค่าคงที่ที่ผ่านด่านเสมอเข้าไปแทน"""
    seen: list[tuple[str, str]] = []
    real_assert_target = mod.assert_target

    def spy(database_url: str, target: str) -> str:
        seen.append((database_url, target))
        return real_assert_target(database_url, target)

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

    🔴 **ห้าม assert ข้อความ error ของเคสนี้** — ต่างกันตามว่าเครื่องที่รันเทสมี
    `.env.sit` หรือไม่ · `rc == 1` กับ `seen` เหมือนกันทั้งสองสภาพ
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
    assert session.added == []
    assert session.committed is False
    assert all(spy_poster.writes == {} for spy_poster in posters.values())
    assert "ปลายทาง" not in capsys.readouterr().out


def test_a_dev_url_that_passes_the_guard_still_reaches_the_write(
    monkeypatch, tmp_path, capsys
) -> None:
    """🔴 positive control ของทั้ง §G5"""
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
    """ทรงเดียวกับ `_install_cli` แต่ **ไม่ตั้ง `DATABASE_URL` ไว้ล่วงหน้า** — ทางเดียว
    ที่ค่านั้นจะมาถึง `main()` คือผ่าน `_load_env()`"""
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
    """🔴 ตัวฆ่า mutation ที่ **ถอด `_load_env(args.target)` ออกจาก `main()`**"""
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
    assert f"ปลายทาง : {G6_DEV_TARGET_LABEL}  [--target dev]" in captured.out
    assert session.committed is True
    assert posters[PID].writes == {"condition_grade": PosterCondition.fine}


def test_main_loads_the_env_of_the_target_the_human_typed_not_a_constant(
    monkeypatch, tmp_path, capsys
) -> None:
    """🔴 ตัวฆ่า mutation ที่ hardcode **อาร์กิวเมนต์** เป็น `_load_env("dev")`"""
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
    assert seen == [(G6_ENV_FILE_URLS["sit"], "sit")]
    assert session.added == []
    assert session.committed is False
    assert all(spy_poster.writes == {} for spy_poster in posters.values())
    capsys.readouterr()


def test_main_names_the_missing_database_url_instead_of_blaming_the_target(
    monkeypatch, tmp_path, capsys
) -> None:
    """🔴 ตัวฆ่า mutation ที่ **ถอด guard `if not database_url` ออก**"""
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


def test_the_field_flag_accepts_verified_at_and_published_at_on_the_cli(
    monkeypatch, tmp_path
) -> None:
    """`choices=WRITABLE_FIELDS` ต้องยอมรับสองฟิลด์ใหม่ — ถ้า argparse ปฏิเสธจะได้
    `SystemExit(2)` ก่อนโค้ดเดินถึงส่วนอื่นเลย ไม่ต้องพึ่ง DATABASE_URL ของเครื่องจริง
    """
    monkeypatch.setattr(mod, "_load_env", lambda _target: None)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "correction_entry.py",
            "--file",
            str(tmp_path / "ยังไม่มีไฟล์.csv"),
            "--field",
            "verified_at",
            "--field",
            "published_at",
        ],
    )
    # ไม่ raise SystemExit(2) แปลว่า choices ยอมรับทั้งสองค่า — ล้มทีหลังด้วยเหตุผล
    # อื่น (ไม่มี DATABASE_URL) ซึ่งไม่ใช่สิ่งที่เทสนี้สนใจ
    assert mod.main() == 1
