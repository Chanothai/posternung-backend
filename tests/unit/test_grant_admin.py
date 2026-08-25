"""scripts/grant_admin.py — ADR-0031 D6-a · D6-b · D6-c · D6.1 · INF-35

🔴 **เทส D6-c ต้องรันสองครั้งบน DB เดียวกัน** (`test_second_grant_is_refused_...`)
เทสที่รันครั้งเดียวบน DB สะอาดจะเขียวเสมอไม่ว่าเงื่อนไข "ปฏิเสธถ้ามีแอดมินอยู่แล้ว"
จะมีอยู่จริงหรือไม่ — fixture ที่ตรึงตัวแปรที่เทสตั้งใจจะควบคุม (`test-quality` §6.1)
ADR-0031 เขียนตรงตัวว่า "เทสว่ารันครั้งที่สองโดยไม่มี flag ยืนยันต้องถูกปฏิเสธ
**ไม่ใช่แค่เขียนเงื่อนไขไว้**"
"""

from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPO_ROOT / "scripts" / "grant_admin.py"


def _load_script():
    """โหลด scripts/grant_admin.py เป็นโมดูล (scripts/ ไม่ใช่ package)."""
    spec = importlib.util.spec_from_file_location("grant_admin", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


grant_admin = _load_script()


def _args(
    *,
    email: str,
    audit_log: Path,
    commit: bool = False,
    allow_additional_admin: bool = False,
    granted_by: str = "เจ้าของระบบ",
) -> argparse.Namespace:
    return argparse.Namespace(
        email=email,
        granted_by=granted_by,
        audit_log=str(audit_log),
        commit=commit,
        allow_additional_admin=allow_additional_admin,
    )


async def _make_user(
    session: AsyncSession, email: str, *, is_admin: bool = False
) -> User:
    user = User(email=email, is_verified=True, is_admin=is_admin)
    session.add(user)
    await session.flush()
    return user


async def _is_admin(session: AsyncSession, email: str) -> bool:
    user = await session.scalar(select(User).where(User.email == email))
    assert user is not None
    await session.refresh(user)
    return user.is_admin


async def _user_count(session: AsyncSession) -> int:
    return await session.scalar(select(func.count()).select_from(User))


# ───────────────────── D6-a — dry-run เป็นค่าเริ่มต้น ─────────────────────


async def test_dry_run_is_the_default_and_changes_nothing(
    db_session: AsyncSession, tmp_path: Path
) -> None:
    email = "dryrun@test.example"
    await _make_user(db_session, email)
    audit = tmp_path / "audit.jsonl"

    code = await grant_admin.grant(db_session, _args(email=email, audit_log=audit))

    assert code == 0
    assert await _is_admin(db_session, email) is False, "dry-run ไม่ควรเขียน is_admin"
    assert not audit.exists(), "dry-run ไม่ควรสร้างไฟล์ audit"


async def test_commit_flag_actually_grants(
    db_session: AsyncSession, tmp_path: Path
) -> None:
    email = "commit@test.example"
    await _make_user(db_session, email)
    audit = tmp_path / "audit.jsonl"

    code = await grant_admin.grant(
        db_session, _args(email=email, audit_log=audit, commit=True)
    )

    assert code == 0
    assert await _is_admin(db_session, email) is True


# ───────────────────── D6-b — audit ทุกครั้งที่เขียนจริง ─────────────────────


async def test_audit_line_records_who_when_and_by_whom(
    db_session: AsyncSession, tmp_path: Path
) -> None:
    email = "audited@test.example"
    user = await _make_user(db_session, email)
    audit = tmp_path / "nested" / "audit.jsonl"

    await grant_admin.grant(
        db_session,
        _args(email=email, audit_log=audit, commit=True, granted_by="คนสั่ง A"),
    )

    lines = audit.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    record = json.loads(lines[0])
    assert record["granted_to_email"] == email
    assert record["granted_to_user_id"] == str(user.id)
    assert record["granted_by"] == "คนสั่ง A"
    assert record["granted_at"]  # ISO timestamp — มีจริง ไม่ใช่ค่าว่าง


async def test_audit_file_is_append_only_never_overwritten(
    db_session: AsyncSession, tmp_path: Path
) -> None:
    audit = tmp_path / "audit.jsonl"
    audit.write_text('{"pre-existing": true}\n', encoding="utf-8")

    email = "appended@test.example"
    await _make_user(db_session, email)
    await grant_admin.grant(
        db_session, _args(email=email, audit_log=audit, commit=True)
    )

    lines = audit.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 2, "บรรทัดเดิมต้องยังอยู่ — ไฟล์ audit เขียนทับไม่ได้"
    assert json.loads(lines[0]) == {"pre-existing": True}


async def test_grant_is_abandoned_when_audit_cannot_be_written(
    db_session: AsyncSession, tmp_path: Path
) -> None:
    """เขียน audit ไม่ได้ → ต้องไม่มีการให้สิทธิ์เกิดขึ้นเลย

    การให้สิทธิ์ที่ไม่มีร่องรอยคือสิ่งที่ D6-b ห้ามไว้ — ถ้าเลือกลำดับผิด
    (commit ก่อนเขียน audit) เทสข้อนี้จะแดง
    """
    blocker = tmp_path / "not-a-dir"
    blocker.write_text("ไฟล์ ไม่ใช่โฟลเดอร์", encoding="utf-8")
    audit = blocker / "audit.jsonl"

    email = "auditfail@test.example"
    await _make_user(db_session, email)

    code = await grant_admin.grant(
        db_session, _args(email=email, audit_log=audit, commit=True)
    )

    assert code == 3
    assert await _is_admin(db_session, email) is False


# ───────────────────── D6-c — ปฏิเสธถ้ามีแอดมินอยู่แล้ว ─────────────────────


async def test_second_grant_is_refused_without_the_confirm_flag(
    db_session: AsyncSession, tmp_path: Path
) -> None:
    """🔴 หัวใจของ D6-c — รันสองครั้งบน DB เดียวกัน

    ครั้งแรกต้องผ่าน (ยังไม่มีแอดมิน) ครั้งที่สองต้องถูกปฏิเสธ
    ถ้าเขียนเป็นสองเทสแยกที่ต่างคนต่างเริ่มจาก DB สะอาด ทั้งคู่จะเขียว
    แม้เงื่อนไข D6-c จะถูกถอดออกทั้งก้อน
    """
    audit = tmp_path / "audit.jsonl"
    first, second = "first@test.example", "second@test.example"
    await _make_user(db_session, first)
    await _make_user(db_session, second)

    first_code = await grant_admin.grant(
        db_session, _args(email=first, audit_log=audit, commit=True)
    )
    assert first_code == 0, "ครั้งแรกต้องผ่าน — ยังไม่มีแอดมินในระบบ"
    assert await _is_admin(db_session, first) is True

    second_code = await grant_admin.grant(
        db_session, _args(email=second, audit_log=audit, commit=True)
    )

    assert second_code == 2, "ครั้งที่สองต้องถูกปฏิเสธ (D6-c)"
    assert await _is_admin(db_session, second) is False
    assert (
        len(audit.read_text(encoding="utf-8").strip().splitlines()) == 1
    ), "การให้สิทธิ์ที่ถูกปฏิเสธต้องไม่ลง audit"


async def test_second_grant_succeeds_with_the_explicit_confirm_flag(
    db_session: AsyncSession, tmp_path: Path
) -> None:
    audit = tmp_path / "audit.jsonl"
    first, second = "boss1@test.example", "boss2@test.example"
    await _make_user(db_session, first, is_admin=True)
    await _make_user(db_session, second)

    code = await grant_admin.grant(
        db_session,
        _args(
            email=second,
            audit_log=audit,
            commit=True,
            allow_additional_admin=True,
        ),
    )

    assert code == 0
    assert await _is_admin(db_session, second) is True


async def test_granting_an_existing_admin_again_is_a_no_op(
    db_session: AsyncSession, tmp_path: Path
) -> None:
    audit = tmp_path / "audit.jsonl"
    email = "already@test.example"
    await _make_user(db_session, email, is_admin=True)

    code = await grant_admin.grant(
        db_session, _args(email=email, audit_log=audit, commit=True)
    )

    assert code == 0
    assert not audit.exists(), "ไม่มีการเปลี่ยนสิทธิ์ ⇒ ไม่ควรมีบรรทัด audit"


# ───────────── D6.1 — บัญชีต้องมีอยู่แล้ว ห้ามสร้างให้เอง ─────────────


async def test_unknown_email_is_refused_and_creates_no_user(
    db_session: AsyncSession, tmp_path: Path
) -> None:
    """user ที่ไม่ได้มาจาก Firebase จะไม่มี oauth_identities และล็อกอินไม่ได้ตลอดกาล
    ⇒ สคริปต์ต้องปฏิเสธ ไม่ใช่สร้างแถวใหม่ให้
    """
    audit = tmp_path / "audit.jsonl"
    before = await _user_count(db_session)

    code = await grant_admin.grant(
        db_session,
        _args(email="never-signed-in@test.example", audit_log=audit, commit=True),
    )

    assert code == 1
    assert await _user_count(db_session) == before, "ห้ามสร้าง user ใหม่ให้เอง"
    assert not audit.exists()


# ───────────── argparse — ค่าที่ขาดไม่ได้ต้องขาดไม่ได้จริง ─────────────


@pytest.mark.parametrize(
    "argv",
    [
        pytest.param(["--granted-by", "x", "--audit-log", "a.jsonl"], id="no-email"),
        pytest.param(
            ["--email", "a@b.c", "--audit-log", "a.jsonl"], id="no-granted-by"
        ),
        pytest.param(["--email", "a@b.c", "--granted-by", "x"], id="no-audit-log"),
    ],
)
def test_required_arguments_cannot_be_omitted(argv: list[str]) -> None:
    with pytest.raises(SystemExit):
        grant_admin.build_parser().parse_args(argv)


def test_commit_defaults_to_false_at_the_parser_level(tmp_path: Path) -> None:
    """D6-a ที่ระดับ argparse — ไม่ใส่ --commit ต้องได้ False ไม่ใช่ None/True"""
    args = grant_admin.build_parser().parse_args(
        ["--email", "a@b.c", "--granted-by", "x", "--audit-log", str(tmp_path / "a")]
    )
    assert args.commit is False
    assert args.allow_additional_admin is False
