"""按 Jira 最新一次 ADP 会话，用消息 start_time/end_time 计算 case 耗时。

用途：
  python tools/adp_case_duration.py --field "耗时2-Ai拿到字段自行相减计算"
  python tools/adp_case_duration.py --field "耗时3-AI写脚本，两字段相减"

口径：
  - 每个 Jira 取 create_time 最新的会话；
  - 开始时间取该会话最早记录 create_time；
  - 完成时间取该会话最后一条 assistant 消息 end_time；
  - traceid 取最后一条 assistant 消息的 trace_id；
  - 耗时 = (完成 - 开始) / 60，保留 1 位小数。
"""
import argparse
import concurrent.futures
import json
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.clients import feishu_client
from src.config import load_config

SCRIPT = os.path.join(os.path.dirname(__file__), "skills", "log-review-pan-scan", "scripts", "adp_chat.py")
ENV = os.environ.copy()
ENV.update({
    "ADP_API_KEY": os.environ.get("ADP_API_KEY", ""),
    "ADP_APP_ID": os.environ.get("ADP_APP_ID", ""),
    "ADP_SPACE_ID": os.environ.get("ADP_SPACE_ID", "default_space"),
})
MASTER = "tblVezjvVi4oxh2a"


def txt(v):
    if isinstance(v, list):
        return "".join(str(x.get("text") or x.get("name") or x) for x in v)
    if isinstance(v, dict):
        return str(v.get("text") or v.get("name") or v)
    return str(v) if v is not None else ""


def call(args):
    p = subprocess.run([sys.executable, SCRIPT] + args, capture_output=True,
                       text=True, encoding="utf-8", env=ENV, timeout=180)
    if p.returncode != 0:
        raise RuntimeError((p.stderr or "")[-200:])
    return json.loads(p.stdout)


def calc(jira):
    d = call(["records", "--days", "365", "--query", jira,
              "--query-type", "Question", "--page-size", "100", "--json"])
    recs = d.get("records") or []
    if not recs:
        return None
    sessions = {}
    for r in recs:
        sid = r.get("session_id")
        if sid:
            sessions.setdefault(sid, []).append(r)
    if not sessions:
        return None
    sid, srecs = max(sessions.items(), key=lambda kv: max(int(x.get("create_time") or 0) for x in kv[1]))
    m = call(["messages", "--conversation-id", sid, "--direction", "3",
              "--limit", "50", "--json"])
    msgs = []
    for x in (m.get("message_list") or []):
        ex = x.get("extra_info") or {}
        if ex.get("start_time") and ex.get("end_time"):
            msgs.append((x.get("role"), int(ex["start_time"]), int(ex["end_time"]),
                         str(ex.get("trace_id") or "")))
    if not msgs:
        return None
    # 以最后一条 assistant 消息的 traceid 为最新 traceid
    latest = max(msgs, key=lambda x: x[2])
    latest_tid = latest[3]
    same = [x for x in msgs if x[3] == latest_tid]
    start = min(x[1] for x in same)
    end = max(x[2] for x in same)
    return {
        "jira": jira, "traceid": latest_tid,
        "minutes": round((end - start) / 1000 / 60, 1),
        "start_ms": start, "end_ms": end,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--field", required=True)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    c = load_config()["adp"]
    app = c["bitable_app_token"]
    rows = feishu_client.list_bitable_records(app, MASTER)
    targets = []
    for r in rows:
        f = r.get("fields") or {}
        j = txt(f.get("Jira链接")).rstrip("/").split("/")[-1]
        if j:
            targets.append((j, r.get("record_id")))

    results = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
        futs = {pool.submit(calc, j): (j, rid) for j, rid in targets}
        for i, fut in enumerate(concurrent.futures.as_completed(futs), 1):
            j, rid = futs[fut]
            try:
                val = fut.result()
            except Exception as e:
                print(i, j, "ERR", str(e)[:120], flush=True)
                continue
            if val:
                results.append((rid, val["minutes"], val["traceid"]))
                print(i, j, val["minutes"], val["traceid"], flush=True)

    print("calculated", len(results), "of", len(targets), flush=True)
    with open("data/adp_case_duration_field.json", "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    if not args.dry_run:
        updates = [{"record_id": rid, "fields": {args.field: str(m)}} for rid, m, _ in results]
        for i in range(0, len(updates), 20):
            feishu_client.update_bitable_records(app, MASTER, updates[i:i + 20])
        print("updated", len(updates), flush=True)


if __name__ == "__main__":
    main()
