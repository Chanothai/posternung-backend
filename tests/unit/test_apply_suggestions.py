"""Unit tests ของ `scripts/seed/apply_suggestions.py` — ล็อกกฎ D1–D7 ของ ADR-0010

ไม่ต่อ DB จริง — ทุก test ทำกับฟังก์ชัน pure (`parse_review_rows`, `plan_writes`,
`assert_target_database`) ซึ่งรับสถานะเข้ามาแทนการ query เอง ตาม ship-backend-change §3
(เลี่ยง fixture ที่ไม่จำเป็น)
"""

from __future__ import annotations

import ast
import inspect
import uuid
from datetime import date
from pathlib import Path

import pytest

from scripts.seed import apply_suggestions as mod
from scripts.seed.apply_suggestions import (
    ALLOWED_FIELDS,
    REQUIRED_COLUMNS,
    REVIEW_SHEET_COLUMNS,
    TARGET_FIELD,
    Action,
    PrecheckError,
    ReviewRow,
    Verdict,
    assert_target_database,
    parse_review_rows,
    plan_writes,
)

PID = uuid.UUID("11111111-1111-1111-1111-111111111111")


def _raw(**over: str) -> dict[str, str]:
    row = {
        "poster_uuid": str(PID),
        "release_date_text": "20/7/2023",
        "parsed_date": "2023-07-20",
        "parse_status": "ok",
        "evidence": "ตัวเลขใต้ billing block",
        "image_url": "https://example.invalid/a.jpg",
        "approved": "yes",
        "corrected_text": "",
    }
    row.update(over)
    return row


def _row(**over: object) -> ReviewRow:
    base: dict[str, object] = {
        "poster_uuid": PID,
        "release_date_text": "20/7/2023",
        "corrected_text": "",
        "verdict": Verdict.APPROVED,
    }
    base.update(over)
    return ReviewRow(**base)  # type: ignore[arg-type]


# --- D4: allowlist ---


def test_allowlist_has_exactly_release_date_text() -> None:
    """ล็อก allowlist ไว้ตรง ๆ — การขยายฟิลด์คือการแก้มติ ADR-0010 D4 ต้องผ่าน ADR
    ก่อน ไม่ใช่แก้ค่าคงที่เงียบ ๆ แล้ว test เดิมยังเขียว"""
    assert ALLOWED_FIELDS == {"release_date_text"}


def test_target_field_stays_consistent_with_allowlist() -> None:
    """ใบงานไม่มีคอลัมน์ `field` เพราะ allowlist มีตัวเดียว — ถ้าใครขยาย allowlist
    โดยไม่เพิ่มคอลัมน์นั้นกลับมา สคริปต์จะเขียนฟิลด์ผิดโดยเงียบ · test นี้บังคับให้
    สองอย่างขยับพร้อมกัน"""
    assert ALLOWED_FIELDS == {TARGET_FIELD}


def test_required_columns_are_a_subset_of_the_generated_sheet() -> None:
    """คอลัมน์ที่สคริปต์ต้องใช้ ต้องมีอยู่ในใบงานที่ make_review_sheet.py สร้างเสมอ"""
    assert set(REQUIRED_COLUMNS) <= set(REVIEW_SHEET_COLUMNS)


# --- approved เป็นตัวกั้น ---


def test_pending_row_is_skipped_not_an_error() -> None:
    """`approved` ว่าง = ยังตรวจไม่ถึงแถวนี้ — ใบงานที่ทำไปครึ่งเดียวเป็นสถานะปกติ
    ต้องข้ามเฉย ๆ ไม่ใช่ทำทั้งไฟล์พัง"""
    rows = parse_review_rows([_raw(approved="")])
    assert rows[0].verdict is Verdict.PENDING
    plans = plan_writes(rows, {PID: None})
    assert plans[0].action is Action.SKIP_PENDING


def test_rejected_row_is_skipped() -> None:
    rows = parse_review_rows([_raw(approved="no")])
    assert rows[0].verdict is Verdict.REJECTED
    plans = plan_writes(rows, {PID: None})
    assert plans[0].action is Action.SKIP_REJECTED


@pytest.mark.parametrize("word", ["yes", "Y", "TRUE", "1"])
def test_approved_words_accepted(word: str) -> None:
    assert parse_review_rows([_raw(approved=word)])[0].verdict is Verdict.APPROVED


@pytest.mark.parametrize("word", ["no", "N", "false", "0"])
def test_rejected_words_accepted(word: str) -> None:
    assert parse_review_rows([_raw(approved=word)])[0].verdict is Verdict.REJECTED


def test_unknown_approved_word_rejects_whole_file() -> None:
    """คำที่ไม่รู้จักต้องไม่ถูกตีความเป็น "ไม่อนุมัติ" เงียบ ๆ — คนอาจพิมพ์ 'ok' หรือ
    'ผ่าน' แล้วนึกว่าอนุมัติแล้ว การเดาให้คือการตัดสินแทนคน"""
    with pytest.raises(PrecheckError, match="approved"):
        parse_review_rows([_raw(approved="ผ่านแล้ว")])


def test_approved_with_no_text_at_all_rejects_whole_file() -> None:
    with pytest.raises(PrecheckError, match="ไม่มีอะไรให้เขียน"):
        parse_review_rows([_raw(release_date_text="", corrected_text="")])


def test_pending_row_with_no_text_is_fine() -> None:
    """ยังไม่ตรวจ + ไม่มีข้อความ = ไม่ผิดอะไร แค่ยังไม่ถึงคิว"""
    rows = parse_review_rows(
        [_raw(approved="", release_date_text="", corrected_text="")]
    )
    assert rows[0].verdict is Verdict.PENDING


# --- corrected_text ทับ release_date_text ---


def test_corrected_text_wins_over_ai_value() -> None:
    row = _row(release_date_text="March 18", corrected_text="March 18, 2021")
    assert row.effective_text == "March 18, 2021"
    assert row.was_corrected is True


def test_effective_text_falls_back_to_ai_value_when_not_corrected() -> None:
    row = _row(release_date_text="March 18", corrected_text="")
    assert row.effective_text == "March 18"
    assert row.was_corrected is False


def test_correction_turns_an_incomplete_row_into_a_real_date() -> None:
    """เคสใช้งานจริงของ corrected_text — AI อ่านได้แค่ 'March 18' คนเปิดรูปเห็นปีแล้ว
    เติมให้ครบ → parser derive เป็น DATE ได้"""
    rows = [_row(release_date_text="March 18", corrected_text="18 March 2021")]
    plans = plan_writes(rows, {PID: None})
    assert plans[0].action is Action.APPLY
    assert plans[0].parse_status == "PARSED"
    assert plans[0].release_date == date(2021, 3, 18)


def test_parsed_date_column_in_the_sheet_is_never_trusted() -> None:
    """D4 + ADR-0009 D13 ข้อ 2 — ต่อให้คอลัมน์ parsed_date ในใบงานถูกแก้มือเป็นค่ามั่ว
    สคริปต์ต้อง parse ใหม่จาก effective_text เสมอ ไม่หยิบค่านั้นมาใช้"""
    rows = parse_review_rows(
        [_raw(release_date_text="SUMMER 2021", parsed_date="1999-01-01")]
    )
    plans = plan_writes(rows, {PID: None})
    assert plans[0].release_date is None  # ไม่ใช่ 1999-01-01
    assert plans[0].parse_status == "UNREADABLE"


def test_sheet_columns_for_humans_are_not_read_by_the_planner() -> None:
    """evidence/image_url/parse_status เป็นข้อมูลให้คนอ่าน — `ReviewRow` ไม่เก็บไว้เลย
    จึงไม่มีทางหลุดไปมีผลต่อสิ่งที่เขียนลง DB"""
    assert set(ReviewRow.__dataclass_fields__) == {
        "poster_uuid",
        "release_date_text",
        "corrected_text",
        "verdict",
    }


# --- fail-closed (รูปแบบผิด) ---


def test_bad_uuid_rejects_whole_file() -> None:
    with pytest.raises(PrecheckError, match="ไม่ใช่ UUID"):
        parse_review_rows([_raw(), _raw(poster_uuid="ไม่ใช่ uuid")])


def test_duplicate_poster_uuid_rejected() -> None:
    with pytest.raises(PrecheckError, match="ซ้ำ"):
        parse_review_rows([_raw(), _raw(corrected_text="March 18")])


# --- D6: NULL-only ---


def test_apply_when_target_column_is_null() -> None:
    plans = plan_writes([_row()], {PID: None})
    assert plans[0].action is Action.APPLY
    assert plans[0].current_value is None


def test_skip_when_target_column_already_has_value() -> None:
    """ADR-0010 D6 — ไม่มีโหมดเขียนทับ ไม่มี flag ให้ override · กันการรันซ้ำแล้วลบ
    งานที่คนแก้ไปแล้ว"""
    plans = plan_writes([_row()], {PID: "SUMMER 2021"})
    assert plans[0].action is Action.SKIP_ALREADY_SET
    assert plans[0].current_value == "SUMMER 2021"


def test_skip_when_poster_not_in_database() -> None:
    plans = plan_writes([_row()], {})
    assert plans[0].action is Action.SKIP_NOT_FOUND


def test_rerunning_the_same_sheet_is_idempotent() -> None:
    """รันรอบแรก APPLY แล้วค่าไม่เป็น NULL อีกต่อไป → รอบสองต้อง SKIP
    (idempotent โดยโครงสร้าง ไม่ต้องมี state ฝั่งสคริปต์)"""
    row = _row()
    assert plan_writes([row], {PID: None})[0].action is Action.APPLY
    second = plan_writes([row], {PID: row.effective_text})
    assert second[0].action is Action.SKIP_ALREADY_SET


def test_approval_is_checked_before_database_state() -> None:
    """แถวที่ยังไม่ตรวจต้องรายงานว่า "ยังไม่ตรวจ" ไม่ใช่ "ไม่มีใบใน DB" — ไม่งั้น
    คนอ่านรายงานจะไล่ผิดทาง"""
    plans = plan_writes([_row(verdict=Verdict.PENDING)], {})
    assert plans[0].action is Action.SKIP_PENDING


# --- D4: release_date มาจาก parser เท่านั้น ---


@pytest.mark.parametrize(
    ("value", "status"),
    [
        ("SUMMER 2021", "UNREADABLE"),
        ("March 18", "INCOMPLETE"),
        ("05/06/23", "AMBIGUOUS"),
    ],
)
def test_text_is_kept_but_release_date_stays_null_when_not_fully_parsed(
    value: str, status: str
) -> None:
    """หัวใจของ D13 — ข้อความที่อ่านได้จากใบต้องถูกเก็บเสมอ แม้ derive เป็น DATE ไม่ได้
    · โดยเฉพาะ AMBIGUOUS ที่ห้ามเดา (ใบ US ใช้ MM/DD ไทย/UK ใช้ DD/MM)"""
    plans = plan_writes([_row(release_date_text=value)], {PID: None})
    assert plans[0].action is Action.APPLY  # ยังเขียน _text
    assert plans[0].parse_status == status
    assert plans[0].release_date is None  # แต่ไม่เดา DATE


# --- D1: ต้องมีชื่อคนตรวจ + เวลา ไม่มี default ให้เดา ---


def test_reviewed_at_requires_timezone() -> None:
    """ไม่มี timezone = เครื่องต้องเดาแทนคนตรวจ ซึ่งเป็นการอ้างแทนคนแบบที่ D2 ห้าม"""
    with pytest.raises(PrecheckError, match="timezone"):
        mod._parse_reviewed_at("2026-08-04T13:30:00")


def test_reviewed_at_rejects_non_iso() -> None:
    with pytest.raises(PrecheckError, match="ISO-8601"):
        mod._parse_reviewed_at("4 ส.ค. 2026")


def test_reviewed_at_accepts_iso_with_offset() -> None:
    value = mod._parse_reviewed_at("2026-08-04T13:30:00+07:00")
    assert value.tzinfo is not None


def test_reviewed_at_has_no_default_of_now() -> None:
    """ล็อกว่าไม่มีใครใส่ค่า default เป็นเวลาปัจจุบันให้ `--reviewed-at` ในอนาคต —
    เวลาที่คนตรวจกับเวลาที่รันสคริปต์เป็นคนละเวลากันได้มาก การเดาให้ = กรอกแทนคน"""
    source = ast.unparse(ast.parse(inspect.getsource(mod.main)))
    for token in ("now(", "today(", "utcnow("):
        assert token not in source


def test_commit_requires_reviewer_identity() -> None:
    """D1 — `--commit` ต้องมีทั้ง --reviewed-by และ --reviewed-at เสมอ"""
    source = inspect.getsource(mod.main)
    assert "--commit ต้องระบุ --reviewed-by" in source
    assert "--commit ต้องระบุ --reviewed-at" in source


# --- D2 + poster-database §3: ห้ามแตะ needs_review / status ---


def _assigned_poster_attributes() -> set[str]:
    """สแกน AST ของสคริปต์หา `poster.<attr> = ...` ทุกจุด — ใช้ AST ไม่ใช่ regex
    เพราะ assignment อาจข้ามบรรทัดหรืออยู่ใน branch ที่ grep อ่านผิดได้"""
    tree = ast.parse(inspect.getsource(mod))
    names: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        for target in node.targets:
            if (
                isinstance(target, ast.Attribute)
                and isinstance(target.value, ast.Name)
                and target.value.id == "poster"
            ):
                names.add(target.attr)
    return names


def test_script_writes_only_release_date_columns_of_poster() -> None:
    """ล็อกว่าสคริปต์แตะได้แค่สองคอลัมน์นี้ — ถ้ามีใครเพิ่ม `poster.needs_review = ...`
    หรือ `poster.status = ...` เข้ามา test นี้ต้องแดงทันที (ADR-0010 D2 ห้ามพลิก
    needs_review · poster-database §3 ห้าม import เขียนทับ status)"""
    assert _assigned_poster_attributes() == {"release_date_text", "release_date"}


def test_script_never_mentions_needs_review() -> None:
    tree = ast.parse(inspect.getsource(mod))
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute):
            assert node.attr != "needs_review"


# --- D7: guard ปลายทาง ---


def test_dev_target_accepts_localhost() -> None:
    label = assert_target_database(
        "postgresql+asyncpg://u:p@localhost:5432/poster_nung_db", "dev"
    )
    assert label == "localhost/poster_nung_db"


def test_dev_target_rejects_remote_host() -> None:
    with pytest.raises(PrecheckError, match="ไม่ใช่เครื่องนี้"):
        assert_target_database(
            "postgresql+asyncpg://u:p@10.0.0.5:5432/poster_nung_db", "dev"
        )


def test_dev_target_rejects_sit_database_name() -> None:
    with pytest.raises(PrecheckError, match="sit"):
        assert_target_database(
            "postgresql+asyncpg://u:p@localhost:5432/poster_nung_sit", "dev"
        )


@pytest.mark.parametrize("name", ["poster_nung_prod", "poster_nung_uat", "app_stage"])
def test_production_like_names_rejected_for_every_target(name: str) -> None:
    """ADR-0010 D7 — production ไม่มี target ให้เลือก และต่อให้ url ชี้ไปก็ถูกปฏิเสธ
    ที่ guard นี้อีกชั้น ไม่ว่าจะสั่ง target ไหน"""
    for target in ("dev", "sit"):
        with pytest.raises(PrecheckError):
            assert_target_database(
                f"postgresql+asyncpg://u:p@localhost:5432/{name}", target
            )


def test_no_production_target_option_exists() -> None:
    """อ่านจาก argparse จริง — ต้องไม่มีทางเลือก production/uat ให้เลือกได้เลย"""
    tree = ast.parse(inspect.getsource(mod.main))
    choices: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.keyword) and node.arg == "choices":
            for elt in getattr(node.value, "elts", []):
                if isinstance(elt, ast.Constant):
                    choices.add(str(elt.value))
    assert choices == {"dev", "sit"}


# --- D5: ใบงานแยกจากหลักฐานดิบของ AI ---


def _path_like_constants(module: object) -> set[str]:
    """เก็บ string constant ที่ถูกใช้ "เป็น path" จริง ๆ — คือตัวที่อยู่ใน
    `<something> / "x"` หรือถูกส่งเข้า `Path(...)` / `open(...)`

    จงใจไม่ grep ทั้งไฟล์ เพราะชื่อ `ai-suggestions.csv` **ต้อง**ปรากฏในข้อความ error
    ที่อธิบายกับคนรันว่าใบงานเป็นคนละไฟล์กับผลของ AI (D5) — การพูดถึงในข้อความไม่ใช่
    การอ่านไฟล์ เทสต้องแยกสองอย่างนี้ออกจากกันให้ได้
    """
    tree = ast.parse(Path(inspect.getfile(module)).read_text(encoding="utf-8"))  # type: ignore[arg-type]
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
            for side in (node.left, node.right):
                if isinstance(side, ast.Constant) and isinstance(side.value, str):
                    found.add(side.value)
        elif isinstance(node, ast.Call):
            name = (
                node.func.id
                if isinstance(node.func, ast.Name)
                else getattr(node.func, "attr", "")
            )
            if name in {"Path", "open", "read_text"}:
                for arg in node.args:
                    if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                        found.add(arg.value)
    return found


def test_applier_never_uses_the_ai_output_as_a_file_path() -> None:
    """ADR-0010 D5 — `ai-suggestions.csv` คือหลักฐานดิบ ตัว apply ห้ามแตะ
    · ตรวจที่ "ถูกใช้เป็น path ไหม" ไม่ใช่ "ชื่อโผล่ในไฟล์ไหม" (ดู docstring ข้างบน)"""
    paths = _path_like_constants(mod)
    assert not any("ai-suggestions" in p for p in paths), paths


def test_default_sheet_file_is_not_the_ai_output() -> None:
    assert mod.DEFAULT_SIGNOFF_CSV.name != "ai-suggestions.csv"
