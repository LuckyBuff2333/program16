"""从云端多维表格读取 10-10 ~ 10-11 批量执行记录，生成带成功/失败耗时拆分的墙钟报告"""
import sys, os, json, re
from datetime import datetime, timedelta
from collections import defaultdict
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from src.config import load_config
from src.api.routes.shared import bitable_text as _bitable_text
from src.clients import feishu_client

# ===== 1. 读取云端数据 =====
cfg = load_config().get("feishu_bitable", {})
records = feishu_client.list_bitable_records(cfg["app_token"], cfg["table_id"])

# 筛选 10-10 和 10-11 的记录
target_dates = {"2026/10/10", "2026/10/11", "2026-10-10", "2026-10-11"}
filtered = []
for rec in records:
    f = rec.get("fields", {})
    date_str = _bitable_text(f.get("分析日期", ""))
    if date_str in target_dates:
        jira = _bitable_text(f.get(cfg.get("bugid_field", "jira号"), ""))
        done_time_str = _bitable_text(f.get("分析完成时间", ""))
        result = _bitable_text(f.get("分析结果", ""))
        duration_str = _bitable_text(f.get("分析耗时", ""))
        err_msg = _bitable_text(f.get("错误信息", ""))
        source = _bitable_text(f.get("触发来源", ""))
        # 解析耗时（秒）
        dur_sec = 0
        if duration_str:
            m = re.match(r'([\d.]+)', duration_str)
            if m:
                dur_sec = float(m.group(1))
        # 解析完成时间
        done_dt = None
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y/%m/%d %H:%M:%S"):
            try:
                done_dt = datetime.strptime(done_time_str, fmt)
                break
            except (ValueError, TypeError):
                pass
        if jira and done_dt:
            filtered.append({
                "jira": jira, "date": date_str, "done_dt": done_dt,
                "done_time": done_time_str, "result": result,
                "duration_sec": dur_sec, "err_msg": err_msg, "source": source,
            })

print(f"筛选到 {len(filtered)} 条记录 (10-10 + 10-11)")

# ===== 2. 按日期分组，再按时间窗口识别批次 =====
by_date = defaultdict(list)
for r in filtered:
    d = r["date"].replace("-", "/")
    # 归一化日期
    if "10/10" in d:
        by_date["10-10"].append(r)
    elif "10/11" in d:
        by_date["10-11"].append(r)

def identify_batches(records_list, expected_batch_size=50):
    """按完成时间聚类识别批次：找最大的时间间隔作为批次分割点，
    并用最小间隔阈值过滤噪音（两个记录间隔 < 2分钟的不可能是批次边界）"""
    if not records_list:
        return []
    if len(records_list) <= expected_batch_size * 1.3:
        return [records_list]
    sorted_recs = sorted(records_list, key=lambda r: r["done_dt"])
    # 计算相邻记录的时间间隔
    gaps = []
    for i in range(1, len(sorted_recs)):
        gap_sec = (sorted_recs[i]["done_dt"] - sorted_recs[i-1]["done_dt"]).total_seconds()
        gaps.append((gap_sec, i))
    # 估计批次数（向上取整，避免合并过多）
    n_batches = max(2, round(len(records_list) / expected_batch_size))
    # 取 top (n_batches-1) 个最大间隔，但要求间隔 > 2分钟
    candidates = [(g, i) for g, i in gaps if g > 120]  # 至少2分钟间隔
    split_points = sorted(candidates, key=lambda x: -x[0])[:n_batches - 1]
    split_indices = sorted([idx for _, idx in split_points])
    # 按分割点切分
    batches = []
    prev = 0
    for idx in split_indices:
        batches.append(sorted_recs[prev:idx])
        prev = idx
    batches.append(sorted_recs[prev:])
    return [b for b in batches if b]

# ===== 3. 计算每个批次的统计 =====
all_batch_stats = []
for date_key in ["10-10", "10-11"]:
    day_records = by_date.get(date_key, [])
    batches = identify_batches(day_records)
    for idx, batch_recs in enumerate(batches, 1):
        ok_recs = [r for r in batch_recs if r["result"] == "成功"]
        fail_recs = [r for r in batch_recs if r["result"] != "成功"]
        all_times = [r["done_dt"] for r in batch_recs]
        ok_times = [r["done_dt"] for r in ok_recs]
        fail_times = [r["done_dt"] for r in fail_recs]
        # 墙钟时间：最早完成 → 最晚完成
        first_done = min(all_times)
        last_done = max(all_times)
        wall_min = (last_done - first_done).total_seconds() / 60
        # 成功总耗时（秒）
        ok_total_sec = sum(r["duration_sec"] for r in ok_recs)
        fail_total_sec = sum(r["duration_sec"] for r in fail_recs)
        # 成功/失败的完成时间跨度
        ok_wall_min = (max(ok_times) - min(ok_times)).total_seconds() / 60 if ok_times else 0
        fail_wall_min = (max(fail_times) - min(fail_times)).total_seconds() / 60 if fail_times else 0
        # 首个来源标识
        sources = set(r["source"] for r in batch_recs if r["source"])
        source_label = "/".join(sources) if sources else "unknown"
        batch_name = f"r{idx}" if len(batches) > 1 else "batch"
        all_batch_stats.append({
            "date": date_key, "name": batch_name,
            "total": len(batch_recs), "ok": len(ok_recs), "fail": len(fail_recs),
            "first_done": first_done.strftime("%H:%M:%S"),
            "last_done": last_done.strftime("%H:%M:%S"),
            "wall_min": round(wall_min, 1),
            "ok_wall_min": round(ok_wall_min, 1),
            "fail_wall_min": round(fail_wall_min, 1),
            "ok_total_sec": round(ok_total_sec, 1),
            "fail_total_sec": round(fail_total_sec, 1),
            "ok_avg_sec": round(ok_total_sec / len(ok_recs), 1) if ok_recs else 0,
            "fail_avg_sec": round(fail_total_sec / len(fail_recs), 1) if fail_recs else 0,
            "source": source_label,
        })

print(f"\n识别到 {len(all_batch_stats)} 个批次:")
for b in all_batch_stats:
    print(f"  {b['date']} {b['name']}: {b['total']}条(成功{b['ok']}/失败{b['fail']}) "
          f"墙钟{b['wall_min']}min 成功跨度{b['ok_wall_min']}min 失败跨度{b['fail_wall_min']}min "
          f"成功总耗时{b['ok_total_sec']/60:.1f}min 失败总耗时{b['fail_total_sec']/60:.1f}min")

# ===== 4. 生成 HTML =====
# 按日期分组数据
batches_10 = [b for b in all_batch_stats if b["date"] == "10-10"]
batches_11 = [b for b in all_batch_stats if b["date"] == "10-11"]

total_bugs = sum(b["total"] for b in all_batch_stats)
total_ok = sum(b["ok"] for b in all_batch_stats)
total_fail = sum(b["fail"] for b in all_batch_stats)
avg_wall = round(sum(b["wall_min"] for b in batches_11) / len(batches_11), 1) if batches_11 else 0
min_wall_b = min(batches_11, key=lambda b: b["wall_min"]) if batches_11 else None
max_wall_b = max(batches_11, key=lambda b: b["wall_min"]) if batches_11 else None

html = f'''<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>批次墙钟耗时报告 · 10-10 ~ 10-11 · 云端数据</title>
<script src="https://cdn.jsdelivr.net/npm/echarts@5/dist/echarts.min.js"></script>
<style>
:root{{--bg:#0f1117;--card:#1a1d2e;--border:#2a2d3e;--text:#e2e8f0;--muted:#8892a8;--accent:#6366f1;--green:#22c55e;--red:#ef4444;--orange:#f59e0b;--blue:#3b82f6;--cyan:#06b6d4;--purple:#a78bfa}}
*{{margin:0;padding:0;box-sizing:border-box}}
body{{font-family:-apple-system,'Segoe UI','PingFang SC','Microsoft YaHei',sans-serif;background:var(--bg);color:var(--text);line-height:1.7;padding:20px}}
.container{{max-width:1440px;margin:0 auto}}
h1{{font-size:26px;font-weight:700;background:linear-gradient(135deg,#6366f1,#a78bfa);-webkit-background-clip:text;background-clip:text;-webkit-text-fill-color:transparent}}
.subtitle{{color:var(--muted);font-size:13px;margin:4px 0 24px}}
.grid-2{{display:grid;grid-template-columns:1fr 1fr;gap:16px}}
.grid-3{{display:grid;grid-template-columns:1fr 1fr 1fr;gap:16px}}
.grid-4{{display:grid;grid-template-columns:repeat(4,1fr);gap:12px}}
.grid-5{{display:grid;grid-template-columns:repeat(5,1fr);gap:12px}}
@media(max-width:1000px){{.grid-2,.grid-3,.grid-4,.grid-5{{grid-template-columns:1fr 1fr}}}}
.card{{background:var(--card);border:1px solid var(--border);border-radius:12px;padding:18px}}
.card-label{{font-size:11px;color:var(--muted);text-transform:uppercase;letter-spacing:.5px}}
.card-value{{font-size:28px;font-weight:700;margin:4px 0}}
.card-sub{{font-size:11px;color:var(--muted)}}
.section{{margin:28px 0}}
.section-title{{font-size:16px;font-weight:600;margin-bottom:14px;display:flex;align-items:center;gap:8px}}
.section-title::before{{content:'';display:inline-block;width:4px;height:18px;background:var(--accent);border-radius:2px}}
.chart-box{{background:var(--card);border:1px solid var(--border);border-radius:12px;padding:16px;margin-bottom:20px}}
.chart-title{{font-size:14px;font-weight:600;margin-bottom:10px}}
.chart-sub{{font-size:11px;color:var(--muted);margin-bottom:8px}}
table{{width:100%;border-collapse:collapse;font-size:12px}}
th,td{{padding:8px 10px;text-align:left;border-bottom:1px solid var(--border)}}
th{{color:var(--muted);font-weight:600;font-size:11px;text-transform:uppercase;letter-spacing:.3px;position:sticky;top:0;background:var(--card)}}
tr:hover{{background:rgba(99,102,241,.06)}}
.tag{{display:inline-block;padding:2px 8px;border-radius:4px;font-size:10px;font-weight:600}}
.tag-ok{{background:rgba(34,197,94,.15);color:var(--green)}}
.tag-fail{{background:rgba(239,68,68,.15);color:var(--red)}}
.tag-warn{{background:rgba(245,158,11,.15);color:var(--orange)}}
.tag-info{{background:rgba(59,130,246,.15);color:var(--blue)}}
.green{{color:var(--green)}}.red{{color:var(--red)}}.orange{{color:var(--orange)}}.blue{{color:var(--blue)}}.cyan{{color:var(--cyan)}}.purple{{color:var(--purple)}}
.conclusion{{background:linear-gradient(135deg,rgba(99,102,241,.08),rgba(167,139,250,.05));border:1px solid rgba(99,102,241,.25);border-radius:12px;padding:20px;margin-top:24px}}
.conclusion h3{{font-size:15px;color:var(--accent);margin-bottom:12px}}
.conclusion li{{margin:6px 0;font-size:13px;line-height:1.7}}
.table-wrap{{max-height:520px;overflow:auto;border-radius:8px;border:1px solid var(--border)}}
.highlight-box{{background:rgba(34,197,94,.08);border:1px solid rgba(34,197,94,.2);border-radius:10px;padding:16px;text-align:center}}
.highlight-box .val{{font-size:36px;font-weight:800;color:var(--green)}}
.highlight-box .lbl{{font-size:12px;color:var(--muted);margin-top:4px}}
</style>
</head>
<body>
<div class="container">
<h1>批次墙钟耗时报告 · 10-10 ~ 10-11</h1>
<p class="subtitle">墙钟时间 = 首个完成 → 最后一个完成的时间差 · 成功耗时 = 成功记录的完成时间跨度 · 失败耗时 = 失败记录的完成时间跨度 · 数据源：飞书多维表格 · {datetime.now().strftime("%Y-%m-%d %H:%M")}</p>

<div class="grid-5">
  <div class="card"><div class="card-label">10-11 批次数</div><div class="card-value cyan">{len(batches_11)}</div><div class="card-sub">自动聚类识别</div></div>
  <div class="card"><div class="card-label">总 Bug</div><div class="card-value blue">{total_bugs}</div><div class="card-sub">成功 {total_ok} / 失败 {total_fail}</div></div>
  <div class="highlight-box"><div class="val">{avg_wall}<span style="font-size:16px">min</span></div><div class="lbl">10-11 平均每批次墙钟</div></div>
  <div class="card"><div class="card-label">最短批次</div><div class="card-value green">{min_wall_b['wall_min'] if min_wall_b else '-'}<span style="font-size:14px">min</span></div><div class="card-sub">{min_wall_b['name'] if min_wall_b else ''} ({min_wall_b['first_done'] if min_wall_b else ''})</div></div>
  <div class="card"><div class="card-label">最长批次</div><div class="card-value orange">{max_wall_b['wall_min'] if max_wall_b else '-'}<span style="font-size:14px">min</span></div><div class="card-sub">{max_wall_b['name'] if max_wall_b else ''} ({max_wall_b['first_done'] if max_wall_b else ''})</div></div>
</div>

<div class="section">
  <div class="section-title">图表分析</div>
  <div class="chart-box">
    <div class="chart-title">每批次墙钟时间 + 成功/失败时间跨度拆解</div>
    <div class="chart-sub">蓝色=成功记录跨度 · 红色=失败记录跨度 · 折线=成功率(%)</div>
    <div id="chart_wallclock" style="height:420px"></div>
  </div>
  <div class="grid-2">
    <div class="chart-box">
      <div class="chart-title">每批次成功 vs 失败总耗时（分析耗时字段累加）</div>
      <div class="chart-sub">绿色=成功总耗时(min) · 红色=失败总耗时(min)</div>
      <div id="chart_duration" style="height:360px"></div>
    </div>
    <div class="chart-box">
      <div class="chart-title">10-11 各批次多维表格分析成功率</div>
      <div id="chart_success_rate" style="height:360px"></div>
    </div>
  </div>
  <div class="chart-box">
    <div class="chart-title">10-11 各批次成功/失败完成时间跨度对比</div>
    <div class="chart-sub">绿色=成功跨度(min) · 红色=失败跨度(min) · 灰色=总墙钟(min)</div>
    <div id="chart_breakdown" style="height:360px"></div>
  </div>
</div>

<div class="section">
  <div class="section-title">批次详情（墙钟 + 成功/失败耗时拆分）</div>
  <div class="table-wrap">
  <table>
    <thead><tr>
      <th>#</th><th>批次</th><th>来源</th>
      <th>总数</th><th>成功</th><th>失败</th><th>成功率</th>
      <th>首个完成</th><th>最后完成</th><th>墙钟时间</th>
      <th>成功跨度</th><th>失败跨度</th>
      <th>成功总耗时</th><th>失败总耗时</th>
      <th>单Bug均耗时</th><th>状态</th>
    </tr></thead>
    <tbody id="batchTable"></tbody>
  </table>
  </div>
</div>

<div class="conclusion">
  <h3>核心结论</h3>
  <ol id="conclusions"></ol>
</div>

</div>
<script>
const batches = {json.dumps(all_batch_stats, ensure_ascii=False)};
const b11 = batches.filter(b => b.date === '10-11');
const b10 = batches.filter(b => b.date === '10-10');
const b11Names = b11.map(b => b.name);

// 图1：墙钟 + 成功率
const c1 = echarts.init(document.getElementById('chart_wallclock'));
c1.setOption({{
  tooltip:{{trigger:'axis',formatter:function(p){{
    const b = b11[p[0].dataIndex];
    if(!b) return '';
    return `<b>${{b.name}}</b><br/>墙钟: ${{b.wall_min}}min<br/>成功跨度: ${{b.ok_wall_min}}min<br/>失败跨度: ${{b.fail_wall_min}}min<br/>成功: ${{b.ok}} / 失败: ${{b.fail}}`;
  }}}},
  legend:{{data:['成功跨度(min)','失败跨度(min)','成功率(%)'],textStyle:{{color:'#8892a8'}}}},
  grid:{{left:55,right:55,bottom:50,top:45}},
  xAxis:{{type:'category',data:b11Names,axisLabel:{{color:'#8892a8',fontSize:12}},axisLine:{{lineStyle:{{color:'#2a2d3e'}}}}}},
  yAxis:[
    {{type:'value',name:'分钟',nameTextStyle:{{color:'#8892a8'}},axisLabel:{{color:'#8892a8'}},splitLine:{{lineStyle:{{color:'#1e2030'}}}}}},
    {{type:'value',name:'成功率%',max:100,nameTextStyle:{{color:'#8892a8'}},axisLabel:{{color:'#8892a8',formatter:'{{value}}%'}},splitLine:{{show:false}}}}
  ],
  series:[
    {{name:'成功跨度(min)',type:'bar',stack:'wall',data:b11.map(b=>b.ok_wall_min),itemStyle:{{color:'#22c55e'}},barWidth:'50%'}},
    {{name:'失败跨度(min)',type:'bar',stack:'wall',data:b11.map(b=>b.fail_wall_min),itemStyle:{{color:'#ef4444'}}}},
    {{name:'成功率(%)',type:'line',yAxisIndex:1,data:b11.map(b=>b.total>0?+(b.ok/b.total*100).toFixed(1):0),
     lineStyle:{{color:'#a78bfa',width:2}},symbol:'circle',symbolSize:7,itemStyle:{{color:'#a78bfa'}},
     label:{{show:true,color:'#a78bfa',fontSize:10,formatter:p=>p.value+'%'}}}}
  ]
}});

// 图2：成功 vs 失败总耗时
const c2 = echarts.init(document.getElementById('chart_duration'));
c2.setOption({{
  tooltip:{{trigger:'axis',formatter:function(p){{
    const b = b11[p[0].dataIndex]; if(!b) return '';
    return `<b>${{b.name}}</b><br/>成功总耗时: ${{(b.ok_total_sec/60).toFixed(1)}}min<br/>失败总耗时: ${{(b.fail_total_sec/60).toFixed(1)}}min`;
  }}}},
  legend:{{data:['成功总耗时(min)','失败总耗时(min)'],textStyle:{{color:'#8892a8'}}}},
  grid:{{left:55,right:15,bottom:50,top:40}},
  xAxis:{{type:'category',data:b11Names,axisLabel:{{color:'#8892a8'}},axisLine:{{lineStyle:{{color:'#2a2d3e'}}}}}},
  yAxis:{{type:'value',name:'分钟',nameTextStyle:{{color:'#8892a8'}},axisLabel:{{color:'#8892a8'}},splitLine:{{lineStyle:{{color:'#1e2030'}}}}}},
  series:[
    {{name:'成功总耗时(min)',type:'bar',data:b11.map(b=>+(b.ok_total_sec/60).toFixed(1)),itemStyle:{{color:'#22c55e'}},barWidth:'35%',
     label:{{show:true,position:'top',color:'#22c55e',fontSize:10,formatter:p=>p.value}}}},
    {{name:'失败总耗时(min)',type:'bar',data:b11.map(b=>+(b.fail_total_sec/60).toFixed(1)),itemStyle:{{color:'#ef4444'}},barWidth:'35%',
     label:{{show:true,position:'top',color:'#ef4444',fontSize:10,formatter:p=>p.value}}}}
  ]
}});

// 图3：成功率
const c3 = echarts.init(document.getElementById('chart_success_rate'));
c3.setOption({{
  tooltip:{{trigger:'axis'}},
  grid:{{left:45,right:15,bottom:50,top:20}},
  xAxis:{{type:'category',data:b11Names,axisLabel:{{color:'#8892a8'}},axisLine:{{lineStyle:{{color:'#2a2d3e'}}}}}},
  yAxis:{{type:'value',max:100,axisLabel:{{formatter:'{{value}}%',color:'#8892a8'}},splitLine:{{lineStyle:{{color:'#1e2030'}}}}}},
  series:[{{type:'bar',data:b11.map(b=>{{
    const r=b.total>0?+(b.ok/b.total*100).toFixed(1):0;
    return {{value:r,itemStyle:{{color:r>=80?'#22c55e':r>=60?'#3b82f6':r>=40?'#f59e0b':'#ef4444'}}}};
  }}),barWidth:'60%',label:{{show:true,position:'top',color:'#e2e8f0',fontSize:10,formatter:p=>p.value+'%'}}}}]
}});

// 图4：成功/失败跨度对比
const c4 = echarts.init(document.getElementById('chart_breakdown'));
c4.setOption({{
  tooltip:{{trigger:'axis',formatter:function(p){{
    const b = b11[p[0].dataIndex]; if(!b) return '';
    return `<b>${{b.name}}</b><br/>成功跨度: ${{b.ok_wall_min}}min<br/>失败跨度: ${{b.fail_wall_min}}min<br/>总墙钟: ${{b.wall_min}}min`;
  }}}},
  legend:{{data:['成功跨度','失败跨度','总墙钟'],textStyle:{{color:'#8892a8'}}}},
  grid:{{left:55,right:15,bottom:50,top:40}},
  xAxis:{{type:'category',data:b11Names,axisLabel:{{color:'#8892a8'}},axisLine:{{lineStyle:{{color:'#2a2d3e'}}}}}},
  yAxis:{{type:'value',name:'分钟',nameTextStyle:{{color:'#8892a8'}},axisLabel:{{color:'#8892a8'}},splitLine:{{lineStyle:{{color:'#1e2030'}}}}}},
  series:[
    {{name:'成功跨度',type:'bar',data:b11.map(b=>b.ok_wall_min),itemStyle:{{color:'#22c55e'}},barWidth:'25%'}},
    {{name:'失败跨度',type:'bar',data:b11.map(b=>b.fail_wall_min),itemStyle:{{color:'#ef4444'}},barWidth:'25%'}},
    {{name:'总墙钟',type:'line',data:b11.map(b=>b.wall_min),lineStyle:{{color:'#8892a8',width:2,type:'dashed'}},symbol:'diamond',symbolSize:8,itemStyle:{{color:'#8892a8'}}}}
  ]
}});

// 表格
const tb = document.getElementById('batchTable');
batches.forEach((b,i) => {{
  const rate = b.total>0?(b.ok/b.total*100).toFixed(1):'–';
  const rNum = parseFloat(rate);
  const wallStr = b.wall_min >= 60 ? `${{Math.floor(b.wall_min/60)}}h${{Math.round(b.wall_min%60)}}m` : `${{b.wall_min}}min`;
  const okDurStr = b.ok_total_sec>0 ? (b.ok_total_sec/60).toFixed(1)+'min' : '–';
  const failDurStr = b.fail_total_sec>0 ? (b.fail_total_sec/60).toFixed(1)+'min' : '–';
  const avgSec = b.ok>0 ? b.ok_avg_sec : 0;
  const avgStr = avgSec>0 ? (avgSec/60).toFixed(1)+'min' : '–';
  let status = b.total<20?'<span class="tag tag-warn">数据不足</span>':rNum>=80?'<span class="tag tag-ok">优秀</span>':rNum>=60?'<span class="tag tag-info">正常</span>':rNum>=40?'<span class="tag tag-warn">偏低</span>':'<span class="tag tag-fail">异常</span>';
  tb.innerHTML += `<tr>
    <td>${{i+1}}</td>
    <td><strong>${{b.date}} ${{b.name}}</strong></td>
    <td><span class="tag tag-info">${{b.source||'–'}}</span></td>
    <td>${{b.total}}</td>
    <td class="green">${{b.ok}}</td>
    <td class="red">${{b.fail}}</td>
    <td><span class="tag ${{rNum>=70?'tag-ok':rNum>=50?'tag-warn':'tag-fail'}}">${{rate}}%</span></td>
    <td style="font-family:monospace;font-size:11px">${{b.first_done}}</td>
    <td style="font-family:monospace;font-size:11px">${{b.last_done}}</td>
    <td><strong style="font-size:13px">${{wallStr}}</strong></td>
    <td class="green">${{b.ok_wall_min}}min</td>
    <td class="red">${{b.fail_wall_min}}min</td>
    <td class="green">${{okDurStr}}</td>
    <td class="red">${{failDurStr}}</td>
    <td>${{avgStr}}</td>
    <td>${{status}}</td>
  </tr>`;
}});

// 结论
const cl = document.getElementById('conclusions');
const totalOk = batches.reduce((s,b)=>s+b.ok,0);
const totalFail = batches.reduce((s,b)=>s+b.fail,0);
const totalBugs = batches.reduce((s,b)=>s+b.total,0);
const avgWall = b11.length>0 ? (b11.reduce((s,b)=>s+b.wall_min,0)/b11.length).toFixed(1) : '-';
const minB = b11.length>0 ? b11.reduce((a,b)=>a.wall_min<b.wall_min?a:b) : null;
const maxB = b11.length>0 ? b11.reduce((a,b)=>a.wall_min>b.wall_min?a:b) : null;
const totalOkSec = batches.reduce((s,b)=>s+b.ok_total_sec,0);
const totalFailSec = batches.reduce((s,b)=>s+b.fail_total_sec,0);
cl.innerHTML = `
  <li><strong>10-11 共 ${{b11.length}} 个批次</strong>，总计 ${{totalBugs}} 个 Bug（成功 ${{totalOk}} / 失败 ${{totalFail}}）</li>
  <li><strong>10-11 平均每批次墙钟 ${{avgWall}} 分钟</strong>，最快 ${{minB?minB.name+'('+minB.wall_min+'min)':'–'}}，最慢 ${{maxB?maxB.name+'('+maxB.wall_min+'min)':'–'}}</li>
  <li><strong>成功记录总分析耗时 ${{(totalOkSec/60).toFixed(0)}} 分钟</strong>（所有批次累加），<strong>失败记录总分析耗时 ${{(totalFailSec/60).toFixed(0)}} 分钟</strong></li>
  <li><strong>成功率 ${{(totalOk/totalBugs*100).toFixed(1)}}%</strong>，成功记录平均跨度 vs 失败记录跨度可反映分析服务端对不同结果的处理速度差异</li>
  <li>墙钟时间 = max(成功跨度, 失败跨度)，两者之和 ≤ 墙钟是因为成功/失败记录可能交叉完成</li>
`;

window.addEventListener('resize',()=>{{c1.resize();c2.resize();c3.resize();c4.resize()}});
</script>
</body>
</html>'''

# 保存
_PROJECT_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
out_path = os.path.join(_PROJECT_ROOT, "reports", "batch_wallclock_10-10_to_10-11_v2.html")
with open(out_path, "w", encoding="utf-8") as f:
    f.write(html)
print(f"\n报告已生成: {out_path}")
