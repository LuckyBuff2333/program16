"""多维表格路由：未验证 Jira 号提取"""
from fastapi import APIRouter, Request

from src.config import load_config, setup_logger
from src.schemas.common import ApiResponse

logger = setup_logger("web.bitable")
router = APIRouter()


@router.post("/api/bitable/unverified_jiras", response_model=ApiResponse)
async def bitable_unverified_jiras(request: Request):
    """从多维表格提取所有"分析结果=成功"且置信度为空的记录"""
    from src.clients import feishu_client
    from src.api.routes.shared import ok as _ok, fail as _fail
    cfg = load_config().get("feishu_bitable", {})
    app_token = cfg.get("app_token", "")
    table_id = cfg.get("table_id", "")
    bugid_field = cfg.get("bugid_field", "jira号")
    conf_field = cfg.get("confidence_field", "结果置信度")
    if not app_token or not table_id:
        return _fail("多维表格 app_token/table_id 未配置")
    try:
        records = feishu_client.list_bitable_records(app_token, table_id)
        result, seen = [], set()
        for rec in records:
            fields = rec.get("fields", {})
            result_status = str(fields.get("分析结果", "")).strip()
            if result_status != "成功":
                continue
            conf_val = fields.get(conf_field, "")
            if isinstance(conf_val, list):
                conf_val = " ".join(str(v) for v in conf_val)
            conf_str = str(conf_val).strip()
            if not conf_str or conf_str == "0" or conf_str == "0.0":
                fv = fields.get(bugid_field, "")
                if isinstance(fv, list):
                    fv = " ".join(str(v) for v in fv)
                fv = str(fv).strip()
                if fv and fv not in seen:
                    seen.add(fv)
                    result.append({
                        "jira号": fv,
                        "分析问题时间": str(fields.get("分析问题时间", "")).strip(),
                        "分析结果": "成功",
                        "rootcause": str(fields.get("rootcause", "")).strip()[:100],
                        "AI评论总结": str(fields.get("AI评论总结", "")).strip()[:100],
                    })
        result.sort(key=lambda r: r["jira号"])
        jira_list = [r["jira号"] for r in result]
        return _ok({"jiras": jira_list, "records": result, "count": len(result)}, f"提取到 {len(result)} 个置信度为空的 Jira 号")
    except Exception as e:
        logger.error("提取未验证Jira号失败: %s", e, exc_info=True)
        return _fail(f"提取失败: {e}")
