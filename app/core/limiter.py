"""slowapi Limiter instance ที่ใช้ร่วมกันระหว่าง main.py และ endpoint ที่ต้อง rate-limit."""

from fastapi import Request
from slowapi import Limiter
from slowapi.util import get_remote_address

# headers_enabled=True — docs/openapi.yaml กำหนดว่าทุก 429 ต้องมี Retry-After header
# (default ของ slowapi คือ False ซึ่งจะไม่ใส่ header ใดๆ เลย)
limiter = Limiter(key_func=get_remote_address, headers_enabled=True)


def reserve_rate_limit_key(request: Request) -> str:
    """คีย์ rate-limit ของ `POST /listings/{poster_id}/reserve` — **ราย `user_id`
    ไม่ใช่ราย IP** (ADR-0037 **D6**) — IP บนมือถือคือ CGNAT ของ operator เดียวกัน
    ล็อกหนึ่ง IP = ล็อกลูกค้าคนอื่นครึ่งเครือข่าย

    🔴 **ต้องชื่อพารามิเตอร์ว่า `request` เป๊ะ** — `slowapi` เลือกว่าจะส่ง `Request`
    ให้ `key_func` หรือไม่ด้วยการดูชื่อพารามิเตอร์ตรง ๆ (`extension.py:501`)
    ตั้งชื่ออื่น (เช่น `req`) จะได้ `TypeError` ตอนเรียก

    อ่าน user id จาก `request.state.user_id` ที่ `get_current_user()`
    (`app/api/deps.py`) เขียนไว้ให้แล้ว — ปลอดภัยเรื่องลำดับเพราะ decorator ของ
    slowapi ห่อตัว endpoint ⇒ FastAPI resolve dependency ให้เสร็จก่อนเสมอแล้วค่อยนับ
    · fallback เป็น IP เมื่อไม่มี (คำขอที่ token ไม่ผ่านได้ 401 ก่อนถึงจุดนับ จึงไม่มี
    `user_id` ให้อ่าน — ยอมรับแล้วว่าเส้นนี้ไม่มี rate limit สำหรับคนที่ยังไม่ล็อกอิน)

    🔴 **ห้ามคืนสตริงว่างเด็ดขาด** — `extension.py:507` ใช้ `if all(args):` ถ้า
    `key_func` คืน `""` การนับจะถูกข้ามไปเงียบ ๆ โดยไม่มี error ใด ๆ ·
    `get_remote_address()` ไม่มีวันคืน `""` (fallback เป็น `"127.0.0.1"` เสมอ)
    """
    user_id = getattr(request.state, "user_id", None)
    if user_id:
        return str(user_id)
    return get_remote_address(request)
