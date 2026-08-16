"""Python enums ที่ map ตรงกับ PostgreSQL ENUM types (ดู docs/database-design.md §3).

ค่าต้องตรงกับ openapi.yaml components.schemas เป๊ะ — เป็น contract เดียวกัน
"""

import enum


class PosterStatus(str, enum.Enum):
    available = "available"
    reserved = "reserved"
    sold = "sold"


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
