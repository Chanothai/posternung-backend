"""Unit tests ของ `scripts/seed/reference_entry.py` — ADR-0014 Amendment 3 (INF-13)

ไม่ต่อ DB จริง — ส่วนใหญ่ทำกับฟังก์ชัน pure (`parse_rows`, `plan_writes`,
`derive_status`, `validate_reference_url`, `audit_entries`, `_report_counts`)
ซึ่งรับสถานะเข้ามาแทนการ query เอง ตาม ship-backend-change §3

🔴 **`run()` มีเทสของตัวเองผ่าน session ปลอม** (§`run()` ท้ายไฟล์) — ไม่ใช่เพราะอยาก
ครอบ coverage แต่เพราะ **closed-world ที่ระดับซอร์สจับชื่อ attribute ที่ประกอบขึ้น
ตอนรันไม่ได้เลย** (`setattr(poster, "a" + "b", …)`) และการเขียนที่เพิ่ม *นอก* ลูป
ของ `field_writes` ก็ไม่มี fail-closed ตัวไหนกั้น · `code-critic` พิสูจน์ทั้งสองช่อง
ไว้แล้วเมื่อ 2026-08-08

`derive_status()` import `app.models.enums` ข้างในตัวเอง — ใต้ pytest env ครบอยู่แล้ว
จึงเรียกได้ตรง ๆ (เหตุผลที่ไม่ import บนหัวไฟล์อยู่ใน docstring ของฟังก์ชันนั้น)
"""

from __future__ import annotations

import argparse
import ast
import csv
import inspect
import re
import sys
import uuid
from datetime import datetime
from pathlib import Path

import pytest

from app.models.enums import VerificationStatus
from app.models.poster import Poster
from scripts.seed import reference_entry as mod
from scripts.seed.apply_suggestions import ALLOWED_FIELDS as SUGGEST_ALLOWED_FIELDS
from scripts.seed.manual_entry import ALLOWED_FIELDS as MANUAL_ALLOWED_FIELDS
from scripts.seed.reference_entry import (
    DERIVED_FIELDS,
    HUMAN_FIELDS,
    NULL_ONLY_FIELDS,
    REFERENCE_SHEET_COLUMNS,
    REQUIRED_COLUMNS,
    WRITABLE_FIELDS,
    AuditEntry,
    PosterState,
    PrecheckError,
    ReferenceRow,
    RowAction,
    _report_counts,
    assert_not_in_the_future,
    assert_own_sheet,
    assert_schema_ready,
    audit_entries,
    derive_status,
    duplicate_reference_urls,
    parse_rows,
    plan_writes,
    planned_field_counts,
    read_sheet,
    validate_reference_url,
)

PID = uuid.UUID("11111111-1111-1111-1111-111111111111")
PID2 = uuid.UUID("22222222-2222-2222-2222-222222222222")
PID3 = uuid.UUID("33333333-3333-3333-3333-333333333333")
REVIEWED_AT = datetime.fromisoformat("2026-08-08T20:00:00+07:00")

# ลิงก์จริงจากใบงานเส้นที่ 3 — **`http://` ไม่ใช่ `https://`** ทั้ง 108 อัน
URL = "http://www.impawards.com/2021/no_time_to_die_ver15.html"
URL2 = "http://www.impawards.com/2023/antman_and_the_wasp_quantumania_ver4.html"


def _raw(**over: str) -> dict[str, str]:
    row = {
        "poster_uuid": str(PID),
        "title": "Some Poster",
        "image_url": "https://example.invalid/a.jpg",
        "previous_note": "",
        "reference_url": "",
        "reference_note": "",
    }
    row.update(over)
    return row


def _row(**over: object) -> ReferenceRow:
    base: dict[str, object] = {
        "poster_uuid": PID,
        "reference_url": URL,
        "reference_note": "",
        "lineno": 2,
    }
    base.update(over)
    return ReferenceRow(**base)  # type: ignore[arg-type]


def _state(**over: object) -> PosterState:
    values: dict[str, object] = {name: None for name in NULL_ONLY_FIELDS}
    values.update(over)
    return PosterState(values=values)


# --------------------------------------------------------------------------
# AC-7 — เทสระดับ AST/closed-world ที่ล็อกว่าเครื่องเขียนอะไรได้บ้าง
# --------------------------------------------------------------------------

POSTER_COLUMNS = set(Poster.__table__.columns.keys())


def _names_the_module_mentions(module) -> set[str]:
    """ชื่อทุกตัวที่โมดูลเอ่ยถึงในซอร์ส — **string literal และ `<obj>.attr`**

    🔴 `ast.Attribute.attr` เป็น `str` ธรรมดา **ไม่ใช่ `ast.Constant`** — การสแกนหา
    เฉพาะ literal จึงมองไม่เห็น `poster.needs_review = False` เลยแม้แต่น้อย
    (พิสูจน์แล้วโดย `code-critic` 2026-08-08: เทสรุ่นก่อนเขียวกับ mutation แบบนั้น
    ทั้งที่ docstring ของมันเองยกเคสนั้นมาเป็นตัวอย่างว่าจะจับได้)
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
    """🔴 closed-world ระดับซอร์ส — ชั้นที่ 1 จาก 2

    **จับได้:** ชื่อคอลัมน์ที่เขียนตรง ๆ ไม่ว่าจะมาทาง `poster.<col> = …` หรือทาง
    string literal ในทูเพิล/dict/`setattr` ใด ๆ

    🔴 **จับไม่ได้: ชื่อที่ประกอบขึ้นตอนรัน** — `setattr(poster, "a" + "b", …)` ·
    f-string · `"_".join([...])` · `REFERENCE_SHEET_COLUMNS[3]`
    ชั้นที่ปิดช่องนั้นคือ `test_run_writes_nothing_outside_the_writable_set`
    ซึ่งดูที่ *attribute ที่ถูกเซ็ตจริงตอนรัน* ไม่ใช่ที่ซอร์ส — **ห้ามลบตัวใดตัวหนึ่ง
    แล้วอ้างว่าอีกตัวครอบแทนได้**

    สองชื่อที่ติดมาโดยไม่ใช่การเขียน — พิสูจน์ด้วยชั้นที่ 2 ว่าไม่เคยถูกเซ็ต:
    · `title` = คอลัมน์ที่ *ใบงานแสดงให้คนอ่าน* (อยู่ใน `REFERENCE_SHEET_COLUMNS`)
    · `id` = `Poster.id` ที่ `_load_state()` ใช้เป็นคีย์ตอน **อ่าน**
    """
    named = _names_the_module_mentions(mod) & POSTER_COLUMNS
    assert named == {*WRITABLE_FIELDS, "title", "id"}


# ชื่อฟังก์ชันที่ถือว่า "อ่านนาฬิกา" — เทียบแบบ **substring** โดยตั้งใจ ให้ครอบ
# `datetime.now` · `datetime.utcnow` · `date.today` · และ wrapper ที่ตั้งชื่อเลี่ยง
# อย่าง `_now_iso()` / `get_now()` ด้วย (เทสรุ่นก่อนเป็นการแบน substring บนซอร์ส
# ทั้งโมดูล — เก็บความไวระดับเดียวกันไว้ แต่เปลี่ยนจาก "ห้ามมี" เป็น "มีได้ที่เดียว")
CLOCK_TOKENS = ("now", "today", "utcnow")
# ชื่อด่านที่เป็น **ที่เดียว** ที่รับเวลาปัจจุบันได้
CLOCK_SINK = "assert_not_in_the_future"


def _callee_name(node: ast.Call) -> str:
    func = node.func
    if isinstance(func, ast.Attribute):
        return func.attr
    if isinstance(func, ast.Name):
        return func.id
    return ""


def _is_clock_call(node: ast.AST) -> bool:
    return isinstance(node, ast.Call) and any(
        tok in _callee_name(node).lower() for tok in CLOCK_TOKENS
    )


def _module_tree(module) -> ast.Module:
    return ast.parse(inspect.getsource(module))


def test_reviewed_at_can_only_ever_be_the_value_the_human_typed() -> None:
    """🔴 **นี่คือกฎจริงของ ADR-0010 D5** — `args.reviewed_at` ต้องมาจาก
    `_parse_reviewed_at(<สิ่งที่คนพิมพ์>)` เท่านั้น ห้ามเป็นนิพจน์เวลาปัจจุบัน
    ไม่ว่าจะทางไหน (เวลาที่คนตัดสิน ≠ เวลาที่รันสคริปต์ · การเดาให้ = กรอกแทนคน)

    เทสรุ่นก่อนแบนโทเคน `now(`/`today(`/`utcnow(` ทั้งโมดูล ซึ่งเป็นแค่ **proxy หยาบ**
    ของกฎข้อนี้ — และเป็น proxy ที่พังทันทีที่โมดูลต้องรู้เวลาปัจจุบันเพื่อ *ปฏิเสธ*
    ค่าที่อยู่ในอนาคต · ตัวนี้ตรวจกฎตรง ๆ แทน ส่วน "นาฬิกาอยู่ที่เดียว" ไปอยู่ที่
    `test_the_clock_is_read_in_exactly_one_place_and_only_to_feed_the_gate`

    🔴 **ห้ามลบตัวใดตัวหนึ่งแล้วอ้างว่าอีกตัวครอบแทนได้** — ตัวนี้จับ "ค่ามาจากไหน"
    อีกตัวจับ "นาฬิกาไปโผล่ที่ไหนได้บ้าง" คนละคำถาม
    """
    tree = _module_tree(mod)
    assigned: list[ast.expr] = []
    for node in ast.walk(tree):
        targets: list[ast.expr] = []
        if isinstance(node, ast.Assign):
            targets = list(node.targets)
        elif isinstance(node, (ast.AnnAssign, ast.AugAssign)):
            targets = [node.target]
        else:
            continue
        if node.value is None:  # `x: T` ที่ไม่มีค่า
            continue
        for target in targets:
            if isinstance(target, ast.Attribute) and target.attr == "reviewed_at":
                assigned.append(node.value)

    assert (
        assigned
    ), "ไม่พบการ assign `args.reviewed_at` เลย — ด่าน parse หายไปหรือเปล่า"
    for value in assigned:
        rendered = ast.unparse(value)
        assert isinstance(value, ast.Call), rendered
        assert _callee_name(value) == "_parse_reviewed_at", rendered

    # ปิดช่องเขียนแบบ dynamic ที่การไล่ `ast.Assign` มองไม่เห็น
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and _callee_name(node) == "setattr":
            literals = [
                a.value
                for a in node.args
                if isinstance(a, ast.Constant) and isinstance(a.value, str)
            ]
            assert "reviewed_at" not in literals, ast.unparse(node)


def test_the_clock_is_read_in_exactly_one_place_and_only_to_feed_the_gate() -> None:
    """🔴 นาฬิกาปรากฏได้ **ที่เดียว**: เป็น argument ที่ส่งให้ด่านปฏิเสธ

    อ่านนาฬิกาเพื่อ **ปฏิเสธ** เป็นคนละเรื่องกับอ่านเพื่อ **จ่ายค่า** — D5 ห้ามอย่างหลัง
    เท่านั้น · การบังคับให้นาฬิกาโผล่ได้ตำแหน่งเดียวทำให้ "อย่างหลัง" ไม่มีที่ยืน
    โดยไม่ต้องแบนคำว่า `now(` ทั้งโมดูลอีกต่อไป

    🔴 ต้องเป็น argument **โดยตรง** — `now=datetime.now(tz) - timedelta(days=1)`
    ทำให้ id ของ call ไม่อยู่ในเซตที่อนุญาต จึงแดง
    """
    tree = _module_tree(mod)
    clock_calls = [n for n in ast.walk(tree) if _is_clock_call(n)]
    allowed: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and _callee_name(node) == CLOCK_SINK:
            allowed.update(id(a) for a in node.args)
            allowed.update(id(k.value) for k in node.keywords)

    rendered = [ast.unparse(n) for n in clock_calls]
    assert len(clock_calls) == 1, rendered
    assert {id(n) for n in clock_calls} <= allowed, rendered
    # นาฬิกาที่ไม่ระบุ timezone จะได้ค่า naive แล้วการเทียบใน `assert_not_in_the_future`
    # จะระเบิดเป็น TypeError ดิบตอนรัน — ที่นี่คือที่เดียวที่ดักได้ก่อนถึงมือคนใช้
    assert clock_calls[0].args or clock_calls[0].keywords, rendered[0]


TIMESTAMP = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}")


def test_no_example_in_this_lane_is_a_timestamp_someone_can_copy_and_run() -> None:
    """🔴 เกิดจริง 2026-08-08 — docstring ของโมดูลนี้เขียนตัวอย่าง `--reviewed-at`
    เป็นเวลาจริงที่ก๊อปได้ ผู้ใช้ก๊อปมาทั้งบรรทัด แล้ว `reviewed_at` ของ **232 แถว**
    ลงเป็นเวลาในอนาคต 3.5 ชั่วโมง

    ด่าน `assert_not_in_the_future` กันไม่ให้ค่าแบบนั้นลง DB ได้ แต่กันไม่ให้ **ตัวอย่าง
    ที่ก๊อปแล้วดูเหมือนใช้ได้** กลับมาอยู่ในเอกสารไม่ได้ — ตัวนี้ทำหน้าที่นั้น
    """
    from scripts.seed import make_reference_sheet

    for module in (mod, make_reference_sheet):
        found = TIMESTAMP.findall(inspect.getsource(module))
        assert not found, f"{module.__name__} มีเวลาจริงที่ก๊อปแล้วรันได้: {found}"


def test_the_ai_paths_still_cannot_write_any_of_these_three_fields() -> None:
    """ADR-0014 D7 — AI ห้ามเป็น writer ของฟิลด์ชุดนี้ตลอดกาล · เส้นที่ 2 (AI เสนอ
    คนเซ็นรับ) และเส้นที่ 3 (คนดูใบจริง) ต้องไม่มีทางแตะมันเลยแม้แต่ช่องเดียว"""
    for allowlist in (SUGGEST_ALLOWED_FIELDS, MANUAL_ALLOWED_FIELDS):
        assert set(allowlist).isdisjoint(WRITABLE_FIELDS)


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


def test_parse_rows_reads_exactly_the_required_columns_and_nothing_else() -> None:
    """🔴 ADR-0014 D28 — `previous_note` เป็นช่องช่วยจำของคน ถ้าสคริปต์อ่านมันจะกลาย
    เป็น parser ตัวที่สองที่เดาว่าท่อนไหนคือ URL ท่อนไหนคือเหตุผล (AC-5 ห้าม) ·
    แถวที่คนเขียนว่า *ไม่ใช่โปสเตอร์* (กรอบไฟ · BL-82) จะกลายเป็นผลการตรวจเงียบ ๆ

    🔴 **closed-world ที่ runtime ไม่ใช่การไล่ literal** — การไล่ literal ปล่อย
    `raw.get(REFERENCE_SHEET_COLUMNS[3])` และ `raw.get("previous" + "_note")` ผ่าน
    (`code-critic` พิสูจน์แล้ว 2026-08-08) · ท่านี้จับได้เพราะดูที่ *คีย์ที่ถูกอ่านจริง*
    """
    seen: set[str] = set()
    rows = [
        _RecordingRow(_raw(reference_url=URL), seen),
        _RecordingRow(_raw(poster_uuid=str(PID2), reference_note="ไม่เจอ"), seen),
        _RecordingRow(_raw(poster_uuid=str(PID3)), seen),  # เว้นว่างทั้งคู่
    ]
    parse_rows(rows)  # type: ignore[arg-type]
    assert seen == set(REQUIRED_COLUMNS)


def test_previous_note_has_no_place_to_land_in_the_parsed_row() -> None:
    """ชั้นโครงสร้าง — ไม่มีฟิลด์ให้เก็บ แปลว่าไม่มีชั้นไหนข้างล่างอ่านมันได้เลย"""
    assert "previous_note" not in REQUIRED_COLUMNS
    assert "previous_note" not in {
        f.name for f in ReferenceRow.__dataclass_fields__.values()
    }


def test_the_sheet_has_exactly_two_human_columns_and_no_status_column() -> None:
    """AC-2 · AC-3 — ไม่มี `verification_status` · ไม่มี checklist · ไม่มี `approved`"""
    assert REFERENCE_SHEET_COLUMNS == (
        "poster_uuid",
        "title",
        "image_url",
        "previous_note",
        "reference_url",
        "reference_note",
    )
    assert set(DERIVED_FIELDS).isdisjoint(REFERENCE_SHEET_COLUMNS)


def test_writable_set_is_exactly_the_three_columns_of_adr_0014() -> None:
    assert HUMAN_FIELDS == ("reference_url", "reference_note")
    assert DERIVED_FIELDS == ("verification_status",)
    assert WRITABLE_FIELDS == ("reference_url", "reference_note", "verification_status")
    # D29 ตรวจเป็นก้อน — ทุกช่องที่เขียนได้ต้องอยู่ในก้อนที่ต้องว่างพร้อมกัน
    assert set(NULL_ONLY_FIELDS) == set(WRITABLE_FIELDS)


def test_production_is_not_a_selectable_target() -> None:
    """🔴 ยืม `TARGETS` ของเส้นที่ 3 มาใช้ ไม่ประกาศซ้ำ — ADR-0015 D8"""
    from scripts.seed import manual_entry as manual_mod

    assert mod.TARGETS == ("dev", "sit")
    # ต้องเป็น **ตัวเดียวกัน** ไม่ใช่ก๊อปมา — guard สองชั้นของ ADR-0015 D8 จะได้ไม่ drift
    assert mod.assert_target is manual_mod.assert_target
    assert mod.TARGETS is manual_mod.TARGETS


# --------------------------------------------------------------------------
# D22 — ตาราง derive ครบทั้ง 4 ช่อง
# --------------------------------------------------------------------------


def test_url_only_derives_reference_found() -> None:
    assert derive_status(URL, "") is VerificationStatus.REFERENCE_FOUND


def test_note_only_derives_no_reference_found() -> None:
    assert derive_status("", "เว็บมีหนังแต่ไม่มีวาเรียนต์นี้") is (
        VerificationStatus.NO_REFERENCE_FOUND
    )


def test_both_blank_stays_null_not_a_member_of_the_enum() -> None:
    """🔴 D21 — `NOT_CHECKED` ไม่ใช่สมาชิกของ enum · `NULL` ทำหน้าที่นั้น"""
    assert derive_status("", "") is None
    assert "NOT_CHECKED" not in {m.value for m in VerificationStatus}


def test_both_filled_rejects_the_whole_file_not_just_the_row() -> None:
    """AC-4 · D29 — เข้าใจกติกาไม่ตรงกัน ไม่ใช่กรอกไม่เสร็จ"""
    with pytest.raises(
        PrecheckError, match="กรอกทั้ง reference_url และ reference_note"
    ):
        parse_rows(
            [
                _raw(reference_url=URL),  # แถวที่ถูกต้อง
                _raw(
                    poster_uuid=str(PID2),
                    reference_url=URL2,
                    reference_note="เจอแล้วแต่อยากอธิบายด้วย",
                ),
            ]
        )


def test_the_enum_has_exactly_two_members() -> None:
    assert {m.value for m in VerificationStatus} == {
        "REFERENCE_FOUND",
        "NO_REFERENCE_FOUND",
    }


# --------------------------------------------------------------------------
# AC-5 — ตรวจรูปแบบ URL (pure · ไม่ต่อเน็ต · ไม่ normalize)
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "value",
    [
        URL,
        "https://www.impawards.com/2021/no_time_to_die_ver15.html",
        "http://www.impawards.com/2021/",  # trailing slash ต้องอยู่ครบ
        "http://WWW.ImpAwards.COM/A.html",  # ตัวพิมพ์ต้องไม่ถูกแปลง
        "http://example.invalid/a?b=c&d=e#frag",
    ],
)
def test_valid_urls_come_back_unchanged(value: str) -> None:
    """🔴 ห้าม normalize — ค่าที่เก็บต้องเป็นสิ่งที่คนแปะมาเป๊ะ ๆ"""
    assert validate_reference_url(value) == value


@pytest.mark.parametrize(
    ("value", "why"),
    [
        ("http://a.invalid/x y.html", "ช่องว่างข้างใน"),
        ("http://a.invalid/x\ty", "แท็บข้างใน"),
        ("http://a.invalid/x\ny", "ขึ้นบรรทัดใหม่ข้างใน"),
        ("http://a.invalid/x|เจอแล้ว", "คั่นด้วย |"),
        ('{"url":"http://a.invalid"}', "JSON"),
        ("[http://a.invalid]", "ลิสต์"),
        ("http://a.invalid http://b.invalid", "สอง URL (ติดช่องว่างก่อน)"),
        ("http://a.invalid/x?u=http://b.invalid", "'://' สองครั้ง"),
        ("www.impawards.com/2021/a.html", "ไม่มี scheme — สคริปต์ไม่เติมให้"),
        ("ftp://a.invalid/x", "scheme ที่ไม่ใช่ http/https"),
        ("http://", "ไม่มีชื่อโฮสต์"),
        ("เจอแล้วที่ IMP Awards", "ข้อความล้วน"),
    ],
)
def test_malformed_urls_are_rejected(value: str, why: str) -> None:
    with pytest.raises(ValueError):
        validate_reference_url(value)


def test_http_is_accepted_because_every_real_link_uses_it() -> None:
    """🔴 ห้ามบังคับ https — ลิงก์ที่คนกรอกไว้จริงทั้งชุดเป็น http://
    ถ้าบังคับ ไฟล์ที่ถูกต้องทั้งไฟล์จะถูกปฏิเสธตั้งแต่รันครั้งแรก"""
    assert validate_reference_url(URL).startswith("http://")


def test_a_bad_url_rejects_the_whole_file() -> None:
    with pytest.raises(PrecheckError, match="reference_url"):
        parse_rows(
            [
                _raw(reference_url=URL),
                _raw(poster_uuid=str(PID2), reference_url="ftp://x/y"),
            ]
        )


def test_cell_whitespace_is_trimmed_by_the_reader_not_by_the_validator(
    tmp_path,
) -> None:
    """`read_sheet()` ตัดช่องว่างหัวท้ายของ cell (ทรงเดียวกับเส้นที่ 3) —
    `validate_reference_url()` จึงไม่ต้อง strip เอง และไม่ควร strip เอง"""
    path = tmp_path / "reference-entry.csv"
    path.write_text(
        ",".join(REFERENCE_SHEET_COLUMNS) + f"\n{PID},T,,,  {URL}  ,\n",
        encoding="utf-8",
    )
    assert read_sheet(path)[0]["reference_url"] == URL
    with pytest.raises(ValueError):
        validate_reference_url(f" {URL} ")


def test_missing_required_column_is_reported_by_name(tmp_path) -> None:
    path = tmp_path / "reference-entry.csv"
    path.write_text("poster_uuid,reference_url\n", encoding="utf-8")
    with pytest.raises(PrecheckError, match="reference_note"):
        read_sheet(path)


def test_duplicate_poster_uuid_rejects_the_file() -> None:
    with pytest.raises(PrecheckError, match="ซ้ำกับแถวก่อนหน้า"):
        parse_rows([_raw(reference_url=URL), _raw(reference_url=URL2)])


def test_bad_uuid_rejects_the_file() -> None:
    with pytest.raises(PrecheckError, match="ไม่ใช่ UUID"):
        parse_rows([_raw(poster_uuid="not-a-uuid")])


# --------------------------------------------------------------------------
# D30 — URL ซ้ำข้ามแถว = warning เท่านั้น
# --------------------------------------------------------------------------


def test_duplicate_urls_do_not_stop_the_run() -> None:
    """🔴 ADR-0014 D30 — ใบไทย `THEATRICAL` กับ `ADVANCE` ของหนังเรื่องเดียวกันใช้
    อาร์ตเวิร์กชุดเดียวกัน จึงชี้ URL เดียวกันโดยถูกต้อง (เจ้าของยืนยันจากใบจริง)
    ด่านปฏิเสธจะปฏิเสธไฟล์ที่ถูกตั้งแต่รันครั้งแรก — ห้ามใครใส่กลับมา
    """
    rows = parse_rows(
        [_raw(reference_url=URL), _raw(poster_uuid=str(PID2), reference_url=URL)]
    )
    assert len(rows) == 2
    plans = plan_writes(rows, {PID: _state(), PID2: _state()})
    assert [p.action for p in plans] == [RowAction.WRITE, RowAction.WRITE]
    # สถานะที่ derive ได้ต้องไม่เปลี่ยนเพราะความซ้ำ
    assert all(
        p.field_writes["verification_status"] is VerificationStatus.REFERENCE_FOUND
        for p in plans
    )


def test_duplicate_urls_are_listed_for_the_human_to_look_at() -> None:
    rows = parse_rows(
        [
            _raw(reference_url=URL),
            _raw(poster_uuid=str(PID2), reference_url=URL2),
            _raw(poster_uuid=str(PID3), reference_url=URL),
        ]
    )
    assert duplicate_reference_urls(rows) == [(URL, (2, 4))]


def test_unique_urls_produce_no_warning() -> None:
    rows = parse_rows(
        [_raw(reference_url=URL), _raw(poster_uuid=str(PID2), reference_url=URL2)]
    )
    assert duplicate_reference_urls(rows) == []


def test_blank_urls_are_not_counted_as_duplicates_of_each_other() -> None:
    rows = parse_rows(
        [
            _raw(reference_note="ไม่เจอ"),
            _raw(poster_uuid=str(PID2), reference_note="ไม่เจอเหมือนกัน"),
        ]
    )
    assert duplicate_reference_urls(rows) == []


# --------------------------------------------------------------------------
# D29 — NULL-only เป็นก้อน · ไม่มีโหมดเขียนทับ
# --------------------------------------------------------------------------


def test_all_null_target_is_written() -> None:
    plan = plan_writes([_row()], {PID: _state()})[0]
    assert plan.action is RowAction.WRITE
    assert plan.field_writes == {
        "reference_url": URL,
        "verification_status": VerificationStatus.REFERENCE_FOUND,
    }


def test_note_only_row_writes_the_note_and_the_derived_status() -> None:
    plan = plan_writes(
        [_row(reference_url="", reference_note="ไม่เจอในเว็บ")], {PID: _state()}
    )[0]
    assert plan.field_writes == {
        "reference_note": "ไม่เจอในเว็บ",
        "verification_status": VerificationStatus.NO_REFERENCE_FOUND,
    }


@pytest.mark.parametrize(
    "existing",
    [
        {"reference_url": "http://old.invalid/x"},
        {"reference_note": "เคยบันทึกไว้"},
        {"verification_status": VerificationStatus.NO_REFERENCE_FOUND},
    ],
)
def test_any_non_null_in_the_block_skips_the_whole_poster(existing: dict) -> None:
    """🔴 D29 — ตรวจเป็นก้อน ไม่ใช่ทีละฟิลด์ · ถ้าตรวจทีละฟิลด์ ใบที่มี url อยู่แล้ว
    จะรับ note เข้าไปแล้วได้ค่าสามตัวที่ขัดกันเองโดย derive ไม่ทัน"""
    plan = plan_writes([_row()], {PID: _state(**existing)})[0]
    assert plan.action is RowAction.SKIP_ALREADY_SET
    assert plan.field_writes == {}
    assert set(plan.already_set) == set(existing)


def test_a_poster_with_a_url_does_not_accept_a_note_this_round() -> None:
    """เคสที่ D29 ยกมาเป็นเหตุผลตรง ๆ"""
    plan = plan_writes(
        [_row(reference_url="", reference_note="ไม่เจอ")],
        {PID: _state(reference_url="http://old.invalid/x")},
    )[0]
    assert plan.action is RowAction.SKIP_ALREADY_SET
    assert plan.field_writes == {}


def test_blank_row_is_normal_and_leaves_the_column_null() -> None:
    plan = plan_writes([_row(reference_url="", reference_note="")], {PID: _state()})[0]
    assert plan.action is RowAction.SKIP_BLANK
    assert plan.field_writes == {}


def test_missing_poster_is_skipped_never_inserted() -> None:
    plan = plan_writes([_row()], {})[0]
    assert plan.action is RowAction.SKIP_NOT_FOUND
    assert plan.field_writes == {}


def test_rerunning_the_same_sheet_writes_nothing_the_second_time() -> None:
    """idempotent โดยโครงสร้าง — ผลพลอยได้ของ D29"""
    rows = parse_rows([_raw(reference_url=URL)])
    first = plan_writes(rows, {PID: _state()})
    assert planned_field_counts(first) == {
        "reference_url": 1,
        "reference_note": 0,
        "verification_status": 1,
    }
    after = _state(
        reference_url=URL, verification_status=VerificationStatus.REFERENCE_FOUND
    )
    second = plan_writes(rows, {PID: after})
    assert planned_field_counts(second) == dict.fromkeys(WRITABLE_FIELDS, 0)


def test_field_writes_never_contain_anything_outside_the_writable_set() -> None:
    """closed-world ที่ runtime — คู่กับเทส AST ข้างบน · ครอบทุกสาขาของ `plan_writes()`"""
    rows = [
        _row(),
        _row(poster_uuid=PID2, reference_url="", reference_note="ไม่เจอ", lineno=3),
        _row(poster_uuid=PID3, reference_url="", reference_note="", lineno=4),
    ]
    plans = plan_writes(rows, {PID: _state(), PID2: _state(), PID3: _state()})
    written: set[str] = set()
    for plan in plans:
        assert set(plan.field_writes) <= set(WRITABLE_FIELDS)
        written |= set(plan.field_writes)
    assert written == set(WRITABLE_FIELDS)


# --------------------------------------------------------------------------
# AC-6 · D31 — audit 2 แถวต่อใบที่เขียนจริง
# --------------------------------------------------------------------------


def test_a_found_reference_writes_two_audit_rows() -> None:
    plan = plan_writes([_row()], {PID: _state()})[0]
    entries = audit_entries(plan)
    assert len(entries) == 2
    assert {e.field for e in entries} == {"reference_url", "verification_status"}


def test_a_missing_reference_also_writes_two_audit_rows() -> None:
    plan = plan_writes(
        [_row(reference_url="", reference_note="ไม่เจอ")], {PID: _state()}
    )[0]
    entries = audit_entries(plan)
    assert len(entries) == 2
    assert {e.field for e in entries} == {"reference_note", "verification_status"}


def test_the_derived_status_gets_its_own_audit_row_with_the_enum_value() -> None:
    """🔴 D31 — ถ้าค่า derive ไม่มีแถวของตัวเอง จะมีคอลัมน์บน `posters` เปลี่ยนค่า
    โดยไม่มีร่องรอย ซึ่งชนตารางเส้นแบ่งของ ADR-0014 D2"""
    plan = plan_writes([_row()], {PID: _state()})[0]
    status_row = next(
        e for e in audit_entries(plan) if e.field == "verification_status"
    )
    assert status_row.value_after == "REFERENCE_FOUND"


@pytest.mark.parametrize("note", ["", "ไม่เจอ"])
def test_value_before_is_always_null_on_a_null_only_write(note: str) -> None:
    """AC-6 — ไม่มีโหมดเขียนทับ จึงไม่มีค่าเดิมให้เก็บ"""
    url = "" if note else URL
    plan = plan_writes([_row(reference_url=url, reference_note=note)], {PID: _state()})[
        0
    ]
    assert all(isinstance(e, AuditEntry) for e in audit_entries(plan))
    assert [e.value_before for e in audit_entries(plan)] == [None, None]


def test_skipped_rows_produce_no_audit_at_all() -> None:
    for plan in plan_writes(
        [_row(), _row(poster_uuid=PID2, lineno=3)],
        {PID: _state(reference_url="http://old.invalid/x")},
    ):
        assert audit_entries(plan) == ()


# --------------------------------------------------------------------------
# assert หลัง commit
# --------------------------------------------------------------------------


def test_count_assertion_passes_when_deltas_match() -> None:
    before = dict.fromkeys(WRITABLE_FIELDS, 0)
    after = {"reference_url": 1, "reference_note": 0, "verification_status": 1}
    planned = dict(after)
    assert _report_counts(before, after, planned) == 0


def test_count_assertion_fails_when_nothing_actually_landed() -> None:
    """🔴 กับดักเดียวกับ `count(*)` — ต้องจับได้ว่าไม่มีอะไรเข้า DB จริง"""
    before = dict.fromkeys(WRITABLE_FIELDS, 0)
    planned = {"reference_url": 1, "reference_note": 0, "verification_status": 1}
    assert _report_counts(before, dict(before), planned) == 1


def test_count_assertion_covers_every_writable_column() -> None:
    before = dict.fromkeys(WRITABLE_FIELDS, 0)
    after = dict(before)
    for name in WRITABLE_FIELDS:
        planned = dict.fromkeys(WRITABLE_FIELDS, 0)
        planned[name] = 1
        assert _report_counts(before, after, planned) == 1, name


# --------------------------------------------------------------------------
# AC-1 — dry-run เป็น default · --reviewed-by/--reviewed-at บังคับเมื่อ --commit
# --------------------------------------------------------------------------


def _argv(monkeypatch, *args: str) -> None:
    monkeypatch.setattr(sys, "argv", ["reference_entry.py", *args])


def test_commit_without_reviewed_by_is_refused(monkeypatch) -> None:
    _argv(monkeypatch, "--commit", "--reviewed-at", "2026-08-08T20:00:00+07:00")
    with pytest.raises(SystemExit) as exc:
        mod.main()
    assert exc.value.code == 2


def test_commit_without_reviewed_at_is_refused(monkeypatch) -> None:
    _argv(monkeypatch, "--commit", "--reviewed-by", "chanothai")
    with pytest.raises(SystemExit) as exc:
        mod.main()
    assert exc.value.code == 2


def test_reviewed_at_without_a_timezone_is_refused(monkeypatch) -> None:
    """🔴 ADR-0010 D5 — ไม่มี default เป็น now() และไม่เดา timezone ให้"""
    _argv(
        monkeypatch,
        "--commit",
        "--reviewed-by",
        "chanothai",
        "--reviewed-at",
        "2026-08-08T20:00:00",
    )
    with pytest.raises(SystemExit) as exc:
        mod.main()
    assert exc.value.code == 2


def test_dry_run_is_the_default_and_asks_for_no_reviewer(
    monkeypatch, tmp_path, capsys
) -> None:
    """AC-1 — ไม่ใส่ `--commit` แล้วต้องไม่มีใครถูกบังคับให้ระบุชื่อ/เวลา

    ต้อง assert **ข้อความ** ไม่ใช่แค่ `rc == 1` — `rc = 1` มาได้จากหลายเส้นทางที่
    ไม่เกี่ยวกันเลย (ชื่อ database มีคำว่า `prod` · ไม่พบ `DATABASE_URL`) แล้วเทส
    จะเขียวโดยไม่เคยเดินผ่าน argparse guard ที่ตั้งใจจะวัด
    """
    _argv(monkeypatch, "--file", str(tmp_path / "ยังไม่มีไฟล์.csv"))
    assert mod.main() == 1  # ไม่ใช่ SystemExit(2) จาก argparse
    assert "ไม่พบใบงาน" in capsys.readouterr().err


# --------------------------------------------------------------------------
# ด่าน `--reviewed-at` ที่อยู่ในอนาคต (pure — ป้อน `now` เข้าไปเอง ไม่ freeze เวลา)
# --------------------------------------------------------------------------


def _at(text: str) -> datetime:
    return datetime.fromisoformat(text)


def test_a_time_in_the_past_passes() -> None:
    assert (
        assert_not_in_the_future(
            _at("2026-08-08T16:00:00+07:00"), now=_at("2026-08-08T16:29:00+07:00")
        )
        is None
    )


def test_exactly_now_passes_because_this_gate_is_not_strict() -> None:
    """คนที่เพิ่งตัดสินเสร็จแล้วรันทันทีคือการใช้งานปกติ — ปฏิเสธ `now` เป๊ะ ๆ
    จะทำให้ด่านนี้เป็นกับดักแทนที่จะเป็นตัวช่วย"""
    moment = _at("2026-08-08T16:29:00+07:00")
    assert assert_not_in_the_future(moment, now=moment) is None


def test_one_second_ahead_is_already_refused() -> None:
    with pytest.raises(PrecheckError, match="อนาคต"):
        assert_not_in_the_future(
            _at("2026-08-08T16:29:01+07:00"), now=_at("2026-08-08T16:29:00+07:00")
        )


def test_the_same_instant_written_in_two_timezones_is_not_in_the_future() -> None:
    """🔴 เทียบเป็น **instant** ไม่ใช่หน้าปัด — `20:00+07:00` กับ `13:00Z` คือเวลา
    เดียวกัน · ด่านที่ตัด tzinfo ทิ้งแล้วเทียบ naive จะปฏิเสธค่าที่ถูกต้องตรงนี้"""
    assert (
        assert_not_in_the_future(
            _at("2026-08-08T20:00:00+07:00"), now=_at("2026-08-08T13:00:00+00:00")
        )
        is None
    )


def test_a_future_instant_hiding_behind_a_smaller_wall_clock_is_still_refused() -> None:
    """ทิศตรงข้ามของเทสบน — `09:00Z` = `16:00+07:00` ซึ่งล้ำหน้า `15:00+07:00` อยู่
    หนึ่งชั่วโมง แต่ตัวเลขหน้าปัด (09 < 15) หลอกให้ด่านที่เทียบ naive ปล่อยผ่าน"""
    with pytest.raises(PrecheckError, match="อนาคต"):
        assert_not_in_the_future(
            _at("2026-08-08T09:00:00+00:00"), now=_at("2026-08-08T15:00:00+07:00")
        )


def test_the_message_says_how_far_ahead_so_a_timezone_typo_is_obvious() -> None:
    """ตัวเลขคือสิ่งที่ทำให้คนเดาสาเหตุถูก — เหตุการณ์จริง 2026-08-08 ล้ำหน้า
    **3 ชั่วโมง 31 นาที** ซึ่งอ่านแล้วเห็นทันทีว่าคือ `+07:00` ที่ก๊อปมา ไม่ใช่
    ค่าที่ตั้งใจพิมพ์"""
    with pytest.raises(PrecheckError) as exc:
        assert_not_in_the_future(
            _at("2026-08-08T20:00:00+07:00"), now=_at("2026-08-08T16:29:00+07:00")
        )
    text = str(exc.value)
    assert "3 ชั่วโมง" in text
    assert "31 นาที" in text


def test_the_current_time_is_shown_in_the_timezone_the_human_typed() -> None:
    """`now` ที่โผล่ในข้อความถูกแปลงเป็น timezone เดียวกับค่าที่กรอก คนจะได้เทียบ
    สองตัวเลขนี้ตรง ๆ ได้ — `09:29Z` ต้องแสดงเป็น `16:29+07:00`"""
    with pytest.raises(PrecheckError) as exc:
        assert_not_in_the_future(
            _at("2026-08-08T20:00:00+07:00"), now=_at("2026-08-08T09:29:00+00:00")
        )
    assert "2026-08-08T16:29:00+07:00" in str(exc.value)


def test_a_future_reviewed_at_is_refused_at_the_cli_before_anything_is_read(
    monkeypatch, tmp_path, capsys
) -> None:
    """🔴 ด่านต้องถูก **ต่อสายเข้า `main()` จริง** ไม่ใช่แค่มีฟังก์ชันอยู่เฉย ๆ

    `--file` ชี้ไปไฟล์ที่ไม่มีอยู่โดยตั้งใจ: ถ้าด่านถูกถอดออก `main()` จะเดินต่อไป
    จนตกที่ `read_sheet()` แล้ว **คืน 1 แทนที่จะ `SystemExit(2)`** → เทสแดง ·
    และการยืนยันว่า stderr ไม่มี "ไม่พบใบงาน" คือหลักฐานว่าหยุดก่อนถึงชั้นอ่านไฟล์
    """
    _argv(
        monkeypatch,
        "--commit",
        "--reviewed-by",
        "chanothai",
        "--reviewed-at",
        "3000-01-01T00:00:00+07:00",
        "--file",
        str(tmp_path / "ยังไม่มีไฟล์.csv"),
    )
    with pytest.raises(SystemExit) as exc:
        mod.main()
    assert exc.value.code == 2
    err = capsys.readouterr().err
    assert re.search(r"อนาคต\s+\d", err), err
    assert "ไม่พบใบงาน" not in err


def test_a_past_reviewed_at_walks_straight_through_the_gate(
    monkeypatch, tmp_path, capsys
) -> None:
    """ด้านที่ต้องไม่พัง — เวลาในอดีตกับนาฬิกา **จริง** ต้องผ่านด่านไปจนถึงชั้นอ่านไฟล์

    เทสตัวนี้เป็นตัวเดียวที่เดินผ่าน `datetime.now(...)` ของจริง จึงเป็นตัวเดียวที่จับ
    ได้ถ้านาฬิกาถูกอ่านแบบไม่มี timezone (naive `now` → `TypeError` ตอนเทียบ)
    """
    _argv(
        monkeypatch,
        "--commit",
        "--reviewed-by",
        "chanothai",
        "--reviewed-at",
        "2020-01-01T00:00:00+07:00",
        "--file",
        str(tmp_path / "ยังไม่มีไฟล์.csv"),
    )
    assert mod.main() == 1  # ไม่ใช่ SystemExit(2) จาก argparse
    assert "ไม่พบใบงาน" in capsys.readouterr().err


# --------------------------------------------------------------------------
# ด่านก่อนเขียน — ใบงานของเส้นอื่น · schema ปลายทาง · CSV ที่มีคอลัมน์เกิน
# --------------------------------------------------------------------------


def test_the_manual_entry_sheet_is_refused_by_name() -> None:
    """🔴 `poster_attribute_reviews.source` เก็บชื่อไฟล์ ซึ่งเป็น**สิ่งเดียว**ที่แยกว่า
    ค่าไหนมาจากเส้นที่ 3 ค่าไหนมาจากเส้นที่ 4 (ADR-0014 D28) — ส่งไฟล์ผิดมาแล้ว
    ร่องรอยนั้นหายไปเงียบ ๆ โดยที่ทุกอย่างดูเหมือนสำเร็จ"""
    from scripts.seed.manual_entry import DEFAULT_MANUAL_CSV

    with pytest.raises(PrecheckError, match="เส้นที่ 3"):
        assert_own_sheet(DEFAULT_MANUAL_CSV)
    with pytest.raises(PrecheckError, match="เส้นที่ 3"):
        assert_own_sheet(Path("/tmp") / DEFAULT_MANUAL_CSV.name)


def test_our_own_sheet_passes_wherever_it_lives() -> None:
    assert_own_sheet(Path("/anywhere/reference-entry.csv")) is None
    assert_own_sheet(mod.DEFAULT_REFERENCE_CSV) is None


def test_schema_ready_passes_when_the_columns_are_there() -> None:
    assert assert_schema_ready([]) is None


def test_missing_columns_name_the_real_cause_not_an_attributeerror() -> None:
    """ปลายทางตามหลัง `develop` → ต้องบอกว่าให้ไป migrate/rebuild ไม่ใช่โยน
    `AttributeError` ดิบที่คนอ่านไม่ออกว่าต้องทำอะไรต่อ"""
    with pytest.raises(PrecheckError, match="reference_url") as exc:
        assert_schema_ready(["reference_url", "verification_status"])
    assert "alembic upgrade head" in str(exc.value)


def test_a_row_with_more_values_than_header_is_a_precheck_error(tmp_path) -> None:
    """🔴 เกิดจริงเมื่อ `reference_note` มีจุลภาคแล้วไม่ได้ครอบด้วยอัญประกาศ ·
    `csv.DictReader` ยัดส่วนเกินเป็น **list** ทำให้ `.strip()` โยน `AttributeError`
    ดิบถ้าไม่ดัก (บั๊กคลาสเดียวกันยังอยู่ใน `manual_entry.read_manual_sheet()` —
    นอกขอบเขตรอบนี้ รายงานไว้แล้ว)"""
    path = tmp_path / "reference-entry.csv"
    path.write_text(
        ",".join(REFERENCE_SHEET_COLUMNS)
        + f"\n{PID},T,,,,ไม่เจอ, เพราะเว็บไม่มีวาเรียนต์นี้\n",
        encoding="utf-8",
    )
    with pytest.raises(PrecheckError, match="มากกว่าจำนวนคอลัมน์"):
        read_sheet(path)


# --------------------------------------------------------------------------
# `run()` — closed-world ที่ runtime (ชั้นที่ 2) + ลำดับการเรียก
# --------------------------------------------------------------------------


class _PosterSpy:
    """object แทน `Poster` ที่จำ **ทุก** attribute ที่ถูกเซ็ตลงไป

    🔴 นี่คือชั้นเดียวที่จับชื่อซึ่งประกอบขึ้นตอนรันได้ —
    `setattr(poster, "needs" + "_review", …)` · f-string · `"_".join([...])` ·
    `REFERENCE_SHEET_COLUMNS[3]` · การสแกนซอร์สมองไม่เห็นทั้งหมดนั้น
    """

    def __init__(self) -> None:
        object.__setattr__(self, "writes", {})

    def __setattr__(self, name: str, value: object) -> None:
        self.writes[name] = value
        object.__setattr__(self, name, value)


class _FakeSession:
    """พอสำหรับ `run()` — `__aenter__`/`get`/`add`/`commit` · ไม่มี SQL สักบรรทัด."""

    def __init__(self, posters: dict) -> None:
        self.posters = posters
        self.added: list = []
        self.committed = False

    async def __aenter__(self) -> _FakeSession:
        return self

    async def __aexit__(self, *exc: object) -> bool:
        return False

    async def get(self, _model: object, pk: object) -> object:
        return self.posters.get(pk)

    def add(self, obj: object) -> None:
        self.added.append(obj)

    async def commit(self) -> None:
        self.committed = True


def _write_sheet(tmp_path, rows: list[dict[str, str]]):
    path = tmp_path / "reference-entry.csv"
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(REFERENCE_SHEET_COLUMNS))
        writer.writeheader()
        writer.writerows(rows)
    return path


async def _run_applier(monkeypatch, tmp_path, sheet_rows, *, commit: bool = True):
    """เรียก `run()` จริง โดยแทนเฉพาะ **ทางเข้าออก DB** — ตรรกะทั้งหมดเป็นของจริง"""
    import app.core.database as db_mod

    path = _write_sheet(tmp_path, sheet_rows)
    ids = [uuid.UUID(r["poster_uuid"]) for r in sheet_rows]
    posters = {pid: _PosterSpy() for pid in ids}
    session = _FakeSession(posters)

    async def fake_load_state(_session, _ids):
        return {pid: PosterState(values=dict.fromkeys(NULL_ONLY_FIELDS)) for pid in ids}

    async def fake_counts(_session):
        return {
            name: sum(1 for p in posters.values() if getattr(p, name, None) is not None)
            for name in WRITABLE_FIELDS
        }

    monkeypatch.setattr(db_mod, "async_session_maker", lambda: session)
    monkeypatch.setattr(mod, "_load_state", fake_load_state)
    monkeypatch.setattr(mod, "_column_counts", fake_counts)

    args = argparse.Namespace(
        file=path, commit=commit, reviewed_by="chanothai", reviewed_at=REVIEWED_AT
    )
    rc = await mod.run(args, "fake/db  [--target dev]")
    return rc, session, posters


async def test_run_writes_nothing_outside_the_writable_set(monkeypatch, tmp_path):
    """🔴 closed-world ที่ **runtime** — ชั้นที่ 2 จาก 2 (ดู docstring ของโมดูล)

    ครอบสิ่งที่ชั้นซอร์สจับไม่ได้: ชื่อ attribute ที่ประกอบขึ้นตอนรัน **และ**
    การเขียนที่เพิ่ม *นอก* ลูปของ `field_writes` ซึ่ง fail-closed ตัวนั้นไม่ครอบ
    """
    rc, _session, posters = await _run_applier(
        monkeypatch,
        tmp_path,
        [
            _raw(reference_url=URL),
            _raw(poster_uuid=str(PID2), reference_note="ไม่เจอในเว็บ"),
            _raw(poster_uuid=str(PID3)),  # เว้นว่างทั้งคู่ — ต้องไม่ถูกแตะเลย
        ],
    )
    assert rc == 0
    written = set()
    for spy in posters.values():
        assert set(spy.writes) <= set(WRITABLE_FIELDS)
        written |= set(spy.writes)
    assert written == set(WRITABLE_FIELDS)
    assert posters[PID3].writes == {}


async def test_run_records_exactly_two_audit_rows_per_written_poster(
    monkeypatch, tmp_path
):
    """AC-6 · D31 — และ `source` ต้องเป็นชื่อใบงานของเส้นนี้ (D28)"""
    _rc, session, _posters = await _run_applier(
        monkeypatch,
        tmp_path,
        [_raw(reference_url=URL), _raw(poster_uuid=str(PID2), reference_note="ไม่เจอ")],
    )
    assert session.committed is True
    assert len(session.added) == 4
    by_poster: dict = {}
    for entry in session.added:
        by_poster.setdefault(entry.poster_id, set()).add(entry.field)
    assert by_poster == {
        PID: {"reference_url", "verification_status"},
        PID2: {"reference_note", "verification_status"},
    }
    assert all(e.value_before is None for e in session.added)
    assert all(e.reviewed_by == "chanothai" for e in session.added)
    assert all(e.reviewed_at == REVIEWED_AT for e in session.added)
    assert {e.source for e in session.added} == {"reference-entry.csv"}


async def test_dry_run_touches_no_poster_and_records_no_audit(monkeypatch, tmp_path):
    rc, session, posters = await _run_applier(
        monkeypatch, tmp_path, [_raw(reference_url=URL)], commit=False
    )
    assert rc == 0
    assert session.added == []
    assert session.committed is False
    assert all(spy.writes == {} for spy in posters.values())


async def test_run_parses_the_sheet_before_it_plans_anything(monkeypatch, tmp_path):
    """🔴 precondition ของ `derive_status()` — กฎ AC-4/D29 มีเจ้าของที่ `parse_rows()`
    แห่งเดียว · ถ้าใครสลับลำดับหรือข้ามมัน แถวที่กรอกทั้งสองช่องจะไหลเข้า
    `plan_writes()` แล้วได้ `REFERENCE_FOUND` เงียบ ๆ แทนที่จะปฏิเสธทั้งไฟล์"""
    calls: list[str] = []
    real_parse, real_plan = mod.parse_rows, mod.plan_writes

    def spy_parse(raw_rows):
        calls.append("parse_rows")
        return real_parse(raw_rows)

    def spy_plan(rows, current):
        calls.append("plan_writes")
        return real_plan(rows, current)

    monkeypatch.setattr(mod, "parse_rows", spy_parse)
    monkeypatch.setattr(mod, "plan_writes", spy_plan)
    await _run_applier(monkeypatch, tmp_path, [_raw(reference_url=URL)])
    assert calls == ["parse_rows", "plan_writes"]


async def test_run_refuses_the_other_lanes_sheet_before_touching_anything(
    monkeypatch, tmp_path
):
    from scripts.seed.manual_entry import DEFAULT_MANUAL_CSV

    path = _write_sheet(tmp_path, [_raw(reference_url=URL)])
    path.rename(tmp_path / DEFAULT_MANUAL_CSV.name)
    args = argparse.Namespace(
        file=tmp_path / DEFAULT_MANUAL_CSV.name,
        commit=True,
        reviewed_by="chanothai",
        reviewed_at=REVIEWED_AT,
    )
    with pytest.raises(PrecheckError, match="เส้นที่ 3"):
        await mod.run(args, "fake/db")
