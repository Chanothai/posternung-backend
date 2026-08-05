"""สร้าง **ใบงานเปล่า** ให้คนตัดสิน `is_poster` / `needs_review` ของทุกใบก่อน seed

    python3 scripts/seed/make_triage_sheet.py
    python3 scripts/seed/make_triage_sheet.py --out /path/to/sheet.csv

🔴 **สคริปต์นี้ไม่ใช่ตัวตัดสิน และห้ามทำให้เป็น** — คอลัมน์ `is_poster` กับ
`needs_review` ถูกเขียนเป็นค่าว่างเสมอ ไม่มี flag ให้เติมอัตโนมัติ ถ้าเครื่องกรอกสอง
คอลัมน์นี้ให้ ก็คือเครื่องตัดสินงานของเครื่องเอง ซึ่งขัด ADR-0009 D6 (การยืนยันต้องมา
จากคน) — หลักและรูปแบบเดียวกับ `make_review_sheet.py` ของ ADR-0010

**ทำไมต้องเป็นไฟล์ใหม่ ไม่ใช่กรอกลง `posters-seed-v2.csv` ตรง ๆ:**
ไฟล์นั้นเป็น *derived data* ที่ `prepare_seed.py` เขียนทับทั้งไฟล์ทุกครั้งที่รัน และ
`.gitignore` กัน `scripts/seed/*.csv` ไว้ทั้งหมด (repo เป็น public) → ไม่มี backup ใน
git เลย ค่าที่คนกรอกในไฟล์นั้นจึงหายแบบกู้ไม่ได้ทันทีที่มีคนรัน generator ซ้ำ
· เป็นเหตุผลเดียวกับ ADR-0010 OD-5 ที่ห้ามเติมคอลัมน์เซ็นรับลงใน `ai-suggestions.csv`

**hint_* คือหลักฐาน ไม่ใช่คำตอบ** — `hint_is_poster` มาจาก regex `poster|โปสเตอร์`
บนชื่อสินค้า TikTok และ `hint_reasons` คือเหตุผล 6 ข้อของ `prepare_seed.py` ที่บันทึกไว้
ใน `review-needed.csv` · ทั้งคู่ผิดได้จริง (ยืนยันแล้ว: 3 ใบที่ `hint_is_poster=0` เป็น
โปสเตอร์ทั้งหมด ผู้ขายแค่ไม่ได้พิมพ์คำว่า poster ในชื่อ) คนจึงต้องตัดสินเอง ไม่ใช่ลอก

อ่าน `posters-seed-v2.csv` + `review-needed.csv` อย่างเดียว ไม่เขียนทับทั้งคู่
"""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

SEED_DIR = Path(__file__).resolve().parent
REPO_ROOT = SEED_DIR.parents[1]
sys.path.insert(0, str(REPO_ROOT))

from scripts.seed.prepare_seed import NOT_A_POSTER_REASON  # noqa: E402
from scripts.seed.seed_posters import (  # noqa: E402
    DEFAULT_TRIAGE_CSV,
    TRIAGE_SHEET_COLUMNS,
)

POSTERS_CSV = SEED_DIR / "posters-seed-v2.csv"
REVIEW_CSV = SEED_DIR / "review-needed.csv"


def build_sheet_rows(
    posters: list[dict[str, str]], review: list[dict[str, str]]
) -> list[dict[str, str]]:
    """แปลง seed CSV + review CSV → แถวใบงาน (pure — ไม่แตะไฟล์)

    `is_poster` และ `needs_review` เป็นค่าว่างเสมอ ดู docstring ของโมดูล

    `hint_is_poster` ย้อนกลับมาจาก `review-needed.csv` ได้อย่างครบถ้วนเพราะ
    `prepare_seed.py` เขียนเหตุผล `NOT_A_POSTER_REASON` ลงทุกครั้งที่ regex ไม่เจอ
    → ใบที่ไม่มีเหตุผลนั้นแปลว่า regex เจอแน่นอน ไม่มีเคสกำกวม
    """
    reasons_by_uuid = {r["poster_uuid"]: r.get("reasons", "") for r in review}

    rows: list[dict[str, str]] = []
    seen: set[str] = set()
    for poster in posters:
        poster_uuid = poster["poster_uuid"]
        # 🔴 1 แถว = 1 *ใบ* ไม่ใช่ 1 แถวของ CSV — posters-seed-v2.csv มี poster_uuid
        # ซ้ำได้จริง (ยืนยันแล้ว: 118 แถว = 117 ใบ) คนตัดสินว่า "ใบนี้เป็นโปสเตอร์ไหม"
        # ครั้งเดียวพอ · การเลือกว่าจะเอาแถวไหนของราคาที่ต่างกันเป็นคนละคำถาม และ
        # seed_posters.py มีนโยบายของตัวเองอยู่แล้ว (--dedupe-poster-id)
        # ไม่ทิ้งเงียบ — main() รายงานจำนวนที่ยุบเสมอ
        if poster_uuid in seen:
            continue
        seen.add(poster_uuid)
        reasons = reasons_by_uuid.get(poster_uuid, "")
        rows.append(
            {
                "poster_uuid": poster_uuid,
                "title": poster["title"],
                "original_name": poster["original_name"],
                "quantity": poster["quantity"],
                "price_thb": poster["price_thb"],
                "hint_is_poster": "0" if NOT_A_POSTER_REASON in reasons else "1",
                "hint_reasons": reasons,
                "is_poster": "",
                "needs_review": "",
            }
        )
    # ใบที่ heuristic สะดุดขึ้นก่อน — ถ้าเรียงใบที่ไม่มีอะไรน่าสงสัยไว้บน คนจะไล่ผ่าน
    # แถวที่ไม่ต้องคิดหลายสิบแถวก่อนเจอของจริง (เหตุผลเดียวกับ STATUS_ORDER ของ
    # make_review_sheet.py) · ในกลุ่มเดียวกันเรียงใบที่ regex สงสัยขึ้นก่อนอีกชั้น
    rows.sort(
        key=lambda r: (
            not r["hint_reasons"],
            r["hint_is_poster"] == "1",
            r["poster_uuid"],
        )
    )
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--posters",
        type=Path,
        default=POSTERS_CSV,
        help=f"seed CSV (อ่านอย่างเดียว · default: {POSTERS_CSV.name})",
    )
    parser.add_argument(
        "--review",
        type=Path,
        default=REVIEW_CSV,
        help=f"เหตุผลจาก heuristic (อ่านอย่างเดียว · default: {REVIEW_CSV.name})",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=DEFAULT_TRIAGE_CSV,
        help=f"ใบงานที่จะสร้าง (default: {DEFAULT_TRIAGE_CSV.name})",
    )
    args = parser.parse_args()

    for path in (args.posters, args.review):
        if not path.is_file():
            print(f"ไม่พบไฟล์ {path}", file=sys.stderr)
            return 1
    if args.out.exists():
        # กันเขียนทับใบงานที่คนกรอกไปแล้วครึ่งทาง — งานที่หายไปกู้ไม่ได้
        # (CSV ในโฟลเดอร์นี้ไม่อยู่ใน git เลย ดู .gitignore:101)
        print(
            f"{args.out} มีอยู่แล้ว — ลบหรือเปลี่ยนชื่อก่อน (กันทับใบงานที่กรอกไปแล้ว)",
            file=sys.stderr,
        )
        return 1

    def _read(path: Path) -> list[dict[str, str]]:
        with path.open(newline="", encoding="utf-8-sig") as fh:
            return [
                {k: (v or "").strip() for k, v in row.items()}
                for row in csv.DictReader(fh)
            ]

    posters = _read(args.posters)
    rows = build_sheet_rows(posters, _read(args.review))
    with args.out.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(TRIAGE_SHEET_COLUMNS))
        writer.writeheader()
        writer.writerows(rows)

    collapsed = len(posters) - len(rows)
    flagged = sum(1 for r in rows if r["hint_reasons"])
    not_poster = sum(1 for r in rows if r["hint_is_poster"] == "0")
    print(f"เขียน {args.out} — {len(rows)} แถว\n")
    print(f"  heuristic สะดุด          {flagged:>4}  (ขึ้นก่อนในไฟล์)")
    print(f"  regex ไม่เจอคำว่า poster  {not_poster:>4}  🔴 เปิดดูรูปก่อนตัดสิน")
    print(f"  ไม่มีอะไรน่าสงสัย        {len(rows) - flagged:>4}")
    if collapsed:
        # ไม่ทิ้งเงียบ — คนอ่านต้องรู้ว่าจำนวนแถวไม่เท่ากับจำนวนแถวใน seed CSV
        print(
            f"\n  ⚠️  ยุบ poster_uuid ซ้ำ {collapsed} แถว จาก {len(posters)} แถวใน "
            f"{args.posters.name}\n"
            "      (การเลือกว่าจะเอาแถวราคาไหนเป็นคนละคำถาม — seed_posters.py "
            "มี --dedupe-poster-id ของตัวเอง)"
        )
    print(
        "\nขั้นต่อไป: กรอก is_poster / needs_review ให้ครบทุกแถว (ว่าง = seed ไม่ผ่าน)"
    )
    print("จากนั้น python3 scripts/seed/seed_posters.py  (dry-run ก่อนเสมอ)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
