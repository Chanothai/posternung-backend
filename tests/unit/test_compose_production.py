"""`docker-compose.production.yml` render จริง — INF-44 AC-5 (ADR-0015 A3-D5)

🔴 **ห้ามแตะ `.env.production` จริง** — เทสนี้ render จากสำเนาใน `tmp_path` +
env ปลอมเท่านั้น (ทรงเดียวกับ skill `docker-environments` §"ตรวจซ้ำว่า production
ไม่ inherit") · ถ้าเครื่องเทสไม่มี `docker`/compose plugin หรือ render ไม่ผ่านด้วย
เหตุผลของเครื่อง (ไม่ใช่บั๊กของไฟล์) ให้ `pytest.skip` แทนที่จะทำเทสหลอก
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]

# 🔴 critic H-3 — ต้องเป็นรูปแบบ sha จริง (40 hex) ไม่ใช่ "test-sha" เฉย ๆ เพื่อให้เทส
# `test_image_tag_comes_from_deploy_env_not_env_file` มีค่าที่แยกแยะได้ชัดจากของปลอมอื่น
_FAKE_IMAGE_TAG = "abcdef0123456789abcdef0123456789abcdef01"

_FAKE_ENV_LINES = [
    "POSTGRES_USER=u",
    "POSTGRES_PASSWORD=p",
    "POSTGRES_DB=d",
    "POSTGRES_PORT=5432",
    "IMAGE_REGISTRY=posternung",
    f"IMAGE_TAG={_FAKE_IMAGE_TAG}",
    "FIREBASE_SA_HOST_PATH=/opt/posternung-ops/firebase-sa.json",
    "SCRIPTS_HOST_PATH=/opt/posternung/scripts",
    "ENV_FILE_HOST_PATH=/opt/posternung/.env.production",
    "OPS_HOST_DIR=/opt/posternung-ops",
    "OPS_TOTP_SECRET_PATH=/opt/posternung-ops/totp/ops-totp.secret",
]


def _docker_daemon_reachable() -> bool:
    """🔴 critic M-4 — `shutil.which` เจอ CLI ไม่ได้แปลว่า daemon ตอบ (เช่น Docker
    Desktop ปิดอยู่) · ต้องแยก "ไม่มีเครื่องมือให้ทดสอบ" (skip ถูกต้อง) ออกจาก
    "compose file พังจริง" (ต้อง fail ไม่ใช่ skip)"""
    if shutil.which("docker") is None:
        return False
    try:
        result = subprocess.run(
            ["docker", "version", "--format", "{{.Server.Version}}"],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return result.returncode == 0


@pytest.fixture
def rendered(tmp_path: Path) -> dict:
    if not _docker_daemon_reachable():
        pytest.skip("docker CLI ไม่มี หรือ daemon ไม่ตอบบนเครื่องนี้")

    for name in ("docker-compose.yml", "docker-compose.production.yml"):
        shutil.copy(REPO_ROOT / name, tmp_path / name)
    # `env_file: !override - .env.production` ต้องมีไฟล์อยู่ (เนื้อหาว่างพอ) —
    # ห้ามแตะไฟล์จริงของเครื่อง (ไม่มีอยู่แล้วในเครื่อง dev ปกติ)
    (tmp_path / ".env.production").write_text("", encoding="utf-8")

    fake_env = tmp_path / "fake.env"
    fake_env.write_text("\n".join(_FAKE_ENV_LINES) + "\n", encoding="utf-8")

    result = subprocess.run(
        [
            "docker",
            "compose",
            "-f",
            "docker-compose.yml",
            "-f",
            "docker-compose.production.yml",
            "--env-file",
            str(fake_env),
            "config",
            "--format",
            "json",
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=30,
    )
    # 🔴 critic M-4 — daemon ตอบแล้ว (เช็คไปแล้วข้างบน) ⇒ exit != 0 ที่นี่แปลว่า
    # compose file พังจริง ต้อง fail ไม่ใช่ skip (skip ทุก exit != 0 คือเขียวหลอก)
    assert result.returncode == 0, (
        f"docker compose config ล้ม (exit={result.returncode}) — "
        f"stderr: {result.stderr[:2000]}"
    )
    return json.loads(result.stdout)


def test_every_app_bind_mount_source_is_absolute(rendered: dict) -> None:
    volumes = rendered["services"]["app"]["volumes"]
    for vol in volumes:
        if vol.get("type") == "bind":
            assert vol["source"].startswith("/"), vol


def test_scripts_is_mounted_read_only(rendered: dict) -> None:
    volumes = rendered["services"]["app"]["volumes"]
    scripts_mounts = [v for v in volumes if v.get("target") == "/app/scripts"]
    assert len(scripts_mounts) == 1, volumes
    assert scripts_mounts[0].get("read_only") is True


def test_db_uses_the_named_volume_for_pgdata(rendered: dict) -> None:
    volumes = rendered["services"]["db"]["volumes"]
    named = [v for v in volumes if v.get("type") == "volume"]
    assert any(v.get("source") == "pgdata-production" for v in named), volumes


def test_db_restart_policy_if_present_is_not_the_bare_default(rendered: dict) -> None:
    """ตรวจเฉพาะถ้ามี key — hotfix PR #100 (`fix/production-db-restart-policy`)
    แตะ `docker-compose.yml` db section คนละไฟล์กับใบนี้ ไม่ควรทำให้เทสนี้แดงไม่ว่า
    จะ merge ก่อนหรือหลังใบนี้"""
    restart = rendered["services"]["db"].get("restart")
    if restart is not None:
        assert restart != "no"


def test_app_declares_ops_env_vars(rendered: dict) -> None:
    env = rendered["services"]["app"].get("environment", {})
    assert env.get("OPS_AUDIT_DIR") == "/app/var/ops/audit"
    assert env.get("OPS_BACKUP_DIR") == "/app/var/ops/backups"
    assert env.get("OPS_TOTP_SECRET_PATH") == "/run/secrets/ops-totp"


def test_image_tag_comes_from_deploy_env_not_env_file(rendered: dict) -> None:
    """🔴 critic H-3 — ต้องมาจาก `environment:` (ซึ่งได้ค่าจาก `--env-file`/`export`
    ของ deploy.sh ตอน compose up) ไม่ใช่ค่าที่ค้างอยู่ใน `.env.production` บน host
    (`env_file:` แพ้ `environment:` เสมอ — ถ้า H-3 กลับมา ค่านี้จะหายไปจาก environment
    ของ service แล้วด่าน ⑧ ของ production_gate() จะปฏิเสธทุกครั้งหลัง deploy จริง)"""
    env = rendered["services"]["app"].get("environment", {})
    assert env.get("IMAGE_TAG") == _FAKE_IMAGE_TAG


def test_audit_mount_is_read_write(rendered: dict) -> None:
    volumes = rendered["services"]["app"]["volumes"]
    audit_mounts = [v for v in volumes if v.get("target") == "/app/var/ops/audit"]
    assert len(audit_mounts) == 1, volumes
    assert not audit_mounts[0].get("read_only"), audit_mounts[0]


def test_backups_mount_on_app_is_read_only(rendered: dict) -> None:
    volumes = rendered["services"]["app"]["volumes"]
    backup_mounts = [v for v in volumes if v.get("target") == "/app/var/ops/backups"]
    assert len(backup_mounts) == 1, volumes
    assert backup_mounts[0].get("read_only") is True


def test_env_production_mount_is_read_only(rendered: dict) -> None:
    volumes = rendered["services"]["app"]["volumes"]
    env_mounts = [v for v in volumes if v.get("target") == "/app/.env.production"]
    assert len(env_mounts) == 1, volumes
    assert env_mounts[0].get("read_only") is True


def test_db_backups_mount_is_read_write(rendered: dict) -> None:
    """เจ้าของต้อง `pg_dump` เขียนไฟล์ที่นี่ได้จริง — ro จะทำให้ backup-ref (⑦) สร้างไม่ได้"""
    volumes = rendered["services"]["db"]["volumes"]
    backup_mounts = [v for v in volumes if v.get("target") == "/backups"]
    assert len(backup_mounts) == 1, volumes
    assert not backup_mounts[0].get("read_only"), backup_mounts[0]


def test_app_has_exactly_six_volumes(rendered: dict) -> None:
    """firebase-sa · scripts · .env.production · audit · backups · totp-secret —
    วัดจริงด้วยคำสั่งเดียวกับที่ skill `docker-environments` แนะนำให้ตรวจซ้ำ"""
    volumes = rendered["services"]["app"]["volumes"]
    assert len(volumes) == 6, volumes
    assert sum("scripts" in str(v) for v in volumes) == 1, volumes
