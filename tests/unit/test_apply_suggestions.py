"""Unit tests ของ `scripts/seed/apply_suggestions.py` — ล็อกกฎ D1–D7 ของ ADR-0010

ไม่ต่อ DB จริง — ทุก test ทำกับฟังก์ชัน pure (`parse_review_rows`, `plan_writes`,
`assert_target_database`) ซึ่งรับสถานะเข้ามาแทนการ query เอง ตาม ship-backend-change §3
(เลี่ยง fixture ที่ไม่จำเป็น)
"""

from __future__ import annotations

import ast
import inspect
import sys
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
    UNPARSEABLE_URL_LABEL,
    Action,
    PrecheckError,
    ReviewRow,
    Verdict,
    _url_label,
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


# กฎรูปแบบของ `--reviewed-at` และด่านปฏิเสธเวลาอนาคตอยู่ที่ `scripts/seed/_shared.py`
# แล้ว — เทสของมันอยู่ที่ `test_seed_lane_shared_rules.py` ซึ่งครอบทั้งสามเส้นพร้อมกัน


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
    """🔴 ‹แก้ critic รอบ 1 L-5 — ถ้อยคำเดิมเขียนว่า "production ไม่มี target ให้เลือก"
    ซึ่งเท็จแล้วตั้งแต่ ADR-0015 Amendment 3 (A3-D1)› ADR-0010 D7 — hint ชื่อ db ที่ดู
    เป็น env จริง (`prod`/`uat`/`stage`) ยังถูกปฏิเสธบน **dev/sit** เหมือนเดิมทุกตัวอักษร
    (ชั้นนี้ข้าม hint check เฉพาะตอน `target == "production"` เท่านั้น — A3-D2)"""
    for target in ("dev", "sit"):
        with pytest.raises(PrecheckError):
            assert_target_database(
                f"postgresql+asyncpg://u:p@localhost:5432/{name}", target
            )


@pytest.mark.parametrize("name", ["poster_nung_sit", "poster_nung_prod"])
def test_production_target_does_not_get_a_free_pass_from_a_db_name_that_looks_right(
    monkeypatch, name: str
) -> None:
    """🔴 critic รอบ 1 L-5 — A3-D2 "ข้ามการเช็ค hint ชื่อ" สำหรับ production หมายถึง
    ไม่ใช้ชื่อ db เป็นสัญญาณ**ปฏิเสธ** เท่านั้น — ห้ามอ่านผิดเป็นว่าชื่อ db ที่ *ดูเหมือน*
    ถูกต้อง (มีคำว่า sit/prod ปน) ทำให้ผ่านง่ายขึ้น ไม่มีไฟล์ `.env.production` ที่ตรง
    เป๊ะ = ปฏิเสธเสมอ ไม่ว่าชื่อ db จะสื่ออะไรก็ตาม"""
    _fake_env(monkeypatch, {})  # ไม่มี .env.production เลย
    url = f"postgresql+asyncpg://u:p@db:5432/{name}"
    with pytest.raises(PrecheckError, match="ไม่เจอ"):
        assert_target_database(url, "production")


def test_production_target_does_not_accept_a_url_just_because_its_name_says_sit(
    monkeypatch,
) -> None:
    """🔴 critic รอบ 1 L-5 — url ที่ *ไม่ตรง* กับ `.env.production` ต้องถูกปฏิเสธ แม้ชื่อ
    database ของมันจะมีคำว่า `sit` ปนอยู่ (ซึ่งเป็นสัญญาณที่ layer sit ใช้ แต่ layer
    production ไม่สนใจชื่อเลย — เทียบด้วยสตริง url ทั้งเส้นเท่านั้น)"""
    prod_url = "postgresql+asyncpg://u:p@db:5432/poster_db"
    _fake_env(monkeypatch, {".env.production": {"DATABASE_URL": prod_url}})
    other_but_sit_flavored = "postgresql+asyncpg://u:p@db:5432/poster_nung_db_sit"
    with pytest.raises(PrecheckError, match="ไม่ตรงกับค่าใน"):
        assert_target_database(other_but_sit_flavored, "production")


def test_no_production_target_option_exists() -> None:
    """🔴 ห้ามเปลี่ยน — เส้นที่ 2 (AI suggestion) ไม่มีเหตุให้ apply บน production
    ในรอบนี้ (ADR-0015 A3-D1: `apply_suggestions.main` มี `choices=("dev","sit")`
    literal ของตัวเอง ไม่ผูกกับ `TARGETS` ของ `_production_gate.py`)"""
    tree = ast.parse(inspect.getsource(mod.main))
    choices: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.keyword) and node.arg == "choices":
            for elt in getattr(node.value, "elts", []):
                if isinstance(elt, ast.Constant):
                    choices.add(str(elt.value))
    assert choices == {"dev", "sit"}


# --- ADR-0015 Amendment 3 (INF-44 A3-D2) — assert_target_database() ชั้น ① สาขา production ---


def _fake_env(monkeypatch, files: dict[str, dict[str, str]]) -> None:
    def fake(path) -> dict[str, str]:
        return files.get(getattr(path, "name", str(path)), {})

    monkeypatch.setattr(mod, "_parse_env_file", fake)


PROD_URL = "postgresql+asyncpg://u:p@db:5432/poster_db"


def test_production_target_accepts_only_the_url_from_env_production(
    monkeypatch,
) -> None:
    _fake_env(monkeypatch, {".env.production": {"DATABASE_URL": PROD_URL}})
    label = assert_target_database(PROD_URL, "production")
    assert "poster_db" in label


def test_production_target_rejects_a_url_that_differs_from_env_production(
    monkeypatch,
) -> None:
    _fake_env(monkeypatch, {".env.production": {"DATABASE_URL": PROD_URL}})
    other = "postgresql+asyncpg://u:p@db:5432/other_db"
    with pytest.raises(PrecheckError, match="ไม่ตรงกับค่าใน"):
        assert_target_database(other, "production")


def test_production_target_refuses_when_env_production_file_is_missing(
    monkeypatch,
) -> None:
    """A3-D2 — ไม่มีทางผ่อนแบบเดาจากชื่อ database ต่างจาก sit ของ ADR-0010 D7"""
    _fake_env(monkeypatch, {})
    with pytest.raises(PrecheckError, match="ไม่เจอ"):
        assert_target_database(PROD_URL, "production")


def test_production_target_still_rejects_url_matching_env_uat(monkeypatch) -> None:
    _fake_env(monkeypatch, {".env.uat": {"DATABASE_URL": PROD_URL}})
    with pytest.raises(PrecheckError, match="uat"):
        assert_target_database(PROD_URL, "production")


def test_dev_still_rejects_a_url_matching_env_production(monkeypatch) -> None:
    """🔴 dev ไม่แตะสักบรรทัด — ยัง *ปฏิเสธ* URL ที่ตรงกับ .env.production เหมือนเดิม
    (สัญญาณเดียวกันกลับด้านตาม target — A3-D2)

    🔴 **ใช้ host=localhost โดยตั้งใจ** — `PROD_URL` (host=`db`) ทำให้ด่าน "dev ต้อง
    เป็น localhost" ยิงก่อนด่าน production-file-match เสมอ ทำให้เทสผ่านได้แม้ด่านหลัง
    ถูกถอดออกไปแล้ว (มุมบอดที่เจอตอนรัน mutation จริง — เก็บ URL เดิมไว้ในเทสที่ไม่ได้
    ตั้งใจแยกด่านจะพิสูจน์ผิดตัว)
    """
    url = "postgresql+asyncpg://u:p@localhost:5432/poster_db"
    _fake_env(monkeypatch, {".env.production": {"DATABASE_URL": url}})
    with pytest.raises(PrecheckError, match="production"):
        assert_target_database(url, "dev")


def test_sit_still_rejects_a_url_matching_env_production(monkeypatch) -> None:
    """🔴 sit ไม่แตะสักบรรทัด — ยัง *ปฏิเสธ* URL ที่ตรงกับ .env.production เหมือนเดิม

    🔴 **`.env.sit` ต้องตรงกับ url เดียวกันด้วย** ไม่งั้นด่านของ sit เอง (ไม่มี .env.sit
    ที่ตรง) จะปฏิเสธก่อนถึงด่าน production-file-match — แยกด่านให้ขาดจากกันเพื่อให้
    เทสนี้พิสูจน์เฉพาะด่านที่ตั้งใจพิสูจน์จริง ๆ
    """
    url = "postgresql+asyncpg://u:p@localhost:5432/poster_db"
    _fake_env(
        monkeypatch,
        {".env.sit": {"DATABASE_URL": url}, ".env.production": {"DATABASE_URL": url}},
    )
    with pytest.raises(PrecheckError, match="production"):
        assert_target_database(url, "sit")


# --------------------------------------------------------------------------
# INF-51 (BL-167) · ADR-0015 AC-1/AC-2/AC-3 — `_url_label()` เป็นป้ายเดียวของทุก
# lane · M-2 ทาง (ก): รหัสผ่านที่มี `?`/`#` โดยไม่ percent-encode ต้องได้ marker
# เหมือนกับ `/` (ก่อนแก้: `?`/`#` ทำให้ query/fragment กลืน netloc ที่เหลือไปจน
# `db_name` ว่างเปล่า/สะอาด แล้วหลุดตัวกรอง `@:/` เดิมไปได้ทั้งที่ host ที่แยกได้จริง
# คือ**ชื่อผู้ใช้** ไม่ใช่ host จริง — พิสูจน์ตัวเลขจริงไว้ในเทสข้างล่างนี้)
# --------------------------------------------------------------------------

LEAK_USER = "leakuser"
# 🔴 เลือก 4 ตัวนี้เพราะแต่ละตัวพิสูจน์คนละจุด:
#   SLASH_PW    — บั๊กเดิมที่ INF-39 แก้แล้ว (`/` ตัด netloc ก่อน `@`) ยังต้องเป็น marker
#   QUESTION_PW — M-2 (ก): `?` ทำให้ query กลืนเศษ netloc ไป (ช่องโหว่ที่ INF-51 แก้)
#   HASH_PW     — M-2 (ก): เหมือนกันแต่ทาง fragment
#   STAGE_PW    — มี `/` (แยกส่วนไม่ได้เหมือน SLASH_PW) **และ** db_name ที่ได้ยังบังเอิญ
#                 มีคำว่า "stage" ปน ⇒ พิสูจน์ว่า PRODUCTION_DB_HINTS ไม่พิมพ์ `hit`
#                 ("stage") ออกมาเมื่อ url แยกส่วนไม่ได้ (AC-2 · ฆ่า mutant M7)
SLASH_PW = "s3cr3t/xyz"
QUESTION_PW = "ab?cd"
HASH_PW = "ab#cd"
STAGE_PW = "ab/xstagey"
LEAKING_PASSWORDS = (SLASH_PW, QUESTION_PW, HASH_PW, STAGE_PW)


def _url_with_password(password: str, *, host: str = "localhost") -> str:
    return f"postgresql+asyncpg://{LEAK_USER}:{password}@{host}:5432/poster_nung_db"


@pytest.mark.parametrize("password", LEAKING_PASSWORDS)
def test_url_label_returns_the_marker_for_every_leaking_password_shape(
    password: str,
) -> None:
    """AC-1/AC-3 — ทั้ง 4 รูปแบบต้องได้ marker เดียวกัน ไม่ใช่แค่บางรูป

    🔴 ก่อนแก้ M-2: `QUESTION_PW`/`HASH_PW` ทำให้ `parts.hostname` กลายเป็น
    `LEAK_USER` (ชื่อผู้ใช้!) และ `db_name` ว่างเปล่า ⇒ `_url_label()` เดิมคืน
    `"leakuser/"` ตรง ๆ — ยืนยันจริงด้วย python interactive ก่อนเขียนเทสนี้
    (`urlsplit(...).hostname == "leakuser"` เมื่อ password มี `?`/`#`)
    """
    label = _url_label(_url_with_password(password))
    assert label == UNPARSEABLE_URL_LABEL
    assert LEAK_USER not in label


@pytest.mark.parametrize("password", LEAKING_PASSWORDS)
def test_assert_target_database_never_leaks_the_username_for_any_leaking_password(
    password: str,
) -> None:
    """AC-2 — เดินผ่านทางเข้าจริง (`assert_target_database`) ไม่ใช่แค่ `_url_label()`
    ตรง ๆ — เผื่อมีจุดใดใน `assert_target_database()` เอง embed ค่าดิบแซง label"""
    url = _url_with_password(password)
    with pytest.raises(PrecheckError) as exc:
        assert_target_database(url, "dev")
    assert LEAK_USER not in str(exc.value)
    assert password not in str(exc.value)


def test_url_label_positive_control_a_clean_url_keeps_the_real_host_and_db() -> None:
    """positive control (AC-3) — url ที่แยกส่วนได้ปกติต้องไม่โดน marker คลุมไปด้วย
    ไม่งั้นเทสข้างบนจะผ่านได้แม้ `_url_label()` คืน marker เสมอไม่ว่า url จะเป็นอะไร
    (mutant M12)"""
    label = _url_label("postgresql+asyncpg://u:p@localhost:5432/poster_nung_db")
    assert label == "localhost/poster_nung_db"
    assert label != UNPARSEABLE_URL_LABEL


def test_url_label_positive_control_an_unencoded_at_sign_still_parses_cleanly() -> None:
    """positive control (AC-3) — `urlsplit` แยก netloc ที่ `@` ตัว**สุดท้าย** เสมอ ⇒
    รหัสผ่านที่มี `@` โดยไม่ encode ยังหา host/db ได้ปกติ ไม่ใช่ marker (ต่างจาก `/`
    `?` `#` ที่ตัด netloc ตั้งแต่ตัวแรกที่เจอ)"""
    label = _url_label("postgresql+asyncpg://u:ab@cd@localhost:5432/poster_nung_db")
    assert label == "localhost/poster_nung_db"


def test_no_query_string_appears_anywhere_in_the_env_files_this_repo_reads() -> None:
    """AC-3 — บันทึกไว้เป็นเทสไม่ใช่แค่ README: URL ของทุก env ที่ตรวจได้วันนี้ไม่มี
    `?`/`#` ⇒ การที่ query string ที่ถูกกฎหมายจะได้ marker (cosmetic ตาม AC-3) ยังไม่
    เกิดขึ้นจริงกับ env ไหนในโปรเจกต์นี้ตอนนี้"""
    for name in (".env.example",):
        path = Path(__file__).resolve().parents[2] / name
        if not path.is_file():
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip().startswith("DATABASE_URL="):
                assert "?" not in line and "#" not in line.split("=", 1)[1]


# --- PRODUCTION_DB_HINTS branch (message point 1) — ห้ามพิมพ์ `hit` เมื่อ marker ---


def test_production_hint_message_shows_the_hit_word_when_the_url_parses_cleanly() -> (
    None
):
    """ทางปกติ (url แยกส่วนได้) ยังต้องคงพฤติกรรมเดิม — พิมพ์ `hit` ได้ตามปกติ เพราะ
    ไม่ใช่ข้อมูลอ่อนไหว (เป็นคำใน `PRODUCTION_DB_HINTS` เอง ไม่ใช่เศษรหัสผ่าน)"""
    url = "postgresql+asyncpg://u:p@localhost:5432/poster_nung_prod"
    with pytest.raises(PrecheckError, match="'prod'"):
        assert_target_database(url, "dev")


def test_production_hint_message_hides_the_hit_word_when_the_url_is_unparseable() -> (
    None
):
    """🔴 AC-2 · ฆ่า mutant M7 — เมื่อ url แยกส่วนไม่ได้ (`STAGE_PW` มี `/` ทำให้
    db_name บังเอิญมีคำว่า "stage" ปน) ข้อความต้องเป็นข้อความทั่วไป **ไม่พิมพ์คำว่า
    'stage' เลย** แม้มันจะเป็นแค่คำใน `PRODUCTION_DB_HINTS` ก็ตาม — เพราะสิ่งที่ทำให้
    เกิด "hit" ในเคสนี้คือเศษของ db_name ที่แยกส่วนไม่ได้ ไม่ใช่ชื่อ database จริง
    """
    url = _url_with_password(STAGE_PW)
    with pytest.raises(PrecheckError) as exc:
        assert_target_database(url, "dev")
    assert "stage" not in str(exc.value)
    assert "แยกส่วนไม่ได้" in str(exc.value)


# --- host-mismatch branch (message point 2) และ dev+'sit' branch (message point 3) ---


def test_dev_host_mismatch_message_uses_the_label_not_the_raw_host() -> None:
    """ทางปกติยังต้องพิมพ์ host/db จริงได้ (ไม่ใช่ marker) — regression guard คู่กับ
    `test_dev_target_rejects_remote_host` ข้างบนที่เช็คแค่วลีคงที่"""
    with pytest.raises(PrecheckError, match=r"10\.0\.0\.5/poster_nung_db"):
        assert_target_database(
            "postgresql+asyncpg://u:p@10.0.0.5:5432/poster_nung_db", "dev"
        )


@pytest.mark.parametrize("password", [SLASH_PW, QUESTION_PW, HASH_PW])
def test_dev_host_mismatch_message_never_leaks_when_url_is_unparseable(
    password: str,
) -> None:
    """🔴 AC-2 — host ที่แยกได้จริงตอน url พังคือ**ชื่อผู้ใช้** (`urlsplit` เอาไปเป็น
    hostname) ไม่ใช่ host จริง ⇒ ข้อความต้องไม่พิมพ์ host ดิบนั้นออกมาเด็ดขาด
    (ไม่ใช้ STAGE_PW เพราะมันโดนด่าน PRODUCTION_DB_HINTS จับก่อนถึงด่านนี้เสมอ)"""
    url = _url_with_password(password, host="10.0.0.5")
    with pytest.raises(PrecheckError) as exc:
        assert_target_database(url, "dev")
    assert LEAK_USER not in str(exc.value)
    assert "ไม่ใช่เครื่องนี้" in str(exc.value)


def test_dev_sit_named_database_message_still_works_when_the_url_parses_cleanly() -> (
    None
):
    """message point 3 ทางปกติ — regression guard คู่กับเทส unparseable ข้างล่าง"""
    with pytest.raises(PrecheckError, match=r"poster_nung_db_sit"):
        assert_target_database(
            "postgresql+asyncpg://u:p@localhost:5432/poster_nung_db_sit", "dev"
        )


def test_dev_sit_named_database_message_never_leaks_when_url_is_unparseable() -> None:
    """🔴 message point 3 — `--target dev` + host ยัง `localhost` ปกติ (ผ่านด่านแรก)
    แต่ path ที่เหลือแยกส่วนไม่ได้ (มี `@` ปน) และบังเอิญมีคำว่า 'sit' ปนอยู่ด้วย —
    ก่อนแก้ M6 ข้อความจุดนี้พิมพ์ `db_name!r}` ทั้งก้อนดิบ ๆ ซึ่งรวมเศษ `@junk` ไปด้วย

    🔴 **ต้องยืนยันว่าไม่มี `@`/`junk` หลุดออกมา ไม่ใช่แค่ match วลีคงที่** — วลี
    `"สั่ง target ผิด"` ปรากฏอยู่ใน **ทั้งข้อความ marker และข้อความดิบที่รั่ว** เหมือนกัน
    ⇒ ยืนยันด้วยวลีอย่างเดียวจับมิวเทชันนี้ไม่ได้เลย (พบตอนรัน mutation testing จริง —
    เทสรุ่นแรกของจุดนี้ผ่านฉลุยแม้ถอดด่าน marker ออกไปทั้งก้อน)
    """
    url = "postgresql+asyncpg://u:p@localhost:5432/poster_nung_sit_leakuser@junk"
    with pytest.raises(PrecheckError) as exc:
        assert_target_database(url, "dev")
    assert "สั่ง target ผิด" in str(exc.value)
    assert "@junk" not in str(exc.value)
    assert "แยกส่วนไม่ได้" in str(exc.value)


# --- sit-no-file branch (message point 4) ---


@pytest.mark.parametrize("password", [SLASH_PW, QUESTION_PW, HASH_PW])
def test_sit_no_file_message_never_leaks_when_url_is_unparseable(
    password: str, monkeypatch
) -> None:
    """message point 4 — `--target sit`, ไม่มี `.env.sit`, url พัง และชื่อ db (เท่าที่
    แยกได้) ไม่มีคำว่า 'sit' — ต้องได้ marker ในข้อความ ไม่ใช่ db_name ดิบ"""
    _fake_env(monkeypatch, {})  # ไม่มี .env.sit เลย
    url = _url_with_password(password)
    with pytest.raises(PrecheckError, match="ยืนยันปลายทางไม่ได้"):
        assert_target_database(url, "sit")
    # ยืนยันว่าไม่มี username หลุดออกมาด้วย (ข้อความอ้าง label ไม่ใช่ db_name ดิบ)
    with pytest.raises(PrecheckError) as exc:
        assert_target_database(url, "sit")
    assert LEAK_USER not in str(exc.value)


# --- (ก) เส้นทางสำเร็จ — url แยกส่วนไม่ได้แต่ตรงกับ .env.sit เป๊ะ (string เท่ากัน) ---


@pytest.mark.parametrize("password", [SLASH_PW, QUESTION_PW, HASH_PW])
def test_sit_success_path_still_returns_the_marker_label_when_url_matches_env_sit(
    password: str, monkeypatch
) -> None:
    """🔴 AC-4 เส้นทาง (ก) — `assert_target_database()` เทียบ **สตริงทั้งเส้นเท่ากัน**
    ไม่ได้ parse ใหม่ ⇒ url ที่แยกส่วนไม่ได้แต่ตรงกับ `.env.sit` เป๊ะ (คนละสภาพแวดล้อม
    เดียวกัน แค่บังเอิญรหัสผ่านมีอักขระพิเศษ) ต้องผ่านด่านได้เหมือนเดิม แค่ป้ายที่คืน
    มาเป็น marker แทนที่จะเป็น host/db จริง (ไม่ใช้ STAGE_PW — โดน PRODUCTION_DB_HINTS
    ปฏิเสธก่อนเสมอไม่ว่า target ไหน)"""
    url = _url_with_password(password)
    _fake_env(monkeypatch, {".env.sit": {"DATABASE_URL": url}})
    label = assert_target_database(url, "sit")
    assert label == UNPARSEABLE_URL_LABEL


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


# --------------------------------------------------------------------------
# INF-51 (BL-167) มติ 2 — driver error ตอนต่อ DB ไม่ผ่านต้องไม่พิมพ์ credential ดิบ
# (ก่อนหน้านี้ `main()` ของเส้นนี้ไม่มีการจับ error รอบ `asyncio.run(run(...))` เลย
# นอกจาก `PrecheckError`)
# --------------------------------------------------------------------------


def _argv(*extra: str) -> list[str]:
    return ["apply_suggestions.py", *extra]


def test_network_error_on_connect_is_reported_without_a_traceback(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    async def _raise_os_error(_args, _target_label) -> int:
        raise OSError("Connection refused")

    monkeypatch.setattr(mod, "_load_env", lambda _target: None)
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://u:p@localhost/db")
    monkeypatch.setattr(mod, "run", _raise_os_error)
    monkeypatch.setattr(sys, "argv", _argv())

    rc = mod.main()

    assert rc == 1
    assert "Connection refused" in capsys.readouterr().err


def test_postgres_driver_error_on_connect_never_echoes_credentials(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from asyncpg.exceptions import PostgresError

    async def _raise_postgres_error(_args, _target_label) -> int:
        raise PostgresError('password authentication failed for user "leaked_user_abc"')

    monkeypatch.setattr(mod, "_load_env", lambda _target: None)
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://u:p@localhost/db")
    monkeypatch.setattr(mod, "run", _raise_postgres_error)
    monkeypatch.setattr(sys, "argv", _argv())

    rc = mod.main()
    combined = capsys.readouterr()
    text = combined.out + combined.err

    assert rc == 1
    assert "leaked_user_abc" not in text
    assert "PostgresError" in text


def test_sqlalchemy_wrapped_error_never_echoes_credentials(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from sqlalchemy.exc import SQLAlchemyError

    async def _raise_sqlalchemy_error(_args, _target_label) -> int:
        raise SQLAlchemyError(
            "(asyncpg.exceptions.InvalidPasswordError) password authentication "
            'failed for user "leaked_user_abc"'
        )

    monkeypatch.setattr(mod, "_load_env", lambda _target: None)
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://u:p@localhost/db")
    monkeypatch.setattr(mod, "run", _raise_sqlalchemy_error)
    monkeypatch.setattr(sys, "argv", _argv())

    rc = mod.main()
    combined = capsys.readouterr()
    text = combined.out + combined.err

    assert rc == 1
    assert "leaked_user_abc" not in text
    assert "SQLAlchemyError" in text
