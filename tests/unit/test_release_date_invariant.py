"""ล็อก ADR-0009 D13 ข้อ 2: "ห้ามมีใครกรอก `release_date` โดยไม่มี
`release_date_text` รองรับ" — ADR ตัดสินใจไว้ว่ากันด้วย "กฎ writer เดียว + test
เท่านั้น" ไม่ใช้ DB CHECK constraint (จะพิจารณาแยกที่ GATE 3) และไม่เพิ่ม runtime
validation ในรอบนี้ ดังนั้น test นี้คือ guard เดียวที่มีอยู่จริงตอนนี้

ที่มา: code-critic เจอว่า `tests/unit/test_poster_service.py` เคยมี fixture ที่
สร้าง `Poster(release_date=..., ...)` โดยไม่มี `release_date_text` คู่กัน แล้ว test
ที่มีอยู่เดิมไม่มีตัวไหนจับได้เลย (แก้ fixture นั้นแล้วแยกต่างหาก)

วิธีตรวจ: สแกน AST (ไม่ใช้ regex เพราะ call อาจข้ามหลายบรรทัด) หา `Poster(...)`
ทุกจุดใน `app/`, `scripts/`, `tests/` แล้วเช็คว่าถ้ามี keyword `release_date` ที่ไม่ใช่
`None` ต้องมี keyword `release_date_text` อยู่ใน call เดียวกันด้วยเสมอ
"""

from __future__ import annotations

import ast
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
_SCAN_DIRS = ("app", "scripts", "tests")
_THIS_FILE = Path(__file__).resolve()


def _iter_python_files() -> list[Path]:
    files: list[Path] = []
    for scan_dir in _SCAN_DIRS:
        root = REPO_ROOT / scan_dir
        if not root.is_dir():
            continue
        for path in root.rglob("*.py"):
            resolved = path.resolve()
            if resolved == _THIS_FILE:
                continue
            files.append(path)
    return files


def _is_poster_call(node: ast.Call) -> bool:
    func = node.func
    if isinstance(func, ast.Name):
        return func.id == "Poster"
    if isinstance(func, ast.Attribute):
        return func.attr == "Poster"
    return False


def _sets_non_none_release_date(node: ast.Call) -> bool:
    for kw in node.keywords:
        if kw.arg != "release_date":
            continue
        is_literal_none = isinstance(kw.value, ast.Constant) and kw.value.value is None
        return not is_literal_none
    return False


def _find_violations() -> list[str]:
    violations: list[str] = []
    for path in _iter_python_files():
        try:
            source = path.read_text(encoding="utf-8")
            tree = ast.parse(source, filename=str(path))
        except SyntaxError:
            continue

        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not _is_poster_call(node):
                continue
            if not _sets_non_none_release_date(node):
                continue
            kw_names = {kw.arg for kw in node.keywords if kw.arg is not None}
            if "release_date_text" not in kw_names:
                violations.append(f"{path.relative_to(REPO_ROOT)}:{node.lineno}")

    return violations


def test_no_poster_construction_sets_release_date_without_release_date_text() -> None:
    """สแกนทั้ง repo หา `Poster(release_date=...)` ที่ไม่มี `release_date_text=`
    คู่กัน — ต้องไม่พบเลยสักจุด (ADR-0009 D13 ข้อ 2). ถ้า test นี้แดง แปลว่ามีคน
    เขียนโค้ด/เทสที่ละเมิด single-writer invariant ของ `release_date` อีกครั้ง."""
    violations = _find_violations()
    assert violations == [], (
        "พบจุดที่กรอก Poster.release_date โดยไม่มี release_date_text คู่กัน "
        f"(ละเมิด ADR-0009 D13 ข้อ 2): {violations}"
    )
