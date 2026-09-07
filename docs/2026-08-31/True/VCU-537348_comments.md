# VCU-537348 评论分析总结

## 排查结论

已定位为VCU侧NTF通知静默失败，已提交补丁并发布新版本，待车端确认实际发送情况。


## 排查过程分析

### 问题现象
车辆未下电时，手机端收不到“车辆未下电”提醒，NTF通知上报流程静默失败。

### 排查过程
| 步骤 | 排查动作 | 结果 | 关键证据 |
|------|----------|------|----------|
| 1 | 请求车端排查NTF上报 | 待车端确认是否发出及CE ID | 评论1：请求车端排查NTF上报 |
| 2 | 询问NTF及URL信息 | 待用户提供具体信息 | 评论2：询问NTF及URL信息 |
| 3 | 解析ntf通知报文 | 确认VCU发送ConstantConnectUnavailableReason通知 | 评论3：`"source":"cls:\/\/vcu.LSGCF8N59SS12` |
| 4 | 提交代码补丁评审 | 提交补丁至VCUPRO分支 | 评论4：`Git Commit : 7104b393b18ad084389b1128bca90fb15ce14347` |
| 5 | 提交代码补丁审查 | 提交补丁至VCUPROmain_release7分支 | 评论5：`Git Commit : 53445e327cc29c86a98e1e2e8a6873fb990bbf39` |
| 6 | 提交代码补丁审查 | 提交补丁至VCUPROmain分支 | 评论6：`Git Commit : 3bd493142e7a12bec3af430eb2041f362d368c18` |
| 7 | 发布新版本并关联代码 | 版本已发布至指定tag | 评论7：`tag : 557-8255-Mainline-20260828-UQB26C-1505` |
| 8 | 发布版本并记录构建信息 | 版本已发布至tag | 评论8：`tag : 358-8255-Mainline-20260828-UQB27C-146` |
| 9 | 发布版本并关联代码 | 已发布557-8775版本 | 评论9：`tag : 557-8775-Mainline-20260828-UQB26C-601` |
| 10 | 发布NCLB-8775版本 | 版本已发布至tag | 评论10：`tag : 358-8255-Mainline-20260828-UQB27C-146` |

### 排查结论
- **已确认的事实**：VCU确实发送了`ConstantConnectUnavailableReason`通知（评论3）；代码补丁已提交并发布至多个tag（评论7-10）；AI日志分析确认`REASON_PM_NON_OFF`枚举值在protobuf中无对应定义，导致序列化失败。
- **尚未确认需进一步排查的方向**：车端是否实际发出NTF及CE ID（评论1）；用户未提供NTF及URL具体信息（评论2）；补丁发布后是否实际解决手机端收不到提醒的问题，需验证。
- **与AI日志分析结论的一致点和差异点**：一致点：均确认通知上报失败与`REASON_PM_NON_OFF`枚举值序列化异常相关；差异点：


## 时序排查详情

### AI日志分析

- 业务枚举与 protobuf 枚举定义不同步：`SetUsageProfileStatusTopicEvent` 使用了 `REASON_PM_NON_OFF`，但 `ConstantConnectUnavailableReason.UnavailableReason` protobuf 枚举中无对应值，导致序列化失败（L86200、L86667）
- sendNotification 缺少枚举合法性校验：`ClsLinkManager.sendNotification`（ClsLinkManager.kt:109）在调用 `addUnavailableReasons` 时未校验枚举值合法性，异常直接抛出导致通知静默丢失（L86669）
- 通知上报失败导致手机端无提醒：`IllegalArgumentException` 中断了通知上报流程，reason 退化为 `UNRECOGNIZED`，手机端收不到"车辆未下电"提醒（L86662）
- 通知通道本身正常：15:05:47 使用其他 reason 值成功发送通知（status=OK），证明问题仅出在 `REASON_PM_NON_OFF` 枚举值的序列化环节（L125014）
- 请求链路完整且正确：手机端 → ServiceBus → CoreService → ConstantConnectQueue 的请求链路完整，CoreService 正确校验 PowerMode=ON 并拒绝请求（L118356、L118415）

### 评论 1

**排查动作**: 请求车端排查NTF上报

**排查结果**: 待车端确认是否发出及CE ID


### 评论 2

**排查动作**: 询问NTF及URL信息

**排查结果**: 待用户提供具体信息


### 评论 3

**排查动作**: 解析ntf通知报文

**排查结果**: 确认VCU发送ConstantConnectUnavailableReason通知


**日志证据**:

```
{"specversion":"1.0","id":"1f1a27bc-feab-67fd-8531-77fc4789d39f","source":"cls:\/\/vcu.LSGCF8N59SS120115.veh.lscp.sgm.com\/com.sgm.cls.constantconnectservice\/1\/ntf#ConstantConnectUnavailableReason","type":"ntf.v1","time":"2026-08-28T09:00:06.812+08:00","sink":"cls:\/\/bo.lscp.sgm.com\/vcvv\/1\/ConstantConnectUnavailableReason.notification","priority":"CS1","ttl":0}
```


### 评论 4

**排查动作**: 提交代码补丁评审

**排查结果**: 提交补丁至VCUPRO分支


**日志证据**:

```
Project : SDVConstantConnectService
Branch : VCUPROmain_release7
Git Commit : 7104b393b18ad084389b1128bca90fb15ce14347
Gerrit Change-Id : If1550aecd78e184a38ef6ec3a06e0c6a52929f6f
Gerrit URL : https://info-gerrit.apps.saic-gm.com/291585
```


### 评论 5

**排查动作**: 提交代码补丁审查

**排查结果**: 提交补丁至VCUPROmain_release7分支


**日志证据**:

```
Project : SDVConstantConnectService
Branch : VCUPROmain_release7
Git Commit : 53445e327cc29c86a98e1e2e8a6873fb990bbf39
Gerrit Change-Id : If1550aecd78e184a38ef6ec3a06e0c6a52929f6f
Gerrit URL : https://info-gerrit.apps.saic-gm.com/291585
```


### 评论 6

**排查动作**: 提交代码补丁审查

**排查结果**: 提交补丁至VCUPROmain分支


**日志证据**:

```
Project : SDVConstantConnectService
Branch : VCUPROmain
Git Commit : 3bd493142e7a12bec3af430eb2041f362d368c18
Gerrit Change-Id : If1550aecd78e184a38ef6ec3a06e0c6a52929f6f
Gerrit URL : https://info-gerrit.apps.saic-gm.com/291617
```


### 评论 7

**排查动作**: 发布新版本并关联代码

**排查结果**: 版本已发布至指定tag


**日志证据**:

```
[ This change has been released in tag : 557-8255-Mainline-20260828-UQB26C-1505 ]
Git Commit : 3bd493142e7a12bec3af430eb2041f362d368c18
Gerrit URL : https://info-gerrit.apps.saic-gm.com/291617
```


### 评论 8

**排查动作**: 发布版本并记录构建信息

**排查结果**: 版本已发布至tag 358-8255-Mainline-20260828-UQB27C-146


**日志证据**:

```
[ This change has been released in tag : 358-8255-Mainline-20260828-UQB27C-146 ]
Git Commit : 3bd493142e7a12bec3af430eb2041f362d368c18
Gerrit URL : https://info-gerrit.apps.saic-gm.com/291617
```


### 评论 9

**排查动作**: 发布版本并关联代码

**排查结果**: 已发布557-8775版本，提交3bd4931


**日志证据**:

```
[ This change has been released in tag : 557-8775-Mainline-20260828-UQB26C-601 ]
Git Commit : 3bd493142e7a12bec3af430eb2041f362d368c18
```


### 评论 10

**排查动作**: 发布NCLB-8775版本

**排查结果**: 版本已发布至tag


**日志证据**:

```
[ This change has been released in tag : NCLB-8775-Mainline-20260828-UQB26C-125 ]
Git Commit : 3bd493142e7a12bec3af430eb2041f362d368c18
Gerrit URL : https://info-gerrit.apps.saic-gm.com/291617
```


### 评论 11

**排查动作**: 发布Release7版本

**排查结果**: 版本已发布至tag 358-8255-Release7


**日志证据**:

```
[ This change has been released in tag : 358-8255-Release7-20260828-UQB27C-27 ]
Git Commit : 53445e327cc29c86a98e1e2e8a6873fb990bbf39
Gerrit URL : https://info-gerrit.apps.saic-gm.com/291585
```


### 评论 12

**排查动作**: 发布Release7版本

**排查结果**: 版本已发布至tag 557-8775-Release7


**日志证据**:

```
[ This change has been released in tag : 557-8775-Release7-20260828-UQB27C-29 ]
Git Commit : 53445e327cc29c86a98e1e2e8a6873fb990bbf39
Gerrit URL : https://info-gerrit.apps.saic-gm.com/291585
```


### 评论 13

**排查动作**: 发布Release7版本

**排查结果**: 版本已发布至tag 557-8255-Release7


**日志证据**:

```
[ This change has been released in tag : 557-8255-Release7-20260829-UQB27C-35 ]
Git Commit : 53445e327cc29c86a98e1e2e8a6873fb990bbf39
Gerrit URL : https://info-gerrit.apps.saic-gm.com/291585
```


### 评论 14

**排查动作**: 发布Release7版本

**排查结果**: 版本已发布至指定tag


**日志证据**:

```
[ This change has been released in tag : NDNC-8775-Release7-20260829-UQB26C-25 ]
```

