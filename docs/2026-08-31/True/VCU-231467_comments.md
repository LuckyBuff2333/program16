# VCU-231467 评论分析总结

## 排查结论

已定位：手机端连续下发两条指令，车端仅处理首条LATER模式，未处理ELECTRIC_RATE_PERIOD，导致预约时间未更新，已提交修复补丁。


**排查摘要**：已定位：手机端连续下发两条指令，车端仅处理首条LATER模式，未处理ELECTRIC_RATE_PERIOD


## 排查过程分析

### 问题现象
用户通过手机端设置预约充电“按时出发”模式（出发时间06:03），车端收到指令后返回ack-high确认，但实际未写入新值，车端仍保留上一次设定值06:01，导致手机端显示同步成功而车端未生效。

### 排查过程
| 步骤 | 排查动作 | 结果 | 关键证据 |
|------|----------|------|----------|
| 1 | 上传实车复测日志及视频 | 提供复现材料 | 附件2187954/2187955/2187957 |
| 2 | 复制工作项1104832 | 无新增排查动作 | 评论2无证据 |
| 3 | 分析手机端下发指令时序 | 发现两条连续指令 | 19:31:35.550 LATER模式；19:31:35.551 ELECTRIC_RATE_PERIOD模式 |
| 4 | 核对下发指令参数 | 确认两条指令均含vin及request_ce_id | request_ce_id:eb030d7d...及eaffb1f1... |
| 5 | 提交代码补丁至VCUPROmain | 修复SDV_CoreService | Commit:127a00147ad69418399bf6fdeddc32b66978cf35 |
| 6 | 提交补丁至VCUPROmain_release2 | 同步修复至release2 | Commit:cff45c55d40ff955c40f477525e1243126fa5e45 |
| 7 | 提交补丁至VCUPROmain_dev_3.0 | 同步修复至dev分支 | Commit:82018f76625bca17fc9a8b3814c52dc60caa28f6 |
| 8 | 提交补丁至VCUPROmain分支 | 最终合入主分支 | 评论8证据被截断 |

### 排查结论
- **已确认的事实**：手机端在19:31:35.550和19:31:35.551连续下发两条充电模式指令（LATER和ELECTRIC_RATE_PERIOD），均携带vin:LSGMJ5P56SV003542；代码修复已提交至4个分支（VCUPROmain、VCUPROmain_release2、VCUPROmain_dev_3.0、VCUPROmain），涉及SDV_CoreService项目。
- **尚未确认需进一步排查的方向**：两条连续指令（LATER与ELECTRIC_RATE_PERIOD）之间的竞争关系是否导致后一条覆盖前一条；车端电源模式非OFF时拒绝写入的具体处理逻辑是否已覆盖所有异常场景；手机端同步成功判定机制是否需增加车端写入结果校验。
- **与AI日志分析结论的一致点和差异点**：一致点在于均确认车端未写入新值且仍显示06:01，且ack-high仅表示收到请求不代表写入成功；差异点在于AI分析聚焦电源模式RUN导致写入拒绝（错误码9），而评论证据显示存在两条指令连续下发，可能还存在指令覆盖或时序竞争问题，AI未提及此可能性。


## 时序排查详情

### AI日志分析

- 电源模式非 OFF 导致写入拒绝：车端在电源模式为 RUN（非 OFF）时，SetUsageProfileProcessor 检测到电源模式非 OFF，返回错误码 9，未写入新值（19:28:35.696，SetUsageProfileProcessor）
- 车端仍显示上一次设定值 6:01：车端存储的按时出发时间未更新，仍为 6:01（19:29:46.393，ChargeLaterTimeModel）
- ack-high 确认与写入结果脱节：车端在收到请求后立即发送 ack-high 确认，但该确认仅表示收到请求，不代表写入成功（19:28:35.674，CommProxy-cyberManager）
- 手机端同步成功判定机制可能存在缺陷：手机端显示同步成功，但车端实际未写入新值，手机端可能仅依赖云端转发完成即判定同步成功而未校验车端实际写入结果

### 评论 1

**排查动作**: 上传实车复测日志附件

**排查结果**: 提供复现视频及日志压缩包


**日志证据**:

```
附件 2187954 (9b1410ee31376b499f7554a895d92827.mp4)
附件 2187955 (1SD_IVDAR9EJ8FE4KSG_VCU_PLUS.zip)
附件 2187957 (gmlogger_2025_8_6_19_38_51.part1.rar)
附件 2187958 (gmlogger_2025_8_6_19_38_51.part2.rar)
附件 2187959 (充电 8-06-2025 7-33-43 pm.vsb)
```


### 评论 2

**排查动作**: 复制工作项1104832

**排查结果**: 无新增排查动作


### 评论 3

**排查动作**: (Comment from 顾

**排查结果**: (Comment from 顾梦玥)
 


**日志证据**:

```
2025-08-06 19:31:35.550手机端发送chargingService: {chargeMode: LATER,endTime: {hour: 06, minutes: 03}
2025-08-06 19:31:35.550  (Size: 0.45 KB) mqtt---08---startCommonCmdPush下发指令入参是vin:LSGMJ5P56SV003542---type:START_CHARGING,sdvArchVersion:SDV1,params:{chargingService: {chargeMode: LATER,endTime: {hour: 06, minutes: 03}, customerSetting: {targetSoc: 100}}},requestId:LATER
2025-08-06 19:31:35.551手机端发送chargingService: {chargeMode: ELECTRIC_RATE_PERIOD, startTime: {hour: 00, minutes: 00}, endTime: {hour: 11, minutes: 00}
2025-08-06 19:31:35.551  (Size: 0.58 KB) mqtt---08---startCommonCmdPush下发指令入参是vin:LSGMJ5P56SV003542---type:START_CHARGING,sdvArchVersion:SDV1,params:{chargingService: {chargeMode: ELECTRIC_RATE_PERIOD, startTime: {hour: 00, minutes: 00}, endTime: {hour: 11, minutes: 00}, customerSetting: {targetSoc: 100}}},requestId:ELECTRIC_RATE_PERIOD
2025-08-06 19:31:38.742  (Size: 0.23 KB) mqtt---08---startCommonCmdPush复合下发指令状态bizCodeE0000 --bizMsg--- 操作成功--requestId----eaffb1f1-72b8-11f0-a744-a9ff1c4e36c6
2025-08-06 19:31:38.763  (Size: 0.23 KB) mqtt---08---startCommonCmdPush复合下发指令状态bizCodeE0000 --bizMsg--- 操作成功--requestId----eb030d7d-72b8-11f0-8236-e5d69b9771f4
2025-08-06 19:31:39.164手机端收到LATER远控执行成功
2025-08-06 19:31:39.164  (Size: 0.59 KB) Flutter CallBack 日志: MQTT 接受到消息: {"bizCode":"E0000","bizMsg":"远控执行成功","data":{"requestId":"eb030d7d-72b8-11f0-8236-e5d69b9771f4","remoteType":"START_CHARGING","mqttTopic":"SOSOAG/SDV/5193c46eb343c32965a216c50359237d","status":0},"traceparent":"00-7513447ec034eb4b8f2d33e0bc3d5deb-65961fc46d5f7f7e-01"}
2025-08-06 19:31:39.442手机端收到ELECTRIC_RATE_PERIOD远控执行成功
2025-08-06 19:31:39.442  (Size: 0.69 KB) MQTTMessageCallBack: topicId=SOSOAG/SDV/5193c46eb343c32965a216c50359237d --- message={"bizCode":"E0000","bizMsg":"远控执行成功","data":{"requestId":"eaffb1f1-72b8-11f0-a744-a9ff1c4e36c6","remoteType":"START_CHARGING","mqttTopic":"SOSOAG/SDV/5193c46eb343c32965a216c50359237d","status":0},"traceparent":"00-78378ea24c28672d1346d73e3508ad75-f632e5055fcf8b03-01"}
2025-08-06 19:31:39.478在远控执行成功后收到{"chargeModeType":2,"timeslots":[{"startingTime":{"hours":0,"minutes":0,"seconds":0},"endingTime":{"hours":6,"minutes":1,"seconds":0}
2025-08-06 19:31:39.478  (Size: 1.24 KB) Flutter CallBack 日志: MQTT 接受到消息: {"scene":"CHARGING_DATA_SUB","dataType":"CHARGING_SERVICE_PROFILE","requestId":"7ec035a8-72b8-11f0-9c38-49d72c1d8af6","ceId":"1f072b8e-a4da-64b6-94b0-39660b60957b","data":{"chargeModeType":2,"timeslots":[{"startingTime":{"hours":0,"minutes":0,"seconds":0},"endingTime":{"hours":6,"minutes":1,"seconds":0},"chargingSettings":{"targetSoc":100}}],"readyBy":{"hours":0,"minutes":0,"seconds":0},"electricRateScheduleStartTime":{"hours":0,"minutes":0,"seconds":0},"electricRateScheduleEndingTime":{"hours":11,"minutes":0,"seconds":0}},"traceparent":"00-217cdd4ca75a24390a1e59e4d7929cac-0e8c7f2b12f37ceb-01"}
2025-08-06 19:31:47.631手机端下发chargingService: {chargeMode: LATER, endTime: {hour: 06, minutes: 06}
2025-08-06 19:31:47.631  (Size: 0.45 KB) mqtt---08---startCommonCmdPush下发指令入参是vin:LSGMJ5P56SV003542---type:START_CHARGING,sdvArchVersion:SDV1,params:{chargingService: {chargeMode: LATER, endTime: {hour: 06, minutes: 06}, customerSetting: {targetSoc: 100}}},requestId:LATER
2025-08-06 19:31:47.633手机端下发chargingService: {chargeMode: ELECTRIC_RATE_PERIOD, startTime: {hour: 00, minutes: 00}, endTime: {hour: 11, minutes: 00}
2025-08-06 19:31:47.633  (Size: 0.58 KB) mqtt---08---startCommonCmdPush下发指令入参是vin:LSGMJ5P56SV003542---type:START_CHARGING,sdvArchVersion:SDV1,params:{chargingService: {chargeMode: ELECTRIC_RATE_PERIOD, startTime: {hour: 00, minutes: 00}, endTime: {hour: 11, minutes: 00}, customerSetting: {targetSoc: 100}}},requestId:ELECTRIC_RATE_PERIOD
2025-08-06 19:31:50.888  (Size: 0.23 KB) mqtt---08---startCommonCmdPush复合下发指令状态bizCodeE0000 --bizMsg--- 操作成功--requestId----f23da352-72b8-11f0-a744-718aa7328eaf
2025-08-06 19:31:50.896  (Size: 0.23 KB) mqtt---08---startCommonCmdPush复合下发指令状态bizCodeE0000 --bizMsg--- 操作成功--requestId----f23df19e-72b8-11f0-8236-cbdb048e7267
2025-08-06 19:31:51.257收到LATER远控执行成功
2025-08-06 19:31:51.257  (Size: 0.59 KB) Flutter CallBack 日志: MQTT 接受到消息: {"bizCode":"E0000","bizMsg":"远控执行成功","data":{"requestId":"f23da352-72b8-11f0-a744-718aa7328eaf","remoteType":"START_CHARGING","mqttTopic":"SOSOAG/SDV/5193c46eb343c32965a216c50359237d","status":0},"traceparent":"00-bbe4d717b0168bbb88627077c06c699a-134b7332ea67bb1b-01"}
2025-08-06 19:31:51.314收到ELECTRIC_RATE_PERIOD执行成功
2025-08-06 19:31:51.314  (Size: 0.59 KB) Flutter CallBack 日志: MQTT 接受到消息: {"bizCode":"E0000","bizMsg":"远控执行成功","data":{"requestId":"f23df19e-72b8-11f0-8236-cbdb048e7267","remoteType":"START_CHARGING","mqttTopic":"SOSOAG/SDV/5193c46eb343c32965a216c50359237d","status":0},"traceparent":"00-8d70b792a62cce822944f492cff4e0af-8c523da5f92dc603-01"}
车端显示为每天06：01出发，手机端在指令发送成功后未收到CHARGING_SERVICE_PROFILE，直到2025-08-06 19:32:21.675才收到mqtt返回的CHARGING_SERVICE_PROFILE
2025-08-06 19:32:17.959手机端发送chargingService: {chargeMode: CHARGE_DELAY_BASED_ON_START_AND_END_TIME, startTime: {hour: 19, minutes: 00}, endTime: {hour: 17, minutes: 24}
2025-08-06 19:32:17.959  (Size: 0.66 KB) mqtt---08---startCommonCmdPush下发指令入参是vin:LSGMJ5P56SV003542---type:START_CHARGING,sdvArchVersion:SDV1,params:{chargingService: {chargeMode: CHARGE_DELAY_BASED_ON_START_AND_END_TIME, startTime: {hour: 19, minutes: 00}, endTime: {hour: 17, minutes: 24}, customerSetting: {targetSoc: 100}}},requestId:CHARGE_DELAY_BASED_ON_START_AND_END_TIME
2025-08-06 19:32:21.166  (Size: 0.23 KB) mqtt---08---startCommonCmdPush复合下发指令状态bizCodeE0000 --bizMsg--- 操作成功--requestId----0445932f-72b9-11f0-8236-ddee194649fc
2025-08-06 19:32:21.677收到{"startingTime":{"hours":19,"minutes":0,"seconds":0},"endingTime":{"hours":23,"minutes":0,"seconds":0}
2025-08-06 19:32:21.677  (Size: 1.38 KB) mqtt---08---startCommonCmdPush收到mqtt的结果topicId:VCVV/SDVTWIN/5193c46eb343c32965a216c50359237d---message:{"scene":"CHARGING_DATA_SUB","dataType":"CHARGING_SERVICE_PROFILE","requestId":"7ec035a8-72b8-11f0-9c38-49d72c1d8af6","ceId":"1f072b90-37f1-63e9-94b0-39660b60957b","data":{"chargeModeType":12,"timeslots":[{"startingTime":{"hours":19,"minutes":0,"seconds":0},"endingTime":{"hours":23,"minutes":0,"seconds":0},"chargingSettings":{"targetSoc":100}}],"readyBy":{"hours":0,"minutes":0,"seconds":0},"electricRateScheduleStartTime":{"hours":0,"minutes":0,"seconds":0},"electricRateScheduleEndingTime":{"hours":11,"minutes":0,"seconds":0}},"traceparent":"00-eb3197d0dbb9e13d1d990158b79135ba-2c18ac0225cedfd4-01"}
2025-08-06 19:32:21.733 手机端搜到远控执行成功
2025-08-06 19:32:21.733  (Size: 0.59 KB) Flutter CallBack 日志: MQTT 接受到消息: {"bizCode":"E0000","bizMsg":"远控执行成功","data":{"requestId":"0445932f-72b9-11f0-8236-ddee194649fc","remoteType":"START_CHARGING","mqttTopic":"SOSOAG/SDV/5193c46eb343c32965a216c50359237d","status":0},"traceparent":"00-22a7f763d6f5d44536d28e621a05eed1-9c2ffb3a1a82e6c9-01"}
2025-08-06 19:32:23.786收到"chargeModeType":12,"timeslots":[{"startingTime":{"hours":19,"minutes":0,"seconds":0},"endingTime":{"hours":17,"minutes":24,"seconds":0}
2025-08-06 19:32:23.786  (Size: 1.25 KB) Flutter CallBack 日志: MQTT 接受到消息: {"scene":"CHARGING_DATA_SUB","dataType":"CHARGING_SERVICE_PROFILE","requestId":"7ec035a8-72b8-11f0-9c38-49d72c1d8af6","ceId":"1f072b90-3a7d-61a8-94b0-39660b60957b","data":{"chargeModeType":12,"timeslots":[{"startingTime":{"hours":19,"minutes":0,"seconds":0},"endingTime":{"hours":17,"minutes":24,"seconds":0},"chargingSettings":{"targetSoc":100}}],"readyBy":{"hours":0,"minutes":0,"seconds":0},"electricRateScheduleStartTime":{"hours":0,"minutes":0,"seconds":0},"electricRateScheduleEndingTime":{"hours":11,"minutes":0,"seconds":0}},"traceparent":"00-18669b720354ea7ac34298741b58f475-8cd56a2243ff39ce-01"}
2025-08-06 19:33:05.305手机端下发chargingService: {chargeMode: CHARGE_DELAY_BASED_ON_START_AND_END_TIME, startTime: {hour: 07, minutes: 00}, endTime: {hour: 23, minutes: 15}
2025-08-06 19:33:05.305  (Size: 0.66 KB) mqtt---08---startCommonCmdPush下发指令入参是vin:LSGMJ5P56SV003542---type:START_CHARGING,sdvArchVersion:SDV1,params:{chargingService: {chargeMode: CHARGE_DELAY_BASED_ON_START_AND_END_TIME, startTime: {hour: 07, minutes: 00}, endTime: {hour: 23, minutes: 15}, customerSetting: {targetSoc: 100}}},requestId:CHARGE_DELAY_BASED_ON_START_AND_END_TIME
2025-08-06 19:33:08.527  (Size: 0.23 KB) mqtt---08---startCommonCmdPush复合下发指令状态bizCodeE0000 --bizMsg--- 操作成功--requestId----208182c0-72b9-11f0-8236-c3daf82dcd4c
2025-08-06 19:33:09.035收到远控执行异常
2025-08-06 19:33:09.035  (Size: 0.61 KB) Flutter CallBack 日志: MQTT 接受到消息: {"bizCode":"E4000","bizMsg":"远控执行异常","data":{"requestId":"208182c0-72b9-11f0-8236-c3daf82dcd4c","remoteType":"START_CHARGING","mqttTopic":"SOSOAG/SDV/5193c46eb343c32965a216c50359237d","status":9,"commMsg":""},"traceparent":"00-d325cbef1b9859f06d397ec771a489e1-c819eba3eca402fc-01"}
2025-08-06 19:31:35.550手机端发送chargingService: {chargeMode: LATER,endTime: {hour: 06, minutes: 03}，
2025-08-06 19:31:35.551手机端发送chargingService: {chargeMode: ELECTRIC_RATE_PERIOD, startTime: {hour: 00, minutes: 00}, endTime: {hour: 11, minutes: 00}，
2025-08-06 19:31:39.164手机端收到LATER远控执行成功，
2025-08-06 19:31:39.442手机端收到ELECTRIC_RATE_PERIOD远控执行成功，
2025-08-06 19:31:39.478在远控执行成功后收到{"chargeModeType":2,"timeslots":[{"startingTime":{"hours":0,"minutes":0,"seconds":0},"endingTime":{"hours":6,"minutes":1,"seconds":0}，
2025-08-06 19:31:47.631手机端下发chargingService: {chargeMode: LATER, endTime: {hour: 06, minutes: 06}，
2025-08-06 19:31:47.633手机端下发chargingService: {chargeMode: ELECTRIC_RATE_PERIOD, startTime: {hour: 00, minutes: 00}, endTime: {hour: 11, minutes: 00}，
2025-08-06 19:31:51.257收到LATER远控执行成功，
2025-08-06 19:31:51.314收到ELECTRIC_RATE_PERIOD执行成功，
车端显示为每天06：01出发，手机端在指令发送成功后未收到CHARGING_SERVICE_PROFILE，直到2025-08-06 19:32:21.675才收到mqtt返回的CHARGING_SERVICE_PROFILE，
需东升排查 19:31:51.257 收到LATER requestId----f23da352-72b8-11f0-a744-718aa7328eaf 远控执行成功后，在2025-08-06 19:32:21.675之前有无收到CHARGING_SERVICE_PROFILE
2025-08-06 19:33:05.305手机端下发chargingService: {chargeMode: CHARGE_DELAY_BASED_ON_START_AND_END_TIME, startTime: {hour: 07, minutes: 00}, endTime: {hour: 23, minutes: 15}
2025-08-06 19:33:09.035收到远控执行异常，
```


### 评论 4

**排查动作**: (Comment from 郭

**排查结果**: (Comment from 郭东升)
1


**日志证据**:

```
2025-08-06 19:31:35 手机端设置预约充电按时出发，
2025-08-06 19:31:35.550 下发指令，request_ce_id:eb030d7d-72b8-11f0-8236-e5d69b9771f4，{chargeMode: LATER,endTime: {hour: 06, minutes: 03}，指令执行成功
2025-08-06 19:31:35.551下发指令，request_ce_id:eaffb1f1-72b8-11f0-a744-a9ff1c4e36c6， {chargeMode: ELECTRIC_RATE_PERIOD, startTime: {hour: 00, minutes: 00}, endTime: {hour: 11, minutes: 00}，指令执行成功
2025-08-06 19:31:39.478收到pub数据上报 {"chargeModeType":2,"timeslots":[{"startingTime":{"hours":0,"minutes":0,"seconds":0},"endingTime":{"hours":6,"minutes":1,"seconds":0}，手机端展示按时出发模式，每天06:01出发，与设置值06:03不符合
2025-08-06 19:31:47.631下发指令 request_ce_id:f23da352-72b8-11f0-a744-718aa7328eaf，{chargeMode: LATER, endTime: {hour: 06, minutes: 06}，指令执行成功
2025-08-06 19:31:47.633下发指令 request_ce_id:f23df19e-72b8-11f0-8236-cbdb048e7267，{chargeMode: ELECTRIC_RATE_PERIOD, startTime: {hour: 00, minutes: 00}, endTime: {hour: 11, minutes: 00}，指令执行成功
2025-08-06 19:33:05.305下发指令 request_ce_id:208182c0-72b9-11f0-8236-c3daf82dcd4c，{chargeMode: CHARGE_DELAY_BASED_ON_START_AND_END_TIME, startTime: {hour: 07, minutes: 00}, endTime: {hour: 23, minutes: 15}，指令执行response报错，code: 9
```


### 评论 5

**排查动作**: 提交代码补丁审查

**排查结果**: 提交SDV_CoreService代码补丁


**日志证据**:

```
Project : gminfo/vendor/patac_ext/soa/SDV_CoreService
Branch : VCUPROmain
Git Commit : 127a00147ad69418399bf6fdeddc32b66978cf35
Gerrit Change-Id : I42a35f1c77256570690400a29ebe0a063c470831
Gerrit URL : https://info-gerrit.apps.saic-gm.com/210502
```


### 评论 6

**排查动作**: 提交代码补丁审查

**排查结果**: 提交补丁至VCUPROmain_release2分支


**日志证据**:

```
Project : gminfo/vendor/patac_ext/soa/SDV_CoreService
Branch : VCUPROmain_release2
Git Commit : cff45c55d40ff955c40f477525e1243126fa5e45
Gerrit Change-Id : I42a35f1c77256570690400a29ebe0a063c470831
Gerrit URL : https://info-gerrit.apps.saic-gm.com/210504
```


### 评论 7

**排查动作**: 提交代码补丁评审

**排查结果**: 提交补丁至VCUPRO分支


**日志证据**:

```
Project : gminfo/vendor/patac_ext/soa/SDV_CoreService
Branch : VCUPROmain_dev_3.0
Git Commit : 82018f76625bca17fc9a8b3814c52dc60caa28f6
Gerrit Change-Id : I42a35f1c77256570690400a29ebe0a063c470831
Gerrit URL : https://info-gerrit.apps.saic-gm.com/210505
```


### 评论 8

**排查动作**: 提交代码补丁审查

**排查结果**: 提交补丁至VCUPROmain分支


**日志证据**:

```
Project : gminfo/vendor/patac_ext/soa/SDV_CoreService
Branch : VCUPROmain
Git Commit : 7a8ae54d86a3abfb8bc8c3d0b46914e391a2013f
Gerrit Change-Id : Ic885032df8e9af8c165f75cb345ff22d15991191
Gerrit URL : https://info-gerrit.apps.saic-gm.com/210527
```


### 评论 9

**排查动作**: 提交代码补丁修复

**排查结果**: 提交补丁至VCUPROmain_release2分支


### 评论 10

**排查动作**: 提交代码补丁修复

**排查结果**: 提交补丁至VCUPROmain_dev_3.0分支


### 评论 11

**排查动作**: 推进状态并关注测试版本

**排查结果**: 请求佳宁推进状态


### 评论 12

**排查动作**: 发布版本并记录提交信息

**排查结果**: 版本已发布至指定tag


**日志证据**:

```
[ This change has been released in tag L234-8255-Mainline-20250807-UQB26B-19.zip ]
Git Commit : 127a00147ad69418399bf6fdeddc32b66978cf35
Gerrit URL : "https://info-gerrit.apps.saic-gm.com/210502"
```


### 评论 13

**排查动作**: 发布版本并记录提交信息

**排查结果**: 已发布至L234-8255-Mainline-20250807


**日志证据**:

```
[ This change has been released in tag L234-8255-Mainline-20250807-UQB26B-19.zip ]
Git Commit : 7a8ae54d86a3abfb8bc8c3d0b46914e391a2013f
Gerrit URL : "https://info-gerrit.apps.saic-gm.com/210527"
```


### 评论 14

**排查动作**: 发布软件版本NDNC-8775

**排查结果**: 已发布至Release2-20250808-UQB26C-104


**日志证据**:

```
[ This change has been released in software NDNC-8775-Release2-20250808-UQB26C-104.zip ]
Git Commit : cff45c55d40ff955c40f477525e1243126fa5e45
Artifactory Link : https://jfrog-sync.apps.saic-gm.com:443/artifactory/VcuPro/NDNC_Release2/NDNC-8775-Release2-20250808-UQB26C-104/NDNC-8775-Release2-20250808-UQB26C-104.zip
```


### 评论 15

**排查动作**: 发布软件版本NDNC-8775-Release2

**排查结果**: 已发布至指定版本包


**日志证据**:

```
[ This change has been released in software NDNC-8775-Release2-20250808-UQB26C-104.zip ]
```


### 评论 16

**排查动作**: 发布版本并记录提交信息

**排查结果**: 已发布至557-8775-Release2


**日志证据**:

```
[ This change has been released in tag 557-8775-Release2-20250808-UQB26C-57.zip ]
Git Commit : cff45c55d40ff955c40f477525e1243126fa5e45
Gerrit URL : "https://info-gerrit.apps.saic-gm.com/210504"
```


### 评论 17

**排查动作**: 发布版本并记录提交信息

**排查结果**: 已发布至557-8775-Release2


**日志证据**:

```
[ This change has been released in tag 557-8775-Release2-20250808-UQB26C-57.zip ]
Git Commit : e5cf9e1ccc1d26b4c70481f3d13d77f585d8e9e2
Gerrit URL : "https://info-gerrit.apps.saic-gm.com/210546"
```


### 评论 18

**排查动作**: 发布版本并记录提交信息

**排查结果**: 已发布至557-8255-Release2


**日志证据**:

```
[ This change has been released in tag 557-8255-Release2-20250808-UQB26C-65.zip ]
Git Commit : cff45c55d40ff955c40f477525e1243126fa5e45
Artifactory Link : http://10.203.71.4:8081/artifactory/VcuPro/557_release2/8255/
```


### 评论 19

**排查动作**: 发布修复版本

**排查结果**: 修复已发布至557-8255-Release2


**日志证据**:

```
[ This change has been released in tag 557-8255-Release2-20250808-UQB26C-65.zip ]
```


### 评论 20

**排查动作**: 发布软件版本NDNC-8775

**排查结果**: 已发布至Mainline-20250808-UQB26C-145


**日志证据**:

```
[ This change has been released in software NDNC-8775-Mainline-20250808-UQB26C-145.zip ]
Git Commit : 127a00147ad69418399bf6fdeddc32b66978cf35
Gerrit URL : "https://info-gerrit.apps.saic-gm.com/210502"
```


### 评论 21

**排查动作**: 发布软件版本NDNC-8775

**排查结果**: 修复已合入主线下发


**日志证据**:

```
[ This change has been released in software NDNC-8775-Mainline-20250808-UQB26C-145.zip ]
Git Commit : 7a8ae54d86a3abfb8bc8c3d0b46914e391a2013f
```


### 评论 22

**排查动作**: 发布版本并记录提交信息

**排查结果**: 已发布至tag 557-8255-Mainline-20250808


**日志证据**:

```
[ This change has been released in tag 557-8255-Mainline-20250808-UQB26C-997.zip ]
Git Commit : 127a00147ad69418399bf6fdeddc32b66978cf35
Gerrit URL : "https://info-gerrit.apps.saic-gm.com/210502"
```


### 评论 23

**排查动作**: 发布版本并记录提交信息

**排查结果**: 已发布至557-8255-Mainline-20250808


**日志证据**:

```
[ This change has been released in tag 557-8255-Mainline-20250808-UQB26C-997.zip ]
Git Commit : 7a8ae54d86a3abfb8bc8c3d0b46914e391a2013f
Gerrit URL : "https://info-gerrit.apps.saic-gm.com/210527"
```


### 评论 24

**排查动作**: 发布修复版本并记录提交

**排查结果**: 修复已发布至指定tag


**日志证据**:

```
[ This change has been released in tag 557-8775-Mainline-20250808-UQB26C-101.zip ]
Git Commit : 127a00147ad69418399bf6fdeddc32b66978cf35
```


### 评论 25

**排查动作**: 发布版本并记录提交信息

**排查结果**: 已发布至557-8775-Mainline-20250808


**日志证据**:

```
[ This change has been released in tag 557-8775-Mainline-20250808-UQB26C-101.zip ]
Git Commit : 7a8ae54d86a3abfb8bc8c3d0b46914e391a2013f
Gerrit URL : "https://info-gerrit.apps.saic-gm.com/210527"
```


### 评论 26

**排查动作**: 确认0808版本待验证

**排查结果**: 0808版本待验证


### 评论 27

**排查动作**: 上传复现视频与日志

**排查结果**: 已提供问题复现素材


### 评论 28

**排查动作**: 实车复测问题验证

**排查结果**: 问题仍存在，需进一步排查


### 评论 29

**排查动作**: 上传gmlogger日志附件

**排查结果**: 已添加两个分卷压缩日志附件


**日志证据**:

```
附件 2193451 (gmlogger_2025_8_8_20_9_40.part2.rar)
附件 2193452 (gmlogger_2025_8_8_20_9_40.part1.rar)
```


### 评论 30

**排查动作**: 提交代码补丁审查

**排查结果**: 提交SDV_CoreService代码补丁


### 评论 31

**排查动作**: 提交代码补丁修复

**排查结果**: 提交补丁至VCUPROmain_release2分支


### 评论 32

**排查动作**: 提交代码补丁审查

**排查结果**: 提交补丁至VCUPROmain_dev_3.0分支


### 评论 33

**排查动作**: 发布软件版本NDNC-8775

**排查结果**: 已发布至Release2-20250810


**日志证据**:

```
[ This change has been released in software NDNC-8775-Release2-20250810-UQB26C-108.zip ]
Git Commit : 2e2296c702a6e9dbfae48fb8da5b36b71b2d7c0b
Artifactory Link : https://jfrog-sync.apps.saic-gm.com:443/artifactory/VcuPro/NDNC_Release2/NDNC-8775-Release2-20250810-UQB26C-108/NDNC-8775-Release2-20250810-UQB26C-108.zip
```


### 评论 34

**排查动作**: 发布版本并记录提交信息

**排查结果**: 已发布至557-8775-Release2


**日志证据**:

```
[ This change has been released in tag 557-8775-Release2-20250810-UQB26C-61.zip ]
Git Commit : 2e2296c702a6e9dbfae48fb8da5b36b71b2d7c0b
Gerrit URL : "https://info-gerrit.apps.saic-gm.com/211040"
```


### 评论 35

**排查动作**: 发布版本并记录变更

**排查结果**: 变更已发布至557-8255-Release2


**日志证据**:

```
[ This change has been released in tag 557-8255-Release2-20250810-UQB26C-69.zip ]
Git Commit : 2e2296c702a6e9dbfae48fb8da5b36b71b2d7c0b
Gerrit URL : "https://info-gerrit.apps.saic-gm.com/211040"
Artifactory Link : http://10.203.71.4:8081/artifactory/VcuPro/557_release2/8255/
```


### 评论 36

**排查动作**: 发布软件版本NDNC-8775

**排查结果**: 修复已合入Mainline分支


**日志证据**:

```
[ This change has been released in software NDNC-8775-Mainline-20250810-UQB26C-147.zip ]
Git Commit : 1924adaec9496db096f6e83aaf13a061c710e17d
Gerrit URL : "https://info-gerrit.apps.saic-gm.com/211038"
```


### 评论 37

**排查动作**: 发布代码到指定tag

**排查结果**: 代码已发布至557-8255-Mainline


**日志证据**:

```
[ This change has been released in tag 557-8255-Mainline-20250810-UQB26C-1000.zip ]
Git Commit : 1924adaec9496db096f6e83aaf13a061c710e17d
Gerrit URL : "https://info-gerrit.apps.saic-gm.com/211038"
```


### 评论 38

**排查动作**: 发布版本并关联代码提交

**排查结果**: 已发布至557-8775-Mainline-20250810


**日志证据**:

```
[ This change has been released in tag 557-8775-Mainline-20250810-UQB26C-103.zip ]
Git Commit : 1924adaec9496db096f6e83aaf13a061c710e17d
Gerrit URL : "https://info-gerrit.apps.saic-gm.com/211038"
```


### 评论 39

**排查动作**: 验证问题是否通过

**排查结果**: 问题已验证通过


### 评论 40

**排查动作**: 上传实车故障视频

**排查结果**: 已添加附件mp4视频

