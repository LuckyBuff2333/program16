# VCU-198434 评论分析总结

## 排查结论

VCU实车发送MODE101而非预期MODE56，CoreService未收到指定currentMode，问题已定位至VCU指令发送环节，待进一步确认传值。


**排查摘要**：VCU实车发送MODE101而非预期MODE56，CoreService未收到指定currentMode


## 排查过程分析

### 问题现象
手机端点击大四座模式后，VCU实际发送MODE101而非预期的MODE56，且CoreService未收到指定currentMode，导致座椅模式切换功能异常。

### 排查过程
| 步骤 | 排查动作 | 结果 | 关键证据 |
|------|----------|------|----------|
| 1 | 上传实车复测日志视频 | 已提供复现视频与日志压缩包 | 附件1957115 (e29d2b66ffb2aedd10804e8d5e647548.mp4) |
| 2 | 复制工作项1025664 | 无新排查动作，仅复制 | 评论2 |
| 3 | 分析MQTT指令推送 | 收到mqtt结果topicId | 2025-04-22 13:54:20.978 mqtt---08---startCommonCmdPush收到mqtt的结果topicId:VCVV/SDVTWIN/578404ee164e978d |
| 4 | 请求车端确认传值 | 待车端反馈传值情况 | 评论4 |
| 5 | 分析日志缺失模式 | CoreService未收到指定currentmode | 行94712: 04-22 13:57:38.211 currentMode: [0, 0, 0, 0, 0, 0, 0, 0, 0, 0] |
| 6 | 添加VCU指令错误截图 | 提供VCU端大四座指令发送错误证据 | 附件1958442 (VCU端大四座指令发送错误.PNG) |
| 7 | 实车复测大四座模式 | VCU发送MODE101非MODE56 | 手机端点击大四座，实际VCU发送MODE101非MODE56 |
| 8 | 实车确认MSM模式调用 | MSM端正常，转VCU确认 | 评论8 |
| 9 | 添加实车故障截图附件 | 已添加两张现场图片附件 | 评论11 |
| 10 | 优化弱网数据接收稳定性 | 待复测验证 | 评论12 |
| 11 | 远控功能联调检查 | 车端未集成VCU，暂不可测 | 评论13/14/15 |
| 12 | 确认接口变更及页面更新 | 问题已解决，票单关闭 | 评论16 |

### 排查结论
- **已确认的事实**：VCU端发送MODE101而非MODE56（评论7）；CoreService日志中currentMode全为0（行94712）；MQTT链路正常收到topicId（13:54:20.978日志）；MSM端调用正常（评论8）。
- **尚未确认需进一步排查的方向**：VCU端MODE101与MODE56的枚举映射关系；车端未集成VCU导致远控功能不可测（评论13-15）；弱网数据接收稳定性优化后的复测结果（评论12）。
- **与AI日志分析结论的一致点**：均确认currentMode与请求模式值不匹配，且RPC成功不代表ECU实际执行模式切换。
- **与AI日志分析结论的差异点**：


## 时序排查详情

### AI日志分析

- currentMode 数组与请求模式值系统性不匹配：四次设置请求中，三次的 currentMode 结果与请求值不一致，模式 3 从未出现在 currentMode 中（L279598, L975306, L1389689）
- supportedMode 与 currentMode 矛盾：supportedMode 声明支持模式 3，但 currentMode 从未出现模式 3，指向 ECU 侧执行异常或枚举映射不一致（L94709）
- RPC 成功 ≠ 模式生效：RPC 链路返回成功仅表示 HMI 请求 property 写入成功，不代表 ECU 实际执行了模式切换（L279044）
- 模式值映射存在偏移嫌疑：请求 val=1 时 currentMode 变为 2，请求 val=3 时 currentMode 变为 1/2，疑似存在枚举值偏移或映射错误（L975306）
- 请求到状态回传延迟稳定：三次请求到 SeatModeTopic 发布的延迟均为 ~68-69ms，说明状态回传链路本身无异常（L279598）

### 评论 1

**排查动作**: 上传实车复测日志视频

**排查结果**: 已提供复现视频与日志压缩包


**日志证据**:

```
附件 1957115 (e29d2b66ffb2aedd10804e8d5e647548.mp4)
附件 1957120 (gmlogger_2025_4_22_14_9_10.part2.rar)
附件 1957132 (gmlogger_2025_4_22_14_9_10.part1.rar)
```


### 评论 2

**排查动作**: 复制工作项1025664

**排查结果**: 无新排查动作，仅复制


### 评论 3

**排查动作**: (Comment from 顾

**排查结果**: (Comment from 顾梦玥)
手


**日志证据**:

```
2025-04-22 13:54:20.978 mqtt---08---startCommonCmdPush收到mqtt的结果topicId:VCVV/SDVTWIN/578404ee164e978df528532006f05dd4---message:{"scene":"SEAT","dataType":"SEAT_MODE","requestId":"3b8fabd0-1f3e-11f0-8951-939a07d79df3","data":{"supportedModes":[1,1,1,0,0,0,0,1,1,1,1,1,1,0,0,0,0,0,0,0,0,0,0,0,0,0,1,1,1,1,1,1,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,1,0,0,1,1,1,0,0,0,0,0,0],"availableModes":[1,1,1,0,0,0,0,1,1,1,1,1,1,0,0,0,0,0,0,0,0,0,0,0,0,0,1,1,1,0,1,1,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,1,0,0,1,1,1,0,0,0,0,0,0],"currentModes":[{"mode":1,"modeMotionStatus":0,"modeRecallStatus":0},{"mode":2,"modeMotionStatus":0,"modeRecallStatus":0},{"mode":3,"modeMotionStatus":0,"modeRecallStatus":0},{"mode":4,"modeMotionStatus":0,"modeRecallStatus":0},{"mode":5,"modeMotionStatus":0,"modeRecallStatus":0},{"mode":6,"modeMotionStatus":0,"modeRecallStatus":0},{"mode":7,"modeMotionStatus":0,"modeRecallStatus":0},{"mode":8,"modeMotionStatus":0,"modeRecallStatus":0},{"mode":9,"modeMotionStatus":0,"modeRecallStatus":0},{"mode":10,"modeMotionStatus":0,"modeRecallStatus":0},{"mode":11,"modeMotionStatus":0,"modeRecallStatus":0},{"mode":12,"modeMotionStatus":0,"modeRecallStatus":0},{"mode":13,"modeMotionStatus":0,"modeRecallStatus":0},{"mode":14,"modeMotionStatus":0,"modeRecallStatus":0},{"mode":15,"modeMotionStatus":0,"modeRecallStatus":0},{"mode":16,"modeMotionStatus":0,"modeRecallStatus":0},{"mode":17,"modeMotionStatus":0,"modeRecallStatus":0},{"mode":18,"modeMotionStatus":0,"modeRecallStatus":0},{"mode":19,"modeMotionStatus":0,"modeRecallStatus":0},{"mode":20,"modeMotionStatus":0,"modeRecallStatus":0},{"mode":21,"modeMotionStatus":0,"modeRecallStatus":0},{"mode":22,"modeMotionStatus":0,"modeRecallStatus":0},{"mode":23,"modeMotionStatus":0,"modeRecallStatus":0},{"mode":24,"modeMotionStatus":0,"modeRecallStatus":0},{"mode":25,"modeMotionStatus":0,"modeRecallStatus":0},{"mode":26,"modeMotionStatus":0,"modeRecallStatus":0},{"mode":27,"modeMotionStatus":0,"modeRecallStatus":0},{"mode":28,"modeMotionStatus":0,"modeRecallStatus":0},{"mode":29,"modeMotionStatus":0,"modeRecallStatus":0},{"mode":30,"modeMotionStatus":0,"modeRecallStatus":0},{"mode":31,"modeMotionStatus":0,"modeRecallStatus":0},{"mode":32,"modeMotionStatus":0,"modeRecallStatus":0},{"mode":33,"modeMotionStatus":0,"modeRecallStatus":0},{"mode":34,"modeMotionStatus":0,"modeRecallStatus":0},{"mode":35,"modeMotionStatus":0,"modeRecallStatus":0},{"mode":36,"modeMotionStatus":0,"modeRecallStatus":0},{"mode":37,"modeMotionStatus":0,"modeRecallStatus":0},{"mode":38,"modeMotionStatus":0,"modeRecallStatus":0},{"mode":39,"modeMotionStatus":0,"modeRecallStatus":0},{"mode":40,"modeMotionStatus":0,"modeRecallStatus":0},{"mode":41,"modeMotionStatus":0,"modeRecallStatus":0},{"mode":42,"modeMotionStatus":0,"modeRecallStatus":0},{"mode":43,"modeMotionStatus":0,"modeRecallStatus":0},{"mode":44,"modeMotionStatus":0,"modeRecallStatus":0},{"mode":45,"modeMotionStatus":0,"modeRecallStatus":0},{"mode":46,"modeMotionStatus":0,"modeRecallStatus":0},{"mode":47,"modeMotionStatus":0,"modeRecallStatus":0},{"mode":48,"modeMotionStatus":0,"modeRecallStatus":0},{"mode":49,"modeMotionStatus":0,"modeRecallStatus":0},{"mode":50,"modeMotionStatus":0,"modeRecallStatus":0},{"mode":51,"modeMotionStatus":0,"modeRecallStatus":0},{"mode":52,"modeMotionStatus":0,"modeRecallStatus":0},{"mode":53,"modeMotionStatus":0,"modeRecallStatus":0},{"mode":54,"modeMotionStatus":0,"modeRecallStatus":0},{"mode":55,"modeMotionStatus":0,"modeRecallStatus":0},{"mode":56,"modeMotionStatus":2,"modeRecallStatus":4},{"mode":57,"modeMotionStatus":0,"modeRecallStatus":0},{"mode":58,"modeMotionStatus":0,"modeRecallStatus":0},{"mode":59,"modeMotionStatus":0,"modeRecallStatus":0},{"mode":60,"modeMotionStatus":0,"modeRecallStatus":0},{"mode":61,"modeMotionStatus":0,"modeRecallStatus":0},{"mode":62,"modeMotionStatus":0,"modeRecallStatus":0},{"mode":63,"modeMotionStatus":0,"modeRecallStatus":0},{"mode":64,"modeMotionStatus":0,"modeRecallStatus":0}]}}
```


### 评论 4

**排查动作**: 请求车端确认传值

**排查结果**: 待车端反馈传值情况


### 评论 5

**排查动作**: 分析日志缺失模式

**排查结果**: CoreService未收到指定currentmode


**日志证据**:

```
行  94712: 04-22 13:57:38.211  4176  4176 I SeatModeTopic: currentMode: [0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 2, 0, 0, 0, 0, 0, 0, 0, 0]
```


### 评论 6

**排查动作**: 添加VCU指令错误截图

**排查结果**: 提供VCU端大四座指令发送错误证据


**日志证据**:

```
附件 1958442 (VCU端大四座指令发送错误.PNG)
```


### 评论 7

**排查动作**: 实车复测大四座模式

**排查结果**: VCU发送MODE101非MODE56


**日志证据**:

```
手机端点击大四座，实际VCU发送MODE101非MODE56
```


### 评论 8

**排查动作**: 实车确认MSM模式调用

**排查结果**: MSM端正常，转VCU确认


### 评论 9

**排查动作**: (Comment from 顾

**排查结果**: (Comment from 顾佳宁)
从


### 评论 10

**排查动作**: (Comment from 顾

**排查结果**: (Comment from 顾梦玥)
1


**日志证据**:

```
1、2025-04-22 13:54:20.978 日志如下
2025-04-22 13:54:20.978 mqtt---08---startCommonCmdPush收到mqtt的结果topicId:VCVV/SDVTWIN/578404ee164e978df528532006f05dd4---message:{"scene":"SEAT","dataType":"SEAT_MODE","requestId":"3b8fabd0-1f3e-11f0-8951-939a07d79df3","data":{"supportedModes":[1,1,1,0,0,0,0,1,1,1,1,1,1,0,0,0,0,0,0,0,0,0,0,0,0,0,1,1,1,1,1,1,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,1,0,0,1,1,1,0,0,0,0,0,0],"availableModes":[1,1,1,0,0,0,0,1,1,1,1,1,1,0,0,0,0,0,0,0,0,0,0,0,0,0,1,1,1,0,1,1,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,1,0,0,1,1,1,0,0,0,0,0,0],"currentModes":[{"mode":1,"modeMotionStatus":0,"modeRecallStatus":0},{"mode":2,"modeMotionStatus":0,"modeRecallStatus":0},{"mode":3,"modeMotionStatus":0,"modeRecallStatus":0},{"mode":4,"modeMotionStatus":0,"modeRecallStatus":0},{"mode":5,"modeMotionStatus":0,"modeRecallStatus":0},{"mode":6,"modeMotionStatus":0,"modeRecallStatus":0},{"mode":7,"modeMotionStatus":0,"modeRecallStatus":0},{"mode":8,"modeMotionStatus":0,"modeRecallStatus":0},{"mode":9,"modeMotionStatus":0,"modeRecallStatus":0},{"mode":10,"modeMotionStatus":0,"modeRecallStatus":0},{"mode":11,"modeMotionStatus":0,"modeRecallStatus":0},{"mode":12,"modeMotionStatus":0,"modeRecallStatus":0},{"mode":13,"modeMotionStatus":0,"modeRecallStatus":0},{"mode":14,"modeMotionStatus":0,"modeRecallStatus":0},{"mode":15,"modeMotionStatus":0,"modeRecallStatus":0},{"mode":16,"modeMotionStatus":0,"modeRecallStatus":0},{"mode":17,"modeMotionStatus":0,"modeRecallStatus":0},{"mode":18,"modeMotionStatus":0,"modeRecallStatus":0},{"mode":19,"modeMotionStatus":0,"modeRecallStatus":0},{"mode":20,"modeMotionStatus":0,"modeRecallStatus":0},{"mode":21,"modeMotionStatus":0,"modeRecallStatus":0},{"mode":22,"modeMotionStatus":0,"modeRecallStatus":0},{"mode":23,"modeMotionStatus":0,"modeRecallStatus":0},{"mode":24,"modeMotionStatus":0,"modeRecallStatus":0},{"mode":25,"modeMotionStatus":0,"modeRecallStatus":0},{"mode":26,"modeMotionStatus":0,"modeRecallStatus":0},{"mode":27,"modeMotionStatus":0,"modeRecallStatus":0},{"mode":28,"modeMotionStatus":0,"modeRecallStatus":0},{"mode":29,"modeMotionStatus":0,"modeRecallStatus":0},{"mode":30,"modeMotionStatus":0,"modeRecallStatus":0},{"mode":31,"modeMotionStatus":0,"modeRecallStatus":0},{"mode":32,"modeMotionStatus":0,"modeRecallStatus":0},{"mode":33,"modeMotionStatus":0,"modeRecallStatus":0},{"mode":34,"modeMotionStatus":0,"modeRecallStatus":0},{"mode":35,"modeMotionStatus":0,"modeRecallStatus":0},{"mode":36,"modeMotionStatus":0,"modeRecallStatus":0},{"mode":37,"modeMotionStatus":0,"modeRecallStatus":0},{"mode":38,"modeMotionStatus":0,"modeRecallStatus":0},{"mode":39,"modeMotionStatus":0,"modeRecallStatus":0},{"mode":40,"modeMotionStatus":0,"modeRecallStatus":0},{"mode":41,"modeMotionStatus":0,"modeRecallStatus":0},{"mode":42,"modeMotionStatus":0,"modeRecallStatus":0},{"mode":43,"modeMotionStatus":0,"modeRecallStatus":0},{"mode":44,"modeMotionStatus":0,"modeRecallStatus":0},{"mode":45,"modeMotionStatus":0,"modeRecallStatus":0},{"mode":46,"modeMotionStatus":0,"modeRecallStatus":0},{"mode":47,"modeMotionStatus":0,"modeRecallStatus":0},{"mode":48,"modeMotionStatus":0,"modeRecallStatus":0},{"mode":49,"modeMotionStatus":0,"modeRecallStatus":0},{"mode":50,"modeMotionStatus":0,"modeRecallStatus":0},{"mode":51,"modeMotionStatus":0,"modeRecallStatus":0},{"mode":52,"modeMotionStatus":0,"modeRecallStatus":0},{"mode":53,"modeMotionStatus":0,"modeRecallStatus":0},{"mode":54,"modeMotionStatus":0,"modeRecallStatus":0},{"mode":55,"modeMotionStatus":0,"modeRecallStatus":0},{"mode":56,"modeMotionStatus":2,"modeRecallStatus":4},{"mode":57,"modeMotionStatus":0,"modeRecallStatus":0},{"mode":58,"modeMotionStatus":0,"modeRecallStatus":0},{"mode":59,"modeMotionStatus":0,"modeRecallStatus":0},{"mode":60,"modeMotionStatus":0,"modeRecallStatus":0},{"mode":61,"modeMotionStatus":0,"modeRecallStatus":0},{"mode":62,"modeMotionStatus":0,"modeRecallStatus":0},{"mode":63,"modeMotionStatus":0,"modeRecallStatus":0},{"mode":64,"modeMotionStatus":0,"modeRecallStatus":0}]}}
```


### 评论 11

**排查动作**: 添加实车故障截图附件

**排查结果**: 已添加两张现场图片附件


### 评论 12

**排查动作**: 优化弱网数据接收稳定性

**排查结果**: 待复测验证


### 评论 13

**排查动作**: 远控功能联调检查

**排查结果**: 车端未集成VCU，暂不可测


### 评论 14

**排查动作**: 远控功能联调检查

**排查结果**: 车端未集成VCU，暂不可测


### 评论 15

**排查动作**: 评估远控链路可测性

**排查结果**: 车端未发布，暂不可测


### 评论 16

**排查动作**: 确认接口变更及页面更新

**排查结果**: 问题已解决，票单关闭

