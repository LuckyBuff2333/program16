# VCU-229457 评论分析总结

## 排查结论

远控服务未启动因StorageManagerService报Package不存在，已定位并提交补丁修复，实车复测未复现，问题已解决。


**排查摘要**：远控服务未启动因StorageManagerService报Package不存在，已定位并提交补丁修复，实车复测未复现


## 排查过程分析

### 问题现象
车机端远控服务（com.sgm.cls.remotecontrolservice）未启动，导致远控指令执行失败，问题在实车复测中未复现。

### 排查过程
| 步骤 | 排查动作 | 结果 | 关键证据 |
|------|----------|------|----------|
| 1 | 上传复现附件 | 提供pcap、日志、视频 | 评论1：上传复现附件 |
| 2 | 实车复测8-11版本 | 问题未复现 | 评论2：实车复测未复现 |
| 3 | 云端日志分析 | 车机无对应点日志 | 评论3：车机无对应点日志 |
| 4 | 添加5S002截图 | 已添加附件 | 评论4：添加5S002截图 |
| 5 | 添加无远控进程截图 | 已添加附件 | 评论5：添加无远控进程截图 |
| 6 | 分析远控服务未启动日志 | 服务未启动，需系统层协助 | 评论6：StorageManagerService报Package不存在 |
| 7 | 提交代码补丁审查 | 提交至VCUPROmain分支 | 评论8：Commit 3d4a97796faa |
| 8 | 提交代码补丁修复 | 提交至VCUPROmain_release2 | 评论9：Commit 86ccd5e89d34 |
| 9 | 发布软件版本NDNC-8775 | 已发布Release2-20250813 | 评论10：NDNC-8775-Release2 |
| 10 | 发布版本并记录变更 | 已发布至557-8255-Release2 | 评论11：tag 557-8255-Release2 |
| 11 | 发布版本并记录提交 | 已发布至557-8775-Release2 | 评论12：tag 557-8775-Release2 |

### 排查结论
**已确认的事实：**
- 远控服务未启动，日志显示 `Package com.sgm.cls.remotecontrolservice doe`（评论6）
- 服务数据目录访问失败：`Failed to ensure /data/user/10/com.sgm.cls.remotecontr`（评论6）
- 代码修复已提交并发布至多个版本分支（评论8-12，Commit 86ccd5e89d34）

**尚未确认需进一步排查的方向：**
- 远控服务未启动的根本原因（系统层权限或包管理问题）
- 实车复测未复现的原因（偶发性问题或环境差异）
- 5S002错误与本次bug的关联性（AI分析指出属摄像头模块）

**与AI日志分析结论的一致点和差异点：**
- 一致点：均确认远控指令执行记录缺失，5S002错误与本次bug无直接关联
- 差异点：AI分析认为日志窗口可能不覆盖指令下发时间，而人工排查确认服务未启动是直接原因；AI未识别出服务未启动的包管理异常，人工日志分析定位到具体包错误


## 时序排查详情

### AI日志分析

- 远控指令执行记录完全缺失：日志窗口内未追踪到四类远控指令的任何执行记录，无法定位失败环节（13:29:45~13:33:57，全窗口）
- 5S002 错误与本次 bug 无直接关联：唯一匹配的 5S002 错误属于摄像头模块 RPC 请求，uri 为 `cls:/camera.connected_camera/1/rpc.GetTopicMessage`（13:30:02，PID 4720）
- 日志窗口可能不覆盖指令下发时间：问题实际发生时间未填写，日志窗口起始于 13:29:45，而问题时间标注为 13:29:51，远控指令可能通过车云链路异步下发（13:29:51，-）
- CarPropertyService 属性权限异常：propId `0x212001ba` 不在配置列表中，与远控指令失败的关联性未确认（13:29:45，PID 2823）
- 车云通信链路状态未验证：SDV_Streamer MQTT / VDC Agent 状态未检查，无法确认云端指令是否成功下发到车端（全窗口）

### 评论 1

**排查动作**: 上传复现附件

**排查结果**: 提供pcap、日志、视频等证据


### 评论 2

**排查动作**: 实车复测8-11版本

**排查结果**: 问题未复现，待进一步分析


### 评论 3

**排查动作**: 云端日志分析

**排查结果**: 车机无对应点日志


### 评论 4

**排查动作**: 添加附件5S002截图

**排查结果**: 已添加附件，待进一步分析


### 评论 5

**排查动作**: 添加无远控进程截图

**排查结果**: 已添加附件，待进一步分析


### 评论 6

**排查动作**: 分析远控服务未启动日志

**排查结果**: 服务未启动，需系统层协助


**日志证据**:

```
08-11 13:29:46.421  1687  3279 V StorageManagerService: Package com.sgm.cls.remotecontrolservice does not have legacy storage
08-11 13:29:50.548  4141  4141 W ContextImpl: Failed to ensure /data/user/10/com.sgm.cls.remotecontrolservi
```


### 评论 7

**排查动作**: (Comment from 肖

**排查结果**: (Comment from 肖凯)
Cu


### 评论 8

**排查动作**: 提交代码补丁审查

**排查结果**: 提交补丁至VCUPROmain分支


**日志证据**:

```
Project : SDVRemoteControlService
Branch : VCUPROmain
Git Commit : 3d4a97796faa215b61f18eb14ea5387d2c3e33d4
Gerrit Change-Id : I4a277062788584440ae9641eb0cf5aa6a1d7d3e5
Gerrit URL : https://info-gerrit.apps.saic-gm.com/211507
```


### 评论 9

**排查动作**: 提交代码补丁修复

**排查结果**: 提交补丁至VCUPROmain_release2分支


**日志证据**:

```
Project : SDVRemoteControlService
Branch : VCUPROmain_release2
Git Commit : 86ccd5e89d34bb3b9d711467ea6b5233ef283fb2
Gerrit Change-Id : I4a277062788584440ae9641eb0cf5aa6a1d7d3e5
Gerrit URL : https://info-gerrit.apps.saic-gm.com/211529
```


### 评论 10

**排查动作**: 发布软件版本NDNC-8775

**排查结果**: 已发布至Release2-20250813-UQB26C-120


**日志证据**:

```
[ This change has been released in software NDNC-8775-Release2-20250813-UQB26C-120.zip ]
Git Commit : 86ccd5e89d34bb3b9d711467ea6b5233ef283fb2
Gerrit URL : "https://info-gerrit.apps.saic-gm.com/211529"
```


### 评论 11

**排查动作**: 发布版本并记录变更

**排查结果**: 变更已发布至557-8255-Release2


**日志证据**:

```
[ This change has been released in tag 557-8255-Release2-20250813-UQB26C-76.zip ]
Git Commit : 86ccd5e89d34bb3b9d711467ea6b5233ef283fb2
Gerrit URL : "https://info-gerrit.apps.saic-gm.com/211529"
```


### 评论 12

**排查动作**: 发布版本并记录提交信息

**排查结果**: 版本已发布至tag 557-8775-Release2


**日志证据**:

```
[ This change has been released in tag 557-8775-Release2-20250813-UQB26C-65.zip ]
Git Commit : 86ccd5e89d34bb3b9d711467ea6b5233ef283fb2
Gerrit URL : "https://info-gerrit.apps.saic-gm.com/211529"
```


### 评论 13

**排查动作**: 指定版本复测要求

**排查结果**: 需基于新版本复测


**日志证据**:

```
LOCAL8155_R2-A-UQB26C-20250812
```


### 评论 14

**排查动作**: 推动VCU刷写验证

**排查结果**: 等待VCU刷写后实车验证


### 评论 15

**排查动作**: 提供USB升级包

**排查结果**: 已交付给张晓锋


### 评论 16

**排查动作**: 实车复测验证问题

**排查结果**: 问题未解决，需进一步分析


### 评论 17

**排查动作**: 上传0813VCU远控测试视频及日志

**排查结果**: 已提供测试视频和分段日志附件


**日志证据**:

```
附件 2204609 (0813VCU远控远况测试.mp4)
附件 2204610 (gmlogger_2025_8_13_20_45_50.part01.rar)
附件 2204611 (gmlogger_2025_8_13_20_45_50.part02.rar)
```


### 评论 18

**排查动作**: 上传VCU远控测试附件

**排查结果**: 提供测试视频、日志及抓包文件


### 评论 19

**排查动作**: 确认问题解决并归类

**排查结果**: 5S002已解决，新问题与1108819类似


### 评论 20

**排查动作**: 确认5S002未出现

**排查结果**: 新问题转Bug 1108819跟踪

