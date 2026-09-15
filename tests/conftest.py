"""Test fixtures — ใช้ poster_nung_test แยกจาก dev DB (ไม่แตะข้อมูล dev)."""

import asyncio
from pathlib import Path

import asyncpg
import pytest
import pytest_asyncio
from alembic import command
from alembic.config import Config
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.core.config import settings

BACKEND_ROOT = Path(__file__).resolve().parent.parent
TEST_DB_NAME = "poster_nung_test"

_dev_url = make_url(settings.DATABASE_URL)
# str(url)/render_as_string() default เซ็นเซอร์รหัสผ่านเป็น '***' — ต้อง hide_password=False
# ไม่งั้น asyncpg auth fail เพราะ password กลายเป็น literal '***'
TEST_DATABASE_URL = _dev_url.set(database=TEST_DB_NAME).render_as_string(
    hide_password=False
)


async def _ensure_test_database_exists() -> None:
    """เชื่อมต่อ maintenance DB (postgres) เพื่อสร้าง poster_nung_test ถ้ายังไม่มี."""
    admin_url = _dev_url.set(database="postgres")
    conn = await asyncpg.connect(
        user=admin_url.username,
        password=admin_url.password,
        host=admin_url.host,
        port=admin_url.port,
        database=admin_url.database,
    )
    try:
        exists = await conn.fetchval(
            "SELECT 1 FROM pg_database WHERE datname = $1", TEST_DB_NAME
        )
        if not exists:
            # TEST_DB_NAME เป็นค่าคงที่ในโค้ด ไม่ใช่ user input — interpolate ตรงนี้ปลอดภัย
            # (CREATE DATABASE ไม่รองรับ parameterized identifier)
            await conn.execute(f'CREATE DATABASE "{TEST_DB_NAME}"')
    finally:
        await conn.close()


def _run_migrations() -> None:
    """รัน alembic upgrade head บน poster_nung_test (sync — เรียกตอนยังไม่มี event loop)."""
    cfg = Config(str(BACKEND_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_ROOT / "alembic"))
    cfg.attributes["sqlalchemy_url_override"] = TEST_DATABASE_URL
    command.upgrade(cfg, "head")


@pytest.fixture(scope="session", autouse=True)
def _setup_test_database() -> None:
    """สร้าง DB + apply migration ครั้งเดียวต่อ test session."""
    asyncio.run(_ensure_test_database_exists())
    _run_migrations()


@pytest_asyncio.fixture
async def db_session() -> AsyncSession:
    """Session ต่อ 1 test — ครอบด้วย transaction เดียวแล้ว rollback ทิ้งเสมอ
    (join_transaction_mode="create_savepoint" กัน session.commit() ของ service
    ทะลุออกไป commit จริงบน DB)."""
    engine = create_async_engine(TEST_DATABASE_URL)
    async with engine.connect() as conn:
        await conn.begin()
        # expire_on_commit=False ให้ตรงกับ async_session_maker จริง — ไม่งั้นหลัง route
        # commit() ORM object จะ expired แล้วตอน serialize response จะ trigger async I/O
        # นอก greenlet → MissingGreenlet
        session = AsyncSession(
            bind=conn,
            join_transaction_mode="create_savepoint",
            expire_on_commit=False,
        )
        try:
            yield session
        finally:
            await session.close()
            await conn.rollback()
    await engine.dispose()


@pytest_asyncio.fixture
async def client(db_session: AsyncSession):
    """httpx AsyncClient ยิงเข้า ASGI app ตรง ๆ — override get_db ให้ใช้ test session
    เดียวกับ db_session (data ที่ route commit เป็น savepoint แล้ว rollback ท้าย test).

    ปิด rate limiter ระหว่าง test เพราะ state ของ slowapi เป็น in-memory ค้างข้าม
    test (key = client IP เดียวกัน) จะทำให้เกิด 429 สุ่ม — พฤติกรรม 429 ทดสอบแยก/manual แล้ว.

    🔴 **ข้อจำกัด (ADR-0037 D5) — fixture นี้พิสูจน์ concurrency ไม่ได้เลย** ทุก
    request ที่ยิงผ่าน `client` นี้ใช้ **`db_session` ตัวเดียวกันบน connection
    เดียวกัน** ที่ครอบด้วยทรานแซกชันเดียว ⇒ สอง request ที่ "ยิงพร้อมกัน" ทาง Python
    (เช่นผ่าน `asyncio.gather`) จริง ๆ แล้วอยู่ใน**ทรานแซกชันเดียวกัน** — `SELECT ...
    FOR UPDATE` ไม่มีวันบล็อกตัวเอง และ `AsyncSession` ตัวเดียวใช้ขนานกันไม่ได้ด้วยซ้ำ
    (จะได้ `InterfaceError: another operation is in progress`) เทสที่ต้องพิสูจน์ว่า
    row lock กันการชนจริง (race condition · 429 รายผู้ใช้) **ต้องใช้ fixture
    `real_client` ด้านล่างแทน** — ดูเหตุผลเต็มใน docstring ของมัน
    """
    from httpx import ASGITransport, AsyncClient

    from app.core.config import settings
    from app.core.database import get_db
    from app.core.limiter import limiter
    from app.main import app

    async def _override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = _override_get_db
    limiter_was_enabled = limiter.enabled
    limiter.enabled = False
    # บังคับ DEBUG=true ระหว่าง integration test ให้พฤติกรรมเหมือนกันทุกเครื่อง
    # (ไม่ขึ้นกับว่า CI/local ตั้ง DEBUG ไว้ยังไง)
    debug_was = settings.DEBUG
    settings.DEBUG = True

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    settings.DEBUG = debug_was
    limiter.enabled = limiter_was_enabled
    app.dependency_overrides.clear()


@pytest_asyncio.fixture
async def real_client():
    """httpx AsyncClient ที่ให้ **session ต่อ 1 request จริง บน connection ของตัวเอง**
    (ADR-0037 D5) — ใช้เฉพาะเทสที่ต้องพิสูจน์ว่าการชนกันที่ระดับ DB เกิดขึ้นจริง
    (race condition ของ row lock · 429 รายผู้ใช้) ซึ่ง `client` ข้างบนพิสูจน์ไม่ได้เลย

    🔴 **commit เป็นของจริง ลง `poster_nung_test`** — override `get_db` ที่นี่สร้าง
    `AsyncSession` ใหม่จาก engine เดียวกันทุกครั้งที่ FastAPI เรียก dependency
    (คนละ connection ต่อ request จริง ไม่ใช่ session เดียวที่แชร์กัน) ⇒ เทสที่ใช้
    fixture นี้ **ต้องเก็บกวาดข้อมูลที่ตัวเองสร้างเอง** — ใช้ท่า "ป้าย" ทรงเดียวกับ
    `tests/integration/test_reserve_listing_race.py:51-57` (ลบด้วย marker เช่น
    prefix ของ email/title ไม่ใช่ id ที่เพิ่งสร้าง เพราะรอบที่ล้มกลางทาง seed จะไม่มี
    id ให้ลบ) **ห้ามพึ่งการ rollback อัตโนมัติเหมือน `client`/`db_session`**

    เปิด rate limiter จริง (`limiter.enabled = True` + `limiter.reset()` ล้าง state
    ที่อาจค้างจากเทสไฟล์อื่น) ต่างจาก `client` ที่ปิดไว้เสมอ — เทสที่ใช้ fixture นี้
    คือที่เดียวที่ทดสอบพฤติกรรม 429 จริงได้

    ⚠️ **ความเสี่ยงที่รู้ล่วงหน้า (ADR-0037 D5)**: `ASGITransport` รันทุก request
    ใน **event loop เดียว** — ถ้าโค้ดฝั่งใดฝั่งหนึ่งบล็อก loop ทั้งตัวระหว่างรอ
    `FOR UPDATE` (ไม่ยอม `await` คืนการควบคุม) การชนจะไม่เกิดจริงแม้ยิงผ่าน
    `asyncio.gather` เพราะ request ที่สองจะไม่ได้เริ่มจนกว่าที่หนึ่งจบ ⇒ เทสที่ใช้
    fixture นี้ต้องมี**เทสควบคุม**ยืนยันก่อนว่าสองฝั่งค้างพร้อมกันจริงและวัดได้
    (เวลาที่ฝั่งที่สองถูกบล็อก หรือ `pg_locks`) — **ถ้าพิสูจน์ไม่ได้ว่าชน เทส race
    ที่พึ่ง fixture นี้เป็นโมฆะทั้งชุด** (`test-quality` §3.1)
    """
    from httpx import ASGITransport, AsyncClient
    from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

    from app.core.config import settings
    from app.core.database import get_db
    from app.core.limiter import limiter
    from app.main import app

    engine = create_async_engine(TEST_DATABASE_URL)

    async def _override_get_db():
        # session ใหม่ + connection ใหม่จาก pool ทุกครั้งที่ FastAPI เรียก — ไม่ใช่
        # ตัวแปรที่ปิดคลุมไว้ตัวเดียว (นั่นคือสิ่งที่ทำให้ `client` พิสูจน์ concurrency
        # ไม่ได้) commit ใน route (`await session.commit()`) จึงเป็นของจริง
        async with AsyncSession(engine, expire_on_commit=False) as session:
            try:
                yield session
            except Exception:
                await session.rollback()
                raise
            finally:
                await session.close()

    app.dependency_overrides[get_db] = _override_get_db
    limiter_was_enabled = limiter.enabled
    limiter.enabled = True
    limiter.reset()
    debug_was = settings.DEBUG
    settings.DEBUG = True

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        # เผื่อเทสที่ต้องแอบดู SQL จริงที่ยิงออกไป (เช่น grep หา "FOR UPDATE" แบบ
        # เดียวกับ test_reserve_listing_race.py) — engine ตัวนี้ถูกสร้างในนี้เอง
        # ไม่มีทางเข้าถึงจากนอกฟังก์ชันได้ถ้าไม่แปะไว้ที่ object ที่ส่งออกไป
        ac.test_engine = engine
        yield ac

    settings.DEBUG = debug_was
    limiter.enabled = limiter_was_enabled
    limiter.reset()
    app.dependency_overrides.clear()
    await engine.dispose()
