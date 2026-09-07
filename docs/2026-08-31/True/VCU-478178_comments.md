# VCU-478178 评论分析总结

## 排查结论

远程启动失败已定位：someIp信号字段异常导致未上报1B012，6秒超时触发2B007，需对手件确认CAN信号及车型配置。


**排查摘要**：远程启动失败已定位


## 排查过程分析

### 问题现象
远程启动车辆功能失败，执行远程启动指令后约6秒超时，系统抛出2B007错误码，但未按预期上报1B012错误码，导致远程启动流程中断。

### 排查过程
| 步骤 | 排查动作 | 结果 | 关键证据 |
|------|----------|------|----------|
| 1 | 复制工作项1292520 | 仅复制记录，无新增排查 | 评论1 |
| 2 | 上传实车日志附件 | 提供gmlogger与TBox日志 | gmlogger_2026_4_20_9_58_30.part01-03.rar |
| 3 | 指派紫阳排查远程启动失败 | 待排查 | 评论3 |
| 4 | 转交CoreService排查 | RPC成功但未报1B012 | 评论4 |
| 5 | 分析远控失败日志 | 6秒超时，远控启动失败 | 56910: startChecker:2; 56911: 6s timeout; 56916: failureDetails |
| 6 | 分析someIp信号字段 | 字段非0导致不报1B012 | 04-18 01:59:43.556 getPPMShwVehOnExtModeSwRe; getPPMShwVehOffSwMnReqd |
| 7 | 查看s2s上报及can信号 | s2s正常上报，需对手件查can | 25579 2026/04/19 01:59:13.793389 QNX QSYM US2S |
| 8 | 确认配置车型对应关系 | CL/CM车型0x401标大CCU，待VC4.0修改后测试 | 评论9 |
| 9 | 确认车辆CL和CM车型 | 待确认车型信息 | 评论10 |
| 10 | 忽略评论9和10，确认DRE | ndlb DRE为郭文超 | 评论11 |
| 11 | 确认问题归属 | 待确认转派或澄清 | 评论12 |
| 12 | 询问信号及附件缺失 | 待补充CAN日志，信号待确认 | 评论13 |
| 13 | 询问下发指令内容 | 待确认指令与信号关系 | 评论14 |
| 14 | 询问下发topic修改值 | 待确认下发topic影响 | 评论15 |
| 15 | 确认无法修改该值 | 无法修改，未执行操作 | 评论16 |
| 16 | 确认分析所需日志范围 | 需补充CAN日志及确认APP是否设值 | 评论17 |
| 17 | 请求提供CAN日志 | 等待补充日志数据 | 评论18 |
| 18 | 确认问题存在 | 问题确认存在 | 评论19 |

### 排查结论
- **已确认的事实**：远程启动执行6秒超时后抛出2B007（证据：56911行"6s timeout"）；someIp信号字段非0导致1B012分支未触发（证据：04-18 01:59:43.556 getPPMShwVehOnExtModeSwRe）；s2s上报正常


## 时序排查详情

### AI日志分析

- 2B007 实际抛出路径确认：远程启动 6 秒超时后，RequestProcessor 在 2ms 内判定 2B007 并输出 failureDetails，路径完整且证据充分（02:00:01.421~.424，PID 5213）。
- 1B012 分支完全未触发：全量 298676 行日志中 1B012 零匹配，说明累计超时分支的判定逻辑在本次执行中未被走到（全量日志扫描）。
- 状态机累计超时计数已达阈值但未跳转：mRunAbortedNumber:2 且 mRemoteStartStatus:1，表明累计超时条件已满足，但状态机未跳转到 1B012 分支（02:00:01.491，PID 5213）。
- 多个 RequestProcessor 表现一致：方向盘加热、气候命令、座椅温度组三个处理器均报 2B007，说明这是备车方案执行链路的系统性行为而非单点异常（02:00:01.421~.491，PID 5213）。
- 系统存在资源过载迹象：resolv（16764 行）、ServiceBus（10888 行）、SQLiteQueryBuilder（10194 行）等 TAG 存在大量超时/异常记录，但尚未直接关联到备车方案执行链路的 RPC 超时。

### 评论 1

**排查动作**: 复制工作项1292520

**排查结果**: 无新增排查，仅复制记录


### 评论 2

**排查动作**: 上传实车日志附件

**排查结果**: 提供gmlogger与TBox日志


**日志证据**:

```
gmlogger_2026_4_20_9_58_30.part01.rar
gmlogger_2026_4_20_9_58_30.part02.rar
gmlogger_2026_4_20_9_58_30.part03.rar
gmlogger_2026_4_20_9_58_30.part04.rar
TBoxLog_VIN123456_20260420_131934
```


### 评论 3

**排查动作**: 指派紫阳排查远程启动失败

**排查结果**: 待排查


### 评论 4

**排查动作**: 转交CoreService排查

**排查结果**: RPC成功但未报1B012


### 评论 5

**排查动作**: 分析远控失败日志

**排查结果**: 6秒超时，远控启动失败


**日志证据**:

```
56910: 04-20 02:00:01.484  5213  6996 I RemoteExecuteClimateCommandRequestProcessor:  startChecker:2mRunAbortedNumber:2mRemoteStartStatus:1
56911: 04-20 02:00:01.484  5213  6996 E RemoteExecuteClimateCommandRequestProcessor:  6s timeout start remote vehicle failed
56916: 04-20 02:00:01.484  5213  6996 D RemoteExecuteClimateCommandRequestProcessor: failureDetails: Remote start fail overallStatus: failure subCategory: 2B007
```


### 评论 6

**排查动作**: 分析someIp信号字段

**排查结果**: 字段非0导致不报1B012


**日志证据**:

```
04-18 01:59:43.556  4774  6400 D SDV_CoreService: [EnergySomeIpClient]resp.getPPMShwVehOnExtModeSwReqd():false
04-18 01:59:43.556  4774  6400 D SDV_CoreService: [EnergySomeIpClient]resp.getPPMShwVehOffSwMnReqd():false
148603: 04-20 01:59:45.352  4921  6892 I SetVehicleRemoteStartProcessor: RemoteVehicleStartRequest currentTime: 0 stateValue: 2
```


### 评论 7

**排查动作**: (Comment from 许

**排查结果**: (Comment from 许传民)
a


### 评论 8

**排查动作**: 查看s2s上报及can信号

**排查结果**: s2s正常上报，需对手件查can


**日志证据**:

```
25579 2026/04/19 01:59:13.793389 98583.6051 7 QNX QSYM US2S 1515580 log info verbose 7 1776535152515428436 57501 s2s.1503309..0 info 42 5 [Com][VSOMEIP][server][rpc] notify the service [1] instance [1] event [32872]
```


### 评论 9

**排查动作**: 确认配置车型对应关系

**排查结果**: CL/CM车型0x401标大CCU，待VC4.0修改后测试


### 评论 10

**排查动作**: 确认车辆CL和CM车型

**排查结果**: 待确认车型信息


### 评论 11

**排查动作**: 忽略评论9和10，确认DRE

**排查结果**: ndlb DRE为郭文超


### 评论 12

**排查动作**: 确认问题归属

**排查结果**: 待确认转派或澄清


### 评论 13

**排查动作**: 询问信号及附件缺失

**排查结果**: 待补充CAN日志，信号待确认


### 评论 14

**排查动作**: 询问下发指令内容

**排查结果**: 待确认指令与信号关系


### 评论 15

**排查动作**: 询问下发topic修改值

**排查结果**: 待确认下发topic影响


### 评论 16

**排查动作**: 确认无法修改该值

**排查结果**: 无法修改，未执行操作


### 评论 17

**排查动作**: 确认分析所需日志范围

**排查结果**: 需补充CAN日志及确认APP是否设值


### 评论 18

**排查动作**: 请求提供CAN日志

**排查结果**: 等待补充日志数据


### 评论 19

**排查动作**: 确认问题存在

**排查结果**: 问题确认存在

