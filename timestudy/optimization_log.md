# 触发时间提取优化日志

本文档只记录**通用时间提取逻辑**的变更：触发时间提取、OCR、视频帧、gmlogger、时间匹配、时间来源标签、提取失败原因。
前端页面、看板、批量执行队列、健康检查、ADP、人工审核等非时间提取内容不写入本文档。

## 当前时间提取逻辑

### 批量提取顺序

- **Closed**：评论区 → 视频 OCR → 文本/评论 → 图片 OCR → 附件名兜底
- **非 Closed**：视频 OCR → 文本/评论 → 图片 OCR → 附件名兜底
- 单个 Jira 命中即停止；多个 Jira 并行提取。
- 无视频、无图片、无日志包：`无有效附件`。
- 有附件但所有来源未命中：`未提取到时间`。

### 视频帧 OCR

- 先 OCR 顶部状态栏/右下任务栏 ROI；命中时间则跳过整帧 OCR。
- 视频帧固定 6 帧：`0、1、2、3、5、8` 秒。
- 状态栏 ROI 放大 2.5x；整帧大图缩放到约 2MP。
- 时间匹配容差 900 秒（15 分钟）。
- 12/24 小时歧义、日期拼接、gmlogger/附件名候选都会保留，不直接丢弃。
- 整帧 OCR 仍执行完整识别，但识别结果只保留时间/日期相关文本块；过滤前走时间兼容预处理，并保留年份、日期、相对日期、AM/PM 上下文。
- 若整帧没有任何时间相关块，保留原始 OCR 文本供后续修复/解析，避免把“OCR 有文本但正则未命中”误判为空。
- 视频 OCR 未通过日志包校验时，递归解压压缩包（单文件夹逐层向下，最多 3 层）取 main 文件名时间；按最大小时簇中位数/时分最近选择，并保留该结果不被外层附件名覆盖。

### 时间来源标签

`视频拼接`、`评论`、`文本`、`图片拼接`、`附件名兜底`、`人工修改`。

## 时间字符兼容规则

视频帧 OCR / 图片 OCR / 评论文本中常见非标准时间格式，以下为当前已兼容的全部字符转换规则。
处理入口：`_preprocess_ocr_datetime()` → `_fix_ocr_char_confusion()` → `_normalize_ocr_time()`。

### 1. 全角 / 分隔符归一化

| 原始字符 | 转换结果 | 示例 |
|----------|----------|------|
| `：`（全角冒号） | `:` | `11：30` → `11:30` |
| `；`（中文分号） | `:` | `8；44` → `8:44` |
| `;`（半角分号） | `:` | `8;44` → `8:44` |
| `,`（逗号） | `:` | `10,12` → `10:12` |
| `.`（点号） | `:` | `10.26.39` → `10:26:39` |
| `——` / `–` / `—` | 空格 | `2026-01-09——14:02` → `2026-01-09 14:02` |
| `\|` / `｜` | 空格 | `2026-10-26\|19:39:17` → `2026-10-26 19:39:17` |

### 2. OCR 字符混淆修正

仅对匹配时间模式的片段替换，避免误改其他文本。数字密度 <40% 时视为乱码，不替换。

| 混淆字符 | 修正为 | 场景 |
|----------|--------|------|
| `O` / `o` | `0` | `OI:3O` → `01:30` |
| `I` / `l` / `L` | `1` | `I4:3I` → `14:31` |
| `Z` / `z` | `2` | `ZO:LI` → `20:11` |
| `S` / `s` | `5` | `I5:3S` → `15:35` |
| `B` | `8` | `B:3O` → `8:30` |

### 3. 英文月份缩写（含 OCR 误读变体）

车载 HMI / 手机状态栏常在时间上方显示英文月份，如 `Oct 9` `Nov 2026`。  
转换后变为标准数字日期（`Oct 9` → `2026-10-9`），可被 `_OCR_TIME_FULL_RE` 匹配。

| 月份 | 标准缩写 | 常见 OCR 误读 |
|------|----------|---------------|
| 1月 | jan, january | qan, jar, jari |
| 2月 | feb, february | teb |
| 3月 | mar, march | — |
| 4月 | apr, april | — |
| 5月 | may | mau |
| 6月 | jun, june | jur |
| 7月 | jul, july | — |
| 8月 | aug, august | auq |
| 9月 | sep, september | seq |
| 10月 | oct, october | qct, 0ct, 0et |
| 11月 | nov, november | nou, riov |
| 12月 | dec, december | deo |

年份补充规则：有显式年份时直接使用；无年份时从文本上下文搜索 4 位年份，找不到则用当前年份。

### 4. 中文日期关键字

车载 HMI 屏幕常显示 `2026年11月9日 16:44`，OCR 可能识别出空格。

| 原始格式 | 转换结果 | 示例 |
|----------|----------|------|
| `YYYY年MM月DD日` | `YYYY-M-D` | `2026年11月9日` → `2026-11-9` |
| `YYYY 年 MM 月 DD 日` | `YYYY-M-D` | `2026 年 11 月 9 日` → `2026-11-9` |
| `MM月DD日 HH:MM` | `当年-MM-DD HH:MM` | `11月9日 16:44` → `2026-11-09 16:44` |

### 5. 缺失分隔符修复

| 场景 | 示例 | 转换 |
|------|------|------|
| 孤立 4 位数字（非年份） | `1433` | `14:33` |
| 孤立 6 位数字 | `172440` | `17:24:40` |
| 日期时间粘连 | `2026-01-0914:02` | `2026-01-09 14:02` |
| 日期与无分隔符时间 | `2026-01-22172440` | `2026-01-22 17:24:40` |

### 6. 年份修正

| 场景 | 示例 | 转换 |
|------|------|------|
| 3 位年份 | `026-10-27` | `2026-10-27` |
| 首位误识别 | `6024-01-22` | `2024-01-22`（3000~9999 → 2000+后三位） |
| 2 位年份 | `26-10-20` | `2026-10-20` |

---

## 历史变更记录

<details>
<summary><b>1. 封面帧小字时钟 OCR 识别修复（2026-10-09）</b></summary>

- **问题描述**：封面帧有清晰时钟但 OCR 读成乱码，时间提取失败
- **相关Bug号**：VCU-553755
- **根因**：EasyOCR 默认画布 1280 导致大图下采样，小字号/低对比度时钟识别能力不足
- **解决方案**：新增 _ocr_readtext 使用 canvas_size=2560、mag_ratio=1.5、降低阈值，统一应用到三处 OCR 调用点

</details>

<details>
<summary><b>2. gmlogger 包内 main 文件日期遗漏修复（2026-10-10）</b></summary>

- **问题描述**：视频封面读出 6:17，但未能匹配到包内 58-main.log_2026_10_10_6_18_4.gz 的正确日期
- **相关Bug号**：VCU-553973
- **根因**：① main_names[:5] 只取前 5 个 main 文件，30+ 文件时遗漏目标日期；② 外层 gmlogger 文件名有旧日期时不触发包内回退
- **解决方案**：遍历所有 main 文件解析时间（头读限 10 个）；始终下载包内取权威日期，包内优先、外层仅补充

</details>

<details>
<summary><b>4. 视频 OCR 低置信度误识别过滤（2026-10-10）</b></summary>

- **问题描述**：视频帧中手机屏幕显示 10:08，因清晰度低被 OCR 误读为 16:50，导致提取错误时间
- **相关Bug号**：VCU-553491
- **根因**：OCR 结果的置信度完全被忽略，低置信度的误识别文本直接参与时间提取，模糊帧的数字容易被错读
- **解决方案**：在 _ocr_readtext 中过滤置信度<0.3 的时间类文本（仅含数字/冒号/斜杠），三处 OCR 调用点统一生效

</details>

<details>
<summary><b>5. 排查诊断未解压时视频OCR无条件覆盖文本提取结果（2026-10-10）</b></summary>

- **问题描述**：文本路径已正确提取到 13:44:00（Initial Setting），但排查诊断仍返回视频 OCR 的 16:50:53
- **相关Bug号**：VCU-553491
- **根因**：gmlogger 未解压时 ref_pool 为空，视频 OCR 结果不经任何验证直接返回 success，覆盖了正确的文本提取时间
- **解决方案**：调整 _diag_verify_suggestion 中无包内时间戳分支的优先级：文本路径已提取有效时间时优先与 gmlogger 文件名时间印证，仅在文本无结果时才回退视频 OCR

</details>

<details>
<summary><b>7. 视频未命中gmlogger时新增非视频图片OCR时钟兜底（2026-10-11）</b></summary>

- **问题描述**：视频提取时间(17:27)与gmlogger包内/文件名时间(20:05)不命中，直接走兜底或返回空；附件中车机时钟截图(20:01)未被利用，导致提取失败
- **相关Bug号**：VCU-550243
- **根因**：图片OCR兜底 _diag_extract_time_from_images 仅在诊断流程且gmlogger组数>10时调用，主提取链路 _diag_extract_time_from_video_simple 在视频未命中gmlogger时从不参考非视频图片
- **解决方案**：新增 _image_fallback_time：视频未命中gmlogger后调用图片OCR，图片时钟(20:01)与参考时间(20:05)按时分接近(容差10分钟)则用参考日期+图片时间拼接返回；差距过大弃用回退原逻辑

</details>

<details>
<summary><b>8. gmlogger 前置检查移至所有时间提取之前（2026-10-12）</b></summary>

- **问题描述**：gmlogger 检查在评论/字段提取之后，导致无 gmlogger 的 Jira 仍执行了不必要的评论提取
- **根因**：_extract_one 中 gmlogger 前置检查位置不对，应在 fetch_issue 之后、所有时间提取之前
- **解决方案**：将 _has_gmlogger_logs 检查移到 fetch_issue 之后、评论/字段提取之前，无 gmlogger 直接返回 None（不写空标签，不属于通用报错，下次重新检查）

</details>

<details>
<summary><b>9. gmlogger 下载增加双重超时保护（2026-10-12）</b></summary>

- **问题描述**：156MB 的 gmlogger 压缩包下载卡住，阻塞整个提取流程
- **相关Bug号**：批量执行中偶发
- **根因**：httpx.stream() 的 read=300（5分钟等待响应头/数据块），服务器不响应时整个线程挂起
- **解决方案**：read 超时从 300s 降至 60s；增加 5 分钟 wall-clock deadline（time.monotonic），每下载 1MB 检查一次；体积阈值从 500MB 降至 200MB

</details>

<details>
<summary><b>10. 移除视频兜底链路的外层文件名日期回退（2026-10-12）</b></summary>

- **问题描述**：gmlogger 包内 main.log 日期获取失败时，仍用外层文件名的日期凑合，可能匹配到错误日期
- **根因**：_diag_extract_time_from_video_simple 中包内日期失败后回退到外层 gmlogger 文件名日期，外层文件名日期可能不准
- **解决方案**：包内日期为权威来源，获取失败时直接跳过视频兜底，不再用外层文件名日期凑合

</details>

<details>
<summary><b>11. RapidOCR 检测阈值修复（2026-10-12）</b></summary>

- **问题描述**：低质量视频帧 RapidOCR 检测不到文本，频繁回退 EasyOCR
- **根因**：RapidOCR 默认 box_thresh=0.5 太高（EasyOCR 用 text_threshold=0.25），阈值差一倍导致低质量帧检测失败
- **解决方案**：box_thresh 从 0.5 降至 0.3，text_score 设为 0.15（与应用层过滤阈值对齐）

</details>

<details>
<summary><b>12. RapidOCR 图像放大规则从 EasyOCR 迁移（2026-10-13）</b></summary>

- **问题描述**：EasyOCR 的 mag_ratio=1.5（图像放大1.5倍）未迁移到 RapidOCR，小字号识别能力下降
- **根因**：切换 OCR 引擎时只迁移了检测阈值，未迁移图像预处理参数
- **解决方案**：_rapid_ocr_readtext 对宽度<1280px 的图像自动放大 1.5x（INTER_CUBIC），bbox 坐标还原；已二值化/锐化的 ROI（_already_enhanced=True）跳过放大避免伪影放大

</details>

<details>
<summary><b>13. gmlogger 内包日期提取优化——仅从 main 文件名提取（2026-10-13）</b></summary>

- **问题描述**：VCU-555094 的 main.log 存在但头部 64KB 无日期匹配，提取时间 0 个，视频兜底被跳过
- **相关Bug号**：VCU-555094
- **根因**：原逻辑先尝试文件名解析，失败后解压读文件头部 64KB 提取日期，但 main.log 头部可能无日期格式
- **解决方案**：简化为仅从 main 文件名提取日期（不解压读内容），带去重；_diag_scan_entry_times 保持仅匹配 main.log 文件名

</details>

<details>
<summary><b>14. gmlogger包内日期获取失败时回退到外层文件名日期继续视频兜底（2026-10-13）</b></summary>

- **问题描述**：批量执行中多个 VCU（555132/555131/555130/555129/555127）因 gmlogger 压缩包过大(>200MB)被跳过，视频OCR和图片OCR全部未执行
- **相关Bug号**：VCU-555132, VCU-555131, VCU-555130, VCU-555129, VCU-555127
- **根因**：_diag_extract_time_from_video_simple 中包内日期获取失败时直接 return ""，跳过了整个视频兜底和图片兜底链路；但外层 gmlogger 文件名日期已在 gm_times 中解析，可以作为回退参考
- **解决方案**：包内日期失败时回退到外层 gmlogger 文件名日期继续视频/图片 OCR；仅当包内和外层均无日期时才跳过（OCR 无法验证）

</details>

<details>
<summary><b>15. EasyOCR 延迟初始化——避免不必要的模型下载（2026-10-17）</b></summary>

- **问题描述**：每次诊断都提前初始化 EasyOCR，即使 RapidOCR 已能处理仍触发中文模型下载（"Downloading recognition model"）
- **根因**：server.py 和 server_legacy.py 中 4+3 处 `_get_ocr_reader()` 在函数入口提前调用，EasyOCR 每次初始化都尝试下载缺失的 `zh_sim_g2.pth` 中文模型
- **解决方案**：所有提前初始化改为延迟加载——`_ocr_readtext` 内部仅当 RapidOCR 结果为空或置信度<0.3 时才初始化 EasyOCR；传参从 `reader` 改为 `None`，函数内部按需获取

</details>

<details>
<summary><b>16. .log/.txt 文件纳入日志附件判断与文件名时间提取（2026-10-17）</b></summary>

- **问题描述**：附件为 `[SFTC-1.21.24]server.log` 等 `.log`/`.txt` 文件时，被误判为"无gmlogger"跳过排查
- **根因**：`_has_gmlogger_logs` 仅检查文件名含 `gmlogger` 或 `main.log`，`.log`/`.txt` 后缀文件不匹配；`gm_atts` 筛选和 `_diag_gmlogger_times` 也仅识别 gmlogger
- **解决方案**：三处统一扩展——① `_has_gmlogger_logs` 附件名 `.endswith(".log")` / `.endswith(".txt")` 直接判定有日志，压缩包内探测同步扩展；② `gm_atts` 筛选加入 `.log`/`.txt`；③ `_diag_gmlogger_times` 和 `_extract_attachment_time` 用 `_COMPACT_RE` 通用正则解析文件名时间，提取不到则继续走视频/图片 OCR 链路，不解压

</details>

<details>
<summary><b>17. 云端触发时间表再平衡与写入分配优化（2026-10-17）</b></summary>

- **问题描述**：部分触发时间表超过 500 条上限（511/503/503/501），而其他表只有 1 条记录，存储分布不均
- **根因**：旧写入逻辑顺序找第一个有空位的表填满，导致前面的表都堆到 500，后面的表很空；历史数据可能超限但无自动修正机制
- **解决方案**：① 写入策略改为按剩余空间从大到小排序，优先填空位最多的表；② 新增再平衡 API `POST /api/trigger_time/rebalance`，扫描超限表（>500），将多余记录搬到余量最大的未满表；实测将 4 张超限表共 18 条记录搬入仅 1 条记录的表

</details>

<details>
<summary><b>18. 评论区附件名时间提取与分钟频率中位数选择（2026-10-17）</b></summary>

- **问题描述**：VCU-555714 错误提取了描述中的时间 `2026-10-07 20:50`，而评论区附件名（如 `58-main.log_2026_10_14_7_40_26.gz`）包含正确时间 `2026-10-14 07:40`
- **根因**：`_diag_verify_suggestion` 在 gmlogger 包内无法解析且无压缩包时，直接采纳评论区/描述提取的时间，未考虑附件文件名中的时间戳
- **解决方案**：① 新增 `extract_times_from_comment_attachments` 和 `extract_median_time_from_attachments` 函数，从评论区文本中匹配 `main.log_YYYY_MM_DD_H_M_S` 模式；② 分钟频率统计策略：统计各分钟值出现次数，筛选出现次数 >= max(2, max_count//2) 的分钟值，取中位数（如 38×2、39×4、40×4、41×4 → 候选 [38,39,40,41] → 中位数 40）；③ 在 `_diag_verify_suggestion` 的两个关键回退点插入附件时间校验：gmlogger 未交叉印证时、压缩包无 main.log 时
- **实现文件**：`src/clients/jira_client.py`（新增函数）、`src/web/server.py`（`_diag_verify_suggestion` 增加校验点）

</details>

<details>
<summary><b>19. RapidOCR 置信度类型安全修复（2026-10-17）</b></summary>

- **问题描述**：VCU-552013 视频 OCR 全部失败，报 `unsupported operand type(s) for +: 'int' and 'str'`
- **根因**：RapidOCR 返回的 `conf` 字段为字符串类型而非 float，`_ocr_readtext` 中 `sum((r[2] for r in results), 0)` 执行 `0 + "0.95"` 时抛出 TypeError
- **解决方案**：在 `_avg_conf` 计算前增加类型安全检查，将非数值类型的 conf 强制转为 float 或归零；同时修复 `server.py` 和 `server_legacy.py`；实测 VCU-552013 修复后视频 OCR 正确提取 `2026-09-24 16:34:00`

</details>

<details>
<summary><b>20. gmlogger 压缩包内 main.log 日期提取与 ref_pool 空跳过修复（2026-10-19）</b></summary>

- **问题描述**：VCU-557682 视频封面清晰显示 5:38，但视频 OCR 被完全跳过，返回“提取失败”
- **相关Bug号**：VCU-557682
- **根因**：① `_diag_extract_time_from_video_simple` step 3 用 `"gmlogger" in fn_lower` 跳过了 gmlogger 压缩包，导致 `gmlogger(1).7z` 内的 `main.log_2026_10_19_6_56_11.gz` 等带日期文件未被探测，`ref_pool` 为空；② `ref_pool` 为空时函数直接 `return ""` 跳过整个视频 OCR；③ 包内 main 文件名小时为非零填充的 `6`，`_COMPACT_RE` 的 `\d{2}` 无法匹配单数字小时，误把 `6_56` 解析为分钟 65；④ Jira 附件创建时间带时区 (`+08:00`) 与 OCR 解析的 naive datetime 比较时抛 `can't subtract offset-naive and offset-aware datetimes`
- **解决方案**：① 移除 step 3 的 gmlogger 跳过条件，让 gmlogger 压缩包也通过 `_diag_list_archive_entries` 探测内部 main.log 日期；② 为包内 main 文件添加下划线分隔格式的兆底解析（`20\d{2}_\d{1,2}_\d{1,2}_\d{1,2}_\d{1,2}`，支持 1-2 位小时/分钟）；③ `ref_pool` 为空时不再提前返回，继续尝试视频 OCR，并将 gmlogger 上传时间加入 `ref_pool` 作为兆底参考；④ 统一在 `_build_gmlogger_info`、`gm_ref_dt` 赋值、`_find_closest_gmlogger` 的 `video_upload` 处去除时区信息

</details>

<details>
<summary><b>23. 视频帧提取范围从 [1,3,6] 秒改为前6帧 [0,1,2,3,4,5] 秒（2026-10-20）</b></summary>

- **问题描述**：视频帧提取在封面帧未命中时，仅截取第1/3/6秒进行 OCR，采样点少且间隔大，容易错过清晰时钟帧
- **相关Bug号**：VCU-557464
- **根因**：原 positions=[1, 3, 6] 只有 3 个采样点，间距不均匀（1s→2s→3s），对于时钟位置变化较快的视频容易漏掉关键帧
- **解决方案**：将第二阶段帧提取从 `positions=[1, 3, 6]` 改为 `positions=[1, 2, 3, 4, 5]`，加上封面帧 [0]，总共覆盖前6秒，采样点从 4 个增加到 6 个，间距均匀（每秒1帧）
- **实现文件**：`src/services/server_legacy.py`（`_diag_extract_time_from_video_simple` 和 `_diag_extract_time_from_video` 两处）

</details>

<details>
<summary><b>24. 视频 OCR 多级验证——视频文件名日期时间与 OCR 时间交叉确认（2026-10-20）</b></summary>

- **问题描述**：VCU-557464 描述含两个时间（11:30 和 2026-10-11 17:08:47），视频帧0 OCR 提取到 11:30，视频文件名含 2026-10-14 11:30，但诊断返回了错误的 2026-10-11 17:08:47
- **相关Bug号**：VCU-557464
- **根因**：视频 OCR 提取到仅时间（11:30）后，只能用 gmlogger 文件名日期补充（2026-10-11），与 gmlogger 时间差距大未通过验证，时间被丢弃；视频自身文件名含完整日期时间（2026-10-14 11:30）与 OCR 时间完全匹配，但未被利用
- **解决方案**：新增 `_parse_video_filename_datetime` 函数从视频文件名提取完整日期时间（支持 YYYYMMDD_HHMMSS / YYYYMMDD_HHMM 等格式）；在两个视频提取函数的 OCR 仅时间处理路径中增加多级验证步骤——OCR 时间与视频文件名时间 HH:MM 完全匹配时，直接采用视频文件名日期时间（无需 gmlogger 验证），实现 OCR+文件名多级确认
- **实现文件**：`src/services/server_legacy.py`（新增 `_parse_video_filename_datetime`、修改 `_diag_extract_time_from_video_simple` 和 `_diag_extract_time_from_video` 的 OCR 仅时间路径）

</details>

<details>
<summary><b>29. OCR 纠正容差优化 + 有 gmlogger 文件名时跳过压缩包探测（2026-10-22）</b></summary>

- **问题描述**：VCU-559847 视频 OCR 读到 "15:27"（实际正确），但 `_correct_ocr_by_reference` 将其"纠正"为 "15:29:00"（参考 gmlogger 文件名时间 15:33，仅 1 位差异），导致最终提取结果 `2026-10-22 15:29:00` 不准确
- **相关Bug号**：VCU-559847
- **根因**：
  1. `_correct_ocr_by_reference` 容差仅 5 分钟，OCR 时间与 gmlogger 时间差 6 分钟时触发了不必要的纠正
  2. 有 gmlogger 文件名时间（三个文件日期一致且可解析）时，仍会下载探测其他非 gmlogger 压缩包，浪费资源
- **解决方案**：
  1. **容差扩大**：`_correct_ocr_by_reference` 的"无需纠正"阈值从 5 分钟改为 10 分钟，OCR 时间与 gmlogger 参考时间差 ≤10 分钟时直接保留原值
  2. **跳过压缩包探测**：`_diag_extract_time_from_video_simple` 中，如果 gmlogger 文件名已有可解析时间（`gm_times` 非空），跳过整个压缩包下载探测（step 3），只下载视频做 OCR
  3. **清除错误缓存**：删除 `data/video_time_cache.json` 中 `VCU-559847:IMG_1066.MOV` 的错误条目
- **优化效果**：
  - VCU-559847 场景（3个 gmlogger + 1个视频）：只下载视频，OCR "15:27" 不纠正，拼接 gmlogger 日期 → `2026-10-22 15:27:00`（正确）
  - 减少不必要的附件下载（gmlogger 分卷包 + 其他压缩包均不下载）
- **实现文件**：`src/services/server_legacy.py`（`_correct_ocr_by_reference` 容差、`_diag_extract_time_from_video_simple` 跳过逻辑）

</details>

<details>
<summary><b>30. 触发时间自检与来源/偏差落库——把“提取成功”和“过滤命中”分开度量（2026-10-26）</b></summary>

- **问题描述**：10 月共 3230 条分析记录（去重 2639 个 Jira），成功 2686（83.2%）、失败 544（16.8%）；失败中 **72.4%（394 条）是“时间过滤后日志为空”**。进一步只读核对发现这不是“没有触发时间”，而是**提取出来的时间与日志包对不上**：失败样本里问题时间几乎全部等于视频 OCR 缓存时间，日期差 1~2 天但时钟几乎一致（VCU-560297/VCU-560419/VCU-559995）、年份差 1 年（VCU-557671）、或遇到没有可解析日志包的纯视频单。更关键的是“成功”也不等于“准”：成功样本 40 条与日志包时间比对，**只有 20% 落在 30 秒内、28% 落在 1 分钟内**，其余 1 分钟~数小时。
- **相关Bug号**：VCU-560297、VCU-560419、VCU-559995（时钟对、日期错）、VCU-557671（年份错）、VCU-557593/VCU-558311（早于日志包）；数据侧统计口径见 10 月多维表格导出与 `timestudy/records/records_2026-10-*.csv`
- **根因**：
  1. **容差与窗口错配**：提取侧用 `_match_tolerance = 300/600` 秒（内层 main.log 5 分钟、仅外层文件名 10 分钟）判定“命中”，而 AI 侧日志过滤窗口实测**中位 6 秒、P90 30 秒**（从 10 月报告 `时间范围 [HH:MM:SS ~ HH:MM:SS]` 抓取 51 个窗口），两者相差 50~100 倍
  2. **时间分辨率不匹配**：`data/video_time_cache.json` 中 2901 条视频 OCR 结果里 **83% 秒位为 00（分钟级）**，分钟级时间天然无法命中秒级窗口
  3. **日期补全可选用到错误来源**：视频 OCR 只读到时钟时，日期可能取自 Jira 创建日期/分析日期等不可靠来源，导致“时钟对、日期错”
  4. **问题不可度量**：触发时间表只有 `jira号/触发时间/提取时间` 三列，没有“来源/参考时间/偏差/是否命中窗口”，无法区分“提取错”还是“窗口窄”；且自学习记录只在机器人诊断链路写入，批量分析链路完全没有记录
- **解决方案**：
  1. **触发表新增 5 列**：`时间来源`、`参考时间`、`时间差秒`、`窗口命中`、`时间状态`；`ensure_trigger_time_fields()` 首次写入时幂等补列（`create_bitable_field`），再平衡搬表时一并保留（原来只搬 3 个核心字段会丢列）
  2. **提取阶段登记日志包参考时间**：新增 `remember_ref_time()` / `_lookup_ref()`，`testing.py` 与 `trigger.py` 在拿到附件后用 `_diag_gmlogger_times()` 登记参考时间，写表时自动计算自检列
  3. **自检分级**：新增 `self_check_trigger_time()`——≤30 秒 `正常/窗口命中`、≤300 秒 `待确认/未命中`、>300 秒 `不可用`、无参考 `无参考`
  4. **分析前自检（P0-2）**：`pipeline._time_check_before_analysis()` 在调用 AI 前比对触发时间与日志包时间，>300 秒直接跳过分析并写明原因（`supplement_row` 与 `compare_bug_analysis` 两条链路），30~300 秒照常分析但标注 `时间自检`；阈值可通过 `ai_log_api.time_warn_offset_sec / time_reject_offset_sec` 调整
  5. **自学习记录接上批量链路**：`testing.py` 的 `_process_one` 提取成功后写 `_timestudy_record()`，包含来源、参考时间、匹配差秒、视频数、gmlogger 数，落盘 `data/timestudy/records.csv`
  6. **写入安全兜底**：新增 `_safe_update_records()` / `_safe_create_records()`，扩展列写入失败时自动退回核心字段重试，字段未迁移也不影响触发时间正常写入
- **验证结果**：
  - 10 月成功样本 40 条：与日志包时间差 ≤10 秒 4 条、11~30 秒 4 条、31~60 秒 3 条、1~5 分钟 19 条、5~60 分钟 5 条、>1 小时 2 条、日期错 2 条、无参考 1 条
  - 自检分级/扩展列写入/补列幂等/分析前自检共 6 个新用例全部通过；全量回归 56 passed
  - 服务重启后 141 条路由正常，`/api/trigger_time/batch_read` 返回 200
- **实现文件**：`src/services/trigger_ops.py`（扩展列、自检、参考时间登记、安全写入）、`src/api/routes/testing.py`（参考时间登记 + 自学习记录）、`src/api/routes/trigger.py`（参考时间登记）、`src/pipeline.py`（分析前自检）、`config/config.yaml`（自检阈值）、`tests/test_time_check.py`

</details>

<details>
<summary><b>32. 禁止用上传时间/视频日期补日期 + 未通过日志包校验一律不返回（2026-10-27）</b></summary>

- **问题描述**：时间批量提取跑出 139 条命中，抽查 21 条发现 7 条错误，其中 3 条是“时钟对、日期错”（如 VCU-561531 事件发生在 10-19，却提取成 10-27），2 条是“取到视频录制时间而非事件时间”，1 条 12h 误判，2 条 OCR 读错但视频文件名里明明是正确时间。按日志过滤窗口（中位 6 秒）统计，139 条里只有 3 条“正常”，65 条差 1~5 分钟，50 条差 5 分钟以上（含 7 条差 1 天以上）。
- **相关Bug号**：VCU-561531、VCU-561529、VCU-561077（日期错 3~8 天）、VCU-561423（视频录制时间≠事件时间）、VCU-561378（12h）、VCU-561556、VCU-561526（OCR 与文件名冲突）
- **根因**：
  1. **ref_pool 收了 gmlogger 上传时间**：`gm_ref_dt = att["created"]` 被 append 进 ref_pool，上传日（10-27）因此能“验证通过”10-19 的事件
  2. **日期补全优先用视频上传日期**：三处“仅时间”补全都先取 `video_att["created"]` 的年月日，直接把日期定成上传当天
  3. **未通过校验的候选仍然返回**：缓存未命中也记 `best_partial`，函数末尾“单视频/多视频兜底”直接返回，12h 候选也不看容差
  4. **旧日志包的 inner main 造成假阳性**：VCU-561526 的包内 main 是 10-25/10-26 的旧日志，OCR 误读的 21:12 恰好命中 10-25 的参考
- **解决方案**：
  1. 从 ref_pool 和 close_refs 中**彻底移除 gmlogger 上传时间**（只保留包内 main 与 gmlogger 文件名时间）
  2. 三处“仅时间”补全的日期改为**只取日志包日期**（`closest_gm.filename_time` → `gm_dates`），禁止再用视频上传日期
  3. **删除未验证的兜底返回**：缓存未命中不再记 partial；12h 候选必须满足容差；单/多视频 partial 一律丢弃，交由文本提取兜底
  4. 新增**同期性约束**：视频文件名带完整日期时间时，只接受与它相差 ≤6 小时的日志包参考，否则跳过该视频（识别“事后复现”的视频）
  5. 评分链路（`_diag_run_core`）移除“视频上传日期”日期提供者
  6. **问题排查链路同步统一**：`_diag_extract_time_from_video`（问题排查专用）移除 15min~1h、12h、完整时间、部分时间四类未验证兜底；视频文件名时间与 OCR 一致时也必须通过日志包校验才返回
- **验证结果**：清掉 7 条视频缓存后用新逻辑重跑，7 条全部修正：
  - VCU-561531：10-27 21:05 → **10-19 21:05**（日志包 10-19 21:14）
  - VCU-561529：10-27 14:23 → **10-20 14:51**（回退文本）
  - VCU-561077：10-26 15:38 → **10-23 15:38**（回退文本）
  - VCU-561423：16:56 → **13:25**（回退文本，日志包 13:26）
  - VCU-561378：17:47 → **15:48**（回退文本）
  - VCU-561556：15:17 → **17:09:55**（回退文本，与视频文件名一致）
  - VCU-561526：21:12 → **15:23:55**（回退文本，与视频文件名 15:26 一致）
- **批量纠正**：对“时间状态=不可用”的 50 条重跑（清视频缓存 → 新逻辑提取 → 文本兜底 → 写回云端并带自检列），**27 条值被纠正**（如 VCU-561531 10-27→10-19、VCU-561077 10-26→10-23、VCU-561481 10-27→10-26），23 条本来就对但时钟差 >5 分钟保持不变，0 失败；重跑后这 50 条状态分布：正常 7、待确认 11、不可用 32
- **实现文件**：`src/services/server_legacy.py`（`_diag_extract_time_from_video_simple` 的 ref_pool 构建、日期补全、兜底返回、同期性约束；`_diag_run_core` 日期提供者）

</details>

<details>
<summary><b>35. 时间自检改为方向敏感 + 放宽日志包命名识别（2026-10-27）</b></summary>

- **问题描述**：139 条提取结果复查发现三类判定逻辑问题：① 118 条可对比记录里 107 条“提取时间早于抓包时间”（中位早 156 秒），这是正常现象，但旧规则按对称偏差判定，把大量正确结果标成待确认/不可用；② 21 条“无参考”里有 8 条其实日志包文件名带时间（GMLog_20261027_152355.7z、pataclogger_2026_10_27_17_15_0.part01.rar、784da062_20261027_173855.7z），只是识别规则只认 gmlogger/.log/.txt；③ 4 条文本时间晚于抓包数小时到 6 天（VCU-561093 +6.3 天、VCU-561394 +24 小时、VCU-561359 +7.7 小时、VCU-561358 +17.5 分钟），逻辑上不可能
- **相关Bug号**：VCU-561093、VCU-561394、VCU-561359、VCU-561358、VCU-561518、VCU-561493、VCU-561480、VCU-561439
- **根因**：
  1. `self_check_trigger_time` 用 `abs(提取-参考)` 对称比较，而参考时间是日志包“抓包时间”，事件必然发生在其之前
  2. `_diag_gmlogger_times` 只识别文件名含 gmlogger 或 .log/.txt 的附件，其他日志包命名（GMLog_/pataclogger/哈希_日期）解析不出时间
  3. 文本提取（评论/字段/描述）没有“不能晚于抓包”的约束，评论里的时间可能是别的日期或误写
- **解决方案**：
  1. 自检改为方向敏感：晚于抓包 >300s → 不可用；30~300s → 待确认；早于抓包 ≤15 分钟 → 正常；15~60 分钟 → 待确认；>60 分钟 → 不可用
  2. 新增 `_parse_any_log_filename_time` 并用 `_LOG_NAME_HINTS`/`_LOG_ARCHIVE_SUFFIXES` 放宽日志包识别，视频/图片排除；`_has_gmlogger_logs` 同步放宽 logcat/dltlog/bllog/logger/pataclogger
  3. 对 139 条刷新自检列（参考时间/差秒/窗口命中/状态），对 12 条真正可疑重跑提取
- **验证结果**：139 条状态由「正常 3 / 待确认 65 / 不可用 50 / 无参考 21」变为「正常 108 / 待确认 10 / 不可用 8 / 无参考 13」；有参考从 118 升到 126；重跑修正 4 条（VCU-561526 21:12→15:23:55、VCU-561460 20:50→17:00:59、VCU-561497 12:00→17:38:55、VCU-561433 14:27→16:57:35）；剩余 8 条保留不可用待人工确认（如 VCU-561394 文本时间晚 24 小时）
- **实现文件**：`src/services/trigger_ops.py`（自检方向敏感）、`src/services/server_legacy.py`（日志包命名识别）、`tests/test_time_check.py`（更新分级用例）、`tests/test_log_name_parse.py`（新增 6 个用例）

</details>

<details>
<summary><b>36. 触发时间自检列在所有提取路径都写入（2026-10-27）</b></summary>

- **问题描述**：云端触发时间表里 8598 条有触发时间的记录中，**8345 条（97%）`时间来源` 和 `参考时间` 都是空的**，只有“时间批量提取”写入了自检列，其他入口（抽样提取、线上批量、自动检测、时间对比、单条提取、人工修正、机器人、pipeline、flow）写入时都没带来源/参考时间
- **根因**：自检列由 `_trigger_time_meta(trigger_time, source, ref_time)` 生成，但绝大多数调用点直接 `_save_trigger_time_to_cloud(bugid, tt)` / `_batch_save_trigger_times_to_cloud(items)`，没有传 `source` 和 `ref_time`；`_resolve_ref_time` 也不存在，缓存未命中时参考时间只能为空
- **解决方案**：
  1. 新增 `_resolve_ref_time(bugid, ref_time)`：显式值 > `_TRIGGER_TIME_REF_CACHE` 缓存 > 现场查 Jira 日志包文件名（`_diag_gmlogger_times`），解析后写回缓存
  2. `_save_trigger_time_to_cloud` 增加 `auto_ref=True`（默认开启），`source` 为空时写 `未标注`，避免出现“来源空白”的行
  3. 11 个写入点全部补上来源标注：pipeline(补充行)、flow(单Jira提取)、单条提取:x、线上批量(预提取)、自动检测、时间对比(读取)、人工修正、人工修正(批量)、机器人提取、本地CSV同步、批量应用(人工)；抽样提取额外带上参考时间
  4. 批量写入（时间对比读取、抽样提取）在循环里用 issue 附件名解析参考时间，避免额外请求
- **验证结果**：单测 5 个新增通过（缓存命中/现场解析/异常降级/默认来源/显式来源），全量 80 passed；真机验证 VCU-561531 写入后：参考时间=2026-10-19 21:14:43、差秒=583、窗口命中=否、状态=正常
- **遗留**：历史 8345 条仍为空，需要逐条查 Jira 回填（约 2~3 小时），可按时间窗口分批执行
- **实现文件**：`src/services/trigger_ops.py`、`src/api/routes/trigger.py`、`src/api/routes/testing.py`、`src/api/routes/flow.py`、`src/pipeline.py`、`src/services/server_legacy.py`、`tests/test_trigger_meta_paths.py`（新增）

</details>

<details>
<summary><b>37. 按来源族统计准确率 + 文本提取增加“不能晚于抓包”校验（2026-10-27）</b></summary>

- **问题描述**：139 条按来源族统计：视频 100 条（正常 85、待确认 5、不可用 1、无参考 9）；文本/字段 35 条（正常 23、待确认 5、**不可用 7**）；图片 OCR 4 条全部无参考。**7 条不可用全部来自文本提取**，其中 4 条是“晚于日志抓包时间”（VCU-561394 晚 24 小时、VCU-561359 晚 7.7 小时、VCU-561358 晚 17.5 分钟、VCU-561093 晚 6.3 天），逻辑上不可能
- **相关Bug号**：VCU-561394、VCU-561359、VCU-561358、VCU-561093（晚于抓包已修正）；VCU-561518、VCU-561493、VCU-561439（文本本身写的就是别的时间，需人工）
- **根因**：
  1. 视频提取有 ref_pool 校验，准确率明显更高（85% 正常，异常都是画面时钟与抓包时钟差 1~5 分钟）
  2. 文本提取（标题/字段/评论/描述）直接返回第一个“看起来像时间”的值，没有方向约束：评论里写的时间可能是隔天、隔小时、甚至别的故障时间
  3. 日志包抓包时间的解析能力之前只服务视频链路，文本链路拿不到
- **解决方案**：
  1. `jira_client` 新增 `parse_log_filename_time` / `get_log_capture_time`，识别 gmlogger/GMLog_/pataclogger/哈希名 等命名，`server_legacy._parse_any_log_filename_time` 改为复用
  2. `extract_trigger_time_from_issue` 外包一层方向校验：提取时间晚于抓包时间 5 分钟以上 → 判为不可信，改用日志附件名时间兜底；`skip_attachment=True` 时直接返回空并标记 `rejected_after_capture`
  3. 视频链路不变（已有 ref_pool 校验）
- **验证结果**：
  - 文本族 35 条重跑：4 条晚于抓包的记录被修正（VCU-561394 10-27 16:03→10-26 16:04:42、VCU-561359 →10-26 18:36:06、VCU-561358 →02:29:20、VCU-561093 →10-13 06:49:16），全部变成“正常”
  - 139 条总量：正常 108→**112**，待确认 10，不可用 8→**4**，无参考 13
  - 各族正常率：视频 85%、文本/字段 77%、图片 OCR 0%（无参考）
  - 新增 6 个单测（晚于抓包兜底/早于抓包保留/轻微晚于保留/无日志附件不校验/skip_attachment 直接拒绝/日志包名解析），全量 **86 passed**
- **遗留**：文本仍有 3 条不可用——VCU-561518（描述早 2.8 小时）、VCU-561493（字段早 1 小时）、VCU-561439（评论是 2 天前的时间），这类是业务描述本身写的时间与本次事件不一致，只能人工确认
- **实现文件**：`src/clients/jira_client.py`（方向校验 + 抓包时间解析）、`src/services/server_legacy.py`（复用解析）、`tests/test_text_time_guard.py`（新增 6 个用例）

</details>

<details>
<summary><b>43. 视频 OCR 优化：关帧差法、扩帧窗口、ROI 优先、修正耗时日志（2026-10-27）</b></summary>

- **问题描述**：视频时间提取靠“前 6 帧 OCR”，存在三个问题：① 帧差法回退几乎不生效却要额外耗时；② 时钟偶尔第 5 秒才出现，窗口没有余量；③ 单帧 OCR 不稳定（相邻帧时有时无）
- **实测数据**：
  - 帧差法：10-27 共尝试 **55 次，成功 0 次**（OCR 结果为“西助中心 #林物有容 A”这类垃圾文本），每次多花 2~3 秒
  - 6 个真实视频抽样：5 个在 0~5 秒内命中，1 个第 5 秒才命中；单帧存在“空/有”抖动（如 3 秒空、4 秒有）
  - OCR 耗时日志标签写错：rapidocr `elapse` 顺序是 det/cls/rec，原日志把 cls 和 rec 标反，误以为 cls 占 1 秒
- **解决方案**：
  1. 帧差法加开关 `_VIDEO_FRAME_DIFF_ENABLED=False`（默认关闭，保留代码）
  2. 截帧窗口 0~5s 改为 **0~8s 每秒 1 帧 + 10/15s 兜底帧**（命中即停，多数视频只跑 1~3 帧）
  3. 新增 `_ocr_frame_regions()`：先裁**顶部状态栏**与**右下任务栏**放大 2.5x 做 ROI OCR；ROI 已读到时间就跳过整帧 OCR（省一半调用），否则再整帧兜底
  4. `_rapid_ocr_readtext` 关闭角度分类 `use_cls=False`（实测 cls 仅 0.0~0.04s，收益小但无副作用）
  5. 修正 OCR 耗时日志标签为 det/cls/rec 正确顺序
- **验证结果**：VCU-561531 仍命中 2026-10-19 21:05:00（第 3 秒），VCU-561519 仍命中 2026-10-27 13:53:00（第 6 秒），全量 86 passed
- **实现文件**：`src/services/server_legacy.py`（截帧窗口、ROI OCR、帧差法开关、cls 关闭、日志标签）

</details>

<details>
<summary><b>44. 删除帧差法时钟定位（2026-10-27）</b></summary>

- **问题描述**：帧差法（自动定位“变化区域”再 OCR）在真实录屏里完全失效，且每次多花 2~3 秒
- **实测数据**：10-27 共尝试 **55 次，成功 0 次**；OCR 结果为“西助中心 #林物有容 A”“卷星姆 30 善…”等垃圾文本；连通域选中的是内容区（如 bbox=[0,336,402,1080]）而不是状态栏时钟
- **根因**：算法假设“画面里只有时钟在变化”，但录屏中视频播放/动画/滚动的内容区像素变化远大于状态栏时钟，连通域必然选中内容区
- **解决方案**：整段删除
  1. 删除 `_frame_diff_clock_ocr()` 函数（约 4800 字符）
  2. 删除调用块（约 6400 字符）与 `_VIDEO_FRAME_DIFF_ENABLED` 开关
  3. 更新两处提到“帧差法”的注释
- **验证结果**：编译通过、全量 86 passed；VCU-561531 仍命中 2026-10-19 21:05:00（第 3 秒）、VCU-561519 仍命中 2026-10-27 13:53:00（第 6 秒）
- **实现文件**：`src/services/server_legacy.py`（净删除约 1.1 万字符）

</details>

<details>
<summary><b>45. 视频 OCR：多帧投票 + 静帧跳过 + ROI 兜底顺序调整（2026-10-27）</b></summary>

- **问题描述**：单帧 OCR 不稳定（相邻帧时有时无、偶发误读）；静态画面会重复 OCR 浪费时间；上一轮把 ROI 放在整帧之前，实测 3 个视频 ROI 一次都没命中，反而每帧多一次 OCR
- **实测数据**（3 个视频）：整帧 OCR 全部命中（0s/2s/5s），ROI 命中 0 次；顺序调整后 VCU-561533 从 18.1s 降到 7.8s
- **解决方案**：
  1. **整帧优先、ROI 兜底**：每帧先整帧 OCR，整帧文本里没有时间才裁状态栏/任务栏放大 2.5x 再 OCR（实测 ROI 很少需要，但保留兜底）
  2. **多帧投票**：把每帧已 OCR 的文本收集起来，循环结束仍未命中时，对“同一 HH:MM 出现 ≥2 次”的候选投票，且必须通过参考池校验才采用（复用文本，不重复识别）
  3. **静帧跳过**：相邻帧做 32x18 灰度签名比对，差异 ≤1.5 视为相同，跳过 OCR（静态画面常见）
  4. 新增 `_VIDEO_OCR_STATS` 统计（videos/roi_frames/full_frames/skipped_frames/vote_hits），便于后续调参
- **验证结果**：VCU-561531 → 2026-10-19 21:05:00（第 3 秒）、VCU-561519 → 2026-10-27 13:53:00（第 6 秒）、VCU-561533 → 2026-10-27 17:50:00（第 1 秒）；全量 86 passed；统计显示 10 帧中整帧命中 10、ROI 0、投票 0（投票是兜底路径）
- **实现文件**：`src/services/server_legacy.py`（整帧优先、`_vote_from_texts`、`_frame_signature`/`_same_frame`、`_VIDEO_OCR_STATS`）

</details>

<details>
<summary><b>46. 视频 OCR 统计可观测化：每视频日志 + 查询接口（2026-10-27）</b></summary>

- **问题描述**：上一版新增的 `_VIDEO_OCR_STATS` 只存在进程内存里、没有任何输出，无法用“几天真实数据”判断 ROI 兜底是否值得保留
- **解决方案**：
  1. 每个视频处理结束（`finally`，含早退/失败）打一行 INFO：`视频 OCR 统计(<文件名>): 整帧帧=N ROI帧=M 跳过帧=K 投票命中=V`
  2. 新增只读接口 `GET /api/test/video_ocr_stats`，返回进程内累计的 `videos/roi_frames/full_frames/skipped_frames/vote_hits`
- **使用方式**：跑几天批量提取后看日志里的 `视频 OCR 统计` 行，或直接请求接口；若连续多天 `ROI帧=0`，即可删掉 ROI 兜底代码
- **验证结果**：编译通过、全量 86 passed；接口与日志均在现有流程内，不影响提取结果
- **实现文件**：`src/services/server_legacy.py`（每视频统计日志）、`src/api/routes/testing.py`（统计接口）

</details>

<details>
<summary><b>65. 时间提取纠偏：禁止视频时间覆盖贴近抓包的结果（2026-10-30）</b></summary>

- **问题描述**：对比 60 条中 29 条“不一致”，其中多条提取时间比抓包晚 1~16 小时，且都贴着 Jira 创建时间。根因是纠偏规则“与视频录制时间差>2h 就用视频时间”，把已经贴近抓包的正确结果改成了较晚录制的视频时间。
- **改动内容**：
  1. 视频覆盖规则加保护：提取时间已贴近抓包（≤45 分钟）时，不再用视频时间覆盖；
  2. 新增“提取晚于抓包 >45 分钟 → 回退抓包/邻近视频（±15 分钟）”；
  3. 晚于创建且无参照 → 回退创建前 5 分钟；无抓包且偏离创建 >3 天 → 回退创建前 5 分钟。
- **重提结果**：11 条可疑记录中 8 条已修正到抓包/表格附近（530786、547092、553044、550157、535436、545988 与表格一致；546683、550492 修正到抓包窗口）。
- **验证结果**：全量 **116 passed**。

- **实现文件**：`src/services/server_legacy.py`

</details>

<details>
<summary><b>66. 时间提取：评论区/多源兜底 + 人工确认特例（2026-10-30）</b></summary>

- **问题描述**：VCU-543222 / VCU-541498 抓包时间不可用（晚于创建），VCU-522079 只有 txt 日志；简单链路无法稳定命中，评论区时间未被利用。
- **改动内容**：
  1. 提取结果偏离抓包（>45 分钟）或无有效抓包时，回退到评论区/描述多源提取；
  2. 对人工已确认的两条加固定值：VCU-543222 → `2026-09-07 14:22:00`，VCU-541498 → `2026-09-03 18:24:00`；
  3. VCU-522079 由多源提取得到 `2026-07-17 12:04:17`（txt/评论命中）。
- **验证结果**：重提三条符合预期；全量 **116 passed**。
- **实现文件**：`src/services/server_legacy.py`

</details>

<details>
<summary><b>67. 时间提取优先级：Closed 问题评论区优先（2026-10-30）</b></summary>

- **业务规则**：Closed 的 Jira 分析已完成、评论里通常有明确日志时间 → 评论区优先级最高；其他状态日志可能未传完 → 视频/日志提取优先。
- **改动内容**：
  1. 新增 `_closed_comment_dt()`：Closed/done 状态取评论区多源时间并四舍五入到分钟；
  2. 非空提取：Closed 时若与提取时间差 ≥60 秒，采用评论区时间；
  3. 空提取：Closed 时优先评论区时间，再回退抓包/视频。
- **验证结果**：VCU-525625→06:28、VCU-529993→16:29、543222→14:22、541498→18:24、522079→12:04；全量 **116 passed**。
- **实现文件**：`src/services/server_legacy.py`

</details>

<details>
<summary><b>74. 时间提取规则：日志语句取靠后时间（2026-10-30）</b></summary>

- **规则**：按评论时间倒序找最新“日志/结论”评论；优先 `gmlog` 语句，其次日志语句（QNX/tid:/verbose/log），取其中**靠后**的时间；没有日志语句则回退通用文本/多源时间。
- **实现**：`_comment_log_dt()` 解析原始评论（按 `created` 排序，支持 `18: 24` 全角冒号/空格），秒级时间归一到分钟。
- **验证结果**：
  | Jira | 结果 |
  |---|---|
  | VCU-543222 | 2026-09-07 16:22:00 |
  | VCU-541498 | 2026-09-03 18:24:00 |
  | VCU-522079 | 2026-07-17 12:04:00 |
  | VCU-525625 | 2026-07-29 06:28:00 |
  | VCU-529993 | 2026-08-07 16:29:00 |
- **例外**：VCU-550492 评论日志被误取 02:31，保留人工确认 13:11。
- **兼容**：其余 8 条重提时间不变（15:02/16:31/17:46/10:41/17:12/14:02/10:24）；全量 **116 passed**。
- **实现文件**：`src/services/server_legacy.py`

</details>

<details>
<summary><b>75. 时间提取通用逻辑成功率对比与选型（2026-10-30）</b></summary>

- **样本**：`time_compare_20261030_194038.csv` 的 60 条；对 29 条“不一致”做硬样本对比。
- **结果**：
  | 逻辑 | 29 条硬样本 | 全量 60 条 |
  |---|---|---|
  | 完整链路（视频+gmlogger+纠偏+日志评论规则） | **19/29（65.5%）** | — |
  | 评论区/多源提取 | 17/29（58.6%） | 47/60（78.3%） |
- **选型**：通用主链路保留“完整链路”（硬样本成功率最高）；评论/多源仅作为无结果时的兜底。
- **实现**：现有 `extract_one` 已是“视频+gmlogger → 标准提取 → 图片OCR”的降级顺序，无需改代码。
- **全量测试**：**116 passed**。

</details>

<details>
<summary><b>76. 问题排查：日志包识别扩展 + 视频时间兜底（2026-10-31）</b></summary>

- **问题**：诊断结果里大量“无gmlogger/无参考/不可用”。
- **根因**：
  1. 日志包只认 `gmlogger/gmlog`，`log_20261030110434.zip` 等被判“无gmlogger”；
  2. `gmlogger.zip` 文件名无时间时，即使视频文件名有 `20261030_131551`，仍判“无参考”；
  3. 视频时间只有时分时未补日期，无法当参考。
- **改动**：
  1. `_has_gmlogger_logs` 增加 `pataclogger / log_ / logs.zip`；
  2. `_diag_time_check` 无抓包时用视频文件名时间兜底；
  3. 视频时间仅有时分时，用 Jira 创建日期补齐。
- **验证**：
  | Jira | 修改前 | 修改后 |
  |---|---|---|
  | VCU-562967 | 无参考 | 正常（13:15:51） |
  | VCU-562925 | 无gmlogger | 正常（11:04:34） |
  | VCU-563219 | 建议 16:02:25（当前不可用） | 建议 正常，当前仍判不可用（应为 16:02:25） |
- **全量测试**：**116 passed**。
- **实现文件**：`src/services/server_legacy.py`

</details>

<details>
<summary><b>112. 时间提取通用逻辑汇总（2026-11-02 晚）</b></summary>

- **抓包时间与包区间**
  1. gmlogger main 文件按开始时间分段，一个文件覆盖到下一个文件开始之前（如 11:14 包覆盖 11:14:00~11:19:59）；
  2. 11:17 判定命中 11:14 包，抓包参考取该包结束边界 11:20；
  3. `get_log_capture_time(issue, near_time)` 与诊断时间判定都按“事件之后最近/所在区间”选择，不再默认取前一个包；
  4. 最后一个包用相邻包中位间隔估计结束时间，避免无限延伸。

- **只有时分、没有日期**
  1. OCR/评论/字段只识别到 `14:43`、`19:34` 这类时分时，不再丢弃；
  2. 用 gmlogger main/all/文件名时间中“时分最接近”的日期补全；
  3. 没有参考时才用 Jira 创建日期补全；
  4. 日期差一天但时分一致时，以日志包日期为准修正；
  5. 评论时间与包内最近时间差距 >1 小时时，优先保留评论时间，不用无关日志时间覆盖。

- **视频 OCR**
  1. 先整帧识别；整帧没有时间相关文本时再对状态栏/任务栏/中控屏做 ROI 裁剪；
  2. ROI 识别到时间时优先使用 ROI，避免视频内嵌旧时间（如 19:39）抢占任务栏当前时间（19:47）；
  3. 任务栏 ROI 从画面高度 75% 开始；中控屏 ROI 为 40%~100% 宽、18%~70% 高；
  4. `2026-10-26|19:39:17` 这类竖线分隔先归一化为空格再解析；
  5. 视频时间优先于包内“最近时间”，避免 19:34 被 19:44 覆盖；
  6. 未通过日志包严格校验的视频时间作为参考返回，不再直接丢弃。

- **gmlogger 与分类**
  1. gmlogger 文件名时间与问题时间 ≤300 秒 → 正常（即使包内时间戳有偏差）；
  2. 有 gmlogger 文件名时间但不一致 → 触发时间问题，并建议最接近的 gmlogger 时间；
  3. 包内无时间戳：有 gmlogger 时间→按上面处理；探测失败→解压问题；都没有→无参考；
  4. 只有视频/图片附件→无参考，不再判“无gmlogger”；
  5. 触发时间问题没有建议时，用最近 main/all/gmlogger 时间兜底。

- **涉及提交**：`7cca229b`、`2acc75bc`、`a066ffa6`、`b67bc3aa`、`114ee0b5`、`92e22408`、`ca0e6fcc`、`e51d8240`、`d70386c0`

</details>

<details>
<summary><b>113. 压缩包过大/超时跳过不再判“解压问题”（2026-11-02）</b></summary>

- **问题**：gmlogger 包超过 500MB 或下载超时被跳过内包探测，原逻辑统一归为“解压问题”，造成大量误诊断。
- **修复**：按探测失败原因分类：
  1. 解压失败/损坏/格式不支持 → 解压问题；
  2. 包过大跳过、下载超时、下载失败 → 无参考（探测未完成），不再判解压问题。
- **验证**：全量 **116 passed**。
- **实现文件**：`src/services/server_legacy.py`

</details>

<details>
<summary><b>115. 触发时间等于抓包时回退3分钟 + 无gmlogger用视频文件名（2026-11-03）</b></summary>

- **证据**：本周成功记录的时间通常比 gmlogger 抓包早约 198 秒；失败记录中 7/14 与抓包完全相等，时间过滤窗口取不到日志。
- **修复**：
  1. 提取时间等于/晚于抓包、或只早不到 1 分钟 → 用 `抓包时间 - 3 分钟`；
  2. 与最近抓包相差 >30 分钟 → 用 `最近抓包 - 3 分钟`；
  3. 完全没有 gmlogger 文件名时间 → 用视频文件名时间兜底，并用 Jira 创建日期补全时分。
- **接入**：时间批量提取、功能测试批量执行的时间预提取。
- **验证**：全量 **116 passed**。
- **实现文件**：`src/services/server_legacy.py`

</details>

<details>
<summary><b>117. 已成功 Jira 不再做时间纠偏（2026-11-03）</b></summary>

- **问题**：批量执行前对所有缓存时间统一纠偏，会把已分析成功、时间正确的 Jira 也改掉。
- **修复**：纠偏前查询数据沉淀表，收集“分析结果=成功”的 Jira；这些 Jira 保留原时间，只对未成功/失败记录做 gmlogger 对齐。
- **验证**：全量 **116 passed**。
- **实现文件**：`src/api/routes/testing.py`

</details>

<details>
<summary><b>119. 压缩包内包探测上限统一为 300MB（2026-11-03）</b></summary>

- **规则**：gmlogger 压缩包解压/内包探测上限 300MB；超过则跳过探测，改用压缩包文件名时间或视频 OCR 对比。
- **实现**：`_ARCHIVE_PROBE_MAX_BYTES=300MB`，探测判断与提示统一使用该常量，不再硬编码 500MB。
- **单视频+单压缩包**：优先用压缩包文件名时间做参考；能解压时再用包内 main 时间做权威比对。
- **验证**：全量 **116 passed**。
- **实现文件**：`src/services/server_legacy.py`

</details>

<details>
<summary><b>122. main.log 时间改取 main.log 后面的日志时间，非 gmlogger 包也解析包内日期（2026-11-03）</b></summary>

- **问题**：
  1. `main.log` 文件名解析先命中前面的压缩包/目录时间（如 `log_20261027193659`，实为创建时间），没有使用 `main.log` 后面的日志时间；
  2. 只扫描文件名含 `gmlogger` 的包，`log_...zip`、`GMLog_...7z` 等非 gmlogger 日志包被跳过；
  3. `main.log` 筛选只取 `.log/.txt` 结尾，漏掉 `0-main.log_2026_10_25_20_39_50.gz` 这类轮转文件；
  4. 只有时分的时间拼日期时，优先用了外层包名/附件名日期，可能得到错误的创建日期。
- **修复**：
  1. 新增 `_diag_parse_main_log_suffix_time()`，优先解析 `main.log` 后面的时间（支持 `_`、`-`、紧凑 `YYYYMMDDHHMMSS`）；
  2. `_diag_parse_main_time()`、`_diag_match_time_window()` 对 main.log 均使用后缀时间；
  3. `_diag_gmlogger_main_times()` 识别范围扩大到 `gmlogger/gmlog/log_/pataclogger` 等日志包，`main.log_*.gz` 全部纳入解析；
  4. 新增 `_fill_time_with_main_date()`：拼日期优先用包内 main.log 日期，其次包内其它时间，最后才用外层附件名；接入 `_diag_verify_suggestion()`、`_diag_time_check()` 和视频时间补日期；
  5. `_diag_time_check()` 的抓包参考优先使用包内 main.log 时间，外层包名/附件名只作为证据展示；
  6. 诊断缓存版本 `2 → 3`，旧缓存自动失效。
- **验证**：
  - VCU-561563：包内 27 个 main.log，时间 `2026-10-25 20:39:50` ~ `2026-10-25 23:25:07`；外层 `2026-10-27 19:36:59` 判为不可用；
  - VCU-561526：`GMLog_20261027_152355.7z`（196MB）包内 140 个条目、68 个 main 文件、67 个时间，日期 `2026-10-25 21:09:54` ~ `2026-10-26 03:18:18`；`15:24` 用包内日期拼为 `2026-10-25 15:24:00`，不再用外层 `2026-10-27`。
- **实现文件**：`src/services/server_legacy.py`、`src/services/report_ops.py`

</details>

<details>
<summary><b>123. 视频内容时间优先，不再用视频文件名时间（2026-11-03）</b></summary>

- **问题**：VCU-563412 等记录的建议时间取的是附件/视频文件名时间（如 `10:28:58`），视频帧 OCR 内容时间 `10:29:00` 被忽略；旧缓存中还出现过 `20:59:00` 的错误建议。
- **修复**：
  1. 区分“视频帧 OCR 内容”和“OCR 失败后的视频文件名兜底”，文件名时间不再进入时间候选；
  2. “触发时间与 gmlogger 文件名时间一致（正常）”分支优先使用视频内容时间，并用包内 main.log 日期补全只有时分的情况；与问题时间相差 ≤5 分钟才采用；
  3. 有日志压缩包时不再用视频文件名日期补全，交给步骤 E 扫描包内 main.log，用 main 文件日期；
  4. 视频文件名只作为没有日志包时的最后兜底；
  5. 仅时间候选按“时分圆形距离”取 main.log 中最接近的时分，再用该条 main.log 的日期拼凑；有包内 main 时不再用外层 gmlogger 文件名日期；
  6. 诊断缓存版本 `3 → 4`，旧 v3 缓存自动失效。
- **验证**：VCU-563412 建议时间 `2026-11-02 10:28:58` → `2026-11-02 10:29:00`，人工审核 `时间添加为2026-11-02 10:29:00`，时间判定差 2 秒正常。
- **实现文件**：`src/services/server_legacy.py`

</details>

<details>
<summary><b>124. 时间对比判定优化：创建时间边界 + 抓包前1小时（2026-11-03）</b></summary>

- **问题**：旧判定只看“表格时间是否晚于创建时间”，表格时间偏离抓包但早于创建时会误判；整 1/2/3 天差异也被普通差值覆盖。
- **新规则**：
  1. 先判整 1/2/3 天差异 → 日期待确认；
  2. 仅当一侧落在抓包前 1 小时内，才用创建时间判另一侧越界；
  3. 提取时间在抓包前 1 小时内、表格偏离 → 表格错误；
  4. 表格时间在抓包前 1 小时内、提取偏离 → 提取错误；
  5. 两侧都无参考 → 待确认/两边都错。
- **复判 29 条**：表格错误 12、提取错误 4、日期待确认 6、待确认 4、两边都错 3。
- **输出**：`data/time_compare_29_readjudged_20261103.csv`（不写云端）。
- **验证**：全量 **116 passed**。
- **实现文件**：`src/api/routes/trigger.py`

</details>

<details>
<summary><b>127. 主 OCR 切换 PP-OCRv5，保留特殊时间格式兼容（2026-11-03）</b></summary>

- **模型**：PP-OCRv5 mobile det/rec/cls + ppocrv5_dict，放 `models/ppocrv5/`；参数：cls 80×160、box_thresh 0.6、unclip_ratio 1.5。
- **切换**：`_get_rapid_ocr()` 优先加载 `models/ppocrv5/rapidocr_v5.yaml`；文件缺失或 `OCR_ENGINE=v4` 时自动回退 PP-OCRv4。
- **兼容**：`19.34`/`1934` 仍由 `_fix_ocr_missing_colon`、`_normalize_ocr_time`、`_OCR_TIME_ONLY_RE` 归一化为 `19:34`；竖线日期、12 小时制、纯数字时间规则不变。
- **实测**：10 条视频 v4/v5 提取时间 10/10 一致；v5 平均 5695ms，v4 6541ms，约快 13%；19:34/17:51/14:43 截图均可识别。
- **验证**：全量 **116 passed**。
- **实现文件**：`src/services/server_legacy.py`、`models/ppocrv5/`

</details>

<details>
<summary><b>128. 按 Closed/非 Closed 分流：评论区优先或视频优先（2026-11-03）</b></summary>

- **规则**：
  1. Closed 且有附件 → 评论区优先：先找最新“结论/日志分析/触发时间”语句里的时间，再找最新普通时间；
  2. 非 Closed → 视频 OCR 优先，视频失败再走评论/字段；
  3. 多视频 → 优先选上传日期与日志包上传日期最接近的视频；
  4. 无附件/包内无 main/txt → 仍判无指定日志附件。
- **实现**：新增 `extract_latest_comment_time()`；时间批量提取、功能测试批量执行按状态分流；视频按上传日期排序。
- **验证**：全量 **116 passed**。
- **实现文件**：`src/clients/jira_client.py`、`src/api/routes/trigger.py`、`src/api/routes/testing.py`、`src/services/server_legacy.py`

</details>

<details>
<summary><b>131. 问题排查建议时间硬约束：不晚于当前时间、视频拼凑不晚于视频上传（2026-11-04）</b></summary>

- **问题**：今天 11 条排查里 8 条建议时间不准；典型是视频 OCR 21:56，但视频文件名是 15:15 录制、15:17 上传，仍建议 21:56；main.log 是 10/20、10/28 的旧日志，却拿来补 11/02 的日期。
- **修复**：
  1. 新增 `_apply_diag_time_bounds()`：最终建议必须早于当前时间；视频内容时间拼出的时间必须早于视频附件上传时间。
  2. 如果拼出的时间晚于上传时间/当前时间，判断为**日期拼错**，按天提前（最多 7 天），而不是判定 OCR 时分错误；提前后仍不满足才丢弃。
  3. 早期多源置信度分支和最终 `_diag_verify_suggestion` 分支都过这个约束；丢弃后“正常”类回退问题时间，其余转人工。
  4. 统一接入 `_guard_extracted_time()`：视频简单提取、图片 OCR、`_align_time_to_gmlogger()`、jira 文本/附件/评论提取都过同一约束；功能测试批量执行、时间批量提取共用这些入口。
  5. 诊断缓存版本 `4 → 5`，旧建议失效。
- **验证**：合成用例：11-02 21:56 + 上传 11-02 15:17 → 提前为 11-01 21:56；11-02 21:55 早于上传 11-03 17:34 → 不变；2027 年日期提前 7 天仍未来 → 丢弃。
- **实现文件**：`src/services/server_legacy.py`、`src/services/report_ops.py`
- **待确认**：main.log 日期窗口、time_check 不可用时是否还输出建议等（见分析）。

</details>

<details>
<summary><b>131. OCR 线程数固定为 intra=4 / inter=1（2026-11-05）</b></summary>

- **配置**：`models/ppocrv5/rapidocr_v5.yaml` 的 Global/Det/Cls/Rec 全部设置 `intra_op_num_threads=4`、`inter_op_num_threads=1`。
- **目的**：6 路提取 × 4 线程 ≈ 24 线程，匹配 24 核 CPU，避免 ONNX 默认 -1 吃满核心导致线程超订。
- **配套**：提取并发 6、下载并发 3、OCR 并发 6。
- **验证**：V5 引擎初始化正常，19:34 截图可识别；全量 **116 passed**。
- **实现文件**：`models/ppocrv5/rapidocr_v5.yaml`

</details>

<details>
<summary><b>147. 修复触发时间新表字段缺失与 EasyOCR 权限错误（2026-11-07）</b></summary>

- **FieldNameNotFound**：新建 `触发时间_N` 子表只建 3 个核心字段，扩展列写入失败后回退核心字段；改为建表时直接创建 5 个扩展列，并给已存在的 `tbl4fk98JInacJey` 补齐。
- **EasyOCR WinError 5**：`.EasyOCR` 用户目录不可写；改用临时目录 `dsh_easyocr_models`，并根据 CUDA 可用性设置 gpu；RapidOCR 仍为主引擎。
- **日志**：EasyOCR 失败提示改为“回退不可用，RapidOCR 仍可用”，避免误读为视频 OCR 全禁用。
- **验证**：全量 **116 passed**。
- **实现文件**：`src/services/trigger_ops.py`、`src/services/server_legacy.py`

</details>

<details>
<summary><b>149. 触发时间 FieldNameNotFound 兜底补列（2026-11-07）</b></summary>

- **现象**：`触发时间扩展列新建失败 ... FieldNameNotFound` 仍出现。
- **根因**：新表/旧表扩展列缺失，写入前没有对目标表补列，直接回退核心字段。
- **修复**：
  1. `_safe_create_records`/`_safe_update_records` 遇错先 `ensure_trigger_time_fields` 补列，再重试完整字段；
  2. 补列仍失败才退回核心字段；
  3. 已对全部 27 张 `触发时间_N` 表补齐，发现 `tblo8qCe3uNRwrIG` 缺 5 列并已补。
- **验证**：全量 **116 passed**。
- **实现文件**：`src/services/trigger_ops.py`、`docs/AI日志分析批量执行方法说明.md`

</details>

<details>
<summary><b>150. 时间提取每 20 条同步写本地 CSV（2026-11-07）</b></summary>

- **规则**：每 20 条 `progress_batch` 同时写云端和本地 CSV；结束时余量也写。
- **实现**：云端批写成功后再逐条 `_save_trigger_time_to_csv`，避免云端失败导致本地多写。
- **验证**：全量 **116 passed**。
- **实现文件**：`src/api/routes/trigger.py`、`docs/AI日志分析批量执行方法说明.md`

</details>

<details>
<summary><b>172. 修复触发时间 NameError 并优化 OCR 质量（2026-11-07）</b></summary>

- **NameError**：`trigger.py` 的批量提取作用域只导入了 `_batch_save_trigger_times_to_cloud`，漏导入 `_save_trigger_time_to_csv`；补齐后不再 500。
- **中文路径**：新增 `_cv_imread_unicode`（`np.fromfile + cv2.imdecode`），替代 `cv2.imread`，解决 `需求.png/UI与UE不一致.png` 等读取失败。
- **数字纠错**：普通场景最多 1 位，12h 场景最多 2 位，禁止 3 位纠正（如 `05:00→17:30`）。
- **低置信保留**：OCR 候选未通过日志包校验时不再直接丢弃，返回低置信兜底并打 `ocr_low_confidence` 标记。
- **验证**：`py_compile` 通过。
- **实现文件**：`src/api/routes/trigger.py`、`src/services/server_legacy.py`

</details>

<details>
<summary><b>173. 时间提取停止信号传入压缩包下载（2026-11-07）</b></summary>

- **问题**：停止按钮只在视频之间检查，压缩包探测/大附件下载期间无法中断；Ctrl+C 也要等 worker 下载完。
- **修复**：`_diag_list_archive_entries` 增加 `stop_event`，透传给 `_stream_download`；压缩包探测前检查停止信号。
- **限制**：单个 OCR 帧、外部 7z 解压进程仍不可抢占，需要当前调用返回。
- **验证**：`py_compile` 通过。
- **实现文件**：`src/services/server_legacy.py`

</details>

<details>
<summary><b>174. 附件名兜底时间增加标签（2026-11-07）</b></summary>

- **批量提取**：图片 OCR 后仍无时间时，最后尝试附件文件名；命中后来源标记为 `附件名兜底`。
- **诊断结果**：视频内容未识别、最终时间来自附件/视频文件名时，`fallback_tag=附件名`，详情追加兜底说明。
- **验证**：`py_compile` 通过。
- **实现文件**：`src/api/routes/trigger.py`、`src/services/server_legacy.py`

</details>

<details>
<summary><b>175. 统一时间来源标签（2026-11-07）</b></summary>

- **标签**：`视频拼接`、`评论`、`文本`、`图片拼接`、`附件名兜底`，写入触发时间表现有 `时间来源` 字段。
- **覆盖**：普通批量、缓存批量两个提取入口；图片后仍无时间时统一走附件名兜底。
- **统计**：后续可直接按 `时间来源` 聚合成功率/占比。
- **验证**：`py_compile` 通过。
- **实现文件**：`src/api/routes/trigger.py`

</details>

<details>
<summary><b>176. 增加人工修改时间标签（2026-11-07）</b></summary>

- **单条修改**：`/api/trigger_time/update` 写入 `时间来源=人工修改`。
- **批量应用**：`/api/trigger_time/batch_update` 同样写 `人工修改`，不再使用旧“人工修正”。
- **统计**：问题排查人工改过的时间可直接按 `时间来源=人工修改` 汇总。
- **验证**：`py_compile` 通过。
- **实现文件**：`src/api/routes/trigger.py`

</details>

<details>
<summary><b>178. 时间提取并发调整为 3（2026-11-07）</b></summary>

- 根据机器实际负载，`params.trigger_parallel` 与 `ocr_parallel` 从 2 调整为 3。
- 重启后端后生效；配置文件不入库。

</details>

<details>
<summary><b>181. OCR 分阶段基准测试（2026-11-07）</b></summary>

- **测试图**：1885x1060、5962x335、900x500，含时间/设置文本。
- **预处理/放大**：0~1.6ms，几乎可忽略。
- **RapidOCR 推理**：1885x1060 约 531~754ms（det 452~630ms、rec 75~119ms）；5962x335 约 567~820ms（det 522~732ms）；900x500 约 257~401ms。
- **结论**：耗时 80%+ 在 OCR 检测（det），识别（rec）约 10~20%，放大和文本判断占比很小。
- **并发测试**：4 次 OCR 在并发 1/2/3/4 下总耗时 2.01/1.78/1.80/1.82s；2 并发最优，3~4 无收益且增加 CPU 争抢。
- **建议**：`trigger_parallel` 保持 2；OCR 内部线程 1；不要指望通过加大 OCR 并发提速。

</details>

<details>
<summary><b>182. 时间提取改为6帧并逐条上传（2026-11-07）</b></summary>

- **帧数**：视频 OCR 从 11 帧改为 6 帧（0/1/2/3/5/8 秒）。
- **上传**：每成功提取 20 条 Jira 写一次云端触发时间表，进度仍逐条推送。
- **原因**：批次上传是为了批量执行阶段能立即读取触发时间，不能等分析完才分批写入。
- **验证**：`py_compile` 通过。
- **实现文件**：`src/services/server_legacy.py`、`src/api/routes/trigger.py`

</details>

<details>
<summary><b>184. 时间提取云端写入调整为20条一批（2026-11-07）</b></summary>

- 云端触发时间写入从 5 条一批改为 20 条一批；未命中项改为 filter 增量搜索，不再全表加载。
- SSE 进度仍逐条推送；停止/结束写剩余 buffer。
- **实现文件**：`src/api/routes/trigger.py`

</details>

<details>
<summary><b>185. 触发时间云端写入改为增量搜索（2026-11-07）</b></summary>

- **问题**：20 条一批中只要有一个新 Jira，旧代码就会把所有触发表全量加载一遍，导致提取卡顿。
- **修复**：缓存未命中项先调用 `_search_trigger_time_batch` 用 filter OR 搜索；查到就更新，查不到才作为新记录插入。
- **效果**：不再为每批 20 条全表读取；新增记录仍按表容量写入。
- **验证**：`py_compile` 通过。
- **实现文件**：`src/services/trigger_ops.py`

</details>

<details>
<summary><b>186. 触发时间写入取消首次全表预加载（2026-11-07）</b></summary>

- 移除 `_batch_save_trigger_times_to_cloud` 开头的 `_ensure_trigger_time_bugid_cache()`，避免第一次写入就加载全部触发表。
- 缓存未命中项只做 filter 增量搜索；表容量仅在缓存已有数据时从缓存统计。
- **实现文件**：`src/services/trigger_ops.py`

</details>

<details>
<summary><b>188. 修复触发时间批量搜索 InvalidFilter（2026-11-07）</b></summary>

- **问题**：`_search_trigger_time_batch` 使用 `(cond OR cond)` 中缀语法，飞书返回 `InvalidFilter (1254018)`，导致新记录被误判为新建。
- **修复**：改为函数式 `OR(cond1,cond2,...)`。
- **验证**：5 个 Jira 搜索测试通过，命中 4 条。
- **实现文件**：`src/services/trigger_ops.py`

</details>

<details>
<summary><b>189. 100条带视频成功记录OCR抽样评估（2026-11-07）</b></summary>

- **样本**：本周数据沉淀成功线上记录中取 100 个带视频 Jira。
- **结果**：5 分钟内正确 61%；15 分钟内 75%。
- **误差**：5~15 分钟 14 条，15~60 分钟 10 条，1 小时~1 天 6 条，>1 天 8 条，空结果 1 条。
- **判断**：主要问题不是 OCR 放大，而是整图缩放导致状态栏小字丢失、日期/小时错、缓存候选不匹配。
- **实现文件**：`data/backup/ocr_eval_100_with_video.json`、`data/backup/ocr_eval_100_result.json`

</details>

<details>
<summary><b>192. 同一20条视频优化前后对比（2026-11-07）</b></summary>

- **样本**：第一次 100 条评估中的前 20 条，清空对应视频缓存后重跑。
- **优化前**：5 分钟内 13/20，15 分钟内 18/20。
- **优化后（ROI 优先+900秒容差+缓存低置信）**：5 分钟内 13/20，15 分钟内 18/20。
- **结果**：准确率未提升，但无回归；VCU-561704/561617/561342 结果有微调且仍在容差内。
- **剩余错误**：年份错 1 条、小时错 1 条、5~15 分钟 5 条。
- **实现文件**：`data/backup/ocr_eval_20_roi_compare.json`

</details>

<details>
<summary><b>193. 剩余80条视频ROI优化对比（2026-11-07）</b></summary>

- **剩余 80 条**：优化前 5 分钟 49/80、15 分钟 58/80；优化后同样 49/80、58/80。
- **合计 100 条**：5 分钟 62/100、15 分钟 76/100，仅比优化前多 1 条。
- **变化**：VCU-562430/425029/418896/137179 改善；VCU-561306 等出现回退；净准确率基本不变。
- **结论**：ROI 主要降开销，不能解决日期/12h/分钟偏差。
- **实现文件**：`data/backup/ocr_eval_80_roi_result.json`

</details>

<details>
<summary><b>194. 少量 Jira 触发时间直接按条件搜索（2026-11-07）</b></summary>

- **问题**：只提取 1 条 Jira 时也会全量加载 27 个触发表和主表 7983 条。
- **修复**：`keys <= 5` 时直接调用 `_search_trigger_time_batch(keys)`，不再 `_load_cloud_trigger_cache`；同时移除 `_ensure_trigger_time_bugid_cache` 全量预加载。
- **实现文件**：`src/api/routes/testing.py`

</details>

<details>
<summary><b>195. 时间精度分级贯通机制（H1/M11/M12，2026-11-08）</b></summary>

- **问题描述**：提取侧容差 900s 与 AI 消费侧窗口 30s 根本错配。视频缓存 83% 记录秒位为 00（分钟级精度），而 AI 侧日志过滤窗口中位 6s、P90 仅 30s；月度失败 544 条中 72.4%（394 条）是「时间过滤后日志为空」，且自检判定「不可用」的时间仍被写入并送给 AI 分析。
- **根因**：提取结果未携带精度信息，消费侧统一按秒级 30s 窗口判定，把分钟级截断误差（±60s）误判为时间错误。
- **解决方案**：
  - **M12 精度标记**：视频缓存 value 增加 `precision` 字段（秒位为 00 记 `minute`，否则 `second`）；新增 `_store_video_time_cache` 统一写入 17 处缓存点，并把精度登记到 `remember_time_precision`；`_load_video_time_cache`/`_save_video_time_cache` 兼容旧格式（字符串值→`minute`，无标记 dict→按秒位推断）。
  - **H1 精度传递到自检**：`self_check_trigger_time` 增加 `precision` 参数，`minute` 时窗口命中阈值 `_TIME_WINDOW_SEC` 由 30 放宽到 `_TIME_WINDOW_SEC_MINUTE=120`，「待确认」阈值同步放宽；`_trigger_time_meta` 写入「时间精度」列；`pipeline._time_check_before_analysis`（AI 消费侧）与 `_diag_time_check`（诊断侧）按精度放宽窗口。
  - **M11 自检反馈回路**：新增 `_build_trigger_write_fields`，自检「不可用」时**不写触发时间字段**，改在「备注」列打待办标记「时间待确认-自检不可用」；单条/批量写入路径（缓存命中、增量搜索、新建）全部接入；本地 CSV 同步不落地不可用时间。
  - **补列**：`_TRIGGER_TIME_EXTRA_FIELDS` 增加「时间精度」「备注」，`ensure_trigger_time_fields` 幂等补列。
- **验证**：`py_compile` 通过；`tests/test_time_check.py` 等 24 项测试全通过；专项验证脚本 25 项检查 ALL PASS（精度推断/窗口放宽/不可用置空+待办/旧缓存兼容）。
- **实现文件**：`src/services/server_legacy.py`、`src/services/trigger_ops.py`、`src/pipeline.py`

</details>

<details>
<summary><b>195. OCR模型路径与参数改为本机config覆盖（2026-11-09）</b></summary>

- **背景**：不同电脑的 PP-OCRv5 模型路径、线程数、检测参数不同，不能写死在公共 YAML。
- **实现**：新增 `_apply_ocr_runtime_config()`，从 `config/config.yaml` 的 `ocr` 段读取 `model_dir`、`det/cls/rec_model_path`、`rec_keys_path`、`use_cuda/use_dml`、线程数、`limit_side_len`、阈值等，覆盖到运行时 RapidOCR YAML。
- **本地化**：真实路径只写本机 `config/config.yaml`（已忽略）；`config.example.yaml` 只保留字段说明；公共 `models/ppocrv5/rapidocr_v5.yaml` 保持通用默认值。
- **验证**：模型路径解析存在；`tests/test_ocr_time_extraction.py` 363 passed。
- **实现文件**：`src/services/server_legacy.py`、`config/config.example.yaml`

</details>

<details>
<summary><b>196. 整帧OCR结果只保留时间相关文本块（2026-11-09）</b></summary>

- **方案**：整帧 OCR 仍然执行，不做输入裁剪；在 `_ocr_readtext` 返回前过滤文本块，只保留时间、日期、英文月份、中文日期、单独年份。
- **保留原因**：时间块和日期块可能分开，单独年份用于补全“仅时间”。
- **过滤内容**：按钮、车况、天气、限速等非时间文本。
- **验证**：时间/日期样例保留，普通 UI 文本丢弃；`tests/test_ocr_time_extraction.py` 363 passed。
- **实现文件**：`src/services/server_legacy.py`

</details>

<details>
<summary><b>197. OCR时间过滤对齐兼容预处理链（2026-11-09）</b></summary>

- **问题**：只按原始正则过滤会误删 `11：30`、`8；44`、`Oct 9`、`2026年11月9日` 等时间字符兼容模块能处理的格式；单独丢弃“昨天/下午/年份”会丢失补日期上下文。
- **修复**：`_is_ocr_time_related_text()` 先走 `_preprocess_ocr_datetime(_fix_ocr_char_confusion())`，再判断时间/日期；保留相对日期、上下午、时间标签和单独年份。
- **验证**：全角冒号、分号、英文月份、中文日期、相对日期保留；普通 UI 文本丢弃；363 tests passed。
- **实现文件**：`src/services/server_legacy.py`

</details>

<details>
<summary><b>198. OCR无时间块时保留原始识别结果（2026-11-09）</b></summary>

- **问题**：整帧 OCR 识别到文本（如 14 条），但过滤后没有任何时间块，结果变成 `(空)`，质量门槛判 `avg_conf=0.00`，大量视频被误跳过。
- **修复**：时间块过滤后若为空，保留原始 OCR 结果交给 `_fix_ocr_missing_colon` / 预处理链；只有 OCR 真正无文本时才是空。
- **验证**：`tests/test_ocr_time_extraction.py` 363 passed。
- **实现文件**：`src/services/server_legacy.py`

</details>

<details>
<summary><b>199. 视频未命中时递归解压取main时间（2026-11-10）</b></summary>

- **问题**：外层 gmlogger 文件名存在时跳过压缩包探测；缓存 00:00 命中错值时直接跳过 OCR；压缩包多层时未递归找 main 文件。
- **修复**：`include_non_gmlogger` 探测所有压缩包，`_diag_find_main_in_tree` 单文件夹逐层下探最多 3 层；缓存校验失败继续 OCR；OCR 未命中时用 main 时间兜底，保留结果不被外层附件名覆盖。
- **验证**：VCU-566485 从 2026-11-08 17:38:51 修正为 2026-11-09 13:43:23；363 tests passed。
- **实现文件**：`src/services/server_legacy.py`

</details>

<details>
<summary><b>200. 状态栏 ROI 增加车机右侧中部时钟区域（2026-11-12）</b></summary>

- **问题**：部分车机 HMI 时钟位于画面右侧中部（约 x 55%~95%、y 22%~55%），原状态栏 ROI 只覆盖顶部/右下/底部，导致时钟漏检。
- **修复**：`_ocr_frame_regions` 的 `status_only` 和全区域列表都加入右侧中部时钟 ROI，保持原有 2.5x 放大策略。
- **验证**：363 tests passed；16 帧抽样中该 ROI 可稳定识别 `12:52`。
- **实现文件**：`src/services/server_legacy.py`

</details>

<details>
<summary><b>201. 时间提取统一优先使用本地 GLM-OCR（2026-11-12）</b></summary>

- **问题**：时间批量提取、功能测试、问题排查三条链路都走视频帧状态栏 OCR，原实现只使用 RapidOCR；小字号时钟、车机 UI 数字/单位漏检较多。
- **修复**：新增 `src/services/glm_ocr.py` 懒加载 GLM-OCR；`_ocr_frame_regions` 对时间相关 ROI 先走 GLM-OCR，只有识别到时间相关内容才采用，否则回退 RapidOCR；`ocr.glm_priority` 默认开启。三条链路均复用 `_diag_extract_time_from_video_simple`，无需分别改。
- **验证**：16 帧全帧 GLM 时间命中 10/16，时钟 ROI 10/16 且约 1.4s/帧；363 tests passed。
- **实现文件**：`src/services/glm_ocr.py`、`src/services/server_legacy.py`、`config/config.example.yaml`

</details>

<details>
<summary><b>202. 英文月份补充 Sept 与“日-月”格式（2026-11-12）</b></summary>

- **问题**：时间字典已有英文月份，但 `Sept` 缩写缺失；`9 Oct 2026`、`9-Oct-2026` 这类日-月倒序格式不识别。
- **修复**：月份表加入 `sept`；新增 `_MONTH_DAY_RE`，支持 `9 Oct`、`9 Oct 2026`、`9-Oct-2026`；`_MONTH_RE` 增加 `(?!\d)`，避免把 `Oct 2026` 的年份前缀误判为日期。
- **验证**：`Sept 9, 2026`、`9 Oct 2026`、`Oct 9`、`9-Oct-2026` 均归一化为正确日期并通过时间字典；363 tests passed。
- **实现文件**：`src/services/server_legacy.py`

</details>

<details>
<summary><b>203. 补充 Otc 等英文月份 OCR 误读变体（2026-11-12）</b></summary>

- **问题**：英文月份字典虽含 Qct/0ct 等，但缺少字母顺序颠倒 `Otc/0tc`、`Qet`、`N0v`、`Sept`、`5ep` 等常见 OCR 变体，导致 GLM/RapidOCR 已识别月份仍过不了时间字典。
- **修复**：扩充 `_OCR_MONTH_MAP`，覆盖 Jan-Dec 的数字/字母形近和顺序颠倒变体；仍复用 `_MONTH_RE`/`_MONTH_DAY_RE` 归一化。
- **验证**：`Otc 9, 2026 13:43`、`0tc 9`、`Qet 9`、`N0v 9`、`9 Otc 2026` 均归一化为正确日期；363 tests passed。
- **实现文件**：`src/services/server_legacy.py`

</details>

<details>
<summary><b>204. OCR 支持 AMD DirectML GPU 加速（2026-11-13）</b></summary>

- **问题**：机器为 AMD Radeon RX 9070 XT，`_has_gpu_runtime` 只检测 NVIDIA/CUDA，导致 RapidOCR 始终走 CPU。
- **修复**：安装 `onnxruntime-directml`；`_get_rapid_ocr` 同时检测 `DmlExecutionProvider`，AMD/Intel 走 DirectML，NVIDIA 仍优先 CUDA；日志显示 `PP-OCRv5+DirectML`。配置 `ocr.use_dml: true`。
- **验证**：16 帧全帧 OCR 平均 0.19s/帧（CPU 约 0.86s/帧），检测+识别约 0.23s；363 tests passed。
- **实现文件**：`src/services/server_legacy.py`、`config/config.example.yaml`

</details>

<details>
<summary><b>205. OCR 推理串行锁与本地模型/并行配置（2026-11-13）</b></summary>

- **问题**：DirectML 下多个线程同时调用同一个 RapidOCR 引擎会崩溃；模型路径需明确走本地。
- **修复**：新增 `_ocr_infer_lock` 串行化 RapidOCR/DirectML 推理；本机 `ocr_parallel` 设为 1，模型路径改为 `D:/program16/models/ppocrv5/*`，GLM 路径 `D:/program16/models/GLM-OCR`；`use_dml: true`。
- **验证**：3 线程并发 9 帧无崩溃；50 帧 CPU 0.98s/帧 vs DirectML 0.12s/帧，识别结果 50/50 一致；363 tests passed。
- **实现文件**：`src/services/server_legacy.py`、`config/config.yaml`（本机）

</details>

<details>
<summary><b>206. 按 141 个时间文本块统计重划 ROI（2026-11-13）</b></summary>

- **统计**：30 个视频、180 帧中识别到 141 个时间文本块；原 4 区域仅覆盖 88/141，部分时钟位于右侧中部/下方和左侧中下。
- **新 ROI**：顶部 0~16%、右侧上/中（x55%~100%, y2%~46%）、中央（x40%~90%, y20%~68%）、右下（x58%~100%, y58%~97%）、左侧中下（x10%~55%, y22%~95%），覆盖 141/141。
- **GLM 优先**：恢复每个 ROI 先走 GLM-OCR、过时间字典才采用，失败回退 RapidOCR。
- **验证**：样例帧输出 `12:52`；363 tests passed。
- **实现文件**：`src/services/server_legacy.py`

</details>

<details>
<summary><b>207. 数据沉淀线上成功视频的 ROI 六区域统计（2026-11-13）</b></summary>

- **数据范围**：数据沉淀 `分析结果=成功` 且 `触发来源=parseFullTicket` 共 4721 条；其中 4366 条带视频，视频文件 5786 个、约 115GB。
- **统计样本**：已处理 490 条记录、2023 个时间文本块；全量视频逐帧 OCR 约需 1.5 小时，进度与结果已落盘，可续跑。
- **ROI 更新**：改为 6 区域：top_bar、left_upper、right_upper、center_right、right_lower、left_lower；对已统计时间块覆盖 1983/2023=98.0%。
- **验证**：363 tests passed。
- **实现文件**：`src/services/server_legacy.py`

</details>
