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

## สองด่านเพิ่มเติมที่ใช้เสมอ (แม้กับ `--all`) — แก้ 2026-08-12 (code-critic รอบ 4)

1. **ต้องมีเกรดอยู่แล้ว (`condition_grade is not None`)** — กันกรอบไฟของ BL-82
   (`quantity = 11` · ไม่มีเกรด · ยังไม่ publish · `is_unique = false`) ที่
   **ADR-0019 D4 ข้อ 2 สั่งห้ามแตกเป็น 11 แถว** เข้าใบงานผ่านทาง `--all` (ซึ่งข้าม
   ตัวกรอง published อยู่แล้ว) — โปสเตอร์จริงทุกใบที่ published ต้องมีเกรดอยู่แล้ว
   (CHECK `ck_posters_published_requires_condition_grade` บังคับไว้) และใบที่ยัง
   ไม่ publish แต่เตรียมแตกล่วงหน้าก็ให้เกรดผ่านเส้นที่ 3 ได้ก่อน publish อยู่แล้ว
   (`condition_grade` ไม่ผูกกับ `publish=Y`) — กรอบไฟไม่มีทางผ่านด่านนี้ได้เลยเพราะ
   มันไม่ใช่โปสเตอร์ ไม่มีวันถูกให้เกรด
2. **ต้องมีผลนับใบจริงแล้ว (`count_actual` ไม่ว่างใน `manual-entry.csv`)** —
   ADR-0024 INF-22 AC-1: *"ห้ามรันก่อนมีผลการนับ"* — แถวที่ยังไม่มีผลนับถูกข้าม
   พร้อมรายงาน ไม่ใช่เดาจาก `posters-seed-v2.csv` (ดู `load_counted_parent_ids()`)
   🔴 วันนี้ `count_actual` ว่าง **117/117** ⇒ ใบงานที่สร้างวันนี้จะ**ว่างเปล่าโดย
   ตั้งใจ** จนกว่าเจ้าของจะเริ่มนับ — ห้ามผ่อนด่านนี้เพื่อให้ใบงานไม่ว่าง
"""

from __future__ import annotations

import argparse
import csv
import os
import sys
import uuid
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

# 🔴 import ตัวอ่านใบงานเดียวกับเส้นที่ 3 — ไม่สร้าง CSV reader ของตัวเอง (BL-101/
# BL-103) `read_manual_sheet()` แค่ parse โครงสร้าง ไม่ validate ค่าแต่ละฟิลด์ ซึ่งพอดี
# กับที่เครื่องมือนี้ต้องการ: รู้แค่ "นับแล้วหรือยัง" ไม่ใช่ตรวจทั้งไฟล์ของอีกเส้น
from scripts.seed.manual_entry import (  # noqa: E402
    DEFAULT_MANUAL_CSV,
    read_manual_sheet,
)
from scripts.seed.split_entry import (  # noqa: E402
    DEFAULT_SPLIT_CSV,
    HUMAN_COLUMNS,
    SPLIT_SHEET_COLUMNS,
)

# `HUMAN_COLUMNS` = ช่องที่ **คน** กรอก · re-export ตรงจาก `split_entry.py` ซึ่งเป็น
# เจ้าของนิยาม — เทส AST ในไฟล์นี้ใช้เซตนี้ยืนยันว่า generator เขียนทุกช่องเป็นค่าว่าง
# คงที่ ไม่ใช่นิพจน์ · ‹แก้ 2026-08-15 · INF-22 G5› เดิมบรรทัดนี้ **พิมพ์รายชื่อซ้ำ**
# ทั้งที่คอมเมนต์ข้าง ๆ อ้างว่า "ประกอบจากค่าคงที่ของ split_entry.py ไม่พิมพ์รายชื่อซ้ำ"
# — ตอนนี้อ้างแล้วจริง · **ห้ามประกาศทูเพิลใหม่ที่นี่** มีเทส AST ล็อกไว้
__all__ = ["HUMAN_COLUMNS", "build_sheet_rows", "load_counted_parent_ids", "main"]


def build_sheet_rows(
    posters: list[dict[str, Any]],
    image_urls: dict[Any, str],
    *,
    include_all: bool,
    counted_parent_ids: set[Any] | None = None,
) -> list[dict[str, str]]:
    """แปลงแถวพ่อจาก DB → แถวใบงาน (pure — ไม่แตะไฟล์ ไม่ query)

    `posters` = dict ต่อใบ มีคีย์ `id` · `title` · `is_unique` · `published_at` ·
    `condition_grade`

    สามช่องที่คนกรอกเป็นค่าว่างเสมอ ดู docstring ของโมดูล

    🔴 **สองด่านท้ายนี้ทำงานเสมอ ไม่ว่า `include_all` จะเป็นอะไร** — ต่างจากตัวกรอง
    `is_unique`/`published_at` ที่ `--all` ตั้งใจให้ข้ามได้ (ดู §ใบไหนเข้าใบงาน):
    - `condition_grade is None` → ข้าม (กันกรอบไฟ BL-82 — ADR-0019 D4 ข้อ 2)
    - `counted_parent_ids is not None` และใบนั้นไม่อยู่ในเซต → ข้าม (ADR-0024 INF-22
      AC-1 — ห้ามรันก่อนมีผลการนับ) · `None` (ไม่ส่งพารามิเตอร์) = ไม่กรองข้อนี้
      (ใช้ในเทสที่ไม่สนเรื่องนี้ — `main()` จริงส่งเซตเสมอ)
    """
    rows: list[dict[str, str]] = []
    for poster in posters:
        if not include_all:
            if poster.get("is_unique") is not False:
                continue
            if poster.get("published_at") is None:
                continue
        if poster.get("condition_grade") is None:
            continue
        if counted_parent_ids is not None and poster["id"] not in counted_parent_ids:
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


def load_counted_parent_ids(path: Path) -> set[uuid.UUID]:
    """ใบไหน "นับแล้ว" ตาม `manual-entry.csv` — ADR-0024 INF-22 AC-1

    เกตนี้ตรวจแค่ **"count_actual ไม่ว่าง"** ไม่ตรวจว่าเป็นตัวเลขถูกต้องหรือค่าเท่าไหร่
    — การตรวจรูปแบบเต็มเป็นหน้าที่ของเส้นที่ 3 (`manual_entry.parse_manual_rows()`
    ซึ่งมีด่านของตัวเองอยู่แล้วตอน publish) เครื่องมือนี้แค่ต้องรู้ว่า "มีคนนับแล้ว
    หรือยัง" ก่อนจะเสนอใบพ่อให้แตก — แถวที่ `poster_uuid`/`count_actual` พังรูปแบบ
    ถูกข้ามเงียบ ๆ ที่นี่โดยตั้งใจ เพราะการฟ้องรูปแบบเป็นหน้าที่ของเส้นที่ 3

    raise `PrecheckError` ถ้าไม่พบไฟล์เลย — ไม่มีไฟล์แปลว่า **ไม่มีทางรู้ว่าใบไหน
    นับแล้ว** ซึ่งเข้าเงื่อนไข "ห้ามรัน" เดียวกับที่ทุกแถวว่าง (fail-closed แบบเดียว
    กับที่ `read_manual_sheet()` ทำอยู่แล้วเมื่อไม่พบไฟล์)
    """
    counted: set[uuid.UUID] = set()
    for raw in read_manual_sheet(path):
        if not raw.get("count_actual"):
            continue
        try:
            counted.add(uuid.UUID(raw["poster_uuid"]))
        except ValueError:
            continue
    return counted


async def load_from_db() -> tuple[list[dict[str, Any]], dict[Any, str]]:
    """อ่าน `posters` + รูปตัวแทนของแต่ละใบพ่อ — read-only ล้วน ๆ."""
    from sqlalchemy import select

    from app.core.database import async_session_maker
    from app.core.media import build_media_url, is_public_storage_key
    from app.models.poster import Poster, PosterImage

    async with async_session_maker() as session:
        result = await session.execute(
            select(
                Poster.id,
                Poster.title,
                Poster.is_unique,
                Poster.published_at,
                Poster.condition_grade,
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
        help="ใส่ทุกใบ ไม่ใช่เฉพาะใบที่ is_unique=false และ published (ดู §ใบไหนเข้าใบงาน) "
        "— 🔴 ไม่ข้ามด่านต้องมีเกรดและด่านต้องมีผลนับ (§สองด่านเพิ่มเติม) กรอบไฟของ "
        "BL-82 ยังเข้าไม่ได้แม้ใส่ flag นี้",
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

    # ADR-0024 INF-22 AC-1 — ต้องรู้ว่าใบไหน "นับแล้ว" ก่อนอ่าน DB ด้วยซ้ำ (fail-closed
    # ก่อนแตะ DB เลย ถ้า manual-entry.csv หาไม่เจอ — ทรงเดียวกับ precheck อื่น ๆ ในไฟล์นี้)
    try:
        counted_parent_ids = load_counted_parent_ids(DEFAULT_MANUAL_CSV)
    except PrecheckError as exc:
        print(f"precheck ไม่ผ่าน: {exc}", file=sys.stderr)
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
    rows = build_sheet_rows(
        posters, image_urls, include_all=args.all, counted_parent_ids=counted_parent_ids
    )

    with args.out.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(SPLIT_SHEET_COLUMNS))
        writer.writeheader()
        writer.writerows(rows)

    # แถวที่ผ่านตัวกรอง is_unique/published (หรือ --all) แล้ว แต่ยังไม่มีเกรด หรือ
    # ยังไม่มีผลนับ — แยกสองสาเหตุเพื่อรายงานให้คนอ่านออกว่าต้องทำอะไรต่อ
    status_eligible = [
        p
        for p in posters
        if args.all
        or (p.get("is_unique") is False and p.get("published_at") is not None)
    ]
    ungraded = [p for p in status_eligible if p.get("condition_grade") is None]
    graded = [p for p in status_eligible if p.get("condition_grade") is not None]
    uncounted = [p for p in graded if p["id"] not in counted_parent_ids]

    no_image = sum(1 for r in rows if not r["parent_image_url"])
    print(f"อ่านจาก {target_label} — {len(posters)} ใบ")
    print(f"เขียน {args.out} — {len(rows)} แถว\n")
    if no_image:
        print(
            f"  ⚠️  ไม่มีรูป public ให้เปิดดู {no_image} ใบ — ตรวจสภาพจากใบงานนี้ไม่ได้"
        )
    if ungraded:
        print(
            f"  ⚠️  ข้าม {len(ungraded)} ใบ — ยังไม่มีเกรด (condition_grade ว่าง) "
            "ไม่เข้าใบงาน (ADR-0019 D4 ข้อ 2 — กันกรอบไฟของ BL-82 หลุดเข้ามาผ่าน --all "
            "ด้วยกฎเดียวกัน)"
        )
        for p in sorted(ungraded, key=lambda p: p.get("title") or ""):
            print(f"      {p['id']}  {p.get('title') or ''}")
    if uncounted:
        print(
            f"  ⚠️  ข้าม {len(uncounted)} ใบ — ยังไม่มีผลนับ (count_actual ว่างใน "
            "manual-entry.csv หรือไม่มีแถวของใบนี้เลย) ไม่เข้าใบงาน (ADR-0024 INF-22 "
            "AC-1 — ห้ามรันก่อนมีผลการนับ):"
        )
        for p in sorted(uncounted, key=lambda p: p.get("title") or ""):
            print(f"      {p['id']}  {p.get('title') or ''}")
    if not rows:
        print(
            "\n🔴 ใบงานว่างเปล่า — ไม่มีใบที่ผ่านครบทุกเงื่อนไข: (1) is_unique=false "
            "และ published (หรือ --all) (2) มีเกรดแล้ว (3) มีผลนับแล้ว\n"
            "นี่คือพฤติกรรมที่ถูกต้องถ้ายังไม่มีใครนับใบจริงเลย (ADR-0024 INF-22 AC-1) "
            "— ห้ามผ่อนด่านนี้เพื่อให้ใบงานไม่ว่าง\n"
            "ขั้นต่อไป: เจ้าของนับใบจริงแล้วกรอก count_actual ใน manual-entry.csv "
            "(เส้นที่ 3 — สร้างด้วย make_manual_sheet.py ถ้ายังไม่มี) ก่อน แล้วรัน "
            "make_split_sheet.py ใหม่"
        )
        return 0
    print(
        "\nขั้นต่อไป: หยิบใบจริงขึ้นมา แล้วกรอก **condition_grade · price · reason** "
        "ของชิ้นที่จะแตกออกมา ครบทั้งสามช่องพร้อมกัน (ไม่มีแนวคิด 'เติมทีหลัง')"
    )
    print("\nจากนั้น ./venv/bin/python scripts/seed/split_entry.py  (dry-run ก่อนเสมอ)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
