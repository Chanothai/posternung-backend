#!/usr/bin/env python3
"""ประตูเดียวของเส้นทางข้อมูลโปสเตอร์ — INF-26

    ./venv/bin/python scripts/seed/poster_ops.py --help
    ./venv/bin/python scripts/seed/poster_ops.py manual sheet
    ./venv/bin/python scripts/seed/poster_ops.py manual apply --commit --target sit

🔴 **ไฟล์นี้ไม่ใช่การยุบเส้น** — `ADR-0015` **D1** เขียนหัวข้อไว้ตรงตัวว่า *"เส้นทางเขียน
`posters` มี 5 เส้น คนละแหล่ง คนละกฎ **ห้ามยุบรวม**"* (วันนี้ 7 เส้น หลัง ADR-0024 ·
ADR-0025) เพราะการยัดสองรูปแบบงานลงสคริปต์เดียวทำให้ *ที่มาของค่าใน
`poster_attribute_reviews` แยกไม่ออก* ว่าค่าไหนคนพิมพ์เอง ค่าไหนคนแค่กดรับของ AI
· สิ่งที่ไฟล์นี้ทำคือ **เปลี่ยนชื่อคำสั่งที่ต้องจำจาก 13 ตัวให้เหลือรูปเดียว** — เจ็ดเส้น
ยังเป็นเจ็ดไฟล์ คนละ process คนละกฎ เหมือนเดิมทุกตัวอักษร

## กฎเดียวที่ไฟล์นี้ต้องรักษา: ห้ามรู้จัก argument ของเส้นไหนเลย

argv ทุกตัวหลัง `<lane> <action>` ถูกส่งต่อ **ทั้งก้อนโดยไม่ตีความ** — ไฟล์นี้จึงไม่มี
`argparse` ของตัวเองสำหรับสิ่งที่เส้นรับ · **เหตุผลไม่ใช่ความขี้เกียจ**: dispatcher ที่
ประกาศ argument เองคือ**แหล่งความจริงที่สอง**ที่ drift ทันทีที่เส้นใดเพิ่ม flag แล้วไม่มี
อะไรฟ้อง — โรคเดียวกับ `HUMAN_COLUMNS` ของ `make_split_sheet.py` ที่ PR #62 เพิ่งแก้
ด้วยการให้มันประกอบจากต้นทางจริงแทนการก๊อป

ผลพลอยได้ที่ตั้งใจ: `poster_ops.py manual apply --help` แสดง help **ของ `manual_entry.py`
เอง** ไม่ใช่ของไฟล์นี้ ⇒ เอกสาร argument มีที่อยู่ที่เดียวตลอดไป

## ทำไมเรียกเป็น subprocess ไม่ใช่ import แล้ว call main()

สคริปต์หลายตัวทำงานตั้งแต่ตอน import (โหลด `.env` · ด่าน dev/sit · `Settings()`) —
`seed_posters.py` เขียนไว้ตรง ๆ ว่า *"env + dev guard ทำก่อน import app.*"* การ import
เข้ามาในโปรเซสเดียวกันจึงเปลี่ยนลำดับที่ด่านพวกนั้นทำงาน · subprocess ทำให้
**พฤติกรรมของทุกเส้นเท่าเดิมเป๊ะ** ไม่ใช่ "น่าจะเท่าเดิม" — ราคาที่จ่ายคือโปรเซสละ ~0.1 วิ
ซึ่งไม่มีความหมายกับงานที่รันวันละไม่กี่ครั้ง

## สิ่งที่ **จงใจไม่อยู่** ในแผนที่นี้ (ดู `EXCLUDED`)

`ai_suggest.py` เป็นตัวสำคัญที่สุดในสามตัวนั้น — มันรันด้วย **venv คนละตัว**
(`scripts/seed/.venv/bin/python` ตาม README §เส้นที่ 2) ถ้าไฟล์นี้เรียกมันด้วย
interpreter เดียวกับตัวเอง มันจะรันผิด venv **เงียบ ๆ** จนกว่าจะไปตายที่ import
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

SEED_DIR = Path(__file__).resolve().parent


class Lane:
    """หนึ่งเส้นทางเขียน `posters` — ชื่อไฟล์เท่านั้น ไม่มีความรู้เรื่อง argument ของมัน"""

    def __init__(self, number: int, summary: str, apply: str, sheet: str | None = None):
        self.number = number
        self.summary = summary
        self.apply = apply
        self.sheet = sheet

    @property
    def scripts(self) -> dict[str, str]:
        actions = {"apply": self.apply}
        if self.sheet is not None:
            actions["sheet"] = self.sheet
        return actions


# เรียงตามหมายเลขเส้นใน `scripts/seed/README.md` §5 — ชื่อ lane สั้นกว่าชื่อไฟล์โดยตั้งใจ
# เพราะสิ่งที่คนจำไม่ได้คือ *ชื่อไฟล์* ไม่ใช่ *ว่ามีเส้นอะไรบ้าง*
LANES: dict[str, Lane] = {
    "seed": Lane(
        1,
        "ข้อมูลตั้งต้นจาก TikTok export (INSERT ครั้งแรก)",
        apply="seed_posters.py",
        sheet="make_triage_sheet.py",
    ),
    "suggest": Lane(
        2,
        "AI เสนอ คนเซ็นรับ",
        apply="apply_suggestions.py",
        sheet="make_review_sheet.py",
    ),
    "manual": Lane(
        3,
        "คนดูของจริงแล้วพิมพ์",
        apply="manual_entry.py",
        sheet="make_manual_sheet.py",
    ),
    "reference": Lane(
        4,
        "คนเปิดเว็บอ้างอิงแล้วแปะลิงก์",
        apply="reference_entry.py",
        sheet="make_reference_sheet.py",
    ),
    "correction": Lane(
        5,
        "คนตรวจซ้ำแล้วพบว่าค่าที่อยู่ในระบบผิด (เส้นเดียวที่ทับค่าเดิม)",
        apply="correction_entry.py",
        sheet="make_correction_sheet.py",
    ),
    "split": Lane(
        6,
        "แตกแถวพ่อออกเป็นแถวลูกใหม่",
        apply="split_entry.py",
        sheet="make_split_sheet.py",
    ),
    "sold": Lane(
        7,
        "บันทึกการขายนอกระบบ (ไม่มีใบงาน — argument ต่อใบ)",
        apply="sold_entry.py",
    ),
}

# 🔴 สคริปต์ที่ *มีอยู่จริง* แต่จงใจไม่ให้เรียกผ่านประตูนี้ — เหตุผลต่อตัว ไม่ใช่รายชื่อลอย ๆ
# เทส closed-world บังคับให้ทุกไฟล์ใน `scripts/seed/*.py` ต้องอยู่ในแผนที่หรืออยู่ที่นี่
# อย่างใดอย่างหนึ่ง ⇒ เส้นที่ 8 ที่เพิ่มวันหน้าทำให้เทสแดง ไม่ใช่หายเงียบ
EXCLUDED: dict[str, str] = {
    "_shared.py": "โมดูลกลาง ไม่ใช่สคริปต์ที่คนเรียก",
    "poster_ops.py": "ตัวมันเอง",
    "ai_suggest.py": (
        "รันด้วย venv คนละตัว (scripts/seed/.venv/bin/python — README §เส้นที่ 2) "
        "ถ้าเรียกจากที่นี่จะได้ interpreter ผิดตัวแบบเงียบ ๆ"
    ),
    "prepare_seed.py": (
        "import ครั้งเดียวจาก TikTok — input posters-seed.csv / images-manifest.csv "
        "ไม่มีในเครื่องแล้ว (ติด .gitignore) รันวันนี้ไม่ผ่านตั้งแต่เปิดไฟล์"
    ),
    "migrate_to_r2.py": (
        "อัปโหลดรูปครั้งเดียวขึ้น R2 — input images-manifest.csv ไม่มีในเครื่องแล้ว "
        "เหมือน prepare_seed.py"
    ),
}

# 🔴 ห้ามเขียนชื่อ flag --reviewed-at แบบมีอัญประกาศคู่ครอบในไฟล์นี้ **โดยเด็ดขาด** —
# tests/unit/test_seed_lane_shared_rules.py::test_every_script_that_accepts_reviewed_at_is_in_LANES
# สแกนหารูปนั้นในทุกไฟล์ .py ของโฟลเดอร์นี้เพื่อจับ "เส้นใหม่ที่รับ flag นั้นแต่ลืมต่อ
# รายชื่อ LANES" · ไฟล์นี้ไม่ใช่เส้น มันไม่รู้จัก flag ไหนเลย (ดูหัวข้อกฎเดียวข้างบน)
# การไม่มี literal นั้นจึงเป็น **ความตั้งใจที่ต้องรักษาไว้** ไม่ใช่เรื่องบังเอิญ


def _usage() -> str:
    lines = [
        "ประตูเดียวของเส้นทางข้อมูลโปสเตอร์ (INF-26)",
        "",
        "    poster_ops.py <lane> <action> [argument ของเส้นนั้น ...]",
        "",
        "เจ็ดเส้นทางเขียน posters (README.md §5 · ADR-0015 D1 — คนละแหล่ง คนละกฎ):",
        "",
    ]
    for name, lane in LANES.items():
        actions = " · ".join(
            f"{action} → {script}" for action, script in sorted(lane.scripts.items())
        )
        lines.append(f"  {name:<11} เส้นที่ {lane.number} — {lane.summary}")
        lines.append(f"  {'':<11} {actions}")
    lines += [
        "",
        "argument ทั้งหมดหลัง <action> ถูกส่งต่อให้สคริปต์นั้นตรง ๆ ไม่ถูกตีความที่นี่",
        "อยากเห็น argument ของเส้นไหน สั่ง: poster_ops.py <lane> <action> --help",
        "",
        "สคริปต์ที่ต้องเรียกตรง เรียกผ่านประตูนี้ไม่ได้:",
    ]
    for filename, reason in EXCLUDED.items():
        if filename in ("_shared.py", "poster_ops.py"):
            continue
        lines.append(f"  {filename:<20} {reason}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)

    if not args or args[0] in ("-h", "--help", "help"):
        print(_usage())
        return 0

    lane_name, rest = args[0], args[1:]
    lane = LANES.get(lane_name)
    if lane is None:
        print(
            f"ไม่รู้จักเส้น {lane_name!r} — เลือกจาก: {' · '.join(LANES)}\n"
            "ดูทั้งหมดด้วย poster_ops.py --help",
            file=sys.stderr,
        )
        return 2

    if not rest:
        print(
            f"เส้น {lane_name!r} ต้องระบุ action ด้วย — "
            f"เลือกจาก: {' · '.join(sorted(lane.scripts))}",
            file=sys.stderr,
        )
        return 2

    action, passthrough = rest[0], rest[1:]
    script = lane.scripts.get(action)
    if script is None:
        available = " · ".join(sorted(lane.scripts))
        extra = (
            ""
            if lane.sheet is not None
            else f" (เส้นที่ {lane.number} ไม่มีใบงาน CSV — README §เส้นที่ {lane.number})"
        )
        print(
            f"เส้น {lane_name!r} ไม่มี action {action!r} — เลือกจาก: {available}{extra}",
            file=sys.stderr,
        )
        return 2

    # ส่งต่อทั้งก้อน · cwd/env ไม่ถูกแตะเลย เพื่อให้ด่านของแต่ละเส้นเห็นสภาพเดียวกับ
    # ตอนถูกเรียกตรง (ด่าน --target sit เทียบกับ .env.sit ที่ path สัมพันธ์กับ cwd)
    completed = subprocess.run(  # noqa: S603
        [sys.executable, str(SEED_DIR / script), *passthrough],
        check=False,
    )
    return completed.returncode


if __name__ == "__main__":
    raise SystemExit(main())
