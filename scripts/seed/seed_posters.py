"""Seed `posters` + `poster_images` ลง **dev database เท่านั้น** จาก CSV ชุด v2.

อ่าน 3 ไฟล์จากโฟลเดอร์เดียวกับสคริปต์นี้:
  · posters-seed-v2.csv    — 1 แถว = 1 โปสเตอร์
  · images-manifest-v2.csv — รูปทั้งหมด (เลือกเฉพาะ is_gallery=1, duplicate!=1)
  · migration-result.csv   — ผลอัปโหลดขึ้น R2 (join ด้วย object_key เอา width/height)

หลักการที่ยึด:
  · idempotent — ทุก INSERT เป็น ON CONFLICT DO NOTHING รันซ้ำได้ไม่พัง
  · dry-run เป็น default — ต้องใส่ `--commit` ถึงจะเขียนจริง
  · precheck ก่อนเขียนเสมอ ผิดข้อไหน = หยุดทั้งชุด ไม่ insert บางส่วน
  · ห้ามเดา `condition_grade` (ADR-0003) — default ลง NULL เสมอ · เปิด
    `--derive-condition-from-price` ได้เฉพาะเมื่อรู้ตัวว่าต้องการค่า placeholder
    สำหรับ dev (ดู derive_condition())
  · dev เท่านั้น — guard ปฏิเสธ DATABASE_URL ที่ไม่ได้ชี้ localhost (ดู _assert_dev_database)

คอลัมน์ใน CSV ที่ **ยังไม่มีที่เก็บใน schema** (ดู REPORT ท้ายการรัน): year, quantity,
edition_key/tiktok_product_id — สคริปต์ข้ามให้ ไม่สร้างคอลัมน์ใหม่เอง

    python3 scripts/seed/seed_posters.py            # dry-run (default)
    python3 scripts/seed/seed_posters.py --commit --status available
"""

from __future__ import annotations

import argparse
import csv
import os
import sys
from collections import Counter
from decimal import Decimal, InvalidOperation
from pathlib import Path
from urllib.parse import unquote, urlsplit

SEED_DIR = Path(__file__).resolve().parent
REPO_ROOT = SEED_DIR.parents[1]

POSTERS_CSV = SEED_DIR / "posters-seed-v2.csv"
MANIFEST_CSV = SEED_DIR / "images-manifest-v2.csv"
RESULT_CSV = SEED_DIR / "migration-result.csv"

# object key ต้องอยู่ใต้ prefix นี้เท่านั้น ไม่งั้น build_media_url() จะ raise
# UnsafeStorageKeyError ตอน serialize response (ADR-0006 D2/D5) — เจอตอน seed ดีกว่าเจอ 500
PUBLIC_PREFIX = "posters/public/"

# dev guard: DATABASE_URL ต้องชี้เครื่องตัวเองเท่านั้น
LOCAL_HOSTS = {"", "localhost", "127.0.0.1", "::1"}
# ชื่อ database ที่สื่อว่าเป็น env จริง — ปฏิเสธทันทีแม้ host จะเป็น localhost
# (เช่น เผลอเปิด ssh tunnel ไป prod ไว้)
NON_DEV_DB_HINTS = ("sit", "uat", "prod", "stage")
# ไฟล์ env ของ env จริง — ถ้า DATABASE_URL ตรงกับไฟล์ไหน = ไม่ใช่ dev
NON_DEV_ENV_FILES = (".env.sit", ".env.uat", ".env.production")


class PrecheckError(Exception):
    """precheck ไม่ผ่าน — รายละเอียดอยู่ใน args[0] (หลายบรรทัดได้)."""


# --------------------------------------------------------------------------
# env + dev guard (ทำก่อน import app.* เพราะ Settings() ต้องการ env ครบตอน import)
# --------------------------------------------------------------------------


def _parse_env_file(path: Path) -> dict[str, str]:
    """อ่าน KEY=VALUE แบบง่ายจากไฟล์ .env (ไม่รองรับ multi-line / export)."""
    values: dict[str, str] = {}
    if not path.is_file():
        return values
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, raw = line.partition("=")
        values[key.strip()] = raw.strip().strip('"').strip("'")
    return values


def _load_dev_env() -> None:
    """เติม env จาก REPO_ROOT/.env ให้ `Settings()` สร้างได้ไม่ว่าจะรันจาก cwd ไหน

    env var ที่ตั้งมาจากข้างนอกชนะไฟล์ .env เสมอ (12-Factor — ดู
    .claude/rules/environments.md)
    """
    for key, value in _parse_env_file(REPO_ROOT / ".env").items():
        os.environ.setdefault(key, value)


def _assert_dev_database(database_url: str) -> str:
    """ยืนยันว่า DATABASE_URL ชี้ dev บนเครื่องตัวเอง — ไม่ผ่าน = จบทันที

    ไม่มี flag ให้ override โดยตั้งใจ: งาน seed ชุดนี้ทำกับ dev อย่างเดียว การ
    seed ทับ SIT/production ต้องเป็นการตัดสินใจแยกที่มีขั้นตอนของมันเอง
    """
    parts = urlsplit(database_url)
    host = (parts.hostname or "").lower()
    db_name = unquote(parts.path).lstrip("/").lower()

    if host not in LOCAL_HOSTS:
        raise PrecheckError(
            f"DATABASE_URL ชี้ host {host!r} ซึ่งไม่ใช่เครื่องนี้ — สคริปต์นี้ทำงานกับ dev "
            "เท่านั้น (localhost/127.0.0.1)"
        )
    hit = next((h for h in NON_DEV_DB_HINTS if h in db_name), None)
    if hit:
        raise PrecheckError(
            f"ชื่อ database {db_name!r} มีคำว่า {hit!r} — ดูเหมือน env จริง ไม่ใช่ dev"
        )
    for env_file in NON_DEV_ENV_FILES:
        other = _parse_env_file(REPO_ROOT / env_file).get("DATABASE_URL")
        if other and other == database_url:
            raise PrecheckError(
                f"DATABASE_URL ตรงกับค่าใน {env_file} — นั่นคือ env จริง ไม่ใช่ dev"
            )
    return f"{host or 'localhost'}/{db_name}"


# --------------------------------------------------------------------------
# CSV loading
# --------------------------------------------------------------------------


def _read_csv(path: Path) -> list[dict[str, str]]:
    if not path.is_file():
        raise PrecheckError(f"ไม่พบไฟล์ {path}")
    # utf-8-sig — ไฟล์ชุดนี้มี BOM นำหน้า header คอลัมน์แรก
    with path.open(newline="", encoding="utf-8-sig") as fh:
        return [
            {k: (v or "").strip() for k, v in row.items()} for row in csv.DictReader(fh)
        ]


def _int_or_none(value: str) -> int | None:
    return int(value) if value else None


# --------------------------------------------------------------------------
# build rows
# --------------------------------------------------------------------------


def derive_condition(price: Decimal, threshold: Decimal) -> str:
    """เกรด placeholder จากราคา — **ไม่ใช่สภาพจริงของโปสเตอร์**

    🔴 อ่านก่อนใช้: ราคา *ไม่ได้* บอกสภาพ ค่าที่ได้จากฟังก์ชันนี้เป็นข้อมูล dev
    สำหรับให้ UI ที่ผูกกับ BR-05 (ต้องแสดงราคาคู่สภาพเสมอ) มีอะไรแสดงเท่านั้น
    ห้ามใช้กับ SIT/production และห้ามถือเป็นคำรับรองสภาพต่อผู้ซื้อ — ADR-0003
    §Consequence อธิบายไว้ว่าเกรดที่ผิดคือต้นทางของ dispute โดยตรง

    เปิดใช้ได้เฉพาะเมื่อสั่ง --derive-condition-from-price เท่านั้น (default
    ยังเป็น NULL ตามเดิม) และตัว backfill จะแตะเฉพาะแถวที่เกรดเป็น NULL —
    เกรดที่คนใส่มาแล้ว (อนาคต: ร้านค้าปรับเอง) จะไม่ถูกทับ
    """
    return "mint" if price > threshold else "very_good"


def build_poster_rows(
    posters: list[dict[str, str]],
    status: str,
    dedupe: bool,
    grade_threshold: Decimal | None,
) -> tuple[list[dict[str, object]], list[str]]:
    """แปลง posters CSV → ค่าที่ insert ลงตาราง `posters`

    condition_grade ไม่ถูกใส่เลยถ้าไม่ได้สั่ง --derive-condition-from-price —
    ปล่อยเป็น NULL ตาม ADR-0003 (CSV ก็ว่างทั้ง 118 แถว) ห้ามเดาเกรดจาก title/ราคา
    """
    notes: list[str] = []
    seen: dict[str, dict[str, str]] = {}
    rows: list[dict[str, object]] = []

    for row in posters:
        poster_id = row["poster_uuid"]
        if poster_id in seen:
            if not dedupe:
                # กันเงียบ: ON CONFLICT DO NOTHING จะทิ้งแถวหลังโดยไม่บอกใคร
                raise PrecheckError(
                    f"poster_uuid ซ้ำใน {POSTERS_CSV.name}: {poster_id}\n"
                    f"  idx {seen[poster_id]['idx']} ราคา {seen[poster_id]['price_thb']}\n"
                    f"  idx {row['idx']} ราคา {row['price_thb']}\n"
                    "  → แถวหลังจะถูก ON CONFLICT DO NOTHING ทิ้งเงียบๆ ตัดสินก่อนว่าจะเอาแถวไหน\n"
                    "     แก้ CSV แล้วรันใหม่ หรือใส่ --dedupe-poster-id=first ถ้ายอมรับว่าเอาแถวแรก"
                )
            notes.append(
                f"poster_uuid {poster_id} ซ้ำ — ใช้ idx {seen[poster_id]['idx']} "
                f"(ราคา {seen[poster_id]['price_thb']}) ทิ้ง idx {row['idx']} "
                f"(ราคา {row['price_thb']})"
            )
            continue
        seen[poster_id] = row

        try:
            price = Decimal(row["price_thb"])
        except InvalidOperation as exc:
            raise PrecheckError(
                f"ราคาไม่ใช่ตัวเลข ที่ idx {row['idx']}: {row['price_thb']!r}"
            ) from exc
        if price < 0:
            raise PrecheckError(
                f"ราคาติดลบที่ idx {row['idx']} (ck_posters_price_non_negative)"
            )

        values: dict[str, object] = {
            "id": poster_id,
            "title": row["title"],
            "price": price,
            "status": status,
            # CSV ไม่มีคอลัมน์ quantity ใน schema — is_unique คือคอลัมน์เดียวใน
            # ตารางที่สื่อความหมายนั้น และ CSV คำนวณมาให้แล้ว (is_unique = quantity==1)
            "is_unique": row["is_unique"] == "1",
            "size": row["size"] or None,
            "era_decade": _int_or_none(row["era_decade"]),
            "studio": row["studio"] or None,
            "is_authenticated": False,
        }
        if grade_threshold is not None:
            values["condition_grade"] = derive_condition(price, grade_threshold)
        rows.append(values)
    return rows, notes


def build_image_rows(
    manifest: list[dict[str, str]],
    result_by_key: dict[str, dict[str, str]],
    poster_ids: set[str],
) -> list[dict[str, object]]:
    """แปลง manifest (เฉพาะแถวที่คัดแล้ว) → ค่าที่ insert ลงตาราง `poster_images`."""
    rows: list[dict[str, object]] = []
    for row in manifest:
        key = row["object_key"]
        if row["poster_uuid"] not in poster_ids:
            raise PrecheckError(
                f"manifest อ้าง poster_uuid {row['poster_uuid']} ที่ไม่มีใน "
                f"{POSTERS_CSV.name} (จะติด FK)"
            )
        result = result_by_key[key]
        rows.append(
            {
                "poster_id": row["poster_uuid"],
                "storage_key": key,
                "is_primary": row["is_primary"] == "1",
                "sort_order": int(row["sort_order"]),
                "width_px": int(result["width"]),
                "height_px": int(result["height"]),
            }
        )
    return rows


def select_manifest_rows(manifest: list[dict[str, str]]) -> list[dict[str, str]]:
    """เฉพาะแถว is_gallery=1 และ duplicate!=1 (status ของไฟล์เช็คที่ precheck)."""
    return [r for r in manifest if r["is_gallery"] == "1" and r["duplicate"] != "1"]


# --------------------------------------------------------------------------
# prechecks
# --------------------------------------------------------------------------


def precheck_images(
    selected: list[dict[str, str]],
    result_rows: list[dict[str, str]],
    accepted_status: set[str],
) -> dict[str, dict[str, str]]:
    """ทุก object_key ที่จะ insert ต้องมีใน migration-result และ status ผ่านเกณฑ์

    ไม่ผ่านแม้แถวเดียว = หยุดทั้งชุด (ไม่ insert เฉพาะที่ผ่าน) — รูปที่หายไปเงียบๆ
    ตรวจยากกว่าการ seed ล้มทั้งรอบมาก
    """
    result_by_key: dict[str, dict[str, str]] = {}
    for row in result_rows:
        result_by_key.setdefault(row["object_key"], row)

    missing = [
        r["object_key"] for r in selected if r["object_key"] not in result_by_key
    ]
    bad_status = [
        (r["object_key"], result_by_key[r["object_key"]]["status"])
        for r in selected
        if r["object_key"] in result_by_key
        and result_by_key[r["object_key"]]["status"] not in accepted_status
    ]
    duplicated = [
        k for k, n in Counter(r["object_key"] for r in selected).items() if n > 1
    ]
    unsafe = [
        r["object_key"]
        for r in selected
        if not r["object_key"].startswith(PUBLIC_PREFIX)
    ]

    problems: list[str] = []
    if missing:
        problems.append(
            f"{len(missing)} object_key ไม่มีใน {RESULT_CSV.name} เลย:\n"
            + "\n".join(f"    {k}" for k in missing[:10])
        )
    if bad_status:
        counts = Counter(status for _, status in bad_status)
        problems.append(
            f"{len(bad_status)} object_key มี status ที่ไม่รับ "
            f"(รับเฉพาะ {sorted(accepted_status)}): {dict(counts)}\n"
            + "\n".join(f"    {k}  status={s}" for k, s in bad_status[:10])
            + "\n    → ถ้ายืนยันว่าไฟล์อยู่บน R2 จริง ใส่ --accept-status <status> เพิ่มได้"
        )
    if duplicated:
        problems.append(
            f"{len(duplicated)} object_key ซ้ำในชุดที่คัดมา (ติด uq_poster_images_storage_key):\n"
            + "\n".join(f"    {k}" for k in duplicated[:10])
        )
    if unsafe:
        problems.append(
            f"{len(unsafe)} object_key ไม่ได้อยู่ใต้ {PUBLIC_PREFIX} — build_media_url() "
            "จะ raise ตอนอ่าน (ADR-0006 D5):\n"
            + "\n".join(f"    {k}" for k in unsafe[:10])
        )

    for row in selected:
        result = result_by_key.get(row["object_key"])
        if result and not (result["width"] and result["height"]):
            problems.append(
                f"{row['object_key']} ไม่มี width/height ใน {RESULT_CSV.name} "
                "(ck_poster_images_dimensions_paired)"
            )
            break

    primary_per_poster = Counter(
        r["poster_uuid"] for r in selected if r["is_primary"] == "1"
    )
    multi_primary = [p for p, n in primary_per_poster.items() if n > 1]
    if multi_primary:
        problems.append(
            f"{len(multi_primary)} โปสเตอร์มีรูป is_primary มากกว่า 1 "
            "(ติด uq_poster_images_primary):\n"
            + "\n".join(f"    {p}" for p in multi_primary[:10])
        )
    no_primary = sorted({r["poster_uuid"] for r in selected} - set(primary_per_poster))
    if no_primary:
        problems.append(
            f"{len(no_primary)} โปสเตอร์ไม่มีรูป is_primary เลย:\n"
            + "\n".join(f"    {p}" for p in no_primary[:10])
        )

    if problems:
        raise PrecheckError("\n\n".join(problems))
    return result_by_key


# --------------------------------------------------------------------------
# database
# --------------------------------------------------------------------------


async def run(args: argparse.Namespace, database_url: str, target: str) -> int:
    from sqlalchemy import func, select, update
    from sqlalchemy.dialects.postgresql import insert
    from sqlalchemy.ext.asyncio import create_async_engine

    from app.models.enums import PosterCondition, PosterStatus
    from app.models.poster import Poster, PosterImage

    if args.status not in {s.value for s in PosterStatus}:
        raise PrecheckError(
            f"status {args.status!r} ไม่มีใน enum poster_status "
            f"(มีแค่ {[s.value for s in PosterStatus]})"
        )
    if args.grade_threshold is not None:
        grades = {derive_condition(Decimal(0), args.grade_threshold), "mint"}
        unknown = grades - {c.value for c in PosterCondition}
        if unknown:
            raise PrecheckError(f"เกรดที่จะลง {unknown} ไม่มีใน enum poster_condition")

    posters_csv = _read_csv(POSTERS_CSV)
    manifest_csv = _read_csv(MANIFEST_CSV)
    result_csv = _read_csv(RESULT_CSV)
    selected = select_manifest_rows(manifest_csv)

    result_by_key = precheck_images(
        selected, result_csv, {"uploaded", *args.accept_status}
    )
    poster_rows, notes = build_poster_rows(
        posters_csv, args.status, args.dedupe_poster_id, args.grade_threshold
    )
    poster_ids = {str(r["id"]) for r in poster_rows}
    image_rows = build_image_rows(selected, result_by_key, poster_ids)

    engine = create_async_engine(database_url)
    try:
        async with engine.begin() as conn:
            existing_posters = set(
                (await conn.execute(select(Poster.__table__.c.id))).scalars().all()
            )
            existing_keys = set(
                (await conn.execute(select(PosterImage.__table__.c.storage_key)))
                .scalars()
                .all()
            )

            new_posters = [
                r
                for r in poster_rows
                if r["id"] not in {str(i) for i in existing_posters}
            ]
            new_images = [
                r for r in image_rows if r["storage_key"] not in existing_keys
            ]

            # backfill: แถวที่ insert ไปแล้วรอบก่อนจะไม่ถูก ON CONFLICT DO NOTHING
            # แตะอีกเลย ถ้าไม่นับ/อัปเดตตรงนี้ --derive-condition-from-price จะไม่มีผล
            # อะไรกับ DB ที่ seed ไว้แล้ว · เงื่อนไข IS NULL คือหัวใจ — เกรดที่มีคนใส่
            # ไว้แล้วห้ามถูกทับ (อนาคต: ร้านค้าปรับเกรดเอง)
            backfill = 0
            if args.grade_threshold is not None:
                backfill = (
                    await conn.execute(
                        select(func.count())
                        .select_from(Poster.__table__)
                        .where(
                            Poster.__table__.c.condition_grade.is_(None),
                            Poster.__table__.c.id.in_([r["id"] for r in poster_rows]),
                        )
                    )
                ).scalar_one()

            _report(
                args,
                target,
                posters_csv,
                selected,
                poster_rows,
                image_rows,
                new_posters,
                new_images,
                notes,
                backfill,
            )

            if not args.commit:
                print(
                    "\nDRY-RUN — ไม่ได้เขียนอะไรลง database (ใส่ --commit เพื่อเขียนจริง)"
                )
                return 0

            poster_result = await conn.execute(
                insert(Poster.__table__).values(poster_rows).on_conflict_do_nothing()
            )
            image_result = await conn.execute(
                insert(PosterImage.__table__)
                .values(image_rows)
                .on_conflict_do_nothing()
            )
            backfilled = 0
            if args.grade_threshold is not None:
                for grade in ("mint", "very_good"):
                    ids = [
                        r["id"]
                        for r in poster_rows
                        if r.get("condition_grade") == grade
                    ]
                    if not ids:
                        continue
                    result = await conn.execute(
                        update(Poster.__table__)
                        .where(
                            Poster.__table__.c.condition_grade.is_(None),
                            Poster.__table__.c.id.in_(ids),
                        )
                        .values(condition_grade=grade)
                    )
                    backfilled += result.rowcount
        print(
            f"\nCOMMITTED — posters +{poster_result.rowcount} แถว · "
            f"poster_images +{image_result.rowcount} แถว"
            + (
                f" · condition_grade backfill {backfilled} แถว"
                if args.grade_threshold is not None
                else ""
            )
        )
    finally:
        await engine.dispose()
    return 0


def _report(
    args: argparse.Namespace,
    target: str,
    posters_csv: list[dict[str, str]],
    selected: list[dict[str, str]],
    poster_rows: list[dict[str, object]],
    image_rows: list[dict[str, object]],
    new_posters: list[dict[str, object]],
    new_images: list[dict[str, object]],
    notes: list[str],
    backfill: int,
) -> None:
    images_per_poster = Counter(str(r["poster_id"]) for r in image_rows)
    csv_unique = Counter(r["is_unique"] for r in posters_csv)
    row_unique = Counter(bool(r["is_unique"]) for r in poster_rows)
    print(f"target       : {target}  (mode={'COMMIT' if args.commit else 'DRY-RUN'})")
    print(f"status ที่จะลง : {args.status}")
    print()
    print(f"posters CSV        : {len(posters_csv)} แถว → {len(poster_rows)} โปสเตอร์")
    print(f"  มีอยู่แล้วใน DB   : {len(poster_rows) - len(new_posters)}")
    print(f"  จะ INSERT        : {len(new_posters)}")
    print(
        f"  is_unique (CSV)  : true {csv_unique['1']} · false {csv_unique['0']} "
        f"(= quantity==1 — ห้ามปล่อยเป็น server_default)"
    )
    print(f"  is_unique (insert): true {row_unique[True]} · false {row_unique[False]}")
    print(f"manifest ที่คัดแล้ว  : {len(selected)} แถว (is_gallery=1, duplicate!=1)")
    print(f"  มีอยู่แล้วใน DB   : {len(image_rows) - len(new_images)}")
    print(f"  จะ INSERT        : {len(new_images)}")
    print(
        f"  storage_key      : {len({str(r['storage_key']) for r in image_rows})} key ไม่ซ้ำ "
        f"· join width/height จาก {RESULT_CSV.name} ครบ "
        f"{sum(1 for r in image_rows if r['width_px'] and r['height_px'])}/{len(image_rows)}"
    )
    print(
        f"  primary/gallery  : {sum(1 for r in image_rows if r['is_primary'])} / "
        f"{len(image_rows)}  ·  รูปต่อโปสเตอร์ "
        f"{min(images_per_poster.values())}-{max(images_per_poster.values())}"
    )
    print()
    if args.grade_threshold is None:
        print("condition_grade      : NULL ทุกแถว (ADR-0003 — ห้ามเดา)")
    else:
        graded = Counter(str(r.get("condition_grade")) for r in poster_rows)
        print(
            f"🔴 condition_grade   : เดาจากราคา (> {args.grade_threshold} → mint · "
            f"ที่เหลือ → very_good)"
        )
        print(
            f"                      mint {graded['mint']} · "
            f"very_good {graded['very_good']} แถว"
        )
        print(
            f"                      backfill แถวที่เกรดเป็น NULL อยู่แล้ว: {backfill}"
        )
        print(
            "                      ⚠️ ค่า PLACEHOLDER ไม่ใช่สภาพจริง — dev เท่านั้น "
            "(ADR-0003 §Consequence)"
        )
        print("                      แถวที่มีเกรดอยู่แล้วจะไม่ถูกทับ")
    print("is_authenticated     : false ทุกแถว")
    print(
        "คอลัมน์ CSV ที่ข้าม   : year, edition_key (ไม่มีคอลัมน์รองรับใน schema — SCR-03 G8)"
    )
    print(
        "quantity            : ไม่มีคอลัมน์ → ลงเป็น is_unique เท่านั้น "
        "(false = มากกว่า 1 ใบ แต่ไม่รู้กี่ใบ — SCR-03 G8)"
    )
    if notes:
        print()
        for note in notes:
            print(f"NOTE: {note}")


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
        "--dry-run",
        action="store_true",
        help="นับแถวที่จะ insert โดยไม่เขียน (เป็น default อยู่แล้ว มีไว้ให้เขียนชัดเจน)",
    )
    parser.add_argument(
        "--status",
        default=None,
        help="ค่า posters.status ที่จะลง — ต้องระบุเองตอน --commit "
        "(poster_status ยังไม่มีค่าที่แปลว่า 'ยังไม่ publish' ดู REPORT)",
    )
    parser.add_argument(
        "--accept-status",
        action="append",
        default=[],
        metavar="STATUS",
        help="ยอมรับ status อื่นใน migration-result.csv เพิ่มจาก 'uploaded' (ระบุซ้ำได้)",
    )
    parser.add_argument(
        "--dedupe-poster-id",
        choices=["first"],
        default=None,
        help="ยอมให้ poster_uuid ซ้ำได้โดยเอาแถวแรก (default: หยุดแล้วรายงาน)",
    )
    parser.add_argument(
        "--derive-condition-from-price",
        action="store_true",
        help="🔴 เดา condition_grade จากราคา (> threshold → mint · ที่เหลือ → very_good) "
        "เป็น PLACEHOLDER สำหรับ dev เท่านั้น ไม่ใช่สภาพจริง — default ไม่เปิด "
        "ปล่อยเป็น NULL ตาม ADR-0003",
    )
    parser.add_argument(
        "--grade-price-threshold",
        type=Decimal,
        default=Decimal("1400"),
        metavar="THB",
        help="เส้นแบ่งราคาของ --derive-condition-from-price (default: 1400)",
    )
    args = parser.parse_args()

    if args.commit and args.dry_run:
        parser.error("--commit กับ --dry-run ใส่พร้อมกันไม่ได้")
    if args.commit and args.status is None:
        parser.error(
            "--commit ต้องระบุ --status ด้วย: poster_status มีแค่ available/reserved/sold "
            "ยังไม่มีค่าที่แปลว่า 'ยังไม่ publish' — ต้องเลือกเองอย่างรู้ตัว"
        )
    args.status = args.status or "available"
    args.dedupe_poster_id = args.dedupe_poster_id == "first"
    # threshold = None แปลว่า "ไม่แตะ condition_grade เลย" (ค่า default ของสคริปต์)
    args.grade_threshold = (
        args.grade_price_threshold if args.derive_condition_from_price else None
    )

    _load_dev_env()
    database_url = os.environ.get("DATABASE_URL", "")
    if not database_url:
        print("ERROR: ไม่พบ DATABASE_URL (ทั้งใน env และ .env)", file=sys.stderr)
        return 2

    sys.path.insert(0, str(REPO_ROOT))
    import asyncio

    try:
        target = _assert_dev_database(database_url)
        return asyncio.run(run(args, database_url, target))
    except PrecheckError as exc:
        print(
            f"\nPRECHECK ไม่ผ่าน — ไม่ได้เขียนอะไรลง database\n\n{exc}", file=sys.stderr
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
