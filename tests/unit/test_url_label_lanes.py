"""AC-1 ของ INF-51 (BL-167) — `_url_label()` เป็นป้ายเดียวของทุก lane · closed-world

ทรงเดียวกับ `test_seed_lane_shared_rules.py::test_every_script_that_offers_target_is_in_TARGET_GUARD_LANES`
— ล็อก **สายไฟ** ด้วย AST ให้ครบทุกเส้นที่ผลิตป้ายปลายทาง แทนเทสพฤติกรรมเต็มรูปที่ต้อง
ซ้ำกัน 13 รอบ (เทสพฤติกรรมเต็มรูปของ `_url_label()`/`assert_target_database()`/
`_assert_dev_database()` เองอยู่ที่ `test_apply_suggestions.py` และ
`test_seed_posters_dev_database_guard.py` — ที่นี่พิสูจน์แค่ว่า **ทุก lane ต่อสายเข้า
ฟังก์ชันที่ถูกพิสูจน์แล้วเหล่านั้นจริง** ไม่ได้ประกอบป้ายเอง (mutant M8)
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from scripts.seed import _shared
from scripts.seed import apply_suggestions as suggest_mod
from scripts.seed import make_reference_sheet as make_reference_sheet_mod
from scripts.seed import make_split_sheet as make_split_sheet_mod
from scripts.seed import seed_posters as seed_mod
from tests.unit.test_seed_lane_shared_rules import (
    SHEET_TARGET_LANES,
    TARGET_GUARD_LANES,
    _callee_name,
    _main_of,
)

# ‹INF-51 · AC-1› ป้ายเดียวของทุก lane = `apply_suggestions._url_label()` — เรียกผ่าน
# `assert_target()` (7 เส้นของ `TARGET_GUARD_LANES` + 2 เส้นของ `SHEET_TARGET_LANES`
# wrap ผ่าน `manual_entry.assert_target()`), `assert_target_database()` ตรง ๆ
# (`apply_suggestions` เอง · `make_reference_sheet` · `make_split_sheet`) หรือ
# `_assert_dev_database()` ที่คืน/พิมพ์ผ่าน `_url_label()` แล้ว (`seed_posters`)
LABEL_EXTRA_LANES = (
    suggest_mod,
    make_reference_sheet_mod,
    make_split_sheet_mod,
    seed_mod,
)
LABEL_LANES = TARGET_GUARD_LANES + SHEET_TARGET_LANES + LABEL_EXTRA_LANES
LABEL_IDS = tuple(m.__name__.rsplit(".", 1)[-1] for m in LABEL_LANES)

LABEL_PRODUCING_CALL_NAMES = {
    "assert_target",
    "assert_target_database",
    "_assert_dev_database",
}
# ชื่อตัวแปรที่แต่ละ lane ผูกป้ายไว้จริง (ตรวจแล้วทีละไฟล์ — ไม่ได้เดา)
LABEL_BIND_NAME = {
    "manual_entry": "target_label",
    "reference_entry": "target_label",
    "correction_entry": "target_label",
    "split_entry": "target_label",
    "sold_entry": "target_label",
    "photo_entry": "target_label",
    "order_ops": "target_label",
    "make_manual_sheet": "label",
    "make_correction_sheet": "label",
    "apply_suggestions": "target_label",
    "make_reference_sheet": "target_label",
    "make_split_sheet": "target_label",
    "seed_posters": "target",
}
assert set(LABEL_BIND_NAME) == set(LABEL_IDS), "รายการนี้ต้องครบทุก lane ใน LABEL_LANES"


# --------------------------------------------------------------------------
# closed-world — เส้นใหม่ที่เรียกฟังก์ชันผลิตป้ายต้องเข้า LABEL_LANES ก่อนมีเทสของ
# ตัวเอง (AST ไม่ใช่ substring — ทรงเดียวกับ TARGET_GUARD_LANES)
# --------------------------------------------------------------------------


def _calls_a_label_producing_function(path: Path) -> bool:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return any(
        isinstance(node, ast.Call) and _callee_name(node) in LABEL_PRODUCING_CALL_NAMES
        for node in ast.walk(tree)
    )


def test_every_module_that_produces_a_target_label_is_in_LABEL_LANES() -> None:
    """closed-world — กวาด `scripts/seed/*.py` + `scripts/orders/*.py` ด้วย AST หา
    โมดูลที่เรียก `assert_target`/`assert_target_database`/`_assert_dev_database` แล้ว
    เทียบกับ `LABEL_LANES` แบบเซตปิด — ไม่ตรง = มี lane ที่หลุดไปโดยไม่มีอะไรครอบ

    🔴 `apply_suggestions.py` เป็น**เจ้าของ** `assert_target_database()` (มี `def` +
    เรียกใช้เองใน `main()`) จึงถูกกวาดเจอโดยธรรมชาติ ไม่ต้องยกเว้นแบบเทส
    `test_every_script_that_offers_target_is_in_TARGET_GUARD_LANES` ที่ยกเว้นมันออก
    (เทสนั้นเช็คคนละอย่าง — "ใครมี `--target` สองชั้น" ไม่ใช่ "ใครผลิตป้าย")
    """
    seed_dir = Path(_shared.__file__).parent
    orders_dir = seed_dir.parent / "orders"
    candidates = sorted(seed_dir.glob("*.py")) + sorted(orders_dir.glob("*.py"))

    found = {p.stem for p in candidates if _calls_a_label_producing_function(p)}
    assert found == set(LABEL_IDS)


# --------------------------------------------------------------------------
# ต่อ lane — ค่าที่ผูกกับชื่อป้ายใน main() ต้องมาจาก Call ของฟังก์ชันผลิตป้ายที่รู้จัก
# เท่านั้น ห้ามประกอบเอง (mutant M8: `target_label = f"{host}/{db_name} ..."`)
# --------------------------------------------------------------------------


# ‹แก้ 2026-09-27 · code-critic round 1 INF-51 · mutant MC› เดิม `_label_source_call`
# ดูแค่ `FormattedValue` **ตัวแรก** ของ f-string ⇒ `f"{assert_target(...)}  [--target
# {args.target}] {database_url}"` (เติม `{database_url}` เป็นชิ้นที่สาม) ผ่านเทสไปได้
# ฉลุยเพราะไม่มีใครเดินดูชิ้นที่เหลือเลย — เปลี่ยนมาเดินทั้ง expression tree แทน: หา Call
# ของฟังก์ชันผลิตป้ายทุกตัวใน `value` แล้วเก็บ node ที่อยู่ **ในอาร์กิวเมนต์ของ Call
# เหล่านั้น** ไว้เป็นโซนที่อนุญาต จากนั้นเดินทั้งต้นไม้อีกรอบ — เจอ `Name`/`Attribute`
# ที่ชื่อ `database_url`/`host`/`db_name`/`urlsplit` อยู่**นอก**โซนนั้นเมื่อไหร่ = ประกอบ
# ป้ายเองบางส่วน ต้องแดงทันที ไม่ว่าจะอยู่ที่ไหนใน expression (ไม่ใช่แค่ตัวแรก)
FORBIDDEN_RAW_NAMES = {"database_url", "host", "db_name", "urlsplit"}


def _approved_call_nodes(value: ast.expr, known_names: set[str]) -> list[ast.Call]:
    return [
        node
        for node in ast.walk(value)
        if isinstance(node, ast.Call) and _callee_name(node) in known_names
    ]


def _node_ids_inside_call_arguments(call: ast.Call) -> set[int]:
    ids: set[int] = {id(call)}
    for arg_node in list(call.args) + [kw.value for kw in call.keywords]:
        for sub in ast.walk(arg_node):
            ids.add(id(sub))
    return ids


def _binds_to(node: ast.AST, name: str) -> bool:
    if not isinstance(node, ast.Assign):
        return False
    return any(isinstance(t, ast.Name) and t.id == name for t in node.targets)


@pytest.mark.parametrize("module", LABEL_LANES, ids=LABEL_IDS)
def test_label_bound_in_main_comes_only_from_a_label_producing_call(module) -> None:
    """🔴 มิวเทชันที่ต้องตาย:
    - M8 เดิม: `target_label = f"{host}/{db_name}  [--target {args.target}]"`
      (ประกอบป้ายทั้งก้อนเองจากค่าดิบ ข้าม `_url_label()` ไปเลย)
    - MC (code-critic round 1): `target_label = f"{assert_target(...)}  [--target
      {args.target}] {database_url}"` — Call ที่ถูกต้องยังอยู่ แต่แอบเติมชิ้นดิบเข้าไป
      อีกชิ้นข้าง ๆ กัน ต้องแดงเหมือนกันแม้ Call แรกจะถูกต้องเป๊ะก็ตาม
    """
    bind_name = LABEL_BIND_NAME[module.__name__.rsplit(".", 1)[-1]]
    main = _main_of(module)
    assigns = [node for node in ast.walk(main) if _binds_to(node, bind_name)]
    assert assigns, f"{module.__name__}: main() ไม่ผูกชื่อ {bind_name!r} เลย"

    known_names = LABEL_PRODUCING_CALL_NAMES | {"_url_label"}
    for node in assigns:
        value = node.value
        approved_calls = _approved_call_nodes(value, known_names)
        assert approved_calls, (
            f"{module.__name__}: {bind_name} = {ast.unparse(value)} ไม่มี Call ของ "
            f"ฟังก์ชันผลิตป้ายที่รู้จักเลย ({sorted(known_names)})"
        )

        allowed_ids: set[int] = set()
        for call in approved_calls:
            allowed_ids |= _node_ids_inside_call_arguments(call)

        for sub in ast.walk(value):
            if id(sub) in allowed_ids:
                continue
            raw_name = None
            if isinstance(sub, ast.Name):
                raw_name = sub.id
            elif isinstance(sub, ast.Attribute):
                raw_name = sub.attr
            assert raw_name not in FORBIDDEN_RAW_NAMES, (
                f"{module.__name__}: {bind_name} = {ast.unparse(value)} อ้าง "
                f"{raw_name!r} ดิบอยู่นอกอาร์กิวเมนต์ของฟังก์ชันผลิตป้าย"
            )


# --------------------------------------------------------------------------
# driver-error hardening (มติ 2 ของ GATE 1) — 10 lane ต้องมี except (PostgresError,
# SQLAlchemyError) ครอบรอบจุดต่อ DB ใน main() และห้ามพิมพ์ตัว exception ดิบ
# --------------------------------------------------------------------------

DRIVER_ERROR_LANES = TARGET_GUARD_LANES + (
    suggest_mod,
    make_reference_sheet_mod,
    make_split_sheet_mod,
)
DRIVER_ERROR_IDS = tuple(m.__name__.rsplit(".", 1)[-1] for m in DRIVER_ERROR_LANES)
assert len(DRIVER_ERROR_LANES) == 10, "มติ 2 ของ GATE 1 ระบุ 10 lane เป๊ะ"


def _driver_error_handlers_in(entry: ast.AST) -> list[ast.ExceptHandler]:
    handlers = []
    for node in ast.walk(entry):
        if not isinstance(node, ast.ExceptHandler) or node.type is None:
            continue
        type_names = set()
        if isinstance(node.type, ast.Tuple):
            type_names = {elt.id for elt in node.type.elts if isinstance(elt, ast.Name)}
        elif isinstance(node.type, ast.Name):
            type_names = {node.type.id}
        if {"PostgresError", "SQLAlchemyError"} & type_names:
            handlers.append(node)
    return handlers


@pytest.mark.parametrize("module", DRIVER_ERROR_LANES, ids=DRIVER_ERROR_IDS)
def test_main_has_a_driver_error_handler_that_never_prints_the_raw_exception(
    module,
) -> None:
    """🔴 มิวเทชัน M10 (ถอด `except (PostgresError, SQLAlchemyError)` ออก) และมิวเทชัน
    "พิมพ์ `{exc}` ตรง ๆ แทน `type(exc).__name__`" ต้องทำให้เทสนี้แดงทั้งคู่
    """
    main = _main_of(module)
    handlers = _driver_error_handlers_in(main)
    assert handlers, f"{module.__name__}: main() ไม่มี except (PostgresError, ...) เลย"

    for handler in handlers:
        exc_name = handler.name  # ชื่อตัวแปร `as exc`
        for node in ast.walk(handler):
            if not (isinstance(node, ast.Name) and node.id == exc_name):
                continue
            # อนุญาตเฉพาะตอนเป็นอาร์กิวเมนต์ของ `type(...)` — ทุกที่อื่นห้ามอ้างชื่อนี้
            # ตรง ๆ (โดยเฉพาะใน f-string/`.format()`/`str.__add__` ที่จะพิมพ์ค่าดิบ)
            parent_is_type_call = False
            for maybe_call in ast.walk(handler):
                if (
                    isinstance(maybe_call, ast.Call)
                    and _callee_name(maybe_call) == "type"
                    and maybe_call.args
                    and maybe_call.args[0] is node
                ):
                    parent_is_type_call = True
                    break
            assert parent_is_type_call, (
                f"{module.__name__}: except handler อ้าง {exc_name!r} ตรง ๆ นอก "
                "type(...) — เสี่ยงพิมพ์ exception message ดิบที่มี credential ปน"
            )
