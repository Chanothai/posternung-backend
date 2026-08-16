# API Contract — F1–F3 (Poster Nung Backend)

> สรุปภาษาคนของ [`openapi.yaml`](../../workspace/docs/api/openapi.yaml) — spec ฉบับเต็ม (paths/schemas/security) อยู่ในไฟล์นั้น
> ⚠️ contract ย้ายไป `../../workspace/docs/api/openapi.yaml` แล้ว · `docs/openapi.yaml` เหลือเป็น pointer
> Schema ฐานข้อมูลอ้างอิงที่ [`database-design.md`](./database-design.md)
> ขอบเขต: **F1 Authentication · F2 Poster Catalog · F3 Cart & Reservation** (contract-first ก่อนเขียน FastAPI code จริง)

---

## 1. Convention ที่ใช้ทุก endpoint

- **Base path:** `/api/v1`
- **Auth:** `Authorization: Bearer <access_token>` (JWT) — endpoint ที่ต้อง login ระบุไว้ในตารางด้านล่าง
- **Error envelope (ใช้กับทุก 4xx/5xx แบบเดียวกันหมด):**
  ```json
  {
    "error_code": "POSTER_NOT_AVAILABLE",
    "message": "โปสเตอร์นี้ถูกจองหรือขายไปแล้ว",
    "details": null
  }
  ```
  `details` เป็น array ของ `{field, message}` เฉพาะกรณี `422 VALIDATION_ERROR` เท่านั้น นอกนั้นเป็น `null`
- **429 ทุกตัว** ใส่ header `Retry-After` (วินาที) มาด้วย

---

## 2. Endpoint Table

### Auth — `/auth` (public)

| Method | Path | Request body | Success | Error status → code |
|---|---|---|---|---|
| POST | `/auth/refresh` | `refresh_token` | `200` TokenResponse | `401` REFRESH_TOKEN_INVALID |
| POST | `/auth/logout` | `refresh_token` | `204` No Content *(revoke device นี้ — idempotent เสมอ)* | `422` VALIDATION_ERROR |
| POST | `/auth/firebase` | `id_token` (Firebase ID token — email/password, phone-OTP, หรือ Google) | `200` TokenResponse *(find-or-create + auto-login)* | `401` OAUTH_TOKEN_INVALID · `403` OAUTH_EMAIL_NOT_VERIFIED · `409` OAUTH_LOGIN_CONFLICT · `422` VALIDATION_ERROR · `503` OAUTH_PROVIDER_NOT_CONFIGURED |

### Auth (protected) — `/auth` ต้องแนบ `Authorization: Bearer <access_token>`

| Method | Path | Success | Error status → code |
|---|---|---|---|
| GET | `/auth/me` | `200` UserResponse | `401` UNAUTHORIZED (ไม่มี/token ผิด/หมดอายุ/ใช้ refresh แทน access) |

### Posters — `/posters` (public)

| Method | Path | Query params | Success | Error status → code |
|---|---|---|---|---|
| GET | `/posters` | `era_decade?, condition_grade?, min_price?, max_price?, in_stock_only?, limit=20(max100), offset=0` | `200` `{items[], total, limit, offset}` | `422` VALIDATION_ERROR |
| GET | `/posters/{poster_id}` | — | `200` PosterDetailResponse | `404` POSTER_NOT_FOUND |

### Cart — `/cart` ⚠️ ต้อง login (Bearer JWT)

| Method | Path | Success | Error status → code |
|---|---|---|---|
| POST | `/cart/reserve/{poster_id}` | `201` ReservationResponse | `401` UNAUTHORIZED · `404` POSTER_NOT_FOUND · **`409` POSTER_NOT_AVAILABLE** · `429` RESERVE_RATE_LIMITED |
| DELETE | `/cart/reservation/{reservation_id}` | `204` No Content | `401` UNAUTHORIZED · `403` FORBIDDEN · `404` RESERVATION_NOT_FOUND · `409` RESERVATION_NOT_ACTIVE |

---

## 3. Error Code Catalog (รวมทุก endpoint — FE เปิดตารางเดียวจับ error ได้ครบ)

| error_code | HTTP | เกิดที่ endpoint | ความหมาย |
|---|---|---|---|
| `VALIDATION_ERROR` | 422 | ทุก endpoint ที่รับ body/query | field ไม่ผ่าน validation — ดู `details[]` |
| `LOGIN_RATE_LIMITED` | 429 | `POST /auth/firebase` | login ถี่เกินไป (5/นาที ต่อ IP) |
| `REFRESH_TOKEN_INVALID` | 401 | `POST /auth/refresh` | token ผิด/หมดอายุ/ถูก revoke |
| `OAUTH_TOKEN_INVALID` | 401 | `POST /auth/firebase` | Firebase id_token verify ไม่ผ่าน (ผิด/หมดอายุ/audience=project ไม่ตรง) หรือ sign_in_provider ที่ยังไม่รองรับ |
| `OAUTH_EMAIL_NOT_VERIFIED` | 403 | `POST /auth/firebase` | provider password/google บอกว่า email ยังไม่ verified — ปฏิเสธ ไม่ auto-link |
| `OAUTH_LOGIN_CONFLICT` | 409 | `POST /auth/firebase` | แพ้ race ระหว่าง link บัญชี — ให้ client retry (id_token ยังใช้ได้) |
| `OAUTH_PROVIDER_NOT_CONFIGURED` | 503 | `POST /auth/firebase` | ยังไม่ได้ตั้ง `FIREBASE_PROJECT_ID` / service account บน environment นี้ |
| `POSTER_NOT_FOUND` | 404 | `GET /posters/{id}`, `POST /cart/reserve/{id}` | ไม่มีโปสเตอร์นี้ **หรือมีแต่ยังไม่ถูกเปิดขาย** (`published_at IS NULL` — ADR-0013 D2) ใบที่ยังไม่ publish ถูกซ่อนทั้งจาก list และ detail และตอบรหัสเดียวกับใบที่ไม่มีอยู่จริง (ไม่แยกรหัส เพราะการแยกจะยืนยันให้คนไล่เดา id ได้ว่าแถวนี้มีอยู่) · ใบที่ไม่มี `condition_grade` เข้าเคสนี้เสมอเพราะ publish ไม่ได้เลยตาม CHECK ของ ADR-0013 D3 (BR-05) · 🔴 ใบที่ `status = sold` แต่ publish แล้ว **ไม่ใช่** เคสนี้ — ตอบ 200 พร้อม `status: sold` (ADR-0013 D6 · ADR-0005 D5 · SCR-05 AC-5) |
| `POSTER_NOT_PUBLISHABLE` | 409 | — (**ยังไม่มี endpoint ไหนใช้**) | จองรหัสไว้ให้ `poster_service.assert_publishable()` ซึ่งเป็น guard ก่อนเขียน `published_at` ตอน `condition_grade` เป็น NULL (BR-05) · ADR-0013 D4 ตั้งใจไม่มี writer ของ `published_at` ในรอบนี้ guard จึงยังไม่มี call site — จะมีตอน INF-11 (เส้นทางเปิดขาย) · กฎเดียวกันถูกบังคับที่ระดับ DB แล้วด้วย CHECK `ck_posters_published_requires_condition_grade` |
| `UNAUTHORIZED` | 401 | ทุก endpoint ที่ต้อง login | ไม่มี/token ผิด |
| **`POSTER_NOT_AVAILABLE`** | **409** | `POST /cart/reserve/{id}` (F3 — ยังไม่มีโค้ด) · `poster_service.mark_sold()` (ADR-0025 · INF-24, **ไม่มี endpoint** — เรียกได้จาก CLI operator เท่านั้น) | **โปสเตอร์ `status` ไม่ใช่ `available`** — ที่ `/cart/reserve/{id}` คือผลตรงของ concurrency defense (`FOR UPDATE`) ที่ `mark_sold()` คือขายซ้ำ/ขายใบที่กำลังจองอยู่ |
| `RESERVE_RATE_LIMITED` | 429 | `POST /cart/reserve/{id}` | จองถี่เกินไป |
| `FORBIDDEN` | 403 | `DELETE /cart/reservation/{id}` | ไม่ใช่เจ้าของ reservation (ownership check) |
| `RESERVATION_NOT_FOUND` | 404 | `DELETE /cart/reservation/{id}` | ไม่มี reservation นี้ |
| `RESERVATION_NOT_ACTIVE` | 409 | `DELETE /cart/reservation/{id}` | ยกเลิกซ้ำ/หมดอายุ/converted ไปแล้ว |
| **`POSTER_HAS_ACTIVE_RESERVATION`** | **409** | — (**ยังไม่มี endpoint ไหนใช้**) · `poster_service.mark_sold()` (ADR-0025 D3 · INF-24) | มี reservation ที่ยัง `active` อยู่บนโปสเตอร์นี้ — `mark_sold()` ปฏิเสธทั้งรายการเสมอ ไม่มี `--force` (มีลูกค้าค้างกลางทางจ่ายเงินที่คืนเงินอัตโนมัติไม่ได้ — ADR-0002) `details` มี `reservation_id` ให้คนไปตัดสินเอง |
| **`POSTER_HAS_PENDING_CHARGE`** | **409** | — (**ยังไม่มี endpoint ไหนใช้ — ไม่มีทาง raise จริงวันนี้**) · จองไว้ให้ `poster_service._pending_charge_for()` (ADR-0025 · INF-24) | charge ที่ยัง `pending` ต้องยืนยันกับ Omise ก่อนตัดสินใจ (`stock-integrity` ข้อ 7 · ADR-0002) — วันนี้ไม่มีตาราง `payments` เลย จองรหัสไว้ล่วงหน้าให้ `SCR-06` แทนการใช้ `POSTER_NOT_AVAILABLE` ผิดความหมาย |
| **`POSTER_SOLD_REASON_REQUIRED`** | **422** | — (**ยังไม่มี endpoint ไหนใช้**) · `poster_service.mark_sold()` (ADR-0025 D1 ข้อ 3 · INF-24) | `reason` ว่าง/เป็นช่องว่างล้วน — การขายนอกระบบไม่มี event ให้เชื่อ นอกจากคำของคน จึงบังคับเหตุผลเสมอ |

รวม **18 error_code**

---

## 3.5 `mark_sold()` (ADR-0025 · INF-24) — error_code ที่ยังไม่ผ่าน HTTP

🔴 **`POSTER_NOT_AVAILABLE`/`POSTER_HAS_ACTIVE_RESERVATION` สองแถวข้างบนถูก `raise` จริง
เป็นครั้งแรกโดย `poster_service.mark_sold()` ไม่ใช่โดย endpoint ใด** — Phase 1 ไม่มี
admin auth (`security-baseline` §3) จึงห้ามเปิด endpoint สำหรับเส้นทางนี้ (INF-24 AC-7)
ทางเรียกวันนี้คือ `scripts/seed/sold_entry.py` (CLI operator) เท่านั้น ซึ่งจับ `AppError`
แล้วพิมพ์ `exc.message`/`exc.details` ออก stderr ไม่ได้ผ่าน JSON error envelope ของ
ข้อ 1 เลย — ตารางข้อ 3 ยังคงรายการนี้ไว้เพราะ `error_code` ถูกจองมาตั้งแต่ F3
(`POSTER_NOT_AVAILABLE`) หรือถูกจองใหม่ไว้ล่วงหน้าให้ F3/SCR-06 ใช้ต่อ (`POSTER_HAS_ACTIVE_RESERVATION`)
เมื่อมี endpoint จริงในรอบถัดไป

---

## 4. จุดวิกฤต — `409 POSTER_NOT_AVAILABLE`

`POST /cart/reserve/{poster_id}` คือ endpoint ที่แปลง race-condition defense จาก [`database-design.md` §6](./database-design.md#6-race-condition-strategy-f3--หัวใจของ-design) เป็น HTTP contract โดยตรง:

1. Service เปิด transaction เดียว → `SELECT status FROM posters WHERE id=:id FOR UPDATE`
2. ถ้า `status != 'available'` → rollback → คืน **409 POSTER_NOT_AVAILABLE**
3. ถ้า available → update เป็น `reserved` + insert `reservations` (status=`active`, expires_at=+15min) → คืน **201**

**Acceptance test ที่ต้องมี (ตาม CLAUDE.md F3):** ยิง `POST /cart/reserve/{poster_id}` พร้อมกัน 2 request (คนละ user) ไปยัง poster เดียวกัน → ต้องได้ `201` แค่ 1 ฝั่ง อีกฝั่งได้ `409 POSTER_NOT_AVAILABLE` เท่านั้น (ห้ามได้ `500` จาก unique-violation ที่ไม่ได้ catch — DB partial unique index เป็นแค่ safety net ชั้นที่ 2 ไม่ใช่ error path หลัก)

---

## 5. Rate-limit — `429 LOGIN_RATE_LIMITED`

`POST /auth/firebase` จำกัด **5 ครั้ง/นาที ต่อ IP** (slowapi) — เกินแล้วคืน `429 LOGIN_RATE_LIMITED` พร้อม `Retry-After` header

> **OTP ไม่ใช่ความรับผิดชอบของ backend แล้ว** — SMS OTP ของ Phone Auth ส่ง/ตรวจที่ Firebase ทั้งหมด (rate-limit + lockout เป็นของ Firebase) backend เห็นแค่ ID token ที่ผ่าน verify มาแล้ว

---

## 6. จุดวิกฤต — `POST /auth/firebase` unified Firebase login + account linking

> `/auth/google` (deprecated alias เดิม) ถูกถอดออกแล้ว — ใช้ `/auth/firebase` เท่านั้น

- **Endpoint เดียวรองรับทุก provider** — client sign-in ผ่าน Firebase Auth (email/password, phone SMS-OTP, หรือ Google) แล้วส่ง **Firebase ID token** (`getIdToken()`) มา; backend อ่าน claim **`firebase.sign_in_provider`** เพื่อแยกจัดการ (map: `password`→`password`, `google.com`→`google`, `phone`→`phone`; provider อื่น → `401 OAUTH_TOKEN_INVALID`)
- **Verify แบบ Firebase** — verify ด้วย **`firebase-admin` SDK** (`firebase_admin.auth.verify_id_token(..., check_revoked=True)`) — ต้องตั้ง `FIREBASE_PROJECT_ID` (`posternung` ทุก env, public) **และ service account credential** (secret — ได้จาก Firebase console) · ตั้ง credential ได้ 2 ทาง (PATH มาก่อน): **prod แนะนำ `FIREBASE_SERVICE_ACCOUNT_PATH`** (path ไปยังไฟล์ JSON ที่ read-only bind-mount เข้า container — key ไม่อยู่ใน env จึงไม่โผล่ใน `docker inspect`/env dump) · **dev/test ใช้ `FIREBASE_SERVICE_ACCOUNT_JSON`** (เนื้อ JSON ทั้งก้อนใน env var) · `check_revoked=True` reject token ที่ถูก revoke หรือ user ถูก disable
- **`password` / `google.com`** — ต้องมี `email` + `email_verified=true` (ไม่งั้น `403 OAUTH_EMAIL_NOT_VERIFIED`); auto-link เข้า user เดิมที่ email ตรงกันได้ (สร้าง User มี email) — กัน email มั่วมาผูกกับบัญชีคนอื่น
- **`phone`** — SMS OTP ยืนยันโดย Firebase แล้ว (token = ยืนยันสำเร็จ) จึง **ไม่บังคับ `email_verified`** → phone login **ไม่มีทางโดน `403 OAUTH_EMAIL_NOT_VERIFIED`**; ต้องมี claim `phone_number` เสมอ (ไม่มี = `401`, กันสร้าง user ที่ระบุตัวตนไม่ได้) · **`email` ที่ติดมากับ token จะถูกใช้ก็ต่อเมื่อ `email_verified=true`** (Firebase ใส่ claim ตามที่ user record มี ไม่ขึ้นกับ provider ที่ sign in รอบนั้น) → บัญชีที่ผูกทั้งเบอร์และ email จะ **link เข้า user row เดิม ไม่แตกเป็น 2 ใบ** และเบอร์จะถูกเติมลง row เดิมที่ยังว่าง · email ที่ยังไม่ verified → ละทิ้งเฉยๆ (User ได้ `email=NULL`) ไม่บล็อก login · **จับคู่บัญชีด้วย Firebase `uid` เท่านั้น ไม่ auto-link ด้วยเบอร์** (เบอร์ถูก telco recycle ได้ → กัน account takeover) · OTP ของ phone auth ส่ง/verify ที่ Firebase ทั้งหมด — **backend เราไม่ได้ส่ง SMS เอง**
- **`users.email` เป็น nullable** (migration `f1b2a3c4d5e6`) — รองรับ phone-only user · unique constraint บน nullable email = Postgres ยอมหลาย `NULL` ได้
- **`oauth_identities` แยกตาราง** จาก `users` — `provider_user_id` = **Firebase `uid`** (`sub` claim) เป็น key ที่เสถียรต่อ user ใน project ไม่ใช้ email เป็น key เพราะเปลี่ยนได้ · ถ้ายังไม่ verify มาก่อน จะ auto-verify ให้ทันที
- **Account linking — จับคู่ user เดิมตามลำดับความน่าเชื่อถือ 2 ชั้น** (ดู `firebase_login()`):
  1. **Firebase `uid` เดียวกันแต่คนละ provider** → Firebase ยืนยันเองว่าเป็นบัญชีเดียวกัน (เกิดเมื่อ client เรียก `linkWithCredential()` ผูก sign-in method เพิ่มเข้าบัญชีเดิม — uid ไม่เปลี่ยน) เป็นสัญญาณที่**แข็งแรงที่สุด มาก่อนเสมอ** · รองรับด้วย index `ix_oauth_identities_provider_user_id` (unique constraint `(provider, provider_user_id)` ใช้ค้นด้วยคอลัมน์หลังเดี่ยวๆ ไม่ได้)
  2. **email ที่ `email_verified=true` ตรงกัน** → ใช้เมื่อ uid ยังไม่เคยเห็น (คนละบัญชี Firebase แต่ email เดียวกัน)
  · เจอ user เดิมแล้วจะ **backfill `phone`/`email` ที่ยังว่าง** จาก token (ไม่ทับของเดิม · ถ้า email นั้นมี row อื่นถืออยู่แล้วจะปล่อยว่างไว้ ไม่ยัดจนชน unique)
  · ⚠️ **ฝั่ง mobile ต้องใช้ `linkWithCredential()`** ตอนผู้ใช้เพิ่มวิธี sign-in ใหม่ ไม่ใช่ `signInWith…` เฉยๆ ไม่งั้น Firebase สร้าง**บัญชีใหม่คนละ uid** ซึ่ง backend ไม่มีทางรู้ว่าเป็นคนเดียวกัน (และไม่ควรเดา)
- **Race condition** (สอง request login account เดียวกันครั้งแรกพร้อมกัน) ป้องกันด้วย `session.begin_nested()` (savepoint) + `IntegrityError` handling — ถ้าแพ้ race จะ retry อ่าน identity ที่อีกฝั่งสร้างไว้ก่อน ถ้ายังหาไม่เจอ (กรณีที่แปลกมาก) คืน `409 OAUTH_LOGIN_CONFLICT` ให้ client เรียกซ้ำ (id_token ยังใช้ได้ไม่กี่นาที)
- **ไม่มี local password/OTP แล้ว** — `users.hashed_password` และตาราง `otp_codes` ถูก drop ใน migration `a7c4e91b2d38`; endpoint `/auth/register`, `/auth/verify-otp`, `/auth/login` ถูกถอดออก (sign-in ทุกวิธีทำที่ Firebase ฝั่ง client)
- **`OAuthProvider` enum** = `google` · `password` · `phone` (migration `f1b2a3c4d5e6` เพิ่ม 2 ค่าหลังด้วย recreate-type ให้ downgrade กลับได้) · **หมายเหตุ:** ทุก env ใช้ Firebase project เดียว → token จาก app คนละ env verify ผ่าน backend ทุก env (แยก env จาก token ไม่ได้ ถ้าต้องการแยกต้องแยก Firebase project)
- **Platform-agnostic (ยืนยันแล้วด้วยไฟล์ config จริงทั้ง iOS + Android)** — `verify_id_token` เช็คแค่ `aud`/`iss` ระดับ **project** เท่านั้น ไม่แตะ platform-specific field ใดๆ (OAuth client_id, api_key, package/bundle id) ที่อยู่ใน `GoogleService-Info.plist`/`google-services.json` — field พวกนั้นฝั่ง mobile SDK ใช้คุยกับ Google/Firebase เองก่อนได้ token มา backend ไม่เกี่ยว ตรวจแล้ว Android `google-services.json` ทั้ง 3 env มี `project_id: "posternung"` ตรงกับ iOS เป๊ะ (project เดียวกัน) → **endpoint เดิมรองรับ Android ได้ทันทีโดยไม่ต้องแก้โค้ดฝั่ง backend เลย**

---

## 6.5 `POST /auth/logout` — ข้อจำกัดที่ mobile ต้องรู้

- **Revoke ได้แค่ device เดียว** (token ที่ส่งมา) — ไม่มี "logout all devices" ในเวอร์ชันนี้
- **Idempotent เสมอ → `204`** ไม่ว่า token จะไม่เคยมีจริง/หมดอายุ/ถูก revoke ไปแล้วก็ตาม (แนวทาง RFC 7009 — ไม่ leak ว่า token ไหนมีจริงในระบบ) ไม่ต้องแนบ `Authorization` header — การถือ refresh token คือหลักฐานในตัวเองอยู่แล้ว
- **⚠️ Revoke access token ไม่ได้** — เป็น stateless JWT (อายุ 30 นาที ตาม `JWT_ACCESS_EXPIRE_MINUTES`) backend ไม่มี record ให้เช็ค ต่อให้ logout แล้ว access token ใบเดิมยังเรียก endpoint อื่นได้จนกว่าจะหมดอายุเอง — ไม่ใช่บั๊ก เป็นข้อจำกัดมาตรฐานของ JWT (ถ้าต้อง revoke ทันทีจริงต้องทำ denylist แลกกับ DB lookup ทุก request — ยังไม่อยู่ในสโคป)
- **ไม่แตะ Firebase session เลย** — client ต้องเรียก `FirebaseAuth.signOut()` (iOS/Android/Web SDK) เอง + เคลียร์ token ที่เก็บไว้ใน secure storage (Keychain/Keystore) ด้วยตัวเอง ไม่ใช่หน้าที่ backend

---

## 7. Schema สรุป (รายละเอียดเต็มใน `../../workspace/docs/api/openapi.yaml` → `components.schemas`)

- **Request:** `FirebaseLoginRequest`, `RefreshRequest`, `LogoutRequest`
- **Response:** `UserResponse` (ไม่มี field อ่อนไหว), `TokenResponse`, `PosterListItem`, `PosterDetailResponse` (extends `PosterListItem` + authenticity/provenance/images), `PaginatedPosterList`, `ReservationResponse`
- **Error:** `ErrorResponse{error_code, message, details}`, `ValidationErrorDetail{field, message}`
- **Enum ที่ใช้ตรงกับ `database-design.md`:** `PosterStatus`, `ReservationStatus`, `PosterCondition`, `OAuthProvider`

---

## 8. Verification checklist

- [ ] Lint contract ผ่าน (`npx @redocly/cli lint ../workspace/docs/api/openapi.yaml` หรือ validator อื่น)
- [ ] เปิด spec ใน Swagger Editor / VS Code OpenAPI preview — ทุก path มี response ตรงตามตารางข้อ 2
- [ ] `409 POSTER_NOT_AVAILABLE` และ `429 LOGIN_RATE_LIMITED` มี error_code แยกกันชัดเจนตามข้อ 4–5
- [ ] เทียบ field ใน schema กับ `database-design.md` ตรงกัน (โดยเฉพาะ enum `condition_grade`/`poster_condition`)
- [ ] ไม่มี field รหัสผ่าน/บัตร/CVV หลุดเข้า response schema ใดๆ
