# VCU-233963 评论分析总结

## 排查结论

方向盘加热请求因信号HtdStrgWhlLvlAval不可用导致VHAL下设失败，问题已定位至信号源异常，待进一步排查。


## 排查过程分析

### 问题现象
方向盘加热功能请求下发失败，用户操作后加热功能未生效，VHAL 返回信号不可用错误。

### 排查过程
| 步骤 | 排查动作 | 结果 | 关键证据 |
|------|----------|------|----------|
| 1 | 复制工作项1139142 | 无新增排查，仅复制关联 | 评论1 |
| 2 | 上传实车复测日志 | 提供方向盘加热问题复现日志 | 评论2 |
| 3 | 分析CoreService下发与上报日志 | CoreService下发成功，需CarService检查信号值 | Line 76244-76245: CLEAHeatedSteeringWheelRequestProcessor processRequest |
| 4 | 分析VHAL下设失败日志 | 加热请求下发失败，未收到上报 | Line 76247-76248: GMVHAL Set HVAC_STEERING_WHEEL_HEAT_REQUEST failed |
| 5 | 分析HVAC请求失败日志 | 加热请求因信号不可用失败 | Line 76248: Set failed: Ava...；Line: Signal HtdStrgWhlLvlAval is 0 |
| 6 | 请求FW接力分析 | 等待后续分析 | 评论7 |
| 7 | 分析VHAL未上报原因 | 下设请求后未收到上报信号 | Line 76246: setProperty 0x2140020；Line 76596: VehicleController Receive |
| 8 | 确认下设失败原因 | 下设失败导致无上报，原因已说明 | 12:45:53.581 HVAC_STEERING_WHEEL_HEAT_REQUEST下设值3失败 |
| 9 | 上层排查信号前提 | 需满足信号为1才能下发 | 评论10 |
| 10 | 分析available信号上报时序 | 信号在16秒后由0变1 | 评论11 |

### 排查结论
- **已确认的事实**：VHAL 在 12:45:53.581 下发 HVAC_STEERING_WHEEL_HEAT_REQUEST 失败，错误原因为信号不可用（`Set failed: Ava...`）；同时刻 `Signal HtdStrgWhlLvlAval is 0`，即信号值为 0 导致下发被拒；CoreService 侧请求处理正常（Line 76244-76245），但 VHAL 未收到上报（Line 76596）。
- **尚未确认需进一步排查的方向**：信号 `HtdStrgWhlLvlAval` 在 12:45:37 为 0，但评论11 指出 16 秒后变为 1，需确认该信号由谁控制、为何初始为 0，以及 CarService 是否在信号变为 1 后重试下发。
- **与AI日志分析结论的一致点和差异点**：一致点：均确认指令链路在 CoreService 层正常，但最终未成功下发至 VHAL；差异点：AI 分析认为 `mHeatedSteerWheelStatus = 255` 异常状态可能导致指令被拦截，而人工排查直接定位为 VHAL 信号不可用（`HtdStrgWhlLvlAval = 0`），未


## 时序排查详情

### AI日志分析

- 方向盘加热指令可能被拦截或跳过：`onCheckEnd` 分支判断 `mIsAllClose = -1, isClose = 0`，后续是否实际发送方向盘加热指令到 CoreService/GMVHAL 无法确认（12:45:51.954，RemoteSetCLEAHeatedSteeringWheelRequestProcessor）
- mHeatedSteerWheelStatus = 255 异常状态：该值非 0 非 1，疑似未初始化或未知状态，可能导致指令被拦截或跳过（12:45:51.966，SubTopicManager）
- 气候控制指令链路正常：RemoteExecuteClimateCommandRequestProcessor 正常处理 air_distribution: AD_OFF 和 getPowerOnCommand: command = 1，说明气候控制指令链路正常（12:45:51.987，RemoteExecuteClimateCommandRequestProcessor）
- 车辆 OFF 后备车方案执行：GMVHAL 读取 SYSTEM_POWER_MODE = 0，车辆 OFF 状态，备车方案在车辆 OFF 后执行（12:45:51.966，GMVHAL）

### 评论 1

**排查动作**: 复制工作项1139142

**排查结果**: 无新增排查，仅复制关联


### 评论 2

**排查动作**: 上传实车复测日志附件

**排查结果**: 提供方向盘加热问题复现日志


### 评论 3

**排查动作**: (Comment from 李

**排查结果**: (Comment from 李振扬)
收


### 评论 4

**排查动作**: 分析CoreService下发与上报日志

**排查结果**: CoreService下发成功，需CarService检查信号值


**日志证据**:

```
Line  76244: 09-15 12:45:53.580  4360 25323 I CLEAHeatedSteeringWheelRequestProcessor: processRequest: process CabinClimate request
Line  76245: 09-15 12:45:53.580  4360 25323 I CLEAHeatedSteeringWheelRequestProcessor: cleaHSWCReq value is 5
Line  76249: 09-15 12:45:53.581  4360 25323 I CLEAHeatedSteeringWheelRequestProcessor: processRequest: finish set CLEAHeatedSteeringWheelCommand.cleaheatedsteeringwheelcommand
Line  77282: 09-15 12:45:53.660  4360  5424 I CLEAHeatedSteeringWheelStatusTopic: generate protobuf message, topic name: cls:/body.cabin_climate/1/status#CLEAHeatedSteeringWheelStatus
```


### 评论 5

**排查动作**: 分析VHAL下设失败日志

**排查结果**: 加热请求下发失败，未收到上报


**日志证据**:

```
Line  76247: 09-15 12:45:53.581  1383  1433 D GMVHAL  : vhal_set Property: HVAC_STEERING_WHEEL_HEAT_REQUEST AreaID: 16777216 Status: 0 int32Values: 3
Line  76248: 09-15 12:45:53.581  1383  1433 E GMVHAL  : Set HVAC_STEERING_WHEEL_HEAT_REQUEST failed: Availabe opt[00], client set:3
```


### 评论 6

**排查动作**: 分析HVAC请求失败日志

**排查结果**: 方向盘加热请求因信号不可用失败


**日志证据**:

```
Line 76247: 09-15 12:45:53.581 1383 1433 D GMVHAL : vhal_set Property: HVAC_STEERING_WHEEL_HEAT_REQUEST AreaID: 16777216 Status: 0 int32Values: 3
Line 76248: 09-15 12:45:53.581 1383 1433 E GMVHAL : Set HVAC_STEERING_WHEEL_HEAT_REQUEST failed: Availabe opt[00], client set:3
09-15 12:45:37.510 1383 1496 D GMVHAL : Signal HtdStrgWhlLvlAval is 0
09-15 12:45:53.627 1383 1496 D GMVHAL : Signal HtdStrgWhlLvlAval is 1
```


### 评论 7

**排查动作**: 请求FW接力分析

**排查结果**: 等待后续分析


### 评论 8

**排查动作**: 分析VHAL未上报原因

**排查结果**: 下设请求后未收到上报信号


**日志证据**:

```
Line  76246: 09-15 12:45:53.581  4360 25323 D CarPropertyManager: setProperty, propertyId: 0x21400208, areaId: 0x1000000, class: class java.lang.Integer, val: 3
Line  76596: 09-15 12:45:53.628  2186  3090 D VehicleController: Receive: CarPropertyValue{mPropertyId=0x214033dd, propertyName=0x214033dd, mAreaId=0x1000000, mStatus=0, mTimestampNanos=11738628498489, mValue=1} from CarService
```


### 评论 9

**排查动作**: 确认comment6下设失败原因

**排查结果**: 下设失败导致无上报，原因已说明


**日志证据**:

```
12:45:53.581 HVAC_STEERING_WHEEL_HEAT_REQUEST下设值3失败
```


### 评论 10

**排查动作**: 上层排查信号前提

**排查结果**: 需满足信号为1才能下发


### 评论 11

**排查动作**: 分析available信号上报时序

**排查结果**: 信号在16秒后由0变1


**日志证据**:

```
09-15 12:45:37.510  1383  1496 D GMVHAL  : Signal HtdStrgWhlLvlAval is 0
09-15 12:45:53.627  1383  1496 D GMVHAL  : Signal HtdStrgWhlLvlAval is 1
```


### 评论 12

**排查动作**: 分析BDF侧CAN总线数据

**排查结果**: HSW响应正常，非BDF问题


**日志证据**:

```
RVS Active后正常响应HMI HSW Request=High请求
HSW Level Available及HSW Indication均正常发送
收到HMI HSW Request=Off指令，方向盘加热关闭
HSW Level Available=Two Levels Available 早于 RVS Status=Active 10ms 发出
HMI HSW Request=High 下发时 HSW Level Available=Two Levels Available
```


### 评论 13

**排查动作**: 添加方向盘加热CAN数据分析附件

**排查结果**: 已上传BDF侧数据分析PDF


**日志证据**:

```
附件 2282814 (BDF侧方向盘加热CAN数据分析.pdf)
```


### 评论 14

**排查动作**: 添加远控失败案例截图

**排查结果**: 已添加附件，待进一步分析


### 评论 15

**排查动作**: 分析失败案例时序

**排查结果**: Available信号晚于Status 50ms导致请求未发出


**日志证据**:

```
09-15 12:45:53.627
SPY3数据中4:45:54秒左右
Remote Start Status 先发出，Heated Steering Wheel Levels Available 之后发出。时间间隔50ms
```


### 评论 16

**排查动作**: 与BDF模型确认时序

**排查结果**: 时间间隔应在100-200ms，案例120/170ms


**日志证据**:

```
HSW Level Available=Two Levels Available基于PSA=True后发出
模型处理最大时间100ms
0x41E-HSW Level Available更新时间100ms
0x0C6 PSA信号周期25ms
成功案例是120ms，失败案例是170ms
```


### 评论 17

**排查动作**: 提交代码补丁审查

**排查结果**: 提交补丁至VCUPROmain分支


**日志证据**:

```
Project : SDVRemoteControlService
Branch : VCUPROmain
Git Commit : 6e5594b827999b589da7d4ffe96ab3f050ff12d8
Gerrit Change-Id : If75fd2013bdc1d263c54fa825fe259c47e5b1b55
Gerrit URL : https://info-gerrit.apps.saic-gm.com/225286
```


### 评论 18

**排查动作**: 提交代码补丁审查

**排查结果**: 提交补丁至VCUPRO分支


**日志证据**:

```
Project : SDVRemoteControlService
Branch : VCUPROmain_release3
Git Commit : 43e26f8f52b74f6d59bd087ea8fee1f5e0f2ee3f
Gerrit Change-Id : If75fd2013bdc1d263c54fa825fe259c47e5b1b55
Gerrit URL : https://info-gerrit.apps.saic-gm.com/225287
```


### 评论 19

**排查动作**: 发布修复版本

**排查结果**: 修复已发布至557-8775-Release3


**日志证据**:

```
[ This change has been released in tag 557-8775-Release3-20250926-UQB26C-84.zip ]
Git Commit : 43e26f8f52b74f6d59bd087ea8fee1f5e0f2ee3f
Gerrit URL : "https://info-gerrit.apps.saic-gm.com/225287"
```


### 评论 20

**排查动作**: 发布修复版本并记录提交

**排查结果**: 修复已发布至557-8255-Release3


**日志证据**:

```
[ This change has been released in tag 557-8255-Release3-20250926-UQB26C-108.zip ]
Git Commit : 43e26f8f52b74f6d59bd087ea8fee1f5e0f2ee3f
Gerrit URL : "https://info-gerrit.apps.saic-gm.com/225287"
```


### 评论 21

**排查动作**: 发布版本并关联代码

**排查结果**: 已发布至L234-8255-Mainline-20250926


**日志证据**:

```
[ This change has been released in tag L234-8255-Mainline-20250926-UQB26B-104.zip ]
Git Commit : 6e5594b827999b589da7d4ffe96ab3f050ff12d8
Gerrit URL : "https://info-gerrit.apps.saic-gm.com/225286"
```


### 评论 22

**排查动作**: 发布版本并记录提交信息

**排查结果**: 版本已发布至指定tag


**日志证据**:

```
[ This change has been released in tag 557-8255-Mainline-20250926-UQB26C-1064.zip ]
Git Commit : 6e5594b827999b589da7d4ffe96ab3f050ff12d8
Gerrit URL : "https://info-gerrit.apps.saic-gm.com/225286"
```


### 评论 23

**排查动作**: 发布修复版本并关联代码

**排查结果**: 修复已发布至557-8775-Mainline标签


**日志证据**:

```
[ This change has been released in tag 557-8775-Mainline-20250926-UQB26C-160.zip ]
Git Commit : 6e5594b827999b589da7d4ffe96ab3f050ff12d8
Gerrit URL : "https://info-gerrit.apps.saic-gm.com/225286"
```


### 评论 24

**排查动作**: 发布软件版本NDNC-8775

**排查结果**: 修复已合入主分支并发布


**日志证据**:

```
[ This change has been released in software NDNC-8775-Mainline-20250928-UQB26C-220.zip ]
Git Commit : 6e5594b827999b589da7d4ffe96ab3f050ff12d8
Gerrit URL : "https://info-gerrit.apps.saic-gm.com/225286"
```


### 评论 25

**排查动作**: 提交代码补丁修复

**排查结果**: 提交补丁至VCUPROmain_release2分支


**日志证据**:

```
Project : SDVRemoteControlService
Branch : VCUPROmain_release2
Git Commit : a7ae428a3f26836582d3309ef54948beb3a837e6
Gerrit Change-Id : I911c2db137904482761b2bfab868f8727fed44c2
Gerrit URL : https://info-gerrit.apps.saic-gm.com/226147
```


### 评论 26

**排查动作**: 提交代码补丁修复

**排查结果**: 提交补丁至VCUPROmain_release2分支


**日志证据**:

```
Project : SDVRemoteControlService
Branch : VCUPROmain_release2
Git Commit : 5dc3c1d8a0407094d1f4a359fa0dd1468eeb01b3
Gerrit Change-Id : If75fd2013bdc1d263c54fa825fe259c47e5b1b55
Gerrit URL : https://info-gerrit.apps.saic-gm.com/226349
```


### 评论 27

**排查动作**: 发布软件版本NDNC-8775

**排查结果**: 修复已发布至Release2


**日志证据**:

```
[ This change has been released in software NDNC-8775-Release2-20250929-UQB26C-311.zip ]
```


### 评论 28

**排查动作**: 发布软件版本NDNC-8775

**排查结果**: 修复已发布至Release2版本


**日志证据**:

```
[ This change has been released in software NDNC-8775-Release2-20250929-UQB26C-311.zip ]
```


### 评论 29

**排查动作**: 参考comment28测试NDNC版本

**排查结果**: 需使用29号之后的版本


### 评论 30

**排查动作**: 实车验证1017-233版本

**排查结果**: 10次未复现问题

