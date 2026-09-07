# VCU-418020 评论分析总结

## 排查结论

远控关窗偶发卡在2%未至0，已定位为总线电压低致车窗停止，待PLM确认12V概率影响。


## 排查过程分析

### 问题现象
实车复测中，远控关闭右后车窗时，车窗从82%降至2%后停止，未完全关闭至0%，云端轮询超时后报错，问题偶发未稳定复现。

### 排查过程
| 步骤 | 排查动作 | 结果 | 关键证据 |
|------|----------|------|----------|
| 1 | 上传实车复测日志及视频 | 提供冷车失败视频及多类日志 | gmlogger_2026_1_21_17_37_40.part01.rar |
| 2 | 实车复测1/21版本 | 问题未复现，需观察 | 评论2：问题未复现 |
| 3 | 分析车窗状态校验日志 | 右后车窗位置异常，设置失败 | 42998: set window fail |
| 4 | 下发远控关闭右后车窗 | 收到PS_POSITION_A，非关闭成功 | windowTopic_rear_right_positionStatus: PS_POSITI |
| 5 | 上传崩溃截图附件 | 已上传现场截图 | 评论5：已上传截图 |
| 6 | VCU下发关窗请求复测 | 右后窗只关到2%，未到0 | 评论6：只关到2% |
| 7 | 询问BDF版本及NC/ND车型 | 待确认车辆软件版本和车型 | 评论7：待确认 |
| 8 | 修正标题并确认车辆版本 | 车辆为NCUB-MY26，BDF版本VC11 | 评论8：NCUB-MY26，VC11 |
| 9 | 添加车窗状态截图附件 | 已上传车窗状态图片 | 评论9：已上传图片 |
| 10 | 总线电压信号分析 | 电压低导致车窗停止工作 | 总线信号看电压低12v，到bdf端可能小于11v |
| 11 | 确认设计及生产影响 | 待PLM同意，需确认12V概率 | 评论11：待PLM同意 |
| 12 | 反馈BDF优化车窗算法 | FO和PLM不接受12V风险 | 评论12：需按SSTS优化 |
| 13 | 优化算法适配电池波动 | 算法已优化，适配NCUB车 | 评论13：算法已优化 |
| 14 | 询问修复模块 | 待确认修复模块 | 评论14：待确认 |
| 15 | 计划VC11.4修复 | 计划在VC11.4版本修复 | 评论15：VC11.4修复 |
| 16 | BDF模块更新算法 | 增加低于11v判断时间 | 评论16：增加低于11v判断时间 |
| 17 | 请求修复后转交复测 | 等待修复后复测 | 评论17：等待复测 |
| 18 | 判定非VCU问题并关闭 | BDF问题不在此域跟踪 | 评论18：BDF问题不在此域跟踪 |

### 排查结论
- **已确认的事实**：右后车窗从82%降至2%后停止，未到0%（日志：windowTopic_rear_right_Position: 98→2


## 时序排查详情

### AI日志分析

- 右后车窗停在 2% 未完全关闭：右后车窗从 82% 降至 2% 后停止，未继续到 0%，位置状态为 PS_POSITION_A（2%），未达到请求的完全关闭（0%）（17:31:58.100，RemoteExecuteWindowCommandRequestProcessor）
- 轮询超时 16701ms 后返回失败：RemoteExecuteWindowCommandRequestProcessor 在 17:32:09.113 报 poll time out!，失败详情为 coreService:REAR_RIGHT_WINDOW PS_POSITION_A != request:0，即右后车窗最终停在 PS_POSITION_A（未完全关闭，位置 2%），未达到请求的完全关闭（0%），轮询超时 16701ms 后返回失败，云端报错码 2B017（17:32:09.113，RemoteExecuteWindowCommandRequestProcessor）
- 右后车窗从 82% 降至 2% 后停止，未继续到 0%，疑似卡滞或控制逻辑提前停止：已搜索 anti-pinch、防夹、block、prevent、obstacle、夹等关键词，无匹配结果，排除防夹事件（17:31:55.094，GMVHAL）
- SomeIP 通信正常（NOTIFY_WINDOW_STATUS_MESSAGE SUCCESS），失败原因是位置状态不满足，而非通信超时（17:31:54.500，GMVHAL）
- 第二次车窗关闭指令成功：右后车窗同样先报 window.getPosition():2 和 set window fail，但随后位置变为 0，set window command success poll count，耗时约 1680ms 成功（17:32:40，RemoteExecuteWindowCommandRequestProcessor）

### 评论 1

**排查动作**: 上传实车复测日志附件

**排查结果**: 提供冷车车窗失败视频及多类日志


**日志证据**:

```
gmlogger_2026_1_21_17_37_40.part01.rar
rec_6377683_default_2026-01-21-17_24_57_2.rbf.gz
TBoxLog_VIN123456_20260121_173913
冷车-车窗失败-1731.mp4
```


### 评论 2

**排查动作**: 实车复测1/21版本

**排查结果**: 问题未复现，需进一步观察


### 评论 3

**排查动作**: 分析车窗状态校验日志

**排查结果**: 右后车窗位置异常，设置失败


**日志证据**:

```
42996: 01-21 17:32:09.113  3992 32182 I RemoteExecuteWindowCommandRequestProcessor: windowName:rear_right-requestWindowAction:0-window.getPosition():2
42997: 01-21 17:32:09.113  3992 32182 I RemoteExecuteWindowCommandRequestProcessor: requestWindowAction: 0-PositionStatus:PS_POSITION_A
42998: 01-21 17:32:09.113  3992 32182 I RemoteExecuteWindowCommandRequestProcessor: set window fail REAR_RIGHT_WINDOW,
```


### 评论 4

**排查动作**: 下发远控关闭右后车窗

**排查结果**: 收到PS_POSITION_A，非关闭成功状态


**日志证据**:

```
01-21 17:31:52.990  4597 25374 I WindowRequestProcessor: windowPosition Req: rear_right  Value:0
01-21 17:32:33.866  4597  4630 I WindowTopicMapper: windowTopic_rear_right_positionStatus: PS_POSITION_A
01-21 17:31:53.218  4597  5129 I WindowTopicMapper: windowTopic_rear_right_Position: 98
01-21 17:31:53.218  4597  5129 I WindowTopicMapper: windowTopic_rear_right_motionStatus: MS_CLOSING
01-21 17:31:53.218  4597  5129 I WindowTopicMapper: windowTopic_rear_right_positionStatus: PS_OPEN_MORE_THEN_C
```


### 评论 5

**排查动作**: 添加崩溃截图附件

**排查结果**: 已上传现场截图


### 评论 6

**排查动作**: VCU下发关窗请求复测

**排查结果**: 右后窗只关到2%，未到0


### 评论 7

**排查动作**: 询问BDF版本及NC/ND车型

**排查结果**: 待确认车辆软件版本和车型


### 评论 8

**排查动作**: 修正标题并确认车辆版本

**排查结果**: 车辆为NCUB-MY26，BDF版本VC11


### 评论 9

**排查动作**: 添加车窗状态截图附件

**排查结果**: 已上传车窗状态图片


### 评论 10

**排查动作**: 总线电压信号分析

**排查结果**: 电压低导致车窗停止工作


**日志证据**:

```
从总线信号看电压低12v，到bdf 端可能已经小于11v
```


### 评论 11

**排查动作**: 确认设计及生产影响

**排查结果**: 待PLM同意，需确认12V概率


### 评论 12

**排查动作**: 反馈BDF优化车窗算法

**排查结果**: FO和PLM不接受12V风险，需按SSTS优化


### 评论 13

**排查动作**: 优化算法适配电池波动

**排查结果**: 算法已优化，适配NCUB车


### 评论 14

**排查动作**: 询问修复模块

**排查结果**: 待确认修复模块


### 评论 15

**排查动作**: 计划VC11.4修复

**排查结果**: 计划在VC11.4版本修复


### 评论 16

**排查动作**: BDF模块更新算法

**排查结果**: 增加低于11v判断时间


### 评论 17

**排查动作**: 请求修复后转交复测

**排查结果**: 等待修复后复测


### 评论 18

**排查动作**: 判定非VCU问题并关闭

**排查结果**: BDF问题不在此域跟踪

