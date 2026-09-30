"""岸电接电台账业务规则。

接电单的状态机、同船幂等开单、同泊位复靠延续、电表抄见数计量、掉电回退、
当班操作审计与总览供电量重算都收在这里，路由层不做业务判断。

状态流转：

    开单 ──▶ 待接 ──插枪成功(填起始抄见数/枪数)──▶ 已通电
                    ▲                              │
                    └────────中途掉电(注明原因)─────┤
                                                   │
                              拔枪结算(填结算抄见数) ──▶ 已结算（收口）

约束：
- 同一艘船存在未收口（待接/已通电）接电单时，重复开单只返回第一张，不另开。
- 同一船在同一泊位复靠（上一张已收口）时，新单延续上一张，串成同一条台账链。
- 中途掉电只能从「已通电」退回「待接」并注明原因，退回后不允许直接结算。
- 结算必须在「已通电」状态，且结算抄见数必填、不小于起始抄见数。
- 供电量一律由「结算抄见数 - 起始抄见数」重算，不接受手填度数。
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from app.store import store

MODULE = "shorepower"
EVENTS_MODULE = "_shorepower_events"

STATUS_WAITING = "待接"
STATUS_ON = "已通电"
STATUS_SETTLED = "已结算"
ACTIVE_STATUSES = {STATUS_WAITING, STATUS_ON}


class ShorepowerError(ValueError):
    """业务校验不通过：message 直接回给前端，不抛 500。"""


class ShorepowerService:
    # ------------------------------------------------------------------ 查询
    def list_entries(
        self,
        *,
        keyword: str | None = None,
        status: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        rows = store.rows(MODULE)
        if status:
            rows = [row for row in rows if row.get("status") == status]
        if keyword:
            key = keyword.strip()
            rows = [
                row
                for row in rows
                if key in str(row.get("order_no", ""))
                or key in str(row.get("vessel_name", ""))
                or key in str(row.get("vessel_code", ""))
                or key in str(row.get("berth_code", ""))
                or key in str(row.get("box_code", ""))
            ]
        rows = sorted(rows, key=lambda row: int(row.get("id", 0)), reverse=True)
        total = len(rows)
        start = max(page - 1, 0) * size
        return rows[start:start + size], total

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        return store.find(MODULE, entry_id)

    def events_for(self, entry_id: int) -> list[dict[str, Any]]:
        return [
            dict(event)
            for event in store.rows(EVENTS_MODULE)
            if int(event.get("order_id", 0)) == entry_id
        ]

    def list_events(
        self,
        *,
        vessel: str | None = None,
        operator: str | None = None,
        shift: str | None = None,
    ) -> list[dict[str, Any]]:
        rows = store.rows(EVENTS_MODULE)
        if vessel:
            key = vessel.strip()
            rows = [
                row
                for row in rows
                if key in str(row.get("vessel_name", "")) or key in str(row.get("vessel_code", ""))
            ]
        if operator:
            key = operator.strip()
            rows = [row for row in rows if key in str(row.get("operator", ""))]
        if shift:
            key = shift.strip()
            rows = [row for row in rows if key in str(row.get("shift", ""))]
        return sorted(rows, key=lambda row: int(row.get("id", 0)), reverse=True)

    def vessel_ledger(self) -> list[dict[str, Any]]:
        """随船走动的台账：按船归集其全部接电单，供电量实时重算。"""
        ledger: dict[str, dict[str, Any]] = {}
        for row in sorted(store.rows(MODULE), key=lambda item: int(item.get("id", 0))):
            key = self._vessel_key(row)
            book = ledger.setdefault(
                key,
                {
                    "vessel_code": row.get("vessel_code") or "",
                    "vessel_name": row.get("vessel_name") or key,
                    "order_count": 0,
                    "total_kwh": 0.0,
                    "open_status": None,
                    "orders": [],
                },
            )
            book["order_count"] += 1
            book["total_kwh"] = round(book["total_kwh"] + self.power_of(row), 2)
            if row.get("status") in ACTIVE_STATUSES:
                book["open_status"] = row.get("status")
            book["orders"].append(self._ledger_line(row))
        return sorted(ledger.values(), key=lambda item: item["vessel_name"])

    def _ledger_line(self, row: dict[str, Any]) -> dict[str, Any]:
        root = store.find(MODULE, int(row.get("root_id") or row.get("id") or 0))
        chain_no = str(root.get("order_no")) if root else str(row.get("order_no"))
        return {
            "id": row.get("id"),
            "order_no": row.get("order_no"),
            "chain_no": chain_no,
            "visit_no": row.get("visit_no", 1),
            "continues_from_id": row.get("continues_from_id"),
            "berth_code": row.get("berth_code"),
            "box_code": row.get("box_code"),
            "status": row.get("status"),
            "gun_count": row.get("gun_count"),
            "meter_start": row.get("meter_start"),
            "meter_end": row.get("meter_end"),
            "kwh": self.power_of(row),
            "outage_count": row.get("outage_count", 0),
            "opened_at": row.get("opened_at"),
            "settled_at": row.get("settled_at"),
        }

    def summary(self) -> dict[str, Any]:
        """总览口径：供电量跟随接电单实时重算。"""
        rows = store.rows(MODULE)
        settled = [row for row in rows if row.get("status") == STATUS_SETTLED]
        return {
            "total_orders": len(rows),
            "waiting": sum(1 for row in rows if row.get("status") == STATUS_WAITING),
            "energized": sum(1 for row in rows if row.get("status") == STATUS_ON),
            "settled": len(settled),
            "open_chains": sum(1 for row in rows if row.get("status") in ACTIVE_STATUSES),
            "outage_count": sum(int(row.get("outage_count", 0) or 0) for row in rows),
            "active_guns": sum(
                int(row.get("gun_count", 0) or 0)
                for row in rows
                if row.get("status") == STATUS_ON
            ),
            "total_kwh": round(sum(self.power_of(row) for row in settled), 2),
        }

    @staticmethod
    def power_of(row: dict[str, Any]) -> float:
        """供电量只认电表抄见数差值，结算后才有；未结算或读数缺失按 0。"""
        if row.get("status") != STATUS_SETTLED:
            return 0.0
        start = row.get("meter_start")
        end = row.get("meter_end")
        if start is None or end is None:
            return 0.0
        return round(float(end) - float(start), 2)

    # ------------------------------------------------------------------ 开单
    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any], str]:
        vessel_code = str(values.get("vessel_code") or "").strip()
        vessel_name = str(values.get("vessel_name") or "").strip()
        berth_code = str(values.get("berth_code") or "").strip()
        box_code = str(values.get("box_code") or "").strip()
        voyage = str(values.get("voyage") or "").strip()
        operator = self._operator(values)

        missing = []
        if not (vessel_code or vessel_name):
            missing.append("船舶编号/船名")
        if not berth_code:
            missing.append("泊位")
        if not box_code:
            missing.append("接电箱")
        if missing:
            raise ShorepowerError(f"开单缺少必填项：{'、'.join(missing)}")

        rows = store.rows(MODULE)

        # 约束 1：同一艘船有未收口的单，重复提交只认第一张。
        active = self._find_active(vessel_code, vessel_name)
        if active is not None:
            same_spot = active.get("berth_code") == berth_code and active.get("box_code") == box_code
            hint = "请直接在原单上切换状态" if same_spot else "（与当前选择的泊位/接电箱不一致，仍沿用首张）"
            return active, f"该船已有未收口接电单 {active['order_no']}（{active['status']}），{hint}，不另开新单"

        new_id = max((int(row.get("id", 0)) for row in rows), default=0) + 1
        order_no = f"SP-{new_id:04d}"

        # 约束 2：同船同泊位复靠，接上一张延续；否则开一条新链。
        previous = self._find_last_settled(vessel_code, vessel_name, berth_code)
        if previous is not None:
            root_id = int(previous.get("root_id") or previous["id"])
            visit_no = int(previous.get("visit_no", 1)) + 1
            continues_from_id = int(previous["id"])
        else:
            root_id = new_id
            visit_no = 1
            continues_from_id = None

        now, shift = self._clock()
        entry = {
            "id": new_id,
            "order_no": order_no,
            "status": STATUS_WAITING,
            "pending": True,
            "abnormal": False,
            "vessel_code": vessel_code,
            "vessel_name": vessel_name or vessel_code,
            "berth_code": berth_code,
            "box_code": box_code,
            "voyage": voyage,
            "root_id": root_id,
            "visit_no": visit_no,
            "continues_from_id": continues_from_id,
            "gun_count": None,
            "meter_start": None,
            "meter_end": None,
            "kwh": 0.0,
            "outage_count": 0,
            "outages": [],
            "opened_at": now,
            "opened_by": operator,
            "energized_at": None,
            "energized_by": None,
            "last_drop_at": None,
            "last_drop_reason": None,
            "settled_at": None,
            "settled_by": None,
            "last_action_at": now,
            "last_operator": operator,
            "last_shift": shift,
        }
        rows.append(entry)
        self._log(entry, "开单", operator, None, STATUS_WAITING, now, shift,
                  {"接电箱": box_code, "航次": voyage})

        if continues_from_id is not None:
            prev_no = previous["order_no"]  # type: ignore[index]
            return entry, f"复靠接电：新单 {order_no} 延续上一张 {prev_no}（同泊位第 {visit_no} 次接电）"
        return entry, f"接电单 {order_no} 已开具，当前状态：待接"

    # ------------------------------------------------------------------ 动作
    def run_action(self, entry_id: int, values: dict[str, Any]) -> tuple[dict[str, Any], str]:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            raise ShorepowerError(f"接电单 {entry_id} 不存在或已归档")
        action = str(values.get("action") or "").strip()
        operator = self._operator(values)
        if action == "插枪通电":
            return self._energize(entry, values, operator)
        if action == "中途掉电":
            return self._dropout(entry, values, operator)
        if action == "拔枪结算":
            return self._settle(entry, values, operator)
        raise ShorepowerError(f"动作「{action}」不属于岸电接电单可执行范围")

    def _energize(
        self, entry: dict[str, Any], values: dict[str, Any], operator: str
    ) -> tuple[dict[str, Any], str]:
        if entry["status"] != STATUS_WAITING:
            raise ShorepowerError(f"当前为「{entry['status']}」，只有「待接」状态能插枪通电")

        first_time = entry.get("meter_start") is None
        # 首次通电必须登记起始抄见数；掉电恢复时沿用首次读数，不强制再填。
        reading = self._parse_reading(
            values.get("meter_reading"), field="电表抄见数", required=first_time
        )
        guns = self._parse_guns(values.get("gun_count"), required=entry.get("gun_count") is None)
        if first_time:
            entry["meter_start"] = reading
        if guns is not None:
            entry["gun_count"] = guns

        now, shift = self._clock()
        entry["status"] = STATUS_ON
        entry["pending"] = True
        entry["energized_at"] = now
        entry["energized_by"] = operator
        self._touch(entry, operator, now, shift)
        detail = {"抄见数": reading, "枪数": entry["gun_count"], "首次通电": first_time}
        self._log(entry, "插枪通电", operator, STATUS_WAITING, STATUS_ON, now, shift, detail)
        word = "已通电，起始抄见数已锁定" if first_time else "恢复通电，沿用首次起始抄见数"
        return entry, f"{entry['order_no']} {word}：{entry['meter_start']}，在接 {entry['gun_count']} 条枪"

    def _dropout(
        self, entry: dict[str, Any], values: dict[str, Any], operator: str
    ) -> tuple[dict[str, Any], str]:
        # 约束 3：只能从已通电掉回待接，并强制注明原因。
        if entry["status"] != STATUS_ON:
            raise ShorepowerError(f"当前为「{entry['status']}」，只有「已通电」状态能登记中途掉电")
        reason = str(values.get("reason") or "").strip()
        if not reason:
            raise ShorepowerError("登记中途掉电必须注明掉电原因")
        reading = self._parse_reading(values.get("meter_reading"), field="掉电时抄见数", required=False)

        now, shift = self._clock()
        entry["outages"].append(
            {"reason": reason, "reading": reading, "at": now, "operator": operator, "shift": shift}
        )
        entry["outage_count"] = int(entry.get("outage_count", 0) or 0) + 1
        entry["status"] = STATUS_WAITING
        entry["pending"] = True
        entry["abnormal"] = True
        entry["last_drop_at"] = now
        entry["last_drop_reason"] = reason
        self._touch(entry, operator, now, shift)
        self._log(
            entry,
            "中途掉电",
            operator,
            STATUS_ON,
            STATUS_WAITING,
            now,
            shift,
            {"掉电原因": reason, "掉电时抄见数": reading},
        )
        return entry, (
            f"{entry['order_no']} 中途掉电已退回「待接」（原因：{reason}）；"
            "需重新插枪通电后才能拔枪结算，不能直接收口"
        )

    def _settle(
        self, entry: dict[str, Any], values: dict[str, Any], operator: str
    ) -> tuple[dict[str, Any], str]:
        # 约束 3/4：必须在已通电，且结算抄见数必填。
        if entry["status"] == STATUS_WAITING:
            raise ShorepowerError("当前为「待接」，不允许直接收口；请先插枪通电后再拔枪结算")
        if entry["status"] != STATUS_ON:
            raise ShorepowerError(f"当前为「{entry['status']}」，不能重复结算")
        end = self._parse_reading(values.get("meter_end"), field="结算抄见数")
        if end is None:
            raise ShorepowerError("结算抄见数没填，不允许结算")
        start = entry.get("meter_start")
        if start is not None and end < float(start):
            raise ShorepowerError(f"结算抄见数 {end} 小于起始抄见数 {start}，请核对电表")
        guns = self._parse_guns(values.get("gun_count"), required=False)
        if guns is not None:
            entry["gun_count"] = guns

        now, shift = self._clock()
        entry["meter_end"] = end
        entry["kwh"] = self.power_of({**entry, "status": STATUS_SETTLED})
        entry["status"] = STATUS_SETTLED
        entry["pending"] = False
        entry["settled_at"] = now
        entry["settled_by"] = operator
        self._touch(entry, operator, now, shift)
        self._log(
            entry,
            "拔枪结算",
            operator,
            STATUS_ON,
            STATUS_SETTLED,
            now,
            shift,
            {"起始抄见数": start, "结算抄见数": end, "供电量": entry["kwh"], "枪数": entry["gun_count"]},
        )
        return entry, (
            f"{entry['order_no']} 已收口：{start} → {end}，本次供电 {entry['kwh']} 度，"
            f"接 {entry['gun_count']} 条枪"
        )

    # ------------------------------------------------------------------ 辅助
    def _find_active(self, vessel_code: str, vessel_name: str) -> dict[str, Any] | None:
        for row in store.rows(MODULE):
            if row.get("status") in ACTIVE_STATUSES and self._same_vessel(row, vessel_code, vessel_name):
                return row
        return None

    def _find_last_settled(
        self, vessel_code: str, vessel_name: str, berth_code: str
    ) -> dict[str, Any] | None:
        candidates = [
            row
            for row in store.rows(MODULE)
            if row.get("status") == STATUS_SETTLED
            and row.get("berth_code") == berth_code
            and self._same_vessel(row, vessel_code, vessel_name)
        ]
        return max(candidates, key=lambda row: int(row.get("id", 0)), default=None)

    @staticmethod
    def _same_vessel(row: dict[str, Any], code: str, name: str) -> bool:
        row_code = str(row.get("vessel_code") or "").strip()
        row_name = str(row.get("vessel_name") or "").strip()
        if code and row_code and row_code == code:
            return True
        if name and row_name and row_name == name:
            return True
        # 只填了船名对上编号、或只填编号对上名的兜底
        return bool(code and row_name and row_name == code) or bool(name and row_code and row_code == name)

    @staticmethod
    def _vessel_key(row: dict[str, Any]) -> str:
        return str(row.get("vessel_code") or row.get("vessel_name") or "").strip()

    @staticmethod
    def _operator(values: dict[str, Any]) -> str:
        return str(values.get("operator") or "").strip() or "值班管理员"

    @staticmethod
    def _parse_reading(value: Any, *, field: str, required: bool = True) -> float | None:
        if value is None or (isinstance(value, str) and not value.strip()):
            if required:
                raise ShorepowerError(f"{field}没填，不允许继续")
            return None
        try:
            number = float(value)
        except (TypeError, ValueError):
            raise ShorepowerError(f"{field}必须是数字，收到的是「{value}」")
        if number < 0:
            raise ShorepowerError(f"{field}不能为负数")
        return round(number, 2)

    @staticmethod
    def _parse_guns(value: Any, *, required: bool = True) -> int | None:
        if value is None or value == "":
            if required:
                raise ShorepowerError("插接枪数没填")
            return None
        try:
            number = int(str(value).strip())
        except (TypeError, ValueError):
            raise ShorepowerError(f"插接枪数必须是整数，收到的是「{value}」")
        if number < 1:
            raise ShorepowerError("插接枪数至少为 1 条")
        return number

    @staticmethod
    def _clock() -> tuple[str, str]:
        now = datetime.now()
        stamp = now.strftime("%Y-%m-%d %H:%M:%S")
        shift_name = "白班" if 8 <= now.hour < 20 else "夜班"
        return stamp, f"{now.strftime('%Y-%m-%d')} {shift_name}"

    @staticmethod
    def _touch(entry: dict[str, Any], operator: str, now: str, shift: str) -> None:
        entry["last_action_at"] = now
        entry["last_operator"] = operator
        entry["last_shift"] = shift

    def _log(
        self,
        entry: dict[str, Any],
        action: str,
        operator: str,
        from_status: str | None,
        to_status: str | None,
        at: str,
        shift: str,
        detail: dict[str, Any] | None = None,
    ) -> None:
        events = store.rows(EVENTS_MODULE)
        event = {
            "id": max((int(row.get("id", 0)) for row in events), default=0) + 1,
            "order_id": int(entry["id"]),
            "order_no": entry["order_no"],
            "vessel_code": entry.get("vessel_code"),
            "vessel_name": entry.get("vessel_name"),
            "berth_code": entry.get("berth_code"),
            "action": action,
            "from_status": from_status,
            "to_status": to_status,
            "operator": operator,
            "shift": shift,
            "at": at,
            "detail": detail or {},
        }
        events.append(event)
