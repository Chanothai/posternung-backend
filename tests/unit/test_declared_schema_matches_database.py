"""เทียบสิ่งที่ model **ประกาศ** (`Base.metadata`) กับ schema **ที่มีอยู่จริง** ใน DB
หลัง `alembic upgrade head` — ปิด `known_gap` **G1 ของ INF-25**

ก่อนไฟล์นี้ **ไม่มีเทสตัวไหนในโปรเจกต์เทียบสองฝั่งนี้เลย** `conftest.py` migrate ด้วย
`upgrade head` แล้วเทสทุกตัวก็ยิงกับ DB นั้น ⇒ constraint ที่ประกาศไว้ใน `__table_args__`
แต่ไม่มีใน migration (หรือกลับกัน) เขียวทั้งชุด · code-critic พิสูจน์ไว้ 2026-08-15 ว่า
mutation สองตัวนี้เขียวทั้งชุดทั้งคู่:

* (a) สลับ `uq_poster_splits_parent_piece` กลับไปใช้ `reason` **โดยคงชื่อ constraint เดิม**
* (b) ถอด `CheckConstraint("piece_no >= 2")` ทิ้ง

ราคาจริงของช่องนี้คือ `alembic revision --autogenerate` รอบหน้าอ่านจาก model ที่ไม่มี
ใครตรวจ — drift จึงถูกเขียนต่อเข้า migration ใหม่แทนที่จะถูกจับ

🔴 **ครอบทุกตารางใน `Base.metadata` ไม่ใช่แค่ `poster_splits`** (parametrize ตามชื่อตาราง)
เพราะช่องว่างนี้ไม่ได้เกิดจาก INF-25 และไม่ได้อยู่แค่ที่ตารางเดียว

## ทำไมต้องให้ Postgres เป็นคนทำให้ expression เป็นรูปมาตรฐาน

ข้อความ `CheckConstraint` ที่คนเขียน (`price >= 0`) กับที่ PG เก็บจริง
(`CHECK ((price >= (0)::numeric))`) **ไม่มีวันตรงกันด้วยการเทียบสตริง** — การ normalize
เองด้วย regex คือการเดาไวยากรณ์ของ PG ซึ่งพังเงียบได้ทุกครั้งที่เจอรูปที่ไม่ได้เผื่อไว้
เทสนี้จึงเอา expression ที่ *model ประกาศ* ไปสร้างเป็น constraint ชั่วคราว (`NOT VALID`
— ไม่สแกนตาราง ไม่แตะข้อมูล) บนตารางจริง แล้วอ่านกลับด้วย `pg_get_constraintdef()`
⇒ ทั้งสองฝั่งผ่านตัว parser เดียวกัน สิ่งที่เหลือให้เทียบจึงเป็นความหมาย ไม่ใช่การจัดวรรค

## สิ่งที่เทสนี้ **ไม่** พิสูจน์ (ห้ามอ้างว่าครอบ — `test-quality` §5)

* **ชนิดข้อมูลของคอลัมน์** — เทียบแค่ชื่อ · `nullable` · primary key
  (`VARCHAR(255)` ↔ `character varying(255)` ต้องแมปเอง ซึ่งเป็นการเดาชุดใหม่)
* **foreign key / ondelete** — ยังไม่มีอะไรเทียบ
* **สิ่งที่ไม่ได้อยู่ใน `Base.metadata` เลย** เช่น trigger, view, grant
* **เงื่อนไขที่เขียนคนละสำนวนแต่ความหมายเดียวกัน** (`a > 0` กับ `0 < a`) — PG เก็บตามที่
  เขียน ไม่ได้ทำให้เป็นรูปมาตรฐานเชิงตรรกะ ⇒ จะ **แดงแบบเสียงดัง** ไม่ใช่เขียวแบบเงียบ
  จึงยอมรับได้ (ทางแก้คือเขียนใน model ให้ตรงกับ migration)
"""

import pytest
from sqlalchemy import CheckConstraint, UniqueConstraint, inspect, text
from sqlalchemy.dialects import postgresql
from sqlalchemy.engine import Inspector
from sqlalchemy.ext.asyncio import AsyncSession

import app.models  # noqa: F401  — บังคับให้ทุก model ลงทะเบียนกับ Base.metadata ก่อนอ่าน
from app.core.database import Base

# parametrize ตามชื่อตารางเพื่อให้ชื่อเทสที่แดงบอกได้ทันทีว่าตารางไหน drift
TABLE_NAMES = sorted(Base.metadata.tables)


def _declared_check_constraints(table_name: str) -> dict[str, str]:
    """{ชื่อ: expression ที่ประกาศไว้ (SQL ที่ยังไม่ผ่าน parser ของ PG)}"""
    table = Base.metadata.tables[table_name]
    return {
        constraint.name: str(
            constraint.sqltext.compile(
                dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}
            )
        )
        for constraint in table.constraints
        if isinstance(constraint, CheckConstraint) and constraint.name
    }


def _declared_unique_constraints(
    table_name: str,
) -> tuple[dict[str, tuple[str, ...]], list[tuple[str, ...]]]:
    """(constraint ที่ตั้งชื่อเอง, คอลัมน์ของตัวที่ไม่ได้ตั้งชื่อ)

    ตัวที่ไม่ได้ตั้งชื่อมาจาก `Column(unique=True)` (เช่น `users.email`) — PG ตั้งชื่อให้เอง
    เป็น `<table>_<column>_key` จึงเทียบชื่อไม่ได้ เทียบได้แค่ว่ามีคีย์บนคอลัมน์ชุดนั้นจริง
    """
    table = Base.metadata.tables[table_name]
    named: dict[str, tuple[str, ...]] = {}
    unnamed: list[tuple[str, ...]] = []
    for constraint in table.constraints:
        if not isinstance(constraint, UniqueConstraint):
            continue
        columns = tuple(column.name for column in constraint.columns)
        if constraint.name:
            named[constraint.name] = columns
        else:
            unnamed.append(columns)
    return named, sorted(unnamed)


def _canonical(expression: str | None) -> str | None:
    """ตัดช่องว่างทิ้งและถอดวงเล็บครอบนอกสุด (เฉพาะคู่ที่จับคู่กันจริง) ออกทีละชั้น

    ใช้กับ **ทั้งสองฝั่ง** เสมอ — ฝั่งที่ผ่าน `pg_get_constraintdef()` มาแล้วก็ยังต้องผ่าน
    ตัวนี้ เพราะ PG ใส่วงเล็บซ้อนต่างจำนวนกันในแต่ละรูป (`CHECK ((a >= 2))` vs
    `pg_get_expr` ที่คืน `(a = 'x')`)
    """
    if expression is None:
        return None
    text_ = "".join(str(expression).split()).lower()
    while text_.startswith("(") and text_.endswith(")"):
        depth = 0
        for position, character in enumerate(text_):
            depth += (character == "(") - (character == ")")
            if depth == 0 and position < len(text_) - 1:
                # วงเล็บตัวแรกปิดก่อนจบสตริง เช่น `(a)and(b)` — ไม่ใช่วงเล็บครอบทั้งก้อน
                return text_
        text_ = text_[1:-1]
    return text_


def _declared_indexes(
    table_name: str,
) -> dict[str, tuple[tuple[str, ...], bool, str | None]]:
    """{ชื่อ index: (คอลัมน์, unique ไหม, predicate ของ partial index ที่ยังไม่ normalise)}"""
    table = Base.metadata.tables[table_name]
    declared = {}
    for index in table.indexes:
        where = index.dialect_options["postgresql"].get("where")
        declared[index.name] = (
            tuple(column.name for column in index.columns),
            bool(index.unique),
            None if where is None else str(where),
        )
    return declared


async def _inspector_call(session: AsyncSession, fn):
    """เรียก method ของ `Inspector` จากฝั่ง async — reflection เป็น API แบบ sync"""
    connection = await session.connection()
    return await connection.run_sync(lambda sync_conn: fn(inspect(sync_conn)))


async def _pg_normalised_expression(
    session: AsyncSession, table_name: str, label: str, sqltext: str
) -> str | None:
    """เอา expression ที่ *model ประกาศ* ไปสร้างเป็น constraint ชั่วคราวแล้วอ่านกลับจาก PG

    `NOT VALID` = ไม่สแกนแถวเดิม ⇒ ไม่แตะข้อมูลและไม่ล้มแม้ตารางจะมีแถวที่ผิดกฎอยู่
    (สนใจแค่ว่า PG ตีความ expression นี้ออกมาเป็นอะไร ไม่ได้จะบังคับใช้จริง)
    · drop ทิ้งทันที และทั้ง transaction ถูก rollback โดย fixture `db_session` อยู่แล้ว

    ใช้กับ `CheckConstraint` และกับ predicate ของ partial index — เป็น boolean expression
    เหนือคอลัมน์ของตารางเดียวกันทั้งคู่ จึงผ่าน parser ตัวเดียวกันได้
    """
    probe_name = f"probe_{label}"[:63]
    await session.execute(
        text(
            f'ALTER TABLE "{table_name}" ADD CONSTRAINT "{probe_name}" '
            f"CHECK ({sqltext}) NOT VALID"
        )
    )
    definition = await session.scalar(
        text("SELECT pg_get_constraintdef(oid) FROM pg_constraint WHERE conname = :n"),
        {"n": probe_name},
    )
    await session.execute(
        text(f'ALTER TABLE "{table_name}" DROP CONSTRAINT "{probe_name}"')
    )
    assert definition is not None, (
        f"สร้าง constraint ชั่วคราว {probe_name} แล้วอ่านกลับไม่เจอ — "
        "แปลว่า harness ของเทสนี้เองพัง ไม่ใช่ schema drift"
    )
    return _canonical(definition.removesuffix(" NOT VALID").removeprefix("CHECK "))


async def _actual_check_constraints(
    session: AsyncSession, table_name: str
) -> dict[str, str]:
    """{ชื่อ: นิยามที่ PG เก็บจริง} — อ่านจาก `pg_constraint` ตรง ๆ

    ไม่ใช้ `Inspector.get_check_constraints()` เพราะมันคืน `sqltext` ที่ถูกตัดวงเล็บออก
    บางส่วนแล้ว (คนละรูปกับที่ `pg_get_constraintdef()` คืน) — ฝั่ง "ที่ประกาศ" ของเทสนี้
    อ่านผ่าน `pg_get_constraintdef()` ทั้งคู่จึงต้องเป็นแหล่งเดียวกัน
    """
    rows = await session.execute(
        text(
            "SELECT con.conname, pg_get_constraintdef(con.oid) "
            "FROM pg_constraint con "
            "JOIN pg_class rel ON rel.oid = con.conrelid "
            "JOIN pg_namespace nsp ON nsp.oid = rel.relnamespace "
            "WHERE nsp.nspname = 'public' AND rel.relname = :t AND con.contype = 'c'"
        ),
        {"t": table_name},
    )
    return {name: definition for name, definition in rows.all()}


@pytest.mark.parametrize("table_name", TABLE_NAMES)
async def test_declared_check_constraints_match_the_migrated_database(
    table_name: str, db_session: AsyncSession
) -> None:
    """🔴 ตัวฆ่า mutation (b) — ถอด `CheckConstraint` ออกจาก model แล้วเทสนี้ต้องแดง

    เทียบทั้ง **ชื่อ** และ **expression ที่ PG ตีความแล้ว** สองทาง: ประกาศแล้วต้องมีจริง
    และมีจริงแล้วต้องถูกประกาศ (ถอดออกจาก model = ตกข้อหลัง)
    """
    declared = _declared_check_constraints(table_name)
    actual = await _actual_check_constraints(db_session, table_name)

    assert set(declared) == set(actual), (
        f"CHECK constraint ของ `{table_name}` ไม่ตรงกันระหว่าง model กับ DB\n"
        f"  ประกาศไว้แต่ไม่มีใน DB: {sorted(set(declared) - set(actual))}\n"
        f"  มีใน DB แต่ไม่ได้ประกาศ: {sorted(set(actual) - set(declared))}"
    )

    for name, sqltext in sorted(declared.items()):
        normalised = await _pg_normalised_expression(
            db_session, table_name, name, sqltext
        )
        expected = _canonical(actual[name].removeprefix("CHECK "))
        assert normalised == expected, (
            f"`{table_name}`.`{name}` ชื่อตรงแต่เงื่อนไขคนละอัน\n"
            f"  model ประกาศ: {normalised}\n"
            f"  DB มีจริง   : {expected}"
        )


@pytest.mark.parametrize("table_name", TABLE_NAMES)
async def test_declared_unique_constraints_match_the_migrated_database(
    table_name: str, db_session: AsyncSession
) -> None:
    """🔴 ตัวฆ่า mutation (a) — สลับคอลัมน์ของ UNIQUE โดย **คงชื่อเดิม** แล้วเทสนี้ต้องแดง

    การเช็คแค่ว่า "มี constraint ชื่อนี้อยู่" เขียวกับ mutation นั้นทุกครั้ง จึงต้องเทียบ
    ตัวคอลัมน์ **ตามลำดับ** ด้วย
    """
    declared_named, declared_unnamed = _declared_unique_constraints(table_name)
    actual_rows = await _inspector_call(
        db_session, lambda insp: insp.get_unique_constraints(table_name)
    )
    actual = {row["name"]: tuple(row["column_names"]) for row in actual_rows}

    # ตัวที่ PG ตั้งชื่อให้เอง (มาจาก Column(unique=True)) เทียบด้วยคอลัมน์ ไม่ใช่ชื่อ
    auto_named = sorted(
        columns for name, columns in actual.items() if name not in declared_named
    )
    assert auto_named == declared_unnamed, (
        f"UNIQUE ที่ไม่ได้ตั้งชื่อของ `{table_name}` ไม่ตรงกัน\n"
        f"  model ประกาศ: {declared_unnamed}\n"
        f"  DB มีจริง   : {auto_named}"
    )

    for name, columns in sorted(declared_named.items()):
        assert name in actual, (
            f"`{table_name}` ประกาศ UNIQUE `{name}` ไว้ใน model แต่ DB ไม่มี — "
            "migration ยังไม่ได้สร้าง (หรือถูก drop ไปแล้ว)"
        )
        assert columns == actual[name], (
            f"`{table_name}`.`{name}` ชื่อตรงแต่คนละคอลัมน์\n"
            f"  model ประกาศ: {columns}\n"
            f"  DB มีจริง   : {actual[name]}"
        )


@pytest.mark.parametrize("table_name", TABLE_NAMES)
async def test_declared_indexes_match_the_migrated_database(
    table_name: str, db_session: AsyncSession
) -> None:
    """index ที่ประกาศใน `__table_args__` ต้องมีจริง ครบชื่อ คอลัมน์ unique และ predicate"""
    declared = _declared_indexes(table_name)

    def _actual(insp: Inspector):
        return [
            index
            for index in insp.get_indexes(table_name)
            # index ที่ PG สร้างให้ UNIQUE constraint อัตโนมัติ ไม่ใช่ index ที่ใครประกาศ
            # — มีเทสของตัวเองอยู่แล้วข้างบน
            if not index.get("duplicates_constraint")
        ]

    actual = {
        index["name"]: (
            tuple(index["column_names"]),
            bool(index["unique"]),
            _canonical(index.get("dialect_options", {}).get("postgresql_where")),
        )
        for index in await _inspector_call(db_session, _actual)
    }

    assert set(declared) == set(actual), (
        f"index ของ `{table_name}` ไม่ตรงกันระหว่าง model กับ DB\n"
        f"  ประกาศไว้แต่ไม่มีใน DB: {sorted(set(declared) - set(actual))}\n"
        f"  มีใน DB แต่ไม่ได้ประกาศ: {sorted(set(actual) - set(declared))}"
    )
    for name in sorted(declared):
        columns, unique, where = declared[name]
        # predicate ของ partial index ต้องผ่าน parser ของ PG เหมือน CheckConstraint —
        # `status='active'` ที่คนเขียน กับ `status='active'::reservation_status` ที่ PG
        # เก็บจริง เป็นเงื่อนไขเดียวกันแต่เทียบสตริงตรง ๆ ไม่มีวันตรง
        if where is not None:
            where = await _pg_normalised_expression(
                db_session, table_name, f"where_{name}", where
            )
        assert (columns, unique, where) == actual[name], (
            f"`{table_name}`.`{name}` ชื่อตรงแต่รายละเอียดคนละอัน "
            "(คอลัมน์, unique, predicate)\n"
            f"  model ประกาศ: {(columns, unique, where)}\n"
            f"  DB มีจริง   : {actual[name]}"
        )


@pytest.mark.parametrize("table_name", TABLE_NAMES)
async def test_declared_columns_match_the_migrated_database(
    table_name: str, db_session: AsyncSession
) -> None:
    """ชื่อคอลัมน์ · `nullable` · primary key ต้องตรงกัน (ชนิดข้อมูลไม่ได้เทียบ — ดู docstring)"""
    table = Base.metadata.tables[table_name]
    declared = {column.name: column.nullable for column in table.columns}
    actual = {
        column["name"]: column["nullable"]
        for column in await _inspector_call(
            db_session, lambda insp: insp.get_columns(table_name)
        )
    }
    assert declared == actual, (
        f"คอลัมน์ของ `{table_name}` ไม่ตรงกันระหว่าง model กับ DB (ชื่อ/nullable)\n"
        f"  model ประกาศ: {declared}\n"
        f"  DB มีจริง   : {actual}"
    )

    declared_pk = tuple(column.name for column in table.primary_key.columns)
    pk_constraint = await _inspector_call(
        db_session, lambda insp: insp.get_pk_constraint(table_name)
    )
    actual_pk = tuple(pk_constraint["constrained_columns"])
    assert (
        declared_pk == actual_pk
    ), f"primary key ของ `{table_name}` ไม่ตรงกัน: {declared_pk} vs {actual_pk}"


async def test_the_comparison_actually_reaches_the_constraints_it_exists_for(
    db_session: AsyncSession,
) -> None:
    """🔴 กันเคสที่เทสข้างบนเขียวเพราะ **ไม่มีอะไรให้เทียบ**

    ถ้า `Base.metadata` ว่าง หรือ `TABLE_NAMES` ไม่มี `poster_splits` (เช่น มีคนถอด import
    ของ model ออก) เทสที่ parametrize ข้างบนจะหายไปทั้งชุดโดยไม่มีอะไรแดงเลย — เทสนี้
    ยืนยันว่า **ฝั่ง DB** มองเห็น constraint ทั้งสามตัวของ INF-25 อยู่จริง ณ เวลาที่รัน
    """
    assert "poster_splits" in TABLE_NAMES

    checks = await _actual_check_constraints(db_session, "poster_splits")
    uniques = await _inspector_call(
        db_session, lambda insp: insp.get_unique_constraints("poster_splits")
    )
    seen = set(checks) | {row["name"] for row in uniques}

    assert {
        "ck_poster_splits_piece_no_min",
        "uq_poster_splits_child_poster",
        "uq_poster_splits_parent_piece",
    } <= seen, f"DB ของเทสไม่มี constraint ของ INF-25 ครบ — เห็นแค่ {sorted(seen)}"

    # `reason` หลุดออกจากคีย์ทุกตัวแล้ว (ADR-0024 A-D5 · AC-1 ของ INF-25) — assertion
    # เชิงลบคู่กัน เพราะการ "มีครบสามตัว" ข้างบนยังเขียวได้แม้มีคีย์เก่าค้างอยู่ด้วย
    assert "uq_poster_splits_parent_reason" not in seen
