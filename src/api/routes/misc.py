"""Misc routes - 5 endpoints: auth, favicon, root, doc-images"""
from fastapi import APIRouter, Request, Query
from fastapi.responses import JSONResponse, FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
import os

from src.schemas.common import ApiResponse
from src.config import PROJECT_ROOT

router = APIRouter()

# 前端构建产物目录：frontend/dist/
_FRONTEND_DIST = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))),
    "frontend", "dist",
)


@router.get("/api/doc-images/{bugid}/{filename}")
async def serve_doc_image(bugid: str, filename: str):
    from src.services.server_legacy import _DOC_IMAGES_DIR
    filepath = os.path.join(_DOC_IMAGES_DIR, bugid, filename)
    if not os.path.isfile(filepath):
        return JSONResponse({"ok": False, "message": "图片不存在"}, status_code=404)
    return FileResponse(filepath)


@router.get("/api/auth/authorize", response_model=ApiResponse)
async def get_authorize_url(request: Request):
    from src.api.routes.shared import ok as _ok
    from src.config import load_config
    cfg = load_config().get("feishu_bitable", {})
    app_id = cfg.get("app_id", "")
    scopes = "bitable:app docx:document docx:document:readonly sheets:spreadsheet:readonly drive:drive drive:drive:readonly im:chat:readonly im:message:readonly im:message.p2p_msg:get_as_user im:message.group_msg:get_as_user wiki:wiki"
    redirect_uri = str(request.url_for("oauth_callback"))
    redirect_uri = redirect_uri.replace("127.0.0.1", "localhost")
    url = (f"https://open.feishu.cn/open-apis/authen/v1/authorize"
           f"?app_id={app_id}&redirect_uri={redirect_uri}&scope={scopes}")
    return _ok({"authorize_url": url}, "请点击链接完成授权")


@router.get("/api/callback", name="oauth_callback")
async def oauth_callback(code: str = "", error: str = ""):
    from src.config import setup_logger
    from src.api.routes.shared import oauth_cache as _oauth_cache
    from src.config import load_config
    from src.services.server_legacy import _save_user_token_to_config
    import httpx as _httpx
    logger = setup_logger("oauth_callback")
    logger.info("OAuth 回调触发: code=%s, error=%s", bool(code), error)
    if error:
        logger.error("OAuth 授权失败: %s", error)
        return JSONResponse(content={"ok": False, "message": f"授权失败: {error}"}, status_code=200)
    if not code:
        logger.error("OAuth 回调未收到授权码")
        return JSONResponse(content={"ok": False, "message": "未收到授权码"}, status_code=200)
    cfg = load_config().get("feishu_bitable", {})
    url = "https://open.feishu.cn/open-apis/authen/v1/oidc/access_token"
    payload = {"grant_type": "authorization_code", "code": code}
    token_url = "https://open.feishu.cn/open-apis/auth/v3/app_access_token/internal"
    token_resp = _httpx.post(token_url, json={
        "app_id": cfg.get("app_id", ""),
        "app_secret": cfg.get("app_secret", ""),
    }, timeout=10, verify=False)
    app_token = token_resp.json().get("app_access_token", "")
    logger.info("获取 app_access_token: %s", "成功" if app_token else "失败")
    resp = _httpx.post(url, json=payload, headers={
        "Authorization": f"Bearer {app_token}",
        "Content-Type": "application/json",
    }, timeout=10, verify=False)
    data = resp.json()
    logger.info("换取 user_access_token 响应: code=%s", data.get("code"))
    if data.get("code") == 0:
        user_token = data.get("data", {}).get("access_token", "")
        refresh_token = data.get("data", {}).get("refresh_token", "")
        expire = data.get("data", {}).get("expires_in", 7200)
        scope = data.get("data", {}).get("scope", "")
        logger.info("OAuth 授权成功: scope=%s, expires_in=%ds, token_prefix=%s", scope, expire, user_token[:20])
        _oauth_cache["token"] = user_token
        _oauth_cache["code"] = code
        _save_user_token_to_config(user_token, refresh_token)
        html = (f"<html><body style='font-family:sans-serif;text-align:center;padding:60px'>"
                f"<h2 style='color:#67c23a'>✅ 授权成功</h2>"
                f"<p>scope: <code>{scope}</code></p>"
                f"<p>有效期: {expire}s</p>"
                f"<p style='color:#999'>请关闭此页面，回到测试页面点击「列出所有聊天」</p>"
                f"</body></html>")
        return HTMLResponse(content=html, status_code=200)
    logger.error("换取 user_access_token 失败: %s", data.get("msg"))
    return JSONResponse(content={"ok": False, "message": f"换取 token 失败: {data.get('msg')}"}, status_code=200)


@router.get("/favicon.ico")
def favicon():
    from fastapi.responses import Response
    return Response(status_code=204)


@router.get("/")
def index():
    """Serve 前端构建产物，未构建时返回提示信息"""
    dist_index = os.path.join(_FRONTEND_DIST, "index.html")
    if os.path.isfile(dist_index):
        return FileResponse(
            dist_index,
            headers={"Cache-Control": "no-cache, no-store, must-revalidate", "Pragma": "no-cache"},
        )
    return HTMLResponse(
        "<h2>前端未构建</h2><p>请执行 <code>cd frontend && npm run build</code> 或使用开发模式 <code>npx vite</code></p>",
        status_code=200,
    )


def mount_frontend_assets(app):
    """挂载前端构建产物的 assets 目录（Vite 构建后的 JS/CSS）"""
    assets_dir = os.path.join(_FRONTEND_DIST, "assets")
    if os.path.isdir(assets_dir):
        app.mount("/assets", StaticFiles(directory=assets_dir), name="frontend-assets")
    # 挂载 reports 目录，使报告 HTML 可通过浏览器访问
    reports_dir = os.path.join(PROJECT_ROOT, "reports")
    if os.path.isdir(reports_dir):
        app.mount("/reports", StaticFiles(directory=reports_dir), name="report-files")