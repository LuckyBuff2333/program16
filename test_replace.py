import re

with open('d:/program16/src/api/routes/testing.py', 'r', encoding='utf-8') as f:
    content = f.read()

# ===== Batch flow: replace fixed-batch with dynamic pool =====

batch_old = '''            with concurrent.futures.ThreadPoolExecutor(max_workers=batch_size) as pool:
                futures = {}
                for it in batch:
                    f = pool.submit(_run_one, it)
                    futures[f] = it
                # 非阻塞轮询等待，每 5 秒发心跳防止前端连接超时
                import time as _time
                remaining = dict(futures)
                batch_deadline = _time.time() + 600  # 单批超时 10 分钟
                while remaining:
                    if _batch_stop.is_set():
                        for f in remaining:
                            f.cancel()
                        pool.shutdown(wait=False, cancel_futures=True)
                        break
                    if _time.time() > batch_deadline:
                        for f in list(remaining):
                            f.cancel()
                            it = remaining.pop(f)
                            r = {"ok": False, "jira_key": it.get("bugid", ""), "error": "ADP 分析超时"}
                            batch_results.append(r)
                            yield f"data: {_json.dumps({'type': 'item_done', 'jira_key': r['jira_key'], 'ok': False, 'results': {}, 'error': r['error'], 'fail_type': _adp_fail_type(r), **_adp_text_payload({}), 'file_urls': []}, ensure_ascii=False)}\\n\\n"
                        break
                    # 收集已完成的 future
                    done_now = [f for f in remaining if f.done()]
                    for future in done_now:
                        del remaining[future]
                        it = futures[future]
                        try:
                            r = future.result()
                        except Exception as e:
                            r = {"ok": False, "jira_key": it.get("bugid", ""), "error": str(e)[:100]}
                        batch_results.append(r)
                        yield f"data: {_json.dumps({'type': 'item_done', 'jira_key': r.get('jira_key', ''), 'ok': r.get('ok', False), 'results': r.get('results', {}), 'error': r.get('error', ''), 'fail_type': _adp_fail_type(r), **_adp_text_payload(r), 'file_urls': r.get('file_urls', [])}, ensure_ascii=False)}\\n\\n"
                    # 还有未完成的，发心跳并等待
                    if remaining and not done_now:
                        running_keys = [futures[f].get('bugid', '') for f in remaining]
                        yield f"data: {_json.dumps({'type': 'keepalive', 'running': running_keys}, ensure_ascii=False)}\\n\\n"
                    if remaining:
                        await asyncio.sleep(5)

            all_results.extend(batch_results)'''

batch_new = '''            # 动态并发池：始终保持 batch_size 个任务在跑，一个完成立即补位
            import time as _time
            with concurrent.futures.ThreadPoolExecutor(max_workers=batch_size) as pool:
                futures = {}
                # 初始提交
                for it in todo:
                    if len(futures) >= batch_size:
                        break
                    f = pool.submit(_run_one, it)
                    futures[f] = it
                
                batch_deadline = _time.time() + 600  # 单批超时 10 分钟
                while futures:
                    if _batch_stop.is_set():
                        for f in futures:
                            f.cancel()
                        pool.shutdown(wait=False, cancel_futures=True)
                        break
                    
                    # 收集已完成的 future
                    done_now = [f for f in futures if f.done()]
                    for future in done_now:
                        it = futures.pop(future)
                        try:
                            r = future.result()
                        except Exception as e:
                            r = {"ok": False, "jira_key": it.get("bugid", ""), "error": str(e)[:100]}
                        batch_results.append(r)
                        yield f"data: {_json.dumps({'type': 'item_done', 'jira_key': r.get('jira_key', ''), 'ok': r.get('ok', False), 'results': r.get('results', {}), 'error': r.get('error', ''), 'fail_type': _adp_fail_type(r), **_adp_text_payload(r), 'file_urls': r.get('file_urls', [])}, ensure_ascii=False)}\\n\\n"
                        
                        # 动态补位：从剩余 todo 中取下一个
                        for next_it in todo:
                            if next_it not in [futures[f] for f in futures] and next_it not in batch_results:
                                nf = pool.submit(_run_one, next_it)
                                futures[nf] = next_it
                                break
                    
                    # 还有未完成的，发心跳并等待
                    if futures and not done_now:
                        running_keys = [futures[f].get('bugid', '') for f in futures]
                        yield f"data: {_json.dumps({'type': 'keepalive', 'running': running_keys}, ensure_ascii=False)}\\n\\n"
                        await asyncio.sleep(5)

            all_results.extend(batch_results)'''

# For lookup flow
lookup_old = '''            # 并发执行本组（最多 batch_size 个线程，字段补全+ADP分析全在线程内）
            batch_results = []
            with concurrent.futures.ThreadPoolExecutor(max_workers=batch_size) as pool:
                futures = {}
                for bugid in batch_bugids:
                    f = pool.submit(_run_one_adp, bugid)
                    futures[f] = {"bugid": bugid}
                # 非阻塞轮询等待，定期发心跳
                remaining = dict(futures)
                batch_deadline = _time.time() + adp_cfg["timeout"] + 120
                while remaining:
                    if _stop_event.is_set():
                        for f in remaining:
                            f.cancel()
                        pool.shutdown(wait=False, cancel_futures=True)
                        break
                    # 检查超时的 future
                    if _time.time() > batch_deadline:
                        for f in list(remaining):
                            f.cancel()
                            bugid = remaining.pop(f)["bugid"]
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
                    done_now = [f for f in remaining if f.done()]
                    for future in done_now:
                        del remaining[future]
                        bugid = futures[future]["bugid"]
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

                        # 写回多维表格（改为批量写入，分析阶段暂不做逐条写回）
                        # feishu_ok = await _write_back(bugid, result, info["rec"])
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
                    # 还有未完成的，发心跳并等待
                    if remaining and not done_now:
                        running_keys = [futures[f]["bugid"] for f in remaining]
                        yield f"data: {_json.dumps({'type': 'keepalive', 'running': running_keys}, ensure_ascii=False)}\\n\\n"
                    if remaining:
                        await asyncio.sleep(5)'''

print("Batch old found:", batch_old in content)
print("Lookup old found:", lookup_old in content)
