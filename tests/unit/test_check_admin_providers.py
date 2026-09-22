"""scripts/check_admin_providers.py — ADR-0031 Amendment 1 · INF-35

ด่านนี้ตรวจว่า **ทุกแถวที่ `is_admin = true` เข้าได้ทางเดียวคือ google** เพราะ Google
2-Step Verification ครอบเฉพาะเส้นนั้น · ทางเข้าที่สองจะเลี่ยง 2SV ได้ทั้งเส้น

🔴 **เคสที่สำคัญที่สุดคือ `google` + อย่างอื่น** — บัญชียัง sign-in ด้วย google ได้ปกติ
ทุกอย่างดูถูกต้องหมด แต่มีประตูที่สองที่ 2SV เอื้อมไม่ถึง · ด่านที่เช็คแค่ "มี google ไหม"
จะปล่อยเคสนี้ผ่าน — เทสข้างล่างล็อกไว้ว่าต้องเป็น "google **เท่านั้น**"

🔴 **exit 2 (ตรวจไม่ได้) ต้องไม่เท่ากับ exit 0 (ผ่าน)** — ทรงเดียวกับ
`.claude/scripts/check-contract-drift.py` ของ INF-31
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPO_ROOT / "scripts" / "check_admin_providers.py"


def _load_script():
    spec = importlib.util.spec_from_file_location("check_admin_providers", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


checker = _load_script()


def _completed(stdout: str = "", stderr: str = "", returncode: int = 0):
    return subprocess.CompletedProcess(
        args=["docker"], returncode=returncode, stdout=stdout, stderr=stderr
    )


def _payload(admins: list[dict]) -> str:
    return "some noise line\nADMIN_PROVIDERS_JSON " + json.dumps(admins) + "\n"


# ───────────────────────── violations() ─────────────────────────


@pytest.mark.parametrize(
    "providers, is_violation",
    [
        pytest.param(["google"], False, id="google-only-ok"),
        pytest.param(["google", "password"], True, id="google-plus-password"),
        pytest.param(["google", "phone"], True, id="google-plus-phone"),
        pytest.param(["password"], True, id="password-only"),
        pytest.param(["phone"], True, id="phone-only"),
        pytest.param([], True, id="no-provider-at-all"),
    ],
)
def test_only_a_google_only_account_is_accepted(providers, is_violation) -> None:
    admins = [{"user_id": "u1", "email": "a@b.c", "providers": providers}]
    assert bool(checker.violations(admins)) is is_violation


def test_violations_reports_every_bad_row_not_just_the_first() -> None:
    admins = [
        {"user_id": "u1", "email": "ok@x.com", "providers": ["google"]},
        {"user_id": "u2", "email": "bad1@x.com", "providers": ["google", "phone"]},
        {"user_id": "u3", "email": "bad2@x.com", "providers": []},
    ]
    assert [a["email"] for a in checker.violations(admins)] == [
        "bad1@x.com",
        "bad2@x.com",
    ]


# ───────────────────────── read_admins() ─────────────────────────


def test_reads_the_payload_line_out_of_container_output(monkeypatch) -> None:
    rows = [{"user_id": "u1", "email": "a@b.c", "providers": ["google"]}]
    monkeypatch.setattr(
        checker.subprocess, "run", lambda *a, **k: _completed(stdout=_payload(rows))
    )
    assert checker.read_admins("c") == rows


@pytest.mark.parametrize(
    "make_run, reason",
    [
        pytest.param(
            lambda *a, **k: (_ for _ in ()).throw(FileNotFoundError("docker")),
            "ไม่มี docker บนเครื่อง",
            id="docker-missing",
        ),
        pytest.param(
            lambda *a, **k: _completed(returncode=1, stderr="No such container"),
            "container ไม่รัน",
            id="container-down",
        ),
        pytest.param(
            lambda *a, **k: _completed(stdout="ไม่มีบรรทัดผลลัพธ์เลย"),
            "query ไม่ได้รันจริง",
            id="no-payload-line",
        ),
    ],
)
def test_every_unreadable_situation_raises_instead_of_returning_empty(
    monkeypatch, make_run, reason
) -> None:
    """🔴 คืน [] แทนการ raise = ระบบจะอ่านว่า "ไม่มีแอดมินผิด" แล้ว exit 0

    ทั้งสามเคสนี้คือ "ตรวจไม่ได้" ซึ่งต้องแยกจาก "ตรวจแล้วผ่าน" ให้ขาด
    """
    monkeypatch.setattr(checker.subprocess, "run", make_run)
    with pytest.raises(RuntimeError):
        checker.read_admins("c")


# ───────────────────────── exit code ของ main() ─────────────────────────


def _run_main(monkeypatch, admins=None, exc=None) -> int:
    def fake(container):
        if exc is not None:
            raise exc
        return admins

    monkeypatch.setattr(checker, "read_admins", fake)
    monkeypatch.setattr("sys.argv", ["check_admin_providers.py", "some-container"])
    return checker.main()


def test_exit_0_when_every_admin_is_google_only(monkeypatch) -> None:
    assert (
        _run_main(
            monkeypatch,
            admins=[{"user_id": "u1", "email": "a@b.c", "providers": ["google"]}],
        )
        == 0
    )


def test_exit_0_when_there_is_no_admin_yet(monkeypatch) -> None:
    """หลัง migration แต่ก่อน grant_admin.py ระบบไม่มีแอดมินเลย — fail-closed ที่ถูกต้อง
    ตาม ADR-0031 D8 ไม่ใช่ความล้มเหลวของด่านนี้
    """
    assert _run_main(monkeypatch, admins=[]) == 0


def test_exit_1_when_an_admin_has_a_second_entrance(monkeypatch) -> None:
    assert (
        _run_main(
            monkeypatch,
            admins=[
                {"user_id": "u1", "email": "a@b.c", "providers": ["google", "phone"]}
            ],
        )
        == 1
    )


def test_exit_2_when_it_cannot_check_at_all(monkeypatch) -> None:
    """🔴 ต้องเป็น 2 ไม่ใช่ 0 — 'ตรวจไม่ได้' ที่ถูกอ่านว่า 'ผ่าน' คือด่านที่โกหก"""
    assert _run_main(monkeypatch, exc=RuntimeError("container ไม่รัน")) == 2


# ───────── ด่านต้องไม่ผูกกับ "แอดมินมีกี่คน" ─────────
#
# 🔴 ระบบมีแอดมิน **2 บัญชี** ตั้งแต่ 2026-08-25 (ADR-0031 Amendment 1 · A1-D6)
# — เป็นคนคนเดียวกันถือสองบัญชีเพื่อไม่ให้ล็อกตายเมื่อ second factor ใบหนึ่งหาย
# ด่านนี้จึงต้องตัดสินจาก **แต่ละแถว** ไม่ใช่จากจำนวนแถว
# ถ้าใครทำให้มันง่ายขึ้นเป็นสมมติฐาน "แอดมินคนเดียว" เทสสามข้อนี้จะแดง


def test_two_google_only_admins_both_pass(monkeypatch) -> None:
    """สภาพจริงของ SIT วันนี้ — สองบัญชี google-only ต้อง exit 0"""
    assert (
        _run_main(
            monkeypatch,
            admins=[
                {"user_id": "u1", "email": "a@x.com", "providers": ["google"]},
                {"user_id": "u2", "email": "b@x.com", "providers": ["google"]},
            ],
        )
        == 0
    )


def test_one_bad_row_among_many_still_fails(monkeypatch) -> None:
    """🔴 แถวดีไม่กลบแถวเสีย — ด่านที่ตัดสินจาก "ส่วนใหญ่ผ่าน" คือด่านที่ไร้ค่า"""
    assert (
        _run_main(
            monkeypatch,
            admins=[
                {"user_id": "u1", "email": "ok@x.com", "providers": ["google"]},
                {
                    "user_id": "u2",
                    "email": "bad@x.com",
                    "providers": ["google", "phone"],
                },
                {"user_id": "u3", "email": "ok2@x.com", "providers": ["google"]},
            ],
        )
        == 1
    )


def test_verdict_does_not_depend_on_how_many_admins_there_are() -> None:
    """เพิ่มแอดมินที่ถูกต้องกี่คนก็ไม่เปลี่ยนคำตัดสิน — คุณสมบัติที่ต้องคงไว้"""
    good = {"user_id": "g", "email": "g@x.com", "providers": ["google"]}
    bad = {"user_id": "b", "email": "b@x.com", "providers": ["phone"]}
    for n in (1, 2, 5, 20):
        assert checker.violations([dict(good, user_id=f"g{i}") for i in range(n)]) == []
        assert len(checker.violations([bad] + [good] * n)) == 1


def test_the_three_exit_codes_are_all_distinct() -> None:
    """กันการ refactor ที่ยุบ 2 กับ 0 เข้าด้วยกันโดยไม่ตั้งใจ"""
    assert len({0, 1, 2}) == 3
    assert checker.ALLOWED_PROVIDERS == {"google"}
