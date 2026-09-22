"""ตรวจว่า **ทุกบัญชีแอดมินยังเข้าได้ทางเดียวคือ google** — ADR-0031 Amendment 1

## อาการที่ไฟล์นี้มีไว้จับ

สิทธิ์แอดมินของระบบนี้ถูกคุ้มครองด้วย **Google Account 2-Step Verification** ของบัญชี
เจ้าของ ไม่ใช่ด้วย Firebase/Identity Platform MFA — เพราะในเส้น federated Firebase
**ไม่ได้พิสูจน์ตัวตนเอง มันเชื่อคำยืนยันของ Google** ⇒ 2SV คือด่านจริง

แต่ 2SV ครอบเฉพาะ **เส้น google** · backend รับ 3 provider (`google` · `password` ·
`phone`) และ `auth_service.firebase_login()` ผูก provider ใหม่เข้า **user row เดิม**
เมื่อ Firebase uid ตรง **หรือ email ที่ verified แล้วตรงกัน**

⇒ วันที่บัญชีแอดมินมีทางเข้าที่สองเมื่อไหร่ **การป้องกันทั้งหมดเสื่อมลงเงียบ ๆ**
ไม่มี error ไม่มีเทสแดง ไม่มีอะไรเปลี่ยนบนหน้าจอ — สิ่งเดียวที่เปลี่ยนคือมีประตู
ที่ 2SV เอื้อมไม่ถึงเพิ่มมาหนึ่งบาน

🔴 **ไฟล์นี้เป็นตัว *ตรวจจับ* ไม่ใช่ตัว *ป้องกัน*** — ตัวป้องกันคือด่านใน
`scripts/grant_admin.py` ซึ่งรันทุกครั้งที่มีการให้สิทธิ์ (exit 4) · ไฟล์นี้จับกรณีที่
provider ถูกผูกเพิ่ม **หลัง** ให้สิทธิ์ไปแล้ว ซึ่งด่านนั้นมองไม่เห็นเพราะมันจบไปแล้ว

## รันที่ไหน · บ่อยแค่ไหน

**ตอน deploy ทุกครั้ง** (คู่กับ `check_container_migrations.py`) และ **รันมือได้ทุกเมื่อ**

🔴 **รันบน GitHub CI ไม่ได้** — CI คลาวด์เข้าถึง DB ของ sit/production ที่อยู่ใน docker
บนเครื่องเจ้าของไม่ได้เลย · การใส่ไว้ใน workflow จะได้ด่านที่ดูเหมือนมีแต่ไม่เคยทำงาน
ซึ่งแย่กว่าไม่มี เพราะมันสร้างความรู้สึกปลอดภัยที่ไม่มีของจริงรองรับ

⚠️ **ยอมรับตรง ๆ ว่ามันไม่ได้รันเองระหว่าง deploy** — ช่วงเวลาที่ provider ถูกผูกเพิ่ม
จนถึง deploy ครั้งถัดไปคือช่องที่ไม่มีใครเฝ้า · นั่นคือเหตุผลที่ด่านใน `grant_admin.py`
เป็นตัวหลัก ไม่ใช่ไฟล์นี้

```bash
./venv/bin/python scripts/check_admin_providers.py posternung-sit-app
```

## exit code — สามค่าโดยตั้งใจ

| exit | แปลว่า |
|---|---|
| `0` | ทุกแถวที่ `is_admin = true` มี provider = `{google}` พอดี |
| `1` | พบแถวที่ละเมิด — มี provider อื่น หรือไม่มี provider เลย |
| `2` | **ตรวจไม่ได้** (ไม่มี docker · container ไม่รัน · query ล้ม) |

🔴 **`2` ต้องไม่ถูกอ่านว่า "ผ่าน"** — ทรงเดียวกับ `.claude/scripts/check-contract-drift.py`
ของ INF-31 · ด่านที่กลืนความล้มเหลวของตัวเองเป็น "เขียว" คือด่านที่โกหก

**แถวที่ไม่มี provider เลยก็นับว่าละเมิด** — `oauth_identities` ถูกสร้างตอน sign-in ผ่าน
Firebase ครั้งแรก ⇒ แอดมินที่ไม่มีสักแถวแปลว่า user row นั้นเกิดนอกเส้นทาง Firebase
ซึ่ง ADR-0031 D6.1 ห้ามไว้ตรงตัว (`grant_admin.py` ห้ามสร้าง user ใหม่ให้เอง)
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys

ALLOWED_PROVIDERS = {"google"}

# รันในคอนเทนเนอร์เพื่อใช้ DATABASE_URL ที่ resolve แล้วของมันเอง — ไม่ต้องรู้รหัสผ่าน
# และไม่ต้องเดาว่า compose แทนค่า $VAR ให้หรือยัง (กับดักที่เจอจริง 2026-08-25:
# `docker run --env-file` ไม่แทนค่า $VAR ส่วน compose แทน → InvalidPasswordError
# ที่อ่านแล้วเหมือนรหัสผ่านผิดทั้งที่ไฟล์ถูกทุกตัวอักษร)
_QUERY = """
import asyncio, json
from sqlalchemy import select
from app.core.database import async_session_maker
from app.models.user import OAuthIdentity, User


async def main():
    async with async_session_maker() as s:
        admins = (await s.scalars(select(User).where(User.is_admin.is_(True)))).all()
        out = []
        for u in admins:
            provs = (
                await s.scalars(
                    select(OAuthIdentity.provider).where(OAuthIdentity.user_id == u.id)
                )
            ).all()
            out.append(
                {
                    "user_id": str(u.id),
                    "email": u.email,
                    "providers": sorted(p.value for p in provs),
                }
            )
        print("ADMIN_PROVIDERS_JSON " + json.dumps(out, ensure_ascii=False))


asyncio.run(main())
"""


def read_admins(container: str) -> list[dict]:
    """คืนรายชื่อแอดมินพร้อม provider — raise RuntimeError ถ้าตรวจไม่ได้."""
    try:
        result = subprocess.run(
            ["docker", "exec", container, "python", "-c", _QUERY],
            capture_output=True,
            text=True,
        )
    except FileNotFoundError as exc:  # ไม่มี docker บนเครื่องนี้
        raise RuntimeError(f"เรียก docker ไม่ได้: {exc}") from exc

    if result.returncode != 0:
        raise RuntimeError(
            f"docker exec {container} ล้ม (exit {result.returncode})\n"
            + (result.stderr or "").strip()[-500:]
        )

    for line in result.stdout.splitlines():
        if line.startswith("ADMIN_PROVIDERS_JSON "):
            return json.loads(line[len("ADMIN_PROVIDERS_JSON ") :])
    raise RuntimeError(
        "ไม่เจอบรรทัดผลลัพธ์ในเอาต์พุตของคอนเทนเนอร์ — query อาจไม่ได้รันจริง\n"
        + (result.stdout or "").strip()[-500:]
    )


def violations(admins: list[dict]) -> list[dict]:
    return [a for a in admins if set(a["providers"]) != ALLOWED_PROVIDERS]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "container",
        help="ชื่อคอนเทนเนอร์ของแอป เช่น posternung-sit-app",
    )
    args = parser.parse_args()

    try:
        admins = read_admins(args.container)
    except RuntimeError as exc:
        print(f"check-admin-providers: ⚠️ ตรวจไม่ได้ — {exc}", file=sys.stderr)
        print("   'ตรวจไม่ได้' ไม่ใช่ 'ผ่าน' (exit 2)", file=sys.stderr)
        return 2

    if not admins:
        # ไม่ใช่ความล้มเหลว: หลัง migration แต่ก่อน grant_admin.py ระบบไม่มีแอดมินเลย
        # ซึ่งเป็นสถานะที่ถูกต้องตาม ADR-0031 D8 (fail-closed)
        print("check-admin-providers: ✅ ยังไม่มีแอดมินในระบบ — ไม่มีอะไรให้ตรวจ")
        return 0

    bad = violations(admins)
    if bad:
        print(
            f"check-admin-providers: 🔴 พบแอดมินที่เข้าได้มากกว่าทาง google "
            f"({len(bad)}/{len(admins)} คน)",
            file=sys.stderr,
        )
        for a in bad:
            listed = ", ".join(a["providers"]) or "(ไม่มี provider เลย)"
            print(f"   {a['email'] or a['user_id']} → {listed}", file=sys.stderr)
        print(
            "\nGoogle 2-Step Verification ครอบเฉพาะเส้น google — ทางเข้าอื่นเลี่ยง 2SV\n"
            "ได้ทั้งเส้น (ADR-0031 Amendment 1) · ถอนสิทธิ์หรือถอด provider ส่วนเกินออก",
            file=sys.stderr,
        )
        return 1

    print(
        f"check-admin-providers: ✅ แอดมิน {len(admins)} คน เข้าได้ทางเดียวคือ google"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
