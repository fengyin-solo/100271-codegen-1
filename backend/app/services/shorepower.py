"""岸电接电业务规则：接电单随船走动，状态流转、计量校验与供电量汇总都收在这里。

状态机：
    待接 ──插枪通电──▶ 已通电 ──拔枪结算──▶ 已收口
      ▲                  │
      └────掉电复位──────┘ （必须注明掉电原因，不能直接收口）

约束：
- 同一艘船只认第一张未收口的接电单：重复提交接电返回原单，不再开新单。
- 同一泊位同一船复靠，接电单在上一张基础上延续（续靠次数 +1、新增一段接电段）。
- 供电量按电表抄见数末数减起数结算；拔枪结算时末数没填不允许结算。
- 总览供电量随接电单段次实时重算；每次处理都留下当班人与工班，交班后可追溯。
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from app.store import store

MODULE = "shorepower"

STATUS_WAITING = "待接"
STATUS_POWERED = "已通电"
STATUS_CLOSED = "已收口"
STATUS_ORDER = [STATUS_WAITING, STATUS_POWERED, STATUS_CLOSED]

ACTION_PLUG = "插枪通电"
ACTION_OUTAGE = "掉电复位"
ACTION_REPLUG = "重新插枪"
ACTION_SETTLE = "拔枪结算"

REQUIRED_FIELDS = ["泊位编号", "船舶编号", "船名"]


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def box_no_of(values: dict[str, Any]) -> str:
    return str(values.get("接电箱号") or "").strip()


def _parse_reading(raw: Any) -> Decimal | None:
    """电表抄见数只接受非负数字，空值/非法值返回 None 由调用方决定如何拒绝。"""
    if raw is None:
        return None
    text = str(raw).strip()
    if not text:
        return None
    try:
        value = Decimal(text)
    except InvalidOperation:
        return None
    if value < 0:
        return None
    return value


class ShorePowerService:
    # ---------- 查询 ----------
    def list_entries(
        self,
        *,
        keyword: str | None = None,
        status: str | None = None,
        berth: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        rows = store.rows(MODULE)
        if keyword:
            rows = [
                row
                for row in rows
                if keyword in str(row.get("接电单号", ""))
                or keyword in str(row.get("船舶编号", ""))
                or keyword in str(row.get("船名", ""))
            ]
        if status:
            rows = [row for row in rows if row.get("status") == status]
        if berth:
            rows = [row for row in rows if berth in str(row.get("泊位编号", ""))]
        rows = sorted(rows, key=lambda row: int(row.get("id", 0)), reverse=True)
        total = len(rows)
        start = max(page - 1, 0) * size
        return rows[start:start + size], total

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        return store.find(MODULE, entry_id)

    def active_order_for_vessel(self, vessel_code: str) -> dict[str, Any] | None:
        """同一艘船当前未收口的接电单（重复提交只认这一张）。"""
        candidates = [
            row
            for row in store.rows(MODULE)
            if str(row.get("船舶编号", "")).strip() == str(vessel_code).strip()
            and row.get("status") != STATUS_CLOSED
        ]
        if not candidates:
            return None
        return max(candidates, key=lambda row: int(row.get("id", 0)))

    def latest_order_for_vessel(self, vessel_code: str) -> dict[str, Any] | None:
        """该船最近一张接电单（含已收口），用于判断同泊位复靠延续。"""
        candidates = [
            row
            for row in store.rows(MODULE)
            if str(row.get("船舶编号", "")).strip() == str(vessel_code).strip()
        ]
        if not candidates:
            return None
        return max(candidates, key=lambda row: int(row.get("id", 0)))

    def summary(self) -> dict[str, Any]:
        """供电量随接电单一起重算：汇总每一段已结束接电段的段供电量。"""
        rows = store.rows(MODULE)
        total_kwh = Decimal("0")
        closed_kwh = Decimal("0")
        status_counts = {STATUS_WAITING: 0, STATUS_POWERED: 0, STATUS_CLOSED: 0}
        gun_count = 0
        for row in rows:
            status = str(row.get("status", ""))
            if status in status_counts:
                status_counts[status] += 1
            for segment in row.get("接电段", []):
                if segment.get("段供电量") is not None:
                    total_kwh += Decimal(str(segment["段供电量"]))
                    gun_count += 1
            if status == STATUS_CLOSED:
                closed_kwh += Decimal(str(row.get("供电量") or 0))
        return {
            "接电单总数": len(rows),
            "待接单数": status_counts[STATUS_WAITING],
            "通电中单数": status_counts[STATUS_POWERED],
            "已收口单数": status_counts[STATUS_CLOSED],
            "已结算接电段": gun_count,
            "累计供电量": float(total_kwh),
            "已收口供电量": float(closed_kwh),
        }

    # ---------- 开单 ----------
    def open_order(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, str, bool]:
        """靠泊后开接电单。

        返回 (单据, 消息, created)：created=False 表示命中了同船未收口的第一张单，
        本次提交不另开新单。
        """
        missing = [field for field in REQUIRED_FIELDS if not str(values.get(field) or "").strip()]
        if missing:
            return None, f"缺少必填字段：{'、'.join(missing)}", False

        vessel_code = str(values.get("船舶编号")).strip()
        berth_code = str(values.get("泊位编号")).strip()
        existing = self.active_order_for_vessel(vessel_code)
        if existing is not None:
            # 同一艘船重复提交接电只认第一次开的那张，不另开新单。
            return (
                existing,
                f"船舶「{existing.get('船名')}」已有未收口接电单 {existing.get('接电单号')}，"
                f"重复提交只认第一次开的那张，请在原单上操作",
                False,
            )

        latest = self.latest_order_for_vessel(vessel_code)
        if latest is not None and str(latest.get("泊位编号", "")).strip() == berth_code:
            # 同一泊位同一船复靠：接上一张延续（续靠次数 +1、累计供电量保留、等待重新插枪）。
            return self._reopen_for_return_berth(latest, values)

        rows = store.rows(MODULE)
        entry_id = max((int(row.get("id", 0)) for row in rows), default=0) + 1
        same_pair = [
            row
            for row in rows
            if str(row.get("船舶编号", "")).strip() == vessel_code
            and str(row.get("泊位编号", "")).strip() == berth_code
        ]
        operator = str(values.get("经办人") or "").strip() or "值班管理员"
        shift = str(values.get("当班工班") or "").strip() or "未指定工班"
        initial_raw = str(values.get("起始读数") or "").strip()
        initial_reading: str | None = None
        if initial_raw:
            parsed = _parse_reading(initial_raw)
            if parsed is None:
                return None, "起始抄见数不是有效数字，请核对电表底数", False
            initial_reading = str(parsed)
        opened_at = _now()
        entry: dict[str, Any] = {
            "id": entry_id,
            "接电单号": f"SP-{entry_id:04d}",
            "泊位编号": berth_code,
            "船舶编号": vessel_code,
            "船名": str(values.get("船名")).strip(),
            "接电箱号": box_no_of(values),
            "status": STATUS_WAITING,
            "pending": True,
            "abnormal": False,
            "续靠次数": len(same_pair),
            "起始读数": initial_reading,
            "末次抄见数": None,
            "供电量": "0",
            "掉电原因": "",
            "开单时间": opened_at,
            "开单经办人": operator,
            "开单工班": shift,
            "收口时间": None,
            "收口经办人": None,
            "收口工班": None,
            "接电段": [],
            "处理记录": [
                {"时间": opened_at, "动作": "靠泊开单", "经办人": operator, "工班": shift, "说明": "靠泊后开具接电单，等待插枪"}
            ],
        }
        rows.append(entry)
        return entry, f"接电单 {entry['接电单号']} 已开具，状态：待接", True

    def _reopen_for_return_berth(
        self, latest: dict[str, Any], values: dict[str, Any]
    ) -> tuple[dict[str, Any], str, bool]:
        """同泊位复靠：已收口单据回到待接，等插枪后沿用上段止数新增接电段。"""
        operator = str(values.get("经办人") or "").strip() or "值班管理员"
        shift = str(values.get("当班工班") or "").strip() or "未指定工班"
        box_no = str(values.get("接电箱号") or "").strip()
        if box_no:
            latest["接电箱号"] = box_no
        latest["续靠次数"] = int(latest.get("续靠次数") or 0) + 1
        latest["status"] = STATUS_WAITING
        latest["pending"] = True
        latest["abnormal"] = False
        latest["掉电原因"] = ""
        latest["收口时间"] = None
        latest["收口经办人"] = None
        latest["收口工班"] = None
        occurred_at = _now()
        # 末次抄见数与累计供电量保留在单上，作为下一段插枪时的起数来源。
        latest["处理记录"].append(
            {
                "时间": occurred_at,
                "动作": "复靠延续",
                "经办人": operator,
                "工班": shift,
                "说明": (
                    f"同一泊位复靠，接电单 {latest['接电单号']} 接着上一张延续，"
                    f"历史供电量 {latest.get('供电量')} 度保留，等待重新插枪"
                ),
            }
        )
        return (
            latest,
            f"同一泊位复靠：接电单 {latest['接电单号']} 已延续（第 {latest['续靠次数']} 次复靠），"
            "插枪时将沿用上段止数继续计量",
            True,
        )

    # ---------- 状态流转 ----------
    def run_action(
        self, entry_id: int, action: str, values: dict[str, Any] | None = None
    ) -> tuple[dict[str, Any] | None, str]:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"接电单 {entry_id} 不存在或已归档"
        values = values or {}
        if action == ACTION_PLUG:
            return self._plug(entry, values)
        if action == ACTION_REPLUG:
            return self._plug(entry, values)
        if action == ACTION_OUTAGE:
            return self._outage(entry, values)
        if action == ACTION_SETTLE:
            return self._settle(entry, values)
        return None, f"动作「{action}」不属于岸电接电可执行范围"

    # ---------- 内部规则 ----------
    def _plug(self, entry: dict[str, Any], values: dict[str, Any]) -> tuple[dict[str, Any] | None, str]:
        status = entry.get("status")
        if status != STATUS_WAITING:
            return None, f"接电单当前为「{status}」，不能插枪通电；仅待接状态可以插枪"
        # 是否为掉电后续接：以单据上的掉电标记为准（前端两个按钮共用这段逻辑）。
        after_outage = bool(entry.get("掉电原因"))

        start_reading: Decimal
        replug_backfill = False
        if entry["接电段"]:
            last_end = entry["接电段"][-1].get("止数")
            if last_end is not None:
                # 同一张单的后续接电段接着上次抄见数延续，不允许另起底数。
                start_reading = Decimal(str(last_end))
            else:
                # 上段掉电时没来得及抄见：重新插枪必须补一次电表读数，
                # 并用它把掉电那段的止数/段供电量一并截算，避免掉电前用电漏计。
                raw_start = _parse_reading(values.get("起始读数"))
                if raw_start is None:
                    return None, "上段掉电时未抄见，请填写本次插枪时的电表抄见数后续段"
                error = self._apply_segment_reading(entry, entry["接电段"][-1], raw_start)
                if error:
                    return None, error
                start_reading = raw_start
                replug_backfill = True
        else:
            raw_start = _parse_reading(values.get("起始读数"))
            if raw_start is not None:
                start_reading = raw_start
            elif str(values.get("起始读数") or "").strip():
                return None, "起始抄见数不是有效数字，请核对电表底数"
            elif entry.get("起始读数") is not None:
                # 开单时已抄过电表底数的，首段插枪直接沿用。
                start_reading = Decimal(str(entry["起始读数"]))
            else:
                start_reading = Decimal("0")

        operator = str(values.get("经办人") or "").strip() or "值班管理员"
        shift = str(values.get("当班工班") or "").strip() or "未指定工班"
        box_no = str(values.get("接电箱号") or "").strip()
        if box_no:
            entry["接电箱号"] = box_no
        occurred_at = _now()
        entry["接电段"].append(
            {
                "段次": len(entry["接电段"]) + 1,
                "起数": str(start_reading),
                "止数": None,
                "段供电量": None,
                "插枪时间": occurred_at,
                "收口时间": None,
                "插枪经办人": operator,
                "插枪工班": shift,
                "掉电原因": entry.get("掉电原因", "") if after_outage else "",
            }
        )
        if entry.get("起始读数") is None:
            entry["起始读数"] = str(start_reading)
        entry["status"] = STATUS_POWERED
        entry["pending"] = False
        is_continuation = len(entry["接电段"]) > 1  # 新增段之前已有接电段
        if after_outage:
            note = "掉电后重新插枪，沿用上段止数继续计量"
            if replug_backfill:
                note = (
                    f"掉电时未抄见，按本次插枪读数 {start_reading} 补截上段"
                    f"（已供 {entry['接电段'][-2]['段供电量']} 度），新段沿此数继续计量"
                )
        elif is_continuation:
            note = "复靠后重新插枪，沿用上段止数继续计量"
        else:
            note = "插枪成功，开始供电"
        entry["处理记录"].append(
            {"时间": occurred_at, "动作": ACTION_REPLUG if is_continuation else ACTION_PLUG,
             "经办人": operator, "工班": shift, "说明": note}
        )
        if after_outage:
            entry["掉电原因"] = ""
            entry["abnormal"] = False
        return entry, f"接电单 {entry['接电单号']} 插枪成功，已通电（起数 {start_reading}）"

    def _outage(self, entry: dict[str, Any], values: dict[str, Any]) -> tuple[dict[str, Any] | None, str]:
        if entry.get("status") != STATUS_POWERED:
            return None, f"接电单当前为「{entry.get('status')}」，没有进行中的供电，不能登记掉电"
        reason = str(values.get("掉电原因") or "").strip()
        if not reason:
            return None, "掉电必须注明掉电原因，否则不能复位到待接"

        segment = entry["接电段"][-1]
        reading_raw = str(values.get("末次抄见数") or "").strip()
        end_reading: Decimal | None = None
        if reading_raw:
            end_reading = _parse_reading(reading_raw)
            if end_reading is None:
                return None, "掉电抄见数不是有效数字，请核对电表"
        message_tail = ""
        if end_reading is not None:
            error = self._apply_segment_reading(entry, segment, end_reading)
            if error:
                return None, error
            message_tail = f"，本段已供 {segment['段供电量']} 度"

        operator = str(values.get("经办人") or "").strip() or "值班管理员"
        shift = str(values.get("当班工班") or "").strip() or "未指定工班"
        occurred_at = _now()
        segment["掉电原因"] = reason
        entry["status"] = STATUS_WAITING
        entry["pending"] = True
        entry["abnormal"] = True
        entry["掉电原因"] = reason
        entry["处理记录"].append(
            {"时间": occurred_at, "动作": ACTION_OUTAGE, "经办人": operator, "工班": shift,
             "说明": f"中途掉电，单据退回待接，原因：{reason}{message_tail}；不允许直接收口"}
        )
        return entry, f"接电单 {entry['接电单号']} 已登记掉电并退回待接，原因：{reason}{message_tail}"

    def _settle(self, entry: dict[str, Any], values: dict[str, Any]) -> tuple[dict[str, Any] | None, str]:
        if entry.get("status") != STATUS_POWERED:
            return None, (
                f"接电单当前为「{entry.get('status')}」，不能拔枪结算；"
                "待接/掉电单据须先重新插枪通电，不允许直接收口"
            )
        reading_raw = str(values.get("末次抄见数") or "").strip()
        if not reading_raw:
            return None, "拔枪结算必须填写电表抄见数（末数），未填不允许结算"
        end_reading = _parse_reading(reading_raw)
        if end_reading is None:
            return None, "末次抄见数不是有效数字，请核对电表"

        segment = entry["接电段"][-1]
        error = self._apply_segment_reading(entry, segment, end_reading)
        if error:
            return None, error

        operator = str(values.get("经办人") or "").strip() or "值班管理员"
        shift = str(values.get("当班工班") or "").strip() or "未指定工班"
        occurred_at = _now()
        segment["收口时间"] = occurred_at
        entry["status"] = STATUS_CLOSED
        entry["pending"] = False
        entry["abnormal"] = False
        entry["收口时间"] = occurred_at
        entry["收口经办人"] = operator
        entry["收口工班"] = shift
        total = sum(
            (Decimal(str(seg.get("段供电量") or 0)) for seg in entry["接电段"]),
            Decimal("0"),
        )
        entry["供电量"] = str(total)
        entry["处理记录"].append(
            {"时间": occurred_at, "动作": ACTION_SETTLE, "经办人": operator, "工班": shift,
             "说明": f"拔枪结算收口，本段供电 {segment['段供电量']} 度，本单合计 {total} 度"}
        )
        return entry, f"接电单 {entry['接电单号']} 已结算收口，合计供电 {total} 度"

    def _apply_segment_reading(
        self, entry: dict[str, Any], segment: dict[str, Any], end_reading: Decimal
    ) -> str:
        """把止数落到接电段上，回算段供电量并刷新单据末次抄见数/累计供电量。

        返回空串表示成功，否则是拒绝原因。
        """
        start_reading = Decimal(str(segment.get("起数") or 0))
        if end_reading < start_reading:
            return f"末次抄见数 {end_reading} 小于本段起数 {start_reading}，电表读数不能倒走"
        segment["止数"] = str(end_reading)
        segment["段供电量"] = str(end_reading - start_reading)
        entry["末次抄见数"] = str(end_reading)
        total = sum(
            (Decimal(str(seg.get("段供电量") or 0)) for seg in entry["接电段"]),
            Decimal("0"),
        )
        entry["供电量"] = str(total)
        return ""
