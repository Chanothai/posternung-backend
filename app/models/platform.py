"""config ที่แก้ได้โดยไม่ต้อง deploy + outbox ของการแจ้งเตือน"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text, text
from sqlalchemy.dialects.postgresql import ENUM as PgEnum
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.base import CreatedAtMixin, TimestampMixin, uuid_pk
from app.models.enums import NotificationChannel, NotificationStatus

notification_channel_enum = PgEnum(
    NotificationChannel, name="notification_channel", create_type=False
)
notification_status_enum = PgEnum(
    NotificationStatus, name="notification_status", create_type=False
)


class PlatformSetting(Base, TimestampMixin):
    """ค่าที่ **BUSINESS_RULES บังคับว่าต้องแก้ได้โดยไม่ต้องแก้โค้ด**

    | key | ที่มาของข้อบังคับ |
    |---|---|
    | `commission_rate_bps` | BR-L7 — "เขียนเป็น config ค่าเดียวในระบบ แก้ได้ไม่ต้องแก้โค้ด" |
    | `reservation_ttl_minutes` | ADR-0030 D3 — "ค่านี้ต้องเป็น config ตัวเดียว ไม่ hardcode" |
    | `inspection_period_days` | ADR-0020 **A4-D1** — ข้อกำหนดของเจ้าของ 2026-08-22 |
    | `ship_by_business_days` | BR-P3 |
    | `platform_promptpay_id` | ADR-0029 D1 |

    🔴 **ค่าที่ใช้จริงกับธุรกรรมหนึ่ง ๆ ต้องถูก snapshot ลงแถวนั้น** —
    `orders.commission_rate_bps` และ `orders.auto_confirm_due_at` ไม่ได้อ่านจากที่นี่สด ๆ
    การแก้ค่าที่นี่จึงมีผลกับ **ธุรกรรมใหม่เท่านั้น** ตามที่ตั้งใจ

    🔴 **`inspection_period_days` ต้องไม่เกิน 90** — ADR-0020 D13/A4-D3 ล็อกไว้ว่า
    หน้าต่างข้อพิพาทห้ามยาวกว่าระยะเก็บที่อยู่ ไม่งั้นจะมีช่วงที่เรารับปากให้เคลมได้
    ทั้งที่ลบที่อยู่ปลายทางไปแล้ว · **บังคับด้วยเทส ไม่ใช่ด้วยความจำของคนแก้ config**
    """

    __tablename__ = "platform_settings"

    key: Mapped[str] = mapped_column(String(60), primary_key=True)
    value: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    updated_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )


class NotificationOutbox(Base, CreatedAtMixin):
    """INF-33 AC-8 — BR-P8 บังคับแจ้งเตือนทุกจุดเปลี่ยนสถานะทั้งสองฝ่าย

    🔴 **เขียนลงตารางนี้ในทรานแซกชันเดียวกับการเปลี่ยนสถานะ แล้วให้ worker ส่ง**
    ยิง API ตรงจากใน transaction แล้ว LINE/อีเมลล่ม = การแจ้งเตือน**หายถาวรและไม่มีใครรู้**
    — เป็นบทเรียนเดียวกับที่ ADR-0002 Amendment 1 บันทึกไว้ว่า Omise
    *"does not currently guarantee automatic retries"* ⇒ event ที่หายไปหายจริง

    `send_after` ทำให้เลื่อนเวลาส่งได้โดยไม่ต้องมีคิวแยก (เช่นทวงผู้ขายก่อนครบกำหนดส่ง)
    """

    __tablename__ = "notification_outbox"
    __table_args__ = (
        # worker หยิบงานจากตรงนี้ — เฉพาะที่ยังไม่ส่งและถึงเวลาแล้ว
        Index(
            "ix_notification_outbox_pending",
            "send_after",
            postgresql_where=text("status = 'PENDING'"),
        ),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    channel: Mapped[NotificationChannel] = mapped_column(
        notification_channel_enum, nullable=False
    )
    recipient_user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    # ชื่อ template ไม่ใช่ข้อความที่ประกอบแล้ว — ข้อความจริงประกอบตอนส่ง
    # 🔴 ADR-0020 D9: `payload` ห้ามมีชื่อผู้รับ/ที่อยู่/เบอร์ · ใส่ id แล้วให้ตัวส่งไปอ่านเอง
    template_key: Mapped[str] = mapped_column(String(60), nullable=False)
    payload: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    status: Mapped[NotificationStatus] = mapped_column(
        notification_status_enum,
        nullable=False,
        server_default=NotificationStatus.PENDING.value,
    )
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    send_after: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    sent_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
