"""Unit tests ของ `scripts/seed/manual_entry.py` + `make_manual_sheet.py`
— ล็อกกฎ D1–D8 ของ ADR-0015

ไม่ต่อ DB จริง — ทุก test ทำกับฟังก์ชัน pure (`parse_manual_rows`, `plan_writes`,
`build_sheet_rows`, `_report_counts`) ซึ่งรับสถานะเข้ามาแทนการ query เอง ตาม
ship-backend-change §3 (เลี่ยง fixture ที่ไม่จำเป็น)

`field_specs()` import `app.models.enums` ข้างในตัวเอง — ใต้ pytest env ครบอยู่แล้ว
จึงเรียกได้ตรง ๆ (ดู docstring ของฟังก์ชันนั้นว่าทำไมไม่ import ไว้บนหัวไฟล์)
"""

from __future__ import annotations

import ast
import inspect
import uuid
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from app.models.enums import (
    PosterCondition,
    PosterType,
    RestorationStatus,
    SizeFormat,
)
from scripts.seed import make_manual_sheet as sheet_mod
from scripts.seed.make_manual_sheet import build_sheet_rows
from scripts.seed.manual_entry import (
    STATE_FIELDS,
    OVERWRITE_ELIGIBLE,
    ALLOWED_FIELDS,
    DERIVED_FIELDS,
    MANUAL_SHEET_COLUMNS,
    PUBLISH_FIELD,
    REQUIRED_COLUMNS,
    YEAR_MAX,
    YEAR_MIN,
    ManualRow,
    PosterState,
    PrecheckError,
    Publish,
    PublishAction,
    _report_counts,
    field_specs,
    parse_manual_rows,
    plan_writes,
    planned_field_counts,
    render_value,
    verify_overwrites,
    audit_value_before,
)

PID = uuid.UUID("11111111-1111-1111-1111-111111111111")
PID2 = uuid.UUID("22222222-2222-2222-2222-222222222222")
NOW = datetime(2026, 8, 5, 13, 0, tzinfo=UTC)


def _raw(**over: str) -> dict[str, str]:
    row = {
        "poster_uuid": str(PID),
        "title": "Some Poster",
        "image_url": "https://example.invalid/a.jpg",
        "condition_grade": "very_good",
        "year": "1999",
        "poster_type": "THEATRICAL",
        "restoration_status": "NONE",
        "tmdb_id": "603",
        # 📏 default เป็นใบที่ **วัดแล้ว** — เคสปกติหลัง BL-93 · 27×41 เลือกมาเพราะ
        # เป็นแถวที่ D16 กำกับไว้ว่าต้องเก็บตัวเลขไว้ด้วย (สัญญาณงานพิมพ์ยุคเก่า)
        "width_in": "27",
        "height_in": "41",
        # ว่างเสมอตาม default ของ make_manual_sheet.py — เคสที่ยังไม่มีค่า ("ยังไม่นับ")
        # เป็นเคสปกติของวันนี้ (117/117 ยังว่าง) เทสที่ต้องการ count_actual ค่าอื่น
        # override เอง
        "count_actual": "",
        "publish": "",
        "note": "",
    }
    row.update(over)
    return row


def _row(**over: object) -> ManualRow:
    base: dict[str, object] = {
        "poster_uuid": PID,
        "values": {"condition_grade": PosterCondition.very_good},
        "publish": Publish.PENDING,
        "count_actual": None,
        "lineno": 2,
    }
    base.update(over)
    return ManualRow(**base)  # type: ignore[arg-type]


def _state(**over: object) -> PosterState:
    base: dict[str, object] = {
        "values": {name: None for name in (*ALLOWED_FIELDS, *DERIVED_FIELDS)},
        "published": False,
        "image_count": 1,
        # ‹2026-08-16 · ADR-0026 D8› ค่าปริยายของเทสเดิมคือ "มีรูปหน้าใบ 1 รูป"
        # ซึ่งตรงกับเจตนาเดิมของ `image_count: 1` (ตอนนั้นยังไม่มีชนิดของรูป)
        # เทสที่จงใจทดสอบ BR-06 ส่งค่าเองเสมอ
        "front_image_count": 1,
    }
    base.update(over)
    return PosterState(**base)  # type: ignore[arg-type]


# --- D2: allowlist ---


def test_allowlist_is_exactly_the_seven_human_only_fields() -> None:
    """ล็อก allowlist ไว้ตรง ๆ — การเพิ่มฟิลด์คือการแก้มติ ADR-0015 D2 ต้องผ่าน ADR
    ก่อน ไม่ใช่แก้ค่าคงที่เงียบ ๆ แล้ว test เดิมยังเขียว

    ‹2026-08-08› 5 → 7 ที่ **ADR-0015 Amendment D9** (`width_in`/`height_in`) ·
    ผ่านเกณฑ์เดิมของ D2 ทุกข้อ: ว่างทั้งตาราง · คนตอบได้จากการดูใบ ·
    **เครื่องเดาแทนไม่ได้ตลอดกาล** (ADR-0009 D16)
    """
    assert ALLOWED_FIELDS == (
        "condition_grade",
        "year",
        "poster_type",
        "restoration_status",
        "tmdb_id",
        "width_in",
        "height_in",
    )
    # 🔴 `size_format` เป็น derived ห้ามอยู่ใน allowlist — ถ้ามันหลุดเข้ามา แปลว่า
    # มีใครทำให้มัน "กรอกเองได้" ซึ่งลบเหตุผลทั้งหมดของ D16 ทิ้ง
    for name in DERIVED_FIELDS:
        assert name not in ALLOWED_FIELDS


def test_every_writable_field_has_a_spec_and_vice_versa() -> None:
    """ทุกฟิลด์ที่สคริปต์เขียนได้ต้องมี spec และทุก spec ต้องมีฟิลด์รองรับ

    เดิมเทียบกับ `ALLOWED_FIELDS` ตรง ๆ · หลัง ADR-0010 D8 มี `title` ที่เขียนได้
    เฉพาะโหมด overwrite จึงไม่อยู่ใน allowlist — `STATE_FIELDS` คือชุดเต็มที่ถูกต้อง
    **ไม่ได้ผ่อนความเข้ม**: ยังห้ามมี spec ที่ไม่มีฟิลด์ และห้ามมีฟิลด์ที่ไม่มี spec
    """
    assert set(field_specs()) == set(STATE_FIELDS)
    # 🔴 derived ต้อง **ไม่มี** spec — spec คือตัวแปลงข้อความจากใบงาน การมี spec
    # แปลว่ามีคนคาดหวังให้กรอกเอง ซึ่ง D16 ห้าม (แหล่งความจริงที่สอง)
    for name in DERIVED_FIELDS:
        assert name not in field_specs()
        assert name not in STATE_FIELDS


def test_overwrite_eligible_is_exactly_two_fields() -> None:
    """🔴 ADR-0010 D8 อนุญาตแค่ `title` กับ `year` — การเพิ่มต้องแก้ ADR ก่อน

    เทสนี้คือด่านที่ทำให้ข้อห้ามนั้นเป็นกฎจริง ไม่ใช่ข้อความในเอกสาร ·
    โดยเฉพาะ `condition_grade` (BR-05) และ `published_at` ที่ D8 ห้ามไว้ตลอดกาล
    """
    assert set(OVERWRITE_ELIGIBLE) == {"title", "year"}
    assert "condition_grade" not in OVERWRITE_ELIGIBLE
    assert PUBLISH_FIELD not in OVERWRITE_ELIGIBLE
    # ‹เพิ่ม 2026-08-09 · ADR-0010 **A-D1**› `is_unique` จัดชั้นเดียวกับ
    # `condition_grade` — แก้ได้เฉพาะผ่านเส้นที่ 5 (`correction_entry.py`) ที่บังคับ
    # เหตุผลต่อค่า **ไม่ใช่** ผ่าน flag ตัวเดียวบน CLI ซึ่งบังคับหลักฐานว่ามีคนไปดู
    # ของจริงมาแล้วไม่ได้ (A-D3) · A-D4 ข้อ 3 ระบุว่ารายการนี้ไม่ขยายเลยสักฟิลด์
    assert "is_unique" not in OVERWRITE_ELIGIBLE


def test_published_at_is_not_in_the_allowlist() -> None:
    """`published_at` ต้องผ่านคอลัมน์ `publish` ที่มีด่านของตัวเอง (D4) เท่านั้น —
    ถ้ามันหลุดเข้า ALLOWED_FIELDS จะกลายเป็นช่องกรอกธรรมดาที่ข้ามด่านทั้งสองไปได้"""
    assert PUBLISH_FIELD not in ALLOWED_FIELDS


def test_measurement_columns_now_reach_the_database() -> None:
    """📏 ADR-0009 **D16** + ADR-0015 **D9** — สองช่องนี้เขียนลง DB ได้แล้ว

    ‹กลับด้านจากเทสเดิม 2026-08-08› ตอนเช้าวันเดียวกันเทสตัวนี้ยืนยัน**ตรงกันข้าม**
    คือ "มีช่องให้กรอกแต่ยังไปไม่ถึง DB" ซึ่งถูกต้องในตอนนั้นเพราะยังไม่มีคอลัมน์
    ปลายทาง · เก็บบันทึกไว้เพราะเวลาย้อนอ่าน การเปลี่ยนคำตอบของเทสโดยไม่บอกว่า
    *อะไรเปลี่ยน* แยกไม่ออกจากการอ่อนข้อให้โค้ดที่พัง
    """
    assert "width_in" in MANUAL_SHEET_COLUMNS
    assert "height_in" in MANUAL_SHEET_COLUMNS
    # 🔴 ห้ามมีช่อง size_format ในใบงานเด็ดขาด (D16 · หลักเดียวกับ ADR-0014 AC-3)
    assert "size_format" not in MANUAL_SHEET_COLUMNS
    assert "size" not in MANUAL_SHEET_COLUMNS

    (row,) = parse_manual_rows([_raw()])
    assert row.values["width_in"] == Decimal("27")
    assert row.values["height_in"] == Decimal("41")

    (plan,) = plan_writes([row], {PID: _state()})
    assert plan.field_writes["width_in"] == Decimal("27")
    assert plan.field_writes["height_in"] == Decimal("41")


def test_size_format_is_derived_from_the_measurement_never_typed() -> None:
    """ADR-0009 D16 — คนกรอกตัวเลข เครื่อง map · ไม่มีใครพิมพ์ `size_format` เลย"""
    (row,) = parse_manual_rows([_raw(width_in="27", height_in="41")])
    assert "size_format" not in row.values  # ไม่มีช่องให้กรอก จึงเข้ามาไม่ได้

    (plan,) = plan_writes([row], {PID: _state()})
    assert plan.field_writes["size_format"] is SizeFormat.ONE_SHEET


def test_more_than_two_decimals_is_rejected_not_silently_rounded() -> None:
    """🔴 คอลัมน์เป็น `Numeric(5, 2)` — PostgreSQL **ปัดให้เงียบ ๆ** ไม่ error

    ยืนยันกับ PostgreSQL จริง (2026-08-08): `SELECT 27.126::numeric(5,2)` คืน
    **`27.13`** ไม่มี warning ไม่มี error · (ต่างจากการเกิน *precision* เช่น
    `1234.5::numeric(5,2)` ที่ throw `numeric field overflow` จริง — เคสนั้นถูก
    ด่านช่วง 1–99.99 จับไปก่อนอยู่แล้ว)

    ผลคือถ้าปล่อยผ่าน **ค่าที่เก็บจะไม่ตรงกับที่คนกรอก โดยไม่มีอะไรฟ้อง** และ
    `derive_size_format()` ซึ่งเทียบค่าแบบเป๊ะจะทำงานกับตัวเลขที่คนไม่เคยพิมพ์
    """
    with pytest.raises(PrecheckError) as exc:
        parse_manual_rows([_raw(width_in="27.126")])
    assert "ทศนิยม" in str(exc.value)

    # ≤ 2 ตำแหน่งต้องผ่าน — ไม่งั้นเทสข้างบนผ่านได้ด้วยการปฏิเสธทศนิยมทั้งหมด
    (row,) = parse_manual_rows([_raw(width_in="20.50")])
    assert row.values["width_in"] == Decimal("20.50")


def test_dry_run_report_names_the_derived_field_it_is_about_to_write(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """🔴 dry-run ที่ไม่บอกว่ากำลังจะเขียนอะไร = dry-run ที่ใช้ตรวจไม่ได้

    `size_format` **ไม่มีคอลัมน์ในใบงาน** คนอ่านรายงานจึงไม่มีทางเดาเองได้เลยว่า
    มันจะถูกเขียน — ต่างจากฟิลด์อื่นทุกตัวที่คนพิมพ์เองกับมือ · ถ้ารายงานเงียบ
    เส้นทางนี้จะเขียนคอลัมน์ที่ไม่มีใครเห็นว่าตัวเองสั่ง ซึ่งขัดกับเหตุผลทั้งหมดที่
    ADR-0015 D8 ให้ dry-run เป็น default
    """
    from scripts.seed.manual_entry import _report

    (row,) = parse_manual_rows([_raw()])  # 27×41
    plans = plan_writes([row], {PID: _state()})
    _report(plans, "test", committed=False)

    out = capsys.readouterr().out
    assert "size_format" in out
    # ต้องบอก *ที่มา* ด้วย ไม่ใช่แค่โผล่ชื่อ — คนอ่านต้องรู้ว่าทำไมมันถึงมีค่าทั้งที่
    # ตัวเองไม่ได้กรอก ไม่งั้นจะไปตามหาช่องที่ไม่มีอยู่
    assert "width_in" in out and "D16" in out


def test_size_format_is_not_derived_until_both_sides_are_measured() -> None:
    """วัดด้านเดียว = ยังไม่มีคำตอบ · **ห้ามได้ `OTHER`** (= วัดแล้วไม่เข้าสเกล)"""
    (row,) = parse_manual_rows([_raw(height_in="")])
    (plan,) = plan_writes([row], {PID: _state()})
    assert "height_in" not in plan.field_writes  # D6 — ช่องว่างคือข้าม
    assert "size_format" not in plan.field_writes


def test_measurement_from_a_previous_run_still_derives_this_run() -> None:
    """กรอกกว้างรอบก่อน เติมสูงรอบนี้ → derive ได้ ไม่ต้องกรอกซ้ำทั้งสองช่อง

    ถ้า derive อ่านเฉพาะค่าที่มาในรอบนี้ ใบที่ทำครึ่งทางไว้จะไม่มีวันได้
    `size_format` เลย และไม่มีอะไรฟ้องเพราะทั้งสองช่องก็มีค่าครบใน DB แล้ว
    """
    (row,) = parse_manual_rows([_raw(width_in="")])
    state = _state(values={**_state().values, "width_in": Decimal("27.00")})
    (plan,) = plan_writes([row], {PID: state})
    assert plan.field_writes["size_format"] is SizeFormat.ONE_SHEET


def test_measurement_that_contradicts_a_stored_size_format_rejects_the_file() -> None:
    """🔴 ขนาดที่วัดได้ขัดกับค่าใน DB = ปฏิเสธทั้งไฟล์ ไม่ใช่ข้ามเงียบ ๆ

    D6 ไม่มีโหมดเขียนทับ ทางเลือกจึงเหลือสองทาง: ข้ามเงียบ ๆ (ปล่อยให้ DB เก็บค่าที่
    การวัดของเราเองบอกว่าผิด) หรือหยุดให้คนมาดู · เลือกอย่างหลังด้วยหลักเดียวกับ
    §"แถวไหนทำทั้งไฟล์พัง" ของ ADR-0015 D4
    """
    (row,) = parse_manual_rows([_raw(width_in="21", height_in="31")])  # → OTHER
    state = _state(values={**_state().values, "size_format": SizeFormat.ONE_SHEET})
    (plan,) = plan_writes([row], {PID: state})
    assert plan.blockers
    assert "size_format" in plan.blockers[0]
    assert "size_format" not in plan.field_writes


def test_no_blocker_when_the_measurement_agrees_with_what_is_stored() -> None:
    """ค่าเท่าเดิม = ไม่ใช่ความขัดแย้ง และไม่ใช่การเขียนซ้ำ"""
    (row,) = parse_manual_rows([_raw()])  # 27×41 → ONE_SHEET
    state = _state(values={**_state().values, "size_format": SizeFormat.ONE_SHEET})
    (plan,) = plan_writes([row], {PID: state})
    assert plan.blockers == ()
    assert "size_format" not in plan.field_writes


def test_extra_columns_in_the_sheet_are_ignored_not_written() -> None:
    """ADR-0010 D2 + skill poster-database §3 — ห้ามแตะ `needs_review`/`status`
    เด็ดขาด · ตัวเขียนจริง `setattr(poster, name, ...)` วนตาม key ของ `field_writes`
    เท่านั้น ข้อนี้จึงพิสูจน์ว่าคอลัมน์ที่ไม่ได้อยู่ใน allowlist เข้าไปถึง key ไม่ได้
    แม้จะถูกเติมลงไฟล์ด้วยมือ"""
    raw = _raw()
    raw["needs_review"] = "false"
    raw["status"] = "available"
    raw["published_at"] = "2026-08-05T20:00:00+07:00"
    (row,) = parse_manual_rows([raw])
    assert set(row.values) == set(ALLOWED_FIELDS)

    (plan,) = plan_writes([row], {PID: _state()})
    # `size_format` เข้ามาได้ทางเดียวคือ derive (D16) — ไม่ใช่จากคอลัมน์ในไฟล์
    assert set(plan.field_writes) <= set(ALLOWED_FIELDS) | set(DERIVED_FIELDS)
    assert plan.publish_action is PublishAction.NONE  # publish ว่าง → ไม่เปิดขาย


# --- D2/D3: การตรวจรูปแบบ ---


def test_valid_row_parses_every_field() -> None:
    (row,) = parse_manual_rows([_raw()])
    assert row.values == {
        "condition_grade": PosterCondition.very_good,
        "year": 1999,
        "poster_type": PosterType.THEATRICAL,
        "restoration_status": RestorationStatus.NONE,
        "tmdb_id": 603,
        "width_in": Decimal("27"),
        "height_in": Decimal("41"),
    }
    assert row.publish is Publish.PENDING


def test_blank_cells_are_skipped_not_written_as_null() -> None:
    """D6 — ช่องว่างต้องไม่โผล่ใน values เลย ชั้นล่างจึงไม่มีทางเขียน NULL ทับของเดิม"""
    (row,) = parse_manual_rows([_raw(year="", poster_type="", tmdb_id="")])
    assert set(row.values) == {
        "condition_grade",
        "restoration_status",
        "width_in",
        "height_in",
    }


def test_entirely_blank_row_is_normal_not_an_error() -> None:
    """ใบงานที่กรอกไปได้ครึ่งเดียวเป็นสถานะปกติของงานนี้ ไม่ใช่ความผิดพลาด"""
    (row,) = parse_manual_rows(
        [_raw(**{name: "" for name in ALLOWED_FIELDS})]  # type: ignore[arg-type]
    )
    assert row.values == {}


@pytest.mark.parametrize(
    "over",
    [
        {"condition_grade": "excellent"},  # ไม่อยู่ใน enum
        {"condition_grade": "C7"},  # สเกลที่ ADR-0003 ปฏิเสธไปแล้ว
        {"poster_type": "STREAMING"},  # ADR-0009 D14 ยังไม่เพิ่มค่านี้
        {"restoration_status": "linen"},
        {"year": "199"},
        {"year": str(YEAR_MIN - 1)},
        {"year": str(YEAR_MAX + 1)},
        {"year": "1999.5"},
        {"tmdb_id": "0"},
        {"tmdb_id": "-3"},
        {"tmdb_id": "tt0133093"},  # id ของ IMDb ไม่ใช่ TMDB
        # 📏 ADR-0009 D16 — ช่วงและรูปแบบของขนาดที่วัดได้
        {"width_in": "ยี่สิบเจ็ด"},
        {"width_in": '27"'},  # หน่วยติดมาด้วย — คอลัมน์เป็นตัวเลขล้วน
        {"width_in": "27x40"},  # คัดมาจากช่อง `size` เดิม ซึ่ง D4 ห้ามใช้เป็น input
        {"height_in": "0"},
        {"height_in": "-27"},
        {"height_in": "100"},  # เกินเพดานของ Numeric(5, 2)
        {"width_in": "NaN"},  # `Decimal()` รับเข้ามาโดยปริยาย — ต้องดักก่อนเทียบช่วง
        {"width_in": "Infinity"},
        {"publish": "maybe"},
        {"poster_uuid": "not-a-uuid"},
    ],
)
def test_bad_values_reject_the_whole_file(over: dict[str, str]) -> None:
    """fail-closed — คนกรอกเข้าใจกติกาไม่ตรงกัน การ apply บางส่วนจะตามยากภายหลัง"""
    with pytest.raises(PrecheckError):
        parse_manual_rows([_raw(**over)])


def test_uppercase_enums_stay_case_insensitive() -> None:
    """`poster_type`/`restoration_status` ยังรับตัวพิมพ์ผสม — ตั้งใจ

    `manual-entry.csv` วันนี้มี `Unknown` (ตัวพิมพ์ผสม) อยู่ 2 แถวและผ่านได้เพราะข้อนี้
    ถ้าใครจะทำให้เข้มต้องแก้ไฟล์ก่อน ไม่ใช่แก้สคริปต์ก่อน
    """
    (row,) = parse_manual_rows(
        [_raw(poster_type="theatrical", restoration_status="none")]
    )
    assert row.values["poster_type"] is PosterType.THEATRICAL
    assert row.values["restoration_status"] is RestorationStatus.NONE


def test_condition_grade_rejects_wrong_case() -> None:
    """🔴 `condition_grade` ต้องตรงเป๊ะ — ห้ามแปลงเงียบ ๆ (BR-05)

    เกิดขึ้นจริง: `Fine` 8 แถว + `Good` 3 แถว ถูกแปลงเงียบเข้า DB เมื่อ 2026-08-07
    ก่อนที่ใครจะเห็นว่าคนกรอกใช้สเกลคนละชุดในหัวหรือแค่พิมพ์ลวก
    """
    for wrong in ("Fine", "Good", "NEAR_MINT", "Very_Fine"):
        with pytest.raises(PrecheckError) as exc:
            parse_manual_rows([_raw(condition_grade=wrong)])
        message = str(exc.value)
        assert "ตัวพิมพ์ไม่ตรง" in message, message
        # ต้องบอก **เลขบรรทัด** ไม่ใช่แค่ว่ามีอะไรผิดสักที่ในไฟล์
        assert "บรรทัด" in message, message
        # ต้องบอกค่าที่ถูกให้ด้วย ไม่ใช่ปล่อยให้ไปเดาเอง
        assert repr(wrong.lower()) in message, message


def test_condition_grade_still_rejects_values_outside_enum() -> None:
    """ค่าที่ไม่มีจริงต้องได้ข้อความคนละแบบกับเคสผิด — สองอย่างนี้แก้คนละวิธี"""
    with pytest.raises(PrecheckError) as exc:
        parse_manual_rows([_raw(condition_grade="excellent")])
    message = str(exc.value)
    assert "ไม่อยู่ใน enum" in message, message
    assert "ตัวพิมพ์ไม่ตรง" not in message, message


def test_condition_grade_accepts_exact_lowercase() -> None:
    (row,) = parse_manual_rows([_raw(condition_grade="very_good")])
    assert row.values["condition_grade"] is PosterCondition.very_good


def test_unknown_is_accepted_from_a_human() -> None:
    """ADR-0009 D2 — `UNKNOWN` = "คนตรวจใบจริงแล้วแต่ตัดสินไม่ได้" ซึ่งคนเท่านั้นพูดได้
    เส้นทางนี้คือเส้นเดียวที่คนพิมพ์เอง จึงเป็นเส้นเดียวที่เขียนค่านี้ได้ (ADR-0015 D3)
    """
    (row,) = parse_manual_rows(
        [_raw(poster_type="UNKNOWN", restoration_status="UNKNOWN")]
    )
    assert row.values["poster_type"] is PosterType.UNKNOWN
    assert row.values["restoration_status"] is RestorationStatus.UNKNOWN


def test_enum_choices_come_from_the_enum_not_a_copied_list() -> None:
    """ถ้ามีใครเพิ่มค่าเข้า enum ใหม่ ใบงานต้องรับได้ทันทีโดยไม่ต้องแก้สคริปต์"""
    for member in PosterCondition:
        (row,) = parse_manual_rows([_raw(condition_grade=member.value)])
        assert row.values["condition_grade"] is member


def test_duplicate_poster_uuid_rejects_the_file() -> None:
    with pytest.raises(PrecheckError, match="ซ้ำ"):
        parse_manual_rows([_raw(), _raw()])


def test_missing_required_column_is_reported_by_name(tmp_path) -> None:
    from scripts.seed.manual_entry import read_manual_sheet

    path = tmp_path / "sheet.csv"
    path.write_text("poster_uuid,title\n", encoding="utf-8")
    with pytest.raises(PrecheckError, match="condition_grade"):
        read_manual_sheet(path)


# --- D5/D6: UPDATE เท่านั้น · ไม่มีโหมดเขียนทับ ---


def test_missing_poster_is_skipped_never_inserted() -> None:
    (plan,) = plan_writes([_row()], {})
    assert plan.found is False
    assert plan.field_writes == {}
    assert plan.publish_action is PublishAction.SKIP_NOT_FOUND


def test_existing_value_is_skipped_not_overwritten() -> None:
    state = _state(values={**_state().values, "condition_grade": PosterCondition.mint})
    (plan,) = plan_writes([_row()], {PID: state})
    assert plan.field_writes == {}
    assert plan.skipped_already_set == {"condition_grade": "mint"}


def test_null_targets_are_written() -> None:
    (plan,) = plan_writes([_row()], {PID: _state()})
    assert plan.field_writes == {"condition_grade": PosterCondition.very_good}


def test_rerunning_the_same_sheet_writes_nothing_second_time() -> None:
    """idempotent โดยโครงสร้าง (D6) — รอบสองสถานะ DB มีค่าครบแล้ว จึงไม่มีอะไรให้เขียน"""
    row = _row(values={"condition_grade": PosterCondition.very_good, "year": 1999})
    first = plan_writes([row], {PID: _state()})
    assert planned_field_counts(first)["condition_grade"] == 1
    after = _state(
        values={
            **_state().values,
            "condition_grade": PosterCondition.very_good,
            "year": 1999,
        }
    )
    second = plan_writes([row], {PID: after})
    assert planned_field_counts(second) == dict.fromkeys(
        [*ALLOWED_FIELDS, *DERIVED_FIELDS, PUBLISH_FIELD], 0
    )


def test_zero_is_not_mistaken_for_a_missing_value() -> None:
    """`tmdb_id` เป็นตัวเลข — เช็คด้วย `is None` ไม่ใช่ความจริงเชิงตรรกะ ไม่งั้นค่า 0
    (ถ้ามีหลุดเข้ามา) จะถูกอ่านว่า "ยังว่าง" แล้วถูกทับ"""
    state = _state(values={**_state().values, "tmdb_id": 0})
    (plan,) = plan_writes([_row(values={"tmdb_id": 5})], {PID: state})
    assert plan.field_writes == {}
    assert plan.skipped_already_set == {"tmdb_id": "0"}


# --- D4: ด่านของการเปิดขาย ---


def test_publish_needs_a_grade_from_this_sheet_or_the_db() -> None:
    row = _row(values={"condition_grade": PosterCondition.fine}, publish=Publish.YES)
    (plan,) = plan_writes([row], {PID: _state()})
    assert plan.publish_action is PublishAction.APPLY
    assert plan.blockers == ()

    row_db = _row(values={}, publish=Publish.YES)
    state = _state(values={**_state().values, "condition_grade": PosterCondition.fine})
    (plan_db,) = plan_writes([row_db], {PID: state})
    assert plan_db.publish_action is PublishAction.APPLY


def test_publish_without_any_grade_is_blocked_before_the_database_sees_it() -> None:
    """ADR-0013 D3 — ปล่อยไปจะได้ IntegrityError จาก
    ck_posters_published_requires_condition_grade · ต้องรายงานเอง ไม่ใช่ให้ DB โยน"""
    row = _row(values={}, publish=Publish.YES)
    (plan,) = plan_writes([row], {PID: _state()})
    assert plan.publish_action is PublishAction.BLOCKED
    assert any("condition_grade" in b for b in plan.blockers)


def test_publish_without_an_image_is_blocked_br06() -> None:
    """BR-06 — ADR-0013 OD-1 เลื่อนการบังคับมาให้ INF-11 (รอบนี้) เพราะ CHECK constraint
    อ้างข้ามตาราง posters ↔ poster_images ไม่ได้"""
    row = _row(publish=Publish.YES)
    (plan,) = plan_writes([row], {PID: _state(image_count=0, front_image_count=0)})
    assert plan.publish_action is PublishAction.BLOCKED
    assert any("BR-06" in b for b in plan.blockers)
    assert any("ไม่มีรูปสักรูป" in b for b in plan.blockers)


def test_publish_is_blocked_when_the_only_photos_are_back_or_defect() -> None:
    """🔴 ADR-0026 D8 — "มีรูป" ไม่พอแล้ว ต้องมีรูป **หน้าใบ**

    เคสจริงที่จะเกิดระหว่างงาน BL-40: ถ่ายรูปตำหนิกับด้านหลังไปก่อน แล้วเผลอ
    publish · ใบนั้นจะขึ้นร้านโดยหน้า Home ไม่มีรูปให้แสดงเลย (SCR-03 ใช้ FRONT
    เท่านั้น) · ข้อความต้องบอกด้วยว่า *มีรูปอยู่กี่รูป* ไม่งั้นคนอ่านจะนึกว่าไม่มีรูปเลย
    """
    row = _row(publish=Publish.YES)
    (plan,) = plan_writes([row], {PID: _state(image_count=3, front_image_count=0)})

    assert plan.publish_action is PublishAction.BLOCKED
    (blocker,) = [b for b in plan.blockers if "BR-06" in b]
    assert "kind=FRONT" in blocker
    assert "3 รูป" in blocker
    # assertion เชิงลบ — ห้ามใช้ถ้อยคำของเคส "ไม่มีรูปเลย" ซึ่งจะพาคนไปแก้ผิดจุด
    assert "ไม่มีรูปสักรูป" not in blocker


def test_publish_passes_with_a_front_photo_even_if_it_is_the_only_one() -> None:
    """ด้านที่ต้องไม่พัง — ด่านที่บล็อกทุกอย่างก็ผ่านเทสข้างบนได้เหมือนกัน"""
    row = _row(publish=Publish.YES)
    (plan,) = plan_writes([row], {PID: _state(image_count=1, front_image_count=1)})

    assert plan.publish_action is PublishAction.APPLY
    assert not plan.blockers


def test_both_publish_gates_are_reported_together() -> None:
    """คนกรอกควรเห็นทุกเหตุผลในรอบเดียว ไม่ใช่แก้ทีละข้อแล้วรันใหม่"""
    row = _row(values={}, publish=Publish.YES)
    (plan,) = plan_writes([row], {PID: _state(image_count=0, front_image_count=0)})
    assert len(plan.blockers) == 2


def test_publish_no_never_unpublishes() -> None:
    """ADR-0013 D6 — การถอดออกจากชั้นเป็นการกระทำที่ถูกต้อง แต่ไม่ใช่หน้าที่ของสคริปต์นี้
    และ "ขายไปแล้ว" ไม่ใช่เหตุผลที่ถูกต้องข้อนั้น"""
    for verdict in (Publish.NO, Publish.PENDING):
        (plan,) = plan_writes([_row(publish=verdict)], {PID: _state(published=True)})
        assert plan.publish_action is PublishAction.NONE
        assert PUBLISH_FIELD not in plan.field_writes


def test_already_published_is_skipped() -> None:
    (plan,) = plan_writes([_row(publish=Publish.YES)], {PID: _state(published=True)})
    assert plan.publish_action is PublishAction.SKIP_ALREADY


def test_publish_for_a_missing_poster_is_a_skip_not_a_blocker() -> None:
    """ใบที่ไม่มีใน DB เป็นเรื่องปกติของใบงานเก่า — ไม่ควรทำให้ทั้งไฟล์ล้ม"""
    (plan,) = plan_writes([_row(publish=Publish.YES)], {})
    assert plan.blockers == ()


# --- D9 ข้อ 2 / A-D2: ประตูจำนวน (count_actual) — ADR-0019 · INF-22 ---


def test_count_actual_blank_is_not_a_blocker() -> None:
    """ค่าว่าง = 'ยังไม่นับ' — วันนี้ว่าง 117/117 ห้ามกลายเป็นด่านที่ปฏิเสธข้อมูลที่
    ถูกอยู่แล้วทั้งไฟล์ (A-D2 ข้อ 2)"""
    row = _row(publish=Publish.YES, count_actual=None)
    (plan,) = plan_writes([row], {PID: _state()})
    assert plan.publish_action is PublishAction.APPLY
    assert plan.blockers == ()


def test_count_actual_zero_blocks_publish() -> None:
    row = _row(publish=Publish.YES, count_actual=0)
    (plan,) = plan_writes([row], {PID: _state()})
    assert plan.publish_action is PublishAction.BLOCKED
    assert any("count_actual" in b and "= 0" in b for b in plan.blockers)


def test_count_actual_zero_is_not_a_blocker_when_not_publishing() -> None:
    """🔴 ด่านนี้เป็น *ประตู publish* ตรงตัวตาม D9 ข้อ 2 — แถวที่ publish=N/ว่าง
    ยังไม่ต้องผ่านด่านนี้เลย (ต่างจาก publish=Y ซึ่งเป็นค่า default ของอาร์กิวเมนต์
    `--field`/ทดสอบข้างบนทุกตัว — ตัวนี้คือเทสที่ยืนยันขอบเขตด้วยค่าที่ไม่ใช่ YES)"""
    for verdict in (Publish.PENDING, Publish.NO):
        row = _row(publish=verdict, count_actual=0)
        (plan,) = plan_writes([row], {PID: _state()})
        assert plan.publish_action is PublishAction.NONE
        assert plan.blockers == ()


def test_count_actual_two_or_more_blocks_publish_on_a_non_mint_grade() -> None:
    row = _row(
        values={"condition_grade": PosterCondition.near_mint},
        publish=Publish.YES,
        count_actual=2,
    )
    (plan,) = plan_writes([row], {PID: _state()})
    assert plan.publish_action is PublishAction.BLOCKED
    assert any("mint" in b for b in plan.blockers)


def test_count_actual_two_or_more_passes_on_mint() -> None:
    """ด้านที่ต้องไม่พัง — ประตูนี้เจาะจงที่ *เกรด* ไม่ใช่ปฏิเสธ ≥2 ทุกกรณี"""
    row = _row(
        values={"condition_grade": PosterCondition.mint},
        publish=Publish.YES,
        count_actual=2,
    )
    (plan,) = plan_writes([row], {PID: _state()})
    assert plan.publish_action is PublishAction.APPLY
    assert plan.blockers == ()


def test_count_actual_one_on_a_non_mint_grade_passes() -> None:
    """ขอบเขตล่างของด่าน ≥2 — 1 ชิ้นไม่ใช่ปัญหาไม่ว่าจะเกรดไหน"""
    row = _row(
        values={"condition_grade": PosterCondition.fine},
        publish=Publish.YES,
        count_actual=1,
    )
    (plan,) = plan_writes([row], {PID: _state()})
    assert plan.publish_action is PublishAction.APPLY
    assert plan.blockers == ()


def test_count_actual_checks_the_grade_after_this_round_not_only_the_db() -> None:
    """เกรดที่รอบนี้กำลังจะเขียน (ไม่ใช่แค่ค่าที่มีอยู่ใน DB) ต้องถูกใช้ตัดสินด้วย —
    ทรงเดียวกับด่าน BR-05 (D4 ด่านที่ 1) ที่อ่าน grade_after ไม่ใช่แค่ state เดิม"""
    row = _row(
        values={"condition_grade": PosterCondition.mint},
        publish=Publish.YES,
        count_actual=3,
    )
    state = _state(values={**_state().values, "condition_grade": None})
    (plan,) = plan_writes([row], {PID: state})
    assert plan.publish_action is PublishAction.APPLY


def test_count_actual_parse_rejects_negative_values() -> None:
    with pytest.raises(PrecheckError, match="count_actual"):
        parse_manual_rows([_raw(count_actual="-1", publish="")])


def test_count_actual_parse_rejects_non_integers() -> None:
    with pytest.raises(PrecheckError, match="count_actual"):
        parse_manual_rows([_raw(count_actual="abc", publish="")])


def test_count_actual_parse_accepts_blank_and_zero_and_positive() -> None:
    (blank,) = parse_manual_rows([_raw(count_actual="", publish="")])
    (zero,) = parse_manual_rows([_raw(count_actual="0", publish="")])
    (three,) = parse_manual_rows([_raw(count_actual="3", publish="")])
    assert blank.count_actual is None
    assert zero.count_actual == 0
    assert three.count_actual == 3


def test_dry_run_report_warns_about_uncounted_rows_about_to_publish(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """ค่าว่างไม่ใช่ blocker แต่ยังต้องให้คนเห็นว่ายังไม่มีผลนับ (ADR-0019 D10)"""
    from scripts.seed.manual_entry import _report

    row = _row(publish=Publish.YES, count_actual=None)
    plans = plan_writes([row], {PID: _state()})
    _report(plans, "test", committed=False)
    out = capsys.readouterr().out
    assert "ยังไม่มีผลนับ" in out
    assert "1/1" in out


def test_dry_run_report_says_nothing_about_counting_when_nothing_is_publishing(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """ด้านที่ต้องไม่พัง — บรรทัดเตือนไม่ควรโผล่เมื่อไม่มีแถวไหนจะเปิดขายรอบนี้เลย"""
    from scripts.seed.manual_entry import _report

    row = _row(publish=Publish.PENDING, count_actual=None)
    plans = plan_writes([row], {PID: _state()})
    _report(plans, "test", committed=False)
    out = capsys.readouterr().out
    assert "ยังไม่มีผลนับ" not in out


def test_planned_counts_split_fields_and_publication() -> None:
    rows = [
        _row(values={"condition_grade": PosterCondition.fine}, publish=Publish.YES),
        _row(poster_uuid=PID2, values={"year": 1980}, publish=Publish.NO),
    ]
    counts = planned_field_counts(plan_writes(rows, {PID: _state(), PID2: _state()}))
    assert counts["condition_grade"] == 1
    assert counts["year"] == 1
    assert counts[PUBLISH_FIELD] == 1
    assert counts["tmdb_id"] == 0


# --- assert หลัง commit ---


def test_count_assertion_passes_when_deltas_match() -> None:
    before = dict.fromkeys([*ALLOWED_FIELDS, PUBLISH_FIELD], 0)
    planned = {**before, "condition_grade": 2, PUBLISH_FIELD: 1}
    after = {**before, "condition_grade": 2, PUBLISH_FIELD: 1}
    assert _report_counts(before, after, planned) == 0


def test_count_assertion_fails_when_nothing_actually_landed() -> None:
    """ข้อนี้คือเหตุผลที่ต้องนับ count(<column>) ไม่ใช่ count(*) — สคริปต์นี้ UPDATE
    อย่างเดียว จำนวนแถวทั้งตารางจึงเท่าเดิมเสมอไม่ว่าจะเขียนสำเร็จหรือไม่"""
    before = dict.fromkeys([*ALLOWED_FIELDS, PUBLISH_FIELD], 0)
    planned = {**before, "condition_grade": 2}
    assert _report_counts(before, dict(before), planned) == 1


def test_count_assertion_covers_every_writable_column() -> None:
    source = inspect.getsource(_report_counts)
    assert "count(*)" in source  # อธิบายไว้ว่าทำไมไม่ใช้
    for name in [*ALLOWED_FIELDS, PUBLISH_FIELD]:
        counts = dict.fromkeys([*ALLOWED_FIELDS, PUBLISH_FIELD], 0)
        assert _report_counts(counts, counts, {**counts, name: 1}) == 1


# --- make_manual_sheet ---


def _db_row(**over: object) -> dict:
    row: dict = {
        "id": PID,
        "title": "Some Poster",
        "published_at": None,
        **{name: None for name in ALLOWED_FIELDS},
        # generator อ่านค่า derived มาแสดงไม่ได้ (ไม่มีคอลัมน์ในใบงาน) แต่ `_state()`
        # ของฝั่ง plan_writes ต้องมี — ดู `_state()` ข้างล่าง
    }
    row.update(over)
    return row


def test_sheet_uses_the_column_list_shared_with_the_applier() -> None:
    rows = build_sheet_rows([_db_row()], {}, include_complete=False)
    assert set(rows[0]) == set(MANUAL_SHEET_COLUMNS)
    assert set(REQUIRED_COLUMNS) <= set(MANUAL_SHEET_COLUMNS)


def test_publish_column_is_always_left_empty() -> None:
    """🔴 เครื่องกรอกคอลัมน์นี้ = เครื่องตัดสินใจเปิดขายแทนคน ขัด ADR-0013 D4"""
    rows = build_sheet_rows(
        [_db_row(condition_grade=PosterCondition.mint)], {}, include_complete=True
    )
    assert rows[0]["publish"] == ""
    assert rows[0]["note"] == ""


def test_generator_never_writes_into_the_human_columns() -> None:
    """ล็อกระดับ AST — กันการเผลอเติมค่า default ลงช่องที่เป็นของคน
    (แบบเดียวกับที่ ADR-0010 ล็อก approved/corrected_text ของ make_review_sheet.py)

    🔴 `width_in`/`height_in` อยู่ในรายการนี้ด้วยเหตุผลที่ *ต่างจาก* publish/note:
    ค่าที่จะเดาตามได้มีอยู่จริงในตาราง (`posters.size` = `27x40` 116/117 แถว) และมัน
    เป็น `size_guess` ที่ **ADR-0009 D4 ห้ามใช้เป็น input ของ `size_format`** ·
    เติมมาให้ดู = ชี้นำให้คนกรอกตามค่าที่ห้ามใช้ แล้ว D16 จะกลายเป็นพิธีกรรม
    """
    # ‹2026-08-08› `width_in`/`height_in` **ออกจากรายการนี้แล้ว** — เข้า ALLOWED_FIELDS
    # ที่ ADR-0015 D9 จึงถูกลูป `render_value()` เติมค่าจาก DB เหมือน condition_grade
    # (D6 idempotency: ค่าที่มีอยู่แล้วถูกแสดงให้เห็น แล้วถูกข้ามตอน apply)
    human_columns = ("publish", "note")
    tree = ast.parse(inspect.getsource(sheet_mod.build_sheet_rows))
    seen: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Dict):
            continue
        for key, value in zip(node.keys, node.values, strict=True):
            if isinstance(key, ast.Constant) and key.value in human_columns:
                assert isinstance(
                    value, ast.Constant
                ), f"{key.value} ถูกเติมด้วยนิพจน์ ไม่ใช่ค่าว่างคงที่"
                assert value.value == ""
                seen.add(key.value)
    # closed-world — เทสนี้ผ่านได้ฟรีถ้าคอลัมน์ถูกลบออกจาก build_sheet_rows ไปเฉย ๆ
    assert seen == set(human_columns)


def test_existing_values_are_shown_so_the_human_knows_what_is_done() -> None:
    rows = build_sheet_rows(
        [_db_row(condition_grade=PosterCondition.fine, year=1994)],
        {PID: "https://cdn.invalid/a.jpg"},
        include_complete=False,
    )
    assert rows[0]["condition_grade"] == "fine"
    assert rows[0]["year"] == "1994"
    assert rows[0]["poster_type"] == ""
    assert rows[0]["image_url"] == "https://cdn.invalid/a.jpg"


def test_complete_and_published_rows_are_dropped_unless_all_is_asked() -> None:
    complete = _db_row(
        published_at=NOW,
        condition_grade=PosterCondition.mint,
        year=1994,
        poster_type=PosterType.THEATRICAL,
        restoration_status=RestorationStatus.NONE,
        tmdb_id=603,
        width_in=Decimal("27.00"),
        height_in=Decimal("41.00"),
    )
    assert build_sheet_rows([complete], {}, include_complete=False) == []
    assert len(build_sheet_rows([complete], {}, include_complete=True)) == 1


def test_complete_but_unpublished_row_is_still_included() -> None:
    """ใบที่กรอกครบแต่ยังไม่เปิดขายคือใบที่เหลือแค่คนกด — ต้องอยู่ในใบงาน"""
    row = _db_row(
        condition_grade=PosterCondition.mint,
        year=1994,
        poster_type=PosterType.THEATRICAL,
        restoration_status=RestorationStatus.NONE,
        tmdb_id=603,
    )
    assert len(build_sheet_rows([row], {}, include_complete=False)) == 1


def test_ungraded_rows_sort_before_graded_ones() -> None:
    graded = _db_row(id=PID, title="AAA", condition_grade=PosterCondition.mint)
    ungraded = _db_row(id=PID2, title="ZZZ")
    rows = build_sheet_rows([graded, ungraded], {}, include_complete=False)
    assert [r["poster_uuid"] for r in rows] == [str(PID2), str(PID)]


def test_poster_without_a_public_image_gets_an_empty_url() -> None:
    """ADR-0006 D5 — key ที่ไม่ public ถูกกรองทิ้งก่อนถึง build_media_url()
    ใบแบบนั้นเปิดขายไม่ได้ตาม BR-06 อยู่แล้ว จึงไม่ควรมี url ปลอมมาให้กด"""
    rows = build_sheet_rows([_db_row()], {}, include_complete=False)
    assert rows[0]["image_url"] == ""


# --- D8 (amendment 2026-08-06): --target dev|sit · guard ต้องไม่อ่อนลง ---

SIT_URL = "postgresql+asyncpg://u:p@db:5432/poster_nung_db_sit"
DEV_URL = "postgresql+asyncpg://u:p@localhost:5432/poster_nung_db"


def _fake_env(monkeypatch, files: dict[str, dict[str, str]]) -> None:
    """แทน `_parse_env_file` ทั้งของ manual_entry และของ apply_suggestions ที่มันเรียกต่อ

    ต้อง patch สองที่เพราะ manual_entry import ชื่อมาไว้ใน namespace ตัวเอง แต่
    `assert_target_database()` (ชั้นแรก) อ่านผ่าน namespace ของ apply_suggestions
    """
    from scripts.seed import apply_suggestions as apply_mod
    from scripts.seed import manual_entry as mod

    def fake(path) -> dict[str, str]:
        return files.get(getattr(path, "name", str(path)), {})

    monkeypatch.setattr(mod, "_parse_env_file", fake)
    monkeypatch.setattr(apply_mod, "_parse_env_file", fake)


def test_production_is_not_a_selectable_target() -> None:
    """🔴 ห้ามเพิ่ม production เข้า TARGETS โดยไม่แก้ ADR-0015 D8"""
    from scripts.seed.manual_entry import TARGETS

    assert TARGETS == ("dev", "sit")


def test_sit_accepts_only_the_url_from_env_sit(monkeypatch) -> None:
    from scripts.seed.manual_entry import assert_target

    _fake_env(monkeypatch, {".env.sit": {"DATABASE_URL": SIT_URL}})
    assert "poster_nung_db_sit" in assert_target(SIT_URL, "sit")


def test_sit_rejects_a_url_that_differs_from_env_sit(monkeypatch) -> None:
    from scripts.seed.manual_entry import assert_target

    _fake_env(monkeypatch, {".env.sit": {"DATABASE_URL": SIT_URL}})
    other = "postgresql+asyncpg://u:p@db:5432/somewhere_sit"
    with pytest.raises(PrecheckError, match="ไม่ตรงกับค่าใน"):
        assert_target(other, "sit")


def test_sit_refuses_to_run_when_env_sit_is_missing(monkeypatch) -> None:
    """🔴 ข้อที่ทำให้ guard **ไม่อ่อนลง** — `assert_target_database()` ของ ADR-0010 D7
    ยอมรับ url ที่ชื่อ db มีคำว่า 'sit' เมื่อไม่มีไฟล์ `.env.sit` · ชั้นที่สองต้องตัด
    ทางนั้นทิ้ง ไม่งั้นลบไฟล์เดียวก็เขียนทะลุไปที่ database อะไรก็ได้ที่ตั้งชื่อให้มี 'sit'
    """
    from scripts.seed import apply_suggestions as apply_mod
    from scripts.seed.manual_entry import assert_target

    _fake_env(monkeypatch, {})  # ไม่มี .env.sit เลย
    # ชั้นแรกยอมให้ผ่าน — พิสูจน์ว่าช่องนี้มีอยู่จริง ไม่ใช่กันซ้ำเปล่า ๆ
    assert apply_mod.assert_target_database(SIT_URL, "sit")
    with pytest.raises(PrecheckError, match="ยืนยันปลายทางไม่ได้"):
        assert_target(SIT_URL, "sit")


def test_env_var_left_over_from_another_env_cannot_win(monkeypatch) -> None:
    """env ที่ตั้งค้างชนะไฟล์เสมอ (12-Factor) — ต้องถูกจับได้ ไม่ใช่เขียนผิดที่เงียบ ๆ"""
    from scripts.seed.manual_entry import assert_target

    _fake_env(monkeypatch, {".env.sit": {"DATABASE_URL": SIT_URL}})
    with pytest.raises(PrecheckError):
        assert_target(DEV_URL, "sit")


def test_dev_target_still_requires_a_local_host(monkeypatch) -> None:
    """ชั้นแรกของ ADR-0010 D7 ต้องไม่ถูกผ่อนตอนเพิ่ม --target"""
    from scripts.seed.manual_entry import assert_target

    _fake_env(monkeypatch, {})
    assert assert_target(DEV_URL, "dev")
    with pytest.raises(PrecheckError, match="ไม่ใช่เครื่องนี้"):
        assert_target(SIT_URL, "dev")


@pytest.mark.parametrize(
    "url",
    [
        "postgresql+asyncpg://u:p@db:5432/poster_nung_db_prod",
        "postgresql+asyncpg://u:p@db:5432/poster_nung_db_uat",
        "postgresql+asyncpg://u:p@db:5432/poster_nung_stage_sit",
    ],
)
def test_production_like_names_are_rejected_on_every_target(monkeypatch, url) -> None:
    from scripts.seed.manual_entry import assert_target

    _fake_env(monkeypatch, {".env.sit": {"DATABASE_URL": url}})
    for target in ("dev", "sit"):
        with pytest.raises(PrecheckError):
            assert_target(url, target)


# --- preflight: ปลายทางต้องมี schema ครบก่อนเขียน ---


def test_schema_ready_passes_when_everything_is_there() -> None:
    from scripts.seed.manual_entry import assert_schema_ready

    assert_schema_ready([], True)  # ไม่ raise


def test_missing_columns_name_the_real_cause_not_an_attributeerror() -> None:
    """image เก่าในคอนเทนเนอร์ หรือ DB ที่ยังไม่ migrate — รากเดียวกันคนละอาการ
    ปล่อยไว้จะได้ `AttributeError: type object 'Poster' has no attribute 'published_at'`
    ซึ่งอ่านไม่ออกว่าต้องทำอะไรต่อ (เจอจริงตอนยิง --target sit ครั้งแรก 2026-08-06)"""
    from scripts.seed.manual_entry import assert_schema_ready

    with pytest.raises(PrecheckError, match="BL-75") as exc:
        assert_schema_ready(["published_at"], False)
    assert "published_at" in str(exc.value)


def test_missing_publish_check_is_refused_even_when_columns_exist() -> None:
    """🔴 ADR-0013 D3 — CHECK คือกฎที่กันการเปิดขายใบไม่มีเกรดในระดับที่ข้ามไม่ได้
    ถ้าปลายทางไม่มี การเขียนจากสคริปต์นี้จะเหลือด่านแค่ชั้นสคริปต์ซึ่งเลี่ยงได้ด้วย psql
    """
    from scripts.seed.manual_entry import (
        PUBLISH_CHECK_CONSTRAINT,
        assert_schema_ready,
    )

    with pytest.raises(PrecheckError, match=PUBLISH_CHECK_CONSTRAINT):
        assert_schema_ready([], False)


def test_render_value_is_the_single_place_values_become_text() -> None:
    assert render_value(None) == ""
    assert render_value(PosterCondition.very_good) == "very_good"
    assert render_value(1994) == "1994"


# --- ADR-0010 D8: โหมดทับค่าเดิม ---


def _state_with(**values: object) -> PosterState:
    base = {name: None for name in STATE_FIELDS}
    base.update(values)
    return PosterState(values=base, published=False, image_count=1, front_image_count=1)


def test_overwrite_is_off_by_default() -> None:
    """🔴 ด่านหลักของ D8 — ไม่ส่ง flag = D6 เดิมทุกประการ ค่าเดิมต้องรอด

    ถ้าเทสนี้แดง แปลว่าการทับกลายเป็นพฤติกรรมปริยาย ซึ่งเป็นสิ่งที่ ADR-0010 D6
    ตัดออกโดยตั้งใจตั้งแต่ GATE 1
    """
    row = _row(values={"year": 2003})
    (plan,) = plan_writes([row], {PID: _state_with(year=2022)})
    assert plan.field_writes == {}
    assert plan.skipped_already_set == {"year": "2022"}
    assert plan.overwrites == {}


def test_overwrite_only_touches_the_requested_field() -> None:
    """ฟิลด์ที่ไม่ได้ระบุยังเป็น NULL-only ในการรันเดียวกัน — flag ผูกกับฟิลด์ ไม่ใช่กับการรัน"""
    row = _row(values={"year": 2003, "condition_grade": PosterCondition.mint})
    (plan,) = plan_writes(
        [row],
        {PID: _state_with(year=2022, condition_grade=PosterCondition.fine)},
        overwrite_fields=("year",),
    )
    assert plan.field_writes == {"year": 2003}
    assert plan.overwrites == {"year": ("2022", "2003")}
    # 🔴 เกรดต้องรอด — D8 ห้ามทับ condition_grade ตลอดกาล (BR-05)
    assert plan.skipped_already_set == {"condition_grade": "fine"}


def test_overwrite_with_identical_value_is_not_a_write() -> None:
    """ค่าเท่าเดิม = ไม่ใช่การแก้ · ถ้านับเป็น write จะได้ audit ปลอมและเลิก idempotent"""
    row = _row(values={"year": 2003})
    (plan,) = plan_writes(
        [row], {PID: _state_with(year=2003)}, overwrite_fields=("year",)
    )
    assert plan.field_writes == {}
    assert plan.overwrites == {}
    assert plan.skipped_already_set == {"year": "2003"}


def test_overwrite_still_fills_nulls_without_recording_an_overwrite() -> None:
    """ช่องว่างที่ถูกเติมต้องไม่ถูกบันทึกเป็นการทับ — audit จะได้ value_before = NULL ถูกต้อง"""
    row = _row(values={"year": 2003})
    (plan,) = plan_writes([row], {PID: _state_with()}, overwrite_fields=("year",))
    assert plan.field_writes == {"year": 2003}
    assert plan.overwrites == {}


def test_title_is_unreadable_without_the_flag() -> None:
    """`title` ต้องไม่หลุดเข้า values เลยถ้าไม่ขอ overwrite — ไม่งั้นชื่อจะถูกเขียนโดยไม่ตั้งใจ"""
    (row,) = parse_manual_rows([_raw(title="NEW NAME")])
    assert "title" not in row.values

    (row2,) = parse_manual_rows([_raw(title="NEW NAME")], ("title",))
    assert row2.values["title"] == "NEW NAME"


def test_title_trims_trailing_space() -> None:
    """เคสจริงใน manual-entry.csv (BL-87) — เว้นวรรคเกินท้ายสตริงที่มองไม่เห็นด้วยตา"""
    (row,) = parse_manual_rows([_raw(title="Hobbit: The Battle  ")], ("title",))
    assert row.values["title"] == "Hobbit: The Battle"


def test_planned_counts_exclude_overwrites() -> None:
    """🔴 count(<column>) ไม่ขยับเมื่อทับ — ถ้านับรวม assert หลัง commit จะฟ้องผิดทุกครั้ง"""
    row = _row(values={"year": 2003})
    plans = plan_writes(
        [row], {PID: _state_with(year=2022)}, overwrite_fields=("year",)
    )
    assert planned_field_counts(plans)["year"] == 0


def test_verify_overwrites_catches_a_write_that_did_not_land() -> None:
    """ตัวเดียวที่พิสูจน์การทับได้ — อ่านค่ากลับมาเทียบ ไม่ใช่นับจำนวน"""
    row = _row(values={"year": 2003})
    plans = plan_writes(
        [row], {PID: _state_with(year=2022)}, overwrite_fields=("year",)
    )
    assert verify_overwrites(plans, {PID: _state_with(year=2003)}) == []

    problems = verify_overwrites(plans, {PID: _state_with(year=2022)})
    assert len(problems) == 1
    assert "'2003'" in problems[0] and "'2022'" in problems[0]


def test_audit_records_the_real_previous_value_when_overwriting() -> None:
    """🔴 ADR-0010 D8 บังคับข้อนี้ตรง ๆ — audit ที่ value_before เป็น NULL ตอนทับ
    จะหน้าตาเหมือนการเติมช่องว่าง ซึ่งอ่านย้อนแล้วเข้าใจผิดถาวรและตามกลับไม่ได้

    เทสนี้เกิดจาก mutation ที่รอด (2026-08-07): เปลี่ยนตัวเขียนให้ใส่ None เสมอ
    แล้วเทสทั้ง 74 ตัวยังเขียว เพราะตรรกะเดิมอยู่ในลูปที่ต้องมี DB ถึงจะรันได้
    """
    row = _row(values={"year": 2003})
    (plan,) = plan_writes(
        [row], {PID: _state_with(year=2022)}, overwrite_fields=("year",)
    )
    assert audit_value_before(plan, "year") == "2022"


def test_audit_value_before_is_null_when_filling_a_blank() -> None:
    """D6 — เติมช่องว่างไม่มีค่าเดิมให้เก็บ · ต้องไม่ไปใส่ค่าอะไรมั่ว"""
    row = _row(values={"year": 2003})
    (plan,) = plan_writes([row], {PID: _state_with()}, overwrite_fields=("year",))
    assert audit_value_before(plan, "year") is None
