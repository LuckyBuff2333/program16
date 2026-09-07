# VCU-238243 评论分析总结

## 排查结论

已定位：AHBA状态值设为2但接口无回调，对手件不响应VCU请求，复测确认与CR 1113095为同一问题。


## 排查过程分析

### 问题现象
用户操作自动远光灯功能时，HMI界面显示高亮但车辆远光灯实际未激活，且底层VCU对手件不响应请求，疑似链路中断。

### 排查过程
| 步骤 | 排查动作 | 结果 | 关键证据 |
|------|----------|------|----------|
| 1 | 复制工作项1132835 | 无新增动作 | 评论1无日志 |
| 2 | 上传实车gmlogger与rec日志 | 提供日志供分析 | 附件2250471/2250472/2250475 |
| 3 | 请求提供实车视频 | 等待用户补充 | 评论3无日志 |
| 4 | 上传实车复测视频 | 已添加mp4附件 | 附件2250509 |
| 5 | 补传视频并请求分析 | 待继续分析 | 评论5无日志 |
| 6 | 分析AHBA状态日志 | AHBA状态值设为2 | 16:25:10.547 setAhbaStatus value |
| 7 | 分析接口调用日志 | 未收到回调，疑似同bug1122517 | 行13319/13328/18771 |
| 8 | 添加截图附件 | 已添加附件 | 附件2250588 |
| 9 | 确认对手件响应状态 | 对手件不响应VCU请求 | 评论9无日志 |
| 10 | 复测557 BDF V16.0断点 | 确认与CR 1113095相同问题 | 评论10无日志 |

### 排查结论
- **已确认的事实**：AHBA状态值被设为2（16:25:10.547）；接口调用后未收到回调（行13319/13328/18771）；对手件不响应VCU请求；复测确认与CR 1113095相同问题。
- **尚未确认需进一步排查的方向**：HMI层与CoreService之间链路断裂的具体原因；onAhbaControlAvailableChanged value=0 触发机制；UI状态与实际状态不一致的根因。
- **与AI日志分析结论的一致点**：均确认链路在HMI层与CoreService之间断裂，且UI状态与实际车辆状态不一致。
- **与AI日志分析结论的差异点**：AI分析指出底层远光灯未激活（HiBmIO=false）与Bug描述"一直高亮"矛盾，而人工排查更侧重于对手件不响应VCU请求，未明确提及该矛盾点。


## 时序排查详情

### AI日志分析

- 链路断裂：setAutoHighBeamAssistStatus 调用后，未发现该指令传递到 CoreService 或 LightingSomeIpClient 的日志证据，链路在 HMI 层与 CoreService 之间断裂（16:25:04.272，BasePatacAutoHighBeamSignal）
- 控制可用性异常：onAhbaControlAvailableChanged value=0 在用户点击前触发，表明自动远光灯控制可用性已变为不可用，可能影响后续指令处理（16:25:03.571，onAhbaControlAvailableChanged）
- UI 状态与实际状态不一致：PatacAutoHighBeamViewModel 在 16:25:03.572 更新状态为 selected=true，但底层远光灯状态为 HiBmIO=false，UI 状态与实际车辆状态不一致（16:25:03.572 / 16:25:03.575，PatacAutoHighBeamViewModel / LightingSomeIpClient）
- 底层远光灯未激活：LightingSomeIpClient 在 16:25:03.575 收到 NOTIFY_EXTERIOR_LIGHTING 通知，HiBmIO=false 表明远光灯未激活，与 Bug 描述"一直高亮"矛盾（16:25:03.575，LightingSomeIpClient）

### 评论 1

**排查动作**: 复制工作项1132835

**排查结果**: 无新增排查动作


### 评论 2

**排查动作**: 上传实车日志附件

**排查结果**: 提供gmlogger与rec日志供分析


**日志证据**:

```
附件 2250471 (gmlogger_2025_9_2_16_27_39.zip.001)
附件 2250472 (gmlogger_2025_9_2_16_27_39.zip.002)
附件 2250475 (rec_6377771_default_2025-09-02-16_21_36_4.rbf.gz)
```


### 评论 3

**排查动作**: 请求提供视频

**排查结果**: 等待用户补充视频


### 评论 4

**排查动作**: 上传实车复测视频

**排查结果**: 已添加附件mp4视频


**日志证据**:

```
附件 2250509 (0e7cec066e5e2462983d5c20530a7ce7.mp4)
```


### 评论 5

**排查动作**: 补传视频并请求分析

**排查结果**: 已补传视频，待继续分析


### 评论 6

**排查动作**: 分析AHBA状态日志

**排查结果**: AHBA状态值设为2


**日志证据**:

```
09-02 16:25:10.547  4317 11288 D com.patac.hmi.settings-LightControllerManager: setAhbaStatus value = 2
```


### 评论 7

**排查动作**: 分析接口调用日志

**排查结果**: 未收到回调，疑似同bug1122517


**日志证据**:

```
行 13319: 09-02 16:25:08.911  4317  4413 D VehicleController: get property[VendorProperty.VIRTUAL_CONTROL_AUTO_HIGH_BEAM_STATUS_CONTROL_AVAILABLE] : CarPropertyValue{mPropertyId=0x21401281, propertyName=0x21401281, mAreaId=0x1000000, mStatus=0, mTimestampNanos=6841980257, mValue=1}
行 13328: 09-02 16:25:08.912  4317  4413 I com.patac.hmi.settings-LightControllerManager: isAhbaSupportIviControl = com.patac.vehicle.VehicleController$Result@fce3924, configArray = []
行 18771: 09-02 16:25:10.547  4317 11288 D com.patac.hmi.settings-LightControllerManager: setAhbaStatus value = 2
```


### 评论 8

**排查动作**: 添加附件截图

**排查结果**: 已添加附件2250588


### 评论 9

**排查动作**: 确认对手件响应状态

**排查结果**: 对手件不响应VCU请求


### 评论 10

**排查动作**: 复测557 BDF V16.0断点

**排查结果**: 确认与CR 1113095相同问题

