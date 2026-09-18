# `scripts/orders/` — เส้นธุรกรรมที่แอดมินทำมือ (INF-41)

ประตูตัวที่สอง แยกจาก `scripts/seed/` เพราะไม่เขียน `posters` เลยสักคอลัมน์โดยตรง
(เหตุผลเต็มอยู่ใน docstring หัวไฟล์ `order_ops.py` §มติ AC-8)

## รัน

```bash
./venv/bin/python scripts/orders/order_ops.py --help
./venv/bin/python scripts/orders/order_ops.py verify-payment --help
./venv/bin/python scripts/orders/order_ops.py reject-payment --help
./venv/bin/python scripts/orders/order_ops.py ship --help
./venv/bin/python scripts/orders/order_ops.py complete --help
```

สี่เส้นวันนี้:

| เส้น | ทำอะไร | เขียน |
|---|---|---|
| `verify-payment` | ยืนยันเงินเข้าจริง (BR-P2) | `PAYMENT_REVIEW → AWAITING_SHIPMENT` + `payments.status → VERIFIED` |
| `reject-payment` | ปฏิเสธสลิป = ยกเลิกทันที (BR-P10 · A2-D1) | `PAYMENT_REVIEW → CANCELLED` + `payments.status → REJECTED` + `posters.status → available` ทันที (สามตารางในทรานแซกชันเดียว — **ไม่มีหน้าต่างแก้ตัวอีกแล้ว ดู §concierge ด้านล่าง**) |
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

## `reject-payment` — concierge ก่อนกด (A2-D3 · process ไม่ใช่โค้ด)

- 🔴 **ติดต่อผู้ซื้อก่อนกดปฏิเสธเสมอ** — ปฏิเสธ = ยกเลิกออร์เดอร์ + ปล่อยของทันที
  ไม่มีหน้าต่างแก้ตัวให้ผู้ซื้อคนเดิมในระบบอีกเลย (ช่องทางติดต่อ: `order_shipping_details`)
  บันทึกผลการติดต่อลง `--reason`
- ผู้ที่โอนจริงแต่ถูกปฏิเสธ (โอนผิดยอด/โอนช้า) = **คืนเงินด้วยมือตาม BR-P9** — ไม่มี
  โค้ดของเรื่องนี้ในสคริปต์
- "จ่ายใหม่ได้อีก 30 นาที" ของ BR-P10 เดิม เปลี่ยนความหมายเป็น "จองและสั่งใหม่ได้"
  ผ่านแอปปกติ — ไม่มีหน้าต่างพิเศษให้ผู้ซื้อคนเดิมอีกแล้ว

## audit

`--commit` เขียน audit สองบรรทัดต่อการรันหนึ่งครั้ง (`phase="intent"` ก่อนเรียก
service · `phase="committed"` หลัง commit สำเร็จ — ล้มเหลวได้ `phase="failed"` พร้อม
`error=<ชื่อ exception>` เท่านั้น ไม่มี message) ผ่าน `append_audit_line()` ตัวเดียวกับ
`grant_admin.py` (`scripts/_audit.py`) — **ไม่มี email / DATABASE_URL / password ในบรรทัด
ไหนเลย**
