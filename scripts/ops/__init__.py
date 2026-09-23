"""`scripts/ops/` — เครื่องมือ operator แบบ **one-shot** (ไม่ใช่ lane ที่รันซ้ำได้)

ต่างจาก `scripts/seed/*.py` ซึ่งเป็นเส้นทางเขียน `posters` ที่ "มีชีวิตต่อ" — รันซ้ำได้
ตามใบงานใหม่ทุกรอบ และขึ้นทะเบียนอยู่ใน `scripts/_production_gate.PRODUCTION_LANES` —
ไฟล์ในโฟลเดอร์นี้คือการก่อร่างฐานข้อมูลที่ทำได้ **ครั้งเดียวต่อ environment** แล้วปิดถาวร
ด้วย marker ไฟล์ของตัวเอง (ADR-0015 Amendment 4 `A4-D1` — ดูรายละเอียดเต็มที่
`../workspace/docs/adr/ADR-0015-manual-entry-path.md` §"Amendment 4")

**ไม่เข้า `scripts/seed/poster_ops.py`** และ **ไม่เพิ่มชื่อเข้า `PRODUCTION_LANES`**
— เส้นทางนี้ยืม gate ของ `scripts/_production_gate.py` เป็น**รายฟังก์ชัน** ไม่ใช่ผ่าน
`production_gate()` ทั้งก้อน เพราะด่าน 0 ของฟังก์ชันนั้นจะปฏิเสธเส้นที่ไม่อยู่ใน
`PRODUCTION_LANES` โดยนิยาม — และถูกต้องแล้วที่ปฏิเสธ
"""
