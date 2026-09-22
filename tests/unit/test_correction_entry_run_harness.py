"""harness ระดับ `run()` ของเส้นที่ 5 — INF-29 (ADR-0027)

🔴 **ทำไมไฟล์นี้ต้องมี** — เหตุผลเดียวกับ `test_manual_entry_run_harness.py` (INF-30):
`test_correction_entry.py` มีเทสหลายร้อยตัวที่ยิงที่ `plan_writes()`/`audit_entries()`
ซึ่งเป็น pure ⇒ พิสูจน์ได้แค่ว่า *ตรรกะของด่านถูก* ไม่ได้พิสูจน์ว่า **ด่านถูกต่อเข้าสาย
จริง** — โดยเฉพาะ cascade ของ ADR-0027 D6 (มุตทีชัน 2/4/5) และด่าน sold (มุตทีชัน 3)
ซึ่งทั้งคู่ต้องรู้สถานะ DB สด ๆ (`_load_state()`) และต้องพิสูจน์ผ่านธุรกรรมจริง

## สิ่งที่ไฟล์นี้ทำ และไม่ทำ

- ✅ เรียก **`run()` ตัวจริง** ด้วยไฟล์ CSV จริงใน `tmp_path` และ `db_session` จริง
- ✅ assert ที่ **ผลลัพธ์ใน DB** (`verified_at`/`published_at`/`condition_grade` ·
  แถว `poster_attribute_reviews`) ไม่ใช่ที่ข้อความรายงาน
- ✅ `count_actual` อ่านจาก **ไฟล์ manual-entry.csv จริง** ใน `tmp_path` ผ่าน
  `manual_entry.load_count_actual_by_poster()` ตัวจริง (แทนเฉพาะ `mod.DEFAULT_MANUAL_CSV`
  ให้ชี้มาที่ไฟล์ทดสอบ — ไม่ mock ตัวฟังก์ชันเอง) เพื่อพิสูจน์เส้นทางอ่านข้ามไฟล์จริง
- ❌ **ไม่แตะตรรกะของเส้นที่ 5 แม้บรรทัดเดียว** — `scripts/seed/correction_entry.py`
  ต้องไม่ปรากฏใน `git diff --stat` ของงานที่แก้ไฟล์นี้ทีหลัง

⚠️ **ข้อจำกัดที่ต้องรู้** — harness ประกอบ `argparse.Namespace` เอง จึงไม่ครอบชั้น
argparse ของ `main()` (ทรงเดียวกับ INF-30 §G1 ที่เปิดไว้เป็น gap แยก)
"""

from __future__ import annotations

import argparse
import base64
import csv
import re
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import (
    OAuthProvider,
    PosterCondition,
    PosterImageKind,
    PosterStatus,
)
from app.models.poster import Poster, PosterImage
from app.models.poster_attribute_review import PosterAttributeReview
from app.models.user import OAuthIdentity, User
from scripts import _production_gate as gate
from scripts import _totp
from scripts.seed._shared import PrecheckError
from tests.support import HOUSE_APPROVED_AT, HOUSE_SELLER_ID
from scripts.seed import correction_entry as mod
from scripts.seed.correction_entry import CORRECTION_SHEET_COLUMNS, main, run
from scripts.seed.manual_entry import MANUAL_SHEET_COLUMNS

REVIEWED_AT = datetime(2026, 8, 16, 9, 0, tzinfo=UTC)
REVIEWED_BY = "chanothai.d"
# เวลาที่ "คนตรวจใบจริงแล้วเซ็นรับ/ถอน" รอบก่อนหน้า — ค่าคงที่ ไม่ใช่ now()
PAST_SIGNED_AT = datetime(2026, 8, 10, 10, 0, tzinfo=UTC)


class _SessionHandle:
    """ตัวแทน `async_session_maker()` ที่คืน **session ของเทส** แทนการเปิดใหม่

    🔴 นี่คือ **จุดเดียว** ที่ harness แทนของจริง — ทุกอย่างที่เหลือใน `run()` เป็น
    ของจริงทั้งหมด รวม `_check_schema()` · `_load_state()` ·
    `assert_no_row_targets_a_sold_poster()` · `assert_signable()` · `plan_writes()`
    · `session.commit()` (savepoint ตาม `join_transaction_mode` ของ fixture)
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def __aenter__(self) -> AsyncSession:
        return self._session

    async def __aexit__(self, *exc: object) -> bool:
        return False


@pytest.fixture
def use_test_session(monkeypatch: pytest.MonkeyPatch, db_session: AsyncSession) -> None:
    import app.core.database as db_mod

    monkeypatch.setattr(
        db_mod, "async_session_maker", lambda: _SessionHandle(db_session)
    )


def _sheet(tmp_path: Path, rows: list[dict[str, Any]]) -> Path:
    path = tmp_path / "correction-entry.csv"
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(CORRECTION_SHEET_COLUMNS))
        writer.writeheader()
        for row in rows:
            writer.writerow({col: row.get(col, "") for col in CORRECTION_SHEET_COLUMNS})
    return path


def _manual_csv(tmp_path: Path, counts: dict[uuid.UUID, str]) -> Path:
    """ไฟล์ `manual-entry.csv` จริง — ด่านก่อนเซ็น (D3) อ่าน `count_actual` จากที่นี่
    ผ่าน `manual_entry.load_count_actual_by_poster()` ตัวจริง (ไม่ mock)"""
    path = tmp_path / "manual-entry.csv"
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(MANUAL_SHEET_COLUMNS))
        writer.writeheader()
        for poster_id, count_actual in counts.items():
            row = {col: "" for col in MANUAL_SHEET_COLUMNS}
            row["poster_uuid"] = str(poster_id)
            row["count_actual"] = count_actual
            writer.writerow(row)
    return path


@pytest.fixture
def use_test_manual_csv(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """ปริยาย = ไฟล์ manual-entry.csv ว่างเปล่า (ไม่มีแถวของใครเลย) — เทสที่ต้องการ
    ผลนับจริงเรียก `_manual_csv()` เองแล้วตั้งค่านี้ทับ"""
    default_path = _manual_csv(tmp_path, {})
    monkeypatch.setattr(mod, "DEFAULT_MANUAL_CSV", default_path)

    def set_counts(counts: dict[uuid.UUID, str]) -> None:
        monkeypatch.setattr(mod, "DEFAULT_MANUAL_CSV", _manual_csv(tmp_path, counts))

    return set_counts


def _args(
    path: Path, *, commit: bool, field: list[str] | None = None, **overrides: Any
) -> argparse.Namespace:
    base = dict(
        file=path,
        field=field or [],
        commit=commit,
        reviewed_by=REVIEWED_BY,
        reviewed_at=REVIEWED_AT,
        target="dev",
        actor=None,
        plan_hash=None,
        audit_log=None,
        backup_ref=None,
    )
    base.update(overrides)
    return argparse.Namespace(**base)


async def _make_poster(
    session: AsyncSession,
    *,
    condition_grade: PosterCondition | None = PosterCondition.very_good,
    is_unique: bool = True,
    verified_at: datetime | None = None,
    published_at: datetime | None = None,
    status: PosterStatus = PosterStatus.available,
    image_kind: PosterImageKind | None = PosterImageKind.FRONT,
) -> Poster:
    # ck_posters_sold_requires_sold_at (ADR-0025 D2) — ใบที่ sold ต้องมี sold_at เสมอ
    sold_at = PAST_SIGNED_AT if status is PosterStatus.sold else None
    poster = Poster(
        seller_id=HOUSE_SELLER_ID,
        approved_at=HOUSE_APPROVED_AT,
        title=f"Harness {uuid.uuid4()}",
        price=Decimal("500"),
        condition_grade=condition_grade,
        is_unique=is_unique,
        verified_at=verified_at,
        published_at=published_at,
        status=status,
        sold_at=sold_at,
    )
    session.add(poster)
    await session.flush()
    if image_kind is not None:
        band = {
            PosterImageKind.FRONT: 0,
            PosterImageKind.BACK: 100,
            PosterImageKind.DEFECT: 200,
        }[image_kind]
        session.add(
            PosterImage(
                poster_id=poster.id,
                storage_key=f"posters/public/{poster.id}/{band:02d}-{image_kind.value.lower()}.jpg",
                kind=image_kind,
                sort_order=band,
                is_primary=image_kind is PosterImageKind.FRONT,
            )
        )
        await session.flush()
    return poster


def _row(poster: Poster, **over: str) -> dict[str, str]:
    row: dict[str, str] = {"poster_uuid": str(poster.id)}
    row.update(over)
    return row


async def _refresh(session: AsyncSession, poster_id: uuid.UUID) -> Poster:
    return await session.get(Poster, poster_id)


async def _audit_fields(session: AsyncSession, poster_id: uuid.UUID) -> list[str]:
    rows = await session.execute(
        select(PosterAttributeReview.field).where(
            PosterAttributeReview.poster_id == poster_id
        )
    )
    return sorted(rows.scalars().all())


# --------------------------------------------------------------------------
# ทางที่สำเร็จ — SIGN / WITHDRAW เดี่ยว ๆ (ตัวหลักที่ฆ่า mutation "ตัด plan_writes")
# --------------------------------------------------------------------------


async def test_commit_signs_a_poster_and_records_the_audit_row(
    db_session: AsyncSession,
    tmp_path: Path,
    use_test_session: None,
    use_test_manual_csv,
) -> None:
    """🔴 positive control ของทั้งไฟล์ — ถ้าไม่มีตัวนี้ ชุดข้างล่างเขียวได้ด้วย
    `run()` ที่ปฏิเสธทุกกรณี"""
    poster = await _make_poster(db_session, verified_at=None)
    use_test_manual_csv({poster.id: "1"})
    path = _sheet(
        tmp_path,
        [_row(poster, verified_at="SIGN", verified_at_reason="ตรวจครบทุกมิติแล้ว")],
    )

    rc = await run(_args(path, commit=True), "test", now=REVIEWED_AT)

    assert rc == 0
    refreshed = await _refresh(db_session, poster.id)
    assert refreshed.verified_at == REVIEWED_AT
    assert await _audit_fields(db_session, poster.id) == ["verified_at"]


async def test_dry_run_touches_nothing_in_the_database(
    db_session: AsyncSession,
    tmp_path: Path,
    use_test_session: None,
    use_test_manual_csv,
) -> None:
    poster = await _make_poster(db_session, verified_at=None)
    use_test_manual_csv({poster.id: "1"})
    path = _sheet(
        tmp_path,
        [_row(poster, verified_at="SIGN", verified_at_reason="ตรวจครบทุกมิติแล้ว")],
    )

    rc = await run(_args(path, commit=False), "test", now=REVIEWED_AT)

    assert rc == 0
    refreshed = await _refresh(db_session, poster.id)
    assert refreshed.verified_at is None
    assert await _audit_fields(db_session, poster.id) == []


async def test_commit_withdraws_a_published_poster(
    db_session: AsyncSession,
    tmp_path: Path,
    use_test_session: None,
    use_test_manual_csv,
) -> None:
    poster = await _make_poster(
        db_session, verified_at=PAST_SIGNED_AT, published_at=PAST_SIGNED_AT
    )
    use_test_manual_csv({})
    path = _sheet(
        tmp_path,
        [_row(poster, published_at="WITHDRAW", published_at_reason="พบว่าข้อมูลผิด")],
    )

    rc = await run(_args(path, commit=True), "test", now=REVIEWED_AT)

    assert rc == 0
    refreshed = await _refresh(db_session, poster.id)
    assert refreshed.published_at is None
    # ADR-0027 D6 ไม่มีการเขียน condition_grade/is_unique ในรอบนี้ → cascade ไม่ทำงาน
    # → verified_at ยังอยู่เหมือนเดิม (WITHDRAW ไม่แตะ verified_at เลย)
    assert refreshed.verified_at == PAST_SIGNED_AT
    assert await _audit_fields(db_session, poster.id) == ["published_at"]


# --------------------------------------------------------------------------
# มุตทีชัน 2/4/5 — นโยบายความสด (D6) เดินครบวงจาก CSV → run() → DB
# --------------------------------------------------------------------------


async def test_editing_the_grade_clears_signature_and_publication_in_one_commit(
    db_session: AsyncSession,
    tmp_path: Path,
    use_test_session: None,
    use_test_manual_csv,
) -> None:
    """🔴 มุตทีชัน 2 — ถอด cascade ออกทั้งก้อนต้องทำให้เทสนี้แดง"""
    poster = await _make_poster(
        db_session, verified_at=PAST_SIGNED_AT, published_at=PAST_SIGNED_AT
    )
    use_test_manual_csv({})
    path = _sheet(
        tmp_path,
        [_row(poster, condition_grade="fine", condition_grade_reason="ตรวจซ้ำพบตำหนิ")],
    )

    rc = await run(_args(path, commit=True), "test", now=REVIEWED_AT)

    assert rc == 0
    refreshed = await _refresh(db_session, poster.id)
    assert refreshed.condition_grade is PosterCondition.fine
    assert refreshed.verified_at is None
    assert refreshed.published_at is None
    assert await _audit_fields(db_session, poster.id) == [
        "condition_grade",
        "published_at",
        "verified_at",
    ]


async def test_the_cascade_still_clears_when_field_flag_narrows_to_grade_only(
    db_session: AsyncSession,
    tmp_path: Path,
    use_test_session: None,
    use_test_manual_csv,
) -> None:
    """🔴 มุตทีชัน 4 — `--field condition_grade` ต้องไม่กลายเป็นทางเลี่ยง D6"""
    poster = await _make_poster(
        db_session, verified_at=PAST_SIGNED_AT, published_at=PAST_SIGNED_AT
    )
    use_test_manual_csv({})
    path = _sheet(
        tmp_path,
        [_row(poster, condition_grade="fine", condition_grade_reason="ตรวจซ้ำพบตำหนิ")],
    )

    rc = await run(
        _args(path, commit=True, field=["condition_grade"]), "test", now=REVIEWED_AT
    )

    assert rc == 0
    refreshed = await _refresh(db_session, poster.id)
    assert refreshed.condition_grade is PosterCondition.fine
    assert refreshed.verified_at is None
    assert refreshed.published_at is None


async def test_sign_wins_over_the_cascade_in_the_same_row(
    db_session: AsyncSession,
    tmp_path: Path,
    use_test_session: None,
    use_test_manual_csv,
) -> None:
    """🔴 มุตทีชัน 5 — สลับลำดับ cascade กับ SIGN ต้องทำให้แถวจบด้วย verified_at
    ไม่เป็น NULL"""
    poster = await _make_poster(
        db_session,
        condition_grade=PosterCondition.very_good,  # ต้องมีเกรดเดิมที่ "fine" ต่างจากนี้
        verified_at=PAST_SIGNED_AT,  # เคยเซ็นมาแล้ว — cascade ต้องพยายามล้างค่านี้
        published_at=None,
    )
    use_test_manual_csv({poster.id: "1"})
    path = _sheet(
        tmp_path,
        [
            _row(
                poster,
                condition_grade="fine",
                condition_grade_reason="ตรวจซ้ำพบตำหนิ",
                verified_at="SIGN",
                verified_at_reason="ตรวจครบทุกมิติแล้วหลังแก้เกรด",
            )
        ],
    )

    rc = await run(_args(path, commit=True), "test", now=REVIEWED_AT)

    assert rc == 0
    refreshed = await _refresh(db_session, poster.id)
    assert refreshed.condition_grade is PosterCondition.fine
    assert refreshed.verified_at == REVIEWED_AT  # ไม่ใช่ NULL — SIGN ทับ cascade
    fields = await _audit_fields(db_session, poster.id)
    assert fields == ["condition_grade", "verified_at"]


# --------------------------------------------------------------------------
# มุตทีชัน 3 — ด่าน sold (ADR-0027 A-D11) เดินครบวงจาก CSV → run() → DB
# --------------------------------------------------------------------------


async def test_a_row_touching_a_sold_poster_blocks_the_whole_file(
    db_session: AsyncSession,
    tmp_path: Path,
    use_test_session: None,
    use_test_manual_csv,
) -> None:
    """🔴 มุตทีชัน 3 — แถวที่ถูกต้องในไฟล์เดียวกันต้องไม่ถูกเขียนเลย (fail-closed)"""
    good = await _make_poster(db_session, verified_at=None)
    sold = await _make_poster(db_session, status=PosterStatus.sold)
    use_test_manual_csv({good.id: "1"})
    path = _sheet(
        tmp_path,
        [
            _row(good, verified_at="SIGN", verified_at_reason="ตรวจครบทุกมิติแล้ว"),
            _row(
                sold,
                condition_grade="fine",
                condition_grade_reason="ตรวจซ้ำพบตำหนิ",
            ),
        ],
    )

    from scripts.seed.correction_entry import PrecheckError

    with pytest.raises(PrecheckError, match="A-D11"):
        await run(_args(path, commit=True), "test", now=REVIEWED_AT)

    refreshed_good = await _refresh(db_session, good.id)
    refreshed_sold = await _refresh(db_session, sold.id)
    assert refreshed_good.verified_at is None
    assert refreshed_sold.condition_grade is not PosterCondition.fine
    assert await _audit_fields(db_session, good.id) == []
    assert await _audit_fields(db_session, sold.id) == []


async def test_withdrawing_a_sold_poster_is_blocked_too(
    db_session: AsyncSession,
    tmp_path: Path,
    use_test_session: None,
    use_test_manual_csv,
) -> None:
    poster = await _make_poster(
        db_session, status=PosterStatus.sold, published_at=PAST_SIGNED_AT
    )
    use_test_manual_csv({})
    path = _sheet(
        tmp_path,
        [_row(poster, published_at="WITHDRAW", published_at_reason="พบว่าข้อมูลผิด")],
    )

    from scripts.seed.correction_entry import PrecheckError

    with pytest.raises(PrecheckError, match="A-D11"):
        await run(_args(path, commit=True), "test", now=REVIEWED_AT)

    refreshed = await _refresh(db_session, poster.id)
    assert refreshed.published_at == PAST_SIGNED_AT


# --------------------------------------------------------------------------
# ด่านก่อนเซ็น (ADR-0027 D3) เดินครบวงจาก CSV → run() → DB — รวมการอ่าน
# manual-entry.csv จริง (ไม่ mock ฟังก์ชัน)
# --------------------------------------------------------------------------


async def test_signing_without_a_front_photo_is_refused_end_to_end(
    db_session: AsyncSession,
    tmp_path: Path,
    use_test_session: None,
    use_test_manual_csv,
) -> None:
    poster = await _make_poster(db_session, image_kind=PosterImageKind.DEFECT)
    use_test_manual_csv({poster.id: "1"})
    path = _sheet(
        tmp_path,
        [_row(poster, verified_at="SIGN", verified_at_reason="ตรวจครบทุกมิติแล้ว")],
    )

    from scripts.seed.correction_entry import PrecheckError

    with pytest.raises(PrecheckError, match="ADR-0027 D3"):
        await run(_args(path, commit=True), "test", now=REVIEWED_AT)

    refreshed = await _refresh(db_session, poster.id)
    assert refreshed.verified_at is None


async def test_signing_without_a_count_row_in_manual_entry_csv_is_refused(
    db_session: AsyncSession,
    tmp_path: Path,
    use_test_session: None,
    use_test_manual_csv,
) -> None:
    """🔴 count_actual มาจากไฟล์จริง — ไม่มีแถวของ poster นี้เลยใน manual-entry.csv
    ⇒ UNKNOWN_COUNT ⇒ ปฏิเสธทั้งไฟล์"""
    poster = await _make_poster(db_session)
    use_test_manual_csv({})  # ไฟล์มีอยู่ แต่ไม่มีแถวของ poster นี้
    path = _sheet(
        tmp_path,
        [_row(poster, verified_at="SIGN", verified_at_reason="ตรวจครบทุกมิติแล้ว")],
    )

    from scripts.seed.correction_entry import PrecheckError

    with pytest.raises(PrecheckError, match="ADR-0027 D3"):
        await run(_args(path, commit=True), "test", now=REVIEWED_AT)

    refreshed = await _refresh(db_session, poster.id)
    assert refreshed.verified_at is None


async def test_signing_succeeds_when_the_real_manual_entry_csv_has_the_count(
    db_session: AsyncSession,
    tmp_path: Path,
    use_test_session: None,
    use_test_manual_csv,
) -> None:
    """positive control ของ §ด่านก่อนเซ็น — ยืนยันว่าการอ่านไฟล์จริงเดินสำเร็จได้"""
    poster = await _make_poster(db_session)
    use_test_manual_csv({poster.id: "1"})
    path = _sheet(
        tmp_path,
        [_row(poster, verified_at="SIGN", verified_at_reason="ตรวจครบทุกมิติแล้ว")],
    )

    rc = await run(_args(path, commit=True), "test", now=REVIEWED_AT)

    assert rc == 0
    refreshed = await _refresh(db_session, poster.id)
    assert refreshed.verified_at == REVIEWED_AT


# --------------------------------------------------------------------------
# critic รอบ 1 H-2 — `run()`/`main()` ที่ target="production" ยังไม่มีเทสเลย
# (คู่แฝดของ tests/unit/test_manual_entry_run_harness.py — เส้นที่ 5 อยู่ใน
# PRODUCTION_LANES เหมือนกับเส้นที่ 3)
# --------------------------------------------------------------------------

_TOTP_SECRET_B32 = base64.b32encode(b"12345678901234567890").decode()
PRODUCTION_ACTOR_EMAIL = "prod-admin@example.test"


class _FakeTTYStdin:
    def isatty(self) -> bool:
        return True


async def _make_production_admin(session: AsyncSession) -> User:
    user = User(email=PRODUCTION_ACTOR_EMAIL, is_verified=True, is_admin=True)
    session.add(user)
    await session.flush()
    session.add(
        OAuthIdentity(
            user_id=user.id,
            provider=OAuthProvider.google,
            provider_user_id=f"google-uid-{user.id}",
            email=PRODUCTION_ACTOR_EMAIL,
        )
    )
    await session.flush()
    return user


def _setup_production_environment(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    *,
    at: datetime,
    sha: str = "e" * 40,
) -> dict[str, Path]:
    monkeypatch.setenv("ENVIRONMENT", "production")

    secret_path = tmp_path / "totp-secret"
    secret_path.write_text(_TOTP_SECRET_B32, encoding="utf-8")
    secret_path.chmod(0o400)
    monkeypatch.setenv("OPS_TOTP_SECRET_PATH", str(secret_path))
    code = _totp.totp(_TOTP_SECRET_B32, at=at)
    monkeypatch.setattr(gate.sys, "stdin", _FakeTTYStdin())
    monkeypatch.setattr(gate.getpass, "getpass", lambda prompt="": code)
    monkeypatch.setattr(gate, "_now", lambda: at)

    audit_dir = tmp_path / "audit"
    audit_dir.mkdir()
    monkeypatch.setenv("OPS_AUDIT_DIR", str(audit_dir))

    deployed_sha = tmp_path / ".deployed-sha"
    deployed_sha.write_text(sha, encoding="utf-8")
    monkeypatch.setenv("IMAGE_TAG", sha)
    monkeypatch.setenv("DEPLOYED_SHA_PATH", str(deployed_sha))

    backup_dir = tmp_path / "backups"
    backup_dir.mkdir()
    monkeypatch.setenv("OPS_BACKUP_DIR", str(backup_dir))
    backup_ref = backup_dir / "prod.dump"
    backup_ref.write_bytes(b"PGDMP" + b"\x00" * 16)
    import os

    ts = at.timestamp()
    os.utime(backup_ref, (ts, ts))

    monkeypatch.setattr("builtins.input", lambda prompt="": "production")

    return {"audit_dir": audit_dir, "backup_ref": backup_ref}


def _advance_totp(monkeypatch: pytest.MonkeyPatch, *, at: datetime) -> None:
    code = _totp.totp(_TOTP_SECRET_B32, at=at)
    monkeypatch.setattr(gate.getpass, "getpass", lambda prompt="": code)
    monkeypatch.setattr(gate, "_now", lambda: at)


def _extract_plan_hash(printed: str) -> str:
    match = re.search(r"plan-hash[^:]*:\s*([0-9a-f]{64})", printed)
    assert match, f"หา plan-hash ไม่เจอในรายงาน:\n{printed}"
    return match.group(1)


async def test_dry_run_on_production_writes_nothing(
    db_session: AsyncSession,
    tmp_path: Path,
    use_test_session: None,
    use_test_manual_csv,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """H-2 (a) — dry-run บน production ต้องผ่านด่าน ①②③⑥⑧ แต่ยังไม่เขียนอะไรเลย"""
    await _make_production_admin(db_session)
    _setup_production_environment(monkeypatch, tmp_path, at=REVIEWED_AT)
    poster = await _make_poster(db_session, verified_at=None)
    use_test_manual_csv({poster.id: "1"})
    path = _sheet(
        tmp_path,
        [_row(poster, verified_at="SIGN", verified_at_reason="ตรวจครบทุกมิติแล้ว")],
    )

    rc = await run(
        _args(
            path,
            commit=False,
            target="production",
            actor=PRODUCTION_ACTOR_EMAIL,
            audit_log=str(tmp_path / "audit" / "correction.jsonl"),
        ),
        "test  [--target production]",
        now=REVIEWED_AT,
    )
    capsys.readouterr()

    assert rc == 0
    refreshed = await _refresh(db_session, poster.id)
    assert refreshed.verified_at is None
    assert await _audit_fields(db_session, poster.id) == []
    assert (tmp_path / "audit" / "totp-last.json").exists()


async def test_audit_write_failure_on_intent_leaves_the_database_untouched(
    db_session: AsyncSession,
    tmp_path: Path,
    use_test_session: None,
    use_test_manual_csv,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """H-2 (b) — เขียน audit `phase="intent"` ไม่สำเร็จ ⇒ ต้องไม่มีผลข้างเคียงใน DB"""
    await _make_production_admin(db_session)
    _setup_production_environment(monkeypatch, tmp_path, at=REVIEWED_AT)
    poster = await _make_poster(db_session, verified_at=None)
    use_test_manual_csv({poster.id: "1"})
    path = _sheet(
        tmp_path,
        [_row(poster, verified_at="SIGN", verified_at_reason="ตรวจครบทุกมิติแล้ว")],
    )
    audit_log = tmp_path / "audit" / "correction.jsonl"

    dry_args = _args(
        path,
        commit=False,
        target="production",
        actor=PRODUCTION_ACTOR_EMAIL,
        audit_log=str(audit_log),
    )
    await run(dry_args, "test  [--target production]", now=REVIEWED_AT)
    plan_hash = _extract_plan_hash(capsys.readouterr().out)

    import scripts._audit as audit_mod

    def _boom(path: Path, record: dict) -> None:
        raise audit_mod.AuditWriteFailed("simulated — เขียน audit ไม่สำเร็จ")

    monkeypatch.setattr(audit_mod, "append_audit_line", _boom)

    _advance_totp(monkeypatch, at=REVIEWED_AT + timedelta(seconds=30))
    commit_args = _args(
        path,
        commit=True,
        target="production",
        actor=PRODUCTION_ACTOR_EMAIL,
        audit_log=str(audit_log),
        plan_hash=plan_hash,
        backup_ref=str(tmp_path / "backups" / "prod.dump"),
    )
    rc = await run(commit_args, "test  [--target production]", now=REVIEWED_AT)

    assert rc == 1
    refreshed = await _refresh(db_session, poster.id)
    assert refreshed.verified_at is None
    assert await _audit_fields(db_session, poster.id) == []


async def test_commit_on_production_records_reviewed_by_as_the_actor_email(
    db_session: AsyncSession,
    tmp_path: Path,
    use_test_session: None,
    use_test_manual_csv,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """H-2 (c) — OD-4 — `reviewed_by` บน production ต้องเป็นอีเมลของ `--actor` เสมอ"""
    await _make_production_admin(db_session)
    _setup_production_environment(monkeypatch, tmp_path, at=REVIEWED_AT)
    poster = await _make_poster(db_session, verified_at=None)
    use_test_manual_csv({poster.id: "1"})
    path = _sheet(
        tmp_path,
        [_row(poster, verified_at="SIGN", verified_at_reason="ตรวจครบทุกมิติแล้ว")],
    )
    audit_log = tmp_path / "audit" / "correction.jsonl"

    dry_args = _args(
        path,
        commit=False,
        target="production",
        actor=PRODUCTION_ACTOR_EMAIL,
        audit_log=str(audit_log),
    )
    await run(dry_args, "test  [--target production]", now=REVIEWED_AT)
    plan_hash = _extract_plan_hash(capsys.readouterr().out)

    _advance_totp(monkeypatch, at=REVIEWED_AT + timedelta(seconds=30))
    commit_args = _args(
        path,
        commit=True,
        target="production",
        actor=PRODUCTION_ACTOR_EMAIL,
        audit_log=str(audit_log),
        plan_hash=plan_hash,
        backup_ref=str(tmp_path / "backups" / "prod.dump"),
    )
    rc = await run(commit_args, "test  [--target production]", now=REVIEWED_AT)

    assert rc == 0
    refreshed = await _refresh(db_session, poster.id)
    assert refreshed.verified_at == REVIEWED_AT
    rows = await db_session.execute(
        select(PosterAttributeReview.reviewed_by).where(
            PosterAttributeReview.poster_id == poster.id
        )
    )
    assert set(rows.scalars().all()) == {PRODUCTION_ACTOR_EMAIL}
    assert audit_log.exists()
    lines = audit_log.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    for line in lines:
        assert "@" not in line, f"audit line มีอีเมลหลุดเข้าไป: {line}"


def test_main_rejects_reviewed_by_on_production_before_touching_anything(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """H-2 (d) — `--reviewed-by` ห้ามใช้บน production (OD-4)"""
    monkeypatch.setattr(
        "sys.argv",
        [
            "correction_entry.py",
            "--commit",
            "--target",
            "production",
            "--reviewed-by",
            "someone",
            "--reviewed-at",
            "2020-01-01T00:00:00+07:00",
            "--actor",
            PRODUCTION_ACTOR_EMAIL,
            "--file",
            str(tmp_path / "correction-entry.csv"),
        ],
    )
    with pytest.raises(SystemExit) as exc:
        main()
    assert exc.value.code == 2


async def test_commit_is_rejected_when_db_state_changed_since_the_dry_run(
    db_session: AsyncSession,
    tmp_path: Path,
    use_test_session: None,
    use_test_manual_csv,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """H-2 (e) — plan-hash ต้องผูกกับสถานะ DB ตอน dry-run จริง (M-1 คือด่านที่ทำให้
    เคสนี้จับได้แม่นขึ้น: ค่าเดิมเปลี่ยนแต่ทับไปเป็นค่าเดียวกันก็ต้องถูกจับ)"""
    await _make_production_admin(db_session)
    _setup_production_environment(monkeypatch, tmp_path, at=REVIEWED_AT)
    poster = await _make_poster(
        db_session, condition_grade=PosterCondition.good, verified_at=PAST_SIGNED_AT
    )
    use_test_manual_csv({poster.id: "1"})
    path = _sheet(
        tmp_path,
        [
            _row(
                poster,
                condition_grade="fine",
                condition_grade_reason="ดูใบจริงซ้ำ พบรอยพับที่มุมล่างขวา",
            )
        ],
    )
    audit_log = tmp_path / "audit" / "correction.jsonl"

    dry_args = _args(
        path,
        commit=False,
        target="production",
        actor=PRODUCTION_ACTOR_EMAIL,
        audit_log=str(audit_log),
    )
    await run(dry_args, "test  [--target production]", now=REVIEWED_AT)
    plan_hash = _extract_plan_hash(capsys.readouterr().out)

    # DB state เปลี่ยนหลัง dry-run — ค่าเดิมกลายเป็น mint (จากเดิม good) ก่อนคนอื่นจะ
    # commit ตาม plan_hash เดิม ทับไปเป็น fine เหมือนกัน (M-1: ต้องจับได้แม้ค่าใหม่ตรงกัน)
    poster.condition_grade = PosterCondition.mint
    await db_session.flush()
    await db_session.commit()

    _advance_totp(monkeypatch, at=REVIEWED_AT + timedelta(seconds=30))
    commit_args = _args(
        path,
        commit=True,
        target="production",
        actor=PRODUCTION_ACTOR_EMAIL,
        audit_log=str(audit_log),
        plan_hash=plan_hash,
        backup_ref=str(tmp_path / "backups" / "prod.dump"),
    )

    with pytest.raises(PrecheckError, match="plan-hash"):
        await run(commit_args, "test  [--target production]", now=REVIEWED_AT)

    grade = await db_session.scalar(
        select(Poster.condition_grade).where(Poster.id == poster.id)
    )
    assert grade is PosterCondition.mint  # ไม่ถูกทับกลับเป็น fine
