# VCU-210539 评论分析总结

## 排查结论

远程控制座椅通风/加热功能在多个版本持续失效，VCU未发出请求且根因未定，当前问题已定位至VCU流转环节，待进一步排查。


## 排查过程分析

### 问题现象
远程控制座椅通风/加热功能失效，用户通过手机APP下发指令后，车辆端始终未执行远程启动，问题在多个软件版本（8155-1215、0622）上持续复现。

### 排查过程
| 步骤 | 排查动作 | 结果 | 关键证据 |
|------|----------|------|----------|
| 1 | 上传远控座椅通风日志 | 已上传8155-1215日志包 | 附件2054701 (8155-1215远控座椅通风.zip) |
| 2 | 分析远程座椅加热日志 | 远程启动不支持，请求失败 | `failureDetails: start` (06-17 12:14:55.462) |
| 3 | 远程启动验证 | 始终未远程启动 | 评论3：始终未远程启动 |
| 4 | 添加截图附件 | 已添加附件2055260 | 附件2055260 |
| 5 | 复测ndlb远程启动 | 问题仍复现 | 评论5：问题仍复现 |
| 6 | 关联同类问题并转派 | VCU未发出请求，需确认流转 | 评论6：VCU未发出请求 |
| 7 | 集成远程启动property到8155 | 待集成，未执行排查 | 评论7：待集成 |
| 8 | 关联问题1063283，vhal层排查 | 同1063283问题，根因未定 | 评论8：根因未定 |
| 9 | 要求使用新版本验证 | 需rb-vcuplus_NS_2025.25.4+ | 评论9：需25.4及以上版本 |
| 10 | 实车复测0622版本 | 问题仍存在 | 评论10：0622版本问题还在，时间09:46 |
| 11 | 上传实车日志附件 | 提供gmlogger、someip、spy3日志 | 评论11：提供三类日志 |
| 12 | 日志检索下发操作 | 未发现下发记录，转FW排查 | `log中没有下发REMOTE_VEHICLE_START_SOFTWARE_DEFINED_FEATURE_REQUEST_SERVICE的操作` |
| 13 | 日志排查FWK接口调用 | 未看到调用FWK接口 | 评论13：未看到调用FWK接口 |
| 14 | 检索远况座椅通风日志 | 未找到相关记录 | 评论14：未找到相关记录 |
| 15 | ServiceBus云事件流分析 | 发现onStreamerChanged事件流 | `onStreamerChanged cloudEvent=CloudEvent{id` (06-27 09:31:41.563) |
| 16 | ServiceBus RPC请求分析 | 发现RPC请求重试 | `handleRpcRequest rpc.req.local` + `addRpcReqToRetryList retryAgain` (06-27 09:45:57) |
| 17 | 请求协助分析servicebus问题 | 待嘉哥排查 | 评论17：待嘉哥排查 |
| 18 | 确认车型集成SDVRemoteControlServiceAPK | 待确认ND车型是否集成 | 评论18：


## 时序排查详情

### AI日志分析

- RPC 服务未注册：`cls:/remote_control/1/rpc.RemoteUpdateSeatTemperature` 在 ServiceBus 中无服务注册，指令无法路由到座椅控制器（L342058、L342062）
- 客户端响应类型不匹配：收到 `google.rpc.Status` 而非 `SeatTemperatureResponse`，说明车端无法正常处理请求（L170434）
- MQTT 链路正常：指令成功从云端到达车端 ServiceBus，排除链路异常假设（L341975、L342057）
- SeatTemperatureTopic 无 RPC 能力：车端座椅温度服务仅注册了事件发布（type=pub.v1），不具备 RPC 处理能力（L180935）
- 电源模式假设排除：错误发生在 ServiceBus RPC 路由层，与电源模式检查无关（L168845）

### 评论 1

**排查动作**: 添加远控座椅通风日志附件

**排查结果**: 已上传8155-1215日志压缩包


**日志证据**:

```
附件 2054701 (8155-1215远控座椅通风.zip)
```


### 评论 2

**排查动作**: 分析远程座椅加热日志

**排查结果**: 远程启动不支持，请求失败


**日志证据**:

```
06-17 12:14:55.462  4493  4493 D RemoteUpdateSeatTemperatureRequestProcessor: failureDetails: start remote start not support overallStatus: failure subCategory: INVALID_ARGUMENT
```


### 评论 3

**排查动作**: 远程启动验证

**排查结果**: 始终未远程启动


### 评论 4

**排查动作**: 添加附件截图

**排查结果**: 已添加附件2055260


### 评论 5

**排查动作**: 复测ndlb远程启动

**排查结果**: 问题仍复现


### 评论 6

**排查动作**: 关联同类问题并转派

**排查结果**: VCU未发出请求，需确认流转


### 评论 7

**排查动作**: 集成远程启动property到8155

**排查结果**: 待集成，未执行排查


### 评论 8

**排查动作**: 关联问题1063283，vhal层排查

**排查结果**: 同1063283问题，根因未定


### 评论 9

**排查动作**: 要求使用新版本验证

**排查结果**: 需rb-vcuplus_NS_2025.25.4及以上版本


### 评论 10

**排查动作**: 实车复测0622版本

**排查结果**: 问题仍存在


**日志证据**:

```
0622版本问题还在，时间09:46
```


### 评论 11

**排查动作**: 上传实车日志附件

**排查结果**: 提供gmlogger、someip、spy3日志


### 评论 12

**排查动作**: 日志检索下发操作

**排查结果**: 未发现下发记录，转FW排查


**日志证据**:

```
log中没有下发REMOTE_VEHICLE_START_SOFTWARE_DEFINED_FEATURE_REQUEST_SERVICE的操作
```


### 评论 13

**排查动作**: 日志排查FWK接口调用

**排查结果**: 未看到调用FWK接口


### 评论 14

**排查动作**: 检索远况座椅通风日志

**排查结果**: 未找到相关记录，需他人协助


### 评论 15

**排查动作**: (Comment from 陈

**排查结果**: (Comment from 陈传峰)
s


**日志证据**:

```
06-27 09:31:41.563  4595  7533 D ServiceBus: [Dispatcher] onStreamerChanged cloudEvent=CloudEvent{id='1f052f67-a4a9-6fa2-8dd5-01f00857dd31', source=cls://bo.lscp.sgm.com/vcsp/1/ChargingServiceProfile.notification, type='res.v1', datacontenttype='application/x-protobuf', dataschema=type.googleapis.com/google.rpc.Status, time=2025-06-27T01:31:40.559Z, data=BytesCloudEventData{value=[10, 37, 116, 121, 112, 101, 46, 103, 111, 111, 103, 108, 101, 97, 112, 105, 115, 46, 99, 111, 109, 47, 103, 111, 111, 103, 108, 101, 46, 114, 112, 99, 46, 83, 116, 97, 116, 117, 115, 18, 38, 8, 14, 18, 34, 49, 52, 67, 48, 48, 49, 58, -26, -100, -86, -27, -69, -70, -25, -85, -117, -28, -72, -114, 66, 114, 111, 107, 101, 114, -25, -102, -124, -24, -65, -98, -26, -114, -91]}, extensions={sink=cls://vcu.LSGMJ5P56SV001113.veh.lscp.sgm.com/com.sgm.cls.energyservice/1/ntf#ChargingServiceProfile, commstatus=14C001, priority=CS6, ttl=60000, reqid=1f052f67-a487-6eff-9022-ebbda386f5fa}}
06-27 09:31:42.580  4595  7533 D ServiceBus: [Dispatcher] onStreamerChanged cloudEvent=CloudEvent{id='1f052f67-ae55-6903-8dd5-01f00857dd31', source=cls://bo.lscp.sgm.com/vcsp/1/ChargingServiceProfile.notification, type='res.v1', datacontenttype='application/x-protobuf', dataschema=type.googleapis.com/google.rpc.Status, time=2025-06-27T01:31:41.574Z, data=BytesCloudEventData{value=[10, 37, 116, 121, 112, 101, 46, 103, 111, 111, 103, 108, 101, 97, 112, 105, 115, 46, 99, 111, 109, 47, 103, 111, 111, 103, 108, 101, 46, 114, 112, 99, 46, 83, 116, 97, 116, 117, 115, 18, 38, 8, 14, 18, 34, 49, 52, 67, 48, 48, 49, 58, -26, -100, -86, -27, -69, -70, -25, -85, -117, -28, -72, -114, 66, 114, 111, 107, 101, 114, -25, -102, -124, -24, -65, -98, -26, -114, -91]}, extensions={sink=cls://vcu.LSGMJ5P56SV001113.veh.lscp.sgm.com/com.sgm.cls.energyservice/1/ntf#ChargingServiceProfile, commstatus=14C001, priority=CS6, ttl=60000, reqid=1f052f67-a487-6eff-9022-ebbda386f5fa}}
06-27 09:31:43.591  4595  4621 D ServiceBus: [Dispatcher] onStreamerChanged cloudEvent=CloudEvent{id='1f052f67-b7f9-6d34-8dd5-01f00857dd31', source=cls://bo.lscp.sgm.com/vcsp/1/ChargingServiceProfile.notification, type='res.v1', datacontenttype='application/x-protobuf', dataschema=type.googleapis.com/google.rpc.Status, time=2025-06-27T01:31:42.585Z, data=BytesCloudEventData{value=[10, 37, 116, 121, 112, 101, 46, 103, 111, 111, 103, 108, 101, 97, 112, 105, 115, 46, 99, 111, 109, 47, 103, 111, 111, 103, 108, 101, 46, 114, 112, 99, 46, 83, 116, 97, 116, 117, 115, 18, 38, 8, 14, 18, 34, 49, 52, 67, 48, 48, 49, 58, -26, -100, -86, -27, -69, -70, -25, -85, -117, -28, -72, -114, 66, 114, 111, 107, 101, 114, -25, -102, -124, -24, -65, -98, -26, -114, -91]}, extensions={sink=cls://vcu.LSGMJ5P56SV001113.veh.lscp.sgm.com/com.sgm.cls.energyservice/1/ntf#ChargingServiceProfile, commstatus=14C001, priority=CS6, ttl=60000, reqid=1f052f67-a487-6eff-9022-ebbda386f5fa}}
06-27 09:31:44.605  4595  4619 D ServiceBus: [Dispatcher] onStreamerChanged cloudEvent=CloudEvent{id='1f052f67-c1a7-6da5-8dd5-01f00857dd31', source=cls://bo.lscp.sgm.com/vcsp/1/ChargingServiceProfile.notification, type='res.v1', datacontenttype='application/x-protobuf', dataschema=type.googleapis.com/google.rpc.Status, time=2025-06-27T01:31:43.600Z, data=BytesCloudEventData{value=[10, 37, 116, 121, 112, 101, 46, 103, 111, 111, 103, 108, 101, 97, 112, 105, 115, 46, 99, 111, 109, 47, 103, 111, 111, 103, 108, 101, 46, 114, 112, 99, 46, 83, 116, 97, 116, 117, 115, 18, 38, 8, 14, 18, 34, 49, 52, 67, 48, 48, 49, 58, -26, -100, -86, -27, -69, -70, -25, -85, -117, -28, -72, -114, 66, 114, 111, 107, 101, 114, -25, -102, -124, -24, -65, -98, -26, -114, -91]}, extensions={sink=cls://vcu.LSGMJ5P56SV001113.veh.lscp.sgm.com/com.sgm.cls.energyservice/1/ntf#ChargingServiceProfile, commstatus=14C001, priority=CS6, ttl=60000, reqid=1f052f67-a487-6eff-9022-ebbda386f5fa}}
```


### 评论 16

**排查动作**: (Comment from 王

**排查结果**: (Comment from 王雪阳)
陈


**日志证据**:

```
06-27 09:45:57.478  4595  4841 D ServiceBus: [Dispatcher] handleRpcRequest rpc.req.local rpcMeth has no service registration. ce=CloudEvent{id='1f052f87-4465-6b56-8901-b73d08fa6e12', source=cls:/com.example.proxy//rpc.response, type='req.v1', datacontenttype='application/x-protobuf', dataschema=type.googleapis.com/cls.app.remote_control.v1.SeatTemperatureRequest, time=2025-06-27T01:45:50.464Z, data=BytesCloudEventData{value=[10, 68, 116, 121, 112, 101, 46, 103, 111, 111, 103, 108, 101, 97, 112, 105, 115, 46, 99, 111, 109, 47, 99, 108, 115, 46, 97, 112, 112, 46, 114, 101, 109, 111, 116, 101, 95, 99, 111, 110, 116, 114, 111, 108, 46, 118, 49, 46, 83, 101, 97, 116, 84, 101, 109, 112, 101, 114, 97, 116, 117, 114, 101, 82, 101, 113, 117, 101, 115, 116, 18, 44, 18, 15, 115, 101, 97, 116, 46, 114, 111, 119, 49, 95, 114, 105, 103, 104, 116, 26, 4, 98, 97, 99, 107, 26, 7, 99, 117, 115, 104, 105, 111, 110, 34, 4, 104, 101, 97, 116, 42, 4, 104, 105, 103, 104]}, extensions={sink=cls:/remote_control/1/rpc.RemoteUpdateSeatTemperature, priority=CS4, ttl=10000}}
06-27 09:45:57.479  4595  4841 I ServiceBus: [RequestRetryManager] addRpcReqToRetryList retryAgain. RequestEvent{cloudEvent=CloudEvent{id='1f052f87-4465-6b56-8901-b73d08fa6e12', source=cls:/com.example.proxy//rpc.response, type='req.v1', datacontenttype='application/x-protobuf', dataschema=type.googleapis.com/cls.app.remote_control.v1.SeatTemperatureRequest, time=2025-06-27T01:45:50.464Z, data=BytesCloudEventData{value=[10, 68, 116, 121, 112, 101, 46, 103, 111, 111, 103, 108, 101, 97, 112, 105, 115, 46, 99, 111, 109, 47, 99, 108, 115, 46, 97, 112, 112, 46, 114, 101, 109, 111, 116, 101, 95, 99, 111, 110, 116, 114, 111, 108, 46, 118, 49, 46, 83, 101, 97, 116, 84, 101, 109, 112, 101, 114, 97, 116, 117, 114, 101, 82, 101, 113, 117, 101, 115, 116, 18, 44, 18, 15, 115, 101, 97, 116, 46, 114, 111, 119, 49, 95, 114, 105, 103, 104, 116, 26, 4, 98, 97, 99, 107, 26, 7, 99, 117, 115, 104, 105, 111, 110, 34, 4, 104, 101, 97, 116, 42, 4, 104, 105, 103, 104]}, extensions={sink=cls:/remote_control/1/rpc.RemoteUpdateSeatTemperature, priority=CS4, ttl=10000}}, retryCount=1, retryTime=7000, lastRetryTime=925444, client=Client{mCredentials=Credentials{packageName='com.example.proxy', pid=14273, uid=1010093, uri=cls:/com.example.proxy/}, mReleased=false, mBinder=android.os.BinderProxy@6d60a63}, status=code: 5
```


### 评论 17

**排查动作**: 请求协助分析servicebus问题

**排查结果**: 待嘉哥排查


### 评论 18

**排查动作**: 确认车型集成SDVRemoteControlServiceAPK

**排查结果**: 待确认ND车型是否集成该APK


### 评论 19

**排查动作**: 请求确认

**排查结果**: 等待雪峰工确认


### 评论 20

**排查动作**: 确认ND车型进程归属

**排查结果**: 发现SDVRemoteControlServiceAPK


### 评论 21

**排查动作**: 清理缓存并重启复测

**排查结果**: 重新配置后台，待复测验证


**日志证据**:

```
adb root
adb remount
adb shell
cd data
cd media/10
ls
rm connProxy.txt
sync
```


### 评论 22

**排查动作**: 确认RPC发送方式

**排查结果**: 本地simulator发RPC，不涉及云端


### 评论 23

**排查动作**: 转单操作说明

**排查结果**: 要求确认转单人并转回


### 评论 24

**排查动作**: 添加附件1501.zip

**排查结果**: 已上传日志压缩包


**日志证据**:

```
附件 2090942 (1501.zip)
```


### 评论 25

**排查动作**: 查看最新测试日志

**排查结果**: 已提供附件1501.zip


### 评论 26

**排查动作**: (Comment from 陈

**排查结果**: (Comment from 陈传峰)
从


### 评论 27

**排查动作**: 日志分析CoreService信号

**排查结果**: 未收到远控Carservice信号


**日志证据**:

```
CoreService未收到远控的Carservice信号 557867317的Topic信号
```


### 评论 28

**排查动作**: 请求CarService核查信号发送

**排查结果**: 待确认信号是否发送


### 评论 29

**排查动作**: 日志分析FWK接口调用

**排查结果**: 未看到调用FWK接口


### 评论 30

**排查动作**: 检索远况座椅通风日志

**排查结果**: 未找到相关记录，需他人协助


### 评论 31

**排查动作**: (Comment from C

**排查结果**: (Comment from CLM_DA


**日志证据**:

```
06-27 09:31:41.563  4595  7533 D ServiceBus: [Dispatcher] onStreamerChanged cloudEvent=CloudEvent{id='1f052f67-a4a9-6fa2-8dd5-01f00857dd31', source=cls://bo.lscp.sgm.com/vcsp/1/ChargingServiceProfile.notification, type='res.v1', datacontenttype='application/x-protobuf', dataschema=type.googleapis.com/google.rpc.Status, time=2025-06-27T01:31:40.559Z, data=BytesCloudEventData{value=[10, 37, 116, 121, 112, 101, 46, 103, 111, 111, 103, 108, 101, 97, 112, 105, 115, 46, 99, 111, 109, 47, 103, 111, 111, 103, 108, 101, 46, 114, 112, 99, 46, 83, 116, 97, 116, 117, 115, 18, 38, 8, 14, 18, 34, 49, 52, 67, 48, 48, 49, 58, -26, -100, -86, -27, -69, -70, -25, -85, -117, -28, -72, -114, 66, 114, 111, 107, 101, 114, -25, -102, -124, -24, -65, -98, -26, -114, -91]}, extensions={sink=cls://vcu.LSGMJ5P56SV  001113.veh.lscp.sgm.com/com.sgm.cls.energyservice/1/ntf#ChargingServiceProfile, commstatus=14C001, priority=CS6, ttl=60000, reqid=1f052f67-a487-6eff-9022-ebbda386f5fa}}
06-27 09:31:42.580  4595  7533 D ServiceBus: [Dispatcher] onStreamerChanged cloudEvent=CloudEvent{id='1f052f67-ae55-6903-8dd5-01f00857dd31', source=cls://bo.lscp.sgm.com/vcsp/1/ChargingServiceProfile.notification, type='res.v1', datacontenttype='application/x-protobuf', dataschema=type.googleapis.com/google.rpc.Status, time=2025-06-27T01:31:41.574Z, data=BytesCloudEventData{value=[10, 37, 116, 121, 112, 101, 46, 103, 111, 111, 103, 108, 101, 97, 112, 105, 115, 46, 99, 111, 109, 47, 103, 111, 111, 103, 108, 101, 46, 114, 112, 99, 46, 83, 116, 97, 116, 117, 115, 18, 38, 8, 14, 18, 34, 49, 52, 67, 48, 48, 49, 58, -26, -100, -86, -27, -69, -70, -25, -85, -117, -28, -72, -114, 66, 114, 111, 107, 101, 114, -25, -102, -124, -24, -65, -98, -26, -114, -91]}, extensions={sink=cls://vcu.LSGMJ5P56SV  001113.veh.lscp.sgm.com/com.sgm.cls.energyservice/1/ntf#ChargingServiceProfile, commstatus=14C001, priority=CS6, ttl=60000, reqid=1f052f67-a487-6eff-9022-ebbda386f5fa}}
06-27 09:31:43.591  4595  4621 D ServiceBus: [Dispatcher] onStreamerChanged cloudEvent=CloudEvent{id='1f052f67-b7f9-6d34-8dd5-01f00857dd31', source=cls://bo.lscp.sgm.com/vcsp/1/ChargingServiceProfile.notification, type='res.v1', datacontenttype='application/x-protobuf', dataschema=type.googleapis.com/google.rpc.Status, time=2025-06-27T01:31:42.585Z, data=BytesCloudEventData{value=[10, 37, 116, 121, 112, 101, 46, 103, 111, 111, 103, 108, 101, 97, 112, 105, 115, 46, 99, 111, 109, 47, 103, 111, 111, 103, 108, 101, 46, 114, 112, 99, 46, 83, 116, 97, 116, 117, 115, 18, 38, 8, 14, 18, 34, 49, 52, 67, 48, 48, 49, 58, -26, -100, -86, -27, -69, -70, -25, -85, -117, -28, -72, -114, 66, 114, 111, 107, 101, 114, -25, -102, -124, -24, -65, -98, -26, -114, -91]}, extensions={sink=cls://vcu.LSGMJ5P56SV  001113.veh.lscp.sgm.com/com.sgm.cls.energyservice/1/ntf#ChargingServiceProfile, commstatus=14C001, priority=CS6, ttl=60000, reqid=1f052f67-a487-6eff-9022-ebbda386f5fa}}
06-27 09:31:44.605  4595  4619 D ServiceBus: [Dispatcher] onStreamerChanged cloudEvent=CloudEvent{id='1f052f67-c1a7-6da5-8dd5-01f00857dd31', source=cls://bo.lscp.sgm.com/vcsp/1/ChargingServiceProfile.notification, type='res.v1', datacontenttype='application/x-protobuf', dataschema=type.googleapis.com/google.rpc.Status, time=2025-06-27T01:31:43.600Z, data=BytesCloudEventData{value=[10, 37, 116, 121, 112, 101, 46, 103, 111, 111, 103, 108, 101, 97, 112, 105, 115, 46, 99, 111, 109, 47, 103, 111, 111, 103, 108, 101, 46, 114, 112, 99, 46, 83, 116, 97, 116, 117, 115, 18, 38, 8, 14, 18, 34, 49, 52, 67, 48, 48, 49, 58, -26, -100, -86, -27, -69, -70, -25, -85, -117, -28, -72, -114, 66, 114, 111, 107, 101, 114, -25, -102, -124, -24, -65, -98, -26, -114, -91]}, extensions={sink=cls://vcu.LSGMJ5P56SV  001113.veh.lscp.sgm.com/com.sgm.cls.energyservice/1/ntf#ChargingServiceProfile, commstatus=14C001, priority=CS6, ttl=60000, reqid=1f052f67-a487-6eff-9022-ebbda386f5fa}}
```


### 评论 32

**排查动作**: (Comment from C

**排查结果**: (Comment from CLM_DA


**日志证据**:

```
06-27 09:45:57.478  4595  4841 D ServiceBus: [Dispatcher] handleRpcRequest rpc.req.local rpcMeth has no service registration. ce=CloudEvent{id='1f052f87-4465-6b56-8901-b73d08fa6e12', source=cls:/com.example.proxy//rpc.response, type='req.v1', datacontenttype='application/x-protobuf', dataschema=type.googleapis.com/cls.app.remote_control.v1.SeatTemperatureRequest, time=2025-06-27T01:45:50.464Z, data=BytesCloudEventData{value=[10, 68, 116, 121, 112, 101, 46, 103, 111, 111, 103, 108, 101, 97, 112, 105, 115, 46, 99, 111, 109, 47, 99, 108, 115, 46, 97, 112, 112, 46, 114, 101, 109, 111, 116, 101, 95, 99, 111, 110, 116, 114, 111, 108, 46, 118, 49, 46, 83, 101, 97, 116, 84, 101, 109, 112, 101, 114, 97, 116, 117, 114, 101, 82, 101, 113, 117, 101, 115, 116, 18, 44, 18, 15, 115, 101, 97, 116, 46, 114, 111, 119, 49, 95, 114, 105, 103, 104, 116, 26, 4, 98, 97, 99, 107, 26, 7, 99, 117, 115, 104, 105, 111, 110, 34, 4, 104, 101, 97, 116, 42, 4, 104, 105, 103, 104]}, extensions={sink=cls:/remote_control/1/rpc.RemoteUpdateSeatTemperature, priority=CS4, ttl=10000}}
06-27 09:45:57.479  4595  4841 I ServiceBus: [RequestRetryManager] addRpcReqToRetryList retryAgain. RequestEvent{cloudEvent=CloudEvent{id='1f052f87-4465-6b56-8901-b73d08fa6e12', source=cls:/com.example.proxy//rpc.response, type='req.v1', datacontenttype='application/x-protobuf', dataschema=type.googleapis.com/cls.app.remote_control.v1.SeatTemperatureRequest, time=2025-06-27T01:45:50.464Z, data=BytesCloudEventData{value=[10, 68, 116, 121, 112, 101, 46, 103, 111, 111, 103, 108, 101, 97, 112, 105, 115, 46, 99, 111, 109, 47, 99, 108, 115, 46, 97, 112, 112, 46, 114, 101, 109, 111, 116, 101, 95, 99, 111, 110, 116, 114, 111, 108, 46, 118, 49, 46, 83, 101, 97, 116, 84, 101, 109, 112, 101, 114, 97, 116, 117, 114, 101, 82, 101, 113, 117, 101, 115, 116, 18, 44, 18, 15, 115, 101, 97, 116, 46, 114, 111, 119, 49, 95, 114, 105, 103, 104, 116, 26, 4, 98, 97, 99, 107, 26, 7, 99, 117, 115, 104, 105, 111, 110, 34, 4, 104, 101, 97, 116, 42, 4, 104, 105, 103, 104]}, extensions={sink=cls:/remote_control/1/rpc.RemoteUpdateSeatTemperature, priority=CS4, ttl=10000}}, retryCount=1, retryTime=7000, lastRetryTime=  925444, client=Client{mCredentials=Credentials{packageName='com.example.proxy', pid=14273, uid=  1010093, uri=cls:/com.example.proxy/}, mReleased=false, mBinder=android.os.BinderProxy@  6d60a63}, status=code: 5
```


### 评论 33

**排查动作**: 请求协助分析servicebus问题

**排查结果**: 待嘉哥排查


### 评论 34

**排查动作**: 确认车型集成APK

**排查结果**: 待确认SDVRemoteControlServiceAPK集成情况


### 评论 35

**排查动作**: 请求确认

**排查结果**: 等待雪峰工确认


### 评论 36

**排查动作**: 确认ND车型进程含SDVRemoteControlServiceAPK

**排查结果**: 定位到SDVRemoteControlServiceAPK存在


### 评论 37

**排查动作**: 清理缓存并重启复测

**排查结果**: 重新配置后台，待复测验证


**日志证据**:

```
adb root
adb remount
adb shell
cd data
cd media/10
ls
rm connProxy.txt
sync
```


### 评论 38

**排查动作**: 确认RPC发送方式

**排查结果**: 本地simulator，不涉及云端


### 评论 39

**排查动作**: 转单操作说明

**排查结果**: 要求确认转单人并避免乱转


### 评论 40

**排查动作**: 查看最新测试日志

**排查结果**: 已获取附件1501.zip日志


### 评论 41

**排查动作**: (Comment from C

**排查结果**: (Comment from CLM_DA


### 评论 42

**排查动作**: 日志信号排查

**排查结果**: 未收到远控Carservice信号


**日志证据**:

```
CoreService未收到远控的Carservice信号 557867317的Topic信号
```


### 评论 43

**排查动作**: 请求CarService核查信号发送

**排查结果**: 待确认信号是否发送


### 评论 44

**排查动作**: 分析日志未收到CAN信号

**排查结果**: 所有日志均未收到上抛CAN信号


**日志证据**:

```
comment25的所有日志均未收到上抛的CAN信号
PPEI_PLATFORM_GENERAL_STATUS_SIGNAL_GROUP_REMOTE_START_STATUS / 557867317
```


### 评论 45

**排查动作**: 确认实车测试环境

**排查结果**: 无需手动模拟发送信号


### 评论 46

**排查动作**: 检索相关日志信号

**排查结果**: 未找到信号及CAN日志，需重测


### 评论 47

**排查动作**: 提取总线log信号

**排查结果**: 47F值无变化，需从信号分析


**日志证据**:

```
PPEI_PLATFORM_GENERAL_STATUS_SIGNAL_GROUP_REMOTE_START_STATUS信号
```


### 评论 48

**排查动作**: 添加远程启动状态截图

**排查结果**: 已添加附件，待进一步分析


### 评论 49

**排查动作**: 确认信号未上报并转办

**排查结果**: 未收到信号，需MCU确认转办


### 评论 50

**排查动作**: 信号基本信息排查

**排查结果**: 信号值恒为0，上行通路正常


**日志证据**:

```
HSCAN7上有0X47F,0X111，0x82,0xE4，推断物理CAN为PCAN
总线上有信号RemStrtSt，对应值一直为0没有变化
自测NS25.5信号上行通路正常
```


### 评论 51

**排查动作**: 添加总线信号附件

**排查结果**: 已上传信号截图


**日志证据**:

```
附件 2094250 (总线信号.png)
```


### 评论 52

**排查动作**: 邮件转发对手件工程师

**排查结果**: 已转交黄菲菲处理


### 评论 53

**排查动作**: 搜索RemStrtSt信号

**排查结果**: 数据内未找到该信号


### 评论 54

**排查动作**: 分析Vdata上抛策略

**排查结果**: 信号无变化不上报，与VHAL日志相符


**日志证据**:

```
1501 7-01-2025 3-01-55 pm.vsb
CANID：0X111
RemStrtSt对应值一直为0
```


### 评论 55

**排查动作**: 请求BDF确认0x111

**排查结果**: 待BDF确认


### 评论 56

**排查动作**: 添加附件截图

**排查结果**: 已添加附件，待进一步分析


### 评论 57

**排查动作**: 分析CAN日志

**排查结果**: BDF未收到远程启动命令


### 评论 58

**排查动作**: 添加附件截图

**排查结果**: 已添加附件2117041


### 评论 59

**排查动作**: 请求BOSCH再次确认

**排查结果**: 等待供应商进一步确认


### 评论 60

**排查动作**: 关联同源问题1084357

**排查结果**: 问题同1084357，用该票追踪

