# VCU-419146 评论分析总结

## 排查结论

已定位：NLU链路在“无此位置”场景误触发香氛弹窗及引导语，且存在多skillId跳转，非UE设计缺陷，需进一步排查链路逻辑。


**排查摘要**：已定位：NLU链路在“无此位置”场景误触发香氛弹窗及引导语，且存在多skillId跳转，非UE设计缺陷


## 排查过程分析

### 问题现象
用户询问"XX位置有没有香氛"时，系统错误弹出香氛轻量化弹窗并播报引导语"还不支持这个位置哦，现在只有这些香氛哦"，而需求要求仅反馈"没有这个位置"且不弹窗。

### 排查过程
| 步骤 | 排查动作 | 结果 | 关键证据 |
|------|----------|------|----------|
| 1 | 上传实车视频与日志 | 已提供复现素材待分析 | gmlogger_2026_1_16_13_55_2.part01-03.rar |
| 2 | 复制工作项1244590 | 无新增排查动作 | 评论2无实质内容 |
| 3 | 查看NLU处理日志 | 确认进入NLU处理流程 | "01-16 13:39:11.880 on process nlu -> to" |
| 4 | 确认播报结果 | 播报符合预期，需与测试澄清 | 评论4结论 |
| 5 | 添加截图附件 | 已添加截图供参考 | 评论5附件 |
| 6 | 确认UE设计 | 设计如此，非缺陷 | 评论6贴图确认 |

### 排查结论
- **已确认的事实**：① 13:40:44.110 AIN-MultiDisplaySkillJsonUtil 在"无此位置"场景下 isNeedShow 返回 true，主动触发弹窗；② 最终 TTS 为"还不支持这个位置哦，现在只有这些香氛哦"，含引导语；③ 同一链路出现三个 skillId（2025072900000027→2024031500000086→2025071500000012）；④ CLEAFragranceDiffuserRequestProcessor 全程未收到香氛控制请求。
- **尚未确认需进一步排查的方向**：① exeResult=1020 错误码具体含义（需 lookup_error_code 确认）；② 第二次 NLU 解析延迟 34 秒是否触发中枢大模型兜底逻辑；③ 多 skill 切换机制及最终决策者归属。
- **与AI日志分析结论的一致点和差异点**：一致点——均确认弹窗触发逻辑缺陷（isNeedShow 返回 true）及错误 TTS 文本产出；差异点——AI 分析认为"设计如此非缺陷"的结论与日志证据冲突，且 AI 未识别出"第二次 NLU 解析延迟 34 秒"这一关键时序问题，而人工评论中未提及该延迟现象。


## 时序排查详情

### AI日志分析

- Critical — 弹窗触发逻辑缺陷：AIN-MultiDisplaySkillJsonUtil 在"无此位置"场景下 isNeedShow 返回 true，主动触发香氛轻量化弹窗，与需求"仅反馈没有这个位置、不弹窗"直接冲突（13:40:44.110，AIN-MultiDisplaySkillJsonUtil）。
- Critical — 错误 TTS 文本产出：最终 TTS 为"还不支持这个位置哦，现在只有这些香氛哦"，包含"从这些香型里挑一个"的引导语，而需求要求仅反馈"没有这个位置"（13:40:44.110，skillId=2025071500000012）。
- Important — 多 skill 竞争/切换：同一交互链路中出现三个不同 skillId（2025072900000027 → 2024031500000086 → 2025071500000012），skill 切换机制未追踪到，最终决策者不明确（13:40:06.242 ~ 13:40:44.110）。
- Important — 第二次 NLU 解析延迟 34 秒：13:40:40 出现第二次 NLU 解析，距首次指令约 34 秒，可能触发了中枢大模型兜底逻辑（13:40:40.130，PID 4619）。
- Info — 车辆端未收到指令：CLEAFragranceDiffuserRequestProcessor 全程未收到香氛控制请求，问题不在 ECU 执行层（13:38:34，PID 4750）。
- Info — exeResult=1020 含义未确认：该错误码可能对应"通道不存在"类错误，但未通过 lookup_error_code 确认（13:40:06.235，PID 4619）。

### 评论 1

**排查动作**: 上传实车视频与日志

**排查结果**: 已提供复现素材待分析


**日志证据**:

```
gmlogger_2026_1_16_13_55_2.part01.rar
gmlogger_2026_1_16_13_55_2.part02.rar
gmlogger_2026_1_16_13_55_2.part03.rar
gmlogger_2026_1_16_13_55_2.part04.rar
第五一 1-16-2026 1-39-38 pm.rar
```


### 评论 2

**排查动作**: 复制工作项1244590

**排查结果**: 无新增排查动作


### 评论 3

**排查动作**: (Comment from 楚

**排查结果**: (Comment from 楚志远)
协


**日志证据**:

```
01-16 13:39:11.880  4597 29980 D sgm.voice.server_local8155_1.4.5.0_2026-01-14: on process nlu -> topic:sys.car.crl, data:{"customInnerType":"nativeCommand","part":"香味","action_concrete":"true","action":"调节","value":"5","object":"香氛","context":{"nlgLanguageClass":"Chinese","rec":"香氛通道调到第五个","keepListening":0,"tedVadInfo":[{"text":"香氛通道调到第五个","recLeftMargin":322,"endStatus":true}],"wordsEnd":true,"keepSession":300,"currentIntentName":"车身控制"},"dmInput":"香氛通道调到第五个","dmInputSimple":"香氛通道调到第五个","intentName":"车身控制","widgetParams":{"yt_debug_logBus":{"aispeech_classify_result":"SGM车载控制","choose_result":"aispeech"},"intentName":"车身控制","skillId":"2025071500000012","skillName":"SGM车载控制","taskName":"车载控制"},"recordId":"25660c23875e45d8b30dad52e0fe7b56:da42b8d59f994def9f7ed5c93034503a:665477c9ab49436ca0a9adc2566772dc","skillId":"2025071500000012","skillName":"SGM车载控制","taskName":"车载控制","hasFrontTask":false}
```


### 评论 4

**排查动作**: 播报结果确认

**排查结果**: 播报符合预期，需与测试澄清


### 评论 5

**排查动作**: 添加附件截图

**排查结果**: 已添加截图附件


### 评论 6

**排查动作**: 确认UE设计并贴截图

**排查结果**: 设计如此，非缺陷

