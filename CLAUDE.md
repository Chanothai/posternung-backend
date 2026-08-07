# CLAUDE.md — Poster Nung Backend (FastAPI)

> ไฟล์นี้โหลดอัตโนมัติทุก session · เก็บเฉพาะ rule + สิ่งที่ต้องรู้ตลอด
> เรื่อง environment/deploy setup อยู่ที่ `.claude/rules/environments.md` (path-scoped rule — โหลดเข้า context เฉพาะตอนแตะไฟล์ config/deploy)

---

## Project
Backend REST API สำหรับ Movie Poster Original e-commerce

**ความเสี่ยงหลัก 2 อย่างที่ต้องระวังทุก feature:**
1. Unique inventory (สต็อก=1) → ต้องกัน race condition ด้วย row-lock
2. Real payment → กฎทั้งหมดอยู่ในสกิล `security-baseline` และ `../workspace/docs/adr/ADR-0002-payment.md`

## Stack
FastAPI async · SQLAlchemy 2.0 async · PostgreSQL · Alembic · Pydantic v2
JWT (`python-jose`) + Firebase Admin · `slowapi` · pytest + httpx · ruff + black

## Architecture (บังคับ)
```
app/{core,models,schemas,repositories,services,api/v1}
```
Dependency ทางเดียว: `api → services → repositories → models`
`api/` = thin controller เท่านั้น (ห้ามมี DB query) · business logic อยู่ใน `services/`

---

## 🔗 ไฟล์กลางที่อยู่นอก repo นี้

| อะไร | อยู่ที่ |
|---|---|
| **API contract (source of truth)** | `../workspace/docs/api/openapi.yaml` — **ห้ามแก้จาก repo นี้** · `docs/openapi.yaml` เหลือเป็น pointer แล้ว |
| Architecture decisions | `../workspace/docs/adr/` — **ADR-0002 ต้องอ่านก่อนแตะอะไรที่เกี่ยวกับเงินเสมอ** |
| ภาพรวมทั้งระบบ + คำสั่งเปิดงานประจำวัน | `../workspace/CLAUDE.md` |

`openapi.json` ที่ root generate จาก FastAPI = สะท้อนโค้ดจริง ใช้เทียบ drift กับ contract ได้
path ใน contract ที่มี `x-status: DRAFT` = ออกแบบไว้แต่ยังไม่มีโค้ด **ห้าม implement เอง**

## 🤖 Agent ของ repo นี้

`backend-dev` (`.claude/agents/backend-dev.md`) — ใช้เขียนโค้ดครบทุก layer ตาม contract
pipeline ทั้งรอบเรียกผ่าน `/feature` จาก `../workspace/`

---

## Global Rules (apply ทุก feature เสมอ)
1. ทุก endpoint มี Pydantic schema request/response — ห้าม return dict/ORM ตรงๆ
2. **ข้อมูลบัตรและ payment payload** → กฎอยู่ในสกิล `security-baseline` §1–2 (ห้ามเขียนซ้ำที่นี่)
3. Endpoint ที่ดึงข้อมูล user ต้องเช็ค ownership (กัน OWASP API1) ไม่ใช่แค่เช็คว่า login
4. ทุก service ใหม่ต้องมี unit test คู่กัน · **งานที่เขียนหรือแก้เทส → โหลดสกิล `test-quality`
   ก่อนเสมอ** (เจ้าของกฎเรื่อง mutation, assertion เชิงลบ, สิ่งที่เทสพิสูจน์ไม่ได้)
5. Rate-limit: `/auth/firebase`, `/cart/reserve`
6. **การ log ข้อมูลอ่อนไหว** → กฎอยู่ในสกิล `security-baseline` §2
7. ห้ามรัน alembic downgrade / drop table โดยไม่ถาม · ห้าม commit `.env`

---

## New API Checklist (ทุก endpoint ใหม่ — บังคับ ไม่ใช่แค่ happy path)
ทุก API ที่ implement ต่อจากนี้ ต้องทำ 3 ข้อนี้เสมอ (F1 hardening ทำเป็นต้นแบบไว้แล้ว):

1. **Edge-case errors** — ไล่หมวดให้ครบ ไม่ใช่แค่ทางที่ถูก:
   - validation boundary (min/max, byte vs char เช่น bcrypt 72 **bytes**, format/regex)
   - concurrency/race → catch `IntegrityError` แปลงเป็น 409 (ห้ามปล่อยเป็น 500)
   - not-found (404) · already-exists (409) · auth/ownership (401/403)
   - rate-limit (429) · timing/enumeration (login user ไม่มี → verify กับ dummy hash ให้ constant-time)
2. **Auth audit** — ตัดสินทุกเส้นว่า public หรือ protected → รายละเอียดในสกิล `security-baseline` §3
3. **Tests** — cover edge case ที่คิดในข้อ 1:
   - business logic → unit test (service) · behavior ระดับ HTTP (auth, envelope, ownership, status) → integration test ผ่าน `client` fixture (`tests/conftest.py`)

Error ใหม่เพิ่มใน `app/core/exceptions.py` (subclass `AppError`) ให้ตรง error_code catalog · แล้วอัปเดต `docs/api-contract-f1-f3.md`

---

## Checklist ก่อนจบแต่ละ feature (ห้ามข้าม)
- [ ] เปิด `/docs` ทดสอบ endpoint จริง ≥1 รอบ
- [ ] commit: `feat(<scope>): <subject>` (scope = ชื่อ feature เช่น auth, reservation) — บน feature branch ตาม Git Workflow ด้านล่าง

คำสั่ง verify ทั้งหมด (`ruff` · `black` · `alembic` · `pytest` + วิธี reset test DB
และ verify migration up→down→up) → สกิล **`ship-backend-change` §4** ห้ามเขียนซ้ำที่นี่
ข้อบังคับเรื่อง test ของงานที่แตะสต็อก/เงิน → สกิล **`stock-integrity`**
การตรวจ ownership และการ grep หาข้อมูลบัตร → สกิล **`security-baseline`**

## Git Workflow (บังคับ — repo protect `master` และ `develop` ระดับ GitHub server-side)
`master` และ `develop` protect ด้วย GitHub ruleset จริงทั้งคู่ (ไม่ใช่แค่ข้อตกลง) — push
ตรงเข้าทั้งสอง branch ถูก GitHub ปฏิเสธเสมอ ไม่มีข้อยกเว้นแม้ admin
(`current_user_can_bypass: never`)

- **`develop` = integration branch — PR ทุกอันเข้าที่นี่ ไม่ใช่ `master`**
  ทุก feature/API service ใหม่ → แยก branch จาก `develop` เสมอ ตั้งชื่อ `feature/<scope>`
  (เช่น `feature/f2-poster-catalog`) หรือ `fix/<scope>` สำหรับ bug fix →
  `gh pr create --base develop`
- เปิด PR แล้ว**หยุดรอผู้ใช้ review + merge เอง** — ห้าม auto-merge แม้ CI (`test` job)
  จะผ่านแล้วก็ตาม
- **`master` = deploy trigger เท่านั้น** — `develop` ไม่ผูกกับ build/deploy job ใดๆ
  (`push: branches: [master]` ใน `test.yml` ยังชี้ที่ `master` อย่างเดียว) การเอา
  `develop` → `master` (พร้อม deploy) เป็นการตัดสินใจแยกต่างหากที่ผู้ใช้ทำเอง (PR
  `develop` → `master` เมื่อพร้อม release)
- ทั้งสอง branch require: PR (ไม่บังคับ approval count — solo dev), status check `test`
  ผ่าน, ห้าม force-push, ห้ามลบ branch (ดู `.claude/rules/environments.md` ไม่เกี่ยว
  — rule นี้เป็น GitHub repo setting ไม่ใช่ path-scoped file)
- GitHub default branch ยังเป็น `master` (ไม่เปลี่ยน) — ต้องระบุ `--base develop`
  ทุกครั้งตอนเปิด PR ฟีเจอร์ใหม่

## ห้ามทำโดยไม่ถาม
- ห้าม auto-generate secret/JWT key ใส่ค่า default ที่ดูใช้งานได้จริง (ต้องเป็น placeholder)
- ห้าม drop table / alembic downgrade
- ห้าม commit `.env`
- ห้าม push ตรงเข้า `master` เด็ดขาด (ถูก GitHub ปฏิเสธอยู่แล้ว แต่ห้ามพยายามด้วย —
  ดู Git Workflow ด้านบน)
