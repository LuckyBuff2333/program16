"""内网环境接口连通性检测脚本

使用方法：插上网线后执行
    python scripts/check_network.py
"""
import time
import httpx
import json

TIMEOUT = 10

# ── 待检测接口列表 ──
endpoints = [
    {
        "name": "AI 日志分析接口",
        "config": "ai_log_api",
        "method": "POST",
        "url": "http://10.22.127.11:8001/jira/analyze",
        "body": {"issue_key": "VCU-501224"},
        "headers": {"Content-Type": "application/json"},
        "expect": "返回分析报告或异步任务启动响应",
    },
    {
        "name": "Jira REST API",
        "config": "jira_api",
        "method": "GET",
        "url": "https://jira-patac.apps.saic-gm.com/rest/api/2/issue/VCU-501224",
        "params": {"expand": "comment"},
        "headers": {"Authorization": "Bearer <YOUR_JIRA_TOKEN>"},
        "expect": "返回 Jira issue JSON",
    },
    {
        "name": "阿里云 LLM (qwen3.7-flash)",
        "config": "llm_filter",
        "method": "POST",
        "url": "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions",
        "body": {"model": "qwen3.7-flash", "messages": [{"role": "user", "content": "回复OK"}], "max_tokens": 5},
        "headers": {"Authorization": "Bearer <YOUR_DASHSCOPE_KEY>", "Content-Type": "application/json"},
        "expect": "返回 LLM 回复",
    },
    {
        "name": "Diana AI 网关 (dianaDeepSeekV)",
        "config": "diana",
        "method": "POST",
        "url": "http://aigw01.apps-qa.saic-gm.com/diana-text/v1/chat/completions",
        "body": {"model": "dianaDeepSeekV", "messages": [{"role": "user", "content": "回复OK"}], "max_tokens": 10},
        "headers": {"x-api-key": "<YOUR_DIANA_KEY>", "Content-Type": "application/json"},
        "expect": "返回 LLM 回复（可能需 token，响应任何状态码均说明服务可达）",
        "any_response_ok": True,
    },
    {
        "name": "AIDM Token 接口",
        "config": "diana.token",
        "method": "POST",
        "url": "http://aidm-issue.apps-qa.saic-gm.com/aidm/sgmidp/oauth2/v3.0/token",
        "body": {
            "scope": "ALL",
            "grant_type": "client_credentials",
            "client_id": "PVCS0l3wUS3xhb1V2Y721hIQV25SmjGVECDodz612xyYYz249G22s2771a0",
            "client_secret": "PVCS02dXtb9BAq3fxkr1b9v2730OJMGq4CI90ijSKoXnR2c1Wq3cctLV25L",
        },
        "form": True,
        "headers": {"Content-Type": "application/x-www-form-urlencoded"},
        "expect": "返回 access_token",
    },
]


def check_one(ep: dict) -> dict:
    """检测单个接口，返回结果字典"""
    name = ep["name"]
    url = ep["url"]
    method = ep["method"]
    result = {"name": name, "url": url, "ok": False, "elapsed": 0, "detail": ""}

    t0 = time.time()
    try:
        if method == "GET":
            r = httpx.get(url, params=ep.get("params"), headers=ep.get("headers"),
                          timeout=TIMEOUT, follow_redirects=True)
        elif ep.get("form"):
            r = httpx.post(url, data=ep.get("body", {}), headers=ep.get("headers"), timeout=TIMEOUT)
        else:
            r = httpx.post(url, json=ep.get("body", {}), headers=ep.get("headers"), timeout=TIMEOUT)

        result["elapsed"] = time.time() - t0
        result["status_code"] = r.status_code

        if r.status_code < 400 or ep.get("any_response_ok"):
            result["ok"] = True
            # 截取响应摘要
            try:
                data = r.json()
                text = json.dumps(data, ensure_ascii=False)
                result["detail"] = text[:200] if len(text) > 200 else text
            except Exception:
                result["detail"] = r.text[:200]
        else:
            result["detail"] = f"HTTP {r.status_code}: {r.text[:150]}"

    except httpx.ConnectTimeout:
        result["elapsed"] = time.time() - t0
        result["detail"] = "ConnectTimeout - 连接超时，服务不可达"
    except httpx.ConnectError as e:
        result["elapsed"] = time.time() - t0
        err_msg = str(e)
        if "getaddrinfo" in err_msg:
            result["detail"] = "DNS 解析失败，域名不存在"
        elif "10061" in err_msg:
            result["detail"] = "连接被拒绝，服务未启动"
        else:
            result["detail"] = f"ConnectError: {err_msg[:80]}"
    except Exception as e:
        result["elapsed"] = time.time() - t0
        result["detail"] = f"{type(e).__name__}: {str(e)[:80]}"

    return result


def main():
    print("=" * 70)
    print("  内网环境接口连通性检测")
    print("=" * 70)

    results = []
    for ep in endpoints:
        print(f"\n检测: {ep['name']}...")
        print(f"  {ep['method']} {ep['url']}")
        r = check_one(ep)
        results.append(r)

        icon = "OK" if r["ok"] else "X"
        print(f"  [{icon}] {r['detail'][:100]}  ({r['elapsed']:.1f}s)")

    # ── 汇总 ──
    ok_count = sum(1 for r in results if r["ok"])
    fail_count = len(results) - ok_count
    print(f"\n{'=' * 70}")
    print(f"  结果: {ok_count} 个可用, {fail_count} 个不可用")
    print("=" * 70)

    if fail_count:
        print("\n不可用接口:")
        for r in results:
            if not r["ok"]:
                print(f"  - {r['name']}: {r['detail'][:60]}")

    if ok_count:
        print("\n可用接口:")
        for r in results:
            if r["ok"]:
                print(f"  + {r['name']} ({r['elapsed']:.1f}s)")


if __name__ == "__main__":
    main()
