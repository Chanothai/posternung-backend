"""Integration tests (HTTP-level) ของด่านสิทธิ์แอดมิน — ADR-0031 D3 · D4 ข้อ 2 · INF-35

ทุกเคสยิงผ่าน endpoint จริง (`GET /api/v1/admin/me`) ด้วย fixture `client`
**ไม่ใช่เรียก dependency ตรง** — เพราะสิ่งที่ต้องพิสูจน์คือ "ผู้ใช้ที่ยิงเข้ามาได้อะไร"
ไม่ใช่ "ฟังก์ชันคืนค่าอะไร" · ด่านที่ต่อไม่ติดกับสายจริงจะผ่านเทสแบบหลังทุกข้อ

ตาราง D3 มี 5 แถว — แถว 1/2/5 อยู่ที่นี่ · แถว 3 (`None`/ไม่มี attribute) และแถว 4
(ไม่ applicable ภายใต้ D1 = A-1) อยู่ที่ `tests/unit/test_admin_route_guard.py`
เพราะบังคับค่าพวกนั้นผ่าน DB ไม่ได้ (คอลัมน์เป็น NOT NULL)
"""

from datetime import datetime, timedelta, timezone

import pytest
from httpx import ASGITransport, AsyncClient
from jose import jwt
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import security
from app.core.config import settings
from app.models.user import User

ADMIN_ME = "/api/v1/admin/me"


async def _make_user(session: AsyncSession, *, email: str, is_admin: bool) -> User:
    user = User(email=email, is_verified=True, is_admin=is_admin)
    session.add(user)
    await session.flush()
    return user


def _auth(user: User) -> dict[str, str]:
    return {"Authorization": f"Bearer {security.create_access_token(str(user.id))}"}


# ─────────────────── D3 แถว 1 — พิสูจน์ตัวตนไม่ได้ = 401 ───────────────────


async def test_no_token_is_401(client: AsyncClient) -> None:
    res = await client.get(ADMIN_ME)
    assert res.status_code == 401
    assert res.json()["error_code"] == "UNAUTHORIZED"


async def test_garbage_token_is_401(client: AsyncClient) -> None:
    res = await client.get(ADMIN_ME, headers={"Authorization": "Bearer not-a-jwt"})
    assert res.status_code == 401
    assert res.json()["error_code"] == "UNAUTHORIZED"


async def test_expired_token_is_401(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    user = await _make_user(db_session, email="expired@test.example", is_admin=True)
    now = datetime.now(timezone.utc)
    expired = jwt.encode(
        {
            "sub": str(user.id),
            "type": "access",
            "iat": now - timedelta(hours=2),
            "exp": now - timedelta(hours=1),
            "jti": "expired-token",
        },
        settings.JWT_SECRET,
        algorithm=settings.JWT_ALGORITHM,
    )
    res = await client.get(ADMIN_ME, headers={"Authorization": f"Bearer {expired}"})
    assert res.status_code == 401
    assert res.json()["error_code"] == "UNAUTHORIZED"


async def test_refresh_token_instead_of_access_is_401(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """แอดมินตัวจริงแต่ส่ง refresh token มาแทน access — ต้องไม่ผ่าน

    นี่คือเหตุผลที่ ADR-0031 D2 ห้าม require_admin decode token เอง: เส้นทางที่สอง
    จะพลาดเรื่อง type == "access" แน่นอน
    """
    user = await _make_user(db_session, email="refresh@test.example", is_admin=True)
    refresh_token, _ = security.create_refresh_token(str(user.id))
    res = await client.get(
        ADMIN_ME, headers={"Authorization": f"Bearer {refresh_token}"}
    )
    assert res.status_code == 401
    assert res.json()["error_code"] == "UNAUTHORIZED"


async def test_token_of_deleted_user_is_401(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    user = await _make_user(db_session, email="gone@test.example", is_admin=True)
    headers = _auth(user)
    await db_session.delete(user)
    await db_session.flush()

    res = await client.get(ADMIN_ME, headers=headers)
    assert res.status_code == 401
    assert res.json()["error_code"] == "UNAUTHORIZED"


# ─────────────────── D3 แถว 2 — ล็อกอินได้แต่ไม่ใช่แอดมิน = 403 ───────────────────


async def test_normal_user_is_403_admin_required(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    user = await _make_user(db_session, email="member@test.example", is_admin=False)
    res = await client.get(ADMIN_ME, headers=_auth(user))
    assert res.status_code == 403
    body = res.json()
    assert body["error_code"] == "ADMIN_REQUIRED"
    # ADR-0017 — ห้ามข้อความ exception ดิบขึ้นจอ
    assert body["message"] == "คุณไม่มีสิทธิ์เข้าถึงส่วนนี้"


async def test_admin_gets_200_with_contract_shape(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    user = await _make_user(db_session, email="boss@test.example", is_admin=True)
    res = await client.get(ADMIN_ME, headers=_auth(user))
    assert res.status_code == 200, res.text
    body = res.json()
    # ตรงกับ AdminMeResponse ใน ../posternung-workspace/docs/api/openapi.yaml
    assert body == {"user_id": str(user.id), "is_admin": True}


# ─────────────────── D4 ข้อ 2 — สิทธิ์มาจากแถว DB ที่ผูกกับ sub เท่านั้น ───────────────────


@pytest.mark.parametrize(
    "kwargs",
    [
        pytest.param({"headers_extra": {"X-Is-Admin": "true"}}, id="header"),
        pytest.param({"headers_extra": {"X-Admin": "1"}}, id="header-alt"),
        pytest.param({"params": {"is_admin": "true"}}, id="query"),
        pytest.param({"params": {"role": "admin"}}, id="query-role"),
    ],
)
async def test_client_supplied_admin_hints_are_ignored(
    client: AsyncClient, db_session: AsyncSession, kwargs: dict
) -> None:
    """header/query ที่อ้างว่าเป็นแอดมินต้องไม่มีผลใด ๆ — ต้องยัง 403"""
    user = await _make_user(
        db_session, email=f"spoof-{id(kwargs)}@test.example", is_admin=False
    )
    headers = _auth(user) | kwargs.get("headers_extra", {})
    res = await client.get(ADMIN_ME, headers=headers, params=kwargs.get("params"))
    assert res.status_code == 403
    assert res.json()["error_code"] == "ADMIN_REQUIRED"


async def test_request_body_claiming_is_admin_is_ignored(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """body ที่อ้างว่าเป็นแอดมินต้องไม่มีผล — GET ที่มี body ก็ยังต้อง 403

    ครบชุดกับ header/query/JWT-claim ข้างบน: **ไม่มีช่องทางไหนที่ client ส่งค่ามาเอง
    แล้วกลายเป็นสิทธิ์ได้** (ADR-0031 D4 ข้อ 2)
    """
    user = await _make_user(db_session, email="bodyspoof@test.example", is_admin=False)
    res = await client.request(
        "GET",
        ADMIN_ME,
        headers=_auth(user),
        json={"is_admin": True, "role": "admin"},
    )
    assert res.status_code == 403
    assert res.json()["error_code"] == "ADMIN_REQUIRED"


async def test_signed_jwt_claiming_is_admin_is_still_403(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """🔴 เคสที่สำคัญที่สุดของ D4 ข้อ 2

    token ใบนี้ signature **ถูกต้องจริง** (เซ็นด้วย JWT_SECRET ของเราเอง), type ถูก,
    sub ชี้ user ที่มีอยู่จริง — ต่างจากเคสอื่นตรงที่มี claim `is_admin: true` ติดมา
    ถ้าโค้ดอ่านสิทธิ์จาก payload แทนที่จะอ่านจากแถวใน DB เคสนี้จะได้ 200 ทันที
    """
    user = await _make_user(db_session, email="claim@test.example", is_admin=False)
    now = datetime.now(timezone.utc)
    forged = jwt.encode(
        {
            "sub": str(user.id),
            "type": "access",
            "iat": now,
            "exp": now + timedelta(minutes=30),
            "jti": "forged-claim",
            "is_admin": True,
            "role": "admin",
        },
        settings.JWT_SECRET,
        algorithm=settings.JWT_ALGORITHM,
    )
    res = await client.get(ADMIN_ME, headers={"Authorization": f"Bearer {forged}"})
    assert res.status_code == 403
    assert res.json()["error_code"] == "ADMIN_REQUIRED"


# ─────────────────── D3 แถว 5 — อ่านสิทธิ์ไม่ได้ ≠ มีสิทธิ์ ───────────────────


async def test_db_error_while_reading_permission_is_not_a_pass(
    db_session: AsyncSession, client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """DB พังตอนอ่านแถว user → ต้องเป็น 500 ไม่ใช่ 200 และไม่ใช่ 403 ที่กลืน error

    ใช้ client ของตัวเองที่ตั้ง raise_app_exceptions=False เพื่อให้ได้ status จริง
    แทนที่ exception จะทะลุออกมาที่เทส (fixture `client` ปล่อยให้ทะลุตามค่า default)
    · `app/main.py` ไม่มี handler ที่จับ SQLAlchemyError กว้าง ๆ ⇒ 500 คือผลที่ถูก
    """
    user = await _make_user(db_session, email="dberror@test.example", is_admin=True)
    headers = _auth(user)

    async def _boom(self, *args, **kwargs):
        raise SQLAlchemyError("database is down")

    monkeypatch.setattr(AsyncSession, "get", _boom)

    from app.main import app

    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        res = await ac.get(ADMIN_ME, headers=headers)

    assert res.status_code == 500, res.text
    assert res.status_code != 200
