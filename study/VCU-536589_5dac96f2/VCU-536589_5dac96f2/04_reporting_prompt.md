# System Prompt

你是一个日志分析报告生成专家。基于裁决结果和工具执行数据生成高可读性分析报告。

## 可读性核心原则（必须严格遵守）

1. **结论前置**：① 必须是执行摘要，读者看完第一章就知道根因、因果链和修复方向。不要埋结论。② 问题根因紧接着用大白话直接回答"问题是什么原因造成的"。
2. **因果链可视化**：使用纯文本箭头图展示问题传播路径，例如：
   ```
   03:17:14 StageCoordinator 因 RETURN_HOME 退出分屏
           ↓
   03:17:14 分屏模式关闭 (isInSplitMode: false)
           ↓
   03:27:02 ICSActivity.onResume 无条件调用 setScreenMode(2)
           ↓
   03:27:02 NaviView(switch_map_bt) 可见 ← Bug 表现
   ```
   不依赖 mermaid 图，使用 ↓↑←→ 箭头和缩进即可。
3. **关键日志原文**：每个证据组必须用 ``` 代码块贴出原始日志行（含时间戳、PID、TAG），不能只用跳转链接代替。读者需要在报告中直接看到日志内容。
4. **按需生成章节**：无数据的章节直接跳过，不生成空洞占位。例如没有对比数据就不生成"对比分析"章节。
5. **严格去重（最重要）**：同一事实只在报告中出现一次。
   - 因果链图**仅在 ① 中出现**，禁止在 ③④⑤⑥ 中重复描述
   - 证据日志行**仅在 ③ 中展示**，⑤ 根因分析用一句话引用即可，禁止重复贴日志
   - 状态时间线如果在 ③ 中已经通过证据展示清楚，**不再单独生成 ④ 表格**
   - ② 问题根因用自然语言概述，不重复 ① 的因果链图和 ⑤ 的分级列表
6. **叙事优先**：用"故事线"组织内容——为什么出问题 → 证据是什么 → 怎么修复，而非机械填表。
7. **证据精确**：每个结论必须附上原始日志文本，同时标注时间戳和 TAG。
8. **篇幅控制**：报告总长度控制在 **100~150 行**以内。如果超出，优先删减重复内容和冗余章节。

## 报告章节框架

报告标题固定为 `# 日志分析报告`，**仅在最开头输出一次，禁止在后续章节前重复**。不包含模块名。
严格按以下框架生成报告。章节编号使用中文圆圈数字（①②③...），章节标题必须与实际内容匹配。

### ① 执行摘要（必须有）

这是读者最先看到的内容，必须包含：

1. **问题描述简表**（仅 4 行：Bug 标题、预期结果、实际结果、分析时间范围）
2. **核心结论**：一句话概括"操作 → 期望 → 实际"的矛盾，用红色框高亮：
   ```html
   <div style="background:#fef0f0;border:1px solid #fde2e2;border-radius:8px;padding:16px;margin:12px 0;">
   <strong style="color:#f56c6c;">🔴 核心矛盾：</strong>{一句话概括}
   </div>
   ```
3. **因果链图**：纯文本箭头图，展示从根因到 Bug 表现的完整传播路径，每个节点标注时间戳
4. **置信度**：高/中/低，一句话说明理由
5. **错误码精确含义**（如有错误码）

### ② 问题根因（必须有）

用 **2~4 句大白话** 直接回答"这个问题是什么原因造成的"。

要求：
- 不贴日志原文、不用行号引用（那些留给 ③⑤）
- 不复述 ① 的因果链图，而是用自然语言把根因讲清楚
- 让非技术背景的读者也能看懂问题出在哪里
- 如果根因涉及多个因素，按主次顺序说明

示例：
> 这个问题的原因是 ICSActivity 的 onResume 方法中无条件调用了 setScreenMode(2)，
> 没有检查当前是否处于分屏模式。当用户从分屏切回全屏时，StageCoordinator 已经
> 退出了分屏状态，但 ICSActivity 重新 onResume 时又把屏幕模式强制设回了双屏，
> 导致导航界面在非预期时刻弹出。

### ③ 关键证据与日志原文（必须有）

按证据组分组展示，每组包含：

- **证据标题**：一句话概括这组证据说明了什么
- **原始日志代码块**：用 ``` 包裹，贴出 3-8 行最关键的原始日志（含时间戳、PID、TAG）
- **一行解读**：用 `>` 引用块说明这段日志的含义

证据分组示例：
- 证据 1：分屏状态已退出（system.log）
- 证据 2：NaviView 仍可见且可交互（main.log）
- 证据 3：setScreenMode 被无条件调用（main.log）

每个证据组同时附上时间戳和 PID 信息。

### ④ 状态时间线（有状态变化数据时必须生成）

用表格展示完整的状态变化时间线。表格列：时间 | 事件 | 状态值 | 来源。
状态变化用 **粗体** 标注，异常事件用 ⚠️ 标注。

数据来源：structured_evidence 中的 timeline 和 state_comparison 数据。

### ⑤ 根因分析与关键发现（必须有）

按严重程度三级分类。**此处不重复贴日志原文**，仅用一句话因果说明。每条格式：

```
- 🔴/🟡/🔵 **{发现标题}**：{一句话结论}（{时间戳}，{TAG}）
```

- **🔴 Critical**：直接导致功能失败的核心问题
- **🟡 Important**：影响功能可靠性的重要异常
- **🔵 Info**：值得关注的辅助信息

### ⑥ 修复建议（必须有）

给出具体、可操作的修复方向：
- 优先给出代码级建议（如能推断出具体方法名，给出伪代码片段）
- 其次给出配置级建议
- 最后给出排查方向（当根因不完全确定时）

数据来源：structured_evidence 中的 recommended_actions 数据。

### ⑦ 未覆盖信息（必须有）

列出当前日志无法覆盖但对诊断重要的信息，每条说明为什么重要。
给出 1-3 条建议补充措施（如添加日志、复现对比场景等）。

## 禁止生成的内容

- 禁止空洞占位表格（所有列都是 "-" 或 "如适用"）
- 禁止没有数据的章节（如"对比分析"但实际无对比数据）
- **禁止同一发现在多个章节重复**：因果链只在 ①，问题根因只在 ②，日志原文只在 ③，根因分级只引用不重复
- 禁止猜测类名/方法名，除非有工具查询结果支持
- 禁止用 mermaid 图代替文字叙述
- 禁止只有链接但没有日志原文的证据

## 数据使用优先级

- 结构化证据（structured_evidence）优先：signal_chain、timeline、state_comparison、e2e_timing 直接使用
- 裁决结果（conclusions、core_conflict、causal_chain）作为报告核心结论
- 推理历史证据摘要（evidence_summary）作为补充细节



---

# User Prompt

## 裁决结果
### 结论列表
[{"statement": "CleaNewDriverHabitManager 中 mRestoreDriverHabitFlow 始终为 null，dealDriverHabitResultEvent 在 12:55:22.736、12:55:23.036、12:55:23.339、12:55:23.943、12:55:24.242 多次触发时均检测到该变量未赋值，记忆恢复流程从未启动", "confidence": "high", "evidence_refs": ["R12"], "line_refs": ["L12:55:22.736", "L12:55:23.036", "L12:55:23.339", "L12:55:23.943", "L12:55:24.242"], "category": "confirmed", "severity": "critical", "root_cause_or_symptom": "root_cause"}, {"statement": "mHabitRestoreResult 始终为 null，dealDriverHabitDataEvent 在 12:55:22.477、12:55:22.581、12:55:22.688、12:55:22.805、12:55:23.030、12:55:23.137、12:55:23.363 多次触发时均检测到记忆恢复结果为空，全量 404301 行日志中 mRestoreDriverHabitFlow\\s*= 和 mHabitRestoreResult\\s*= 均无匹配，赋值代码路径从未执行", "confidence": "high", "evidence_refs": ["R12"], "line_refs": ["L12:55:22.477", "L12:55:22.581", "L12:55:22.688", "L12:55:22.805", "L12:55:23.030", "L12:55:23.137", "L12:55:23.363"], "category": "confirmed", "severity": "critical", "root_cause_or_symptom": "root_cause"}, {"statement": "mDriverMirrorFeedback 从 12:55:22.434 的 2 变为 12:55:23.036 的 0，dealDriverMirrorFeedbackEvent 主驾后视镜反馈 is 0（12:55:22.730）、dealPassengerMirrorFeedbackEvent 副驾后视镜反馈 is 0（12:55:22.735），后视镜反馈值异常归零", "confidence": "high", "evidence_refs": ["R12"], "line_refs": ["L12:55:22.434", "L12:55:22.730", "L12:55:22.735", "L12:55:23.036"], "category": "confirmed", "severity": "important", "root_cause_or_symptom": "symptom"}, {"statement": "LeftMirrorFeatureHandle:dealDataChange data feature 从 12:55:22.433 的 2 变为 12:55:22.730 的 0，左后视镜 feature 状态异常切换", "confidence": "high", "evidence_refs": ["R12"], "line_refs": ["L12:55:22.433", "L12:55:22.730"], "category": "confirmed", "severity": "important", "root_cause_or_symptom": "symptom"}, {"statement": "后视镜位置反馈链路正常：CarDataSource 持续上报 left mirror position:-6.7 -0.2 0.0（12:55:22.688）、-7.1 -0.2 0.0（12:55:22.804）、-7.4 -0.2 0.0（12:55:22.913）、right mirror position:-5.2 0.1 0.0（12:55:23.363），GMVHAL 持续上报 MIRROR_POSITION_STATUS，说明后视镜硬件反馈和位置上报链路正常", "confidence": "high", "evidence_refs": ["R12"], "line_refs": ["L12:55:22.688", "L12:55:22.804", "L12:55:22.913", "L12:55:23.363"], "category": "confirmed", "severity": "info", "root_cause_or_symptom": "observation"}, {"statement": "设置侧角度接收正常：RightRearviewMirrorAvailableTopic 收到 responding_feature: MF_TILT_MIRROR，horizontal_angle: 0.1，vertical_angle: 4.9（12:56:34.205），设置侧与反馈侧角度数据一致，未发现参数丢失", "confidence": "medium", "evidence_refs": ["R12"], "line_refs": ["L12:56:34.205"], "category": "confirmed", "severity": "info", "root_cause_or_symptom": "observation"}, {"statement": "R 档信号正常：getVehicleGear 返回 1，挂 R 档时档位信号正确传递，暂未发现 R 档触发时序异常", "confidence": "medium", "evidence_refs": ["R12"], "line_refs": [], "category": "possible", "severity": "info", "root_cause_or_symptom": "observation"}]

### 核心矛盾
用户调节倒车自动下翻后视镜并挂R档期望记忆上次设置位置，但 CleaNewDriverHabitManager 的 mRestoreDriverHabitFlow 和 mHabitRestoreResult 始终为 null，记忆恢复流程从未启动，导致后视镜只能固定下翻到默认位置

### 错误码含义
未发现具体错误码，核心异常为 mRestoreDriverHabitFlow is null 和 mHabitRestoreResult is null，表示记忆恢复流程和恢复结果均未初始化

### 因果链
mRestoreDriverHabitFlow 和 mHabitRestoreResult 赋值代码路径从未执行（全量日志无赋值语句）→ 记忆恢复流程从未启动 → dealDriverHabitResultEvent 检测到 mRestoreDriverHabitFlow is null → dealDriverHabitDataEvent 检测到 mHabitRestoreResult is null → 用户设置的下翻位置未被恢复 → 挂 R 档时后视镜使用固定默认位置下翻 → 表现为'无记忆'

### 整体置信度
medium

### 冲突与解决
[{"description": "后视镜位置反馈链路正常（CarDataSource 持续上报位置数据）与记忆恢复流程未启动（mHabitRestoreResult is null）之间的矛盾", "resolution": "位置反馈链路（硬件→GMVHAL→CarDataSource）与记忆恢复流程（CleaNewDriverHabitManager）是两条独立链路。位置反馈正常仅说明硬件和底层上报正常，但记忆恢复流程未启动导致用户设置的位置无法被回读和应用，两者不矛盾"}, {"description": "设置侧角度接收正常（RightRearviewMirrorAvailableTopic 收到 MF_TILT_MIRROR 角度数据）与记忆恢复结果为空之间的矛盾", "resolution": "设置侧角度接收正常说明设置界面与后视镜控制链路的实时通信正常，但记忆恢复（mHabitRestoreResult）是独立的持久化恢复流程，实时通信正常不代表记忆恢复流程已启动"}]

### 未确认项
- mRestoreDriverHabitFlow 和 mHabitRestoreResult 的赋值代码路径为何从未执行——是否依赖某个前置条件（如用户 Profile 加载、CLEA 连接建立、初始化完成事件）在日志时间窗口内未满足
- CleaNewDriverHabitManager 的初始化流程和赋值条件的具体逻辑（知识库中未找到 DriverHabit 记忆机制相关文档）
- 记忆恢复流程的启动触发条件是什么（是否依赖用户登录状态、Profile 加载完成等）
- OSRVMTiltControlRequestProcessor 和 OSRVMDirectionRequestProcessor 处理下翻请求时使用的具体角度参数（日志不打印请求参数，无法直接验证是否使用了固定默认值）
- 问题发生时间 12:57:57 与日志中观察到的异常时间 12:55:22~12:55:24 之间的关联性（Bug 描述中的问题时间与日志异常时间存在约 2 分钟偏差）
- mDriverMirrorFeedback 从 2 变为 0 的具体触发原因和影响

## 结构化证据
### 信号链路（请求+回调）
{"request_chain": [{"node": "Setting 界面调节倒车自动下翻后视镜", "input": "用户操作", "output": "设置角度 horizontal_angle: 0.1, vertical_angle: 4.9", "latency": "未追踪到", "pid": "未追踪到", "line": "L12:56:34.205"}, {"node": "RightRearviewMirrorAvailableTopic", "input": "设置角度数据", "output": "responding_feature: MF_TILT_MIRROR", "latency": "未追踪到", "pid": "未追踪到", "line": "L12:56:34.205"}, {"node": "CleaNewDriverHabitManager:dealDriverHabitDataEvent", "input": "CLEA_DRIVER_HABIT_DATA_EVENT", "output": "mHabitRestoreResult is null", "latency": "未追踪到", "pid": "未追踪到", "line": "L12:55:22.477"}, {"node": "CleaNewDriverHabitManager:dealDriverHabitResultEvent", "input": "CLEA2_DRIVER_HABIT_RESULT_EVENT", "output": "mRestoreDriverHabitFlow is null", "latency": "未追踪到", "pid": "未追踪到", "line": "L12:55:22.736"}], "callback_chain": [{"node": "GMVHAL", "input": "后视镜位置传感器", "output": "MIRROR_POSITION_STATUS", "latency": "未追踪到", "pid": "1371", "line": "L12:55:22.688"}, {"node": "CarDataSource", "input": "GMVHAL 位置数据", "output": "left mirror position:-6.7 -0.2 0.0", "latency": "未追踪到", "pid": "未追踪到", "line": "L12:55:22.688"}, {"node": "LeftMirrorFeatureHandle:dealDataChange", "input": "feature 数据", "output": "feature is 2 → feature is 0", "latency": "未追踪到", "pid": "未追踪到", "line": "L12:55:22.433 → L12:55:22.730"}, {"node": "dealDriverMirrorFeedbackEvent", "input": "主驾后视镜反馈", "output": "主驾后视镜反馈 is 0", "latency": "未追踪到", "pid": "未追踪到", "line": "L12:55:22.730"}, {"node": "dealPassengerMirrorFeedbackEvent", "input": "副驾后视镜反馈", "output": "副驾后视镜反馈 is 0", "latency": "未追踪到", "pid": "未追踪到", "line": "L12:55:22.735"}]}

### 状态对比
field=mRestoreDriverHabitFlow | before=未赋值（null） | after=未赋值（null） | anomaly=异常 - 记忆恢复流程从未启动，赋值代码路径从未执行
field=mHabitRestoreResult | before=未赋值（null） | after=未赋值（null） | anomaly=异常 - 记忆恢复结果从未产生
field=mDriverMirrorFeedback | before=2（12:55:22.434） | after=0（12:55:23.036） | anomaly=异常 - 反馈值从 2 归零，可能表示反馈状态异常切换
field=LeftMirrorFeatureHandle feature | before=2（12:55:22.433） | after=0（12:55:22.730） | anomaly=异常 - feature 状态从 2 切换为 0
field=left mirror position | before=-6.7 -0.2 0.0（12:55:22.688） | after=-7.4 -0.2 0.0（12:55:22.913） | anomaly=正常 - 位置持续变化，反馈链路正常
field=right mirror position | before=未追踪到 | after=-5.2 0.1 0.0（12:55:23.363） | anomaly=正常 - 位置反馈正常

### 时间线
time=12:55:22.433 | event=LeftMirrorFeatureHandle:dealDataChange data feature is 2 | detail=左后视镜 feature 状态为 2 | pid=未追踪到 | line=L12:55:22.433
time=12:55:22.434 | event=mDriverMirrorFeedback 值为 2 | detail=主驾后视镜反馈值为 2 | pid=未追踪到 | line=L12:55:22.434
time=12:55:22.477 | event=dealDriverHabitDataEvent mHabitRestoreResult is null | detail=记忆恢复结果为空，恢复流程未启动 | pid=未追踪到 | line=L12:55:22.477
time=12:55:22.688 | event=CarDataSource:left mirror position:-6.7 -0.2 0.0 | detail=左后视镜位置反馈正常 | pid=未追踪到 | line=L12:55:22.688
time=12:55:22.730 | event=dealDriverMirrorFeedbackEvent 主驾后视镜反馈 is 0 | detail=主驾后视镜反馈值归零 | pid=未追踪到 | line=L12:55:22.730
time=12:55:22.730 | event=LeftMirrorFeatureHandle:dealDataChange data feature is 0 | detail=左后视镜 feature 状态切换为 0 | pid=未追踪到 | line=L12:55:22.730
time=12:55:22.735 | event=dealPassengerMirrorFeedbackEvent 副驾后视镜反馈 is 0 | detail=副驾后视镜反馈值归零 | pid=未追踪到 | line=L12:55:22.735
time=12:55:22.736 | event=dealDriverHabitResultEvent mRestoreDriverHabitFlow is null | detail=记忆恢复流程为空，恢复流程未启动 | pid=未追踪到 | line=L12:55:22.736
time=12:55:23.036 | event=mDriverMirrorFeedback 从 2 变为 0 | detail=主驾后视镜反馈值异常归零 | pid=未追踪到 | line=L12:55:23.036
time=12:55:23.363 | event=CarDataSource:right mirror position:-5.2 0.1 0.0 | detail=右后视镜位置反馈正常 | pid=未追踪到 | line=L12:55:23.363
time=12:56:34.205 | event=RightRearviewMirrorAvailableTopic 收到 MF_TILT_MIRROR | detail=设置侧角度接收正常，horizontal_angle: 0.1, vertical_angle: 4.9 | pid=未追踪到 | line=L12:56:34.205

### 端到端耗时
chain=记忆恢复流程启动链路 | start_node=CLEA_DRIVER_HABIT_DATA_EVENT 触发 | end_node=mHabitRestoreResult 赋值 | start_time=12:55:22.477 | end_time=未发生 | latency=未完成（赋值从未执行）
chain=记忆恢复结果处理链路 | start_node=CLEA2_DRIVER_HABIT_RESULT_EVENT 触发 | end_node=mRestoreDriverHabitFlow 赋值 | start_time=12:55:22.736 | end_time=未发生 | latency=未完成（赋值从未执行）
chain=后视镜位置反馈链路 | start_node=GMVHAL 上报 | end_node=CarDataSource 输出 | start_time=12:55:22.688 | end_time=12:55:23.363 | latency=约 675ms（持续上报）
chain=设置侧角度接收链路 | start_node=Setting 界面调节 | end_node=RightRearviewMirrorAvailableTopic 接收 | start_time=未追踪到 | end_time=12:56:34.205 | latency=未追踪到

### 建议排查方向
- 查阅 CleaNewDriverHabitManager 的源码或设计文档，确认 mRestoreDriverHabitFlow 和 mHabitRestoreResult 的赋值条件（如是否依赖用户 Profile 加载、CLEA 连接建立、初始化完成事件等前置条件），并在日志中搜索这些前置条件的触发日志
- 在日志中搜索 CleaNewDriverHabitManager 的初始化相关日志（如 init、onCreate、onStart、registerListener 等），确认该 Manager 是否完成了初始化
- 搜索用户登录/Profile 加载相关日志（如 UserAccount、Profile、Login 等 TAG），确认在问题发生时间窗口内用户 Profile 是否已加载完成
- 搜索 CLEA 连接建立相关日志（如 CLEA、Connection、Connect 等关键词），确认 CLEA 连接是否已建立
- 对比正常场景（记忆功能正常时）的日志，确认 mRestoreDriverHabitFlow 和 mHabitRestoreResult 在正常场景下的赋值时机和触发条件
- 检查 mDriverMirrorFeedback 从 2 变为 0 的原因，搜索相关赋值和状态切换日志，确认该变化是否与记忆恢复流程未启动有关

## 关键证据摘要（来自推理层搜索过程）
推理层共执行 0 轮搜索（详细过程见推理历史）

## 分析链路信息
### 分析时间范围
2026-08-25 12:52:57 ~ 13:02:57（问题时间 2026-08-25 12:57:57，前5分钟 ~ 后5分钟）
日志实际覆盖: 08-25 13:02:45.974 ~ 08-25 13:02:56.994

### 问题描述
【Bug标题】[Setting][NCUB韩国][实车][UserDebug][R6]12；57  倒车自动下翻后视镜不记忆

问题发生时间:
(未填写)

初始设定 Initial Setting:
run

操作顺序 Operation Schedule:
1.调节倒车自动下翻后视镜
2.返回界面
3.挂R档

预期结果 Expect Result:
1.倒车自动下翻后视镜记忆上次设置位置

执行结果 Actual Result:
无记忆（只会固定保存在同一个位置）


### 选择模块
core_service

### 日志来源
/home/ai-agent-ladt/文档/LogAnalysisBackend/filtered/jira/VCU-536589/filtered_time_only.log (404301 行)

### 日志文件
/home/ai-agent-ladt/文档/LogAnalysisBackend/filtered/jira/VCU-536589/filtered_time_only.log

### 总行数
404301

请基于以上信息生成分析报告，标题为 `# 日志分析报告`，章节结构按照系统 prompt 的 ①-⑦ 框架（①执行摘要→②问题根因→③关键证据→④状态时间线→⑤根因分析→⑥修复建议→⑦未覆盖信息），总长度控制在 100~150 行以内：