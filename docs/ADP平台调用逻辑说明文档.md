# ADP 平台调用逻辑说明文档

> 最后更新：2026-10-26（第 2 版：补全失败快照、结果预览契约、失败类型、报告读取端点、作业模型）

## 一、架构总览

```
前端 AdpTestPanel.vue
  ├─ 单条分析  → POST /api/test/adp_single
  ├─ 批量执行  → POST /api/test/adp_batch    (Excel/CSV 导入)
  ├─ 表格查找  → POST /api/test/adp_lookup   (多维表格自动查找，已接入作业模型)
  ├─ 补全字段  → POST /api/test/adp_enrich   (补全描述/触发时间)
  ├─ 停止执行  → POST /api/test/adp_lookup/stop
  └─ 查看报告  → GET  /api/test/adp_report?jira_key=VCU-xxx  (按需打开完整文本)

后端 API (testing.py)
  ├─ 参数解析 + 并发控制 (ThreadPoolExecutor, batch_size=2)
  ├─ SSE 流式推送进度到前端（只推预览，不推全文）
  ├─ adp_lookup 通过 job_stream 注册作业（/api/jobs 可查可停）
  └─ 调用 adp_ops.py 核心函数链

核心函数链 (adp_ops.py)
  Step 1   query_attachments()       → dpportal 查附件
  Step 2   build_adp_message()       → 构建入参消息
           call_adp_sse_stream()     → ADP v2 SSE 流式分析（含迟到报告续接）
  Step 3   extract_adp_results()     → 提取 6 个字段
  Step 3.5 download_adp_report()     → 下载 HTML 报告 + 上传飞书附件
  Step 4   save_adp_local()          → 保存本地 MD + JSON（返回输出目录）
           失败分支：_save_adp_fail_snapshot() → 保存失败快照 MD
  Step 5   write_adp_to_feishu()     → 写入飞书多维表格
```

## 二、配置参数（config.yaml → `adp` 段）

```yaml
adp:
  app_key: skOjTa...           # ADP API Key
  url: https://wss.lke.cloud.tencent.com/adp/v2/chat   # SSE 接口
  sandbox_base: https://sandbox.adp.cloud.tencent.com/files?path=
  attach_api: https://dpportal.apps.saic-gm.com/api/logAnalysis/attachments
  attach_api_key: c2e918...    # dpportal 认证 Key
  timeout: 3600                # 单次分析超时（秒）
  bitable_app_token: K7wib...  # 多维表格 app_token
  bitable_table_id: tblVez...  # 多维表格 table_id
  bitable_view_id: ""          # 可选，指定视图
  jira_field: Jira链接          # 用于匹配记录的字段名
  save_dir: docs/adp_results   # 本地结果保存目录
```

> 未配置项均有默认值（`_get_adp_cfg`）。`save_dir` 为默认值时会走 `get_path("doc_dir")`，跟随 output 配置。

## 三、核心流程详解

### Step 1：查询附件（query_attachments）

```
输入: Jira号 (如 VCU-512009)
接口: POST https://dpportal.apps.saic-gm.com/api/logAnalysis/attachments
请求: {"jiraKey": "VCU-512009"}  + X-API-Key 认证
输出: [{filename, downloadUrl, size, ...}, ...]
超时: 30s
```

**有效附件过滤（`_is_valid_attachment`）**：文件名匹配
`\.(zip|z\d+|rar|7z|tar|gz|bz2|xz|tgz|txt|log)(\.\d+)?$`（含分卷压缩包），且 `downloadUrl` 非空。

两种提前终止（都会写 `fail_type`，`results.完成状态 = 无法分析`）：

| 场景 | error 文案 | fail_type |
|---|---|---|
| 无附件 | `无附件` | 输入质量问题（无附件） |
| 有附件但无有效日志 | `没有日志附件（已有: xxx）` | 输入质量问题（无有效日志文件） |

### Step 2：构建消息 + 调用 ADP SSE

#### 2a. 构建入参消息（build_adp_message）

```
JIRA号VCU-512009，描述: {description}，触发时间: {trigger_time}
日志附件下载链接：
- filename1 (12.3MB): https://downloadUrl1
- filename2 (5.6MB): https://downloadUrl2
```

只拼接「有效附件」，日志会记录「共 N 个附件，过滤后 M 个」。

#### 2b. SSE 流式调用（call_adp_sse_stream）

```
接口: POST https://wss.lke.cloud.tencent.com/adp/v2/chat
请求体:
  {
    RequestId: uuid(32位hex),
    ConversationId: uuid(32位hex),
    AppKey: config.app_key,
    VisitorId: "jira_analysis_user",
    Contents: [{Type: "text", Text: message}],
    Incremental: true,
    Stream: "enable",
    StreamingThrottle: 5
  }
超时: httpx.Timeout(timeout=3600, connect=30, read=60)
重试: 最多 3 次（仅连接级错误且尚未收到任何文本）
退避: wait = 10 * attempt 秒（可被 stop_event 打断）
```

**SSE 事件类型处理：**

| 事件 Type | 处理逻辑 |
|-----------|----------|
| `response.created` | 记录 start_ts；尝试提取 trace_id（TraceId/trace_id/ConversationId…） |
| `text.delta` | 追加到 full_text（`_fix_encoding` 修复 latin-1→UTF-8） |
| `text.replace` | 检测 closeout JSON（同时含 `"ok"` 与 `"html"`） |
| `content.added` (Type=file) | 收集 `{name, url}` 到 file_urls |
| `[DONE]` | 流结束标记 |

**心跳机制：** 每 30s 调用 `keepalive_cb(elapsed_sec)`，前端据此推 SSE 保活帧。

**返回值（6 元组）：**

```
(full_text, file_urls, closeout_data, start_ts, end_ts, trace_id)
```

**closeout 兜底：** 若流中未解析到 closeout，则用正则从 full_text 中再找一次
（`{"ok":true,...,"html":...}` 或含 `case_id` 的 JSON）。

#### 2c. 迟到报告检测与续接（重要）

ADP 偶尔在 SSE 结束后才产出 HTML 报告，因此有续接逻辑：

```
触发条件: full_text 长度 > 500 且当前没有可下载报告
         （无 agent.adp-cos.com 链接，且 file_urls 中没有非 meta 的 .html）
耗时门槛: 本次流耗时 <= 300 秒 -> 判定为连接异常中断，跳过续接
续接轮次: 最多 2 轮，每轮等待 300 秒（合计最多 10 分钟）
每轮动作: 复制原 payload、换新 RequestId、重新 POST 同一接口，
         继续追加 text.delta / text.replace / content.added
提前结束: 出现可下载报告，或本轮无新增内容（文本长度与 file_urls 都没变）
```

### Step 3：提取分析结果（extract_adp_results）

从 `full_text` 和 `closeout_data` 中提取 **6 个字段**：

| 字段名 | 提取逻辑 |
|--------|----------|
| 完成状态 | 固定为 "完成"（无报告时由 Step 3.5 改为 "分析失败"） |
| 报告链接 | 4 级优先级提取（见下文） |
| 置信度 | 优先 closeout_data → 文本正则提取 → 规范化校验 |
| 耗时(分) | `(end_ts - start_ts) / 1000 / 60` |
| agent分析的问题模块 | 正则匹配 ADP 专有格式（后续可被 HTML 中的断点模块覆盖） |
| agent分析的root cause | 正则匹配根因归属/现象级归因 |

**报告链接 4 级提取优先级（_extract_report_url）：**

```
1. 文本中 agent.adp-cos.com 链接 (签名有效期 ~90天，最可靠)
2. file_urls 中的 .html 文件 (排除 meta 文件)
3. closeout_data 拼 sandbox 路径 (签名有效期短，易 401)
4. 文本中其他 report_*.html URL
```

**失败归因补全：** 若 Step 3.5 判定为"分析失败"但没有归因，会用
`classify_adp_failure(error, full_text, attachment_count)` 自动归类并写入
`results.分析失败归因`（同一值会作为 `fail_type` 返回前端）。

### Step 3.5：下载 HTML 报告 + 上传附件（download_adp_report）

```
1. 下载: GET report_url → 保存到 reports/adp/{jira_key}/{html_file 或 URL 末段}
         httpx.Client(timeout=120, follow_redirects=True)
2. 上传: feishu_client.upload_bitable_attachment(app_token, local_path,
                                                content_type="text/html")
         → 飞书 Drive media upload API (parent_type=bitable_file)
         → 返回 file_token
3. 成功: results["_report_file_token"] = token
        results["报告链接（分析报告、可观测报告）"] = "附件: xxx.html"
        并从 HTML 中提取"断点模块"覆盖 results["agent分析的问题模块"]
4. 失败/无 CDN 链接:
        results["完成状态"] = "分析失败"
        results["分析失败归因"] = "分析完成但未产出HTML报告"
        pop 掉"报告链接"字段（保留 root cause / 置信度 / 模块等已提取字段）
```

> 为什么必须用 file_token：多维表格的报告链接是**附件类型字段**，
> 写入 URL 字符串会触发 `AttachFieldConvFail`。

### Step 4：保存本地文件（save_adp_local）

```
保存路径: {doc_dir}/adp_results/{jira_key}/     (默认 docs/adp_results/...)
文件:
  - {jira_key}_full_analysis.md  (完整分析报告：入参/提取结果/closeout/file_urls/全文)
  - {jira_key}_raw_data.json     (结构化原始数据，供重放/排查)
返回值: out_dir（供上层拼出 report_path）
```

**失败快照（`_save_adp_fail_snapshot`）**：Step 3~5 任一环节抛异常时调用，

```
文件: {doc_dir}/adp_results/{jira_key}/{jira_key}_fail_{YYYYmmdd_HHMMSS}.md
内容: 失败时间 / 错误信息 / 问题描述 / 触发时间 /
      已提取字段(JSON，过滤下划线私有字段) / ADP 返回内容（不截断）
```

### Step 5：写入飞书多维表格（write_adp_to_feishu）

```
1. 查找: list_bitable_records → 按 jira_field(默认 Jira链接) 匹配 Jira 号
2. 不存在则新建: batch_create_records（仅写 jira_field）
3. 写入字段白名单:
   allowed = ["完成状态", "报告链接（分析报告、可观测报告）", "耗时(分)",
              "agent分析的问题模块", "agent分析的root cause", "置信度"]
4. 报告链接字段: 有 file_token → [{"file_token": token}]
                无 file_token → 从写入字段中 pop 掉
5. update_bitable_records 写入，返回 {ok, record_id, message, fields}
```

`skip_feishu=True`（表格查找模式）时跳过本步，由调用方 `_write_back` 用**已知 record_id** 写回，避免重复全表查询。

## 四、结果返回契约（前端只拿预览，不拿全文）

完整分析文本可能有几 MB，放 SSE 会撑爆响应体。因此 Step 2 拿到文本后**立刻**记录预览，
后续任何失败都仍可回显：

| 字段 | 含义 |
|---|---|
| `text_len` | 完整文本字符数 |
| `text_preview` | 前 2000 字（固定截断） |
| `report_path` | 落盘 md 路径（成功=`_full_analysis.md`，异常=`_fail_时间戳.md`） |
| `fail_type` | 失败类型；成功时为空串 |
| `file_urls` | ADP 返回的文件链接列表 `[{name, url}]` |
| `results` | 提取的 6 个字段（含 `分析失败归因`、`_report_file_token` 等） |
| `elapsed` / `total_elapsed` | 分析耗时 / 全流程耗时（秒） |
| `attachment_count` | 附件总数 |
| `feishu_ok` / `feishu` | 飞书写入结果 |

`_adp_text_payload(result)` 与 `_adp_fail_type(result)` 负责统一这两个字段，
`fail_type` 优先取 `result.fail_type`，回退 `results.分析失败归因`。

## 五、失败类型分类（fail_type）

### 5.1 自动归类（classify_adp_failure）

| 输入特征 | 归因 |
|---|---|
| error = `无附件` | 输入质量问题（无附件） |
| error 以 `没有日志附件` 开头 | 输入质量问题（无有效日志文件） |
| error = `ADP 无返回` | ADP连接超时或网络异常 |
| 文本 < 1500 字，含"日志附件下载链接/日志包路径"且含"缺失/补充/请提供" | 输入质量问题（日志附件链接为空） |
| 文本 < 1500 字，含"请先明确/无法启动/矛盾/不一致"等 | 输入质量问题（描述矛盾或信息不足） |
| 含 `404` 且含"下载/链接"，或"链接已失效" | 下载链接失效 |
| 含 `rc=18`/`transfer closed` 且含"残件" | 下载链接失效（传输中断） |
| 含 `expect=46` 或"体积对账 + 误判" | 下载链接失效（签名URL响应异常） |
| 含"下载/解包/索引/fetch_raw/unpack"且文本 > 3000 字 | 分析过程未完成 |
| error 含 connect/timeout | ADP连接超时或网络异常 |
| 其它默认 | 分析完成但未产出HTML报告 |

### 5.2 手工/特殊类型

| 场景 | fail_type |
|---|---|
| Step 3~5 抛异常 | `处理异常: {异常信息前120字}` |
| 分析成功但飞书写入失败 | `飞书写入失败` |
| 表格查找批次超时 | `ADP 分析超时` |

### 5.3 最终取值规则（run_adp_single 末尾）

```
out.ok 为真        → fail_type = ""
否则              → 依次取：results.分析失败归因 → out.fail_type（早退时已写）
                    → 若都为空：完成状态=="完成" 则 "飞书写入失败"
                                否则 classify_adp_failure(...)
最后回填 results.分析失败归因（若为空）
```

## 六、报告读取端点

### `GET /api/test/adp_report?jira_key=VCU-xxx`

```
校验: jira_key 必须匹配 [A-Za-z0-9_-]+（防路径穿越）
主路径: {save_dir}/adp_results/{key}/{key}_full_analysis.md
回退  : 同目录下 <key>_fail_*.md 中最新的一份（按文件名倒序）
返回  : FileResponse(text/markdown; charset=utf-8)，浏览器内联展示
失败  : {"ok": false, "message": "报告不存在: xxx"} / "jira_key 不合法"
```

前端「查看完整报告」链接就是拼这个 URL（`adpReportUrl(key)`）。

## 七、API 端点详解

### 7.1 单条分析 `/api/test/adp_single`

```
输入: {bugid: "VCU-xxx"}
流程: Jira API 获取描述/触发时间 → run_adp_single() → SSE 推送进度
SSE 事件: step(jira_info/attachments/adp_analysis/...) / keepalive / done
done 帧字段: ok, results, elapsed, attachment_count, feishu_ok, fail_type,
             text_len, text_preview, report_path, file_urls
无附件时也返回 done（ok=false + fail_type），不再只回一句"无附件"
```

### 7.2 批量执行 `/api/test/adp_batch`

```
输入: {items: [{bugid, description, trigger_time}], batch_size: 2, continuous: false}
流程:
  1. 按 batch_size 分批（默认 2）
  2. 批内并发 ThreadPoolExecutor(max_workers=batch_size)
  3. 非阻塞轮询 + 5s 心跳
  4. 单批超时 600 秒
  5. 连续模式: 完成一批立即开始下一批
SSE 事件: dedup / start / batch_start / item_done / batch_done / keepalive / done
失败策略: 不重试，直接标记"分析失败"并写 fail_type
```

### 7.3 表格查找 `/api/test/adp_lookup`

```
输入: {mode: "manual"|"auto", bugids: [...], limit: 10, batch_size: 2}
流程:
  1. manual: 使用传入 bugids；auto: 从多维表格找"完成状态"为空的记录，取前 limit 条
  2. Jira API 补全 description + trigger_time
  3. 按 batch_size 并发；batch deadline = adp.timeout + 120
  4. run_adp_single(skip_feishu=True) → _write_back 用已知 record_id 写回
  5. 支持停止信号
SSE 事件: step(read_bitable) / start / batch_start / item_done / batch_done / done
超时或停止的条目: item_done 带 fail_type="ADP 分析超时"
```

**作业模型接入**：端点返回前会 `JOBS.create("adp_lookup", "ADP 表格查找作业")`，
并用 `job_stream(job, event_generator, adp_lookup_stop_event)` 包装 —— 作业结束时
自动落 `done/failed/cancelled`，页面 `/api/jobs` 可查，`/api/jobs/{id}/stop` 可单独停止。

**_write_back 写回逻辑：**
- `ok=true` 或 状态为"无法分析"/"分析失败" → 允许写回
- 其他失败 → 跳过写回
- 报告链接：有 file_token 写入附件格式，无则 pop 掉

### 7.4 补全字段 `/api/test/adp_enrich`

```
输入: {bugids: ["VCU-xxx", ...]}
流程: ThreadPoolExecutor(max_workers=5) 并发调用 Jira API 获取 description + trigger_time
输出: [{bugid, description, trigger_time}, ...]
```

### 7.5 停止执行 `/api/test/adp_lookup/stop`

```
功能: 置位 adp_lookup_stop_event，当前批次完成后停止（不中断已在执行的分析）
注意: 只影响 ADP 表格查找，不影响回归/表单/时间提取等其它流程（各自独立事件）
```

### 7.6 读取报告 `/api/test/adp_report`

见「六、报告读取端点」。

## 八、前端 SSE 事件协议

| 端点 | 事件 type | 说明 |
|---|---|---|
| adp_single | `step` | 步骤状态 `{step, status, detail?}`，step 含 jira_info/attachments/adp_analysis/extract/download_report/save_local/write_feishu |
| adp_single | `keepalive` | `{elapsed}` |
| adp_single | `done` | 最终结果（含第四节所有字段） |
| adp_batch | `dedup` | `{skipped}` 去重跳过的数量 |
| adp_batch | `start` | `{total, batch_size, total_batches, continuous}` |
| adp_batch | `batch_start` | `{batch, total_batches, count}` |
| adp_batch | `item_done` | `{jira_key, ok, results, error, fail_type, text_len, text_preview, report_path, file_urls}` |
| adp_batch | `batch_done` | `{batch, success, fail}` |
| adp_lookup | `step` | `{step: read_bitable, status, total_records, matched}` |
| adp_lookup | `start` | `{total, batch_size}` |
| adp_lookup | `batch_start` | `{batch, items}` |
| adp_lookup | `item_done` | 同 adp_batch |
| adp_lookup | `batch_done` | `{batch, success, fail, skip}` |
| adp_lookup | `done` | `{total, success, fail, skip}` |
| 通用 | `keepalive` | `{elapsed}` 或 `{running: []}` |

> 历史文档中的 `progress`/`all_done`/`error` 在此版本已不再使用；
> 单条采 `step`，批量采 `batch_*`，最终都是 `done`。

## 九、作业模型（/api/jobs）

| 端点 | 说明 |
|---|---|
| `GET /api/jobs?limit=20` | 最近作业列表（新→旧），字段含 id/type/title/status/total/done/percent/elapsed_sec/message/error |
| `GET /api/jobs/{job_id}` | 单个作业快照 |
| `POST /api/jobs/{job_id}/stop` | 请求停止该作业（只置位它自己的停止事件） |

当前接入状态：

| 流程 | 是否接入作业 | 类型 |
|---|---|---|
| ADP 表格查找 | ✅ | `adp_lookup` |
| ADP 单条 / 批量 / 补全 | ❌（无作业，靠 SSE 连接） | — |
| 回归 / 表单 / 时间提取 / 缓存批处理 | ✅ | `regression` / `form_exec` / `time_extract` / `cache_batch` |

## 十、关键参数汇总

| 参数 | 值 | 位置 | 说明 |
|------|------|------|------|
| 并发数 | 2 | testing.py | batch_size 默认值（lookup 同） |
| 补全并发 | 5 | testing.py | adp_enrich |
| SSE 超时 | 3600s | config.yaml | 单次 ADP 分析超时 |
| SSE 连接超时 | 30s | adp_ops.py | connect timeout |
| SSE 读超时 | 60s | adp_ops.py | read timeout |
| SSE 重试 | 3 次 | adp_ops.py | 仅连接级错误且未收到文本 |
| 重试退避 | 10/20/30s | adp_ops.py | wait = 10 * attempt |
| 心跳间隔 | 30s | adp_ops.py | keepalive 回调 |
| StreamingThrottle | 5 | adp_ops.py | SSE 流式节流 |
| 迟到报告门槛 | 300s | adp_ops.py | 流耗时 ≤300s 不触发续接 |
| 续接轮次 | 2 轮 × 300s | adp_ops.py | 最多多等 10 分钟 |
| 报告下载超时 | 120s | adp_ops.py | HTML 报告下载（跟随重定向） |
| 附件查询超时 | 30s | adp_ops.py | dpportal 请求 |
| 批次 deadline（batch） | 600s | testing.py | 单批超时 |
| 批次 deadline（lookup） | timeout + 120s | testing.py | 留 2 分钟余量 |
| 心跳轮询 | 5s | testing.py | SSE sleep 间隔 |
| 自动模式 limit | 10 条 | testing.py | auto 模式默认 |
| 预览截断 | 2000 字 | adp_ops.py | `text_preview` |

## 十一、错误处理与降级

| 场景 | 处理 |
|------|------|
| 无附件 | 完成状态=无法分析，fail_type=输入质量问题（无附件），不写回 |
| 无有效日志附件 | 完成状态=无法分析，fail_type=输入质量问题（无有效日志文件） |
| ADP 无返回 | 完成状态=分析失败，fail_type=ADP连接超时或网络异常 |
| SSE 连接失败 | 最多重试 3 次（10/20/30s 退避，停止信号可打断） |
| SSE 已收到数据后断连 | 不重试，返回已收数据继续后续步骤 |
| SSE 流结束但无报告 | 流耗时 >300s 时续接最多 2 轮（每轮 5 分钟） |
| 报告下载 401/超时 | file_token 为空，报告链接字段 pop 掉，完成状态=分析失败 |
| 无 CDN 报告链接 | 同上，保留已提取字段；fail_type=分析完成但未产出HTML报告 |
| Step 3~5 抛异常 | 已拿到的文本写入失败快照，report_path 指向快照，fail_type=处理异常: xxx |
| 飞书写入异常 | 捕获并记录；本地文件已保存可重放；分析成功但写入失败 → fail_type=飞书写入失败 |
| 报告链接写入附件字段 | 必须 file_token 格式，URL 字符串会触发 AttachFieldConvFail |
| 批次超时/停止 | item_done 带 fail_type=ADP 分析超时（lookup）或标记失败（batch） |

## 十二、前端展示（AdpTestPanel.vue）

| 区域 | 展示内容 |
|---|---|
| 单条执行 | 步骤条 + 结果区；新增「失败类型」项（红字，仅失败时出现） |
| 分析文本 | 只显示 `text_preview`（前 2000 字）+ 「查看完整报告」链接（指向 `/api/test/adp_report`） |
| 批量执行 | 表格新增「失败类型」列；展开行显示预览 + 报告链接 |
| 表格查找 | 同上（表格 + 展开行） |
| 停止 | 单条/批量靠断开 SSE；表格查找可点停止（服务端 `adp_lookup_stop_event`，或 `/api/jobs/{id}/stop`） |

## 十三、数据流向图

```
                    ┌─────────────────┐
                    │   前端 Vue      │
                    │  AdpTestPanel   │
                    └────────┬────────┘
                             │ POST (SSE)
                    ┌────────▼────────┐
                    │  testing.py     │
                    │  路由/并发/推送  │
                    └────────┬────────┘
                             │
              ┌──────────────▼──────────────┐
              │       adp_ops.py             │
              │                              │
   ┌──────────┤ 1. query_attachments()      │──→ dpportal API
   │          │ 2. call_adp_sse_stream()    │──→ ADP v2 SSE（含续接）
   │          │ 3. extract_adp_results()    │
   │          │ 3.5 download_adp_report()   │──→ agent.adp-cos.com
   │          │     upload_bitable_attachment│──→ 飞书 Drive API
   │          │ 4. save_adp_local()         │──→ docs/adp_results/
   │          │    _save_adp_fail_snapshot()│──→ 失败快照 md
   │          │ 5. write_adp_to_feishu()    │──→ 飞书 Bitable API
   │          └──────────────────────────────┘
   │
   │  ┌────────────────────────────────────────────────────────┐
   └──┤  本地存储                                               │
      │  {doc_dir}/adp_results/{jira_key}/                     │
      │    ├─ {jira_key}_full_analysis.md  (成功：完整分析报告) │
      │    ├─ {jira_key}_raw_data.json     (结构化原始数据)     │
      │    └─ {jira_key}_fail_{时间戳}.md  (失败：快照)         │
      │  reports/adp/{jira_key}/                               │
      │    └─ report_*.html                (HTML 报告原件)      │
      └────────────────────────────────────────────────────────┘

  前端按需读取：GET /api/test/adp_report?jira_key=xxx
```
