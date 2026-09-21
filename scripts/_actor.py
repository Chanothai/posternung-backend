"""ผู้สั่งการที่ต้องเป็นแอดมิน — ที่อยู่เดียวของด่าน google-only (INF-44 · ADR-0015 A3-D3 ①)

🔴 **ย้ายมาจาก `scripts/grant_admin.py:138-163`** (ADR-0031 Amendment 1) — เดิมด่าน
"provider ต้องเป็น google เท่านั้น" ประกาศอยู่ที่นั่นเพราะเป็นที่แรกที่ต้องเช็ค พอ
`scripts/orders/order_ops.py` (INF-41 OD-3) และ `scripts/_production_gate.py`
(INF-44 A3-D3 ①) ต้องเช็คคนละบัญชีที่ **ต่างความหมายกัน** จำเป็นต้องแยกเป็นบ้านกลาง —
บทเรียนเดียวกับที่ `scripts/seed/_shared.py` แยกออกมา (ทิศทาง lane → module กลาง)

## สองความหมายที่ต้องแยกให้ชัด — ห้ามสับสน

`grant_admin.py` เช็ค provider ของ **บัญชีที่กำลังจะถูกตั้งเป็นแอดมิน** (ยังไม่ใช่แอดมิน
ตอนที่เช็ค) — ใช้ `assert_google_only_admin()` เดี่ยว ๆ กับ `providers` ที่มันอ่านมาเอง

`order_ops.py`/`_production_gate.py` เช็ค provider ของ **ผู้สั่งการที่ต้องเป็นแอดมิน
อยู่แล้ว** (`--actor <email>`) — ใช้ `resolve_admin_actor()` ซึ่งทำครบสามด่าน:
lookup ด้วยอีเมล → ต้องเป็น `is_admin` อยู่แล้ว → (ถ้า `require_google_only=True`)
ต้องมี provider เป็น `{google}` พอดี

**`resolve_admin_actor()` ใช้กับ `grant_admin.py` ไม่ได้** — target ของสคริปต์นั้น
ยังไม่ใช่แอดมินตอนที่เช็ค (นั่นคือทั้งประเด็นของสคริปต์ — จะให้สิทธิ์ก็ต่อเมื่อผ่านด่านนี้ก่อน)
ด่านที่ใช้ร่วมกันได้จริงมีแค่ **การเทียบ provider เท่านั้น** (`assert_google_only_admin`)
ไม่ใช่ทั้งฟังก์ชัน — grant_admin.py จึง import เฉพาะ `assert_google_only_admin` +
`load_oauth_providers` ไม่ใช่ `resolve_admin_actor` ทั้งก้อน (**พฤติกรรม/exit code
ของ `grant_admin.py` เท่าเดิมทุกประการ** — เทสเดิมทุกตัวใน `tests/unit/test_grant_admin.py`
ไม่ถูกแก้แม้บรรทัดเดียว ‹แก้ 2026-09-21 · critic รอบ 1 L-1: ถ้อยคำเดิมเขียนว่า
"ไฟล์นี้ไม่ถูกแก้เลยสักบรรทัด" ซึ่งเกินจริง — ไฟล์เทส **มี** เทสใหม่เพิ่มเข้ามา
(`test_google_only_check_is_the_same_object_as_actor_module`) สิ่งที่ไม่ถูกแก้คือ
เทส**เดิม**ทั้งหมดและพฤติกรรมของ `grant_admin.grant()`/exit code เท่านั้น›)

## `require_google_only` — INF-41 ตั้งใจไม่บังคับบน sit

`order_ops.dispatch()` เรียก `resolve_admin_actor(..., require_google_only=(target ==
"production"))` — บน `dev`/`sit` ด่าน google-only **ไม่บังคับ** (มติเดิมของ INF-41 OD-3:
`--actor` เป็น attribution ไม่ใช่ authentication ในช่วง Closed Beta) ส่วนบน `production`
ผ่าน `_production_gate.production_gate()` ซึ่งส่ง `require_google_only=True` เสมอ
(ADR-0015 A3-D3 ①)
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from scripts.seed._shared import PrecheckError

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.models.enums import OAuthProvider
    from app.models.user import User


class ActorNotFound(PrecheckError):
    """ไม่พบบัญชีตามอีเมลที่ระบุใน users."""


class ActorNotAdmin(PrecheckError):
    """บัญชีมีอยู่จริงแต่ไม่มีสิทธิ์แอดมิน."""


class ActorNotGoogleOnly(PrecheckError):
    """บัญชีมีทางเข้าอื่นนอกจาก google — 2-Step Verification ของ Google ไม่ครอบทางนั้น."""


async def load_oauth_providers(
    session: "AsyncSession", user_id
) -> set["OAuthProvider"]:
    """เซตของ provider ที่ `user_id` มี sign-in อยู่ — ใช้ร่วมกันทั้งสองความหมายข้างบน."""
    from sqlalchemy import select

    from app.models.user import OAuthIdentity

    return set(
        (
            await session.scalars(
                select(OAuthIdentity.provider).where(OAuthIdentity.user_id == user_id)
            )
        ).all()
    )


def assert_google_only_admin(providers: set["OAuthProvider"], *, email: str) -> None:
    """ปฏิเสธถ้า `providers != {google}` พอดี — ด่านเดียวที่ทั้งสองความหมายใช้ร่วมกัน

    🔴 **`!=` ไม่ใช่ `"google" not in providers`** — บัญชีที่มี `{google, password}`
    ต้องถูกปฏิเสธเหมือนกัน เพราะทางเข้าที่สองเลี่ยง 2-Step Verification ของ Google
    ไปได้ทั้งเส้น (ดู docstring ของ `ADR-0031` Amendment 1 — ห้ามเล่าซ้ำที่นี่)

    🔴 **`email` รับเข้ามาแต่ห้ามใส่ในข้อความ error** (`security-baseline` §2 — stdout
    ของ `docker exec` ถูก redirect/paste ลงแชทบ่อย) พารามิเตอร์นี้ยังอยู่เพื่อให้ผู้เรียก
    เดิม (`grant_admin.py`) ส่งได้โดยไม่ต้องแก้ call site — ดู `test_order_ops.py`
    ที่ยืนยันว่า stderr ของ `order_ops.py` ต้องไม่มี `"@"` เลย
    """
    from app.models.enums import OAuthProvider

    if providers != {OAuthProvider.google}:
        listed = ", ".join(sorted(p.value for p in providers)) or "(ไม่มีเลย)"
        raise ActorNotGoogleOnly(
            f"บัญชีนี้มี sign-in provider = {listed}\n"
            "ต้องเข้าได้ทางเดียวคือ google เท่านั้น (ADR-0031 Amendment 1) — "
            "ด่านจริงที่คุ้มครองบัญชีนี้คือ Google 2-Step Verification ซึ่งครอบเฉพาะ"
            "เส้น google · ทางเข้าอื่นจะเลี่ยง 2SV ไปได้ทั้งเส้น"
        )


async def resolve_admin_actor(
    session: "AsyncSession",
    email: str,
    *,
    require_google_only: bool = True,
) -> "User":
    """แปลงอีเมล `--actor` → `User` ที่ยืนยันแล้วว่าเป็นแอดมิน (+ google-only ถ้าขอ)

    ใช้โดย `order_ops.dispatch()` (`require_google_only=target=="production"` — INF-41
    OD-3) และ `_production_gate.production_gate()` (`require_google_only=True` เสมอ —
    ADR-0015 A3-D3 ①) **ไม่ใช่** โดย `grant_admin.py` (ดู docstring หัวไฟล์)
    """
    from app.repositories import user_repository

    target = await user_repository.get_by_email(session, email)
    if target is None:
        # 🔴 ห้ามใส่อีเมลลงข้อความ (security-baseline §2) — เหมือน order_ops.py เดิม
        raise ActorNotFound(
            "ไม่พบบัญชีตามอีเมลที่ระบุใน --actor ใน users — ต้องเป็นบัญชีที่เคย "
            "sign-in มาก่อน"
        )
    if not target.is_admin:
        raise ActorNotAdmin(f"user {target.id} ไม่มีสิทธิ์แอดมิน")
    if require_google_only:
        providers = await load_oauth_providers(session, target.id)
        assert_google_only_admin(providers, email=email)
    return target
