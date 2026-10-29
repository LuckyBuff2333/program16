# ADP 技能使用说明（log-review-pan-scan）

> 版本：1.0.0  
> 接入时间：2026-10-29  
> 适用代码：`src/services/adp_ops.py`、`src/api/routes/testing.py`

---

## 一、这个技能是做什么的

`log-review-pan-scan` 用来按 **traceId** 反查 ADP 会话记录，导出复核取证包：

| 产物 | 内容 |
|---|---|
| `record.json` | 智能体的 question / answer + Token/延迟指标 |
| `session_messages.txt` | 分析过程消息流（工具调用、检索、降级声明） |

我们用它生成 **traceid 排查报告**，解决“只有 ADP 报告链接、看不到分析过程”的问题。

---

## 二、技能位置

```
tools/skills/log-review-pan-scan/
  SKILL.md                 # 方法论（四阶段）
  README.md                # 原始使用说明
  scripts/
    record_lookup.py       # 反查 + 取证包导出（我们主要用这个）
    adp_chat.py            # 平台记录查询（底层 MCP）
    pan_scan.py            # 泛解析（暂未接入）
  references/
    knowledge-principles.md
```

---

## 三、凭据

技能需要三个环境变量，取自 `config/config.yaml` 的 `adp` 段：

| 环境变量 | 配置来源 | 说明 |
|---|---|---|
| `ADP_API_KEY` | `adp.mcp_api_key`（回退 `adp.app_key`） | 平台 API Key |
| `ADP_APP_ID` | `adp.app_id` | 目标应用 ID |
| `ADP_SPACE_ID` | `adp.space_id` | 应用归属空间 ID |

`_run_trace_skill()` 会自动注入，不需要手工 export。

---

## 四、代码里的调用方式

### 4.1 入口

```python
from src.services.adp_ops import _run_trace_skill

report_path, err, doc_url = _run_trace_skill(jira_key, trace_id)
```

返回：

- `report_path`：本地 md 报告路径；
- `err`：失败原因（成功为空）；
- `doc_url`：飞书在线文档链接（发布失败为空）。

### 4.2 何时调用

- **仅成功**（已拿到 ADP 报告附件 `_report_file_token`）时调用；
- 失败时不调技能，`traceid` 不写入，`traceid排查` 只放“返回内容”的报告链接。

### 4.3 内部流程

```
trace_id
  → record_lookup.py <trace_id> --days 3|1 --refresh --page-size 50 --export <证据目录>
  → 读取 record.json + session_messages.txt
  → 汇总成 <JIRA>_traceid_report.md
  → 发布为飞书文档（指定文件夹）
  → 返回链接
```

失败会依次尝试 `--days 3`、`--days 1`，仍失败则返回错误并回退 ADP 报告链接。

---

## 五、手工调用（排查用）

```bash
cd tools/skills/log-review-pan-scan
set ADP_API_KEY=...
set ADP_APP_ID=2107062858696560449
set ADP_SPACE_ID=default_space

python scripts/record_lookup.py <traceid> --days 3 --refresh --page-size 50 --export evidence
```

注意：

- `traceid` 支持 `trace_id` / `record_id`（`rcd_`）/ `session_id`（32 位 hex）；
- 平台记录里我们的 `trace_id` 常是 **ConversationId**，对应记录的 `session_id`，脚本已兼容。

---

## 六、我们对技能包做的 3 处修改

| 问题 | 修改 |
|---|---|
| `MCP tools/call ... body size 4194305 exceeds limit 4194304` | `adp_chat.py records` 加 `--page-size 50`（默认 100 太大） |
| 32 位 hex 会话 ID 匹配不到 | `match_records()` 同时匹配 `session_id` |
| `session_messages.txt` 为空（GBK 解码异常） | `messages` 子进程加 `encoding="utf-8", errors="ignore"` |

---

## 七、报告落点

| 报告类型 | 配置键 | 飞书文件夹 token |
|---|---|---|
| traceid 排查报告 | `adp.trace_report_folder` | `Gia7fmmoqlLRCGdW5x1caCd2nfg` |
| 完整分析报告（成功） | `adp.report_folder` | `SeCwfa1iwlLpNEd4lf9cwAZnnHf` |
| 失败快照 / 报错返回 | 同上 | 同上 |
| 批次执行记录 CSV | `adp.batch_report_folder` | `Mhhdfq23flRR12die9scepr9nbd` |

本地文件：

```
docs/adp_results/<JIRA>/<JIRA>_traceid_report.md      # trace 报告
docs/adp_results/<JIRA>/<JIRA>_full_analysis.md       # 完整分析
docs/adp_results/<JIRA>/<JIRA>_fail_*.md              # 失败快照
data/adp_batch_logs/adp_batch_N.csv                   # 批次记录
```

---

## 八、字段写入规则

| 场景 | `traceid` | `traceid排查` |
|---|---|---|
| 成功 | 写入**最后一次**响应的 traceid | 技能报告链接（飞书文档） |
| 失败 | 不写 | 失败快照/返回内容的飞书文档链接（没有则留空） |

补充：

- `traceid` 是**请求级 ID**，每次请求都会变；同一会话只有 `ConversationId` 不变；
- 续接（发“继续”）会复用原 `ConversationId`，最终取最后一次续接的 `traceid`。

---

## 九、错误分类约定

失败原因写在 `分析失败归因`，归类保持原有枚举，例如：

| 场景 | 分析失败归因 |
|---|---|
| 智能体追问 | `需要澄清（ADP智能体追问，需人工作答）` |
| 文本澄清 | `ADP智能体收口无报告(澄清/索取信息话术: ...)` |
| 拒答 | `ADP智能体收口无报告(ReplyMethod=3（智能体拒答）)` |
| 流中断 | `未完成（疑似流中断）` |
| 无附件 | `无日志附件` |
| 附件接口异常 | `ADP附件接口异常` |

---

## 十、已知限制

| 限制 | 说明 |
|---|---|
| 4MB / 分页 | 平台 MCP 单次响应上限 4MB；已用 `--page-size 50` 规避 |
| 时间窗口 | 默认只查近 3 天，失败退到 1 天；更早的记录需手工加 `--days` |
| 记录找不到 | 若 `trace_id` 不属于该 `app_id`，会返回“未命中” |
| 文档权限 | 文档归属创建者，需确认查看人可访问 |

---

## 十一、验证方式

```bash
# 单元测试
.venv\Scripts\python.exe -m pytest tests -q

# 手工验证技能
python tools/skills/log-review-pan-scan/scripts/record_lookup.py <traceid> --days 1 --refresh --export evidence
```

---

## 十二、相关接口

| 接口 | 用途 |
|---|---|
| `GET /api/test/adp_report?jira_key=...` | 打开完整分析报告（本地回退） |
| `GET /api/test/adp_trace_report?jira_key=...` | 打开 traceid 排查报告（本地回退） |
