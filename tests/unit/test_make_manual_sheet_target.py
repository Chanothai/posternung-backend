"""`make_manual_sheet.py --target dev|sit` — INF-49

ใบงาน manual ชุด seed-v2 ใช้กับ DB ไหนไม่ได้อีกแล้ว (`BL-162`) — เครื่องมือนี้เป็น
ตัวเดียวที่สร้างใบงาน manual จาก DB ได้ แต่ล็อก `dev` ตายตัวมาตั้งแต่ `INF-11` ไฟล์นี้
ล็อกด่านที่เปิดให้ชี้ SIT ได้โดย **ไม่ผ่อน** ด่านเดิมสักข้อ (ADR-0015 D8) และไม่เปิด
`production` ในเครื่องมือนี้เลย (INF-49 AC-1 · AC-7(ค))

**สิ่งที่ไฟล์นี้ไม่ทดสอบซ้ำ** — ตรรกะภายในของ `assert_target()`/`assert_target_database()`
เอง (ชั้นแรก/ชั้นสอง ของ ADR-0010 D7 / ADR-0015 D8) มีเทสของตัวเองครบแล้วที่
`tests/unit/test_manual_entry.py` — ที่นี่ทดสอบแค่ว่า **`make_manual_sheet.main()`
ต่อสายเข้าด่านนั้นถูกจุด** และ **ไม่รั่วความลับออกมาตอนด่านนั้นปฏิเสธ/ตอนต่อ DB ไม่ติด**
"""

from __future__ import annotations

import ast
import inspect
import sys
from pathlib import Path

import pytest

from scripts._production_gate import TARGETS as PRODUCTION_TARGETS
from scripts.seed import apply_suggestions as suggest_mod
from scripts.seed import make_manual_sheet as mod
from scripts.seed import manual_entry as manual_mod

# ค่าที่ **มีคำว่า sit ปน** เพราะชั้นแรก (`assert_target_database`) มีทางผ่อนตอนไม่มี
# `.env.sit` (ยอมรับ url ที่ชื่อ database มีคำว่า "sit") — ใช้ค่านี้ในทุกเทสเพื่อไม่ให้
# ชั้นแรกปฏิเสธไปก่อนถึงด่านที่ต้องการทดสอบจริง (ทรงเดียวกับ test_manual_entry.py)
CLEAN_SIT_URL = "postgresql+asyncpg://u:p@db:5432/poster_nung_db_sit"
OTHER_SIT_URL = "postgresql+asyncpg://u:p@db:5432/somewhere_sit"
DEV_URL = "postgresql+asyncpg://u:p@localhost:5432/poster_nung_db"
# 🔴 รหัสผ่านมี `/` ไม่ percent-encode โดยตั้งใจ — `urlsplit` ตัด netloc ที่ `/` ตัวแรก
# ⇒ เศษรหัสผ่าน (`xyz`) ไหลไปอยู่ใน `path` ถ้าโค้ดพิมพ์ค่าที่แยกส่วนแบบนั้นออกมาตรง ๆ
# (บั๊กที่ `_url_label()`/INF-39 แก้ไว้แล้ว — เทสกลุ่มนี้ยืนยันว่า `make_manual_sheet.py`
# ไม่หลบไปพิมพ์ป้ายดิบที่ไม่ผ่านตัวกรองนั้นแทน)
SECRET_SIT_URL = "postgresql+asyncpg://u:s3cr3t/xyz@db:5432/poster_nung_db_sit"
FORBIDDEN_SUBSTRINGS = ("s3cr3t", "xyz", "postgresql", "@")


def _fake_env(
    monkeypatch: pytest.MonkeyPatch, files: dict[str, dict[str, str]]
) -> None:
    """แทน `_parse_env_file` ทั้งของ `manual_entry` และของ `apply_suggestions`

    ต้อง patch สองที่ — ทรงเดียวกับ `test_manual_entry.py::_fake_env` — เพราะ
    `assert_target()` (สอง layer) อ่านผ่านสอง namespace คนละที่กัน
    """

    def fake(path: object) -> dict[str, str]:
        return files.get(getattr(path, "name", str(path)), {})

    monkeypatch.setattr(manual_mod, "_parse_env_file", fake)
    monkeypatch.setattr(suggest_mod, "_parse_env_file", fake)


def _argv(tmp_path: Path, *extra: str, out: Path | None = None) -> list[str]:
    out_path = out if out is not None else tmp_path / "manual-entry-v3.csv"
    return ["make_manual_sheet.py", "--out", str(out_path), *extra]


def _unreachable_load_from_db() -> None:
    raise AssertionError(
        "load_from_db() ถูกเรียกทั้งที่ด่านก่อนหน้าควรหยุดสคริปต์ไว้แล้ว"
    )


def _fake_load_from_db(posters: list[dict], image_urls: dict | None = None):
    async def _fn():
        return posters, (image_urls or {})

    return _fn


async def _raise_os_error() -> None:
    raise OSError("Connection refused")


def _poster(poster_id, title: str) -> dict:
    return {
        "id": poster_id,
        "title": title,
        "published_at": None,
        "condition_grade": None,
        "year": None,
        "poster_type": None,
        "restoration_status": None,
        "tmdb_id": None,
        "width_in": None,
        "height_in": None,
    }


# --------------------------------------------------------------------------
# 1 — production/prod/uat ถูกปฏิเสธที่ argparse ก่อนอ่านไฟล์ใด ๆ เลย (AC-7 ค)
# --------------------------------------------------------------------------


@pytest.mark.parametrize("bad_target", ["production", "prod", "uat"])
def test_target_outside_dev_sit_is_rejected_before_reading_any_env_file(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, bad_target: str
) -> None:
    load_env_calls: list[str] = []
    parse_env_calls: list[object] = []
    monkeypatch.setattr(mod, "_load_env", lambda t: load_env_calls.append(t))
    monkeypatch.setattr(
        suggest_mod, "_parse_env_file", lambda p: (parse_env_calls.append(p), {})[1]
    )
    monkeypatch.setattr(sys, "argv", _argv(tmp_path, "--target", bad_target))

    with pytest.raises(SystemExit) as exc:
        mod.main()

    assert exc.value.code == 2
    assert load_env_calls == []
    assert parse_env_calls == []


# --------------------------------------------------------------------------
# 2 — choices เป็น literal ("dev", "sit") จริง ๆ ไม่ใช่ตัวแปรที่วันหลังอาจโตขึ้นมามี
# "production" ปนโดยไม่มีใครรู้ตัว — และเป็น subset แท้ของ TARGETS ตัวจริง
# --------------------------------------------------------------------------


def _target_add_argument_call(tree: ast.AST) -> ast.Call:
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "add_argument"
            and node.args
            and isinstance(node.args[0], ast.Constant)
            and node.args[0].value == "--target"
        ):
            return node
    raise AssertionError('add_argument("--target", ...) ไม่พบใน main()')


def test_target_choices_is_a_dev_sit_literal_subset_of_TARGETS() -> None:
    tree = ast.parse(inspect.getsource(mod))
    call = _target_add_argument_call(tree)
    choices_kw = next(kw for kw in call.keywords if kw.arg == "choices")
    assert isinstance(
        choices_kw.value, ast.Tuple
    ), "choices ต้องเป็น literal tuple ไม่ใช่ชื่อตัวแปร/นิพจน์ — กันไม่ให้วันหลังมีคนสลับ ไปใช้ TARGETS ทั้งก้อนแล้วเปิด production เงียบ ๆ"
    values = tuple(elt.value for elt in choices_kw.value.elts)
    assert values == ("dev", "sit")
    assert "production" not in values
    assert set(values) <= set(PRODUCTION_TARGETS)


# --------------------------------------------------------------------------
# 3 — ไม่ใส่ --target เลย ต้องยังเป็น "dev" เหมือนพฤติกรรมเดิมของคนที่รันอยู่ทุกวันนี้
# --------------------------------------------------------------------------


def test_default_target_is_dev_and_wires_the_real_url_through(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    calls: dict[str, object] = {}

    def fake_load_env(target: str) -> None:
        calls["load_env"] = target
        monkeypatch.setenv("DATABASE_URL", DEV_URL)

    def fake_assert_target(url: str, target: str) -> str:
        calls["assert_target"] = (url, target)
        return "localhost/poster_nung_db"

    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setattr(mod, "_load_env", fake_load_env)
    monkeypatch.setattr(mod, "assert_target", fake_assert_target)
    monkeypatch.setattr(mod, "load_from_db", _fake_load_from_db([]))
    monkeypatch.setattr(sys, "argv", _argv(tmp_path))

    rc = mod.main()

    assert rc == 0
    assert calls["load_env"] == "dev"
    assert calls["assert_target"] == (DEV_URL, "dev")


# --------------------------------------------------------------------------
# 4/5/6 — precheck ปฏิเสธก่อนแตะ DB เลย (load_from_db ต้องไม่ถูกเรียก)
# --------------------------------------------------------------------------


def test_sit_without_env_sit_file_is_refused_before_touching_db(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _fake_env(monkeypatch, {})  # ไม่มี .env.sit เลย
    monkeypatch.delenv("ENVIRONMENT", raising=False)
    monkeypatch.setenv("DATABASE_URL", CLEAN_SIT_URL)
    monkeypatch.setattr(mod, "load_from_db", _unreachable_load_from_db)
    monkeypatch.setattr(sys, "argv", _argv(tmp_path, "--target", "sit"))

    rc = mod.main()

    assert rc == 1


def test_sit_url_that_differs_from_env_sit_is_refused_before_touching_db(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _fake_env(monkeypatch, {".env.sit": {"DATABASE_URL": CLEAN_SIT_URL}})
    monkeypatch.delenv("ENVIRONMENT", raising=False)
    monkeypatch.setenv("DATABASE_URL", OTHER_SIT_URL)
    monkeypatch.setattr(mod, "load_from_db", _unreachable_load_from_db)
    monkeypatch.setattr(sys, "argv", _argv(tmp_path, "--target", "sit"))

    rc = mod.main()

    assert rc == 1


def test_environment_production_with_target_sit_is_refused(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _fake_env(monkeypatch, {".env.sit": {"DATABASE_URL": CLEAN_SIT_URL}})
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("DATABASE_URL", CLEAN_SIT_URL)
    monkeypatch.setattr(mod, "load_from_db", _unreachable_load_from_db)
    monkeypatch.setattr(sys, "argv", _argv(tmp_path, "--target", "sit"))

    rc = mod.main()

    assert rc == 1


# --------------------------------------------------------------------------
# 7 — รหัสผ่านที่มี `/` ต้องไม่หลุดออกมาไม่ว่าเส้นไหน (สำเร็จ · precheck · OSError)
# --------------------------------------------------------------------------


def test_secret_password_never_leaks_on_success(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _fake_env(monkeypatch, {".env.sit": {"DATABASE_URL": SECRET_SIT_URL}})
    monkeypatch.delenv("ENVIRONMENT", raising=False)
    monkeypatch.setenv("DATABASE_URL", SECRET_SIT_URL)
    monkeypatch.setattr(mod, "load_from_db", _fake_load_from_db([]))
    monkeypatch.setattr(sys, "argv", _argv(tmp_path, "--target", "sit"))

    rc = mod.main()
    captured = capsys.readouterr()

    assert rc == 0
    combined = captured.out + captured.err
    for forbidden in FORBIDDEN_SUBSTRINGS:
        assert forbidden not in combined, f"{forbidden!r} หลุดออกมาใน output"


def test_secret_password_never_leaks_on_precheck_failure(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    # .env.sit ชี้คนละฐานกับ DATABASE_URL ที่มีรหัสผ่านหลุด — ต้องถูกปฏิเสธ (precheck)
    _fake_env(monkeypatch, {".env.sit": {"DATABASE_URL": CLEAN_SIT_URL}})
    monkeypatch.delenv("ENVIRONMENT", raising=False)
    monkeypatch.setenv("DATABASE_URL", SECRET_SIT_URL)
    monkeypatch.setattr(mod, "load_from_db", _unreachable_load_from_db)
    monkeypatch.setattr(sys, "argv", _argv(tmp_path, "--target", "sit"))

    rc = mod.main()
    captured = capsys.readouterr()

    assert rc == 1
    combined = captured.out + captured.err
    for forbidden in FORBIDDEN_SUBSTRINGS:
        assert forbidden not in combined, f"{forbidden!r} หลุดออกมาใน output"


def test_secret_password_never_leaks_on_connection_failure(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _fake_env(monkeypatch, {".env.sit": {"DATABASE_URL": SECRET_SIT_URL}})
    monkeypatch.delenv("ENVIRONMENT", raising=False)
    monkeypatch.setenv("DATABASE_URL", SECRET_SIT_URL)
    monkeypatch.setattr(mod, "load_from_db", _raise_os_error)
    monkeypatch.setattr(sys, "argv", _argv(tmp_path, "--target", "sit"))

    rc = mod.main()
    captured = capsys.readouterr()

    assert rc != 0
    combined = captured.out + captured.err
    for forbidden in FORBIDDEN_SUBSTRINGS:
        assert forbidden not in combined, f"{forbidden!r} หลุดออกมาใน output"
    # hint ของ OSError ต้องยังบอกคำสั่งที่ถูกต้อง แม้จะกรองความลับออกไปแล้ว
    assert "docker exec posternung-sit-app" in combined


# --------------------------------------------------------------------------
# 8 — ด่านกันเขียนทับ (AC-3) ต้องมาก่อนแตะ env ใด ๆ เลย
# --------------------------------------------------------------------------


def test_overwrite_guard_leaves_the_existing_file_byte_for_byte_untouched(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    out = tmp_path / "existing.csv"
    original = b"poster_uuid,title\n11111111-1111-1111-1111-111111111111,Some Title\n"
    out.write_bytes(original)
    mtime_before = out.stat().st_mtime_ns

    load_env_calls: list[str] = []
    monkeypatch.setattr(mod, "_load_env", lambda t: load_env_calls.append(t))
    monkeypatch.setattr(mod, "load_from_db", _unreachable_load_from_db)
    monkeypatch.setattr(sys, "argv", _argv(tmp_path, out=out))

    rc = mod.main()

    assert rc != 0
    assert out.read_bytes() == original
    assert out.stat().st_mtime_ns == mtime_before
    assert load_env_calls == []


# --------------------------------------------------------------------------
# 9 — --out ในโฟลเดอร์ที่เขียนไม่ได้ (เช่น mount :ro ของ SIT) ต้องถูกปฏิเสธก่อนแตะ DB
# --------------------------------------------------------------------------


def test_unwritable_out_directory_is_refused_before_touching_db(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    readonly_dir = tmp_path / "ro"
    readonly_dir.mkdir()
    readonly_dir.chmod(0o500)  # r-x — เขียนไม่ได้
    out = readonly_dir / "manual-entry-v3.csv"

    monkeypatch.setattr(mod, "load_from_db", _unreachable_load_from_db)
    monkeypatch.setattr(sys, "argv", _argv(tmp_path, out=out))

    try:
        rc = mod.main()
    finally:
        readonly_dir.chmod(0o700)  # ให้ tmp_path cleanup ลบโฟลเดอร์ได้ตามปกติ

    assert rc != 0
    assert not out.exists()


# --------------------------------------------------------------------------
# 10 — AC-4: รายงานท้ายการรันบอก target จริงและจำนวนแถว
# --------------------------------------------------------------------------


def test_report_names_the_real_target_and_the_row_count(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    import uuid

    posters = [
        _poster(uuid.uuid4(), "Poster A"),
        _poster(uuid.uuid4(), "Poster B"),
    ]
    _fake_env(monkeypatch, {".env.sit": {"DATABASE_URL": CLEAN_SIT_URL}})
    monkeypatch.delenv("ENVIRONMENT", raising=False)
    monkeypatch.setenv("DATABASE_URL", CLEAN_SIT_URL)
    monkeypatch.setattr(mod, "load_from_db", _fake_load_from_db(posters))
    out = tmp_path / "manual-entry-v3.csv"
    monkeypatch.setattr(sys, "argv", _argv(tmp_path, "--target", "sit", out=out))

    rc = mod.main()
    printed = capsys.readouterr().out

    assert rc == 0
    assert "[--target sit]" in printed
    assert "2 แถว" in printed
    rows = out.read_text(encoding="utf-8").splitlines()
    assert len(rows) == 1 + 2  # header + 2 แถว


# --------------------------------------------------------------------------
# 11 — AC-2: อ่านอย่างเดียวพิสูจน์ได้จากโครงสร้าง ไม่ใช่แค่ตั้งใจ
# --------------------------------------------------------------------------
#
# 🔴 ‹ย้าย 2026-09-26 · code-critic รอบ 1 INF-49 item L-2› เทส AST ของ "ไม่มี writer
# primitive" ย้ายไปเป็น `test_every_sheet_target_lane_never_calls_a_write_primitive`
# parametrize บน `SHEET_TARGET_LANES` ใน `tests/unit/test_seed_lane_shared_rules.py`
# แทน — เดิมล็อกแค่ไฟล์นี้ไฟล์เดียว เส้นถัดไปที่เข้าหมวดเดียวกัน (ตัวสร้างใบงานตัวอื่น
# ในอนาคต) จะไม่มีอะไรบังคับให้อ่านอย่างเดียวเหมือนกันโดยอัตโนมัติ — ดูที่นั่นแทน


# --------------------------------------------------------------------------
# 12 — M-1 (code-critic รอบ 1): url ที่แยกส่วนไม่ได้ต้องไม่พิมพ์ host/db_name ดิบ
# --------------------------------------------------------------------------
#
# `apply_suggestions.py:181-201` (ไม่แตะ — `BL-167`) ฝัง `host`/`db_name` ดิบไว้ใน
# บางสาขาของ `assert_target_database()` โดยไม่ผ่านตัวกรอง `@:/` ของ `_url_label()`
# เลย — ยืนยันจริงสองแบบ (ดู docstring ของ `make_manual_sheet.py` ตรง except block):
# (dev) username หลุดทาง `host` · (sit) เศษรหัสผ่านหลุดทาง `db_name` เพราะบังเอิญมี
# ตัวอักษร "uat" ต่อกันแล้วโดนด่าน `PRODUCTION_DB_HINTS` จับ

DEV_LEAK_URL = "postgresql+asyncpg://admin:s3cr3t/xyz@localhost/poster_db"
SIT_LEAK_URL = "postgresql+asyncpg://admin:ab/quatro@db:5432/poster_nung_db_sit"


def test_dev_precheck_failure_never_echoes_the_username_from_a_malformed_url(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """dev + รหัสผ่านที่มี `/` ไม่ encode → `urlsplit` เอา username ไปเป็น `host`
    ⇒ `apply_suggestions.py` raise `"--target dev แต่ DATABASE_URL ชี้ host 'admin' ..."`
    ตรง ๆ ไม่ผ่าน `_url_label()` เลย — พิสูจน์ยืนยันจริงด้วย python interactive แล้วก่อน
    เขียนเทสนี้ (ดู commit message)
    """
    _fake_env(monkeypatch, {})
    monkeypatch.delenv("ENVIRONMENT", raising=False)
    monkeypatch.setenv("DATABASE_URL", DEV_LEAK_URL)
    monkeypatch.setattr(mod, "load_from_db", _unreachable_load_from_db)
    monkeypatch.setattr(sys, "argv", _argv(tmp_path))  # default target = dev

    rc = mod.main()
    captured = capsys.readouterr()
    combined = captured.out + captured.err

    assert rc == 1
    for forbidden in ("admin", "s3cr3t", "xyz"):
        assert forbidden not in combined, f"{forbidden!r} หลุดออกมาใน output"


def test_sit_precheck_failure_never_echoes_a_password_fragment_from_a_malformed_url(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """sit + รหัสผ่านที่มี `/` ไม่ encode → เศษรหัสผ่านไหลไปอยู่ใน `db_name` แล้ว
    บังเอิญมีตัวอักษร "uat" ต่อกัน ⇒ ด่าน `PRODUCTION_DB_HINTS` raise
    `"ชื่อ database 'quatro@db:5432/...' มีคำว่า 'uat' ..."` พิมพ์ `db_name` ดิบทั้งก้อน

    🔴 ใช้ `"quatro"` เป็นตัวตรวจ ไม่ใช่ `"ab"` — `"ab"` เป็นสายอักขระย่อยของคำว่า
    `"database"` ที่โค้ดพิมพ์เองตามปกติ (`ต่อ database ไม่ได้`) ⇒ จะเป็น false positive
    """
    _fake_env(monkeypatch, {})
    monkeypatch.delenv("ENVIRONMENT", raising=False)
    monkeypatch.setenv("DATABASE_URL", SIT_LEAK_URL)
    monkeypatch.setattr(mod, "load_from_db", _unreachable_load_from_db)
    monkeypatch.setattr(sys, "argv", _argv(tmp_path, "--target", "sit"))

    rc = mod.main()
    captured = capsys.readouterr()
    combined = captured.out + captured.err

    assert rc == 1
    assert "quatro" not in combined, "เศษรหัสผ่านหลุดออกมาใน output"


def test_unparseable_url_label_marker_matches_the_real_function() -> None:
    """drift guard — ถ้า `_url_label()` (`apply_suggestions.py`) เปลี่ยนคำที่คืนตอน
    แยกส่วนไม่ได้ แล้วไม่มีใครมาแก้ `mod._UNPARSEABLE_URL_LABEL` ตาม ด่าน M-1 ทั้งก้อน
    จะเงียบเฉยแล้วกลับไปพิมพ์ `{exc}` ดิบเหมือนเดิมโดยไม่มีใครรู้ตัว
    """
    assert suggest_mod._url_label(SECRET_SIT_URL) == mod._UNPARSEABLE_URL_LABEL


# --------------------------------------------------------------------------
# 13 — Low item 2 (code-critic รอบ 1): error จาก DB driver ตอน connect ไม่ผ่าน
# OSError (auth/catalog ผิด) ต้องไม่พิมพ์ {exc} ดิบเหมือนกัน
# --------------------------------------------------------------------------
#
# ยืนยันจริงบนสแตกนี้ (asyncpg + SQLAlchemy async engine ตัวเดียวกับ
# `app.core.database.async_session_maker`) ด้วย python interactive:
# - รหัสผ่านผิด → `asyncpg.exceptions.InvalidPasswordError` **ดิบ ไม่ถูก SQLAlchemy
#   wrap** (connect() ล้มเหลว)
# - ชื่อ database ไม่มีจริง → `asyncpg.exceptions.InvalidCatalogNameError` ดิบเหมือนกัน
# - SQL ผิด (error ระดับ statement หลัง connect สำเร็จ) → ถูก wrap เป็น
#   `sqlalchemy.exc.ProgrammingError` (subclass ของ `SQLAlchemyError`)
# ⇒ ต้องคุมทั้งสองตระกูล


def test_postgres_driver_error_on_connect_never_echoes_credentials(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from asyncpg.exceptions import PostgresError

    async def _raise_postgres_error() -> None:
        raise PostgresError('password authentication failed for user "leaked_user_abc"')

    _fake_env(monkeypatch, {".env.sit": {"DATABASE_URL": CLEAN_SIT_URL}})
    monkeypatch.delenv("ENVIRONMENT", raising=False)
    monkeypatch.setenv("DATABASE_URL", CLEAN_SIT_URL)
    monkeypatch.setattr(mod, "load_from_db", _raise_postgres_error)
    monkeypatch.setattr(sys, "argv", _argv(tmp_path, "--target", "sit"))

    rc = mod.main()
    captured = capsys.readouterr()
    combined = captured.out + captured.err

    assert rc != 0
    assert "leaked_user_abc" not in combined
    assert "PostgresError" in combined  # ยังบอกชนิด error พอวินิจฉัยได้
    assert "docker exec posternung-sit-app" in combined


def test_sqlalchemy_wrapped_error_never_echoes_credentials(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from sqlalchemy.exc import SQLAlchemyError

    async def _raise_sqlalchemy_error() -> None:
        raise SQLAlchemyError(
            "(asyncpg.exceptions.InvalidPasswordError) password authentication "
            'failed for user "leaked_user_abc"'
        )

    _fake_env(monkeypatch, {".env.sit": {"DATABASE_URL": CLEAN_SIT_URL}})
    monkeypatch.delenv("ENVIRONMENT", raising=False)
    monkeypatch.setenv("DATABASE_URL", CLEAN_SIT_URL)
    monkeypatch.setattr(mod, "load_from_db", _raise_sqlalchemy_error)
    monkeypatch.setattr(sys, "argv", _argv(tmp_path, "--target", "sit"))

    rc = mod.main()
    captured = capsys.readouterr()
    combined = captured.out + captured.err

    assert rc != 0
    assert "leaked_user_abc" not in combined
    assert "SQLAlchemyError" in combined
    assert "docker exec posternung-sit-app" in combined


# --------------------------------------------------------------------------
# 14 — L-1 (code-critic รอบ 1 · mutant M6 ที่รอด): `_load_env()` ต้องได้รับ target
# ของรอบนั้นจริง ๆ ไม่ใช่ "dev" hardcode
# --------------------------------------------------------------------------
#
# 🔴 เทสเดิม (#3 ข้างบน) ที่ `monkeypatch.setenv("DATABASE_URL", ...)` ไว้ก่อนเรียก
# `main()` จับมิวเทชันนี้ไม่ได้ เพราะ `_load_env()` ใช้ `os.environ.setdefault()` —
# ค่าที่ตั้งไว้แล้วชนะเสมอไม่ว่าจะ `_load_env` จะถูกเรียกด้วย target อะไร เทสนี้ยืนกับ
# **อาร์กิวเมนต์ที่ main() ส่งเข้าไปจริง** แทนผลข้างเคียงของ env


def test_target_sit_is_the_value_load_env_actually_receives(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    calls: list[str] = []

    def spy_load_env(target: str) -> None:
        calls.append(target)

    def fake_assert_target(url: str, target: str) -> str:
        return "db/poster_nung_db_sit"

    monkeypatch.setenv("DATABASE_URL", CLEAN_SIT_URL)
    monkeypatch.setattr(mod, "_load_env", spy_load_env)
    monkeypatch.setattr(mod, "assert_target", fake_assert_target)
    monkeypatch.setattr(mod, "load_from_db", _fake_load_from_db([]))
    monkeypatch.setattr(sys, "argv", _argv(tmp_path, "--target", "sit"))

    rc = mod.main()

    assert rc == 0
    assert calls == ["sit"]
