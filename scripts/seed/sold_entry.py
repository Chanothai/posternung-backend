"""บันทึกการขายนอกระบบ — service transition ที่เขียน `status = sold` + `sold_at`
(ADR-0025 · INF-24)

    ./venv/bin/python scripts/seed/sold_entry.py \\
        --poster-uuid <uuid ของใบที่ขายไปแล้ว> \\
        --sold-at <เวลาที่ของขายออกไปจริง ISO-8601 พร้อม timezone> \\
        --reason <เพราะอะไรถึงบันทึกว่าขายแล้ว>                     # 1. dry-run (default)
    ./venv/bin/python scripts/seed/sold_entry.py --commit \\
        --poster-uuid <uuid> --sold-at <...> --reason <...> \\
        --reviewed-by <ชื่อคุณ> \\
        --reviewed-at <เวลาที่คุณตัดสิน ISO-8601 พร้อม timezone>

🔴 **ค่าตัวอย่างข้างบนเป็น placeholder ที่ก๊อปทั้งบรรทัดแล้วรันไม่ผ่านโดยตั้งใจ** —
เหตุการณ์เดิม 2026-08-08: ตัวอย่างเวลาที่เป็นเวลาจริงถูกก๊อปทั้งบรรทัดแล้ว `reviewed_at`
ของ 232 แถวลงเป็นอนาคต 3.5 ชั่วโมง 🔴 **ห้ามก๊อปค่าจริงของ `ec3478a8` (THE MATRIX ·
วันที่ 12 กรกฎาคม 2026 บ่ายสี่โมงตามเวลาไทย) มาเป็นตัวอย่างในเอกสารเด็ดขาด** — สะกด
เป็นตัวเลข ISO-8601 แล้วมันจะเป็นค่าที่ก๊อปแล้วรันได้ทันที (มีเทสสแกนทั้งโฟลเดอร์บังคับ
ข้อนี้อยู่ — `test_no_example_anywhere_is_a_timestamp_someone_can_copy_and_run`)
`assert_not_in_the_future()` ปฏิเสธค่าที่อยู่ในอนาคตตั้งแต่ `main()` แล้ว (ADR-0010 D5)

## เส้นทางใหม่นี้ต่างจากอีกหกเส้นที่มีอยู่ตรงจุดเดียวที่สำคัญที่สุด

อีกหกเส้น (`seed_posters.py` · `apply_suggestions.py` · `manual_entry.py` ·
`reference_entry.py` · `correction_entry.py` · `split_entry.py` — ADR-0015 D1 ·
ADR-0024 D2) เขียน `posters` ผ่าน ORM/Core ตรง · **เส้นนี้เรียก
`poster_service.mark_sold()` แทน — ห้ามเขียน ORM ตรงเอง** (ADR-0025 **D1**): `status`
เป็นแกนที่ `poster_service` คุมแต่ผู้เดียว (`poster-database` §3 · ADR-0010 D2 ·
ADR-0019 A-D1) เส้นนี้จึงเป็นเส้นแรก (และเส้นเดียว) ของ `scripts/seed/` ที่ import
`app.services` แทนที่จะหยุดแค่ `app.models`/`app.core.database`

## เขียนได้แค่สองคอลัมน์: `posters.status` → `sold` และ `posters.sold_at`

ไม่แตะคอลัมน์อื่นของ `posters` เลย ไม่แตะ `published_at` (AC-5 · ADR-0013 D6 · A-D1)
ไม่แตะ `reservations` เลยสักคอลัมน์ (ADR-0025 D3) — ตรรกะทั้งหมดอยู่ใน `mark_sold()`
ไม่ใช่ในไฟล์นี้ (ไฟล์นี้แค่ parse args · แสดงพรีวิว · เรียก service · commit)

## `--sold-at` กับ `--reviewed-at` เป็นคนละค่า (ADR-0025 D4)

`--sold-at` = เวลาที่ **ของขายออกไปจริง** (อดีตที่ไกลได้มาก — ขายผ่าน TikTok ก่อน
บันทึกเข้าระบบเป็นเดือนได้) · `--reviewed-at` = เวลาที่ **คุณกรอกใบนี้** ยุบเป็นค่า
เดียวจะได้ประวัติราคาที่ผิด (เหตุผลเดียวที่ ADR-0013 Amendment A-D3 เพิ่มคอลัมน์นี้มา)
ทั้งคู่ปฏิเสธเวลาในอนาคตด้วย `assert_not_in_the_future()` ตัวเดิมจาก `_shared.py`
(import ไม่ก๊อป) — ข้อความ error ของฟังก์ชันนั้นผูกคำว่า `--reviewed-at`/"เวลาที่คน
ตัดสิน" ไว้ตรง ๆ เพราะออกแบบมาให้เส้นอื่นเรียกก่อน ตอนใช้กับ `--sold-at` จึงห่อ
ข้อความเพิ่มอีกชั้นให้ชัดว่ากำลังพูดถึง flag ไหน (ดู `main()`)

## แถวไหนถูกปฏิเสธ (fail-closed ทั้งหมด — ไม่เขียนอะไรเลยเมื่อปฏิเสธ)

`--poster-uuid` ไม่มีใน DB · `status` เดิมไม่ใช่ `available` (ขายซ้ำ/ใบกำลังจอง) ·
มี reservation ที่ยัง `active` อยู่บนใบนี้ (ADR-0002 — คืนเงินไม่ได้ จึงห้ามยึดของที่มี
ลูกค้าค้างจ่ายอยู่ · ไม่มี `--force` — ADR-0025 D3/OD-2) · `--reason` ว่าง ·
`--sold-at`/`--reviewed-at` รูปแบบผิดหรืออยู่ในอนาคต

## `--target dev|sit` เท่านั้น — ไม่มี `production` (ADR-0015 D8)

เหมือนอีกห้าเส้นทุกประการ · `sit` ต้องรันข้างในคอนเทนเนอร์ sit และ `DATABASE_URL`
ต้องตรงกับ `.env.sit` เป๊ะ (`assert_target()`)

## dry-run เป็น default

ไม่ใส่ `--commit` = พรีวิวอย่างเดียว — `run()` ไม่เรียก `mark_sold()` เลยถ้าไม่ใส่
`--commit` จึงไม่มีการเขียน DB เกิดขึ้นแม้แต่ในทรานแซกชันที่จะ rollback ทีหลัง
"""

from __future__ import annotations

import argparse
import os
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

SEED_DIR = Path(__file__).resolve().parent
REPO_ROOT = SEED_DIR.parents[1]
sys.path.insert(0, str(REPO_ROOT))

from scripts.seed._shared import (  # noqa: E402
    PrecheckError,
    _parse_reviewed_at,
    assert_not_in_the_future,
)
from scripts.seed.apply_suggestions import _load_env  # noqa: E402
from scripts.seed.manual_entry import (  # noqa: E402
    SIT_ENV_FILE,
    TARGETS,
    assert_target,
)


def _parse_sold_at(raw: str) -> datetime:
    """ISO-8601 ที่ต้องมี timezone — ตรรกะเดียวกับ `_parse_reviewed_at()` ของ
    `_shared.py` เป๊ะ แต่เขียนแยกเพราะข้อความ error ของฟังก์ชันนั้นผูกคำว่า
    `--reviewed-at` ไว้ตรง ๆ ในตัวข้อความ การใช้ร่วมจะพิมพ์ "--reviewed-at ... ไม่ใช่
    ISO-8601" ตอนที่ผู้ใช้พิมพ์ `--sold-at` ผิด ซึ่งชี้ผิด flag ให้คนอ่าน

    ด่านปฏิเสธเวลาอนาคต (ตัวที่แพงกว่าและ ADR สั่งห้ามก๊อปตรง ๆ) ยังใช้
    `assert_not_in_the_future()` ตัวเดิมร่วมกับ `--reviewed-at` อยู่ — ดู `main()`
    """
    try:
        value = datetime.fromisoformat(raw)
    except ValueError:
        raise PrecheckError(f"--sold-at {raw!r} ไม่ใช่ ISO-8601") from None
    if value.tzinfo is None:
        raise PrecheckError(
            f"--sold-at {raw!r} ไม่มี timezone — ต้องระบุเอง "
            "ตามรูปแบบ YYYY-MM-DDThh:mm:ss+07:00"
        )
    return value


def _report(
    *,
    poster_title: str,
    poster_id: uuid.UUID,
    current_status: str,
    sold_at: datetime,
    reason: str,
    active_reservation_id: uuid.UUID | None,
    will_be_rejected: bool,
    target_label: str,
    committed: bool,
) -> None:
    print()
    print("=" * 72)
    print(f"ปลายทาง : {target_label}")
    print(f"โปสเตอร์ : {poster_id}  ({poster_title})")
    print(f"status ปัจจุบัน : {current_status}")
    print(f"sold_at ที่จะเขียน : {sold_at.isoformat()}")
    print(f"เหตุผล : {reason}")

    if active_reservation_id is not None:
        print()
        print(
            f"🔴 มี reservation ที่ยัง active อยู่บนใบนี้ (id={active_reservation_id}) "
            "— ปฏิเสธเสมอ ไม่มี --force (ADR-0025 D3): มีลูกค้าค้างกลางทางจ่ายเงินที่"
            "ระบบคืนเงินให้ไม่ได้ (ADR-0002) · ไปตัดสินเองว่าจะทำอย่างไรกับใบนี้ก่อน"
        )
    elif will_be_rejected:
        print()
        print(f"🔴 status ปัจจุบันไม่ใช่ available ({current_status}) — ปฏิเสธเสมอ")

    print()
    if not committed:
        print("DRY-RUN — ไม่ได้เขียนอะไรลง database (ใส่ --commit เพื่อเขียนจริง)")
    print("=" * 72)


async def run(args: argparse.Namespace, target_label: str) -> int:
    from app.core.database import async_session_maker
    from app.core.exceptions import AppError
    from app.models.enums import PosterStatus
    from app.repositories import poster_repository, reservation_repository
    from app.services import poster_service

    async with async_session_maker() as session:
        poster = await poster_repository.get_by_id(session, args.poster_uuid)
        if poster is None:
            print(
                f"ไม่พบโปสเตอร์ {args.poster_uuid} ที่ {target_label}", file=sys.stderr
            )
            return 1

        active_reservation = await reservation_repository.get_active_reservation(
            session, args.poster_uuid
        )

        _report(
            poster_title=poster.title,
            poster_id=poster.id,
            current_status=poster.status.value,
            sold_at=args.sold_at,
            reason=args.reason,
            active_reservation_id=(
                active_reservation.id if active_reservation is not None else None
            ),
            will_be_rejected=poster.status != PosterStatus.available,
            target_label=target_label,
            committed=args.commit,
        )

        if not args.commit:
            return 0

        try:
            await poster_service.mark_sold(
                session,
                args.poster_uuid,
                sold_at=args.sold_at,
                reviewed_by=args.reviewed_by,
                reviewed_at=args.reviewed_at,
                reason=args.reason,
                source="sold_entry.py",
            )
        except AppError as exc:
            await session.rollback()
            print(f"\n🔴 ปฏิเสธ: {exc.message}", file=sys.stderr)
            if exc.details:
                print(f"   รายละเอียด: {exc.details}", file=sys.stderr)
            return 1

        await session.commit()

        # อ่านค่ากลับมาเทียบ — แบบเดียวกับเส้นที่ 2–5 (verify_corrections() ฯลฯ)
        refreshed = await poster_repository.get_by_id(session, args.poster_uuid)
        assert refreshed is not None  # เพิ่งเขียนไปเองเมื่อครู่
        problems: list[str] = []
        if refreshed.status != PosterStatus.sold:
            problems.append(f"status ควรเป็น sold แต่ได้ {refreshed.status.value}")
        if refreshed.sold_at != args.sold_at:
            problems.append(
                f"sold_at ควรเป็น {args.sold_at.isoformat()} แต่อ่านกลับมาได้ "
                f"{refreshed.sold_at.isoformat() if refreshed.sold_at else None}"
            )
        if problems:
            print(
                "\n🔴 การเขียนไม่ลงตามแผน — commit ไปแล้ว ต้องตรวจด้วยมือ:",
                file=sys.stderr,
            )
            for problem in problems:
                print(f"  {problem}", file=sys.stderr)
            return 1

    print(
        f"\nบันทึกแล้ว: {args.poster_uuid} → status=sold sold_at="
        f"{args.sold_at.isoformat()} — ตรวจซ้ำด้วยการอ่านค่ากลับมาเทียบแล้ว ตรงทุกค่า"
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--commit",
        action="store_true",
        help="เขียนลง database จริง (ไม่ใส่ = dry-run พรีวิวอย่างเดียว ไม่แตะ DB เลย)",
    )
    parser.add_argument(
        "--poster-uuid",
        required=True,
        type=uuid.UUID,
        metavar="<uuid ของใบที่ขายไปแล้ว>",
        help="UUID ของโปสเตอร์ที่ขายไปแล้ว (มาจากใบเดียวเสมอ — ไม่ใช่ไฟล์ใบงาน batch "
        "ตาม ADR-0025 OD-3: ปริมาณจริง 3–5 ใบ/เดือน)",
    )
    parser.add_argument(
        "--sold-at",
        required=True,
        metavar="<เวลาที่ของขายออกไปจริง ISO-8601 พร้อม timezone>",
        help="เวลาที่ **ของขายออกไป** ไม่ใช่เวลาที่รันสคริปต์นี้ (ADR-0025 D4) "
        "· ปฏิเสธเวลาในอนาคต",
    )
    parser.add_argument(
        "--reason",
        required=True,
        metavar="<เพราะอะไรถึงบันทึกว่าขายแล้ว>",
        help="บังคับ ห้ามว่าง — ลง poster_attribute_reviews.reason (ADR-0025 D1 ข้อ 2)",
    )
    parser.add_argument(
        "--target",
        choices=TARGETS,
        default="dev",
        help="ปลายทาง — เหมือนอีกห้าเส้นทุกประการ (ADR-0015 D8: dev กับ sit เท่านั้น "
        "production ไม่มีให้เลือกโดยตั้งใจ) · sit ต้องรันข้างในคอนเทนเนอร์ sit และ "
        f"DATABASE_URL ต้องตรงกับ {SIT_ENV_FILE} เป๊ะ",
    )
    parser.add_argument(
        "--reviewed-by",
        help="ชื่อคนที่ตัดสินว่าใบนี้ขายแล้ว — บังคับเมื่อ --commit (ADR-0010 D1)",
    )
    parser.add_argument(
        "--reviewed-at",
        metavar="<เวลาที่คุณตัดสิน ISO-8601 พร้อม timezone>",
        help="บังคับเมื่อ --commit · เวลาที่คุณกรอกใบนี้ — ต่างจาก --sold-at "
        "(ADR-0025 D4) · ไม่มี default เป็นเวลาปัจจุบัน (ADR-0010 D5)",
    )
    args = parser.parse_args()

    if not args.reason.strip():
        parser.error("--reason ต้องไม่ว่าง")

    now = datetime.now(timezone.utc)
    try:
        args.sold_at = _parse_sold_at(args.sold_at)
        assert_not_in_the_future(args.sold_at, now=now)
    except PrecheckError as exc:
        parser.error(
            f"--sold-at ผิดเงื่อนไข: {exc}\n"
            "    (ข้อความข้างบนอาจอ้างคำว่า '--reviewed-at'/'เวลาที่คนตัดสิน' เพราะ "
            "ด่านปฏิเสธเวลาอนาคตใช้ฟังก์ชันร่วมกับ --reviewed-at โดยตั้งใจ (ADR-0010 "
            "D5 · import ไม่ก๊อป) — ให้อ่านว่า '--sold-at ต้องไม่ใช่เวลาในอนาคต' แทน)"
        )

    if args.commit:
        if not args.reviewed_by:
            parser.error("--commit ต้องระบุ --reviewed-by ด้วย (ADR-0010 D1)")
        if not args.reviewed_at:
            parser.error("--commit ต้องระบุ --reviewed-at ด้วย (ADR-0010 D5)")
        try:
            args.reviewed_at = _parse_reviewed_at(args.reviewed_at)
            # 🔴 จุดเดียวในโมดูลที่อ่านนาฬิกา — และอ่านเพื่อ **ปฏิเสธ** เท่านั้น
            # ไม่เคยถูกใช้เป็นค่าให้ arg ใด (ADR-0010 D5 · มีเทส AST ล็อกแบบเดียวกัน
            # ในเส้นอื่นแล้ว)
            assert_not_in_the_future(args.reviewed_at, now=now)
        except PrecheckError as exc:
            parser.error(str(exc))
    # dry-run: args.reviewed_by/args.reviewed_at เป็น None อยู่แล้วจาก argparse
    # (ไม่ required ตอนไม่ --commit) — run() ไม่อ่านค่าทั้งสองเลยนอก `if args.commit`

    _load_env(args.target)
    database_url = os.environ.get("DATABASE_URL", "")
    if not database_url:
        print(f"ไม่พบ DATABASE_URL (target={args.target})", file=sys.stderr)
        return 1

    try:
        target_label = (
            f"{assert_target(database_url, args.target)}  [--target {args.target}]"
        )
    except PrecheckError as exc:
        print(
            f"precheck ไม่ผ่าน: {exc}\n"
            "(ADR-0015 D8 — production ไม่มีให้เลือกเลย · --target sit ต้องรัน"
            f"ข้างในคอนเทนเนอร์ sit และ DATABASE_URL ต้องตรงกับ {SIT_ENV_FILE} เป๊ะ)",
            file=sys.stderr,
        )
        return 1

    import asyncio

    try:
        return asyncio.run(run(args, target_label))
    except PrecheckError as exc:
        print(f"precheck ไม่ผ่าน: {exc}", file=sys.stderr)
        return 1
    except OSError as exc:
        hint = ""
        if args.target == "sit":
            hint = (
                "\n--target sit ต้องรัน **ข้างในคอนเทนเนอร์ sit** ไม่ใช่จากเครื่องนี้:\n"
                "  docker compose -p posternung-sit \\\n"
                "    -f docker-compose.yml -f docker-compose.sit.yml --env-file .env.sit \\\n"
                "    exec app python scripts/seed/sold_entry.py --target sit ..."
            )
        print(
            f"ต่อ database ไม่ได้ (target={args.target}): {exc}{hint}", file=sys.stderr
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
