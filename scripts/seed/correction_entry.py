"""แก้ค่าที่ **มีคนเห็นบนหน้าร้านไปแล้ว** — ADR-0010 Amendment 2026-08-09 (INF-21)
· เซ็นรับว่าตรวจแล้ว + ถอนของออกจากชั้น — ADR-0027 (INF-29)

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
ต่อค่า และเป็นเส้นเดียวที่ `value_before` **ห้ามเป็น NULL** — ยกเว้นค่าเดียวในระบบ
คือการเซ็นรับครั้งแรกของ `verified_at` (ดู §เซ็นรับ · AC-7 ของ INF-29)

## เขียนได้ 4 คอลัมน์ ไม่มีคอลัมน์อื่นเลย (ADR-0010 A-D2 ข้อ 6 · ADR-0027 D7)

| คอลัมน์ | โหมด | ทำไมอยู่ที่นี่ |
|---|---|---|
| `condition_grade` | ค่า (VALUE) | **BR-05** — ลูกค้าใช้ตัดสินใจซื้อ · ADR-0010 D8 ห้ามทับผ่านเส้นที่ 3 ตลอดกาล |
| `is_unique` | ค่า (VALUE) | ปลายทางคือ *จำนวนของที่ขายได้* ผิดแล้วจบที่ ADR-0002 เหมือนกัน (**A-D1**) |
| `verified_at` | คำสั่ง (COMMAND) | เซ็นรับว่าตรวจครบทุกมิติแล้ว (ADR-0027 D1 · D3) — เขียนได้ทางเดียวคือ `SIGN` |
| `published_at` | คำสั่ง (COMMAND) | ถอนของออกจากชั้น (ADR-0013 D6 เปิดสิทธิ์ไว้ก่อน · ADR-0027 D7 สร้าง writer) — เขียนได้ทางเดียวคือ `WITHDRAW` |

🔴 **`--allow-overwrite` ของเส้นที่ 3 ไม่เปลี่ยนเลย** — ยังเป็น `title` · `year`
เท่านั้น (**A-D4** ข้อ 3) · เหตุผลที่ไม่ขยายมันแทนการสร้างเส้นนี้อยู่ที่ **A-D3**:
flag ตัวเดียวบน CLI บังคับให้มี *หลักฐานว่ามีคนไปดูของจริงมาแล้ว* ไม่ได้

## สองคอลัมน์คำสั่ง (COMMAND) — "อ่านออก" กับ "เขียนได้" เป็นคนละเรื่อง (ADR-0027 §AC-2)

| ช่อง | อ่านออก | เขียนได้ | ผล |
|---|---|---|---|
| `verified_at` | `SIGN` · `KEEP` · `UNSIGN` | **`SIGN` เท่านั้น** | `verified_at := <--reviewed-at>` |
| `published_at` | `WITHDRAW` · `KEEP` · `PUBLISH` | **`WITHDRAW` เท่านั้น** | `published_at := NULL` |

`KEEP` = คำที่แปลว่า *ไม่ทำอะไร* ของทั้งสองช่อง (คำเดียว ไม่ใช่คนละคำ — ADR-0027 D7)
· `UNSIGN` (ไม่มีสถานะ "ตรวจแล้วไม่ผ่าน" — แก้ค่าแล้วเซ็นใหม่แทน) และ `PUBLISH`
(การ *เปิด* ขายเป็นของเส้นที่ 3 ที่เดียว) **อ่านออกแต่เขียนไม่ได้** · ทั้งสองช่องพิมพ์
`KEEP` ในคอลัมน์ช่วยจำ `current_verified_at`/`current_published_at` เมื่อมีค่าอยู่แล้ว
และพิมพ์ว่างเมื่อเป็น NULL — **ห้ามพิมพ์วันที่จริงลงใบงานเด็ดขาด**

ค่าที่ลงจริงของ `verified_at` = **`args.reviewed_at`** (เวลาที่คนตัดสิน ไม่ใช่นาฬิกา
ตอนรัน) — ทรงเดียวกับ `--reviewed-at` ที่เส้นที่ 3 ใช้เป็น `published_at` · **ไม่มี
`--verified-at` แยก** เพราะสองเวลาต่อการตัดสินหนึ่งครั้งคือสองความจริงที่ต่างกันได้
โดยไม่มีใครรู้ (ADR-0027 D7)

## นโยบายความสด (ADR-0027 D6) — แก้เกรด/จำนวน = ลายเซ็นหายอัตโนมัติในธุรกรรมเดียวกัน

เขียน `condition_grade`/`is_unique` **จริง** (ไม่ใช่ `SKIP_SAME`) ⇒ `verified_at`
และ `published_at` ถูกล้างเป็น `NULL` **ในธุรกรรมเดียวกัน** เสมอ · แถวหลุดจากร้าน
ทันทีจนกว่าจะมีคนตรวจและเซ็นใหม่ · 🔴 **cascade นี้ไม่ฟัง `--field`** — `--field
condition_grade` ยังล้างลายเซ็นเหมือนเดิม ไม่งั้นแฟล็กนั้นจะกลายเป็นทางเลี่ยง D6
· ถ้าแถวเดียวกันสั่ง `SIGN` ด้วย ลายเซ็นใหม่ (`args.reviewed_at`) จะ **ทับผลของ
cascade** — คนตรวจของจริงแล้วเซ็นโดยรู้ว่าตัวเองเพิ่งแก้อะไรไม่ใช่ลายเซ็นที่โกหก

## 🔴 ปฏิเสธทั้งไฟล์เมื่อมีแถวใดสั่งเขียนอะไรก็ตามลงใบที่ `status = 'sold'` (ADR-0027 A-D11)

**กว้างกว่าการห้ามเฉพาะ `WITHDRAW`** — เพราะ cascade ของ D6 ถอนแถวออกจากร้านให้เอง
เมื่อแก้เกรด/จำนวน แม้คนกรอกไม่ได้สั่งถอนเลยสักช่อง ผลคือ `get_poster_detail()`
ตอบ 404 แทน 200 (ผิด ADR-0013 D6 · ADR-0005 D5 · SCR-05 AC-5) · ด่านนี้อยู่ **ชั้นที่
รู้ `status`** (หลัง `_load_state()` ก่อนการเขียนครั้งแรกทุกกรณี ทั้ง dry-run และ
`--commit`) เพราะ `status` **ไม่มีในใบงานและต้องไม่มี** — ค่าที่คนพิมพ์เองได้คือค่า
ที่ปลอมได้ · 🔴 **ผลที่ยอมรับ: การแก้เกรดของใบที่ขายแล้วไม่มีเครื่องมือรองรับ**

## 🔴 ด่านก่อนเซ็น — `verified_at` ต้องไม่กลายเป็นตรายาง (ADR-0027 D3)

เขียน `verified_at` ไม่ได้ถ้าเครื่องตรวจ**ส่วนที่ตรวจได้เอง**แล้วไม่ผ่าน — เรียก
`poster_service.publish_blockers()` ตัวเดียวกับที่เส้นที่ 3 ใช้ (ตัด `NOT_VERIFIED`
ออกเพราะเป็นสิ่งที่กำลังจะแก้พอดี) ด้วย `PublishReadiness` ที่ประกอบจากค่า **หลังรอบนี้**
(ไม่ใช่ค่าใน DB เฉย ๆ — กันไม่ให้ใบที่กรอกเกรดกับ `SIGN` ในแถวเดียวกันติดลูป) ·
`count_actual` **อ่านข้ามไฟล์จาก `manual-entry.csv`** ผ่าน
`manual_entry.load_count_actual_by_poster()` (ตัวเดียวกับเส้นที่ 6) เฉพาะตอนมีแถว
ที่สั่ง `SIGN` เท่านั้น — ไม่พบไฟล์ = precheck พัง · มีไฟล์แต่ไม่มีค่า = `UNKNOWN_COUNT`
= ปฏิเสธทั้งไฟล์ (fail-closed ตาม ADR-0027 D5) · ด่านนี้อยู่ที่เดียวกับด่าน sold —
ปฏิเสธทั้งไฟล์ ไม่ใช่ข้ามรายแถว

## แถวไหนถูกข้าม แถวไหนทำทั้งไฟล์พัง

**ข้ามเฉย ๆ (ปกติ ไม่ใช่ error):** เว้นว่างทั้งคู่ · สั่ง `KEEP` (ไม่ว่าจะมีเหตุผลติด
มาด้วยหรือไม่ — ADR-0027 D7 ความหมายเดียวกับเว้นว่างทั้งคู่ พาร์เซอร์อ่านออกแล้ว
`parse_rows()` ปฏิบัติเหมือนไม่ได้กรอกอะไรทันที) · ค่าใหม่เท่ากับค่าเดิม
(ADR-0010 D8 — *ค่าเท่าเดิม = ไม่ใช่การเขียน* ไม่งั้นได้ audit ปลอมและเลิก idempotent) ·
ใบไม่มีใน DB (UPDATE เท่านั้น ไม่ INSERT — ADR-0015 D5) · **`condition_grade`
ปลายทางเป็น `NULL`** (เส้นนี้ *แก้* ไม่ใช่ *เติม* → ไปใช้เส้นที่ 3) · **`WITHDRAW` บน
ใบที่ยังไม่ publish** (ไม่มีอะไรให้ถอน → ไปใช้เส้นที่ 3 เพื่อเปิดขาย)

**ทั้งไฟล์ถูกปฏิเสธ ไม่เขียนอะไรเลย (fail-closed):** `poster_uuid` ไม่ใช่ UUID ·
`poster_uuid` ซ้ำ · **กรอกค่าแต่ไม่กรอกเหตุผลของฟิลด์นั้น** (A-D2 ข้อ 2 — ยกเว้น
`KEEP` ซึ่งไม่ต้องมีเหตุผลเลยเพราะไม่มีการเขียนให้เหตุผลอธิบาย) ·
**กรอกเหตุผลแต่ไม่กรอกค่า** (ข้อมูลขัดกันเอง) · `condition_grade` ตัวพิมพ์ไม่ตรง ·
`is_unique` อ่านไม่ออก (ไม่ใช่ `Y`/`N`) · **`is_unique = N` ทุกกรณีไม่มีข้อยกเว้น** ·
`verified_at`/`published_at` อ่านไม่ออก หรืออ่านออกแต่เขียนไม่ได้ (`UNSIGN`/
`PUBLISH` — **ไม่ใช่** `KEEP` ซึ่งเขียนได้ในความหมายว่าไม่ทำอะไร) ·
**มีแถวใดสั่งเขียนอะไรก็ตามลงใบที่ `sold`** (ADR-0027 A-D11) ·
**สั่ง `SIGN` บนใบที่เครื่องตรวจแล้วไม่ผ่าน** (ADR-0027 D3) ·
**สั่ง `SIGN` แต่ไม่มี `--reviewed-at`** (ไม่ว่าโหมดไหน — ด่านนี้เดิมมีแค่ตอน
`--commit` ผ่าน `parser.error()` เท่านั้น ทำให้ dry-run รายงานผิดเป็น
`SKIP_SAME` — code-critic รอบ 1 ของ INF-29)

## 🔴 `is_unique = N` เขียนไม่ได้เลยในระบบวันนี้ — และนั่นไม่ใช่ข้อจำกัดชั่วคราวของสคริปต์

**ADR-0019 D6** เขียนหัวข้อของตัวเองว่า *"หลัง D1 `is_unique` ต้องเป็น `true` **ทุกแถว**"*
และ **D5** ปิดท้ายมติว่า *"จนถึงตอนนั้น **แม้ใบ `mint` ก็เก็บเป็น 1 แถว 1 ชิ้น** — D1 คือ
สิทธิ์ที่ยังไม่มีเครื่องมือรองรับ ไม่ใช่สิ่งที่ทำได้พรุ่งนี้"* · เหตุผลอยู่ในโค้ดจริง
ไม่ใช่ความกังวล: `posters.status` เป็นสถานะของ **แถว** · reservation ผูกกับ `poster_id`
ไม่ใช่กับชิ้น · และ `uq_active_reservation_per_poster` ปฏิเสธ active reservation ที่สอง
ของแถวเดียวกัน**ที่ระดับ DB** ⇒ แถวที่แทนของ 3 ชิ้นขายได้จริงชิ้นเดียว

⚠️ **"อ่านไม่ออก" กับ "อ่านออกแต่ห้าม" เป็นคนละเรื่องและแยกกันในโค้ด** —
`parse_is_unique()` ยัง parse `N` เป็น `False` ได้ตามปกติ (มันไม่ใช่ค่ากำกวม)
ส่วนด่านนโยบายอยู่ที่ `parse_rows()` และบอกเหตุผลเป็นคนละข้อความกัน · หลักการเดียวกัน
ใช้กับ `UNSIGN`/`PUBLISH`/`KEEP` ของสองคอลัมน์คำสั่ง

## ด่านสองประเภท — ตัดสินได้จากไฟล์อย่างเดียว vs ต้องรู้สถานะ DB

🔴 **ไม่ใช่ทุกด่านตัดสินก่อนเปิด session อีกต่อไป** (ต่างจากรุ่นก่อน INF-29) — ด่านที่
ตรวจได้จาก*ตัวไฟล์*อย่างเดียว (รูปแบบ, `reason` บังคับ, `is_unique = N`, คำสั่งที่อ่าน
ออกแต่เขียนไม่ได้) ยังอยู่ใน `parse_rows()` **ทั้งหมด** ซึ่ง `raise PrecheckError`
ก่อน `return` และถูกเรียกก่อนเปิด session เสมอ · ด่านที่ต้องรู้*สถานะ DB* (schema ·
`status` ของใบ · ผลตรวจ `publish_blockers()`) อยู่**หลัง** `_load_state()` แต่**ก่อน
การเขียนครั้งแรกทุกกรณี** (ทั้ง dry-run และ `--commit`) และปฏิเสธทั้งไฟล์เหมือนกัน —
ไม่มีที่ไหนในไฟล์นี้ที่เขียนครึ่งทางแล้ว rollback

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
- ❌ **ไม่แตะ `needs_review` · `status`** — `status` เป็นของ service ที่คุม transition
  (skill `poster-database` §3) — อ่านได้ (ด่าน sold ต้องรู้ `status`) แต่เขียนไม่ได้เลย
- ❌ **ไม่แตะ `published_at` ให้มีค่า** — เขียนได้ทางเดียวคือล้างเป็น `NULL`
  (`WITHDRAW`) การ *ตั้ง* ค่ายังเป็นของเส้นที่ 3 ที่เดียว (ADR-0027 D7)
- ❌ **ไม่อ่านช่อง `current_*` ในใบงาน** — เป็นช่องช่วยจำของคนล้วน ๆ (precedent ตรงตัว:
  `previous_note` ของเส้นที่ 4 · ADR-0014 D28) · มีเทส closed-world ที่ระดับคีย์ที่ถูกอ่านจริง
- ❌ **ไม่แตกแถว ไม่แตะ `quantity`/`price`** — เป็นงานของ **INF-22** (ADR-0019 D8/D11)
- ❌ **ไม่มี CHECK ระดับ DB สำหรับ invariant `published ⇒ verified`** —
  `ck_posters_published_requires_verified` ยังไม่ลง (ADR-0027 D4) วันนี้บังคับ
  **แค่ฝั่ง Python** ที่ด่านก่อนเซ็นข้างบน
"""

from __future__ import annotations

import argparse
import os
import sys
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from functools import lru_cache
from pathlib import Path
from typing import Any

SEED_DIR = Path(__file__).resolve().parent
REPO_ROOT = SEED_DIR.parents[1]
sys.path.insert(0, str(REPO_ROOT))

from app.services.poster_service import (  # noqa: E402
    PublishBlocker,
    PublishReadiness,
    publish_blockers,
)
from scripts.seed._shared import (  # noqa: E402
    PrecheckError,
    _parse_reviewed_at,
    assert_not_in_the_future,
    read_sheet_rows,
)
from scripts.seed.apply_suggestions import _load_env  # noqa: E402

# 🔴 import **object เดียวกัน ไม่ก๊อป** — `_enum_parser(..., exact_case=True)` คือด่าน
# ที่ทำให้ `Fine` ไม่ถูกแปลงเป็น `fine` เงียบ ๆ (เกิดจริง 8 แถวเมื่อ 2026-08-07) ·
# `load_count_actual_by_poster` — ด่านก่อนเซ็น (ADR-0027 D3) อ่านผลนับข้ามไฟล์จาก
# `manual-entry.csv` ด้วยพาร์เซอร์เดียวกับเส้นที่ 6 (INF-29 ขั้นที่ 1 — ย้ายมาบ้าน
# ของ manual_entry.py 2026-08-16) · ถ้าก๊อปมาเป็นสำเนา วันที่ใครแก้ด่านฝั่งหนึ่งอีกฝั่ง
# จะเงียบ (เหตุผลเต็ม: `_shared.py`)
from scripts.seed.manual_entry import (  # noqa: E402
    DEFAULT_MANUAL_CSV,
    SIT_ENV_FILE,
    TARGETS,
    FieldSpec,
    _enum_parser,
    assert_target,
    load_count_actual_by_poster,
    render_value,
)
from scripts.seed.reference_entry import DEFAULT_REFERENCE_CSV  # noqa: E402

DEFAULT_CORRECTION_CSV = SEED_DIR / "correction-entry.csv"


class FieldMode(str, Enum):
    """VALUE = คอลัมน์เก็บ*ค่าปลายทาง*ตรงตัว (condition_grade/is_unique) · COMMAND =
    คอลัมน์เก็บ*คำสั่ง* ที่ `plan_writes()` แปลเป็นค่าปลายทางเอง (verified_at/
    published_at) — ADR-0027 §AC-1 · ตารางนี้เป็นแหล่งเดียวของความต่างระหว่างสองโหมด
    """

    VALUE = "VALUE"
    COMMAND = "COMMAND"


# 🔴 คอลัมน์ทั้งหมดที่สคริปต์นี้เขียนได้ — ADR-0010 **A-D2 ข้อ 6** (ฉบับเดิม) ·
# ขยายเป็น 4 โดย ADR-0027 **D7** (ฉบับที่แก้ A-D2 ข้อ 6) **ห้ามเพิ่มโดยไม่แก้ ADR**
# ตัวนี้เป็นแหล่งเดียวของ `choices` ที่ argparse ด้วย ("ปฏิเสธฟิลด์นอกรายการตั้งแต่
# ชั้น CLI") และของ fail-closed ในลูปที่เขียน
WRITABLE_FIELDS = ("condition_grade", "is_unique", "verified_at", "published_at")
FIELD_MODES: dict[str, FieldMode] = {
    "condition_grade": FieldMode.VALUE,
    "is_unique": FieldMode.VALUE,
    "verified_at": FieldMode.COMMAND,
    "published_at": FieldMode.COMMAND,
}
# ช่องเหตุผล — **หนึ่งช่องต่อหนึ่งฟิลด์** (มติเจ้าของ 2026-08-09 · เข้มกว่าตัวอักษร
# ของ A-D2 ข้อ 2 ซึ่งพูดแค่ "ต่อแถว") · เหตุผลของเกรดกับของจำนวนเป็นคนละเรื่องกัน
# ก้อนเดียวที่ถูกก๊อปลงสองแถว audit จะอ่านย้อนแล้วแยกไม่ออกว่าอธิบายอันไหน
REASON_COLUMNS = tuple(f"{name}_reason" for name in WRITABLE_FIELDS)
# ช่องช่วยจำของคน — **สคริปต์ไม่อ่านเลย** (ดู §สิ่งที่สคริปต์นี้ไม่ทำ)
CURRENT_COLUMNS = tuple(f"current_{name}" for name in WRITABLE_FIELDS)

# คอลัมน์ของใบงาน — `make_correction_sheet.py` import ไปใช้ ไม่ประกาศซ้ำสองที่ ·
# **ประกอบจากทูเพิลของ WRITABLE_FIELDS** (ไม่ hardcode) เพื่อให้ฟิลด์ที่เพิ่มวันหน้า
# ได้คอลัมน์ครบโดยอัตโนมัติ — ลำดับ: ตัวช่วยระบุใบ → ช่องช่วยจำทั้งหมด →
# (ช่องกรอก, ช่องเหตุผล) สลับกันต่อฟิลด์
CORRECTION_SHEET_COLUMNS = (
    ("poster_uuid", "title", "image_url")
    + CURRENT_COLUMNS
    + tuple(
        col
        for pair in zip(WRITABLE_FIELDS, REASON_COLUMNS, strict=True)
        for col in pair
    )
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
# vocabulary ของสองคอลัมน์คำสั่ง — ADR-0027 §AC-2
# --------------------------------------------------------------------------

# คำที่ปรากฏได้ในคอลัมน์ *ช่วยจำ* (`current_verified_at`/`current_published_at`)
# **และเป็นคำเดียวที่ทั้งสองคอลัมน์ใช้แทน "ไม่ทำอะไร"** — ADR-0027 D7: ใช้คำเดียวกัน
# เพื่อไม่ให้มีคำที่แปลว่า "ไม่ทำอะไร" สองคำในไฟล์เดียว
KEEP_WORD = "KEEP"
# ช่องเซ็นรับ — อ่านออกสามคำ เขียนได้ค่าเดียว (ADR-0027 D1 · D7)
VERIFIED_AT_WORDS = {"sign": "SIGN", "keep": KEEP_WORD, "unsign": "UNSIGN"}
VERIFIED_AT_ONLY_WRITABLE_VALUE = "SIGN"
# ช่องถอนของ — อ่านออกสามคำ เขียนได้ค่าเดียว (ADR-0027 D7)
PUBLISHED_AT_WORDS = {"withdraw": "WITHDRAW", "keep": KEEP_WORD, "publish": "PUBLISH"}
PUBLISHED_AT_ONLY_WRITABLE_VALUE = "WITHDRAW"


def _command_word_parser(
    words: dict[str, str], *, field_label: str
) -> Callable[[str], str]:
    """ตัวอ่านคำสั่งของคอลัมน์ COMMAND — คืน**คำสั่ง** (`str`) ไม่ใช่ค่าปลายทาง

    ทรงเดียวกับ `_enum_parser`/`parse_is_unique` — เทียบแบบไม่สนตัวพิมพ์ ปฏิเสธคำที่
    ไม่อยู่ในรายการด้วยข้อความที่บอกตัวเลือกทั้งหมด · ค่าปลายทางจริง (เช่น
    `args.reviewed_at`) ยังไม่ถูกตัดสินที่นี่ — เป็นหน้าที่ของ `plan_writes()`
    """

    def parse(raw: str) -> str:
        word = words.get(raw.lower())
        if word is not None:
            return word
        allowed = " / ".join(sorted(set(words.values())))
        raise ValueError(
            f"{raw!r} ใช้ไม่ได้ — {field_label} รับเฉพาะ {allowed} (ตัวพิมพ์ใดก็ได้)"
        )

    return parse


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

    🔴 **`verified_at`/`published_at` ห้ามพิมพ์วันที่จริงเด็ดขาด** (ADR-0027 G7 —
    ตั้งชื่อ G7 ซ้ำบทเรียนเดิมโดยตั้งใจ เพราะเป็นกฎเดียวกัน: ใบงานสอนคำที่พาร์เซอร์
    ของฟิลด์นั้นอ่านออก) — พิมพ์ `KEEP` เมื่อมีค่าอยู่ (คอลัมน์ COMMAND อ่าน `KEEP`
    ได้อยู่แล้ว) และพิมพ์ว่างเมื่อเป็น `NULL`

    ฟิลด์ที่ไม่มีใน `SHEET_RENDERERS` ตกมาที่ `render_value()` ซึ่งถูกก็ต่อเมื่อ
    พาร์เซอร์ของมันอ่าน `str(value)` กลับได้ (จริงกับ enum: `near_mint` → `near_mint`)
    · **ด่านที่กันไม่ให้ข้อนี้กลับมาในช่องอื่นคือเทส round-trip** ไม่ใช่ความจำของคน
    → `test_make_correction_sheet.py` §round-trip
    """
    if value is None:
        # `is_unique` เป็น NOT NULL จึงไม่มีวันมาทางนี้ · `condition_grade` มาได้
        # (`--all`) และช่องว่างคือคำตอบที่ถูก: *ยังไม่มีเกรด* ไม่ใช่คำที่ต้องอ่านออก ·
        # `verified_at`/`published_at` มาได้ปกติ (ยังไม่เคยเซ็น/ยังไม่ publish)
        return ""
    renderer = SHEET_RENDERERS.get(field)
    if renderer is not None:
        return renderer(value)
    return render_value(value)


# ฟิลด์ที่ `render_value()` เขียนออกมาเป็นคำที่พาร์เซอร์ของมันเองอ่านไม่ออก
SHEET_RENDERERS: dict[str, Callable[[Any], str]] = {
    "is_unique": lambda value: IS_UNIQUE_TEXT[bool(value)],
    # G7 (ADR-0027) — ห้ามพิมพ์วันที่จริง · `value is not None` การันตีแล้วโดย
    # `render_current_value()` ก่อนเรียกมาถึงนี่ ⇒ คืน KEEP เสมอไม่ว่าค่าจริงจะเป็นเมื่อไหร่
    "verified_at": lambda _value: KEEP_WORD,
    "published_at": lambda _value: KEEP_WORD,
}


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
    """นิยามของ 4 ฟิลด์ใน `WRITABLE_FIELDS` — สองตัวแรก*ค่า* สองตัวหลัง*คำสั่ง*

    import `app.models.enums` **ข้างในฟังก์ชัน** ด้วยเหตุผลเดียวกับ
    `manual_entry.field_specs()` เป๊ะ — `app/models/__init__.py` ลาก
    `app.core.database` ตามมา ซึ่งต้องการ env ครบตอน import ส่วนบนของไฟล์นี้จึงต้อง
    import ได้ก่อน `_load_env()` ถูกเรียก

    🔴 **`verified_at`/`published_at` คืน *คำสั่ง* (`str`) จาก `.parse` ไม่ใช่ค่า
    ปลายทาง** — `plan_writes()` เป็นคนแปลงคำสั่งเป็นค่าจริง (ดู `FieldMode.COMMAND`)
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
        "verified_at": FieldSpec(
            name="verified_at",
            parse=_command_word_parser(VERIFIED_AT_WORDS, field_label="ช่องเซ็นรับ"),
            hint=(
                "SIGN = เซ็นรับว่าตรวจครบทุกมิติแล้ว (เขียนได้ค่านี้ค่าเดียว — ใช้ "
                "--reviewed-at เป็นเวลาที่เซ็น) · KEEP = ไม่ทำอะไร เหมือนเว้นว่างช่องนี้ "
                "ทั้งคู่ (เขียนได้ในความหมายว่าไม่มีอะไรให้เขียน) · UNSIGN อ่านออกแต่"
                "เขียนไม่ได้ (ADR-0027 D1: ไม่มีสถานะ 'ตรวจแล้วไม่ผ่าน' — แก้ค่าแล้ว"
                "เซ็นใหม่แทน)"
            ),
        ),
        "published_at": FieldSpec(
            name="published_at",
            parse=_command_word_parser(PUBLISHED_AT_WORDS, field_label="ช่องถอนของ"),
            hint=(
                "WITHDRAW = ถอนใบนี้ออกจากชั้น (เขียนได้ค่านี้ค่าเดียว) · KEEP = "
                "ไม่ทำอะไร เหมือนเว้นว่างช่องนี้ทั้งคู่ · PUBLISH อ่านออกแต่เขียนไม่ได้ "
                "— การ *เปิด* ขายเป็นของเส้นที่ 3 (manual_entry.py) ที่เดียว "
                "(ADR-0027 D7) · ถอนใบที่ status=sold ไม่ได้ทุกกรณี (ADR-0027 A-D11)"
            ),
        ),
    }


def refuse_unwritable_value(field: str, value: Any) -> str | None:
    """ค่าที่ **อ่านออกแต่เขียนไม่ได้** → เหตุผล · เขียนได้ (รวม `KEEP` = ไม่ทำอะไร) →
    `None` (pure)

    🔴 **นี่คือด่านที่ไม่ต้องรู้สถานะ DB เลย** — ไม่ดูเกรด ไม่ดูค่าเดิม ไม่ดู `--field`
    ไม่ดูว่าใบนั้นมีใน DB ไหม จึงอยู่ใน `parse_rows()` ได้ ซึ่งแปลว่ามันตัดสิน
    **ก่อนเปิด session**

    ครอบทั้ง 4 ฟิลด์: `is_unique` (ADR-0019 D5/D6) · `verified_at`/`published_at`
    (ADR-0027 §AC-2 — **เฉพาะ** `UNSIGN`/`PUBLISH` เท่านั้นที่อ่านออกแต่เขียนไม่ได้)

    🔴 **G2 (code-critic รอบ 1 ของ INF-29)** — รุ่นก่อนของฟังก์ชันนี้ปฏิเสธ `KEEP`
    เหมือน `UNSIGN`/`PUBLISH` ทั้งที่ ADR-0027 D7 เขียนไว้ตรง ๆ ว่า `KEEP` = *"ไม่ทำ
    อะไร"* ซึ่งไม่ใช่ error — ผลคือคนก๊อป `KEEP` จากช่อง `current_*` มาแปะ (ตามที่
    `render_current_value()` ตั้งใจให้ก๊อปได้) แล้วโดนปฏิเสธทั้งไฟล์ ทรงเดียวกับ G7
    เดิมที่ไฟล์นี้เตือนตัวเองไว้แล้ว (ใบงานสอนคำที่พาร์เซอร์ของมันเองปฏิเสธ) ·
    `parse_rows()` เป็นคนกันไม่ให้ `KEEP` ไปถึง `field_writes`/`overwrites`/audit ใดๆ
    (ปฏิบัติเหมือนเว้นว่าง) — ที่นี่แค่ต้องไม่ถือว่า `KEEP` เป็นค่าที่ต้องปฏิเสธ

    ‹แก้ 2026-08-09 หลัง code-critic รอบที่ 1› รุ่นแรกของไฟล์นี้ทำด่านนี้เป็น
    *"`N` ได้เฉพาะเกรด `mint`"* ตาม **D1** ซึ่ง **ผิด** — D1 เป็น *สิทธิ์* ที่ **D5**
    ระบุว่ายังไม่มีเครื่องมือรองรับ (*"แม้ใบ `mint` ก็เก็บเป็น 1 แถว 1 ชิ้น"*) และ
    **D6** เขียนหัวข้อของตัวเองว่า `is_unique` ต้องเป็น `true` **ทุกแถว** ·
    ด่านที่อ่านแต่ D1 จึงเปิดกลไกทีละชิ้น ซึ่งมติเจ้าของเขียนกำกับว่า **"ห้ามทยอย"**
    """
    if field == "is_unique":
        if value is IS_UNIQUE_ONLY_WRITABLE_VALUE:
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
    if field == "verified_at":
        if value == VERIFIED_AT_ONLY_WRITABLE_VALUE:  # "SIGN"
            return None
        if value == KEEP_WORD:
            # ไม่ทำอะไร (ADR-0027 D7) — เขียนได้ในความหมายว่า "ไม่มีอะไรให้เขียน"
            # parse_rows() เป็นคนกันไม่ให้ค่านี้ไปถึง field_writes/overwrites/audit
            return None
        return (  # UNSIGN
            "UNSIGN อ่านออกแต่เขียนไม่ได้ — ADR-0027 D1 ไม่มีสถานะ 'ตรวจแล้วไม่ผ่าน' "
            "(NULL แปลว่า 'ยังไม่เคยมีใครตรวจ' เท่านั้น) · ใบที่ตรวจแล้วพบว่าผิด "
            "ให้แก้ค่าที่ผิดแล้วเซ็น SIGN ใหม่ในแถวเดียวกันแทน — ลายเซ็นจะถูกล้าง"
            "ให้อัตโนมัติอยู่แล้วถ้าแก้ condition_grade/is_unique จริง (D6)"
        )
    if field == "published_at":
        if value == PUBLISHED_AT_ONLY_WRITABLE_VALUE:  # "WITHDRAW"
            return None
        if value == KEEP_WORD:
            # ไม่ทำอะไร (ADR-0027 D7) — เขียนได้ในความหมายว่า "ไม่มีอะไรให้เขียน"
            return None
        return (  # PUBLISH
            "PUBLISH อ่านออกแต่เขียนไม่ได้ — การ *ตั้ง* ค่า published_at (เปิดขาย) "
            "เป็นของเส้นที่ 3 (manual_entry.py --commit ผ่าน publish=Y) ที่เดียว "
            "(ADR-0027 D7 · ADR-0013 D6) เส้นนี้ล้างค่าได้อย่างเดียว"
        )
    return None  # condition_grade — ทุกค่าที่ parse ผ่านมาได้เขียนได้


@dataclass(frozen=True)
class CorrectionRow:
    """หนึ่งแถวของใบงานที่ผ่านการตรวจรูปแบบแล้ว

    🔴 **ไม่มีฟิลด์สำหรับ `current_*`** — ชั้นนี้คือทุกอย่างที่สคริปต์รู้เกี่ยวกับ
    แถวหนึ่ง การไม่มีมันที่นี่แปลว่าไม่มีชั้นไหนข้างล่างอ่านมันได้เลย

    `values`/`reasons` ของฟิลด์ COMMAND เก็บ **คำสั่ง** (`"SIGN"`/`"WITHDRAW"`) ไม่ใช่
    ค่าปลายทาง — `plan_writes()` เป็นคนแปลง (ดู `FieldMode`)

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
            "แล้วให้คนหยิบใบจริงขึ้นมาตรวจซ้ำและกรอกเอง\n"
            "🔴 ใบงานรุ่นเก่า (ก่อน INF-29) มีแค่ 2 คอลัมน์ที่กรอก — ถ้าเจอข้อความ "
            "'ใบงานขาดคอลัมน์' ด้านล่าง แปลว่าไฟล์เก่าเกินไป ลบแล้ว regenerate ใหม่"
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
    จะกลายเป็นทางเลี่ยงด่าน `reason` ของฟิลด์อื่นในไฟล์เดียวกัน (และของด่าน D6 cascade
    ด้วย — ดู docstring ของ `plan_writes()`)
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

            if not text:
                # reason มีข้อความแต่ไม่มีค่าให้เหตุผลนั้นอธิบาย
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

            if value == KEEP_WORD:
                # 🔴 G2 — KEEP = "ไม่ทำอะไร" (ADR-0027 D7) เหมือนเว้นว่างช่องนี้ทั้งคู่
                # ไม่บังคับ reason แม้จะติดมาด้วยก็ไม่ใช่ข้อมูลขัดกันเอง เพราะ KEEP
                # ไม่มีการเขียนให้เหตุผลอธิบายเลย — ไม่เติมลง values/reasons จึงไม่มี
                # ทาง field_writes/overwrites/audit เห็นค่านี้เลย (เหมือนแถวว่าง)
                continue

            if not reason:
                # 🔴 A-D2 ข้อ 2 — นี่คือสิ่งเดียวที่ทำให้ "มีคนรู้เห็น" ต่างจาก "มีคนรัน"
                errors.append(
                    f"{prefix}: {name} = {text!r} แต่ {reason_column} ว่าง — "
                    "เส้นนี้ทับค่าที่ลูกค้าเห็นบนหน้าร้านไปแล้ว (หรือกระทบว่าใบนี้อยู่"
                    "บนร้านไหม) เหตุผลจึงบังคับต่อค่า (ADR-0010 A-D2 ข้อ 2) · "
                    "เหตุผลที่ไม่ถูกเก็บ = เหตุผลที่ไม่มี"
                )
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


def assert_reviewed_at_present_when_signing(
    rows: list[CorrectionRow], signed_at: datetime | None
) -> None:
    """ปฏิเสธทั้งไฟล์เมื่อมีแถวสั่ง `SIGN` แต่ไม่มี `--reviewed-at` — pure ล้วน
    (ไม่ต้องรู้สถานะ DB เลย) จึงเรียกได้**ก่อนเปิด session** ก่อนแม้แต่การอ่าน
    `manual-entry.csv` ของด่านก่อนเซ็น (D3)

    🔴 **G1 (code-critic รอบ 1 ของ INF-29)** — ด่านนี้เดิมมีอยู่แค่ที่
    `parser.error()` ตอน `--commit` เท่านั้น (`main()` แปลง `--reviewed-at` เป็น
    `datetime` เฉพาะเมื่อ `args.commit`) ⇒ dry-run ส่ง `signed_at` เป็น `str | None`
    ดิบเข้า `plan_writes()`/`assert_signable()`: ใบยังไม่เคยเซ็น + `SIGN` →
    `render_value(None)` ได้ `""` เท่ากับ `before` ของใบที่ยังไม่เคยเซ็น ⇒ รายงานผิด
    เป็น `SKIP_SAME` แทนที่จะปฏิเสธ (ใบเคยเซ็นแล้วยิ่งแย่กว่า — ดูเหมือนค่ากลายเป็น
    ว่างซึ่งไม่มีสถานะแบบนั้นในระบบตาม D1) · ด่านนี้ตัดปัญหาตั้งแต่ต้นทาง
    **ไม่ว่าโหมดไหน** แทนที่จะพึ่งแค่ `main()` ฝั่ง `--commit`

    รับ `signed_at` เป็น `datetime | None` ตรง ๆ (ไม่ใช่ `args.reviewed_at` ดิบที่
    อาจยังเป็น `str`) — ผู้เรียก (`run()`) ต้องผ่านด่าน parse ของ `main()` มาก่อนแล้ว
    เสมอไม่ว่าโหมดไหน (ดูการแก้ของ G1 ใน `main()`)
    """
    # 🔴 G1 (code-critic รอบ 2 ของ INF-29) — เช็คแค่ `is not None` ไม่พอ: ถ้ามี
    # ที่อื่นหลุด `args.reviewed_at` เป็น `""` (string ว่าง) เข้ามาโดยไม่ผ่าน
    # `_parse_reviewed_at()` (เช่น เรียกฟังก์ชันนี้ตรง ๆ จากที่อื่นในอนาคต) ด่านนี้
    # ต้องปฏิเสธด้วย ไม่ใช่ปล่อยผ่านเพราะ `"" is not None` เป็นจริง — เช็คชนิดตรง ๆ
    # ว่าต้องเป็น `datetime` เท่านั้นถึงจะถือว่า "มีลายเซ็นแล้ว"
    if isinstance(signed_at, datetime):
        return
    offenders = [row for row in rows if "verified_at" in row.values]
    if not offenders:
        return
    lines = [f"บรรทัด {r.lineno} ({r.poster_uuid}): สั่ง SIGN" for r in offenders]
    raise PrecheckError(
        "ใบต่อไปนี้สั่ง SIGN แต่ไม่ได้ใส่ --reviewed-at — ปฏิเสธทั้งไฟล์ ไม่ว่าจะเป็น "
        "dry-run หรือ --commit ก็ตาม (เวลาที่เซ็นต้องมาจาก --reviewed-at เสมอ ไม่มี "
        "default เป็นเวลาปัจจุบัน — ADR-0010 D5):\n  "
        + "\n  ".join(lines)
        + "\n\nใส่ --reviewed-at <เวลาที่คุณตัดสิน ISO-8601 พร้อม timezone> แล้วรันใหม่"
    )


# --------------------------------------------------------------------------
# วางแผนการเขียน (pure — รับสถานะปัจจุบันเข้ามา ไม่ query เอง)
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class PosterState:
    """สถานะปัจจุบันของใบหนึ่งใน DB — ทุกอย่างที่ `plan_writes()`/ด่านก่อนเขียนต้องรู้

    🔴 **`status`/`front_image_count` เพิ่มเข้ามา 2026-08-16 (INF-29)** — ไม่ใช่
    `WRITABLE_FIELDS` (เส้นนี้เขียนไม่ได้ทั้งคู่) แต่ต้องรู้เพื่อด่าน sold (A-D11)
    และด่านก่อนเซ็น (D3) ตามลำดับ
    """

    # ค่าปัจจุบันของ `WRITABLE_FIELDS` (ค่าดิบจาก ORM · `condition_grade`/
    # `verified_at`/`published_at` เป็น `None` ได้ · `is_unique` เป็น NOT NULL)
    values: dict[str, Any]
    status: "Any"  # PosterStatus — string annotation กันการ import ตอน module load
    front_image_count: int


class RowAction(str, Enum):
    WRITE = "WRITE"
    SKIP_BLANK = "SKIP_BLANK"  # ยังไม่ได้ตรวจ (หรือถูกตัดออกด้วย --field)
    SKIP_SAME = "SKIP_SAME"  # ค่าใหม่เท่าค่าเดิม — ADR-0010 D8
    SKIP_NO_TARGET = "SKIP_NO_TARGET"  # ปลายทางยังว่าง → เส้นนี้แก้ไม่ได้ ไปเส้นที่ 3
    SKIP_NOT_FOUND = "SKIP_NOT_FOUND"  # ไม่มีใบนี้ใน DB — ADR-0015 D5


@dataclass(frozen=True)
class PlannedWrite:
    row: CorrectionRow
    action: RowAction
    # ฟิลด์ที่จะเขียนจริง — ว่างเสมอเมื่อ action ไม่ใช่ WRITE · ค่าของ
    # verified_at/published_at ที่เป็น cascade (D6) ไม่มี key คู่ใน `row.values`
    field_writes: dict[str, Any]
    # {ชื่อฟิลด์: (ค่าเดิมเป็นข้อความ, ค่าใหม่เป็นข้อความ)} — คีย์ตรงกับ `field_writes`
    # เสมอ เพราะเส้นนี้ **ทับ 100%** ไม่มีการเติมช่องว่าง · `verified_at` ตัวเดียวที่
    # ค่าเดิมเป็นข้อความเปล่า `""` ได้ (แปลว่า NULL — audit_entries() แปลงเป็น `None`)
    overwrites: dict[str, tuple[str, str]]
    # ฟิลด์ที่กรอกมาแต่ค่าเท่าเดิม → {ชื่อฟิลด์: ค่าเดิมเป็นข้อความ}
    unchanged: dict[str, str]
    # ฟิลด์ที่กรอกมาแต่ปลายทางยังเป็น NULL → เส้นนี้ไม่ใช่เจ้าของงานเติมช่องว่าง
    # (condition_grade) หรือไม่มีอะไรให้ถอน (published_at + WITHDRAW)
    no_target: tuple[str, ...]
    # ค่าปัจจุบันของทุกคอลัมน์ที่เขียนได้ (ข้อความ) — ใช้ในรายงาน ไม่ใช่ในการตัดสิน
    current: dict[str, str]


def plan_writes(
    rows: list[CorrectionRow],
    current: dict[uuid.UUID, PosterState],
    fields: tuple[str, ...] = WRITABLE_FIELDS,
    *,
    signed_at: datetime,
) -> list[PlannedWrite]:
    """แถวใบงาน + สถานะปัจจุบันของ DB → แผนการเขียน

    `current` = {poster_id: PosterState} · ใบที่ไม่มีใน dict ถือว่าไม่มีในฐานข้อมูล
    → **ข้าม ไม่ใช่ INSERT** (ADR-0015 D5 ตกทอดมาทั้งดุ้น)

    `signed_at` = ค่าที่ *ลง* `verified_at` จริงเมื่อแถวสั่ง `SIGN` — พารามิเตอร์บังคับ
    ไม่มี default (ทรงเดียวกับ `--reviewed-at` ที่ไม่มี default เป็นเวลาปัจจุบัน)
    เพื่อคงความ pure ไม่มีการอ่านนาฬิกาเพิ่มในไฟล์นี้เลย (ADR-0027 §AC-2)

    pure function — ไม่ query ไม่เขียน ไม่แตะเวลาปัจจุบัน

    🔴 **`condition_grade` ที่ปลายทางเป็น `NULL` ถูกข้าม *เฉพาะฟิลด์นั้น*** ไม่ใช่ทั้งแถว
    — นี่คือกลไกที่ทำให้ `value_before` ของฟิลด์นั้นห้ามเป็น `NULL` จริง **โดยโครงสร้าง**
    ไม่ใช่โดยข้อตกลง: ฟิลด์เดียวที่เป็น `NULL` ได้ถูกกันออกตั้งแต่ตอนวางแผน ส่วน
    `is_unique` เป็น `NOT NULL` จึงมีค่าเดิมเสมอ

    🔴 **นโยบายความสด (ADR-0027 D6) — ต้องไม่ฟัง `fields`** — เขียน `condition_grade`
    หรือ `is_unique` จริง (ไม่ใช่ `SKIP_SAME`) ⇒ ล้าง `verified_at`/`published_at`
    ที่มีค่าอยู่เป็น `NULL` ในธุรกรรมเดียวกันเสมอ ไม่ว่า `--field` จะจำกัดรอบนี้ไว้
    แค่คอลัมน์ไหนก็ตาม — ไม่งั้น `--field condition_grade` จะกลายเป็นทางเลี่ยง D6
    · ถ้าแถวเดียวกันสั่ง `SIGN` ด้วย ผลของ `SIGN` **ทับผลของ cascade** บน `verified_at`
    เสมอ (คนตรวจของจริงแล้วเซ็นโดยรู้ว่าตัวเองเพิ่งแก้อะไร — ลายเซ็นไม่ได้โกหก) **ยกเว้น**
    กรณีขอบ (แก้ G4 · code-critic รอบ 2 ของ INF-29): ถ้าเวลาที่ `SIGN` เท่ากับค่าที่มีอยู่
    **ก่อน** cascade จะล้าง — สุทธิแล้ว `verified_at` ไม่เปลี่ยนเลย ⇒ ถอนทั้งการเขียนของ
    cascade และของ `SIGN` ออกจาก `verified_at` (net no-op ตาม ADR-0010 D8) `published_at`
    ไม่เกี่ยวกับข้อยกเว้นนี้ — ยังถูก cascade ล้างตามปกติเสมอ
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

        # --- ฟิลด์โหมด VALUE: condition_grade · is_unique ---
        for name in ("condition_grade", "is_unique"):
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

        # --- นโยบายความสด (ADR-0027 D6) — ล้างลายเซ็น/publish อัตโนมัติ ---
        # 🔴 ต้องมาก่อนสองบล็อก COMMAND ข้างล่าง เพื่อให้ SIGN ทับผลของมันได้ (D6)
        cascade_triggers = tuple(
            n for n in ("condition_grade", "is_unique") if n in field_writes
        )
        if cascade_triggers:
            for cascaded in ("verified_at", "published_at"):
                before_cascade = rendered_current[cascaded]
                if before_cascade == "":
                    continue  # ไม่มีอะไรให้ล้าง — ยังไม่เคยเซ็น/ยังไม่เคย publish
                field_writes[cascaded] = None
                overwrites[cascaded] = (before_cascade, "")

        # --- ฟิลด์โหมด COMMAND: verified_at (SIGN) ---
        if "verified_at" in fields and "verified_at" in row.values:
            before = rendered_current["verified_at"]
            after = render_value(signed_at)
            if cascade_triggers and before == after:
                # 🔴 G4 (code-critic รอบ 2 ของ INF-29) — cascade ข้างบนเพิ่งล้าง
                # verified_at เป็น NULL (เพราะเกรด/is_unique เปลี่ยนในแถวเดียวกัน) แต่
                # คำสั่ง SIGN รอบนี้ใช้เวลาเดิมเป๊ะกับค่าที่มีอยู่ **ก่อน** cascade จะล้าง
                # ⇒ สุทธิแล้วคอลัมน์นี้ไม่เปลี่ยนเลย (net no-op) — ADR-0010 D8
                # ("ค่าเท่าเดิม = ไม่ใช่การเขียน") ต้องมีผลตรงนี้เหมือนฟิลด์อื่นทุกที่ใน
                # ระบบ ไม่ใช่ข้อยกเว้น (รอบก่อนปล่อยให้เขียน NULL→signed_at ทั้งที่ค่า
                # สุทธิเท่าเดิม — ดู test_sign_becomes_a_net_no_op_when_the_instant_
                # already_matches_the_old_signature)
                #
                # ต้องถอนทั้งการเขียนของ cascade (ใส่ None ไปแล้วข้างบน) และของ SIGN
                # ออกจาก field_writes/overwrites โดยสิ้นเชิง — .pop() ไม่ใช่แค่ไม่เพิ่ม
                # เข้าไปใหม่ เพราะ cascade ใส่ field_writes["verified_at"] = None ไปแล้ว
                # ก่อนถึงบรรทัดนี้ · published_at ไม่เกี่ยวกับข้อนี้เลย — cascade ยังล้าง
                # published_at ตามปกติเสมอ (บล็อกข้างบนไม่ถูกแตะ)
                field_writes.pop("verified_at", None)
                overwrites.pop("verified_at", None)
            elif not cascade_triggers and before == after:
                # idempotent — รันซ้ำใบงานเดิมด้วยเวลาเดิมไม่ควรสร้าง audit ปลอม
                unchanged["verified_at"] = before
            else:
                # cascade การันตีว่าแถวนี้เปลี่ยนอยู่แล้ว — SIGN ทับผลของมันเสมอ
                # ไม่ตรวจค่าเท่าเดิม ไม่งั้นแถวจะจบด้วย verified_at=NULL ทั้งที่คน
                # เพิ่งเซ็นในแถวเดียวกัน (ADR-0027 D6 §"ทับผลข้อ 2")
                field_writes["verified_at"] = signed_at
                overwrites["verified_at"] = (before, after)

        # --- ฟิลด์โหมด COMMAND: published_at (WITHDRAW) ---
        if "published_at" in fields and "published_at" in row.values:
            before = rendered_current["published_at"]
            if before == "":
                # ยังไม่ publish — ไม่มีอะไรให้ถอน (ADR-0027 §จุดปะทะ — SKIP_NO_TARGET
                # ใช้ถูกต้องแล้วสำหรับกรณีนี้)
                no_target.append("published_at")
            else:
                field_writes["published_at"] = None
                overwrites["published_at"] = (before, "")

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
    """จำนวนค่าที่จะถูก**ทับ** แยกทีละคอลัมน์ (รวม cascade) — ตัวเลขที่คนต้องยืนยัน
    ก่อน `--commit`

    ⚠️ **ตัวเลขชุดนี้เทียบกับ `count(<column>)` ไม่ได้** ต่างจากเส้นอื่น — ดู
    §ทำไมไม่มี `_report_counts()` ใน docstring ของโมดูล
    """
    counts = dict.fromkeys(WRITABLE_FIELDS, 0)
    for plan in plans:
        for name in plan.field_writes:
            counts[name] += 1
    return counts


# --------------------------------------------------------------------------
# ด่านที่ต้องรู้สถานะ DB — เรียกหลัง `_load_state()` ก่อนการเขียนครั้งแรกทุกกรณี
# (ทั้ง dry-run และ --commit) — ADR-0027 A-D11 · D3
# --------------------------------------------------------------------------


def assert_no_row_targets_a_sold_poster(
    rows: list[CorrectionRow], current: dict[uuid.UUID, PosterState]
) -> None:
    """ADR-0027 **A-D11** — ปฏิเสธทั้งไฟล์เมื่อมีแถวใดสั่งเขียนอะไรก็ตามลงใบที่
    `status = 'sold'`

    🔴 **กว้างกว่า AC-3 ตัวอักษรหนึ่งขั้นโดยตั้งใจ** — ไม่ใช่แค่ปฏิเสธ `WITHDRAW`:
    cascade ของ D6 ถอนแถวออกจากร้านให้เองเมื่อแก้เกรด/จำนวน (`published_at → NULL`)
    แม้คนกรอกไม่ได้สั่งถอนเลยสักช่อง ⇒ ด่านที่ห้ามเฉพาะ `WITHDRAW` ปิดทางตรงแต่เปิด
    ทางอ้อมทิ้งไว้ทั้งบาน (`get_poster_detail()` ตอบ 404 แทน 200 — ผิด ADR-0013 D6 ·
    ADR-0005 D5 · SCR-05 AC-5) จึงต้องห้าม **ทุกคอลัมน์ที่เขียนได้** บนแถวที่ `sold`

    รับ `current` เข้ามาแทนที่จะ query เอง เพื่อให้ยังเป็นฟังก์ชันที่เทสได้ตรง ๆ
    โดยไม่ต้องมี DB จริง — แม้จะต้อง "รู้สถานะ DB" (`status` มาจาก `current` ที่
    ผู้เรียกโหลดมาให้แล้ว)
    """
    from app.models.enums import PosterStatus

    offenders = []
    for row in rows:
        if not row.values:
            continue  # แถวว่าง — ไม่มีอะไรจะเขียนอยู่แล้ว ไม่เกี่ยวกับด่านนี้
        state = current.get(row.poster_uuid)
        if state is None or state.status is not PosterStatus.sold:
            continue
        offenders.append(row)
    if not offenders:
        return
    lines = [f"บรรทัด {r.lineno} ({r.poster_uuid}): status = sold" for r in offenders]
    raise PrecheckError(
        "ใบต่อไปนี้ขายไปแล้ว (status = sold) — ปฏิเสธทั้งไฟล์ ไม่เขียนอะไรเลยแม้แถวอื่น "
        "จะถูกต้อง (ADR-0027 A-D11):\n  "
        + "\n  ".join(lines)
        + "\n\nADR-0027 D6 ล้าง verified_at/published_at อัตโนมัติเมื่อแก้ condition_grade"
        "/is_unique — บนแถวที่ขายแล้ว ผลนั้นคือการถอนใบที่ขายไปแล้วออกจากร้าน ซึ่ง "
        "ADR-0013 D6 + ADR-0005 D5 ห้ามไว้ (get_poster_detail() จะตอบ 404 แทน 200 — "
        "SCR-05 AC-5 พัง)\n"
        "🔴 การแก้เกรดของใบที่ขายแล้วไม่มีเครื่องมือรองรับ — เป็นผลที่ยอมรับแล้ว "
        "ไม่ใช่บั๊ก (ADR-0027 Amendment ครั้งที่ 2)"
    )


# ถ้อยคำสั้น ๆ ต่อ blocker สำหรับด่านก่อนเซ็น — ไม่ใช่การตัดสินซ้ำ (ตัดสินอยู่ที่
# `publish_blockers()` ที่เดียว ADR-0026 D8) เป็นแค่การแปล blocker → ภาษาคน
_SIGN_BLOCKER_HINTS: dict[PublishBlocker, str] = {
    PublishBlocker.NO_CONDITION_GRADE: (
        "ยังไม่มีเกรด — กรอก condition_grade ในแถวเดียวกันนี้ก่อน"
    ),
    PublishBlocker.UNKNOWN_IS_UNIQUE: (
        "อ่านค่า is_unique ของใบนี้ไม่ได้ — ไม่ทราบ = ไม่ผ่าน (ADR-0027 D5)"
    ),
    PublishBlocker.NOT_UNIQUE: (
        "is_unique = false — ของหลายชิ้นต้องแตกเป็นหลายแถวก่อนด้วยเส้นที่ 6 "
        "(split_entry.py — INF-22)"
    ),
    PublishBlocker.UNKNOWN_COUNT: (
        "count_actual ว่าง — ยังไม่มีผลนับใบจริง กรอกใน manual-entry.csv "
        "(เส้นที่ 3) ก่อน แล้วรันใหม่"
    ),
    PublishBlocker.COUNT_IS_ZERO: (
        "count_actual = 0 ใน manual-entry.csv — การนับล่าสุดบอกว่าไม่มีของ"
    ),
    PublishBlocker.COUNT_MULTIPLE_ON_NON_MINT: (
        "count_actual >= 2 บนเกรดที่ไม่ใช่ mint — เกรดต่ำกว่า mint ทุกระดับต้องเป็น "
        "1 แถว 1 ชิ้นเสมอ ต้องแตกเป็นหลายแถวก่อนด้วยเส้นที่ 6 (ADR-0019 D1)"
    ),
    PublishBlocker.UNKNOWN_FRONT_IMAGE_COUNT: (
        "นับรูป kind=FRONT ของใบนี้ไม่ได้ — ไม่ทราบ = ไม่ผ่าน (ADR-0027 D5)"
    ),
    PublishBlocker.NO_FRONT_IMAGE: ("ไม่มีรูป kind=FRONT สักรูป (BR-06 · ADR-0026 D8)"),
}


def assert_signable(
    rows: list[CorrectionRow],
    current: dict[uuid.UUID, PosterState],
    counts: dict[uuid.UUID, int | None] | None,
    *,
    signed_at: datetime,
) -> None:
    """ADR-0027 **D3** — เขียน `verified_at` ไม่ได้ถ้าเครื่องตรวจส่วนที่ตรวจได้เอง
    แล้วไม่ผ่าน — ปฏิเสธทั้งไฟล์ (ลายเซ็นที่กดได้ลอย ๆ คือตรายาง)

    🔴 **เรียก `publish_blockers()` ตัวเดียวกับที่เส้นที่ 3 ใช้ — ห้ามเขียนเงื่อนไข
    ซ้ำที่นี่** (ADR-0026 D8 · A-D9 ข้อ 1 · ADR-0027 D5) · ตัด `NOT_VERIFIED` ออก
    เพราะเป็นสิ่งที่แถวนี้กำลังจะแก้พอดี ไม่ใช่เงื่อนไขที่ควรบล็อกตัวเอง

    `PublishReadiness` ประกอบจากค่า **หลังรอบนี้** (`grade_after`/`is_unique_after`
    = ค่าที่กำลังจะเขียนถ้ามี ไม่งั้นค่าใน DB) และ `verified_at=signed_at` (ค่าที่
    กำลังจะเขียน ไม่ใช่ค่าเดิม) — เทคนิคเดียวกับ `grade_after` ของเส้นที่ 3 กันไม่ให้
    ใบที่กรอกเกรดกับ SIGN ในแถวเดียวกันติดลูปตัวเอง

    `counts` มาจาก `manual_entry.load_count_actual_by_poster()` — ผู้เรียก (`run()`)
    เป็นคนตัดสินว่าต้องโหลดไหม (เฉพาะเมื่อมีแถวที่สั่ง SIGN) · `counts=None` ใช้ได้
    เมื่อไม่มีแถวไหนสั่ง SIGN เลย (ฟังก์ชันนี้จะไม่แตะมันเลยในกรณีนั้น)
    """
    offenders: list[tuple[CorrectionRow, tuple[PublishBlocker, ...]]] = []
    for row in rows:
        if "verified_at" not in row.values:
            continue
        state = current.get(row.poster_uuid)
        if state is None:
            continue  # SKIP_NOT_FOUND จะจัดการเอง — ด่านนี้ไม่เกี่ยวกับใบที่ไม่มีจริง
        grade_after = row.values.get(
            "condition_grade", state.values.get("condition_grade")
        )
        is_unique_after = row.values.get("is_unique", state.values.get("is_unique"))
        count_actual = counts.get(row.poster_uuid) if counts else None
        readiness = PublishReadiness(
            condition_grade=grade_after,
            verified_at=signed_at,
            is_unique=is_unique_after,
            count_actual=count_actual,
            front_image_count=state.front_image_count,
        )
        blockers = tuple(
            b
            for b in publish_blockers(readiness)
            if b is not PublishBlocker.NOT_VERIFIED
        )
        if blockers:
            offenders.append((row, blockers))
    if not offenders:
        return
    lines = []
    for row, blockers in offenders:
        for blocker in blockers:
            hint = _SIGN_BLOCKER_HINTS.get(blocker, blocker.value)
            lines.append(
                f"บรรทัด {row.lineno} ({row.poster_uuid}): {blocker.value} — {hint}"
            )
    raise PrecheckError(
        "เซ็นรับไม่ได้ — เครื่องตรวจแล้วไม่ผ่านอย่างน้อยหนึ่งด่าน ปฏิเสธทั้งไฟล์ "
        "(ADR-0027 D3 · D5 fail-closed ต่อ field):\n  "
        + "\n  ".join(lines)
        + "\n\nลายเซ็นที่กดได้ลอย ๆ คือตรายาง — แก้ให้ผ่านด่านที่ระบุก่อนจะเซ็นได้"
    )


@dataclass(frozen=True)
class AuditEntry:
    """หนึ่งแถวที่จะลง `poster_attribute_reviews` — ADR-0010 D3 + **A-D2 ข้อ 3/4**

    `value_before: str | None` — **เกือบทุกฟิลด์ห้ามเป็น `None`** เพราะเส้นนี้ทับ
    100% ของการเขียน (`None` = "ยังไม่มีค่า" ซึ่งผิดเสมอสำหรับฟิลด์เหล่านั้น) ·
    **ยกเว้นที่เดียวในระบบ**: `verified_at` ตอนเซ็นรับครั้งแรก (`NULL_BEFORE_ALLOWED`)
    — `audit_entries()` เป็นคนบังคับข้อนี้ ไม่ใช่ข้อตกลง
    """

    field: str
    value_before: str | None
    value_after: str
    reason: str


# ฟิลด์เดียวที่ `value_before` เป็น `None` ได้ — การเซ็นรับครั้งแรก (verified_at
# NULL → มีค่า) คือการ "เติมช่องว่าง" จริง ๆ ไม่ใช่การทับ · ทุกฟิลด์อื่นถูกกันไม่ให้
# มาถึงจุดนี้ด้วย NULL อยู่แล้วโดยโครงสร้างของ `plan_writes()` (condition_grade →
# `no_target` · is_unique → NOT NULL · published_at → `no_target`)
NULL_BEFORE_ALLOWED = ("verified_at",)


def _cascade_reason(triggers: tuple[str, ...]) -> str:
    """ข้อความ audit ของแถวที่ D6 ล้างให้อัตโนมัติ — ประกาศตัวเองว่าเป็นผลอัตโนมัติ

    🔴 **ไม่ใช่การให้เครื่องเขียนเหตุผลแทนคน** — ข้อห้ามของ A-D2 ข้อ 2 เล็งที่
    generator เติมช่องของ*คน* (เช่น `make_correction_sheet.py` เดาเกรดให้) ไม่ใช่
    ข้อความอธิบาย*ผลข้างเคียงของระบบ*ที่ระบุแหล่งที่มาตรง ๆ ว่าเป็นอัตโนมัติ · ถ้าไม่
    ลง audit จะไม่มีใครตอบได้ว่าแถวหลุดจากร้านเพราะอะไร ซึ่งคือทั้งหมดที่ ADR-0013
    D6 ต้องการ
    """
    names = " · ".join(triggers)
    return (
        f"อัตโนมัติ (ADR-0027 D6): {names} ถูกแก้ในรอบเดียวกัน — ลายเซ็น/สถานะเปิดขาย"
        "เดิม (ถ้ามี) ไม่รับรองข้อมูลนี้อีกต่อไป แถวหลุดจากร้านจนกว่าจะมีคนตรวจและ"
        "เซ็นรับใหม่"
    )


def audit_entries(plan: PlannedWrite) -> tuple[AuditEntry, ...]:
    """แถว audit ของใบหนึ่ง — **หนึ่งแถวต่อหนึ่งค่าที่ทับจริง** (pure ไม่แตะ session)

    🔴 **ต้องเป็นฟังก์ชัน pure ไม่ใช่โค้ดในลูปของ `run()`** — ตรรกะเดียวกันนี้เคยอยู่
    ในลูปที่ต้องมี DB ถึงจะรันได้ แล้ว mutation ที่เปลี่ยนให้ `value_before=None` เสมอ
    **รอดเทสทั้ง 74 ตัว** เมื่อ 2026-08-07 ทั้งที่ ADR บังคับเรื่องนี้ตรง ๆ

    🔴 **แยก "เหตุผลของคน" กับ "เหตุผลอัตโนมัติของ cascade" ด้วยคีย์ที่มีอยู่ใน
    `row.reasons` เท่านั้น** — `parse_rows()` การันตีว่า `row.values`/`row.reasons`
    มีคีย์ชุดเดียวกันเสมอ ⇒ ฟิลด์ที่อยู่ใน `overwrites` แต่**ไม่มี**คีย์คู่ใน
    `row.reasons` ต้องเป็นผลของ cascade (D6) เท่านั้น ไม่มีทางเป็นอย่างอื่น
    """
    triggers = tuple(
        n for n in ("condition_grade", "is_unique") if n in plan.overwrites
    )
    cascade_reason = _cascade_reason(triggers) if triggers else None

    entries = []
    for name, (before, after) in plan.overwrites.items():
        reason = plan.row.reasons.get(name)
        if reason is None:
            if cascade_reason is None:  # pragma: no cover — ไม่ควรเกิดได้ตามโครงสร้าง
                raise AssertionError(
                    f"{name} อยู่ใน overwrites แต่ไม่มีทั้ง reason ของคนและ cascade "
                    "reason — ตรวจ plan_writes() ว่าเขียนฟิลด์นี้ได้อย่างไร"
                )
            reason = cascade_reason

        value_before: str | None = before
        if before == "":
            if name not in NULL_BEFORE_ALLOWED:
                # 🔴 G4 — ไม่ควรเกิดได้ตามโครงสร้างของ plan_writes() (fail-closed
                # เผื่อโครงสร้างพังในอนาคต) · เทสเชิงลบที่ป้อน PlannedWrite สังเคราะห์
                # ตรงเข้ามาครอบบรรทัดนี้แล้ว — ดู
                # test_null_before_guard_raises_for_any_field_other_than_verified_at
                raise AssertionError(
                    f"{name} มี value_before เป็นค่าว่าง (NULL) ซึ่งไม่ได้รับอนุญาต "
                    f"(NULL_BEFORE_ALLOWED = {NULL_BEFORE_ALLOWED}) — ฟิลด์นี้ต้องมี"
                    "ค่าเดิมเสมอตามโครงสร้างของ plan_writes() ถ้าเกิดขึ้นจริงคือบั๊ก"
                )
            value_before = None

        entries.append(
            AuditEntry(
                field=name,
                value_before=value_before,
                value_after=after,
                reason=reason,
            )
        )
    return tuple(entries)


def verify_corrections(
    plans: list[PlannedWrite],
    after_state: dict[uuid.UUID, PosterState],
    *,
    signed_at: datetime,
) -> list[str]:
    """อ่านค่ากลับมาเทียบกับค่าที่ตั้งใจเขียน — pure (รับสถานะหลัง commit เข้ามา)

    🔴 **นี่คือ assert ตัวเดียวที่เส้นนี้มี** — ดู §ทำไมไม่มี `_report_counts()`

    🔴 **เทียบตามความหมาย ไม่ใช่สตริง สำหรับฟิลด์ COMMAND** — `render_value(datetime)`
    ที่เขียนกับค่าที่ DB คืนกลับมาอาจต่าง format/offset กัน (offset ของ `signed_at`
    ที่คนพิมพ์ vs `timestamptz` ที่ PostgreSQL คืนเป็น UTC เสมอ) แม้จะเป็น**instant
    เดียวกัน** — เทียบสตริงตรง ๆ จะ false-positive ที่นี่ (จุดที่พังเงียบ #1 ของแผน
    architect) `verified_at` จึงเทียบด้วย `==` ของ `datetime` (เทียบ instant ผ่าน
    tzinfo-aware equality) ส่วนฟิลด์ที่ถูกล้างเป็น `NULL` (`published_at` หรือ
    `verified_at` จาก cascade) เทียบด้วย `is None`
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
            actual_value = state.values.get(name)
            if name == "verified_at" and after != "":
                if actual_value != signed_at:
                    problems.append(
                        f"บรรทัด {plan.row.lineno}: verified_at ควรเป็น "
                        f"{signed_at.isoformat()} แต่อ่านกลับมาได้ {actual_value!r}"
                    )
                continue
            if after == "":
                if actual_value is not None:
                    problems.append(
                        f"บรรทัด {plan.row.lineno}: {name} ควรเป็น NULL "
                        f"แต่อ่านกลับมาได้ {actual_value!r}"
                    )
                continue
            actual = render_value(actual_value)
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

    🔴 **ไม่ดูเกรดเลย และนั่นคือความถูกต้องไม่ใช่ความมักง่าย** — `false` ผิดทุกเกรด
    (หลัง D5) คำถามเดียวที่เหลือคือ *ยังเป็น false ไหม*
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

    # 🔴 สรุปแยกมุมมองข้างล่าง **นับซ้ำได้** ไม่ใช่ partition — แถวเดียวกันนับได้ใน
    # หลายหมวดพร้อมกัน (เช่นแถวที่แก้เกรด+SIGN ในรอบเดียวนับทั้ง "ทับเกรด/จำนวน" และ
    # "เซ็นรับ") ป้ายเดิม "แยกตามการกระทำ" สื่อว่าเป็น partition ซึ่งไม่จริง (low item
    # #2 ของ code-critic รอบ 1 ของ INF-29)
    overwritten = [
        p
        for p in plans
        if any(n in p.overwrites for n in ("condition_grade", "is_unique"))
    ]
    signed = [
        p
        for p in plans
        if "verified_at" in p.overwrites and "verified_at" in p.row.reasons
    ]
    withdrawn = [
        p
        for p in plans
        if "published_at" in p.overwrites and "published_at" in p.row.reasons
    ]
    auto_cleared = [
        p
        for p in plans
        if any(
            n in p.overwrites and n not in p.row.reasons
            for n in ("verified_at", "published_at")
        )
    ]

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
    print("สรุปแยกมุมมอง (นับซ้ำได้ — ADR-0027 D6 · D7):")
    print(f"  ทับเกรด/จำนวน                     : {len(overwritten)}")
    print(f"  เซ็นรับ (SIGN)                     : {len(signed)}")
    print(f"  ถอนของ (WITHDRAW)                  : {len(withdrawn)}")
    print(
        f"  ล้างอัตโนมัติ (D6 cascade)          : {len(auto_cleared)}"
        "  (ลายเซ็น/publish หายเพราะเกรดหรือจำนวนถูกแก้ในรอบเดียวกัน)"
    )

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
        f"{by_action[RowAction.SKIP_NO_TARGET]}  (เกรด: เส้นนี้แก้ไม่ใช่เติม → เส้นที่ 3 · "
        "WITHDRAW: ยังไม่ publish ไม่มีอะไรให้ถอน)"
    )
    print(
        f"  ข้าม — ไม่มีใบนี้ใน DB            : "
        f"{by_action[RowAction.SKIP_NOT_FOUND]}  (UPDATE เท่านั้น ไม่ INSERT)"
    )

    writing = [p for p in plans if p.overwrites]
    if writing:
        # 🔴 low item #2 ของ code-critic รอบ 1 ของ INF-29 — การเซ็นรับครั้งแรก
        # (value_before ว่างของ verified_at) คือการ *เติม* ช่องว่าง ไม่ใช่การ *ทับ*
        # ค่าที่มีคนเห็นมาก่อน (NULL_BEFORE_ALLOWED) แยกนับออกจากตัวเลข "จะทับ"
        first_signature_count = sum(
            1
            for plan in writing
            for name, (before, _after) in plan.overwrites.items()
            if name == "verified_at" and before == ""
        )
        overwrite_value_count = total - first_signature_count
        print()
        header = f"🔴 จะทับค่าเดิม {overwrite_value_count} ค่า ใน {len(writing)} ใบ"
        if first_signature_count:
            header += (
                f" · เติมลายเซ็นครั้งแรก {first_signature_count} ค่า "
                "(value_before เดิมเป็น NULL — เติม ไม่ใช่ทับ)"
            )
        header += " — ค่าที่ทับมีคนเห็นบนหน้าร้านไปแล้ว หรือกระทบว่าใบนี้อยู่บนร้านไหม:"
        print(header)
        for plan in writing:
            for name, (before, after) in plan.overwrites.items():
                reason = (
                    plan.row.reasons.get(name) or "อัตโนมัติ — ดู D6 cascade ด้านบน"
                )
                print(
                    f"  บรรทัด {plan.row.lineno:>4}  {name:<16} "
                    f"{before!r} → {after!r}"
                )
                print(f"                เหตุผล: {reason}")
        print(
            "  ↑ ค่าเดิมและเหตุผลทุกบรรทัดถูกบันทึกลง poster_attribute_reviews "
            "(value_before · reason)"
        )

    no_target = [p for p in plans if p.no_target]
    if no_target:
        print()
        print(
            "ใบที่ปลายทางยังว่าง — เส้นนี้เขียนไม่ได้ (แก้เกรด ไม่ใช่เติม / ไม่มีอะไร"
            "ให้ถอน):"
        )
        for plan in no_target:
            print(f"  บรรทัด {plan.row.lineno:>4}  {' · '.join(plan.no_target)}")

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
    print(
        "ไม่แตะ needs_review · status เลยสักแถว (อ่าน status ได้เพื่อด่าน sold เท่านั้น)"
    )
    print(
        "🔴 published_at เขียนได้ทางเดียวคือล้างเป็น NULL — ไม่มีทางในไฟล์นี้ที่ตั้งค่า"
        "จริงให้มัน (การเปิดขายเป็นของเส้นที่ 3)"
    )
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
    from sqlalchemy import func, select

    from app.models.enums import PosterImageKind
    from app.models.poster import Poster, PosterImage

    result = await session.execute(
        select(
            Poster.id,
            *[getattr(Poster, n) for n in WRITABLE_FIELDS],
            Poster.status,
            # FILTER ของ PostgreSQL — นับเฉพาะรูปหน้าใบในการ query รอบเดียวกัน
            # ไม่ต้องยิงเพิ่ม (ทรงเดียวกับ manual_entry._load_state()) — ADR-0027 D3
            # ต้องรู้ front_image_count เพื่อด่านก่อนเซ็น
            func.count(PosterImage.id).filter(
                PosterImage.kind == PosterImageKind.FRONT
            ),
        )
        .outerjoin(PosterImage, PosterImage.poster_id == Poster.id)
        .where(Poster.id.in_(poster_ids))
        .group_by(Poster.id)
    )
    state: dict[uuid.UUID, PosterState] = {}
    for row in result.all():
        poster_id, *rest = row
        values = dict(zip(WRITABLE_FIELDS, rest[: len(WRITABLE_FIELDS)], strict=True))
        status, front_image_count = rest[len(WRITABLE_FIELDS) :]
        state[poster_id] = PosterState(
            values=values, status=status, front_image_count=front_image_count
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

    # 🔴 G1 — ด่านไฟล์ล้วน (ไม่ต้องรู้สถานะ DB) เรียกก่อนเปิด session เสมอ ไม่ว่า
    # dry-run หรือ --commit — กันไม่ให้ signed_at เป็น None หลุดเข้า plan_writes()/
    # assert_signable() (ดู docstring ของฟังก์ชันนี้)
    assert_reviewed_at_present_when_signing(rows, args.reviewed_at)

    async with async_session_maker() as session:
        await _check_schema(session)
        current = await _load_state(session, [r.poster_uuid for r in rows])

        # ด่านที่ต้องรู้สถานะ DB — ก่อนการเขียนครั้งแรกทุกกรณี (ทั้ง dry-run และ
        # --commit) และก่อน _report() (ADR-0027 A-D11 · D3)
        assert_no_row_targets_a_sold_poster(rows, current)
        counts: dict[uuid.UUID, int | None] | None = None
        if any("verified_at" in r.values for r in rows):
            # 🔴 อ่านเฉพาะเมื่อมีแถวที่สั่ง SIGN เท่านั้น (ADR-0027 §AC-4) — ไฟล์นี้
            # ไม่พบ = PrecheckError ตรง ๆ จาก load_count_actual_by_poster()
            counts = load_count_actual_by_poster(DEFAULT_MANUAL_CSV)
        assert_signable(rows, current, counts, signed_at=args.reviewed_at)

        plans = plan_writes(rows, current, fields, signed_at=args.reviewed_at)

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
            plans,
            await _load_state(session, [p.row.poster_uuid for p in plans]),
            signed_at=args.reviewed_at,
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
            "ไม่ใส่ = ทั้งสี่ฟิลด์ · **ไม่มีรูปแบบที่แปลว่า 'ทุกฟิลด์' แบบเปิดกว้าง** "
            "โดยเจตนา (ADR-0010 A-D2 ข้อ 6) · ไม่ว่าจะระบุอะไร ด่าน reason ยังตรวจ"
            "ทั้งไฟล์เสมอ และ cascade ของ D6 ไม่ฟังแฟล็กนี้เลย"
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
        help="ชื่อคนที่ตรวจซ้ำแล้วตัดสินว่าค่าเดิมผิด/คนที่เซ็นรับ/คนที่สั่งถอน — "
        "บังคับเมื่อ --commit (ADR-0010 D1)",
    )
    parser.add_argument(
        "--reviewed-at",
        metavar="<เวลาที่คุณตัดสิน ISO-8601 พร้อม timezone>",
        help="บังคับเมื่อ --commit หรือเมื่อใบงานมีแถวสั่ง SIGN แม้เป็น dry-run "
        "ก็ตาม (G1) · ค่านี้ถูกใช้เป็น verified_at ของแถวที่สั่ง SIGN ด้วย "
        "(ADR-0027) · 🔴 ไม่มี default เป็นเวลาปัจจุบัน (ADR-0010 D5) "
        "และค่าที่อยู่ในอนาคตถูกปฏิเสธ (เวลาที่คนตัดสินย้อนไปข้างหน้าไม่ได้)",
    )
    args = parser.parse_args()

    # 🔴 G1 (code-critic รอบ 1 ของ INF-29) — เดิม parse เฉพาะตอน --commit ทำให้
    # dry-run ส่ง args.reviewed_at เป็น str | None ดิบเข้า plan_writes()/
    # assert_signable() ตรง ๆ · ตอนนี้ parse **ไม่ว่าโหมดไหน** ทันทีที่มีค่าให้ parse
    # เพื่อให้ dry-run เห็น datetime เหมือน --commit เป๊ะ (assert_reviewed_at_
    # present_when_signing() ใน run() เป็นด่านที่บังคับว่าต้องมีค่าเมื่อมีแถว SIGN)
    #
    # 🔴 G1 (code-critic รอบ 2 ของ INF-29) — เดิมเช็คด้วย truthiness
    # (`if args.reviewed_at:`) ⇒ string ว่าง `""` เป็น falsy → ข้าม parse ไปเลย
    # แล้ว args.reviewed_at ยังเป็น `""` (str) ตกไปที่ plan_writes()/assert_signable()
    # ดิบ ๆ เหมือนบั๊กเดิมของ G1 รอบ 1 ทุกประการ (เพราะด่านตรวจแค่ `is not None` ซึ่ง
    # `""` ไม่ใช่ `None`) ⇒ เปลี่ยนเป็นเช็ค `is not None` ให้ `""` ตกเข้า parse แล้วถูก
    # ปฏิเสธเพราะไม่ใช่ ISO-8601 ที่ถูกต้อง (`datetime.fromisoformat("")` raise
    # ValueError → PrecheckError)
    if args.reviewed_at is not None:
        try:
            args.reviewed_at = _parse_reviewed_at(args.reviewed_at)
            # 🔴 จุดเดียวในโมดูลที่อ่านนาฬิกา — และอ่านเพื่อ **ปฏิเสธ** เท่านั้น
            # ไม่เคยถูกใช้เป็นค่าให้ `args.reviewed_at` (ADR-0010 D5 · มีเทส AST ล็อก)
            assert_not_in_the_future(args.reviewed_at, now=datetime.now(timezone.utc))
        except PrecheckError as exc:
            parser.error(str(exc))

    if args.commit:
        if not args.reviewed_by:
            parser.error("--commit ต้องระบุ --reviewed-by ด้วย (ADR-0010 D1)")
        if not args.reviewed_at:
            parser.error("--commit ต้องระบุ --reviewed-at ด้วย (ADR-0010 D5)")

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
