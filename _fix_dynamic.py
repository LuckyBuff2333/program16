"""Modify testing.py for dynamic pool and batch_size=3"""

with open('d:/program16/src/api/routes/testing.py', 'r', encoding='utf-8') as f:
    lines = f.readlines()

# 1. Change default batch_size from 2 to 3 (both occurrences)
for i, line in enumerate(lines):
    if 'batch_size = int(body.get("batch_size") or 2)' in line:
        lines[i] = line.replace('or 2)', 'or 3)')
        print(f"Line {i+1}: Changed batch_size default to 3")

# 2. Replace batch flow: lines 5208-5283 (0-indexed: 5207-5282)
# Find the exact line numbers by searching for markers
batch_start = None
batch_end = None
for i, line in enumerate(lines):
    if 'all_results = []' in line and batch_start is None:
        # Check if next line has 'for batch_idx in range(total_batches):'
        if i + 1 < len(lines) and 'for batch_idx in range(total_batches):' in lines[i+1]:
            batch_start = i
    if batch_start is not None and batch_end is None:
        if 'all_results.extend(batch_results)' in line:
            batch_end = i
            break

print(f"Batch flow: lines {batch_start+1} to {batch_end+1}")

if batch_start is not None and batch_end is not None:
    new_batch = '''        all_results = []
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
                    # 动态补位：只要完成一个，立即从 todo 取下一个
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

        all_results.extend(batch_results)
'''
    lines[batch_start:batch_end+1] = [new_batch]
    print("Batch flow replaced with dynamic pool")
else:
    print("ERROR: Could not find batch flow boundaries")

with open('d:/program16/src/api/routes/testing.py', 'w', encoding='utf-8') as f:
    f.writelines(lines)
print("Saved")
