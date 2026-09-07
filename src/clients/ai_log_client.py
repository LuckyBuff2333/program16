"""AI 日志分析工具接口客户端：支持 mock 模式与真实接口切换

mock 模式下直接从本地测试数据表（bug_test_data.csv）读取根因与评论，
并优先读取已生成的分析报告文件，确保 mock 数据与真实数据同源。
"""
import csv
import os
import time
from datetime import datetime
from typing import Optional

from src.clients.base import http_post, cancellable_sleep
from src.config import PROJECT_ROOT, get_path, load_config, setup_logger

logger = setup_logger("ai_log")

# 本地测试数据表
TESTDATA_CSV = os.path.join(PROJECT_ROOT, "testdata", "bug_test_data.csv")


def _load_testdata_row(bugid: str):
    """在测试数据表中查找指定 bugid 的行，未命中返回 None

    匹配优先级：精确匹配 → 后缀模糊匹配（如 5001 匹配 BUG-5001）
    """
    if not os.path.exists(TESTDATA_CSV):
        return None
    with open(TESTDATA_CSV, encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    # 精确匹配
    for row in rows:
        if row.get("bugid") == bugid:
            return row
    # 后缀模糊匹配：输入 5001 可匹配 BUG-5001
    for row in rows:
        csv_bugid = row.get("bugid", "")
        if csv_bugid.endswith(bugid):
            return row
    return None


def _extract_valid_logs(log_path: str) -> list:
    """从日志文件中提取 WARN/ERROR 有效日志行（其余为无效噪音日志）"""
    if not os.path.exists(log_path):
        return []
    valid = []
    with open(log_path, encoding="utf-8") as f:
        for line in f:
            if "[ERROR]" in line or "[WARN]" in line:
                valid.append(line.strip())
    return valid


def _load_generated_report(bugid: str) -> str:
    """读取已生成的分析报告文件（docs/YYYY-MM-DD/bugid.md），未找到返回 None"""
    date_str = datetime.now().strftime("%Y-%m-%d")
    doc_path = os.path.join(get_path("doc_dir"), date_str, f"{bugid}.md")
    if os.path.exists(doc_path):
        with open(doc_path, encoding="utf-8") as f:
            return f.read()
    return None


# 每个 bug 的详细分析步骤：根据日志内容定制，与评论中的分析步骤呼应
MOCK_DOC_STEPS = {
    "BUG-5001": [
        "查看服务错误日志，发现大量数据库连接超时错误，连接池活跃连接数达到上限",
        "分析连接池监控指标，确认 HikariPool 活跃连接 50/50，idle=0，连接池已耗尽",
        "定位到慢查询 SELECT * FROM t_order_detail 执行耗时 28.4s，长期占用连接未释放",
        "修复慢SQL并扩大连接池配置，服务恢复正常",
    ],
    "BUG-5002": [
        "排查订单服务内存使用情况，发现 JVM 老年代使用率从 82% 持续增长至 91%",
        "分析GC日志，确认 Full GC 耗时 6.2s 且回收率不足 5%，堆内存持续增长不回收",
        "定位到 OrderExportCache 持有 240 万条记录未释放，确认为内存泄漏点",
        "修复未关闭的数据库会话并清理缓存，服务重启后内存恢复正常",
    ],
    "BUG-5003": [
        "检查Redis集群状态，发现 redis-node-2 节点网络抖动导致心跳丢失，集群标记节点 FAIL",
        "分析缓存命中率，确认节点宕机引发缓存雪崩，热点 key 集中失效",
        "确认大量缓存请求穿透到数据库，数据库 QPS 从 800 激增至 9200，CPU 使用率 99%",
        "重启 Redis 节点并补充缓存降级策略，数据库压力恢复正常",
    ],
    "BUG-5004": [
        "检查API网关错误日志，发现 SSL 证书校验失败 certificate has expired",
        "查看证书有效期，确认 api.example.com 证书已于 2026-08-12 00:00 过期",
        "确认 HTTPS 请求批量握手失败，javax.net.ssl.SSLHandshakeException，全站 API 调用失败率 98%",
        "更新 SSL 证书并重启网关，TLS 握手恢复正常，请求恢复",
    ],
    "BUG-5005": [
        "查看数据库慢查询日志，发现全表扫描操作：SELECT * FROM t_trade_record 执行耗时 56s",
        "分析业务线程状态，确认等待 t_trade_record 行锁的线程达 210 个，线程池使用率 100%",
        "定位到订单查询SQL缺少索引导致全表扫描锁表，业务线程阻塞堆积",
        "添加索引 idx_create_time 并优化SQL，kill 慢SQL会话后服务恢复正常",
    ],
}


def _build_testdata_report(row: dict) -> str:
    """基于测试数据行构造分析报告：根因取自表格，分析依据取自日志有效行"""
    log_path = os.path.join(PROJECT_ROOT, "testdata", row.get("日志文件", ""))
    valid_logs = _extract_valid_logs(log_path)
    bugid = row["bugid"]
    lines = [
        f"# Bug {bugid} 日志分析报告",
        "",
        "## 根因结论",
        row["根因分析"],
        "",
        "## 问题触发时间",
        row["问题触发时间"],
        "",
        "## 关键日志依据",
    ]
    for log_line in valid_logs:
        lines.append(f"- {log_line}")
    lines += ["", "## 分析步骤"]
    # 优先使用详细步骤表，未命中时用通用步骤
    steps = MOCK_DOC_STEPS.get(bugid, [
        "按触发时间检索日志，发现告警前兆（WARN 日志）",
        "定位触发时间点附近的 ERROR 日志，确认故障爆发范围",
        f"结合异常堆栈与监控指标，确认根因：{row['根因分析']}",
    ])
    for idx, step in enumerate(steps, 1):
        lines.append(f"{idx}. {step}")
    return "\n".join(lines)


def _build_mock_report(bugid: str) -> str:
    """构造 mock 分析报告：优先读取已生成的报告文件，再从测试数据表构建

    优先读报告文件：当存在手工修改/生成的报告文件时，直接使用文件内容，
    便于模拟 AI 分析报告与 bug 单不一致的场景（如分析错误）。
    表格作为兜底：无报告文件时从测试数据表构建。
    """
    # 优先读取已生成的报告文件（支持手工修改/错误报告模拟）
    generated = _load_generated_report(bugid)
    if generated:
        logger.info("[mock] bugid=%s 读取已生成的分析报告", bugid)
        return generated
    # 从测试数据表构建报告
    testdata_row = _load_testdata_row(bugid)
    if testdata_row is not None:
        logger.info("[mock] bugid=%s 从测试数据表构建报告", bugid)
        return _build_testdata_report(testdata_row)
    # 完全无数据，返回空报告
    logger.warning("[mock] bugid=%s 无报告文件且不在测试数据表中，返回空报告", bugid)
    return f"# Bug {bugid} 日志分析报告\n\n## 根因结论\n\n## 分析步骤\n"


def _is_async_pending(response: dict) -> bool:
    """判断响应是否为异步任务启动响应（未包含实际报告内容）

    异步接口典型响应: {"code": 200, "msg": "分析任务已启动...正在后台处理中", "data": {"issue_key": "xxx"}}
    """
    if not isinstance(response, dict):
        return False
    msg = str(response.get("msg", ""))
    # 检查是否包含异步提示关键词
    async_keywords = ["后台处理", "已启动", "正在分析", "正在处理", "processing", "pending"]
    if any(kw in msg for kw in async_keywords):
        return True
    # 无 report/content/result 字段且 data 中也没有报告内容
    data = response.get("data")
    if isinstance(data, dict):
        if data.get("report") or data.get("content") or data.get("result"):
            return False
    return False


def analyze_logs(bugid: str, trigger_time: str = None, cancel_check=None, progress_callback=None) -> dict:
    """调用 AI 日志分析工具接口，支持异步接口自动轮询

    异步接口返回 HTTP 200 后，第1分钟先查一次多维表格，
    然后第6-10分钟每分钟查一次，总超时10分钟。
    :param bugid: Jira bugid
    :param trigger_time: 可选的触发时间，随入参传给分析工具
    :param cancel_check: 可选回调函数，返回 True 表示需要取消
    :param progress_callback: 可选回调，异步任务提交成功时调用，传入 (msg: str)
    :return: {"report": 分析报告文本} 或含 data.report 的完整响应
    """
    cfg = load_config()["ai_log_api"]
    if cfg.get("mock", False):
        logger.info("[mock] AI 日志分析: bugid=%s, trigger_time=%s", bugid, trigger_time)
        return {"code": 0, "data": {"report": _build_mock_report(bugid)}}
    # 真实接口：入参字段名按配置映射
    payload = {cfg["bugid_field"]: bugid}
    if trigger_time and cfg.get("trigger_time_field"):
        payload[cfg["trigger_time_field"]] = trigger_time
    timeout = int(cfg.get("timeout", 60))
    # 记录接口触发时间，用于多维表格记录匹配
    api_trigger_time = datetime.now()
    logger.info("调用 AI 日志分析接口: bugid=%s, trigger=%s", bugid, api_trigger_time.strftime("%H:%M:%S"))
    response = http_post(cfg["url"], payload, timeout=timeout)
    # 异步接口：第1分钟先查，然后第6-10分钟每分钟查一次
    if _is_async_pending(response):
        if progress_callback:
            progress_callback(response.get("msg", "分析任务已启动"))
        logger.info("AI 分析接口返回异步响应，开始多维表格轮询（1/6/7/8/9/10分钟）")
        bitable_result = _poll_feishu_bitable(bugid, api_trigger_time=api_trigger_time,
                                              cancel_check=cancel_check)
        if bitable_result:
            return bitable_result
        logger.warning("多维表格查询未获取到分析结果，AI日志分析失败")
        return {"code": -1, "msg": "AI日志分析超时（10分钟），多维表格未更新"}
    return response


def _poll_feishu_im(bugid: str, after_time: str, cancel_check=None) -> dict:
    """监听飞书消息，等待「分析完成通知」并下载报告内容

    通过飞书长连接事件订阅接收消息，无需 IM API 权限。
    匹配策略：优先 bugid 直匹配，回退按时间顺序下载报告验证 Jira 号。
    轮询策略：第 6 分钟检查一次，之后每分钟检查一次，总超时 10 分钟
    :param bugid: Jira bugid
    :param after_time: API 调用时的 Unix 时间戳（秒）
    :param cancel_check: 可选回调函数，返回 True 表示需要取消
    :return: {"report": str, "report_link": str, "source": "feishu_im"} 成功时返回，失败返回 None
    """
    try:
        from src.clients import feishu_client
        initial_delay = 6 * 60
        logger.info("AI 分析已提交，等待 %d 秒后检查飞书事件推送", initial_delay)
        # 第 6 分钟：一次性等待
        if cancellable_sleep(initial_delay, cancel_check):
            logger.info("等待期间收到取消信号")
            return None
        # 第 6-10 分钟：每分钟检查一次，共 5 次
        max_checks = 5
        for check_num in range(1, max_checks + 1):
            if cancel_check and cancel_check():
                logger.info("飞书轮询收到取消信号")
                return None
            # 策略一：bugid 直匹配（URL 含 bugid 的快速路径）
            event = feishu_client.get_feishu_event(bugid)
            if event and event.get("link"):
                logger.info("事件直匹配命中: bugid=%s, link=%s", bugid, event["link"][:60])
                feishu_client.clear_feishu_event(bugid)
                return _download_report_from_link(bugid, event["link"])
            # 策略二：按时间顺序取执行时间之后的最近卡片，下载报告验证 Jira 号
            time_event = feishu_client.get_feishu_event_after_time(after_time)
            if time_event and time_event.get("link"):
                logger.info("时间匹配命中: title=%s, link=%s", time_event.get("title", "")[:30], time_event["link"][:60])
                result = _download_report_from_link(bugid, time_event["link"])
                report_content = (result.get("data") or {}).get("report", "")
                if bugid in report_content:
                    logger.info("报告内容验证通过: bugid=%s", bugid)
                    feishu_client.remove_feishu_card_event(time_event["link"])
                    return result
                logger.info("报告内容不含 %s，继续等待下一个事件", bugid)
                feishu_client.remove_feishu_card_event(time_event["link"])
            logger.info("第 %d/%d 次检查飞书事件推送（已等待 %d 分钟）", check_num, max_checks, 6 + check_num - 1)
            if check_num < max_checks:
                if cancellable_sleep(60, cancel_check):
                    logger.info("轮询期间收到取消信号")
                    return None
        logger.warning("飞书事件推送超时（10 分钟），未收到 bugid=%s 的分析完成通知", bugid)
        return None
    except Exception as e:
        logger.warning("飞书事件轮询异常: %s", e)
        return None


def _download_report_from_link(bugid: str, report_link: str) -> dict:
    """从飞书报告链接下载文档内容"""
    from src.clients import feishu_client
    doc_id = feishu_client.extract_doc_id_from_url(report_link)
    feishu_domain = feishu_client.extract_domain_from_url(report_link)
    if not doc_id:
        logger.warning("无法从链接提取文档 ID: %s", report_link)
        return {"code": 0, "data": {"report": report_link},
                "report_link": report_link, "source": "feishu_im"}
    md_content = feishu_client.fetch_docx_as_markdown(
        doc_id, bugid=bugid, feishu_domain=feishu_domain
    )
    return {"code": 0, "data": {"report": md_content},
            "report_link": report_link, "source": "feishu_im"}


def _extract_field_text(value) -> str:
    """从飞书字段值中提取纯文本，兼容字符串/列表/字典格式"""
    if not value:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, list):
        return "".join(
            item.get("text", str(item)) if isinstance(item, dict) else str(item)
            for item in value
        ).strip()
    if isinstance(value, dict):
        return (value.get("text") or value.get("value") or str(value)).strip()
    return str(value).strip()


def _pick_best_record(records: list, api_trigger_time: datetime) -> Optional[dict]:
    """从多条匹配记录中选取分析完成时间最接近 API 触发时间的记录

    :param records: bugid 匹配的所有记录
    :param api_trigger_time: AI 分析接口触发时间
    :return: 最佳匹配记录，无有效记录返回 None
    """
    if not records:
        return None
    if len(records) == 1:
        return records[0]
    # 多条记录：按分析完成时间与触发时间的差值排序，取最近
    best = None
    best_diff = float("inf")
    for rec in records:
        fields = rec.get("fields", {})
        finish_str = _extract_field_text(fields.get("分析完成时间"))
        if not finish_str:
            continue
        try:
            finish_dt = datetime.strptime(finish_str, "%Y-%m-%d %H:%M:%S")
            diff = abs((finish_dt - api_trigger_time).total_seconds())
            if diff < best_diff:
                best_diff = diff
                best = rec
        except ValueError:
            continue
    if best is None:
        best = records[0]  # 全部无完成时间，取第一条
    logger.info("选取最接近触发时间的记录: 共 %d 条, 时间差 %.0fs", len(records), best_diff)
    return best


def _poll_feishu_bitable(bugid: str, api_trigger_time: datetime = None,
                         cancel_check=None) -> dict:
    """监听飞书多维表格更新，查找对应 bugid 的分析结果

    轮询策略：第1分钟首查（快速发现失败），然后第6/7/8/9/10分钟各查一次。
    匹配逻辑：同一 bugid 多条记录时，选取分析完成时间最接近 API 触发时间的记录。
    失败即停：分析结果=失败时直接返回错误，停止后续链路。
    :param api_trigger_time: AI 分析接口调用时间，用于匹配最新记录
    :param cancel_check: 可选回调函数，返回 True 表示需要取消
    :return: 成功 {"code":0, "data":{...}}，失败 {"code":-1, "msg":str}，未找到 None
    """
    try:
        from src.clients import feishu_client
        bitable_cfg = load_config().get("feishu_bitable", {})
        has_token = bitable_cfg.get("app_id") and bitable_cfg.get("app_secret")
        has_cookie = bitable_cfg.get("cookie")
        if not has_token and not has_cookie:
            logger.info("飞书 Bitable 未配置认证信息，跳过表格查询")
            return None
        if api_trigger_time is None:
            api_trigger_time = datetime.now()
        # 轮询时间点：第1分钟 + 第6-10分钟
        check_schedule = [60, 300, 360, 420, 480, 540]  # 秒
        waited = 0
        for check_num, target_wait in enumerate(check_schedule, 1):
            sleep_secs = target_wait - waited
            if sleep_secs > 0:
                logger.info("等待 %d 秒后第 %d 次查询多维表格: bugid=%s", sleep_secs, check_num, bugid)
                if cancellable_sleep(sleep_secs, cancel_check):
                    logger.info("多维表格监听收到取消信号")
                    return None
            waited = target_wait
            if cancel_check and cancel_check():
                logger.info("多维表格监听收到取消信号")
                return None
            try:
                # 获取所有匹配记录，选取最接近触发时间的
                records = feishu_client.find_records_by_bugid(bugid)
                record = _pick_best_record(records, api_trigger_time)
                if record:
                    fields = record.get("fields", {})
                    result_status = _extract_field_text(fields.get("分析结果"))
                    error_msg = _extract_field_text(fields.get("错误信息"))
                    finish_time = _extract_field_text(fields.get("分析完成时间"))
                    duration = _extract_field_text(fields.get("分析耗时"))
                    source = _extract_field_text(fields.get("触发来源"))
                    # 分析结果为失败：立即停止，返回错误信息
                    if result_status == "失败":
                        logger.warning("多维表格命中失败记录: bugid=%s, 错误=%s, 耗时=%s",
                                       bugid, error_msg, duration)
                        return {"code": -1, "msg": f"AI分析失败: {error_msg}",
                                "data": {"分析结果": "失败", "错误信息": error_msg,
                                          "分析耗时": duration, "分析完成时间": finish_time,
                                          "触发来源": source},
                                "source": "feishu_bitable"}
                    # 分析结果为成功或无状态：提取报告
                    try:
                        report = feishu_client.extract_report_from_bitable(fields)
                    except Exception:
                        report = ""
                    logger.info("多维表格命中: bugid=%s, 第 %d 次查询(第 %d 分钟), 结果=%s, 报告长度=%d",
                                bugid, check_num, target_wait // 60,
                                result_status or "未标记", len(report or ""))
                    return {"code": 0,
                            "data": {"report": report, "分析结果": result_status or "成功",
                                      "分析耗时": duration, "分析完成时间": finish_time,
                                      "触发来源": source, "错误信息": error_msg},
                            "source": "feishu_bitable"}
            except Exception as e:
                logger.warning("多维表格查询失败: %s", e)
            logger.info("第 %d/%d 次查询多维表格（已等待 %d 分钟），未找到匹配记录",
                        check_num, len(check_schedule), target_wait // 60)
        logger.warning("多维表格监听超时（10 分钟），bugid=%s 未找到匹配的 Jira 号", bugid)
    except Exception as e:
        logger.warning("多维表格监听异常: %s", e)
    return None


def _poll_api_endpoint(cfg: dict, payload: dict, bugid: str, timeout: int, cancel_check=None) -> dict:
    """回退轮询：定期重新调用 AI 分析接口等待结果"""
    poll_interval = int(cfg.get("poll_interval", 15))
    waited = 0
    logger.info("开始轮询 AI 分析接口（间隔 %ds，最大 %ds）", poll_interval, timeout)
    response = None
    while waited < timeout:
        if cancel_check and cancel_check():
            logger.info("AI 分析接口轮询收到取消信号")
            return response
        if cancellable_sleep(poll_interval, cancel_check):
            logger.info("AI 分析接口轮询收到取消信号（sleep期间）")
            return response
        waited += poll_interval
        logger.info("轮询 AI 分析结果: bugid=%s, 已等待 %ds", bugid, waited)
        try:
            response = http_post(cfg["url"], payload, timeout=timeout)
        except Exception as e:
            logger.warning("轮询请求失败: %s", e)
            continue
        if not _is_async_pending(response):
            logger.info("AI 分析完成，总等待 %ds", waited)
            return response
    logger.warning("AI 分析轮询超时（%ds），返回最后一次响应", timeout)
    return response


def extract_report(response: dict) -> str:
    """从接口返回值中提取报告内容，兼容多种常见格式"""
    # 检查是否为明确失败响应
    if isinstance(response, dict) and response.get("code") == -1:
        msg = response.get("msg", "AI 分析失败")
        raise ValueError(msg)
    # 尝试多种常见响应结构
    report = None
    if isinstance(response, dict):
        # 格式1: {"data": {"report": "..."}}  
        data = response.get("data")
        if isinstance(data, dict):
            report = data.get("report") or data.get("content") or data.get("result")
        elif isinstance(data, str):
            report = data
        # 格式2: {"report": "..."} 或 {"content": "..."} 或 {"result": "..."}
        if not report:
            report = response.get("report") or response.get("content") or response.get("result")
    if not report:
        raise ValueError(f"AI 分析接口返回值中未找到报告内容，响应结构: {str(response)[:500]}")
    return report
