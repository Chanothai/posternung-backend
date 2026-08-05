"""สร้าง **ใบงาน** ให้คนกรอกฟิลด์ที่เครื่องเดาแทนไม่ได้ — ADR-0015 (INF-11)

    ./venv/bin/python scripts/seed/make_manual_sheet.py
    ./venv/bin/python scripts/seed/make_manual_sheet.py --all --out /path/to/sheet.csv

อ่าน `posters` + `poster_images` จาก **dev DB บนเครื่องนี้** อย่างเดียว ไม่เขียนอะไรเลย
· ต่างจาก `make_review_sheet.py`/`make_triage_sheet.py` ที่อ่านจาก CSV เพราะฟิลด์ชุดนี้
ไม่มีแหล่งอื่นนอกจากตัว DB เอง — ไม่มีไฟล์ export ไหนมีคอลัมน์ `condition_grade`

🔴 **สคริปต์นี้ไม่ใช่ตัวตัดสิน และห้ามทำให้เป็น** — คอลัมน์ `publish` ถูกเขียนเป็น
ค่าว่างเสมอ ไม่มี flag ให้เติมอัตโนมัติ ถ้าเครื่องกรอกคอลัมน์นี้ให้ ก็คือเครื่องตัดสินใจ
เปิดขายแทนคน ซึ่งขัด ADR-0013 D4 ตรง ๆ (และหลักเดียวกับ ADR-0009 D6) · หลักและรูปแบบ
เดียวกับ `make_review_sheet.py` ของ ADR-0010 และ `make_triage_sheet.py` ของ ADR-0009 D6

**ค่าที่มีอยู่แล้วใน DB ถูกเติมมาให้ดู** เพื่อให้รู้ว่าช่องไหนกรอกไปแล้ว — และเพราะ
`manual_entry.py` เขียนเฉพาะช่องที่ปลายทางเป็น `NULL` (ADR-0015 D6) ค่าที่เติมมาจึงถูก
ข้ามเสมอตอน apply ทำให้รันซ้ำได้โดยไม่มีอะไรเปลี่ยน

⚠️ **ค่าที่เติมมาไม่ใช่ค่าที่ "มีคนยืนยันแล้ว" เสมอไป** — `year` เป็นฟิลด์เดียวที่
`seed_posters.py` เขียนได้ (ข้อยกเว้นของ ADR-0009 D6 ข้อ 2) และค่าที่มันเขียนคือ
`year_guess` จากไฟล์ export ไม่ใช่ค่าที่ใครตรวจ · วันนี้ยังไม่มีผลจริงเพราะ
`posters.year` เป็น `NULL` ทั้งตาราง (`screens.yaml` INF-06 known_gaps ข้อ 1) แต่ถ้าวันไหน
มีค่าโผล่มา **ต้องรู้ว่าแก้ผ่านเส้นทางนี้ไม่ได้** — ไม่มีโหมดเขียนทับ (ADR-0015 §ผลเสียที่ยอมรับ)

`image_url` ประกอบจาก `poster_images.storage_key` ผ่าน `build_media_url()` เท่านั้น
(ADR-0006) และเอาเฉพาะ key ที่อยู่ใต้ `posters/public/` (ADR-0006 D5 · ADR-0007) —
ใบที่มีแต่รูป internal จะได้ช่องว่าง พร้อมนับให้เห็นในสรุปท้ายการรัน
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
from scripts.seed.manual_entry import (  # noqa: E402
    ALLOWED_FIELDS,
    DEFAULT_MANUAL_CSV,
    MANUAL_SHEET_COLUMNS,
    render_value,
)


def build_sheet_rows(
    posters: list[dict[str, Any]],
    image_urls: dict[Any, str],
    *,
    include_complete: bool,
) -> list[dict[str, str]]:
    """แปลงแถวจาก DB → แถวใบงาน (pure — ไม่แตะไฟล์ ไม่ query)

    `posters` = dict ต่อใบ มีคีย์ `id` · `title` · `published_at` + 5 ฟิลด์ของ
    `ALLOWED_FIELDS` · `image_urls` = {poster_id: url} (ใบที่ไม่มี url public ไม่ต้องมีคีย์)

    "ยังกรอกไม่ครบ" = มีอย่างน้อยหนึ่งช่องใน `ALLOWED_FIELDS` เป็น `NULL`
    **หรือ** ยังไม่ถูกเปิดขาย — ใบที่ครบและเปิดขายแล้วไม่มีอะไรให้คนทำในใบงานนี้

    `publish` เป็นค่าว่างเสมอ ดู docstring ของโมดูล
    """
    rows: list[dict[str, str]] = []
    for poster in posters:
        missing = [n for n in ALLOWED_FIELDS if poster.get(n) is None]
        unpublished = poster.get("published_at") is None
        if not include_complete and not missing and not unpublished:
            continue
        row = {
            "poster_uuid": str(poster["id"]),
            "title": poster.get("title") or "",
            "image_url": image_urls.get(poster["id"], ""),
            "publish": "",
            "note": "",
        }
        for name in ALLOWED_FIELDS:
            row[name] = render_value(poster.get(name))
        rows.append(row)

    # ใบที่ยังไม่มีเกรดขึ้นก่อน แล้วเรียงตามจำนวนช่องที่ว่างมาก→น้อย
    # เหตุผล: `condition_grade` เป็นด่านเดียวที่กั้นการเปิดขายอยู่จริง (ADR-0013 D3)
    # ใบที่ขาดแค่มันใบเดียวคือใบที่ใกล้ขึ้นหน้าร้านที่สุด · ถ้าเรียงตามชื่อเฉย ๆ คนจะไล่
    # ผ่านใบที่กรอกครบแล้วหลายสิบแถวก่อนเจอของจริง (หลักเดียวกับ STATUS_ORDER ของ
    # make_review_sheet.py)
    def sort_key(row: dict[str, str]) -> tuple:
        missing_count = sum(1 for n in ALLOWED_FIELDS if not row[n])
        return (bool(row["condition_grade"]), -missing_count, row["title"])

    rows.sort(key=sort_key)
    return rows


async def load_from_db() -> tuple[list[dict[str, Any]], dict[Any, str]]:
    """อ่าน `posters` + รูปตัวแทนของแต่ละใบ — read-only ล้วน ๆ."""
    from sqlalchemy import select

    from app.core.database import async_session_maker
    from app.core.media import build_media_url, is_public_storage_key
    from app.models.poster import Poster, PosterImage

    columns = [Poster.id, Poster.title, Poster.published_at] + [
        getattr(Poster, name) for name in ALLOWED_FIELDS
    ]
    async with async_session_maker() as session:
        result = await session.execute(select(*columns).order_by(Poster.title))
        posters = [dict(row._mapping) for row in result.all()]

        # รูปตัวแทน = รูป primary ถ้ามี ไม่งั้นเอาตัวแรกตาม sort_order — เรียงให้
        # ตัวที่ต้องการมาก่อน แล้วเก็บตัวแรกที่เจอต่อใบ (`setdefault`)
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
            # ไม่ใช่ไปผ่อนปรนฟังก์ชันนั้น (ADR-0007)
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
        default=DEFAULT_MANUAL_CSV,
        help=f"ใบงานที่จะสร้าง (default: {DEFAULT_MANUAL_CSV.name})",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="ใส่ทุกใบ ไม่ใช่เฉพาะใบที่ยังกรอกไม่ครบ",
    )
    args = parser.parse_args()

    if args.out.exists():
        # กันเขียนทับใบงานที่คนกรอกไปแล้วครึ่งทาง — งานที่หายไปกู้ไม่ได้
        # (CSV ในโฟลเดอร์นี้ไม่อยู่ใน git เลย ดู .gitignore:101)
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
    rows = build_sheet_rows(posters, image_urls, include_complete=args.all)

    with args.out.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(MANUAL_SHEET_COLUMNS))
        writer.writeheader()
        writer.writerows(rows)

    no_image = sum(1 for r in rows if not r["image_url"])
    print(f"อ่านจาก {target_label} — {len(posters)} ใบ")
    print(f"เขียน {args.out} — {len(rows)} แถว\n")
    print(f"  {'ฟิลด์':<20} {'ยังว่าง':>8} / {len(rows)}")
    for name in ALLOWED_FIELDS:
        print(f"  {name:<20} {sum(1 for r in rows if not r[name]):>8}")
    print(f"  {'ยังไม่เปิดขาย':<20} {sum(1 for r in rows if not r['publish']):>8}")
    if no_image:
        # ใบพวกนี้ publish ไม่ได้ตาม BR-06 (ADR-0015 D4 ด่านที่ 2) — บอกตั้งแต่ตอนนี้
        # ดีกว่าให้คนกรอก publish=Y แล้วโดนปฏิเสธทั้งไฟล์ตอน apply
        print(
            f"\n  🔴 ไม่มีรูป public ให้เปิดดู {no_image} ใบ — ใบพวกนี้ publish ไม่ได้ "
            "(BR-06) และตรวจสภาพจากใบงานนี้ไม่ได้ด้วย"
        )
    print("\nขั้นต่อไป: เปิดรูปดูแล้วกรอกเอง — publish=Y ได้เฉพาะใบที่มีเกรดและมีรูป")
    print("จากนั้น ./venv/bin/python scripts/seed/manual_entry.py  (dry-run ก่อนเสมอ)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
