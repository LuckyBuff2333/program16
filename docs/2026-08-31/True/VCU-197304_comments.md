# VCU-197304 评论分析总结

## 排查结论

车端上报后云端重复下发3条FRIDGE_STATUS消息，导致状态跳变；已定位云端多发消息，待车端确认传值进一步排查。


## 排查过程分析

### 问题现象
冰箱模式状态在车端与云端之间出现异常跳变，车端上报后云端疑似重复下发消息，导致状态不一致。

### 排查过程

| 步骤 | 排查动作 | 结果 | 关键证据 |
|------|----------|------|----------|
| 1 | 上传实车复测视频与日志 | 已提供3个分卷压缩包 | gmlogger_2025_4_15_19_27_13.part1-3.rar |
| 2 | 复制工作项1021634 | 无新增排查动作 | 评论2无实质内容 |
| 3 | 查看Flutter MQTT回调日志 | 19:06:59连续收到3条FRIDGE_STATUS消息 | 19:06:59.741/.796/19:07:00.481 三条MQTT消息 |
| 4 | 添加附件截图 | 已添加图片附件 | 评论4附件 |
| 5 | 查看附件日志截图 | 已提供日志截图 | 评论5附件 |
| 6 | 请求车端核对传值 | 待车端老师确认 | 评论6无结论 |
| 7 | 日志时序排查上报链路 | 上报后未再上报，云端疑多发消息 | 19:06:59.173 ClsLinkRequestListener Process Finish；19:06:59.360 SomeIp Response Code:0 |
| 8 | 平台收到车端上报消息 | 消息ID已记录，待车端排查 | 19:06:59.487 消息ID：1f016c70-763d-6c1a-8605-59b1cdb32f60 |
| 9 | 添加附件截图 | 已添加附件，待进一步分析 | 评论9附件 |
| 10 | 顾→顾佳宁评论 | 无实质内容 | 评论10仅"该"字 |
| 11 | 常→常仲民查看argo-events日志 | 19:37:50收到MQTT消息 | 19:37:50.956 mqtt/start.go:145 receive |
| 12 | 常→常仲民查看argo-events日志 | 19:07:17收到MQTT消息 | 19:07:17.165 mqtt/start.go:145 receive |
| 13 | 查询平台冰箱数据时间点 | 平台收到数据，需车端确认 | time:"2025-04-15T19:07:08.487+08:00" |
| 14 | 确认CoreService最后pu | 未完成，待补充 | 评论14截断 |

### 排查结论

**已确认的事实：**
- 车端在19:06:59.173完成ClsLinkRequestProcessor处理，19:06:59.360收到SomeIp响应Code:0，表明车端上报链路正常
- 平台在19:06:59.487收到消息ID为1f016c70-763d-6c1a-8605-59b1cdb32f60的上报，19:07:08.487平台有冰箱数据时间点记录
- 云端在19:06:59.741/.


## 时序排查详情

### AI日志分析

- 推理层未获得任何有效日志搜索结果：无法确认 CLEAFridgeRequestProcessor、CabinClimateSomeIpClient、FridgeDataTrackUtils、CleaFridgeStatusTopic 等关键链路组件的运行状态（19:00~19:55，无日志证据）
- 日志概览显示核心组件活跃：VehicleSomeIpClient、DefaultCache、CommunicationProxyManager、jmqtt、ServiceBus 等核心组件在 19:02:08~19:04:20 期间活跃，但无法确认冰箱模式相关指令的处理情况（19:02:08~19:04:20，无日志证据）
- 推理层未完成任何有效搜索：无法定位冰箱模式乱跳的根因，也无法确认 RPC 链路完整性（19:00~19:55，无日志证据）

### 评论 1

**排查动作**: 上传复测视频与日志

**排查结果**: 已提供实车复测证据材料


**日志证据**:

```
gmlogger_2025_4_15_19_27_13.part1.rar
gmlogger_2025_4_15_19_27_13.part2.rar
gmlogger_2025_4_15_19_27_13.part3.rar
gmlogger_2025_4_15_19_55_11.part1.rar
gmlogger_2025_4_15_19_55_11.part2.rar
```


### 评论 2

**排查动作**: 复制工作项1021634

**排查结果**: 无新增排查动作


### 评论 3

**排查动作**: (Comment from 顾

**排查结果**: (Comment from 顾梦玥)
1


**日志证据**:

```
2025-04-15 19:06:59.741 Flutter CallBack 日志: MQTT 接受到消息: {"scene":"FRIDGE","dataType":"FRIDGE_STATUS","requestId":"c0adb803-19e9-11f0-adb4-1f449b35239e","data":{"mode":4,"switchState":2,"heatTemperature":40,"coolTemperature":4,"error":[],"shutReason":1,"poweroffAvailable":false}}
2025-04-15 19:06:59.796 Flutter CallBack 日志: MQTT 接受到消息: {"scene":"FRIDGE","dataType":"FRIDGE_STATUS","requestId":"c0285b60-19e9-11f0-adb4-fd6c28be55d7","data":{"mode":5,"switchState":2,"heatTemperature":40,"coolTemperature":-6,"error":[],"shutReason":1,"poweroffAvailable":false}}
2025-04-15 19:07:00.481 Flutter CallBack 日志: MQTT 接受到消息: {"scene":"FRIDGE","dataType":"FRIDGE_STATUS","requestId":"c0285b60-19e9-11f0-adb4-fd6c28be55d7","data":{"mode":5,"switchState":2,"heatTemperature":40,"coolTemperature":-6,"error":[],"shutReason":1,"poweroffAvailable":false}}
2025-04-15 19:07:08.388 Flutter CallBack 日志: MQTT 接受到消息: {"scene":"FRIDGE","dataType":"FRIDGE_STATUS","requestId":"c59006e5-19e9-11f0-8a5d-fb0665e318f4","data":{"mode":4,"switchState":2,"heatTemperature":40,"coolTemperature":4,"error":[],"shutReason":1,"poweroffAvailable":false}}
```


### 评论 4

**排查动作**: 添加附件截图

**排查结果**: 已添加图片附件


### 评论 5

**排查动作**: 查看附件日志截图

**排查结果**: 已提供日志截图


### 评论 6

**排查动作**: 请求车端核对传值

**排查结果**: 待车端老师确认


### 评论 7

**排查动作**: 日志时序排查上报链路

**排查结果**: 上报后未再上报，云端疑多发消息


**日志证据**:

```
04-15 19:06:59.173  4343  9627 I ClsLinkRequestListener: Process Finish，
04-15 19:06:59.173  4343  9627 I ClsLinkRequestListener:  Status: Status{code=OK, message='Fridge Request was successfully sent.')
04-15 19:06:59.360  4343  9882 I CabinClimateSomeIpClient: SomeIp Response Code:0
```


### 评论 8

**排查动作**: 平台收到车端上报消息

**排查结果**: 消息ID已记录，待车端排查


**日志证据**:

```
19:06:59.487 消息ID：1f016c70-763d-6c1a-8605-59b1cdb32f60
```


### 评论 9

**排查动作**: 添加附件截图

**排查结果**: 已添加附件，待进一步分析


### 评论 10

**排查动作**: (Comment from 顾

**排查结果**: (Comment from 顾佳宁)
该


### 评论 11

**排查动作**: (Comment from 常

**排查结果**: (Comment from 常仲民)
{


**日志证据**:

```
{"message":"2025-04-15T19:37:50.956+0800\tINFO\targo-events.eventsource\tmqtt/start.go:145\treceive msg payload: {\"data_base64\":\"ClF0eXBlLmdvb2dsZWFwaXMuY29tL2Nscy52ZWhpY2xlLmJvZHkuY2FiaW5fY2xpbWF0ZS52MS5DTEVBRnJhZ3JhbmNlRGlmZnVzZXJTdGF0dXMSIAgBEAIYASIGCAEQARhaIgYIAhACGGQiBggDEAMYWigB\",\"datacontenttype\":\"application/x-protobuf\",\"dataschema\":\"type.googleapis.com/cls.vehicle.body.cabin_climate.v1.CLEAFragranceDiffuserStatus\",\"id\":\"1f016c70-763d-6c1a-8605-59b1cdb32f60\",\"sink\":\"cls://bo.lscp.sgm.com/core.subscription/\",\"source\":\"cls://vcu.LSGUN8P2XRA033333.veh.lscp.sgm.com/body.cabin_climate/1/status#CLEAFragranceDiffuserStatus\",\"specversion\":\"1.0\",\"time\":\"2025-04-15T19:37:50.553+08:00\",\"ttl\":0,\"type\":\"pub.v1\"}\t{\"eventSourceName\": \"mqtt-d2c-high-mob04\", \"eventSourceType\": \"mqtt\", \"eventName\": \"example\"}"}
```


### 评论 12

**排查动作**: (Comment from 常

**排查结果**: (Comment from 常仲民)
{


**日志证据**:

```
{"message":"2025-04-15T19:07:17.165+0800\tINFO\targo-events.eventsource\tmqtt/start.go:145\treceive msg payload: {\"data_base64\":\"CkZ0eXBlLmdvb2dsZWFwaXMuY29tL2Nscy52ZWhpY2xlLmJvZHkuY2FiaW5fY2xpbWF0ZS52MS5DTEVBRnJpZGdlU3RhdHVzEgwIAhAEGCggBCgBOAE\\u003d\",\"datacontenttype\":\"application/x-protobuf\",\"dataschema\":\"type.googleapis.com/cls.vehicle.body.cabin_climate.v1.CLEAFridgeStatus\",\"id\":\"1f019e9c-06b6-6680-8606-59b1cdb32f60\",\"sink\":\"cls://bo.lscp.sgm.com/core.subscription/\",\"source\":\"cls://vcu.LSGUN8P2XRA033333.veh.lscp.sgm.com/body.cabin_climate/1/status#CLEAFridgeStatus\",\"specversion\":\"1.0\",\"time\":\"2025-04-15T19:07:16.782+08:00\",\"ttl\":0,\"type\":\"pub.v1\"}\t{\"eventSourceName\": \"mqtt-d2c-mob04\", \"eventSourceType\": \"mqtt\", \"eventName\": \"example\"}"}
```


### 评论 13

**排查动作**: 查询平台冰箱数据时间点

**排查结果**: 平台收到数据，需车端确认


**日志证据**:

```
time:"2025-04-15T19:07:08.487+08:00"
```


### 评论 14

**排查动作**: 确认CoreService最后pub时间

**排查结果**: CoreService最后pub为19:06:59.482


**日志证据**:

```
CoreService最后pub消息的时间是19:06:59.482
```


### 评论 15

**排查动作**: 分析云端下发订阅请求

**排查结果**: 确认两bug同因，云端持续下发冰箱订阅


**日志证据**:

```
云端一直在下发冰箱订阅请求
车端会pub缓存的last value给到云端
```


### 评论 16

**排查动作**: (Comment from 张

**排查结果**: (Comment from 张嘉)
04


### 评论 17

**排查动作**: 手机端查看优化方案

**排查结果**: 待手机端反馈


### 评论 18

**排查动作**: 更新SOSOAG远控服务

**排查结果**: 车端未集成，暂不可复现


### 评论 19

**排查动作**: 远控功能联调检查

**排查结果**: 车端未集成VCU，暂不可测


### 评论 20

**排查动作**: 远控功能联调检查

**排查结果**: 车端未集成VCU，暂不可测


### 评论 21

**排查动作**: 确认车端集成状态

**排查结果**: VCU未集成，暂不可测


### 评论 22

**排查动作**: 远控功能联调检查

**排查结果**: 车端未集成VCU，暂不可测


### 评论 23

**排查动作**: 评估车端版本与链路

**排查结果**: 车端未发布，远控链路不通，暂不可测

