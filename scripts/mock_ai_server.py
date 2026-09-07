"""本地模拟日志分析 API 服务

接收 bugid 与触发时间，读取本地测试日志文件，发送至 qwen3.7-flash 做真实分析，
返回与真实 AI 日志分析工具接口相同格式的报告（{code:0, data:{report:...}}）。

启动方式：python scripts/mock_ai_server.py
监听端口：8061
"""
import csv
import os
import sys

import uvicorn
from fastapi import FastAPI, Request

# 项目根目录
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

from src.config import load_config
from src.clients.base import http_post

app = FastAPI(title="模拟日志分析 API")

# 测试数据路径
TESTDATA_CSV = os.path.join(PROJECT_ROOT, "testdata", "bug_test_data.csv")
LOG_DIR = os.path.join(PROJECT_ROOT, "testdata", "logs")


def _load_testdata(bugid: str) -> dict | None:
    """从测试数据表查找 bugid 对应行"""
    if not os.path.exists(TESTDATA_CSV):
        return None
    with open(TESTDATA_CSV, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if row.get("bugid") == bugid or row.get("bugid", "").endswith(bugid):
                return row
    return None


def _read_log(log_rel_path: str) -> str:
    """读取日志文件内容"""
    log_path = os.path.join(PROJECT_ROOT, "testdata", log_rel_path)
    if not os.path.exists(log_path):
        return "(日志文件不存在)"
    with open(log_path, encoding="utf-8") as f:
        return f.read()


SYSTEM_PROMPT = """你是一个资深的后端运维工程师，擅长分析服务日志并定位问题根因。
请根据以下日志内容进行分析，严格按照指定格式输出 Markdown 分析报告。

输出格式（必须严格遵守）：
# Bug {bugid} 日志分析报告

## 根因结论
（用一句话概括根因，不超过40个字）

## 问题触发时间
（从日志中推断问题爆发的精确时间点）

## 关键日志依据
- （列出3~5条关键日志行，每条以 - 开头）

## 分析步骤
1. （第一步：发现的问题现象）
2. （第二步：深入排查的过程）
3. （第三步：定位到的具体根因）
4. （第四步：修复措施或建议）

注意：分析步骤必须基于日志内容推导，不要凭空编造。"""


@app.post("/api/analyze")
async def analyze(request: Request):
    """日志分析接口：读取本地日志 → qwen 分析 → 返回报告"""
    body = await request.json()
    bugid = body.get("bug_id", body.get("bugid", ""))
    trigger_time = body.get("trigger_time", "")

    print(f"[mock-ai] 收到分析请求: bugid={bugid}, trigger_time={trigger_time}")

    # BUG-5005 模拟服务端错误（用于测试失败场景）
    if "5005" in str(bugid):
        from fastapi.responses import JSONResponse
        print(f"[mock-ai] 模拟服务端错误: {bugid}")
        return JSONResponse(
            status_code=500,
            content={"code": -1, "message": "Internal Server Error: 日志分析服务异常"}
        )

    # 读取测试数据和日志
    testdata = _load_testdata(bugid)
    if testdata:
        log_content = _read_log(testdata.get("日志文件", ""))
    else:
        log_content = f"(未找到 {bugid} 的测试数据)"

    # 调用 qwen3.7-flash 做真实分析
    cfg = load_config().get("llm_filter", {})
    llm_url = cfg.get("url", "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions")
    llm_model = cfg.get("model", "qwen3.7-flash")
    llm_key = cfg.get("api_key", "")

    user_msg = f"Bug ID: {bugid}\n触发时间: {trigger_time or '未知'}\n\n日志内容:\n{log_content}"

    headers = {"Authorization": f"Bearer {llm_key}"} if llm_key else {}
    payload = {
        "model": llm_model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_msg},
        ],
        "temperature": 0.2,
    }

    try:
        result = http_post(llm_url, payload, timeout=60, headers=headers)
        report = result.get("choices", [{}])[0].get("message", {}).get("content", "")
        # 去除可能的 markdown 代码块包裹
        import re
        report = re.sub(r"^```(?:markdown)?\s*", "", report.strip())
        report = re.sub(r"\s*```$", "", report.strip())
        print(f"[mock-ai] qwen 分析完成: {bugid}, 报告长度={len(report)}")
    except Exception as e:
        print(f"[mock-ai] qwen 分析失败: {e}")
        report = f"# Bug {bugid} 日志分析报告\n\n## 根因结论\n\n分析失败: {str(e)[:200]}\n\n## 分析步骤\n\n1. 分析失败\n"

    return {"code": 0, "data": {"report": report}}


if __name__ == "__main__":
    print("=" * 50)
    print("  模拟日志分析 API 服务")
    print("  端口: 8061")
    print("  接口: POST /api/analyze")
    print("=" * 50)
    uvicorn.run(app, host="127.0.0.1", port=8061, log_level="info")
