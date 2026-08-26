"""ตารางกฎ transition — INF-33 **AC-5** · ADR-0033 D1/OD-4

🔴 **เทสหลักของไฟล์นี้เป็น closed-world บน *เส้นทั้งหมด* ไม่ใช่การเช็คทีละเส้นที่นึกออก**
— assertion เชิงลบแบบระบุชื่อ (`assert (sold, available) not in edges`) จับได้เฉพาะ
เส้นที่เราเดาชื่อถูก ส่วนความผิดพลาดที่เกิดจริงคือ **การเพิ่มเส้นที่เราไม่รู้ว่ามันถูกเพิ่ม**
(`test-quality` §4) ⇒ เซตทั้งหมดต้องเท่ากับเซตที่ตั้งใจ

เซตที่คาดหวังในไฟล์นี้ **ประกอบจากเอกสารกติกา ไม่ใช่ก๊อปจากผลลัพธ์ที่โค้ดคืนวันนี้**
(`test-quality` §4 — allowlist ที่ก๊อปมาจากผลลัพธ์พิสูจน์แค่ว่าโค้ดเท่ากับตัวเอง):

* listing — `BUSINESS_RULES.md` **BR-L5** + **BR-L9** (`ADR-0028` A1-D1) ·
  ตารางเต็มที่ `docs/proposals/marketplace-schema-and-state-machine.md` §4.1
* order — `ADR-0028` **D4** · proposal §4.2
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from app.core import state_machine
from app.models.enums import OrderStatus, PosterStatus
from app.models.order import TERMINAL_ORDER_STATUSES

P = PosterStatus
O = OrderStatus  # noqa: E741 — ชื่อสั้นเพื่อให้ตารางเส้นด้านล่างอ่านเป็นตารางได้

# proposal §4.1 — ทุกแถวมีที่มาเป็นกติกา ไม่ใช่พฤติกรรมของโค้ดวันนี้
EXPECTED_LISTING_EDGES = frozenset(
    {
        (P.draft, P.pending_review),  # ผู้ขายส่งเข้าคิวอนุมัติ
        (P.draft, P.delisted),  # BR-L5 "ทุกสถานะก่อนขาย → Delisted"
        (P.pending_review, P.available),  # แอดมินอนุมัติ (BR-L6)
        (P.pending_review, P.rejected),  # แอดมินปฏิเสธ (ต้องมีเหตุผล)
        (P.pending_review, P.delisted),
        (P.rejected, P.delisted),
        (P.available, P.reserved),  # มีการจองสำเร็จ (BR-B1)
        (P.available, P.pending_review),  # แก้ tier/สภาพ (BR-L9 · ADR-0028 A1-D1)
        (P.available, P.delisted),
        (P.reserved, P.available),  # จองหมดเวลา + ไม่มีการแจ้งโอน (BR-B4 · BR-P9)
        (P.reserved, P.sold),  # เฉพาะตอน order → COMPLETED (ADR-0028 D4)
    }
)

# proposal §4.2 — สถานะปลายทางคือ COMPLETED · CANCELLED · REFUNDED เท่านั้น
EXPECTED_ORDER_EDGES = frozenset(
    {
        (O.AWAITING_PAYMENT, O.PAYMENT_REVIEW),  # ผู้ซื้อแจ้งโอน + อัปสลิป
        (O.AWAITING_PAYMENT, O.CANCELLED),  # หมดเวลาจอง / ยกเลิก
        (O.PAYMENT_REVIEW, O.AWAITING_SHIPMENT),  # แอดมินยืนยันเงินเข้า
        (O.PAYMENT_REVIEW, O.AWAITING_PAYMENT),  # แอดมินปฏิเสธสลิป (BR-P10)
        (O.AWAITING_SHIPMENT, O.SHIPPED),  # ผู้ขายกรอก tracking
        (O.AWAITING_SHIPMENT, O.CANCELLED),  # เลย ship_by_due_at (BR-P3)
        (O.SHIPPED, O.COMPLETED),  # ผู้ซื้อกดรับ / auto 7 วัน
        (O.SHIPPED, O.DISPUTED),  # ผู้ซื้อแจ้งปัญหาใน 7 วัน (BR-P6)
        (O.DISPUTED, O.COMPLETED),  # แอดมินตัดสินให้ผู้ขาย
        (O.DISPUTED, O.REFUNDED),  # แอดมินตัดสินคืนเงิน
    }
)


def test_listing_graph_is_exactly_the_rulebook() -> None:
    """closed-world ของเส้นทั้งหมดในเครื่อง listing — **เพิ่มเส้นใหม่ต้องแดง**"""
    assert state_machine.listing_edges() == EXPECTED_LISTING_EDGES


def test_order_graph_is_exactly_the_rulebook() -> None:
    """closed-world ของเส้นทั้งหมดในเครื่อง order — **เพิ่มเส้นใหม่ต้องแดง**"""
    assert state_machine.order_edges() == EXPECTED_ORDER_EDGES


def test_there_is_no_path_from_sold_back_to_available() -> None:
    """🔴 **INF-33 AC-5** — ของที่ขายแล้วไม่กลับเข้าชั้น

    เขียนแยกจาก closed-world ข้างบนโดยตั้งใจ: closed-world จะแดงถ้ามีคนเพิ่มเส้นนี้
    ก็จริง แต่มันแดงพร้อมข้อความ diff ยาว ๆ ที่คนอ่านอาจ "แก้ให้ผ่าน" ด้วยการเติม
    เส้นเข้า expected · เทสข้อนี้ตั้งชื่อกฎไว้ตรง ๆ ให้คนที่มาแก้เห็นว่ากำลังกลับมติอะไร
    """
    assert (P.sold, P.available) not in state_machine.listing_edges()
    assert state_machine.listing_transitions_from(P.sold) == frozenset()
    assert not state_machine.is_listing_transition_allowed(P.sold, P.available)


def test_delisted_is_not_reachable_from_reserved_or_sold() -> None:
    """BR-L5 — ผู้ขายถอนของที่มีคนจอง/ซื้อไปแล้วไม่ได้"""
    assert not state_machine.is_listing_transition_allowed(P.reserved, P.delisted)
    assert not state_machine.is_listing_transition_allowed(P.sold, P.delisted)


def test_every_status_value_has_a_row_in_both_tables() -> None:
    """สถานะที่ไม่มีแถวในตาราง = ตอบคำถาม "ไปไหนได้บ้าง" ไม่ได้เลย

    ต้องมีครบทุกค่าของ enum แม้ค่านั้นจะเป็นปลายทาง (แถวว่าง) — "ปลายทางโดยตั้งใจ"
    กับ "ลืมใส่" ต้องแยกออกจากกันได้จากตัวตาราง ไม่ใช่จากความจำของคนอ่าน
    """
    assert set(state_machine.LISTING_TRANSITIONS) == set(PosterStatus)
    assert set(state_machine.ORDER_TRANSITIONS) == set(OrderStatus)


def test_terminal_order_states_come_from_the_model_not_a_second_list() -> None:
    """`TERMINAL_ORDER_STATUSES` ต้องตรงกับ `WHERE` ของ `uq_live_order_per_poster`
    ⇒ มีเจ้าของอยู่แล้วที่ `app/models/order.py` **ห้ามพิมพ์รายชื่อซ้ำ**
    """
    assert state_machine.TERMINAL_ORDER_STATES == frozenset(
        OrderStatus(value) for value in TERMINAL_ORDER_STATUSES
    )


@pytest.mark.parametrize("terminal", sorted(state_machine.TERMINAL_ORDER_STATES))
def test_terminal_order_states_have_no_way_out(terminal: OrderStatus) -> None:
    """ADR-0028 D4 — ออกจาก `COMPLETED`/`CANCELLED`/`REFUNDED` ไม่ได้"""
    assert state_machine.order_transitions_from(terminal) == frozenset()


def test_unknown_source_status_is_fail_closed() -> None:
    """ค่าที่ไม่มีในตาราง (เช่นถ้ามีคนเพิ่มค่า enum แล้วลืมเพิ่มแถว) ต้องแปลว่า
    **ไปไหนไม่ได้เลย** ไม่ใช่ **ไปได้ทุกที่**
    """
    assert state_machine.listing_transitions_from(None) == frozenset()  # type: ignore[arg-type]
    assert state_machine.order_transitions_from(None) == frozenset()  # type: ignore[arg-type]


def test_state_machine_module_stays_pure() -> None:
    """ADR-0033 D1 — ตารางกฎต้องไม่มี session ไม่มี I/O ไม่ import repository

    ถ้าวันหนึ่งมีคนลาก `AsyncSession` เข้ามาในไฟล์นี้ เทสรูปกราฟทั้งหมดจะต้องมี DB
    ถึงจะรันได้ ซึ่งเป็นการทำลายเหตุผลที่แยกไฟล์นี้ออกมาตั้งแต่แรก
    """
    tree = ast.parse(
        Path(state_machine.__file__).read_text(encoding="utf-8"),
        filename=state_machine.__file__,
    )

    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
    forbidden_imports = {
        name
        for name in imported
        if name.split(".")[0] in {"sqlalchemy", "asyncio"}
        or "repositories" in name
        or "services" in name
    }
    assert not forbidden_imports, f"state_machine.py ห้าม import: {forbidden_imports}"

    # ไม่มีฟังก์ชันไหนรับ session และไม่มี async def เลย — pure function ล้วน
    for node in ast.walk(tree):
        assert not isinstance(node, ast.AsyncFunctionDef), node.name
        if isinstance(node, ast.FunctionDef):
            names = [arg.arg for arg in node.args.args + node.args.kwonlyargs]
            assert "session" not in names, node.name
