"""BR-D4 · BR-D6 — รีวิวหลังจบธุรกรรม และรายการโปรด (SCR-17)"""

import uuid

from sqlalchemy import CheckConstraint, ForeignKey, Index, SmallInteger, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.base import CreatedAtMixin, uuid_pk


class Review(Base, CreatedAtMixin):
    """1 ออร์เดอร์ = 1 รีวิว · เขียนได้เฉพาะออร์เดอร์ที่ `COMPLETED` (SCR-17 AC-1)

    🔴 เงื่อนไข "ออร์เดอร์ต้อง COMPLETED" บังคับที่ service ไม่ใช่ CHECK —
    CHECK ข้ามตารางทำไม่ได้ใน PostgreSQL และ trigger เป็นแหล่งความจริงที่ซ่อนอยู่
    ⇒ ต้องมีเทสเชิงลบว่ารีวิวออร์เดอร์ที่ยังไม่จบไม่ได้

    ‹proposal §6 · known_gap ของ SCR-17› MVP: **แก้ไม่ได้ ลบไม่ได้ ผู้ขายตอบไม่ได้**
    จึงไม่มี `updated_at` และไม่มีตารางคำตอบ — เพิ่มทีหลังต้องมีมติก่อน
    """

    __tablename__ = "reviews"
    __table_args__ = (
        CheckConstraint("rating BETWEEN 1 AND 5", name="ck_reviews_rating_range"),
        Index("ix_reviews_seller_created", "seller_id", "created_at"),
    )

    # PK คือ order_id เอง — บังคับ "1 ออร์เดอร์ 1 รีวิว" ที่ระดับ DB ไม่ใช่ที่ service
    order_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("orders.id", ondelete="CASCADE"), primary_key=True
    )
    reviewer_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    seller_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("seller_profiles.id", ondelete="CASCADE"), nullable=False
    )
    rating: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)


class Favorite(Base, CreatedAtMixin):
    """BR-D6 — บันทึกรายการโปรด

    🔴 **ยังไม่มีการแจ้งเตือนราคา / Want List อัตโนมัติ** — อยู่ใน `docs/PHASE2.md`
    ตารางนี้คือฐานที่ฟีเจอร์นั้นจะต่อยอด ไม่ใช่ฟีเจอร์นั้นเอง
    """

    __tablename__ = "favorites"
    __table_args__ = (
        Index("uq_favorite_user_poster", "user_id", "poster_id", unique=True),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    # CASCADE ได้เพราะรายการโปรดไม่ใช่หลักฐานทางธุรกรรม ต่างจาก orders ที่เป็น RESTRICT
    poster_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("posters.id", ondelete="CASCADE"), nullable=False
    )
