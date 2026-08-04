"""ตาราง audit ของการนำค่าที่ "คนตรวจแล้ว" เข้า `posters` — ADR-0010 D3

ทำไมเป็นตารางแยกไม่ใช่คอลัมน์บน `posters`: ADR-0009 §Open Decisions ข้อ 4 เขียนไว้เอง
ตอนรับ `needs_review` ลง `posters` ว่า *"ถ้ารอบต่อไปมีฟิลด์ ops ตัวที่สอง ให้ทบทวนว่า
ถึงเวลาแยกตารางหรือยัง"* — `reviewed_by`/`reviewed_at` คือฟิลด์ ops ตัวที่สองนั้น

append-only: หนึ่งแถว = การเขียนค่าหนึ่งครั้งลงหนึ่งฟิลด์ของหนึ่งใบ ไม่มีการ UPDATE
หรือ DELETE แถวในตารางนี้ (จึงใช้ `CreatedAtMixin` ไม่ใช่ `TimestampMixin`)

🔴 **ข้อจำกัดที่ต้องเข้าใจให้ตรง (ADR-0010 D1):** `reviewed_by` เป็นข้อความที่คนพิมพ์เอง
ลงไฟล์เซ็นรับ ไม่ได้ผ่าน authentication ใด ๆ — Phase 1 ยังไม่มีระบบ identity ของ operator
เลย (ไม่มี role/is_admin ในโค้ด) ตารางนี้จึงเป็น **ร่องรอยไว้ตามถาม ไม่ใช่หลักฐานที่ใช้
ยันกันได้** ห้ามอ่าน ADR-0009 D6 ข้อ 3 ว่า "มี identity แล้ว" เพราะมีตารางนี้
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.base import CreatedAtMixin, uuid_pk


class PosterAttributeReview(Base, CreatedAtMixin):
    __tablename__ = "poster_attribute_reviews"
    __table_args__ = (
        # ใช้ค้นว่า "ใบนี้เคยมีคนตรวจฟิลด์ไหนไปแล้วบ้าง" — คำถามหลักของตารางนี้
        Index("ix_poster_attribute_reviews_poster_field", "poster_id", "field"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    poster_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("posters.id", ondelete="CASCADE"),
        nullable=False,
    )
    # ชื่อคอลัมน์ปลายทางบน `posters` — เก็บเป็นข้อความไม่ใช่ enum โดยตั้งใจ เพราะ
    # allowlist ของ ADR-0010 D4 จะขยายขึ้นในรอบหลัง การใช้ PG enum จะบังคับให้ต้อง
    # recreate type ทุกครั้งที่เพิ่มฟิลด์ (poster-database §5) โดยไม่ได้อะไรกลับมา —
    # ตัว allowlist บังคับที่สคริปต์ซึ่งมี test คุมอยู่แล้ว
    field: Mapped[str] = mapped_column(String(64), nullable=False)
    # ค่าก่อน/หลังเก็บเป็นข้อความเสมอไม่ว่าคอลัมน์ปลายทางจะเป็นชนิดอะไร — ตารางนี้
    # ต้องรองรับหลายฟิลด์ที่ชนิดต่างกันในคอลัมน์ชุดเดียว
    # value_before ปกติเป็น NULL เพราะ D6 อนุญาตให้เขียนเฉพาะแถวที่ปลายทางว่างอยู่
    # (เก็บไว้เพราะถ้า D6 ถูกผ่อนในอนาคต คอลัมน์นี้คือสิ่งเดียวที่บอกว่าทับอะไรไป)
    value_before: Mapped[str | None] = mapped_column(Text, nullable=True)
    value_after: Mapped[str | None] = mapped_column(Text, nullable=True)
    # ชื่อคนที่เซ็นรับ — มาจากไฟล์เซ็นรับตรง ๆ ดูข้อจำกัดใน docstring ของโมดูล
    reviewed_by: Mapped[str] = mapped_column(String(120), nullable=False)
    # เวลาที่ "คนตรวจ" ตามที่ระบุในไฟล์ — คนละอันกับ created_at ที่เป็นเวลาที่
    # "เครื่องเขียนลง DB" · สองค่านี้ต่างกันได้มาก (ตรวจวันนี้ apply อาทิตย์หน้า)
    reviewed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    # ที่มาของหลักฐาน — ชื่อไฟล์เซ็นรับที่ใช้รันรอบนั้น (ADR-0010 D3)
    # ตัวไฟล์ commit เข้า repo ไม่ได้ (.gitignore กัน CSV ไว้เพราะ repo เป็น public)
    # จึงเก็บชื่อไว้เพื่อให้ตามหาไฟล์บนเครื่องคนรันได้
    source: Mapped[str] = mapped_column(String(255), nullable=False)

    # `created_at` (จาก CreatedAtMixin) = **`applied_at`** ที่ ADR-0010 D3 ระบุไว้ —
    # ใช้ชื่อของ mixin แทนการประกาศคอลัมน์เองตาม poster-database §4 ข้อ 2
    # ("reuse ... เสมอ อย่าเขียน timestamp column เอง") · แถวในตารางนี้ถูกสร้าง
    # ณ วินาทีที่ UPDATE ถูก apply พอดี ทั้งสองชื่อจึงหมายถึงเวลาเดียวกันเป๊ะ
