"""Pydantic v2 schemas ของเส้นทางแอดมิน (ตรง ../posternung-workspace/docs/api/openapi.yaml).

🔴 แยกไฟล์จาก schemas/auth.py โดยตั้งใจ — UserResponse ของ /auth/me ต้องไม่โตตาม
สิทธิ์ที่เพิ่มเข้ามา (ADR-0031 ไม่ได้เปิด is_admin ให้เส้นสาธารณะ)
"""

import uuid

from pydantic import BaseModel, Field


class AdminMeResponse(BaseModel):
    """ผลของ GET /admin/me — operationId getAdminMe."""

    user_id: uuid.UUID
    # เป็น True เสมอ: ถ้าไม่ใช่แอดมินจะไม่ถึงตัว handler เพราะ require_admin ตอบ 403
    # ไปก่อนแล้ว (ADR-0031 D2)
    #
    # 🔴 ห้ามใส่ `default=True` — Pydantic จะถอดฟิลด์ออกจาก `required` ทันที ทำให้
    # `openapi.json` ได้ `required: [user_id]` ขณะที่สัญญาเขียน `required: [user_id, is_admin]`
    # เป็น drift ที่ `check-contract-drift.py` มองไม่เห็นเพราะยังไม่เทียบ `required`
    # (พบตอนรีวิว INF-35 — บันทึกเป็น known_gap ของ INF-31 แล้ว)
    is_admin: bool = Field(json_schema_extra={"enum": [True]})
