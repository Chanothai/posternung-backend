"""เส้นทางแอดมิน — ทุก endpoint ในไฟล์นี้อยู่หลัง require_admin (ADR-0031 D2).

🔴 **อย่าย้าย dependencies=[...] ออกจาก APIRouter ไปผูกรายเส้นเด็ดขาด** — เหตุผลทั้งหมด
ของการผูกที่ระดับ router คือ endpoint แอดมินตัวที่เพิ่มทีหลังต้องถูกป้องกัน
**เพราะโครงสร้าง ไม่ใช่เพราะคนเขียนจำได้** · มีเทส closed-world คุมข้อนี้อยู่ที่
`tests/unit/test_admin_route_guard.py` (ADR-0031 D5)

🔴 **handler ในไฟล์นี้ต้องพึ่ง `get_current_user` ไม่ใช่ `require_admin`** — ฟังดูกลับหัว
แต่จงใจ: ถ้า handler ประกาศ `Depends(require_admin)` เองด้วย มันจะ *อุ้มพฤติกรรมไว้*
ทำให้การถอดด่านออกจาก router ไม่มีเทสไหนแดงนอกจากเทสโครงสร้างตัวเดียว
· พิสูจน์แล้วตอนรีวิว INF-35: ถอด `dependencies` ออกจาก router แล้ว
  - handler พึ่ง `require_admin` → แดง **1** เทส
  - handler พึ่ง `get_current_user` → แดง **9** เทส
  ⇒ ทางหลังทำให้ router-level binding *แบกพฤติกรรมจริง* ไม่ใช่แค่มีเทสเฝ้า

endpoint แอดมินที่ **เปลี่ยนสถานะ** (อนุมัติ listing · ยืนยันเงินเข้า · ตัดสิน dispute ·
payout) ตาม BR-L6/BR-P2/BR-P6 ยังไม่เข้ามาที่นี่ — รูป request/response ของมันเป็น
ฟังก์ชันของ state machine ที่ยังไม่มี (INF-33) จึงเป็นงานของรอบ SCR-15 + INF-33
"""

from fastapi import APIRouter, Depends

from app.api.deps import get_current_user, require_admin
from app.models.user import User
from app.schemas.admin import AdminMeResponse

router = APIRouter(
    prefix="/admin",
    tags=["Admin"],
    dependencies=[Depends(require_admin)],
)


@router.get("/me", response_model=AdminMeResponse)
async def get_admin_me(
    current_user: User = Depends(get_current_user),
) -> AdminMeResponse:
    """ตรวจว่า token ที่แนบมามีสิทธิ์แอดมินหรือไม่ — operationId getAdminMe.

    อ่านอย่างเดียว ไม่แตะตารางของ order/listing/payment ⇒ ไม่พึ่ง INF-33

    ถึงตัวนี้ได้แปลว่าผ่าน `require_admin` ที่ผูกไว้ระดับ router มาแล้ว (ดู docstring
    ของไฟล์ว่าทำไม handler ถึงไม่ประกาศ `require_admin` ซ้ำ) · `is_admin` จึงเป็น
    `True` เสมอโดยนิยาม ไม่ใช่ค่าที่อ่านมาจากที่ไหนอีกที
    """
    return AdminMeResponse(user_id=current_user.id, is_admin=True)
