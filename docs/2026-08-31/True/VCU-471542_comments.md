# VCU-471542 评论分析总结

## 排查结论

香氛浓度调节异常已定位为SOME/IP订阅成功但未收到2533279085461684 topic数据，网关转发与CAN一致，问题待香氛专家进一步排查。


**排查摘要**：香氛浓度调节异常已定位为SOME/IP订阅成功但未收到2533279085461684 topic数据


## 排查过程分析

### 问题现象
香氛浓度调节功能异常，远控下发请求后香氛浓度无响应，需排查 SOME/IP 订阅与数据链路。

### 排查过程
| 步骤 | 排查动作 | 结果 | 关键证据 |
|------|----------|------|----------|
| 1 | 上传实车日志与截图 | 已提供复现附件 | 附件 2692039 (1653 4-16-2026 4-53-48 pm.vsb) |
| 2 | 分析日志缺失 topic | 未收到 2533279085461684 topic | 04-16 16:53:31.007 CLEAFragranceDiffuserRequestProcessor: processRequest: finish Enabl |
| 3 | 订阅下发请求分析 | 订阅成功但未收到数据 | Event: 0x80b4 is Subscribed |
| 4 | 网关转发状态一致性确认 | 转发与 CAN 一致，转交香氛专家 | 评论4 结论 |
| 5 | 询问问题工况和香氛棒状态 | 等待补充信息 | 评论5 提问 |
| 6 | 确认是否拔出过 | 未拔出过 | 评论6 回复 |
| 7 | 上传实车故障视频 | 已添加附件 mp4 视频 | 附件 2697636 (e52e457733d1d0c887a674a7960bdc99.mp4) |
| 8 | 远控换香问题确认 | 待判断是否为新问题 | 评论8 结论 |
| 9 | 添加 HVAC 分析附件 | 已上传分析图片 | 评论9 附件 |
| 10 | 梳理 3d8 请求信号清单 | 仅需两条浓度信号，其余禁止发送 | HVAC Infotainment Controls Request Fragrance Diffuser Information |
| 11 | 请 VCU 查看发送逻辑 | 待 VCU 排查发送逻辑 | 评论11 请求 |
| 12 | 请求底层分析 coreservice 发送 someip topic | 待底层排查 | 评论12 请求 |
| 13 | 确认 someip 调查范围 | 下发已成功，需明确新调查点 | topic = 1407379178586223 的下发，c |

### 排查结论
- **已确认的事实**：SOME/IP 订阅成功（Event: 0x80b4 is Subscribed）；CoreService 进程内存在香氛处理模块（PID 4890 含 CLEAFragranceDiffuserRequestProcessor）；3d8 请求仅需两条浓度信号，其余禁止发送。
- **尚未确认需进一步排查的方向**：VCU 发送逻辑是否异常；底层 coreservice 发送 someip topic 的具体行为；topic 2533279085461684 未收到的根因。
- **与 AI 日志分析结论的一致点和差异点**：一致点——均确认 CoreService 进程内存在香氛处理链路，且日志时间范围覆盖 Bug 时刻。差异点——AI 分析指出 SomeIpTopicReceiverManager 频繁报错 `not found receiver by topic`，但未确认与香氛浓度相关；人工排查已确认订阅成功但未收到数据，需进一步定位 topic 未到达


## 时序排查详情

### AI日志分析

- CoreService 进程内存在香氛处理模块：PID 4890 包含 CLEAFragranceDiffuserRequestProcessor、CabinClimateSomeIpClient、CabinClimateTopicMappingFactory 等 TAG，说明香氛处理链路在 CoreService 进程内存在。
- SomeIpTopicReceiverManager 频繁报错：日志概览错误采样中频繁出现 `not found receiver by topic` 错误，但未确认这些 topic 是否与香氛浓度相关。
- 日志时间范围覆盖 Bug 时刻：日志时间范围（04-16 16:49:41 ~ 16:56:33）与 Bug 时间（16:53:31）存在重叠，但无法确认具体时间点的日志内容。

### 评论 1

**排查动作**: 上传实车日志与截图

**排查结果**: 已提供复现附件供分析


**日志证据**:

```
附件 2692039 (1653 4-16-2026 4-53-48 pm.vsb)
附件 2692040 (c6758637ab78eb1927d78d5dd1120df6.png)
附件 2692051 (gmlogger_2026_4_16_16_56_25.z01)
附件 2692058 (gmlogger_2026_4_16_16_56_25.zip)
附件 2692059 (someip.log)
```


### 评论 2

**排查动作**: 分析日志缺失topic

**排查结果**: 未收到2533279085461684 topic


**日志证据**:

```
04-16 16:53:31.007  4890  6901 I CLEAFragranceDiffuserRequestProcessor: processRequest: finish EnableValue： 2
04-16 16:53:31.007  4890  6901 I CLEAFragranceDiffuserRequestProcessor: processRequest: finish CartridgeSettingValue： 2
04-16 16:53:31.007  4890  6901 I CLEAFragranceDiffuserRequestProcessor: processRequest: finish ScentIntensity： 45
04-16 16:53:31.008  1557  1584 D ts::someip::plugin:  [setAttribute:160] si = 65537 topic = 1407379178586223
```


### 评论 3

**排查动作**: 订阅下发请求分析

**排查结果**: 订阅成功但未收到数据


**日志证据**:

```
[2026-04-16 16:47:51.297] Service: 0x0001, Instance: 0x0001, Event: 0x80b4 is Subscribed
04-16 16:53:31.008  1557  1584 D someip::vendor.ts.someip@1.0-service: setAttribute: enter. hdl(2).
04-16 16:53:31.008  1557  1584 D ts::someip::plugin:  [setAttribute:160] si = 65537 topic = 1407379178586223
04-16 16:53:31.008  1557  1584 D someip::vendor.ts.someip@1.0-service: setAttribute quit rc = 0
```


### 评论 4

**排查动作**: 网关转发状态一致性确认

**排查结果**: 转发与CAN一致，转交香氛专家


### 评论 5

**排查动作**: 询问问题工况和香氛棒状态

**排查结果**: 等待补充信息


### 评论 6

**排查动作**: 确认是否拔出过

**排查结果**: 未拔出过


### 评论 7

**排查动作**: 上传实车故障视频

**排查结果**: 已添加附件mp4视频


**日志证据**:

```
附件 2697636 (e52e457733d1d0c887a674a7960bdc99.mp4)
```


### 评论 8

**排查动作**: 远控换香问题确认

**排查结果**: 待判断是否为新问题


### 评论 9

**排查动作**: 添加HVAC分析附件

**排查结果**: 已上传分析图片


### 评论 10

**排查动作**: 梳理3d8请求信号清单

**排查结果**: 仅需两条浓度信号，其余两条禁止发送


**日志证据**:

```
HVAC Infotainment Controls Request Fragrance Diffuser Information : HVAC Infotainment Controls Request Fragrance Diffuser Scent Intensity Level
HVAC Infotainment Controls Request Fragrance Diffuser Information : HVAC Infotainment Controls Request Fragrance Diffuser Scent Intensity Level Active
```


### 评论 11

**排查动作**: 请VCU查看发送逻辑

**排查结果**: 待VCU排查发送逻辑


### 评论 12

**排查动作**: 请求底层分析coreservice发送someip topic

**排查结果**: 待底层排查


### 评论 13

**排查动作**: 确认someip调查范围

**排查结果**: 下发已成功，需明确新调查点


**日志证据**:

```
topic = 1407379178586223的下发，comment 3 已经显示成功下发了
```


### 评论 14

**排查动作**: (Comment from 唐

**排查结果**: (Comment from 唐振富)
调

