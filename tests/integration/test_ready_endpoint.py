"""🔴 INF-42 **AC-4** — `/ready` ต้องตอบ 503 เมื่อ DB ไม่ถึง (เทส regression)

## ทำไมข้อนี้เป็น regression ไม่ใช่พฤติกรรมใหม่

`app/main.py` ทำถูกอยู่แล้วตั้งแต่ก่อนใบนี้ (`SELECT 1` ผ่าน `async_session_maker`
แล้วคืน 503 เมื่อ throw) · AC-4 สั่งให้ **ล็อกพฤติกรรมนั้นด้วยเทส** เพราะก่อนรอบนี้
`grep -rn '/ready' tests/` เจอแค่**คอมเมนต์**ที่ `tests/unit/test_admin_route_guard.py:22`
— ไม่มีเทสไหนเรียกเส้นนี้เลยสักตัว ทั้ง 200 และ 503

## 🔴 ข้อจำกัดที่รอบนี้เปิดโปงเอง — และเป็นเหตุผลที่บั๊ก 2026-09-10 ถูกไล่ผิดที่สามชั้น

**`/ready` เบิก connection แค่ *ตัวเดียว* จาก pool ที่มีได้ถึง 15**
(`pool_size=5` + `max_overflow=10`) ⇒ **มันตอบ 200 ได้ทั้งที่ connection ตัวอื่นใน
pool ตายไปแล้ว**

⇒ 🔴 **ห้ามอ่านว่า `/ready` = 200 แปลว่า pool ทั้งก้อนใช้ได้** · ตอนไล่หาสาเหตุของ
`POST /auth/firebase` ที่ตอบ 500 เมื่อ 2026-09-10 ระบบ health check บอกว่าทุกอย่างปกติ
ตลอดเวลา ซึ่งเป็นส่วนหนึ่งของเหตุผลที่ไปไล่ Wi-Fi · `adb reverse` · SHA-1 ก่อนจะถึง DB

**สิ่งที่ `/ready` รับประกันได้จริง:** *"ตอนนี้เปิด connection ใหม่ไปหา DB ได้"*
**สิ่งที่มันรับประกันไม่ได้:** *"connection ทุกตัวที่ค้างอยู่ใน pool ยังใช้ได้"*
— ตัวที่คุ้มข้อหลังคือ `pool_pre_ping` ใน `app/core/database.py` ไม่ใช่เส้นนี้

‹บันทึกไว้ในไฟล์เทสเพราะ **AC-6 สั่งว่าขอบเขตของใบนี้คือ `app/core/database.py` (+ เทส)
และ `/ready` ไม่ต้องแก้** ⇒ เขียนลง `app/main.py` จะเป็นการบานออกนอกขอบเขตที่ AC-6 ห้าม›
"""

from __future__ import annotations

from contextlib import asynccontextmanager

import pytest
from httpx import AsyncClient


async def test_ready_returns_200_when_the_database_answers(
    client: AsyncClient,
) -> None:
    """เส้นปกติ — ยืนยันว่าเทส 503 ข้างล่างไม่ได้เขียวเพราะ `/ready` พังอยู่แล้ว"""
    response = await client.get("/ready")

    assert response.status_code == 200
    assert response.json() == {"status": "ready", "checks": {"database": "up"}}


async def test_ready_returns_503_when_the_database_is_unreachable(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """DB ไม่ถึง → **503 ไม่ใช่ 500 และไม่ใช่ 200**

    🔴 **patch `app.main.async_session_maker` ไม่ใช่ `get_db`** — `/ready` เรียก
    `async_session_maker` **ตรง ๆ** ไม่ได้ผ่าน dependency ⇒ `app.dependency_overrides`
    ที่ fixture `client` ตั้งไว้ **ไม่มีผลกับเส้นนี้เลย** · ถ้า patch ผิดที่ เทสจะเขียว
    โดยไม่เคยแตะเส้นทางที่ตั้งใจทดสอบ (`test-quality` §3.1)
    """
    import app.main as main

    @asynccontextmanager
    async def _dead_session_maker():
        raise OSError("connection refused")
        yield  # pragma: no cover — ไปไม่ถึง แต่ต้องมีเพื่อให้เป็น async generator

    monkeypatch.setattr(main, "async_session_maker", _dead_session_maker)

    response = await client.get("/ready")

    assert response.status_code == 503, (
        "DB ไม่ถึงต้องเป็น 503 — 500 แปลว่า exception หลุดออกไปถึง handler กลาง "
        "และ 200 แปลว่าไม่ได้แตะ DB เลย"
    )
    assert response.json() == {
        "status": "unavailable",
        "checks": {"database": "down"},
    }
