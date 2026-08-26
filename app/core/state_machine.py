"""ตารางกฎ transition ของสองเครื่อง — ADR-0033 **D1** (INF-33 AC-1 · AC-5)

**pure data + pure function** — ไม่มี `session` ไม่มี I/O ไม่ import repository เลย
(ทรงเดียวกับ `app/core/release_date.py` ที่แยกตัวคำนวณออกจาก service)

ทำไมต้องแยกออกมาเป็นไฟล์ของตัวเอง: สิ่งที่ **AC-5** ต้องพิสูจน์ (*ไม่มีเส้น
`sold → available`*) คือ **รูปร่างของกราฟ** ไม่ใช่พฤติกรรมของ session ⇒ กราฟที่เป็น
ข้อมูล pure ทำให้เขียนเทส closed-world บน **เส้นทั้งหมด** ได้โดยไม่ต้องมี DB
และทำให้ "เส้นที่อนุญาต" มีแหล่งความจริงที่นับได้ **ที่เดียว**

🔴 **ประกาศกราฟครบทั้งสองเครื่อง แต่ executor เขียนเฉพาะเส้นที่มีผู้เรียกจริง**
(ADR-0033 **OD-4** — เจ้าของเคาะ (ก) สำหรับตารางกฎ · (ข) สำหรับ executor)
⇒ การที่เส้นหนึ่งอยู่ในตารางนี้ **ไม่ได้แปลว่ามีโค้ดพามันเกิดแล้ว**

## ที่มาของทุกเส้น (ห้ามเพิ่มเส้นโดยไม่มีที่มา)

* **listing** — `BUSINESS_RULES.md` **BR-L5** (วงจรสถานะ) + **BR-L9** / `ADR-0028`
  **A1-D1** (แก้ tier/สภาพ ⇒ กลับไป `pending_review`) ·
  ตารางเต็มอยู่ที่ `docs/proposals/marketplace-schema-and-state-machine.md` §4.1
* **order** — `ADR-0028` **D4** · แผนภาพและตารางผลข้างเคียงที่ proposal §4.2

## 🔴 เส้นที่ *ตั้งใจไม่มี* — เขียนไว้เพื่อไม่ให้คนรอบหน้าเดาว่าตกหล่น

| เส้น | ทำไมไม่มี |
|---|---|
| `sold → available` | **INF-33 AC-5** ตรงตัว — ของคืนจาก dispute สร้าง listing **ใบใหม่** ไม่ใช่ปลุกใบเดิม (ของเปลี่ยนสภาพและเปลี่ยนเรื่องราวไปแล้ว) |
| `reserved → delisted` · `sold → delisted` | BR-L5 — ผู้ขายถอนของที่มีคนจอง/ซื้อไปแล้วไม่ได้ (คอมเมนต์ของ `PosterStatus` ใน `app/models/enums.py` เขียนข้อยกเว้นนี้ไว้แล้ว) |
| `rejected → pending_review` (ส่งใหม่หลังถูกปฏิเสธ) | **ยังไม่มีมติ** — proposal §4.1 ไม่มีเส้นนี้ และ BR-L5 วาดลูกศรทางเดียว ⇒ เป็นของ `SCR-13` ที่ต้องเคาะเอง **ห้ามเติมเองเพราะ "น่าจะต้องมี"** |
| `delisted → *` (เอากลับขึ้นชั้น) | เหตุผลเดียวกับแถวบน — ไม่มีมติ |
| `payment_review → cancelled` | proposal §4.2 มีเฉพาะ `awaiting_payment → cancelled` และ `awaiting_shipment → cancelled` · **BR-P7** อ่านได้ว่าน่าจะยกเลิกได้ทุกจังหวะก่อนส่งของ แต่ตารางผลข้างเคียงของ proposal ไม่ครอบช่องนี้ (สลิปที่ค้างอยู่ต้องทำยังไง) ⇒ ต้องมีมติก่อน |
"""

from __future__ import annotations

from app.models.enums import OrderStatus, PosterStatus
from app.models.order import TERMINAL_ORDER_STATUSES

# 🔴 อ่านจาก `app/models/order.py` **ห้ามพิมพ์รายชื่อซ้ำ** — ค่านั้นต้องตรงกับ
# `WHERE` ของ `uq_live_order_per_poster` เป๊ะ และมีเจ้าของอยู่แล้วที่ไฟล์โมเดล
TERMINAL_ORDER_STATES: frozenset[OrderStatus] = frozenset(
    OrderStatus(value) for value in TERMINAL_ORDER_STATUSES
)


# ── เครื่องที่ 1: listing (`posters.status`) ────────────────────────────────
LISTING_TRANSITIONS: dict[PosterStatus, frozenset[PosterStatus]] = {
    PosterStatus.draft: frozenset({PosterStatus.pending_review, PosterStatus.delisted}),
    PosterStatus.pending_review: frozenset(
        {PosterStatus.available, PosterStatus.rejected, PosterStatus.delisted}
    ),
    PosterStatus.rejected: frozenset({PosterStatus.delisted}),
    PosterStatus.available: frozenset(
        {
            PosterStatus.reserved,
            # BR-L9 · ADR-0028 A1-D1 — แก้ tier/สภาพ = กลับเข้าคิวอนุมัติใหม่
            PosterStatus.pending_review,
            PosterStatus.delisted,
        }
    ),
    PosterStatus.reserved: frozenset(
        {
            # จองหมดเวลา **และไม่มีการแจ้งโอน** (BR-B4 · BR-P9)
            PosterStatus.available,
            # เฉพาะตอน order เข้า COMPLETED (ADR-0028 D4 · INF-33 AC-4 — สไลซ์ B)
            PosterStatus.sold,
        }
    ),
    PosterStatus.sold: frozenset(),
    PosterStatus.delisted: frozenset(),
}


# ── เครื่องที่ 2: order (`orders.status`) ───────────────────────────────────
ORDER_TRANSITIONS: dict[OrderStatus, frozenset[OrderStatus]] = {
    OrderStatus.AWAITING_PAYMENT: frozenset(
        {OrderStatus.PAYMENT_REVIEW, OrderStatus.CANCELLED}
    ),
    OrderStatus.PAYMENT_REVIEW: frozenset(
        {
            OrderStatus.AWAITING_SHIPMENT,
            # แอดมินปฏิเสธสลิป → ผู้ซื้อจ่ายใหม่ได้อีก 30 นาที (BR-P10)
            OrderStatus.AWAITING_PAYMENT,
        }
    ),
    OrderStatus.AWAITING_SHIPMENT: frozenset(
        {OrderStatus.SHIPPED, OrderStatus.CANCELLED}
    ),
    OrderStatus.SHIPPED: frozenset({OrderStatus.COMPLETED, OrderStatus.DISPUTED}),
    OrderStatus.DISPUTED: frozenset({OrderStatus.COMPLETED, OrderStatus.REFUNDED}),
    OrderStatus.COMPLETED: frozenset(),
    OrderStatus.CANCELLED: frozenset(),
    OrderStatus.REFUNDED: frozenset(),
}


def listing_transitions_from(from_status: PosterStatus) -> frozenset[PosterStatus]:
    """ปลายทางที่ `from_status` ไปได้ — ค่าที่ไม่รู้จักคืนเซตว่าง (fail-closed)"""
    return LISTING_TRANSITIONS.get(from_status, frozenset())


def order_transitions_from(from_status: OrderStatus) -> frozenset[OrderStatus]:
    """ปลายทางที่ `from_status` ไปได้ — ค่าที่ไม่รู้จักคืนเซตว่าง (fail-closed)"""
    return ORDER_TRANSITIONS.get(from_status, frozenset())


def is_listing_transition_allowed(
    from_status: PosterStatus, to_status: PosterStatus
) -> bool:
    return to_status in listing_transitions_from(from_status)


def is_order_transition_allowed(
    from_status: OrderStatus, to_status: OrderStatus
) -> bool:
    return to_status in order_transitions_from(from_status)


def listing_edges() -> frozenset[tuple[PosterStatus, PosterStatus]]:
    """เส้นทั้งหมดของเครื่อง listing — ให้เทส closed-world นับได้ (AC-5)"""
    return frozenset(
        (source, target)
        for source, targets in LISTING_TRANSITIONS.items()
        for target in targets
    )


def order_edges() -> frozenset[tuple[OrderStatus, OrderStatus]]:
    """เส้นทั้งหมดของเครื่อง order — ให้เทส closed-world นับได้"""
    return frozenset(
        (source, target)
        for source, targets in ORDER_TRANSITIONS.items()
        for target in targets
    )
