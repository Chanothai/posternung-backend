"""แตกแถวพ่อที่แทนของหลายชิ้นออกเป็นแถวลูกใหม่ — ADR-0024 (INF-22)

    ./venv/bin/python scripts/seed/make_split_sheet.py       # 1. สร้างใบงาน
    # 2. หยิบใบจริงขึ้นมา แล้วกรอก condition_grade / price / reason ของ**ชิ้น**นั้น
    ./venv/bin/python scripts/seed/split_entry.py                        # 3. dry-run (default)
    ./venv/bin/python scripts/seed/split_entry.py --commit \
        --reviewed-by <ชื่อคุณ> \
        --reviewed-at <เวลาที่คุณตัดสิน ISO-8601 พร้อม timezone>

🔴 **ค่าตัวอย่างข้างบนเป็น placeholder ที่ก๊อปทั้งบรรทัดแล้วรันไม่ผ่านโดยตั้งใจ** —
ดูเหตุผล (232 แถวลงเวลาอนาคตเมื่อ 2026-08-08) ที่ docstring ของ `correction_entry.py`
`assert_not_in_the_future()` ปฏิเสธค่าที่อยู่ในอนาคตตั้งแต่ `main()` เหมือนอีกสี่เส้น

## นี่คือ "เส้นที่ 6" และมันต่างจากทุกเส้นก่อนหน้าตรงจุดเดียวที่สำคัญที่สุด

ห้าเส้นก่อนหน้า (ADR-0015 D1 · ADR-0010 A-D2) ล้วน **UPDATE แถวที่มีอยู่แล้ว** —
เติมช่องว่างหรือทับค่าเดิม แต่ไม่เคย INSERT แถวใหม่ (เว้น `seed_posters.py` ที่ insert
จาก CSV ต้นทาง) เส้นนี้ **INSERT แถวลูกใหม่ทั้งแถว** จากการตัดสินใจของคนว่า "แถวพ่อ
แทนของมากกว่าหนึ่งชิ้น ต้องแยกชิ้นนี้ออกมาเป็นแถวของตัวเอง" (ADR-0019 D1/D2/D8)

**ผลที่ตามมา — ไม่มีคอนเซปต์ "ค่าเดิม/ทับค่าเดิม" เลยในไฟล์นี้**: ไม่มี `before`/`after`
ไม่มีโหมด `--allow-overwrite` ไม่มี `_report_counts()` ที่เทียบ `count(<column>)` ก่อน/หลัง
— สิ่งที่มีคือ "จะสร้างแถวใหม่กี่แถว" ล้วนๆ

## แถวพ่อ — ห้ามแตะเด็ดขาด ไม่ใช่แค่ในทางปฏิบัติ

🔴 **ไม่มีคำสั่ง UPDATE บน `posters` เลยแม้แต่บรรทัดเดียวในไฟล์นี้** — ทั้ง `price` ·
`status` · `published_at` · `needs_review` · `condition_grade` ของแถวพ่อ **ห้ามถูก
แตะทุกกรณี** โดยเฉพาะ `price` ซึ่ง ADR-0019 **D11 ข้อ 3** สั่งห้ามแก้ย้อนเพราะระบบไม่มี
ประวัติราคา (ห้ามแม้แต่*อ่าน*ไปคำนวณอะไรก็ห้าม ไม่ใช่แค่ห้ามเขียน)

**ลำดับบังคับ (ADR-0024 D3): แตกลูกก่อน → แก้ `is_unique` ของพ่อทีหลังด้วยเส้นที่ 5**
(`correction_entry.py`) เส้นนี้จึง**ไม่เขียน `is_unique` ของใครเลย** ทั้งพ่อและลูก —
ของแถวลูกได้มาจาก `server_default = true` ของคอลัมน์ (ไม่ต้อง set ตอน INSERT)

## แถวลูกได้อะไรมาบ้าง (ADR-0024 D4 · OD-2)

| กลุ่ม | ฟิลด์ | ที่มา |
|---|---|---|
| ของ **ชิ้น** | `condition_grade` · `price` | ใบงานนี้ — คนกรอกพร้อมกันในรอบเดียว (D11 ข้อ 2) |
| คัดจากพ่อ | `title` | เพราะยังเป็นหนังเรื่องเดียวกัน |
| ปล่อย `NULL` | `tmdb_id` · `year` · `poster_type` · `studio` · `era_decade` · `size` · `release_date*` · `copyright_year` · ทุกฟิลด์ระดับงานพิมพ์อื่น | **OD-2 เลือก (ก)** — ไม่มีเครื่องเขียนค่าที่ไม่มีคนยืนยัน (ADR-0009 D6) ให้เส้นที่ 3 เติมทีหลัง |
| ปล่อยให้ DB จัดการ | `is_unique` (→`true`) · `status` (→`available`) · `needs_review` (→`true`) · `is_authenticated` (→`false`) | server_default — **ห้าม set ค่าเหล่านี้เองใน INSERT** |

`published_at` ไม่ถูกแตะเลย (`NULL` เพราะไม่มี server_default) — แถวลูกไม่มีรูปเลย
ตอนสร้าง จึงยังไม่ผ่านด่าน BR-06 ของเส้นที่ 3 (`manual_entry.py`) อยู่แล้ว (D3 §ผลที่
ต้องยอมรับพร้อมกัน)

## ใบไหนถูกข้าม ใบไหนทำทั้งไฟล์พัง

🔴 **แก้ 2026-08-15 (ADR-0024 A-D5 · A-D6 · INF-25)** — taxonomy ข้างล่างเปลี่ยนสองจุด
จากเดิม: (1) มีคอลัมน์ใหม่ `piece_no` ที่เครื่องเติม (ไม่ใช่คนกรอก) ต้องผ่านรูปแบบเมื่อ
สามช่องของคนกรอกครบ (2) **ชนคีย์กันรันซ้ำไม่ปฏิเสธทั้งไฟล์อีกต่อไป** — ข้ามเฉพาะแถวแล้ว
รายงานดัง (เดิม `BLOCKED_ALREADY_SPLIT` ปฏิเสธทั้งไฟล์ — A-D6 หักล้างแล้ว)

**ทั้งไฟล์ถูกปฏิเสธ (fail-closed — เป็นปัญหาที่ตัวไฟล์ ไม่ต้องมี DB ถึงจะรู้):**
`parent_poster_uuid` ไม่ใช่ UUID · `parent_poster_uuid` ซ้ำในไฟล์เดียวกัน (รันเครื่องมือ
นี้ใหม่ทีละรอบถ้าต้องการแตกมากกว่าหนึ่งชิ้นจากใบเดียวกัน — ดู `parse_rows()`) ·
`condition_grade`/`price`/`reason` กรอกมาไม่ครบทั้งสามช่องพร้อมกัน · `condition_grade`
นอก enum หรือตัวพิมพ์ไม่ตรง · `price` ไม่ใช่ตัวเลข/ติดลบ/ทศนิยมเกิน 2 ตำแหน่ง ·
`piece_no` ไม่ใช่จำนวนเต็ม ≥ 2 **เมื่อสามช่องของคนกรอกครบแล้ว** (แถวที่ว่างทั้งสามช่อง
ยังเป็น `SKIP_BLANK` ปกติ ไม่บังคับให้ `piece_no` ถูกด้วย — ใบงานที่ทำไปครึ่งเดียวไม่ควร
พังทั้งไฟล์เพราะช่องที่เครื่องเติมของแถวที่ยังไม่ได้แตะเลย) · ไม่พบ `manual-entry.csv`
หรือ header ไม่มีคอลัมน์ `count_actual` (ใบงานรุ่นเก่าก่อน ADR-0019 A-D2)

**ข้ามเฉพาะแถว พร้อมรายงาน (ต้องมี DB/ไฟล์อื่นสด ๆ ถึงจะรู้ — ไม่ใช่ปัญหาที่ตัวไฟล์):**
ทั้งสามช่องว่าง (ยังไม่ได้กรอก — สถานะปกติ) · ไม่มีแถวพ่อนี้ใน DB · แถวพ่อไม่ใช่
`is_unique = false` แล้ว (มีคนแก้ผ่านเส้นที่ 5 ไปแล้วระหว่างที่ใบงานนี้ยังค้างอยู่) ·
พ่อยังไม่มี `condition_grade` (AC-5 — กันกรอบไฟของ BL-82 หลุดเข้ามาทางที่ไม่ใช่
`make_split_sheet.py`) · **`piece_no` ที่กรอกมาชนกับที่มีอยู่แล้วในฐาน (AC-4 · A-D6) —
แถวนั้นไม่ถูกสร้าง ต่างจากรูปแบบผิดตรงที่นี่เป็นสถานะปกติของการรันไฟล์เดิมซ้ำ** ·
ยังไม่มีผลนับใบจริง (`count_actual` ว่าง/ไม่มีแถวของพ่อนี้ใน `manual-entry.csv`) ·
`piece_no` เกินผลนับ (`piece_no > count_actual` — AC-6)

## สิ่งที่สคริปต์นี้ **ไม่** ทำ

- ❌ **ไม่เขียน `is_unique` เลยสักบรรทัด** ทั้งพ่อและลูก (D3) — มีเทสระดับซอร์ส (AST)
  ล็อกว่าไม่มี `ast.Attribute` ไหนชื่อ `is_unique` ในไฟล์นี้เลย
- ❌ **ไม่มี UPDATE บน `posters` เลยแม้แต่บรรทัดเดียว** — มีเทส AST ล็อกว่าไม่มี
  `ast.Call` ไหนเป็น `update(Poster...)` หรือ `session.execute(update(...))`
- ❌ **ไม่แตะ `price`/`status`/`published_at`/`needs_review`/`condition_grade` ของ
  แถวพ่อ** — อ่านแถวพ่อได้แค่เพื่อคัด `title` และเช็ค `is_unique` เท่านั้น
- ❌ **ไม่คัดฟิลด์ระดับงานพิมพ์จากพ่อ** (`tmdb_id`/`year`/`poster_type`/`studio`/
  `era_decade`/`size`/`release_date*`) — OD-2 ปิดที่ (ก): ปล่อย `NULL` ให้เส้นที่ 3
"""

from __future__ import annotations

import argparse
import os
import sys
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from enum import Enum
from functools import lru_cache
from pathlib import Path
from typing import Any

SEED_DIR = Path(__file__).resolve().parent
REPO_ROOT = SEED_DIR.parents[1]
sys.path.insert(0, str(REPO_ROOT))

from scripts.seed._shared import (  # noqa: E402
    PrecheckError,
    _parse_reviewed_at,
    assert_not_in_the_future,
    read_sheet_rows,
)
from scripts.seed.apply_suggestions import _load_env  # noqa: E402
from scripts.seed.correction_entry import DEFAULT_CORRECTION_CSV  # noqa: E402

# 🔴 import **object เดียวกัน ไม่ก๊อป** — `_enum_parser(..., exact_case=True)` คือด่าน
# ที่ทำให้ `Fine` ไม่ถูกแปลงเป็น `fine` เงียบ ๆ (BR-05 — ลูกค้าใช้ตัดสินใจซื้อ) ·
# `assert_target`/`TARGETS`/`SIT_ENV_FILE` เป็นทูเพิล/ฟังก์ชันเดียวกับทุกเส้นที่มี
# `--target` (มีเทส identity ล็อกที่ tests/unit/test_seed_lane_shared_rules.py) ·
# `load_count_actual_by_poster` — ด่านผลนับของ AC-6 (ADR-0024 A-D5) ใช้ parser เดียวกับ
# เส้นที่ 3 เป๊ะ ไม่สร้าง reader/parser ของตัวเอง (ย้ายมาบ้านของ `manual_entry.py`
# 2026-08-16 · INF-29 ขั้นที่ 1 — เดิมชื่อ `_load_counts()` อยู่ที่นี่)
from scripts.seed.manual_entry import (  # noqa: E402
    DEFAULT_MANUAL_CSV,
    SIT_ENV_FILE,
    TARGETS,
    FieldSpec,
    _enum_parser,
    assert_target,
    load_count_actual_by_poster,
)
from scripts.seed.reference_entry import DEFAULT_REFERENCE_CSV  # noqa: E402

DEFAULT_SPLIT_CSV = SEED_DIR / "split-entry.csv"

# คอลัมน์ของใบงาน — make_split_sheet.py import ไปใช้ ไม่ประกาศซ้ำสองที่ · `piece_no`
# เพิ่มเข้ามา 2026-08-15 (ADR-0024 A-D5 · INF-25) — อยู่กลุ่มเดียวกับ parent_title/
# parent_image_url เพราะเป็นช่องที่ *เครื่อง* เติม ไม่ใช่ช่องที่คนกรอก (ดู HUMAN_COLUMNS)
SPLIT_SHEET_COLUMNS = (
    "parent_poster_uuid",
    "parent_title",
    "parent_image_url",
    "piece_no",
    "condition_grade",
    "price",
    "reason",
)
# คอลัมน์ที่สคริปต์นี้ *ใช้จริง* — parent_title/parent_image_url เป็นข้อมูลให้คนอ่าน
# ตอนกรอก ขาดได้ไม่เป็นไร (แต่ generator ใส่มาให้เสมอ) — ทรงเดียวกับ correction_entry.py
REQUIRED_COLUMNS = (
    "parent_poster_uuid",
    "piece_no",
    "condition_grade",
    "price",
    "reason",
)
# ช่องที่คนกรอก — ต้องมาครบทั้งสามพร้อมกันเสมอ (ไม่มีแนวคิด "เติมทีหลัง" แบบเส้นที่ 3
# เพราะนี่คือ INSERT ครั้งเดียวจบ ไม่ใช่ UPDATE ที่ทยอยเติมได้) 🔴 `piece_no` **ไม่อยู่ใน
# ชุดนี้โดยตั้งใจ** — เป็นช่องที่เครื่อง (`make_split_sheet.py`) เติมให้จาก
# max(piece_no)+1 ต่อพ่อ คนไม่ต้องพิมพ์เลขชิ้นเอง (ADR-0024 A-D5 §ใครเติม)
HUMAN_COLUMNS = ("condition_grade", "price", "reason")

# เพดานของคอลัมน์ posters.price (Numeric(12, 2))
PRICE_MAX = Decimal("9999999999.99")
# piece_no เริ่มที่ 2 เสมอ — แถวพ่อเองคือชิ้นที่ 1 (ADR-0019 D1) · ตรงกับ
# ck_poster_splits_piece_no_min ที่ระดับ DB
PIECE_NO_MIN = 2


# --------------------------------------------------------------------------
# นิยามฟิลด์ + การตรวจรูปแบบ (pure — ไม่แตะ DB)
# --------------------------------------------------------------------------


def _parse_price(raw: str) -> Decimal:
    """ราคาต่อ**ชิ้น** ของแถวลูก — ADR-0019 D11 ข้อ 2 (กรอกพร้อมเกรดในรอบเดียว)

    🔴 **ไม่เกี่ยวกับราคาของแถวพ่อเลย** — เส้นนี้ไม่อ่าน `price` ของพ่อไปคำนวณอะไร
    ทั้งสิ้น (D11 ข้อ 3 ห้ามแตะราคาเดิม) ค่านี้เป็นราคาใหม่ของชิ้นใหม่ล้วน ๆ

    กฎเดียวกับคอลัมน์ `posters.price` (`Numeric(12, 2)` + `ck_posters_price_non_negative`):
    ไม่ติดลบ · ทศนิยมไม่เกิน 2 ตำแหน่ง (ปล่อยผ่านแล้ว PostgreSQL จะปัดเงียบ ๆ) ·
    ไม่เกินเพดานของคอลัมน์
    """
    try:
        value = Decimal(raw)
    except InvalidOperation:
        raise ValueError(f"{raw!r} ไม่ใช่ตัวเลข") from None
    if not value.is_finite():
        raise ValueError(f"{raw!r} ไม่ใช่ตัวเลขที่ใช้ได้")
    if value < 0:
        raise ValueError(f"{value} ติดลบ — ck_posters_price_non_negative ไม่รับ")
    if value > PRICE_MAX:
        raise ValueError(f"{value} เกินเพดานของคอลัมน์ posters.price (Numeric(12,2))")
    if -value.as_tuple().exponent > 2:
        raise ValueError(f"{value} มีทศนิยมเกิน 2 ตำแหน่ง")
    return value


def _parse_piece_no(raw: str) -> int:
    """`piece_no` — "ชิ้นที่เท่าไหร่ของพ่อคนนี้" (ADR-0024 A-D5)

    🔴 **ช่องที่เครื่องเติม ไม่ใช่ช่องที่คนกรอก** (ไม่อยู่ใน `HUMAN_COLUMNS`) แต่ยังต้อง
    ผ่านด่านรูปแบบเหมือนช่องอื่นเมื่อแถวนั้นถูกกรอกจริง (สามช่องของคนครบแล้ว) — คนแก้เลข
    นี้ด้วยมือได้เสมอ (เช่นรวมสองใบงานเข้าด้วยกัน) จึงต้องตรวจรูปแบบไม่ต่างจากช่องอื่น

    ไม่ใช่ตัวเลข หรือ < 2 → ผิดรูปแบบ (ปฏิเสธทั้งไฟล์ ทรงเดียวกับ `_parse_price`) —
    ต่างจาก "ชนกับเลขที่มีอยู่แล้ว" ซึ่งเป็นด่านที่ต้องรู้สถานะ DB สด ๆ อยู่ใน
    `plan_writes()` (`SKIP_PIECE_TAKEN`) ไม่ใช่ที่นี่
    """
    try:
        value = int(raw)
    except ValueError:
        raise ValueError(f"{raw!r} ไม่ใช่จำนวนเต็ม") from None
    if value < PIECE_NO_MIN:
        raise ValueError(
            f"{value} ต้อง >= {PIECE_NO_MIN} — แถวพ่อเองคือชิ้นที่ 1 เสมอ (ADR-0019 D1)"
        )
    return value


@lru_cache(maxsize=1)
def field_specs() -> dict[str, FieldSpec]:
    """นิยามของสองฟิลด์ที่คนกรอกเป็นค่า (ไม่รวม `reason` ซึ่งเป็น free text ล้วน)

    import `app.models.enums` **ข้างในฟังก์ชัน** ด้วยเหตุผลเดียวกับ
    `manual_entry.field_specs()` เป๊ะ — ต้อง import ได้ก่อน `_load_env()` ถูกเรียก
    """
    from app.models.enums import PosterCondition

    return {
        "condition_grade": FieldSpec(
            name="condition_grade",
            # 🔴 exact_case — ฟิลด์นี้ลูกค้าใช้ตัดสินใจซื้อ (BR-05) เหตุผลเต็มอยู่ที่
            # docstring ของ `_enum_parser()` ห้ามเขียนซ้ำที่นี่
            parse=_enum_parser(PosterCondition, exact_case=True),
            hint=(
                "เกรดของ*ชิ้นนี้* · เรียงดี→แย่: "
                + " > ".join(m.value for m in PosterCondition)
                + " · ตัวพิมพ์เล็กทั้งหมด ต้องตรงเป๊ะ"
            ),
        ),
        "price": FieldSpec(
            name="price",
            parse=_parse_price,
            hint="ราคาของ*ชิ้นนี้* (บาท) ทศนิยมได้ไม่เกิน 2 ตำแหน่ง ห้ามติดลบ",
        ),
    }


@dataclass(frozen=True)
class SplitPayload:
    """ค่าของแถวที่พร้อมเขียน — มีครบทั้งหมดหรือไม่มีเลย (ดู `parse_rows()`)

    `condition_grade` เป็น `PosterCondition` แต่ประกาศ type แบบ string เพราะไฟล์นี้
    เปิด `from __future__ import annotations` (annotation ไม่ถูก evaluate ตอน import)
    — import จริงเกิดข้างใน `field_specs()` เท่านั้น (เหตุผลเดียวกับ manual_entry.py)

    `piece_no` **มาจากไฟล์เท่านั้น** (เครื่อง `make_split_sheet.py` เติมให้ตอนสร้าง
    ใบงาน) — `run()` ต้องเขียนค่านี้ลง `PosterSplit.piece_no` ตรง ๆ ห้ามคำนวณใหม่
    (ADR-0024 A-D5 §ใครเติม)
    """

    condition_grade: "PosterCondition"  # noqa: F821 - forward ref, ดู docstring
    price: Decimal
    reason: str
    piece_no: int


@dataclass(frozen=True)
class SplitRow:
    """หนึ่งแถวของใบงานที่ผ่านการตรวจรูปแบบแล้ว

    `payload is None` = ยังไม่ได้กรอก (สถานะปกติของใบงานที่ทำไปครึ่งเดียว) —
    ต่างจากเส้นอื่นตรงที่ไม่มีแนวคิด "ค่าเดิม" เลย จึงไม่ต้องมีฟิลด์ `values`/`reasons`
    แยกกันแบบ `CorrectionRow`
    """

    lineno: int
    parent_poster_uuid: uuid.UUID
    payload: SplitPayload | None


def assert_own_sheet(path: Path) -> None:
    """ปฏิเสธใบงานของเส้นอื่น — pure เพื่อให้ test ครอบได้โดยไม่ต้องมีไฟล์จริง

    🔴 `poster_splits.source` เก็บ **ชื่อไฟล์ใบงาน** ซึ่งเป็นสิ่งเดียวที่แยกได้ว่า
    แถวไหนมาจากรอบไหน (หลักเดียวกับ ADR-0014 D28) — ส่งไฟล์ของเส้นอื่นมาแล้ว
    ร่องรอยจะชี้ผิดรอบทันทีโดยไม่มีอะไรฟ้อง
    """
    others = {
        DEFAULT_MANUAL_CSV.name: ("เส้นที่ 3", "manual_entry.py"),
        DEFAULT_REFERENCE_CSV.name: ("เส้นที่ 4", "reference_entry.py"),
        DEFAULT_CORRECTION_CSV.name: ("เส้นที่ 5", "correction_entry.py"),
    }
    hit = others.get(path.name)
    if hit is None:
        return
    lane, script = hit
    raise PrecheckError(
        f"--file ชี้ไปที่ {path.name} ซึ่งเป็นใบงานของ **{lane}** ({script})\n"
        "สคริปต์นี้ต้องใช้ใบงานของตัวเอง เพราะ poster_splits.source เก็บชื่อไฟล์ไว้เป็น "
        "ตัวแยกว่าแถวไหนมาจากรอบไหน\n"
        "สร้างด้วย `./venv/bin/python scripts/seed/make_split_sheet.py`"
    )


def read_sheet(path: Path) -> list[dict[str, str]]:
    if not path.is_file():
        raise PrecheckError(
            f"ไม่พบใบงาน {path}\n"
            "สร้างด้วย `./venv/bin/python scripts/seed/make_split_sheet.py` ก่อน "
            "แล้วให้คนหยิบใบจริงขึ้นมากรอกเกรด/ราคา/เหตุผลของชิ้นที่จะแตกออกมา"
        )
    return read_sheet_rows(
        path,
        required_columns=REQUIRED_COLUMNS,
        sheet_columns=SPLIT_SHEET_COLUMNS,
        maker_script="make_split_sheet.py",
        free_text_columns=("reason",),
    )


def parse_rows(raw_rows: list[dict[str, str]]) -> list[SplitRow]:
    """ตรวจรูปแบบทุกแถวแล้วคืน `SplitRow` — เจอผิดแม้แถวเดียว raise ทั้งไฟล์

    🔴 **pure ล้วน ไม่ต้องมี DB** โดยตั้งใจ — ทุกด่านของฟังก์ชันนี้ตรวจได้จากตัวไฟล์
    อย่างเดียว (รูปแบบผิด) ต่างจากด่านที่ต้องรู้สถานะ DB สด ๆ (พ่อยังมีอยู่ไหม ·
    ยัง `is_unique=false` อยู่ไหม) ซึ่งอยู่ใน `plan_writes()` และข้ามเฉพาะแถว
    ไม่ทำทั้งไฟล์พัง (ทรงเดียวกับ `SKIP_NOT_FOUND` ของเส้นที่ 5)
    """
    specs = field_specs()
    rows: list[SplitRow] = []
    errors: list[str] = []
    seen: set[str] = set()

    for lineno, raw in enumerate(raw_rows, start=2):  # +1 header, +1 นับจาก 1
        prefix = f"บรรทัด {lineno}"

        try:
            parent_uuid = uuid.UUID(raw["parent_poster_uuid"])
        except ValueError:
            errors.append(
                f"{prefix}: parent_poster_uuid {raw['parent_poster_uuid']!r} ไม่ใช่ UUID"
            )
            continue

        if str(parent_uuid) in seen:
            errors.append(
                f"{prefix}: parent_poster_uuid ซ้ำกับแถวก่อนหน้า — เส้นนี้ INSERT "
                "แถวใหม่ต่อแถว ถ้าต้องการแตกมากกว่าหนึ่งชิ้นจากใบเดียวกัน ให้รันเครื่องมือ "
                "นี้ใหม่ทีละรอบ (สร้างใบงานใหม่ · แตกทีละชิ้น) ไม่ใช่ใส่สองแถวในใบเดียว"
            )
            continue
        seen.add(str(parent_uuid))

        texts = {name: raw.get(name, "") for name in HUMAN_COLUMNS}
        filled = [name for name, text in texts.items() if text]

        if not filled:
            # ยังไม่ได้กรอกเลย — สถานะปกติของใบงานที่ทำไปครึ่งเดียว · `piece_no` ของ
            # แถวนี้ไม่ต้องถูกด้วยเช่นกัน (แถวว่างไม่มีอะไรให้เขียน จึงไม่ต้องตรวจช่อง
            # ที่เครื่องเติมให้เลย — บังคับก็มีแต่จะทำให้ใบงานที่ทำไปครึ่งเดียวพังทั้งไฟล์
            # โดยไม่มีประโยชน์อะไรเพิ่ม)
            rows.append(
                SplitRow(lineno=lineno, parent_poster_uuid=parent_uuid, payload=None)
            )
            continue
        if len(filled) < len(HUMAN_COLUMNS):
            missing = [name for name in HUMAN_COLUMNS if name not in filled]
            errors.append(
                f"{prefix}: กรอกมาไม่ครบ — {', '.join(missing)} ยังว่าง "
                f"(กรอกมาแล้ว {filled}) · เส้นนี้ INSERT แถวใหม่ ไม่มีแนวคิด "
                "'เติมทีหลัง' แบบเส้นที่ 3 — condition_grade/price/reason ต้องมา "
                "ครบทั้งสามพร้อมกันเสมอ (ADR-0019 D11 ข้อ 2)"
            )
            continue

        row_failed = False
        try:
            grade = specs["condition_grade"].parse(texts["condition_grade"])
        except ValueError as exc:
            errors.append(f"{prefix}: condition_grade — {exc}")
            row_failed = True
        try:
            price = specs["price"].parse(texts["price"])
        except ValueError as exc:
            errors.append(f"{prefix}: price — {exc}")
            row_failed = True
        try:
            piece_no = _parse_piece_no(raw.get("piece_no", ""))
        except ValueError as exc:
            errors.append(f"{prefix}: piece_no — {exc}")
            row_failed = True

        if row_failed:
            continue

        rows.append(
            SplitRow(
                lineno=lineno,
                parent_poster_uuid=parent_uuid,
                payload=SplitPayload(
                    condition_grade=grade,
                    price=price,
                    reason=texts["reason"],
                    piece_no=piece_no,
                ),
            )
        )

    if errors:
        raise PrecheckError(
            f"ใบงานไม่ผ่านการตรวจรูปแบบ {len(errors)} จุด — ไม่เขียนอะไรเลยทั้งไฟล์:\n  "
            + "\n  ".join(errors)
        )
    return rows


# --------------------------------------------------------------------------
# วางแผนการเขียน (pure — รับสถานะปัจจุบันเข้ามา ไม่ query เอง)
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class ParentState:
    """สถานะปัจจุบันของแถวพ่อ — ทุกอย่างที่ `plan_writes()` ต้องรู้ (อ่านอย่างเดียว)

    `condition_grade` เพิ่มเข้ามา 2026-08-15 (ADR-0024 A-D5 · INF-25 · AC-5) — ด่าน
    "พ่อต้องมีเกรดแล้ว" ต้องอยู่ที่ชั้น applier เอง ไม่ใช่เชื่อใจว่าใบงานมาจาก
    `make_split_sheet.py` เท่านั้น (กันกรอบไฟของ BL-82 หลุดถ้ามีคนแก้ไฟล์ใบงานด้วยมือ)
    """

    title: str
    is_unique: bool
    condition_grade: "PosterCondition | None"  # noqa: F821 - forward ref, ดู docstring
    # ‹2026-08-22 · ADR-0028 INF-32› เจ้าของและสถานะการอนุมัติของแถวพ่อ — ลูกสืบทอด
    # ทั้งคู่ **ไม่ใช่ค่าใหม่ที่เส้นนี้ตัดสินเอง** ดู `run()` ตรงที่สร้าง `Poster(...)`
    seller_id: uuid.UUID
    approved_at: "datetime | None"  # noqa: F821 - forward ref, ดู docstring


class RowAction(str, Enum):
    WRITE = "WRITE"
    SKIP_BLANK = "SKIP_BLANK"  # ยังไม่ได้กรอก
    SKIP_NOT_FOUND = "SKIP_NOT_FOUND"  # ไม่มีแถวพ่อนี้ใน DB
    # แถวพ่อไม่ใช่ is_unique=false แล้ว — มีคนแก้ผ่านเส้นที่ 5 ไปแล้วระหว่างใบงานนี้
    # ยังค้างอยู่ (D3: แตกลูกก่อน → แก้พ่อทีหลัง แต่ระหว่างนั้นพ่ออาจถูกแก้จากรอบอื่น)
    SKIP_NOT_ELIGIBLE = "SKIP_NOT_ELIGIBLE"
    # 🔴 AC-5 (ADR-0024 A-D5) — พ่อยังไม่มี condition_grade ณ ตอนรัน · กันกรอบไฟของ
    # BL-82 (ADR-0019 D4 ข้อ 2) หลุดเข้ามาจากใบงานที่คนแก้มือ ไม่ใช่ผ่าน
    # make_split_sheet.py (ตัว generator กรองด่านนี้ไว้แล้วชั้นหนึ่ง แต่ applier ต้อง
    # ไม่เชื่อใจแหล่งที่มาของไฟล์)
    SKIP_PARENT_UNGRADED = "SKIP_PARENT_UNGRADED"
    # 🔴 AC-4 (ADR-0024 A-D6) — piece_no ที่กรอกมาชนกับที่มีอยู่แล้วใน poster_splits
    # ของพ่อคนนี้ — **ข้ามเฉพาะแถว ไม่ปฏิเสธทั้งไฟล์** (ต่างจาก BLOCKED_ALREADY_SPLIT
    # เดิมที่ถูกถอดไปแล้ว) เพราะการรันไฟล์ที่ทำไปครึ่งเดียวซ้ำเป็น workflow ปกติของ
    # เส้นนี้ (README §เส้นที่ 6) — ราคาที่ยอมรับ: piece_no ที่คนแก้มือจนชนเลขเดิม
    # จะถูกข้าม ไม่ใช่ถูกปฏิเสธ ⇒ รายงานต้องดังพอ (ดู _report())
    SKIP_PIECE_TAKEN = "SKIP_PIECE_TAKEN"
    # 🔴 AC-6 (ADR-0024 A-D5 สูตร piece_no <= count_actual) — ยังไม่มีผลนับใบจริง
    # (count_actual ว่าง หรือไม่มีแถวของพ่อนี้เลยใน manual-entry.csv) ต่างจากประตู
    # publish ของ manual_entry.py ที่ค่าว่าง = เตือนไม่ปฏิเสธ — เส้นนี้*สร้าง*ของใหม่
    # ไม่ใช่*เปิดขาย*ของเดิม ค่าว่างจึงต้องปฏิเสธ (แต่ข้ามเฉพาะแถว ไม่ทั้งไฟล์)
    SKIP_NOT_COUNTED = "SKIP_NOT_COUNTED"
    # 🔴 AC-6 — piece_no ที่กรอกมาเกินจำนวนที่นับได้จริง (piece_no > count_actual)
    SKIP_OVER_COUNT = "SKIP_OVER_COUNT"


@dataclass(frozen=True)
class PlannedSplit:
    row: SplitRow
    action: RowAction
    parent_title: str | None  # None เมื่อไม่มีแถวพ่อให้อ่าน
    # ผลนับที่ใช้ตัดสิน — ไม่ว่างเฉพาะ SKIP_NOT_COUNTED/SKIP_OVER_COUNT/WRITE
    # (เก็บไว้ให้ _report() แสดงได้โดยไม่ต้อง query ซ้ำ)
    count_actual: int | None = None
    # ‹2026-08-22 · ADR-0028 INF-32› ค่าที่ลูกสืบทอดจากพ่อ — ไม่ว่างเฉพาะ WRITE
    # 🔴 อ่านเป็น "คัดลอกมาจากพ่อ" ไม่ใช่ "เส้นนี้ตัดสิน" (ดูคอมเมนต์ที่ `Poster(...)`)
    parent_seller_id: uuid.UUID | None = None
    parent_approved_at: "datetime | None" = None  # noqa: F821 - forward ref


def plan_writes(
    rows: list[SplitRow],
    parents: dict[uuid.UUID, ParentState],
    taken_pieces: dict[uuid.UUID, frozenset[int]],
    counts: dict[uuid.UUID, int | None],
) -> list[PlannedSplit]:
    """แถวใบงาน + สถานะพ่อปัจจุบัน + piece_no ที่ใช้ไปแล้ว + ผลนับ → แผนการสร้างแถวลูก

    `parents` = {parent_poster_id: ParentState} · พ่อที่ไม่มีใน dict ถือว่าไม่มีใน DB
    `taken_pieces` = {parent_poster_id: {piece_no, ...}} — เซตของ `piece_no` ที่เคยถูก
    ใช้แตกพ่อคนนี้แล้ว (จาก `poster_splits` ที่มีอยู่จริง — ADR-0024 A-D5 §ใครเติม:
    applier ตรวจซ้ำกับ DB ว่าเลขในไฟล์ยังว่างอยู่จริง ไม่ใช่คิดเลขใหม่ให้)
    `counts` = {parent_poster_id: count_actual | None} — ผลนับล่าสุดจาก
    `manual-entry.csv` (`load_count_actual_by_poster()`) · `None` = ยังไม่มีผลนับของพ่อคนนั้น

    pure function — ไม่ query ไม่เขียน ไม่แตะเวลาปัจจุบัน · ทั้งสอง dict เป็น
    พารามิเตอร์บังคับ (ไม่มี default) โดยตั้งใจ — AC-3 ต้องพิสูจน์ได้ว่าตัดด่านชั้น
    สคริปต์ออกจากสาย (`taken_pieces={}`) แล้วยังชนที่ระดับ DB จริง

    ลำดับด่าน (ตรงกับ GATE 1): SKIP_BLANK → SKIP_NOT_FOUND → SKIP_NOT_ELIGIBLE →
    SKIP_PARENT_UNGRADED (AC-5) → SKIP_PIECE_TAKEN (AC-4) → SKIP_NOT_COUNTED /
    SKIP_OVER_COUNT (AC-6) → WRITE — หลังก้อนนี้ไม่เหลือด่านที่ปฏิเสธทั้งไฟล์เลย
    (ต่างจากเดิมที่ BLOCKED_ALREADY_SPLIT ปฏิเสธทั้งไฟล์ — A-D6 หักล้างแล้ว)
    """
    plans: list[PlannedSplit] = []
    for row in rows:
        if row.payload is None:
            plans.append(
                PlannedSplit(row=row, action=RowAction.SKIP_BLANK, parent_title=None)
            )
            continue

        state = parents.get(row.parent_poster_uuid)
        if state is None:
            plans.append(
                PlannedSplit(
                    row=row, action=RowAction.SKIP_NOT_FOUND, parent_title=None
                )
            )
            continue

        if state.is_unique:
            plans.append(
                PlannedSplit(
                    row=row,
                    action=RowAction.SKIP_NOT_ELIGIBLE,
                    parent_title=state.title,
                )
            )
            continue

        if state.condition_grade is None:
            plans.append(
                PlannedSplit(
                    row=row,
                    action=RowAction.SKIP_PARENT_UNGRADED,
                    parent_title=state.title,
                )
            )
            continue

        taken = taken_pieces.get(row.parent_poster_uuid, frozenset())
        if row.payload.piece_no in taken:
            plans.append(
                PlannedSplit(
                    row=row,
                    action=RowAction.SKIP_PIECE_TAKEN,
                    parent_title=state.title,
                )
            )
            continue

        count = counts.get(row.parent_poster_uuid)
        if count is None:
            plans.append(
                PlannedSplit(
                    row=row,
                    action=RowAction.SKIP_NOT_COUNTED,
                    parent_title=state.title,
                    count_actual=None,
                )
            )
            continue

        if row.payload.piece_no > count:
            plans.append(
                PlannedSplit(
                    row=row,
                    action=RowAction.SKIP_OVER_COUNT,
                    parent_title=state.title,
                    count_actual=count,
                )
            )
            continue

        plans.append(
            PlannedSplit(
                row=row,
                action=RowAction.WRITE,
                parent_seller_id=state.seller_id,
                parent_approved_at=state.approved_at,
                parent_title=state.title,
                count_actual=count,
            )
        )
    return plans


def assert_schema_ready(has_table: bool) -> None:
    """ปลายทางต้องมีตาราง `poster_splits` ก่อนเขียน — pure เพื่อให้ test ครอบได้

    อาการเดียวกับ `manual_entry.assert_schema_ready()`: รันในคอนเทนเนอร์ที่ image เก่า
    หรือ DB ปลายทางยังไม่ `alembic upgrade head`
    """
    if not has_table:
        raise PrecheckError(
            "ปลายทางไม่มีตาราง poster_splits (ADR-0024 D2 · INF-22)\n"
            "แปลว่า **ปลายทางตามหลัง develop อยู่** — ถ้ารันในคอนเทนเนอร์คือ image เก่า "
            "(ต้อง build/pull ใหม่) ถ้ารันบน host คือ DB ยังไม่ `alembic upgrade head`"
        )


# --------------------------------------------------------------------------
# รายงาน
# --------------------------------------------------------------------------


def _report(plans: list[PlannedSplit], target_label: str, committed: bool) -> None:
    """🔴 หลังก้อนที่ 2 (INF-25) ไม่มีด่านไหนปฏิเสธทั้งไฟล์แล้ว (A-D6) — ทุก skip เป็น
    ข้ามเฉพาะแถว รายงานนี้จึงต้องดังพอที่คนอ่านจะไม่พลาด `SKIP_PIECE_TAKEN` (AC-4:
    ราคาที่ยอมรับคือแถวที่ตั้งใจแตกจริงหายไปเงียบ ๆ ถ้าไม่มีใครอ่านรายงาน)
    """
    by_action = {action: 0 for action in RowAction}
    for plan in plans:
        by_action[plan.action] += 1

    print()
    print("=" * 72)
    print(f"ปลายทาง : {target_label}")
    print(f"แถวในใบงาน : {len(plans)}")
    print()
    print("แยกตามผลของแถว:")
    print(f"  จะสร้างแถวลูกใหม่                      : {by_action[RowAction.WRITE]}")
    print(
        f"  ข้าม — ยังไม่ได้กรอก                   : {by_action[RowAction.SKIP_BLANK]}"
    )
    print(
        f"  ข้าม — ไม่มีแถวพ่อนี้ใน DB              : "
        f"{by_action[RowAction.SKIP_NOT_FOUND]}"
    )
    print(
        f"  ข้าม — พ่อไม่ใช่ is_unique=false แล้ว    : "
        f"{by_action[RowAction.SKIP_NOT_ELIGIBLE]}  (มีคนแก้ผ่านเส้นที่ 5 ไปแล้ว)"
    )
    print(
        f"  ข้าม — พ่อยังไม่มีเกรด                  : "
        f"{by_action[RowAction.SKIP_PARENT_UNGRADED]}  (AC-5 — กันกรอบไฟ BL-82)"
    )
    print(
        f"  ข้าม — piece_no นี้ถูกใช้ไปแล้ว          : "
        f"{by_action[RowAction.SKIP_PIECE_TAKEN]}  (AC-4 — แถวนั้นไม่ถูกสร้าง)"
    )
    print(
        f"  ข้าม — ยังไม่มีผลนับ                    : "
        f"{by_action[RowAction.SKIP_NOT_COUNTED]}  (count_actual ว่าง/ไม่มีในใบงาน)"
    )
    print(
        f"  ข้าม — piece_no เกินผลนับ               : "
        f"{by_action[RowAction.SKIP_OVER_COUNT]}  (piece_no > count_actual)"
    )

    writing = [p for p in plans if p.action is RowAction.WRITE]
    if writing:
        print()
        print(f"🔴 จะสร้างแถวลูกใหม่ {len(writing)} แถว:")
        for plan in writing:
            payload = plan.row.payload
            assert payload is not None  # WRITE การันตีว่ามี payload เสมอ
            print(
                f"  บรรทัด {plan.row.lineno:>4}  {plan.parent_title!r} → "
                f"ชิ้นที่ {payload.piece_no} · เกรด {payload.condition_grade.value} · "
                f"ราคา {payload.price} บาท"
            )
            print(f"                เหตุผล: {payload.reason}")
        print(
            "  ↑ แถวลูกได้ title จากพ่อ · is_unique/status/published_at/needs_review "
            "ปล่อยเป็น server_default · ฟิลด์ระดับงานพิมพ์ (tmdb_id/year/... ) เป็น NULL "
            "ทั้งหมด (OD-2)"
        )

    not_eligible = [p for p in plans if p.action is RowAction.SKIP_NOT_ELIGIBLE]
    if not_eligible:
        print()
        print("ข้าม — พ่อไม่ใช่ is_unique=false แล้ว ณ ตอนรัน:")
        for plan in not_eligible:
            print(f"  บรรทัด {plan.row.lineno:>4}  {plan.parent_title!r}")

    ungraded = [p for p in plans if p.action is RowAction.SKIP_PARENT_UNGRADED]
    if ungraded:
        print()
        print("ข้าม — พ่อยังไม่มี condition_grade (AC-5 — กันกรอบไฟของ BL-82):")
        for plan in ungraded:
            print(f"  บรรทัด {plan.row.lineno:>4}  {plan.parent_title!r}")

    piece_taken = [p for p in plans if p.action is RowAction.SKIP_PIECE_TAKEN]
    if piece_taken:
        print()
        print(
            f"🔴 ข้าม — piece_no ชนกับที่มีอยู่แล้ว {len(piece_taken)} แถว "
            "(AC-4 — แถวเหล่านี้ไม่ถูกสร้าง):"
        )
        for plan in piece_taken:
            payload = plan.row.payload
            assert payload is not None
            print(
                f"  บรรทัด {plan.row.lineno:>4}  {plan.parent_title!r} — "
                f"piece_no {payload.piece_no} ถูกใช้ไปแล้ว"
            )
        print(
            "  ↑ ถ้าตั้งใจแตกชิ้นใหม่ ให้ regenerate ใบงานด้วย make_split_sheet.py "
            "เพื่อได้ piece_no ที่ยังว่าง — ห้ามแก้เลขในใบงานเดิมด้วยมือ (A-D6: เลขที่ "
            "ชนจะถูกข้าม ไม่ถูกปฏิเสธ — ชิ้นที่ตั้งใจแตกจริงหายไปเงียบ ๆ ถ้าไม่อ่านตรงนี้)"
        )

    not_counted = [p for p in plans if p.action is RowAction.SKIP_NOT_COUNTED]
    if not_counted:
        print()
        print(
            f"ข้าม — ยังไม่มีผลนับใบจริง {len(not_counted)} แถว "
            "(count_actual ว่างหรือไม่มีแถวใน manual-entry.csv — AC-6):"
        )
        for plan in not_counted:
            print(f"  บรรทัด {plan.row.lineno:>4}  {plan.parent_title!r}")

    over_count = [p for p in plans if p.action is RowAction.SKIP_OVER_COUNT]
    if over_count:
        print()
        print(f"🔴 ข้าม — piece_no เกินผลนับ {len(over_count)} แถว (AC-6):")
        for plan in over_count:
            payload = plan.row.payload
            assert payload is not None
            print(
                f"  บรรทัด {plan.row.lineno:>4}  {plan.parent_title!r} — "
                f"piece_no {payload.piece_no} > count_actual {plan.count_actual}"
            )

    print()
    print("ไม่มีคำสั่ง UPDATE บน posters เลยแม้แต่บรรทัดเดียว — ไม่แตะ price/status/")
    print("published_at/needs_review/condition_grade ของแถวพ่อเลย · ไม่เขียน is_unique")
    print("ของใครเลยทั้งพ่อและลูก (server_default จัดการแถวลูก)")
    print()
    skipped = len(plans) - by_action[RowAction.WRITE]
    print(
        f"สรุป: สร้างจริง {by_action[RowAction.WRITE]} แถว · ข้ามทั้งหมด {skipped} แถว"
    )
    if not committed:
        print()
        print("DRY-RUN — ไม่ได้เขียนอะไรลง database (ใส่ --commit เพื่อเขียนจริง)")
        if writing:
            print(f"🔴 ยืนยันจำนวน {len(writing)} แถวข้างบนก่อนใส่ --commit")
    print("=" * 72)

    if not committed:
        specs = field_specs()
        print("\nค่าที่รับได้:")
        for name in ("condition_grade", "price"):
            print(f"  {name:<20} {specs[name].hint}")


# --------------------------------------------------------------------------
# ตัวรัน
# --------------------------------------------------------------------------


async def _load_parents(
    session: Any, parent_ids: list[uuid.UUID]
) -> dict[uuid.UUID, ParentState]:
    from sqlalchemy import select

    from app.models.poster import Poster

    if not parent_ids:
        return {}
    result = await session.execute(
        select(
            Poster.id,
            Poster.title,
            Poster.is_unique,
            Poster.condition_grade,
            Poster.seller_id,
            Poster.approved_at,
        ).where(Poster.id.in_(parent_ids))
    )
    return {
        poster_id: ParentState(
            title=title,
            is_unique=is_unique,
            condition_grade=condition_grade,
            seller_id=seller_id,
            approved_at=approved_at,
        )
        for (
            poster_id,
            title,
            is_unique,
            condition_grade,
            seller_id,
            approved_at,
        ) in result.all()
    }


async def _load_taken_pieces(
    session: Any, parent_ids: list[uuid.UUID]
) -> dict[uuid.UUID, frozenset[int]]:
    """`piece_no` ที่เคยถูกใช้แตกพ่อแต่ละคนไปแล้ว — ด่านชั้นสคริปต์ของ
    `SKIP_PIECE_TAKEN` (ADR-0024 A-D5 · INF-25) คู่กับ `uq_poster_splits_parent_piece`
    ที่ระดับ DB — ดู docstring ของ `plan_writes()` · แทน `_load_already_split()` เดิม
    ที่อ่าน `reason` (ถูกถอดไปพร้อม `uq_poster_splits_parent_reason`)
    """
    from collections import defaultdict

    from sqlalchemy import select

    from app.models.poster_split import PosterSplit

    if not parent_ids:
        return {}
    result = await session.execute(
        select(PosterSplit.parent_poster_id, PosterSplit.piece_no).where(
            PosterSplit.parent_poster_id.in_(parent_ids)
        )
    )
    by_parent: dict[uuid.UUID, set[int]] = defaultdict(set)
    for parent_id, piece_no in result.all():
        by_parent[parent_id].add(piece_no)
    return {parent_id: frozenset(pieces) for parent_id, pieces in by_parent.items()}


async def _check_schema(session: Any) -> None:
    from sqlalchemy import text

    from app.models.poster_split import PosterSplit

    has_table = bool(
        await session.scalar(
            text(
                "SELECT 1 FROM information_schema.tables "
                "WHERE table_schema = current_schema() AND table_name = :table"
            ),
            {"table": PosterSplit.__tablename__},
        )
    )
    assert_schema_ready(has_table)


async def run(args: argparse.Namespace, target_label: str) -> int:
    from sqlalchemy.exc import IntegrityError

    from app.core.database import async_session_maker
    from app.models.poster import Poster
    from app.models.poster_split import PosterSplit

    assert_own_sheet(args.file)
    rows = parse_rows(read_sheet(args.file))
    if not rows:
        print("ใบงานไม่มีแถวข้อมูล — ไม่มีอะไรให้ทำ")
        return 0

    # ด่านผลนับ (AC-6) อ่านไฟล์ล้วน ๆ ไม่ต้องมี DB — เรียกก่อนเข้า session เพื่อให้
    # PrecheckError ของไฟล์นี้ (ไม่พบไฟล์ / header ไม่มี count_actual) ขึ้นก่อนเสมอ
    # ไม่ปนกับ error ที่มาจากชั้น DB
    counts = load_count_actual_by_poster(DEFAULT_MANUAL_CSV)

    async with async_session_maker() as session:
        await _check_schema(session)
        parent_ids = [r.parent_poster_uuid for r in rows]
        parents = await _load_parents(session, parent_ids)
        taken_pieces = await _load_taken_pieces(session, parent_ids)
        plans = plan_writes(rows, parents, taken_pieces, counts)

        # 🔴 หลังก้อนที่ 2 (INF-25 · A-D6) ไม่มีด่านไหนปฏิเสธทั้งไฟล์แล้ว — ทุก skip
        # เป็นการข้ามเฉพาะแถว รายงานคือด่านเดียวที่เหลือ (ดู docstring ของ _report())
        _report(plans, target_label, committed=args.commit)
        if not args.commit:
            return 0

        source = args.file.name
        created = 0

        for plan in plans:
            if plan.action is not RowAction.WRITE:
                continue
            payload = plan.row.payload
            assert payload is not None  # WRITE การันตีว่ามี payload เสมอ

            # id มินท์เองแทนรอ server_default — ต้องรู้ id ของลูกทันทีเพื่อผูก
            # poster_splits.child_poster_id ในทรานแซกชันเดียวกัน ไม่ต้อง flush คั่น
            # 🔴 title/price/condition_grade เท่านั้นที่ set — is_unique/status/
            # needs_review/is_authenticated ปล่อยให้ server_default ของคอลัมน์จัดการ
            # (D3/D4 — ห้าม set ค่าเหล่านี้เอง) ฟิลด์ระดับงานพิมพ์อื่นไม่ถูกแตะเลย
            # จึงเป็น NULL ตามค่าเริ่มต้นของคอลัมน์ (OD-2)
            #
            # ‹2026-08-22 · ADR-0028 INF-32› **+2 kwargs ที่สืบทอดจากพ่อ ไม่ใช่ค่าใหม่**
            # `seller_id`   — ของชิ้นเดียวถูกแตกเป็นหลายชิ้น **เจ้าของไม่เปลี่ยน**
            #                 คอลัมน์เป็น NOT NULL และตั้งใจไม่มี server_default
            #                 (การเดาเจ้าของคือความผิดพลาดที่แพงที่สุดในตลาดหลายผู้ขาย)
            # `approved_at` — พ่อผ่านการอนุมัติมาแล้ว (BR-L6) การแตกแถวเป็นการนับใหม่
            #                 ของ**ของเดิม** ไม่ใช่การเอาของใหม่เข้าร้าน จึงไม่ต้อง
            #                 อนุมัติซ้ำ · ถ้าไม่สืบทอด ลูกจะละเมิด
            #                 `ck_posters_sellable_requires_approved_at` ทันทีที่
            #                 `status` ได้ค่า `available` จาก server_default
            # 🔴 **ทั้งคู่ยังอยู่ในหลัก D3/D4 เดิม** — เส้นนี้ไม่ได้ *ตัดสิน* ค่าไหนใหม่
            #    มันคัดลอกค่าของพ่อมาตรง ๆ · ต่างจาก `status`/`is_unique` ที่ D3/D4
            #    ห้ามแตะเพราะการ set มันคือการตัดสิน
            child = Poster(
                id=uuid.uuid4(),
                title=plan.parent_title,
                price=payload.price,
                condition_grade=payload.condition_grade,
                seller_id=plan.parent_seller_id,
                approved_at=plan.parent_approved_at,
            )
            session.add(child)
            session.add(
                PosterSplit(
                    child_poster_id=child.id,
                    parent_poster_id=plan.row.parent_poster_uuid,
                    # 🔴 มาจากไฟล์ตรง ๆ — ห้ามคำนวณ/เดาเลขใหม่ที่นี่ (ADR-0024 A-D5
                    # §ใครเติม) applier มีหน้าที่แค่ตรวจซ้ำว่าเลขนี้ยังว่างอยู่จริง
                    # (SKIP_PIECE_TAKEN ใน plan_writes()) ไม่ใช่คิดเลขใหม่ให้ — ถ้าคิดเอง
                    # รันซ้ำจะได้เลขใหม่ทุกครั้งและ AC-4 จะไม่กันอะไรเลย
                    piece_no=payload.piece_no,
                    reviewed_by=args.reviewed_by,
                    reviewed_at=args.reviewed_at,
                    source=source,
                    reason=payload.reason,
                )
            )
            created += 1

        try:
            await session.commit()
        except IntegrityError as exc:
            await session.rollback()
            # เคสจริงที่ทำให้พังตรงนี้ได้คือ piece_no ชนกัน (uq_poster_splits_parent_
            # piece — ควรไม่เกิดเพราะ SKIP_PIECE_TAKEN กันไว้แล้วที่ชั้นสคริปต์ เว้นแต่
            # มีคนแตกพ่อเดียวกันพร้อมกันจากสองเครื่อง) หรือ child_poster_id ชนกัน
            # (uq_poster_splits_child_poster — แทบเป็นไปไม่ได้เพราะ id เป็น uuid4
            # สดใหม่ทุกแถว) — จับไว้เพื่อไม่ให้คนเห็น traceback ดิบ ไม่ใช่เพราะคาดว่า
            # จะเกิดบ่อย (AC-3: ด่านชั้นสคริปต์ไม่ใช่ตัวกันจริง — DB ต่างหากที่เป็น
            # fail-closed จริง)
            print(
                f"\n🔴 commit ล้มเหลว (IntegrityError) — rollback แล้ว ไม่มีอะไรถูกเขียนจริง:"
                f"\n{exc}",
                file=sys.stderr,
            )
            return 1

    print(
        f"\nสร้างแถวลูกใหม่แล้ว {created} แถว · บันทึก poster_splits {created} แถวคู่กัน"
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--commit",
        action="store_true",
        help="เขียนลง database จริง (ไม่ใส่ = dry-run นับแถวอย่างเดียว)",
    )
    parser.add_argument(
        "--file",
        type=Path,
        default=DEFAULT_SPLIT_CSV,
        help=f"ใบงาน (default: {DEFAULT_SPLIT_CSV.name})",
    )
    parser.add_argument(
        "--target",
        choices=TARGETS,
        default="dev",
        help="ปลายทาง — เหมือนเส้นอื่นทุกประการ (ADR-0015 D8: dev กับ sit เท่านั้น "
        "production ไม่มีให้เลือกโดยตั้งใจ) · sit ต้องรันข้างในคอนเทนเนอร์ sit และ "
        f"DATABASE_URL ต้องตรงกับ {SIT_ENV_FILE} เป๊ะ",
    )
    parser.add_argument(
        "--reviewed-by",
        help="ชื่อคนที่ตัดสินใจแตกแถวรอบนี้ — บังคับเมื่อ --commit",
    )
    parser.add_argument(
        "--reviewed-at",
        metavar="<เวลาที่คุณตัดสิน ISO-8601 พร้อม timezone>",
        help="บังคับเมื่อ --commit · 🔴 ไม่มี default เป็นเวลาปัจจุบัน และค่าที่อยู่"
        "ในอนาคตถูกปฏิเสธ (เวลาที่คนตัดสินย้อนไปข้างหน้าไม่ได้)",
    )
    args = parser.parse_args()

    if args.commit:
        if not args.reviewed_by:
            parser.error("--commit ต้องระบุ --reviewed-by ด้วย")
        if not args.reviewed_at:
            parser.error("--commit ต้องระบุ --reviewed-at ด้วย")
        try:
            args.reviewed_at = _parse_reviewed_at(args.reviewed_at)
            # 🔴 จุดเดียวในโมดูลที่อ่านนาฬิกา — และอ่านเพื่อ **ปฏิเสธ** เท่านั้น
            # ไม่เคยถูกใช้เป็นค่าให้ args.reviewed_at
            assert_not_in_the_future(args.reviewed_at, now=datetime.now(timezone.utc))
        except PrecheckError as exc:
            parser.error(str(exc))

    _load_env(args.target)
    database_url = os.environ.get("DATABASE_URL", "")
    if not database_url:
        print(f"ไม่พบ DATABASE_URL (target={args.target})", file=sys.stderr)
        return 1

    try:
        target_label = (
            f"{assert_target(database_url, args.target)}  [--target {args.target}]"
        )
    except PrecheckError as exc:
        print(
            f"precheck ไม่ผ่าน: {exc}\n"
            "(ADR-0015 D8 — production ไม่มีให้เลือกเลย · --target sit ต้องรัน"
            f"ข้างในคอนเทนเนอร์ sit และ DATABASE_URL ต้องตรงกับ {SIT_ENV_FILE} เป๊ะ)",
            file=sys.stderr,
        )
        return 1

    import asyncio

    try:
        return asyncio.run(run(args, target_label))
    except PrecheckError as exc:
        print(f"precheck ไม่ผ่าน: {exc}", file=sys.stderr)
        return 1
    except OSError as exc:
        hint = ""
        if args.target == "sit":
            hint = (
                "\n--target sit ต้องรัน **ข้างในคอนเทนเนอร์ sit** ไม่ใช่จากเครื่องนี้:\n"
                "  docker compose -p posternung-sit \\\n"
                "    -f docker-compose.yml -f docker-compose.sit.yml --env-file .env.sit \\\n"
                "    exec app python scripts/seed/split_entry.py --target sit"
            )
        print(
            f"ต่อ database ไม่ได้ (target={args.target}): {exc}{hint}", file=sys.stderr
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
