#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
adp_chat.py — adp-chat-analysis skill 唯一脚本入口。

分析 ADP 应用历史对话的只读工具（describe_app_summary_list /
describe_unsatisfied_reply_list / describe_msg_record_category_list /
describe_msg_record_list / describe_record_trace_info /
describe_conversation_message_list）全部经本脚本调用，底层走 adp_app_manager
MCP Server（与 adp-app-builder 共用端点，本 skill 白名单独立）。

设计参考 tencentcloud-adp-kb-management 的接口形态：命名参数子命令 +
脚本内自动分页/自动时间窗口/摘要输出，LLM 不手写 JSON 入参、不手算时间戳。

子命令：
    apps        按应用名找 app_id / 列出空间下应用（用户只给应用名时先用它）
    categories  消息记录分类树
    unsatisfied 不满意回复列表（附下钻命令提示）
    records     消息记录列表（自动窗口 30→90→180→365 天、自动翻页、统计摘要）
    trace       单条记录执行链路（可自动定位 conversation_id）
    messages    会话上下文消息（以某条 record 为锚点查前后文）
    call        白名单内工具的裸调用兜底（极少用到）
    list-tools  打印工具白名单（自检）

用法示例：
    python3 scripts/adp_chat.py apps --query 客服            # 按名称找 app_id
    python3 scripts/adp_chat.py categories --app-id 2087148599915662464
    python3 scripts/adp_chat.py unsatisfied --app-id 2087148599915662464
    python3 scripts/adp_chat.py records  --app-id 2087148599915662464 --days 30
    python3 scripts/adp_chat.py records  --app-id 2087148599915662464 --json
    python3 scripts/adp_chat.py trace    --app-id 2087148599915662464 --record-id p9L_xxx
    python3 scripts/adp_chat.py messages --app-id 2087148599915662464 \
      --conversation-id <sid> --record-id <rid> --type 2
    python3 scripts/adp_chat.py call describe_msg_record_list '{"app_id":"..."}'

环境变量（凭据静默：仅从环境读取，不索要、不落盘、不打印）：
    ADP_API_KEY           self-serve 模式 Bearer token
    ADP_DELEGATE_API_KEY  delegate 模式（检测到即优先，两模式互斥不回退）
    ADP_APP_ID / ADP_DELEGATE_APP_ID   app_id 缺省来源（按鉴权模式绑定：delegate 只认
                                        ADP_DELEGATE_APP_ID，self-serve 只认 ADP_APP_ID，不跨模式回退）
    ADP_PLUGIN_GW_HOST / ADP_PLUGIN_GW_SCHEME  网关覆盖（自动补 schema，host 自动入白名单）

退出码：0 ok / 1 参数错误（含 tool 不在白名单）/ 2 配置缺失（含凭据未注入、URL 不在白名单）
        / 3 网络或平台错误 / 4 鉴权失败（401/403）

依赖：Python 3.8+ 与 requests。
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Any, Optional

try:
    import requests
except ImportError:  # pragma: no cover
    sys.stderr.write("ERROR: Python 依赖 `requests` 未安装。请执行：pip install requests\n")
    sys.exit(2)

try:
    requests.packages.urllib3.disable_warnings()  # type: ignore[attr-defined]
except Exception:
    pass

# locale 兜底：部分环境 stdout 编码退化为 ASCII，中文摘要会变 "?"。
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    except (AttributeError, ValueError):
        pass

USER_AGENT = "adp-chat-analysis-skill/2.0 (+adp_chat.py)"
PROTOCOL_VERSION = "2024-11-05"
DEFAULT_TIMEOUT = 60

EXIT_OK = 0
EXIT_BAD_ARGS = 1
EXIT_CONFIG = 2
EXIT_NETWORK_OR_SERVER = 3
EXIT_AUTH = 4

MCP_CONFIG_PATH = Path(__file__).resolve().parent.parent / "mcp.json"

# records 自动窗口序列：--days 未指定时按此顺序试探，首个 total>0 的窗口生效。
AUTO_WINDOWS = (30, 90, 180, 365)
# 疑似兜底/拒答话术模式（可按业务扩充），用于 fallback_rate 指标计算。
# 借鉴 adp-conversation-optimizer 的 FALLBACK_PATTERNS 设计。
MAX_PAGES = 50  # 翻页保险丝，防异常响应导致死循环

# 疑似兜底/拒答话术模式（可按业务扩充），用于 fallback_rate 指标计算。
# 借鉴 adp-conversation-optimizer 的 FALLBACK_PATTERNS 设计。
FALLBACK_PATTERNS = [
    "抱歉", "无法回答", "没有找到", "不知道", "无法提供", "暂时无法",
    "我不清楚", "无法帮您", "请联系人工", "换个问题", "超出我的",
    "没有相关", "未能理解", "无法识别", "已知内容无法回答",
]


def _norm_question(q: str) -> str:
    """问题归一化：去空白去标点截断，用于高频问题聚类。"""
    q = re.sub(r"\s+", "", str(q or ""))
    q = re.sub(r"[，。！？、,.!?~：:；;\"'（）()【】\[\]]", "", q)
    return q[:40]


_IMG_MD_RE = re.compile(r"!\[[^\]]*\]\([^)]*\)")


def _strip_images(q: str) -> str:
    """剥离消息中的 markdown 图片标记 ![alt](url)，保留其余文字，用于高频问题聚类。

    图片输入常为「图片 + 文字」混合（如 `![img](https://...png) 这是什么产品`）。
    直接把整条按图片剔除会连带丢掉文字诉求；改为去图留文——保留文字参与聚类分析，
    纯图片消息（去图后为空）自然不计入。同时避免各异的图片 URL 前缀伪聚成假 Top。"""
    return _IMG_MD_RE.sub("", str(q or "")).strip()


def _has_references(rec: dict[str, Any]) -> bool:
    """判断是否命中知识库：reply_method=4 为知识库问答（样本归纳级，见 api-reference.md）。
    ⚠ 仅【标准模式 app_mode=1】成立——其他模式知识库检索不走 reply_method=4：
      Claw/Agentic RAG 走 Agent 工具调用（reply_method 恒为 10）、单工作流走工作流回复(6)等，
      对这些模式本函数会系统性漏判，知识库命中须看 trace 的 tool_call/knowledge_retrieval 节点。
    注意：引用标记 [1](@ref) 只出现在 Trace 的 generate 节点 output 中，
    msg_record_list 的 answer 字段不含引用标记，故不能用文本匹配。"""
    return str(rec.get("reply_method")) == "4"


def is_fallback(rec: dict[str, Any]) -> bool:
    """检查回复是否命中兜底/拒答话术模式。"""
    text = str(rec.get("answer") or "")
    return any(p in text for p in FALLBACK_PATTERNS)


def die(code: int, msg: str) -> None:
    sys.stderr.write(f"ERROR: {msg}\n")
    sys.exit(code)


def info(msg: str) -> None:
    """过程性说明走 stderr，不污染 stdout 的业务输出。"""
    sys.stderr.write(f"· {msg}\n")


# ───────────────────────── 配置 / 白名单 / 凭据 ────────────────────────────


def load_mcp_config() -> dict[str, Any]:
    if not MCP_CONFIG_PATH.is_file():
        die(EXIT_CONFIG, f"mcp.json 不存在：{MCP_CONFIG_PATH}")
    try:
        cfg = json.loads(MCP_CONFIG_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        die(EXIT_CONFIG, f"mcp.json 解析失败：{exc}")
    if not isinstance(cfg, dict) or not cfg.get("url"):
        die(EXIT_CONFIG, "mcp.json 缺少 url 字段")
    return cfg


def ensure_url_scheme(host: str) -> str:
    if re.match(r"^[a-zA-Z][a-zA-Z0-9+.\-]*://", host):
        return host
    scheme = os.environ.get("ADP_PLUGIN_GW_SCHEME", "").strip() or "https"
    if host.startswith("//"):
        return f"{scheme}:{host}"
    return f"{scheme}://{host}"


def parse_url(cfg: dict[str, Any]) -> str:
    url = str(cfg.get("url") or "").strip()
    gw_host = os.environ.get("ADP_PLUGIN_GW_HOST", "").strip()
    if not gw_host:
        return url
    m = re.match(r"^[a-zA-Z][a-zA-Z0-9+.\-]*://([^/]+)(/.*)?$", url)
    if not m:
        return url
    return ensure_url_scheme(gw_host) + (m.group(2) or "")


def parse_allowed_prefixes(cfg: dict[str, Any]) -> list[str]:
    sec = cfg.get("security") or {}
    prefixes = list(sec.get("allowed_url_prefixes") or [])
    gw_host = os.environ.get("ADP_PLUGIN_GW_HOST", "").strip()
    if gw_host:  # 网关覆盖 host 与凭据同信任层级，自动放行
        prefixes.append(ensure_url_scheme(gw_host) + "/")
    if not prefixes:
        die(EXIT_CONFIG, "mcp.json 缺少 security.allowed_url_prefixes")
    return [str(p) for p in prefixes]


def parse_allowed_tools(cfg: dict[str, Any]) -> list[str]:
    tools = cfg.get("tools") or []
    if not tools:
        die(EXIT_CONFIG, "mcp.json 缺少 tools 白名单")
    return [str(t) for t in tools]


def resolve_api_key() -> str:
    delegate = os.environ.get("ADP_DELEGATE_API_KEY", "").strip()
    if delegate:
        return delegate
    self_serve = os.environ.get("ADP_API_KEY", "").strip()
    if self_serve:
        return self_serve
    die(EXIT_CONFIG,
        "未检测到 ADP_DELEGATE_API_KEY / ADP_API_KEY。"
        "托管环境下凭据由运行环境自动注入，请确认宿主已配置注入；"
        "若为本地/自建环境，请先 export ADP_API_KEY=<密钥>（从 ADP 控制台-密钥管理页面获取）后重试。")
    return ""


# ───────────────────────── MCP 传输层 ──────────────────────────────────────


def parse_mcp_body(body: str) -> Any:
    """application/json 直返 或 text/event-stream 取最后一帧 data: 行。"""
    try:
        return json.loads(body)
    except json.JSONDecodeError:
        pass
    last_data: list[str] = []
    for chunk in body.split("\n\n"):
        data_lines = [ln[5:].lstrip() for ln in chunk.splitlines() if ln.startswith("data:")]
        if data_lines:
            last_data = data_lines
    if not last_data:
        raise json.JSONDecodeError("body is neither JSON nor SSE JSON", body, 0)
    return json.loads("\n".join(last_data).strip())


class MCPClient:
    def __init__(self, url: str, api_key: str, timeout: int = DEFAULT_TIMEOUT):
        self.url, self.api_key, self.timeout = url, api_key, timeout
        self.session_id = ""
        self.next_id = 1

    def _headers(self) -> dict[str, str]:
        h = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            "Authorization": f"Bearer {self.api_key}",
            "User-Agent": USER_AGENT,
        }
        if self.session_id:
            h["Mcp-Session-Id"] = self.session_id
        return h

    def _post(self, payload: dict[str, Any]):
        try:
            resp = requests.post(
                self.url,
                data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                headers=self._headers(),
                timeout=self.timeout,
                verify=False,
            )
        except requests.RequestException as exc:
            die(EXIT_NETWORK_OR_SERVER, f"MCP 请求失败：{exc}")
            return None, 0, ""
        sid = resp.headers.get("Mcp-Session-Id")
        if sid:
            self.session_id = sid
        return resp, resp.status_code, resp.text or ""

    def request(self, method: str, params: dict[str, Any] | None = None) -> Any:
        payload = {"jsonrpc": "2.0", "id": self.next_id, "method": method, "params": params or {}}
        self.next_id += 1
        _, status, body = self._post(payload)
        if status in (401, 403):
            die(EXIT_AUTH, f"鉴权失败（HTTP {status}）")
        if status >= 400:
            die(EXIT_NETWORK_OR_SERVER, f"MCP {method} 失败（HTTP {status}）：{(body or '(empty)')[:400]}")
        try:
            return parse_mcp_body(body)
        except json.JSONDecodeError as exc:
            die(EXIT_NETWORK_OR_SERVER, f"MCP {method} 响应解析失败：{exc}")
            return None

    def notify(self, method: str, params: dict[str, Any] | None = None) -> None:
        payload = {"jsonrpc": "2.0", "method": method, "params": params or {}}
        _, status, body = self._post(payload)
        if status in (401, 403):
            die(EXIT_AUTH, f"鉴权失败（HTTP {status}）")
        if status >= 400:
            die(EXIT_NETWORK_OR_SERVER, f"MCP {method} 通知失败（HTTP {status}）：{(body or '(empty)')[:400]}")

    def initialize(self) -> Any:
        return self.request(
            "initialize",
            {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": "adp-chat-analysis-skill", "version": "2.0"},
            },
        )

    def call_tool(self, name: str, arguments: dict[str, Any]) -> Any:
        return self.request("tools/call", {"name": name, "arguments": arguments})


def unwrap_tool_payload(response: Any) -> Any:
    """tools/call 响应剥成纯业务 JSON。"""
    if not isinstance(response, dict):
        return response
    if "error" in response and isinstance(response["error"], dict):
        die(EXIT_NETWORK_OR_SERVER, f"tool 返回 JSON-RPC error：{json.dumps(response['error'], ensure_ascii=False)[:400]}")
    result = response.get("result")
    if not isinstance(result, dict):
        return response
    if result.get("isError"):
        parts = [str(i.get("text") or "") for i in result.get("content") or [] if isinstance(i, dict) and i.get("type") == "text"]
        die(EXIT_NETWORK_OR_SERVER, f"tool 返回错误：{(' '.join(parts).strip())[:400] or '(无文本)'}")
    for item in result.get("content") or []:
        if not isinstance(item, dict) or item.get("type") != "text":
            continue
        text = item.get("text") or ""
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return text
    return result


def call_tool(tool: str, arguments: dict[str, Any]) -> Any:
    """一次成型：配置校验 → 白名单 → 鉴权 → 握手 → 调用 → 剥壳。"""
    cfg = load_mcp_config()
    url = parse_url(cfg)
    check_url = parse_allowed_prefixes(cfg)
    if not any(url.startswith(p) for p in check_url):
        die(EXIT_CONFIG, f"URL 不在白名单内，拒绝发送鉴权头：{url}（白名单：{check_url}）")
    allowed = parse_allowed_tools(cfg)
    if tool not in allowed:
        die(EXIT_BAD_ARGS, f"tool `{tool}` 不在本 skill 白名单内。合法 tool：{allowed}")
    client = MCPClient(url=url, api_key=resolve_api_key())
    client.initialize()
    try:
        client.notify("notifications/initialized", {})
    except SystemExit:
        raise
    except Exception as exc:  # pragma: no cover
        sys.stderr.write(f"WARN: notifications/initialized 失败：{exc}\n")
    return unwrap_tool_payload(client.call_tool(tool, arguments))


# ───────────────────────── 业务辅助 ────────────────────────────────────────


def resolve_run_mode() -> str:
    """鉴权模式（整会话判一次，互斥不回退）：检测到 ADP_DELEGATE_API_KEY 即 delegate，
    否则 self-serve。与 resolve_api_key 同源，保证 api_key 与 app_id/space_id 取自同一模式。"""
    return "delegate" if os.environ.get("ADP_DELEGATE_API_KEY", "").strip() else "self-serve"


def resolve_space_id(args: argparse.Namespace) -> str:
    """space_id 按鉴权模式绑定来源（仅 describe_app_summary_list 按应用名找 app_id 时用）：
      - delegate 模式：ADP_DELEGATE_SPACE_ID
      - self-serve 模式：ADP_SPACE_ID
    显式 --space-id 优先；env 也缺失时**不兜造 default_space**，而是报错让 LLM 向用户
    确认目标空间（与 resolve_app_id 缺失即停的风格一致，避免默默查错空间）。"""
    explicit = (getattr(args, "space_id", "") or "").strip()
    if explicit:
        return explicit
    mode = resolve_run_mode()
    env_name = "ADP_DELEGATE_SPACE_ID" if mode == "delegate" else "ADP_SPACE_ID"
    sid = os.environ.get(env_name, "").strip()
    if sid:
        return sid
    die(EXIT_BAD_ARGS,
        f"缺少 space_id：当前 {mode} 模式应注入 {env_name}（未检测到）。"
        f"请传 --space-id，或让用户在消息中给出目标空间；不要默认某个空间。")
    return ""


def resolve_app_id(args: argparse.Namespace) -> str:
    """app_id 按鉴权模式绑定来源（对齐 adp-app-builder load_config，防跨企业错配）：
      - delegate 模式：只认 ADP_DELEGATE_APP_ID
      - self-serve 模式：只认 ADP_APP_ID
    不跨模式回退——delegate 凭证配 self-serve 应用（或反之）平台必报「企业与应用归属不一致」。
    显式 --app-id 允许（分析场景查任意应用），但与当前模式的 env app_id 不符时报错拒绝，
    避免用错模式凭证去查另一企业的应用。"""
    mode = resolve_run_mode()
    env_name = "ADP_DELEGATE_APP_ID" if mode == "delegate" else "ADP_APP_ID"
    env_app_id = os.environ.get(env_name, "").strip()

    app_id = (getattr(args, "app_id", "") or "").strip()
    if app_id:
        # 显式传入：若当前模式已注入 env app_id 且与之不符 → 大概率跨企业错配，拒绝
        if env_app_id and app_id != env_app_id:
            die(EXIT_BAD_ARGS,
                f"--app-id={app_id} 与当前鉴权模式（{mode}）的应用 {env_name}={env_app_id} 不一致。"
                f"delegate 凭证只能查 {env_name} 对应企业的应用，跨企业会报「企业与应用归属不一致」。"
                f"如需查该应用，请确认它归属当前凭证的企业，或切换到匹配的鉴权模式。")
        return app_id

    if env_app_id:
        info(f"--app-id 未提供，回退环境变量 {env_name}（{mode} 模式）")
        return env_app_id
    die(EXIT_BAD_ARGS,
        f"缺少 app_id：当前 {mode} 模式应注入 {env_name}（未检测到）。"
        f"请传 --app-id，或让用户在消息中给出 appid。")
    return ""


def trunc(s: Any, n: int) -> str:
    s = str(s or "").replace("\n", " ").strip()
    return s if len(s) <= n else s[: n - 1] + "…"


def fmt_ts(sec: Any) -> str:
    try:
        return time.strftime("%m-%d %H:%M", time.localtime(int(sec)))
    except (TypeError, ValueError):
        return "?"


def sec_range(days: int) -> tuple[int, int]:
    now = int(time.time())
    return now - days * 86400, now


def parse_time_arg(s: str) -> Optional[int]:
    """解析时间参数：Unix 秒时间戳、YYYY-MM-DD、YYYY-MM-DD HH:MM 三种形态。失败返回 None。"""
    s = (s or "").strip()
    if not s:
        return None
    if s.isdigit():  # 已是秒级时间戳
        return int(s)
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return int(time.mktime(time.strptime(s, fmt)))
        except ValueError:
            continue
    return None


def is_test_traffic(rec: dict[str, Any]) -> bool:
    # 仅调试页面(channel_type=3) 与 应用评测(channel_type=6) 为调试测评消息，其余渠道均为正式
    ch = str((rec.get("source") or {}).get("channel_type") or "")
    return ch in {"3", "6"}


def fetch_records(app_id: str, days: Optional[int], page_size: int, filters: dict[str, Any] | None = None,
                  start: Optional[int] = None, end: Optional[int] = None) -> tuple[list[dict[str, Any]], int]:
    """自动翻页拉满一个时间窗口的全部记录。start/end 显式给定则忽略 days。"""
    if start is not None and end is not None:
        s, e = start, end
    else:
        s, e = sec_range(days or 30)
    collected: list[dict[str, Any]] = []
    total = 0
    page = 0
    while page < MAX_PAGES:
        args = {"app_id": app_id, "start_time": s, "end_time": e,
                "page_number": page, "page_size": page_size, "sort_order": "desc"}
        if filters:
            args.update(filters)
        d = call_tool("describe_msg_record_list", args)
        if not isinstance(d, dict):
            die(EXIT_NETWORK_OR_SERVER, f"records 响应形态异常：{trunc(d, 200)}")
        total = int(d.get("total_count") or 0)
        batch = d.get("msg_record_list") or []
        collected.extend(batch)
        if not batch or (total and len(collected) >= total):
            break
        page += 1
    if total and len(collected) < total:
        info(f"⚠ 翻页保险丝触发（{MAX_PAGES} 页）：已取 {len(collected)}/{total} 条，结果不完整。"
             f"用 --start/--end 拆分区间分批拉取，或调大 --page-size 后重试。")
    return collected, total


def fetch_windowed(app_id: str, days: Optional[int], page_size: int, filters: dict[str, Any] | None = None,
                   start: Optional[int] = None, end: Optional[int] = None):
    """显式区间直接单次拉取；否则 --days 单窗口 / 30→90→180→365 自动试探。
    返回 (records, total, days_used, expanded)。"""
    if start is not None and end is not None:
        records, total = fetch_records(app_id, None, page_size, filters, start=start, end=end)
        return records, total, 0, False
    windows = [days] if days else list(AUTO_WINDOWS)
    for i, w in enumerate(windows):
        records, total = fetch_records(app_id, w, page_size, filters)
        if total > 0 or i == len(windows) - 1:
            return records, total, w, i > 0
        info(f"近 {w} 天无记录，自动扩大窗口…")
    return [], 0, windows[-1], False  # unreachable


def record_stats(records: list[dict[str, Any]]) -> dict[str, Any]:
    toks = [int(((r.get("result") or {}).get("total_token")) or 0) for r in records]
    lats = [int(((r.get("result") or {}).get("total_token_latency")) or 0) for r in records]
    fts = [int(((r.get("result") or {}).get("first_token_latency")) or 0) for r in records]
    ok = sum(1 for r in records if str((r.get("result") or {}).get("call_result")) == "1")
    canceled = sum(1 for r in records if str((r.get("result") or {}).get("call_result")) == "3")
    sessions = {str(r.get("session_id")) for r in records}
    users = {str((r.get("source") or {}).get("user_id")) for r in records}
    tests = sum(1 for r in records if is_test_traffic(r))

    # 加工指标（借鉴 adp-conversation-optimizer 的质量指标体系）
    fallbacks = sum(1 for r in records if is_fallback(r))
    refs = sum(1 for r in records if _has_references(r))
    # 高频问题聚类（归一化后 Counter）——先剥离 markdown 图片标记、保留文字；纯图片（剥离后为空）不计入
    from collections import Counter
    q_counter = Counter(_norm_question(t) for r in records
                        if (t := _strip_images(r.get("question"))))
    fallback_qs = Counter(_norm_question(t) for r in records
                          if is_fallback(r) and (t := _strip_images(r.get("question"))))

    n = max(len(records), 1)

    def avg(xs: list[int]) -> int:
        return sum(xs) // len(xs) if xs else 0

    return {
        "n": len(records), "ok": ok, "canceled": canceled,
        "sessions": len(sessions), "users": len(users), "tests": tests,
        # 成功率排除用户主动取消（call_result=3）——取消是用户行为，非应用失败，不计入分母
        "success_denominator": max(len(records) - canceled, 0),
        "success_rate": round(ok / max(len(records) - canceled, 1), 4),
        "tok_sum": sum(toks), "tok_avg": avg(toks), "tok_max": max(toks) if toks else 0,
        "lat_avg": avg(lats), "lat_max": max(lats) if lats else 0, "ft_avg": avg(fts),
        # 加工指标
        "fallback_count": fallbacks,
        "fallback_rate": round(fallbacks / n, 4),
        "reference_hit_count": refs,
        "reference_hit_rate": round(refs / n, 4),
        "top_questions": q_counter.most_common(10),
        "top_fallback_questions": fallback_qs.most_common(10),
    }


def print_record_digest(rec: dict[str, Any], with_answer: bool) -> None:
    res = rec.get("result") or {}
    rid = rec.get("record_id") or "?"
    ts = fmt_ts(rec.get("create_time"))
    intent_val = rec.get("intent") or "-"
    intent_cat = rec.get("intent_category") or "-"
    intent = f"{intent_val}/{intent_cat}" if intent_val != "-" or intent_cat != "-" else "-"
    method = f"m{rec.get('reply_method')}"
    tok = f"{res.get('total_token') or 0}tok({res.get('input_token') or 0}/{res.get('output_token') or 0})"
    lat = f"{res.get('total_token_latency') or 0}ms"
    # record_id 不截断——它是 trace 下钻的钥匙，截断会导致定位失败
    line = f"[{rid}] {ts} | {intent} | {method} | {tok} | {lat} | Q: {trunc(rec.get('question'), 40)}"
    if with_answer:
        line += f" | A: {trunc(rec.get('answer'), 60)}"
    print(line)


# ───────────────────────── 子命令 ─────────────────────────────────────────


_APP_MODE_NAMES = {1: "标准", 2: "Multi-Agent", 3: "单工作流", 4: "Claw"}
_APP_STATUS_NAMES = {0: "未指定", 1: "未上线", 2: "运行中", 3: "停用"}


def cmd_apps(args: argparse.Namespace) -> int:
    """按应用名找 app_id（或列出空间下应用）。用户只给了应用名、没给 app_id 时先用它定位。"""
    space_id = resolve_space_id(args)
    payload: dict[str, Any] = {
        "space_id": space_id,
        "page_number": args.page_number,
        "page_size": args.page_size,
    }
    if args.query:
        payload["query"] = args.query  # 按应用名称模糊匹配
    d = call_tool("describe_app_summary_list", payload)
    items = d.get("app_list") or d.get("AppList") or []
    total = d.get("total_count") or d.get("TotalCount") or len(items)
    hint = f"（名称含「{args.query}」）" if args.query else ""
    print(f"空间 {space_id} 下应用{hint}: {total} 个")
    if not items:
        print("未匹配到应用；换个名称关键词，或让用户直接提供 app_id。")
        return EXIT_OK
    for i, it in enumerate(items, 1):
        if not isinstance(it, dict):
            continue
        aid = it.get("app_id") or it.get("AppId") or "-"
        name = it.get("name") or it.get("Name") or "-"
        mode = it.get("app_mode") or it.get("AppMode")
        status = it.get("status") or it.get("Status")
        mode_s = _APP_MODE_NAMES.get(mode, mode)
        status_s = _APP_STATUS_NAMES.get(status, status)
        print(f"[{i}] {name} | app_id: {aid} | 模式: {mode_s} | 状态: {status_s}")
    if len([x for x in items if isinstance(x, dict)]) > 1:
        print("\n命中多个，请与用户确认目标应用后，用其 app_id 继续分析（records/trace/... --app-id <APP_ID>）。")
    return EXIT_OK


def cmd_categories(args: argparse.Namespace) -> int:
    app_id = resolve_app_id(args)
    d = call_tool("describe_msg_record_category_list", {"app_id": app_id})
    root = (d.get("category_list") or [{}])[0]
    total = root.get("total_count")
    print(f"应用 {app_id} 消息记录分类树:")
    for child in root.get("children") or []:
        print(f"  - [{child.get('category_id')}] {child.get('name')}: {child.get('total_count')}")
    if total == 0:
        print("提示: 该应用尚无任何消息记录。")
    return EXIT_OK


def cmd_unsatisfied(args: argparse.Namespace) -> int:
    app_id = resolve_app_id(args)
    d = call_tool("describe_unsatisfied_reply_list", {"app_id": app_id, "page_number": 0, "page_size": args.page_size})
    items = d.get("unsatisfied_reply_list") or []
    print(f"不满意回复: {d.get('total_count')} 条")
    if not items:
        print("无不满意反馈，报告相应章节注明即可。")
        return EXIT_OK
    for i, it in enumerate(items, 1):
        reasons = "、".join(it.get("reason_list") or [])
        print(f"[{i}] {it.get('record_id')} | 原因: {reasons} | Q: {trunc(it.get('question'), 40)}")
        print(f"    A: {trunc(it.get('answer'), 80)}")
    print("\n下钻执行链路：")
    print(f"  python3 scripts/adp_chat.py trace --app-id {app_id} --record-id {items[0].get('record_id')}")
    return EXIT_OK


def cmd_records(args: argparse.Namespace) -> int:
    if args.group_by_session and not args.json:
        die(EXIT_BAD_ARGS, "--group-by-session 仅在 --json 下生效，请同时加 --json。")
    app_id = resolve_app_id(args)
    filters: dict[str, Any] = {}
    if args.query:
        filters["query"] = args.query
    if args.query_type:
        filters["query_type"] = args.query_type
    if args.call_result is not None:
        filters["call_result"] = args.call_result
    if args.category_id:
        filters["category_id"] = args.category_id
    if args.channel_type is not None:
        filters["channel_type"] = args.channel_type
    if args.intent:
        filters["intent"] = args.intent
    if args.reply_method is not None:
        filters["reply_method"] = args.reply_method
    if args.feedback_type is not None:
        filters["feedback_type"] = args.feedback_type
    if args.fail_reason:
        filters["fail_reason"] = args.fail_reason

    # 时间参数三形态：--start/--end 显式区间 > --days 相对窗口 > 自动试探。
    start = end = None
    if args.start or args.end:
        if not (args.start and args.end):
            die(EXIT_BAD_ARGS, "--start 与 --end 必须成对使用（或都不传，走 --days/自动窗口）。")
        start = parse_time_arg(args.start)
        end = parse_time_arg(args.end)
        if start is None:
            die(EXIT_BAD_ARGS, f"--start 无法解析：{args.start}（支持 YYYY-MM-DD / YYYY-MM-DD HH:MM / Unix 秒）")
        if end is None:
            die(EXIT_BAD_ARGS, f"--end 无法解析：{args.end}（支持 YYYY-MM-DD / YYYY-MM-DD HH:MM / Unix 秒）")
        if start >= end:
            die(EXIT_BAD_ARGS, "--start 必须早于 --end。")

    records, total, days_used, expanded = fetch_windowed(
        app_id, args.days, args.page_size, filters or None, start=start, end=end)

    if args.json:
        if args.group_by_session:
            # 按 session_id 分组、组内按 create_time 升序，便于结合上下文看完整对话链。
            # 组的排列顺序按各组最早一条的 create_time 升序，稳定可读。
            def _ct(r: dict[str, Any]) -> int:
                try:
                    return int(r.get("create_time") or 0)
                except (TypeError, ValueError):
                    return 0
            grouped: dict[str, list[dict[str, Any]]] = {}
            for r in records:
                sid = str(r.get("session_id") or "_no_session")
                grouped.setdefault(sid, []).append(r)
            for sid in grouped:
                grouped[sid].sort(key=_ct)
            ordered = dict(sorted(grouped.items(), key=lambda kv: _ct(kv[1][0])))
            print(json.dumps({"app_id": app_id, "window_days": days_used, "total_count": total,
                              "session_count": len(ordered), "sessions": ordered},
                             ensure_ascii=False, indent=2))
        else:
            print(json.dumps({"app_id": app_id, "window_days": days_used, "total_count": total,
                              "records": records}, ensure_ascii=False, indent=2))
        return EXIT_OK

    if start is not None:
        print(f"窗口: {fmt_ts(start)} ~ {fmt_ts(end)}（显式区间）")
    else:
        s0, e0 = sec_range(days_used)
        print(f"窗口: {fmt_ts(s0)} ~ {fmt_ts(e0)}（近 {days_used} 天{'，自动扩展' if expanded else ''}）")
    if total == 0:
        print("该窗口内无记录。若分类树 total_count>0，可用 --days 显式指定更大范围。")
        return EXIT_OK

    s = record_stats(records)
    print(f"消息 {s['n']} 条（正式 {s['n'] - s['tests']} + 调试测评 {s['tests']}）| 会话 {s['sessions']} 个 | 用户 {s['users']} 个")
    print(f"成功率 {s['ok']}/{s['success_denominator']}={s['success_rate']:.1%}"
          f"（已剔除用户主动取消 {s['canceled']} 条）"
          f" | Token 总 {s['tok_sum']} / 均 {s['tok_avg']} / 最大 {s['tok_max']}"
          f" | 延迟 均 {s['lat_avg']}ms / 最大 {s['lat_max']}ms / 首token均 {s['ft_avg']}ms")
    # 疑似拒答：只做关键词初筛，不输出"拒答率"（避免误当精确指标）——筛出的需逐一确认
    print(f"疑似拒答/兜底 {s['fallback_count']} 条（关键词初筛，需逐一判断，非精确拒答率）")
    # 知识库命中靠 reply_method=4 统计，仅标准模式(app_mode=1) 成立；非标准模式恒为 0。
    # 仅在确有命中(>0)时输出——既避免非标准模式的"不适用"噪音，也省去每次的免责长句。
    if s["reference_hit_count"] > 0:
        print(f"知识库命中(reply_method=4) {s['reference_hit_count']} 条（仅标准模式有效，其他模式看 trace）")
    if s["top_questions"]:
        print("高频问题 Top5:")
        for q, cnt in s["top_questions"][:5]:
            print(f"  ({cnt}x) {q}")
    if s["top_fallback_questions"]:
        print("高频疑似被拒/兜底问题 Top5（关键词初筛，需逐一确认）:")
        for q, cnt in s["top_fallback_questions"][:5]:
            print(f"  ({cnt}x) {q}")

    shown = records[: args.max_digest]
    print(f"\n记录摘要（--answers 可带回答摘要，--json 输出全量原始字段）:")
    for rec in shown:
        print_record_digest(rec, args.answers)
    if len(records) > len(shown):
        print(f"…另有 {len(records) - len(shown)} 条未展示，用 --max-digest 调整或 --json 导出")
    return EXIT_OK


def find_record(app_id: str, record_id: str) -> dict[str, Any]:
    """跨窗口扫描定位单条记录（trace 自动配对 conversation_id 用）。"""
    for w in AUTO_WINDOWS:
        info(f"在近 {w} 天窗口中定位 {trunc(record_id, 24)}…")
        page = 0
        while page < MAX_PAGES:
            start, end = sec_range(w)
            d = call_tool("describe_msg_record_list", {
                "app_id": app_id, "start_time": start, "end_time": end,
                "page_number": page, "page_size": 100, "sort_order": "desc"})
            batch = d.get("msg_record_list") or []
            for r in batch:
                if r.get("record_id") == record_id:
                    return r
            total = int(d.get("total_count") or 0)
            fetched = (page + 1) * 100
            if not batch or (total and fetched >= total):
                break
            page += 1
    die(EXIT_BAD_ARGS, f"未找到 record_id={record_id} 的消息记录（已在近 365 天内扫描）。"
        f"确认 ID 来自同一 app_id；若该应用记录超 5000 条，可能触发翻页保险丝漏扫，"
        f"可先用 records --json 确认该记录的时间，再用 --days 覆盖对应窗口。")
    return {}


def cmd_trace(args: argparse.Namespace) -> int:
    app_id = resolve_app_id(args)
    record_id = args.record_id
    conversation_id = args.conversation_id
    if not conversation_id:
        info("未传 --conversation-id，自动定位该记录所属会话…")
        rec = find_record(app_id, record_id)
        conversation_id = str(rec.get("session_id") or "")
        if not conversation_id:
            die(EXIT_BAD_ARGS, "定位到的记录缺少 session_id，请显式传 --conversation-id。")
        info(f"已定位 conversation_id = {conversation_id}")

    d = call_tool("describe_record_trace_info", {
        "app_id": app_id, "conversation_id": conversation_id, "record_id": record_id,
        "request_id": args.request_id or f"trace_{trunc(record_id, 16)}"})

    if args.json:
        print(json.dumps(d, ensure_ascii=False, indent=2))
        return EXIT_OK

    t = d.get("trace_info") or {}
    print(f"record {record_id} | status {t.get('status')} | 总耗时 {t.get('elapsed')}ms | tokens {t.get('total_tokens')}")
    generates = 0
    confidence: Optional[float] = None
    for i, p in enumerate(t.get("procedures") or [], 1):
        ptype = p.get("type") or "?"
        name = p.get("name") or ""
        model = f" model={p.get('model_name')}" if p.get("model_name") else ""
        print(f"  [{i}] {ptype} {name} | {p.get('status')} | {p.get('elapsed')}ms{model}")
        try:
            out = json.loads(p.get("output") or "") if isinstance(p.get("output"), str) else (p.get("output") or {})
            if ptype == "knowledge_retrieval" and isinstance(out, dict):
                k = (out.get("Knowledge") or [{}])[0]
                confidence = k.get("confidence")
                if k.get("doc_name"):
                    print(f"      命中文档: {k.get('doc_name')} 置信度 {confidence}")
            if ptype == "thought" and isinstance(out, dict):
                if out.get("Intent"):
                    print(f"      意图: {out.get('Intent')}")
                if out.get("tool_calls"):
                    tool_names = [tc.get("function", {}).get("name", "?") for tc in out["tool_calls"] if isinstance(tc, dict)]
                    if tool_names:
                        print(f"      调用工具: {', '.join(tool_names)}")
            if ptype == "tool_call" and isinstance(out, dict):
                result = out.get("result") or {}
                if isinstance(result, dict) and result.get("output"):
                    print(f"      工具返回: {trunc(result.get('output'), 100)}")
            if ptype == "generate":
                generates += 1
        except (json.JSONDecodeError, TypeError, IndexError):
            pass
    if generates > 1:
        print(f"⚠ 信号: 出现 {generates} 个 generate 节点 = 生成模型重试")
    if confidence is not None:
        print(f"ℹ 检索置信度 {confidence}（参考值，无统一标准线，不据此单独判定覆盖不足）；"
              f"知识库是否召回准确以下方切片内容是否包含答案为准")

    # 召回排查摘要（借鉴 adp-conversation-optimizer S5 归因思路）
    # 从 Trace 的 knowledge_retrieval 节点提取命中信息；深度切片分析需跨 skill 下钻
    retrieval_info = None
    for p in t.get("procedures") or []:
        if p.get("type") == "knowledge_retrieval":
            try:
                out = json.loads(p.get("output") or "{}") if isinstance(p.get("output"), str) else (p.get("output") or {})
                k = (out.get("Knowledge") or [{}])[0]
                if k:
                    retrieval_info = k
            except (json.JSONDecodeError, TypeError, IndexError):
                pass
            break
    if retrieval_info:
        content = str(retrieval_info.get("content") or "")
        doc_biz_id = retrieval_info.get("doc_biz_id", "")
        conf = retrieval_info.get("confidence")
        print(f"\n召回排查:")
        print(f"  命中文档: {retrieval_info.get('doc_name')} | 置信度: {conf}")
        print(f"  切片长度: {len(content)} 字符 | 前 100 字: {trunc(content, 100)}")
        if conf is not None:
            print(f"  置信度: {conf}（参考值，无统一阈值，不单独作判定依据）")
        print(f"  → 判断召回是否准确以切片内容为准：")
        print(f"    · 切片已包含答案但回复仍不准 → 查提示词是否要求'依据检索作答'")
        print(f"    · 切片不含答案 / 与问题无关 → 补充或重写知识库文档、检查切分粒度")
        # 跨 skill 深度下钻建议（查看完整切片、下载原文对比）
        if doc_biz_id:
            print(f"  深度切片分析: 用 tencentcloud-adp-kb-management skill 的 describe_doc / get_doc_preview")
            print(f"    对 doc_biz_id={doc_biz_id} 查看切片规则、下载原文、对比命中片段是否合理")
    else:
        # 检查 user_input 的 output 是否引用了知识库内容（Agentic RAG 信号）
        user_out = ""
        for p in t.get("procedures") or []:
            if p.get("type") == "user_input":
                user_out = str(p.get("output") or "")
                break
        has_kb_ref = any(kw in user_out for kw in ("知识库", "检索结果", "根据", "References"))
        if has_kb_ref:
            print(f"\n召回排查: 无 knowledge_retrieval 独立节点，但 user_input output 引用了知识库内容")
            print(f"  → Agentic RAG 模式：知识库检索折叠在 user_input 内，无独立检索节点和置信度")
            print(f"  → 无法获取 confidence，深度切片分析需衔接 kb-management 用 doc_biz_id 查看原文")
        else:
            # 检查是否有 tool_call 节点（Function Calling 模式）
            has_tool_call = any(p.get("type") == "tool_call" for p in t.get("procedures") or [])
            if has_tool_call:
                print(f"\n召回排查: 无 knowledge_retrieval 节点，但有 tool_call 节点（Function Calling 模式）")
                print(f"  → Agent 自主决定调用工具，非平台内置知识库检索")
                print(f"  → 检查 Agent 工具列表中挂载的工具及其触发逻辑")
            else:
                print(f"\n召回排查: 无 knowledge_retrieval 节点，output 也未引用知识库内容")
                print(f"  → 未走知识库，纯模型直答；若业务需要知识库命中，检查 Agent 工具列表")
    if generates == 1:
        print("信号: 无生成重试（作为对照基线时使用）")
    return EXIT_OK


def cmd_messages(args: argparse.Namespace) -> int:
    """查会话上下文消息——以某条 record 为锚点，向前后查历史对话，看上下文是否影响输出。"""
    app_id = resolve_app_id(args)
    conv_id = args.conversation_id
    record_id = args.record_id

    # conversation_id 缺省时自动定位（复用 trace 的定位逻辑）
    if not conv_id:
        info("未传 --conversation-id，自动定位该记录所属会话…")
        rec = find_record(app_id, record_id)
        conv_id = str(rec.get("session_id") or "")
        if not conv_id:
            die(EXIT_BAD_ARGS, "定位到的记录缺少 session_id。")
        info(f"已定位 conversation_id = {conv_id}")

    # 会话类型推断：默认 5（API接入），查不到再试 2（评测）
    type_val = args.type
    if type_val is None:
        for candidate in (5, 2, 1, 10):
            payload = {
                "app_id": app_id, "conversation_id": conv_id,
                "type": candidate, "limit": 1,
            }
            if record_id:
                payload["record_id"] = record_id
                payload["record_query_direction"] = 3
            else:
                payload["record_query_direction"] = 0
            try:
                test = call_tool("describe_conversation_message_list", payload)
                if isinstance(test, dict) and (test.get("message_list") or test.get("MessageList")):
                    type_val = candidate
                    info(f"未传 --type，自动探测 type={type_val}")
                    break
            except SystemExit:
                continue
        if type_val is None:
            die(EXIT_BAD_ARGS, "无法探测会话类型，请显式传 --type（1=访客 2=评测 5=API 10=工作流）")

    direction = args.direction  # None=自动, 0=默认向前, 1=向前, 2=向后, 3=双向
    limit = args.limit

    # 方向默认：有锚点→双向(3)查上下文；无锚点→向前(0)拉最新
    direction_val = direction if direction is not None else (3 if record_id else 0)

    payload = {
        "app_id": app_id,
        "conversation_id": conv_id,
        "type": type_val,
        "limit": limit,
    }
    if record_id:
        payload["record_id"] = record_id
        payload["record_query_direction"] = direction_val
    else:
        payload["record_query_direction"] = direction_val if direction is not None else 0

    d = call_tool("describe_conversation_message_list", payload)

    if args.json:
        print(json.dumps(d, ensure_ascii=False, indent=2))
        return EXIT_OK

    msgs = d.get("message_list") or d.get("MessageList") or []
    print(f"会话 {conv_id} | 消息 {len(msgs)} 条 | type={type_val}")
    if d.get("has_more_before") or d.get("HasMoreBefore"):
        print("  更早消息方向: 还有更多")
    if d.get("has_more_after") or d.get("HasMoreAfter"):
        print("  更新消息方向: 还有更多")

    for i, m in enumerate(msgs, 1):
        role = m.get("role") or m.get("Role") or "?"
        status = m.get("status") or m.get("Status") or ""
        record_id_m = m.get("record_id") or m.get("RecordId") or ""
        # 提取文本内容
        contents = m.get("content_list") or m.get("ContentList") or []
        texts = []
        for c in contents:
            t = c.get("text") or c.get("Text") or ""
            if t:
                texts.append(t)
        text = " ".join(texts)
        marker = " ◀锚点" if record_id_m == record_id and record_id else ""
        print(f"  [{i}] {role}{marker} | {status} | {trunc(record_id_m, 20)} | {trunc(text, 80)}")

    return EXIT_OK


def cmd_call(args: argparse.Namespace) -> int:
    tool = args.tool_name
    payload: dict[str, Any] = {}
    if args.args_json or args.file:
        raw = args.args_json
        if args.file:
            raw = sys.stdin.read() if args.file == "-" else Path(args.file).read_text(encoding="utf-8")
        try:
            payload = json.loads(raw or "{}")
        except json.JSONDecodeError as exc:
            die(EXIT_BAD_ARGS, f"args_json 不是合法 JSON：{exc}")
        if not isinstance(payload, dict):
            die(EXIT_BAD_ARGS, "args_json 必须是 JSON 对象")
    out = call_tool(tool, payload)
    if isinstance(out, (dict, list)):
        print(json.dumps(out, ensure_ascii=False, indent=2))
    else:
        print(out)
    return EXIT_OK


def cmd_list_tools(_args: argparse.Namespace) -> int:
    for n in parse_allowed_tools(load_mcp_config()):
        print(n)
    return EXIT_OK


# ───────────────────────── 入口 ───────────────────────────────────────────


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="adp_chat.py", description="ADP 应用对话记录分析（只读，统一脚本通道）")
    sub = p.add_subparsers(dest="command", required=True)

    def add_app(sp):
        sp.add_argument("--app-id", default=None, help="应用 ID；缺省按鉴权模式回退（delegate→ADP_DELEGATE_APP_ID，self-serve→ADP_APP_ID）")

    sp = sub.add_parser("apps", help="按应用名找 app_id / 列出空间下应用")
    sp.add_argument("--query", default=None, help="按应用名称模糊匹配；缺省列出空间下应用")
    sp.add_argument("--space-id", default=None, help="空间 ID；缺省按鉴权模式取 env（ADP_[DELEGATE_]SPACE_ID），env 也缺失则报错请用户提供，不默认空间")
    sp.add_argument("--page-number", type=int, default=0)
    sp.add_argument("--page-size", type=int, default=20)
    sp.set_defaults(func=cmd_apps)

    sp = sub.add_parser("categories", help="消息记录分类树")
    add_app(sp); sp.set_defaults(func=cmd_categories)

    sp = sub.add_parser("unsatisfied", help="不满意回复列表")
    add_app(sp)
    sp.add_argument("--page-size", type=int, default=100)
    sp.set_defaults(func=cmd_unsatisfied)

    sp = sub.add_parser("records", help="消息记录列表（自动窗口+自动翻页+统计摘要）")
    add_app(sp)
    sp.add_argument("--days", type=int, default=None, help="相对窗口天数（now-N 天 ~ now）；缺省自动 30→90→180→365 试探")
    sp.add_argument("--start", default=None, help="显式区间起点（YYYY-MM-DD / YYYY-MM-DD HH:MM / Unix 秒），须与 --end 成对")
    sp.add_argument("--end", default=None, help="显式区间终点，同上；给定后忽略 --days 与自动窗口")
    sp.add_argument("--page-size", type=int, default=100)
    sp.add_argument("--query", default=None, help="检索文本（对问题/答案等做模糊匹配）")
    sp.add_argument("--query-type", default=None, help="检索类型：SessionId / Question / Answer / Intent / User")
    sp.add_argument("--call-result", type=int, default=None, help="0全部/1成功/2失败/3用户取消")
    sp.add_argument("--category-id", default=None, help="分类过滤")
    sp.add_argument("--channel-type", type=int, default=None, help="渠道过滤，0=全部（如 7=调试API）")
    sp.add_argument("--intent", default=None, help="意图过滤（如 聊天 / 其他问题 / 逻辑推理）")
    sp.add_argument("--reply-method", type=int, default=None, help="回复类型过滤（4=知识润色 / 10=大模型直接）")
    sp.add_argument("--feedback-type", type=int, default=None, help="反馈过滤，-1=全部/0=未评价/1=点赞/2=点踩")
    sp.add_argument("--fail-reason", default=None, help="失败原因模糊匹配")
    sp.add_argument("--answers", action="store_true", help="摘要行附带回答前 60 字")
    sp.add_argument("--max-digest", type=int, default=200, help="最多展示的摘要行数（默认 200）")
    sp.add_argument("--json", action="store_true", help="输出全量原始 JSON（含 answer 全文）")
    sp.add_argument("--group-by-session", action="store_true",
                    help="仅 --json 生效：按 session_id 分组、组内按 create_time 升序，便于结合上下文看完整对话链")
    sp.set_defaults(func=cmd_records)

    sp = sub.add_parser("trace", help="单条记录执行链路")
    add_app(sp)
    sp.add_argument("--record-id", required=True, help="消息记录 record_id")
    sp.add_argument("--conversation-id", default=None, help="会话 ID；缺省自动定位（推荐留空）")
    sp.add_argument("--request-id", default=None, help="自定义请求关联标识（可选）")
    sp.add_argument("--json", action="store_true", help="输出全量原始 JSON")
    sp.set_defaults(func=cmd_trace)

    sp = sub.add_parser("messages", help="会话上下文消息（查前后文是否影响输出）")
    add_app(sp)
    sp.add_argument("--conversation-id", default=None, help="会话 ID；缺省自动定位")
    sp.add_argument("--record-id", default=None, help="锚点记录 ID，围绕它查前后文")
    sp.add_argument("--type", type=int, default=None, help="会话类型：1=访客体验 2=评测 5=API接入 10=工作流调试；缺省自动推断")
    sp.add_argument("--direction", type=int, default=None, help="查询方向：0=默认向前 1=向前(更早) 2=向后(更新) 3=双向（默认）")
    sp.add_argument("--limit", type=int, default=10, help="返回消息数，最大 50（默认 10）")
    sp.add_argument("--json", action="store_true", help="输出全量原始 JSON")
    sp.set_defaults(func=cmd_messages)

    sp = sub.add_parser("call", help="白名单内工具裸调用（兜底）")
    sp.add_argument("tool_name")
    sp.add_argument("args_json", nargs="?", default=None)
    sp.add_argument("-f", dest="file", default=None, help="从文件/stdin 读入参 JSON")
    sp.set_defaults(func=cmd_call)

    sp = sub.add_parser("list-tools", help="打印工具白名单")
    sp.set_defaults(func=cmd_list_tools)

    ns = p.parse_args(argv)
    return ns.func(ns)


if __name__ == "__main__":
    sys.exit(main())
