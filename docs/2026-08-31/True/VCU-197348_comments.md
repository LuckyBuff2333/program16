# VCU-197348 评论分析总结

## 排查结论

快速制冰模式下发热饮模式闪跳已定位，根因是手机端UI状态被旧pub覆盖，当前问题已定位待复测验证。


## 排查过程分析

### 问题现象
快速制冰模式下，手机端发热饮模式显示在热饮/非热饮间来回闪跳，无法稳定显示。

### 排查过程
| 步骤 | 排查动作 | 结果 | 关键证据 |
| :--- | :--- | :--- | :--- |
| 1 | 上传复现视频与日志 | 已提供素材待分析 | 评论1 |
| 2 | 复制工作项1023144 | 无新排查，仅复制记录 | 评论2 |
| 3 | 复现快速制冰下发热饮 | 手机端模式显示跳变回热饮 | `IDPCB0C0330B:2025-04-17 10:50:17.396 mqtt---08---startCommonCmdPush` |
| 4 | 添加附件截图 | 已添加附件，待分析 | 评论4 |
| 5 | 检查gmlog时间点 | 日志未覆盖当前时间点 | `main.log_2025_4_17_10_50_17` |
| 6 | 补充log并请求重新分析 | 等待重新分析 | 评论6 |
| 7 | 上传复现视频与日志 | 提供问题复现素材 | 评论7 |
| 8 | 优化完成，通知复测 | 已优化，待复测验证 | 评论9 |
| 9 | 确认远控服务更新状态 | 车端未集成，暂不可测 | 评论10 |
| 10 | 确认远控联调状态 | 车端未集成VCU，暂不可测 | 评论11 |
| 11 | 远控功能联调检查 | 车端未集成VCU，暂不可测 | 评论12-14 |
| 12 | 评估车端版本可测性 | 车端未发布，远控链路不通 | 评论15 |
| 13 | 实车复测切换模式 | 问题复现，模式来回闪跳 | `VCU:20250418-UQB26C-24-R1`, `bug time：2025/05/07 14:44` |
| 14 | 分析手机端日志 | UI状态被旧pub覆盖 | 评论20 |
| 15 | 分析车端pub数据时序 | A指令上报晚于B指令，页面跳变 | 评论21 |
| 16 | 分析请求与回调时序 | 未出现请求未发送即收到回调 | `Line 137104: processRequest`, `Line 138896: SUCCESS: NOTIFY_FRIDGE_STATU` |
| 17 | 分析超时日志与代码逻辑 | 超时逻辑设计为2s*6，需修改 | `05-07 14:44:14.335 E RemoteSetCLEAFridgeRequestProcessor: poll time out!` |

### 排查结论
- **已确认的事实**：问题在实车（VCU:20250418-UQB26C-24-R1, APP:11.16.24）上稳定复现，时间点为2025/05/07 14:44。手机端UI状态被旧pub覆盖，车端A指令上报晚于B指令导致页面跳


## 时序排查详情

### AI日志分析

- loopCheckCleaFridgeState 状态回环机制：远控处理进程（PID 17551）中的循环检查函数导致 mSubCleaFridgeStatus 在 CFSS_ON/CFSS_OFF 间反复切换，是模式闪跳的直接根因（14:43:18~14:45:51，RemoteSetCLEAFridgeRequestProcessor）。
- 订阅/取消订阅循环模式：subScribeCleaFridgeTopic 与 unSubScribeCleaFridgeTopic 在 14:45:48~14:45:49 交替执行，形成"订阅-检查-取消订阅"循环，导致状态被反复拉取和推送（14:45:48.712，PID 17551）。
- CPECallbackController 事件丢弃：PID 2501 在 14:45:48.713 因时间戳乱序丢弃 carPropertyEvent（propId: 291504647），可能是加重状态不稳定的因素，但与闪跳的直接因果关系未确认。
- 状态回环仅存在于远控链路：PID 17551（远控处理）有 loopCheckCleaFridgeState 日志，PID 3602（本地处理）无该函数日志，表明问题出在远控链路特有的状态管理逻辑。
- 传输层链路正常：CommunicationProxyManager（PID 4447）成功发送 RPC 请求并收到响应，确认问题不在传输层，而在应用层状态管理。
- --

### 评论 1

**排查动作**: 上传复现视频与日志

**排查结果**: 已提供复现素材待分析


### 评论 2

**排查动作**: 复制工作项1023144

**排查结果**: 无新排查，仅复制记录


### 评论 3

**排查动作**: 复现快速制冰下发热饮

**排查结果**: 手机端模式显示跳变回热饮


**日志证据**:

```
IDPCB0C0330B:2025-04-17 10:50:17.396 mqtt---08---startCommonCmdPush下发指令入参是vin:LSGUN8P27RA062256---type:FRIDGE,params:{fridge: {fridgeSwitch: ON, fridgeMode: ONE_CLICK_HEATING, temperature: 40}}
IDPCB0C0330B:2025-04-17 10:50:22.038 Flutter CallBack 日志: MQTT 接受到消息: {"scene":"FRIDGE","dataType":"FRIDGE_STATUS","requestId":"b3d0e139-1b36-11f0-907c-912b5c81cb57","data":{"mode":3,"switchState":2,"heatTemperature":40,"coolTemperature":-7,"error":[],"shutReason":1,"poweroffAvailable":false}}
```


### 评论 4

**排查动作**: 添加附件截图

**排查结果**: 已添加附件，待分析


### 评论 5

**排查动作**: 检查gmlog时间点

**排查结果**: 日志未覆盖当前时间点


**日志证据**:

```
main.log_2025_4_17_10_50_17
10:50:17.396 ---10:50:24.741
```


### 评论 6

**排查动作**: 补充log并请求重新分析

**排查结果**: 等待重新分析


### 评论 7

**排查动作**: 上传复现视频与日志

**排查结果**: 提供问题复现素材


### 评论 8

**排查动作**: (Comment from 顾

**排查结果**: (Comment from 顾佳宁)
从


### 评论 9

**排查动作**: 优化完成，通知复测

**排查结果**: 已优化，待复测验证


### 评论 10

**排查动作**: 确认远控服务更新状态

**排查结果**: 车端未集成，暂不可测


### 评论 11

**排查动作**: 确认远控联调状态

**排查结果**: 车端未集成VCU，暂不可测


### 评论 12

**排查动作**: 远控功能联调检查

**排查结果**: 车端未集成VCU，暂不可测


### 评论 13

**排查动作**: 远控功能联调检查

**排查结果**: 车端未集成VCU，暂不可测


### 评论 14

**排查动作**: 远控功能联调检查

**排查结果**: 车端未集成VCU，暂不可测


### 评论 15

**排查动作**: 评估车端版本可测性

**排查结果**: 车端未发布，远控链路不通，暂不可测


### 评论 16

**排查动作**: 上传复现日志与视频

**排查结果**: 提供崩溃复现素材


### 评论 17

**排查动作**: 实车复测切换模式

**排查结果**: 问题复现，模式来回闪跳


**日志证据**:

```
VCU:20250418-UQB26C-24-R1
APP:11.16.24
bug time：2025/05/07 14:44
```


### 评论 18

**排查动作**: 询问测试账号信息

**排查结果**: 等待提供账号


### 评论 19

**排查动作**: 复测17193402256

**排查结果**: 问题复现


### 评论 20

**排查动作**: 分析手机端日志

**排查结果**: UI状态被旧pub覆盖


### 评论 21

**排查动作**: 分析车端pub数据时序

**排查结果**: A指令上报晚于B指令，页面跳变


### 评论 22

**排查动作**: 分析请求与回调时序

**排查结果**: 未出现请求未发送即收到回调


**日志证据**:

```
Line 137104: 05-07 14:44:27.017  3602  5761 I CLEAFridgeRequestProcessor: processRequest: process CabinClimate request ---请求
Line 138896: 05-07 14:44:27.308  3602  8513 I CabinClimateSomeIpClient: SUCCESS: NOTIFY_FRIDGE_STATUS
Line 168081: 05-07 14:44:31.927  3602  5761 I CLEAFridgeRequestProcessor: processRequest: process CabinClimate request
```


### 评论 23

**排查动作**: 分析超时日志与代码逻辑

**排查结果**: 超时逻辑设计为2s*6，需修改


**日志证据**:

```
05-07 14:44:14.335 17551 20850 E RemoteSetCLEAFridgeRequestProcessor: poll time out!
05-07 14:44:16.228 17551 20865 E RemoteSetCLEAFridgeRequestProcessor: poll time out!
05-07 14:44:28.696 17551 20936 E RemoteSetCLEAFridgeRequestProcessor: poll time out!
05-07 14:44:32.472 17551 20965 E RemoteSetCLEAFridgeRequestProcessor: poll time out!
05-07 14:44:35.776 17551 20987 E RemoteSetCLEAFridgeRequestProcessor: poll time out!
```


### 评论 24

**排查动作**: 提交代码待合入

**排查结果**: 已提交，等待合入


### 评论 25

**排查动作**: 合入代码并通知测试

**排查结果**: 待5月26日后版本验证


### 评论 26

**排查动作**: 转交bug给对应负责人

**排查结果**: 非本组提交，拒绝处理


### 评论 27

**排查动作**: 请求打回reviewed状态

**排查结果**: 要求将3/4状态打回给测试


### 评论 28

**排查动作**: 上传实车日志与视频附件

**排查结果**: 提供复现数据，待分析


### 评论 29

**排查动作**: 复测冰箱模式快速切换

**排查结果**: 问题仍存在


**日志证据**:

```
bug time：14:44
```


### 评论 30

**排查动作**: 会议沟通前端优化需求

**排查结果**: 要求手机端前端进行优化


### 评论 31

**排查动作**: 优化冰箱界面指令时序

**排查结果**: 待复测验证问题是否解决


### 评论 32

**排查动作**: 排期优化并同步风险

**排查结果**: 车端快速点击无法通过手机优化解决


### 评论 33

**排查动作**: 确认车况订阅上传机制

**排查结果**: 时间戳比对，不存在问题


### 评论 34

**排查动作**: 确认指令队列机制

**排查结果**: SDV发送指令无队列，安吉星有队列


### 评论 35

**排查动作**: 添加崩溃截图附件

**排查结果**: 已添加截图，待进一步分析


### 评论 36

**排查动作**: 更新安卓测试环境安装包

**排查结果**: 版本号更新为11.18.6


**日志证据**:

```
更新安装包，安卓测试环境版本号：11.18.6
```


### 评论 37

**排查动作**: 添加500ms点击优化

**排查结果**: 已提供新安装包待测试


### 评论 38

**排查动作**: 上传复现附件与日志

**排查结果**: 提供冰箱闪跳复现素材


### 评论 39

**排查动作**: (Comment from 吴

**排查结果**: (Comment from 吴天吟)
从


**日志证据**:

```
2025-07-01 11:22:03.904
2025-07-01 14:21:43.705 mqtt---08---startCommonCmdPush下发指令入参是vin:LSGUN8P56SA003327---type:FRIDGE,sdvArchVersion:SDV1,params:{fridge: {fridgeSwitch: ON, fridgeMaintainTime: MAINTAIN_TIME_1, fridgeMode: ICE_MAKING, temperature: -10, conditionalJudgment: CHECK_GEAR}},requestId:fridge_mode_present_2
2025-07-01 14:21:44.986 Flutter CallBack 日志: MQTT 接受到消息: {"ceId":"1f05643a-7725-677e-9ab8-69668d6f0d84","data":{"coolTemperature":-7,"error":[],"heatTemperature":40,"mode":3,"poweroffAvailable":true,"shutReason":1,"switchState":2},"dataType":"FRIDGE_STATUS","requestId":"63cfb6f9-5643-11f0-8b28-b7b3622cd34e","scene":"FRIDGE","traceparent":"00-57bf02f9496dee9c7356ebd4fb4131c2-a085f72c407660b8-01"}
2025-07-01 14:21:45.898 mqtt---08---startCommonCmdPush下发指令入参是vin:LSGUN8P56SA003327---type:FRIDGE,sdvArchVersion:SDV1,params:{fridge: {fridgeSwitch: ON, fridgeMaintainTime: MAINTAIN_TIME_1, fridgeMode: ONE_CLICK_COOLING, temperature: 4, conditionalJudgment: CHECK_GEAR}},requestId:fridge_mode_present_0
2025-07-01 14:21:46.682 mqtt---08---startCommonCmdPush下发指令入参是vin:LSGUN8P56SA003327---type:FRIDGE,sdvArchVersion:SDV1,params:{fridge: {fridgeSwitch: ON, fridgeMaintainTime: MAINTAIN_TIME_1, fridgeMode: ONE_CLICK_ICE_MAKING, temperature: -6, conditionalJudgment: CHECK_GEAR}},requestId:fridge_mode_present_1
2025-07-01 14:21:47.136 Flutter CallBack 日志: MQTT 接受到消息: {"ceId":"1f05643a-8bb2-6b30-9ab8-69668d6f0d84","data":{"coolTemperature":4,"error":[],"heatTemperature":40,"mode":4,"poweroffAvailable":true,"shutReason":1,"switchState":2},"dataType":"FRIDGE_STATUS","requestId":"63cfb6f9-5643-11f0-8b28-b7b3622cd34e","scene":"FRIDGE","traceparent":"00-442f5cbc463e2160a73d572dfbb3b7fb-8fc31373aabdc618-01"}
2025-07-01 14:21:49.291 Flutter CallBack 日志: MQTT 接受到消息: {"ceId":"1f05643a-8f1c-6b92-9ab8-69668d6f0d84","data":{"coolTemperature":-6,"error":[],"heatTemperature":40,"mode":6,"poweroffAvailable":true,"shutReason":1,"switchState":2},"dataType":"FRIDGE_STATUS","requestId":"63cfb6f9-5643-11f0-8b28-b7b3622cd34e","scene":"FRIDGE","traceparent":"00-6ffc00f96228e9d8448993fe08192718-1033ef3aa0f289e8-01"}
```


### 评论 40

**排查动作**: 分析MQTT延迟问题

**排查结果**: 延迟消息无法过滤，需新方案


### 评论 41

**排查动作**: 添加冰箱指令code映射附件

**排查结果**: 已添加附件2091002


### 评论 42

**排查动作**: 确认改UX交互方案

**排查结果**: 需改交互，下周中完成复测


### 评论 43

**排查动作**: 修改交互逻辑

**排查结果**: 已实现指令互斥


### 评论 44

**排查动作**: 更正交互逻辑说明

**排查结果**: 已按需求修改交互，指令执行中禁止下发


### 评论 45

**排查动作**: 添加实车测试截图

**排查结果**: 已添加别克11.19.5-qa截图


**日志证据**:

```
附件 2114719 (别克11.19.5-qa.png)
```


### 评论 46

**排查动作**: 实车复测0718版本

**排查结果**: 问题未复现，测试通过


### 评论 47

**排查动作**: 开新票待功能正常后验证

**排查结果**: 0725版本远控有问题


### 评论 48

**排查动作**: 复测8255的0731版本

**排查结果**: 问题仍存在，修复版本延后


### 评论 49

**排查动作**: 实车复测0805版本

**排查结果**: 问题未复现，测试通过


### 评论 50

**排查动作**: 实车复测0808版本

**排查结果**: 问题未复现，测试通过


### 评论 51

**排查动作**: 实车复测0812版本

**排查结果**: 问题未复现，测试通过

