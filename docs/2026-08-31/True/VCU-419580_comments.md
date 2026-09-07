# VCU-419580 评论分析总结

## 排查结论

主驾阅读灯亮度调节在0118/0127版本均失败，NLU语义解析正常，问题疑在推理层，已定位待进一步排查。


## 排查过程分析

### 问题现象
实车语音控制主驾阅读灯亮度调节功能在多个版本（0118、0127）中验证失败，系统提示异常，无法完成亮度调节。

### 排查过程

| 步骤 | 排查动作 | 结果 | 关键证据 |
|------|----------|------|----------|
| 1 | 复制工作项1244983 | 无新动作，仅复制 | 评论1 |
| 2 | 上传实车日志与视频 | 提供复现素材 | 评论2 |
| 3 | 查看NLU处理日志 | 语义处理中 | 01-17 14:47:24.211 sgm.voice.server_local8155 |
| 4 | 提交工单并预期上线 | 已提单，预期0119上线 | 评论4 |
| 5 | 添加附件图片 | 已添加附件2544861 | 评论5 |
| 6 | 验证0118版本 | 验证不通过 | 评论6 |
| 7 | 0119凌晨上线操作 | 完成上线部署 | 评论7 |
| 8 | 拉取日志给下游分析 | 语义已正确，待分析 | 评论8 |
| 9 | 请求协助抓取日志 | 暂无可用实车 | 评论9 |
| 10 | 上传实车复现视频 | 已添加附件2549527 | 附件 2549527 (1389280793.mp4) |
| 11 | 上传实车日志附件 | 提供gmlogger及时间戳日志 | gmlogger_2026_1_21_13_13_8.zip.001~003 |
| 12 | 重新上传附件 | 已重新上传附件 | 评论12 |
| 13 | 查看推理层日志 | 处理中 | Line 73142: 01-21 13:12:21.956 sgm.voice.server_local8155_1.4.5.2 |
| 14 | 添加截图附件 | 已添加截图附件 | 评论14 |
| 15 | 分析语音调灯日志 | 反馈不能调节主驾阅读灯亮度 | 01-21 13:11:39.632 W AIN-DuiInputerJar: feedbackNativeCommandResult |
| 16 | 审查commit15日志配置 | 智慧顶灯误入座舱主题灯光 | "light_type_inside": "智慧顶灯"，mode= "第三空间" |
| 17 | 修改api参数并验证 | 已修改sys.car.crl，待内部验证 | "api" : "sys.car.crl" 已修改 |
| 18 | 实车验证0127版本 | 验证失败，提示异常 | 版本：0127集成版本，验证次数：30，结果：Fail |
| 19 | 上传三份main日志 | 已添加附件，待分析 | 附件 2564213~2564215 (main.log_2026_1_27_*.gz) |
| 20 | 确认日志缺失 | 无当前querylog，需测试确认 | 评论20 |
| 21 | 核对语义下发一致性 | 语义下发与需求一致 | 收到SGM车载控制


## 时序排查详情

### AI日志分析

- 目标灯光区域存在性校验失败：系统检测到目标灯光区域 `exist=false`，导致调节请求未发出或未生效（13:12:21，推理层摘要）
- 裁决层 LLM 调用失败：裁决层无法生成正式结论，仅能提供兜底输出（分析时点，裁决层）
- 日志规模巨大：日志文件超过 226 万行，增加了人工排查难度（分析时点，日志文件）

### 评论 1

**排查动作**: 复制工作项1244983

**排查结果**: 无新排查动作，仅复制


### 评论 2

**排查动作**: 上传实车日志与视频附件

**排查结果**: 提供复现素材，待分析


### 评论 3

**排查动作**: (Comment from 楚

**排查结果**: (Comment from 楚志远)
协


**日志证据**:

```
01-17 14:47:24.211  5272 17298 D sgm.voice.server_local8155_1.4.5.0_2026-01-14: on process nlu -> topic:sys.car.crl, data:{"light_type_inside":"智慧顶灯","part_raw":"亮度","customInnerType":"nativeCommand","part":"亮度","value":"+20\/100","object":"车内灯","context":{"nlgLanguageClass":"Chinese","rec":"座舱主题灯光亮度调高20%。","keepListening":0,"wordsEnd":false,"keepSession":300,"currentIntentName":"车身控制"},"dmInput":"座舱主题灯光亮度调高百分之二十","dmInputSimple":"座舱主题灯光亮度调高百分之二十","intentName":"车身控制","widgetParams":{"yt_debug_logBus":{"yt_classify_result":"vehicle_control","aispeech_classify_result":"SGM车载控制","choose_result":"aispeech"},"intentName":"车身控制","skillId":"2025071500000012","skillName":"SGM车载控制","taskName":"车载控制"},"recordId":"4346c0e6969c4185836bf56ee20fccfa:30c1705eb83d4ba38881b276a2701a3e:35a27f79778e4780a08f326f0299a489","skillId":"2025071500000012","skillName":"SGM车载控制","taskName":"车载控制","hasFrontTask":false}
```


### 评论 4

**排查动作**: 提交工单并预期上线

**排查结果**: 已提单，预期0119上线


### 评论 5

**排查动作**: 添加附件图片

**排查结果**: 已添加附件2544861


### 评论 6

**排查动作**: 验证0118版本

**排查结果**: 验证不通过


### 评论 7

**排查动作**: 0119凌晨上线操作

**排查结果**: 完成上线部署


### 评论 8

**排查动作**: 拉取日志给下游分析

**排查结果**: 语义已正确，待分析


### 评论 9

**排查动作**: 请求协助抓取日志

**排查结果**: 暂无可用实车，需原始车辆日志


### 评论 10

**排查动作**: 上传实车复现视频

**排查结果**: 已添加附件2549527


**日志证据**:

```
附件 2549527 (1389280793.mp4)
```


### 评论 11

**排查动作**: 上传实车日志附件

**排查结果**: 提供gmlogger及时间戳日志


**日志证据**:

```
gmlogger_2026_1_21_13_13_8.zip.001
gmlogger_2026_1_21_13_13_8.zip.002
gmlogger_2026_1_21_13_13_8.zip.003
gmlogger_2026_1_21_13_13_8.zip.004
2 1-21-2026 1-12-44 pm.zip
```


### 评论 12

**排查动作**: 重新上传附件

**排查结果**: 已重新上传附件


### 评论 13

**排查动作**: (Comment from 马

**排查结果**: (Comment from 马云鹏)
看


**日志证据**:

```
Line  73142: 01-21 13:12:21.956  5477 10851 D sgm.voice.server_local8155_1.4.5.2_2026-01-16: on process nlu -> topic:sys.car.crl, data:{"light_type_inside":"智慧顶灯","customInnerType":"nativeCommand","part_raw":"亮度","part":"亮度","action_concrete":"true","value":"+50\/100","object":"车内灯","context":{"nlgLanguageClass":"Chinese","rec":"座舱主题亮主题灯光亮度调高50%。","tedVadInfo":[{"text":"座舱主题亮","recLeftMargin":476,"endStatus":true},{"text":"座舱主题亮主题灯光亮度调高百分之五十","recLeftMargin":369,"endStatus":true}],"wordsEnd":true},"dmInput":"座舱主题亮主题灯光亮度调高百分之五十","dmInputSimple":"座舱主题亮主题灯光亮度调高百分之五十","intentName":"","widgetParams":{"llmTaskname":"复杂车控","yt_debug_logBus":{"yt_classify_result":"vehicle_control","aispeech_classify_result":"SGM车载控制","asr_sentence_cost":103,"choose_result":"aispeech"},"carCtlRefineText":"智慧顶灯亮度调高百分之五十","intentName":"","skillId":"2024031500000086","skillName":"中枢大模型技能","taskName":"复杂车控"},"recordId":"14e3c70533014b0bb9d76fadf24c25b9:cf6aa76def7941188ef551b78f05c300:888d4cad437b4c78982440ab3235eb43","skillId":"2024031500000086","skillName":"中枢大模型技能","taskName":"复杂车控","hasFrontTask":false}
```


### 评论 14

**排查动作**: 添加截图附件

**排查结果**: 已添加截图附件


### 评论 15

**排查动作**: 分析语音调灯日志

**排查结果**: 反馈不能调节主驾阅读灯亮度


**日志证据**:

```
01-21 13:11:39.632  5477 30257 W AIN-DuiInputerJar: feedbackNativeCommandResult with: nativeCommand = sys.car.crl, feedbackJO = {"nlg":"不能调节主驾阅读灯亮度哦","customNativeCommandResult":{"exeResult":"5000","toastContent":""}}
```


### 评论 16

**排查动作**: 审查commit15日志配置

**排查结果**: 智慧顶灯误入座舱主题灯光


**日志证据**:

```
"light_type_inside": "智慧顶灯"
mode= "第三空间"
```


### 评论 17

**排查动作**: 修改api参数并验证

**排查结果**: 已修改sys.car.crl，待内部验证


**日志证据**:

```
"api" : "sys.car.crl" 已修改
```


### 评论 18

**排查动作**: 实车验证0127版本

**排查结果**: 验证失败，提示异常


**日志证据**:

```
版本：0127集成版本
验证次数：30
验证结果：Fail
log时间在13：35
```


### 评论 19

**排查动作**: 上传三份main日志

**排查结果**: 已添加附件，待分析


**日志证据**:

```
附件 2564213 (25-main.log_2026_1_27_13_35_20.gz)
附件 2564214 (26-main.log_2026_1_27_13_36_5.gz)
附件 2564215 (24-main.log_2026_1_27_13_34_48.gz)
```


### 评论 20

**排查动作**: 确认日志缺失

**排查结果**: 无当前querylog，需测试确认


### 评论 21

**排查动作**: 核对语义下发一致性

**排查结果**: 语义下发与需求一致


**日志证据**:

```
收到SGM车载控制command:sys.car.crl?{"part_raw":"亮度","action_concrete":"true","part":"亮度","customInnerType":"nativeCommand","value":"+20/100","object":"车内灯","mode":"第三空间"}
200260127 语义下发与需求一致
```


### 评论 22

**排查动作**: 实车复测0128版本

**排查结果**: 验证失败，提示重试


**日志证据**:

```
log时间在10：57
```


### 评论 23

**排查动作**: 上传三份main日志

**排查结果**: 待分析日志已提供


**日志证据**:

```
附件 2566913 (20-main.log_2026_1_28_10_57_38.gz)
附件 2566914 (21-main.log_2026_1_28_10_58_35.gz)
附件 2566915 (19-main.log_2026_1_28_10_56_45.gz)
```


### 评论 24

**排查动作**: 添加附件截图

**排查结果**: 已添加截图附件


### 评论 25

**排查动作**: 请求测试同学提供有效log

**排查结果**: log无法解压，需重新提供


### 评论 26

**排查动作**: 云端验证命令有效性

**排查结果**: 命令有效，可正常下发


**日志证据**:

```
收到SGM车载控制command:sys.car.crl?{"object":"车内灯","customInnerType":"nativeCommand","value":"+30/100","mode":"第三空间","part":"亮度","part_raw":"亮度","action_concrete":"true"}
```


### 评论 27

**排查动作**: 实车复测0129版本

**排查结果**: 验证失败，车机无法控制


**日志证据**:

```
8775实车验证，车机回复我暂时无法控制，稍后再试试吧，log时间再11：36
```


### 评论 28

**排查动作**: 上传三份main日志

**排查结果**: 已添加附件待分析


**日志证据**:

```
附件 2571229 (41-main.log_2026_1_29_11_36_8.gz)
附件 2571230 (42-main.log_2026_1_29_11_37_0.gz)
附件 2571231 (40-main.log_2026_1_29_11_35_22.gz)
```


### 评论 29

**排查动作**: (Comment from 曹

**排查结果**: (Comment from 曹达)
na


**日志证据**:

```
01-29 11:36:12.848  6463 25433 D sgm.voice.server_vcupro_1.4.6.2_2026-01-28: on process nlu -> topic:sys.car.crl, data:{"mode":"第三空间","customInnerType":"nativeCommand","part_raw":"亮度","part":"亮度","action_concrete":"true","value":"+","object":"车内灯","context":{"nlgLanguageClass":"Chinese","rec":"座舱主题灯光亮度调高","keepListening":0,"tedVadInfo":[{"text":"座舱主题灯光亮度调高","recLeftMargin":611,"endStatus":true}],"wordsEnd":true,"keepSession":300,"currentIntentName":"车身控制"},"dmInput":"座舱主题灯光亮度调高","dmInputSimple":"座舱主题灯光亮度调高","intentName":"车身控制","widgetParams":{"yt_debug_logBus":{"yt_classify_result":"vehicle_control","aispeech_classify_result":"SGM车载控制","asr_sentence_cost":56,"llm_choose_cost":441,"choose_result":"aispeech"},"intentName":"车身控制","skillId":"2025071500000012","skillName":"SGM车载控制","taskName":"车载控制"},"recordId":"99b389bacac342009b0d0c2f24c96631:bab45257554f4e89b5c6f4461d1ed649:26af8f3a92394825853450816d141e46","skillId":"2025071500000012","skillName":"SGM车载控制","taskName":"车载控制","hasFrontTask":false}
```


### 评论 30

**排查动作**: (Comment from 马

**排查结果**: (Comment from 马云鹏)
看


**日志证据**:

```
Line  24000: 01-29 11:36:12.848  6463 25433 D sgm.voice.server_vcupro_1.4.6.2_2026-01-28: on process nlu -> topic:sys.car.crl, data:{"mode":"第三空间","customInnerType":"nativeCommand","part_raw":"亮度","part":"亮度","action_concrete":"true","value":"+","object":"车内灯","context":{"nlgLanguageClass":"Chinese","rec":"座舱主题灯光亮度调高","keepListening":0,"tedVadInfo":[{"text":"座舱主题灯光亮度调高","recLeftMargin":611,"endStatus":true}],"wordsEnd":true,"keepSession":300,"currentIntentName":"车身控制"},"dmInput":"座舱主题灯光亮度调高","dmInputSimple":"座舱主题灯光亮度调高","intentName":"车身控制","widgetParams":{"yt_debug_logBus":{"yt_classify_result":"vehicle_control","aispeech_classify_result":"SGM车载控制","asr_sentence_cost":56,"llm_choose_cost":441,"choose_result":"aispeech"},"intentName":"车身控制","skillId":"2025071500000012","skillName":"SGM车载控制","taskName":"车载控制"},"recordId":"99b389bacac342009b0d0c2f24c96631:bab45257554f4e89b5c6f4461d1ed649:26af8f3a92394825853450816d141e46","skillId":"2025071500000012","skillName":"SGM车载控制","taskName":"车载控制","hasFrontTask":false}
Line  24006: 01-29 11:36:12.851  6463 25433 D sgm.voice.server_vcupro_1.4.6.2_2026-01-28: builder:Builder{domain=car, intent=third.space.brightness, slots=Bundle[{action=increase}]}
Line  24007: 01-29 11:36:12.851  6463 25433 D sgm.voice.server_vcupro_1.4.6.2_2026-01-28: system version -> NDNC-8775-Release4-20260129-UQB26C-77
Line  24008: 01-29 11:36:12.851  6463 25433 D sgm.voice.server_vcupro_1.4.6.2_2026-01-28: car bot process dialogue round --> intent:third.space.brightness target:MAIN command:Builder{domain=car, intent=third.space.brightness, slots=Bundle[{action=increase}]}
Line  24009: 01-29 11:36:12.852  6463 25433 D sgm.voice.server_vcupro_1.4.6.2_2026-01-28: read calibration --> name:是否支持第三空间虚拟控制 id:P_INTELLIGENCE_DOME_LIGHT_SWITCH_ENABLE value:true
Line  24011: 01-29 11:36:12.853  6463 25433 D sgm.voice.server_vcupro_1.4.6.2_2026-01-28: read calibration --> name:是否支持第三空间亮度虚拟控制 id:P_INTELLIGENCE_DOME_LIGHT_BRIGHTNESS_ENABLE value:true
Line  24016: 01-29 11:36:12.854  6463 25433 D sgm.voice.server_vcupro_1.4.6.2_2026-01-28: IGNITION_STATE(289408009) read -> area:16777216 value:4 status:0
Line  24101: 01-29 11:36:12.869  6463 25433 D sgm.voice.server_vcupro_1.4.6.2_2026-01-28: IntelligenceDomeLightStatus read 状态码 --> 0
Line  24103: 01-29 11:36:12.869  6463 25433 D sgm.voice.server_vcupro_1.4.6.2_2026-01-28: ThirdSpaceSwitchProcessor available --> false
Line  24104: 01-29 11:36:12.869  6463 25433 D sgm.voice.server_vcupro_1.4.6.2_2026-01-28: com.sgm.voice.dm.session.DialogueRound@d375c94 add dialogue round result:1002
Line  24106: 01-29 11:36:12.869  6463 25433 D sgm.voice.server_vcupro_1.4.6.2_2026-01-28: com.sgm.voice.dm.session.DialogueRound@d3fb33d add dialogue round result:1002
Line  24108: 01-29 11:36:12.869  6463 25433 D sgm.voice.server_vcupro_1.4.6.2_2026-01-28: dcp properties -> {"G617":"{\"domain\":\"car\",\"intent\":\"third.space.brightness\",\"slots\":[{\"name\":\"action\",\"value\":\"increase\"}]}","G110":"{\"domain\":\"car\",\"intent\":\"third.space.brightness\",\"results\":[{\"code\":1002,\"slots\":[{\"name\":\"direction\",\"value\":\"45\"}]}]}","G111":"18"}
Line  24114: 01-29 11:36:12.870  6463 25433 D sgm.voice.server_vcupro_1.4.6.2_2026-01-28: read calibration --> name:语音源类型 id:P_PATAC_INT_RESERVED21 value:1
Line  24115: 01-29 11:36:12.870  6463 25433 D sgm.voice.server_vcupro_1.4.6.2_2026-01-28: hatch dictionaries -> [{"priority":0,"text":"我暂时无法控制，晚点再试试吧","tone":"","words":{}}]
Line  24116: 01-29 11:36:12.870  6463 25433 D sgm.voice.server_vcupro_1.4.6.2_2026-01-28: hatch tts -> 我暂时无法控制，晚点再试试吧
```


### 评论 31

**排查动作**: 请求实车验证

**排查结果**: 等待支持车型验证


### 评论 32

**排查动作**: 请求验证修复

**排查结果**: 语义下发正确但手动调节仍报错


### 评论 33

**排查动作**: 确认修复状态

**排查结果**: 问题已修复

