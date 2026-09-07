# VCU-226779 评论分析总结

## 排查结论

远控启动失败因CoreService上报RVSS_ON与CAN总线RVSS_OFF不一致，空调指令未达车端，问题已定位。


## 排查过程分析

### 问题现象
用户远控启动失败，车端CoreService上报的远程启动状态与CAN总线实际状态不一致，且云端下发的空调温度指令未到达车端。

### 排查过程
| 步骤 | 排查动作 | 结果 | 关键证据 |
|------|----------|------|----------|
| 1 | 上传复现日志与视频 | 提供远控失败复现材料 | 评论1：上传复现日志与视频附件 |
| 2 | 复制工作项1115843 | 无新增排查动作 | 评论2：复制工作项1115843 |
| 3 | 分析远程启动状态上报 | CoreService状态与CAN总线不一致 | 74921: 10:26:27.040 D RemoteExecuteClimateCommandRequestProcessor: onRemoteStartCh |
| 4 | 确认HVAC_POWER_ON上报字段 | 关闭空调后Topic正常上报false | 75915: ID=====> 35；75917: value = fal；81867: ID=====> 35 |
| 5 | 确认信号上报状态 | 上报RVSS_ON但总线为OFF | cls:/energy.power_management/1/propulsion#RemoteVehicleStart 上报RVSS_ON（2），CAN总线为RVSS_OFF |
| 6 | 分析时间点与日志对应关系 | 10:25:20下电，10:26:06首次RPC请求 | 71376: 10:25:20.667 RemoteStartStatusTopic: 0；129388: 10:26:06.921 processRequest |
| 7 | 分析CAN与CoreService数据 | CAN为rvs off但返回1，需排查 | 10:26:06.909 ID=====> 557867317；RemoteStartStatusTopic: 1 |
| 8 | 核对信号与总线对应关系 | 信号变化值与总线对应 | PPEI_Platform_General_Status_111_M,0x111,8,IN,RemStrtSt,PPEI |

### 排查结论
- **已确认的事实**：CoreService上报的远程启动状态（RVSS_ON=2）与CAN总线实际状态（RVSS_OFF）不一致（评论5）；HVAC_POWER_ON字段在关闭空调后能正常上报false（评论4）；10:25:20下电后，10:26:06首次RPC请求（评论6）；CAN总线为rvs off但CoreService返回1（评论7）。
- **尚未确认需进一步排查的方向**：CoreService为何在CAN总线为OFF时仍上报ON状态；云端25→26温度指令未到达车端的具体原因；RemoteControlService进程多次重启的根因。
- **与AI日志分析结论的一致点**：均确认车端HVAC远控链路本身工作正常（AI结论4与评论4一致）；均确认上行队列空轮询非本次故障根因（AI结论3）。
- **与AI日志分析结论的差异点**：AI结论认为25→26指令从未到达车端，但评论未直接验证该指令是否到达；AI结论关注RemoteControlService进程重启，而评论聚焦于CoreService状态与CAN总线不一致。


## 时序排查详情

### AI日志分析

- 爱车卡片 25→26 指令从未到达车端：全日志 149 万行中无 `temperature_setpoint="25"/"26"` 的 C2D 指令记录，`RemoteExecuteHVACCommand` 的 C2D 指令仅 3 条，最后一条对应座舱环境 19→20 操作（L1289758）
- RemoteControlService 进程多次重启：PID 从 12757→14835→15107，10:25:09.322 重新注册 RPC 方法，但无崩溃堆栈，原因未明（L508714）
- 上行队列空轮询现象：大量 `sendToStreamer QueueData data is null object` 与 `revCloudEvent cloudMsg is empty` 为车端→云端方向队列空轮询，与下行指令接收无关，非本次故障根因
- 座舱环境 19→20 指令执行成功：车端 HVAC 远控链路本身工作正常，证明问题出在车端边界之外

### 评论 1

**排查动作**: 上传复现日志与视频附件

**排查结果**: 提供远控失败复现材料


### 评论 2

**排查动作**: 复制工作项1115843

**排查结果**: 无新增排查动作


### 评论 3

**排查动作**: 分析远程启动状态上报

**排查结果**: CoreService状态与CAN总线不一致


**日志证据**:

```
74921: 08-21 10:26:27.040 15107 15128 D RemoteExecuteClimateCommandRequestProcessor: onRemoteStartChange status :2
```


### 评论 4

**排查动作**: 确认HVAC_POWER_ON上报字段

**排查结果**: 关闭空调后Topic正常上报false


**日志证据**:

```
75915: 08-21 10:25:20.754 4588 4908 I ServiceLaunchManager: buildCarPropertyCloudEvents: ID=====> 354419984 AreaId: 112 Value: false
75917: 08-21 10:25:20.754 4588 4908 I ZoneTopic: mPropertyID: 354419984 , mAreaId = 112, value = false
81867: 08-21 10:25:20.850 4588 4908 I ServiceLaunchManager: buildCarPropertyCloudEvents: ID=====> 354419984 AreaId: 5 Value: false
```


### 评论 5

**排查动作**: 确认信号上报状态

**排查结果**: 上报RVSS_ON但总线为OFF


**日志证据**:

```
cls:/energy.power_management/1/propulsion#RemoteVehicleStart" 上报的是RVSS_ON（2），但CAN总线上是RVSS_OFF
```


### 评论 6

**排查动作**: 分析时间点与日志对应关系

**排查结果**: 10:25:20下电，10:26:06首次RPC请求


**日志证据**:

```
71376: 08-21 10:25:20.667 4588 4908 I RemoteStartStatusTopic: RemoteStartStatusTopic: 0
129388: 08-21 10:26:06.921 4588 6269 I CLEAExecuteClimateCommandRequestProcessor: processRequest: process CabinClimate request
129413: 08-21 10:26:06.923 4588 6269 I CLEAExecuteClimateCommandRequestProcessor: processRequest kehvc_front_zone: 2 rear_temp_zone: 1 rear_blower_cont_avl: true dual_front_air_dis: true rear_cliamte_app_avl: true
```


### 评论 7

**排查动作**: 分析CAN与CoreService数据

**排查结果**: CAN为rvs off但返回1，需排查


**日志证据**:

```
10:26:06.909 4588 4908 I ServiceLaunchManager: buildCarPropertyCloudEvents: ID=====> 557867317 AreaId: 16777216 Value: 1
10:26:06.909 4588 4908 I RemoteStartStatusTopic: RemoteStartStatusTopic: 1
10:26:32.877 4588 4908 I ServiceLaunchManager: buildCarPropertyCloudEvents: ID=====> 557867317 AreaId: 16777216 Value: 0
10:26:32.877 4588 4908 I RemoteStartStatusTopic: RemoteStartStatusTopic: 0
```


### 评论 8

**排查动作**: 核对信号与总线对应关系

**排查结果**: 信号变化值与总线对应


**日志证据**:

```
PPEI_Platform_General_Status_111_M,0x111,8,IN,RemStrtSt,PPEI Platform General Status Signal Group : Remote Start Status
```


### 评论 9

**排查动作**: 添加附件截图

**排查结果**: 已添加截图附件


### 评论 10

**排查动作**: 对齐视频与CAN日志时间点

**排查结果**: 确认远程启动状态为active，未下发启动请求


**日志证据**:

```
CAN log上的时间点是1410（横坐标）
CAN总线的远程启动是INACTIVE
远控下发26°请求时没有下发远控启动请求
从VCU底层获取到的远程启动状态就是active
```


### 评论 11

**排查动作**: 对比两处CAN log时间点

**排查结果**: 截图时间点不一致，需对齐


### 评论 12

**排查动作**: 确认总线分析remote状态

**排查结果**: 待确认remote请求是否发出


### 评论 13

**排查动作**: (Comment from 夏

**排查结果**: (Comment from 夏陶悦)
H


### 评论 14

**排查动作**: 定位问题时间节点

**排查结果**: 问题点在10:25:20至10:26:06之间


**日志证据**:

```
10：25：20 到10：26：06
```


### 评论 15

**排查动作**: 对齐视频定位问题时间段

**排查结果**: 问题点锁定在10:25:20至10:26:06


**日志证据**:

```
10:25:20 到10:26:06之间
```


### 评论 16

**排查动作**: app查找日志分析

**排查结果**: 定位为token失效导致


### 评论 17

**排查动作**: 添加截图附件

**排查结果**: 已添加附件，待分析


### 评论 18

**排查动作**: 通知修复完成

**排查结果**: 已修复，请复测


### 评论 19

**排查动作**: 添加截图附件

**排查结果**: 已添加附件，待分析


### 评论 20

**排查动作**: 实车复测APP11.20.37

**排查结果**: 问题未复现，频率0/70


### 评论 21

**排查动作**: 实车复测APP11.20.48

**排查结果**: 问题未复现，频率0/70


### 评论 22

**排查动作**: 实车复测APP11.20.57

**排查结果**: 问题未复现，连续3版本通过


**日志证据**:

```
557-8775-Release3-20250905-UQB26C-39  APP：11.20.57
OK
0/70
```

