# 置信度评测 & 评论对比 功能代码汇总

> 提取自 `src/web/server.py`、`src/pipeline.py`、`src/core/semantic.py`、`src/core/filter.py`、`src/web/index.html`
> 原始文件未做任何修改，仅做代码摘录便于审阅。


## 一、置信度批量写入（后端 API）
### 1.1 `/api/test/confidence_batch_write` — SSE 流式评测

**文件**: `src/web/server.py` L13943-L14328

```python
async def test_confidence_batch_write(request: Request, after_time: str = "", only_empty: str = "", jira_ids: str = ""):
    """置信度批量写入：填充 rootcause + AI问题分析根因，对比语义相似度写回置信度

    :param after_time: 可选时间筛选，仅处理分析完成时间在此时间之后的记录
    :param jira_ids: 可选 Jira 号列表（逗号分隔），指定时仅处理这些记录，忽略 after_time 和 only_empty
    """
    from src.clients import feishu_client
    from src.core import semantic as semantic_module
    import json as _json

    async def generate():
        cfg = load_config().get("feishu_bitable", {})
        app_token = cfg.get("app_token", "")
        table_id = cfg.get("table_id", "")
        bugid_field = cfg.get("bugid_field", "jira号")
        conf_field_name = cfg.get("confidence_field", "结果置信度")
        threshold = float(load_config().get("similarity", {}).get("threshold", 0.7))
        if not app_token or not table_id:
            yield f"data: {_json.dumps({'type': 'error', 'msg': '多维表格 app_token/table_id 未配置'}, ensure_ascii=False)}\n\n"
            return

        # 加载字段定义，确定字段名和类型
        try:
            field_defs = feishu_client.list_bitable_fields(app_token, table_id)
            field_type_map = {fd.get("field_name", ""): fd.get("type", 0) for fd in field_defs}
            field_names = list(field_type_map.keys())
            # 置信度字段
            cf_field = conf_field_name if conf_field_name in field_type_map else ""
            if not cf_field:
                for fn in field_names:
                    if "置信度" in fn:
                        cf_field = fn
                        break
            # rootcause 字段
            rc_field = next((fn for fn in field_names if fn.lower() == "rootcause"), "")
            # AI问题分析根因字段
            ai_rc_field = next((fn for fn in field_names if "AI问题分析根因" in fn or "问题分析根因" in fn), "")
            if not ai_rc_field:
                ai_rc_field = next((fn for fn in field_names if "AI" in fn and "根因" in fn), "")
            logger.info("置信度批量写入字段映射: cf=%s, rc=%s, ai_rc=%s", cf_field, rc_field, ai_rc_field)
        except Exception as e:
            yield f"data: {_json.dumps({'type': 'error', 'msg': f'获取字段定义失败: {e}'}, ensure_ascii=False)}\n\n"
            return

        # 加载多维表格记录，筛选分析结果=成功 且 置信度为空/0
        try:
            records = feishu_client.list_bitable_records(app_token, table_id)
        except Exception as e:
            yield f"data: {_json.dumps({'type': 'error', 'msg': f'加载多维表格记录失败: {e}'}, ensure_ascii=False)}\n\n"
            return

        # 当指定 jira_ids 时，仅处理这些 Jira 号，忽略 after_time 和 only_empty
        _jira_id_set = set(x.strip().upper() for x in jira_ids.split(",") if x.strip()) if jira_ids else None
        targets = []
        for rec in records:
            fields = rec.get("fields", {})
            if str(fields.get("分析结果", "")).strip() != "成功":
                continue
            if _jira_id_set:
                # 按指定 Jira ID 过滤（大小写不敏感）
                fv_check = fields.get(bugid_field, "")
                if isinstance(fv_check, list):
                    fv_check = " ".join(str(v) for v in fv_check)
                if str(fv_check).strip().upper() not in _jira_id_set:
                    continue
            if not _jira_id_set and after_time:
                done_str = _bitable_text(fields.get("分析完成时间", ""))
                if not done_str or done_str < after_time:
                    continue
            conf_val = fields.get(conf_field_name, "")
            if isinstance(conf_val, list):
                conf_val = " ".join(str(v) for v in conf_val)
            conf_str = str(conf_val).strip()
            # only_empty=True 时仅处理置信度为空的记录，jira_ids 模式忽略此筛选
            if not _jira_id_set and only_empty and conf_str and conf_str not in ("0", "0.0"):
                continue
            fv = fields.get(bugid_field, "")
            if isinstance(fv, list):
                fv = " ".join(str(v) for v in fv)
            fv = str(fv).strip()
            if not fv:
                continue
            # 提取已有字段值
            existing_rc = _bitable_text(fields.get(rc_field, "")) if rc_field else ""
            existing_ai_rc = _bitable_text(fields.get(ai_rc_field, "")) if ai_rc_field else ""
            feishu_link = fields.get("AI分析结果(飞书链接)", "")
            if isinstance(feishu_link, dict):
                feishu_link = feishu_link.get("link", "") or feishu_link.get("text", "")
            feishu_link = str(feishu_link).strip() if feishu_link else ""
            targets.append({
                "jira号": fv, "record_id": rec["record_id"],
                "rootcause": existing_rc, "ai_rootcause": existing_ai_rc,
                "feishu_link": feishu_link,
                "conf_empty": not conf_str or conf_str in ("0", "0.0"),
            })

        total = len(targets)
        yield f"data: {_json.dumps({'type': 'start', 'total': total, 'threshold': threshold, 'after_time': after_time or ''}, ensure_ascii=False)}\n\n"
        if not total:
            yield f"data: {_json.dumps({'type': 'done', 'updated': 0, 'total': 0, 'msg': '无需处理的记录'}, ensure_ascii=False)}\n\n"
            return

        # 逐条处理：填充字段 + 对比 + 立即写回
        loop = asyncio.get_event_loop()
        success_count = 0
        fail_count = 0
        written = 0

        def _extract_core_rootcause(text: str) -> str:
            """从根因文本中提取核心语义用于 Diana LLM 对比

            支持两种格式：
            1. 结构化标记：【根本原因】/【直接原因】 段落
            2. 自然语言：提取结论句+前文上下文，拼成完整因果链
            无标记时返回全文。
            """
            if not text:
                return ""
            import re as _re
            # 1. 结构化标记：【根本原因】/【直接原因】
            m = _re.search(r'[\[\u3010\(（]\s*(?:根本原因|直接原因)\s*[\]\u3011\)）]\s*(.*?)(?=[\[\u3010\(（]|$)', text, _re.DOTALL)
            if m:
                return m.group(1).strip()
            # 2. 自然语言结论句提取
            # 优先匹配结论句（“因此”），带上前一句上下文拼成完整因果链
            for pattern in [
                r'(?:因此[，,]?\s*)([\u4e00-\u9fff].{10,})',
                r'(?:核心原因[是为]|直接原因[是为]|根因[是为])([\u4e00-\u9fff].{10,})',
            ]:
                m = _re.search(pattern, text)
                if m:
                    conclusion = m.group(1).strip()
                    # 取到第一个句号/感叹号为止的核心句
                    end = _re.search(r'[。！]', conclusion)
                    if end and end.start() > 6:
                        conclusion = conclusion[:end.end()]
                    else:
                        conclusion = conclusion[:200]
                    # 去除尾部噪声从句：“由于…”“这是…”“但无法…”
                    conclusion = _re.sub(r'[，,]\s*(?:由于|这是|但无法|但目前|无法确认|无法读取).*$', '', conclusion)
                    # 去除模糊词：“很可能”“可能”“大概率”
                    conclusion = _re.sub(r'(?:很可能|很可能是|大概率|可能)', '', conclusion)
                    # 提取前一句上下文（原因/背景），拼成完整因果链
                    before = text[:m.start()].strip()
                    if before:
                        prev_sents = _re.split(r'[。！？]', before)
                        prev_sents = [s.strip() for s in prev_sents if len(s.strip()) >= 8]
                        if prev_sents:
                            context = prev_sents[-1]
                            # 前句过长时从句子边界截取尾部，避免截断单词
                            if len(context) > 100:
                                sub = _re.split(r'[，,、]', context)
                                context = '，'.join(sub[-2:]) if len(sub) > 1 else context[-60:]
                            return (context + '，' + conclusion).strip()
                    return conclusion.strip()
            # 3. 回退：返回全文
            return text.strip()

        def _split_semantic_sentences(text: str) -> list:
            """将长文本按句子拆分，用于逐句语义兆底对比"""
            import re as _re
            parts = _re.split(r'([。！？；;!?])', text)
            sentences, cur = [], ""
            for i in range(len(parts)):
                cur += parts[i]
                if i % 2 == 1:  # 标点符号
                    s = cur.strip()
                    if len(s) >= 6:
                        sentences.append(s)
                    cur = ""
            if cur.strip() and len(cur.strip()) >= 6:
                sentences.append(cur.strip())
            return sentences

        def _extract_conclusion_only(text: str) -> str:
            """提取最干净的结论句（避免负面句子拉低对比分）"""
            import re as _re
            m = _re.search(r'(?:因此[，,]?\s*)([\u4e00-\u9fff].{10,})', text)
            if m:
                conclusion = m.group(1).strip()
                end = _re.search(r'[。！]', conclusion)
                if end and end.start() > 6:
                    conclusion = conclusion[:end.end()]
                else:
                    conclusion = conclusion[:200]
                conclusion = _re.sub(r'[，,]\s*(?:由于|这是|但无法|但目前|无法确认|无法读取).*$', '', conclusion)
                conclusion = _re.sub(r'(?:很可能|很可能是|大概率|可能)', '', conclusion)
                return conclusion.strip()
            return ""

        def _extract_entity_sentence(text: str, keywords: list) -> str:
            """从文本中提取同时包含最多关键词的句子，用于更精准的语义对比"""
            import re as _re
            parts = _re.split(r'[。！？]', text)
            best_sent = ""
            best_count = 0
            for part in parts:
                s = part.strip()
                if len(s) < 8:
                    continue
                count = sum(1 for kw in keywords if kw in s)
                if count > best_count:
                    best_count = count
                    best_sent = s
            return best_sent if best_count >= 2 else ""

        def _write_one(record_id, fields_to_write):
            """单条写入，失败时返回错误信息，不中断流程"""
            try:
                feishu_client.update_bitable_records(app_token, table_id,
                                                     [{"record_id": record_id, "fields": fields_to_write}])
                return ""
            except Exception as e:
                return str(e)[:120]

        for idx, t in enumerate(targets):
            if await request.is_disconnected():
                yield f"data: {_json.dumps({'type': 'cancelled'}, ensure_ascii=False)}\n\n"
                return
            bugid = t["jira号"]
            conf_empty = t.get("conf_empty", False)
            fields_to_write = {}
            jira_rc = t["rootcause"]
            ai_rc = t["ai_rootcause"]
            try:
                # 1. rootcause：始终从 Jira API 取最新值，覆盖表格旧数据
                if rc_field:
                    try:
                        issue = await loop.run_in_executor(None, jira_client.fetch_issue, bugid)
                        fresh_rc = jira_client.extract_rootcause(issue) or ""
                        if fresh_rc:
                            jira_rc = fresh_rc
                            fields_to_write[rc_field] = fresh_rc
                    except Exception as e:
                        logger.warning("bugid=%s Jira rootcause获取失败，回退表格值: %s", bugid, e)
                # 2. AI问题分析根因：表格已有数据则直接用，否则从飞书文档提取
                if not ai_rc and ai_rc_field and t["feishu_link"]:
                    try:
                        ai_content = await loop.run_in_executor(
                            None, pipeline._get_ai_report_content, bugid, t["feishu_link"])
                        ai_rc = doc_generator.parse_root_cause_section(ai_content) or ""
                        if ai_rc:
                            fields_to_write[ai_rc_field] = ai_rc
                    except Exception as e:
                        logger.warning("bugid=%s AI文档根因获取失败: %s", bugid, e)
                # 3. 两个根因都为空则跳过
                if not jira_rc and not ai_rc:
                    _sse_d = {'type': 'progress', 'index': idx + 1, 'total': total,
                                                'bugid': bugid, 'status': 'skipped', 'score': 0,
                                                'record_id': t['record_id'], 'write_fields': fields_to_write,
                                                'conf_empty': conf_empty,
                                                'msg': '两个根因字段均为空'}
                    yield f"data: {_json.dumps(_sse_d, ensure_ascii=False)}\n\n"
                    fail_count += 1
                    continue
                if not jira_rc or not ai_rc:
                    missing = 'Jira根因' if not jira_rc else 'AI根因'
                    _sse_d = {'type': 'progress', 'index': idx + 1, 'total': total,
                                                'bugid': bugid, 'status': 'skipped', 'score': 0,
                                                'jira_rootcause': jira_rc, 'ai_rootcause': ai_rc,
                                                'record_id': t['record_id'], 'write_fields': fields_to_write,
                                                'conf_empty': conf_empty,
                                                'msg': f'{missing}为空，无法对比'}
                    yield f"data: {_json.dumps(_sse_d, ensure_ascii=False)}\n\n"
                    fail_count += 1
                    continue
                # 4. 通用/无效/重复根因：置信度写"无法判断"
                _SKIP_ROOTCAUSE_KEYWORDS = ("同根因重复", "重复BUG", "重复问题", "重复缺陷", "根因一致")
                _INVALID_AI_RC_KEYWORDS = ("无法复现", "日志无法", "无法定位", "暂无分析", "无法获取日志")
                skip_reason = ""
                if pipeline._is_generic_rootcause(jira_rc):
                    skip_reason = f"Jira根因为通用表述: {jira_rc[:60]}"
                elif any(kw in jira_rc for kw in _SKIP_ROOTCAUSE_KEYWORDS):
                    hit = next(kw for kw in _SKIP_ROOTCAUSE_KEYWORDS if kw in jira_rc)
                    skip_reason = f"Jira根因含重复标记关键词[{hit}]: {jira_rc[:60]}"
                elif any(kw in ai_rc for kw in _INVALID_AI_RC_KEYWORDS):
                    hit = next(kw for kw in _INVALID_AI_RC_KEYWORDS if kw in ai_rc)
                    skip_reason = f"AI根因含无效关键词[{hit}]: {ai_rc[:60]}"
                if skip_reason:
                    cf_type = field_type_map.get(cf_field, 0)
                    write_val = "无法判断" if cf_type != 2 else 0
                    fields_to_write[cf_field] = write_val
                    success_count += 1
                    logger.info("置信度跳过 bugid=%s reason=%s", bugid, skip_reason)
                    _sse_d = {'type': 'progress', 'index': idx + 1, 'total': total,
                                                'bugid': bugid, 'status': 'invalid', 'score': '无法判断',
                                                'jira_rootcause': jira_rc, 'ai_rootcause': ai_rc,
                                                'record_id': t['record_id'], 'write_fields': fields_to_write,
                                                'conf_empty': conf_empty,
                                                'msg': skip_reason}
                    yield f"data: {_json.dumps(_sse_d, ensure_ascii=False)}\n\n"
                    continue
                # 5. 多路语义对比：取最高分
                jira_core = _extract_core_rootcause(jira_rc)
                ai_core = _extract_core_rootcause(ai_rc)
                logger.info("置信度对比 bugid=%s | jira_core=[%s] | ai_core=[%s]", bugid, jira_core[:80], ai_core[:80])
                # 路1: 核心语义对比（可能带上下文）
                score = await loop.run_in_executor(None, semantic_module.semantic_similarity, jira_core, ai_core)
                score = round(score, 3)
                is_pass = score >= threshold
                logger.info("置信度核心对比 bugid=%s score=%.3f pass=%s", bugid, score, is_pass)
                ai_conclusion = ""
                # 路2: 仅结论句对比（避免负面上下文拉低分数）
                if not is_pass:
                    ai_conclusion = _extract_conclusion_only(ai_rc)
                    if ai_conclusion and ai_conclusion != ai_core:
                        sc2 = await loop.run_in_executor(None, semantic_module.semantic_similarity, jira_core, ai_conclusion)
                        sc2 = round(sc2, 3)
                        logger.info("置信度结论对比 bugid=%s score=%.3f conclusion=[%s]", bugid, sc2, ai_conclusion[:80])
                        if sc2 > score:
                            score = sc2
                            is_pass = score >= threshold
                # 路3: 实体句匹配（从AI根因中提取同时含Jira关键实体的句子对比）
                if not is_pass:
                    import re as _re2
                    # 提取Jira根因中的有意义短关键词（2-3字），过滤噪声词
                    _noise_kw = {"这个", "问题", "符合", "设计", "导致", "因为", "所以", "因此", "但是", "然后"}
                    # 先用标点拆分，再对每个子串提取2-3字关键词
                    _jira_parts = _re2.split(r'[^\u4e00-\u9fff]+', jira_rc)
                    jira_keywords = []
                    for p in _jira_parts:
                        for kw_len in (3, 2):
                            for i in range(len(p) - kw_len + 1):
                                kw = p[i:i+kw_len]
                                if kw not in _noise_kw and kw not in jira_keywords:
                                    jira_keywords.append(kw)
                    if jira_keywords:
                        entity_sent = _extract_entity_sentence(ai_rc, jira_keywords)
                        if entity_sent and entity_sent != ai_core:
                            sc3 = await loop.run_in_executor(None, semantic_module.semantic_similarity, jira_core, entity_sent)
                            sc3 = round(sc3, 3)
                            logger.info("置信度实体句对比 bugid=%s score=%.3f entity_sent=[%s] keywords=%s", bugid, sc3, entity_sent[:80], jira_keywords[:8])
                            if sc3 > score:
                                score = sc3
                                is_pass = score >= threshold
                # 路4: 逐句兆底对比
                if not is_pass and len(ai_rc) > 80:
                    ai_sents = _split_semantic_sentences(ai_rc)
                    if len(ai_sents) > 1:
                        sent_max = 0.0
                        sent_best = ""
                        for s in ai_sents:
                            sc = await loop.run_in_executor(None, semantic_module.semantic_similarity, jira_core, s)
                            if sc > sent_max:
                                sent_max = sc
                                sent_best = s[:60]
                        sent_max = round(sent_max, 3)
                        logger.info("置信度逐句兆底 bugid=%s sent_max=%.3f best=[%s] sents=%d", bugid, sent_max, sent_best, len(ai_sents))
                        if sent_max >= threshold:
                            score = sent_max
                            is_pass = True
                # 路5: 全文原始对比（用原始Jira根因与原始AI根因，让模型看完整上下文）
                if not is_pass and len(ai_rc) > 50:
                    sc5 = await loop.run_in_executor(None, semantic_module.semantic_similarity, jira_rc[:300], ai_rc[:500])
                    sc5 = round(sc5, 3)
                    logger.info("置信度全文对比 bugid=%s score=%.3f", bugid, sc5)
                    if sc5 > score:
                        score = sc5
                        is_pass = score >= threshold
                cf_type = field_type_map.get(cf_field, 0)
                write_val = float(score) if cf_type == 2 else str(score)
                fields_to_write[cf_field] = write_val
                if is_pass:
                    success_count += 1
                _sse_d = {'type': 'progress', 'index': idx + 1, 'total': total,
                                            'bugid': bugid, 'status': 'pass' if is_pass else 'low',
                                            'score': score,
                                            'jira_rootcause': jira_rc, 'ai_rootcause': ai_rc,
                                            'record_id': t['record_id'], 'write_fields': fields_to_write,
                                            'conf_empty': conf_empty,
                                            'msg': '' if is_pass else f'相似度{score}<{threshold}'}
                yield f"data: {_json.dumps(_sse_d, ensure_ascii=False)}\n\n"
            except Exception as e:
                fail_count += 1
                _sse_d = {'type': 'progress', 'index': idx + 1, 'total': total,
                                            'bugid': bugid, 'status': 'fail', 'score': 0,
                                            'conf_empty': conf_empty,
                                            'msg': str(e)[:120]}
                yield f"data: {_json.dumps(_sse_d, ensure_ascii=False)}\n\n"

        _sse_d = {'type': 'done', 'total': total, 'updated': 0,
                                    'passed': success_count, 'failed': fail_count,
                                    'msg': f'分析完成: {total}条, 达标{success_count}条, 未达标{total - success_count - fail_count}条, 跳过/失败{fail_count}条'}
        yield f"data: {_json.dumps(_sse_d, ensure_ascii=False)}\n\n"

    return StreamingResponse(generate(), media_type="text/event-stream")
```


### 1.2 `/api/test/confidence_batch_commit` — 批量写入提交

**文件**: `src/web/server.py` L14332-L14361

```python
async def test_confidence_batch_commit(request: Request):
    """置信度批量写入提交：接收前端筛选后的记录列表，批量写入多维表格"""
    from src.clients import feishu_client
    body = await request.json() or {}
    items = body.get("items") or []
    if not items:
        return _fail("待写入列表为空")
    cfg = load_config().get("feishu_bitable", {})
    app_token = cfg.get("app_token", "")
    table_id = cfg.get("table_id", "")
    if not app_token or not table_id:
        return _fail("多维表格 app_token/table_id 未配置")
    # 逐条写入，跳过 record_id 为空的
    written = 0
    errors = []
    for item in items:
        record_id = item.get("record_id", "")
        fields = item.get("write_fields") or {}
        if not record_id or not fields:
            continue
        try:
            feishu_client.update_bitable_records(app_token, table_id,
                                                 [{"record_id": record_id, "fields": fields}])
            written += 1
        except Exception as e:
            errors.append(f"{item.get('bugid', '?')}: {str(e)[:80]}")
    msg = f"写入完成: {written}/{len(items)} 条"
    if errors:
        msg += f"，{len(errors)} 条失败"
    return _ok({"written": written, "errors": errors}, msg)
```


## 二、评论对比（后端 API）
### 2.1 `_compare_single_bug` — 单条对比核心逻辑

**文件**: `src/web/server.py` L14926-L14946

```python
def _compare_single_bug(bugid: str, trigger_time: str = None, uploaded_rows: list = None) -> dict:
    """对单个 bug 执行完整对比，复用 pipeline.compare_bug_analysis 并补充结论与兼容字段"""
    result = pipeline.compare_bug_analysis(bugid, trigger_time, uploaded_rows)
    # 生成结论描述
    if result.get("skipped"):
        conclusion = f"已跳过：{result.get('skip_reason', '未知原因')}"
    elif result["all_ok"]:
        conclusion = "分析正确：根因与评论对比均通过"
    elif result["root_cause_ok"]:
        conclusion = "需人工复核：根因匹配但评论对比不通过"
    elif result["comment_compare_ok"]:
        conclusion = "需人工复核：评论对比通过但根因不匹配"
    else:
        conclusion = "分析不一致：根因与评论对比均不通过，需人工复核"
    return {
        **result, "conclusion": conclusion, "error": None,
        "comments_total": len(result["comments"]),
        "comments_used": len(result["valid_comments"]),
        "truncated": len(result["valid_comments"]) < len(result["comments"]),
        "error_cause": result["bug_root_cause"],  # 兼容前端原有字段名
    }
```


### 2.2 `/api/test/comment_compare` — 单条评论对比

**文件**: `src/web/server.py` L14949-L14961

```python
@app.post("/api/test/comment_compare")
async def test_comment_compare(request: Request):
    """功能测试2：评论提取与对比（单条），返回评论原文、提取步骤及双重比对结果"""
    body = await request.json() or {}
    bugid = str(body.get("bugid", "")).strip()
    if not bugid:
        return _fail("bugid 不能为空")
    try:
        result = _compare_single_bug(bugid, body.get("trigger_time") or None)
        return _ok(result, "评论提取与对比完成")
    except Exception as e:
        logger.error("评论对比功能测试失败: %s", e)
        return _fail(str(e))
```


### 2.3 `/api/test/comment_compare_strategies` — 多策略评论分析对比

**文件**: `src/web/server.py` L14964-L15082

```python
@app.post("/api/test/comment_compare_strategies")
async def comment_compare_strategies(request: Request):
    """评论分析侧重点对比：对同一 Jira 用多种 prompt 策略各跑一次评论分析，并列展示"""
    from src.core.filter import COMMENT_ANALYSIS_STRATEGIES, summarize_comments, generate_comment_analysis
    from src.clients import jira_client, diana_client as _dc
    body = await request.json() or {}
    bugid = str(body.get("bugid", "")).strip()
    if not bugid:
        return _fail("bugid 不能为空")
    try:
        # 获取评论和 AI 结论（只执行一次，所有策略共用）
        issue = jira_client.fetch_issue(bugid)
        comments = jira_client.extract_comments(issue)
        summaries = summarize_comments(comments)
        # 获取 AI 日志分析结论（优先本地文档，回退从多维表格查飞书链接再下载）
        ai_conclusion = ""
        try:
            ai_content = pipeline._get_ai_report_content(bugid, "")
            ai_conclusion = doc_generator.parse_conclusion(ai_content) or ""
        except Exception:
            # 本地无文档，从多维表格查找飞书链接
            feishu_link = ""
            try:
                from src.clients import feishu_client
                cfg_bitable = load_config().get("feishu_bitable", {})
                at = cfg_bitable.get("app_token", "")
                tid = cfg_bitable.get("table_id", "")
                bf = cfg_bitable.get("bugid_field", "jira号")
                lf = "AI分析结果(飞书链接)"
                if at and tid:
                    records = feishu_client.list_bitable_records(at, tid)
                    for rec in records:
                        fields = rec.get("fields", {})
                        bid_val = str(fields.get(bf, ""))
                        if bid_val == bugid:
                            link_val = fields.get(lf, "")
                            if isinstance(link_val, dict):
                                link_val = link_val.get("link", "") or link_val.get("text", "")
                            feishu_link = str(link_val).strip() if link_val else ""
                            break
            except Exception as e:
                logger.warning("从多维表格查找飞书链接失败: %s", e)
            if feishu_link:
                try:
                    ai_content = pipeline._get_ai_report_content(bugid, feishu_link)
                    ai_conclusion = doc_generator.parse_conclusion(ai_content) or ""
                except Exception as e:
                    logger.warning("bugid=%s 通过飞书链接下载AI报告失败: %s", bugid, e)
        # 提取 Jira 根因
        bug_rootcause = ""
        try:
            bug_rootcause = jira_client.extract_rootcause(issue) or ""
        except Exception:
            pass
        # 对每种策略各跑一次评论分析
        results = []
        for key, strategy in COMMENT_ANALYSIS_STRATEGIES.items():
            try:
                analysis = generate_comment_analysis(
                    summaries, ai_conclusion, style_instruction=strategy["instruction"])
                # 从分析结果提取排查结论段落
                conclusion_text = ""
                if analysis:
                    in_section = False
                    for line in analysis.split("\n"):
                        if "## 排查结论" in line or "### 排查结论" in line:
                            in_section = True
                            continue
                        if in_section and line.startswith("##"):
                            break
                        if in_section and line.strip():
                            conclusion_text += line.strip() + " "
                    conclusion_text = conclusion_text.strip()[:120]
                # 用 Diana 生成 8-20 字的表格结论
                table_conclusion = ""
                if conclusion_text:
                    try:
                        simplify_prompt = (
                            f"用一句话（8到20字）概括以下排查结论，偏bug分析方向，必须是完整语义，只输出概括本身：\n"
                            f"{conclusion_text}\n概括："
                        )
                        tc = _dc._llm_chat(simplify_prompt, max_tokens=50, timeout=15)
                        if tc:
                            from src.pipeline import _strip_conclusion_prefix
                            table_conclusion = _strip_conclusion_prefix(tc.strip().rstrip('。.'))
                    except Exception:
                        pass
                results.append({
                    "key": key, "label": strategy["label"],
                    "instruction": strategy["instruction"],
                    "analysis": analysis or "（生成失败）",
                    "bugid": bugid,
                    "root_cause": bug_rootcause[:100] if bug_rootcause else "（未提取）",
                    "table_conclusion": table_conclusion or conclusion_text[:40] or "（无）",
                    "has_ai_conclusion": bool(ai_conclusion),
                    "confidence_assessment": (
                        "高" if (analysis and ai_conclusion and conclusion_text)
                        else "中" if analysis and not analysis.startswith("（")
                        else "低"
                    ),
                })
            except Exception as e:
                results.append({
                    "key": key, "label": strategy["label"],
                    "instruction": strategy["instruction"],
                    "analysis": f"（异常: {str(e)[:60]}）",
                    "bugid": bugid, "root_cause": "（异常）",
                    "table_conclusion": "（异常）", "has_ai_conclusion": False,
                    "confidence_assessment": "低",
                })
        # 读取当前已保存的风格偏好
        cfg = load_config()
        current_style = cfg.get("comment_analysis", {}).get("style_keywords", "")
        return _ok({"strategies": results, "current_style": current_style,
                    "comments_count": len(comments), "summaries_count": len(summaries)},
                   f"对比完成: {len(results)} 种策略, {len(comments)} 条评论")
    except Exception as e:
        logger.error("评论分析侧重点对比失败: %s", e, exc_info=True)
        return _fail(f"对比失败: {e}")
```


### 2.4 `/api/test/batch_compare` — 批量评论对比

**文件**: `src/web/server.py` L15129-L15168

```python
@app.post("/api/test/batch_compare")
async def batch_compare(request: Request):
    """批量评论对比：支持分号/逗号分隔的 bugid 列表（最多 30 个），返回汇总表格"""
    body = await request.json() or {}
    raw_bugids = str(body.get("bugids", "")).strip()
    if not raw_bugids:
        return _fail("bugid 列表不能为空")
    bugids = _parse_bugids(raw_bugids)
    if not bugids:
        return _fail("未解析到有效 bugid")
    trigger_times = body.get("trigger_times") or {}
    # 获取上传文件数据（可选）
    file_id = body.get("file_id")
    uploaded_rows = _uploaded_files_cache.get(file_id) if file_id else None
    try:
        results = []
        for bugid in bugids:
            try:
                result = _compare_single_bug(bugid, trigger_times.get(bugid), uploaded_rows)
                results.append(result)
            except Exception as e:
                logger.error("批量对比中 bugid=%s 失败: %s", bugid, e)
                results.append({
                    "bugid": bugid, "error": str(e)[:200],
                    "root_cause_ok": False, "comment_compare_ok": False, "all_ok": False,
                    "root_cause_score": 0.0, "layer1_score": 0.0, "layer2_score": 0.0,
                    "conclusion": f"分析异常: {str(e)[:80]}",
                })
        summary = {
            "total": len(results),
            "all_match_count": sum(1 for r in results if r.get("all_ok")),
            "root_cause_match_count": sum(1 for r in results if r.get("root_cause_ok")),
            "comment_match_count": sum(1 for r in results if r.get("comment_compare_ok")),
            "skipped_count": sum(1 for r in results if r.get("skipped")),
            "results": results,
        }
        return _ok(summary, f"批量对比完成: {len(results)} 个 bug")
    except Exception as e:
        logger.error("批量对比失败: %s", e)
        return _fail(str(e))
```


## 三、核心对比逻辑（pipeline.py）
### 3.1 `compare_bug_analysis` — AI报告 vs Bug单数据完整对比

**文件**: `src/pipeline.py` L872-L962

```python
def compare_bug_analysis(bugid: str, trigger_time: str = None, uploaded_rows: list = None) -> dict:
    """对单个 bug 执行完整对比：AI 报告 vs bug 单数据（根因 + 步骤）

    统一 pipeline 和 server 的对比逻辑。
    :return: 对比结果字典，含根因/步骤匹配度与结论
    """
    # 1. AI 分析并生成文档
    response = ai_log_client.analyze_logs(bugid, trigger_time)
    report_text = ai_log_client.extract_report(response)
    doc_path = doc_generator.save_document(bugid, report_text)
    doc_steps = doc_generator.parse_doc_steps(report_text)
    conclusion_text = doc_generator.parse_conclusion(report_text)

    # AI 报告无法提取根因或步骤：直接判定对比失败
    if not conclusion_text or not doc_steps:
        logger.info("bugid=%s AI报告无法提取根因(%s)或步骤(%d条)，对比直接失败",
                    bugid, "有" if conclusion_text else "无", len(doc_steps))
        return {
            "bugid": bugid, "doc_path": doc_path, "doc_steps": doc_steps,
            "ai_conclusion": conclusion_text, "bug_root_cause": "",
            "root_cause_score": 0.0, "root_cause_ok": False,
            "layer1_score": 0.0, "layer1_ok": False,
            "layer2_score": 0.0, "layer2_ok": False,
            "comment_compare_ok": False, "all_ok": False,
            "comments": [], "comment_steps": [], "valid_comments": [],
            "threshold": load_config()["similarity"].get("threshold", 0.7),
            "compare_mode": semantic_module.compare_mode(),
        }

    # 2. 获取 bug 单数据（根因 + 评论）
    bug_data = bug_source.load_bug_data(bugid, trigger_time, uploaded_rows)
    bug_root_cause = bug_data["root_cause"]
    comments = bug_data["comments"]
    # Jira 根因分析内容为空时直接过滤
    if not bug_root_cause:
        logger.info("bugid=%s Jira根因分析内容为空，跳过对比", bugid)
        return {
            "bugid": bugid, "doc_path": doc_path, "doc_steps": doc_steps,
            "ai_conclusion": conclusion_text, "bug_root_cause": "",
            "root_cause_score": 0.0, "root_cause_ok": False,
            "layer1_score": 0.0, "layer1_ok": False,
            "layer2_score": 0.0, "layer2_ok": False,
            "comment_compare_ok": False, "all_ok": False,
            "comments": comments, "comment_steps": [], "valid_comments": [],
            "threshold": load_config()["similarity"].get("threshold", 0.7),
            "compare_mode": semantic_module.compare_mode(),
            "skipped": True, "skip_reason": "Jira根因分析内容为空",
        }
    # 3. 步骤提取（不截断，用全部评论）
    comment_steps, valid_comments = comment_filter.extract_analysis_steps(comments)
    # 4. 根因对比：AI 分析结论 vs bug 单根因（通用根因跳过）
    sim_cfg = load_config()["similarity"]
    threshold = sim_cfg.get("threshold", 0.7)
    is_generic = _is_generic_rootcause(bug_root_cause)
    root_cause_score = 0.0
    root_cause_ok = True  # 通用根因默认通过
    if not is_generic and conclusion_text and bug_root_cause:
        root_cause_score = semantic_module.semantic_similarity(conclusion_text, bug_root_cause)
        root_cause_ok = root_cause_score >= threshold
    # 5. 评论对比：两层语义比对
    layer1_score = 0.0
    if valid_comments and comment_steps:
        layer1_scores = semantic_module.semantic_best_matches(
            [c for c in valid_comments if c.strip()], comment_steps
        )
        layer1_score = sum(layer1_scores) / len(layer1_scores) if layer1_scores else 0.0
    layer1_ok = layer1_score >= threshold
    joined_doc_steps = "，".join(doc_steps)
    layer2_score = semantic_module.semantic_similarity(bug_root_cause, joined_doc_steps) if joined_doc_steps else 0.0
    layer2_ok = layer2_score >= threshold
    comment_compare_ok = layer1_ok or layer2_ok
    # 通用根因时 all_ok 仅看评论对比，正常根因需两者都通过
    all_ok = (root_cause_ok and comment_compare_ok) if not is_generic else comment_compare_ok
    # 符合需求/符合预期类根因 → 追加 AI 结论到括号中（仅影响展示）
    display_root_cause = bug_root_cause
    if is_generic and conclusion_text:
        display_root_cause = f"{bug_root_cause}（{conclusion_text}）"
    logger.info("bugid=%s 对比完成: 根因=%.3f(%s), L1=%.3f(%s), L2=%.3f(%s), 通过=%s",
                bugid, root_cause_score, root_cause_ok, layer1_score, layer1_ok,
                layer2_score, layer2_ok, all_ok)
    return {
        "bugid": bugid, "doc_path": doc_path, "doc_steps": doc_steps,
        "ai_conclusion": conclusion_text, "bug_root_cause": display_root_cause,
        "root_cause_score": round(root_cause_score, 3), "root_cause_ok": root_cause_ok,
        "layer1_score": round(layer1_score, 3), "layer1_ok": layer1_ok,
        "layer2_score": round(layer2_score, 3), "layer2_ok": layer2_ok,
        "comment_compare_ok": comment_compare_ok, "all_ok": all_ok,
        "comments": comments, "comment_steps": comment_steps,
        "valid_comments": valid_comments, "threshold": threshold,
        "compare_mode": semantic_module.compare_mode(),
    }
```


## 四、语义相似度计算（semantic.py）

**文件**: `src/core/semantic.py` L40-L93

```python
def semantic_similarity(text_a: str, text_b: str) -> float:
    """计算两段文本的语义相似度（0~1）

    调用链：Diana LLM → 句向量模型 → TF-IDF 兜底
    """
    if not text_a or not text_b:
        return 0.0
    # Diana LLM 优先
    try:
        from src.clients import diana_client
        if diana_client.is_diana_mode() and diana_client.check_connectivity():
            score = diana_client.llm_similarity(text_a, text_b)
            if score > 0:
                return score
    except Exception as e:
        logger.debug("Diana LLM 相似度不可用，回退 embedding: %s", e)
    # 句向量模型兜底
    model = _get_model()
    if model is None:
        from src.core.similarity import cosine_of_texts
        return cosine_of_texts(text_a, text_b)
    vectors = model.encode([text_a, text_b], normalize_embeddings=True)
    return float((vectors[0] * vectors[1]).sum())


def semantic_best_matches(steps_a: list, steps_b: list) -> list:
    """逐条最佳匹配语义相似度：steps_a 每条取与 steps_b 各条的最大语义相似度

    模型不可用时回退 TF-IDF 逐对余弦；steps_b 为空时全部记 0 分。
    """
    if not steps_a:
        return []
    if not steps_b:
        return [0.0] * len(steps_a)
    model = _get_model()
    if model is None:
        from src.core.similarity import cosine_of_texts
        return [max(cosine_of_texts(a, b) for b in steps_b) for a in steps_a]
    vectors_a = model.encode(steps_a, normalize_embeddings=True)
    vectors_b = model.encode(steps_b, normalize_embeddings=True)
    matrix = vectors_a @ vectors_b.T
    return [float(row.max()) for row in matrix]


def compare_mode() -> str:
    """当前生效的对比方式，供页面展示"""
    try:
        from src.clients import diana_client
        if diana_client.is_diana_mode() and diana_client.check_connectivity():
            return f"Diana LLM 语义对比（{diana_client.get_model()}）"
    except Exception:
        pass
    return "句向量对比" if _get_model() is not None else "词面对比（LLM/语义模型均不可用，已回退）"
```


## 五、评论分析策略（filter.py）

**文件**: `src/core/filter.py` L441-L458

```python
COMMENT_ANALYSIS_STRATEGIES = {
    "log_focus": {
        "label": "偏日志分析",
        "instruction": "重点关注日志断层、错误码、异常堆栈和进程状态变化，从日志证据链角度分析"
    },
    "action_focus": {
        "label": "偏排查动作",
        "instruction": "重点关注排查步骤的时序、操作方法和排查方向变化，从排查流程角度分析"
    },
    "conclusion_focus": {
        "label": "偏结论判定",
        "instruction": "重点关注最终结论、问题定位状态和责任归属判定，从问题定性角度分析"
    },
    "impact_focus": {
        "label": "偏影响评估",
        "instruction": "重点关注问题对用户的影响范围、严重程度和修复优先级，从影响面角度分析"
    },
}
```


## 六、前端 UI 与交互（index.html）
### 6.1 置信度评测 UI 模板

**文件**: `src/web/index.html` L363-L424

```html
          <!-- Step 2: 置信度评测（自动，LLM语义对比） -->
          <div v-if="flow2Records.length" style="margin-bottom:16px;border-top:1px solid #eee;padding-top:14px">
            <div style="font-weight:700;font-size:14px;margin-bottom:8px">
              <el-tag type="success" size="small" effect="dark" style="margin-right:6px">自动</el-tag>
              ② 置信度评测（根因语义对比）
            </div>
            <div style="font-size:13px;color:#8a93a6;margin-bottom:8px">{{ flow2Conf.msg || '点击"开始执行"进行置信度评测' }}</div>
            <el-button type="primary" :loading="flow2Conf.running" @click="flow2RunConfidence"
              :disabled="flow2Conf.running" style="margin-bottom:10px">
              {{ flow2Conf.running ? '执行中...' : '开始执行' }}
            </el-button>
            <el-checkbox v-model="flow2AutoWrite" style="margin-left:8px;margin-bottom:10px">自动写入</el-checkbox>
            <el-checkbox v-model="flow2OnlyEmpty" style="margin-left:8px;margin-bottom:10px">仅置信度为空</el-checkbox>
            <!-- 进度统计 -->
            <div v-if="flow2Conf.total > 0" style="margin-bottom:8px">
              <el-progress :percentage="Math.round(flow2Conf.currentIndex / flow2Conf.total * 100)"
                :stroke-width="10" style="margin-bottom:6px"></el-progress>
              <div style="font-size:12px;color:#606266;display:flex;gap:16px;flex-wrap:wrap">
                <span>总数: <b>{{ flow2Conf.total }}</b></span>
                <span>进度: <b>{{ flow2Conf.currentIndex }}</b></span>
                <span style="color:#67c23a">达标: <b>{{ flow2Conf.passed }}</b></span>
                <span style="color:#e6a23c">未达标: <b>{{ flow2Conf.low }}</b></span>
                <span style="color:#f56c6c">跳过/失败: <b>{{ flow2Conf.failed }}</b></span>
              </div>
            </div>
            <!-- 逐条结果表格 -->
            <el-table v-if="flow2Conf.results.length" :data="flow2Conf.results" max-height="420"
              size="small" :row-class-name="({row}) => row.status === 'pass' ? 'success-row' : (row.status === 'low' ? 'warning-row' : '')">
              <el-table-column type="index" label="#" width="45"></el-table-column>
              <el-table-column prop="bugid" label="Jira号" width="120"></el-table-column>
              <el-table-column prop="score" label="置信度" width="90" align="center">
                <template #default="{row}">
                  <el-tag v-if="row.score === '无法判断'" type="info" size="small">无法判断</el-tag>
                  <el-tag v-else :type="row.score >= 0.7 ? 'success' : (row.score >= 0.4 ? 'warning' : 'danger')" size="small">{{ row.score }}</el-tag>
                </template>
              </el-table-column>
              <el-table-column prop="status" label="结果" width="70" align="center">
                <template #default="{row}">
                  <el-tag :type="row.status === 'pass' ? 'success' : (row.status === 'low' ? 'warning' : 'info')" size="small">
                    {{ row.status === 'pass' ? '达标' : (row.status === 'low' ? '未达标' : (row.status === 'skipped' ? '跳过' : '失败')) }}
                  </el-tag>
                </template>
              </el-table-column>
              <el-table-column prop="jira_rootcause" label="Jira根因(rootcause)" min-width="200" show-overflow-tooltip></el-table-column>
              <el-table-column prop="ai_rootcause" label="AI问题分析根因" min-width="200" show-overflow-tooltip></el-table-column>
              <el-table-column prop="msg" label="说明" min-width="160" show-overflow-tooltip>
                <template #default="{row}">
                  <span :style="row.status === 'fail' || row.status === 'skipped' ? 'color:#f56c6c' : ''">{{ row.msg || '-' }}</span>
                </template>
              </el-table-column>
            </el-table>
            <!-- 一键写入 + 仅置信度为空 -->
            <div v-if="flow2Conf.results.length && !flow2Conf.running" style="margin-top:12px;display:flex;gap:10px;flex-wrap:wrap;align-items:center">
              <el-button type="primary" :loading="flow2Conf.committing" @click="flow2CommitConfidence">
                一键写入（{{ flow2Conf.results.filter(r => (r.status === 'pass' || r.status === 'invalid' || r.status === 'low') && r.record_id && r.write_fields && Object.keys(r.write_fields).length > 0 && (!flow2OnlyEmpty || r.conf_empty)).length }}）
              </el-button>
              <el-checkbox v-model="flow2OnlyEmpty">仅置信度为空</el-checkbox>
            </div>
            <!-- 完成提示 -->
            <el-alert v-if="flow2Conf.doneMsg" type="success" :closable="false"
              :title="flow2Conf.doneMsg" style="margin-top:10px"></el-alert>
          </div>
```


### 6.2 置信度评测前端执行逻辑

**文件**: `src/web/index.html` L4311-L4360

```javascript
    flow2RunConfidence() {
      const conf = this.flow2Conf;
      conf.running = true; conf.total = 0; conf.currentIndex = 0; conf.passed = 0; conf.low = 0; conf.failed = 0;
      conf.results = []; conf.msg = '正在准备置信度评测...'; conf.doneMsg = '';
      // 过滤分析结果=成功的 Jira 号；若勾选"无分析结果不参与"则同样仅取成功记录
      let records = this.flow2Records;
      if (this.flow2NoAnalysis) {
        records = records.filter(r => (r['分析结果'] || '').trim() === '成功');
      }
      const jiraIds = records.map(r => r['jira号']).filter(Boolean).join(',');
      if (!jiraIds) {
        conf.running = false; conf.msg = '无可用的 Jira 号';
        return ElementPlus.ElMessage.warning('无可用的 Jira 号');
      }
      const params = new URLSearchParams();
      params.set('jira_ids', jiraIds);
      const url = '/api/test/confidence_batch_write?' + params.toString();
      const es = new EventSource(url);
      es.onmessage = (evt) => {
        const d = JSON.parse(evt.data);
        if (d.type === 'start') {
          conf.total = d.total;
          conf.msg = `共 ${d.total} 条待处理，阈值 ${d.threshold}`;
        } else if (d.type === 'progress') {
          conf.currentIndex = d.index;
          conf.results.push({ bugid: d.bugid, score: d.score || 0, status: d.status,
            jira_rootcause: d.jira_rootcause || '', ai_rootcause: d.ai_rootcause || '',
            record_id: d.record_id || '', write_fields: d.write_fields || {}, msg: d.msg || '',
            conf_empty: !!d.conf_empty });
          if (d.status === 'pass') conf.passed++;
          else if (d.status === 'invalid') conf.passed++;
          else if (d.status === 'low') conf.low++;
          else conf.failed++;
          conf.msg = `处理中 ${d.index}/${d.total}：${d.bugid}`;
        } else if (d.type === 'done') {
          conf.doneMsg = d.msg || '处理完成';
          conf.msg = `已完成: 达标${d.passed || 0}条, 写入${d.updated || 0}条`;
          conf.running = false; es.close();
          if (this.flow2AutoWrite) {
            this.$nextTick(() => this.flow2CommitConfidence());
          }
        } else if (d.type === 'error') {
          conf.msg = '错误: ' + (d.msg || '未知错误');
          conf.running = false; es.close();
        } else if (d.type === 'cancelled') {
          conf.msg = '已取消'; conf.running = false; es.close();
        }
      };
      es.onerror = () => { conf.msg = '连接中断'; conf.running = false; es.close(); };
    },
```


### 6.3 评论对比前端执行逻辑

**文件**: `src/web/index.html` L3776-L3807

```javascript
    async runCommentCompare() {
      if (!this.commentCompare.bugid) { ElementPlus.ElMessage.warning('请输入 Jira 号'); return; }
      this.running.commentCompare = true;
      this.commentCompare.results = [];
      this.commentCompare.selected = null;
      try {
        const result = await this.api('/api/test/comment_compare_strategies', {
          method: 'POST', body: JSON.stringify({ bugid: this.commentCompare.bugid })
        });
        const data = result.data || {};
        this.commentCompare.results = data.strategies || [];
        this.commentCompare.currentStyle = data.current_style || '';
        // 标记当前已选中的策略
        if (data.current_style) {
          const match = (data.strategies || []).find(s => s.instruction === data.current_style);
          if (match) this.commentCompare.selected = match.key;
        }
        ElementPlus.ElMessage.success(result.msg || '对比完成');
      } catch (e) { ElementPlus.ElMessage.error('对比失败: ' + e.message); }
      finally { this.running.commentCompare = false; }
    },
    // 选定风格偏好并保存到配置
    async saveStylePreference(key, label, instruction) {
      try {
        const result = await this.api('/api/test/save_style_preference', {
          method: 'POST', body: JSON.stringify({ strategy_key: key, instruction: instruction })
        });
        this.commentCompare.selected = key;
        this.commentCompare.currentStyle = instruction;
        ElementPlus.ElMessage.success(`已选定「${label}」风格，后续分析将按此侧重点执行`);
      } catch (e) { ElementPlus.ElMessage.error('保存失败: ' + e.message); }
    },
```
