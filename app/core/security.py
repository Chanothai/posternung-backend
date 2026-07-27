"""JWT + refresh-token hashing helpers.

Password/OTP hashing ถูกถอดออกแล้ว — sign-in ทุกวิธีทำที่ Firebase ฝั่ง client
backend ไม่เก็บรหัสผ่านหรือ OTP ของตัวเองอีกต่อไป (ดู services/auth_service.py)
"""

import hashlib
import secrets
from datetime import datetime, timedelta, timezone

from jose import JWTError, jwt

from app.core.config import settings


# ---- Refresh token hashing (deterministic — ใช้ lookup ใน refresh_tokens.token_hash) ----
def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


# ---- JWT ----
def _create_token(subject: str, token_type: str, expires_delta: timedelta) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": subject,
        "type": token_type,
        "iat": now,
        "exp": now + expires_delta,
        # jti กัน token ซ้ำกัน byte-ต่อ-byte เมื่อออกให้ user เดียวกัน 2 ครั้งในวินาทีเดียวกัน
        # (iat ถูก truncate เป็นวินาที — ไม่มี jti จะทำให้ sha256(token) ชนกัน แล้ว insert
        # ลง refresh_tokens.token_hash UNIQUE พังด้วย IntegrityError)
        "jti": secrets.token_hex(16),
    }
    return jwt.encode(payload, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)


def create_access_token(user_id: str) -> str:
    return _create_token(
        str(user_id),
        "access",
        timedelta(minutes=settings.JWT_ACCESS_EXPIRE_MINUTES),
    )


def create_refresh_token(user_id: str) -> tuple[str, datetime]:
    """คืน (token, expires_at) — service เก็บ hash ของ token ลง refresh_tokens."""
    expires_at = datetime.now(timezone.utc) + timedelta(
        days=settings.JWT_REFRESH_EXPIRE_DAYS
    )
    token = _create_token(
        str(user_id),
        "refresh",
        timedelta(days=settings.JWT_REFRESH_EXPIRE_DAYS),
    )
    return token, expires_at


def decode_token(token: str) -> dict:
    """decode + verify signature/exp — raise JWTError ถ้าไม่ถูกต้อง/หมดอายุ."""
    return jwt.decode(token, settings.JWT_SECRET, algorithms=[settings.JWT_ALGORITHM])


__all__ = [
    "hash_token",
    "create_access_token",
    "create_refresh_token",
    "decode_token",
    "JWTError",
]
