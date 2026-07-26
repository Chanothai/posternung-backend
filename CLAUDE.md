# CLAUDE.md — Poster Nung Backend (FastAPI)

> ไฟล์นี้โหลดอัตโนมัติทุก session · เก็บเฉพาะ rule + feature workflow
> เรื่อง environment/deploy setup อยู่ที่ `.claude/rules/environments.md` (path-scoped rule — โหลดเข้า context เฉพาะตอนแตะไฟล์ config/deploy)

---

## Project
Backend REST API สำหรับ Movie Poster Original e-commerce

**ความเสี่ยงหลัก 2 อย่างที่ต้องระวังทุก feature:**
1. Unique inventory (สต็อก=1) → ต้องกัน race condition ด้วย row-lock
2. Real payment → รับแค่ token ห้ามแตะข้อมูลบัตรดิบ (PCI-DSS)

## Stack
FastAPI async · SQLAlchemy 2.0 async · PostgreSQL · Alembic · Pydantic v2
JWT (`python-jose`) + `passlib[bcrypt]` · APScheduler · pytest + httpx · ruff + black

## Architecture (บังคับ)
```
app/{core,models,schemas,repositories,services,api/v1,tests}
```
Dependency ทางเดียว: `api → services → repositories → models`
`api/` = thin controller เท่านั้น (ห้ามมี DB query) · business logic อยู่ใน `services/`

---

## Global Rules (apply ทุก feature เสมอ)
1. ทุก endpoint มี Pydantic schema request/response — ห้าม return dict/ORM ตรงๆ
2. **ห้าม**สร้าง field รับเลขบัตร/CVV/expiry ในทุก schema — รับแค่ `payment_token`
3. Endpoint ที่ดึงข้อมูล user ต้องเช็ค ownership (กัน OWASP API1) ไม่ใช่แค่เช็คว่า login
4. ทุก service ใหม่ต้องมี unit test คู่กัน
5. Rate-limit: `/auth/firebase`, `/cart/reserve`
6. ห้าม log payment token/password แม้ debug mode
7. ห้ามรัน alembic downgrade / drop table โดยไม่ถาม · ห้าม commit `.env`

---

## New API Checklist (ทุก endpoint ใหม่ — บังคับ ไม่ใช่แค่ happy path)
ทุก API ที่ implement ต่อจากนี้ ต้องทำ 3 ข้อนี้เสมอ (F1 hardening ทำเป็นต้นแบบไว้แล้ว):

1. **Edge-case errors** — ไล่หมวดให้ครบ ไม่ใช่แค่ทางที่ถูก:
   - validation boundary (min/max, byte vs char เช่น bcrypt 72 **bytes**, format/regex)
   - concurrency/race → catch `IntegrityError` แปลงเป็น 409 (ห้ามปล่อยเป็น 500)
   - not-found (404) · already-exists (409) · auth/ownership (401/403)
   - rate-limit (429) · timing/enumeration (login user ไม่มี → verify กับ dummy hash ให้ constant-time)
2. **Auth audit** — ตัดสินทุกเส้น: public หรือ protected
   - protected → ใช้ `Depends(get_current_user)` (`app/api/deps.py`, bearerAuth) + ownership check (Global Rule 3)
   - endpoint ที่ดึง/แก้ข้อมูลของ user เฉพาะราย = protected เสมอ
3. **Tests** — cover edge case ที่คิดในข้อ 1:
   - business logic → unit test (service) · behavior ระดับ HTTP (auth, envelope, ownership, status) → integration test ผ่าน `client` fixture (`tests/conftest.py`)

Error ใหม่เพิ่มใน `app/core/exceptions.py` (subclass `AppError`) ให้ตรง error_code catalog · แล้วอัปเดต `docs/api-contract-f1-f3.md`

---

## วิธีสั่งงาน Claude Code ให้ได้ผลดีที่สุด (อ่านก่อนใช้ prompt ด้านล่าง)

**หลักการ 4 ข้อที่ทำให้ prompt มีประสิทธิภาพ:**
1. **เริ่มด้วย plan mode เสมอ** สำหรับ feature ใหม่ (`claude --permission-mode plan`)
   ให้ Claude สำรวจ + เสนอแผนก่อน แล้วค่อยรีวิว → สลับ acceptEdits
2. **ระบุ layer ที่ต้องสร้างให้ครบ** (model → schema → repository → service → api → test)
   ไม่ปล่อยให้เดา ไม่งั้นมักลืม test หรือข้าม layer
3. **ระบุเงื่อนไข acceptance ชัดเจน** (เช่น "test ต้องครอบ case X") Claude จะเขียน test ตรงเป้า
4. **จบทุก feature ด้วย verification** ก่อนไป feature ถัดไป (ดู checklist ท้ายไฟล์)

**Prompt pattern ที่ดี** = context + scope ครบ layer + acceptance criteria:
```
[อ่าน spec ก่อน] → [สร้างอะไรบ้าง ระบุครบทุก layer] → [test ต้องครอบ case ไหน]
```

---

## Feature Prompt Templates (copy ไปใช้ทีละอัน ตามลำดับ)

### F0 · Core Infrastructure
```
อ่าน CLAUDE.md ก่อน ช่วยวาง core infrastructure (ยังไม่ต้องทำ feature):
1. app/core/config.py — pydantic-settings อ่านจาก .env (DATABASE_URL, JWT_SECRET,
   JWT_ALGORITHM, JWT_ACCESS_EXPIRE_MINUTES, DEBUG)
2. app/core/database.py — async engine + async_session_maker + declarative Base
   + dependency get_db() ที่ yield session พร้อม rollback on error
3. app/core/security.py — hash_password, verify_password, create_access_token,
   create_refresh_token, decode_token
4. alembic init พร้อม config ให้ใช้ async engine + อ่าน DATABASE_URL จาก settings
เริ่มด้วย plan ก่อน แสดง structure ให้ดูก่อนสร้างจริง
```

### F1 · Authentication (spec 1.2)
> ⚠️ **ล้าสมัย — เก็บไว้เป็นบันทึกเท่านั้น.** F1 ถูกย้ายไป Firebase ทั้งหมดแล้ว
> (`POST /auth/firebase` รับ Firebase ID token) · local register/verify-otp/login,
> `users.hashed_password` และตาราง `otp_codes` ถูกถอดออกใน migration `a7c4e91b2d38`
> ดูสถานะจริงที่ `docs/api-contract-f1-f3.md` §6
```
อ่าน docs/movie-poster-app-features-uxpilot.md ข้อ 1.2 ก่อน implement auth ครบ layer:
- models/user.py: id(UUID), email(unique), phone, hashed_password, is_verified, created_at
- schemas/auth.py: RegisterRequest, LoginRequest, OTPVerifyRequest, TokenResponse,
  UserResponse (ห้ามมี hashed_password ใน response)
- repositories/user_repository.py: get_by_email, create, set_verified
- services/auth_service.py: register (hash+สร้าง OTP), verify_otp (rate-limit 5ครั้ง/10นาที),
  login (verify+ออก JWT), refresh_token
- api/v1/auth.py: POST register, login, verify-otp, refresh
- tests/unit/test_auth_service.py
Acceptance: test ต้องครอบ (1) register สำเร็จ (2) login ผิดรหัส 401
(3) OTP เกิน rate-limit โดน block
```

### F2 · Poster Catalog + Detail (spec 1.3-1.5)
```
อ่าน spec ข้อ 1.3-1.5 ก่อน implement ครบ layer:
- models/poster.py: id, title, price, status(available/reserved/sold), is_unique,
  condition_grade, size, era_decade, studio, description, created_at
- schemas/poster.py: PosterListItem, PosterDetailResponse (รวม authenticity/provenance
  ตาม UXPilot prompt 1.5), PosterFilterParams
- repositories/poster_repository.py: list_with_filters (era, condition, price range,
  in_stock_only) + pagination limit/offset, get_by_id
- api/v1/posters.py: GET /posters (query filter), GET /posters/{id} (404 ถ้าไม่มี)
- alembic migration + index บน (status, era_decade, price)
Acceptance: test filter คืนเฉพาะ poster ที่ตรงเงื่อนไข + pagination ถูกต้อง
```

### F3 · Cart & Reservation ⚠️ จุดวิกฤต (spec 1.6 + 4.1)
```
อ่าน spec ข้อ 1.6 และ 4.1 (Race Condition) ให้ละเอียดก่อน implement:
- models/reservation.py: id, poster_id, user_id, status(active/expired/converted),
  expires_at, created_at
- services/reservation_service.py:
  * reserve_poster(poster_id, user_id): เปิด transaction เดียว → SELECT poster
    FOR UPDATE → เช็ค status=='available' ถ้าไม่ใช่ raise 409 Conflict →
    ถ้าใช่ set status='reserved' + สร้าง reservation expires_at=now+15min
  * release_expired(): คืน poster ที่ reservation หมดอายุกลับเป็น available
- api/v1/cart.py: POST /cart/reserve/{poster_id}, DELETE /cart/reservation/{id}
- APScheduler: เรียก release_expired() ทุก 60 วินาที
- tests/integration/test_reservation_concurrency.py
Acceptance (สำคัญที่สุด): จำลอง concurrent 2 request reserve poster เดียวกันพร้อมกัน
ต้องสำเร็จแค่ 1 อีกอันได้ 409 — ต้อง verify ว่าใช้ FOR UPDATE จริง ไม่ใช่แค่เช็ค if
```

### F4 · Checkout & Payment ⚠️ PCI-DSS (spec 1.7-1.8)
```
อ่าน spec ข้อ 1.7-1.8 ก่อน implement — backend รับแค่ payment_token เท่านั้น
ห้ามมี field เลขบัตร/CVV/expiry ในทุก schema เด็ดขาด:
- models/order.py + order_item.py: order(id, user_id, status, total_amount,
  shipping_address_id, created_at), order_item(order_id, poster_id, price_at_purchase)
- schemas/checkout.py: CheckoutRequest(address_id, shipping_method, payment_token),
  OrderResponse
- services/payment_service.py: เรียก Stripe/Omise ด้วย token, verify webhook signature
- services/checkout_service.py: แปลง active reservation → order → เรียก payment →
  ถ้าสำเร็จ set poster='sold' / ถ้าล้มเหลว rollback คืน reservation
- api/v1/checkout.py: POST /checkout, POST /webhooks/payment
Acceptance: test rollback เมื่อ payment fail (poster กลับเป็น reserved ไม่ใช่ sold)
Verify: grep -ri "card_number\|cvv\|expiry" app/ ต้องไม่เจอ
```

### F5 · Order History & Profile (spec 1.9-1.10)
```
อ่าน spec ข้อ 1.9-1.10 ก่อน implement:
- schemas/order.py: OrderListItem, OrderDetailResponse (มี status timeline)
- api/v1/orders.py: GET /orders (เฉพาะของ user login), GET /orders/{id}
- api/v1/profile.py: GET /profile, PATCH /profile, GET /profile/addresses
Acceptance: test ว่า user A เปิด order ของ user B ได้ 403 (ownership check)
```

### F6 · Testing & CI
```
ช่วยสร้าง:
- tests/conftest.py: async test client + test DB session ที่ rollback หลังทุก test
- .github/workflows/test.yml: postgres service container → alembic upgrade head →
  pytest → ruff check → black --check
```

---

## Checklist ก่อนจบแต่ละ feature (ห้ามข้าม)
- [ ] `pytest` ผ่านหมด · `ruff check .` ไม่มี error
- [ ] เปิด `/docs` ทดสอบ endpoint จริง ≥1 รอบ
- [ ] (F3) รัน concurrency test จริง + อ่านโค้ดยืนยัน `FOR UPDATE`
- [ ] (F4) `grep -ri "card_number\|cvv\|expiry" app/` ต้องว่าง
- [ ] (F5) ทุก endpoint ที่ดึงข้อมูล user เช็ค ownership แล้ว
- [ ] commit: `feat(<scope>): <subject>` (scope = ชื่อ feature เช่น auth, reservation) — บน feature branch ตาม Git Workflow ด้านล่าง

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
