"""`notification_outbox` table access — thin DB layer (ไม่มี business logic)

INF-33 **AC-3/AC-8** · BR-P8 — แจ้งเตือน **ทุกจุดเปลี่ยนสถานะ ทั้งสองฝ่าย**
🔴 แถวถูกเขียนใน **ทรานแซกชันเดียวกับการเปลี่ยนสถานะ** แล้วให้ worker ส่งทีหลัง
(worker เป็นของ AC-8 ซึ่ง **ยังไม่มีในรอบนี้** — วันนี้แถวจะค้างอยู่ในตารางเฉย ๆ
และนั่นถูกต้อง: มีร่องรอยดีกว่ายิง API ตรงจากใน transaction แล้วหายถาวร)

🔴 **`payload` ห้ามมีชื่อ · ที่อยู่ · เบอร์ · อีเมล** (ADR-0020 **D9**) — ใส่ id
แล้วให้ตัวส่งไปอ่านเอง

⚠️ **ขอบเขตจริงของ `_assert_no_personal_data()` — อ่านให้ตรง** ‹เขียนใหม่ 2026-08-26
ตาม `code-critic`; ถ้อยคำเดิมเรียกตัวเองว่า "ด่าน" ซึ่งพูดเกินกว่าที่โค้ดทำ›
มันตรวจ **ชื่อคีย์** เทียบกับรายการคำต้องห้าม โดยเดินลงไป**ทุกชั้น**ของ dict/list
· มัน **ไม่ตรวจค่า** เลย ⇒ `{"note": "สมชาย ใจดี 081-…"}` ผ่านฉลุย
· มันจึงเป็น **ตัวดักความเผลอ ไม่ใช่ขอบเขตความปลอดภัย** — ตัวตัดสินจริงคือคนเขียน
ผู้เรียกที่ต้องส่งแต่ id ตามที่ ADR-0020 D9 สั่ง
"""

import uuid
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import NotificationChannel
from app.models.platform import NotificationOutbox

# คีย์ที่แปลว่ามีข้อมูลส่วนบุคคลปนมาใน payload — ADR-0020 D9 ระบุรายการนี้ตรงตัว
_FORBIDDEN_PAYLOAD_KEY_PARTS = (
    "name",
    "phone",
    "address",
    "email",
    "recipient",
    "slip",
)


def _assert_no_personal_data(value: object, *, path: str = "payload") -> None:
    """เดินลงไป **ทุกชั้น** ของ dict/list แล้วปฏิเสธคีย์ที่เข้าข่ายข้อมูลส่วนบุคคล

    ต้อง recursive เพราะ payload ซ้อนชั้นได้ (`{"shipping": {"recipient_name": …}}`)
    — ตรวจแค่ชั้นบนสุดคือด่านที่หลุดตั้งแต่มีคนห่อ dict ชั้นที่สอง (code-critic)
    """
    if isinstance(value, dict):
        for key, nested in value.items():
            lowered = str(key).lower()
            for part in _FORBIDDEN_PAYLOAD_KEY_PARTS:
                if part in lowered:
                    raise ValueError(
                        "notification payload ห้ามมีข้อมูลส่วนบุคคล (ADR-0020 D9) — "
                        f"คีย์ {path}.{key} ต้องเปลี่ยนเป็น id "
                        "แล้วให้ตัวส่งไปอ่านเอง"
                    )
            _assert_no_personal_data(nested, path=f"{path}.{key}")
    elif isinstance(value, (list, tuple)):
        for index, nested in enumerate(value):
            _assert_no_personal_data(nested, path=f"{path}[{index}]")


def queue(
    session: AsyncSession,
    *,
    recipient_user_id: uuid.UUID,
    template_key: str,
    payload: dict | None,
    send_after: datetime,
    channel: NotificationChannel = NotificationChannel.EMAIL,
) -> NotificationOutbox:
    """ต่อคิวแจ้งเตือนหนึ่งฉบับ — ไม่ `flush` ไม่ `commit` (ผู้เรียกคุม transaction)

    `channel` default เป็น **EMAIL** เพราะเจ้าของเคาะที่ GATE 1 ว่า *อีเมลก่อน LINE*
    · LINE Messaging API ยังไม่เคยต่อเลยในโปรเจกต์นี้ (INF-33 `known_gap`) และ
    การเลือกช่องทางจริงเป็นของ **ADR-0034** ไม่ใช่ของไฟล์นี้
    """
    _assert_no_personal_data(payload)
    row = NotificationOutbox(
        channel=channel,
        recipient_user_id=recipient_user_id,
        template_key=template_key,
        payload=payload,
        send_after=send_after,
    )
    session.add(row)
    return row
