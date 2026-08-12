"""ตาราง audit ของการแตกแถว — ADR-0024 D2 (INF-22)

หนึ่งแถว = หนึ่งแถวลูกที่ถูกสร้างขึ้นจากการแตกแถวพ่อ — เก็บความสัมพันธ์ "แถวนี้เกิดจาก
แถวไหน" ที่ `posters` ไม่มีคอลัมน์ไหนบอกได้เลย (ADR-0019 D8: การแตกแถวเป็นเครื่องมือ
ไม่ใช่การแก้ข้อมูล และร่องรอยของมันต้องไม่หายไปพร้อมเครื่องที่รันมัน)

ทำไมเป็นตารางแยกไม่ใช่คอลัมน์ self-FK บน `posters` — เหตุผลสามชั้น (ADR-0024 D2):
1. **precedent** — `poster_attribute_reviews` (ADR-0010 D3) ตัดสินไปแล้วว่าฟิลด์ ops
   ตัวที่สองของ `posters` ควรแยกตาราง ไม่ใช่เติมคอลัมน์ทีละตัว
2. `posters` เป็นตารางที่ถูก query ตรงเพื่อ public response — self-FK บนตารางนั้นคือ
   คอลัมน์ที่ `select *` เผลอพาออก public API ได้ง่ายกว่าตารางแยก (ADR-0009 D11)
3. **UNIQUE ที่ `child_poster_id`** คือด่านกันรันซ้ำสร้างลูกซ้ำจริงที่ระดับ DB
   ไม่ใช่แค่ระดับสคริปต์ (หลักเดียวกับ `uq_poster_images_storage_key`)

append-only เหมือน `poster_attribute_reviews` — ไม่มี UPDATE/DELETE บนแถวของตารางนี้
จึงใช้ `CreatedAtMixin` (ไม่มี `updated_at`)

ตารางนี้เป็นข้อมูลภายในล้วน ๆ — **ไม่มี endpoint ไหนอ่านมันเลย** (ADR-0024 D2 §เตือน)
ถ้าวันหน้าต้องแสดง "ใบพี่น้อง" ให้ผู้ซื้อ นั่นเป็นมติใหม่ที่ต้องผ่านขั้น contract ก่อน
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.base import CreatedAtMixin, uuid_pk


class PosterSplit(Base, CreatedAtMixin):
    __tablename__ = "poster_splits"
    __table_args__ = (
        # ใช้ค้นว่า "แถวพ่อนี้เคยถูกแตกออกเป็นลูกกี่แถวแล้ว" — คำถามหลักของตารางนี้
        Index("ix_poster_splits_parent", "parent_poster_id"),
        # ด่านจริงระดับ DB — รันเครื่องมือแตกแถวซ้ำจากรอบเดิมสร้างแถวลูกซ้ำไม่ได้
        # (ADR-0024 D2 ข้อ 3) · ตั้งชื่อเองแทนปล่อยให้ dialect ตั้งชื่อให้ (poster.py
        # ทำแบบนี้กับ uq_poster_images_storage_key เช่นกัน) เพื่อกัน autogenerate
        # เห็นว่าชื่อไม่ตรงกับ migration ในรอบถัดไป
        UniqueConstraint("child_poster_id", name="uq_poster_splits_child_poster"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    # แถวลูกที่ถูกสร้างจากการแตกครั้งนี้ — UNIQUE (ดู __table_args__)
    child_poster_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("posters.id", ondelete="CASCADE"),
        nullable=False,
    )
    # แถวพ่อที่ถูกแตกออกมา — ไม่ UNIQUE เพราะพ่อแตกได้หลายรอบ (หลายแถวลูก)
    parent_poster_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("posters.id", ondelete="CASCADE"),
        nullable=False,
    )
    # ชื่อคนที่ตัดสินใจแตก — ข้อจำกัดเดียวกับ poster_attribute_reviews.reviewed_by:
    # เป็นข้อความที่คนพิมพ์เอง ไม่ได้ผ่าน authentication (Phase 1 ยังไม่มี identity
    # ของ operator) จึงเป็นร่องรอยไว้ตามถาม ไม่ใช่หลักฐานที่ใช้ยันกันได้
    reviewed_by: Mapped[str] = mapped_column(String(120), nullable=False)
    # เวลาที่ "คนตัดสินใจแตก" ตามที่ระบุในใบงาน — คนละอันกับ created_at ซึ่งเป็นเวลา
    # ที่เครื่องเขียนลง DB จริง (สองค่านี้ต่างกันได้: ตรวจวันนี้ apply อาทิตย์หน้า)
    reviewed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    # ชื่อไฟล์ใบงานที่ใช้รันรอบนั้น — ตัวไฟล์ commit เข้า repo ไม่ได้ (.gitignore กัน
    # CSV ของ scripts/seed/ ไว้เพราะ repo เป็น public) จึงเก็บชื่อไว้ให้ตามหาไฟล์บน
    # เครื่องคนรันได้ (แบบเดียวกับ poster_attribute_reviews.source)
    source: Mapped[str] = mapped_column(String(255), nullable=False)
    # ทำไมถึงแตกแถวนี้ — บังคับกรอกเสมอในเครื่องมือนี้ (ต่างจาก
    # poster_attribute_reviews.reason ที่เป็น nullable เพราะบางเส้นทางไม่ต้องการ
    # เหตุผล เส้นแตกแถวมีเหตุผลเดียวและบังคับทุกแถว จึงประกาศ NOT NULL ตรง ๆ)
    reason: Mapped[str] = mapped_column(Text, nullable=False)

    # created_at (จาก CreatedAtMixin) = เวลาที่แตกจริง (เวลาที่เครื่องเขียนแถวนี้)
