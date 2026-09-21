"""`scripts/_totp.py` — RFC 6238 + กัน replay + mode ไฟล์ secret (INF-44 A3-D3 ②)"""

from __future__ import annotations

import base64
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from scripts import _totp
from scripts.seed._shared import PrecheckError

# RFC 6238 Appendix B — secret ASCII "12345678901234567890" (SHA-1 test vector)
_RFC_SECRET_B32 = base64.b32encode(b"12345678901234567890").decode()


@pytest.mark.parametrize(
    "unix_time, expected",
    [
        (59, "287082"),
        (1111111109, "081804"),
        (1111111111, "050471"),
        (1234567890, "005924"),
        (2000000000, "279037"),
    ],
)
def test_rfc6238_appendix_b_vectors(unix_time: int, expected: str) -> None:
    at = datetime.fromtimestamp(unix_time, tz=timezone.utc)
    assert _totp.totp(_RFC_SECRET_B32, at=at) == expected


def test_totp_is_six_digits_zero_padded() -> None:
    at = datetime.fromtimestamp(0, tz=timezone.utc)
    code = _totp.totp(_RFC_SECRET_B32, at=at)
    assert len(code) == 6
    assert code.isdigit()


# --------------------------------------------------------------------------
# verify() — window ±1 step + กัน replay
# --------------------------------------------------------------------------


def test_verify_accepts_the_current_code(tmp_path: Path) -> None:
    at = datetime.fromtimestamp(1111111109, tz=timezone.utc)
    code = _totp.totp(_RFC_SECRET_B32, at=at)
    _totp.verify(_RFC_SECRET_B32, code, at=at, replay_file=tmp_path / "replay.json")


def test_verify_accepts_one_step_before_and_after(tmp_path: Path) -> None:
    base = 1111111109
    at = datetime.fromtimestamp(base, tz=timezone.utc)
    before_code = _totp.totp(
        _RFC_SECRET_B32, at=datetime.fromtimestamp(base - 30, tz=timezone.utc)
    )
    _totp.verify(
        _RFC_SECRET_B32, before_code, at=at, replay_file=tmp_path / "replay-a.json"
    )

    after_code = _totp.totp(
        _RFC_SECRET_B32, at=datetime.fromtimestamp(base + 30, tz=timezone.utc)
    )
    _totp.verify(
        _RFC_SECRET_B32, after_code, at=at, replay_file=tmp_path / "replay-b.json"
    )


def test_verify_rejects_two_steps_away(tmp_path: Path) -> None:
    base = 1111111109
    at = datetime.fromtimestamp(base, tz=timezone.utc)
    far_code = _totp.totp(
        _RFC_SECRET_B32, at=datetime.fromtimestamp(base + 60, tz=timezone.utc)
    )
    with pytest.raises(PrecheckError, match="ไม่ถูกต้อง"):
        _totp.verify(_RFC_SECRET_B32, far_code, at=at, replay_file=tmp_path / "r.json")


def test_verify_rejects_wrong_code(tmp_path: Path) -> None:
    at = datetime.fromtimestamp(1111111109, tz=timezone.utc)
    with pytest.raises(PrecheckError):
        _totp.verify(_RFC_SECRET_B32, "000000", at=at, replay_file=tmp_path / "r.json")


def test_verify_rejects_a_code_already_used_once(tmp_path: Path) -> None:
    """🔴 กัน replay — code เดิมใช้ซ้ำต้องถูกปฏิเสธแม้ยังอยู่ในหน้าต่างเวลาเดิม"""
    at = datetime.fromtimestamp(1111111109, tz=timezone.utc)
    code = _totp.totp(_RFC_SECRET_B32, at=at)
    replay_file = tmp_path / "replay.json"

    _totp.verify(_RFC_SECRET_B32, code, at=at, replay_file=replay_file)
    with pytest.raises(PrecheckError, match="replay"):
        _totp.verify(_RFC_SECRET_B32, code, at=at, replay_file=replay_file)


def test_verify_rejects_a_code_from_a_step_older_than_the_last_accepted(
    tmp_path: Path,
) -> None:
    """แม้ code จะตรง (คำนวณจากนาฬิกาที่ถอยหลัง) step เก่ากว่าที่เคยรับแล้วต้องถูกปฏิเสธ"""
    replay_file = tmp_path / "replay.json"
    later = datetime.fromtimestamp(1111111109 + 30, tz=timezone.utc)
    later_code = _totp.totp(_RFC_SECRET_B32, at=later)
    _totp.verify(_RFC_SECRET_B32, later_code, at=later, replay_file=replay_file)

    earlier = datetime.fromtimestamp(1111111109, tz=timezone.utc)
    earlier_code = _totp.totp(_RFC_SECRET_B32, at=earlier)
    with pytest.raises(PrecheckError):
        _totp.verify(_RFC_SECRET_B32, earlier_code, at=later, replay_file=replay_file)


def test_replay_file_records_the_accepted_step_not_the_secret_or_code(
    tmp_path: Path,
) -> None:
    """security-baseline §2 — ไฟล์ replay ต้องไม่มี secret/code อ่านออกได้"""
    at = datetime.fromtimestamp(1111111109, tz=timezone.utc)
    code = _totp.totp(_RFC_SECRET_B32, at=at)
    replay_file = tmp_path / "replay.json"
    _totp.verify(_RFC_SECRET_B32, code, at=at, replay_file=replay_file)

    data = json.loads(replay_file.read_text(encoding="utf-8"))
    assert set(data.keys()) == {"step"}
    assert _RFC_SECRET_B32 not in replay_file.read_text(encoding="utf-8")
    assert code not in replay_file.read_text(encoding="utf-8")


# --------------------------------------------------------------------------
# read_secret() — mode ไฟล์
# --------------------------------------------------------------------------


def test_read_secret_rejects_group_readable_file(tmp_path: Path) -> None:
    path = tmp_path / "secret"
    path.write_text(_RFC_SECRET_B32, encoding="utf-8")
    path.chmod(0o640)
    with pytest.raises(PrecheckError, match="permission"):
        _totp.read_secret(path)


def test_read_secret_accepts_0400(tmp_path: Path) -> None:
    path = tmp_path / "secret"
    path.write_text(_RFC_SECRET_B32, encoding="utf-8")
    path.chmod(0o400)
    assert _totp.read_secret(path) == _RFC_SECRET_B32


def test_read_secret_missing_file_is_a_precheck_error(tmp_path: Path) -> None:
    with pytest.raises(PrecheckError, match="ไม่พบไฟล์"):
        _totp.read_secret(tmp_path / "nope")


# --------------------------------------------------------------------------
# enroll() — สร้างครั้งเดียว ห้ามเขียนทับ
# --------------------------------------------------------------------------


def test_enroll_writes_a_0400_file_and_returns_otpauth_uri(tmp_path: Path) -> None:
    path = tmp_path / "totp" / "secret"
    uri = _totp.enroll(path)
    assert uri.startswith("otpauth://totp/PosterNung:ops?secret=")
    assert path.stat().st_mode & 0o777 == 0o400


def test_enroll_refuses_to_overwrite_an_existing_secret(tmp_path: Path) -> None:
    path = tmp_path / "secret"
    _totp.enroll(path)
    with pytest.raises(PrecheckError, match="มีอยู่แล้ว"):
        _totp.enroll(path)
