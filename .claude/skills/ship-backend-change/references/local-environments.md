# Local environments: dev vs sit

โปรเจกต์มี 2 วิธีรัน backend บนเครื่อง — เลือกผิดแบบแล้วเสียเวลาไล่ debug ที่ไม่ใช่บั๊กจริง

## dev — สำหรับเขียนโค้ด/รัน pytest ประจำวัน

```bash
docker compose up -d db          # แค่ postgres ใน container
uvicorn app.main:app --reload    # app รันบน host ตรงๆ
```
- ใช้ `.env` (มี `DATABASE_URL=...@localhost:5432/...` เพราะ app รันบน host ไม่ใช่
  container)
- container ชื่อ `posternung-backend-db-1`, publish `5432:5432`
- `pytest` เชื่อมต่อ DB ตัวนี้เสมอ (ผ่าน `tests/conftest.py`) — **อย่าปิด container
  นี้ระหว่างพัฒนา** ถ้าจำเป็นต้องปิดชั่วคราว (เช่น port ชนกับ sit) ให้เปิดกลับก่อน
  รัน `pytest` ครั้งถัดไปเสมอ:
  ```bash
  docker compose -f docker-compose.yml up -d db
  ```
  (ใช้ compose ไม่ใช่ `docker start` เฉยๆ — `docker start` คืน container เดิมแต่ไม่
  รับประกันว่า port ยัง publish ถูกต้องถ้า network state เพี้ยน)

## sit — production-like บนเครื่อง (ทดสอบ Docker image จริงก่อน deploy)

รัน image ที่ build จาก `Dockerfile` จริง (ไม่ hot-reload) ด้วย `ENVIRONMENT=sit` —
ใกล้เคียง production มากที่สุดเท่าที่ทำบนเครื่องได้

```bash
docker compose -p posternung-sit \
  -f docker-compose.yml -f docker-compose.sit.yml \
  --env-file .env.sit up -d --build
```

จุดสำคัญที่ต่างจาก dev:
- **`-p posternung-sit`** — แยก compose project ออกจาก dev (project เดียวกันจะไป
  แย่ง/recreate container กันเอง เพราะ service ชื่อ `db`/`app` ซ้ำกัน)
- `docker-compose.sit.yml` มี `ports: !reset []` ที่ service `db` — **ไม่ publish
  port ออก host เลย** (เหมือน production) เพื่อไม่ชนกับ dev db ที่ถือ `5432` อยู่
  ก่อนแล้ว — ถ้าเจอ error "port is already allocated" ตอน start db ของ sit ให้เช็ค
  บรรทัดนี้มีอยู่จริงใน `docker-compose.sit.yml` (อาจอยู่คนละ branch ที่ยังไม่ merge)
- app publish `8000:8000` ตามปกติ — เข้าได้ทั้ง:
  - `http://127.0.0.1:8000/api/v1` (จากเครื่องนี้)
  - `http://<LAN IP>:8000/api/v1` (จากมือถือใน Wi-Fi เดียวกัน — หา IP ด้วย
    `ipconfig getifaddr en0`)
- `.env.sit` (gitignored, local เท่านั้น) แยก Firebase project เป็นของตัวเอง
  (`FIREBASE_PROJECT_ID=posternung-sit`, credential ที่
  `secrets/firebase-sa-sit.json`) — **ไม่ใช่ project เดียวกับ production**
  (`posternung`) ห้ามเอา credential ของ prod มาใช้ที่นี่เด็ดขาด
- `IMAGE_TAG=sit-local` แยกจาก `posternung:local` ที่ dev ใช้ (ถ้ามี) กัน image
  ชนกัน

### ⚠️ กับดักใหญ่ที่สุด: `--build` ไม่ recreate container

`docker compose up -d --build` จะ **build image ใหม่เสมอ** แต่ **ไม่ recreate
container ที่กำลังรันอยู่** ถ้า container เดิมยังอยู่และ config ไม่เปลี่ยน (เช่นแก้แค่
โค้ดใน `app/` ที่ไม่ได้เปลี่ยน compose file) — ผลคือทดสอบโค้ดเก่าโดยไม่รู้ตัว แล้ว
สรุปผลผิด (เคยเกิดจริง — ตอบ 200 ทั้งที่ควรเป็น 401 เพราะ container ยังเป็น image
ก่อน fix)

**วิธีที่ชัวร์ที่สุด:**
```bash
docker compose -p posternung-sit -f docker-compose.yml -f docker-compose.sit.yml \
  --env-file .env.sit up -d --build --force-recreate app
```

**ก่อนเชื่อผลทดสอบ ให้ยืนยันว่าโค้ดในคอนเทนเนอร์เป็นเวอร์ชันล่าสุดจริง** — grep หา
comment/string ที่เพิ่งเขียนไว้ในโค้ด:
```bash
docker exec posternung-sit-app grep -c "<เศษข้อความที่เพิ่งเขียน>" app/services/auth_service.py
```
ถ้าได้ `0` แปลว่า container ยังรันโค้ดเก่า ต้อง `--force-recreate` ก่อน

### เช็ค container ขึ้นสำเร็จจริง

```bash
docker ps --format '{{.Names}}\t{{.Status}}\t{{.Ports}}'
docker logs posternung-sit-app --tail 10   # ต้องเห็น "Application startup complete"
curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8000/health   # ต้อง 200
```
ถ้า container restart วนหรือ `/health` ไม่ตอบ ให้ดู log เต็มก่อนเดา — สาเหตุที่เจอ
บ่อยคือ port ชนกับ dev db (ด้านบน) ไม่ใช่ปัญหา network/IP

### ทำความสะอาดหลังทดสอบ

ลบ test data ที่ seed ไว้ใน sit db เสมอ:
```bash
docker exec posternung-sit-db psql -U poster_nung_app -d poster_nung_db_sit \
  -c "DELETE FROM refresh_tokens; DELETE FROM oauth_identities; DELETE FROM users;"
```
ปิด stack ทั้งหมดเมื่อเลิกใช้ (ไม่บังคับต้องปิดทันทีถ้ายังทดสอบต่อ):
```bash
docker compose -p posternung-sit -f docker-compose.yml -f docker-compose.sit.yml \
  --env-file .env.sit down
```
