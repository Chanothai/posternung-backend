"""SCR-07 · code-critic รอบ 1 **F1 (High)** — `echo=True` (DEBUG=true) ต้องไม่ log
ชื่อผู้รับ/เบอร์/ที่อยู่ (ADR-0020 D9 · security-baseline §2)

`app/core/database.py` สร้าง `engine` เป็น module-level object ตอน import ด้วยค่า
`echo=settings.DEBUG` **ที่ freeze ไปแล้ว ณ ตอนนั้น** — การตั้ง `settings.DEBUG = True`
ทีหลัง (แบบที่ `client`/`real_client` fixture ใน `tests/conftest.py` ทำ) **ไม่มีผล
ย้อนกลับไปเปลี่ยน `echo` ของ engine ตัวที่ import มาแล้ว** ⇒ เทสที่พึ่ง engine ตัวนั้น
ไม่มีวันแตะเส้นทาง echo=True เลย (ยืนยันจาก code-critic รอบ 1 — จุดที่
`test_create_order_does_not_log_any_personal_data` ใน `test_orders_api.py` พลาดไป)

เทสนี้จึงสร้าง engine ของตัวเองตรง ๆ ด้วย `echo=True` (จำลอง production/SIT ที่
`DEBUG=true`) แล้วเรียก `order_service.create_order()` จริงผ่าน session ที่ผูกกับ
engine ตัวนั้น — พิสูจน์ว่า `hide_parameters=True` (ที่เพิ่งเติมใน `database.py`)
ตัด bound parameters ออกจาก log ของ SQLAlchemy echo จริง ไม่ใช่แค่ปิด echo เฉย ๆ
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.models.enums import PosterCondition, PosterStatus
from app.models.poster import Poster
from app.models.seller import SellerProfile
from app.models.user import User
from app.schemas.order import ShippingAddressInput
from app.services import order_service
from tests.conftest import TEST_DATABASE_URL

NOW = datetime(2026, 3, 2, 4, 0, tzinfo=UTC)
PUBLISHED_AT = datetime(2026, 1, 1, tzinfo=UTC)
APPROVED_AT = datetime(2026, 1, 2, tzinfo=UTC)
VERIFIED_AT = datetime(2026, 1, 1, 6, 0, tzinfo=UTC)

# ค่าที่ไม่ซ้ำใคร (unlikely string) — ถ้าเจอในข้อความ log แปลว่าเป็นของเทสนี้แน่ๆ
# ไม่ใช่ noise จาก query อื่นที่บังเอิญมีคำคล้ายกัน
RECIPIENT_NAME = "สมชาย ทดสอบไม่ซ้ำ998"
RECIPIENT_PHONE = "0891112222"
ADDRESS_LINE = "99/1 ซอยทดสอบไม่ซ้ำใคร ถนนสุขุมวิท"


def test_the_production_engine_really_sets_hide_parameters() -> None:
    """🔴 **เทสข้างล่างพิสูจน์ *ฟีเจอร์ของ SQLAlchemy* ไม่ใช่ *config ของแอป*** —
    มันสร้าง engine ของตัวเองพร้อม `hide_parameters=True` ที่เขียนไว้ในเทสเอง
    ⇒ **ถอด `hide_parameters=True` ออกจาก `app/core/database.py` แล้วมันยังเขียว**
    (`code-critic` รอบ 2 รันพิสูจน์แล้วว่า exit code = 0)

    บรรทัดเดียวข้างล่างคือสิ่งที่ผูกเทสไฟล์นี้เข้ากับโค้ดโปรดักชันจริง —
    `SCR-07` **AC-7** บังคับว่า *"พิสูจน์ด้วยเทสที่ mutate แล้วแดง ไม่ใช่ด้วยการอ่านโค้ด"*
    ⇒ ถ้าไม่มีเทสนี้ AC-7 ยังพิสูจน์แบบที่ AC สั่งไม่ได้ แม้ช่องโหว่จะปิดไปแล้วจริง

    🔴 **อ่าน `engine` ผ่าน import ในฟังก์ชัน ไม่ใช่ที่หัวไฟล์** — engine ตัวจริงต่อ
    `settings.DATABASE_URL` (dev DB) ไม่ใช่ `poster_nung_test` · เทสนี้ไม่ยิง query
    ใด ๆ แค่อ่าน attribute ที่ freeze ไว้ตอน import จึงไม่แตะข้อมูล dev
    """
    from app.core.database import engine as production_engine

    assert production_engine.sync_engine.hide_parameters is True, (
        "app/core/database.py ต้องตั้ง hide_parameters=True — ไม่งั้น echo=DEBUG "
        "จะพ่นชื่อผู้รับ/เบอร์/ที่อยู่ลง log และ str(IntegrityError) (ADR-0020 D9)"
    )


async def test_echo_true_does_not_leak_shipping_address_into_sql_log(
    caplog: pytest.LogCaptureFixture,
) -> None:
    engine = create_async_engine(TEST_DATABASE_URL, echo=True, hide_parameters=True)
    try:
        async with AsyncSession(engine, expire_on_commit=False) as session:
            seller_owner = User(
                email=f"echo-seller-{uuid.uuid4().hex[:8]}@example.test",
                is_verified=True,
            )
            session.add(seller_owner)
            await session.flush()

            seller = SellerProfile(
                user_id=seller_owner.id,
                display_name="ร้านทดสอบ echo",
                real_name="ผู้ขายทดสอบ",
                bank_name="ธนาคารทดสอบ",
                bank_account_name="ผู้ขายทดสอบ",
                bank_account_no="0000000000",
            )
            session.add(seller)
            await session.flush()

            poster = Poster(
                seller_id=seller.id,
                approved_at=APPROVED_AT,
                title="Echo Test Poster",
                price=Decimal("1000.00"),
                shipping_fee=Decimal("0.00"),
                condition_grade=PosterCondition.very_fine,
                status=PosterStatus.available,
                published_at=PUBLISHED_AT,
                verified_at=VERIFIED_AT,
            )
            session.add(poster)
            await session.flush()

            buyer = User(
                email=f"echo-buyer-{uuid.uuid4().hex[:8]}@example.test",
                is_verified=True,
            )
            session.add(buyer)
            await session.flush()

            reservation = await order_service.reserve_listing(
                session, poster.id, buyer_user_id=buyer.id, at=NOW
            )

            address = ShippingAddressInput(
                recipient_name=RECIPIENT_NAME,
                recipient_phone=RECIPIENT_PHONE,
                address_line=ADDRESS_LINE,
                province="กรุงเทพมหานคร",
                postal_code="10110",
            )

            with caplog.at_level(logging.INFO, logger="sqlalchemy.engine.Engine"):
                await order_service.create_order(
                    session,
                    reservation.id,
                    buyer_user_id=buyer.id,
                    shipping_address=address,
                    at=NOW,
                )

            # ไม่ commit โดยตั้งใจ — เทสนี้ไม่ต้องเก็บกวาด DB เพราะ rollback ทิ้งเอง
            await session.rollback()
    finally:
        await engine.dispose()

    log_text = "\n".join(record.getMessage() for record in caplog.records)
    assert (
        log_text
    ), "ไม่มี SQL log เกิดขึ้นเลย — engine echo=True ไม่ทำงาน เทสนี้พิสูจน์อะไรไม่ได้"

    for leaked in (RECIPIENT_NAME, RECIPIENT_PHONE, ADDRESS_LINE):
        assert (
            leaked not in log_text
        ), f"พบข้อมูลส่วนบุคคลหลุดเข้า SQL echo log: {leaked!r}"

    # ยืนยันว่า SQLAlchemy เข้าเส้นทาง hide_parameters จริง ไม่ใช่แค่บังเอิญไม่มี log
    assert "hidden due to hide_parameters" in log_text
