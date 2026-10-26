# ADP 调用逻辑

> 实现：`src/services/adp_ops.py` ｜ 端点：`src/api/routes/testing.py`

## 主流程

```mermaid
flowchart TD
    A["Jira 号"] --> B["查附件 dpportal"]
    B -->|无附件| X1["无法分析 · 输入质量"]
    B -->|无有效日志| X2["无法分析 · 无有效日志"]
    B -->|有日志| C["拼消息<br/>描述 + 触发时间 + 附件链接"]
    C --> D["ADP SSE 流式分析"]
    D -->|无返回| X3["失败 · 连接超时或网络异常"]
    D --> E{"有 HTML 报告?"}
    E -->|否 · 流耗时超过5分钟| F["续接 2 轮 × 5 分钟"]
    E -->|是| G["提取 6 字段"]
    F --> G
    G --> H{"报告可下载?"}
    H -->|是| I["下载 HTML → 传飞书换 file_token"]
    H -->|否| J["标记分析失败<br/>保留已提取字段"]
    I --> K["本地保存"]
    J --> K
    K --> L["写飞书多维表格 · 6 字段"]
    L --> M["返回前端：预览 + 报告路径 + 失败类型"]
```

## 数据落在哪

```mermaid
flowchart LR
    subgraph LOCAL["本地"]
        A["docs/adp_results/KEY/"]
        A --> A1["KEY_full_analysis.md"]
        A --> A2["KEY_raw_data.json"]
        A --> A3["KEY_fail_时间戳.md（失败快照）"]
        B["reports/adp/KEY/*.html"]
    end
    subgraph CLOUD["飞书"]
        C["多维表格：6 字段 + 报告附件（file_token）"]
    end
    A -.->|查看完整报告| U["GET /api/test/adp_report"]
```

## 接口

```mermaid
flowchart LR
    FE["AdpTestPanel"] -->|单条| S1["POST /adp_single"]
    FE -->|批量| S2["POST /adp_batch"]
    FE -->|查表| S3["POST /adp_lookup"] --> JB["/api/jobs 作业"]
    FE -->|补全| S4["POST /adp_enrich"]
    FE -->|看报告| S5["GET /adp_report"]
```

## 失败类型

- 输入质量：无附件 / 无有效日志 / 链接为空 / 描述不清
- ADP 连接超时或网络异常
- 下载链接失效
- 分析过程未完成
- 分析完成但未产出 HTML 报告
- `处理异常: xxx` / 飞书写入失败 / ADP 分析超时

## 参数与坑

| 项 | 值 |
|---|---|
| 并发 / SSE 超时 | 2 / 3600s（connect 30s、read 60s） |
| 重试 / 心跳 | 3 次（10/20/30s） / 30s |
| 续接 / 下载 / 预览 | 300s×2 轮 / 120s / 2000 字 |

1. 报告链接是**附件字段**：必须 `[{"file_token": token}]`，写 URL 会 `AttachFieldConvFail`。
2. **全文只落盘**，前端只拿预览。
3. 失败也留 `_fail_*.md`，失败时同样能「查看完整报告」。
