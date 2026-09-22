"""ประกอบ URL รูปโปสเตอร์จาก storage_key (ADR-0006).

DB เก็บ `poster_images.storage_key` (object key สัมพันธ์กับ bucket) ไม่ใช่ URL เต็ม —
ฟังก์ชันนี้เป็นจุดเดียวที่ต่อ `settings.MEDIA_BASE_URL` เข้ากับ key ตอน serialize
เปลี่ยน CDN/bucket ภายหลัง (หรือสลับไปใช้ signed URL) แก้ที่นี่ที่เดียว ไม่ต้อง migration.

รูปแบบ key และความหมายของ segment `visibility` (`public`/`internal`) ดู ADR-0006 D2 —
ไม่ก๊อปมาเขียนซ้ำที่นี่.
"""

from app.core.config import settings

_PUBLIC_PREFIX = "posters/public/"


class UnsafeStorageKeyError(ValueError):
    """`storage_key` ไม่ได้อยู่ใต้ `posters/public/` (ADR-0006 D2/D5).

    ตั้งใจเป็น `ValueError` ไม่ใช่ `AppError`: นี่คือ programming/data-integrity
    error (ผู้เรียกส่ง key ที่ไม่ผ่านการกรอง visibility เข้ามา) ไม่ใช่เงื่อนไขที่
    client ควรเห็นเป็น error envelope ที่ออกแบบมาให้อ่านได้ — `app/main.py` ไม่มี
    handler จับ exception นี้โดยตั้งใจ จึงปล่อยให้กลายเป็น 500 ทั่วไปที่ log เต็ม
    ฝั่ง server เท่านั้น
    """


def is_public_storage_key(storage_key: str) -> bool:
    """key นี้อยู่ใต้ visibility `public` ไหม (ADR-0006 D2)

    เป็นจุดเดียวที่ผู้เรียกใช้ตัดสิน visibility ได้ **ก่อน** ถึง `build_media_url()`
    ซึ่ง raise เสมอเมื่อ key ไม่ public (D5) — ผู้เรียกที่ต้องข้ามรูปแทนที่จะพัง
    ทั้งคำขอ ให้กรองด้วยฟังก์ชันนี้ก่อน อย่าไปผ่อนปรน `build_media_url()`
    (เหตุผลที่ฟังก์ชันนี้มีอยู่ตั้งแต่ตอนนี้แทนที่จะรอ BLOCK 5.5: ADR-0007)

    ต้องเทียบ `_PUBLIC_PREFIX` ทั้งก้อนรวม `/` ปิดท้าย — `posters/publicx/...` ต้องเป็น
    False ไม่งั้นจะหลุด filter ไปโดน `build_media_url()` raise = 500 กลับมาเงียบ ๆ
    """
    return storage_key.lstrip("/").startswith(_PUBLIC_PREFIX)


def build_media_url(storage_key: str) -> str:
    """ต่อ settings.MEDIA_BASE_URL กับ storage_key ให้เป็น URL เต็ม 1 ตัว

    รับเฉพาะ key ที่อยู่ใต้ `posters/public/` เท่านั้น (ADR-0006 D5) — `MEDIA_BASE_URL`
    คือ CDN สาธารณะ key อื่น (เช่น `posters/internal/...`) ต้อง raise
    `UnsafeStorageKeyError` แทนที่จะถูกต่อเป็น URL ที่ใครก็เปิดได้

    กัน `//` ซ้ำตรงรอยต่อไม่ว่า base/key จะมีหรือไม่มี slash นำ/ปิดท้ายมาก็ตาม
    (ไม่แตะ `://` ของ scheme เพราะ strip แค่ปลายสุดของ base และหัวสุดของ key)
    """
    key = storage_key.lstrip("/")
    if not key.startswith(_PUBLIC_PREFIX):
        # ห้ามใส่ค่า key จริงในข้อความนี้ — จะทำให้ path ของรูป internal
        # (ที่ควรถูกคุมสิทธิ์) หลุดเข้า log ทุกครั้งที่ raise (security-baseline §2)
        raise UnsafeStorageKeyError(
            "build_media_url() ปฏิเสธ storage_key ที่ไม่ได้อยู่ใต้ posters/public/"
        )
    base = settings.MEDIA_BASE_URL.rstrip("/")
    return f"{base}/{key}"
