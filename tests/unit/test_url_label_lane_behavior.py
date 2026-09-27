"""AC-4 ของ INF-51 (BL-167) — พฤติกรรมจริงของ `main()` ต่อ lane เมื่อ `DATABASE_URL`

มี password ที่แยกส่วนไม่ได้ (`/` `?` `#` โดยไม่ percent-encode)

🔴 **ต่างจาก `test_url_label_lanes.py`** — ไฟล์นั้นล็อก *สายไฟ* ด้วย AST (ค่าที่ผูกกับ
`target_label` มาจาก Call ของฟังก์ชันผลิตป้ายเท่านั้น) ไฟล์นี้พิสูจน์ *พฤติกรรมจริง*
ที่ `main()` ของทั้ง 7 เส้นของ `TARGET_GUARD_LANES` — เดินผ่าน argparse จริง เรียก
`main()` จริง แล้วยืนยันว่า stdout+stderr ไม่มีเศษ credential หลุดออกมาเลยไม่ว่าจะ
เดินไปทางไหน (ก)(ข)(ค) — เหตุผลที่ต้องมีคู่กัน: AST พิสูจน์ได้แค่ว่า *มีสายไฟ* ไม่ได้
พิสูจน์ว่า `assert_target()` (`manual_entry.py`) เองไม่ได้เอาป้ายที่ `assert_target_
database()` คืนมาแล้วไปประกอบใหม่จาก `host`/`db_name` ดิบอีกทีหลังจากนั้น — มิวเทชัน
ที่พิสูจน์แล้วว่า AST จับไม่ได้ (`code-critic` critic round 1 INF-51 · mutant MA:
แก้ `manual_entry.assert_target()` ให้สร้างป้ายเองจาก `host`/`db_name` **หลัง** เรียก
`assert_target_database()` แล้ว) — AST เห็นแค่ว่า `main()` เรียก `assert_target(...)`
ถูกต้อง แต่ไม่รู้ว่า *ข้างในฟังก์ชันนั้น* เอาค่าที่ได้มาทิ้งแล้วสร้างใหม่หรือเปล่า

closed-world: `LANE_ARGV` ต้องมีครบทุกเส้นใน `TARGET_GUARD_LANES` — เส้นที่แปดในอนาคต
ที่ไม่มี spec ในนี้ต้องทำให้คอลเลกชันเทสพัง ไม่ใช่ถูกข้ามไปเงียบ ๆ
"""

from __future__ import annotations

import sys

import pytest

from scripts.seed import apply_suggestions as suggest_mod
from scripts.seed import manual_entry as manual_mod
from tests.unit.test_seed_lane_shared_rules import TARGET_GUARD_IDS, TARGET_GUARD_LANES

LEAK_USER = "leakuser"
SLASH_PW = "s3cr3t/xyz"
QUESTION_PW = "ab?cd"
HASH_PW = "ab#cd"
LEAKING_PASSWORDS = (SLASH_PW, QUESTION_PW, HASH_PW)

FORBIDDEN_SUBSTRINGS = (
    LEAK_USER,
    "s3cr3t",
    "xyz",
    QUESTION_PW,
    HASH_PW,
    "postgresql",
    "@",
)

PAST_ISO = "2020-01-01T00:00:00+07:00"
POSTER_UUID = "11111111-1111-1111-1111-111111111111"


def _leaky_url(password: str) -> str:
    return f"postgresql+asyncpg://{LEAK_USER}:{password}@localhost:5432/poster_nung_db"


# --------------------------------------------------------------------------
# argv ต่อ lane — เท่าที่ต้องมีให้ dry-run เดินถึง `_load_env()`/`assert_target()`
# ได้จริง (ดูพาร์เซอร์ของแต่ละไฟล์ก่อนเขียน — ไม่ใช่เดา)
# --------------------------------------------------------------------------


def _manual_entry_argv(target: str) -> list[str]:
    return ["manual_entry.py", "--target", target]


def _correction_entry_argv(target: str) -> list[str]:
    return ["correction_entry.py", "--target", target]


def _reference_entry_argv(target: str) -> list[str]:
    return ["reference_entry.py", "--target", target]


def _split_entry_argv(target: str) -> list[str]:
    return ["split_entry.py", "--target", target]


def _sold_entry_argv(target: str) -> list[str]:
    return [
        "sold_entry.py",
        "--poster-uuid",
        POSTER_UUID,
        "--sold-at",
        PAST_ISO,
        "--reason",
        "ทดสอบ",
        "--target",
        target,
    ]


def _photo_entry_argv(target: str) -> list[str]:
    return ["photo_entry.py", "--target", target]


def _order_ops_argv(target: str) -> list[str]:
    return [
        "order_ops.py",
        "complete",
        "--order-no",
        "PN-260918-0001",
        "--actor",
        "admin@example.test",
        "--at",
        PAST_ISO,
        "--target",
        target,
    ]


LANE_ARGV = {
    "manual_entry": _manual_entry_argv,
    "correction_entry": _correction_entry_argv,
    "reference_entry": _reference_entry_argv,
    "split_entry": _split_entry_argv,
    "sold_entry": _sold_entry_argv,
    "photo_entry": _photo_entry_argv,
    "order_ops": _order_ops_argv,
}

# closed-world — เส้นที่แปดในอนาคตที่ไม่มี spec ในนี้ต้องทำให้ import พังทันที
# ไม่ใช่ถูกข้ามไปเงียบ ๆ (ทรงเดียวกับด่านอื่นของไฟล์นี้กลุ่ม)
assert set(LANE_ARGV) == set(TARGET_GUARD_IDS), (
    f"LANE_ARGV ({sorted(LANE_ARGV)}) ไม่ตรงกับ TARGET_GUARD_IDS "
    f"({sorted(TARGET_GUARD_IDS)}) — เส้นใหม่ต้องมี argv spec ที่นี่ก่อน"
)


def _fake_env(
    monkeypatch: pytest.MonkeyPatch, files: dict[str, dict[str, str]]
) -> None:
    """แทน `_parse_env_file` ทั้งของ `manual_entry` (ชั้นที่สอง D8) และของ
    `apply_suggestions` (ชั้นแรก D7) — ทั้ง 7 เส้นเรียก `assert_target()` ตัวเดียวกัน
    ที่ wrap สองชั้นนี้ ไม่ว่า `main()` ของเส้นไหนจะเรียก"""

    def fake(path: object) -> dict[str, str]:
        return files.get(getattr(path, "name", str(path)), {})

    monkeypatch.setattr(manual_mod, "_parse_env_file", fake)
    monkeypatch.setattr(suggest_mod, "_parse_env_file", fake)


def _combined_output(capsys: pytest.CaptureFixture[str]) -> str:
    captured = capsys.readouterr()
    return captured.out + captured.err


def _assert_no_leak(text: str) -> None:
    for forbidden in FORBIDDEN_SUBSTRINGS:
        assert forbidden not in text, f"{forbidden!r} หลุดออกมาใน output: {text!r}"


# --------------------------------------------------------------------------
# (ก) เส้นทางสำเร็จ — url แยกส่วนไม่ได้แต่ตรงกับ .env.sit เป๊ะ (string เท่ากัน)
# --------------------------------------------------------------------------


@pytest.mark.parametrize("password", LEAKING_PASSWORDS)
@pytest.mark.parametrize("module", TARGET_GUARD_LANES, ids=TARGET_GUARD_IDS)
def test_success_path_passes_the_marker_label_into_run_never_the_raw_url(
    module, password: str, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    """🔴 mutant MA (`code-critic` round 1) — ถ้า `manual_entry.assert_target()`
    เอาป้ายที่ปลอดภัยจาก `assert_target_database()` มาทิ้งแล้วประกอบใหม่จาก
    `host`/`db_name` ดิบเอง เทสนี้ต้องแดงทันทีในทุกเส้นที่เรียก `assert_target()`
    """
    url = _leaky_url(password)
    argv_factory = LANE_ARGV[module.__name__.rsplit(".", 1)[-1]]

    _fake_env(monkeypatch, {".env.sit": {"DATABASE_URL": url}})
    monkeypatch.delenv("ENVIRONMENT", raising=False)
    monkeypatch.setenv("DATABASE_URL", url)

    calls: list[tuple[tuple, dict]] = []

    async def fake_run(*args: object, **kwargs: object) -> int:
        calls.append((args, kwargs))
        return 0

    monkeypatch.setattr(module, "run", fake_run)
    monkeypatch.setattr(sys, "argv", argv_factory("sit"))

    rc = module.main()

    assert rc == 0, _combined_output(capsys)
    assert len(calls) == 1, f"{module.__name__}: run() ถูกเรียก {len(calls)} ครั้ง"
    args, kwargs = calls[0]
    # ทุกเส้นเรียก run(args_ns, target_label, ...) — target_label คือ positional ตัวที่ 2
    assert len(args) >= 2, f"{module.__name__}: run() ได้ positional args {args!r}"
    target_label = args[1]
    assert target_label.startswith(suggest_mod.UNPARSEABLE_URL_LABEL), (
        f"{module.__name__}: target_label ที่ส่งเข้า run() คือ {target_label!r} "
        "— ไม่ได้ขึ้นต้นด้วย marker"
    )
    _assert_no_leak(_combined_output(capsys))


# --------------------------------------------------------------------------
# (ข) precheck ① — --target dev + url แยกส่วนไม่ได้ ต้องถูกปฏิเสธก่อนเปิด session
# --------------------------------------------------------------------------


@pytest.mark.parametrize("password", LEAKING_PASSWORDS)
@pytest.mark.parametrize("module", TARGET_GUARD_LANES, ids=TARGET_GUARD_IDS)
def test_dev_precheck_rejects_the_leaking_url_without_calling_run(
    module, password: str, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    url = _leaky_url(password)
    argv_factory = LANE_ARGV[module.__name__.rsplit(".", 1)[-1]]

    _fake_env(monkeypatch, {})
    monkeypatch.delenv("ENVIRONMENT", raising=False)
    monkeypatch.setenv("DATABASE_URL", url)

    calls: list[object] = []

    async def fake_run(*args: object, **kwargs: object) -> int:
        calls.append((args, kwargs))
        return 0

    monkeypatch.setattr(module, "run", fake_run)
    monkeypatch.setattr(sys, "argv", argv_factory("dev"))

    rc = module.main()

    assert rc == 1, _combined_output(capsys)
    assert (
        calls == []
    ), f"{module.__name__}: run() ถูกเรียกทั้งที่ precheck ควรหยุดไว้ก่อน"
    _assert_no_leak(_combined_output(capsys))


# --------------------------------------------------------------------------
# (ค) precheck ② — --target sit แต่ไม่มี .env.sit เลย ต้องถูกปฏิเสธ (ไม่ว่าจะโดน
# ด่านชั้นไหนก็ตาม — ชั้นแรกหรือชั้นสองของ ADR-0015 D8 ก็ต้องไม่รั่วเหมือนกัน)
# --------------------------------------------------------------------------


@pytest.mark.parametrize("password", LEAKING_PASSWORDS)
@pytest.mark.parametrize("module", TARGET_GUARD_LANES, ids=TARGET_GUARD_IDS)
def test_sit_precheck_rejects_the_leaking_url_when_env_sit_is_missing(
    module, password: str, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    url = _leaky_url(password)
    argv_factory = LANE_ARGV[module.__name__.rsplit(".", 1)[-1]]

    _fake_env(monkeypatch, {})  # ไม่มี .env.sit เลย
    monkeypatch.delenv("ENVIRONMENT", raising=False)
    monkeypatch.setenv("DATABASE_URL", url)

    calls: list[object] = []

    async def fake_run(*args: object, **kwargs: object) -> int:
        calls.append((args, kwargs))
        return 0

    monkeypatch.setattr(module, "run", fake_run)
    monkeypatch.setattr(sys, "argv", argv_factory("sit"))

    rc = module.main()

    assert rc == 1, _combined_output(capsys)
    assert (
        calls == []
    ), f"{module.__name__}: run() ถูกเรียกทั้งที่ precheck ควรหยุดไว้ก่อน"
    _assert_no_leak(_combined_output(capsys))
