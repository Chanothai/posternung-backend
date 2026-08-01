"""ประกอบ URL รูปโปสเตอร์จาก storage_key (ADR-0006).

DB เก็บ `poster_images.storage_key` (object key สัมพันธ์กับ bucket) ไม่ใช่ URL เต็ม —
ฟังก์ชันนี้เป็นจุดเดียวที่ต่อ `settings.MEDIA_BASE_URL` เข้ากับ key ตอน serialize
เปลี่ยน CDN/bucket ภายหลัง (หรือสลับไปใช้ signed URL) แก้ที่นี่ที่เดียว ไม่ต้อง migration.
"""

from app.core.config import settings


def build_media_url(storage_key: str) -> str:
    """ต่อ settings.MEDIA_BASE_URL กับ storage_key ให้เป็น URL เต็ม 1 ตัว

    กัน `//` ซ้ำตรงรอยต่อไม่ว่า base/key จะมีหรือไม่มี slash นำ/ปิดท้ายมาก็ตาม
    (ไม่แตะ `://` ของ scheme เพราะ strip แค่ปลายสุดของ base และหัวสุดของ key)
    """
    base = settings.MEDIA_BASE_URL.rstrip("/")
    key = storage_key.lstrip("/")
    return f"{base}/{key}"
