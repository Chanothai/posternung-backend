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


# --- ADR-0014 D3: ผลการเทียบใบจริงกับฐานข้อมูลอ้างอิง — ไม่ใช่การรับรองความแท้
# 🔴 ไม่มีค่าที่แปลว่า "ยังไม่ตรวจ" — `NULL` แปลว่านั้นอยู่แล้ว (ADR-0009 D2)
# 🔴 `DISCREPANCY_FOUND` ไม่ได้แปลว่าของปลอม — ต่างจากฉบับอ้างอิงเฉย ๆ
# ใครเขียนค่าพวกนี้ได้บ้าง → ADR-0014 D7 (คนเท่านั้น)


class VerificationStatus(str, enum.Enum):
    # ADR-0014 §Amendment D11-D13 (2026-08-07) — ขอบเขตการเทียบคือ **อาร์ตเวิร์กเท่านั้น**
    # migration a7c31e5f9b04 · ห้ามเพิ่ม NOT_CHECKED (D3/D12 — NULL ทำหน้าที่นั้นอยู่)
    ARTWORK_MATCHED = "ARTWORK_MATCHED"
    DISCREPANCY_FOUND = "DISCREPANCY_FOUND"
    NO_REFERENCE_FOUND = "NO_REFERENCE_FOUND"
    UNKNOWN = "UNKNOWN"
