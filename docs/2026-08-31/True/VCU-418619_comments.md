# VCU-418619 评论分析总结

## 排查结论

香氛浓度切换失效已定位，根因是BDF未收到enable=true信号，底层字段不匹配致换香失败，当前已转IT处理。


## 排查过程分析

### 问题现象
远控香氛浓度切换功能失效，用户下发“适中切浓郁/淡雅”指令后，BDF（香氛执行模块）无响应，浓度值保持不变。

### 排查过程
| 步骤 | 排查动作 | 结果 | 关键证据 |
|------|----------|------|----------|
| 1 | 上传复现日志与视频 | 待分析 | 提供复现附件 |
| 2 | 复制工作项1237196 | 无新增动作 | 复制记录 |
| 3 | 分析MQTT日志 | 消息已接收 | 15:27:58.162 getMqttRemoteTypeWakeUpResult request |
| 4 | 复审信号发送 | BDF未响应 | 信号已发，BDF无回执 |
| 5 | 添加截图附件 | 已添加 | 两张截图 |
| 6 | 复测香氛切换 | BDF未响应 | 15:27:35 适中切浓郁 BDF未响应 |
| 7 | 对比use case7切换逻辑 | 发现enable未发true | 浓度切换未发enable=true导致换香失败 |
| 8 | 添加截图附件 | 已添加 | Capture.PNG |
| 9 | 分析VCU信号与硬件响应 | 底层硬件无法响应 | Fragrance Diffuser Enable = ACTIVE，Scent Intensity Level = 有效值 |
| 10 | 请求协助解决 | 待确认方案 | 需确认后续解决方案 |
| 11 | 确认底层信号与下发字段 | 字段不匹配 | enable = inactive，scent_intensity = 20/50/90 |
| 12 | 转交IT处理 | 已转交 | 转交IT跟进 |
| 13 | 要求service判断active状态 | 有异议上升 | 不接受IT更改方案 |
| 14 | 添加崩溃截图 | 待分析 | 已添加截图 |
| 15 | 比对远控SPEC信号组合 | 底层模块变更未覆盖 | HVAC Infotainment Contr |

### 排查结论
- **已确认的事实**：15:27:18 的远控指令中 enable 字段为 inactive，而 scent_intensity 字段虽为有效值（20/50/90），但底层香氛模块因 enable 未激活而拒绝执行浓度切换；BDF 在多次复测中均无响应，且底层信号显示 Fragrance Diffuser Enable = ACTIVE 但 Scent Intensity Level 有效，说明信号已下发但执行层未动作。
- **尚未确认需进一步排查的方向**：云端/APP 侧序列化时为何在 15:27:18 遗漏 enable=true 字段（AI 日志指出该时刻 update_mask 仅含 message_id/enable/cartridge_setting，但实际 enable 值为 inactive）；底层香氛模块变更后是否覆盖了远控场景的 SPEC 组合；IT 提出的更改方案与 service 判断 active 状态的逻辑冲突需上升决策。
- **与AI日志分析结论的一致点和差异点**：一致点在于均确认 15:27:18 指令存在字段问题（AI 指缺失 scent_intensity，人工排查指 enable 为 inactive），且均指向云端/APP


## 时序排查详情

### AI日志分析

- Critical — 远控指令缺失 scent_intensity 字段：15:27:18 的 update_mask 仅含 message_id/enable/cartridge_setting，车端无浓度数据可执行，直接导致浓度无法调节（15:27:18.964，RemoteSetCLEAFragranceDiffuserRequestProcessor）。
- Critical — 字段遗漏属于云端/APP 侧序列化问题：15:27:34 和 15:27:56 的指令均包含 scent_intensity，证明协议支持该字段，15:27:18 的缺失是生成环节的偶发遗漏（15:27:34.265，RemoteSetCLEAFragranceDiffuserRequestProcessor）。
- Important — cartridge3 槽位回调状态异常：指令指定 cartridge3，但回调返回 CFDCS_SEALED_NO_SCENT，指示槽位可能未正确插入香氛或映射配置错误（15:27:18.983，onFragranceChange）。
- Info — 车端本地香氛功能正常：熄火前本地设置 ScentIntensity=50 成功写入，状态回读链路正常，排除车端处理能力问题（15:26:54.183，CLEAFragranceDiffuserRequestProcessor）。

### 评论 1

**排查动作**: 上传复现日志与视频

**排查结果**: 提供复现附件，待分析


### 评论 2

**排查动作**: 复制工作项1237196

**排查结果**: 无新增排查动作


### 评论 3

**排查动作**: (Comment from 刘

**排查结果**: (Comment from 刘晓)
手机


**日志证据**:

```
IDPU1CEBC18D4: 构建时间: 2026-01-07 15:27:58.162 (Size: 0.35 KB) getMqttRemoteTypeWakeUpResult request {vin: LSGUN8P28SA043639, type: FRAGRANCE, sdvArchVersion: SDV1, params: {fragranceDiffuser: {fragranceEnable: ACTIVE, scentIntensity: 20}}}
IDPU1CEBC18D4:构建时间: 2026-01-07 15:27:58.351  (Size: 0.38 KB) getMqttRemoteTypeWakeUpResult {bizCode: E0000, bizMsg: 操作成功, data: {remoteType: FRAGRANCE, requestId: 63f90345-eb9a-11f0-8dbd-07069943b3f1, vehicleConnState: online, timeOut: 60}} statusCode：200
IDPU1CEBC18D4: 构建时间: 2026-01-07 15:27:59.127 (Size: 0.66 KB) Flutter CallBack 日志: MQTT 接受到消息: {"bizCode":"E0000","bizMsg":"远控执行成功","data":{"mqttTopic":"SOSOAG/SDV/77a38cd3c49c24c8078b23e481a8a8be","remoteType":"FRAGRANCE","requestId":"63f90345-eb9a-11f0-8dbd-07069943b3f1"},"traceparent":"00-264bba60bdd8e4f1ae635cae8752ac83-1410101f609901bf-01"}===>topic==SOSOAG/SDV/77a38cd3c49c24c8078b23e481a8a8be
```


### 评论 4

**排查动作**: 子健复审信号发送

**排查结果**: 信号已发，BDF未响应


### 评论 5

**排查动作**: 添加附件截图

**排查结果**: 已添加两张截图


### 评论 6

**排查动作**: 复测香氛切换功能

**排查结果**: BDF未响应，浓度不变


**日志证据**:

```
15:27:35 适中切浓郁 BDF未响应
15:27:57 适中切淡雅 BDF未响应
```


### 评论 7

**排查动作**: 对比use case7切换逻辑

**排查结果**: 浓度切换未发enable=true导致换香失败


### 评论 8

**排查动作**: 添加附件截图

**排查结果**: 已添加Capture.PNG


### 评论 9

**排查动作**: 分析VCU信号与硬件响应

**排查结果**: 底层香氛硬件无法响应，需改逻辑或备车不支持


**日志证据**:

```
HVAC Infotainment Controls Request Fragrance Diffuser Enable = ACTIVE
HVAC Infotainment Controls Request Fragrance Diffuser Scent Cartridge Selection = 4
HVAC Infotainment Controls Request Fragrance Diffuser Scent Intensity Level = 有效值
HVAC Infotainment Controls Request Fragrance Diffuser Scent Intensity Level Active = TRUE
```


### 评论 10

**排查动作**: 请求协助解决远控香氛问题

**排查结果**: 需确认后续解决方案


### 评论 11

**排查动作**: 确认底层信号与下发字段

**排查结果**: 字段不匹配，需IT确认


**日志证据**:

```
HVAC Infotainment Controls Request Fragrance Diffuser Scent Intensity Level = 有效值
HVAC Infotainment Controls Request Fragrance Diffuser Scent Intensity Level Active = TRUE
enable = inactive. scent_intensity = 想要的浓度20/50/90.
enable不用写，scent_intensity = 想要的浓度20/50/90.
```


### 评论 12

**排查动作**: 转交IT处理

**排查结果**: 已转交IT跟进


### 评论 13

**排查动作**: 要求service判断active状态

**排查结果**: 不接受IT更改方案，有异议上升


**日志证据**:

```
{vin: LSGUN8P28SA043639, type: FRAGRANCE, sdvArchVersion: SDV1, params: {fragranceDiffuser: {fragranceEnable: ACTIVE, scentIntensity: 20}}}
```


### 评论 14

**排查动作**: 添加崩溃截图附件

**排查结果**: 已添加截图，待进一步分析


### 评论 15

**排查动作**: 比对远控SPEC信号组合

**排查结果**: 底层香氛模块变更未覆盖场景


**日志证据**:

```
HVAC Infotainment Controls Request Fragrance Diffuser Enable = ACTIVE
HVAC Infotainment Controls Request Fragrance Diffuser Scent Cartridge Selection = 0
HVAC Infotainment Controls Request Fragrance Diffuser Scent Intensity Level = 有效值
HVAC Infotainment Controls Request Fragrance Diffuser Scent Intensity Level Active = TRUE
```


### 评论 16

**排查动作**: 梳理香氛浓度指令流程

**排查结果**: 需产品线决议是否去除Enable指令


### 评论 17

**排查动作**: TRB会议沟通

**排查结果**: 待讨论


### 评论 18

**排查动作**: 对齐香氛OTA收发逻辑

**排查结果**: 当前版本不接受OTA上线


### 评论 19

**排查动作**: 向FO索要最终更改方案

**排查结果**: 当前仅有一套适配车机端方案


### 评论 20

**排查动作**: 会议结论整理

**排查结果**: BDF无法同时控制香棒与浓度


### 评论 21

**排查动作**: 添加崩溃截图附件

**排查结果**: 已上传现场图片证据


### 评论 22

**排查动作**: 确认问题非备车专属

**排查结果**: 单独浓度调节问题，按会议结论解决


### 评论 23

**排查动作**: 参考comment7转core service

**排查结果**: 转交core service处理


### 评论 24

**排查动作**: 确认场景5需支持

**排查结果**: 该场景为会议场景5，需支持


### 评论 25

**排查动作**: 实车测试场景6信号

**排查结果**: 香氛开关均有异常BUG


**日志证据**:

```
20260123线下实车测试，场景6发送的信号，香氛无论是在开启情况下还是关闭情况下，都会有异常BUG
```


### 评论 26

**排查动作**: 评估远控场景适配责任

**排查结果**: 远控非SPEC定义，BDF已适配，请求信号不一致


### 评论 27

**排查动作**: 邮件同步测试结果并转交评估

**排查结果**: 场景1/3/7/8满足远控使用，待VCU对齐


### 评论 28

**排查动作**: 梳理香氛请求拦截逻辑

**排查结果**: 需底层适配，推动远控FO或产品线


**日志证据**:

```
HVACICRFrgrncDffsrEnbl : $0 No action
HVACICRFrgrncDffsrEnbl : $2 = Active
```


### 评论 29

**排查动作**: 推动core service继续处理

**排查结果**: 按可接受方案推进


### 评论 30

**排查动作**: 推动对手件排查

**排查结果**: 职责范围外，推动受阻


### 评论 31

**排查动作**: 定位问题责任方

**排查结果**: 非远控变更，需core service对齐


### 评论 32

**排查动作**: 责任归属判定

**排查结果**: 底层变动导致，FO整体负责


### 评论 33

**排查动作**: 请求远控服务评估方案

**排查结果**: 待评估浓度字段忽略下发可行性


### 评论 34

**排查动作**: 提交代码补丁修复

**排查结果**: 提交补丁至VCUPROmain分支


**日志证据**:

```
Project : SDVRemoteControlService
Branch : VCUPROmain
Git Commit : 9a3155cbf7016a8c292be3a60647197e2019d012
Gerrit Change-Id : I66f72229dc3bd167cd6178572273a87bc9582483
Gerrit URL : https://info-gerrit.apps.saic-gm.com/249543
```


### 评论 35

**排查动作**: 提交代码补丁修复

**排查结果**: 提交补丁至VCUPRO分支


**日志证据**:

```
Project : SDVRemoteControlService
Branch : VCUPROmain_release2
Git Commit : c83df5bf5fb5019f87f794fd9f109497d8eb4657
Gerrit Change-Id : I66f72229dc3bd167cd6178572273a87bc9582483
Gerrit URL : https://info-gerrit.apps.saic-gm.com/249852
```


### 评论 36

**排查动作**: 提交代码补丁审查

**排查结果**: 提交补丁至VCUPRO分支


**日志证据**:

```
Project : SDVRemoteControlService
Branch : VCUPROmain_release3
Git Commit : 195421c5a4a249c760363cfa5065a7dd76c3c1b7
Gerrit Change-Id : I66f72229dc3bd167cd6178572273a87bc9582483
Gerrit URL : https://info-gerrit.apps.saic-gm.com/249853
```


### 评论 37

**排查动作**: 提交代码补丁审查

**排查结果**: 提交补丁至VCUPROmain_release4分支


**日志证据**:

```
Project : SDVRemoteControlService
Branch : VCUPROmain_release4
Git Commit : c19c2b51eb9b481a19281f3aabea32dd330891e8
Gerrit Change-Id : I66f72229dc3bd167cd6178572273a87bc9582483
Gerrit URL : https://info-gerrit.apps.saic-gm.com/249854
```


### 评论 38

**排查动作**: 修改相关方task

**排查结果**: 更新三个task编号


### 评论 39

**排查动作**: 确认合入版本后提测

**排查结果**: 等待紫阳确认具体版本


### 评论 40

**排查动作**: 发布软件版本NDNC-8775

**排查结果**: 修复已合入Release4版本


**日志证据**:

```
[ This change has been released in software NDNC-8775-Release4-20260203-UQB26C-89.zip ]
Git Commit : c19c2b51eb9b481a19281f3aabea32dd330891e8
Gerrit URL : "https://info-gerrit.apps.saic-gm.com/249854"
```


### 评论 41

**排查动作**: 发布版本并记录提交信息

**排查结果**: 已发布至L234-8255-Release4


**日志证据**:

```
[ This change has been released in tag L234-8255-Release4-20260203-UQB27B-83.zip ]
Git Commit : 9a3155cbf7016a8c292be3a60647197e2019d012
Gerrit URL : "https://info-gerrit.apps.saic-gm.com/249543"
```


### 评论 42

**排查动作**: 发布版本并记录提交信息

**排查结果**: 已发布至L234-8255-Release4


**日志证据**:

```
[ This change has been released in tag L234-8255-Release4-20260203-UQB27B-83.zip ]
Git Commit : c19c2b51eb9b481a19281f3aabea32dd330891e8
Gerrit URL : "https://info-gerrit.apps.saic-gm.com/249854"
```


### 评论 43

**排查动作**: 发布Release4版本

**排查结果**: 已发布至L234-8255-Release4


**日志证据**:

```
[ This change has been released in tag L234-8255-Release4-20260203-UQB27B-83.zip ]
```


### 评论 44

**排查动作**: 发布Release4版本

**排查结果**: 变更已发布至L234-8255-Release4


**日志证据**:

```
[ This change has been released in tag L234-8255-Release4-20260203-UQB27B-83.zip ]
```


### 评论 45

**排查动作**: 发布Release3版本

**排查结果**: 变更已发布至557-8775-Release3


**日志证据**:

```
[ This change has been released in tag 557-8775-Release3-20260203-UQB26C-426.zip ]
Git Commit : 195421c5a4a249c760363cfa5065a7dd76c3c1b7
Gerrit URL : "https://info-gerrit.apps.saic-gm.com/249853"
```


### 评论 46

**排查动作**: 发布软件版本

**排查结果**: 已发布至Mainline-20260203


**日志证据**:

```
NDNC-8775-Mainline-20260203-UQB26C-502.zip
```


### 评论 47

**排查动作**: 发布代码到557-8255-Release3

**排查结果**: 已发布，包含SDVRemoteControlService变更


**日志证据**:

```
[ This change has been released in tag 557-8255-Release3-20260203-UQB26C-360.zip ]
Project : SDVRemoteControlService
Branch : VCUPROmain_release3
Git Commit : 195421c5a4a249c760363cfa5065a7dd76c3c1b7
Gerrit URL : "https://info-gerrit.apps.saic-gm.com/249853"
Artifactory Link : https://jfrog-sync.apps.saic-gm.com:443/artifactory/VcuPro/557_release3/8255/
```


### 评论 48

**排查动作**: 发布软件版本NDNC-8775

**排查结果**: 修复已发布至Release2版本


**日志证据**:

```
[ This change has been released in software NDNC-8775-Release2-20260203-UQB26C-629.zip ]
Git Commit : c83df5bf5fb5019f87f794fd9f109497d8eb4657
Gerrit URL : "https://info-gerrit.apps.saic-gm.com/249852"
```


### 评论 49

**排查动作**: 发布版本并关联代码

**排查结果**: 已发布至L234-8255-Mainline-20260203


**日志证据**:

```
[ This change has been released in tag L234-8255-Mainline-20260203-UQB27B-315.zip ]
Git Commit : 9a3155cbf7016a8c292be3a60647197e2019d012
Gerrit URL : "https://info-gerrit.apps.saic-gm.com/249543"
```


### 评论 50

**排查动作**: 发布版本并记录提交信息

**排查结果**: 已发布至L234-8255-Mainline-20260203


**日志证据**:

```
[ This change has been released in tag L234-8255-Mainline-20260203-UQB27B-315.zip ]
Git Commit : c19c2b51eb9b481a19281f3aabea32dd330891e8
Gerrit URL : "https://info-gerrit.apps.saic-gm.com/249854"
```


### 评论 51

**排查动作**: 发布版本并记录提交信息

**排查结果**: 版本已发布至指定tag


**日志证据**:

```
[ This change has been released in tag L234-8255-Mainline-20260203-UQB27B-315.zip ]
Git Commit : c83df5bf5fb5019f87f794fd9f109497d8eb4657
Gerrit URL : "https://info-gerrit.apps.saic-gm.com/249852"
```


### 评论 52

**排查动作**: 发布版本并记录提交信息

**排查结果**: 版本已发布至指定tag


**日志证据**:

```
[ This change has been released in tag L234-8255-Mainline-20260203-UQB27B-315.zip ]
Git Commit : 195421c5a4a249c760363cfa5065a7dd76c3c1b7
Gerrit URL : "https://info-gerrit.apps.saic-gm.com/249853"
```


### 评论 53

**排查动作**: 发布版本并记录提交信息

**排查结果**: 版本已发布至指定tag


**日志证据**:

```
[ This change has been released in tag 557-8775-Mainline-20260203-UQB26C-316.zip ]
Git Commit : 9a3155cbf7016a8c292be3a60647197e2019d012
Gerrit URL : "https://info-gerrit.apps.saic-gm.com/249543"
```


### 评论 54

**排查动作**: 发布版本并记录提交信息

**排查结果**: 版本已发布至指定tag


**日志证据**:

```
[ This change has been released in tag 557-8255-Mainline-20260203-UQB26C-1217.zip ]
Git Commit : 9a3155cbf7016a8c292be3a60647197e2019d012
Gerrit URL : "https://info-gerrit.apps.saic-gm.com/249543"
```


### 评论 55

**排查动作**: 指定验证版本

**排查结果**: 基于557-8775-Release3验证


### 评论 56

**排查动作**: 实车复测0205版本

**排查结果**: 香氛浓度正常，问题已修复


**日志证据**:

```
557-8775-Ralease3-20250205-UQB26C-428
OK
0/30
```

