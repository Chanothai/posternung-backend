"""closed-world ของคอลัมน์ `status` **แยกตามตาราง** — ADR-0025 D5 + ADR-0033 **D5**
(INF-24 AC-1 · INF-33 AC-2)

## ทำไมต้องแยกตามตาราง ‹เขียนใหม่ 2026-08-26 · INF-33 สไลซ์ A›

ไฟล์นี้เดิมมีเซตเดียวคือผู้เขียน `posters.status` และกฎข้อ 1 (`<expr>.status = <ค่า>`)
**ไม่ได้ gate ด้วยตาราง** (ตั้งใจ — ยอมรับ false positive ที่กว้างกว่าจริง)
⇒ **วินาทีที่มีบรรทัด `order.status = ...` ใน `app/` เทสเดิมจะแดงทันที**

🔴 **ทางที่ ADR-0033 D5 ห้ามชัดเจน: ห้ามแก้ด้วยการเติมไฟล์ใหม่เข้าเซตเดิม** —
ทางนั้นแจกใบอนุญาตเขียน `posters.status` ให้ไฟล์นั้นไปด้วยโดยไม่มีใครตั้งใจ และ
ทำให้ `ADR-0025 D5` อ่อนลงจริงทั้งที่ตัวอักษรยังอยู่ครบ

⇒ ตัวสแกน **จำแนกว่าแต่ละการเขียนเป็นของตารางไหน** แล้วมี **เซตแยกต่อตาราง**
ตารางที่ยังไม่มีผู้เขียน (`payments` · `disputes` · `payouts` · `notification_outbox`)
ต้องเป็น **เซตว่าง และเทส assert ว่าว่าง** ไม่ใช่ "ไม่ได้ตรวจ"

## เซตที่บังคับอยู่วันนี้

| ตาราง | UPDATE | INSERT |
|---|---|---|
| `posters` | `app/services/poster_service.py` (ADR-0025 D5 — **ไม่ขยับสักไฟล์**) | `scripts/seed/seed_posters.py` |
| `orders` | `app/services/order_service.py` (ADR-0033 D1) | `app/services/order_service.py` |
| `reservations` | `app/services/order_service.py` (lazy-expire + converted) | `app/repositories/reservation_repository.py` |
| `payments` · `disputes` · `payouts` · `notification_outbox` | — | — |

ขอบเขตการสแกน = `app/` + `scripts/` **ไม่รวม `tests/`** (fixture ตั้ง `status=` เป็น
เรื่องปกติที่ไม่ต้องผ่าน service — D5)

🔴 **ตัวสแกนเป็นฟังก์ชัน pure ที่รับ `paths` เข้ามา** เพื่อให้มีเทสที่ป้อน source
สังเคราะห์ที่ *ละเมิด* เข้าไปแล้วพิสูจน์ว่ามันจับเป็น — แม่แบบ
(`test_release_date_invariant.py`) ไม่มีเทสชนิดนี้และเขียวได้ตลอดกาลถ้าตัวสแกนพัง

## ตัววัด (pure AST · ไม่มี data-flow analysis ข้ามฟังก์ชัน)

**UPDATE-style** — สามรูปที่ repo นี้ใช้จริงหรือมี precedent อยู่แล้ว
1. `ast.Assign` ที่ target เป็น `<expr>.status = <ไม่ใช่ None>` ยกเว้นชื่อตัวแปรใน
   `_IGNORED_TARGET_NAMES` (`args` = argparse Namespace ของ `seed_posters.py`)
2. `setattr(<obj>, "status", <ค่าที่ไม่ใช่ literal None>)` — รูปที่ `correction_entry.py` /
   `manual_entry.py` / `reference_entry.py` ใช้อยู่ทุกวันกับฟิลด์อื่น
3. `<expr>.values(status=<ไม่ใช่ None>)` — รูปของ SQLAlchemy Core UPDATE

**INSERT-style**
4. `<Model>(status=<ไม่ใช่ None>)` (constructor ของโมเดลที่รู้จัก)
5. `ast.Dict` literal ที่มีคีย์ `"status"` ค่าไม่ใช่ `None` **ในไฟล์ที่อ้างถึงชื่อโมเดล**
   (รูปจริงของ `seed_posters.py` ซึ่งสร้าง dict คนละฟังก์ชันกับจุดที่ `insert()` ใช้มัน)

## 🔴 การจำแนกตาราง — และทำไม "จำแนกไม่ได้" ถึงต้องแดง

* รูปที่ 1/2 จำแนกจาก **ชื่อตัวแปร** (`poster.status` → `posters` · `order.status` →
  `orders`) เพราะ AST เปล่า ๆ ไม่รู้ชนิดสถิตของตัวแปร
* รูปที่ 3/4/5 จำแนกจาก **ชื่อโมเดลใน chain** ก่อน แล้วค่อยตกไปที่ "ไฟล์นี้อ้างถึง
  โมเดลเดียว" (ครอบ `from ... import Poster as P` ซึ่งชื่อโมเดลไม่โผล่ใน chain)
* **จำแนกไม่ได้ = เทสแดง** (`test_no_status_write_is_unclassified`) —
  fail-closed โดยตั้งใจ: การเขียน `status` ที่บอกไม่ได้ว่าเป็นของตารางไหน
  คือการเขียนที่ closed-world คุ้มไม่ได้ ทางแก้คือ **ตั้งชื่อตัวแปรให้ตรงกับตาราง**
  ไม่ใช่ผ่อนตัวสแกน
* ข้อยกเว้นเดียว: `ast.Dict` ในไฟล์ที่ **ไม่อ้างถึงโมเดลไหนเลย** ถูกข้าม —
  ไม่งั้น `{"status": "ok"}` ของ health check ใน `app/main.py` จะแดง

## 🔴 รูปที่สแกนเนอร์นี้ *ยังจับไม่ได้* (พบจาก `code-critic` รอบ 1 ของ INF-24 — H4)

1. **raw SQL ผ่าน `text("UPDATE posters SET status='sold'")`** — สแกนไม่แตะสตริง SQL ดิบ
   (ไม่มี precedent จริงในโค้ดวันนี้ — ทุกเส้นทางใช้ SQLAlchemy Core/ORM)
2. **dict literal คีย์ `"status"` ในไฟล์ที่ไม่อ้างถึงชื่อโมเดลเลย** — ถ้ามีคนแยกฟังก์ชัน
   สร้าง dict ไปไว้อีกไฟล์ที่ไม่ import โมเดล เกณฑ์ "ไฟล์อ้างถึงโมเดล" จะไม่เห็น
3. **ชื่อตัวแปรที่ตั้งให้เข้าใจผิด** — `poster = order` แล้ว `poster.status = ...`
   จะถูกนับเป็นของ `posters` · เป็นราคาของการจำแนกด้วยชื่อ ซึ่งถูกกว่าการไม่จำแนกเลย
"""

from __future__ import annotations

import ast
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
_SCAN_DIRS = ("app", "scripts")  # ไม่รวม tests/ (D5)
# ไดเรกทอรีที่ไม่ใช่ source ของ repo นี้เลย — เจอจริง: scripts/seed/.venv/ (gitignored,
# local เท่านั้น) มี urllib3/rich/pip._vendor ที่เขียน `<obj>.status = ...` เพราะเป็น
# HTTP response object ทั่วไป ต้องกันไว้ไม่งั้นผลลัพธ์ขึ้นกับว่าเครื่องที่รันเคย
# `pip install` ไว้ที่ไหนบ้าง
_EXCLUDED_DIR_NAMES = {".venv", "venv", "__pycache__", ".git", "node_modules"}

# ชื่อคลาสโมเดล → ชื่อตาราง · ใช้จำแนกรูปที่ 3/4/5
MODEL_TABLES: dict[str, str] = {
    "Poster": "posters",
    "Order": "orders",
    "Reservation": "reservations",
    "Payment": "payments",
    "Dispute": "disputes",
    "Payout": "payouts",
    "NotificationOutbox": "notification_outbox",
}

# token ในชื่อตัวแปร → ชื่อตาราง · ใช้จำแนกรูปที่ 1/2
VARIABLE_TABLES: dict[str, str] = {
    "poster": "posters",
    "listing": "posters",
    "order": "orders",
    "reservation": "reservations",
    "payment": "payments",
    "dispute": "disputes",
    "payout": "payouts",
    "notification": "notification_outbox",
}

# ตัวแปรที่ไม่ใช่แถวใน DB เลย — `seed_posters.py` มี
# `args.status = args.status or "available"` จริงในไฟล์
_IGNORED_TARGET_NAMES = {"args"}

UPDATE = "update"
INSERT = "insert"


@dataclass(frozen=True)
class StatusWrite:
    """การเขียน `status` หนึ่งจุด · `table = None` แปลว่า **จำแนกไม่ได้**"""

    location: str
    table: str | None
    kind: str


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


def _model_names_in(tree: ast.AST) -> set[str]:
    """ชื่อโมเดลที่ไฟล์นี้อ้างถึง — ครอบทั้งชื่อตรง (`Poster(...)`, `Poster.__table__`)
    และ import ที่ตั้งชื่อเล่น (`from ... import Poster as P`)

    ตัวหลังต้องเช็ค `ast.alias.name` แยก เพราะ `ast.alias` ไม่ใช่ `ast.Name`/
    `ast.Attribute` — ถ้าไม่เช็ค ไฟล์ที่ import แบบตั้งชื่อเล่นแล้วใช้แต่ชื่อเล่นต่อจากนั้น
    (`P(...)`) จะหลุดจากการจำแนกทั้งที่แตะโมเดลจริง (พบจาก code-critic รอบ 2 ของ INF-24)
    """
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and node.id in MODEL_TABLES:
            found.add(node.id)
        elif isinstance(node, ast.Attribute) and node.attr in MODEL_TABLES:
            found.add(node.attr)
        elif isinstance(node, ast.alias) and node.name in MODEL_TABLES:
            found.add(node.name)
    return found


def _table_from_file(model_names: set[str]) -> str | None:
    """ไฟล์ที่อ้างถึงโมเดลเดียวเท่านั้นถึงจะใช้เป็นตัวจำแนกได้ — สองตัวขึ้นไป = กำกวม"""
    tables = {MODEL_TABLES[name] for name in model_names}
    return next(iter(tables)) if len(tables) == 1 else None


def _table_from_variable(node: ast.expr) -> str | None:
    """จำแนกตารางจากชื่อตัวแปรที่ถูกเขียน (`order.status = ...` → `orders`)"""
    if not isinstance(node, ast.Name):
        return None
    tables = {
        VARIABLE_TABLES[token]
        for token in node.id.lower().split("_")
        if token in VARIABLE_TABLES
    }
    return next(iter(tables)) if len(tables) == 1 else None


def _table_from_call_chain(node: ast.Call, model_names: set[str]) -> str | None:
    """หา `Poster` ใน `update(Poster.__table__).where(...).values(status=...)` ก่อน
    แล้วค่อยตกไปที่ "ไฟล์นี้อ้างถึงโมเดลเดียว" (ครอบเคส `Poster as P`)
    """
    tables = {
        MODEL_TABLES[inner.id]
        for inner in ast.walk(node)
        if isinstance(inner, ast.Name) and inner.id in MODEL_TABLES
    } | {
        MODEL_TABLES[inner.attr]
        for inner in ast.walk(node)
        if isinstance(inner, ast.Attribute) and inner.attr in MODEL_TABLES
    }
    if len(tables) == 1:
        return next(iter(tables))
    return _table_from_file(model_names) if not tables else None


def _is_setattr_status_call(node: ast.Call) -> bool:
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
    `update(...)` จริงไหม เพราะ `insert(...).values(...)` ก็เรียก method ชื่อเดียวกัน
    — วันนี้ไม่มี precedent ที่ใช้ `insert(...).values(status=...)` แบบ keyword)
    """
    if not (isinstance(node.func, ast.Attribute) and node.func.attr == "values"):
        return False
    return any(
        kw.arg == "status" and not _is_none_constant(kw.value) for kw in node.keywords
    )


def _model_call_name(node: ast.Call) -> str | None:
    func = node.func
    if isinstance(func, ast.Name) and func.id in MODEL_TABLES:
        return func.id
    if isinstance(func, ast.Attribute) and func.attr in MODEL_TABLES:
        return func.attr
    return None


def _call_sets_non_none_status(node: ast.Call) -> bool:
    for kw in node.keywords:
        if kw.arg != "status":
            continue
        return not _is_none_constant(kw.value)
    return False


def find_status_writes(paths: Iterable[Path]) -> list[StatusWrite]:
    """สแกนไฟล์ที่ระบุ หาการเขียน `status` ทุกรูป พร้อมบอกว่าเป็นของตารางไหน

    pure function — รับ `paths` เข้ามาโดยตรง ไม่เดินหา `REPO_ROOT` เอง เพื่อให้เทส
    "ป้อน source สังเคราะห์" ทำได้โดยไม่ต้องมีไฟล์จริงในต้นไม้
    """
    writes: list[StatusWrite] = []
    for path in paths:
        tree = _parse(path)
        if tree is None:
            continue
        model_names = _model_names_in(tree)
        file_table = _table_from_file(model_names)

        for node in ast.walk(tree):
            location = f"{path}:{getattr(node, 'lineno', 0)}"

            if isinstance(node, ast.Assign) and not _is_none_constant(node.value):
                for target in node.targets:
                    if not isinstance(target, ast.Attribute) or target.attr != "status":
                        continue
                    if (
                        isinstance(target.value, ast.Name)
                        and target.value.id in _IGNORED_TARGET_NAMES
                    ):
                        continue
                    writes.append(
                        StatusWrite(
                            location=location,
                            table=_table_from_variable(target.value),
                            kind=UPDATE,
                        )
                    )
                continue

            if isinstance(node, ast.Dict):
                if not model_names:
                    # ไฟล์ที่ไม่แตะโมเดลไหนเลย เช่น health check ของ app/main.py
                    continue
                for key, value in zip(node.keys, node.values, strict=True):
                    if not (isinstance(key, ast.Constant) and key.value == "status"):
                        continue
                    if _is_none_constant(value):
                        continue
                    writes.append(
                        StatusWrite(location=location, table=file_table, kind=INSERT)
                    )
                continue

            if not isinstance(node, ast.Call):
                continue

            model_name = _model_call_name(node)
            if model_name is not None:
                if _call_sets_non_none_status(node):
                    writes.append(
                        StatusWrite(
                            location=location,
                            table=MODEL_TABLES[model_name],
                            kind=INSERT,
                        )
                    )
                continue

            if _is_setattr_status_call(node):
                writes.append(
                    StatusWrite(
                        location=location,
                        table=_table_from_variable(node.args[0]),
                        kind=UPDATE,
                    )
                )
            elif _is_values_status_call(node):
                writes.append(
                    StatusWrite(
                        location=location,
                        table=_table_from_call_chain(node, model_names),
                        kind=UPDATE,
                    )
                )
    return writes


# --------------------------------------------------------------------------
# closed-world บนของจริงในต้นไม้ — assert ความเท่ากันของเซต ไม่ใช่ subset (D5)
# --------------------------------------------------------------------------

ALLOWED_UPDATE_WRITERS: dict[str, set[str]] = {
    # 🔴 ADR-0025 D5 — **ห้ามขยับสักไฟล์** · ADR-0033 ไม่มีสิทธิ์กลับมตินี้
    "posters": {"app/services/poster_service.py"},
    # ADR-0033 D1 — ประตูของเครื่อง order
    "orders": {"app/services/order_service.py"},
    # lazy-expire (ADR-0033 D4) + พลิกเป็น converted ตอนสร้างออร์เดอร์
    "reservations": {"app/services/order_service.py"},
    # ยังไม่มีผู้เขียน — **ต้องว่าง** จนกว่ารอบที่ทำมันจะมาถึง (ADR-0033 D5)
    "payments": set(),
    "disputes": set(),
    "payouts": set(),
    "notification_outbox": set(),
}

ALLOWED_INSERT_WRITERS: dict[str, set[str]] = {
    "posters": {"scripts/seed/seed_posters.py"},
    "orders": {"app/services/order_service.py"},
    "reservations": {"app/repositories/reservation_repository.py"},
    "payments": set(),
    "disputes": set(),
    "payouts": set(),
    "notification_outbox": set(),
}


def _repo_writes() -> list[StatusWrite]:
    return find_status_writes(_iter_python_files())


def _writer_files(writes: list[StatusWrite], *, table: str, kind: str) -> set[str]:
    return {
        str(Path(write.location.rsplit(":", 1)[0]).relative_to(REPO_ROOT))
        for write in writes
        if write.table == table and write.kind == kind
    }


def test_no_status_write_is_unclassified() -> None:
    """การเขียน `status` ที่บอกไม่ได้ว่าเป็นของตารางไหน = closed-world คุ้มไม่ได้

    fail-closed โดยตั้งใจ — ทางแก้คือ **ตั้งชื่อตัวแปรให้ตรงกับตาราง** (`order`,
    `poster`, `reservation`, …) ไม่ใช่ผ่อนตัวสแกนให้ข้ามไป
    """
    unclassified = [write for write in _repo_writes() if write.table is None]
    assert not unclassified, (
        "มีการเขียน `status` ที่จำแนกตารางไม่ได้ — ตั้งชื่อตัวแปรให้ตรงกับตาราง "
        f"หรือเพิ่มโมเดลเข้า MODEL_TABLES: {unclassified}"
    )


def test_status_update_closed_world_per_table() -> None:
    """แดงเมื่อมีไฟล์อื่นเขียน `<table>.status` ของแถวที่มีอยู่แล้ว **และ** แดงเมื่อไฟล์
    ที่ควรเขียนเลิกเขียน — เท่ากับเซต ไม่ใช่ subset (ADR-0025 D5 · ADR-0033 D5)
    """
    writes = _repo_writes()
    actual = {
        table: _writer_files(writes, table=table, kind=UPDATE)
        for table in ALLOWED_UPDATE_WRITERS
    }
    assert actual == ALLOWED_UPDATE_WRITERS, (
        "เซตผู้เขียน (UPDATE) `status` ไม่ตรงกับที่ ADR-0025 D5 / ADR-0033 D5 กำหนด: "
        f"{actual}"
    )


def test_status_insert_closed_world_per_table() -> None:
    """เซตผู้ **สร้างแถวใหม่พร้อมกำหนด `status`** — คนละเซตกับ UPDATE โดยตั้งใจ (D5)

    `split_entry.py` ต้องไม่อยู่ในเซตของ `posters` เพราะปล่อย `server_default`
    """
    writes = _repo_writes()
    actual = {
        table: _writer_files(writes, table=table, kind=INSERT)
        for table in ALLOWED_INSERT_WRITERS
    }
    assert actual == ALLOWED_INSERT_WRITERS, (
        "เซตผู้เขียน (INSERT) `status` ไม่ตรงกับที่ ADR-0025 D5 / ADR-0033 D5 กำหนด: "
        f"{actual}"
    )


def test_tables_without_a_writer_are_asserted_empty_not_merely_unlisted() -> None:
    """ADR-0033 D5 สั่งให้ `payments`/`disputes` เป็น **เซตว่างที่ถูก assert**

    เทสนี้กันไม่ให้ใครลบแถวว่างพวกนั้นออกจาก dict แล้วเข้าใจว่า "ไม่มีผู้เขียน"
    ทั้งที่จริงคือ "ไม่ได้ตรวจ" — สองอย่างนี้หน้าตาเหมือนกันเป๊ะบนหน้า checklist
    """
    for table in ("payments", "disputes", "payouts", "notification_outbox"):
        assert ALLOWED_UPDATE_WRITERS[table] == set()
        assert ALLOWED_INSERT_WRITERS[table] == set()


# --------------------------------------------------------------------------
# พิสูจน์ว่าตัวสแกนจับเป็น — ป้อน source สังเคราะห์ที่ละเมิดเข้าไปตรง ๆ (D5 · 🔴)
# --------------------------------------------------------------------------


def _write(tmp_path: Path, name: str, source: str) -> Path:
    path = tmp_path / name
    path.write_text(source, encoding="utf-8")
    return path


def test_update_scanner_catches_synthetic_poster_violation(tmp_path: Path) -> None:
    """ถ้าตัวสแกนพัง (เช่น `ast.walk` ไม่ทำงาน หรือเงื่อนไข attr ผิด) เทส closed-world
    ข้างบนจะเขียวตลอดกาลโดยไม่ได้ตรวจอะไรเลย — เทสนี้พิสูจน์ว่าไม่ใช่กรณีนั้น
    """
    violating = _write(
        tmp_path,
        "rogue_writer.py",
        "def sneak_a_write(poster):\n"
        '    poster.status = "sold"  # ไม่ผ่าน mark_sold() เลย\n',
    )

    assert find_status_writes([violating]) == [
        StatusWrite(location=f"{violating}:2", table="posters", kind=UPDATE)
    ]


def test_update_scanner_catches_synthetic_order_violation(tmp_path: Path) -> None:
    """INF-33 AC-2 — `UPDATE orders SET status` นอกประตูต้องถูกจับ **และต้องถูกจำแนก
    ว่าเป็นของ `orders`** ไม่ใช่ไปกองรวมกับเซตของ `posters`
    """
    violating = _write(
        tmp_path,
        "rogue_order_writer.py",
        "def sneak_a_write(order):\n"
        '    order.status = "COMPLETED"  # ไม่ผ่าน apply_order_transition() เลย\n',
    )

    assert find_status_writes([violating]) == [
        StatusWrite(location=f"{violating}:2", table="orders", kind=UPDATE)
    ]


def test_update_scanner_catches_synthetic_reservation_violation(tmp_path: Path) -> None:
    violating = _write(
        tmp_path,
        "rogue_reservation_writer.py",
        'def sneak_a_write(reservation):\n    reservation.status = "expired"\n',
    )

    assert find_status_writes([violating]) == [
        StatusWrite(location=f"{violating}:2", table="reservations", kind=UPDATE)
    ]


def test_update_scanner_catches_synthetic_payment_violation(tmp_path: Path) -> None:
    """เซตของ `payments` ต้องว่าง — เทสนี้พิสูจน์ว่า "ว่าง" มาจากการตรวจแล้วไม่เจอ
    ไม่ใช่จากการที่ตัวสแกนมองไม่เห็นการเขียนของตารางนี้เลย
    """
    violating = _write(
        tmp_path,
        "rogue_payment_writer.py",
        'def sneak_a_write(payment):\n    payment.status = "VERIFIED"\n',
    )

    assert find_status_writes([violating]) == [
        StatusWrite(location=f"{violating}:2", table="payments", kind=UPDATE)
    ]


def test_update_scanner_flags_unknown_variable_name_as_unclassified(
    tmp_path: Path,
) -> None:
    """ชื่อตัวแปรที่จำแนกไม่ได้ต้อง **ไม่ถูกข้ามเงียบ ๆ** — ต้องโผล่มาเป็น
    `table=None` ซึ่งทำให้ `test_no_status_write_is_unclassified` แดง
    """
    violating = _write(
        tmp_path, "rogue_unknown.py", 'def sneak_a_write(row):\n    row.status = "x"\n'
    )

    assert find_status_writes([violating]) == [
        StatusWrite(location=f"{violating}:2", table=None, kind=UPDATE)
    ]


def test_update_scanner_ignores_args_status(tmp_path: Path) -> None:
    """`args.status = ...` (argparse Namespace ของ CLI) ไม่ใช่การเขียน ORM — ต้องไม่ถูก
    นับ (`seed_posters.py` มี `args.status = args.status or "available"` จริงในไฟล์)
    """
    benign = _write(tmp_path, "cli.py", 'args.status = args.status or "available"\n')

    assert find_status_writes([benign]) == []


def test_update_scanner_ignores_none_assignment(tmp_path: Path) -> None:
    """`x.status = None` ไม่ใช่การเขียนค่าเข้า status — ไม่นับเป็น writer"""
    benign = _write(tmp_path, "cli.py", "poster.status = None\n")

    assert find_status_writes([benign]) == []


def test_update_scanner_catches_setattr_status(tmp_path: Path) -> None:
    """H4 (code-critic รอบ 1) — รูปที่ `correction_entry.py`/`manual_entry.py`/
    `reference_entry.py` ใช้จริงกับฟิลด์อื่นทุกวัน (`setattr(poster, name, value)`)
    ต้องถูกจับถ้าชื่อฟิลด์เป็น literal `"status"`
    """
    violating = _write(
        tmp_path,
        "rogue_setattr.py",
        "def sneak_a_write(poster, value):\n"
        '    setattr(poster, "status", value)  # ไม่ผ่าน mark_sold() เลย\n',
    )

    assert find_status_writes([violating]) == [
        StatusWrite(location=f"{violating}:2", table="posters", kind=UPDATE)
    ]


def test_update_scanner_ignores_setattr_of_other_fields(tmp_path: Path) -> None:
    """`setattr(poster, "condition_grade", value)` ไม่ใช่การเขียน status — ไม่นับ"""
    benign = _write(tmp_path, "cli.py", 'setattr(poster, "condition_grade", value)\n')

    assert find_status_writes([benign]) == []


def test_update_scanner_ignores_setattr_with_dynamic_field_name(tmp_path: Path) -> None:
    """`setattr(poster, name, value)` ที่ `name` เป็นตัวแปร (ไม่ใช่ literal "status")
    — รูปจริงที่ `correction_entry.py`/`manual_entry.py` ใช้ (field มาจาก
    `WRITABLE_FIELDS` ซึ่งไม่มี `"status"`) ไม่มีทางรู้ตอน scan ว่าค่า runtime คืออะไร
    จึงไม่นับ (ด่านตัวจริงของกรณีนี้คือ `WRITABLE_FIELDS` fail-closed ที่ตัวสคริปต์เอง)
    """
    benign = _write(tmp_path, "cli.py", "setattr(poster, name, value)\n")

    assert find_status_writes([benign]) == []


def test_update_scanner_catches_core_update_values_status(tmp_path: Path) -> None:
    """H4 (code-critic รอบ 1) — รูปที่ `test_poster_sold_at_constraint.py` ใช้จำลอง
    seeder (`update(Poster.__table__).where(...).values(status=...)`)
    """
    violating = _write(
        tmp_path,
        "rogue_core_update.py",
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
    )

    # ไม่ผูกกับเลขบรรทัดเป๊ะ — `ast.Call.lineno` ของ chain หลายบรรทัดชี้ที่จุดเริ่ม
    # ของนิพจน์ทั้งก้อน ไม่ใช่บรรทัดของ `.values(...)` เอง
    writes = find_status_writes([violating])
    assert len(writes) == 1, writes
    assert writes[0].table == "posters"
    assert writes[0].kind == UPDATE


def test_update_scanner_classifies_core_update_on_another_table(tmp_path: Path) -> None:
    """`.values(status=...)` ของตารางอื่นต้องเข้าเซตของ **ตารางนั้น** ไม่ใช่ถูกข้าม

    ‹เปลี่ยนพฤติกรรมโดยตั้งใจ 2026-08-26› ตัวสแกนเดิมข้ามเคสนี้ทั้งหมด (gate ด้วย
    "ไฟล์อ้างถึง Poster") ซึ่งแปลว่า `reservations`/`orders` **ไม่มีใครคุ้มเลย** —
    ADR-0033 D5 สั่งให้แต่ละตารางมีเซตของตัวเอง เคสนี้จึงต้องถูกจับ ไม่ใช่ถูกยกเว้น
    """
    violating = _write(
        tmp_path,
        "rogue_reservation_update.py",
        "from app.models.reservation import Reservation\n"
        "from sqlalchemy import update\n"
        "\n"
        "def sneak_an_update(session, reservation_id):\n"
        "    return update(Reservation).where(Reservation.id == reservation_id)"
        '.values(status="expired")\n',
    )

    writes = find_status_writes([violating])
    assert len(writes) == 1, writes
    assert writes[0].table == "reservations"


def test_update_scanner_catches_core_update_values_status_via_aliased_import(
    tmp_path: Path,
) -> None:
    """H4/Low (code-critic รอบ 2) — `from ... import Poster as P` แล้วใช้แต่ `P`
    ต่อจากนั้น ต้องยังจำแนกได้ว่าเป็นของ `posters` แม้ไม่มี identifier `Poster`
    เปล่า ๆ โผล่อีกเลยนอกบรรทัด import
    """
    violating = _write(
        tmp_path,
        "rogue_aliased_update.py",
        "from app.models.poster import Poster as P\n"
        "from sqlalchemy import update\n"
        "\n"
        "def sneak_an_update(session, poster_id):\n"
        "    return update(P.__table__).where(P.__table__.c.id == poster_id)"
        '.values(status="sold")\n',
    )

    writes = find_status_writes([violating])
    assert len(writes) == 1, writes
    assert writes[0].table == "posters"


def test_insert_scanner_catches_synthetic_poster_call(tmp_path: Path) -> None:
    violating = _write(
        tmp_path,
        "rogue_insert.py",
        "from app.models.poster import Poster\n"
        "\n"
        "def sneak_an_insert():\n"
        '    return Poster(title="x", status="sold")\n',
    )

    assert find_status_writes([violating]) == [
        StatusWrite(location=f"{violating}:4", table="posters", kind=INSERT)
    ]


def test_insert_scanner_classifies_order_constructor(tmp_path: Path) -> None:
    """`Order(status=...)` ต้องเข้าเซต INSERT ของ `orders` — เป็นรูปที่
    `order_service.create_order()` ใช้จริง (ตั้งค่าชัดเจนแทนการพึ่ง server_default)
    """
    violating = _write(
        tmp_path,
        "rogue_order_insert.py",
        "from app.models.order import Order\n"
        "\n"
        "def sneak_an_insert():\n"
        '    return Order(order_no="PN-260826-0001", status="AWAITING_PAYMENT")\n',
    )

    assert find_status_writes([violating]) == [
        StatusWrite(location=f"{violating}:4", table="orders", kind=INSERT)
    ]


def test_insert_scanner_catches_synthetic_dict_literal_that_touches_a_model(
    tmp_path: Path,
) -> None:
    """เลียนแบบรูปจริงของ `seed_posters.py`: dict คีย์ "status" ในไฟล์ที่อ้างถึง
    `Poster` อยู่ (แม้จะคนละฟังก์ชันกับจุดที่ใช้ dict นั้นจริง ๆ)
    """
    violating = _write(
        tmp_path,
        "rogue_dict.py",
        "from app.models.poster import Poster\n"
        "\n"
        "def build_row(status):\n"
        '    return {"id": 1, "status": status}\n'
        "\n"
        "def use_it():\n"
        "    insert(Poster.__table__).values(build_row('sold'))\n",
    )

    assert find_status_writes([violating]) == [
        StatusWrite(location=f"{violating}:4", table="posters", kind=INSERT)
    ]


def test_insert_scanner_catches_dict_literal_via_aliased_model_import(
    tmp_path: Path,
) -> None:
    """H4/Low (code-critic รอบ 2) — import แบบตั้งชื่อเล่น (`Poster as P`)
    ยังต้องจำแนกได้เหมือนกัน
    """
    violating = _write(
        tmp_path,
        "rogue_aliased_dict.py",
        "from app.models.poster import Poster as P\n"
        "\n"
        "def build_row(status):\n"
        '    return {"id": 1, "status": status}\n'
        "\n"
        "def use_it():\n"
        "    insert(P.__table__).values(build_row('sold'))\n",
    )

    assert find_status_writes([violating]) == [
        StatusWrite(location=f"{violating}:4", table="posters", kind=INSERT)
    ]


def test_insert_scanner_ignores_dict_literal_in_file_that_never_touches_a_model(
    tmp_path: Path,
) -> None:
    """`app/main.py` มี `{"status": "ok"}` (health check) แต่ไม่อ้างถึงโมเดลไหนเลย
    — ต้องไม่ถูกนับ (กันเทสข้อบนไม่ให้ over-match จน false positive กว้างเกิน)
    """
    benign = _write(
        tmp_path, "health.py", 'def healthcheck():\n    return {"status": "ok"}\n'
    )

    assert find_status_writes([benign]) == []


def test_insert_scanner_flags_dict_literal_in_file_that_touches_two_models(
    tmp_path: Path,
) -> None:
    """ไฟล์ที่อ้างถึงสองโมเดลแล้วมี dict คีย์ `"status"` = **กำกวม ต้องแดง**

    ไม่ใช่การเดาว่าเป็นของตารางไหน — คนเขียนต้องแยกให้ชัดเอง (เขียนเป็น
    constructor ของโมเดล หรือแยกไฟล์)
    """
    ambiguous = _write(
        tmp_path,
        "rogue_two_models.py",
        "from app.models.poster import Poster\n"
        "from app.models.order import Order\n"
        "\n"
        "def build_row(status):\n"
        '    return {"id": 1, "status": status}\n',
    )

    assert find_status_writes([ambiguous]) == [
        StatusWrite(location=f"{ambiguous}:5", table=None, kind=INSERT)
    ]


def test_insert_scanner_ignores_none_status_dict_value(tmp_path: Path) -> None:
    benign = _write(
        tmp_path,
        "rogue_dict.py",
        "from app.models.poster import Poster\n"
        "\n"
        "def build_row():\n"
        '    return {"id": 1, "status": None}\n',
    )

    assert find_status_writes([benign]) == []
