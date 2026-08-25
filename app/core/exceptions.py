"""Custom application errors → map เป็น error envelope {error_code, message, details}.

error_code ตรงกับ catalog ใน docs/api-contract-f1-f3.md §3
"""

from typing import Any


class AppError(Exception):
    """Base error ที่ exception handler แปลงเป็น JSON envelope."""

    status_code: int = 400
    error_code: str = "APP_ERROR"
    message: str = "เกิดข้อผิดพลาด"

    def __init__(
        self,
        message: str | None = None,
        *,
        details: list[dict[str, Any]] | None = None,
    ) -> None:
        self.message = message or self.message
        self.details = details
        super().__init__(self.message)


# ---- F1 Authentication errors ----
class RefreshTokenInvalid(AppError):
    status_code = 401
    error_code = "REFRESH_TOKEN_INVALID"
    message = "Refresh token ไม่ถูกต้องหรือหมดอายุ กรุณาเข้าสู่ระบบใหม่"


class Unauthorized(AppError):
    status_code = 401
    error_code = "UNAUTHORIZED"
    message = "กรุณาเข้าสู่ระบบ"


class AdminRequired(AppError):
    """ล็อกอินถูกต้องแล้วแต่ไม่มีสิทธิ์แอดมิน (ADR-0031 D3).

    ต่างจาก Unauthorized (401) ตรงที่ตัวตนพิสูจน์ได้แล้ว — สิ่งที่ขาดคือสิทธิ์
    ตอบรหัสเดียวกันทุกกรณีที่ไม่ใช่แอดมิน ไม่แยก 404 (ADR-0031 D7)
    """

    status_code = 403
    error_code = "ADMIN_REQUIRED"
    message = "คุณไม่มีสิทธิ์เข้าถึงส่วนนี้"


# ---- Firebase login (email/password, phone-OTP, Google) errors ----
class OAuthTokenInvalid(AppError):
    status_code = 401
    error_code = "OAUTH_TOKEN_INVALID"
    message = "ไม่สามารถยืนยันตัวตนได้ กรุณาลองใหม่"


class OAuthEmailNotVerified(AppError):
    status_code = 403
    error_code = "OAUTH_EMAIL_NOT_VERIFIED"
    message = "บัญชีนี้ยังไม่ได้ยืนยันอีเมล"


class OAuthProviderNotConfigured(AppError):
    status_code = 503
    error_code = "OAUTH_PROVIDER_NOT_CONFIGURED"
    message = "ระบบยังไม่ได้ตั้งค่า Firebase login กรุณาติดต่อผู้ดูแลระบบ"


class OAuthLoginConflict(AppError):
    status_code = 409
    error_code = "OAUTH_LOGIN_CONFLICT"
    message = "เกิดข้อขัดแย้งระหว่างเข้าสู่ระบบ กรุณาลองใหม่อีกครั้ง"


# ---- F2 Catalog errors ----
class PosterNotFound(AppError):
    status_code = 404
    error_code = "POSTER_NOT_FOUND"
    message = "ไม่พบโปสเตอร์นี้ในระบบ"


class PosterNotPublishable(AppError):
    """โปสเตอร์ยังไม่ผ่านเงื่อนไขการเปิดขาย จึงเขียน `published_at` ไม่ได้

    เงื่อนไขทั้งชุดอยู่ที่ `poster_service.is_publishable()` **ที่เดียว** (ADR-0027 D5)
    — ไม่ใช่แค่ "ไม่มีเกรด" อีกแล้ว ‹แก้ 2026-08-16 · ข้อความเดิมพูดถึงเกรดอย่างเดียว
    ซึ่งแคบกว่ากติกาจริงตั้งแต่ ADR-0027›

    ยังไม่มี endpoint ไหน raise ตัวนี้ — เส้นทางที่เขียน `published_at` วันนี้เป็น
    สคริปต์ของ operator (เส้นที่ 3) ซึ่งเรียก `is_publishable()` ตรง ๆ เพื่อพิมพ์
    เหตุผล**ทุกข้อ**ให้คนอ่านในรอบเดียว ไม่ใช่ raise ที่ข้อแรก
    """

    status_code = 409
    error_code = "POSTER_NOT_PUBLISHABLE"
    message = "โปสเตอร์นี้ยังไม่ผ่านเงื่อนไขการเปิดขาย"


class PosterNotAvailable(AppError):
    """โปสเตอร์นี้ `status` ไม่ใช่ `available` จึงดำเนินการต่อไม่ได้

    error_code นี้ถูกจองไว้แล้วใน `docs/api-contract-f1-f3.md` §3 สำหรับ
    `POST /cart/reserve/{id}` (F3 — ยังไม่มีโค้ด) · `poster_service.mark_sold()`
    (ADR-0025 · INF-24) เป็นคนแรกที่ raise จริง ใช้ความหมายเดียวกันเป๊ะ ("แถวนี้ไม่ได้
    อยู่ในสถานะที่ดำเนินการต่อได้") แม้จะยังไม่มี endpoint ให้ HTTP response จริง
    (INF-24 AC-7 ห้ามเปิด endpoint ในรอบนี้ — ทางเรียกวันนี้คือ CLI operator เท่านั้น)
    """

    status_code = 409
    error_code = "POSTER_NOT_AVAILABLE"
    # ตรงกับตัวอย่างใน docs/api-contract-f1-f3.md §1 (error envelope example) เป๊ะ —
    # "จอง" ครอบเคส reserved และ "ขาย" ครอบเคส sold ซึ่งเป็นสองสถานะเดียวที่ไม่ใช่
    # available ในระบบวันนี้ ข้อความจึงแม่นทั้งสอง caller (F3 · mark_sold())
    message = "โปสเตอร์นี้ถูกจองหรือขายไปแล้ว"


class PosterHasActiveReservation(AppError):
    """มี reservation ที่ยัง `active` อยู่บนใบนี้ — ปฏิเสธเสมอ ไม่มีทางข้าม (ADR-0025 D3)

    ระบบไม่มีปุ่มยกเลิก QR หรือคืนเงินอัตโนมัติผ่าน Omise เลย (skill `stock-integrity`)
    การยึดของที่มีลูกค้าค้างกลางทางจ่ายเงินอยู่คือความเสี่ยงที่แก้คืนไม่ได้ (ADR-0002)
    `details` มี `reservation_id` ให้คนไปตัดสินเอง — `mark_sold()` ห้ามพลิก/ลบ/แก้
    `reservations` เองเลยสักคอลัมน์
    """

    status_code = 409
    error_code = "POSTER_HAS_ACTIVE_RESERVATION"
    message = "โปสเตอร์นี้มีการจองที่ยัง active อยู่ ต้องตัดสินก่อนบันทึกว่าขายแล้ว"


class PosterHasPendingCharge(AppError):
    """charge ที่ยัง `pending` ต้องยืนยันกับ Omise ก่อนตัดสินใจปล่อย/ยึดสต็อก
    (skill `stock-integrity` ข้อ 7 · ADR-0002)

    วันนี้ไม่มีตาราง `payments` เลย — `poster_service._pending_charge_for()` คืน
    `None` เสมอ ตัวนี้จึงไม่มีทาง raise จริงในรอบนี้ (`# pragma: no cover`) ขึ้นทะเบียน
    error_code ไว้ล่วงหน้าให้ `SCR-06` ใช้ต่อได้เลย แทนที่จะต้องมาแก้ทีหลังว่า
    `mark_sold()` เคย raise `PosterNotAvailable` ผิดความหมาย (charge ค้าง ≠ status
    ไม่ใช่ available — พบจาก `code-critic` รอบ 1 ของ INF-24, Low)
    """

    status_code = 409
    error_code = "POSTER_HAS_PENDING_CHARGE"
    message = "โปสเตอร์นี้มี charge ที่ยังไม่จบ ต้องยืนยันสถานะก่อนบันทึกว่าขายแล้ว"


class PosterSoldReasonRequired(AppError):
    """`mark_sold()` บังคับ `reason` ต่อค่า ห้ามว่าง (ADR-0025 D1 ข้อ 3 · AC-4)

    🔴 เป็น `AppError` subclass ไม่ใช่ `ValueError` เปล่า ๆ โดยตั้งใจ (แก้จาก
    `code-critic` รอบ 1 ของ INF-24, Low) — `ValueError` ไม่ผ่าน `except AppError`
    ของ CLI (`sold_entry.py`) และจะกลายเป็น traceback ดิบแทนข้อความที่อ่านออก และ
    ถ้า SCR-06 ต่อ endpoint ที่เรียก `mark_sold()` ในอนาคต `ValueError` ที่ไม่ถูก
    catch จะกลายเป็น `500` แทนที่จะเป็น error envelope ที่ถูกต้อง
    """

    status_code = 422
    error_code = "POSTER_SOLD_REASON_REQUIRED"
    message = "ต้องระบุเหตุผลก่อนบันทึกว่าโปสเตอร์นี้ขายแล้ว"
