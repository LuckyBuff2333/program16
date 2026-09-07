# VCU-222723 评论分析总结

## 排查结论

远程车门解闭锁失败因安吉星未下发请求，且8155 BDF版本与信号定义存在差异，问题已定位，待对手件及版本确认。


## 排查过程分析

### 问题现象
实车测试7-5及V5.0版本时，远程车门解闭锁功能失败，且安吉星后台未下发请求，VCU信号一直为no action。

### 排查过程
| 步骤 | 排查动作 | 结果 | 关键证据 |
|------|----------|------|----------|
| 1 | 实车复测7-5版本 | 问题未复现 | 评论1：需进一步观察 |
| 2 | 上传复测日志视频 | 提供失败材料 | 附件2102298-2102300（gmlogger0705、失败视频） |
| 3 | 确认门锁远控失败原因 | BDF 5.0修改控制信号 | 评论3：需对手件确认 |
| 4 | 添加崩溃截图 | 已上传现场图片 | 评论4附件 |
| 5 | 分析安吉星请求日志 | 安吉星未发送请求 | 评论5：从log分析安吉星没发请求，附件2103112 |
| 6 | 指派安吉星分析 | 等待李工确认 | 评论6 |
| 7 | 确认热车解闭锁信号定义 | 信号为Door Control Request VCU_SDV remote door lock request | 评论7：72.1以后 |
| 8 | 更新远程控制方案CR | 方案更新完成 | 评论8 |
| 9 | 确认测试软件版本及信号 | 需确认VeSCoME BDF及VC5.0 | 评论9 |
| 10 | 澄清控制信号来源 | 非安吉星信号，非ICM enhancement | 评论10：Door Control Request VCU_Unused and Reserved 8 |
| 11 | 确认8155 BDF版本 | 测试时BDF为V4.5 | 评论11：7-5测试时，8155的BDF是V4.5 |
| 12 | 明确NDF版本与信号差异 | V4.5与V5.0信号有变更 | 评论12：需明确测试环境 |
| 13 | 上传实车日志附件 | 已提供RBF及gmlogger日志 | 附件rec_6377693、gmlogger_2025_7_8 |
| 14 | 实车复测V5.0版本 | 车门上锁解锁仍失败 | 评论14 |
| 15 | 确认BDF版本及零件号 | 需DPS读取BDF零件号 | 评论15 |
| 16 | 请求查看刷机后日志 | 等待郭工确认 | 评论16 |
| 17 | 分析VCU信号数据 | 信号一直为no action | 评论17：Door Control Request VCU_SDV remote door lock request一直是no action |
| 18 | 添加崩溃截图 | 已上传现场截图 | 评论18 |
| 19 | 确认8155远控定位 | 待确认是否同8775问题 | 评论19 |
| 20 | 排查VCU远程锁车信号 | VCU未发远程请求，排除后台误触发 | 评论20：15:53:55前主驾门开未锁，15


## 时序排查详情

### AI日志分析

- 分析过程失败：推理层在未获得任何工具返回结果的情况下被系统提示"未调用任何工具"，随后仍重复发起相同搜索，未切换搜索策略或使用 read_time_range 读取关键时间段原始日志，分析过程陷入死循环（15:53:05，推理历史）。
- 车端信号层可能存在通信异常：日志概览显示 GMVHAL（PID 1234）存在大量 Invalid Frame 相关日志，CarPropertyManager 和 ServiceBus 均标记为异常/超时，但推理层未进一步追踪验证（15:53:05，日志概览）。
- 推理层未完成任何有效的日志搜索或证据收集：仅重复发起对 RemoteExecuteDoorCommandRequestProcessor 的搜索但未获得任何工具返回结果，无法确认车门远控指令在车端的实际执行路径和失败原因（15:53:05，推理历史）。

### 评论 1

**排查动作**: 实车复测7-5版本

**排查结果**: 问题未复现，需进一步观察


### 评论 2

**排查动作**: 上传实车复测日志视频

**排查结果**: 提供车门解闭锁失败复现材料


**日志证据**:

```
附件 2102298 (gmlogger0705.part1.rar)
附件 2102299 (gmlogger0705.part2.rar)
附件 2102300 (车门解闭锁-失败-1916.mp4)
附件 2102301 (rec_6377693_default_2025-07-05-19_13_47_51.rbf.gz)
```


### 评论 3

**排查动作**: 确认门锁远控失败原因

**排查结果**: BDF 5.0修改控制信号，需对手件确认


### 评论 4

**排查动作**: 添加崩溃截图附件

**排查结果**: 已上传现场图片证据


### 评论 5

**排查动作**: 分析安吉星请求日志

**排查结果**: 安吉星未发送请求


**日志证据**:

```
从log分析安吉星没发请求，附件 2103112
```


### 评论 6

**排查动作**: 指派安吉星分析

**排查结果**: 等待李工确认负责人


### 评论 7

**排查动作**: 确认热车解闭锁信号定义

**排查结果**: 确认信号为Door Control Request VCU_SDV remote door lock request


**日志证据**:

```
Door Control Request VCU Signal Group : Door Control Request VCU_SDV remote door lock request（72.1以后）
```


### 评论 8

**排查动作**: 更新远程控制方案CR

**排查结果**: 方案更新完成


### 评论 9

**排查动作**: 确认测试软件版本及信号

**排查结果**: 需确认VeSCoME BDF及VC5.0软件


### 评论 10

**排查动作**: 澄清控制信号来源

**排查结果**: 非安吉星信号，非ICM enhancement


**日志证据**:

```
Door Control Request VCU Signal Group : Door Control Request VCU_Unused and Reserved 8
```


### 评论 11

**排查动作**: 确认8155 BDF版本

**排查结果**: 测试时BDF为V4.5


**日志证据**:

```
7-5测试时，8155的BDF是V4.5
```


### 评论 12

**排查动作**: 明确NDF版本与信号差异

**排查结果**: V4.5与V5.0信号有变更，需明确测试环境


### 评论 13

**排查动作**: 上传实车日志附件

**排查结果**: 已提供RBF及gmlogger日志


**日志证据**:

```
rec_6377693_default_2025-07-08-15_50_21_1.rbf.gz
gmlogger_2025_7_8_15_55_42.part1.rar
gmlogger_2025_7_8_15_55_42.part2.rar
```


### 评论 14

**排查动作**: 实车复测V5.0版本

**排查结果**: 车门上锁解锁仍失败


### 评论 15

**排查动作**: 确认BDF版本及零件号

**排查结果**: 需DPS读取BDF零件号确认


### 评论 16

**排查动作**: 请求查看刷机后日志

**排查结果**: 等待郭工确认日志


### 评论 17

**排查动作**: 分析VCU信号数据

**排查结果**: 信号一直为no action


**日志证据**:

```
Door Control Request VCU Signal Group : Door Control Request VCU_SDV remote door lock request一直是no action
```


### 评论 18

**排查动作**: 添加崩溃截图附件

**排查结果**: 已上传现场截图


### 评论 19

**排查动作**: 确认8155远控定位

**排查结果**: 待确认是否同8775问题


### 评论 20

**排查动作**: 排查VCU远程锁车信号

**排查结果**: VCU未发远程请求，排除后台误触发


**日志证据**:

```
15:53:55前初始车况：主驾门开未锁，左后门关未锁，副驾右后门关已锁
15:53:55-15:54:08主驾门始终开启
15:53:55副驾右后门解锁，触发源中控或门把手
15:53:56四门落锁，触发源中控或门把手
15:53:58主驾防反锁自动解锁
15:53:58自动解锁后600ms再次上锁
15:54:00主驾再次防反锁解锁
15:54:00再次解锁后600ms再上锁
15:54:01四门防反锁解锁
15:54:08主驾门关闭保持解锁
15:54:09四门上锁，触发源中控或门把手
全程总线未收到VCU远程上锁解锁信号
```


### 评论 21

**排查动作**: 添加附件截图

**排查结果**: 已添加附件，待进一步分析


### 评论 22

**排查动作**: 日志链路排查请求下发

**排查结果**: 请求已下发至CarService


**日志证据**:

```
Line 148049: 07-08 15:54:09.216  5293  5575 I RemoteControlRequestProcessFactory: getRequestProcessor: processor = cls:/remote_control/1/rpc.RemoteExecuteDoorCommand
Line 149642: 07-08 15:54:09.696  5293  8844 I RemoteExecuteDoorCommandRequestProcessor: processRequest: req = message_id: "DoorRequest"
Line 151776: 07-08 15:54:10.188  7254  7349 I DoorRequestProcessor: processRequest: process door request
Line 151800: 07-08 15:54:10.196  7254  7349 D CarPropertyManager: setProperty, propertyId: 0x2140509f, areaId: 0x1000000, class: class java.lang.Integer, val: 1
```


### 评论 23

**排查动作**: 问题转派至Bosch开发

**排查结果**: 转派肖凯并修改负责人


### 评论 24

**排查动作**: 分析远程锁车日志

**排查结果**: 远程锁车指令正常下发


**日志证据**:

```
07-08 15:54:10.196  7254  7349 I DoorRequestProcessor: remote_lock_command
07-08 15:54:10.196  7254  7349 I DoorRequestProcessor: executeReqRemoteLockCommand: 1
07-08 15:54:10.197  1234  1318 D GMVHAL  : vhal_set Property: REMOTE_VEHICLE_START_SOFTWARE_DEFINED_FEATURE_REQUEST_SERVICE AreaID: 16777216 Status: 0 int32Values: 1
```


### 评论 25

**排查动作**: 日志信号下发分析

**排查结果**: 信号已下发至MCU侧，待确认


**日志证据**:

```
07-08 15:54:10.197  1234  1318 D GMVHAL  : vhal_set Property: REMOTE_VEHICLE_START_SOFTWARE_DEFINED_FEATURE_REQUEST_SERVICE AreaID: 16777216 Status: 0 int32Values: 1 
07-08 15:54:10.197  1234  1318 D GMVHAL  : TX Message f1 0c 01 90 e0 08 00 00 00 00 00 00 00 02 
07-08 15:54:10.197  1234  1318 D GMVHAL  : SET REMOTE_VEHICLE_START_SOFTWARE_DEFINED_FEATURE_REQUEST_SERVICE SUCCESS
```


### 评论 26

**排查动作**: 添加总线信号附件

**排查结果**: 已添加附件，待分析


**日志证据**:

```
附件 2122151 (总线信号.png)
```


### 评论 27

**排查动作**: CAN trace信号分析

**排查结果**: 信号下设通路正常，值0到1变化


**日志证据**:

```
RmVhStrtSDFReqFncReqSrv  0x47F(MAC报文）VR_BCM_Request_47F_M  PCAN
信号值有0到1变化，与vhal下发日志相符
```


### 评论 28

**排查动作**: 转交对手件确认

**排查结果**: 待对手件方处理


### 评论 29

**排查动作**: 分析VCU信号状态

**排查结果**: Door Control Request信号无动作


**日志证据**:

```
VCU信号Door Control Request VCU Signal Group : Door Control Request VCU_SDV remote door lock request一直是no action
```


### 评论 30

**排查动作**: 回看评论27及20/21

**排查结果**: 确认测试状态为power mode run


**日志证据**:

```
47F是远程启动请求，上锁解锁请求是0x348
这段Log我从总线上面看是在power mode run的状态测试的
```


### 评论 31

**排查动作**: 核查信号数据库版本

**排查结果**: 信号仅存在于72.1数据库，70.4无此信号


**日志证据**:

```
Door Control Request VCU Signal Group : Door Control Request VCU_SDV remote door lock request
```


### 评论 32

**排查动作**: 核对数据库信号定义

**排查结果**: 仅更名，枚举值未变，可mapping


**日志证据**:

```
Door Control Request VCU Signal Group : Door Control Request VCU_Unused and Reserved 8
$0=no action无动作，$1=lock all上锁四门，$2=unlock all解锁四门，$3为仅尾门释放
```


### 评论 33

**排查动作**: 添加总线信号附件

**排查结果**: 已添加附件，待分析


### 评论 34

**排查动作**: 分析CAN trace总线信号

**排查结果**: DoCtrlReqVCU_UnandRsv8_PCB恒为0


**日志证据**:

```
总线信号DoCtrlReqVCU_UnandRsv8_PCB值一直为0,没有变化
```


### 评论 35

**排查动作**: 源头信号链路分析

**排查结果**: 信号正常下发，需源头确认


### 评论 36

**排查动作**: 确认信号下发方

**排查结果**: VCU下发为0，转BOSCH分析


### 评论 37

**排查动作**: 分析赋值逻辑

**排查结果**: 需应用调用赋值才下发正确值


### 评论 38

**排查动作**: 添加附件截图

**排查结果**: 已添加附件，待进一步分析


### 评论 39

**排查动作**: 结合spec文档核对信号

**排查结果**: 确认0x2140509f对应DoCtrlReqVCU_UnandRsv8_PCB


### 评论 40

**排查动作**: 请求调用framework接口下设信号

**排查结果**: 等待顾工执行信号下设操作


### 评论 41

**排查动作**: 请求提供设锁车信号接口

**排查结果**: 待范豪提供接口给顾工


### 评论 42

**排查动作**: 建议统一调用fwk接口

**排查结果**: APP直接下设可能导致信号不一致


**日志证据**:

```
Log.e(TAG, "unsupported ARCH!")
```


### 评论 43

**排查动作**: 对齐平台策略接口

**排查结果**: 要求按8155策略提供接口


### 评论 44

**排查动作**: 确认解决方案并推进

**排查结果**: 超过3天未解决，需确认方案


### 评论 45

**排查动作**: 等待博世输出info3jar包

**排查结果**: 当前处于等待状态


### 评论 46

**排查动作**: 请求bosh输出info3jar包

**排查结果**: 等待bosh同事提供jar包


### 评论 47

**排查动作**: 确认jar包信号包含情况

**排查结果**: 需确认jar包是否含指定信号


**日志证据**:

```
DOOR_CONTROL_REQUEST_VCU_UNUSED_AND_RESERVED_8
```


### 评论 48

**排查动作**: 等待博世输出info3jar包

**排查结果**: 同jar包问题，待解决


### 评论 49

**排查动作**: 确认修复版本与测试状态

**排查结果**: 待确认修复版本，需博世推进


### 评论 50

**排查动作**: 添加附件截图

**排查结果**: 已添加附件，待进一步分析


### 评论 51

**排查动作**: 查看附件图片

**排查结果**: 待确认图片内容


### 评论 52

**排查动作**: 添加附件截图

**排查结果**: 已添加附件


### 评论 53

**排查动作**: 标记修复版本

**排查结果**: 已在页面标记修复版本


### 评论 54

**排查动作**: 复测0721VCU远控指令

**排查结果**: 复测不通过，车端未执行


### 评论 55

**排查动作**: 参考Bug 1093848

**排查结果**: 关联已知问题，待进一步排查


### 评论 56

**排查动作**: 分析门锁请求信号映射

**排查结果**: 门锁请求错误对应远程启动信号


**日志证据**:

```
07-23 10:04:11.757  1313  1341 D GMVHAL  : vhal_set Property: REMOTE_VEHICLE_START_SOFTWARE_DEFINED_FEATURE_REQUEST_SERVICE AreaID: 16777216 Status: 0 int32Values: 1
```


### 评论 57

**排查动作**: 分析VHAL下发信号差异

**排查结果**: APP已改但VHAL未同步，需查下设逻辑


**日志证据**:

```
APP侧已修改下发信号为PatacProperty.DOOR_CONTROL_REQUEST_VCU_UNUSED_AND_RESERVED_8
VHAL侧下发的还是REMOTE_VEHICLE_START_SOFTWARE_DEFINED_FEATURE_REQUEST_SERVICE
```


### 评论 58

**排查动作**: 要求应用侧确认接口调用

**排查结果**: 需使用fwk封装接口，禁用原生接口


### 评论 59

**排查动作**: 确认接口调用方式

**排查结果**: 确认可通过property name调用


### 评论 60

**排查动作**: 确认属性ID映射

**排查结果**: 属性ID为557863071，需确认


**日志证据**:

```
07-23 10:04:11.757  1313  1341 D GMVHAL  : vhal_set Property: REMOTE_VEHICLE_START_SOFTWARE_DEFINED_FEATURE_REQUEST_SERVICE AreaID: 16777216 Status: 0 int32Values: 1
```


### 评论 61

**排查动作**: 确认修复状态

**排查结果**: 已修复，0725


### 评论 62

**排查动作**: 请求PM协调版本

**排查结果**: 等待版本协调


### 评论 63

**排查动作**: 上传操作视频附件

**排查结果**: 已添加操作视频附件


**日志证据**:

```
附件 2166670 (操作视频.mp4)
```


### 评论 64

**排查动作**: VCU 0727版本验证

**排查结果**: 验证通过

