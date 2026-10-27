"""CLI 入口：analyze / retry / store 三个子命令

工具运行结果不写入数据库，只生成文档与每日 CSV 结论报表；
知识库入库由开发手工执行 store 命令触发，不做自动化。
"""
import argparse
import os
import sys
from datetime import datetime

# 确保项目根目录在 sys.path 中，支持 python src/main.py 直接运行
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from src import db, pipeline
from src.config import get_path, setup_logger
from src.core import audit as audit_module

logger = setup_logger("main")


def _parse_trigger_times(pairs: list) -> dict:
    """解析 --trigger-time 参数列表，格式为 bugid=触发时间"""
    result = {}
    for pair in pairs or []:
        if "=" not in pair:
            raise ValueError(f"触发时间参数格式错误（应为 bugid=时间）: {pair}")
        bugid, time_str = pair.split("=", 1)
        result[bugid.strip()] = time_str.strip()
    return result


def cmd_analyze(args):
    """步骤1~3：去重过滤、AI 分析生成文档、比对并输出当日报表"""
    trigger_times = _parse_trigger_times(args.trigger_time)
    csv_path = pipeline.run_pipeline(args.bugids, trigger_times)
    print(f"分析流程完成，当日报表: {csv_path}")


def cmd_retry(args):
    """失败 bug 重新分析（开发手工触发），直至分析正确"""
    csv_path = pipeline.retry_bug(args.bugid)
    print(f"bugid={args.bugid} 重新分析完成，结论报表已更新: {csv_path}")


def cmd_store(args):
    """开发确认后手工将分析文档推入知识库（是否入库由执行人自行判断）"""
    pipeline.store_bug(args.bugid)
    print(f"bugid={args.bugid} 分析文档已推入知识库")


def cmd_report(args):
    """查看当日结论报表路径（报表由 analyze/retry 自动生成与合并）"""
    date_str = args.date or datetime.now().strftime("%Y-%m-%d")
    csv_path = os.path.join(get_path("doc_dir"), date_str, f"{date_str}_daily.csv")
    if not os.path.exists(csv_path):
        raise FileNotFoundError(f"当日报表不存在: {csv_path}，请先执行 analyze 生成")
    print(f"当日结论报表: {csv_path}")


def cmd_audit(args):
    """从数据库随机抽查 bugid 重新分析，与已入库字段对比生成人工审核表格"""
    report_path = audit_module.sample_and_audit(args.count)
    print(f"随机抽查完成，人工审核表格: {report_path}")


def cmd_cleanup(args):
    """按保留期清理运行期生成的数据（docs/reports/logs/缓存），默认只预演"""
    from src.core import retention
    summary = retention.prune_runtime_data(args.days, dry_run=not args.apply)
    mode = "已执行" if args.apply else "预演（未删除）"
    print(f"保留期清理[{mode}] 保留 {summary['days']} 天："
          f"{summary['file_count']} 个文件，约 {summary['bytes'] / 1024 / 1024:.1f} MB")
    for s in summary.get("sample", [])[:10]:
        print(f"  示例: {s}")
    if args.apply:
        print(f"  实际删除 {summary.get('removed', 0)} 个，失败 {summary.get('failed', 0)} 个")


def _listener_pids(port: int) -> list:
    """返回正在监听指定端口的进程 PID 列表（Windows 用 netstat，*nix 用 lsof）"""
    import subprocess
    import sys

    pids = set()
    if sys.platform == "win32":
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        try:
            out = subprocess.check_output(["netstat", "-ano", "-p", "TCP"],
                                          stderr=subprocess.DEVNULL,
                                          creationflags=flags).decode("utf-8", "ignore")
        except Exception as e:
            logger.warning("netstat 查询端口失败: %s", e)
            return []
        for line in out.splitlines():
            parts = line.split()
            # 形如：TCP  0.0.0.0:8060  0.0.0.0:0  LISTENING  8180
            if len(parts) >= 5 and parts[0].upper() == "TCP" \
                    and parts[1].endswith(f":{port}") and parts[3].upper().startswith("LISTEN"):
                if parts[4].isdigit():
                    pids.add(int(parts[4]))
        return sorted(pids)
    try:
        out = subprocess.check_output(["lsof", "-ti", f":{port}"],
                                      stderr=subprocess.DEVNULL).decode().strip()
        return sorted({int(p) for p in out.split() if p.isdigit()})
    except Exception:
        return []


def _kill_port_hog(port: int):
    """启动前自动杀掉占用指定端口的旧进程（Windows 用 taskkill，*nix 用 SIGKILL）"""
    import signal
    import socket
    import subprocess
    import sys
    import time

    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(1)
    result = s.connect_ex(('127.0.0.1', port))
    s.close()
    if result != 0:
        return  # 端口空闲，无需处理

    logger.info("端口 %d 被占用，正在清理旧进程...", port)
    pids = [pid for pid in _listener_pids(port) if pid != os.getpid()]
    if not pids:
        logger.warning("端口 %d 被占用，但未识别到监听进程", port)
        return
    for pid in pids:
        try:
            if sys.platform == "win32":
                # 用 /T 连子进程一起结束：uvicorn reload 模式下真正监听端口的是
                # reloader 派生的 worker 子进程，只杀父进程会留下“孤儿 worker”
                # 继续占用端口并运行旧代码，导致重启后请求时快时慢/改动不生效。
                res = subprocess.run(["taskkill", "/F", "/T", "/PID", str(pid)],
                                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                     creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                if res.returncode == 0:
                    logger.info("已杀掉占用端口的旧进程 PID=%d", pid)
                else:
                    logger.warning("结束进程 %d 失败（可能属于其它用户/会话），返回码 %s", pid, res.returncode)
            else:
                os.kill(pid, signal.SIGKILL)
                logger.info("已杀掉占用端口的旧进程 PID=%d", pid)
        except Exception as e:
            logger.warning("清理端口 %d 时结束进程 %d 失败: %s", port, pid, e)
    time.sleep(1)  # 等待端口释放


def cmd_web(args):
    """启动前端可视化页面服务（基于 uvicorn + FastAPI，支持代码热重载）"""
    import logging
    import os

    import uvicorn

    # 自动杀掉占用端口的旧进程
    _kill_port_hog(args.port)

    # 判断是否为打包后的 exe（打包后无源码，禁用 reload）
    is_frozen = getattr(sys, 'frozen', False)

    # 过滤 favicon 等无效请求的 access log
    class _FaviconFilter(logging.Filter):
        def filter(self, record):
            msg = record.getMessage()
            return "favicon.ico" not in msg

    logging.getLogger("uvicorn.access").addFilter(_FaviconFilter())

    # uvicorn 日志统一写入 logs/ 目录（不再依赖外部重定向）
    _log_dir = get_path("log_dir")
    _date_str = datetime.now().strftime("%Y-%m-%d")
    _fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s - %(message)s")

    _access_fh = logging.FileHandler(
        os.path.join(_log_dir, f"access_{_date_str}.log"), encoding="utf-8"
    )
    _access_fh.setFormatter(_fmt)
    _access_fh.addFilter(_FaviconFilter())
    logging.getLogger("uvicorn.access").addHandler(_access_fh)

    _error_fh = logging.FileHandler(
        os.path.join(_log_dir, f"uvicorn_{_date_str}.log"), encoding="utf-8"
    )
    _error_fh.setFormatter(_fmt)
    logging.getLogger("uvicorn.error").addHandler(_error_fh)
    logging.getLogger("uvicorn").addHandler(_error_fh)

    url = f"http://127.0.0.1:{args.port}"
    # 清除上次的浏览器打开标记，确保本次启动可以打开（含历史遗留位置）
    from src.config import PROJECT_ROOT as _PROJECT_ROOT
    import tempfile as _tempfile
    _flags = [
        os.path.join(_PROJECT_ROOT, "data", ".web_browser_opened"),
        os.path.join(_tempfile.gettempdir(), ".web_browser_opened"),
        os.path.join(os.getcwd(), ".web_browser_opened"),
    ]
    for _flag in _flags:
        try:
            os.remove(_flag)
        except FileNotFoundError:
            continue
        except OSError:
            continue
    # 通过环境变量传递 URL，由 app.py startup 事件在服务就绪后打开浏览器
    os.environ["_WEB_OPEN_URL"] = url
    if is_frozen:
        print(f"前端页面已启动: {url}（按 Ctrl+C 停止服务）")
        uvicorn.run("src.api.app:app", host="127.0.0.1", port=args.port,
                    log_level="info")
    else:
        print(f"前端页面已启动: {url}（代码修改自动重载，在终端按 Ctrl+C 停止服务）")
        uvicorn.run("src.api.app:app", host="127.0.0.1", port=args.port,
                    log_level="info", reload=True, reload_dirs=["src"])


def build_parser() -> argparse.ArgumentParser:
    """构建命令行参数解析器"""
    parser = argparse.ArgumentParser(prog="bug-doc-tool", description="AI应用测评平台")
    sub = parser.add_subparsers(dest="command", required=False)

    p_analyze = sub.add_parser("analyze", help="分析 bugid 列表（去重、AI 分析、比对、出报表）")
    p_analyze.add_argument("bugids", nargs="+", help="Jira bugid 列表")
    p_analyze.add_argument("--trigger-time", action="append",
                           help="触发时间，格式 bugid=时间，可多次指定")
    p_analyze.set_defaults(func=cmd_analyze)

    p_retry = sub.add_parser("retry", help="重新分析指定 bugid（失败重试）")
    p_retry.add_argument("bugid", help="Jira bugid")
    p_retry.set_defaults(func=cmd_retry)

    p_store = sub.add_parser("store", help="手工将指定 bugid 的分析文档推入知识库")
    p_store.add_argument("bugid", help="Jira bugid")
    p_store.set_defaults(func=cmd_store)

    p_report = sub.add_parser("report", help="查看当日结论报表路径")
    p_report.add_argument("--date", help="日期，格式 YYYY-MM-DD，默认当天")
    p_report.set_defaults(func=cmd_report)

    p_audit = sub.add_parser("audit", help="随机抽查已入库 bugid 重新分析并生成人工审核表格")
    p_audit.add_argument("--count", type=int, default=None,
                         help="抽样数量，默认取配置 audit.sample_count（30）")
    p_audit.set_defaults(func=cmd_audit)

    p_cleanup = sub.add_parser("cleanup", help="按保留期清理运行期生成的数据（默认只预演）")
    p_cleanup.add_argument("--days", type=int, default=180, help="保留天数，默认 180")
    p_cleanup.add_argument("--apply", action="store_true", help="实际删除（不加则只预演统计）")
    p_cleanup.set_defaults(func=cmd_cleanup)

    p_web = sub.add_parser("web", help="启动前端可视化页面（流程可视化/接口设置/数据看板）")
    p_web.add_argument("--port", type=int, default=8060, help="服务端口，默认 8060")
    p_web.set_defaults(func=cmd_web)
    return parser


def main():
    """入口函数：初始化数据库并分发子命令"""
    # Windows 控制台默认 GBK 编码，切换 UTF-8 避免中文输出乱码
    if sys.platform == "win32":
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    parser = build_parser()
    args = parser.parse_args()
    # 双击 exe 无参数时默认启动 web 服务
    if not args.command:
        args = parser.parse_args(["web"])
    db.init_db()
    try:
        args.func(args)
    except Exception as e:
        logger.error("命令执行失败: %s", e)
        print(f"执行失败: {e}", file=sys.stderr)
        # 双击运行时防止窗口闪退，等待用户按键
        if getattr(sys, 'frozen', False):
            input("\n按回车键退出...")
        sys.exit(1)


if __name__ == "__main__":
    main()
