# Bug 分析全流程图

## 一、总体流程概览

```mermaid
flowchart LR
    A[① AI日志分析去重] --> B[② 触发时间提取]
    B --> C[③ 排查诊断]
    C --> D[④ 置信度写入]
    D --> E[⑤ 数据看板]
    E --> F[⑥ 质量抽查]
    style A fill:#4CAF50,color:#fff
    style B fill:#2196F3,color:#fff
    style C fill:#FF9800,color:#fff
    style D fill:#9C27B0,color:#fff
    style E fill:#00BCD4,color:#fff
    style F fill:#F44336,color:#fff
```

---

## 二、全流程时序图

```mermaid
sequenceDiagram
    actor User as 用户/CLI
    participant Web as FastAPI Web层
    participant Pipeline as pipeline.py
    participant Jira as Jira API
    participant AI as AI日志分析服务
    participant Diana as Diana LLM
    participant Feishu as 飞书 Open API
    participant DB as SQLite DB
    participant FS as 本地文件系统

    rect rgb(232, 245, 233)
    Note over User, FS: ① AI日志分析去重执行
    User->>Web: POST /api/flow/single {bugid}
    Web->>Pipeline: execute_single_flow(bugid)
    Pipeline->>Jira: fetch_issue(bugid)
    Jira-->>Pipeline: issue (含状态)
    Pipeline->>Pipeline: 检查状态 == Closed ?
    alt 非 Closed
        Pipeline-->>Web: ❌ 拒绝（仅 Closed 允许）
    end
    Pipeline->>FS: 读取当日 CSV 去重检查
    alt 已有完整记录
        Pipeline->>Pipeline: 跳过 AI 分析（need_ai=False）
    else 无记录/不完整
        Pipeline->>AI: analyze_logs(bugid, trigger_time)
        AI-->>Pipeline: 分析报告 JSON
        Pipeline->>FS: save_document(bugid, report)
    end
    end

    rect rgb(227, 242, 253)
    Note over User, FS: ② 触发时间提取
    Pipeline->>Jira: extract_trigger_time_from_issue(issue)
    Jira-->>Pipeline: 评论中的时间戳
    alt 提取成功
        Pipeline->>Feishu: _save_trigger_time_to_cloud(bugid, time)
        alt 云端写入失败
            Pipeline->>FS: 降级写本地 CSV
        end
    else 提取失败
        Pipeline->>Pipeline: 不阻断，继续后续流程
    end
    end

    rect rgb(255, 243, 224)
    Note over User, FS: ③ 排查诊断（评论分析 + 根因提取）
    Pipeline->>Jira: extract_rootcause(issue)
    Jira-->>Pipeline: rootcause
    Pipeline->>Jira: extract_comments(issue)
    Jira-->>Pipeline: 评论列表
    Pipeline->>Diana: summarize_comments(评论简化)
    Diana-->>Pipeline: 简化评论摘要
    Pipeline->>Diana: generate_comment_analysis(摘要+AI结论)
    Diana-->>Pipeline: 评论分析结果
    Pipeline->>Diana: 概括排查结论（8-20字）
    Diana-->>Pipeline: 核心语义结论
    Pipeline->>FS: generate_comment_summary_doc(bugid)
    end

    rect rgb(243, 229, 245)
    Note over User, FS: ④ 置信度写入
    Pipeline->>FS: 读取 AI 报告内容
    Pipeline->>Pipeline: parse_conclusion() + parse_doc_steps()
    Pipeline->>Diana: semantic_similarity(Jira根因, AI结论)
    Diana-->>Pipeline: root_cause_score
    Pipeline->>Diana: semantic_best_matches(评论, AI步骤)
    Diana-->>Pipeline: step_score
    Pipeline->>Pipeline: confidence = (root_cause_score + step_score) / 2
    alt confidence >= threshold
        Pipeline->>FS: 写入当日 CSV 报表
        Pipeline->>FS: 评论文档移入 True/ 目录
    else confidence < threshold
        Pipeline->>Pipeline: 标记失败，需手工修复
        Pipeline->>FS: 评论文档移入 False/ 目录
    end
    end

    rect rgb(224, 247, 250)
    Note over User, FS: ⑤ 数据看板
    User->>Web: GET /api/data/history_batches
    Web->>Feishu: list_folder_files(folder_token)
    Feishu-->>Web: 云端批次文档列表
    User->>Web: GET /api/report/daily_csv
    Web->>FS: 读取当日 CSV 报表
    FS-->>Web: 报表数据
    Web-->>User: 展示数据看板（前端 Vue）
    end

    rect rgb(255, 235, 238)
    Note over User, FS: ⑥ 质量抽查
    User->>Web: POST /api/flow/audit {count}
    Web->>DB: 随机抽取已入库 bugid
    DB-->>Web: 抽样列表
    loop 每个抽样的 bugid
        Web->>AI: analyze_logs(bugid, trigger_time) 重新分析
        AI-->>Web: 新分析报告
        Web->>DB: 读取已入库的根因+步骤
        Web->>Diana: 语义对比（新旧根因/步骤）
        Diana-->>Web: 相似度分数
        Web->>FS: 生成 spotcheck/日期/re-bugid.md
    end
    Web->>FS: 输出 audit_comparison.csv
    Web->>FS: 不达标项输出 audit_failed_日期.csv
    Web-->>User: 审核表格供人工复核
    end
```

---

## 三、单 Bug 执行流程详细图（execute_single_flow）

```mermaid
flowchart TD
    Start([开始]) --> CheckJira{Jira 状态检查}
    CheckJira -->|非 Closed| Reject[❌ 拒绝处理]
    CheckJira -->|Closed| ExtractTime[触发时间提取]

    ExtractTime --> DedupCheck{去重检查<br/>当日CSV已有完整记录?}
    DedupCheck -->|是| SkipAI[跳过 AI 分析]
    DedupCheck -->|否| CallAI[调用 AI 日志分析接口]

    CallAI --> AIReachable{接口可达?}
    AIReachable -->|否| FailAI[❌ AI 分析失败]
    AIReachable -->|是| AIAnalyze[AI 生成分析报告]
    AIAnalyze --> SaveDoc[保存文档到 docs/日期/]

    SkipAI --> Step2[执行结果查看]
    SaveDoc --> Step2

    Step2 --> FetchDoc{本地有文档?}
    FetchDoc -->|否且有飞书链接| DownloadDoc[从飞书下载文档]
    FetchDoc -->|是| Rootcause
    DownloadDoc --> Rootcause

    Rootcause[提取 Rootcause] --> CommentSummary[AI 评论总结]

    CommentSummary --> GetComments[获取 Jira 全部评论]
    GetComments --> LLMSummary[Diana LLM 简化评论]
    LLMSummary --> CommentAnalysis[评论分析 vs AI日志分析对比]
    CommentAnalysis --> CoreConclusion[Diana 概括核心语义 8-20字]
    CoreConclusion --> GenCommentDoc[生成评论分析 md 文档]

    GenCommentDoc --> Confidence{置信度计算}
    Confidence --> GetAIReport[读取 AI 报告]
    GetAIReport --> CalcRootScore[根因语义对比分]
    GetAIReport --> CalcStepScore[步骤语义对比分]
    CalcRootScore --> AvgScore[confidence = avg 或 step_score]
    CalcStepScore --> AvgScore

    AvgScore --> ThresholdCheck{confidence >= 阈值?}
    ThresholdCheck -->|是 ✅| WriteCSV[写入当日 CSV 报表]
    ThresholdCheck -->|否 ❌| MarkFail[标记失败 需手工修复]

    WriteCSV --> ClassifyDoc[文档移入 True/ 目录]
    MarkFail --> ClassifyDocFail[文档移入 False/ 目录]

    ClassifyDoc --> End([结束])
    ClassifyDocFail --> End
    Reject --> End
    FailAI --> End

    style Start fill:#4CAF50,color:#fff
    style End fill:#4CAF50,color:#fff
    style Reject fill:#F44336,color:#fff
    style FailAI fill:#F44336,color:#fff
    style MarkFail fill:#FF9800,color:#fff
    style WriteCSV fill:#2196F3,color:#fff
```

---

## 四、质量抽查流程详细图

```mermaid
flowchart TD
    Start([audit 命令]) --> Sample[从 DB 随机抽取 N 个已入库 bugid]
    Sample --> Exclude[排除已抽查过的 bugid]
    Exclude --> Loop{遍历每个 bugid}

    Loop --> ReAnalyze[重新调用 AI 日志分析]
    ReAnalyze --> GetOld[从 DB 读取已入库的根因+步骤]
    GetOld --> Compare[语义对比]

    Compare --> RootCompare[根因相似度计算]
    Compare --> StepCompare[分析流程相似度计算]

    RootCompare --> Judge{根因相似 且<br/>步骤/综合相似?}
    StepCompare --> Judge

    Judge -->|达标 ✅| Pass[判定: 通过]
    Judge -->|不达标 ❌| Fail[判定: 不通过]

    Pass --> SaveDoc[保存 re-bugid.md 到 spotcheck/]
    Fail --> SaveDoc

    SaveDoc --> RecordBugid[记录到 audited_bugids.csv]
    RecordBugid --> Loop

    Loop -->|遍历结束| OutputCSV[输出 audit_comparison.csv]
    OutputCSV --> OutputFail[不达标项输出 audit_failed_日期.csv]
    OutputFail --> End([人工审核])

    style Start fill:#F44336,color:#fff
    style End fill:#FF9800,color:#fff
    style Pass fill:#4CAF50,color:#fff
    style Fail fill:#F44336,color:#fff
```

---

## 五、模块职责对照表

| 阶段 | 核心模块 | API 路由 | 外部依赖 |
|------|---------|---------|---------|
| ① AI日志分析去重 | `pipeline.execute_single_flow` | `POST /api/flow/single` | Jira API, AI日志分析服务 |
| ② 触发时间提取 | `jira_client.extract_trigger_time_from_issue` + `trigger_ops` | `POST /api/flow/extract_time`, `POST /api/trigger_time/batch_read` | Jira API, 飞书 Bitable |
| ③ 排查诊断 | `pipeline._fill_comment_summary` + `comment_filter` | 内嵌在 flow/single 中 | Diana LLM, Jira API |
| ④ 置信度写入 | `pipeline._fill_confidence` + `semantic` | 内嵌在 flow/single 中 | Diana LLM (TF-IDF 语义) |
| ⑤ 数据看板 | `data.py` + `report.py` 路由 | `GET /api/data/*`, `GET /api/report/*` | 飞书云盘, 本地 CSV |
| ⑥ 质量抽查 | `audit.sample_and_audit` | `POST /api/flow/audit` | AI日志分析服务, Diana LLM, SQLite |

---

## 六、关键数据流向

```mermaid
flowchart LR
    subgraph 输入
        Jira[Jira Bug 单]
        AI[AI 日志分析服务]
    end

    subgraph 处理
        P[pipeline.py]
        Core[core/ 模块]
        Clients[clients/ 模块]
    end

    subgraph 存储
        CSV[每日 CSV 报表<br/>docs/日期/]
        MD[分析文档<br/>docs/日期/bugid.md]
        DB[(SQLite<br/>bug_records.db)]
        Bitable[飞书 Bitable<br/>触发时间]
    end

    subgraph 展示
        Vue[Vue 前端]
        API[FastAPI 路由]
    end

    Jira --> Clients
    AI --> Clients
    Clients --> P
    P --> Core
    Core --> CSV
    Core --> MD
    P --> DB
    P --> Bitable
    CSV --> API
    MD --> API
    DB --> API
    API --> Vue
```
