"""Audit trail แบบ append-only — ที่อยู่เดียวของ `append_audit_line()` (INF-41 §10.5)

🔴 **ย้ายมาจาก `scripts/grant_admin.py` 2026-09-18** — เดิมฟังก์ชันนี้ประกาศอยู่ที่นั่น
เพราะเป็นสคริปต์แรกที่ต้องเขียน audit (ADR-0031 D6-b) พอ `scripts/orders/order_ops.py`
(INF-41) ต้องใช้กลไกเดียวกัน การ `import` ข้ามจาก `grant_admin.py` จะทำให้สคริปต์นั้น
กลายเป็นโมดูลกลางโดยบังเอิญ — บทเรียนเดียวกับที่ `scripts/seed/_shared.py` แยกออกมา
(ดู docstring ของไฟล์นั้น: *"ทิศทางเป็นทางเดียวเสมอ: lane → module กลาง"*)

`grant_admin.py` **import กลับจากที่นี่แล้ว** — พฤติกรรมของมันเท่าเดิมทุกประการ
ไม่มีอะไรเปลี่ยนสำหรับผู้เรียกเดิม (มีเทส identity ยืนยัน:
`grant_admin.append_audit_line is _audit.append_audit_line`)

รูปแบบไฟล์ audit: JSON หนึ่งบรรทัดต่อหนึ่งเหตุการณ์ (JSONL) เปิดโหมด append เท่านั้น
— ไม่มีเส้นทางไหนในทั้งสองสคริปต์ที่เขียนทับของเดิมได้
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class AuditWriteFailed(RuntimeError):
    """เขียนไฟล์ audit ไม่สำเร็จ — ผู้เรียกต้องไม่ทำผลข้างเคียงที่ไม่มีร่องรอยต่อ

    (ADR-0031 D6-b: *"ถ้าเขียนร่องรอยไม่ได้ ต้องไม่มีการให้สิทธิ์เกิดขึ้นเลย"* — กฎ
    เดียวกันใช้กับทุกผู้เรียก ไม่ใช่แค่ `grant_admin.py`)
    """


def append_audit_line(audit_path: Path, record: dict[str, Any]) -> None:
    """เขียน 1 บรรทัด JSON ต่อท้ายไฟล์ audit (append-only)

    เปิดด้วยโหมด `"a"` เท่านั้น — ไม่มีเส้นทางไหนที่เขียนทับของเดิมได้
    """
    try:
        audit_path.parent.mkdir(parents=True, exist_ok=True)
        with audit_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")
    except OSError as exc:
        raise AuditWriteFailed(str(exc)) from exc
