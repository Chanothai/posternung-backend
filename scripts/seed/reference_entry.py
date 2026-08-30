"""นำ **ลิงก์แหล่งอ้างอิงที่คนเปิดเว็บหาเอง** เข้า `posters` — ADR-0014 Amendment 3 (INF-13)

    ./venv/bin/python scripts/seed/make_reference_sheet.py              # 1. สร้างใบงาน
    # 2. คนเปิดเว็บอ้างอิง แล้วกรอก reference_url หรือ reference_note เอง (ช่องเดียวต่อแถว)
    ./venv/bin/python scripts/seed/reference_entry.py                    # 3. dry-run (default)
    ./venv/bin/python scripts/seed/reference_entry.py --commit \
        --reviewed-by <ชื่อคุณ> \
        --reviewed-at <เวลาที่คุณตัดสิน ISO-8601 พร้อม timezone>

🔴 **ค่าตัวอย่างข้างบนเป็น placeholder ที่ก๊อปทั้งบรรทัดแล้วรันไม่ผ่านโดยตั้งใจ** —
ตัวอย่างที่เคยเขียนเป็นเวลาจริงถูกก๊อปมาทั้งบรรทัดเมื่อ 2026-08-08 แล้ว `reviewed_at`
ของ 232 แถวลงเป็น **เวลาในอนาคต 3.5 ชั่วโมง** · `--reviewed-at` ที่อยู่ในอนาคตถูก
`assert_not_in_the_future()` ปฏิเสธตั้งแต่ `main()` แล้ว

## นี่คือ "เส้นทางที่ 4" ไม่ใช่ส่วนขยายของ `manual_entry.py`

ระบบมีเส้นทางเขียน `posters` สี่เส้น **คนละแหล่ง คนละกฎ** (ADR-0015 D1 · Amendment
2026-08-08) — เส้นที่ 3 คือ *คนจับใบจริงแล้วพิมพ์* ส่วนเส้นนี้คือ *คนเปิดเว็บอ้างอิง
แล้วแปะลิงก์* · คนละแหล่งของค่า แม้จะเป็นคนคนเดียวกัน · เหตุผลเต็ม: **ADR-0014 D28**

🔴 **AI ห้ามเป็น writer ของฟิลด์ชุดนี้ตลอดกาล** — ADR-0014 **D7** เป็นเจ้าของข้อห้าม
(มีเทสระดับ AST ล็อกไว้ตาม `screens.yaml` INF-13 AC-7)

## สิ่งที่สคริปต์นี้เขียน — 3 คอลัมน์ ไม่มีคอลัมน์อื่นเลย

| คอลัมน์ | มาจากไหน |
|---|---|
| `reference_url` | คนกรอก — URL ล้วน ๆ (AC-5) |
| `reference_note` | คนกรอก — เหตุผลตอนหาไม่เจอ อย่างเดียว (D22) |
| `verification_status` | **สคริปต์ derive จากสองช่องบน** (D22) ไม่มีช่องให้กรอก |

`previous_note` ในใบงานเป็น *ช่องช่วยจำของคน* — สคริปต์นี้ **ไม่อ่านเลย** (D28 ‹ทางที่
ปฏิเสธ›: การให้เครื่องแยกว่าท่อนไหนคือ URL ท่อนไหนคือเหตุผล = เครื่องตัดสินความหมายแทนคน)

## แถวไหนถูกข้าม แถวไหนทำทั้งไฟล์พัง

**ข้ามเฉย ๆ (ปกติ ไม่ใช่ error):** ทั้งสองช่องว่าง (ยังไม่ได้เปิดหา) · ใบไม่มีใน DB ·
ใบที่สามคอลัมน์นั้นไม่ได้เป็น `NULL` ครบทั้งสาม (D29 — ตรวจเป็นก้อน ไม่ใช่ทีละฟิลด์
· ไม่มีโหมดเขียนทับ ตกทอดจาก ADR-0010 D6 · ADR-0015 D6)

**ทั้งไฟล์ถูกปฏิเสธ ไม่เขียนอะไรเลย (fail-closed):** `poster_uuid` ไม่ใช่ UUID ·
`poster_uuid` ซ้ำ · **กรอกทั้ง `reference_url` และ `reference_note` ในแถวเดียวกัน**
(AC-4 · D29 — คนเข้าใจความหมายของ `reference_note` ไม่ตรงกัน ไม่ใช่กรอกไม่เสร็จ) ·
`reference_url` ผิดรูปแบบตาม `validate_reference_url()`

## 🔴 URL ซ้ำข้ามแถว = **warning เท่านั้น ห้ามทำเป็นด่านปฏิเสธ**

ข้อเท็จจริงที่เจ้าของโปรเจกต์ยืนยันจากใบจริงเมื่อ 2026-08-08: โปสเตอร์ที่**ผลิตในไทย**
ใช้อาร์ตเวิร์กชุดเดียวกับฉบับต่างประเทศ ใบ `THEATRICAL` กับ `ADVANCE` ของหนังเรื่อง
เดียวกันจึงชี้ `reference_url` เดียวกัน **โดยถูกต้อง** — วันนี้มีอยู่จริงแล้ว 2 คู่
ในข้อมูลที่คนกรอกไว้ ด่านปฏิเสธจึงจะปฏิเสธไฟล์ที่ถูกตั้งแต่รันครั้งแรก

มติและเหตุผลเต็มอยู่ที่ **ADR-0014 D30** (และ `screens.yaml` INF-13 `standing_rules`)
— 🔴 **ห้ามใครใส่ด่านนี้กลับมาโดยอ้างว่า "ข้อมูลดูผิด"** เพราะเป็นข้อเท็จจริงเรื่อง
สินค้าจริงที่อ่านจากข้อมูลอย่างเดียวไม่มีทางรู้ · มีเทสล็อกไว้ว่าต้องเดินต่อ ไม่ใช่ล้ม

## สิ่งที่สคริปต์นี้ **ไม่** ทำ

- ❌ **ไม่ยิง HTTP ไปเช็คว่าลิงก์มีชีวิต** — ไม่ต่อเน็ตเลยสักบรรทัด · ADR-0014 D24
  ระบุว่าเราเก็บ URL สาธารณะแล้วให้คนกดไปดูเอง ไม่ดึง ไม่ scrape ไม่แคช
- ❌ **ไม่ normalize URL** — ไม่เติม scheme ไม่ตัด trailing slash ไม่แปลงตัวพิมพ์
  (AC-5 · เก็บสิ่งที่คนแปะมาเป๊ะ ๆ เพื่อให้ตามกลับไปที่หน้าต้นทางได้ตรงตัว)
- ❌ **ไม่แตะคอลัมน์อื่นของ `posters` เลยสักตัว** — `WRITABLE_FIELDS` เป็น fail-closed
  ในลูปที่เขียน และมีเทสล็อกไว้ **สองชั้น** เพราะชั้นเดียวไม่พอ:
  1. *ระดับซอร์ส* — สแกนชื่อทุกตัวที่โมดูลนี้เอ่ยถึง (string literal **และ**
     `<obj>.attr`) แล้วตัดกับรายชื่อคอลัมน์จริงของ `Poster`
     · 🔴 **ชั้นนี้จับชื่อที่ประกอบขึ้นตอนรันไม่ได้** (`setattr(poster, "a"+"b", …)`)
  2. *ระดับ runtime* — เรียก `run()` จริงกับ session ปลอมที่บันทึกทุก attribute
     ที่ถูก `setattr` ลงบน object แล้วเทียบเซตกับ `WRITABLE_FIELDS` แบบ closed-world
     · ชั้นนี้จับชื่อ dynamic และการเขียน**นอกลูป**ได้ ซึ่งชั้นที่ 1 จับไม่ได้
  🔴 **สิ่งที่ยังจับไม่ได้ทั้งสองชั้น: การเขียนที่ไม่ผ่าน `run()`** — เช่น raw SQL
  หรือ `session.execute(update(...))` ที่ใครเพิ่มเข้ามาใหม่ · ยังต้องพึ่งการรีวิว
"""

from __future__ import annotations

import argparse
import os
import sys
import uuid
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

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
from scripts.seed.manual_entry import (  # noqa: E402
    DEFAULT_MANUAL_CSV,
    SIT_ENV_FILE,
    TARGETS,
    assert_target,
    render_value,
)

DEFAULT_REFERENCE_CSV = SEED_DIR / "reference-entry.csv"

# คอลัมน์ของใบงาน — `make_reference_sheet.py` import ไปใช้ ไม่ประกาศซ้ำสองที่
# 🔴 **ห้ามมีคอลัมน์ `verification_status`** (D22/AC-3 — จะเป็นแหล่งความจริงที่สอง) ·
# **ห้ามมี checklist** (D23) · **ห้ามมี `approved`/`corrected_*`** (D28) — เส้นนี้ไม่มี
# ข้อเสนอของเครื่องให้คนเซ็นรับตั้งแต่แรก
REFERENCE_SHEET_COLUMNS = (
    "poster_uuid",
    "title",
    "image_url",
    "previous_note",
    "reference_url",
    "reference_note",
)
# คอลัมน์ที่สคริปต์นี้ *ใช้จริง* — 🔴 `previous_note` **ไม่อยู่ในนี้โดยตั้งใจ** (D28)
# `title`/`image_url` เป็นข้อมูลให้คนอ่านตอนกรอก ขาดได้ไม่เป็นไร
REQUIRED_COLUMNS = ("poster_uuid", "reference_url", "reference_note")

# ช่องที่ **คน** กรอก — หนึ่งแถวกรอกได้ช่องเดียว (D22 · AC-4)
HUMAN_FIELDS = ("reference_url", "reference_note")
# ค่าที่ **สคริปต์คำนวณเอง** — ไม่มีช่องในใบงาน (D22) · precedent ตรงตัวคือ
# `DERIVED_FIELDS` ของ `manual_entry.py` (`size_format` ตาม ADR-0015 D9.1)
DERIVED_FIELDS = ("verification_status",)
# 🔴 คอลัมน์ทั้งหมดที่สคริปต์นี้เขียนได้ — fail-closed ใน `run()`
# ห้ามเพิ่มโดยไม่แก้ ADR-0014 · มีเทส closed-world ระดับซอร์สล็อกไว้
WRITABLE_FIELDS = HUMAN_FIELDS + DERIVED_FIELDS
# ADR-0014 **D29** — เขียนก็ต่อเมื่อ *ทั้งสาม* คอลัมน์เป็น NULL หมด ไม่งั้นข้ามทั้งใบ
# ตั้งใจให้เป็นทูเพิลเดียวกับ `WRITABLE_FIELDS`: ทุกช่องที่เราเขียนได้ต้องว่างพร้อมกัน
# ถ้าตรวจทีละฟิลด์ ใบที่มี url อยู่แล้วจะรับ note เข้าไปแล้วได้ค่าสามตัวที่ขัดกันเอง
NULL_ONLY_FIELDS = WRITABLE_FIELDS


# --------------------------------------------------------------------------
# ตรวจรูปแบบ (pure — ไม่แตะ DB ไม่แตะเน็ต)
# --------------------------------------------------------------------------

ALLOWED_URL_SCHEMES = ("http", "https")
# ตัวคั่นที่เคยถูกใช้ยัดข้อมูลหลายค่าลงช่องเดียว — AC-5 ห้ามตรง ๆ
STRUCTURED_MARKERS = ("|",)
STRUCTURED_PREFIXES = ("{", "[")


def validate_reference_url(value: str) -> str:
    """ตรวจว่าเป็น **URL ล้วน ๆ** แล้วคืนค่าเดิมเป๊ะ ๆ — AC-5 (pure · ไม่ต่อเน็ต)

    🔴 **ห้าม normalize** — ไม่เติม scheme ไม่ตัด trailing slash ไม่แปลงตัวพิมพ์
    ไม่ strip อะไรนอกจากช่องว่างหัวท้ายของ cell ซึ่ง `read_sheet()` ทำไปแล้ว ·
    ค่าที่เก็บต้องเป็นสิ่งที่คนแปะมา เพื่อให้กดกลับไปหน้าต้นทางได้ตรงตัว

    🔴 **ห้ามบังคับ `https`** — ลิงก์ที่คนกรอกไว้จริงทั้ง 108 อันเป็น `http://`
    ทั้งหมด การบังคับจะปฏิเสธข้อมูลที่ถูกต้องทั้งชุด

    สิ่งที่ปฏิเสธคือ *สัญญาณว่าช่องนี้ถูกใช้เก็บมากกว่าหนึ่งค่า* (AC-5: หนึ่งค่า
    หนึ่งคอลัมน์) — ช่องว่างข้างใน · `|` · ขึ้นต้นด้วย `{`/`[` (JSON) · `://` เกินหนึ่งครั้ง
    """
    if any(ch.isspace() for ch in value):
        raise ValueError(
            "มีช่องว่างอยู่ข้างใน — ช่องนี้เก็บ URL ล้วน ๆ ค่าเดียว "
            "คำอธิบายห้ามปนมาด้วย (AC-5)"
        )
    hit = next((m for m in STRUCTURED_MARKERS if m in value), None)
    if hit:
        raise ValueError(
            f"มี {hit!r} อยู่ข้างใน — ดูเหมือนยัดหลายค่าลงช่องเดียว (AC-5 ห้าม)"
        )
    if value.startswith(STRUCTURED_PREFIXES):
        raise ValueError("ขึ้นต้นด้วย { หรือ [ — ห้ามเก็บ JSON ลงคอลัมน์ข้อความ (AC-5)")
    if value.count("://") > 1:
        raise ValueError("มี '://' มากกว่าหนึ่งครั้ง — ดูเหมือนหลาย URL ต่อกัน (AC-5)")

    parts = urlsplit(value)
    if parts.scheme not in ALLOWED_URL_SCHEMES:
        raise ValueError(
            f"scheme {parts.scheme!r} ใช้ไม่ได้ — ต้องเป็น "
            f"{' หรือ '.join(ALLOWED_URL_SCHEMES)} และต้องพิมพ์มาเต็ม "
            "(สคริปต์ไม่เติมให้เอง)"
        )
    if not parts.netloc:
        raise ValueError("ไม่มีชื่อโฮสต์หลัง scheme")
    return value


@dataclass(frozen=True)
class ReferenceRow:
    """หนึ่งแถวของใบงานที่ผ่านการตรวจรูปแบบแล้ว

    🔴 **ไม่มีฟิลด์ `previous_note`** — ชั้นนี้คือทุกอย่างที่สคริปต์รู้เกี่ยวกับแถวหนึ่ง
    การไม่มีมันที่นี่แปลว่าไม่มีชั้นไหนข้างล่างอ่านมันได้เลย (D28)
    """

    poster_uuid: uuid.UUID
    reference_url: str
    reference_note: str
    lineno: int


def assert_own_sheet(path: Path) -> None:
    """ปฏิเสธใบงานของเส้นอื่น — pure เพื่อให้ test ครอบได้โดยไม่ต้องมีไฟล์จริง

    🔴 `poster_attribute_reviews.source` เก็บ **ชื่อไฟล์ใบงาน** ซึ่งเป็นสิ่งเดียวที่
    แยกได้ว่าค่าไหนมาจากรอบไหน (ADR-0014 D28 — เหตุผลทั้งหมดที่เส้นที่ 4 แยกไฟล์
    ออกจากเส้นที่ 3 คือข้อนี้) · ถ้า operator เผลอส่ง `--file …/manual-entry.csv`
    มา แถว audit จะได้ `source` ชนกับเส้นที่ 3 แล้ว **ร่องรอยที่ D28 สร้างขึ้นมา
    หายไปเงียบ ๆ โดยที่ทุกอย่างดูเหมือนสำเร็จ**
    """
    if path.name == DEFAULT_MANUAL_CSV.name:
        raise PrecheckError(
            f"--file ชี้ไปที่ {path.name} ซึ่งเป็นใบงานของ **เส้นที่ 3** "
            "(manual_entry.py)\n"
            "สคริปต์นี้ต้องใช้ใบงานของตัวเอง เพราะ poster_attribute_reviews.source "
            "เก็บชื่อไฟล์ไว้เป็นตัวแยกว่าค่าไหนมาจากรอบไหน (ADR-0014 D28)\n"
            "สร้างด้วย `./venv/bin/python scripts/seed/make_reference_sheet.py`"
        )


def read_sheet(path: Path) -> list[dict[str, str]]:
    if not path.is_file():
        raise PrecheckError(
            f"ไม่พบใบงาน {path}\n"
            "สร้างด้วย `./venv/bin/python scripts/seed/make_reference_sheet.py` ก่อน "
            "แล้วให้คนเปิดเว็บอ้างอิงหาและกรอกเอง"
        )
    return read_sheet_rows(
        path,
        required_columns=REQUIRED_COLUMNS,
        sheet_columns=REFERENCE_SHEET_COLUMNS,
        maker_script="make_reference_sheet.py",
        free_text_columns=("reference_note",),
    )


def parse_rows(raw_rows: list[dict[str, str]]) -> list[ReferenceRow]:
    """ตรวจรูปแบบทุกแถวแล้วคืน `ReferenceRow` — เจอผิดแม้แถวเดียว raise ทั้งไฟล์

    "ผิดรูปแบบ" ไม่รวมแถวที่ยังไม่ได้กรอก — ใบงานที่ทำไปได้ครึ่งเดียวเป็นสถานะปกติ
    ของงานนี้ ดู §"แถวไหนถูกข้าม" ใน docstring ของโมดูล
    """
    rows: list[ReferenceRow] = []
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

        url = raw.get("reference_url", "")
        note = raw.get("reference_note", "")

        if url and note:
            # AC-4 · D29 — ปฏิเสธทั้งไฟล์ ไม่ใช่ข้ามเฉพาะแถว
            errors.append(
                f"{prefix}: กรอกทั้ง reference_url และ reference_note — "
                "reference_note แปลว่า *หาไม่เจอ* อย่างเดียว (ADR-0014 D22) "
                "การมีทั้งคู่คือข้อมูลขัดกันเอง ไม่ใช่ข้อมูลเพิ่ม · "
                "เจอแล้วให้ใส่แค่ลิงก์ ไม่ต้องอธิบาย"
            )
            continue

        if url:
            try:
                url = validate_reference_url(url)
            except ValueError as exc:
                errors.append(f"{prefix}: reference_url — {exc}")
                continue

        rows.append(
            ReferenceRow(
                poster_uuid=poster_uuid,
                reference_url=url,
                reference_note=note,
                lineno=lineno,
            )
        )

    if errors:
        raise PrecheckError(
            f"ใบงานไม่ผ่านการตรวจรูปแบบ {len(errors)} จุด — ไม่เขียนอะไรเลยทั้งไฟล์:\n  "
            + "\n  ".join(errors)
        )
    return rows


def derive_status(reference_url: str, reference_note: str):
    """สองช่องที่คนกรอก → `verification_status` — ADR-0014 **D22** (pure)

    🔴 **ไม่มีใครกรอกค่านี้ด้วยมือ** (AC-3) · `NULL` = `NOT_CHECKED` ซึ่ง **ไม่ใช่
    สมาชิกของ enum** (D21) — คืน `None` ไม่ใช่ค่าใน enum

    🔴 **precondition: เรียกได้เฉพาะกับแถวที่ผ่าน `parse_rows()` มาแล้ว** — ฟังก์ชันนี้
    เป็น *ตารางแปลง* ของ D22 ตรงตัว จึงคืน `REFERENCE_FOUND` เมื่อมี url ไม่ว่า note
    จะมีค่าหรือไม่ · กฎ **AC-4/D29** (กรอกทั้งคู่ = ปฏิเสธทั้งไฟล์) มีเจ้าของที่
    `parse_rows()` **แห่งเดียว** และ `run()` เรียกมันก่อน `plan_writes()` เสมอ
    (มีเทสล็อกลำดับนั้นไว้) — จงใจไม่ตรวจซ้ำที่นี่ เพื่อไม่ให้มีสองที่ที่พูดกฎเดียวกัน
    แล้ว drift กัน

    import ข้างในฟังก์ชันด้วยเหตุผลเดียวกับ `field_specs()` ของ `manual_entry.py`:
    `app/models/__init__.py` ลาก `app.core.database` ตามมา ซึ่งต้องการ env ครบตอน import
    """
    from app.models.enums import VerificationStatus

    if reference_url:
        return VerificationStatus.REFERENCE_FOUND
    if reference_note:
        return VerificationStatus.NO_REFERENCE_FOUND
    return None


def duplicate_reference_urls(
    rows: list[ReferenceRow],
) -> list[tuple[str, tuple[int, ...]]]:
    """URL ที่ถูกใช้มากกว่าหนึ่งแถว → [(url, บรรทัดทั้งหมด)] เรียงตามบรรทัดแรก

    🔴 **ผลของฟังก์ชันนี้เป็น warning เท่านั้น ไม่ใช่ error** — ดู §URL ซ้ำ ของ
    docstring โมดูล และ **ADR-0014 D30**
    """
    by_url: dict[str, list[int]] = defaultdict(list)
    for row in rows:
        if row.reference_url:
            by_url[row.reference_url].append(row.lineno)
    dupes = [(url, tuple(lines)) for url, lines in by_url.items() if len(lines) > 1]
    dupes.sort(key=lambda pair: pair[1][0])
    return dupes


# --------------------------------------------------------------------------
# วางแผนการเขียน (pure — รับสถานะปัจจุบันเข้ามา ไม่ query เอง)
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class PosterState:
    """สถานะปัจจุบันของใบหนึ่งใน DB — ทุกอย่างที่ `plan_writes()` ต้องรู้."""

    # ค่าปัจจุบันของ 3 คอลัมน์ใน `NULL_ONLY_FIELDS` (ค่าดิบจาก ORM · None = ยังว่าง)
    values: dict[str, Any]


class RowAction(str, Enum):
    WRITE = "WRITE"
    SKIP_BLANK = "SKIP_BLANK"  # ยังไม่ได้เปิดหา — คงเป็น NULL (D22)
    SKIP_NOT_FOUND = "SKIP_NOT_FOUND"  # ไม่มีใบนี้ใน DB — UPDATE เท่านั้น
    SKIP_ALREADY_SET = "SKIP_ALREADY_SET"  # ไม่ NULL ครบทั้งสาม (D29)


@dataclass(frozen=True)
class PlannedWrite:
    row: ReferenceRow
    action: RowAction
    # ฟิลด์ที่จะเขียนจริง — ว่างเสมอเมื่อ action ไม่ใช่ WRITE
    field_writes: dict[str, Any]
    # คอลัมน์ที่ปลายทางมีค่าอยู่แล้ว → {ชื่อคอลัมน์: ค่าปัจจุบันเป็นข้อความ}
    already_set: dict[str, str]


def plan_writes(
    rows: list[ReferenceRow], current: dict[uuid.UUID, PosterState]
) -> list[PlannedWrite]:
    """แปลงแถวใบงาน + สถานะปัจจุบันของ DB เป็นแผนการเขียน

    `current` = {poster_id: PosterState} · ใบที่ไม่มีใน dict ถือว่าไม่มีในฐานข้อมูล
    → **ข้าม ไม่ใช่ INSERT** (ADR-0015 D5 ตกทอดมาทั้งดุ้น)

    pure function — ไม่ query ไม่เขียน ไม่แตะเวลาปัจจุบัน เพื่อให้ test ครอบได้ครบ
    ทุกสาขาโดยไม่ต้องมี DB
    """
    plans: list[PlannedWrite] = []
    for row in rows:
        state = current.get(row.poster_uuid)
        if state is None:
            plans.append(PlannedWrite(row, RowAction.SKIP_NOT_FOUND, {}, {}))
            continue

        already = {
            name: render_value(state.values.get(name))
            for name in NULL_ONLY_FIELDS
            if state.values.get(name) is not None
        }
        if not row.reference_url and not row.reference_note:
            plans.append(PlannedWrite(row, RowAction.SKIP_BLANK, {}, already))
            continue
        if already:
            # D29 — ตรวจเป็นก้อน: มีค่าอยู่แล้วแม้ช่องเดียว = ข้ามทั้งใบ
            plans.append(PlannedWrite(row, RowAction.SKIP_ALREADY_SET, {}, already))
            continue

        field_writes: dict[str, Any] = {}
        if row.reference_url:
            field_writes["reference_url"] = row.reference_url
        else:
            field_writes["reference_note"] = row.reference_note
        # D31 — ค่าที่ derive ได้ก็ต้องถูกเขียนและมีแถว audit ของตัวเอง
        field_writes["verification_status"] = derive_status(
            row.reference_url, row.reference_note
        )
        plans.append(PlannedWrite(row, RowAction.WRITE, field_writes, already))
    return plans


def planned_field_counts(plans: list[PlannedWrite]) -> dict[str, int]:
    """จำนวนแถวที่จะถูกเขียนจริง แยกทีละคอลัมน์ — ตัวเลขที่ใช้ assert หลัง commit."""
    counts = {name: 0 for name in WRITABLE_FIELDS}
    for plan in plans:
        for name in plan.field_writes:
            counts[name] += 1
    return counts


@dataclass(frozen=True)
class AuditEntry:
    """หนึ่งแถวที่จะลง `poster_attribute_reviews` — ADR-0010 D3 · ADR-0014 **D31**."""

    field: str
    value_before: str | None
    value_after: str


def audit_entries(plan: PlannedWrite) -> tuple[AuditEntry, ...]:
    """แถว audit ของใบหนึ่ง — **2 แถวต่อใบที่เขียนจริง** (D31)

    หนึ่งแถวของช่องที่คนกรอก **+ อีกหนึ่งแถวของ `verification_status` ที่ derive ได้**
    · ถ้าค่า derive ไม่มีแถวของตัวเอง จะมีคอลัมน์บน `posters` เปลี่ยนค่าโดยไม่มีร่องรอย
    ซึ่งชนตารางเส้นแบ่งของ ADR-0014 D2 · precedent = `size_format` ของ `manual_entry.py`

    `value_before` เป็น `None` เสมอ เพราะรอบนี้เขียนเฉพาะช่องที่เป็น `NULL` ครบทั้งก้อน
    (D29 · AC-6) — ไม่มีโหมดเขียนทับจึงไม่มีค่าเดิมให้เก็บ
    """
    return tuple(
        AuditEntry(field=name, value_before=None, value_after=render_value(value))
        for name, value in plan.field_writes.items()
    )


def assert_schema_ready(missing_columns: list[str]) -> None:
    """ปลายทางต้องมีคอลัมน์ครบก่อนเขียน — pure เพื่อให้ test ครอบได้โดยไม่ต้องมี DB

    อาการเดียวกับ `manual_entry.assert_schema_ready()`: รันในคอนเทนเนอร์ที่ image เก่า
    → model ไม่มีแอตทริบิวต์ (ได้ `AttributeError` ดิบ) · รันบน host แต่ DB ปลายทาง
    ยังไม่ migrate → คอลัมน์หายไป
    """
    if missing_columns:
        raise PrecheckError(
            "ปลายทางไม่มีคอลัมน์: " + ", ".join(missing_columns) + "\n"
            "แปลว่า **ปลายทางตามหลัง develop อยู่** — ถ้ารันในคอนเทนเนอร์คือ image เก่า "
            "(ต้อง build/pull ใหม่) ถ้ารันบน host คือ DB ยังไม่ `alembic upgrade head`\n"
            "คอลัมน์ชุดนี้มาจาก migration ของ ADR-0014 (INF-12)"
        )


# --------------------------------------------------------------------------
# รายงาน
# --------------------------------------------------------------------------


def _report(plans: list[PlannedWrite], target_label: str, committed: bool) -> None:
    planned = planned_field_counts(plans)
    by_action = {action: 0 for action in RowAction}
    for plan in plans:
        by_action[plan.action] += 1

    print()
    print("=" * 72)
    print(f"ปลายทาง : {target_label}")
    print(f"แถวในใบงาน : {len(plans)}")
    print()
    print("แยกทีละคอลัมน์ (ADR-0014 D22 · เขียนเฉพาะใบที่ทั้งสามช่องเป็น NULL — D29):")
    print(f"  {'คอลัมน์':<24} {'จะเขียน':>8}")
    for name in HUMAN_FIELDS:
        print(f"  {name:<24} {planned[name]:>8}")
    for name in DERIVED_FIELDS:
        print(
            f"  {name:<24} {planned[name]:>8}"
            "   ← derive จาก 2 ช่องบน (ADR-0014 D22) ไม่มีช่องให้กรอก"
        )

    print()
    print("แยกตามผลของแถว:")
    print(f"  จะเขียน                        : {by_action[RowAction.WRITE]}")
    print(
        f"  ข้าม — ยังไม่ได้เปิดหา          : {by_action[RowAction.SKIP_BLANK]}"
        "  (คงเป็น NULL = NOT_CHECKED)"
    )
    print(
        f"  ข้าม — มีค่าอยู่แล้วในสามช่องนั้น : "
        f"{by_action[RowAction.SKIP_ALREADY_SET]}  (D29 · ไม่มีโหมดเขียนทับ)"
    )
    print(
        f"  ข้าม — ไม่มีใบนี้ใน DB           : "
        f"{by_action[RowAction.SKIP_NOT_FOUND]}  (UPDATE เท่านั้น ไม่ INSERT)"
    )

    already = [p for p in plans if p.action is RowAction.SKIP_ALREADY_SET]
    if already:
        print()
        print("ใบที่ถูกข้ามเพราะมีค่าอยู่แล้ว (แก้ผ่านสคริปต์นี้ไม่ได้ — D29):")
        for plan in already:
            shown = " · ".join(f"{k}={v!r}" for k, v in plan.already_set.items())
            print(f"  บรรทัด {plan.row.lineno:>4}  {shown}")

    dupes = duplicate_reference_urls([p.row for p in plans])
    if dupes:
        print()
        print(f"⚠️  reference_url ซ้ำข้ามแถว {len(dupes)} กลุ่ม — **ไม่ใช่ error**")
        print(
            "   ใบไทยของหนังเรื่องเดียวกันใช้อาร์ตเวิร์กชุดเดียวกัน "
            "การซ้ำจึงถูกต้องได้ (ADR-0014 D30)"
        )
        for url, lines in dupes:
            print(f"   บรรทัด {', '.join(str(n) for n in lines)}  {url}")

    print()
    print(
        "เขียนเฉพาะ " + " · ".join(WRITABLE_FIELDS) + " — ไม่แตะคอลัมน์อื่นของ posters"
    )
    print("ไม่แตะ previous_note / title / image_url — เป็นข้อมูลให้คนอ่านอย่างเดียว")
    if not committed:
        print()
        print("DRY-RUN — ไม่ได้เขียนอะไรลง database (ใส่ --commit เพื่อเขียนจริง)")
    print("=" * 72)


def _report_counts(
    before: dict[str, int], after: dict[str, int], planned: dict[str, int]
) -> int:
    """เทียบ `count(<column>)` ก่อน/หลัง กับจำนวนที่วางแผนไว้ — ไม่ตรง = ถือว่าพัง

    🔴 **`count(<column>)` ไม่ใช่ `count(*)`** — สคริปต์นี้ UPDATE อย่างเดียว จำนวนแถว
    ทั้งตารางจึงไม่ขยับไม่ว่าจะเขียนสำเร็จหรือไม่ · เหตุผลเต็มอยู่ที่ docstring ของ
    `manual_entry._column_counts()`
    """
    print()
    print(
        "assert count(<column>) — ไม่ใช่ count(*) ซึ่งจะเขียวตลอดกาลกับสคริปต์ UPDATE:"
    )
    print(f"  {'คอลัมน์':<24} {'ก่อน':>7} {'หลัง':>7} {'ต่าง':>7} {'ที่วางแผน':>10}")
    ok = True
    for name in WRITABLE_FIELDS:
        delta = after[name] - before[name]
        mark = "" if delta == planned[name] else "  🔴"
        ok = ok and delta == planned[name]
        print(
            f"  {name:<24} {before[name]:>7} {after[name]:>7} "
            f"{delta:>+7} {planned[name]:>10}{mark}"
        )
    if not ok:
        print(
            "\n🔴 จำนวนที่เพิ่มจริงไม่ตรงกับแผน — ข้อมูลเข้าไปแล้ว (commit ไปแล้ว) "
            "ต้องตรวจ poster_attribute_reviews กับ posters ด้วยมือก่อนรันอะไรต่อ"
        )
        return 1
    return 0


# --------------------------------------------------------------------------
# ตัวรัน
# --------------------------------------------------------------------------


async def _column_counts(session: Any) -> dict[str, int]:
    from sqlalchemy import func, select

    from app.models.poster import Poster

    result = await session.execute(
        select(*[func.count(getattr(Poster, name)) for name in WRITABLE_FIELDS])
    )
    return dict(zip(WRITABLE_FIELDS, result.one(), strict=True))


async def _load_state(session: Any, poster_ids: list[uuid.UUID]) -> dict:
    from sqlalchemy import select

    from app.models.poster import Poster

    result = await session.execute(
        select(Poster.id, *[getattr(Poster, n) for n in NULL_ONLY_FIELDS]).where(
            Poster.id.in_(poster_ids)
        )
    )
    state: dict[uuid.UUID, PosterState] = {}
    for row in result.all():
        poster_id, *rest = row
        state[poster_id] = PosterState(
            values=dict(zip(NULL_ONLY_FIELDS, rest, strict=True))
        )
    return state


async def run(args: argparse.Namespace, target_label: str) -> int:
    from app.core.database import async_session_maker
    from app.models.poster import Poster
    from app.models.poster_attribute_review import PosterAttributeReview

    # ปลายทางตามหลัง develop = ไม่มีแอตทริบิวต์ → ต้องบอกสาเหตุจริง ไม่ใช่ AttributeError ดิบ
    assert_schema_ready([n for n in WRITABLE_FIELDS if not hasattr(Poster, n)])
    assert_own_sheet(args.file)

    rows = parse_rows(read_sheet(args.file))
    if not rows:
        print("ใบงานไม่มีแถวข้อมูล — ไม่มีอะไรให้ทำ")
        return 0

    async with async_session_maker() as session:
        current = await _load_state(session, [r.poster_uuid for r in rows])
        plans = plan_writes(rows, current)

        _report(plans, target_label, committed=args.commit)
        if not args.commit:
            return 0

        before = await _column_counts(session)
        planned = planned_field_counts(plans)
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
                        reviewed_by=args.reviewed_by,
                        reviewed_at=args.reviewed_at,
                        source=source,
                    )
                )
                written += 1

        await session.commit()
        after = await _column_counts(session)

    print(
        f"\nเขียนจริงแล้ว {written} ค่า · "
        f"บันทึก audit {written} แถวลง poster_attribute_reviews"
    )
    return _report_counts(before, after, planned)


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
        default=DEFAULT_REFERENCE_CSV,
        help=f"ใบงาน (default: {DEFAULT_REFERENCE_CSV.name})",
    )
    parser.add_argument(
        "--target",
        choices=TARGETS,
        default="dev",
        help="ปลายทาง — เหมือนเส้นที่ 3 ทุกประการ (ADR-0015 D8: dev กับ sit เท่านั้น "
        "production ไม่มีให้เลือกโดยตั้งใจ) · sit ต้องรันข้างในคอนเทนเนอร์ sit "
        f"และ DATABASE_URL ต้องตรงกับ {SIT_ENV_FILE} เป๊ะ",
    )
    parser.add_argument(
        "--reviewed-by",
        help="ชื่อคนที่เปิดหาแหล่งอ้างอิงรอบนี้ — บังคับเมื่อ --commit (ADR-0010 D1)",
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
                "    exec app python scripts/seed/reference_entry.py --target sit"
            )
        print(
            f"ต่อ database ไม่ได้ (target={args.target}): {exc}{hint}", file=sys.stderr
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
