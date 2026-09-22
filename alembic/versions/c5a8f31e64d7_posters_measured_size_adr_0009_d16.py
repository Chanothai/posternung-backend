"""posters: width_in / height_in — ขนาดที่วัดจากใบจริง (ADR-0009 D16)

Revision ID: c5a8f31e64d7
Revises: f4c8a1e07b93
Create Date: 2026-08-08 10:30:00.000000

**ADR-0009 D16** ตัดสินว่า input ตัวเดียวที่ยอมรับได้สำหรับ `size_format` คือ
**ขนาดที่วัดจากใบจริง หน่วยนิ้ว** — ไม่ใช่รูปถ่าย และไม่ใช่คอลัมน์ `size` ที่มีอยู่

รอบก่อนหน้านี้ `size_format` ติดอยู่ที่ *"ไม่มีที่เก็บขนาดที่วัดได้"* ตรง ๆ:
D16 เขียนไว้เองว่า **"ยังเขียนค่าลง DB ไม่ได้จนกว่าจะมีคอลัมน์นั้น"** — migration
นี้คือคอลัมน์นั้น

## ทำไมไม่ derive จาก `posters.size` ที่มีอยู่แล้ว

`size` มาจากคอลัมน์ `size_guess` ของไฟล์ export (สคริปต์ขั้นนำเข้า
`prepare_seed.py` — ถูกลบ 2026-08-16 · ADR-0019 A-D3 · อ่านย้อนได้จาก git history)
ซึ่งคือ **ข้อความโฆษณา** ไม่ใช่การวัด · **ADR-0009 D4 ห้ามใช้เป็น input ไปแล้ว**
และเมื่อนับจาก dev DB จริงวันที่เขียนไฟล์นี้ (2026-08-08) พบว่า:

    count(*) = 117 · count(size) = 116 · **ค่าที่ต่างกันมีเพียง 1 ค่า: `27x40`**

(แถวที่ `size` ว่างคือกรอบไฟ Slim Light Box ไม่ใช่โปสเตอร์ — BL-82)

การ backfill จากคอลัมน์นั้นจะได้ `ONE_SHEET` ครบ 116 ใบโดยที่**ไม่มีใครเคยวัดอะไรเลย**
ซึ่งเป็นการสร้างข้อมูลปลอมที่ตรวจย้อนไม่ได้ — migration นี้จึง **ไม่แตะข้อมูลเดิม
แม้แต่แถวเดียว** ทั้งสองคอลัมน์เป็น `NULL` ทั้งตารางหลัง upgrade

`NULL` ที่นี่แปลว่า **"ยังไม่มีใครวัด"** ตรงตามหลัก D2 (NULL ≠ UNKNOWN ≠ OTHER)

## ทำไม `Numeric(5, 2)` ไม่ใช่ `Float`

ขนาดที่คนวัดมาเป็นทศนิยมตายตัว (`27` · `41` · `20.5`) และ `derive_size_format()`
**เทียบค่าแบบเป๊ะ** กับตาราง mapping ของ D16 — ค่าที่เก็บต้องเป็นทศนิยมฐานสิบจริง
ไม่ใช่ค่าประมาณฐานสอง · `(5, 2)` = ถึง 999.99 นิ้ว เกินพอสำหรับใบที่ใหญ่ที่สุด
(quad 30×40) หลายเท่า

⚠️ **ไม่มี CHECK constraint กำกับช่วงค่า** — ด่านช่วง 1–99.99 อยู่ที่ตัว parser ของ
`scripts/seed/manual_entry.py` เท่านั้น ซึ่ง**อ่อนกว่า** CHECK อย่างมีนัยสำคัญ
(เขียนผ่าน `psql` ตรง ๆ ข้ามได้) · ยอมรับด้วยเหตุผลเดียวกับที่ ADR-0015 D4 ยอมรับ
ให้ด่าน BR-06 อยู่ที่สคริปต์: รอบนี้ยังไม่มี writer ตัวอื่นเลยนอกจากสคริปต์นั้น
ถ้าวันหน้ามี admin endpoint เขียนคอลัมน์นี้ **ต้องกลับมาเพิ่ม CHECK ก่อน**

## contract

`docs/api/openapi.yaml` มีทั้งสองฟิลด์แล้วแต่ติด **`x-status: DRAFT`** — backend
**ยังไม่ส่งออก API** ในรอบนี้ (ไม่มีใน `PosterDetailResponse` ของ `app/schemas/`)
มีเทสเชิงลบล็อกไว้ ทรงเดียวกับ `reference_url` ของ ADR-0014 D6
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c5a8f31e64d7"
down_revision: Union[str, Sequence[str], None] = "f4c8a1e07b93"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ไม่มี server_default โดยตั้งใจ — NULL ต้องแปลว่า "ยังไม่มีใครวัด" ตรง ๆ
    # (หลักเดียวกับที่ ADR-0009 D2 ห้ามตั้ง default เป็น UNKNOWN ให้ฟิลด์ enum)
    op.add_column("posters", sa.Column("width_in", sa.Numeric(5, 2), nullable=True))
    op.add_column("posters", sa.Column("height_in", sa.Numeric(5, 2), nullable=True))


def downgrade() -> None:
    # 🔴 downgrade **ทำลายการวัดที่กู้คืนไม่ได้** — ตัวเลขพวกนี้มาจากการหยิบใบจริง
    # ขึ้นมาวัดทีละใบ ซึ่งเป็นงานที่แพงที่สุดในสายนี้ (BL-93) และไม่มีที่ไหนสำรองไว้
    # `size_format` ที่ derive ไปแล้วจะค้างอยู่โดยไม่มีที่มาให้ตรวจย้อน
    # → ก่อนรัน downgrade บนปลายทางที่มีข้อมูล ต้อง dump สองคอลัมน์นี้เก็บก่อน
    op.drop_column("posters", "height_in")
    op.drop_column("posters", "width_in")
