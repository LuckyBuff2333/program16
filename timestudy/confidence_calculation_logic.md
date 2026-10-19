# 置信度计算逻辑

## 概述

置信度（Confidence）用于衡量 **AI 日志分析报告** 与 **Jira Bug 单实际数据** 之间的一致性程度。  
通过对「根因」和「分析步骤」两个维度的语义对比，产出 0~1 的综合评分，达标（≥ 0.7）方可写入正式报表，不达标则需人工复核修复。

---

## 流程图

![置信度计算流程图](images/diagram_1.png)

<!-- Mermaid 源码（编辑时改这里，然后用 mermaid.ink 重新生成 PNG）：
```mermaid
flowchart TD
    Start([开始：输入 bugid / feishu_link / rootcause]) --> GetReport[获取 AI 分析报告<br/>本地 docs/ 优先 → 飞书 API 回退]

    GetReport --> HasReport{是否有<br/>AI 报告？}
    HasReport -- "无" --> ZeroC1[置信度 = 0<br/>无法对比]

    HasReport -- "有" --> ParseReport[解析 AI 报告<br/>① 提取根因结论 ai_conclusion<br/>② 提取分析步骤 ai_steps]

    ParseReport --> CanParse{根因 和 步骤<br/>是否均有效？}
    CanParse -- "否" --> ZeroC2[置信度 = 0<br/>报告内容不完整]

    CanParse -- "是" --> CheckGeneric{rootcause 是否<br/>为通用根因？}

    %% ===== 通用根因分支 =====
    CheckGeneric -- "是（符合预期/符合需求等）" --> StepOnly[仅执行步骤对比<br/>跳过根因对比]

    %% ===== 正常根因分支 =====
    CheckGeneric -- "否（具体根因）" --> RootCompare[根因对比<br/>Jira rootcause vs AI 根因结论<br/>→ root_cause_score]

    RootCompare --> StepCompare

    StepOnly --> StepCompare[步骤对比<br/>Jira 评论 vs AI 分析步骤]

    StepCompare --> Layer1[Layer 1：逐条最佳匹配<br/>valid_comments ↔ comment_steps<br/>取平均 → layer1_score]
    StepCompare --> Layer2[Layer 2：整体语义相似度<br/>error_cause ↔ joined ai_steps<br/>→ layer2_score]

    Layer1 --> MaxLayer["step_score = max(layer1, layer2)"]
    Layer2 --> MaxLayer

    MaxLayer --> FinalScore{根因类型？}

    FinalScore -- "通用根因" --> GenericFormula["置信度 = step_score"]
    FinalScore -- "正常根因" --> NormalFormula["置信度 = (root_cause_score + step_score) / 2"]

    GenericFormula --> Threshold
    NormalFormula --> Threshold{置信度 ≥ 0.7？}

    Threshold -- "是 ✓" --> Pass([达标：写入报表])
    Threshold -- "否 ✗" --> Fail([不达标：需人工修复])
```
-->

---

## 核心模块说明

### 1. AI 报告获取

| 优先级 | 来源 | 说明 |
|--------|------|------|
| 1 | 本地 `docs/{日期}/{bugid}.md` | 已下载或已生成的本地文档 |
| 2 | 飞书 Open API | 通过飞书链接提取 doc_id，调用 `fetch_docx_as_markdown` |
| 3 | 无报告 | 置信度直接返回 **0** |

### 2. AI 报告解析

从报告文本中提取两个关键内容：

- **根因结论**（`parse_conclusion`）：匹配 `## 根因结论` / `### ④ 根因分析` 等标题段落
- **分析步骤**（`parse_doc_steps`）：优先提取 `**证据 N：xxx**` 格式的证据段落，无证据时回退提取 `1. xxx` 格式的序号步骤

> 两者均无法提取时，置信度 = 0

### 3. 根因类型判定

判断 Jira rootcause 是否为**通用根因**（无实质根因信息的表述）：

```
通用根因关键词：符合需求、符合预期、需求符合、预期行为、设计如此、非问题、登陆后无法复现、test error
```

判定规则：去除括号内容后，基础文本 ≤ 10 字且包含上述关键词 → 通用根因

### 4. 根因对比（正常根因专属）

```
root_cause_score = semantic_similarity(Jira rootcause, AI 根因结论)
```

通用根因跳过此步骤（root_cause_score 不参与最终计算）。

### 5. 步骤对比（双层取最大值）

| 层级 | 对比方式 | 计算公式 |
|------|---------|---------|
| **Layer 1** | 逐条最佳匹配 | Jira 有效评论 ↔ AI 评论提取步骤，每条取最大相似度后求平均 → `layer1_score` |
| **Layer 2** | 整体语义相似度 | Jira error_cause ↔ AI 分析步骤拼接文本 → `layer2_score` |

```
step_score = max(layer1_score, layer2_score)
```

### 6. 置信度合成公式

| 根因类型 | 公式 | 说明 |
|---------|------|------|
| **正常根因** | `confidence = (root_cause_score + step_score) / 2` | 根因与步骤各占 50% 权重 |
| **通用根因** | `confidence = step_score` | 无实质根因可对比，仅依赖步骤一致性 |

---

## 语义相似度计算（三级回退）

![语义相似度三级回退](images/diagram_2.png)

<!-- Mermaid 源码（编辑时改这里，然后用 mermaid.ink 重新生成 PNG）：
```mermaid
flowchart LR
    A[Diana LLM<br/>prompt 语义判断] -->|不可用| B[句向量模型<br/>BAAI/bge-small-zh-v1.5<br/>余弦相似度]
    B -->|不可用| C[TF-IDF<br/>词面余弦相似度]
```
-->

| 优先级 | 方法 | 特点 |
|--------|------|------|
| 1 | **Diana LLM** | 通过 prompt 让大模型判断根因是否相同，精细但慢 |
| 2 | **句向量模型** | BAAI/bge-small-zh-v1.5 编码后余弦相似度，适合批量 |
| 3 | **TF-IDF 兜底** | jieba 分词 + TF-IDF 向量化余弦，LLM 和模型均不可用时回退 |

---

## 阈值判定与后续处理

```
阈值（threshold）= 0.7（可在 config.yaml 中配置）
```

| 结果 | 条件 | 处理 |
|------|------|------|
| **达标** ✓ | confidence ≥ 0.7 | 评论文档移入 `{日期}/True/`，写入正式报表 |
| **不达标** ✗ | confidence < 0.7 | 评论文档移入 `{日期}/False/`，标记为需人工修复 |
| **备用判定** | confidence 不达标时 | 额外计算 AI 日志分析结论 vs AI 评论排查结论的语义相似度（`extra_similarity`），供人工参考 |

---

## 数据流总览

![数据流总览](images/diagram_3.png)

<!-- Mermaid 源码（编辑时改这里，然后用 mermaid.ink 重新生成 PNG）：
```mermaid
flowchart LR
    subgraph 数据源
        JIRA[Jira Bug 单]
        AI[AI 日志分析报告]
    end

    subgraph Jira数据提取
        RC[rootcause<br/>根因字段]
        CM[comments<br/>全部评论]
        EC[error_cause<br/>报错原因]
        CS[comment_steps<br/>评论分析步骤]
        VC[valid_comments<br/>有效评论]
    end

    subgraph AI报告解析
        AC[ai_conclusion<br/>根因结论]
        AS[ai_steps<br/>分析步骤]
    end

    subgraph 语义对比引擎
        RCS[root_cause_score<br/>根因对比分]
        L1[layer1_score<br/>逐条最佳匹配]
        L2[layer2_score<br/>整体语义相似度]
    end

    JIRA --> RC & CM & EC
    CM --> CS & VC
    AI --> AC & AS

    RC --> RCS
    AC --> RCS & L2

    VC --> L1
    CS --> L1
    EC --> L2
    AS --> L2

    RCS --> CONF[置信度合成]
    L1 --> SS[step_score<br/>= max L1, L2]
    L2 --> SS
    SS --> CONF
    CONF --> OUT[0 ~ 1 评分]
```
-->

---

## 关键代码位置

| 模块 | 文件 | 核心函数 |
|------|------|---------|
| 置信度计算主逻辑 | `src/pipeline.py` | `_fill_confidence()` |
| 通用根因判定 | `src/pipeline.py` | `_is_generic_rootcause()` |
| AI 报告解析 | `src/core/doc_generator.py` | `parse_conclusion()` / `parse_doc_steps()` |
| 语义相似度 | `src/core/semantic.py` | `semantic_similarity()` / `semantic_best_matches()` |
| TF-IDF 兜底 | `src/core/similarity.py` | `cosine_of_texts()` / `compare_root_cause()` |
| Diana LLM 对比 | `src/clients/diana_client.py` | `llm_similarity()` |
| 阈值配置 | `config/config.yaml` | `similarity.threshold: 0.7` |
