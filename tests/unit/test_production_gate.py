"""`scripts/_production_gate.py` — ด่าน 8 ข้อของ `--target production` (INF-44 A3-D3)"""

from __future__ import annotations

import argparse
import base64
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import OAuthProvider
from app.models.user import OAuthIdentity, User
from scripts import _production_gate as gate
from scripts import _totp
from scripts.seed._shared import PrecheckError

NOW = datetime(2026, 9, 21, 10, 0, tzinfo=timezone.utc)
_SECRET = base64.b32encode(b"12345678901234567890").decode()


async def _make_admin(
    session: AsyncSession,
    email: str = "owner@example.test",
    *,
    providers: tuple[OAuthProvider, ...] = (OAuthProvider.google,),
) -> User:
    user = User(email=email, is_verified=True, is_admin=True)
    session.add(user)
    await session.flush()
    for provider in providers:
        session.add(
            OAuthIdentity(
                user_id=user.id,
                provider=provider,
                provider_user_id=f"{provider.value}-uid-{user.id}",
                email=email,
            )
        )
    await session.flush()
    return user


def _args(**overrides) -> argparse.Namespace:
    base = dict(
        actor="owner@example.test",
        commit=False,
        allow_overwrite=[],
        plan_hash=None,
        audit_log=None,
        backup_ref=None,
    )
    base.update(overrides)
    return argparse.Namespace(**base)


# --------------------------------------------------------------------------
# 0 — PRODUCTION_LANES (A3-D4)
# --------------------------------------------------------------------------


async def test_lane_not_in_production_lanes_is_rejected_before_touching_db(
    db_session: AsyncSession,
) -> None:
    """ไม่ query actor เลย — เทสนี้ตั้งใจไม่สร้าง user ใด ๆ เพื่อพิสูจน์ข้อนั้น"""
    with pytest.raises(PrecheckError, match="reference"):
        await gate.production_gate(
            db_session, _args(), lane="reference", plans_digest="", now=NOW
        )


def test_production_lanes_is_exactly_manual_and_correction() -> None:
    assert gate.PRODUCTION_LANES == frozenset({"manual", "correction"})


# --------------------------------------------------------------------------
# ① actor google-only
# --------------------------------------------------------------------------


async def test_non_admin_actor_is_rejected(
    db_session: AsyncSession, monkeypatch
) -> None:
    from app.models.user import User as UserModel

    user = UserModel(email="notadmin@example.test", is_verified=True, is_admin=False)
    db_session.add(user)
    await db_session.flush()

    with pytest.raises(PrecheckError):
        await gate.production_gate(
            db_session,
            _args(actor="notadmin@example.test"),
            lane="manual",
            plans_digest="x",
            now=NOW,
        )


async def test_admin_with_non_google_only_provider_is_rejected(
    db_session: AsyncSession,
) -> None:
    await _make_admin(
        db_session,
        "mixed@example.test",
        providers=(OAuthProvider.google, OAuthProvider.password),
    )
    with pytest.raises(PrecheckError):
        await gate.production_gate(
            db_session,
            _args(actor="mixed@example.test"),
            lane="manual",
            plans_digest="x",
            now=NOW,
        )


# --------------------------------------------------------------------------
# ② TOTP — critic รอบ 1 H-1: ก่อนหน้านี้ไม่มีเทสเลยว่า production_gate() บังคับ
# TOTP จริง (ถอด _verify_totp ออกทั้งฟังก์ชัน 330 เทสเดิมยังเขียว 100%)
# --------------------------------------------------------------------------


def test_totp_window_is_exactly_one_step() -> None:
    """🔴 ล็อกค่าคงที่ที่ด่านด้านล่างอ้างอิง — เปลี่ยนตัวเลขนี้ต้องมาแก้เทสคู่กัน"""
    assert gate._TOTP_WINDOW_STEPS == 1


async def test_wrong_totp_code_is_rejected_before_anything_else(
    db_session: AsyncSession, monkeypatch, tmp_path: Path
) -> None:
    """actor ผ่านด่าน ① แล้ว (admin google-only ถูกต้อง) แต่ TOTP ผิด → ต้องหยุดที่นี่
    ก่อนแม้แต่จะเช็ค --allow-overwrite (③) — พิสูจน์ด้วยการตั้ง allow_overwrite ผิด
    กฎไว้ด้วย แล้วยืนยันว่าข้อความ error พูดเรื่อง TOTP ไม่ใช่เรื่อง allow-overwrite"""
    await _make_admin(db_session)
    secret_path = tmp_path / "totp-secret"
    secret_path.write_text(_SECRET, encoding="utf-8")
    secret_path.chmod(0o400)
    monkeypatch.setenv("OPS_TOTP_SECRET_PATH", str(secret_path))
    _setup_audit_dir(monkeypatch, tmp_path)
    monkeypatch.setattr(gate.sys, "stdin", _FakeTTYStdin())
    monkeypatch.setattr(gate.getpass, "getpass", lambda prompt="": "000000")
    monkeypatch.setattr(gate, "_now", lambda: NOW)

    with pytest.raises(PrecheckError, match="ไม่ถูกต้อง"):
        await gate.production_gate(
            db_session,
            _args(allow_overwrite=["title"]),  # ต้องไม่มีวันไปถึงด่านนี้
            lane="manual",
            plans_digest="x",
            now=NOW,
        )


async def test_totp_code_one_step_before_or_after_is_accepted(
    db_session: AsyncSession, monkeypatch, tmp_path: Path
) -> None:
    """code คำนวณจากเวลา -1 step เทียบกับเวลาที่ `_verify_totp` อ่านตอนตรวจ — ต้องผ่าน
    (จำลองนาฬิกามือถือ/เซิร์ฟเวอร์คลาดเคลื่อนกันได้ ±1 step ตาม _TOTP_WINDOW_STEPS)"""
    await _make_admin(db_session)
    verify_at = NOW
    code_at = NOW - timedelta(seconds=30)
    _setup_totp(monkeypatch, tmp_path, at=code_at, verify_at=verify_at)
    audit_dir = _setup_audit_dir(monkeypatch, tmp_path)
    _setup_image_tag(monkeypatch, tmp_path, sha="f" * 40)

    result = await gate.production_gate(
        db_session,
        _args(audit_log=str(audit_dir / "manual.jsonl")),
        lane="manual",
        plans_digest="x",
        now=NOW,
    )
    assert result.actor_email == "owner@example.test"


async def test_totp_code_two_steps_away_is_rejected(
    db_session: AsyncSession, monkeypatch, tmp_path: Path
) -> None:
    """code คำนวณจากเวลา -2 step (60 วินาที) — เกินหน้าต่าง ±1 step ต้องถูกปฏิเสธ
    (ล็อกว่า _TOTP_WINDOW_STEPS == 1 มีผลจริง ไม่ใช่แค่ประกาศไว้เฉย ๆ)"""
    await _make_admin(db_session)
    verify_at = NOW
    code_at = NOW - timedelta(seconds=60)
    _setup_totp(monkeypatch, tmp_path, at=code_at, verify_at=verify_at)
    _setup_audit_dir(monkeypatch, tmp_path)

    with pytest.raises(PrecheckError, match="ไม่ถูกต้อง"):
        await gate.production_gate(
            db_session, _args(), lane="manual", plans_digest="x", now=NOW
        )


async def test_gate_raises_when_totp_verification_raises(
    db_session: AsyncSession, monkeypatch, tmp_path: Path
) -> None:
    """🔴 พิสูจน์ว่า `production_gate()` **เรียก** `_verify_totp()` จริง (ไม่ใช่แค่มี
    ฟังก์ชันอยู่เฉย ๆ โดยไม่มีใครเรียก) — monkeypatch ให้ raise แล้ว gate ต้อง raise
    ตาม ไม่ใช่เดินต่อเงียบ ๆ"""
    await _make_admin(db_session)
    _setup_audit_dir(monkeypatch, tmp_path)

    def _boom(*, audit_dir):
        raise PrecheckError("ปลอม — พิสูจน์ว่า production_gate() เรียกจริง")

    monkeypatch.setattr(gate, "_verify_totp", _boom)

    with pytest.raises(PrecheckError, match="พิสูจน์ว่า production_gate"):
        await gate.production_gate(
            db_session, _args(), lane="manual", plans_digest="x", now=NOW
        )


async def test_totp_replay_is_rejected_through_the_full_gate_not_just_the_primitive(
    db_session: AsyncSession, monkeypatch, tmp_path: Path
) -> None:
    """🔴 H-1 ข้อ 4 — เทสเดิมพิสูจน์ replay แค่ระดับ `_totp.verify()` ตรง ๆ
    (`test_totp.py`) เทสนี้พิสูจน์ว่า **เดินผ่าน `production_gate()` เต็มวงสองรอบ**
    รอบที่สอง (code เดิม เวลาเดิม) ต้องถูกปฏิเสธ ไม่ใช่แค่ primitive เฉย ๆ"""
    await _make_admin(db_session)
    audit_dir = _setup_audit_dir(monkeypatch, tmp_path)
    _setup_totp(monkeypatch, tmp_path, at=NOW, verify_at=NOW)
    _setup_image_tag(monkeypatch, tmp_path, sha="f" * 40)
    args = _args(audit_log=str(audit_dir / "manual.jsonl"))

    first = await gate.production_gate(
        db_session, args, lane="manual", plans_digest="x", now=NOW
    )
    assert first.actor_email == "owner@example.test"

    # รอบสอง — code/เวลาเดิมเป๊ะ ผ่าน _setup_totp เดิม (ไม่เรียกซ้ำ เพราะ getpass/​_now
    # ยัง monkeypatch ค้างอยู่จากรอบแรก) ต้องเจอ replay ที่ audit_dir เดียวกัน
    assert (audit_dir / "totp-last.json").exists()
    with pytest.raises(PrecheckError, match="replay"):
        await gate.production_gate(
            db_session, args, lane="manual", plans_digest="x", now=NOW
        )


# --------------------------------------------------------------------------
# ⑤ confirm_target_interactively — critic รอบ 1 M-3: ไม่มีเทสเชิงลบเลยสักตัว
# --------------------------------------------------------------------------


class _FakeTTYStdinM3:
    def isatty(self) -> bool:
        return True


@pytest.mark.parametrize(
    "typed", ["prod", "Production", "", "PRODUCTION", " production"]
)
def test_confirm_target_rejects_anything_but_an_exact_match(
    monkeypatch, typed: str
) -> None:
    monkeypatch.setattr(gate.sys, "stdin", _FakeTTYStdinM3())
    monkeypatch.setattr("builtins.input", lambda prompt="": typed)
    with pytest.raises(PrecheckError):
        gate.confirm_target_interactively("production")


def test_confirm_target_accepts_the_exact_word(monkeypatch) -> None:
    monkeypatch.setattr(gate.sys, "stdin", _FakeTTYStdinM3())
    monkeypatch.setattr("builtins.input", lambda prompt="": "production")
    gate.confirm_target_interactively("production")  # ไม่ raise


def test_confirm_target_without_a_tty_is_rejected_without_reading_input(
    monkeypatch,
) -> None:
    """ต้องปฏิเสธ**ก่อน**เรียก `input()` เลย — ถ้าไม่มี TTY การเรียก `input()` จะ block
    หรือโยน `EOFError` ซึ่งเป็นคนละ error กับสิ่งที่ด่านนี้ตั้งใจสื่อ"""

    class _NoTTYStdin:
        def isatty(self) -> bool:
            return False

    monkeypatch.setattr(gate.sys, "stdin", _NoTTYStdin())

    def _fail_if_called(prompt: str = "") -> str:
        raise AssertionError("input() ไม่ควรถูกเรียกเลยเมื่อไม่มี TTY")

    monkeypatch.setattr("builtins.input", _fail_if_called)
    with pytest.raises(PrecheckError, match="TTY"):
        gate.confirm_target_interactively("production")


def test_prompt_totp_code_without_a_tty_is_rejected(monkeypatch) -> None:
    class _NoTTYStdin:
        def isatty(self) -> bool:
            return False

    monkeypatch.setattr(gate.sys, "stdin", _NoTTYStdin())

    def _fail_if_called(prompt: str = "") -> str:
        raise AssertionError("getpass() ไม่ควรถูกเรียกเลยเมื่อไม่มี TTY")

    monkeypatch.setattr(gate.getpass, "getpass", _fail_if_called)
    with pytest.raises(PrecheckError, match="TTY"):
        gate._prompt_totp_code()


# --------------------------------------------------------------------------
# ③ --allow-overwrite ห้ามเสมอ
# --------------------------------------------------------------------------


async def test_allow_overwrite_is_always_rejected_on_production(
    db_session: AsyncSession, monkeypatch, tmp_path: Path
) -> None:
    await _make_admin(db_session)
    _setup_totp(monkeypatch, tmp_path)
    _setup_audit_dir(monkeypatch, tmp_path)
    with pytest.raises(PrecheckError, match="allow-overwrite"):
        await gate.production_gate(
            db_session,
            _args(allow_overwrite=["title"]),
            lane="manual",
            plans_digest="x",
            now=NOW,
        )


# --------------------------------------------------------------------------
# helpers ที่ต้องพึ่ง filesystem/env
# --------------------------------------------------------------------------


class _FakeTTYStdin:
    """แทน `sys.stdin` ทั้งตัว — ปลอดภัยกว่าการ monkeypatch attribute ของ stdin จริง
    ที่ pytest capture อาจแทนที่ด้วย object ที่ไม่รองรับการตั้ง attribute เอง"""

    def isatty(self) -> bool:
        return True


def _setup_totp(
    monkeypatch,
    tmp_path: Path,
    *,
    at: datetime = NOW,
    verify_at: datetime | None = None,
) -> str:
    """เตรียม TOTP ให้ผ่าน — `at` = เวลาที่ใช้ *คำนวณ* code (จำลองแอป authenticator) ·
    `verify_at` = เวลาที่ `_verify_totp()` จะ *อ่านนาฬิกาของตัวเอง* ตอนตรวจ (M-2 —
    ค่าเริ่มต้นเท่ากับ `at` คือเคส "พิมพ์ทันที" · ตั้งต่างกันเพื่อจำลอง drift/replay)
    """
    secret_path = tmp_path / "totp-secret"
    secret_path.write_text(_SECRET, encoding="utf-8")
    secret_path.chmod(0o400)
    monkeypatch.setenv("OPS_TOTP_SECRET_PATH", str(secret_path))
    code = _totp.totp(_SECRET, at=at)
    monkeypatch.setattr(gate.sys, "stdin", _FakeTTYStdin())
    monkeypatch.setattr(gate.getpass, "getpass", lambda prompt="": code)
    monkeypatch.setattr(
        gate, "_now", lambda: verify_at if verify_at is not None else at
    )
    return code


def _setup_audit_dir(monkeypatch, tmp_path: Path) -> Path:
    audit_dir = tmp_path / "audit"
    audit_dir.mkdir()
    monkeypatch.setenv("OPS_AUDIT_DIR", str(audit_dir))
    return audit_dir


def _setup_backup_ref(tmp_path: Path, *, mtime: datetime = NOW) -> Path:
    backup_dir = tmp_path / "backups"
    backup_dir.mkdir(exist_ok=True)
    backup_file = backup_dir / "prod.dump"
    backup_file.write_bytes(b"PGDMP" + b"\x00" * 16)
    import os

    ts = mtime.timestamp()
    os.utime(backup_file, (ts, ts))
    return backup_file


def _setup_image_tag(monkeypatch, tmp_path: Path, sha: str = "a" * 40) -> None:
    monkeypatch.setenv("IMAGE_TAG", sha)
    deployed = tmp_path / ".deployed-sha"
    deployed.write_text(sha, encoding="utf-8")
    monkeypatch.setenv("DEPLOYED_SHA_PATH", str(deployed))


# --------------------------------------------------------------------------
# ⑥ audit path
# --------------------------------------------------------------------------


def test_audit_path_outside_ops_audit_dir_is_rejected(
    monkeypatch, tmp_path: Path
) -> None:
    _setup_audit_dir(monkeypatch, tmp_path)
    outside = tmp_path / "elsewhere" / "audit.jsonl"
    with pytest.raises(PrecheckError, match="OPS_AUDIT_DIR"):
        gate.assert_audit_path_is_persistent(outside)


def test_audit_path_without_ops_audit_dir_env_is_rejected(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.delenv("OPS_AUDIT_DIR", raising=False)
    with pytest.raises(PrecheckError, match="OPS_AUDIT_DIR"):
        gate.assert_audit_path_is_persistent(tmp_path / "a.jsonl")


def test_audit_path_inside_ops_audit_dir_is_accepted_and_writable(
    monkeypatch, tmp_path: Path
) -> None:
    audit_dir = _setup_audit_dir(monkeypatch, tmp_path)
    gate.assert_audit_path_is_persistent(audit_dir / "manual.jsonl")


def test_audit_path_check_does_not_create_the_file(monkeypatch, tmp_path: Path) -> None:
    """A4-D6 (INF-48) — gap Low ของ INF-44: dry-run เคยทิ้งไฟล์ `--audit-log` ว่าง
    (0 ไบต์) ไว้เสมอเพราะด่านนี้เปิดไฟล์ด้วย `open("a")` ตรง ๆ · ตอนนี้ต้องผ่านด่าน
    **โดยไม่สร้างไฟล์เลย** — พิสูจน์ทั้งสองทาง: ไม่ throw และ `not path.exists()`"""
    audit_dir = _setup_audit_dir(monkeypatch, tmp_path)
    path = audit_dir / "catalog-bootstrap.jsonl"
    assert not path.exists()

    gate.assert_audit_path_is_persistent(path)

    assert not path.exists(), (
        "assert_audit_path_is_persistent() สร้างไฟล์ทั้งที่ยังไม่มี dry-run "
        "หรือ commit ใดเขียนจริง — mutation ที่คืน open('a') ตรง ๆ ต้องทำให้เทสนี้แดง"
    )


# --------------------------------------------------------------------------
# ⑦ backup-ref
# --------------------------------------------------------------------------


def test_backup_ref_wrong_header_is_rejected(monkeypatch, tmp_path: Path) -> None:
    backup_dir = tmp_path / "backups"
    backup_dir.mkdir()
    monkeypatch.setenv("OPS_BACKUP_DIR", str(backup_dir))
    bad = backup_dir / "bad.dump"
    bad.write_bytes(b"NOTAPGDUMP")
    with pytest.raises(PrecheckError, match="PGDMP"):
        gate.assert_backup_ref(bad, now=NOW)


def test_backup_ref_too_old_is_rejected(monkeypatch, tmp_path: Path) -> None:
    backup_dir = tmp_path / "backups"
    backup_dir.mkdir()
    monkeypatch.setenv("OPS_BACKUP_DIR", str(backup_dir))
    stale = _setup_backup_ref(tmp_path, mtime=NOW - timedelta(minutes=61))
    with pytest.raises(PrecheckError, match="เก่าเกิน"):
        gate.assert_backup_ref(stale, now=NOW)


def test_backup_ref_fresh_pgdmp_is_accepted(monkeypatch, tmp_path: Path) -> None:
    backup_dir = tmp_path / "backups"
    backup_dir.mkdir()
    monkeypatch.setenv("OPS_BACKUP_DIR", str(backup_dir))
    fresh = _setup_backup_ref(tmp_path, mtime=NOW - timedelta(minutes=1))
    gate.assert_backup_ref(fresh, now=NOW)  # ไม่ raise


# --------------------------------------------------------------------------
# ⑦ backup-ref นอก OPS_BACKUP_DIR — ปิด gap 12c ของ INF-44 (screens.yaml · critic รอบ 2 21 ก.ย.)
# โค้ด `relative_to(OPS_BACKUP_DIR)` ปฏิเสธจริงอยู่แล้ว แต่ไม่มีเทสเลย —
# mutation รอบ 2 ถอด `relative_to` แล้วเทสเดิมยังเขียวหมด (ไม่มีเคสไหนแตะ path
# ที่อยู่นอก dir เลย)
# --------------------------------------------------------------------------


def test_backup_ref_outside_ops_backup_dir_is_rejected_even_with_valid_header_and_fresh_mtime(
    monkeypatch, tmp_path: Path
) -> None:
    """ไฟล์ header ถูก (`PGDMP`) และ mtime สด แต่อยู่นอก `OPS_BACKUP_DIR` — ต้องโดนปฏิเสธ
    ที่ด่าน path ไม่ใช่ด่าน header/mtime (ยืนยันว่าคนละสาเหตุกับสองเทสด้านบน)"""
    backup_dir = tmp_path / "backups"
    backup_dir.mkdir()
    monkeypatch.setenv("OPS_BACKUP_DIR", str(backup_dir))

    outside_dir = tmp_path / "elsewhere"
    outside_dir.mkdir()
    outside = outside_dir / "x.dump"
    outside.write_bytes(b"PGDMP" + b"\x00" * 16)
    ts = NOW.timestamp()
    os.utime(outside, (ts, ts))

    with pytest.raises(PrecheckError, match="OPS_BACKUP_DIR"):
        gate.assert_backup_ref(outside, now=NOW)


def test_backup_ref_outside_dir_error_does_not_leak_the_configured_directory_value(
    monkeypatch, tmp_path: Path
) -> None:
    """security-baseline §2 — ข้อความ error ใส่ได้แค่ *ชื่อ* env (`OPS_BACKUP_DIR`)
    ห้ามมีค่าจริงของไดเรกทอรีลับ · `path` เป็นค่าที่ผู้เรียก (`--backup-ref`) พิมพ์เอง
    ไม่ใช่ความลับ ใส่ได้ตามปกติ"""
    backup_dir = tmp_path / "backups" / "secret-ops-location"
    backup_dir.mkdir(parents=True)
    monkeypatch.setenv("OPS_BACKUP_DIR", str(backup_dir))

    outside = tmp_path / "elsewhere" / "x.dump"
    outside.parent.mkdir()
    outside.write_bytes(b"PGDMP" + b"\x00" * 16)
    ts = NOW.timestamp()
    os.utime(outside, (ts, ts))

    with pytest.raises(PrecheckError) as exc_info:
        gate.assert_backup_ref(outside, now=NOW)
    message = str(exc_info.value)
    assert "OPS_BACKUP_DIR" in message
    assert str(backup_dir) not in message
    assert str(backup_dir.resolve()) not in message


def test_backup_ref_dotdot_traversal_outside_ops_backup_dir_is_rejected(
    monkeypatch, tmp_path: Path
) -> None:
    """`OPS_BACKUP_DIR/../x.dump` — ถ้า `.resolve()` ไม่ถูกใช้ `Path.relative_to()`
    เทียบกันแบบ lexical จะ "ผ่าน" เพราะพาร์ตแรกของ path ตรงกับ `OPS_BACKUP_DIR` เฉย ๆ
    โดยไม่สนใจ `..` — เทสนี้พิสูจน์ว่า `.resolve()` ถูกใช้จริงก่อนเทียบ"""
    backup_dir = tmp_path / "backups"
    backup_dir.mkdir()
    monkeypatch.setenv("OPS_BACKUP_DIR", str(backup_dir))

    outside = tmp_path / "x.dump"
    outside.write_bytes(b"PGDMP" + b"\x00" * 16)
    ts = NOW.timestamp()
    os.utime(outside, (ts, ts))

    traversal_path = backup_dir / ".." / "x.dump"
    with pytest.raises(PrecheckError, match="OPS_BACKUP_DIR"):
        gate.assert_backup_ref(traversal_path, now=NOW)


def test_backup_ref_symlink_pointing_outside_ops_backup_dir_is_rejected(
    monkeypatch, tmp_path: Path
) -> None:
    """symlink *ใต้* `OPS_BACKUP_DIR` ที่ชี้ออกไปไฟล์นอก dir — `.resolve()` ต้องตาม
    symlink แล้วเทียบตำแหน่งจริง ไม่ใช่เทียบแค่ตำแหน่งของตัว symlink เอง"""
    backup_dir = tmp_path / "backups"
    backup_dir.mkdir()
    monkeypatch.setenv("OPS_BACKUP_DIR", str(backup_dir))

    real = tmp_path / "elsewhere" / "real.dump"
    real.parent.mkdir()
    real.write_bytes(b"PGDMP" + b"\x00" * 16)
    ts = NOW.timestamp()
    os.utime(real, (ts, ts))

    link = backup_dir / "sneaky.dump"
    link.symlink_to(real)

    with pytest.raises(PrecheckError, match="OPS_BACKUP_DIR"):
        gate.assert_backup_ref(link, now=NOW)


async def test_full_gate_rejects_backup_ref_outside_ops_backup_dir_before_scripts_check(
    db_session: AsyncSession, monkeypatch, tmp_path: Path
) -> None:
    """เส้นเต็มของ `production_gate()`: backup-ref นอก `OPS_BACKUP_DIR` ต้องถูกปฏิเสธที่
    ด่าน ⑦ ก่อนถึงด่าน ⑧ (`assert_scripts_match_image`) — **ไม่ตั้ง `IMAGE_TAG` เลย** เพื่อ
    พิสูจน์ว่าด่าน ⑧ ไม่ถูกเรียกจริง (ถ้า ⑦ เงียบ ๆ ปล่อยผ่าน จะไป raise ที่ ⑧ ด้วยข้อความ
    คนละแบบ — `match="OPS_BACKUP_DIR"` จะจับความต่างนี้ได้)

    🔴 หมายเหตุลำดับ: ด่าน ⑤ (`confirm_target_interactively`) มาก่อนด่าน ⑦ ตามลำดับที่
    ADR-0015 A3-D3 ล็อกไว้ (`production_gate()` เรียก ④→⑤→⑥→⑦→⑧ เป๊ะ) เทสนี้จึงต้อง mock
    `builtins.input` ให้ผ่าน ⑤ ไปก่อน — **ไม่ได้** พิสูจน์ว่า backup-ref ถูกเช็คก่อน confirm
    prompt — ลำดับ ④→⑤→⑥→⑦→⑧ ล็อกโดย ADR-0015 A3-D3 จึงไม่สลับให้ ⑦ มาก่อน confirm
    """
    await _make_admin(db_session)
    _setup_totp(monkeypatch, tmp_path)
    audit_dir = _setup_audit_dir(monkeypatch, tmp_path)
    monkeypatch.setattr("builtins.input", lambda prompt="": "production")
    monkeypatch.delenv("IMAGE_TAG", raising=False)

    backup_dir = tmp_path / "backups"
    backup_dir.mkdir()
    monkeypatch.setenv("OPS_BACKUP_DIR", str(backup_dir))
    outside = tmp_path / "elsewhere" / "x.dump"
    outside.parent.mkdir()
    outside.write_bytes(b"PGDMP" + b"\x00" * 16)
    ts = NOW.timestamp()
    os.utime(outside, (ts, ts))

    with pytest.raises(PrecheckError, match="OPS_BACKUP_DIR"):
        await gate.production_gate(
            db_session,
            _args(
                commit=True,
                plan_hash="digest-xyz",
                audit_log=str(audit_dir / "manual.jsonl"),
                backup_ref=str(outside),
            ),
            lane="manual",
            plans_digest="digest-xyz",
            now=NOW,
        )


# --------------------------------------------------------------------------
# ⑧ scripts ต้องตรง sha กับ image
# --------------------------------------------------------------------------


def test_scripts_sha_mismatch_is_rejected(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("IMAGE_TAG", "a" * 40)
    deployed = tmp_path / ".deployed-sha"
    deployed.write_text("b" * 40, encoding="utf-8")
    monkeypatch.setenv("DEPLOYED_SHA_PATH", str(deployed))
    with pytest.raises(PrecheckError, match="ไม่ตรง sha"):
        gate.assert_scripts_match_image()


def test_scripts_sha_match_is_accepted(monkeypatch, tmp_path: Path) -> None:
    _setup_image_tag(monkeypatch, tmp_path, sha="c" * 40)
    assert gate.assert_scripts_match_image() == "c" * 40


def test_missing_image_tag_env_is_rejected(monkeypatch) -> None:
    monkeypatch.delenv("IMAGE_TAG", raising=False)
    with pytest.raises(PrecheckError, match="IMAGE_TAG"):
        gate.assert_scripts_match_image()


# --------------------------------------------------------------------------
# assert_environment_matches — สองทิศ (A3-D2)
# --------------------------------------------------------------------------


def test_environment_matches_when_both_say_production() -> None:
    gate.assert_environment_matches("production", env={"ENVIRONMENT": "production"})


def test_target_production_outside_production_container_is_rejected() -> None:
    with pytest.raises(PrecheckError):
        gate.assert_environment_matches("production", env={"ENVIRONMENT": "sit"})


def test_production_container_with_target_sit_is_rejected() -> None:
    with pytest.raises(PrecheckError):
        gate.assert_environment_matches("sit", env={"ENVIRONMENT": "production"})


def test_dev_target_outside_any_special_environment_passes() -> None:
    gate.assert_environment_matches("dev", env={"ENVIRONMENT": "sit"})


# --------------------------------------------------------------------------
# plan_digest — deterministic, เปลี่ยนตามอินพุต
# --------------------------------------------------------------------------


def test_plan_digest_is_deterministic() -> None:
    a = gate.plan_digest(b"file-bytes", "plan-repr")
    b = gate.plan_digest(b"file-bytes", "plan-repr")
    assert a == b


def test_plan_digest_changes_when_file_bytes_change() -> None:
    a = gate.plan_digest(b"file-bytes-1", "plan-repr")
    b = gate.plan_digest(b"file-bytes-2", "plan-repr")
    assert a != b


def test_plan_digest_changes_when_plan_repr_changes() -> None:
    a = gate.plan_digest(b"file-bytes", "plan-repr-1")
    b = gate.plan_digest(b"file-bytes", "plan-repr-2")
    assert a != b


# --------------------------------------------------------------------------
# ④/⑤ commit-only: plan-hash + confirm — ผ่าน production_gate() แบบเต็มวง
# --------------------------------------------------------------------------


async def test_commit_without_matching_plan_hash_is_rejected(
    db_session: AsyncSession, monkeypatch, tmp_path: Path
) -> None:
    await _make_admin(db_session)
    _setup_totp(monkeypatch, tmp_path)
    _setup_audit_dir(monkeypatch, tmp_path)
    with pytest.raises(PrecheckError, match="plan-hash"):
        await gate.production_gate(
            db_session,
            _args(
                commit=True,
                plan_hash="wrong",
                audit_log=str(tmp_path / "audit" / "a.jsonl"),
            ),
            lane="manual",
            plans_digest="correct-digest",
            now=NOW,
        )


async def test_full_gate_passes_when_every_step_is_satisfied(
    db_session: AsyncSession, monkeypatch, tmp_path: Path
) -> None:
    actor = await _make_admin(db_session)
    _setup_totp(monkeypatch, tmp_path)
    audit_dir = _setup_audit_dir(monkeypatch, tmp_path)
    backup_dir = tmp_path / "backups"
    backup_dir.mkdir()
    monkeypatch.setenv("OPS_BACKUP_DIR", str(backup_dir))
    backup_ref = _setup_backup_ref(tmp_path, mtime=NOW - timedelta(minutes=1))
    _setup_image_tag(monkeypatch, tmp_path, sha="d" * 40)
    monkeypatch.setattr("builtins.input", lambda prompt="": "production")

    result = await gate.production_gate(
        db_session,
        _args(
            commit=True,
            plan_hash="digest-123",
            audit_log=str(audit_dir / "manual.jsonl"),
            backup_ref=str(backup_ref),
        ),
        lane="manual",
        plans_digest="digest-123",
        now=NOW,
    )
    assert result.actor_user_id == actor.id
    assert result.actor_email == actor.email
    assert result.image_tag == "d" * 40


async def test_dry_run_on_production_does_not_require_plan_hash_or_backup_ref(
    db_session: AsyncSession, monkeypatch, tmp_path: Path
) -> None:
    """A3-D3 — ④⑤⑦ เป็น commit เท่านั้น dry-run ต้องผ่านโดยไม่ต้องมีค่าพวกนี้เลย"""
    await _make_admin(db_session)
    _setup_totp(monkeypatch, tmp_path)
    audit_dir = _setup_audit_dir(monkeypatch, tmp_path)
    _setup_image_tag(monkeypatch, tmp_path, sha="e" * 40)

    result = await gate.production_gate(
        db_session,
        _args(commit=False, audit_log=str(audit_dir / "manual.jsonl")),
        lane="manual",
        plans_digest="whatever",
        now=NOW,
    )
    assert result.image_tag == "e" * 40


# --------------------------------------------------------------------------
# audit_record() — ห้ามมี email/URL/ค่าที่เขียน (security-baseline §2)
# --------------------------------------------------------------------------


def test_audit_record_never_contains_an_email_field() -> None:
    """🔴 closed-world — ชื่อคีย์ต้องไม่มี email เลยสักตัว (กัน field ใหม่ที่ใครเผลอเพิ่ม)"""
    record = gate.audit_record(
        phase="intent",
        lane="manual",
        target="production",
        file_name="manual-entry.csv",
        file_sha256="deadbeef",
        plan_hash="digest",
        rows_planned=1,
        rows_written=0,
        actor_user_id="11111111-1111-1111-1111-111111111111",
        reviewed_at=NOW,
        ran_at=NOW,
        backup_ref=None,
        image_tag=None,
    )
    for key in record:
        assert "email" not in key.lower()


def test_audit_record_values_never_look_like_an_email() -> None:
    record = gate.audit_record(
        phase="committed",
        lane="manual",
        target="production",
        file_name="manual-entry.csv",
        file_sha256="deadbeef",
        plan_hash="digest",
        rows_planned=1,
        rows_written=1,
        actor_user_id="11111111-1111-1111-1111-111111111111",
        reviewed_at=NOW,
        ran_at=NOW,
        backup_ref="/app/var/ops/backups/x.dump",
        image_tag="a" * 40,
    )
    for value in record.values():
        assert "@" not in str(value)
