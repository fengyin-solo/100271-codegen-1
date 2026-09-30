"""岸电接电台账接口。

路由层只做参数接收与结果包装；接电单状态机、幂等开单、复靠延续、抄见数计量
等业务判断全部在 ShorepowerService。
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from app.schemas import ActionResult, PageResult
from app.services.shorepower import ShorepowerError, ShorepowerService

router = APIRouter(prefix="/api/shorepower", tags=["岸电接电"])

service = ShorepowerService()

STATUSES = ["待接", "已通电", "已结算"]
ACTIONS = ["插枪通电", "中途掉电", "拔枪结算"]


class ShorepowerCreate(BaseModel):
    vessel_code: str | None = None   # 船舶编号
    vessel_name: str | None = None   # 船名（编号、船名至少填一个）
    berth_code: str | None = None    # 泊位
    box_code: str | None = None      # 接电箱
    voyage: str | None = None        # 航次
    operator: str | None = None      # 开单当班人


class ShorepowerAction(BaseModel):
    action: str                      # 插枪通电 / 中途掉电 / 拔枪结算
    meter_reading: float | None = None  # 插枪通电：起始（或恢复时）抄见数
    meter_end: float | None = None      # 拔枪结算：结算抄见数
    gun_count: int | None = None        # 插接枪数（插了几条）
    reason: str | None = None           # 中途掉电原因
    operator: str | None = None         # 操作当班人


@router.get("/summary")
def summary() -> dict[str, Any]:
    """岸电总览：供电量跟随接电单实时重算。"""
    return service.summary()


@router.get("/ledger")
def vessel_ledger() -> dict[str, Any]:
    """随船走动的台账：按船归集全部接电单与累计供电量。"""
    books = service.vessel_ledger()
    return {"items": books, "total": len(books)}


@router.get("/events")
def list_events(
    vessel: str | None = Query(default=None, description="按船名/编号检索"),
    operator: str | None = Query(default=None, description="按当班处理人检索"),
    shift: str | None = Query(default=None, description="按工班检索"),
) -> dict[str, Any]:
    """操作审计：交班后仍可按船、按当班人、按工班追溯每一次状态切换。"""
    items = service.list_events(vessel=vessel, operator=operator, shift=shift)
    return {"items": items, "total": len(items)}


@router.get("", response_model=PageResult[dict])
def list_entries(
    keyword: str | None = Query(default=None, description="接电单号/船名/泊位/接电箱"),
    status: str | None = Query(default=None, description="待接、已通电、已结算"),
    page: int = 1,
    size: int = 20,
) -> PageResult[dict]:
    """按关键字与状态过滤接电单；没有数据时返回空页，不报错。"""
    if size > 200:
        raise HTTPException(status_code=400, detail="每页最多 200 条，请缩小分页范围")
    if status and status not in STATUSES:
        raise HTTPException(status_code=400, detail=f"状态只能是：{'、'.join(STATUSES)}")
    items, total = service.list_entries(keyword=keyword, status=status, page=page, size=size)
    return PageResult(items=items, total=total, page=page, size=size)


@router.get("/{entry_id}/events", response_model=dict)
def entry_events(entry_id: int) -> dict[str, Any]:
    """一张接电单的完整操作轨迹（谁、在哪个工班、何时做了什么）。"""
    if service.get_entry(entry_id) is None:
        raise HTTPException(status_code=404, detail=f"接电单 {entry_id} 不存在或已归档")
    items = service.events_for(entry_id)
    return {"items": items, "total": len(items)}


@router.get("/{entry_id}", response_model=dict)
def get_entry(entry_id: int) -> dict[str, Any]:
    """读取单张接电单明细；不存在时给出可读的错误说明。"""
    entry = service.get_entry(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"接电单 {entry_id} 不存在或已归档")
    return entry


@router.post("", response_model=ActionResult)
def create_entry(payload: ShorepowerCreate) -> ActionResult:
    """靠泊后在接电箱开单；同船未收口时幂等返回首张，同泊位复靠时延续上一张。"""
    values = payload.model_dump()
    try:
        entry, message = service.create_entry(values)
        return ActionResult(ok=True, message=message, entry=entry)
    except ShorepowerError as exc:
        return ActionResult(ok=False, message=str(exc))


@router.post("/{entry_id}/actions", response_model=ActionResult)
def run_action(entry_id: int, payload: ShorepowerAction) -> ActionResult:
    """插枪通电 / 中途掉电 / 拔枪结算；非法流转会被拦下并说明原因。"""
    values = payload.model_dump()
    try:
        entry, message = service.run_action(entry_id, values)
        return ActionResult(ok=True, message=message, entry=entry)
    except ShorepowerError as exc:
        return ActionResult(ok=False, message=str(exc))
