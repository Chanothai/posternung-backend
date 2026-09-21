"""เส้นเขียน production — ที่เดียวที่ `--target production` เปิดได้ (INF-44 · ADR-0015 Amendment 3)

ย่อ A3-D1..D6 (ฉบับเต็มอยู่ที่ `../workspace/docs/adr/ADR-0015-manual-entry-path.md`
§"Amendment 3" — **ห้ามเล่าซ้ำที่นี่เกินกว่าที่จำเป็นให้คนอ่านโค้ดเข้าใจ**):

* **A3-D1** — `TARGETS = ("dev", "sit", "production")` ประกาศ**ที่นี่ที่เดียว**
  · `manual_entry.TARGETS` re-export object เดียวกัน (เทส identity ล็อกไว้)
* **A3-D2** — ชั้น ①/② ของ `assert_target()`/`assert_target_database()` มีความหมายใหม่
  เมื่อ `target == "production"` (ดูที่ไฟล์นั้น ๆ — ที่นี่มีแค่ `assert_environment_matches()`
  ซึ่งเป็นส่วนของชั้น ② ที่ทุก target แชร์กัน)
* **A3-D3** — ด่าน 8 ข้อของ `production_gate()` ด้านล่าง (บังคับทั้ง dry-run และ commit
  เว้นข้อที่ระบุว่า "commit เท่านั้น")
* **A3-D4** — `PRODUCTION_LANES` เป็นรายการปิด — เส้นที่ไม่อยู่ในนี้ถูกปฏิเสธ **ที่นี่**
  ไม่ใช่ `if target == "production"` กระจายอยู่ 7 ไฟล์
* **A3-D5** — วิธีรันบน production จริง (bind-mount 5 จุด) — ดู
  `docker-compose.production.yml` + `scripts/seed/README.md` §production
* **A3-D6** — ด่านทั้ง 8 กัน *ความผิดพลาด/อ้างชื่อผิด/laptop-SSH key หลุด* **ไม่กัน**
  คนที่มี shell + docker บนตัว host เอง (ถือ credential DB อยู่แล้ว) — ทางที่แข็งกว่า
  คือ endpoint ที่มี token (`SCR-15`) ยอมรับสำหรับ Beta ที่มีแอดมินคนเดียว
"""

from __future__ import annotations

import getpass
import hashlib
import os
import socket
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any

from scripts import _totp
from scripts._actor import resolve_admin_actor
from scripts.seed._shared import PrecheckError

if TYPE_CHECKING:
    import argparse

    from sqlalchemy.ext.asyncio import AsyncSession

# A3-D1 — ที่เดียวที่ประกาศ TARGETS ของทุกสคริปต์ operator
TARGETS = ("dev", "sit", "production")

# ใช้เป็นค่า `now=` ของ `production_gate()` เฉพาะที่เรียกจากเส้นที่**ไม่มีวันผ่านด่าน 0**
# (lane ที่ยังไม่อยู่ใน PRODUCTION_LANES) — `production_gate()` raise ที่ด่าน 0 ก่อนแตะ
# `now` เลยเสมอในกรณีนั้น ค่านี้จึงไม่มีวันถูกอ่านจริง · **ไม่ใช่การอ่านนาฬิกา** (literal
# คงที่) เพื่อไม่ให้เส้นที่ยังไม่เปิด production ต้อง thread `now` ผ่าน `run()`/เพิ่มจุด
# อ่านนาฬิกาที่สองในไฟล์ (เทส `test_the_clock_is_read_in_exactly_one_place_...` ของ
# `tests/unit/test_seed_lane_shared_rules.py` ล็อกไว้ว่าแต่ละเส้นอ่านนาฬิกาได้ที่เดียว)
UNREACHABLE_NOW = datetime(1970, 1, 1, tzinfo=timezone.utc)

PRODUCTION_ENV_FILE = ".env.production"

# A3-D4 — รายการปิด: เพิ่มเส้นใหม่ = แก้ ADR-0015 (Amendment ของตัวเอง) + AC ของเส้นนั้น
# ก่อนเพิ่มชื่อเข้ามา ห้ามเพิ่มเงียบ ๆ
PRODUCTION_LANES = frozenset({"manual", "correction"})

# ด่าน ⑦ — pg_dump custom format (`-Fc`) เริ่มไฟล์ด้วย magic bytes นี้เสมอ
_BACKUP_MAGIC = b"PGDMP"
_BACKUP_MAX_AGE = timedelta(minutes=60)

_TOTP_WINDOW_STEPS = 1  # ±1 step ของ 30 วินาที (A3-D3 ②)
_TOTP_REPLAY_FILENAME = "totp-last.json"


def plan_digest(file_bytes: bytes, plans_repr: str) -> str:
    """SHA-256 ของ (ไฟล์ CSV ที่ใช้ + แผนการเขียนที่คำนวณจาก DB state ปัจจุบัน)

    `plans_repr` เป็นสตริง deterministic ที่ lane เป็นคนสร้างเอง (เช่น
    `repr(sorted(...))` ของแผนที่แปลงเป็น tuple ล้วน) — ฟังก์ชันนี้ไม่รู้จักรูปร่าง
    ของแผนของแต่ละเส้นเลย เจตนา: hash ต้องเปลี่ยนทั้งตอนไฟล์เปลี่ยนและตอน DB
    state เปลี่ยนระหว่างรอบ dry-run กับรอบ --commit (A3-D3 ④)
    """
    digest = hashlib.sha256()
    digest.update(file_bytes)
    digest.update(b"\0")
    digest.update(plans_repr.encode("utf-8"))
    return digest.hexdigest()


def assert_environment_matches(target: str, env: dict[str, str] | None = None) -> None:
    """`ENVIRONMENT=production` ⇔ `--target production` — สองทิศ (A3-D2)

    กันสองเคส: (1) รันในคอนเทนเนอร์ production แต่สั่ง `--target sit` เผลอ ๆ
    (2) รัน `--target production` นอกคอนเทนเนอร์ production (เช่นบนเครื่อง dev ที่ดัน
    ตั้ง `ENVIRONMENT=production` ไว้ผิด ๆ — ยืนยันแล้วว่าเป็นบั๊กจริงของ `.env` บางไฟล์
    ตาม ADR-0015 §Firebase project)
    """
    environ = os.environ if env is None else env
    environment = environ.get("ENVIRONMENT", "")
    is_prod_env = environment == "production"
    is_prod_target = target == "production"
    if is_prod_env == is_prod_target:
        return
    if is_prod_target:
        raise PrecheckError(
            "--target production แต่ ENVIRONMENT ในสภาพแวดล้อมนี้ไม่ใช่ 'production' "
            f"(ได้ {environment!r}) — ต้องรันในคอนเทนเนอร์ production เท่านั้น"
        )
    raise PrecheckError(
        f"ENVIRONMENT=production แต่สั่ง --target {target!r} — คอนเทนเนอร์นี้คือ "
        "production ต้องสั่ง --target production เท่านั้น"
    )


def assert_audit_path_is_persistent(path: Path) -> None:
    """`--audit-log` ต้องอยู่ใต้ `OPS_AUDIT_DIR` (bind-mount ถาวร) และเขียนได้จริง (⑥)"""
    audit_dir = os.environ.get("OPS_AUDIT_DIR", "")
    if not audit_dir:
        raise PrecheckError(
            "OPS_AUDIT_DIR ไม่ได้ตั้งในสภาพแวดล้อมนี้ — ไม่รู้ว่า path ถาวรอยู่ที่ไหน "
            "จึงยืนยัน --audit-log ไม่ได้"
        )
    audit_dir_resolved = Path(audit_dir).resolve()
    resolved = path.resolve()
    try:
        resolved.relative_to(audit_dir_resolved)
    except ValueError:
        raise PrecheckError(
            f"--audit-log ({path}) ไม่อยู่ใต้ OPS_AUDIT_DIR ({audit_dir}) — "
            "ไฟล์ที่อยู่นอก bind-mount ถาวรหายได้เมื่อ container ถูกลบ"
        ) from None
    try:
        resolved.parent.mkdir(parents=True, exist_ok=True)
        with resolved.open("a", encoding="utf-8"):
            pass
    except OSError as exc:
        raise PrecheckError(f"เขียน --audit-log ({path}) ไม่ได้: {exc}") from exc


def assert_backup_ref(
    path: Path, *, now: datetime, max_age: timedelta = _BACKUP_MAX_AGE
) -> None:
    """`--backup-ref` ต้องเป็นไฟล์ `pg_dump -Fc` สดใต้ `OPS_BACKUP_DIR` (⑦)"""
    backup_dir = os.environ.get("OPS_BACKUP_DIR", "")
    if not backup_dir:
        raise PrecheckError(
            "OPS_BACKUP_DIR ไม่ได้ตั้งในสภาพแวดล้อมนี้ — ยืนยัน --backup-ref ไม่ได้"
        )
    backup_dir_resolved = Path(backup_dir).resolve()
    resolved = path.resolve()
    try:
        resolved.relative_to(backup_dir_resolved)
    except ValueError:
        raise PrecheckError(
            f"--backup-ref ({path}) ไม่อยู่ใต้ OPS_BACKUP_DIR ({backup_dir})"
        ) from None

    try:
        with resolved.open("rb") as fh:
            header = fh.read(len(_BACKUP_MAGIC))
    except OSError as exc:
        raise PrecheckError(f"อ่าน --backup-ref ({path}) ไม่ได้: {exc}") from exc
    if header != _BACKUP_MAGIC:
        raise PrecheckError(
            f"--backup-ref ({path}) ไม่ใช่ pg_dump custom format (header ไม่ใช่ "
            f"{_BACKUP_MAGIC!r}) — ต้องรันด้วย `pg_dump -Fc`"
        )

    try:
        mtime_ts = resolved.stat().st_mtime
    except OSError as exc:  # pragma: no cover — เพิ่งอ่านไฟล์สำเร็จข้างบน
        raise PrecheckError(
            f"อ่าน mtime ของ --backup-ref ({path}) ไม่ได้: {exc}"
        ) from exc
    mtime = datetime.fromtimestamp(mtime_ts, tz=timezone.utc)
    now_utc = now.astimezone(timezone.utc)
    age = now_utc - mtime
    if age > max_age:
        raise PrecheckError(
            f"--backup-ref ({path}) เก่าเกิน {max_age} (อายุจริง {age}) — pg_dump ใหม่"
            "ก่อนรอบ --commit นี้"
        )


def assert_scripts_match_image() -> str:
    """`scripts/` ที่ mount เข้ามาต้อง sha เดียวกับ image ที่กำลังรันอยู่ (⑧)

    `deploy.sh` เป็นคนเขียน `<checkout>/scripts/.deployed-sha` หลัง `git checkout
    --detach <sha>` สำเร็จ (ด่านฝั่ง host) · ที่นี่เทียบแค่ `.deployed-sha == IMAGE_TAG`
    เพราะในคอนเทนเนอร์ไม่มี `git` ให้เรียก `git rev-parse HEAD` (A3-D3 ⑧)
    """
    image_tag = os.environ.get("IMAGE_TAG", "")
    if not image_tag:
        raise PrecheckError(
            "IMAGE_TAG ไม่ได้ตั้งในสภาพแวดล้อมของคอนเทนเนอร์นี้ — เทียบ sha ของ "
            "scripts/ กับ image ไม่ได้"
        )
    deployed_sha_path = Path(
        os.environ.get("DEPLOYED_SHA_PATH", "/app/scripts/.deployed-sha")
    )
    try:
        deployed_sha = deployed_sha_path.read_text(encoding="utf-8").strip()
    except OSError as exc:
        raise PrecheckError(
            f"อ่าน {deployed_sha_path} ไม่ได้ ({exc}) — deploy.sh ต้องเขียนไฟล์นี้หลัง "
            "checkout สำเร็จก่อน compose up (ADR-0015 A3-D5)"
        ) from exc
    if deployed_sha != image_tag:
        raise PrecheckError(
            "scripts/ ที่ mount เข้ามาไม่ตรง sha กับ image ที่กำลังรัน "
            f"(.deployed-sha={deployed_sha!r} · IMAGE_TAG={image_tag!r}) — กันการรัน "
            "สคริปต์จาก branch อื่นทับ image ที่ deploy จริง"
        )
    return image_tag


def confirm_target_interactively(target: str) -> None:
    """พิมพ์ชื่อ target ซ้ำ — ต้องมี TTY เสมอ **ไม่มี `--yes`** (⑤ · commit เท่านั้น)"""
    if not sys.stdin.isatty():
        raise PrecheckError(
            "ต้องมี TTY เพื่อยืนยัน --commit บน production — ไม่มีโหมด non-interactive "
            "(ไม่มี --yes โดยตั้งใจ)"
        )
    typed = input(f'พิมพ์ "{target}" เพื่อยืนยัน: ')
    if typed != target:
        raise PrecheckError(f'พิมพ์ไม่ตรงกับ "{target}" — ยกเลิก')


def _prompt_totp_code() -> str:
    if not sys.stdin.isatty():
        raise PrecheckError(
            "ต้องมี TTY เพื่อกรอกรหัส TOTP — ไม่รับผ่าน argv/env/stdin-pipe (A3-D3 ②)"
        )
    return getpass.getpass("รหัส TOTP (6 หลักจากแอป authenticator): ").strip()


def _verify_totp(*, now: datetime, audit_dir: Path) -> None:
    secret_path_raw = os.environ.get("OPS_TOTP_SECRET_PATH", "")
    if not secret_path_raw:
        raise PrecheckError("OPS_TOTP_SECRET_PATH ไม่ได้ตั้งในสภาพแวดล้อมนี้")
    secret = _totp.read_secret(Path(secret_path_raw))
    code = _prompt_totp_code()
    replay_file = audit_dir / _TOTP_REPLAY_FILENAME
    _totp.verify(
        secret, code, at=now, window=_TOTP_WINDOW_STEPS, replay_file=replay_file
    )


@dataclass(frozen=True)
class GateResult:
    actor_user_id: Any
    actor_email: str
    image_tag: str


async def production_gate(
    session: "AsyncSession",
    args: "argparse.Namespace",
    *,
    lane: str,
    plans_digest: str,
    now: datetime,
) -> GateResult:
    """ด่าน 8 ข้อของ A3-D3 — เรียงลำดับตาม ADR เป๊ะ ทุกด่านต้องผ่านก่อนเปิด write ใด ๆ

    `args` ต้องมี attribute: `actor`(str) · `commit`(bool) · `allow_overwrite`
    (list ว่าง/ไม่มี) · `plan_hash`(str|None) · `audit_log`(str|None) ·
    `backup_ref`(str|None) — ชื่อเดียวกับ flag ที่แต่ละ lane ประกาศเอง
    """
    # 0 — A3-D4: เส้นที่ยังไม่เปิดถูกปฏิเสธที่นี่ที่เดียว ก่อนด่านอื่นทั้งหมด
    if lane not in PRODUCTION_LANES:
        raise PrecheckError(
            f"เส้น {lane!r} ยังไม่เปิดสำหรับ --target production "
            f"(เปิดแล้ว: {sorted(PRODUCTION_LANES)}) — เพิ่มเข้า PRODUCTION_LANES ใน "
            "scripts/_production_gate.py พร้อม AC ของตัวเองตาม ADR-0015 A3-D4"
        )

    # ① actor ต้องเป็นแอดมิน provider google เท่านั้น
    actor = await resolve_admin_actor(session, args.actor, require_google_only=True)

    # ② TOTP — บังคับทั้ง dry-run และ commit
    audit_dir_raw = os.environ.get("OPS_AUDIT_DIR", "")
    if not audit_dir_raw:
        raise PrecheckError("OPS_AUDIT_DIR ไม่ได้ตั้งในสภาพแวดล้อมนี้")
    _verify_totp(now=now, audit_dir=Path(audit_dir_raw))

    # ③ ไม่รับการเขียนทับฟิลด์ใดบน production
    if getattr(args, "allow_overwrite", None):
        raise PrecheckError("production ไม่รับ --allow-overwrite ฟิลด์ใดเลย (A3-D3 ③)")

    committing = bool(getattr(args, "commit", False))

    if committing:
        # ④ plan-hash ต้องตรงกับผล dry-run รอบล่าสุด
        plan_hash = getattr(args, "plan_hash", None)
        if not plan_hash or plan_hash != plans_digest:
            raise PrecheckError(
                "--plan-hash ไม่ตรงกับผลคำนวณของรอบนี้ (ไฟล์หรือ DB state เปลี่ยนไป "
                "ตั้งแต่ dry-run รอบล่าสุด) — รัน dry-run ใหม่แล้วคัด plan-hash ที่พิมพ์"
                "ออกมา (A3-D3 ④)"
            )
        # ⑤ พิมพ์ชื่อ target ซ้ำ
        confirm_target_interactively("production")

    # ⑥ audit ต้องอยู่ใต้ OPS_AUDIT_DIR และเขียนได้จริง
    audit_log = getattr(args, "audit_log", None)
    if not audit_log:
        raise PrecheckError("production ต้องระบุ --audit-log (A3-D3 ⑥)")
    assert_audit_path_is_persistent(Path(audit_log))

    if committing:
        # ⑦ backup-ref สด — commit เท่านั้น
        backup_ref = getattr(args, "backup_ref", None)
        if not backup_ref:
            raise PrecheckError(
                "--commit บน production ต้องระบุ --backup-ref (A3-D3 ⑦)"
            )
        assert_backup_ref(Path(backup_ref), now=now)

    # ⑧ scripts/ ต้องตรง sha กับ image
    image_tag = assert_scripts_match_image()

    return GateResult(
        actor_user_id=actor.id, actor_email=actor.email, image_tag=image_tag
    )


def audit_record(
    *,
    phase: str,
    lane: str,
    target: str,
    file_name: str,
    file_sha256: str,
    plan_hash: str,
    rows_planned: int,
    rows_written: int,
    actor_user_id: Any,
    reviewed_at: datetime,
    ran_at: datetime,
    backup_ref: str | None,
    image_tag: str | None,
    error: str | None = None,
) -> dict[str, Any]:
    """record ของ audit ถาวร (⑥) — 🔴 ห้ามมี email / URL / ค่าที่เขียน (security-baseline §2)"""
    record: dict[str, Any] = {
        "phase": phase,
        "lane": lane,
        "target": target,
        "file_name": file_name,
        "file_sha256": file_sha256,
        "plan_hash": plan_hash,
        "rows_planned": rows_planned,
        "rows_written": rows_written,
        "actor_user_id": str(actor_user_id),
        "reviewed_at": reviewed_at.isoformat(),
        "ran_at": ran_at.isoformat(),
        "hostname": socket.gethostname(),
        "image_tag": image_tag,
        "backup_ref": backup_ref,
    }
    if error is not None:
        record["error"] = error
    return record
