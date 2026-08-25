"""Pydantic v2 schemas สำหรับ F2 Poster Catalog (ตรง docs/openapi.yaml)."""

import uuid
from enum import Enum
from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import (
    PosterCondition,
    PosterImageKind,
    PosterType,
    ReleaseRegion,
    RestorationStatus,
    SizeFormat,
    VerificationStatus,
)


# ---- Responses ----
class PosterImageResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    url: str
    # ADR-0026 D6 — ออก public API โดยเจตนา · รูป DEFECT ผู้ซื้อเห็นเพราะเป็นหลักฐาน
    # ของ condition_grade (BR-05) และเกราะข้อพิพาทตาม ADR-0002 ที่คืนเงินอัตโนมัติไม่ได้
    kind: PosterImageKind
    is_primary: bool
    sort_order: int


# ══════════════════════════════════════════════════════════════════════════
# สถานะที่ **ลูกค้าเห็นได้** — 3 ค่าเท่าเดิม ไม่ใช่ 7 ค่าของ `app.models.enums.PosterStatus`
# ‹เพิ่ม 2026-08-22 · ADR-0028 INF-32›
#
# ADR-0028 เพิ่มสถานะภายใน 4 ตัว (`draft` · `pending_review` · `rejected` · `delisted`)
# ลง `posters.status` · **ทั้งสี่ตัวไม่ออก public API**:
#   1. เป็นธงงานภายใน — precedent ตรงคือ `needs_review` (ADR-0009 D11) และ
#      `published_at` (ADR-0013 D5) ซึ่งถูกกันออกจาก public API ด้วยเหตุผลเดียวกัน
#   2. บอกเรื่องที่ลูกค้าไม่ควรรู้ — "ใบนี้กำลังรอแอดมินตรวจ" / "ใบนี้ถูกปฏิเสธ"
#      เป็นเรื่องระหว่างผู้ขายกับแพลตฟอร์ม
#   3. ทำให้สัญญาไม่ต้องเปลี่ยน — `docs/api/openapi.yaml` ยังมี 3 ค่าเท่าเดิม
#      ⇒ ไม่ต้องแก้ไฟล์ที่ติด hook · ไม่ต้องแก้ Flutter · ไม่มี drift ให้ INF-31 จับ
#
# 🔴 **ชื่อคลาสต้องเป็น `PosterStatus` เป๊ะ ห้ามเปลี่ยน** — FastAPI ใช้ชื่อคลาสเป็นชื่อ
# component ใน OpenAPI · เปลี่ยนชื่อเมื่อไหร่ `$ref` ในสัญญาเปลี่ยนทันที ซึ่งเป็น
# breaking change ของ contract ทั้งที่ค่าข้างในเหมือนเดิมทุกตัว
# (ลองตั้ง `PublicPosterStatus` มาแล้ว 2026-08-22 → `test_openapi_json_is_fresh` แดง)
#
# 🔴 **ห้ามใส่ docstring** — FastAPI เอาไปเป็น `description` ในสัญญา ⇒ เหตุผลภายใน
# กลายเป็นส่วนหนึ่งของ public contract (บทเรียนเดียวกับ `app/models/enums.py`)
#
# 🔴 **ชื่อชนกับ `app.models.enums.PosterStatus` โดยตั้งใจและมีค่าไม่เท่ากัน** —
# ตัวนั้นคือความจริงของ DB (7 ค่า) ตัวนี้คือสิ่งที่สัญญาประกาศ (3 ค่า)
# ที่ import ตัวไหนให้ดูว่ากำลังพูดถึง *ข้อมูล* หรือ *สัญญา*
# ══════════════════════════════════════════════════════════════════════════
class PosterStatus(str, Enum):
    available = "available"
    reserved = "reserved"
    sold = "sold"


# ชื่อที่อ่านแล้วไม่กำกวมสำหรับที่อื่นที่ต้อง import — ชี้ตัวเดียวกัน
PublicPosterStatus = PosterStatus


class PosterListItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    title: str
    price: Decimal
    status: PosterStatus
    condition_grade: PosterCondition | None
    era_decade: int | None
    studio: str | None
    primary_image_url: str | None = None


class PosterDetailResponse(PosterListItem):
    tmdb_id: int | None
    size: str | None
    description: str | None
    # ADR-0014 D4 — เลิกใช้แล้ว ยังส่งอยู่จนกว่าจะถึง INF-14 (ลบทันทีทำให้แอปพัง)
    # 🔴 ห้าม derive ค่านี้จาก verification_status
    is_authenticated: bool = Field(deprecated=True)
    authenticity_note: str | None
    provenance: str | None
    # --- ADR-0014 D5: ผลการหาแหล่งอ้างอิง — ออก public API ทั้งคู่
    # 🔴 `reference_url` ไม่อยู่ที่นี่ในรอบนี้ — D24 เปิดประตูของ D6/OD-3 แล้ว แต่ยังไม่มี
    #    ใครกรอกค่าสักแถว (writer คือ INF-13) การเพิ่มฟิลด์ว่างเข้าสัญญาไม่ได้ให้อะไร
    # 🔴 อยู่ในสัญญา ≠ อนุญาตให้เอาไปแสดงบนจอ — D5.1 บล็อกฝั่งแอปไว้จนกว่า OD-2 จะปิด
    # ‹`reference_note` เดิมชื่อ `verification_note` — เปลี่ยนที่ D22 · breaking change›
    verification_status: VerificationStatus | None
    reference_note: str | None
    # --- ADR-0009: คุณลักษณะเชิงพรรณนา (9 ฟิลด์ — ไม่รวม needs_review ตาม D11
    # รวม release_date_text ที่เพิ่มเข้ามาตาม D13 amendment แล้ว) ---
    poster_type: PosterType | None
    release_region: ReleaseRegion | None
    # ADR-0009 D13 (amendment) — ข้อความวันฉายตามที่พิมพ์บนใบ (observed) ไม่ตีความ
    release_date_text: str | None
    # วันฉายที่ "พิมพ์อยู่บนตัวใบ" ไม่ใช่วันฉายจริงตามประวัติศาสตร์ — ADR-0009 D3
    release_date: date | None
    # ปีใน billing block ของตัวใบ — ไม่ใช่ปีหนัง (year) และไม่ใช่ print_year — ADR-0009 D3
    copyright_year: int | None
    size_format: SizeFormat | None
    # ปีที่หนังฉาย — คนละอย่างกับ era_decade (ทศวรรษ) ที่อยู่ใน PosterListItem — ADR-0009 D3
    year: int | None
    restoration_status: RestorationStatus | None
    restoration_note: str | None
    images: list[PosterImageResponse]
    created_at: datetime
    # ADR-0013 Amendment A-D3 / ADR-0025 — เวลาที่ "คนตัดสินว่าขายไปแล้ว" ไม่ใช่เวลาที่
    # สคริปต์รัน · writer เดียวคือ mark_sold() ซึ่งเขียนพร้อม status ในทรานแซกชันเดียว
    # 🔴 อยู่ที่นี่เท่านั้น ไม่อยู่ใน PosterListItem (contract GATE 2 ของ INF-24 —
    # ถอดออกจาก response ทีหลัง = breaking, เพิ่มเข้าไป = ไม่ breaking)
    sold_at: datetime | None


class PaginatedPosterList(BaseModel):
    items: list[PosterListItem]
    total: int
    limit: int
    offset: int


# ---- Requests ----
class PosterFilterParams(BaseModel):
    era_decade: int | None = None
    condition_grade: PosterCondition | None = None
    min_price: Decimal | None = Field(default=None, ge=0)
    max_price: Decimal | None = Field(default=None, ge=0)
    in_stock_only: bool = False
    limit: int = Field(default=20, ge=1, le=100)
    offset: int = Field(default=0, ge=0)
