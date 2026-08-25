"""ตั้งสิทธิ์แอดมินให้บัญชีที่มีอยู่แล้ว — ทางเดียวของการตั้งแอดมิน **คนแรก** (ADR-0031 D6)

    ./venv/bin/python scripts/grant_admin.py \
        --email someone@example.com --granted-by "ชื่อคนสั่ง" \
        --audit-log var/admin-grants.jsonl                        # dry-run (ค่าเริ่มต้น)

    ./venv/bin/python scripts/grant_admin.py \
        --email someone@example.com --granted-by "ชื่อคนสั่ง" \
        --audit-log var/admin-grants.jsonl --commit               # เขียนจริง

ทำไมต้องมีสคริปต์นี้: หลัง migration `c9f4a2e07b18` **ไม่มีใครเป็นแอดมินเลย** และ
endpoint ที่จะตั้งแอดมินก็อยู่หลัง `require_admin` เอง ⇒ ไก่กับไข่ที่จะทำให้ SCR-15
ค้างทั้งใบถ้าไม่วางทางไว้ (ADR-0031 D6)

ทางที่ถูกปฏิเสธไปแล้วและเหตุผล — **อย่าเอากลับมา**:
  (ข) SQL มือ            → ไม่มีร่องรอยว่าใครให้สิทธิ์ใครเมื่อไหร่
  (ค) env `BOOTSTRAP_ADMIN_EMAIL` → 🔴 เส้นทางยกระดับสิทธิ์ที่ทำงานเงียบ ๆ
                            **ทุกครั้งที่ container restart**

## เงื่อนไขบังคับ 3 ข้อ (ADR-0031 D6-a/b/c) — ทุกข้อมีเทสคุม

D6-a  **dry-run เป็นค่าเริ่มต้น** ต้องใส่ `--commit` ถึงจะเขียนจริง
      ทรงเดียวกับเส้นนำเข้า 8 เส้นของ `poster_ops.py` — การให้สิทธิ์สูงสุดต้องไม่เกิด
      จากการพิมพ์คำสั่งพลาด

D6-b  **บันทึก audit ทุกครั้งที่เขียนจริง**: ใครถูกตั้ง · เมื่อไหร่ · โดยใคร
      ADR-0031 D1 เลือก A-1 (`users.is_admin`) ซึ่ง **ไม่มีประวัติในตัว** ⇒ ร่องรอย
      ต้องมาจากที่นี่แทน ไม่งั้นจะไม่มีทางตอบได้เลยว่าใครให้สิทธิ์ใคร
      · ที่เก็บ = **ไฟล์ append-only ที่ผู้รันระบุ** (เจ้าของเลือก 2026-08-25) —
      **ไม่สร้างตาราง audit ใหม่** เพราะตารางแบบนั้นหน้าตาเหมือน A-3 ที่ D1 ปฏิเสธไป
      คนอ่านย้อนหลังจะเข้าใจว่าเราแอบกลับมติ
      ⚠️ ข้อจำกัดที่รู้ตัว: ไฟล์ในคอนเทนเนอร์หายได้ ร่องรอยอ่อนกว่าตาราง

D6-c  **ปฏิเสธถ้ามีแอดมินอยู่แล้ว** เว้นแต่ใส่ `--allow-additional-admin`
      กันไม่ให้สคริปต์ bootstrap กลายเป็นประตูหลังถาวร — หลังพ้นช่วงตั้งคนแรกแล้ว
      การเพิ่มแอดมินต้องไปผ่าน endpoint ที่มี `require_admin` ไม่ใช่สคริปต์ที่ใครมี
      shell ก็รันได้

## 🔴 อีเมลรับผ่าน --email เสมอ ห้าม hardcode (ADR-0031 D6.1)

ค่าที่เจ้าของระบุไว้เป็นแอดมินคนแรกคือ **ข้อมูลนำเข้าของการรันสคริปต์ ไม่ใช่ค่า default
ในโค้ด** — ถ้า hardcode ไว้ มันจะกลายเป็นบัญชีที่ถูกตั้งเป็นแอดมินซ้ำทุกครั้งที่มีคน
รันสคริปต์ ซึ่งเป็นสิ่งที่ D6-c เขียนขึ้นมาป้องกันพอดี
(มีเทสสแกนว่าไม่มีอีเมลนั้นเป็น literal ใน `app/` และ `scripts/`)

## บัญชีต้องมีอยู่แล้ว — ห้ามสร้างให้เอง

user ที่ไม่ได้มาจาก Firebase จะไม่มีแถวใน `oauth_identities` และ **ล็อกอินไม่ได้
ตลอดกาล** ⇒ อีเมลที่หาไม่เจอต้องถูกปฏิเสธอย่างชัดเจน ไม่ใช่สร้างแถวใหม่ให้

## ลำดับการเขียนตอน --commit

เขียน audit → `UPDATE` → `session.commit()`

**audit มาก่อนเสมอ** เพราะถ้าเขียนร่องรอยไม่ได้ ต้องไม่มีการให้สิทธิ์เกิดขึ้นเลย
ผลข้างเคียงที่ยอมรับ: ถ้า commit ล้มหลัง audit ถูกเขียน จะมีบรรทัด audit ของการให้
สิทธิ์ที่ไม่ได้เกิด — **ยอมให้ audit เกินดีกว่าให้สิทธิ์แบบเงียบ**

🔴 **ห้ามใช้ `session.rollback()` เป็นทางถอย** — `grant()` รับ session จากข้างนอก
(ดู docstring ของมัน) การ rollback จะล้างงานของคนเรียกทั้งทรานแซกชันไปด้วย
เคยเป็นบั๊กจริงในรอบนี้: เทส D6-b ล้มเพราะ user ที่เทสสร้างไว้หายไปพร้อมกัน

Exit code
    0  สำเร็จ (รวม dry-run และกรณีเป็นแอดมินอยู่แล้ว = ไม่ต้องทำอะไร)
    1  หาบัญชีตามอีเมลไม่เจอ
    2  มีแอดมินอยู่แล้วและไม่ได้ใส่ --allow-additional-admin (D6-c)
    3  เขียน audit ไม่สำเร็จ — ไม่มีการให้สิทธิ์เกิดขึ้น
    4  บัญชีเป้าหมายมี sign-in provider นอกเหนือจาก google (Amendment 1)
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

BACKEND_ROOT = Path(__file__).resolve().parent.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))


class AuditWriteFailed(RuntimeError):
    """เขียนไฟล์ audit ไม่สำเร็จ — ต้องไม่ให้สิทธิ์ต่อ (D6-b)."""


def append_audit_line(audit_path: Path, record: dict[str, Any]) -> None:
    """เขียน 1 บรรทัด JSON ต่อท้ายไฟล์ audit (append-only).

    เปิดด้วยโหมด "a" เท่านั้น — ไม่มีเส้นทางไหนในสคริปต์นี้ที่เขียนทับของเดิมได้
    """
    try:
        audit_path.parent.mkdir(parents=True, exist_ok=True)
        with audit_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")
    except OSError as exc:
        raise AuditWriteFailed(str(exc)) from exc


async def grant(session: Any, args: argparse.Namespace) -> int:
    """แกนของสคริปต์ — แยกจาก run() เพื่อให้เทสฉีด session ของตัวเองเข้ามาได้

    (run() เป็นตัวเปิด session จริง · การผูกกับ async_session_maker ตรง ๆ จะทำให้
    เทส D6-c ที่ต้องรันสองครั้งบน DB เดียวกันเขียนไม่ได้เลย)
    """
    from sqlalchemy import func, select

    from app.models.enums import OAuthProvider
    from app.models.user import OAuthIdentity, User

    audit_path = Path(args.audit_log)

    target = await session.scalar(select(User).where(User.email == args.email))
    if target is None:
        print(
            f"ไม่พบบัญชีอีเมล {args.email} ใน users\n"
            "สคริปต์นี้ไม่สร้าง user ใหม่ให้โดยตั้งใจ — บัญชีต้องเคย sign-in ผ่าน "
            "Firebase มาก่อน ไม่งั้นจะไม่มีแถวใน oauth_identities และล็อกอินไม่ได้ตลอดกาล",
            file=sys.stderr,
        )
        return 1

    if target.is_admin:
        print(f"{args.email} เป็นแอดมินอยู่แล้ว — ไม่ต้องทำอะไร")
        return 0

    # D6-c — นับแอดมินที่มีอยู่ (target ยังไม่ใช่แอดมิน จึงไม่ต้องกันตัวเองออก)
    existing_admins = await session.scalar(
        select(func.count()).select_from(User).where(User.is_admin.is_(True))
    )
    if existing_admins and not args.allow_additional_admin:
        print(
            f"ปฏิเสธ — ระบบมีแอดมินอยู่แล้ว {existing_admins} คน (ADR-0031 D6-c)\n"
            "หลังพ้นช่วงตั้งแอดมินคนแรกแล้ว การเพิ่มแอดมินต้องผ่าน endpoint ที่มี "
            "require_admin ไม่ใช่สคริปต์นี้\n"
            "ถ้าตั้งใจจริง ให้ใส่ --allow-additional-admin",
            file=sys.stderr,
        )
        return 2

    # ── ด่าน google-only (ADR-0031 Amendment 1) ──────────────────────────────
    # สิทธิ์แอดมินถูกคุ้มครองด้วย Google Account 2-Step Verification ของบัญชีนั้น
    # ซึ่งได้ผลก็ต่อเมื่อ **ทางเข้าเดียวของบัญชีคือ provider google** — Firebase ไม่ได้
    # พิสูจน์ตัวตนเองในเส้น federated มันเชื่อคำยืนยันของ Google
    #
    # 🔴 backend รับ 3 provider และ auth_service ผูก provider ใหม่เข้า user row เดิม
    # เมื่อ Firebase uid ตรง **หรือ email ที่ verified แล้วตรงกัน** ⇒ ถ้าบัญชีแอดมิน
    # มีทางเข้าอื่นนอกจาก google การเปิด 2SV จะไม่ได้คุ้มครองทางเข้านั้นเลย
    # เหตุผลเต็มอยู่ที่ ADR-0031 Amendment 1 — ห้ามเล่าซ้ำที่นี่
    providers = set(
        (
            await session.scalars(
                select(OAuthIdentity.provider).where(OAuthIdentity.user_id == target.id)
            )
        ).all()
    )
    if providers != {OAuthProvider.google}:
        listed = ", ".join(sorted(p.value for p in providers)) or "(ไม่มีเลย)"
        print(
            f"ปฏิเสธ — บัญชี {args.email} มี sign-in provider = {listed}\n"
            "แอดมินต้องเข้าได้ทางเดียวคือ google เท่านั้น (ADR-0031 Amendment 1)\n"
            "เพราะด่านจริงที่คุ้มครองบัญชีนี้คือ Google 2-Step Verification ซึ่งครอบ\n"
            "เฉพาะเส้น google — ทางเข้าอื่นจะเลี่ยง 2SV ไปได้ทั้งเส้น",
            file=sys.stderr,
        )
        return 4

    if not args.commit:
        print(
            "dry-run — ยังไม่เขียนอะไรทั้งนั้น (ADR-0031 D6-a)\n"
            f"  จะตั้ง is_admin = true ให้ {args.email} (user_id={target.id})\n"
            f"  จะบันทึก audit ต่อท้าย {audit_path}\n"
            f"  โดย {args.granted_by}\n"
            "ใส่ --commit เพื่อเขียนจริง"
        )
        return 0

    granted_at = datetime.now(timezone.utc)

    # audit ต้องลงก่อนแตะ DB — ถ้าเขียนร่องรอยไม่ได้ ต้องไม่มีการให้สิทธิ์เกิดขึ้นเลย
    try:
        append_audit_line(
            audit_path,
            {
                "granted_to_email": args.email,
                "granted_to_user_id": str(target.id),
                "granted_at": granted_at.isoformat(),
                "granted_by": args.granted_by,
            },
        )
    except AuditWriteFailed as exc:
        print(
            f"เขียน audit ไม่สำเร็จ ({exc}) — ไม่ให้สิทธิ์\n"
            "การให้สิทธิ์ที่ไม่มีร่องรอยคือสิ่งที่ ADR-0031 D6-b ห้ามไว้",
            file=sys.stderr,
        )
        return 3

    target.is_admin = True
    await session.flush()
    await session.commit()
    print(
        f"ตั้ง {args.email} (user_id={target.id}) เป็นแอดมินแล้ว\n"
        f"  audit ต่อท้ายที่ {audit_path}"
    )
    return 0


async def run(args: argparse.Namespace) -> int:
    from app.core.database import async_session_maker

    async with async_session_maker() as session:
        return await grant(session, args)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="ตั้งสิทธิ์แอดมินให้บัญชีที่มีอยู่แล้ว (ADR-0031 D6)",
    )
    parser.add_argument(
        "--email",
        required=True,
        help="อีเมลของบัญชีที่จะตั้งเป็นแอดมิน — ต้องมีแถวใน users อยู่แล้ว",
    )
    parser.add_argument(
        "--granted-by",
        required=True,
        help="ใครเป็นคนสั่งให้สิทธิ์นี้ — ลงใน audit (D6-b)",
    )
    parser.add_argument(
        "--audit-log",
        required=True,
        help="path ของไฟล์ audit แบบ append-only (JSON บรรทัดละรายการ)",
    )
    parser.add_argument(
        "--commit",
        action="store_true",
        help="เขียนจริง — ไม่ใส่ = dry-run (D6-a)",
    )
    parser.add_argument(
        "--allow-additional-admin",
        action="store_true",
        help="ยอมให้เพิ่มแอดมินทั้งที่มีอยู่แล้ว — ต้องตั้งใจเท่านั้น (D6-c)",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    return asyncio.run(run(args))


if __name__ == "__main__":
    raise SystemExit(main())
