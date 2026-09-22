"""ล็อกว่า `docs/api-contract-f1-f3.md` §3 (Error Code Catalog) นับแถวถูก — พบจาก
`code-critic` รอบ 1 ของ INF-24 (M-a): ตัวเลขท้ายตาราง ("รวม N error_code") ค้างมา
ก่อน INF-24 แล้ว (นับจริง 15 แถวตอนนั้น แต่เขียนว่า 14) และรอบที่แก้ไฟล์นี้เพิ่มแถวใหม่
โดยไม่อัปเดตตัวเลขก็ยังทำผิดซ้ำ (นับจริง 16 แถวแต่เขียนว่า 15)

ทรงเดียวกับ `test_openapi_json_is_fresh.py` — ไฟล์เอกสารต้องตรงกับสิ่งที่มันอ้างถึงตัวเอง
ไม่ต้องรอให้คนนับด้วยตาแล้วพลาด
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
CONTRACT_DOC = REPO_ROOT / "docs" / "api-contract-f1-f3.md"

CATALOG_HEADER = "## 3. Error Code Catalog"
TOTAL_LINE_PATTERN = re.compile(r"รวม \*\*(\d+) error_code\*\*")
# แถวข้อมูลของตาราง markdown: ขึ้นต้นด้วย `|` และมี error_code (ครอบด้วย backtick)
# ไม่ใช่แถวหัวตาราง (มีคำว่า "error_code" ไม่ครอบ backtick) หรือแถวคั่น (`---`)
TABLE_ROW_PATTERN = re.compile(r"^\|\s*\*{0,2}`[A-Z_]+`")


def _catalog_section() -> str:
    text = CONTRACT_DOC.read_text(encoding="utf-8")
    start = text.index(CATALOG_HEADER)
    total_match = TOTAL_LINE_PATTERN.search(text, start)
    assert total_match, "หา 'รวม N error_code' ไม่เจอหลัง §3 — รูปแบบเปลี่ยนไปหรือเปล่า"
    return text[start : total_match.end()]


def test_error_catalog_row_count_matches_the_stated_total() -> None:
    section = _catalog_section()
    rows = [
        line for line in section.splitlines() if TABLE_ROW_PATTERN.match(line.strip())
    ]
    stated = TOTAL_LINE_PATTERN.search(section)
    assert stated is not None
    stated_total = int(stated.group(1))

    assert len(rows) == stated_total, (
        f"ตาราง §3 มี {len(rows)} แถวจริง แต่ท้ายตารางเขียนว่า {stated_total} — "
        "แก้ตัวเลขท้ายตาราง (หรือแก้ตาราง) ให้ตรงกัน\n" + "\n".join(rows)
    )
