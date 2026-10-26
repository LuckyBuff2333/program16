# 测试管理平台功能全景：四大维度梳理

## 一、总体架构概览

平台围绕 **"AI 日志分析 → 缺陷诊断 → 质量闭环"** 核心理念，划分为四大功能维度：

```
┌──────────────┐  ┌──────────────┐  ┌──────────────┐  ┌──────────────────┐
│  测试设计中心  │→│  测试执行中心  │→│  缺陷反馈中心  │→│  质量分析与决策    │
│              │  │              │  │              │  │                  │
│ · JQL 搜索    │  │ · 单Jira分析  │  │ · 排查诊断    │  │ · 日报/周报/汇总  │
│ · CSV 导入    │  │ · 批量执行    │  │ · 根因提取    │  │ · 质量抽查复核    │
│ · 去重过滤    │  │ · 触发时间提取 │  │ · 评论分析    │  │ · 置信度评估     │
│ · 随机抽样    │  │ · 文档生成    │  │ · 置信度判定   │  │ · 参数调优分析   │
│ · 时间预提取  │  │ · 知识库入库  │  │ · 多维表格回写 │  │ · 数据看板       │
└──────────────┘  └──────────────┘  └──────────────┘  └──────────────────┘
```

---

## 二、测试设计中心

> **定位：** 测试执行前的准备工作，包括候选 Bug 筛选、去重、抽样、触发时间预提取，确保执行阶段高效精准。

### 2.1 JQL 搜索候选 Bug

| 项目 | 说明 |
|------|------|
| **功能** | 通过 Jira JQL 查询语句批量搜索候选 Bug，自动过滤仅保留 VCU 项目 |
| **接口** | `POST /api/test/batch_ai_search` |
| **代码** | [testing.py#L185-L210](file:///d:/工作/工作/AI/testplatform/program16/src/api/routes/testing.py#L185-L210) |
| **特性** | 支持最多 5000 条结果返回；自动过滤非 VCU 项目；展示 key、摘要、状态、创建日期 |

### 2.2 CSV 文件导入

| 项目 | 说明 |
|------|------|
| **功能** | 从本地 CSV 文件导入 Jira 号列表及触发时间，自动去重 |
| **接口** | `GET /api/test/batch_ai_csv_files`（列出可用文件）<br>`POST /api/test/batch_ai_csv_import`（导入） |
| **代码** | [testing.py#L123-L182](file:///d:/工作/工作/AI/testplatform/program16/src/api/routes/testing.py#L123-L182) |
| **特性** | 兼容多种列名（Jira号/jira号/JIRA号）；自动提取触发时间列；输出重复统计 |

### 2.3 多维表格去重过滤

| 项目 | 说明 |
|------|------|
| **功能** | 查询飞书多维表格，过滤掉已分析成功/已处理的记录，避免重复执行 |
| **接口** | `POST /api/test/batch_ai_filter` |
| **代码** | [testing.py#L542-L625](file:///d:/工作/工作/AI/testplatform/program16/src/api/routes/testing.py#L542-L625) |
| **过滤模式** | ① 智能过滤（默认）：排除成功+无需重试<br>② 全量过滤：排除所有已存在<br>③ PC来源过滤：仅排除 PC 触发来源<br>④ 线上来源过滤：仅排除线上触发来源<br>⑤ AI 初步分析过滤：排除已成功+无效审核 |

### 2.4 随机抽样

| 项目 | 说明 |
|------|------|
| **功能** | 从候选列表中按指定数量随机抽取，优先使用云端已有触发时间的记录 |
| **接口** | `POST /api/test/batch_ai_sample` |
| **代码** | [testing.py#L628-L758](file:///d:/工作/工作/AI/testplatform/program16/src/api/routes/testing.py#L628-L758) |
| **特性** | 扫描 `docs/` 全量 CSV 排除已测试记录；云端触发时间优先；不够时逐批从 Jira 提取；提取失败自动跳过不阻断 |

### 2.5 触发时间批量预提取

| 项目 | 说明 |
|------|------|
| **功能** | 对候选 Bug 批量提取触发时间（日志分析所需的起始时间点），支持 SSE 实时进度推送 |
| **接口** | `POST /api/test/batch_ai_extract_times`<br>`POST /api/test/batch_ai_extract_times/stop`（停止） |
| **代码** | [testing.py#L266-L539](file:///d:/工作/工作/AI/testplatform/program16/src/api/routes/testing.py#L266-L539) |
| **提取策略** | 云端缓存命中 → 视频附件 OCR 提取（可选兜底） → Jira 评论正则匹配 → 空标记 |
| **并发控制** | 支持串行/并行（8路并发）两种模式；OCR 并发限制 2 路（GPU 显存保护） |
| **容错** | Ctrl+C 优雅中断；前端断开自动停止；每 20 条批量写入云端；提取失败保留旧缓存 |

### 2.6 触发时间自学习（TimeStudy）

| 项目 | 说明 |
|------|------|
| **功能** | 对历史触发时间提取记录做深度分析：错误模式统计、顽固 Jira 检测、流水线断点溯源，辅助优化提取策略 |
| **接口** | `POST /api/timestudy/analyze`（分析）<br>`GET /api/timestudy/summary`（摘要）<br>`GET /api/timestudy/records`（记录）<br>`POST /api/timestudy/root-causes`（根因查询） |
| **代码** | [timestudy.py](file:///e:/program23/src/api/routes/timestudy.py)（路由）<br>[trigger_ops.py](file:///e:/program23/src/services/trigger_ops.py)（记录写入+上下文）<br>[server_legacy.py#_timestudy_analyze](file:///e:/program23/src/services/server_legacy.py)（深度分析） |
| **特性** | 统计成功率、错误分布、顽固 Jira、共性特征分类（系统性/顽固/偶发）、流水线断点分析、常见路径统计 |
| **文档** | [timestudy/README.md](file:///e:/program23/timestudy/README.md)（功能说明）<br>[timestudy/optimization_log.md](file:///e:/program23/timestudy/optimization_log.md)（提取优先级+历史变更记录） |
| **数据** | `data/timestudy/records.csv`（原始记录）<br>`data/timestudy/error_patterns.json`（分析结果）<br>`reports/timestudy/optimization_log.md`（可读报告） |

### 2.7 已成功 Jira 号过滤

| 项目 | 说明 |
|------|------|
| **功能** | 查询多维表格，区分 PC 来源和线上来源的已成功分析记录，供前端精确过滤 |
| **接口** | `POST /api/test/filter_success_jiras` |
| **代码** | [testing.py#L223-L264](file:///d:/工作/工作/AI/testplatform/program16/src/api/routes/testing.py#L223-L264) |

### 2.8 未验证 Jira 号提取

| 项目 | 说明 |
|------|------|
| **功能** | 从多维表格提取所有"分析结果=成功"但置信度为空的记录，识别需要补充验证的 Bug |
| **接口** | `POST /api/bitable/unverified_jiras` |
| **代码** | [bitable.py](file:///d:/工作/工作/AI/testplatform/program16/src/api/routes/bitable.py) |

---

## 三、测试执行中心

> **定位：** 核心分析引擎，从单 Bug 分析到批量并行执行，覆盖 AI 日志分析、文档生成、知识库入库的全执行链路。

### 3.1 单 Bug 全流程执行

| 项目 | 说明 |
|------|------|
| **功能** | 对单个 Bug 执行完整 4 步流程：AI 日志分析 → 结果查看 → 置信度判断 → 写入报表，SSE 实时推送每步结果 |
| **接口** | `POST /api/flow/single`（SSE 流式）<br>`POST /api/flow/stop/{bugid}`（取消）<br>`GET /api/flow/check/{bugid}`（检查状态） |
| **代码** | [flow.py#L69-L152](file:///d:/工作/工作/AI/testplatform/program16/src/api/routes/flow.py#L69-L152)，[pipeline.py#L456-L729](file:///d:/工作/工作/AI/testplatform/program16/src/pipeline.py#L456-L729) |
| **4 步流程** | **Step 1** AI 日志分析：Jira 状态检查 → 触发时间提取 → 去重 → AI 接口调用<br>**Step 2** 执行结果查看：确认文档生成成功<br>**Step 3** 置信度判断：飞书文档获取 + Rootcause + 评论总结 + 置信度计算<br>**Step 4** 写入完成：生成当日 CSV 报表 |

### 3.2 批量并行执行

| 项目 | 说明 |
|------|------|
| **功能** | 并行批量调用 AI 日志分析接口，SSE 实时推送每个完成结果，完成后自动生成批次 CSV 并上传云端 |
| **接口** | `POST /api/test/batch_ai_run` |
| **代码** | [testing.py#L759-L910](file:///d:/工作/工作/AI/testplatform/program16/src/api/routes/testing.py#L759-L910) |
| **特性** | 可配置分析并发数/下载并发数/模型/触发来源；自动从云端补全缺失触发时间；生成 `batch_HHMMSS.csv`；上传飞书云盘 |

### 3.3 AI 日志分析接口测试

| 项目 | 说明 |
|------|------|
| **功能** | 单独测试 AI 日志分析接口：阶段 1 验证接口响应字段，阶段 2 异步监听飞书通知获取分析完成卡片 |
| **接口** | `POST /api/test/ai_analyze` |
| **代码** | [testing.py#L42-L122](file:///d:/工作/工作/AI/testplatform/program16/src/api/routes/testing.py#L42-L122) |
| **验证项** | code=200、issue_key 一致、msg 含"已启动"；异步监听飞书对话获取完成通知 |

### 3.4 内容补充流程

| 项目 | 说明 |
|------|------|
| **功能** | 接收表格行数据，对缺失字段执行补充填充（触发时间、AI 报告、评论总结、根因、置信度） |
| **接口** | `POST /api/analyze` |
| **代码** | [flow.py#L24-L41](file:///d:/工作/工作/AI/testplatform/program16/src/api/routes/flow.py#L24-L41)，[pipeline.py#L960-L999](file:///d:/工作/工作/AI/testplatform/program16/src/pipeline.py#L960-L999) |
| **规则** | 重复 bugid 且 5 字段全有值才跳过，其余走补充流程；每步失败不阻断后续 |

### 3.5 失败重试

| 项目 | 说明 |
|------|------|
| **功能** | 对失败 Bug 重新走完整补充流程 |
| **接口** | `POST /api/retry` |
| **代码** | [flow.py#L153-L166](file:///d:/工作/工作/AI/testplatform/program16/src/api/routes/flow.py#L153-L166)，[pipeline.py#L1002-L1009](file:///d:/工作/工作/AI/testplatform/program16/src/pipeline.py#L1002-L1009) |

### 3.6 知识库入库

| 项目 | 说明 |
|------|------|
| **功能** | 开发确认分析正确后手工推入知识库，同时将根因与分析步骤写入 SQLite 供后续抽查 |
| **接口** | `POST /api/store` |
| **代码** | [flow.py#L167-L180](file:///d:/工作/工作/AI/testplatform/program16/src/api/routes/flow.py#L167-L180)，[pipeline.py#L1012-L1022](file:///d:/工作/工作/AI/testplatform/program16/src/pipeline.py#L1012-L1022) |
| **设计原则** | **不自动入库**，只生成文档与报表；入库由人工判断后手动触发 |

### 3.7 飞书文档管理

| 项目 | 说明 |
|------|------|
| **功能** | 从飞书下载分析文档、创建飞书文档、提取文档 ID |
| **代码** | [feishu_client.py](file:///d:/工作/工作/AI/testplatform/program16/src/clients/feishu_client.py) |
| **特性** | 支持 docx → Markdown 转换；自动提取 doc_id 和 domain；上传到飞书云盘文件夹 |

### 3.8 Mock 模式

| 项目 | 说明 |
|------|------|
| **功能** | AI 日志分析、Jira、知识库三个外部接口均支持 Mock 模式，离线调试无需真实接口 |
| **配置** | `config.yaml` 中各模块的 `mock: true` 字段 |
| **状态** | 首页概览 (`/api/overview`) 展示各接口 Mock 状态 |

---

## 四、缺陷反馈中心

> **定位：** 分析结果的深度诊断、验证、修正与回写，形成"分析 → 诊断 → 修正 → 回写"的闭环反馈。

### 4.1 排查诊断

| 项目 | 说明 |
|------|------|
| **功能** | 对单个 Bug 执行深度排查：视频附件检查 → gmlogger 解析 → 视频下载 → 帧提取 → OCR 识别 → 触发时间匹配 |
| **接口** | `POST /api/troubleshoot/diagnose` |
| **代码** | [troubleshoot.py#L82-L131](file:///d:/工作/工作/AI/testplatform/program16/src/api/routes/troubleshoot.py#L82-L131) |
| **特性** | 支持强制重新诊断（`force`）；可跳过视频缓存（`skip_video_cache`）；诊断超时保护；结果本地缓存 |

### 4.2 多维表格记录查询

| 项目 | 说明 |
|------|------|
| **功能** | 从飞书多维表格查询 Bug 的排查记录，支持多种查询方式 |
| **接口** | `POST /api/troubleshoot/records`（按条件查询）<br>`POST /api/troubleshoot/direct`（按 Jira 号直接查询）<br>`POST /api/troubleshoot/search_jira`（关键词搜索） |
| **代码** | [troubleshoot.py#L18-L66](file:///d:/工作/工作/AI/testplatform/program16/src/api/routes/troubleshoot.py#L18-L66) |
| **过滤** | 支持按时间范围、结果状态、来源、去重、排除人工已审核等条件组合 |

### 4.3 诊断缓存管理

| 项目 | 说明 |
|------|------|
| **功能** | 更新诊断结果的缓存数据，支持修正时间、添加备注、修改分类 |
| **接口** | `POST /api/troubleshoot/update_cache` |
| **代码** | [troubleshoot.py#L134-L156](file:///d:/工作/工作/AI/testplatform/program16/src/api/routes/troubleshoot.py#L134-L156) |
| **可修正字段** | `correction_time`（修正时间）、`correction_note`（修正备注）、`human_reason`（人工根因）、`category`（分类） |

### 4.4 Rootcause 提取

| 项目 | 说明 |
|------|------|
| **功能** | 从 Jira issue 获取根因字段，对"符合预期"等通用根因追加 AI 精炼结论 |
| **代码** | [pipeline.py#L394-L398](file:///d:/工作/工作/AI/testplatform/program16/src/pipeline.py#L394-L398)、[pipeline.py#L749-L773](file:///d:/工作/工作/AI/testplatform/program16/src/pipeline.py#L749-L773) |
| **通用根因处理** | 识别"符合需求/符合预期/设计如此"等通用表述，追加 AI 分析结论到括号中辅助展示 |

### 4.5 AI 评论总结

| 项目 | 说明 |
|------|------|
| **功能** | 获取 Jira 全部评论 → LLM 语义简化 → 评论分析（与 AI 日志分析对比） → Diana 概括核心语义 → 生成评论分析 md 文档 |
| **代码** | [pipeline.py#L235-L365](file:///d:/工作/工作/AI/testplatform/program16/src/pipeline.py#L235-L365) |
| **输出** | 8-20 字核心语义结论 + 详细排查分析文档（含排查摘要、排查过程、时序排查详情） |

### 4.6 置信度计算与判定

| 项目 | 说明 |
|------|------|
| **功能** | 基于语义相似度计算 AI 分析结果的可信程度 |
| **代码** | [pipeline.py#L401-L453](file:///d:/工作/工作/AI/testplatform/program16/src/pipeline.py#L401-L453) |
| **计算方式** | **正常根因：** `(根因语义对比分 + 评论vs因果链分) / 2`<br>**通用根因：** 直接使用评论vs因果链语义相似度 |
| **对比细节** | 根因对比：Jira rootcause vs AI 根因结论<br>步骤对比：评论提取步骤 vs AI 分析步骤（两层语义比对取最大值） |
| **判定** | `confidence >= threshold` → 达标，写入报表，文档移入 `True/` 目录<br>`confidence < threshold` → 不达标，标记失败，文档移入 `False/` 目录 |

### 4.7 结果验证与填入

| 项目 | 说明 |
|------|------|
| **功能** | 对已有分析报告的 Bug 执行三字段验证（AI 评论总结、rootcause、置信度），写入 CSV 和多维表格 |
| **接口** | ~~`POST /api/verify_and_fill`~~、~~`POST /api/verify_write`~~、~~`POST /api/verify_write_bitable`~~、~~`GET /api/verify_bitable_eligible`~~（**均已下线**：verify.py 已删除，改由问题排查面板「校正编辑」+ `/api/troubleshoot/*` 承接） |
| **代码** | 现役实现见 [troubleshoot.py](file:///d:/工作/工作/AI/testplatform/program16/src/api/routes/troubleshoot.py) 与 [pipeline.py](file:///d:/工作/工作/AI/testplatform/program16/src/pipeline.py) |
| **备用相似度** | 验证时额外计算 AI 日志分析结论 vs AI 评论排查结论的语义相似度，供置信度不达标时兜底判定 |

### 4.8 批量人工审核回写

| 项目 | 说明 |
|------|------|
| **功能** | 将人工审核结果批量写回多维表格 |
| **接口** | `POST /api/troubleshoot/batch_write_review` |
| **代码** | [troubleshoot.py#L159-L174](file:///d:/工作/工作/AI/testplatform/program16/src/api/routes/troubleshoot.py#L159-L174) |
| **特性** | 支持仅写入空审核字段（`only_empty_review`），避免覆盖已有审核 |

### 4.9 触发时间问题导出

| 项目 | 说明 |
|------|------|
| **功能** | 将触发时间提取失败的记录导出为 CSV 并上传飞书云端 |
| **接口** | `POST /api/troubleshoot/export_trigger_time_issues` |
| **代码** | [troubleshoot.py#L177-L189](file:///d:/工作/工作/AI/testplatform/program16/src/api/routes/troubleshoot.py#L177-L189) |

### 4.10 批量预归类

| 项目 | 说明 |
|------|------|
| **功能** | 根据错误信息和人工审核结果快速分类，无需深度分析的记录自动跳过，支持三步分类逻辑 |
| **接口** | `POST /api/troubleshoot/batch_pre_classify` |
| **代码** | [troubleshoot_service.py](file:///e:/program23/src/services/troubleshoot_service.py)（`batch_pre_classify`） |
| **三步分类** | ① 无报错信息/服务有报错 → 跳过排查<br>② 人工审核结果倒推（如模型调用失败→待后端开发排查）<br>③ 错误信息文本预归类（`_diag_pre_classify`） |
| **输出** | `skip`（跳过列表，自动生成报告）+ `need_analysis`（需分析列表） |

### 4.11 开发者通知

| 项目 | 说明 |
|------|------|
| **功能** | 将自动归类的待后端排查记录通过飞书机器人发送给后端开发者 |
| **接口** | `POST /api/troubleshoot/send_to_developer` |
| **代码** | [troubleshoot_service.py](file:///e:/program23/src/services/troubleshoot_service.py)（`send_to_developer`） |
| **消息格式** | Markdown 表格（#、Jira号、分析完成时间、错误信息）+ 分类统计 |
| **依赖** | `feishu_bot.notify_chat_id` 配置 |

### 4.12 诊断取消控制

| 项目 | 说明 |
|------|------|
| **功能** | 对正在执行的诊断任务发送取消信号，支持单个或全部取消 |
| **接口** | `POST /api/troubleshoot/cancel_diag` |
| **代码** | [troubleshoot.py#L69-L79](file:///d:/工作/工作/AI/testplatform/program16/src/api/routes/troubleshoot.py#L69-L79) |

### 4.13 飞书机器人集成

| 项目 | 说明 |
|------|------|
| **功能** | 飞书长连接客户端实时接收消息事件，支持卡片交互回调、消息调试 |
| **接口** | `POST /api/feishu/event`（事件回调）<br>`GET /api/feishu/events`（调试查看）<br>`POST /api/test/feishu_msg_debug`（消息调试） |
| **代码** | [feishu.py](file:///d:/工作/工作/AI/testplatform/program16/src/api/routes/feishu.py) |
| **特性** | 支持 HTTP 回调模式和 WebSocket 长连接模式；启动时自动连接 |

### 4.14 Jira 原始数据查看

| 项目 | 说明 |
|------|------|
| **功能** | 直接查看 Jira issue 原始 API 返回数据，用于排查接口问题 |
| **接口** | `POST /api/test/jira_raw` |
| **代码** | [testing.py#L1098-L1135](file:///d:/工作/工作/AI/testplatform/program16/src/api/routes/testing.py#L1098-L1135) |

### 4.15 置信度批量写入（根因语义对比）

| 项目 | 说明 |
|------|------|
| **功能** | 筛选多维表格中“分析结果=成功”的记录，填充 rootcause（从 Jira 取最新）和 AI 问题分析根因（表格有则用，无则从飞书文档提取），用 Diana LLM 做 5 路语义相似度对比写回置信度。通用/无效/重复根因写“无法判断” |
| **接口** | `GET /api/test/confidence_batch_write`（SSE 流式，支持 after_time/only_empty/jira_ids 筛选）<br>`POST /api/test/confidence_batch_commit`（分类批量写入） |
| **代码** | [testing.py#L1424-L1845](file:///d:/工作/工作/AI/testplatform/program16/src/api/routes/testing.py#L1424-L1845)，[ConfidenceBatchPanel.vue](file:///d:/工作/工作/AI/testplatform/program16/frontend/src/panels/ConfidenceBatchPanel.vue) |
| **5 路语义对比** | 路1: 核心语义提取对比<br>路2: 仅结论句对比（避免负面上下文拉低分数）<br>路3: 实体句匹配（从 AI 根因提取含 Jira 关键实体的句子）<br>路4: 逐句兆底对比（长文本拆分逐句比对）<br>路5: 全文原始对比（原始根因全文上下文对比） |
| **前端流程** | 开始执行（EventSource SSE）→ 实时进度展示 → 结果表格 → 分类写入按钮（达标/无效/未达标/一键）→ POST 提交 |

---

## 五、质量分析与决策

> **定位：** 基于执行数据和反馈数据生成多维度质量报告，支撑质量评估、参数优化和持续改进决策。

### 5.1 每日结论报表

| 项目 | 说明 |
|------|------|
| **功能** | 按日期查询/刷新每日分析结论报表，包含 6 列核心字段 |
| **接口** | `GET /api/report/daily`（查询）<br>`GET /api/report/daily_refresh`（刷新） |
| **代码** | [report.py#L42-L161](file:///d:/工作/工作/AI/testplatform/program16/src/api/routes/report.py#L42-L161) |
| **报表列** | jira号、分析问题时间、AI分析结果(飞书链接)、AI评论总结、rootcause、结果置信度 |
| **刷新逻辑** | 从批次执行记录 + 多维表格拼接；自动分类（失败/待处理/超长成功/正常成功）；同步上传云端文档 + 写入多维表格统计 |

### 5.2 每日汇总统计

| 项目 | 说明 |
|------|------|
| **功能** | 根据结论报表生成当日汇总指标：总数、回归数、成功数、失败数、待处理数、去重数 |
| **接口** | `GET /api/report/daily_summary` |
| **代码** | [report.py#L164-L261](file:///d:/工作/工作/AI/testplatform/program16/src/api/routes/report.py#L164-L261) |
| **前端** | [DailySummaryPanel.vue](file:///d:/program23/frontend/src/panels/DailySummaryPanel.vue)（“更多工具”→每日汇总，集成每日/每周/时间段三个 Tab） |

### 5.3 每周汇总

| 项目 | 说明 |
|------|------|
| **功能** | 按周维度汇总分析执行数据，支撑周度质量回顾 |
| **接口** | `GET /api/report/weekly_summary` |
| **代码** | [report.py#L264-L275](file:///d:/工作/工作/AI/testplatform/program16/src/api/routes/report.py#L264-L275) |
| **前端** | 同 §5.2 DailySummaryPanel.vue“每周汇总” Tab |

### 5.4 自定义时间段汇总

| 项目 | 说明 |
|------|------|
| **功能** | 指定起止日期范围生成汇总报告 |
| **接口** | `GET /api/report/range_summary?start_date=&end_date=` |
| **代码** | [report.py#L278-L291](file:///d:/工作/工作/AI/testplatform/program16/src/api/routes/report.py#L278-L291) |
| **前端** | 同 §5.2 DailySummaryPanel.vue“时间段汇总” Tab |

### 5.5 质量抽查复核

| 项目 | 说明 |
|------|------|
| **功能** | 从 SQLite 已入库记录中随机抽样，重新执行 AI 分析并与已入库数据做语义对比，生成审核表格 |
| **接口** | `POST /api/audit`（执行抽查）<br>`POST /api/audit/clear`（清空已抽查记录） |
| **代码** | [flow.py#L181-L196](file:///d:/工作/工作/AI/testplatform/program16/src/api/routes/flow.py#L181-L196)，[audit.py](file:///d:/工作/工作/AI/testplatform/program16/src/core/audit.py) |
| **达标条件** | 根因语义相似 **且**（步骤语义相似 **或** 综合分析语义相似） |
| **输出** | `audit_comparison.csv`（全量审核表）+ `audit_failed_日期.csv`（不达标项）+ `spotcheck/日期/re-bugid.md`（重新分析文档） |
| **去重** | 已抽查过的 bugid 记录在 `audited_bugids.csv`，下次自动排除 |

### 5.6 抽查报表查询

| 项目 | 说明 |
|------|------|
| **功能** | 查询抽查审核表格和已抽查记录 |
| **接口** | `GET /api/report/audit`（审核表格）<br>`GET /api/report/audited`（已抽查记录）<br>`GET /api/report/audit_failed`（不达标报表） |
| **代码** | [report.py#L294-L308](file:///d:/工作/工作/AI/testplatform/program16/src/api/routes/report.py#L294-L308) |

### 5.7 批量执行报表

| 项目 | 说明 |
|------|------|
| **功能** | 按日期查询批量执行记录和结果验证记录 |
| **接口** | `GET /api/report/batch`（执行记录）<br>`GET /api/report/verify`（验证记录） |
| **代码** | [report.py#L311-L356](file:///d:/工作/工作/AI/testplatform/program16/src/api/routes/report.py#L311-L356) |

### 5.8 批次质量评估

| 项目 | 说明 |
|------|------|
| **功能** | 统计当前批次的成功率/耗时，扫描多维表格补写缺失的执行时间 |
| **接口** | `POST /api/test/batch_quality_assess` |
| **代码** | [testing.py#L913-L961](file:///d:/工作/工作/AI/testplatform/program16/src/api/routes/testing.py#L913-L961) |
| **指标** | 总数、补写数量、缺失数量、最晚完成时间 |

### 5.9 配置参数调优分析

| 项目 | 说明 |
|------|------|
| **功能** | 列出所有历史批量执行批次，对选中批次计算成功率、平均/中位数/P95 耗时等指标 |
| **接口** | `GET /api/tuning/batch_list`（批次列表）<br>`POST /api/tuning/analyze`（分析） |
| **代码** | [tuning.py](file:///d:/工作/工作/AI/testplatform/program16/src/api/routes/tuning.py) |
| **指标** | 成功率、平均耗时、中位数耗时、P95 耗时、版本号；支持按来源（PC/线上）过滤 |

### 5.10 数据看板

| 项目 | 说明 |
|------|------|
| **功能** | 从飞书云端列出所有历史批次，支持云端批次预览和本地同步 |
| **接口** | `GET /api/data/history_batches`（批次列表）<br>`GET /api/data/history_batch_preview`（批次预览）<br>`POST /api/data/sync_cloud_batches`（云端同步）<br>`GET /api/data/history_jira`（批次 Jira 详情） |
| **代码** | [data.py](file:///d:/工作/工作/AI/testplatform/program16/src/api/routes/data.py) |
| **特性** | 云端批次浏览（按日期文件夹递归）；云端 → 本地 CSV 同步去重；批次详情聚合多维表格匹配记录 |

### 5.11 文档管理

| 项目 | 说明 |
|------|------|
| **功能** | 列出 `docs/` 目录下的所有 CSV 报表文件（文件预览接口已下线） |
| **接口** | `GET /api/docs/files`（文件列表）<br>~~`GET /api/docs/preview`~~（**已下线**） |
| **代码** | [docs.py](file:///d:/工作/工作/AI/testplatform/program16/src/api/routes/docs.py) |

### 5.12 评论文档分类

| 项目 | 说明 |
|------|------|
| **功能** | 根据执行记录对当天评论分析文档按置信度自动分类到 `True/` 或 `False/` 目录 |
| **接口** | `POST /api/report/classify_docs` |
| **代码** | [report.py#L28-L39](file:///d:/工作/工作/AI/testplatform/program16/src/api/routes/report.py#L28-L39) |

### 5.13 首页概览

| 项目 | 说明 |
|------|------|
| **功能** | 展示当日核心指标：今日总数/完整数/不完整数、已抽查总数、各接口 Mock 状态 |
| **接口** | `GET /api/overview` |
| **代码** | [system.py#L117-L143](file:///d:/工作/工作/AI/testplatform/program16/src/api/routes/system.py#L117-L143) |

---

## 六、系统管理支撑功能

> 以下为平台运行支撑能力，横跨四大维度。

| 功能 | 接口 | 说明 |
|------|------|------|
| **配置读写** | `GET/POST /api/config` | 在线读写 `config.yaml`，支持按段合并 |
| **服务控制** | `POST /api/shutdown`、`POST /api/restart` | 优雅关闭/重启服务 |
| **远程更新** | ~~`POST /api/system/git_pull`~~（**已下线**：令牌校验写死、从未生效） | 原设计为远程拉取最新代码并自动重启 |
| **OAuth 授权** | `GET /api/auth/authorize`、`GET /api/callback` | 飞书 Open API 用户授权 |
| **每日播报** | 启动时自动初始化调度器 | 定时推送昨日分析汇总到飞书群 |
| **多维表格写入** | `POST /api/test/bitable_write` | 支持 dry-run 预览的飞书多维表格写入 |
| **飞书文档创建** | `POST /api/test/create_docx` | 创建飞书在线文档 |

---

## 七、功能-维度映射矩阵

| 功能点 | 测试设计 | 测试执行 | 缺陷反馈 | 质量分析 |
|--------|:------:|:------:|:------:|:------:|
| JQL 搜索候选 Bug | ✅ | | | |
| CSV 导入 | ✅ | | | |
| 多维表格去重过滤 | ✅ | | | |
| 随机抽样 | ✅ | | | |
| 触发时间批量预提取 | ✅ | | | |
| 触发时间自学习 | ✅ | | | |
| 单 Bug 全流程执行 | | ✅ | | |
| 批量并行执行 | | ✅ | | |
| AI 日志分析接口测试 | | ✅ | | |
| 内容补充流程 | | ✅ | | |
| 失败重试 | | ✅ | | |
| 知识库入库 | | ✅ | | |
| 排查诊断 | | | ✅ | |
| 多维表格记录查询 | | | ✅ | |
| 诊断缓存管理 | | | ✅ | |
| Rootcause 提取 | | | ✅ | |
| AI 评论总结 | | | ✅ | |
| 置信度计算与判定 | | | ✅ | |
| 结果验证与填入 | | | ✅ | |
| 批量人工审核回写 | | | ✅ | |
| 批量预归类 | | | ✅ | |
| 置信度批量写入 | | | ✅ | |
| 开发者通知 | | | ✅ | |
| 飞书机器人集成 | | | ✅ | |
| 每日/每周/时间段汇总 | | | | ✅ |
| 质量抽查复核 | | | | ✅ |
| 批次质量评估 | | | | ✅ |
| 配置参数调优分析 | | | | ✅ |
| 数据看板 | | | | ✅ |
| 评论文档分类 | | | | ✅ |

---

## 八、接口清单汇总（共 60+ 端点）

| 路由模块 | 端点数 | 文件 |
|---------|:-----:|------|
| testing | 15 | [testing.py](file:///d:/工作/工作/AI/testplatform/program16/src/api/routes/testing.py) |
| report | 11 | [report.py](file:///d:/工作/工作/AI/testplatform/program16/src/api/routes/report.py) |
| flow | 8 | [flow.py](file:///d:/工作/工作/AI/testplatform/program16/src/api/routes/flow.py) |
| troubleshoot | 10 | [troubleshoot.py](file:///d:/工作/工作/AI/testplatform/program16/src/api/routes/troubleshoot.py) |
| system | 6 | [system.py](file:///d:/工作/工作/AI/testplatform/program16/src/api/routes/system.py) |
| trigger | 5 | [trigger.py](file:///d:/工作/工作/AI/testplatform/program16/src/api/routes/trigger.py) |
| verify | 6 | [verify.py](file:///d:/工作/工作/AI/testplatform/program16/src/api/routes/verify.py) |
| data | 4 | [data.py](file:///d:/工作/工作/AI/testplatform/program16/src/api/routes/data.py) |
| misc | 5 | [misc.py](file:///d:/工作/工作/AI/testplatform/program16/src/api/routes/misc.py) |
| feishu | 3 | [feishu.py](file:///d:/工作/工作/AI/testplatform/program16/src/api/routes/feishu.py) |
| timestudy | 4 | [timestudy.py](file:///d:/工作/工作/AI/testplatform/program16/src/api/routes/timestudy.py) |
| tuning | 2 | [tuning.py](file:///d:/工作/工作/AI/testplatform/program16/src/api/routes/tuning.py) |
| docs | 2 | [docs.py](file:///d:/工作/工作/AI/testplatform/program16/src/api/routes/docs.py) |
| bitable | 1 | [bitable.py](file:///d:/工作/工作/AI/testplatform/program16/src/api/routes/bitable.py) |
| audit | 1 | [audit.py](file:///d:/工作/工作/AI/testplatform/program16/src/api/routes/audit.py) |
