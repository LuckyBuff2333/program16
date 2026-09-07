# VCU-242699 评论分析总结

## 排查结论

远控闪灯鸣笛异常已定位至coreservice发送异常topic，指令下发正常但鸣笛仅响一声，问题原因待网关及CAN日志进一步确认。


**排查摘要**：远控闪灯鸣笛异常已定位至coreservice发送异常topic，指令下发正常但鸣笛仅响一声


## 排查过程分析

### 问题现象
远控闪灯鸣笛功能异常：APP下发指令后，车端鸣笛仅响一声，后续重复操作只闪灯不鸣笛（VIN:LSGCF8NT4SS106766，2025/11/25 15:26）。

### 排查过程
| 步骤 | 排查动作 | 结果 | 关键证据 |
|------|----------|------|----------|
| 1 | 复测远控闪灯鸣笛功能 | 鸣笛只响一声，后续仅闪灯 | 15:26 APP发送闪灯鸣笛，鸣笛只响一声 |
| 2 | 上传四部分日志压缩包 | 已添加日志附件，待分析 | 日志附件已上传 |
| 3 | 上传实车故障视频 | 提供车端只闪灯不鸣笛证据 | 附件2427631 (闪灯鸣笛指令-车端只闪灯不鸣笛.mp4) |
| 4 | 分析闪灯鸣笛日志 | 指令下发成功，信号正常 | 15:26:53.369 processRequest；15:26:53.727 executeActivateHornReque；15:26:53.728 executeSetCLEATurnLampRe |
| 5 | 转发someip分析问题 | coreservice发送异常topic待分析 | 15:26:53.707 too many sequences, count=1；15:26:53.711 setAttribute si=65537 |
| 6 | 请求网关和对手件分析 | 待分析，问题原因未明 | 15:26:53.711 setAttribute si=65537 topic=14073791 |
| 7 | 要求提供CANlog及TCPDUMP | 等待补充日志数据 | 待补充 |

### 排查结论
- **已确认的事实**：APP指令在15:26:53.369成功下发（processRequest日志）；车端在15:26:53.727执行了鸣笛请求（executeActivateHornReque），但ActivateHornRequestProcessor在15:26:53.707报"too many sequences, count=1"；someip层在15:26:53.711设置topic=65537时出现异常。
- **尚未确认需进一步排查的方向**：someip topic=65537发送异常的具体原因；车端ECU是否实际收到鸣笛指令及执行情况；需CANlog及TCPDUMP数据确认网关转发和ECU响应链路。
- **与AI日志分析结论的一致点**：均确认指令在应用层下发成功，但车端鸣笛执行链路存在异常（AI指出HornStatus序列号始终为0，与"too many sequences"日志吻合）。
- **与AI日志分析结论的差异点**：AI认为存在Poll time out超时7303ms导致指令失败（15:27:41），但人工日志分析显示问题发生在15:26:53.7xx，时间差约48秒，且人工分析未发现明确的超时失败记录，需进一步核实时间线。


## 时序排查详情

### AI日志分析

- Critical — Poll time out 导致指令失败：RemoteExecuteAlertCommandRequestProcessor 轮询等待 ECU 响应超时 7303ms，直接导致 FLASH_LIGHTS_AND_HONK_HORN 指令被判定为 failure（15:27:41.578，RemoteExecuteAlertCommandRequestProcessor）
- Critical — HornStatus 序列号始终为 0：指令处理期间 HornStatus.current_sequence 始终为 0、remaining_cycles=0，表明 ECU 侧鸣笛序列可能从未启动（15:27:40.576，RemoteExecuteAlertCommandRequestProcessor）
- Important — 失败后链路未恢复：指令失败后 TopicManager 取消订阅、ServiceBus 禁用 lamp 主题分发，但无任何证据表明后续指令处理前这些状态被复位或恢复（15:27:41.578~579，TopicManager/ServiceBus）
- Important — ActivateHornRequestProcessor 链路证据缺失：日志中未找到 ActivateHornRequestProcessor 实际下发鸣笛指令到 ECU 的完整链路，无法确认 ECU 是否收到并执行了鸣笛指令
- Info — DefaultCache 缓存更新异常：15:27:40.574 和 15:27:41.575 分别对 VEHICLE_ClmtCtrlCabinTemp 和 IMUVertAccPriAval 执行 putOrUpdate 返回"缓存更新失败"，但未发现与 Horn 相关的缓存拦截证据，已排除缓存拦截假设
- Info — 问题时间与日志时间差：Bug 描述的问题时间为 15:26:53，但日志中首次失败时间为 15:27:41.578，两者相差约 48 秒，原因未明

### 评论 1

**排查动作**: 复测远控闪灯鸣笛功能

**排查结果**: 鸣笛只响一声，后续仅闪灯不鸣笛


**日志证据**:

```
VIN:LSGCF8NT4SS106766
2025/11/25 15：26分 APP发送远控指令：闪灯鸣笛；鸣笛只响了一声，后续再发送闪灯鸣笛操作，车端只闪灯不鸣笛
```


### 评论 2

**排查动作**: 上传四部分日志压缩包

**排查结果**: 已添加日志附件，待分析


### 评论 3

**排查动作**: 上传实车故障视频

**排查结果**: 提供车端只闪灯不鸣笛证据


**日志证据**:

```
附件 2427631 (闪灯鸣笛指令-车端只闪灯不鸣笛.mp4)
```


### 评论 4

**排查动作**: 分析闪灯鸣笛日志

**排查结果**: 指令下发成功，信号正常


**日志证据**:

```
11-25 15:26:53.369  4056 24502 I RemoteExecuteAlertCommandRequestProcessor: processRequest: req = message_id: "flash honk req"
11-25 15:26:53.727  4056  4168 I RemoteExecuteAlertCommandRequestProcessor: executeActivateHornRequestCommand: code = OK
11-25 15:26:53.728  4056  4172 I RemoteExecuteAlertCommandRequestProcessor: executeSetCLEATurnLampRequestCommand: code = OK
11-25 15:26:54.729  4056  1695 I RemoteExecuteAlertCommandRequestProcessor: FLASH_LIGHTS_AND_HONK_HORN mIsLampOpened = truemIsHornOpened: true
11-25 15:26:54.729  4056  1695 D RemoteExecuteAlertCommandRequestProcessor: failureDetails: set VehicleAlertRequest success overallStatus: success subCategory: OK
```


### 评论 5

**排查动作**: 转发someip分析问题

**排查结果**: coreservice发送异常topic待分析


**日志证据**:

```
行 46735: 11-25 15:26:53.707  4495  6166 I ActivateHornRequestProcessor: too many sequences, count=1
行 46737: 11-25 15:26:53.707  4495  6166 I ActivateHornRequestProcessor: setting builder parameters: cycleCount=3, onTime=20, offTime=980
11-25 15:26:53.711  1584  1592 D ts::someip::plugin:  [setAttribute:156] si = 65537 topic = 1407379178586588
```


### 评论 6

**排查动作**: 请求网关和对手件分析

**排查结果**: 待分析，问题原因未明


**日志证据**:

```
11-25 15:26:53.711  1584  1592 D ts::someip::plugin:  [setAttribute:156] si = 65537 topic = 1407379178586588
```


### 评论 7

**排查动作**: 要求提供CANlog及TCPDUMP

**排查结果**: 等待补充日志数据

