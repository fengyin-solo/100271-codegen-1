"""港口集装箱作业管理平台 后端服务入口。

启动：uvicorn app.main:app --host 127.0.0.1 --port 8000
健康检查：GET /api/health
"""
from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.routers import ROUTERS
from app.services.shorepower import ShorepowerService
from app.store import store

app = FastAPI(title="港口集装箱作业管理平台", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

for module in ROUTERS:
    app.include_router(module.router)


@app.get("/api/health")
def health() -> dict[str, object]:
    """健康检查：确认服务已经监听、示例数据已经就绪。"""
    return {"ok": True, "app": settings.app_name, "modules": len(store.module_names())}


@app.get("/api/overview")
def overview() -> dict[str, object]:
    """运营概览：把各业务模块的待处理量汇总成看板卡片。"""
    data = store.overview()
    # 岸电供电量跟随接电单实时重算，单独给一组卡片，月底对账直接看这里。
    shore = ShorepowerService().summary()
    data["shorepower"] = shore
    data["cards"] = [
        *data["cards"],
        {"label": "岸电累计供电量(度)", "value": shore["total_kwh"]},
        {"label": "在供接电单", "value": shore["energized"]},
        {"label": "掉电回退(次)", "value": shore["outage_count"]},
    ]
    return data
