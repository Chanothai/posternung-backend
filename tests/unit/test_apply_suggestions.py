"""Unit tests ของ `scripts/seed/apply_suggestions.py` — ล็อกกฎ D1–D7 ของ ADR-0010

ไม่ต่อ DB จริง — ทุก test ทำกับฟังก์ชัน pure (`parse_signoff_rows`, `plan_writes`,
`assert_target_database`) ซึ่งรับสถานะเข้ามาแทนการ query เอง ตาม ship-backend-change §3
(เลี่ยง fixture ที่ไม่จำเป็น)
"""

from __future__ import annotations

import ast
import inspect
import uuid
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

from scripts.seed import apply_suggestions as mod
from scripts.seed.apply_suggestions import (
    ALLOWED_FIELDS,
    Action,
    PrecheckError,
    SignoffRow,
    assert_target_database,
    parse_signoff_rows,
    plan_writes,
)

TZ = timezone(timedelta(hours=7))
PID = uuid.UUID("11111111-1111-1111-1111-111111111111")


def _raw(**over: str) -> dict[str, str]:
    row = {
        "poster_uuid": str(PID),
        "field": "release_date_text",
        "value": "20/7/2023",
        "reviewed_by": "chanothai",
        "reviewed_at": "2026-08-04T13:30:00+07:00",
    }
    row.update(over)
    return row


def _row(**over: object) -> SignoffRow:
    base = {
        "poster_uuid": PID,
        "field": "release_date_text",
        "value": "20/7/2023",
        "reviewed_by": "chanothai",
        "reviewed_at": datetime(2026, 8, 4, 13, 30, tzinfo=TZ),
    }
    base.update(over)
    return SignoffRow(**base)  # type: ignore[arg-type]


# --- D4: allowlist ---


def test_allowlist_has_exactly_release_date_text() -> None:
    """ล็อก allowlist ไว้ตรง ๆ — การขยายฟิลด์คือการแก้มติ ADR-0010 D4 ต้องผ่าน ADR
    ก่อน ไม่ใช่แก้ค่าคงที่เงียบ ๆ แล้ว test เดิมยังเขียว"""
    assert ALLOWED_FIELDS == {"release_date_text"}


def test_field_outside_allowlist_rejects_whole_file() -> None:
    """copyright_year อยู่ใน CSV ของ AI แต่ไม่อยู่ใน allowlist รอบแรก (confidence low
    102/116) — ต้องปฏิเสธ ไม่ใช่ข้ามแถวนั้นเงียบ ๆ"""
    with pytest.raises(PrecheckError, match="allowlist"):
        parse_signoff_rows([_raw(field="copyright_year", value="1999")])


def test_release_date_itself_is_not_accepted_from_file() -> None:
    """`release_date` เป็นค่า derived ที่ parser เท่านั้นเขียนได้ (ADR-0009 D13 ข้อ 2)
    ห้ามรับค่าตรงจากไฟล์แม้จะเป็นชื่อคอลัมน์จริงบน posters"""
    with pytest.raises(PrecheckError, match="allowlist"):
        parse_signoff_rows([_raw(field="release_date", value="2023-07-20")])


# --- D1: ต้องมีชื่อคนตรวจ ---


def test_empty_reviewed_by_rejected() -> None:
    with pytest.raises(PrecheckError, match="reviewed_by"):
        parse_signoff_rows([_raw(reviewed_by="")])


def test_naive_reviewed_at_rejected() -> None:
    """ไม่มี timezone = เครื่องต้องเดาแทนคนตรวจ ซึ่งเป็นการอ้างแทนคนแบบที่ D2 ห้าม"""
    with pytest.raises(PrecheckError, match="timezone"):
        parse_signoff_rows([_raw(reviewed_at="2026-08-04T13:30:00")])


def test_valid_row_parses() -> None:
    rows = parse_signoff_rows([_raw()])
    assert len(rows) == 1
    assert rows[0].poster_uuid == PID
    assert rows[0].reviewed_by == "chanothai"
    assert rows[0].reviewed_at.tzinfo is not None


# --- fail-closed ---


def test_one_bad_row_rejects_every_row_including_good_ones() -> None:
    """fail-closed — ไฟล์ที่มีแถวผิดปนอยู่ต้องไม่ apply อะไรเลย ไม่ใช่ apply เฉพาะ
    แถวที่ถูก · เป็นเส้นทาง UPDATE เส้นแรก การ apply บางส่วนทำให้ตามยากว่าอะไรเข้าไปแล้ว
    """
    good = _raw()
    bad = _raw(poster_uuid="ไม่ใช่ uuid")
    with pytest.raises(PrecheckError):
        parse_signoff_rows([good, bad])


def test_duplicate_poster_and_field_rejected() -> None:
    with pytest.raises(PrecheckError, match="ซ้ำ"):
        parse_signoff_rows([_raw(), _raw(value="March 18")])


def test_empty_value_rejected() -> None:
    with pytest.raises(PrecheckError, match="value ว่าง"):
        parse_signoff_rows([_raw(value="")])


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


def test_rerunning_the_same_file_is_idempotent() -> None:
    """รันรอบแรก APPLY แล้วค่าไม่เป็น NULL อีกต่อไป → รอบสองต้อง SKIP ทุกแถว
    (idempotent โดยโครงสร้าง ไม่ต้องมี state ฝั่งสคริปต์)"""
    row = _row()
    first = plan_writes([row], {PID: None})
    assert first[0].action is Action.APPLY
    after = {PID: row.value}
    second = plan_writes([row], after)
    assert second[0].action is Action.SKIP_ALREADY_SET


# --- D4: release_date มาจาก parser เท่านั้น ---


def test_release_date_derived_only_when_parser_returns_parsed() -> None:
    plans = plan_writes([_row(value="20/7/2023")], {PID: None})
    assert plans[0].parse_status == "PARSED"
    assert plans[0].release_date == date(2023, 7, 20)


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
    plans = plan_writes([_row(value=value)], {PID: None})
    assert plans[0].action is Action.APPLY  # ยังเขียน _text
    assert plans[0].parse_status == status
    assert plans[0].release_date is None  # แต่ไม่เดา DATE


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
    """กันแบบหยาบอีกชั้น — ชื่อคอลัมน์นี้ไม่ควรโผล่ในโค้ดที่รันจริงเลย
    (ยอมให้อยู่ใน docstring/comment ที่อธิบายว่า *ไม่* แตะ)"""
    tree = ast.parse(inspect.getsource(mod))
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute):
            assert node.attr != "needs_review"
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            continue  # docstring/ข้อความรายงาน — อธิบายว่าไม่แตะ ไม่ใช่การแตะ


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
    source = inspect.getsource(mod.main)
    tree = ast.parse(source)
    choices: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.keyword) and node.arg == "choices":
            for elt in getattr(node.value, "elts", []):
                if isinstance(elt, ast.Constant):
                    choices.add(str(elt.value))
    assert choices == {"dev", "sit"}


# --- D5: ไฟล์เซ็นรับแยกจากหลักฐานดิบของ AI ---


def test_default_signoff_file_is_not_the_ai_output() -> None:
    """ADR-0010 D5 — ไฟล์ที่ AI ผลิตคือหลักฐานดิบ ห้ามอ่าน/เขียนทับ"""
    assert mod.DEFAULT_SIGNOFF_CSV.name != "ai-suggestions.csv"
    assert "signoff" in mod.DEFAULT_SIGNOFF_CSV.name


def _path_like_constants() -> set[str]:
    """เก็บ string constant ที่ถูกใช้ "เป็น path" จริง ๆ เท่านั้น — คือตัวที่อยู่ใน
    `<something> / "x"` หรือถูกส่งเข้า `Path(...)` / `open(...)`

    จงใจไม่ใช้ grep ทั้งไฟล์ เพราะชื่อ `ai-suggestions.csv` **ต้อง**ปรากฏในข้อความ
    error ที่อธิบายกับคนรันว่าไฟล์เซ็นรับเป็นคนละไฟล์กับผลของ AI (D5) — การพูดถึง
    ในข้อความไม่ใช่การอ่านไฟล์ เทสต้องแยกสองอย่างนี้ออกจากกันให้ได้
    """
    tree = ast.parse(Path(inspect.getfile(mod)).read_text(encoding="utf-8"))
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


def test_script_never_uses_the_ai_output_as_a_file_path() -> None:
    """ADR-0010 D5 — `ai-suggestions.csv` คือหลักฐานดิบ สคริปต์นี้ห้ามอ่านหรือเขียนทับ
    · ตรวจที่ "ถูกใช้เป็น path ไหม" ไม่ใช่ "ชื่อโผล่ในไฟล์ไหม" (ดู docstring ข้างบน)"""
    paths = _path_like_constants()
    assert not any("ai-suggestions" in p for p in paths), paths
