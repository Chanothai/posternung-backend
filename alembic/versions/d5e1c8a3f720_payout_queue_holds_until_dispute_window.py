"""ix_orders_payout_queue พา auto_confirm_due_at ติดมาด้วย (ADR-0032 Amendment 1 · D8-finding-2)

## เรื่องที่ migration นี้เป็นครึ่งหนึ่งของคำตอบ

BR-P4 ให้ผู้ซื้อกด "ได้รับสินค้า ตรงตามรายการ" **เมื่อไหร่ก็ได้** → `COMPLETED`
BR-P6 ให้เปิด dispute ได้ **ภายใน 7 วันหลัง `Shipped`** → เงินถูกอายัด

⇒ ผู้ซื้อกดยืนยันวันที่ 2 แล้วเงินออกวันที่ 3 ขณะที่เขายังเคลมได้ถึงวันที่ 7
**มีช่วง 4–5 วันที่ผู้ซื้อมีสิทธิ์แต่เงินอายัดไม่ได้แล้ว** — และระบบนี้ **ไม่มี chargeback**
ช่วง dispute จึงเป็นการคุ้มครองเดียวที่เขามี

เจ้าของเลือกทาง **(ข)**: **เงินถูกกันไว้จนครบ 7 วันหลัง `Shipped` เสมอ ต่อให้
`COMPLETED` แล้ว** ⇒ เกณฑ์เข้าคิวจ่ายไม่ใช่ `COMPLETED` เฉย ๆ อีกต่อไป

## 🔴 ทำไมไม่ใส่เงื่อนไขเวลาลงใน predicate ตรง ๆ

เพราะ **PostgreSQL ไม่ยอม** — พิสูจน์ด้วยคำสั่งจริงบน `poster_nung_test` 2026-08-25:

```
CREATE INDEX ... WHERE status='COMPLETED' AND auto_confirm_due_at <= now();
ERROR:  functions in index predicate must be marked IMMUTABLE
```

`now()` เป็น STABLE ไม่ใช่ IMMUTABLE · index ที่ predicate ขึ้นกับ "ตอนนี้กี่โมง"
จะถูกต้องแค่ ณ วินาทีที่สร้าง จึงเป็นไปไม่ได้โดยธรรมชาติของ index

⇒ ทำได้แค่ **คัดล่วงหน้าด้วยส่วนที่ immutable** (`status` · `payout_id`) แล้วพา
`auto_confirm_due_at` ติดมาเป็น **คอลัมน์** ให้ query กรองช่วงเวลาต่อได้โดยไม่ต้อง
กลับไปอ่านตาราง

## ⚠️ สิ่งที่ migration นี้ **ไม่ได้** ทำ

**มันไม่ได้บังคับกฎ** — DB ชั้นนี้บังคับเรื่องนี้ไม่ได้เลย · ตัวบังคับจริงคือ query ของ
payout scheduler ซึ่งเป็นงานของ **INF-33** และต้องมีเทสว่าออร์เดอร์ที่
`auto_confirm_due_at > now()` **ไม่โผล่ในคิวจ่าย** แม้จะ `COMPLETED` แล้ว

🔴 **ห้ามอ่าน index นี้ว่าเป็นด่าน** — มันคือเครื่องมือให้ query ที่ถูกต้องทำงานเร็ว
เทสที่บันทึกช่องนี้ไว้: `tests/unit/test_payout_queue_index.py`

## ทำไมทำตอนนี้

**ยังไม่มีโค้ด payout สักบรรทัด** (grep `app/services/` `app/api/` แล้วไม่เจอ) —
จังหวะนี้ถูกที่สุด เพราะไม่มี query ไหนต้องรื้อตาม

Revision ID: d5e1c8a3f720
Revises: c9f4a2e07b18
Create Date: 2026-08-25 18:02:44.913077
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d5e1c8a3f720"
down_revision: Union[str, Sequence[str], None] = "c9f4a2e07b18"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_PREDICATE = "status = 'COMPLETED' AND payout_id IS NULL"


def upgrade() -> None:
    """Upgrade schema."""
    op.drop_index("ix_orders_payout_queue", table_name="orders")
    op.create_index(
        "ix_orders_payout_queue",
        "orders",
        ["seller_id", "auto_confirm_due_at"],
        postgresql_where=sa.text(_PREDICATE),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_orders_payout_queue", table_name="orders")
    op.create_index(
        "ix_orders_payout_queue",
        "orders",
        ["seller_id"],
        postgresql_where=sa.text(_PREDICATE),
    )
