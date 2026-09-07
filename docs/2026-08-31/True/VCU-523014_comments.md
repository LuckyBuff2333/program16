# VCU-523014 评论分析总结

## 排查结论

已定位问题：MQTTMP服务pod损坏及指令无条件判断导致powerMode=2时仍触发云端短信唤醒，异常信息截断待补全。


**排查摘要**：已定位问题：MQTTMP服务pod损坏及指令无条件判断导致powerMode=2时仍触发云端短信唤醒


## 排查过程分析

### 问题现象
车辆已启动（powerMode=2）状态下仍收到远控唤醒请求，触发短信唤醒兜底，导致用户收到异常短信通知。

### 排查过程
| 步骤 | 排查动作 | 结果 | 关键证据 |
|------|----------|------|----------|
| 1 | 检查MQTTMP服务pod状态 | pod损坏，已修复 | 评论1："发现pod损坏，已修复" |
| 2 | 分析车端日志L911198 | 指令无条件判断逻辑 | "conditional_judgment=null 导致无条件唤醒" |
| 3 | 分析CoreService处理L911330 | 抛出RequestBuildException | "powerMode=2 状态下处理唤醒请求时抛出异常" |
| 4 | 检查异常信息完整性 | 错误文本被截断 | "fail request: --- 后具体错误缺失" |
| 5 | 定位短信唤醒触发点 | 确认在云端 | "车端无短信唤醒记录，触发点在bo.lscp.sgm.com" |
| 6 | 验证指令执行链路 | 执行成功 | "全程237ms，指令执行成功" |

### 排查结论
- **已确认事实**：MQTTMP服务pod曾损坏（评论1）；RemoteExecuteLocationTimestampCommand指令无条件判断（L911198）；CoreService在powerMode=2时抛RequestBuildException（L911330）；短信唤醒触发点在云端（L911204）；指令执行链路本身成功（L912304）。
- **待确认方向**：L911330处异常信息被截断，需补充完整错误堆栈；云端短信唤醒的具体触发规则和条件需进一步核查。
- **与AI日志分析一致点**：均确认conditional_judgment=null是无条件唤醒的根源，且短信唤醒触发点在云端。
- **与AI日志分析差异点**：AI分析未提及MQTTMP服务pod损坏这一基础设施问题；AI认为异常上报是短信唤醒的直接原因，而评论1显示pod修复可能已消除该问题，需验证修复后是否仍会触发。


## 时序排查详情

### AI日志分析

- conditional_judgment=null 导致无条件唤醒：`RemoteExecuteLocationTimestampCommand` 指令未携带条件判断逻辑，远控服务在车辆已启动时仍发起唤醒请求，这是触发短信唤醒的根源（L911198）
- 车辆已启动却收到唤醒请求导致异常：CoreService 在 powerMode=2 状态下处理 subsystem_active=true 的唤醒请求时抛出 RequestBuildException，该异常上报云端后触发短信唤醒兜底（L911330）
- RequestBuildException 异常信息被截断：L911330 处 `fail request: ---` 后的具体错误文本缺失，无法确认异常的确切原因（L911330）
- 短信唤醒触发点在云端：车端日志中无短信唤醒相关记录，短信唤醒的触发逻辑在云端（bo.lscp.sgm.com），车端只能证明前置条件成立（L911204）
- 指令执行链路本身成功：RemoteExecuteLocationTimestampCommand 从 MQTT 接收到响应返回全程 237ms，指令执行成功，短信唤醒与指令执行结果无关（L912304）

### 评论 1

**排查动作**: 排查MQTTMP服务pod

**排查结果**: 发现pod损坏，已修复

