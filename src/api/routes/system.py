"""系统管理路由：配置读写、服务控制、概览"""
import asyncio
import copy
import os
import shutil
import signal
import subprocess
import sys
import tempfile

import yaml
from fastapi import APIRouter, Request

from src import config as cfg_module
from src.config import get_path, load_config, setup_logger, PROJECT_ROOT
from src.api.routes.shared import ok, fail, read_csv_rows
from src.schemas.common import ApiResponse

logger = setup_logger("web.system")
router = APIRouter()


@router.post("/api/shutdown", response_model=ApiResponse)
async def shutdown_server():
    """优雅关闭服务：发送 Ctrl+C 信号让整个进程组正常退出"""
    logger.info("收到关闭请求，正在优雅退出...")
    _flag = os.path.join(PROJECT_ROOT, "data", ".web_browser_opened")
    try:
        if os.path.exists(_flag):
            os.remove(_flag)
    except Exception:
        pass

    def _do_shutdown():
        if os.name == "nt":
            os.kill(0, signal.CTRL_C_EVENT)
        else:
            os.kill(os.getpid(), signal.SIGINT)

    loop = asyncio.get_event_loop()
    loop.call_later(0.3, _do_shutdown)
    return ok(message="服务正在关闭...")


@router.post("/api/restart", response_model=ApiResponse)
async def restart_server():
    """重启 worker：只终止当前 worker，reloader 会自动拉起新 worker 加载最新代码"""
    logger.info("收到重启请求，终止 worker 让 reloader 自动重启...")
    loop = asyncio.get_event_loop()
    loop.call_later(0.3, lambda: sys.exit(0))
    return ok(message="worker 正在终止，reloader 将自动重启...")


# ── 配置读写辅助 ──
# 敏感字段占位符：GET 用占位符替换真实值，前端原样回传或留空都表示“保持原值”
_MASK = "********"
# 键名命中以下关键字视为敏感（密钥/令牌/登录态），不回显也不允许被占位符覆盖
_SENSITIVE_KEYWORDS = (
    "token", "secret", "password", "passwd", "api_key", "apikey",
    "app_key", "appkey", "cookie", "credential", "private_key",
)
# 这些后缀是“地址/字段名”而非密钥，即使命中关键字也不脱敏（如 diana.token_url）
_SENSITIVE_EXCLUDE_SUFFIX = ("_url", "_uri", "_field", "_column", "_timeout", "_path", "_dir")
# 页面不可改写的配置段（内部服务地址，避免被误改后难以恢复）
_READONLY_SECTIONS = frozenset({"app_log_server"})
# 目录类配置：只允许项目内路径（防止把输出目录写到仓库外）
_PATH_KEY_SUFFIX = "_dir"
# 留空时自动回退复用其它段的字段（与 feishu_client._get_bot_cfg 的规则保持一致）
_FALLBACK_FIELDS = {
    "feishu_bot.app_id": "feishu_bitable.app_id",
    "feishu_bot.app_secret": "feishu_bitable.app_secret",
}
# 共用凭证：所有人共用同一套，页面只读、后端拒绝修改与删除（要改只能直接编辑 config.yaml）
_PROTECTED_FIELDS = frozenset({
    "feishu_bitable.app_id",
    "feishu_bitable.app_secret",
})


def _is_sensitive_key(key: str) -> bool:
    """按键名判断是否为敏感字段（密钥/令牌/登录态）"""
    low = key.lower()
    if low.endswith(_SENSITIVE_EXCLUDE_SUFFIX):
        return False
    return any(kw in low for kw in _SENSITIVE_KEYWORDS)


def _mask_section(section: str, values: dict) -> tuple:
    """脱敏单个配置段，返回 (脱敏后的段, 被脱敏的字段路径列表)"""
    masked, sensitive = {}, []
    for key, value in values.items():
        if _is_sensitive_key(key) and isinstance(value, str) and value.strip():
            masked[key] = _MASK
            sensitive.append(f"{section}.{key}")
        else:
            masked[key] = value
    return masked, sensitive


def _assert_protected_unchanged(cfg: dict, updates: dict, deletes) -> None:
    """共用凭证的写保护：页面既不能改也不能删，只能直接编辑 config.yaml

    只拦截“实质性变更”：掩码占位符、空值、与原值相同的回传都视为未修改，
    这样页面正常保存（把原值原样带回来）不会被挡住。
    """
    for entry in deletes or []:
        path = _parse_delete_path(entry)
        if len(path) >= 2 and ".".join(path[:2]) in _PROTECTED_FIELDS:
            raise ValueError(f"{'.'.join(path[:2])} 是共用凭证，不允许删除（如需变更请直接编辑 config/config.yaml）")
    for path in _PROTECTED_FIELDS:
        section, _, key = path.partition(".")
        values = updates.get(section)
        if not isinstance(values, dict) or key not in values:
            continue
        new_value = values[key]
        if new_value is None or new_value == _MASK or (isinstance(new_value, str) and not new_value.strip()):
            continue  # 掩码/留空 = 不修改
        old_values = cfg.get(section)
        old_value = old_values.get(key) if isinstance(old_values, dict) else None
        if str(new_value) != str(old_value or ""):
            raise ValueError(f"{path} 是共用凭证，不允许在页面修改（如需变更请直接编辑 config/config.yaml）")


def _fallback_hints(cfg: dict) -> dict:
    """生成“留空则复用”的提示：{目标字段路径: {"from": 来源路径, "preview": 生效值预览}}

    机器人等字段留空时并不等于没配置，而是回退复用另一段的凭证；
    页面需要知道这一点，否则只会显示“未配置”而让人误以为缺值。
    """
    hints = {}
    for path, source in _FALLBACK_FIELDS.items():
        section, _, key = source.partition(".")
        values = cfg.get(section)
        source_value = values.get(key) if isinstance(values, dict) else None
        if source_value is None:
            source_value = ""
        if not isinstance(source_value, str):
            source_value = str(source_value)
        # 预览：密钥类只说明“已配置”，普通值直接给出（如 app_id）
        preview = ("已配置" if _is_sensitive_key(key) else source_value) if source_value else ""
        hints[path] = {"from": source, "preview": preview}
    return hints


def _merge_section(old: dict, new: dict) -> dict:
    """字段级合并配置段

    - 未出现的字段保持不变（旧客户端只提交部分字段也不会丢配置）
    - 敏感字段收到占位符/空值时保留原密钥（避免把 ****** 写进配置）
    - 嵌套字典递归合并，列表整体替换
    """
    result = dict(old)
    for key, value in new.items():
        if key.startswith("_"):
            continue  # 前端临时键（如 _newKey）不落盘
        old_value = result.get(key)
        if _is_sensitive_key(key) and isinstance(old_value, str) and old_value.strip():
            if value is None or value == _MASK or (isinstance(value, str) and not value.strip()):
                continue  # 留空/占位符 → 保留旧密钥
        if isinstance(old_value, dict) and isinstance(value, dict):
            result[key] = _merge_section(old_value, value)
        else:
            result[key] = value
    return result


def _parse_delete_path(entry) -> list:
    """解析删除项：支持 ["section","key",...] / {"section","key","sub"} / "section.key" """
    if isinstance(entry, (list, tuple)):
        return [str(p) for p in entry if str(p).strip()]
    if isinstance(entry, dict):
        parts = [entry.get("section"), entry.get("field") or entry.get("key"), entry.get("sub")]
        return [str(p) for p in parts if p]
    if isinstance(entry, str):
        return [p for p in entry.split(".") if p]
    return []


def _apply_deletes(cfg: dict, deletes) -> list:
    """按路径删除配置项，返回实际删除的路径列表（用于回显）"""
    removed = []
    for entry in deletes or []:
        path = _parse_delete_path(entry)
        if len(path) < 2:
            continue
        node = cfg
        for part in path[:-1]:
            node = node.get(part) if isinstance(node, dict) else None
            if not isinstance(node, dict):
                break
        if isinstance(node, dict) and path[-1] in node:
            node.pop(path[-1], None)
            removed.append(".".join(path))
    return removed


def _is_unsafe_relpath(value: str) -> bool:
    """目录配置是否为“仓库外路径”：含 .. 或指向项目根之外的绝对路径"""
    normalized = str(value).replace("\\", "/")
    if ".." in normalized.split("/"):
        return True
    if os.path.isabs(normalized) or (len(normalized) > 1 and normalized[1] == ":"):
        root = PROJECT_ROOT.replace("\\", "/").rstrip("/")
        return not (normalized.rstrip("/") == root or normalized.startswith(root + "/"))
    return False


def _validate_updates(updates: dict) -> None:
    """只校验本次提交的字段，不碰未提交的配置（避免误伤测试/历史数据）"""
    for section, values in updates.items():
        if not isinstance(values, dict):
            continue
        for key, value in values.items():
            if not str(key).endswith(_PATH_KEY_SUFFIX):
                continue
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{section}.{key} 必须是非空字符串")
            if _is_unsafe_relpath(value):
                raise ValueError(
                    f"{section}.{key} 只能是项目内路径，不能用 .. 或指向项目外（当前值: {value}）")


def _write_config(cfg: dict) -> str:
    """原子写回 config.yaml：先写临时文件再替换，并保留上一版备份"""
    path = cfg_module.CONFIG_PATH
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    tmp_path = f"{path}.tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        yaml.safe_dump(cfg, f, allow_unicode=True, sort_keys=False)
    backup = ""
    try:
        if os.path.exists(path):
            backup = f"{path}.bak"
            shutil.copy2(path, backup)
    except OSError as e:
        logger.warning("配置备份失败（继续写入）: %s", e)
        backup = ""
    os.replace(tmp_path, path)
    return backup


@router.get("/api/config", response_model=ApiResponse)
def get_config():
    """读取当前全局配置：敏感字段以占位符返回，内部服务段不下发"""
    cfg = load_config()
    data, sensitive = {}, []
    for section, values in cfg.items():
        if section in _READONLY_SECTIONS:
            continue
        if isinstance(values, dict):
            masked, paths = _mask_section(section, values)
            data[section] = masked
            sensitive.extend(paths)
        else:
            data[section] = values
    data["_sensitive"] = sensitive
    data["_mask"] = _MASK
    data["_fallbacks"] = _fallback_hints(cfg)
    data["_locked"] = sorted(_PROTECTED_FIELDS)
    return ok(data)


@router.post("/api/config", response_model=ApiResponse)
async def save_config(request: Request):
    """更新配置：字段级合并 + 显式删除 + 敏感字段保留，原子写回 config.yaml

    请求体支持两种形式（旧式仍兼容）：
    1) {"config": {"<段>": {...}}, "delete": [["<段>", "<字段>"], ...]}
    2) {"<段>": {...}}  （等价于只带 config）
    """
    try:
        raw = await request.json() or {}
        if not isinstance(raw, dict):
            return fail("请求体必须是 JSON 对象")
        updates = raw.get("config") if isinstance(raw.get("config"), dict) else raw
        deletes = raw.get("delete") or []
        # 无变更时不落盘：避免仅因一次空提交就重写文件（重写会丢注释）
        if not updates and not deletes:
            return ok({"sections": [], "removed": [], "backup": ""}, "没有需要保存的变更")
        _validate_updates(updates)

        cfg = copy.deepcopy(load_config())
        _assert_protected_unchanged(cfg, updates, deletes)
        removed = _apply_deletes(cfg, deletes)
        changed = []
        for section, values in updates.items():
            if section.startswith("_") or section in _READONLY_SECTIONS:
                continue
            if not isinstance(values, dict):
                cfg[section] = values
                changed.append(section)
                continue
            base = cfg.get(section)
            base = dict(base) if isinstance(base, dict) else {}
            cfg[section] = _merge_section(base, values)
            changed.append(section)

        backup = _write_config(cfg)
        load_config(cfg_module.CONFIG_PATH)
        logger.info("配置已由页面更新: 段=%s, 删除=%s", changed, removed)
        detail = f"已更新 {len(changed)} 个配置段"
        if removed:
            detail += f"，删除 {len(removed)} 个字段"
        return ok({"sections": changed, "removed": removed, "backup": backup},
                  f"配置保存成功（{detail}）")
    except ValueError as e:
        logger.warning("配置校验失败: %s", e)
        return fail(f"配置校验失败: {e}")
    except Exception as e:
        logger.error("配置保存失败: %s", e)
        return fail(f"配置保存失败: {e}")


@router.get("/api/overview", response_model=ApiResponse)
def overview():
    """首页概览：统计指标与接口模式状态"""
    from datetime import datetime
    cfg = load_config()
    daily = read_csv_rows(
        os.path.join(get_path("doc_dir"),
                     datetime.now().strftime("%Y-%m-%d"),
                     f"{datetime.now().strftime('%Y-%m-%d')}_daily.csv")
    )
    audited = read_csv_rows(os.path.join(get_path("report_dir"), cfg["audit"]["audited_file"]))
    supplement_fields = ["分析问题时间", "AI分析结果(飞书链接)", "AI评论总结", "rootcause", "结果置信度"]
    complete_count = sum(1 for r in daily if all(
        (r.get(f) or "").strip() not in ("", "-", "None") for f in supplement_fields))
    data = {
        "today": datetime.now().strftime("%Y-%m-%d"),
        "mock": {
            "ai_log": bool(cfg["ai_log_api"].get("mock")),
            "jira": bool(cfg["jira_api"].get("mock")),
            "kb": bool(cfg["knowledge_base_api"].get("mock")),
        },
        "daily_total": len(daily),
        "daily_complete": complete_count,
        "daily_incomplete": len(daily) - complete_count,
        "audited_total": len(audited),
    }
    return ok(data)


_MAX_APP_LOG_BYTES = 1024 * 1024 * 1024  # app.log 下载上限 1GB


@router.get("/api/applog/download")
async def download_app_log(source: str = "pc"):
    """代理下载远程服务器 app.log（流式落盘 + 体积上限），source=pc|online

    原先用 client.get() 把整个日志读进内存，几 GB 的日志会直接把进程打满；
    现在改为流式写临时文件，成功后再原子替换，超限即中止并清理半成品。
    """
    import httpx
    cfg_all = load_config().get("app_log_server", {})
    # 兼容旧配置：如果没有 pc/online 分层，直接用默认值
    if source not in cfg_all and "host" in cfg_all:
        cfg = cfg_all
    else:
        cfg = cfg_all.get(source, cfg_all.get("pc", {}))
    host = cfg.get("host", "10.22.126.133")
    port = cfg.get("port", 8001)
    endpoint = cfg.get("endpoint", "/api/logs/download")
    url = f"http://{host}:{port}{endpoint}"
    # 保存路径：项目根目录/logs/app_{source}.log
    logs_dir = os.path.join(PROJECT_ROOT, "logs")
    os.makedirs(logs_dir, exist_ok=True)
    filename = "app.log" if source == "pc" else f"app_{source}.log"
    save_path = os.path.join(logs_dir, filename)
    tmp_path = f"{save_path}.part"
    label = "PC" if source == "pc" else "线上"
    total = 0
    try:
        async with httpx.AsyncClient(timeout=120) as client:
            async with client.stream("GET", url) as resp:
                resp.raise_for_status()
                with open(tmp_path, "wb") as f:
                    async for chunk in resp.aiter_bytes(chunk_size=1024 * 1024):
                        total += len(chunk)
                        if total > _MAX_APP_LOG_BYTES:
                            raise ValueError(
                                f"日志超过 {_MAX_APP_LOG_BYTES // 1024 // 1024}MB 上限"
                                f"（已下载 {total / 1024 / 1024:.1f}MB），已中止")
                        f.write(chunk)
        os.replace(tmp_path, save_path)
        size_mb = total / 1024 / 1024
        logger.info("[%s] app.log 已下载到 %s (%.2f MB)", label, save_path, size_mb)
        return ok({"path": save_path, "size_mb": round(size_mb, 2)}, f"{label} 下载成功")
    except httpx.ConnectError:
        return fail(f"无法连接{source}服务器 {host}:{port}，请检查网络或服务器状态")
    except httpx.TimeoutException:
        return fail("下载超时（120秒），文件可能过大或网络不稳定")
    except ValueError as e:
        return fail(str(e))
    except Exception as e:
        logger.error("app.log 下载失败: %s", e)
        return fail(f"下载失败: {str(e)[:200]}")
    finally:
        # 失败时清理半成品，避免留下不完整文件
        if os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError:
                pass


@router.post("/api/applog/open_folder")
def open_app_log_folder():
    """打开 app.log 所在目录"""
    logs_dir = os.path.join(PROJECT_ROOT, "logs")
    if not os.path.isdir(logs_dir):
        return fail("logs 目录不存在")
    try:
        if os.name == "nt":
            os.startfile(logs_dir)
        else:
            subprocess.Popen(["xdg-open", logs_dir])
        return ok(message="已打开目录")
    except Exception as e:
        return fail(f"打开目录失败: {e}")
