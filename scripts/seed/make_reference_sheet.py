"""สร้าง **ใบงาน** ให้คนเปิดเว็บอ้างอิงแล้วแปะลิงก์ — ADR-0014 Amendment 3 (INF-13)

    ./venv/bin/python scripts/seed/make_reference_sheet.py
    ./venv/bin/python scripts/seed/make_reference_sheet.py --all --out /path/to/sheet.csv

อ่าน `posters` + `poster_images` จาก **dev DB บนเครื่องนี้** อย่างเดียว ไม่เขียนอะไรเลย
— ทรงเดียวกับ `make_manual_sheet.py` ของ ADR-0015 ทุกประการ

🔴 **สคริปต์นี้ไม่ใช่ตัวตรวจ และห้ามทำให้เป็น** — `reference_url` กับ `reference_note`
ถูกเขียนเป็นค่าว่าง**เสมอ** ไม่มี flag ไหนเติมค่าให้ได้ · ถ้าเครื่องกรอกสองคอลัมน์นี้
ก็คือเครื่องตัดสินแทนคนว่าเจอแหล่งอ้างอิงหรือไม่ ซึ่ง ADR-0014 D7 ห้ามไว้ตลอดกาล
(หลักและรูปแบบเดียวกับ `approved`/`corrected_text` ของ `make_review_sheet.py`) ·
มีเทสระดับ AST ล็อกไว้ตาม `screens.yaml` INF-13 **AC-7**

🔴 **ไม่มีคอลัมน์ `verification_status` ในใบงาน** — เป็นค่าที่ `reference_entry.py`
derive เอง (ADR-0014 D22) · ช่องให้กรอกเองจะกลายเป็นแหล่งความจริงที่สองทันที

## คอลัมน์

    poster_uuid · title · image_url · previous_note   ← เครื่องเติม
    reference_url · reference_note                     ← คนกรอก

`previous_note` = ค่าคอลัมน์ `note` ของ `manual-entry.csv` (ใบงานของเส้นที่ 3) จับคู่ด้วย
`poster_uuid` — คนส่วนใหญ่จดลิงก์ไว้ในช่องนั้นตอนกรอกเกรด ยกมาวางบนแถวเดียวกันเพื่อให้
ก๊อปในสเปรดชีตได้ ไม่ต้องเปิดเว็บซ้ำ 108 ครั้ง (ADR-0014 **D28**)

🔴 **ยกข้อความมาดิบ ๆ ห้ามแยกว่าอันไหนเป็น URL อันไหนเป็นเหตุผล** — เหตุผลเต็มอยู่ที่
ADR-0014 D28 ‹ทางที่ปฏิเสธ› · และ **`reference_entry.py` ไม่อ่านคอลัมน์นี้เลย** (มีเทสล็อก)
· ไฟล์ `manual-entry.csv` อยู่ใน `.gitignore` จึง **อาจไม่มีบนเครื่องที่ clone ใหม่** →
ช่องนี้ว่างทั้งใบงานพร้อมคำเตือน ไม่ใช่สคริปต์ล้ม

`image_url` ประกอบจาก `poster_images.storage_key` ผ่าน `build_media_url()` เท่านั้น
(ADR-0006) และเอาเฉพาะ key ที่อยู่ใต้ `posters/public/` (ADR-0006 D5 · ADR-0007)
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
from scripts.seed.manual_entry import DEFAULT_MANUAL_CSV  # noqa: E402
from scripts.seed.reference_entry import (  # noqa: E402
    DEFAULT_REFERENCE_CSV,
    NULL_ONLY_FIELDS,
    REFERENCE_SHEET_COLUMNS,
)

# คอลัมน์ของ `manual-entry.csv` ที่ใช้เป็นที่มาของ `previous_note`
PREVIOUS_NOTE_COLUMN = "note"


def load_previous_notes(path: Path) -> tuple[dict[str, str], str | None]:
    """อ่านคอลัมน์ `note` ของใบงานเส้นที่ 3 → {poster_uuid: note} + เหตุผลถ้าอ่านไม่ได้

    คืน `({}, "เหตุผล")` แทนการ raise — ไฟล์นี้อยู่ใน `.gitignore` การไม่มีจึงเป็น
    สถานะปกติ ไม่ใช่ความผิดพลาด · ใบงานยังสร้างได้ครบทุกแถว แค่ช่องช่วยจำว่างเปล่า

    🔴 **ยกข้อความมาทั้งก้อน** ไม่แยก ไม่ตัด ไม่เดาว่าท่อนไหนคือ URL (ADR-0014 D28)
    """
    if not path.is_file():
        return {}, f"ไม่พบ {path.name} — ช่อง previous_note จะว่างทั้งใบงาน"
    with path.open(newline="", encoding="utf-8-sig") as fh:
        reader = csv.DictReader(fh)
        fields = reader.fieldnames or []
        if "poster_uuid" not in fields or PREVIOUS_NOTE_COLUMN not in fields:
            return {}, (
                f"{path.name} ไม่มีคอลัมน์ poster_uuid/{PREVIOUS_NOTE_COLUMN} — "
                "ช่อง previous_note จะว่างทั้งใบงาน"
            )
        notes: dict[str, str] = {}
        for row in reader:
            key = (row.get("poster_uuid") or "").strip()
            note = (row.get(PREVIOUS_NOTE_COLUMN) or "").strip()
            if key and note:
                notes[key] = note
    return notes, None


def build_sheet_rows(
    posters: list[dict[str, Any]],
    image_urls: dict[Any, str],
    previous_notes: dict[str, str],
    *,
    include_complete: bool,
) -> list[dict[str, str]]:
    """แปลงแถวจาก DB → แถวใบงาน (pure — ไม่แตะไฟล์ ไม่ query)

    `posters` = dict ต่อใบ มีคีย์ `id` · `title` + 3 คอลัมน์ของ `NULL_ONLY_FIELDS`

    "ยังไม่ได้ทำ" = ทั้งสามคอลัมน์เป็น `NULL` — ใบที่มีค่าแล้วแม้ช่องเดียวถูก
    `reference_entry.py` ข้ามทั้งใบอยู่แล้ว (ADR-0014 D29 · ไม่มีโหมดเขียนทับ)
    การใส่มาในใบงานจึงเป็นการเชิญให้คนกรอกสิ่งที่ไม่มีวันถูกเขียน

    `reference_url`/`reference_note` เป็นค่าว่างเสมอ ดู docstring ของโมดูล
    """
    rows: list[dict[str, str]] = []
    for poster in posters:
        untouched = all(poster.get(name) is None for name in NULL_ONLY_FIELDS)
        if not include_complete and not untouched:
            continue
        rows.append(
            {
                "poster_uuid": str(poster["id"]),
                "title": poster.get("title") or "",
                "image_url": image_urls.get(poster["id"], ""),
                "previous_note": previous_notes.get(str(poster["id"]), ""),
                "reference_url": "",
                "reference_note": "",
            }
        )
    # ใบที่มีบันทึกเก่าให้ก๊อปขึ้นก่อน — เป็นแถวที่คนทำงานได้เร็วที่สุด
    # (หลักเดียวกับ STATUS_ORDER ของ make_review_sheet.py และ sort_key ของ
    # make_manual_sheet.py: เอาแถวที่คนลงมือได้ทันทีขึ้นบน)
    rows.sort(key=lambda r: (not r["previous_note"], r["title"]))
    return rows


async def load_from_db() -> tuple[list[dict[str, Any]], dict[Any, str]]:
    """อ่าน `posters` + รูปตัวแทนของแต่ละใบ — read-only ล้วน ๆ."""
    from sqlalchemy import select

    from app.core.database import async_session_maker
    from app.core.media import build_media_url, is_public_storage_key
    from app.models.poster import Poster, PosterImage

    columns = [Poster.id, Poster.title] + [
        getattr(Poster, name) for name in NULL_ONLY_FIELDS
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
        default=DEFAULT_REFERENCE_CSV,
        help=f"ใบงานที่จะสร้าง (default: {DEFAULT_REFERENCE_CSV.name})",
    )
    parser.add_argument(
        "--previous",
        type=Path,
        default=DEFAULT_MANUAL_CSV,
        help=(
            "ใบงานของเส้นที่ 3 ที่จะยกคอลัมน์ note มาเป็น previous_note "
            f"(อ่านอย่างเดียว · default: {DEFAULT_MANUAL_CSV.name} · ไม่มีก็รันได้)"
        ),
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="ใส่ทุกใบ ไม่ใช่เฉพาะใบที่ยังไม่มีใครเปิดหาแหล่งอ้างอิง",
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

    previous_notes, problem = load_previous_notes(args.previous)

    import asyncio

    posters, image_urls = asyncio.run(load_from_db())
    rows = build_sheet_rows(
        posters, image_urls, previous_notes, include_complete=args.all
    )

    with args.out.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(REFERENCE_SHEET_COLUMNS))
        writer.writeheader()
        writer.writerows(rows)

    with_note = sum(1 for r in rows if r["previous_note"])
    no_image = sum(1 for r in rows if not r["image_url"])
    print(f"อ่านจาก {target_label} — {len(posters)} ใบ")
    print(f"เขียน {args.out} — {len(rows)} แถว\n")
    if problem:
        print(f"  ⚠️  {problem}")
    else:
        print(f"  มีบันทึกเก่าให้ก๊อป (previous_note) {with_note} / {len(rows)} แถว")
    if no_image:
        print(f"  ⚠️  ไม่มีรูป public ให้เปิดดู {no_image} ใบ")
    print("\nขั้นต่อไป: เปิดเว็บอ้างอิงหาแบบของใบนั้น แล้วกรอก **ช่องเดียว** ต่อแถว")
    print("  เจอ    → reference_url  (URL ล้วน ๆ ไม่มีคำอธิบายปน)")
    print("  ไม่เจอ → reference_note (เหตุผลที่หาไม่เจอ)")
    print("  ยังไม่ได้เปิดหา → เว้นว่างทั้งสองช่อง")
    print(
        "\nจากนั้น ./venv/bin/python scripts/seed/reference_entry.py  (dry-run ก่อนเสมอ)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
