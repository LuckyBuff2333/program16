"""触发时间管理服务：自学习、云端缓存、触发时间 CRUD

从 server.py 提取，包含触发时间的完整生命周期管理。
函数通过 server.py 的 _alias 导入保持向后兼容。
"""

import json
import os
import re
import threading
from datetime import datetime

import pandas as pd
import yaml

from src import config as cfg_module
from src import pipeline
from src.clients import ai_log_client, bug_source, jira_client
from src.clients import diana_client as _diana_client
from src.config import get_path, load_config, setup_logger, PROJECT_ROOT
from src.core import doc_generator
from src.services.report_ops import _delete_default_bitable_table

_CACHE_BATCH_PROGRESS_FILE = os.path.join(PROJECT_ROOT, "data", "cache_batch_progress.json")

# ── 云端缓存状态 ──
_trigger_time_table_cache = {"app_token": "", "table_ids": [], "inited": False}
_trigger_time_bugid_cache = {}  # {jira号: (table_id, record_id, trigger_time)}
_last_cache_load_partial = False
_TRIGGER_TIME_TABLE_LIMIT = 500

# 从共享模块导入公共工具和状态
from src.api.routes.shared import (
    bitable_text as _bitable_text,
    is_bitable_excluded as _is_bitable_excluded,
    flatten_bitable_record as _flatten_bitable_record,
    get_prod_ai_url as _get_prod_ai_url,
    ts_parse_datetime as _ts_parse_datetime,
    read_csv_rows as _read_csv_rows,
    ok as _ok,
    fail as _fail,
    _bitable_bulk_cache,
    _BITABLE_CACHE_TTL,
)

logger = setup_logger("services.trigger_ops")

# ── 触发时间自学习状态 ──
_TIMESTUDY_DIR = os.path.join(PROJECT_ROOT, "data", "timestudy")
_TIMESTUDY_RECORDS = os.path.join(_TIMESTUDY_DIR, "records.csv")
_TIMESTUDY_CSV_HEADERS = [
    "jira号", "记录时间", "提取来源", "提取结果", "是否正确",
    "错误类型", "错误详情", "修正后时间",
    "视频数量", "gmlogger数量", "参考时间",
    "OCR原文", "匹配差秒", "12h转换", "jira创建时间",
    "trace_steps"
]
_timestudy_ctx: dict = {}
_timestudy_lock = threading.Lock()
_record_write_lock = threading.Lock()

# 单条记录缓存：bugid -> (table_id, record_id, trigger_time)
_trigger_time_bugid_cache = {}

# 单表记录上限
_TRIGGER_TIME_TABLE_LIMIT = 500

# 需要从 server.py 延迟导入的函数（在函数体内 import）
# _bot_get_trigger_times 等依赖 diagnostics 的函数留在 server.py


def _timestudy_init_ctx(bugid: str):
    """初始化提取上下文（每次提取前调用）"""
    with _timestudy_lock:
        _timestudy_ctx[bugid] = {
            "source": "", "error_type": "", "error_detail": "",
            "video_count": 0, "gm_count": 0, "ref_times": "",
            "ocr_text": "", "match_diff": "", "h12": "no",
            "jira_created": "",
            "trace": []  # 提取流水线步骤记录
        }


def _timestudy_trace(bugid: str, step: str):
    """追加一条流水线步骤记录（溯源用）"""
    with _timestudy_lock:
        ctx = _timestudy_ctx.get(bugid)
        if ctx and isinstance(ctx.get("trace"), list):
            ctx["trace"].append(step)


def _timestudy_update_ctx(bugid: str, **kwargs):
    """更新提取上下文"""
    with _timestudy_lock:
        ctx = _timestudy_ctx.get(bugid)
        if ctx:
            ctx.update(kwargs)


def _timestudy_get_ctx(bugid: str) -> dict:
    """获取并清除提取上下文"""
    with _timestudy_lock:
        return _timestudy_ctx.pop(bugid, None) or {}


def _timestudy_record(bugid: str, result: str, source: str,
                      error_type: str = "", error_detail: str = "",
                      correction: str = "", ctx: dict = None):
    """写入一条自学习记录到 timestudy/records.csv"""
    import csv as _csv
    os.makedirs(_TIMESTUDY_DIR, exist_ok=True)
    ctx = ctx or {}
    record_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    file_exists = os.path.exists(_TIMESTUDY_RECORDS)
    row = [
        bugid, record_time, source, result, "unknown",
        error_type, error_detail, correction,
        str(ctx.get("video_count", 0)),
        str(ctx.get("gm_count", 0)),
        ctx.get("ref_times", ""),
        ctx.get("ocr_text", ""),
        ctx.get("match_diff", ""),
        ctx.get("h12", "no"),
        ctx.get("jira_created", ""),
        "→".join(ctx.get("trace", [])),  # trace_steps: 用箭头连接各步骤
    ]
    try:
        with _record_write_lock:
            with open(_TIMESTUDY_RECORDS, "a", newline="", encoding="utf-8-sig") as f:
                writer = _csv.writer(f)
                if not file_exists:
                    writer.writerow(_TIMESTUDY_CSV_HEADERS)
                writer.writerow(row)
    except Exception as e:
        logger.warning("自学习记录写入失败 %s: %s", bugid, e)


def _save_trigger_time_to_csv(bugid: str, trigger_time: str):
    """将提取到的触发时间记录到 data/日期/ 目录"""
    import csv as _csv
    date_str = datetime.now().strftime("%Y-%m-%d")
    tt_dir = os.path.join(PROJECT_ROOT, "data", date_str)
    os.makedirs(tt_dir, exist_ok=True)
    csv_path = os.path.join(tt_dir, f"trigger_times_{date_str}.csv")
    file_exists = os.path.exists(csv_path)
    try:
        with open(csv_path, "a", newline="", encoding="utf-8-sig") as f:
            writer = _csv.writer(f)
            if not file_exists:
                writer.writerow(["jira号", "触发时间", "提取时间"])
            writer.writerow([bugid, trigger_time, datetime.now().strftime("%Y-%m-%d %H:%M:%S")])
    except Exception as e:
        logger.warning("触发时间保存失败: %s", e)


def _load_trigger_times_from_local() -> dict:
    """从 data/ 目录加载所有已提取的触发时间，返回 {jira号: 触发时间}"""
    import csv as _csv
    data_dir = os.path.join(PROJECT_ROOT, "data")
    result = {}
    if not os.path.isdir(data_dir):
        return result
    for root, _dirs, files in os.walk(data_dir):
        for filename in files:
            if not filename.startswith("trigger_times_") or not filename.endswith(".csv"):
                continue
            csv_path = os.path.join(root, filename)
            try:
                with open(csv_path, "r", encoding="utf-8-sig") as f:
                    reader = _csv.DictReader(f)
                    for row in reader:
                        jira_no = (row.get("jira号") or "").strip()
                        tt = (row.get("触发时间") or "").strip()
                        if jira_no and tt:
                            result[jira_no] = tt
            except Exception as e:
                logger.warning("加载触发时间文件失败 %s: %s", filename, e)
    return result


def _get_trigger_time_table_cfg() -> tuple:
    """获取触发时间云端多维表格配置，首次调用时自动创建并回填

    :return: (app_token, table_ids_list)
    """
    from src.clients import feishu_client
    cache = _trigger_time_table_cache
    if cache["inited"] and cache["app_token"] and cache["table_ids"]:
        return cache["app_token"], cache["table_ids"]
    cfg = load_config().get("feishu_bitable", {})
    app_token = cfg.get("trigger_time_app_token", "")
    # 优先读 table_ids 列表，兼容旧版 table_id 单值
    table_ids = cfg.get("trigger_time_table_ids", [])
    if not table_ids:
        old_id = cfg.get("trigger_time_table_id", "")
        if old_id:
            table_ids = [old_id]
    folder = cfg.get("trigger_time_folder", "NgdFfKVhtlg3RPdPiqAcUStNnop")
    if app_token and table_ids:
        # 自动发现云端所有触发时间表，补全 config 中缺失的
        try:
            cloud_tables = feishu_client.list_bitable_tables(app_token)
            for t in cloud_tables:
                tname = t.get("name", "")
                tid = t.get("table_id", "")
                if tid and tname.startswith("触发时间") and tid not in table_ids:
                    table_ids.append(tid)
                    logger.warning("自动发现云端触发时间表: [%s] %s", tname, tid)
            if len(table_ids) > len(cfg.get("trigger_time_table_ids", [])):
                _update_config_table_ids(app_token, table_ids)
        except Exception as e:
            logger.warning("查询云端表列表失败，仅使用 config 中的 %d 张表: %s", len(table_ids), e)
        cache["app_token"], cache["table_ids"], cache["inited"] = app_token, list(table_ids), True
        return app_token, list(table_ids)
    # 首次运行：自动创建多维表格
    logger.info("触发时间云端表格未配置，自动创建中...")
    result = feishu_client.create_bitable("触发时间记录", folder)
    app_token = result["app_token"]
    fields = [
        {"field_name": "jira号", "type": 1},
        {"field_name": "触发时间", "type": 1},
        {"field_name": "提取时间", "type": 1},
    ]
    table_id = feishu_client.create_bitable_table(app_token, "触发时间", fields)
    _delete_default_bitable_table(app_token, table_id)
    # 写回 config.yaml
    import yaml
    from src.config import CONFIG_PATH
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f) or {}
    config.setdefault("feishu_bitable", {})["trigger_time_app_token"] = app_token
    config["feishu_bitable"]["trigger_time_table_ids"] = [table_id]
    config["feishu_bitable"].pop("trigger_time_table_id", None)
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        yaml.dump(config, f, allow_unicode=True, default_flow_style=False)
    import src.config as _cfg_module
    _cfg_module._CONFIG = None
    cache["app_token"], cache["table_ids"], cache["inited"] = app_token, [table_id], True
    logger.info("触发时间云端表格已创建并回填: app_token=%s, table_ids=%s", app_token, [table_id])
    _migrate_local_trigger_times_to_cloud(app_token, table_id)
    return app_token, [table_id]


def _migrate_local_trigger_times_to_cloud(app_token: str, table_id: str):
    """一次性迁移：将本地 CSV 中的触发时间批量写入云端 bitable"""
    from src.clients import feishu_client
    local_times = _load_trigger_times_from_local()
    if not local_times:
        return
    records = [{"fields": {
        "jira号": bugid, "触发时间": tt
    }} for bugid, tt in local_times.items()]
    try:
        feishu_client.batch_create_records(app_token, table_id, records)
        logger.info("本地触发时间已迁移到云端: %d 条", len(records))
    except Exception as e:
        logger.warning("本地触发时间迁移失败: %s", e)


def _load_cloud_trigger_cache() -> tuple:
    """一次加载云端触发时间缓存，返回 (times_dict, keys_set)

    合并加载有触发时间的记录和已标记空的记录，避免两次 API 调用。
    云端不可用时降级读本地 CSV。
    当任一子表加载失败时，设置 _last_cache_load_partial 标记，
    不缓存结果，并禁止上层写入空值。

    :return: ({jira号: 触发时间}, {已记录的jira号})
    """
    import time
    global _last_cache_load_partial
    _ck = "cloud_trigger_cache"
    cached = _bitable_bulk_cache.get(_ck)
    if cached and time.time() - cached[0] < _BITABLE_CACHE_TTL:
        logger.info("云端触发时间缓存命中（TTL内）: %d 条有触发时间", len(cached[1][0]))
        return cached[1]
    from src.clients import feishu_client
    try:
        app_token, table_ids = _get_trigger_time_table_cfg()
        times = {}
        keys = set()
        partial = False  # 部分子表加载失败标记
        for tid in table_ids:
            try:
                records = feishu_client.list_bitable_records(app_token, tid)
                for rec in records:
                    fields = rec.get("fields", {})
                    jira_no = _bitable_text(fields.get("jira号", ""))
                    if not jira_no:
                        continue
                    keys.add(jira_no)
                    tt = _bitable_text(fields.get("触发时间", ""))
                    if tt:
                        times[jira_no] = tt
                    # 同时填充 bugid 缓存，避免后续 _ensure_trigger_time_bugid_cache 重复加载
                    if not _trigger_time_bugid_cache or jira_no not in _trigger_time_bugid_cache:
                        _trigger_time_bugid_cache[jira_no] = (tid, rec.get("record_id", ""), tt)
            except Exception as e:
                logger.warning("加载触发时间表 %s 失败，已跳过: %s", tid, e)
                partial = True
        logger.info("云端触发时间缓存加载完成: %d 条有触发时间, %d 条已记录%s",
                    len(times), len(keys), " (部分加载)" if partial else "")
        # 部分加载时不缓存结果，避免上层误判"云端没有"而触发空值覆盖
        if partial:
            _last_cache_load_partial = True
            logger.warning("云端触发时间缓存为部分加载，已跳过缓存写入，禁止本轮空值写入")
        else:
            _last_cache_load_partial = False
            _bitable_bulk_cache[_ck] = (time.time(), (times, keys))
        return times, keys
    except Exception as e:
        logger.warning("云端触发时间缓存加载失败，降级读本地 CSV: %s", e)
        _last_cache_load_partial = True
        return _load_trigger_times_from_local(), set()


def _load_trigger_times_from_cloud() -> dict:
    """从云端多维表格加载所有触发时间（支持多表），云端不可用时降级读本地 CSV

    :return: {jira号: 触发时间}
    """
    import time
    _ck = "trigger_times_cloud"
    cached = _bitable_bulk_cache.get(_ck)
    if cached and time.time() - cached[0] < _BITABLE_CACHE_TTL:
        logger.info("云端触发时间加载缓存命中（TTL内）: %d 条", len(cached[1]))
        return cached[1]
    from src.clients import feishu_client
    try:
        app_token, table_ids = _get_trigger_time_table_cfg()
        result = {}
        for tid in table_ids:
            try:
                records = feishu_client.list_bitable_records(app_token, tid)
                for rec in records:
                    fields = rec.get("fields", {})
                    jira_no = _bitable_text(fields.get("jira号", ""))
                    tt = _bitable_text(fields.get("触发时间", ""))
                    if jira_no and tt:
                        result[jira_no] = tt
            except Exception as e:
                logger.warning("加载触发时间表 %s 失败，已跳过: %s", tid, e)
        logger.info("云端触发时间加载完成: %d 条", len(result))
        _bitable_bulk_cache[_ck] = (time.time(), result)
        return result
    except Exception as e:
        logger.warning("云端触发时间加载失败，降级读本地 CSV: %s", e)
        return _load_trigger_times_from_local()


def _load_cloud_trigger_keys() -> set:
    """加载云端所有已记录的 jira 号（含空触发时间标记），用于跳过已处理记录

    :return: {jira号}
    """
    from src.clients import feishu_client
    try:
        app_token, table_ids = _get_trigger_time_table_cfg()
        keys = set()
        for tid in table_ids:
            try:
                records = feishu_client.list_bitable_records(app_token, tid)
                for rec in records:
                    jira_no = _bitable_text((rec.get("fields") or {}).get("jira号", ""))
                    if jira_no:
                        keys.add(jira_no)
            except Exception as e:
                logger.warning("加载触发时间表keys %s 失败，已跳过: %s", tid, e)
        logger.info("云端触发时间keys加载完成: %d 个", len(keys))
        return keys
    except Exception as e:
        logger.warning("云端触发时间keys加载失败: %s", e)
        return set()


def _load_all_cloud_trigger_records() -> list:
    """加载云端全量触发时间记录（含空触发时间），用于重新提取扫描

    :return: [{jira_no, trigger_time, table_id, record_id}]
    """
    from src.clients import feishu_client
    app_token, table_ids = _get_trigger_time_table_cfg()
    all_records = []
    valid_tables = 0
    for tid in table_ids:
        try:
            records = feishu_client.list_bitable_records(app_token, tid)
            valid_tables += 1
            for rec in records:
                fields = rec.get("fields", {})
                jira_no = _bitable_text(fields.get("jira号", ""))
                tt = _bitable_text(fields.get("触发时间", ""))
                if jira_no:
                    all_records.append({
                        "jira_no": jira_no,
                        "trigger_time": tt,
                        "table_id": tid,
                        "record_id": rec["record_id"],
                    })
        except Exception as e:
            logger.warning("加载触发时间表 %s 失败，已跳过: %s", tid, e)
    logger.info("云端全量触发时间加载完成: %d 条（%d/%d 个表成功）", len(all_records), valid_tables, len(table_ids))
    return all_records


def _ensure_trigger_time_bugid_cache():
    """懒加载触发时间缓存：首次访问时从云端加载所有表的 jira号 索引"""
    if _trigger_time_bugid_cache:
        return  # 缓存已填充
    from src.clients import feishu_client
    app_token, table_ids = _get_trigger_time_table_cfg()
    for tid in table_ids:
        try:
            records = feishu_client.list_bitable_records(app_token, tid)
            for rec in records:
                fields = rec.get("fields", {})
                jira_no = _bitable_text(fields.get("jira号", ""))
                trigger_time = _bitable_text(fields.get("触发时间", ""))
                if jira_no:
                    _trigger_time_bugid_cache[jira_no] = (tid, rec["record_id"], trigger_time)
        except Exception as e:
            logger.warning("初始化触发时间缓存失败(表 %s): %s", tid, e)
    logger.info("触发时间缓存已加载: %d 条记录", len(_trigger_time_bugid_cache))


def _save_trigger_time_to_cloud(bugid: str, trigger_time: str):
    """将单条触发时间写入云端 bitable（有则更新，无则新建），云端成功后再写本地 CSV"""
    # 空值保护：不覆盖已有的非空触发时间
    if not trigger_time:
        _ensure_trigger_time_bugid_cache()
        cached = _trigger_time_bugid_cache.get(bugid)
        if cached and isinstance(cached, tuple) and len(cached) >= 3:
            existing_time = cached[2]
            if existing_time:
                logger.warning("跳过空值写入，bugid=%s 云端已有触发时间: %s", bugid, existing_time)
                return
        # 缓存不完整时也禁止写入空值
        if _last_cache_load_partial:
            logger.warning("跳过空值写入，bugid=%s 云端缓存为部分加载，无法确认是否已有值", bugid)
            return
    # 懒加载缓存
    _ensure_trigger_time_bugid_cache()
    # 单条更新：优先用缓存直接定位，避免全表扫描
    cached = _trigger_time_bugid_cache.get(bugid)
    cloud_ok = False
    if cached and isinstance(cached, tuple) and len(cached) >= 3:
        tid, rec_id, _ = cached
        try:
            app_token, _ = _get_trigger_time_table_cfg()
            from src.clients import feishu_client
            feishu_client.update_bitable_records(app_token, tid, [
                {"record_id": rec_id, "fields": {"触发时间": trigger_time}}
            ])
            # 更新缓存时间戳
            _trigger_time_bugid_cache[bugid] = (tid, rec_id, trigger_time)
            logger.info("云端触发时间单条更新(缓存命中): %s -> %s", bugid, trigger_time)
            cloud_ok = True
        except Exception as e:
            logger.warning("缓存更新失败 %s，回退批量模式: %s", bugid, e)
            _trigger_time_bugid_cache.pop(bugid, None)
    if not cloud_ok:
        # 缓存未命中或更新失败：走批量模式
        cloud_ok = _batch_save_trigger_times_to_cloud({bugid: trigger_time})
    # 云端成功后才写本地 CSV，避免云端失败时本地多余
    if cloud_ok:
        _save_trigger_time_to_csv(bugid, trigger_time)
        # 清除云端触发时间批量缓存，确保后续步骤能读到最新数据
        _bitable_bulk_cache.pop("cloud_trigger_cache", None)
    else:
        logger.warning("云端写入失败，跳过本地 CSV 保存: %s", bugid)


def _batch_save_trigger_times_to_cloud(items: dict) -> bool:
    """批量将触发时间写入云端 bitable，只加载一次表数据。items: {bugid: trigger_time}

    :return: 云端写入是否成功
    """
    from src.clients import feishu_client
    if not items:
        return True
    try:
        app_token, table_ids = _get_trigger_time_table_cfg()
        # 一次性加载所有表数据
        all_records = {}  # {table_id: [records]}
        table_counts = {}
        valid_tids = []
        jira_index = {}  # {bugid: (table_id, record)} 用于快速查找已有记录
        for tid in table_ids:
            try:
                records = feishu_client.list_bitable_records(app_token, tid)
                all_records[tid] = records
                table_counts[tid] = len(records)
                valid_tids.append(tid)
                for rec in records:
                    fields = rec.get("fields", {})
                    jira_no = _bitable_text(fields.get("jira号", ""))
                    if jira_no:
                        jira_index[jira_no] = (tid, rec)
            except Exception as e:
                if "TableIdNotFound" in str(e) or "1254041" in str(e):
                    logger.warning("触发时间子表已不存在，已跳过: %s", tid)
                else:
                    logger.warning("加载触发时间表 %s 失败，已跳过: %s", tid, e)
        # 清理无效 table_id
        invalid_tids = [tid for tid in table_ids if tid not in valid_tids]
        if invalid_tids and valid_tids:
            _trigger_time_table_cache["table_ids"] = valid_tids
            _update_config_table_ids(app_token, valid_tids)
        table_ids = valid_tids
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        # 按表分组：更新 vs 新建
        updates_by_table = {}  # {tid: [{"record_id":..., "fields":...}]}
        new_items = []  # [(bugid, trigger_time)] 需要新建的
        for bugid, trigger_time in items.items():
            # 空值保护：不覆盖已有的非空触发时间
            if not trigger_time and bugid in jira_index:
                tid_check, rec_check = jira_index[bugid]
                existing_tt = _bitable_text(rec_check.get("fields", {}).get("触发时间", ""))
                if existing_tt:
                    logger.warning("跳过空值写入，bugid=%s 云端已有触发时间: %s", bugid, existing_tt)
                    continue
            # 缓存不完整时禁止写入空值
            if not trigger_time and _last_cache_load_partial:
                logger.warning("跳过空值写入，bugid=%s 云端缓存为部分加载", bugid)
                continue
            if bugid in jira_index:
                tid, rec = jira_index[bugid]
                updates_by_table.setdefault(tid, []).append({
                    "record_id": rec["record_id"],
                    "fields": {"触发时间": trigger_time}
                })
            else:
                new_items.append((bugid, trigger_time))
        # 批量更新
        for tid, recs in updates_by_table.items():
            feishu_client.update_bitable_records(app_token, tid, recs)
            logger.info("云端触发时间批量更新: %d 条 (表 %s)", len(recs), tid)
            # 更新本地缓存（从已加载的 jira_index 反向查找）
            for item in recs:
                rec_id = item.get("record_id")
                if rec_id:
                    for b, (t, r) in jira_index.items():
                        if r.get("record_id") == rec_id:
                            tt = item["fields"].get("触发时间", "")
                            _trigger_time_bugid_cache[b] = (t, rec_id, tt)
                            break
        # 批量新建：按 500 条上限分批写入，优先填充空位最多的表
        if new_items:
            remaining = list(new_items)
            while remaining:
                # 按剩余空间从大到小排序，优先填空位最多的表
                available = [(tid, _TRIGGER_TIME_TABLE_LIMIT - table_counts.get(tid, 0))
                             for tid in table_ids if table_counts.get(tid, 0) < _TRIGGER_TIME_TABLE_LIMIT]
                available.sort(key=lambda x: x[1], reverse=True)
                if not available:
                    # 所有表已满，创建新表
                    from src.clients import feishu_client as _fc
                    cloud_tables = _fc.list_bitable_tables(app_token)
                    cloud_tids = {t["table_id"] for t in cloud_tables if t.get("table_id")}
                    cloud_tids.update(table_ids)
                    target_tid = _create_trigger_time_subtable(app_token, len(table_ids) + 1, cloud_tids)
                    table_ids.append(target_tid)
                    table_counts[target_tid] = 0
                    _trigger_time_table_cache["table_ids"] = list(table_ids)
                    _update_config_table_ids(app_token, table_ids)
                    space = _TRIGGER_TIME_TABLE_LIMIT
                else:
                    target_tid, space = available[0]
                batch = remaining[:space]
                remaining = remaining[space:]
                create_records = [{"fields": {"jira号": bid, "触发时间": tt, "提取时间": now_str}} for bid, tt in batch]
                feishu_client.batch_create_records(app_token, target_tid, create_records)
                table_counts[target_tid] = table_counts.get(target_tid, 0) + len(batch)
                logger.info("云端触发时间批量新建: %d 条 (表 %s, 当前 %d/%d)",
                            len(create_records), target_tid, table_counts[target_tid], _TRIGGER_TIME_TABLE_LIMIT)
            # 更新本地缓存
            for bid, tt in new_items:
                _trigger_time_bugid_cache.pop(bid, None)
    except Exception as e:
        logger.warning("云端触发时间批量写入失败: %s", e)
        # 云端写入失败时保留本地缓存，避免下次重复提取（本地与云端短暂不一致可接受）
        return False
    # 批量写入成功后清除云端触发时间批量缓存，确保后续步骤能读到最新数据
    _bitable_bulk_cache.pop("cloud_trigger_cache", None)
    return True


def _remove_local_trigger_entries(jira_keys: set):
    """从本地 CSV 中删除指定的 jira 号条目，保持与云端一致"""
    import csv as _csv
    if not jira_keys:
        return
    data_dir = os.path.join(PROJECT_ROOT, "data")
    removed = 0
    for root, _dirs, files in os.walk(data_dir):
        for filename in files:
            if not filename.startswith("trigger_times_") or not filename.endswith(".csv"):
                continue
            path = os.path.join(root, filename)
            try:
                rows = []
                with open(path, "r", encoding="utf-8-sig") as f:
                    for row in _csv.DictReader(f):
                        rows.append(row)
                keep = [r for r in rows if (r.get("jira号") or "").strip() not in jira_keys]
                if len(keep) < len(rows):
                    removed += len(rows) - len(keep)
                    with open(path, "w", encoding="utf-8-sig", newline="") as f:
                        writer = _csv.DictWriter(f, fieldnames=["jira号", "触发时间", "提取时间"])
                        writer.writeheader()
                        writer.writerows(keep)
            except Exception:
                pass
    if removed:
        logger.info("已从本地 CSV 清理 %d 条未同步到云端的记录", removed)


def _refresh_trigger_time_bugid_cache(app_token: str, table_ids: list):
    """刷新 bugid 缓存，从所有表中重建索引"""
    from src.clients import feishu_client
    _trigger_time_bugid_cache.clear()
    for tid in table_ids:
        try:
            records = feishu_client.list_bitable_records(app_token, tid)
            for rec in records:
                fields = rec.get("fields", {})
                jira_no = _bitable_text(fields.get("jira号", ""))
                trigger_time = _bitable_text(fields.get("触发时间", ""))
                if jira_no:
                    _trigger_time_bugid_cache[jira_no] = (tid, rec["record_id"], trigger_time)
        except Exception as e:
            logger.warning("刷新 bugid 缓存失败(表 %s): %s", tid, e)


def _create_trigger_time_subtable(app_token: str, index: int, existing_table_ids: set = None) -> str:
    """创建触发时间子表（触发时间_N），返回 table_id

    遇到重名则跳过，继续创建下一个编号，直到成功。
    """
    from src.clients import feishu_client
    fields = [
        {"field_name": "jira号", "type": 1},
        {"field_name": "触发时间", "type": 1},
        {"field_name": "提取时间", "type": 1},
    ]
    for i in range(10):  # 最多尝试10次避免死循环
        name = f"触发时间_{index + i}"
        try:
            table_id = feishu_client.create_bitable_table(app_token, name, fields)
            _delete_default_bitable_table(app_token, table_id, keep_table_ids=existing_table_ids)
            logger.info("触发时间子表已创建: %s -> %s", name, table_id)
            return table_id
        except ValueError as e:
            if "TableNameDuplicated" in str(e):
                logger.info("子表 %s 已存在，跳过尝试下一个...", name)
                continue
            raise
    raise RuntimeError(f"连续创建 10 个子表均重名，请检查云端多维表格")


def _update_config_table_ids(app_token: str, table_ids: list):
    """更新 config.yaml 中的 table_ids 列表"""
    import yaml
    from src.config import CONFIG_PATH
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            config = yaml.safe_load(f) or {}
        config.setdefault("feishu_bitable", {})["trigger_time_table_ids"] = list(table_ids)
        config["feishu_bitable"].pop("trigger_time_table_id", None)
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            yaml.dump(config, f, allow_unicode=True, default_flow_style=False)
        import src.config as _cfg_module
        _cfg_module._CONFIG = None
    except Exception as e:
        logger.warning("更新 config table_ids 失败: %s", e)


def _load_cache_batch_progress() -> dict:
    """加载本地缓存批量提取进度，返回 {bugid: {time, source, status}}"""
    try:
        if os.path.exists(_CACHE_BATCH_PROGRESS_FILE):
            with open(_CACHE_BATCH_PROGRESS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            logger.info("加载本地缓存批量进度: %d 条记录", len(data))
            return data
    except Exception as e:
        logger.warning("加载本地缓存批量进度失败: %s", e)
    return {}


def _save_cache_batch_progress(progress: dict):
    """保存缓存批量提取进度到本地文件"""
    try:
        os.makedirs(os.path.dirname(_CACHE_BATCH_PROGRESS_FILE), exist_ok=True)
        with open(_CACHE_BATCH_PROGRESS_FILE, "w", encoding="utf-8") as f:
            json.dump(progress, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.warning("保存本地缓存批量进度失败: %s", e)


def _invalidate_bitable_cache():
    """清除批量加载缓存，在数据写入时调用"""
    global _last_cache_load_partial
    _bitable_bulk_cache.clear()
    _last_cache_load_partial = False


def rebalance_trigger_time_tables() -> dict:
    """再平衡触发时间表：把超过500的表中多余记录搬运到不足500的表中

    :return: {"moved": int, "details": [str]}
    """
    from src.clients import feishu_client
    app_token, table_ids = _get_trigger_time_table_cfg()
    if not app_token or not table_ids:
        return {"moved": 0, "details": ["无触发时间表配置"]}
    # 加载所有表的数据
    table_data = {}  # {tid: [records]}
    for tid in table_ids:
        try:
            records = feishu_client.list_bitable_records(app_token, tid)
            table_data[tid] = records
        except Exception as e:
            logger.warning("再平衡：加载表 %s 失败，已跳过: %s", tid, e)
    # 分组：超限表 vs 有余量表
    overflow_tables = []  # [(tid, excess_records)]
    available_tables = []  # [(tid, space)]
    for tid, records in table_data.items():
        count = len(records)
        if count > _TRIGGER_TIME_TABLE_LIMIT:
            excess = records[_TRIGGER_TIME_TABLE_LIMIT:]
            overflow_tables.append((tid, excess))
        elif count < _TRIGGER_TIME_TABLE_LIMIT:
            available_tables.append((tid, _TRIGGER_TIME_TABLE_LIMIT - count))
    if not overflow_tables:
        return {"moved": 0, "details": ["无超限表，无需再平衡"]}
    if not available_tables:
        return {"moved": 0, "details": ["无有余量表，无法再平衡"]}
    # 按余量从大到小排序
    available_tables.sort(key=lambda x: x[1], reverse=True)
    total_moved = 0
    details = []
    for src_tid, excess in overflow_tables:
        remaining = list(excess)
        # 从源表删除多余记录
        excess_ids = [r["record_id"] for r in excess]
        for i in range(0, len(excess_ids), 500):
            feishu_client.batch_delete_records(app_token, src_tid, excess_ids[i:i + 500])
        details.append(f"从表 {src_tid} 移除 {len(excess)} 条超限记录")
        # 分配到有空间的表
        while remaining:
            if not available_tables:
                details.append(f"警告：{len(remaining)} 条记录无有余量表可存放")
                break
            dst_tid, space = available_tables[0]
            batch = remaining[:space]
            remaining = remaining[space:]
            # 重建记录（只保留核心字段）
            create_records = []
            for rec in batch:
                fields = rec.get("fields", {})
                create_records.append({"fields": {
                    "jira号": _bitable_text(fields.get("jira号", "")),
                    "触发时间": _bitable_text(fields.get("触发时间", "")),
                    "提取时间": _bitable_text(fields.get("提取时间", "")),
                }})
            feishu_client.batch_create_records(app_token, dst_tid, create_records)
            moved = len(create_records)
            total_moved += moved
            details.append(f"写入表 {dst_tid}: {moved} 条")
            # 更新剩余空间
            available_tables[0] = (dst_tid, space - moved)
            if available_tables[0][1] <= 0:
                available_tables.pop(0)
    # 清除缓存，下次重新加载
    _invalidate_bitable_cache()
    return {"moved": total_moved, "details": details}
