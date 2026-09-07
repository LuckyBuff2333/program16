# VCU-416584 评论分析总结

## 排查结论

NLU语义解析正常，但“智慧顶灯”被设计为按阅读灯控制，VRDM层映射逻辑待确认，问题已定位为设计逻辑，待WAD推送后关闭。


**排查摘要**：NLU语义解析正常，但“智慧顶灯”被设计为按阅读灯控制，VRDM层映射逻辑待确认，问题已定位为设计逻辑


## 排查过程分析

### 问题现象
语音指令“打开智慧顶灯”被错误映射为RGB氛围灯控制，实际执行时打开的是阅读灯，而非智慧顶灯。

### 排查过程
| 步骤 | 排查动作 | 结果 | 关键证据 |
|------|----------|------|----------|
| 1 | 上传复现视频与日志 | 提供问题复现素材 | 评论1：上传复现视频与日志 |
| 2 | 复制工作项1237240 | 无新增排查，仅复制记录 | 评论2：复制工作项1237240 |
| 3 | 上传gmlogger日志分卷 | 已添加4个日志附件 | 评论3：已添加4个日志附件 |
| 4 | 语义下发日志分析 | 语义解析正常，需VRDM确认 | 评论4：01-06 13:55:12.440 on process nlu -> to |
| 5 | 查看日志55890-55944行 | 确认NLU处理流程正常 | 评论5：Line 55890/55943/55944 on proc/builder/system |
| 6 | 确认设计逻辑 | 按阅读灯控制，设计如此 | 评论6：按阅读灯控制，设计如此 |
| 7 | 请求推送WAD问题 | 待确认后关闭 | 评论7：请求推送WAD问题 |

### 排查结论
- **已确认的事实**：NLU语义解析正常（评论4证据：`on process nlu -> to`）；设计逻辑确认为按阅读灯控制（评论6）；日志中NLU处理流程完整（评论5：Line 55890-55944）。
- **尚未确认需进一步排查的方向**：VRDM（语音交互设备管理）层对“智慧顶灯”指令的最终映射逻辑；WAD问题推送后的处理结果；`object`字段语义降级及槽位值截断问题需在VRDM层进一步验证。
- **与AI日志分析结论的一致点和差异点**：一致点——均确认NLU意图解析正确，问题出在指令映射层；差异点——AI分析指出`object`字段语义降级和槽位值截断是错误映射的关键条件，而人工排查未涉及该细节，且AI认为“打开的是阅读灯”与人工确认的“按阅读灯控制”设计逻辑一致，但AI未提及设计如此这一结论。


## 时序排查详情

### AI日志分析

- Critical：车控指令映射错误：语音指令"打开智慧顶灯"被映射为 `SetRGBAmbientLight`（RGB 氛围灯控制），而非顶灯开关控制，直接导致打开的是阅读灯（L883、L1051、L1084）
- Critical：object 字段语义降级：车控指令 JSON 中 `object` 字段被映射为宽泛的"车内灯"，丢失了"智慧顶灯"的具体语义，为错误映射创造了条件（L324）
- Important：NLU 槽位值被截断：`pos:[2,5]` 对象槽位的完整 value 值在日志中被截断，无法确认 NLU 将"智慧顶灯"解析为何种对象标识符，阻碍了精确定位映射错误发生的层级（L294）
- Important：顶灯信号关联性不明：`BasePatacDomeLampSignal` 的 `onDomeLightStatusChanged value=2` 事件发生在语音指令后约 10 秒，无法确认是否与本次指令相关（L58639）
- Info：ASR 与 NLU 意图解析正确：语音识别文本和意图解析均正确，排除了语音识别层和意图分类层的错误（L267）

### 评论 1

**排查动作**: 上传复现视频与日志

**排查结果**: 提供问题复现素材


### 评论 2

**排查动作**: 复制工作项1237240

**排查结果**: 无新增排查，仅复制记录


### 评论 3

**排查动作**: 上传gmlogger日志分卷

**排查结果**: 已添加4个日志附件


### 评论 4

**排查动作**: 语义下发日志分析

**排查结果**: 语义解析正常，需VRDM确认


**日志证据**:

```
01-06 13:55:12.440  5220 14836 D sgm.voice.server_local8155_1.4.3.5_2025-12-31: on process nlu -> topic:sys.car.crl, data:{"light_type_inside":"智慧顶灯","object_raw":"智慧顶灯","customInnerType":"nativeCommand","action":"打开","object":"车内灯"}
```


### 评论 5

**排查动作**: (Comment from 马

**排查结果**: (Comment from 马云鹏)
看


**日志证据**:

```
Line  55890: 01-06 13:55:23.269  5220 14667 D sgm.voice.server_local8155_1.4.3.5_2025-12-31: on process nlu -> topic:sys.car.crl, data:{"light_type_inside":"智慧顶灯","object_raw":"智慧顶灯","customInnerType":"nativeCommand","action":"关闭","object":"车内灯","context":{"nlgLanguageClass":"Chinese","rec":"实际它打开的是阅读灯而不是我的这个智慧顶灯智慧顶灯是关闭状态。","tedVadInfo":[{"text":"实际它打开的是阅读灯","recLeftMargin":427,"endStatus":true},{"text":"实际它打开的是阅读灯而不是我的这个","recLeftMargin":495,"endStatus":true},{"text":"实际它打开的是阅读灯而不是我的这个智慧顶灯智慧顶灯是关闭状态","recLeftMargin":146,"endStatus":true}],"wordsEnd":true,"currentIntentName":"复杂车控"},"dmInput":"实际它打开的是阅读灯而不是我的这个智慧顶灯智慧顶灯是关闭状态","dmInputSimple":"实际它打开的是阅读灯而不是我的这个智慧顶灯智慧顶灯是关闭状态","intentName":"复杂车控","widgetParams":{"llmTaskname":"复杂车控","carCtlRefineText":"关闭智慧顶灯","intentName":"复杂车控","skillId":"2024031500000086","skillName":"中枢大模型技能","taskName":"复杂车控"},"recordId":"158849235d384360a9c97c49278b09f7:b8e2c5d7f81d4ace9abfb21093d83dd0:3e65771b5e8649b3b862f01de4794f57","skillId":"2024031500000086","skillName":"中枢大模型技能","taskName":"复杂车控","hasFrontTask":false}
Line  55943: 01-06 13:55:23.280  5220 14667 D sgm.voice.server_local8155_1.4.3.5_2025-12-31: builder:Builder{domain=car, intent=dome.light.switch, slots=Bundle[{action=close}]}
Line  55944: 01-06 13:55:23.280  5220 14667 D sgm.voice.server_local8155_1.4.3.5_2025-12-31: system version -> NDNC-LOCAL8155_R4-UQB26C-20260105-29
Line  55946: 01-06 13:55:23.280  5220 14667 D sgm.voice.server_local8155_1.4.3.5_2025-12-31: car bot process dialogue round --> intent:dome.light.switch target:RIGHT_FRONT command:Builder{domain=car, intent=dome.light.switch, slots=Bundle[{action=close}]}
Line  55947: 01-06 13:55:23.280  5220 14667 D sgm.voice.server_local8155_1.4.3.5_2025-12-31: demo light action  open --> false target -->ALL
Line  55948: 01-06 13:55:23.280  5220 14667 D sgm.voice.server_local8155_1.4.3.5_2025-12-31: directionHelper --> 45direction --> 63
Line  55950: 01-06 13:55:23.280  5220 14667 D sgm.voice.server_local8155_1.4.3.5_2025-12-31: read calibration --> name:阅读灯功能是否支持 id:P_VEHICLE_CONTROL_DOME_LIGHT_ENABLE value:1
Line  55962: 01-06 13:55:23.283  5220 14667 D sgm.voice.server_local8155_1.4.3.5_2025-12-31: getPropertyType=class java.lang.Integer
Line  55970: 01-06 13:55:23.285  5220 14667 D sgm.voice.server_local8155_1.4.3.5_2025-12-31: 0x214011f2(557847026) read -> area:16777216 value:1
Line  55971: 01-06 13:55:23.285  5220 14667 D sgm.voice.server_local8155_1.4.3.5_2025-12-31: domeEnable --> 1 domeAvailable --> 1
Line  55972: 01-06 13:55:23.286  5220 14667 D sgm.voice.server_local8155_1.4.3.5_2025-12-31: getPropertyType=class java.lang.Integer
Line  55984: 01-06 13:55:23.289  5220 14667 D sgm.voice.server_local8155_1.4.3.5_2025-12-31: 0x214011f3(557847027) read -> area:16777216 value:1
Line  55985: 01-06 13:55:23.289  5220 14667 D sgm.voice.server_local8155_1.4.3.5_2025-12-31: values : 1
Line  55986: 01-06 13:55:23.289  5220 14667 D sgm.voice.server_local8155_1.4.3.5_2025-12-31: 0x214101d5(557908437) write -> area:16777216 value:[0, 2]
Line  58380: 01-06 13:55:23.797  5220 14667 D sgm.voice.server_local8155_1.4.3.5_2025-12-31: 0x214101d5(557908437) write -> area:16777216 value:[0, 0]
Line  58423: 01-06 13:55:23.804  5220 14667 D sgm.voice.server_local8155_1.4.3.5_2025-12-31: com.sgm.voice.dm.session.DialogueRound@ce9ce72 add dialogue round result:1
Line  58438: 01-06 13:55:23.806  5220 14667 D sgm.voice.server_local8155_1.4.3.5_2025-12-31: read calibration --> name:是否支持第三空间虚拟控制 id:P_INTELLIGENCE_DOME_LIGHT_SWITCH_ENABLE value:true
Line  58440: 01-06 13:55:23.806  5220 14667 D sgm.voice.server_local8155_1.4.3.5_2025-12-31: P_INTELLIGENCE_DOME_LIGHT_SWITCH_ENABLE : true
Line  58994: 01-06 13:55:23.926  5220 14667 D sgm.voice.server_local8155_1.4.3.5_2025-12-31: BodyLightingInterior状态码 --> 0
Line  59125: 01-06 13:55:23.958  5220 14667 D sgm.voice.server_local8155_1.4.3.5_2025-12-31: IntelligenceDomeLightProcessor  available ->true
Line  59138: 01-06 13:55:23.958  5220 14667 D sgm.voice.server_local8155_1.4.3.5_2025-12-31: IntelligenceDomeLightProcessor  mode ->IDLM_OFF brightness --> 0
Line  59151: 01-06 13:55:23.961  5220 14667 D sgm.voice.server_local8155_1.4.3.5_2025-12-31: dcp properties -> {"G617":"{\"domain\":\"car\",\"intent\":\"dome.light.switch\",\"slots\":[{\"name\":\"action\",\"value\":\"close\"},{\"name\":\"target\",\"value\":\"ALL\"}]}","G110":"{\"domain\":\"car\",\"intent\":\"dome.light.switch\",\"results\":[{\"code\":1,\"slots\":[{\"name\":\"direction\",\"value\":\"32767\"}]}]}","G111":"681"}
Line  59158: 01-06 13:55:23.963  5220 14667 D sgm.voice.server_local8155_1.4.3.5_2025-12-31: read calibration --> name:语音源类型 id:P_PATAC_INT_RESERVED21 value:1
Line  59159: 01-06 13:55:23.963  5220 14667 D sgm.voice.server_local8155_1.4.3.5_2025-12-31: hatch dictionaries -> [{"priority":0,"tone":"","words":{}}]
Line  59160: 01-06 13:55:23.963  5220 14667 D sgm.voice.server_local8155_1.4.3.5_2025-12-31: hatch tts -> 搞定
```


### 评论 6

**排查动作**: 确认设计逻辑

**排查结果**: 按阅读灯控制，设计如此


### 评论 7

**排查动作**: 请求推送WAD问题

**排查结果**: 待确认后关闭

