# 触发时间自学习（TimeStudy）功能说明

## 1. 功能定位

触发时间自学习是平台的**数据驱动优化闭环**，对每次触发时间提取的全过程（来源、结果、错误、流水线步骤）做持久化记录，再通过深度分析识别错误模式、顽固 Jira 和流水线断点，辅助开发者优化提取策略。

```
触发时间提取（每次执行自动记录）
        │
        ▼
 data/timestudy/records.csv（原始记录）
        │
        ▼
 _timestudy_analyze()（深度分析）
        │
        ├──► data/timestudy/error_patterns.json（结构化分析结果）
        └──► reports/timestudy/optimization_log.md（自动分析报告）

 timestudy/optimization_log.md（人工维护：提取优先级 + 历史变更记录）
```

---

## 2. 数据记录

### 2.1 记录时机

每条记录在**触发时间提取完成后**自动写入，调用链：

```
_bot_get_trigger_times()  →  _diag_extract_time_from_video_simple()  →  _timestudy_record()
                              _jc.extract_trigger_time_from_issue()  ↗
```

- 代码位置：`src/services/trigger_ops.py` → `_timestudy_record()`
- 存储路径：`data/timestudy/records.csv`

### 2.2 CSV 字段定义

| 列名 | 说明 | 示例 |
|------|------|------|
| jira号 | Jira Bug 编号 | VCU-536589 |
| 记录时间 | 记录写入时间戳 | 2026-10-13 10:30:45 |
| 提取来源 | 结果来自哪个提取路径 | video_ocr / text_fallback / cloud_cache / empty |
| 提取结果 | 提取到的触发时间（成功时有值） | 2026-09-28 14:35:22 |
| 是否正确 | 用户审核标记 | unknown / corrected |
| 错误类型 | 失败时的分类标签 | video_download_failed / ocr_no_time_pattern / all_sources_empty |
| 错误详情 | 失败原因的详细描述 | 视频下载超时(30s) |
| 修正后时间 | 人工修正后的正确时间 | 2026-09-28 14:35:22 |
| 视频数量 | Jira 附件中视频文件数 | 3 |
| gmlogger数量 | gmlogger 附件数 | 1 |
| 参考时间 | gmlogger 文件名解析出的参考时间 | 2026-09-28 14:30:00 |
| OCR原文 | OCR 识别出的原始文字 | 14:35:22 触发异常 |
| 匹配差秒 | 提取时间与参考时间的差值（秒） | 22 |
| 12h转换 | 是否使用了 12h 制转换 | yes / no |
| jira创建时间 | Jira Issue 创建时间 | 2026-09-28 10:00:00 |
| trace_steps | 提取流水线各步骤记录（箭头连接） | video:3→gm:1→dl:ok→frame:ok→ocr:hit→full:hit→result:video_hit |

### 2.3 Trace 步骤编码

trace_steps 字段记录提取流水线的完整路径，每个步骤格式为 `步骤码:参数`：

| 步骤码 | 中文含义 | 说明 |
|--------|----------|------|
| cloud | 云端缓存 | 检查云端多维表格是否已有触发时间 |
| diag | 诊断缓存 | 检查本地诊断缓存 |
| video | 视频附件检查 | 检查 Jira 附件中的视频文件数量 |
| gm | gmlogger 解析 | 解析 gmlogger 附件获取参考时间 |
| dl | 视频下载 | 从 Jira 下载视频文件 |
| frame | 帧提取 | 使用 ffmpeg 提取视频帧 |
| ocr | OCR 识别 | 对视频帧做 OCR 文字识别 |
| full | 完整时间匹配 | 将 OCR 文字与参考时间做严格匹配 |
| 12h | 12h 转换 | AM/PM 歧义时做 12h 制转换匹配 |
| cache | 缓存命中 | 视频时间缓存命中（跳过重复 OCR） |
| fn | 文件名回退 | OCR 失败时从视频文件名提取时间 |
| partial | 部分结果兜底 | 多视频场景下使用部分匹配结果 |
| text | 文本提取回退 | 视频提取失败，回退到标题/评论/描述提取 |
| result | 最终结果 | 提取成功的最终标记 |
| fetch | Jira 获取 | 获取 Jira Issue 数据 |
| skip | 前置跳过 | 无 gmlogger 等前置条件不满足时跳过 |

---

## 3. 提取上下文管理

每次提取前通过一组函数管理上下文，确保记录包含完整诊断信息：

| 函数 | 作用 | 代码位置 |
|------|------|----------|
| `_timestudy_init_ctx(bugid)` | 初始化提取上下文 | trigger_ops.py |
| `_timestudy_trace(bugid, step)` | 追加一步流水线记录 | trigger_ops.py |
| `_timestudy_update_ctx(bugid, **kwargs)` | 更新上下文属性 | trigger_ops.py |
| `_timestudy_get_ctx(bugid)` | 获取并清除上下文 | trigger_ops.py |
| `_timestudy_record(bugid, result, source, ...)` | 写入 CSV 记录 | trigger_ops.py |

上下文结构：
```python
{
    "source": "",           # 提取来源
    "error_type": "",       # 错误类型
    "error_detail": "",     # 错误详情
    "video_count": 0,       # 视频数量
    "gm_count": 0,          # gmlogger 数量
    "ref_times": "",        # 参考时间
    "ocr_text": "",         # OCR 原文
    "match_diff": "",       # 匹配差秒
    "h12": "no",            # 12h 转换标记
    "jira_created": "",     # Jira 创建时间
    "trace": []             # 流水线步骤列表
}
```

---

## 4. 深度分析

### 4.1 触发方式

- **API 调用**：`POST /api/timestudy/analyze`，支持 `after_time` 时间过滤
- **飞书机器人**：发送 "timestudy" / "自学习" / "触发时间学习" 关键词
- **函数调用**：`_timestudy_analyze(after_time="")`

代码位置：`src/services/server_legacy.py` → `_timestudy_analyze()`

### 4.2 分析维度

| 维度 | 说明 |
|------|------|
| **基础统计** | 总记录数、成功率、成功/失败/跳过计数、用户修正数、12h 转换数 |
| **错误分布** | 按错误类型聚合计数，排序输出 Top N |
| **提取来源分布** | 按来源聚合计数和占比 |
| **顽固 Jira 检测** | 同一 Jira 出现 2+ 次失败记录，标记为顽固 |
| **共性特征分析** | 每种错误类型的失败记录是否共享特征（无视频占比、无 gmlogger 占比、12h 占比、时间范围） |
| **错误分类** | 基于共性特征将错误分为：系统性问题（≥3 个 Jira + 有共性）、顽固问题（单 Jira 3+ 次）、偶发问题 |
| **流水线断点分析** | 解析 trace_steps，找出失败时断在哪一步 |
| **常见提取路径** | 统计 Top 5 最常见的完整 trace 路径 |

### 4.3 输出产物

#### error_patterns.json（`data/timestudy/error_patterns.json`）

```json
{
  "total_records": 120,
  "skip_count": 10,
  "effective_total": 110,
  "success_count": 85,
  "fail_count": 25,
  "corrected_count": 3,
  "h12_count": 8,
  "success_rate": 77.3,
  "error_distribution": { "video_download_failed": 10, "ocr_no_time_pattern": 8, ... },
  "source_distribution": { "video_ocr": 60, "text_fallback": 25, ... },
  "stubborn_jiras": { "VCU-123456": 3, "VCU-789012": 2 },
  "error_analysis": {
    "video_download_failed": {
      "count": 10,
      "unique_jiras": 5,
      "stubborn_jiras": ["VCU-123456"],
      "no_video_pct": 0,
      "no_gm_pct": 20,
      "h12_pct": 10,
      "date_range": "2026-09-20~2026-10-10",
      "common_features": ["时间范围: 2026-09-20~2026-10-10"],
      "classification": "系统性问题",
      "example_jiras": ["VCU-111111", "VCU-222222"],
      "breakpoints": [{ "step": "dl", "desc": "视频下载", "count": 8, "pct": 80 }],
      "main_breakpoint": "视频下载 (80%)"
    }
  },
  "breakpoint_summary": [
    { "step": "dl", "desc": "视频下载", "count": 8 },
    { "step": "ocr", "desc": "OCR识别", "count": 5 }
  ],
  "common_trace_patterns": [
    { "trace": "video:1→gm:1→dl:ok→frame:ok→ocr:hit→full:hit→result:video_hit", "count": 45 }
  ],
  "generated_at": "2026-10-13 10:00:00"
}
```

#### optimization_log.md（`timestudy/optimization_log.md`）

人工维护的触发时间提取优化日志，仅记录**通用时间提取逻辑**的变更（逻辑变更时追加，偶发失败不入库）。

文档结构：
1. **当前时间提取逻辑** — Mermaid 流程图展示提取优先级链（视频帧 OCR → ref_pool 验证 → 12h/文件名回退 → 图片 OCR 兜底 → 标题/评论/描述/自定义字段 → gmlogger 文件名补日期）
2. **历史变更记录** — 每条含问题描述、相关 Bug 号、根因、解决方案

> 原始失败记录见 `timestudy/records/records_YYYY-MM-DD.csv`；分析快照见 `timestudy/error_patterns*.json`。

---

## 5. API 接口

| 端点 | 方法 | 说明 | 代码位置 |
|------|------|------|----------|
| `/api/timestudy/analyze` | POST | 触发深度分析，支持 `after_time` 过滤 | timestudy.py |
| `/api/timestudy/summary` | GET | 获取最新分析摘要（轻量，不重新分析） | timestudy.py |
| `/api/timestudy/records` | GET | 获取最近 N 条自学习记录（`?limit=50`） | timestudy.py |
| `/api/timestudy/root-causes` | POST | 批量查询 Jira 的上次提取根因 | timestudy.py |

### 请求/响应示例

**触发分析：**
```
POST /api/timestudy/analyze
Body: { "after_time": "2026-10-01" }
Response: { "ok": true, "data": { ...error_patterns... }, "msg": "自学习分析完成: 120条记录, 成功率77.3%, Top3错误: ..." }
```

**根因查询：**
```
POST /api/timestudy/root-causes
Body: { "bugids": ["VCU-123456", "VCU-789012"] }
Response: {
  "ok": true,
  "data": {
    "VCU-123456": {
      "root_cause": "视频下载",
      "trace": "video:2→gm:1→dl:fail",
      "error_type": "video_download_failed",
      "source": "empty",
      "result": ""
    }
  }
}
```

---

## 6. 目录结构

```
timestudy/                          ← 功能文档（本文件所在目录）
  ├── README.md                     ← 功能说明文档（本文件）
  ├── optimization_log.md           ← 触发时间提取优化日志（提取优先级 + 历史变更记录）
  └── records/                      ← 原始失败记录
      └── records_YYYY-MM-DD.csv   ← 按日期归档的失败记录

data/timestudy/                     ← 运行时数据
  ├── records.csv                   ← 自学习原始记录（追加写入）
  └── error_patterns*.json          ← 深度分析快照

reports/timestudy/                  ← 自动生成的分析报告
  └── optimization_log.md           ← 可读优化日志（覆盖写入）

data/{日期}/                        ← 每日触发时间存档
  └── trigger_times_{日期}.csv      ← 当日提取结果
```

---

## 7. 错误类型枚举

| 错误类型 | 触发场景 | 常见断点 |
|----------|----------|----------|
| video_download_failed | 视频文件下载超时或失败 | dl（视频下载） |
| ocr_no_time_pattern | OCR 识别了文字但无法匹配时间模式 | ocr（OCR识别） |
| ocr_empty | OCR 未识别到任何文字 | ocr（OCR识别） |
| time_no_match_gmlogger | 提取的时间与 gmlogger 参考时间不匹配 | full（完整匹配） |
| no_video | Jira 无视频附件 | video（视频检查） |
| all_sources_empty | 所有来源（视频+文本）均未提取到时间 | text（文本回退） |
| 12h_ambiguity | 12h 制 AM/PM 歧义无法判定 | 12h（12h转换） |
| gmlogger_missing | 无 gmlogger 参考文件 | gm（gmlogger解析） |
| user_corrected | 用户人工修正了提取结果 | — |
| fetch_failed | Jira API 请求失败 | fetch（Jira获取） |
| video_failed_text_fallback | 视频提取失败，回退到文本提取 | text（文本回退） |
