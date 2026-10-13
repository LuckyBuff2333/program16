"""全量数据统计报告生成器
数据来源：多维表格 + Troubleshoot沉淀 + 触发时间缓存 + 批量执行CSV
功能：去重过滤（同一Jira先败后成算成功）+ ECharts图表 + 错误分析
"""
import sys, json, os, csv
sys.path.insert(0, '.')
from collections import Counter, defaultdict
from datetime import datetime

print("正在从多维表格获取数据...")
from src.clients import feishu_client
from src.config import load_config

cfg = load_config().get('feishu_bitable', {})
records = feishu_client.list_bitable_records(cfg['app_token'], cfg['table_id'], page_size=500)
print(f"多维表格: {len(records)} 条记录")

# ── 来源名称中文映射 ──
SOURCE_NAME_MAP = {
    'jira_analyze': '线上',
    'parseFullTicket': 'PC端',
    'feishu_bot': '飞书机器人',
    'online': '线上',
    'pc': 'PC端',
    'bot': '飞书机器人',
}
def _map_source(raw):
    """将触发来源原始值映射为中文名称"""
    if not raw:
        return '未知'
    return SOURCE_NAME_MAP.get(raw, SOURCE_NAME_MAP.get(raw.lower(), raw))

# ── 辅助函数 ──
def _text(val):
    if isinstance(val, str): return val.strip()
    if isinstance(val, list): return ''.join(str(x.get('text','')) for x in val if isinstance(x,dict)).strip()
    if isinstance(val, dict): return (val.get('text','') or val.get('value','')).strip()
    return str(val).strip() if val else ''

# ── 1. 解析所有记录 ──
parsed = []
for rec in records:
    f = rec.get('fields', {})
    jira = _text(f.get('jira号','')) or _text(f.get('Jira号',''))
    result = _text(f.get('分析结果',''))
    source = _map_source(_text(f.get('触发来源','')))
    err = _text(f.get('错误信息',''))
    finish = _text(f.get('分析完成时间',''))
    trigger_time = _text(f.get('分析问题时间',''))
    dur = _text(f.get('分析耗时',''))
    confidence = _text(f.get('结果置信度',''))
    err_type = _text(f.get('错误类型','')) or _text(f.get('错误分类',''))
    report_link = _text(f.get('AI分析结果(飞书链接)',''))
    rootcause = _text(f.get('rootcause',''))
    comment = _text(f.get('AI评论总结',''))
    parsed.append({
        'jira': jira, 'result': result, 'source': source, 'err': err[:200],
        'finish': finish, 'trigger_time': trigger_time, 'dur': dur,
        'confidence': confidence, 'err_type': err_type,
        'report_link': report_link, 'rootcause': rootcause,
    })

# ── 2. 去重过滤：同一Jira先败后成算成功 ──
jira_records = defaultdict(list)
for r in parsed:
    if r['jira']:
        jira_records[r['jira']].append(r)

dedup_results = {}  # jira -> '成功' or '失败'
dedup_details = {}  # jira -> final record
for jira, recs in jira_records.items():
    recs.sort(key=lambda x: x['finish'])
    has_success = any(r['result'] == '成功' for r in recs)
    if has_success:
        dedup_results[jira] = '成功'
        dedup_details[jira] = next(r for r in recs if r['result'] == '成功')
    else:
        dedup_results[jira] = '失败'
        dedup_details[jira] = recs[-1]

dedup_total = len(dedup_results)
dedup_success = sum(1 for v in dedup_results.values() if v == '成功')
dedup_fail = dedup_total - dedup_success
dedup_fixed = sum(1 for jira, recs in jira_records.items()
                  if len(recs) > 1 and any(r['result']=='成功' for r in recs)
                  and any(r['result']=='失败' for r in recs))

print(f"去重后: {dedup_total} 个独立Jira, 成功 {dedup_success} ({dedup_success/dedup_total*100:.1f}%), 失败 {dedup_fail}")
print(f"先败后成: {dedup_fixed} 个Jira被修正为成功")

# ── 3. 按来源统计（去重后） ──
source_dedup = defaultdict(lambda: {'success': 0, 'fail': 0})
for jira, result in dedup_results.items():
    src = dedup_details[jira]['source']
    if result == '成功': source_dedup[src]['success'] += 1
    else: source_dedup[src]['fail'] += 1

# ── 4. 按月份统计（去重后，按最终结果的首次成功/最后失败时间） ──
month_dedup = defaultdict(lambda: {'success': 0, 'fail': 0, 'total': 0})
for jira, result in dedup_results.items():
    finish = dedup_details[jira]['finish']
    month = finish[:7] if finish else 'unknown'
    month_dedup[month]['total'] += 1
    if result == '成功': month_dedup[month]['success'] += 1
    else: month_dedup[month]['fail'] += 1

# ── 5. 失败错误分析（去重后仅看最终失败的） ──
fail_errors = Counter()
fail_by_source = defaultdict(Counter)
for jira, result in dedup_results.items():
    if result == '失败':
        rec = dedup_details[jira]
        err = rec['err'][:80] if rec['err'] else '未知错误'
        # 归一化错误类型
        if '时间过滤后日志为空' in err: err_cat = '触发时间不准确（日志为空）'
        elif '超时' in err or 'timeout' in err.lower(): err_cat = '分析超时'
        elif '未找到有效的日志文件' in err: err_cat = '日志文件缺失/不支持'
        elif '429' in err: err_cat = '429限流'
        elif 'connection' in err.lower() or 'All connection' in err: err_cat = '网络连接异常'
        elif '服务有报错' in err: err_cat = '服务端报错'
        elif '模型调用失败' in err or 'reasoning' in err.lower(): err_cat = 'AI模型调用失败'
        elif 'No space' in err or 'Errno 28' in err: err_cat = '磁盘空间不足'
        elif err and err != '未知错误': err_cat = err[:40]
        else: err_cat = '未知错误'
        fail_errors[err_cat] += 1
        fail_by_source[rec['source']][err_cat] += 1

# ── 6. 触发时间问题统计 ──
troubleshoot = []
for fn in sorted(os.listdir('data/troubleshoot')):
    if not fn.endswith('.json'): continue
    with open(f'data/troubleshoot/{fn}', 'r') as f:
        try: troubleshoot.append(json.load(f))
        except: continue
ts_cats = Counter(d.get('category','未知') for d in troubleshoot)

# ── 7. 视频时间缓存 ──
with open('data/video_time_cache.json', 'r') as f:
    cache = json.load(f)

# ── 8. 每日成功/失败趋势（去重后按日） ──
daily_dedup = defaultdict(lambda: {'success': 0, 'fail': 0})
for jira, result in dedup_results.items():
    day = dedup_details[jira]['finish'][:10] if dedup_details[jira]['finish'] else 'unknown'
    if result == '成功': daily_dedup[day]['success'] += 1
    else: daily_dedup[day]['fail'] += 1

# ── 9. 耗时统计 ──
dur_list = []
for r in parsed:
    try:
        d = float(r['dur'])
        if d > 0: dur_list.append(d)
    except: pass

avg_dur = sum(dur_list)/len(dur_list) if dur_list else 0
med_dur = sorted(dur_list)[len(dur_list)//2] if dur_list else 0

# ── 10. 置信度分布 ──
conf_buckets = {'0-0.3': 0, '0.3-0.5': 0, '0.5-0.7': 0, '0.7-0.9': 0, '0.9-1.0': 0}
for jira, result in dedup_results.items():
    if result == '成功':
        try:
            c = float(dedup_details[jira]['confidence'])
            if c < 0.3: conf_buckets['0-0.3'] += 1
            elif c < 0.5: conf_buckets['0.3-0.5'] += 1
            elif c < 0.7: conf_buckets['0.5-0.7'] += 1
            elif c < 0.9: conf_buckets['0.7-0.9'] += 1
            else: conf_buckets['0.9-1.0'] += 1
        except: pass

# ── 11. 批量提交CSV统计 ──
batch_total = 0
batch_pending = 0
batch_429 = 0
for day_dir in sorted(os.listdir('docs')):
    day_path = os.path.join('docs', day_dir)
    if not os.path.isdir(day_path): continue
    for fn in os.listdir(day_path):
        if not fn.endswith('.csv'): continue
        with open(os.path.join(day_path, fn), 'r', encoding='utf-8-sig') as f:
            for row in csv.DictReader(f):
                batch_total += 1
                note = (row.get('备注','') or '').strip()
                if '后台处理' in note or '已启动' in note: batch_pending += 1
                elif '429' in note: batch_429 += 1

now = datetime.now().strftime('%Y-%m-%d %H:%M')

# ═══════════════════════════════════════════════════
# 生成 HTML 报告
# ═══════════════════════════════════════════════════
daily_days = sorted(daily_dedup.keys())
daily_success = [daily_dedup[d]['success'] for d in daily_days]
daily_fail = [daily_dedup[d]['fail'] for d in daily_days]

html = f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="UTF-8"><title>AI日志分析全量数据报告</title>
<script src="https://cdn.jsdelivr.net/npm/echarts@5/dist/echarts.min.js"></script>
<style>
* {{ margin:0; padding:0; box-sizing:border-box; }}
body {{ font-family: -apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif; background:#f0f2f5; color:#333; padding:20px; }}
.header {{ background:linear-gradient(135deg,#667eea,#764ba2); color:#fff; padding:30px 40px; border-radius:12px; margin-bottom:20px; }}
.header h1 {{ font-size:28px; margin-bottom:8px; }}
.header .sub {{ opacity:0.85; font-size:14px; }}
.kpi-row {{ display:grid; grid-template-columns:repeat(5,1fr); gap:16px; margin-bottom:20px; }}
.kpi {{ background:#fff; border-radius:10px; padding:20px; text-align:center; box-shadow:0 2px 8px rgba(0,0,0,.06); }}
.kpi .num {{ font-size:32px; font-weight:700; }}
.kpi .label {{ font-size:13px; color:#888; margin-top:4px; }}
.kpi .rate {{ font-size:18px; margin-top:2px; }}
.green {{ color:#52c41a; }} .red {{ color:#ff4d4f; }} .blue {{ color:#1890ff; }} .orange {{ color:#fa8c16; }} .purple {{ color:#722ed1; }}
.card {{ background:#fff; border-radius:10px; padding:24px; margin-bottom:20px; box-shadow:0 2px 8px rgba(0,0,0,.06); }}
.card h2 {{ font-size:18px; margin-bottom:16px; border-left:4px solid #667eea; padding-left:12px; }}
.chart-row {{ display:grid; grid-template-columns:1fr 1fr; gap:20px; margin-bottom:20px; }}
.chart {{ height:380px; }}
.chart-full {{ height:420px; }}
table {{ width:100%; border-collapse:collapse; font-size:13px; }}
th {{ background:#fafafa; padding:10px 12px; text-align:left; border-bottom:2px solid #eee; font-weight:600; }}
td {{ padding:8px 12px; border-bottom:1px solid #f0f0f0; }}
tr:hover {{ background:#fafafa; }}
.tag {{ display:inline-block; padding:2px 8px; border-radius:4px; font-size:12px; }}
.tag-ok {{ background:#f6ffed; color:#52c41a; border:1px solid #b7eb8f; }}
.tag-fail {{ background:#fff2f0; color:#ff4d4f; border:1px solid #ffccc7; }}
.tag-warn {{ background:#fffbe6; color:#fa8c16; border:1px solid #ffe58f; }}
.footer {{ text-align:center; color:#aaa; font-size:12px; padding:20px; }}
</style></head><body>
<div class="header">
  <h1>AI日志分析 · 全量数据统计报告</h1>
  <div class="sub">数据来源：多维表格 {len(records)} 条 + Troubleshoot {len(troubleshoot)} 条 + 视频缓存 {len(cache)} 条 + 批量提交 {batch_total} 条 &nbsp;|&nbsp; 生成时间: {now}</div>
</div>

<!-- KPI -->
<div class="kpi-row">
  <div class="kpi"><div class="num blue">{len(records)}</div><div class="label">多维表格总记录</div></div>
  <div class="kpi"><div class="num purple">{dedup_total}</div><div class="label">去重后独立Jira</div><div class="rate green">{dedup_success/dedup_total*100:.1f}% 成功率</div></div>
  <div class="kpi"><div class="num green">{dedup_success}</div><div class="label">成功（含先败后成 {dedup_fixed}）</div></div>
  <div class="kpi"><div class="num red">{dedup_fail}</div><div class="label">最终失败</div></div>
  <div class="kpi"><div class="num orange">{len(troubleshoot)}</div><div class="label">Troubleshoot沉淀</div><div class="rate">{len(cache)} 视频缓存</div></div>
</div>

<!-- 图表行1：成功率饼图 + 来源饼图 -->
<div class="chart-row">
  <div class="card"><h2>去重后成功/失败分布</h2><div id="pie_result" class="chart"></div></div>
  <div class="card"><h2>触发来源分布（去重后）</h2><div id="pie_source" class="chart"></div></div>
</div>

<!-- 图表行2：月度趋势 + 日趋势 -->
<div class="chart-row">
  <div class="card"><h2>月度成功率趋势（去重后）</h2><div id="bar_month" class="chart"></div></div>
  <div class="card"><h2>每日成功/失败趋势（去重后）</h2><div id="line_daily" class="chart"></div></div>
</div>

<!-- 图表行3：错误分类 + 置信度分布 -->
<div class="chart-row">
  <div class="card"><h2>失败错误分类（去重后 {dedup_fail} 条）</h2><div id="bar_error" class="chart"></div></div>
  <div class="card"><h2>成功记录置信度分布</h2><div id="bar_conf" class="chart"></div></div>
</div>

<!-- Troubleshoot 分析 -->
<div class="card"><h2>Troubleshoot 数据沉淀分析（{len(troubleshoot)} 条）</h2>
<div class="chart-row" style="margin-bottom:0">
  <div><div id="pie_ts" class="chart"></div></div>
  <div>
    <table>
    <tr><th>错误分类</th><th>数量</th><th>占比</th><th>典型Jira</th></tr>
"""

# Troubleshoot表格
ts_samples = defaultdict(list)
for d in troubleshoot:
    cat = d.get('category','未知')
    if len(ts_samples[cat]) < 3:
        ts_samples[cat].append(d.get('bugid',''))
for cat, cnt in ts_cats.most_common():
    pct = cnt/len(troubleshoot)*100
    tag_cls = 'tag-fail' if cnt > 50 else ('tag-warn' if cnt > 10 else 'tag-ok')
    samples = ', '.join(ts_samples.get(cat, []))
    html += f'    <tr><td>{cat}</td><td><b>{cnt}</b></td><td><span class="tag {tag_cls}">{pct:.1f}%</span></td><td style="font-size:11px;color:#888">{samples}</td></tr>\n'

html += """    </table>
  </div>
</div></div>

<!-- 错误详细分析 -->
<div class="card"><h2>失败错误详细分析（去重后最终失败）</h2>
<table>
<tr><th>错误类型</th><th>数量</th><th>占比</th><th>影响来源</th></tr>
"""
for err, cnt in fail_errors.most_common(15):
    pct = cnt/dedup_fail*100
    sources_affected = ', '.join(s for s, errs in fail_by_source.items() if err in errs)
    tag_cls = 'tag-fail' if cnt > 30 else ('tag-warn' if cnt > 10 else 'tag-ok')
    html += f'<tr><td>{err}</td><td><b>{cnt}</b></td><td><span class="tag {tag_cls}">{pct:.1f}%</span></td><td style="font-size:11px;color:#888">{sources_affected}</td></tr>\n'

html += f"""</table></div>

<!-- 来源×结果明细 -->
<div class="card"><h2>触发来源×成功率明细（去重后）</h2>
<table>
<tr><th>触发来源</th><th>总数</th><th>成功</th><th>失败</th><th>成功率</th></tr>
"""
for src, counts in sorted(source_dedup.items(), key=lambda x: -(x[1]['success']+x[1]['fail'])):
    total = counts['success'] + counts['fail']
    rate = counts['success']/total*100 if total else 0
    html += f'<tr><td>{src}</td><td>{total}</td><td class="green">{counts["success"]}</td><td class="red">{counts["fail"]}</td><td><b>{rate:.1f}%</b></td></tr>\n'

html += f"""</table></div>

<!-- 月度明细 -->
<div class="card"><h2>月度明细（去重后）</h2>
<table>
<tr><th>月份</th><th>总数</th><th>成功</th><th>失败</th><th>成功率</th><th>环比</th></tr>
"""
prev_rate = None
for m in sorted(month_dedup.keys()):
    s = month_dedup[m]
    rate = s['success']/s['total']*100 if s['total'] else 0
    delta = ''
    if prev_rate is not None:
        diff = rate - prev_rate
        delta = f'<span class="{"green" if diff>0 else "red"}">{"+" if diff>0 else ""}{diff:.1f}%</span>'
    prev_rate = rate
    html += f'<tr><td>{m}</td><td>{s["total"]}</td><td class="green">{s["success"]}</td><td class="red">{s["fail"]}</td><td><b>{rate:.1f}%</b></td><td>{delta}</td></tr>\n'

html += f"""</table></div>

<div class="footer">AI日志分析全量数据报告 · 数据截至 {now} · 去重规则：同一Jira有成功记录则计为成功</div>

<script>
// === 饼图：成功/失败 ===
echarts.init(document.getElementById('pie_result')).setOption({{
  tooltip: {{ trigger:'item', formatter:'{{b}}: {{c}} ({{d}}%)' }},
  series: [{{ type:'pie', radius:['40%','70%'], label:{{ position:'inside', formatter:'{{b}}\\n{{c}} ({{d}}%)', color:'#fff', fontSize:14, fontWeight:'bold' }},
    data:[
      {{value:{dedup_success}, name:'成功', itemStyle:{{color:'#52c41a'}}}},
      {{value:{dedup_fail}, name:'失败', itemStyle:{{color:'#ff4d4f'}}}},
    ]
  }}]
}});

// === 饼图：来源分布 ===
var sourceData = [{','.join(f'{{value:{v["success"]+v["fail"]}, name:"{_map_source(k)}"}}' for k,v in source_dedup.items())}];
echarts.init(document.getElementById('pie_source')).setOption({{
  tooltip: {{ trigger:'item', formatter:'{{b}}: {{c}} ({{d}}%)' }},
  series: [{{ type:'pie', radius:['40%','70%'], label:{{ position:'inside', formatter:'{{b}}\\n{{c}} ({{d}}%)', color:'#fff', fontSize:13, fontWeight:'bold' }},
    data: sourceData,
    color: ['#1890ff','#52c41a','#fa8c16','#722ed1','#13c2c2']
  }}]
}});

// === 柱状图：月度 ===
var months = [{','.join(f'"{m}"' for m in sorted(month_dedup.keys()))}];
var mSuccess = [{','.join(str(month_dedup[m]['success']) for m in sorted(month_dedup.keys()))}];
var mFail = [{','.join(str(month_dedup[m]['fail']) for m in sorted(month_dedup.keys()))}];
echarts.init(document.getElementById('bar_month')).setOption({{
  tooltip: {{ trigger:'axis' }},
  legend: {{ data:['成功','失败'] }},
  xAxis: {{ type:'category', data:months }},
  yAxis: {{ type:'value' }},
  series: [
    {{ name:'成功', type:'bar', stack:'total', data:mSuccess, itemStyle:{{color:'#52c41a'}} }},
    {{ name:'失败', type:'bar', stack:'total', data:mFail, itemStyle:{{color:'#ff4d4f'}} }}
  ]
}});

// === 折线图：每日趋势 ===
var days = [{','.join(f'"{d}"' for d in daily_days)}];
var dSuccess = [{','.join(str(x) for x in daily_success)}];
var dFail = [{','.join(str(x) for x in daily_fail)}];
echarts.init(document.getElementById('line_daily')).setOption({{
  tooltip: {{ trigger:'axis' }},
  legend: {{ data:['成功','失败'] }},
  xAxis: {{ type:'category', data:days, axisLabel:{{rotate:45}} }},
  yAxis: {{ type:'value' }},
  series: [
    {{ name:'成功', type:'line', smooth:true, data:dSuccess, itemStyle:{{color:'#52c41a'}}, areaStyle:{{color:'rgba(82,196,26,0.1)'}} }},
    {{ name:'失败', type:'line', smooth:true, data:dFail, itemStyle:{{color:'#ff4d4f'}}, areaStyle:{{color:'rgba(255,77,79,0.1)'}} }}
  ]
}});

// === 柱状图：错误分类 ===
var errLabels = [{','.join(f'"{e[0]}"' for e in fail_errors.most_common(10))}];
var errValues = [{','.join(str(e[1]) for e in fail_errors.most_common(10))}];
echarts.init(document.getElementById('bar_error')).setOption({{
  tooltip: {{ trigger:'axis' }},
  xAxis: {{ type:'category', data:errLabels, axisLabel:{{rotate:30, fontSize:11}} }},
  yAxis: {{ type:'value' }},
  series: [{{ type:'bar', data:errValues, itemStyle:{{ color: function(p){{ var colors=['#ff4d4f','#ff7a45','#ffa940','#ffc53d','#ffec3d','#bae637','#73d13d','#36cfc9','#597ef7','#9254de']; return colors[p.dataIndex%colors.length]; }} }} }}]
}});

// === 柱状图：置信度分布 ===
echarts.init(document.getElementById('bar_conf')).setOption({{
  tooltip: {{ trigger:'axis' }},
  xAxis: {{ type:'category', data:['0-0.3','0.3-0.5','0.5-0.7','0.7-0.9','0.9-1.0'] }},
  yAxis: {{ type:'value' }},
  series: [{{ type:'bar', data:[{conf_buckets['0-0.3']},{conf_buckets['0.3-0.5']},{conf_buckets['0.5-0.7']},{conf_buckets['0.7-0.9']},{conf_buckets['0.9-1.0']}],
    itemStyle:{{ color: function(p){{ return ['#ff4d4f','#ffa940','#ffc53d','#73d13d','#52c41a'][p.dataIndex]; }} }}
  }}]
}});

// === 饼图：Troubleshoot分类 ===
echarts.init(document.getElementById('pie_ts')).setOption({{
  tooltip: {{ trigger:'item', formatter:'{{b}}: {{c}} ({{d}}%)' }},
  series: [{{ type:'pie', radius:['35%','65%'], label:{{ position:'inside', formatter:'{{b}}\\n{{c}} ({{d}}%)', color:'#fff', fontSize:12, fontWeight:'bold' }},
    data:[{','.join(f'{{value:{v}, name:"{k}"}}' for k,v in ts_cats.most_common())}],
    color: ['#ff4d4f','#fa8c16','#ffc53d','#73d13d']
  }}]
}});
</script>
</body></html>"""

report_path = 'reports/full_data_report.html'
os.makedirs('reports', exist_ok=True)
with open(report_path, 'w', encoding='utf-8') as f:
    f.write(html)
print(f"\n报告已生成: {report_path}")
