"""ล็อก ADR-0025 D1/D5 (INF-24 AC-1): `posters.status` มี **writer เดียว** สำหรับแถว
ที่มีอยู่แล้ว (`app/services/poster_service.py` — `mark_sold()`) และ **writer เดียว**
สำหรับตอนสร้างแถวใหม่ (`scripts/seed/seed_posters.py`) — สองเซตนี้แยกกันโดยตั้งใจ
(D5): UPDATE ≠ INSERT, closed-world ต้อง assert ความ**เท่ากัน**ของเซต ไม่ใช่ subset

ขอบเขตการสแกน = `app/` + `scripts/` **ไม่รวม `tests/`** (fixture ตั้ง `status=` เป็น
เรื่องปกติที่ไม่ต้องผ่าน service — D5)

🔴 **ตัวสแกนทั้งสองเป็นฟังก์ชัน pure ที่รับ `paths` เข้ามา** (ไม่ใช่เดินหา `REPO_ROOT`
เอง) เพื่อให้มีเทสคู่หนึ่งที่ป้อน source สังเคราะห์ที่ *ละเมิด* เข้าไปแล้วพิสูจน์ว่า
มันจับเป็น — แม่แบบ (`test_release_date_invariant.py`) ไม่มีเทสชนิดนี้และเขียวได้
ตลอดกาลถ้าตัวสแกนพัง ต้องไม่ลอกจุดอ่อนนั้นมา (ADR-0025 D5)

ตัววัด (pure AST, ไม่มี data-flow analysis ข้ามฟังก์ชัน):

* **UPDATE-style** — สามรูปที่ repo นี้ใช้จริงหรือมี precedent อยู่แล้ว
  1. `ast.Assign` ที่ target เป็น `<expr>.status = <ไม่ใช่ None>` ยกเว้น `args.status`
     (argparse Namespace ของ `seed_posters.py`, ไม่ใช่ ORM object)
  2. `setattr(<obj>, "status", <ค่าใด ๆ ที่ไม่ใช่ literal None>)` — รูปที่
     `correction_entry.py` / `manual_entry.py` / `reference_entry.py` ใช้อยู่ทุกวัน
     กับฟิลด์อื่น (`WRITABLE_FIELDS` ไม่รวม `"status"` วันนี้ แต่ scanner ต้องจับได้
     ถ้าใครเผลอเพิ่มเข้าไปในอนาคต — ไม่ gate ด้วย "ไฟล์อ้างถึง Poster" เพราะ object
     ที่ถูก setattr เป็นตัวแปร ไม่รู้ชนิดสถิตได้ ยอมรับ false positive ที่กว้างกว่าจริง
     ไว้ก่อน)
  3. `<update-call>.values(status=<ไม่ใช่ None>)` — รูปที่ `test_poster_sold_at_constraint.py`
     ใช้จำลอง seeder (`update(Poster.__table__).where(...).values(status=...)`) และ
     เป็นรูปที่ `SCR-06` จะใช้เขียน `status='reserved'`/`'expired'` gate ด้วย "ไฟล์
     อ้างถึงชื่อ Poster" เพื่อไม่ชนกับ `.values(status=...)` ของตารางอื่นที่มีคอลัมน์
     ชื่อ `status` เหมือนกัน (เช่น `reservations` — ยังไม่มีโค้ดจริงวันนี้)
* **INSERT-style** — `Poster(status=<ไม่ใช่ None>)` (constructor call) หรือ
  `ast.Dict` literal ที่มีคีย์ `"status"` ค่าไม่ใช่ `None` **ในไฟล์ที่อ้างถึงชื่อ
  `Poster` ที่ไหนสักแห่ง** (กันไฟล์ที่บังเอิญมี dict คีย์ "status" ไม่เกี่ยวกับตาราง
  `posters` เลย เช่น health-check dict ของ `app/main.py` หรือ upload-status dict
  ของ `scripts/seed/migrate_to_r2.py` — ทั้งสองไม่ import/อ้างถึง `Poster` เลย)

ที่มา: `scripts/seed/seed_posters.py` เขียน `"status": status` ใน `dict` ที่ถูก
ประกอบเป็น `poster_rows` แล้วส่งเข้า `insert(Poster.__table__).values(poster_rows)`
คนละฟังก์ชันกับจุดที่สร้าง dict — pure AST ไล่ตามตัวแปรข้ามฟังก์ชันไม่ได้ จึงใช้
เกณฑ์ "ไฟล์อ้างถึง Poster + มี dict คีย์ status" แทนการไล่ data-flow เต็มรูป
(ยอมรับว่าเป็นเกณฑ์ที่กว้างกว่าการไล่ data-flow จริง — ดู test ท้ายไฟล์ที่พิสูจน์ขอบเขตนี้)

## 🔴 รูปที่สแกนเนอร์นี้ *ยังจับไม่ได้* (พบจาก `code-critic` รอบ 1 ของ INF-24 — H4)

บันทึกไว้ตรง ๆ แทนการอ้างว่าครอบครบ (แม่แบบ `reference_entry.py` §สิ่งที่ไม่ทำ):

1. **raw SQL ผ่าน `text("UPDATE posters SET status='sold'")`** — สแกนไม่แตะ
   `ast.Constant` ที่เป็นสตริง SQL ดิบเลย เพราะ parse SQL ไม่ใช่หน้าที่ของ AST scanner
   ตัวนี้ (ไม่มี precedent จริงในโค้ดวันนี้ — ทุกเส้นทางที่มีอยู่ใช้ SQLAlchemy Core/ORM)
2. **`ast.Dict` literal คีย์ `"status"` ในไฟล์ที่ไม่อ้างถึงชื่อ `Poster` เลยแม้แต่ครั้งเดียว**
   — ถ้ามีคนแยกฟังก์ชันสร้าง dict ไปไว้อีกไฟล์ที่ไม่ import/reference `Poster`
   (เช่น module กลางที่ใช้ type hint แบบ string หรือไม่ import เลย) แล้วอีกไฟล์
   หนึ่งค่อย import ฟังก์ชันนั้นมาป้อน `insert(Poster.__table__).values(...)` เกณฑ์
   "ไฟล์อ้างถึง Poster" จะไม่เห็น — ยอมรับความเสี่ยงนี้เพราะไม่มี precedent จริงวันนี้
   (`seed_posters.py` สร้าง dict และใช้ `Poster.__table__` อยู่ไฟล์เดียวกันเสมอ)
"""

from __future__ import annotations

import ast
from collections.abc import Iterable
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
_SCAN_DIRS = ("app", "scripts")  # ไม่รวม tests/ (D5)
# ไดเรกทอรีที่ไม่ใช่ source ของ repo นี้เลย — เจอจริง: scripts/seed/.venv/ (gitignored,
# local เท่านั้น) มี urllib3/rich/pip._vendor ที่เขียน `<obj>.status = ...` เพราะเป็น
# HTTP response object ทั่วไป ไม่เกี่ยวกับ Poster เลย ต้องกันไว้ไม่งั้นเทสนี้ผลลัพธ์
# ขึ้นกับว่าเครื่องที่รันเคย `pip install` ไว้ที่ไหนบ้าง
_EXCLUDED_DIR_NAMES = {".venv", "venv", "__pycache__", ".git", "node_modules"}


def _iter_python_files(scan_dirs: Iterable[str] = _SCAN_DIRS) -> list[Path]:
    files: list[Path] = []
    for scan_dir in scan_dirs:
        root = REPO_ROOT / scan_dir
        if not root.is_dir():
            continue
        for path in sorted(root.rglob("*.py")):
            if _EXCLUDED_DIR_NAMES.isdisjoint(path.relative_to(root).parts):
                files.append(path)
    return files


def _parse(path: Path) -> ast.AST | None:
    try:
        source = path.read_text(encoding="utf-8")
        return ast.parse(source, filename=str(path))
    except (SyntaxError, OSError):
        return None


def _is_none_constant(node: ast.expr) -> bool:
    return isinstance(node, ast.Constant) and node.value is None


def _is_poster_call(node: ast.Call) -> bool:
    func = node.func
    if isinstance(func, ast.Name):
        return func.id == "Poster"
    if isinstance(func, ast.Attribute):
        return func.attr == "Poster"
    return False


def _references_poster_name(tree: ast.AST) -> bool:
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and node.id == "Poster":
            return True
        if isinstance(node, ast.Attribute) and node.attr == "Poster":
            return True
    return False


def _is_setattr_status_call(node: ast.Call) -> bool:
    """`setattr(<obj>, "status", <ค่า>)` — รูปที่เส้นที่ 3/4/5 ใช้จริงกับฟิลด์อื่น

    ไม่ gate ด้วย "ไฟล์อ้างถึง Poster" โดยตั้งใจ — `<obj>` เป็นตัวแปร รู้ชนิดสถิตไม่ได้
    จาก AST เฉย ๆ ยอมรับ false positive ที่กว้างกว่าจริงไว้ก่อน (ดู docstring หัวไฟล์)
    """
    if not (isinstance(node.func, ast.Name) and node.func.id == "setattr"):
        return False
    if len(node.args) < 3:
        return False
    field = node.args[1]
    if not (isinstance(field, ast.Constant) and field.value == "status"):
        return False
    return not _is_none_constant(node.args[2])


def _is_values_status_call(node: ast.Call) -> bool:
    """`<expr>.values(status=<ไม่ใช่ None>)` — รูปของ SQLAlchemy Core UPDATE

    เช็คแค่ชื่อ method `values` + keyword `status` (ไม่ไล่ว่า chain ต้นทางเป็น
    `update(...)` จริงไหม เพราะ `insert(...).values(...)` ก็เรียก method ชื่อ
    เดียวกัน — วันนี้ไม่มี precedent ที่ใช้ `insert(...).values(status=...)` แบบ
    keyword เลย (`seed_posters.py` ส่ง `poster_rows` เป็น positional arg) จึงไม่ชนกัน
    จริงในโค้ดวันนี้ ถ้าวันหน้ามีจะ over-flag เป็นฝั่ง UPDATE (ยังจับได้ แค่จัดกลุ่มพลาด)
    """
    if not (isinstance(node.func, ast.Attribute) and node.func.attr == "values"):
        return False
    for kw in node.keywords:
        if kw.arg == "status" and not _is_none_constant(kw.value):
            return True
    return False


def find_status_update_writers(paths: Iterable[Path]) -> list[str]:
    """สแกนไฟล์ที่ระบุ หา UPDATE-style write ของ `status` สามรูป (ดู docstring หัวไฟล์)

    คืน list ของ `"path:lineno"` — pure function รับ `paths` เข้ามาโดยตรง ไม่เดินหา
    REPO_ROOT เอง เพื่อให้เทส "ป้อน source สังเคราะห์" ทำได้โดยไม่ต้องมีไฟล์จริงในต้นไม้
    """
    writers: list[str] = []
    for path in paths:
        tree = _parse(path)
        if tree is None:
            continue
        touches_poster = _references_poster_name(tree)
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign) and not _is_none_constant(node.value):
                for target in node.targets:
                    if not isinstance(target, ast.Attribute) or target.attr != "status":
                        continue
                    if isinstance(target.value, ast.Name) and target.value.id == "args":
                        continue  # argparse Namespace ไม่ใช่ ORM object — ดู docstring
                    writers.append(f"{path}:{node.lineno}")
            if not isinstance(node, ast.Call):
                continue
            if _is_setattr_status_call(node):
                writers.append(f"{path}:{node.lineno}")
            elif touches_poster and _is_values_status_call(node):
                writers.append(f"{path}:{node.lineno}")
    return writers


def _call_sets_non_none_status(node: ast.Call) -> bool:
    for kw in node.keywords:
        if kw.arg != "status":
            continue
        return not _is_none_constant(kw.value)
    return False


def find_status_insert_writers(paths: Iterable[Path]) -> list[str]:
    """สแกนไฟล์ที่ระบุ หา `Poster(status=...)` หรือ dict literal คีย์ `"status"`
    ในไฟล์ที่อ้างถึง `Poster` (INSERT-style) — คืน list ของ `"path:lineno"`
    """
    writers: list[str] = []
    for path in paths:
        tree = _parse(path)
        if tree is None:
            continue
        touches_poster = _references_poster_name(tree)
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and _is_poster_call(node):
                if _call_sets_non_none_status(node):
                    writers.append(f"{path}:{node.lineno}")
                continue
            if not touches_poster or not isinstance(node, ast.Dict):
                continue
            for key, value in zip(node.keys, node.values, strict=True):
                if not (isinstance(key, ast.Constant) and key.value == "status"):
                    continue
                if _is_none_constant(value):
                    continue
                writers.append(f"{path}:{node.lineno}")
    return writers


# --------------------------------------------------------------------------
# closed-world บนของจริงในต้นไม้ — สองเซต assert ความเท่ากัน ไม่ใช่ subset (D5)
# --------------------------------------------------------------------------

ALLOWED_UPDATE_WRITER_FILES = {"app/services/poster_service.py"}
ALLOWED_INSERT_WRITER_FILES = {"scripts/seed/seed_posters.py"}


def _writer_files(writers: list[str]) -> set[str]:
    return {
        str(Path(entry.rsplit(":", 1)[0]).relative_to(REPO_ROOT)) for entry in writers
    }


def test_status_update_closed_world_is_poster_service_only() -> None:
    """แดงเมื่อมีโค้ดอื่นนอก `mark_sold()` เขียน `<obj>.status = ...` บนแถวที่มีอยู่แล้ว
    (AC-1) — เท่ากับเซต ไม่ใช่ subset: ถ้า `poster_service.py` เลิกเขียน status เทสนี้
    ก็ต้องแดงเช่นกัน (พิสูจน์ว่าไม่ได้แค่ "ไม่มีตัวอื่นเพิ่ม")
    """
    writers = find_status_update_writers(_iter_python_files())
    assert (
        _writer_files(writers) == ALLOWED_UPDATE_WRITER_FILES
    ), f"เซตผู้เขียน (UPDATE) posters.status ไม่ตรงกับที่ ADR-0025 D5 กำหนด: {writers}"


def test_status_insert_closed_world_is_seed_posters_only() -> None:
    """แดงเมื่อมีโค้ดอื่นนอก `seed_posters.py` สร้างแถวใหม่พร้อมกำหนด `status` เอง
    (AC-1) — `split_entry.py` ต้องไม่อยู่ในเซตนี้เพราะปล่อย `server_default` (D5)
    """
    writers = find_status_insert_writers(_iter_python_files())
    assert (
        _writer_files(writers) == ALLOWED_INSERT_WRITER_FILES
    ), f"เซตผู้เขียน (INSERT) posters.status ไม่ตรงกับที่ ADR-0025 D5 กำหนด: {writers}"


# --------------------------------------------------------------------------
# พิสูจน์ว่าตัวสแกนจับเป็น — ป้อน source สังเคราะห์ที่ละเมิดเข้าไปตรง ๆ (D5 · 🔴)
# --------------------------------------------------------------------------


def test_update_scanner_catches_synthetic_violation(tmp_path: Path) -> None:
    """ถ้าตัวสแกนพัง (เช่น `ast.walk` ไม่ทำงาน หรือเงื่อนไข attr ผิด) เทส closed-world
    ข้างบนจะเขียวตลอดกาลโดยไม่ได้ตรวจอะไรเลย — เทสนี้พิสูจน์ว่าไม่ใช่กรณีนั้น
    """
    violating = tmp_path / "rogue_writer.py"
    violating.write_text(
        "def sneak_a_write(poster):\n"
        '    poster.status = "sold"  # ไม่ผ่าน mark_sold() เลย\n',
        encoding="utf-8",
    )

    assert find_status_update_writers([violating]) == [f"{violating}:2"]


def test_update_scanner_ignores_args_status(tmp_path: Path) -> None:
    """`args.status = ...` (argparse Namespace ของ CLI) ไม่ใช่การเขียน ORM — ต้องไม่ถูก
    นับ (สาเหตุที่ `find_status_update_writers` ต้องกันเคสนี้ไว้: `seed_posters.py`
    มี `args.status = args.status or "available"` จริงในไฟล์)
    """
    benign = tmp_path / "cli.py"
    benign.write_text('args.status = args.status or "available"\n', encoding="utf-8")

    assert find_status_update_writers([benign]) == []


def test_update_scanner_ignores_none_assignment(tmp_path: Path) -> None:
    """`x.status = None` ไม่ใช่การเขียนค่าเข้า status — ไม่นับเป็น writer"""
    benign = tmp_path / "cli.py"
    benign.write_text("poster.status = None\n", encoding="utf-8")

    assert find_status_update_writers([benign]) == []


def test_update_scanner_catches_setattr_status(tmp_path: Path) -> None:
    """H4 (code-critic รอบ 1) — รูปที่ `correction_entry.py`/`manual_entry.py`/
    `reference_entry.py` ใช้จริงกับฟิลด์อื่นทุกวัน (`setattr(poster, name, value)`)
    ต้องถูกจับถ้าชื่อฟิลด์เป็น literal `"status"`
    """
    violating = tmp_path / "rogue_setattr.py"
    violating.write_text(
        "def sneak_a_write(poster, value):\n"
        '    setattr(poster, "status", value)  # ไม่ผ่าน mark_sold() เลย\n',
        encoding="utf-8",
    )

    assert find_status_update_writers([violating]) == [f"{violating}:2"]


def test_update_scanner_ignores_setattr_of_other_fields(tmp_path: Path) -> None:
    """`setattr(poster, "condition_grade", value)` ไม่ใช่การเขียน status — ไม่นับ"""
    benign = tmp_path / "cli.py"
    benign.write_text('setattr(poster, "condition_grade", value)\n', encoding="utf-8")

    assert find_status_update_writers([benign]) == []


def test_update_scanner_ignores_setattr_with_dynamic_field_name(tmp_path: Path) -> None:
    """`setattr(poster, name, value)` ที่ `name` เป็นตัวแปร (ไม่ใช่ literal "status")
    — รูปจริงที่ `correction_entry.py`/`manual_entry.py` ใช้ (field มาจาก
    `WRITABLE_FIELDS` ซึ่งไม่มี `"status"`) ไม่มีทางรู้ตอน scan ว่าค่า runtime คือ
    อะไร จึงไม่นับ (ด่านตัวจริงของกรณีนี้คือ `WRITABLE_FIELDS` fail-closed ที่ตัวสคริปต์
    เอง ไม่ใช่ scanner ตัวนี้)
    """
    benign = tmp_path / "cli.py"
    benign.write_text("setattr(poster, name, value)\n", encoding="utf-8")

    assert find_status_update_writers([benign]) == []


def test_update_scanner_catches_core_update_values_status(tmp_path: Path) -> None:
    """H4 (code-critic รอบ 1) — รูปที่ `test_poster_sold_at_constraint.py` ใช้จำลอง
    seeder (`update(Poster.__table__).where(...).values(status=...)`) และรูปที่
    `SCR-06` จะใช้เขียน `status='reserved'`/`'expired'`
    """
    violating = tmp_path / "rogue_core_update.py"
    violating.write_text(
        "from app.models.poster import Poster\n"
        "from sqlalchemy import update\n"
        "\n"
        "def sneak_an_update(session, poster_id):\n"
        "    stmt = (\n"
        "        update(Poster.__table__)\n"
        "        .where(Poster.__table__.c.id == poster_id)\n"
        '        .values(status="sold")\n'
        "    )\n"
        "    return stmt\n",
        encoding="utf-8",
    )

    # ไม่ผูกกับเลขบรรทัดเป๊ะ — ast.Call.lineno ของ chain หลายบรรทัดชี้ที่จุดเริ่ม
    # ของนิพจน์ทั้งก้อน (บรรทัดของ `update(...)`) ไม่ใช่บรรทัดของ `.values(...)` เอง
    writers = find_status_update_writers([violating])
    assert len(writers) == 1, writers
    assert writers[0].startswith(f"{violating}:")


def test_update_scanner_ignores_core_update_values_status_without_poster_reference(
    tmp_path: Path,
) -> None:
    """`.values(status=...)` บนตารางอื่นที่ไม่เกี่ยวกับ `Poster` เลย (เช่น
    `reservations` ในอนาคต) ไม่ถูกนับ — gate ด้วย "ไฟล์อ้างถึงชื่อ Poster" (ดู
    docstring ของ `_is_values_status_call`)
    """
    benign = tmp_path / "rogue_core_update.py"
    benign.write_text(
        "from sqlalchemy import update\n"
        "\n"
        "def touch_something_else(session, row_id):\n"
        '    return update(SomeOtherTable).where(SomeOtherTable.c.id == row_id).values(status="x")\n',
        encoding="utf-8",
    )

    assert find_status_update_writers([benign]) == []


def test_insert_scanner_catches_synthetic_poster_call(tmp_path: Path) -> None:
    violating = tmp_path / "rogue_insert.py"
    violating.write_text(
        "from app.models.poster import Poster\n"
        "\n"
        "def sneak_an_insert():\n"
        '    return Poster(title="x", status="sold")\n',
        encoding="utf-8",
    )

    assert find_status_insert_writers([violating]) == [f"{violating}:4"]


def test_insert_scanner_catches_synthetic_dict_literal_that_touches_poster(
    tmp_path: Path,
) -> None:
    """เลียนแบบรูปจริงของ `seed_posters.py`: dict คีย์ "status" ในไฟล์ที่อ้างถึง
    `Poster` อยู่ (แม้จะคนละฟังก์ชันกับจุดที่ใช้ dict นั้นจริง ๆ)
    """
    violating = tmp_path / "rogue_dict.py"
    violating.write_text(
        "from app.models.poster import Poster\n"
        "\n"
        "def build_row(status):\n"
        '    return {"id": 1, "status": status}\n'
        "\n"
        "def use_it():\n"
        "    insert(Poster.__table__).values(build_row('sold'))\n",
        encoding="utf-8",
    )

    assert find_status_insert_writers([violating]) == [f"{violating}:4"]


def test_insert_scanner_ignores_dict_literal_in_file_that_never_touches_poster(
    tmp_path: Path,
) -> None:
    """`app/main.py` มี `{"status": "ok"}` (health check) แต่ไม่อ้างถึง `Poster` เลย
    — ต้องไม่ถูกนับ (กันเทสข้อบนไม่ให้ over-match จนล้ม false positive กว้างเกิน)
    """
    benign = tmp_path / "health.py"
    benign.write_text(
        'def healthcheck():\n    return {"status": "ok"}\n', encoding="utf-8"
    )

    assert find_status_insert_writers([benign]) == []


def test_insert_scanner_ignores_none_status_dict_value(tmp_path: Path) -> None:
    benign = tmp_path / "rogue_dict.py"
    benign.write_text(
        "from app.models.poster import Poster\n"
        "\n"
        "def build_row():\n"
        '    return {"id": 1, "status": None}\n',
        encoding="utf-8",
    )

    assert find_status_insert_writers([benign]) == []
