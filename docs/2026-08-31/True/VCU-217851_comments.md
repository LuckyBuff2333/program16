# VCU-217851 评论分析总结

## 排查结论

座椅按摩功能未生效，已定位为信号处理异常，疑似对手件连续上报导致，已提交代码补丁，待进一步验证。


## 排查过程分析

### 问题现象
座椅按摩功能在实车复测中未生效，HMI 图标熄灭，且按摩类型不受支持，疑似信号处理或状态同步异常。

### 排查过程
| 步骤 | 排查动作 | 结果 | 关键证据 |
|------|----------|------|----------|
| 1 | 上传实车复测视频与日志 | 已提供复现素材，待分析 | 评论1：提供视频与日志 |
| 2 | 分析座椅按摩日志 | 发现不支持按摩类型，功能未生效 | 行144102-144103：`SeatMassageFirstRowRightTopic: set not` |
| 3 | 查看视频并分析自动关闭 | 怀疑对手件连续上报两次数据 | 评论3：怀疑连续上报 |
| 4 | 建议统一缓存刷新策略 | 建议local缓存message，不一致时刷新View | 评论5：缓存刷新策略 |
| 5 | 建议拦截Intensity为0信号 | 提出处理策略，待确认 | 评论6：拦截0信号 |
| 6 | 询问逻辑参照来源 | 待确认逻辑设计依据 | 评论7：逻辑来源待确认 |
| 7 | 通知复用字段级OnChange代码 | 建议复用代码处理座椅按摩BUG | 评论8：复用OnChange代码 |
| 8 | 回复字段判断方法 | 以intensity变化后的值为准 | 评论9：以变化后值为准 |
| 9 | 提交代码补丁审查 | 提交补丁至HMI开发分支 | Git Commit: 44b2070de665 |
| 10 | 提交代码补丁评审 | 提交HMI开发分支补丁 | Git Commit: 00fe4d95e48e |
| 11 | 提交代码补丁审查 | 提交补丁至HMI开发分支 | Git Commit: 0597e0b99eb5 |
| 12 | 提交代码补丁评审 | 提交HMI开发分支补丁 | Git Commit: 9d1d3c8730c3 |
| 13 | 提交代码补丁审查 | 提交补丁至release2分支 | Git Commit: 4333f9f7f7ea |
| 14 | 发布版本并记录提交信息 | 版本已发布至指定tag | 评论19：版本已发布 |

### 排查结论
- **已确认的事实**：日志显示座椅按摩类型不支持（`set not`），HMI 图标熄灭；intensity 请求为 0 但实际更新为 4，参数传递异常；isRealOpen 状态未更新导致 HMI 图标熄灭。
- **尚未确认需进一步排查的方向**：对手件连续上报两次数据的机制未验证；intensity 为 0 信号的拦截策略未最终确认；逻辑参照来源待明确。
- **与AI日志分析结论的一致点和差异点**：一致点在于均确认 isRealOpen 状态未更新及 intensity 不一致问题；差异点在于 AI 分析强调跨进程状态同步不完整，而人工排查更聚焦于信号拦截和缓存刷新策略。


## 时序排查详情

### AI日志分析

- isRealOpen 状态未更新：座椅按摩和加热请求均成功，但 isRealOpen 始终为 false，直接导致 HMI 图标熄灭（16:37:38.074，HMI getPhysio）
- intensityRequest 与 update intensity 不一致：请求强度为 0 但实际更新为 4，参数传递链路存在异常，可能影响状态判断逻辑（16:37:38.074，SeatMassageSomeIpRequestProcessor）
- HMI 侧 location:3/4 状态未同步：HMI 读取的 location:3 和 location:4 的 isOpen 均为 false，而 PhysioService 侧 location:1 的 isOpen 已为 true，跨进程状态同步不完整（16:37:38.074，HMI getPhysio）
- 多进程架构：PhysioService（PID 7982）与 HMI（PID 7150）分属不同进程，状态同步依赖跨进程通信，增加了状态不一致的风险（16:37:38.074，PhysioService）

### 评论 1

**排查动作**: 上传实车复测视频与日志

**排查结果**: 已提供复现素材，待分析


### 评论 2

**排查动作**: 分析座椅按摩日志

**排查结果**: 发现不支持按摩类型，功能未生效


**日志证据**:

```
行 144102: 07-21 16:37:25.763  7150  7369 I com.patac.hmi.climate-SeatMassageFirstRowRightTopic:  setRowFirstRightData: 1 isControlAvailable: true getSupportedMassageTypesCount: 1 isMassageSupport: true getIntensity: 0 getLastChosenTypeValue: 31 getTypeValue: 1
行 144103: 07-21 16:37:25.763  7150  7369 I com.patac.hmi.climate-SeatMassageFirstRowRightTopic: not surport row one right
```


### 评论 3

**排查动作**: 查看视频并分析自动关闭

**排查结果**: 怀疑对手件连续上报两次数据


### 评论 4

**排查动作**: (Comment from 顾

**排查结果**: (Comment from 顾佳宁)
该


### 评论 5

**排查动作**: 建议统一缓存刷新策略

**排查结果**: 建议local缓存message，不一致时刷新View


### 评论 6

**排查动作**: 建议拦截Intensity为0信号

**排查结果**: 提出处理策略，待确认


### 评论 7

**排查动作**: 询问逻辑参照来源

**排查结果**: 待确认逻辑设计依据


### 评论 8

**排查动作**: 通知复用字段级OnChange代码

**排查结果**: 建议复用代码处理座椅按摩BUG


### 评论 9

**排查动作**: 回复评论6，说明字段判断方法

**排查结果**: 以instensity变化后的值为准


### 评论 10

**排查动作**: 提交代码补丁审查

**排查结果**: 提交补丁至HMI开发分支


**日志证据**:

```
Project : PATACClimate
Branch : hmi_development
Git Commit : 44b2070de66513a7ee3246c569c131641705794a
Gerrit Change-Id : Ibefab69b01b8768ad5d13d873c5814dc3b71c41e
Gerrit URL : https://info-gerrit.apps.saic-gm.com/205159
```


### 评论 11

**排查动作**: 提交代码补丁评审

**排查结果**: 提交补丁至HMI开发分支


### 评论 12

**排查动作**: 提交代码补丁评审

**排查结果**: 提交HMI开发分支补丁


### 评论 13

**排查动作**: 提交代码补丁审查

**排查结果**: 提交补丁至HMI开发分支


**日志证据**:

```
Project : PATACClimate
Branch : hmi_development_release2
Git Commit : 00fe4d95e48ead745454c97def2eda24c118c632
Gerrit Change-Id : Ibefab69b01b8768ad5d13d873c5814dc3b71c41e
```


### 评论 14

**排查动作**: 提交代码补丁审查

**排查结果**: 提交补丁至HMI开发分支


**日志证据**:

```
Project : PATACClimate
Branch : hmi_development
Git Commit : 0597e0b99eb53b8125007531a928f6b7aeeb8199
Gerrit Change-Id : Ibefab69b01b8768ad5d13d873c5814dc3b71c41e
Gerrit URL : https://info-gerrit.apps.saic-gm.com/205159
```


### 评论 15

**排查动作**: 提交代码补丁评审

**排查结果**: 提交HMI开发分支补丁


**日志证据**:

```
Project : PATACClimate
Branch : hmi_development
Git Commit : 9d1d3c8730c354faaafab6595c5aa0f3d8086b4f
Gerrit Change-Id : Ibefab69b01b8768ad5d13d873c5814dc3b71c41e
Gerrit URL : https://info-gerrit.apps.saic-gm.com/205159
```


### 评论 16

**排查动作**: 提交代码补丁审查

**排查结果**: 提交补丁至hmi_development_release2分支


**日志证据**:

```
Project : PATACClimate
Branch : hmi_development_release2
Git Commit : 4333f9f7f7ead5ff026c52a47ed402438da34100
Gerrit Change-Id : Ibefab69b01b8768ad5d13d873c5814dc3b71c41e
Gerrit URL : https://info-gerrit.apps.saic-gm.com/205160
```


### 评论 17

**排查动作**: 提交代码补丁审查

**排查结果**: 提交HMI开发分支补丁


### 评论 18

**排查动作**: 提交代码补丁审查

**排查结果**: 提交补丁至HMI开发分支


### 评论 19

**排查动作**: 发布版本并记录提交信息

**排查结果**: 版本已发布至指定tag


**日志证据**:

```
[ This change has been released in tag 557-8255-Release2-20250723-UQB26C-35.zip ]
Git Commit : ea30f069e1f98a79b090369359773bafafe2de21
Gerrit URL : "https://info-gerrit.apps.saic-gm.com/205160"
```


### 评论 20

**排查动作**: 发布557-8775-Release2版本

**排查结果**: 版本已发布至指定tag


**日志证据**:

```
[ This change has been released in tag 557-8775-Release2-20250723-UQB26C-30.zip ]
Git Commit : ea30f069e1f98a79b090369359773bafafe2de21
Artifactory Link : http://10.203.71.4:8081/artifactory/VcuPro/557_release2/8775/
```


### 评论 21

**排查动作**: 发布版本并同步代码

**排查结果**: 已发布至GBBuick_Mid_R5_F1KM-20250723-SQB24B-344


**日志证据**:

```
[ This change has been released in tag : GBBuick_Mid_R5_F1KM-20250723-SQB24B-344]
Git Commit : 92906670c6a41ce819b453bbdf6ad9e8fb8a0179
Gerrit URL : "https://info-gerrit.apps.saic-gm.com/205159"
```


### 评论 22

**排查动作**: 发布软件版本NDNC-8775

**排查结果**: 已发布至Release2分支


**日志证据**:

```
[ This change has been released in software NDNC-8775-Release2-20250724-UQB26C-45.zip ]
Git Commit : ea30f069e1f98a79b090369359773bafafe2de21
Artifactory Link : https://jfrog-sync.apps.saic-gm.com:443/artifactory/VcuPro/NDNC_Release2/NDNC-8775-Release2-20250724-UQB26C-45/NDNC-8775-Release2-20250724-UQB26C-45.zip
```


### 评论 23

**排查动作**: 发布R5-20250724版本

**排查结果**: 版本已发布至指定tag


**日志证据**:

```
[ This change has been released in tag R5-20250724-SQB25C-780.zip ]
Git Commit : 92906670c6a41ce819b453bbdf6ad9e8fb8a0179
Gerrit URL : "https://info-gerrit.apps.saic-gm.com/205159"
```


### 评论 24

**排查动作**: 发布版本并记录提交信息

**排查结果**: 版本已发布至指定tag


**日志证据**:

```
[ This change has been released in tag 557-8255-Mainline-20250724-UQB26C-979.zip ]
Git Commit : 92906670c6a41ce819b453bbdf6ad9e8fb8a0179
Artifactory Link : http://10.203.71.4:8081/artifactory/VcuPro/557/8255/
```


### 评论 25

**排查动作**: 发布版本并记录提交信息

**排查结果**: 版本已发布至指定tag


**日志证据**:

```
[ This change has been released in tag 557-8775-Mainline-20250724-UQB26C-84.zip ]
Git Commit : 92906670c6a41ce819b453bbdf6ad9e8fb8a0179
Gerrit URL : "https://info-gerrit.apps.saic-gm.com/205159"
```


### 评论 26

**排查动作**: 提交代码补丁审查

**排查结果**: 提交补丁至HMI开发分支


**日志证据**:

```
Project : PATACClimate
Branch : hmi_development
Git Commit : 643e0418eb0e6ca7d0ba49fe6d6ef95f1954912b
Gerrit Change-Id : I6d57abce330bf34fc549847558f0fdec1212746e
Gerrit URL : https://info-gerrit.apps.saic-gm.com/206077
```


### 评论 27

**排查动作**: 提交代码补丁评审

**排查结果**: 提交补丁至hmi_development_release2分支


**日志证据**:

```
Project : PATACClimate
Branch : hmi_development_release2
Git Commit : 06028416d0a5f9acfe25a878c54c5e0d719dae93
Gerrit Change-Id : I6d57abce330bf34fc549847558f0fdec1212746e
Gerrit URL : https://info-gerrit.apps.saic-gm.com/206079
```


### 评论 28

**排查动作**: 发布软件版本NDNC-8775

**排查结果**: 修复已合入hmi_development分支


**日志证据**:

```
[ This change has been released in software NDNC-8775-Mainline-20250724-UQB26C-125.zip ]
Git Commit : 92906670c6a41ce819b453bbdf6ad9e8fb8a0179
Gerrit URL : "https://info-gerrit.apps.saic-gm.com/205159"
```


### 评论 29

**排查动作**: 提交代码补丁修复

**排查结果**: 补丁已提交，UT通过


**日志证据**:

```
UTResult : pass
```


### 评论 30

**排查动作**: 提交代码补丁修复

**排查结果**: UT通过，补丁已提交


**日志证据**:

```
UTResult : pass
```


### 评论 31

**排查动作**: (Comment from 魏

**排查结果**: (Comment from 魏珰)
行 


### 评论 32

**排查动作**: 发布版本并记录提交信息

**排查结果**: 版本已发布至tag 557-8255-Release2


**日志证据**:

```
[ This change has been released in tag 557-8255-Release2-20250725-UQB26C-38.zip ]
Git Commit : 06028416d0a5f9acfe25a878c54c5e0d719dae93
Gerrit URL : "https://info-gerrit.apps.saic-gm.com/206079"
```


### 评论 33

**排查动作**: 发布软件版本NDNC-8775

**排查结果**: 修复已合入hmi_development分支


**日志证据**:

```
[ This change has been released in software NDNC-8775-Mainline-20250725-UQB26C-126.zip ]
Git Commit : 92906670c6a41ce819b453bbdf6ad9e8fb8a0179
Gerrit URL : "https://info-gerrit.apps.saic-gm.com/205159"
```


### 评论 34

**排查动作**: 发布软件版本NDNC-8775

**排查结果**: 版本已发布至指定链接


**日志证据**:

```
[ This change has been released in software NDNC-8775-Mainline-20250725-UQB26C-126.zip ]
Git Commit : 643e0418eb0e6ca7d0ba49fe6d6ef95f1954912b
Artifactory Link : https://jfrog-sync.apps.saic-gm.com:443/artifactory/VcuPro/NDNC/NDNC-8775-Mainline-20250725-UQB26C-126/NDNC-8775-Mainline-20250725-UQB26C-126.zip
```


### 评论 35

**排查动作**: 发布软件版本NDNC-8775

**排查结果**: 已发布至Release2分支


**日志证据**:

```
[ This change has been released in software NDNC-8775-Release2-20250725-UQB26C-49.zip ]
Git Commit : 06028416d0a5f9acfe25a878c54c5e0d719dae93
Gerrit URL : "https://info-gerrit.apps.saic-gm.com/206079"
```


### 评论 36

**排查动作**: 发布版本并记录提交信息

**排查结果**: 版本已发布至指定标签


**日志证据**:

```
[ This change has been released in tag 557-8255-Mainline-20250725-UQB26C-980.zip ]
Git Commit : 643e0418eb0e6ca7d0ba49fe6d6ef95f1954912b
Gerrit URL : "https://info-gerrit.apps.saic-gm.com/206077"
```


### 评论 37

**排查动作**: 分析理疗模式RPC时序

**排查结果**: 单按钮触发两RPC，响应需850ms


**日志证据**:

```
rpc处理时间100ms，控制信号信号发送延时0~100ms，机电层模型周期0~100ms，座椅按摩LIN调度表280~560ms，状态信号接收延时0~100ms；总计固定100ms+浮动时间280~860ms，取80%位数---744ms，加上固定时间总计844ms，取整维护为850ms
```


### 评论 38

**排查动作**: 发布版本并记录提交信息

**排查结果**: 已发布至557-8775-Release2标签


**日志证据**:

```
[ This change has been released in tag 557-8775-Release2-20250725-UQB26C-34.zip ]
Git Commit : 06028416d0a5f9acfe25a878c54c5e0d719dae93
Gerrit URL : "https://info-gerrit.apps.saic-gm.com/206079"
```


### 评论 39

**排查动作**: 发布版本并关联代码

**排查结果**: 已发布至557-8775-Mainline


**日志证据**:

```
[ This change has been released in tag 557-8775-Mainline-20250725-UQB26C-85.zip ]
Git Commit : 643e0418eb0e6ca7d0ba49fe6d6ef95f1954912b
Gerrit URL : "https://info-gerrit.apps.saic-gm.com/206077"
```


### 评论 40

**排查动作**: 发布版本并记录提交信息

**排查结果**: 已发布至557-8255-Release2


**日志证据**:

```
[ This change has been released in tag 557-8255-Release2-20250725-UQB26C-40.zip ]
Git Commit : 6a5999498858d36bf8fd3ac6382bf1ebdfec24d8
Gerrit URL : "https://info-gerrit.apps.saic-gm.com/206335"
```


### 评论 41

**排查动作**: 发布版本并记录提交信息

**排查结果**: 已发布至557-8775-Release2


**日志证据**:

```
[ This change has been released in tag 557-8775-Release2-20250725-UQB26C-36.zip ]
Git Commit : 6a5999498858d36bf8fd3ac6382bf1ebdfec24d8
Gerrit URL : "https://info-gerrit.apps.saic-gm.com/206335"
```


### 评论 42

**排查动作**: 提交代码补丁修复

**排查结果**: UT通过，补丁已提交


**日志证据**:

```
UTResult : pass
```


### 评论 43

**排查动作**: 提交代码补丁评审

**排查结果**: UT通过，等待评审


**日志证据**:

```
UTResult : pass
```


### 评论 44

**排查动作**: 提交代码补丁审查

**排查结果**: 补丁已提交，UT通过


### 评论 45

**排查动作**: 提交代码补丁审查

**排查结果**: UT通过，等待评审


**日志证据**:

```
UTResult : pass
```


### 评论 46

**排查动作**: 发布软件版本NDNC-8775

**排查结果**: 已发布至Release2分支


**日志证据**:

```
[ This change has been released in software NDNC-8775-Release2-20250727-UQB26C-57.zip ]
Git Commit : 6a5999498858d36bf8fd3ac6382bf1ebdfec24d8
Gerrit URL : "https://info-gerrit.apps.saic-gm.com/206335"
```


### 评论 47

**排查动作**: 发布软件版本

**排查结果**: 已发布至NDNC-8775-Mainline-20250727


**日志证据**:

```
NDNC-8775-Mainline-20250727-UQB26C-131.zip
```


### 评论 48

**排查动作**: 发布版本并关联代码

**排查结果**: 已发布至557-8255-Mainline-20250728


**日志证据**:

```
[ This change has been released in tag 557-8255-Mainline-20250728-UQB26C-984.zip ]
Git Commit : dd3efe2f464fc8b78f9b74012a66f632fbf4d65c
Gerrit URL : "https://info-gerrit.apps.saic-gm.com/206334"
```


### 评论 49

**排查动作**: 发布R5-20250728版本

**排查结果**: 版本已发布至指定tag


**日志证据**:

```
[ This change has been released in tag R5-20250728-SQB25C-781.zip ]
Git Commit : 643e0418eb0e6ca7d0ba49fe6d6ef95f1954912b
Artifactory Link : http://10.203.71.4:8081/artifactory/Info4/dailybuild_R5_CLEA/
```


### 评论 50

**排查动作**: 发布R5-20250728版本

**排查结果**: 版本已发布至指定tag


**日志证据**:

```
[ This change has been released in tag R5-20250728-SQB25C-781.zip ]
Git Commit : dd3efe2f464fc8b78f9b74012a66f632fbf4d65c
Gerrit URL : "https://info-gerrit.apps.saic-gm.com/206334"
```


### 评论 51

**排查动作**: 发布版本并关联代码提交

**排查结果**: 版本已发布至指定tag


**日志证据**:

```
[ This change has been released in tag 557-8775-Mainline-20250728-UQB26C-88.zip ]
Git Commit : dd3efe2f464fc8b78f9b74012a66f632fbf4d65c
Gerrit URL : "https://info-gerrit.apps.saic-gm.com/206334"
```


### 评论 52

**排查动作**: 发布版本并记录构建信息

**排查结果**: 版本已发布至指定tag


**日志证据**:

```
[ This change has been released in tag : GBBuick_Mid_R5_F1KH-20250730-SQB24B-760]
Git Commit : 643e0418eb0e6ca7d0ba49fe6d6ef95f1954912b
Gerrit URL : "https://info-gerrit.apps.saic-gm.com/206077"
```


### 评论 53

**排查动作**: 发布版本并记录提交信息

**排查结果**: 版本已发布至指定标签


**日志证据**:

```
[ This change has been released in tag : GBBuick_Mid_R5_F1KH-20250730-SQB24B-760]
Git Commit : dd3efe2f464fc8b78f9b74012a66f632fbf4d65c
Gerrit URL : "https://info-gerrit.apps.saic-gm.com/206334"
```


### 评论 54

**排查动作**: 发布版本并记录提交信息

**排查结果**: 版本已发布至指定标签


**日志证据**:

```
[ This change has been released in tag : GBBuick_Mid_R5_F1KM-20250730-SQB24B-345]
Git Commit : 643e0418eb0e6ca7d0ba49fe6d6ef95f1954912b
Gerrit URL : "https://info-gerrit.apps.saic-gm.com/206077"
```


### 评论 55

**排查动作**: 发布版本并附构建信息

**排查结果**: 版本已发布至指定tag


**日志证据**:

```
[ This change has been released in tag : GBBuick_Mid_R5_F1KM-20250730-SQB24B-345]
Git Commit : dd3efe2f464fc8b78f9b74012a66f632fbf4d65c
Artifactory Link : http://10.203.71.4:8081/artifactory/Info4/dailybuild_GBBuick_R5/
```

