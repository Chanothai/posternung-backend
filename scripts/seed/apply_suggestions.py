"""นำค่าที่ **คนตรวจแล้ว** จากใบงานเซ็นรับเข้า `posters` — ADR-0010 (INF-08)

    python3 scripts/seed/make_review_sheet.py               # 1. สร้างใบงานเปล่า
    # 2. คนเปิดรูปตรวจ แล้วกรอก approved / corrected_text เอง
    python3 scripts/seed/apply_suggestions.py               # 3. dry-run (default)
    python3 scripts/seed/apply_suggestions.py --commit \
        --reviewed-by chanothai --reviewed-at 2026-08-04T13:30:00+07:00

สคริปต์นี้คือ **เส้นทาง UPDATE เส้นแรกของโปรเจกต์** — ทุกอย่างก่อนหน้านี้เป็น INSERT
ที่ `on_conflict_do_nothing()` เท่านั้น กฎทุกข้อข้างล่างมาจาก ADR-0010 §Decision ตรง ๆ
ไม่ใช่ดุลพินิจของคนเขียนสคริปต์:

* **D1** — "คนที่ระบุตัวได้" ใน Phase 1 = ชื่อที่คนรันระบุเอง (`--reviewed-by`)
  ไม่ใช่ในระบบสิทธิ์ · เป็นสคริปต์ที่ operator รันเอง **ไม่ใช่ endpoint**
  เพราะ admin write endpoint ชน guard `admin catalog governance (EPIC 7)` = Phase 2
  🔴 `reviewed_by` คือการ **อ้างชื่อ ไม่ใช่การพิสูจน์ตัวตน** — ไม่มี auth ไม่มี signature
* **D2** — **ห้ามแตะ `needs_review`** ไม่ว่ากรณีใด (และห้ามแตะ `status` ตาม
  `poster-database` §3) · allowlist มีฟิลด์เดียว การพลิกธงระดับแถวคือการอ้างเกินหลักฐาน
* **D3** — ทุกการเขียนบันทึกลง `poster_attribute_reviews` หนึ่งแถว
* **D4** — allowlist = `release_date_text` **เท่านั้น** · `release_date` เขียนได้เฉพาะค่า
  ที่ได้จาก `parse_release_date_text()` (ADR-0009 D13 ข้อ 2 — writer เดียว)
  **สคริปต์นี้ห้ามคำนวณวันที่เอง** และห้ามเชื่อคอลัมน์ `parsed_date` ในใบงาน
* **D5** — อ่านจาก **ใบงานที่แยกต่างหาก** ห้ามอ่าน/เขียน `ai-suggestions.csv`
  ซึ่งเป็นหลักฐานดิบของ AI
* **D6** — เขียนเฉพาะแถวที่คอลัมน์ปลายทางเป็น `NULL` · **ไม่มีโหมดเขียนทับ** ทำให้
  สคริปต์ idempotent โดยโครงสร้าง รันซ้ำไม่ลบงานที่คนแก้ไปแล้ว
* **D7** — dry-run เป็น default · ต้อง `--commit` ถึงเขียนจริง · dev เป็นค่าตั้งต้น
  SIT ต้องระบุ `--target sit` · **production ไม่มีทางเลือกให้เลือกเลย**

## รูปแบบใบงาน (D5)

สร้างด้วย `make_review_sheet.py` — 8 คอลัมน์:

    poster_uuid,release_date_text,parsed_date,parse_status,evidence,image_url,approved,corrected_text

| คอลัมน์ | ใครกรอก | สคริปต์นี้ใช้ทำอะไร |
|---|---|---|
| `poster_uuid` | เครื่อง | ระบุใบ |
| `release_date_text` | เครื่อง (ค่าที่ AI อ่านได้) | ค่าตั้งต้น ใช้เมื่อ `corrected_text` ว่าง |
| `parsed_date` · `parse_status` | เครื่อง | **ให้คนอ่านเท่านั้น** สคริปต์ parse ใหม่เองเสมอ |
| `evidence` · `image_url` | เครื่อง | ให้คนเปิดรูปตรวจ — สคริปต์ไม่แตะ |
| `approved` | **คน** | ตัวกั้น — ว่าง = ยังไม่ตรวจ · `yes` = อนุมัติ · `no` = ไม่อนุมัติ |
| `corrected_text` | **คน** | ถ้ากรอก จะ**ทับ** `release_date_text` |

`parsed_date` ในใบงานเป็นข้อมูลประกอบการตัดสินของคนล้วน ๆ — สคริปต์คำนวณ
`release_date` ใหม่จาก `parse_release_date_text()` เสมอ ต่อให้คอลัมน์นั้นถูกแก้มือมา
ก็ไม่มีผล (D4 + ADR-0009 D13 ข้อ 2 writer เดียว)

## แถวไหนถูกข้าม แถวไหนทำทั้งไฟล์พัง

**ข้ามเฉย ๆ (ปกติ ไม่ใช่ error):** `approved` ว่าง (ยังตรวจไม่ถึง) · `approved=no` ·
ใบไม่มีใน DB · ปลายทางมีค่าอยู่แล้ว — ใบงานที่ตรวจไปได้ครึ่งเดียวเป็นเรื่องปกติ

**ทั้งไฟล์ถูกปฏิเสธ (fail-closed):** `poster_uuid` ไม่ใช่ UUID · `poster_uuid` ซ้ำ ·
`approved` เป็นคำที่ไม่รู้จัก · อนุมัติแล้วแต่ไม่มีข้อความให้เขียนเลย — พวกนี้แปลว่า
คนทำไฟล์เข้าใจกติกาไม่ตรงกัน การ apply บางส่วนจะทำให้ตามยากภายหลังว่าอะไรเข้าไปแล้ว
"""

from __future__ import annotations

import argparse
import csv
import os
import sys
import uuid
from collections import Counter
from dataclasses import dataclass
from datetime import date, datetime
from enum import Enum
from pathlib import Path
from urllib.parse import unquote, urlsplit

SEED_DIR = Path(__file__).resolve().parent
REPO_ROOT = SEED_DIR.parents[1]

DEFAULT_SIGNOFF_CSV = SEED_DIR / "release-date-signoff.csv"

# ADR-0010 D4 — รอบแรกเขียนได้ฟิลด์เดียว · `release_date` ไม่อยู่ในนี้โดยตั้งใจ
# เพราะมันเป็นค่า derived ที่สคริปต์คำนวณเองจาก parser ไม่ใช่ค่าที่รับจากไฟล์
ALLOWED_FIELDS = frozenset({"release_date_text"})
# ใบงานรอบนี้มีฟิลด์เดียวจึง **ไม่มีคอลัมน์ `field`** ในไฟล์ — ชื่อฟิลด์เป็นค่าคงที่
# ถ้า ALLOWED_FIELDS โตขึ้นเมื่อไหร่ ต้องเพิ่มคอลัมน์นั้นกลับมาพร้อมกัน
# (มี test ล็อกไว้ว่าสองอย่างนี้ต้องสอดคล้องกันเสมอ)
TARGET_FIELD = "release_date_text"

# คอลัมน์ของใบงาน — `make_review_sheet.py` import ไปใช้ ไม่ประกาศซ้ำสองที่
REVIEW_SHEET_COLUMNS = (
    "poster_uuid",
    "release_date_text",
    "parsed_date",
    "parse_status",
    "evidence",
    "image_url",
    "approved",
    "corrected_text",
)
# คอลัมน์ที่สคริปต์นี้ *ใช้จริง* — ที่เหลือเป็นข้อมูลให้คนอ่าน ขาดได้ไม่เป็นไร
REQUIRED_COLUMNS = ("poster_uuid", "release_date_text", "approved", "corrected_text")

_APPROVED_WORDS = frozenset({"yes", "y", "true", "1"})
_REJECTED_WORDS = frozenset({"no", "n", "false", "0"})

# --- guard ปลายทาง (D7) ---
LOCAL_HOSTS = {"", "localhost", "127.0.0.1", "::1"}
# ชื่อ database ที่สื่อว่าเป็น env จริงกว่าที่เลือกไว้ — ปฏิเสธเสมอไม่ว่า target ไหน
PRODUCTION_DB_HINTS = ("prod", "uat", "stage")
PRODUCTION_ENV_FILES = (".env.uat", ".env.production")


class PrecheckError(Exception):
    """precheck ไม่ผ่าน — รายละเอียดอยู่ใน args[0] (หลายบรรทัดได้)."""


# --------------------------------------------------------------------------
# env + guard ปลายทาง (ทำก่อน import app.* เพราะ Settings() ต้องการ env ครบตอน import)
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


def _load_env(target: str) -> None:
    """เติม env จากไฟล์ของ target ให้ `Settings()` สร้างได้ไม่ว่าจะรันจาก cwd ไหน

    env var ที่ตั้งมาจากข้างนอกชนะไฟล์เสมอ (12-Factor)
    """
    env_file = ".env" if target == "dev" else f".env.{target}"
    for key, value in _parse_env_file(REPO_ROOT / env_file).items():
        os.environ.setdefault(key, value)


def assert_target_database(database_url: str, target: str) -> str:
    """ยืนยันว่า `DATABASE_URL` ตรงกับ target ที่สั่งจริง — ไม่ผ่าน = จบก่อนแตะ DB

    ADR-0010 D7: รอบนี้อนุญาต dev กับ SIT เท่านั้น · **ไม่มี target production
    ให้เลือกเลย** และต่อให้ url ชี้ production ก็ถูกปฏิเสธที่นี่อีกชั้น
    """
    parts = urlsplit(database_url)
    host = (parts.hostname or "").lower()
    db_name = unquote(parts.path).lstrip("/").lower()

    hit = next((h for h in PRODUCTION_DB_HINTS if h in db_name), None)
    if hit:
        raise PrecheckError(
            f"ชื่อ database {db_name!r} มีคำว่า {hit!r} — ADR-0010 D7 อนุญาตแค่ dev กับ SIT "
            "ในรอบนี้"
        )
    for env_file in PRODUCTION_ENV_FILES:
        other = _parse_env_file(REPO_ROOT / env_file).get("DATABASE_URL")
        if other and other == database_url:
            raise PrecheckError(
                f"DATABASE_URL ตรงกับค่าใน {env_file} — นั่นคือ env จริงที่รอบนี้ไม่อนุญาต"
            )

    if target == "dev":
        if host not in LOCAL_HOSTS:
            raise PrecheckError(
                f"--target dev แต่ DATABASE_URL ชี้ host {host!r} ซึ่งไม่ใช่เครื่องนี้"
            )
        if "sit" in db_name:
            raise PrecheckError(
                f"--target dev แต่ชื่อ database {db_name!r} มีคำว่า 'sit' — สั่ง target ผิด"
            )
    elif target == "sit":
        sit_url = _parse_env_file(REPO_ROOT / ".env.sit").get("DATABASE_URL")
        if sit_url and sit_url != database_url:
            raise PrecheckError("--target sit แต่ DATABASE_URL ไม่ตรงกับค่าใน .env.sit")
        if not sit_url and "sit" not in db_name:
            raise PrecheckError(
                f"--target sit แต่ไม่มี .env.sit และชื่อ database {db_name!r} ไม่มีคำว่า 'sit' "
                "— ยืนยันปลายทางไม่ได้"
            )
    else:  # pragma: no cover — argparse choices กันไว้แล้ว
        raise PrecheckError(f"target {target!r} ไม่รองรับ")

    return f"{host or 'localhost'}/{db_name}"


# --------------------------------------------------------------------------
# อ่าน + ตรวจใบงาน (pure — ไม่แตะ DB)
# --------------------------------------------------------------------------


class Verdict(str, Enum):
    """ผลการตรวจของคนในคอลัมน์ `approved`."""

    PENDING = "PENDING"  # ว่าง — ยังตรวจไม่ถึงแถวนี้
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


@dataclass(frozen=True)
class ReviewRow:
    """หนึ่งแถวของใบงานที่ผ่านการตรวจรูปแบบแล้ว."""

    poster_uuid: uuid.UUID
    release_date_text: str  # ค่าที่ AI อ่านได้
    corrected_text: str  # ค่าที่คนแก้ (ว่าง = ใช้ของ AI)
    verdict: Verdict

    @property
    def effective_text(self) -> str:
        """ข้อความที่จะถูกเขียนจริง — `corrected_text` ชนะเสมอเมื่อมีค่า."""
        return self.corrected_text or self.release_date_text

    @property
    def was_corrected(self) -> bool:
        return bool(self.corrected_text)


def read_review_sheet(path: Path) -> list[dict[str, str]]:
    if not path.is_file():
        raise PrecheckError(
            f"ไม่พบใบงาน {path}\n"
            "สร้างด้วย `python3 scripts/seed/make_review_sheet.py` ก่อน แล้วให้คนกรอก "
            "approved / corrected_text\n"
            "ไฟล์นี้เป็นคนละไฟล์กับ ai-suggestions.csv โดยตั้งใจ (ADR-0010 D5) — "
            "ผลของ AI คือหลักฐานดิบ ห้ามเขียนทับ"
        )
    with path.open(newline="", encoding="utf-8-sig") as fh:
        reader = csv.DictReader(fh)
        missing = [c for c in REQUIRED_COLUMNS if c not in (reader.fieldnames or [])]
        if missing:
            raise PrecheckError(
                f"ใบงานขาดคอลัมน์: {', '.join(missing)}\n"
                f"header ที่ make_review_sheet.py สร้าง: {','.join(REVIEW_SHEET_COLUMNS)}"
            )
        return [{k: (v or "").strip() for k, v in row.items()} for row in reader]


def _parse_verdict(raw: str) -> Verdict:
    lowered = raw.lower()
    if not lowered:
        return Verdict.PENDING
    if lowered in _APPROVED_WORDS:
        return Verdict.APPROVED
    if lowered in _REJECTED_WORDS:
        return Verdict.REJECTED
    raise ValueError(raw)


def parse_review_rows(raw_rows: list[dict[str, str]]) -> list[ReviewRow]:
    """ตรวจรูปแบบทุกแถวแล้วคืน `ReviewRow` — เจอผิดแม้แถวเดียว raise ทั้งไฟล์

    "ผิดรูปแบบ" ไม่รวมแถวที่ยังไม่ได้ตรวจ (`approved` ว่าง) — ใบงานที่ทำไปได้ครึ่งเดียว
    เป็นสถานะปกติของงานนี้ ไม่ใช่ความผิดพลาด · ดู §"แถวไหนถูกข้าม" ใน docstring ของโมดูล
    """
    rows: list[ReviewRow] = []
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

        try:
            verdict = _parse_verdict(raw["approved"])
        except ValueError:
            errors.append(
                f"{prefix}: approved {raw['approved']!r} ไม่รู้จัก — ใช้ได้แค่ ว่าง "
                f"(ยังไม่ตรวจ) · {'/'.join(sorted(_APPROVED_WORDS))} · "
                f"{'/'.join(sorted(_REJECTED_WORDS))}"
            )
            continue

        row = ReviewRow(
            poster_uuid=poster_uuid,
            release_date_text=raw["release_date_text"],
            corrected_text=raw["corrected_text"],
            verdict=verdict,
        )

        if verdict is Verdict.APPROVED and not row.effective_text:
            errors.append(
                f"{prefix}: อนุมัติแล้วแต่ทั้ง release_date_text และ corrected_text ว่าง "
                "— ไม่มีอะไรให้เขียน · ถ้าตรวจแล้วใบนี้ไม่มีวันฉายพิมพ์อยู่ ยังบันทึกไม่ได้ "
                "ในรอบนี้ (ADR-0009 §ผลเสียที่ยอมรับ) ให้ใส่ approved=no แทน"
            )
            continue

        rows.append(row)

    if errors:
        raise PrecheckError(
            f"ใบงานไม่ผ่านการตรวจรูปแบบ {len(errors)} จุด — ไม่ apply อะไรเลยทั้งไฟล์:\n  "
            + "\n  ".join(errors)
        )
    return rows


# --------------------------------------------------------------------------
# วางแผนการเขียน (pure — รับสถานะปัจจุบันเข้ามา ไม่ query เอง)
# --------------------------------------------------------------------------


class Action(str, Enum):
    APPLY = "APPLY"
    SKIP_PENDING = "SKIP_PENDING"  # approved ว่าง — ยังตรวจไม่ถึง
    SKIP_REJECTED = "SKIP_REJECTED"  # คนตรวจแล้วไม่อนุมัติ
    SKIP_NOT_FOUND = "SKIP_NOT_FOUND"  # ไม่มีใบนี้ใน DB
    SKIP_ALREADY_SET = "SKIP_ALREADY_SET"  # ปลายทางไม่ใช่ NULL — D6 ห้ามทับ


@dataclass(frozen=True)
class PlannedWrite:
    row: ReviewRow
    action: Action
    # ค่าที่จะเขียนลง `release_date` — มีค่าเฉพาะตอน parser คืน PARSED เท่านั้น
    release_date: date | None
    parse_status: str
    current_value: str | None


def plan_writes(
    rows: list[ReviewRow],
    current: dict[uuid.UUID, str | None],
) -> list[PlannedWrite]:
    """แปลงแถวใบงาน + สถานะปัจจุบันของ DB เป็นแผนการเขียน

    `current` = {poster_id: ค่าปัจจุบันของ release_date_text} · ใบที่ไม่มีใน dict
    ถือว่าไม่มีในฐานข้อมูล

    pure function — ไม่ query ไม่เขียน ไม่แตะเวลาปัจจุบัน เพื่อให้ test ครอบได้ครบ
    ทุกสาขาโดยไม่ต้องมี DB
    """
    # import ที่นี่เพื่อให้ฟังก์ชัน pure ส่วนบนของไฟล์ import ได้โดยไม่ต้องมี env ครบ
    from app.core.release_date import ReleaseDateParseStatus, parse_release_date_text

    plans: list[PlannedWrite] = []
    for row in rows:
        # parse จากข้อความที่จะเขียนจริงเสมอ (corrected_text ชนะ) — ไม่เชื่อคอลัมน์
        # parsed_date ในใบงาน เพราะ D4 บอกว่า writer เดียวคือ parser ตัวนี้
        parsed = parse_release_date_text(row.effective_text)
        release_date = (
            parsed.value if parsed.status is ReleaseDateParseStatus.PARSED else None
        )
        current_value: str | None = None

        if row.verdict is Verdict.PENDING:
            action = Action.SKIP_PENDING
        elif row.verdict is Verdict.REJECTED:
            action = Action.SKIP_REJECTED
        elif row.poster_uuid not in current:
            action = Action.SKIP_NOT_FOUND
        elif current[row.poster_uuid] is not None:
            # ADR-0010 D6 — ไม่มีโหมดเขียนทับ ไม่มี flag ให้ override
            action = Action.SKIP_ALREADY_SET
            current_value = current[row.poster_uuid]
        else:
            action = Action.APPLY

        plans.append(
            PlannedWrite(
                row=row,
                action=action,
                release_date=release_date,
                parse_status=parsed.status.value,
                current_value=current_value,
            )
        )
    return plans


# --------------------------------------------------------------------------
# รายงาน
# --------------------------------------------------------------------------


def _report(plans: list[PlannedWrite], target_label: str, committed: bool) -> None:
    by_action = Counter(p.action for p in plans)
    applying = [p for p in plans if p.action is Action.APPLY]
    by_status = Counter(p.parse_status for p in applying)

    print()
    print("=" * 72)
    print(f"ปลายทาง : {target_label}")
    print(f"แถวในใบงาน : {len(plans)}")
    print()
    print(f"  จะเขียน (APPLY)          : {by_action[Action.APPLY]}")
    print(f"  ข้าม — ยังไม่ได้ตรวจ       : {by_action[Action.SKIP_PENDING]}")
    print(f"  ข้าม — ตรวจแล้วไม่อนุมัติ   : {by_action[Action.SKIP_REJECTED]}")
    print(f"  ข้าม — ไม่มีใบใน DB       : {by_action[Action.SKIP_NOT_FOUND]}")
    print(
        f"  ข้าม — มีค่าอยู่แล้ว        : {by_action[Action.SKIP_ALREADY_SET]}"
        "  (ADR-0010 D6 ไม่มีโหมดเขียนทับ)"
    )

    if applying:
        corrected = sum(1 for p in applying if p.row.was_corrected)
        derived = by_status.get("PARSED", 0)
        text_only = len(applying) - derived
        print()
        print(f"  ในนั้นเป็นค่าที่คนแก้เอง (corrected_text) : {corrected}")
        print()
        print("ในแถวที่จะเขียน — ผลของ parser (ADR-0009 D13 ข้อ 2 writer เดียว):")
        print(f"  ได้ release_date เป็น DATE : {derived}")
        print(f"  🔴 เก็บได้แค่ข้อความ ต้องกลับมาเติมวัน/เดือน/ปีด้วยมือ : {text_only}")
        for status, count in sorted(by_status.items()):
            if status != "PARSED":
                print(f"       {status:12} {count}")

    print()
    print("ไม่แตะ needs_review และ status เลยสักแถว (ADR-0010 D2 · poster-database §3)")
    if not committed:
        print()
        print("DRY-RUN — ไม่ได้เขียนอะไรลง database (ใส่ --commit เพื่อเขียนจริง)")
    print("=" * 72)


# --------------------------------------------------------------------------
# ตัวรัน
# --------------------------------------------------------------------------


async def run(args: argparse.Namespace, target_label: str) -> int:
    from sqlalchemy import select

    from app.core.database import async_session_maker
    from app.models.poster import Poster
    from app.models.poster_attribute_review import PosterAttributeReview

    rows = parse_review_rows(read_review_sheet(args.file))
    if not rows:
        print("ใบงานไม่มีแถวข้อมูล — ไม่มีอะไรให้ทำ")
        return 0

    poster_ids = [r.poster_uuid for r in rows]

    async with async_session_maker() as session:
        result = await session.execute(
            select(Poster.id, Poster.release_date_text).where(Poster.id.in_(poster_ids))
        )
        current = {row_id: text for row_id, text in result.all()}

        plans = plan_writes(rows, current)
        _report(plans, target_label, committed=args.commit)

        if not args.commit:
            return 0

        source = args.file.name
        applied = 0
        for plan in plans:
            if plan.action is not Action.APPLY:
                continue
            poster = await session.get(Poster, plan.row.poster_uuid)
            if poster is None:  # pragma: no cover — plan บอกว่ามีแล้ว
                continue
            # เขียนแค่สองคอลัมน์นี้เท่านั้น — ห้ามแตะ needs_review/status (D2)
            poster.release_date_text = plan.row.effective_text
            if plan.release_date is not None:
                poster.release_date = plan.release_date
            session.add(
                PosterAttributeReview(
                    poster_id=plan.row.poster_uuid,
                    field=TARGET_FIELD,
                    value_before=plan.current_value,
                    value_after=plan.row.effective_text,
                    reviewed_by=args.reviewed_by,
                    reviewed_at=args.reviewed_at,
                    source=source,
                )
            )
            applied += 1

        await session.commit()

    print(
        f"\nเขียนจริงแล้ว {applied} แถว · บันทึก audit {applied} แถวลง "
        "poster_attribute_reviews"
    )
    return 0


def _parse_reviewed_at(raw: str) -> datetime:
    """ISO-8601 ที่ **ต้องมี timezone** — ห้ามให้เครื่องเดาแทนคนตรวจ

    ไม่มี default เป็น "เวลาตอนนี้" โดยตั้งใจ: เวลาที่คนตรวจกับเวลาที่รันสคริปต์
    เป็นคนละเวลากันได้มาก (ตรวจวันนี้ apply อาทิตย์หน้า) การเดาให้คือการกรอก
    ข้อมูลแทนคนซึ่งเป็นสิ่งเดียวกับที่ ADR-0009 D2 ห้าม
    """
    try:
        value = datetime.fromisoformat(raw)
    except ValueError:
        raise PrecheckError(f"--reviewed-at {raw!r} ไม่ใช่ ISO-8601") from None
    if value.tzinfo is None:
        raise PrecheckError(
            f"--reviewed-at {raw!r} ไม่มี timezone — ต้องระบุเอง เช่น "
            "2026-08-04T13:30:00+07:00"
        )
    return value


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
        "--target",
        choices=("dev", "sit"),
        default="dev",
        help="ปลายทาง — ADR-0010 D7 อนุญาตแค่ dev กับ SIT ในรอบนี้ "
        "(production ไม่มีให้เลือกโดยตั้งใจ)",
    )
    parser.add_argument(
        "--file",
        type=Path,
        default=DEFAULT_SIGNOFF_CSV,
        help=f"ใบงาน (default: {DEFAULT_SIGNOFF_CSV.name})",
    )
    parser.add_argument(
        "--reviewed-by",
        help="ชื่อคนที่ตรวจใบงานรอบนี้ — บังคับเมื่อ --commit (ADR-0010 D1)",
    )
    parser.add_argument(
        "--reviewed-at",
        help="เวลาที่ตรวจ ISO-8601 พร้อม timezone — บังคับเมื่อ --commit",
    )
    args = parser.parse_args()

    if args.commit:
        # D1 — ต้องมีชื่อคนและเวลาที่ตรวจเสมอ ไม่มีค่า default ให้เดา
        if not args.reviewed_by:
            parser.error("--commit ต้องระบุ --reviewed-by ด้วย (ADR-0010 D1)")
        if not args.reviewed_at:
            parser.error("--commit ต้องระบุ --reviewed-at ด้วย (ADR-0010 D1)")
        try:
            args.reviewed_at = _parse_reviewed_at(args.reviewed_at)
        except PrecheckError as exc:
            parser.error(str(exc))

    _load_env(args.target)
    database_url = os.environ.get("DATABASE_URL", "")
    if not database_url:
        print("ไม่พบ DATABASE_URL", file=sys.stderr)
        return 1

    try:
        target_label = assert_target_database(database_url, args.target)
    except PrecheckError as exc:
        print(f"precheck ไม่ผ่าน: {exc}", file=sys.stderr)
        return 1

    # ให้ `import app.*` ทำงานได้ตอนรันเป็นสคริปต์ตรง ๆ (เหมือน seed_posters.py:707)
    # — ตอนรันผ่าน pytest ไม่ต้องใช้เพราะ rootdir อยู่ใน sys.path อยู่แล้ว
    sys.path.insert(0, str(REPO_ROOT))
    import asyncio

    try:
        return asyncio.run(run(args, target_label))
    except PrecheckError as exc:
        print(f"precheck ไม่ผ่าน: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
