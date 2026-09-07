# VCU-215859 评论分析总结

## 排查结论

主驾车门ajax状态持续false，VCU与BDF信号链路正常，已排除远程互斥；停止逻辑未响应车门变化，需对手件乘客门状态订阅进一步排查。


**排查摘要**：主驾车门ajax状态持续false，VCU与BDF信号链路正常，已排除远程互斥；停止逻辑未响应车门变化


## 排查过程分析

### 问题现象
主驾车门开启后，闪灯鸣笛功能未按预期停止，持续激活约20秒，且主驾车门ajax状态持续为false，疑似停止逻辑未响应车门状态变化。

### 排查过程
| 步骤 | 排查动作 | 结果 | 关键证据 |
|------|----------|------|----------|
| 1 | 上传日志附件 | 已上传log.zip和someip.log | 附件2140706 (1124 7-19-2025 11-25-49 am.zip) |
| 2 | 查看主驾车门ajax状态 | 持续false，需对手件核查 | Line 76799/78681/78918: resp.getDDAjrSwAtv():false |
| 3 | 添加崩溃截图附件 | 已上传现场图片 | 评论5附件 |
| 4 | 总线数据复测分析 | VCU正常下发，BDF正常响应 | 11:23:47-11:24:07；11:24:14-11:24:34；11:23:54-11:23:57 |
| 5 | 补充分析 | 排除远程互斥操作可能 | 评论7（基于评论5分析） |

### 排查结论
- **已确认的事实**：主驾车门ajax状态持续为false（Line 76799/78681/78918），VCU总线数据正常下发且BDF正常响应（11:23:47-11:24:07等时间段），排除远程互斥操作可能（评论7）。
- **尚未确认需进一步排查的方向**：需对手件（乘客门）进行核查，确认乘客门打开事件是否被停止逻辑正确捕获；需检查ActivateHornRequestProcessor是否订阅了乘客门状态（PDAjrSwAtv）。
- **与AI日志分析结论的一致点**：均确认主驾车门状态为false且信号链路正常（SomeIP信号传递无异常）。
- **与AI日志分析结论的差异点**：AI分析指出停止逻辑可能仅覆盖驾驶员门而未覆盖乘客门（未发现PDAjrSwAtv订阅证据），而Jira评论中未提及乘客门状态核查，仅聚焦于主驾车门ajax状态；AI分析发现11:24:15.018出现第4次ActivateHorn调用，而Jira评论未涉及该时间点的重复激活行为。


## 时序排查详情

### AI日志分析

- 停止逻辑未响应乘客门打开事件：乘客门打开后无任何 DeactivateHorn/StopHorn 调用，闪灯鸣笛持续激活（11:23:54.311 ~ 11:24:15.018，HornStatusMapper / ActivateHornRequestProcessor）
- 停止逻辑可能仅覆盖驾驶员门：ActivateHornRequestProcessor 未发现车门状态订阅/监听注册的证据，停止条件可能仅检查 DDAjrSwAtv 而未覆盖 PDAjrSwAtv（11:23:54.311，ActivateHornRequestProcessor）
- 车门打开后仍有新的 ActivateHorn 调用：11:24:15.018 出现第 4 次 ActivateHorn 调用，说明停止逻辑在整个执行周期内均未生效（11:24:15.018，ActivateHornRequestProcessor）
- SomeIP 信号链路正常：乘客门打开事件从 ts::someip::plugin 到 AccessSomeIpClient 的传递在同一时间戳完成，信号链路无异常（11:23:54.311，ts::someip::plugin / AccessSomeIpClient）
- 请求链路完整且延迟合理：MQTT 接收到 ActivateHorn 执行耗时约 613ms，链路无异常（11:23:12.306 ~ 11:23:12.919，MqttManager / ActivateHornRequestProcessor）

### 评论 1

**排查动作**: 添加日志附件

**排查结果**: 已上传log.zip和someip.log


### 评论 2

**排查动作**: 添加附件日志压缩包

**排查结果**: 已上传1124日志文件


**日志证据**:

```
附件 2140706 (1124 7-19-2025 11-25-49 am.zip)
```


### 评论 3

**排查动作**: (Comment from 陈

**排查结果**: (Comment from 陈传峰)
/


### 评论 4

**排查动作**: 查看主驾车门ajax状态

**排查结果**: ajax状态持续false，需对手件核查


**日志证据**:

```
Line 76799: 07-19 11:23:47.891  4304 29096 D AccessSomeIpClient: resp.getDDAjrSwAtv():false
Line 78681: 07-19 11:23:48.791  4304 29096 D AccessSomeIpClient: resp.getDDAjrSwAtv():false
Line 78918: 07-19 11:23:48.882  4304 29096 D AccessSomeIpClient: resp.getDDAjrSwAtv():false
Line 81066: 07-19 11:23:49.783  4304 29096 D AccessSomeIpClient: resp.getDDAjrSwAtv():false
Line 81324: 07-19 11:23:49.899  4304 29096 D AccessSomeIpClient: resp.getDDA
```


### 评论 5

**排查动作**: 添加崩溃截图附件

**排查结果**: 已上传现场图片


### 评论 6

**排查动作**: 总线数据复测分析

**排查结果**: VCU正常下发，BDF正常响应


**日志证据**:

```
11：23：47-11：24：07
11：24：14-11：24：34
11：23：54-11：23：57
11：24：08-11：24：10
11：24：19-11：24：22
11：24：32-11：24：33
```


### 评论 7

**排查动作**: 补充comments5分析

**排查结果**: 排除远程互斥操作可能

