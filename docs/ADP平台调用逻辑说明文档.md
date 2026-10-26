# ADP 调用逻辑（简版）

> 实现见 `src/services/adp_ops.py`，端点见 `src/api/routes/testing.py`。

## 做什么

给一个 Jira 号，把日志附件交给 ADP 流式分析，取回结论、下载 HTML 报告，落到本地与飞书多维表格。

## 流程

1. **查附件**（dpportal）：只认压缩包和 txt/log，且必须有下载链接
2. **拼消息**：Jira 号 + 描述 + 触发时间 + 各附件下载链接
3. **调 ADP SSE**：增量收全文；流结束仍无报告且本次耗时 >5 分钟时，续接最多 2 轮（每轮 5 分钟）
4. **提取 6 字段**：完成状态 / 报告链接 / 置信度 / 耗时 / 问题模块 / root cause
5. **报告落盘**：下载 HTML → 传飞书换 `file_token`（报告链接是附件字段，必须用 token）
6. **写回飞书**：按 `Jira链接` 找记录（无则新建），只写上述 6 个字段
7. **本地保存**：`docs/adp_results/{key}/` 下 `_full_analysis.md` + `_raw_data.json`；异常时存 `_fail_{时间戳}.md`

## 给前端什么

只回**预览**，不回全文：`text_len`、`text_preview`（前 2000 字）、`report_path`、`fail_type`、`results`、`file_urls`。
完整文本按需打开：`GET /api/test/adp_report?jira_key=VCU-xxx`（无主报告时回退最新失败快照）。

## 失败类型（fail_type）

输入质量问题（无附件 / 无有效日志 / 链接为空 / 描述不清）、ADP连接超时或网络异常、下载链接失效、分析过程未完成、分析完成但未产出HTML报告、`处理异常: xxx`、飞书写入失败、ADP 分析超时。

## 端点

| 端点 | 用途 |
|---|---|
| `POST /api/test/adp_single` | 单条分析 |
| `POST /api/test/adp_batch` | 批量导入 |
| `POST /api/test/adp_lookup` | 多维表格查找后批量跑（已接入 `/api/jobs`） |
| `POST /api/test/adp_enrich` | 补全描述/触发时间 |
| `POST /api/test/adp_lookup/stop` | 停止表格查找 |
| `GET /api/test/adp_report` | 看完整报告 |

## 关键参数

并发 2；SSE 超时 3600s（connect 30s / read 60s）；连接失败重试 3 次（10/20/30s）；心跳 30s；迟到续接 300s×2 轮；报告下载 120s；预览截断 2000 字。

## 三个坑

1. 报告链接是**附件字段**：必须 `[{"file_token": token}]`，写 URL 会报 `AttachFieldConvFail`；拿不到 token 就删掉该字段。
2. **全文只落盘**，SSE/JSON 里只有预览，避免几十 MB 响应拖死页面。
3. 失败也会留 `_fail_*.md` 快照，所以失败时前端同样能点「查看完整报告」。
