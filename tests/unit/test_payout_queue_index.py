"""คิวจ่ายเงินต้องกันเงินไว้จนหน้าต่าง dispute ปิด — ADR-0032 Amendment 1 · D8-finding-2

## กฎที่ไฟล์นี้เฝ้า

เงินของออร์เดอร์ต้องถูกกันไว้จน **ครบ 7 วันหลัง `Shipped`** เสมอ **ต่อให้ผู้ซื้อกด
"ได้รับสินค้า ตรงตามรายการ" ไปแล้ว** (BR-P4 ให้กดเมื่อไหร่ก็ได้ · BR-P6 ให้เคลมได้ถึงวันที่ 7)
— ระบบนี้ไม่มี chargeback ช่วง dispute จึงเป็นการคุ้มครองเดียวที่ผู้ซื้อมี

จุดที่หน้าต่างปิดคือ `orders.auto_confirm_due_at` ซึ่งเป็น **snapshot** ที่คำนวณตอนเข้า
`SHIPPED` (ADR-0020 A4-D1 · ADR-0032 D7) ⇒ เกณฑ์เข้าคิวจ่ายจริงคือ

    status = 'COMPLETED' AND payout_id IS NULL AND auto_confirm_due_at <= now()

## 🔴 ไฟล์นี้พิสูจน์กฎนั้นไม่ได้ และนั่นคือประเด็นของมัน

`test_payout_eligibility_is_not_enforced_at_the_database_layer` เขียนไว้เพื่อ**บันทึกช่อง**
ว่ากฎนี้ **ไม่มีอะไรบังคับที่ชั้น DB เลย** — บังคับได้เฉพาะที่ query ของ payout scheduler
ซึ่งเป็นงานของ **INF-33** ที่ยังไม่มีโค้ดสักบรรทัด

ทรงเดียวกับ `test_buying_from_yourself_is_not_blocked_at_the_db_layer` ของ INF-32:
**เทสที่จะต้องแดงในวันที่ด่านตัวจริงถูกเพิ่ม ซึ่งเป็นสัญญาณให้มาลบเทสนั้นทิ้ง**
"""

from __future__ import annotations

import re

from app.models.order import Order

INDEX_NAME = "ix_orders_payout_queue"


def _payout_index():
    for index in Order.__table__.indexes:
        if index.name == INDEX_NAME:
            return index
    raise AssertionError(
        f"ไม่เจอ index {INDEX_NAME} — ถ้าเปลี่ยนชื่อ ต้องแก้เทสนี้พร้อมกัน "
        "ไม่ใช่ลบเทสทิ้ง"
    )


def test_index_carries_the_dispute_window_column() -> None:
    """`auto_confirm_due_at` ต้องอยู่ในคอลัมน์ของ index

    ถ้าใครถอดออก query ของคิวจ่ายจะต้องกลับไปอ่านตารางทุกแถวเพื่อกรองเวลา —
    ไม่ผิดเชิงความถูกต้อง แต่แปลว่าคนถอดไม่รู้ว่าคอลัมน์นี้อยู่ตรงนี้ทำไม
    """
    columns = [c.name for c in _payout_index().columns]
    assert columns == ["seller_id", "auto_confirm_due_at"], columns


def test_index_predicate_filters_status_and_unpaid_only() -> None:
    predicate = str(_payout_index().dialect_options["postgresql"]["where"])
    assert "status = 'COMPLETED'" in predicate
    assert "payout_id IS NULL" in predicate


def test_predicate_has_no_time_condition_because_postgres_forbids_it() -> None:
    """🔴 ไม่ใช่การลืม — PostgreSQL ปฏิเสธ predicate ที่มีฟังก์ชันแบบ non-IMMUTABLE

    พิสูจน์ด้วยคำสั่งจริงบน `poster_nung_test` 2026-08-25:
        CREATE INDEX ... WHERE status='COMPLETED' AND auto_confirm_due_at <= now();
        ERROR:  functions in index predicate must be marked IMMUTABLE

    เทสข้อนี้กันคนที่อ่านโค้ดแล้วคิดว่า "เงื่อนไขเวลาหายไป น่าจะลืม" แล้วเติมกลับเข้าไป
    — จะได้ migration ที่ล้มตอนรัน ไม่ใช่ตอนรีวิว
    """
    predicate = str(_payout_index().dialect_options["postgresql"]["where"])
    assert not re.search(
        r"now\(\)|current_timestamp|auto_confirm_due_at\s*<", predicate
    )


def test_payout_eligibility_is_not_enforced_at_the_database_layer() -> None:
    """บันทึกช่องที่ยังเปิดอยู่ — ไม่ใช่การยืนยันว่าปลอดภัย

    ไม่มี CHECK constraint และไม่มี predicate ตัวไหนที่ห้ามจ่ายก่อน
    `auto_confirm_due_at` · ออร์เดอร์ที่ `COMPLETED` แต่หน้าต่าง dispute ยังไม่ปิด
    **เข้าเงื่อนไข predicate ของ index นี้เต็ม ๆ** — DB ยอมทุกอย่าง

    ⇒ ตัวบังคับต้องอยู่ที่ query ของ payout scheduler (INF-33) พร้อมเทสว่า
    ออร์เดอร์แบบนั้นไม่โผล่ในคิว · **วันที่ด่านนั้นมาถึง เทสข้อนี้จะกลายเป็นเท็จ
    และต้องถูกลบ ไม่ใช่ถูกแก้ให้ผ่าน**
    """
    checks = [
        str(c.sqltext) for c in Order.__table__.constraints if hasattr(c, "sqltext")
    ]
    guarding = [c for c in checks if "auto_confirm_due_at" in c and "payout" in c]
    assert guarding == [], (
        "มี CHECK ที่ดูเหมือนบังคับเรื่องนี้แล้ว: "
        + str(guarding)
        + " — ถ้าด่านตัวจริงมาแล้ว ให้ลบเทสข้อนี้ทิ้งพร้อมอัปเดต ADR-0032 Amendment 1"
    )
