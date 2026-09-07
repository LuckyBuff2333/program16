# VCU-207543 评论分析总结

## 排查结论

SOME/IP链路正常，但ServiceBus返回FAILED_PRECONDITION，灯光控制失败已定位至迎宾SWC仲裁逻辑问题，修复已合入。


**排查摘要**：SOME/IP链路正常，但ServiceBus返回FAILED_PRECONDITION


## 排查过程分析

### 问题现象
实车近光灯/远光灯控制请求失败，SOME/IP 链路已调通但 ServiceBus 返回 FAILED_PRECONDITION，灯光未实际执行控制。

### 排查过程
| 步骤 | 排查动作 | 结果 | 关键证据 |
|------|----------|------|----------|
| 1 | 上传实车日志与视频 | 提供复现材料 | 附件 KHCI5580.MP4、gmlogger 压缩包 |
| 2 | 分析 SOME/IP 未调通日志 | serverAvailable=false，请求失败 | 15:39:36.764 getIsReady: true serverAv... |
| 3 | 上传 gmlogger/someip/spy3 日志 | 提供完整链路日志 | 附件 2089802/2089803/2089804 |
| 4 | 分析 SOME/IP 链路日志 | 链路正常，需上层分析 | someip.log 无异常 |
| 5 | 要求补充测试时间 | 等待补充信息 | 评论时间 13:29 |
| 6 | 分析 SOME/IP 回调延迟 | 关闭请求无回调，延迟 3 秒 | Line 44133: 13:29:08.515 processRequest；Line 58758: 13:29:13.8 |
| 7 | 指派 VXM 排查信号异常 | 待 VXM 分析近远光灯信号 | 评论 10 |
| 8 | 分析灯光信号下发逻辑 | 需迎宾 SWC 仲裁后发送 | 评论 11 |
| 9 | 梳理 VCU 与迎宾逻辑 | 明确信号处理优先级规则 | 评论 12 |
| 10 | 修复合入 | 已修复并合入 | 评论 13 |

### 排查结论
- **已确认的事实**：SOME/IP 链路本身正常（someip.log 无异常）；ServiceBus 返回 FAILED_PRECONDITION（15:39:36.764 Status{code=FAILED_PRECONDITION}）；近光灯请求在 13:29:08.515 发出后延迟 3 秒无回调（Line 44133/58758）；最终已修复合入（评论 13）。
- **尚未确认需进一步排查的方向**：ServiceBus 前置条件检查的具体失败条件（28 秒窗口日志缺失）；迎宾 SWC 仲裁逻辑与 VCU 优先级规则的实际执行路径；VXM 对近远光灯 SOME/IP 信号的最终分析结论。
- **与 AI 日志分析结论的一致点**：均确认 ServiceBus 前置条件失败是根因，且 SOME/IP 层返回 code0/OK 但灯光未执行。
- **与 AI 日志分析结论的差异点**：AI 分析指出 28 秒检查窗口日志缺失，而人工排查通过回调延迟 3 秒定位到具体请求行；AI 排除 GMVHAL 帧错误关联，人工排查未涉及该点，但最终通过迎宾 SWC 仲裁逻辑修复，与 AI 的“前置条件未满足”结论在根因层面一致。


## 时序排查详情

### AI日志分析

- ServiceBus 前置条件检查失败：SomeIP 层返回 code0/OK 后，ServiceBus 在约 28 秒后返回 FAILED_PRECONDITION，表明灯光控制的前置条件未满足（13:27:46.403，ServiceBus）
- 近光灯控制未执行：SetLowBeamLamp 返回 code0 但实际未控制灯光，与远光灯表现一致，指向同一前置条件根因（13:29:13.807，近光灯 comm）
- 28 秒检查窗口日志缺失：13:27:18.878 到 13:27:46.403 之间的前置条件检查逻辑日志未获取到，无法确认具体是哪个条件不满足（13:27:18~13:27:46，ServiceBus）
- GMVHAL 帧错误与灯光控制无关：Invalid Frame Received 错误发生在 13:31:23，与灯光控制时段不重叠，排除直接关联（13:31:23.019，GMVHAL）

### 评论 1

**排查动作**: 上传实车日志附件

**排查结果**: 提供复现日志与视频


### 评论 2

**排查动作**: 分析someip未调通日志

**排查结果**: serverAvailable为false，请求失败


**日志证据**:

```
06-11 15:39:36.764  6828 11888 I LightingSomeIpClient: generateSendStatus: getIsReady: true serverAvailable: false
06-11 15:39:36.764  6828 11888 I ClsLinkRequestListener:  Status: Status{code=FAILED_PRECONDITION, message='')
06-11 15:41:09.915  6828 11888 I LightingSomeIpClient: generateSendStatus: getIsReady: true serverAvailable: false
06-11 15:41:09.915  6828 11888 I ClsLinkRequestListener:  Status: Status{code=FAILED_PRECONDITION, message='')
```


### 评论 3

**排查动作**: 上传实车视频附件

**排查结果**: 已添加KHCI5580.MP4视频


**日志证据**:

```
附件 2067766 (KHCI5580.MP4)
```


### 评论 4

**排查动作**: 上传日志附件

**排查结果**: 已添加日志压缩包


**日志证据**:

```
附件 2067767 (gmlogger_2025_6_22_15_24_29.zip.002)
```


### 评论 5

**排查动作**: 上传复现日志与截图

**排查结果**: 已提供gmlogger、someip、spy3日志及截图


**日志证据**:

```
附件 2089802 (gmlogger.zip)
附件 2089803 (someip.log)
附件 2089804 (spy3.zip)
附件 2089805 (9a51e69c40ed086232158af8e8afc92.png)
```


### 评论 6

**排查动作**: 分析someip链路日志

**排查结果**: someip链路正常，需上层分析


**日志证据**:

```
2089803 (someip.log)
```


### 评论 7

**排查动作**: 要求补充测试时间

**排查结果**: 等待补充信息


### 评论 8

**排查动作**: 评论时间记录

**排查结果**: 记录评论时间13:29


### 评论 9

**排查动作**: 分析SOME/IP回调延迟

**排查结果**: 关闭请求无回调，延迟3秒才回复


**日志证据**:

```
Line 44133: 07-01 13:29:08.515  6064 31873 I LowBeamLampSomeIpRequestProcessor: processRequest: process lighting request ---请求
Line 44137: 07-01 13:29:08.516  6064 31873 I LowBeamLampSomeIpRequestProcessor: commandValue: 1
Line 58758: 07-01 13:29:13.8
```


### 评论 10

**排查动作**: 指派VXM排查信号异常

**排查结果**: 待VXM分析近远光灯SOMEIP信号


### 评论 11

**排查动作**: 分析灯光信号下发逻辑

**排查结果**: 需迎宾SWC仲裁后发送


### 评论 12

**排查动作**: 梳理VCU与迎宾逻辑

**排查结果**: 明确信号处理优先级规则


### 评论 13

**排查动作**: 修复合入

**排查结果**: 已修复并合入

