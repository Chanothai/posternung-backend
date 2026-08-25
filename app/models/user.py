"""F1 Authentication models — users, refresh_tokens, oauth_identities.

ไม่มี local password/OTP แล้ว — sign-in ทุกวิธีทำที่ Firebase ฝั่ง client
(ดู services/auth_service.py) backend เก็บแค่ตัวตน + refresh token ของ JWT ตัวเอง
"""

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import CITEXT
from sqlalchemy.dialects.postgresql import ENUM as PgEnum
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.base import CreatedAtMixin, TimestampMixin, uuid_pk
from app.models.enums import OAuthProvider

# create_type=False → เราจัดการ CREATE/DROP TYPE เองใน migration (ดู plan §D)
oauth_provider_enum = PgEnum(OAuthProvider, name="oauth_provider", create_type=False)


class User(Base, TimestampMixin):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = uuid_pk()
    # nullable — phone-only user (Firebase Phone Auth) ไม่มี email; unique บน nullable
    # OK (Postgres ยอมหลาย NULL) — social/email user ยังมี email ตามปกติ
    email: Mapped[str | None] = mapped_column(CITEXT, unique=True, nullable=True)
    phone: Mapped[str | None] = mapped_column(String(20), nullable=True)
    is_verified: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false"
    )
    # ที่เก็บสิทธิ์แอดมินเพียงที่เดียวของระบบ (ADR-0031 D1 = A-1)
    #
    # 🔴 ห้ามเพิ่มคอลัมน์สิทธิ์ตัวที่สอง (is_moderator ฯลฯ) เด็ดขาด — เงื่อนไขย้ายบ้าน
    # ของ ADR-0031 D1 เขียนไว้ว่า วันที่มีคนที่สองเข้ามาช่วยงานแอดมิน "และเขาไม่ควร
    # ทำได้ทุกอย่างที่เจ้าของทำได้" ให้ย้ายไปตาราง admin_grants ทั้งก้อน
    # การเติมคอลัมน์ที่สองคือทางที่ดูถูกกว่าเฉพาะวันแรก แล้วแพงตลอดไป
    is_admin: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false"
    )


class RefreshToken(Base, CreatedAtMixin):
    __tablename__ = "refresh_tokens"
    __table_args__ = (Index("ix_refresh_tokens_user", "user_id"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    token_hash: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    revoked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class OAuthIdentity(Base, CreatedAtMixin):
    """เชื่อม user กับบัญชี social provider (เช่น Google) — แยกตารางเผื่อรองรับ
    provider อื่นในอนาคต (Apple/Facebook) และ user คนเดียว link ได้หลาย provider
    โดยไม่ต้อง migrate schema ของ users ซ้ำ."""

    __tablename__ = "oauth_identities"
    __table_args__ = (
        # provider + provider_user_id คู่เดียวกันต้อง map ไป user เดียวเท่านั้น
        UniqueConstraint(
            "provider", "provider_user_id", name="uq_oauth_identities_provider_user"
        ),
        Index("ix_oauth_identities_user", "user_id"),
        # ค้นด้วย Firebase uid อย่างเดียว (ข้าม provider) เพื่อจับคู่บัญชีที่ link หลาย
        # sign-in method — unique constraint ข้างบนใช้ไม่ได้เพราะ provider เป็นคอลัมน์นำ
        Index("ix_oauth_identities_provider_user_id", "provider_user_id"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    provider: Mapped[OAuthProvider] = mapped_column(oauth_provider_enum, nullable=False)
    # "sub" claim ของ Google — ตัวระบุบัญชีที่เสถียร (ไม่ใช้ email เป็น key เพราะเปลี่ยนได้)
    provider_user_id: Mapped[str] = mapped_column(String(255), nullable=False)
    # email ตอน link ไว้เพื่อ audit/debug เท่านั้น ไม่ใช่ source of truth (ดูที่ users.email)
    # nullable — phone provider ไม่มี email
    email: Mapped[str | None] = mapped_column(CITEXT, nullable=True)
