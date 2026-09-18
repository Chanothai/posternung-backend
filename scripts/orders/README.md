# `scripts/orders/` — เส้นธุรกรรมที่แอดมินทำมือ (INF-41)

ประตูตัวที่สอง แยกจาก `scripts/seed/` เพราะไม่เขียน `posters` เลยสักคอลัมน์โดยตรง
(เหตุผลเต็มอยู่ใน docstring หัวไฟล์ `order_ops.py` §มติ AC-8)

## รัน

```bash
./venv/bin/python scripts/orders/order_ops.py --help
./venv/bin/python scripts/orders/order_ops.py verify-payment --help
./venv/bin/python scripts/orders/order_ops.py ship --help
./venv/bin/python scripts/orders/order_ops.py complete --help
```

สามเส้นวันนี้ (`reject-payment` ยังไม่ลง — รอ `ADR-0033` Amendment 2):

| เส้น | ทำอะไร | เขียน |
|---|---|---|
| `verify-payment` | ยืนยันเงินเข้าจริง (BR-P2) | `PAYMENT_REVIEW → AWAITING_SHIPMENT` + `payments.status → VERIFIED` |
| `ship` | กดส่งของแทนผู้ขาย | `AWAITING_SHIPMENT → SHIPPED` + เลขพัสดุ + เริ่มนาฬิกา `inspection_period_days` |
| `complete` | ปิดออร์เดอร์ | `SHIPPED → COMPLETED` + `posters.status → sold` (ผ่านประตูเดียวกัน) |

ทุกเส้น dry-run เป็นค่าเริ่มต้น (ไม่พิมพ์ `--commit` = ไม่เรียก service ไม่แตะ DB เลย)
`--target sit|dev` เท่านั้น — ไม่มี `production` โดยตั้งใจ (ADR-0015 D8 · ปลดล็อกที่
`INF-44` AC-1 จุดเดียว)

## ข้อจำกัดที่รู้ตัว

- **`--target sit` ต้องรันข้างในคอนเทนเนอร์ sit** (`scripts` mount แบบ `:ro`) ⇒
  `--audit-log` ต้องชี้ path ที่**เขียนได้ในคอนเทนเนอร์** และไฟล์นั้น**หายเมื่อ
  container recreate** — ที่เก็บถาวรนอกเครื่องเจ้าของเป็นของ `INF-44` AC-4
  (ข้อจำกัดเดียวกับ `grant_admin.py` D6-b)
- `--actor <email>` เป็น **attribution ไม่ใช่ authentication** — อ่านเหตุผลเต็มใน
  docstring หัวไฟล์ `order_ops.py`
- `reject-payment` ยังไม่ลง — รอมติ `ADR-0033` Amendment 2

## audit

`--commit` เขียน audit สองบรรทัดต่อการรันหนึ่งครั้ง (`phase="intent"` ก่อนเรียก
service · `phase="committed"` หลัง commit สำเร็จ — ล้มเหลวได้ `phase="failed"` พร้อม
`error=<ชื่อ exception>` เท่านั้น ไม่มี message) ผ่าน `append_audit_line()` ตัวเดียวกับ
`grant_admin.py` (`scripts/_audit.py`) — **ไม่มี email / DATABASE_URL / password ในบรรทัด
ไหนเลย**
