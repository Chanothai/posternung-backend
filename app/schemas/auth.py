"""Pydantic v2 schemas สำหรับ F1 Authentication (ตรง docs/openapi.yaml)."""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field


# ---- Requests ----
class RefreshRequest(BaseModel):
    refresh_token: str


class LogoutRequest(BaseModel):
    # refresh token ของ device ที่จะ logout — revoke เฉพาะใบนี้ (schema แยกจาก
    # RefreshRequest แม้ field เหมือนกัน เพื่อให้ OpenAPI สื่อความหมายตรงตัว)
    refresh_token: str


class FirebaseLoginRequest(BaseModel):
    # Firebase ID token จาก Firebase Auth (email/password, phone-OTP, หรือ Google
    # sign-in) บน mobile app — JWT ที่ Firebase เซ็นให้ backend verify กับ project id
    id_token: str = Field(min_length=1)


# ---- Responses ----
class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    # nullable — phone-only user (Firebase Phone Auth) ไม่มี email
    email: EmailStr | None
    phone: str | None
    is_verified: bool
    created_at: datetime


# ---- Error envelope (สำหรับ OpenAPI docs) ----
class ErrorResponse(BaseModel):
    error_code: str
    message: str
    details: list[dict] | None = None
