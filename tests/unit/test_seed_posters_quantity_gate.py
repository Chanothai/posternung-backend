"""Unit tests ของ `assert_no_zero_quantity_rows()` — ประตูนำเข้าบานที่ 1
(ADR-0019 D9 ข้อ 1 · ADR-0024 D5, INF-22)

ไม่ต่อ DB จริง — ฟังก์ชัน pure รับ list ของ raw CSV row เข้ามา (ทรงเดียวกับ
`load_triage()` ที่มีอยู่แล้วในไฟล์เดียวกัน)
"""

from __future__ import annotations

import pytest

from scripts.seed.seed_posters import PrecheckError, assert_no_zero_quantity_rows


def _row(**over: str) -> dict[str, str]:
    row = {"idx": "1", "poster_uuid": "poster-uuid-1", "quantity": "1"}
    row.update(over)
    return row


def test_no_rows_is_fine() -> None:
    assert assert_no_zero_quantity_rows([]) is None


def test_all_nonzero_quantities_pass() -> None:
    rows = [_row(idx="1", quantity="1"), _row(idx="2", quantity="5")]
    assert assert_no_zero_quantity_rows(rows) is None


def test_a_single_zero_quantity_row_rejects_the_whole_file() -> None:
    rows = [_row(idx="1", quantity="1"), _row(idx="2", quantity="0")]
    with pytest.raises(PrecheckError, match="quantity = 0"):
        assert_no_zero_quantity_rows(rows)


def test_the_error_names_every_bad_row_not_just_the_first() -> None:
    """🔴 ทรงเดียวกับ `load_triage()` — พิมพ์ `idx`/`poster_uuid` ของ*ทุก*แถวที่ผิด"""
    rows = [
        _row(idx="10", poster_uuid="uuid-a", quantity="0"),
        _row(idx="20", poster_uuid="uuid-b", quantity="1"),
        _row(idx="30", poster_uuid="uuid-c", quantity="0"),
    ]
    with pytest.raises(PrecheckError) as exc:
        assert_no_zero_quantity_rows(rows)
    text = str(exc.value)
    assert "idx 10" in text and "uuid-a" in text
    assert "idx 30" in text and "uuid-c" in text
    assert "idx 20" not in text  # แถวที่ถูกต้องต้องไม่ถูกพิมพ์เป็นปัญหา


def test_a_blank_quantity_cell_counts_as_zero() -> None:
    """ช่องว่างในคอลัมน์นี้แปลว่าไม่มีตัวเลข ไม่ใช่ 'ไม่รู้' — ปฏิบัติเหมือน 0"""
    rows = [_row(quantity="")]
    with pytest.raises(PrecheckError, match="quantity = 0"):
        assert_no_zero_quantity_rows(rows)


def test_a_non_numeric_quantity_also_rejects_the_whole_file() -> None:
    rows = [_row(quantity="abc")]
    with pytest.raises(PrecheckError, match="อ่านไม่ออก"):
        assert_no_zero_quantity_rows(rows)


def test_there_is_no_skip_flag_the_message_points_at_fixing_the_csv() -> None:
    rows = [_row(quantity="0")]
    with pytest.raises(PrecheckError, match="ไม่มี flag ข้าม"):
        assert_no_zero_quantity_rows(rows)
