# ADP 平台调用逻辑说明

> 最后更新：2026-10-26
> 实现细节看 `src/services/adp_ops.py`（核心链路）与 `src/api/routes/testing.py`（ADP 端点）。

## 一、总览

```
前端 AdpTestPanel
  ├─ 单条   POST /api/test/adp_single
  ├─ 批量   POST /api/test/adp_batch
  ├─ 查表   POST /api/test/adp_lookup   (已接入作业模型)
  ├─ 补全   POST /api/test/adp_enrich
  └─ 报告   GET  /api/test/adp_report?jira_key=VCU-xxx

核心链路 (adp_ops.py)
  查附件 → 拼消息 → ADP SSE 流式分析 → 提取 6 字段 → 下载 HTML 报告并上传飞书附件
        → 本地保存（异常时存失败快照） → 写飞书多维表格
```

## 二、配置（config.yaml → `adp` 段）

```yaml
adp:
  app_key: ...                  # ADP API Key
  url: https://wss.lke.cloud.tencent.com/adp/v2/chat
  sandbox_base: https://sandbox.adp.cloud.tencent.com/files?path=
  attach_api: https://dpportal.apps.saic-gm.com/api/logAnalysis/attachments
  attach_api_key: ...
  timeout: 3600                 # 单次分析超时（秒）
  bitable_app_token: ...        # ADP 结果多维表格
  bitable_table_id: ...
  bitable_view_id: ""           # 可选
  jira_field: Jira链接           # 匹配记录的字段
  save_dir: docs/adp_results    # 本地保存目录
```

## 三、流程

| 步骤 | 做什么 | 失败/降级 |
|---|---|---|
| 1. 查附件 | `POST dpportal` 按 `jiraKey` 取附件；只认压缩包(zip/z01/rar/7z/tar/gz/bz2/xz/tgz)和 txt/log，且必须有 downloadUrl | 无附件 → `无法分析 / 输入质量问题（无附件）`；有附件无日志 → `无法分析 / 无有效日志文件` |
| 2. 拼消息 | `JIRA号X，描述:…，触发时间:…` + 每个有效附件的下载链接与大小 | — |
| 3. SSE 分析 | `POST adp/v2/chat`，`Incremental/Stream/StreamingThrottle=5`；`text.delta` 累积全文、`text.replace` 取 closeout JSON、`content.added(Type=file)` 收文件；每 30s 心跳 | 连接级错误（且尚未收到文本）最多重试 3 次，退避 10/20/30s |
| 3b. 迟到续接 | 流结束但仍无 HTML 报告、且本次流耗时 >300s → 最多 2 轮 × 5 分钟，换新 RequestId 重连继续追加 | 出现报告或本轮无新增即停止 |
| 4. 提取字段 | 从全文+closeout 提 6 个字段（完成状态/报告链接/置信度/耗时/问题模块/root cause）；报告链接按 4 级优先级取（agent.adp-cos.com → file_urls 里的 .html → sandbox 拼接 → 其它 report_*.html） | 无报告 → `分析失败 / 分析完成但未产出HTML报告`（保留已提取字段） |
| 5. 报告落盘 | 下载 HTML 到 `reports/adp/{key}/`（120s，跟随重定向），再用 `upload_bitable_attachment` 传飞书拿 `file_token`；HTML 里的"断点模块"会覆盖问题模块 | 下载/上传失败 → `file_token` 为空，报告链接字段从写入字段中移除 |
| 6. 本地保存 | `{doc_dir}/adp_results/{key}/`：`{key}_full_analysis.md`（完整报告）+ `{key}_raw_data.json`（结构化原始数据） | 步骤 3~6 抛异常 → 写失败快照 `{key}_fail_{时间戳}.md`（含完整返回内容） |
| 7. 写飞书 | 按 `jira_field` 找记录（无则新建），只写白名单 6 字段；报告链接必须是 `[{"file_token": token}]` | 写入异常只记录日志；分析成功但写入失败 → `fail_type=飞书写入失败` |

## 四、返回给前端什么

**只回预览，不回全文**（全文可能几 MB）：

| 字段 | 说明 |
|---|---|
| `text_len` / `text_preview` | 全文长度 / 前 2000 字 |
| `report_path` | 落盘路径（成功 `_full_analysis.md`，异常 `_fail_时间戳.md`） |
| `fail_type` | 失败类型；成功为空 |
| `results` | 提取的 6 个字段（含 `分析失败归因`） |
| `file_urls` / `feishu` / `elapsed` / `attachment_count` | 附件链接 / 飞书写入结果 / 耗时 / 附件数 |

前端「查看完整报告」= `GET /api/test/adp_report?jira_key=`（校验 key 白名单，主读 `_full_analysis.md`，没有则回退最新的 `_fail_*.md`）。

## 五、失败类型（fail_type）

| 类型 | 触发 |
|---|---|
| 输入质量问题（无附件 / 无有效日志文件 / 日志附件链接为空 / 描述矛盾或信息不足） | 前置条件不满足，或短文本里要求补充 |
| ADP连接超时或网络异常 | 无返回、连接超时 |
| 下载链接失效（普通 / 传输中断 / 签名URL响应异常） | 404、rc=18+残件、expect=46 |
| 分析过程未完成 | 文本 >3000 字但只到下载/解包/索引阶段 |
| 分析完成但未产出HTML报告 | 默认兜底 |
| 处理异常: xxx | 步骤 3~6 抛异常 |
| 飞书写入失败 | 分析成功、写表失败 |
| ADP 分析超时 | 表格查找批次超时 |

取值顺序：`results.分析失败归因` → `out.fail_type` → 若完成状态=完成则`飞书写入失败` → 否则自动归类。

## 六、接口

| 端点 | 说明 |
|---|---|
| `POST /api/test/adp_single` | 单条分析，SSE：`step` / `keepalive` / `done` |
| `POST /api/test/adp_batch` | 批量导入，`batch_size` 默认 2，单批 600s，SSE：`dedup`/`start`/`batch_start`/`item_done`/`batch_done`/`done` |
| `POST /api/test/adp_lookup` | 表格查找（manual/auto），`skip_feishu` 后统一 `_write_back`；deadline=`timeout+120`；已注册作业 |
| `POST /api/test/adp_enrich` | 补全描述/触发时间，并发 5 |
| `POST /api/test/adp_lookup/stop` | 置位停止信号，当前批次后停止 |
| `GET /api/test/adp_report` | 读取完整报告（内联 markdown，失败回退快照） |
| `POST /api/jobs/{id}/stop` | 作业级停止（adp_lookup 已接入 `/api/jobs`） |

## 七、关键参数

| 参数 | 值 |
|---|---|
| 并发 | batch_size 默认 2；补全并发 5 |
| SSE 超时 | 3600s（connect 30s / read 60s） |
| SSE 重试 | 3 次，退避 10/20/30s（仅连接级、未收到文本） |
| 心跳 | 30s |
| 迟到续接 | 门槛 300s，2 轮 × 300s |
| 报告下载 | 120s |
| 批次 deadline | batch 600s；lookup timeout+120s |
| 预览截断 | 2000 字 |

## 八、几个必须知道的坑

1. **报告链接字段是附件类型**：必须写 `[{"file_token": token}]`，写 URL 字符串会 `AttachFieldConvFail`；拿不到 token 就把该字段去掉。
2. **全文只落盘、不回传**：SSE/JSON 里只有 `text_preview`，避免超大响应把页面拖死。
3. **失败也要留证据**：异常路径会写 `_fail_时间戳.md`，所以失败时前端同样能看「查看完整报告」。
4. **停止信号是流程独立的**：`/api/test/adp_lookup/stop` 只影响表格查找，不影响回归/表单/时间提取。
