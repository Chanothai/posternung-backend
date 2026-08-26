"""เพดาน active reservation ต่อผู้ใช้ เข้า platform_settings (ADR-0033 OD-3)

## ทำไมเป็นแถว config ไม่ใช่เลขในโค้ด

เพดาน **3 รายการ/ผู้ใช้** มาจาก `ADR-0002` ซึ่งถูกเลื่อนไป Phase 2 พร้อม Omise
(`ADR-0029`) และวันนี้ยังปรากฏอยู่ในสัญญาที่ `POST /cart/reserve/{id}`
(`RESERVATION_LIMIT_EXCEEDED`) กับในสกิล `stock-integrity` แต่ **ไม่มี BR ข้อไหน
รับช่วงต่อ** ⇒ เจ้าของตัดสินที่ GATE 1 ของ `/feature INF-33` ว่า **คงเพดานไว้
แต่ย้ายเลขเข้า `platform_settings`** (ADR-0033 **OD-3** ทาง (ก))

เหตุผลเดิมของเพดาน (คนเดียวจับของทั้งร้านเป็นตัวประกัน) **แรงขึ้นไม่ใช่อ่อนลง**
เมื่อ TTL ยาวจาก 15 เป็น 60 นาที (`ADR-0030` D3)

## ขอบเขต

**data migration ล้วน — ไม่แตะ schema เลย** ไม่มีคอลัมน์ใหม่ ไม่มีค่า enum ใหม่
ไม่มีตารางใหม่ · `downgrade()` ลบเฉพาะแถวที่ `upgrade()` ใส่เข้าไป

Revision ID: b6f2d4a91c73
Revises: d5e1c8a3f720
Create Date: 2026-08-26 10:12:31.004518
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b6f2d4a91c73"
down_revision: Union[str, Sequence[str], None] = "d5e1c8a3f720"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SETTING_KEY = "max_active_reservations_per_user"
SETTING_VALUE = "3"
SETTING_DESCRIPTION = (
    "เพดาน active reservation ต่อผู้ใช้ (ADR-0033 OD-3 · เดิมมาจาก ADR-0002) "
    "🔴 ห้าม hardcode ในโค้ด — อ่านทางเดียวกับ reservation_ttl_minutes"
)


def upgrade() -> None:
    """Upgrade schema."""
    # ON CONFLICT DO NOTHING เผื่อ environment ที่มีคนใส่คีย์นี้ด้วยมือไปก่อนแล้ว —
    # migration ต้องไม่ล้มเพราะค่าที่ถูกต้องอยู่ที่นั่นอยู่แล้ว
    op.get_bind().execute(
        sa.text(
            "INSERT INTO platform_settings (key, value, description) "
            "VALUES (:key, :value, :description) ON CONFLICT (key) DO NOTHING"
        ),
        {
            "key": SETTING_KEY,
            "value": SETTING_VALUE,
            "description": SETTING_DESCRIPTION,
        },
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.get_bind().execute(
        sa.text("DELETE FROM platform_settings WHERE key = :key"),
        {"key": SETTING_KEY},
    )
