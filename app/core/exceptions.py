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
    """โปสเตอร์ยังขาดข้อมูลที่ BR-05 บังคับ จึงเปิดขาย (เขียน `published_at`) ไม่ได้

    ยังไม่มี endpoint ไหน raise ตัวนี้ เพราะ ADR-0013 D4 ตั้งใจไม่สร้าง writer ของ
    `published_at` เลยในรอบนี้ · ขึ้นทะเบียนไว้ตั้งแต่ตอนนี้เพื่อให้
    `poster_service.assert_publishable()` มีของที่จะ raise และให้ error_code
    ถูกจองไว้ก่อนที่ INF-11 (เส้นทางเปิดขาย) จะมาใช้
    """

    status_code = 409
    error_code = "POSTER_NOT_PUBLISHABLE"
    message = "โปสเตอร์นี้ยังไม่มีเกรดสภาพ จึงยังเปิดขายไม่ได้"
