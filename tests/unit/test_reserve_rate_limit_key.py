"""SCR-07 · มติเจ้าของ 2026-09-15 ที่ GATE 3 — `key_func` ของเส้นจอง **ไม่มีวันคืนสตริงว่าง**

ทำไมต้องมีเทสนี้: `slowapi/extension.py:507` ใช้ `if all(args):` ⇒ ถ้า `key_func`
คืน `""` การนับจะถูก **ข้ามไปเงียบ ๆ โดยไม่มี error** — rate limit หายไปทั้งเส้น
โดยที่ทุกเทสอื่นยังเขียว · ทางที่ถูกคือ **คำขอที่ไม่มี user id ต้องได้ 401 ก่อนถึง limiter**
(`get_current_user()` เป็น dependency ที่ FastAPI resolve ก่อน decorator ของ slowapi
จะนับ) ไม่ใช่ปล่อยให้ key_func รับ request ที่ไม่มี user แล้วคืนค่าว่าง

เทสนี้ยิง `key_func` ตรง ๆ ด้วย `request.state` สามแบบ (ไม่มี user_id · user_id เป็น
`None` · user_id เป็นสตริงว่าง) และ assert ว่าทุกแบบได้ค่าที่ไม่ว่าง (fallback เป็น IP
ซึ่ง `get_remote_address()` ไม่มีวันคืน `""`)

mutation ที่ต้องตาย: เปลี่ยน fallback ใน `reserve_rate_limit_key()` ให้คืน `""` → แดง
"""

import uuid

from starlette.requests import Request

from app.core.limiter import reserve_rate_limit_key


def _request(client_ip: str | None, **state: object) -> Request:
    scope = {
        "type": "http",
        "method": "POST",
        "path": "/api/v1/listings/x/reserve",
        "headers": [],
        "client": (client_ip, 12345) if client_ip else None,
    }
    req = Request(scope)
    for k, v in state.items():
        setattr(req.state, k, v)
    return req


def test_key_func_uses_user_id_when_present() -> None:
    uid = uuid.uuid4()
    assert reserve_rate_limit_key(_request("203.0.113.9", user_id=uid)) == str(uid)


def test_key_func_never_returns_an_empty_string_without_a_user() -> None:
    """🔴 ถ้าข้อนี้แดง แปลว่า rate limit ทั้งเส้นถูกข้ามเงียบ ๆ ได้ (extension.py:507)."""
    for req in (
        _request("203.0.113.9"),  # ไม่มี user_id ใน state เลย
        _request("203.0.113.9", user_id=None),
        _request("203.0.113.9", user_id=""),
        _request(
            None
        ),  # ไม่มี client ใน scope ด้วยซ้ำ — get_remote_address ยัง fallback
    ):
        key = reserve_rate_limit_key(req)
        assert isinstance(key, str)
        assert key != "", "key_func คืนสตริงว่าง — slowapi จะข้ามการนับโดยไม่มี error"
