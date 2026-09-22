"""Unit tests ของเส้นทาง triage ที่คนกรอก — `is_poster` / `needs_review`

จุดสำคัญที่สุดที่ต้องล็อก 2 ข้อ:
  1. `make_triage_sheet.py` **ห้ามกรอกสองคอลัมน์นี้ให้**
     ถ้าเครื่องกรอก = เครื่องตัดสินงานของเครื่องเอง ขัด ADR-0009 D6
     ‹แก้ 2026-08-16 · INF-26 AC-9› เดิมข้อนี้ครอบ `prepare_seed.py` ด้วย — ไฟล์นั้น
     **ถูกลบไปแล้ว** (ADR-0019 **A-D3**) ⇒ ครอบตัวที่เหลืออยู่จริงตัวเดียว
     🔴 **กฎไม่ได้อ่อนลง หายไปเพราะไม่มีตัวให้ครอบ** — ห้ามอ่านการหายไปของเคสนั้นว่า
     เป็นการผ่อนปรน · ADR-0009 D6 · ADR-0010 D2 ยังบังคับเต็มกับ generator ทุกตัว
  2. `seed_posters.py` ต้อง **fail-closed** — ช่องว่างหรือค่าที่ไม่ใช่ 0/1 ต้องหยุด
     ทั้งชุด ไม่ใช่ข้ามเฉพาะแถวนั้น
"""

from __future__ import annotations

import ast
import inspect

import pytest

from scripts.seed import make_triage_sheet as sheet_mod
from scripts.seed._shared import NOT_A_POSTER_REASON
from scripts.seed.make_triage_sheet import build_sheet_rows
from scripts.seed.seed_posters import (
    TRIAGE_HUMAN_COLUMNS,
    TRIAGE_REQUIRED_COLUMNS,
    PrecheckError,
    apply_triage,
    load_triage,
)

SHEET = "poster-triage-signoff.csv"
UUID_A = "11111111-1111-1111-1111-111111111111"
UUID_B = "22222222-2222-2222-2222-222222222222"


def _sheet_row(**over: str) -> dict[str, str]:
    row = {
        "poster_uuid": UUID_A,
        "title": "BLADE RUNNER",
        "original_name": "BLADE RUNNER - 1982 poster",
        "quantity": "1",
        "price_thb": "1290",
        "hint_is_poster": "1",
        "hint_reasons": "",
        "is_poster": "1",
        "needs_review": "0",
    }
    row.update(over)
    return row


def _poster_row(poster_uuid: str = UUID_A, title: str = "BLADE RUNNER") -> dict:
    return {"id": poster_uuid, "title": title, "needs_review": True}


# --- 1. เครื่องห้ามกรอกสองคอลัมน์นี้ (ล็อกระดับ AST) ---


@pytest.mark.parametrize(
    "func",
    [sheet_mod.build_sheet_rows],
    ids=["make_triage_sheet.build_sheet_rows"],
)
def test_generators_never_write_into_the_two_human_columns(func) -> None:
    """generator ต้องเขียน is_poster/needs_review เป็นค่าว่างเท่านั้น

    ‹2026-08-16› เหลือตัวเดียวเพราะ `prepare_seed.py` ถูกลบ — **ยัง parametrize ไว้
    โดยตั้งใจ** เพื่อให้ generator ตัวถัดไปต่อรายชื่อได้โดยไม่ต้องรื้อรูปเทส

    ตรวจที่ AST ไม่ใช่ที่ผลลัพธ์ เพราะสิ่งที่ต้องกันคือ *มีคนเขียนโค้ดให้กรอก* ไม่ใช่
    แค่ว่าวันนี้ผลลัพธ์บังเอิญว่าง (เทสที่ดูแต่ผลลัพธ์จะผ่านถ้ามีการเติมค่าแบบมีเงื่อนไข)
    """
    tree = ast.parse(inspect.getsource(func))
    for node in ast.walk(tree):
        if not isinstance(node, ast.Dict):
            continue
        for key, value in zip(node.keys, node.values):
            if (
                isinstance(key, ast.Constant)
                and key.value in TRIAGE_HUMAN_COLUMNS
                and isinstance(value, ast.Constant)
            ):
                assert value.value == "", f"{key.value} ถูกกรอกค่าให้: {value.value!r}"


def test_sheet_leaves_both_human_columns_blank() -> None:
    rows = build_sheet_rows(
        [
            {
                "poster_uuid": UUID_A,
                "title": "A",
                "original_name": "A poster",
                "quantity": "1",
                "price_thb": "100",
            }
        ],
        [],
    )
    assert rows[0]["is_poster"] == ""
    assert rows[0]["needs_review"] == ""


# --- 2. hint มาจากหลักฐาน ไม่ใช่คำตอบ ---


def test_hint_is_poster_is_derived_from_the_recorded_reason() -> None:
    """ใบที่ไม่มีเหตุผล NOT_A_POSTER_REASON แปลว่า regex เจอคำว่า poster แน่นอน

    เป็นการย้อนกลับที่ครบถ้วน เพราะขั้นนำเข้าเขียนเหตุผลนี้ลง review-needed.csv
    ทุกครั้งที่ regex ไม่เจอ — ไม่มีเคสที่ is_poster=0 แล้วไม่มีเหตุผล

    🔴 ค่าคงที่ตัวนี้ต้องแมตช์กับข้อความที่อยู่ใน CSV จริงซึ่งสร้างใหม่ไม่ได้แล้ว
    (ดูคอมเมนต์ที่ `_shared.NOT_A_POSTER_REASON`) — เทสนี้คือตัวที่ฟ้องถ้ามีคนแก้มัน
    """
    posters = [
        {
            "poster_uuid": u,
            "title": "T",
            "original_name": "N",
            "quantity": "1",
            "price_thb": "1",
        }
        for u in (UUID_A, UUID_B)
    ]
    review = [{"poster_uuid": UUID_A, "reasons": f"{NOT_A_POSTER_REASON} · ไม่มีปี"}]

    rows = {r["poster_uuid"]: r for r in build_sheet_rows(posters, review)}

    assert rows[UUID_A]["hint_is_poster"] == "0"
    assert rows[UUID_B]["hint_is_poster"] == "1"
    assert rows[UUID_B]["hint_reasons"] == ""


def test_rows_with_heuristic_reasons_sort_first() -> None:
    posters = [
        {
            "poster_uuid": u,
            "title": "T",
            "original_name": "N",
            "quantity": "1",
            "price_thb": "1",
        }
        for u in (UUID_A, UUID_B)
    ]
    review = [{"poster_uuid": UUID_B, "reasons": "ไม่มีปี"}]

    rows = build_sheet_rows(posters, review)

    assert [r["poster_uuid"] for r in rows] == [UUID_B, UUID_A]


# --- 3. fail-closed ตอนอ่านใบเซ็นรับ ---


@pytest.mark.parametrize("column", TRIAGE_REQUIRED_COLUMNS)
def test_blank_required_column_stops_the_whole_run(column: str) -> None:
    with pytest.raises(PrecheckError) as exc:
        load_triage([_sheet_row(**{column: ""})], SHEET)

    assert "ยังไม่ได้กรอก" in str(exc.value)


def test_blank_needs_review_is_allowed() -> None:
    """ว่าง = "ยังไม่ตัดสิน" ไม่ใช่ค่าผิด (NULL ≠ UNKNOWN — ADR-0009 D2)

    ช่องนี้ยังไปไม่ถึง DB เลย การบังคับกรอกจึงเป็นพิธีกรรมแบบที่ ADR-0010 D5
    เตือนไว้เอง · ยืนยันจากของจริง: คนกรอก is_poster ครบ 117 แถวแล้วเว้น
    needs_review ทั้งหมด ซึ่งเป็นการตอบที่ถูกต้อง
    """
    triage = load_triage([_sheet_row(needs_review="")], SHEET)

    assert triage[UUID_A]["needs_review"] == ""


def test_needs_review_that_is_filled_must_still_be_zero_or_one() -> None:
    """ว่างได้ ไม่ได้แปลว่าอะไรก็ได้ — ค่าที่กรอกมาแล้วผิดรูปแบบยังหยุดทั้งชุด"""
    with pytest.raises(PrecheckError) as exc:
        load_triage([_sheet_row(needs_review="maybe")], SHEET)

    assert "ไม่ใช่ 0 หรือ 1" in str(exc.value)


@pytest.mark.parametrize("bad", ["yes", "true", "2", "-1", "0.0"])
def test_value_outside_zero_or_one_stops_the_whole_run(bad: str) -> None:
    with pytest.raises(PrecheckError) as exc:
        load_triage([_sheet_row(is_poster=bad)], SHEET)

    assert "ไม่ใช่ 0 หรือ 1" in str(exc.value)


def test_missing_column_stops_the_whole_run() -> None:
    row = _sheet_row()
    del row["hint_reasons"]

    with pytest.raises(PrecheckError) as exc:
        load_triage([row], SHEET)

    assert "ขาดคอลัมน์" in str(exc.value)


def test_duplicate_poster_uuid_stops_the_whole_run() -> None:
    with pytest.raises(PrecheckError):
        load_triage([_sheet_row(), _sheet_row()], SHEET)


def test_fully_filled_sheet_loads() -> None:
    triage = load_triage([_sheet_row(), _sheet_row(poster_uuid=UUID_B)], SHEET)

    assert set(triage) == {UUID_A, UUID_B}


# --- 4. ผลของคำตัดสิน ---


def test_poster_missing_from_the_sheet_stops_the_whole_run() -> None:
    """ทุกใบต้องผ่านการตัดสินของคน — ไม่มีแถว = ไม่ได้ตรวจ ไม่ใช่ 'อนุญาตโดยปริยาย'"""
    with pytest.raises(PrecheckError) as exc:
        apply_triage([_poster_row(UUID_B)], load_triage([_sheet_row()], SHEET), SHEET)

    assert UUID_B in str(exc.value)


def test_is_poster_zero_drops_the_row_and_reports_it() -> None:
    triage = load_triage(
        [_sheet_row(is_poster="0"), _sheet_row(poster_uuid=UUID_B)], SHEET
    )

    kept, skipped, notes = apply_triage(
        [_poster_row(UUID_A, "ไม่ใช่โปสเตอร์"), _poster_row(UUID_B)], triage, SHEET
    )

    assert [r["id"] for r in kept] == [UUID_B]
    assert skipped == {UUID_A}
    assert any("ไม่ใช่โปสเตอร์" in n for n in notes)


def test_sheet_rows_outside_this_batch_are_a_note_not_an_error() -> None:
    """ใบเซ็นรับกว้างกว่าชุดที่ seed รอบนี้ได้ — ต่างจากรูปที่อ้างโปสเตอร์ไม่มีจริง"""
    triage = load_triage(
        [_sheet_row(), _sheet_row(poster_uuid=UUID_B)],
        SHEET,
    )

    kept, skipped, notes = apply_triage([_poster_row(UUID_A)], triage, SHEET)

    assert [r["id"] for r in kept] == [UUID_A]
    assert not skipped
    assert any("ไม่อยู่ในชุด seed" in n for n in notes)


def test_needs_review_from_the_sheet_never_reaches_the_row() -> None:
    """🔴 ADR-0009 D6 + ADR-0010 D2 — คนกรอก 0 ก็ยังต้องลง DB เป็น true

    ล็อกไว้เพราะเป็นจุดที่ดูเหมือน "ทำต่อให้ครบ" ที่สุด · การเปลี่ยนต้องเป็น amendment
    ของ ADR ทั้งสองฉบับ ไม่ใช่แก้สคริปต์
    """
    triage = load_triage([_sheet_row(needs_review="0")], SHEET)

    kept, _, _ = apply_triage([_poster_row()], triage, SHEET)

    assert kept[0]["needs_review"] is True


def test_duplicate_poster_uuid_in_seed_csv_collapses_to_one_sheet_row() -> None:
    """1 แถว = 1 ใบ ไม่ใช่ 1 แถวของ CSV

    posters-seed-v2.csv มี poster_uuid ซ้ำได้จริง (ยืนยันกับไฟล์จริง: 118 แถว = 117 ใบ)
    ถ้าปล่อยซ้ำเข้าใบงาน load_triage() จะปฏิเสธทั้งไฟล์ — เจอตอนรันกับข้อมูลจริง
    ไม่ใช่ตอนเขียนเทส
    """
    same_uuid = [
        {
            "poster_uuid": UUID_A,
            "title": "A",
            "original_name": "N",
            "quantity": "1",
            "price_thb": price,
        }
        for price in ("3990", "890")
    ]

    rows = build_sheet_rows(same_uuid, [])

    assert len(rows) == 1
    assert rows[0]["price_thb"] == "3990"  # แถวแรกชนะ
    load_triage([{**rows[0], "is_poster": "1", "needs_review": "1"}], SHEET)
