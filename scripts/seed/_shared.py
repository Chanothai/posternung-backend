"""กฎที่ **เส้นทางเขียน `posters` มากกว่าหนึ่งเส้นใช้ร่วมกัน** — ที่อยู่เดียวของมัน

ADR-0015 **D1** บอกว่าห้าเส้นทางนั้น *คนละแหล่ง คนละกฎ ห้ามยุบรวม* — โมดูลนี้
**ไม่ได้ยุบเส้นทาง** มันเก็บเฉพาะกฎที่ทุกเส้นต้องเชื่อฟังเหมือนกันเป๊ะ ๆ อยู่แล้ว
(รูปแบบของ `--reviewed-at` ตาม ADR-0010 **D5** · ด่านปฏิเสธเวลาอนาคต · การอ่านใบงาน
CSV ที่มี field เกิน header) · ค่าที่แต่ละเส้น *เขียนได้* ยังอยู่ในไฟล์ของตัวเองทั้งหมด

🔴 **ทำไมต้องมีไฟล์นี้แทนที่จะ import ข้ามเส้น** — ก่อนหน้านี้เส้นที่ 4 import
`_parse_reviewed_at` จากเส้นที่ 3 และ `PrecheckError` จากเส้นที่ 2 ทำให้เส้นที่ทำทีหลัง
กลายเป็นโมดูลกลางโดยบังเอิญ · พอเส้นที่ 2 ต้องใช้ด่านที่เกิดในเส้นที่ 4 ทิศของ import
จะกลับหัวและวนกลับมาหาตัวเอง · ที่นี่ **ห้าม import อะไรจากไฟล์ของเส้นทางใด ๆ**
ทิศทางเป็นทางเดียวเสมอ: lane → `_shared`

🔴 **ห้ามเขียนตัวอย่าง `--reviewed-at` เป็นเวลาจริงในไฟล์ใดก็ตามของ `scripts/seed/`**
— เกิดขึ้นจริง 2026-08-08: ตัวอย่างใน docstring ถูกก๊อปมาทั้งบรรทัดแล้ว `reviewed_at`
ของ 232 แถวลงเป็นเวลาในอนาคต 3.5 ชั่วโมง ต้องตามแก้ด้วย SQL ตรง ๆ · มีเทสล็อกไว้
"""

from __future__ import annotations

import csv
from collections.abc import Sequence
from datetime import datetime, timedelta
from pathlib import Path

# รูปแบบที่ใช้บอกคนกรอกว่าต้องพิมพ์อะไร — **เป็นสเปกของรูปแบบ ไม่ใช่ค่าที่ใช้ได้จริง**
# ก๊อปทั้งบรรทัดไปรันแล้วต้องไม่ผ่าน (นั่นคือจุดประสงค์ทั้งหมดของมัน)
REVIEWED_AT_FORMAT_HINT = "YYYY-MM-DDThh:mm:ss+07:00"


class PrecheckError(Exception):
    """precheck ไม่ผ่าน — รายละเอียดอยู่ใน args[0] (หลายบรรทัดได้)."""


# --------------------------------------------------------------------------
# `--reviewed-at` — ADR-0010 D5
# --------------------------------------------------------------------------


def _parse_reviewed_at(raw: str, *, flag: str = "--reviewed-at") -> datetime:
    """ISO-8601 ที่ **ต้องมี timezone** — ห้ามให้เครื่องเดาแทนคนที่ตัดสิน

    ไม่มี default เป็น "เวลาตอนนี้" โดยตั้งใจ: เวลาที่คนตัดสินกับเวลาที่รันสคริปต์
    เป็นคนละเวลากันได้มาก (ตรวจวันนี้ apply อาทิตย์หน้า) การเดาให้คือการกรอก
    ข้อมูลแทนคนซึ่งเป็นสิ่งเดียวกับที่ ADR-0009 D2 ห้าม · มีเทส AST ล็อกทั้งห้าเส้น
    ว่า `args.reviewed_at` มาจากฟังก์ชันนี้เท่านั้น

    🔴 **`flag` — เพิ่มโดย `code-critic` รอบ 1 ของ INF-24 (M-c)** — ตรรกะ ISO-8601+tz
    นี้เป็นด่านเดียวที่ใช้ร่วมกันได้ทั้งค่าที่แปลว่า *"เวลาที่คนตัดสิน"* (`--reviewed-at`
    ของห้าเส้นเดิม) และค่าที่แปลว่าอย่างอื่นแต่ต้องผ่านรูปแบบเดียวกันเป๊ะ (เช่น
    `--sold-at` ของ `sold_entry.py` ซึ่งแปลว่า *"เวลาที่ของขายออกไปจริง"* — ADR-0025
    D4) ก่อนหน้านี้ `sold_entry.py` ก๊อปฟังก์ชันนี้ทั้งดุ้นเพียงเพราะข้อความ error
    hardcode คำว่า `--reviewed-at` ไว้ตรง ๆ — พารามิเตอร์นี้แก้ที่ต้นเหตุแทน ไม่ต้อง
    ก๊อปเลย ค่าเริ่มต้นคงเดิมเป๊ะจึงไม่กระทบ 5 เส้นที่เรียกโดยไม่ระบุ `flag`
    """
    try:
        value = datetime.fromisoformat(raw)
    except ValueError:
        raise PrecheckError(f"{flag} {raw!r} ไม่ใช่ ISO-8601") from None
    if value.tzinfo is None:
        raise PrecheckError(
            f"{flag} {raw!r} ไม่มี timezone — ต้องระบุเอง "
            f"ตามรูปแบบ {REVIEWED_AT_FORMAT_HINT}"
        )
    return value


def _render_ahead(ahead: timedelta) -> str:
    """`timedelta` → ข้อความไทยอ่านง่าย — ตัวเลขคือสิ่งที่ทำให้คนเห็นว่าพิมพ์อะไรผิด."""
    total = int(ahead.total_seconds())
    days, rest = divmod(total, 86400)
    hours, rest = divmod(rest, 3600)
    minutes, secs = divmod(rest, 60)
    parts = []
    if days:
        parts.append(f"{days} วัน")
    if hours:
        parts.append(f"{hours} ชั่วโมง")
    if minutes:
        parts.append(f"{minutes} นาที")
    if secs or not parts:
        parts.append(f"{secs} วินาที")
    return " ".join(parts)


def assert_not_in_the_future(value: datetime, *, now: datetime) -> None:
    """`--reviewed-at` ที่อยู่ในอนาคต = ปฏิเสธ (pure — ไม่อ่านนาฬิกาเอง)

    🔴 **รับ `now` เข้ามาเป็นพารามิเตอร์โดยตั้งใจ** — ฟังก์ชันนี้จึงเป็น pure function
    ที่เทสได้โดยไม่ต้อง freeze เวลา และที่สำคัญกว่านั้นคือ **`main()` ของแต่ละเส้นเป็น
    ที่เดียวที่อ่านนาฬิกาได้** ซึ่งเป็นสิ่งที่ทำให้ ADR-0010 D5 (ห้ามมี default เป็นเวลา
    ปัจจุบัน) ยังยืนอยู่ได้แม้จะมีด่านที่ต้องรู้เวลาปัจจุบัน — *อ่านนาฬิกาเพื่อ
    **ปฏิเสธ** คนละเรื่องกับอ่านนาฬิกาเพื่อ **จ่ายค่า*** · มีเทส AST ล็อกทั้งสองข้อ

    `reviewed_at` แปลว่า **เวลาที่คนตัดสิน** อย่างเดียว เวลาในอนาคตจึงผิดโดยนิยาม
    ไม่มีเคสที่ถูกต้อง (เกิดจริง 2026-08-08 — ก๊อปเวลาตัวอย่างจาก docstring มาทั้ง
    บรรทัดแล้ว 232 แถวลงเป็นอนาคต 3.5 ชั่วโมง)

    เท่ากับ `now` เป๊ะ ๆ **ผ่าน** — ด่านนี้ไม่ใช่ strict เพราะคนที่ตัดสินเสร็จแล้วรัน
    ทันทีคือการใช้งานปกติ · precondition: ทั้งสองค่าต้องมี timezone (มาจาก
    `_parse_reviewed_at()` ซึ่งบังคับไว้แล้ว) จึงเทียบกันเป็น *instant* ไม่ใช่หน้าปัด
    """
    if value <= now:
        return
    raise PrecheckError(
        f"--reviewed-at {value.isoformat()} อยู่ในอนาคต "
        f"{_render_ahead(value - now)} "
        f"(เวลาตอนนี้ = {now.astimezone(value.tzinfo).isoformat()})\n"
        "ค่านี้แปลว่า *เวลาที่คนตัดสิน* จึงเป็นอนาคตไม่ได้ (ADR-0010 D5)\n"
        "มักเกิดจากพิมพ์ timezone ผิด หรือก๊อปค่าตัวอย่างในเอกสารมาทั้งบรรทัด — "
        "ตัวอย่างทุกที่เป็น placeholder ไม่ใช่ค่าที่ใช้ได้จริง"
    )


# --------------------------------------------------------------------------
# อ่านใบงาน CSV — ด่าน field เกิน header
# --------------------------------------------------------------------------

# คีย์ที่ `csv.DictReader` ใช้เก็บ field ที่เกิน header — ต้องตั้งเอง ไม่งั้นค่าเริ่มต้น
# เป็น `None` แล้วค่าที่ได้เป็น **list** ทำให้ `.strip()` โยน `AttributeError` ดิบ
# แทนที่จะเป็น `PrecheckError` ที่บอกสาเหตุ (คนอ่านไม่ออกว่าไฟล์ผิดตรงไหน)
EXTRA_FIELDS_KEY = "__เกินจาก header__"


def read_sheet_rows(
    path: Path,
    *,
    required_columns: Sequence[str],
    sheet_columns: Sequence[str],
    maker_script: str,
    free_text_columns: Sequence[str],
) -> list[dict[str, str]]:
    """อ่านใบงานทั้งไฟล์ → list ของ dict ที่ตัดช่องว่างหัวท้ายของทุกช่องแล้ว

    🔴 **นี่คือทางเดียวที่ *สี่เส้นที่รับ `--reviewed-at`* ใช้อ่านใบงาน** — การสร้าง
    `csv.DictReader` เองแล้วลืม `restkey` คือบั๊กที่เกิดจริง (BL-101): แถวที่มีค่าเกิน
    header จะได้ `list` ใต้คีย์ `None` แล้ว `.strip()` ระเบิดเป็น `AttributeError`
    ที่คนอ่านไม่ออกว่าต้องแก้อะไร แทนที่จะเป็นข้อความที่บอก **เลขบรรทัด** และ
    **สาเหตุที่เป็นไปได้จริง**

    ⚠️ **ไม่ใช่ *ทุก* เส้น — บั๊กคลาสเดียวกันยังมีชีวิตอยู่อีก 2 ที่ → `BL-103`**
    `seed_posters._read_csv()` (อ่าน `poster-triage-signoff.csv` ซึ่ง **คนกรอกเอง**)
    และ `make_review_sheet.py` ยังสร้าง reader ของตัวเองอยู่ · เทส
    `test_no_lane_builds_its_own_csv_reader` ครอบเฉพาะสี่เส้นใน `LANES` เท่านั้น
    **อย่าอ่านชื่อเทสนั้นว่าครอบทั้งโฟลเดอร์**

    เรียงลำดับด่านไว้แบบนี้โดยตั้งใจ: header ก่อน แล้วค่อยเนื้อไฟล์ — ไฟล์ที่ผิดทั้ง
    สองอย่างควรได้ยินเรื่อง header ก่อน เพราะแก้ header แล้วเลขบรรทัดจะเปลี่ยนหมด

    `path` ต้องมีอยู่จริงแล้ว — ข้อความ "ไม่พบใบงาน" เป็นของแต่ละเส้น เพราะแต่ละเส้น
    บอกคนละคำสั่งในการสร้างใบงานขึ้นมาใหม่
    """
    with path.open(newline="", encoding="utf-8-sig") as fh:
        reader = csv.DictReader(fh, restkey=EXTRA_FIELDS_KEY)
        header = list(reader.fieldnames or [])
        missing = [c for c in required_columns if c not in header]
        if missing:
            raise PrecheckError(
                f"ใบงานขาดคอลัมน์: {', '.join(missing)}\n"
                f"header ที่ {maker_script} สร้าง: {','.join(sheet_columns)}"
            )
        rows: list[dict[str, str]] = []
        for row in reader:
            # 🔴 `reader.line_num` ไม่ใช่การนับแถวเอง — ช่องที่ครอบอัญประกาศแล้วขึ้น
            # บรรทัดใหม่ทำให้ 1 แถวกินหลายบรรทัดในไฟล์ และบรรทัดว่างก็ถูกข้ามโดยไม่นับ
            # `enumerate()` จึงชี้ผิดบรรทัดทันทีที่ไฟล์มีอย่างใดอย่างหนึ่ง — และ
            # `reference_note` เป็นช่องข้อความอิสระที่คนพิมพ์เอง โอกาสมีบรรทัดใหม่
            # ไม่ใช่เรื่องทฤษฎี · หน้าที่ทั้งหมดของข้อความนี้คือชี้ให้คนไปแก้บรรทัดไหน
            lineno = reader.line_num
            if EXTRA_FIELDS_KEY in row:
                raise PrecheckError(
                    f"บรรทัด {lineno}: มีค่ามากกว่าจำนวนคอลัมน์ใน header "
                    f"({len(header)} คอลัมน์)\n"
                    f"มักเกิดจากข้อความใน {' หรือ '.join(free_text_columns)} "
                    'มีจุลภาคแล้วไม่ได้ครอบด้วย "…" — แก้ที่ไฟล์แล้วรันใหม่'
                )
            rows.append({k: (v or "").strip() for k, v in row.items()})
        return rows
