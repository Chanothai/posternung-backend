"""เทสของ `scripts/seed/sold_entry.py` (ADR-0025 · INF-24)

🔴 **จำกัดไว้เฉพาะด่านระดับ argparse ที่ตัดสิน "ก่อน" แตะ DB เสมอ** — เพื่อไม่ให้เทส
หน่วยต้องพึ่งว่ามี dev container รันอยู่จริง เทสในไฟล์นี้ทุกตัว monkeypatch `_load_env`
ให้ raise ถ้าถูกเรียก แล้วพิสูจน์ว่าด่านที่ทดสอบ raise `SystemExit(2)` ก่อนถึงจุดนั้น
เสมอ — ทรงเดียวกับ `test_a_future_reviewed_at_is_refused_at_the_cli_before_anything_is_read`
ใน `test_seed_lane_shared_rules.py` ที่ชี้ `--file` ไปไฟล์ไม่มีจริงเพื่อบังคับให้จบก่อน
ถึงชั้นอ่านไฟล์ — เส้นนี้ไม่มีไฟล์ให้ชี้ จึงใช้ monkeypatch แทน

เทสของฝั่ง service (`mark_sold()` เอง) อยู่ที่ `tests/unit/test_poster_service.py`
"""

from __future__ import annotations

import re
import sys

import pytest

from scripts.seed import sold_entry
from scripts.seed._shared import PrecheckError

BASE_ARGS = ("--poster-uuid", "11111111-1111-1111-1111-111111111111")


def _argv(monkeypatch, *args: str) -> None:
    monkeypatch.setattr(sys, "argv", ["sold_entry.py", *args])


def _forbid_load_env(monkeypatch) -> None:
    """ยืนยันว่าด่านที่ทดสอบจบก่อนถึง `_load_env()`/DB เสมอ."""

    def _boom(*_a, **_k):
        raise AssertionError(
            "ไม่ควรถูกเรียก — ด่านที่ทดสอบต้องจบก่อนถึง _load_env()/DB เสมอ"
        )

    monkeypatch.setattr(sold_entry, "_load_env", _boom)


# --------------------------------------------------------------------------
# _parse_sold_at() — pure, ไม่แตะ DB
# --------------------------------------------------------------------------


def test_parse_sold_at_requires_timezone() -> None:
    with pytest.raises(PrecheckError, match="timezone"):
        sold_entry._parse_sold_at("2026-08-04T13:30:00")


def test_parse_sold_at_rejects_non_iso() -> None:
    with pytest.raises(PrecheckError, match="ISO-8601"):
        sold_entry._parse_sold_at("4 ส.ค. 2026")


def test_parse_sold_at_accepts_iso_with_offset() -> None:
    value = sold_entry._parse_sold_at("2026-08-04T13:30:00+07:00")
    assert value.tzinfo is not None


def test_parse_sold_at_error_mentions_the_flag_not_reviewed_at() -> None:
    """🔴 บั๊กที่เกือบเกิด — ถ้าใช้ `_parse_reviewed_at()` ตรงๆ ข้อความจะพิมพ์
    `--reviewed-at` ทั้งที่ผู้ใช้พิมพ์ `--sold-at` ผิด (`_parse_sold_at` เขียนแยกไว้
    เพื่อกันเคสนี้ — ดู docstring ของมัน)"""
    with pytest.raises(PrecheckError) as exc:
        sold_entry._parse_sold_at("not-a-date")
    assert "--sold-at" in str(exc.value)


# --------------------------------------------------------------------------
# main() — ด่านที่ต้องจบก่อนแตะ DB
# --------------------------------------------------------------------------


def test_main_rejects_blank_reason(monkeypatch, capsys) -> None:
    _forbid_load_env(monkeypatch)
    _argv(
        monkeypatch,
        *BASE_ARGS,
        "--sold-at",
        "2020-01-01T00:00:00+07:00",
        "--reason",
        "   ",
    )

    with pytest.raises(SystemExit) as exc:
        sold_entry.main()

    assert exc.value.code == 2
    assert "--reason" in capsys.readouterr().err


def test_main_rejects_malformed_sold_at(monkeypatch, capsys) -> None:
    _forbid_load_env(monkeypatch)
    _argv(
        monkeypatch,
        *BASE_ARGS,
        "--sold-at",
        "not-a-date",
        "--reason",
        "ทดสอบ",
    )

    with pytest.raises(SystemExit) as exc:
        sold_entry.main()

    assert exc.value.code == 2
    assert "--sold-at" in capsys.readouterr().err


def test_main_rejects_future_sold_at(monkeypatch, capsys) -> None:
    """AC-3 — ปฏิเสธเวลาในอนาคตตั้งแต่ `main()` ก่อนเรียก `_load_env()`/เปิด session"""
    _forbid_load_env(monkeypatch)
    _argv(
        monkeypatch,
        *BASE_ARGS,
        "--sold-at",
        "3000-01-01T00:00:00+07:00",
        "--reason",
        "ทดสอบ",
    )

    with pytest.raises(SystemExit) as exc:
        sold_entry.main()

    assert exc.value.code == 2
    err = capsys.readouterr().err
    assert re.search(r"อนาคต\s+\d", err), err


def test_main_dry_run_does_not_require_reviewed_by_or_reviewed_at(
    monkeypatch,
) -> None:
    """dry-run ไม่บังคับ --reviewed-by/--reviewed-at — เดินผ่านด่าน argparse จนถึง
    _load_env() ได้โดยไม่ raise SystemExit(2) จากด่านสองตัวนั้น (พิสูจน์ด้วยการปล่อยให้
    _load_env() ถูกเรียกจริงหนึ่งครั้งแล้วหยุดที่นั่นด้วย exception ที่คุมเอง)"""
    reached = False

    def _stop_here(*_a, **_k):
        nonlocal reached
        reached = True
        raise RuntimeError("หยุดตรงนี้พอ — พิสูจน์แล้วว่าด่าน args ผ่านหมด")

    monkeypatch.setattr(sold_entry, "_load_env", _stop_here)
    _argv(
        monkeypatch,
        *BASE_ARGS,
        "--sold-at",
        "2020-01-01T00:00:00+07:00",
        "--reason",
        "ทดสอบ",
    )

    with pytest.raises(RuntimeError):
        sold_entry.main()

    assert reached is True


def test_main_commit_requires_reviewed_by(monkeypatch, capsys) -> None:
    _forbid_load_env(monkeypatch)
    _argv(
        monkeypatch,
        *BASE_ARGS,
        "--commit",
        "--sold-at",
        "2020-01-01T00:00:00+07:00",
        "--reason",
        "ทดสอบ",
    )

    with pytest.raises(SystemExit) as exc:
        sold_entry.main()

    assert exc.value.code == 2
    assert "--reviewed-by" in capsys.readouterr().err


def test_main_commit_requires_reviewed_at(monkeypatch, capsys) -> None:
    _forbid_load_env(monkeypatch)
    _argv(
        monkeypatch,
        *BASE_ARGS,
        "--commit",
        "--sold-at",
        "2020-01-01T00:00:00+07:00",
        "--reason",
        "ทดสอบ",
        "--reviewed-by",
        "tester",
    )

    with pytest.raises(SystemExit) as exc:
        sold_entry.main()

    assert exc.value.code == 2
    assert "--reviewed-at" in capsys.readouterr().err


def test_main_commit_rejects_future_reviewed_at(monkeypatch, capsys) -> None:
    _forbid_load_env(monkeypatch)
    _argv(
        monkeypatch,
        *BASE_ARGS,
        "--commit",
        "--sold-at",
        "2020-01-01T00:00:00+07:00",
        "--reason",
        "ทดสอบ",
        "--reviewed-by",
        "tester",
        "--reviewed-at",
        "3000-01-01T00:00:00+07:00",
    )

    with pytest.raises(SystemExit) as exc:
        sold_entry.main()

    assert exc.value.code == 2
    err = capsys.readouterr().err
    assert re.search(r"อนาคต\s+\d", err), err


def test_main_no_target_choice_other_than_dev_or_sit() -> None:
    """AC-7 · ADR-0015 D8 — ไม่มี `production` ให้เลือกเลยที่ระดับ argparse `choices`"""
    assert sold_entry.TARGETS == ("dev", "sit")
