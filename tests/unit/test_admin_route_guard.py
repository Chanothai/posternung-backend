"""ด่านที่สองของสิทธิ์แอดมิน — ADR-0031 D3 แถว 3/4 · D4 ข้อ 1 · D5 · D6.1 · INF-35

สามอย่างในไฟล์เดียวเพราะทั้งหมดเป็น "ด่านที่ตรวจโครงสร้าง ไม่ใช่ตรวจพฤติกรรมของ
request ใด request หนึ่ง":

1. closed-world ระดับ route table — ทุก route ของแอดมินต้องมี `require_admin`
   ในสายพึ่งพา **รวม route ที่ยังไม่มีใครเขียน** (D5)
2. AST scan — ไม่มี default ที่แปลว่า "อนุญาต" อยู่บนเส้นทางสิทธิ์เลย (D4 ข้อ 1)
3. ไม่มีอีเมลของแอดมินคนแรกเป็น literal ในโค้ด (D6.1)

🔴 **กับดักสองข้อที่ทำให้เทสแบบนี้เขียวโดยไม่ได้ตรวจอะไร — เขียนไว้กันคนแก้ผิดทาง**

  ก. `app/main.py` mount ด้วย `prefix="/api/v1"` ⇒ path จริงคือ `/api/v1/admin/...`
     เทสที่หา `startswith("/admin")` จะเจอ **ศูนย์ route แล้วเขียวตลอดกาล**
  ข. `dependencies` ที่ประกาศไว้ไม่เคยบอก dependency ที่ **ซ้อนอยู่ข้างใน** —
     `get_current_user` ไม่เคยถูกประกาศที่ route หรือที่ router เลย มันมาถึงเพราะ
     `require_admin` พึ่งมันอีกที ⇒ ต้องเดิน `dependant` แบบ recursive
     (ใน FastAPI 0.139 router-level dependency **โผล่** ที่ `dependencies` ของ context
     แล้ว ต่างจากรุ่นก่อน — แต่ตัวที่ซ้อนยังไม่โผล่อยู่ดี ด่านจึงยังต้องเดินต้นไม้)
  ค. 🔴 **FastAPI 0.139 ไม่ flatten route ที่ include เข้า `app.routes` อีกแล้ว** —
     เก็บเป็น `_IncludedRouter` ที่ต้องเรียก `effective_candidates()` ถึงจะเห็นเส้นข้างใน
     ⇒ เทสที่วน `app.routes` ตรง ๆ จะเจอแค่ `/health` กับ `/ready` แล้วเขียวตลอดกาล
     (เจอจริงตอนเขียนรอบนี้ — จับได้เพราะ assertion กันโมฆะข้างล่าง ไม่ใช่เพราะโค้ดผิด)

`test_guard_itself_catches_an_unprotected_admin_route` คือตัวพิสูจน์ว่าด่านนี้จับได้จริง
ไม่ได้ผ่านเพราะไม่มีอะไรให้จับ (ทรงเดียวกับ `test_no_card_data_in_schema.py`)
"""

from __future__ import annotations

import ast
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import APIRouter, Depends, FastAPI

from app.api.deps import get_current_user, require_admin
from app.core.exceptions import AdminRequired
from app.main import app

REPO_ROOT = Path(__file__).resolve().parents[2]
_THIS_FILE = Path(__file__).resolve()

# path จริงหลัง mount — ไม่ใช่ "/admin" (ดูกับดักข้อ ก. ข้างบน)
ADMIN_PATH_PREFIX = "/api/v1/admin"

# อีเมลแอดมินคนแรกตาม ADR-0031 D6.1 — เป็นข้อมูลนำเข้าของการรันสคริปต์
# ไฟล์เทสนี้คือ **ที่เดียว** ที่ยอมให้มี literal นี้ได้ (มันคือสิ่งที่กำลังตรวจหา)
FIRST_ADMIN_EMAIL = "frameshine.th@gmail.com"


# ───────────────────────── helper ─────────────────────────


def _iter_route_specs(application: FastAPI) -> list[tuple[str, object, object]]:
    """คืน (path จริงหลัง mount, dependant, ตัว route/context) ของทุกเส้นในแอป

    รองรับทั้งทรงเดิม (APIRoute อยู่ใน app.routes ตรง ๆ) และทรงของ FastAPI 0.139
    (_IncludedRouter → effective_candidates() → _EffectiveRouteContext)
    ถ้าเวอร์ชันหน้าเปลี่ยนกลับไป flatten เหมือนเดิม ตัวนี้ก็ยังใช้ได้ — ดูกับดักข้อ ค.
    """
    specs: list[tuple[str, object, object]] = []
    stack: list = list(application.routes)
    while stack:
        item = stack.pop()
        candidates = getattr(item, "effective_candidates", None)
        if callable(candidates):
            stack.extend(candidates())
            continue
        path = getattr(item, "path", None)
        dependant = getattr(item, "dependant", None)
        if isinstance(path, str) and dependant is not None:
            specs.append((path, dependant, item))
    return specs


def _dependency_calls(dependant) -> list:
    """ไล่ทุก dependency ที่จะถูกเรียกจริง (recursive) — ดูกับดักข้อ ข."""
    calls: list = []
    stack = [dependant]
    while stack:
        dep = stack.pop()
        if dep.call is not None:
            calls.append(dep.call)
        stack.extend(dep.dependencies)
    return calls


def _admin_specs(application: FastAPI) -> list[tuple[str, object, object]]:
    return [
        spec
        for spec in _iter_route_specs(application)
        if spec[0].startswith(ADMIN_PATH_PREFIX)
    ]


def _admin_routes_missing_guard(application: FastAPI) -> list[str]:
    return [
        path
        for path, dependant, _ in _admin_specs(application)
        if require_admin not in _dependency_calls(dependant)
    ]


def _iter_python_files(*scan_dirs: str) -> list[Path]:
    files: list[Path] = []
    for scan_dir in scan_dirs:
        root = REPO_ROOT / scan_dir
        if not root.is_dir():
            continue
        for path in root.rglob("*.py"):
            if path.resolve() == _THIS_FILE:
                continue
            files.append(path)
    return files


# ───────────────── D5 — closed-world ระดับ route table ─────────────────


def test_there_is_at_least_one_admin_route_to_check() -> None:
    """กันเทสทั้งไฟล์นี้กลายเป็นโมฆะ

    ถ้าไม่มี route แอดมินสักเส้น เทสข้างล่างจะวนลูปศูนย์รอบแล้วเขียว — ซึ่งแปลว่า
    ไม่มีการเปลี่ยนโค้ดแบบใดเลยที่ทำให้มันแดงได้ · ข้อนี้ยังจับกับดัก prefix ผิด
    (`/admin` แทน `/api/v1/admin`) ได้ด้วย เพราะทั้งสองอาการให้ผลเป็นศูนย์เหมือนกัน
    """
    routes = _admin_specs(app)
    assert routes, (
        f"ไม่พบ route ที่ path ขึ้นต้นด้วย {ADMIN_PATH_PREFIX} เลย — "
        "อาจเป็นเพราะ prefix ที่ใช้ค้นผิด หรือ admin router ไม่ได้ถูก mount"
    )


def test_every_admin_route_has_require_admin_in_its_dependency_chain() -> None:
    unprotected = _admin_routes_missing_guard(app)
    assert unprotected == [], (
        "route แอดมินที่ไม่มี require_admin ในสายพึ่งพา: "
        + ", ".join(unprotected)
        + "\nADR-0031 D2 — ผูกที่ APIRouter(dependencies=[...]) ไม่ใช่รายเส้น"
    )


def test_guard_itself_catches_an_unprotected_admin_route() -> None:
    """พิสูจน์ว่าด่านข้างบนจับได้จริง ไม่ได้ผ่านเพราะไม่มีอะไรให้จับ

    ประกอบแอปปลอมที่มี route แอดมิน 1 เส้นซึ่ง **ลืมผูก** require_admin
    ถ้า `_admin_routes_missing_guard` คืนลิสต์ว่าง แปลว่าตัวตรวจเสีย
    """
    fake = FastAPI()
    router = APIRouter(prefix="/admin")

    @router.get("/forgot-the-guard")
    async def _forgot() -> dict:
        return {}

    fake.include_router(router, prefix="/api/v1")

    assert _admin_routes_missing_guard(fake) == ["/api/v1/admin/forgot-the-guard"]


def test_guard_walks_the_dependency_tree_not_only_declared_dependencies() -> None:
    """ล็อกกับดักข้อ ข. — ตัวตรวจต้องเดินต้นไม้ ไม่ใช่อ่านรายการที่ประกาศไว้

    `get_current_user` ไม่เคยถูกประกาศที่ route หรือที่ router สักที่ — มันอยู่ในสาย
    เพราะ `require_admin` พึ่งมันอีกทอด ถ้าใครเปลี่ยน `_dependency_calls` ไปอ่านแค่
    `dependencies` ที่ประกาศไว้ เทสข้อนี้จะแดงทันที ส่วนเทสอื่นจะยังเขียวหมด
    """
    admin_specs = _admin_specs(app)
    assert admin_specs, "ไม่มี route แอดมินให้ตรวจ"
    _, dependant, route = admin_specs[0]
    calls = _dependency_calls(dependant)

    assert require_admin in calls
    assert get_current_user in calls, (
        "ไม่เห็น get_current_user ในสายพึ่งพา — ตัวตรวจอ่านแค่ระดับบนสุด "
        "จะพลาด dependency ที่ซ้อนลึกทั้งหมด"
    )
    declared = [d.dependency for d in getattr(route, "dependencies", [])]
    assert get_current_user not in declared, (
        "สมมติฐานของเทสนี้เปลี่ยนไป — get_current_user โผล่ในรายการที่ประกาศไว้แล้ว "
        "ให้ทบทวนว่าคำเตือนกับดักข้อ ข. ยังจริงไหม"
    )


def test_admin_router_binds_the_guard_at_router_level_not_per_route() -> None:
    """🔴 ถ้าย้าย require_admin จาก APIRouter ไปผูกรายเส้น เทสนี้จะแดง — และมีแค่ข้อนี้

    เทสอื่นทั้งหมดจะยังเขียว เพราะ /admin/me ประกาศ Depends(require_admin) ไว้ที่
    signature ของตัวเองด้วย ⇒ closed-world ยังผ่าน · แต่ endpoint ตัวถัดไปที่ใครเพิ่ม
    จะไม่ถูกป้องกันอีกต่อไป ซึ่งเป็นสิ่งเดียวที่ ADR-0031 D2 ต้องการรับประกัน
    """
    from app.api.v1.admin import router as admin_router

    bound = [d.dependency for d in admin_router.dependencies]
    assert require_admin in bound, (
        "admin router ไม่ได้ผูก require_admin ที่ระดับ APIRouter — "
        "ADR-0031 D2 บังคับให้ผูกที่ระดับ router เพื่อให้ endpoint ที่เพิ่มทีหลัง "
        "ถูกป้องกันเพราะโครงสร้าง ไม่ใช่เพราะคนเขียนจำได้"
    )


def test_router_level_binding_is_what_protects_future_endpoints() -> None:
    """route แอดมินที่ไม่ได้ผูก dependency รายเส้นเลย ต้องยังถูกป้องกัน (ADR-0031 D2)

    นี่คือคุณสมบัติที่ทำให้ endpoint ตัวที่เพิ่มทีหลังปลอดภัยโดยไม่ต้องพึ่งความจำ
    """
    fake = FastAPI()
    router = APIRouter(prefix="/admin", dependencies=[Depends(require_admin)])

    @router.get("/bound-at-router")
    async def _bound() -> dict:
        return {}

    fake.include_router(router, prefix="/api/v1")

    assert _admin_routes_missing_guard(fake) == []


def test_no_sub_application_is_mounted_under_the_admin_prefix() -> None:
    """ปิดจุดบอดของ closed-world — `app.mount()` หลุดด่านทั้งก้อนอย่างเงียบ ๆ

    `_iter_route_specs` เก็บเฉพาะสิ่งที่มีทั้ง `path` และ `dependant` · `Mount` มี
    `path` แต่ไม่มี `dependant` และไม่มี `effective_candidates()` ⇒ sub-app ที่ mount
    ไว้ใต้ `/api/v1/admin/...` จะไม่ถูกไล่ตรวจเลย และ `require_admin` ก็ไม่ครอบมันด้วย
    (dependency ของ APIRouter ไม่ตกทอดข้าม Mount)

    วันนี้ไม่มี `Mount` ในแอป — ข้อนี้จึงเป็นด่านกันอนาคต ไม่ใช่การแก้บั๊กที่มีอยู่
    """
    mounted = [
        route.path
        for route in app.routes
        if type(route).__name__ == "Mount"
        and str(getattr(route, "path", "")).startswith(ADMIN_PATH_PREFIX)
    ]
    assert mounted == [], (
        "มี sub-application mount ไว้ใต้เส้นทางแอดมิน: "
        + ", ".join(mounted)
        + "\nrequire_admin ที่ผูกกับ APIRouter ไม่ครอบ Mount — ต้องมีด่านของตัวเอง"
    )


# ─────────── D3 แถว 3/4 — None และ attribute ที่ไม่มี = ไม่ใช่แอดมิน ───────────


@pytest.mark.parametrize(
    "current_user",
    [
        pytest.param(SimpleNamespace(is_admin=None), id="is_admin-is-None"),
        pytest.param(SimpleNamespace(is_admin=False), id="is_admin-is-False"),
        pytest.param(SimpleNamespace(), id="attribute-missing"),
        pytest.param(SimpleNamespace(is_admin="true"), id="truthy-string-is-not-True"),
        pytest.param(SimpleNamespace(is_admin=1), id="int-1-is-not-True"),
    ],
)
async def test_non_true_permission_value_is_rejected(current_user) -> None:
    """🔴 `None` = ไม่ใช่แอดมิน ห้ามตีความว่า "ยังไม่รู้" แล้วปล่อยผ่าน (D3 แถว 3)

    เคสเหล่านี้บังคับผ่าน DB ไม่ได้เพราะคอลัมน์เป็น NOT NULL — แต่ค่ามาถึง
    require_admin ได้ทางอื่น (object ที่ยังไม่ flush, การ refactor ในอนาคต)
    ด่านจึงต้องยืนบนค่าที่รับมาจริง ไม่ใช่บนสมมติฐานว่า DB จะกันให้
    """
    with pytest.raises(AdminRequired):
        await require_admin(current_user=current_user)


async def test_true_permission_value_passes_and_returns_the_user() -> None:
    """เคสบวก — ไม่มีข้อนี้ ด่านที่ปฏิเสธทุกอย่างก็ผ่านเทสข้างบนครบ"""
    user = SimpleNamespace(is_admin=True)
    assert await require_admin(current_user=user) is user


def test_d3_row_4_revoked_grant_is_not_applicable_under_a1() -> None:
    """D3 แถว 4 (`revoked_at` ของแถว grant) — **ไม่ applicable ภายใต้ D1 = A-1**

    เขียนไว้เป็นเทสแทนที่จะเงียบ เพราะวันที่ระบบย้ายไปตาราง `admin_grants` (A-3)
    ตามเงื่อนไขย้ายบ้านของ ADR-0031 D1 แถวนี้จะกลับมาบังคับใช้ทันที และคนที่ย้าย
    ต้องเห็นว่ามีข้อนี้ค้างอยู่ · ข้อนี้จะแดงเองเมื่อ `admin_grants` เกิดขึ้นจริง
    """
    from app.core.database import Base

    assert "admin_grants" not in Base.metadata.tables, (
        "มีตาราง admin_grants แล้ว — ระบบย้ายไป A-3 ⇒ D3 แถว 4 กลับมาบังคับใช้ "
        "ต้องเพิ่มเทสว่าแถว grant ที่ revoked_at ไม่ว่าง ได้ 403"
    )


# ───────────── D4 ข้อ 1 — ไม่มี default ที่แปลว่า "อนุญาต" ─────────────

_PERMISSION_KEYS = {"is_admin", "role", "admin", "is_superuser", "is_staff"}


def _permissive_defaults(tree: ast.AST) -> list[str]:
    """หา default ที่แปลว่า "อนุญาต" บนเส้นทางสิทธิ์

    ครอบสามทรงที่ ADR-0031 D4 ข้อ 1 ห้ามไว้ตรงตัว:
      getattr(user, "is_admin", True) · payload.get("role", "admin") · ... or True
    """
    found: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue

        # getattr(obj, "<perm-key>", <default ที่ไม่ใช่ False/None>)
        if (
            isinstance(node.func, ast.Name)
            and node.func.id == "getattr"
            and len(node.args) == 3
            and isinstance(node.args[1], ast.Constant)
            and node.args[1].value in _PERMISSION_KEYS
        ):
            default = node.args[2]
            if not (
                isinstance(default, ast.Constant) and default.value in (False, None)
            ):
                found.append(f"line {node.lineno}: getattr(..., default ที่ไม่ปฏิเสธ)")

        # <mapping>.get("<perm-key>", <default ที่เป็นความจริง>)
        if (
            isinstance(node.func, ast.Attribute)
            and node.func.attr == "get"
            and node.args
            and isinstance(node.args[0], ast.Constant)
            and node.args[0].value in _PERMISSION_KEYS
            and len(node.args) == 2
            and isinstance(node.args[1], ast.Constant)
            and bool(node.args[1].value)
        ):
            found.append(f"line {node.lineno}: .get(<perm>, <ค่าที่แปลว่าอนุญาต>)")

    # `<อะไรก็ตาม> or True` — ผลลัพธ์เป็น True เสมอ ไม่มีเหตุผลที่ถูกต้องบนเส้นสิทธิ์
    for node in ast.walk(tree):
        if isinstance(node, ast.BoolOp) and isinstance(node.op, ast.Or):
            if any(
                isinstance(v, ast.Constant) and v.value is True for v in node.values
            ):
                found.append(f"line {node.lineno}: `... or True`")
    return found


def test_no_permissive_default_on_any_permission_path() -> None:
    offenders: dict[str, list[str]] = {}
    for path in _iter_python_files("app", "scripts"):
        hits = _permissive_defaults(ast.parse(path.read_text(encoding="utf-8")))
        if hits:
            offenders[str(path.relative_to(REPO_ROOT))] = hits
    assert offenders == {}, (
        "พบ default ที่แปลว่า 'อนุญาต' บนเส้นทางสิทธิ์ (ADR-0031 D4 ข้อ 1):\n"
        + "\n".join(f"  {f}: {h}" for f, h in offenders.items())
    )


def test_permissive_default_scanner_actually_catches_each_forbidden_shape() -> None:
    """ตัวสแกนต้องจับได้ทั้งสามทรง ไม่งั้นเทสข้างบนคือกระดาษเปล่า"""
    for source in (
        'x = getattr(user, "is_admin", True)',
        'x = payload.get("role", "admin")',
        "x = user.is_admin or True",
    ):
        assert _permissive_defaults(ast.parse(source)), f"สแกนไม่เจอ: {source}"

    for safe in (
        'x = getattr(user, "is_admin", False)',
        'x = getattr(user, "is_admin", None)',
        'x = payload.get("role")',
    ):
        assert _permissive_defaults(ast.parse(safe)) == [], f"false positive: {safe}"


# ───────────── D6.1 — ห้าม hardcode อีเมลแอดมินคนแรก ─────────────


def test_first_admin_email_is_never_a_literal_in_code() -> None:
    """อีเมลแอดมินคนแรกต้องมาทาง --email เสมอ (ADR-0031 D6.1)

    ถ้า hardcode ไว้ มันจะกลายเป็นบัญชีที่ถูกตั้งเป็นแอดมินซ้ำทุกครั้งที่มีคนรัน
    สคริปต์ ซึ่งเป็นสิ่งที่ D6-c เขียนขึ้นมาป้องกันพอดี
    """
    offenders = [
        str(path.relative_to(REPO_ROOT))
        for path in _iter_python_files("app", "scripts")
        if FIRST_ADMIN_EMAIL in path.read_text(encoding="utf-8")
    ]
    assert offenders == [], (
        f"เจอ {FIRST_ADMIN_EMAIL} เป็น literal ใน: {', '.join(offenders)} — "
        "ต้องรับผ่าน --email เท่านั้น"
    )
