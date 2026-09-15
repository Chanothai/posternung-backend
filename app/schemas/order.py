"""Pydantic v2 schemas สำหรับ SCR-07 Reserve/Order (ADR-0037) — ตรง docs/api/openapi.yaml

🔴 **ห้ามใส่ docstring บน enum ที่ใช้เป็น field type ในไฟล์นี้** — FastAPI เอา
`__doc__` ของ enum ไปเป็น `description` ใน component ของสัญญา (บทเรียนเดียวกับ
`PosterStatus` ใน `app/schemas/poster.py`) ⇒ ประกาศ `ReservationStatus`/`OrderStatus`
แยกจาก `app.models.enums` แม้ค่าจะตรงกันทุกตัว เพราะตัวใน `app.models.enums.OrderStatus`
มี docstring ภายใน (ADR reference) ที่ไม่ควรหลุดเข้า public contract
"""

import uuid
from datetime import datetime
from decimal import Decimal
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field


class ReservationStatus(str, Enum):
    active = "active"
    expired = "expired"
    converted = "converted"


class OrderStatus(str, Enum):
    AWAITING_PAYMENT = "AWAITING_PAYMENT"
    PAYMENT_REVIEW = "PAYMENT_REVIEW"
    AWAITING_SHIPMENT = "AWAITING_SHIPMENT"
    SHIPPED = "SHIPPED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    DISPUTED = "DISPUTED"
    REFUNDED = "REFUNDED"


class ReservationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    poster_id: uuid.UUID
    user_id: uuid.UUID
    status: ReservationStatus
    expires_at: datetime
    created_at: datetime


class ShippingAddressInput(BaseModel):
    """ที่อยู่จัดส่งที่ผู้ซื้อพิมพ์เองตอน checkout — ตรงกับ `order_shipping_details`
    เป๊ะทั้ง 7 ฟิลด์ (ADR-0020 D5 · D12.1 · ADR-0037 D1)

    🔴 ทั้งก้อนนี้เป็นข้อมูลส่วนบุคคล — ห้าม log ทุกชั้น (ADR-0020 D9 · SCR-07 AC-7)
    """

    recipient_name: str = Field(min_length=1, max_length=120)
    recipient_phone: str = Field(min_length=1, max_length=20)
    address_line: str = Field(min_length=1)
    sub_district: str | None = Field(default=None, max_length=80)
    district: str | None = Field(default=None, max_length=80)
    province: str = Field(min_length=1, max_length=80)
    postal_code: str = Field(min_length=1, max_length=10)


class OrderCreateRequest(BaseModel):
    reservation_id: uuid.UUID
    shipping_address: ShippingAddressInput


class OrderResponse(BaseModel):
    """🔴 ไม่มีข้อมูลส่วนบุคคลแม้แต่ฟิลด์เดียวโดยตั้งใจ (ADR-0020 D5 ชั้น ก) — ที่อยู่
    ที่เพิ่งส่งมาไม่ถูกส่งกลับ ห้ามเพิ่มฟิลด์ที่อยู่เข้ามาที่นี่ (มีเทส closed-world ล็อกไว้)
    """

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    order_no: str = Field(max_length=20)
    poster_id: uuid.UUID
    status: OrderStatus
    item_price: Decimal
    shipping_fee: Decimal
    total_amount: Decimal
    item_title: str = Field(max_length=255)
    created_at: datetime
