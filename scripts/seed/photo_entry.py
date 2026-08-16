#!/usr/bin/env python3
"""เส้นที่ 8 — นำเข้ารูปจากโฟลเดอร์ในเครื่อง (ADR-0026 **D10** · INF-27 AC-7)

    ./venv/bin/python scripts/seed/photo_entry.py --dir photos            # dry-run
    ./venv/bin/python scripts/seed/photo_entry.py --dir photos --commit

โครงโฟลเดอร์ที่รับ — **หนึ่งโฟลเดอร์ = หนึ่งใบ ชื่อโฟลเดอร์คือ `poster_uuid`**

    photos/
      3f2a8c91-…-…/            ← poster_uuid ของใบนั้น
        front.jpg              → kind=FRONT
        front-02.jpg           → kind=FRONT  (ชิ้นที่สองของกลุ่ม)
        back.jpg               → kind=BACK
        defect-01.jpg          → kind=DEFECT
        defect-02.jpg          → kind=DEFECT

🔴 **นี่คือทางเข้าเดียวของรูปนับจากนี้** (ADR-0026 D10) — `migrate_to_r2.py` ซึ่งดึงรูป
จาก CDN ของ TikTok ถูก retire โดยตั้งใจใน PR #66 เพราะเป็นขั้นนำเข้าครั้งเดียวที่จบไปแล้ว
และ input ต้นทางไม่มีในเครื่องอีก

## ด่านชื่อไฟล์ — fail-closed ทั้งรอบ ไม่ใช่ข้ามทีละไฟล์ (AC-7)

ชื่อที่แปลเป็น `kind` ไม่ได้ = **ปฏิเสธทั้งรอบก่อนแตะอะไรเลย** · **ไม่มี default**
· เหตุผล: `kind` ผิด = รูปตำหนิกลายเป็นรูปหน้าใบบนหน้า Home ซึ่งผู้ซื้อเห็นทันที
(ADR-0026 D9) · ราคาของการเดาผิดสูงกว่าการให้คนเปลี่ยนชื่อไฟล์มาก
· ทรงเดียวกับเส้นที่ 6: **รูปแบบข้อมูลผิด = ปฏิเสธทั้งไฟล์** (ADR-0024 A-D6)

## `sort_order` — คำนวณจาก *แถบของ kind นั้น* ห้ามต่อท้าย max ข้ามกลุ่ม (ADR-0026 D5)

`FRONT` 0–99 · `BACK` 100–199 · `DEFECT` 200–299 · ภายในกลุ่มเรียงตาม `NN` ในชื่อไฟล์
· ใบที่มีรูปเดิมอยู่แล้ว **นับต่อจากเลขสูงสุด *ในแถบเดียวกัน*** ไม่ใช่จาก `max()` ทั้งใบ
— ต่อท้ายข้ามกลุ่มเมื่อไหร่ รูปหน้าใบที่เพิ่มทีหลังจะไปโผล่หลังรูปตำหนิ

## ทำไม `--commit` ต้องมี Pillow + boto3 แต่ dry-run ไม่ต้อง

สองไลบรารีนี้อยู่ใน `requirements-dev.txt` **ไม่ใช่ `requirements.txt`** — เป็นเครื่องมือ
ของ operator ไม่ใช่ของ API runtime · dry-run วางแผนได้ครบโดยไม่ต้องมี (ตรวจชื่อไฟล์ ·
แถบ · ซ้ำ) แต่**บอกตรง ๆ ในรายงานว่ายังไม่ได้ตรวจว่าไฟล์เป็นรูปจริง**
🔴 `--commit` **hard-require ทั้งคู่** — ไม่มีโหมด "อัปโหลดโดยไม่ล้าง EXIF"
(รูปจากมือถือมี GPS ของบ้านคนขายติดมาด้วย)

## ความไม่เป็นอะตอมที่ยอมรับแล้ว — อัปโหลดก่อน แล้วค่อย INSERT

R2 ไม่อยู่ในทรานแซกชันเดียวกับ DB · ถ้า INSERT ล้มหลังอัปโหลดสำเร็จ จะเหลือ object
กำพร้าใน R2 · **เลือกทางนี้เพราะทิศตรงข้ามแย่กว่า**: แถวใน DB ที่ชี้ object ที่ไม่มีจริง
= รูปเสียบนหน้าร้าน ส่วน object กำพร้า = เปลืองพื้นที่ไม่กี่บาทและไม่มีใครเห็น
· เมื่อเกิดขึ้น สคริปต์ **พิมพ์ key ที่กำพร้าออกมาให้ครบ** เพื่อให้ตามลบได้

## idempotent — รันซ้ำไม่สร้างแถวซ้ำ

`storage_key` มี **sha256 ของเนื้อไฟล์** อยู่ในชื่อ ⇒ ไฟล์เดิมได้ key เดิมเสมอ
· ก่อนวางแผน สคริปต์อ่าน key ที่ใบนั้นมีอยู่แล้วมาเทียบ **ถ้าแฮชซ้ำ = ข้ามแถวนั้น
พร้อมรายงาน** ไม่ใช่ปฏิเสธทั้งรอบ (ทรงเดียวกับ ADR-0024 A-D6)
"""

from __future__ import annotations

import argparse
import hashlib
import os
import re
import sys
import uuid
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

SEED_DIR = Path(__file__).resolve().parent
REPO_ROOT = SEED_DIR.parents[1]
sys.path.insert(0, str(REPO_ROOT))

from scripts.seed._shared import PrecheckError  # noqa: E402
from scripts.seed.apply_suggestions import _load_env  # noqa: E402

# 🔴 import **object เดียวกัน ไม่ก๊อป** — `assert_target`/`TARGETS`/`SIT_ENV_FILE`
# เป็นตัวเดียวกับทุกเส้นที่มี `--target` (มีเทส identity ล็อกที่
# tests/unit/test_seed_lane_shared_rules.py)
from scripts.seed.manual_entry import (  # noqa: E402
    SIT_ENV_FILE,
    TARGETS,
    assert_target,
)

DEFAULT_PHOTO_DIR = SEED_DIR / "photos"

# นามสกุลที่รับ — ตัวเล็กเท่านั้น (ADR-0026 D2: ฝั่งชื่อไฟล์เป็น lowercase)
ALLOWED_SUFFIXES = (".jpg", ".jpeg", ".png")

# ══════════════════════════════════════════════════════════════════════════
# ADR-0026 D5 — แถบของ sort_order ต่อ kind
#
# 🔴 ต้องตรงกับ `ck_poster_images_sort_order_band` ใน app/models/poster.py และ
#    migration a1f4d7b93e28 เป๊ะ · ถ้าไม่ตรง แถวจะถูก DB ปฏิเสธตอน INSERT
#    (ซึ่งถูกแล้ว — พังดังดีกว่าเรียงผิดเงียบ ๆ)
# ══════════════════════════════════════════════════════════════════════════
BAND_SIZE = 100
BANDS: dict[str, int] = {"FRONT": 0, "BACK": 100, "DEFECT": 200}

# ชื่อไฟล์ → kind · **lowercase เท่านั้น** และ **นี่คือจุดแปลงที่เดียวของทั้งระบบ**
# (ADR-0026 D2) — ชั้นอื่นเห็น UPPERCASE หมด ห้ามรับสองรูปแบบที่อื่น
_STEM = re.compile(r"^(?P<kind>front|back|defect)(?:-(?P<seq>\d{1,2}))?$")


class PhotoAction(str, Enum):
    UPLOAD = "UPLOAD"
    SKIP_ALREADY = "SKIP_ALREADY"  # แฮชเดิมมีอยู่แล้วในใบนี้ — รันซ้ำ


@dataclass(frozen=True)
class PlannedPhoto:
    poster_id: uuid.UUID
    path: Path
    kind: str
    sort_order: int
    storage_key: str
    sha256: str
    is_primary: bool
    action: PhotoAction


@dataclass(frozen=True)
class PosterPhotoState:
    """สิ่งที่ต้องรู้เกี่ยวกับใบหนึ่งก่อนวางแผน — มาจาก DB ทั้งหมด"""

    exists: bool
    has_primary: bool
    # เลข sort_order สูงสุดที่ใช้ไปแล้วในแต่ละแถบ (ไม่มี = ยังไม่มีรูปในแถบนั้น)
    max_in_band: dict[str, int] = field(default_factory=dict)
    # แฮชของรูปที่ใบนี้มีอยู่แล้ว — ใช้ตัดสิน SKIP_ALREADY
    known_hashes: frozenset[str] = frozenset()


def parse_kind(filename: str) -> tuple[str, int]:
    """ชื่อไฟล์ → (`kind` แบบ UPPERCASE, ลำดับในกลุ่ม)

    🔴 **fail-closed** — ชื่อที่ไม่เข้าแบบ raise `PrecheckError` เสมอ **ไม่มี default**
    · `front.jpg` → `("FRONT", 0)` · `defect-02.jpg` → `("DEFECT", 2)`
    · `FRONT.JPG` **ไม่ผ่าน** โดยตั้งใจ (ADR-0026 D2 — ฝั่งชื่อไฟล์เป็น lowercase
      เท่านั้น · การรับตัวใหญ่ด้วยคือการยอมรับสองรูปแบบที่ขอบเดียวกัน ซึ่ง D2 ห้าม)
    """
    path = Path(filename)
    if path.suffix not in ALLOWED_SUFFIXES:
        raise PrecheckError(
            f"`{filename}` — นามสกุลไม่รองรับ · รับเฉพาะ "
            f"{' · '.join(ALLOWED_SUFFIXES)} (ตัวเล็ก)"
        )
    matched = _STEM.match(path.stem)
    if matched is None:
        raise PrecheckError(
            f"`{filename}` — อ่านชนิดของรูปจากชื่อไฟล์ไม่ได้\n"
            "  รับเฉพาะ: front.jpg · front-NN.jpg · back.jpg · back-NN.jpg · defect-NN.jpg\n"
            "  (ตัวเล็กเท่านั้น · NN เป็นเลข 1–2 หลัก)\n"
            "  🔴 ไม่มีค่า default โดยตั้งใจ — เดาผิดแปลว่ารูปตำหนิไปโผล่หน้า Home "
            "ในฐานะรูปหน้าใบ (ADR-0026 D9) ซึ่งผู้ซื้อเห็นทันที"
        )
    return matched.group("kind").upper(), int(matched.group("seq") or 0)


def build_storage_key(
    poster_id: uuid.UUID, sort_order: int, digest: str, suffix: str
) -> str:
    """`posters/public/{uuid}/{NN}-{sha256[:32]}{ext}` — ADR-0006 **D2**

    ใช้ **แฮชของเนื้อไฟล์** เป็น `asset_id` แทนค่าสุ่ม เพื่อให้ไฟล์เดิมได้ key เดิมเสมอ
    ⇒ อัปโหลดซ้ำไม่สร้าง object ใหม่ และ `uq_poster_images_storage_key` เป็นตาข่าย
    ชั้นสุดท้ายที่ระดับ DB
    """
    return f"posters/public/{poster_id}/{sort_order:02d}-{digest[:32]}{suffix}"


def plan_folder(
    poster_id: uuid.UUID,
    files: list[tuple[Path, str]],
    state: PosterPhotoState,
) -> list[PlannedPhoto]:
    """🔴 pure — วางแผนของใบเดียว · `files` = [(path, sha256), ...] อ่านมาแล้ว

    เขียนแบบนี้เพื่อให้เทสป้อนสถานะที่ *ละเมิด* เข้ามาได้โดยไม่ต้องมีทั้ง DB และไฟล์จริง
    (บทเรียนเดียวกับ `test_status_writer_invariant.py`)
    """
    if not state.exists:
        raise PrecheckError(
            f"`{poster_id}` — ไม่มีใบนี้ในตาราง posters\n"
            "  ชื่อโฟลเดอร์ต้องเป็น poster_uuid ของใบที่มีอยู่จริง "
            "(เส้นนี้เพิ่มรูปให้ใบที่มีอยู่ ไม่ได้สร้างใบใหม่)"
        )

    parsed = []
    for path, digest in files:
        kind, seq = parse_kind(path.name)
        parsed.append((kind, seq, path, digest))

    # ── ด่าน front-required ฝั่งเครื่องมือ (ADR-0026 D8 ชั้นที่ 3) ──────────
    # ปฏิเสธ**ทั้งโฟลเดอร์** ถ้าใบนี้จะยังไม่มีรูปหน้าใบหลังรอบนี้
    has_front_after = any(k == "FRONT" for k, _, _, _ in parsed) or bool(
        state.max_in_band.get("FRONT") is not None
    )
    if not has_front_after:
        raise PrecheckError(
            f"`{poster_id}` — โฟลเดอร์นี้ไม่มีไฟล์ `front*` และใบนี้ยังไม่มีรูป FRONT ใน DB\n"
            "  ขัด BR-06 (ADR-0026 D8) — หน้า Home ใช้รูป FRONT เท่านั้น ใบที่มีแต่รูป\n"
            "  ตำหนิหรือด้านหลังจะขึ้นร้านแบบไม่มีรูปให้แสดง\n"
            "  🔴 ปฏิเสธทั้งโฟลเดอร์ ไม่ใช่นำเข้าเฉพาะที่มี — เพื่อไม่ให้ครึ่งหนึ่งของงาน\n"
            "  ลงไปแล้วอีกครึ่งค้าง"
        )

    plans: list[PlannedPhoto] = []
    next_in_band = dict(state.max_in_band)
    primary_taken = state.has_primary
    seen_hashes = set(state.known_hashes)

    # เรียงตาม (แถบ, ลำดับในชื่อไฟล์, ชื่อไฟล์) — ชื่อไฟล์เป็นตัวตัดสินสุดท้ายเพื่อให้
    # ผลคงที่ทุกรอบ ไม่ขึ้นกับลำดับที่ระบบไฟล์คืนมา
    for kind, seq, path, digest in sorted(
        parsed, key=lambda r: (BANDS[r[0]], r[1], r[2].name)
    ):
        if digest in seen_hashes:
            plans.append(
                PlannedPhoto(
                    poster_id=poster_id,
                    path=path,
                    kind=kind,
                    sort_order=-1,
                    storage_key="",
                    sha256=digest,
                    is_primary=False,
                    action=PhotoAction.SKIP_ALREADY,
                )
            )
            continue
        seen_hashes.add(digest)

        band_start = BANDS[kind]
        current = next_in_band.get(kind)
        sort_order = band_start if current is None else current + 1
        if sort_order >= band_start + BAND_SIZE:
            raise PrecheckError(
                f"`{poster_id}` — รูป {kind} ล้นแถบ ({band_start}–"
                f"{band_start + BAND_SIZE - 1})\n"
                f"  ใบนี้จะมีรูป {kind} เกิน {BAND_SIZE} รูป ซึ่งเกินเพดานที่ ADR-0026 D5\n"
                "  ยอมรับไว้ · ล้นแถบแล้วลำดับกลุ่มจะพัง (รูปกลุ่มถัดไปถูกแซง)"
            )
        next_in_band[kind] = sort_order

        # รูป FRONT ตัวแรกของใบที่ยังไม่มีรูปนำ → ตั้งเป็น primary
        # (ck_poster_images_primary_is_front บังคับอยู่แล้วว่า primary ต้องเป็น FRONT)
        is_primary = kind == "FRONT" and not primary_taken
        if is_primary:
            primary_taken = True

        plans.append(
            PlannedPhoto(
                poster_id=poster_id,
                path=path,
                kind=kind,
                sort_order=sort_order,
                storage_key=build_storage_key(
                    poster_id, sort_order, digest, path.suffix
                ),
                sha256=digest,
                is_primary=is_primary,
                action=PhotoAction.UPLOAD,
            )
        )
    return plans


def read_folders(root: Path) -> dict[uuid.UUID, list[Path]]:
    """อ่านโครงโฟลเดอร์ → {poster_uuid: [ไฟล์...]} · ตรวจชื่อโฟลเดอร์ที่ไม่ใช่ uuid"""
    if not root.is_dir():
        raise PrecheckError(f"ไม่พบโฟลเดอร์ {root}")
    folders: dict[uuid.UUID, list[Path]] = {}
    for child in sorted(root.iterdir()):
        if child.name.startswith(".") or not child.is_dir():
            continue
        try:
            poster_id = uuid.UUID(child.name)
        except ValueError as exc:
            raise PrecheckError(
                f"`{child.name}` — ชื่อโฟลเดอร์ไม่ใช่ UUID\n"
                "  หนึ่งโฟลเดอร์ = หนึ่งใบ และชื่อต้องเป็น poster_uuid ของใบนั้น"
            ) from exc
        files = [
            f
            for f in sorted(child.iterdir())
            if f.is_file() and not f.name.startswith(".")
        ]
        if not files:
            raise PrecheckError(f"`{child.name}` — โฟลเดอร์ว่าง")
        folders[poster_id] = files
    if not folders:
        raise PrecheckError(f"ไม่มีโฟลเดอร์ของใบไหนเลยใน {root}")
    return folders


def sha256_of(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def strip_exif(raw: bytes) -> tuple[bytes, int, int]:
    """ล้าง EXIF + ยืนยันว่าเป็นรูปจริง → (bytes สะอาด, กว้าง, สูง)

    🔴 **ไม่มีโหมดข้ามการล้าง** — รูปจากมือถือมี GPS ของบ้านคนขายติดมาด้วย
    · Pillow raise ถ้าไฟล์ไม่ใช่รูป ⇒ ทำหน้าที่ตรวจ magic byte ไปในตัว
      (ไม่เชื่อนามสกุลไฟล์)
    """
    try:
        from PIL import Image
    except ModuleNotFoundError as exc:  # pragma: no cover — ขึ้นกับเครื่อง
        raise PrecheckError(
            "ไม่มี Pillow — ติดตั้งก่อน: ./venv/bin/pip install -r requirements-dev.txt\n"
            "  🔴 ไม่มีโหมดอัปโหลดโดยไม่ล้าง EXIF (รูปมือถือมี GPS ติดมาด้วย)"
        ) from exc
    import io

    Image.open(io.BytesIO(raw)).verify()
    image = Image.open(io.BytesIO(raw))
    width, height = image.size
    fmt = (image.format or "JPEG").upper()
    if image.mode in ("RGBA", "P") and fmt == "JPEG":
        image = image.convert("RGB")
    buffer = io.BytesIO()
    # Pillow ไม่ copy EXIF ให้ตอน save (ต้องส่ง exif= เองถึงจะติด) — re-encode เฉย ๆ
    # จึงได้ไฟล์สะอาด
    if fmt == "JPEG":
        image.save(buffer, format="JPEG", quality=95, optimize=True)
    elif fmt == "PNG":
        image.save(buffer, format="PNG", optimize=True)
    else:
        image.save(buffer, format=fmt)
    return buffer.getvalue(), width, height


def r2_client():  # pragma: no cover — ต้องมี credential จริง
    """client ของ R2 · **ต้องมี env ครบ 4 ตัว ไม่งั้นหยุด** ไม่ใช่เดาค่า"""
    try:
        import boto3
        from botocore.client import Config
    except ModuleNotFoundError as exc:
        raise PrecheckError(
            "ไม่มี boto3 — ติดตั้งก่อน: ./venv/bin/pip install -r requirements-dev.txt"
        ) from exc

    required = (
        "R2_ENDPOINT_URL",
        "R2_ACCESS_KEY_ID",
        "R2_SECRET_ACCESS_KEY",
        "R2_BUCKET",
    )
    missing = [name for name in required if not os.environ.get(name)]
    if missing:
        raise PrecheckError(
            f"ต้องตั้ง env ก่อน --commit: {', '.join(missing)}\n"
            "  🔴 ค่าพวกนี้ไม่อยู่ใน .env ของ repo โดยตั้งใจ (เป็น credential ของ bucket)"
        )
    return boto3.client(
        "s3",
        endpoint_url=os.environ["R2_ENDPOINT_URL"],
        aws_access_key_id=os.environ["R2_ACCESS_KEY_ID"],
        aws_secret_access_key=os.environ["R2_SECRET_ACCESS_KEY"],
        region_name="auto",
        config=Config(signature_version="s3v4"),
    )


def _report(
    plans_by_poster: dict[uuid.UUID, list[PlannedPhoto]],
    target_label: str,
    committed: bool,
    checked_images: bool,
) -> None:
    flat = [p for plans in plans_by_poster.values() for p in plans]
    upload = [p for p in flat if p.action is PhotoAction.UPLOAD]
    skipped = [p for p in flat if p.action is PhotoAction.SKIP_ALREADY]

    print("=" * 72)
    print("เส้นที่ 8 — นำเข้ารูปจากโฟลเดอร์ (ADR-0026 D10 · INF-27)")
    print(
        f"target       : {target_label}  (mode={'COMMIT' if committed else 'DRY-RUN'})"
    )
    print(f"ใบที่มีรูป    : {len(plans_by_poster)}")
    print(f"จะนำเข้า      : {len(upload)} รูป")
    for kind in ("FRONT", "BACK", "DEFECT"):
        count = sum(1 for p in upload if p.kind == kind)
        if count:
            orders = sorted(p.sort_order for p in upload if p.kind == kind)
            print(f"  {kind:<7}: {count} รูป · sort_order {orders}")
    if skipped:
        print(f"ข้าม (มีอยู่แล้ว): {len(skipped)} รูป — แฮชเดิมอยู่ในใบนั้นแล้ว")
        for p in skipped:
            print(f"  · {p.poster_id} / {p.path.name}")
    primaries = [p for p in upload if p.is_primary]
    if primaries:
        print(f"ตั้งเป็นรูปนำ  : {len(primaries)} ใบ (ใบที่ยังไม่มี is_primary)")

    if not checked_images:
        print(
            "\n⚠️  **ยังไม่ได้ตรวจว่าไฟล์เป็นรูปจริงและยังไม่ได้ล้าง EXIF** — dry-run รอบนี้\n"
            "    ไม่มี Pillow จึงวางแผนจากชื่อไฟล์กับแฮชเท่านั้น · `--commit` จะไม่ยอมรัน\n"
            "    ถ้าไม่มีไลบรารีครบ (ไม่มีโหมดอัปโหลดโดยไม่ล้าง EXIF)"
        )
    if not committed:
        print("\nDRY-RUN — ยังไม่อัปโหลดและยังไม่เขียน DB · ใส่ --commit เมื่อพร้อม")
    print("=" * 72)


async def _load_states(
    session: Any, poster_ids: list[uuid.UUID]
) -> dict[uuid.UUID, PosterPhotoState]:
    from sqlalchemy import select

    from app.models.poster import Poster, PosterImage

    rows = (
        await session.execute(select(Poster.id).where(Poster.id.in_(poster_ids)))
    ).all()
    existing = {r[0] for r in rows}

    images = (
        await session.execute(
            select(
                PosterImage.poster_id,
                PosterImage.kind,
                PosterImage.sort_order,
                PosterImage.is_primary,
                PosterImage.storage_key,
            ).where(PosterImage.poster_id.in_(poster_ids))
        )
    ).all()

    states: dict[uuid.UUID, PosterPhotoState] = {}
    for poster_id in poster_ids:
        mine = [row for row in images if row[0] == poster_id]
        max_in_band: dict[str, int] = {}
        for _, kind, sort_order, _, _ in mine:
            name = kind.value if hasattr(kind, "value") else str(kind)
            max_in_band[name] = max(max_in_band.get(name, sort_order), sort_order)
        # แฮชอยู่ในชื่อไฟล์ของ key: `…/NN-<sha256[:32]>.<ext>`
        hashes = {
            Path(row[4]).stem.split("-", 1)[1]
            for row in mine
            if "-" in Path(row[4]).stem
        }
        states[poster_id] = PosterPhotoState(
            exists=poster_id in existing,
            has_primary=any(row[3] for row in mine),
            max_in_band=max_in_band,
            known_hashes=frozenset(hashes),
        )
    return states


async def run(args: argparse.Namespace, target_label: str) -> int:
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from app.models.enums import PosterImageKind
    from app.models.poster import PosterImage

    folders = read_folders(args.dir)
    digests = {
        poster_id: [(path, sha256_of(path)) for path in files]
        for poster_id, files in folders.items()
    }

    engine = create_async_engine(os.environ["DATABASE_URL"])
    maker = async_sessionmaker(engine, expire_on_commit=False)
    uploaded_keys: list[str] = []
    try:
        async with maker() as session:
            states = await _load_states(session, list(folders))
            plans_by_poster = {
                poster_id: plan_folder(poster_id, files, states[poster_id])
                for poster_id, files in digests.items()
            }

            checked = True
            if not args.commit:
                try:
                    strip_exif(next(iter(folders.values()))[0].read_bytes())
                except PrecheckError:
                    checked = False
                _report(plans_by_poster, target_label, False, checked)
                return 0

            client = r2_client()
            bucket = os.environ["R2_BUCKET"]
            for plan in [p for ps in plans_by_poster.values() for p in ps]:
                if plan.action is not PhotoAction.UPLOAD:
                    continue
                clean, width, height = strip_exif(plan.path.read_bytes())
                client.put_object(
                    Bucket=bucket,
                    Key=plan.storage_key,
                    Body=clean,
                    ContentType=(
                        "image/png" if plan.path.suffix == ".png" else "image/jpeg"
                    ),
                    CacheControl="public, max-age=31536000, immutable",
                )
                uploaded_keys.append(plan.storage_key)
                session.add(
                    PosterImage(
                        poster_id=plan.poster_id,
                        storage_key=plan.storage_key,
                        kind=PosterImageKind(plan.kind),
                        sort_order=plan.sort_order,
                        is_primary=plan.is_primary,
                        width_px=width,
                        height_px=height,
                    )
                )
            await session.commit()
            _report(plans_by_poster, target_label, True, True)
            return 0
    except Exception:
        if uploaded_keys:
            print(
                "\n🔴 อัปโหลดขึ้น R2 ไปแล้วแต่เขียน DB ไม่สำเร็จ — **object กำพร้าที่ต้องตามลบ**:",
                file=sys.stderr,
            )
            for key in uploaded_keys:
                print(f"  {key}", file=sys.stderr)
        raise
    finally:
        await engine.dispose()


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--commit",
        action="store_true",
        help="อัปโหลดขึ้น R2 และเขียน DB จริง (ไม่ใส่ = dry-run วางแผนอย่างเดียว)",
    )
    parser.add_argument(
        "--dir",
        type=Path,
        default=DEFAULT_PHOTO_DIR,
        help=f"โฟลเดอร์รูป (default: {DEFAULT_PHOTO_DIR})",
    )
    parser.add_argument(
        "--target",
        choices=TARGETS,
        default="dev",
        help="ปลายทาง — เหมือนเส้นอื่นทุกประการ (ADR-0015 D8: dev กับ sit เท่านั้น) · "
        f"sit ต้องรันข้างในคอนเทนเนอร์ sit และ DATABASE_URL ต้องตรงกับ {SIT_ENV_FILE} เป๊ะ",
    )
    args = parser.parse_args()

    # 🔴 เส้นนี้ **ไม่มี --reviewed-by/--reviewed-at โดยตั้งใจ** — ต่างจากหกเส้นที่มี
    # เพราะ `poster_images` ไม่มีคอลัมน์ provenance ให้เขียน (ADR-0006 D2 ตั้งใจให้
    # ตารางนี้เก็บแค่ที่อยู่ของ object) · flag ที่ไม่มีปลายทางให้เขียนคือ flag ที่หลอก
    # คนกรอกว่ามีใครบันทึกไว้ · ร่องรอยของรูปคือ storage_key + created_at

    _load_env(args.target)
    database_url = os.environ.get("DATABASE_URL", "")
    if not database_url:
        print(f"ไม่พบ DATABASE_URL (target={args.target})", file=sys.stderr)
        return 1

    try:
        target_label = (
            f"{assert_target(database_url, args.target)}  [--target {args.target}]"
        )
    except PrecheckError as exc:
        print(f"precheck ไม่ผ่าน: {exc}", file=sys.stderr)
        return 1

    import asyncio

    try:
        return asyncio.run(run(args, target_label))
    except PrecheckError as exc:
        print(f"precheck ไม่ผ่าน: {exc}", file=sys.stderr)
        return 1
    except OSError as exc:
        print(f"ต่อ database ไม่ได้ (target={args.target}): {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
