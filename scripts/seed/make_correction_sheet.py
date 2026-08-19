"""สร้าง **ใบงาน** ให้คนตรวจซ้ำแล้วแก้ค่าที่ผิด/เซ็นรับ/ถอนของ — ADR-0010 Amendment
2026-08-09 (INF-21) · ADR-0027 (INF-29)

    ./venv/bin/python scripts/seed/make_correction_sheet.py
    ./venv/bin/python scripts/seed/make_correction_sheet.py --all --out /path/to/sheet.csv

อ่าน `posters` + `poster_images` จาก **dev DB บนเครื่องนี้** อย่างเดียว ไม่เขียนอะไรเลย
— ทรงเดียวกับ `make_manual_sheet.py` และ `make_reference_sheet.py` ทุกประการ

🔴 **สคริปต์นี้ไม่ใช่ตัวตัดสิน และห้ามทำให้เป็น** — แปดช่องที่คนกรอก (ค่า+เหตุผล ของ
`condition_grade` · `is_unique` · `verified_at` · `published_at`) ถูกเขียนเป็นค่าว่าง
**เสมอ ไม่มี flag ไหนเติมค่าให้ได้** · เครื่องที่เสนอเกรดใหม่ให้คนเซ็นคือเครื่องที่
ตัดสินสภาพสินค้าแทนคน ซึ่ง **ADR-0009 D6** และ **ADR-0014 D7** ห้ามไว้ตลอดกาล
(หลักและรูปแบบเดียวกับ `approved`/`corrected_text` ของ `make_review_sheet.py`
และ `reference_url`/`reference_note` ของ `make_reference_sheet.py`) · มีเทสระดับ AST ล็อกไว้

**และห้ามเติมช่อง `*_reason` เป็นพิเศษ** — เหตุผลที่เครื่องเขียนให้ไม่ใช่เหตุผล มันคือ
ข้อความที่ทำให้ audit *ดูเหมือน* มีคนรู้เห็น ทั้งที่ไม่มี (A-D2 ข้อ 2)

## คอลัมน์

    poster_uuid · title · image_url ·
    current_condition_grade · current_is_unique ·
    current_verified_at · current_published_at         ← เครื่องเติม
    condition_grade · condition_grade_reason ·
    is_unique · is_unique_reason ·
    verified_at · verified_at_reason ·
    published_at · published_at_reason                 ← คนกรอก

🔴 **ค่าใน `current_*` เขียนด้วยคำชุดเดียวกับที่ช่องกรอกรับ** (`is_unique` → `Y`/`N`
ไม่ใช่ `True`/`False` · `verified_at`/`published_at` → `KEEP` หรือว่างเปล่า **ห้าม
พิมพ์วันที่จริงเด็ดขาด**) ผ่าน `correction_entry.render_current_value()` ที่เดียว —
ช่องช่วยจำอยู่ติดกับช่องกรอก คนจึงก๊อปข้ามช่อง และ**ควรก๊อปได้** · ใบงานที่สอนคำ
ที่พาร์เซอร์ปฏิเสธคือใบงานที่ปฏิเสธคนที่ทำถูก (เกิดจริง 5/5 แถว 2026-08-11 · G7)

`current_*` เป็น **ช่องช่วยจำของคน** ให้เห็นว่ากำลังจะทับ/เปลี่ยนอะไร —
`correction_entry.py` **ไม่อ่านมันเลย** (มีเทสล็อกที่ระดับคีย์ที่ถูกอ่านจริง) ·
ค่าที่สคริปต์ apply ใช้เทียบคือค่าที่อ่านจาก DB สด ๆ ตอนรัน ไม่ใช่ค่าในไฟล์ ซึ่งอาจเก่าไปแล้ว

`image_url` ประกอบจาก `poster_images.storage_key` ผ่าน `build_media_url()` เท่านั้น
(ADR-0006) และเอาเฉพาะ key ที่อยู่ใต้ `posters/public/` (ADR-0006 D5 · ADR-0007)

## ใบไหนเข้าใบงาน

ปริยาย = **ใบที่มีเกรดอยู่แล้ว** เพราะเส้นนี้ *แก้* ไม่ใช่ *เติม* — ใบที่ยังไม่มีเกรด
ถูก `correction_entry.py` ข้ามพร้อมรายงานอยู่แล้ว การใส่มาในใบงานคือการเชิญให้คนกรอก
สิ่งที่ไม่มีวันถูกเขียน (หลักเดียวกับ `make_reference_sheet.py`)

⚠️ `--all` จำเป็นจริงอยู่กรณีเดียว: **แก้ `is_unique` ของใบที่ยังไม่มีเกรด** ซึ่งทำได้
(ฟิลด์นั้นเป็น `NOT NULL` จึงมีค่าเดิมเสมอ) แต่หลุดตัวกรองปริยายไป — `verified_at`/
`published_at` ไม่มีกรณีนี้ เพราะทั้งคู่มีค่าได้ก็ต่อเมื่อมีเกรดแล้วเท่านั้น (ด่านก่อนเซ็น
ต้องมี `condition_grade` · CHECK ระดับ DB บังคับ `published ⇒ มีเกรด` อยู่แล้ว)
"""

from __future__ import annotations

import argparse
import csv
import os
import sys
from pathlib import Path
from typing import Any

SEED_DIR = Path(__file__).resolve().parent
REPO_ROOT = SEED_DIR.parents[1]
sys.path.insert(0, str(REPO_ROOT))

from scripts.seed.apply_suggestions import (  # noqa: E402
    PrecheckError,
    _load_env,
    assert_target_database,
)
from scripts.seed.correction_entry import (  # noqa: E402
    CORRECTION_SHEET_COLUMNS,
    DEFAULT_CORRECTION_CSV,
    REASON_COLUMNS,
    WRITABLE_FIELDS,
    render_current_value,
)

# ช่องที่ **คน** กรอก — ประกอบจากทูเพิลของเส้นที่ 5 ไม่พิมพ์รายชื่อซ้ำ · เทส AST
# ใช้เซตนี้ยืนยันว่าเครื่องเขียนทุกช่องเป็นค่าว่างคงที่ ไม่ใช่นิพจน์
HUMAN_COLUMNS = WRITABLE_FIELDS + REASON_COLUMNS


def build_sheet_rows(
    posters: list[dict[str, Any]],
    image_urls: dict[Any, str],
    *,
    include_all: bool,
) -> list[dict[str, str]]:
    """แปลงแถวจาก DB → แถวใบงาน (pure — ไม่แตะไฟล์ ไม่ query)

    `posters` = dict ต่อใบ มีคีย์ `id` · `title` + คอลัมน์ของ `WRITABLE_FIELDS`

    แปดช่องที่คนกรอก (ค่า+เหตุผล ของ 4 ฟิลด์) เป็นค่าว่างเสมอ ดู docstring ของโมดูล
    """
    rows: list[dict[str, str]] = []
    for poster in posters:
        if not include_all and poster.get("condition_grade") is None:
            continue
        rows.append(
            {
                "poster_uuid": str(poster["id"]),
                "title": poster.get("title") or "",
                "image_url": image_urls.get(poster["id"], ""),
                # 🔴 `render_current_value()` ไม่ใช่ `render_value()` — ช่องนี้อยู่
                # ติดกับช่องที่คนกรอกและถูกก๊อปข้ามช่องเป็นปกติ คำที่พิมพ์ลงไปจึง
                # ต้องเป็นคำที่พาร์เซอร์ของฟิลด์นั้นอ่านออก (เหตุผลเต็มอยู่ที่
                # docstring ของฟังก์ชันนั้น · G7 เกิดจริง 2026-08-11)
                "current_condition_grade": render_current_value(
                    "condition_grade", poster.get("condition_grade")
                ),
                "current_is_unique": render_current_value(
                    "is_unique", poster.get("is_unique")
                ),
                # G7 (ADR-0027) — ห้ามพิมพ์วันที่จริง ผ่าน render_current_value() ตัวเดียว
                # เหมือนสองช่องบน — คืน KEEP หรือว่างเปล่าเท่านั้น
                "current_verified_at": render_current_value(
                    "verified_at", poster.get("verified_at")
                ),
                "current_published_at": render_current_value(
                    "published_at", poster.get("published_at")
                ),
                "condition_grade": "",
                "condition_grade_reason": "",
                "is_unique": "",
                "is_unique_reason": "",
                "verified_at": "",
                "verified_at_reason": "",
                "published_at": "",
                "published_at_reason": "",
            }
        )
    # ใบที่ `is_unique` เป็น false ขึ้นก่อน — ADR-0019 บอกไว้แล้วว่าแถวพวกนี้คือ
    # แถวที่รู้อยู่แล้วว่าไม่ตรงกับมติ D1 จึงเป็นแถวที่คนลงมือได้ทันที
    # (หลักเดียวกับ sort_key ของ make_manual_sheet.py: เอาแถวที่ทำงานได้เลยขึ้นบน)
    rows.sort(
        key=lambda r: (
            r["current_is_unique"] != render_current_value("is_unique", False),
            r["title"],
        )
    )
    return rows


async def load_from_db() -> tuple[list[dict[str, Any]], dict[Any, str]]:
    """อ่าน `posters` + รูปตัวแทนของแต่ละใบ — read-only ล้วน ๆ."""
    from sqlalchemy import select

    from app.core.database import async_session_maker
    from app.core.media import build_media_url, is_public_storage_key
    from app.models.poster import Poster, PosterImage

    columns = [Poster.id, Poster.title] + [
        getattr(Poster, name) for name in WRITABLE_FIELDS
    ]
    async with async_session_maker() as session:
        result = await session.execute(select(*columns).order_by(Poster.title))
        posters = [dict(row._mapping) for row in result.all()]

        images = await session.execute(
            select(PosterImage.poster_id, PosterImage.storage_key).order_by(
                PosterImage.poster_id,
                PosterImage.is_primary.desc(),
                PosterImage.sort_order,
            )
        )
        urls: dict[Any, str] = {}
        for poster_id, storage_key in images.all():
            if poster_id in urls:
                continue
            # ADR-0006 D5 — build_media_url() raise ถ้า key ไม่ public · กรองก่อนเสมอ
            if is_public_storage_key(storage_key):
                urls.setdefault(poster_id, build_media_url(storage_key))
    return posters, urls


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=DEFAULT_CORRECTION_CSV,
        help=f"ใบงานที่จะสร้าง (default: {DEFAULT_CORRECTION_CSV.name})",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="ใส่ทุกใบ ไม่ใช่เฉพาะใบที่มีเกรดอยู่แล้ว (ดู §ใบไหนเข้าใบงาน)",
    )
    args = parser.parse_args()

    if args.out.exists():
        # กันเขียนทับใบงานที่คนกรอกไปแล้วครึ่งทาง — งานที่หายไปกู้ไม่ได้
        # (CSV ในโฟลเดอร์นี้ไม่อยู่ใน git เลย ดู README §6)
        print(
            f"{args.out} มีอยู่แล้ว — ลบหรือเปลี่ยนชื่อก่อน (กันทับใบงานที่กรอกไปแล้ว)",
            file=sys.stderr,
        )
        return 1

    _load_env("dev")
    database_url = os.environ.get("DATABASE_URL", "")
    if not database_url:
        print("ไม่พบ DATABASE_URL", file=sys.stderr)
        return 1
    try:
        target_label = assert_target_database(database_url, "dev")
    except PrecheckError as exc:
        print(f"precheck ไม่ผ่าน: {exc}", file=sys.stderr)
        return 1

    import asyncio

    posters, image_urls = asyncio.run(load_from_db())
    rows = build_sheet_rows(posters, image_urls, include_all=args.all)

    with args.out.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(CORRECTION_SHEET_COLUMNS))
        writer.writeheader()
        writer.writerows(rows)

    not_unique = sum(
        1
        for r in rows
        if r["current_is_unique"] == render_current_value("is_unique", False)
    )
    no_image = sum(1 for r in rows if not r["image_url"])
    print(f"อ่านจาก {target_label} — {len(posters)} ใบ")
    print(f"เขียน {args.out} — {len(rows)} แถว\n")
    print(
        f"  is_unique = false อยู่ตอนนี้ {not_unique} แถว (ADR-0019 — เรียงขึ้นบนสุด)"
    )
    if no_image:
        print(
            f"  ⚠️  ไม่มีรูป public ให้เปิดดู {no_image} ใบ — ตรวจสภาพจากใบงานนี้ไม่ได้"
        )
    print(
        "\nขั้นต่อไป: หยิบใบจริงขึ้นมาตรวจซ้ำ แล้วกรอก **ค่าใหม่ + เหตุผล** คู่กันเสมอ"
    )
    print("  แก้เกรด   → condition_grade + condition_grade_reason")
    print(
        "  แก้จำนวน  → is_unique = Y + is_unique_reason "
        "(N เขียนไม่ได้เลย ADR-0019 D5/D6 — ของหลายชิ้นต้องแตกแถว = INF-22)"
    )
    print(
        "  เซ็นรับ   → verified_at = SIGN + verified_at_reason "
        "(ต้องผ่านด่านก่อนเซ็นก่อน — ADR-0027 D3)"
    )
    print(
        "  ถอนของ    → published_at = WITHDRAW + published_at_reason "
        "(ถอนใบที่ status=sold ไม่ได้ทุกกรณี — ADR-0027 A-D11)"
    )
    print("  ไม่ต้องแก้ → เว้นว่างทั้งคู่ (กรอกค่าโดยไม่มีเหตุผล = ปฏิเสธทั้งไฟล์)")
    print(
        "\n🔴 แก้เกรด/จำนวนจริง ⇒ ลายเซ็นและสถานะเปิดขายเดิม (ถ้ามี) ถูกล้างอัตโนมัติ "
        "ในรอบเดียวกัน (ADR-0027 D6) — แถวจะหลุดจากร้านจนกว่าจะมีคนตรวจและเซ็นใหม่"
    )
    print(
        "\nจากนั้น ./venv/bin/python scripts/seed/correction_entry.py  (dry-run ก่อนเสมอ)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
