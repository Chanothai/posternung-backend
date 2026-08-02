---
name: poster-database
description: >
  Convention การเพิ่ม/แก้ database schema ของ Poster Nung — model ใหม่, migration,
  PostgreSQL enum, constraint, และฟิลด์ที่ยังขาดของ `posters` (authenticity,
  print_origin, condition grade ฯลฯ) ใช้ skill นี้เสมอเมื่อผู้ใช้ขอเพิ่ม/แก้ column
  หรือ table ที่เกี่ยวกับ poster, เพิ่มค่า enum ใหม่ (เช่น poster_status,
  poster_condition), เขียน migration ที่แตะ posters/poster_images/reservations,
  หรืออ้างอิง spec/roadmap เรื่อง schema ของ poster (เช่นไฟล์
  `claude-code-prompt-poster-schema.md`) — ใช้แม้ผู้ใช้จะไม่พูดคำว่า "skill" หรือ
  "database" ตรงๆ แค่บอกว่าจะเพิ่มฟิลด์/แก้ enum/ทำ migration ก็เข้าเงื่อนไข
---

# Poster database (Poster Nung)

ไฟล์นี้เก็บ **convention เฉพาะของ schema poster + วิธี resolve เมื่อ spec ภายนอกขัดกับ
repo จริง** เท่านั้น สิ่งที่มีคำตอบอยู่แล้วที่อื่น ไปอ่านตรงนั้นแทน อย่าคาดหวังว่าจะซ้ำที่นี่:

| ต้องการอะไร | ไปที่ |
|---|---|
| schema เต็ม (ทุกตาราง ทุกคอลัมน์ ทุก enum value) | `docs/database-design.md` |
| Global Rules, architecture, Git workflow, F3 FOR UPDATE requirement | `CLAUDE.md` (โหลดอัตโนมัติทุก session อยู่แล้ว) |
| verify (`ruff`/`black`/`pytest`), reset test DB, migration up→down→up, เปิด PR | skill `ship-backend-change` |
| container ไม่ขึ้น, ต่อ DB ไม่ได้, psql เข้า container | skill `docker-environments` |

## 1. ข้อขัดแย้ง spec ↔ repo — มติที่ตัดสินแล้ว

มีไฟล์ spec ภายนอก (`claude-code-prompt-poster-schema.md`) ที่เสนอ refactor schema
poster แบบเขียนขึ้นโดยไม่เห็น repo จริง จึงขัดกับของที่มีอยู่หลายจุด ถ้าเจอ spec/prompt
ทำนองนี้อีก **ยึดมติข้างล่างเป็นค่าเริ่มต้น** ไม่ใช่ทำตาม spec ตรงๆ — ถ้าจะเปลี่ยนมติ
ต้องถามผู้ใช้ก่อน อย่าตัดสินใจเอง

> **ไฟล์ spec นั้นไม่ได้เก็บอยู่ใน repo นี้** (ผู้ใช้เอามาวางเป็นครั้งคราว) — ถ้าหาไม่เจอ
> อย่าเสียเวลาไล่หา สาระที่ต้องใช้สรุปไว้ครบแล้วในตารางข้างล่างกับ §6

| ประเด็น | spec เสนอ | **มติ (ใช้อันนี้)** | เหตุผล |
|---|---|---|---|
| โครงตาราง | ผ่า `posters` เป็น `movie` + `poster_item` + `poster_item_private` + `poster_image` | **คง `posters` เดิมไว้ เติมคอลัมน์เข้าไปทีละตัว** (ดู §6) | normalize เต็มรูปกระทบ API contract + Flutter ทันที โดยยังไม่มีเหตุผลจำเป็น (ยังไม่มี multi-listing ต่อหนัง 1 เรื่อง) |
| ตัวพิมพ์ enum | UPPERCASE ทั้งหมด (`ORIGINAL`, `DOUBLE_SIDED`) | **ค่าใหม่ = UPPERCASE** แต่ enum เดิม 4 ตัว (`poster_status` ฯลฯ) ยังเป็น lowercase อยู่จนกว่าจะมี PR ย้ายแยกต่างหาก | เดิมกับใหม่ปนกันได้ระยะสั้น แต่ **ห้ามเพิ่มค่าตัวพิมพ์เล็กใหม่เข้า enum เดิมอีก** — จะย้อนกลับยากขึ้น |
| กัน double-booking | ห้ามใช้ `SELECT ... FOR UPDATE` ให้ใช้ conditional `UPDATE ... WHERE status='available'` แทน | **คง `FOR UPDATE`** ตามที่ผูกไว้แล้วใน `CLAUDE.md`/`docs/database-design.md`/`docs/openapi.yaml` | เปลี่ยนกลไกตอนนี้ = แก้เอกสาร 3 ที่ + ยังไม่มี F3 implementation ให้ migrate จริงอยู่แล้ว (ดู §2) — ย้ายเวลามีเหตุผลจาก scale จริง ไม่ใช่ตาม spec ลอย |
| คำสั่ง dev | อ้าง `task be:lint` / `task be:test` / `task be:migrate` | **ไม่มี Taskfile ในนี้** ใช้คำสั่งจริงตามที่ CI รัน (ดู `ship-backend-change` §4) | สั่ง `task be:*` แล้วจะ fail เพราะไม่มีคำสั่งนี้อยู่จริง |

Spec ฉบับนี้ **ยังมีประโยชน์เป็น roadmap รายชื่อฟิลด์ที่ควรเติม** — ดู §6

## 2. สถานะจริง vs สิ่งที่เอกสารสื่อ

`posters` และ `poster_images` implement ครบ (model + repository + service + API
read-only) แต่ **`reservations` มีแค่ SQLAlchemy model เท่านั้น — ยังไม่มี
service/repository/API (F3 ยังไม่ทำ)** ทั้งที่ `docs/database-design.md`,
`docs/openapi.yaml` และ `CLAUDE.md` F3 เขียนกลไก `FOR UPDATE` ราวกับมีโค้ดจริงแล้ว
— ถ้างานที่ทำเกี่ยวกับ reservation ให้เช็คโค้ดจริงก่อนเชื่อเอกสารเหล่านั้น

## 3. กฎข้อมูล poster (เฉพาะโดเมนนี้ — ไม่อยู่ใน Global Rules ของ CLAUDE.md)

- **เงินห้ามเป็น float** — pattern ที่ repo ใช้อยู่จริงคือ DB `Numeric(12, 2)`
  (`Poster.price`) + Pydantic ประกาศเป็น `Decimal` เปล่าๆ (`app/schemas/poster.py`)
  ตามนั้นเวลาเพิ่มฟิลด์เงินใหม่ · ถ้าต้องการบังคับ scale ที่ชั้น schema ด้วย
  (`condecimal(max_digits=12, decimal_places=2)`) ทำได้ แต่**ยังไม่มีที่ไหนในโปรเจกต์ใช้**
  — ถ้าจะเริ่มใช้ ให้เปลี่ยนทั้งไฟล์ในรอบเดียว อย่าปนสองแบบ
- **ฟิลด์ที่เป็น `Decimal` ใน response ต้องประกาศเป็น `type: string` ใน `openapi.yaml`
  เสมอ ไม่ใช่ `type: number`** — Pydantic v2 serialize `Decimal` เป็น JSON string เสมอ
  (ยืนยันแล้ว: `Decimal('450.00').model_dump_json()` → `{"price":"450.00"}`) เจอเป็น
  contract drift จริงที่ `PosterListItem.price` มาก่อน (แก้ที่ `/feature SCR-05` GATE 3
  แล้ว) — ตอนเพิ่ม `payments.amount` / `manual_refunds.amount` (ADR-0002) ต้องเขียนเป็น
  `type: string, format: decimal` ตั้งแต่แรก อย่าเขียน `type: number` ตามสัญชาตญาณ
- **ปีหนังไม่เท่ากับปีที่พิมพ์โปสเตอร์** — ถ้าเพิ่มคอลัมน์ปีใหม่ ต้องแยกชัดว่าเป็นปี
  ไหน (`era_decade` ที่มีอยู่คือทศวรรษหนัง ไม่ใช่ปีพิมพ์) อย่ายุบเป็นฟิลด์เดียว —
  โปสเตอร์ re-release มูลค่าต่างจากพิมพ์รอบแรกมาก
- **1 แถวใน `posters` = โปสเตอร์จริง 1 ใบ** (มีเกรด ราคา รูป เป็นของตัวเอง) ไม่ใช่
  1 แถวต่อชื่อหนัง
- **ข้อมูลลับ (ต้นทุน, ซัพพลายเออร์, ที่จัดเก็บ) ห้ามอยู่ในตารางเดียวกับที่ query
  เพื่อ public response** — ถ้าเพิ่มฟิลด์กลุ่มนี้ ให้แยกตารางใหม่ (`poster_item_private`
  หรือชื่ออื่นที่สื่อความหมาย) ผูก 1:1 กับ `posters` ไม่ใช่เติมคอลัมน์ลงตารางเดิม (OWASP
  A01 — เผลอ select * แล้วข้อมูลลับหลุดออก public API ได้ง่ายกว่าถ้าอยู่ตารางเดียวกัน)
- **`status` เป็น state ที่ backend/service คุมเท่านั้น** — ถ้าทำ import หรือ admin
  form ที่แก้หลายคอลัมน์พร้อมกัน ห้ามให้เขียนทับ `status` ตรงๆ ต้องผ่าน service ที่คุม
  transition (available → reserved → sold)

## 4. เพิ่ม/แก้ model — ลำดับที่ต้องทำใน repo นี้

1. เพิ่มค่า enum ใหม่ใน `app/models/enums.py` ถ้าต้องใช้ (ดู §5 ก่อนตั้งชื่อค่า)
2. แก้/เพิ่ม column ใน `app/models/poster.py` (หรือไฟล์ model ใหม่ถ้าเป็นตารางใหม่)
   — reuse `uuid_pk()` / `TimestampMixin` / `CreatedAtMixin` จาก `app/models/base.py`
   เสมอ อย่าเขียน timestamp column เอง
3. **เติม import ใน `app/models/__init__.py`** ถ้าเป็น model ใหม่ — ลืมขั้นนี้แล้ว
   `alembic revision --autogenerate` จะมองไม่เห็นตารางใหม่เลย (ดู §7)
4. ใช้ `server_default` เป็นค่าเริ่มต้นเสมอ ไม่ใช่ default ฝั่ง Python — ทุก column
   ที่มีอยู่ในโปรเจกต์นี้ทำแบบนี้หมด (ดู `Poster.status`, `Poster.is_unique`)
5. เขียน/แก้ migration แล้วทำตาม `ship-backend-change` §4 (verify up→down→up, reset
   test DB) — ไม่ต้องทำเองที่นี่

## 5. Enum convention

- ค่า enum **ใหม่** ที่ยังไม่เคยมีในระบบ → เขียนเป็น **UPPERCASE** (`ORIGINAL`,
  `DOUBLE_SIDED`) ตามมติ §1
- Enum เดิม 4 ตัว (`poster_status`, `poster_condition`, `reservation_status`,
  `oauth_provider`) เป็น lowercase และผูกกับ `openapi.yaml` โดยตรง (comment ใน
  `enums.py` บอกไว้ว่า "ค่าต้องตรงกับ openapi.yaml เป๊ะ") — **ถ้าจะแปลงเป็น
  UPPERCASE ต้องทำเป็น PR แยกที่แก้พร้อมกันทั้ง 3 จุดในรอบเดียว**: migration
  เปลี่ยนค่า enum, `docs/openapi.yaml`, และฝั่ง Flutter — แก้จุดเดียวแล้วปล่อยไว้
  จะทำให้ client กับ backendไม่ตรงกัน
- ทุก `PgEnum(...)` ในโปรเจกต์นี้ประกาศ `create_type=False` (ดู `poster.py`,
  `reservation.py`) — หมายความว่า **autogenerate จะไม่สร้าง/ลบ TYPE ให้** ต้องเขียน
  migration เอง: `<enum>.create(bind, checkfirst=True)` ก่อน `op.create_table`/
  `add_column`, และ `.drop(bind, checkfirst=True)` ใน downgrade หลัง drop ทุกตาราง
  ที่ใช้ type นั้น
- **เพิ่มค่าใหม่เข้า enum ที่มีอยู่แล้ว** ใช้วิธี **recreate type** (ไม่ใช่
  `ALTER TYPE ... ADD VALUE` เพราะคำสั่งนั้น downgrade ไม่ได้ในทรานแซกชันเดียว) —
  ดูสูตรจริงที่ migration `f1b2a3c4d5e6` เป็นตัวอย่าง: RENAME type เดิม → CREATE
  type ใหม่ด้วยค่าครบ → `ALTER TABLE ... USING col::text::newtype` → DROP type เดิม

## 6. ฟิลด์ที่ spec เสนอไว้แต่ยังไม่มีในโค้ด (roadmap — ทำทีละตัวตาม §1)

สรุปจาก `claude-code-prompt-poster-schema.md` Phase 1 มาไว้ที่นี่แล้ว (ตัวไฟล์ไม่ได้อยู่
ใน repo — ดู §1 · ตารางนี้คือสาระทั้งหมดที่ต้องใช้ ไม่ต้องตามหาไฟล์ต้นทาง) รายการนี้เป็น
roadmap ที่ยัง**ไม่มีอยู่จริง** อย่าสมมติว่ามีคอลัมน์เหล่านี้แล้ว เพิ่มได้ทีละตัวตาม §4:

| ฟิลด์ที่ควรเติม | ลง `posters` | หมายเหตุ |
|---|---|---|
| `authenticity` (ORIGINAL/REPRINT/REPRODUCTION) | ใหม่ | ดูว่าซ้ำความหมายกับ `is_authenticated`/`authenticity_note` ที่มีอยู่แล้วหรือไม่ — คุยกับผู้ใช้ก่อนเพิ่ม column ใหม่ทับของเดิม |
| `print_origin` (US/INTERNATIONAL/TH/OTHER) | ใหม่ | |
| `print_sides` (SINGLE_SIDED/DOUBLE_SIDED) | ใหม่ | |
| `print_year` | ใหม่ | **ต้องแยกจาก `era_decade` เดิม** ตามกฎ §3 |
| `storage_form` (ROLLED/FOLDED) | ใหม่ | |
| `edition`, `catalog_no`, `width_in`/`height_in`, `defects[]`, `is_rare` | ใหม่ | |
| `cost_amount`, `supplier`, `storage_location`, `acquired_on` | **ตารางใหม่** (private) | ตามกฎ §3 ห้ามอยู่ตาราง `posters` |
| `poster_images.role`/`kind` (FRONT/BACK/DETAIL) | แก้ `poster_images` | BLOCK 5.5 — ยังไม่ทำ (`storage_key` ทำไปแล้วตาม ADR-0006 ดู `docs/database-design.md` §4.5) |

## 7. กับดักที่เจอมาแล้ว (เฉพาะเรื่อง schema — ไม่ซ้ำกับ skill อื่น)

| อาการ | สาเหตุ | ทางแก้ |
|---|---|---|
| `alembic revision --autogenerate` ไม่เห็น model ใหม่เลย | ลืมเติม import ใน `app/models/__init__.py` | เพิ่ม import + ใส่ชื่อใน `__all__` ก่อนรัน autogenerate เสมอ |
| autogenerate ไม่สร้าง `CREATE TYPE` หรือ `CREATE EXTENSION` ให้ | ทุก `PgEnum` ในโปรเจกต์ตั้ง `create_type=False`; extension (เช่น `citext`) ก็ไม่ auto-detect เหมือนกัน | เขียน `.create()/.drop()` และ `CREATE EXTENSION IF NOT EXISTS` เองในไฟล์ migration (ดู §5) |
| column ใหม่ที่เป็น enum insert ค่า default ไม่ได้ตอน migrate ข้อมูลเดิม | ใส่ `server_default=SomeEnum.value_name` (enum member) แทนสตริง | ต้องเป็น `.value` เสมอ เช่น `server_default=PosterStatus.available.value` ไม่ใช่ `PosterStatus.available` |
| แก้ enum แล้ว Flutter ขึ้น error/แสดงค่าผิดหลัง deploy | แก้ `enums.py` + migration แต่ลืมอัปเดต `docs/openapi.yaml` (contract) และโค้ด Flutter ให้ตรงกัน | แก้พร้อมกันทั้ง 3 จุดใน PR เดียวเสมอ ตามที่เขียนไว้ใน §5 |

## เมื่อไหร่ควรอ่านต่อ

**จะ verify, เขียน test, หรือเปิด PR** → skill **`ship-backend-change`** (มีสูตร
verify migration up→down→up, reset test DB, mirror CI ครบแล้ว ไม่ต้องทำซ้ำที่นี่)

**container/DB ต่อไม่ได้ ต้อง psql เข้าไปเช็คตาราง** → skill **`docker-environments`**

**ต้องการ schema เต็มทุกคอลัมน์/enum value หรือดูกลยุทธ์ concurrency แบบละเอียด** →
`docs/database-design.md`
