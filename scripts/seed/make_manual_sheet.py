"""สร้าง **ใบงาน** ให้คนกรอกฟิลด์ที่เครื่องเดาแทนไม่ได้ — ADR-0015 (INF-11 · INF-49)

    ./venv/bin/python scripts/seed/make_manual_sheet.py
    ./venv/bin/python scripts/seed/make_manual_sheet.py --all --out /path/to/sheet.csv
    ./venv/bin/python scripts/seed/make_manual_sheet.py --target sit --all --out /tmp/manual-entry-v3.csv

อ่าน `posters` + `poster_images` จาก **dev หรือ SIT DB** อย่างเดียว ไม่เขียนอะไรเลย —
`--target` ผ่านด่านเดียวกับ 7 เส้นอื่น (`assert_target()` ของ `manual_entry.py`) แต่
**ไม่เปิด `production`** ในเครื่องมือนี้ — เหตุผลเต็มอยู่ที่ `INF-49` AC-7(ค) และ
ADR-0015 A3-D1 ข้อ 3 (ไม่ก๊อปมาซ้ำที่นี่) — `--target sit` ต้องรัน**ข้างในคอนเทนเนอร์
`posternung-sit-app`** เท่านั้น (mount `scripts/` เป็น `:ro` — `--out` ต้องชี้ `/tmp`
แล้ว `docker cp` ออกมา ดู `scripts/seed/README.md` §`make_manual_sheet.py --target sit`)
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
    _url_label,
)
from scripts.seed.manual_entry import (  # noqa: E402
    ALLOWED_FIELDS,
    DEFAULT_MANUAL_CSV,
    MANUAL_SHEET_COLUMNS,
    assert_target,
    render_value,
)

# 🔴 M-1 (code-critic รอบ 1 · INF-49) — ต้องตรงกับ marker ที่ `_url_label()` คืนตอน
# แยกส่วน url ไม่ได้ (`apply_suggestions.py` — ไม่แตะไฟล์นั้น เพราะเป็น `BL-167`)
# เทส `test_unparseable_url_label_marker_matches_the_real_function` ล็อกไว้ว่าถ้า
# `_url_label()` เปลี่ยนคำนี้แล้วไม่มาแก้ค่านี้ด้วย เทสต้องแดงทันที ไม่ใช่ค่อยรู้ตอน
# ความลับหลุดออกไปเงียบ ๆ
_UNPARSEABLE_URL_LABEL = "<url ที่แยกส่วนไม่ได้>"


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
            # ADR-0019 A-D2 ข้อ 1 — เขียนเป็นค่าว่างเสมอเหมือน `publish` เครื่องนับ
            # ของแทนคนไม่ได้ ช่องนี้เป็น input ของประตู publish ไม่ใช่ค่าที่เดาได้
            "count_actual": "",
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
    parser.add_argument(
        "--target",
        choices=("dev", "sit"),
        default="dev",
        help="ปลายทาง — ผ่านด่านเดียวกับ 7 เส้นอื่น (assert_target()) · ไม่เปิด "
        "production ในเครื่องมือนี้ (เหตุผล: INF-49 AC-7(ค) · ADR-0015 A3-D1 ข้อ 3) · "
        "--target sit ต้องรันข้างในคอนเทนเนอร์ sit และ DATABASE_URL ต้องตรงกับ "
        ".env.sit เป๊ะ",
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

    # AC-7(ก) — ตรวจว่าเขียนได้ **ก่อนแตะ DB เลย** mount ของ SIT ทำ `scripts/` เป็น
    # `:ro` ทั้งโฟลเดอร์ ⇒ `--out` ที่ชี้ใต้ `/app/scripts` ต้องถูกปฏิเสธที่นี่ ไม่ใช่
    # ไปพังตอนเปิดไฟล์เขียนหลังอ่าน DB มาแล้วทั้งก้อน
    if not os.access(args.out.parent, os.W_OK):
        print(
            f"เขียน {args.out} ไม่ได้ (โฟลเดอร์ไม่มีอยู่จริงหรือเขียนไม่ได้) — ถ้ารันใน "
            "คอนเทนเนอร์ sit ให้ --out ชี้ไปที่ /tmp แล้ว docker cp ออกมาแทน "
            "(scripts/ ถูก mount แบบ read-only ในคอนเทนเนอร์ sit)",
            file=sys.stderr,
        )
        return 1

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
        # 🔴 ใช้เพื่อ**ยืนยัน**เท่านั้น — ไม่ใช้ค่าที่คืนมาเป็นป้ายที่พิมพ์ออกจอ ค่าคืนของ
        # `assert_target()`/`assert_target_database()` ไม่ผ่านตัวกรอง `@:/` ของ
        # `_url_label()` ⇒ รหัสผ่านที่มี `/` ไม่ encode หลุดออกไปได้ (ดู known risk ของ
        # INF-49 GATE 1) — ป้ายที่พิมพ์จริงคำนวณจาก `_url_label(database_url)` ข้างล่าง
        assert_target(database_url, args.target)
    except PrecheckError as exc:
        # 🔴 M-1 (code-critic รอบ 1 · INF-49) — ข้อความของ `assert_target_database()`
        # ชั้น ① (`apply_suggestions.py:181-201` — ไม่แตะ เพราะเป็น `BL-167`) ฝัง
        # `host`/`db_name` ดิบไว้ในบางสาขา (เช่นด่าน `PRODUCTION_DB_HINTS`) โดยไม่ผ่าน
        # ตัวกรอง `@:/` ของ `_url_label()` เลย — `DATABASE_URL` ที่มีรหัสผ่านซึ่งมี `/`
        # ไม่ percent-encode ทำให้ username/เศษรหัสผ่านไหลไปอยู่ใน `host`/`db_name`
        # แล้วหลุดออกทาง `{exc}` ตรง ๆ (ยืนยันจริง: เศษรหัสผ่านที่บังเอิญมีตัวอักษร
        # "uat" ต่อกันจะโดนด่าน hint ชื่อ database ชี้เป็น "มีคำว่า 'uat'" พร้อมพิมพ์
        # ค่าดิบทั้งก้อนออกมา) ⇒ ถ้า url แยกส่วนไม่ได้ (สัญญาณเดียวกับที่ `_url_label()`
        # ใช้ตัดสินใจปิดบัง) พิมพ์ข้อความทั่วไปแทน **ไม่พิมพ์ `{exc}` เลย**
        if _url_label(database_url) == _UNPARSEABLE_URL_LABEL:
            print(
                "precheck ไม่ผ่าน: DATABASE_URL แยกส่วนไม่ได้ (อาจมีอักขระพิเศษในรหัสผ่าน "
                "ที่ไม่ได้ percent-encode) — ตรวจ .env ของ target",
                file=sys.stderr,
            )
            return 1
        print(
            f"precheck ไม่ผ่าน: {exc}\n"
            "(--target sit ต้องรันข้างในคอนเทนเนอร์ posternung-sit-app และ DATABASE_URL "
            "ต้องตรงกับ .env.sit เป๊ะ — ADR-0015 D8)",
            file=sys.stderr,
        )
        return 1

    label = f"{_url_label(database_url)}  [--target {args.target}]"

    hint = ""
    if args.target == "sit":
        hint = (
            "\n--target sit ต้องรัน **ข้างในคอนเทนเนอร์ posternung-sit-app** "
            "ไม่ใช่จากเครื่องนี้:\n"
            "  docker exec posternung-sit-app python scripts/seed/make_manual_sheet.py "
            "--target sit --all --out /tmp/manual-entry-v3.csv\n"
            "แล้ว docker cp ออกมา (scripts/ mount แบบ read-only ใต้ /app/scripts)"
        )

    import asyncio

    from asyncpg.exceptions import PostgresError
    from sqlalchemy.exc import SQLAlchemyError

    try:
        posters, image_urls = asyncio.run(load_from_db())
    except OSError as exc:
        # ต่อ DB ไม่ติดระดับเครือข่าย (DNS resolve ไม่ได้ · connection refused) — เคสที่
        # เจอบ่อยที่สุดคือสั่ง --target sit จากเครื่อง Mac ทั้งที่ .env.sit ชี้ hostname
        # `db` ซึ่ง resolve ได้เฉพาะใน docker network (precheck ผ่านถูกต้องแล้วเพราะ url
        # ตรงกับไฟล์จริง — ที่พังคือ network) · ข้อความของชั้นนี้เป็นของ socket/DNS
        # ไม่ใช่ของ postgres driver จึงไม่มี username/รหัสผ่านปนมาด้วย ปลอดภัยพอจะพิมพ์
        # {exc} ตรง ๆ — ปล่อยเป็น traceback ดิบจะอ่านไม่ออกว่าต้องทำอะไรต่อ
        print(
            f"ต่อ database ไม่ได้ (target={args.target}): {exc}{hint}", file=sys.stderr
        )
        return 1
    except (PostgresError, SQLAlchemyError) as exc:
        # 🔴 Low ข้อ 2 (code-critic รอบ 1 · INF-49) — ยืนยันจริงบนสแตกนี้ (asyncpg +
        # SQLAlchemy async engine ตัวเดียวกับ `app.core.database.async_session_maker`)
        # ว่า error ตอน **connect ล้มเหลว** (รหัสผ่านผิด/ชื่อ database ไม่มีจริง) เป็น
        # `asyncpg.exceptions.PostgresError` **ดิบ ไม่ถูก SQLAlchemy wrap** ส่วน error
        # ระดับ statement (เช่น query ผิด) ถูก wrap เป็น `sqlalchemy.exc.*` — ข้อความ
        # ของทั้งสองตระกูลมีโอกาสฝัง username/connection string ตรง ๆ (เช่น
        # `password authentication failed for user "…"`) พิมพ์แค่**ชื่อ exception**
        # ไม่พิมพ์ `{exc}` เลย
        print(
            f"ต่อ database ไม่ได้ (target={args.target}): {type(exc).__name__}{hint}",
            file=sys.stderr,
        )
        return 1

    rows = build_sheet_rows(posters, image_urls, include_complete=args.all)

    with args.out.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(MANUAL_SHEET_COLUMNS))
        writer.writeheader()
        writer.writerows(rows)

    no_image = sum(1 for r in rows if not r["image_url"])
    print(f"อ่านจาก {label} — {len(posters)} ใบ")
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
