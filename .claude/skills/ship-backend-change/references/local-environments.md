# Local environments: dev vs sit

> พื้นฐานเรื่อง local setup, compose base+override, และ config ต่อ env อยู่ใน
> `.claude/rules/environments.md` (path-scoped rule — โหลดเองอยู่แล้วตอนแตะ
> `docker-compose*.yml`) ไฟล์นี้เก็บเฉพาะเรื่องที่เกิดตอน **รันสอง stack พร้อมกัน
> บนเครื่องเดียว** ซึ่ง rule นั้นไม่ได้ครอบ

โปรเจกต์มี 2 วิธีรันบนเครื่อง เลือกผิดแล้วเสียเวลาไล่ debug สิ่งที่ไม่ใช่บั๊กจริง

## dev — ใช้เขียนโค้ด/รัน pytest ประจำวัน

container `posternung-backend-db-1` publish `5432:5432` · **`pytest` เชื่อม DB ตัวนี้
เสมอ** ผ่าน `tests/conftest.py`

**อย่าปิด container นี้ทิ้งไว้** ถ้าจำเป็นต้องปิดชั่วคราว (เช่น port ชนกับ sit) ให้
เปิดกลับด้วย compose ก่อนรัน `pytest` ครั้งถัดไป:
```bash
docker compose -f docker-compose.yml up -d db
```
ใช้ compose ไม่ใช่ `docker start` เฉยๆ — `docker start` คืน container เดิมได้ แต่ถ้า
network state เพี้ยน (เคยเจอตอน Docker Desktop restart) จะได้ container ที่รันอยู่แต่
**ไม่ publish port** ทำให้ `pytest` ต่อ DB ไม่ได้ทั้งที่ `docker ps` ดูปกติ
เช็คด้วย `docker port posternung-backend-db-1` — ถ้าไม่มี output แปลว่าไม่ได้ publish

## sit — production-like บนเครื่อง

รัน image ที่ build จาก `Dockerfile` จริง (ไม่ hot-reload) ด้วย `ENVIRONMENT=sit` —
ใกล้ production ที่สุดเท่าที่ทำบนเครื่องได้

```bash
docker compose -p posternung-sit \
  -f docker-compose.yml -f docker-compose.sit.yml \
  --env-file .env.sit up -d --build --force-recreate app
```

จุดที่ต่างจาก dev:
- **`-p posternung-sit`** — แยก compose project ออกจาก dev · ถ้าไม่แยก compose จะมอง
  ว่า service `db`/`app` เป็นตัวเดียวกันกับ stack dev แล้วไป recreate/แย่ง container
  ของ dev
- `docker-compose.sit.yml` มี `ports: !reset []` ที่ service `db` — ไม่ publish port
  ออก host เพื่อไม่ชนกับ dev db ที่ถือ `5432` อยู่ก่อน · เจอ error
  `port is already allocated` ตอน start db ของ sit ให้เช็คว่าบรรทัดนี้ยังอยู่
  (เคยหายไปเพราะอยู่คนละ branch ที่ยังไม่ merge)
- app publish `8000:8000` — เข้าได้ทั้ง `http://127.0.0.1:8000/api/v1` และ
  `http://<LAN IP>:8000/api/v1` (หา IP: `ipconfig getifaddr en0`) สำหรับยิงจากมือถือ
- `.env.sit` ใช้ **Firebase project แยกของตัวเอง** (`posternung-sit`) — ไม่ใช่ตัว
  เดียวกับ production ดู `references/release-and-deploy.md`

### ⚠️ กับดักใหญ่: `--build` ไม่ recreate container

`docker compose up -d --build` **build image ใหม่เสมอ แต่ไม่ recreate container ที่
กำลังรันอยู่** ถ้า container เดิมยังอยู่และ compose config ไม่เปลี่ยน (เช่นแก้แค่โค้ด
ใน `app/`) → ทดสอบโค้ดเก่าโดยไม่รู้ตัวแล้วสรุปผลผิด

เคยเกิดจริง: endpoint ตอบ 200 ทั้งที่ควรเป็น 401 เพราะ container ยังเป็น image ก่อน
fix — เสียเวลาไล่หาบั๊กที่ไม่มีอยู่จริง

**ก่อนเชื่อผลทดสอบ ให้ยืนยันว่าโค้ดในคอนเทนเนอร์ใหม่จริง** — grep หา marker ที่เพิ่ง
เขียนลงไป:
```bash
docker exec posternung-sit-app grep -c "<ข้อความที่เพิ่งเขียน>" app/services/auth_service.py
```
ได้ `0` = ยังรันโค้ดเก่า ต้อง `--force-recreate`

### เช็คว่าขึ้นสำเร็จจริง

```bash
docker ps --format '{{.Names}}\t{{.Status}}\t{{.Ports}}'
docker logs posternung-sit-app --tail 10   # ต้องเห็น "Application startup complete"
curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8000/health   # ต้อง 200
```
ถ้า container restart วนหรือ `/health` ไม่ตอบ ให้อ่าน log เต็มก่อนเดา — สาเหตุที่เจอ
บ่อยที่สุดคือ port ชนกับ dev db ไม่ใช่ปัญหา network/IP

### ทำความสะอาดหลังทดสอบ

```bash
docker exec posternung-sit-db psql -U poster_nung_app -d poster_nung_db_sit \
  -c "DELETE FROM refresh_tokens; DELETE FROM oauth_identities; DELETE FROM users;"

docker compose -p posternung-sit -f docker-compose.yml -f docker-compose.sit.yml \
  --env-file .env.sit down
```
