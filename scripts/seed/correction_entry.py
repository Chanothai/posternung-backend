"""แก้ค่าที่ **มีคนเห็นบนหน้าร้านไปแล้ว** — ADR-0010 Amendment 2026-08-09 (INF-21)

    ./venv/bin/python scripts/seed/make_correction_sheet.py            # 1. สร้างใบงาน
    # 2. คนหยิบใบจริงขึ้นมาตรวจซ้ำ แล้วกรอก **ค่าใหม่ + เหตุผล** ของฟิลด์นั้น
    ./venv/bin/python scripts/seed/correction_entry.py                  # 3. dry-run (default)
    ./venv/bin/python scripts/seed/correction_entry.py --commit \
        --reviewed-by <ชื่อคุณ> \
        --reviewed-at <เวลาที่คุณตัดสิน ISO-8601 พร้อม timezone>

🔴 **ค่าตัวอย่างข้างบนเป็น placeholder ที่ก๊อปทั้งบรรทัดแล้วรันไม่ผ่านโดยตั้งใจ** —
ตัวอย่างที่เคยเขียนเป็นเวลาจริงถูกก๊อปมาทั้งบรรทัดเมื่อ 2026-08-08 แล้ว `reviewed_at`
ของ 232 แถวลงเป็น **เวลาในอนาคต 3.5 ชั่วโมง** · `assert_not_in_the_future()` ปฏิเสธ
ค่าที่อยู่ในอนาคตตั้งแต่ `main()` แล้ว (ADR-0010 D5)

## นี่คือ "เส้นทางที่ 5" และมันต่างจากอีกสี่เส้นตรงจุดเดียวที่สำคัญที่สุด

อีกสี่เส้น (ADR-0015 D1) **เติมช่องที่ยังว่าง** — ไม่มีใครเคยเห็นค่าที่ถูกทับ เพราะ
ไม่มีค่าให้ทับ · เส้นนี้ **ทับค่าที่ลูกค้าอ่านไปแล้วก่อนตัดสินใจซื้อ** บนระบบที่
ADR-0002 ยืนยันว่า **คืนเงินอัตโนมัติไม่ได้** → จึงเป็นเส้นเดียวที่บังคับ `reason`
ต่อค่า และเป็นเส้นเดียวที่ `value_before` **ห้ามเป็น NULL แม้แถวเดียว**

## เขียนได้ 2 คอลัมน์ ไม่มีคอลัมน์อื่นเลย (A-D2 ข้อ 6)

| คอลัมน์ | ทำไมอยู่ที่นี่แทนที่จะเป็น `--allow-overwrite` ของเส้นที่ 3 |
|---|---|
| `condition_grade` | **BR-05** — ลูกค้าใช้ตัดสินใจซื้อ · ADR-0010 D8 ห้ามทับผ่านเส้นที่ 3 ตลอดกาล |
| `is_unique` | ปลายทางคือ *จำนวนของที่ขายได้* ผิดแล้วจบที่ ADR-0002 เหมือนกัน (**A-D1**) |

🔴 **`--allow-overwrite` ของเส้นที่ 3 ไม่เปลี่ยนเลย** — ยังเป็น `title` · `year`
เท่านั้น (**A-D4** ข้อ 3) · เหตุผลที่ไม่ขยายมันแทนการสร้างเส้นนี้อยู่ที่ **A-D3**:
flag ตัวเดียวบน CLI บังคับให้มี *หลักฐานว่ามีคนไปดูของจริงมาแล้ว* ไม่ได้

## แถวไหนถูกข้าม แถวไหนทำทั้งไฟล์พัง

**ข้ามเฉย ๆ (ปกติ ไม่ใช่ error):** เว้นว่างทั้งคู่ · ค่าใหม่เท่ากับค่าเดิม
(ADR-0010 D8 — *ค่าเท่าเดิม = ไม่ใช่การเขียน* ไม่งั้นได้ audit ปลอมและเลิก idempotent) ·
ใบไม่มีใน DB (UPDATE เท่านั้น ไม่ INSERT — ADR-0015 D5) · **`condition_grade`
ปลายทางเป็น `NULL`** (เส้นนี้ *แก้* ไม่ใช่ *เติม* → ไปใช้เส้นที่ 3)

**ทั้งไฟล์ถูกปฏิเสธ ไม่เขียนอะไรเลย (fail-closed):** `poster_uuid` ไม่ใช่ UUID ·
`poster_uuid` ซ้ำ · **กรอกค่าแต่ไม่กรอกเหตุผลของฟิลด์นั้น** (A-D2 ข้อ 2) ·
**กรอกเหตุผลแต่ไม่กรอกค่า** (ข้อมูลขัดกันเอง) · `condition_grade` ตัวพิมพ์ไม่ตรง ·
`is_unique` อ่านไม่ออก (ไม่ใช่ `Y`/`N`) · **`is_unique = N` ทุกกรณีไม่มีข้อยกเว้น**

## 🔴 `is_unique = N` เขียนไม่ได้เลยในระบบวันนี้ — และนั่นไม่ใช่ข้อจำกัดชั่วคราวของสคริปต์

**ADR-0019 D6** เขียนหัวข้อของตัวเองว่า *"หลัง D1 `is_unique` ต้องเป็น `true` **ทุกแถว**"*
และ **D5** ปิดท้ายมติว่า *"จนถึงตอนนั้น **แม้ใบ `mint` ก็เก็บเป็น 1 แถว 1 ชิ้น** — D1 คือ
สิทธิ์ที่ยังไม่มีเครื่องมือรองรับ ไม่ใช่สิ่งที่ทำได้พรุ่งนี้"* · เหตุผลอยู่ในโค้ดจริง
ไม่ใช่ความกังวล: `posters.status` เป็นสถานะของ **แถว** · reservation ผูกกับ `poster_id`
ไม่ใช่กับชิ้น · และ `uq_active_reservation_per_poster` ปฏิเสธ active reservation ที่สอง
ของแถวเดียวกัน**ที่ระดับ DB** ⇒ แถวที่แทนของ 3 ชิ้นขายได้จริงชิ้นเดียว

🔴 **วันเปิดกลไกต้องทำสามอย่างพร้อมกันรอบเดียว** (คอลัมน์ `quantity` + รื้อ
`uq_active_reservation_per_poster` พร้อมเขียน concurrency ใหม่ให้ครบ 7 คำถามของ
`stock-integrity` + **BR-04 ทั้ง 5 จุดของ D7**) — มติเจ้าของ 2026-08-09 เขียนกำกับว่า
**"ห้ามทยอย"** · สคริปต์ที่ยอมให้เขียน `N` ได้ **คือการทยอยข้อแรก** จึงห้ามมีทางนั้น
· ถ้าจะเปิดจริงต้องมี **amendment ของ ADR-0019 ก่อน ไม่ใช่แก้ไฟล์นี้**

⚠️ **"อ่านไม่ออก" กับ "อ่านออกแต่ห้าม" เป็นคนละเรื่องและแยกกันในโค้ด** —
`parse_is_unique()` ยัง parse `N` เป็น `False` ได้ตามปกติ (มันไม่ใช่ค่ากำกวม)
ส่วนด่านนโยบายอยู่ที่ `parse_rows()` และบอกเหตุผลเป็นคนละข้อความกัน

🔴 **ด่านทุกตัวอยู่ *ก่อน* เปิด session — ไม่มีที่ไหนในไฟล์นี้ที่ rollback และไม่มีที่ไหน
ที่ตัดสินหลังเปิด transaction** · ทุกกฎของเส้นนี้ตรวจได้จาก *ตัวไฟล์อย่างเดียว* จึงอยู่ใน
`parse_rows()` ทั้งหมด ซึ่ง `raise PrecheckError` **ก่อน `return`** และถูกเรียกก่อน
`async with async_session_maker()` เสมอ

## ทำไมไม่มี `_report_counts()` แบบเส้นอื่น

เส้นอื่น assert ด้วย `count(<column>)` ก่อน/หลัง — ใช้ได้เพราะมันเติมช่องว่าง
(`NULL` → มีค่า = ตัวนับขยับ) · **เส้นนี้ทับ 100% ของการเขียน ตัวนับจึงไม่ขยับ
เลยสักหน่วยไม่ว่าจะสำเร็จหรือล้มเหลว** เป็นกับดักตัวเดียวกับ `count(*)` ที่
`manual_entry._column_counts()` เตือนไว้ แค่ลึกลงไปอีกชั้น (ดู
`manual_entry.verify_overwrites()`) · ตัวเดียวที่พิสูจน์ได้คือ **อ่านค่ากลับมาเทียบ**
→ `verify_corrections()`

## สิ่งที่สคริปต์นี้ **ไม่** ทำ

- ❌ **ไม่แตะคอลัมน์อื่นของ `posters` เลยสักตัว** — `WRITABLE_FIELDS` เป็น fail-closed
  ในลูปที่เขียน + `choices` ที่ argparse + มีเทสล็อกไว้ **สามชั้น** (ระดับซอร์ส ·
  ระดับ runtime · ตัวเซตเอง) เพราะชั้นเดียวจับชื่อที่ประกอบตอนรันไม่ได้
- ❌ **ไม่แตะ `needs_review` · `status` · `published_at`** — `status` เป็นของ service
  ที่คุม transition (skill `poster-database` §3) · `published_at` เป็น *เหตุการณ์*
  ที่ ADR-0010 D8 ห้ามทับตลอดกาล
- ❌ **ไม่อ่านช่อง `current_*` ในใบงาน** — เป็นช่องช่วยจำของคนล้วน ๆ (precedent ตรงตัว:
  `previous_note` ของเส้นที่ 4 · ADR-0014 D28) · มีเทส closed-world ที่ระดับคีย์ที่ถูกอ่านจริง
- ❌ **ไม่แตกแถว ไม่แตะ `quantity`/`price`** — เป็นงานของ **INF-22** (ADR-0019 D8/D11)
"""

from __future__ import annotations

import argparse
import os
import sys
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
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

# 🔴 import **object เดียวกัน ไม่ก๊อป** — `_enum_parser(..., exact_case=True)` คือด่าน
# ที่ทำให้ `Fine` ไม่ถูกแปลงเป็น `fine` เงียบ ๆ (เกิดจริง 8 แถวเมื่อ 2026-08-07) ·
# ถ้าก๊อปมาเป็นสำเนา วันที่ใครแก้ด่านฝั่งหนึ่งอีกฝั่งจะเงียบ (เหตุผลเต็ม: `_shared.py`)
from scripts.seed.manual_entry import (  # noqa: E402
    DEFAULT_MANUAL_CSV,
    SIT_ENV_FILE,
    TARGETS,
    FieldSpec,
    _enum_parser,
    assert_target,
    render_value,
)
from scripts.seed.reference_entry import DEFAULT_REFERENCE_CSV  # noqa: E402

DEFAULT_CORRECTION_CSV = SEED_DIR / "correction-entry.csv"

# 🔴 คอลัมน์ทั้งหมดที่สคริปต์นี้เขียนได้ — ADR-0010 **A-D2 ข้อ 6**
# **ห้ามเพิ่มโดยไม่แก้ ADR** · ตัวนี้เป็นแหล่งเดียวของ `choices` ที่ argparse ด้วย
# ("ปฏิเสธฟิลด์นอกรายการตั้งแต่ชั้น CLI") และของ fail-closed ในลูปที่เขียน
WRITABLE_FIELDS = ("condition_grade", "is_unique")
# ช่องเหตุผล — **หนึ่งช่องต่อหนึ่งฟิลด์** (มติเจ้าของ 2026-08-09 · เข้มกว่าตัวอักษร
# ของ A-D2 ข้อ 2 ซึ่งพูดแค่ "ต่อแถว") · เหตุผลของเกรดกับของจำนวนเป็นคนละเรื่องกัน
# ก้อนเดียวที่ถูกก๊อปลงสองแถว audit จะอ่านย้อนแล้วแยกไม่ออกว่าอธิบายอันไหน
REASON_COLUMNS = tuple(f"{name}_reason" for name in WRITABLE_FIELDS)
# ช่องช่วยจำของคน — **สคริปต์ไม่อ่านเลย** (ดู §สิ่งที่สคริปต์นี้ไม่ทำ)
CURRENT_COLUMNS = tuple(f"current_{name}" for name in WRITABLE_FIELDS)

# คอลัมน์ของใบงาน — `make_correction_sheet.py` import ไปใช้ ไม่ประกาศซ้ำสองที่
CORRECTION_SHEET_COLUMNS = (
    "poster_uuid",
    "title",
    "image_url",
    "current_condition_grade",
    "current_is_unique",
    "condition_grade",
    "condition_grade_reason",
    "is_unique",
    "is_unique_reason",
)
# คอลัมน์ที่สคริปต์นี้ *ใช้จริง* — `title`/`image_url`/`current_*` เป็นข้อมูลให้คนอ่าน
# ตอนกรอก ขาดได้ไม่เป็นไร (แต่ generator ใส่มาให้เสมอ)
REQUIRED_COLUMNS = ("poster_uuid",) + tuple(
    col for pair in zip(WRITABLE_FIELDS, REASON_COLUMNS, strict=True) for col in pair
)

# ค่าที่ `is_unique` **อ่านออก** — `Y`/`N` เท่านั้น ไม่สนตัวพิมพ์ (AC-7)
# 🔴 "อ่านออก" ≠ "เขียนได้" — `N` อ่านออกแต่ถูกด่านนโยบายของ `parse_rows()` ปฏิเสธ
# ทุกกรณี (ADR-0019 D5 · D6) · สองเรื่องนี้แยกกันโดยตั้งใจ ดู §`is_unique = N`
IS_UNIQUE_WORDS = {"y": True, "n": False}
# ค่าที่ถูกปฏิเสธ **โดยเจตนา** ทั้งที่ภาษาอื่นตีความได้ — ดู `parse_is_unique()`
AMBIGUOUS_COUNT_WORDS = ("1", "0")
# ค่าเดียวที่ `is_unique` เขียนลง DB ได้ในระบบวันนี้ — ADR-0019 **D6**
# ("หลัง D1 `is_unique` ต้องเป็น `true` ทุกแถว") · เก็บเป็นค่าคงที่เพื่อให้ด่าน
# และเทสอ้างของชิ้นเดียวกัน ไม่ใช่ต่างคนต่างเขียน `False` ไว้คนละที่
IS_UNIQUE_ONLY_WRITABLE_VALUE = True
# คำที่ **ใบงานพิมพ์ให้คนอ่าน** ต่อค่าที่อยู่ใน DB — กลับด้านของ `IS_UNIQUE_WORDS`
# **ตัวเดียวกัน ไม่ใช่รายชื่อที่พิมพ์ซ้ำ** จึงไม่มีทางที่ฝั่งพิมพ์กับฝั่งอ่านจะรู้จัก
# คนละคำ · ตัวพิมพ์ใหญ่เพราะสเปรดชีตไม่แตะ `Y`/`N` (ไม่ใช่ boolean literal ของมัน)
IS_UNIQUE_TEXT = {value: word.upper() for word, value in IS_UNIQUE_WORDS.items()}


# --------------------------------------------------------------------------
# นิยามฟิลด์ + การตรวจรูปแบบ (pure — ไม่แตะ DB)
# --------------------------------------------------------------------------


def render_current_value(field: str, value: Any) -> str:
    """ค่าจาก DB → ข้อความในช่อง `current_<field>` ของใบงาน — **จุดเดียวที่แปลง**

    🔴 **ทุกคำที่ออกจากที่นี่ต้องเป็นคำที่ `field_specs()[field].parse` อ่านออก** —
    ช่อง `current_*` อยู่ *ติดกับ* ช่องที่คนกรอก คนจึงก๊อปข้ามช่องเป็นเรื่องปกติ
    (และควรก๊อปได้ นั่นคือเหตุผลที่ช่องนี้มีอยู่) · ถ้าสองฝั่งใช้คำคนละชุด ใบงาน
    จะ **สอนคำที่ตัวพาร์เซอร์ปฏิเสธ** แล้วคนที่ทำถูกทุกอย่างจะถูกปฏิเสธทั้งไฟล์

    ‹เกิดจริง 2026-08-11 · G7› เดิมช่องนี้เขียนด้วย `render_value()` ตรง ๆ ได้
    `True`/`False` (และสเปรดชีตเขียนกลับเป็น `TRUE`/`FALSE`) ขณะที่ `parse_is_unique()`
    รับ `Y`/`N` เท่านั้น **โดยเจตนา** — 5/5 แถวของรอบแรกถูกปฏิเสธ เสียไปหนึ่งรอบเต็ม
    · ด่านไม่ได้ผิด **generator สอนคำผิด** ทางแก้จึงอยู่ที่นี่ ไม่ใช่ผ่อนด่านให้รับ `TRUE`

    ฟิลด์ที่ไม่มีใน `SHEET_RENDERERS` ตกมาที่ `render_value()` ซึ่งถูกก็ต่อเมื่อ
    พาร์เซอร์ของมันอ่าน `str(value)` กลับได้ (จริงกับ enum: `near_mint` → `near_mint`)
    · **ด่านที่กันไม่ให้ข้อนี้กลับมาในช่องอื่นคือเทส round-trip** ไม่ใช่ความจำของคน
    → `test_make_correction_sheet.py` §round-trip
    """
    if value is None:
        # `is_unique` เป็น NOT NULL จึงไม่มีวันมาทางนี้ · `condition_grade` มาได้
        # (`--all`) และช่องว่างคือคำตอบที่ถูก: *ยังไม่มีเกรด* ไม่ใช่คำที่ต้องอ่านออก
        return ""
    renderer = SHEET_RENDERERS.get(field)
    if renderer is not None:
        return renderer(value)
    return render_value(value)


# ฟิลด์ที่ `render_value()` เขียนออกมาเป็นคำที่พาร์เซอร์ของมันเองอ่านไม่ออก
SHEET_RENDERERS = {"is_unique": lambda value: IS_UNIQUE_TEXT[bool(value)]}


def parse_is_unique(raw: str) -> bool:
    """`Y`/`N` → bool — **boolean ตัวแรกของโฟลเดอร์นี้** (AC-7 · ADR-0019 D12 ข้อ 1)

    🔴 **ฟังก์ชันนี้ตอบแค่ว่า *อ่านออกไหม* ไม่ได้ตอบว่า *เขียนได้ไหม*** — `N` อ่านออก
    และคืน `False` ตามปกติ ส่วนด่านที่ปฏิเสธมันอยู่ที่ `parse_rows()` (ADR-0019 D5/D6)
    · แยกกันโดยตั้งใจเพราะข้อความที่คนต้องอ่านคนละเรื่องกันคนละชุด: *"พิมพ์อะไรมา
    ไม่รู้จัก"* กับ *"รู้จักดี แต่ระบบวันนี้ยังรับไม่ได้และนี่คือเหตุผล"* · การยุบสอง
    อย่างนี้เข้าด้วยกันจะทำให้คนที่พิมพ์ `N` ถูกต้องตามที่เข้าใจ ได้ข้อความว่าพิมพ์ผิด

    🔴 **`1`/`0` ถูกปฏิเสธโดยเจตนา ไม่ใช่เพราะยังไม่ได้รองรับ** — ฟิลด์นี้อยู่ในใบงาน
    ของงาน *นับจำนวนใบจริง* คนที่นับได้ 1 ใบแล้วพิมพ์ `1` จะได้ `true` โดยบังเอิญ
    (ถูกโดยฟลุ๊ค) ส่วนคนที่นับได้ 0 ใบแล้วพิมพ์ `0` จะได้ `false` = *มีหลายชิ้น*
    ซึ่งตรงข้ามกับที่ตั้งใจโดยสิ้นเชิง — และนั่นคือเคส `THE MATRIX (ADVANCE 4K)` เป๊ะ ๆ
    (ADR-0019: `quantity = 0` ในไฟล์ export กลายเป็น `is_unique = false` ในระบบ
    แล้วของขึ้นหน้าร้านทั้งที่ไม่มีใครนับ)

    `true`/`false` ก็ถูกปฏิเสธด้วยหลักเดียวกัน: ยิ่งรับคำได้หลายแบบ คนยิ่งพิมพ์คำที่
    *ตัวเองแปลว่าอะไร* แทนคำที่ *ระบบแปลว่าอะไร* · หนึ่งความหมายควรมีคำเดียว
    """
    word = IS_UNIQUE_WORDS.get(raw.lower())
    if word is not None:
        return word
    hint = ""
    if raw in AMBIGUOUS_COUNT_WORDS:
        hint = (
            f" · เดาว่า {raw!r} คือ *จำนวนใบที่นับได้* ซึ่งช่องนี้ไม่ได้ถามจำนวน "
            "— ช่องนี้ถามว่า 'แถวนี้แทนของชิ้นเดียวใช่ไหม' (Y) หรือ "
            "'แถวนี้แทนของมากกว่าหนึ่งชิ้น' (N)"
        )
    raise ValueError(
        f"{raw!r} ใช้ไม่ได้ — รับเฉพาะ Y หรือ N (ตัวพิมพ์ใดก็ได้)\n"
        "    🔴 ตัวเลขและ true/false ถูกปฏิเสธโดยเจตนา เพราะช่องนี้อยู่ในใบงานเดียวกับ "
        "งานนับใบจริง: คนที่นับได้ 1 แล้วพิมพ์ 1 จะได้ 'ชิ้นเดียว' โดยบังเอิญ "
        "และคนที่นับได้ 0 แล้วพิมพ์ 0 จะได้ 'หลายชิ้น' ซึ่งตรงข้ามกับที่ตั้งใจ"
        f"{hint}"
    )


@lru_cache(maxsize=1)
def field_specs() -> dict[str, FieldSpec]:
    """นิยามของสองฟิลด์ใน `WRITABLE_FIELDS`

    import `app.models.enums` **ข้างในฟังก์ชัน** ด้วยเหตุผลเดียวกับ
    `manual_entry.field_specs()` เป๊ะ — `app/models/__init__.py` ลาก
    `app.core.database` ตามมา ซึ่งต้องการ env ครบตอน import ส่วนบนของไฟล์นี้จึงต้อง
    import ได้ก่อน `_load_env()` ถูกเรียก
    """
    from app.models.enums import PosterCondition

    return {
        "condition_grade": FieldSpec(
            name="condition_grade",
            # 🔴 `exact_case` — object เดียวกับเส้นที่ 3 เหตุผลเต็มอยู่ที่ docstring
            # ของ `manual_entry._enum_parser()` **ห้ามเขียนซ้ำที่นี่**
            parse=_enum_parser(PosterCondition, exact_case=True),
            hint=(
                "เกรดใหม่ · เรียงดี→แย่: "
                + " > ".join(m.value for m in PosterCondition)
                + " · ตัวพิมพ์เล็กทั้งหมด ต้องตรงเป๊ะ"
            ),
        ),
        "is_unique": FieldSpec(
            name="is_unique",
            parse=parse_is_unique,
            hint=(
                "Y = แถวนี้แทนของชิ้นเดียว — **วันนี้เขียนได้ค่านี้ค่าเดียว** · "
                "N (แทนหลายชิ้น) อ่านออกแต่เขียนไม่ได้ ปฏิเสธทั้งไฟล์ "
                "(ADR-0019 D5 · D6 — ของหลายชิ้นต้องแตกเป็นหลายแถว = INF-22) · "
                "ตัวเลขและ true/false ใช้ไม่ได้"
            ),
        ),
    }


def refuse_unwritable_value(field: str, value: Any) -> str | None:
    """ค่าที่ **อ่านออกแต่เขียนไม่ได้** → เหตุผล · เขียนได้ → `None` (pure)

    🔴 **นี่คือด่านของ ADR-0019 D5 · D6 และมันไม่มีเงื่อนไขเลยสักข้อ** — ไม่ดูเกรด
    ไม่ดูค่าเดิม ไม่ดู `--field` ไม่ดูว่าใบนั้นมีใน DB ไหม · ด่านนี้จึงไม่ต้องรู้
    สถานะ DB เลย และอยู่ใน `parse_rows()` ได้ ซึ่งแปลว่ามันตัดสิน**ก่อนเปิด session**

    ‹แก้ 2026-08-09 หลัง code-critic รอบที่ 1› รุ่นแรกของไฟล์นี้ทำด่านนี้เป็น
    *"`N` ได้เฉพาะเกรด `mint`"* ตาม **D1** ซึ่ง **ผิด** — D1 เป็น *สิทธิ์* ที่ **D5**
    ระบุว่ายังไม่มีเครื่องมือรองรับ (*"แม้ใบ `mint` ก็เก็บเป็น 1 แถว 1 ชิ้น"*) และ
    **D6** เขียนหัวข้อของตัวเองว่า `is_unique` ต้องเป็น `true` **ทุกแถว** ·
    ด่านที่อ่านแต่ D1 จึงเปิดกลไกทีละชิ้น ซึ่งมติเจ้าของเขียนกำกับว่า **"ห้ามทยอย"**
    """
    if field != "is_unique" or value is IS_UNIQUE_ONLY_WRITABLE_VALUE:
        return None
    return (
        "ค่านี้ **อ่านออก** แต่ **เขียนไม่ได้ในระบบวันนี้** (ไม่ใช่เพราะพิมพ์ผิด)\n"
        "    ADR-0019 **D6** — หลัง D1 แล้ว `is_unique` ต้องเป็น true **ทุกแถว**\n"
        "    ADR-0019 **D5** — กลไก 'แถวเดียวหลายชิ้น' ยังปิดอยู่: ไม่มีคอลัมน์ "
        "quantity · reservation ผูกกับ poster_id ไม่ใช่กับชิ้น · "
        "uq_active_reservation_per_poster ปฏิเสธ active reservation ที่สองของแถว"
        "เดียวกันที่ระดับ DB ⇒ แถวที่แทนของหลายชิ้นขายได้จริงชิ้นเดียว\n"
        "    ⇒ **แม้ใบ mint ก็เก็บเป็น 1 แถว 1 ชิ้น** · D1 คือสิทธิ์ที่ยังไม่มี"
        "เครื่องมือรองรับ ไม่ใช่สิ่งที่ทำได้พรุ่งนี้ — เกรดจึงไม่เกี่ยวกับด่านนี้เลย\n"
        "    🔴 วันเปิดกลไกต้องทำสามอย่างพร้อมกันรอบเดียว (quantity + รื้อ "
        "uq_active_reservation_per_poster + BR-04 ทั้ง 5 จุดของ D7) · **ห้ามทยอย** — "
        "การยอมให้สคริปต์นี้เขียน N คือการทยอยข้อแรก\n"
        "    ของมีหลายชิ้นจริง → **แตกเป็นหลายแถว** ซึ่งเป็นงานของ **INF-22** "
        "(ADR-0019 D8) ไม่ใช่ของสคริปต์นี้\n"
        "    ถ้าตั้งใจให้เขียน N ได้จริง ต้องมี **amendment ของ ADR-0019 ก่อน** "
        "ไม่ใช่แก้สคริปต์นี้"
    )


@dataclass(frozen=True)
class CorrectionRow:
    """หนึ่งแถวของใบงานที่ผ่านการตรวจรูปแบบแล้ว

    🔴 **ไม่มีฟิลด์สำหรับ `current_*`** — ชั้นนี้คือทุกอย่างที่สคริปต์รู้เกี่ยวกับ
    แถวหนึ่ง การไม่มีมันที่นี่แปลว่าไม่มีชั้นไหนข้างล่างอ่านมันได้เลย

    `values` และ `reasons` มีคีย์ **ชุดเดียวกันเสมอ** — `parse_rows()` ปฏิเสธทั้งไฟล์
    เมื่อมีอย่างใดอย่างหนึ่งขาด จึงเป็น invariant ที่ชั้นล่างพึ่งได้
    """

    poster_uuid: uuid.UUID
    values: dict[str, Any]
    reasons: dict[str, str]
    lineno: int


def assert_own_sheet(path: Path) -> None:
    """ปฏิเสธใบงานของเส้นอื่น — pure เพื่อให้ test ครอบได้โดยไม่ต้องมีไฟล์จริง

    🔴 `poster_attribute_reviews.source` เก็บ **ชื่อไฟล์ใบงาน** ซึ่งเป็นสิ่งเดียวที่
    แยกได้ว่าค่าไหนมาจากรอบไหน (ADR-0014 D28) · ส่งไฟล์ของเส้นอื่นมาแล้วแถว audit
    จะได้ `source` ชนกับเส้นนั้น แล้ว **ร่องรอยหายไปเงียบ ๆ โดยที่ทุกอย่างดูเหมือน
    สำเร็จ** — และเส้นนี้เป็นเส้นที่ทับค่าที่ลูกค้าเห็นแล้ว ร่องรอยจึงแพงกว่าเส้นอื่น

    ⚠️ **ไม่ได้ยกขึ้น `_shared.py`** ทั้งที่เส้นที่ 4 ก็มีฟังก์ชันชื่อนี้ — สองตัวนี้
    *ไม่ใช่กฎเดียวกัน* (คนละรายชื่อไฟล์ที่ปฏิเสธ · คนละคำสั่งสร้างใบงานในข้อความ)
    และ `_shared.py` ระบุขอบเขตตัวเองว่าเก็บเฉพาะกฎที่ทุกเส้นเชื่อฟัง **เหมือนกันเป๊ะ**
    """
    others = {
        DEFAULT_MANUAL_CSV.name: ("เส้นที่ 3", "manual_entry.py"),
        DEFAULT_REFERENCE_CSV.name: ("เส้นที่ 4", "reference_entry.py"),
    }
    hit = others.get(path.name)
    if hit is None:
        return
    lane, script = hit
    raise PrecheckError(
        f"--file ชี้ไปที่ {path.name} ซึ่งเป็นใบงานของ **{lane}** ({script})\n"
        "สคริปต์นี้ต้องใช้ใบงานของตัวเอง เพราะ poster_attribute_reviews.source "
        "เก็บชื่อไฟล์ไว้เป็นตัวแยกว่าค่าไหนมาจากรอบไหน (ADR-0014 D28)\n"
        "สร้างด้วย `./venv/bin/python scripts/seed/make_correction_sheet.py`"
    )


def read_sheet(path: Path) -> list[dict[str, str]]:
    if not path.is_file():
        raise PrecheckError(
            f"ไม่พบใบงาน {path}\n"
            "สร้างด้วย `./venv/bin/python scripts/seed/make_correction_sheet.py` ก่อน "
            "แล้วให้คนหยิบใบจริงขึ้นมาตรวจซ้ำและกรอกเอง"
        )
    return read_sheet_rows(
        path,
        required_columns=REQUIRED_COLUMNS,
        sheet_columns=CORRECTION_SHEET_COLUMNS,
        maker_script="make_correction_sheet.py",
        free_text_columns=REASON_COLUMNS,
    )


def parse_rows(raw_rows: list[dict[str, str]]) -> list[CorrectionRow]:
    """ตรวจรูปแบบทุกแถวแล้วคืน `CorrectionRow` — เจอผิดแม้แถวเดียว raise ทั้งไฟล์

    🔴 **pure ล้วน ไม่ต้องมี DB** โดยตั้งใจ — กฎที่แพงที่สุดของเส้นนี้ (A-D2 ข้อ 2:
    ขาด `reason` แม้แถวเดียว = ปฏิเสธทั้งไฟล์) จึงเทสได้โดยตรง · บทเรียนของ
    Amendment 2026-08-07 คือตรรกะที่ซ่อนอยู่ในลูปที่ต้องมี DB **รอดเทส 74 ตัว**

    🔴 **ตรวจทุกฟิลด์ในไฟล์เสมอ ไม่สนใจ `--field`** — `--field` เลือกว่าจะ *เขียน*
    อะไร ไม่ใช่ว่าจะ *ตรวจ* อะไร · ถ้าผูกสองอย่างนี้เข้าด้วยกัน `--field condition_grade`
    จะกลายเป็นทางเลี่ยงด่าน `reason` ของ `is_unique` ในไฟล์เดียวกัน
    """
    specs = field_specs()
    rows: list[CorrectionRow] = []
    errors: list[str] = []
    seen: set[str] = set()

    for lineno, raw in enumerate(raw_rows, start=2):  # +1 header, +1 นับจาก 1
        prefix = f"บรรทัด {lineno}"

        try:
            poster_uuid = uuid.UUID(raw["poster_uuid"])
        except ValueError:
            errors.append(f"{prefix}: poster_uuid {raw['poster_uuid']!r} ไม่ใช่ UUID")
            continue

        if str(poster_uuid) in seen:
            errors.append(
                f"{prefix}: poster_uuid ซ้ำกับแถวก่อนหน้า — ใบงานต้องมีใบละแถวเดียว"
            )
            continue
        seen.add(str(poster_uuid))

        values: dict[str, Any] = {}
        reasons: dict[str, str] = {}
        row_failed = False

        for name, reason_column in zip(WRITABLE_FIELDS, REASON_COLUMNS, strict=True):
            text = raw.get(name, "")
            reason = raw.get(reason_column, "")

            if not text and not reason:
                continue  # ยังไม่ได้ตรวจฟิลด์นี้ — สถานะปกติของใบงานที่ทำไปครึ่งเดียว
            if text and not reason:
                # 🔴 A-D2 ข้อ 2 — นี่คือสิ่งเดียวที่ทำให้ "มีคนรู้เห็น" ต่างจาก "มีคนรัน"
                errors.append(
                    f"{prefix}: {name} = {text!r} แต่ {reason_column} ว่าง — "
                    "เส้นนี้ทับค่าที่ลูกค้าเห็นบนหน้าร้านไปแล้ว เหตุผลจึงบังคับต่อค่า "
                    "(ADR-0010 A-D2 ข้อ 2) · เหตุผลที่ไม่ถูกเก็บ = เหตุผลที่ไม่มี"
                )
                row_failed = True
                continue
            if reason and not text:
                errors.append(
                    f"{prefix}: {reason_column} มีข้อความแต่ {name} ว่าง — "
                    "ข้อมูลขัดกันเอง ไม่ใช่ข้อมูลเพิ่ม · อธิบายการแก้ที่ไม่ได้เกิดขึ้น "
                    "ไม่ได้ · กรอกค่าใหม่ในแถวเดียวกันนี้ หรือลบเหตุผลออก"
                )
                row_failed = True
                continue

            try:
                value = specs[name].parse(text)
            except ValueError as exc:
                errors.append(f"{prefix}: {name} — {exc}")
                row_failed = True
                continue

            policy = refuse_unwritable_value(name, value)
            if policy is not None:
                errors.append(f"{prefix}: {name} = {text!r} — {policy}")
                row_failed = True
                continue

            values[name] = value
            reasons[name] = reason

        if row_failed:
            continue
        rows.append(
            CorrectionRow(
                poster_uuid=poster_uuid,
                values=values,
                reasons=reasons,
                lineno=lineno,
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
class PosterState:
    """สถานะปัจจุบันของใบหนึ่งใน DB — ทุกอย่างที่ `plan_writes()` ต้องรู้."""

    # ค่าปัจจุบันของ `WRITABLE_FIELDS` (ค่าดิบจาก ORM · `condition_grade` เป็น
    # `None` ได้ · `is_unique` เป็น NOT NULL จึงไม่มีวันเป็น `None`)
    values: dict[str, Any]


class RowAction(str, Enum):
    WRITE = "WRITE"
    SKIP_BLANK = "SKIP_BLANK"  # ยังไม่ได้ตรวจ (หรือถูกตัดออกด้วย --field)
    SKIP_SAME = "SKIP_SAME"  # ค่าใหม่เท่าค่าเดิม — ADR-0010 D8
    SKIP_NO_TARGET = "SKIP_NO_TARGET"  # ปลายทางยังว่าง → เส้นนี้แก้ไม่ได้ ไปเส้นที่ 3
    SKIP_NOT_FOUND = "SKIP_NOT_FOUND"  # ไม่มีใบนี้ใน DB — ADR-0015 D5
    # 🔴 **ไม่มี `BLOCKED`** — เคยมีตอนที่ด่าน `is_unique = N` ยังอ่านเกรด (ซึ่งผิด
    # ตาม D5/D6 · ดู `refuse_unwritable_value()`) · วันนี้ทุกกฎของเส้นนี้ตรวจได้จาก
    # ตัวไฟล์อย่างเดียว จึงตายที่ `parse_rows()` ก่อนถึงชั้นนี้เสมอ · การเก็บสถานะ
    # ที่ไม่มีทางเกิดไว้ "เผื่อ" คือโค้ดตายที่อ่านแล้วเข้าใจว่ายังมีทางนั้นอยู่


@dataclass(frozen=True)
class PlannedWrite:
    row: CorrectionRow
    action: RowAction
    # ฟิลด์ที่จะเขียนจริง — ว่างเสมอเมื่อ action ไม่ใช่ WRITE
    field_writes: dict[str, Any]
    # {ชื่อฟิลด์: (ค่าเดิมเป็นข้อความ, ค่าใหม่เป็นข้อความ)} — คีย์ตรงกับ `field_writes`
    # เสมอ เพราะเส้นนี้ **ทับ 100%** ไม่มีการเติมช่องว่าง
    overwrites: dict[str, tuple[str, str]]
    # ฟิลด์ที่กรอกมาแต่ค่าเท่าเดิม → {ชื่อฟิลด์: ค่าเดิมเป็นข้อความ}
    unchanged: dict[str, str]
    # ฟิลด์ที่กรอกมาแต่ปลายทางยังเป็น NULL → เส้นนี้ไม่ใช่เจ้าของงานเติมช่องว่าง
    no_target: tuple[str, ...]
    # ค่าปัจจุบันของทุกคอลัมน์ที่เขียนได้ (ข้อความ) — ใช้ในรายงาน ไม่ใช่ในการตัดสิน
    current: dict[str, str]


def plan_writes(
    rows: list[CorrectionRow],
    current: dict[uuid.UUID, PosterState],
    fields: tuple[str, ...] = WRITABLE_FIELDS,
) -> list[PlannedWrite]:
    """แถวใบงาน + สถานะปัจจุบันของ DB → แผนการเขียน

    `current` = {poster_id: PosterState} · ใบที่ไม่มีใน dict ถือว่าไม่มีในฐานข้อมูล
    → **ข้าม ไม่ใช่ INSERT** (ADR-0015 D5 ตกทอดมาทั้งดุ้น)

    pure function — ไม่ query ไม่เขียน ไม่แตะเวลาปัจจุบัน

    🔴 **`condition_grade` ที่ปลายทางเป็น `NULL` ถูกข้าม *เฉพาะฟิลด์นั้น*** ไม่ใช่ทั้งแถว
    — นี่คือกลไกที่ทำให้ AC-4 (`value_before` ห้ามเป็น `NULL`) จริง **โดยโครงสร้าง**
    ไม่ใช่โดยข้อตกลง: ฟิลด์เดียวที่เป็น `NULL` ได้ถูกกันออกตั้งแต่ตอนวางแผน ส่วน
    `is_unique` เป็น `NOT NULL` จึงมีค่าเดิมเสมอ · การข้ามทั้งแถวจะทำให้ใบที่ยังไม่มี
    เกรดแก้ `is_unique` ไม่ได้เลย ทั้งที่ `is_unique` ไม่ได้ขึ้นกับเกรดเลยสักนิด

    🔴 **ชั้นนี้ไม่มีด่านปฏิเสธของตัวเองแม้แต่ข้อเดียว** — ทุกกฎของเส้นนี้ตรวจได้จาก
    ตัวไฟล์อย่างเดียว จึงตายที่ `parse_rows()` ก่อนเปิด session · ค่าที่มาถึงที่นี่
    ผ่าน `refuse_unwritable_value()` มาแล้ว ⇒ `row.values["is_unique"]` เป็น `True`
    เสมอ ซึ่งเป็นเหตุผลที่ `rows_still_marked_as_multi_piece()` **พิสูจน์ได้**ว่า
    แถวที่ยังเป็น `false` ไม่ได้เกิดจากรอบนี้
    """
    plans: list[PlannedWrite] = []
    for row in rows:
        state = current.get(row.poster_uuid)
        if state is None:
            plans.append(
                PlannedWrite(
                    row=row,
                    action=RowAction.SKIP_NOT_FOUND,
                    field_writes={},
                    overwrites={},
                    unchanged={},
                    no_target=(),
                    current={},
                )
            )
            continue

        rendered_current = {
            name: render_value(state.values.get(name)) for name in WRITABLE_FIELDS
        }
        field_writes: dict[str, Any] = {}
        overwrites: dict[str, tuple[str, str]] = {}
        unchanged: dict[str, str] = {}
        no_target: list[str] = []

        for name in WRITABLE_FIELDS:
            if name not in fields or name not in row.values:
                continue
            current_value = state.values.get(name)
            if current_value is None:
                no_target.append(name)
                continue
            before = rendered_current[name]
            after = render_value(row.values[name])
            if before == after:
                # ADR-0010 D8 — ค่าเท่าเดิมไม่ใช่การเขียน · นับเป็น write เมื่อไหร่
                # ได้ audit ปลอมที่บอกว่ามีคนแก้ทั้งที่ไม่มีอะไรเปลี่ยน
                unchanged[name] = before
                continue
            field_writes[name] = row.values[name]
            overwrites[name] = (before, after)

        if field_writes:
            action = RowAction.WRITE
        elif no_target:
            action = RowAction.SKIP_NO_TARGET
        elif unchanged:
            action = RowAction.SKIP_SAME
        else:
            action = RowAction.SKIP_BLANK

        plans.append(
            PlannedWrite(
                row=row,
                action=action,
                field_writes=field_writes,
                overwrites=overwrites,
                unchanged=unchanged,
                no_target=tuple(no_target),
                current=rendered_current,
            )
        )
    return plans


def planned_field_counts(plans: list[PlannedWrite]) -> dict[str, int]:
    """จำนวนค่าที่จะถูก**ทับ** แยกทีละคอลัมน์ — ตัวเลขที่คนต้องยืนยันก่อน `--commit`

    ⚠️ **ตัวเลขชุดนี้เทียบกับ `count(<column>)` ไม่ได้** ต่างจากเส้นอื่น — ดู
    §ทำไมไม่มี `_report_counts()` ใน docstring ของโมดูล
    """
    counts = dict.fromkeys(WRITABLE_FIELDS, 0)
    for plan in plans:
        for name in plan.field_writes:
            counts[name] += 1
    return counts


@dataclass(frozen=True)
class AuditEntry:
    """หนึ่งแถวที่จะลง `poster_attribute_reviews` — ADR-0010 D3 + **A-D2 ข้อ 3/4**

    `value_before` ประกาศเป็น `str` **ไม่ใช่ `str | None`** โดยตั้งใจ: เส้นนี้ทับ 100%
    ของการเขียน `None` จึงผิดเสมอ ไม่ใช่ "ยังไม่มีค่า"
    """

    field: str
    value_before: str
    value_after: str
    reason: str


def audit_entries(plan: PlannedWrite) -> tuple[AuditEntry, ...]:
    """แถว audit ของใบหนึ่ง — **หนึ่งแถวต่อหนึ่งค่าที่ทับจริง** (pure ไม่แตะ session)

    🔴 **ต้องเป็นฟังก์ชัน pure ไม่ใช่โค้ดในลูปของ `run()`** — ตรรกะเดียวกันนี้เคยอยู่
    ในลูปที่ต้องมี DB ถึงจะรันได้ แล้ว mutation ที่เปลี่ยนให้ `value_before=None` เสมอ
    **รอดเทสทั้ง 74 ตัว** เมื่อ 2026-08-07 ทั้งที่ ADR บังคับเรื่องนี้ตรง ๆ
    (ADR-0010 §บทเรียนจาก mutation ที่รอด · AC-8 ข้อ 1 สั่งห้ามให้ซ้ำรอย)

    `overwrites` กับ `reasons` การันตีว่ามีคีย์ครบเสมอ: `field_writes` มาจาก
    `row.values` และ `parse_rows()` ปฏิเสธทั้งไฟล์เมื่อค่าใดไม่มีเหตุผลคู่กัน
    """
    return tuple(
        AuditEntry(
            field=name,
            value_before=before,
            value_after=after,
            reason=plan.row.reasons[name],
        )
        for name, (before, after) in plan.overwrites.items()
    )


def verify_corrections(
    plans: list[PlannedWrite],
    after_state: dict[uuid.UUID, PosterState],
) -> list[str]:
    """อ่านค่ากลับมาเทียบกับค่าที่ตั้งใจเขียน — pure (รับสถานะหลัง commit เข้ามา)

    🔴 **นี่คือ assert ตัวเดียวที่เส้นนี้มี** — ดู §ทำไมไม่มี `_report_counts()`
    """
    problems: list[str] = []
    for plan in plans:
        if not plan.overwrites:
            continue
        state = after_state.get(plan.row.poster_uuid)
        if state is None:
            problems.append(f"บรรทัด {plan.row.lineno}: อ่านใบกลับมาไม่เจอหลัง commit")
            continue
        for name, (before, after) in plan.overwrites.items():
            actual = render_value(state.values.get(name))
            if actual != after:
                problems.append(
                    f"บรรทัด {plan.row.lineno}: {name} ควรเป็น {after!r} "
                    f"แต่อ่านกลับมาได้ {actual!r} (ค่าเดิมคือ {before!r})"
                )
    return problems


def rows_still_marked_as_multi_piece(plans: list[PlannedWrite]) -> tuple[int, ...]:
    """แถวที่ **จะยังเป็น `is_unique = false` หลังรอบนี้** → ทูเพิลของเลขบรรทัด

    🔴 **warning เท่านั้น ห้ามทำเป็นด่านปฏิเสธ** — สภาพนี้มีอยู่ใน DB ก่อนสคริปต์นี้
    เกิด (ADR-0019 §Context) ด่านปฏิเสธจะปฏิเสธใบงานที่ถูกต้องตั้งแต่รันครั้งแรก และ
    ปิดทางเดียวที่มีอยู่ในการ **แก้** สภาพนั้น · การพาแถวพวกนี้ให้ถูกต้องคือการแตกแถว
    ซึ่งเป็นงานของ **INF-22** ไม่ใช่ของสคริปต์นี้

    🔴 **ไม่ดูเกรดเลย และนั่นคือความถูกต้องไม่ใช่ความมักง่าย** ‹แก้หลัง code-critic
    รอบที่ 1› — รุ่นแรกอ่าน `plan.overwrites["condition_grade"][1]` (เกรด*ใหม่*ที่รอบนี้
    กำลังจะเขียน) แล้วพิมพ์ว่า *"เป็นสภาพที่มีมาก่อน"* ซึ่งเป็นการยืนยันสาเหตุที่ตัวเอง
    ไม่รู้ · หลัง **D5** (แม้ `mint` ก็ 1 แถว 1 ชิ้น) เกรดไม่เกี่ยวกับความถูกผิดของ
    `is_unique` อีกต่อไป — `false` ผิดทุกเกรด คำถามเดียวที่เหลือคือ *ยังเป็น false ไหม*

    ✅ **คำว่า "มีมาก่อน" พิสูจน์ได้ ไม่ใช่คำอ้าง** — `refuse_unwritable_value()`
    ปฏิเสธ `N` ทุกกรณีตั้งแต่ `parse_rows()` ⇒ เส้นนี้เขียน `false` ไม่ได้เลย ⇒ แถวที่
    เป็น `false` ต้องเป็น `false` อยู่ก่อนแล้วเสมอ · และแถวที่รอบนี้กำลังแก้เป็น `true`
    ถูกตัดออกจากรายการ เพราะหลังรอบนี้มันจะไม่ใช่ `false` อีก
    """
    return tuple(
        plan.row.lineno
        for plan in plans
        if plan.action is not RowAction.SKIP_NOT_FOUND
        and plan.current.get("is_unique") == render_value(False)
        and "is_unique" not in plan.field_writes
    )


def assert_schema_ready(missing_columns: list[str], has_reason_column: bool) -> None:
    """ปลายทางต้องมี schema ครบก่อนเขียน — pure เพื่อให้ test ครอบได้โดยไม่ต้องมี DB

    อาการเดียวกับ `manual_entry.assert_schema_ready()`: รันในคอนเทนเนอร์ที่ image เก่า
    → model ไม่มีแอตทริบิวต์ · รันบน host แต่ DB ปลายทางยังไม่ migrate → คอลัมน์หายไป

    🔴 **`poster_attribute_reviews.reason` ต้องมีอยู่ *ที่ปลายทาง*** ไม่ใช่แค่ในไฟล์
    model — ถ้าไม่มี การเขียนจะล้มตอน INSERT (หรือแย่กว่านั้นคือเงียบไปถ้าใครเผลอ
    ทำให้มันไม่ล้ม) แล้วเราจะได้ audit ที่ **บอกว่าใครแก้อะไร แต่ตอบไม่ได้ว่าทำไม**
    ซึ่งลบเหตุผลทั้งหมดที่เส้นนี้มีอยู่ (A-D2 ข้อ 2/3)
    """
    if missing_columns:
        raise PrecheckError(
            "ปลายทางไม่มีคอลัมน์: " + ", ".join(missing_columns) + "\n"
            "แปลว่า **ปลายทางตามหลัง develop อยู่** — ถ้ารันในคอนเทนเนอร์คือ image เก่า "
            "(ต้อง build/pull ใหม่) ถ้ารันบน host คือ DB ยังไม่ `alembic upgrade head`"
        )
    if not has_reason_column:
        raise PrecheckError(
            "ปลายทางไม่มีคอลัมน์ `poster_attribute_reviews.reason` "
            "(migration ของ ADR-0010 Amendment 2026-08-09 · INF-21)\n"
            "เส้นนี้บังคับเหตุผลต่อค่า — ถ้าปลายทางไม่มีที่เก็บ สิ่งที่ได้คือ audit ที่ "
            "บอกว่าใครแก้อะไร แต่ตอบไม่ได้ว่าทำไม ซึ่งคือทั้งหมดที่เส้นนี้มีไว้เพื่อ\n"
            "`alembic upgrade head` ที่ปลายทางก่อน แล้วรันใหม่"
        )


# --------------------------------------------------------------------------
# รายงาน
# --------------------------------------------------------------------------


def _report(
    plans: list[PlannedWrite],
    target_label: str,
    fields: tuple[str, ...],
    committed: bool,
) -> None:
    planned = planned_field_counts(plans)
    by_action = {action: 0 for action in RowAction}
    for plan in plans:
        by_action[plan.action] += 1
    total = sum(planned.values())

    print()
    print("=" * 72)
    print(f"ปลายทาง : {target_label}")
    print(f"แถวในใบงาน : {len(plans)}")
    print(f"ฟิลด์ที่เปิดในรอบนี้ : {' · '.join(fields)}  [--field]")
    print()
    print("แยกทีละคอลัมน์ (ทับค่าเดิมทั้งหมด — เส้นนี้ไม่เติมช่องว่าง):")
    print(f"  {'คอลัมน์':<24} {'จะทับ':>8}")
    for name in WRITABLE_FIELDS:
        print(f"  {name:<24} {planned[name]:>8}")

    print()
    print("แยกตามผลของแถว:")
    print(f"  จะทับ                            : {by_action[RowAction.WRITE]}")
    print(f"  ข้าม — ยังไม่ได้กรอก              : {by_action[RowAction.SKIP_BLANK]}")
    print(
        f"  ข้าม — ค่าใหม่เท่าค่าเดิม          : {by_action[RowAction.SKIP_SAME]}"
        "  (ADR-0010 D8 — ไม่ใช่การเขียน)"
    )
    print(
        f"  ข้าม — ปลายทางยังว่าง             : "
        f"{by_action[RowAction.SKIP_NO_TARGET]}  (เส้นนี้แก้ ไม่ใช่เติม → เส้นที่ 3)"
    )
    print(
        f"  ข้าม — ไม่มีใบนี้ใน DB            : "
        f"{by_action[RowAction.SKIP_NOT_FOUND]}  (UPDATE เท่านั้น ไม่ INSERT)"
    )

    writing = [p for p in plans if p.overwrites]
    if writing:
        print()
        print(
            f"🔴 จะทับค่าเดิม {total} ค่า ใน {len(writing)} ใบ — "
            "ทุกค่าที่นี่มีคนเห็นบนหน้าร้านไปแล้ว:"
        )
        for plan in writing:
            for name, (before, after) in plan.overwrites.items():
                print(
                    f"  บรรทัด {plan.row.lineno:>4}  {name:<16} "
                    f"{before!r} → {after!r}"
                )
                print(f"                เหตุผล: {plan.row.reasons[name]}")
        print(
            "  ↑ ค่าเดิมและเหตุผลทุกบรรทัดถูกบันทึกลง poster_attribute_reviews "
            "(value_before · reason)"
        )

    no_target = [p for p in plans if p.no_target]
    if no_target:
        print()
        print("ใบที่ปลายทางยังว่าง — เส้นนี้เขียนไม่ได้ (แก้ ไม่ใช่เติม):")
        for plan in no_target:
            print(
                f"  บรรทัด {plan.row.lineno:>4}  {' · '.join(plan.no_target)} "
                "— ใช้ `manual_entry.py` (เส้นที่ 3) แทน"
            )

    unchanged = [p for p in plans if p.unchanged]
    if unchanged:
        print()
        print("ใบที่กรอกมาแต่ค่าเท่าเดิม — ไม่มีแถว audit (ADR-0010 D8):")
        for plan in unchanged:
            shown = " · ".join(f"{k}={v!r}" for k, v in plan.unchanged.items())
            print(f"  บรรทัด {plan.row.lineno:>4}  {shown}")

    stale = rows_still_marked_as_multi_piece(plans)
    if stale:
        print()
        # 🔴 ขอบเขตของตัวเลขต้องอยู่ **ในประโยคเดียวกับตัวเลข** — เลขนี้นับเฉพาะแถว
        # ที่อยู่ในใบงานที่รันรอบนี้ ส่วน BACKLOG §0 กับ ADR-0019 นับทั้งร้าน สองเลข
        # จึงไม่เท่ากันได้โดยที่ทั้งคู่ถูก (ใบที่ไม่มีเกรดหลุดตัวกรองปริยายของใบงาน
        # เช่นกรอบไฟ BL-82) · เลขลอย ๆ ที่ต้องพึ่งคนจำว่ามันนับอะไร อ่านผิดเมื่อไหร่
        # ก็ได้ และคนที่อ่านผิดจะคิดว่าตัวเลขในทะเบียนผิด
        print(
            f"⚠️  {len(stale)} แถวในใบงานนี้จะยังเป็น is_unique=false หลังรอบนี้ "
            "— **ไม่ใช่ error และรอบนี้ไม่ได้ทำให้เกิด**"
        )
        print(
            "   เส้นนี้เขียน is_unique=false ไม่ได้เลย (ADR-0019 D5/D6 — ด่านอยู่ที่ "
            "parse_rows) ค่าพวกนี้จึงมีมาก่อนเสมอ พิสูจน์ได้ ไม่ใช่คำอ้าง"
        )
        print(
            "   นับเฉพาะแถวในใบงานนี้ — ทั้งร้านมีได้มากกว่านี้ (ใบที่ยังไม่มีเกรด "
            "ไม่เข้าใบงานปริยาย ต้อง --all)"
        )
        print("   การพาให้ถูกต้องคือการแตกแถว = INF-22 (ADR-0019 D8)")
        print(f"   บรรทัด: {', '.join(str(n) for n in stale)}")

    print()
    print(
        "เขียนเฉพาะ " + " · ".join(WRITABLE_FIELDS) + " — ไม่แตะคอลัมน์อื่นของ posters"
    )
    print("ไม่แตะ needs_review · status · published_at เลยสักแถว")
    print("ไม่อ่าน current_* / title / image_url — เป็นข้อมูลให้คนอ่านอย่างเดียว")
    if not committed:
        print()
        print("DRY-RUN — ไม่ได้เขียนอะไรลง database (ใส่ --commit เพื่อเขียนจริง)")
        print(
            f"🔴 ยืนยันตัวเลข {total} ค่าข้างบนก่อนใส่ --commit (ADR-0010 A-D2 ข้อ 5)"
        )
    print("=" * 72)

    if not committed:
        specs = field_specs()
        print("\nค่าที่รับได้:")
        for name in WRITABLE_FIELDS:
            print(f"  {name:<20} {specs[name].hint}")


# --------------------------------------------------------------------------
# ตัวรัน
# --------------------------------------------------------------------------


async def _load_state(session: Any, poster_ids: list[uuid.UUID]) -> dict:
    from sqlalchemy import select

    from app.models.poster import Poster

    result = await session.execute(
        select(Poster.id, *[getattr(Poster, n) for n in WRITABLE_FIELDS]).where(
            Poster.id.in_(poster_ids)
        )
    )
    state: dict[uuid.UUID, PosterState] = {}
    for row in result.all():
        poster_id, *rest = row
        state[poster_id] = PosterState(
            values=dict(zip(WRITABLE_FIELDS, rest, strict=True))
        )
    return state


async def _check_schema(session: Any) -> None:
    from sqlalchemy import text

    from app.models.poster import Poster
    from app.models.poster_attribute_review import PosterAttributeReview

    missing = [n for n in WRITABLE_FIELDS if not hasattr(Poster, n)]
    has_reason = hasattr(PosterAttributeReview, "reason")
    if has_reason:
        has_reason = bool(
            await session.scalar(
                text(
                    # 🔴 `table_schema` ห้ามหาย — ชื่อตารางไม่ unique ข้าม schema
                    # การละไว้แปลว่าตารางชื่อเดียวกันใน schema อื่นตอบแทนได้
                    "SELECT 1 FROM information_schema.columns "
                    "WHERE table_schema = current_schema() "
                    "AND table_name = :table AND column_name = :column"
                ),
                {"table": PosterAttributeReview.__tablename__, "column": "reason"},
            )
        )
    assert_schema_ready(missing, has_reason)


async def run(args: argparse.Namespace, target_label: str) -> int:
    from app.core.database import async_session_maker
    from app.models.poster import Poster
    from app.models.poster_attribute_review import PosterAttributeReview

    assert_own_sheet(args.file)
    fields = tuple(dict.fromkeys(args.field)) or WRITABLE_FIELDS

    rows = parse_rows(read_sheet(args.file))
    if not rows:
        print("ใบงานไม่มีแถวข้อมูล — ไม่มีอะไรให้ทำ")
        return 0

    async with async_session_maker() as session:
        await _check_schema(session)
        current = await _load_state(session, [r.poster_uuid for r in rows])
        plans = plan_writes(rows, current, fields)

        _report(plans, target_label, fields, committed=args.commit)
        if not args.commit:
            return 0

        source = args.file.name
        written = 0

        for plan in plans:
            if plan.action is not RowAction.WRITE:
                continue
            poster = await session.get(Poster, plan.row.poster_uuid)
            if poster is None:  # pragma: no cover — plan บอกว่ามีแล้ว
                continue

            for name, value in plan.field_writes.items():
                if name not in WRITABLE_FIELDS:  # pragma: no cover — fail-closed
                    raise PrecheckError(
                        f"พยายามเขียนคอลัมน์ {name!r} ซึ่งไม่อยู่ใน WRITABLE_FIELDS"
                    )
                setattr(poster, name, value)
            for entry in audit_entries(plan):
                session.add(
                    PosterAttributeReview(
                        poster_id=plan.row.poster_uuid,
                        field=entry.field,
                        value_before=entry.value_before,
                        value_after=entry.value_after,
                        reason=entry.reason,
                        reviewed_by=args.reviewed_by,
                        reviewed_at=args.reviewed_at,
                        source=source,
                    )
                )
                written += 1

        await session.commit()
        # A-D2 ข้อ 5 — การทับไม่ทำให้ count() ขยับ ต้องอ่านค่ากลับมาเทียบเอง
        problems = verify_corrections(
            plans, await _load_state(session, [p.row.poster_uuid for p in plans])
        )

    print(
        f"\nทับค่าเดิมแล้ว {written} ค่า · "
        f"บันทึก audit {written} แถวลง poster_attribute_reviews (มี reason ครบทุกแถว)"
    )
    if problems:
        print("\n🔴 การทับไม่ลงตามแผน — commit ไปแล้ว ต้องตรวจด้วยมือ:")
        for problem in problems:
            print(f"  {problem}")
        return 1
    print("ตรวจซ้ำด้วยการอ่านค่ากลับมาเทียบแล้ว — ตรงทุกค่า")
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
        "--field",
        action="append",
        default=[],
        choices=WRITABLE_FIELDS,
        metavar="FIELD",
        help=(
            "จำกัดรอบนี้ให้ทับเฉพาะฟิลด์ที่ระบุ — ระบุซ้ำได้หลายครั้ง · "
            f"รับได้เฉพาะ {' · '.join(WRITABLE_FIELDS)} · "
            "ไม่ใส่ = ทั้งสองฟิลด์ · **ไม่มีรูปแบบที่แปลว่า 'ทุกฟิลด์' แบบเปิดกว้าง** "
            "โดยเจตนา (ADR-0010 A-D2 ข้อ 6) · ไม่ว่าจะระบุอะไร ด่าน reason ยังตรวจ"
            "ทั้งไฟล์เสมอ"
        ),
    )
    parser.add_argument(
        "--file",
        type=Path,
        default=DEFAULT_CORRECTION_CSV,
        help=f"ใบงาน (default: {DEFAULT_CORRECTION_CSV.name})",
    )
    parser.add_argument(
        "--target",
        choices=TARGETS,
        default="dev",
        help="ปลายทาง — เหมือนเส้นที่ 3/4 ทุกประการ (ADR-0015 D8: dev กับ sit เท่านั้น "
        "production ไม่มีให้เลือกโดยตั้งใจ) · sit ต้องรันข้างในคอนเทนเนอร์ sit "
        f"และ DATABASE_URL ต้องตรงกับ {SIT_ENV_FILE} เป๊ะ",
    )
    parser.add_argument(
        "--reviewed-by",
        help="ชื่อคนที่ตรวจซ้ำแล้วตัดสินว่าค่าเดิมผิด — บังคับเมื่อ --commit (ADR-0010 D1)",
    )
    parser.add_argument(
        "--reviewed-at",
        metavar="<เวลาที่คุณตัดสิน ISO-8601 พร้อม timezone>",
        help="บังคับเมื่อ --commit · 🔴 ไม่มี default เป็นเวลาปัจจุบัน (ADR-0010 D5) "
        "และค่าที่อยู่ในอนาคตถูกปฏิเสธ (เวลาที่คนตัดสินย้อนไปข้างหน้าไม่ได้)",
    )
    args = parser.parse_args()

    if args.commit:
        if not args.reviewed_by:
            parser.error("--commit ต้องระบุ --reviewed-by ด้วย (ADR-0010 D1)")
        if not args.reviewed_at:
            parser.error("--commit ต้องระบุ --reviewed-at ด้วย (ADR-0010 D5)")
        try:
            args.reviewed_at = _parse_reviewed_at(args.reviewed_at)
            # 🔴 จุดเดียวในโมดูลที่อ่านนาฬิกา — และอ่านเพื่อ **ปฏิเสธ** เท่านั้น
            # ไม่เคยถูกใช้เป็นค่าให้ `args.reviewed_at` (ADR-0010 D5 · มีเทส AST ล็อก)
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
                "    exec app python scripts/seed/correction_entry.py --target sit"
            )
        print(
            f"ต่อ database ไม่ได้ (target={args.target}): {exc}{hint}", file=sys.stderr
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
