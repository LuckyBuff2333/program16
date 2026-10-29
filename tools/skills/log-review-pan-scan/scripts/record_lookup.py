#!/usr/bin/env python3
"""record_lookup.py — traceId 反查与会话取证包导出

通过 traceId（或 record_id / session_id）反查所属记录与会话，输出记录摘要；
--export 可导出复核取证包：record.json（结论侧）+ session_messages.txt（过程侧）。

依赖：同目录 adp_chat.py（只读接口，随本技能包分发）。
凭据从环境变量读取（ADP_API_KEY / ADP_APP_ID），支持 --env-file 注入，不打印不落盘。

用法:
    python3 record_lookup.py <traceid> [--env-file <.env>] [--app-id <id>]
                             [--days 365] [--refresh] [--show-answer] [--json]
                             [--export <取证目录>]

退出码: 0=命中 1=未命中 2=配置缺失 3=平台/网络错误
"""
import argparse
import datetime
import json
import os
import re
import subprocess
import sys
import tempfile

DEFAULT_CHAT_SCRIPT = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "adp_chat.py")

CALL_RESULT_MAP = {0: "成功", 1: "成功", 2: "失败", 3: "用户取消"}

UUID_RE = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")
HEX32_RE = re.compile(r"^[0-9a-fA-F]{32}$")


def fail(code, msg):
    print("ERROR: " + msg, file=sys.stderr)
    sys.exit(code)


def load_env_file(path):
    """解析简单 KEY=VALUE .env 文件并注入 os.environ（不覆盖已有环境变量，不打印值）。"""
    if not os.path.isfile(path):
        fail(2, "--env-file 不存在: %s" % path)
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            k, v = k.strip(), v.strip().strip("'\"")
            if v and k not in os.environ:
                os.environ[k] = v


def resolve_app_id(args):
    if args.app_id:
        return args.app_id
    if os.environ.get("ADP_DELEGATE_API_KEY"):
        aid = os.environ.get("ADP_DELEGATE_APP_ID")
    else:
        aid = os.environ.get("ADP_APP_ID")
    if not aid:
        fail(2, "缺少 app_id：未传 --app-id，且环境无 ADP_APP_ID/ADP_DELEGATE_APP_ID。"
                "请传 --app-id 或 --env-file。")
    return aid


def fetch_records(app_id, days, chat_script, cache_path, refresh):
    """拉取全量记录 JSON（带本地缓存，默认 1 小时）。返回 (json_obj, from_cache)。"""
    if cache_path and os.path.isfile(cache_path) and not refresh:
        age = datetime.datetime.now().timestamp() - os.path.getmtime(cache_path)
        if age < 3600:
            with open(cache_path, encoding="utf-8") as f:
                try:
                    return json.load(f), True
                except ValueError:
                    pass  # 缓存损坏，重新拉取
    if not os.path.isfile(chat_script):
        fail(2, "找不到 adp_chat.py: %s（可用 --chat-script 指定）" % chat_script)
    cmd = [sys.executable, chat_script, "records", "--app-id", app_id,
           "--days", str(days), "--page-size", "50", "--json"]
    target = cache_path or os.path.join(
        tempfile.gettempdir(), "adp_records_%s.json" % app_id)
    with open(target, "w", encoding="utf-8") as out:
        proc = subprocess.run(cmd, stdout=out, stderr=subprocess.PIPE, text=True)
    if proc.returncode != 0:
        fail(3, "adp_chat.py records 拉取失败(%d): %s" % (proc.returncode, proc.stderr.strip()[:300]))
    with open(target, encoding="utf-8") as f:
        return json.load(f), False


def extract_records(export):
    if isinstance(export, list):
        return export
    for key in ("records", "data"):
        v = export.get(key)
        if isinstance(v, list):
            return v
    return []


def match_records(records, target):
    """按 ID 类型优先级匹配，返回 [(record, 匹配字段, 值), ...]。"""
    hits = []
    if target.startswith("rcd_"):
        for r in records:
            if r.get("record_id") == target:
                hits.append((r, "record_id", target))
    elif UUID_RE.match(target):
        for r in records:
            if r.get("session_id") == target:
                hits.append((r, "session_id", target))
    else:
        # 32 位十六进制 = 平台 trace_id；其余形态做全字段包含匹配兜底
        for r in records:
            if r.get("trace_id") == target:
                hits.append((r, "trace_id", target))
            elif r.get("session_id") == target:
                hits.append((r, "session_id", target))
            elif not HEX32_RE.match(target):
                for k, v in r.items():
                    if isinstance(v, str) and target in v:
                        hits.append((r, k, target))
                        break
    return hits


def fmt_time(ts):
    try:
        return datetime.datetime.fromtimestamp(int(ts)).strftime("%Y-%m-%d %H:%M:%S")
    except (ValueError, TypeError):
        return str(ts or "-")


def fmt_duration(ms):
    try:
        ms = int(ms)
    except (ValueError, TypeError):
        return "-"
    if ms >= 3600000:
        return "%.1fh" % (ms / 3600000)
    if ms >= 60000:
        return "%.1fmin" % (ms / 60000)
    return "%.1fs" % (ms / 1000)


def export_evidence(app_id, chat_script, record, out_dir):
    """导出复核取证包：record.json（结论侧）+ session_messages.txt（过程侧）。"""
    rid = record.get("record_id")
    sid = record.get("session_id")
    os.makedirs(out_dir, exist_ok=True)

    rec_path = os.path.join(out_dir, "record.json")
    with open(rec_path, "w", encoding="utf-8") as f:
        json.dump(record, f, ensure_ascii=False, indent=2)

    msg_path = os.path.join(out_dir, "session_messages.txt")
    # limit 是分页大小（平台上限 50），adp_chat.py 自动翻页拉全量
    cmd = [sys.executable, chat_script, "messages", "--app-id", app_id,
           "--conversation-id", sid, "--record-id", rid, "--limit", "50"]
    proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="ignore")
    with open(msg_path, "w", encoding="utf-8") as f:
        f.write(proc.stdout or "")
    n_msgs = len([l for l in (proc.stdout or "").splitlines() if re.match(r"\s*\[\d+\]", l)])
    return rec_path, msg_path, n_msgs, proc.returncode


def main():
    ap = argparse.ArgumentParser(description="traceId 反查与会话取证包导出")
    ap.add_argument("traceid", help="traceId / record_id / session_id")
    ap.add_argument("--env-file", help=".env 路径（注入 ADP_API_KEY/ADP_APP_ID 等）")
    ap.add_argument("--app-id", help="显式指定 app_id（优先于环境变量）")
    ap.add_argument("--days", type=int, default=365, help="拉取窗口天数（默认 365）")
    ap.add_argument("--refresh", action="store_true", help="忽略本地缓存强制重新拉取")
    ap.add_argument("--show-answer", action="store_true", help="输出命中记录的 answer 全文")
    ap.add_argument("--json", action="store_true", help="输出命中记录的完整原始 JSON")
    ap.add_argument("--export", metavar="DIR", help="导出复核取证包到该目录：record.json（结论+问答+指标）+ session_messages.txt（分析过程消息流）")
    ap.add_argument("--chat-script", default=DEFAULT_CHAT_SCRIPT, help="adp_chat.py 路径（默认同目录）")
    args = ap.parse_args()

    if args.env_file:
        load_env_file(args.env_file)
    app_id = resolve_app_id(args)

    cache_path = os.path.join(tempfile.gettempdir(), "adp_records_%s.json" % app_id)
    export, cached = fetch_records(app_id, args.days, args.chat_script,
                                   cache_path, args.refresh)
    records = extract_records(export)
    print("· app_id=%s | 窗口=%s天 | 记录=%d条 | 数据源=%s" % (
        app_id, export.get("window_days", args.days) if isinstance(export, dict) else args.days,
        len(records), "本地缓存" if cached else "实时拉取"))

    hits = match_records(records, args.traceid.strip())
    if not hits:
        print("\n未命中：该 ID 不在所拉记录的 trace_id/record_id/session_id 中。"
              "\n可尝试 --refresh 重新拉取，或 --days 扩大窗口；"
              "仍无则确认该 ID 是否属于 app_id=%s。" % app_id)
        sys.exit(1)

    print("· 命中 %d 条：" % len(hits))
    for r, field, _ in hits:
        res = r.get("result") or {}
        src = r.get("source") or {}
        call_result = res.get("call_result")
        print("\n===== 匹配字段: %s =====" % field)
        print("record_id    : %s" % r.get("record_id"))
        print("session_id   : %s" % r.get("session_id"))
        print("trace_id     : %s" % r.get("trace_id"))
        print("create_time  : %s" % fmt_time(r.get("create_time")))
        print("call_result  : %s (%s)" % (call_result, CALL_RESULT_MAP.get(call_result, "未知")))
        print("reply_method : %s" % r.get("reply_method"))
        print("channel_type : %s" % src.get("channel_type"))
        print("token        : 总 %s（输入 %s / 输出 %s）" % (
            res.get("total_token"), res.get("input_token"), res.get("output_token")))
        print("延迟         : 总 %s | 首token %s" % (
            fmt_duration(res.get("total_token_latency")),
            fmt_duration(res.get("first_token_latency"))))
        print("question     : %s" % (str(r.get("question"))[:200].replace("\n", " ")))
        if args.show_answer:
            print("\n--- answer (%d chars) ---" % len(r.get("answer") or ""))
            print(r.get("answer") or "")
        if args.json:
            print("\n--- raw record json ---")
            print(json.dumps(r, ensure_ascii=False, indent=2))

    chat = args.chat_script
    rid = hits[0][0].get("record_id")
    sid = hits[0][0].get("session_id")
    print("\n===== 下钻命令（可直接复制执行）=====")
    print("# 会话消息流还原（单轮长链路的替代路径）")
    print("python3 %s messages --app-id %s --conversation-id %s --record-id %s" % (chat, app_id, sid, rid))
    print("# 注：下钻命令在新 shell 执行，需先 export ADP_API_KEY/ADP_APP_ID"
          "（或 source .env）——--env-file 注入仅对本次反查进程生效")

    if args.export:
        rec_path, msg_path, n_msgs, rc = export_evidence(
            app_id, chat, hits[0][0], args.export)
        print("\n===== 复核取证包已导出 =====")
        print("record.json         : %s（question/answer 全文 + Token/延迟指标）" % rec_path)
        print("session_messages.txt: %s（分析过程消息流，约 %d 条）" % (msg_path, n_msgs))
        if rc != 0:
            print("警告：messages 拉取退出码 %d，消息流可能不全" % rc)
        print("取证材料就绪后按 SKILL.md「三问复核」方法分析，缺用户结论/问题模块时先向用户索取。")
    sys.exit(0)


if __name__ == "__main__":
    main()
