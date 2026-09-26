"""冷藏箱监控接口：维护冷藏箱，覆盖温度报警、调整设定、断电处置等动作。"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from app.schemas import ActionResult, EntryPayload, PageResult
from app.services.coldchain import ColdchainService

router = APIRouter(prefix="/api/coldchain", tags=["冷藏箱监控"])

service = ColdchainService()

LIST_FIELDS = ["冷藏箱号", "设定温度", "当前温度", "运行电流", "插电桩号", "温度偏差", "报警记录", "监控状态"]
STATUSES = ["温度正常", "温度偏高", "温度偏低", "已断电"]


@router.get("", response_model=PageResult[dict])
def list_entries(
    keyword: str | None = Query(default=None, description="按冷藏箱号检索"),
    status: str | None = Query(default=None, description="温度正常、温度偏高、温度偏低、已断电"),
    page: int = 1,
    size: int = 20,
) -> PageResult[dict]:
    """按冷藏箱号与状态过滤冷藏箱监控列表；没有数据时返回空页，不报错。"""
    if size > 200:
        raise HTTPException(status_code=400, detail="每页最多 200 条，请缩小分页范围")
    items, total = service.list_entries(keyword=keyword, status=status, page=page, size=size)
    return PageResult(items=items, total=total, page=page, size=size)


@router.get("/{entry_id}", response_model=dict)
def get_entry(entry_id: int) -> dict:
    """读取单条冷藏箱明细；不存在时给出可读的错误说明。"""
    entry = service.get_entry(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"冷藏箱 {entry_id} 不存在或已归档")
    return entry


@router.post("", response_model=ActionResult)
def create_entry(payload: EntryPayload) -> ActionResult:
    """登记一条冷藏箱，缺字段时说明原因而不是静默丢弃。"""
    entry, missing = service.create_entry(payload.values)
    if missing:
        return ActionResult(ok=False, message=f"缺少必填字段：{'、'.join(missing)}")
    return ActionResult(ok=True, message="冷藏箱已登记", entry=entry)


@router.post("/{entry_id}/actions", response_model=ActionResult)
def run_action(entry_id: int, payload: EntryPayload) -> ActionResult:
    """对单条冷藏箱执行温度报警、调整设定、断电处置；不允许的动作会被拦下并说明原因。"""
    action = str(payload.values.get("action") or "").strip()
    entry, message = service.run_action(entry_id, action)
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)


@router.get("/export")
def export_entries() -> dict[str, Any]:
    """导出冷藏箱监控清单：返回当前过滤条件下的全量数据。"""
    items, total = service.list_entries(page=1, size=10000)
    return {"module": "coldchain", "total": total, "items": items}
