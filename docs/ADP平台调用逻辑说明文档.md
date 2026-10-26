# ADP 平台调用逻辑说明文档

> 最后更新：2026-10-26

## 一、架构总览

```
前端 AdpTestPanel.vue
  ├─ 单条分析  → POST /api/test/adp_single
  ├─ 批量执行  → POST /api/test/adp_batch   (Excel/CSV 导入)
  ├─ 表格查找  → POST /api/test/adp_lookup  (多维表格自动查找)
  ├─ 补全字段  → POST /api/test/adp_enrich  (补全描述/触发时间)
  └─ 停止执行  → POST /api/test/adp_lookup/stop

后端 API (testing.py)
  ├─ 参数解析 + 并发控制 (ThreadPoolExecutor, batch_size=2)
  ├─ SSE 流式推送进度到前端
  └─ 调用 adp_ops.py 核心函数链

核心函数链 (adp_ops.py)
  Step 1  query_attachments()       → dpportal 查附件
  Step 2  build_adp_message()       → 构建入参消息
          call_adp_sse_stream()     → ADP v2 SSE 流式分析
  Step 3  extract_adp_results()     → 提取 6 个字段
  Step 3.5 download_adp_report()    → 下载 HTML 报告 + 上传飞书附件
  Step 4  save_adp_local()          → 保存本地 MD + JSON
  Step 5  write_adp_to_feishu()     → 写入飞书多维表格
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
  jira_field: Jira链接          # 用于匹配记录的字段名
  save_dir: docs/adp_results   # 本地结果保存目录
```

## 三、核心流程详解

### Step 1：查询附件（query_attachments）

```
输入: Jira号 (如 VCU-512009)
接口: POST https://dpportal.apps.saic-gm.com/api/logAnalysis/attachments
请求: {"jiraKey": "VCU-512009"}  + X-API-Key 认证
输出: [{filename, downloadUrl, size, ...}, ...]
超时: 30s
过滤: 仅保留压缩包(.zip/.rar/.7z/.tar.gz等)和文本文件(.txt/.log)
```

- 无附件 → 返回 `{"完成状态": "无法分析"}`，流程终止
- 有附件但无有效日志附件 → 同上，附提示"没有日志附件（已有: xxx）"

### Step 2：构建消息 + 调用 ADP SSE

#### 2a. 构建入参消息（build_adp_message）

```
格式:
  JIRA号VCU-512009，描述: {description}，触发时间: {trigger_time}
  日志附件下载链接：
  - filename1 (12.3MB): https://downloadUrl1
  - filename2 (5.6MB): https://downloadUrl2
```

#### 2b. SSE 流式调用（call_adp_sse_stream）

```
接口: POST https://wss.lke.cloud.tencent.com/adp/v2/chat
请求体:
  {
    RequestId: uuid,
    ConversationId: uuid,
    AppKey: config.app_key,
    VisitorId: "jira_analysis_user",
    Contents: [{Type: "text", Text: message}],
    Incremental: true,
    Stream: "enable",
    StreamingThrottle: 5
  }
超时: 3600s (connect=30s)
重试: 最多 3 次（仅连接级错误，已收到数据不重试）
退避: wait = 10 * attempt 秒
```

**SSE 事件类型处理：**

| 事件 Type | 处理逻辑 |
|-----------|----------|
| `response.created` | 记录 start_ts |
| `text.delta` | 追加到 full_text（修复 latin-1→UTF-8 编码） |
| `text.replace` | 检测 closeout JSON（含 "ok" + "html"） |
| `content.added` (Type=file) | 收集到 file_urls 列表 |
| `[DONE]` | 流结束标记 |

**心跳机制：** 每 30s 调用 `keepalive_cb(elapsed_sec)`，前端 SSE 推送保活

**输出：** `(full_text, file_urls, closeout_data, start_ts, end_ts)`

### Step 3：提取分析结果（extract_adp_results）

从 `full_text` 和 `closeout_data` 中提取 **6 个字段**：

| 字段名 | 提取逻辑 |
|--------|----------|
| 完成状态 | 固定为 "完成"（无返回时由上层设为 "无法分析"/"分析失败"） |
| 报告链接 | 4 级优先级提取（见下文） |
| 置信度 | 优先 closeout_data → 文本正则提取 → 规范化校验 |
| 耗时(分) | `(end_ts - start_ts) / 1000 / 60` |
| agent分析的问题模块 | 正则匹配 ADP 专有格式 |
| agent分析的root cause | 正则匹配根因归属/现象级归因 |

**报告链接 4 级提取优先级（_extract_report_url）：**

```
1. 文本中 agent.adp-cos.com 链接 (签名有效期 ~90天，最可靠)
2. file_urls 中的 .html 文件 (排除 meta 文件)
3. closeout_data 拼 sandbox 路径 (签名有效期短，易 401)
4. 文本中其他 report_*.html URL
```

### Step 3.5：下载 HTML 报告 + 上传附件（download_adp_report）

```
1. 下载: GET report_url → 保存到 reports/adp/{jira_key}/
2. 上传: feishu_client.upload_bitable_attachment(app_token, local_path)
         → 飞书 Drive media upload API (parent_type=bitable_file)
         → 返回 file_token
3. 失败处理: 无 file_token 时从写入字段中移除报告链接
            (避免 URL 字符串写入附件类型字段导致 AttachFieldConvFail)
超时: 120s
```

### Step 4：保存本地文件（save_adp_local）

```
保存路径: docs/adp_results/{jira_key}/
文件:
  - {jira_key}_full_analysis.md  (完整分析报告，含入参/提取结果/closeout/file_urls/全文)
  - {jira_key}_raw_data.json     (结构化原始数据，供后续重放/排查)
```

### Step 5：写入飞书多维表格（write_adp_to_feishu）

```
1. 查找: list_bitable_records → 按 jira_field 匹配 Jira号
2. 不存在则新建: batch_create_records
3. 写入 6 个字段:
   - allowed = ["完成状态", "报告链接（分析报告、可观测报告）", "耗时(分)",
                "agent分析的问题模块", "agent分析的root cause", "置信度"]
   - 报告链接字段: 有 file_token → [{"file_token": token}]
                   无 file_token → 从写入字段中 pop 掉
4. update_bitable_records 写入
```

## 四、API 端点详解

### 4.1 单条分析 `/api/test/adp_single`

```
输入: {bugid: "VCU-xxx"}
流程: Jira API 获取描述/触发时间 → run_adp_single() → SSE 推送进度
输出: SSE 流式事件
```

### 4.2 批量执行 `/api/test/adp_batch`

```
输入: {items: [{bugid, description, trigger_time}], batch_size: 2, continuous: false}
流程:
  1. 按 batch_size 分批
  2. 每批内并发执行 (ThreadPoolExecutor)
  3. 非阻塞轮询等待 + 5s 心跳
  4. 连续模式: 完成一批立即开始下一批
输出: SSE 流式事件 (batch_start / item_done / keepalive / batch_done)
```

**关键参数：**
- `batch_size` 默认 2（可通过前端调整，最大 10）
- 批次 deadline = `timeout + 120s` (留 2 分钟余量)
- 失败不重试，直接标记"分析失败"

### 4.3 表格查找 `/api/test/adp_lookup`

```
输入: {mode: "manual"|"auto", bugids: [...], limit: 10}
流程:
  1. manual: 使用传入的 bugids
     auto:   从多维表格查找"完成状态"为空的记录，取前 limit 条
  2. Jira API 补全 description + trigger_time
  3. 按 batch_size=2 并发执行
  4. 每条完成后立即 _write_back 写回多维表格
  5. 支持 Ctrl+C 停止信号
输出: SSE 流式事件
```

**_write_back 写回逻辑：**
- `ok=true` 或 状态为"无法分析"/"分析失败" → 允许写回
- 其他失败 → 跳过写回
- 报告链接：有 file_token 写入附件格式，无则 pop 掉

### 4.4 补全字段 `/api/test/adp_enrich`

```
输入: {bugids: ["VCU-xxx", ...]}
流程: 并发 (5路) 调用 Jira API 获取 description + trigger_time
输出: [{bugid, description, trigger_time}, ...]
```

### 4.5 停止执行 `/api/test/adp_lookup/stop`

```
功能: 设置 stop_event，当前批次完成后停止
```

## 五、前端 SSE 事件协议

| 事件 type | 含义 | 数据 |
|-----------|------|------|
| `batch_start` | 批次开始 | `{batch, items}` |
| `item_start` | 单条开始 | `{bugid}` |
| `progress` | 步骤进度 | `{step, status, detail}` |
| `keepalive` | 心跳保活 | `{elapsed}` 或 `{running: []}` |
| `item_done` | 单条完成 | `{bugid, ok, results, feishu, elapsed}` |
| `batch_done` | 批次结束 | `{batch, success, fail, skip}` |
| `all_done` | 全部完成 | `{total, success, fail, skip}` |
| `error` | 错误 | `{message}` |

## 六、关键参数汇总

| 参数 | 值 | 位置 | 说明 |
|------|------|------|------|
| 并发数 | 2 | testing.py | batch_size 默认值 |
| SSE 超时 | 3600s | config.yaml | 单次 ADP 分析超时 |
| SSE 连接超时 | 30s | adp_ops.py | connect timeout |
| SSE 重试 | 3 次 | adp_ops.py | 仅连接级错误 |
| 重试退避 | 10/20/30s | adp_ops.py | wait = 10 * attempt |
| 心跳间隔 | 30s | adp_ops.py | keepalive 回调 |
| StreamingThrottle | 5 | adp_ops.py | SSE 流式节流 |
| 报告下载超时 | 120s | adp_ops.py | HTML 报告下载 |
| 附件查询超时 | 30s | adp_ops.py | dpportal 请求 |
| 批次 deadline | 3720s | testing.py | timeout + 120s |
| 心跳轮询 | 5s | testing.py | SSE sleep 间隔 |
| 自动模式 limit | 10 条 | testing.py | auto 模式默认 |

## 七、错误处理与降级

| 场景 | 处理 |
|------|------|
| 无附件 | 标记"无法分析"，不写回 |
| 无有效日志附件 | 标记"无法分析"，提示已有文件类型 |
| ADP 无返回 | 标记失败，不写回 |
| SSE 连接失败 | 最多重试 3 次（指数退避） |
| SSE 已收到数据后断连 | 不重试，返回已收数据 |
| 报告下载 401 | file_token 为空，报告链接字段 pop 掉 |
| 报告链接写入附件字段 | 必须用 file_token 格式，URL 字符串会触发 AttachFieldConvFail |
| 飞书写入异常 | 捕获异常，记录日志，本地数据已保存可重放 |
| 分析失败 | 标记"分析失败"，允许写回状态字段 |

## 八、数据流向图

```
                    ┌─────────────────┐
                    │   前端 Vue      │
                    │  AdpTestPanel   │
                    └────────┬────────┘
                             │ POST (SSE)
                    ┌────────▼────────┐
                    │  testing.py     │
                    │  API 路由层     │
                    │  并发控制/推送  │
                    └────────┬────────┘
                             │
              ┌──────────────▼──────────────┐
              │       adp_ops.py             │
              │                              │
   ┌──────────┤ 1. query_attachments()      │──→ dpportal API
   │          │ 2. call_adp_sse_stream()    │──→ ADP v2 SSE
   │          │ 3. extract_adp_results()    │
   │          │ 3.5 download_adp_report()   │──→ agent.adp-cos.com
   │          │     upload_bitable_attachment│──→ 飞书 Drive API
   │          │ 4. save_adp_local()         │──→ docs/adp_results/
   │          │ 5. write_adp_to_feishu()    │──→ 飞书 Bitable API
   │          └──────────────────────────────┘
   │
   │  ┌────────────────────────────────────────────────┐
   └──┤  本地存储                                       │
      │  docs/adp_results/{jira_key}/                  │
      │    ├─ {jira_key}_full_analysis.md  (分析报告)   │
      │    └─ {jira_key}_raw_data.json    (结构化数据)  │
      │  reports/adp/{jira_key}/                       │
      │    └─ report_full_*.html          (HTML 报告)   │
      └────────────────────────────────────────────────┘
```
