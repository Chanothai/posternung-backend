"""Unit tests ของ `scripts/seed/make_review_sheet.py` — ADR-0010 D5

จุดสำคัญที่สุดที่ต้องล็อก: สคริปต์นี้ **ห้ามกรอก `approved`/`corrected_text` ให้**
ถ้าเครื่องกรอกสองคอลัมน์นี้ = เครื่องเซ็นรับงานของเครื่องเอง ขัด ADR-0009 D6
"""

from __future__ import annotations

import ast
import inspect

import pytest

from scripts.seed import make_review_sheet as mod
from scripts.seed.apply_suggestions import REVIEW_SHEET_COLUMNS
from scripts.seed.make_review_sheet import STATUS_ORDER, build_sheet_rows, classify


def _sugg(**over: str) -> dict[str, str]:
    row = {
        "poster_uuid": "11111111-1111-1111-1111-111111111111",
        "field": "release_date",
        "value": "March 18",
        "confidence": "high",
        "evidence": "ข้อความล่างสุด",
        "image_url": "https://example.invalid/a.jpg",
    }
    row.update(over)
    return row


# --- การจำแนกสถานะ ---


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        # ครบสามส่วน
        ("20/7/2023", "ok"),
        ("10 มกราคม 2562", "ok"),  # พ.ศ.
        ("11.16.12", "ok"),
        # รู้เดือน+วัน ขาดปี
        ("March 18", "no_year"),
        ("MAY 1", "no_year"),
        ("15 กุมภาพันธ์", "no_year"),
        ("พุธที่ 15 กุมภาพันธ์", "no_year"),
        ("11.19", "no_year"),  # ตัวเลขล้วน 19 > 12 จึงรู้ว่าใครวันใครเดือน
        ("7.15", "no_year"),
        # รู้เดือน+ปี ขาดวัน
        ("MARCH 2022", "no_day"),
        ("February 2005", "no_day"),
        ("JULY 2004", "no_day"),
        # รู้แค่เดือน ขาดทั้งวันและปี
        ("MARCH", "no_day_no_year"),
        ("AUGUST", "no_day_no_year"),
        ("DECEMBER", "no_day_no_year"),
        # อ่านไม่ออกเลย
        ("2022", "failed"),
        ("SUMMER 2010", "failed"),
        ("COMING SOON", "failed"),
        # กำกวม DD/MM ↔ MM/DD
        ("05/06/23", "ambiguous"),
    ],
)
def test_classify(text: str, expected: str) -> None:
    assert classify(text) == expected


def test_month_only_is_not_lumped_into_no_day_or_no_year() -> None:
    """🔴 เหตุผลที่ `no_day_no_year` ต้องมีอยู่: ถ้ายุบ 'MARCH' เข้า no_day คนตรวจจะ
    เห็นว่า "ขาดแค่วัน" แล้วเติมแค่วัน พอส่งกลับเข้า parser ก็ยังไม่ครบเพราะไม่มีปี
    — สถานะที่บอกความจริงไม่หมดทำให้คนทำงานผิด เสียรอบตรวจฟรี ๆ"""
    assert classify("MARCH") not in {"no_day", "no_year"}


def test_every_classification_has_a_sort_position() -> None:
    """ถ้ามีใครเพิ่มสถานะใหม่แล้วลืมใส่ใน STATUS_ORDER สคริปต์จะ KeyError ตอน sort
    — จับตั้งแต่ test ดีกว่าจับตอนรันจริงกับ 41 แถว"""
    statuses = {
        classify(t)
        for t in ("20/7/2023", "March 18", "MARCH 2022", "MARCH", "2022", "05/06/23")
    }
    assert statuses <= set(STATUS_ORDER)


# --- โครงใบงาน ---


def test_sheet_uses_the_column_list_shared_with_the_applier() -> None:
    """คอลัมน์ประกาศที่เดียวใน apply_suggestions.py — ที่นี่ import ไปใช้ ไม่เขียนซ้ำ"""
    rows = build_sheet_rows([_sugg()])
    assert tuple(rows[0]) == REVIEW_SHEET_COLUMNS


def test_approved_and_corrected_text_are_always_left_empty() -> None:
    """🔴 กฎที่สำคัญที่สุดของสคริปต์นี้ (ADR-0009 D6 · ADR-0010 D5) — เครื่องเสนอได้
    แต่เซ็นรับแทนคนไม่ได้"""
    rows = build_sheet_rows([_sugg(), _sugg(value="20/7/2023")])
    assert all(r["approved"] == "" for r in rows)
    assert all(r["corrected_text"] == "" for r in rows)


def test_generator_never_writes_into_the_two_human_columns() -> None:
    """ล็อกที่ระดับซอร์ส — ถ้ามีใครเพิ่ม flag ให้เติม approved อัตโนมัติในอนาคต
    ต้องแดงทันที · ตรวจว่าไม่มี literal ของสองคอลัมน์นี้ถูก assign ค่าที่ไม่ใช่ค่าว่าง
    """
    tree = ast.parse(inspect.getsource(mod.build_sheet_rows))
    for node in ast.walk(tree):
        if not isinstance(node, ast.Dict):
            continue
        for key, value in zip(node.keys, node.values):
            if (
                isinstance(key, ast.Constant)
                and key.value in {"approved", "corrected_text"}
                and isinstance(value, ast.Constant)
            ):
                assert value.value == "", f"{key.value} ถูกกรอกค่าให้: {value.value!r}"


def test_only_release_date_rows_with_a_value_are_included() -> None:
    rows = build_sheet_rows(
        [
            _sugg(value="March 18"),
            _sugg(field="copyright_year", value="1999"),  # คนละฟิลด์
            _sugg(value=""),  # AI อ่านไม่ได้ ไม่มีอะไรให้ตรวจ
        ]
    )
    assert len(rows) == 1
    assert rows[0]["release_date_text"] == "March 18"


def test_non_ok_rows_sort_before_ok_rows() -> None:
    rows = build_sheet_rows(
        [
            _sugg(
                poster_uuid="00000000-0000-0000-0000-000000000001", value="20/7/2023"
            ),
            _sugg(poster_uuid="00000000-0000-0000-0000-000000000002", value="MARCH"),
            _sugg(poster_uuid="00000000-0000-0000-0000-000000000003", value="2022"),
        ]
    )
    assert [r["parse_status"] for r in rows] == ["failed", "no_day_no_year", "ok"]


def test_parsed_date_filled_only_when_fully_parsed() -> None:
    rows = build_sheet_rows(
        [
            _sugg(
                poster_uuid="00000000-0000-0000-0000-000000000001", value="20/7/2023"
            ),
            _sugg(poster_uuid="00000000-0000-0000-0000-000000000002", value="March 18"),
        ]
    )
    by_status = {r["parse_status"]: r for r in rows}
    assert by_status["ok"]["parsed_date"] == "2023-07-20"
    assert by_status["no_year"]["parsed_date"] == ""


def test_evidence_and_image_url_are_carried_over_for_the_human() -> None:
    """คนตรวจต้องเปิดรูปดูได้จากแถวเดียวกัน ไม่ต้องไปเปิดไฟล์อื่นเทียบเอง"""
    rows = build_sheet_rows(
        [_sugg(evidence="ข้อความล่างสุด", image_url="https://x/y.jpg")]
    )
    assert rows[0]["evidence"] == "ข้อความล่างสุด"
    assert rows[0]["image_url"] == "https://x/y.jpg"
