"""每日播报的跨机器共享状态（飞书多维表格）

背景：`last_run_date` 和 `data/broadcast_locks/` 都只在本机生效，
两台机器同时开着服务时，同一天会各播一次，群里就出现重复播报。

这里把「某群 · 某报告日期 是否已播」写到飞书多维表格的一张「播报状态」表，
所有机器读同一份：
- 抢占式写入 + 复查（record_id 最小者胜出），并发时也不会双发
- claim 超过 CLAIM_TTL 秒还没结果（机器中途挂掉）允许接管
- 云端不可用时返回 unavailable，调用方回退到本地文件锁（保持旧行为，不阻塞播报）
"""
import logging
import os
import socket
import time
from datetime import datetime

from src.config import load_config
from src.clients import feishu_client

logger = logging.getLogger(__name__)

TABLE_NAME = "播报状态"
CLAIM_TTL = 1800  # claim 超过 30 分钟未完成，视为该机器已挂，可被接管
_TABLE_CACHE = {"app_token": "", "table_id": "", "ts": 0.0}
_TABLE_CACHE_TTL = 3600

FIELDS = [
    {"field_name": "群ID", "type": 1},
    {"field_name": "播报日期", "type": 1},
    {"field_name": "播报时间", "type": 1},
    {"field_name": "机器", "type": 1},
    {"field_name": "状态", "type": 1},
    {"field_name": "详情", "type": 1},
    {"field_name": "更新时间", "type": 1},
]


def _txt(value) -> str:
    """多维表格字段可能是字符串、数字或 [{text}] 结构，统一转字符串"""
    if value is None:
        return ""
    if isinstance(value, list):
        return "".join(_txt(v.get("text", v)) if isinstance(v, dict) else _txt(v) for v in value)
    if isinstance(value, dict):
        return _txt(value.get("text", ""))
    return str(value).strip()


def _machine() -> str:
    try:
        return socket.gethostname()[:40]
    except Exception:
        return os.environ.get("COMPUTERNAME", "unknown")[:40]


def _cfg() -> dict:
    cfg = load_config().get("daily_broadcast") or {}
    bcfg = load_config().get("feishu_bitable") or {}
    return {
        "app_token": str(cfg.get("state_app_token") or bcfg.get("app_token") or "").strip(),
        "table_id": str(cfg.get("state_table_id") or "").strip(),
    }


def _ensure_table() -> tuple:
    """返回 (app_token, table_id)：优先配置，其次按名称发现，最后自动创建"""
    c = _cfg()
    app_token = c["app_token"]
    if not app_token:
        raise RuntimeError("未配置 feishu_bitable.app_token，无法使用播报状态表")
    if c["table_id"]:
        return app_token, c["table_id"]
    now = time.time()
    if (_TABLE_CACHE["table_id"] and _TABLE_CACHE["app_token"] == app_token
            and now - _TABLE_CACHE["ts"] < _TABLE_CACHE_TTL):
        return app_token, _TABLE_CACHE["table_id"]
    table_id = ""
    try:
        for t in feishu_client.list_bitable_tables(app_token):
            if (t.get("name") or "").strip() == TABLE_NAME:
                table_id = t.get("table_id", "")
                break
    except Exception as e:
        logger.warning("播报状态表发现失败: %s", e)
    if not table_id:
        table_id = feishu_client.create_bitable_table(app_token, TABLE_NAME, FIELDS)
        logger.info("已创建播报状态表: app=%s, table=%s", app_token, table_id)
    _TABLE_CACHE.update({"app_token": app_token, "table_id": table_id, "ts": now})
    return app_token, table_id


def _rows(app_token: str, table_id: str) -> list:
    out = []
    for r in feishu_client.list_bitable_records(app_token, table_id) or []:
        f = r.get("fields") or {}
        out.append({
            "record_id": r.get("record_id", ""),
            "chat_id": _txt(f.get("群ID")),
            "date": _txt(f.get("播报日期")),
            "time": _txt(f.get("播报时间")),
            "machine": _txt(f.get("机器")),
            "status": _txt(f.get("状态")),
            "detail": _txt(f.get("详情")),
            "updated": _txt(f.get("更新时间")),
        })
    return out


def _same_day(rows: list, chat_id: str, date_str: str) -> list:
    return [r for r in rows if r["chat_id"] == chat_id and r["date"] == date_str]


def _age_seconds(updated: str) -> float:
    try:
        return (datetime.now() - datetime.strptime(updated[:19], "%Y-%m-%d %H:%M:%S")).total_seconds()
    except Exception:
        return float("inf")


def get_state(chat_id: str, date_str: str) -> dict:
    """查询 (群, 报告日期) 的播报状态；云端异常抛异常（调用方据此回退）"""
    app_token, table_id = _ensure_table()
    rows = _same_day(_rows(app_token, table_id), chat_id, date_str)
    if not rows:
        return {"status": "", "record_id": "", "machine": "", "detail": "", "updated": ""}
    rows.sort(key=lambda r: r["record_id"])
    return rows[0]


def claim(chat_id: str, date_str: str, time_str: str = "") -> tuple:
    """抢占今天/该报告日期的播报权

    :return: ("claimed", record_id) / ("exists", record_id) / ("unavailable", "")
    """
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    try:
        app_token, table_id = _ensure_table()
        existing = _same_day(_rows(app_token, table_id), chat_id, date_str)
        if existing:
            existing.sort(key=lambda r: r["record_id"])
            head = existing[0]
            stale = head["status"] == "claiming" and _age_seconds(head["updated"]) > CLAIM_TTL
            if not stale:
                return "exists", head["record_id"]
            # 旧 claim 已超时（机器中途挂了）：接管这条记录
            feishu_client.update_bitable_records(app_token, table_id, [{
                "record_id": head["record_id"],
                "fields": {"状态": "claiming", "机器": _machine(),
                           "更新时间": now_str, "播报时间": time_str, "详情": "接管超时 claim"},
            }])
            logger.info("播报状态：接管超时 claim chat=%s date=%s", chat_id[:12], date_str)
            return "claimed", head["record_id"]
        resp = feishu_client.batch_create_records(app_token, table_id, [{
            "fields": {"群ID": chat_id, "播报日期": date_str, "播报时间": time_str,
                       "机器": _machine(), "状态": "claiming", "详情": "", "更新时间": now_str},
        }])
        records = (resp or {}).get("records") or []
        my_id = records[0].get("record_id", "") if records else ""
        if not my_id:
            raise RuntimeError("创建播报状态记录未返回 record_id")
        # 并发复查：同一 (群, 日期) 可能被两台机器同时写入，record_id 最小者胜出
        time.sleep(0.6)
        rivals = _same_day(_rows(app_token, table_id), chat_id, date_str)
        if len(rivals) > 1:
            winner = min(rivals, key=lambda r: r["record_id"])
            if winner["record_id"] != my_id:
                try:
                    feishu_client.batch_delete_records(app_token, table_id, [my_id])
                except Exception as e:
                    logger.warning("播报状态：删除落败记录失败: %s", e)
                return "exists", winner["record_id"]
        return "claimed", my_id
    except Exception as e:
        logger.warning("播报状态：云端不可用，回退本地锁: %s", e)
        return "unavailable", ""


def finish(record_id: str, ok: bool, detail: str = "") -> bool:
    """标记播报结果（成功/失败），失败不抛异常"""
    if not record_id:
        return False
    try:
        app_token, table_id = _ensure_table()
        feishu_client.update_bitable_records(app_token, table_id, [{
            "record_id": record_id,
            "fields": {"状态": "success" if ok else "failed",
                       "详情": (detail or "")[:200],
                       "更新时间": datetime.now().strftime("%Y-%m-%d %H:%M:%S")},
        }])
        return True
    except Exception as e:
        logger.warning("播报状态：写入结果失败 %s: %s", record_id, e)
        return False


def record_result(chat_id: str, date_str: str, ok: bool, detail: str = "") -> bool:
    """按 (群, 报告日期) 记录结果：已存在则更新，不存在则新建（手动单次播报用）"""
    try:
        app_token, table_id = _ensure_table()
        rows = _same_day(_rows(app_token, table_id), chat_id, date_str)
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        if rows:
            rows.sort(key=lambda r: r["record_id"])
            feishu_client.update_bitable_records(app_token, table_id, [{
                "record_id": rows[0]["record_id"],
                "fields": {"状态": "success" if ok else "failed", "详情": (detail or "")[:200],
                           "机器": _machine(), "更新时间": now_str},
            }])
        else:
            feishu_client.batch_create_records(app_token, table_id, [{
                "fields": {"群ID": chat_id, "播报日期": date_str,
                           "播报时间": datetime.now().strftime("%H:%M"), "机器": _machine(),
                           "状态": "success" if ok else "failed",
                           "详情": (detail or "")[:200], "更新时间": now_str},
            }])
        return True
    except Exception as e:
        logger.warning("播报状态：记录结果失败 chat=%s date=%s: %s", chat_id[:12], date_str, e)
        return False
