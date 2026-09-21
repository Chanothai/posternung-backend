"""`scripts/_production_gate.py` — ด่าน 8 ข้อของ `--target production` (INF-44 A3-D3)"""

from __future__ import annotations

import argparse
import base64
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


def _setup_totp(monkeypatch, tmp_path: Path, *, at: datetime = NOW) -> str:
    secret_path = tmp_path / "totp-secret"
    secret_path.write_text(_SECRET, encoding="utf-8")
    secret_path.chmod(0o400)
    monkeypatch.setenv("OPS_TOTP_SECRET_PATH", str(secret_path))
    code = _totp.totp(_SECRET, at=at)
    monkeypatch.setattr(gate.sys, "stdin", _FakeTTYStdin())
    monkeypatch.setattr(gate.getpass, "getpass", lambda prompt="": code)
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
