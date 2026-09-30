"""内存数据仓库：给每个业务模块准备一份可筛选、可流转的示例数据。

真实项目里这里会换成数据库访问层；当前实现只依赖标准库，保证克隆下来就能起。
"""
from __future__ import annotations

from decimal import Decimal
from typing import Any

from app.seed import SEED_ROWS

SHOREPOWER_MODULE = "shorepower"


class Store:
    def __init__(self) -> None:
        self._tables: dict[str, list[dict[str, Any]]] = {
            name: [dict(row) for row in rows] for name, rows in SEED_ROWS.items()
        }

    def module_names(self) -> list[str]:
        return sorted(self._tables)

    def rows(self, module: str) -> list[dict[str, Any]]:
        return self._tables.setdefault(module, [])

    def find(self, module: str, entry_id: int) -> dict[str, Any] | None:
        for row in self.rows(module):
            if int(row.get("id", 0)) == entry_id:
                return row
        return None

    def shorepower_total_kwh(self) -> Decimal:
        """岸电总供电量：按已结算的接电段段供电量累加，随接电单一起重算。"""
        total = Decimal("0")
        for row in self.rows(SHOREPOWER_MODULE):
            for segment in row.get("接电段", []):
                kwh = segment.get("段供电量")
                if kwh is not None:
                    total += Decimal(str(kwh))
        return total

    def overview(self) -> dict[str, object]:
        modules: list[dict[str, object]] = []
        for name in self.module_names():
            rows = self.rows(name)
            module_item = {
                "name": name,
                "created": len(rows),
                "pending": sum(1 for row in rows if row.get("pending")),
                "abnormal": sum(1 for row in rows if row.get("abnormal")),
            }
            if name == SHOREPOWER_MODULE:
                # 供电量是岸电台账的核心指标，总览直接跟接电段同源重算。
                module_item["supply_kwh"] = float(self.shorepower_total_kwh())
            modules.append(module_item)
        shorepower_rows = self.rows(SHOREPOWER_MODULE)
        cards = [
            {"label": "业务模块", "value": len(modules)},
            {"label": "今日新增", "value": sum(int(item["created"]) for item in modules)},
            {"label": "待处理", "value": sum(int(item["pending"]) for item in modules)},
            {"label": "岸电累计供电量(度)", "value": float(self.shorepower_total_kwh())},
            {
                "label": "岸电异常/掉电单数",
                "value": sum(1 for row in shorepower_rows if row.get("abnormal")),
            },
        ]
        return {"cards": cards, "modules": modules}


store = Store()
