# ADP v2 Chat 接口问题判别与处理策略

> 基于官方文档 + `adp_agent_driver.py` 实战经验整理，供 `adp_ops.py` 改造参考。

---

## 一、SSE 事件流全景（共 14 种）

```
请求发出
  │
  ├─ request_ack          ← 请求被受理（限流/安全拦截时不会收到）
  │
  ├─ response.created     ← 响应开始（有 TraceId）
  │
  ├─ response.processing  ← 响应处理中
  │
  ├─ message.added        ← 消息增加
  ├─ message.processing   ← 消息处理中（Agent 工具调用过程）
  ├─ content.added        ← 内容增加（text/file/option_cards/questionnaire）
  ├─ text.delta           ← 文本增量
  ├─ text.replace         ← 文本替换（完整文本或 closeout JSON）
  ├─ message.done         ← 单条消息完成
  │
  ├─ error                ← ⚠️ 错误事件（致命/限流/安全拦截）
  │
  ├─ response.completed   ← 本轮响应完成（Status + ExtraInfo.ReplyMethod）
  │
  └─ done / [DONE]        ← 流结束
```

### 各事件关键字段

| 事件 | 关键字段 | 用途 |
|---|---|---|
| `request_ack` | `RequestAck.RecordId`, `RequestAck.ConversationId` | 确认请求被受理；限流秒拒时无此事件 |
| `response.created` | `TraceId`/`trace_id`, `Timestamp` | 提取 trace_id + 计算 start_ts |
| `text.delta` | `Text` | 增量文本拼接（注意 latin-1→UTF-8 修复） |
| `text.replace` | `Text` | 替换整段文本或 closeout JSON（含 ok/html 字段时） |
| `content.added` | `Content.Type`, `Content.File`, `Content.OptionCards`, `Content.Questionnaire` | 文件产物 / 追问卡片 / 问卷 |
| `message.done` | `Message.Contents[]` | 单条消息完整内容（兜底取全文） |
| `response.completed` | `Response.Status`, `Response.ExtraInfo.ReplyMethod`, `Response.Messages[]` | 判断本轮是否成功 + 回复方式 |
| `error` | `Error.Code`, `Error.Message`, `Error.TraceId` | 错误分类处理 |

---

## 二、错误码分级（64 个错误码，按处理策略分 4 类）

### 2.1 致命错误（配置/账号级，发"继续"无效，应立即终止）

| 错误码 | 含义 | 处理 |
|---|---|---|
| `4505004` | AppKey 无效 | 终止，检查配置 |
| `460001` | Token 校验失败 | 终止 |
| `460004` | 应用不存在 | 终止 |
| `460026` | 应用停用或欠费 | 终止 |
| `460048` | 应用未发布 | 终止 |
| `460501` | 输入内容不合法（安全拦截） | 终止 |
| `460502` | 输出内容不合法（安全拦截） | 终止 |
| `460032` | 当前应用模型余额不足 | 终止 |
| `460702` | 专属模型余额不足 | 终止 |

**归因映射**：`分析失败归因 = "ADP平台配置错误: {错误码} {错误信息}"`

### 2.2 限流错误（应退避后原样重发，不计入"继续"预算）

| 错误码 | 含义 | 退避时间 |
|---|---|---|
| `460011` | 超出应用 QPM 并发限制 | 60s |
| `460031` | 超出应用 QPS 并发限制 | 60s |
| `460711` | 空间 TPM 超限（容量类） | 300s |
| `460712` | 空间 QPM 超限（容量类） | 300s |
| `460713` | 空间每日 Token 超限 | 300s |
| `460721` | 应用 TPM 超限（容量类） | 300s |
| `460722` | 应用 QPM 超限（容量类） | 300s |
| `460723` | 应用每日 Token 超限 | 300s |

**关键判断**：
- 限流时**没有 `request_ack`**（请求未被受理），会话是空的
- 必须**原样重发原始请求**，不能发"继续"（会话里没有上下文）
- 容量类（TPM/QPM/每日 Token）退避 300s，纯并发类（QPM/QPS）退避 60s

### 2.3 可重试错误（发"继续"让智能体接着跑）

| 错误码 | 含义 | 处理 |
|---|---|---|
| `460020` | 模型请求超时 | 发"继续" |
| `460401` | 请求处理超时 | 发"继续" |
| `500` | 服务器内部错误 | 重试或发"继续" |
| `460007` | 会话创建失败 | 新 ConversationId 重试 |

### 2.4 需人工介入

| 错误码 | 含义 | 处理 |
|---|---|---|
| `460919` | 会话 ID 已存在 | 换新 ConversationId 重试 |
| `460034` | 输入内容过长 | 截断后重试 |
| `460038` | AppID 请求存在异常行为 | 人工排查 |

---

## 三、ReplyMethod 含义（response.completed 里的关键信号）

`Response.ExtraInfo.ReplyMethod` 取值说明：

| 值 | 含义 | 对我们项目的影响 |
|---|---|---|
| `0` | 未指定 | - |
| `1` | 大模型直接回复 | ✅ 正常分析 |
| `2` | 未知问题回复 | ⚠️ 可能分析质量低 |
| **`3`** | **拒答问题回复** | **❌ 分析失败：智能体拒绝回答** |
| `4` | 敏感回复 | ⚠️ 内容被过滤 |
| `5` | 已采纳问答对优先回复 | ✅ 正常 |
| `6` | 欢迎语回复 | ❌ 异常：不应在分析场景出现 |
| `7` | 并发数超限回复 | ⚠️ 限流信号 |
| `8` | 全局干预知识 | ✅ 正常 |
| `9` | 任务流回复 | ✅ 正常 |
| `10` | 任务流答案 | ✅ 正常 |
| `11` | 搜索引擎回复 | ✅ 正常 |
| `12` | 知识润色后回复 | ✅ 正常 |
| `13` | 图片理解回复 | ✅ 正常 |
| `14` | 实时文档回复 | ✅ 正常 |
| **`15`** | **澄清确认回复** | **❌ 分析失败：智能体在等用户补充信息** |
| `16` | 工作流回复 | ✅ 正常 |
| `17` | 工作流运行结束 | ✅ 正常 |
| `18` | 智能体回复 | ✅ 正常（最常见） |
| `19` | 多意图回复 | ✅ 正常 |

---

## 四、Content.Type 交互信号

| Type | 含义 | 对我们的影响 |
|---|---|---|
| `text` | 文本 | 正常处理 |
| `file` | 文件（HTML 报告等） | ✅ 提取报告链接 |
| **`option_cards`** | **选项卡片** | **❌ 智能体在等用户选择，发"继续"无效** |
| **`questionnaire`** | **问卷追问** | **❌ 智能体在等用户作答，发"继续"无效** |
| `sandbox` | 沙箱信息 | 提取沙箱 URL |
| `json_text` | JSON 文本 | 可能包含结构化数据 |
| `image` | 图片 | 截图等 |

### 追问卡片检测

`option_cards` 字段结构：
```json
{
  "Type": "option_cards",
  "OptionCards": ["选项A", "选项B", "选项C"],
  "OptionMode": 0  // 0=单选, 1=多选
}
```

`questionnaire` 字段结构：
```json
{
  "Type": "questionnaire",
  "Questionnaire": {
    "Title": "问卷标题",
    "Questions": [
      {
        "Question": "问题内容",
        "Type": 1,  // 1=单选, 2=多选
        "Options": [{"Label": "选项A"}, {"Label": "选项B"}]
      }
    ]
  }
}
```

---

## 五、无报告时的回复形态判断

### 5.1 疑似截断（发"继续"）

**三条件同时成立**：
1. 回复 > 2000 字（短回复谈不上截断）
2. 没有任何收尾章节（归因/根因/修复建议/决策点/结论）
3. 末尾不是终止符（。！？…）)】」》"'）

```python
COMPLETE_SECTION_MARKERS = ["归因", "根因", "修复建议", "决策点", "待办与缺口", "结论"]

def looks_truncated(reply):
    if len(reply) < 2000:
        return False
    if any(k in reply for k in COMPLETE_SECTION_MARKERS):
        return False
    return reply.rstrip()[-1:] not in "。！？!?…）)】」》\"'"
```

### 5.2 澄清/拒答（发"继续"无效，直接标失败）

**ReplyMethod 判断优先**：
- ReplyMethod=3 → 拒答
- ReplyMethod=15 → 澄清确认

**文本关键词兜底**（仅短篇回复 < 4000 字时生效）：
```python
CLARIFY_KEYWORDS = ["请提供", "请补充", "请上传", "请确认", "请重新提供",
                    "无法下载", "无法获取", "无法访问", "下载失败", "未找到日志"]
REFUSAL_KEYWORDS = ["无法分析", "无法处理", "不能分析", "拒绝回答"]
```

> **长度护栏**（< 4000 字）：真实的澄清/拒答回复是短篇；几万字的分析叙事中段出现"无法分析"只是局部描述，不是拒答。

### 5.3 主体完整但无报告（先继续一次补报告）

**判据**：≥ 800 字 + 命中 ≥ 2 个收尾章节标志

```python
def looks_complete_no_report(reply):
    if len(reply) < 800:
        return False
    hits = [k for k in COMPLETE_SECTION_MARKERS if k in reply]
    return len(hits) >= 2
```

处理策略：第一次发"继续"触发补报告，再犯则标失败。

---

## 六、"首轮未开工"检测（最隐蔽的问题）

TPM 秒拒时的状态：`request_ack` 到了、`record` 也建了，但模型没跑、无 token、无实质回复。
此时发"继续" = 会话里只有"继续"两个字，原始请求彻底丢失。

### 判据

```python
# 历史轮次从未有过实质回复
started = any((t.get("reply_chars") or 0) > 0 for t in prior_turns)

# 本轮"实质回复"三条件
cur_meaningful = (
    bool(tr.reply.strip())                              # 有文本
    and tr.reply.strip() != tr.error_msg.strip()        # 不是错误文案本身
    and (tr.status != "failed" or len(tr.reply) > 50)   # 非 failed 或长于50字
)

# 边界兜底：failed 且回复含 TPM/QPM 字样 → 容量错误文案
reply_head = tr.reply[:200]
if tr.status == "failed" and ("TPM" in reply_head or "QPM" in reply_head):
    cur_meaningful = False

# 未开工 = 历史没开工 + 本轮也没开工 + 有错误/失败
if not started and not cur_meaningful and (tr.error_code or tr.status == "failed"):
    # → 原样重发原始请求，不能发"继续"
```

---

## 七、完整判别决策树

```
无报告时：
  │
  ├─ 1. 流中断（SSE 断连/停摆/整轮超时）
  │     → 发"继续"，等 300s（断流≠智能体死了）
  │
  ├─ 2. error 事件
  │     ├─ 限流码 + 未被受理(无 ack) → 退避后原样重发
  │     ├─ 限流码 + 已被受理 → 退避后发"继续"
  │     ├─ 致命码 → 立即终止
  │     └─ 其他错误码 → 发"继续"
  │
  ├─ 3. Status = failed / stop
  │     → 发"继续"（平台侧未正常完成）
  │
  ├─ 4. 追问卡片（option_cards / questionnaire）
  │     → 异常终止（需人工作答，继续无效）
  │
  ├─ 5. Status = success 时的回复形态三判：
  │     ├─ 疑似截断 → 发"继续"
  │     ├─ 澄清/拒答 → 异常终止
  │     ├─ 主体完整但无报告 → 第一次继续，再犯异常
  │     └─ 无法判断 → 谨慎继续
  │
  └─ 6. "继续"预算耗尽
        → exhausted 终态
```

---

## 八、咱们项目当前差距与改造点

### 8.1 `call_adp_sse_stream()` 需增加的事件处理

| 事件 | 当前状态 | 需增加 |
|---|---|---|
| `error` | ❌ 未处理 | 识别错误码，分类处理 |
| `request_ack` | ❌ 未处理 | 标记请求被受理 |
| `response.completed` | ❌ 未处理 | 提取 Status + ReplyMethod |
| `message.done` | ❌ 未处理 | 兜底取完整回复 |
| `content.added` | ⚠️ 只处理 `file` | 增加 `option_cards`/`questionnaire` 检测 |

### 8.2 `classify_adp_failure()` 需增强

当前归因：
```python
# 只有粗略的：无附件/无日志/连接超时/未产出报告
```

需增加：
- 致命错误码映射 → `"ADP平台配置错误: {code}"`
- 限流错误码映射 → `"ADP并发限流: {code}"`
- ReplyMethod=3 → `"ADP智能体拒答"`
- ReplyMethod=15 → `"ADP智能体要求补充信息"`
- 追问卡片 → `"ADP智能体追问（需人工）"`
- 截断检测 → `"ADP分析输出被截断"`
- 主体完整无报告 → `"ADP报告渲染环节异常"`

### 8.3 `run_adp_single()` 需增加续接机制

当前：无报告直接标失败

需增加：
- 同一 ConversationId 发"继续"
- 最大继续次数（建议 2~3 次）
- 退避等待（流断等 300s，正常收口等 60s）
- 限流重发（原样重发原始请求）

---

## 九、相关常量定义（供代码参考）

```python
# 致命错误码：重试/继续均无意义
FATAL_ERROR_CODES = {
    "4505004", "460001", "460004", "460026", "460048",
    "460501", "460502", "460032", "460702"
}

# 并发限流码：原样重发
RATE_LIMIT_CODES = {"460011", "460031"}

# 容量类限流码（TPM/QPM，分钟级窗口，退避 300s）
CAPACITY_LIMIT_CODES = {
    "460711", "460712", "460713",   # 空间级
    "460721", "460722", "460723",   # 应用级
}

# 拒答/澄清 ReplyMethod
NO_REPORT_REPLY_METHODS = {"3", "15"}

# 澄清/索取信息话术关键词
CLARIFY_KEYWORDS = [
    "请提供", "请补充", "请上传", "请确认", "请重新提供",
    "无法下载", "无法获取", "无法访问", "下载失败", "未找到日志",
    "缺少日志", "需要您提供", "需要您确认"
]

# 拒答话术关键词
REFUSAL_KEYWORDS = [
    "无法分析", "无法处理", "不能分析", "拒绝回答", "不予回答"
]

# 回复完整收尾章节标志
COMPLETE_SECTION_MARKERS = [
    "归因", "根因", "修复建议", "决策点", "待办与缺口", "结论"
]

# 报告链接提取正则
REPORT_PATTERNS = [
    r"(?:报告链接|报告已生成|报告地址)\s*[:：]?\s*[^\n]*?(https?://\S+)",
    r"(https?://\S*?/observatory/\S+?\.html\S*)",
    r"(https?://\S+\.html\S*)",
]
```

---

> **文档版本**: v1.0  
> **最后更新**: 2026-10-28  
> **来源**: 腾讯云官方文档 + `adp_agent_driver.py` 实战经验
