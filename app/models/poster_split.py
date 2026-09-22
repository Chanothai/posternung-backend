"""ตาราง audit ของการแตกแถว — ADR-0024 D2 (INF-22)

หนึ่งแถว = หนึ่งแถวลูกที่ถูกสร้างขึ้นจากการแตกแถวพ่อ — เก็บความสัมพันธ์ "แถวนี้เกิดจาก
แถวไหน" ที่ `posters` ไม่มีคอลัมน์ไหนบอกได้เลย (ADR-0019 D8: การแตกแถวเป็นเครื่องมือ
ไม่ใช่การแก้ข้อมูล และร่องรอยของมันต้องไม่หายไปพร้อมเครื่องที่รันมัน)

ทำไมเป็นตารางแยกไม่ใช่คอลัมน์ self-FK บน `posters` — เหตุผลสามชั้น (ADR-0024 D2):
1. **precedent** — `poster_attribute_reviews` (ADR-0010 D3) ตัดสินไปแล้วว่าฟิลด์ ops
   ตัวที่สองของ `posters` ควรแยกตาราง ไม่ใช่เติมคอลัมน์ทีละตัว
2. `posters` เป็นตารางที่ถูก query ตรงเพื่อ public response — self-FK บนตารางนั้นคือ
   คอลัมน์ที่ `select *` เผลอพาออก public API ได้ง่ายกว่าตารางแยก (ADR-0009 D11)

append-only เหมือน `poster_attribute_reviews` — ไม่มี UPDATE/DELETE บนแถวของตารางนี้
จึงใช้ `CreatedAtMixin` (ไม่มี `updated_at`)

🔴 **แก้ 2026-08-12 (code-critic รอบ 4)** — เหตุผลข้อ 3 เดิม (*"UNIQUE ที่
`child_poster_id` คือด่านกันรันซ้ำสร้างลูกซ้ำจริงที่ระดับ DB"*) **เป็นเท็จ**:
`child_poster_id` เป็น `uuid.uuid4()` สดใหม่ทุกครั้งที่ `split_entry.py` insert
แถวลูก การรันใบงานเดิมซ้ำจึงได้ child คนละ id เสมอ — constraint นั้นไม่มีวันยิงกับ
เคสนี้ (พิสูจน์จริงด้วย probe: รันใบเดิมสองครั้งได้ `poster_splits=2`)
~~ด่านจริงคือ `uq_poster_splits_parent_reason` ด้านล่าง — ดู `__table_args__`~~
🔴 **แก้ 2026-08-15 (ADR-0024 A-D5 · INF-25)** — ข้อความข้างบน**เองก็เป็นเท็จไปแล้ว**:
`uq_poster_splits_parent_reason` ผูกด่านกันรันซ้ำไว้กับ `reason` ซึ่ง workflow จริง
บังคับให้เปลี่ยนทุกรอบ (~4 รอบต่อพ่อหนึ่งคน — A-D4) ⇒ คนต้องคิดข้อความใหม่ทุกรอบ และ
**แก้คำผิดใน `reason` แล้วรันไฟล์เดิมซ้ำสร้างลูกเกินมาได้โดยไม่มีอะไรฟ้อง**
(`screens.yaml` INF-22 G2) ด่านจริงตอนนี้คือ `uq_poster_splits_parent_piece`
(`parent_poster_id` + `piece_no`) ด้านล่าง — `reason` **หลุดออกจากคีย์ทั้งหมดแล้ว**
กลับไปทำหน้าที่เดียวคือบันทึกเหตุผล ไม่ใช่ตัวประกันความไม่ซ้ำอีกต่อไป

ตารางนี้เป็นข้อมูลภายในล้วน ๆ — **ไม่มี endpoint ไหนอ่านมันเลย** (ADR-0024 D2 §เตือน)
ถ้าวันหน้าต้องแสดง "ใบพี่น้อง" ให้ผู้ซื้อ นั่นเป็นมติใหม่ที่ต้องผ่านขั้น contract ก่อน
"""

import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.base import CreatedAtMixin, uuid_pk


class PosterSplit(Base, CreatedAtMixin):
    __tablename__ = "poster_splits"
    __table_args__ = (
        # ใช้ค้นว่า "แถวพ่อนี้เคยถูกแตกออกเป็นลูกกี่แถวแล้ว" — คำถามหลักของตารางนี้
        Index("ix_poster_splits_parent", "parent_poster_id"),
        # กัน insert ผิดพลาดที่ชี้ child ซ้ำ (เกือบเป็นไปไม่ได้เพราะ id เป็น uuid4
        # สดใหม่ทุกแถว) — **ไม่ใช่ด่านกันรันซ้ำ** ดู docstring ของโมดูลนี้ว่าทำไม
        UniqueConstraint("child_poster_id", name="uq_poster_splits_child_poster"),
        # 🔴 ด่านจริงที่กันรันใบงานเดิมซ้ำ (ADR-0024 A-D5 · แก้ 2026-08-15 · INF-25) —
        # แทน uq_poster_splits_parent_reason เดิม (ดูเหตุผลใน docstring ของโมดูล) ·
        # piece_no มาจากไฟล์ใบงานเท่านั้น ไม่ใช่เลขที่ applier คำนวณเอง — ถ้า applier
        # คำนวณเอง รันซ้ำจะได้เลขใหม่ทุกครั้งและด่านนี้ไม่กันอะไรเลย (ดู split_entry.py)
        UniqueConstraint(
            "parent_poster_id", "piece_no", name="uq_poster_splits_parent_piece"
        ),
        # 🔴 piece_no เริ่มที่ 2 เสมอ — แถวพ่อเองคือ "ชิ้นที่ 1" (ADR-0019 D1: 1 แถว
        # 1 ชิ้น) ค่า 0/1 จะเป็นการบันทึกสิ่งที่ขัดกับ D1 ลงตารางตรง ๆ ล็อกไว้ที่ระดับ
        # DB เพราะ AC-3 (INF-25) บอกเองว่าด่านชั้นสคริปต์ไม่ใช่ตัวกันจริง
        CheckConstraint("piece_no >= 2", name="ck_poster_splits_piece_no_min"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    # แถวลูกที่ถูกสร้างจากการแตกครั้งนี้ — UNIQUE (ดู __table_args__)
    child_poster_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("posters.id", ondelete="CASCADE"),
        nullable=False,
    )
    # แถวพ่อที่ถูกแตกออกมา — ไม่ UNIQUE เดี่ยว ๆ เพราะพ่อแตกได้หลายรอบ (หลายแถวลูก) ·
    # คู่กับ piece_no เป็น uq_poster_splits_parent_piece (ดู __table_args__)
    parent_poster_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("posters.id", ondelete="CASCADE"),
        nullable=False,
    )
    # 🔴 ใหม่ 2026-08-15 (ADR-0024 A-D5 · INF-25) — "ชิ้นที่เท่าไหร่ของพ่อคนนี้"
    # เริ่มที่ 2 เพราะแถวพ่อเองคือชิ้นที่ 1 (ADR-0019 D1) · คู่กับ parent_poster_id
    # เป็นคีย์กันรันซ้ำที่ระดับ DB (uq_poster_splits_parent_piece) แทน (parent, reason)
    # เดิมที่ผูกกับข้อความที่ workflow บังคับให้เปลี่ยนทุกรอบ
    # 🔴 **ไม่มี server_default โดยตั้งใจ** — ถ้าคอลัมน์นี้เติมเลขให้เองอัตโนมัติ
    # (เช่น sequence ต่อพ่อ) รันใบงานเดิมซ้ำจะได้เลขใหม่ทุกครั้ง ⇒ ด่านกันรันซ้ำ
    # ไม่กันอะไรเลย (A-D5 §ใครเติม) — ผู้เติมเลขคือ generator (`make_split_sheet.py`
    # อ่าน max(piece_no)+1 จาก DB ต่อพ่อ) ส่วน applier (`split_entry.py`) ต้อง**เขียน
    # ค่าที่มาจากไฟล์เท่านั้น ห้ามคำนวณเอง** — การไม่มี default บังคับให้ต้องส่งค่ามา
    # เสมอ ผิดแล้วพังตอน insert ทันทีแทนที่จะเงียบด้วยเลขที่เครื่องคิดเอง
    piece_no: Mapped[int] = mapped_column(Integer, nullable=False)
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
    # 🔴 แก้ 2026-08-15 (ADR-0024 A-D5 · INF-25) — ช่องนี้**เคย**เป็นครึ่งหนึ่งของ
    # uq_poster_splits_parent_reason ไม่ใช่อีกต่อไป กลับไปทำหน้าที่เดียวคือบันทึก
    # เหตุผลที่คนพิมพ์เอง **ห้ามเป็นส่วนของคีย์หรือ index ใดอีก** — piece_no แทนที่แล้ว
    reason: Mapped[str] = mapped_column(Text, nullable=False)

    # created_at (จาก CreatedAtMixin) = เวลาที่แตกจริง (เวลาที่เครื่องเขียนแถวนี้)
