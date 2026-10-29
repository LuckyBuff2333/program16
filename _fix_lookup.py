with open('d:/program16/src/api/routes/testing.py', 'r', encoding='utf-8') as f:
    lines = f.readlines()

# Find the lookup while pending: loop and replace it
# The loop starts around line 5528 and ends around line 5649
# We need to find exact boundaries

start_idx = None
end_idx = None
for i, line in enumerate(lines):
    if 'while pending:' in line and i > 5500:
        start_idx = i
        print(f"Found while pending at line {i+1}")
    if start_idx is not None and end_idx is None:
        if 'yield f"data: {_json.dumps' in line and 'batch_done' in line:
            # This is the batch_done yield, which is the last line of the while loop body
            end_idx = i
            print(f"Found end at line {i+1}")
            break

if start_idx is None or end_idx is None:
    print("ERROR: Could not find boundaries")
    exit(1)

print(f"Replacing lines {start_idx+1} to {end_idx+1}")

# Build the new dynamic pool code
new_code = '''        # 动态并发池：始终保持 batch_size 个任务在跑，一个完成立即补位
        batch_results = []
        with concurrent.futures.ThreadPoolExecutor(max_workers=batch_size) as pool:
            futures = {}
            next_idx = 0
            # 初始提交 batch_size 个
            for _ in range(min(batch_size, len(effective_bugids))):
                bugid = effective_bugids[next_idx]
                f = pool.submit(_run_one_adp, bugid)
                futures[f] = {"bugid": bugid}
                next_idx += 1
            
            batch_deadline = _time.time() + adp_cfg["timeout"] + 120
            while futures:
                if _stop_event.is_set():
                    for f in futures:
                        f.cancel()
                    pool.shutdown(wait=False, cancel_futures=True)
                    break
                # 检查超时的 future
                if _time.time() > batch_deadline:
                    for f in list(futures):
                        f.cancel()
                        bugid = futures.pop(f)["bugid"]
                        rec = bt_map.get(bugid)
                        item = {
                            "jira_key": bugid, "ok": False, "has_html": False,
                            "skipped": False,
                            "results": {"完成状态": "分析失败"}, "error": "ADP 分析超时",
                            "bt_found": rec is not None,
                            "desc_source": "bitable" if rec else "none",
                            "time_source": "bitable" if rec else "none",
                            "text_len": 0, "text_preview": "", "report_path": "",
                            "fail_type": "ADP 分析超时", "file_urls": [],
                        }
                        batch_results.append(item)
                        yield f"data: {_json.dumps({'type': 'item_done', **item}, ensure_ascii=False)}\\n\\n"
                    break
                # 收集已完成的 future
                done_now = [f for f in futures if f.done()]
                for future in done_now:
                    bugid = futures.pop(future)["bugid"]
                    try:
                        r = future.result()
                    except Exception as e:
                        r = {"bugid": bugid, "result": {"ok": False, "jira_key": bugid, "error": str(e)[:100]},
                             "has_html": False, "info": {"bugid": bugid, "desc": "", "tt": "", "rec": bt_map.get(bugid),
                                                         "bt_desc": "", "bt_time": ""}}
                    info = r.get("info") or {"bugid": bugid, "desc": "", "tt": "", "rec": bt_map.get(bugid),
                                             "bt_desc": "", "bt_time": ""}
                    result = r.get("result", {})
                    has_html = r.get("has_html", False)

                    # 判断是否为"无法分析"（无有效日志附件）→ 不算失败，跳过
                    results_dict = result.get("results") or {}
                    is_skipped = results_dict.get("完成状态") == "无法分析"

                    # 失败（没拿到html且非跳过）：设"分析失败"+ 自动归因并保存本地MD
                    if not has_html and not is_skipped:
                        results_dict["完成状态"] = "分析失败"
                        # 自动归因：分析ADP返回内容判定失败类型
                        if not results_dict.get("分析失败归因"):
                            results_dict["分析失败归因"] = classify_adp_failure(
                                error=result.get("error", ""),
                                full_text=result.get("full_text", ""),
                                attachment_count=result.get("attachment_count", 0))
                        # 失败快照落到本地，并把路径带回前端，失败行也能点「查看完整报告」
                        fail_md = _save_fail_md(bugid, result)
                        if fail_md and not result.get("report_path"):
                            result["report_path"] = fail_md

                    feishu_ok = True
                    ok = result.get("ok", False) and has_html and feishu_ok

                    item = {
                        "jira_key": bugid, "ok": ok, "has_html": has_html,
                        "skipped": is_skipped,
                        "results": results_dict,
                        "error": result.get("error", ""),
                        "bt_found": info["rec"] is not None,
                        "desc_source": "bitable" if info["bt_desc"] else ("api" if info["desc"] else "none"),
                        "time_source": "bitable" if info["bt_time"] else ("api" if info["tt"] else "none"),
                        "fail_type": _adp_fail_type(result),
                        **_adp_text_payload(result),
                        "file_urls": result.get("file_urls", []),
                    }
                    batch_results.append(item)
                    yield f"data: {_json.dumps({'type': 'item_done', **item}, ensure_ascii=False)}\\n\\n"
                    # 动态补位：只要完成一个，立即从队列取下一个
                    if next_idx < len(effective_bugids):
                        next_bugid = effective_bugids[next_idx]
                        nf = pool.submit(_run_one_adp, next_bugid)
                        futures[nf] = {"bugid": next_bugid}
                        next_idx += 1
                # 还有未完成的，发心跳并等待
                if futures and not done_now:
                    running_keys = [futures[f]["bugid"] for f in futures]
                    yield f"data: {_json.dumps({'type': 'keepalive', 'running': running_keys}, ensure_ascii=False)}\\n\\n"
                if futures:
                    await asyncio.sleep(5)

        all_results.extend(batch_results)
        total_success = sum(1 for r in batch_results if r["has_html"])
        total_fail = len(batch_results) - total_success
        total_skip = sum(1 for r in batch_results if r.get("skipped"))
'''

# Replace the old while pending: block with new code
new_lines = lines[:start_idx] + [new_code] + lines[end_idx+1:]

with open('d:/program16/src/api/routes/testing.py', 'w', encoding='utf-8') as f:
    f.writelines(new_lines)
print("Done")
