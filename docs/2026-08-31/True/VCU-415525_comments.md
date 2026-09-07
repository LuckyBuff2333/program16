# VCU-415525 评论分析总结

## 排查结论

远控指令下发成功，但车端vhal先收总线信号后收远控设置值，存在时序冲突致温度异常，问题已定位待进一步排查。


## 排查过程分析

### 问题现象
远控下发27度空调指令后，车端温度设置值出现异常跳动（先收到总线温度信号，后收到远控设置值），疑似存在数据竞争或时序冲突。

### 排查过程
| 步骤 | 排查动作 | 结果 | 关键证据 |
|------|----------|------|----------|
| 1 | 复制工作项1254331 | 无新增动作 | 评论1 |
| 2 | 上传复现视频与日志 | 待分析 | 评论2 |
| 3 | 分析远控下发日志 | 27度下发成功 | 14:02:22.611开始下发，14:02:22.916下发成功 requestId:3edc44a9 |
| 4 | 分析ServiceBus消息 | 收到2次handleGenericMessage | 14:02:22.614和14:02:23.323各一次 |
| 5 | 分析CoreService温度信号 | 对应时间点收到2次信号 | 14:02:22.609和14:02:23.319各一次buildCarPropertyCloud |
| 6 | 请求提供topic id | 等待补充 | 评论6 |
| 7 | 确认command5值 | 358614274，与之前一致 | command5: 358614274 |
| 8 | 请求查看command5 | 待夏工分析 | 评论8 |
| 9 | 分析gmlog数据变化 | vhal先收总线数据再收远控 | 14:02:22.553 GMVHAL收总线数据，14:02:23.178 setProperty，14:02:23.179 vhal_set |
| 10 | 0209版本复测排查 | 暂未复现 | 评论10 |

### 排查结论
- **已确认的事实**：远控指令在14:02:22.916下发成功（requestId:3edc44a9）；CoreService在14:02:22.609和14:02:23.319收到两次温度信号；GMVHAL在14:02:22.553先收到总线数据，14:02:23.179才执行vhal_set远控设置值，存在约626ms的时序差。
- **尚未确认需进一步排查的方向**：两次温度信号的具体内容差异；command5值358614274的具体含义及作用；topic id对应的消息路由；0209版本未复现的原因。
- **与AI日志分析结论的一致点**：均确认远控指令链路存在异常，CoreService收到信号但无法确认指令是否完整到达；均指出回调链路（CPECallbackController）和温度读写序列（PATACREMOTESettingsManager）存在未验证的风险点。
- **与AI日志分析结论的差异点**：AI分析认为CLEAExecuteClimateCommandRequestProcessor无日志输出，但实际排查发现指令已成功下发（requestId存在）；AI未识别出GMVHAL先收总线数据再收远控的时序问题，而人工排查已确认该时序差是温度跳动的直接诱因。


## 时序排查详情

### AI日志分析

- 远控空调指令链路日志缺失：CLEAExecuteClimateCommandRequestProcessor 在目标时间段内无日志输出，无法确认指令是否到达 CoreService（14:00:00~14:02:30，搜索无结果）
- 回调链路无法验证：CPECallbackController 是否丢弃 carPropertyEvent 事件未确认，无法判断温度跳动是否由回调丢失/延迟引起（未检索到相关日志）
- 温度设置值读写序列未追踪：PATACREMOTESettingsManager 是否存在旧值覆盖新值的情况未确认（未检索到相关日志）
- 下电状态与温度跳动的时序关联未建立：PLSS_PMSvc onSystemState 相关日志未检索，无法确认下电切换是否触发了温度事件异常（未检索到相关日志）
- Bug 描述信息不完整：问题发生时间未填写，温度跳动的具体表现（回跳值、跳动次数、时间间隔）未记录，增加了定位难度（Bug 描述）

### 评论 1

**排查动作**: 复制工作项1254331

**排查结果**: 无新增排查动作


### 评论 2

**排查动作**: 上传复现视频与日志

**排查结果**: 已添加附件，待分析


### 评论 3

**排查动作**: (Comment from 吴

**排查结果**: (Comment from 吴天吟)
 


**日志证据**:

```
2026-01-30 14:02:22.611  开始下发27度
2026-01-30 14:02:22.916   下发成功     requestId: 3edc44a9-fda1-11f0-8f8b-177b8be39265
IDPC1474E10CE:构建时间: 2026-01-30 14:02:24.463  (Size: 2.03 KB) Flutter CallBack 日志: MQTT 接受到消息: {"scene":"VEHICLE_CONDITION","dataType":"VEHICLE_CONDITION","requestId":"205af861-fda1-11f0-848f-3177662b46fe","ceId":"1f0fda13-e8fd-6515-8b6a-31604c2ece8e","data":{"lastUpdateTime":"2026-01-30 14:02:23.969","modelCode":"NCUB","rseVersion":"1.0","dataList":[{"sourceId":26,"dataField":"leftFrontBlowerAutoState","dataValue":[2],"dataType":"int","description":"空调自动风开关状态","lastUpdateTime":"2026-01-30 14:02:23.969"},{"sourceId":68,"dataField":"leftFrontBlowerLevel","dataValue":[25],"dataType":"int","description":"空调风量","lastUpdateTime":"2026-01-30 14:02:23.969"},{"sourceId":43,"dataField":"leftFrontTempSetpoint","dataValue":[26.0],"dataType":"float","description":"空调温度值","lastUpdateTime":"2026-01-30 14:02:23.969"},{"sourceId":13,"dataField":"leftFrontAirPowerState","dataValue":[true],"dataType":"bool","description":"空调开关状态","lastUpdateTime":"2026-01-30 14:02:23.969"}]},"traceparent":"00-78ab7aa87d943ea717d2ec1a6c556dfb-936a5216ca90e499-01"}===>topic==VCVV/SDVTWIN/1dd35149c41255ab5038a4ccdf7841ca
IDPC1474E10CE:构建时间: 2026-01-30 14:02:24.833  (Size: 1.13 KB) Flutter CallBack 日志: MQTT 接受到消息: {"scene":"VEHICLE_CONDITION","dataType":"VEHICLE_CONDITION","requestId":"205af861-fda1-11f0-848f-3177662b46fe","ceId":"1f0fda13-ecd2-6c36-8b6a-31604c2ece8e","data":{"lastUpdateTime":"2026-01-30 14:02:24.371","modelCode":"NCUB","rseVersion":"1.0","dataList":[{"sourceId":43,"dataField":"leftFrontTempSetpoint","dataValue":[27.0],"dataType":"float","description":"空调温度值","lastUpdateTime":"2026-01-30 14:02:24.371"}]},"traceparent":"00-88fad84be5e8aa7e2241bc1bf1c2b787-bcf514954e7de7dd-01"}===>topic==VCVV/SDVTWIN/1dd35149c41255ab5038a4ccdf7841ca
```


### 评论 4

**排查动作**: (Comment from 李

**排查结果**: (Comment from 李飞)
从车


**日志证据**:

```
01-30 14:02:22.614  5281  9287 D ServiceBus: [Dispatcher] Received handleGenericMessage CloudEvent=CloudEvent{id='1f0fda13-e59a-65ce-83f8-97e64a6f1e45', source=cls:/body.cabin_climate/1/zone.row1#Zone, type='pub.v1', datacontenttype='application/x-protobuf', dataschema=type.googleapis.com/cls.vehicle.body.cabin_climate.v1.Zone, time=2026-01-30T06:02:23.610Z, data=BytesCloudEventData{value=[10, 58, 116, 121, 112, 101, 46, 103, 111, 111, 103, 108, 101, 97, 112, 105, 115, 46, 99, 111, 109, 47, 99, 108, 115, 46, 118, 101, 104, 105, 99, 108, 101, 46, 98, 111, 100, 121, 46, 99, 97, 98, 105, 110, 95, 99, 108, 105, 109, 97, 116, 101, 46, 118, 49, 46, 90, 111, 110, 101, 18, 19, 10, 4, 114, 111, 119, 49, 21, 0, 0, -48, 65, 24, 2, 32, 25, 48, 1, 56, 1]}, extensions={}};
01-30 14:02:23.323  5281  5769 D ServiceBus: [Dispatcher] Received handleGenericMessage CloudEvent=CloudEvent{id='1f0fda13-ec5f-6c42-83f8-97e64a6f1e45', source=cls:/body.cabin_climate/1/zone.row1#Zone, type='pub.v1', datacontenttype='application/x-protobuf', dataschema=type.googleapis.com/cls.vehicle.body.cabin_climate.v1.Zone, time=2026-01-30T06:02:24.319Z, data=BytesCloudEventData{value=[10, 58, 116, 121, 112, 101, 46, 103, 111, 111, 103, 108, 101, 97, 112, 105, 115, 46, 99, 111, 109, 47, 99, 108, 115, 46, 118, 101, 104, 105, 99, 108, 101, 46, 98, 111, 100, 121, 46, 99, 97, 98, 105, 110, 95, 99, 108, 105, 109, 97, 116, 101, 46, 118, 49, 46, 90, 111, 110, 101, 18, 19, 10, 4, 114, 111, 119, 49, 21, 0, 0, -40, 65, 24, 2, 32, 25, 48, 1, 56, 1]}, extensions={}};
```


### 评论 5

**排查动作**: 分析coreService温度信号

**排查结果**: 对应时间点收到2次温度信号


**日志证据**:

```
30399: 01-30 14:02:22.609  4957  5647 I SDV_CoreService: [ServiceLaunchManager]buildCarPropertyCloudEvents: ID=====> 358614274 AreaId: 49 Value: 26.0
32154: 01-30 14:02:23.319  4957  5647 I SDV_CoreService: [ServiceLaunchManager]buildCarPropertyCloudEvents: ID=====> 358614274 AreaId: 49 Value: 27.0
```


### 评论 6

**排查动作**: 请求提供topic id

**排查结果**: 等待补充信息


### 评论 7

**排查动作**: 确认command5值

**排查结果**: 收到358614274，与之前一致


**日志证据**:

```
command5: 358614274
```


### 评论 8

**排查动作**: 请求查看command5

**排查结果**: 待夏工分析


### 评论 9

**排查动作**: 分析gmlog数据变化

**排查结果**: vhal先收总线数据再收远控


**日志证据**:

```
01-30 14:02:22.553  1606  1688 D GMVHAL  : Callback Called, SignalStore SignalName: IndTmpStngLvlFL type: INT32 Value: 26
01-30 14:02:23.178  4957 32714 D CarPropertyManager: setProperty, propertyId: HVAC_TEMPERATURE_SET, areaId: 0x44, class: 
01-30 14:02:23.179  1606  1630 D GMVHAL  : vhal_set Property: HVAC_TEMPERATURE_SET AreaID: 68 Status: 0 floatValues: 27
01-30 14:02:23.317  1606  1688 D GMVHAL  : Callback Called, SignalStore SignalName: IndTmpStngLvlFL type: INT32 Value: 27
```


### 评论 10

**排查动作**: 0209版本复测排查

**排查结果**: 暂未复现问题

