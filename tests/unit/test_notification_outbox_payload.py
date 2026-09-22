"""ADR-0020 **D9** — `notification_outbox.payload` ห้ามมีข้อมูลส่วนบุคคล

🔴 **อ่านขอบเขตให้ตรง**: `_assert_no_personal_data()` ตรวจ **ชื่อคีย์** ทุกชั้น
มัน **ไม่ตรวจค่า** ⇒ เป็นตัวดักความเผลอ ไม่ใช่ขอบเขตความปลอดภัย · เทสไฟล์นี้
ล็อกทั้งสิ่งที่มันจับได้ **และสิ่งที่มันจับไม่ได้** เพื่อไม่ให้ใครอ่านผลเขียว
แล้วเข้าใจว่า payload ถูกกรอง PII ครบ (`test-quality` §5)
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories import notification_repository

AT = datetime(2026, 3, 2, 4, 0, tzinfo=UTC)


def _queue(session: AsyncSession, payload: dict | None):
    return notification_repository.queue(
        session,
        recipient_user_id=uuid.uuid4(),
        template_key="order_created_buyer",
        payload=payload,
        send_after=AT,
    )


async def test_a_personal_key_at_the_top_level_is_rejected(
    db_session: AsyncSession,
) -> None:
    with pytest.raises(ValueError, match="recipient_name"):
        _queue(db_session, {"order_id": "x", "recipient_name": "สมชาย ใจดี"})


async def test_a_personal_key_nested_one_level_down_is_rejected(
    db_session: AsyncSession,
) -> None:
    """🔴 เคสที่ตัวตรวจรุ่นแรกปล่อยผ่าน (ตรวจแค่ชั้นบนสุด) — code-critic รอบ 1"""
    with pytest.raises(ValueError, match=r"payload\.shipping\.address_line"):
        _queue(db_session, {"order_id": "x", "shipping": {"address_line": "1/2 ซอย…"}})


async def test_a_personal_key_inside_a_list_is_rejected(
    db_session: AsyncSession,
) -> None:
    with pytest.raises(ValueError, match=r"payload\.items\[1\]\.phone"):
        _queue(
            db_session,
            {"items": [{"order_id": "a"}, {"phone": "0812345678"}]},
        )


async def test_a_payload_of_ids_only_is_accepted(db_session: AsyncSession) -> None:
    """เทสเชิงบวก — ถ้าไม่มีข้อนี้ ตัวตรวจที่ raise ทุกกรณีก็ยังเขียว"""
    row = _queue(db_session, {"order_id": "x", "poster_id": "y", "to_status": "z"})

    assert row.payload == {"order_id": "x", "poster_id": "y", "to_status": "z"}


async def test_none_and_empty_payloads_are_accepted(db_session: AsyncSession) -> None:
    assert _queue(db_session, None).payload is None
    assert _queue(db_session, {}).payload == {}


async def test_personal_data_hidden_in_a_value_is_NOT_caught(
    db_session: AsyncSession,
) -> None:
    """🔴 **บันทึกข้อจำกัด ไม่ใช่การอวยพร** — ตัวตรวจดูแต่ชื่อคีย์

    ถ้าวันหนึ่งมีคนทำให้มันตรวจค่าด้วย เทสนี้จะแดง ซึ่งเป็นสัญญาณให้มาลบเทสนี้ทิ้ง
    ไม่ใช่สัญญาณว่าอะไรพัง · ตัวบังคับจริงของ D9 คือคนเขียนผู้เรียกที่ส่งแต่ id
    """
    row = _queue(db_session, {"note": "สมชาย ใจดี 081-234-5678"})

    assert row.payload == {"note": "สมชาย ใจดี 081-234-5678"}
