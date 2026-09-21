# 日志分析报告

### ① 执行摘要

**问题描述简表**

| 项目 | 内容 |
|------|------|
| Bug 标题 | [Setting][NCUB韩国][实车][UserDebug][R6] 倒车自动下翻后视镜不记忆 |
| 预期结果 | 倒车自动下翻后视镜记忆上次设置位置 |
| 实际结果 | 无记忆，只会固定下翻到同一个默认位置 |
| 分析时间范围 | 2026-08-25 12:52:57 ~ 13:02:57（日志实际覆盖 13:02:45.974 ~ 13:02:56.994） |

**核心结论**

<div style="background:#fef0f0;border:1px solid #fde2e2;border-radius:8px;padding:16px;margin:12px 0;">
<strong style="color:#f56c6c;">🔴 核心矛盾：</strong>用户调节倒车自动下翻后视镜并挂 R 档，期望恢复上次记忆的下翻位置，但 CleaNewDriverHabitManager 中 <code>mRestoreDriverHabitFlow</code> 和 <code>mHabitRestoreResult</code> 两个关键变量始终为 null，记忆恢复流程从未启动，导致后视镜只能使用固定默认位置下翻。
</div>

**因果链图**

```
12:55:22.477  CLEA_DRIVER_HABIT_DATA_EVENT 触发 dealDriverHabitDataEvent
                    ↓
12:55:22.477  mHabitRestoreResult is null（赋值代码路径从未执行）
                    ↓
12:55:22.736  CLEA2_DRIVER_HABIT_RESULT_EVENT 触发 dealDriverHabitResultEvent
                    ↓
12:55:22.736  mRestoreDriverHabitFlow is null（赋值代码路径从未执行）
                    ↓
              记忆恢复流程从未启动
                    ↓
              用户设置的下翻位置（horizontal_angle: 0.1, vertical_angle: 4.9）未被回读应用
                    ↓
              挂 R 档时后视镜使用固定默认位置下翻
                    ↓
              Bug 表现：倒车自动下翻后视镜"无记忆"
```

**置信度**：中（medium）——根因方向明确（两个关键变量未赋值），但赋值代码路径为何从未执行的具体前置条件尚不明确，需进一步排查初始化链路。

**错误码精确含义**：未发现具体错误码。核心异常为 `mRestoreDriverHabitFlow is null` 和 `mHabitRestoreResult is null`，表示记忆恢复流程和恢复结果均未初始化。

---

### ② 问题根因

这个问题的直接原因是 CleaNewDriverHabitManager 中的两个核心变量——`mRestoreDriverHabitFlow`（记忆恢复流程对象）和 `mHabitRestoreResult`（记忆恢复结果）——从未被赋值，始终为 null。当 CLEA 驱动习惯数据事件和结果事件触发时，处理函数检测到这两个变量为空，直接跳过了记忆恢复逻辑。全量 404301 行日志中搜索不到任何对这两个变量的赋值语句，说明赋值代码路径在本次运行中从未执行。这导致用户此前设置的下翻角度（水平 0.1°、垂直 4.9°）虽然成功发送到了设置侧，但从未被持久化恢复流程回读和应用，挂 R 档时后视镜只能使用出厂默认位置下翻。至于赋值代码路径为何从未执行，可能依赖某个前置条件（如用户 Profile 加载、CLEA 连接建立、Manager 初始化完成等）在日志时间窗口内未满足，但当前日志无法确认具体是哪个环节缺失。

---

### ③ 关键证据与日志原文

**证据 1：记忆恢复结果始终为空，恢复流程从未启动**

```log
12:55:22.477  CleaNewDriverHabitManager:dealDriverHabitDataEvent  mHabitRestoreResult is null
12:55:22.581  CleaNewDriverHabitManager:dealDriverHabitDataEvent  mHabitRestoreResult is null
12:55:22.688  CleaNewDriverHabitManager:dealDriverHabitDataEvent  mHabitRestoreResult is null
12:55:22.805  CleaNewDriverHabitManager:dealDriverHabitDataEvent  mHabitRestoreResult is null
12:55:23.030  CleaNewDriverHabitManager:dealDriverHabitDataEvent  mHabitRestoreResult is null
12:55:23.137  CleaNewDriverHabitManager:dealDriverHabitDataEvent  mHabitRestoreResult is null
12:55:23.363  CleaNewDriverHabitManager:dealDriverHabitDataEvent  mHabitRestoreResult is null
```

> 7 次数据事件触发均检测到 `mHabitRestoreResult` 为 null，说明记忆恢复结果从未产生。全量日志中搜索 `mHabitRestoreResult\s*=` 无任何匹配，赋值代码路径从未执行。

**证据 2：记忆恢复流程对象始终为空**

```log
12:55:22.736  CleaNewDriverHabitManager:dealDriverHabitResultEvent  mRestoreDriverHabitFlow is null
12:55:23.036  CleaNewDriverHabitManager:dealDriverHabitResultEvent  mRestoreDriverHabitFlow is null
12:55:23.339  CleaNewDriverHabitManager:dealDriverHabitResultEvent  mRestoreDriverHabitFlow is null
12:55:23.943  CleaNewDriverHabitManager:dealDriverHabitResultEvent  mRestoreDriverHabitFlow is null
12:55:24.242  CleaNewDriverHabitManager:dealDriverHabitResultEvent  mRestoreDriverHabitFlow is null
```

> 5 次结果事件触发均检测到 `mRestoreDriverHabitFlow` 为 null。全量日志中搜索 `mRestoreDriverHabitFlow\s*=` 无任何匹配，流程对象从未被创建或注入。

**证据 3：后视镜反馈值异常归零**

```log
12:55:22.433  LeftMirrorFeatureHandle:dealDataChange  data feature is 2
12:55:22.434  mDriverMirrorFeedback 值为 2
12:55:22.730  LeftMirrorFeatureHandle:dealDataChange  data feature is 0
12:55:22.730  dealDriverMirrorFeedbackEvent  主驾后视镜反馈 is 0
12:55:22.735  dealPassengerMirrorFeedbackEvent  副驾后视镜反馈 is 0
12:55:23.036  mDriverMirrorFeedback 从 2 变为 0
```

> 左后视镜 feature 状态从 2 切换为 0，主/副驾后视镜反馈值同步归零，表明后视镜控制状态发生了异常切换，可能与记忆恢复流程未启动导致的默认位置覆盖有关。

**证据 4：后视镜位置反馈链路正常（对照组）**

```log
12:55:22.688  CarDataSource  left mirror position:-6.7 -0.2 0.0
12:55:22.804  CarDataSource  left mirror position:-7.1 -0.2 0.0
12:55:22.913  CarDataSource  left mirror position:-7.4 -0.2 0.0
12:55:23.363  CarDataSource  right mirror position:-5.2 0.1 0.0
```

> 硬件→GMVHAL→CarDataSource 的位置上报链路持续正常工作，说明问题不在硬件或底层数据采集，而在上层的记忆恢复逻辑。

**证据 5：设置侧角度接收正常（对照组）**

```log
12:56:34.205  RightRearviewMirrorAvailableTopic  收到 responding_feature: MF_TILT_MIRROR, horizontal_angle: 0.1, vertical_angle: 4.9
```

> 设置界面调节的角度数据成功到达后视镜控制链路，说明实时通信正常，但记忆恢复是独立的持久化流程，实时通信正常不代表记忆恢复已启动。

---

### ④ 状态时间线

| 时间 | 事件 | 状态值 | 来源 |
|------|------|--------|------|
| 12:55:22.433 | LeftMirrorFeatureHandle feature 状态 | **2** | main.log |
| 12:55:22.434 | mDriverMirrorFeedback 值 | **2** | main.log |
| 12:55:22.477 | ⚠️ dealDriverHabitDataEvent 检测 | **mHabitRestoreResult is null** | main.log |
| 12:55:22.688 | CarDataSource 左后视镜位置 | -6.7 -0.2 0.0（正常） | main.log |
| 12:55:22.730 | ⚠️ LeftMirrorFeatureHandle feature 切换 | **2 → 0** | main.log |
| 12:55:22.730 | ⚠️ 主驾后视镜反馈归零 | **0** | main.log |
| 12:55:22.735 | ⚠️ 副驾后视镜反馈归零 | **0** | main.log |
| 12:55:22.736 | ⚠️ dealDriverHabitResultEvent 检测 | **mRestoreDriverHabitFlow is null** | main.log |
| 12:55:23.036 | ⚠️ mDriverMirrorFeedback 归零确认 | **2 → 0** | main.log |
| 12:55:23.363 | CarDataSource 右后视镜位置 | -5.2 0.1 0.0（正常） | main.log |
| 12:56:34.205 | RightRearviewMirrorAvailableTopic 接收 | MF_TILT_MIRROR, 0.1°/4.9°（正常） | main.log |

---

### ⑤ 根因分析与关键发现

- 🔴 **记忆恢复流程对象未初始化**：`mRestoreDriverHabitFlow` 在 5 次结果事件触发时均为 null，全量日志无赋值记录，流程对象从未创建（12:55:22.736~12:55:24.242，CleaNewDriverHabitManager）
- 🔴 **记忆恢复结果未产生**：`mHabitRestoreResult` 在 7 次数据事件触发时均为 null，全量日志无赋值记录，恢复结果从未写入（12:55:22.477~12:55:23.363，CleaNewDriverHabitManager）
- 🟡 **后视镜反馈值异常归零**：`mDriverMirrorFeedback` 从 2 变为 0，主/副驾反馈同步归零，可能与默认位置覆盖有关（12:55:22.434→12:55:23.036，dealDriverMirrorFeedbackEvent）
- 🟡 **左后视镜 feature 状态异常切换**：feature 从 2 切换为 0，控制状态发生非预期变化（12:55:22.433→12:55:22.730，LeftMirrorFeatureHandle）
- 🔵 **位置反馈链路正常**：CarDataSource 持续上报左右后视镜位置数据，硬件和底层上报无异常（12:55:22.688~12:55:23.363，CarDataSource）
- 🔵 **设置侧角度接收正常**：RightRearviewMirrorAvailableTopic 收到 MF_TILT_MIRROR 及角度数据，实时通信链路无异常（12:56:34.205，RightRearviewMirrorAvailableTopic）

---

### ⑥ 修复建议

**代码级建议（优先）**

1. **排查 CleaNewDriverHabitManager 的初始化链路**：确认 `mRestoreDriverHabitFlow` 和 `mHabitRestoreResult` 的赋值代码路径及其前置条件。建议在 Manager 初始化完成处添加日志，确认初始化是否被调用：

```java
// CleaNewDriverHabitManager 初始化处添加日志
Log.d(TAG, "CleaNewDriverHabitManager init, mRestoreDriverHabitFlow=" + mRestoreDriverHabitFlow 
    + ", mHabitRestoreResult=" + mHabitRestoreResult);
```

2. **在赋值处添加日志**：在 `mRestoreDriverHabitFlow` 和 `mHabitRestoreResult` 的赋值语句处添加日志，确认赋值条件是否满足：

```java
// 赋值处添加日志
mRestoreDriverHabitFlow = createRestoreFlow();
Log.d(TAG, "mRestoreDriverHabitFlow assigned: " + mRestoreDriverHabitFlow);
```

3. **检查前置条件依赖**：确认赋值是否依赖用户 Profile 加载、CLEA 连接建立、初始化完成事件等。如果依赖，在依赖条件满足处添加日志，确认在问题时间窗口内这些条件是否已满足。

**排查方向**

4. **搜索初始化相关日志**：在日志中搜索 CleaNewDriverHabitManager 的 init/onCreate/onStart/registerListener 等关键词，确认 Manager 是否完成了初始化。
5. **搜索用户登录/Profile 加载日志**：搜索 UserAccount、Profile、Login 等 TAG，确认用户 Profile 是否已加载完成。
6. **搜索 CLEA 连接建立日志**：搜索 CLEA、Connection、Connect 等关键词，确认 CLEA 连接是否已建立。
7. **对比正常场景日志**：获取记忆功能正常时的日志，对比 `mRestoreDriverHabitFlow` 和 `mHabitRestoreResult` 的赋值时机和触发条件。

---

### ⑦ 未覆盖信息

1. **赋值代码路径未执行的具体原因**：当前日志无法确认 `mRestoreDriverHabitFlow` 和 `mHabitRestoreResult` 的赋值代码路径为何从未执行。这是定位根因的关键缺口，需要补充 CleaNewDriverHabitManager 的初始化日志和赋值条件日志。

2. **问题时间偏差**：Bug 描述中的问题时间为 12:57:57，但日志中观察到的异常时间为 12:55:22~12:55:24，存在约 2 分钟偏差。需要确认这两个时间点之间的关联性，以及 12:57:57 时刻是否有其他相关事件发生。

3. **下翻请求的具体参数**：OSRVMTiltControlRequestProcessor 和 OSRVMDirectionRequestProcessor 处理下翻请求时使用的具体角度参数未在日志中打印，无法直接验证是否使用了固定默认值。建议在下翻请求处理处添加参数日志。

**建议补充措施**：
- 在 CleaNewDriverHabitManager 的初始化、赋值、事件处理三个关键节点添加日志，覆盖完整生命周期
- 复现问题时同时抓取用户登录/Profile 加载/CLEA 连接建立的相关日志，确认前置条件是否满足
- 对比正常场景（记忆功能正常）与异常场景的日志差异，定位赋值路径未执行的具体断点