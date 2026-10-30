# AI 日志分析批量执行方法说明

> 文档版本：2026-10-30  
> 涉及文件：`src/api/routes/testing.py`、`src/api/routes/trigger.py`、`src/services/server_legacy.py`

---

## 一、整体架构

批量执行遵循 **三步解耦** 设计，每个阶段通过独立接口实现：

| 阶段 | 说明 | 前端入口 |
|------|------|---------|
| **① 搜索与过滤** | JQL 查询 / CSV 导入 / 直接输入 → 获取 Jira 号列表 | 查询条件区 |
| **② 触发时间提取** | 三级优先级提取 → 云端缓存 → 随机抽样去重 | 触发时间提取区 |
| **③ 并行批量执行** | 调用 AI 分析接口 → 结果记录 → 云端上传 | 执行按钮区 |

---

## 二、数据输入源

### 2.1 JQL 查询

前端预设 4 种快捷 JQL 按钮（均含 `project = VCS_Info4.0_High_Platform_PATAC_Jira` 过滤）：

| 预设名称 | JQL 条件 |
|----------|---------|
| 今日新增 Bug | `created >= startOfDay() AND issuetype = "bug" AND status != "closed"` |
| 昨日新增 Bug | `created >= startOfDay("-1d") AND created <= endOfDay("-1d") AND issuetype = "bug"` |
| 本周新增 Bug | `created >= startOfWeek() AND issuetype = "bug" AND status != "closed"` |
| 无触发时间标签 | `labels not in (trigger_time)` |

也支持用户自定义 JQL，最大返回 500 条。

### 2.2 CSV 导入

从功能 11（未分析 Bug 提取）的 CSV 文件中读取 `Jira号` 列。

### 2.3 直接输入

用户手动输入 Jira 号，支持逗号/分号/空格分隔。

---

## 三、过滤机制

### 3.1 重复过滤（多维表格）

查询飞书多维表格，跳过 **已执行成功** 或 **人工审核确认为无效** 的记录。判定依据：
- `分析结果` 字段为"成功"→ 跳过
- `人工审核结果` 字段标记为无效 → 跳过

### 3.2 按来源过滤

支持按触发来源定向过滤，两种模式互斥：

| 勾选项 | 含义 | 过滤逻辑 |
|--------|------|---------|
| 仅过滤线上的 | 跳过线上来源（`parseFullTicket`）的正确+通用失败 | `trigger_source != "jira_analyze"` 时跳过 |
| 仅过滤PC的 | 跳过PC来源（`jira_analyze`）的正确+通用失败 | `trigger_source == "jira_analyze"` 时跳过 |

> 同来源云端批量记录也会参与去重，PC 和线上允许交叉重复。

### 3.3 缓存跳过

勾选"跳过已有缓存"时，预加载云端触发时间缓存，已有触发时间的 Jira 号跳过提取步骤。

### 3.4 AI 初步分析过滤

勾选"过滤 AI 初步分析结果"时，并行检查 Jira 自定义字段 `customfield_13714`：
- 有值且非空 → 说明已有 AI 分析，跳过
- 为空或 `none/null` → 保留

### 3.5 无触发时间过滤

提取阶段完成后，无触发时间的 Jira 号自动排除，不进入执行队列。

---

## 四、触发时间提取

### 4.1 三级优先级提取管线

```
评论/字段提取（最快最准）→ 视频 OCR 兜底 → 图片 OCR 兜底 → 附件文件名兜底
```

| 优先级 | 方法 | 说明 |
|--------|------|------|
| 1 | `extract_trigger_time_from_issue` | 从 Jira 评论区 / 自定义字段提取，文本方式，准确率最高 |
| 2 | `_diag_extract_time_from_video_simple` | 视频封面+前 6 帧 OCR 识别时间 |
| 3 | `_diag_extract_time_from_images` | 图片附件 OCR 识别时间 |
| 4 | `extract_attachment_time` | 从附件文件名解析时间（最后兜底） |

### 4.2 前置检查

提取前先检查 `_has_gmlogger_logs()`：无 gmlogger 附件的 Jira 号直接跳过所有时间提取，返回 `None`（不写空标签到云端，下次仍可重试）。

### 4.3 云端缓存机制

提取优先级：**前端已传入 > 云端缓存 > 重新提取**

- 云端缓存命中 → 直接使用，不重复提取
- 云端空标记（`""`）→ 标记为"已知失败"，跳过
- 提取成功 → 写入云端缓存（`_save_trigger_time_to_cloud`），供后续复用
- 提取失败 → 写入空标记，避免反复重试

### 4.4 批量提取并发

提取阶段以 50 条为一批，每批 5 线程并发提取，进度每 20 条推送一次。

---

## 五、批量执行

### 5.1 执行模式

| 模式 | 接口 | 说明 |
|------|------|------|
| **PC 执行** | `/api/test/batch_ai_run` → `ai_log_api.url` | 调用本地 AI 分析服务 |
| **线上执行** | `/api/test/prod_batch_run` → `prod_ai.url` | 调用线上 `parseFullTicket` 接口 |

两种模式互斥，前端通过 `exec_mode` 参数控制。

### 5.2 并发控制

```python
_exec_concurrency = int(body.get("analysis_concurrency") or 5)
_exec_sem = threading.Semaphore(_exec_concurrency)
```

- **默认并发数**：PC=10、线上=5（可在配置区调整）
- 通过 `Semaphore` 控制同时执行的请求数
- 所有任务通过 `loop.run_in_executor()` 在线程池中并行执行

### 5.3 失败重试

```python
_MAX_RETRIES = 1   # 失败后重试次数
_RETRY_DELAY = 3   # 重试间隔（秒）
```

- **仅异常重试**：HTTP 请求抛异常（超时、连接失败）时重试，业务失败（接口返回非 200）不重试
- PC 模式额外校验：响应 `msg` 需包含 `分析任务已启动` / `后台处理` / `正在分析`

### 5.4 结果记录

执行完成后自动生成 CSV 记录，保存到 `data/unanalyzed/` 目录：

```
prod_batch_{日期}_{时间}.csv
```

CSV 字段：`Jira号, 执行结果, 触发时间, 执行时间, 备注, 分析并发数, 下载并发数, 模型, 触发来源`

同时上传至飞书云端文件夹，标题格式：`线上批量执行 {日期} {时间} ({成功数}/{总数})`

### 5.5 内存级去重

```python
_mark_executed(run_bugids)
```

执行完成后将 Jira 号标记到内存集合，防止下一批次因多维表格尚未更新导致重复执行。

---

## 六、持续执行模式

### 6.1 概述

持续执行模式仅通过 **飞书机器人**（功能 6.1.1 → 选项 3）触发，适用于大批量长时执行场景。

### 6.2 参数配置

| 参数 | 范围 | 默认值 | 说明 |
|------|------|--------|------|
| `count` | 任意正整数 | 用户输入 | 每轮执行的 Jira 数量 |
| `interval_min` | 1~120 分钟 | 10 | 轮间等待时间 |
| `total_rounds` | 2~100 轮 | 5 | 总执行轮数 |
| `batch_count` | — | 同 count | 持续模式下每轮数量 |

### 6.3 执行流程

```
第1轮 → 等待 interval_min → 第2轮 → ... → 第N轮
```

每轮执行逻辑：
1. JQL 搜索获取候选 Jira 号
2. 排除跨轮已执行的 `executed_set`
3. 过滤（多维表格 + 来源）
4. 提取触发时间
5. 执行 AI 分析
6. 本轮新增的 Jira 号加入 `executed_set`

### 6.4 提前终止条件

- **用户取消**：发送"退出"消息 → `_is_cancelled()` 返回 True → 完成当前 Jira 后终止
- **数据不足**：本轮实际执行数 < 目标数量 → 自动停止后续轮次

### 6.5 轮间等待

等待期间每秒检查取消标记，支持随时中断：

```python
for _ in range(interval_min * 60):
    if _is_cancelled(chat_id):
        break
    _time.sleep(1)
```

---

## 七、中断与停止机制

### 7.1 前端停止

- **触发时间提取**：`stop_event` + `AbortSignal`，完成当前 Jira 后在下一条前终止
- **批量执行**：`request.is_disconnected()` 检测浏览器断开 → `stop_event.set()` → 工作线程退出

### 7.2 机器人停止

发送"退出"消息 → `_is_cancelled(chat_id)` → 每条任务执行前后检查取消标记

### 7.3 设计原则

> **当前 Jira 号必须完成完整处理**（提取、分析、保存），然后在下一个条目前终止，避免数据不一致或中途崩溃。

---

## 八、SSE 事件流

批量执行通过 SSE（Server-Sent Events）实时推送进度，前端通过 `EventSource` 或 `fetch + ReadableStream` 接收。

### 8.1 线上批量执行（`prod_batch_run`）

| 事件类型 | 触发时机 | 关键字段 |
|----------|---------|---------|
| `start` | 执行开始 | `total, dedup, skipped, raw, max_count, need_fetch` |
| `extract_progress` | 提取进度 | `current, total, hit` |
| `extract_done` | 提取完成 | `total, with_time, without_time, skip_empty_mark` |
| `progress` | 每条执行完成 | `index, total, bugid, status, msg, exec_time` |
| `done` | 全部完成 | `total, success, fail, dedup, skipped, csv_path, cloud_url` |

### 8.2 功能测试批量执行（`batch_ai_run`）

| 事件类型 | 触发时机 | 关键字段 |
|----------|---------|---------|
| `start` | 执行开始 | `total` |
| `item_done` | 每条执行完成 | `jira号, 执行结果, 报告长度, 备注` |
| `done` | 全部完成 | 汇总统计 + CSV 路径 |

---

## 九、配置参数

| 参数 | 默认值（PC/线上） | 说明 |
|------|-------------------|------|
| `analysis_concurrency` | 10 / 5 | AI 分析并发数 |
| `download_concurrency` | 4 / 2 | 附件下载并发数 |
| `model` | `deepseek-v-pro` | 分析模型 |
| `trigger_source` | PC / 线上 | 触发来源标识 |

---

## 十、关键代码入口

| 功能 | 文件 | 函数/路由 |
|------|------|----------|
| 线上批量执行 | `testing.py` | `test_prod_batch_run()` → `/api/test/prod_batch_run` |
| 功能测试批量执行 | `testing.py` | `test_batch_ai_run()` → `/api/test/batch_ai_run` |
| 触发时间批量提取 | `trigger.py` | `batch_extract_trigger()` → `/api/trigger/batch_extract` |
| 机器人单次执行 | `server_legacy.py` | `_bot_run_batch_ai()` |
| 机器人持续执行 | `server_legacy.py` | `_bot_run_batch_ai_continuous()` |
| 机器人单轮执行 | `server_legacy.py` | `_bot_run_batch_ai_single_round()` |
| 内存级去重标记 | `testing.py` | `_mark_executed()` / `_get_same_source_executed_keys()` |
