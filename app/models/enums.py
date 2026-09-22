"""Python enums ที่ map ตรงกับ PostgreSQL ENUM types (ดู docs/database-design.md §3).

ค่าต้องตรงกับ openapi.yaml components.schemas เป๊ะ — เป็น contract เดียวกัน
"""

import enum


# เครื่องแรกของ state machine (เครื่องที่สองคือ `OrderStatus`) — ADR-0028 D4
#
# 🔴 **ลำดับที่ประกาศ = ลำดับใน PostgreSQL** (enum เรียงตามลำดับประกาศ ไม่ใช่ตัวอักษร
# — ADR-0003 อธิบายไว้กับ `poster_condition`) · ลำดับนี้ตรงกับวงจรชีวิตจริง และตรงกับ
# migration `b1a7c3d9e024` ที่ใช้ `BEFORE`/`AFTER` วางไว้เป๊ะ
#
# 🔴 **`available` คือสิ่งที่ BUSINESS_RULES เรียกว่า "Active"** — ไม่เปลี่ยนชื่อ
# เพราะ rename enum value กระทบ `openapi.yaml` + Flutter + เทสทั้งชุดในรอบเดียว
#
# 🔴 **เขียนเป็นคอมเมนต์ ไม่ใช่ docstring โดยตั้งใจ** — FastAPI เอา docstring ของ enum
# ไปใส่เป็น `description` ใน OpenAPI ⇒ เหตุผลภายในจะกลายเป็นส่วนหนึ่งของ **สัญญา
# สาธารณะ** และทำให้ `openapi.json` ต่างจาก `docs/api/openapi.yaml` ทันที
# (พบตอนรัน `test_openapi_json_is_fresh` 2026-08-22)
#
# 🔴 **ค่า 4 ตัวที่เพิ่ม 2026-08-22 เป็นสถานะภายใน ไม่ออก public API** — ตัวที่ออก
# คือ `PublicPosterStatus` ใน `app/schemas/poster.py` ซึ่งมี 3 ค่าเท่าเดิม
# (precedent: ADR-0009 D11 · ADR-0013 D5 — ธงงานภายในไม่ออก public API)
class PosterStatus(str, enum.Enum):

    # ก่อนขึ้นขาย — ยังไม่ต้องมี `approved_at` (BR-L6)
    draft = "draft"
    pending_review = "pending_review"
    rejected = "rejected"
    # ขึ้นขายแล้ว — ทั้งสามค่านี้บังคับว่าต้องมี `approved_at`
    available = "available"
    reserved = "reserved"
    sold = "sold"
    # ผู้ขายถอนเอง — ทำได้ทุกสถานะก่อนขาย **ยกเว้น `reserved` และ `sold`** (BR-L5)
    delisted = "delisted"


class ReservationStatus(str, enum.Enum):
    active = "active"
    expired = "expired"
    converted = "converted"


class PosterCondition(str, enum.Enum):
    mint = "mint"
    near_mint = "near_mint"
    very_fine = "very_fine"
    fine = "fine"
    very_good = "very_good"
    good = "good"
    fair = "fair"
    poor = "poor"


class OAuthProvider(str, enum.Enum):
    # map จาก Firebase token claim firebase.sign_in_provider:
    #   google.com -> google · password -> password · phone -> phone
    google = "google"
    password = "password"
    phone = "phone"


# --- ADR-0009: คุณลักษณะเชิงพรรณนาของโปสเตอร์ — ค่าใหม่เป็น UPPERCASE ตาม
# skill poster-database §5 (enum เดิม 4 ตัวข้างบนยังเป็น lowercase ห้ามแตะ)


class PosterType(str, enum.Enum):
    TEASER = "TEASER"
    ADVANCE = "ADVANCE"
    THEATRICAL = "THEATRICAL"
    RERELEASE = "RERELEASE"
    UNKNOWN = "UNKNOWN"


class ReleaseRegion(str, enum.Enum):
    TH = "TH"
    US = "US"
    JP = "JP"
    UK = "UK"
    INTL = "INTL"
    UNKNOWN = "UNKNOWN"


class SizeFormat(str, enum.Enum):
    ONE_SHEET = "ONE_SHEET"
    HALF_SHEET = "HALF_SHEET"
    INSERT = "INSERT"
    QUAD = "QUAD"
    OTHER = "OTHER"
    UNKNOWN = "UNKNOWN"


class RestorationStatus(str, enum.Enum):
    NONE = "NONE"
    RESTORED = "RESTORED"
    LINEN_BACKED = "LINEN_BACKED"
    UNKNOWN = "UNKNOWN"


# --- ADR-0014 D21: **เปิดหาแหล่งอ้างอิงแล้วเจอหรือไม่** — ไม่ใช่การรับรองความแท้
# และไม่ใช่การตัดสินว่าใบไหนต่างจากมาตรฐาน (D21 ตัด `DISCREPANCY_FOUND` ออกเพราะการบอกว่า
# "ต่าง" คือการอ้างว่ารู้ว่าอะไรคือมาตรฐาน ซึ่งไม่ใช่สิ่งที่ร้านนี้ทำ)
# 🔴 ไม่มีค่าที่แปลว่า "ยังไม่ตรวจ" — `NULL` คือ `NOT_CHECKED` (D21 · ADR-0009 D2)
# ใครเขียนค่าพวกนี้ได้บ้าง → ADR-0014 D7 (คนเท่านั้น · AI ห้ามตลอดกาล)


class VerificationStatus(str, enum.Enum):
    # ADR-0014 §Amendment 2 D21/D22 (2026-08-07) — ยุบจาก 4 ค่าเหลือ 2 (+ NULL)
    # migration f4c8a1e07b93 · ห้ามเพิ่ม NOT_CHECKED เป็นสมาชิก (D21 — NULL ทำหน้าที่นั้น)
    # 🔴 ห้าม derive ด้วยมือ — สคริปต์ของ INF-13 derive จาก reference_url/reference_note (D22)
    REFERENCE_FOUND = "REFERENCE_FOUND"
    NO_REFERENCE_FOUND = "NO_REFERENCE_FOUND"


# --- ADR-0026: ชนิดของรูป (BLOCK 5.5 ของ ADR-0006 ถูกเปิด "บางส่วน")
# 🔴 ค่าต้องตรงกับ component `PosterImageKind` ใน ../workspace/docs/api/openapi.yaml เป๊ะ


class PosterImageKind(str, enum.Enum):
    # ADR-0026 D1 — สามค่านี้เท่านั้น · "ผิวกระดาษ"(raking) / corner / UV / detail
    # ถูกกันไว้โดยตั้งใจ ไม่ใช่ตกหล่น การเพิ่มค่าต้องเป็น amendment ของ ADR-0026
    # (พร้อมแถบ sort_order ถัดไปตาม D5) ไม่ใช่เติมสมาชิกเงียบ ๆ
    # 🔴 D2 — UPPERCASE ทุกชั้น (DB · API · โมเดล) · ชื่อไฟล์ที่คนถ่ายตั้งเป็น lowercase
    # และแปลงที่ขอบเดียวคือเส้นที่ 8 เท่านั้น ห้ามให้ชั้นอื่นรับสองรูปแบบ
    FRONT = "FRONT"
    BACK = "BACK"
    DEFECT = "DEFECT"


# ══════════════════════════════════════════════════════════════════════════
# ADR-0028 (marketplace) · ADR-0029 (โอน+สลิป) · ADR-0030 (ซื้อเลย ไม่มีตะกร้า)
# เพิ่ม 2026-08-22 — INF-32 · ค่าทั้งหมด UPPERCASE ตาม skill `poster-database` §5
# 🔴 ค่าต้องตรงกับ component ใน ../posternung-workspace/docs/api/openapi.yaml เป๊ะ
#    (วันนี้ยังไม่มีใน contract — ขั้น contract ของ /feature เป็นคนใส่ ไม่ใช่ไฟล์นี้)
# ══════════════════════════════════════════════════════════════════════════


class PosterTier(str, enum.Enum):
    """BR-L3 — ประเภทของใบ · **บังคับเลือก ห้ามคลุมเครือ**

    🔴 **ไม่มีค่า `UNKNOWN` โดยตั้งใจ** — ต่างจาก enum ของ ADR-0009 ที่ยอมให้ `UNKNOWN`
    เพราะพวกนั้นเป็น *คุณลักษณะที่อาจไม่มีใครรู้* ส่วน tier เป็น *สิ่งที่ผู้ขายต้องรู้
    ก่อนขาย* — ถ้าไม่รู้แปลว่ายังไม่พร้อมขาย ไม่ใช่ว่าต้องมีค่าให้เลือกว่าไม่รู้
    · `NULL` = ยังไม่มีใครกรอก (แถวที่รอใบงาน Q2) **ไม่ใช่** "ไม่แน่ใจ"
    """

    ORIGINAL_VINTAGE = "ORIGINAL_VINTAGE"
    ORIGINAL_MODERN = "ORIGINAL_MODERN"
    REPRINT = "REPRINT"


class KycStatus(str, enum.Enum):
    """BR-L1 — สถานะการยืนยันตัวตนผู้ขาย · `APPROVED` เท่านั้นที่ลงขายได้ (BR-L6)"""

    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class OrderStatus(str, enum.Enum):
    """ADR-0028 D4 — เครื่องที่สองของ state machine (เครื่องแรกคือ `PosterStatus`)

    🔴 สถานะปลายทางคือ `COMPLETED` · `CANCELLED` · `REFUNDED` เท่านั้น — ออกจากสามตัวนี้ไม่ได้
    """

    AWAITING_PAYMENT = "AWAITING_PAYMENT"
    PAYMENT_REVIEW = "PAYMENT_REVIEW"
    AWAITING_SHIPMENT = "AWAITING_SHIPMENT"
    SHIPPED = "SHIPPED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    DISPUTED = "DISPUTED"
    REFUNDED = "REFUNDED"


class PaymentStatus(str, enum.Enum):
    """ADR-0029 D3 — สลิปคือ **การอ้าง** ไม่ใช่หลักฐานว่าเงินเข้า

    `CLAIMED` = ผู้ซื้อบอกว่าโอนแล้ว · ระบบยังไม่เชื่ออะไรทั้งนั้น
    `VERIFIED` = แอดมินเห็นยอดในบัญชีจริงแล้ว (ไม่ใช่เห็นแค่ภาพสลิป)
    """

    AWAITING = "AWAITING"
    CLAIMED = "CLAIMED"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"


class DeliveryConfirmActor(str, enum.Enum):
    """ADR-0020 **Amendment 4 · A4-D1** — ใครเป็นคนยืนยันว่าของถึงมือผู้ซื้อ

    D14.1 เดิมมี actor เดียว (เจ้าของ) ซึ่งใช้กับ marketplace ไม่ได้เพราะเจ้าของ
    แพลตฟอร์มไม่มีทางรู้ว่าของของผู้ขายรายอื่นถึงหรือยัง

    🔴 `SYSTEM_AUTO` **ไม่ใช่ค่าที่ปลอดภัยที่สุด — เป็นค่าที่เสี่ยงที่สุด**
    แปลว่าไม่มีมนุษย์คนไหนยืนยันว่าของถึงจริง ⇒ ต้องนับและแสดงจำนวนแยก (SCR-15 AC-7)
    """

    BUYER = "BUYER"
    SYSTEM_AUTO = "SYSTEM_AUTO"
    ADMIN = "ADMIN"


class DisputeStatus(str, enum.Enum):
    """BR-P6 — เปิดแล้วเงินถูกอายัดทันที (ตัดออกจากคิวจ่าย)"""

    OPEN = "OPEN"
    RESOLVED_REFUND = "RESOLVED_REFUND"
    RESOLVED_RELEASE = "RESOLVED_RELEASE"
    REJECTED = "REJECTED"


class PayoutStatus(str, enum.Enum):
    """BR-P5 — จ่ายเป็นรอบอังคาร/ศุกร์ · ระบบทำคิว **คนโอนเอง** (ADR-0029 D7)"""

    QUEUED = "QUEUED"
    PAID = "PAID"
    FAILED = "FAILED"


class NotificationChannel(str, enum.Enum):
    """BR-P8 — แจ้งเตือนทั้งสองฝ่ายทุกจุดเปลี่ยนสถานะ"""

    EMAIL = "EMAIL"
    LINE = "LINE"


class NotificationStatus(str, enum.Enum):
    """INF-33 AC-8 — outbox pattern

    🔴 เขียนลงตารางใน **ทรานแซกชันเดียวกับการเปลี่ยนสถานะ** แล้วให้ worker ส่ง
    ยิง API ตรงจากใน transaction แล้วปลายทางล่ม = การแจ้งเตือน**หายถาวรและไม่มีใครรู้**
    (บทเรียนเดียวกับ ADR-0002 Amendment 1 เรื่อง webhook ที่ไม่รับประกัน retry)
    """

    PENDING = "PENDING"
    SENT = "SENT"
    FAILED = "FAILED"
