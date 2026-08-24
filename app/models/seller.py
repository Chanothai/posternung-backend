"""ADR-0028 — ผู้ขาย + KYC (`seller_profiles`)

🔴 **ตารางนี้เก็บข้อมูลส่วนบุคคลอ่อนไหวที่สุดในระบบ** — เลขบัญชีธนาคารและภาพบัตรประชาชน
อยู่ภายใต้ ADR-0020 (PDPA) เต็มรูปแบบ · **ห้ามออก public API เด็ดขาด** และห้ามอยู่ใน
serializer เดียวกับโปรไฟล์ผู้ขายที่คนทั่วไปเห็น (ADR-0028 D6)

ADR-0028 D2 หยุดที่ขั้น 1 ของ `docs/database-design.md` §8.3 — มีตาราง `sellers` แล้ว
แต่ **ไม่แยก `poster_editions` / `listings`** เพราะของทุกชิ้น unique (BR-L2) ทำให้
`posters` เป็นตาราง listing อยู่แล้วโดยพฤตินัย
"""

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import ENUM as PgEnum
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.base import TimestampMixin, uuid_pk
from app.models.enums import KycStatus

kyc_status_enum = PgEnum(KycStatus, name="kyc_status", create_type=False)

# ══════════════════════════════════════════════════════════════════════════
# ADR-0028 D3 — "house account" คือแถว singleton ของร้านเราเอง ที่ 113 แถวเดิม
# ถูก backfill มาให้ · **id เป็นค่าคงที่โดยตั้งใจ ไม่ใช่ gen_random_uuid()**
#
# เหตุผล: มันเป็นแถวเดียวที่ต้องอ้างถึงได้จาก migration · เทส · สคริปต์ operator
# ทั้ง 8 เส้น และจากทุก environment (dev · sit · production) — ถ้า id ต่างกันแต่ละที่
# ทุกที่ที่อ้างถึงมันต้อง query หาก่อนใช้ ซึ่งแปลว่า **โค้ดที่ลืม query จะไปเจอ
# แถวผิดแบบเงียบ ๆ** · ค่าคงที่ทำให้ "ผิดที่ไหน" กลายเป็น FK violation ที่ดังทันที
#
# 🔴 **ห้ามใช้ id พวกนี้เป็น default ของคอลัมน์ใด ๆ** — `posters.seller_id` ตั้งใจ
# ไม่มี server_default เพราะการลืมระบุผู้ขายต้องเป็น error ไม่ใช่การยกของให้ร้านเรา
# ══════════════════════════════════════════════════════════════════════════
HOUSE_USER_ID = uuid.UUID("00000000-0000-4000-8000-000000000001")
HOUSE_SELLER_ID = uuid.UUID("00000000-0000-4000-8000-000000000002")
HOUSE_EMAIL = "house@posternung.local"


class SellerProfile(Base, TimestampMixin):
    __tablename__ = "seller_profiles"
    __table_args__ = (
        # อัตราคอมมิชชั่นเป็น bps (10% = 1000) — ห้ามใช้ทศนิยมเพื่อไม่ให้เกิดปัญหาปัดเศษ
        # NULL = ใช้ค่ากลางจาก platform_settings (BR-L7)
        CheckConstraint(
            "commission_rate_bps IS NULL OR "
            "(commission_rate_bps >= 0 AND commission_rate_bps <= 10000)",
            name="ck_seller_profiles_commission_rate_bps_range",
        ),
        # ปฏิเสธแล้วต้องบอกได้ว่าทำไม — ผู้ขายต้องแก้แล้วส่งใหม่ได้ (SCR-12 AC-5)
        CheckConstraint(
            "kyc_status <> 'REJECTED' OR kyc_rejection_reason IS NOT NULL",
            name="ck_seller_profiles_rejected_requires_reason",
        ),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    # 1 user = ผู้ขายได้ 1 โปรไฟล์ · ลบ user แล้วโปรไฟล์ไปด้วย (ADR-0020 สิทธิ์ลบข้อมูล)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    # ชื่อร้านที่คนอื่นเห็น — ตัวเดียวในตารางนี้ที่ออก public API ได้
    display_name: Mapped[str] = mapped_column(String(80), nullable=False)

    # --- 🔴 ตั้งแต่บรรทัดนี้ลงไปห้ามออก public API ทุกฟิลด์ (ADR-0028 D6 · ADR-0020) ---
    real_name: Mapped[str] = mapped_column(String(120), nullable=False)
    # OTP ผ่าน Firebase (BR-L1) — NULL = ยังไม่ยืนยัน ไม่ใช่ไม่มีเบอร์
    phone_verified_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    bank_name: Mapped[str] = mapped_column(String(80), nullable=False)
    bank_account_name: Mapped[str] = mapped_column(String(120), nullable=False)
    # proposal §6 Q1 — เก็บ plaintext ใน DB ที่ไม่เปิด public และไม่ออก API
    # (เข้ารหัสระดับคอลัมน์เพิ่มความซับซ้อนของ key management ที่คนเดียวดูแลยาก)
    bank_account_no: Mapped[str] = mapped_column(String(30), nullable=False)
    # 🔴 **key ใน private storage เท่านั้น ห้ามเป็น URL ที่เปิดได้**
    # precedent: ADR-0006 (poster image storage key) — เหตุผลเดียวกันแต่เดิมพันสูงกว่ามาก
    id_card_image_key: Mapped[str | None] = mapped_column(Text, nullable=True)

    kyc_status: Mapped[KycStatus] = mapped_column(
        kyc_status_enum, nullable=False, server_default=KycStatus.PENDING.value
    )
    kyc_reviewed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    kyc_reviewed_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    kyc_rejection_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    # override รายผู้ขาย — ผู้ขายรุ่นก่อตั้ง 5% = 500 (BR-L7)
    # NULL = ใช้ค่ากลาง · 🔴 อัตราที่ "ใช้จริง" ถูก snapshot ลงแถว order ตอนสร้าง
    #        การแก้ค่านี้ภายหลังห้ามกระทบยอดของธุรกรรมที่เกิดไปแล้ว
    commission_rate_bps: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # ADR-0028 D3 — ร้านของเจ้าของเอง ที่ 113 แถวเดิมถูก backfill มาให้
    # 🔴 ใช้กันไม่ให้คิดคอมและไม่ให้เข้าคิว payout (proposal §6 Q3) — ไม่ใช่ธงแสดงผล
    is_house_account: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false"
    )
