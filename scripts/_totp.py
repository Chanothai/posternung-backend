"""TOTP (RFC 6238) — 2-Step Verification ของด่าน production (INF-44 · ADR-0015 A3-D3 ②)

🔴 **stdlib เท่านั้น — ห้ามเพิ่ม dependency** (`hmac` · `hashlib` · `struct` · `base64`)
ตาม A3-D3 OD-1 (ทาง ข) — secret แชร์กับ authenticator app บนมือถือของเจ้าของ
(Google Authenticator / Authy ฯลฯ ตัวไหนก็ได้ที่พูด TOTP มาตรฐาน)

## เหตุผลที่เลือก TOTP เหนือ Firebase ID token / one-time code ใน outbox

ดูตาราง §③ ของ `docs/status/gates/INF-44-gate1.md` — สรุปสั้น: ไม่ต้องพึ่ง whitelist
OAuth client ของ Firebase console (งานนอกโค้ดที่ยังไม่ได้ทำ) และ factor อยู่บนมือถือ
แยกจาก laptop/SSH key จริง ๆ (กัน "laptop หลุด" ได้ดีที่สุดในสามทาง)

## กัน replay — จำ step ล่าสุดที่ยอมรับแล้ว

RFC 6238 ให้ code ซ้ำได้ภายในหน้าต่าง 30 วินาทีเดียวกัน (และซ้ำข้ามหน้าต่างได้ถ้าเดา
ถูกจังหวะ) — ถ้าไม่กัน replay คนที่เห็น code เก่า (เช่นจากประวัติ terminal) ใช้ซ้ำได้
`verify()` จึงบันทึก `(step, code)` ล่าสุดที่ **ยอมรับแล้ว** ลงไฟล์ใต้ `OPS_AUDIT_DIR`
· step ที่ ≤ ค่าที่บันทึกไว้แล้ว = ปฏิเสธเสมอ ไม่ว่า code จะตรงหรือไม่

🔴 **ไฟล์ replay เก็บเฉพาะ step ตัวเลข ไม่เก็บ secret และไม่เก็บ code ที่อ่านออกได้ว่า
ยังใช้ได้อยู่กี่วินาที** — ปลอดภัยพอจะอยู่ใต้ `OPS_AUDIT_DIR` (`security-baseline` §2)
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import struct
from datetime import datetime
from pathlib import Path

from scripts.seed._shared import PrecheckError

STEP_SECONDS = 30
DIGITS = 6


def totp(
    secret_b32: str, *, at: datetime, step: int = STEP_SECONDS, digits: int = DIGITS
) -> str:
    """RFC 6238 — HOTP(secret, floor(unix_time / step)) ตัดเหลือ `digits` หลัก."""
    key = base64.b32decode(secret_b32.upper().strip(), casefold=True)
    counter = int(at.timestamp()) // step
    msg = struct.pack(">Q", counter)
    digest = hmac.new(key, msg, hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    truncated = struct.unpack(">I", digest[offset : offset + 4])[0] & 0x7FFFFFFF
    return str(truncated % (10**digits)).zfill(digits)


def _step_of(at: datetime, *, step: int = STEP_SECONDS) -> int:
    return int(at.timestamp()) // step


def _read_last_accepted_step(replay_file: Path) -> int | None:
    try:
        data = json.loads(replay_file.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (OSError, ValueError) as exc:
        raise PrecheckError(
            f"ไฟล์กัน replay ของ TOTP ({replay_file}) อ่านไม่ได้: {exc}"
        ) from exc
    step = data.get("step")
    if not isinstance(step, int):
        raise PrecheckError(
            f"ไฟล์กัน replay ของ TOTP ({replay_file}) รูปแบบผิด — ไม่มีคีย์ step ที่เป็นจำนวนเต็ม"
        )
    return step


def _write_last_accepted_step(replay_file: Path, step: int) -> None:
    try:
        replay_file.parent.mkdir(parents=True, exist_ok=True)
        replay_file.write_text(json.dumps({"step": step}), encoding="utf-8")
    except OSError as exc:
        raise PrecheckError(
            f"เขียนไฟล์กัน replay ของ TOTP ({replay_file}) ไม่ได้: {exc}"
        ) from exc


def verify(
    secret_b32: str,
    code: str,
    *,
    at: datetime,
    window: int = 1,
    replay_file: Path,
) -> None:
    """ยืนยัน `code` เทียบ `secret_b32` ที่เวลา `at` ± `window` step · กัน replay

    ปฏิเสธ (`PrecheckError`) เมื่อ:
      - `code` ไม่ตรงกับ TOTP ที่ step ใดใน [-window, +window]
      - step ที่ตรง (ถ้าเจอ) ≤ step ล่าสุดที่เคยยอมรับแล้ว (replay)

    ยอมรับแล้วต้อง**บันทึก step นั้นทันที** ก่อน return — ไม่งั้น code เดิมใช้ซ้ำได้
    ในโอกาสถัดไปที่ `verify()` ถูกเรียกก่อนไฟล์ replay ถูกเขียน
    """
    current_step = _step_of(at)
    last_accepted = _read_last_accepted_step(replay_file)

    matched_step: int | None = None
    for delta in range(-window, window + 1):
        candidate_step = current_step + delta
        candidate_at = datetime.fromtimestamp(
            candidate_step * STEP_SECONDS, tz=at.tzinfo
        )
        if hmac.compare_digest(totp(secret_b32, at=candidate_at), code):
            matched_step = candidate_step
            break

    if matched_step is None:
        raise PrecheckError("รหัส TOTP ไม่ถูกต้อง (หรือหมดอายุแล้ว — ลองรหัสถัดไป)")

    if last_accepted is not None and matched_step <= last_accepted:
        raise PrecheckError(
            "รหัส TOTP นี้ถูกใช้ไปแล้ว (replay) — รอรหัสถัดไปจากแอป authenticator"
        )

    _write_last_accepted_step(replay_file, matched_step)


def read_secret(path: Path) -> str:
    """อ่าน secret จากไฟล์ — ต้อง mode `0400`/`0600` เท่านั้น (fail-closed)."""
    if not path.is_file():
        raise PrecheckError(
            f"ไม่พบไฟล์ secret ของ TOTP ({path}) — enroll ก่อนด้วย "
            "`scripts/ops_totp.py enroll`"
        )
    mode = path.stat().st_mode & 0o777
    if mode & 0o077:
        raise PrecheckError(
            f"ไฟล์ secret ของ TOTP ({path}) มี permission {oct(mode)} — group/other "
            "อ่านได้ ต้องเป็น 0400 หรือ 0600 เท่านั้น (`chmod 0400 {path}`)"
        )
    return path.read_text(encoding="utf-8").strip()


def enroll(path: Path) -> str:
    """สร้าง secret ใหม่ → เขียนไฟล์ mode `0400` → คืน `otpauth://` URI (พิมพ์ครั้งเดียว)

    🔴 **ปฏิเสธถ้าไฟล์มีอยู่แล้ว** — ห้ามเขียนทับ secret เดิม (จะทำให้ authenticator
    app ที่ enroll ไปแล้วใช้ไม่ได้เงียบ ๆ โดยไม่มีใครรู้จนกว่าจะลองยืนยัน)
    """
    if path.exists():
        raise PrecheckError(
            f"{path} มีอยู่แล้ว — ห้ามเขียนทับ secret เดิม (ลบไฟล์เองก่อนถ้าตั้งใจ enroll ใหม่)"
        )
    secret_bytes = secrets.token_bytes(
        20
    )  # 160 บิต — เท่ากับที่ RFC 6238 แนะนำสำหรับ SHA-1
    secret_b32 = base64.b32encode(secret_bytes).decode("ascii")

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(secret_b32, encoding="utf-8")
    path.chmod(0o400)

    return f"otpauth://totp/PosterNung:ops?secret={secret_b32}&issuer=PosterNung"
