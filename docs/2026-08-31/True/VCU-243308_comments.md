# VCU-243308 评论分析总结

## 排查结论

U盘挂载异常因代码回退后解决，根因与user10未绑定及mount状态未重置相关，当前问题已定位并验证通过。


## 排查过程分析

### 问题现象
U盘插入设备后无法被识别，XVR服务启动后持续检测到U盘未挂载，最终需回退代码并升级版本才解决。

### 排查过程
| 步骤 | 排查动作 | 结果 | 关键证据 |
|------|----------|------|----------|
| 1 | 上传实车日志与视频附件 | 提供复现素材，待分析 | 评论1：上传实车日志与视频附件 |
| 2 | 复制工作项1202411 | 无新增排查动作 | 评论2：复制工作项1202411 |
| 3 | 分析U盘挂载无写权限 | U盘无写入权限，需系统侧协助 | 11-11 11:01:20.184 XVRService-UsbMountReceiver: MOUNT onReceive Action:android.intent |
| 4 | 分析media挂载报错日志 | fuse挂载失败但状态仍为mounted | Line 28505: receive child output finished in ForkExecvpTi |
| 5 | 分析media mounted传递原因 | 需framework排查传递逻辑 | 评论5：需framework排查传递逻辑 |
| 6 | 回退代码并提交验证 | mount时user10未绑定，异常未reset | Revert "[VCU Pro] not reset when ExternalStorageService already connected" (1088305) |
| 7 | 版本验证通过 | SGM 220版本验证pass，可关闭 | SGM=557-8775-Release3-20251113-UQB26C-220版本验证pass |

### 排查结论
- **已确认的事实**：U盘挂载时fuse挂载失败但状态仍为mounted（Line 28505）；回退"ExternalStorageService already connected"相关代码后，SGM 220版本验证通过（评论7）；U盘无写入权限（11-11 11:01:20.184 XVRService-UsbMountReceiver日志）。
- **尚未确认需进一步排查的方向**：framework层media mounted状态传递逻辑的具体缺陷；U盘REMOVED触发原因（系统主动卸载还是重新枚举）未明确。
- **与AI日志分析结论的一致点**：均确认U盘首次挂载失败是核心问题，且与ExternalStorageService连接状态相关。
- **与AI日志分析结论的差异点**：AI分析认为冷启动时序竞争是根因，而人工排查通过回退代码验证了"not reset"逻辑缺陷是直接原因；AI未提及U盘无写权限问题，人工排查发现该权限问题需系统侧协助。


## 时序排查详情

### AI日志分析

- 冷启动时序竞争导致 U盘首次挂载失败：StorageManagerService 在 11:01:12.338 挂载 U盘卷到 user 10 时，ExternalStorageServiceImpl 服务尚未启动（not found），挂载失败（L536277）
- XVR 服务启动后无法识别 U盘：XVR 在 11:01:16.988 启动后，因 U盘处于挂载失败状态，isMounted 持续为 false（11:01:45~50），无法识别 U盘（L2848）
- 挂载失败后无自动重试机制：从挂载失败（11:01:12）到 U盘被移除重新枚举（11:01:55）间隔约 43 秒，期间系统未尝试重新挂载（L27979）
- user 10 media 进程启动延迟约 4.37 秒：user 0 media 进程在 11:01:09 启动，user 10 直到 11:01:14 才启动，启动调度存在明显延迟（L534292 L536936）
- MediaProvider 扫描正常：扫描完成无异常，排除了扫描失败导致 U盘不可用的假设（L35079）
- U盘 REMOVED 触发原因未明：11:01:55.795 U盘被 REMOVED 的具体触发原因（系统主动卸载还是 U盘重新枚举）未在日志中明确追踪到（L27979）

### 评论 1

**排查动作**: 上传实车日志与视频附件

**排查结果**: 提供复现素材，待分析


### 评论 2

**排查动作**: 复制工作项1202411

**排查结果**: 无新增排查动作


### 评论 3

**排查动作**: 分析U盘挂载无写权限

**排查结果**: U盘无写入权限，需系统侧协助


**日志证据**:

```
11-11 11:01:20.184  6173  6173 I XVRService-UsbMountReceiver: MOUNT onReceive Action:android.intent.action.MEDIA_MOUNTED
11-11 11:01:20.387  6173  6956 D XVRService-UsbMountUtils: path:/storage/C633-0305 file.exists():false file.isDirectory():false file.canWrite():false
```


### 评论 4

**排查动作**: 分析media挂载报错日志

**排查结果**: fuse挂载失败但状态仍为mounted


**日志证据**:

```
Line 28491: 11-11 11:01:11.811  4976  4976 V vold    : /system/bin/blkid
Line 28504: 11-11 11:01:11.849  4977  4977 I vold    : /dev/block/vold/public:8,1: LABEL="M-MM-uM-QM-)M-CM-H" UUID="C633-0305" TYPE="vfat"
Line 28505: 11-11 11:01:11.850   459   598 I vold    : receive child output finished in ForkExecvpTimeout
Line 28690: 11-11 11:01:12
```


### 评论 5

**排查动作**: 分析media mounted传递原因

**排查结果**: 需framework排查传递逻辑


### 评论 6

**排查动作**: 回退代码并提交验证

**排查结果**: mount时user10未绑定，异常未reset


**日志证据**:

```
Revert "[VCU Pro] not reset when ExternalStorageService already connected" (1088305)
Revert "[VCU Pro] not reset when ExternalStorageService already connected" (1088306)
Revert "[VCU Pro] not reset when ExternalStorageService already connected" (1088307)
```


### 评论 7

**排查动作**: 版本验证通过

**排查结果**: SGM 220版本验证pass，可关闭


**日志证据**:

```
SGM=557-8775-Release3-20251113-UQB26C-220版本验证pass
```

