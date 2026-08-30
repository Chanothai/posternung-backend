"""กฎที่ **ทุกเส้นทางเขียน `posters` ต้องเชื่อฟังเหมือนกัน** — เจ้าของคือ `_shared.py`

ขอบเขตของไฟล์นี้คือ *ข้ามเส้น* โดยตั้งใจ (BL-101 · BL-102) — สิ่งที่เคยอยู่ใน
`test_reference_entry.py` แล้วครอบเส้นที่ 4 เส้นเดียวถูกย้ายมาที่นี่และ parametrize
ต่อโมดูล เพราะชื่อไฟล์เดิมโกหกขอบเขตทันทีที่กฎเดียวกันบังคับกับสามเส้น

กฎที่ล็อกไว้ที่นี่:
* ADR-0010 **D5** — `reviewed_at` มาจาก `_parse_reviewed_at(<สิ่งที่คนพิมพ์>)` เท่านั้น ·
  ไม่มี default เป็นเวลาปัจจุบัน · นาฬิกาถูกอ่านที่เดียวและอ่านเพื่อ **ปฏิเสธ** เท่านั้น
* ตัวอย่าง `--reviewed-at` ทุกที่ต้องเป็น placeholder ที่ก๊อปแล้วรันไม่ผ่าน
* ใบงาน CSV ที่มี field เกิน header ต้องได้ `PrecheckError` ที่บอกเลขบรรทัด
  ไม่ใช่ `AttributeError: 'list' object has no attribute 'strip'`
* ทั้งสามเส้นต้องใช้ **object เดียวกัน** ไม่ใช่ก๊อปกฎไปคนละชุด
"""

from __future__ import annotations

import ast
import inspect
import re
import sys
import uuid
from datetime import datetime
from pathlib import Path

import pytest

from scripts.seed import _shared
from scripts.seed import apply_suggestions as suggest_mod
from scripts.seed import correction_entry as correction_mod
from scripts.seed import manual_entry as manual_mod
from scripts.seed import photo_entry as photo_mod
from scripts.seed import reference_entry as reference_mod
from scripts.seed import seed_posters as seed_mod
from scripts.seed import sold_entry as sold_mod
from scripts.seed import split_entry as split_mod
from scripts.seed._shared import PrecheckError, assert_not_in_the_future

# หกเส้นที่รับ `--reviewed-at` — เส้นที่ 1 (`seed_posters.py`) ไม่มีแนวคิดนี้เลย
# เพราะเป็น INSERT ตั้งต้นที่ไม่มีใครเซ็นรับ (ADR-0015 D1)
# ‹เพิ่ม `correction_entry` 2026-08-09 · INF-21› ‹เพิ่ม `split_entry` 2026-08-12 ·
# INF-22 (ADR-0024)› ‹เพิ่ม `sold_entry` 2026-08-15 · INF-24 (ADR-0025) — code-critic
# รอบ 1 ยืนยันว่า "ไม่มีใบงาน CSV" ไม่ใช่เหตุผลที่พอจะยกเว้นออกจากด่านกลาง: ด่านทุกตัว
# ที่ไม่ผูกกับ CSV จริง ๆ (identity · ไม่มี DictReader ของตัวเอง · ที่มาของ
# `reviewed_at` · นาฬิกาอ่านที่เดียว) ยังบังคับกับมันได้เหมือนเดิม จึงต้องอยู่ใน LANES
# ไม่ใช่มีเทสแยกของตัวเอง› เส้นใหม่เข้าที่นี่ **ก่อน** เทสของตัวเองเสียอีก เพราะ
# `test_every_script_that_accepts_reviewed_at_is_in_LANES` จะแดงทันทีที่ไฟล์ถูกสร้าง
# — นั่นคือมันทำงานถูก ไม่ใช่ต้องผ่อน
LANES = (suggest_mod, manual_mod, reference_mod, correction_mod, split_mod, sold_mod)
LANE_IDS = tuple(m.__name__.rsplit(".", 1)[-1] for m in LANES)

# ห้าเส้นที่มีใบงาน CSV จริง (ต่างจาก `LANES` ที่ตอนนี้รวม `sold_entry` ที่ไม่มีใบงาน
# ด้วย — ADR-0025 OD-3: argument ต่อใบ ไม่ใช่ไฟล์ใบงาน batch เพราะปริมาณจริง 3–5
# ใบ/เดือน) ใช้เฉพาะสองเทสที่พึ่ง `--file` ตรง ๆ ด้านล่าง (`test_a_future_reviewed_at_...`
# / `test_a_past_reviewed_at_...`) — `sold_entry.py` ไม่มี flag นี้เลยเพราะรับ
# `--poster-uuid`/`--sold-at`/`--reason` แทน จึงพิสูจน์ "จบก่อนแตะ DB" คนละรูปแบบ
# (ดู `tests/unit/test_sold_entry.py`)
SHEET_LANES = (suggest_mod, manual_mod, reference_mod, correction_mod, split_mod)
SHEET_LANE_IDS = tuple(m.__name__.rsplit(".", 1)[-1] for m in SHEET_LANES)


def _tree(module) -> ast.Module:
    return ast.parse(inspect.getsource(module))


def _callee_name(node: ast.Call) -> str:
    func = node.func
    if isinstance(func, ast.Attribute):
        return func.attr
    if isinstance(func, ast.Name):
        return func.id
    return ""


# --------------------------------------------------------------------------
# กฎหนึ่งข้อมีที่อยู่ที่เดียว — ต้องเป็น object เดียวกัน ไม่ใช่แค่พฤติกรรมเหมือนกัน
# --------------------------------------------------------------------------

SHARED_NAMES = (
    "PrecheckError",
    "_parse_reviewed_at",
    "assert_not_in_the_future",
    "read_sheet_rows",
)


@pytest.mark.parametrize("module", LANES, ids=LANE_IDS)
@pytest.mark.parametrize("name", SHARED_NAMES)
def test_every_lane_uses_the_one_shared_object_not_a_copy(module, name: str) -> None:
    """🔴 `is` ไม่ใช่ `==` — ทรงเดียวกับเทส `assert_target`/`TARGETS` ที่มีอยู่แล้ว

    พฤติกรรมที่ "เหมือนกันวันนี้" คือสิ่งที่ drift ได้เงียบ ๆ · ก่อนรอบนี้เส้นที่ 2
    กับเส้นที่ 3 มี `_parse_reviewed_at` **คนละตัว** ที่เขียนกฎเดียวกันคนละสำเนา —
    ตัวหนึ่งได้ด่านเวลาอนาคต อีกตัวไม่ได้ ก็จะไม่มีอะไรฟ้อง

    🔴 **ข้าม (ไม่ import มาเลย) ถือว่าผ่าน ไม่ใช่ fail** — คำถามของเทสนี้คือ "ถ้าเส้นนี้
    ใช้กฎข้อนี้ ต้องเป็น object เดียวกับ `_shared` ไม่ใช่สำเนา" ไม่ใช่ "ทุกเส้นต้อง import
    ครบทุกชื่อ" · ชื่อที่เส้นนั้นไม่มีวันใช้ (เช่น `sold_entry.py` ไม่มีใบงาน CSV เลย จึง
    ไม่มีวันเรียก `read_sheet_rows`) ไม่มีอะไรให้ drift และไม่มีอะไรให้จับ · ด่านกันก๊อป
    ตัวจริงคือ `test_no_lane_declares_its_own_version_of_a_shared_rule` (AST — ไม่ต้องมี
    import ก็ทำงานได้) (พบจาก code-critic รอบ 2 ของ INF-24 — M-d: `sold_entry.py`
    เคย import `read_sheet_rows` แบบไม่ใช้งานจริงพร้อม `# noqa: F401` เพียงเพื่อผ่านเทส
    นี้ — ลบทั้งคู่แล้ว)
    """
    if not hasattr(module, name):
        pytest.skip(
            f"{module.__name__} ไม่ได้ใช้ {name} — ด่านกันก๊อปคือ "
            "test_no_lane_declares_its_own_version_of_a_shared_rule"
        )
    assert getattr(module, name) is getattr(_shared, name)


@pytest.mark.parametrize("module", LANES, ids=LANE_IDS)
@pytest.mark.parametrize("name", SHARED_NAMES + ("_render_ahead",))
def test_no_lane_declares_its_own_version_of_a_shared_rule(module, name: str) -> None:
    """import ตัวเดียวกันมาแล้ว **แล้วประกาศทับ** ก็ยังผ่านเทส identity ไม่ได้ —
    แต่การประกาศไว้เฉย ๆ โดยไม่มีใครเรียกจะรอด · ตัวนี้ปิดช่องนั้นที่ระดับซอร์ส
    """
    declared = {
        node.name
        for node in ast.walk(_tree(module))
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
    }
    assert name not in declared


@pytest.mark.parametrize("module", LANES, ids=LANE_IDS)
def test_no_lane_builds_its_own_csv_reader(module) -> None:
    """🔴 BL-101 — `csv.DictReader(fh)` ที่ไม่มี `restkey` คือรูปเดิมของบั๊ก

    ค่าที่เกิน header จะไปกองใต้คีย์ `None` เป็น **list** แล้ว `.strip()` ระเบิดเป็น
    `AttributeError` ที่คนกรอกอ่านไม่ออก · การบังคับให้ทุกเส้นเข้าทาง
    `read_sheet_rows()` ทางเดียวแปลว่าไม่มีใคร "ลืม" `restkey` ได้อีก
    """
    calls = [
        ast.unparse(n)
        for n in ast.walk(_tree(module))
        if isinstance(n, ast.Call) and _callee_name(n) == "DictReader"
    ]
    assert calls == []


# --------------------------------------------------------------------------
# ADR-0010 D5 — ที่มาของ `reviewed_at` และตำแหน่งที่นาฬิกาโผล่ได้
# --------------------------------------------------------------------------

# ชื่อฟังก์ชันที่ถือว่า "อ่านนาฬิกา" — เทียบแบบ **substring** โดยตั้งใจ ให้ครอบ
# `datetime.now` · `datetime.utcnow` · `date.today` · และ wrapper ที่ตั้งชื่อเลี่ยง
# อย่าง `_now_iso()` / `get_now()` ด้วย
CLOCK_TOKENS = ("now", "today", "utcnow")
# ชื่อด่านที่เป็น **ที่เดียว** ที่รับเวลาปัจจุบันได้
CLOCK_SINK = "assert_not_in_the_future"


def _is_clock_call(node: ast.AST) -> bool:
    return isinstance(node, ast.Call) and any(
        tok in _callee_name(node).lower() for tok in CLOCK_TOKENS
    )


def _assert_attr_only_assigned_via_parse_reviewed_at(tree, attr_name: str) -> None:
    """ตรรกะร่วมของ `args.reviewed_at` (ADR-0010 D5) และ `args.sold_at`
    (ADR-0025 D4) — ทั้งคู่ต้องมาจาก `_parse_reviewed_at(<สิ่งที่คนพิมพ์>, ...)`
    เท่านั้น ห้ามเป็นนิพจน์เวลาปัจจุบันไม่ว่าจะทางไหน
    """
    assigned: list[ast.expr] = []
    for node in ast.walk(tree):
        targets: list[ast.expr] = []
        if isinstance(node, ast.Assign):
            targets = list(node.targets)
        elif isinstance(node, (ast.AnnAssign, ast.AugAssign)):
            targets = [node.target]
        else:
            continue
        if node.value is None:  # `x: T` ที่ไม่มีค่า
            continue
        for target in targets:
            if isinstance(target, ast.Attribute) and target.attr == attr_name:
                assigned.append(node.value)

    assert (
        assigned
    ), f"ไม่พบการ assign `args.{attr_name}` เลย — ด่าน parse หายไปหรือเปล่า"
    for value in assigned:
        rendered = ast.unparse(value)
        assert isinstance(value, ast.Call), rendered
        assert _callee_name(value) == "_parse_reviewed_at", rendered

    # ปิดช่องเขียนแบบ dynamic ที่การไล่ `ast.Assign` มองไม่เห็น
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and _callee_name(node) == "setattr":
            literals = [
                a.value
                for a in node.args
                if isinstance(a, ast.Constant) and isinstance(a.value, str)
            ]
            assert attr_name not in literals, ast.unparse(node)


@pytest.mark.parametrize("module", LANES, ids=LANE_IDS)
def test_reviewed_at_can_only_ever_be_the_value_the_human_typed(module) -> None:
    """🔴 **นี่คือกฎจริงของ ADR-0010 D5** — `args.reviewed_at` ต้องมาจาก
    `_parse_reviewed_at(<สิ่งที่คนพิมพ์>)` เท่านั้น ห้ามเป็นนิพจน์เวลาปัจจุบัน
    ไม่ว่าจะทางไหน (เวลาที่คนตัดสิน ≠ เวลาที่รันสคริปต์ · การเดาให้ = กรอกแทนคน)

    🔴 **ห้ามลบตัวนี้แล้วอ้างว่าเทสนาฬิกาข้างล่างครอบแทนได้** — ตัวนี้จับ "ค่ามาจากไหน"
    อีกตัวจับ "นาฬิกาไปโผล่ที่ไหนได้บ้าง" คนละคำถาม
    """
    _assert_attr_only_assigned_via_parse_reviewed_at(_tree(module), "reviewed_at")


def test_sold_at_can_only_ever_be_the_value_the_human_typed() -> None:
    """คู่แฝดของเทสข้างบนแต่สำหรับ `args.sold_at` (ADR-0025 D4) — มีแค่ `sold_entry.py`
    เท่านั้นที่มีแนวคิดนี้ จึงไม่ parametrize ข้าม `LANES` เหมือนตัวบน

    🔴 พบจาก `code-critic` รอบ 2 ของ INF-24 (H5 · MR-M1b) — `args.reviewed_at` มีด่านนี้
    มาตั้งแต่แรก แต่ `args.sold_at` ไม่มีคู่แฝดของมันเลยตอนที่ด่านนาฬิกาถูกผ่อนให้รับ
    ตัวแปร alias (H3 ของรอบ 1) ทำให้ mutation แบบ
    `args.sold_at = now if args.sold_at == "now" else _parse_reviewed_at(...)`
    ไม่มีอะไรจับ — เทสนี้ปิดช่องนั้น
    """
    _assert_attr_only_assigned_via_parse_reviewed_at(_tree(sold_mod), "sold_at")


@pytest.mark.parametrize("module", LANES, ids=LANE_IDS)
def test_the_clock_is_read_in_exactly_one_place_and_only_to_feed_the_gate(
    module,
) -> None:
    """🔴 นาฬิกาปรากฏได้ **ที่เดียวต่อเส้น**: เป็น argument ที่ส่งให้ด่านปฏิเสธ ไม่ว่าจะ
    ส่งตรง ๆ หรือผ่านตัวแปรที่ถูก assign จากค่านาฬิกาครั้งเดียวแล้วส่งต่อ (ผ่อนให้
    `code-critic` รอบ 1 ของ INF-24 — `sold_entry.py` ใช้ `now = datetime.now(tz)`
    ตัวเดียวป้อนทั้งด่าน `--sold-at` และ `--reviewed-at` ซึ่งเป็นรูปที่ยังตรงตาม
    เจตนาเดิมทุกประการ: นาฬิกายังถูกอ่าน**ครั้งเดียว**และใช้เพื่อ**ปฏิเสธ**เท่านั้น)

    อ่านนาฬิกาเพื่อ **ปฏิเสธ** เป็นคนละเรื่องกับอ่านเพื่อ **จ่ายค่า** — D5 ห้ามอย่างหลัง
    เท่านั้น · การบังคับให้นาฬิกาโผล่ได้ตำแหน่งเดียว (ไม่ว่าจะอ้างถึงกี่ครั้ง) ทำให้
    "อย่างหลัง" ไม่มีที่ยืน

    🔴 ต้องเป็น argument โดยตรง หรือผ่าน **ตัวแปรที่ผูกกับนาฬิกาตัวนี้ตัวเดียวเท่านั้น**
    (assign จาก clock call ตัวนี้เป๊ะครั้งเดียวในทั้งไฟล์ ไม่ reassign ที่ไหนอีก) —
    `now=datetime.now(tz) - timedelta(days=1)` ยังคงแดงเหมือนเดิม เพราะ argument
    ที่ป้อนไม่ใช่ทั้งสองแบบที่อนุญาต (เป็น `BinOp` ไม่ใช่ `Name`/clock call ตรง ๆ)
    """
    tree = _tree(module)
    clock_calls = [n for n in ast.walk(tree) if _is_clock_call(n)]
    rendered = [ast.unparse(n) for n in clock_calls]
    assert len(clock_calls) == 1, rendered
    clock_call = clock_calls[0]
    # นาฬิกาที่ไม่ระบุ timezone จะได้ค่า naive แล้วการเทียบใน `assert_not_in_the_future`
    # จะระเบิดเป็น TypeError ดิบตอนรัน — ที่นี่คือที่เดียวที่ดักได้ก่อนถึงมือคนใช้
    assert clock_call.args or clock_call.keywords, rendered[0]

    # ตัวแปรที่ assign มาจาก clock_call ตัวนี้ **เป๊ะ** และ assign แบบนี้แค่ครั้งเดียว
    # ในทั้งไฟล์ (ไม่ reassign จากที่อื่นอีก) — ถือเป็นชื่อสำรอง (alias) ของนาฬิกาตัว
    # เดียวกัน (sold_entry.py ใช้รูปนี้: `now = datetime.now(tz)` แล้วส่งต่อสองครั้ง)
    alias_names = {
        target.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Assign) and node.value is clock_call
        for target in node.targets
        if isinstance(target, ast.Name)
    }
    reassigned = {
        target.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Assign) and node.value is not clock_call
        for target in node.targets
        if isinstance(target, ast.Name) and target.id in alias_names
    }
    alias_names -= reassigned

    allowed: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and _callee_name(node) == CLOCK_SINK:
            for arg in (*node.args, *(kw.value for kw in node.keywords)):
                allowed.add(id(arg))
                if isinstance(arg, ast.Name) and arg.id in alias_names:
                    allowed.add(id(clock_call))

    assert {id(n) for n in clock_calls} <= allowed, rendered


def test_the_gate_itself_never_reads_the_clock() -> None:
    """`assert_not_in_the_future` เป็น pure function ที่รับ `now` เข้ามา — ถ้ามันอ่าน
    นาฬิกาเองเมื่อไหร่ เทสข้างบนจะนับเจอศูนย์ครั้งในทุกเส้นแล้วยัง "ผ่าน" ไม่ได้
    แต่กฎว่าโมดูลกลางต้องไม่มีนาฬิกาเลยควรมีตัวยืนของมันเอง
    """
    assert [n for n in ast.walk(_tree(_shared)) if _is_clock_call(n)] == []


# --------------------------------------------------------------------------
# ตัวอย่างในเอกสารต้องก๊อปแล้วรันไม่ผ่าน (BL-102)
# --------------------------------------------------------------------------

TIMESTAMP = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}")

SEED_DIR = Path(_shared.__file__).resolve().parent
# ทุกไฟล์ที่คนอ่านแล้วก๊อปคำสั่งไปรัน — สคริปต์ทุกตัวใน `scripts/seed/` + README
DOC_SOURCES = tuple(sorted(SEED_DIR.glob("*.py"))) + (SEED_DIR / "README.md",)


@pytest.mark.parametrize("path", DOC_SOURCES, ids=lambda p: p.name)
def test_no_example_anywhere_is_a_timestamp_someone_can_copy_and_run(path) -> None:
    """🔴 เกิดจริง 2026-08-08 — docstring เขียนตัวอย่าง `--reviewed-at` เป็นเวลาจริง
    ที่ก๊อปได้ ผู้ใช้ก๊อปมาทั้งบรรทัด แล้ว `reviewed_at` ของ **232 แถว** ลงเป็นเวลา
    ในอนาคต 3.5 ชั่วโมง ต้องตามแก้ด้วย SQL ตรง ๆ เพราะไม่มีเส้นทางสคริปต์ให้แก้

    ด่าน `assert_not_in_the_future` กันไม่ให้ค่าแบบนั้นลง DB ได้ แต่กันไม่ให้ **ตัวอย่าง
    ที่ก๊อปแล้วดูเหมือนใช้ได้** กลับมาอยู่ในเอกสารไม่ได้ — ตัวนี้ทำหน้าที่นั้น

    🔴 กวาดทั้งโฟลเดอร์ด้วย `glob` ไม่ใช่รายชื่อที่พิมพ์ไว้ — สคริปต์เส้นที่ 5 ที่ยัง
    ไม่มีใครเขียนจะถูกครอบทันทีที่ไฟล์ถูกสร้าง โดยไม่ต้องมีใครนึกได้ว่าต้องมาต่อรายชื่อ
    """
    found = TIMESTAMP.findall(path.read_text(encoding="utf-8"))
    assert not found, f"{path.name} มีเวลาจริงที่ก๊อปแล้วรันได้: {found}"


def test_every_script_that_accepts_reviewed_at_is_in_LANES() -> None:
    """closed-world ของ `LANES` เอง — ทุกด่านในไฟล์นี้ (identity · ห้ามสร้าง
    `DictReader` เอง · นาฬิกาอ่านที่เดียว · ที่มาของ `reviewed_at`) ครอบเฉพาะโมดูล
    ที่อยู่ในทูเพิลนั้น · สคริปต์ตัวถัดไปที่รับ `--reviewed-at` จะ **หลุดทุกด่าน
    เงียบ ๆ** ถ้าไม่มีใครนึกได้ว่าต้องมาต่อรายชื่อ

    🔴 นี่คือ failure mode เดียวกับที่ BL-101/BL-102 เกิดมา — เส้นที่ 4 มีด่าน
    เส้นอื่นไม่มี แล้วไม่มีอะไรฟ้อง · เทสนี้ฟ้อง
    """
    accepts = {
        path.name
        for path in SEED_DIR.glob("*.py")
        # _shared.py เอง **ไม่ใช่** เส้นที่รับ --reviewed-at เป็น CLI flag — มันคือ
        # โมดูลกลางที่นิยาม `_parse_reviewed_at(raw, *, flag="--reviewed-at")`
        # (M-c ของ code-critic รอบ 1 ของ INF-24 เพิ่ม default parameter ที่ literal
        # ตรงกับ pattern การสแกนนี้พอดี โดยบังเอิญ — ไม่ใช่เส้นใหม่ที่ควรถูกนับ)
        if path.name != "_shared.py"
        and '"--reviewed-at"' in path.read_text(encoding="utf-8")
    }
    covered = {f"{name}.py" for name in LANE_IDS}
    assert accepts == covered, (
        f"สคริปต์ที่รับ --reviewed-at แต่ไม่อยู่ใน LANES: {sorted(accepts - covered)} · "
        f"อยู่ใน LANES แต่ไม่รับแล้ว: {sorted(covered - accepts)}"
    )


def test_the_sweep_actually_covers_all_seven_lanes() -> None:
    """closed-world ของตัวกวาดเอง — `glob` ที่ชี้ผิดโฟลเดอร์จะได้ลิสต์ว่างแล้ว
    `parametrize` ที่ว่างเปล่าจะ **ไม่แดงเลยสักตัว** (เทสหายเงียบ ไม่ใช่เทสตก)

    เจ็ดเส้นทางเขียน `posters` ตาม `scripts/seed/README.md` §5 (ADR-0015 D1 ·
    ADR-0024 D2 — เส้นที่ 6 (`split_entry`) เพิ่มเข้ามา 2026-08-12 · ADR-0025 —
    เส้นที่ 7 (`sold_entry`) เพิ่มเข้ามา 2026-08-15) · `make_split_sheet.py` ไม่ได้
    อยู่ใน `LANES` (มันไม่รับ `--reviewed-at`) แต่ต้องอยู่ในตัวกวาดนี้เหมือนสคริปต์อื่น
    เพราะ `test_no_example_anywhere_is_a_timestamp_someone_can_copy_and_run` ครอบ
    ทุกไฟล์ `.py` ในโฟลเดอร์อยู่แล้วผ่าน `DOC_SOURCES` — ใส่ชื่อไว้ที่นี่เพื่อยืนยันว่า
    glob ไม่ได้พลาดมันไป
    """
    names = {p.name for p in DOC_SOURCES}
    assert {
        "apply_suggestions.py",
        "manual_entry.py",
        "reference_entry.py",
        "correction_entry.py",
        "seed_posters.py",
        "split_entry.py",
        "sold_entry.py",
        "make_split_sheet.py",
        "README.md",
    } <= names


# --------------------------------------------------------------------------
# `_parse_reviewed_at` — รูปแบบที่รับได้ (ย้ายมาจาก `test_apply_suggestions.py`)
# --------------------------------------------------------------------------


def test_reviewed_at_requires_timezone() -> None:
    """ไม่มี timezone = เครื่องต้องเดาแทนคนตรวจ ซึ่งเป็นการอ้างแทนคนแบบที่ D2 ห้าม"""
    with pytest.raises(PrecheckError, match="timezone"):
        _shared._parse_reviewed_at("2026-08-04T13:30:00")


def test_reviewed_at_rejects_non_iso() -> None:
    with pytest.raises(PrecheckError, match="ISO-8601"):
        _shared._parse_reviewed_at("4 ส.ค. 2026")


def test_reviewed_at_accepts_iso_with_offset() -> None:
    value = _shared._parse_reviewed_at("2026-08-04T13:30:00+07:00")
    assert value.tzinfo is not None


def test_the_format_hint_in_the_error_is_not_itself_copy_and_runnable() -> None:
    """ข้อความที่บอกรูปแบบคือ *ที่ที่คนกำลังมองหาค่าที่ใช้ได้พอดี* — ถ้ามันเป็นเวลาจริง
    มันคือกับดักตัวเดิมที่ย้ายจาก docstring มาอยู่ใน error message เฉย ๆ

    ค่าที่คนพิมพ์เองถูก echo กลับมาในข้อความด้วย ซึ่งไม่ใช่กับดัก (มันคือค่าที่เพิ่ง
    ถูกปฏิเสธไป) — ตัดออกก่อนตรวจ ที่เหลือคือข้อความที่ *เรา* เขียน
    """
    raw = "2026-08-04T13:30:00"
    with pytest.raises(PrecheckError) as exc:
        _shared._parse_reviewed_at(raw)
    ours = str(exc.value).replace(repr(raw), "")
    assert TIMESTAMP.search(ours) is None
    assert _shared.REVIEWED_AT_FORMAT_HINT in ours


# --------------------------------------------------------------------------
# `assert_not_in_the_future` — pure (ป้อน `now` เข้าไปเอง ไม่ freeze เวลา)
# --------------------------------------------------------------------------


def _at(text: str) -> datetime:
    return datetime.fromisoformat(text)


def test_a_time_in_the_past_passes() -> None:
    assert (
        assert_not_in_the_future(
            _at("2026-08-08T16:00:00+07:00"), now=_at("2026-08-08T16:29:00+07:00")
        )
        is None
    )


def test_exactly_now_passes_because_this_gate_is_not_strict() -> None:
    """คนที่เพิ่งตัดสินเสร็จแล้วรันทันทีคือการใช้งานปกติ — ปฏิเสธ `now` เป๊ะ ๆ
    จะทำให้ด่านนี้เป็นกับดักแทนที่จะเป็นตัวช่วย"""
    moment = _at("2026-08-08T16:29:00+07:00")
    assert assert_not_in_the_future(moment, now=moment) is None


def test_one_second_ahead_is_already_refused() -> None:
    with pytest.raises(PrecheckError, match="อนาคต"):
        assert_not_in_the_future(
            _at("2026-08-08T16:29:01+07:00"), now=_at("2026-08-08T16:29:00+07:00")
        )


def test_the_same_instant_written_in_two_timezones_is_not_in_the_future() -> None:
    """🔴 เทียบเป็น **instant** ไม่ใช่หน้าปัด — `20:00+07:00` กับ `13:00Z` คือเวลา
    เดียวกัน · ด่านที่ตัด tzinfo ทิ้งแล้วเทียบ naive จะปฏิเสธค่าที่ถูกต้องตรงนี้"""
    assert (
        assert_not_in_the_future(
            _at("2026-08-08T20:00:00+07:00"), now=_at("2026-08-08T13:00:00+00:00")
        )
        is None
    )


def test_a_future_instant_hiding_behind_a_smaller_wall_clock_is_still_refused() -> None:
    """ทิศตรงข้ามของเทสบน — `09:00Z` = `16:00+07:00` ซึ่งล้ำหน้า `15:00+07:00` อยู่
    หนึ่งชั่วโมง แต่ตัวเลขหน้าปัด (09 < 15) หลอกให้ด่านที่เทียบ naive ปล่อยผ่าน"""
    with pytest.raises(PrecheckError, match="อนาคต"):
        assert_not_in_the_future(
            _at("2026-08-08T09:00:00+00:00"), now=_at("2026-08-08T15:00:00+07:00")
        )


def test_the_message_says_how_far_ahead_so_a_timezone_typo_is_obvious() -> None:
    """ตัวเลขคือสิ่งที่ทำให้คนเดาสาเหตุถูก — เหตุการณ์จริง 2026-08-08 ล้ำหน้า
    **3 ชั่วโมง 31 นาที** ซึ่งอ่านแล้วเห็นทันทีว่าคือ `+07:00` ที่ก๊อปมา ไม่ใช่
    ค่าที่ตั้งใจพิมพ์"""
    with pytest.raises(PrecheckError) as exc:
        assert_not_in_the_future(
            _at("2026-08-08T20:00:00+07:00"), now=_at("2026-08-08T16:29:00+07:00")
        )
    text = str(exc.value)
    assert "3 ชั่วโมง" in text
    assert "31 นาที" in text


def test_the_current_time_is_shown_in_the_timezone_the_human_typed() -> None:
    """`now` ที่โผล่ในข้อความถูกแปลงเป็น timezone เดียวกับค่าที่กรอก คนจะได้เทียบ
    สองตัวเลขนี้ตรง ๆ ได้ — `09:29Z` ต้องแสดงเป็น `16:29+07:00`"""
    with pytest.raises(PrecheckError) as exc:
        assert_not_in_the_future(
            _at("2026-08-08T20:00:00+07:00"), now=_at("2026-08-08T09:29:00+00:00")
        )
    assert "2026-08-08T16:29:00+07:00" in str(exc.value)


# --------------------------------------------------------------------------
# ด่านต้องถูก **ต่อสายเข้า `main()` ของทุกเส้น** ไม่ใช่แค่มีฟังก์ชันอยู่เฉย ๆ
# --------------------------------------------------------------------------


def _argv(monkeypatch, module, *args: str) -> None:
    name = module.__name__.rsplit(".", 1)[-1] + ".py"
    monkeypatch.setattr(sys, "argv", [name, *args])


@pytest.mark.parametrize("module", SHEET_LANES, ids=SHEET_LANE_IDS)
def test_a_future_reviewed_at_is_refused_at_the_cli_before_anything_is_read(
    module, monkeypatch, tmp_path, capsys
) -> None:
    """`--file` ชี้ไปไฟล์ที่ไม่มีอยู่โดยตั้งใจ: ถ้าด่านถูกถอดออก `main()` จะเดินต่อไป
    จนตกที่ชั้นอ่านใบงานแล้ว **คืน 1 แทนที่จะ `SystemExit(2)`** → เทสแดง ·
    และการยืนยันว่า stderr ไม่มี "ไม่พบใบงาน" คือหลักฐานว่าหยุดก่อนถึงชั้นอ่านไฟล์

    🔴 ใช้ `SHEET_LANES` ไม่ใช่ `LANES` — เทสนี้พึ่ง `--file` ตรง ๆ ซึ่งมีแค่ห้าเส้นที่มี
    ใบงาน CSV เท่านั้น (`sold_entry.py` มีเทสเทียบเท่าของตัวเองที่ไม่พึ่ง `--file` ที่
    `tests/unit/test_sold_entry.py::test_main_rejects_future_sold_at`)
    """
    _argv(
        monkeypatch,
        module,
        "--commit",
        "--reviewed-by",
        "chanothai",
        "--reviewed-at",
        "3000-01-01T00:00:00+07:00",
        "--file",
        str(tmp_path / "ยังไม่มีไฟล์.csv"),
    )
    with pytest.raises(SystemExit) as exc:
        module.main()
    assert exc.value.code == 2
    err = capsys.readouterr().err
    assert re.search(r"อนาคต\s+\d", err), err
    assert "ไม่พบใบงาน" not in err


@pytest.mark.parametrize("module", SHEET_LANES, ids=SHEET_LANE_IDS)
def test_a_past_reviewed_at_walks_straight_through_the_gate(
    module, monkeypatch, tmp_path, capsys
) -> None:
    """ด้านที่ต้องไม่พัง — เวลาในอดีตกับนาฬิกา **จริง** ต้องผ่านด่านไปจนถึงชั้นอ่านไฟล์

    เทสตัวนี้เป็นตัวเดียวที่เดินผ่าน `datetime.now(...)` ของจริง จึงเป็นตัวเดียวที่จับ
    ได้ถ้านาฬิกาถูกอ่านแบบไม่มี timezone (naive `now` → `TypeError` ตอนเทียบ)

    🔴 ใช้ `SHEET_LANES` ไม่ใช่ `LANES` — เหตุผลเดียวกับเทสข้างบน
    """
    _argv(
        monkeypatch,
        module,
        "--commit",
        "--reviewed-by",
        "chanothai",
        "--reviewed-at",
        "2020-01-01T00:00:00+07:00",
        "--file",
        str(tmp_path / "ยังไม่มีไฟล์.csv"),
    )
    assert module.main() == 1  # ไม่ใช่ SystemExit(2) จาก argparse
    assert "ไม่พบใบงาน" in capsys.readouterr().err


# --------------------------------------------------------------------------
# BL-101 — ใบงานที่มี field เกิน header ต้องได้ข้อความที่คนแก้ต่อได้
# --------------------------------------------------------------------------

PID = uuid.UUID("11111111-1111-1111-1111-111111111111")

# (โมดูล, ฟังก์ชันอ่านใบงานของเส้นนั้น, คอลัมน์ของใบงาน, คอลัมน์ระบุตัวใบ, คอลัมน์ข้อความอิสระ)
# 🔴 คอลัมน์ระบุตัวใบไม่ได้ชื่อ `poster_uuid` ทุกเส้น — เส้นที่ 6 (`split_entry`) ใช้
# `parent_poster_uuid` เพราะแถวในใบงานนั้นระบุ "แถวพ่อ" ไม่ใช่ "แถวที่จะเขียน" ตรง ๆ
# (มันจะ INSERT แถวลูกใหม่ ไม่ใช่ UPDATE แถวที่ระบุ) — ต้องส่งชื่อคอลัมน์มาต่อพารามิเตอร์
# แทนการเดาว่าเป็น `poster_uuid` เสมอ
SHEETS = (
    (
        suggest_mod.read_review_sheet,
        suggest_mod.REVIEW_SHEET_COLUMNS,
        "poster_uuid",
        "evidence",
    ),
    (
        manual_mod.read_manual_sheet,
        manual_mod.MANUAL_SHEET_COLUMNS,
        "poster_uuid",
        "note",
    ),
    (
        reference_mod.read_sheet,
        reference_mod.REFERENCE_SHEET_COLUMNS,
        "poster_uuid",
        "reference_note",
    ),
    (
        correction_mod.read_sheet,
        correction_mod.CORRECTION_SHEET_COLUMNS,
        "poster_uuid",
        "condition_grade_reason",
    ),
    (
        split_mod.read_sheet,
        split_mod.SPLIT_SHEET_COLUMNS,
        "parent_poster_uuid",
        "reason",
    ),
)
SHEET_IDS = (
    "apply_suggestions",
    "manual_entry",
    "reference_entry",
    "correction_entry",
    "split_entry",
)


def _write(path: Path, columns, cells: list[str]) -> Path:
    path.write_text(",".join(columns) + "\n" + ",".join(cells) + "\n", encoding="utf-8")
    return path


def _cells(columns, id_column: str, free_text: str, value: str) -> list[str]:
    row = [""] * len(columns)
    row[columns.index(id_column)] = str(PID)
    row[columns.index(free_text)] = value
    return row


@pytest.mark.parametrize("read, columns, id_column, free_text", SHEETS, ids=SHEET_IDS)
def test_a_row_with_more_values_than_header_is_a_precheck_error(
    read, columns, id_column, free_text, tmp_path
) -> None:
    """🔴 BL-101 — เกิดจริงเมื่อช่องหมายเหตุมีจุลภาคแล้วไม่ได้ครอบด้วยอัญประกาศ

    ก่อนรอบนี้เส้นที่ 3 (และเส้นที่ 2 ซึ่งมีบั๊กคลาสเดียวกัน) โยน
    `AttributeError: 'list' object has no attribute 'strip'` ซึ่งคนกรอกอ่านไม่ออกเลยว่า
    ต้องไปแก้อะไร · fail-closed อยู่แล้ว (ไม่มีอะไรลง DB) ความเสียหายคือคนติดตาย
    """
    path = _write(
        tmp_path / "sheet.csv",
        columns,
        _cells(columns, id_column, free_text, "ไม่เจอ, เพราะเว็บไม่มีวาเรียนต์นี้"),
    )
    with pytest.raises(PrecheckError) as exc:
        read(path)
    text = str(exc.value)
    assert "มากกว่าจำนวนคอลัมน์" in text
    assert "บรรทัด 2" in text  # เลขบรรทัดจริงในไฟล์ ไม่ใช่ index ของแถว
    assert free_text in text  # ชื่อช่องที่น่าจะเป็นต้นเหตุ


@pytest.mark.parametrize("read, columns, id_column, free_text", SHEETS, ids=SHEET_IDS)
def test_the_same_comma_wrapped_in_quotes_is_accepted(
    read, columns, id_column, free_text, tmp_path
) -> None:
    """🔴 ด้านที่ต้องไม่พัง — ด่านใหม่ต้องปฏิเสธเฉพาะไฟล์ที่ *ผิดจริง*

    ถ้าเทสมีแต่ฝั่งปฏิเสธ ด่านที่ปฏิเสธทุกไฟล์ที่มีจุลภาคก็ยังเขียวทั้งชุด
    """
    text = "ไม่เจอ, เพราะเว็บไม่มีวาเรียนต์นี้"
    path = _write(
        tmp_path / "sheet.csv",
        columns,
        _cells(columns, id_column, free_text, f'"{text}"'),
    )
    (row,) = read(path)
    assert row[free_text] == text


@pytest.mark.parametrize("read, columns, id_column, free_text", SHEETS, ids=SHEET_IDS)
def test_a_missing_sheet_still_names_the_lanes_own_maker_script(
    read, columns, id_column, free_text, tmp_path
) -> None:
    """ข้อความ "ไม่พบใบงาน" ยังเป็นของแต่ละเส้น — คนละคำสั่งในการสร้างใบงานใหม่
    (นี่คือเหตุผลที่การเปิดไฟล์ไม่ได้ถูกยกไป `_shared` ทั้งก้อน)"""
    with pytest.raises(PrecheckError, match="ไม่พบใบงาน"):
        read(tmp_path / "ยังไม่มีไฟล์.csv")


# --------------------------------------------------------------------------
# G — จุดต่อของ `assert_target()` ใน `main()` ของ **ทุกเส้น** ‹INF-39 AC-5›
# --------------------------------------------------------------------------
#
# 🔴 **ทำไมต้องมีที่นี่ ทั้งที่บางเส้นมีเทสของตัวเองแล้ว** — รัน mutation จริงเมื่อ
# 2026-08-30 (ถอดการเรียก `assert_target()` ออกจาก `main()` ทีละเส้น แล้วรันเทสของเส้นนั้น):
#
#     correction_entry  → 8 failed   ✅ จับได้
#     split_entry       → 1 failed   ✅ จับได้
#     manual_entry      → 106 passed ❌ **ไม่มีอะไรฟ้อง**
#     reference_entry   →  71 passed ❌
#     sold_entry        →  14 passed ❌
#     photo_entry       →  35 passed ❌
#
# ⇒ **สี่ในหกเส้นถอดด่านออกได้เงียบ ๆ** ทั้งที่มันเป็นชั้นเดียวที่กันไม่ให้สคริปต์ที่เขียน
# `condition_grade`/`published_at`/`status` ยิงเข้า environment ผิดตัว (ADR-0010 D7 ·
# ADR-0015 D8 · A2-D2) · เทสพฤติกรรมเต็มรูปของแต่ละเส้นแพงและซ้ำกันหกรอบ — ที่นี่จึง
# ล็อก **สายไฟ** ด้วย AST ให้ครบทุกเส้นแทน (ทรงเดียวกับด่าน `args.reviewed_at` ข้างบน)
# และปล่อยให้เทสพฤติกรรมของ `correction_entry`/`split_entry` ทำหน้าที่พิสูจน์ว่า
# *ตัวด่านเอง* หยุดจริงก่อนเปิด session
#
# 🔴 **ข้อจำกัดที่รู้ตัว:** AST พิสูจน์ได้แค่ว่า *มีสายไฟ* ไม่ได้พิสูจน์ว่าค่าที่ส่งเข้าไป
# ถูกใช้ต่อจริง — mutation ที่ *คงการเรียกไว้แต่โยนผลทิ้ง* ยังต้องพึ่งเทสพฤติกรรม

TARGET_GUARD_LANES = (
    manual_mod,
    reference_mod,
    correction_mod,
    split_mod,
    sold_mod,
    photo_mod,
)
TARGET_GUARD_IDS = tuple(m.__name__.rsplit(".", 1)[-1] for m in TARGET_GUARD_LANES)


def _main_of(module) -> ast.FunctionDef:
    for node in ast.walk(_tree(module)):
        if isinstance(node, ast.FunctionDef) and node.name == "main":
            return node
    raise AssertionError(f"{module.__name__} ไม่มี main()")


@pytest.mark.parametrize("module", TARGET_GUARD_LANES, ids=TARGET_GUARD_IDS)
def test_main_of_every_lane_wires_assert_target_to_this_runs_values(module) -> None:
    """🔴 ตัวฆ่า mutation **ถอด `assert_target()` ออกจาก `main()`** — ครบทุกเส้น

    ล็อกสองอย่าง ไม่ใช่อย่างเดียว:
      1. `main()` เรียก `assert_target` จริง
      2. อาร์กิวเมนต์เป็น **ค่าของรอบนั้น** (`database_url`, `args.target`)
         ไม่ใช่ค่าคงที่ที่ผ่านด่านเสมอ — ข้อ 2 คือข้อที่ "พิสูจน์ว่าถูกเรียก" จับไม่ได้
    """
    calls = [
        node
        for node in ast.walk(_main_of(module))
        if isinstance(node, ast.Call) and _callee_name(node) == "assert_target"
    ]
    assert (
        len(calls) == 1
    ), f"{module.__name__}: เจอ assert_target {len(calls)} ครั้งใน main()"

    first, second = calls[0].args
    assert isinstance(first, ast.Name) and first.id == "database_url"
    assert isinstance(second, ast.Attribute) and second.attr == "target"
    assert isinstance(second.value, ast.Name) and second.value.id == "args"


def test_every_script_that_offers_target_is_in_TARGET_GUARD_LANES() -> None:
    """closed-world — เส้นใหม่ที่มี `--target` ต้องเข้ารายการนี้ **ก่อน** มีเทสของตัวเอง

    ‹ทรงเดียวกับ `test_every_script_that_accepts_reviewed_at_is_in_LANES`› ถ้าไม่มีข้อนี้
    เส้นที่เจ็ดจะเกิดขึ้นมาโดยไม่มีอะไรตรวจว่ามันต่อด่านปลายทางไว้หรือยัง
    """
    # ‹INF-39 · code-critic L-2› หาด้วย AST ไม่ใช่ substring — เดิมผูกกับอัญประกาศคู่
    # ⇒ เส้นที่เขียน `'--target'` หลุดด่านเงียบ ๆ และไฟล์ที่แค่ *พูดถึง* `"--target"`
    # ใน docstring ถูกนับเข้ามาผิด ๆ
    seed_dir = Path(_shared.__file__).parent

    def _declares_target(path: Path) -> bool:
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if (
                isinstance(node, ast.Call)
                and _callee_name(node) == "add_argument"
                and node.args
                and isinstance(node.args[0], ast.Constant)
                and node.args[0].value == "--target"
            ):
                return True
        return False

    with_target = {p.stem for p in sorted(seed_dir.glob("*.py")) if _declares_target(p)}
    # `apply_suggestions` มี `--target` เหมือนกันแต่เรียก `assert_target_database()`
    # (ชั้นแรกล้วน ๆ) เพราะเป็นเจ้าของด่านชั้นแรกเอง — ADR-0015 D8 เพิ่มชั้นที่สอง
    # ให้เฉพาะเส้นที่เขียนฟิลด์ซึ่งดันของขึ้นหน้าร้าน
    assert with_target - {"apply_suggestions"} == set(TARGET_GUARD_IDS)


# --------------------------------------------------------------------------
# H — ตัวอ่าน env โยน PrecheckError ได้แล้ว · main() ต้องจับ ‹INF-39 · critic M-1›
# --------------------------------------------------------------------------
#
# 🔴 ก่อน `ADR-0015` A2-D1 ตัวอ่าน `.env` **ไม่เคยโยนอะไรเลย** ทุกเส้นจึงเรียก
# `_load_env()` นอก `try/except` ได้อย่างปลอดภัย · พอ A2-D1 ทำให้มันปฏิเสธรูปที่ไม่รองรับ
# เส้นที่ยังไม่ครอบจะส่ง **traceback ดิบ** ให้ผู้รันแทนข้อความ precheck — ซึ่งเป็นกรณีที่
# **A2-D4 สั่งให้แยกออกมาเป็นข้อ (2) โดยเฉพาะ** (*"ไฟล์อ้างตัวแปรที่ขยายไม่ได้"*)
#
# ที่นี่ล็อก **สายไฟ** ให้ครบทุกเส้นด้วย AST — เทสพฤติกรรมเต็มรูปอยู่ที่
# `test_env_file_expansion.py::test_main_reports_an_unusable_env_file_as_precheck`

ENV_LOADING_LANES = TARGET_GUARD_LANES + (suggest_mod, seed_mod)
ENV_LOADING_IDS = tuple(m.__name__.rsplit(".", 1)[-1] for m in ENV_LOADING_LANES)


@pytest.mark.parametrize("module", ENV_LOADING_LANES, ids=ENV_LOADING_IDS)
def test_main_catches_precheck_errors_from_loading_the_env_file(module) -> None:
    """การเรียก `_load_env()` ใน `main()` ต้องอยู่ใน `try` ที่จับ `PrecheckError`"""
    main = _main_of(module)
    guarded = [
        node
        for node in ast.walk(main)
        if isinstance(node, ast.Try)
        and any(
            isinstance(c, ast.Call)
            and _callee_name(c) in {"_load_env", "_load_dev_env"}
            for c in ast.walk(node.body[0])
            if isinstance(c, ast.Call)
        )
        and any(
            isinstance(h.type, ast.Name) and h.type.id == "PrecheckError"
            for h in node.handlers
        )
    ]
    assert (
        guarded
    ), f"{module.__name__}: _load_env() ไม่ได้อยู่ใน try/except PrecheckError"
