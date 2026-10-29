# ADP 接口问题判别与处理策略

> 代码位置：`src/services/adp_ops.py`  
> 最后更新：2026-10-29

## 一、错误码四级分类与处理策略

ADP v2 Chat 接口返回的错误码（SSE `error` 事件中的 `Error.Code`）分为四类，每类处理策略不同：

### 1. 致命错误（Fatal）→ 立即终止

配置/账号级问题，发"继续"无效，必须修复配置后才能恢复。

| 错误码 | 含义 | 处理 |
|--------|------|------|
| `4505004` | AppKey 无效 | 检查 config.yaml 的 adp.app_key |
| `460001` | Token 校验失败 | 检查密钥是否正确 |
| `460004` | 应用不存在 | 检查应用是否已创建 |
| `460026` | 应用停用或欠费 | 联系平台管理员 |
| `460048` | 应用未发布 | 在 ADP 控制台发布应用 |
| `460501` | 输入内容安全拦截 | 检查输入内容 |
| `460502` | 输出内容安全拦截 | 检查模型输出 |
| `460032` | 模型余额不足 | 充值或切换模型 |
| `460702` | 专属模型余额不足 | 充值专属模型额度 |

**代码常量**：`FATAL_ERROR_CODES`  
**处理逻辑**：SSE 收到 error 事件 → break 终止流 → `run_adp_single` early return → 标记"分析失败"  
**归因格式**：`ADP平台配置错误: {含义}({错误码})`

---

### 2. 限流错误（Rate Limit）→ 退避后重发原始请求

并发/容量超限，等待后重发即可恢复。

| 错误码 | 含义 | 退避时间 |
|--------|------|----------|
| `460011` | QPM 并发超限 | 60s |
| `460031` | 并发限流 | 60s |
| `460711` | 空间级 TPM 限流 | 300s |
| `460712` | 空间级 QPM 限流 | 300s |
| `460713` | 空间级 RPM 限流 | 300s |
| `460721` | 应用级 TPM 限流 | 300s |
| `460722` | 应用级 QPM 限流 | 300s |
| `460723` | 应用级 RPM 限流 | 300s |

**代码常量**：`RATE_LIMIT_CODES`（并发）+ `CAPACITY_LIMIT_CODES`（容量）  
**处理逻辑**：SSE break → 续接机制 `need_resend` → 退避等待 → 重发原始消息（复用原会话 ID）  
**归因格式**：`ADP并发限流({错误码})` 或 `ADP容量限流({错误码})`

---

### 3. 可重试错误（Retryable）→ 发"继续"续接

模型侧临时问题，发"继续"即可恢复分析。

| 错误码 | 含义 | 处理 |
|--------|------|------|
| `460020` | 模型超时 | 发"继续"恢复分析 |
| `460030` | 模型服务异常 | 发"继续"恢复分析 |

**代码常量**：`RETRYABLE_ERROR_CODES`  
**处理逻辑**：SSE break → 续接机制 `need_continue`（含 `err_code in RETRYABLE_ERROR_CODES`）→ 发"继续"  
**归因格式**：`ADP模型超时({错误码})`

---

### 4. 需人工干预错误（Manual Intervention）→ 换新会话 ID 重试

会话级冲突，换新 ID 即可解决。

| 错误码 | 含义 | 处理 |
|--------|------|------|
| `460919` | 会话 ID 已存在 | 生成新 ConversationId 重试 |

**代码常量**：`SESSION_CONFLICT_CODES`  
**处理逻辑**：SSE break → 续接机制 `need_new_session` → 生成新 `uuid4().hex[:32]` → 用新 ID 重发原始消息  
**归因格式**：`ADP会话冲突({错误码})`

---

## 二、ReplyMethod 判别

`response.completed` 事件的 `ExtraInfo.ReplyMethod` 是判断分析结果的关键信号：

| ReplyMethod | 含义 | 处理策略 |
|-------------|------|----------|
| `1` | 正常回复 | 正常提取报告 |
| `12` | 正常回复（变体） | 正常提取报告 |
| `18` | 正常回复（变体） | 正常提取报告 |
| `3` | 拒答 | 停止续接，归因为"智能体收口无报告" |
| `7` | 并发超限 | 归因为"ADP并发超限(ReplyMethod=7)" |
| `15` | 澄清确认（等用户补充信息） | 停止续接，归因为"智能体收口无报告" |

**代码常量**：
- `NO_REPORT_REPLY_METHODS = {"3", "15"}` — 拒答/澄清
- `CONCURRENT_LIMIT_REPLY = "7"` — 并发超限

---

## 三、续接机制（Step 3.3）

当分析结果不满足预期时，自动触发续接，最多 2 轮：

```
触发条件                          → 动作
─────────────────────────────────────────────────────
完成状态=分析失败 + 归因="分析完成但未产出HTML报告"  → 发"继续"
_looks_truncated(full_text)     → 发"继续"
err_code ∈ RETRYABLE_ERROR_CODES   → 发"继续"
err_code ∈ RATE_LIMIT_CODES     → 退避60s/300s → 重发原始消息
无 full_text + request_ack + 无 stream_exc → 重发原始消息
err_code ∈ SESSION_CONFLICT_CODES   → 换新会话ID → 重发原始消息
```

**合并策略**：
- 续接返回的文本追加到 `full_text`
- 续接返回的 `file_urls` 追加到已有列表
- 重新调用 `extract_adp_results()` 提取结果
- 任一轮获得报告 URL 或完成状态为"完成"则停止

---

## 四、失败归因体系（classify_adp_failure）

按优先级从高到低自动归类：

| 优先级 | 判断条件 | 归因结果 |
|--------|----------|----------|
| 1 | 致命错误码 | `ADP平台配置错误: {含义}({码})` |
| 2a | 限流错误码 | `ADP并发限流({码})` / `ADP容量限流({码})` |
| 2b | 可重试错误码 | `ADP模型超时({码})` |
| 2c | 会话冲突码 | `ADP会话冲突({码})` |
| 3 | has_cards（追问卡片） | `ADP智能体追问（需人工作答）` |
| 4 | ReplyMethod=7 | `ADP并发超限(ReplyMethod=7)` |
| 4 | ReplyMethod=3/15 + 文本匹配 | `ADP智能体收口无报告({原因})` |
| 5 | error="无附件" | `输入质量问题（无附件）` |
| 5 | error 含"没有日志附件" | `输入质量问题（无有效日志文件）` |
| 5 | error="ADP 无返回" | `ADP连接超时或网络异常` |
| 6a | _looks_truncated | `ADP分析输出被截断({字数}、无收尾章节)` |
| 6b | 澄清/拒答关键词 | `ADP智能体收口无报告({原因})` |
| 6c | _looks_complete_no_report | `ADP报告渲染环节异常(分析主体完整但无报告链接)` |
| 6d | 短篇+日志链接为空 | `输入质量问题（日志附件链接为空）` |
| 6e | 短篇+描述矛盾 | `输入质量问题（描述矛盾或信息不足）` |
| 6f | 文本含404/下载失效 | `下载链接失效` |
| 6g | 传输中断 | `下载链接失效（传输中断）` |
| 6h | 签名URL异常 | `下载链接失效（签名URL响应异常）` |
| 6i | 分析过程关键词 | `分析过程未完成` |
| 7 | stream_exc | `ADP流异常: {详情}` |
| 7 | error 含 connect/timeout | `ADP连接超时或网络异常` |
| 兜底 | 以上均不命中 | `分析完成但未产出HTML报告` |

---

## 五、报告链接提取优先级（_extract_report_url）

**核心原则：签名 URL 始终优先于无签名 URL，避免 COS 403 Forbidden。**

| 优先级 | 来源 | 特征 | 说明 |
|--------|------|------|------|
| 1a | reply 文本 | `agent.adp-cos.com` + 含 `q-sign` | 最可靠，签名有效 |
| 2 | reply 文本 | `lke.cloud.tencent.com/s/xxx` | 短链，302 → COS 签名 URL |
| 3a | file_urls | `content.added` 事件 + 含 `q-sign` | SSE 流中捕获的签名 URL |
| 3b | file_urls | `content.added` 事件 + 无签名 | 降级使用 |
| 1b | reply 文本 | `agent.adp-cos.com` + 无签名 | 最后兜底（可能 403） |
| 4a | reply 文本 | `sandbox.adp.cloud.tencent.com` | 沙箱 URL（401 不可下载，仅展示） |
| 4b | reply 文本 | `/workdir/case_.../out/report_...html` | 沙箱路径（拼接为 4a 格式） |

### 签名 URL 判断标准

URL 的 query 参数中包含 `q-sign` 相关字段即为签名 URL：

```
?q-sign-algorithm=sha1
&q-ak=AKIDxxx
&q-sign-time=xxx
&q-signature=xxx
```

无签名的裸路径（如 `https://agent.adp-cos.com/agent-app/.../report_xxx.html`）会被 COS CDN 拒绝返回 **403 Forbidden**。

### 已知陷阱

- ADP 智能体有时在 reply 文本中只放**无签名的裸路径 URL**，但 `content.added` 事件的 `file_urls` 中有带签名的正确 URL
- 旧代码用 `re.search` 匹配到第一个就 return，导致拿到无签名 URL → 403
- 修复后扫描所有匹配，按签名优先排序，确保拿到可用的签名 URL

---

## 六、辅助判别信号

### Content.Type 信号

| Type | 含义 | 处理 |
|------|------|------|
| `file` | 文件产物 | 收集到 file_urls |
| `option_cards` | 追问卡片 | 标记 has_cards，发"继续"无效 |
| `questionnaire` | 问卷 | 标记 has_cards，发"继续"无效 |

### 文本形态判断

| 函数 | 条件 | 判定 |
|------|------|------|
| `_looks_truncated` | ≥2000字 + 无收尾章节 + 非终止符结尾 | 疑似截断，发"继续" |
| `_looks_like_clarify_or_refusal` | ReplyMethod=3/15 或关键词命中 | 拒答/澄清，停止续接 |
| `_looks_complete_no_report` | ≥800字 + ≥2个收尾章节标志 | 主体完整但缺报告 |

### 澄清/拒答关键词

**澄清类**：请提供、请补充、请上传、请确认、无法下载、无法获取、缺少日志…  
**拒答类**：无法分析、无法处理、不能分析、拒绝回答、不予回答
