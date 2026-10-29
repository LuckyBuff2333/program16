with open('d:/program16/src/api/routes/testing.py', 'r', encoding='utf-8') as f:
    content = f.read()

# 1. Change default batch_size from 2 to 3
content = content.replace(
    'batch_size = int(body.get("batch_size") or 2)',
    'batch_size = int(body.get("batch_size") or 3)'
)

# 2. Replace batch flow execution
batch_old = '''        all_results = []
        for batch_idx in range(total_batches):
            if _batch_stop.is_set():
                break
            batch = todo[batch_idx * batch_size : (batch_idx + 1) * batch_size]
            yield f"data: {_json.dumps({'type': 'batch_start', 'batch': batch_idx + 1, 'total_batches': total_batches, 'count': len(batch)}, ensure_ascii=False)}\\n\\n"
            # 并发执行本批次
            batch_results = []
            def _run_one(item):
                bugid = item.get("bugid", "")
                desc = item.get("description", "")
                tt = item.get("trigger_time", "")
                # 描述或时间为空时用 Jira API 兜底
                if not desc.strip() or not tt.strip():
                    try:
                        from src.clients import jira_client as _jc_fallback
                        _issue = _jc_fallback.fetch_issue(bugid)
                        _f = (_issue.get("fields") or {})
                        if not desc.strip():
                            desc = (_f.get("description") or "")[:500]
                        if not desc.strip():
                            desc = (_f.get("summary") or "")[:500]
                        if not tt.strip():
                            try:
                                tt = _jc_fallback.extract_trigger_time_from_issue(_issue) or ""  
                            except Exception:
                                pass
                    except Exception as _e:
                        logger.warning("ADP batch Jira兜底失败 %s: %s", bugid, _e)
                try:
                    return run_adp_single(bugid, desc, tt, stop_event=_batch_stop)
                except Exception as e:
                    return {"ok": False, "jira_key": bugid, "error": str(e)[:100]}

            with concurrent.futures.ThreadPoolExecutor(max_workers=batch_size) as pool:
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

batch_new = '''        all_results = []
        batch_results = []
        next_idx = 0
        import time as _time

        def _run_one(item):
            bugid = item.get("bugid", "")
            desc = item.get("description", "")
            tt = item.get("trigger_time", "")
            # 描述或时间为空时用 Jira API 兜底
            if not desc.strip() or not tt.strip():
                try:
                    from src.clients import jira_client as _jc_fallback
                    _issue = _jc_fallback.fetch_issue(bugid)
                    _f = (_issue.get("fields") or {})
                    if not desc.strip():
                        desc = (_f.get("description") or "")[:500]
                    if not desc.strip():
                        desc = (_f.get("summary") or "")[:500]
                    if not tt.strip():
                        try:
                            tt = _jc_fallback.extract_trigger_time_from_issue(_issue) or ""  
                        except Exception:
                            pass
                except Exception as _e:
                    logger.warning("ADP batch Jira兜底失败 %s: %s", bugid, _e)
            try:
                return run_adp_single(bugid, desc, tt, stop_event=_batch_stop)
            except Exception as e:
                return {"ok": False, "jira_key": bugid, "error": str(e)[:100]}

        with concurrent.futures.ThreadPoolExecutor(max_workers=batch_size) as pool:
            futures = {}
            for it in todo[:batch_size]:
                f = pool.submit(_run_one, it)
                futures[f] = it
            next_idx = batch_size
            batch_deadline = _time.time() + 600
            while futures:
                if _batch_stop.is_set():
                    for f in futures:
                        f.cancel()
                    pool.shutdown(wait=False, cancel_futures=True)
                    break
                if _time.time() > batch_deadline:
                    for f in list(futures):
                        f.cancel()
                        it = futures.pop(f)
                        r = {"ok": False, "jira_key": it.get("bugid", ""), "error": "ADP 分析超时"}
                        batch_results.append(r)
                        yield f"data: {_json.dumps({'type': 'item_done', 'jira_key': r['jira_key'], 'ok': False, 'results': {}, 'error': r['error'], 'fail_type': _adp_fail_type(r), **_adp_text_payload({}), 'file_urls': []}, ensure_ascii=False)}\\n\\n"
                    break
                done_now = [f for f in futures if f.done()]
                for future in done_now:
                    it = futures.pop(future)
                    try:
                        r = future.result()
                    except Exception as e:
                        r = {"ok": False, "jira_key": it.get("bugid", ""), "error": str(e)[:100]}
                    batch_results.append(r)
                    yield f"data: {_json.dumps({'type': 'item_done', 'jira_key': r.get('jira_key', ''), 'ok': r.get('ok', False), 'results': r.get('results', {}), 'error': r.get('error', ''), 'fail_type': _adp_fail_type(r), **_adp_text_payload(r), 'file_urls': r.get('file_urls', [])}, ensure_ascii=False)}\\n\\n"
                    # 动态补位
                    if next_idx < len(todo):
                        next_item = todo[next_idx]
                        nf = pool.submit(_run_one, next_item)
                        futures[nf] = next_item
                        next_idx += 1
                if futures and not done_now:
                    running_keys = [futures[f].get('bugid', '') for f in futures]
                    yield f"data: {_json.dumps({'type': 'keepalive', 'running': running_keys}, ensure_ascii=False)}\\n\\n"
                if futures:
                    await asyncio.sleep(5)

        all_results.extend(batch_results)'''

if batch_old in content:
    content = content.replace(batch_old, batch_new)
    print("Batch flow replaced")
else:
    print("Batch old NOT found")

with open('d:/program16/src/api/routes/testing.py', 'w', encoding='utf-8') as f:
    f.write(content)
print("Saved")
