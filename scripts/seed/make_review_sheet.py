"""สร้าง **ใบงานเปล่า** ให้คนตรวจ `release_date` จาก `ai-suggestions.csv` — ADR-0010

    ./venv/bin/python scripts/seed/make_review_sheet.py
    ./venv/bin/python scripts/seed/make_review_sheet.py --out /path/to/sheet.csv

🔴 **สคริปต์นี้ไม่ใช่ตัวเซ็นรับ และห้ามทำให้เป็น** — คอลัมน์ `approved` กับ
`corrected_text` ถูกเขียนเป็นค่าว่างเสมอ ไม่มี flag ให้เติมอัตโนมัติ ถ้าเครื่องกรอก
สองคอลัมน์นี้ให้ ก็คือเครื่องเซ็นรับงานของเครื่องเอง ซึ่งขัด ADR-0009 D6 (การยืนยัน
ต้องมาจากคน) และ ADR-0010 D5 (ผลของ AI คือหลักฐานดิบ คนละชั้นกับคำยืนยัน)

สิ่งที่สคริปต์นี้ทำคือ **ย้ายภาระการเปิดไฟล์มาเทียบกันเอง** ออกจากคนตรวจ: เอาค่าที่ AI
เสนอ ผลของ parser หลักฐาน และลิงก์รูป มาไว้ในแถวเดียวกัน เพื่อให้ตรวจได้ว่า *ทั้ง*
ข้อความถูก **และ** parser แปลงถูก — ADR-0009 D13 แยก observed (`release_date_text`)
ออกจาก derived (`release_date`) ถ้าเห็นแค่ตัวใดตัวหนึ่งจะตรวจไม่ครบ

อ่าน `ai-suggestions.csv` อย่างเดียว ไม่เขียนทับ (D5) · เอาเฉพาะแถวที่
`field=release_date` และมีค่า — แถวที่ AI อ่านวันฉายไม่ได้ไม่มีอะไรให้ตรวจ
"""

from __future__ import annotations

import argparse
import csv
import sys
from collections import Counter
from pathlib import Path

SEED_DIR = Path(__file__).resolve().parent
REPO_ROOT = SEED_DIR.parents[1]
sys.path.insert(0, str(REPO_ROOT))

from app.core.release_date import (  # noqa: E402
    _ENGLISH_MONTHS,
    _NUMERIC_MONTH_DAY,
    _THAI_MONTHS,
    _THAI_WEEKDAY_PREFIX,
    ReleaseDateParseStatus,
    parse_release_date_text,
)
from scripts.seed.apply_suggestions import (  # noqa: E402
    DEFAULT_SIGNOFF_CSV,
    REVIEW_SHEET_COLUMNS,
)

AI_SUGGESTIONS_CSV = SEED_DIR / "ai-suggestions.csv"
SOURCE_FIELD = "release_date"

# ลำดับการตรวจ — ตัวที่ต้องใช้วิจารณญาณมากสุดขึ้นก่อน `ok` ไปท้ายสุด
# เหตุผล: ถ้าเรียง ok ไว้บน คนจะไล่ผ่านแถวที่ไม่ต้องคิด 7 แถวก่อนเจอของจริง
STATUS_ORDER = {
    "ambiguous": 0,  # เสี่ยงได้ข้อมูลผิดถ้าเผลอเดา — ต้องเปิดรูปตัดสิน
    "failed": 1,  # parser อ่านไม่ออกเลย
    "no_day_no_year": 2,  # รู้แค่เดือน ต้องเติมสองอย่าง
    "no_day": 3,
    "no_year": 4,
    "ok": 5,
}


def classify(text: str) -> str:
    """แปลงสถานะของ parser เป็นคำที่ใบงานใช้

    `ReleaseDateParseStatus.INCOMPLETE` ถูกแตกเป็น 3 แบบตามว่า *อะไร* ที่ขาด เพราะ
    งานของคนตรวจต่างกันคนละเรื่อง — ถ้าบอกแค่ "ไม่ครบ" คนจะไม่รู้ว่าต้องเติมอะไร

    🔴 `no_day_no_year` (รู้แค่เดือน) จำเป็นต้องแยกออกมา ไม่ใช่ยุบเข้า `no_day` หรือ
    `no_year` — สถานะที่บอกว่า "ขาดแค่วัน" ทั้งที่ปีก็ไม่รู้ จะทำให้คนเติมแค่วันแล้ว
    คิดว่าจบ พอส่งกลับเข้า parser ก็ยังไม่ครบอยู่ดี เสียรอบตรวจฟรี ๆ

    ใช้พจนานุกรมเดือนกับ regex **ตัวเดียวกับ parser จริง** ไม่เขียน logic ใหม่ที่จะ
    เพี้ยนจากกันเมื่อ parser เปลี่ยน
    """
    result = parse_release_date_text(text)
    if result.status is ReleaseDateParseStatus.PARSED:
        return "ok"
    if result.status is ReleaseDateParseStatus.AMBIGUOUS:
        return "ambiguous"
    if result.status is ReleaseDateParseStatus.UNREADABLE:
        return "failed"

    stripped = text.strip()
    # ตัวเลขล้วนสองกลุ่ม (11.19 · 7.15) — รู้วัน/เดือน ขาดปีเสมอ
    if _NUMERIC_MONTH_DAY.match(stripped):
        return "no_year"

    tokens = _THAI_WEEKDAY_PREFIX.sub("", stripped).replace(",", " ").split()
    numbers = [(int(t), len(t)) for t in tokens if t.isdigit()]
    has_month = any(
        _ENGLISH_MONTHS.get(t.lower()) or _THAI_MONTHS.get(t) for t in tokens
    )
    if not has_month:  # pragma: no cover — parser คืน UNREADABLE ไปแล้ว
        return "failed"

    has_year = any(digits == 4 or value > 31 for value, digits in numbers)
    has_day = any(digits != 4 and value <= 31 for value, digits in numbers)
    if has_year and not has_day:
        return "no_day"
    if has_day and not has_year:
        return "no_year"
    return "no_day_no_year"


def build_sheet_rows(suggestions: list[dict[str, str]]) -> list[dict[str, str]]:
    """แปลงแถว `field=release_date` ที่มีค่า → แถวใบงาน (pure — ไม่แตะไฟล์)

    `approved` และ `corrected_text` เป็นค่าว่างเสมอ ดู docstring ของโมดูล
    """
    rows: list[dict[str, str]] = []
    for raw in suggestions:
        if raw.get("field") != SOURCE_FIELD:
            continue
        text = (raw.get("value") or "").strip()
        if not text:
            continue
        parsed = parse_release_date_text(text)
        rows.append(
            {
                "poster_uuid": raw["poster_uuid"],
                "release_date_text": text,
                "parsed_date": parsed.value.isoformat() if parsed.value else "",
                "parse_status": classify(text),
                "evidence": raw.get("evidence", ""),
                "image_url": raw.get("image_url", ""),
                "approved": "",
                "corrected_text": "",
            }
        )
    rows.sort(key=lambda r: (STATUS_ORDER[r["parse_status"]], r["poster_uuid"]))
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--source",
        type=Path,
        default=AI_SUGGESTIONS_CSV,
        help=f"ผลของ AI (อ่านอย่างเดียว · default: {AI_SUGGESTIONS_CSV.name})",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=DEFAULT_SIGNOFF_CSV,
        help=f"ใบงานที่จะสร้าง (default: {DEFAULT_SIGNOFF_CSV.name})",
    )
    args = parser.parse_args()

    if not args.source.is_file():
        print(f"ไม่พบไฟล์ {args.source}", file=sys.stderr)
        return 1
    if args.out.exists():
        # กันเขียนทับใบงานที่คนกรอกไปแล้วครึ่งทาง — งานที่หายไปกู้ไม่ได้
        print(
            f"{args.out} มีอยู่แล้ว — ลบหรือเปลี่ยนชื่อก่อน (กันทับใบงานที่กรอกไปแล้ว)",
            file=sys.stderr,
        )
        return 1

    with args.source.open(newline="", encoding="utf-8-sig") as fh:
        suggestions = [
            {k: (v or "").strip() for k, v in row.items()} for row in csv.DictReader(fh)
        ]

    rows = build_sheet_rows(suggestions)
    with args.out.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(REVIEW_SHEET_COLUMNS))
        writer.writeheader()
        writer.writerows(rows)

    counts = Counter(r["parse_status"] for r in rows)
    print(f"เขียน {args.out} — {len(rows)} แถว\n")
    for status in sorted(counts, key=lambda s: STATUS_ORDER[s]):
        print(f"  {status:16} {counts[status]:>3}")
    print(f"\n  {'รวมที่ไม่ใช่ ok':16} {len(rows) - counts['ok']:>3}")
    print("\nขั้นต่อไป: เปิดรูปตรวจแล้วกรอก approved / corrected_text เอง")
    print(
        "จากนั้น ./venv/bin/python scripts/seed/apply_suggestions.py  (dry-run ก่อนเสมอ)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
