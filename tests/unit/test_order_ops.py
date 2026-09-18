"""`scripts/orders/order_ops.py` — INF-41 สไลซ์ A (verify/ship/complete) + สไลซ์ B (reject-payment)

ทรงเดียวกับ `tests/unit/test_grant_admin.py`: เทสเรียก `order_ops.dispatch(session, ...)`
ตรง ๆ (แกนที่รับ session ฉีดเข้ามาได้) ไม่ใช่ `run()` ที่เปิด `async_session_maker()`
เอง — ถ้าเรียก `run()` จะได้ session คนละตัวกับ `db_session` fixture (คนละ connection
คนละทรานแซกชัน) เห็นข้อมูลที่ fixture สร้างไว้ไม่ได้เลย

🔴 **`dispatch()` เรียก `session.rollback()` เองเมื่อ service/commit ล้ม** (ต่างจาก
`grant_admin.grant()` ที่ตั้งใจไม่ทำแบบนั้น — ดู docstring ของมัน)

🔴 **หลัง rollback ต้อง query ใหม่เสมอ — ห้ามอ่าน attribute ของ object เดิม**
(`code-critic` รอบ 1 แก้การวินิจฉัยที่เคยผิด: ไม่ใช่ SAVEPOINT หรือ `FOR UPDATE`
ที่ทำให้ `MissingGreenlet` แต่เป็นการอ่าน attribute แบบ sync บน object ที่ถูก
`expire_all()`/rollback ทำให้ expired ไปแล้ว ต้อง reload ผ่าน await เท่านั้น)

**ทำไมเทส `test_a_commit_failure_...` ด้านล่างยังใช้ `db_session.rollback()` เปล่า
ไม่ใช่ `begin_nested()` เหมือนเทส rollback ของ `test_order_service_admin_lanes.py`**
— พิสูจน์แล้วด้วยการรันจริง (ไม่ใช่ทฤษฎี): แม้ห่อการเรียก `dispatch()` ด้วย
`db_session.begin_nested()` ของเทสเอง `session.rollback()` ที่ `dispatch()` เรียก
**จากในแอป** (ไม่ใช่เรียกผ่าน object ที่ `begin_nested()` คืนมาโดยตรง) ยังคงล้าง
**ทั้งทรานแซกชันของเซสชัน รวมถึง fixture ที่สร้างไว้ก่อน `begin_nested()` ด้วย**
(ยืนยันด้วยการเช็คว่า `admin` ที่สร้างไว้ก่อนหน้าหายไปด้วย) — ต่างจาก
`test_order_service_admin_lanes.py` ที่เทส**เรียก `sp.rollback()` เองตรง ๆ** บน
object ที่ `begin_nested()` คืนมา ซึ่ง scope ถูกต้องตามที่ควรจะเป็น ⇒ สอง
สถานการณ์นี้ไม่เหมือนกัน ทางแก้ของเทสนี้จึงยังเป็น `db_session.rollback()` เปล่า
+ query ใหม่ (ไม่ใช่ `begin_nested()`)
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from scripts import _audit
from scripts import grant_admin as grant_admin_mod
from scripts.orders import order_ops
from scripts.seed import manual_entry as manual_mod

from app.models.enums import OrderStatus, PaymentStatus
from app.models.order import Order
from app.models.poster import Poster
from tests.unit.test_order_service import (
    NOW,
    _a_listing,
    _a_seller,
    _a_user,
    _reserve_and_order,
    _sold_audit_rows,
)
from tests.unit.test_order_service_admin_lanes import (
    _a_claimed_payment,
    _advance_order,
    _an_admin,
    _history_rows,
)

TARGET_LABEL = "localhost/poster_nung_test  [--target dev]"


def _args(
    *,
    lane: str,
    order_no: str = "PN-260918-0001",
    actor: str = "admin@example.test",
    at: datetime = NOW,
    target: str = "dev",
    commit: bool = False,
    audit_log: Path | None = None,
    bank_statement_checked: bool = False,
    reason: str | None = None,
    tracking_no: str | None = None,
    carrier: str | None = None,
) -> argparse.Namespace:
    return argparse.Namespace(
        lane=lane,
        order_no=order_no,
        actor=actor,
        at=at,
        target=target,
        commit=commit,
        audit_log=str(audit_log) if audit_log is not None else None,
        bank_statement_checked=bank_statement_checked,
        reason=reason,
        tracking_no=tracking_no,
        carrier=carrier,
    )


def _lines(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


# --------------------------------------------------------------------------
# identity — AC-7 · §03 มติ "import ของเดิม ไม่ประกาศเอง"
# --------------------------------------------------------------------------


def test_targets_is_the_same_object_as_manual_entry() -> None:
    assert order_ops.TARGETS is manual_mod.TARGETS


def test_assert_target_is_the_same_object_as_manual_entry() -> None:
    assert order_ops.assert_target is manual_mod.assert_target


def test_append_audit_line_is_the_one_shared_object() -> None:
    assert (
        order_ops.append_audit_line
        is _audit.append_audit_line
        is grant_admin_mod.append_audit_line
    )


def test_docstring_states_attribution_not_authentication() -> None:
    """OD-3 — ต้องมีถ้อยคำนี้ตรงตัว ไม่ใช่แค่ความหมายใกล้เคียง"""
    assert "attribution ไม่ใช่ authentication" in (order_ops.__doc__ or "")


# --------------------------------------------------------------------------
# --target production ไม่มีโดยตั้งใจ (AC-7 · INF-44 AC-1)
# --------------------------------------------------------------------------


def test_target_production_is_rejected_at_the_argparse_layer(monkeypatch) -> None:
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "order_ops.py",
            "complete",
            "--order-no",
            "PN-260918-0001",
            "--actor",
            "admin@example.test",
            "--at",
            "2020-01-01T00:00:00+07:00",
            "--target",
            "production",
        ],
    )
    with pytest.raises(SystemExit) as exc:
        order_ops.main()
    assert exc.value.code == 2


# --------------------------------------------------------------------------
# reject-payment --reason บังคับ
# --------------------------------------------------------------------------


def test_reject_payment_without_a_reason_flag_is_an_argparse_error(monkeypatch) -> None:
    """`--reason` เป็น `required=True` ของ subparser ⇒ ขาดไปเลย = argparse error
    (`SystemExit(2)`) ก่อนถึง `main()` เอง"""
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "order_ops.py",
            "reject-payment",
            "--order-no",
            "PN-260918-0001",
            "--actor",
            "admin@example.test",
            "--at",
            "2020-01-01T00:00:00+07:00",
        ],
    )
    with pytest.raises(SystemExit) as exc:
        order_ops.main()
    assert exc.value.code == 2


def test_reject_payment_with_a_blank_reason_is_refused(monkeypatch, capsys) -> None:
    """`--reason` ใส่มาแต่เป็นช่องว่างล้วน — argparse ไม่จับ (ค่ามีอยู่จริง) ต้องพึ่ง
    ด่านของ `main()` เอง"""
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "order_ops.py",
            "reject-payment",
            "--order-no",
            "PN-260918-0001",
            "--actor",
            "admin@example.test",
            "--at",
            "2020-01-01T00:00:00+07:00",
            "--reason",
            "   ",
        ],
    )
    with pytest.raises(SystemExit) as exc:
        order_ops.main()
    assert exc.value.code == 2
    assert "--reason" in capsys.readouterr().err


# --------------------------------------------------------------------------
# ด่าน CLI ของอีกสองเส้น (Low-5 — ก่อนหน้านี้มีแค่ --reason ที่มีเทส)
# --------------------------------------------------------------------------


def test_verify_payment_without_the_bank_statement_checked_flag_is_refused(
    monkeypatch, capsys
) -> None:
    """`--bank-statement-checked` เป็น `store_true` (ไม่มี `required=True`) ⇒
    ไม่ใส่เลย = argparse ผ่าน แต่ `main()` เองต้องปฏิเสธ (SCR-15 AC-3)"""
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "order_ops.py",
            "verify-payment",
            "--order-no",
            "PN-260918-0001",
            "--actor",
            "admin@example.test",
            "--at",
            "2020-01-01T00:00:00+07:00",
        ],
    )
    with pytest.raises(SystemExit) as exc:
        order_ops.main()
    assert exc.value.code == 2
    assert "--bank-statement-checked" in capsys.readouterr().err


def test_ship_with_a_blank_tracking_no_is_refused(monkeypatch, capsys) -> None:
    """`--tracking-no` ใส่มาแต่เป็นช่องว่างล้วน — argparse ไม่จับ (ค่ามีอยู่จริง)
    ต้องพึ่งด่านของ `main()` เอง (ทรงเดียวกับ `--reason` ของ `reject-payment`)"""
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "order_ops.py",
            "ship",
            "--order-no",
            "PN-260918-0001",
            "--actor",
            "admin@example.test",
            "--at",
            "2020-01-01T00:00:00+07:00",
            "--tracking-no",
            "   ",
        ],
    )
    with pytest.raises(SystemExit) as exc:
        order_ops.main()
    assert exc.value.code == 2
    assert "--tracking-no" in capsys.readouterr().err


# --------------------------------------------------------------------------
# --at — ADR-0010 D5 (ก๊อปมาจาก manual_entry.py แต่พิสูจน์ผ่าน main() ของไฟล์นี้)
# --------------------------------------------------------------------------


def test_a_future_at_is_refused_before_anything_is_read(monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "order_ops.py",
            "complete",
            "--order-no",
            "PN-260918-0001",
            "--actor",
            "admin@example.test",
            "--at",
            "3000-01-01T00:00:00+07:00",
        ],
    )
    with pytest.raises(SystemExit) as exc:
        order_ops.main()
    assert exc.value.code == 2
    assert "อนาคต" in capsys.readouterr().err


def test_an_at_without_timezone_is_refused(monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "order_ops.py",
            "complete",
            "--order-no",
            "PN-260918-0001",
            "--actor",
            "admin@example.test",
            "--at",
            "2020-01-01T00:00:00",
        ],
    )
    with pytest.raises(SystemExit) as exc:
        order_ops.main()
    assert exc.value.code == 2
    assert "timezone" in capsys.readouterr().err


# --------------------------------------------------------------------------
# dispatch() — actor/order lookup ก่อนแตะอะไร
# --------------------------------------------------------------------------


async def test_an_unknown_actor_email_is_refused_without_opening_a_write(
    db_session: AsyncSession, tmp_path: Path
) -> None:
    seller = await _a_seller(db_session)
    poster = await _a_listing(db_session, seller)
    buyer = await _a_user(db_session, "buyer")
    order = await _reserve_and_order(db_session, poster, buyer)

    args = _args(
        lane="complete",
        order_no=order.order_no,
        actor="ไม่มีบัญชีนี้@example.test",
        commit=True,
        audit_log=tmp_path / "audit.jsonl",
    )
    code = await order_ops.dispatch(db_session, args, TARGET_LABEL, now=NOW)

    assert code == 1
    assert not (tmp_path / "audit.jsonl").exists()


async def test_a_non_admin_actor_is_refused(
    db_session: AsyncSession, tmp_path: Path, capsys
) -> None:
    seller = await _a_seller(db_session)
    poster = await _a_listing(db_session, seller)
    buyer = await _a_user(db_session, "buyer")
    order = await _reserve_and_order(db_session, poster, buyer)
    non_admin = await _a_user(db_session, "not-admin")

    args = _args(
        lane="complete",
        order_no=order.order_no,
        actor=non_admin.email,
        commit=True,
        audit_log=tmp_path / "audit.jsonl",
    )
    code = await order_ops.dispatch(db_session, args, TARGET_LABEL, now=NOW)

    assert code == 1
    assert not (tmp_path / "audit.jsonl").exists()
    captured = capsys.readouterr()
    assert "@" not in captured.out + captured.err
    assert str(non_admin.id) in captured.err


async def test_an_unknown_order_no_is_refused(
    db_session: AsyncSession, tmp_path: Path
) -> None:
    admin = await _an_admin(db_session)
    args = _args(
        lane="complete",
        order_no="PN-999999-9999",
        actor=admin.email,
        commit=True,
        audit_log=tmp_path / "audit.jsonl",
    )
    code = await order_ops.dispatch(db_session, args, TARGET_LABEL, now=NOW)

    assert code == 1
    assert not (tmp_path / "audit.jsonl").exists()


# --------------------------------------------------------------------------
# dry-run ไม่เรียก service เลย
# --------------------------------------------------------------------------


async def test_dry_run_never_calls_any_of_the_four_services(
    db_session: AsyncSession, monkeypatch
) -> None:
    from app.services import order_service

    def _boom(*_args, **_kwargs):
        raise AssertionError("dry-run ต้องไม่เรียก service เลย")

    monkeypatch.setattr(order_service, "verify_payment", _boom)
    monkeypatch.setattr(order_service, "reject_payment", _boom)
    monkeypatch.setattr(order_service, "ship_order", _boom)
    monkeypatch.setattr(order_service, "complete_order", _boom)

    seller = await _a_seller(db_session)
    poster = await _a_listing(db_session, seller)
    buyer = await _a_user(db_session, "buyer")
    admin = await _an_admin(db_session)
    order = await _reserve_and_order(db_session, poster, buyer)
    await _advance_order(db_session, order, actor=buyer, to=OrderStatus.SHIPPED)

    args = _args(
        lane="complete", order_no=order.order_no, actor=admin.email, commit=False
    )
    code = await order_ops.dispatch(db_session, args, TARGET_LABEL, now=NOW)

    assert code == 0


async def test_dry_run_previews_a_rejection_when_the_transition_is_not_allowed(
    db_session: AsyncSession,
) -> None:
    """🔴 `code-critic` รอบ 1 Low-4 — ก่อนหน้านี้ dry-run ไม่เช็ค
    `is_order_transition_allowed()` เลย ⇒ พิมพ์เหมือนทุกอย่างจะสำเร็จทั้งที่
    `--commit` จริงจะโดนประตูปฏิเสธด้วย `OrderTransitionNotAllowed` — เทสนี้ยืนยันว่า
    dry-run รายงาน exit 1 ให้เห็นตั้งแต่ก่อน `--commit`
    """
    seller = await _a_seller(db_session)
    poster = await _a_listing(db_session, seller)
    buyer = await _a_user(db_session, "buyer")
    admin = await _an_admin(db_session)
    order = await _reserve_and_order(db_session, poster, buyer)
    # order ยังอยู่ AWAITING_PAYMENT — "ship" ต้องการ AWAITING_SHIPMENT → SHIPPED
    # ซึ่งไม่อยู่ในตารางกฎเลยจากสถานะนี้

    args = _args(
        lane="ship",
        order_no=order.order_no,
        actor=admin.email,
        commit=False,
        tracking_no="TH1234567890",
    )
    code = await order_ops.dispatch(db_session, args, TARGET_LABEL, now=NOW)

    assert code == 1
    assert order.status is OrderStatus.AWAITING_PAYMENT  # ไม่ขยับเลย


# --------------------------------------------------------------------------
# --commit ครบวงจร ต่อเส้น
# --------------------------------------------------------------------------


async def test_commit_verify_payment_moves_the_order_and_writes_audit(
    db_session: AsyncSession, tmp_path: Path, capsys
) -> None:
    seller = await _a_seller(db_session)
    poster = await _a_listing(db_session, seller)
    buyer = await _a_user(db_session, "buyer")
    admin = await _an_admin(db_session)
    order = await _reserve_and_order(db_session, poster, buyer)
    await _advance_order(db_session, order, actor=buyer, to=OrderStatus.PAYMENT_REVIEW)
    payment = await _a_claimed_payment(db_session, order)
    audit_path = tmp_path / "audit.jsonl"

    args = _args(
        lane="verify-payment",
        order_no=order.order_no,
        actor=admin.email,
        commit=True,
        audit_log=audit_path,
        bank_statement_checked=True,
    )
    code = await order_ops.dispatch(db_session, args, TARGET_LABEL, now=NOW)

    assert code == 0
    assert order.status is OrderStatus.AWAITING_SHIPMENT
    assert payment.status is PaymentStatus.VERIFIED

    # มติเจ้าของ GATE 3 — stdout ต้องพูดภาษาเดียวกับ audit: user_id ไม่ใช่อีเมล
    captured = capsys.readouterr()
    assert "@" not in captured.out
    assert "@" not in captured.err
    assert str(admin.id) in captured.out

    records = _lines(audit_path)
    assert [r["phase"] for r in records] == ["intent", "committed"]
    for record in records:
        assert record["lane"] == "verify-payment"
        assert record["order_no"] == order.order_no
        assert record["actor_user_id"] == str(admin.id)
        assert "email" not in json.dumps(record)


async def test_commit_reject_payment_cancels_the_order_and_writes_audit(
    db_session: AsyncSession, tmp_path: Path
) -> None:
    seller = await _a_seller(db_session)
    poster = await _a_listing(db_session, seller)
    buyer = await _a_user(db_session, "buyer")
    admin = await _an_admin(db_session)
    order = await _reserve_and_order(db_session, poster, buyer)
    await _advance_order(db_session, order, actor=buyer, to=OrderStatus.PAYMENT_REVIEW)
    payment = await _a_claimed_payment(db_session, order)
    audit_path = tmp_path / "audit.jsonl"

    args = _args(
        lane="reject-payment",
        order_no=order.order_no,
        actor=admin.email,
        commit=True,
        audit_log=audit_path,
        reason="ลูกค้าโอนผิดยอด ติดต่อแล้ว",
    )
    code = await order_ops.dispatch(db_session, args, TARGET_LABEL, now=NOW)

    assert code == 0
    assert order.status is OrderStatus.CANCELLED
    assert payment.status is PaymentStatus.REJECTED
    poster_after = await db_session.get(Poster, poster.id)
    assert poster_after.status.value == "available"

    records = _lines(audit_path)
    assert [r["phase"] for r in records] == ["intent", "committed"]
    for record in records:
        assert record["lane"] == "reject-payment"
        assert record["order_no"] == order.order_no
        assert record["actor_user_id"] == str(admin.id)
        line_text = json.dumps(record)
        assert "@" not in line_text
        assert "ลูกค้าโอนผิดยอด" not in line_text  # audit ไม่มี reason ก็ได้ (§5)


async def test_commit_ship_moves_the_order(
    db_session: AsyncSession, tmp_path: Path
) -> None:
    seller = await _a_seller(db_session)
    poster = await _a_listing(db_session, seller)
    buyer = await _a_user(db_session, "buyer")
    admin = await _an_admin(db_session)
    order = await _reserve_and_order(db_session, poster, buyer)
    await _advance_order(
        db_session, order, actor=buyer, to=OrderStatus.AWAITING_SHIPMENT
    )

    args = _args(
        lane="ship",
        order_no=order.order_no,
        actor=admin.email,
        commit=True,
        audit_log=tmp_path / "audit.jsonl",
        tracking_no="TH1234567890",
        carrier="Kerry",
    )
    code = await order_ops.dispatch(db_session, args, TARGET_LABEL, now=NOW)

    assert code == 0
    assert order.status is OrderStatus.SHIPPED
    assert order.tracking_no == "TH1234567890"


async def test_commit_complete_sells_the_listing(
    db_session: AsyncSession, tmp_path: Path
) -> None:
    """🔴 `code-critic` รอบ 1 High — ครอบเส้นทางผ่าน CLI จริง (ไม่ใช่แค่เรียก
    `complete_order()` ตรง) ว่า actor ที่ระบุด้วย `--actor` ไหลถึง history/audit
    จริง (มิวเทตส่ง `actor_user_id=None` เข้า gate เคยรอด — ดู docstring ของ
    `test_completing_sells_the_listing_and_records_delivery`)
    """
    seller = await _a_seller(db_session)
    poster = await _a_listing(db_session, seller)
    buyer = await _a_user(db_session, "buyer")
    admin = await _an_admin(db_session)
    order = await _reserve_and_order(db_session, poster, buyer)
    await _advance_order(db_session, order, actor=buyer, to=OrderStatus.SHIPPED)

    args = _args(
        lane="complete",
        order_no=order.order_no,
        actor=admin.email,
        commit=True,
        audit_log=tmp_path / "audit.jsonl",
    )
    code = await order_ops.dispatch(db_session, args, TARGET_LABEL, now=NOW)

    assert code == 0
    assert order.status is OrderStatus.COMPLETED
    poster_after = await db_session.get(Poster, poster.id)
    assert poster_after.status.value == "sold"

    history = await _history_rows(db_session, order.id)
    last = history[-1]
    assert last.to_status == OrderStatus.COMPLETED.value
    assert last.actor_user_id == admin.id

    sold_rows = await _sold_audit_rows(db_session, poster.id)
    assert len(sold_rows) == 1
    assert sold_rows[0].reviewed_by == str(admin.id)


# --------------------------------------------------------------------------
# audit — สองจังหวะ · ไม่มี PII · ไม่มี DATABASE_URL
# --------------------------------------------------------------------------


async def test_audit_intent_line_comes_before_the_committed_line(
    db_session: AsyncSession, tmp_path: Path
) -> None:
    seller = await _a_seller(db_session)
    poster = await _a_listing(db_session, seller)
    buyer = await _a_user(db_session, "buyer")
    admin = await _an_admin(db_session)
    order = await _reserve_and_order(db_session, poster, buyer)
    await _advance_order(db_session, order, actor=buyer, to=OrderStatus.SHIPPED)
    audit_path = tmp_path / "audit.jsonl"

    await order_ops.dispatch(
        db_session,
        _args(
            lane="complete",
            order_no=order.order_no,
            actor=admin.email,
            commit=True,
            audit_log=audit_path,
        ),
        TARGET_LABEL,
        now=NOW,
    )

    records = _lines(audit_path)
    assert len(records) == 2
    assert records[0]["phase"] == "intent"
    assert records[1]["phase"] == "committed"
    for record in records:
        keys = set(record)
        assert {
            "phase",
            "lane",
            "order_no",
            "order_id",
            "from_status",
            "to_status",
            "actor_user_id",
            "at",
            "ran_at",
            "hostname",
            "target",
        } <= keys
        line_text = json.dumps(record)
        assert "@" not in line_text
        assert "DATABASE_URL" not in line_text
        assert "postgres" not in line_text.lower()


async def test_a_commit_failure_writes_intent_and_failed_but_not_committed_and_the_db_does_not_change(
    db_session: AsyncSession, tmp_path: Path, monkeypatch
) -> None:
    """`session.commit()` ล้ม → `phase="failed"` พร้อม `error=<ชื่อคลาส>` (ไม่มี message)
    ไม่มี `phase="committed"` และไม่มีอะไรถูกเขียนลง DB จริง

    🔴 **ไม่ห่อด้วย `begin_nested()`** — ทดสอบแล้วจริง (ไม่ใช่ทฤษฎี): แม้ห่อ
    `dispatch()` ด้วย `db_session.begin_nested()` ของเทสเอง `session.rollback()`
    ที่ `dispatch()` เรียก**จากในแอป**ยังล้างทั้งทรานแซกชันของเซสชันอยู่ดี (รวม
    seller/poster/buyer/admin/order ที่สร้างไว้**ก่อน** `begin_nested()` ด้วย —
    ยืนยันด้วยการเช็คว่า `admin` หายไปด้วย) ต่างจากเทสใน
    `test_order_service_admin_lanes.py` ที่เรียก `sp.rollback()` เองตรง ๆ บน
    object ที่ `begin_nested()` คืนมา ⇒ ปล่อยให้ `dispatch()` ล้างทั้งทรานแซกชัน
    ตามที่มันเป็นจริง แล้วพิสูจน์ด้วยการ query ใหม่ว่า **ไม่มีแถวไหนของ order นี้
    เหลืออยู่เลย** (แข็งแรงกว่า "ยัง SHIPPED" เพราะพิสูจน์ว่าไม่มี COMPLETED หลุดไป
    ค้างที่ไหนทั้งสิ้น ไม่ใช่แค่ค่าที่ session เดียวกันเห็น)
    """
    seller = await _a_seller(db_session)
    poster = await _a_listing(db_session, seller)
    buyer = await _a_user(db_session, "buyer")
    admin = await _an_admin(db_session)
    order = await _reserve_and_order(db_session, poster, buyer)
    await _advance_order(db_session, order, actor=buyer, to=OrderStatus.SHIPPED)
    order_id, poster_id = order.id, poster.id
    audit_path = tmp_path / "audit.jsonl"

    async def _boom_commit() -> None:
        raise RuntimeError("จำลอง commit ล้ม")

    monkeypatch.setattr(db_session, "commit", _boom_commit)

    code = await order_ops.dispatch(
        db_session,
        _args(
            lane="complete",
            order_no=order.order_no,
            actor=admin.email,
            commit=True,
            audit_log=audit_path,
        ),
        TARGET_LABEL,
        now=NOW,
    )
    assert code == 1
    monkeypatch.undo()

    records = _lines(audit_path)
    assert [r["phase"] for r in records] == ["intent", "failed"]
    assert records[1]["error"] == "RuntimeError"
    assert "message" not in records[1]
    assert "จำลอง" not in json.dumps(records[1])

    # `dispatch()` rollback แล้ว — ทั้งทรานแซกชันของเทสหายไปด้วย รวมถึงแถวเหล่านี้เอง
    refreshed_order = await db_session.scalar(select(Order).where(Order.id == order_id))
    refreshed_poster = await db_session.scalar(
        select(Poster).where(Poster.id == poster_id)
    )
    assert refreshed_order is None
    assert refreshed_poster is None


async def test_an_unwritable_audit_log_path_leaves_the_db_untouched(
    db_session: AsyncSession, tmp_path: Path
) -> None:
    blocker = tmp_path / "not-a-dir"
    blocker.write_text("ไฟล์ ไม่ใช่โฟลเดอร์", encoding="utf-8")
    bad_audit_log = blocker / "audit.jsonl"

    seller = await _a_seller(db_session)
    poster = await _a_listing(db_session, seller)
    buyer = await _a_user(db_session, "buyer")
    admin = await _an_admin(db_session)
    order = await _reserve_and_order(db_session, poster, buyer)
    await _advance_order(db_session, order, actor=buyer, to=OrderStatus.SHIPPED)

    code = await order_ops.dispatch(
        db_session,
        _args(
            lane="complete",
            order_no=order.order_no,
            actor=admin.email,
            commit=True,
            audit_log=bad_audit_log,
        ),
        TARGET_LABEL,
        now=NOW,
    )

    assert code == 1
    assert order.status is OrderStatus.SHIPPED
