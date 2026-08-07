"""verification: enum เหลือ 2 ค่า + verification_note → reference_note (ADR-0014 D21/D22)

Revision ID: f4c8a1e07b93
Revises: a7c31e5f9b04
Create Date: 2026-08-07 21:10:00.000000

ADR-0014 **Amendment 2 (D21–D26)** ยุบโมเดลลงให้เท่ากับสิ่งที่ระบบพูดได้จริง คือ
*"เปิดดูแล้วเจอ นี่ลิงก์"* — ไม่ใช่การเทียบลายแล้วตัดสินว่าใบไหนต่างจากมาตรฐาน

  - **D21** `ARTWORK_MATCHED` → `REFERENCE_FOUND` (ชื่อเดิมแปลว่า *เจอแล้วเทียบผ่าน*
    ซึ่งแรงกว่าที่ทำจริง) · **ตัด `DISCREPANCY_FOUND`** เพราะการบอกว่าใบนี้ "ต่าง"
    คือการอ้างว่ารู้ว่าอะไรคือมาตรฐาน · **ตัด `UNKNOWN`** เพราะไม่มีทาง derive ได้
    จาก 2 ช่องที่คนกรอก (D22) และไม่เคยมีแถวไหนมีค่า
  - **D22** `verification_note` → `reference_note` — คอลัมน์นี้เหลือความหมายเดียวคือ
    *เหตุผลตอนหาไม่เจอ* ชื่อเดิมจึงกว้างกว่าเนื้อหา (ปัญหาทรงเดียวกับที่ D13 แก้ชื่อค่า)

🔴 **`NOT_CHECKED` ยังไม่ใช่สมาชิกของ enum และห้ามเพิ่มโดยไม่มีมติใหม่** — `NULL` ทำหน้าที่นั้น
(D21) · ⚠️ แต่ D21 บันทึกไว้ด้วยว่า เหตุผลเดิมของ ADR-0009 Alternative 7 ที่ปฏิเสธ
`NOT NULL DEFAULT 'NOT_CHECKED'` (*"ลบความต่างระหว่าง ยังไม่มีใครดู กับ ดูแล้วตัดสินไม่ได้"*)
**ตายไปพร้อม `UNKNOWN` แล้ว** — ถ้าวันหน้าเจ้าของสั่งให้เป็นค่าจริง นั่นคือการเปลี่ยนที่ถูกหลัก
ไม่ใช่การรื้อมตินี้

## ข้อมูลที่ต้องแปลง

**ไม่มี** — ยืนยันกับ dev DB 2026-08-07 ก่อนเขียนไฟล์นี้:
`count(*)=117` · `count(verification_status)=0` · `count(verification_note)=0` ·
`count(reference_url)=0` · SIT เท่ากันทุกตัว

🔴 **แต่ migration ต้องถูกต้องโดยไม่พึ่งข้อเท็จจริงชั่วคราวนั้น** — `USING` ใช้ `CASE`
แปลงค่าให้ครบทุกทางในคำสั่งเดียว จึงรอดแม้ตารางมีข้อมูลแล้ว

## ทำไม recreate-type ไม่ใช่ `ALTER TYPE ... RENAME VALUE`

`RENAME VALUE` ทำได้เฉพาะการเปลี่ยนชื่อ — **ลบสมาชิกไม่ได้เลย** (PostgreSQL ไม่มี
`DROP VALUE`) และรอบนี้ต้องลบสองค่า · repo นี้ตั้ง `create_type=False` ทุก `PgEnum`
และมีสูตร recreate อยู่แล้วที่ `f1b2a3c4d5e6` / `a7c31e5f9b04` (skill `poster-database` §5)
"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "f4c8a1e07b93"
down_revision: Union[str, Sequence[str], None] = "a7c31e5f9b04"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_OLD_VALUES = (
    "ARTWORK_MATCHED",
    "DISCREPANCY_FOUND",
    "NO_REFERENCE_FOUND",
    "UNKNOWN",
)
_NEW_VALUES = ("REFERENCE_FOUND", "NO_REFERENCE_FOUND")


def _recreate(values: Sequence[str], remap: dict[str, str | None]) -> None:
    """RENAME เดิม → CREATE ใหม่ → ALTER COLUMN USING → DROP เดิม (สูตรของ repo §5)

    🔴 **การแปลงค่าต้องเกิดใน `USING` ไม่ใช่ `UPDATE` แยกก่อนหน้า** — `UPDATE` ก่อนสลับ
    type จะพังเพราะ type เดิมไม่มีค่าปลายทาง ส่วน `UPDATE` หลังสลับก็สายไปแล้วเพราะ
    `USING` ระเบิดไปก่อน (บทเรียนจาก `a7c31e5f9b04` ฉบับแรก)

    ⚠️ `ELSE ... END` ยังส่งค่าที่ไม่อยู่ใน `remap` ผ่านไปตรง ๆ — ค่าที่ถูก**ลบ**ออกจาก
    type ปลายทางจึงต้องอยู่ใน `remap` ที่ map เป็น `None` เสมอ ไม่งั้น cast จะพัง
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
    _recreate(
        _NEW_VALUES,
        {
            "ARTWORK_MATCHED": "REFERENCE_FOUND",
            "DISCREPANCY_FOUND": None,
            "UNKNOWN": None,
        },
    )
    op.alter_column("posters", "verification_note", new_column_name="reference_note")


def downgrade() -> None:
    """Downgrade schema.

    🔴 **ย้อนกลับแล้วข้อมูลไม่ครบเหมือนเดิม** — `upgrade()` แปลง `DISCREPANCY_FOUND`
    และ `UNKNOWN` เป็น `NULL` ไปแล้ว ไม่มีอะไรบอกได้ว่าแถวไหนเคยเป็นค่าไหน · ยอมรับได้
    เพราะวันที่รัน migration นี้ยังไม่มีแถวไหนมีค่า (0/117) — **ถ้ามีข้อมูลจริงแล้ว
    ต้องอ่านข้อนี้ก่อน downgrade** ไม่ใช่รันแล้วค่อยรู้
    """
    op.alter_column("posters", "reference_note", new_column_name="verification_note")
    _recreate(_OLD_VALUES, {"REFERENCE_FOUND": "ARTWORK_MATCHED"})
