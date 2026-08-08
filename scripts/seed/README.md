# `scripts/seed/` — วิธีรัน

> **คำตอบสั้นที่สุด: รัน*บนเครื่อง*ด้วย `./venv/bin/python` ไม่ใช่ในคอนเทนเนอร์
> และไม่ใช่ `python3` เปล่า ๆ**
>
> ```bash
> cd ~/Desktop/frameshine/movieposter/posternung-backend
> docker compose up -d db                       # ต้องมี db ขึ้นก่อน
> ./venv/bin/python scripts/seed/make_manual_sheet.py
> ```

---

## 1. `python3` เปล่า ๆ ใช้ไม่ได้ — มี venv 2 ตัวในโปรเจกต์นี้ คนละหน้าที่

| venv | มีอะไร | ใช้กับสคริปต์ไหน |
|---|---|---|
| **`venv/` ที่ root ของ repo** | ทั้ง stack ของแอป (`sqlalchemy` · `asyncpg` · `alembic` · `pydantic`) | **ทุกตัวที่แตะ DB** — ทั้ง 6 ตัวในตาราง §4 ยกเว้น `ai_suggest.py` |
| `scripts/seed/.venv` | `anthropic` + `requests` เท่านั้น | **`ai_suggest.py` ตัวเดียว** (คุยกับ Claude API ไม่แตะ DB เลย) |

🔴 **`ModuleNotFoundError: No module named 'sqlalchemy'` = หยิบ venv ผิดตัว**
`scripts/seed/.venv` ถูกสร้างไว้ตอนทำ `ai_suggest.py` โดยเฉพาะ มันไม่มี `sqlalchemy`
และ **ไม่ควรมี** — สคริปต์ที่คุยกับ Claude API ไม่ควรลากทั้ง stack ของแอปมาด้วย
· `python3` ของระบบ (`/usr/local/bin/python3`) ก็ไม่มีเหมือนกัน

ทั้งสอง venv อยู่ใน `.gitignore` (`venv/` บรรทัด 17 · `.venv/` บรรทัด 18) — clone ใหม่
แล้วไม่มี ต้องสร้างเอง:

```bash
python3 -m venv venv && ./venv/bin/pip install -r requirements.txt
```

## 2. ทำไมต้องบนเครื่อง ไม่ใช่ `docker compose exec`

**ไม่ใช่เพราะ `:ro` — แต่เพราะ guard ของตัวสคริปต์เองปฏิเสธ**

สคริปต์ที่เขียน DB ทุกตัวเรียก `assert_target_database(url, "dev")` ซึ่งบังคับว่า
host ต้องเป็นเครื่องนี้ (`localhost` · `127.0.0.1` · `::1` · ว่าง) แต่ `docker-compose.dev.yml`
ตั้ง `DATABASE_URL` ของคอนเทนเนอร์ให้ชี้ hostname **`db`** (ต้องเป็นแบบนั้นเพราะมันคุยกัน
ผ่าน docker network) → รันข้างในได้ผลนี้เสมอ:

```
precheck ไม่ผ่าน: --target dev แต่ DATABASE_URL ชี้ host 'db' ซึ่งไม่ใช่เครื่องนี้
```

**ดังนั้นคำถามเรื่อง "เขียน `manual-entry.csv` ออกมาที่ไหนตอน mount เป็น `:ro`"
ไม่เกิดขึ้นเลย** — เส้นทางคอนเทนเนอร์ตันตั้งแต่ก่อนถึงจุดเขียนไฟล์

### 🔴 ห้ามถอด `:ro` ออกจาก `./scripts:/app/scripts:ro`

mount นั้น **ไม่ได้มีไว้ให้ `make_manual_sheet.py`/`manual_entry.py` ใช้** — มันมีไว้ให้
`apply_suggestions.py --target sit` ซึ่งเป็นโหมดเดียวที่ยอมให้ host ไม่ใช่เครื่องนี้
(เทียบกับ `.env.sit` แทน) · โฟลเดอร์นี้มี CSV ที่มีราคา · `seller_sku` ·
`tiktok_product_id` และ object key ของ R2 ครบทุกใบ การให้คอนเทนเนอร์เขียนกลับได้
ไม่ได้แลกอะไรกลับมาเลยในเมื่อไม่มีสคริปต์ตัวไหนต้องการ

## 3. dev DB ต่อจากเครื่องได้จริง — ยืนยันแล้ว

- `.env` ตั้ง `DATABASE_URL` ชี้ `localhost:5432/poster_nung_db`
- `docker-compose.yml` service `db` publish port ออกมาแล้ว
  (`docker ps` → `posternung-backend-db-1  0.0.0.0:5432->5432/tcp`)
- ผลรันจริง: `make_manual_sheet.py` → `อ่านจาก localhost/poster_nung_db — 117 ใบ`

ถ้าต่อไม่ได้ ให้ไล่ตามลำดับนี้ก่อนไปแก้โค้ด:

```bash
docker compose up -d db                        # db ขึ้นหรือยัง
docker ps --format '{{.Names}}\t{{.Ports}}'    # port 5432 publish ออกมาไหม
```

⚠️ `posternung-sit-db` **ไม่** publish port ออกมา (เห็นเป็น `5432/tcp` เฉย ๆ) — ตั้งใจ
· รายละเอียด gotcha ระดับ Docker อยู่ในสกิล `docker-environments` ไม่เขียนซ้ำที่นี่

## 4. สคริปต์ทั้งหมดในโฟลเดอร์นี้

| สคริปต์ | ทำอะไร | แตะ DB | รันด้วย |
|---|---|---|---|
| `prepare_seed.py` | แปลง export ของ TikTok → `posters-seed-v2.csv` | ไม่ | `./venv/bin/python` |
| `make_triage_sheet.py` | ใบงานให้คนตัดสิน `is_poster`/`needs_review` | ไม่ | `./venv/bin/python` |
| `seed_posters.py` | **INSERT** แถวตั้งต้น (`on_conflict_do_nothing`) | ✅ เขียน | `./venv/bin/python` |
| `migrate_to_r2.py` | ย้ายรูปขึ้น R2 + เขียน `storage_key` | ✅ เขียน | `./venv/bin/python` |
| `ai_suggest.py` | ให้ Claude อ่านรูป → `ai-suggestions.csv` | ❌ **ไม่แตะ DB เลย** | `scripts/seed/.venv/bin/python` |
| `make_review_sheet.py` | ใบงานให้คนเซ็นรับผลของ AI | ไม่ | `./venv/bin/python` |
| `apply_suggestions.py` | **UPDATE** `release_date_text` (ADR-0010) | ✅ เขียน | `./venv/bin/python` |
| `make_manual_sheet.py` | ใบงานให้คนกรอกเอง (อ่าน DB) | อ่านอย่างเดียว | `./venv/bin/python` |
| `manual_entry.py` | **UPDATE** 7 ฟิลด์ + `size_format` + `published_at` (ADR-0015) | ✅ เขียน | `./venv/bin/python` |
| `make_reference_sheet.py` | ใบงานให้คนแปะลิงก์แหล่งอ้างอิง (อ่าน DB) | อ่านอย่างเดียว | `./venv/bin/python` |
| `reference_entry.py` | **UPDATE** `reference_url`/`reference_note` + `verification_status` ที่ derive เอง (ADR-0014 Amendment 3) | ✅ เขียน | `./venv/bin/python` |

**cwd ไหนก็ได้** — ทุกตัวอ้าง path จากตำแหน่งไฟล์ตัวเอง (`Path(__file__)`) และอ่าน `.env`
จาก root ของ repo เสมอ · ตัวอย่างในเอกสารใช้ root เพื่อให้ path สั้น

## 5. สี่เส้นทางที่เขียน `posters` — คนละแหล่ง คนละกฎ (ADR-0015 D1)

**แบ่งเส้นด้วย *แหล่งของค่า* ไม่ใช่ *ใครเป็นคนกรอก*** — เส้นที่ 3 กับเส้นที่ 4 เป็นคน
คนเดียวกันและดูรูปชุดเดียวกัน แต่ค่ามาจากคนละที่ (จับใบจริง ↔ เปิดเว็บอ้างอิง)
จึงยังเป็นคนละเส้น · เหตุผลเต็ม: ADR-0015 D1 (Amendment 2026-08-08) + ADR-0014 D28

### เส้นที่ 1 — ข้อมูลตั้งต้นจาก TikTok export

```bash
./venv/bin/python scripts/seed/prepare_seed.py
./venv/bin/python scripts/seed/make_triage_sheet.py    # → กรอก is_poster/needs_review เอง
./venv/bin/python scripts/seed/seed_posters.py                       # dry-run
./venv/bin/python scripts/seed/seed_posters.py --commit --status available
```

### เส้นที่ 2 — AI เสนอ คนเซ็นรับ (ADR-0010 · `release_date_text` ฟิลด์เดียว)

```bash
scripts/seed/.venv/bin/python scripts/seed/ai_suggest.py --limit 5   # ← venv คนละตัว
./venv/bin/python scripts/seed/make_review_sheet.py    # → กรอก approved/corrected_text เอง
./venv/bin/python scripts/seed/apply_suggestions.py                  # dry-run
./venv/bin/python scripts/seed/apply_suggestions.py --commit \
    --reviewed-by <ชื่อคุณ> --reviewed-at 2026-08-06T13:30:00+07:00
```

`ai_suggest.py` ต้องมี `ANTHROPIC_API_KEY` + `MEDIA_BASE_URL` (ดู `.env.ai` — **ไม่อยู่ใน git**)

### เส้นที่ 3 — คนกรอกเอง (ADR-0015 · INF-11)

```bash
./venv/bin/python scripts/seed/make_manual_sheet.py    # → เปิดรูปดูแล้วกรอกเอง
./venv/bin/python scripts/seed/manual_entry.py                       # dry-run
./venv/bin/python scripts/seed/manual_entry.py --commit \
    --reviewed-by <ชื่อคุณ> --reviewed-at 2026-08-06T13:30:00+07:00
```

🔴 **เฟส 1 กรอกเกรดอย่างเดียว `publish=N` ทั้งหมด** — ห้ามใช้ `publish=Y` จนกว่า
**SCR-11 Condition Guide** และแถบแสดงตำแหน่งบนสเกลจะเสร็จ (ADR-0003 §ข้อบังคับด้าน UI:
`fine > very_good` สวนสัญชาตญาณ → dispute ที่คืนเงินอัตโนมัติไม่ได้ตาม ADR-0002)

#### `--target sit` — ใช้ได้จริงแล้ว (ใช้ครั้งแรก 2026-08-07)

`manual_entry.py` และ `reference_entry.py` รับ `--target dev|sit` (default `dev`) ·
**`production` ไม่มีให้เลือกและห้ามเพิ่มโดยไม่แก้ ADR-0015 D8** ·
`reference_entry.py` **import `assert_target()` ตัวเดียวกัน ไม่ก๊อป** — guard สองชั้น
จะได้ไม่ drift · `--target sit` ต้อง:

- **รันข้างในคอนเทนเนอร์ sit** — `.env.sit` ชี้ hostname `db` ซึ่ง resolve ได้เฉพาะใน
  docker network และ SIT DB ไม่ publish port ออกมาที่ host (นี่คือเหตุผลที่ mount
  `./scripts:/app/scripts:ro` มีอยู่)
- `DATABASE_URL` **ตรงกับ `.env.sit` เป๊ะ** · ไม่มีไฟล์ = **ไม่ให้รัน** ไม่ใช่เดาจาก
  ชื่อ database (เข้มกว่า `apply_suggestions.py --target sit` หนึ่งชั้น)

```bash
docker compose -p posternung-sit \
  -f docker-compose.yml -f docker-compose.sit.yml --env-file .env.sit \
  exec app python scripts/seed/manual_entry.py --target sit      # dry-run
```

🔴 **`-p posternung-sit` ห้ามลืม** — ไม่ใส่แล้ว compose จะใช้ project เดียวกับ dev
(ชื่อมาจากโฟลเดอร์) แล้วไป recreate/แย่ง `posternung-backend-db-1` ซึ่งคือ **dev db**
· รายละเอียดอยู่ในสกิล `docker-environments` §"ทำไมต้อง `-p`"

`docker-compose.sit.yml` mount `./.env.sit:/app/.env.sit:ro` ให้ด้วย เพราะ guard เทียบกับ
**ไฟล์** ไม่ใช่ env var — image COPY แค่ `app/` `alembic/` `alembic.ini` ไฟล์ env จึงไม่มี
อยู่ข้างใน · ไม่ได้เพิ่มความเสี่ยงใหม่ (ค่าทุกตัวอยู่ใน env ของคอนเทนเนอร์อยู่แล้วผ่าน
`env_file:`) และ **production/uat ไม่ inherit** (ตรวจแล้วด้วยคำสั่งในสกิล `docker-environments`)

✅ **SIT พร้อมรับแล้ว — ยืนยันด้วย query จริง 2026-08-07** (`BACKLOG.md` **BL-75** และ
**BL-83** ปิดแล้วทั้งคู่) · SIT มีคอลัมน์ครบ มี CHECK ของ ADR-0013 D3 และ app ที่รันอยู่
มี `published_only()` แล้ว · `--target sit --commit` ถูกใช้จริงครั้งแรกวันนั้น
‹ข้อความเดิมตรงนี้เขียนว่า "SIT ยังรับไม่ได้จริงวันนี้ — ตามหลัง migration 2 ตัว"
ซึ่ง **ตกยุคและทำให้เข้าใจผิดว่าเส้นทางนี้ยังใช้ไม่ได้"** แก้ 2026-08-08›

· ⚠️ **นโยบาย `publish=N` ของเฟส 1 ยังไม่มีด่านในโค้ด** — วันนี้ `publish=Y` ผ่านได้
ถ้าใบนั้นมีเกรดและมีรูป ไม่มีอะไรเช็คว่า SCR-11 เสร็จหรือยัง
(ดู `screens.yaml` INF-11 `known_gaps` · ADR-0015 §ต้องทำตามมา)

### เส้นที่ 4 — คนเปิดเว็บอ้างอิงแล้วแปะลิงก์ (ADR-0014 Amendment 3 · INF-13)

```bash
./venv/bin/python scripts/seed/make_reference_sheet.py   # → เปิดเว็บหาแล้วกรอกเอง
./venv/bin/python scripts/seed/reference_entry.py                    # dry-run
./venv/bin/python scripts/seed/reference_entry.py --commit \
    --reviewed-by <ชื่อคุณ> --reviewed-at 2026-08-08T20:00:00+07:00
```

ใบงาน `reference-entry.csv` มี **2 ช่องที่คนกรอก** — กรอกได้ **ช่องเดียวต่อแถว**:

| กรอกอะไร | ผล |
|---|---|
| `reference_url` (URL ล้วน ๆ) | `verification_status = REFERENCE_FOUND` |
| `reference_note` (เหตุผลตอนหาไม่เจอ) | `verification_status = NO_REFERENCE_FOUND` |
| ไม่กรอกอะไรเลย | คงเป็น `NULL` (= ยังไม่มีใครเปิดหา) |
| **กรอกทั้งคู่** | 🔴 **ปฏิเสธทั้งไฟล์** — ข้อมูลขัดกันเอง (ADR-0014 D29) |

- 🔴 **ไม่มีคอลัมน์ `verification_status` ให้กรอก** — สคริปต์ derive เอง (ADR-0014 D22)
- คอลัมน์ `previous_note` เป็น **ช่องช่วยจำของคน** ยกมาจาก `note` ของ `manual-entry.csv`
  — `reference_entry.py` **ไม่อ่านมันเลย** (ADR-0014 D28 · มีเทสล็อก)
- เขียนเฉพาะใบที่ **ทั้งสามคอลัมน์เป็น `NULL` ครบ** · ไม่มีโหมดเขียนทับ (D29)
- ⚠️ **`reference_url` ซ้ำข้ามแถวเป็นเรื่องปกติ ไม่ใช่บั๊ก** — ขึ้นเป็น warning แล้วเดินต่อ
  · เหตุผล (ใบไทยใช้อาร์ตเวิร์กชุดเดียวกับฉบับต่างประเทศ) อยู่ที่ **ADR-0014 D30**
  และ docstring ของสคริปต์ · 🔴 **ห้ามใครเปลี่ยนเป็นด่านปฏิเสธ**
- 🔴 **สคริปต์นี้ไม่ต่อเน็ต** — ไม่ยิง HTTP ไปเช็คว่าลิงก์มีชีวิต และไม่ normalize URL
- audit ลง `poster_attribute_reviews` **2 แถวต่อใบที่เขียนจริง** (ช่องที่คนกรอก +
  `verification_status` ที่ derive ได้) · `value_before` เป็น `NULL` เสมอ (ADR-0014 D31)

## 6. กติกาที่ใช้ร่วมกันทุกตัว

- **dry-run เป็น default เสมอ** ต้องใส่ `--commit` ถึงเขียนจริง
- ตัวสร้างใบงานทุกตัว **ปฏิเสธที่จะเขียนทับไฟล์ที่มีอยู่แล้ว** — กันทับงานที่กรอกไปครึ่งทาง
  (ลบหรือเปลี่ยนชื่อไฟล์เดิมก่อน) เพราะ CSV ไม่อยู่ใน git จึงกู้ไม่ได้
- 🔴 **`.gitignore` กัน `scripts/seed/*.csv` · `*.bak` · `*.csv.*` ไว้ทั้งหมด** — repo นี้
  เป็น public และ CSV มี object key ของ R2 ครบทุกใบ ซึ่งทำลายเจตนาของ ADR-0006 D2
  · **ห้าม `git add -f` ไฟล์พวกนี้เด็ดขาด**
- `--reviewed-at` **ไม่มี default เป็นเวลาปัจจุบัน** โดยตั้งใจ (ADR-0010 D5) — เวลาที่คน
  ตัดสินกับเวลาที่รันสคริปต์เป็นคนละเวลากันได้มาก การเดาให้คือการกรอกข้อมูลแทนคน
- **`production` ไม่มีให้เลือกในสคริปต์ตัวไหนเลย** — `--target` รับแค่ `dev|sit`
  (`manual_entry.py:TARGETS` · `reference_entry.py` import ทูเพิลเดียวกันมาใช้) และ
  การเพิ่มต้องแก้ ADR-0015 D8 ก่อน มีเทสล็อกไว้ทั้งสองฝั่ง
  ‹แก้ 2026-08-08 — บรรทัดนี้เคยเขียนว่า *"`manual_entry.py` ไม่มี `--target` ด้วยซ้ำ"*
  ซึ่งไม่จริงตั้งแต่ ADR-0015 D8 Amendment (2026-08-06): ของจริงมี `--target` และ
  guard **เข้มกว่า** `apply_suggestions.py` หนึ่งชั้น ไม่ใช่ไม่มีเลย›

กฎเรื่อง lint/test/PR ของ repo นี้อยู่ใน `CLAUDE.md` + สกิล `ship-backend-change`
— ไม่เขียนซ้ำที่นี่
