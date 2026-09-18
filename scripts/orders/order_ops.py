#!/usr/bin/env python3
"""ประตูของเส้นธุรกรรม (order/payment) ที่แอดมินทำมือ — INF-41 (ADR-0035 D2)

แทน `SCR-15` ใน Closed Beta: ตอนนี้มีแอดมินคนเดียว ไม่มี UI แอดมิน ⇒ สคริปต์นี้เป็น
ทางเข้าเดียวที่ทำให้ออร์เดอร์เดินต่อจาก `PAYMENT_REVIEW` ได้ (ไม่มีมันเลย ออร์เดอร์ทุกใบ
ใน Beta ค้างตายที่ `PAYMENT_REVIEW` — ดู `docs/status/gates/INF-41-gate1.md` §why)

    ./venv/bin/python scripts/orders/order_ops.py verify-payment \\
        --order-no <PN-YYMMDD-NNNN> --actor <อีเมลแอดมิน> \\
        --at <เวลาที่ยืนยัน ISO-8601 พร้อม timezone> \\
        --bank-statement-checked                                   # dry-run (default)

    ./venv/bin/python scripts/orders/order_ops.py verify-payment --commit \\
        --order-no <PN-YYMMDD-NNNN> --actor <อีเมลแอดมิน> \\
        --at <เวลาที่ยืนยัน ISO-8601 พร้อม timezone> \\
        --bank-statement-checked --audit-log var/order-ops.jsonl   # เขียนจริง

    ./venv/bin/python scripts/orders/order_ops.py reject-payment --commit \\
        --order-no <PN-YYMMDD-NNNN> --actor <อีเมลแอดมิน> \\
        --at <เวลาที่ตัดสิน ISO-8601 พร้อม timezone> \\
        --reason <เหตุผล — สรุปผลที่ติดต่อผู้ซื้อแล้ว> \\
        --audit-log var/order-ops.jsonl

    ./venv/bin/python scripts/orders/order_ops.py ship --commit \\
        --order-no <PN-YYMMDD-NNNN> --actor <อีเมลแอดมิน> \\
        --at <เวลาที่กดส่ง ISO-8601 พร้อม timezone> \\
        --tracking-no <เลขพัสดุ> --carrier <ผู้ให้บริการขนส่ง> \\
        --audit-log var/order-ops.jsonl

    ./venv/bin/python scripts/orders/order_ops.py complete --commit \\
        --order-no <PN-YYMMDD-NNNN> --actor <อีเมลแอดมิน> \\
        --at <เวลาที่ปิดออร์เดอร์ ISO-8601 พร้อม timezone> \\
        --audit-log var/order-ops.jsonl

🔴 **ค่าตัวอย่างข้างบนเป็น placeholder ที่ก๊อปทั้งบรรทัดแล้วรันไม่ผ่านโดยตั้งใจ** —
ทรงเดียวกับ `scripts/seed/manual_entry.py` (เหตุการณ์ 2026-08-08: ตัวอย่างที่เป็นเวลาจริง
ถูกก๊อปมาทั้งบรรทัดแล้วลงข้อมูลผิดไป 232 แถว) `assert_not_in_the_future()` ปฏิเสธเวลา
อนาคตตั้งแต่ `main()` แล้ว (ADR-0010 D5)

## มติ AC-8 — ทำไมเป็น dispatcher ตัวที่สอง ไม่ใช่ lane ใน `poster_ops.py`

`poster_ops.py` เป็นประตูของ**เส้นทางเขียน `posters`** (ADR-0015 D1 — "คนละแหล่งค่า
คนละกฎ") เส้นธุรกรรมในไฟล์นี้**ไม่เขียน `posters` เลยสักคอลัมน์**โดยตรง (เขียนผ่าน
`apply_order_transition()` ที่ไปเรียก `mark_sold_by_order()` เองอีกที) — ยัดเข้าไปใน
`poster_ops.py` จะทำให้ชื่อไฟล์โกหกและทำให้ `LANES` numbering ของมันผูกกับ README §5
ที่พูดถึงคนละเรื่อง จึงแยกเป็นไฟล์ที่สองแทน (รายละเอียดเต็ม:
`docs/status/gates/INF-41-gate1.md` §03) ราคาที่จ่ายคือมี "ที่ที่สองที่ต้องคุม
`--target`" ให้ตรงกัน — แก้ด้วยการ **import ของเดิมมาใช้ ไม่ประกาศเอง** (ดูส่วน import
ด้านล่าง: `TARGETS` / `assert_target` / `_load_env` / `append_audit_line` ทุกตัวเป็น
`object` เดียวกับที่ `scripts/seed/manual_entry.py` และ `scripts/grant_admin.py` ใช้)

หนึ่งไฟล์นี้มีสี่ (วันนี้สาม) subcommand ผ่าน `argparse` subparsers ไม่ใช่สี่ไฟล์ + เรียก
subprocess เหมือน `poster_ops.py` — เหตุผลที่ `poster_ops.py` แยกเป็น subprocess
(คนละ venv คนละด่าน import-time) ไม่มีในเส้นเหล่านี้ ทุกเส้นอยู่ใน process/venv เดียวกัน
และแชร์ด่าน `assert_target()` จุดเดียวกันอยู่แล้ว

## 🔴 OD-3 — `--actor` คือ attribution ไม่ใช่ authentication

`--actor <email>` ถูก lookup เป็น `users.id` แล้วบังคับว่าต้อง `is_admin` — แต่ **นี่คือ
attribution ไม่ใช่ authentication** ตัวยืนยันตัวตนจริงที่ปกป้องเส้นทางนี้อยู่คือ
**credential ของฐานข้อมูลที่คนรันสคริปต์ถืออยู่** ไม่ใช่ค่าที่พิมพ์ผ่าน `--actor` (ใครก็พิมพ์
อีเมลของคนอื่นได้ถ้าเข้าถึง DB ได้อยู่แล้ว) ⇒ ใช้ได้เฉพาะช่วง **Closed Beta ที่มีแอดมิน
คนเดียว** เท่านั้น เมื่อมีแอดมินคนที่สองหรือเข้า Phase ถัดไป ด่านตัวตนจริง (provider
`google` + 2-Step Verification) เป็นของ **`INF-44` AC-2** และเส้นทางที่ควรแทนสคริปต์นี้
ทั้งก้อนคือ **endpoint ที่มี token** (`SCR-15` · `INF-35` gap2) — ไม่ใช่การเติมด่านใน
ไฟล์นี้

## `--target production` ไม่มีโดยตั้งใจ

เหมือนทุกสคริปต์ operator ตัวอื่น (`ADR-0015` D8) — `TARGETS = ("dev", "sit")` เท่านั้น
ประตูปลดล็อก production เป็นของ **`INF-44` AC-1** แก้ที่เดียว (`manual_entry.TARGETS`)
แล้วมีผลกับทุกสคริปต์ที่ import จากตรงนั้นรวมถึงไฟล์นี้ — ไม่มีอะไรให้แก้ที่นี่

## 🔴 `reject-payment` = ยกเลิกออร์เดอร์ ไม่มีหน้าต่างแก้ตัวในระบบอีกแล้ว (A2-D3)

ลงแล้วตาม `ADR-0033` Amendment 2 (A2-D1/A2-D2 — เจ้าของเคาะทาง (ก) ที่ GATE 1 ของ
`/feature INF-41` สไลซ์ B) — `PAYMENT_REVIEW → CANCELLED` ทันที + ปล่อยของกลับขึ้น
ชั้น**ทันทีไม่พึ่งนาฬิกา** (ไม่ใช่ `→ AWAITING_PAYMENT` ให้จ่ายใหม่ที่ออร์เดอร์เดิม
อย่างที่เคยออกแบบไว้ — ทำไม่ได้จริง อ่านเหตุผลเต็มที่ ADR)

**ขั้นตอน concierge (กระบวนการ ไม่ใช่โค้ด — A2-D3):**

- 🔴 **แอดมินต้องติดต่อผู้ซื้อก่อนกดปฏิเสธเสมอ** — ปฏิเสธ = ยกเลิกออร์เดอร์และปล่อย
  ของทันที ไม่มีหน้าต่างแก้ตัวให้ผู้ซื้อคนเดิมอีกเลย (ช่องทางติดต่อดูจาก
  `order_shipping_details`) · ผลการติดต่อบันทึกลง `--reason`
- **ผู้ที่โอนจริงแต่ถูกปฏิเสธ** (โอนผิดยอด/โอนช้าจนแอดมินตัดสินไปแล้ว) = **คืนเงินด้วย
  มือตาม BR-P9** — ทำได้เพราะเป็นโอนธนาคาร ไม่มีโค้ดของเรื่องนี้ในสคริปต์นี้
- BR-P10 เดิมเขียนว่า "จ่ายใหม่ได้อีก 30 นาที" — **ความหมายเปลี่ยนเป็น "จองและ
  สั่งใหม่ได้"** ผ่านแอป (`reserve_listing()`/`create_order()` ปกติ) ไม่มีหน้าต่าง
  30 นาทีพิเศษให้ผู้ซื้อคนเดิมอีกแล้ว — แข่งกับคนอื่นตามกติกาสต็อก=1 ปกติ

## audit สองจังหวะ (มติเจ้าของ)

`--commit` เขียน audit **สองบรรทัด**: `phase="intent"` **ก่อน**เรียก service ·
`phase="committed"` **หลัง** `session.commit()` สำเร็จ · ถ้าระหว่างนั้นล้มเหลว (service
raise หรือ `commit()` ล้ม) → `session.rollback()` + เขียน `phase="failed"` พร้อม
`error=<ชื่อคลาส exception>` (**ไม่มี message** — ป้องกันข้อความ error รั่ว PII/detail
ลง log) แล้ว exit 1 · ถ้าเขียน `phase="intent"` เองไม่สำเร็จ (`AuditWriteFailed`) →
**ไม่เรียก service เลย ไม่แตะ DB** (ทรงเดียวกับ `grant_admin.py` D6-b: "เขียนร่องรอย
ไม่ได้ ต้องไม่มีผลข้างเคียงเกิดขึ้น")

audit record: `{phase, lane, order_no, order_id, from_status, to_status, actor_user_id,
at, ran_at, hostname, target}` (+ `error` เฉพาะ `phase="failed"`) — 🔴 **ห้ามมี email /
DATABASE_URL / password ในบรรทัดไหนเลย** (`security-baseline` §2) `ran_at` มาจาก
ตัวแปร `now` ตัวเดียวกับที่ป้อนด่าน `assert_not_in_the_future`
"""

from __future__ import annotations

import argparse
import asyncio
import os
import socket
import sys
from datetime import datetime, timezone
from pathlib import Path

ORDERS_DIR = Path(__file__).resolve().parent
REPO_ROOT = ORDERS_DIR.parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

# 🔴 import ของเดิม ไม่ประกาศเอง — ทรงเดียวกับที่ `sold_entry.py` ทำกับ `manual_entry.py`
from scripts._audit import AuditWriteFailed, append_audit_line  # noqa: E402
from scripts.seed._shared import (  # noqa: E402
    PrecheckError,
    _parse_reviewed_at,
    assert_not_in_the_future,
)
from scripts.seed.apply_suggestions import _load_env  # noqa: E402
from scripts.seed.manual_entry import SIT_ENV_FILE, TARGETS, assert_target  # noqa: E402

LANES = ("verify-payment", "reject-payment", "ship", "complete")

# ปลายทางของแต่ละเส้น — ใช้แค่พิมพ์รายงาน/เขียน audit ไม่ใช่ตัวตัดสิน (ตัวตัดสินจริง
# คือ `app/core/state_machine.py` ผ่าน `apply_order_transition()`) จึงเป็น literal
# string พอ ไม่ต้อง import `OrderStatus` มาที่ระดับโมดูล (เลี่ยงการ import `app.*`
# ก่อน `_load_env()` — ดู "ทำไมเรียกเป็น subprocess" ใน `poster_ops.py` เทียบ)
_LANE_TO_STATUS = {
    "verify-payment": "AWAITING_SHIPMENT",
    "reject-payment": "CANCELLED",
    "ship": "SHIPPED",
    "complete": "COMPLETED",
}


def _report(
    *,
    lane: str,
    order_no: str,
    from_status: str,
    to_status: str,
    actor_email: str,
    at: datetime,
    target_label: str,
    committed: bool,
) -> None:
    print()
    print("=" * 72)
    print(f"ปลายทาง : {target_label}")
    print(f"เส้น : {lane}")
    print(f"order_no : {order_no}")
    print(f"สถานะ : {from_status} → {to_status}")
    print(f"actor (attribution ไม่ใช่ authentication) : {actor_email}")
    print(f"at : {at.isoformat()}")
    print()
    if not committed:
        print(
            "DRY-RUN — ไม่ได้เรียก service และไม่ได้เขียนอะไรลง database (ใส่ --commit)"
        )
    print("=" * 72)


async def dispatch(
    session,
    args: argparse.Namespace,
    target_label: str,
    *,
    now: datetime,
) -> int:
    """แกนของสคริปต์ — แยกจาก `run()` เพื่อให้เทสฉีด session ของตัวเองเข้ามาได้

    ทรงเดียวกับ `grant_admin.grant()`/`run()` — `run()` เป็นตัวเปิด session จริง
    การผูกกับ `async_session_maker` ตรง ๆ จะทำให้เทสที่ต้องใช้ `db_session` fixture
    (transaction แยกที่ rollback ทิ้งเองตาม `conftest.py`) มองไม่เห็นข้อมูลที่เขียนไว้
    """
    from app.core.exceptions import AppError
    from app.repositories import order_repository, user_repository
    from app.services.order_service import (
        complete_order,
        reject_payment,
        ship_order,
        verify_payment,
    )

    hostname = socket.gethostname()
    to_status = _LANE_TO_STATUS[args.lane]

    actor = await user_repository.get_by_email(session, args.actor)
    if actor is None:
        print(f"ไม่พบบัญชีอีเมล {args.actor} ใน users", file=sys.stderr)
        return 1
    if not actor.is_admin:
        print(f"{args.actor} ไม่มีสิทธิ์แอดมิน — ปฏิเสธ (OD-3)", file=sys.stderr)
        return 1

    order = await order_repository.get_by_order_no(session, args.order_no)
    if order is None:
        print(f"ไม่พบคำสั่งซื้อ {args.order_no}", file=sys.stderr)
        return 1

    from_status = order.status.value
    order_id = order.id

    _report(
        lane=args.lane,
        order_no=args.order_no,
        from_status=from_status,
        to_status=to_status,
        actor_email=args.actor,
        at=args.at,
        target_label=target_label,
        committed=args.commit,
    )

    if not args.commit:
        return 0

    record = {
        "lane": args.lane,
        "order_no": args.order_no,
        "order_id": str(order_id),
        "from_status": from_status,
        "to_status": to_status,
        "actor_user_id": str(actor.id),
        "at": args.at.isoformat(),
        "ran_at": now.isoformat(),
        "hostname": hostname,
        "target": args.target,
    }
    audit_path = Path(args.audit_log)

    try:
        append_audit_line(audit_path, {**record, "phase": "intent"})
    except AuditWriteFailed as exc:
        print(
            f"เขียน audit ไม่สำเร็จ ({exc}) — ไม่เรียก service ไม่แตะ DB",
            file=sys.stderr,
        )
        return 1

    try:
        if args.lane == "verify-payment":
            await verify_payment(
                session,
                order_id,
                actor_user_id=actor.id,
                bank_statement_checked=args.bank_statement_checked,
                at=args.at,
            )
        elif args.lane == "reject-payment":
            await reject_payment(
                session,
                order_id,
                actor_user_id=actor.id,
                reason=args.reason,
                at=args.at,
            )
        elif args.lane == "ship":
            await ship_order(
                session,
                order_id,
                actor_user_id=actor.id,
                tracking_no=args.tracking_no,
                carrier=args.carrier,
                at=args.at,
            )
        elif args.lane == "complete":
            await complete_order(session, order_id, actor_user_id=actor.id, at=args.at)
        else:  # pragma: no cover — argparse choices ของ subparsers กันไว้แล้ว
            raise AssertionError(f"lane ไม่รู้จัก: {args.lane}")

        await session.commit()
    except Exception as exc:
        await session.rollback()
        try:
            append_audit_line(
                audit_path,
                {**record, "phase": "failed", "error": type(exc).__name__},
            )
        except AuditWriteFailed:
            pass  # DB rollback ไปแล้ว — เขียน audit ไม่ได้ก็ไม่มีอะไรให้ทำต่อ
        if isinstance(exc, AppError):
            print(f"🔴 ปฏิเสธ: {exc.message}", file=sys.stderr)
        else:
            print(f"🔴 ล้มเหลว: {type(exc).__name__}", file=sys.stderr)
        return 1

    append_audit_line(audit_path, {**record, "phase": "committed"})

    print(f"\nสำเร็จ: {args.order_no} · {args.lane} · {from_status} → {to_status}")
    return 0


async def run(args: argparse.Namespace, target_label: str, *, now: datetime) -> int:
    """เปิด session จริงแล้วมอบงานต่อให้ `dispatch()` — ทางเข้าจริงของ `main()`"""
    from app.core.database import async_session_maker

    async with async_session_maker() as session:
        return await dispatch(session, args, target_label, now=now)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="order_ops.py",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    subparsers = parser.add_subparsers(dest="lane", required=True)

    def add_common(sp: argparse.ArgumentParser) -> None:
        sp.add_argument(
            "--order-no",
            required=True,
            metavar="PN-YYMMDD-NNNN",
            help="เลขที่คำสั่งซื้อ",
        )
        sp.add_argument(
            "--actor",
            required=True,
            metavar="<อีเมลแอดมินผู้สั่ง>",
            help="อีเมลของผู้สั่ง — lookup users.id แล้วบังคับ is_admin "
            "🔴 attribution ไม่ใช่ authentication (ดู docstring หัวไฟล์)",
        )
        sp.add_argument(
            "--at",
            required=True,
            metavar="<เวลาที่เหตุการณ์นี้เกิด ISO-8601 พร้อม timezone>",
            help="ไม่มี default เป็นเวลาปัจจุบัน (ADR-0010 D5) · ปฏิเสธเวลาในอนาคต",
        )
        sp.add_argument(
            "--target",
            choices=TARGETS,
            default="dev",
            help="ปลายทาง — dev/sit เท่านั้น (ADR-0015 D8) · production ไม่มีให้เลือกโดยตั้งใจ "
            f"(INF-44 AC-1) · sit ต้องรันข้างในคอนเทนเนอร์ sit และ DATABASE_URL ต้องตรงกับ "
            f"{SIT_ENV_FILE} เป๊ะ",
        )
        sp.add_argument(
            "--commit",
            action="store_true",
            help="เขียนจริง — ไม่ใส่ = dry-run พิมพ์สรุปอย่างเดียว ไม่เรียก service เลย",
        )
        sp.add_argument(
            "--audit-log",
            metavar="<path>",
            help="path ของไฟล์ audit แบบ append-only (JSONL) — บังคับเมื่อ --commit",
        )

    verify_payment_parser = subparsers.add_parser(
        "verify-payment",
        help="ยืนยันเงินเข้า (BR-P2) — PAYMENT_REVIEW → AWAITING_SHIPMENT",
    )
    add_common(verify_payment_parser)
    verify_payment_parser.add_argument(
        "--bank-statement-checked",
        action="store_true",
        help="ยืนยันว่าเห็นยอดในบัญชีจริงแล้ว (SCR-15 AC-3) — ไม่ใส่ = ปฏิเสธก่อนเปิด session",
    )

    reject_payment_parser = subparsers.add_parser(
        "reject-payment",
        help="ปฏิเสธสลิป = ยกเลิกออร์เดอร์ทันที — PAYMENT_REVIEW → CANCELLED",
    )
    add_common(reject_payment_parser)
    reject_payment_parser.add_argument(
        "--reason",
        required=True,
        metavar="<เหตุผล>",
        help="บังคับ ห้ามว่าง — ลง cancellation_reason + payments.rejection_reason "
        "(A2-D3: ติดต่อผู้ซื้อก่อนเสมอ แล้วสรุปผลไว้ที่นี่)",
    )

    ship_parser = subparsers.add_parser(
        "ship", help="กดส่งของแทนผู้ขาย — AWAITING_SHIPMENT → SHIPPED"
    )
    add_common(ship_parser)
    ship_parser.add_argument(
        "--tracking-no", required=True, metavar="<เลขพัสดุ>", help="ห้ามว่าง"
    )
    ship_parser.add_argument("--carrier", default=None, metavar="<ผู้ให้บริการขนส่ง>")

    complete_parser = subparsers.add_parser(
        "complete", help="ปิดออร์เดอร์ — SHIPPED → COMPLETED"
    )
    add_common(complete_parser)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    if args.commit and not args.audit_log:
        parser.error("--commit ต้องระบุ --audit-log ด้วย")

    if args.lane == "verify-payment" and not args.bank_statement_checked:
        parser.error(
            "verify-payment ต้องระบุ --bank-statement-checked เสมอ "
            "(SCR-15 AC-3 — สลิปไม่ใช่หลักฐาน ต้องเห็นยอดในบัญชีจริงก่อน)"
        )
    if args.lane == "ship" and not (args.tracking_no or "").strip():
        parser.error("ship ต้องระบุ --tracking-no ที่ไม่ว่าง")
    if args.lane == "reject-payment" and not (args.reason or "").strip():
        parser.error("reject-payment ต้องระบุ --reason ที่ไม่ว่าง")

    now = datetime.now(timezone.utc)
    try:
        args.at = _parse_reviewed_at(args.at, flag="--at")
        # 🔴 จุดเดียวในโมดูลที่อ่านนาฬิกา — และอ่านเพื่อ **ปฏิเสธ** เท่านั้น (ADR-0010 D5)
        # `now` ตัวเดียวกันนี้ถูกส่งต่อไปเป็น `ran_at` ของ audit ใน run()
        assert_not_in_the_future(args.at, now=now)
    except PrecheckError as exc:
        parser.error(str(exc))

    try:
        _load_env(args.target)
    except PrecheckError as exc:
        print(f"precheck ไม่ผ่าน: {exc}", file=sys.stderr)
        return 1
    database_url = os.environ.get("DATABASE_URL", "")
    if not database_url:
        print("ไม่พบ DATABASE_URL", file=sys.stderr)
        return 1

    try:
        target_label = assert_target(database_url, args.target)
    except PrecheckError as exc:
        print(f"precheck ไม่ผ่าน: {exc}", file=sys.stderr)
        return 1

    try:
        return asyncio.run(run(args, target_label, now=now))
    except PrecheckError as exc:
        print(f"precheck ไม่ผ่าน: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
