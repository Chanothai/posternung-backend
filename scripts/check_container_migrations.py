"""ตรวจว่า **image ที่รันอยู่รู้จัก migration ครบเท่าโค้ด** — `docs/BACKLOG.md` **BL-88**

## อาการที่ข้อนี้มีไว้จับ

`Dockerfile` COPY `alembic/` เข้า image ตอน build · ถ้า deploy image เก่ากว่าโค้ด
แล้วสั่ง `docker exec <c> alembic upgrade head` **มันจะจบเงียบ ๆ exit 0** เพราะ
alembic ในคอนเทนเนอร์ *ไม่เห็นไฟล์ revision ใหม่* จึงถือว่าถึง head แล้วจริง ๆ
— ไม่มี error ไม่มี warning และ **output หน้าตาเหมือนกรณีที่ทุกอย่างถูกต้องเป๊ะ**

ซ้ำร้าย `CMD` ของ image รัน `alembic upgrade head` ตอน start อยู่แล้ว คำสั่งที่คน
สั่งตามทีหลังจึงเป็น no-op เสมอ — **"no-op เพราะ migrate ไปแล้ว" กับ "no-op เพราะ
image ไม่รู้จัก migration ใหม่" แยกจากกันไม่ได้เลยจาก output**

รอบ 2026-08-07 รอดมาได้เพราะคน `ls` ไฟล์ revision ในคอนเทนเนอร์ด้วยมือก่อน migrate
· **นั่นคือคนจำได้ ไม่ใช่ระบบบังคับ** — ไฟล์นี้คือระบบนั้น

## สิ่งที่ตรวจ

เทียบสามอย่าง ซึ่งต้องตรงกันหมดถึงจะผ่าน:

| | มาจากไหน | ตอบคำถามว่า |
|---|---|---|
| `repo` | `alembic history/heads` บน host (โค้ดที่ checkout อยู่) | โค้ดมี migration ถึงไหน |
| `image` | `alembic history/heads` **ในคอนเทนเนอร์** | image รู้จักถึงไหน |
| `db` | `alembic current` ในคอนเทนเนอร์ | DB ปลายทางอยู่ที่ไหน |

🔴 **เทียบด้วย *รายชื่อ revision ทั้งชุด* ไม่ใช่แค่ head** — head เป็นค่าที่
*เปลี่ยน* ไม่ใช่ค่าที่ *สะสม* · การเทียบเฉพาะ head บอกได้แค่ว่า "ต่างกัน"
แต่บอกไม่ได้ว่า image **เก่ากว่า** หรือ **คนละสาย** ซึ่งเป็นคนละปัญหาและคนละทางแก้

## วิธีใช้

```bash
./venv/bin/python scripts/check_container_migrations.py posternung-sit-app
./venv/bin/python scripts/check_container_migrations.py posternung-prod-app --wait 60
```

`--wait` = รอ `CMD` ของคอนเทนเนอร์รัน `alembic upgrade head` ให้จบก่อนตัดสิน
(ใช้ตอนเรียกทันทีหลัง deploy) · ไม่ใส่ = ตัดสินจากสถานะ ณ ตอนนี้เลย
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


# --------------------------------------------------------------------------
# ส่วน pure — ไม่เรียก docker ไม่เรียก alembic เพื่อให้ test ครอบได้ครบทุกสาขา
# --------------------------------------------------------------------------


def parse_revisions(history_output: str) -> set[str]:
    """`alembic history` → เซตของ revision id ทั้งหมดที่ฝั่งนั้น *รู้จัก*

    รูปแบบบรรทัด: `<down_rev> -> <rev> (head), <message>` หรือ `<rev>, <message>`
    (แถวฐานไม่มีลูกศร) · ตัดที่คอมมาแรกก่อนเสมอ เพราะ **ข้อความ commit ในโปรเจกต์นี้
    เป็นภาษาไทยและมีทั้ง `->` และ `,` ปนอยู่จริง** (เช่น "verification_note → reference_note")
    การ split ทั้งบรรทัดจะกลืนคำในข้อความมาเป็น revision id
    """
    revisions: set[str] = set()
    for line in history_output.splitlines():
        head, _, _ = line.partition(",")
        head = head.strip()
        if not head:
            continue
        # `<down> -> <rev>` → เอาฝั่งขวา · แถวฐานไม่มีลูกศร → ทั้งก้อนคือ rev
        candidate = head.split("->")[-1].strip()
        candidate = candidate.replace("(head)", "").replace("(base)", "").strip()
        # `(mergepoint)`/`(branchpoint)` ฯลฯ ที่อาจตามมา — เอาโทเคนแรกพอ
        candidate = candidate.split()[0] if candidate.split() else ""
        if candidate:
            revisions.add(candidate)
    return revisions


def parse_heads(heads_output: str) -> set[str]:
    """`alembic heads` / `alembic current` → เซตของ revision id

    DB ที่ยังไม่เคย migrate เลย ทำให้ `alembic current` ไม่พิมพ์อะไรออก stdout →
    คืนเซตว่าง ซึ่ง `diagnose()` แปลว่า "ยังไม่ migrate" ไม่ใช่ "ตรงกันแล้ว"
    """
    heads: set[str] = set()
    for line in heads_output.splitlines():
        token = line.strip().split()
        if token:
            heads.add(token[0])
    return heads


@dataclass(frozen=True)
class Side:
    """สถานะของฝั่งหนึ่ง — `revisions` = ที่รู้จักทั้งหมด · `heads` = ปลายทางปัจจุบัน."""

    revisions: set[str]
    heads: set[str]


@dataclass(frozen=True)
class Verdict:
    ok: bool
    code: str
    message: str


def diagnose(repo: Side, image: Side, db_current: set[str]) -> Verdict:
    """ตัดสินจากสามฝั่ง — pure ล้วน · ลำดับการเช็คมีความหมาย

    เช็ค image ก่อน db เสมอ เพราะถ้า image ผิดตัว สถานะของ DB จะตีความไม่ได้:
    `db == image.heads` บน image ที่เก่ากว่าโค้ด **แปลว่า "migrate ครบแล้ว" ผิด ๆ**
    ซึ่งเป็นข้อความที่อันตรายที่สุดที่เครื่องมือนี้จะพูดได้
    """
    if not image.revisions:
        return Verdict(
            False,
            "IMAGE_HAS_NO_MIGRATIONS",
            "คอนเทนเนอร์ไม่มีไฟล์ migration เลยสักตัว — image build ผิด "
            "(Dockerfile ต้อง COPY alembic/) หรือชี้คอนเทนเนอร์ผิดตัว",
        )

    if repo.revisions != image.revisions:
        missing_in_image = sorted(repo.revisions - image.revisions)
        extra_in_image = sorted(image.revisions - repo.revisions)
        if missing_in_image and not extra_in_image:
            return Verdict(
                False,
                "IMAGE_BEHIND_CODE",
                "🔴 **image เก่ากว่าโค้ด** — คอนเทนเนอร์ไม่รู้จัก migration "
                f"{len(missing_in_image)} ตัว: {', '.join(missing_in_image)}\n"
                "\n"
                "`alembic upgrade head` ในคอนเทนเนอร์จะ **จบเงียบ ๆ exit 0** "
                "เพราะมันไม่เห็นไฟล์พวกนี้ — ไม่ใช่เพราะ migrate ครบแล้ว\n"
                "ทางแก้: build image ใหม่จากโค้ดปัจจุบัน แล้ว `up -d --force-recreate` "
                "· **ห้ามสั่ง upgrade ซ้ำแล้วเชื่อว่าผ่าน**",
            )
        if extra_in_image and not missing_in_image:
            return Verdict(
                False,
                "IMAGE_AHEAD_OF_CODE",
                "🔴 **image ใหม่กว่าโค้ดที่ checkout อยู่** — คอนเทนเนอร์มี migration "
                f"ที่โค้ดนี้ไม่มี: {', '.join(extra_in_image)}\n"
                "\n"
                "มักแปลว่ากำลังจะ deploy ของเก่าทับของใหม่ หรือ checkout ผิด branch "
                "· **หยุดก่อน** — deploy ต่อไปจะทำให้ DB อยู่หน้า image",
            )
        return Verdict(
            False,
            "DIVERGED",
            "🔴 **image กับโค้ดคนละสาย** — ต่างกันทั้งสองทิศ\n"
            f"  โค้ดมีแต่ image ไม่มี : {', '.join(missing_in_image)}\n"
            f"  image มีแต่โค้ดไม่มี : {', '.join(extra_in_image)}\n"
            "มักเกิดจาก rebase/merge ที่เขียน migration ทับกัน — ต้องดูด้วยมือ",
        )

    unknown_to_image = db_current - image.revisions
    if unknown_to_image:
        return Verdict(
            False,
            "DB_AHEAD_OF_IMAGE",
            "🔴 **DB อยู่หน้า image** — DB ถูก migrate ด้วยโค้ดที่ใหม่กว่านี้: "
            f"{', '.join(sorted(unknown_to_image))}\n"
            "\n"
            "การรัน image นี้ต่อคือการถอยโค้ดโดยไม่ถอย schema — **อันตราย** "
            "· อย่า downgrade เพื่อให้มันตรง (ห้ามตาม CLAUDE.md) ให้ deploy image "
            "ที่ตรงกับ DB แทน",
        )

    if not db_current:
        return Verdict(
            False,
            "DB_NOT_MIGRATED",
            "🔴 **DB ยังไม่เคย migrate เลย** — `alembic_version` ว่าง\n"
            "`CMD` ของ image รัน `alembic upgrade head` ตอน start อยู่แล้ว "
            "การที่ยังว่างแปลว่ามันล้มเหลว → ดู `docker logs`",
        )

    if db_current != image.heads:
        return Verdict(
            False,
            "DB_BEHIND_IMAGE",
            f"🔴 **DB ยังไม่ถึง head ของ image** — DB อยู่ที่ {', '.join(sorted(db_current))} "
            f"· image ไปได้ถึง {', '.join(sorted(image.heads))}\n"
            "แปลว่า `alembic upgrade head` ยังไม่ได้รันหรือรันแล้วล้ม → ดู `docker logs`",
        )

    return Verdict(
        True,
        "OK",
        f"image · โค้ด · DB ตรงกันทั้งสามฝั่งที่ {', '.join(sorted(image.heads))} "
        f"({len(image.revisions)} revision)",
    )


# --------------------------------------------------------------------------
# ส่วน IO
# --------------------------------------------------------------------------


def _run(cmd: list[str]) -> str:
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(
            f"คำสั่งล้มเหลว: {' '.join(cmd)}\n{result.stderr.strip() or result.stdout.strip()}"
        )
    return result.stdout


def read_repo_side() -> Side:
    alembic = REPO_ROOT / "venv" / "bin" / "alembic"
    binary = str(alembic) if alembic.is_file() else "alembic"
    return Side(
        revisions=parse_revisions(_run([binary, "history"])),
        heads=parse_heads(_run([binary, "heads"])),
    )


def read_container_side(container: str) -> tuple[Side, set[str]]:
    def in_container(*args: str) -> str:
        return _run(["docker", "exec", container, "alembic", *args])

    side = Side(
        revisions=parse_revisions(in_container("history")),
        heads=parse_heads(in_container("heads")),
    )
    return side, parse_heads(in_container("current"))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "container", help="ชื่อคอนเทนเนอร์ app (เช่น posternung-sit-app)"
    )
    parser.add_argument(
        "--wait",
        type=int,
        default=0,
        metavar="SECONDS",
        help="รอให้ `alembic upgrade head` ของ CMD จบก่อนตัดสิน (ใช้หลัง deploy)",
    )
    args = parser.parse_args()

    # traceback ของ Python ใน log ของ deploy อ่านยากและกลบสาเหตุจริง — คำสั่งที่ล้ม
    # ที่นี่มีสาเหตุเดียวที่เกิดจริง คือชี้คอนเทนเนอร์ผิดตัว/คอนเทนเนอร์ยังไม่ขึ้น
    # ซึ่งบอกเป็นประโยคได้ · exit 1 เหมือนกันทุกทาง ด่านไม่ได้อ่อนลง
    try:
        repo = read_repo_side()
        deadline = time.monotonic() + args.wait
        while True:
            image, db_current = read_container_side(args.container)
            verdict = diagnose(repo, image, db_current)
            # รอได้เฉพาะอาการที่ *เวลาแก้ได้จริง* — DB ยังตามไม่ทันเพราะ CMD ยังรันอยู่
            # · อาการเรื่อง image ผิดตัวรอไปก็ไม่หาย รออีกก็เท่าเดิม จึงตอบทันที
            waitable = verdict.code in ("DB_NOT_MIGRATED", "DB_BEHIND_IMAGE")
            if verdict.ok or not waitable or time.monotonic() >= deadline:
                break
            time.sleep(2)
    except RuntimeError as exc:
        print(f"🔴 ตรวจไม่ได้ — ไม่ได้แปลว่าผ่าน\n{exc}", file=sys.stderr)
        return 1

    print(
        f"โค้ด (host)      heads={sorted(repo.heads)}  revisions={len(repo.revisions)}"
    )
    print(
        f"image ({args.container})  heads={sorted(image.heads)}  revisions={len(image.revisions)}"
    )
    print(f"DB               current={sorted(db_current)}")
    print()
    if verdict.ok:
        print(f"✅ {verdict.message}")
        return 0
    print(f"[{verdict.code}] {verdict.message}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
