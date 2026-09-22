"""สร้าง `openapi.json` ที่ root ใหม่จาก FastAPI app — **แหล่งเดียวที่สร้างไฟล์นี้**

ไฟล์ `openapi.json` ถูก `CLAUDE.md` แต่งตั้งว่าเป็น *"สิ่งที่ generate จาก FastAPI =
สะท้อนโค้ดจริง ใช้เทียบ drift กับ contract"* และสกิล `contract-drift-check` §2 ใช้มัน
เป็นฝั่ง "โค้ดจริง" ของการเทียบ · **ถ้ามันค้าง การเทียบ drift จะให้คำตอบผิดโดยไม่มี
อะไรฟ้อง** — คนรันจะเชื่อว่าสองฝั่งตรงกันทั้งที่เทียบกับไฟล์ที่ไม่ใช่โค้ดจริง

เคยเกิดจริง (`docs/BACKLOG.md` **BL-91** · 2026-08-07): ไฟล์ค้างอยู่ที่ชุดค่า
`REFERENCE_MATCHED` · `DISCREPANCY_FOUND` · `UNKNOWN` + `verification_note`
ซึ่งเป็น **ชุดก่อน `a7c31e5f9b04`** คือค้างข้าม migration มา 2 รอบ · แก้ด้วยมือที่
`1e62092` แต่ **กลไกที่ทำให้ไม่ค้างอีกไม่มี** — จนถึงไฟล์นี้

## วิธีใช้

```bash
./venv/bin/python scripts/generate_openapi.py          # เขียนทับ openapi.json
./venv/bin/python scripts/generate_openapi.py --check  # ไม่เขียน · ต่างเมื่อไหร่ exit 1
```

`--check` คือโหมดที่ CI ใช้ (job `test` ของ `.github/workflows/test.yml`) —
**ทำให้ไฟล์ค้างเป็นสิ่งที่ merge ไม่ผ่าน** ไม่ใช่สิ่งที่ต้องมีคนจำได้

🔴 **ไฟล์นี้ไม่ใช่ contract** — `../workspace/docs/api/openapi.yaml` คือ source of
truth · ไฟล์นี้คือ *ภาพสะท้อนของโค้ด* ไว้เอาไปเทียบกับ contract เท่านั้น การแก้
`openapi.json` ด้วยมือให้ตรงกับ contract คือการทำลายเครื่องมือวัด ไม่ใช่การแก้ drift
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
OUTPUT = REPO_ROOT / "openapi.json"
# รันจาก path ไหนก็ได้ — สคริปต์นี้ถูกเรียกทั้งจาก CI (cwd = repo root) และจากคน
# ที่อาจอยู่ที่อื่น · แบบเดียวกับ `scripts/seed/manual_entry.py`
sys.path.insert(0, str(REPO_ROOT))

# ค่า env ที่ `app.core.config` ต้องมีตอน import — ตัวสคริปต์นี้ไม่ต่อ DB และไม่เรียก
# endpoint ใด ๆ มันแค่เดินตาราง route เพื่อประกอบ schema · ค่าพวกนี้จึงเป็น
# **placeholder ล้วน** และตั้งเฉพาะเมื่อยังไม่มีของจริงใน environment
#
# 🔴 ห้ามใส่ค่าที่ดูใช้งานได้จริง (`CLAUDE.md` §ห้ามทำโดยไม่ถาม) — และห้ามให้ค่าพวกนี้
# ชนะค่าที่ตั้งมาแล้ว เพราะจะทำให้ผลของสคริปต์ต่างกันระหว่างเครื่องที่มี env กับไม่มี
_PLACEHOLDER_ENV = {
    "ENVIRONMENT": "sit",
    "DATABASE_URL": "postgresql+asyncpg://placeholder:placeholder@localhost:5432/placeholder",
    "JWT_SECRET": "placeholder-not-a-real-key",
    "MEDIA_BASE_URL": "https://placeholder.invalid",
}


def build_schema() -> str:
    """คืนเนื้อไฟล์ที่ควรเป็น — ข้อความล้วน ไม่แตะดิสก์

    แยกจากการเขียนไฟล์เพื่อให้ `--check` กับโหมดเขียนใช้ตัวสร้างตัวเดียวกันจริง ๆ
    ถ้าสองโหมดสร้างคนละทาง `--check` จะเขียวได้ทั้งที่ไฟล์ผิด
    """
    for key, value in _PLACEHOLDER_ENV.items():
        os.environ.setdefault(key, value)

    from app.main import app

    # `sort_keys=False` — เก็บลำดับที่ FastAPI ประกอบไว้ (ลำดับ route/field ตามโค้ด)
    # การ sort จะทำให้ diff อ่านง่ายขึ้นก็จริง แต่ทำให้ไฟล์ **ไม่เท่ากับ** สิ่งที่
    # `/openapi.json` ของแอปจริงเสิร์ฟ ซึ่งเป็นทั้งหมดของเหตุผลที่ไฟล์นี้มีอยู่
    #
    # ไม่มี newline ปิดท้าย — ให้ตรงกับไฟล์ที่ commit ไว้ตั้งแต่ `1e62092` เป๊ะ
    # (ตั้งใจให้ PR ที่เพิ่มสคริปต์นี้ **ไม่มี diff ของ openapi.json ปนมา**
    #  ไม่งั้นจะแยกไม่ออกว่าไฟล์เปลี่ยนเพราะโค้ดเปลี่ยน หรือเพราะรูปแบบเปลี่ยน)
    return json.dumps(app.openapi(), indent=2, ensure_ascii=False, sort_keys=False)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="ไม่เขียนไฟล์ · ต่างจากของที่ commit ไว้เมื่อไหร่ exit 1 (โหมดที่ CI ใช้)",
    )
    args = parser.parse_args()

    generated = build_schema()

    if not args.check:
        OUTPUT.write_text(generated, encoding="utf-8")
        print(f"เขียน {OUTPUT.relative_to(REPO_ROOT)} — {len(generated):,} ตัวอักษร")
        return 0

    current = OUTPUT.read_text(encoding="utf-8") if OUTPUT.is_file() else None
    if current == generated:
        print(f"{OUTPUT.name} ตรงกับโค้ดจริงแล้ว")
        return 0

    print(
        f"🔴 {OUTPUT.name} ไม่ตรงกับโค้ดจริง\n"
        "\n"
        "ไฟล์นี้คือ *ภาพสะท้อนของโค้ด* ที่สกิล `contract-drift-check` §2 ใช้เป็นฝั่ง\n"
        '"โค้ดจริง" — ถ้ามันค้าง การเทียบ drift จะให้คำตอบผิดโดยไม่มีอะไรฟ้อง\n'
        "\n"
        "แก้ด้วย:\n"
        "  ./venv/bin/python scripts/generate_openapi.py\n"
        "แล้ว commit ไฟล์ที่ได้มาพร้อมกับการเปลี่ยน schema ในรอบเดียวกัน\n"
        "\n"
        "🔴 ห้ามแก้ openapi.json ด้วยมือให้ตรงกับ contract — contract ตัวจริงอยู่ที่\n"
        "   ../workspace/docs/api/openapi.yaml · การแก้ไฟล์นี้ด้วยมือคือการทำลาย\n"
        "   เครื่องมือวัด ไม่ใช่การแก้ drift",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
