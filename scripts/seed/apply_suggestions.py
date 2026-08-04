"""นำค่าที่ **คนตรวจแล้ว** จากไฟล์เซ็นรับเข้า `posters` — ADR-0010 (INF-08)

    python3 scripts/seed/apply_suggestions.py                      # dry-run (default)
    python3 scripts/seed/apply_suggestions.py --commit             # เขียนจริงลง dev
    python3 scripts/seed/apply_suggestions.py --commit --target sit

สคริปต์นี้คือ **เส้นทาง UPDATE เส้นแรกของโปรเจกต์** — ทุกอย่างก่อนหน้านี้เป็น INSERT
ที่ `on_conflict_do_nothing()` เท่านั้น กฎทุกข้อข้างล่างมาจาก ADR-0010 §Decision ตรง ๆ
ไม่ใช่ดุลพินิจของคนเขียนสคริปต์:

* **D1** — "คนที่ระบุตัวได้" ใน Phase 1 = ชื่อที่อยู่ใน **ข้อมูล** (`reviewed_by` ในไฟล์
  เซ็นรับ) ไม่ใช่ในระบบสิทธิ์ · เป็นสคริปต์ที่ operator รันเอง **ไม่ใช่ endpoint**
  เพราะ admin write endpoint ชน guard `admin catalog governance (EPIC 7)` = Phase 2
  🔴 `reviewed_by` คือการ **อ้างชื่อ ไม่ใช่การพิสูจน์ตัวตน** — ไม่มี auth ไม่มี signature
* **D2** — **ห้ามแตะ `needs_review`** ไม่ว่ากรณีใด (และห้ามแตะ `status` ตาม
  `poster-database` §3) · allowlist มีฟิลด์เดียว การพลิกธงระดับแถวคือการอ้างเกินหลักฐาน
* **D3** — ทุกการเขียนบันทึกลง `poster_attribute_reviews` หนึ่งแถว
* **D4** — allowlist = `release_date_text` **เท่านั้น** · `release_date` เขียนได้เฉพาะค่า
  ที่ได้จาก `parse_release_date_text()` (ADR-0009 D13 ข้อ 2 — writer เดียว)
  **สคริปต์นี้ห้ามคำนวณวันที่เอง**
* **D5** — อ่านจาก **ไฟล์เซ็นรับที่แยกต่างหาก** ห้ามอ่าน/เขียน `ai-suggestions.csv`
  ซึ่งเป็นหลักฐานดิบของ AI
* **D6** — เขียนเฉพาะแถวที่คอลัมน์ปลายทางเป็น `NULL` · **ไม่มีโหมดเขียนทับ** ทำให้
  สคริปต์ idempotent โดยโครงสร้าง รันซ้ำไม่ลบงานที่คนแก้ไปแล้ว
* **D7** — dry-run เป็น default · ต้อง `--commit` ถึงเขียนจริง · dev เป็นค่าตั้งต้น
  SIT ต้องระบุ `--target sit` · **production ไม่มีทางเลือกให้เลือกเลย**

## รูปแบบไฟล์เซ็นรับ (D5)

CSV header: `poster_uuid,field,value,reviewed_by,reviewed_at`

`reviewed_at` เป็น ISO-8601 ที่มี timezone (เช่น `2026-08-04T13:30:00+07:00`) —
บังคับให้มี tz เพราะคอลัมน์ปลายทางเป็น `TIMESTAMPTZ` ถ้าปล่อยให้ไม่มีจะกลายเป็นการ
เดา timezone ของคนตรวจ ซึ่งเป็นการอ้างแทนคนแบบเดียวกับที่ ADR-0009 D2 ห้าม

**แถวไหนผิดกติกา = ทั้งไฟล์ไม่ถูก apply** (fail-closed) ไม่ใช่ข้ามเฉพาะแถวนั้น —
ไฟล์ที่มีฟิลด์นอก allowlist หรือ `reviewed_by` ว่าง แปลว่าคนทำไฟล์เข้าใจกติกาไม่ตรงกัน
การ apply บางส่วนจะทำให้ตามยากว่าอะไรเข้าไปแล้วบ้าง
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

SIGNOFF_COLUMNS = ("poster_uuid", "field", "value", "reviewed_by", "reviewed_at")

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
# อ่าน + ตรวจไฟล์เซ็นรับ (pure — ไม่แตะ DB)
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class SignoffRow:
    """หนึ่งแถวของไฟล์เซ็นรับที่ผ่านการตรวจรูปแบบแล้ว."""

    poster_uuid: uuid.UUID
    field: str
    value: str
    reviewed_by: str
    reviewed_at: datetime


def read_signoff_csv(path: Path) -> list[dict[str, str]]:
    if not path.is_file():
        raise PrecheckError(
            f"ไม่พบไฟล์เซ็นรับ {path}\n"
            "ไฟล์นี้เป็นคนละไฟล์กับ ai-suggestions.csv โดยตั้งใจ (ADR-0010 D5) — "
            "ต้องสร้างจากการตรวจของคน ไม่ใช่ผลของ AI ตรง ๆ"
        )
    with path.open(newline="", encoding="utf-8-sig") as fh:
        reader = csv.DictReader(fh)
        missing = [c for c in SIGNOFF_COLUMNS if c not in (reader.fieldnames or [])]
        if missing:
            raise PrecheckError(
                f"ไฟล์เซ็นรับขาดคอลัมน์: {', '.join(missing)}\n"
                f"header ที่ต้องมี: {','.join(SIGNOFF_COLUMNS)}"
            )
        return [{k: (v or "").strip() for k, v in row.items()} for row in reader]


def parse_signoff_rows(raw_rows: list[dict[str, str]]) -> list[SignoffRow]:
    """ตรวจทุกแถวแล้วคืน `SignoffRow` — เจอผิดแม้แถวเดียว raise ทั้งไฟล์ (fail-closed)

    เหตุผลที่ไม่ข้ามเฉพาะแถวที่ผิด: ไฟล์ที่มีฟิลด์นอก allowlist หรือ `reviewed_by` ว่าง
    แปลว่าคนทำไฟล์เข้าใจกติกาไม่ตรงกัน การ apply บางส่วนจะทำให้ตามยากภายหลังว่าอะไร
    เข้าไปแล้วบ้าง — ยิ่งเป็นเส้นทาง UPDATE เส้นแรกยิ่งต้องชัด
    """
    rows: list[SignoffRow] = []
    errors: list[str] = []
    seen: set[tuple[str, str]] = set()

    for lineno, raw in enumerate(raw_rows, start=2):  # +1 header, +1 นับจาก 1
        prefix = f"บรรทัด {lineno}"

        field = raw["field"]
        if field not in ALLOWED_FIELDS:
            errors.append(
                f"{prefix}: field {field!r} ไม่อยู่ใน allowlist ของ ADR-0010 D4 "
                f"({', '.join(sorted(ALLOWED_FIELDS))})"
            )
            continue

        try:
            poster_uuid = uuid.UUID(raw["poster_uuid"])
        except ValueError:
            errors.append(f"{prefix}: poster_uuid {raw['poster_uuid']!r} ไม่ใช่ UUID")
            continue

        key = (str(poster_uuid), field)
        if key in seen:
            errors.append(f"{prefix}: ซ้ำกับแถวก่อนหน้า (poster_uuid + field เดียวกัน)")
            continue
        seen.add(key)

        value = raw["value"]
        if not value:
            errors.append(
                f"{prefix}: value ว่าง — ถ้าตรวจแล้วใบนี้ไม่มีวันฉายพิมพ์อยู่ ยังบันทึกไม่ได้ "
                "ในรอบนี้ (ADR-0009 §ผลเสียที่ยอมรับ) ให้ตัดแถวออกจากไฟล์แทน"
            )
            continue

        reviewed_by = raw["reviewed_by"]
        if not reviewed_by:
            errors.append(
                f"{prefix}: reviewed_by ว่าง — ADR-0009 D6 ข้อ 3 ต้องมีชื่อคนตรวจ"
            )
            continue

        try:
            reviewed_at = datetime.fromisoformat(raw["reviewed_at"])
        except ValueError:
            errors.append(
                f"{prefix}: reviewed_at {raw['reviewed_at']!r} ไม่ใช่ ISO-8601"
            )
            continue
        if reviewed_at.tzinfo is None:
            errors.append(
                f"{prefix}: reviewed_at {raw['reviewed_at']!r} ไม่มี timezone — "
                "ต้องระบุเอง ห้ามให้เครื่องเดาแทนคนตรวจ"
            )
            continue

        rows.append(
            SignoffRow(
                poster_uuid=poster_uuid,
                field=field,
                value=value,
                reviewed_by=reviewed_by,
                reviewed_at=reviewed_at,
            )
        )

    if errors:
        raise PrecheckError(
            f"ไฟล์เซ็นรับไม่ผ่านการตรวจ {len(errors)} จุด — ไม่ apply อะไรเลยทั้งไฟล์:\n  "
            + "\n  ".join(errors)
        )
    return rows


# --------------------------------------------------------------------------
# วางแผนการเขียน (pure — รับสถานะปัจจุบันเข้ามา ไม่ query เอง)
# --------------------------------------------------------------------------


class Action(str, Enum):
    APPLY = "APPLY"
    SKIP_NOT_FOUND = "SKIP_NOT_FOUND"  # ไม่มีใบนี้ใน DB
    SKIP_ALREADY_SET = "SKIP_ALREADY_SET"  # ปลายทางไม่ใช่ NULL — D6 ห้ามทับ


@dataclass(frozen=True)
class PlannedWrite:
    row: SignoffRow
    action: Action
    # ค่าที่จะเขียนลง `release_date` — มีค่าเฉพาะตอน parser คืน PARSED เท่านั้น
    release_date: date | None
    parse_status: str
    current_value: str | None


def plan_writes(
    rows: list[SignoffRow],
    current: dict[uuid.UUID, str | None],
) -> list[PlannedWrite]:
    """แปลงแถวเซ็นรับ + สถานะปัจจุบันของ DB เป็นแผนการเขียน

    `current` = {poster_id: ค่าปัจจุบันของ release_date_text} · ใบที่ไม่มีใน dict
    ถือว่าไม่มีในฐานข้อมูล

    pure function — ไม่ query ไม่เขียน ไม่แตะเวลาปัจจุบัน เพื่อให้ test ครอบได้ครบ
    ทุกสาขาโดยไม่ต้องมี DB
    """
    # import ที่นี่เพื่อให้ฟังก์ชัน pure ส่วนบนของไฟล์ import ได้โดยไม่ต้องมี env ครบ
    from app.core.release_date import ReleaseDateParseStatus, parse_release_date_text

    plans: list[PlannedWrite] = []
    for row in rows:
        parsed = parse_release_date_text(row.value)
        release_date = (
            parsed.value if parsed.status is ReleaseDateParseStatus.PARSED else None
        )

        if row.poster_uuid not in current:
            action = Action.SKIP_NOT_FOUND
            current_value = None
        elif current[row.poster_uuid] is not None:
            # ADR-0010 D6 — ไม่มีโหมดเขียนทับ ไม่มี flag ให้ override
            action = Action.SKIP_ALREADY_SET
            current_value = current[row.poster_uuid]
        else:
            action = Action.APPLY
            current_value = None

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
    print(f"แถวในไฟล์เซ็นรับ : {len(plans)}")
    print()
    print(f"  จะเขียน (APPLY)        : {by_action[Action.APPLY]}")
    print(f"  ข้าม — ไม่มีใบใน DB     : {by_action[Action.SKIP_NOT_FOUND]}")
    print(
        f"  ข้าม — มีค่าอยู่แล้ว      : {by_action[Action.SKIP_ALREADY_SET]}"
        "  (ADR-0010 D6 ไม่มีโหมดเขียนทับ)"
    )

    if applying:
        derived = by_status.get("PARSED", 0)
        text_only = len(applying) - derived
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

    rows = parse_signoff_rows(read_signoff_csv(args.file))
    if not rows:
        print("ไฟล์เซ็นรับไม่มีแถวข้อมูล — ไม่มีอะไรให้ทำ")
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
            poster.release_date_text = plan.row.value
            if plan.release_date is not None:
                poster.release_date = plan.release_date
            session.add(
                PosterAttributeReview(
                    poster_id=plan.row.poster_uuid,
                    field=plan.row.field,
                    value_before=plan.current_value,
                    value_after=plan.row.value,
                    reviewed_by=plan.row.reviewed_by,
                    reviewed_at=plan.row.reviewed_at,
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
        help=f"ไฟล์เซ็นรับ (default: {DEFAULT_SIGNOFF_CSV.name})",
    )
    args = parser.parse_args()

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
