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

### Orders — `/listings/{poster_id}/reserve` · `/orders` ⚠️ ต้อง login (Bearer JWT)

🔴 **‹แก้ 2026-09-15 · SCR-07 สไลซ์ A (ADR-0037)› `/cart/*` ถูกถอดออกจากสัญญาแล้ว**
(`ADR-0030` D1 — ไม่มีตะกร้าในระบบ) **แถวสองแถวข้างล่างของตารางเดิมที่นี่เคยอยู่
(`POST /cart/reserve/{poster_id}` · `DELETE /cart/reservation/{id}`) ไม่มีอยู่จริง
ในสัญญาอีกแล้ว** — "ซื้อเลย" คือจองทันทีผ่านเส้นด้านล่างนี้แทน และ **ไม่มีเส้นยกเลิก
การจองใน Beta** (`ADR-0037` D2 — ยกเลิก = ปล่อยหมดอายุ)

| Method | Path | Success | Error status → code |
|---|---|---|---|
| POST | `/listings/{poster_id}/reserve` (ไม่มี request body) | `201` ReservationResponse (แถวใหม่) · **`200` ReservationResponse (แถว active เดิมของผู้เรียกเอง — idempotent ต่อ (buyer, poster) · ไม่ต่อ TTL · ADR-0037 A5-D1)** | `401` UNAUTHORIZED · `403` BUYER_IS_SELLER · `404` POSTER_NOT_FOUND · **`409` POSTER_NOT_AVAILABLE / BUYER_HAS_LIVE_ORDER / POSTER_ALREADY_RESERVED / RESERVATION_LIMIT_EXCEEDED** · `429` RESERVE_RATE_LIMITED |
| POST | `/orders` (`reservation_id` · `shipping_address` 7 ฟิลด์ inline — ไม่มีสมุดที่อยู่) | `201` OrderResponse | `401` UNAUTHORIZED · `403` BUYER_IS_SELLER · `404` RESERVATION_NOT_FOUND · **`409` RESERVATION_NOT_ACTIVE / POSTER_NOT_AVAILABLE** · `422` VALIDATION_ERROR |

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
| `POSTER_NOT_FOUND` | 404 | `GET /posters/{id}` · `POST /listings/{id}/reserve` (ครอบ 3 เคส: ไม่มีจริง · `published_at IS NULL` · `approved_at IS NULL` — ไม่แยกรหัส ADR-0037) | ไม่มีโปสเตอร์นี้ **หรือมีแต่ยังไม่ถูกเปิดขาย** (`published_at IS NULL` — ADR-0013 D2) ใบที่ยังไม่ publish ถูกซ่อนทั้งจาก list และ detail และตอบรหัสเดียวกับใบที่ไม่มีอยู่จริง (ไม่แยกรหัส เพราะการแยกจะยืนยันให้คนไล่เดา id ได้ว่าแถวนี้มีอยู่) · ใบที่ไม่มี `condition_grade` เข้าเคสนี้เสมอเพราะ publish ไม่ได้เลยตาม CHECK ของ ADR-0013 D3 (BR-05) · 🔴 ใบที่ `status = sold` แต่ publish แล้ว **ไม่ใช่** เคสนี้ — ตอบ 200 พร้อม `status: sold` (ADR-0013 D6 · ADR-0005 D5 · SCR-05 AC-5) |
| `POSTER_NOT_PUBLISHABLE` | 409 | — (**ยังไม่มี endpoint ไหนใช้**) | จองรหัสไว้ให้ `poster_service.assert_publishable()` ซึ่งเป็น guard ก่อนเขียน `published_at` ตอน `condition_grade` เป็น NULL (BR-05) · ADR-0013 D4 ตั้งใจไม่มี writer ของ `published_at` ในรอบนี้ guard จึงยังไม่มี call site — จะมีตอน INF-11 (เส้นทางเปิดขาย) · กฎเดียวกันถูกบังคับที่ระดับ DB แล้วด้วย CHECK `ck_posters_published_requires_condition_grade` |
| `UNAUTHORIZED` | 401 | ทุก endpoint ที่ต้อง login | ไม่มี/token ผิด |
| **`POSTER_NOT_AVAILABLE`** | **409** | `POST /listings/{id}/reserve` (`details[].reserved_until` ISO-8601 ถ้ามี active reservation **ของคนอื่น** อยู่ — ADR-0037 D4 · ถ้าผู้ถือคือผู้เรียกเองเส้นนี้ตอบ `200` แทน (A5-D1) · ถ้าไม่มีแถว active แล้ว (converted/sold) **ไม่มี `details`** — และถ้าออร์เดอร์ที่ยังไม่จบเป็นของผู้เรียกเองจะได้ `BUYER_HAS_LIVE_ORDER` แทน (A5-D4)) · `POST /orders` (ชั้นที่ 3 `uq_live_order_per_poster`) · `poster_service.mark_sold()` (ADR-0025 · INF-24, **ไม่มี endpoint** — เรียกได้จาก CLI operator เท่านั้น) | **โปสเตอร์ `status` ไม่ใช่ `available`** — ผลตรงของ concurrency defense (`FOR UPDATE`) |
| **`BUYER_HAS_LIVE_ORDER`** | **409** | `POST /listings/{id}/reserve` (`order_service.reserve_listing()` — ADR-0037 **A5-D4**) | ใบนี้มี**ออร์เดอร์ที่ยังไม่จบของผู้เรียกเอง** (`status NOT IN TERMINAL_ORDER_STATUSES` — ชุดเดียวกับ `uq_live_order_per_poster` · reservation ถูก `converted` ไปแล้วจึงไม่มี `reserved_until` ให้บอก) ⇒ ไม่ต้องจองซ้ำ ให้ไปชำระเงินของออร์เดอร์เดิม · `details[]` = `[{field: "order_no", message: "PN-YYMMDD-NNNN"}]` (ค่าเครื่องตาม A2-D2) · 🔴 **ตอบเฉพาะผู้ซื้อคนเดิม** — คนอื่นได้ `POSTER_NOT_AVAILABLE` เปล่า ๆ เพราะ `order_no` ของคนอื่นเป็นข้อมูลธุรกรรม (security-baseline §5) |
| `RESERVE_RATE_LIMITED` | 429 | `POST /listings/{id}/reserve` | จองถี่เกินไป — คีย์ด้วย `user_id` ไม่ใช่ IP (ADR-0037 D6) |
| `RESERVATION_NOT_FOUND` | 404 | `POST /orders` | ไม่มี reservation นี้ · 🔴 **ครอบเคส "เป็นของผู้ใช้คนอื่น" ด้วย** — ตอบรหัสเดียวกันโดยตั้งใจ ไม่แยก 403 เพราะการแยกจะยืนยันให้คนไล่เดา id ได้ว่าแถวนี้มีอยู่จริง (หลักเดียวกับ `POSTER_NOT_FOUND`) |
| `RESERVATION_NOT_ACTIVE` | 409 | `POST /orders` | หมดอายุ/converted ไปแล้ว — ครอบทั้งแถวที่ `status` ไม่ใช่ `active` และแถวที่ `expires_at` เลยเวลาแล้ว |
| **`POSTER_HAS_ACTIVE_RESERVATION`** | **409** | — (**ยังไม่มี endpoint ไหนใช้**) · `poster_service.mark_sold()` (ADR-0025 D3 · INF-24) | มี reservation ที่ยัง `active` อยู่บนโปสเตอร์นี้ — `mark_sold()` ปฏิเสธทั้งรายการเสมอ ไม่มี `--force` (มีลูกค้าค้างกลางทางจ่ายเงินที่คืนเงินอัตโนมัติไม่ได้ — ADR-0002) `details` มี `reservation_id` ให้คนไปตัดสินเอง |
| **`POSTER_HAS_PENDING_CHARGE`** | **409** | — (**ยังไม่มี endpoint ไหนใช้ — ไม่มีทาง raise จริงวันนี้**) · จองไว้ให้ `poster_service._pending_charge_for()` (ADR-0025 · INF-24) | charge ที่ยัง `pending` ต้องยืนยันกับ Omise ก่อนตัดสินใจ (`stock-integrity` ข้อ 7 · ADR-0002) — วันนี้ไม่มีตาราง `payments` เลย จองรหัสไว้ล่วงหน้าให้ `SCR-06` แทนการใช้ `POSTER_NOT_AVAILABLE` ผิดความหมาย |
| **`POSTER_SOLD_REASON_REQUIRED`** | **422** | — (**ยังไม่มี endpoint ไหนใช้**) · `poster_service.mark_sold()` (ADR-0025 D1 ข้อ 3 · INF-24) | `reason` ว่าง/เป็นช่องว่างล้วน — การขายนอกระบบไม่มี event ให้เชื่อ นอกจากคำของคน จึงบังคับเหตุผลเสมอ |
| **`ADMIN_REQUIRED`** | **403** | ทุก endpoint ใต้ `/admin` (ADR-0031 D2 — ผูกที่ `APIRouter` ไม่ใช่รายเส้น) | ล็อกอินแล้วแต่ `users.is_admin` ไม่เป็นจริง — ครอบทั้ง `false` และ `null` (🔴 อ่านสิทธิ์ไม่ได้ ≠ มีสิทธิ์ · ADR-0031 D3) · **ตอบรหัสเดียวกันทุกกรณี ไม่แยก 404** เพราะทั้ง router เป็นของแอดมินล้วน ไม่มี ownership รายแถว (D7) · ส่วนกรณีพิสูจน์ตัวตนไม่ได้เลยเป็น `UNAUTHORIZED` 401 ไม่ใช่รหัสนี้ |
| **`BUYER_IS_SELLER`** | **403** | `POST /listings/{id}/reserve` · `POST /orders` (`order_service.assert_buyer_is_not_seller()` — ADR-0033 OD-1 · INF-33) | ผู้ซื้อกับผู้ขายเป็นคนเดียวกัน · เทียบ `seller_profiles.user_id` กับ `buyer_id` **ไม่ใช่** `posters.seller_id` (proposal §9.1 — CHECK เดิมเทียบ id คนละตารางจึงไม่เคยจับอะไรได้) · ด่านอยู่ **ทั้งสองเส้น** เพราะ BR-B1 ทำให้ "ซื้อเลย" = จองก่อน |
| **`RESERVATION_LIMIT_EXCEEDED`** | **409** | `POST /listings/{id}/reserve` (`order_service.reserve_listing()`) | ผู้ใช้มี active reservation ครบเพดานแล้ว — เพดานอ่านจาก `platform_settings.max_active_reservations_per_user` (ADR-0033 OD-3) 🔴 **ไม่ใช่ rate-limit** ซึ่งเป็น 429 คนละเส้นกัน · `details[]` = `[{field: "limit", message: "<int>"}]` (ADR-0037 Amendment 2) |
| **`POSTER_ALREADY_RESERVED`** | **409** | `POST /listings/{id}/reserve` (`order_service.reserve_listing()`) | ชั้นที่ 2 ของการกันซื้อซ้อน (`uq_active_reservation_per_poster`) จับได้ — ไม่มีทางถึงถ้า `FOR UPDATE` ทำงานถูกต้อง แต่ต้องมีเพราะ `IntegrityError` ดิบ = 500 |
| **`ORDER_NOT_FOUND`** | **404** | — (**ยังไม่มี endpoint ไหนใช้**) · `order_service.apply_order_transition()` | ไม่มีออร์เดอร์ id นั้น |
| **`ORDER_TRANSITION_NOT_ALLOWED`** | **409** | — (**ยังไม่มี endpoint ไหนใช้**) · `order_service.apply_order_transition()` (INF-33 AC-1) | เส้นที่ขอไม่มีในตารางกฎของ `app/core/state_machine.py` · `details` บอก `from_status`/`to_status` |
| **`LISTING_TRANSITION_NOT_ALLOWED`** | **409** | — (**ยังไม่มี endpoint ไหนใช้**) · `poster_service.apply_listing_transition()` · `poster_service.mark_sold_by_order()` (INF-33 AC-1 · AC-4 สไลซ์ B) | เส้นที่ขอไม่มีในตารางกฎ **หรือ** แถวนั้นยังขาดเงื่อนไขของ CHECK ระดับ DB (`approved_at` · `rejection_reason`) **หรือ** ปลายทางเป็น `sold` ที่เรียกผ่าน `apply_listing_transition()` ตรง ๆ ซึ่งต้องผ่าน `mark_sold()`/`mark_sold_by_order()` แทนเพราะต้องเขียน `sold_at` พร้อมกัน (ADR-0025 D1 · A1-D1) **หรือ** `mark_sold_by_order()` เรียกกับใบที่ `status` ไม่ใช่ `reserved` |
| **`ORDER_CANCELLATION_REASON_REQUIRED`** | **422** | — (**ยังไม่มี endpoint ไหนใช้**) · `order_service.apply_order_transition()` | ไป `CANCELLED`/`REFUNDED` โดยไม่มีเหตุผล — ถ้าไม่ตรวจก่อน `flush()` `ck_orders_cancelled_requires_reason` จะกลายเป็น 500 (ท่าเดียวกับ `POSTER_SOLD_REASON_REQUIRED`) |
| **`SELLER_PROFILE_NOT_FOUND`** | **500** | — (**ไม่มีทางเกิดตราบใดที่ FK ยังอยู่**) · `order_service` · `poster_service.apply_listing_transition()` | `posters.seller_id` ชี้แถวที่ไม่มีอยู่ — มีไว้เพื่อล้มเสียงดัง ไม่ใช่เดินต่อเงียบ ๆ |
| **`PLATFORM_SETTING_MISSING`** | **500** | — (**ยังไม่มี endpoint ไหนใช้**) · `platform_setting_repository.get_int()` | คีย์ใน `platform_settings` หายไปหรืออ่านเป็นตัวเลขไม่ได้ 🔴 **ห้ามมี default ในโค้ด** — fallback เงียบ ๆ = แก้ config แล้วระบบไม่เปลี่ยนตามโดยไม่มีใครรู้ |
| **`POSTER_SALE_ORDER_MISMATCH`** | **500** | — (**ไม่มีทาง raise จริงจากเส้นทางปกติวันนี้**) · `poster_service.mark_sold_by_order()` (ADR-0025 Amendment 1 A1-D2 ข้อ 3 · INF-33 AC-4 สไลซ์ B) | ออร์เดอร์ที่ `order_service.apply_order_transition()` ส่งมา**ไม่ใช่ของโปสเตอร์ใบนี้** หรือ**ยัง `status` ไม่ใช่ `COMPLETED`** — ผู้เรียกเดียววันนี้คือประตูของเครื่อง order เองหลัง `flush()` สถานะ `COMPLETED` แล้ว จึงล้มเสียงดังแทนเดินต่อเงียบ ๆ ถ้าวันหน้ามี call site ที่เรียกผิด (ทรงเดียวกับ `SELLER_PROFILE_NOT_FOUND`) |
| **`BANK_STATEMENT_NOT_CHECKED`** | **409** | — (**ยังไม่มี endpoint ไหนใช้**) · `order_service.verify_payment()` (INF-41 สไลซ์ A · SCR-15 AC-3) | เรียก `verify-payment` โดยไม่ยืนยันว่าเห็นยอดในบัญชีจริง — สลิปเป็นแค่การอ้าง (ADR-0029 D3) ปฏิเสธ**ก่อนเปิด lock/flush ใด ๆ** ผู้เรียกวันนี้คือ `scripts/orders/order_ops.py verify-payment` เท่านั้น |
| **`PAYMENT_NOT_CLAIMED`** | **409** | — (**ยังไม่มี endpoint ไหนใช้**) · `order_service.verify_payment()` (INF-41 สไลซ์ A) | ไม่พบแถว `payments` ที่ `status == CLAIMED` ของออร์เดอร์นี้ — ยังไม่มีใครแจ้งโอน หรือรันซ้ำหลังยืนยันไปแล้ว (แถวขยับเป็น `VERIFIED` แล้ว) |
| **`PAYMENT_REJECTION_REASON_REQUIRED`** | **400** | — (**ยังไม่มี call site — จองรหัสไว้ให้สไลซ์ B**) · `order_service.reject_payment()` (ยังไม่ลง — รอ ADR-0033 Amendment 2) | เหตุผลปฏิเสธสลิปว่าง — BR-P10 บังคับเหตุผลเสมอ |
| **`TRACKING_NO_REQUIRED`** | **400** | — (**ยังไม่มี endpoint ไหนใช้**) · `order_service.ship_order()` (INF-41 สไลซ์ A · AC-4) | `--tracking-no` ว่าง/whitespace ล้วน — ปฏิเสธก่อนเขียนอะไรเลย ผู้เรียกวันนี้คือ `scripts/orders/order_ops.py ship` เท่านั้น |

รวม **33 error_code** ‹แก้ 2026-09-18 · INF-41 สไลซ์ A — เพิ่ม `BANK_STATEMENT_NOT_CHECKED` ·
`PAYMENT_NOT_CLAIMED` · `PAYMENT_REJECTION_REASON_REQUIRED` (จองไว้ให้สไลซ์ B ที่ยังไม่ลง) ·
`TRACKING_NO_REQUIRED` — ไม่มี endpoint ไหนใช้เลยสักตัว ผู้เรียกวันนี้คือ
`scripts/orders/order_ops.py` เท่านั้น›
‹แก้ 2026-09-17 · INF-33 สไลซ์ B — เพิ่ม `POSTER_SALE_ORDER_MISMATCH`
(ADR-0025 Amendment 1 A1-D2 ข้อ 3)›
‹แก้ 2026-09-17 · SCR-07 รอบ A5 — เพิ่ม `BUYER_HAS_LIVE_ORDER` (ADR-0037 A5-D4)›
‹แก้ 2026-09-15 · SCR-07 สไลซ์ A — ลบแถว `FORBIDDEN` ที่ผูกกับ
`DELETE /cart/reservation/{id}` ซึ่งไม่มีอยู่ในสัญญาแล้ว (ADR-0030 D1 · ADR-0037 D2)
และไม่มี call site ไหนใน `app/` raise error_code นี้เลย›

---

## 3.5 `mark_sold()` (ADR-0025 · INF-24) — error_code ที่ยังไม่ผ่าน HTTP

🔴 **`POSTER_NOT_AVAILABLE`/`POSTER_HAS_ACTIVE_RESERVATION` สองแถวข้างบนถูก `raise` จริง
เป็นครั้งแรกโดย `poster_service.mark_sold()` ไม่ใช่โดย endpoint ใด** — **ยังห้ามเปิด
endpoint สำหรับเส้นทางนี้ (INF-24 AC-7)**
⚠️ ‹แก้ 2026-08-25 · INF-35› **เหตุผลเดิมหมดอายุแล้ว ข้อห้ามไม่ได้หมดอายุ** — ถ้อยคำเดิม
บอกว่าห้ามเพราะ "Phase 1 ไม่มี admin auth" ซึ่งไม่จริงอีกต่อไป: `users.is_admin` +
`require_admin` ลงแล้วตาม ADR-0031 · ที่ยังห้ามคือ INF-24 AC-7 ซึ่งเป็นมติของตัวมันเอง
และเพราะการเปลี่ยนสถานะของแอดมินต้องผ่านประตูเดียวของ **INF-33** ก่อน ไม่ใช่ต่อตรง
เข้า `mark_sold()` · **ห้ามอ่านย่อหน้านี้ว่าเปิดทางแล้ว**
ทางเรียกวันนี้คือ `scripts/seed/sold_entry.py` (CLI operator) เท่านั้น ซึ่งจับ `AppError`
แล้วพิมพ์ `exc.message`/`exc.details` ออก stderr ไม่ได้ผ่าน JSON error envelope ของ
ข้อ 1 เลย — ตารางข้อ 3 ยังคงรายการนี้ไว้เพราะ `error_code` ถูกจองมาตั้งแต่ F3
(`POSTER_NOT_AVAILABLE`) หรือถูกจองใหม่ไว้ล่วงหน้าให้ F3/SCR-06 ใช้ต่อ (`POSTER_HAS_ACTIVE_RESERVATION`)
เมื่อมี endpoint จริงในรอบถัดไป

---

## 4. จุดวิกฤต — `409 POSTER_NOT_AVAILABLE`

🔴 ‹แก้ 2026-09-15 · SCR-07 สไลซ์ A› `POST /listings/{poster_id}/reserve`
(`order_service.reserve_listing()`) คือ endpoint ที่แปลง race-condition defense
เป็น HTTP contract โดยตรง — **ไม่ใช่ 15 นาทีอีกแล้ว** ถ้อยคำเดิมของหัวข้อนี้อ้างอิง
`/cart/reserve/{id}` และ TTL 15 นาทีของ `ADR-0002` ซึ่งถูกแทนที่ทั้งคู่:

1. Service เปิด transaction เดียว → `SELECT ... FROM posters WHERE id=:id FOR UPDATE`
2. lazy-expire การจองที่หมดอายุของใบนี้ก่อนตัดสิน (`ADR-0033` D4)
3. ถ้า `status != 'available'` (หรือยังไม่ publish/approve) → rollback → คืน **404/409**
   ตามเคส — `409 POSTER_NOT_AVAILABLE` แนบ `details[].reserved_until` ถ้ามี active
   reservation จริง (`ADR-0037` D4)
4. ถ้า available → update เป็น `reserved` + insert `reservations`
   (status=`active`, expires_at = **now + `platform_settings.reservation_ttl_minutes`
   ค่าเป็น 60 นาทีวันนี้ — ห้าม hardcode**, `ADR-0030` D3) → คืน **201**

**Acceptance test ที่มีจริงแล้ว** (`tests/integration/test_reserve_listing_endpoint_race.py`
· `tests/integration/test_real_client_concurrent_locking.py`): ยิง
`POST /listings/{poster_id}/reserve` พร้อมกัน 2 request (คนละ user) ไปยัง poster
เดียวกันผ่าน `real_client` fixture (connection แยกกันจริง ไม่ใช่ `client` ปกติซึ่ง
พิสูจน์ concurrency ไม่ได้) → ต้องได้ `201` แค่ 1 ฝั่ง อีกฝั่งได้ `409` เท่านั้น
(ห้ามได้ `500` จาก unique-violation ที่ไม่ได้ catch — DB partial unique index เป็นแค่
safety net ชั้นที่ 2 ไม่ใช่ error path หลัก) — ยืนยันแล้วว่า `FOR UPDATE` ปรากฏใน SQL
จริง ไม่ใช่แค่พึ่ง constraint

---

## 5. Rate-limit

`POST /auth/firebase` จำกัด **5 ครั้ง/นาที ต่อ IP** (slowapi) — เกินแล้วคืน `429 LOGIN_RATE_LIMITED` พร้อม `Retry-After` header

> **OTP ไม่ใช่ความรับผิดชอบของ backend แล้ว** — SMS OTP ของ Phone Auth ส่ง/ตรวจที่ Firebase ทั้งหมด (rate-limit + lockout เป็นของ Firebase) backend เห็นแค่ ID token ที่ผ่าน verify มาแล้ว

🔴 ‹เพิ่ม 2026-09-15 · SCR-07 สไลซ์ A · ADR-0037 D3/D6› `POST /listings/{poster_id}/reserve`
จำกัด **10 ครั้ง/นาที ต่อ `user_id`** (ไม่ใช่ IP — endpoint นี้ต้อง auth อยู่แล้ว และ
IP บนมือถือคือ CGNAT ของ operator เดียวกัน) เกินแล้วคืน `429 RESERVE_RATE_LIMITED`
พร้อม `Retry-After` header · `error_code` ของ 429 แต่ละเส้นมาจาก `error_message=`
ที่ตั้งไว้ตอน decorate route นั้น ๆ (`app/api/v1/auth.py` · `app/api/v1/orders.py`)
ไม่ใช่จากการ `if` บน path string — กันไม่ให้เน่าเงียบตอนเพิ่มเส้นที่สาม
(`app/main.py` `rate_limit_handler`)
🔴 **ต้องตั้ง `scope=` เป็นค่าคงที่เสมอเมื่อ route มี path parameter** — `slowapi`
default `key_style="url"` ทำให้ rate limit นับแยกตาม path จริงถ้าไม่ตั้ง `scope`
(พิสูจน์แล้วจริงตอนพัฒนาใบนี้: ยิง `poster_id` สุ่มใหม่ทุกครั้ง 25 ครั้งไม่ติด 429
เลยสักครั้งจนกว่าจะตั้ง `scope="reserve_listing"` — ใช้ `Limiter.shared_limit()`
ไม่ใช่ `Limiter.limit()` เพราะตัวหลังไม่เปิดพารามิเตอร์ `scope` ให้ตั้ง)

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
