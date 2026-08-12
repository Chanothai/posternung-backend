"""สร้าง **ใบงาน** ให้คนกรอกเกรด/ราคา/เหตุผลของชิ้นที่จะแตกออกจากแถวพ่อ — ADR-0024 (INF-22)

    ./venv/bin/python scripts/seed/make_split_sheet.py
    ./venv/bin/python scripts/seed/make_split_sheet.py --all --out /path/to/sheet.csv

อ่าน `posters` จาก **dev DB บนเครื่องนี้** อย่างเดียว ไม่เขียนอะไรเลย — ทรงเดียวกับ
`make_correction_sheet.py`/`make_manual_sheet.py` ทุกประการ

🔴 **สคริปต์นี้ไม่ใช่ตัวตัดสิน และห้ามทำให้เป็น** — สามช่องที่คนกรอก
(`condition_grade` · `price` · `reason`) ถูกเขียนเป็นค่าว่าง**เสมอ ไม่มี flag ไหน
เติมค่าให้ได้** — เครื่องที่เสนอเกรด/ราคาให้คนเซ็นรับคือเครื่องที่ตัดสินสภาพและราคา
สินค้าแทนคน ซึ่ง **ADR-0009 D6** ห้ามไว้ตลอดกาล (หลักและรูปแบบเดียวกับ
`condition_grade`/`is_unique` ของ `make_correction_sheet.py`) · มีเทสระดับ AST ล็อกไว้

## คอลัมน์

    parent_poster_uuid · parent_title · parent_image_url   ← เครื่องเติม (อ่านอย่างเดียว)
    condition_grade · price · reason                       ← คนกรอก

`parent_image_url` ประกอบจาก `poster_images.storage_key` ผ่าน `build_media_url()`
เท่านั้น (ADR-0006) และเอาเฉพาะ key ที่อยู่ใต้ `posters/public/` (ADR-0006 D5) — ใบพ่อ
ที่มีแต่รูป internal จะได้ช่องว่าง

## ใบไหนเข้าใบงาน

ปริยาย = แถวที่ **`is_unique = false` และ published** (คือแถวที่รอแตกจริงตามความหมาย
ของ ADR-0019 D1/D2) — แถวที่ `is_unique = true` แล้วไม่ต้องแตก และแถวที่ยังไม่ publish
ยังไม่ใช่แถวที่ "มีคนเห็นแล้วว่าขายของหลายชิ้น" จึงไม่ต้องเร่งแตกวันนี้ (ใช้ `--all`
ถ้าต้องการเห็นทุกแถวรวมสองกลุ่มนั้นด้วย — เช่นเตรียมแตกล่วงหน้าก่อน publish)

⚠️ **ต่างจาก `make_correction_sheet.py` ตรงตัวกรองปริยาย** — เส้นที่ 5 กรองด้วย
"มีเกรดอยู่แล้ว" เพราะมันเป็นเส้นที่ *แก้*ค่าที่มีอยู่ ส่วนเส้นนี้กรองด้วย
"`is_unique = false` และ published" เพราะมันเป็นเส้นที่ *สร้าง*แถวใหม่จากแถวที่รู้
อยู่แล้วว่าแทนของมากกว่าหนึ่งชิ้น — เกณฑ์ของสองเส้นตอบคนละคำถามกัน
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
from scripts.seed.split_entry import (  # noqa: E402
    DEFAULT_SPLIT_CSV,
    SPLIT_SHEET_COLUMNS,
)

# ช่องที่ **คน** กรอก — ประกอบจากค่าคงที่ของ split_entry.py ไม่พิมพ์รายชื่อซ้ำ · เทส
# AST ใช้เซตนี้ยืนยันว่าเครื่องเขียนทุกช่องเป็นค่าว่างคงที่ ไม่ใช่นิพจน์
HUMAN_COLUMNS = ("condition_grade", "price", "reason")


def build_sheet_rows(
    posters: list[dict[str, Any]],
    image_urls: dict[Any, str],
    *,
    include_all: bool,
) -> list[dict[str, str]]:
    """แปลงแถวพ่อจาก DB → แถวใบงาน (pure — ไม่แตะไฟล์ ไม่ query)

    `posters` = dict ต่อใบ มีคีย์ `id` · `title` · `is_unique` · `published_at`

    สามช่องที่คนกรอกเป็นค่าว่างเสมอ ดู docstring ของโมดูล
    """
    rows: list[dict[str, str]] = []
    for poster in posters:
        if not include_all:
            if poster.get("is_unique") is not False:
                continue
            if poster.get("published_at") is None:
                continue
        rows.append(
            {
                "parent_poster_uuid": str(poster["id"]),
                "parent_title": poster.get("title") or "",
                "parent_image_url": image_urls.get(poster["id"], ""),
                "condition_grade": "",
                "price": "",
                "reason": "",
            }
        )
    rows.sort(key=lambda r: r["parent_title"])
    return rows


async def load_from_db() -> tuple[list[dict[str, Any]], dict[Any, str]]:
    """อ่าน `posters` + รูปตัวแทนของแต่ละใบพ่อ — read-only ล้วน ๆ."""
    from sqlalchemy import select

    from app.core.database import async_session_maker
    from app.core.media import build_media_url, is_public_storage_key
    from app.models.poster import Poster, PosterImage

    async with async_session_maker() as session:
        result = await session.execute(
            select(
                Poster.id, Poster.title, Poster.is_unique, Poster.published_at
            ).order_by(Poster.title)
        )
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
        default=DEFAULT_SPLIT_CSV,
        help=f"ใบงานที่จะสร้าง (default: {DEFAULT_SPLIT_CSV.name})",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="ใส่ทุกใบ ไม่ใช่เฉพาะใบที่ is_unique=false และ published (ดู §ใบไหนเข้าใบงาน)",
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
        writer = csv.DictWriter(fh, fieldnames=list(SPLIT_SHEET_COLUMNS))
        writer.writeheader()
        writer.writerows(rows)

    no_image = sum(1 for r in rows if not r["parent_image_url"])
    print(f"อ่านจาก {target_label} — {len(posters)} ใบ")
    print(f"เขียน {args.out} — {len(rows)} แถว\n")
    if no_image:
        print(
            f"  ⚠️  ไม่มีรูป public ให้เปิดดู {no_image} ใบ — ตรวจสภาพจากใบงานนี้ไม่ได้"
        )
    print(
        "\nขั้นต่อไป: หยิบใบจริงขึ้นมา แล้วกรอก **condition_grade · price · reason** "
        "ของชิ้นที่จะแตกออกมา ครบทั้งสามช่องพร้อมกัน (ไม่มีแนวคิด 'เติมทีหลัง')"
    )
    print("\nจากนั้น ./venv/bin/python scripts/seed/split_entry.py  (dry-run ก่อนเสมอ)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
