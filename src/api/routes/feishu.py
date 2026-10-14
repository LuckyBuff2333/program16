"""飞书路由：事件订阅回调与调试端点"""
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from src.config import setup_logger
from src.schemas.common import ApiResponse

logger = setup_logger("web.feishu")
router = APIRouter()


@router.post("/api/feishu/event")
async def feishu_event(request: Request):
    """飞书事件订阅回调（HTTP回调模式）"""
    from src.services.server_legacy import _process_feishu_message_event
    data = await request.json() or {}
    if data.get("type") == "url_verification":
        challenge = data.get("challenge", "")
        logger.info("飞书事件订阅验证: challenge=%s", challenge[:20])
        return JSONResponse(content={"challenge": challenge})
    header = data.get("header", {})
    event = data.get("event", {})
    if header.get("event_type") == "im.message.receive_v1":
        _process_feishu_message_event(event)
    return JSONResponse(content={"code": 0})


@router.get("/api/feishu/events", response_model=ApiResponse)
async def get_feishu_events():
    """查看已存储的飞书事件推送 + 卡片事件 + 最近消息（调试用）"""
    from src.clients import feishu_client as _fc
    from src.api.routes.shared import ok as _ok
    from src.services.server_legacy import _feishu_recent_messages
    events = dict(_fc._feishu_events)
    card_events = list(_fc._feishu_card_events[-20:][::-1])
    recent = list(_feishu_recent_messages[-20:][::-1])
    return _ok({
        "events": events, "count": len(events),
        "card_events": card_events, "card_count": len(card_events),
        "recent_messages": recent, "recent_count": len(recent)
    }, f"事件{len(events)}个 / 卡片{len(card_events)}条 / 消息{len(recent)}条")


@router.post("/api/test/feishu_msg_debug")
async def test_feishu_msg_debug(request: Request):
    """调试用：尝试所有认证方式读取指定群聊的消息"""
    from src.services.server_legacy import _feishu_msg_debug_impl
    return await _feishu_msg_debug_impl(request)
