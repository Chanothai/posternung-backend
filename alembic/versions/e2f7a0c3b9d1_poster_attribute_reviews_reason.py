"""poster_attribute_reviews.reason — ADR-0010 Amendment 2026-08-09 (A-D2 ข้อ 3)

Revision ID: e2f7a0c3b9d1
Revises: c5a8f31e64d7

เพิ่มคอลัมน์เดียว: `reason` (Text · nullable · **ไม่มี server_default**)

## ทำไมไม่มี `server_default` และทำไมไม่ backfill

`NULL` ในคอลัมน์นี้แปลว่า **"เขียนโดยเส้นทางที่ไม่ต้องการเหตุผล"** ไม่ใช่ "ลืมกรอก"
— **973 แถว**ที่มีอยู่บน dev (นับจริง `SELECT source, count(*) ... GROUP BY source`:
`manual-entry.csv` 700 + `reference-entry.csv` 232 + `release-date-signoff.csv` 41)
มาจากเส้นที่ 2/3/4 ซึ่งเติมช่องที่ยังว่าง (ไม่มีอะไรให้อธิบาย)
‹แก้ 2026-08-09 หลัง code-critic รอบที่ 1 — ตัวเลขเดิมเขียน 741 ซึ่งคือ 700+41
คือ **ตัดเส้นที่ 4 ออกทั้งที่ประโยคอ้างว่ารวมทั้งสามเส้น**›
การเติมค่าใด ๆ ให้แถวเหล่านั้นย้อนหลังคือ **การกรอกข้อมูลแทนคนที่ไม่เคยพูด** ซึ่งเป็น
สิ่งเดียวกับที่ ADR-0009 D2 ห้าม · `server_default` ก็เป็นการกรอกแทนคนแบบเดียวกัน
แค่เกิดกับแถวอนาคตแทนแถวเก่า

## 🔴 downgrade ลบเหตุผลทิ้งโดยกู้ไม่ได้

`op.drop_column()` ทิ้งข้อความที่คนพิมพ์อธิบายว่า **ทำไมถึงแก้ค่าที่ลูกค้าเห็นบน
หน้าร้านไปแล้ว** — ไม่มีที่อื่นเก็บสำเนาไว้เลย (ใบงาน CSV อยู่ใน `.gitignore` และอยู่
บนเครื่องคนรันเท่านั้น) · ค่าอื่นในตารางนี้ยังอยู่ครบ ผลลัพธ์จึงเป็น audit ที่บอกได้ว่า
*ใครแก้อะไรเมื่อไหร่* แต่ตอบไม่ได้ว่า *ทำไม* ซึ่งเป็นสิ่งเดียวที่ทำให้เส้นที่ 5 ต่างจาก
การรันสคริปต์เฉย ๆ (A-D2 ข้อ 2)

→ **ก่อน downgrade บน DB ที่มีข้อมูลจริง ให้ dump คอลัมน์นี้เก็บไว้ก่อน**
"""

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "e2f7a0c3b9d1"
down_revision: Union[str, Sequence[str], None] = "c5a8f31e64d7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "poster_attribute_reviews",
        sa.Column("reason", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    # 🔴 ลบเหตุผลของการแก้ค่าที่ลูกค้าเห็นแล้วทิ้งถาวร — ดู docstring ด้านบน
    op.drop_column("poster_attribute_reviews", "reason")
