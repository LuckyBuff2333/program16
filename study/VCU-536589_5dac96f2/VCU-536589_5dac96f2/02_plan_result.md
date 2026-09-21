# Plan 节点输出

## 问题解构

- 操作步骤: 1. 在 Setting 界面调节倒车自动下翻后视镜（设置下翻位置/角度）；2. 返回上一界面；3. 挂 R 档触发倒车自动下翻。
- 预期结果: 倒车自动下翻后视镜应记忆用户上次设置的位置，挂 R 档时下翻到用户设定位置。
- 实际结果: 无记忆，后视镜只会固定下翻到同一个默认位置，用户设置的位置未被保存/回读。
- 关键实体: Setting (com.patac.hmi.settings), 倒车自动下翻后视镜 (Reverse Tilt Mirror / Mirror Tilt in Reverse), OSRVMTiltControlRequestProcessor, OSRVMDirectionRequestProcessor, VehicleRequestProcessorFactory, SDV_CoreService, ServiceBus / SomeIP Topic, CarPropertyManager / GMVHAL, R 档信号 (Gear Position), 后视镜位置记忆 (Mirror Position Memory / Profile)
- 时间线索: 问题时间 2026-08-25 12:57:57；日志时间范围 08-25 12:55:22~13:02:56，其中 Setting 界面 Activity 相关日志集中在 13:02:46 前后。

## 候选假设

### 假设 1
- 描述: 后视镜倒车下翻位置在设置后未被持久化保存（未写入 Profile/记忆存储），导致挂 R 档时只能使用固定默认位置。
- 验证方法: 在日志中搜索 Setting 侧后视镜设置保存相关 TAG（如 Mirror、Tilt、OSRVM、Profile、Setting 保存/写入），确认设置动作后是否有写存储/写属性成功的日志；同时搜索挂 R 档后是否有读取记忆位置的日志。
- 优先级: high (现象为“只会固定保存在同一个位置”，最直接指向记忆写入或读取环节缺失，是首要排查方向。)

### 假设 2
- 描述: OSRVMTiltControlRequestProcessor / OSRVMDirectionRequestProcessor 在处理下翻请求时使用了固定默认角度，未使用用户设置值（请求参数丢失或映射错误）。
- 验证方法: 在日志中搜索 OSRVMTiltControlRequestProcessor、OSRVMDirectionRequestProcessor、VehicleRequestProcessorFactory 的请求/响应日志，核对下翻请求携带的角度/方向参数是否与用户设置一致。
- 优先级: high (日志概览中明确列出这三个 RequestProcessor 活跃，且与后视镜下翻（OSRVM Tilt/Direction）语义高度吻合，是核心链路。)

### 假设 3
- 描述: 挂 R 档信号（Gear）到后视镜下翻触发的链路存在时序/条件问题，导致下翻动作未按记忆位置执行（例如档位信号丢失或触发时机错误）。
- 验证方法: 在日志中搜索 R 档/Gear 相关信号（Gear、Shift、R 档、Reverse）与后视镜下翻触发日志的时间对应关系，确认挂 R 档时是否收到正确档位信号并触发下翻。
- 优先级: medium (若记忆保存正常但触发链路异常，也会表现为下翻位置不对；需在排除前两个假设后验证。)

## 需要查阅的 WIKI 模块

- remote_control_service, core_service, sgm_surrounding_reality
- 理由: remote_control_service 包含 OSRVMTiltControlRequestProcessor/OSRVMDirectionRequestProcessor 等远控指令接收与 RPC 转发链路，直接对应后视镜下翻控制；core_service 负责 RPC 信号链路、SomeIP 与 ServiceBus 路由，是设置值下发与档位信号传递的通道；sgm_surrounding_reality 涉及 HMI 与车辆信号集成，可辅助确认 Setting 界面设置项与信号映射关系。

## 搜索计划

搜索优先级：先验证假设2（OSRVMTiltControlRequestProcessor/OSRVMDirectionRequestProcessor 请求参数是否为固定默认值），因为日志概览已明确这些 Processor 活跃且直接对应后视镜下翻控制，能最快定位是否使用了固定位置；再验证假设1（Setting 侧设置保存/持久化日志，确认用户设置是否被写入记忆存储）；最后验证假设3（R 档信号与下翻触发时序），确认触发链路是否正常。