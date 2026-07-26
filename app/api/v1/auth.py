"""Thin controller ของ F1 Authentication — ห้ามมี DB query ตรงนี้ เรียก service ล้วน.

Sign-in ทุกวิธีทำที่ Firebase ฝั่ง client (email/password, phone SMS-OTP, Google)
แล้วส่ง ID token มาที่ POST /auth/firebase — backend ไม่มี local password/OTP flow แล้ว
"""

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.core.database import get_db
from app.core.limiter import limiter
from app.models.user import User
from app.schemas.auth import (
    FirebaseLoginRequest,
    RefreshRequest,
    TokenResponse,
    UserResponse,
)
from app.services import auth_service

router = APIRouter(prefix="/auth", tags=["Auth"])


@router.post("/firebase", response_model=TokenResponse)
@limiter.limit("5/minute")
async def firebase_login(
    request: Request,
    response: Response,  # ให้ slowapi inject rate-limit headers เข้า response นี้ (ไม่ใช้ตรงๆ)
    data: FirebaseLoginRequest,
    session: AsyncSession = Depends(get_db),
) -> TokenResponse:
    """Mobile login ผ่าน Firebase — รองรับ email/password, phone-OTP, และ Google
    sign-in ผ่าน endpoint เดียว (backend อ่าน sign_in_provider จาก token เอง). client
    sign-in ด้วย Firebase SDK แล้วแนบ Firebase ID token (getIdToken) มา."""
    result = await auth_service.firebase_login(session, data)
    await session.commit()
    return result


@router.post("/refresh", response_model=TokenResponse)
async def refresh(
    data: RefreshRequest, session: AsyncSession = Depends(get_db)
) -> TokenResponse:
    result = await auth_service.refresh_token(session, data)
    await session.commit()
    return result


@router.get("/me", response_model=UserResponse)
async def me(current_user: User = Depends(get_current_user)) -> User:
    """ข้อมูลผู้ใช้จาก access token ปัจจุบัน (protected — ต้องแนบ Bearer token)."""
    return current_user
