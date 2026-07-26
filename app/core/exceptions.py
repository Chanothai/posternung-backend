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
class EmailAlreadyRegistered(AppError):
    status_code = 409
    error_code = "EMAIL_ALREADY_REGISTERED"
    message = "อีเมลนี้ถูกใช้สมัครสมาชิกไปแล้ว"


class UserNotFound(AppError):
    status_code = 404
    error_code = "USER_NOT_FOUND"
    message = "ไม่พบบัญชีผู้ใช้นี้ในระบบ"


class OtpInvalid(AppError):
    status_code = 400
    error_code = "OTP_INVALID"
    message = "รหัส OTP ไม่ถูกต้อง"


class OtpExpired(AppError):
    status_code = 400
    error_code = "OTP_EXPIRED"
    message = "รหัส OTP หมดอายุแล้ว กรุณาขอรหัสใหม่"


class OtpLocked(AppError):
    status_code = 429
    error_code = "OTP_LOCKED"
    message = "กรอกรหัสผิดเกินจำนวนที่กำหนด กรุณาขอรหัส OTP ใหม่"


class OtpRateLimited(AppError):
    status_code = 429
    error_code = "OTP_RATE_LIMITED"
    message = "ขอรหัส OTP บ่อยเกินไป กรุณาลองใหม่ภายหลัง"


class InvalidCredentials(AppError):
    status_code = 401
    error_code = "INVALID_CREDENTIALS"
    message = "อีเมลหรือรหัสผ่านไม่ถูกต้อง"


class AccountNotVerified(AppError):
    status_code = 403
    error_code = "ACCOUNT_NOT_VERIFIED"
    message = "กรุณายืนยัน OTP ก่อนเข้าสู่ระบบ"


class AccountAlreadyVerified(AppError):
    status_code = 409
    error_code = "ACCOUNT_ALREADY_VERIFIED"
    message = "บัญชีนี้ยืนยันแล้ว ไม่ต้องยืนยันซ้ำ"


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
