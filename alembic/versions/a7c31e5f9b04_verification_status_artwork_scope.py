"""verification_status: ARTWORK_MATCHED + NO_REFERENCE_FOUND (ADR-0014 D12/D13)

Revision ID: a7c31e5f9b04
Revises: 4f0b6c2ad713
Create Date: 2026-08-07 18:30:00.000000

ADR-0014 §Amendment 2026-08-07 (D11–D20) จำกัดขอบเขตการเทียบไว้ที่ **อาร์ตเวิร์กเท่านั้น**
(D11) → ชื่อค่าเดิมกว้างกว่าสิ่งที่ทำจริงและมีค่าที่ขาดไปหนึ่งตัว:

  - **D13** `REFERENCE_MATCHED` → `ARTWORK_MATCHED` — ชื่อใหม่บอกขอบเขตในตัวเอง
    ไม่ต้องพึ่งให้คนไปอ่าน D11 ก่อนถึงจะเข้าใจถูก
  - **D12** เพิ่ม `NO_REFERENCE_FOUND` = *เทียบแล้วแต่ไม่มีแบบให้เทียบ* (โปสเตอร์ไทยที่
    วาดอาร์ตเวิร์กใหม่ทั้งใบ) — ต่างจาก `NULL` ซึ่งแปลว่า **ยังไม่มีใครทำ**
  - `DISCREPANCY_FOUND` · `UNKNOWN` คงเดิม

🔴 **ไม่มี `NOT_CHECKED` และห้ามเพิ่ม** — D3 ปฏิเสธไว้พร้อมเหตุผลว่าจะเกิด "สองวิธีพูดว่า
ไม่รู้" ซึ่ง ADR-0009 Alternative 7 ปฏิเสธไปแล้ว · `NULL` ทำหน้าที่นั้นอยู่ (D12 ยืนยันซ้ำ)

## ทำไมถึงเป็น migration ใหม่ ไม่ใช่การแก้ `4f0b6c2ad713`

migration ที่สร้าง type นี้ **merge เข้า `origin/develop` ไปแล้วและ apply บน dev + SIT
ทั้งคู่แล้ว** (ยืนยัน `alembic_version = 4f0b6c2ad713` ทั้งสองฝั่ง 2026-08-07)

## ทำไม recreate-type ไม่ใช่ `ALTER TYPE ... ADD VALUE`

`ADD VALUE` **ย้อนกลับไม่ได้** — PostgreSQL ไม่มี `DROP VALUE` ทำให้ `downgrade()`
เขียนให้ถูกไม่ได้เลย · repo นี้ตั้ง `create_type=False` ทุก `PgEnum` และมีสูตร recreate
อยู่แล้วที่ `f1b2a3c4d5e6` (skill `poster-database` §5) — ไฟล์นี้ใช้สูตรเดียวกัน

## ข้อมูลที่ต้องแปลง

**ไม่มี** — `verification_status` เป็น `NULL` ทั้ง 117 แถวบนทั้ง dev และ SIT
(ยืนยันด้วย query 2026-08-07) · `USING col::text::newtype` จึงแปลง `NULL → NULL` ล้วน ๆ
🔴 **แต่ migration ต้องถูกต้องโดยไม่พึ่งข้อเท็จจริงชั่วคราวข้อนั้น** — `USING` ใช้ `CASE`
แปลง `REFERENCE_MATCHED → ARTWORK_MATCHED` ให้ในคำสั่งเดียว จึงรอดแม้ตารางมีข้อมูลแล้ว
"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a7c31e5f9b04"
down_revision: Union[str, Sequence[str], None] = "4f0b6c2ad713"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_OLD_VALUES = ("REFERENCE_MATCHED", "DISCREPANCY_FOUND", "UNKNOWN")
_NEW_VALUES = (
    "ARTWORK_MATCHED",
    "DISCREPANCY_FOUND",
    "NO_REFERENCE_FOUND",
    "UNKNOWN",
)


def _recreate(values: Sequence[str], remap: dict[str, str | None]) -> None:
    """RENAME เดิม → CREATE ใหม่ → ALTER COLUMN USING → DROP เดิม (สูตรของ repo §5)

    🔴 **การเปลี่ยนชื่อค่าต้องเกิดใน `USING` ไม่ใช่ `UPDATE` แยกก่อนหน้า** —
    `UPDATE ... SET x = 'ARTWORK_MATCHED'` ก่อนสลับ type จะพังทันทีเพราะ type เดิม
    ไม่มีค่านั้น ส่วนการ `UPDATE` หลังสลับก็สายไปแล้วเพราะ `USING` ระเบิดไปก่อน
    · `CASE` ทำให้ทั้งการแปลงและการสลับเกิดในคำสั่งเดียว
    """
    joined = ", ".join(f"'{v}'" for v in values)
    cases = " ".join(
        f"WHEN '{src}' THEN {'NULL' if dst is None else repr(dst)}"
        for src, dst in remap.items()
    )
    op.execute("ALTER TYPE verification_status RENAME TO verification_status_old")
    op.execute(f"CREATE TYPE verification_status AS ENUM ({joined})")
    op.execute(
        "ALTER TABLE posters ALTER COLUMN verification_status "
        "TYPE verification_status USING (CASE verification_status::text "
        f"{cases} ELSE verification_status::text END)::verification_status"
    )
    op.execute("DROP TYPE verification_status_old")


def upgrade() -> None:
    """Upgrade schema."""
    _recreate(_NEW_VALUES, {"REFERENCE_MATCHED": "ARTWORK_MATCHED"})


def downgrade() -> None:
    """Downgrade schema.

    🔴 **ย้อนกลับแล้วข้อมูลบางส่วนหายความหมาย** — `NO_REFERENCE_FOUND` ไม่มีใน type เดิม
    จึงถูกแปลงเป็น `NULL` ซึ่งเปลี่ยนความหมายจาก *"ตรวจแล้วไม่มีแบบให้เทียบ"* เป็น
    *"ยังไม่มีใครตรวจ"* · ยอมรับได้เพราะวันนี้ยังไม่มีแถวไหนมีค่า — **ถ้ามีข้อมูลจริงแล้ว
    ต้องอ่านข้อนี้ก่อน downgrade** ไม่ใช่รันแล้วค่อยรู้
    """
    _recreate(
        _OLD_VALUES,
        {"ARTWORK_MATCHED": "REFERENCE_MATCHED", "NO_REFERENCE_FOUND": None},
    )
