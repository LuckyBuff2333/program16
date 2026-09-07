# VCU-420588 评论分析总结

## 排查结论

实车复测360出图失败，因RemoteSVC进程未启动致5446接口超时，问题已定位至车端进程异常，具体原因待进一步排查。


**排查摘要**：实车复测360出图失败，因RemoteSVC进程未启动致5446接口超时，问题已定位至车端进程异常


## 排查过程分析

### 问题现象
车辆远程监控功能在实车复测中360出图失败，车端RemoteSVC进程未启动，导致5446接口请求超时无回调，问题在Release4版本验证中持续复现。

### 排查过程
| 步骤 | 排查动作 | 结果 | 关键证据 |
|------|----------|------|----------|
| 1 | 上传复现视频与日志 | 已提供素材待分析 | 附件2547315 (mp4)、2547322/2547325 (z01/z02) |
| 2 | 复制工作项1246780 | 无新排查动作 | 仅复制操作 |
| 3 | 上传gmlogger日志附件 | 已添加日志供分析 | 附件2547378 (zip) |
| 4 | 添加附件截图 | 已添加待分析 | 附件未编号 |
| 5 | 请求下载新包复测 | 等待朱工验证 | 无日志证据 |
| 6 | 上传复现视频与日志 | 已提供素材待分析 | 附件未编号 |
| 7 | 确认车辆能力配置问题 | 问题已解决 | 无日志证据 |
| 8 | 实车复测360出图 | 能力已配置但不出图 | 无日志证据 |
| 9 | 上传复现视频与日志 | 提供素材待分析 | 附件未编号 |
| 10 | 手机端分析定位问题 | 问题来自车端 | 需陈工处理 |
| 11 | 添加附件截图 | 已添加附件 | 附件2556833 |
| 12 | 分析5446接口超时日志 | 请求参数正常，超时待查 | 12:40:56 request参数正常、requestTimeout countdown start |
| 13 | 检查RemoteSVC进程状态 | 进程未启动，原因不明 | 无日志证据 |
| 14 | 版本验证Fail并添加视频日志 | NDNC-8775 Release4验证失败 | 无日志证据 |
| 15 | 上传复现视频与日志 | 提供问题复现素材 | 附件未编号 |
| 16 | 分析日志定位超时 | 无5446回调，请求超时 | 13:15:14 send START_REMOTE_MONITOR、13:15:24 请求进入远程查看工 |
| 17 | 补充comment15分析结论 | 基于日志视频时间节点分析 | 无日志证据 |
| 18 | 检查QNX侧订阅日志 | 未收到5446订阅，转交QNX | 13:15:15 got a subscribe request for |

### 排查结论
- **已确认的事实**：5446接口请求参数正常但无回调（12:40:56 request参数正常）；车端RemoteSVC进程未启动（评论13）；QNX侧未收到5446订阅（13:15:15 got a subscribe request for）；请求超时发生在发送START_REMOTE_MONITOR后10秒（13:15:14发送、13:15:24超时）。
- **尚未确认需进一步排查的方向**：RemoteSVC进程未启动的根本原因；QNX侧未收到订阅请求的具体原因；


## 时序排查详情

### AI日志分析

- 裁决层 LLM 调用失败：分析流程在裁决阶段发生异常，导致所有结论均为兜底输出，无法进行有效的根因分析（2026-01-24 13:15:24，裁决层）
- 结构化证据全部缺失：信号链路、状态对比、时间线、端到端耗时均未追踪到，说明推理层未能从日志中提取到有效的事件序列（推理层 3 轮搜索）
- 日志规模较大但无有效产出：327,007 行日志经过 3 轮搜索后未产出可引用的证据组，可能存在搜索策略不匹配或日志内容与问题不相关的情况

### 评论 1

**排查动作**: 上传复现视频与日志

**排查结果**: 已提供复现素材待分析


**日志证据**:

```
附件 2547315 (4172d8df3cf98dba385f3a1fed0a061f.mp4)
附件 2547322 (gmlogger_2026_1_20_12_57_57.z01)
附件 2547325 (gmlogger_2026_1_20_12_57_57.z02)
```


### 评论 2

**排查动作**: 复制工作项1246780

**排查结果**: 无新排查动作，仅复制


### 评论 3

**排查动作**: 上传gmlogger日志附件

**排查结果**: 已添加日志附件供分析


**日志证据**:

```
附件 2547378 (gmlogger_2026_1_20_12_57_57.zip)
```


### 评论 4

**排查动作**: 添加附件截图

**排查结果**: 已添加附件，待分析


### 评论 5

**排查动作**: 请求下载新包复测

**排查结果**: 等待朱工验证新包


### 评论 6

**排查动作**: 上传复现视频与日志附件

**排查结果**: 已提供复现素材，待分析


### 评论 7

**排查动作**: 确认车辆能力配置问题

**排查结果**: 问题已解决


### 评论 8

**排查动作**: 实车复测360出图

**排查结果**: 能力已配置但360仍不出图


### 评论 9

**排查动作**: 上传复现视频与日志附件

**排查结果**: 提供问题复现素材待分析


### 评论 10

**排查动作**: 手机端分析定位问题

**排查结果**: 问题来自车端，需陈工处理


### 评论 11

**排查动作**: 添加附件截图

**排查结果**: 已添加附件2556833


### 评论 12

**排查动作**: 分析5446接口超时日志

**排查结果**: 请求参数正常，超时待查


**日志证据**:

```
01-23 12:40:56.286 12662 12962 I CC Service-RemoteCameraConnectionControlProcessor: request参数: remote_camera_connection_request: RCC_START
01-23 12:40:56.289 12662 12962 D CC Service-RemoteMonitorStateMachine: requestTimeout countdown start
01-23 12:40:56.289 12662 12962 I CC Service-PatacFsaManager cc by remote monitor: doRemoteCameraConnectionRequest isStart:true
```


### 评论 13

**排查动作**: 检查RemoteSVC进程状态

**排查结果**: 进程未启动，原因不明


### 评论 14

**排查动作**: 版本验证Fail并添加视频日志

**排查结果**: NDNC-8775 Release4验证失败


### 评论 15

**排查动作**: 上传复现视频与日志

**排查结果**: 提供问题复现素材


### 评论 16

**排查动作**: 分析日志定位超时

**排查结果**: 无5446回调，请求超时


**日志证据**:

```
01-24 13:15:14.902  8777  9376 I CC Service-PatacFsaManager cc: send 6 START_REMOTE_MONITOR to the qnx server
01-24 13:15:14.902  8777  9376 D PATACREMOTECameraManager:  setSentinelModeStatus status = true
01-24 13:15:24.914  8777  9375 D CC Service-RemoteMonitorStateMachine: 请求PATAC Remote Service进入远程查看工作模式timeout. ###Fatal###
```


### 评论 17

**排查动作**: 补充comment15分析结论

**排查结果**: 基于日志视频时间节点分析


### 评论 18

**排查动作**: 检查QNX侧订阅日志

**排查结果**: 未收到5446订阅，转交QNX分析


**日志证据**:

```
01-24 13:15:15.761  3005 11882 D FSAINotificationService: got a subscribe request for ID 5523
01-24 13:15:15.762  3005 11882 D FSAINotificationService: got a subscribe request for ID 5525
```


### 评论 19

**排查动作**: 请求超哥查看

**排查结果**: 等待进一步处理


### 评论 20

**排查动作**: 提交代码补丁审查

**排查结果**: 提交补丁至VCUPROmain_release4


**日志证据**:

```
Project : vcu/qnx/patac/SGMViewingRemoteApps
Branch : VCUPROmain_release4
Git Commit : 02e927569a6cbe52d49c4e77ac9ba87f83ca5222
Gerrit Change-Id : I6cf3c352c276e406bf8ee131d5e4cf74a2993d70
Gerrit URL : https://info-gerrit.apps.saic-gm.com/248674
```


### 评论 21

**排查动作**: 提交代码补丁审查

**排查结果**: 提交补丁，等待审查


### 评论 22

**排查动作**: 发布软件版本NDNC-8775

**排查结果**: 修复已合入主分支并发布


**日志证据**:

```
[ This change has been released in software NDNC-8775-Mainline-20260128-UQB26C-490.zip ]
Git Commit : b7919d59af609102b09dbeb99307ea301bb02432
Gerrit URL : "https://info-gerrit.apps.saic-gm.com/248675"
```


### 评论 23

**排查动作**: 发布版本并记录提交信息

**排查结果**: 版本已发布至指定tag


**日志证据**:

```
[ This change has been released in tag L234-8255-Mainline-20260128-UQB27B-308.zip ]
Git Commit : b7919d59af609102b09dbeb99307ea301bb02432
Gerrit URL : "https://info-gerrit.apps.saic-gm.com/248675"
```


### 评论 24

**排查动作**: 提交代码补丁审查

**排查结果**: 提交补丁至VCUPROmain_release4分支


**日志证据**:

```
Project : vcu/qnx/patac/SGMViewingRemoteApps
Branch : VCUPROmain_release4
Git Commit : 02e927569a6cbe52d49c4e77ac9ba87f83ca5222
Gerrit Change-Id : I6cf3c352c276e406bf8ee131d5e4cf74a2993d70
Gerrit URL : https://info-gerrit.apps.saic-gm.com/248674
```


### 评论 25

**排查动作**: 提交代码补丁评审

**排查结果**: 提交补丁至VCUPROmain_release4


**日志证据**:

```
Project : vcu/qnx/patac/SGMViewingRemoteApps
Branch : VCUPROmain_release4
Git Commit : 9d3daa90117b1b34f2add09a57a415c145f29a7a
Gerrit Change-Id : If78e323e8123cc2f5956dda9cfe445752a7b9671
Gerrit URL : https://info-gerrit.apps.saic-gm.com/248762
```


### 评论 26

**排查动作**: 提交代码补丁审查

**排查结果**: 代码补丁已提交，UT结果N/A


**日志证据**:

```
Project : vcu/qnx/patac/SGMViewingBsw
Branch : VCUPROmain
Git Commit : bbbf22b0406bfbb84da2f58cb003edb712fdb557
Gerrit Change-Id : Ib225a616fd8918156e7054ff4266c2c2c25f05bf
Gerrit URL : https://info-gerrit.apps.saic-gm.com/248816
UTResult : N/A
```


### 评论 27

**排查动作**: 提交代码补丁审查

**排查结果**: 代码补丁已提交，UT结果N/A


### 评论 28

**排查动作**: 发布版本并记录提交信息

**排查结果**: 已发布至L234-8255-Release4


**日志证据**:

```
[ This change has been released in tag L234-8255-Release4-20260128-UQB27B-75.zip ]
Git Commit : b7919d59af609102b09dbeb99307ea301bb02432
Gerrit URL : "https://info-gerrit.apps.saic-gm.com/248675"
```


### 评论 29

**排查动作**: 确认版本发布信息

**排查结果**: 已发布至L234-8255-Release4


**日志证据**:

```
[ This change has been released in tag L234-8255-Release4-20260128-UQB27B-75.zip ]
Git Commit : 02e927569a6cbe52d49c4e77ac9ba87f83ca5222
Gerrit URL : "https://info-gerrit.apps.saic-gm.com/248674"
```


### 评论 30

**排查动作**: 提交代码补丁审查

**排查结果**: 提交补丁至VCUPROmain_release4分支


**日志证据**:

```
Git Commit : 6e57e25b735fcd272d77675b6c328851096813f3
Gerrit Change-Id : If78e323e8123cc2f5956dda9cfe445752a7b9671
Gerrit URL : https://info-gerrit.apps.saic-gm.com/248762
```


### 评论 31

**排查动作**: 发布软件版本NDNC-8775

**排查结果**: 已发布至Release4-20260129


**日志证据**:

```
[ This change has been released in software NDNC-8775-Release4-20260129-UQB26C-77.zip ]
Git Commit : 02e927569a6cbe52d49c4e77ac9ba87f83ca5222
Gerrit URL : "https://info-gerrit.apps.saic-gm.com/248674"
```


### 评论 32

**排查动作**: 提交代码补丁评审

**排查结果**: 提交补丁至VCUPROmain_release4


**日志证据**:

```
Project : vcu/qnx/patac/SGMViewingRemoteApps
Branch : VCUPROmain_release4
Git Commit : 4f54b4f699f99bdb0380ef53524bcf3b4aabfd82
Gerrit Change-Id : If78e323e8123cc2f5956dda9cfe445752a7b9671
Gerrit URL : https://info-gerrit.apps.saic-gm.com/248762
```


### 评论 33

**排查动作**: 提交代码补丁审查

**排查结果**: 代码补丁已提交，等待审查


### 评论 34

**排查动作**: 发布版本并记录提交信息

**排查结果**: 已发布至L234-8255-Mainline-20260129


**日志证据**:

```
[ This change has been released in tag L234-8255-Mainline-20260129-UQB27B-310.zip ]
Git Commit : 02e927569a6cbe52d49c4e77ac9ba87f83ca5222
Gerrit URL : "https://info-gerrit.apps.saic-gm.com/248674"
```


### 评论 35

**排查动作**: 提交代码补丁审查

**排查结果**: 提交补丁，UT结果N/A


### 评论 36

**排查动作**: 发布版本并记录提交信息

**排查结果**: 版本已发布至L234-8255-Release4


**日志证据**:

```
[ This change has been released in tag L234-8255-Release4-20260130-UQB27B-78.zip ]
Git Commit : 7b3175f6015a8314307e23deae7e23e222f9eb41
Gerrit URL : "https://info-gerrit.apps.saic-gm.com/248963"
```


### 评论 37

**排查动作**: 发布版本并记录提交信息

**排查结果**: 版本已发布至L234-8255-Release4


**日志证据**:

```
[ This change has been released in tag L234-8255-Release4-20260130-UQB27B-78.zip ]
Git Commit : 4892701d9137c8b155ac37c4627a527bde2621dd
Gerrit URL : "https://info-gerrit.apps.saic-gm.com/248762"
```


### 评论 38

**排查动作**: 发布版本并关联代码

**排查结果**: 已发布至L234-8255-Release4


**日志证据**:

```
[ This change has been released in tag L234-8255-Release4-20260130-UQB27B-78.zip ]
Git Commit : 61898be427d51bb75d4e88b139acd2e8e94bd0c3
Gerrit URL : "https://info-gerrit.apps.saic-gm.com/249221"
```


### 评论 39

**排查动作**: 发布版本并记录提交信息

**排查结果**: 版本已发布至L234-8255-Release4


**日志证据**:

```
[ This change has been released in tag L234-8255-Release4-20260130-UQB27B-78.zip ]
Git Commit : c8e208a78b4c389f33070a5f18b051d158070b10
Gerrit URL : "https://info-gerrit.apps.saic-gm.com/248816"
```


### 评论 40

**排查动作**: 发布版本并记录提交信息

**排查结果**: 已发布至L234-8255-Mainline-20260130


**日志证据**:

```
[ This change has been released in tag L234-8255-Mainline-20260130-UQB27B-311.zip ]
Git Commit : 7b3175f6015a8314307e23deae7e23e222f9eb41
Gerrit URL : "https://info-gerrit.apps.saic-gm.com/248963"
```


### 评论 41

**排查动作**: 发布版本并记录提交信息

**排查结果**: 已发布至L234-8255-Mainline-20260130


**日志证据**:

```
[ This change has been released in tag L234-8255-Mainline-20260130-UQB27B-311.zip ]
Git Commit : 4892701d9137c8b155ac37c4627a527bde2621dd
Gerrit URL : "https://info-gerrit.apps.saic-gm.com/248762"
```


### 评论 42

**排查动作**: 发布版本并关联代码

**排查结果**: 已发布至L234-8255-Mainline-20260130


**日志证据**:

```
[ This change has been released in tag L234-8255-Mainline-20260130-UQB27B-311.zip ]
Git Commit : 61898be427d51bb75d4e88b139acd2e8e94bd0c3
Gerrit URL : "https://info-gerrit.apps.saic-gm.com/249221"
```


### 评论 43

**排查动作**: 发布版本并记录提交信息

**排查结果**: 版本已发布至指定标签


**日志证据**:

```
[ This change has been released in tag L234-8255-Mainline-20260130-UQB27B-311.zip ]
Git Commit : c8e208a78b4c389f33070a5f18b051d158070b10
Gerrit URL : "https://info-gerrit.apps.saic-gm.com/248816"
```


### 评论 44

**排查动作**: 发布软件版本NDNC-8775-Release4

**排查结果**: 修复已合入release4分支


**日志证据**:

```
[ This change has been released in software NDNC-8775-Release4-20260130-UQB26C-79.zip ]
Git Commit : 7b3175f6015a8314307e23deae7e23e222f9eb41
Gerrit URL : "https://info-gerrit.apps.saic-gm.com/248963"
```


### 评论 45

**排查动作**: 发布软件版本NDNC-8775-Release4

**排查结果**: 变更已发布至指定版本


**日志证据**:

```
[ This change has been released in software NDNC-8775-Release4-20260130-UQB26C-79.zip ]
Git Commit : 4892701d9137c8b155ac37c4627a527bde2621dd
Artifactory Link : https://jfrog-sync.apps.saic-gm.com:443/artifactory/VcuPro/NDNC_Release4/NDNC-8775-Release4-20260130-UQB26C-79/NDNC-8775-Release4-20260130-UQB26C-79.zip
```


### 评论 46

**排查动作**: 发布软件版本NDNC-8775

**排查结果**: 修复已合入主分支并发布


**日志证据**:

```
[ This change has been released in software NDNC-8775-Mainline-20260130-UQB26C-498.zip ]
Git Commit : 61898be427d51bb75d4e88b139acd2e8e94bd0c3
Gerrit URL : "https://info-gerrit.apps.saic-gm.com/249221"
```


### 评论 47

**排查动作**: 发布软件版本NDNC-8775

**排查结果**: 修复已合入主分支并发布


**日志证据**:

```
[ This change has been released in software NDNC-8775-Mainline-20260130-UQB26C-498.zip ]
Git Commit : c8e208a78b4c389f33070a5f18b051d158070b10
Gerrit URL : "https://info-gerrit.apps.saic-gm.com/248816"
```


### 评论 48

**排查动作**: 计划下周验证30号版本

**排查结果**: 待验证


### 评论 49

**排查动作**: 版本复测未复现

**排查结果**: 0130-79版本未复现，偶现问题跟踪


### 评论 50

**排查动作**: 0130-81版本复现

**排查结果**: 问题复现，附件已上传


**日志证据**:

```
发生时间14.21
```


### 评论 51

**排查动作**: 上传日志与截图附件

**排查结果**: 已添加5个附件待分析


### 评论 52

**排查动作**: 分析MQTT远控回调日志

**排查结果**: vehicleStateFail为true，需车端排查


**日志证据**:

```
2026-01-31 14:21:07.341手机端收到vehicleStateFail":true
MQTT 接受到消息: {"bizCode":"E0000","bizMsg":"远控执行成功","data":{"commandResult":{"vehicleStateFail":true}}
```


### 评论 53

**排查动作**: (Comment from 顾

**排查结果**: (Comment from 顾梦玥)
忽


**日志证据**:

```
构建时间: 2026-01-31 14:20:43.786 (Size: 0.45 KB) getMqttRemoteTypeWakeUpResult request {vin: LSGCF8N56SS132478, type: REMOTE_CAMERA_CONNECTION, sdvArchVersion: SDV1.0, params: {remoteCameraConnection: {connectionAction: RCC_START, duration: 5, cameraView: CAMERA_FRONT_SURROUND}}}
构建时间: 2026-01-31 14:20:44.337 (Size: 1.78 KB) Flutter CallBack 日志: MQTT 接受到消息: {"bizCode":"E0000","bizMsg":"远控执行成功","data":{"commandResult":{"cancelledAsRequested":false,"durationExpired":false,"gPSInvalid":false,"generalErrorDetected":false,"geoSDKErrorCode":[],"geoSDKErrorCodeMemoizedSerializedSize":0,"highVoltageBatterySoCLow":false,"maskingSDKErrorCode":[],"maskingSDKErrorCodeMemoizedSerializedSize":0,"outOfParkGear":false,"powerModeUnsatisfied":false,"restrictedAreaDetected":false,"selectedCameraNotFound":false,"streamSDKErrorCode":[],"streamSDKErrorCodeMemoizedSerializedSize":0,"tokenExpired":false,"tokenInvalid":false,"vehicleCameraError":0,"vehicleStateFail":true},"mqttTopic":"SOSOAG/SDV/1dd35149c41255ab5038a4ccdf7841ca","remoteType":"REMOTE_CAMERA_CONNECTION","requestId":"f9aec99a-fe6c-11f0-a6a8-61773f2989d4"},"traceparent":"00-fcf43ce01a4c3b12a5703a726b17150d-d792221d0515fb91-01"}===>topic==SOSOAG/SDV/1dd35149c41255ab5038a4ccdf7841ca
```


### 评论 54

**排查动作**: 提供修复版本请求测试

**排查结果**: 已修复，需验证新版本

