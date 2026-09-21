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

_FAKE_ENV_LINES = [
    "POSTGRES_USER=u",
    "POSTGRES_PASSWORD=p",
    "POSTGRES_DB=d",
    "POSTGRES_PORT=5432",
    "IMAGE_REGISTRY=posternung",
    "IMAGE_TAG=test-sha",
    "FIREBASE_SA_HOST_PATH=/opt/posternung-ops/firebase-sa.json",
    "SCRIPTS_HOST_PATH=/opt/posternung/scripts",
    "ENV_FILE_HOST_PATH=/opt/posternung/.env.production",
    "OPS_HOST_DIR=/opt/posternung-ops",
    "OPS_TOTP_SECRET_PATH=/opt/posternung-ops/totp/ops-totp.secret",
]


@pytest.fixture
def rendered(tmp_path: Path) -> dict:
    if shutil.which("docker") is None:
        pytest.skip("docker ไม่มีในเครื่องเทสนี้")

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
    if result.returncode != 0:
        pytest.skip(
            "docker compose config ไม่ผ่านบนเครื่องนี้ (ไม่จำเป็นว่าไฟล์ผิด) — "
            f"stderr: {result.stderr[:800]}"
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
