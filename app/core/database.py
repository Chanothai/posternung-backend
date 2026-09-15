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
# ── `pool_recycle` เลือกจากของที่วัดได้บนระบบนี้ ไม่ใช่เลขที่คนอื่นใช้กัน (AC-3) ──
#
# วัด 2026-09-15 บน PostgreSQL ที่รันอยู่จริง:
#     idle_session_timeout = 0            (ปิด)
#     idle_in_transaction_session_timeout = 0   (ปิด)
#     statement_timeout = 0               (ปิด)
#     tcp_keepalives_idle/interval/count = 0    (ตาม default ของ OS)
# และ `nf_conntrack_tcp_timeout_established` ของ Docker VM = **432000 s (5 วัน)**
#
# 🔴 **แปลว่าบนสแตกนี้ไม่มีอะไรตัด connection ที่ idle เลยก่อน 5 วัน** ⇒ `pool_recycle`
# **ไม่ใช่สิ่งที่แก้บั๊กที่เจอ** — ตัวที่แก้คือ `pool_pre_ping` · สิ่งที่ฆ่า connection จริง ๆ
# ในเหตุการณ์นั้นคือ *ปลายทางหายไป* (เครื่อง dev หลับแล้วตื่น · container ถูก restart ·
# deploy) ซึ่งไม่มี timeout ตัวไหนบรรยายได้
#
# หน้าที่ของ `pool_recycle` จึงเป็น **การจำกัดอายุ ไม่ใช่การจับคู่กับ timeout**:
# 3600 s ทำให้ช่วง idle ที่ยาวกว่าหนึ่งชั่วโมง (ข้ามคืน · พักเที่ยง · เครื่องหลับ)
# ได้ connection ใหม่แทนที่จะให้ `pool_pre_ping` ตรวจแล้วทิ้งทีละตัว
# · ต่ำกว่าเพดานที่วัดได้ **120 เท่า** · และที่ `pool_size=5` ราคาสูงสุดคือเปิดใหม่
# 5 ครั้ง/ชั่วโมง ซึ่งเทียบไม่ได้กับ round-trip ที่ `pool_pre_ping` จ่ายทุก checkout อยู่แล้ว
#
# ⚠️ **ตัวเลขนี้อ้างผลวัดของเครื่อง dev เครื่องนี้** — production ยังไม่ได้วัด และอาจมี
# NAT/firewall ที่ตัดเร็วกว่ามาก ถ้าวันหนึ่งเจอ `connection is closed` บน production
# อีก **ให้วัดก่อนแล้วค่อยลดเลข ห้ามเดา** (`known_gap` ของ INF-42)
#
# `pool_size=5` · `max_overflow=10` · `timeout=30s` เป็นค่า default ที่ใช้อยู่จริง
# **ยังไม่เปลี่ยนเพราะยังไม่มีเลขที่บอกว่าต้องเปลี่ยน** (มติเจ้าของ 2026-09-10 · AC-5)
# 🔴 แยกเป็นค่าคงที่เพราะ **เทสของ AC-1 ต้องสร้าง engine จากค่าชุดเดียวกันนี้**
# ถ้าเทสตั้งค่าเอง มันจะเขียวต่อไปแม้มีคนถอด `pool_pre_ping` ออกจากบรรทัดล่าง
# ⇒ mutation ของ AC-2 จะไม่ตาย และใบนี้จะปิดด้วยเทสที่พิสูจน์ไม่ได้
POOL_KWARGS: dict[str, object] = {
    "pool_pre_ping": True,
    "pool_recycle": 3600,
}

engine = create_async_engine(
    settings.DATABASE_URL,
    echo=settings.DEBUG,
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
