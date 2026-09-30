"""岸电接电接口：靠泊开单、插枪通电、掉电复位、拔枪结算与供电量汇总。"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from app.schemas import ActionResult, EntryPayload, PageResult
from app.services.shorepower import (
    ACTION_OUTAGE,
    ACTION_PLUG,
    ACTION_REPLUG,
    ACTION_SETTLE,
    ShorePowerService,
)

router = APIRouter(prefix="/api/shorepower", tags=["岸电接电"])

service = ShorePowerService()

LIST_FIELDS = [
    "接电单号", "泊位编号", "船舶编号", "船名", "接电箱号", "接电单状态",
    "续靠次数", "起始读数", "末次抄见数", "供电量", "掉电原因",
    "开单时间", "开单经办人", "收口时间", "收口经办人",
]
STATUSES = ["待接", "已通电", "已收口"]
ACTIONS = [ACTION_PLUG, ACTION_OUTAGE, ACTION_REPLUG, ACTION_SETTLE]


@router.get("", response_model=PageResult[dict])
def list_entries(
    keyword: str | None = Query(default=None, description="按接电单号/船舶编号/船名检索"),
    status: str | None = Query(default=None, description="待接、已通电、已收口"),
    berth: str | None = Query(default=None, description="按泊位编号筛选"),
    page: int = 1,
    size: int = 20,
) -> PageResult[dict]:
    """按船名/单号、状态、泊位过滤接电单；没有数据时返回空页，不报错。"""
    if size > 200:
        raise HTTPException(status_code=400, detail="每页最多 200 条，请缩小分页范围")
    items, total = service.list_entries(keyword=keyword, status=status, berth=berth, page=page, size=size)
    return PageResult(items=items, total=total, page=page, size=size)


@router.get("/summary")
def summary() -> dict[str, Any]:
    """供电量总览：与接电单段次同源实时重算。"""
    return {"module": "shorepower", **service.summary()}


@router.get("/export")
def export_entries() -> dict[str, Any]:
    """导出岸电接电台账全量数据（含每段供电量与处理记录）。"""
    items, total = service.list_entries(page=1, size=10000)
    return {"module": "shorepower", "total": total, "summary": service.summary(), "items": items}


@router.get("/{entry_id}", response_model=dict)
def get_entry(entry_id: int) -> dict:
    """读取单张接电单明细（含接电段与处理记录）；不存在时给出可读的错误说明。"""
    entry = service.get_entry(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"接电单 {entry_id} 不存在或已归档")
    return entry


@router.post("", response_model=ActionResult)
def open_order(payload: EntryPayload) -> ActionResult:
    """靠泊后开具接电单；同船已有未收口单据时返回第一张原单，不另开新单。"""
    entry, message, created = service.open_order(payload.values)
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry) if created else ActionResult(
        ok=False, message=message, entry=entry
    )


@router.post("/{entry_id}/actions", response_model=ActionResult)
def run_action(entry_id: int, payload: EntryPayload) -> ActionResult:
    """执行插枪通电、掉电复位、重新插枪、拔枪结算；不允许的流转会被拦下并说明原因。"""
    action = str(payload.values.get("action") or "").strip()
    params = {k: v for k, v in payload.values.items() if k != "action"}
    entry, message = service.run_action(entry_id, action, params)
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)
