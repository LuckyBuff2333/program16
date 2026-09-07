# VCU-230196 评论分析总结

## 排查结论

已定位VCU注入Key与整车不一致，且未发送0x16C基础周期报文，疑与SOMEIP相关，问题定位为测试环境配置异常。


## 排查过程分析

### 问题现象
车辆远程控制功能异常，云端下发闪灯鸣笛、解闭锁、车窗控制等指令后，车端执行失败或执行错误指令，且VCU未发送基础周期报文，伴随DTC报码。

### 排查过程
| 步骤 | 排查动作 | 结果 | 关键证据 |
|------|----------|------|----------|
| 1 | 上传实车复测日志附件 | 已提供视频、日志、抓包等证据 | 评论1附件 |
| 2 | 添加云端收到信息截图 | 已添加附件，待进一步分析 | 附件2197647 (云端收到信息.png) |
| 3 | 检查DTC Key一致性 | VCU Key与整车不一致 | 评论3结论 |
| 4 | 添加附件说明VCU Key不一致 | VCU注的Key与整车不一致 | 附件2197947 (VCU注的Key和整车不一致.png) |
| 5 | 指派someip开发分析 | 待app分析后接力 | 评论5指派记录 |
| 6 | 查看comments3测试环境 | 确认为测试环境问题 | 评论6结论 |
| 7 | 请求紫阳工协助排查 | 等待进一步分析 | 评论7指派记录 |
| 8 | 分析总线日志与视频时间差 | 视频与日志时间不匹配，VCU未发0x16C报文 | 测试视频显示测试时间在21：04，但是总线log是从21：06开始的；I CAN有数据，但VCU全过程并未发出过基础的0x16C周期报文；结合紫阳回复的U1962报码 |
| 9 | 分析闪灯鸣笛报错日志 | FAILED_PRECONDITION疑与SOMEIP相关 | 152055: 08-11 20:53:24.701 RemoteExecuteAlertCommandRequestProcessor: processRequest；152676: VehicleGearState；152677: HornStatus: nu |
| 10 | 分析云端unlock请求日志 | 云端请求unlock但执行lock命令 | 135680: 08-11 20:53:20.477 action: "unlock"；139362: 08-11 20:53:20.921 executeReqRemoteLockCommand: 2 |
| 11 | 分析车窗请求日志 | 请求100但front_left状态异常 | 82923: 08-11 21:04:07.768 processRequest；82924: action: "100"；83570: reqwindow |
| 12 | 周→周紫阳评论接力 | 基于紫阳工评论9-12分析 | 评论12接力记录 |
| 13 | 接力博世分析问题 | 基于紫阳工评论9-12分析 | 评论13接力记录 |
| 14 | 分析tcpdump抓包数据 | 无sub因服务发现晚于co | 评论14结论 |

### 排查结论
- **已确认的事实**：VCU注入的Key与整车不一致（附件2197947）；测试视频时间（21:04）与总线日志时间（21:06）不匹配，且VCU全过程未发出0x16C周期报文（评论8）；云端请求unlock


## 时序排查详情

### AI日志分析

- VehicleSomeIpClient 未就绪：闪灯鸣笛指令无法通过 SomeIP 链路下发到 ECU，导致指令被拒绝（21:03:57.237，ActivateHornRequestProcessor）
- 闪灯鸣笛指令执行失败：ActivateHornRequestProcessor 输出 'failed, server is not available or client is not ready'，ClsLinkRequestEventListener: onRequest: false，确认指令被拒绝（21:03:57.237，ClsLinkRequestEventListener）
- SetUsageProfileProcessor 前置条件校验失败：电源模式非 OFF 状态导致前置条件校验失败（21:03:56.939，SetUsageProfileProcessor）
- 位置服务指令执行流程存在矛盾：21:04:33.463 就 Process Finish，但 21:04:41 又记录失败，需要进一步确认（21:04:33.463，ClsLinkRequestListener3）
- TimeResult 时间戳偏差约 500 秒：mTimeMillis: 1754916664878, AgeMillis: 500334，而 generateGMTrustedTimeMillis 返回 1754917165212，两者偏差约 500 秒（48 万毫秒），说明可信时间生成存在异常（21:03:56.939，TimeResult）
- 解闭锁指令未找到相关日志：可能使用了不同的关键词，需要搜索解闭锁相关指令

### 评论 1

**排查动作**: 上传实车复测日志附件

**排查结果**: 已提供视频、日志、抓包等证据


### 评论 2

**排查动作**: 添加云端收到信息截图

**排查结果**: 已添加附件，待进一步分析


**日志证据**:

```
附件 2197647 (云端收到信息.png)
```


### 评论 3

**排查动作**: 检查DTC Key一致性

**排查结果**: VCU Key与整车不一致


### 评论 4

**排查动作**: 添加附件说明VCU Key不一致

**排查结果**: VCU注的Key与整车不一致


**日志证据**:

```
附件 2197947 (VCU注的Key和整车不一致.png)
```


### 评论 5

**排查动作**: 指派someip开发分析

**排查结果**: 待app分析后接力


### 评论 6

**排查动作**: 查看comments3测试环境

**排查结果**: 确认为测试环境问题


### 评论 7

**排查动作**: 请求紫阳工协助排查

**排查结果**: 等待进一步分析


### 评论 8

**排查动作**: 分析总线日志与视频时间差

**排查结果**: 视频与日志时间不匹配，VCU未发0x16C报文


**日志证据**:

```
测试视频显示测试时间在21：04，但是总线log是从21：06开始的
I CAN有数据，但是VCU全过程并未发出过基础的0x16C周期报文
结合紫阳回复的U1962报码
```


### 评论 9

**排查动作**: 分析闪灯鸣笛报错日志

**排查结果**: FAILED_PRECONDITION疑与SOMEIP相关


**日志证据**:

```
152055: 08-11 20:53:24.701  5233  8740 I RemoteExecuteAlertCommandRequestProcessor: processRequest: req = message_id: "flash honk req"
152676: 08-11 20:53:24.968  5233  5233 D RemoteExecuteAlertCommandRequestProcessor: VehicleGearState: selected_gear: S_PARK
152677: 08-11 20:53:24.968  5233  5233 D RemoteExecuteAlertCommandRequestProcessor: , HornStatus: null, LeftLamp: null, RightLamp: null
```


### 评论 10

**排查动作**: 分析云端unlock请求日志

**排查结果**: 云端请求unlock但执行lock命令


**日志证据**:

```
135680: 08-11 20:53:20.477  5233  8652 I RemoteExecuteDoorCommandRequestProcessor: action: "unlock"
139362: 08-11 20:53:20.921  4338  5440 I DoorRequestProcessor: executeReqRemoteLockCommand: 2
```


### 评论 11

**排查动作**: 分析车窗请求日志

**排查结果**: 请求100但front_left状态异常


**日志证据**:

```
82923: 08-11 21:04:07.768  5233  8740 I RemoteExecuteWindowCommandRequestProcessor: processRequest: req = message_id: "WindowRequest"
82924: 08-11 21:04:07.768  5233  8740 I RemoteExecuteWindowCommandRequestProcessor: action: "100"
83570: 08-11 21:04:08.085  4338  5440 I WindowRequestProcessor: reqwindow {
83571: 08-11 21:04:08.085  4338  5440 I WindowRequestProcessor:   name: "front_left"
83572: 08-11 21:04:08.085  4338  5440 I WindowRequestProcessor:   position: 100
```


### 评论 12

**排查动作**: (Comment from 周

**排查结果**: (Comment from 周紫阳)
位


### 评论 13

**排查动作**: 接力博世分析问题

**排查结果**: 基于紫阳工评论9-12分析


### 评论 14

**排查动作**: 分析tcpdump抓包数据

**排查结果**: 无sub因服务发现晚于coreservice


**日志证据**:

```
2197639 (21.pcap)
当前只有offer报文，没有sub
```


### 评论 15

**排查动作**: 代码修改上传

**排查结果**: 已修改并上传代码


### 评论 16

**排查动作**: 请求在NS33.5版本验证

**排查结果**: 待验证，无结论


### 评论 17

**排查动作**: 上传VCU远控测试附件

**排查结果**: 提供测试视频、日志及抓包文件


### 评论 18

**排查动作**: 实车复测验证问题

**排查结果**: 问题未解决，需进一步分析


**日志证据**:

```
VCU版本：LOCAL8155-R2-A-UQB26C-20250813-118
测试时间：8-13 20:33-20:37
```


### 评论 19

**排查动作**: 分析最新测试日志

**排查结果**: 仍无sub数据，问题依旧


**日志证据**:

```
目前还是只有offer，没有sub数据
```


### 评论 20

**排查动作**: 沟通确认VCU件问题

**排查结果**: 更换样件后someip链路正常


### 评论 21

**排查动作**: 更换VCU硬件后实车验证

**排查结果**: 验证通过


### 评论 22

**排查动作**: 上传热车车控视频

**排查结果**: 提供实车复测证据


**日志证据**:

```
附件 2211455 (热车-车控.mp4)
```

