"""Trigger time service layer - 触发时间管理业务逻辑

提取自 routes/trigger.py 的复杂业务逻辑，
包含云端缓存扫描、批量提取进度管理、排除逻辑等。
"""
import asyncio
import json
import os
from datetime import datetime
from typing import Optional

from src.config import PROJECT_ROOT, load_config, setup_logger
from src.clients import feishu_client, jira_client

logger = setup_logger("service.trigger")


# ── 飞书多维表格辅助 ──


def _bitable_text(val) -> str:
    """提取飞书多维表格文本字段的纯文本值"""
    if isinstance(val, list):
        return "".join(seg.get("text", "") for seg in val if isinstance(seg, dict))
    if isinstance(val, dict):
        return val.get("text", "")
    return str(val) if val else ""


# ── 云端缓存批量扫描 ──


def scan_candidates(
    all_records: list,
    exclude_bitable_success: bool = False,
    exclude_corrected: bool = False,
) -> dict:
    """扫描云端触发时间记录，筛选待重新提取的候选项

    Args:
        all_records: 云端全部触发时间记录
        exclude_bitable_success: 排除多维表格中分析结果为"成功"的记录
        exclude_corrected: 排除诊断缓存中已修正的记录

    Returns:
        {"candidates": [...], "total_cloud": int, "total_cached": int,
         "bitable_success_count": int, "corrected_count": int, "message": str}
    """
    total_cloud = len(all_records)
    cached_records = [r for r in all_records if r["trigger_time"]]
    total_cached = len(cached_records)

    jira_map = {}
    for r in cached_records:
        jira_map[r["jira_no"]] = r

    bitable_success_keys, corrected_keys = set(), set()

    # 排除多维表格中分析已成功的
    if exclude_bitable_success:
        try:
            cfg = load_config().get("feishu_bitable", {})
            records = feishu_client.list_bitable_records(
                cfg.get("app_token", ""), cfg.get("table_id", ""))
            bf = cfg.get("bugid_field", "jira号")
            for rec in records:
                fields = rec.get("fields", {})
                jk = _bitable_text(fields.get(bf, ""))
                result_status = str(fields.get("分析结果", "")).strip()
                if jk and result_status == "成功":
                    bitable_success_keys.add(jk)
        except Exception as e:
            logger.warning("云端缓存批量扫描: 多维表格查询失败: %s", e)

    # 回溯标记：从多维表格人工审核结果中识别已修正的
    applied_tagged = 0
    time_corrected_jiras = set()
    try:
        cfg = load_config().get("feishu_bitable", {})
        if cfg.get("app_token") and cfg.get("table_id"):
            bt_records = feishu_client.list_bitable_records(cfg["app_token"], cfg["table_id"])
            bf = cfg.get("bugid_field", "jira号")
            for rec in bt_records:
                fields = rec.get("fields", {})
                review = _bitable_text(fields.get("人工审核结果", ""))
                if "时间添加为" in review or "时间异常" in review:
                    jk = _bitable_text(fields.get(bf, ""))
                    if jk:
                        time_corrected_jiras.add(jk)
    except Exception as e:
        logger.warning("回溯标记: 多维表格查询失败: %s", e)

    # 扫描诊断缓存，回溯标记已修正的
    cache_dir = os.path.join(PROJECT_ROOT, "data", "troubleshoot")
    if os.path.isdir(cache_dir):
        for fname in os.listdir(cache_dir):
            if not fname.endswith(".json"):
                continue
            try:
                fpath = os.path.join(cache_dir, fname)
                with open(fpath, "r", encoding="utf-8") as f:
                    cached = json.load(f)
                vs = cached.get("verify_status", "")
                if vs in ("corrected", "success"):
                    continue
                bugid = cached.get("bugid", fname[:-5])
                should_tag = False
                st = cached.get("suggested_time", "")
                if st and bugid in jira_map and jira_map[bugid]["trigger_time"] == st:
                    should_tag = True
                if not should_tag and bugid in time_corrected_jiras:
                    should_tag = True
                if should_tag:
                    cached["verify_status"] = "corrected"
                    with open(fpath, "w", encoding="utf-8") as f:
                        json.dump(cached, f, ensure_ascii=False, indent=2)
                    corrected_keys.add(bugid)
                    applied_tagged += 1
            except Exception:
                pass

    # 排除已修正的诊断缓存
    if exclude_corrected:
        if os.path.isdir(cache_dir):
            for fname in os.listdir(cache_dir):
                if not fname.endswith(".json"):
                    continue
                try:
                    fpath = os.path.join(cache_dir, fname)
                    with open(fpath, "r", encoding="utf-8") as f:
                        cached = json.load(f)
                    vs = cached.get("verify_status", "")
                    if vs in ("corrected", "success"):
                        corrected_keys.add(cached.get("bugid", fname[:-5]))
                except Exception:
                    pass

    exclude_all = bitable_success_keys | corrected_keys
    candidates = []
    for jira_no, rec in jira_map.items():
        if jira_no not in exclude_all:
            candidates.append({
                "bugid": jira_no, "current_time": rec["trigger_time"],
                "table_id": rec["table_id"], "record_id": rec["record_id"],
            })

    msg_parts = [f"云端有缓存: {total_cached}"]
    if exclude_bitable_success:
        msg_parts.append(f"多维表格已成功排除: {len(bitable_success_keys)}")
    if exclude_corrected:
        msg_parts.append(f"已修正排除: {len(corrected_keys)}" + (f"（含回溯标记 {applied_tagged}）" if applied_tagged else ""))
    msg_parts.append(f"待重新提取: {len(candidates)}")

    return {
        "candidates": candidates,
        "total_cloud": total_cloud,
        "total_cached": total_cached,
        "bitable_success_count": len(bitable_success_keys),
        "corrected_count": len(corrected_keys),
        "message": "、".join(msg_parts),
    }


# ── 批量提取 SSE 事件生成 ──


async def generate_extract_events(
    bugids: list,
    old_times: dict,
    video_first: bool,
    stop_event,
    progress_loader,
    progress_saver,
    video_extractor,
    cloud_saver,
    video_suffixes,
    request,
):
    """生成批量提取的 SSE 事件流

    这是一个 async generator，产出 SSE 格式的事件字符串。
    所有 server.py 依赖通过参数注入，避免服务层直接导入 server.py。
    """
    loop = asyncio.get_event_loop()
    stop_event.clear()
    local_progress = progress_loader()
    new_items = 0
    for bugid in bugids:
        if bugid not in local_progress:
            local_progress[bugid] = {"time": "", "source": "", "status": "pending"}
            new_items += 1
        elif local_progress[bugid].get("status") == "pending":
            new_items += 1
    if new_items:
        progress_saver(local_progress)

    completed_count = sum(1 for b in bugids if b in local_progress and local_progress[b].get("status") != "pending")
    total = len(bugids)
    yield f"data: {json.dumps({'type': 'start', 'total': total, 'cached': completed_count, 'pending': new_items}, ensure_ascii=False)}\n\n"

    done_count = updated = unchanged = empty = error_count = 0
    results, interrupted = [], False

    for i, bugid in enumerate(bugids):
        if stop_event.is_set():
            interrupted = True
            break
        if await request.is_disconnected():
            interrupted = True
            break
        await asyncio.sleep(0)

        # 跳过已完成的
        if bugid in local_progress and local_progress[bugid].get("status") != "pending":
            cached = local_progress[bugid]
            status = cached.get("status", "success")
            tt_val = cached.get("time", "")
            source = cached.get("source", "本地缓存")
            if status in ("success", "unchanged"):
                unchanged += 1
            elif status == "empty":
                empty += 1
            elif status == "error":
                error_count += 1
            done_count += 1
            results.append({"bugid": bugid, "trigger_time": tt_val, "source": source, "status": status})
            yield f"data: {json.dumps({'type': 'progress', 'index': done_count, 'total': total, 'key': bugid, 'status': status, 'time': tt_val, 'source': '本地缓存'}, ensure_ascii=False)}\n\n"
            continue

        status, tt_val, source = "success", "", ""
        try:
            issue = await asyncio.wait_for(
                loop.run_in_executor(None, jira_client.fetch_issue, bugid), timeout=30)
            fields = issue.get("fields") or {}
            attachments = fields.get("attachment") or []
            has_video = any((a.get("filename", "") or "").lower().endswith(video_suffixes) for a in attachments)

            tt, src = "", ""
            if video_first and has_video:
                tt = await loop.run_in_executor(None, video_extractor, issue)
                src = "视频+gmlogger"
            if not tt:
                tt = jira_client.extract_trigger_time_from_issue(issue)
                src = "标准提取"
            if not tt and not video_first and has_video:
                tt = await loop.run_in_executor(None, video_extractor, issue)
                src = "视频兜底"

            if tt:
                old = old_times.get(bugid, "")
                is_same = (tt == old)
                if not is_same and old:
                    try:
                        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
                            try:
                                t_new = datetime.strptime(tt, fmt)
                                break
                            except ValueError:
                                continue
                        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
                            try:
                                t_old = datetime.strptime(old, fmt)
                                break
                            except ValueError:
                                continue
                        if t_new and t_old and abs((t_new - t_old).total_seconds()) <= 60:
                            is_same = True
                    except Exception:
                        pass
                if is_same:
                    status = "unchanged"
                    unchanged += 1
                    tt_val = old or tt
                else:
                    await loop.run_in_executor(None, cloud_saver, bugid, tt)
                    updated += 1
                    tt_val = tt
            else:
                status = "empty"
                empty += 1
        except (asyncio.TimeoutError,):
            status = "error"
            error_count += 1
        except Exception as e:
            status = "error"
            error_count += 1
            logger.warning("缓存批量提取失败 %s: %s", bugid, e)

        done_count += 1
        results.append({"bugid": bugid, "trigger_time": tt_val, "source": source, "status": status})
        local_progress[bugid] = {"time": tt_val, "source": source, "status": status}
        progress_saver(local_progress)
        yield f"data: {json.dumps({'type': 'progress', 'index': done_count, 'total': total, 'key': bugid, 'status': status, 'time': tt_val, 'source': source}, ensure_ascii=False)}\n\n"

    yield f"data: {json.dumps({'type': 'done', 'total': total, 'updated': updated, 'unchanged': unchanged, 'empty': empty, 'error': error_count, 'interrupted': interrupted, 'results': results}, ensure_ascii=False)}\n\n"
