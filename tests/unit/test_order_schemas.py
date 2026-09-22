"""SCR-07 สไลซ์ A · A1 — schema closed-world เทียบกับ `docs/api/openapi.yaml`

🔴 **ปิดด้วย set เทียบทั้งก้อน ไม่ใช่ assert ทีละชื่อ** (`test-quality` §4) — assert
ทีละชื่อจับ "ฟิลด์ที่ถูกเพิ่มเข้ามา" ไม่ได้เลย เช่นถ้ามีใครเผลอเติม `recipient_name`
เข้า `OrderResponse` เทสแบบ "เช็คว่ามี id/order_no/... ครบ" จะยังเขียวต่อไป

mutation ที่ต้องตาย (พิสูจน์จริงระหว่างพัฒนา ไม่ใช่แค่คิดว่าน่าจะจับได้ — ดูรายงาน
ท้ายงาน §mutation): เติม `recipient_name: str | None = None` เข้า `OrderResponse`
ใน `app/schemas/order.py` แล้วรันไฟล์นี้ → `test_order_response_fields_match_the_contract_exactly`
ต้องแดง
"""

from app.schemas.order import (
    OrderCreateRequest,
    OrderResponse,
    ReservationResponse,
    ShippingAddressInput,
)

# ตรงกับ `required` ของ OrderResponse ใน docs/api/openapi.yaml เป๊ะ (9 ฟิลด์ —
# schema นี้ไม่มี optional field เลยสักตัว ⇒ required set == property set ทั้งหมด)
_CONTRACT_ORDER_RESPONSE_FIELDS = {
    "id",
    "order_no",
    "poster_id",
    "status",
    "item_price",
    "shipping_fee",
    "total_amount",
    "item_title",
    "created_at",
}

# ที่อยู่ทั้ง 7 ฟิลด์ของ ShippingAddressInput/order_shipping_details — ต้องไม่โผล่ใน
# OrderResponse แม้แต่ตัวเดียว (ADR-0020 D5 ชั้น ก)
_ADDRESS_FIELD_NAMES = set(ShippingAddressInput.model_fields) | {"shipping_address"}

_CONTRACT_RESERVATION_RESPONSE_FIELDS = {
    "id",
    "poster_id",
    "user_id",
    "status",
    "expires_at",
    "created_at",
}

_CONTRACT_SHIPPING_ADDRESS_INPUT_REQUIRED = {
    "recipient_name",
    "recipient_phone",
    "address_line",
    "province",
    "postal_code",
}


def test_order_response_fields_match_the_contract_exactly() -> None:
    assert set(OrderResponse.model_fields) == _CONTRACT_ORDER_RESPONSE_FIELDS


def test_order_response_carries_no_shipping_address_field() -> None:
    """ADR-0020 D5 ชั้น ก — assertion เชิงลบตรง ๆ แยกจาก closed-world ด้านบน
    เพื่อให้ชื่อเทสสื่อเจตนาเฉพาะเรื่องนี้ (SCR-07 ต้องมีเทสยืนยันเชิงลบข้อนี้)"""
    leaked = set(OrderResponse.model_fields) & _ADDRESS_FIELD_NAMES
    assert not leaked, f"OrderResponse มีฟิลด์ที่อยู่หลุดเข้ามา: {leaked}"


def test_reservation_response_fields_match_the_contract_exactly() -> None:
    assert (
        set(ReservationResponse.model_fields) == _CONTRACT_RESERVATION_RESPONSE_FIELDS
    )


def test_order_create_request_requires_reservation_id_and_shipping_address() -> None:
    assert set(OrderCreateRequest.model_fields) == {
        "reservation_id",
        "shipping_address",
    }
    required = {
        name
        for name, field in OrderCreateRequest.model_fields.items()
        if field.is_required()
    }
    assert required == {"reservation_id", "shipping_address"}


def test_shipping_address_input_required_fields_match_the_contract() -> None:
    required = {
        name
        for name, field in ShippingAddressInput.model_fields.items()
        if field.is_required()
    }
    assert required == _CONTRACT_SHIPPING_ADDRESS_INPUT_REQUIRED
    # sub_district/district เป็น optional — เช็คเชิงลบว่าไม่ได้อยู่ใน required
    assert "sub_district" not in required
    assert "district" not in required
