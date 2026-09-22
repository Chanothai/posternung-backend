"""Unit tests ของ `assert_no_zero_quantity_rows()` — ประตูนำเข้าบานที่ 1
(ADR-0019 D9 ข้อ 1 · ADR-0024 D5, INF-22)

ไม่ต่อ DB จริง — ฟังก์ชัน pure รับ list ของ raw CSV row เข้ามา (ทรงเดียวกับ
`load_triage()` ที่มีอยู่แล้วในไฟล์เดียวกัน)

ท้ายไฟล์ (§main()/run()) เพิ่มเทสที่วิ่งผ่าน `main()` จริง — ยังไม่ต่อ DB จริงเช่นกัน
(`MANIFEST_CSV`/`RESULT_CSV` ถูกชี้ไปไฟล์ที่ไม่มีอยู่จริงเสมอ) แต่พิสูจน์จุดต่อของ
ฟังก์ชันด่านนี้เข้า `run()` ซึ่งไม่เคยมีเทสไหนแตะมาก่อน
"""

from __future__ import annotations

import csv
import sys
from pathlib import Path

import pytest

from scripts.seed import seed_posters as mod
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


# --------------------------------------------------------------------------
# main()/run() — จุดต่อของ assert_no_zero_quantity_rows() (INF-22 High สุดท้าย)
# --------------------------------------------------------------------------
#
# 🔴 ด่านข้างบนมีเทสของ*ตัวฟังก์ชัน*ครบทุกกิ่งแล้ว แต่ **สายที่ต่อมันเข้า `run()` ไม่เคย
# ถูกแตะเลย** เพราะไม่มีเทสไหนในโปรเจกต์เรียก `mod.main()`/`mod.run()` ของสคริปต์นี้มา
# ก่อน — รูปเดียวกับ G5 ของ INF-21 (`test_correction_entry.py` §G5 — commit
# 98756d7/68cc030) mutation ที่ถอด `assert_no_zero_quantity_rows(posters_csv)` ออก
# จาก `run()` (แทนด้วย `pass`) จะทำให้แถว `quantity = 0` หลุดผ่านไปถึงขั้นถัดไปได้ทั้งที่
# ADR-0019 D9 ข้อ 1 ห้ามไว้ — แม้ฟังก์ชันด่านเองจะยังถูกต้อง 100% ก็ตาม

DEV_URL_FOR_MAIN = "postgresql+asyncpg://u:p@localhost:5432/poster_nung_dev_test7"


def _write_posters_csv(path: Path, rows: list[dict[str, str]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=["idx", "poster_uuid", "quantity"])
        writer.writeheader()
        writer.writerows(rows)


def _install_seed_posters_cli(monkeypatch, *argv: str) -> None:
    """ต่อ `sys.argv` จริงเข้า `main()` — `_load_dev_env()` ถูกแทนด้วย no-op ด้วยเหตุผล
    เดียวกับ `_install_cli()` ของ `test_correction_entry.py` (`.env` ของเครื่องที่รัน
    ทำให้เทสไม่ deterministic ข้ามเครื่อง)
    """
    monkeypatch.setattr(mod, "_load_dev_env", lambda: None)
    monkeypatch.setenv("DATABASE_URL", DEV_URL_FOR_MAIN)
    monkeypatch.setattr(sys, "argv", ["seed_posters.py", *argv])


def test_run_stops_at_the_quantity_gate_before_reading_the_manifest(
    monkeypatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """🔴 ตัวฆ่า mutation ที่ถอด `assert_no_zero_quantity_rows()` ออกจาก `run()`

    `MANIFEST_CSV`/`RESULT_CSV` ถูกชี้ไปไฟล์ที่ไม่มีอยู่จริง**โดยตั้งใจ** — ถ้าด่านนี้
    หายไป โค้ดจะเดินต่อไปอ่านไฟล์เหล่านั้นและพังด้วยข้อความคนละเรื่อง ("ไม่พบไฟล์" แทน
    "quantity = 0") ⚠️ ห้ามชี้ไปไฟล์จริงบนเครื่องพัฒนา (`scripts/seed/*.csv` ไม่อยู่ใน
    git — `.gitignore`) เพราะทำให้เทสไม่ deterministic ข้ามเครื่อง และถ้าด่านหายไปจริง
    อาจไหลต่อไปแตะ DATABASE_URL จริงบนเครื่องนั้น
    """
    posters_csv = tmp_path / "posters-seed-v2.csv"
    _write_posters_csv(
        posters_csv,
        [
            {"idx": "1", "poster_uuid": "uuid-1", "quantity": "1"},
            {"idx": "2", "poster_uuid": "uuid-2", "quantity": "0"},
        ],
    )
    monkeypatch.setattr(mod, "POSTERS_CSV", posters_csv)
    monkeypatch.setattr(mod, "MANIFEST_CSV", tmp_path / "no-such-manifest.csv")
    monkeypatch.setattr(mod, "RESULT_CSV", tmp_path / "no-such-result.csv")

    calls: list[Path] = []
    real_read_csv = mod._read_csv

    def spy_read_csv(path: Path) -> list[dict[str, str]]:
        calls.append(path)
        return real_read_csv(path)

    monkeypatch.setattr(mod, "_read_csv", spy_read_csv)
    _install_seed_posters_cli(monkeypatch)

    assert mod.main() == 2
    captured = capsys.readouterr()
    assert "quantity = 0" in captured.err
    assert "idx 2" in captured.err
    # พฤติกรรม ไม่ใช่แค่ข้อความ — ไม่ไปแตะ manifest/result เลย (ถ้าด่านหายไป calls
    # จะมีสองไฟล์ ไม่ใช่ไฟล์เดียว)
    assert calls == [posters_csv]


def test_run_passes_the_gate_with_nonzero_quantities_and_reaches_the_manifest_read(
    monkeypatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """positive control ของทั้ง §main()/run() — ถ้าไม่มีตัวนี้ ชุดข้างบนเขียวได้ด้วย
    `run()` ที่ปฏิเสธทุกไฟล์เสมอ (รูปเดียวกับ `test_a_dev_url_that_passes_the_guard_
    still_reaches_the_write` ของ INF-21 G5) — ยืนยันว่าข้อมูลที่ถูกต้องผ่านด่านนี้ไปถึง
    ขั้นอ่าน manifest จริง (ซึ่งพังด้วยเหตุผลอื่นที่ไม่ใช่ quantity)

    🔴 ไม่ไปไกลถึงขั้นเขียนจริงเหมือน G5 — `run()` เปิด `create_async_engine()` ทันที
    หลัง precheck ทั้งหมดผ่าน แม้แต่ dry-run ก็ยังต้อง SELECT จริงกับ DB เพื่อรู้ว่าแถว
    ไหนมีอยู่แล้ว (`existing_posters`/`existing_keys`) การปลอม SQLAlchemy async engine
    ทั้งชุดให้ครบทุก query shape เกินขอบเขตของการปิดช่องโหว่นี้ — ด่านที่ตรวจอยู่คือ
    "ข้อมูลถูกต้องต้องไม่ถูกบล็อก" ซึ่งพิสูจน์ได้แค่ไปถึงขั้นถัดไปก็พอ
    """
    posters_csv = tmp_path / "posters-seed-v2.csv"
    _write_posters_csv(
        posters_csv, [{"idx": "1", "poster_uuid": "uuid-1", "quantity": "1"}]
    )
    manifest_csv = tmp_path / "no-such-manifest.csv"
    monkeypatch.setattr(mod, "POSTERS_CSV", posters_csv)
    monkeypatch.setattr(mod, "MANIFEST_CSV", manifest_csv)
    monkeypatch.setattr(mod, "RESULT_CSV", tmp_path / "no-such-result.csv")
    _install_seed_posters_cli(monkeypatch)

    assert mod.main() == 2
    captured = capsys.readouterr()
    assert "quantity = 0" not in captured.err
    assert f"ไม่พบไฟล์ {manifest_csv}" in captured.err
