"""นำค่าที่ **คนกรอกเอง** จากใบงานเข้า `posters` — ADR-0015 (INF-11)

    ./venv/bin/python scripts/seed/make_manual_sheet.py                # 1. สร้างใบงาน
    # 2. คนเปิดรูปดู แล้วกรอก condition_grade / year / ... / publish เอง
    ./venv/bin/python scripts/seed/manual_entry.py                      # 3. dry-run (default)
    ./venv/bin/python scripts/seed/manual_entry.py --commit \
        --reviewed-by <ชื่อคุณ> \
        --reviewed-at <เวลาที่คุณตัดสิน ISO-8601 พร้อม timezone>

🔴 **ค่าตัวอย่างข้างบนเป็น placeholder ที่ก๊อปทั้งบรรทัดแล้วรันไม่ผ่านโดยตั้งใจ** —
ตัวอย่างที่เคยเขียนเป็นเวลาจริงถูกก๊อปมาทั้งบรรทัดเมื่อ 2026-08-08 แล้ว `reviewed_at`
ของ 232 แถวลงเป็น **เวลาในอนาคต 3.5 ชั่วโมง** · เส้นนี้แพงกว่าเส้นอื่นเพราะ
`--reviewed-at` ถูกใช้เป็น `published_at` ของแถวที่ `publish=Y` ด้วย (D4) —
ค่าที่ผิดตรงนั้นคือบันทึกผิดว่า *ใครสั่งเอาของขึ้นขายเมื่อไหร่* ·
`assert_not_in_the_future()` ปฏิเสธค่าที่อยู่ในอนาคตตั้งแต่ `main()` แล้ว (ADR-0010 D5)

## นี่คือ "เส้นทางที่ 3" ไม่ใช่ส่วนขยายของ `apply_suggestions.py`

ระบบมีเส้นทางเขียน `posters` สามเส้น **คนละแหล่ง คนละกฎ** (ADR-0015 D1):

| เส้นทาง | แหล่งของค่า | เขียนอะไรได้ |
|---|---|---|
| `seed_posters.py` | ไฟล์ export จาก TikTok (เครื่อง) | INSERT ครั้งแรกเท่านั้น · ห้ามแตะ 12 ฟิลด์ที่ต้องให้คนตรวจ |
| `apply_suggestions.py` | **AI อ่านรูป** แล้วคนเซ็นรับ | `release_date_text` ตัวเดียว (ADR-0010 D4 · D4.1) |
| **ไฟล์นี้** | **คนดูของจริงแล้วพิมพ์เอง** | 5 ฟิลด์ของ D2 + `published_at` |

🔴 **ห้ามยุบสองเส้นหลังเข้าด้วยกัน** — `ALLOWED_FIELDS` ของ `apply_suggestions.py`
ยังคงเป็น `release_date_text` ตัวเดียวและ **ห้ามขยาย** (ADR-0010 D4.1: ทบทวนหลัง P5)
เหตุผลไม่ใช่ว่าฟิลด์พวกนั้น "ยังไม่ถึงคิว" แต่เพราะเส้นนั้นรับค่าที่ **เครื่องเดา**
ส่วนเส้นนี้รับค่าที่ **คนพิมพ์** — ADR-0009 D6 แยกสองอย่างนี้ออกจากกันถาวร

## กฎที่บังคับในไฟล์นี้ (มาจาก ADR-0015 §Decision ตรง ๆ)

* **D2** — allowlist = `condition_grade` · `year` · `poster_type` ·
  `restoration_status` · `tmdb_id` เท่านั้น · `published_at` เขียนผ่านคอลัมน์
  `publish` ซึ่งมีด่านของตัวเอง (D4) · **ห้ามแตะ `needs_review` และ `status`**
  (ADR-0010 D2 · skill `poster-database` §3)
* **D3** — `UNKNOWN` เขียนได้ในเส้นทางนี้เส้นเดียว เพราะ ADR-0009 D2 กำหนดว่า
  `UNKNOWN` = *"คนตรวจใบจริงแล้วแต่ตัดสินไม่ได้"* ซึ่ง **คนเท่านั้น**พูดได้
* **D4** — `publish=Y` ต้องผ่าน 2 ด่านก่อน ไม่ใช่ปล่อยให้ DB โยน error:
  1. ต้องมี `condition_grade` (ในใบงานรอบนี้ หรือมีอยู่ใน DB แล้ว) — ไม่งั้นชน
     `ck_posters_published_requires_condition_grade` (ADR-0013 D3)
  2. ต้องมีรูป ≥ 1 รูป — **BR-06** ที่ ADR-0013 **OD-1** เลื่อนมาให้ INF-11 บังคับ
  · `publish=N` = **ไม่ทำอะไร ไม่ใช่การถอดออกจากชั้น** (ADR-0013 D6)
* **D5** — UPDATE เท่านั้น **ห้าม INSERT** · ใบที่ไม่มีใน DB = ข้าม ไม่ใช่สร้างใหม่
* **D6** — เขียนเฉพาะช่องที่ปลายทางเป็น `NULL` · **ไม่มีโหมดเขียนทับ**
  (หลักเดียวกับ ADR-0010 D6) → ช่องว่างในใบงาน = **ข้าม** ไม่ใช่เขียนทับด้วย `NULL`
  → สคริปต์ **idempotent โดยโครงสร้าง** รันซ้ำใบงานเดิมได้ไม่มีอะไรเปลี่ยน
* **D7** — ทุกการเขียนบันทึกลง `poster_attribute_reviews` หนึ่งแถวต่อหนึ่งฟิลด์
  (ADR-0010 D3) · `reviewed_by`/`reviewed_at` มาจาก argument ตอนรัน ไม่ใช่คอลัมน์ในไฟล์
* **D8** — dry-run เป็น default · ต้อง `--commit` · `--target dev|sit`
  **ไม่มี production ให้เลือกเลย** · `--target sit` ต้องรัน**ข้างในคอนเทนเนอร์ sit**
  (`.env.sit` ชี้ hostname `db` ซึ่งอยู่ใน docker network) และ `DATABASE_URL`
  **ต้องตรงกับ `.env.sit` เป๊ะ** ไม่มีทางผ่อน — ดู `assert_target()`
  ✅ **SIT พร้อมรับแล้ว** — ยืนยันกับ `poster_nung_db_sit` เมื่อ 2026-08-07: มีคอลัมน์
  `published_at` และมี CHECK `ck_posters_published_requires_condition_grade` ครบ
  (BL-75 ปิดส่วน schema ไปตั้งแต่ 2026-08-06) · **ที่ยังไม่มีคือ *ข้อมูล* — 0/117
  ทุกฟิลด์ที่คนกรอก** ขณะที่ dev เป็น 116/117 และ publish แล้ว → `docs/BACKLOG.md` **BL-83**
  ⚠️ ข้อความเดิมตรงนี้เขียนว่า "SIT ยังไม่พร้อมรับจริง (ตามหลัง migration 2 ตัว · ไม่มี
  `published_at` · ไม่มี CHECK)" ซึ่ง**ตกยุคไปแล้วและทำให้เข้าใจผิดว่าเส้นทางนี้ยังใช้ไม่ได้**

## รูปแบบใบงาน

สร้างด้วย `make_manual_sheet.py` — 13 คอลัมน์ (ตัวเลขนี้ล้าสมัยได้ง่าย — ดู
`MANUAL_SHEET_COLUMNS` เป็นความจริงเสมอ ไม่ใช่รายชื่อนี้):

    poster_uuid,title,image_url,condition_grade,year,poster_type,
    restoration_status,tmdb_id,width_in,height_in,count_actual,publish,note

| คอลัมน์ | ใครกรอก | สคริปต์นี้ใช้ทำอะไร |
|---|---|---|
| `poster_uuid` | เครื่อง | ระบุใบ |
| `title` · `image_url` | เครื่อง | ให้คนเปิดรูปดูตอนกรอก — **สคริปต์ไม่แตะเลย** |
| 7 ฟิลด์ของ D2/D9 (รวม `width_in`/`height_in`) | **คน** (เครื่องเติมค่าที่มีอยู่แล้วมาให้ดู) | เขียนลง `posters` เมื่อปลายทางเป็น `NULL` |
| `count_actual` | **คน** | **ไม่เขียนลง `posters` เลย** (ไม่มีปลายทาง — ADR-0019 D5) เป็น input ของประตู publish เท่านั้น (ADR-0019 D9 ข้อ 2 · A-D2) — ว่าง = ยังไม่นับ · `0` = blocker · `≥2` บนเกรดที่ไม่ใช่ mint = blocker |
| `publish` | **คน** | `Y` = เปิดขาย (เขียน `published_at`) · `N`/ว่าง = ไม่ทำอะไร |
| `note` | **คน** | 🔴 **บันทึกของคนล้วน ๆ ไม่ถูกเขียนลง DB เลยสักที่** — ไม่มีคอลัมน์ปลายทาง (`restoration_note` เป็นเนื้อหาหน้าร้าน ต้องมีรอบของตัวเอง ADR-0015 §ที่จงใจไม่รวม) |

## แถวไหนถูกข้าม แถวไหนทำทั้งไฟล์พัง

**ข้ามเฉย ๆ (ปกติ ไม่ใช่ error):** ช่องว่าง · ปลายทางมีค่าอยู่แล้ว · ใบไม่มีใน DB ·
`publish` ว่างหรือ `N` · ใบที่ publish ไปแล้ว — ใบงานที่กรอกไปได้ครึ่งเดียวเป็นเรื่องปกติ

**ทั้งไฟล์ถูกปฏิเสธ ไม่เขียนอะไรเลย (fail-closed):**
`poster_uuid` ไม่ใช่ UUID · `poster_uuid` ซ้ำ · ค่านอก enum · ปีนอกช่วง ·
`tmdb_id` ไม่ใช่จำนวนเต็มบวก · `publish` เป็นคำที่ไม่รู้จัก ·
**`publish=Y` โดยยังไม่มีเกรด** · **`publish=Y` โดยใบนั้นไม่มีรูป** ·
**`publish=Y` โดย `count_actual = 0`** (ADR-0019 D9 ข้อ 2) ·
**`publish=Y` โดย `count_actual ≥ 2` บนเกรดที่ไม่ใช่ `mint`** (ADR-0019 D1) ·
`count_actual` ที่กรอกมาไม่ใช่จำนวนเต็ม ≥ 0 (ผิดรูปแบบ — ไม่ใช่ blocker เพราะไม่ต้อง
รู้สถานะ DB ก็รู้ว่าผิด)
— พวกนี้แปลว่าคนกรอกเข้าใจกติกาไม่ตรงกัน การ apply บางส่วนจะทำให้ตามยากภายหลัง
"""

from __future__ import annotations

import argparse
import os
import sys
import uuid
from collections.abc import Callable
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
from scripts.seed.apply_suggestions import (  # noqa: E402
    _APPROVED_WORDS,
    _REJECTED_WORDS,
    _load_env,
    _parse_env_file,
    assert_target_database,
)

DEFAULT_MANUAL_CSV = SEED_DIR / "manual-entry.csv"
SIT_ENV_FILE = ".env.sit"
TARGETS = ("dev", "sit")  # 🔴 ไม่มี production และห้ามเพิ่มโดยไม่แก้ ADR-0015 D8


def assert_target(database_url: str, target: str) -> str:
    """ยืนยันปลายทาง — **เข้มกว่า** `assert_target_database()` ของ ADR-0010 D7 หนึ่งชั้น

    ชั้นแรกคือกฎเดิมทั้งชุด (import มาใช้ ไม่ก๊อป): host ต้อง local เมื่อ target=dev ·
    ชื่อ database ห้ามมี `prod`/`uat`/`stage` · `DATABASE_URL` ห้ามตรงกับ
    `.env.uat`/`.env.production`

    ชั้นที่สองคือของ ADR-0015 D8 (amendment): **`--target sit` ต้องตรงกับ `.env.sit` เป๊ะ
    เท่านั้น ไม่มีทางผ่อน**

    🔴 ทำไมต้องมีชั้นที่สอง — `assert_target_database()` มีทางผ่อนอยู่หนึ่งทาง: ถ้า
    **ไม่มีไฟล์ `.env.sit`** (หรือในไฟล์ไม่มี `DATABASE_URL`) มันจะยอมรับ url ใดก็ได้ที่
    *ชื่อ database มีคำว่า `sit`* ปนอยู่ · ทางนั้นตั้งใจไว้ให้เครื่องที่ไม่มีไฟล์ env ครบ
    แต่สำหรับสคริปต์นี้มันแปลว่าใครก็ตามที่ลบ/เปลี่ยนชื่อ `.env.sit` แล้วตั้ง
    `DATABASE_URL` ชี้ database อะไรก็ได้ที่ตั้งชื่อให้มีคำว่า `sit` จะเขียนทะลุเข้าไปได้
    — บนเส้นทางที่เขียน `condition_grade` และ `published_at` ราคาของความผิดพลาดนั้นสูงเกิน
    (fail-closed: ไม่มีไฟล์ = ไม่ให้รัน ไม่ใช่ = ให้ผ่าน)
    """
    label = assert_target_database(database_url, target)  # กฎเดิมทั้งหมด ไม่ผ่อนสักข้อ
    if target != "sit":
        return label

    sit_url = _parse_env_file(REPO_ROOT / SIT_ENV_FILE).get("DATABASE_URL", "")
    if not sit_url:
        raise PrecheckError(
            f"--target sit แต่หา DATABASE_URL ใน {SIT_ENV_FILE} ไม่เจอ "
            f"(ไฟล์ไม่มี หรือมีแต่ไม่มีคีย์นั้น) — ยืนยันปลายทางไม่ได้จึงไม่รัน\n"
            "ADR-0015 D8 ไม่รับการเดาจากชื่อ database ต่างจาก ADR-0010 D7"
        )
    # 🔴 **ไม่มีการเทียบ `sit_url != database_url` ที่นี่โดยตั้งใจ** ‹ลบออก 2026-08-30 ·
    # `INF-39` M-2 จาก `code-critic` · หลัก `INF-17` **AC-2**: *โค้ดตายที่ดูเหมือนมีการ
    # ป้องกัน อันตรายกว่าไม่มีเลย* เพราะคนอ่านจะนึกว่ามีด่านอยู่แล้วจึงไม่เพิ่มด่านที่จำเป็น›
    #
    # เหตุผลที่มันตาย: `assert_target_database()` ข้างบน **อ่านไฟล์เดียวกันด้วยตัวอ่าน
    # เดียวกัน** แล้วปฏิเสธไปแล้วทุกกรณีที่ค่าไม่ตรง ⇒ โค้ดที่เดินมาถึงบรรทัดนี้ได้
    # แปลว่า `sit_url == database_url` เสมอ · มี mutation ยืนยัน: ลบบล็อกนั้นทิ้งทั้งก้อน
    # แล้วชุดเทสยังเขียว 100% (คือไม่มีอะไรพิสูจน์มันเลยแม้แต่ตัวเดียว)
    #
    # 🔴 **สิ่งที่ทำให้มันตายคือ *เงื่อนไข* ไม่ใช่ *ความบังเอิญ*** — สองชั้นต้องอ่าน
    # ไฟล์เดียวกันด้วยตัวอ่านเดียวกัน · ถ้าวันหนึ่งข้อนั้นไม่จริง (คนละ `REPO_ROOT` ·
    # คนละชื่อไฟล์ · คนละตัวอ่าน) ด่านนี้จะกลับมาจำเป็นทันที
    # ⇒ ล็อกเงื่อนไขนั้นไว้ด้วยเทสแทนการเก็บโค้ดที่ไม่ทำงานไว้:
    #   `test_env_file_expansion.py::test_both_guard_layers_read_the_same_file_with_the_same_reader`
    #   `test_env_file_expansion.py::test_layer_one_rejects_every_mismatch_so_layer_two_has_nothing_left`
    #
    # สิ่งที่ชั้นนี้ยัง **บังคับจริง** คือ `if not sit_url` ข้างบน — ทางที่ ADR-0010 D7
    # ผ่อนไว้ (ไม่มีไฟล์ = เดาจากชื่อ database) และ ADR-0015 D8 ปิด · ทางนั้น **เข้าถึงได้จริง**
    # และมีเทสของตัวเอง (`test_sit_refuses_to_run_when_env_sit_is_missing`)
    return label


# คอลัมน์ของใบงาน — `make_manual_sheet.py` import ไปใช้ ไม่ประกาศซ้ำสองที่
MANUAL_SHEET_COLUMNS = (
    "poster_uuid",
    "title",
    "image_url",
    "condition_grade",
    "year",
    "poster_type",
    "restoration_status",
    "tmdb_id",
    "width_in",
    "height_in",
    "count_actual",
    "publish",
    "note",
)
# 🔢 `count_actual` — ผลนับใบจริงล่าสุด (ADR-0019 D10 · A-D2 · ADR-0024 D5) —
# **ไม่ใช่ฟิลด์ของ `posters`** ไม่มีคอลัมน์ปลายทางให้เขียน (D5: ไม่เพิ่ม `quantity`)
# จึง**ไม่อยู่ใน `REQUIRED_COLUMNS`/`ALLOWED_FIELDS`ทั้งคู่** — มันเป็น *input ของ
# ประตู publish* เท่านั้น (ดู `plan_writes()` §D9 ข้อ 2) `make_manual_sheet.py`
# เขียนเป็นค่าว่างเสมอเช่นเดียวกับ `publish` — เครื่องกรอกให้เมื่อไหร่คือเครื่องนับ
# ของแทนคน
# 🔴 **ห้ามลบคอลัมน์นี้ออกจาก `MANUAL_SHEET_COLUMNS`** — ถ้าไม่อยู่ในนี้ คอลัมน์ที่
# เจ้าของเติมมือไว้จะหายทั้งคอลัมน์ในวินาทีที่มีคนสร้างใบงานใหม่ (A-D2 ข้อ 1)
# 📏 `width_in`/`height_in` — **ขนาดที่วัดจากใบจริง หน่วยนิ้ว** (ทศนิยมได้: `27` · `41` · `20.5`)
# ADR-0009 **D16** รับ *การวัด* เป็น input เดียวของ `size_format` · คอลัมน์ `size` ที่มีอยู่
# เป็น `size_guess` ที่ **D4 ห้ามใช้เป็น input** ไปแล้ว — และในของจริงมันเป็นสตริงเดียวกัน
# ทั้งแคตตาล็อก (`27x40` 116/117 แถว จาก `size_guess` ของไฟล์ export) จึงไม่มีสารสนเทศเลย
# ✅ **เขียนลง DB ได้แล้ว** ตั้งแต่ migration `c5a8f31e64d7` + ADR-0015 **Amendment D9**
# (ข้อความเดิมของบล็อกนี้เขียนว่า "ยังไม่มีคอลัมน์ปลายทาง" — จริงอยู่ช่วง 2026-08-08 เช้า
# ระหว่างที่ยังรอสัญญานิ่ง · เก็บไว้เป็นบันทึกว่าเคยเป็นสถานะเดียวกับ `note`)
# 🔴 **ห้ามกรอก `size_format` ลงใบงานนี้** — มันเป็นค่า *derive* จากสองช่องนี้ตามตาราง D16
# ช่องกรอกเองจะกลายเป็นแหล่งความจริงที่สอง (หลักเดียวกับ ADR-0014 D22/AC-3 ของ INF-13)
# คอลัมน์ที่สคริปต์นี้ *ใช้จริง* — `title`/`image_url`/`note` เป็นข้อมูลให้คนอ่าน
# ขาดได้ไม่เป็นไร (แต่ generator ใส่มาให้เสมอ)
REQUIRED_COLUMNS = (
    "poster_uuid",
    "condition_grade",
    "year",
    "poster_type",
    "restoration_status",
    "tmdb_id",
    "width_in",
    "height_in",
    "publish",
)

# ADR-0015 D2 (+ **Amendment D9** 2026-08-08) — 7 ฟิลด์นี้เท่านั้น · `published_at`
# ไม่อยู่ในนี้โดยตั้งใจ เพราะไม่ใช่ค่าที่รับจากคอลัมน์ในไฟล์ แต่เป็นผลของคอลัมน์
# `publish` ที่มีด่านของตัวเอง (D4)
#
# `width_in`/`height_in` เข้ามาที่ **D9** ด้วยเกณฑ์เดียวกับ 5 ตัวแรกทุกข้อ: ว่างทั้งตาราง ·
# คนตอบได้จากการดูใบเอง · **เครื่องเดาแทนไม่ได้ตลอดกาล** (ADR-0009 D16 — รูปถ่ายไม่มี
# สเกลอ้างอิง และ `size` ที่มีอยู่คือ `size_guess` ที่ D4 ห้ามใช้)
ALLOWED_FIELDS = (
    "condition_grade",
    "year",
    "poster_type",
    "restoration_status",
    "tmdb_id",
    "width_in",
    "height_in",
)
# ฟิลด์ที่ **สคริปต์คำนวณเอง** — ไม่มีช่องในใบงาน ไม่มี spec ให้ parse
# 🔴 `size_format` ห้ามมีคอลัมน์ในใบงานเด็ดขาด — D16 ให้ derive จาก width_in/height_in
# ผ่าน `app.core.size_format.derive_size_format()` ตัวเดียว (D4: mapping ตัวเดียว) ·
# ช่องให้กรอกเองจะกลายเป็นแหล่งความจริงที่สองทันที (หลักเดียวกับ ADR-0014 D22/AC-3
# ที่ห้ามใบงานของ INF-13 มีช่อง `verification_status`)
DERIVED_FIELDS = ("size_format",)
# ฟิลด์เดียวที่ `--allow-overwrite` รับได้ — ADR-0010 §Amendment D8 (2026-08-07)
# 🔴 **ห้ามเพิ่มโดยไม่แก้ ADR** · โดยเฉพาะ `condition_grade` (BR-05 — ลูกค้าใช้ตัดสินใจซื้อ
# บนระบบที่คืนเงินอัตโนมัติไม่ได้) และ `published_at` (เป็นเหตุการณ์ ไม่ใช่คุณสมบัติ
# การทับคือการปลอมประวัติ) ซึ่ง D8 ห้ามไว้ตลอดกาล
OVERWRITE_ELIGIBLE = ("title", "year")
# ฟิลด์ที่ต้องอ่านค่าปัจจุบันจาก DB — ALLOWED_FIELDS + ฟิลด์ที่ทับได้แต่ไม่ได้อยู่ใน allowlist
# (`title`) · ต้องอ่านมาเสมอแม้ไม่ได้ขอ overwrite เพราะ `plan_writes()` ต้องเทียบค่าเดิม
# เพื่อตัดสินว่า "ค่าเท่าเดิม" หรือ "ทับจริง"
STATE_FIELDS = ALLOWED_FIELDS + tuple(
    f for f in OVERWRITE_ELIGIBLE if f not in ALLOWED_FIELDS
)
# ฟิลด์ที่ต้องอ่านค่าปัจจุบันจาก DB **ทั้งหมด** — รวม derived ด้วย เพราะ `plan_writes()`
# ต้องรู้ว่า `size_format` มีค่าอยู่แล้วหรือยัง ถึงจะตัดสินได้ว่าเขียนทับ (ห้าม — D6)
# หรือขัดกับสิ่งที่วัดได้ (ต้องปฏิเสธทั้งไฟล์)
READ_FIELDS = STATE_FIELDS + DERIVED_FIELDS
# ชื่อคอลัมน์ที่ audit trail ใช้บันทึกการเปิดขาย — ต้องตรงกับชื่อคอลัมน์จริงบน `posters`
PUBLISH_FIELD = "published_at"
# CHECK ของ ADR-0013 D3 — ต้องมีอยู่ **ที่ปลายทาง** ไม่ใช่แค่ใน `app/models/poster.py`
# ชื่อต้องตรงกับ migration และ `__table_args__` เป๊ะ (ADR-0013 D3 บังคับไว้)
PUBLISH_CHECK_CONSTRAINT = "ck_posters_published_requires_condition_grade"

# ปีที่หนังฉาย — ล่างสุดคือยุคเริ่มมีภาพยนตร์ฉายจริง บนสุดเผื่อใบ advance ของอนาคต
# 🔴 นี่เป็นด่านที่ *สคริปต์* เท่านั้น — `posters.year` ยังไม่มี CheckConstraint
# (`screens.yaml` INF-06 known_gaps ข้อ 4) การเขียนผ่าน psql ตรง ๆ ยังใส่ปีบ้า ๆ ได้อยู่
YEAR_MIN, YEAR_MAX = 1888, 2100
# ช่วงขนาดที่ยอมรับ (นิ้ว) — ADR-0009 D16 ไม่ได้กำหนดไว้ ตัวเลขนี้เป็นด่านกันพิมพ์ผิด
# ไม่ใช่กฎธุรกิจ: ใบเล็กสุดที่เจอจริงคือใบไทย ~21×31 และใหญ่สุดในตาราง SizeFormat คือ
# quad 30×40 · `99.99` คือเพดานของคอลัมน์ Numeric(5, 2) พอดี
INCHES_MIN, INCHES_MAX = Decimal("1"), Decimal("99.99")


# --------------------------------------------------------------------------
# นิยามฟิลด์ + การตรวจรูปแบบ (pure — ไม่แตะ DB)
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class FieldSpec:
    """วิธีอ่านค่าหนึ่งฟิลด์จากใบงาน และวิธีเขียนกลับลงใบงาน."""

    name: str
    parse: Callable[[str], Any]
    hint: str


def _enum_parser(
    enum_cls: type[Enum], *, exact_case: bool = False
) -> Callable[[str], Enum]:
    """รับเฉพาะค่าที่อยู่ใน enum จริง — ผิดแม้ตัวเดียวหยุดทั้งไฟล์

    **ปริยาย: เทียบแบบไม่สนตัวพิมพ์** เพราะ enum ของโปรเจกต์นี้ปนกันสองแบบอยู่แล้ว
    (`condition_grade` เป็น lowercase ตั้งแต่ก่อน ADR-0009 · enum ใหม่เป็น UPPERCASE
    ตาม skill `poster-database` §5) การบังคับให้คนพิมพ์ถูกเคสทั้งสองแบบในไฟล์เดียว
    เป็นกับดักที่ไม่ได้อะไรกลับมา · ไม่มีสมาชิกคู่ไหนชนกันเมื่อ lower ทั้งหมด

    🔴 **`exact_case=True` สำหรับฟิลด์ที่ลูกค้าใช้ตัดสินใจซื้อ** (วันนี้มีตัวเดียว:
    `condition_grade` — BR-05) · เหตุผลที่ต่างจากฟิลด์อื่น: การแปลงเงียบ ๆ แปลว่า
    **ไม่มีใครรู้ว่าคนกรอกตั้งใจพิมพ์อะไร** — `Fine` อาจเป็นการพิมพ์ลวก หรืออาจเป็น
    สัญญาณว่าคนกรอกกำลังใช้สเกลคนละชุดในหัว (เช่นสเกล CGC ที่เขียน Fine ตัวใหญ่)
    ฟิลด์อื่นผิดแล้วแก้ได้ ฟิลด์นี้ผิดแล้วลูกค้าจ่ายเงินไปแล้ว

    *หลักฐานว่าปัญหานี้เกิดจริง:* `manual-entry.csv` มี `Fine` 8 แถวและ `Good` 3 แถว
    ที่ถูกแปลงเงียบ ๆ เข้า DB ไปแล้วเมื่อ 2026-08-07 ก่อนที่ใครจะเห็น (แก้ในไฟล์แล้ว)

    ⚠️ **ห้ามเปิด `exact_case` ให้ `poster_type`/`restoration_status`** โดยไม่ตรวจไฟล์ก่อน —
    วันนี้ `manual-entry.csv` มี `Unknown` (ตัวพิมพ์ผสม) อยู่ 2 แถว ซึ่งผ่านได้เพราะ
    ค่าปริยายนี้เท่านั้น · enum จริงเป็น `UNKNOWN`
    """
    if exact_case:
        lookup = {member.value: member for member in enum_cls}
    else:
        lookup = {member.value.lower(): member for member in enum_cls}

    def parse(raw: str) -> Enum:
        member = lookup.get(raw if exact_case else raw.lower())
        if member is None:
            allowed = " · ".join(m.value for m in enum_cls)
            # แยกข้อความของ "เคสผิด" ออกจาก "ค่าไม่มีจริง" — สองอย่างนี้แก้คนละวิธี
            # และถ้าบอกรวมกัน คนกรอกจะไปหาว่าพิมพ์ค่าอะไรผิดทั้งที่ค่าถูกอยู่แล้ว
            if exact_case and raw.lower() in {m.value.lower() for m in enum_cls}:
                correct = next(
                    m.value for m in enum_cls if m.value.lower() == raw.lower()
                )
                raise ValueError(
                    f"{raw!r} ตัวพิมพ์ไม่ตรง — ต้องเป็น {correct!r} เป๊ะ "
                    f"(ฟิลด์นี้ลูกค้าใช้ตัดสินใจซื้อ สคริปต์จึงไม่แปลงให้เอง)"
                )
            raise ValueError(f"{raw!r} ไม่อยู่ใน enum — ใช้ได้: {allowed}")
        return member

    return parse


def _inches_parser(low: Decimal, high: Decimal) -> Callable[[str], Decimal]:
    """ขนาดที่วัดได้ หน่วยนิ้ว — ADR-0009 D16

    🔴 **`Decimal(raw)` ไม่ใช่ `float(raw)`** — `derive_size_format()` เทียบค่าแบบเป๊ะ
    กับตาราง mapping ของ D16 · `float("27.1")` ไม่ใช่ 27.1 จริง ๆ ในฐานสอง ผลของ
    การเทียบจึงขึ้นกับเส้นทางที่ค่าเดินทางมา ซึ่งเป็นสิ่งที่ D4 ห้าม (deterministic)

    ปฏิเสธ `NaN`/`Infinity` ที่ `Decimal()` รับเข้ามาโดยปริยาย — ทั้งคู่ผ่านการเทียบ
    ช่วงข้างล่างแบบเงียบ ๆ ไม่ได้ (`NaN` ทำให้ทุกการเปรียบเทียบเป็นเท็จ จึงตกที่
    ข้อความ "อยู่นอกช่วง" ซึ่ง*อ่านแล้วเข้าใจผิด*) — ดักด้วย `is_finite()` ก่อน
    """

    def parse(raw: str) -> Decimal:
        try:
            value = Decimal(raw)
        except InvalidOperation:
            raise ValueError(f"{raw!r} ไม่ใช่ตัวเลข") from None
        if not value.is_finite():
            raise ValueError(f"{raw!r} ไม่ใช่ตัวเลขที่วัดได้")
        if not low <= value <= high:
            raise ValueError(f"{value} อยู่นอกช่วง {low}–{high} นิ้ว")
        if -value.as_tuple().exponent > 2:
            # คอลัมน์เป็น Numeric(5, 2) — PostgreSQL จะ **ปัดให้เงียบ ๆ** ถ้าปล่อยผ่าน
            # แล้วค่าที่เก็บจะไม่ตรงกับที่คนกรอก โดยไม่มีอะไรฟ้อง
            raise ValueError(f"{value} มีทศนิยมเกิน 2 ตำแหน่ง")
        return value

    return parse


def _int_parser(low: int, high: int) -> Callable[[str], int]:
    def parse(raw: str) -> int:
        try:
            value = int(raw)
        except ValueError:
            raise ValueError(f"{raw!r} ไม่ใช่จำนวนเต็ม") from None
        if not low <= value <= high:
            raise ValueError(f"{value} อยู่นอกช่วง {low}–{high}")
        return value

    return parse


def _title_parser(raw: str) -> str:
    """ชื่อเรื่องที่แสดงบนหน้าร้าน — ตรวจแค่สิ่งที่ตรวจได้ ไม่ตัดสินความถูกของชื่อ

    🔴 **ตัดช่องว่างหัวท้ายเสมอ** — `Hobbit: The Battle of the Five Armies ` ที่มี
    เว้นวรรคเกินท้ายสตริงเป็นเคสจริงใน `manual-entry.csv` (BL-87) ซึ่งมองไม่เห็นด้วยตา
    และทำให้เทียบสตริงพลาดตลอดไป

    ไม่ตรวจการสะกด ไม่บังคับตัวพิมพ์ — **สคริปต์ไม่มีทางรู้ว่าชื่อไหนถูก** และ BL-87
    บันทึกไว้แล้วว่ามีชื่อที่ดูเหมือนผิดแต่เป็นชื่อร้านที่ตั้งใจ (`F9` · `TURTLE NINJA`)
    """
    value = raw.strip()
    if not value:
        raise ValueError("ชื่อเรื่องว่าง — ปล่อยช่องว่างไว้ถ้าไม่ต้องการแก้")
    return value


@lru_cache(maxsize=1)
def field_specs() -> dict[str, FieldSpec]:
    """นิยามของ 5 ฟิลด์ใน `ALLOWED_FIELDS` + `title` ที่เขียนได้เฉพาะโหมด overwrite

    import `app.models.enums` **ข้างในฟังก์ชัน** เพราะ `app/models/__init__.py`
    ลาก `app.core.database` ตามมาด้วย ซึ่งต้องการ env ครบตอน import — ส่วนบนของไฟล์นี้
    ต้อง import ได้ก่อน `_load_env()` จะถูกเรียก (หลักเดียวกับ `plan_writes()`
    ของ `apply_suggestions.py`)

    🔴 ค่าที่รับได้มาจาก enum จริงเสมอ **ห้ามก๊อปรายชื่อค่ามาเขียนซ้ำที่นี่** —
    วันที่มีใครเพิ่มค่าเข้า enum แล้วลืมแก้สคริปต์ จะกลายเป็นค่าที่ DB รับแต่ใบงานไม่รับ
    """
    from app.models.enums import PosterCondition, PosterType, RestorationStatus

    return {
        # 🔴 `title` **ไม่อยู่ใน ALLOWED_FIELDS** — เขียนได้เฉพาะเมื่อส่ง
        # `--allow-overwrite title` (ADR-0010 §Amendment D8) · ทุกใบมีชื่ออยู่แล้ว
        # การเขียนตอนเป็น NULL จึงไม่เคยเกิดขึ้นจริงและไม่ต้องรองรับ
        "title": FieldSpec(
            name="title",
            parse=_title_parser,
            hint="ชื่อเรื่องที่แสดงบนหน้าร้าน — แก้ได้เฉพาะโหมด --allow-overwrite title",
        ),
        "condition_grade": FieldSpec(
            name="condition_grade",
            # 🔴 exact_case — ฟิลด์เดียวในไฟล์นี้ที่ลูกค้าใช้ตัดสินใจซื้อ (BR-05)
            # เหตุผลเต็มอยู่ที่ docstring ของ _enum_parser() ห้ามเขียนซ้ำที่นี่
            parse=_enum_parser(PosterCondition, exact_case=True),
            # ADR-0003 §Consequence — ลำดับสวนสัญชาตญาณ (fine ดีกว่า very_good)
            # ใบงานจึงต้องบอกลำดับ ไม่ใช่แค่รายชื่อค่า
            hint=(
                "เรียงดี→แย่: "
                + " > ".join(m.value for m in PosterCondition)
                + " · ตัวพิมพ์เล็กทั้งหมด ต้องตรงเป๊ะ"
            ),
        ),
        "year": FieldSpec(
            name="year",
            parse=_int_parser(YEAR_MIN, YEAR_MAX),
            hint=f"ปีที่หนังฉาย (ค.ศ. {YEAR_MIN}–{YEAR_MAX}) — ไม่ใช่ปีที่พิมพ์ใบ",
        ),
        "poster_type": FieldSpec(
            name="poster_type",
            parse=_enum_parser(PosterType),
            hint=" · ".join(m.value for m in PosterType),
        ),
        "restoration_status": FieldSpec(
            name="restoration_status",
            parse=_enum_parser(RestorationStatus),
            hint=" · ".join(m.value for m in RestorationStatus),
        ),
        "tmdb_id": FieldSpec(
            name="tmdb_id",
            parse=_int_parser(1, 2_147_483_647),  # ช่วงของ INTEGER บน PostgreSQL
            hint="id ของหนังบน TMDB (จำนวนเต็มบวก)",
        ),
        # 📏 ADR-0009 D16 — วัดจากใบจริงเท่านั้น · **ห้ามคัดจากช่อง `size` เดิม**
        # (`size_guess` · D4 ห้ามใช้เป็น input · และเป็นค่าเดียวกันทั้งแคตตาล็อกอยู่แล้ว
        # จึงไม่มีอะไรให้คัด) · hint บอก "กว้าง × สูง" เพราะลำดับด้านมีความหมายในตาราง D16
        "width_in": FieldSpec(
            name="width_in",
            parse=_inches_parser(INCHES_MIN, INCHES_MAX),
            hint="ด้าน**กว้าง**ที่วัดจากใบจริง หน่วยนิ้ว ทศนิยมได้ 2 ตำแหน่ง (27 · 20.5)",
        ),
        "height_in": FieldSpec(
            name="height_in",
            parse=_inches_parser(INCHES_MIN, INCHES_MAX),
            hint="ด้าน**สูง**ที่วัดจากใบจริง หน่วยนิ้ว ทศนิยมได้ 2 ตำแหน่ง (40 · 41)",
        ),
    }


def render_value(value: Any) -> str:
    """ค่าจาก DB → ข้อความในใบงาน (และใน audit trail) — จุดเดียวที่แปลง."""
    if value is None:
        return ""
    if isinstance(value, Enum):
        return str(value.value)
    return str(value)


class Publish(str, Enum):
    """สิ่งที่คนกรอกในคอลัมน์ `publish`."""

    PENDING = "PENDING"  # ว่าง — ยังไม่ตัดสิน
    YES = "YES"
    NO = "NO"


@dataclass(frozen=True)
class ManualRow:
    """หนึ่งแถวของใบงานที่ผ่านการตรวจรูปแบบแล้ว."""

    poster_uuid: uuid.UUID
    # เฉพาะฟิลด์ที่คนกรอกจริง — ช่องว่างไม่เข้ามาใน dict นี้เลย (D6: ว่าง = ข้าม
    # ไม่ใช่เขียนทับด้วย NULL) การแยกตรงนี้ทำให้ชั้นล่างไม่ต้องรู้จัก "ค่าว่าง" อีก
    values: dict[str, Any]
    publish: Publish
    # ผลนับใบจริงล่าสุด — `None` = "ยังไม่นับ" (ต่างจาก `0` ซึ่งคือ "นับแล้วไม่มีของ")
    # ไม่ใช่ฟิลด์ที่เขียนลง `posters` (ไม่มีปลายทาง — ADR-0019 D5) เป็นแค่ input ของ
    # ประตู publish ใน `plan_writes()` (ADR-0019 D9 ข้อ 2 · A-D2)
    count_actual: int | None
    lineno: int


def read_manual_sheet(path: Path) -> list[dict[str, str]]:
    if not path.is_file():
        raise PrecheckError(
            f"ไม่พบใบงาน {path}\n"
            "สร้างด้วย `./venv/bin/python scripts/seed/make_manual_sheet.py` ก่อน "
            "แล้วให้คนเปิดรูปดูและกรอกเอง"
        )
    return read_sheet_rows(
        path,
        required_columns=REQUIRED_COLUMNS,
        sheet_columns=MANUAL_SHEET_COLUMNS,
        maker_script="make_manual_sheet.py",
        free_text_columns=("note",),
    )


def _parse_publish(raw: str) -> Publish:
    lowered = raw.lower()
    if not lowered:
        return Publish.PENDING
    if lowered in _APPROVED_WORDS:
        return Publish.YES
    if lowered in _REJECTED_WORDS:
        return Publish.NO
    raise ValueError(raw)


def _parse_count_actual(raw: str) -> int | None:
    """`count_actual` — ผลนับใบจริงล่าสุด (ADR-0019 D10 · A-D2 ข้อ 3)

    ว่าง → `None` = **"ยังไม่นับ"** ไม่ใช่ error — วันนี้ว่าง 117/117 การทำเป็น
    fail-closed ที่นี่คือด่านที่ปฏิเสธข้อมูลที่ถูกอยู่แล้วทั้งไฟล์ตั้งแต่วันแรก
    (A-D2 ข้อ 2) · มีค่า → ต้องเป็นจำนวนเต็ม ≥ 0 เท่านั้น ค่าอื่น (ติดลบ/ไม่ใช่
    ตัวเลข/ทศนิยม) เป็นความผิดรูปแบบ ปฏิเสธทั้งไฟล์เหมือนฟิลด์อื่นทุกตัวในไฟล์นี้

    🔴 **แยกจาก "0 คือ blocker"** โดยตั้งใจ — `0` เป็นค่าที่ *อ่านออก* (ไม่ใช่ความผิด
    รูปแบบ) แต่เป็นนโยบายที่ *ห้ามเปิดขาย* ด่านนั้นอยู่ที่ `plan_writes()` เพราะ
    ต้องรู้ด้วยว่าแถวนี้กำลัง publish อยู่หรือเปล่า (ทรงเดียวกับที่ `is_unique = N`
    ของเส้นที่ 5 แยกด่าน "อ่านออก" กับด่าน "เขียนได้ไหม" ออกจากกัน)
    """
    if not raw:
        return None
    try:
        value = int(raw)
    except ValueError:
        raise ValueError(f"{raw!r} ไม่ใช่จำนวนเต็ม") from None
    if value < 0:
        raise ValueError(f"{value} ติดลบ — จำนวนใบจริงติดลบไม่ได้")
    return value


def load_count_actual_by_poster(path: Path) -> dict[uuid.UUID, int | None]:
    """`count_actual` ต่อ `poster_uuid` จาก `manual-entry.csv` — บ้านของ `count_actual`
    (ADR-0019 D10 · A-D2) ตัวนี้เป็นพาร์เซอร์ตัวเดียว **ใช้ร่วมกันเส้นที่ 6 และเส้นที่ 5**

    🔴 **ย้ายมาที่นี่ 2026-08-16 (INF-29 ขั้นที่ 1)** — เดิมชื่อ `_load_counts()` อยู่ใน
    `split_entry.py` ทั้งที่ไฟล์นี้เป็นเจ้าของ `read_manual_sheet()`/`_parse_count_actual()`
    ที่มันเรียกอยู่แล้ว การอยู่คนละไฟล์ทำให้ทั้งเส้นที่ 5 และเส้นที่ 6 ต้อง import ข้าม
    เส้นที่ 6 แทน (ทิศทาง import กลับหัว — `_shared.py` เตือนเรื่องนี้ไว้แล้ว) · ย้ายมาไว้
    บ้านของ parser เอง แล้วให้ทั้งสองเส้น **import object เดียวกัน** (เทส identity ที่
    `tests/unit/test_seed_lane_shared_rules.py`)

    แยกสองเคสที่ทำให้ precheck ไม่ผ่านออกจาก "ยังไม่มีใครนับ" อย่างชัดเจน:
    - **ไม่พบไฟล์เลย** → `PrecheckError` จาก `read_manual_sheet()` เอง (ก่อนถึงฟังก์ชัน
      นี้ด้วยซ้ำ)
    - **พบไฟล์แต่ header ไม่มีคอลัมน์ `count_actual`** (ใบงานรุ่นเก่าที่สร้างก่อน
      ADR-0019 A-D2 แล้วยังไม่ regenerate) → `PrecheckError` ที่นี่ — ต่างจาก "ค่าว่าง"
      ตรงที่คอลัมน์**ไม่มีอยู่เลย** ไม่ใช่มีอยู่แต่ยังไม่กรอก

    "ยังไม่มีใครนับ" (คอลัมน์มีอยู่แต่ค่าว่าง หรือไม่มีแถวของ poster นี้เลยในไฟล์) →
    คืน `None` สำหรับ poster นั้น — ผู้เรียกแปลเป็นด่านของตัวเอง (เส้นที่ 6:
    `SKIP_NOT_COUNTED` · เส้นที่ 5: `PublishReadiness.count_actual=None` →
    `UNKNOWN_COUNT` ผ่าน `publish_blockers()`)

    ค่า `count_actual` ที่ผิดรูปแบบต่อแถว (ไม่ใช่จำนวนเต็ม ≥ 0) — ด่านรูปแบบเต็มเป็น
    หน้าที่ของเส้นที่ 3 (`manual_entry.py --commit` จะปฏิเสธไฟล์นั้นเอง) ฟังก์ชันนี้
    ปฏิบัติกับค่าที่ผิดรูปแบบเหมือน "ยังไม่นับ" (`None`) แทนที่จะ raise ทั้งไฟล์ —
    fail-closed แบบเดียวกับค่าว่าง ไม่ใช่ fail-open
    """
    raw_rows = read_manual_sheet(path)  # raise PrecheckError ถ้าไม่พบไฟล์
    if raw_rows and "count_actual" not in raw_rows[0]:
        raise PrecheckError(
            f"{path} ไม่มีคอลัมน์ count_actual ใน header\n"
            f"header ที่ make_manual_sheet.py สร้างวันนี้: "
            f"{','.join(MANUAL_SHEET_COLUMNS)}\n"
            "ต่างจาก 'ยังไม่มีใครนับ' (คอลัมน์มีอยู่แต่ค่าว่าง) — นี่คือใบงานรุ่นเก่า "
            "ที่สร้างก่อน ADR-0019 A-D2 ต้อง regenerate ด้วย make_manual_sheet.py ใหม่"
        )
    counts: dict[uuid.UUID, int | None] = {}
    for raw in raw_rows:
        try:
            poster_uuid = uuid.UUID(raw["poster_uuid"])
        except ValueError:
            continue  # รูปแบบผิด — เป็นหน้าที่ของเส้นที่ 3 ที่จะปฏิเสธไฟล์นั้นเอง
        try:
            counts[poster_uuid] = _parse_count_actual(raw.get("count_actual", ""))
        except ValueError:
            counts[poster_uuid] = None
    return counts


def parse_manual_rows(
    raw_rows: list[dict[str, str]],
    overwrite_fields: tuple[str, ...] = (),
) -> list[ManualRow]:
    """ตรวจรูปแบบทุกแถวแล้วคืน `ManualRow` — เจอผิดแม้แถวเดียว raise ทั้งไฟล์

    "ผิดรูปแบบ" ไม่รวมแถวที่ยังไม่ได้กรอก — ใบงานที่ทำไปได้ครึ่งเดียวเป็นสถานะปกติ
    ของงานนี้ ดู §"แถวไหนถูกข้าม" ใน docstring ของโมดูล
    """
    specs = field_specs()
    rows: list[ManualRow] = []
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
        row_failed = False
        # `title` อ่านเฉพาะเมื่อขอ overwrite — ไม่งั้นคอลัมน์นี้เป็นข้อมูลให้คนอ่านเท่านั้น
        parse_fields = ALLOWED_FIELDS + tuple(
            f for f in overwrite_fields if f not in ALLOWED_FIELDS
        )
        for name in parse_fields:
            text = raw.get(name, "")
            if not text:  # D6 — ว่าง = ข้าม ไม่ใช่เขียนทับด้วย NULL
                continue
            try:
                values[name] = specs[name].parse(text)
            except ValueError as exc:
                errors.append(f"{prefix}: {name} — {exc}")
                row_failed = True

        try:
            publish = _parse_publish(raw["publish"])
        except ValueError:
            errors.append(
                f"{prefix}: publish {raw['publish']!r} ไม่รู้จัก — ใช้ได้แค่ ว่าง "
                f"(ยังไม่ตัดสิน) · {'/'.join(sorted(_APPROVED_WORDS))} · "
                f"{'/'.join(sorted(_REJECTED_WORDS))}"
            )
            row_failed = True

        try:
            count_actual = _parse_count_actual(raw.get("count_actual", ""))
        except ValueError as exc:
            errors.append(f"{prefix}: count_actual — {exc}")
            row_failed = True
            count_actual = None

        if row_failed:
            continue
        rows.append(
            ManualRow(
                poster_uuid=poster_uuid,
                values=values,
                publish=publish,
                count_actual=count_actual,
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


def _publish_blocker_message(
    blocker: "PublishBlocker",
    state: "PosterState",
    *,
    count_actual: int | None = None,
    grade_after: Any = None,
) -> str:
    """แปลง blocker ที่ `publish_blockers()` ตัดสินแล้ว → ถ้อยคำสำหรับคนกรอกใบงาน

    🔴 **ที่นี่ไม่ตัดสินอะไรเลย** — รับผลมาแล้วเปลี่ยนเป็นภาษาคน · การเช็ค
    `state.image_count` ข้างล่างเป็นการเลือก*ถ้อยคำ* ไม่ใช่การตัดสินว่าผ่านหรือไม่
    (ใบที่มีแต่รูปตำหนิกับใบที่ไม่มีรูปเลย ต้องได้คำแนะนำคนละแบบ)
    """
    if blocker is PublishBlocker.NO_CONDITION_GRADE:
        return (
            "publish=Y แต่ไม่มี condition_grade ทั้งใน DB และในใบงาน — "
            "จะชน CHECK ck_posters_published_requires_condition_grade "
            "(ADR-0013 D3) · กรอกเกรดในแถวเดียวกันนี้ หรือเอา publish ออกก่อน"
        )
    if blocker is PublishBlocker.NOT_VERIFIED:
        return (
            "publish=Y แต่ยังไม่มีใครตรวจใบนี้ (verified_at เป็น NULL) — หน้าร้านแสดง "
            "เฉพาะแถวที่ผ่านการตรวจแล้ว (ADR-0027 D1) · หยิบใบจริงขึ้นมาตรวจแล้วเซ็นรับ "
            "ด้วยเส้นที่ 5 (correction_entry.py) ก่อน แล้วค่อยกลับมา publish รอบนี้"
        )
    if blocker is PublishBlocker.UNKNOWN_IS_UNIQUE:
        return (
            "publish=Y แต่อ่านค่า is_unique ของใบนี้ไม่ได้ — ไม่ทราบ = ไม่ผ่าน "
            "(ADR-0027 D5) · คอลัมน์นี้เป็น NOT NULL ถ้าอ่านไม่ได้แปลว่าอ่าน DB ผิดที่"
        )
    if blocker is PublishBlocker.NOT_UNIQUE:
        return (
            "publish=Y แต่ is_unique = false — แถวนี้อ้างว่าแทนของหลายชิ้น ซึ่งหลัง "
            "ADR-0019 D6 ต้องเป็น true ทุกแถว · ของหลายชิ้นต้องแตกเป็นหลายแถวก่อน "
            "ด้วยเส้นที่ 6 (split_entry.py — INF-22)"
        )
    if blocker is PublishBlocker.UNKNOWN_COUNT:
        return (
            "publish=Y แต่ count_actual ว่าง — ยังไม่มีผลนับใบจริง ไม่ทราบ = ไม่ผ่าน "
            "(ADR-0027 D5) · ‹เปลี่ยนจากเดิม 2026-08-16: A-D2 ข้อ 2 เคยให้ค่าว่างผ่าน "
            "ได้ แต่หลัง ADR-0027 การ publish ต้องมีลายเซ็น และเซ็นไม่ได้ถ้ายังไม่นับ "
            "(D3) — ค่าว่างจึงกันอยู่แล้วโดยอ้อม ที่เปลี่ยนคือคนได้อ่านเหตุผลตรง ๆ›"
        )
    if blocker is PublishBlocker.COUNT_IS_ZERO:
        return (
            "publish=Y แต่ count_actual = 0 — การนับล่าสุดบอกว่าไม่มีของ "
            "(ADR-0019 D9 ข้อ 2) · ไม่มี flag ข้าม — นับใหม่ให้ตรงกับของจริง "
            "หรือถอด publish ออกก่อน"
        )
    if blocker is PublishBlocker.COUNT_MULTIPLE_ON_NON_MINT:
        return (
            f"publish=Y แต่ count_actual = {count_actual} บนเกรด "
            f"{grade_after.value if grade_after else grade_after!r} "
            "ซึ่งไม่ใช่ mint — เกรดต่ำกว่า mint ทุกระดับต้องเป็น 1 แถว "
            "1 ชิ้นเสมอ ไม่มีข้อยกเว้น (ADR-0019 D1) · ของหลายชิ้นต้อง "
            "แตกเป็นหลายแถวก่อนด้วยเส้นที่ 6 (split_entry.py — INF-22)"
        )
    if blocker is PublishBlocker.UNKNOWN_FRONT_IMAGE_COUNT:
        return (
            "publish=Y แต่นับรูป kind=FRONT ของใบนี้ไม่ได้ — ไม่ทราบ = ไม่ผ่าน "
            "(ADR-0027 D5)"
        )
    if state.image_count == 0:
        return (
            "publish=Y แต่ใบนี้ไม่มีรูปสักรูปใน poster_images — "
            "ขัด BR-06 (ต้องมีรูปถ่ายของจริง ≥1 รูปก่อนเปิดขาย) · "
            "CHECK constraint อ้างข้ามตารางไม่ได้ ด่านนี้จึงอยู่ที่สคริปต์"
        )
    return (
        f"publish=Y แต่ใบนี้มีรูป {state.image_count} รูปและ**ไม่มีรูป kind=FRONT "
        "สักรูป** — ขัด BR-06 (ADR-0026 D8: รูปตำหนิหรือรูปด้านหลังล้วน ๆ ไม่พอให้ "
        "คนตัดสินใจซื้อ) · หน้า Home ใช้รูป FRONT เท่านั้น ใบนี้จึงจะขึ้นร้านแบบ "
        "ไม่มีรูป · ถ่ายรูปหน้าใบแล้วนำเข้าด้วยเส้นที่ 8 ก่อน"
    )


@dataclass(frozen=True)
class PosterState:
    """สถานะปัจจุบันของใบหนึ่งใน DB — ทุกอย่างที่ `plan_writes()` ต้องรู้."""

    # ค่าปัจจุบันของ 5 ฟิลด์ใน ALLOWED_FIELDS (ค่าดิบจาก ORM · None = ยังว่าง)
    values: dict[str, Any]
    published: bool
    # จำนวนรูปทั้งหมด — ใช้ **เลือกถ้อยคำ** ของ blocker เท่านั้น ไม่ใช่ตัวตัดสิน
    # (ตัวตัดสินคือ poster_service.publish_blockers() — ADR-0026 D8 · INF-27 AC-12)
    image_count: int
    # จำนวนรูป kind=FRONT — ตัวที่ BR-06 สนใจจริงตั้งแต่ ADR-0026
    front_image_count: int = 0
    # ADR-0027 — สองค่านี้เส้นนี้ **ไม่เขียน** แต่ต้องอ่านเพื่อประกอบ `PublishReadiness`
    # (`verified_at` และ `is_unique` เขียนด้วยเส้นที่ 5 เท่านั้น — ADR-0027 D7)
    verified_at: datetime | None = None
    is_unique: bool | None = None


class PublishAction(str, Enum):
    NONE = "NONE"  # publish ว่างหรือ N — ไม่ทำอะไร (ไม่ใช่การถอดออกจากชั้น)
    APPLY = "APPLY"
    SKIP_ALREADY = "SKIP_ALREADY"  # เปิดขายไปแล้ว — D6 ไม่มีโหมดเขียนทับ
    SKIP_NOT_FOUND = "SKIP_NOT_FOUND"
    BLOCKED = "BLOCKED"  # ไม่ผ่านด่านของ D4 — ทั้งไฟล์ถูกปฏิเสธ


@dataclass(frozen=True)
class PlannedWrite:
    row: ManualRow
    found: bool
    # ฟิลด์ที่จะเขียนจริง (ปลายทางเป็น NULL อยู่)
    field_writes: dict[str, Any]
    # ฟิลด์ที่คนกรอกมาแต่ปลายทางมีค่าแล้ว → {ชื่อฟิลด์: ค่าปัจจุบันเป็นข้อความ}
    skipped_already_set: dict[str, str]
    # ฟิลด์ที่ทับค่าเดิม → {ชื่อฟิลด์: (ค่าเดิมเป็นข้อความ, ค่าใหม่เป็นข้อความ)}
    # ADR-0010 D8 บังคับให้ dry-run แสดงคู่นี้ทีละแถว และให้ audit เก็บค่าเดิมจริง
    overwrites: dict[str, tuple[str, str]]
    publish_action: PublishAction
    # เหตุผลที่แถวนี้ทำให้ทั้งไฟล์ถูกปฏิเสธ (ว่าง = ไม่มีปัญหา)
    blockers: tuple[str, ...]


def plan_writes(
    rows: list[ManualRow],
    current: dict[uuid.UUID, PosterState],
    overwrite_fields: tuple[str, ...] = (),
) -> list[PlannedWrite]:
    """แปลงแถวใบงาน + สถานะปัจจุบันของ DB เป็นแผนการเขียน

    `current` = {poster_id: PosterState} · ใบที่ไม่มีใน dict ถือว่าไม่มีในฐานข้อมูล
    → **ข้าม ไม่ใช่ INSERT** (D5)

    pure function — ไม่ query ไม่เขียน ไม่แตะเวลาปัจจุบัน เพื่อให้ test ครอบได้ครบ
    ทุกสาขาโดยไม่ต้องมี DB
    """
    # import ข้างในด้วยเหตุผลเดียวกับ `field_specs()` เป๊ะ — `app.core.size_format`
    # ดึง `app.models.enums` ซึ่งลาก `app/models/__init__.py` → `app.core.database`
    # ตามมา และตัวนั้นต้องการ env ครบตอน import · ส่วนบนของไฟล์นี้ต้อง import ได้
    # ก่อน `_load_env()` จะถูกเรียก
    from app.core.size_format import derive_size_format

    plans: list[PlannedWrite] = []
    for row in rows:
        state = current.get(row.poster_uuid)
        if state is None:
            plans.append(
                PlannedWrite(
                    row=row,
                    found=False,
                    field_writes={},
                    skipped_already_set={},
                    overwrites={},
                    publish_action=PublishAction.SKIP_NOT_FOUND,
                    blockers=(),
                )
            )
            continue

        field_writes: dict[str, Any] = {}
        skipped: dict[str, str] = {}
        overwrites: dict[str, tuple[str, str]] = {}
        for name, value in row.values.items():
            current_value = state.values.get(name)
            if current_value is None:
                # D6 — ช่องว่างเขียนได้เสมอ
                field_writes[name] = value
            elif name in overwrite_fields:
                # ADR-0010 D8 — ทับได้เฉพาะฟิลด์ที่ขอมาเจาะจง
                before = render_value(current_value)
                after = render_value(value)
                if before == after:
                    # ค่าเท่าเดิม = ไม่ใช่การแก้ · ห้ามนับเป็น write ไม่งั้นจะได้ audit
                    # ปลอมและสคริปต์จะเลิก idempotent
                    skipped[name] = before
                else:
                    field_writes[name] = value
                    overwrites[name] = (before, after)
            else:
                skipped[name] = render_value(current_value)

        blockers: list[str] = []

        # --- ADR-0009 D16: size_format เป็นค่า **derive** ไม่ใช่ค่าที่คนกรอก ---
        # อ่านขนาด "หลังรอบนี้" = ค่าที่จะเขียนในรอบนี้ ถ้าไม่มีก็ค่าที่อยู่ใน DB แล้ว
        # → ใบที่วัดกว้างไว้รอบก่อนแล้วมาเติมสูงรอบนี้ ก็ derive ได้ ไม่ต้องกรอกซ้ำสองช่อง
        measured = tuple(
            field_writes.get(n, state.values.get(n)) for n in ("width_in", "height_in")
        )
        derived = derive_size_format(*measured)
        current_format = state.values.get("size_format")
        if derived is not None and current_format is None:
            field_writes["size_format"] = derived
        elif derived is not None and current_format != derived:
            # 🔴 ปฏิเสธทั้งไฟล์ ไม่ใช่ข้ามเงียบ ๆ — ขนาดที่วัดได้ขัดกับค่าที่อยู่ใน DB
            # แปลว่าอย่างใดอย่างหนึ่งผิด และเราแยกไม่ออกว่าฝั่งไหน · การเขียนทับคือการ
            # เลือกข้างโดยไม่มีหลักฐาน (D6 ไม่มีโหมดเขียนทับอยู่แล้ว) ส่วนการข้ามเงียบ ๆ
            # คือการปล่อยให้ DB เก็บค่าที่การวัดของเราเองบอกว่าผิด
            blockers.append(
                f"size_format ใน DB เป็น {render_value(current_format)} แต่ขนาดที่วัดได้ "
                f"({render_value(measured[0])} × {render_value(measured[1])} นิ้ว) "
                f"map เป็น {derived.value} ตามตาราง ADR-0009 D16 — "
                "ตรวจว่าวัดผิดหรือค่าเดิมผิด แล้วแก้ที่ต้นเหตุ "
                "(สคริปต์นี้เขียนทับ size_format ไม่ได้ตามหลัก D6)"
            )

        if row.publish is not Publish.YES:
            publish_action = PublishAction.NONE
        elif state.published:
            publish_action = PublishAction.SKIP_ALREADY
        else:
            # 🔴 **ด่าน publish ทุกข้ออยู่ที่ `poster_service.publish_blockers()` ที่เดียว**
            # (ADR-0026 D8 · INF-27 AC-12 · ADR-0027 D5 · ใช้หนี้ INF-17/BL-81)
            # ที่นี่เหลือหน้าที่เดียว: **แปลงเหตุผลเป็นถ้อยคำที่ operator อ่านรู้เรื่อง**
            # · ห้ามเพิ่มเงื่อนไข publish ลงตรงนี้อีก — นั่นคือสำเนาที่ 4 ที่ AC-12 ห้าม
            # ‹2026-08-16 · INF-28› ด่านที่ 3 (ประตูจำนวน) ย้ายเข้าไปด้วยแล้ว — เดิม
            # ยังตัดสินเองอยู่ที่นี่ทั้งที่ AC-12 ห้าม
            #
            # เกรด "หลังรอบนี้" = ของเดิม หรือของที่จะเขียนในรอบนี้ — ใบที่กรอกเกรดกับ
            # publish=Y ในแถวเดียวกันต้องตัดสินด้วยค่าใหม่ ไม่ใช่ค่าที่ยังไม่ถูกเขียน
            grade_after = state.values.get("condition_grade") or field_writes.get(
                "condition_grade"
            )
            readiness = PublishReadiness(
                condition_grade=grade_after,
                verified_at=state.verified_at,
                is_unique=state.is_unique,
                count_actual=row.count_actual,
                front_image_count=state.front_image_count,
            )
            for blocker in publish_blockers(readiness):
                blockers.append(
                    _publish_blocker_message(
                        blocker,
                        state,
                        count_actual=row.count_actual,
                        grade_after=grade_after,
                    )
                )
            publish_action = PublishAction.BLOCKED if blockers else PublishAction.APPLY

        plans.append(
            PlannedWrite(
                row=row,
                found=True,
                field_writes=field_writes,
                skipped_already_set=skipped,
                overwrites=overwrites,
                publish_action=publish_action,
                blockers=tuple(blockers),
            )
        )
    return plans


def planned_field_counts(plans: list[PlannedWrite]) -> dict[str, int]:
    """จำนวนแถวที่จะถูกเขียนจริง แยกทีละฟิลด์ — ตัวเลขที่ใช้ assert หลัง commit."""
    counts = {name: 0 for name in (*ALLOWED_FIELDS, *DERIVED_FIELDS)}
    counts[PUBLISH_FIELD] = 0
    for plan in plans:
        for name in plan.field_writes:
            # 🔴 **นับเฉพาะการเติมช่องว่าง ไม่นับการทับ** — ตัวเลขชุดนี้ถูกเทียบกับ
            # `count(<column>)` ก่อน/หลัง ซึ่ง**ไม่ขยับเลยเมื่อทับค่าเดิม** (ค่าเก่าก็ไม่ NULL
            # ค่าใหม่ก็ไม่ NULL) · ถ้านับรวมการทับ assert จะฟ้อง 🔴 ทุกครั้งทั้งที่ถูกต้อง
            # การทับถูกตรวจด้วย `verify_overwrites()` ซึ่งอ่านค่าจริงกลับมาเทียบ
            if name in plan.overwrites:
                continue
            # `title` ไม่อยู่ใน ALLOWED_FIELDS — โผล่ได้เฉพาะโหมด overwrite
            counts[name] = counts.get(name, 0) + 1
        if plan.publish_action is PublishAction.APPLY:
            counts[PUBLISH_FIELD] += 1
    return counts


# --------------------------------------------------------------------------
# รายงาน
# --------------------------------------------------------------------------


def _report(plans: list[PlannedWrite], target_label: str, committed: bool) -> None:
    specs = field_specs()
    planned = planned_field_counts(plans)
    not_found = sum(1 for p in plans if not p.found)

    print()
    print("=" * 72)
    print(f"ปลายทาง : {target_label}")
    print(f"แถวในใบงาน : {len(plans)}  (ไม่มีใน DB {not_found} — ข้าม ไม่ INSERT)")
    print()
    # หัวตารางต้องบอกความจริงของ *การรันครั้งนี้* ไม่ใช่ของกฎเดิมเสมอไป —
    # ไม่งั้นจะพิมพ์ "ไม่มีโหมดเขียนทับ" ทับหน้าจอที่กำลังจะทับค่าเดิม 4 ค่า
    if any(p.overwrites for p in plans):
        print("แยกทีละฟิลด์ (นับเฉพาะ*การเติมช่องว่าง* — การทับอยู่ในหัวข้อถัดไป):")
    else:
        print("แยกทีละฟิลด์ (ADR-0015 D2 · ไม่มีโหมดเขียนทับตาม D6):")
    print(f"  {'ฟิลด์':<20} {'จะเขียน':>8} {'ข้าม—มีค่าแล้ว':>16}")
    for name in ALLOWED_FIELDS:
        already = sum(1 for p in plans if name in p.skipped_already_set)
        print(f"  {name:<20} {planned[name]:>8} {already:>16}")
    # 🔴 derived ต้องขึ้นรายงานด้วย — dry-run ที่ไม่บอกว่ากำลังจะเขียนอะไร คือ
    # dry-run ที่ใช้ตรวจไม่ได้ · `size_format` ไม่มีคอลัมน์ในใบงาน คนอ่านจึงไม่มีทาง
    # เดาเองได้เลยว่ามันจะถูกเขียน ถ้ารายงานไม่พูดถึง (ADR-0015 D9.1)
    for name in DERIVED_FIELDS:
        already = sum(1 for p in plans if p.found and name not in p.field_writes)
        print(
            f"  {name:<20} {planned[name]:>8} {already:>16}"
            "   ← derive จาก width_in × height_in (ADR-0009 D16) ไม่มีช่องให้กรอก"
        )

    by_publish = {action: 0 for action in PublishAction}
    for plan in plans:
        by_publish[plan.publish_action] += 1
    print()
    print("เปิดขาย (published_at — ADR-0013 D1 · แกนที่สองแยกจาก status):")
    print(f"  จะเปิดขาย                 : {by_publish[PublishAction.APPLY]}")
    print(f"  ข้าม — เปิดขายอยู่แล้ว      : {by_publish[PublishAction.SKIP_ALREADY]}")
    print(
        f"  ข้าม — publish=N หรือว่าง : {by_publish[PublishAction.NONE]}"
        "  (ไม่ใช่การถอดออกจากชั้น — ADR-0013 D6)"
    )
    # ‹2026-08-16 · INF-28› **ถอดคำเตือน "ยังไม่มีผลนับ" ออกแล้ว ไม่ใช่ลืม** —
    # เดิมมันนับแถวที่ `APPLY` แต่ `count_actual` ว่าง ซึ่งหลัง ADR-0027 **D5**
    # (ไม่ทราบ = ไม่ผ่าน) เป็นสภาพที่เกิดไม่ได้อีกแล้ว: ค่าว่างกลายเป็น blocker
    # ⇒ แถวนั้นเป็น `BLOCKED` ไม่มีวันเป็น `APPLY` · คำเตือนที่เงื่อนไขเป็นจริงไม่ได้
    # คือโค้ดตายที่ดูเหมือนด่าน ซึ่งอันตรายกว่าไม่มีเลย (INF-17 AC-2)
    # · สิ่งที่คนได้แทนคือ blocker พร้อมเหตุผลเต็มจาก `_publish_blocker_message()`

    if not any(planned.values()) and not any(p.overwrites for p in plans):
        print()
        print(
            "  ⚠️  ไม่มีอะไรให้เขียนเลย — ใบงานยังว่าง หรือค่าทุกช่องมีอยู่ใน DB แล้ว"
        )

    print()
    overwriting = [p for p in plans if p.overwrites]
    if overwriting:
        total = sum(len(p.overwrites) for p in overwriting)
        print(
            f"\n🔴 ทับค่าเดิม {total} ค่า ใน {len(overwriting)} ใบ "
            "(ADR-0010 D8 — ฟิลด์ที่ส่ง --allow-overwrite มาเท่านั้น):"
        )
        for plan in overwriting:
            for name, (before, after) in plan.overwrites.items():
                print(
                    f"  บรรทัด {plan.row.lineno:>4}  {name:<16} {before!r} → {after!r}"
                )
        print("  ↑ ค่าเดิมทุกบรรทัดจะถูกบันทึกลง poster_attribute_reviews.value_before")

    print("ไม่แตะ needs_review และ status เลยสักแถว (ADR-0010 D2 · poster-database §3)")
    print("ไม่แตะ note / title / image_url เลย — เป็นข้อมูลให้คนอ่านอย่างเดียว")
    if not committed:
        print()
        print("DRY-RUN — ไม่ได้เขียนอะไรลง database (ใส่ --commit เพื่อเขียนจริง)")
    print("=" * 72)

    # hint ของแต่ละฟิลด์อยู่ท้ายสุด — คนที่กรอกผิดจะได้เห็นค่าที่ใช้ได้โดยไม่ต้องเปิดโค้ด
    if not committed:
        print("\nค่าที่รับได้:")
        for name in ALLOWED_FIELDS:
            print(f"  {name:<20} {specs[name].hint}")


def _report_blockers(plans: list[PlannedWrite]) -> None:
    print()
    print("=" * 72)
    blocked = [p for p in plans if p.blockers]
    print(
        f"🔴 ปฏิเสธทั้งไฟล์ — {len(blocked)} แถวขอเปิดขายทั้งที่ยังไม่ผ่านด่านของ "
        "ADR-0015 D4"
    )
    print("   ไม่เขียนอะไรเลยแม้แต่แถวที่ถูกต้อง (ดู §fail-closed ใน docstring)")
    print()
    for plan in blocked:
        for reason in plan.blockers:
            print(f"  บรรทัด {plan.row.lineno} ({plan.row.poster_uuid}):\n    {reason}")
    print("=" * 72)


# --------------------------------------------------------------------------
# ตัวรัน
# --------------------------------------------------------------------------


async def _column_counts(session: Any) -> dict[str, int]:
    """`count(<column>)` ของทุกฟิลด์ที่สคริปต์นี้เขียนได้ — **ไม่ใช่ `count(*)`**

    `count(*)` นับแถวทั้งตารางซึ่งไม่เปลี่ยนเลยไม่ว่าเราจะเขียนอะไรลงไป (สคริปต์นี้
    UPDATE อย่างเดียว) → assert ด้วย `count(*)` จะเขียวตลอดกาลแม้ไม่มีค่าไหนเข้า DB จริง
    `count(<column>)` นับเฉพาะแถวที่คอลัมน์นั้นไม่เป็น NULL จึงเป็นตัวเดียวที่ขยับ
    """
    from sqlalchemy import func, select

    from app.models.poster import Poster

    columns = [*ALLOWED_FIELDS, *DERIVED_FIELDS, PUBLISH_FIELD]
    result = await session.execute(
        select(*[func.count(getattr(Poster, name)) for name in columns])
    )
    return dict(zip(columns, result.one(), strict=True))


async def _load_state(session: Any, poster_ids: list[uuid.UUID]) -> dict:
    from sqlalchemy import func, select

    from app.models.poster import Poster, PosterImage

    from app.models.enums import PosterImageKind

    result = await session.execute(
        select(
            Poster.id,
            *[getattr(Poster, name) for name in READ_FIELDS],
            Poster.published_at,
            func.count(PosterImage.id),
            # FILTER ของ PostgreSQL — นับเฉพาะรูปหน้าใบในการ query รอบเดียวกัน
            # ไม่ต้องยิงเพิ่ม · ADR-0026 D8: BR-06 สนใจ "มีรูปหน้าใบไหม" ไม่ใช่
            # "มีรูปอะไรก็ได้ไหม" เพราะรูปตำหนิล้วน ๆ ไม่พอให้คนตัดสินใจซื้อ
            func.count(PosterImage.id).filter(
                PosterImage.kind == PosterImageKind.FRONT
            ),
            # ADR-0027 — เส้นนี้ไม่เขียนสองค่านี้ อ่านเพื่อประกอบ `PublishReadiness`
            Poster.verified_at,
            Poster.is_unique,
        )
        .outerjoin(PosterImage, PosterImage.poster_id == Poster.id)
        .where(Poster.id.in_(poster_ids))
        .group_by(Poster.id)
    )
    state: dict[uuid.UUID, PosterState] = {}
    for row in result.all():
        poster_id, *rest = row
        values = dict(zip(READ_FIELDS, rest[: len(READ_FIELDS)], strict=True))
        (
            published_at,
            image_count,
            front_image_count,
            verified_at,
            is_unique,
        ) = rest[len(READ_FIELDS) :]
        state[poster_id] = PosterState(
            values=values,
            published=published_at is not None,
            image_count=image_count,
            front_image_count=front_image_count,
            verified_at=verified_at,
            is_unique=is_unique,
        )
    return state


def audit_value_before(plan: PlannedWrite, field: str) -> str | None:
    """ค่าที่ต้องลง `poster_attribute_reviews.value_before` ของฟิลด์หนึ่ง

    🔴 **แยกออกมาเป็นฟังก์ชัน pure เพราะตรรกะนี้อยู่ในลูปที่ต้องมี DB ถึงจะรันได้**
    ซึ่งแปลว่าไม่มีเทสไหนแตะมันเลย · พิสูจน์แล้วด้วย mutation เมื่อ 2026-08-07:
    เปลี่ยนตรงนี้ให้คืน `None` เสมอ แล้ว **เทสทั้ง 74 ตัวยังเขียว** ทั้งที่ ADR-0010 D8
    บังคับตรง ๆ ว่าโหมด overwrite ต้องเก็บค่าเดิมจริง

    - เติมช่องว่าง (D6) → `None` ถูกต้อง ไม่มีค่าเดิมให้เก็บ
    - ทับค่าเดิม (D8) → **ต้องเป็นค่าเดิมจริง ห้ามเป็น `None`** ไม่งั้น audit จะหน้าตา
      เหมือนการเติมช่องว่าง ซึ่งอ่านย้อนแล้วเข้าใจผิดถาวรและตามกลับไม่ได้
    """
    pair = plan.overwrites.get(field)
    return pair[0] if pair else None


def verify_overwrites(
    plans: list[PlannedWrite],
    after_state: dict[uuid.UUID, PosterState],
) -> list[str]:
    """ตรวจว่าการทับลงจริงทุกช่อง — pure เพื่อให้ test ครอบได้โดยไม่ต้องมี DB

    🔴 **ทำไมต้องมีตัวนี้แยกจาก `_report_counts()`** — การทับไม่ทำให้ `count(<column>)`
    ขยับเลยสักหน่วย (ค่าเก่าก็ไม่ NULL ค่าใหม่ก็ไม่ NULL) การ assert ด้วยจำนวนจึง
    **เขียวตลอดกาล**กับโหมดนี้ ซึ่งเป็นกับดักชนิดเดียวกับ `count(*)` ที่ docstring
    ของ `_column_counts()` เตือนไว้ แค่ลึกลงไปอีกชั้น · ตัวเดียวที่พิสูจน์ได้คือ
    **อ่านค่ากลับมาเทียบกับค่าที่ตั้งใจเขียน**
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


def assert_schema_ready(missing_columns: list[str], has_publish_check: bool) -> None:
    """ปลายทางต้องมี schema ครบก่อนเขียน — pure เพื่อให้ test ครอบได้โดยไม่ต้องมี DB

    ทั้งสองอาการเกิดจากรากเดียวกัน (**ปลายทางตามหลัง `develop`**) แต่โผล่คนละที่:
    รันในคอนเทนเนอร์ที่ image เก่า → model ไม่มีแอตทริบิวต์ (ได้ `AttributeError` ดิบ) ·
    รันบน host แต่ DB ปลายทางยังไม่ migrate → คอลัมน์/constraint หายไป

    🔴 CHECK ของ ADR-0013 D3 ต้องมีอยู่ **ที่ปลายทาง** ไม่ใช่แค่ในไฟล์ model —
    มันคือกฎเดียวที่กันการเปิดขายใบที่ไม่มีเกรดในระดับที่ข้ามไม่ได้ · ถ้าปลายทางไม่มี
    การเขียนผ่านสคริปต์นี้จะเหลือด่านแค่ชั้นสคริปต์ ซึ่งอ่อนกว่าที่ ADR-0013 ตั้งใจไว้มาก
    """
    if missing_columns:
        raise PrecheckError(
            "ปลายทางไม่มีคอลัมน์: " + ", ".join(missing_columns) + "\n"
            "แปลว่า **ปลายทางตามหลัง develop อยู่** — ถ้ารันในคอนเทนเนอร์คือ image เก่า "
            "(ต้อง build/pull ใหม่) ถ้ารันบน host คือ DB ยังไม่ `alembic upgrade head`\n"
            "🔴 กรณี SIT: ดู docs/BACKLOG.md BL-75 — ต้อง upgrade **และ** redeploy app "
            "คู่กัน ทำแค่อย่างเดียวจะได้สถานะครึ่ง ๆ ที่อันตรายกว่าเดิม"
        )
    if not has_publish_check:
        raise PrecheckError(
            f"ปลายทางไม่มี CHECK `{PUBLISH_CHECK_CONSTRAINT}` (ADR-0013 D3)\n"
            "กฎที่กันการเปิดขายใบที่ไม่มีเกรดอยู่ที่ระดับ DB — ถ้าปลายทางไม่มี "
            "การเขียนจากสคริปต์นี้จะเหลือด่านแค่ชั้นสคริปต์ซึ่งใครก็เลี่ยงได้ด้วย psql\n"
            "🔴 กรณี SIT: ดู docs/BACKLOG.md BL-75"
        )


async def _check_schema(session: Any) -> None:
    from sqlalchemy import text

    from app.models.poster import Poster

    missing = [n for n in (*ALLOWED_FIELDS, PUBLISH_FIELD) if not hasattr(Poster, n)]
    has_check = False
    if not missing:
        has_check = bool(
            await session.scalar(
                text("SELECT 1 FROM pg_constraint WHERE conname = :name"),
                {"name": PUBLISH_CHECK_CONSTRAINT},
            )
        )
    assert_schema_ready(missing, has_check)


async def run(args: argparse.Namespace, target_label: str) -> int:
    from app.core.database import async_session_maker
    from app.models.poster import Poster
    from app.models.poster_attribute_review import PosterAttributeReview

    overwrite_fields = tuple(dict.fromkeys(args.allow_overwrite))
    rows = parse_manual_rows(read_manual_sheet(args.file), overwrite_fields)
    if not rows:
        print("ใบงานไม่มีแถวข้อมูล — ไม่มีอะไรให้ทำ")
        return 0

    async with async_session_maker() as session:
        await _check_schema(session)
        current = await _load_state(session, [r.poster_uuid for r in rows])
        plans = plan_writes(rows, current, overwrite_fields)

        if any(p.blockers for p in plans):
            # fail-closed — รายงานก่อน ไม่ปล่อยให้ DB เป็นคนบอก (D4)
            _report(plans, target_label, committed=False)
            _report_blockers(plans)
            return 1

        _report(plans, target_label, committed=args.commit)
        if not args.commit:
            return 0

        before = await _column_counts(session)
        planned = planned_field_counts(plans)
        source = args.file.name
        written = 0

        for plan in plans:
            if not plan.field_writes and plan.publish_action is not PublishAction.APPLY:
                continue
            poster = await session.get(Poster, plan.row.poster_uuid)
            if poster is None:  # pragma: no cover — plan บอกว่ามีแล้ว
                continue

            changes = dict(plan.field_writes)
            if plan.publish_action is PublishAction.APPLY:
                # `published_at` = เวลาที่ **คนตัดสินใจเปิดขาย** ไม่ใช่เวลาที่สคริปต์รัน
                # (หลักเดียวกับ --reviewed-at ของ ADR-0010 D5 ที่ไม่มี default เป็น now)
                changes[PUBLISH_FIELD] = args.reviewed_at

            for name, value in changes.items():
                setattr(poster, name, value)
                # ADR-0010 D8 — โหมด overwrite ต้องเก็บค่าเดิมจริง ห้ามเป็น NULL
                # ไม่งั้น audit จะหน้าตาเหมือนการเติมช่องว่างทั้งที่เป็นการทับ
                # ซึ่งอ่านย้อนแล้วเข้าใจผิดถาวร · D6 (เติมช่องว่าง) ยังเป็น NULL เหมือนเดิม
                session.add(
                    PosterAttributeReview(
                        poster_id=plan.row.poster_uuid,
                        field=name,
                        value_before=audit_value_before(plan, name),
                        value_after=render_value(value),
                        reviewed_by=args.reviewed_by,
                        reviewed_at=args.reviewed_at,
                        source=source,
                    )
                )
                written += 1

        await session.commit()
        after = await _column_counts(session)
        # ADR-0010 D8 — การทับไม่ทำให้ count() ขยับ ต้องอ่านค่ากลับมาเทียบเอง
        overwrite_problems = verify_overwrites(
            plans, await _load_state(session, [p.row.poster_uuid for p in plans])
        )

    print(
        f"\nเขียนจริงแล้ว {written} ค่า · บันทึก audit {written} แถวลง poster_attribute_reviews"
    )
    if overwrite_problems:
        print("\n🔴 การทับค่าเดิมไม่ลงตามแผน — commit ไปแล้ว ต้องตรวจด้วยมือ:")
        for problem in overwrite_problems:
            print(f"  {problem}")
        return 1
    return _report_counts(before, after, planned)


def _report_counts(
    before: dict[str, int], after: dict[str, int], planned: dict[str, int]
) -> int:
    """เทียบ `count(<column>)` ก่อน/หลัง กับจำนวนที่วางแผนไว้ — ไม่ตรง = ถือว่าพัง

    ตรวจที่ระดับ *ตารางทั้งตาราง* ไม่ใช่เฉพาะใบในใบงาน เพื่อให้จับได้ด้วยว่ามีอะไร
    ไปแตะแถวอื่นโดยไม่ตั้งใจ
    """
    print()
    print(
        "assert count(<column>) — ไม่ใช่ count(*) ซึ่งจะเขียวตลอดกาลกับสคริปต์ UPDATE:"
    )
    print(f"  {'คอลัมน์':<20} {'ก่อน':>7} {'หลัง':>7} {'ต่าง':>7} {'ที่วางแผน':>10}")
    ok = True
    for name in [*ALLOWED_FIELDS, PUBLISH_FIELD]:
        delta = after[name] - before[name]
        mark = "" if delta == planned[name] else "  🔴"
        ok = ok and delta == planned[name]
        print(
            f"  {name:<20} {before[name]:>7} {after[name]:>7} "
            f"{delta:>+7} {planned[name]:>10}{mark}"
        )
    if not ok:
        print(
            "\n🔴 จำนวนที่เพิ่มจริงไม่ตรงกับแผน — ข้อมูลเข้าไปแล้ว (commit ไปแล้ว) "
            "ต้องตรวจ poster_attribute_reviews กับ posters ด้วยมือก่อนรันอะไรต่อ"
        )
        return 1
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
        "--allow-overwrite",
        action="append",
        default=[],
        choices=OVERWRITE_ELIGIBLE,
        metavar="FIELD",
        help=(
            "อนุญาตให้ทับค่าเดิมของฟิลด์ที่ระบุ (ADR-0010 D8) — ระบุซ้ำได้หลายครั้ง · "
            f"รับได้เฉพาะ {' · '.join(OVERWRITE_ELIGIBLE)} · "
            "ฟิลด์ที่ไม่ได้ระบุยังเขียนเฉพาะช่องว่างเหมือนเดิม · "
            "ไม่มีรูปแบบที่เปิดทุกฟิลด์พร้อมกันโดยเจตนา"
        ),
    )
    parser.add_argument(
        "--file",
        type=Path,
        default=DEFAULT_MANUAL_CSV,
        help=f"ใบงาน (default: {DEFAULT_MANUAL_CSV.name})",
    )
    parser.add_argument(
        "--target",
        choices=TARGETS,
        default="dev",
        help="ปลายทาง — ADR-0015 D8 อนุญาตแค่ dev กับ sit (production ไม่มีให้เลือก"
        "โดยตั้งใจ) · sit ต้องรันข้างในคอนเทนเนอร์ sit และ DATABASE_URL ต้องตรงกับ "
        f"{SIT_ENV_FILE} เป๊ะ · 🔴 SIT ยังไม่พร้อมรับจริง ดู BACKLOG BL-75",
    )
    parser.add_argument(
        "--reviewed-by",
        help="ชื่อคนที่กรอกใบงานรอบนี้ — บังคับเมื่อ --commit (ADR-0010 D1)",
    )
    parser.add_argument(
        "--reviewed-at",
        metavar="<เวลาที่คุณตัดสิน ISO-8601 พร้อม timezone>",
        help="บังคับเมื่อ --commit · ค่านี้ถูกใช้เป็น published_at ของแถวที่ publish=Y "
        "ด้วย · 🔴 ไม่มี default เป็นเวลาปัจจุบัน (ADR-0010 D5) และค่าที่อยู่ในอนาคต"
        "ถูกปฏิเสธ (เวลาที่คนตัดสินย้อนไปข้างหน้าไม่ได้)",
    )
    args = parser.parse_args()

    if args.commit:
        if not args.reviewed_by:
            parser.error("--commit ต้องระบุ --reviewed-by ด้วย (ADR-0010 D1)")
        if not args.reviewed_at:
            parser.error("--commit ต้องระบุ --reviewed-at ด้วย (ADR-0010 D1)")
        try:
            args.reviewed_at = _parse_reviewed_at(args.reviewed_at)
            # 🔴 จุดเดียวในโมดูลที่อ่านนาฬิกา — และอ่านเพื่อ **ปฏิเสธ** เท่านั้น
            # ไม่เคยถูกใช้เป็นค่าให้ `args.reviewed_at` (ADR-0010 D5 · มีเทส AST ล็อก)
            assert_not_in_the_future(args.reviewed_at, now=datetime.now(timezone.utc))
        except PrecheckError as exc:
            parser.error(str(exc))

    # ADR-0015 D8 — dev เป็น default · sit ต้องสั่งเอง · production ไม่มีให้เลือก
    # ‹INF-39 · code-critic M-1› `_load_env()` โยน `PrecheckError` ได้แล้วตั้งแต่ A2-D1
    # (ไฟล์อ้างตัวแปรที่ขยายไม่ได้) — ถ้าไม่ครอบ กรณีที่ **A2-D4 สั่งให้แยกเป็นข้อ (2)**
    # จะถึงผู้รันเป็น traceback ดิบแทนข้อความ precheck
    try:
        _load_env(args.target)
    except PrecheckError as exc:
        print(f"precheck ไม่ผ่าน: {exc}", file=sys.stderr)
        return 1
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
            "ข้างในคอนเทนเนอร์ sit และ DATABASE_URL ต้องตรงกับ .env.sit เป๊ะ)",
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
        # ต่อ DB ไม่ติด — เคสที่เจอบ่อยที่สุดคือสั่ง `--target sit` จาก host ทั้งที่
        # `.env.sit` ชี้ hostname `db` ซึ่ง resolve ได้เฉพาะใน docker network
        # (precheck ผ่านถูกต้องแล้ว เพราะ url ตรงกับไฟล์จริง — ที่พังคือ network)
        # ปล่อยเป็น traceback ดิบจะอ่านไม่ออกว่าต้องทำอะไรต่อ
        hint = ""
        if args.target == "sit":
            hint = (
                "\n--target sit ต้องรัน **ข้างในคอนเทนเนอร์ sit** ไม่ใช่จากเครื่องนี้:\n"
                "  docker compose -f docker-compose.yml -f docker-compose.sit.yml exec app \\\n"
                "    python scripts/seed/manual_entry.py --target sit\n"
                "🔴 แต่ SIT ยังรับไม่ได้จริงวันนี้ — ดู docs/BACKLOG.md BL-75"
            )
        print(
            f"ต่อ database ไม่ได้ (target={args.target}): {exc}{hint}", file=sys.stderr
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
