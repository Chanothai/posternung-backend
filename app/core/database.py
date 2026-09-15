"""Async SQLAlchemy engine, session maker, declarative Base, และ get_db() dependency."""

from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from app.core.config import settings

# 🔴 INF-42 — pool ที่แจก connection ที่ตายแล้ว ทำให้ผู้ใช้เห็นว่า "ล็อกอินไม่ได้"
#
# ของจริง 2026-09-10: `POST /auth/firebase` ตอบ **500** ทั้งที่ Google Sign-In สำเร็จ
# และ Firebase ออก token ให้แล้ว · ตัวจริงคือ
# `sqlalchemy.exc.InterfaceError: <asyncpg InterfaceError>: connection is closed`
# ตอน `SELECT ... FROM oauth_identities` — pool คืน connection ที่ปลายทางตายไปแล้ว
# และไม่มีใครตรวจก่อนส่งให้ผู้เรียก · อาการพาไล่ผิดที่สามชั้น (Wi-Fi → `adb reverse`
# → SHA-1) ก่อนจะถึง DB เพราะข้อความบนจอไม่ได้บอกอะไรเลยว่าเป็นเรื่องฐานข้อมูล
#
# `pool_pre_ping=True` ยิง `SELECT 1` ตอน **checkout** ถ้าตายก็ทิ้งแล้วเปิดใหม่ให้เงียบ ๆ
#
# 🔴 **ข้อจำกัดที่ต้องรู้ ไม่ใช่ gap** (AC-7): มันตรวจเฉพาะ*จังหวะ checkout*
# ⇒ connection ที่ตาย **ระหว่าง** transaction ยัง error เหมือนเดิม **และนั่นถูกแล้ว** —
# การ retry ทั้ง transaction เป็นคนละเรื่องและไม่อยู่ในใบนี้ (จะ retry คำสั่งที่อาจ
# commit ไปแล้วได้อย่างไรเป็นคำถามของตัวเอง)
#
# ⚠️ ราคาที่จ่ายคือ round-trip เพิ่มหนึ่งครั้งทุก checkout · **ยังไม่ได้วัดว่ากระทบ
# latency เท่าไรบนระบบนี้** — บันทึกเป็น `known_gap` ของ INF-42 ไว้แล้ว ห้ามอ้างว่า
# "ไม่กระทบ" จนกว่าจะมีเลข
#
# ── 🔴 **ไม่ตั้ง `pool_recycle` และนั่นคือมติ ไม่ใช่การลืม** (INF-42 **AC-3**) ──
#
# รอบแรกของใบนี้ตั้งไว้ที่ `3600` พร้อมคอมเมนต์ยาวอธิบายเหตุผล · `code-critic`
# ชี้ว่าเหตุผลนั้น **วนกลับมาที่ตัวเอง** — เลือก 3600 เพราะสนใจ idle ที่เกินหนึ่ง
# ชั่วโมง และสนใจ idle ที่เกินหนึ่งชั่วโมงเพราะเลือก 3600 · ผลวัดที่ยกมารองรับ
# **ให้ได้แค่เพดานบนหนึ่งค่า** (conntrack 432000 s) ซึ่ง 1800 · 7200 · 14400 ·
# 86400 ก็ผ่านเกณฑ์ "ต่ำกว่าเพดานอย่างมีระยะห่าง" เท่ากันหมด
# ⇒ **ไม่มีอะไรในระบบนี้เลือก 3600** และ 3600 เองก็เป็นเลข default ที่ AC-3 ห้ามไว้ตรงตัว
#
# **สองอย่างนี้แก้ปัญหาคนละชนิดกัน:**
# - `pool_pre_ping` แก้ **ของที่วัดแล้วและเห็นแล้ว** — connection ที่ปลายทางหายไป
#   (เครื่องหลับ · container restart · deploy) · `code-critic` พิสูจน์ด้วยการทดลอง:
#   `pre_ping=False` → `asyncpg InterfaceError: connection is closed`
#   · `pre_ping=True` → สำเร็จ และได้ backend pid ใหม่ ⇒ invalidate + reconnect จริง
# - `pool_recycle` แก้ **การตัด connection ตามอายุ** ซึ่ง **ไม่เคยถูกวัดและไม่เคยเห็น
#   บนสแตกนี้เลย** — วัด 2026-09-15 แล้ว PostgreSQL ปิด timeout ทุกตัว
#   (`idle_session_timeout` · `idle_in_transaction_session_timeout` ·
#   `statement_timeout` · `tcp_keepalives_*` = 0 ทั้งหมด)
#
# ⇒ การปักเลขที่ไม่มีตัวขับ ไม่มีเกณฑ์คัดเลือก และไม่แก้ปัญหาที่เจอ **แย่กว่าไม่ตั้ง**
# เพราะมันดูเหมือนมีคนคิดมาแล้ว
#
# 🔴 **เงื่อนไขกลับมาทำ — ห้ามใส่เลข default กลับมาอีก:**
# ต้องมี **เพดานจริงของ production ที่วัดแล้ว** (conntrack ของ host จริง · idle timeout
# ของ proxy/LB ถ้ามี · `SHOW` ของ PostgreSQL ตัวที่ production ใช้) · เลขที่ตั้งต้อง
# **ต่ำกว่าเพดานนั้นและอ้างมันได้** ไม่ใช่ต่ำกว่าเพดานที่วัดบนเครื่อง dev
#
# `pool_size=5` · `max_overflow=10` · `timeout=30s` เป็นค่า default ที่ใช้อยู่จริง
# **ยังไม่เปลี่ยนเพราะยังไม่มีเลขที่บอกว่าต้องเปลี่ยน** (มติเจ้าของ 2026-09-10 · AC-5)
# 🔴 `POOL_KWARGS` แยกออกมาเพราะ **เทสของ AC-1 ต้องอ่าน `pool_pre_ping` จากที่นี่
# ไม่ใช่ตั้งเอง** — ถ้าเทสตั้งเอง มันจะเขียวต่อไปแม้มีคนถอด flag ออกจากที่นี่
# ⇒ mutation ของ AC-2 จะไม่ตาย และใบนี้จะปิดด้วยเทสที่พิสูจน์ไม่ได้
#
# ‹🔴 แก้ 2026-09-15 · `code-critic` รอบ 2› ถ้อยคำเดิมว่า *"เทสของ AC-1 ต้องสร้าง
# engine จาก **ค่าชุดเดียวกันนี้**"* วางอยู่ต่อจากย่อหน้า `pool_size`/`max_overflow`
# จึงอ่านได้ว่าสามค่านั้นอยู่ใน `POOL_KWARGS` ด้วย **ซึ่งไม่จริง — มีคีย์เดียว**
# และเทสก็ไม่ได้ใช้ "ค่าชุดเดียวกัน": มันตั้ง `pool_size=1, max_overflow=0` ของตัวเอง
# เพื่อบังคับให้ pool คืน connection ตัวที่เพิ่งถูกฆ่า
#
# 🔴 **ห้ามย้าย `pool_size` / `max_overflow` เข้ามาใน `POOL_KWARGS`** — เทสส่งสองค่านี้
# เป็น keyword ของตัวเองพร้อมกับ `**POOL_KWARGS` ⇒ จะได้
# `TypeError: create_async_engine() got multiple values for keyword argument 'pool_size'`
# ซึ่งแดงก็จริงแต่อ่านไม่ออกว่าเกิดอะไรขึ้น
POOL_KWARGS: dict[str, object] = {
    "pool_pre_ping": True,
}

# 🔴 SCR-07 · code-critic รอบ 1 F1 — `echo=True` (DEBUG=true) log ทุก SQL statement
# **พร้อม bound parameters**  ⇒ ตั้งแต่ INF-33/SCR-07 เขียนแถว `order_shipping_details`
# ค่าเหล่านั้นมีชื่อผู้รับ/เบอร์/ที่อยู่ — หลุดลง log ตรง ๆ (ADR-0020 D9 · security-baseline §2)
# ยืนยันจริงบน container `posternung-sit-app` (`DEBUG=true` ใน `.env.sit`) ว่าเห็นบรรทัด
# `INSERT INTO order_shipping_details ... ('สมชาย ใจดี', '0891112222', ...)` จริง
#
# `hide_parameters=True` เก็บ echo ของตัว SQL (dev ยังอ่าน query shape ได้) แต่ตัด
# bound parameters ออกจาก log ทั้งหมด (แทนที่ด้วย `[SQL parameters hidden due to
# hide_parameters=True]`) — เลือกทางนี้แทนการปิด `echo` ให้ตายเพราะ SQL shape (ไม่ใช่ค่า)
# ยังมีประโยชน์ตอน debug บน dev/SIT และไม่มีข้อมูลอ่อนไหวอยู่ในตัว query เอง
engine = create_async_engine(
    settings.DATABASE_URL,
    echo=settings.DEBUG,
    hide_parameters=True,
    **POOL_KWARGS,
)

async_session_maker = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


class Base(DeclarativeBase):
    """Declarative base ของทุก ORM model."""


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency — yield session และ rollback อัตโนมัติเมื่อเกิด error."""
    async with async_session_maker() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()
