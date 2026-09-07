# VCU-162205 评论分析总结

## 排查结论

AHBA功能标定已开启但HMI请求后信号无变化，CAN日志与视频时间不匹配，功能状态待进一步排查确认。


## 排查过程分析

### 问题现象
自动远光灯（AHBA）功能在车辆设置界面中显示异常，HMI已发送控制请求但实际功能无效果，且CAN日志与视频时间不匹配，无法确认功能状态。

### 排查过程
| 步骤 | 排查动作 | 结果 | 关键证据 |
|------|----------|------|----------|
| 1 | 复制工作项873248 | 无新增动作 | 评论1无日志 |
| 2 | 上传复现日志与视频 | 提供复现材料 | 附件1515358/1515367/1515368 |
| 3 | 检查标定文件AHBA配置 | 支持自动远光灯 | P_VEHICLE_CONTROL_AHBA_ENABLE: 1 |
| 4 | 确认E2QL显示需求 | 不支持自动远光 | 评论4待确认显示 |
| 5 | 添加附件截图 | 已添加 | 附件1522290 |
| 6 | 解析CALBOM默认值 | Buick需查5个Cal | "P_VEHICLE_CONTROL_HEADLAMPS_ENABLE"等 |
| 7 | 检查标定值判断 | 标定值为1显示正常 | 标定值为1 |
| 8 | 确认功能状态 | 待确认 | 评论8无结论 |
| 9 | 信号分析功能效果 | 发送后无效果 | 评论9无日志 |
| 10 | 上传复现视频日志 | 已提供待分析 | 评论10附件 |
| 11 | 上传gmlogger日志 | 提供新日志 | 评论11附件 |
| 12 | 确认控制信号类型 | 需看request信号 | Virtual Control Auto High Beam Request |
| 13 | 催促确认状态 | 待确认OK则WAD | 评论13 |
| 14 | 查看附件log信号 | 信号无变化 | 评论14无日志 |
| 15 | 分析HMI控制信号 | HMI已发送请求 | setAhbaStatus va 15:09:51/15:10:11/15:10:20 |
| 16 | 上传CAN/USB日志 | 已提供待指示 | 评论16附件 |
| 17 | 检查信号删除情况 | 视频未体现 | 评论17 |
| 18 | 检查CAN log和视频 | 附件含操作记录 | 评论18附件 |
| 19 | 核对时间一致性 | 时间对不上 | canlog只取到15:09，视频时 |

### 排查结论
- **已确认的事实**：标定文件支持AHBA（P_VEHICLE_CONTROL_AHBA_ENABLE=1）；HMI已发送3次setAhbaStatus请求（15:09:51/15:10:11/15:10:20）；CAN日志与视频时间不匹配（canlog止于15:09）。
- **尚未确认需进一步排查的方向**：CAN总线上request信号是否实际发出及车身响应；E2QL车型是否应显示自动远光选项；Buick的5个Cal默认值组合逻辑是否影响显示。
- **与AI日志分析结论的一致点**：均认为日志时间窗口不完整（AI指出15:


## 时序排查详情

### AI日志分析

- 无法确定具体根因：日志中未找到与"自动远光灯系统"直接相关的配置读取或显示逻辑证据，也未找到车型配置标识（E2QL/MY23/VeSCoM）的同步记录（15:10:42~15:12:01，VrPropertyManagerBase）
- 日志时间窗口不完整：问题发生时间15:10:20，但日志最早记录为15:10:42，存在22秒的窗口外事件，无法排除关键配置读取发生在窗口外（15:10:20~15:10:42，日志文件）
- 未发现车型配置同步记录：搜索E2QL、MY23、VeSCoM等关键词均无结果，无法验证假设1中"车型配置标识读取错误"的推测（15:10:42~15:12:01，CanFuseRepository和DBATripManager）
- 未发现PowerManagerService超时与设置界面初始化时序重叠的证据：日志中未发现PowerManagerService超时与设置界面初始化时序重叠的证据（15:10:43~15:12:00，PowerManagerService）
- 根因可能位于日志时间窗口之外：由于日志时间窗口不完整，根因可能发生在15:10:20之前，无法从当前日志中定位（15:10:20之前，日志文件）
- 根因可能不涉及日志中可搜索的模块：设置界面的显示逻辑可能由其他未在日志中出现的模块控制，或者该问题属于配置问题而非运行时错误（15:10:42~15:12:01，日志文件）

### 评论 1

**排查动作**: 复制工作项873248

**排查结果**: 无新增排查动作


### 评论 2

**排查动作**: 上传复现日志与视频

**排查结果**: 提供功能缺少问题复现材料


**日志证据**:

```
附件 1515358 (功能缺少 6-06-2024 10-20-02 am.7z.001)
附件 1515367 (gmlogger_2024_6_6_10_19_39.7z.001)
附件 1515368 (83c14ce5e7dc87024cd21d9e3affc6e9.mp4)
```


### 评论 3

**排查动作**: 检查标定文件AHBA配置

**排查结果**: 支持自动远光灯系统


**日志证据**:

```
P_VEHICLE_CONTROL_AHBA_ENABLE: ENUMERATION: P_VEHICLE_CONTROL_AHBA_ENABLE: ENUMERATION: 1
```


### 评论 4

**排查动作**: 确认E2QL自动远光显示需求

**排查结果**: 不支持自动远光，需确认是否显示


### 评论 5

**排查动作**: 添加附件截图

**排查结果**: 已添加附件1522290


### 评论 6

**排查动作**: 解析CALBOM默认值要求

**排查结果**: Buick需按5个Cal判断默认值


**日志证据**:

```
Use default value always for Cadi&Chevy; For Buick need to check following Cals
"P_VEHICLE_CONTROL_HEADLAMPS_ENABLE";"P_VEHICLE_CONTROL_FRONT_FOG_LAMPS_ENABLE";"P_VEHICLE_CONTROL_REAR_FOG_LAMPS_ENABLE";"P_VEHICLE_CONTROL_DOME_LIGHT_ENABLE"; "P_VEHICLE_CONTROL_AHBA_ENABLE"
False: if all these Cals are False
Ture: if more than one Cals are Ture
```


### 评论 7

**排查动作**: 检查标定值判断逻辑

**排查结果**: 标定值为1，显示逻辑正常


**日志证据**:

```
标定值为1
```


### 评论 8

**排查动作**: 信号确认自动远光灯功能

**排查结果**: 待确认功能状态


### 评论 9

**排查动作**: 信号分析功能无效果

**排查结果**: 功能发送后实际无效果


### 评论 10

**排查动作**: 上传复现视频与日志附件

**排查结果**: 已提供复现素材，待分析


### 评论 11

**排查动作**: 上传gmlogger日志附件

**排查结果**: 提供新日志供分析


### 评论 12

**排查动作**: 确认控制信号类型

**排查结果**: 需查看request信号而非设置信号


**日志证据**:

```
控制信号为Virtual Control Auto High Beam Request
```


### 评论 13

**排查动作**: 催促确认问题状态

**排查结果**: 待确认，OK则WAD


### 评论 14

**排查动作**: 查看附件log信号

**排查结果**: 信号无变化


### 评论 15

**排查动作**: 分析HMI控制信号日志

**排查结果**: HMI已发送请求，需CAN日志确认


**日志证据**:

```
06-18 15:09:51.473  4062  4240 I com.patac.hmi.gmsettings-LightControllerManager: │ setAhbaStatus value = 1
06-18 15:10:11.205  4062  4191 I com.patac.hmi.gmsettings-LightControllerManager: │ setAhbaStatus value = 2
06-18 15:10:20.282  4062  4235 I com.patac.hmi.gmsettings-LightControllerManager: │ setAhbaStatus value = 1
06-18 15:10:31.368  4062  4240 I com.patac.hmi.gmsettings-LightControllerManager: │ setAhbaStatus value = 2
06-18 15:10:32.753  4062  4236 I com.patac.hmi.gmsettings-LightControllerManager: │ setAhbaStatus value = 1
```


### 评论 16

**排查动作**: 上传CAN/USB日志及视频

**排查结果**: 已提供所需日志，等待进一步指示


### 评论 17

**排查动作**: 检查信号删除情况

**排查结果**: 视频未体现检查该信号


### 评论 18

**排查动作**: 检查附件CAN log和视频

**排查结果**: 附件存在，含操作记录


### 评论 19

**排查动作**: 核对canlog与视频时间

**排查结果**: 时间对不上，需补充日志


**日志证据**:

```
canlog只取到15:09，视频时间为15：10
```


### 评论 20

**排查动作**: 添加附件截图

**排查结果**: 已添加附件1531187


### 评论 21

**排查动作**: 请求重新截取logs

**排查结果**: 等待新日志提供

