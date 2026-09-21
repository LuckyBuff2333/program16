# 推理轮次记录

---

## 第 1 轮 — LLM 响应

我先从假设2入手，搜索 OSRVMTiltControlRequestProcessor 和 OSRVMDirectionRequestProcessor 的请求处理日志，确认下翻请求携带的参数是否为固定默认值。



---

## 第 1 轮 — 工具执行结果

[结果 1] 搜索结果: 共 30 条匹配，显示 15 条

L19567     08-25 12:55:26.352  4112  4616 D VehicleRequestProcessorFactory: TRY TO GET PROCESSOR: cls:/vehicle/1/rpc.OSRVMTiltControl
    08-25 12:55:26.352  4477  4896 D ServiceBus: [RequestRetryManager] addRpcReqToRetryList noRetry taskSize= 0
    08-25 12:55:26.352  4156  4851 D com.patac.hmi.media-updateSourceList: updateSourceList: 
>>> 08-25 12:55:26.352  4112  5146 I OSRVMTiltControlRequestProcessor: processRequest: OSRVMDirectionAndTiltControlRequestProcessor request, uri: cls:/vehicle/1/rpc.OSRVMTiltControl
    08-25 12:55:26.352  4112  5146 I OSRVMTiltControlRequestProcessor: processRequest: Process Finish, uri: cls:/vehicle/1/rpc.OSRVMTiltControl
    08-25 12:55:26.352  4515 10235 D [ClsLinkSDK-v0.0.33] ClsLink: invokeMethod Request{id=1f1a0412-ff8f-61ed-bc7f-fd72e8f8f7c6} end
    08-25 12:55:26.352  1368  1368 D someip::vendor.ts.someip@1.0-service: setAttribute: enter. hdl(2). 

L21781     08-25 12:55:30.454   723  6153 I AHAL: AudioMsgQueue: [AudioMsg] reqId=1551, type=202, MsgGetGroupVolumeReq: vgType=6
    08-25 12:55:30.454  4112  4616 D [ClsLinkSDK-v0.0.33] ClsLink: handleRequestEvent:  sink: cls:/vehicle/1/rpc.OSRVMTiltControl, requestId: 1f1a0413-26cd-681e-bc7f-fd72e8f8f7c6, source: cls:/com.patac.hmi.settings//rpc.response
    08-25 12:55:30.454  4112  4616 D VehicleRequestProcessorFactory: TRY TO GET PROCESSOR: cls:/vehicle/1/rpc.OSRVMTiltControl
>>> 08-25 12:55:30.455  4112  5146 I OSRVMTiltControlRequestProcessor: processRequest: OSRVMDirectionAndTiltControlRequestProcessor request, uri: cls:/vehicle/1/rpc.OSRVMTiltControl
    08-25 12:55:30.455   723  7408 I audiohalservice: IDCClientThread::handleMessage RESPONSE: MsgID 1 , Token 739 , Method Result = 1
    08-25 12:55:30.455  4112  5146 I OSRVMTiltControlRequestProcessor: processRequest: Process Finish, uri: cls:/vehicle/1/rpc.OSRVMTiltControl
    08-25 12:55:30.455   723  7408 I audiohalservice: IDCClientThread::handleMessage RESPONSE: MsgID 1 , Token 739 , Method Result = 2

L26724     08-25 12:55:39.487   723  7408 I audiohalservice: IDCClientThread::handleMessage RESPONSE: MsgID 1 , Token 752 , Method Result = 2
    08-25 12:55:39.487   723  7408 D audiohalservice: vUpdateVolumegroupMap: assign Volume for Group = VOL_GROUP_HEADREST_RR and volume = 0
    08-25 12:55:39.487   723  6153 I DMABUFHEAPS: Using DMA-BUF heap named: qcom,system-uncached
>>> 08-25 12:55:39.487  4112  5146 I OSRVMTiltControlRequestProcessor: processRequest: OSRVMDirectionAndTiltControlRequestProcessor request, uri: cls:/vehicle/1/rpc.OSRVMTiltControl
    08-25 12:55:39.487  4112  5146 I OSRVMTiltControlRequestProcessor: processRequest: Process Finish, uri: cls:/vehicle/1/rpc.OSRVMTiltControl
    08-25 12:55:39.487  1368  1368 D someip::vendor.ts.someip@1.0-service: setAttribute: enter. hdl(2). 
    08-25 12:55:39.487  4515 10235 D [ClsLinkSDK-v0.0.33] ClsLink: invokeMethod Request{id=1f1a0413-7ce8-6f71-bc7f-fd72e8f8f7c6} end

L27712     08-25 12:55:41.336  4477  5049 D ServiceBus: [RequestRetryManager] addRpcReqToRetryList noRetry taskSize= 0
    08-25 12:55:41.336  4112  4616 D VehicleRequestProcessorFactory: TRY TO GET PROCESSOR: cls:/vehicle/1/rpc.OSRVMTiltControl
    08-25 12:55:41.336  4515 10235 D [ClsLinkSDK-v0.0.33] ClsLink: invokeMethod Request{id=1f1a0413-8e94-6e42-bc7f-fd72e8f8f7c6} end
>>> 08-25 12:55:41.336  4112  5146 I OSRVMTiltControlRequestProcessor: processRequest: OSRVMDirectionAndTiltControlRequestProcessor request, uri: cls:/vehicle/1/rpc.OSRVMTiltControl
    08-25 12:55:41.336  4112  5146 I OSRVMTiltControlRequestProcessor: processRequest: Process Finish, uri: cls:/vehicle/1/rpc.OSRVMTiltControl
    08-25 12:55:41.336  4515  4515 D com.patac.hmi.settings-CompleteCallback: onComplete
    08-25 12:55:41.336  1368  1368 D someip::vendor.ts.someip@1.0-service: setAttribute: enter. hdl(2). 

L45298     08-25 12:56:04.663  4515 10235 D [ClsLinkSDK-v0.0.33] ClsLink: invokeMethod Request{id=1f1a0414-6d01-6cff-bc7f-fd72e8f8f7c6} end
    08-25 12:56:04.663  4112  4616 D VehicleRequestProcessorFactory: TRY TO GET PROCESSOR: cls:/vehicle/1/rpc.OSRVMTiltControl
    08-25 12:56:04.664  1683  1769 I am_wtf  : [0,1683,system_server,-1,ActivityManager,Sending non-protected broadcast patac.hmi.intent.action.ACTION_SETTING_MIRROR_ADJUST_CLOSE from system 4515:com.patac.hmi.settings/u10s1000 pkg com.patac.hmi.settings]
>>> 08-25 12:56:04.664  4112  5471 I OSRVMTiltControlRequestProcessor: processRequest: OSRVMDirectionAndTiltControlRequestProcessor request, uri: cls:/vehicle/1/rpc.OSRVMTiltControl
    08-25 12:56:04.664  4112  5471 I OSRVMTiltControlRequestProcessor: processRequest: Process Finish, uri: cls:/vehicle/1/rpc.OSRVMTiltControl
    08-25 12:56:04.664  4515  4515 D com.patac.hmi.settings-CompleteCallback: onComplete
    08-25 12:56:04.664  1368  1368 D someip::vendor.ts.someip@1.0-service: setAttribute: enter. hdl(2). 

L68906     08-25 12:56:33.821  4112  4616 D [ClsLinkSDK-v0.0.33] ClsLink: handleRequestEvent:  sink: cls:/vehicle/1/rpc.OSRVMTiltControl, requestId: 1f1a0415-8319-6384-bc7f-fd72e8f8f7c6, source: cls:/com.patac.hmi.settings//rpc.response
    08-25 12:56:33.821  4477  4498 D ServiceBus: [RequestRetryManager] addRpcReqToRetryList noRetry taskSize= 0
    08-25 12:56:33.821  4112  4616 D VehicleRequestProcessorFactory: TRY TO GET PROCESSOR: cls:/vehicle/1/rpc.OSRVMTiltControl
>>> 08-25 12:56:33.821  4112  5471 I OSRVMTiltControlRequestProcessor: processRequest: OSRVMDirectionAndTiltControlRequestProcessor request, uri: cls:/vehicle/1/rpc.OSRVMTiltControl
    08-25 12:56:33.821  4112  5471 I OSRVMTiltControlRequestProcessor: processRequest: Process Finish, uri: cls:/vehicle/1/rpc.OSRVMTiltControl
    08-25 12:56:33.821  4515 10235 D [ClsLinkSDK-v0.0.33] ClsLink: invokeMethod Request{id=1f1a0415-8319-6384-bc7f-fd72e8f8f7c6} end
    08-25 12:56:33.822  1368  1368 D someip::vendor.ts.someip@1.0-service: setAttribute: enter. hdl(2). 

L78783     08-25 12:56:52.183  4112  4616 D VehicleRequestProcessorFactory: TRY TO GET PROCESSOR: cls:/vehicle/1/rpc.OSRVMTiltControl
    08-25 12:56:52.183  4515 10235 D [ClsLinkSDK-v0.0.33] ClsLink: invokeMethod Request{id=1f1a0416-3233-6e19-bc7f-fd72e8f8f7c6} end
    08-25 12:56:52.183  4515  4515 D com.patac.hmi.settings-CompleteCallback: onComplete
>>> 08-25 12:56:52.183  4112  5471 I OSRVMTiltControlRequestProcessor: processRequest: OSRVMDirectionAndTiltControlRequestProcessor request, uri: cls:/vehicle/1/rpc.OSRVMTiltControl
    08-25 12:56:52.183  4112  5471 I OSRVMTiltControlRequestProcessor: processRequest: Process Finish, uri: cls:/vehicle/1/rpc.OSRVMTiltControl
    08-25 12:56:52.184  5951  6023 D CPECallbackController: Dropping carPropertyEvent - propId: 291504647 areaId: 16777216  because getTimestamp(): 3692739659816 < nextUpdateTimeNanos: 3692839659816
    08-25 12:56:52.184  1368  1368 D someip::vendor.ts.someip@1.0-service: setAttribute: enter. hdl(2). 

L88199     08-25 12:57:14.111  4477  5049 D ServiceBus: [Dispatcher] handleRpcRequest end requestId= 1f1a0417-0357-6ebe-bc7f-fd72e8f8f7c6; methodUri= cls:/vehicle/1/rpc.OSRVMTiltControl
    08-25 12:57:14.111  4477  5049 D ServiceBus: [RequestRetryManager] addRpcReqToRetryList noRetry taskSize= 0
    08-25 12:57:14.112  4112  4616 D VehicleRequestProcessorFactory: TRY TO GET PROCESSOR: cls:/vehicle/1/rpc.OSRVMTiltControl
>>> 08-25 12:57:14.112  4112  5146 I OSRVMTiltControlRequestProcessor: processRequest: OSRVMDirectionAndTiltControlRequestProcessor request, uri: cls:/vehicle/1/rpc.OSRVMTiltControl
    08-25 12:57:14.112  4515 10235 D [ClsLinkSDK-v0.0.33] ClsLink: invokeMethod Request{id=1f1a0417-0357-6ebe-bc7f-fd72e8f8f7c6} end
    08-25 12:57:14.112  4112  5146 I OSRVMTiltControlRequestProcessor: processRequest: Process Finish, uri: cls:/vehicle/1/rpc.OSRVMTiltControl
    08-25 12:57:14.112  4515  4515 D com.patac.hmi.settings-CompleteCallback: onComplete

L93411     08-25 12:57:21.279  4477  4498 D ServiceBus: [Dispatcher] handleRpcRequest end requestId= 1f1a0417-47a5-6463-bc7f-fd72e8f8f7c6; methodUri= cls:/vehicle/1/rpc.OSRVMTiltControl
    08-25 12:57:21.279  4477  4498 D ServiceBus: [RequestRetryManager] addRpcReqToRetryList noRetry taskSize= 0
    08-25 12:57:21.279  4112  4616 D VehicleRequestProcessorFactory: TRY TO GET PROCESSOR: cls:/vehicle/1/rpc.OSRVMTiltControl
>>> 08-25 12:57:21.279  4112  5471 I OSRVMTiltControlRequestProcessor: processRequest: OSRVMDirectionAndTiltControlRequestProcessor request, uri: cls:/vehicle/1/rpc.OSRVMTiltControl
    08-25 12:57:21.279  4112  5471 I OSRVMTiltControlRequestProcessor: processRequest: Process Finish, uri: cls:/vehicle/1/rpc.OSRVMTiltControl
    08-25 12:57:21.279  4515 10235 D [ClsLinkSDK-v0.0.33] ClsLink: invokeMethod Request{id=1f1a0417-47a5-6463-bc7f-fd72e8f8f7c6} end
    08-25 12:57:21.279   723  6153 D ACDB-LOADER: ACDB -> ACDB_CMD_GET_AUDPROC_INSTANCE_COMMON_TABLE_SIZE

L109426     08-25 12:57:57.355   723  6153 D audio_hw_primary: start_output_stream: enter: stream(0xb4000072fe8f7b60)usecase(79: sys-notification-playback) devices(0x1000000) is_haptic_usecase(0)
    08-25 12:57:57.355   723  6153 D audio_hw_primary: start_output_stream: out->pcm_device_id :1
    08-25 12:57:57.355   723  6153 D device_utils: update_device_list: Added device type 0x1000000, address BUS01_SYS_NOTIFICATION
>>> 08-25 12:57:57.355  4112  5471 I OSRVMTiltControlRequestProcessor: processRequest: OSRVMDirectionAndTiltControlRequestProcessor request, uri: cls:/vehicle/1/rpc.OSRVMTiltControl
    08-25 12:57:57.355  2015  2273 D gm.onstar.audio: The source is 8 The sink is 7
    08-25 12:57:57.355   723  6153 E ANDR-PERF-CLIENT: ANDR-PERF-CLIENT: getPerfAidlAndLinkToDeath() 110: perf aidl service doesn't exist
    08-25 12:57:57.355   723  6153 E audio_hw_extn: audio_extn_perf_lock_acquire: Failed to acquire perf lock, err: -1

L109462     08-25 12:57:57.356   723  6153 D ACDB-LOADER: ACDB -> create_cal_node: New Node!
    08-25 12:57:57.356   723  6153 I DMABUFHEAPS: Using DMA-BUF heap named: qcom,system-uncached
    08-25 12:57:57.357  4447  4625 D CarPlay_ResourceStateListener: switchDone(): source:8 extSource:0 sink:7
>>> 08-25 12:57:57.357  4112  5471 I OSRVMTiltControlRequestProcessor: processRequest: Process Finish, uri: cls:/vehicle/1/rpc.OSRVMTiltControl
    08-25 12:57:57.357  4447  4614 I CarPlay_ResourceManager: ResourceManagerHandler received message 72
    08-25 12:57:57.358  4447  4614 I CarPlay_AudioStateMachine: onAccAudioSourceChanged(ACCESSORY): source:BUS_NOTIFICATION extSource:BUS_EXT_NONE sink:SINK_TYPE_AMP_SYSTEMSOUND_MIX
    08-25 12:57:57.358   723  6153 D ACDB-LOADER: ACDB -> ACDB_CMD_GET_AUDPROC_INSTANCE_COMMON_TABLE_SIZE

L115558     08-25 12:58:09.014   723  6153 D ACDB-LOADER: ACDB -> send_asm_topology
    08-25 12:58:09.014   723  6153 D ACDB-LOADER: ACDB -> ACDB_CMD_GET_AUDPROC_STREAM_TOPOLOGY_ID
    08-25 12:58:09.014   723  6153 D ACDB-LOADER: ACDB -> create_cal_node: New Node!
>>> 08-25 12:58:09.014  4112  5471 I OSRVMTiltControlRequestProcessor: processRequest: OSRVMDirectionAndTiltControlRequestProcessor request, uri: cls:/vehicle/1/rpc.OSRVMTiltControl
    08-25 12:58:09.014  4112  5471 I OSRVMTiltControlRequestProcessor: processRequest: Process Finish, uri: cls:/vehicle/1/rpc.OSRVMTiltControl
    08-25 12:58:09.014   723  6153 D ACDB-LOADER: ACDB -> send_adm_topology
    08-25 12:58:09.014   723  6153 D ACDB-LOADER: ACDB -> ACDB_CMD_GET_AUDPROC_COMMON_TOPOLOGY_ID

L124781     08-25 12:58:26.250  4477  4896 D ServiceBus: [RequestRetryManager] addRpcReqToRetryList noRetry taskSize= 0
    08-25 12:58:26.250  4112  4616 D [ClsLinkSDK-v0.0.33] ClsLink: handleRequestEvent:  sink: cls:/vehicle/1/rpc.OSRVMTiltControl, requestId: 1f1a0419-b34b-6a6c-bc7f-fd72e8f8f7c6, source: cls:/com.patac.hmi.settings//rpc.response
    08-25 12:58:26.250  4112  4616 D VehicleRequestProcessorFactory: TRY TO GET PROCESSOR: cls:/vehicle/1/rpc.OSRVMTiltControl
>>> 08-25 12:58:26.250  4112  5471 I OSRVMTiltControlRequestProcessor: processRequest: OSRVMDirectionAndTiltControlRequestProcessor request, uri: cls:/vehicle/1/rpc.OSRVMTiltControl
    08-25 12:58:26.251  4112  5471 I OSRVMTiltControlRequestProcessor: processRequest: Process Finish, uri: cls:/vehicle/1/rpc.OSRVMTiltControl
    08-25 12:58:26.251  1368  1368 D someip::vendor.ts.someip@1.0-service: setAttribute: enter. hdl(2). 
    08-25 12:58:26.251  1368  1368 E ts::someip::plugin: si = 65537 topic = 1407379178586320

L143884     08-25 12:58:59.120  4112  4616 D VehicleRequestProcessorFactory: TRY TO GET PROCESSOR: cls:/vehicle/1/rpc.OSRVMTiltControl
    08-25 12:58:59.120  4477  5049 D ServiceBus: [Dispatcher] handleRpcRequest end requestId= 1f1a041a-ecc4-6ad1-bc7f-fd72e8f8f7c6; methodUri= cls:/vehicle/1/rpc.OSRVMTiltControl
    08-25 12:58:59.120  4477  5049 D ServiceBus: [RequestRetryManager] addRpcReqToRetryList noRetry taskSize= 0
>>> 08-25 12:58:59.120  4112  5146 I OSRVMTiltControlRequestProcessor: processRequest: OSRVMDirectionAndTiltControlRequestProcessor request, uri: cls:/vehicle/1/rpc.OSRVMTiltControl
    08-25 12:58:59.120   723  6153 D ACDB-LOADER: ACDB -> ACDB_CMD_GET_AUDPROC_INSTANCE_GAIN_DEP_STEP_TABLE_SIZE
    08-25 12:58:59.120   723  6153 D android.hardware.audio@2.0-service.gmvcu: Failed to fetch the lookup information of the device 00000133 
    08-25 12:58:59.120   723  6153 D ACDB-LOADER: Error: ACDB_CMD_GET_AUDPROC_INSTANCE_GAIN_DEP_STEP_TABLE_SIZE Returned = -19

L151527     08-25 12:59:12.771   723  7408 I audiohalservice: IDCClientThread::handleMessage UPDATE: MsgID 2 , Token 0
    08-25 12:59:12.771   723  7408 I audiohalservice: IDCClientThread:vUpdate CONNECT Info Source = 7, state = 2
    08-25 12:59:12.772  4112  4616 D VehicleRequestProcessorFactory: TRY TO GET PROCESSOR: cls:/vehicle/1/rpc.OSRVMTiltControl
>>> 08-25 12:59:12.772  4112  5146 I OSRVMTiltControlRequestProcessor: processRequest: OSRVMDirectionAndTiltControlRequestProcessor request, uri: cls:/vehicle/1/rpc.OSRVMTiltControl
    08-25 12:59:12.772  4112  5146 I OSRVMTiltControlRequestProcessor: processRequest: Process Finish, uri: cls:/vehicle/1/rpc.OSRVMTiltControl
    08-25 12:59:12.772   723  6153 D ACDB-LOADER: ACDB -> ACDB_CMD_GET_AUDPROC_INSTANCE_COMMON_TABLE_SIZE
    08-25 12:59:12.772   723  6153 D ACDB-LOADER: ACDB -> ACDB_CMD_GET_AUDPROC_INSTANCE_COMMON_TABLE

⚠️ 搜索结果高度重复: 共 30 条匹配中，有 30 条内容相同 ('')。以上仅展示 15 条代表性结果。

---

[结果 2] 搜索结果: 共 30 条匹配，显示 12 条

L18414     08-25 12:55:24.249  4477  5049 D ServiceBus: [RequestRetryManager] addRpcReqToRetryList noRetry taskSize= 0
    08-25 12:55:24.250  4112  4616 D VehicleRequestProcessorFactory: TRY TO GET PROCESSOR: cls:/vehicle/1/rpc.OSRVMDirectionControl
    08-25 12:55:24.250  4515 10235 D [ClsLinkSDK-v0.0.33] ClsLink: invokeMethod Request{id=1f1a0412-eba3-605c-bc7f-fd72e8f8f7c6} end
>>> 08-25 12:55:24.250  4112  5146 I OSRVMDirectionRequestProcessor: processRequest: OSRVMDirectionRequestProcessor request, uri: cls:/vehicle/1/rpc.OSRVMDirectionControl
    08-25 12:55:24.250  4515  4515 D com.patac.hmi.settings-CompleteCallback: onComplete
    08-25 12:55:24.250  4112  5146 I OSRVMDirectionRequestProcessor: transStatusVal: 0
    08-25 12:55:24.250  4112  5146 I OSRVMDirectionRequestProcessor: transStatusVal: 0

L18437     08-25 12:55:24.267  4477  5049 D ServiceBus:  client=Client{mCredentials=Credentials{packageName='com.sgm.cls.coreservice', pid=4112, uid=1001000, uri=cls:/com.sgm.cls.coreservice/}, mReleased=false, mBinder=android.os.BinderProxy@88cf756}
    08-25 12:55:24.267  4477  5049 D ServiceBus: [Client] send to cls:/com.patac.hmi.settings/; id= 1f1a0412-ebd0-60ba-8f77-f3ea29b5da50
    08-25 12:55:24.268  4515  5408 D [ClsLinkSDK-v0.0.33] ClsLink: dispatchCloudEvent {id='1f1a0412-ebd0-60ba-8f77-f3ea29b5da50'}; type=res.v1
>>> 08-25 12:55:24.268  4515  5408 I com.patac.hmi.settings-RearviewMirrorAdjustTopic: setData 32769=message: "OSRVMDirectionRequestProcessor process success"
    08-25 12:55:24.268  4515  5408 D [ClsLinkSDK-v0.0.33] ClsLink: CompletableFuture whenComplete Request{id=1f1a0412-eba3-605c-bc7f-fd72e8f8f7c6} completed
    08-25 12:55:24.268  4515  5408 I [ClsLinkSDK-v0.0.33] ClsLink: response rpc Request{id='1f1a0412-eba3-605c-bc7f-fd72e8f8f7c6'} completed
    08-25 12:55:24.268  4477  5049 D ServiceBus: [Dispatcher] handleResponseMessage end Id= 1f1a0412-ebd0-60ba-8f77-f3ea29b5da50; requestId= 1f1a0412-eba3-605c-bc7f-fd72e8f8f7c6; methodUri= cls:/com.patac.hmi.settings//rpc.response

L24136     08-25 12:55:34.836  4112  4616 D VehicleRequestProcessorFactory: TRY TO GET PROCESSOR: cls:/vehicle/1/rpc.OSRVMDirectionControl
    08-25 12:55:34.836  4515 10235 D [ClsLinkSDK-v0.0.33] ClsLink: invokeMethod Request{id=1f1a0413-5086-6a8f-bc7f-fd72e8f8f7c6} end
    08-25 12:55:34.836  4515  4515 D com.patac.hmi.settings-CompleteCallback: onComplete
>>> 08-25 12:55:34.837  4112  5146 I OSRVMDirectionRequestProcessor: processRequest: OSRVMDirectionRequestProcessor request, uri: cls:/vehicle/1/rpc.OSRVMDirectionControl
    08-25 12:55:34.837  4112  5146 I OSRVMDirectionRequestProcessor: transStatusVal: 0
    08-25 12:55:34.837  4112  5146 I OSRVMDirectionRequestProcessor: transStatusVal: 2
    08-25 12:55:34.837  4112  5146 I OSRVMDirectionRequestProcessor: processRequest: Process Finish, uri: cls:/vehicle/1/rpc.OSRVMDirectionControl leftVal: 0 rightVal: 4

L24158     08-25 12:55:34.853  4477  4896 D ServiceBus:  client=Client{mCredentials=Credentials{packageName='com.sgm.cls.coreservice', pid=4112, uid=1001000, uri=cls:/com.sgm.cls.coreservice/}, mReleased=false, mBinder=android.os.BinderProxy@88cf756}
    08-25 12:55:34.853  4477  4896 D ServiceBus: [Client] send to cls:/com.patac.hmi.settings/; id= 1f1a0413-50c4-6c8d-8f77-f3ea29b5da50
    08-25 12:55:34.853  4515  5408 D [ClsLinkSDK-v0.0.33] ClsLink: dispatchCloudEvent {id='1f1a0413-50c4-6c8d-8f77-f3ea29b5da50'}; type=res.v1
>>> 08-25 12:55:34.854  4515  5408 I com.patac.hmi.settings-RearviewMirrorAdjustTopic: setData 32770=message: "OSRVMDirectionRequestProcessor process success"
    08-25 12:55:34.854  4515  5408 D [ClsLinkSDK-v0.0.33] ClsLink: CompletableFuture whenComplete Request{id=1f1a0413-5086-6a8f-bc7f-fd72e8f8f7c6} completed
    08-25 12:55:34.854  4515  5408 I [ClsLinkSDK-v0.0.33] ClsLink: response rpc Request{id='1f1a0413-5086-6a8f-bc7f-fd72e8f8f7c6'} completed
    08-25 12:55:34.854  1371  1476 D GMVHAL  : setPropFromVehicle Property: VendorProperty::POSITION_OFFSET_FROM_TRIM AreaID: 4 Status: 0 floatValues: -7 

L25427     08-25 12:55:36.792  4112  4616 D VehicleRequestProcessorFactory: TRY TO GET PROCESSOR: cls:/vehicle/1/rpc.OSRVMDirectionControl
    08-25 12:55:36.792  4477  4896 D ServiceBus: [RequestRetryManager] addRpcReqToRetryList noRetry taskSize= 0
    08-25 12:55:36.792  4515 10235 D [ClsLinkSDK-v0.0.33] ClsLink: invokeMethod Request{id=1f1a0413-6335-6600-bc7f-fd72e8f8f7c6} end
>>> 08-25 12:55:36.792  4112  5146 I OSRVMDirectionRequestProcessor: processRequest: OSRVMDirectionRequestProcessor request, uri: cls:/vehicle/1/rpc.OSRVMDirectionControl
    08-25 12:55:36.792  4515  4515 D com.patac.hmi.settings-CompleteCallback: onComplete
    08-25 12:55:36.792  4112  5146 I OSRVMDirectionRequestProcessor: transStatusVal: 0
    08-25 12:55:36.793  4112  5146 I OSRVMDirectionRequestProcessor: transStatusVal: 0

L25458     08-25 12:55:36.810  4477  4896 D ServiceBus:  client=Client{mCredentials=Credentials{packageName='com.sgm.cls.coreservice', pid=4112, uid=1001000, uri=cls:/com.sgm.cls.coreservice/}, mReleased=false, mBinder=android.os.BinderProxy@88cf756}
    08-25 12:55:36.810  4477  4896 D ServiceBus: [Client] send to cls:/com.patac.hmi.settings/; id= 1f1a0413-636e-69e6-8f77-f3ea29b5da50
    08-25 12:55:36.811  4515  5408 D [ClsLinkSDK-v0.0.33] ClsLink: dispatchCloudEvent {id='1f1a0413-636e-69e6-8f77-f3ea29b5da50'}; type=res.v1
>>> 08-25 12:55:36.811  4515  5408 I com.patac.hmi.settings-RearviewMirrorAdjustTopic: setData 32770=message: "OSRVMDirectionRequestProcessor process success"
    08-25 12:55:36.812  4515  5408 D [ClsLinkSDK-v0.0.33] ClsLink: CompletableFuture whenComplete Request{id=1f1a0413-6335-6600-bc7f-fd72e8f8f7c6} completed
    08-25 12:55:36.812  4515  5408 I [ClsLinkSDK-v0.0.33] ClsLink: response rpc Request{id='1f1a0413-6335-6600-bc7f-fd72e8f8f7c6'} completed
    08-25 12:55:36.812  4477  4896 D ServiceBus: [Dispatcher] handleResponseMessage end Id= 1f1a0413-636e-69e6-8f77-f3ea29b5da50; requestId= 1f1a0413-6335-6600-bc7f-fd72e8f8f7c6; methodUri= cls:/com.patac.hmi.settings//rpc.response

L32820     08-25 12:55:48.405  4477  5049 D ServiceBus: [RequestRetryManager] addRpcReqToRetryList noRetry taskSize= 0
    08-25 12:55:48.405  4112  4616 D VehicleRequestProcessorFactory: TRY TO GET PROCESSOR: cls:/vehicle/1/rpc.OSRVMDirectionControl
    08-25 12:55:48.405  4515 10235 D [ClsLinkSDK-v0.0.33] ClsLink: invokeMethod Request{id=1f1a0413-d1fa-64f7-bc7f-fd72e8f8f7c6} end
>>> 08-25 12:55:48.405  4112  5471 I OSRVMDirectionRequestProcessor: processRequest: OSRVMDirectionRequestProcessor request, uri: cls:/vehicle/1/rpc.OSRVMDirectionControl
    08-25 12:55:48.405  4515  4515 D com.patac.hmi.settings-CompleteCallback: onComplete
    08-25 12:55:48.406  4112  5471 I OSRVMDirectionRequestProcessor: transStatusVal: 0
    08-25 12:55:48.406  4112  5471 I OSRVMDirectionRequestProcessor: transStatusVal: 1

L32855     08-25 12:55:48.423  4477  5049 D ServiceBus:  client=Client{mCredentials=Credentials{packageName='com.sgm.cls.coreservice', pid=4112, uid=1001000, uri=cls:/com.sgm.cls.coreservice/}, mReleased=false, mBinder=android.os.BinderProxy@88cf756}
    08-25 12:55:48.423  4477  5049 D ServiceBus: [Client] send to cls:/com.patac.hmi.settings/; id= 1f1a0413-d22e-6aeb-8f77-f3ea29b5da50
    08-25 12:55:48.425  4515  4534 D [ClsLinkSDK-v0.0.33] ClsLink: dispatchCloudEvent {id='1f1a0413-d22e-6aeb-8f77-f3ea29b5da50'}; type=res.v1
>>> 08-25 12:55:48.425  4515  4534 I com.patac.hmi.settings-RearviewMirrorAdjustTopic: setData 32770=message: "OSRVMDirectionRequestProcessor process success"
    08-25 12:55:48.425  4515  4534 D [ClsLinkSDK-v0.0.33] ClsLink: CompletableFuture whenComplete Request{id=1f1a0413-d1fa-64f7-bc7f-fd72e8f8f7c6} completed
    08-25 12:55:48.425  4515  4534 I [ClsLinkSDK-v0.0.33] ClsLink: response rpc Request{id='1f1a0413-d1fa-64f7-bc7f-fd72e8f8f7c6'} completed
    08-25 12:55:48.425  4477  5049 D ServiceBus: [Dispatcher] handleResponseMessage end Id= 1f1a0413-d22e-6aeb-8f77-f3ea29b5da50; requestId= 1f1a0413-d1fa-64f7-bc7f-fd72e8f8f7c6; methodUri= cls:/com.patac.hmi.settings//rpc.response

L34829     08-25 12:55:51.171  4112  4616 D [ClsLinkSDK-v0.0.33] ClsLink: handleRequestEvent:  sink: cls:/vehicle/1/rpc.OSRVMDirectionControl, requestId: 1f1a0413-ec5d-6ae8-bc7f-fd72e8f8f7c6, source: cls:/com.patac.hmi.settings//rpc.response
    08-25 12:55:51.171  4112  4616 D VehicleRequestProcessorFactory: TRY TO GET PROCESSOR: cls:/vehicle/1/rpc.OSRVMDirectionControl
    08-25 12:55:51.171  4515 10235 D [ClsLinkSDK-v0.0.33] ClsLink: invokeMethod Request{id=1f1a0413-ec5d-6ae8-bc7f-fd72e8f8f7c6} end
>>> 08-25 12:55:51.171  4112  5471 I OSRVMDirectionRequestProcessor: processRequest: OSRVMDirectionRequestProcessor request, uri: cls:/vehicle/1/rpc.OSRVMDirectionControl
    08-25 12:55:51.171  4515  4515 D com.patac.hmi.settings-CompleteCallback: onComplete
    08-25 12:55:51.171  4112  5471 I OSRVMDirectionRequestProcessor: transStatusVal: 0
    08-25 12:55:51.171  4112  5471 I OSRVMDirectionRequestProcessor: transStatusVal: 0

L34881     08-25 12:55:51.193  4477  5049 D ServiceBus:  client=Client{mCredentials=Credentials{packageName='com.sgm.cls.coreservice', pid=4112, uid=1001000, uri=cls:/com.sgm.cls.coreservice/}, mReleased=false, mBinder=android.os.BinderProxy@88cf756}
    08-25 12:55:51.193  4477  5049 D ServiceBus: [Client] send to cls:/com.patac.hmi.settings/; id= 1f1a0413-ec99-6621-8f77-f3ea29b5da50
    08-25 12:55:51.194  4515  4534 D [ClsLinkSDK-v0.0.33] ClsLink: dispatchCloudEvent {id='1f1a0413-ec99-6621-8f77-f3ea29b5da50'}; type=res.v1
>>> 08-25 12:55:51.194  4515  4534 I com.patac.hmi.settings-RearviewMirrorAdjustTopic: setData 32770=message: "OSRVMDirectionRequestProcessor process success"
    08-25 12:55:51.195  4515  4534 D [ClsLinkSDK-v0.0.33] ClsLink: CompletableFuture whenComplete Request{id=1f1a0413-ec5d-6ae8-bc7f-fd72e8f8f7c6} completed
    08-25 12:55:51.195  4515  4534 I [ClsLinkSDK-v0.0.33] ClsLink: response rpc Request{id='1f1a0413-ec5d-6ae8-bc7f-fd72e8f8f7c6'} completed
    08-25 12:55:51.195  2425  7756 D FSANetCommsClient: FSARemoteClient RX QSize is: 0, funcID: 100, ID: 100

L35063     08-25 12:55:51.401  4112  4616 D [ClsLinkSDK-v0.0.33] ClsLink: handleRequestEvent:  sink: cls:/vehicle/1/rpc.OSRVMDirectionControl, requestId: 1f1a0413-ee8f-6349-bc7f-fd72e8f8f7c6, source: cls:/com.patac.hmi.settings//rpc.response
    08-25 12:55:51.401  4112  4616 D VehicleRequestProcessorFactory: TRY TO GET PROCESSOR: cls:/vehicle/1/rpc.OSRVMDirectionControl
    08-25 12:55:51.401  4515 10235 D [ClsLinkSDK-v0.0.33] ClsLink: invokeMethod Request{id=1f1a0413-ee8f-6349-bc7f-fd72e8f8f7c6} end
>>> 08-25 12:55:51.402  4112  5471 I OSRVMDirectionRequestProcessor: processRequest: OSRVMDirectionRequestProcessor request, uri: cls:/vehicle/1/rpc.OSRVMDirectionControl
    08-25 12:55:51.402  4515  4515 D com.patac.hmi.settings-CompleteCallback: onComplete
    08-25 12:55:51.402  4112  5471 I OSRVMDirectionRequestProcessor: transStatusVal: 0
    08-25 12:55:51.402  4112  5471 I OSRVMDirectionRequestProcessor: transStatusVal: 2

L35093     08-25 12:55:51.417  4477  5049 D ServiceBus:  client=Client{mCredentials=Credentials{packageName='com.sgm.cls.coreservice', pid=4112, uid=1001000, uri=cls:/com.sgm.cls.coreservice/}, mReleased=false, mBinder=android.os.BinderProxy@88cf756}
    08-25 12:55:51.417  4477  5049 D ServiceBus: [Client] send to cls:/com.patac.hmi.settings/; id= 1f1a0413-eebe-6b34-8f77-f3ea29b5da50
    08-25 12:55:51.418  4515  4534 D [ClsLinkSDK-v0.0.33] ClsLink: dispatchCloudEvent {id='1f1a0413-eebe-6b34-8f77-f3ea29b5da50'}; type=res.v1
>>> 08-25 12:55:51.418  4515  4534 I com.patac.hmi.settings-RearviewMirrorAdjustTopic: setData 32770=message: "OSRVMDirectionRequestProcessor process success"
    08-25 12:55:51.418  4515  4534 D [ClsLinkSDK-v0.0.33] ClsLink: CompletableFuture whenComplete Request{id=1f1a0413-ee8f-6349-bc7f-fd72e8f8f7c6} completed
    08-25 12:55:51.418  4515  4534 I [ClsLinkSDK-v0.0.33] ClsLink: response rpc Request{id='1f1a0413-ee8f-6349-bc7f-fd72e8f8f7c6'} completed
    08-25 12:55:51.419  4477  5049 D ServiceBus: [Dispatcher] handleResponseMessage end Id= 1f1a0413-eebe-6b34-8f77-f3ea29b5da50; requestId= 1f1a0413-ee8f-6349-bc7f-fd72e8f8f7c6; methodUri= cls:/com.patac.hmi.settings//rpc.response

⚠️ 搜索结果高度重复: 共 30 条匹配中，有 30 条内容相同 ('')。以上仅展示 12 条代表性结果。

---

[结果 3] 搜索结果: 共 30 条匹配，显示 7 条

L17122     08-25 12:55:22.451  4112  5150 D VehicleSomeIpClient: resp.getPassengerMirCnfign():true
    08-25 12:55:22.451  4112  5150 D VehicleSomeIpClient: resp.getDriverMirAvl():false
    08-25 12:55:22.451  4112  5150 D VehicleSomeIpClient: resp.getPassengerMirAvl():false
>>> 08-25 12:55:22.451  4112  5150 I OSRVMMapper: sendTopic: send OSRVM OSRVM.left
    08-25 12:55:22.451  4112  5150 I OSRVMMapper: setRespondingFeatureValue: 0
    08-25 12:55:22.452  4112  5150 I OSRVMMapper: HorizontalAngle: -2
    08-25 12:55:22.452  4112  5150 I OSRVMMapper: setHorizontalAngle: -0.2

L17129     08-25 12:55:22.452  4112  5150 I OSRVMMapper: VerticalAngle: -56
    08-25 12:55:22.452  4112  5150 I OSRVMMapper: setVerticalAngle: -5.6
    08-25 12:55:22.452  4112  5150 I OSRVMMapper: IsSupported: true
>>> 08-25 12:55:22.453  4112  5150 I OSRVMMapper: Left IsAllowed: false
    08-25 12:55:22.453  4112  5150 D SDV_CoreService: [SomeIpUtil]uri: cls:/vehicle/1/OSRVM.left#OSRVM
    08-25 12:55:22.453  4112  5115 D TimeResult: SystemClock: 3602994, ElapsedRealtimeMillis: 1892235
    08-25 12:55:22.453  4112  5115 D TimeResult: mTimeMillis: 1787632011696, AgeMillis: 1710759

L17322     08-25 12:55:22.726  4112  5150 D VehicleSomeIpClient: resp.getDriverMirHznPsnFdbck():-2
    08-25 12:55:22.726  4112  5150 D VehicleSomeIpClient: resp.getDriverMirPsnValdty():0
    08-25 12:55:22.726  4112  5150 D VehicleSomeIpClient: resp.getDriverMirVertclPsnFdbck():-67
>>> 08-25 12:55:22.727  4112  5150 I OSRVMMapper: sendTopic: send OSRVM OSRVM.left
    08-25 12:55:22.727  4112  5150 I OSRVMMapper: setRespondingFeatureValue: 0
    08-25 12:55:22.727  4515  4515 D HardKeyInterceptorManager: dispatch keyEventKeyEvent { action=ACTION_DOWN, keyCode=KEYCODE_VOLUME_DOWN, scanCode=0, metaState=0, flags=0x0, repeatCount=11, eventTime=2370043000000, downTime=2370043000000, deviceId=0, source=0x101, displayId=0 } on callback com.patac.
    08-25 12:55:22.727  4112  5150 I OSRVMMapper: HorizontalAngle: -2

L17329     08-25 12:55:22.727  4112  5150 I OSRVMMapper: setHorizontalAngle: -0.2
    08-25 12:55:22.727  4112  5150 I OSRVMMapper: VerticalAngle: -67
    08-25 12:55:22.727  4112  5150 I OSRVMMapper: setVerticalAngle: -6.7
>>> 08-25 12:55:22.727  4112  5150 I OSRVMMapper: IsSupported: true
    08-25 12:55:22.727  4515  4515 D com.patac.hmi.settings-SteeringWheelHardKeyUtil: processSWCOperation keyEvent = KeyEvent { action=ACTION_DOWN, keyCode=KEYCODE_VOLUME_DOWN, scanCode=0, metaState=0, flags=0x0, repeatCount=11, eventTime=2370043000000, downTime=2370043000000, deviceId=0, source=0x101, 
    08-25 12:55:22.727  4112  5150 I OSRVMMapper: Left IsAllowed: false
    08-25 12:55:22.727  4112  5150 D SDV_CoreService: [SomeIpUtil]uri: cls:/vehicle/1/OSRVM.left#OSRVM

L17337     08-25 12:55:22.727  4112  5150 D VehicleSomeIpClient: resp.getPassengerMirHznPsnFdbck():0
    08-25 12:55:22.727  4112  5150 D VehicleSomeIpClient: resp.getPassengerMirPsnValdty():0
    08-25 12:55:22.727  4112  5150 D VehicleSomeIpClient: resp.getPassengerMirVertclPsnFdbck():-52
>>> 08-25 12:55:22.727  4112  5150 I OSRVMMapper: sendTopic: send OSRVM OSRVM.right
    08-25 12:55:22.727  4112  5150 I OSRVMMapper: setRespondingFeatureValue: 0
    08-25 12:55:22.727  4112  5150 I OSRVMMapper: HorizontalAngle: 0
    08-25 12:55:22.727  4112  5150 I OSRVMMapper: setHorizontalAngle: 0.0

L17344     08-25 12:55:22.727  4112  5150 I OSRVMMapper: VerticalAngle: -52
    08-25 12:55:22.727  4112  5150 I OSRVMMapper: setVerticalAngle: -5.2
    08-25 12:55:22.727  4112  5150 I OSRVMMapper: IsSupported: true
>>> 08-25 12:55:22.727  4112  5150 I OSRVMMapper: Right IsAllowed: false
    08-25 12:55:22.727  4112  5150 D SDV_CoreService: [SomeIpUtil]uri: cls:/vehicle/1/OSRVM.right#OSRVM
    08-25 12:55:22.727  4112  5115 D TimeResult: SystemClock: 3603268, ElapsedRealtimeMillis: 1892235
    08-25 12:55:22.727  4112  5115 D TimeResult: mTimeMillis: 1787632011696, AgeMillis: 1711033

L17546     08-25 12:55:23.031  4112  5038 D SDV_CoreService: [RearLeftDoorSignalTopicMapper]resp.getSRlVCPWLSCurrSeltnVal():2
    08-25 12:55:23.031  4112  5039 D SDV_CoreService: [RearRightDoorSignalTopicMapper]resp.srrvcpwlsCurrSeltnVal():2
    08-25 12:55:23.031  4112  5150 D VehicleSomeIpClient: resp.getDriverMirVertclPsnFdbck():-78
>>> 08-25 12:55:23.031  4112  5150 I OSRVMMapper: sendTopic: send OSRVM OSRVM.left
    08-25 12:55:23.031  4112  5118 I SDV_CoreService: [RearRightWindowTopicMapper]someIp srrvcpwlsCurrSeltnVal： 2rrWndAval： truerrWndCfg： true
    08-25 12:55:23.031  4112  5150 I OSRVMMapper: setRespondingFeatureValue: 0
    08-25 12:55:23.031  4112  5150 I OSRVMMapper: HorizontalAngle: -2

⚠️ 搜索结果高度重复: 共 30 条匹配中，有 30 条内容相同 ('')。以上仅展示 7 条代表性结果。

---

## 第 2 轮 — LLM 响应

关键发现：OSRVMMapper 中出现了 `HorizontalAngle`、`VerticalAngle`、`setHorizontalAngle`、`setVerticalAngle` 等字段，这正是后视镜角度记忆的核心。我需要读取 OSRVMMapper 的完整上下文，理解角度是如何被设置和读取的。

让我先看 OSRVMMapper 的完整日志，以及搜索与"记忆/保存"相关的关键词。



---

## 第 2 轮 — 工具执行结果

[结果 1] 搜索结果: 共 40 条匹配，显示 10 条

L17122     08-25 12:55:22.451  4112  5150 D VehicleSomeIpClient: resp.getDriverMirAvl():false
    08-25 12:55:22.451  4112  5150 D VehicleSomeIpClient: resp.getPassengerMirAvl():false
>>> 08-25 12:55:22.451  4112  5150 I OSRVMMapper: sendTopic: send OSRVM OSRVM.left
    08-25 12:55:22.451  4112  5150 I OSRVMMapper: setRespondingFeatureValue: 0
    08-25 12:55:22.452  4112  5150 I OSRVMMapper: HorizontalAngle: -2

L17127     08-25 12:55:22.452  4112  5150 I OSRVMMapper: setHorizontalAngle: -0.2
    08-25 12:55:22.452  4112  5150 I OSRVMMapper: VerticalAngle: -56
>>> 08-25 12:55:22.452  4112  5150 I OSRVMMapper: setVerticalAngle: -5.6
    08-25 12:55:22.452  4112  5150 I OSRVMMapper: IsSupported: true
    08-25 12:55:22.453  4112  5150 I OSRVMMapper: Left IsAllowed: false

L17322     08-25 12:55:22.726  4112  5150 D VehicleSomeIpClient: resp.getDriverMirPsnValdty():0
    08-25 12:55:22.726  4112  5150 D VehicleSomeIpClient: resp.getDriverMirVertclPsnFdbck():-67
>>> 08-25 12:55:22.727  4112  5150 I OSRVMMapper: sendTopic: send OSRVM OSRVM.left
    08-25 12:55:22.727  4112  5150 I OSRVMMapper: setRespondingFeatureValue: 0
    08-25 12:55:22.727  4515  4515 D HardKeyInterceptorManager: dispatch keyEventKeyEvent { action=ACTION_DOWN, keyCode=KEYCODE_VOLUME_DOWN, scanCode=0, metaState=0, flags=0x0, repeatCount=11, eventTime=2370043000000, downTime=2370043000000, deviceId=0, source=0x101, displayId=0 } on callback com.patac.

L17327     08-25 12:55:22.727  4112  5150 I OSRVMMapper: HorizontalAngle: -2
    08-25 12:55:22.727  4112  5150 I OSRVMMapper: setHorizontalAngle: -0.2
>>> 08-25 12:55:22.727  4112  5150 I OSRVMMapper: VerticalAngle: -67
    08-25 12:55:22.727  4112  5150 I OSRVMMapper: setVerticalAngle: -6.7
    08-25 12:55:22.727  4112  5150 I OSRVMMapper: IsSupported: true

L17337     08-25 12:55:22.727  4112  5150 D VehicleSomeIpClient: resp.getPassengerMirPsnValdty():0
    08-25 12:55:22.727  4112  5150 D VehicleSomeIpClient: resp.getPassengerMirVertclPsnFdbck():-52
>>> 08-25 12:55:22.727  4112  5150 I OSRVMMapper: sendTopic: send OSRVM OSRVM.right
    08-25 12:55:22.727  4112  5150 I OSRVMMapper: setRespondingFeatureValue: 0
    08-25 12:55:22.727  4112  5150 I OSRVMMapper: HorizontalAngle: 0

L17342     08-25 12:55:22.727  4112  5150 I OSRVMMapper: setHorizontalAngle: 0.0
    08-25 12:55:22.727  4112  5150 I OSRVMMapper: VerticalAngle: -52
>>> 08-25 12:55:22.727  4112  5150 I OSRVMMapper: setVerticalAngle: -5.2
    08-25 12:55:22.727  4112  5150 I OSRVMMapper: IsSupported: true
    08-25 12:55:22.727  4112  5150 I OSRVMMapper: Right IsAllowed: false

L17546     08-25 12:55:23.031  4112  5039 D SDV_CoreService: [RearRightDoorSignalTopicMapper]resp.srrvcpwlsCurrSeltnVal():2
    08-25 12:55:23.031  4112  5150 D VehicleSomeIpClient: resp.getDriverMirVertclPsnFdbck():-78
>>> 08-25 12:55:23.031  4112  5150 I OSRVMMapper: sendTopic: send OSRVM OSRVM.left
    08-25 12:55:23.031  4112  5118 I SDV_CoreService: [RearRightWindowTopicMapper]someIp srrvcpwlsCurrSeltnVal： 2rrWndAval： truerrWndCfg： true
    08-25 12:55:23.031  4112  5150 I OSRVMMapper: setRespondingFeatureValue: 0

L17551     08-25 12:55:23.031  4112  5150 I OSRVMMapper: HorizontalAngle: -2
    08-25 12:55:23.031  4112  5150 I OSRVMMapper: setHorizontalAngle: -0.2
>>> 08-25 12:55:23.031  4112  5150 I OSRVMMapper: VerticalAngle: -78
    08-25 12:55:23.031  4112  5150 I OSRVMMapper: setVerticalAngle: -7.8
    08-25 12:55:23.031  4112  5150 I OSRVMMapper: IsSupported: true

L17726     08-25 12:55:23.331  4112  5039 D SDV_CoreService: [RearRightDoorSignalTopicMapper]resp.srrvcpwlsCurrSeltnVal():2
    08-25 12:55:23.331  4112  5150 D VehicleSomeIpClient: resp.getDriverMirVertclPsnFdbck():-85
>>> 08-25 12:55:23.332  4112  5150 I OSRVMMapper: sendTopic: send OSRVM OSRVM.left
    08-25 12:55:23.332  4112  5150 I OSRVMMapper: setRespondingFeatureValue: 0
    08-25 12:55:23.332  4112  5150 I OSRVMMapper: HorizontalAngle: -2

L17731     08-25 12:55:23.332  4112  5150 I OSRVMMapper: setHorizontalAngle: -0.2
    08-25 12:55:23.332  4112  5150 I OSRVMMapper: VerticalAngle: -85
>>> 08-25 12:55:23.332  4112  5150 I OSRVMMapper: setVerticalAngle: -8.5
    08-25 12:55:23.332  4112  5150 I OSRVMMapper: IsSupported: true
    08-25 12:55:23.332  4112  5150 I OSRVMMapper: Left IsAllowed: false

⚠️ 搜索结果高度重复: 共 40 条匹配中，有 30 条内容相同 ('')。以上仅展示 10 条代表性结果。

---

[结果 2] 搜索结果: 共 30 条匹配，显示 15 条

L47024     08-25 12:56:07.086  5951  6023 D CPECallbackController: Dropping carPropertyEvent - propId: 291504647 areaId: 16777216  because getTimestamp(): 3647639639816 < nextUpdateTimeNanos: 3647839639816
    08-25 12:56:07.110   723  7407 D AHAL: AudioEthernetProperty: AudioEthernetProperty:vStartClientThread heartbeat
    08-25 12:56:07.114  4112  4749 D SDV_CoreService: [automaticShutdown_VehicleAutomaticShutdownManager]signalUpdate: []
>>> 08-25 12:56:07.114  4112  4749 D SDV_CoreService: [automaticShutdown_AutomaticShutdownTopicSender]sendTopic currentProfiles = [], abortProfiles = []
    08-25 12:56:07.114  4112  4749 D SDV_CoreService: [automaticShutdown_util] isAvailableAutoMaticShutdown = false
    08-25 12:56:07.115  4112  4749 D SDV_CoreService: [automaticShutdown_util] getPowerMode = 2
    08-25 12:56:07.115  4112  4749 D SDV_CoreService: [automaticShutdown_util] getVehicleMotionMovementState = 1

L48008     08-25 12:56:07.817  2015  2196 D GMLocation: Service reportLocation() at time(ms) = 3648358
    08-25 12:56:07.817  2015  2196 D GMLocation: Service reportLocation(), Source = HAL
    08-25 12:56:07.817  4112  5535 D SDV_CoreService: [automaticShutdown_VehicleAutomaticShutdownManager]signalUpdate: []
>>> 08-25 12:56:07.817  4112  5535 D SDV_CoreService: [automaticShutdown_AutomaticShutdownTopicSender]sendTopic currentProfiles = [], abortProfiles = []
    08-25 12:56:07.818  4112  5535 D SDV_CoreService: [automaticShutdown_util] isAvailableAutoMaticShutdown = true
    08-25 12:56:07.818  4112  5535 D SDV_CoreService: [automaticShutdown_util] getPowerMode = 2
    08-25 12:56:07.818  4112  5535 D SDV_CoreService: [automaticShutdown_util] getVehicleMotionMovementState = 0

L48149     08-25 12:56:07.968  4112  5150 I SeatMemoryMapper: setSeatMemStatus MIRCUSTSELTNSTK: false MIRCUSTSELTNACTV: false
    08-25 12:56:07.968  4112  5150 I SeatMemoryMapper: stuck: false active: false activeKey: mirrorActive
    08-25 12:56:07.968  4112  5150 I SeatMemoryMapper: sendDriverSeatTopic: true RecallAvailabletrue MemoryStatus: 0 IsSeatAdjusted: false IsColumnAdjusted: false IsMirrorAdjusted: false
>>> 08-25 12:56:07.968  4112  5150 D SDV_CoreService: [SomeIpUtil]uri: cls:/body.seating/1/seat.row1_left#SeatMemory
    08-25 12:56:07.969  4112  5115 D TimeResult: SystemClock: 3648510, ElapsedRealtimeMillis: 1892235
    08-25 12:56:07.969  4112  5115 D TimeResult: mTimeMillis: 1787632011696, AgeMillis: 1756275
    08-25 12:56:07.969  4112  5115 D SDV_CoreService: [SomeIpUtil]publish event: uri: cls:/body.seating/1/seat.row1_left#SeatMemory

L50048     08-25 12:56:10.630  1683  2271 W ActivityManager: Unable to start service Intent { cmp=com.baidu.che.codriver/.dcsservice.CoDriverService } U=10: not found
    08-25 12:56:10.630  4683  4683 D CoDriverSDK: BridgeManager: bind result = false
    08-25 12:56:10.632  4112  5535 D SDV_CoreService: [automaticShutdown_VehicleAutomaticShutdownManager]signalUpdate: []
>>> 08-25 12:56:10.632  4112  5535 D SDV_CoreService: [automaticShutdown_AutomaticShutdownTopicSender]sendTopic currentProfiles = [], abortProfiles = []
    08-25 12:56:10.632  4112  5535 D SDV_CoreService: [automaticShutdown_util] isAvailableAutoMaticShutdown = false
    08-25 12:56:10.632  4112  5535 D SDV_CoreService: [automaticShutdown_util] getPowerMode = 2
    08-25 12:56:10.632  4112  5535 D SDV_CoreService: [automaticShutdown_util] getVehicleMotionMovementState = 2

L50175     08-25 12:56:10.679  4112  5150 I SeatMemoryMapper: setSeatMemStatus MIRCUSTSELTNSTK: false MIRCUSTSELTNACTV: false
    08-25 12:56:10.679  4112  5150 I SeatMemoryMapper: stuck: false active: false activeKey: mirrorActive
    08-25 12:56:10.679  4112  5150 I SeatMemoryMapper: sendDriverSeatTopic: true RecallAvailablefalse MemoryStatus: 0 IsSeatAdjusted: false IsColumnAdjusted: false IsMirrorAdjusted: false
>>> 08-25 12:56:10.679  4112  5150 D SDV_CoreService: [SomeIpUtil]uri: cls:/body.seating/1/seat.row1_left#SeatMemory
    08-25 12:56:10.680  4112  5115 D TimeResult: SystemClock: 3651221, ElapsedRealtimeMillis: 1892235
    08-25 12:56:10.680  4112  5115 D TimeResult: mTimeMillis: 1787632011696, AgeMillis: 1758986
    08-25 12:56:10.680  4112  5115 D SDV_CoreService: [SomeIpUtil]publish event: uri: cls:/body.seating/1/seat.row1_left#SeatMemory

L52756     08-25 12:56:13.044  1683  1859 D JobScheduler.Concurrency: Pending queue: 
    08-25 12:56:13.044  4691  4691 D PhoneWindow: setStatusBarColor: #0 called by UID: 1010039 (com.patac.hmi.camera)
    08-25 12:56:13.045  4112  5535 D SDV_CoreService: [automaticShutdown_VehicleAutomaticShutdownManager]signalUpdate: []
>>> 08-25 12:56:13.046  4112  5535 D SDV_CoreService: [automaticShutdown_AutomaticShutdownTopicSender]sendTopic currentProfiles = [], abortProfiles = []
    08-25 12:56:13.046  4112  5535 D SDV_CoreService: [automaticShutdown_util] isAvailableAutoMaticShutdown = false
    08-25 12:56:13.046  4112  5535 D SDV_CoreService: [automaticShutdown_util] getPowerMode = 2
    08-25 12:56:13.046  4112  5535 D SDV_CoreService: [automaticShutdown_util] getVehicleMotionMovementState = 3

L60653     08-25 12:56:23.279  2015  2249 D nfsa.transport.out: /172.16.4.1:54590: Heartbeat( 100 ) Status, clientHandle = 0, service= 1026.1, 23 bytes
    08-25 12:56:23.285  5951  6023 I ChildLockRepository: onSpeedOfVehicleSignalChanged 0.0
    08-25 12:56:23.296  4112  4749 D SDV_CoreService: [automaticShutdown_VehicleAutomaticShutdownManager]signalUpdate: []
>>> 08-25 12:56:23.296  4112  4749 D SDV_CoreService: [automaticShutdown_AutomaticShutdownTopicSender]sendTopic currentProfiles = [], abortProfiles = []
    08-25 12:56:23.296  4112  4749 D SDV_CoreService: [automaticShutdown_util] isAvailableAutoMaticShutdown = false
    08-25 12:56:23.297  4112  4749 D SDV_CoreService: [automaticShutdown_util] getPowerMode = 2
    08-25 12:56:23.297  4112  4749 D SDV_CoreService: [automaticShutdown_util] getVehicleMotionMovementState = 1

L61859     08-25 12:56:23.953  4112  5150 I SeatMemoryMapper: setSeatMemStatus MIRCUSTSELTNSTK: false MIRCUSTSELTNACTV: false
    08-25 12:56:23.953  4112  5150 I SeatMemoryMapper: stuck: false active: false activeKey: mirrorActive
    08-25 12:56:23.953  4112  5150 I SeatMemoryMapper: sendDriverSeatTopic: true RecallAvailabletrue MemoryStatus: 0 IsSeatAdjusted: false IsColumnAdjusted: false IsMirrorAdjusted: false
>>> 08-25 12:56:23.953  4112  5150 D SDV_CoreService: [SomeIpUtil]uri: cls:/body.seating/1/seat.row1_left#SeatMemory
    08-25 12:56:23.953  2425  7756 D FSANetCommsClient: FSARemoteClient RX QSize is: 0, funcID: 9732, ID: 9732
    08-25 12:56:23.953  1371  1462 D GMVHAL  : setPropFromVehicle Property: VendorProperty::ODI_EVENT AreaID: 16777216 Status: 0 int32Values: 237 1 
    08-25 12:56:23.953  2425  2458 D FSAClientMessageRouter: FSA: routing message from 9907, functionId 9732, opType 1032

L61885     08-25 12:56:23.956  4477  5049 D ServiceBus: [Dispatcher] Received handleGenericMessage CloudEvent=CloudEvent{id='1f1a0415-250f-6b02-8f77-f3ea29b5da50', source=cls:/energy.power_management/1/notification#ExtendMode, type='pub.v1', datacontenttype='application/x-protobuf', dataschema=type.googleapis.
    08-25 12:56:23.956  4112  5115 D TimeResult: SystemClock: 3664497, ElapsedRealtimeMillis: 1892235
    08-25 12:56:23.956  4112  5115 D TimeResult: mTimeMillis: 1787632011696, AgeMillis: 1772262
>>> 08-25 12:56:23.956  4112  5115 D SDV_CoreService: [SomeIpUtil]publish event: uri: cls:/body.seating/1/seat.row1_left#SeatMemory
    08-25 12:56:23.956  4112  5115 D [ClsLinkSDK-v0.0.33] BusClient: send: {id='1f1a0415-2512-6213-8f77-f3ea29b5da50'}
    08-25 12:56:23.956  4477  5049 D ServiceBus: [Dispatcher] Received handleGenericMessage CloudEvent=CloudEvent{id='1f1a0415-2512-6213-8f77-f3ea29b5da50', source=cls:/body.seating/1/seat.row1_left#SeatMemory, type='pub.v1', datacontenttype='application/x-protobuf', dataschema=type.googleapis.com/cls.v
    08-25 12:56:23.956  4477  5049 D ServiceBus: [Client] send to cls:/com.patac.hmi.user/; id= 1f1a0415-2512-6213-8f77-f3ea29b5da50

L61967     08-25 12:56:23.997  1683  1882 D InputTransport: channel 'PointerEventDispatcher0 (server)' ~ received message of type FINISHED
    08-25 12:56:23.997  1683  1882 D InputTransport: channel 'PointerEventDispatcher0 (server)' ~ receive message failed, errno=11
    08-25 12:56:23.997  4112  4748 D SDV_CoreService: [automaticShutdown_VehicleAutomaticShutdownManager]signalUpdate: []
>>> 08-25 12:56:23.997  4112  4748 D SDV_CoreService: [automaticShutdown_AutomaticShutdownTopicSender]sendTopic currentProfiles = [], abortProfiles = []
    08-25 12:56:23.997  4112  4748 D SDV_CoreService: [automaticShutdown_util] isAvailableAutoMaticShutdown = true
    08-25 12:56:23.997  4112  4748 D SDV_CoreService: [automaticShutdown_util] getPowerMode = 2
    08-25 12:56:23.997  4112  4748 D SDV_CoreService: [automaticShutdown_util] getVehicleMotionMovementState = 0

L131410     08-25 12:58:37.548  4112  5118 I SDV_CoreService: [RearRightWindowTopicMapper]someIp srrvcpwlsCurrSeltnVal： 2rrWndAval： truerrWndCfg： true
    08-25 12:58:37.548  4112  5150 E SDV_CoreService: [SomeIpTopicReceiverManager]not found receiver by topic 2533279085461546
    08-25 12:58:37.549  4112  4748 D SDV_CoreService: [automaticShutdown_VehicleAutomaticShutdownManager]signalUpdate: []
>>> 08-25 12:58:37.549  4112  4748 D SDV_CoreService: [automaticShutdown_AutomaticShutdownTopicSender]sendTopic currentProfiles = [], abortProfiles = []
    08-25 12:58:37.549  4112  4748 D SDV_CoreService: [automaticShutdown_util] isAvailableAutoMaticShutdown = false
    08-25 12:58:37.549  4112  4748 D SDV_CoreService: [automaticShutdown_util] getPowerMode = 2
    08-25 12:58:37.549  4112  4748 D SDV_CoreService: [automaticShutdown_util] getVehicleMotionMovementState = 3

L131497     08-25 12:58:37.556  4112  5150 I SeatMemoryMapper: setSeatMemStatus MIRCUSTSELTNSTK: false MIRCUSTSELTNACTV: false
    08-25 12:58:37.556  4112  5150 I SeatMemoryMapper: stuck: false active: false activeKey: mirrorActive
    08-25 12:58:37.556  4112  5150 I SeatMemoryMapper: sendDriverSeatTopic: true RecallAvailablefalse MemoryStatus: 0 IsSeatAdjusted: false IsColumnAdjusted: false IsMirrorAdjusted: false
>>> 08-25 12:58:37.556  4112  5150 D SDV_CoreService: [SomeIpUtil]uri: cls:/body.seating/1/seat.row1_left#SeatMemory
    08-25 12:58:37.557  4477  4896 D ServiceBus: [Dispatcher] Received handleGenericMessage CloudEvent=CloudEvent{id='1f1a041a-1f24-6694-8f77-f3ea29b5da50', source=cls:/energy.power_management/1/vehicle#VehicleAutomaticShutdown, type='pub.v1', datacontenttype='application/x-protobuf', dataschema=type.go
    08-25 12:58:37.557  4477  4896 D ServiceBus: [Client] send to cls:/com.android.systemui/; id= 1f1a041a-1f24-6694-8f77-f3ea29b5da50
    08-25 12:58:37.558  1371  1462 D GMVHAL  : setPropFromVehicle Property: VendorProperty::ODI_EVENT AreaID: 16777216 Status: 0 int32Values: 237 1 

L131525     08-25 12:58:37.561  2073  2073 D PatacExtendPowerOffController: updateFrom: 0
    08-25 12:58:37.561  4112  5115 D TimeResult: SystemClock: 3798102, ElapsedRealtimeMillis: 1892235
    08-25 12:58:37.561  4112  5115 D TimeResult: mTimeMillis: 1787632011696, AgeMillis: 1905867
>>> 08-25 12:58:37.561  4112  5115 D SDV_CoreService: [SomeIpUtil]publish event: uri: cls:/body.seating/1/seat.row1_left#SeatMemory
    08-25 12:58:37.561  4112  5115 D [ClsLinkSDK-v0.0.33] BusClient: send: {id='1f1a041a-1f37-6f15-8f77-f3ea29b5da50'}
    08-25 12:58:37.561  2425  2490 D PatacOdiPropService: DYN updated: [237, 1, 1, 3, 1]
    08-25 12:58:37.561  2073  4040 I PatacOdiManager: array[DYN_VALUE_INDEX]: 1electricValue:150

L133479     08-25 12:58:39.826  2015  2196 D GMLocation: Service reportLocation() at time(ms) = 3800367
    08-25 12:58:39.826  2015  2196 D GMLocation: Service reportLocation(), Source = HAL
    08-25 12:58:39.850  4112  5535 D SDV_CoreService: [automaticShutdown_VehicleAutomaticShutdownManager]signalUpdate: []
>>> 08-25 12:58:39.850  4112  5535 D SDV_CoreService: [automaticShutdown_AutomaticShutdownTopicSender]sendTopic currentProfiles = [], abortProfiles = []
    08-25 12:58:39.851  4112  5535 D SDV_CoreService: [automaticShutdown_util] isAvailableAutoMaticShutdown = false
    08-25 12:58:39.851  4112  5535 D SDV_CoreService: [automaticShutdown_util] getPowerMode = 2
    08-25 12:58:39.851  4112  5535 D SDV_CoreService: [automaticShutdown_util] getVehicleMotionMovementState = 3

L159221     08-25 12:59:24.845   723  7408 D audiohalservice: vUpdateVolumegroupMap: assign Volume for Group = VOL_GROUP_HEADREST_RR and volume = 0
    08-25 12:59:24.853  2015  2249 D nfsa.transport.out: /172.16.4.1:54590: Heartbeat( 100 ) Status, clientHandle = 0, service= 1026.1, 23 bytes
    08-25 12:59:24.880  4112  5535 D SDV_CoreService: [automaticShutdown_VehicleAutomaticShutdownManager]signalUpdate: []
>>> 08-25 12:59:24.880  4112  5535 D SDV_CoreService: [automaticShutdown_AutomaticShutdownTopicSender]sendTopic currentProfiles = [], abortProfiles = []
    08-25 12:59:24.880  4112  5535 D SDV_CoreService: [automaticShutdown_util] isAvailableAutoMaticShutdown = false
    08-25 12:59:24.880  4112  5535 D SDV_CoreService: [automaticShutdown_util] getPowerMode = 2
    08-25 12:59:24.880  4112  5535 D SDV_CoreService: [automaticShutdown_util] getVehicleMotionMovementState = 1

⚠️ 搜索结果高度重复: 共 30 条匹配中，有 30 条内容相同 ('')。以上仅展示 15 条代表性结果。

---

## 第 3 轮 — LLM 响应

我注意到关键信息：OSRVMMapper 中 `HorizontalAngle`/`VerticalAngle` 是来自 SomeIP 反馈（`getDriverMirHznPsnFdbck`、`getDriverMirVertclPsnFdbck`），这是**当前实际位置反馈**，不是记忆位置。

关键线索：`OSRVMTiltControlRequestProcessor` 的 processRequest 日志非常简略，没有打印请求参数（角度值）。我需要看这个 Processor 的完整处理逻辑，以及它如何决定下翻角度。

让我读取 OSRVMTiltControlRequestProcessor 的完整上下文，并搜索设置侧（com.patac.hmi.settings）保存后视镜下翻位置的日志。



---

## 第 3 轮 — 工具执行结果

[结果 1] 时间范围 [12:55:24.000 ~ 12:55:31.000] (PID=4112): 共 899 行
涉及的 PID: 4112
涉及的 TAG: CabinAirQualityTopic, CabinClimateTopicMappingFactory, CabinParticlesPollution, ChassisTopicMappingFactory, EnergySomeIpClient, EnergyStateTopicMapper, EnergyTopicMappingFactory, LightTopicMappingFactory, LightingSomeIpClient, OSRVMDirectionRequestProcessor

08-25 12:55:24.236  4112  5150 D SDV_CoreService: [SomeIpTopicReceiverManager]topic 2533279085461923
08-25 12:55:24.236  4112  5150 I SDV_CoreService: [ThirdRowLeftDoorSomeIpTopicMapper]SUCCESS: NOTIFY_BODY_INFORMATION_17
08-25 12:55:24.236  4112  5018 D SDV_CoreService: [RearLeftWindowTopicMapper]someIp sRlVCPWLSCurrSeltnVal: 2  rlWndAval: true  sRlWndCfg: true
08-25 12:55:24.236  4112  5019 D SDV_CoreService: [FrontLeftWindowTopicMapper]someIp sRlVCPWLSCurrSeltnVal: 2 drvWndAval: true drvWndCfg: true
08-25 12:55:24.236  4112  5119 D SDV_CoreService: [FrontRightWindowTopicMapper]someIp srrvcpwlsCurrSeltnVal: 2 psWndAval: true psWndCfg: true
08-25 12:55:24.236  4112  5150 D SDV_CoreService: [ThirdRowLeftDoorSomeIpTopicMapper]resp.getSRlVCPWLSCurrSeltnVal(): 2
08-25 12:55:24.236  4112  5150 I SDV_CoreService: [ThirdRowRightDoorSomeIpTopicMapper]SUCCESS: NOTIFY_BODY_INFORMATION_17
08-25 12:55:24.237  4112  5150 D SDV_CoreService: [ThirdRowRightDoorSomeIpTopicMapper]resp.getSRRVCPWLSCurrSeltnVal(): 2
08-25 12:55:24.237  4112  5038 D SDV_CoreService: [RearLeftDoorSignalTopicMapper]SUCCESS: NOTIFY_BODY_INFORMATION_17
08-25 12:55:24.237  4112  5150 D VehicleSomeIpClient: NOTIFY_BODY_INFORMATION_17
08-25 12:55:24.237  4112  5150 D VehicleSomeIpClient: resp.getDriverMirHznPsnFdbck():-2
08-25 12:55:24.237  4112  5150 D VehicleSomeIpClient: resp.getDriverMirPsnValdty():0
08-25 12:55:24.237  4112  5118 I SDV_CoreService: [RearRightWindowTopicMapper]someIp srrvcpwlsCurrSeltnVal： 2rrWndAval： truerrWndCfg： true
08-25 12:55:24.237  4112  5039 D SDV_CoreService: [RearRightDoorSignalTopicMapper]SUCCESS: NOTIFY_BODY_INFORMATION_17
08-25 12:55:24.237  4112  5038 D SDV_CoreService: [RearLeftDoorSignalTopicMapper]resp.getSRlVCPWLSCurrSeltnVal():2
08-25 12:55:24.237  4112  5150 D VehicleSomeIpClient: resp.getDriverMirVertclPsnFdbck():-108
08-25 12:55:24.237  4112  5150 I OSRVMMapper: sendTopic: send OSRVM OSRVM.left
08-25 12:55:24.238  4112  5039 D SDV_CoreService: [RearRightDoorSignalTopicMapper]resp.srrvcpwlsCurrSeltnVal():2
08-25 12:55:24.238  4112  5150 I OSRVMMapper: setRespondingFeatureValue: 0
08-25 12:55:24.238  4112  5150 I OSRVMMapper: HorizontalAngle: -2
08-25 12:55:24.238  4112  5150 I OSRVMMapper: setHorizontalAngle: -0.2
08-25 12:55:24.238  4112  5150 I OSRVMMapper: VerticalAngle: -108
08-25 12:55:24.238  4112  5150 I OSRVMMapper: setVerticalAngle: -10.8
08-25 12:55:24.238  4112  5150 I OSRVMMapper: IsSupported: true
08-25 12:55:24.238  4112  5150 I OSRVMMapper: Left IsAllowed: false
08-25 12:55:24.238  4112  5150 D SDV_CoreService: [SomeIpUtil]uri: cls:/vehicle/1/OSRVM.left#OSRVM
08-25 12:55:24.239  4112  5115 D TimeResult: SystemClock: 3604780, ElapsedRealtimeMillis: 1892235
08-25 12:55:24.239  4112  5115 D TimeResult: mTimeMillis: 1787632011696, AgeMillis: 1712545
08-25 12:55:24.239  4112  5115 D SDV_CoreService: [SomeIpUtil]publish event: uri: cls:/vehicle/1/OSRVM.left#OSRVM
08-25 12:55:24.239  4112  5115 D [ClsLinkSDK-v0.0.33] BusClient: send: {id='1f1a0412-eb8e-6209-8f77-f3ea29b5da50'}
08-25 12:55:24.249  4112  7399 D [ClsLinkSDK-v0.0.33] ClsLink: dispatchCloudEvent {id='1f1a0412-eba3-605c-bc7f-fd72e8f8f7c6'}; type=req.v1
08-25 12:55:24.249  4112  4616 D [ClsLinkSDK-v0.0.33] ClsLink: handleRequestEvent:  sink: cls:/vehicle/1/rpc.OSRVMDirectionControl, requestId: 1f1a0412-eba3-605c-bc7f-fd72e8f8f7c6, source: cls:/com.patac.hmi.settings//rpc.response
08-25 12:55:24.250  4112  4616 D VehicleRequestProcessorFactory: TRY TO GET PROCESSOR: cls:/vehicle/1/rpc.OSRVMDirectionControl
08-25 12:55:24.250  4112  5146 I OSRVMDirectionRequestProcessor: processRequest: OSRVMDirectionRequestProcessor request, uri: cls:/vehicle/1/rpc.OSRVMDirectionControl
08-25 12:55:24.250  4112  5146 I OSRVMDirectionRequestProcessor: transStatusVal: 0
08-25 12:55:24.250  4112  5146 I OSRVMDirectionRequestProcessor: transStatusVal: 0
08-25 12:55:24.250  4112  5146 I OSRVMDirectionRequestProcessor: processRequest: Process Finish, uri: cls:/vehicle/1/rpc.OSRVMDirectionControl leftVal: 0 rightVal: 0
08-25 12:55:24.265  4112  5146 I VehicleSomeIpClient: SUCCESS: Software_Defined_Feature_Req_Service_3
08-25 12:55:24.266  4112  5146 D TimeResult: SystemClock: 3604807, ElapsedRealtimeMillis: 1892235
08-25 12:55:24.266  4112  5146 D TimeResult: mTimeMillis: 1787632011696, AgeMillis: 1712572
08-25 12:55:24.266  4112  5146 D [ClsLinkSDK-v0.0.33] BusClient: send: {id='1f1a0412-ebd0-60ba-8f77-f3ea29b5da50'}
08-25 12:55:24.268  4112  5146 D [ClsLinkSDK-v0.0.33] ClsLink: Request{id=1f1a0412-eba3-605c-bc7f-fd72e8f8f7c6} response sent
08-25 12:55:24.535  4112  5150 D SDV_CoreService: [SomeIpTopicReceiverManager]topic 2533279085461923
08-25 12:55:24.536  4112  5150 I SDV_CoreService: [ThirdRowLeftDoorSomeIpTopicMapper]SUCCESS: NOTIFY_BODY_INFORMATION_17
08-25 12:55:24.536  4112  5018 D SDV_CoreService: [RearLeftWindowTopicMapper]someIp sRlVCPWLSCurrSeltnVal: 2  rlWndAval: true  sRlWndCfg: true
08-25 12:55:24.536  4112  5019 D SDV_CoreService: [FrontLeftWindowTopicMapper]someIp sRlVCPWLSCurrSeltnVal: 2 drvWndAval: true drvWndCfg: true
08-25 12:55:24.536  4112  5119 D SDV_CoreService: [FrontRightWindowTopicMapper]someIp srrvcpwlsCurrSeltnVal: 2 psWndAval: true psWndCfg: true
08-25 12:55:24.536  4112  5150 D SDV_CoreService: [ThirdRowLeftDoorSomeIpTopicMapper]resp.getSRlVCPWLSCurrSeltnVal(): 2
08-25 12:55:24.536  4112  5150 I SDV_CoreService: [ThirdRowRightDoorSomeIpTopicMapper]SUCCESS: NOTIFY_BODY_INFORMATION_17
08-25 12:55:24.536  4112  5150 D SDV_CoreService: [ThirdRowRightDoorSomeIpTopicMapper]resp.getSRRVCPWLSCurrSeltnVal(): 2
08-25 12:55:24.536  4112  5038 D SDV_CoreService: [RearLeftDoorSignalTopicMapper]SUCCESS: NOTIFY_BODY_INFORMATION_17
08-25 12:55:24.536  4112  5039 D SDV_CoreService: [RearRightDoorSignalTopicMapper]SUCCESS: NOTIFY_BODY_INFORMATION_17
08-25 12:55:24.536  4112  5118 I SDV_CoreService: [RearRightWindowTopicMapper]someIp srrvcpwlsCurrSeltnVal： 2rrWndAval： truerrWndCfg： true
08-25 12:55:24.536  4112  5039 D SDV_CoreService: [RearRightDoorSignalTopicMapper]resp.srrvcpwlsCurrSeltnVal():2
08-25 12:55:24.536  4112  5038 D SDV_CoreService: [RearLeftDoorSignalTopicMapper]resp.getSRlVCPWLSCurrSeltnVal():2
08-25 12:55:24.837  4112  5150 D SDV_CoreService: [SomeIpTopicReceiverManager]topic 2533279085461923
08-25 12:55:24.837  4112  5018 D SDV_CoreService: [RearLeftWindowTopicMapper]someIp sRlVCPWLSCurrSeltnVal: 2  rlWndAval: true  sRlWndCfg: true
08-25 12:55:24.837  4112  5019 D SDV_CoreService: [FrontLeftWindowTopicMapper]someIp sRlVCPWLSCurrSeltnVal: 2 drvWndAval: true drvWndCfg: true
08-25 12:55:24.837  4112  5150 I SDV_CoreService: [ThirdRowLeftDoorSomeIpTopicMapper]SUCCESS: NOTIFY_BODY_INFORMATION_17
08-25 12:55:24.837  4112  5119 D SDV_CoreService: [FrontRightWindowTopicMapper]someIp srrvcpwlsCurrSeltnVal: 2 psWndAval: true psWndCfg: true
08-25 12:55:24.837  4112  5150 D SDV_CoreService: [ThirdRowLeftDoorSomeIpTopicMapper]resp.getSRlVCPWLSCurrSeltnVal(): 2
08-25 12:55:24.837  4112  5150 I SDV_CoreService: [ThirdRowRightDoorSomeIpTopicMapper]SUCCESS: NOTIFY_BODY_INFORMATION_17
08-25 12:55:24.837  4112  5150 D SDV_CoreService: [ThirdRowRightDoorSomeIpTopicM

... [截断: 原始结果 23,727 字符，已截取中间 8,727 字符] ...

Fdbck():-52
08-25 12:55:25.443  4112  5038 D SDV_CoreService: [RearLeftDoorSignalTopicMapper]SUCCESS: NOTIFY_BODY_INFORMATION_17
08-25 12:55:25.444  4112  5038 D SDV_CoreService: [RearLeftDoorSignalTopicMapper]resp.getSRlVCPWLSCurrSeltnVal():2
08-25 12:55:25.444  4112  5118 I SDV_CoreService: [RearRightWindowTopicMapper]someIp srrvcpwlsCurrSeltnVal： 2rrWndAval： truerrWndCfg： true
08-25 12:55:25.444  4112  5150 I OSRVMMapper: sendTopic: send OSRVM OSRVM.right
08-25 12:55:25.444  4112  5150 I OSRVMMapper: setRespondingFeatureValue: 0
08-25 12:55:25.444  4112  5150 I OSRVMMapper: HorizontalAngle: 0
08-25 12:55:25.444  4112  5150 I OSRVMMapper: setHorizontalAngle: 0.0
08-25 12:55:25.444  4112  5150 I OSRVMMapper: VerticalAngle: -52
08-25 12:55:25.444  4112  5150 I OSRVMMapper: setVerticalAngle: -5.2
08-25 12:55:25.444  4112  5039 D SDV_CoreService: [RearRightDoorSignalTopicMapper]SUCCESS: NOTIFY_BODY_INFORMATION_17
08-25 12:55:25.444  4112  5150 I OSRVMMapper: IsSupported: true
08-25 12:55:25.444  4112  5150 I OSRVMMapper: Right IsAllowed: false
08-25 12:55:25.445  4112  5039 D SDV_CoreService: [RearRightDoorSignalTopicMapper]resp.srrvcpwlsCurrSeltnVal():2
08-25 12:55:25.445  4112  5150 D SDV_CoreService: [SomeIpUtil]uri: cls:/vehicle/1/OSRVM.right#OSRVM
08-25 12:55:25.445  4112  5115 D TimeResult: SystemClock: 3605986, ElapsedRealtimeMillis: 1892235
08-25 12:55:25.445  4112  5115 D TimeResult: mTimeMillis: 1787632011696, AgeMillis: 1713751
08-25 12:55:25.445  4112  5115 D SDV_CoreService: [SomeIpUtil]publish event: uri: cls:/vehicle/1/OSRVM.right#OSRVM
08-25 12:55:25.445  4112  5115 D [ClsLinkSDK-v0.0.33] BusClient: send: {id='1f1a0412-f710-6e7f-8f77-f3ea29b5da50'}
08-25 12:55:25.741  4112  5150 D SDV_CoreService: [SomeIpTopicReceiverManager]topic 2533279085461923
08-25 12:55:25.742  4112  5150 I SDV_CoreService: [ThirdRowLeftDoorSomeIpTopicMapper]SUCCESS: NOTIFY_BODY_INFORMATION_17
08-25 12:55:25.742  4112  5119 D SDV_CoreService: [FrontRightWindowTopicMapper]someIp srrvcpwlsCurrSeltnVal: 2 psWndAval: true psWndCfg: true
08-25 12:55:25.742  4112  5019 D SDV_CoreService: [FrontLeftWindowTopicMapper]someIp sRlVCPWLSCurrSeltnVal: 2 drvWndAval: true drvWndCfg: true
08-25 12:55:25.742  4112  5150 D SDV_CoreService: [ThirdRowLeftDoorSomeIpTopicMapper]resp.getSRlVCPWLSCurrSeltnVal(): 2
08-25 12:55:25.742  4112  5150 I SDV_CoreService: [ThirdRowRightDoorSomeIpTopicMapper]SUCCESS: NOTIFY_BODY_INFORMATION_17
08-25 12:55:25.742  4112  5150 D SDV_CoreService: [ThirdRowRightDoorSomeIpTopicMapper]resp.getSRRVCPWLSCurrSeltnVal(): 2
08-25 12:55:25.742  4112  5118 I SDV_CoreService: [RearRightWindowTopicMapper]someIp srrvcpwlsCurrSeltnVal： 2rrWndAval： truerrWndCfg： true
08-25 12:55:25.742  4112  5038 D SDV_CoreService: [RearLeftDoorSignalTopicMapper]SUCCESS: NOTIFY_BODY_INFORMATION_17
08-25 12:55:25.742  4112  5038 D SDV_CoreService: [RearLeftDoorSignalTopicMapper]resp.getSRlVCPWLSCurrSeltnVal():2
08-25 12:55:25.742  4112  5039 D SDV_CoreService: [RearRightDoorSignalTopicMapper]SUCCESS: NOTIFY_BODY_INFORMATION_17
08-25 12:55:25.743  4112  5039 D SDV_CoreService: [RearRightDoorSignalTopicMapper]resp.srrvcpwlsCurrSeltnVal():2
08-25 12:55:25.744  4112  5018 D SDV_CoreService: [RearLeftWindowTopicMapper]someIp sRlVCPWLSCurrSeltnVal: 2  rlWndAval: true  sRlWndCfg: true
08-25 12:55:26.044  4112  5150 D SDV_CoreService: [SomeIpTopicReceiverManager]topic 2533279085461923
08-25 12:55:26.045  4112  5150 I SDV_CoreService: [ThirdRowLeftDoorSomeIpTopicMapper]SUCCESS: NOTIFY_BODY_INFORMATION_17
08-25 12:55:26.045  4112  5150 D SDV_CoreService: [ThirdRowLeftDoorSomeIpTopicMapper]resp.getSRlVCPWLSCurrSeltnVal(): 2
08-25 12:55:26.045  4112  5150 I SDV_CoreService: [ThirdRowRightDoorSomeIpTopicMapper]SUCCESS: NOTIFY_BODY_INFORMATION_17
08-25 12:55:26.045  4112  5150 D SDV_CoreService: [ThirdRowRightDoorSomeIpTopicMapper]resp.getSRRVCPWLSCurrSeltnVal(): 2
08-25 12:55:26.045  4112  5118 I SDV_CoreService: [RearRightWindowTopicMapper]someIp srrvcpwlsCurrSeltnVal： 2rrWndAval： truerrWndCfg： true
08-25 12:55:26.045  4112  5038 D SDV_CoreService: [RearLeftDoorSignalTopicMapper]SUCCESS: NOTIFY_BODY_INFORMATION_17
08-25 12:55:26.045  4112  5038 D SDV_CoreService: [RearLeftDoorSignalTopicMapper]resp.getSRlVCPWLSCurrSeltnVal():2
08-25 12:55:26.046  4112  5039 D SDV_CoreService: [RearRightDoorSignalTopicMapper]SUCCESS: NOTIFY_BODY_INFORMATION_17
08-25 12:55:26.046  4112  5039 D SDV_CoreService: [RearRightDoorSignalTopicMapper]resp.srrvcpwlsCurrSeltnVal():2
08-25 12:55:26.046  4112  5018 D SDV_CoreService: [RearLeftWindowTopicMapper]someIp sRlVCPWLSCurrSeltnVal: 2  rlWndAval: true  sRlWndCfg: true
08-25 12:55:26.046  4112  5119 D SDV_CoreService: [FrontRightWindowTopicMapper]someIp srrvcpwlsCurrSeltnVal: 2 psWndAval: true psWndCfg: true
08-25 12:55:26.047  4112  5019 D SDV_CoreService: [FrontLeftWindowTopicMapper]someIp sRlVCPWLSCurrSeltnVal: 2 drvWndAval: true drvWndCfg: true
08-25 12:55:26.284  4112  5150 E SDV_CoreService: [SomeIpTopicReceiverManager]not found receiver by topic 2533279085461934
08-25 12:55:26.284  4112  5150 D SDV_CoreService: [EnergySomeIpClient]SUCCESS: NOTIFY_MSG_2006
08-25 12:55:26.284  4112  5150 D EnergySomeIpClient: resp.getPwr12VbyHVSts():0,resp.getPwr12VbyHVRsp():1,resp.getHVBSOCBatSOC():54734,resp.getHVBSOCBatSOCInv():false
08-25 12:55:26.284  4112  5150 I EnergyStateTopicMapper: buildMessage RemainingEnergy: 24.24 EstimatedRange: 506.0 EstimatedBatteryRange: 150.0 TotalUsableEnergy: 29.439999 LifetimeEnergyUsed: 133.3 setLifetimeWallEnergyUsed: 0.0 PropulsionBatteryPower: -2000.0 RemainingTimeToTargetDischarge: 0 Sele
08-25 12:55:26.284  4112  5150 I EnergyStateTopicMapper: buildStateOfCharge Current: 83.517456 Displayed: 83.0 Target: 0
08-25 12:55:26.285  4112  5150 D SDV_CoreService: [SomeIpUtil]uri: cls:/energy.high_voltage.battery/1/battery#EnergyState
08-25 12:55:26.285  4112  5150 I EnergyStateTopicMapper: buildMessage RemainingEnergy: 24.24 EstimatedRange: 506.0 EstimatedBatteryRange: 150.0 TotalUsableEnergy: 29.439999 LifetimeEnergyUsed: 133.3 setLifetimeWallEnergyUsed: 0.0 PropulsionBatteryPower: -2000.0 RemainingTimeToTargetDischarge: 0 Sele
08-25 12:55:26.285  4112  5150 I EnergyStateTopicMapper: buildStateOfCharge Current: 83.517456 Displayed: 83.0 Target: 0
08-25 12:55:26.285  4112  5150 D SDV_CoreService: [SomeIpUtil]uri: cls:/energy.high_voltage.battery/1/battery#BatteryState
08-25 12:55:26.285  4112  5115 D TimeResult: SystemClock: 3606826, ElapsedRealtimeMillis: 1892235
08-25 12:55:26.285  4112  5115 D TimeResult: mTimeMillis: 1787632011696, AgeMillis: 1714591
08-25 12:55:26.285  4112  5115 D SDV_CoreService: [SomeIpUtil]publish event: uri: cls:/energy.high_voltage.battery/1/battery#EnergyState
08-25 12:55:26.286  4112  5115 D [ClsLinkSDK-v0.0.33] BusClient: send: {id='1f1a0412-ff13-6b00-8f77-f3ea29b5da50'}
08-25 12:55:26.287  4112  5115 D TimeResult: SystemClock: 3606828, ElapsedRealtimeMillis: 1892235
08-25 12:55:26.287  4112  5115 D TimeResult: mTimeMillis: 1787632011696, AgeMillis: 1714593
08-25 12:55:26.287  4112  5115 D SDV_CoreService: [SomeIpUtil]publish event: uri: cls:/energy.high_voltage.battery/1/battery#BatteryState
08-25 12:55:26.287  4112  5115 D [ClsLinkSDK-v0.0.33] BusClient: send: {id='1f1a0412-ff18-6921-8f77-f3ea29b5da50'}
08-25 12:55:26.345  4112  5150 D SDV_CoreService: [SomeIpTopicReceiverManager]topic 2533279085461923
08-25 12:55:26.345  4112  5150 I SDV_CoreService: [ThirdRowLeftDoorSomeIpTopicMapper]SUCCESS: NOTIFY_BODY_INFORMATION_17

---

[结果 2] 搜索结果: 共 30 条匹配，显示 6 条

L17084     08-25 12:55:22.434  5428  5428 I com.patac.hmi.user-UserAccount: CleaNewDriverHabitManager:dealDriverHabitResultEvent mRestoreDriverHabitFlow is null
    08-25 12:55:22.439  4515  5201 I com.patac.hmi.settings-BaseTopicHandler: registerEventListener
    08-25 12:55:22.439  4515  5201 I com.patac.hmi.settings-BaseTopicHandler: result is not null
>>> 08-25 12:55:22.439  4515  5201 I com.patac.hmi.settings-RearviewMirrorAdjustTopic: 32773--->makeResult: name: "OSRVM.left"
    08-25 12:55:22.439  4515  5201 I com.patac.hmi.settings-RearviewMirrorAdjustTopic: responding_feature: MF_TILT_MIRROR
    08-25 12:55:22.439  4515  5201 I com.patac.hmi.settings-RearviewMirrorAdjustTopic: horizontal_angle: -0.2
    08-25 12:55:22.439  4515  5201 I com.patac.hmi.settings-RearviewMirrorAdjustTopic: vertical_angle: -5.6

L17156     08-25 12:55:22.457  5428  5428 I com.patac.hmi.user-UserAccount: CalibrationDataSource:Calibration:MODEL=84
    08-25 12:55:22.457  5428  5428 I com.patac.hmi.user-UserAccount: UserFeatureManager:isModelTypeE22 isE22 = false
    08-25 12:55:22.457  5428  5428 I com.patac.hmi.user-UserAccount: CleaNewDriverHabitManager:dealDriverHabitResultEvent: seatResult is 0 leftMirrorResult is 0 rightMirrorResult is 0 mDriverMirrorFeedback 0 mPassengerMirrorFeedback 0
>>> 08-25 12:55:22.457  4515  5201 I com.patac.hmi.settings-RearviewMirrorAdjustTopic: 32773--->makeResult: name: "OSRVM.left"
    08-25 12:55:22.457  5428  5428 I com.patac.hmi.user-UserAccount: CleaNewDriverHabitManager:dealDriverHabitResultEvent mRestoreDriverHabitFlow is null
    08-25 12:55:22.457  4515  5201 I com.patac.hmi.settings-RearviewMirrorAdjustTopic: horizontal_angle: -0.2
    08-25 12:55:22.457  4515  5201 I com.patac.hmi.settings-RearviewMirrorAdjustTopic: vertical_angle: -5.6

L17356     08-25 12:55:22.729  4515  5201 I com.patac.hmi.settings-BaseTopicHandler: registerEventListener
    08-25 12:55:22.729  4477  5049 D ServiceBus: [Client] send to cls:/com.patac.hmi.user/; id= 1f1a0412-dd25-6291-8f77-f3ea29b5da50
    08-25 12:55:22.730  4515  5201 I com.patac.hmi.settings-BaseTopicHandler: result is not null
>>> 08-25 12:55:22.730  4515  5201 I com.patac.hmi.settings-RearviewMirrorAdjustTopic: 32773--->makeResult: name: "OSRVM.left"
    08-25 12:55:22.730  4515  5201 I com.patac.hmi.settings-RearviewMirrorAdjustTopic: horizontal_angle: -0.2
    08-25 12:55:22.730  4515  5201 I com.patac.hmi.settings-RearviewMirrorAdjustTopic: vertical_angle: -6.7
    08-25 12:55:22.730  4515  5201 I com.patac.hmi.settings-RearviewMirrorAdjustTopic: is_supported: true

L17387     08-25 12:55:22.734  4477  5049 D ServiceBus: [Client] send to cls:/com.patac.hmi.user/; id= 1f1a0412-dd2e-6ed2-8f77-f3ea29b5da50
    08-25 12:55:22.734  4515  5201 I com.patac.hmi.settings-BaseTopicHandler: registerEventListener
    08-25 12:55:22.734  4515  5201 I com.patac.hmi.settings-BaseTopicHandler: result is not null
>>> 08-25 12:55:22.735  4515  5201 I com.patac.hmi.settings-RightRearviewMirrorAvailableTopic: 32774--->makeResult: name: "OSRVM.right"
    08-25 12:55:22.735  4515  5201 I com.patac.hmi.settings-RightRearviewMirrorAvailableTopic: vertical_angle: -5.2
    08-25 12:55:22.735  4515  5201 I com.patac.hmi.settings-RightRearviewMirrorAvailableTopic: is_supported: true
    08-25 12:55:22.735  5428  6558 D [ClsLinkSDK-v0.0.27] ClsLink: dispatchCloudEvent {id='1f1a0412-dd2e-6ed2-8f77-f3ea29b5da50'}; type=pub.v1

L17566     08-25 12:55:23.034  4515  5201 I com.patac.hmi.settings-BaseTopicHandler: registerEventListener
    08-25 12:55:23.034  4477  5049 D ServiceBus: [Client] send to cls:/com.patac.hmi.user/; id= 1f1a0412-e00d-6ca3-8f77-f3ea29b5da50
    08-25 12:55:23.034  4515  5201 I com.patac.hmi.settings-BaseTopicHandler: result is not null
>>> 08-25 12:55:23.034  4515  5201 I com.patac.hmi.settings-RearviewMirrorAdjustTopic: 32773--->makeResult: name: "OSRVM.left"
    08-25 12:55:23.034  4515  5201 I com.patac.hmi.settings-RearviewMirrorAdjustTopic: horizontal_angle: -0.2
    08-25 12:55:23.034  4515  5201 I com.patac.hmi.settings-RearviewMirrorAdjustTopic: vertical_angle: -7.8
    08-25 12:55:23.034  4515  5201 I com.patac.hmi.settings-RearviewMirrorAdjustTopic: is_supported: true

L17749     08-25 12:55:23.336  4515  5201 I com.patac.hmi.settings-BaseTopicHandler: registerEventListener
    08-25 12:55:23.336  4515  5201 I com.patac.hmi.settings-BaseTopicHandler: result is not null
    08-25 12:55:23.336  2425  2490 D PatacOdiPropService: DYN updated: [213, 3, 0, 0, 0]
>>> 08-25 12:55:23.337  4515  5201 I com.patac.hmi.settings-RearviewMirrorAdjustTopic: 32773--->makeResult: name: "OSRVM.left"
    08-25 12:55:23.337  4515  5201 I com.patac.hmi.settings-RearviewMirrorAdjustTopic: horizontal_angle: -0.2
    08-25 12:55:23.337  4515  5201 I com.patac.hmi.settings-RearviewMirrorAdjustTopic: vertical_angle: -8.5
    08-25 12:55:23.337  4515  5201 I com.patac.hmi.settings-RearviewMirrorAdjustTopic: is_supported: true

⚠️ 搜索结果高度重复: 共 30 条匹配中，有 30 条内容相同 ('')。以上仅展示 6 条代表性结果。

---

## 第 4 轮 — LLM 响应

重要发现！出现了 `RearviewMirrorAdjustTopic`（设置侧后视镜调节 Topic）和 `CleaNewDriverHabitManager`（驾驶员习惯管理，即记忆功能）。关键线索：

- `RearviewMirrorAdjustTopic` 中 `responding_feature: MF_TILT_MIRROR`，`horizontal_angle: -0.2`，`vertical_angle: -5.6` —— 这是设置侧收到的后视镜角度
- `CleaNewDriverHabitManager:dealDriverHabitResultEvent` 处理驾驶员习惯结果，`leftMirrorResult is 0 rightMirrorResult is 0` —— 这是记忆恢复流程

我需要深入理解 `CleaNewDriverHabitManager`（记忆管理）和 `RearviewMirrorAdjustTopic` 的完整逻辑。让我搜索记忆保存/恢复相关的日志。



---

## 第 4 轮 — 工具执行结果

[结果 1] 搜索结果: 共 40 条匹配，显示 13 条

L17072     08-25 12:55:22.433  5428  5743 I com.patac.hmi.user-UserAccount: LeftMirrorFeatureHandle:result is not null
    08-25 12:55:22.433  5428  5743 I com.patac.hmi.user-UserAccount: LeftMirrorFeatureHandle:dealDataChange data feature is 2
    08-25 12:55:22.433  5428  5743 I com.patac.hmi.user-UserAccount: SomeIpModule:dealLeftMirrorFeatureChange 左后视镜反馈值 = 2
>>> 08-25 12:55:22.433  5428  5743 I com.patac.hmi.user-UserAccount: DriverHabitMessageHandle:dealDriverMirrorFeedbackEvent 主驾后视镜反馈 is 2
    08-25 12:55:22.434  5428  5743 I com.patac.hmi.user-UserAccount: SystemInfoRepository:sendSystemEvent type is 4 id is  4202
    08-25 12:55:22.434  5428  5428 I com.patac.hmi.user-UserAccount: UserApplicationManager:get system event 4202
    08-25 12:55:22.434  5428  5428 I com.patac.hmi.user-UserAccount: CleaNewDriverHabitManager:dealCustomEvent CLEA2_DRIVER_HABIT_RESULT_EVENT

L17080     08-25 12:55:22.434   732   732 I Calibrationd: [532501538040]CalibrationUsageLog.cpp::logUsage(34): Calibration Requested: com.patac.hmi.user: GMModel: ENUMERATION: [Module]GMModel: ENUMERATION: 84
    08-25 12:55:22.434  5428  5428 I com.patac.hmi.user-UserAccount: CalibrationDataSource:Calibration:MODEL=84
    08-25 12:55:22.434  5428  5428 I com.patac.hmi.user-UserAccount: UserFeatureManager:isModelTypeE22 isE22 = false
>>> 08-25 12:55:22.434  5428  5428 I com.patac.hmi.user-UserAccount: CleaNewDriverHabitManager:dealDriverHabitResultEvent: seatResult is 0 leftMirrorResult is 0 rightMirrorResult is 0 mDriverMirrorFeedback 2 mPassengerMirrorFeedback 0
    08-25 12:55:22.434  5428  5428 I com.patac.hmi.user-UserAccount: CleaNewDriverHabitManager:dealDriverHabitResultEvent mRestoreDriverHabitFlow is null
    08-25 12:55:22.439  4515  5201 I com.patac.hmi.settings-BaseTopicHandler: registerEventListener
    08-25 12:55:22.439  4515  5201 I com.patac.hmi.settings-BaseTopicHandler: result is not null

L17145     08-25 12:55:22.456  5428  5743 I com.patac.hmi.user-UserAccount: LeftMirrorFeatureHandle:result is not null
    08-25 12:55:22.456  5428  5743 I com.patac.hmi.user-UserAccount: LeftMirrorFeatureHandle:dealDataChange data feature is 0
    08-25 12:55:22.456  5428  5743 I com.patac.hmi.user-UserAccount: SomeIpModule:dealLeftMirrorFeatureChange 左后视镜反馈值 = 0
>>> 08-25 12:55:22.456  5428  5743 I com.patac.hmi.user-UserAccount: DriverHabitMessageHandle:dealDriverMirrorFeedbackEvent 主驾后视镜反馈 is 0
    08-25 12:55:22.456  4515  5201 I com.patac.hmi.settings-BaseTopicHandler: registerEventListener
    08-25 12:55:22.456  5428  5743 I com.patac.hmi.user-UserAccount: SystemInfoRepository:sendSystemEvent type is 4 id is  4202
    08-25 12:55:22.456  5428  5428 I com.patac.hmi.user-UserAccount: UserApplicationManager:get system event 4202

L17155     08-25 12:55:22.456   732   732 I Calibrationd: [532501538040]CalibrationUsageLog.cpp::logUsage(34): Calibration Requested: com.patac.hmi.user: GMModel: ENUMERATION: [Module]GMModel: ENUMERATION: 84
    08-25 12:55:22.457  5428  5428 I com.patac.hmi.user-UserAccount: CalibrationDataSource:Calibration:MODEL=84
    08-25 12:55:22.457  5428  5428 I com.patac.hmi.user-UserAccount: UserFeatureManager:isModelTypeE22 isE22 = false
>>> 08-25 12:55:22.457  5428  5428 I com.patac.hmi.user-UserAccount: CleaNewDriverHabitManager:dealDriverHabitResultEvent: seatResult is 0 leftMirrorResult is 0 rightMirrorResult is 0 mDriverMirrorFeedback 0 mPassengerMirrorFeedback 0
    08-25 12:55:22.457  4515  5201 I com.patac.hmi.settings-RearviewMirrorAdjustTopic: 32773--->makeResult: name: "OSRVM.left"
    08-25 12:55:22.457  5428  5428 I com.patac.hmi.user-UserAccount: CleaNewDriverHabitManager:dealDriverHabitResultEvent mRestoreDriverHabitFlow is null
    08-25 12:55:22.457  4515  5201 I com.patac.hmi.settings-RearviewMirrorAdjustTopic: horizontal_angle: -0.2

L17170     08-25 12:55:22.475  1371  1443 D GMVHAL  : setPropFromVehicle Property: VehicleProperty::HW_KEY_INPUT AreaID: 16777216 Status: 0 int32Values: 0 25 0 
    08-25 12:55:22.477  2150  2234 D CAR.INPUT: hal event code: 25, action: 0, display: 0, number of indents: 1
    08-25 12:55:22.477  5428  5704 I com.patac.hmi.user-UserAccount: CarDataSource:left mirror position:-5.9 -0.2 0.0 
>>> 08-25 12:55:22.477  5428  5704 I com.patac.hmi.user-UserAccount: DriverHabitMessageHandle:sendDriverHabitEvent afterCheck
    08-25 12:55:22.477  5428  5704 I com.patac.hmi.user-UserAccount: SystemInfoRepository:sendSystemEvent type is 4 id is  4201
    08-25 12:55:22.477  5428  5428 I com.patac.hmi.user-UserAccount: UserApplicationManager:get system event 4201
    08-25 12:55:22.477  5428  5428 I com.patac.hmi.user-UserAccount: CleaNewDriverHabitManager:dealCustomEvent CLEA_DRIVER_HABIT_DATA_EVENT

L17214     08-25 12:55:22.579  4515  4515 D HardKeyInterceptorManager: dispatch keyEventKeyEvent { action=ACTION_DOWN, keyCode=KEYCODE_VOLUME_DOWN, scanCode=0, metaState=0, flags=0x0, repeatCount=8, eventTime=2369895000000, downTime=2369895000000, deviceId=0, source=0x101, displayId=0 } on callback com.patac.h
    08-25 12:55:22.579  4515  4515 D com.patac.hmi.settings-SteeringWheelHardKeyUtil: processSWCOperation keyEvent = KeyEvent { action=ACTION_DOWN, keyCode=KEYCODE_VOLUME_DOWN, scanCode=0, metaState=0, flags=0x0, repeatCount=8, eventTime=2369895000000, downTime=2369895000000, deviceId=0, source=0x101, d
    08-25 12:55:22.580  5428  5704 I com.patac.hmi.user-UserAccount: CarDataSource:left mirror position:-6.3 -0.2 0.0 
>>> 08-25 12:55:22.580  5428  5704 I com.patac.hmi.user-UserAccount: DriverHabitMessageHandle:sendDriverHabitEvent afterCheck
    08-25 12:55:22.580  5428  5704 I com.patac.hmi.user-UserAccount: SystemInfoRepository:sendSystemEvent type is 4 id is  4201
    08-25 12:55:22.581  5428  5704 I com.patac.hmi.user-UserAccount: CarDataSource:right mirror position:-5.2000003 0.0 0.0 
    08-25 12:55:22.581  5428  5428 I com.patac.hmi.user-UserAccount: UserApplicationManager:get system event 4201

L17221     08-25 12:55:22.581  5428  5704 I com.patac.hmi.user-UserAccount: DriverHabitMessageHandle:sendDriverHabitEvent afterCheck
    08-25 12:55:22.581  5428  5428 I com.patac.hmi.user-UserAccount: CleaNewDriverHabitManager:dealCustomEvent CLEA_DRIVER_HABIT_DATA_EVENT
    08-25 12:55:22.581  5428  5704 I com.patac.hmi.user-UserAccount: SystemInfoRepository:sendSystemEvent type is 4 id is  4201
>>> 08-25 12:55:22.581  5428  5428 I com.patac.hmi.user-UserAccount: DriverHabitInfoUnit:updateCurrentHabitInfo
    08-25 12:55:22.581  5428  5428 I com.patac.hmi.user-UserAccount: UserFeatureManager:isMcuEnableDriverHabit mIsMcuEnableDriverHabit = true
    08-25 12:55:22.581  5428  5428 I com.patac.hmi.user-UserAccount: CleaNewDriverHabitManager:dealDriverHabitDataEvent mHabitRestoreResult is null
    08-25 12:55:22.581  5428  5428 I com.patac.hmi.user-UserAccount: UserApplicationManager:get system event 4201

L17228     08-25 12:55:22.581  5428  5428 I com.patac.hmi.user-UserAccount: CleaNewDriverHabitManager:dealCustomEvent CLEA_DRIVER_HABIT_DATA_EVENT
    08-25 12:55:22.581  5428  5428 I com.patac.hmi.user-UserAccount: DriverHabitInfoUnit:updateCurrentHabitInfo
    08-25 12:55:22.581  5428  5428 I com.patac.hmi.user-UserAccount: UserFeatureManager:isMcuEnableDriverHabit mIsMcuEnableDriverHabit = true
>>> 08-25 12:55:22.581  5428  5428 I com.patac.hmi.user-UserAccount: CleaNewDriverHabitManager:dealDriverHabitDataEvent mHabitRestoreResult is null
    08-25 12:55:22.583  5951  6023 D CPECallbackController: Dropping carPropertyEvent - propId: 291504647 areaId: 16777216  because getTimestamp(): 3603139639816 < nextUpdateTimeNanos: 3603339639816
    08-25 12:55:22.595  2003  2200 D CarPropertyManager: getProperty, propertyId: 0x21410109, areaId: 0x1000000
    08-25 12:55:22.596  1371  1433 D GMVHAL  : vhal_get Property: VendorProperty::LOCAL_TIME AreaID: 16777216 Status: 0 int32Values: 2026 8 25 12 55 21 

L17284     08-25 12:55:22.685  5951  6023 D CPECallbackController: Dropping carPropertyEvent - propId: 291504647 areaId: 16777216  because getTimestamp(): 3603239639816 < nextUpdateTimeNanos: 3603339639816
    08-25 12:55:22.687  1371  1476 D GMVHAL  : setPropFromVehicle Property: PatacProperty::MIRROR_POSITION_STATUS AreaID: 1 Status: 0 floatValues: -6.7 -0.2 0 
    08-25 12:55:22.688  5428  5704 I com.patac.hmi.user-UserAccount: CarDataSource:left mirror position:-6.7000003 -0.2 0.0 
>>> 08-25 12:55:22.688  5428  5704 I com.patac.hmi.user-UserAccount: DriverHabitMessageHandle:sendDriverHabitEvent afterCheck
    08-25 12:55:22.688  5428  5704 I com.patac.hmi.user-UserAccount: SystemInfoRepository:sendSystemEvent type is 4 id is  4201
    08-25 12:55:22.688  5428  5428 I com.patac.hmi.user-UserAccount: UserApplicationManager:get system event 4201
    08-25 12:55:22.688  5428  5428 I com.patac.hmi.user-UserAccount: CleaNewDriverHabitManager:dealCustomEvent CLEA_DRIVER_HABIT_DATA_EVENT

L17366     08-25 12:55:22.730  5428  5743 I com.patac.hmi.user-UserAccount: LeftMirrorFeatureHandle:dealDataChange data feature is 0
    08-25 12:55:22.730  4515  4515 I com.patac.hmi.settings-SettingItemValueSdvManager: 66<--someipHmi--disable-result---->Result{mBoolValue=true, mIntValue=0, mFloatValue=0.0, mState=0, mObject=null, mAvailable=1}
    08-25 12:55:22.730  5428  5743 I com.patac.hmi.user-UserAccount: SomeIpModule:dealLeftMirrorFeatureChange 左后视镜反馈值 = 0
>>> 08-25 12:55:22.730  5428  5743 I com.patac.hmi.user-UserAccount: DriverHabitMessageHandle:dealDriverMirrorFeedbackEvent 主驾后视镜反馈 is 0
    08-25 12:55:22.730  4515  4515 D com.patac.hmi.settings-DriveMirrorDialogManager: requestDisableValueFromSdvSomeIp Value-onNext: 66, disable = false, type = 19
    08-25 12:55:22.730  5428  5743 I com.patac.hmi.user-UserAccount: SystemInfoRepository:sendSystemEvent type is 4 id is  4202
    08-25 12:55:22.730  5428  5428 I com.patac.hmi.user-UserAccount: UserApplicationManager:get system event 4202

L17375     08-25 12:55:22.731   732   732 I Calibrationd: [532501538040]CalibrationUsageLog.cpp::logUsage(34): Calibration Requested: com.patac.hmi.user: GMModel: ENUMERATION: [Module]GMModel: ENUMERATION: 84
    08-25 12:55:22.732  5428  5428 I com.patac.hmi.user-UserAccount: CalibrationDataSource:Calibration:MODEL=84
    08-25 12:55:22.732  5428  5428 I com.patac.hmi.user-UserAccount: UserFeatureManager:isModelTypeE22 isE22 = false
>>> 08-25 12:55:22.732  5428  5428 I com.patac.hmi.user-UserAccount: CleaNewDriverHabitManager:dealDriverHabitResultEvent: seatResult is 0 leftMirrorResult is 0 rightMirrorResult is 0 mDriverMirrorFeedback 0 mPassengerMirrorFeedback 0
    08-25 12:55:22.732  5428  5428 I com.patac.hmi.user-UserAccount: CleaNewDriverHabitManager:dealDriverHabitResultEvent mRestoreDriverHabitFlow is null
    08-25 12:55:22.732  4112  5115 D TimeResult: SystemClock: 3603273, ElapsedRealtimeMillis: 1892235
    08-25 12:55:22.732  4112  5115 D TimeResult: mTimeMillis: 1787632011696, AgeMillis: 1711038

L17397     08-25 12:55:22.735  5428  5743 I com.patac.hmi.user-UserAccount: RightMirrorFeatureHandle:dealDataChange data feature is 0
    08-25 12:55:22.735  4515  4515 D com.patac.hmi.settings-DriveMirrorDialogManager: requestDisableValueFromSdvSomeIp Value-onNext: 67, disable = false, type = 19
    08-25 12:55:22.735  5428  5743 I com.patac.hmi.user-UserAccount: SomeIpModule:dealRightMirrorFeatureChange 右后视镜反馈值 = 0
>>> 08-25 12:55:22.735  5428  5743 I com.patac.hmi.user-UserAccount: DriverHabitMessageHandle:dealPassengerMirrorFeedbackEvent 副驾后视镜反馈 is 0
    08-25 12:55:22.735  5428  5743 I com.patac.hmi.user-UserAccount: SystemInfoRepository:sendSystemEvent type is 4 id is  4202
    08-25 12:55:22.735  5428  5428 I com.patac.hmi.user-UserAccount: UserApplicationManager:get system event 4202
    08-25 12:55:22.735  5428  5428 I com.patac.hmi.user-UserAccount: CleaNewDriverHabitManager:dealCustomEvent CLEA2_DRIVER_HABIT_RESULT_EVENT

L17405     08-25 12:55:22.735   732   732 I Calibrationd: [532501538040]CalibrationUsageLog.cpp::logUsage(34): Calibration Requested: com.patac.hmi.user: GMModel: ENUMERATION: [Module]GMModel: ENUMERATION: 84
    08-25 12:55:22.736  5428  5428 I com.patac.hmi.user-UserAccount: CalibrationDataSource:Calibration:MODEL=84
    08-25 12:55:22.736  5428  5428 I com.patac.hmi.user-UserAccount: UserFeatureManager:isModelTypeE22 isE22 = false
>>> 08-25 12:55:22.736  5428  5428 I com.patac.hmi.user-UserAccount: CleaNewDriverHabitManager:dealDriverHabitResultEvent: seatResult is 0 leftMirrorResult is 0 rightMirrorResult is 0 mDriverMirrorFeedback 0 mPassengerMirrorFeedback 0
    08-25 12:55:22.736  5428  5428 I com.patac.hmi.user-UserAccount: CleaNewDriverHabitManager:dealDriverHabitResultEvent mRestoreDriverHabitFlow is null
    08-25 12:55:22.740  1371  1476 D GMVHAL  : setPropFromVehicle Property: VendorProperty::LOCAL_TIME AreaID: 16777216 Status: 0 int32Values: 2026 8 25 12 55 22 
    08-25 12:55:22.740  1371  1476 D GMVHAL  : setPropFromVehicle Property: VendorProperty::UTC AreaID: 16777216 Status: 0 int32Values: 2026 8 25 4 55 22 

⚠️ 搜索结果高度重复: 共 40 条匹配中，有 30 条内容相同 ('')。以上仅展示 13 条代表性结果。

---

[结果 2] 搜索结果: 共 40 条匹配，显示 15 条

L17085     08-25 12:55:22.439  4515  5201 I com.patac.hmi.settings-BaseTopicHandler: registerEventListener
    08-25 12:55:22.439  4515  5201 I com.patac.hmi.settings-BaseTopicHandler: result is not null
    08-25 12:55:22.439  4515  5201 I com.patac.hmi.settings-RearviewMirrorAdjustTopic: 32773--->makeResult: name: "OSRVM.left"
>>> 08-25 12:55:22.439  4515  5201 I com.patac.hmi.settings-RearviewMirrorAdjustTopic: responding_feature: MF_TILT_MIRROR
    08-25 12:55:22.439  4515  5201 I com.patac.hmi.settings-RearviewMirrorAdjustTopic: horizontal_angle: -0.2
    08-25 12:55:22.439  4515  5201 I com.patac.hmi.settings-RearviewMirrorAdjustTopic: vertical_angle: -5.6
    08-25 12:55:22.439  4515  5201 I com.patac.hmi.settings-RearviewMirrorAdjustTopic: is_supported: true

L22143     08-25 12:55:30.602  5428  5743 I com.patac.hmi.user-UserAccount: SystemInfoRepository:sendSystemEvent type is 4 id is  4202
    08-25 12:55:30.602  4515  5201 I com.patac.hmi.settings-RightRearviewMirrorAvailableTopic: 32774--->makeResult: name: "OSRVM.right"
    08-25 12:55:30.602  5428  5428 I com.patac.hmi.user-UserAccount: UserApplicationManager:get system event 4202
>>> 08-25 12:55:30.602  4515  5201 I com.patac.hmi.settings-RightRearviewMirrorAvailableTopic: responding_feature: MF_TILT_MIRROR
    08-25 12:55:30.602  4515  5201 I com.patac.hmi.settings-RightRearviewMirrorAvailableTopic: vertical_angle: -5.2
    08-25 12:55:30.602  4515  5201 I com.patac.hmi.settings-RightRearviewMirrorAvailableTopic: is_supported: true
    08-25 12:55:30.602  4515  5201 I com.patac.hmi.settings-RightRearviewMirrorAvailableTopic: , cacheData = Result{mBoolValue=true, mIntValue=0, mFloatValue=0.0, mState=0, mObject=null, mAvailable=1}

L22593     08-25 12:55:31.481  4515  5201 I com.patac.hmi.settings-BaseTopicHandler: result is not null
    08-25 12:55:31.481  5428  7822 D [ClsLinkSDK-v0.0.27] ClsLink: dispatchCloudEvent {id='1f1a0413-3092-697b-8f77-f3ea29b5da50'}; type=pub.v1
    08-25 12:55:31.481  4515  5201 I com.patac.hmi.settings-RightRearviewMirrorAvailableTopic: 32774--->makeResult: name: "OSRVM.right"
>>> 08-25 12:55:31.481  4515  5201 I com.patac.hmi.settings-RightRearviewMirrorAvailableTopic: responding_feature: MF_TILT_MIRROR
    08-25 12:55:31.481  4515  5201 I com.patac.hmi.settings-RightRearviewMirrorAvailableTopic: horizontal_angle: 0.1
    08-25 12:55:31.481  4515  5201 I com.patac.hmi.settings-RightRearviewMirrorAvailableTopic: vertical_angle: -5.2
    08-25 12:55:31.481  4515  5201 I com.patac.hmi.settings-RightRearviewMirrorAvailableTopic: is_supported: true

L22878     08-25 12:55:32.082  5428  5743 I com.patac.hmi.user-UserAccount: DriverHabitMessageHandle:dealPassengerMirrorFeedbackEvent 副驾后视镜反馈 is 2
    08-25 12:55:32.082  5428  5743 I com.patac.hmi.user-UserAccount: SystemInfoRepository:sendSystemEvent type is 4 id is  4202
    08-25 12:55:32.082  4515  5201 I com.patac.hmi.settings-RightRearviewMirrorAvailableTopic: 32774--->makeResult: name: "OSRVM.right"
>>> 08-25 12:55:32.082  4515  5201 I com.patac.hmi.settings-RightRearviewMirrorAvailableTopic: responding_feature: MF_TILT_MIRROR
    08-25 12:55:32.082  4515  5201 I com.patac.hmi.settings-RightRearviewMirrorAvailableTopic: vertical_angle: -5.2
    08-25 12:55:32.082  4515  5201 I com.patac.hmi.settings-RightRearviewMirrorAvailableTopic: is_supported: true
    08-25 12:55:32.082  4515  5201 I com.patac.hmi.settings-RightRearviewMirrorAvailableTopic: , cacheData = Result{mBoolValue=true, mIntValue=0, mFloatValue=0.0, mState=0, mObject=null, mAvailable=1}

L23248     08-25 12:55:32.988  4515  5201 I com.patac.hmi.settings-RightRearviewMirrorAvailableTopic: 32774--->makeResult: name: "OSRVM.right"
    08-25 12:55:32.988  5428  5428 I com.patac.hmi.user-UserAccount: UserApplicationManager:get system event 4202
    08-25 12:55:32.988  5428  5428 I com.patac.hmi.user-UserAccount: CleaNewDriverHabitManager:dealCustomEvent CLEA2_DRIVER_HABIT_RESULT_EVENT
>>> 08-25 12:55:32.988  4515  5201 I com.patac.hmi.settings-RightRearviewMirrorAvailableTopic: responding_feature: MF_TILT_MIRROR
    08-25 12:55:32.988  5428  5428 I com.patac.hmi.user-UserAccount: UserFeatureManager:isMcuEnableDriverHabit mIsMcuEnableDriverHabit = true
    08-25 12:55:32.988  4515  5201 I com.patac.hmi.settings-RightRearviewMirrorAvailableTopic: horizontal_angle: 0.1
    08-25 12:55:32.988  4515  5201 I com.patac.hmi.settings-RightRearviewMirrorAvailableTopic: vertical_angle: -5.2

L23390     08-25 12:55:33.288  4515  5201 I com.patac.hmi.settings-BaseTopicHandler: registerEventListener
    08-25 12:55:33.288  4515  5201 I com.patac.hmi.settings-BaseTopicHandler: result is not null
    08-25 12:55:33.288  4515  5201 I com.patac.hmi.settings-RightRearviewMirrorAvailableTopic: 32774--->makeResult: name: "OSRVM.right"
>>> 08-25 12:55:33.288  4515  5201 I com.patac.hmi.settings-RightRearviewMirrorAvailableTopic: responding_feature: MF_TILT_MIRROR
    08-25 12:55:33.288  4515  5201 I com.patac.hmi.settings-RightRearviewMirrorAvailableTopic: vertical_angle: -5.2
    08-25 12:55:33.288  4515  5201 I com.patac.hmi.settings-RightRearviewMirrorAvailableTopic: is_supported: true
    08-25 12:55:33.288  4515  5201 I com.patac.hmi.settings-RightRearviewMirrorAvailableTopic: , cacheData = Result{mBoolValue=true, mIntValue=0, mFloatValue=0.0, mState=0, mObject=null, mAvailable=1}

L69463     08-25 12:56:33.932  4515  5201 I com.patac.hmi.settings-BaseTopicHandler: registerEventListener
    08-25 12:56:33.933  4515  5201 I com.patac.hmi.settings-BaseTopicHandler: result is not null
    08-25 12:56:33.934  4515  5201 I com.patac.hmi.settings-RightRearviewMirrorAvailableTopic: 32774--->makeResult: name: "OSRVM.right"
>>> 08-25 12:56:33.934  4515  5201 I com.patac.hmi.settings-RightRearviewMirrorAvailableTopic: responding_feature: MF_TILT_MIRROR
    08-25 12:56:33.934  4515  5201 I com.patac.hmi.settings-RightRearviewMirrorAvailableTopic: horizontal_angle: 0.3
    08-25 12:56:33.934  4515  5201 I com.patac.hmi.settings-RightRearviewMirrorAvailableTopic: vertical_angle: 4.9
    08-25 12:56:33.934  4515  5201 I com.patac.hmi.settings-RightRearviewMirrorAvailableTopic: is_allowed: true

L69609     08-25 12:56:34.204  5428  5428 I com.patac.hmi.user-UserAccount: CleaNewDriverHabitManager:dealCustomEvent CLEA2_DRIVER_HABIT_RESULT_EVENT
    08-25 12:56:34.205  5428  5428 I com.patac.hmi.user-UserAccount: UserFeatureManager:isMcuEnableDriverHabit mIsMcuEnableDriverHabit = true
    08-25 12:56:34.205  4515  5201 I com.patac.hmi.settings-RightRearviewMirrorAvailableTopic: 32774--->makeResult: name: "OSRVM.right"
>>> 08-25 12:56:34.205  4515  5201 I com.patac.hmi.settings-RightRearviewMirrorAvailableTopic: responding_feature: MF_TILT_MIRROR
    08-25 12:56:34.205  4515  5201 I com.patac.hmi.settings-RightRearviewMirrorAvailableTopic: horizontal_angle: 0.1
    08-25 12:56:34.205  4515  5201 I com.patac.hmi.settings-RightRearviewMirrorAvailableTopic: vertical_angle: 4.9
    08-25 12:56:34.205   732   732 I Calibrationd: [532501538040]CalibrationUsageLog.cpp::logUsage(34): Calibration Requested: com.patac.hmi.user: GMModel: ENUMERATION: [Module]GMModel: ENUMERATION: 84

L69694     08-25 12:56:34.234  4515  5201 I com.patac.hmi.settings-BaseTopicHandler: registerEventListener
    08-25 12:56:34.234  4515  5201 I com.patac.hmi.settings-BaseTopicHandler: result is not null
    08-25 12:56:34.234  4515  5201 I com.patac.hmi.settings-RightRearviewMirrorAvailableTopic: 32774--->makeResult: name: "OSRVM.right"
>>> 08-25 12:56:34.234  4515  5201 I com.patac.hmi.settings-RightRearviewMirrorAvailableTopic: responding_feature: MF_TILT_MIRROR
    08-25 12:56:34.234  4515  5201 I com.patac.hmi.settings-RightRearviewMirrorAvailableTopic: horizontal_angle: 0.1
    08-25 12:56:34.234  4515  5201 I com.patac.hmi.settings-RightRearviewMirrorAvailableTopic: vertical_angle: 4.9
    08-25 12:56:34.234  4515  5201 I com.patac.hmi.settings-RightRearviewMirrorAvailableTopic: is_supported: true

L70003     08-25 12:56:34.504  5428  5743 I com.patac.hmi.user-UserAccount: DriverHabitMessageHandle:dealPassengerMirrorFeedbackEvent 副驾后视镜反馈 is 2
    08-25 12:56:34.504  5428  5743 I com.patac.hmi.user-UserAccount: SystemInfoRepository:sendSystemEvent type is 4 id is  4202
    08-25 12:56:34.504  4515  5201 I com.patac.hmi.settings-RightRearviewMirrorAvailableTopic: 32774--->makeResult: name: "OSRVM.right"
>>> 08-25 12:56:34.504  4515  5201 I com.patac.hmi.settings-RightRearviewMirrorAvailableTopic: responding_feature: MF_TILT_MIRROR
    08-25 12:56:34.504  4515  5201 I com.patac.hmi.settings-RightRearviewMirrorAvailableTopic: horizontal_angle: -0.1
    08-25 12:56:34.504  4515  5201 I com.patac.hmi.settings-RightRearviewMirrorAvailableTopic: vertical_angle: 4.4
    08-25 12:56:34.504  4515  5201 I com.patac.hmi.settings-RightRearviewMirrorAvailableTopic: is_supported: true

L70179     08-25 12:56:34.806  5428  5428 I com.patac.hmi.user-UserAccount: UserApplicationManager:get system event 4202
    08-25 12:56:34.806  4515  5201 I com.patac.hmi.settings-RightRearviewMirrorAvailableTopic: 32774--->makeResult: name: "OSRVM.right"
    08-25 12:56:34.806  5428  5428 I com.patac.hmi.user-UserAccount: CleaNewDriverHabitManager:dealCustomEvent CLEA2_DRIVER_HABIT_RESULT_EVENT
>>> 08-25 12:56:34.806  4515  5201 I com.patac.hmi.settings-RightRearviewMirrorAvailableTopic: responding_feature: MF_TILT_MIRROR
    08-25 12:56:34.806  4515  5201 I com.patac.hmi.settings-RightRearviewMirrorAvailableTopic: horizontal_angle: -0.1
    08-25 12:56:34.806  4515  5201 I com.patac.hmi.settings-RightRearviewMirrorAvailableTopic: vertical_angle: 3.3
    08-25 12:56:34.806  4515  5201 I com.patac.hmi.settings-RightRearviewMirrorAvailableTopic: is_supported: true

L70325     08-25 12:56:35.106  5428  5743 I com.patac.hmi.user-UserAccount: DriverHabitMessageHandle:dealPassengerMirrorFeedbackEvent 副驾后视镜反馈 is 2
    08-25 12:56:35.106  5428  5743 I com.patac.hmi.user-UserAccount: SystemInfoRepository:sendSystemEvent type is 4 id is  4202
    08-25 12:56:35.107  4515  5201 I com.patac.hmi.settings-RightRearviewMirrorAvailableTopic: 32774--->makeResult: name: "OSRVM.right"
>>> 08-25 12:56:35.107  4515  5201 I com.patac.hmi.settings-RightRearviewMirrorAvailableTopic: responding_feature: MF_TILT_MIRROR
    08-25 12:56:35.107  5428  5428 I com.patac.hmi.user-UserAccount: UserApplicationManager:get system event 4202
    08-25 12:56:35.107  4515  5201 I com.patac.hmi.settings-RightRearviewMirrorAvailableTopic: horizontal_angle: -0.1
    08-25 12:56:35.107  4515  5201 I com.patac.hmi.settings-RightRearviewMirrorAvailableTopic: vertical_angle: 2.5

L70515     08-25 12:56:35.414  5428  5428 I com.patac.hmi.user-UserAccount: CleaNewDriverHabitManager:dealDriverHabitResultEvent: seatResult is 0 leftMirrorResult is 0 rightMirrorResult is 0 mDriverMirrorFeedback 0 mPassengerMirrorFeedback 2
    08-25 12:56:35.414  5428  5428 I com.patac.hmi.user-UserAccount: CleaNewDriverHabitManager:dealDriverHabitResultEvent mRestoreDriverHabitFlow is null
    08-25 12:56:35.414  4515  5201 I com.patac.hmi.settings-RightRearviewMirrorAvailableTopic: 32774--->makeResult: name: "OSRVM.right"
>>> 08-25 12:56:35.414  4515  5201 I com.patac.hmi.settings-RightRearviewMirrorAvailableTopic: responding_feature: MF_TILT_MIRROR
    08-25 12:56:35.414  4515  5201 I com.patac.hmi.settings-RightRearviewMirrorAvailableTopic: horizontal_angle: -0.1
    08-25 12:56:35.414  4515  5201 I com.patac.hmi.settings-RightRearviewMirrorAvailableTopic: vertical_angle: 1.4
    08-25 12:56:35.414  4515  5201 I com.patac.hmi.settings-RightRearviewMirrorAvailableTopic: is_supported: true

L70662     08-25 12:56:35.711  5428  5743 I com.patac.hmi.user-UserAccount: SystemInfoRepository:sendSystemEvent type is 4 id is  4202
    08-25 12:56:35.712  4515  5201 I com.patac.hmi.settings-RightRearviewMirrorAvailableTopic: 32774--->makeResult: name: "OSRVM.right"
    08-25 12:56:35.712  5428  5428 I com.patac.hmi.user-UserAccount: UserApplicationManager:get system event 4202
>>> 08-25 12:56:35.712  4515  5201 I com.patac.hmi.settings-RightRearviewMirrorAvailableTopic: responding_feature: MF_TILT_MIRROR
    08-25 12:56:35.712  5428  5428 I com.patac.hmi.user-UserAccount: CleaNewDriverHabitManager:dealCustomEvent CLEA2_DRIVER_HABIT_RESULT_EVENT
    08-25 12:56:35.712  4515  5201 I com.patac.hmi.settings-RightRearviewMirrorAvailableTopic: horizontal_angle: -0.1
    08-25 12:56:35.712  5428  5428 I com.patac.hmi.user-UserAccount: UserFeatureManager:isMcuEnableDriverHabit mIsMcuEnableDriverHabit = true

L70819     08-25 12:56:36.015  5428  5743 I com.patac.hmi.user-UserAccount: RightMirrorFeatureHandle:dealDataChange data feature is 2
    08-25 12:56:36.015  5428  5743 I com.patac.hmi.user-UserAccount: SomeIpModule:dealRightMirrorFeatureChange 右后视镜反馈值 = 2
    08-25 12:56:36.015  4515  5201 I com.patac.hmi.settings-RightRearviewMirrorAvailableTopic: 32774--->makeResult: name: "OSRVM.right"
>>> 08-25 12:56:36.015  4515  5201 I com.patac.hmi.settings-RightRearviewMirrorAvailableTopic: responding_feature: MF_TILT_MIRROR
    08-25 12:56:36.015  5428  5743 I com.patac.hmi.user-UserAccount: DriverHabitMessageHandle:dealPassengerMirrorFeedbackEvent 副驾后视镜反馈 is 2
    08-25 12:56:36.015  4515  5201 I com.patac.hmi.settings-RightRearviewMirrorAvailableTopic: horizontal_angle: -0.1
    08-25 12:56:36.015  5428  5743 I com.patac.hmi.user-UserAccount: SystemInfoRepository:sendSystemEvent type is 4 id is  4202

⚠️ 搜索结果高度重复: 共 40 条匹配中，有 30 条内容相同 ('')。以上仅展示 15 条代表性结果。

---

## 第 5 轮 — LLM 响应

关键发现：`CleaNewDriverHabitManager` 是记忆管理核心，`dealDriverHabitResultEvent` 处理记忆恢复结果。`LeftMirrorFeatureHandle` 处理左后视镜特征，`dealLeftMirrorFeatureChange` 处理左后视镜特征变化。

我需要理解记忆保存和恢复的完整流程。关键问题是：用户设置下翻位置后，这个位置是否被保存到记忆（DriverHabit）中？挂 R 档时是否从记忆恢复？

让我搜索记忆保存相关的日志，以及 R 档触发下翻的日志。同时查看 CleaNewDriverHabitManager 的完整上下文。





---

## 第 5 轮 — 工具执行结果

[结果 1] 搜索结果: 共 40 条匹配，显示 15 条

L17069     08-25 12:55:22.433  4477  5049 D ServiceBus: [Client] send to cls:/com.patac.hmi.user/; id= 1f1a0412-da52-680f-8f77-f3ea29b5da50
    08-25 12:55:22.433  5428  6558 D [ClsLinkSDK-v0.0.27] ClsLink: dispatchCloudEvent {id='1f1a0412-da52-680f-8f77-f3ea29b5da50'}; type=pub.v1
    08-25 12:55:22.433   928  1562 I GMLoggerService|Archiver: Creating compressed file:  /data/gmlogger/10-main.log_2026_8_25_12_55_22.gz
>>> 08-25 12:55:22.433  5428  5743 I com.patac.hmi.user-UserAccount: LeftMirrorFeatureHandle:result is not null
    08-25 12:55:22.433  5428  5743 I com.patac.hmi.user-UserAccount: LeftMirrorFeatureHandle:dealDataChange data feature is 2
    08-25 12:55:22.433  5428  5743 I com.patac.hmi.user-UserAccount: SomeIpModule:dealLeftMirrorFeatureChange 左后视镜反馈值 = 2
    08-25 12:55:22.433  5428  5743 I com.patac.hmi.user-UserAccount: DriverHabitMessageHandle:dealDriverMirrorFeedbackEvent 主驾后视镜反馈 is 2

L17080     08-25 12:55:22.434   732   732 I Calibrationd: [532501538040]CalibrationUsageLog.cpp::logUsage(34): Calibration Requested: com.patac.hmi.user: GMModel: ENUMERATION: [Module]GMModel: ENUMERATION: 84
    08-25 12:55:22.434  5428  5428 I com.patac.hmi.user-UserAccount: CalibrationDataSource:Calibration:MODEL=84
    08-25 12:55:22.434  5428  5428 I com.patac.hmi.user-UserAccount: UserFeatureManager:isModelTypeE22 isE22 = false
>>> 08-25 12:55:22.434  5428  5428 I com.patac.hmi.user-UserAccount: CleaNewDriverHabitManager:dealDriverHabitResultEvent: seatResult is 0 leftMirrorResult is 0 rightMirrorResult is 0 mDriverMirrorFeedback 2 mPassengerMirrorFeedback 0
    08-25 12:55:22.434  5428  5428 I com.patac.hmi.user-UserAccount: CleaNewDriverHabitManager:dealDriverHabitResultEvent mRestoreDriverHabitFlow is null
    08-25 12:55:22.439  4515  5201 I com.patac.hmi.settings-BaseTopicHandler: registerEventListener
    08-25 12:55:22.439  4515  5201 I com.patac.hmi.settings-BaseTopicHandler: result is not null

L17142     08-25 12:55:22.455  4515  5408 D [ClsLinkSDK-v0.0.33] ClsLink: dispatchCloudEvent {id='1f1a0412-da88-6370-8f77-f3ea29b5da50'}; type=pub.v1
    08-25 12:55:22.455  4477  5049 D ServiceBus: [Client] send to cls:/com.patac.hmi.user/; id= 1f1a0412-da88-6370-8f77-f3ea29b5da50
    08-25 12:55:22.456  5428  6558 D [ClsLinkSDK-v0.0.27] ClsLink: dispatchCloudEvent {id='1f1a0412-da88-6370-8f77-f3ea29b5da50'}; type=pub.v1
>>> 08-25 12:55:22.456  5428  5743 I com.patac.hmi.user-UserAccount: LeftMirrorFeatureHandle:result is not null
    08-25 12:55:22.456  5428  5743 I com.patac.hmi.user-UserAccount: LeftMirrorFeatureHandle:dealDataChange data feature is 0
    08-25 12:55:22.456  5428  5743 I com.patac.hmi.user-UserAccount: SomeIpModule:dealLeftMirrorFeatureChange 左后视镜反馈值 = 0
    08-25 12:55:22.456  5428  5743 I com.patac.hmi.user-UserAccount: DriverHabitMessageHandle:dealDriverMirrorFeedbackEvent 主驾后视镜反馈 is 0

L17149     08-25 12:55:22.456  4515  5201 I com.patac.hmi.settings-BaseTopicHandler: registerEventListener
    08-25 12:55:22.456  5428  5743 I com.patac.hmi.user-UserAccount: SystemInfoRepository:sendSystemEvent type is 4 id is  4202
    08-25 12:55:22.456  5428  5428 I com.patac.hmi.user-UserAccount: UserApplicationManager:get system event 4202
>>> 08-25 12:55:22.456  5428  5428 I com.patac.hmi.user-UserAccount: CleaNewDriverHabitManager:dealCustomEvent CLEA2_DRIVER_HABIT_RESULT_EVENT
    08-25 12:55:22.456  5428  5428 I com.patac.hmi.user-UserAccount: UserFeatureManager:isMcuEnableDriverHabit mIsMcuEnableDriverHabit = true
    08-25 12:55:22.456  4515  5201 I com.patac.hmi.settings-BaseTopicHandler: result is not null
    08-25 12:55:22.456   732   732 I Calibrationd: [532501538040]CalibrationUsageLog.cpp::logUsage(34): Calibration Requested: com.patac.hmi.user: GMModel: ENUMERATION: [Module]GMModel: ENUMERATION: 84

L17157     08-25 12:55:22.457  5428  5428 I com.patac.hmi.user-UserAccount: UserFeatureManager:isModelTypeE22 isE22 = false
    08-25 12:55:22.457  5428  5428 I com.patac.hmi.user-UserAccount: CleaNewDriverHabitManager:dealDriverHabitResultEvent: seatResult is 0 leftMirrorResult is 0 rightMirrorResult is 0 mDriverMirrorFeedback 0 mPassengerMirrorFeedback 0
    08-25 12:55:22.457  4515  5201 I com.patac.hmi.settings-RearviewMirrorAdjustTopic: 32773--->makeResult: name: "OSRVM.left"
>>> 08-25 12:55:22.457  5428  5428 I com.patac.hmi.user-UserAccount: CleaNewDriverHabitManager:dealDriverHabitResultEvent mRestoreDriverHabitFlow is null
    08-25 12:55:22.457  4515  5201 I com.patac.hmi.settings-RearviewMirrorAdjustTopic: horizontal_angle: -0.2
    08-25 12:55:22.457  4515  5201 I com.patac.hmi.settings-RearviewMirrorAdjustTopic: vertical_angle: -5.6
    08-25 12:55:22.457  4515  5201 I com.patac.hmi.settings-RearviewMirrorAdjustTopic: is_supported: true

L17170     08-25 12:55:22.475  1371  1443 D GMVHAL  : setPropFromVehicle Property: VehicleProperty::HW_KEY_INPUT AreaID: 16777216 Status: 0 int32Values: 0 25 0 
    08-25 12:55:22.477  2150  2234 D CAR.INPUT: hal event code: 25, action: 0, display: 0, number of indents: 1
    08-25 12:55:22.477  5428  5704 I com.patac.hmi.user-UserAccount: CarDataSource:left mirror position:-5.9 -0.2 0.0 
>>> 08-25 12:55:22.477  5428  5704 I com.patac.hmi.user-UserAccount: DriverHabitMessageHandle:sendDriverHabitEvent afterCheck
    08-25 12:55:22.477  5428  5704 I com.patac.hmi.user-UserAccount: SystemInfoRepository:sendSystemEvent type is 4 id is  4201
    08-25 12:55:22.477  5428  5428 I com.patac.hmi.user-UserAccount: UserApplicationManager:get system event 4201
    08-25 12:55:22.477  5428  5428 I com.patac.hmi.user-UserAccount: CleaNewDriverHabitManager:dealCustomEvent CLEA_DRIVER_HABIT_DATA_EVENT

L17214     08-25 12:55:22.579  4515  4515 D HardKeyInterceptorManager: dispatch keyEventKeyEvent { action=ACTION_DOWN, keyCode=KEYCODE_VOLUME_DOWN, scanCode=0, metaState=0, flags=0x0, repeatCount=8, eventTime=2369895000000, downTime=2369895000000, deviceId=0, source=0x101, displayId=0 } on callback com.patac.h
    08-25 12:55:22.579  4515  4515 D com.patac.hmi.settings-SteeringWheelHardKeyUtil: processSWCOperation keyEvent = KeyEvent { action=ACTION_DOWN, keyCode=KEYCODE_VOLUME_DOWN, scanCode=0, metaState=0, flags=0x0, repeatCount=8, eventTime=2369895000000, downTime=2369895000000, deviceId=0, source=0x101, d
    08-25 12:55:22.580  5428  5704 I com.patac.hmi.user-UserAccount: CarDataSource:left mirror position:-6.3 -0.2 0.0 
>>> 08-25 12:55:22.580  5428  5704 I com.patac.hmi.user-UserAccount: DriverHabitMessageHandle:sendDriverHabitEvent afterCheck
    08-25 12:55:22.580  5428  5704 I com.patac.hmi.user-UserAccount: SystemInfoRepository:sendSystemEvent type is 4 id is  4201
    08-25 12:55:22.581  5428  5704 I com.patac.hmi.user-UserAccount: CarDataSource:right mirror position:-5.2000003 0.0 0.0 
    08-25 12:55:22.581  5428  5428 I com.patac.hmi.user-UserAccount: UserApplicationManager:get system event 4201

L17223     08-25 12:55:22.581  5428  5704 I com.patac.hmi.user-UserAccount: SystemInfoRepository:sendSystemEvent type is 4 id is  4201
    08-25 12:55:22.581  5428  5428 I com.patac.hmi.user-UserAccount: DriverHabitInfoUnit:updateCurrentHabitInfo
    08-25 12:55:22.581  5428  5428 I com.patac.hmi.user-UserAccount: UserFeatureManager:isMcuEnableDriverHabit mIsMcuEnableDriverHabit = true
>>> 08-25 12:55:22.581  5428  5428 I com.patac.hmi.user-UserAccount: CleaNewDriverHabitManager:dealDriverHabitDataEvent mHabitRestoreResult is null
    08-25 12:55:22.581  5428  5428 I com.patac.hmi.user-UserAccount: UserApplicationManager:get system event 4201
    08-25 12:55:22.581  5428  5428 I com.patac.hmi.user-UserAccount: CleaNewDriverHabitManager:dealCustomEvent CLEA_DRIVER_HABIT_DATA_EVENT
    08-25 12:55:22.581  5428  5428 I com.patac.hmi.user-UserAccount: DriverHabitInfoUnit:updateCurrentHabitInfo

L17284     08-25 12:55:22.685  5951  6023 D CPECallbackController: Dropping carPropertyEvent - propId: 291504647 areaId: 16777216  because getTimestamp(): 3603239639816 < nextUpdateTimeNanos: 3603339639816
    08-25 12:55:22.687  1371  1476 D GMVHAL  : setPropFromVehicle Property: PatacProperty::MIRROR_POSITION_STATUS AreaID: 1 Status: 0 floatValues: -6.7 -0.2 0 
    08-25 12:55:22.688  5428  5704 I com.patac.hmi.user-UserAccount: CarDataSource:left mirror position:-6.7000003 -0.2 0.0 
>>> 08-25 12:55:22.688  5428  5704 I com.patac.hmi.user-UserAccount: DriverHabitMessageHandle:sendDriverHabitEvent afterCheck
    08-25 12:55:22.688  5428  5704 I com.patac.hmi.user-UserAccount: SystemInfoRepository:sendSystemEvent type is 4 id is  4201
    08-25 12:55:22.688  5428  5428 I com.patac.hmi.user-UserAccount: UserApplicationManager:get system event 4201
    08-25 12:55:22.688  5428  5428 I com.patac.hmi.user-UserAccount: CleaNewDriverHabitManager:dealCustomEvent CLEA_DRIVER_HABIT_DATA_EVENT

L17362     08-25 12:55:22.730  4515  5201 I com.patac.hmi.settings-RearviewMirrorAdjustTopic: is_supported: true
    08-25 12:55:22.730  4515  5201 I com.patac.hmi.settings-RearviewMirrorAdjustTopic: , cacheData = Result{mBoolValue=true, mIntValue=0, mFloatValue=0.0, mState=0, mObject=null, mAvailable=1}
    08-25 12:55:22.730  5428  6558 D [ClsLinkSDK-v0.0.27] ClsLink: dispatchCloudEvent {id='1f1a0412-dd25-6291-8f77-f3ea29b5da50'}; type=pub.v1
>>> 08-25 12:55:22.730  5428  5743 I com.patac.hmi.user-UserAccount: LeftMirrorFeatureHandle:result is not null
    08-25 12:55:22.730  5428  5743 I com.patac.hmi.user-UserAccount: LeftMirrorFeatureHandle:dealDataChange data feature is 0
    08-25 12:55:22.730  4515  4515 I com.patac.hmi.settings-SettingItemValueSdvManager: 66<--someipHmi--disable-result---->Result{mBoolValue=true, mIntValue=0, mFloatValue=0.0, mState=0, mObject=null, mAvailable=1}
    08-25 12:55:22.730  5428  5743 I com.patac.hmi.user-UserAccount: SomeIpModule:dealLeftMirrorFeatureChange 左后视镜反馈值 = 0

L17370     08-25 12:55:22.730  4515  4515 D com.patac.hmi.settings-DriveMirrorDialogManager: requestDisableValueFromSdvSomeIp Value-onNext: 66, disable = false, type = 19
    08-25 12:55:22.730  5428  5743 I com.patac.hmi.user-UserAccount: SystemInfoRepository:sendSystemEvent type is 4 id is  4202
    08-25 12:55:22.730  5428  5428 I com.patac.hmi.user-UserAccount: UserApplicationManager:get system event 4202
>>> 08-25 12:55:22.730  5428  5428 I com.patac.hmi.user-UserAccount: CleaNewDriverHabitManager:dealCustomEvent CLEA2_DRIVER_HABIT_RESULT_EVENT
    08-25 12:55:22.730  5428  5428 I com.patac.hmi.user-UserAccount: UserFeatureManager:isMcuEnableDriverHabit mIsMcuEnableDriverHabit = true
    08-25 12:55:22.731   732   732 I Calibrationd: [532501538040]CalibrationUsageLog.cpp::logUsage(34): Calibration Requested: com.patac.hmi.user: GMModel: ENUMERATION: [Module]GMModel: ENUMERATION: 84
    08-25 12:55:22.732  5428  5428 I com.patac.hmi.user-UserAccount: CalibrationDataSource:Calibration:MODEL=84

L17392     08-25 12:55:22.735  4515  5201 I com.patac.hmi.settings-RightRearviewMirrorAvailableTopic: is_supported: true
    08-25 12:55:22.735  5428  6558 D [ClsLinkSDK-v0.0.27] ClsLink: dispatchCloudEvent {id='1f1a0412-dd2e-6ed2-8f77-f3ea29b5da50'}; type=pub.v1
    08-25 12:55:22.735  4515  5201 I com.patac.hmi.settings-RightRearviewMirrorAvailableTopic: , cacheData = Result{mBoolValue=true, mIntValue=0, mFloatValue=0.0, mState=0, mObject=null, mAvailable=1}
>>> 08-25 12:55:22.735  5428  5743 I com.patac.hmi.user-UserAccount: RightMirrorFeatureHandle:result is not null
    08-25 12:55:22.735  4515  4515 I com.patac.hmi.settings-SettingItemValueSdvManager: 67<--someipHmi--disable-result---->Result{mBoolValue=true, mIntValue=0, mFloatValue=0.0, mState=0, mObject=null, mAvailable=1}
    08-25 12:55:22.735  5428  5743 I com.patac.hmi.user-UserAccount: RightMirrorFeatureHandle:dealDataChange data feature is 0
    08-25 12:55:22.735  4515  4515 D com.patac.hmi.settings-DriveMirrorDialogManager: requestDisableValueFromSdvSomeIp Value-onNext: 67, disable = false, type = 19

L17400     08-25 12:55:22.735  5428  5743 I com.patac.hmi.user-UserAccount: DriverHabitMessageHandle:dealPassengerMirrorFeedbackEvent 副驾后视镜反馈 is 0
    08-25 12:55:22.735  5428  5743 I com.patac.hmi.user-UserAccount: SystemInfoRepository:sendSystemEvent type is 4 id is  4202
    08-25 12:55:22.735  5428  5428 I com.patac.hmi.user-UserAccount: UserApplicationManager:get system event 4202
>>> 08-25 12:55:22.735  5428  5428 I com.patac.hmi.user-UserAccount: CleaNewDriverHabitManager:dealCustomEvent CLEA2_DRIVER_HABIT_RESULT_EVENT
    08-25 12:55:22.735  5428  5428 I com.patac.hmi.user-UserAccount: UserFeatureManager:isMcuEnableDriverHabit mIsMcuEnableDriverHabit = true
    08-25 12:55:22.735   732   732 I Calibrationd: [532501538040]CalibrationUsageLog.cpp::logUsage(34): Calibration Requested: com.patac.hmi.user: GMModel: ENUMERATION: [Module]GMModel: ENUMERATION: 84
    08-25 12:55:22.736  5428  5428 I com.patac.hmi.user-UserAccount: CalibrationDataSource:Calibration:MODEL=84

L17430     08-25 12:55:22.804  1371  1476 D GMVHAL  : setPropFromVehicle Property: PatacProperty::MIRROR_POSITION_STATUS AreaID: 1 Status: 0 floatValues: -7.1 -0.2 0 
    08-25 12:55:22.804  1371  1476 D GMVHAL  : setPropFromVehicle Property: PatacProperty::FORWARD_LOOKING_LIGHT_LEVEL_EXTENDED AreaID: 16777216 Status: 0 int32Values: 36260 
    08-25 12:55:22.804  5428  5704 I com.patac.hmi.user-UserAccount: CarDataSource:left mirror position:-7.1 -0.2 0.0 
>>> 08-25 12:55:22.805  5428  5704 I com.patac.hmi.user-UserAccount: DriverHabitMessageHandle:sendDriverHabitEvent afterCheck
    08-25 12:55:22.805  5428  5704 I com.patac.hmi.user-UserAccount: SystemInfoRepository:sendSystemEvent type is 4 id is  4201
    08-25 12:55:22.805  5428  5428 I com.patac.hmi.user-UserAccount: UserApplicationManager:get system event 4201
    08-25 12:55:22.805  5428  5428 I com.patac.hmi.user-UserAccount: CleaNewDriverHabitManager:dealCustomEvent CLEA_DRIVER_HABIT_DATA_EVENT

L17472     08-25 12:55:22.911  1371  1476 D GMVHAL  : setPropFromVehicle Property: VehicleProperty::PERF_STEERING_ANGLE AreaID: 16777216 Status: 0 floatValues: 7.75 
    08-25 12:55:22.912  1371  1476 D GMVHAL  : setPropFromVehicle Property: PatacProperty::MIRROR_POSITION_STATUS AreaID: 1 Status: 0 floatValues: -7.4 -0.2 0 
    08-25 12:55:22.913  5428  5704 I com.patac.hmi.user-UserAccount: CarDataSource:left mirror position:-7.4 -0.2 0.0 
>>> 08-25 12:55:22.913  5428  5704 I com.patac.hmi.user-UserAccount: DriverHabitMessageHandle:sendDriverHabitEvent afterCheck
    08-25 12:55:22.914  5428  5704 I com.patac.hmi.user-UserAccount: SystemInfoRepository:sendSystemEvent type is 4 id is  4201
    08-25 12:55:22.914  5428  5428 I com.patac.hmi.user-UserAccount: UserApplicationManager:get system event 4201
    08-25 12:55:22.914  5428  5428 I com.patac.hmi.user-UserAccount: CleaNewDriverHabitManager:dealCustomEvent CLEA_DRIVER_HABIT_DATA_EVENT

⚠️ 搜索结果高度重复: 共 40 条匹配中，有 30 条内容相同 ('')。以上仅展示 15 条代表性结果。

---

[结果 2] 搜索结果: 共 30 条匹配，显示 15 条

L46294     08-25 12:56:06.962  4112  5113 I VehicleGearStateTopic: getVehicleGear: 1
    08-25 12:56:06.962  1996  4258 D TagLauncher: onVehicleMotionMovementStateChanged integer: 1 mResumed: false, mCurDeskMode: KANZI_MODE isKanziConnect: true
    08-25 12:56:06.962  4515  5189 D VehicleController: Receive: CarPropertyValue{mPropertyId=0x21401045, propertyName=0x21401045, mAreaId=0x1000000, mStatus=0, mTimestampNanos=3647500847356, mValue=1} from CarService
>>> 08-25 12:56:06.962  4112  5113 D SDV_CoreService: [SomeIpUtil]uri: cls:/propulsion.transmission/1/gear#VehicleGearState
    08-25 12:56:06.962  1996  4258 D VehicleController: com.patac.launcher.signal.PatacExtendPowerOffSignal$1@985bdbf onSignalChanged
    08-25 12:56:06.962  1996  4258 E PowertainController: onSignalChanged 
    08-25 12:56:06.962  4515  5189 D VehicleController: com.patac.hmi.adassettings.domain.repository.PowertainRepository$1@cc33bfc onSignalChanged

L46374     08-25 12:56:06.965  4515  5189 D CAR.L   : setGroupVolume, zoneid: 0, groupId: 0, index: 25, flags: 16777216
    08-25 12:56:06.966  4112  5115 D TimeResult: SystemClock: 3647507, ElapsedRealtimeMillis: 1892235
    08-25 12:56:06.966  4112  5115 D TimeResult: mTimeMillis: 1787632011696, AgeMillis: 1755272
>>> 08-25 12:56:06.966  4112  5115 D SDV_CoreService: [SomeIpUtil]publish event: uri: cls:/propulsion.transmission/1/gear#VehicleGearState
    08-25 12:56:06.966  4112  5115 D [ClsLinkSDK-v0.0.33] BusClient: send: {id='1f1a0414-8308-6275-8f77-f3ea29b5da50'}
    08-25 12:56:06.966  2150  2167 I CAR.AUDIO: getCallStateForZone : 0
    08-25 12:56:06.966  4477  5049 D ServiceBus: [Dispatcher] Received handleGenericMessage CloudEvent=CloudEvent{id='1f1a0414-8308-6275-8f77-f3ea29b5da50', source=cls:/propulsion.transmission/1/gear#VehicleGearState, type='pub.v1', datacontenttype='application/x-protobuf', dataschema=type.googleapis.co

L47012     08-25 12:56:07.081  4112  5150 D LightingSomeIpClient: resp.getTrnSwAct():0
    08-25 12:56:07.081  4112  5150 D LightingSomeIpClient: resp.getHazSwAtv():false
    08-25 12:56:07.081  4112  5150 I LampMapper: sendReverseTopic LampState: false
>>> 08-25 12:56:07.081  4112  5150 D SDV_CoreService: [SomeIpUtil]uri: cls:/body.lighting.exterior/1/lamp.reverse#Lamp
    08-25 12:56:07.081  4112  5150 D VehicleSomeIpClient: resp.getOtsdAmbtLtLvlStat():2
    08-25 12:56:07.081  4112  5150 D VehicleSomeIpClient: resp.getOtsdAmbtLtLvlStatV():0
    08-25 12:56:07.082  4112  5115 D TimeResult: SystemClock: 3647623, ElapsedRealtimeMillis: 1892235

L47698     08-25 12:56:07.665  4112  5113 I VehicleGearStateTopic: VehicleGear validity: 0
    08-25 12:56:07.665  4112  5113 I VehicleGearStateTopic: getVehicleGear: 0
    08-25 12:56:07.665  1996  4258 E PowertainController: onSignalChanged 
>>> 08-25 12:56:07.665  4112  5113 D SDV_CoreService: [SomeIpUtil]uri: cls:/propulsion.transmission/1/gear#VehicleGearState
    08-25 12:56:07.665  3814  3888 I SOIMT_PhoneLinkAdapterService_V2.0.0.51: [CarAdapterSensorManager] transitionStatus gearboxModel 0  transmissionStatus 1
    08-25 12:56:07.665  1996  4258 D TagLauncher: onVehicleMotionMovementStateChanged integer: 0 mResumed: false, mCurDeskMode: KANZI_MODE isKanziConnect: true
    08-25 12:56:07.665  4515  5189 I com.patac.hmi.settings-PowertainRepository: onCurrentGearChanged:0

L47821     08-25 12:56:07.668  4112  5115 D TimeResult: SystemClock: 3648209, ElapsedRealtimeMillis: 1892235
    08-25 12:56:07.668  4112  5115 D TimeResult: mTimeMillis: 1787632011696, AgeMillis: 1755974
    08-25 12:56:07.668  4112  5039 D SDV_CoreService: [RearRightDoorSignalTopicMapper]SUCCESS: NOTIFY_BODY_INFORMATION_17
>>> 08-25 12:56:07.668  4112  5115 D SDV_CoreService: [SomeIpUtil]publish event: uri: cls:/propulsion.transmission/1/gear#VehicleGearState
    08-25 12:56:07.668  4112  5115 D [ClsLinkSDK-v0.0.33] BusClient: send: {id='1f1a0414-89ba-6061-8f77-f3ea29b5da50'}
    08-25 12:56:07.668  4112  5039 D SDV_CoreService: [RearRightDoorSignalTopicMapper]resp.srrvcpwlsCurrSeltnVal():2
    08-25 12:56:07.668  4515  5189 D VehicleController: get property[VendorProperty.VEHICLE_MOTION_MOVEMENT_STATE] : CarPropertyValue{mPropertyId=0x21401045, propertyName=0x21401045, mAreaId=0x1000000, mStatus=0, mTimestampNanos=3648202726054, mValue=0}

L49600     08-25 12:56:10.481  2015  2015 D UpdateService-GMLANProxy: handleVehicleParked: false
    08-25 12:56:10.481  1996  4258 E PowertainController: onSignalChanged 
    08-25 12:56:10.481  1996  4258 D PatacExtendPowerOffSignal: onVehicleMotionMovementStateChanged : 2
>>> 08-25 12:56:10.481  4112  5113 D SDV_CoreService: [SomeIpUtil]uri: cls:/propulsion.transmission/1/gear#VehicleGearState
    08-25 12:56:10.481  2015  2015 D UpdateService-GMLANProxy: Transmission type: automatic
    08-25 12:56:10.481  4112  5113 D SDV_CoreService: [PropulsionLaunchManager]state: 2
    08-25 12:56:10.481  4515  5189 D VehicleController: com.patac.hmi.settings.domain.systemsetting.audio.AudioExtService$2@1642345 onSignalChanged

L49647     08-25 12:56:10.483  4515  5188 D com.patac.hmi.settings-ADASPermissionManager: powerModeChanged:true
    08-25 12:56:10.483  4112  5115 D TimeResult: SystemClock: 3651024, ElapsedRealtimeMillis: 1892235
    08-25 12:56:10.483  4112  5115 D TimeResult: mTimeMillis: 1787632011696, AgeMillis: 1758789
>>> 08-25 12:56:10.483  4112  5115 D SDV_CoreService: [SomeIpUtil]publish event: uri: cls:/propulsion.transmission/1/gear#VehicleGearState
    08-25 12:56:10.483  4112  5115 D [ClsLinkSDK-v0.0.33] BusClient: send: {id='1f1a0414-a492-6963-8f77-f3ea29b5da50'}
    08-25 12:56:10.483  4105  4559 I com.gm.updater-UpdaterAppService: ┌────────────────────────────────────────────────────────────────────────────────────────────────────────────────
    08-25 12:56:10.483  4105  4559 I com.gm.updater-UpdaterAppService: │ UpdaterAppService.onShiftParkedChange  (UpdaterAppService.java:556)

L51730     08-25 12:56:12.896  2073  2073 D PatacDMSController: updateFrom: 0
    08-25 12:56:12.896  3501  3501 I PhoneLinkCarListenerImpl: onCar360StatusChanged: true
    08-25 12:56:12.896  2073  2073 W ViewInflater: notifyItemDataChanged: no container :-1 ignore notify
>>> 08-25 12:56:12.896  4112  5113 D SDV_CoreService: [SomeIpUtil]uri: cls:/propulsion.transmission/1/gear#VehicleGearState
    08-25 12:56:12.896  3501  3501 E HandleRvcManager: handleRvcOpen mIsRvcOpened: false
    08-25 12:56:12.896  3501  3501 E HandleRvcManager: handleRvcOpen gal is null return: 
    08-25 12:56:12.896  2073  3958 D PatacIntelligentDrivingSystemModeRespUseCase: onNext: ItemRespData{hash=265816769, enabled=true, powerOn=true, selected=false, value=102.0, message='106', clickEnabled=true, loading=false}

L51754     08-25 12:56:12.897  1368  1368 E         : VSIP: routing_manager_impl::send set request (0001): [0001.0001.01bb] 0075
    08-25 12:56:12.897  5951  6098 I CabinModeService: onDataChange
    08-25 12:56:12.897  5951  6098 D CabinModeService: sendDataToClient，id=40005
>>> 08-25 12:56:12.897  4112  5115 D SDV_CoreService: [SomeIpUtil]publish event: uri: cls:/propulsion.transmission/1/gear#VehicleGearState
    08-25 12:56:12.897  4112  5115 D [ClsLinkSDK-v0.0.33] BusClient: send: {id='1f1a0414-bb9a-697e-8f77-f3ea29b5da50'}
    08-25 12:56:12.897  2073  4021 D PatacSuperWelcomeRespUseCase: onNext: ItemRespData{hash=198112072, enabled=false, powerOn=true, selected=false, value=-1.0, message='-1', clickEnabled=true, loading=false}
    08-25 12:56:12.897  4515  5189 D VehicleController: get property[VehiclePropertyIds.DOOR_POS] : CarPropertyValue{mPropertyId=0x16400b00, propertyName=DOOR_POS, mAreaId=0x1, mStatus=0, mTimestampNanos=1914338248955, mValue=0}

L52882     08-25 12:56:13.116  4112  5150 D LightingSomeIpClient: resp.getTrnSwAct():0
    08-25 12:56:13.116  4112  5150 D LightingSomeIpClient: resp.getHazSwAtv():false
    08-25 12:56:13.116  4112  5150 I LampMapper: sendReverseTopic LampState: true
>>> 08-25 12:56:13.116  4112  5150 D SDV_CoreService: [SomeIpUtil]uri: cls:/body.lighting.exterior/1/lamp.reverse#Lamp
    08-25 12:56:13.116  1089  7403 I Bosch_NavSensors: GnssSourceVIP::readerThread ipc_read ret time s 13 ms 400
    08-25 12:56:13.116  4112  5150 D VehicleSomeIpClient: resp.getOtsdAmbtLtLvlStat():2
    08-25 12:56:13.116  4112  5150 D VehicleSomeIpClient: resp.getOtsdAmbtLtLvlStatV():0

L52889     08-25 12:56:13.117  4112  5115 D TimeResult: SystemClock: 3653658, ElapsedRealtimeMillis: 1892235
    08-25 12:56:13.117  4112  5115 D TimeResult: mTimeMillis: 1787632011696, AgeMillis: 1761423
    08-25 12:56:13.117  1089  7404 D ACCGYROCALIBRATION: DHSY 501263551664 1787633773117
>>> 08-25 12:56:13.117  4112  5115 D SDV_CoreService: [SomeIpUtil]publish event: uri: cls:/body.lighting.exterior/1/lamp.reverse#Lamp
    08-25 12:56:13.117  4112  5115 D [ClsLinkSDK-v0.0.33] BusClient: send: {id='1f1a0414-bdb1-6430-8f77-f3ea29b5da50'}
    08-25 12:56:13.117  1089  1373 D Bosch_NavSensors: Nmea: 1787633773400 : $GPGGA,045613.40,3120.158559,N,12047.433480,E,1,10,0.0,25.3,M,,M,,*4B
    08-25 12:56:13.117  1089  1373 D Bosch_NavSensors: Nmea: 1787633773400 : $GPRMC,045613.40,A,3120.158559,N,12047.433480,E,0.0000,22.3000,250826,,,A*6A

L59845     08-25 12:56:23.144  4112  5113 I VehicleGearStateTopic: getVehicleGear: 1
    08-25 12:56:23.144  3814  3888 I SOIMT_PhoneLinkAdapterService_V2.0.0.51: [CarAdapterSensorManager] onGearDataChanged 1
    08-25 12:56:23.144  3814  3888 I SOIMT_PhoneLinkAdapterService_V2.0.0.51: [CarAdapterSensorManager] transitionStatus gearboxModel 1  transmissionStatus 3
>>> 08-25 12:56:23.144  4112  5113 D SDV_CoreService: [SomeIpUtil]uri: cls:/propulsion.transmission/1/gear#VehicleGearState
    08-25 12:56:23.144  4515  5189 E PowertainController: onSignalChanged 
    08-25 12:56:23.144  4112  5113 D SDV_CoreService: [PropulsionLaunchManager]state: 1
    08-25 12:56:23.144  3814  3888 I SOIMT_PhoneLinkAdapterService_V2.0.0.51: [CarAdapterSensorManager] transitionStatus gearboxModel 1  transmissionStatus 3

L59933     08-25 12:56:23.147  4112  5115 D TimeResult: mTimeMillis: 1787632011696, AgeMillis: 1771453
    08-25 12:56:23.147  4515  5189 D CAR.L   : setGroupVolume, zoneid: 0, groupId: 0, index: 25, flags: 16777216
    08-25 12:56:23.147  1371  1433 D GMVHAL  : vhal_get Property: PatacProperty::DISCHARGE_CORDSET_CONNECTION_STATUS AreaID: 16777216 Status: 0 int32Values: 0 
>>> 08-25 12:56:23.147  4112  5115 D SDV_CoreService: [SomeIpUtil]publish event: uri: cls:/propulsion.transmission/1/gear#VehicleGearState
    08-25 12:56:23.147  4112  5115 D [ClsLinkSDK-v0.0.33] BusClient: send: {id='1f1a0415-1d5b-6076-8f77-f3ea29b5da50'}
    08-25 12:56:23.148  4193  4471 D VehicleController: get property[557867024] : CarPropertyValue{mPropertyId=0x21406010, propertyName=0x21406010, mAreaId=0x1000000, mStatus=0, mTimestampNanos=9733166765, mValue=0}
    08-25 12:56:23.148  4477  5049 D ServiceBus: [Dispatcher] Received handleGenericMessage CloudEvent=CloudEvent{id='1f1a0415-1d5b-6076-8f77-f3ea29b5da50', source=cls:/propulsion.transmission/1/gear#VehicleGearState, type='pub.v1', datacontenttype='application/x-protobuf', dataschema=type.googleapis.co

L60724     08-25 12:56:23.366  4112  5150 D LightingSomeIpClient: resp.getTrnSwAct():0
    08-25 12:56:23.366  4112  5150 D LightingSomeIpClient: resp.getHazSwAtv():false
    08-25 12:56:23.367  4112  5150 I LampMapper: sendReverseTopic LampState: false
>>> 08-25 12:56:23.367  4112  5150 D SDV_CoreService: [SomeIpUtil]uri: cls:/body.lighting.exterior/1/lamp.reverse#Lamp
    08-25 12:56:23.368  4112  5150 D VehicleSomeIpClient: resp.getOtsdAmbtLtLvlStat():2
    08-25 12:56:23.368  4112  5150 D VehicleSomeIpClient: resp.getOtsdAmbtLtLvlStatV():0
    08-25 12:56:23.369  4112  5115 D TimeResult: SystemClock: 3663910, ElapsedRealtimeMillis: 1892235

L61331     08-25 12:56:23.846  4112  5113 D VehicleGearStateTopic: sendTopic
    08-25 12:56:23.846  4112  5113 I VehicleGearStateTopic: VehicleGear validity: 0
    08-25 12:56:23.846  4112  5113 I VehicleGearStateTopic: getVehicleGear: 0
>>> 08-25 12:56:23.846  4112  5113 D SDV_CoreService: [SomeIpUtil]uri: cls:/propulsion.transmission/1/gear#VehicleGearState
    08-25 12:56:23.846  4112  5113 D SDV_CoreService: [PropulsionLaunchManager]state: 0
    08-25 12:56:23.846  5951  6023 D VehicleController: Receive: CarPropertyValue{mPropertyId=0x21401045, propertyName=0x21401045, mAreaId=0x1000000, mStatus=0, mTimestampNanos=3664385654433, mValue=0} from CarService
    08-25 12:56:23.847  5951  6023 D VehicleController: com.sgm.climate.domain.signal.repostiory.ChildLockRepository$5@71dae48 onSignalChanged

⚠️ 搜索结果高度重复: 共 30 条匹配中，有 30 条内容相同 ('')。以上仅展示 15 条代表性结果。

---

## 第 6 轮 — LLM 响应



---

## 第 6 轮 — 工具执行结果

[结果 1] 搜索结果: 共 30 条匹配，显示 15 条

L49819     08-25 12:56:10.509  4112  5017 I SDV_CoreService: [CarPropertyEventCallback]publish cloud event, topic uri: cls:/body.seating/1/seat_mode#SeatMode
    08-25 12:56:10.509  2073  3259 I PatacFsaManager: [notifyCallback] methods: [onSettingClusterViewChangedRequest, onClusterViewChangeEnableRequest] ,method: onHudCanMirrorRequest ,args: [false, 0]
    08-25 12:56:10.509  2073  3259 I PatacFsaManager: [notifyCallback] methods: [onAllHudSettingInfoRequest, onHudSettingChangedRequest, onClusterViewChangeEnableRequest] ,method: onHudCanMirrorRequest ,args: [false, 0]
>>> 08-25 12:56:10.509  2073  3259 I PatacFsaManager: [notifyCallback] methods: [onSavedDisplayBrightnessValue, onDisplayBrightnessValueForOHD] ,method: onHudCanMirrorRequest ,args: [false, 0]
    08-25 12:56:10.509  2073  3259 I PatacFsaManager: [notifyCallback] methods: [onAllHudSettingInfoRequest, onHudSettingChangedRequest, onClusterViewChangeEnableRequest] ,method: onHudCanMirrorRequest ,args: [false, 0]
    08-25 12:56:10.509  2073  3259 I PatacFsaManager: [notifyCallback] methods: [onAllHudSettingInfoRequest, onHudSettingChangedRequest, onClusterViewChangeEnableRequest] ,method: onHudCanMirrorRequest ,args: [false, 0]
    08-25 12:56:10.509  2073  4040 I PatacOdiManager: array[DYN_VALUE_INDEX]: 52electricValue:150

L131583     08-25 12:58:37.569  2073  7391 D PATACREMOTESettingsManager: onMethodRequest end 5014
    08-25 12:58:37.569  2073  3259 I PatacFsaManager: [notifyCallback] methods: [onSettingClusterViewChangedRequest, onClusterViewChangeEnableRequest] ,method: onHudCanMirrorRequest ,args: [false, 0]
    08-25 12:58:37.569  2073  3259 I PatacFsaManager: [notifyCallback] methods: [onAllHudSettingInfoRequest, onHudSettingChangedRequest, onClusterViewChangeEnableRequest] ,method: onHudCanMirrorRequest ,args: [false, 0]
>>> 08-25 12:58:37.569  2073  3259 I PatacFsaManager: [notifyCallback] methods: [onSavedDisplayBrightnessValue, onDisplayBrightnessValueForOHD] ,method: onHudCanMirrorRequest ,args: [false, 0]
    08-25 12:58:37.569  2073  3259 I PatacFsaManager: [notifyCallback] methods: [onAllHudSettingInfoRequest, onHudSettingChangedRequest, onClusterViewChangeEnableRequest] ,method: onHudCanMirrorRequest ,args: [false, 0]
    08-25 12:58:37.569  2073  3259 I PatacFsaManager: [notifyCallback] methods: [onAllHudSettingInfoRequest, onHudSettingChangedRequest, onClusterViewChangeEnableRequest] ,method: onHudCanMirrorRequest ,args: [false, 0]
    08-25 12:58:37.569  4112  6563 D PATACREMOTESettingsManager: onHudCanMirrorRequest canMirror = false , reason = 0

L185581     08-25 13:00:02.164  4112  5567 D PATACREMOTESettingsManager: onMethodRequest end 5014
    08-25 13:00:02.164  2073  3259 I PatacFsaManager: [notifyCallback] methods: [onAllHudSettingInfoRequest, onHudSettingChangedRequest, onClusterViewChangeEnableRequest] ,method: onHudCanMirrorRequest ,args: [false, 0]
    08-25 13:00:02.164  4515  4533 D PATACREMOTESettingsManager: onHudCanMirrorRequest canMirror = false , reason = 0
>>> 08-25 13:00:02.164  2073  3259 I PatacFsaManager: [notifyCallback] methods: [onSavedDisplayBrightnessValue, onDisplayBrightnessValueForOHD] ,method: onHudCanMirrorRequest ,args: [false, 0]
    08-25 13:00:02.164  4515  4533 D PATACREMOTESettingsManager: onHudCanMirrorRequest canMirror = false , reason = 0
    08-25 13:00:02.164  2073  3259 I PatacFsaManager: [notifyCallback] methods: [onAllHudSettingInfoRequest, onHudSettingChangedRequest, onClusterViewChangeEnableRequest] ,method: onHudCanMirrorRequest ,args: [false, 0]
    08-25 13:00:02.164  4515  4533 D PATACREMOTESettingsManager: onHudCanMirrorRequest canMirror = false , reason = 0

L218835     08-25 12:54:19.199  2073  3259 I PatacFsaManager: [notifyCallback] methods: [onSettingClusterViewChangedRequest, onClusterViewChangeEnableRequest] ,method: onHudCanMirrorRequest ,args: [false, 0]
    08-25 12:54:19.199  4112  5535 D SDV_CoreService: [automaticShutdown_util] getVehicleMotionMovementState = 2
    08-25 12:54:19.199  2073  3259 I PatacFsaManager: [notifyCallback] methods: [onAllHudSettingInfoRequest, onHudSettingChangedRequest, onClusterViewChangeEnableRequest] ,method: onHudCanMirrorRequest ,args: [false, 0]
>>> 08-25 12:54:19.199  2073  3259 I PatacFsaManager: [notifyCallback] methods: [onSavedDisplayBrightnessValue, onDisplayBrightnessValueForOHD] ,method: onHudCanMirrorRequest ,args: [false, 0]
    08-25 12:54:19.199  4112  5535 D SDV_CoreService: [automaticShutdown_util] getUsableStateOfCharge = 82.595825
    08-25 12:54:19.199  2073  3259 I PatacFsaManager: [notifyCallback] methods: [onAllHudSettingInfoRequest, onHudSettingChangedRequest, onClusterViewChangeEnableRequest] ,method: onHudCanMirrorRequest ,args: [false, 0]
    08-25 12:54:19.199  2073  3259 I PatacFsaManager: [notifyCallback] methods: [onAllHudSettingInfoRequest, onHudSettingChangedRequest, onClusterViewChangeEnableRequest] ,method: onHudCanMirrorRequest ,args: [false, 0]

L222557     08-25 12:54:22.808  1683  3894 D InputDispatcher: setInputWindows displayId=0 3add973 BottomCarSystemBar d735dc9 TopCarSystemBar ac56292 com.ts.kanziservice SurfaceView[com.patac.hmi.settings/com.patac.hmi.settings.presentation.systemsetting.ui.SettingsActivity](BLAST)#375 bbq-wrapper#195 bbq-wrappe
    08-25 12:54:22.810  2073  3259 I PatacFsaManager: [notifyCallback] methods: [onSettingClusterViewChangedRequest, onClusterViewChangeEnableRequest] ,method: onHudCanMirrorRequest ,args: [false, 0]
    08-25 12:54:22.810  2073  3259 I PatacFsaManager: [notifyCallback] methods: [onAllHudSettingInfoRequest, onHudSettingChangedRequest, onClusterViewChangeEnableRequest] ,method: onHudCanMirrorRequest ,args: [false, 0]
>>> 08-25 12:54:22.810  2073  3259 I PatacFsaManager: [notifyCallback] methods: [onSavedDisplayBrightnessValue, onDisplayBrightnessValueForOHD] ,method: onHudCanMirrorRequest ,args: [false, 0]
    08-25 12:54:22.810  2073  3259 I PatacFsaManager: [notifyCallback] methods: [onAllHudSettingInfoRequest, onHudSettingChangedRequest, onClusterViewChangeEnableRequest] ,method: onHudCanMirrorRequest ,args: [false, 0]
    08-25 12:54:22.810  2073  3259 I PatacFsaManager: [notifyCallback] methods: [onAllHudSettingInfoRequest, onHudSettingChangedRequest, onClusterViewChangeEnableRequest] ,method: onHudCanMirrorRequest ,args: [false, 0]
    08-25 12:54:22.811  4112  5535 D SDV_CoreService: [automaticShutdown_VehicleAutomaticShutdownManager]signalUpdate: []

L241962     08-25 12:54:50.984  5428  5428 I com.patac.hmi.user-UserAccount: CleaNewDriverHabitManager:用户主动保存用车习惯，进行便利上下车拦截
    08-25 12:54:50.984  5428  5428 I com.patac.hmi.user-UserAccount: UserDataTrackUtils:deal seat set Data Track
    08-25 12:54:50.984  5428  5428 I com.patac.hmi.user-UserAccount: UserDataTrackUtils:sendDataTrack eventName: User_Seat_Set properties: {"G640":"","G528":"","G622":"","G33":"GUEST"}
>>> 08-25 12:54:50.985  5428  5428 I com.patac.hmi.user-UserAccount: SaveDriverHabitFlow-CommitId-64b31da:saveDriverHabit Habit_V1.0_ID1 isFirstSave false
    08-25 12:54:50.985  5428  5428 I com.patac.hmi.user-UserAccount: SharedPreferenceUtils-CommitId-64b31da:saveInfo: key = preference_last_select_habit, value = Habit_V1.0_ID1
    08-25 12:54:50.985  5428  5428 I com.patac.hmi.user-UserAccount: DriverHabitInfoUnit:getHabit is  type: null
    08-25 12:54:50.985  5428  5428 I com.patac.hmi.user-UserAccount: SaveDriverHabitFlow:saveDriverHabitInternal result = true

L241971     08-25 12:54:50.985

... [截断: 原始结果 17,043 字符，已截取中间 2,043 字符] ...

:50.988  5428  5428 W WindowOnBackDispatcher: sendCancelIfRunning: isInProgress=falsecallback=android.view.ViewRootImpl$$ExternalSyntheticLambda17@f5a8f25
>>> 08-25 12:54:50.988  5428 10643 I com.patac.hmi.user-UserAccount: DriverHabitGuestHandle:saveCleaNewDriverHabitGuest columnPosition = null
    08-25 12:54:50.988  5428 10643 I com.patac.hmi.user-UserAccount: DriverHabitGuestHandle:saveCleaNewDriverHabitGuest type5
    08-25 12:54:50.989  1683  2115 D CoreBackPreview: Window{dd66c00 u10 com.patac.hmi.user}: Setting back callback null
    08-25 12:54:50.989  5428  5428 D [CommonWidgetLog2.3.7] : 【OverlayFocusManager】detachFrom ,view:patac.widget.button.PatacSecondButton{70e1cdc VFED..C.. ......ID 38,331-323,406 #7f09008a app:id/btnMirrors} ,group:null

L241992     08-25 12:54:50.989  5428  5428 D [CommonWidgetLog2.3.7] : 【OverlayFocusManager】detachFrom ,view:patac.widget.uimode.PatacUIModeImageView{13a44ba V.ED..... ......ID 88,331-163,406 #7f0901ac app:id/ivMirrors} ,group:null
    08-25 12:54:50.989  5428  5428 D [CommonWidgetLog2.3.7] : 【OverlayFocusManager】detachFrom ,view:patac.widget.button.PatacSecondButton{89c1f6b VFED..C.. ......ID 351,331-636,406 #7f090087 app:id/btnHud} ,group:null
    08-25 12:54:50.989  5428  5428 D [CommonWidgetLog2.3.7] : 【OverlayFocusManager】detachFrom ,view:patac.widget.uimode.PatacUIModeImageView{3ce2ac8 V.ED..... ......ID 373,331-448,406 #7f0901a8 app:id/ivHud} ,group:null
>>> 08-25 12:54:50.990  5428 10643 I com.patac.hmi.user-UserAccount: DriverHabitGuestHandle:saveInfo: key = Habit_V1.0_ID1, value = {"HabitName":"","HabitUUID":"881b7ba6-1131-4918-8a47-0c9fd22355ac","version":"1.0","DriverHabitSelect":true,"ForwardBackward":51.725002,"ReclineUpwardDownward":23.825,"Cush
    08-25 12:54:50.990   772   821 D audioserver: logFgsApiBegin: FGS Logger Transaction failed, -129
    08-25 12:54:50.992   723  7712 D audio_hw_primary: update_source_metadata_v7: source_metadata track_count: 1
    08-25 12:54:50.992   723  7712 I audio_hw_primary: source_metadata mUsage = 13

L242001     08-25 12:54:50.993   723  1180 I android.hardware.audio@2.0-service.gmvcu: getVolumeGroupType: 1385: [VolumeGroupTypesMap::getVolumeGroupType]: address: BUS01_SYS_NOTIFICATION, tailgate: 0
    08-25 12:54:50.993   723  1180 I AHAL: AudioMsgQueue: [AudioMsg] reqId=1401, type=210, MsgGetVolumeGroupTypeRsp: errCode=0, vgType=6
    08-25 12:54:50.993   723  1180 I AHAL: AudioMsgQueue: [AudioMsg] fulfillGetRequestForType success: reqId=1401, errCode=0
>>> 08-25 12:54:50.993  5428 10643 I com.patac.hmi.user-UserAccount: DriverHabitGuestHandle:saveCleaNewDriverHabitGuest result is true
    08-25 12:54:50.993   723  6153 I AHAL: AudioHelper: AudioHelper::getVolumeGroupType::BUS(BUS01_SYS_NOTIFICATION) vgType is 6
    08-25 12:54:50.993   723  6153 I AHAL: AudioMsgQueue: [AudioMsg] reqId=1402, type=129, MsgSetEnableConnection: address=BUS01_SYS_NOTIFICATION
    08-25 12:54:50.993  5428 10643 I com.patac.hmi.user-UserAccount: DriverHabitGuestHandle:saveCleaNewDriverHabit

L242015     08-25 12:54:50.993   723  1180 D android.hardware.audio@2.0-service.gmvcu: isConnAllowedInLifeCycleState: 1595: [ASCConnectionManager::isConnAllowedInLifeCycleState]:Started_AllAudio
    08-25 12:54:50.993   723  1180 I android.hardware.audio@2.0-service.gmvcu: CreateConnection: 166: [ASCConnectionManager::CreateConnection]: Enter SourceID 7, SinkID 13 
    08-25 12:54:50.993   723  1180 I android.hardware.audio@2.0-service.gmvcu: isConnectionAllowed: 324: [ASCConnectionManager::isConnectionAllowed]: SourceID 7, SinkID 13 
>>> 08-25 12:54:50.993  5428 10643 I com.patac.hmi.user-UserAccount: DriverHabitGuestHandle:saveCleaNewDriverHabitGuest type1
    08-25 12:54:50.993   723  1180 I android.hardware.audio@2.0-service.gmvcu: getNextConnectionID: 282: [ASCConnectionManager::getNextConnectionID]: Leave, ConnectionID is 5
    08-25 12:54:50.993   723  1180 D android.hardware.audio@2.0-service.gmvcu: CreateConnection: 178: [ASCConnectionManager::CreateConnection]: Connection(Id = 5) created.
    08-25 12:54:50.993  5428 10643 I com.patac.hmi.user-UserAccount: DriverHabitGuestHandle:saveCleaNewDriverHabitGuest type2

L242023     08-25 12:54:50.993   723  1180 I android.hardware.audio@2.0-service.gmvcu: SetConnect: 127: [ASCConnectionManagerSM::SetConnect]: Entered 
    08-25 12:54:50.993   723  1180 D android.hardware.audio@2.0-service.gmvcu: progressStateMachine: 88: [ASCConnectionManagerSM::progressStateMachine]: currenrtState - 1  NextState - 2 
    08-25 12:54:50.993   723  1180 I android.hardware.audio@2.0-service.gmvcu: StartPrepareConnection: 264: [ASCConnectionManagerSM::StartPrepareConnection]: Enter 
>>> 08-25 12:54:50.993  5428 10643 I com.patac.hmi.user-UserAccount: DriverHabitGuestHandle:saveCleaNewDriverHabitGuest columnPosition = null
    08-25 12:54:50.993   723  1180 I android.hardware.audio@2.0-service.gmvcu: enableConnection: 1870: [ASCVolumeManager::enableConnection]: entered sourceID = 7 ,sinkID = 13 , mDuckingSwitch = 1 m_AudioConfiguration=5
    08-25 12:54:50.993   723  1180 I android.hardware.audio@2.0-service.gmvcu: evaluateNewConnection: 236: [VolumeDuck::evaluateNewConnection]: leave, headrestMode: 0, src: 7, sink: 13, type: 6
    08-25 12:54:50.993   723  1180 I AHAL: AudioHelper: AudioHelper::vSendVolumeMsg Token = 641, IDCVolumeGroupType : VOL_GROUP_HEADREST_FL, volumeLevel: 0

L242037     08-25 12:54:50.993   723  1180 I audiohalservice: vSendMsg Msgid 1 and Length 16
    08-25 12:54:50.993   723  1180 I audiohalservice: AudioINCClient():writeMsg:fd :13, 4 
    08-25 12:54:50.993   723  1180 I audiohalservice: AudioINCClient():writeMsg:fd :13, 16 
>>> 08-25 12:54:50.993  5428 10643 I com.patac.hmi.user-UserAccount: DriverHabitGuestHandle:saveInfo: key = Habit_V1.0_ID2, value = {"HabitName":"","HabitUUID":"6e792921-e4bd-4c7f-bb87-4d1517bef3c5","version":"1.0","DriverHabitSelect":false,"ForwardBackward":65.775,"ReclineUpwardDownward":23.825,"Cushio
    08-25 12:54:50.993   723  1180 I AHAL: AudioHelper: AudioHelper::vSendVolumeMsg Token = 643, IDCVolumeGroupType : VOL_GROUP_HEADREST_RL, volumeLevel: 0
    08-25 12:54:50.993   723  1180 I audiohalservice: IDCClientThread::vsendmsg Msgid 1 and Length 12 acttoken =643
    08-25 12:54:50.993   723  1180 I audiohalservice: vSendMsg Msgid 1 and Length 16

L242056     08-25 12:54:50.993   723  1180 D android.hardware.audio@2.0-service.gmvcu: setStaticOffsets: 871: [VolumeGroup::setStaticOffsets]: entering 
    08-25 12:54:50.993   723  1180 D android.hardware.audio@2.0-service.gmvcu: setStaticOffsets: 920: [VolumeGroup::setStaticOffset]: no change of static offset or attenuation, no update of volume required
    08-25 12:54:50.993   723  1180 D android.hardware.audio@2.0-service.gmvcu: setStaticOffsets: 922: [VolumeGroup::setStaticOffset]: exiting 
>>> 08-25 12:54:50.993  5428 10643 I com.patac.hmi.user-UserAccount: DriverHabitGuestHandle:saveCleaNewDriverHabitGuest result is true
    08-25 12:54:50.993   723  1180 D android.hardware.audio@2.0-service.gmvcu: setStaticOffset: 859: [VolumeGroup::setStaticOffset]: exiting 
    08-25 12:54:50.993   723  1180 D android.hardware.audio@2.0-service.gmvcu: enableConnection: 1907: [ASCVolumeManager::enableConnection] activate() called on volumegroup 6, stepValue 30
    08-25 12:54:50.993   723  1180 I android.hardware.audio@2.0-service.gmvcu: activate: 492: [VolumeGroup::activate]: entering, mVolumeGroupStatus = 4 

⚠️ 搜索结果高度重复: 共 30 条匹配中，有 30 条内容相同 ('')。以上仅展示 15 条代表性结果。

---

[结果 2] 搜索结果: 共 40 条匹配，显示 15 条

L17075     08-25 12:55:22.433  5428  5743 I com.patac.hmi.user-UserAccount: DriverHabitMessageHandle:dealDriverMirrorFeedbackEvent 主驾后视镜反馈 is 2
    08-25 12:55:22.434  5428  5743 I com.patac.hmi.user-UserAccount: SystemInfoRepository:sendSystemEvent type is 4 id is  4202
    08-25 12:55:22.434  5428  5428 I com.patac.hmi.user-UserAccount: UserApplicationManager:get system event 4202
>>> 08-25 12:55:22.434  5428  5428 I com.patac.hmi.user-UserAccount: CleaNewDriverHabitManager:dealCustomEvent CLEA2_DRIVER_HABIT_RESULT_EVENT
    08-25 12:55:22.434  5428  5428 I com.patac.hmi.user-UserAccount: UserFeatureManager:isMcuEnableDriverHabit mIsMcuEnableDriverHabit = true
    08-25 12:55:22.434   732   732 I Calibrationd: [532501538040]CalibrationUsageLog.cpp::logUsage(34): Calibration Requested: com.patac.hmi.user: GMModel: ENUMERATION: [Module]GMModel: ENUMERATION: 84
    08-25 12:55:22.434  5428  5428 I com.patac.hmi.user-UserAccount: CalibrationDataSource:Calibration:MODEL=84

L17149     08-25 12:55:22.456  4515  5201 I com.patac.hmi.settings-BaseTopicHandler: registerEventListener
    08-25 12:55:22.456  5428  5743 I com.patac.hmi.user-UserAccount: SystemInfoRepository:sendSystemEvent type is 4 id is  4202
    08-25 12:55:22.456  5428  5428 I com.patac.hmi.user-UserAccount: UserApplicationManager:get system event 4202
>>> 08-25 12:55:22.456  5428  5428 I com.patac.hmi.user-UserAccount: CleaNewDriverHabitManager:dealCustomEvent CLEA2_DRIVER_HABIT_RESULT_EVENT
    08-25 12:55:22.456  5428  5428 I com.patac.hmi.user-UserAccount: UserFeatureManager:isMcuEnableDriverHabit mIsMcuEnableDriverHabit = true
    08-25 12:55:22.456  4515  5201 I com.patac.hmi.settings-BaseTopicHandler: result is not null
    08-25 12:55:22.456   732   732 I Calibrationd: [532501538040]CalibrationUsageLog.cpp::logUsage(34): Calibration Requested: com.patac.hmi.user: GMModel: ENUMERATION: [Module]GMModel: ENUMERATION: 84

L17157     08-25 12:55:22.457  5428  5428 I com.patac.hmi.user-UserAccount: UserFeatureManager:isModelTypeE22 isE22 = false
    08-25 12:55:22.457  5428  5428 I com.patac.hmi.user-UserAccount: CleaNewDriverHabitManager:dealDriverHabitResultEvent: seatResult is 0 leftMirrorResult is 0 rightMirrorResult is 0 mDriverMirrorFeedback 0 mPassengerMirrorFeedback 0
    08-25 12:55:22.457  4515  5201 I com.patac.hmi.settings-RearviewMirrorAdjustTopic: 32773--->makeResult: name: "OSRVM.left"
>>> 08-25 12:55:22.457  5428  5428 I com.patac.hmi.user-UserAccount: CleaNewDriverHabitManager:dealDriverHabitResultEvent mRestoreDriverHabitFlow is null
    08-25 12:55:22.457  4515  5201 I com.patac.hmi.settings-RearviewMirrorAdjustTopic: horizontal_angle: -0.2
    08-25 12:55:22.457  4515  5201 I com.patac.hmi.settings-RearviewMirrorAdjustTopic: vertical_angle: -5.6
    08-25 12:55:22.457  4515  5201 I com.patac.hmi.settings-RearviewMirrorAdjustTopic: is_supported: true

L17173     08-25 12:55:22.477  5428  5704 I com.patac.hmi.user-UserAccount: DriverHabitMessageHandle:sendDriverHabitEvent afterCheck
    08-25 12:55:22.477  5428  5704 I com.patac.hmi.user-UserAccount: SystemInfoRepository:sendSystemEvent type is 4 id is  4201
    08-25 12:55:22.477  5428  5428 I com.patac.hmi.user-UserAccount: UserApplicationManager:get system event 4201
>>> 08-25 12:55:22.477  5428  5428 I com.patac.hmi.user-UserAccount: CleaNewDriverHabitManager:dealCustomEvent CLEA_DRIVER_HABIT_DATA_EVENT
    08-25 12:55:22.477  5428  5428 I com.patac.hmi.user-UserAccount: DriverHabitInfoUnit:updateCurrentHabitInfo
    08-25 12:55:22.477  5428  5428 I com.patac.hmi.user-UserAccount: UserFeatureManager:isMcuEnableDriverHabit mIsMcuEnableDriverHabit = true
    08-25 12:55:22.477  5428  5428 I com.patac.hmi.user-UserAccount: CleaNewDriverHabitManager:dealDriverHabitDataEvent mHabitRestoreResult is null

L17219     08-25 12:55:22.581  5428  5704 I com.patac.hmi.user-UserAccount: CarDataSource:right mirror position:-5.2000003 0.0 0.0 
    08-25 12:55:22.581  5428  5428 I com.patac.hmi.user-UserAccount: UserApplicationManager:get system event 4201
    08-25 12:55:22.581  5428  5704 I com.patac.hmi.user-UserAccount: DriverHabitMessageHandle:sendDriverHabitEvent afterCheck
>>> 08-25 12:55:22.581  5428  5428 I com.patac.hmi.user-UserAccount: CleaNewDriverHabitManager:dealCustomEvent CLEA_DRIVER_HABIT_DATA_EVENT
    08-25 12:55:22.581  5428  5704 I com.patac.hmi.user-UserAccount: SystemInfoRepository:sendSystemEvent type is 4 id is  4201
    08-25 12:55:22.581  5428  5428 I com.patac.hmi.user-UserAccount: DriverHabitInfoUnit:updateCurrentHabitInfo
    08-25 12:55:22.581  5428  5428 I com.patac.hmi.user-UserAccount: UserFeatureManager:isMcuEnableDriverHabit mIsMcuEnableDriverHabit = true

L17228     08-25 12:55:22.581  5428  5428 I com.patac.hmi.user-UserAccount: CleaNewDriverHabitManager:dealCustomEvent CLEA_DRIVER_HABIT_DATA_EVENT
    08-25 12:55:22.581  5428  5428 I com.patac.hmi.user-UserAccount: DriverHabitInfoUnit:updateCurrentHabitInfo
    08-25 12:55:22.581  5428  5428 I com.patac.hmi.user-UserAccount: UserFeatureManager:isMcuEnableDriverHabit mIsMcuEnableDriverHabit = true
>>> 08-25 12:55:22.581  5428  5428 I com.patac.hmi.user-UserAccount: CleaNewDriverHabitManager:dealDriverHabitDataEvent mHabitRestoreResult is null
    08-25 12:55:22.583  5951  6023 D CPECallbackController: Dropping carPropertyEvent - propId: 291504647 areaId: 16777216  because getTimestamp(): 3603139639816 < nextUpdateTimeNanos: 3603339639816
    08-25 12:55:22.595  2003  2200 D CarPropertyManager: getProperty, propertyId: 0x21410109, areaId: 0x1000000
    08-25 12:55:22.596  1371  1433 D GMVHAL  : vhal_get Property: VendorProperty::LOCAL_TIME AreaID: 16777216 Status: 0 int32Values: 2026 8 25 12 55 21 

L17287     08-25 12:55:22.688  5428  5704 I com.patac.hmi.user-UserAccount: DriverHabitMessageHandle:sendDriverHabitEvent afterCheck
    08-25 12:55:22.688  5428  5704 I com.patac.hmi.user-UserAccount: SystemInfoRepository:sendSystemEvent type is 4 id is  4201
    08-25 12:55:22.688  5428  5428 I com.patac.hmi.user-UserAccount: UserApplicationManager:get system event 4201
>>> 08-25 12:55:22.688  5428  5428 I com.patac.hmi.user-UserAccount: CleaNewDriverHabitManager:dealCustomEvent CLEA_DRIVER_HABIT_DATA_EVENT
    08-25 12:55:22.688  5428  5428 I com.patac.hmi.user-UserAccount: DriverHabitInfoUnit:updateCurrentHabitInfo
    08-25 12:55:22.688  5428  5428 I com.patac.hmi.user-UserAccount: UserFeatureManager:isMcuEnableDriverHabit mIsMcuEnableDriverHabit = true
    08-25 12:55:22.688  5428  5428 I com.patac.hmi.user-UserAccount: CleaNewDriverHabitManager:dealDriverHabitDataEvent mHabitRestoreResult is null

L17370     08-25 12:55:22.730  4515  4515 D com.patac.hmi.settings-DriveMirrorDialogManager: requestDisableValueFromSdvSomeIp Value-onNext: 66, disable = false, type = 19
    08-25 12:55:22.730  5428  5743 I com.patac.hmi.user-UserAccount: SystemInfoRepository:sendSystemEvent type is 4 id is  4202
    08-25 12:55:22.730  5428  5428 I com.patac.hmi.user-UserAccount: UserApplicationManager:get system event 4202
>>> 08-25 12:55:22.730  5428  5428 I com.patac.hmi.user-UserAccount: CleaNewDriverHabitManager:dealCustomEvent CLEA2_DRIVER_HABIT_RESULT_EVENT
    08-25 12:55:22.730  5428  5428 I com.patac.hmi.user-UserAccount: UserFeatureManager:isMcuEnableDriverHabit mIsMcuEnableDriverHabit = true
    08-25 12:55:22.731   732   732 I Calibrationd: [532501538040]CalibrationUsageLog.cpp::logUsage(34): Calibration Requested: com.patac.hmi.user: GMModel: ENUMERATION: [Module]GMModel: ENUMERATION: 84
    08-25 12:55:22.732  5428  5428 I com.patac.hmi.user-UserAccount: CalibrationDataSource:Calibration:MODEL=84

L17400     08-25 12:55:22.735  5428  5743 I com.patac.hmi.user-UserAccount: DriverHabitMessageHandle:dealPassengerMirrorFeedbackEvent 副驾后视镜反馈 is 0
    08-25 12:55:22.735  5428  5743 I com.patac.hmi.user-UserAccount: SystemInfoRepository:sendSystemEvent type is 4 id is  4202
    08-25 12:55:22.735  5428  5428 I com.patac.hmi.user-UserAccount: UserApplicationManager:get system event 4202
>>> 08-25 12:55:22.735  5428  5428 I com.patac.hmi.user-UserAccount: CleaNewDriverHabitManager:dealCustomEvent CLEA2_DRIVER_HABIT_RESULT_EVENT
    08-25 12:55:22.735  5428  5428 I com.patac.hmi.user-UserAccount: UserFeatureManager:isMcuEnableDriverHabit mIsMcuEnableDriverHabit = true
    08-25 12:55:22.735   732   732 I Calibrationd: [532501538040]CalibrationUsageLog.cpp::logUsage(34): Calibration Requested: com.patac.hmi.user: GMModel: ENUMERATION: [Module]GMModel: ENUMERATION: 84
    08-25 12:55:22.736  5428  5428 I com.patac.hmi.user-UserAccount: CalibrationDataSource:Calibration:MODEL=84

L17433     08-25 12:55:22.805  5428  5704 I com.patac.hmi.user-UserAccount: DriverHabitMessageHandle:sendDriverHabitEvent afterCheck
    08-25 12:55:22.805  5428  5704 I com.patac.hmi.user-UserAccount: SystemInfoRepository:sendSystemEvent type is 4 id is  4201
    08-25 12:55:22.805  5428  5428 I com.patac.hmi.user-UserAccount: UserApplicationManager:get system event 4201
>>> 08-25 12:55:22.805  5428  5428 I com.patac.hmi.user-UserAccount: CleaNewDriverHabitManager:dealCustomEvent CLEA_DRIVER_HABIT_DATA_EVENT
    08-25 12:55:22.805  5428  5428 I com.patac.hmi.user-UserAccount: DriverHabitInfoUnit:updateCurrentHabitInfo
    08-25 12:55:22.805  5428  5428 I com.patac.hmi.user-UserAccount: UserFeatureManager:isMcuEnableDriverHabit mIsMcuEnableDriverHabit = true
    08-25 12:55:22.805  5428  5428 I com.patac.hmi.user-UserAccount: CleaNewDriverHabitManager:dealDriverHabitDataEvent mHabitRestoreResult is null

L17475     08-25 12:55:22.913  5428  5704 I com.patac.hmi.user-UserAccount: DriverHabitMessageHandle:sendDriverHabitEvent afterCheck
    08-25 12:55:22.914  5428  5704 I com.patac.hmi.user-UserAccount: SystemInfoRepository:sendSystemEvent type is 4 id is  4201
    08-25 12:55:22.914  5428  5428 I com.patac.hmi.user-UserAccount: UserApplicationManager:get system event 4201
>>> 08-25 12:55:22.914  5428  5428 I com.patac.hmi.user-UserAccount: CleaNewDriverHabitManager:dealCustomEvent CLEA_DRIVER_HABIT_DATA_EVENT
    08-25 12:55:22.914  5428  5428 I com.patac.hmi.user-UserAccount: DriverHabitInfoUnit:updateCurrentHabitInfo
    08-25 12:55:22.914  5428  5428 I com.patac.hmi.user-UserAccount: UserFeatureManager:isMcuEnableDriverHabit mIsMcuEnableDriverHabit = true
    08-25 12:55:22.914  5428  5428 I com.patac.hmi.user-UserAccount: CleaNewDriverHabitManager:dealDriverHabitDataEvent mHabitRestoreResult is null

L17527     08-25 12:55:23.030  5428  5704 I com.patac.hmi.user-UserAccount: SystemInfoRepository:sendSystemEvent type is 4 id is  4201
    08-25 12:55:23.030  4112  5150 D SDV_CoreService: [SomeIpTopicReceiverManager]topic 2533279085461923
    08-25 12:55:23.030  5428  5428 I com.patac.hmi.user-UserAccount: UserApplicationManager:get system event 4201
>>> 08-25 12:55:23.030  5428  5428 I com.patac.hmi.user-UserAccount: CleaNewDriverHabitManager:dealCustomEvent CLEA_DRIVER_HABIT_DATA_EVENT
    08-25 12:55:23.030  5428  5428 I com.patac.hmi.user-UserAccount: DriverHabitInfoUnit:updateCurrentHabitInfo
    08-25 12:55:23.030  5428  5428 I com.patac.hmi.user-UserAccount: UserFeatureManager:isMcuEnableDriverHabit mIsMcuEnableDriverHabit = true
    08-25 12:55:23.030  5428  5428 I com.patac.hmi.user-UserAccount: CleaNewDriverHabitManager:dealDriverHabitDataEvent mHabitRestoreResult is null

L17580     08-25 12:55:23.035  5428  5743 I com.patac.hmi.user-UserAccount: DriverHabitMessageHandle:dealDriverMirrorFeedbackEvent 主驾后视镜反馈 is 0
    08-25 12:55:23.035  5428  5743 I com.patac.hmi.user-UserAccount: SystemInfoRepository:sendSystemEvent type is 4 id is  4202
    08-25 12:55:23.035  5428  5428 I com.patac.hmi.user-UserAccount: UserApplicationManager:get system event 4202
>>> 08-25 12:55:23.035  5428  5428 I com.patac.hmi.user-UserAccount: CleaNewDriverHabitManager:dealCustomEvent CLEA2_DRIVER_HABIT_RESULT_EVENT
    08-25 12:55:23.035  5428  5428 I com.patac.hmi.user-UserAccount: UserFeatureManager:isMcuEnableDriverHabit mIsMcuEnableDriverHabit = true
    08-25 12:55:23.035   732   732 I Calibrationd: [532501538040]CalibrationUsageLog.cpp::logUsage(34): Calibration Requested: com.patac.hmi.user: GMModel: ENUMERATION: [Module]GMModel: ENUMERATION: 84
    08-25 12:55:23.036  5428  5428 I com.patac.hmi.user-UserAccount: CalibrationDataSource:Calibration:MODEL=84

L17636     08-25 12:55:23.137  5428  5704 I com.patac.hmi.user-UserAccount: DriverHabitMessageHandle:sendDriverHabitEvent afterCheck
    08-25 12:55:23.137  5428  5704 I com.patac.hmi.user-UserAccount: SystemInfoRepository:sendSystemEvent type is 4 id is  4201
    08-25 12:55:23.137  5428  5428 I com.patac.hmi.user-UserAccount: UserApplicationManager:get system event 4201
>>> 08-25 12:55:23.137  5428  5428 I com.patac.hmi.user-UserAccount: CleaNewDriverHabitManager:dealCustomEvent CLEA_DRIVER_HABIT_DATA_EVENT
    08-25 12:55:23.137  5428  5428 I com.patac.hmi.user-UserAccount: DriverHabitInfoUnit:updateCurrentHabitInfo
    08-25 12:55:23.137  5428  5428 I com.patac.hmi.user-UserAccount: UserFeatureManager:isMcuEnableDriverHabit mIsMcuEnableDriverHabit = true
    08-25 12:55:23.137  5428  5428 I com.patac.hmi.user-UserAccount: CleaNewDriverHabitManager:dealDriverHabitDataEvent mHabitRestoreResult is null

L17672     08-25 12:55:23.245  5428  5704 I com.patac.hmi.user-UserAccount: DriverHabitMessageHandle:sendDriverHabitEvent afterCheck
    08-25 12:55:23.245  5428  5704 I com.patac.hmi.user-UserAccount: SystemInfoRepository:sendSystemEvent type is 4 id is  4201
    08-25 12:55:23.245  5428  5428 I com.patac.hmi.user-UserAccount: UserApplicationManager:get system event 4201
>>> 08-25 12:55:23.245  5428  5428 I com.patac.hmi.user-UserAccount: CleaNewDriverHabitManager:dealCustomEvent CLEA_DRIVER_HABIT_DATA_EVENT
    08-25 12:55:23.245  5428  5428 I com.patac.hmi.user-UserAccount: DriverHabitInfoUnit:updateCurrentHabitInfo
    08-25 12:55:23.245  5428  5428 I com.patac.hmi.user-UserAccount: UserFeatureManager:isMcuEnableDriverHabit mIsMcuEnableDriverHabit = true
    08-25 12:55:23.245  5428  5428 I com.patac.hmi.user-UserAccount: CleaNewDriverHabitManager:dealDriverHabitDataEvent mHabitRestoreResult is null

⚠️ 搜索结果高度重复: 共 40 条匹配中，有 30 条内容相同 ('')。以上仅展示 15 条代表性结果。

---

[结果 3] 搜索结果: 共 40 条匹配，显示 15 条

L17085     08-25 12:55:22.439  4515  5201 I com.patac.hmi.settings-BaseTopicHandler: registerEventListener
    08-25 12:55:22.439  4515  5201 I com.patac.hmi.settings-BaseTopicHandler: result is not null
    08-25 12:55:22.439  4515  5201 I com.patac.hmi.settings-RearviewMirrorAdjustTopic: 32773--->makeResult: name: "OSRVM.left"
>>> 08-25 12:55:22.439  4515  5201 I com.patac.hmi.settings-RearviewMirrorAdjustTopic: responding_feature: MF_TILT_MIRROR
    08-25 12:55:22.439  4515  5201 I com.patac.hmi.settings-RearviewMirrorAdjustTopic: horizontal_angle: -0.2
    08-25 12:55:22.439  4515  5201 I com.patac.hmi.settings-RearviewMirrorAdjustTopic: vertical_angle: -5.6
    08-25 12:55:22.439  4515  5201 I com.patac.hmi.settings-RearviewMirrorAdjustTopic: is_supported: true

L22143     08-25 12:55:30.602  5428  5743 I com.patac.hmi.user-UserAccount: SystemInfoRepository:sendSystemEvent type is 4 id is  4202
    08-25 12:55:30.602  4515  5201 I com.patac.hmi.settings-RightRearviewMirrorAvailableTopic: 32774--->makeResult: name: "OSRVM.right"
    08-25 12:55:30.602  5428  5428 I com.patac.hmi.user-UserAccount: UserApplicationManager:get system event 4202
>>> 08-25 12:55:30.602  4515  5201 I com.patac.hmi.settings-RightRearviewMirrorAvailableTopic: responding_feature: MF_TILT_MIRROR
    08-25 12:55:30.602  4515  5201 I com.patac.hmi.settings-RightRearviewMirrorAvailableTopic: vertical_angle: -5.2
    08-25 12:55:30.602  4515  5201 I com.patac.hmi.settings-RightRearviewMirrorAvailableTopic: is_supported: true
    08-25 12:55:30.602  4515  5201 I com.patac.hmi.settings-RightRearviewMirrorAvailableTopic: , cacheData = Result{mBoolValue=true, mIntValue=0, mFloatValue=0.0, mState=0, mObject=null, mAvailable=1}

L22593     08-25 12:55:31.481  4515  5201 I com.patac.hmi.settings-BaseTopicHandler: result is not null
    08-25 12:55:31.481  5428  7822 D [ClsLinkSDK-v0.0.27] ClsLink: dispatchCloudEvent {id='1f1a0413-3092-697b-8f77-f3ea29b5da50'}; type=pub.v1
    08-25 12:55:31.481  4515  5201 I com.patac.hmi.settings-RightRearviewMirrorAvailableTopic: 32774--->makeResult: name: "OSRVM.right"
>>> 08-25 12:55:31.481  4515  5201 I com.patac.hmi.settings-RightRearviewMirrorAvailableTopic: responding_feature: MF_TILT_MIRROR
    08-25 12:55:31.481  4515  5201 I com.patac.hmi.settings-RightRearviewMirrorAvailableTopic: horizontal_angle: 0.1
    08-25 12:55:31.481  4515  5201 I com.patac.hmi.settings-RightRearviewMirrorAvailableTopic: vertical_angle: -5.2
    08-25 12:55:31.481  4515  5201 I com.patac.hmi.settings-RightRearviewMirrorAvailableTopic: is_supported: true

L22878     08-25 12:55:32.082  5428  5743 I com.patac.hmi.user-UserAccount: DriverHabitMessageHandle:dealPassengerMirrorFeedbackEvent 副驾后视镜反馈 is 2
    08-25 12:55:32.082  5428  5743 I com.patac.hmi.user-UserAccount: SystemInfoRepository:sendSystemEvent type is 4 id is  4202
    08-25 12:55:32.082  4515  5201 I com.patac.hmi.settings-RightRearviewMirrorAvailableTopic: 32774--->makeResult: name: "OSRVM.right"
>>> 08-25 12:55:32.082  4515  5201 I com.patac.hmi.settings-RightRearviewMirrorAvailableTopic: responding_feature: MF_TILT_MIRROR
    08-25 12:55:32.082  4515  5201 I com.patac.hmi.settings-RightRearviewMirrorAvailableTopic: vertical_angle: -5.2
    08-25 12:55:32.082  4515  5201 I com.patac.hmi.settings-RightRearviewMirrorAvailableTopic: is_supported: true
    08-25 12:55:32.082  4515  5201 I com.patac.hmi.settings-RightRearviewMirrorAvailableTopic: , cacheData = Result{mBoolValue=true, mIntValue=0, mFloatValue=0.0, mState=0, mObject=null, mAvailable=1}

L23248     08-25 12:55:32.988  4515  5201 I com.patac.hmi.settings-RightRearviewMirrorAvailableTopic: 32774--->makeResult: name: "OSRVM.right"
    08-25 12:55:32.988  5428  5428 I com.patac.hmi.user-UserAccount: UserApplicationManager:get system event 4202
    08-25 12:55:32.988  5428  5428 I com.patac.hmi.user-UserAccount: CleaNewDriverHabitManager:dealCustomEvent CLEA2_DRIVER_HABIT_RESULT_EVENT
>>> 08-25 12:55:32.988  4515  5201 I com.patac.hmi.settings-RightRearviewMirrorAvailableTopic: responding_feature: MF_TILT_MIRROR
    08-25 12:55:32.988  5428  5428 I com.patac.hmi.user-UserAccount: UserFeatureManager:isMcuEnableDriverHabit mIsMcuEnableDriverHabit = true
    08-25 12:55:32.988  4515  5201 I com.patac.hmi.settings-RightRearviewMirrorAvailableTopic: horizontal_angle: 0.1
    08-25 12:55:32.988  4515  5201 I com.patac.hmi.settings-RightRearviewMirrorAvailableTopic: vertical_angle: -5.2

L23390     08-25 12:55:33.288  4515  5201 I com.patac.hmi.settings-BaseTopicHandler: registerEventListener
    08-25 12:55:33.288  4515  5201 I com.patac.hmi.settings-BaseTopicHandler: result is not null
    08-25 12:55:33.288  4515  5201 I com.patac.hmi.settings-RightRearviewMirrorAvailableTopic: 32774--->makeResult: name: "OSRVM.right"
>>> 08-25 12:55:33.288  4515  5201 I com.patac.hmi.settings-RightRearviewMirrorAvailableTopic: responding_feature: MF_TILT_MIRROR
    08-25 12:55:33.288  4515  5201 I com.patac.hmi.settings-RightRearviewMirrorAvailableTopic: vertical_angle: -5.2
    08-25 12:55:33.288  4515  5201 I com.patac.hmi.settings-RightRearviewMirrorAvailableTopic: is_supported: true
    08-25 12:55:33.288  4515  5201 I com.patac.hmi.settings-RightRearviewMirrorAvailableTopic: , cacheData = Result{mBoolValue=true, mIntValue=0, mFloatValue=0.0, mState=0, mObject=null, mAvailable=1}

L69463     08-25 12:56:33.932  4515  5201 I com.patac.hmi.settings-BaseTopicHandler: registerEventListener
    08-25 12:56:33.933  4515  5201 I com.patac.hmi.settings-BaseTopicHandler: result is not null
    08-25 12:56:33.934  4515  5201 I com.patac.hmi.settings-RightRearviewMirrorAvailableTopic: 32774--->makeResult: name: "OSRVM.right"
>>> 08-25 12:56:33.934  4515  5201 I com.patac.hmi.settings-RightRearviewMirrorAvailableTopic: responding_feature: MF_TILT_MIRROR
    08-25 12:56:33.934  4515  5201 I com.patac.hmi.settings-RightRearviewMirrorAvailableTopic: horizontal_angle: 0.3
    08-25 12:56:33.934  4515  5201 I com.patac.hmi.settings-RightRearviewMirrorAvailableTopic: vertical_angle: 4.9
    08-25 12:56:33.934  4515  5201 I com.patac.hmi.settings-RightRearviewMirrorAvailableTopic: is_allowed: true

L69609     08-25 12:56:34.204  5428  5428 I com.patac.hmi.user-UserAccount: CleaNewDriverHabitManager:dealCustomEvent CLEA2_DRIVER_HABIT_RESULT_EVENT
    08-25 12:56:34.205  5428  5428 I com.patac.hmi.user-UserAccount: UserFeatureManager:isMcuEnableDriverHabit mIsMcuEnableDriverHabit = true
    08-25 12:56:34.205  4515  5201 I com.patac.hmi.settings-RightRearviewMirrorAvailableTopic: 32774--->makeResult: name: "OSRVM.right"
>>> 08-25 12:56:34.205  4515  5201 I com.patac.hmi.settings-RightRearviewMirrorAvailableTopic: responding_feature: MF_TILT_MIRROR
    08-25 12:56:34.205  4515  5201 I com.patac.hmi.settings-RightRearviewMirrorAvailableTopic: horizontal_angle: 0.1
    08-25 12:56:34.205  4515  5201 I com.patac.hmi.settings-RightRearviewMirrorAvailableTopic: vertical_angle: 4.9
    08-25 12:56:34.205   732   732 I Calibrationd: [532501538040]CalibrationUsageLog.cpp::logUsage(34): Calibration Requested: com.patac.hmi.user: GMModel: ENUMERATION: [Module]GMModel: ENUMERATION: 84

L69694     08-25 12:56:34.234  4515  5201 I com.patac.hmi.settings-BaseTopicHandler: registerEventListener
    08-25 12:56:34.234  4515  5201 I com.patac.hmi.settings-BaseTopicHandler: result is not null
    08-25 12:56:34.234  4515  5201 I com.patac.hmi.settings-RightRearviewMirrorAvailableTopic: 32774--->makeResult: name: "OSRVM.right"
>>> 08-25 12:56:34.234  4515  5201 I com.patac.hmi.settings-RightRearviewMirrorAvailableTopic: responding_feature: MF_TILT_MIRROR
    08-25 12:56:34.234  4515  5201 I com.patac.hmi.settings-RightRearviewMirrorAvailableTopic: horizontal_angle: 0.1
    08-25 12:56:34.234  4515  5201 I com.patac.hmi.settings-RightRearviewMirrorAvailableTopic: vertical_angle: 4.9
    08-25 12:56:34.234  4515  5201 I com.patac.hmi.settings-RightRearviewMirrorAvailableTopic: is_supported: true

L70003     08-25 12:56:34.504  5428  5743 I com.patac.hmi.user-UserAccount: DriverHabitMessageHandle:dealPassengerMirrorFeedbackEvent 副驾后视镜反馈 is 2
    08-25 12:56:34.504  5428  5743 I com.patac.hmi.user-UserAccount: SystemInfoRepository:sendSystemEvent type is 4 id is  4202
    08-25 12:56:34.504  4515  5201 I com.patac.hmi.settings-RightRearviewMirrorAvailableTopic: 32774--->makeResult: name: "OSRVM.right"
>>> 08-25 12:56:34.504  4515  5201 I com.patac.hmi.settings-RightRearviewMirrorAvailableTopic: responding_feature: MF_TILT_MIRROR
    08-25 12:56:34.504  4515  5201 I com.patac.hmi.settings-RightRearviewMirrorAvailableTopic: horizontal_angle: -0.1
    08-25 12:56:34.504  4515  5201 I com.patac.hmi.settings-RightRearviewMirrorAvailableTopic: vertical_angle: 4.4
    08-25 12:56:34.504  4515  5201 I com.patac.hmi.settings-RightRearviewMirrorAvailableTopic: is_supported: true

L70179     08-25 12:56:34.806  5428  5428 I com.patac.hmi.user-UserAccount: UserApplicationManager:get system event 4202
    08-25 12:56:34.806  4515  5201 I com.patac.hmi.settings-RightRearviewMirrorAvailableTopic: 32774--->makeResult: name: "OSRVM.right"
    08-25 12:56:34.806  5428  5428 I com.patac.hmi.user-UserAccount: CleaNewDriverHabitManager:dealCustomEvent CLEA2_DRIVER_HABIT_RESULT_EVENT
>>> 08-25 12:56:34.806  4515  5201 I com.patac.hmi.settings-RightRearviewMirrorAvailableTopic: responding_feature: MF_TILT_MIRROR
    08-25 12:56:34.806  4515  5201 I com.patac.hmi.settings-RightRearviewMirrorAvailableTopic: horizontal_angle: -0.1
    08-25 12:56:34.806  4515  5201 I com.patac.hmi.settings-RightRearviewMirrorAvailableTopic: vertical_angle: 3.3
    08-25 12:56:34.806  4515  5201 I com.patac.hmi.settings-RightRearviewMirrorAvailableTopic: is_supported: true

L70325     08-25 12:56:35.106  5428  5743 I com.patac.hmi.user-UserAccount: DriverHabitMessageHandle:dealPassengerMirrorFeedbackEvent 副驾后视镜反馈 is 2
    08-25 12:56:35.106  5428  5743 I com.patac.hmi.user-UserAccount: SystemInfoRepository:sendSystemEvent type is 4 id is  4202
    08-25 12:56:35.107  4515  5201 I com.patac.hmi.settings-RightRearviewMirrorAvailableTopic: 32774--->makeResult: name: "OSRVM.right"
>>> 08-25 12:56:35.107  4515  5201 I com.patac.hmi.settings-RightRearviewMirrorAvailableTopic: responding_feature: MF_TILT_MIRROR
    08-25 12:56:35.107  5428  5428 I com.patac.hmi.user-UserAccount: UserApplicationManager:get system event 4202
    08-25 12:56:35.107  4515  5201 I com.patac.hmi.settings-RightRearviewMirrorAvailableTopic: horizontal_angle: -0.1
    08-25 12:56:35.107  4515  5201 I com.patac.hmi.settings-RightRearviewMirrorAvailableTopic: vertical_angle: 2.5

L70515     08-25 12:56:35.414  5428  5428 I com.patac.hmi.user-UserAccount: CleaNewDriverHabitManager:dealDriverHabitResultEvent: seatResult is 0 leftMirrorResult is 0 rightMirrorResult is 0 mDriverMirrorFeedback 0 mPassengerMirrorFeedback 2
    08-25 12:56:35.414  5428  5428 I com.patac.hmi.user-UserAccount: CleaNewDriverHabitManager:dealDriverHabitResultEvent mRestoreDriverHabitFlow is null
    08-25 12:56:35.414  4515  5201 I com.patac.hmi.settings-RightRearviewMirrorAvailableTopic: 32774--->makeResult: name: "OSRVM.right"
>>> 08-25 12:56:35.414  4515  5201 I com.patac.hmi.settings-RightRearviewMirrorAvailableTopic: responding_feature: MF_TILT_MIRROR
    08-25 12:56:35.414  4515  5201 I com.patac.hmi.settings-RightRearviewMirrorAvailableTopic: horizontal_angle: -0.1
    08-25 12:56:35.414  4515  5201 I com.patac.hmi.settings-RightRearviewMirrorAvailableTopic: vertical_angle: 1.4
    08-25 12:56:35.414  4515  5201 I com.patac.hmi.settings-RightRearviewMirrorAvailableTopic: is_supported: true

L70662     08-25 12:56:35.711  5428  5743 I com.patac.hmi.user-UserAccount: SystemInfoRepository:sendSystemEvent type is 4 id is  4202
    08-25 12:56:35.712  4515  5201 I com.patac.hmi.settings-RightRearviewMirrorAvailableTopic: 32774--->makeResult: name: "OSRVM.right"
    08-25 12:56:35.712  5428  5428 I com.patac.hmi.user-UserAccount: UserApplicationManager:get system event 4202
>>> 08-25 12:56:35.712  4515  5201 I com.patac.hmi.settings-RightRearviewMirrorAvailableTopic: responding_feature: MF_TILT_MIRROR
    08-25 12:56:35.712  5428  5428 I com.patac.hmi.user-UserAccount: CleaNewDriverHabitManager:dealCustomEvent CLEA2_DRIVER_HABIT_RESULT_EVENT
    08-25 12:56:35.712  4515  5201 I com.patac.hmi.settings-RightRearviewMirrorAvailableTopic: horizontal_angle: -0.1
    08-25 12:56:35.712  5428  5428 I com.patac.hmi.user-UserAccount: UserFeatureManager:isMcuEnableDriverHabit mIsMcuEnableDriverHabit = true

L70819     08-25 12:56:36.015  5428  5743 I com.patac.hmi.user-UserAccount: RightMirrorFeatureHandle:dealDataChange data feature is 2
    08-25 12:56:36.015  5428  5743 I com.patac.hmi.user-UserAccount: SomeIpModule:dealRightMirrorFeatureChange 右后视镜反馈值 = 2
    08-25 12:56:36.015  4515  5201 I com.patac.hmi.settings-RightRearviewMirrorAvailableTopic: 32774--->makeResult: name: "OSRVM.right"
>>> 08-25 12:56:36.015  4515  5201 I com.patac.hmi.settings-RightRearviewMirrorAvailableTopic: responding_feature: MF_TILT_MIRROR
    08-25 12:56:36.015  5428  5743 I com.patac.hmi.user-UserAccount: DriverHabitMessageHandle:dealPassengerMirrorFeedbackEvent 副驾后视镜反馈 is 2
    08-25 12:56:36.015  4515  5201 I com.patac.hmi.settings-RightRearviewMirrorAvailableTopic: horizontal_angle: -0.1
    08-25 12:56:36.015  5428  5743 I com.patac.hmi.user-UserAccount: SystemInfoRepository:sendSystemEvent type is 4 id is  4202

⚠️ 搜索结果高度重复: 共 40 条匹配中，有 30 条内容相同 ('')。以上仅展示 15 条代表性结果。

---

## 第 7 轮 — LLM 响应

关键发现：`CleaNewDriverHabitManager:dealDriverHabitDataEvent mHabitRestoreResult is null` 出现了两次（12:55:22.477 和 12:55:22.581）。这非常关键——`mHabitRestoreResult is null` 说明记忆恢复结果为空。

让我深入理解这个记忆恢复流程，以及 `mHabitRestoreResult` 为 null 的含义。



---

## 第 7 轮 — 工具执行结果

[结果 1] 搜索结果: 共 40 条匹配，显示 15 条

L17080     08-25 12:55:22.434   732   732 I Calibrationd: [532501538040]CalibrationUsageLog.cpp::logUsage(34): Calibration Requested: com.patac.hmi.user: GMModel: ENUMERATION: [Module]GMModel: ENUMERATION: 84
    08-25 12:55:22.434  5428  5428 I com.patac.hmi.user-UserAccount: CalibrationDataSource:Calibration:MODEL=84
    08-25 12:55:22.434  5428  5428 I com.patac.hmi.user-UserAccount: UserFeatureManager:isModelTypeE22 isE22 = false
>>> 08-25 12:55:22.434  5428  5428 I com.patac.hmi.user-UserAccount: CleaNewDriverHabitManager:dealDriverHabitResultEvent: seatResult is 0 leftMirrorResult is 0 rightMirrorResult is 0 mDriverMirrorFeedback 2 mPassengerMirrorFeedback 0
    08-25 12:55:22.434  5428  5428 I com.patac.hmi.user-UserAccount: CleaNewDriverHabitManager:dealDriverHabitResultEvent mRestoreDriverHabitFlow is null
    08-25 12:55:22.439  4515  5201 I com.patac.hmi.settings-BaseTopicHandler: registerEventListener
    08-25 12:55:22.439  4515  5201 I com.patac.hmi.settings-BaseTopicHandler: result is not null

L17155     08-25 12:55:22.456   732   732 I Calibrationd: [532501538040]CalibrationUsageLog.cpp::logUsage(34): Calibration Requested: com.patac.hmi.user: GMModel: ENUMERATION: [Module]GMModel: ENUMERATION: 84
    08-25 12:55:22.457  5428  5428 I com.patac.hmi.user-UserAccount: CalibrationDataSource:Calibration:MODEL=84
    08-25 12:55:22.457  5428  5428 I com.patac.hmi.user-UserAccount: UserFeatureManager:isModelTypeE22 isE22 = false
>>> 08-25 12:55:22.457  5428  5428 I com.patac.hmi.user-UserAccount: CleaNewDriverHabitManager:dealDriverHabitResultEvent: seatResult is 0 leftMirrorResult is 0 rightMirrorResult is 0 mDriverMirrorFeedback 0 mPassengerMirrorFeedback 0
    08-25 12:55:22.457  4515  5201 I com.patac.hmi.settings-RearviewMirrorAdjustTopic: 32773--->makeResult: name: "OSRVM.left"
    08-25 12:55:22.457  5428  5428 I com.patac.hmi.user-UserAccount: CleaNewDriverHabitManager:dealDriverHabitResultEvent mRestoreDriverHabitFlow is null
    08-25 12:55:22.457  4515  5201 I com.patac.hmi.settings-RearviewMirrorAdjustTopic: horizontal_angle: -0.2

L17176     08-25 12:55:22.477  5428  5428 I com.patac.hmi.user-UserAccount: CleaNewDriverHabitManager:dealCustomEvent CLEA_DRIVER_HABIT_DATA_EVENT
    08-25 12:55:22.477  5428  5428 I com.patac.hmi.user-UserAccount: DriverHabitInfoUnit:updateCurrentHabitInfo
    08-25 12:55:22.477  5428  5428 I com.patac.hmi.user-UserAccount: UserFeatureManager:isMcuEnableDriverHabit mIsMcuEnableDriverHabit = true
>>> 08-25 12:55:22.477  5428  5428 I com.patac.hmi.user-UserAccount: CleaNewDriverHabitManager:dealDriverHabitDataEvent mHabitRestoreResult is null
    08-25 12:55:22.479  2371  2371 D PatacSwcHandlingService: diapatch KeyEvent KeyEvent { action=ACTION_DOWN, keyCode=KEYCODE_VOLUME_DOWN, scanCode=0, metaState=0, flags=0x0, repeatCount=6, eventTime=2369794000000, downTime=2369794000000, deviceId=0, source=0x101, displayId=0 } to HardKeyClient Callbac
    08-25 12:55:22.479  1089  7406 I Bosch_NavSensors: GyrUn:[-0.000266, -0.001332, 0.000799, 0.000000, 0.000000, 0.000000, 1713957]
    08-25 12:55:22.480  4515  5408 D HardKeyInterceptorManager: dispatchKeyEvent event = KeyEvent { action=ACTION_DOWN, keyCode=KEYCODE_VOLUME_DOWN, scanCode=0, metaState=0, flags=0x0, repeatCount=6, eventTime=2369794000000, downTime=2369794000000, deviceId=0, source=0x101, displayId=0 }

L17223     08-25 12:55:22.581  5428  5704 I com.patac.hmi.user-UserAccount: SystemInfoRepository:sendSystemEvent type is 4 id is  4201
    08-25 12:55:22.581  5428  5428 I com.patac.hmi.user-UserAccount: DriverHabitInfoUnit:updateCurrentHabitInfo
    08-25 12:55:22.581  5428  5428 I com.patac.hmi.user-UserAccount: UserFeatureManager:isMcuEnableDriverHabit mIsMcuEnableDriverHabit = true
>>> 08-25 12:55:22.581  5428  5428 I com.patac.hmi.user-UserAccount: CleaNewDriverHabitManager:dealDriverHabitDataEvent mHabitRestoreResult is null
    08-25 12:55:22.581  5428  5428 I com.patac.hmi.user-UserAccount: UserApplicationManager:get system event 4201
    08-25 12:55:22.581  5428  5428 I com.patac.hmi.user-UserAccount: CleaNewDriverHabitManager:dealCustomEvent CLEA_DRIVER_HABIT_DATA_EVENT
    08-25 12:55:22.581  5428  5428 I com.patac.hmi.user-UserAccount: DriverHabitInfoUnit:updateCurrentHabitInfo

L17290     08-25 12:55:22.688  5428  5428 I com.patac.hmi.user-UserAccount: CleaNewDriverHabitManager:dealCustomEvent CLEA_DRIVER_HABIT_DATA_EVENT
    08-25 12:55:22.688  5428  5428 I com.patac.hmi.user-UserAccount: DriverHabitInfoUnit:updateCurrentHabitInfo
    08-25 12:55:22.688  5428  5428 I com.patac.hmi.user-UserAccount: UserFeatureManager:isMcuEnableDriverHabit mIsMcuEnableDriverHabit = true
>>> 08-25 12:55:22.688  5428  5428 I com.patac.hmi.user-UserAccount: CleaNewDriverHabitManager:dealDriverHabitDataEvent mHabitRestoreResult is null
    08-25 12:55:22.691  4156  4156 I com.patac.hmi.media-ProgressHelper: [ProgressHelper]-PlaybackState is null:true,MediaInfo is null:true
    08-25 12:55:22.691  4156  4156 D com.patac.hmi.media-BTAudioManager: mPlayStateEmitter is null,Do nothing Or state is fast ward/rewind
    08-25 12:55:22.714  1089  7403 I Bosch_NavSensors: GnssSourceVIP::readerThread ipc_read ret time s 22 ms 999

L17375     08-25 12:55:22.731   732   732 I Calibrationd: [532501538040]CalibrationUsageLog.cpp::logUsage(34): Calibration Requested: com.patac.hmi.user: GMModel: ENUMERATION: [Module]GMModel: ENUMERATION: 84
    08-25 12:55:22.732  5428  5428 I com.patac.hmi.user-UserAccount: CalibrationDataSource:Calibration:MODEL=84
    08-25 12:55:22.732  5428  5428 I com.patac.hmi.user-UserAccount: UserFeatureManager:isModelTypeE22 isE22 = false
>>> 08-25 12:55:22.732  5428  5428 I com.patac.hmi.user-UserAccount: CleaNewDriverHabitManager:dealDriverHabitResultEvent: seatResult is 0 leftMirrorResult is 0 rightMirrorResult is 0 mDriverMirrorFeedback 0 mPassengerMirrorFeedback 0
    08-25 12:55:22.732  5428  5428 I com.patac.hmi.user-UserAccount: CleaNewDriverHabitManager:dealDriverHabitResultEvent mRestoreDriverHabitFlow is null
    08-25 12:55:22.732  4112  5115 D TimeResult: SystemClock: 3603273, ElapsedRealtimeMillis: 1892235
    08-25 12:55:22.732  4112  5115 D TimeResult: mTimeMillis: 1787632011696, AgeMillis: 1711038

L17405     08-25 12:55:22.735   732   732 I Calibrationd: [532501538040]CalibrationUsageLog.cpp::logUsage(34): Calibration Requested: com.patac.hmi.user: GMModel: ENUMERATION: [Module]GMModel: ENUMERATION: 84
    08-25 12:55:22.736  5428  5428 I com.patac.hmi.user-UserAccount: CalibrationDataSource:Calibration:MODEL=84
    08-25 12:55:22.736  5428  5428 I com.patac.hmi.user-UserAccount: UserFeatureManager:isModelTypeE22 isE22 = false
>>> 08-25 12:55:22.736  5428  5428 I com.patac.hmi.user-UserAccount: CleaNewDriverHabitManager:dealDriverHabitResultEvent: seatResult is 0 leftMirrorResult is 0 rightMirrorResult is 0 mDriverMirrorFeedback 0 mPassengerMirrorFeedback 0
    08-25 12:55:22.736  5428  5428 I com.patac.hmi.user-UserAccount: CleaNewDriverHabitManager:dealDriverHabitResultEvent mRestoreDriverHabitFlow is null
    08-25 12:55:22.740  1371  1476 D GMVHAL  : setPropFromVehicle Property: VendorProperty::LOCAL_TIME AreaID: 16777216 Status: 0 int32Values: 2026 8 25 12 55 22 
    08-25 12:55:22.740  1371  1476 D GMVHAL  : setPropFromVehicle Property: VendorProperty::UTC AreaID: 16777216 Status: 0 int32Values: 2026 8 25 4 55 22 

L17436     08-25 12:55:22.805  5428  5428 I com.patac.hmi.user-UserAccount: CleaNewD

... [截断: 原始结果 15,427 字符，已截取中间 427 字符] ...

DataEvent mHabitRestoreResult is null
    08-25 12:55:22.807  1368  3139 I         : VSIP: cei::rcb (Success): 00 01 80 fb 00 00 00 20 00 00 51 2a 01 01 02 00 01 00 00 00 00 00 00 00 00 4a 18 00 00 00 00 00 00 00 00 00 02 08 54 00 
    08-25 12:55:22.813  1089  7403 I Bosch_NavSensors: GnssSourceVIP::readerThread ipc_read ret time s 23 ms 80
    08-25 12:55:22.813  1089  1373 D Bosch_NavSensors: Nmea: 1787633723080 : $GPGGA,045523.08,3120.158739,N,12047.433599,E,1,10,0.0,24.7,M,,M,,*4F

L17478     08-25 12:55:22.914  5428  5428 I com.patac.hmi.user-UserAccount: CleaNewDriverHabitManager:dealCustomEvent CLEA_DRIVER_HABIT_DATA_EVENT
    08-25 12:55:22.914  5428  5428 I com.patac.hmi.user-UserAccount: DriverHabitInfoUnit:updateCurrentHabitInfo
    08-25 12:55:22.914  5428  5428 I com.patac.hmi.user-UserAccount: UserFeatureManager:isMcuEnableDriverHabit mIsMcuEnableDriverHabit = true
>>> 08-25 12:55:22.914  5428  5428 I com.patac.hmi.user-UserAccount: CleaNewDriverHabitManager:dealDriverHabitDataEvent mHabitRestoreResult is null
    08-25 12:55:22.925  1371  1443 D GMVHAL  : void KeyInputPropertyManager::onLongPressRepeatDelay(const std::vector<int32_t> &)
    08-25 12:55:22.925  1371  1443 D GMVHAL  : setPropFromVehicle Property: VehicleProperty::HW_KEY_INPUT AreaID: 16777216 Status: 0 int32Values: 0 25 0 
    08-25 12:55:22.925  2150  2234 D CAR.INPUT: hal event code: 25, action: 0, display: 0, number of indents: 1

L17530     08-25 12:55:23.030  5428  5428 I com.patac.hmi.user-UserAccount: CleaNewDriverHabitManager:dealCustomEvent CLEA_DRIVER_HABIT_DATA_EVENT
    08-25 12:55:23.030  5428  5428 I com.patac.hmi.user-UserAccount: DriverHabitInfoUnit:updateCurrentHabitInfo
    08-25 12:55:23.030  5428  5428 I com.patac.hmi.user-UserAccount: UserFeatureManager:isMcuEnableDriverHabit mIsMcuEnableDriverHabit = true
>>> 08-25 12:55:23.030  5428  5428 I com.patac.hmi.user-UserAccount: CleaNewDriverHabitManager:dealDriverHabitDataEvent mHabitRestoreResult is null
    08-25 12:55:23.030  4112  5019 D SDV_CoreService: [FrontLeftWindowTopicMapper]someIp sRlVCPWLSCurrSeltnVal: 2 drvWndAval: true drvWndCfg: true
    08-25 12:55:23.031  4112  5150 I SDV_CoreService: [ThirdRowLeftDoorSomeIpTopicMapper]SUCCESS: NOTIFY_BODY_INFORMATION_17
    08-25 12:55:23.031  4112  5150 D SDV_CoreService: [ThirdRowLeftDoorSomeIpTopicMapper]resp.getSRlVCPWLSCurrSeltnVal(): 2

L17585     08-25 12:55:23.035   732   732 I Calibrationd: [532501538040]CalibrationUsageLog.cpp::logUsage(34): Calibration Requested: com.patac.hmi.user: GMModel: ENUMERATION: [Module]GMModel: ENUMERATION: 84
    08-25 12:55:23.036  5428  5428 I com.patac.hmi.user-UserAccount: CalibrationDataSource:Calibration:MODEL=84
    08-25 12:55:23.036  5428  5428 I com.patac.hmi.user-UserAccount: UserFeatureManager:isModelTypeE22 isE22 = false
>>> 08-25 12:55:23.036  5428  5428 I com.patac.hmi.user-UserAccount: CleaNewDriverHabitManager:dealDriverHabitResultEvent: seatResult is 0 leftMirrorResult is 0 rightMirrorResult is 0 mDriverMirrorFeedback 0 mPassengerMirrorFeedback 0
    08-25 12:55:23.036  5428  5428 I com.patac.hmi.user-UserAccount: CleaNewDriverHabitManager:dealDriverHabitResultEvent mRestoreDriverHabitFlow is null
    08-25 12:55:23.056  1371  1476 D GMVHAL  : setPropFromVehicle Property: VendorProperty::POSITION_OFFSET_FROM_TRIM AreaID: 4 Status: 0 floatValues: -8 
    08-25 12:55:23.056  1371  1476 D GMVHAL  : setPropFromVehicle Property: PatacProperty::RIDE_HEIGHT_STATUS_4_SIGNAL_GROUP AreaID: 16777216 Status: 0 int32Values: -15 0 -8 0 -3 0 -18 0 

L17639     08-25 12:55:23.137  5428  5428 I com.patac.hmi.user-UserAccount: CleaNewDriverHabitManager:dealCustomEvent CLEA_DRIVER_HABIT_DATA_EVENT
    08-25 12:55:23.137  5428  5428 I com.patac.hmi.user-UserAccount: DriverHabitInfoUnit:updateCurrentHabitInfo
    08-25 12:55:23.137  5428  5428 I com.patac.hmi.user-UserAccount: UserFeatureManager:isMcuEnableDriverHabit mIsMcuEnableDriverHabit = true
>>> 08-25 12:55:23.137  5428  5428 I com.patac.hmi.user-UserAccount: CleaNewDriverHabitManager:dealDriverHabitDataEvent mHabitRestoreResult is null
    08-25 12:55:23.154  1089  7406 I Bosch_NavSensors: AccUn:[2.530671, -2.707842, 9.045294, 0.000000, 0.000000, 0.000000, 1714628]
    08-25 12:55:23.154  1089  7406 I Bosch_NavSensors: Gravity:[0.000000, -2.668532, 9.436594, 3603695138571]
    08-25 12:55:23.171  2425  7756 D FSANetCommsClient: FSARemoteClient RX QSize is: 0, funcID: 100, ID: 100

L17675     08-25 12:55:23.245  5428  5428 I com.patac.hmi.user-UserAccount: CleaNewDriverHabitManager:dealCustomEvent CLEA_DRIVER_HABIT_DATA_EVENT
    08-25 12:55:23.245  5428  5428 I com.patac.hmi.user-UserAccount: DriverHabitInfoUnit:updateCurrentHabitInfo
    08-25 12:55:23.245  5428  5428 I com.patac.hmi.user-UserAccount: UserFeatureManager:isMcuEnableDriverHabit mIsMcuEnableDriverHabit = true
>>> 08-25 12:55:23.245  5428  5428 I com.patac.hmi.user-UserAccount: CleaNewDriverHabitManager:dealDriverHabitDataEvent mHabitRestoreResult is null
    08-25 12:55:23.262  1089  7406 I Bosch_NavSensors: GyrUn:[0.000266, -0.000533, 0.000266, 0.000000, 0.000000, 0.000000, 1714737]
    08-25 12:55:23.272  1089  7406 I Bosch_NavSensors: AccUn:[2.540248, -2.700660, 9.040505, 0.000000, 0.000000, 0.000000, 1714747]
    08-25 12:55:23.272  1089  7406 I Bosch_NavSensors: Gravity:[0.000000, -2.668957, 9.436475, 3603813344821]

L17774     08-25 12:55:23.339   732   732 I Calibrationd: [532501538040]CalibrationUsageLog.cpp::logUsage(34): Calibration Requested: com.patac.hmi.user: GMModel: ENUMERATION: [Module]GMModel: ENUMERATION: 84
    08-25 12:55:23.339  5428  5428 I com.patac.hmi.user-UserAccount: CalibrationDataSource:Calibration:MODEL=84
    08-25 12:55:23.339  5428  5428 I com.patac.hmi.user-UserAccount: UserFeatureManager:isModelTypeE22 isE22 = false
>>> 08-25 12:55:23.339  5428  5428 I com.patac.hmi.user-UserAccount: CleaNewDriverHabitManager:dealDriverHabitResultEvent: seatResult is 0 leftMirrorResult is 0 rightMirrorResult is 0 mDriverMirrorFeedback 0 mPassengerMirrorFeedback 0
    08-25 12:55:23.339  5428  5428 I com.patac.hmi.user-UserAccount: CleaNewDriverHabitManager:dealDriverHabitResultEvent mRestoreDriverHabitFlow is null
    08-25 12:55:23.361  1371  1476 D GMVHAL  : setPropFromVehicle Property: PatacProperty::MIRROR_POSITION_STATUS AreaID: 1 Status: 0 floatValues: -8.8 -0.2 0 
    08-25 12:55:23.361  1371  1476 D GMVHAL  : setPropFromVehicle Property: PatacProperty::MIRROR_POSITION_STATUS AreaID: 2 Status: 0 floatValues: -5.2 0.1 0 

L17787     08-25 12:55:23.363  5428  5428 I com.patac.hmi.user-UserAccount: DriverHabitInfoUnit:updateCurrentHabitInfo
    08-25 12:55:23.363  5428  5704 I com.patac.hmi.user-UserAccount: DriverHabitMessageHandle:sendDriverHabitEvent afterCheck
    08-25 12:55:23.363  5428  5428 I com.patac.hmi.user-UserAccount: UserFeatureManager:isMcuEnableDriverHabit mIsMcuEnableDriverHabit = true
>>> 08-25 12:55:23.363  5428  5428 I com.patac.hmi.user-UserAccount: CleaNewDriverHabitManager:dealDriverHabitDataEvent mHabitRestoreResult is null
    08-25 12:55:23.364  5428  5704 I com.patac.hmi.user-UserAccount: SystemInfoRepository:sendSystemEvent type is 4 id is  4201
    08-25 12:55:23.364  5428  5428 I com.patac.hmi.user-UserAccount: UserApplicationManager:get system event 4201
    08-25 12:55:23.364  5428  5428 I com.patac.hmi.user-UserAccount: CleaNewDriverHabitManager:dealCustomEvent CLEA_DRIVER_HABIT_DATA_EVENT

⚠️ 搜索结果高度重复: 共 40 条匹配中，有 30 条内容相同 ('')。以上仅展示 15 条代表性结果。

---

[结果 2] 搜索结果: 共 40 条匹配，显示 15 条

L17069     08-25 12:55:22.433  4477  5049 D ServiceBus: [Client] send to cls:/com.patac.hmi.user/; id= 1f1a0412-da52-680f-8f77-f3ea29b5da50
    08-25 12:55:22.433  5428  6558 D [ClsLinkSDK-v0.0.27] ClsLink: dispatchCloudEvent {id='1f1a0412-da52-680f-8f77-f3ea29b5da50'}; type=pub.v1
    08-25 12:55:22.433   928  1562 I GMLoggerService|Archiver: Creating compressed file:  /data/gmlogger/10-main.log_2026_8_25_12_55_22.gz
>>> 08-25 12:55:22.433  5428  5743 I com.patac.hmi.user-UserAccount: LeftMirrorFeatureHandle:result is not null
    08-25 12:55:22.433  5428  5743 I com.patac.hmi.user-UserAccount: LeftMirrorFeatureHandle:dealDataChange data feature is 2
    08-25 12:55:22.433  5428  5743 I com.patac.hmi.user-UserAccount: SomeIpModule:dealLeftMirrorFeatureChange 左后视镜反馈值 = 2
    08-25 12:55:22.433  5428  5743 I com.patac.hmi.user-UserAccount: DriverHabitMessageHandle:dealDriverMirrorFeedbackEvent 主驾后视镜反馈 is 2

L17142     08-25 12:55:22.455  4515  5408 D [ClsLinkSDK-v0.0.33] ClsLink: dispatchCloudEvent {id='1f1a0412-da88-6370-8f77-f3ea29b5da50'}; type=pub.v1
    08-25 12:55:22.455  4477  5049 D ServiceBus: [Client] send to cls:/com.patac.hmi.user/; id= 1f1a0412-da88-6370-8f77-f3ea29b5da50
    08-25 12:55:22.456  5428  6558 D [ClsLinkSDK-v0.0.27] ClsLink: dispatchCloudEvent {id='1f1a0412-da88-6370-8f77-f3ea29b5da50'}; type=pub.v1
>>> 08-25 12:55:22.456  5428  5743 I com.patac.hmi.user-UserAccount: LeftMirrorFeatureHandle:result is not null
    08-25 12:55:22.456  5428  5743 I com.patac.hmi.user-UserAccount: LeftMirrorFeatureHandle:dealDataChange data feature is 0
    08-25 12:55:22.456  5428  5743 I com.patac.hmi.user-UserAccount: SomeIpModule:dealLeftMirrorFeatureChange 左后视镜反馈值 = 0
    08-25 12:55:22.456  5428  5743 I com.patac.hmi.user-UserAccount: DriverHabitMessageHandle:dealDriverMirrorFeedbackEvent 主驾后视镜反馈 is 0

L17362     08-25 12:55:22.730  4515  5201 I com.patac.hmi.settings-RearviewMirrorAdjustTopic: is_supported: true
    08-25 12:55:22.730  4515  5201 I com.patac.hmi.settings-RearviewMirrorAdjustTopic: , cacheData = Result{mBoolValue=true, mIntValue=0, mFloatValue=0.0, mState=0, mObject=null, mAvailable=1}
    08-25 12:55:22.730  5428  6558 D [ClsLinkSDK-v0.0.27] ClsLink: dispatchCloudEvent {id='1f1a0412-dd25-6291-8f77-f3ea29b5da50'}; type=pub.v1
>>> 08-25 12:55:22.730  5428  5743 I com.patac.hmi.user-UserAccount: LeftMirrorFeatureHandle:result is not null
    08-25 12:55:22.730  5428  5743 I com.patac.hmi.user-UserAccount: LeftMirrorFeatureHandle:dealDataChange data feature is 0
    08-25 12:55:22.730  4515  4515 I com.patac.hmi.settings-SettingItemValueSdvManager: 66<--someipHmi--disable-result---->Result{mBoolValue=true, mIntValue=0, mFloatValue=0.0, mState=0, mObject=null, mAvailable=1}
    08-25 12:55:22.730  5428  5743 I com.patac.hmi.user-UserAccount: SomeIpModule:dealLeftMirrorFeatureChange 左后视镜反馈值 = 0

L17392     08-25 12:55:22.735  4515  5201 I com.patac.hmi.settings-RightRearviewMirrorAvailableTopic: is_supported: true
    08-25 12:55:22.735  5428  6558 D [ClsLinkSDK-v0.0.27] ClsLink: dispatchCloudEvent {id='1f1a0412-dd2e-6ed2-8f77-f3ea29b5da50'}; type=pub.v1
    08-25 12:55:22.735  4515  5201 I com.patac.hmi.settings-RightRearviewMirrorAvailableTopic: , cacheData = Result{mBoolValue=true, mIntValue=0, mFloatValue=0.0, mState=0, mObject=null, mAvailable=1}
>>> 08-25 12:55:22.735  5428  5743 I com.patac.hmi.user-UserAccount: RightMirrorFeatureHandle:result is not null
    08-25 12:55:22.735  4515  4515 I com.patac.hmi.settings-SettingItemValueSdvManager: 67<--someipHmi--disable-result---->Result{mBoolValue=true, mIntValue=0, mFloatValue=0.0, mState=0, mObject=null, mAvailable=1}
    08-25 12:55:22.735  5428  5743 I com.patac.hmi.user-UserAccount: RightMirrorFeatureHandle:dealDataChange data feature is 0
    08-25 12:55:22.735  4515  4515 D com.patac.hmi.settings-DriveMirrorDialogManager: requestDisableValueFromSdvSomeIp Value-onNext: 67, disable = false, type = 19

L17574     08-25 12:55:23.034  4515  4515 I com.patac.hmi.settings-SettingItemValueSdvManager: 66<--someipHmi--disable-result---->Result{mBoolValue=true, mIntValue=0, mFloatValue=0.0, mState=0, mObject=null, mAvailable=1}
    08-25 12:55:23.034  4515  4515 D com.patac.hmi.settings-DriveMirrorDialogManager: requestDisableValueFromSdvSomeIp Value-onNext: 66, disable = false, type = 19
    08-25 12:55:23.035  5428  6558 D [ClsLinkSDK-v0.0.27] ClsLink: dispatchCloudEvent {id='1f1a0412-e00d-6ca3-8f77-f3ea29b5da50'}; type=pub.v1
>>> 08-25 12:55:23.035  5428  5743 I com.patac.hmi.user-UserAccount: LeftMirrorFeatureHandle:result is not null
    08-25 12:55:23.035  5428  5743 I com.patac.hmi.user-UserAccount: LeftMirrorFeatureHandle:dealDataChange data feature is 0
    08-25 12:55:23.035  5428  5743 I com.patac.hmi.user-UserAccount: SomeIpModule:dealLeftMirrorFeatureChange 左后视镜反馈值 = 0
    08-25 12:55:23.035  5428  5743 I com.patac.hmi.user-UserAccount: DriverHabitMessageHandle:dealDriverMirrorFeedbackEvent 主驾后视镜反馈 is 0

L17763     08-25 12:55:23.337  4477  5049 D ServiceBus: [Client] send to cls:/com.patac.hmi.user/; id= 1f1a0412-e2ea-6364-8f77-f3ea29b5da50
    08-25 12:55:23.337  2425  2490 D PatacOdiPropService: DYN updated: [213, 14, 0, 0, 0]
    08-25 12:55:23.338  5428  6558 D [ClsLinkSDK-v0.0.27] ClsLink: dispatchCloudEvent {id='1f1a0412-e2ea-6364-8f77-f3ea29b5da50'}; type=pub.v1
>>> 08-25 12:55:23.338  5428  5743 I com.patac.hmi.user-UserAccount: LeftMirrorFeatureHandle:result is not null
    08-25 12:55:23.338  5428  5743 I com.patac.hmi.user-UserAccount: LeftMirrorFeatureHandle:dealDataChange data feature is 0
    08-25 12:55:23.338  5428  5743 I com.patac.hmi.user-UserAccount: SomeIpModule:dealLeftMirrorFeatureChange 左后视镜反馈值 = 0
    08-25 12:55:23.338  5428  5743 I com.patac.hmi.user-UserAccount: DriverHabitMessageHandle:dealDriverMirrorFeedbackEvent 主驾后视镜反馈 is 0

L18002     08-25 12:55:23.637  4515  5201 I com.patac.hmi.settings-BaseTopicHandler: registerEventListener
    08-25 12:55:23.637  5428  5449 D [ClsLinkSDK-v0.0.27] ClsLink: dispatchCloudEvent {id='1f1a0412-e5cd-6f57-8f77-f3ea29b5da50'}; type=pub.v1
    08-25 12:55:23.638  4515  5201 I com.patac.hmi.settings-BaseTopicHandler: result is not null
>>> 08-25 12:55:23.638  5428  5743 I com.patac.hmi.user-UserAccount: LeftMirrorFeatureHandle:result is not null
    08-25 12:55:23.638  5428  5743 I com.patac.hmi.user-UserAccount: LeftMirrorFeatureHandle:dealDataChange data feature is 0
    08-25 12:55:23.638  5428  5743 I com.patac.hmi.user-UserAccount: SomeIpModule:dealLeftMirrorFeatureChange 左后视镜反馈值 = 0
    08-25 12:55:23.638  5428  5743 I com.patac.hmi.user-UserAccount: DriverHabitMessageHandle:dealDriverMirrorFeedbackEvent 主驾后视镜反馈 is 0

L18183     08-25 12:55:23.941  4515  5201 I com.patac.hmi.settings-BaseTopicHandler: registerEventListener
    08-25 12:55:23.941  5428  5449 D [ClsLinkSDK-v0.0.27] ClsLink: dispatchCloudEvent {id='1f1a0412-e8b1-6b48-8f77-f3ea29b5da50'}; type=pub.v1
    08-25 12:55:23.941  4515  5201 I com.patac.hmi.settings-BaseTopicHandler: result is not null
>>> 08-25 12:55:23.941  5428  5743 I com.patac.hmi.user-UserAccount: LeftMirrorFeatureHandle:result is not null
    08-25 12:55:23.941  5428  5743 I com.patac.hmi.user-UserAccount: LeftMirrorFeatureHandle:dealDataChange data feature is 0
    08-25 12:55:23.941  5428  5743 I com.patac.hmi.user-UserAccount: SomeIpModule:dealLeftMirrorFeatureChange 左后视镜反馈值 = 0
    08-25 12:55:23.941  5428  5743 I com.patac.hmi.user-UserAccount: DriverHabitMessageHandle:dealDriverMirrorFeedbackEvent 主驾后视镜反馈 is 0

L18358     08-25 12:55:24.241  4515  5201 I com.patac.hmi.settings-BaseTopicHandler: registerEventListener
    08-25 12:55:24.241  4515  5201 I com.patac.hmi.settings-BaseTopicHandler: result is not null
    08-25 12:55:24.241  5428  5449 D [ClsLinkSDK-v0.0.27] ClsLink: dispatchCloudEvent {id='1f1a0412-eb8e-6209-8f77-f3ea29b5da50'}; type=pub.v1
>>> 08-25 12:55:24.241  5428  5743 I com.patac.hmi.user-UserAccount: LeftMirrorFeatureHandle:result is not null
    08-25 12:55:24.241  5428  5743 I com.patac.hmi.user-UserAccount: LeftMirrorFeatureHandle:dealDataChange data feature is 0
    08-25 12:55:24.241  5428  5743 I com.patac.hmi.user-UserAccount: SomeIpModule:dealLeftMirrorFeatureChange 左后视镜反馈值 = 0
    08-25 12:55:24.241  4515  5201 I com.patac.hmi.settings-RearviewMirrorAdjustTopic: 32773--->makeResult: name: "OSRVM.left"

L18792     08-25 12:55:25.144  4515  5201 I com.patac.hmi.settings-RightRearviewMirrorAvailableTopic: vertical_angle: -5.2
    08-25 12:55:25.144  4515  5201 I com.patac.hmi.settings-RightRearviewMirrorAvailableTopic: is_supported: true
    08-25 12:55:25.144  4515  5201 I com.patac.hmi.settings-RightRearviewMirrorAvailableTopic: , cacheData = Result{mBoolValue=true, mIntValue=0, mFloatValue=0.0, mState=0, mObject=null, mAvailable=1}
>>> 08-25 12:55:25.144  5428  5743 I com.patac.hmi.user-UserAccount: RightMirrorFeatureHandle:result is not null
    08-25 12:55:25.144  5428  5743 I com.patac.hmi.user-UserAccount: RightMirrorFeatureHandle:dealDataChange data feature is 0
    08-25 12:55:25.144  5428  5743 I com.patac.hmi.user-UserAccount: SomeIpModule:dealRightMirrorFeatureChange 右后视镜反馈值 = 0
    08-25 12:55:25.144  4515  4515 I com.patac.hmi.settings-SettingItemValueSdvManager: 67<--someipHmi--disable-result---->Result{mBoolValue=true, mIntValue=0, mFloatValue=0.0, mState=0, mObject=null, mAvailable=1}

L18905     08-25 12:55:25.448  4515  5201 I com.patac.hmi.settings-BaseTopicHandler: registerEventListener
    08-25 12:55:25.448  5428  5449 D [ClsLinkSDK-v0.0.27] ClsLink: dispatchCloudEvent {id='1f1a0412-f710-6e7f-8f77-f3ea29b5da50'}; type=pub.v1
    08-25 12:55:25.448  4515  5201 I com.patac.hmi.settings-BaseTopicHandler: result is not null
>>> 08-25 12:55:25.448  5428  5743 I com.patac.hmi.user-UserAccount: RightMirrorFeatureHandle:result is not null
    08-25 12:55:25.448  5428  5743 I com.patac.hmi.user-UserAccount: RightMirrorFeatureHandle:dealDataChange data feature is 0
    08-25 12:55:25.448  5428  5743 I com.patac.hmi.user-UserAccount: SomeIpModule:dealRightMirrorFeatureChange 右后视镜反馈值 = 0
    08-25 12:55:25.448  5428  5743 I com.patac.hmi.user-UserAccount: DriverHabitMessageHandle:dealPassengerMirrorFeedbackEvent 副驾后视镜反馈 is 0

L19580     08-25 12:55:26.353  4515  5201 I com.patac.hmi.settings-BaseTopicHandler: registerEventListener
    08-25 12:55:26.354  5428  5449 D [ClsLinkSDK-v0.0.27] ClsLink: dispatchCloudEvent {id='1f1a0412-ffaf-6f02-8f77-f3ea29b5da50'}; type=pub.v1
    08-25 12:55:26.354  4515  5201 I com.patac.hmi.settings-BaseTopicHandler: result is not null
>>> 08-25 12:55:26.354  5428  5743 I com.patac.hmi.user-UserAccount: RightMirrorFeatureHandle:result is not null
    08-25 12:55:26.354  5428  5743 I com.patac.hmi.user-UserAccount: RightMirrorFeatureHandle:dealDataChange data feature is 0
    08-25 12:55:26.354  5428  5743 I com.patac.hmi.user-UserAccount: SomeIpModule:dealRightMirrorFeatureChange 右后视镜反馈值 = 0
    08-25 12:55:26.354  5428  5743 I com.patac.hmi.user-UserAccount: DriverHabitMessageHandle:dealPassengerMirrorFeedbackEvent 副驾后视镜反馈 is 0

L19857     08-25 12:55:26.649  4515  5201 I com.patac.hmi.settings-BaseTopicHandler: registerEventListener
    08-25 12:55:26.649  4515  5201 I com.patac.hmi.settings-BaseTopicHandler: result is not null
    08-25 12:55:26.649  5428  5449 D [ClsLinkSDK-v0.0.27] ClsLink: dispatchCloudEvent {id='1f1a0413-0282-6985-8f77-f3ea29b5da50'}; type=pub.v1
>>> 08-25 12:55:26.649  5428  5743 I com.patac.hmi.user-UserAccount: RightMirrorFeatureHandle:result is not null
    08-25 12:55:26.649  5428  5743 I com.patac.hmi.user-UserAccount: RightMirrorFeatureHandle:dealDataChange data feature is 0
    08-25 12:55:26.649  5428  5743 I com.patac.hmi.user-UserAccount: SomeIpModule:dealRightMirrorFeatureChange 右后视镜反馈值 = 0
    08-25 12:55:26.649  5428  5743 I com.patac.hmi.user-UserAccount: DriverHabitMessageHandle:dealPassengerMirrorFeedbackEvent 副驾后视镜反馈 is 0

L20429     08-25 12:55:27.861  4515  5201 I com.patac.hmi.settings-BaseTopicHandler: registerEventListener
    08-25 12:55:27.861  5428  7822 D [ClsLinkSDK-v0.0.27] ClsLink: dispatchCloudEvent {id='1f1a0413-0e0f-623a-8f77-f3ea29b5da50'}; type=pub.v1
    08-25 12:55:27.861  4515  5201 I com.patac.hmi.settings-BaseTopicHandler: result is not null
>>> 08-25 12:55:27.861  5428  5743 I com.patac.hmi.user-UserAccount: RightMirrorFeatureHandle:result is not null
    08-25 12:55:27.861  5428  5743 I com.patac.hmi.user-UserAccount: RightMirrorFeatureHandle:dealDataChange data feature is 0
    08-25 12:55:27.861  5428  5743 I com.patac.hmi.user-UserAccount: SomeIpModule:dealRightMirrorFeatureChange 右后视镜反馈值 = 0
    08-25 12:55:27.861  5428  5743 I com.patac.hmi.user-UserAccount: DriverHabitMessageHandle:dealPassengerMirrorFeedbackEvent 副驾后视镜反馈 is 0

L20606     08-25 12:55:28.163  4515  5201 I com.patac.hmi.settings-BaseTopicHandler: registerEventListener
    08-25 12:55:28.163  4515  5201 I com.patac.hmi.settings-BaseTopicHandler: result is not null
    08-25 12:55:28.163  5428  7822 D [ClsLinkSDK-v0.0.27] ClsLink: dispatchCloudEvent {id='1f1a0413-10f2-6e2d-8f77-f3ea29b5da50'}; type=pub.v1
>>> 08-25 12:55:28.163  5428  5743 I com.patac.hmi.user-UserAccount: RightMirrorFeatureHandle:result is not null
    08-25 12:55:28.163  5428  5743 I com.patac.hmi.user-UserAccount: RightMirrorFeatureHandle:dealDataChange data feature is 0
    08-25 12:55:28.163  5428  5743 I com.patac.hmi.user-UserAccount: SomeIpModule:dealRightMirrorFeatureChange 右后视镜反馈值 = 0
    08-25 12:55:28.163  5428  5743 I com.patac.hmi.user-UserAccount: DriverHabitMessageHandle:dealPassengerMirrorFeedbackEvent 副驾后视镜反馈 is 0

⚠️ 搜索结果高度重复: 共 40 条匹配中，有 30 条内容相同 ('')。以上仅展示 15 条代表性结果。

---

## 第 8 轮 — LLM 响应

关键发现：`LeftMirrorFeatureHandle:dealDataChange data feature is 0` 和 `RightMirrorFeatureHandle:dealDataChange data feature is 0`。这里的 `feature is 0` 与之前看到的 `feature is 2` 不同。

让我理解 `feature` 值的含义，以及 `mHabitRestoreResult is null` 的完整上下文。需要读取 12:55:22.4~12:55:23 的完整时间线，理解记忆恢复流程。



---

## 第 8 轮 — 工具执行结果

[结果 1] 在时间范围 [12:55:22.400, 12:55:22.750] 内未找到日志行 (PID=5428)

---

## 第 9 轮 — LLM 响应



---

## 第 9 轮 — 工具执行结果

[结果 1] 在时间范围 [12:55:22.400, 12:55:22.750] 内未找到日志行

---

## 第 10 轮 — LLM 响应

read_time_range 无结果，可能是时间格式问题。让我用 search_log 直接搜索关键时间点附近的日志，并查阅知识库理解 DriverHabit 记忆机制。



---

## 第 10 轮 — 工具执行结果

[结果 1] 搜索结果: 共 50 条匹配，显示 15 条

L17080     08-25 12:55:22.434   732   732 I Calibrationd: [532501538040]CalibrationUsageLog.cpp::logUsage(34): Calibration Requested: com.patac.hmi.user: GMModel: ENUMERATION: [Module]GMModel: ENUMERATION: 84
    08-25 12:55:22.434  5428  5428 I com.patac.hmi.user-UserAccount: CalibrationDataSource:Calibration:MODEL=84
    08-25 12:55:22.434  5428  5428 I com.patac.hmi.user-UserAccount: UserFeatureManager:isModelTypeE22 isE22 = false
>>> 08-25 12:55:22.434  5428  5428 I com.patac.hmi.user-UserAccount: CleaNewDriverHabitManager:dealDriverHabitResultEvent: seatResult is 0 leftMirrorResult is 0 rightMirrorResult is 0 mDriverMirrorFeedback 2 mPassengerMirrorFeedback 0
    08-25 12:55:22.434  5428  5428 I com.patac.hmi.user-UserAccount: CleaNewDriverHabitManager:dealDriverHabitResultEvent mRestoreDriverHabitFlow is null
    08-25 12:55:22.439  4515  5201 I com.patac.hmi.settings-BaseTopicHandler: registerEventListener
    08-25 12:55:22.439  4515  5201 I com.patac.hmi.settings-BaseTopicHandler: result is not null

L17155     08-25 12:55:22.456   732   732 I Calibrationd: [532501538040]CalibrationUsageLog.cpp::logUsage(34): Calibration Requested: com.patac.hmi.user: GMModel: ENUMERATION: [Module]GMModel: ENUMERATION: 84
    08-25 12:55:22.457  5428  5428 I com.patac.hmi.user-UserAccount: CalibrationDataSource:Calibration:MODEL=84
    08-25 12:55:22.457  5428  5428 I com.patac.hmi.user-UserAccount: UserFeatureManager:isModelTypeE22 isE22 = false
>>> 08-25 12:55:22.457  5428  5428 I com.patac.hmi.user-UserAccount: CleaNewDriverHabitManager:dealDriverHabitResultEvent: seatResult is 0 leftMirrorResult is 0 rightMirrorResult is 0 mDriverMirrorFeedback 0 mPassengerMirrorFeedback 0
    08-25 12:55:22.457  4515  5201 I com.patac.hmi.settings-RearviewMirrorAdjustTopic: 32773--->makeResult: name: "OSRVM.left"
    08-25 12:55:22.457  5428  5428 I com.patac.hmi.user-UserAccount: CleaNewDriverHabitManager:dealDriverHabitResultEvent mRestoreDriverHabitFlow is null
    08-25 12:55:22.457  4515  5201 I com.patac.hmi.settings-RearviewMirrorAdjustTopic: horizontal_angle: -0.2

L17176     08-25 12:55:22.477  5428  5428 I com.patac.hmi.user-UserAccount: CleaNewDriverHabitManager:dealCustomEvent CLEA_DRIVER_HABIT_DATA_EVENT
    08-25 12:55:22.477  5428  5428 I com.patac.hmi.user-UserAccount: DriverHabitInfoUnit:updateCurrentHabitInfo
    08-25 12:55:22.477  5428  5428 I com.patac.hmi.user-UserAccount: UserFeatureManager:isMcuEnableDriverHabit mIsMcuEnableDriverHabit = true
>>> 08-25 12:55:22.477  5428  5428 I com.patac.hmi.user-UserAccount: CleaNewDriverHabitManager:dealDriverHabitDataEvent mHabitRestoreResult is null
    08-25 12:55:22.479  2371  2371 D PatacSwcHandlingService: diapatch KeyEvent KeyEvent { action=ACTION_DOWN, keyCode=KEYCODE_VOLUME_DOWN, scanCode=0, metaState=0, flags=0x0, repeatCount=6, eventTime=2369794000000, downTime=2369794000000, deviceId=0, source=0x101, displayId=0 } to HardKeyClient Callbac
    08-25 12:55:22.479  1089  7406 I Bosch_NavSensors: GyrUn:[-0.000266, -0.001332, 0.000799, 0.000000, 0.000000, 0.000000, 1713957]
    08-25 12:55:22.480  4515  5408 D HardKeyInterceptorManager: dispatchKeyEvent event = KeyEvent { action=ACTION_DOWN, keyCode=KEYCODE_VOLUME_DOWN, scanCode=0, metaState=0, flags=0x0, repeatCount=6, eventTime=2369794000000, downTime=2369794000000, deviceId=0, source=0x101, displayId=0 }

L17223     08-25 12:55:22.581  5428  5704 I com.patac.hmi.user-UserAccount: SystemInfoRepository:sendSystemEvent type is 4 id is  4201
    08-25 12:55:22.581  5428  5428 I com.patac.hmi.user-UserAccount: DriverHabitInfoUnit:updateCurrentHabitInfo
    08-25 12:55:22.581  5428  5428 I com.patac.hmi.user-UserAccount: UserFeatureManager:isMcuEnableDriverHabit mIsMcuEnableDriverHabit = true
>>> 08-25 12:55:22.581  5428  5428 I com.patac.hmi.user-UserAccount: CleaNewDriverHabitManager:dealDriverHabitDataEvent mHabitRestoreResult is null
    08-25 12:55:22.581  5428  5428 I com.patac.hmi.user-UserAccount: UserApplicationManager:get system event 4201
    08-25 12:55:22.581  5428  5428 I com.patac.hmi.user-UserAccount: CleaNewDriverHabitManager:dealCustomEvent CLEA_DRIVER_HABIT_DATA_EVENT
    08-25 12:55:22.581  5428  5428 I com.patac.hmi.user-UserAccount: DriverHabitInfoUnit:updateCurrentHabitInfo

L17290     08-25 12:55:22.688  5428  5428 I com.patac.hmi.user-UserAccount: CleaNewDriverHabitManager:dealCustomEvent CLEA_DRIVER_HABIT_DATA_EVENT
    08-25 12:55:22.688  5428  5428 I com.patac.hmi.user-UserAccount: DriverHabitInfoUnit:updateCurrentHabitInfo
    08-25 12:55:22.688  5428  5428 I com.patac.hmi.user-UserAccount: UserFeatureManager:isMcuEnableDriverHabit mIsMcuEnableDriverHabit = true
>>> 08-25 12:55:22.688  5428  5428 I com.patac.hmi.user-UserAccount: CleaNewDriverHabitManager:dealDriverHabitDataEvent mHabitRestoreResult is null
    08-25 12:55:22.691  4156  4156 I com.patac.hmi.media-ProgressHelper: [ProgressHelper]-PlaybackState is null:true,MediaInfo is null:true
    08-25 12:55:22.691  4156  4156 D com.patac.hmi.media-BTAudioManager: mPlayStateEmitter is null,Do nothing Or state is fast ward/rewind
    08-25 12:55:22.714  1089  7403 I Bosch_NavSensors: GnssSourceVIP::readerThread ipc_read ret time s 22 ms 999

L17375     08-25 12:55:22.731   732   732 I Calibrationd: [532501538040]CalibrationUsageLog.cpp::logUsage(34): Calibration Requested: com.patac.hmi.user: GMModel: ENUMERATION: [Module]GMModel: ENUMERATION: 84
    08-25 12:55:22.732  5428  5428 I com.patac.hmi.user-UserAccount: CalibrationDataSource:Calibration:MODEL=84
    08-25 12:55:22.732  5428  5428 I com.patac.hmi.user-UserAccount: UserFeatureManager:isModelTypeE22 isE22 = false
>>> 08-25 12:55:22.732  5428  5428 I com.patac.hmi.user-UserAccount: CleaNewDriverHabitManager:dealDriverHabitResultEvent: seatResult is 0 leftMirrorResult is 0 rightMirrorResult is 0 mDriverMirrorFeedback 0 mPassengerMirrorFeedback 0
    08-25 12:55:22.732  5428  5428 I com.patac.hmi.user-UserAccount: CleaNewDriverHabitManager:dealDriverHabitResultEvent mRestoreDriverHabitFlow is null
    08-25 12:55:22.732  4112  5115 D TimeResult: SystemClock: 3603273, ElapsedRealtimeMillis: 1892235
    08-25 12:55:22.732  4112  5115 D TimeResult: mTimeMillis: 1787632011696, AgeMillis: 1711038

L17405     08-25 12:55:22.735   732   732 I Calibrationd: [532501538040]CalibrationUsageLog.cpp::logUsage(34): Calibration Requested: com.patac.hmi.user: GMModel: ENUMERATION: [Module]GMModel: ENUMERATION: 84
    08-25 12:55:22.736  5428  5428 I com.patac.hmi.user-UserAccount: CalibrationDataSource:Calibration:MODEL=84
    08-25 12:55:22.736  5428  5428 I com.patac.hmi.user-UserAccount: UserFeatureManager:isModelTypeE22 isE22 = false
>>> 08-25 12:55:22.736  5428  5428 I com.patac.hmi.user-UserAccount: CleaNewDriverHabitManager:dealDriverHabitResultEvent: seatResult is 0 leftMirrorResult is 0 rightMirrorResult is 0 mDriverMirrorFeedback 0 mPassengerMirrorFeedback 0
    08-25 12:55:22.736  5428  5428 I com.patac.hmi.user-UserAccount: CleaNewDriverHabitManager:dealDriverHabitResultEvent mRestoreDriverHabitFlow is null
    08-25 12:55:22.740  1371  1476 D GMVHAL  : setPropFromVehicle Property: VendorProperty::LOCAL_TIME AreaID: 16777216 Status: 0 int32Values: 2026 8 25 12 55 22 
    08-25 12:55:22.740  1371  1476 D GMVHAL  : setPropFromVehicle Property: VendorProperty::UTC AreaID: 16777216 Status: 0 int32Values: 2026 8 25 4 55 22 

L17436     08-25 12:55:22.805  5428  5428 I com.patac.hmi.user-UserAccount: CleaNewD

... [截断: 原始结果 15,427 字符，已截取中间 427 字符] ...

DataEvent mHabitRestoreResult is null
    08-25 12:55:22.807  1368  3139 I         : VSIP: cei::rcb (Success): 00 01 80 fb 00 00 00 20 00 00 51 2a 01 01 02 00 01 00 00 00 00 00 00 00 00 4a 18 00 00 00 00 00 00 00 00 00 02 08 54 00 
    08-25 12:55:22.813  1089  7403 I Bosch_NavSensors: GnssSourceVIP::readerThread ipc_read ret time s 23 ms 80
    08-25 12:55:22.813  1089  1373 D Bosch_NavSensors: Nmea: 1787633723080 : $GPGGA,045523.08,3120.158739,N,12047.433599,E,1,10,0.0,24.7,M,,M,,*4F

L17478     08-25 12:55:22.914  5428  5428 I com.patac.hmi.user-UserAccount: CleaNewDriverHabitManager:dealCustomEvent CLEA_DRIVER_HABIT_DATA_EVENT
    08-25 12:55:22.914  5428  5428 I com.patac.hmi.user-UserAccount: DriverHabitInfoUnit:updateCurrentHabitInfo
    08-25 12:55:22.914  5428  5428 I com.patac.hmi.user-UserAccount: UserFeatureManager:isMcuEnableDriverHabit mIsMcuEnableDriverHabit = true
>>> 08-25 12:55:22.914  5428  5428 I com.patac.hmi.user-UserAccount: CleaNewDriverHabitManager:dealDriverHabitDataEvent mHabitRestoreResult is null
    08-25 12:55:22.925  1371  1443 D GMVHAL  : void KeyInputPropertyManager::onLongPressRepeatDelay(const std::vector<int32_t> &)
    08-25 12:55:22.925  1371  1443 D GMVHAL  : setPropFromVehicle Property: VehicleProperty::HW_KEY_INPUT AreaID: 16777216 Status: 0 int32Values: 0 25 0 
    08-25 12:55:22.925  2150  2234 D CAR.INPUT: hal event code: 25, action: 0, display: 0, number of indents: 1

L17530     08-25 12:55:23.030  5428  5428 I com.patac.hmi.user-UserAccount: CleaNewDriverHabitManager:dealCustomEvent CLEA_DRIVER_HABIT_DATA_EVENT
    08-25 12:55:23.030  5428  5428 I com.patac.hmi.user-UserAccount: DriverHabitInfoUnit:updateCurrentHabitInfo
    08-25 12:55:23.030  5428  5428 I com.patac.hmi.user-UserAccount: UserFeatureManager:isMcuEnableDriverHabit mIsMcuEnableDriverHabit = true
>>> 08-25 12:55:23.030  5428  5428 I com.patac.hmi.user-UserAccount: CleaNewDriverHabitManager:dealDriverHabitDataEvent mHabitRestoreResult is null
    08-25 12:55:23.030  4112  5019 D SDV_CoreService: [FrontLeftWindowTopicMapper]someIp sRlVCPWLSCurrSeltnVal: 2 drvWndAval: true drvWndCfg: true
    08-25 12:55:23.031  4112  5150 I SDV_CoreService: [ThirdRowLeftDoorSomeIpTopicMapper]SUCCESS: NOTIFY_BODY_INFORMATION_17
    08-25 12:55:23.031  4112  5150 D SDV_CoreService: [ThirdRowLeftDoorSomeIpTopicMapper]resp.getSRlVCPWLSCurrSeltnVal(): 2

L17585     08-25 12:55:23.035   732   732 I Calibrationd: [532501538040]CalibrationUsageLog.cpp::logUsage(34): Calibration Requested: com.patac.hmi.user: GMModel: ENUMERATION: [Module]GMModel: ENUMERATION: 84
    08-25 12:55:23.036  5428  5428 I com.patac.hmi.user-UserAccount: CalibrationDataSource:Calibration:MODEL=84
    08-25 12:55:23.036  5428  5428 I com.patac.hmi.user-UserAccount: UserFeatureManager:isModelTypeE22 isE22 = false
>>> 08-25 12:55:23.036  5428  5428 I com.patac.hmi.user-UserAccount: CleaNewDriverHabitManager:dealDriverHabitResultEvent: seatResult is 0 leftMirrorResult is 0 rightMirrorResult is 0 mDriverMirrorFeedback 0 mPassengerMirrorFeedback 0
    08-25 12:55:23.036  5428  5428 I com.patac.hmi.user-UserAccount: CleaNewDriverHabitManager:dealDriverHabitResultEvent mRestoreDriverHabitFlow is null
    08-25 12:55:23.056  1371  1476 D GMVHAL  : setPropFromVehicle Property: VendorProperty::POSITION_OFFSET_FROM_TRIM AreaID: 4 Status: 0 floatValues: -8 
    08-25 12:55:23.056  1371  1476 D GMVHAL  : setPropFromVehicle Property: PatacProperty::RIDE_HEIGHT_STATUS_4_SIGNAL_GROUP AreaID: 16777216 Status: 0 int32Values: -15 0 -8 0 -3 0 -18 0 

L17639     08-25 12:55:23.137  5428  5428 I com.patac.hmi.user-UserAccount: CleaNewDriverHabitManager:dealCustomEvent CLEA_DRIVER_HABIT_DATA_EVENT
    08-25 12:55:23.137  5428  5428 I com.patac.hmi.user-UserAccount: DriverHabitInfoUnit:updateCurrentHabitInfo
    08-25 12:55:23.137  5428  5428 I com.patac.hmi.user-UserAccount: UserFeatureManager:isMcuEnableDriverHabit mIsMcuEnableDriverHabit = true
>>> 08-25 12:55:23.137  5428  5428 I com.patac.hmi.user-UserAccount: CleaNewDriverHabitManager:dealDriverHabitDataEvent mHabitRestoreResult is null
    08-25 12:55:23.154  1089  7406 I Bosch_NavSensors: AccUn:[2.530671, -2.707842, 9.045294, 0.000000, 0.000000, 0.000000, 1714628]
    08-25 12:55:23.154  1089  7406 I Bosch_NavSensors: Gravity:[0.000000, -2.668532, 9.436594, 3603695138571]
    08-25 12:55:23.171  2425  7756 D FSANetCommsClient: FSARemoteClient RX QSize is: 0, funcID: 100, ID: 100

L17675     08-25 12:55:23.245  5428  5428 I com.patac.hmi.user-UserAccount: CleaNewDriverHabitManager:dealCustomEvent CLEA_DRIVER_HABIT_DATA_EVENT
    08-25 12:55:23.245  5428  5428 I com.patac.hmi.user-UserAccount: DriverHabitInfoUnit:updateCurrentHabitInfo
    08-25 12:55:23.245  5428  5428 I com.patac.hmi.user-UserAccount: UserFeatureManager:isMcuEnableDriverHabit mIsMcuEnableDriverHabit = true
>>> 08-25 12:55:23.245  5428  5428 I com.patac.hmi.user-UserAccount: CleaNewDriverHabitManager:dealDriverHabitDataEvent mHabitRestoreResult is null
    08-25 12:55:23.262  1089  7406 I Bosch_NavSensors: GyrUn:[0.000266, -0.000533, 0.000266, 0.000000, 0.000000, 0.000000, 1714737]
    08-25 12:55:23.272  1089  7406 I Bosch_NavSensors: AccUn:[2.540248, -2.700660, 9.040505, 0.000000, 0.000000, 0.000000, 1714747]
    08-25 12:55:23.272  1089  7406 I Bosch_NavSensors: Gravity:[0.000000, -2.668957, 9.436475, 3603813344821]

L17774     08-25 12:55:23.339   732   732 I Calibrationd: [532501538040]CalibrationUsageLog.cpp::logUsage(34): Calibration Requested: com.patac.hmi.user: GMModel: ENUMERATION: [Module]GMModel: ENUMERATION: 84
    08-25 12:55:23.339  5428  5428 I com.patac.hmi.user-UserAccount: CalibrationDataSource:Calibration:MODEL=84
    08-25 12:55:23.339  5428  5428 I com.patac.hmi.user-UserAccount: UserFeatureManager:isModelTypeE22 isE22 = false
>>> 08-25 12:55:23.339  5428  5428 I com.patac.hmi.user-UserAccount: CleaNewDriverHabitManager:dealDriverHabitResultEvent: seatResult is 0 leftMirrorResult is 0 rightMirrorResult is 0 mDriverMirrorFeedback 0 mPassengerMirrorFeedback 0
    08-25 12:55:23.339  5428  5428 I com.patac.hmi.user-UserAccount: CleaNewDriverHabitManager:dealDriverHabitResultEvent mRestoreDriverHabitFlow is null
    08-25 12:55:23.361  1371  1476 D GMVHAL  : setPropFromVehicle Property: PatacProperty::MIRROR_POSITION_STATUS AreaID: 1 Status: 0 floatValues: -8.8 -0.2 0 
    08-25 12:55:23.361  1371  1476 D GMVHAL  : setPropFromVehicle Property: PatacProperty::MIRROR_POSITION_STATUS AreaID: 2 Status: 0 floatValues: -5.2 0.1 0 

L17787     08-25 12:55:23.363  5428  5428 I com.patac.hmi.user-UserAccount: DriverHabitInfoUnit:updateCurrentHabitInfo
    08-25 12:55:23.363  5428  5704 I com.patac.hmi.user-UserAccount: DriverHabitMessageHandle:sendDriverHabitEvent afterCheck
    08-25 12:55:23.363  5428  5428 I com.patac.hmi.user-UserAccount: UserFeatureManager:isMcuEnableDriverHabit mIsMcuEnableDriverHabit = true
>>> 08-25 12:55:23.363  5428  5428 I com.patac.hmi.user-UserAccount: CleaNewDriverHabitManager:dealDriverHabitDataEvent mHabitRestoreResult is null
    08-25 12:55:23.364  5428  5704 I com.patac.hmi.user-UserAccount: SystemInfoRepository:sendSystemEvent type is 4 id is  4201
    08-25 12:55:23.364  5428  5428 I com.patac.hmi.user-UserAccount: UserApplicationManager:get system event 4201
    08-25 12:55:23.364  5428  5428 I com.patac.hmi.user-UserAccount: CleaNewDriverHabitManager:dealCustomEvent CLEA_DRIVER_HABIT_DATA_EVENT

⚠️ 搜索结果高度重复: 共 50 条匹配中，有 30 条内容相同 ('')。以上仅展示 15 条代表性结果。

---

[结果 2] WIKI 文档 [knowledge_list]:
[车控娱乐]
- 车控娱乐/Album-EConnection.md: LocalSend 连接链路日志分析指引（扫码/建链/传输）
- 车控娱乐/Climate.md: 背景
- 车控娱乐/Connection.md: 常见问题集中于Device设备状态是否正常，设备切换流程是否存在问题
- 车控娱乐/DBA.md: 背景
- 车控娱乐/Energy.md: Energy包含的主要功能：充电、放电、能源管理、能量流，界面包括能量中心、充/放电桌面、Kanzi车模。
- 车控娱乐/EngMode.md: 问题类型
- 车控娱乐/Gallery.md: PATACGallery 媒体时间线到详情页日志分析指引
- 车控娱乐/OnlineMusic.md: 常见在线音乐播放问题表现为两个或多个音源同时播放导致的通话结束后，车机媒体未续播、混音问题、数据加载失败等，从根因来看主
- 车控娱乐/Onstar.md: 常见的OnStar问题包括安吉星电话无法打出，安吉星挂断失败/延迟，安吉星显示失败弹框，安吉星odd弹框不显示。
- 车控娱乐/Seat.md: 常见问题定位从表面来讲包含座椅通风按钮置灰、缺少副驾零重力按钮、座舱模式提示不可用问题
- 车控娱乐/Setting.md: 车辆信息
- 车控娱乐/Theme.md: 常见主题壁纸问题从表现形式上来讲包括：下载失败、更新异常、切换无效、显示异常、存储空间不足等。从根因上来看主要分为几类：
- 车控娱乐/calendar.md: 常见的日历问题包括打开农历开关无法显示农历与节假日信息。
- 车控娱乐/customsetting.md: 常见的日历问题包括首次登录无同步弹框，个性化同步失败。
- 车控娱乐/media.md: Tuner典型问题类型列举
- 车控娱乐/phone.md: 背景
- 车控娱乐/user.md: 常见的日历问题包括首次登录无同步弹框，个性化同步失败。
- 车控娱乐/展厅.md: ShowRoom典型问题类型列举
- 车控娱乐/无麦K歌.md: 常见的无麦k歌问题包括界面不显示无麦K歌悬浮窗，悬浮框原伴唱状态与当前音源不一致。

---

## 第 11 轮 — LLM 响应



---

## 第 11 轮 — 工具执行结果

[结果 1] 搜索结果: 共 30 条匹配，显示 15 条

L17081     08-25 12:55:22.434  5428  5428 I com.patac.hmi.user-UserAccount: CalibrationDataSource:Calibration:MODEL=84
    08-25 12:55:22.434  5428  5428 I com.patac.hmi.user-UserAccount: UserFeatureManager:isModelTypeE22 isE22 = false
    08-25 12:55:22.434  5428  5428 I com.patac.hmi.user-UserAccount: CleaNewDriverHabitManager:dealDriverHabitResultEvent: seatResult is 0 leftMirrorResult is 0 rightMirrorResult is 0 mDriverMirrorFeedback 2 mPassengerMirrorFeedback 0
>>> 08-25 12:55:22.434  5428  5428 I com.patac.hmi.user-UserAccount: CleaNewDriverHabitManager:dealDriverHabitResultEvent mRestoreDriverHabitFlow is null
    08-25 12:55:22.439  4515  5201 I com.patac.hmi.settings-BaseTopicHandler: registerEventListener
    08-25 12:55:22.439  4515  5201 I com.patac.hmi.settings-BaseTopicHandler: result is not null
    08-25 12:55:22.439  4515  5201 I com.patac.hmi.settings-RearviewMirrorAdjustTopic: 32773--->makeResult: name: "OSRVM.left"

L17157     08-25 12:55:22.457  5428  5428 I com.patac.hmi.user-UserAccount: UserFeatureManager:isModelTypeE22 isE22 = false
    08-25 12:55:22.457  5428  5428 I com.patac.hmi.user-UserAccount: CleaNewDriverHabitManager:dealDriverHabitResultEvent: seatResult is 0 leftMirrorResult is 0 rightMirrorResult is 0 mDriverMirrorFeedback 0 mPassengerMirrorFeedback 0
    08-25 12:55:22.457  4515  5201 I com.patac.hmi.settings-RearviewMirrorAdjustTopic: 32773--->makeResult: name: "OSRVM.left"
>>> 08-25 12:55:22.457  5428  5428 I com.patac.hmi.user-UserAccount: CleaNewDriverHabitManager:dealDriverHabitResultEvent mRestoreDriverHabitFlow is null
    08-25 12:55:22.457  4515  5201 I com.patac.hmi.settings-RearviewMirrorAdjustTopic: horizontal_angle: -0.2
    08-25 12:55:22.457  4515  5201 I com.patac.hmi.settings-RearviewMirrorAdjustTopic: vertical_angle: -5.6
    08-25 12:55:22.457  4515  5201 I com.patac.hmi.settings-RearviewMirrorAdjustTopic: is_supported: true

L17376     08-25 12:55:22.732  5428  5428 I com.patac.hmi.user-UserAccount: CalibrationDataSource:Calibration:MODEL=84
    08-25 12:55:22.732  5428  5428 I com.patac.hmi.user-UserAccount: UserFeatureManager:isModelTypeE22 isE22 = false
    08-25 12:55:22.732  5428  5428 I com.patac.hmi.user-UserAccount: CleaNewDriverHabitManager:dealDriverHabitResultEvent: seatResult is 0 leftMirrorResult is 0 rightMirrorResult is 0 mDriverMirrorFeedback 0 mPassengerMirrorFeedback 0
>>> 08-25 12:55:22.732  5428  5428 I com.patac.hmi.user-UserAccount: CleaNewDriverHabitManager:dealDriverHabitResultEvent mRestoreDriverHabitFlow is null
    08-25 12:55:22.732  4112  5115 D TimeResult: SystemClock: 3603273, ElapsedRealtimeMillis: 1892235
    08-25 12:55:22.732  4112  5115 D TimeResult: mTimeMillis: 1787632011696, AgeMillis: 1711038
    08-25 12:55:22.732  4112  5115 D SDV_CoreService: [SomeIpUtil]publish event: uri: cls:/vehicle/1/OSRVM.right#OSRVM

L17406     08-25 12:55:22.736  5428  5428 I com.patac.hmi.user-UserAccount: CalibrationDataSource:Calibration:MODEL=84
    08-25 12:55:22.736  5428  5428 I com.patac.hmi.user-UserAccount: UserFeatureManager:isModelTypeE22 isE22 = false
    08-25 12:55:22.736  5428  5428 I com.patac.hmi.user-UserAccount: CleaNewDriverHabitManager:dealDriverHabitResultEvent: seatResult is 0 leftMirrorResult is 0 rightMirrorResult is 0 mDriverMirrorFeedback 0 mPassengerMirrorFeedback 0
>>> 08-25 12:55:22.736  5428  5428 I com.patac.hmi.user-UserAccount: CleaNewDriverHabitManager:dealDriverHabitResultEvent mRestoreDriverHabitFlow is null
    08-25 12:55:22.740  1371  1476 D GMVHAL  : setPropFromVehicle Property: VendorProperty::LOCAL_TIME AreaID: 16777216 Status: 0 int32Values: 2026 8 25 12 55 22 
    08-25 12:55:22.740  1371  1476 D GMVHAL  : setPropFromVehicle Property: VendorProperty::UTC AreaID: 16777216 Status: 0 int32Values: 2026 8 25 4 55 22 
    08-25 12:55:22.750  2015  2249 D nfsa.transport.out: /172.16.4.1:54590: Heartbeat( 100 ) Status, clientHandle = 0, service= 1026.1, 23 bytes

L17586     08-25 12:55:23.036  5428  5428 I com.patac.hmi.user-UserAccount: CalibrationDataSource:Calibration:MODEL=84
    08-25 12:55:23.036  5428  5428 I com.patac.hmi.user-UserAccount: UserFeatureManager:isModelTypeE22 isE22 = false
    08-25 12:55:23.036  5428  5428 I com.patac.hmi.user-UserAccount: CleaNewDriverHabitManager:dealDriverHabitResultEvent: seatResult is 0 leftMirrorResult is 0 rightMirrorResult is 0 mDriverMirrorFeedback 0 mPassengerMirrorFeedback 0
>>> 08-25 12:55:23.036  5428  5428 I com.patac.hmi.user-UserAccount: CleaNewDriverHabitManager:dealDriverHabitResultEvent mRestoreDriverHabitFlow is null
    08-25 12:55:23.056  1371  1476 D GMVHAL  : setPropFromVehicle Property: VendorProperty::POSITION_OFFSET_FROM_TRIM AreaID: 4 Status: 0 floatValues: -8 
    08-25 12:55:23.056  1371  1476 D GMVHAL  : setPropFromVehicle Property: PatacProperty::RIDE_HEIGHT_STATUS_4_SIGNAL_GROUP AreaID: 16777216 Status: 0 int32Values: -15 0 -8 0 -3 0 -18 0 
    08-25 12:55:23.056   730 10727 D android.hardware.thermal@2.0-service.gmvcu SensorsHalClient: Received temperature from Sensors HAL: 43.000000

L17775     08-25 12:55:23.339  5428  5428 I com.patac.hmi.user-UserAccount: CalibrationDataSource:Calibration:MODEL=84
    08-25 12:55:23.339  5428  5428 I com.patac.hmi.user-UserAccount: UserFeatureManager:isModelTypeE22 isE22 = false
    08-25 12:55:23.339  5428  5428 I com.patac.hmi.user-UserAccount: CleaNewDriverHabitManager:dealDriverHabitResultEvent: seatResult is 0 leftMirrorResult is 0 rightMirrorResult is 0 mDriverMirrorFeedback 0 mPassengerMirrorFeedback 0
>>> 08-25 12:55:23.339  5428  5428 I com.patac.hmi.user-UserAccount: CleaNewDriverHabitManager:dealDriverHabitResultEvent mRestoreDriverHabitFlow is null
    08-25 12:55:23.361  1371  1476 D GMVHAL  : setPropFromVehicle Property: PatacProperty::MIRROR_POSITION_STATUS AreaID: 1 Status: 0 floatValues: -8.8 -0.2 0 
    08-25 12:55:23.361  1371  1476 D GMVHAL  : setPropFromVehicle Property: PatacProperty::MIRROR_POSITION_STATUS AreaID: 2 Status: 0 floatValues: -5.2 0.1 0 
    08-25 12:55:23.362  5428  5704 I com.patac.hmi.user-UserAccount: CarDataSource:left mirror position:-8.8 -0.2 0.0 

L18021     08-25 12:55:23.638  5428  5428 I com.patac.hmi.user-UserAccount: CalibrationDataSource:Calibration:MODEL=84
    08-25 12:55:23.638  5428  5428 I com.patac.hmi.user-UserAccount: UserFeatureManager:isModelTypeE22 isE22 = false
    08-25 12:55:23.639  5428  5428 I com.patac.hmi.user-UserAccount: CleaNewDriverHabitManager:dealDriverHabitResultEvent: seatResult is 0 leftMirrorResult is 0 rightMirrorResult is 0 mDriverMirrorFeedback 0 mPassengerMirrorFeedback 0
>>> 08-25 12:55:23.639  5428  5428 I com.patac.hmi.user-UserAccount: CleaNewDriverHabitManager:dealDriverHabitResultEvent mRestoreDriverHabitFlow is null
    08-25 12:55:23.667  1371  1476 D GMVHAL  : setPropFromVehicle Property: VendorProperty::POSITION_OFFSET_FROM_TRIM AreaID: 4 Status: 0 floatValues: -7 
    08-25 12:55:23.668  1371  1476 D GMVHAL  : setPropFromVehicle Property: PatacProperty::RIDE_HEIGHT_STATUS_4_SIGNAL_GROUP AreaID: 16777216 Status: 0 int32Values: -15 0 -7 0 -3 0 -18 0 
    08-25 12:55:23.676  1371  1443 D GMVHAL  : void KeyInputPropertyManager::onLongPressRepeatDelay(const std::vector<int32_t> &)

L18202     08-25 12:55:23.943  5428  5428 I com.patac.hmi.user-UserAccount: CalibrationDataSource:Calibration:MODEL=84
    08-25 12:55:23.943  5428  5428 I com.patac.hmi.user-UserAccount: UserFeatureManager:isModelTypeE22 isE22 = false
    08-

... [截断: 原始结果 15,943 字符，已截取中间 943 字符] ...

c.hmi.user-UserAccount: UserFeatureManager:isModelTypeE22 isE22 = false
    08-25 12:55:24.242  5428  5428 I com.patac.hmi.user-UserAccount: CleaNewDriverHabitManager:dealDriverHabitResultEvent: seatResult is 0 leftMirrorResult is 0 rightMirrorResult is 0 mDriverMirrorFeedback 0 mPassengerMirrorFeedback 0
>>> 08-25 12:55:24.243  5428  5428 I com.patac.hmi.user-UserAccount: CleaNewDriverHabitManager:dealDriverHabitResultEvent mRestoreDriverHabitFlow is null
    08-25 12:55:24.243  1371  1459 I GMVHAL  : keyEvent keycode 25 EVENT 0
    08-25 12:55:24.243  1371  1459 D GMVHAL  : setPropFromVehicle Property: VehicleProperty::HW_KEY_INPUT AreaID: 16777216 Status: 0 int32Values: 1 25 0 
    08-25 12:55:24.243  1371  1459 D GMVHAL  : Unregister long press KEY 25 EVENT 0

L18808     08-25 12:55:25.145  5428  5428 I com.patac.hmi.user-UserAccount: CalibrationDataSource:Calibration:MODEL=84
    08-25 12:55:25.145  5428  5428 I com.patac.hmi.user-UserAccount: UserFeatureManager:isModelTypeE22 isE22 = false
    08-25 12:55:25.145  5428  5428 I com.patac.hmi.user-UserAccount: CleaNewDriverHabitManager:dealDriverHabitResultEvent: seatResult is 0 leftMirrorResult is 0 rightMirrorResult is 0 mDriverMirrorFeedback 0 mPassengerMirrorFeedback 0
>>> 08-25 12:55:25.145  5428  5428 I com.patac.hmi.user-UserAccount: CleaNewDriverHabitManager:dealDriverHabitResultEvent mRestoreDriverHabitFlow is null
    08-25 12:55:25.171  1371  1476 D GMVHAL  : setPropFromVehicle Property: PatacProperty::HORIZONTAL_DILUTION_OF_PRECISION AreaID: 16777216 Status: 0 floatValues: 0.5 
    08-25 12:55:25.172  2425  7756 D FSANetCommsClient: FSARemoteClient RX QSize is: 0, funcID: 100, ID: 100
    08-25 12:55:25.172  2425  7756 D FSAIStateOfHealthClient: FSARemoteClient FSA: handle heartbeat 853

L18924     08-25 12:55:25.449  5428  5428 I com.patac.hmi.user-UserAccount: CalibrationDataSource:Calibration:MODEL=84
    08-25 12:55:25.449  5428  5428 I com.patac.hmi.user-UserAccount: UserFeatureManager:isModelTypeE22 isE22 = false
    08-25 12:55:25.449  5428  5428 I com.patac.hmi.user-UserAccount: CleaNewDriverHabitManager:dealDriverHabitResultEvent: seatResult is 0 leftMirrorResult is 0 rightMirrorResult is 0 mDriverMirrorFeedback 0 mPassengerMirrorFeedback 0
>>> 08-25 12:55:25.449  5428  5428 I com.patac.hmi.user-UserAccount: CleaNewDriverHabitManager:dealDriverHabitResultEvent mRestoreDriverHabitFlow is null
    08-25 12:55:25.449  1371  1476 D GMVHAL  : setPropFromVehicle Property: PatacProperty::RIDE_HEIGHT_STATUS_4_SIGNAL_GROUP AreaID: 16777216 Status: 0 int32Values: -15 0 -7 0 -3 0 -18 0 
    08-25 12:55:25.449  1371  1476 D GMVHAL  : setPropFromVehicle Property: PatacProperty::FORWARD_LOOKING_LIGHT_LEVEL_EXTENDED AreaID: 16777216 Status: 0 int32Values: 36640 
    08-25 12:55:25.476  1089  7406 I Bosch_NavSensors: wheelTick: [620, 616,1236, 1716957 ]

L19598     08-25 12:55:26.355  5428  5428 I com.patac.hmi.user-UserAccount: UserFeatureManager:isModelTypeE22 isE22 = false
    08-25 12:55:26.355  4156  4851 I com.patac.hmi.media-BaseState: updateSourceList size:3
    08-25 12:55:26.355  5428  5428 I com.patac.hmi.user-UserAccount: CleaNewDriverHabitManager:dealDriverHabitResultEvent: seatResult is 0 leftMirrorResult is 0 rightMirrorResult is 0 mDriverMirrorFeedback 0 mPassengerMirrorFeedback 0
>>> 08-25 12:55:26.355  5428  5428 I com.patac.hmi.user-UserAccount: CleaNewDriverHabitManager:dealDriverHabitResultEvent mRestoreDriverHabitFlow is null
    08-25 12:55:26.355  4156  4851 I com.patac.hmi.media-BaseState: update provider
    08-25 12:55:26.355  4515  4515 I com.patac.hmi.settings-SettingItemValueSdvManager: 67<--someipHmi--disable-result---->Result{mBoolValue=true, mIntValue=0, mFloatValue=0.0, mState=0, mObject=null, mAvailable=1}
    08-25 12:55:26.355  4515  4515 D com.patac.hmi.settings-DriveMirrorDialogManager: requestDisableValueFromSdvSomeIp Value-onNext: 67, disable = false, type = 19

L19875     08-25 12:55:26.650  5428  5428 I com.patac.hmi.user-UserAccount: CalibrationDataSource:Calibration:MODEL=84
    08-25 12:55:26.650  5428  5428 I com.patac.hmi.user-UserAccount: UserFeatureManager:isModelTypeE22 isE22 = false
    08-25 12:55:26.650  5428  5428 I com.patac.hmi.user-UserAccount: CleaNewDriverHabitManager:dealDriverHabitResultEvent: seatResult is 0 leftMirrorResult is 0 rightMirrorResult is 0 mDriverMirrorFeedback 0 mPassengerMirrorFeedback 0
>>> 08-25 12:55:26.650  5428  5428 I com.patac.hmi.user-UserAccount: CleaNewDriverHabitManager:dealDriverHabitResultEvent mRestoreDriverHabitFlow is null
    08-25 12:55:26.655  2015  2249 D nfsa.transport.out: /172.16.4.1:54590: Heartbeat( 100 ) Status, clientHandle = 0, service= 1026.1, 23 bytes
    08-25 12:55:26.662  1368  3139 I         : VSIP: cei::rcb (Success): 00 01 80 97 00 00 00 c1 00 00 51 50 01 01 02 00 01 00 00 00 00 00 00 00 00 00 00 00 00 01 00 00 01 00 00 01 00 00 01 00 00 00 00 01 00 00 01 01 00 00 01 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 
    08-25 12:55:26.662  1368  3139 I         : VSIP: cei::rcb (Success): 00 01 80 97 00 00 00 c1 00 00 51 50 01 01 02 00 01 00 00 00 00 00 00 00 00 00 00 00 00 01 00 00 01 00 00 01 00 00 01 00 00 00 00 01 00 00 01 01 00 00 01 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 

L20450     08-25 12:55:27.864  5428  5428 I com.patac.hmi.user-UserAccount: CalibrationDataSource:Calibration:MODEL=84
    08-25 12:55:27.864  5428  5428 I com.patac.hmi.user-UserAccount: UserFeatureManager:isModelTypeE22 isE22 = false
    08-25 12:55:27.864  5428  5428 I com.patac.hmi.user-UserAccount: CleaNewDriverHabitManager:dealDriverHabitResultEvent: seatResult is 0 leftMirrorResult is 0 rightMirrorResult is 0 mDriverMirrorFeedback 0 mPassengerMirrorFeedback 0
>>> 08-25 12:55:27.864  5428  5428 I com.patac.hmi.user-UserAccount: CleaNewDriverHabitManager:dealDriverHabitResultEvent mRestoreDriverHabitFlow is null
    08-25 12:55:27.871  1089  7406 I Bosch_NavSensors: AccUn:[2.537854, -2.691083, 9.033323, 0.000000, 0.000000, 0.000000, 1719349]
    08-25 12:55:27.871  1089  7406 I Bosch_NavSensors: Gravity:[0.000000, -2.668387, 9.436636, 3608412949402]
    08-25 12:55:27.879  1368  3146 I         : VSIP: cei::rcb (Success): 00 01 80 9c 00 00 00 0e 00 00 51 5d 01 01 02 00 01 03 0c 02 f9 21 

L20624     08-25 12:55:28.164  5428  5428 I com.patac.hmi.user-UserAccount: CalibrationDataSource:Calibration:MODEL=84
    08-25 12:55:28.164  5428  5428 I com.patac.hmi.user-UserAccount: UserFeatureManager:isModelTypeE22 isE22 = false
    08-25 12:55:28.164  5428  5428 I com.patac.hmi.user-UserAccount: CleaNewDriverHabitManager:dealDriverHabitResultEvent: seatResult is 0 leftMirrorResult is 0 rightMirrorResult is 0 mDriverMirrorFeedback 0 mPassengerMirrorFeedback 0
>>> 08-25 12:55:28.164  5428  5428 I com.patac.hmi.user-UserAccount: CleaNewDriverHabitManager:dealDriverHabitResultEvent mRestoreDriverHabitFlow is null
    08-25 12:55:28.184  5951  6023 D CPECallbackController: Dropping carPropertyEvent - propId: 291504647 areaId: 16777216  because getTimestamp(): 3608739639816 < nextUpdateTimeNanos: 3608839639816
    08-25 12:55:28.203  1371  1476 D GMVHAL  : setPropFromVehicle Property: VehicleProperty::PERF_STEERING_ANGLE AreaID: 16777216 Status: 0 floatValues: 7.5 
    08-25 12:55:28.211  4156  4156 I com.patac.hmi.media-ProgressHelper: [ProgressHelper]-PlaybackState is null:true,MediaInfo is null:true

⚠️ 搜索结果高度重复: 共 30 条匹配中，有 30 条内容相同 ('')。以上仅展示 15 条代表性结果。

---

[结果 2] 搜索结果: 共 40 条匹配，显示 15 条

L17080     08-25 12:55:22.434   732   732 I Calibrationd: [532501538040]CalibrationUsageLog.cpp::logUsage(34): Calibration Requested: com.patac.hmi.user: GMModel: ENUMERATION: [Module]GMModel: ENUMERATION: 84
    08-25 12:55:22.434  5428  5428 I com.patac.hmi.user-UserAccount: CalibrationDataSource:Calibration:MODEL=84
    08-25 12:55:22.434  5428  5428 I com.patac.hmi.user-UserAccount: UserFeatureManager:isModelTypeE22 isE22 = false
>>> 08-25 12:55:22.434  5428  5428 I com.patac.hmi.user-UserAccount: CleaNewDriverHabitManager:dealDriverHabitResultEvent: seatResult is 0 leftMirrorResult is 0 rightMirrorResult is 0 mDriverMirrorFeedback 2 mPassengerMirrorFeedback 0
    08-25 12:55:22.434  5428  5428 I com.patac.hmi.user-UserAccount: CleaNewDriverHabitManager:dealDriverHabitResultEvent mRestoreDriverHabitFlow is null
    08-25 12:55:22.439  4515  5201 I com.patac.hmi.settings-BaseTopicHandler: registerEventListener
    08-25 12:55:22.439  4515  5201 I com.patac.hmi.settings-BaseTopicHandler: result is not null

L17155     08-25 12:55:22.456   732   732 I Calibrationd: [532501538040]CalibrationUsageLog.cpp::logUsage(34): Calibration Requested: com.patac.hmi.user: GMModel: ENUMERATION: [Module]GMModel: ENUMERATION: 84
    08-25 12:55:22.457  5428  5428 I com.patac.hmi.user-UserAccount: CalibrationDataSource:Calibration:MODEL=84
    08-25 12:55:22.457  5428  5428 I com.patac.hmi.user-UserAccount: UserFeatureManager:isModelTypeE22 isE22 = false
>>> 08-25 12:55:22.457  5428  5428 I com.patac.hmi.user-UserAccount: CleaNewDriverHabitManager:dealDriverHabitResultEvent: seatResult is 0 leftMirrorResult is 0 rightMirrorResult is 0 mDriverMirrorFeedback 0 mPassengerMirrorFeedback 0
    08-25 12:55:22.457  4515  5201 I com.patac.hmi.settings-RearviewMirrorAdjustTopic: 32773--->makeResult: name: "OSRVM.left"
    08-25 12:55:22.457  5428  5428 I com.patac.hmi.user-UserAccount: CleaNewDriverHabitManager:dealDriverHabitResultEvent mRestoreDriverHabitFlow is null
    08-25 12:55:22.457  4515  5201 I com.patac.hmi.settings-RearviewMirrorAdjustTopic: horizontal_angle: -0.2

L17176     08-25 12:55:22.477  5428  5428 I com.patac.hmi.user-UserAccount: CleaNewDriverHabitManager:dealCustomEvent CLEA_DRIVER_HABIT_DATA_EVENT
    08-25 12:55:22.477  5428  5428 I com.patac.hmi.user-UserAccount: DriverHabitInfoUnit:updateCurrentHabitInfo
    08-25 12:55:22.477  5428  5428 I com.patac.hmi.user-UserAccount: UserFeatureManager:isMcuEnableDriverHabit mIsMcuEnableDriverHabit = true
>>> 08-25 12:55:22.477  5428  5428 I com.patac.hmi.user-UserAccount: CleaNewDriverHabitManager:dealDriverHabitDataEvent mHabitRestoreResult is null
    08-25 12:55:22.479  2371  2371 D PatacSwcHandlingService: diapatch KeyEvent KeyEvent { action=ACTION_DOWN, keyCode=KEYCODE_VOLUME_DOWN, scanCode=0, metaState=0, flags=0x0, repeatCount=6, eventTime=2369794000000, downTime=2369794000000, deviceId=0, source=0x101, displayId=0 } to HardKeyClient Callbac
    08-25 12:55:22.479  1089  7406 I Bosch_NavSensors: GyrUn:[-0.000266, -0.001332, 0.000799, 0.000000, 0.000000, 0.000000, 1713957]
    08-25 12:55:22.480  4515  5408 D HardKeyInterceptorManager: dispatchKeyEvent event = KeyEvent { action=ACTION_DOWN, keyCode=KEYCODE_VOLUME_DOWN, scanCode=0, metaState=0, flags=0x0, repeatCount=6, eventTime=2369794000000, downTime=2369794000000, deviceId=0, source=0x101, displayId=0 }

L17223     08-25 12:55:22.581  5428  5704 I com.patac.hmi.user-UserAccount: SystemInfoRepository:sendSystemEvent type is 4 id is  4201
    08-25 12:55:22.581  5428  5428 I com.patac.hmi.user-UserAccount: DriverHabitInfoUnit:updateCurrentHabitInfo
    08-25 12:55:22.581  5428  5428 I com.patac.hmi.user-UserAccount: UserFeatureManager:isMcuEnableDriverHabit mIsMcuEnableDriverHabit = true
>>> 08-25 12:55:22.581  5428  5428 I com.patac.hmi.user-UserAccount: CleaNewDriverHabitManager:dealDriverHabitDataEvent mHabitRestoreResult is null
    08-25 12:55:22.581  5428  5428 I com.patac.hmi.user-UserAccount: UserApplicationManager:get system event 4201
    08-25 12:55:22.581  5428  5428 I com.patac.hmi.user-UserAccount: CleaNewDriverHabitManager:dealCustomEvent CLEA_DRIVER_HABIT_DATA_EVENT
    08-25 12:55:22.581  5428  5428 I com.patac.hmi.user-UserAccount: DriverHabitInfoUnit:updateCurrentHabitInfo

L17290     08-25 12:55:22.688  5428  5428 I com.patac.hmi.user-UserAccount: CleaNewDriverHabitManager:dealCustomEvent CLEA_DRIVER_HABIT_DATA_EVENT
    08-25 12:55:22.688  5428  5428 I com.patac.hmi.user-UserAccount: DriverHabitInfoUnit:updateCurrentHabitInfo
    08-25 12:55:22.688  5428  5428 I com.patac.hmi.user-UserAccount: UserFeatureManager:isMcuEnableDriverHabit mIsMcuEnableDriverHabit = true
>>> 08-25 12:55:22.688  5428  5428 I com.patac.hmi.user-UserAccount: CleaNewDriverHabitManager:dealDriverHabitDataEvent mHabitRestoreResult is null
    08-25 12:55:22.691  4156  4156 I com.patac.hmi.media-ProgressHelper: [ProgressHelper]-PlaybackState is null:true,MediaInfo is null:true
    08-25 12:55:22.691  4156  4156 D com.patac.hmi.media-BTAudioManager: mPlayStateEmitter is null,Do nothing Or state is fast ward/rewind
    08-25 12:55:22.714  1089  7403 I Bosch_NavSensors: GnssSourceVIP::readerThread ipc_read ret time s 22 ms 999

L17375     08-25 12:55:22.731   732   732 I Calibrationd: [532501538040]CalibrationUsageLog.cpp::logUsage(34): Calibration Requested: com.patac.hmi.user: GMModel: ENUMERATION: [Module]GMModel: ENUMERATION: 84
    08-25 12:55:22.732  5428  5428 I com.patac.hmi.user-UserAccount: CalibrationDataSource:Calibration:MODEL=84
    08-25 12:55:22.732  5428  5428 I com.patac.hmi.user-UserAccount: UserFeatureManager:isModelTypeE22 isE22 = false
>>> 08-25 12:55:22.732  5428  5428 I com.patac.hmi.user-UserAccount: CleaNewDriverHabitManager:dealDriverHabitResultEvent: seatResult is 0 leftMirrorResult is 0 rightMirrorResult is 0 mDriverMirrorFeedback 0 mPassengerMirrorFeedback 0
    08-25 12:55:22.732  5428  5428 I com.patac.hmi.user-UserAccount: CleaNewDriverHabitManager:dealDriverHabitResultEvent mRestoreDriverHabitFlow is null
    08-25 12:55:22.732  4112  5115 D TimeResult: SystemClock: 3603273, ElapsedRealtimeMillis: 1892235
    08-25 12:55:22.732  4112  5115 D TimeResult: mTimeMillis: 1787632011696, AgeMillis: 1711038

L17405     08-25 12:55:22.735   732   732 I Calibrationd: [532501538040]CalibrationUsageLog.cpp::logUsage(34): Calibration Requested: com.patac.hmi.user: GMModel: ENUMERATION: [Module]GMModel: ENUMERATION: 84
    08-25 12:55:22.736  5428  5428 I com.patac.hmi.user-UserAccount: CalibrationDataSource:Calibration:MODEL=84
    08-25 12:55:22.736  5428  5428 I com.patac.hmi.user-UserAccount: UserFeatureManager:isModelTypeE22 isE22 = false
>>> 08-25 12:55:22.736  5428  5428 I com.patac.hmi.user-UserAccount: CleaNewDriverHabitManager:dealDriverHabitResultEvent: seatResult is 0 leftMirrorResult is 0 rightMirrorResult is 0 mDriverMirrorFeedback 0 mPassengerMirrorFeedback 0
    08-25 12:55:22.736  5428  5428 I com.patac.hmi.user-UserAccount: CleaNewDriverHabitManager:dealDriverHabitResultEvent mRestoreDriverHabitFlow is null
    08-25 12:55:22.740  1371  1476 D GMVHAL  : setPropFromVehicle Property: VendorProperty::LOCAL_TIME AreaID: 16777216 Status: 0 int32Values: 2026 8 25 12 55 22 
    08-25 12:55:22.740  1371  1476 D GMVHAL  : setPropFromVehicle Property: VendorProperty::UTC AreaID: 16777216 Status: 0 int32Values: 2026 8 25 4 55 22 

L17436     08-25 12:55:22.805  5428  5428 I com.patac.hmi.user-UserAccount: CleaNewD

... [截断: 原始结果 15,427 字符，已截取中间 427 字符] ...

DataEvent mHabitRestoreResult is null
    08-25 12:55:22.807  1368  3139 I         : VSIP: cei::rcb (Success): 00 01 80 fb 00 00 00 20 00 00 51 2a 01 01 02 00 01 00 00 00 00 00 00 00 00 4a 18 00 00 00 00 00 00 00 00 00 02 08 54 00 
    08-25 12:55:22.813  1089  7403 I Bosch_NavSensors: GnssSourceVIP::readerThread ipc_read ret time s 23 ms 80
    08-25 12:55:22.813  1089  1373 D Bosch_NavSensors: Nmea: 1787633723080 : $GPGGA,045523.08,3120.158739,N,12047.433599,E,1,10,0.0,24.7,M,,M,,*4F

L17478     08-25 12:55:22.914  5428  5428 I com.patac.hmi.user-UserAccount: CleaNewDriverHabitManager:dealCustomEvent CLEA_DRIVER_HABIT_DATA_EVENT
    08-25 12:55:22.914  5428  5428 I com.patac.hmi.user-UserAccount: DriverHabitInfoUnit:updateCurrentHabitInfo
    08-25 12:55:22.914  5428  5428 I com.patac.hmi.user-UserAccount: UserFeatureManager:isMcuEnableDriverHabit mIsMcuEnableDriverHabit = true
>>> 08-25 12:55:22.914  5428  5428 I com.patac.hmi.user-UserAccount: CleaNewDriverHabitManager:dealDriverHabitDataEvent mHabitRestoreResult is null
    08-25 12:55:22.925  1371  1443 D GMVHAL  : void KeyInputPropertyManager::onLongPressRepeatDelay(const std::vector<int32_t> &)
    08-25 12:55:22.925  1371  1443 D GMVHAL  : setPropFromVehicle Property: VehicleProperty::HW_KEY_INPUT AreaID: 16777216 Status: 0 int32Values: 0 25 0 
    08-25 12:55:22.925  2150  2234 D CAR.INPUT: hal event code: 25, action: 0, display: 0, number of indents: 1

L17530     08-25 12:55:23.030  5428  5428 I com.patac.hmi.user-UserAccount: CleaNewDriverHabitManager:dealCustomEvent CLEA_DRIVER_HABIT_DATA_EVENT
    08-25 12:55:23.030  5428  5428 I com.patac.hmi.user-UserAccount: DriverHabitInfoUnit:updateCurrentHabitInfo
    08-25 12:55:23.030  5428  5428 I com.patac.hmi.user-UserAccount: UserFeatureManager:isMcuEnableDriverHabit mIsMcuEnableDriverHabit = true
>>> 08-25 12:55:23.030  5428  5428 I com.patac.hmi.user-UserAccount: CleaNewDriverHabitManager:dealDriverHabitDataEvent mHabitRestoreResult is null
    08-25 12:55:23.030  4112  5019 D SDV_CoreService: [FrontLeftWindowTopicMapper]someIp sRlVCPWLSCurrSeltnVal: 2 drvWndAval: true drvWndCfg: true
    08-25 12:55:23.031  4112  5150 I SDV_CoreService: [ThirdRowLeftDoorSomeIpTopicMapper]SUCCESS: NOTIFY_BODY_INFORMATION_17
    08-25 12:55:23.031  4112  5150 D SDV_CoreService: [ThirdRowLeftDoorSomeIpTopicMapper]resp.getSRlVCPWLSCurrSeltnVal(): 2

L17585     08-25 12:55:23.035   732   732 I Calibrationd: [532501538040]CalibrationUsageLog.cpp::logUsage(34): Calibration Requested: com.patac.hmi.user: GMModel: ENUMERATION: [Module]GMModel: ENUMERATION: 84
    08-25 12:55:23.036  5428  5428 I com.patac.hmi.user-UserAccount: CalibrationDataSource:Calibration:MODEL=84
    08-25 12:55:23.036  5428  5428 I com.patac.hmi.user-UserAccount: UserFeatureManager:isModelTypeE22 isE22 = false
>>> 08-25 12:55:23.036  5428  5428 I com.patac.hmi.user-UserAccount: CleaNewDriverHabitManager:dealDriverHabitResultEvent: seatResult is 0 leftMirrorResult is 0 rightMirrorResult is 0 mDriverMirrorFeedback 0 mPassengerMirrorFeedback 0
    08-25 12:55:23.036  5428  5428 I com.patac.hmi.user-UserAccount: CleaNewDriverHabitManager:dealDriverHabitResultEvent mRestoreDriverHabitFlow is null
    08-25 12:55:23.056  1371  1476 D GMVHAL  : setPropFromVehicle Property: VendorProperty::POSITION_OFFSET_FROM_TRIM AreaID: 4 Status: 0 floatValues: -8 
    08-25 12:55:23.056  1371  1476 D GMVHAL  : setPropFromVehicle Property: PatacProperty::RIDE_HEIGHT_STATUS_4_SIGNAL_GROUP AreaID: 16777216 Status: 0 int32Values: -15 0 -8 0 -3 0 -18 0 

L17639     08-25 12:55:23.137  5428  5428 I com.patac.hmi.user-UserAccount: CleaNewDriverHabitManager:dealCustomEvent CLEA_DRIVER_HABIT_DATA_EVENT
    08-25 12:55:23.137  5428  5428 I com.patac.hmi.user-UserAccount: DriverHabitInfoUnit:updateCurrentHabitInfo
    08-25 12:55:23.137  5428  5428 I com.patac.hmi.user-UserAccount: UserFeatureManager:isMcuEnableDriverHabit mIsMcuEnableDriverHabit = true
>>> 08-25 12:55:23.137  5428  5428 I com.patac.hmi.user-UserAccount: CleaNewDriverHabitManager:dealDriverHabitDataEvent mHabitRestoreResult is null
    08-25 12:55:23.154  1089  7406 I Bosch_NavSensors: AccUn:[2.530671, -2.707842, 9.045294, 0.000000, 0.000000, 0.000000, 1714628]
    08-25 12:55:23.154  1089  7406 I Bosch_NavSensors: Gravity:[0.000000, -2.668532, 9.436594, 3603695138571]
    08-25 12:55:23.171  2425  7756 D FSANetCommsClient: FSARemoteClient RX QSize is: 0, funcID: 100, ID: 100

L17675     08-25 12:55:23.245  5428  5428 I com.patac.hmi.user-UserAccount: CleaNewDriverHabitManager:dealCustomEvent CLEA_DRIVER_HABIT_DATA_EVENT
    08-25 12:55:23.245  5428  5428 I com.patac.hmi.user-UserAccount: DriverHabitInfoUnit:updateCurrentHabitInfo
    08-25 12:55:23.245  5428  5428 I com.patac.hmi.user-UserAccount: UserFeatureManager:isMcuEnableDriverHabit mIsMcuEnableDriverHabit = true
>>> 08-25 12:55:23.245  5428  5428 I com.patac.hmi.user-UserAccount: CleaNewDriverHabitManager:dealDriverHabitDataEvent mHabitRestoreResult is null
    08-25 12:55:23.262  1089  7406 I Bosch_NavSensors: GyrUn:[0.000266, -0.000533, 0.000266, 0.000000, 0.000000, 0.000000, 1714737]
    08-25 12:55:23.272  1089  7406 I Bosch_NavSensors: AccUn:[2.540248, -2.700660, 9.040505, 0.000000, 0.000000, 0.000000, 1714747]
    08-25 12:55:23.272  1089  7406 I Bosch_NavSensors: Gravity:[0.000000, -2.668957, 9.436475, 3603813344821]

L17774     08-25 12:55:23.339   732   732 I Calibrationd: [532501538040]CalibrationUsageLog.cpp::logUsage(34): Calibration Requested: com.patac.hmi.user: GMModel: ENUMERATION: [Module]GMModel: ENUMERATION: 84
    08-25 12:55:23.339  5428  5428 I com.patac.hmi.user-UserAccount: CalibrationDataSource:Calibration:MODEL=84
    08-25 12:55:23.339  5428  5428 I com.patac.hmi.user-UserAccount: UserFeatureManager:isModelTypeE22 isE22 = false
>>> 08-25 12:55:23.339  5428  5428 I com.patac.hmi.user-UserAccount: CleaNewDriverHabitManager:dealDriverHabitResultEvent: seatResult is 0 leftMirrorResult is 0 rightMirrorResult is 0 mDriverMirrorFeedback 0 mPassengerMirrorFeedback 0
    08-25 12:55:23.339  5428  5428 I com.patac.hmi.user-UserAccount: CleaNewDriverHabitManager:dealDriverHabitResultEvent mRestoreDriverHabitFlow is null
    08-25 12:55:23.361  1371  1476 D GMVHAL  : setPropFromVehicle Property: PatacProperty::MIRROR_POSITION_STATUS AreaID: 1 Status: 0 floatValues: -8.8 -0.2 0 
    08-25 12:55:23.361  1371  1476 D GMVHAL  : setPropFromVehicle Property: PatacProperty::MIRROR_POSITION_STATUS AreaID: 2 Status: 0 floatValues: -5.2 0.1 0 

L17787     08-25 12:55:23.363  5428  5428 I com.patac.hmi.user-UserAccount: DriverHabitInfoUnit:updateCurrentHabitInfo
    08-25 12:55:23.363  5428  5704 I com.patac.hmi.user-UserAccount: DriverHabitMessageHandle:sendDriverHabitEvent afterCheck
    08-25 12:55:23.363  5428  5428 I com.patac.hmi.user-UserAccount: UserFeatureManager:isMcuEnableDriverHabit mIsMcuEnableDriverHabit = true
>>> 08-25 12:55:23.363  5428  5428 I com.patac.hmi.user-UserAccount: CleaNewDriverHabitManager:dealDriverHabitDataEvent mHabitRestoreResult is null
    08-25 12:55:23.364  5428  5704 I com.patac.hmi.user-UserAccount: SystemInfoRepository:sendSystemEvent type is 4 id is  4201
    08-25 12:55:23.364  5428  5428 I com.patac.hmi.user-UserAccount: UserApplicationManager:get system event 4201
    08-25 12:55:23.364  5428  5428 I com.patac.hmi.user-UserAccount: CleaNewDriverHabitManager:dealCustomEvent CLEA_DRIVER_HABIT_DATA_EVENT

⚠️ 搜索结果高度重复: 共 40 条匹配中，有 30 条内容相同 ('')。以上仅展示 15 条代表性结果。

---

[结果 3] 搜索结果: 共 30 条匹配，显示 15 条

L17085     08-25 12:55:22.439  4515  5201 I com.patac.hmi.settings-BaseTopicHandler: registerEventListener
    08-25 12:55:22.439  4515  5201 I com.patac.hmi.settings-BaseTopicHandler: result is not null
    08-25 12:55:22.439  4515  5201 I com.patac.hmi.settings-RearviewMirrorAdjustTopic: 32773--->makeResult: name: "OSRVM.left"
>>> 08-25 12:55:22.439  4515  5201 I com.patac.hmi.settings-RearviewMirrorAdjustTopic: responding_feature: MF_TILT_MIRROR
    08-25 12:55:22.439  4515  5201 I com.patac.hmi.settings-RearviewMirrorAdjustTopic: horizontal_angle: -0.2
    08-25 12:55:22.439  4515  5201 I com.patac.hmi.settings-RearviewMirrorAdjustTopic: vertical_angle: -5.6
    08-25 12:55:22.439  4515  5201 I com.patac.hmi.settings-RearviewMirrorAdjustTopic: is_supported: true

L22143     08-25 12:55:30.602  5428  5743 I com.patac.hmi.user-UserAccount: SystemInfoRepository:sendSystemEvent type is 4 id is  4202
    08-25 12:55:30.602  4515  5201 I com.patac.hmi.settings-RightRearviewMirrorAvailableTopic: 32774--->makeResult: name: "OSRVM.right"
    08-25 12:55:30.602  5428  5428 I com.patac.hmi.user-UserAccount: UserApplicationManager:get system event 4202
>>> 08-25 12:55:30.602  4515  5201 I com.patac.hmi.settings-RightRearviewMirrorAvailableTopic: responding_feature: MF_TILT_MIRROR
    08-25 12:55:30.602  4515  5201 I com.patac.hmi.settings-RightRearviewMirrorAvailableTopic: vertical_angle: -5.2
    08-25 12:55:30.602  4515  5201 I com.patac.hmi.settings-RightRearviewMirrorAvailableTopic: is_supported: true
    08-25 12:55:30.602  4515  5201 I com.patac.hmi.settings-RightRearviewMirrorAvailableTopic: , cacheData = Result{mBoolValue=true, mIntValue=0, mFloatValue=0.0, mState=0, mObject=null, mAvailable=1}

L22593     08-25 12:55:31.481  4515  5201 I com.patac.hmi.settings-BaseTopicHandler: result is not null
    08-25 12:55:31.481  5428  7822 D [ClsLinkSDK-v0.0.27] ClsLink: dispatchCloudEvent {id='1f1a0413-3092-697b-8f77-f3ea29b5da50'}; type=pub.v1
    08-25 12:55:31.481  4515  5201 I com.patac.hmi.settings-RightRearviewMirrorAvailableTopic: 32774--->makeResult: name: "OSRVM.right"
>>> 08-25 12:55:31.481  4515  5201 I com.patac.hmi.settings-RightRearviewMirrorAvailableTopic: responding_feature: MF_TILT_MIRROR
    08-25 12:55:31.481  4515  5201 I com.patac.hmi.settings-RightRearviewMirrorAvailableTopic: horizontal_angle: 0.1
    08-25 12:55:31.481  4515  5201 I com.patac.hmi.settings-RightRearviewMirrorAvailableTopic: vertical_angle: -5.2
    08-25 12:55:31.481  4515  5201 I com.patac.hmi.settings-RightRearviewMirrorAvailableTopic: is_supported: true

L22878     08-25 12:55:32.082  5428  5743 I com.patac.hmi.user-UserAccount: DriverHabitMessageHandle:dealPassengerMirrorFeedbackEvent 副驾后视镜反馈 is 2
    08-25 12:55:32.082  5428  5743 I com.patac.hmi.user-UserAccount: SystemInfoRepository:sendSystemEvent type is 4 id is  4202
    08-25 12:55:32.082  4515  5201 I com.patac.hmi.settings-RightRearviewMirrorAvailableTopic: 32774--->makeResult: name: "OSRVM.right"
>>> 08-25 12:55:32.082  4515  5201 I com.patac.hmi.settings-RightRearviewMirrorAvailableTopic: responding_feature: MF_TILT_MIRROR
    08-25 12:55:32.082  4515  5201 I com.patac.hmi.settings-RightRearviewMirrorAvailableTopic: vertical_angle: -5.2
    08-25 12:55:32.082  4515  5201 I com.patac.hmi.settings-RightRearviewMirrorAvailableTopic: is_supported: true
    08-25 12:55:32.082  4515  5201 I com.patac.hmi.settings-RightRearviewMirrorAvailableTopic: , cacheData = Result{mBoolValue=true, mIntValue=0, mFloatValue=0.0, mState=0, mObject=null, mAvailable=1}

L23248     08-25 12:55:32.988  4515  5201 I com.patac.hmi.settings-RightRearviewMirrorAvailableTopic: 32774--->makeResult: name: "OSRVM.right"
    08-25 12:55:32.988  5428  5428 I com.patac.hmi.user-UserAccount: UserApplicationManager:get system event 4202
    08-25 12:55:32.988  5428  5428 I com.patac.hmi.user-UserAccount: CleaNewDriverHabitManager:dealCustomEvent CLEA2_DRIVER_HABIT_RESULT_EVENT
>>> 08-25 12:55:32.988  4515  5201 I com.patac.hmi.settings-RightRearviewMirrorAvailableTopic: responding_feature: MF_TILT_MIRROR
    08-25 12:55:32.988  5428  5428 I com.patac.hmi.user-UserAccount: UserFeatureManager:isMcuEnableDriverHabit mIsMcuEnableDriverHabit = true
    08-25 12:55:32.988  4515  5201 I com.patac.hmi.settings-RightRearviewMirrorAvailableTopic: horizontal_angle: 0.1
    08-25 12:55:32.988  4515  5201 I com.patac.hmi.settings-RightRearviewMirrorAvailableTopic: vertical_angle: -5.2

L23390     08-25 12:55:33.288  4515  5201 I com.patac.hmi.settings-BaseTopicHandler: registerEventListener
    08-25 12:55:33.288  4515  5201 I com.patac.hmi.settings-BaseTopicHandler: result is not null
    08-25 12:55:33.288  4515  5201 I com.patac.hmi.settings-RightRearviewMirrorAvailableTopic: 32774--->makeResult: name: "OSRVM.right"
>>> 08-25 12:55:33.288  4515  5201 I com.patac.hmi.settings-RightRearviewMirrorAvailableTopic: responding_feature: MF_TILT_MIRROR
    08-25 12:55:33.288  4515  5201 I com.patac.hmi.settings-RightRearviewMirrorAvailableTopic: vertical_angle: -5.2
    08-25 12:55:33.288  4515  5201 I com.patac.hmi.settings-RightRearviewMirrorAvailableTopic: is_supported: true
    08-25 12:55:33.288  4515  5201 I com.patac.hmi.settings-RightRearviewMirrorAvailableTopic: , cacheData = Result{mBoolValue=true, mIntValue=0, mFloatValue=0.0, mState=0, mObject=null, mAvailable=1}

L69463     08-25 12:56:33.932  4515  5201 I com.patac.hmi.settings-BaseTopicHandler: registerEventListener
    08-25 12:56:33.933  4515  5201 I com.patac.hmi.settings-BaseTopicHandler: result is not null
    08-25 12:56:33.934  4515  5201 I com.patac.hmi.settings-RightRearviewMirrorAvailableTopic: 32774--->makeResult: name: "OSRVM.right"
>>> 08-25 12:56:33.934  4515  5201 I com.patac.hmi.settings-RightRearviewMirrorAvailableTopic: responding_feature: MF_TILT_MIRROR
    08-25 12:56:33.934  4515  5201 I com.patac.hmi.settings-RightRearviewMirrorAvailableTopic: horizontal_angle: 0.3
    08-25 12:56:33.934  4515  5201 I com.patac.hmi.settings-RightRearviewMirrorAvailableTopic: vertical_angle: 4.9
    08-25 12:56:33.934  4515  5201 I com.patac.hmi.settings-RightRearviewMirrorAvailableTopic: is_allowed: true

L69609     08-25 12:56:34.204  5428  5428 I com.patac.hmi.user-UserAccount: CleaNewDriverHabitManager:dealCustomEvent CLEA2_DRIVER_HABIT_RESULT_EVENT
    08-25 12:56:34.205  5428  5428 I com.patac.hmi.user-UserAccount: UserFeatureManager:isMcuEnableDriverHabit mIsMcuEnableDriverHabit = true
    08-25 12:56:34.205  4515  5201 I com.patac.hmi.settings-RightRearviewMirrorAvailableTopic: 32774--->makeResult: name: "OSRVM.right"
>>> 08-25 12:56:34.205  4515  5201 I com.patac.hmi.settings-RightRearviewMirrorAvailableTopic: responding_feature: MF_TILT_MIRROR
    08-25 12:56:34.205  4515  5201 I com.patac.hmi.settings-RightRearviewMirrorAvailableTopic: horizontal_angle: 0.1
    08-25 12:56:34.205  4515  5201 I com.patac.hmi.settings-RightRearviewMirrorAvailableTopic: vertical_angle: 4.9
    08-25 12:56:34.205   732   732 I Calibrationd: [532501538040]CalibrationUsageLog.cpp::logUsage(34): Calibration Requested: com.patac.hmi.user: GMModel: ENUMERATION: [Module]GMModel: ENUMERATION: 84

L69694     08-25 12:56:34.234  4515  5201 I com.patac.hmi.settings-BaseTopicHandler: registerEventListener
    08-25 12:56:34.234  4515  5201 I com.patac.hmi.settings-BaseTopicHandler: result is not null
    08-25 12:56:34.234  4515  5201 I com.patac.hmi.settings-RightRearviewMirrorAvailableTopic: 32774--->makeResult: name: "OSRVM.right"
>>> 08-25 12:56:34.234  4515  5201 I com.patac.hmi.settings-RightRearviewMirrorAvailableTopic: responding_feature: MF_TILT_MIRROR
    08-25 12:56:34.234  4515  5201 I com.patac.hmi.settings-RightRearviewMirrorAvailableTopic: horizontal_angle: 0.1
    08-25 12:56:34.234  4515  5201 I com.patac.hmi.settings-RightRearviewMirrorAvailableTopic: vertical_angle: 4.9
    08-25 12:56:34.234  4515  5201 I com.patac.hmi.settings-RightRearviewMirrorAvailableTopic: is_supported: true

L70003     08-25 12:56:34.504  5428  5743 I com.patac.hmi.user-UserAccount: DriverHabitMessageHandle:dealPassengerMirrorFeedbackEvent 副驾后视镜反馈 is 2
    08-25 12:56:34.504  5428  5743 I com.patac.hmi.user-UserAccount: SystemInfoRepository:sendSystemEvent type is 4 id is  4202
    08-25 12:56:34.504  4515  5201 I com.patac.hmi.settings-RightRearviewMirrorAvailableTopic: 32774--->makeResult: name: "OSRVM.right"
>>> 08-25 12:56:34.504  4515  5201 I com.patac.hmi.settings-RightRearviewMirrorAvailableTopic: responding_feature: MF_TILT_MIRROR
    08-25 12:56:34.504  4515  5201 I com.patac.hmi.settings-RightRearviewMirrorAvailableTopic: horizontal_angle: -0.1
    08-25 12:56:34.504  4515  5201 I com.patac.hmi.settings-RightRearviewMirrorAvailableTopic: vertical_angle: 4.4
    08-25 12:56:34.504  4515  5201 I com.patac.hmi.settings-RightRearviewMirrorAvailableTopic: is_supported: true

L70179     08-25 12:56:34.806  5428  5428 I com.patac.hmi.user-UserAccount: UserApplicationManager:get system event 4202
    08-25 12:56:34.806  4515  5201 I com.patac.hmi.settings-RightRearviewMirrorAvailableTopic: 32774--->makeResult: name: "OSRVM.right"
    08-25 12:56:34.806  5428  5428 I com.patac.hmi.user-UserAccount: CleaNewDriverHabitManager:dealCustomEvent CLEA2_DRIVER_HABIT_RESULT_EVENT
>>> 08-25 12:56:34.806  4515  5201 I com.patac.hmi.settings-RightRearviewMirrorAvailableTopic: responding_feature: MF_TILT_MIRROR
    08-25 12:56:34.806  4515  5201 I com.patac.hmi.settings-RightRearviewMirrorAvailableTopic: horizontal_angle: -0.1
    08-25 12:56:34.806  4515  5201 I com.patac.hmi.settings-RightRearviewMirrorAvailableTopic: vertical_angle: 3.3
    08-25 12:56:34.806  4515  5201 I com.patac.hmi.settings-RightRearviewMirrorAvailableTopic: is_supported: true

L70325     08-25 12:56:35.106  5428  5743 I com.patac.hmi.user-UserAccount: DriverHabitMessageHandle:dealPassengerMirrorFeedbackEvent 副驾后视镜反馈 is 2
    08-25 12:56:35.106  5428  5743 I com.patac.hmi.user-UserAccount: SystemInfoRepository:sendSystemEvent type is 4 id is  4202
    08-25 12:56:35.107  4515  5201 I com.patac.hmi.settings-RightRearviewMirrorAvailableTopic: 32774--->makeResult: name: "OSRVM.right"
>>> 08-25 12:56:35.107  4515  5201 I com.patac.hmi.settings-RightRearviewMirrorAvailableTopic: responding_feature: MF_TILT_MIRROR
    08-25 12:56:35.107  5428  5428 I com.patac.hmi.user-UserAccount: UserApplicationManager:get system event 4202
    08-25 12:56:35.107  4515  5201 I com.patac.hmi.settings-RightRearviewMirrorAvailableTopic: horizontal_angle: -0.1
    08-25 12:56:35.107  4515  5201 I com.patac.hmi.settings-RightRearviewMirrorAvailableTopic: vertical_angle: 2.5

L70515     08-25 12:56:35.414  5428  5428 I com.patac.hmi.user-UserAccount: CleaNewDriverHabitManager:dealDriverHabitResultEvent: seatResult is 0 leftMirrorResult is 0 rightMirrorResult is 0 mDriverMirrorFeedback 0 mPassengerMirrorFeedback 2
    08-25 12:56:35.414  5428  5428 I com.patac.hmi.user-UserAccount: CleaNewDriverHabitManager:dealDriverHabitResultEvent mRestoreDriverHabitFlow is null
    08-25 12:56:35.414  4515  5201 I com.patac.hmi.settings-RightRearviewMirrorAvailableTopic: 32774--->makeResult: name: "OSRVM.right"
>>> 08-25 12:56:35.414  4515  5201 I com.patac.hmi.settings-RightRearviewMirrorAvailableTopic: responding_feature: MF_TILT_MIRROR
    08-25 12:56:35.414  4515  5201 I com.patac.hmi.settings-RightRearviewMirrorAvailableTopic: horizontal_angle: -0.1
    08-25 12:56:35.414  4515  5201 I com.patac.hmi.settings-RightRearviewMirrorAvailableTopic: vertical_angle: 1.4
    08-25 12:56:35.414  4515  5201 I com.patac.hmi.settings-RightRearviewMirrorAvailableTopic: is_supported: true

L70662     08-25 12:56:35.711  5428  5743 I com.patac.hmi.user-UserAccount: SystemInfoRepository:sendSystemEvent type is 4 id is  4202
    08-25 12:56:35.712  4515  5201 I com.patac.hmi.settings-RightRearviewMirrorAvailableTopic: 32774--->makeResult: name: "OSRVM.right"
    08-25 12:56:35.712  5428  5428 I com.patac.hmi.user-UserAccount: UserApplicationManager:get system event 4202
>>> 08-25 12:56:35.712  4515  5201 I com.patac.hmi.settings-RightRearviewMirrorAvailableTopic: responding_feature: MF_TILT_MIRROR
    08-25 12:56:35.712  5428  5428 I com.patac.hmi.user-UserAccount: CleaNewDriverHabitManager:dealCustomEvent CLEA2_DRIVER_HABIT_RESULT_EVENT
    08-25 12:56:35.712  4515  5201 I com.patac.hmi.settings-RightRearviewMirrorAvailableTopic: horizontal_angle: -0.1
    08-25 12:56:35.712  5428  5428 I com.patac.hmi.user-UserAccount: UserFeatureManager:isMcuEnableDriverHabit mIsMcuEnableDriverHabit = true

L70819     08-25 12:56:36.015  5428  5743 I com.patac.hmi.user-UserAccount: RightMirrorFeatureHandle:dealDataChange data feature is 2
    08-25 12:56:36.015  5428  5743 I com.patac.hmi.user-UserAccount: SomeIpModule:dealRightMirrorFeatureChange 右后视镜反馈值 = 2
    08-25 12:56:36.015  4515  5201 I com.patac.hmi.settings-RightRearviewMirrorAvailableTopic: 32774--->makeResult: name: "OSRVM.right"
>>> 08-25 12:56:36.015  4515  5201 I com.patac.hmi.settings-RightRearviewMirrorAvailableTopic: responding_feature: MF_TILT_MIRROR
    08-25 12:56:36.015  5428  5743 I com.patac.hmi.user-UserAccount: DriverHabitMessageHandle:dealPassengerMirrorFeedbackEvent 副驾后视镜反馈 is 2
    08-25 12:56:36.015  4515  5201 I com.patac.hmi.settings-RightRearviewMirrorAvailableTopic: horizontal_angle: -0.1
    08-25 12:56:36.015  5428  5743 I com.patac.hmi.user-UserAccount: SystemInfoRepository:sendSystemEvent type is 4 id is  4202

⚠️ 搜索结果高度重复: 共 30 条匹配中，有 30 条内容相同 ('')。以上仅展示 15 条代表性结果。

---

## 第 12 轮 — LLM 响应

关键发现：`mHabitRestoreResult is null` 和 `mRestoreDriverHabitFlow is null` 持续出现，且 `dealDriverHabitResultEvent` 中 `mDriverMirrorFeedback 0`（之前是 2）。这说明记忆恢复流程始终未启动。

我需要理解 `CleaNewDriverHabitManager` 的完整逻辑，特别是 `mRestoreDriverHabitFlow` 何时被赋值、`mHabitRestoreResult` 何时被赋值。让我查阅知识库和读取关键时间段的完整上下文。



---

## 第 12 轮 — 工具执行结果

[结果 1] 搜索结果: 共 30 条匹配，显示 15 条

L17081     08-25 12:55:22.434  5428  5428 I com.patac.hmi.user-UserAccount: CalibrationDataSource:Calibration:MODEL=84
    08-25 12:55:22.434  5428  5428 I com.patac.hmi.user-UserAccount: UserFeatureManager:isModelTypeE22 isE22 = false
    08-25 12:55:22.434  5428  5428 I com.patac.hmi.user-UserAccount: CleaNewDriverHabitManager:dealDriverHabitResultEvent: seatResult is 0 leftMirrorResult is 0 rightMirrorResult is 0 mDriverMirrorFeedback 2 mPassengerMirrorFeedback 0
>>> 08-25 12:55:22.434  5428  5428 I com.patac.hmi.user-UserAccount: CleaNewDriverHabitManager:dealDriverHabitResultEvent mRestoreDriverHabitFlow is null
    08-25 12:55:22.439  4515  5201 I com.patac.hmi.settings-BaseTopicHandler: registerEventListener
    08-25 12:55:22.439  4515  5201 I com.patac.hmi.settings-BaseTopicHandler: result is not null
    08-25 12:55:22.439  4515  5201 I com.patac.hmi.settings-RearviewMirrorAdjustTopic: 32773--->makeResult: name: "OSRVM.left"

L17157     08-25 12:55:22.457  5428  5428 I com.patac.hmi.user-UserAccount: UserFeatureManager:isModelTypeE22 isE22 = false
    08-25 12:55:22.457  5428  5428 I com.patac.hmi.user-UserAccount: CleaNewDriverHabitManager:dealDriverHabitResultEvent: seatResult is 0 leftMirrorResult is 0 rightMirrorResult is 0 mDriverMirrorFeedback 0 mPassengerMirrorFeedback 0
    08-25 12:55:22.457  4515  5201 I com.patac.hmi.settings-RearviewMirrorAdjustTopic: 32773--->makeResult: name: "OSRVM.left"
>>> 08-25 12:55:22.457  5428  5428 I com.patac.hmi.user-UserAccount: CleaNewDriverHabitManager:dealDriverHabitResultEvent mRestoreDriverHabitFlow is null
    08-25 12:55:22.457  4515  5201 I com.patac.hmi.settings-RearviewMirrorAdjustTopic: horizontal_angle: -0.2
    08-25 12:55:22.457  4515  5201 I com.patac.hmi.settings-RearviewMirrorAdjustTopic: vertical_angle: -5.6
    08-25 12:55:22.457  4515  5201 I com.patac.hmi.settings-RearviewMirrorAdjustTopic: is_supported: true

L17376     08-25 12:55:22.732  5428  5428 I com.patac.hmi.user-UserAccount: CalibrationDataSource:Calibration:MODEL=84
    08-25 12:55:22.732  5428  5428 I com.patac.hmi.user-UserAccount: UserFeatureManager:isModelTypeE22 isE22 = false
    08-25 12:55:22.732  5428  5428 I com.patac.hmi.user-UserAccount: CleaNewDriverHabitManager:dealDriverHabitResultEvent: seatResult is 0 leftMirrorResult is 0 rightMirrorResult is 0 mDriverMirrorFeedback 0 mPassengerMirrorFeedback 0
>>> 08-25 12:55:22.732  5428  5428 I com.patac.hmi.user-UserAccount: CleaNewDriverHabitManager:dealDriverHabitResultEvent mRestoreDriverHabitFlow is null
    08-25 12:55:22.732  4112  5115 D TimeResult: SystemClock: 3603273, ElapsedRealtimeMillis: 1892235
    08-25 12:55:22.732  4112  5115 D TimeResult: mTimeMillis: 1787632011696, AgeMillis: 1711038
    08-25 12:55:22.732  4112  5115 D SDV_CoreService: [SomeIpUtil]publish event: uri: cls:/vehicle/1/OSRVM.right#OSRVM

L17406     08-25 12:55:22.736  5428  5428 I com.patac.hmi.user-UserAccount: CalibrationDataSource:Calibration:MODEL=84
    08-25 12:55:22.736  5428  5428 I com.patac.hmi.user-UserAccount: UserFeatureManager:isModelTypeE22 isE22 = false
    08-25 12:55:22.736  5428  5428 I com.patac.hmi.user-UserAccount: CleaNewDriverHabitManager:dealDriverHabitResultEvent: seatResult is 0 leftMirrorResult is 0 rightMirrorResult is 0 mDriverMirrorFeedback 0 mPassengerMirrorFeedback 0
>>> 08-25 12:55:22.736  5428  5428 I com.patac.hmi.user-UserAccount: CleaNewDriverHabitManager:dealDriverHabitResultEvent mRestoreDriverHabitFlow is null
    08-25 12:55:22.740  1371  1476 D GMVHAL  : setPropFromVehicle Property: VendorProperty::LOCAL_TIME AreaID: 16777216 Status: 0 int32Values: 2026 8 25 12 55 22 
    08-25 12:55:22.740  1371  1476 D GMVHAL  : setPropFromVehicle Property: VendorProperty::UTC AreaID: 16777216 Status: 0 int32Values: 2026 8 25 4 55 22 
    08-25 12:55:22.750  2015  2249 D nfsa.transport.out: /172.16.4.1:54590: Heartbeat( 100 ) Status, clientHandle = 0, service= 1026.1, 23 bytes

L17586     08-25 12:55:23.036  5428  5428 I com.patac.hmi.user-UserAccount: CalibrationDataSource:Calibration:MODEL=84
    08-25 12:55:23.036  5428  5428 I com.patac.hmi.user-UserAccount: UserFeatureManager:isModelTypeE22 isE22 = false
    08-25 12:55:23.036  5428  5428 I com.patac.hmi.user-UserAccount: CleaNewDriverHabitManager:dealDriverHabitResultEvent: seatResult is 0 leftMirrorResult is 0 rightMirrorResult is 0 mDriverMirrorFeedback 0 mPassengerMirrorFeedback 0
>>> 08-25 12:55:23.036  5428  5428 I com.patac.hmi.user-UserAccount: CleaNewDriverHabitManager:dealDriverHabitResultEvent mRestoreDriverHabitFlow is null
    08-25 12:55:23.056  1371  1476 D GMVHAL  : setPropFromVehicle Property: VendorProperty::POSITION_OFFSET_FROM_TRIM AreaID: 4 Status: 0 floatValues: -8 
    08-25 12:55:23.056  1371  1476 D GMVHAL  : setPropFromVehicle Property: PatacProperty::RIDE_HEIGHT_STATUS_4_SIGNAL_GROUP AreaID: 16777216 Status: 0 int32Values: -15 0 -8 0 -3 0 -18 0 
    08-25 12:55:23.056   730 10727 D android.hardware.thermal@2.0-service.gmvcu SensorsHalClient: Received temperature from Sensors HAL: 43.000000

L17775     08-25 12:55:23.339  5428  5428 I com.patac.hmi.user-UserAccount: CalibrationDataSource:Calibration:MODEL=84
    08-25 12:55:23.339  5428  5428 I com.patac.hmi.user-UserAccount: UserFeatureManager:isModelTypeE22 isE22 = false
    08-25 12:55:23.339  5428  5428 I com.patac.hmi.user-UserAccount: CleaNewDriverHabitManager:dealDriverHabitResultEvent: seatResult is 0 leftMirrorResult is 0 rightMirrorResult is 0 mDriverMirrorFeedback 0 mPassengerMirrorFeedback 0
>>> 08-25 12:55:23.339  5428  5428 I com.patac.hmi.user-UserAccount: CleaNewDriverHabitManager:dealDriverHabitResultEvent mRestoreDriverHabitFlow is null
    08-25 12:55:23.361  1371  1476 D GMVHAL  : setPropFromVehicle Property: PatacProperty::MIRROR_POSITION_STATUS AreaID: 1 Status: 0 floatValues: -8.8 -0.2 0 
    08-25 12:55:23.361  1371  1476 D GMVHAL  : setPropFromVehicle Property: PatacProperty::MIRROR_POSITION_STATUS AreaID: 2 Status: 0 floatValues: -5.2 0.1 0 
    08-25 12:55:23.362  5428  5704 I com.patac.hmi.user-UserAccount: CarDataSource:left mirror position:-8.8 -0.2 0.0 

L18021     08-25 12:55:23.638  5428  5428 I com.patac.hmi.user-UserAccount: CalibrationDataSource:Calibration:MODEL=84
    08-25 12:55:23.638  5428  5428 I com.patac.hmi.user-UserAccount: UserFeatureManager:isModelTypeE22 isE22 = false
    08-25 12:55:23.639  5428  5428 I com.patac.hmi.user-UserAccount: CleaNewDriverHabitManager:dealDriverHabitResultEvent: seatResult is 0 leftMirrorResult is 0 rightMirrorResult is 0 mDriverMirrorFeedback 0 mPassengerMirrorFeedback 0
>>> 08-25 12:55:23.639  5428  5428 I com.patac.hmi.user-UserAccount: CleaNewDriverHabitManager:dealDriverHabitResultEvent mRestoreDriverHabitFlow is null
    08-25 12:55:23.667  1371  1476 D GMVHAL  : setPropFromVehicle Property: VendorProperty::POSITION_OFFSET_FROM_TRIM AreaID: 4 Status: 0 floatValues: -7 
    08-25 12:55:23.668  1371  1476 D GMVHAL  : setPropFromVehicle Property: PatacProperty::RIDE_HEIGHT_STATUS_4_SIGNAL_GROUP AreaID: 16777216 Status: 0 int32Values: -15 0 -7 0 -3 0 -18 0 
    08-25 12:55:23.676  1371  1443 D GMVHAL  : void KeyInputPropertyManager::onLongPressRepeatDelay(const std::vector<int32_t> &)

L18202     08-25 12:55:23.943  5428  5428 I com.patac.hmi.user-UserAccount: CalibrationDataSource:Calibration:MODEL=84
    08-25 12:55:23.943  5428  5428 I com.patac.hmi.user-UserAccount: UserFeatureManager:isModelTypeE22 isE22 = false
    08-

... [截断: 原始结果 15,943 字符，已截取中间 943 字符] ...

c.hmi.user-UserAccount: UserFeatureManager:isModelTypeE22 isE22 = false
    08-25 12:55:24.242  5428  5428 I com.patac.hmi.user-UserAccount: CleaNewDriverHabitManager:dealDriverHabitResultEvent: seatResult is 0 leftMirrorResult is 0 rightMirrorResult is 0 mDriverMirrorFeedback 0 mPassengerMirrorFeedback 0
>>> 08-25 12:55:24.243  5428  5428 I com.patac.hmi.user-UserAccount: CleaNewDriverHabitManager:dealDriverHabitResultEvent mRestoreDriverHabitFlow is null
    08-25 12:55:24.243  1371  1459 I GMVHAL  : keyEvent keycode 25 EVENT 0
    08-25 12:55:24.243  1371  1459 D GMVHAL  : setPropFromVehicle Property: VehicleProperty::HW_KEY_INPUT AreaID: 16777216 Status: 0 int32Values: 1 25 0 
    08-25 12:55:24.243  1371  1459 D GMVHAL  : Unregister long press KEY 25 EVENT 0

L18808     08-25 12:55:25.145  5428  5428 I com.patac.hmi.user-UserAccount: CalibrationDataSource:Calibration:MODEL=84
    08-25 12:55:25.145  5428  5428 I com.patac.hmi.user-UserAccount: UserFeatureManager:isModelTypeE22 isE22 = false
    08-25 12:55:25.145  5428  5428 I com.patac.hmi.user-UserAccount: CleaNewDriverHabitManager:dealDriverHabitResultEvent: seatResult is 0 leftMirrorResult is 0 rightMirrorResult is 0 mDriverMirrorFeedback 0 mPassengerMirrorFeedback 0
>>> 08-25 12:55:25.145  5428  5428 I com.patac.hmi.user-UserAccount: CleaNewDriverHabitManager:dealDriverHabitResultEvent mRestoreDriverHabitFlow is null
    08-25 12:55:25.171  1371  1476 D GMVHAL  : setPropFromVehicle Property: PatacProperty::HORIZONTAL_DILUTION_OF_PRECISION AreaID: 16777216 Status: 0 floatValues: 0.5 
    08-25 12:55:25.172  2425  7756 D FSANetCommsClient: FSARemoteClient RX QSize is: 0, funcID: 100, ID: 100
    08-25 12:55:25.172  2425  7756 D FSAIStateOfHealthClient: FSARemoteClient FSA: handle heartbeat 853

L18924     08-25 12:55:25.449  5428  5428 I com.patac.hmi.user-UserAccount: CalibrationDataSource:Calibration:MODEL=84
    08-25 12:55:25.449  5428  5428 I com.patac.hmi.user-UserAccount: UserFeatureManager:isModelTypeE22 isE22 = false
    08-25 12:55:25.449  5428  5428 I com.patac.hmi.user-UserAccount: CleaNewDriverHabitManager:dealDriverHabitResultEvent: seatResult is 0 leftMirrorResult is 0 rightMirrorResult is 0 mDriverMirrorFeedback 0 mPassengerMirrorFeedback 0
>>> 08-25 12:55:25.449  5428  5428 I com.patac.hmi.user-UserAccount: CleaNewDriverHabitManager:dealDriverHabitResultEvent mRestoreDriverHabitFlow is null
    08-25 12:55:25.449  1371  1476 D GMVHAL  : setPropFromVehicle Property: PatacProperty::RIDE_HEIGHT_STATUS_4_SIGNAL_GROUP AreaID: 16777216 Status: 0 int32Values: -15 0 -7 0 -3 0 -18 0 
    08-25 12:55:25.449  1371  1476 D GMVHAL  : setPropFromVehicle Property: PatacProperty::FORWARD_LOOKING_LIGHT_LEVEL_EXTENDED AreaID: 16777216 Status: 0 int32Values: 36640 
    08-25 12:55:25.476  1089  7406 I Bosch_NavSensors: wheelTick: [620, 616,1236, 1716957 ]

L19598     08-25 12:55:26.355  5428  5428 I com.patac.hmi.user-UserAccount: UserFeatureManager:isModelTypeE22 isE22 = false
    08-25 12:55:26.355  4156  4851 I com.patac.hmi.media-BaseState: updateSourceList size:3
    08-25 12:55:26.355  5428  5428 I com.patac.hmi.user-UserAccount: CleaNewDriverHabitManager:dealDriverHabitResultEvent: seatResult is 0 leftMirrorResult is 0 rightMirrorResult is 0 mDriverMirrorFeedback 0 mPassengerMirrorFeedback 0
>>> 08-25 12:55:26.355  5428  5428 I com.patac.hmi.user-UserAccount: CleaNewDriverHabitManager:dealDriverHabitResultEvent mRestoreDriverHabitFlow is null
    08-25 12:55:26.355  4156  4851 I com.patac.hmi.media-BaseState: update provider
    08-25 12:55:26.355  4515  4515 I com.patac.hmi.settings-SettingItemValueSdvManager: 67<--someipHmi--disable-result---->Result{mBoolValue=true, mIntValue=0, mFloatValue=0.0, mState=0, mObject=null, mAvailable=1}
    08-25 12:55:26.355  4515  4515 D com.patac.hmi.settings-DriveMirrorDialogManager: requestDisableValueFromSdvSomeIp Value-onNext: 67, disable = false, type = 19

L19875     08-25 12:55:26.650  5428  5428 I com.patac.hmi.user-UserAccount: CalibrationDataSource:Calibration:MODEL=84
    08-25 12:55:26.650  5428  5428 I com.patac.hmi.user-UserAccount: UserFeatureManager:isModelTypeE22 isE22 = false
    08-25 12:55:26.650  5428  5428 I com.patac.hmi.user-UserAccount: CleaNewDriverHabitManager:dealDriverHabitResultEvent: seatResult is 0 leftMirrorResult is 0 rightMirrorResult is 0 mDriverMirrorFeedback 0 mPassengerMirrorFeedback 0
>>> 08-25 12:55:26.650  5428  5428 I com.patac.hmi.user-UserAccount: CleaNewDriverHabitManager:dealDriverHabitResultEvent mRestoreDriverHabitFlow is null
    08-25 12:55:26.655  2015  2249 D nfsa.transport.out: /172.16.4.1:54590: Heartbeat( 100 ) Status, clientHandle = 0, service= 1026.1, 23 bytes
    08-25 12:55:26.662  1368  3139 I         : VSIP: cei::rcb (Success): 00 01 80 97 00 00 00 c1 00 00 51 50 01 01 02 00 01 00 00 00 00 00 00 00 00 00 00 00 00 01 00 00 01 00 00 01 00 00 01 00 00 00 00 01 00 00 01 01 00 00 01 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 
    08-25 12:55:26.662  1368  3139 I         : VSIP: cei::rcb (Success): 00 01 80 97 00 00 00 c1 00 00 51 50 01 01 02 00 01 00 00 00 00 00 00 00 00 00 00 00 00 01 00 00 01 00 00 01 00 00 01 00 00 00 00 01 00 00 01 01 00 00 01 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 

L20450     08-25 12:55:27.864  5428  5428 I com.patac.hmi.user-UserAccount: CalibrationDataSource:Calibration:MODEL=84
    08-25 12:55:27.864  5428  5428 I com.patac.hmi.user-UserAccount: UserFeatureManager:isModelTypeE22 isE22 = false
    08-25 12:55:27.864  5428  5428 I com.patac.hmi.user-UserAccount: CleaNewDriverHabitManager:dealDriverHabitResultEvent: seatResult is 0 leftMirrorResult is 0 rightMirrorResult is 0 mDriverMirrorFeedback 0 mPassengerMirrorFeedback 0
>>> 08-25 12:55:27.864  5428  5428 I com.patac.hmi.user-UserAccount: CleaNewDriverHabitManager:dealDriverHabitResultEvent mRestoreDriverHabitFlow is null
    08-25 12:55:27.871  1089  7406 I Bosch_NavSensors: AccUn:[2.537854, -2.691083, 9.033323, 0.000000, 0.000000, 0.000000, 1719349]
    08-25 12:55:27.871  1089  7406 I Bosch_NavSensors: Gravity:[0.000000, -2.668387, 9.436636, 3608412949402]
    08-25 12:55:27.879  1368  3146 I         : VSIP: cei::rcb (Success): 00 01 80 9c 00 00 00 0e 00 00 51 5d 01 01 02 00 01 03 0c 02 f9 21 

L20624     08-25 12:55:28.164  5428  5428 I com.patac.hmi.user-UserAccount: CalibrationDataSource:Calibration:MODEL=84
    08-25 12:55:28.164  5428  5428 I com.patac.hmi.user-UserAccount: UserFeatureManager:isModelTypeE22 isE22 = false
    08-25 12:55:28.164  5428  5428 I com.patac.hmi.user-UserAccount: CleaNewDriverHabitManager:dealDriverHabitResultEvent: seatResult is 0 leftMirrorResult is 0 rightMirrorResult is 0 mDriverMirrorFeedback 0 mPassengerMirrorFeedback 0
>>> 08-25 12:55:28.164  5428  5428 I com.patac.hmi.user-UserAccount: CleaNewDriverHabitManager:dealDriverHabitResultEvent mRestoreDriverHabitFlow is null
    08-25 12:55:28.184  5951  6023 D CPECallbackController: Dropping carPropertyEvent - propId: 291504647 areaId: 16777216  because getTimestamp(): 3608739639816 < nextUpdateTimeNanos: 3608839639816
    08-25 12:55:28.203  1371  1476 D GMVHAL  : setPropFromVehicle Property: VehicleProperty::PERF_STEERING_ANGLE AreaID: 16777216 Status: 0 floatValues: 7.5 
    08-25 12:55:28.211  4156  4156 I com.patac.hmi.media-ProgressHelper: [ProgressHelper]-PlaybackState is null:true,MediaInfo is null:true

⚠️ 搜索结果高度重复: 共 30 条匹配中，有 30 条内容相同 ('')。以上仅展示 15 条代表性结果。

---

[结果 2] 搜索结果: 共 30 条匹配，显示 15 条

L17075     08-25 12:55:22.433  5428  5743 I com.patac.hmi.user-UserAccount: DriverHabitMessageHandle:dealDriverMirrorFeedbackEvent 主驾后视镜反馈 is 2
    08-25 12:55:22.434  5428  5743 I com.patac.hmi.user-UserAccount: SystemInfoRepository:sendSystemEvent type is 4 id is  4202
    08-25 12:55:22.434  5428  5428 I com.patac.hmi.user-UserAccount: UserApplicationManager:get system event 4202
>>> 08-25 12:55:22.434  5428  5428 I com.patac.hmi.user-UserAccount: CleaNewDriverHabitManager:dealCustomEvent CLEA2_DRIVER_HABIT_RESULT_EVENT
    08-25 12:55:22.434  5428  5428 I com.patac.hmi.user-UserAccount: UserFeatureManager:isMcuEnableDriverHabit mIsMcuEnableDriverHabit = true
    08-25 12:55:22.434   732   732 I Calibrationd: [532501538040]CalibrationUsageLog.cpp::logUsage(34): Calibration Requested: com.patac.hmi.user: GMModel: ENUMERATION: [Module]GMModel: ENUMERATION: 84
    08-25 12:55:22.434  5428  5428 I com.patac.hmi.user-UserAccount: CalibrationDataSource:Calibration:MODEL=84

L17149     08-25 12:55:22.456  4515  5201 I com.patac.hmi.settings-BaseTopicHandler: registerEventListener
    08-25 12:55:22.456  5428  5743 I com.patac.hmi.user-UserAccount: SystemInfoRepository:sendSystemEvent type is 4 id is  4202
    08-25 12:55:22.456  5428  5428 I com.patac.hmi.user-UserAccount: UserApplicationManager:get system event 4202
>>> 08-25 12:55:22.456  5428  5428 I com.patac.hmi.user-UserAccount: CleaNewDriverHabitManager:dealCustomEvent CLEA2_DRIVER_HABIT_RESULT_EVENT
    08-25 12:55:22.456  5428  5428 I com.patac.hmi.user-UserAccount: UserFeatureManager:isMcuEnableDriverHabit mIsMcuEnableDriverHabit = true
    08-25 12:55:22.456  4515  5201 I com.patac.hmi.settings-BaseTopicHandler: result is not null
    08-25 12:55:22.456   732   732 I Calibrationd: [532501538040]CalibrationUsageLog.cpp::logUsage(34): Calibration Requested: com.patac.hmi.user: GMModel: ENUMERATION: [Module]GMModel: ENUMERATION: 84

L17173     08-25 12:55:22.477  5428  5704 I com.patac.hmi.user-UserAccount: DriverHabitMessageHandle:sendDriverHabitEvent afterCheck
    08-25 12:55:22.477  5428  5704 I com.patac.hmi.user-UserAccount: SystemInfoRepository:sendSystemEvent type is 4 id is  4201
    08-25 12:55:22.477  5428  5428 I com.patac.hmi.user-UserAccount: UserApplicationManager:get system event 4201
>>> 08-25 12:55:22.477  5428  5428 I com.patac.hmi.user-UserAccount: CleaNewDriverHabitManager:dealCustomEvent CLEA_DRIVER_HABIT_DATA_EVENT
    08-25 12:55:22.477  5428  5428 I com.patac.hmi.user-UserAccount: DriverHabitInfoUnit:updateCurrentHabitInfo
    08-25 12:55:22.477  5428  5428 I com.patac.hmi.user-UserAccount: UserFeatureManager:isMcuEnableDriverHabit mIsMcuEnableDriverHabit = true
    08-25 12:55:22.477  5428  5428 I com.patac.hmi.user-UserAccount: CleaNewDriverHabitManager:dealDriverHabitDataEvent mHabitRestoreResult is null

L17219     08-25 12:55:22.581  5428  5704 I com.patac.hmi.user-UserAccount: CarDataSource:right mirror position:-5.2000003 0.0 0.0 
    08-25 12:55:22.581  5428  5428 I com.patac.hmi.user-UserAccount: UserApplicationManager:get system event 4201
    08-25 12:55:22.581  5428  5704 I com.patac.hmi.user-UserAccount: DriverHabitMessageHandle:sendDriverHabitEvent afterCheck
>>> 08-25 12:55:22.581  5428  5428 I com.patac.hmi.user-UserAccount: CleaNewDriverHabitManager:dealCustomEvent CLEA_DRIVER_HABIT_DATA_EVENT
    08-25 12:55:22.581  5428  5704 I com.patac.hmi.user-UserAccount: SystemInfoRepository:sendSystemEvent type is 4 id is  4201
    08-25 12:55:22.581  5428  5428 I com.patac.hmi.user-UserAccount: DriverHabitInfoUnit:updateCurrentHabitInfo
    08-25 12:55:22.581  5428  5428 I com.patac.hmi.user-UserAccount: UserFeatureManager:isMcuEnableDriverHabit mIsMcuEnableDriverHabit = true

L17287     08-25 12:55:22.688  5428  5704 I com.patac.hmi.user-UserAccount: DriverHabitMessageHandle:sendDriverHabitEvent afterCheck
    08-25 12:55:22.688  5428  5704 I com.patac.hmi.user-UserAccount: SystemInfoRepository:sendSystemEvent type is 4 id is  4201
    08-25 12:55:22.688  5428  5428 I com.patac.hmi.user-UserAccount: UserApplicationManager:get system event 4201
>>> 08-25 12:55:22.688  5428  5428 I com.patac.hmi.user-UserAccount: CleaNewDriverHabitManager:dealCustomEvent CLEA_DRIVER_HABIT_DATA_EVENT
    08-25 12:55:22.688  5428  5428 I com.patac.hmi.user-UserAccount: DriverHabitInfoUnit:updateCurrentHabitInfo
    08-25 12:55:22.688  5428  5428 I com.patac.hmi.user-UserAccount: UserFeatureManager:isMcuEnableDriverHabit mIsMcuEnableDriverHabit = true
    08-25 12:55:22.688  5428  5428 I com.patac.hmi.user-UserAccount: CleaNewDriverHabitManager:dealDriverHabitDataEvent mHabitRestoreResult is null

L17370     08-25 12:55:22.730  4515  4515 D com.patac.hmi.settings-DriveMirrorDialogManager: requestDisableValueFromSdvSomeIp Value-onNext: 66, disable = false, type = 19
    08-25 12:55:22.730  5428  5743 I com.patac.hmi.user-UserAccount: SystemInfoRepository:sendSystemEvent type is 4 id is  4202
    08-25 12:55:22.730  5428  5428 I com.patac.hmi.user-UserAccount: UserApplicationManager:get system event 4202
>>> 08-25 12:55:22.730  5428  5428 I com.patac.hmi.user-UserAccount: CleaNewDriverHabitManager:dealCustomEvent CLEA2_DRIVER_HABIT_RESULT_EVENT
    08-25 12:55:22.730  5428  5428 I com.patac.hmi.user-UserAccount: UserFeatureManager:isMcuEnableDriverHabit mIsMcuEnableDriverHabit = true
    08-25 12:55:22.731   732   732 I Calibrationd: [532501538040]CalibrationUsageLog.cpp::logUsage(34): Calibration Requested: com.patac.hmi.user: GMModel: ENUMERATION: [Module]GMModel: ENUMERATION: 84
    08-25 12:55:22.732  5428  5428 I com.patac.hmi.user-UserAccount: CalibrationDataSource:Calibration:MODEL=84

L17400     08-25 12:55:22.735  5428  5743 I com.patac.hmi.user-UserAccount: DriverHabitMessageHandle:dealPassengerMirrorFeedbackEvent 副驾后视镜反馈 is 0
    08-25 12:55:22.735  5428  5743 I com.patac.hmi.user-UserAccount: SystemInfoRepository:sendSystemEvent type is 4 id is  4202
    08-25 12:55:22.735  5428  5428 I com.patac.hmi.user-UserAccount: UserApplicationManager:get system event 4202
>>> 08-25 12:55:22.735  5428  5428 I com.patac.hmi.user-UserAccount: CleaNewDriverHabitManager:dealCustomEvent CLEA2_DRIVER_HABIT_RESULT_EVENT
    08-25 12:55:22.735  5428  5428 I com.patac.hmi.user-UserAccount: UserFeatureManager:isMcuEnableDriverHabit mIsMcuEnableDriverHabit = true
    08-25 12:55:22.735   732   732 I Calibrationd: [532501538040]CalibrationUsageLog.cpp::logUsage(34): Calibration Requested: com.patac.hmi.user: GMModel: ENUMERATION: [Module]GMModel: ENUMERATION: 84
    08-25 12:55:22.736  5428  5428 I com.patac.hmi.user-UserAccount: CalibrationDataSource:Calibration:MODEL=84

L17433     08-25 12:55:22.805  5428  5704 I com.patac.hmi.user-UserAccount: DriverHabitMessageHandle:sendDriverHabitEvent afterCheck
    08-25 12:55:22.805  5428  5704 I com.patac.hmi.user-UserAccount: SystemInfoRepository:sendSystemEvent type is 4 id is  4201
    08-25 12:55:22.805  5428  5428 I com.patac.hmi.user-UserAccount: UserApplicationManager:get system event 4201
>>> 08-25 12:55:22.805  5428  5428 I com.patac.hmi.user-UserAccount: CleaNewDriverHabitManager:dealCustomEvent CLEA_DRIVER_HABIT_DATA_EVENT
    08-25 12:55:22.805  5428  5428 I com.patac.hmi.user-UserAccount: DriverHabitInfoUnit:updateCurrentHabitInfo
    08-25 12:55:22.805  5428  5428 I com.patac.hmi.user-UserAccount: UserFeatureManager:isMcuEnableDriverHabit mIsMcuEnableDriverHabit = true
    08-25 12:55:22.805  5428  5428 I com.patac.hmi.user-UserAccount: CleaNewDriverHabitManager:dealDriverHabitDataEvent mHabitRestoreResult is null

L17475     08-25 12:55:22.913  5428  5704 I com.patac.hmi.user-UserAccount: DriverHabitMessageHandle:sendDriverHabitEvent afterCheck
    08-25 12:55:22.914  5428  5704 I com.patac.hmi.user-UserAccount: SystemInfoRepository:sendSystemEvent type is 4 id is  4201
    08-25 12:55:22.914  5428  5428 I com.patac.hmi.user-UserAccount: UserApplicationManager:get system event 4201
>>> 08-25 12:55:22.914  5428  5428 I com.patac.hmi.user-UserAccount: CleaNewDriverHabitManager:dealCustomEvent CLEA_DRIVER_HABIT_DATA_EVENT
    08-25 12:55:22.914  5428  5428 I com.patac.hmi.user-UserAccount: DriverHabitInfoUnit:updateCurrentHabitInfo
    08-25 12:55:22.914  5428  5428 I com.patac.hmi.user-UserAccount: UserFeatureManager:isMcuEnableDriverHabit mIsMcuEnableDriverHabit = true
    08-25 12:55:22.914  5428  5428 I com.patac.hmi.user-UserAccount: CleaNewDriverHabitManager:dealDriverHabitDataEvent mHabitRestoreResult is null

L17527     08-25 12:55:23.030  5428  5704 I com.patac.hmi.user-UserAccount: SystemInfoRepository:sendSystemEvent type is 4 id is  4201
    08-25 12:55:23.030  4112  5150 D SDV_CoreService: [SomeIpTopicReceiverManager]topic 2533279085461923
    08-25 12:55:23.030  5428  5428 I com.patac.hmi.user-UserAccount: UserApplicationManager:get system event 4201
>>> 08-25 12:55:23.030  5428  5428 I com.patac.hmi.user-UserAccount: CleaNewDriverHabitManager:dealCustomEvent CLEA_DRIVER_HABIT_DATA_EVENT
    08-25 12:55:23.030  5428  5428 I com.patac.hmi.user-UserAccount: DriverHabitInfoUnit:updateCurrentHabitInfo
    08-25 12:55:23.030  5428  5428 I com.patac.hmi.user-UserAccount: UserFeatureManager:isMcuEnableDriverHabit mIsMcuEnableDriverHabit = true
    08-25 12:55:23.030  5428  5428 I com.patac.hmi.user-UserAccount: CleaNewDriverHabitManager:dealDriverHabitDataEvent mHabitRestoreResult is null

L17580     08-25 12:55:23.035  5428  5743 I com.patac.hmi.user-UserAccount: DriverHabitMessageHandle:dealDriverMirrorFeedbackEvent 主驾后视镜反馈 is 0
    08-25 12:55:23.035  5428  5743 I com.patac.hmi.user-UserAccount: SystemInfoRepository:sendSystemEvent type is 4 id is  4202
    08-25 12:55:23.035  5428  5428 I com.patac.hmi.user-UserAccount: UserApplicationManager:get system event 4202
>>> 08-25 12:55:23.035  5428  5428 I com.patac.hmi.user-UserAccount: CleaNewDriverHabitManager:dealCustomEvent CLEA2_DRIVER_HABIT_RESULT_EVENT
    08-25 12:55:23.035  5428  5428 I com.patac.hmi.user-UserAccount: UserFeatureManager:isMcuEnableDriverHabit mIsMcuEnableDriverHabit = true
    08-25 12:55:23.035   732   732 I Calibrationd: [532501538040]CalibrationUsageLog.cpp::logUsage(34): Calibration Requested: com.patac.hmi.user: GMModel: ENUMERATION: [Module]GMModel: ENUMERATION: 84
    08-25 12:55:23.036  5428  5428 I com.patac.hmi.user-UserAccount: CalibrationDataSource:Calibration:MODEL=84

L17636     08-25 12:55:23.137  5428  5704 I com.patac.hmi.user-UserAccount: DriverHabitMessageHandle:sendDriverHabitEvent afterCheck
    08-25 12:55:23.137  5428  5704 I com.patac.hmi.user-UserAccount: SystemInfoRepository:sendSystemEvent type is 4 id is  4201
    08-25 12:55:23.137  5428  5428 I com.patac.hmi.user-UserAccount: UserApplicationManager:get system event 4201
>>> 08-25 12:55:23.137  5428  5428 I com.patac.hmi.user-UserAccount: CleaNewDriverHabitManager:dealCustomEvent CLEA_DRIVER_HABIT_DATA_EVENT
    08-25 12:55:23.137  5428  5428 I com.patac.hmi.user-UserAccount: DriverHabitInfoUnit:updateCurrentHabitInfo
    08-25 12:55:23.137  5428  5428 I com.patac.hmi.user-UserAccount: UserFeatureManager:isMcuEnableDriverHabit mIsMcuEnableDriverHabit = true
    08-25 12:55:23.137  5428  5428 I com.patac.hmi.user-UserAccount: CleaNewDriverHabitManager:dealDriverHabitDataEvent mHabitRestoreResult is null

L17672     08-25 12:55:23.245  5428  5704 I com.patac.hmi.user-UserAccount: DriverHabitMessageHandle:sendDriverHabitEvent afterCheck
    08-25 12:55:23.245  5428  5704 I com.patac.hmi.user-UserAccount: SystemInfoRepository:sendSystemEvent type is 4 id is  4201
    08-25 12:55:23.245  5428  5428 I com.patac.hmi.user-UserAccount: UserApplicationManager:get system event 4201
>>> 08-25 12:55:23.245  5428  5428 I com.patac.hmi.user-UserAccount: CleaNewDriverHabitManager:dealCustomEvent CLEA_DRIVER_HABIT_DATA_EVENT
    08-25 12:55:23.245  5428  5428 I com.patac.hmi.user-UserAccount: DriverHabitInfoUnit:updateCurrentHabitInfo
    08-25 12:55:23.245  5428  5428 I com.patac.hmi.user-UserAccount: UserFeatureManager:isMcuEnableDriverHabit mIsMcuEnableDriverHabit = true
    08-25 12:55:23.245  5428  5428 I com.patac.hmi.user-UserAccount: CleaNewDriverHabitManager:dealDriverHabitDataEvent mHabitRestoreResult is null

L17769     08-25 12:55:23.338  5428  5743 I com.patac.hmi.user-UserAccount: DriverHabitMessageHandle:dealDriverMirrorFeedbackEvent 主驾后视镜反馈 is 0
    08-25 12:55:23.338  5428  5743 I com.patac.hmi.user-UserAccount: SystemInfoRepository:sendSystemEvent type is 4 id is  4202
    08-25 12:55:23.338  5428  5428 I com.patac.hmi.user-UserAccount: UserApplicationManager:get system event 4202
>>> 08-25 12:55:23.338  5428  5428 I com.patac.hmi.user-UserAccount: CleaNewDriverHabitManager:dealCustomEvent CLEA2_DRIVER_HABIT_RESULT_EVENT
    08-25 12:55:23.339  5428  5428 I com.patac.hmi.user-UserAccount: UserFeatureManager:isMcuEnableDriverHabit mIsMcuEnableDriverHabit = true
    08-25 12:55:23.339   732   732 I Calibrationd: [532501538040]CalibrationUsageLog.cpp::logUsage(34): Calibration Requested: com.patac.hmi.user: GMModel: ENUMERATION: [Module]GMModel: ENUMERATION: 84
    08-25 12:55:23.339  5428  5428 I com.patac.hmi.user-UserAccount: CalibrationDataSource:Calibration:MODEL=84

L17783     08-25 12:55:23.363  5428  5704 I com.patac.hmi.user-UserAccount: SystemInfoRepository:sendSystemEvent type is 4 id is  4201
    08-25 12:55:23.363  5428  5428 I com.patac.hmi.user-UserAccount: UserApplicationManager:get system event 4201
    08-25 12:55:23.363  5428  5704 I com.patac.hmi.user-UserAccount: CarDataSource:right mirror position:-5.2000003 0.1 0.0 
>>> 08-25 12:55:23.363  5428  5428 I com.patac.hmi.user-UserAccount: CleaNewDriverHabitManager:dealCustomEvent CLEA_DRIVER_HABIT_DATA_EVENT
    08-25 12:55:23.363  5428  5428 I com.patac.hmi.user-UserAccount: DriverHabitInfoUnit:updateCurrentHabitInfo
    08-25 12:55:23.363  5428  5704 I com.patac.hmi.user-UserAccount: DriverHabitMessageHandle:sendDriverHabitEvent afterCheck
    08-25 12:55:23.363  5428  5428 I com.patac.hmi.user-UserAccount: UserFeatureManager:isMcuEnableDriverHabit mIsMcuEnableDriverHabit = true

⚠️ 搜索结果高度重复: 共 30 条匹配中，有 30 条内容相同 ('')。以上仅展示 15 条代表性结果。

---

[结果 3] 搜索结果: 共 30 条匹配，显示 15 条

L17174     08-25 12:55:22.477  5428  5704 I com.patac.hmi.user-UserAccount: SystemInfoRepository:sendSystemEvent type is 4 id is  4201
    08-25 12:55:22.477  5428  5428 I com.patac.hmi.user-UserAccount: UserApplicationManager:get system event 4201
    08-25 12:55:22.477  5428  5428 I com.patac.hmi.user-UserAccount: CleaNewDriverHabitManager:dealCustomEvent CLEA_DRIVER_HABIT_DATA_EVENT
>>> 08-25 12:55:22.477  5428  5428 I com.patac.hmi.user-UserAccount: DriverHabitInfoUnit:updateCurrentHabitInfo
    08-25 12:55:22.477  5428  5428 I com.patac.hmi.user-UserAccount: UserFeatureManager:isMcuEnableDriverHabit mIsMcuEnableDriverHabit = true
    08-25 12:55:22.477  5428  5428 I com.patac.hmi.user-UserAccount: CleaNewDriverHabitManager:dealDriverHabitDataEvent mHabitRestoreResult is null
    08-25 12:55:22.479  2371  2371 D PatacSwcHandlingService: diapatch KeyEvent KeyEvent { action=ACTION_DOWN, keyCode=KEYCODE_VOLUME_DOWN, scanCode=0, metaState=0, flags=0x0, repeatCount=6, eventTime=2369794000000, downTime=2369794000000, deviceId=0, source=0x101, displayId=0 } to HardKeyClient Callbac

L17221     08-25 12:55:22.581  5428  5704 I com.patac.hmi.user-UserAccount: DriverHabitMessageHandle:sendDriverHabitEvent afterCheck
    08-25 12:55:22.581  5428  5428 I com.patac.hmi.user-UserAccount: CleaNewDriverHabitManager:dealCustomEvent CLEA_DRIVER_HABIT_DATA_EVENT
    08-25 12:55:22.581  5428  5704 I com.patac.hmi.user-UserAccount: SystemInfoRepository:sendSystemEvent type is 4 id is  4201
>>> 08-25 12:55:22.581  5428  5428 I com.patac.hmi.user-UserAccount: DriverHabitInfoUnit:updateCurrentHabitInfo
    08-25 12:55:22.581  5428  5428 I com.patac.hmi.user-UserAccount: UserFeatureManager:isMcuEnableDriverHabit mIsMcuEnableDriverHabit = true
    08-25 12:55:22.581  5428  5428 I com.patac.hmi.user-UserAccount: CleaNewDriverHabitManager:dealDriverHabitDataEvent mHabitRestoreResult is null
    08-25 12:55:22.581  5428  5428 I com.patac.hmi.user-UserAccount: UserApplicationManager:get system event 4201

L17288     08-25 12:55:22.688  5428  5704 I com.patac.hmi.user-UserAccount: SystemInfoRepository:sendSystemEvent type is 4 id is  4201
    08-25 12:55:22.688  5428  5428 I com.patac.hmi.user-UserAccount: UserApplicationManager:get system event 4201
    08-25 12:55:22.688  5428  5428 I com.patac.hmi.user-UserAccount: CleaNewDriverHabitManager:dealCustomEvent CLEA_DRIVER_HABIT_DATA_EVENT
>>> 08-25 12:55:22.688  5428  5428 I com.patac.hmi.user-UserAccount: DriverHabitInfoUnit:updateCurrentHabitInfo
    08-25 12:55:22.688  5428  5428 I com.patac.hmi.user-UserAccount: UserFeatureManager:isMcuEnableDriverHabit mIsMcuEnableDriverHabit = true
    08-25 12:55:22.688  5428  5428 I com.patac.hmi.user-UserAccount: CleaNewDriverHabitManager:dealDriverHabitDataEvent mHabitRestoreResult is null
    08-25 12:55:22.691  4156  4156 I com.patac.hmi.media-ProgressHelper: [ProgressHelper]-PlaybackState is null:true,MediaInfo is null:true

L17434     08-25 12:55:22.805  5428  5704 I com.patac.hmi.user-UserAccount: SystemInfoRepository:sendSystemEvent type is 4 id is  4201
    08-25 12:55:22.805  5428  5428 I com.patac.hmi.user-UserAccount: UserApplicationManager:get system event 4201
    08-25 12:55:22.805  5428  5428 I com.patac.hmi.user-UserAccount: CleaNewDriverHabitManager:dealCustomEvent CLEA_DRIVER_HABIT_DATA_EVENT
>>> 08-25 12:55:22.805  5428  5428 I com.patac.hmi.user-UserAccount: DriverHabitInfoUnit:updateCurrentHabitInfo
    08-25 12:55:22.805  5428  5428 I com.patac.hmi.user-UserAccount: UserFeatureManager:isMcuEnableDriverHabit mIsMcuEnableDriverHabit = true
    08-25 12:55:22.805  5428  5428 I com.patac.hmi.user-UserAccount: CleaNewDriverHabitManager:dealDriverHabitDataEvent mHabitRestoreResult is null
    08-25 12:55:22.807  1368  3139 I         : VSIP: cei::rcb (Success): 00 01 80 fb 00 00 00 20 00 00 51 2a 01 01 02 00 01 00 00 00 00 00 00 00 00 4a 18 00 00 00 00 00 00 00 00 00 02 08 54 00 

L17476     08-25 12:55:22.914  5428  5704 I com.patac.hmi.user-UserAccount: SystemInfoRepository:sendSystemEvent type is 4 id is  4201
    08-25 12:55:22.914  5428  5428 I com.patac.hmi.user-UserAccount: UserApplicationManager:get system event 4201
    08-25 12:55:22.914  5428  5428 I com.patac.hmi.user-UserAccount: CleaNewDriverHabitManager:dealCustomEvent CLEA_DRIVER_HABIT_DATA_EVENT
>>> 08-25 12:55:22.914  5428  5428 I com.patac.hmi.user-UserAccount: DriverHabitInfoUnit:updateCurrentHabitInfo
    08-25 12:55:22.914  5428  5428 I com.patac.hmi.user-UserAccount: UserFeatureManager:isMcuEnableDriverHabit mIsMcuEnableDriverHabit = true
    08-25 12:55:22.914  5428  5428 I com.patac.hmi.user-UserAccount: CleaNewDriverHabitManager:dealDriverHabitDataEvent mHabitRestoreResult is null
    08-25 12:55:22.925  1371  1443 D GMVHAL  : void KeyInputPropertyManager::onLongPressRepeatDelay(const std::vector<int32_t> &)

L17528     08-25 12:55:23.030  4112  5150 D SDV_CoreService: [SomeIpTopicReceiverManager]topic 2533279085461923
    08-25 12:55:23.030  5428  5428 I com.patac.hmi.user-UserAccount: UserApplicationManager:get system event 4201
    08-25 12:55:23.030  5428  5428 I com.patac.hmi.user-UserAccount: CleaNewDriverHabitManager:dealCustomEvent CLEA_DRIVER_HABIT_DATA_EVENT
>>> 08-25 12:55:23.030  5428  5428 I com.patac.hmi.user-UserAccount: DriverHabitInfoUnit:updateCurrentHabitInfo
    08-25 12:55:23.030  5428  5428 I com.patac.hmi.user-UserAccount: UserFeatureManager:isMcuEnableDriverHabit mIsMcuEnableDriverHabit = true
    08-25 12:55:23.030  5428  5428 I com.patac.hmi.user-UserAccount: CleaNewDriverHabitManager:dealDriverHabitDataEvent mHabitRestoreResult is null
    08-25 12:55:23.030  4112  5019 D SDV_CoreService: [FrontLeftWindowTopicMapper]someIp sRlVCPWLSCurrSeltnVal: 2 drvWndAval: true drvWndCfg: true

L17637     08-25 12:55:23.137  5428  5704 I com.patac.hmi.user-UserAccount: SystemInfoRepository:sendSystemEvent type is 4 id is  4201
    08-25 12:55:23.137  5428  5428 I com.patac.hmi.user-UserAccount: UserApplicationManager:get system event 4201
    08-25 12:55:23.137  5428  5428 I com.patac.hmi.user-UserAccount: CleaNewDriverHabitManager:dealCustomEvent CLEA_DRIVER_HABIT_DATA_EVENT
>>> 08-25 12:55:23.137  5428  5428 I com.patac.hmi.user-UserAccount: DriverHabitInfoUnit:updateCurrentHabitInfo
    08-25 12:55:23.137  5428  5428 I com.patac.hmi.user-UserAccount: UserFeatureManager:isMcuEnableDriverHabit mIsMcuEnableDriverHabit = true
    08-25 12:55:23.137  5428  5428 I com.patac.hmi.user-UserAccount: CleaNewDriverHabitManager:dealDriverHabitDataEvent mHabitRestoreResult is null
    08-25 12:55:23.154  1089  7406 I Bosch_NavSensors: AccUn:[2.530671, -2.707842, 9.045294, 0.000000, 0.000000, 0.000000, 1714628]

L17673     08-25 12:55:23.245  5428  5704 I com.patac.hmi.user-UserAccount: SystemInfoRepository:sendSystemEvent type is 4 id is  4201
    08-25 12:55:23.245  5428  5428 I com.patac.hmi.user-UserAccount: UserApplicationManager:get system event 4201
    08-25 12:55:23.245  5428  5428 I com.patac.hmi.user-UserAccount: CleaNewDriverHabitManager:dealCustomEvent CLEA_DRIVER_HABIT_DATA_EVENT
>>> 08-25 12:55:23.245  5428  5428 I com.patac.hmi.user-UserAccount: DriverHabitInfoUnit:updateCurrentHabitInfo
    08-25 12:55:23.245  5428  5428 I com.patac.hmi.user-UserAccount: UserFeatureManager:isMcuEnableDriverHabit mIsMcuEnableDriverHabit = true
    08-25 12:55:23.245  5428  5428 I com.patac.hmi.user-UserAccount: CleaNewDriverHabitManager:dealDriverHabitDataEvent mHabitRestoreResult is null
    08-25 12:55:23.262  1089  7406 I Bosch_NavSensors: GyrUn:[0.000266, -0.000533, 0.000266, 0.000000, 0.000000, 0.000000, 1714737]

L17784     08-25 12:55:23.363  5428  5428 I com.patac.hmi.user-UserAccount: UserApplicationManager:get system event 4201
    08-25 12:55:23.363  5428  5704 I com.patac.hmi.user-UserAccount: CarDataSource:right mirror position:-5.2000003 0.1 0.0 
    08-25 12:55:23.363  5428  5428 I com.patac.hmi.user-UserAccount: CleaNewDriverHabitManager:dealCustomEvent CLEA_DRIVER_HABIT_DATA_EVENT
>>> 08-25 12:55:23.363  5428  5428 I com.patac.hmi.user-UserAccount: DriverHabitInfoUnit:updateCurrentHabitInfo
    08-25 12:55:23.363  5428  5704 I com.patac.hmi.user-UserAccount: DriverHabitMessageHandle:sendDriverHabitEvent afterCheck
    08-25 12:55:23.363  5428  5428 I com.patac.hmi.user-UserAccount: UserFeatureManager:isMcuEnableDriverHabit mIsMcuEnableDriverHabit = true
    08-25 12:55:23.363  5428  5428 I com.patac.hmi.user-UserAccount: CleaNewDriverHabitManager:dealDriverHabitDataEvent mHabitRestoreResult is null

L17791     08-25 12:55:23.364  5428  5704 I com.patac.hmi.user-UserAccount: SystemInfoRepository:sendSystemEvent type is 4 id is  4201
    08-25 12:55:23.364  5428  5428 I com.patac.hmi.user-UserAccount: UserApplicationManager:get system event 4201
    08-25 12:55:23.364  5428  5428 I com.patac.hmi.user-UserAccount: CleaNewDriverHabitManager:dealCustomEvent CLEA_DRIVER_HABIT_DATA_EVENT
>>> 08-25 12:55:23.364  5428  5428 I com.patac.hmi.user-UserAccount: DriverHabitInfoUnit:updateCurrentHabitInfo
    08-25 12:55:23.364  5428  5428 I com.patac.hmi.user-UserAccount: UserFeatureManager:isMcuEnableDriverHabit mIsMcuEnableDriverHabit = true
    08-25 12:55:23.364  5428  5428 I com.patac.hmi.user-UserAccount: CleaNewDriverHabitManager:dealDriverHabitDataEvent mHabitRestoreResult is null
    08-25 12:55:23.370  1371  1476 D GMVHAL  : setPropFromVehicle Property: VendorProperty::POSITION_OFFSET_FROM_TRIM AreaID: 4 Status: 0 floatValues: -7 

L17832     08-25 12:55:23.472  5428  5704 I com.patac.hmi.user-UserAccount: CarDataSource:right mirror position:-5.2000003 0.0 0.0 
    08-25 12:55:23.472  5428  5428 I com.patac.hmi.user-UserAccount: UserApplicationManager:get system event 4201
    08-25 12:55:23.472  5428  5428 I com.patac.hmi.user-UserAccount: CleaNewDriverHabitManager:dealCustomEvent CLEA_DRIVER_HABIT_DATA_EVENT
>>> 08-25 12:55:23.472  5428  5428 I com.patac.hmi.user-UserAccount: DriverHabitInfoUnit:updateCurrentHabitInfo
    08-25 12:55:23.472  5428  5704 I com.patac.hmi.user-UserAccount: DriverHabitMessageHandle:sendDriverHabitEvent afterCheck
    08-25 12:55:23.472  5428  5428 I com.patac.hmi.user-UserAccount: UserFeatureManager:isMcuEnableDriverHabit mIsMcuEnableDriverHabit = true
    08-25 12:55:23.472  5428  5704 I com.patac.hmi.user-UserAccount: SystemInfoRepository:sendSystemEvent type is 4 id is  4201

L17839     08-25 12:55:23.472  5428  5428 I com.patac.hmi.user-UserAccount: CleaNewDriverHabitManager:dealDriverHabitDataEvent mHabitRestoreResult is null
    08-25 12:55:23.472  5428  5428 I com.patac.hmi.user-UserAccount: UserApplicationManager:get system event 4201
    08-25 12:55:23.472  5428  5428 I com.patac.hmi.user-UserAccount: CleaNewDriverHabitManager:dealCustomEvent CLEA_DRIVER_HABIT_DATA_EVENT
>>> 08-25 12:55:23.472  5428  5428 I com.patac.hmi.user-UserAccount: DriverHabitInfoUnit:updateCurrentHabitInfo
    08-25 12:55:23.472  5428  5428 I com.patac.hmi.user-UserAccount: UserFeatureManager:isMcuEnableDriverHabit mIsMcuEnableDriverHabit = true
    08-25 12:55:23.473  5428  5428 I com.patac.hmi.user-UserAccount: CleaNewDriverHabitManager:dealDriverHabitDataEvent mHabitRestoreResult is null
    08-25 12:55:23.475  1371  1443 D GMVHAL  : void KeyInputPropertyManager::onLongPressRepeatDelay(const std::vector<int32_t> &)

L17912     08-25 12:55:23.581  5428  5704 I com.patac.hmi.user-UserAccount: SystemInfoRepository:sendSystemEvent type is 4 id is  4201
    08-25 12:55:23.582  5428  5428 I com.patac.hmi.user-UserAccount: UserApplicationManager:get system event 4201
    08-25 12:55:23.582  5428  5428 I com.patac.hmi.user-UserAccount: CleaNewDriverHabitManager:dealCustomEvent CLEA_DRIVER_HABIT_DATA_EVENT
>>> 08-25 12:55:23.582  5428  5428 I com.patac.hmi.user-UserAccount: DriverHabitInfoUnit:updateCurrentHabitInfo
    08-25 12:55:23.582  5428  5428 I com.patac.hmi.user-UserAccount: UserFeatureManager:isMcuEnableDriverHabit mIsMcuEnableDriverHabit = true
    08-25 12:55:23.582  5428  5428 I com.patac.hmi.user-UserAccount: CleaNewDriverHabitManager:dealDriverHabitDataEvent mHabitRestoreResult is null
    08-25 12:55:23.583  5951  6023 D CPECallbackController: Dropping carPropertyEvent - propId: 291504647 areaId: 16777216  because getTimestamp(): 3604139639816 < nextUpdateTimeNanos: 3604339639816

L18040     08-25 12:55:23.686  5428  5704 I com.patac.hmi.user-UserAccount: SystemInfoRepository:sendSystemEvent type is 4 id is  4201
    08-25 12:55:23.686  5428  5428 I com.patac.hmi.user-UserAccount: UserApplicationManager:get system event 4201
    08-25 12:55:23.686  5428  5428 I com.patac.hmi.user-UserAccount: CleaNewDriverHabitManager:dealCustomEvent CLEA_DRIVER_HABIT_DATA_EVENT
>>> 08-25 12:55:23.686  5428  5428 I com.patac.hmi.user-UserAccount: DriverHabitInfoUnit:updateCurrentHabitInfo
    08-25 12:55:23.686  5428  5428 I com.patac.hmi.user-UserAccount: UserFeatureManager:isMcuEnableDriverHabit mIsMcuEnableDriverHabit = true
    08-25 12:55:23.686  5428  5428 I com.patac.hmi.user-UserAccount: CleaNewDriverHabitManager:dealDriverHabitDataEvent mHabitRestoreResult is null
    08-25 12:55:23.690   744   995 D vendor.bosch.hardware.broadcastradio@2.0-service: [libtda7708]: tuner_Ping start

L18090     08-25 12:55:23.805  5428  5704 I com.patac.hmi.user-UserAccount: SystemInfoRepository:sendSystemEvent type is 4 id is  4201
    08-25 12:55:23.806  5428  5428 I com.patac.hmi.user-UserAccount: UserApplicationManager:get system event 4201
    08-25 12:55:23.806  5428  5428 I com.patac.hmi.user-UserAccount: CleaNewDriverHabitManager:dealCustomEvent CLEA_DRIVER_HABIT_DATA_EVENT
>>> 08-25 12:55:23.806  5428  5428 I com.patac.hmi.user-UserAccount: DriverHabitInfoUnit:updateCurrentHabitInfo
    08-25 12:55:23.806  5428  5428 I com.patac.hmi.user-UserAccount: UserFeatureManager:isMcuEnableDriverHabit mIsMcuEnableDriverHabit = true
    08-25 12:55:23.806  5428  5428 I com.patac.hmi.user-UserAccount: CleaNewDriverHabitManager:dealDriverHabitDataEvent mHabitRestoreResult is null
    08-25 12:55:23.816  1368  3146 I         : VSIP: cei::rcb (Success): 00 01 80 fb 00 00 00 20 00 00 51 33 01 01 02 00 01 00 00 00 00 00 00 00 00 4a 18 00 00 00 00 00 00 00 00 00 02 08 54 00 

⚠️ 搜索结果高度重复: 共 30 条匹配中，有 30 条内容相同 ('')。以上仅展示 15 条代表性结果。

---

## 第 13 轮 — LLM 响应

关键发现：`DriverHabitMessageHandle:sendDriverHabitEvent afterCheck` 和 `dealPassengerMirrorFeedbackEvent 副驾后视镜反馈 is 0`。我需要理解 `sendDriverHabitEvent` 和 `afterCheck` 的完整逻辑，以及 `mRestoreDriverHabitFlow` 何时被赋值。

让我读取关键时间段的完整上下文，理解记忆恢复流程的启动条件。



---

## 第 13 轮 — 工具执行结果

[结果 1] 时间范围 [12:55:22.400 ~ 12:55:23.000] (PID=5428): 共 140 行
涉及的 PID: 5428
涉及的 TAG: [ClsLinkSDK-v0.0.27] ClsLink, com.patac.hmi.user-UserAccount

08-25 12:55:23.030  5428  5704 I com.patac.hmi.user-UserAccount: CarDataSource:left mirror position:-7.8 -0.2 0.0 
08-25 12:55:23.030  5428  5704 I com.patac.hmi.user-UserAccount: DriverHabitMessageHandle:sendDriverHabitEvent afterCheck
08-25 12:55:23.030  5428  5704 I com.patac.hmi.user-UserAccount: SystemInfoRepository:sendSystemEvent type is 4 id is  4201
08-25 12:55:23.030  5428  5428 I com.patac.hmi.user-UserAccount: UserApplicationManager:get system event 4201
08-25 12:55:23.030  5428  5428 I com.patac.hmi.user-UserAccount: CleaNewDriverHabitManager:dealCustomEvent CLEA_DRIVER_HABIT_DATA_EVENT
08-25 12:55:23.030  5428  5428 I com.patac.hmi.user-UserAccount: DriverHabitInfoUnit:updateCurrentHabitInfo
08-25 12:55:23.030  5428  5428 I com.patac.hmi.user-UserAccount: UserFeatureManager:isMcuEnableDriverHabit mIsMcuEnableDriverHabit = true
08-25 12:55:23.030  5428  5428 I com.patac.hmi.user-UserAccount: CleaNewDriverHabitManager:dealDriverHabitDataEvent mHabitRestoreResult is null
08-25 12:55:23.035  5428  6558 D [ClsLinkSDK-v0.0.27] ClsLink: dispatchCloudEvent {id='1f1a0412-e00d-6ca3-8f77-f3ea29b5da50'}; type=pub.v1
08-25 12:55:23.035  5428  5743 I com.patac.hmi.user-UserAccount: LeftMirrorFeatureHandle:result is not null
08-25 12:55:23.035  5428  5743 I com.patac.hmi.user-UserAccount: LeftMirrorFeatureHandle:dealDataChange data feature is 0
08-25 12:55:23.035  5428  5743 I com.patac.hmi.user-UserAccount: SomeIpModule:dealLeftMirrorFeatureChange 左后视镜反馈值 = 0
08-25 12:55:23.035  5428  5743 I com.patac.hmi.user-UserAccount: DriverHabitMessageHandle:dealDriverMirrorFeedbackEvent 主驾后视镜反馈 is 0
08-25 12:55:23.035  5428  5743 I com.patac.hmi.user-UserAccount: SystemInfoRepository:sendSystemEvent type is 4 id is  4202
08-25 12:55:23.035  5428  5428 I com.patac.hmi.user-UserAccount: UserApplicationManager:get system event 4202
08-25 12:55:23.035  5428  5428 I com.patac.hmi.user-UserAccount: CleaNewDriverHabitManager:dealCustomEvent CLEA2_DRIVER_HABIT_RESULT_EVENT
08-25 12:55:23.035  5428  5428 I com.patac.hmi.user-UserAccount: UserFeatureManager:isMcuEnableDriverHabit mIsMcuEnableDriverHabit = true
08-25 12:55:23.036  5428  5428 I com.patac.hmi.user-UserAccount: CalibrationDataSource:Calibration:MODEL=84
08-25 12:55:23.036  5428  5428 I com.patac.hmi.user-UserAccount: UserFeatureManager:isModelTypeE22 isE22 = false
08-25 12:55:23.036  5428  5428 I com.patac.hmi.user-UserAccount: CleaNewDriverHabitManager:dealDriverHabitResultEvent: seatResult is 0 leftMirrorResult is 0 rightMirrorResult is 0 mDriverMirrorFeedback 0 mPassengerMirrorFeedback 0
08-25 12:55:23.036  5428  5428 I com.patac.hmi.user-UserAccount: CleaNewDriverHabitManager:dealDriverHabitResultEvent mRestoreDriverHabitFlow is null
08-25 12:55:23.137  5428  5704 I com.patac.hmi.user-UserAccount: CarDataSource:left mirror position:-8.1 -0.2 0.0 
08-25 12:55:23.137  5428  5704 I com.patac.hmi.user-UserAccount: DriverHabitMessageHandle:sendDriverHabitEvent afterCheck
08-25 12:55:23.137  5428  5704 I com.patac.hmi.user-UserAccount: SystemInfoRepository:sendSystemEvent type is 4 id is  4201
08-25 12:55:23.137  5428  5428 I com.patac.hmi.user-UserAccount: UserApplicationManager:get system event 4201
08-25 12:55:23.137  5428  5428 I com.patac.hmi.user-UserAccount: CleaNewDriverHabitManager:dealCustomEvent CLEA_DRIVER_HABIT_DATA_EVENT
08-25 12:55:23.137  5428  5428 I com.patac.hmi.user-UserAccount: DriverHabitInfoUnit:updateCurrentHabitInfo
08-25 12:55:23.137  5428  5428 I com.patac.hmi.user-UserAccount: UserFeatureManager:isMcuEnableDriverHabit mIsMcuEnableDriverHabit = true
08-25 12:55:23.137  5428  5428 I com.patac.hmi.user-UserAccount: CleaNewDriverHabitManager:dealDriverHabitDataEvent mHabitRestoreResult is null
08-25 12:55:23.245  5428  5704 I com.patac.hmi.user-UserAccount: CarDataSource:left mirror position:-8.5 -0.2 0.0 
08-25 12:55:23.245  5428  5704 I com.patac.hmi.user-UserAccount: DriverHabitMessageHandle:sendDriverHabitEvent afterCheck
08-25 12:55:23.245  5428  5704 I com.patac.hmi.user-UserAccount: SystemInfoRepository:sendSystemEvent type is 4 id is  4201
08-25 12:55:23.245  5428  5428 I com.patac.hmi.user-UserAccount: UserApplicationManager:get system event 4201
08-25 12:55:23.245  5428  5428 I com.patac.hmi.user-UserAccount: CleaNewDriverHabitManager:dealCustomEvent CLEA_DRIVER_HABIT_DATA_EVENT
08-25 12:55:23.245  5428  5428 I com.patac.hmi.user-UserAccount: DriverHabitInfoUnit:updateCurrentHabitInfo
08-25 12:55:23.245  5428  5428 I com.patac.hmi.user-UserAccount: UserFeatureManager:isMcuEnableDriverHabit mIsMcuEnableDriverHabit = true
08-25 12:55:23.245  5428  5428 I com.patac.hmi.user-UserAccount: CleaNewDriverHabitManager:dealDriverHabitDataEvent mHabitRestoreResult is null
08-25 12:55:23.338  5428  6558 D [ClsLinkSDK-v0.0.27] ClsLink: dispatchCloudEvent {id='1f1a0412-e2ea-6364-8f77-f3ea29b5da50'}; type=pub.v1
08-25 12:55:23.338  5428  5743 I com.patac.hmi.user-UserAccount: LeftMirrorFeatureHandle:result is not null
08-25 12:55:23.338  5428  5743 I com.patac.hmi.user-UserAccount: LeftMirrorFeatureHandle:dealDataChange data feature is 0
08-25 12:55:23.338  5428  5743 I com.patac.hmi.user-UserAccount: SomeIpModule:dealLeftMirrorFeatureChange 左后视镜反馈值 = 0
08-25 12:55:23.338  5428  5743 I com.patac.hmi.user-UserAccount: DriverHabitMessageHandle:dealDriverMirrorFeedbackEvent 主驾后视镜反馈 is 0
08-25 12:55:23.338  5428  5743 I com.patac.hmi.user-UserAccount: SystemInfoRepository:sendSystemEvent type is 4 id is  4202
08-25 12:55:23.338  5428  5428 I com.patac.hmi.user-UserAccount: UserApplicationManager:get system event 4202
08-25 12:55:23.338  5428  5428 I com.patac.hmi.user-UserAccount: CleaNewDriverHabitManager:dealCustomEvent CLEA2_DRIVER_HABIT_RESULT_EVENT
08-25 12:55:23.339  5428  5428 I com.patac.hmi.user-UserAccount: UserFeatureManager:isMcuEnableDriverHabit mIsMcuEnableDriverHabit = true
08-25 12:55:23.339  5428  5428 I com.patac.hmi.user-UserAccount: CalibrationDataSource:Calibration:MODEL=84
08-25 12:55:23.339  5428  5428 I com.patac.hmi.user-UserAccount: UserFeatureManager:isModelTypeE22 isE22 = false
08-25 12:55:23.339  5428  5428 I com.patac.hmi.user-UserAccount: CleaNewDriverHabitManager:dealDriverHabitResultEvent: seatResult is 0 leftMirrorResult is 0 rightMirrorResult is 0 mDriverMirrorFeedback 0 mPassengerMirrorFeedback 0
08-25 12:55:23.339  5428  5428 I com.patac.hmi.user-UserAccount: CleaNewDriverHabitManager:dealDriverHabitResultEvent mRestoreDriverHabitFlow is null
08-25 12:55:23.362  5428  5704 I com.patac.hmi.user-UserAccount: CarDataSource:left mirror position:-8.8 -0.2 0.0 
08-25 12:55:23.363  5428  5704 I com.patac.hmi.user-UserAccount: DriverHabitMessageHandle:sendDriverHabitEvent afterCheck
08-25 12:55:23.363  5428  5704 I com.patac.hmi.user-UserAccount: SystemInfoRepository:sendSystemEvent type is 4 id is  4201
08-25 12:55:23.363  5428  5428 I com.patac.hmi.user-UserAccount: UserApplicationManager:get system event 4201
08-25 12:55:23.363  5428  5704 I com.patac.hmi.user-UserAccount: CarDataSource:right mirror position:-5.2000003 0.1 0.0 
08-25 12:55:23.363  5428  5428 I com.patac.hmi.user-UserAccount: CleaNewDriverHabitManager:dealCustomEvent CLEA_DRIVER_HABIT_DATA_EVENT
08-25 12:55:23.363  5428  5428 I com.patac.hmi.user-UserAccount: DriverHabitInfoUnit:updateCurrentHabitInfo
08-25 12:55:23.363  5428  5704 I com.patac.hmi.user-UserAcco

... [截断: 原始结果 18,060 字符，已截取中间 3,060 字符] ...

rHabitDataEvent mHabitRestoreResult is null
08-25 12:55:23.581  5428  5704 I com.patac.hmi.user-UserAccount: CarDataSource:left mirror position:-9.6 -0.2 0.0 
08-25 12:55:23.581  5428  5704 I com.patac.hmi.user-UserAccount: DriverHabitMessageHandle:sendDriverHabitEvent afterCheck
08-25 12:55:23.581  5428  5704 I com.patac.hmi.user-UserAccount: SystemInfoRepository:sendSystemEvent type is 4 id is  4201
08-25 12:55:23.582  5428  5428 I com.patac.hmi.user-UserAccount: UserApplicationManager:get system event 4201
08-25 12:55:23.582  5428  5428 I com.patac.hmi.user-UserAccount: CleaNewDriverHabitManager:dealCustomEvent CLEA_DRIVER_HABIT_DATA_EVENT
08-25 12:55:23.582  5428  5428 I com.patac.hmi.user-UserAccount: DriverHabitInfoUnit:updateCurrentHabitInfo
08-25 12:55:23.582  5428  5428 I com.patac.hmi.user-UserAccount: UserFeatureManager:isMcuEnableDriverHabit mIsMcuEnableDriverHabit = true
08-25 12:55:23.582  5428  5428 I com.patac.hmi.user-UserAccount: CleaNewDriverHabitManager:dealDriverHabitDataEvent mHabitRestoreResult is null
08-25 12:55:23.637  5428  5449 D [ClsLinkSDK-v0.0.27] ClsLink: dispatchCloudEvent {id='1f1a0412-e5cd-6f57-8f77-f3ea29b5da50'}; type=pub.v1
08-25 12:55:23.638  5428  5743 I com.patac.hmi.user-UserAccount: LeftMirrorFeatureHandle:result is not null
08-25 12:55:23.638  5428  5743 I com.patac.hmi.user-UserAccount: LeftMirrorFeatureHandle:dealDataChange data feature is 0
08-25 12:55:23.638  5428  5743 I com.patac.hmi.user-UserAccount: SomeIpModule:dealLeftMirrorFeatureChange 左后视镜反馈值 = 0
08-25 12:55:23.638  5428  5743 I com.patac.hmi.user-UserAccount: DriverHabitMessageHandle:dealDriverMirrorFeedbackEvent 主驾后视镜反馈 is 0
08-25 12:55:23.638  5428  5743 I com.patac.hmi.user-UserAccount: SystemInfoRepository:sendSystemEvent type is 4 id is  4202
08-25 12:55:23.638  5428  5428 I com.patac.hmi.user-UserAccount: UserApplicationManager:get system event 4202
08-25 12:55:23.638  5428  5428 I com.patac.hmi.user-UserAccount: CleaNewDriverHabitManager:dealCustomEvent CLEA2_DRIVER_HABIT_RESULT_EVENT
08-25 12:55:23.638  5428  5428 I com.patac.hmi.user-UserAccount: UserFeatureManager:isMcuEnableDriverHabit mIsMcuEnableDriverHabit = true
08-25 12:55:23.638  5428  5428 I com.patac.hmi.user-UserAccount: CalibrationDataSource:Calibration:MODEL=84
08-25 12:55:23.638  5428  5428 I com.patac.hmi.user-UserAccount: UserFeatureManager:isModelTypeE22 isE22 = false
08-25 12:55:23.639  5428  5428 I com.patac.hmi.user-UserAccount: CleaNewDriverHabitManager:dealDriverHabitResultEvent: seatResult is 0 leftMirrorResult is 0 rightMirrorResult is 0 mDriverMirrorFeedback 0 mPassengerMirrorFeedback 0
08-25 12:55:23.639  5428  5428 I com.patac.hmi.user-UserAccount: CleaNewDriverHabitManager:dealDriverHabitResultEvent mRestoreDriverHabitFlow is null
08-25 12:55:23.686  5428  5704 I com.patac.hmi.user-UserAccount: CarDataSource:left mirror position:-10.0 -0.2 0.0 
08-25 12:55:23.686  5428  5704 I com.patac.hmi.user-UserAccount: DriverHabitMessageHandle:sendDriverHabitEvent afterCheck
08-25 12:55:23.686  5428  5704 I com.patac.hmi.user-UserAccount: SystemInfoRepository:sendSystemEvent type is 4 id is  4201
08-25 12:55:23.686  5428  5428 I com.patac.hmi.user-UserAccount: UserApplicationManager:get system event 4201
08-25 12:55:23.686  5428  5428 I com.patac.hmi.user-UserAccount: CleaNewDriverHabitManager:dealCustomEvent CLEA_DRIVER_HABIT_DATA_EVENT
08-25 12:55:23.686  5428  5428 I com.patac.hmi.user-UserAccount: DriverHabitInfoUnit:updateCurrentHabitInfo
08-25 12:55:23.686  5428  5428 I com.patac.hmi.user-UserAccount: UserFeatureManager:isMcuEnableDriverHabit mIsMcuEnableDriverHabit = true
08-25 12:55:23.686  5428  5428 I com.patac.hmi.user-UserAccount: CleaNewDriverHabitManager:dealDriverHabitDataEvent mHabitRestoreResult is null
08-25 12:55:23.805  5428  5704 I com.patac.hmi.user-UserAccount: CarDataSource:left mirror position:-10.3 -0.2 0.0 
08-25 12:55:23.805  5428  5704 I com.patac.hmi.user-UserAccount: DriverHabitMessageHandle:sendDriverHabitEvent afterCheck
08-25 12:55:23.805  5428  5704 I com.patac.hmi.user-UserAccount: SystemInfoRepository:sendSystemEvent type is 4 id is  4201
08-25 12:55:23.806  5428  5428 I com.patac.hmi.user-UserAccount: UserApplicationManager:get system event 4201
08-25 12:55:23.806  5428  5428 I com.patac.hmi.user-UserAccount: CleaNewDriverHabitManager:dealCustomEvent CLEA_DRIVER_HABIT_DATA_EVENT
08-25 12:55:23.806  5428  5428 I com.patac.hmi.user-UserAccount: DriverHabitInfoUnit:updateCurrentHabitInfo
08-25 12:55:23.806  5428  5428 I com.patac.hmi.user-UserAccount: UserFeatureManager:isMcuEnableDriverHabit mIsMcuEnableDriverHabit = true
08-25 12:55:23.806  5428  5428 I com.patac.hmi.user-UserAccount: CleaNewDriverHabitManager:dealDriverHabitDataEvent mHabitRestoreResult is null
08-25 12:55:23.930  5428  5704 I com.patac.hmi.user-UserAccount: CarDataSource:left mirror position:-10.6 -0.2 0.0 
08-25 12:55:23.930  5428  5704 I com.patac.hmi.user-UserAccount: DriverHabitMessageHandle:sendDriverHabitEvent afterCheck
08-25 12:55:23.930  5428  5704 I com.patac.hmi.user-UserAccount: SystemInfoRepository:sendSystemEvent type is 4 id is  4201
08-25 12:55:23.930  5428  5428 I com.patac.hmi.user-UserAccount: UserApplicationManager:get system event 4201
08-25 12:55:23.930  5428  5428 I com.patac.hmi.user-UserAccount: CleaNewDriverHabitManager:dealCustomEvent CLEA_DRIVER_HABIT_DATA_EVENT
08-25 12:55:23.930  5428  5428 I com.patac.hmi.user-UserAccount: DriverHabitInfoUnit:updateCurrentHabitInfo
08-25 12:55:23.930  5428  5428 I com.patac.hmi.user-UserAccount: UserFeatureManager:isMcuEnableDriverHabit mIsMcuEnableDriverHabit = true
08-25 12:55:23.930  5428  5428 I com.patac.hmi.user-UserAccount: CleaNewDriverHabitManager:dealDriverHabitDataEvent mHabitRestoreResult is null
08-25 12:55:23.941  5428  5449 D [ClsLinkSDK-v0.0.27] ClsLink: dispatchCloudEvent {id='1f1a0412-e8b1-6b48-8f77-f3ea29b5da50'}; type=pub.v1
08-25 12:55:23.941  5428  5743 I com.patac.hmi.user-UserAccount: LeftMirrorFeatureHandle:result is not null
08-25 12:55:23.941  5428  5743 I com.patac.hmi.user-UserAccount: LeftMirrorFeatureHandle:dealDataChange data feature is 0
08-25 12:55:23.941  5428  5743 I com.patac.hmi.user-UserAccount: SomeIpModule:dealLeftMirrorFeatureChange 左后视镜反馈值 = 0
08-25 12:55:23.941  5428  5743 I com.patac.hmi.user-UserAccount: DriverHabitMessageHandle:dealDriverMirrorFeedbackEvent 主驾后视镜反馈 is 0
08-25 12:55:23.941  5428  5743 I com.patac.hmi.user-UserAccount: SystemInfoRepository:sendSystemEvent type is 4 id is  4202
08-25 12:55:23.942  5428  5428 I com.patac.hmi.user-UserAccount: UserApplicationManager:get system event 4202
08-25 12:55:23.943  5428  5428 I com.patac.hmi.user-UserAccount: CleaNewDriverHabitManager:dealCustomEvent CLEA2_DRIVER_HABIT_RESULT_EVENT
08-25 12:55:23.943  5428  5428 I com.patac.hmi.user-UserAccount: UserFeatureManager:isMcuEnableDriverHabit mIsMcuEnableDriverHabit = true
08-25 12:55:23.943  5428  5428 I com.patac.hmi.user-UserAccount: CalibrationDataSource:Calibration:MODEL=84
08-25 12:55:23.943  5428  5428 I com.patac.hmi.user-UserAccount: UserFeatureManager:isModelTypeE22 isE22 = false
08-25 12:55:23.943  5428  5428 I com.patac.hmi.user-UserAccount: CleaNewDriverHabitManager:dealDriverHabitResultEvent: seatResult is 0 leftMirrorResult is 0 rightMirrorResult is 0 mDriverMirrorFeedback 0 mPassengerMirrorFeedback 0
08-25 12:55:23.943  5428  5428 I com.patac.hmi.user-UserAccount: CleaNewDriverHabitManager:dealDriverHabitResultEvent mRestoreDriverHabitFlow is null

---

## 第 14 轮 — LLM 响应



---

## 第 14 轮 — 工具执行结果

[结果 1] 时间范围 [12:55:22.400 ~ 12:55:23.000] (PID=5428): 共 140 行
涉及的 PID: 5428
涉及的 TAG: [ClsLinkSDK-v0.0.27] ClsLink, com.patac.hmi.user-UserAccount

08-25 12:55:23.030  5428  5704 I com.patac.hmi.user-UserAccount: CarDataSource:left mirror position:-7.8 -0.2 0.0 
08-25 12:55:23.030  5428  5704 I com.patac.hmi.user-UserAccount: DriverHabitMessageHandle:sendDriverHabitEvent afterCheck
08-25 12:55:23.030  5428  5704 I com.patac.hmi.user-UserAccount: SystemInfoRepository:sendSystemEvent type is 4 id is  4201
08-25 12:55:23.030  5428  5428 I com.patac.hmi.user-UserAccount: UserApplicationManager:get system event 4201
08-25 12:55:23.030  5428  5428 I com.patac.hmi.user-UserAccount: CleaNewDriverHabitManager:dealCustomEvent CLEA_DRIVER_HABIT_DATA_EVENT
08-25 12:55:23.030  5428  5428 I com.patac.hmi.user-UserAccount: DriverHabitInfoUnit:updateCurrentHabitInfo
08-25 12:55:23.030  5428  5428 I com.patac.hmi.user-UserAccount: UserFeatureManager:isMcuEnableDriverHabit mIsMcuEnableDriverHabit = true
08-25 12:55:23.030  5428  5428 I com.patac.hmi.user-UserAccount: CleaNewDriverHabitManager:dealDriverHabitDataEvent mHabitRestoreResult is null
08-25 12:55:23.035  5428  6558 D [ClsLinkSDK-v0.0.27] ClsLink: dispatchCloudEvent {id='1f1a0412-e00d-6ca3-8f77-f3ea29b5da50'}; type=pub.v1
08-25 12:55:23.035  5428  5743 I com.patac.hmi.user-UserAccount: LeftMirrorFeatureHandle:result is not null
08-25 12:55:23.035  5428  5743 I com.patac.hmi.user-UserAccount: LeftMirrorFeatureHandle:dealDataChange data feature is 0
08-25 12:55:23.035  5428  5743 I com.patac.hmi.user-UserAccount: SomeIpModule:dealLeftMirrorFeatureChange 左后视镜反馈值 = 0
08-25 12:55:23.035  5428  5743 I com.patac.hmi.user-UserAccount: DriverHabitMessageHandle:dealDriverMirrorFeedbackEvent 主驾后视镜反馈 is 0
08-25 12:55:23.035  5428  5743 I com.patac.hmi.user-UserAccount: SystemInfoRepository:sendSystemEvent type is 4 id is  4202
08-25 12:55:23.035  5428  5428 I com.patac.hmi.user-UserAccount: UserApplicationManager:get system event 4202
08-25 12:55:23.035  5428  5428 I com.patac.hmi.user-UserAccount: CleaNewDriverHabitManager:dealCustomEvent CLEA2_DRIVER_HABIT_RESULT_EVENT
08-25 12:55:23.035  5428  5428 I com.patac.hmi.user-UserAccount: UserFeatureManager:isMcuEnableDriverHabit mIsMcuEnableDriverHabit = true
08-25 12:55:23.036  5428  5428 I com.patac.hmi.user-UserAccount: CalibrationDataSource:Calibration:MODEL=84
08-25 12:55:23.036  5428  5428 I com.patac.hmi.user-UserAccount: UserFeatureManager:isModelTypeE22 isE22 = false
08-25 12:55:23.036  5428  5428 I com.patac.hmi.user-UserAccount: CleaNewDriverHabitManager:dealDriverHabitResultEvent: seatResult is 0 leftMirrorResult is 0 rightMirrorResult is 0 mDriverMirrorFeedback 0 mPassengerMirrorFeedback 0
08-25 12:55:23.036  5428  5428 I com.patac.hmi.user-UserAccount: CleaNewDriverHabitManager:dealDriverHabitResultEvent mRestoreDriverHabitFlow is null
08-25 12:55:23.137  5428  5704 I com.patac.hmi.user-UserAccount: CarDataSource:left mirror position:-8.1 -0.2 0.0 
08-25 12:55:23.137  5428  5704 I com.patac.hmi.user-UserAccount: DriverHabitMessageHandle:sendDriverHabitEvent afterCheck
08-25 12:55:23.137  5428  5704 I com.patac.hmi.user-UserAccount: SystemInfoRepository:sendSystemEvent type is 4 id is  4201
08-25 12:55:23.137  5428  5428 I com.patac.hmi.user-UserAccount: UserApplicationManager:get system event 4201
08-25 12:55:23.137  5428  5428 I com.patac.hmi.user-UserAccount: CleaNewDriverHabitManager:dealCustomEvent CLEA_DRIVER_HABIT_DATA_EVENT
08-25 12:55:23.137  5428  5428 I com.patac.hmi.user-UserAccount: DriverHabitInfoUnit:updateCurrentHabitInfo
08-25 12:55:23.137  5428  5428 I com.patac.hmi.user-UserAccount: UserFeatureManager:isMcuEnableDriverHabit mIsMcuEnableDriverHabit = true
08-25 12:55:23.137  5428  5428 I com.patac.hmi.user-UserAccount: CleaNewDriverHabitManager:dealDriverHabitDataEvent mHabitRestoreResult is null
08-25 12:55:23.245  5428  5704 I com.patac.hmi.user-UserAccount: CarDataSource:left mirror position:-8.5 -0.2 0.0 
08-25 12:55:23.245  5428  5704 I com.patac.hmi.user-UserAccount: DriverHabitMessageHandle:sendDriverHabitEvent afterCheck
08-25 12:55:23.245  5428  5704 I com.patac.hmi.user-UserAccount: SystemInfoRepository:sendSystemEvent type is 4 id is  4201
08-25 12:55:23.245  5428  5428 I com.patac.hmi.user-UserAccount: UserApplicationManager:get system event 4201
08-25 12:55:23.245  5428  5428 I com.patac.hmi.user-UserAccount: CleaNewDriverHabitManager:dealCustomEvent CLEA_DRIVER_HABIT_DATA_EVENT
08-25 12:55:23.245  5428  5428 I com.patac.hmi.user-UserAccount: DriverHabitInfoUnit:updateCurrentHabitInfo
08-25 12:55:23.245  5428  5428 I com.patac.hmi.user-UserAccount: UserFeatureManager:isMcuEnableDriverHabit mIsMcuEnableDriverHabit = true
08-25 12:55:23.245  5428  5428 I com.patac.hmi.user-UserAccount: CleaNewDriverHabitManager:dealDriverHabitDataEvent mHabitRestoreResult is null
08-25 12:55:23.338  5428  6558 D [ClsLinkSDK-v0.0.27] ClsLink: dispatchCloudEvent {id='1f1a0412-e2ea-6364-8f77-f3ea29b5da50'}; type=pub.v1
08-25 12:55:23.338  5428  5743 I com.patac.hmi.user-UserAccount: LeftMirrorFeatureHandle:result is not null
08-25 12:55:23.338  5428  5743 I com.patac.hmi.user-UserAccount: LeftMirrorFeatureHandle:dealDataChange data feature is 0
08-25 12:55:23.338  5428  5743 I com.patac.hmi.user-UserAccount: SomeIpModule:dealLeftMirrorFeatureChange 左后视镜反馈值 = 0
08-25 12:55:23.338  5428  5743 I com.patac.hmi.user-UserAccount: DriverHabitMessageHandle:dealDriverMirrorFeedbackEvent 主驾后视镜反馈 is 0
08-25 12:55:23.338  5428  5743 I com.patac.hmi.user-UserAccount: SystemInfoRepository:sendSystemEvent type is 4 id is  4202
08-25 12:55:23.338  5428  5428 I com.patac.hmi.user-UserAccount: UserApplicationManager:get system event 4202
08-25 12:55:23.338  5428  5428 I com.patac.hmi.user-UserAccount: CleaNewDriverHabitManager:dealCustomEvent CLEA2_DRIVER_HABIT_RESULT_EVENT
08-25 12:55:23.339  5428  5428 I com.patac.hmi.user-UserAccount: UserFeatureManager:isMcuEnableDriverHabit mIsMcuEnableDriverHabit = true
08-25 12:55:23.339  5428  5428 I com.patac.hmi.user-UserAccount: CalibrationDataSource:Calibration:MODEL=84
08-25 12:55:23.339  5428  5428 I com.patac.hmi.user-UserAccount: UserFeatureManager:isModelTypeE22 isE22 = false
08-25 12:55:23.339  5428  5428 I com.patac.hmi.user-UserAccount: CleaNewDriverHabitManager:dealDriverHabitResultEvent: seatResult is 0 leftMirrorResult is 0 rightMirrorResult is 0 mDriverMirrorFeedback 0 mPassengerMirrorFeedback 0
08-25 12:55:23.339  5428  5428 I com.patac.hmi.user-UserAccount: CleaNewDriverHabitManager:dealDriverHabitResultEvent mRestoreDriverHabitFlow is null
08-25 12:55:23.362  5428  5704 I com.patac.hmi.user-UserAccount: CarDataSource:left mirror position:-8.8 -0.2 0.0 
08-25 12:55:23.363  5428  5704 I com.patac.hmi.user-UserAccount: DriverHabitMessageHandle:sendDriverHabitEvent afterCheck
08-25 12:55:23.363  5428  5704 I com.patac.hmi.user-UserAccount: SystemInfoRepository:sendSystemEvent type is 4 id is  4201
08-25 12:55:23.363  5428  5428 I com.patac.hmi.user-UserAccount: UserApplicationManager:get system event 4201
08-25 12:55:23.363  5428  5704 I com.patac.hmi.user-UserAccount: CarDataSource:right mirror position:-5.2000003 0.1 0.0 
08-25 12:55:23.363  5428  5428 I com.patac.hmi.user-UserAccount: CleaNewDriverHabitManager:dealCustomEvent CLEA_DRIVER_HABIT_DATA_EVENT
08-25 12:55:23.363  5428  5428 I com.patac.hmi.user-UserAccount: DriverHabitInfoUnit:updateCurrentHabitInfo
08-25 12:55:23.363  5428  5704 I com.patac.hmi.user-UserAcco

... [截断: 原始结果 18,060 字符，已截取中间 3,060 字符] ...

rHabitDataEvent mHabitRestoreResult is null
08-25 12:55:23.581  5428  5704 I com.patac.hmi.user-UserAccount: CarDataSource:left mirror position:-9.6 -0.2 0.0 
08-25 12:55:23.581  5428  5704 I com.patac.hmi.user-UserAccount: DriverHabitMessageHandle:sendDriverHabitEvent afterCheck
08-25 12:55:23.581  5428  5704 I com.patac.hmi.user-UserAccount: SystemInfoRepository:sendSystemEvent type is 4 id is  4201
08-25 12:55:23.582  5428  5428 I com.patac.hmi.user-UserAccount: UserApplicationManager:get system event 4201
08-25 12:55:23.582  5428  5428 I com.patac.hmi.user-UserAccount: CleaNewDriverHabitManager:dealCustomEvent CLEA_DRIVER_HABIT_DATA_EVENT
08-25 12:55:23.582  5428  5428 I com.patac.hmi.user-UserAccount: DriverHabitInfoUnit:updateCurrentHabitInfo
08-25 12:55:23.582  5428  5428 I com.patac.hmi.user-UserAccount: UserFeatureManager:isMcuEnableDriverHabit mIsMcuEnableDriverHabit = true
08-25 12:55:23.582  5428  5428 I com.patac.hmi.user-UserAccount: CleaNewDriverHabitManager:dealDriverHabitDataEvent mHabitRestoreResult is null
08-25 12:55:23.637  5428  5449 D [ClsLinkSDK-v0.0.27] ClsLink: dispatchCloudEvent {id='1f1a0412-e5cd-6f57-8f77-f3ea29b5da50'}; type=pub.v1
08-25 12:55:23.638  5428  5743 I com.patac.hmi.user-UserAccount: LeftMirrorFeatureHandle:result is not null
08-25 12:55:23.638  5428  5743 I com.patac.hmi.user-UserAccount: LeftMirrorFeatureHandle:dealDataChange data feature is 0
08-25 12:55:23.638  5428  5743 I com.patac.hmi.user-UserAccount: SomeIpModule:dealLeftMirrorFeatureChange 左后视镜反馈值 = 0
08-25 12:55:23.638  5428  5743 I com.patac.hmi.user-UserAccount: DriverHabitMessageHandle:dealDriverMirrorFeedbackEvent 主驾后视镜反馈 is 0
08-25 12:55:23.638  5428  5743 I com.patac.hmi.user-UserAccount: SystemInfoRepository:sendSystemEvent type is 4 id is  4202
08-25 12:55:23.638  5428  5428 I com.patac.hmi.user-UserAccount: UserApplicationManager:get system event 4202
08-25 12:55:23.638  5428  5428 I com.patac.hmi.user-UserAccount: CleaNewDriverHabitManager:dealCustomEvent CLEA2_DRIVER_HABIT_RESULT_EVENT
08-25 12:55:23.638  5428  5428 I com.patac.hmi.user-UserAccount: UserFeatureManager:isMcuEnableDriverHabit mIsMcuEnableDriverHabit = true
08-25 12:55:23.638  5428  5428 I com.patac.hmi.user-UserAccount: CalibrationDataSource:Calibration:MODEL=84
08-25 12:55:23.638  5428  5428 I com.patac.hmi.user-UserAccount: UserFeatureManager:isModelTypeE22 isE22 = false
08-25 12:55:23.639  5428  5428 I com.patac.hmi.user-UserAccount: CleaNewDriverHabitManager:dealDriverHabitResultEvent: seatResult is 0 leftMirrorResult is 0 rightMirrorResult is 0 mDriverMirrorFeedback 0 mPassengerMirrorFeedback 0
08-25 12:55:23.639  5428  5428 I com.patac.hmi.user-UserAccount: CleaNewDriverHabitManager:dealDriverHabitResultEvent mRestoreDriverHabitFlow is null
08-25 12:55:23.686  5428  5704 I com.patac.hmi.user-UserAccount: CarDataSource:left mirror position:-10.0 -0.2 0.0 
08-25 12:55:23.686  5428  5704 I com.patac.hmi.user-UserAccount: DriverHabitMessageHandle:sendDriverHabitEvent afterCheck
08-25 12:55:23.686  5428  5704 I com.patac.hmi.user-UserAccount: SystemInfoRepository:sendSystemEvent type is 4 id is  4201
08-25 12:55:23.686  5428  5428 I com.patac.hmi.user-UserAccount: UserApplicationManager:get system event 4201
08-25 12:55:23.686  5428  5428 I com.patac.hmi.user-UserAccount: CleaNewDriverHabitManager:dealCustomEvent CLEA_DRIVER_HABIT_DATA_EVENT
08-25 12:55:23.686  5428  5428 I com.patac.hmi.user-UserAccount: DriverHabitInfoUnit:updateCurrentHabitInfo
08-25 12:55:23.686  5428  5428 I com.patac.hmi.user-UserAccount: UserFeatureManager:isMcuEnableDriverHabit mIsMcuEnableDriverHabit = true
08-25 12:55:23.686  5428  5428 I com.patac.hmi.user-UserAccount: CleaNewDriverHabitManager:dealDriverHabitDataEvent mHabitRestoreResult is null
08-25 12:55:23.805  5428  5704 I com.patac.hmi.user-UserAccount: CarDataSource:left mirror position:-10.3 -0.2 0.0 
08-25 12:55:23.805  5428  5704 I com.patac.hmi.user-UserAccount: DriverHabitMessageHandle:sendDriverHabitEvent afterCheck
08-25 12:55:23.805  5428  5704 I com.patac.hmi.user-UserAccount: SystemInfoRepository:sendSystemEvent type is 4 id is  4201
08-25 12:55:23.806  5428  5428 I com.patac.hmi.user-UserAccount: UserApplicationManager:get system event 4201
08-25 12:55:23.806  5428  5428 I com.patac.hmi.user-UserAccount: CleaNewDriverHabitManager:dealCustomEvent CLEA_DRIVER_HABIT_DATA_EVENT
08-25 12:55:23.806  5428  5428 I com.patac.hmi.user-UserAccount: DriverHabitInfoUnit:updateCurrentHabitInfo
08-25 12:55:23.806  5428  5428 I com.patac.hmi.user-UserAccount: UserFeatureManager:isMcuEnableDriverHabit mIsMcuEnableDriverHabit = true
08-25 12:55:23.806  5428  5428 I com.patac.hmi.user-UserAccount: CleaNewDriverHabitManager:dealDriverHabitDataEvent mHabitRestoreResult is null
08-25 12:55:23.930  5428  5704 I com.patac.hmi.user-UserAccount: CarDataSource:left mirror position:-10.6 -0.2 0.0 
08-25 12:55:23.930  5428  5704 I com.patac.hmi.user-UserAccount: DriverHabitMessageHandle:sendDriverHabitEvent afterCheck
08-25 12:55:23.930  5428  5704 I com.patac.hmi.user-UserAccount: SystemInfoRepository:sendSystemEvent type is 4 id is  4201
08-25 12:55:23.930  5428  5428 I com.patac.hmi.user-UserAccount: UserApplicationManager:get system event 4201
08-25 12:55:23.930  5428  5428 I com.patac.hmi.user-UserAccount: CleaNewDriverHabitManager:dealCustomEvent CLEA_DRIVER_HABIT_DATA_EVENT
08-25 12:55:23.930  5428  5428 I com.patac.hmi.user-UserAccount: DriverHabitInfoUnit:updateCurrentHabitInfo
08-25 12:55:23.930  5428  5428 I com.patac.hmi.user-UserAccount: UserFeatureManager:isMcuEnableDriverHabit mIsMcuEnableDriverHabit = true
08-25 12:55:23.930  5428  5428 I com.patac.hmi.user-UserAccount: CleaNewDriverHabitManager:dealDriverHabitDataEvent mHabitRestoreResult is null
08-25 12:55:23.941  5428  5449 D [ClsLinkSDK-v0.0.27] ClsLink: dispatchCloudEvent {id='1f1a0412-e8b1-6b48-8f77-f3ea29b5da50'}; type=pub.v1
08-25 12:55:23.941  5428  5743 I com.patac.hmi.user-UserAccount: LeftMirrorFeatureHandle:result is not null
08-25 12:55:23.941  5428  5743 I com.patac.hmi.user-UserAccount: LeftMirrorFeatureHandle:dealDataChange data feature is 0
08-25 12:55:23.941  5428  5743 I com.patac.hmi.user-UserAccount: SomeIpModule:dealLeftMirrorFeatureChange 左后视镜反馈值 = 0
08-25 12:55:23.941  5428  5743 I com.patac.hmi.user-UserAccount: DriverHabitMessageHandle:dealDriverMirrorFeedbackEvent 主驾后视镜反馈 is 0
08-25 12:55:23.941  5428  5743 I com.patac.hmi.user-UserAccount: SystemInfoRepository:sendSystemEvent type is 4 id is  4202
08-25 12:55:23.942  5428  5428 I com.patac.hmi.user-UserAccount: UserApplicationManager:get system event 4202
08-25 12:55:23.943  5428  5428 I com.patac.hmi.user-UserAccount: CleaNewDriverHabitManager:dealCustomEvent CLEA2_DRIVER_HABIT_RESULT_EVENT
08-25 12:55:23.943  5428  5428 I com.patac.hmi.user-UserAccount: UserFeatureManager:isMcuEnableDriverHabit mIsMcuEnableDriverHabit = true
08-25 12:55:23.943  5428  5428 I com.patac.hmi.user-UserAccount: CalibrationDataSource:Calibration:MODEL=84
08-25 12:55:23.943  5428  5428 I com.patac.hmi.user-UserAccount: UserFeatureManager:isModelTypeE22 isE22 = false
08-25 12:55:23.943  5428  5428 I com.patac.hmi.user-UserAccount: CleaNewDriverHabitManager:dealDriverHabitResultEvent: seatResult is 0 leftMirrorResult is 0 rightMirrorResult is 0 mDriverMirrorFeedback 0 mPassengerMirrorFeedback 0
08-25 12:55:23.943  5428  5428 I com.patac.hmi.user-UserAccount: CleaNewDriverHabitManager:dealDriverHabitResultEvent mRestoreDriverHabitFlow is null

---

## 第 15 轮 — LLM 响应

工具返回的内容似乎被截断了。让我用 search_log 精确搜索关键时间点附近的日志内容。



---

## 第 15 轮 — 工具执行结果

[结果 1] 搜索结果: 共 50 条匹配，显示 15 条

L17072     08-25 12:55:22.433  5428  5743 I com.patac.hmi.user-UserAccount: LeftMirrorFeatureHandle:result is not null
    08-25 12:55:22.433  5428  5743 I com.patac.hmi.user-UserAccount: LeftMirrorFeatureHandle:dealDataChange data feature is 2
    08-25 12:55:22.433  5428  5743 I com.patac.hmi.user-UserAccount: SomeIpModule:dealLeftMirrorFeatureChange 左后视镜反馈值 = 2
>>> 08-25 12:55:22.433  5428  5743 I com.patac.hmi.user-UserAccount: DriverHabitMessageHandle:dealDriverMirrorFeedbackEvent 主驾后视镜反馈 is 2
    08-25 12:55:22.434  5428  5743 I com.patac.hmi.user-UserAccount: SystemInfoRepository:sendSystemEvent type is 4 id is  4202
    08-25 12:55:22.434  5428  5428 I com.patac.hmi.user-UserAccount: UserApplicationManager:get system event 4202
    08-25 12:55:22.434  5428  5428 I com.patac.hmi.user-UserAccount: CleaNewDriverHabitManager:dealCustomEvent CLEA2_DRIVER_HABIT_RESULT_EVENT

L17145     08-25 12:55:22.456  5428  5743 I com.patac.hmi.user-UserAccount: LeftMirrorFeatureHandle:result is not null
    08-25 12:55:22.456  5428  5743 I com.patac.hmi.user-UserAccount: LeftMirrorFeatureHandle:dealDataChange data feature is 0
    08-25 12:55:22.456  5428  5743 I com.patac.hmi.user-UserAccount: SomeIpModule:dealLeftMirrorFeatureChange 左后视镜反馈值 = 0
>>> 08-25 12:55:22.456  5428  5743 I com.patac.hmi.user-UserAccount: DriverHabitMessageHandle:dealDriverMirrorFeedbackEvent 主驾后视镜反馈 is 0
    08-25 12:55:22.456  4515  5201 I com.patac.hmi.settings-BaseTopicHandler: registerEventListener
    08-25 12:55:22.456  5428  5743 I com.patac.hmi.user-UserAccount: SystemInfoRepository:sendSystemEvent type is 4 id is  4202
    08-25 12:55:22.456  5428  5428 I com.patac.hmi.user-UserAccount: UserApplicationManager:get system event 4202

L17170     08-25 12:55:22.475  1371  1443 D GMVHAL  : setPropFromVehicle Property: VehicleProperty::HW_KEY_INPUT AreaID: 16777216 Status: 0 int32Values: 0 25 0 
    08-25 12:55:22.477  2150  2234 D CAR.INPUT: hal event code: 25, action: 0, display: 0, number of indents: 1
    08-25 12:55:22.477  5428  5704 I com.patac.hmi.user-UserAccount: CarDataSource:left mirror position:-5.9 -0.2 0.0 
>>> 08-25 12:55:22.477  5428  5704 I com.patac.hmi.user-UserAccount: DriverHabitMessageHandle:sendDriverHabitEvent afterCheck
    08-25 12:55:22.477  5428  5704 I com.patac.hmi.user-UserAccount: SystemInfoRepository:sendSystemEvent type is 4 id is  4201
    08-25 12:55:22.477  5428  5428 I com.patac.hmi.user-UserAccount: UserApplicationManager:get system event 4201
    08-25 12:55:22.477  5428  5428 I com.patac.hmi.user-UserAccount: CleaNewDriverHabitManager:dealCustomEvent CLEA_DRIVER_HABIT_DATA_EVENT

L17214     08-25 12:55:22.579  4515  4515 D HardKeyInterceptorManager: dispatch keyEventKeyEvent { action=ACTION_DOWN, keyCode=KEYCODE_VOLUME_DOWN, scanCode=0, metaState=0, flags=0x0, repeatCount=8, eventTime=2369895000000, downTime=2369895000000, deviceId=0, source=0x101, displayId=0 } on callback com.patac.h
    08-25 12:55:22.579  4515  4515 D com.patac.hmi.settings-SteeringWheelHardKeyUtil: processSWCOperation keyEvent = KeyEvent { action=ACTION_DOWN, keyCode=KEYCODE_VOLUME_DOWN, scanCode=0, metaState=0, flags=0x0, repeatCount=8, eventTime=2369895000000, downTime=2369895000000, deviceId=0, source=0x101, d
    08-25 12:55:22.580  5428  5704 I com.patac.hmi.user-UserAccount: CarDataSource:left mirror position:-6.3 -0.2 0.0 
>>> 08-25 12:55:22.580  5428  5704 I com.patac.hmi.user-UserAccount: DriverHabitMessageHandle:sendDriverHabitEvent afterCheck
    08-25 12:55:22.580  5428  5704 I com.patac.hmi.user-UserAccount: SystemInfoRepository:sendSystemEvent type is 4 id is  4201
    08-25 12:55:22.581  5428  5704 I com.patac.hmi.user-UserAccount: CarDataSource:right mirror position:-5.2000003 0.0 0.0 
    08-25 12:55:22.581  5428  5428 I com.patac.hmi.user-UserAccount: UserApplicationManager:get system event 4201

L17284     08-25 12:55:22.685  5951  6023 D CPECallbackController: Dropping carPropertyEvent - propId: 291504647 areaId: 16777216  because getTimestamp(): 3603239639816 < nextUpdateTimeNanos: 3603339639816
    08-25 12:55:22.687  1371  1476 D GMVHAL  : setPropFromVehicle Property: PatacProperty::MIRROR_POSITION_STATUS AreaID: 1 Status: 0 floatValues: -6.7 -0.2 0 
    08-25 12:55:22.688  5428  5704 I com.patac.hmi.user-UserAccount: CarDataSource:left mirror position:-6.7000003 -0.2 0.0 
>>> 08-25 12:55:22.688  5428  5704 I com.patac.hmi.user-UserAccount: DriverHabitMessageHandle:sendDriverHabitEvent afterCheck
    08-25 12:55:22.688  5428  5704 I com.patac.hmi.user-UserAccount: SystemInfoRepository:sendSystemEvent type is 4 id is  4201
    08-25 12:55:22.688  5428  5428 I com.patac.hmi.user-UserAccount: UserApplicationManager:get system event 4201
    08-25 12:55:22.688  5428  5428 I com.patac.hmi.user-UserAccount: CleaNewDriverHabitManager:dealCustomEvent CLEA_DRIVER_HABIT_DATA_EVENT

L17366     08-25 12:55:22.730  5428  5743 I com.patac.hmi.user-UserAccount: LeftMirrorFeatureHandle:dealDataChange data feature is 0
    08-25 12:55:22.730  4515  4515 I com.patac.hmi.settings-SettingItemValueSdvManager: 66<--someipHmi--disable-result---->Result{mBoolValue=true, mIntValue=0, mFloatValue=0.0, mState=0, mObject=null, mAvailable=1}
    08-25 12:55:22.730  5428  5743 I com.patac.hmi.user-UserAccount: SomeIpModule:dealLeftMirrorFeatureChange 左后视镜反馈值 = 0
>>> 08-25 12:55:22.730  5428  5743 I com.patac.hmi.user-UserAccount: DriverHabitMessageHandle:dealDriverMirrorFeedbackEvent 主驾后视镜反馈 is 0
    08-25 12:55:22.730  4515  4515 D com.patac.hmi.settings-DriveMirrorDialogManager: requestDisableValueFromSdvSomeIp Value-onNext: 66, disable = false, type = 19
    08-25 12:55:22.730  5428  5743 I com.patac.hmi.user-UserAccount: SystemInfoRepository:sendSystemEvent type is 4 id is  4202
    08-25 12:55:22.730  5428  5428 I com.patac.hmi.user-UserAccount: UserApplicationManager:get system event 4202

L17397     08-25 12:55:22.735  5428  5743 I com.patac.hmi.user-UserAccount: RightMirrorFeatureHandle:dealDataChange data feature is 0
    08-25 12:55:22.735  4515  4515 D com.patac.hmi.settings-DriveMirrorDialogManager: requestDisableValueFromSdvSomeIp Value-onNext: 67, disable = false, type = 19
    08-25 12:55:22.735  5428  5743 I com.patac.hmi.user-UserAccount: SomeIpModule:dealRightMirrorFeatureChange 右后视镜反馈值 = 0
>>> 08-25 12:55:22.735  5428  5743 I com.patac.hmi.user-UserAccount: DriverHabitMessageHandle:dealPassengerMirrorFeedbackEvent 副驾后视镜反馈 is 0
    08-25 12:55:22.735  5428  5743 I com.patac.hmi.user-UserAccount: SystemInfoRepository:sendSystemEvent type is 4 id is  4202
    08-25 12:55:22.735  5428  5428 I com.patac.hmi.user-UserAccount: UserApplicationManager:get system event 4202
    08-25 12:55:22.735  5428  5428 I com.patac.hmi.user-UserAccount: CleaNewDriverHabitManager:dealCustomEvent CLEA2_DRIVER_HABIT_RESULT_EVENT

L17430     08-25 12:55:22.804  1371  1476 D GMVHAL  : setPropFromVehicle Property: PatacProperty::MIRROR_POSITION_STATUS AreaID: 1 Status: 0 floatValues: -7.1 -0.2 0 
    08-25 12:55:22.804  1371  1476 D GMVHAL  : setPropFromVehicle Property: PatacProperty::FORWARD_LOOKING_LIGHT_LEVEL_EXTENDED AreaID: 16777216 Status: 0 int32Values: 36260 
    08-25 12:55:22.804  5428  5704 I com.patac.hmi.user-UserAccount: CarDataSource:left mirror position:-7.1 -0.2 0.0 
>>> 08-25 12:55:22.805  5428  5704 I com.patac.hmi.user-UserAccount: DriverHabitMessageHandle:sendDriverHabitEvent afterCheck
    08-25 12:55:22.805  5428  5704 I com.patac.hmi.user-UserAccount: SystemInfoRepository:sendSystemEvent type is 4 id is  4201
    08-25 12:55:22.805  5428  5428 I com.patac.hmi.user-UserAccount: UserApplicationManager:get system event 4201
    08-25 12:55:22.805  5428  5428 I com.patac.hmi.user-UserAccount: CleaNewDriverHabitManager:dealCustomEvent CLEA_DRIVER_HABIT_DATA_EVENT

L17472     08-25 12:55:22.911  1371  1476 D GMVHAL  : setPropFromVehicle Property: VehicleProperty::PERF_STEERING_ANGLE AreaID: 16777216 Status: 0 floatValues: 7.75 
    08-25 12:55:22.912  1371  1476 D GMVHAL  : setPropFromVehicle Property: PatacProperty::MIRROR_POSITION_STATUS AreaID: 1 Status: 0 floatValues: -7.4 -0.2 0 
    08-25 12:55:22.913  5428  5704 I com.patac.hmi.user-UserAccount: CarDataSource:left mirror position:-7.4 -0.2 0.0 
>>> 08-25 12:55:22.913  5428  5704 I com.patac.hmi.user-UserAccount: DriverHabitMessageHandle:sendDriverHabitEvent afterCheck
    08-25 12:55:22.914  5428  5704 I com.patac.hmi.user-UserAccount: SystemInfoRepository:sendSystemEvent type is 4 id is  4201
    08-25 12:55:22.914  5428  5428 I com.patac.hmi.user-UserAccount: UserApplicationManager:get system event 4201
    08-25 12:55:22.914  5428  5428 I com.patac.hmi.user-UserAccount: CleaNewDriverHabitManager:dealCustomEvent CLEA_DRIVER_HABIT_DATA_EVENT

L17523     08-25 12:55:23.029  1368  3139 I         : VSIP: cei::rcb (Success): 00 01 81 a3 00 00 00 53 00 00 51 2b 01 01 02 00 01 01 00 01 00 00 00 01 00 01 01 00 00 00 00 01 00 01 01 01 01 01 01 01 00 00 00 00 00 00 00 00 ff b2 ff fe ff cc 00 00 00 00 00 00 00 00 01 01 01 01 01 01 01 01 01 02 00 00 00 00 00 
    08-25 12:55:23.030  1368  3140 D someip::vendor.ts.someip@1.0-service: reportSomeIpMessage enter: topic: { topic = 2533279085461923, .m = 33187, .i = 1, .s = 1, .t = 9}
    08-25 12:55:23.030  5428  5704 I com.patac.hmi.user-UserAccount: CarDataSource:left mirror position:-7.8 -0.2 0.0 
>>> 08-25 12:55:23.030  5428  5704 I com.patac.hmi.user-UserAccount: DriverHabitMessageHandle:sendDriverHabitEvent afterCheck
    08-25 12:55:23.030  5428  5704 I com.patac.hmi.user-UserAccount: SystemInfoRepository:sendSystemEvent type is 4 id is  4201
    08-25 12:55:23.030  4112  5150 D SDV_CoreService: [SomeIpTopicReceiverManager]topic 2533279085461923
    08-25 12:55:23.030  5428  5428 I com.patac.hmi.user-UserAccount: UserApplicationManager:get system event 4201

L17577     08-25 12:55:23.035  5428  5743 I com.patac.hmi.user-UserAccount: LeftMirrorFeatureHandle:result is not null
    08-25 12:55:23.035  5428  5743 I com.patac.hmi.user-UserAccount: LeftMirrorFeatureHandle:dealDataChange data feature is 0
    08-25 12:55:23.035  5428  5743 I com.patac.hmi.user-UserAccount: SomeIpModule:dealLeftMirrorFeatureChange 左后视镜反馈值 = 0
>>> 08-25 12:55:23.035  5428  5743 I com.patac.hmi.user-UserAccount: DriverHabitMessageHandle:dealDriverMirrorFeedbackEvent 主驾后视镜反馈 is 0
    08-25 12:55:23.035  5428  5743 I com.patac.hmi.user-UserAccount: SystemInfoRepository:sendSystemEvent type is 4 id is  4202
    08-25 12:55:23.035  5428  5428 I com.patac.hmi.user-UserAccount: UserApplicationManager:get system event 4202
    08-25 12:55:23.035  5428  5428 I com.patac.hmi.user-UserAccount: CleaNewDriverHabitManager:dealCustomEvent CLEA2_DRIVER_HABIT_RESULT_EVENT

L17633     08-25 12:55:23.128  1089  7406 I Bosch_NavSensors: GyrUn:[-0.000000, -0.001864, 0.001465, 0.000000, 0.000000, 0.000000, 1714607]
    08-25 12:55:23.136  1371  1476 D GMVHAL  : setPropFromVehicle Property: PatacProperty::MIRROR_POSITION_STATUS AreaID: 1 Status: 0 floatValues: -8.1 -0.2 0 
    08-25 12:55:23.137  5428  5704 I com.patac.hmi.user-UserAccount: CarDataSource:left mirror position:-8.1 -0.2 0.0 
>>> 08-25 12:55:23.137  5428  5704 I com.patac.hmi.user-UserAccount: DriverHabitMessageHandle:sendDriverHabitEvent afterCheck
    08-25 12:55:23.137  5428  5704 I com.patac.hmi.user-UserAccount: SystemInfoRepository:sendSystemEvent type is 4 id is  4201
    08-25 12:55:23.137  5428  5428 I com.patac.hmi.user-UserAccount: UserApplicationManager:get system event 4201
    08-25 12:55:23.137  5428  5428 I com.patac.hmi.user-UserAccount: CleaNewDriverHabitManager:dealCustomEvent CLEA_DRIVER_HABIT_DATA_EVENT

L17669     08-25 12:55:23.228  4515  4515 D com.patac.hmi.settings-SteeringWheelHardKeyUtil: processSWCOperation keyEvent = KeyEvent { action=ACTION_DOWN, keyCode=KEYCODE_VOLUME_DOWN, scanCode=0, metaState=0, flags=0x0, repeatCount=21, eventTime=2370543000000, downTime=2370543000000, deviceId=0, source=0x101, 
    08-25 12:55:23.244  1371  1476 D GMVHAL  : setPropFromVehicle Property: PatacProperty::MIRROR_POSITION_STATUS AreaID: 1 Status: 0 floatValues: -8.5 -0.2 0 
    08-25 12:55:23.245  5428  5704 I com.patac.hmi.user-UserAccount: CarDataSource:left mirror position:-8.5 -0.2 0.0 
>>> 08-25 12:55:23.245  5428  5704 I com.patac.hmi.user-UserAccount: DriverHabitMessageHandle:sendDriverHabitEvent afterCheck
    08-25 12:55:23.245  5428  5704 I com.patac.hmi.user-UserAccount: SystemInfoRepository:sendSystemEvent type is 4 id is  4201
    08-25 12:55:23.245  5428  5428 I com.patac.hmi.user-UserAccount: UserApplicationManager:get system event 4201
    08-25 12:55:23.245  5428  5428 I com.patac.hmi.user-UserAccount: CleaNewDriverHabitManager:dealCustomEvent CLEA_DRIVER_HABIT_DATA_EVENT

L17766     08-25 12:55:23.338  5428  5743 I com.patac.hmi.user-UserAccount: LeftMirrorFeatureHandle:result is not null
    08-25 12:55:23.338  5428  5743 I com.patac.hmi.user-UserAccount: LeftMirrorFeatureHandle:dealDataChange data feature is 0
    08-25 12:55:23.338  5428  5743 I com.patac.hmi.user-UserAccount: SomeIpModule:dealLeftMirrorFeatureChange 左后视镜反馈值 = 0
>>> 08-25 12:55:23.338  5428  5743 I com.patac.hmi.user-UserAccount: DriverHabitMessageHandle:dealDriverMirrorFeedbackEvent 主驾后视镜反馈 is 0
    08-25 12:55:23.338  5428  5743 I com.patac.hmi.user-UserAccount: SystemInfoRepository:sendSystemEvent type is 4 id is  4202
    08-25 12:55:23.338  5428  5428 I com.patac.hmi.user-UserAccount: UserApplicationManager:get system event 4202
    08-25 12:55:23.338  5428  5428 I com.patac.hmi.user-UserAccount: CleaNewDriverHabitManager:dealCustomEvent CLEA2_DRIVER_HABIT_RESULT_EVENT

L17779     08-25 12:55:23.361  1371  1476 D GMVHAL  : setPropFromVehicle Property: PatacProperty::MIRROR_POSITION_STATUS AreaID: 1 Status: 0 floatValues: -8.8 -0.2 0 
    08-25 12:55:23.361  1371  1476 D GMVHAL  : setPropFromVehicle Property: PatacProperty::MIRROR_POSITION_STATUS AreaID: 2 Status: 0 floatValues: -5.2 0.1 0 
    08-25 12:55:23.362  5428  5704 I com.patac.hmi.user-UserAccount: CarDataSource:left mirror position:-8.8 -0.2 0.0 
>>> 08-25 12:55:23.363  5428  5704 I com.patac.hmi.user-UserAccount: DriverHabitMessageHandle:sendDriverHabitEvent afterCheck
    08-25 12:55:23.363  5428  5704 I com.patac.hmi.user-UserAccount: SystemInfoRepository:sendSystemEvent type is 4 id is  4201
    08-25 12:55:23.363  5428  5428 I com.patac.hmi.user-UserAccount: UserApplicationManager:get system event 4201
    08-25 12:55:23.363  5428  5704 I com.patac.hmi.user-UserAccount: CarDataSource:right mirror position:-5.2000003 0.1 0.0 

⚠️ 搜索结果高度重复: 共 50 条匹配中，有 30 条内容相同 ('')。以上仅展示 15 条代表性结果。

---

## 第 16 轮 — LLM 响应



---

## 第 16 轮 — 工具执行结果

[结果 1] 未找到匹配 pattern='mRestoreDriverHabitFlow\s*=' 的日志行（共扫描 404301 行）

---

[结果 2] 未找到匹配 pattern='mHabitRestoreResult\s*=' 的日志行（共扫描 404301 行）

---

[结果 3] 日志搜索调用数已达上限 25，search_log 未执行

---

## 第 17 轮 — LLM 响应

搜索调用已达上限。让我用 read_time_range 读取关键时间段的原始日志，理解记忆恢复流程的完整上下文。



---

## 第 17 轮 — 工具执行结果

[结果 1] 时间范围 [12:55:22.400 ~ 12:55:23.000] (PID=无): 共 744 行
涉及的 PID: 1080, 1089, 1129, 1368, 1371
涉及的 TAG: , ACCGYROCALIBRATION, AHAL, ActivityManager, Bosch_NavSensors, CAR.INPUT, CPECallbackController, Calibrationd, CarLinkManager, CarPropertyManager

08-25 12:55:23.025  2150  2234 D CAR.INPUT: hal event code: 25, action: 0, display: 0, number of indents: 1
08-25 12:55:23.035   732   732 I Calibrationd: [532501538040]CalibrationUsageLog.cpp::logUsage(34): Calibration Requested: com.patac.hmi.user: GMModel: ENUMERATION: [Module]GMModel: ENUMERATION: 84
08-25 12:55:23.075  2150  2234 D CAR.INPUT: hal event code: 25, action: 0, display: 0, number of indents: 1
08-25 12:55:23.125  2150  2234 D CAR.INPUT: hal event code: 25, action: 0, display: 0, number of indents: 1
08-25 12:55:23.175  2150  2234 D CAR.INPUT: hal event code: 25, action: 0, display: 0, number of indents: 1
08-25 12:55:23.225  2150  2234 D CAR.INPUT: hal event code: 25, action: 0, display: 0, number of indents: 1
08-25 12:55:23.275  2150  2234 D CAR.INPUT: hal event code: 25, action: 0, display: 0, number of indents: 1
08-25 12:55:23.326  2150  2234 D CAR.INPUT: hal event code: 25, action: 0, display: 0, number of indents: 1
08-25 12:55:23.339   732   732 I Calibrationd: [532501538040]CalibrationUsageLog.cpp::logUsage(34): Calibration Requested: com.patac.hmi.user: GMModel: ENUMERATION: [Module]GMModel: ENUMERATION: 84
08-25 12:55:23.376  2150  2234 D CAR.INPUT: hal event code: 25, action: 0, display: 0, number of indents: 1
08-25 12:55:23.426  2150  2234 D CAR.INPUT: hal event code: 25, action: 0, display: 0, number of indents: 1
08-25 12:55:23.475  2150  2234 D CAR.INPUT: hal event code: 25, action: 0, display: 0, number of indents: 1
08-25 12:55:23.525  2150  2234 D CAR.INPUT: hal event code: 25, action: 0, display: 0, number of indents: 1
08-25 12:55:23.535  1683  2115 W ActivityManager: Unable to start service Intent { cmp=com.sgm.navi.hmi/com.sgm.navi.exportservice.MapService (has extras) } U=10: not found
08-25 12:55:23.578  2150  2234 D CAR.INPUT: hal event code: 25, action: 0, display: 0, number of indents: 1
08-25 12:55:23.581  1683  2115 D NetworkPolicy: Blocked state of 10019: {blocked=NONE,allowed=FOREGROUND|TOP|METERED_FOREGROUND,effective=NONE}
08-25 12:55:23.604   737   829 I PLSS_PMSvc: onSystemState: RUN(5)
08-25 12:55:23.615  1683  2115 W ActivityManager: Unable to start service Intent { act=com.sgm.scene.service.SceneService cmp=com.sgm.scene.app/com.sgm.scene.service.SceneService } U=10: not found
08-25 12:55:23.626  2150  2234 D CAR.INPUT: hal event code: 25, action: 0, display: 0, number of indents: 1
08-25 12:55:23.638   732   732 I Calibrationd: [532501538040]CalibrationUsageLog.cpp::logUsage(34): Calibration Requested: com.patac.hmi.user: GMModel: ENUMERATION: [Module]GMModel: ENUMERATION: 84
08-25 12:55:23.677  2150  2234 D CAR.INPUT: hal event code: 25, action: 0, display: 0, number of indents: 1
08-25 12:55:23.727  2150  2234 D CAR.INPUT: hal event code: 25, action: 0, display: 0, number of indents: 1
08-25 12:55:23.776  2150  2234 D CAR.INPUT: hal event code: 25, action: 0, display: 0, number of indents: 1
08-25 12:55:23.826  2150  2234 D CAR.INPUT: hal event code: 25, action: 0, display: 0, number of indents: 1
08-25 12:55:23.875  2150  2234 D CAR.INPUT: hal event code: 25, action: 0, display: 0, number of indents: 1
08-25 12:55:23.905  1683  2115 W ActivityManager: Unable to start service Intent { act=com.patac.carlink.SDK pkg=com.patac.carlink } U=10: not found
08-25 12:55:23.927  2150  2234 D CAR.INPUT: hal event code: 25, action: 0, display: 0, number of indents: 1
08-25 12:55:23.943   732   732 I Calibrationd: [532501538040]CalibrationUsageLog.cpp::logUsage(34): Calibration Requested: com.patac.hmi.user: GMModel: ENUMERATION: [Module]GMModel: ENUMERATION: 84
08-25 12:55:23.975  2150  2234 D CAR.INPUT: hal event code: 25, action: 0, display: 0, number of indents: 1
08-25 12:55:23.011  1371  1476 D GMVHAL  : setPropFromVehicle Property: VendorProperty::POSITION_OFFSET_FROM_TRIM AreaID: 4 Status: 0 floatValues: -7 
08-25 12:55:23.011  1089  7403 I Bosch_NavSensors: GnssSourceVIP::readerThread ipc_read ret time s 23 ms 280
08-25 12:55:23.011  1089  7406 I Bosch_NavSensors: GyrUn:[0.000399, -0.000133, 0.000000, 0.000000, 0.000000, 0.000000, 1714487]
08-25 12:55:23.011  1371  1476 D GMVHAL  : setPropFromVehicle Property: PatacProperty::RIDE_HEIGHT_STATUS_4_SIGNAL_GROUP AreaID: 16777216 Status: 0 int32Values: -15 0 -7 0 -3 0 -18 0 
08-25 12:55:23.011  1089  1374 D Bosch_NavSensors: GMLocationData: [31.335979, 120.790560, 24.700000, 0.000000, 22.299988, 0.000000, 0.100000, 0.270000, 0.000000,  1787633723280]
08-25 12:55:23.011  2015  2196 D GMLocation: Service reportLocation() at time(ms) = 3603552
08-25 12:55:23.011  2015  2196 D GMLocation: Service reportLocation(), Source = HAL
08-25 12:55:23.013  1089  1373 D Bosch_NavSensors: LocationData: [31.335979, 120.790560, 24.700000, 0.000000, 22.299988, 0.000000, 0.100000, 0.270000, 0.000000, 1787633723280, 0x000000ff]
08-25 12:55:23.020  1089  7406 I Bosch_NavSensors: AccUn:[2.540248, -2.700660, 9.050082, 0.000000, 0.000000, 0.000000, 1714498]
08-25 12:55:23.020  1089  7406 I Bosch_NavSensors: Gravity:[0.000000, -2.665789, 9.437370, 3603561589717]
08-25 12:55:23.025  1371  1443 D GMVHAL  : void KeyInputPropertyManager::onLongPressRepeatDelay(const std::vector<int32_t> &)
08-25 12:55:23.025  1371  1443 D GMVHAL  : setPropFromVehicle Property: VehicleProperty::HW_KEY_INPUT AreaID: 16777216 Status: 0 int32Values: 0 25 0 
08-25 12:55:23.025  2150  2234 D CAR.INPUT: hal event code: 25, action: 0, display: 0, number of indents: 1
08-25 12:55:23.026  2371  2371 D PatacSwcHandlingService: diapatch KeyEvent KeyEvent { action=ACTION_DOWN, keyCode=KEYCODE_VOLUME_DOWN, scanCode=0, metaState=0, flags=0x0, repeatCount=17, eventTime=2370343000000, downTime=2370343000000, deviceId=0, source=0x101, displayId=0 } to HardKeyClient Callba
08-25 12:55:23.027  4515  5408 D HardKeyInterceptorManager: dispatchKeyEvent event = KeyEvent { action=ACTION_DOWN, keyCode=KEYCODE_VOLUME_DOWN, scanCode=0, metaState=0, flags=0x0, repeatCount=17, eventTime=2370343000000, downTime=2370343000000, deviceId=0, source=0x101, displayId=0 }
08-25 12:55:23.027  4515  4515 D HardKeyInterceptorManager: dispatch keyEventKeyEvent { action=ACTION_DOWN, keyCode=KEYCODE_VOLUME_DOWN, scanCode=0, metaState=0, flags=0x0, repeatCount=17, eventTime=2370343000000, downTime=2370343000000, deviceId=0, source=0x101, displayId=0 } on callback com.patac.
08-25 12:55:23.027  4515  4515 D com.patac.hmi.settings-SteeringWheelHardKeyUtil: processSWCOperation keyEvent = KeyEvent { action=ACTION_DOWN, keyCode=KEYCODE_VOLUME_DOWN, scanCode=0, metaState=0, flags=0x0, repeatCount=17, eventTime=2370343000000, downTime=2370343000000, deviceId=0, source=0x101, 
08-25 12:55:23.029  1371  1476 D GMVHAL  : setPropFromVehicle Property: PatacProperty::MIRROR_POSITION_STATUS AreaID: 1 Status: 0 floatValues: -7.8 -0.2 0 
08-25 12:55:23.029  1371  1476 D GMVHAL  : setPropFromVehicle Property: PatacProperty::FORWARD_LOOKING_LIGHT_LEVEL_EXTENDED AreaID: 16777216 Status: 0 int32Values: 36280 
08-25 12:55:23.029  1368  3139 I         : VSIP: cei::rcb (Success): 00 01 81 a3 00 00 00 53 00 00 51 2b 01 01 02 00 01 01 00 01 00 00 00 01 00 01 01 00 00 00 00 01 00 01 01 01 01 01 01 01 00 00 00 00 00 00 00 00 ff b2 ff fe ff cc 00 00 00 00 00 00 00 00 01 01 01 01 01 01 01 01 01 02 00 00 00 00 00 
08-25 12:55:23.

... [截断: 原始结果 29,114 字符，已截取中间 14,114 字符] ...

unt=19, eventTime=2370443000000, downTime=2370443000000, deviceId=0, source=0x101, displayId=0 }
08-25 12:55:23.128  4515  4515 D HardKeyInterceptorManager: dispatch keyEventKeyEvent { action=ACTION_DOWN, keyCode=KEYCODE_VOLUME_DOWN, scanCode=0, metaState=0, flags=0x0, repeatCount=19, eventTime=2370443000000, downTime=2370443000000, deviceId=0, source=0x101, displayId=0 } on callback com.patac.
08-25 12:55:23.128  4515  4515 D com.patac.hmi.settings-SteeringWheelHardKeyUtil: processSWCOperation keyEvent = KeyEvent { action=ACTION_DOWN, keyCode=KEYCODE_VOLUME_DOWN, scanCode=0, metaState=0, flags=0x0, repeatCount=19, eventTime=2370443000000, downTime=2370443000000, deviceId=0, source=0x101, 
08-25 12:55:23.128  1089  7406 I Bosch_NavSensors: GyrUn:[-0.000000, -0.001864, 0.001465, 0.000000, 0.000000, 0.000000, 1714607]
08-25 12:55:23.136  1371  1476 D GMVHAL  : setPropFromVehicle Property: PatacProperty::MIRROR_POSITION_STATUS AreaID: 1 Status: 0 floatValues: -8.1 -0.2 0 
08-25 12:55:23.137  5428  5704 I com.patac.hmi.user-UserAccount: CarDataSource:left mirror position:-8.1 -0.2 0.0 
08-25 12:55:23.137  5428  5704 I com.patac.hmi.user-UserAccount: DriverHabitMessageHandle:sendDriverHabitEvent afterCheck
08-25 12:55:23.137  5428  5704 I com.patac.hmi.user-UserAccount: SystemInfoRepository:sendSystemEvent type is 4 id is  4201
08-25 12:55:23.137  5428  5428 I com.patac.hmi.user-UserAccount: UserApplicationManager:get system event 4201
08-25 12:55:23.137  5428  5428 I com.patac.hmi.user-UserAccount: CleaNewDriverHabitManager:dealCustomEvent CLEA_DRIVER_HABIT_DATA_EVENT
08-25 12:55:23.137  5428  5428 I com.patac.hmi.user-UserAccount: DriverHabitInfoUnit:updateCurrentHabitInfo
08-25 12:55:23.137  5428  5428 I com.patac.hmi.user-UserAccount: UserFeatureManager:isMcuEnableDriverHabit mIsMcuEnableDriverHabit = true
08-25 12:55:23.137  5428  5428 I com.patac.hmi.user-UserAccount: CleaNewDriverHabitManager:dealDriverHabitDataEvent mHabitRestoreResult is null
08-25 12:55:23.154  1089  7406 I Bosch_NavSensors: AccUn:[2.530671, -2.707842, 9.045294, 0.000000, 0.000000, 0.000000, 1714628]
08-25 12:55:23.154  1089  7406 I Bosch_NavSensors: Gravity:[0.000000, -2.668532, 9.436594, 3603695138571]
08-25 12:55:23.171  2425  7756 D FSANetCommsClient: FSARemoteClient RX QSize is: 0, funcID: 100, ID: 100
08-25 12:55:23.172  2425  7756 D FSAIStateOfHealthClient: FSARemoteClient FSA: handle heartbeat 852
08-25 12:55:23.174  1371  1443 D GMVHAL  : void KeyInputPropertyManager::onLongPressRepeatDelay(const std::vector<int32_t> &)
08-25 12:55:23.174  1371  1443 D GMVHAL  : setPropFromVehicle Property: VehicleProperty::HW_KEY_INPUT AreaID: 16777216 Status: 0 int32Values: 0 25 0 
08-25 12:55:23.175  2150  2234 D CAR.INPUT: hal event code: 25, action: 0, display: 0, number of indents: 1
08-25 12:55:23.175  2371  2371 D PatacSwcHandlingService: diapatch KeyEvent KeyEvent { action=ACTION_DOWN, keyCode=KEYCODE_VOLUME_DOWN, scanCode=0, metaState=0, flags=0x0, repeatCount=20, eventTime=2370492000000, downTime=2370492000000, deviceId=0, source=0x101, displayId=0 } to HardKeyClient Callba
08-25 12:55:23.176  4515  5408 D HardKeyInterceptorManager: dispatchKeyEvent event = KeyEvent { action=ACTION_DOWN, keyCode=KEYCODE_VOLUME_DOWN, scanCode=0, metaState=0, flags=0x0, repeatCount=20, eventTime=2370492000000, downTime=2370492000000, deviceId=0, source=0x101, displayId=0 }
08-25 12:55:23.176  4515  4515 D HardKeyInterceptorManager: dispatch keyEventKeyEvent { action=ACTION_DOWN, keyCode=KEYCODE_VOLUME_DOWN, scanCode=0, metaState=0, flags=0x0, repeatCount=20, eventTime=2370492000000, downTime=2370492000000, deviceId=0, source=0x101, displayId=0 } on callback com.patac.
08-25 12:55:23.176  4515  4515 D com.patac.hmi.settings-SteeringWheelHardKeyUtil: processSWCOperation keyEvent = KeyEvent { action=ACTION_DOWN, keyCode=KEYCODE_VOLUME_DOWN, scanCode=0, metaState=0, flags=0x0, repeatCount=20, eventTime=2370492000000, downTime=2370492000000, deviceId=0, source=0x101, 
08-25 12:55:23.183  5951  6023 D CPECallbackController: Dropping carPropertyEvent - propId: 291504647 areaId: 16777216  because getTimestamp(): 3603739639816 < nextUpdateTimeNanos: 3603839639816
08-25 12:55:23.192  4156  4156 I com.patac.hmi.media-ProgressHelper: [ProgressHelper]-PlaybackState is null:true,MediaInfo is null:true
08-25 12:55:23.192  4156  4156 D com.patac.hmi.media-BTAudioManager: mPlayStateEmitter is null,Do nothing Or state is fast ward/rewind
08-25 12:55:23.211  1368  3139 I         : VSIP: cei::rcb (Success): 00 01 80 fb 00 00 00 20 00 00 51 2e 01 01 02 00 01 00 00 00 00 00 00 00 00 4a 18 00 00 00 00 00 00 00 00 00 02 08 54 00 
08-25 12:55:23.219  1089  7403 I Bosch_NavSensors: GnssSourceVIP::readerThread ipc_read ret time s 23 ms 480
08-25 12:55:23.219  1089  1374 D Bosch_NavSensors: GMLocationData: [31.335979, 120.790560, 24.700000, 0.000000, 22.299988, 0.000000, 0.100000, 0.270000, 0.000000,  1787633723480]
08-25 12:55:23.220  2015  2196 D GMLocation: Service reportLocation() at time(ms) = 3603761
08-25 12:55:23.220  2015  2196 D GMLocation: Service reportLocation(), Source = HAL
08-25 12:55:23.220  1089  1373 D Bosch_NavSensors: LocationData: [31.335979, 120.790560, 24.700000, 0.000000, 22.299988, 0.000000, 0.100000, 0.270000, 0.000000, 1787633723480, 0x000000ff]
08-25 12:55:23.225  1371  1443 D GMVHAL  : void KeyInputPropertyManager::onLongPressRepeatDelay(const std::vector<int32_t> &)
08-25 12:55:23.225  1371  1443 D GMVHAL  : setPropFromVehicle Property: VehicleProperty::HW_KEY_INPUT AreaID: 16777216 Status: 0 int32Values: 0 25 0 
08-25 12:55:23.225  2150  2234 D CAR.INPUT: hal event code: 25, action: 0, display: 0, number of indents: 1
08-25 12:55:23.228  2371  2371 D PatacSwcHandlingService: diapatch KeyEvent KeyEvent { action=ACTION_DOWN, keyCode=KEYCODE_VOLUME_DOWN, scanCode=0, metaState=0, flags=0x0, repeatCount=21, eventTime=2370543000000, downTime=2370543000000, deviceId=0, source=0x101, displayId=0 } to HardKeyClient Callba
08-25 12:55:23.228  4515  5408 D HardKeyInterceptorManager: dispatchKeyEvent event = KeyEvent { action=ACTION_DOWN, keyCode=KEYCODE_VOLUME_DOWN, scanCode=0, metaState=0, flags=0x0, repeatCount=21, eventTime=2370543000000, downTime=2370543000000, deviceId=0, source=0x101, displayId=0 }
08-25 12:55:23.228  4515  4515 D HardKeyInterceptorManager: dispatch keyEventKeyEvent { action=ACTION_DOWN, keyCode=KEYCODE_VOLUME_DOWN, scanCode=0, metaState=0, flags=0x0, repeatCount=21, eventTime=2370543000000, downTime=2370543000000, deviceId=0, source=0x101, displayId=0 } on callback com.patac.
08-25 12:55:23.228  4515  4515 D com.patac.hmi.settings-SteeringWheelHardKeyUtil: processSWCOperation keyEvent = KeyEvent { action=ACTION_DOWN, keyCode=KEYCODE_VOLUME_DOWN, scanCode=0, metaState=0, flags=0x0, repeatCount=21, eventTime=2370543000000, downTime=2370543000000, deviceId=0, source=0x101, 
08-25 12:55:23.244  1371  1476 D GMVHAL  : setPropFromVehicle Property: PatacProperty::MIRROR_POSITION_STATUS AreaID: 1 Status: 0 floatValues: -8.5 -0.2 0 
08-25 12:55:23.245  5428  5704 I com.patac.hmi.user-UserAccount: CarDataSource:left mirror position:-8.5 -0.2 0.0 
08-25 12:55:23.245  5428  5704 I com.patac.hmi.user-UserAccount: DriverHabitMessageHandle:sendDriverHabitEvent afterCheck
08-25 12:55:23.245  5428  5704 I com.patac.hmi.user-UserAccount: SystemInfoRepository:sendSystemEvent type is 4 id is  4201
08-25 12:55:23.245  5428  5428 I com.patac.hmi.user-UserAccount: UserApplicationManager:get system event 4201

---

## 第 18 轮 — LLM 响应



---

## 第 18 轮 — 工具执行结果

[结果 1] 相同工具和参数已执行 2 次，read_time_range 未再次执行

---

## 第 19 轮 — LLM 响应



---

## 第 19 轮 — 工具执行结果

[结果 1] 日志搜索调用数已达上限 25，search_log 未执行

---

## 第 20 轮 — LLM 响应

搜索调用已达上限。让我改用 read_time_range 读取关键时间段的原始日志，并查阅知识库理解 DriverHabit 记忆机制。



---

## 第 20 轮 — 工具执行结果

[结果 1] 时间范围 [12:55:22.300 ~ 12:55:23.500] (PID=无): 共 744 行
涉及的 PID: 1080, 1089, 1129, 1368, 1371
涉及的 TAG: , ACCGYROCALIBRATION, AHAL, ActivityManager, Bosch_NavSensors, CAR.INPUT, CPECallbackController, Calibrationd, CarLinkManager, CarPropertyManager

08-25 12:55:23.025  2150  2234 D CAR.INPUT: hal event code: 25, action: 0, display: 0, number of indents: 1
08-25 12:55:23.035   732   732 I Calibrationd: [532501538040]CalibrationUsageLog.cpp::logUsage(34): Calibration Requested: com.patac.hmi.user: GMModel: ENUMERATION: [Module]GMModel: ENUMERATION: 84
08-25 12:55:23.075  2150  2234 D CAR.INPUT: hal event code: 25, action: 0, display: 0, number of indents: 1
08-25 12:55:23.125  2150  2234 D CAR.INPUT: hal event code: 25, action: 0, display: 0, number of indents: 1
08-25 12:55:23.175  2150  2234 D CAR.INPUT: hal event code: 25, action: 0, display: 0, number of indents: 1
08-25 12:55:23.225  2150  2234 D CAR.INPUT: hal event code: 25, action: 0, display: 0, number of indents: 1
08-25 12:55:23.275  2150  2234 D CAR.INPUT: hal event code: 25, action: 0, display: 0, number of indents: 1
08-25 12:55:23.326  2150  2234 D CAR.INPUT: hal event code: 25, action: 0, display: 0, number of indents: 1
08-25 12:55:23.339   732   732 I Calibrationd: [532501538040]CalibrationUsageLog.cpp::logUsage(34): Calibration Requested: com.patac.hmi.user: GMModel: ENUMERATION: [Module]GMModel: ENUMERATION: 84
08-25 12:55:23.376  2150  2234 D CAR.INPUT: hal event code: 25, action: 0, display: 0, number of indents: 1
08-25 12:55:23.426  2150  2234 D CAR.INPUT: hal event code: 25, action: 0, display: 0, number of indents: 1
08-25 12:55:23.475  2150  2234 D CAR.INPUT: hal event code: 25, action: 0, display: 0, number of indents: 1
08-25 12:55:23.525  2150  2234 D CAR.INPUT: hal event code: 25, action: 0, display: 0, number of indents: 1
08-25 12:55:23.535  1683  2115 W ActivityManager: Unable to start service Intent { cmp=com.sgm.navi.hmi/com.sgm.navi.exportservice.MapService (has extras) } U=10: not found
08-25 12:55:23.578  2150  2234 D CAR.INPUT: hal event code: 25, action: 0, display: 0, number of indents: 1
08-25 12:55:23.581  1683  2115 D NetworkPolicy: Blocked state of 10019: {blocked=NONE,allowed=FOREGROUND|TOP|METERED_FOREGROUND,effective=NONE}
08-25 12:55:23.604   737   829 I PLSS_PMSvc: onSystemState: RUN(5)
08-25 12:55:23.615  1683  2115 W ActivityManager: Unable to start service Intent { act=com.sgm.scene.service.SceneService cmp=com.sgm.scene.app/com.sgm.scene.service.SceneService } U=10: not found
08-25 12:55:23.626  2150  2234 D CAR.INPUT: hal event code: 25, action: 0, display: 0, number of indents: 1
08-25 12:55:23.638   732   732 I Calibrationd: [532501538040]CalibrationUsageLog.cpp::logUsage(34): Calibration Requested: com.patac.hmi.user: GMModel: ENUMERATION: [Module]GMModel: ENUMERATION: 84
08-25 12:55:23.677  2150  2234 D CAR.INPUT: hal event code: 25, action: 0, display: 0, number of indents: 1
08-25 12:55:23.727  2150  2234 D CAR.INPUT: hal event code: 25, action: 0, display: 0, number of indents: 1
08-25 12:55:23.776  2150  2234 D CAR.INPUT: hal event code: 25, action: 0, display: 0, number of indents: 1
08-25 12:55:23.826  2150  2234 D CAR.INPUT: hal event code: 25, action: 0, display: 0, number of indents: 1
08-25 12:55:23.875  2150  2234 D CAR.INPUT: hal event code: 25, action: 0, display: 0, number of indents: 1
08-25 12:55:23.905  1683  2115 W ActivityManager: Unable to start service Intent { act=com.patac.carlink.SDK pkg=com.patac.carlink } U=10: not found
08-25 12:55:23.927  2150  2234 D CAR.INPUT: hal event code: 25, action: 0, display: 0, number of indents: 1
08-25 12:55:23.943   732   732 I Calibrationd: [532501538040]CalibrationUsageLog.cpp::logUsage(34): Calibration Requested: com.patac.hmi.user: GMModel: ENUMERATION: [Module]GMModel: ENUMERATION: 84
08-25 12:55:23.975  2150  2234 D CAR.INPUT: hal event code: 25, action: 0, display: 0, number of indents: 1
08-25 12:55:23.011  1371  1476 D GMVHAL  : setPropFromVehicle Property: VendorProperty::POSITION_OFFSET_FROM_TRIM AreaID: 4 Status: 0 floatValues: -7 
08-25 12:55:23.011  1089  7403 I Bosch_NavSensors: GnssSourceVIP::readerThread ipc_read ret time s 23 ms 280
08-25 12:55:23.011  1089  7406 I Bosch_NavSensors: GyrUn:[0.000399, -0.000133, 0.000000, 0.000000, 0.000000, 0.000000, 1714487]
08-25 12:55:23.011  1371  1476 D GMVHAL  : setPropFromVehicle Property: PatacProperty::RIDE_HEIGHT_STATUS_4_SIGNAL_GROUP AreaID: 16777216 Status: 0 int32Values: -15 0 -7 0 -3 0 -18 0 
08-25 12:55:23.011  1089  1374 D Bosch_NavSensors: GMLocationData: [31.335979, 120.790560, 24.700000, 0.000000, 22.299988, 0.000000, 0.100000, 0.270000, 0.000000,  1787633723280]
08-25 12:55:23.011  2015  2196 D GMLocation: Service reportLocation() at time(ms) = 3603552
08-25 12:55:23.011  2015  2196 D GMLocation: Service reportLocation(), Source = HAL
08-25 12:55:23.013  1089  1373 D Bosch_NavSensors: LocationData: [31.335979, 120.790560, 24.700000, 0.000000, 22.299988, 0.000000, 0.100000, 0.270000, 0.000000, 1787633723280, 0x000000ff]
08-25 12:55:23.020  1089  7406 I Bosch_NavSensors: AccUn:[2.540248, -2.700660, 9.050082, 0.000000, 0.000000, 0.000000, 1714498]
08-25 12:55:23.020  1089  7406 I Bosch_NavSensors: Gravity:[0.000000, -2.665789, 9.437370, 3603561589717]
08-25 12:55:23.025  1371  1443 D GMVHAL  : void KeyInputPropertyManager::onLongPressRepeatDelay(const std::vector<int32_t> &)
08-25 12:55:23.025  1371  1443 D GMVHAL  : setPropFromVehicle Property: VehicleProperty::HW_KEY_INPUT AreaID: 16777216 Status: 0 int32Values: 0 25 0 
08-25 12:55:23.025  2150  2234 D CAR.INPUT: hal event code: 25, action: 0, display: 0, number of indents: 1
08-25 12:55:23.026  2371  2371 D PatacSwcHandlingService: diapatch KeyEvent KeyEvent { action=ACTION_DOWN, keyCode=KEYCODE_VOLUME_DOWN, scanCode=0, metaState=0, flags=0x0, repeatCount=17, eventTime=2370343000000, downTime=2370343000000, deviceId=0, source=0x101, displayId=0 } to HardKeyClient Callba
08-25 12:55:23.027  4515  5408 D HardKeyInterceptorManager: dispatchKeyEvent event = KeyEvent { action=ACTION_DOWN, keyCode=KEYCODE_VOLUME_DOWN, scanCode=0, metaState=0, flags=0x0, repeatCount=17, eventTime=2370343000000, downTime=2370343000000, deviceId=0, source=0x101, displayId=0 }
08-25 12:55:23.027  4515  4515 D HardKeyInterceptorManager: dispatch keyEventKeyEvent { action=ACTION_DOWN, keyCode=KEYCODE_VOLUME_DOWN, scanCode=0, metaState=0, flags=0x0, repeatCount=17, eventTime=2370343000000, downTime=2370343000000, deviceId=0, source=0x101, displayId=0 } on callback com.patac.
08-25 12:55:23.027  4515  4515 D com.patac.hmi.settings-SteeringWheelHardKeyUtil: processSWCOperation keyEvent = KeyEvent { action=ACTION_DOWN, keyCode=KEYCODE_VOLUME_DOWN, scanCode=0, metaState=0, flags=0x0, repeatCount=17, eventTime=2370343000000, downTime=2370343000000, deviceId=0, source=0x101, 
08-25 12:55:23.029  1371  1476 D GMVHAL  : setPropFromVehicle Property: PatacProperty::MIRROR_POSITION_STATUS AreaID: 1 Status: 0 floatValues: -7.8 -0.2 0 
08-25 12:55:23.029  1371  1476 D GMVHAL  : setPropFromVehicle Property: PatacProperty::FORWARD_LOOKING_LIGHT_LEVEL_EXTENDED AreaID: 16777216 Status: 0 int32Values: 36280 
08-25 12:55:23.029  1368  3139 I         : VSIP: cei::rcb (Success): 00 01 81 a3 00 00 00 53 00 00 51 2b 01 01 02 00 01 01 00 01 00 00 00 01 00 01 01 00 00 00 00 01 00 01 01 01 01 01 01 01 00 00 00 00 00 00 00 00 ff b2 ff fe ff cc 00 00 00 00 00 00 00 00 01 01 01 01 01 01 01 01 01 02 00 00 00 00 00 
08-25 12:55:23.

... [截断: 原始结果 29,114 字符，已截取中间 14,114 字符] ...

unt=19, eventTime=2370443000000, downTime=2370443000000, deviceId=0, source=0x101, displayId=0 }
08-25 12:55:23.128  4515  4515 D HardKeyInterceptorManager: dispatch keyEventKeyEvent { action=ACTION_DOWN, keyCode=KEYCODE_VOLUME_DOWN, scanCode=0, metaState=0, flags=0x0, repeatCount=19, eventTime=2370443000000, downTime=2370443000000, deviceId=0, source=0x101, displayId=0 } on callback com.patac.
08-25 12:55:23.128  4515  4515 D com.patac.hmi.settings-SteeringWheelHardKeyUtil: processSWCOperation keyEvent = KeyEvent { action=ACTION_DOWN, keyCode=KEYCODE_VOLUME_DOWN, scanCode=0, metaState=0, flags=0x0, repeatCount=19, eventTime=2370443000000, downTime=2370443000000, deviceId=0, source=0x101, 
08-25 12:55:23.128  1089  7406 I Bosch_NavSensors: GyrUn:[-0.000000, -0.001864, 0.001465, 0.000000, 0.000000, 0.000000, 1714607]
08-25 12:55:23.136  1371  1476 D GMVHAL  : setPropFromVehicle Property: PatacProperty::MIRROR_POSITION_STATUS AreaID: 1 Status: 0 floatValues: -8.1 -0.2 0 
08-25 12:55:23.137  5428  5704 I com.patac.hmi.user-UserAccount: CarDataSource:left mirror position:-8.1 -0.2 0.0 
08-25 12:55:23.137  5428  5704 I com.patac.hmi.user-UserAccount: DriverHabitMessageHandle:sendDriverHabitEvent afterCheck
08-25 12:55:23.137  5428  5704 I com.patac.hmi.user-UserAccount: SystemInfoRepository:sendSystemEvent type is 4 id is  4201
08-25 12:55:23.137  5428  5428 I com.patac.hmi.user-UserAccount: UserApplicationManager:get system event 4201
08-25 12:55:23.137  5428  5428 I com.patac.hmi.user-UserAccount: CleaNewDriverHabitManager:dealCustomEvent CLEA_DRIVER_HABIT_DATA_EVENT
08-25 12:55:23.137  5428  5428 I com.patac.hmi.user-UserAccount: DriverHabitInfoUnit:updateCurrentHabitInfo
08-25 12:55:23.137  5428  5428 I com.patac.hmi.user-UserAccount: UserFeatureManager:isMcuEnableDriverHabit mIsMcuEnableDriverHabit = true
08-25 12:55:23.137  5428  5428 I com.patac.hmi.user-UserAccount: CleaNewDriverHabitManager:dealDriverHabitDataEvent mHabitRestoreResult is null
08-25 12:55:23.154  1089  7406 I Bosch_NavSensors: AccUn:[2.530671, -2.707842, 9.045294, 0.000000, 0.000000, 0.000000, 1714628]
08-25 12:55:23.154  1089  7406 I Bosch_NavSensors: Gravity:[0.000000, -2.668532, 9.436594, 3603695138571]
08-25 12:55:23.171  2425  7756 D FSANetCommsClient: FSARemoteClient RX QSize is: 0, funcID: 100, ID: 100
08-25 12:55:23.172  2425  7756 D FSAIStateOfHealthClient: FSARemoteClient FSA: handle heartbeat 852
08-25 12:55:23.174  1371  1443 D GMVHAL  : void KeyInputPropertyManager::onLongPressRepeatDelay(const std::vector<int32_t> &)
08-25 12:55:23.174  1371  1443 D GMVHAL  : setPropFromVehicle Property: VehicleProperty::HW_KEY_INPUT AreaID: 16777216 Status: 0 int32Values: 0 25 0 
08-25 12:55:23.175  2150  2234 D CAR.INPUT: hal event code: 25, action: 0, display: 0, number of indents: 1
08-25 12:55:23.175  2371  2371 D PatacSwcHandlingService: diapatch KeyEvent KeyEvent { action=ACTION_DOWN, keyCode=KEYCODE_VOLUME_DOWN, scanCode=0, metaState=0, flags=0x0, repeatCount=20, eventTime=2370492000000, downTime=2370492000000, deviceId=0, source=0x101, displayId=0 } to HardKeyClient Callba
08-25 12:55:23.176  4515  5408 D HardKeyInterceptorManager: dispatchKeyEvent event = KeyEvent { action=ACTION_DOWN, keyCode=KEYCODE_VOLUME_DOWN, scanCode=0, metaState=0, flags=0x0, repeatCount=20, eventTime=2370492000000, downTime=2370492000000, deviceId=0, source=0x101, displayId=0 }
08-25 12:55:23.176  4515  4515 D HardKeyInterceptorManager: dispatch keyEventKeyEvent { action=ACTION_DOWN, keyCode=KEYCODE_VOLUME_DOWN, scanCode=0, metaState=0, flags=0x0, repeatCount=20, eventTime=2370492000000, downTime=2370492000000, deviceId=0, source=0x101, displayId=0 } on callback com.patac.
08-25 12:55:23.176  4515  4515 D com.patac.hmi.settings-SteeringWheelHardKeyUtil: processSWCOperation keyEvent = KeyEvent { action=ACTION_DOWN, keyCode=KEYCODE_VOLUME_DOWN, scanCode=0, metaState=0, flags=0x0, repeatCount=20, eventTime=2370492000000, downTime=2370492000000, deviceId=0, source=0x101, 
08-25 12:55:23.183  5951  6023 D CPECallbackController: Dropping carPropertyEvent - propId: 291504647 areaId: 16777216  because getTimestamp(): 3603739639816 < nextUpdateTimeNanos: 3603839639816
08-25 12:55:23.192  4156  4156 I com.patac.hmi.media-ProgressHelper: [ProgressHelper]-PlaybackState is null:true,MediaInfo is null:true
08-25 12:55:23.192  4156  4156 D com.patac.hmi.media-BTAudioManager: mPlayStateEmitter is null,Do nothing Or state is fast ward/rewind
08-25 12:55:23.211  1368  3139 I         : VSIP: cei::rcb (Success): 00 01 80 fb 00 00 00 20 00 00 51 2e 01 01 02 00 01 00 00 00 00 00 00 00 00 4a 18 00 00 00 00 00 00 00 00 00 02 08 54 00 
08-25 12:55:23.219  1089  7403 I Bosch_NavSensors: GnssSourceVIP::readerThread ipc_read ret time s 23 ms 480
08-25 12:55:23.219  1089  1374 D Bosch_NavSensors: GMLocationData: [31.335979, 120.790560, 24.700000, 0.000000, 22.299988, 0.000000, 0.100000, 0.270000, 0.000000,  1787633723480]
08-25 12:55:23.220  2015  2196 D GMLocation: Service reportLocation() at time(ms) = 3603761
08-25 12:55:23.220  2015  2196 D GMLocation: Service reportLocation(), Source = HAL
08-25 12:55:23.220  1089  1373 D Bosch_NavSensors: LocationData: [31.335979, 120.790560, 24.700000, 0.000000, 22.299988, 0.000000, 0.100000, 0.270000, 0.000000, 1787633723480, 0x000000ff]
08-25 12:55:23.225  1371  1443 D GMVHAL  : void KeyInputPropertyManager::onLongPressRepeatDelay(const std::vector<int32_t> &)
08-25 12:55:23.225  1371  1443 D GMVHAL  : setPropFromVehicle Property: VehicleProperty::HW_KEY_INPUT AreaID: 16777216 Status: 0 int32Values: 0 25 0 
08-25 12:55:23.225  2150  2234 D CAR.INPUT: hal event code: 25, action: 0, display: 0, number of indents: 1
08-25 12:55:23.228  2371  2371 D PatacSwcHandlingService: diapatch KeyEvent KeyEvent { action=ACTION_DOWN, keyCode=KEYCODE_VOLUME_DOWN, scanCode=0, metaState=0, flags=0x0, repeatCount=21, eventTime=2370543000000, downTime=2370543000000, deviceId=0, source=0x101, displayId=0 } to HardKeyClient Callba
08-25 12:55:23.228  4515  5408 D HardKeyInterceptorManager: dispatchKeyEvent event = KeyEvent { action=ACTION_DOWN, keyCode=KEYCODE_VOLUME_DOWN, scanCode=0, metaState=0, flags=0x0, repeatCount=21, eventTime=2370543000000, downTime=2370543000000, deviceId=0, source=0x101, displayId=0 }
08-25 12:55:23.228  4515  4515 D HardKeyInterceptorManager: dispatch keyEventKeyEvent { action=ACTION_DOWN, keyCode=KEYCODE_VOLUME_DOWN, scanCode=0, metaState=0, flags=0x0, repeatCount=21, eventTime=2370543000000, downTime=2370543000000, deviceId=0, source=0x101, displayId=0 } on callback com.patac.
08-25 12:55:23.228  4515  4515 D com.patac.hmi.settings-SteeringWheelHardKeyUtil: processSWCOperation keyEvent = KeyEvent { action=ACTION_DOWN, keyCode=KEYCODE_VOLUME_DOWN, scanCode=0, metaState=0, flags=0x0, repeatCount=21, eventTime=2370543000000, downTime=2370543000000, deviceId=0, source=0x101, 
08-25 12:55:23.244  1371  1476 D GMVHAL  : setPropFromVehicle Property: PatacProperty::MIRROR_POSITION_STATUS AreaID: 1 Status: 0 floatValues: -8.5 -0.2 0 
08-25 12:55:23.245  5428  5704 I com.patac.hmi.user-UserAccount: CarDataSource:left mirror position:-8.5 -0.2 0.0 
08-25 12:55:23.245  5428  5704 I com.patac.hmi.user-UserAccount: DriverHabitMessageHandle:sendDriverHabitEvent afterCheck
08-25 12:55:23.245  5428  5704 I com.patac.hmi.user-UserAccount: SystemInfoRepository:sendSystemEvent type is 4 id is  4201
08-25 12:55:23.245  5428  5428 I com.patac.hmi.user-UserAccount: UserApplicationManager:get system event 4201

---

[结果 2] WIKI 文档 [knowledge_list]:
[车控娱乐]
- 车控娱乐/Album-EConnection.md: LocalSend 连接链路日志分析指引（扫码/建链/传输）
- 车控娱乐/Climate.md: 背景
- 车控娱乐/Connection.md: 常见问题集中于Device设备状态是否正常，设备切换流程是否存在问题
- 车控娱乐/DBA.md: 背景
- 车控娱乐/Energy.md: Energy包含的主要功能：充电、放电、能源管理、能量流，界面包括能量中心、充/放电桌面、Kanzi车模。
- 车控娱乐/EngMode.md: 问题类型
- 车控娱乐/Gallery.md: PATACGallery 媒体时间线到详情页日志分析指引
- 车控娱乐/OnlineMusic.md: 常见在线音乐播放问题表现为两个或多个音源同时播放导致的通话结束后，车机媒体未续播、混音问题、数据加载失败等，从根因来看主
- 车控娱乐/Onstar.md: 常见的OnStar问题包括安吉星电话无法打出，安吉星挂断失败/延迟，安吉星显示失败弹框，安吉星odd弹框不显示。
- 车控娱乐/Seat.md: 常见问题定位从表面来讲包含座椅通风按钮置灰、缺少副驾零重力按钮、座舱模式提示不可用问题
- 车控娱乐/Setting.md: 车辆信息
- 车控娱乐/Theme.md: 常见主题壁纸问题从表现形式上来讲包括：下载失败、更新异常、切换无效、显示异常、存储空间不足等。从根因上来看主要分为几类：
- 车控娱乐/calendar.md: 常见的日历问题包括打开农历开关无法显示农历与节假日信息。
- 车控娱乐/customsetting.md: 常见的日历问题包括首次登录无同步弹框，个性化同步失败。
- 车控娱乐/media.md: Tuner典型问题类型列举
- 车控娱乐/phone.md: 背景
- 车控娱乐/user.md: 常见的日历问题包括首次登录无同步弹框，个性化同步失败。
- 车控娱乐/展厅.md: ShowRoom典型问题类型列举
- 车控娱乐/无麦K歌.md: 常见的无麦k歌问题包括界面不显示无麦K歌悬浮窗，悬浮框原伴唱状态与当前音源不一致。
