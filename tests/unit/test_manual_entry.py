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

import pytest

from app.models.enums import PosterCondition, PosterType, RestorationStatus
from scripts.seed import make_manual_sheet as sheet_mod
from scripts.seed.make_manual_sheet import build_sheet_rows
from scripts.seed.manual_entry import (
    ALLOWED_FIELDS,
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
        "lineno": 2,
    }
    base.update(over)
    return ManualRow(**base)  # type: ignore[arg-type]


def _state(**over: object) -> PosterState:
    base: dict[str, object] = {
        "values": {name: None for name in ALLOWED_FIELDS},
        "published": False,
        "image_count": 1,
    }
    base.update(over)
    return PosterState(**base)  # type: ignore[arg-type]


# --- D2: allowlist ---


def test_allowlist_is_exactly_the_five_human_only_fields() -> None:
    """ล็อก allowlist ไว้ตรง ๆ — การเพิ่มฟิลด์คือการแก้มติ ADR-0015 D2 ต้องผ่าน ADR
    ก่อน ไม่ใช่แก้ค่าคงที่เงียบ ๆ แล้ว test เดิมยังเขียว"""
    assert ALLOWED_FIELDS == (
        "condition_grade",
        "year",
        "poster_type",
        "restoration_status",
        "tmdb_id",
    )


def test_every_allowed_field_has_a_spec_and_vice_versa() -> None:
    assert set(field_specs()) == set(ALLOWED_FIELDS)


def test_published_at_is_not_in_the_allowlist() -> None:
    """`published_at` ต้องผ่านคอลัมน์ `publish` ที่มีด่านของตัวเอง (D4) เท่านั้น —
    ถ้ามันหลุดเข้า ALLOWED_FIELDS จะกลายเป็นช่องกรอกธรรมดาที่ข้ามด่านทั้งสองไปได้"""
    assert PUBLISH_FIELD not in ALLOWED_FIELDS


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
    assert set(plan.field_writes) <= set(ALLOWED_FIELDS)
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
    }
    assert row.publish is Publish.PENDING


def test_blank_cells_are_skipped_not_written_as_null() -> None:
    """D6 — ช่องว่างต้องไม่โผล่ใน values เลย ชั้นล่างจึงไม่มีทางเขียน NULL ทับของเดิม"""
    (row,) = parse_manual_rows([_raw(year="", poster_type="", tmdb_id="")])
    assert set(row.values) == {"condition_grade", "restoration_status"}


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
        {"publish": "maybe"},
        {"poster_uuid": "not-a-uuid"},
    ],
)
def test_bad_values_reject_the_whole_file(over: dict[str, str]) -> None:
    """fail-closed — คนกรอกเข้าใจกติกาไม่ตรงกัน การ apply บางส่วนจะตามยากภายหลัง"""
    with pytest.raises(PrecheckError):
        parse_manual_rows([_raw(**over)])


def test_enum_values_are_case_insensitive() -> None:
    (row,) = parse_manual_rows(
        [_raw(condition_grade="VERY_GOOD", poster_type="theatrical")]
    )
    assert row.values["condition_grade"] is PosterCondition.very_good
    assert row.values["poster_type"] is PosterType.THEATRICAL


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
        [*ALLOWED_FIELDS, PUBLISH_FIELD], 0
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
    (plan,) = plan_writes([row], {PID: _state(image_count=0)})
    assert plan.publish_action is PublishAction.BLOCKED
    assert any("BR-06" in b for b in plan.blockers)


def test_both_publish_gates_are_reported_together() -> None:
    """คนกรอกควรเห็นทุกเหตุผลในรอบเดียว ไม่ใช่แก้ทีละข้อแล้วรันใหม่"""
    row = _row(values={}, publish=Publish.YES)
    (plan,) = plan_writes([row], {PID: _state(image_count=0)})
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


def test_generator_never_writes_into_the_two_human_columns() -> None:
    """ล็อกระดับ AST — กันการเผลอเติมค่า default ลง publish/note ในอนาคต
    (แบบเดียวกับที่ ADR-0010 ล็อก approved/corrected_text ของ make_review_sheet.py)"""
    tree = ast.parse(inspect.getsource(sheet_mod.build_sheet_rows))
    for node in ast.walk(tree):
        if not isinstance(node, ast.Dict):
            continue
        for key, value in zip(node.keys, node.values, strict=True):
            if (
                isinstance(key, ast.Constant)
                and key.value in ("publish", "note")
                and isinstance(value, ast.Constant)
            ):
                assert value.value == ""


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


def test_render_value_is_the_single_place_values_become_text() -> None:
    assert render_value(None) == ""
    assert render_value(PosterCondition.very_good) == "very_good"
    assert render_value(1994) == "1994"
