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

* **UPDATE-style** — `ast.Assign` ที่ target เป็น `<expr>.status = <ไม่ใช่ None>`
  ยกเว้น `args.status` (argparse Namespace ของ `seed_posters.py`, ไม่ใช่ ORM object)
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


def find_status_update_writers(paths: Iterable[Path]) -> list[str]:
    """สแกนไฟล์ที่ระบุ หา `<expr>.status = <ไม่ใช่ None>` (UPDATE-style)

    คืน list ของ `"path:lineno"` — pure function รับ `paths` เข้ามาโดยตรง ไม่เดินหา
    REPO_ROOT เอง เพื่อให้เทส "ป้อน source สังเคราะห์" ทำได้โดยไม่ต้องมีไฟล์จริงในต้นไม้
    """
    writers: list[str] = []
    for path in paths:
        tree = _parse(path)
        if tree is None:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Assign):
                continue
            if _is_none_constant(node.value):
                continue
            for target in node.targets:
                if not isinstance(target, ast.Attribute) or target.attr != "status":
                    continue
                if isinstance(target.value, ast.Name) and target.value.id == "args":
                    continue  # argparse Namespace ไม่ใช่ ORM object — ดู docstring
                writers.append(f"{path}:{node.lineno}")
    return writers


def _is_poster_call(node: ast.Call) -> bool:
    func = node.func
    if isinstance(func, ast.Name):
        return func.id == "Poster"
    if isinstance(func, ast.Attribute):
        return func.attr == "Poster"
    return False


def _call_sets_non_none_status(node: ast.Call) -> bool:
    for kw in node.keywords:
        if kw.arg != "status":
            continue
        return not _is_none_constant(kw.value)
    return False


def _references_poster_name(tree: ast.AST) -> bool:
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and node.id == "Poster":
            return True
        if isinstance(node, ast.Attribute) and node.attr == "Poster":
            return True
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
