#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""每日测试综合报告生成器（按 timestudy/daily_report_2026-10-13.html 格式）

用法: python scripts/generate_daily_report.py [日期]
默认日期: 今天
"""
import csv
import json
import os
import sys
from collections import defaultdict
from datetime import datetime

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPORTS_DIR = os.path.join(PROJECT_ROOT, "reports")


def _read_csv(path):
    """读取 CSV，自动处理 BOM"""
    if not os.path.exists(path):
        return []
    return list(csv.DictReader(open(path, encoding="utf-8-sig")))


def _clean_row(r):
    """清理行键名（去 BOM）"""
    return {k.replace("\ufeff", ""): v.strip() for k, v in r.items()}


def collect_daily_data(date_str):
    """收集指定日期的所有批次数据"""
    doc_dir = os.path.join(PROJECT_ROOT, "docs", date_str)
    unan_dir = os.path.join(PROJECT_ROOT, "data", "unanalyzed")
    batches = []

    # 1. docs/日期/batch_*.csv (PC 批次)
    if os.path.isdir(doc_dir):
        for f in sorted(os.listdir(doc_dir)):
            if f.startswith("batch_") and f.endswith(".csv"):
                rows = [_clean_row(r) for r in _read_csv(os.path.join(doc_dir, f))]
                if rows:
                    name = f.replace(".csv", "")
                    time_part = name.split("_")[-1] if "_" in name else ""
                    if len(time_part) == 6 and time_part.isdigit():
                        exec_short = f"{date_str[5:7]}-{date_str[8:10]} {time_part[:2]}:{time_part[2:4]}"
                    else:
                        exec_short = f"{date_str[5:7]}-{date_str[8:10]}"
                    batches.append({"name": name, "exec": exec_short, "src": "PC", "rows": rows})

    # 2. data/unanalyzed/prod_batch_日期_*.csv (线上批次)
    if os.path.isdir(unan_dir):
        for f in sorted(os.listdir(unan_dir)):
            if not f.startswith("prod_batch_") or not f.endswith(".csv"):
                continue
            if date_str not in f:
                continue
            rows = [_clean_row(r) for r in _read_csv(os.path.join(unan_dir, f))]
            if rows:
                name = f.replace(".csv", "")
                parts = name.split("_")
                time_part = parts[-1] if len(parts) >= 4 else ""
                if len(time_part) == 6 and time_part.isdigit():
                    exec_short = f"{date_str[5:7]}-{date_str[8:10]} {time_part[:2]}:{time_part[2:4]}"
                else:
                    exec_short = f"{date_str[5:7]}-{date_str[8:10]}"
                batches.append({"name": name, "exec": exec_short, "src": "线上", "rows": rows})

    return batches


def analyze_batch(batch):
    """分析单个批次"""
    rows = batch["rows"]
    total = len(rows)
    submit_ok = sum(1 for r in rows if r.get("执行结果", "") == "成功")
    submit_fail = total - submit_ok
    bt_ok = bt_fail = bt_miss = 0
    errors = []
    durations = []

    for r in rows:
        status = r.get("分析状态", "")
        error = r.get("错误信息", "")
        dur = r.get("分析耗时", "")
        if status in ("成功", "已分析"):
            bt_ok += 1
        elif status in ("错误", "失败"):
            bt_fail += 1
            if error:
                errors.append({"batch": batch["name"], "src": batch["src"],
                               "jira": r.get("Jira号", r.get("jira号", "")),
                               "error": error, "dur": dur})
        else:
            bt_miss += 1
        if dur:
            try:
                d = float(str(dur).replace("min", "").replace("s", "").replace("秒", ""))
                if "min" in str(dur):
                    d *= 60
                durations.append(d)
            except (ValueError, TypeError):
                pass

    bt_match = bt_ok + bt_fail
    avg_dur = sum(durations) / len(durations) if durations else 0
    max_dur = max(durations) if durations else 0
    return {
        "name": batch["name"], "exec": batch["exec"], "src": batch["src"],
        "total": total, "submitOk": submit_ok, "submitFail": submit_fail,
        "btMatch": bt_match, "btOk": bt_ok, "btFail": bt_fail, "btMiss": bt_miss,
        "avgDur": round(avg_dur), "maxDur": round(max_dur),
        "errors": errors, "durations": durations,
    }


def generate_html(date_str, batch_stats, all_errors, all_durations):
    """生成 HTML 报告"""
    pc = [b for b in batch_stats if b["src"] == "PC"]
    on = [b for b in batch_stats if b["src"] == "线上"]
    total_batches = len(batch_stats)
    total_bugs = sum(b["total"] for b in batch_stats)
    total_match = sum(b["btMatch"] for b in batch_stats)
    total_ok = sum(b["btOk"] for b in batch_stats)
    total_fail = sum(b["btFail"] for b in batch_stats)
    rate = round(total_ok / total_match * 100, 1) if total_match > 0 else 0

    pc_bugs = sum(b["total"] for b in pc)
    pc_ok = sum(b["btOk"] for b in pc)
    pc_fail = sum(b["btFail"] for b in pc)
    pc_match = sum(b["btMatch"] for b in pc)
    pc_rate = round(pc_ok / pc_match * 100, 1) if pc_match > 0 else 0
    on_bugs = sum(b["total"] for b in on)
    on_ok = sum(b["btOk"] for b in on)
    on_fail = sum(b["btFail"] for b in on)
    on_match = sum(b["btMatch"] for b in on)
    on_rate = round(on_ok / on_match * 100, 1) if on_match > 0 else 0

    avg_dur = sum(all_durations) / len(all_durations) if all_durations else 0
    min_dur = min(all_durations) if all_durations else 0
    max_dur = max(all_durations) if all_durations else 0

    def fmt_dur(s):
        return f"{s/60:.1f}min" if s >= 60 else f"{s:.0f}s"

    js_data = json.dumps([{
        "name": b["name"], "exec": b["exec"], "src": b["src"],
        "total": b["total"], "submitOk": b["submitOk"], "submitFail": b["submitFail"],
        "btMatch": b["btMatch"], "btOk": b["btOk"], "btFail": b["btFail"],
        "btMiss": b["btMiss"], "avgDur": b["avgDur"], "maxDur": b["maxDur"],
    } for b in batch_stats], ensure_ascii=False)
    js_durations = json.dumps(sorted(all_durations))

    # 失败详情
    fail_rows = ""
    for e in all_errors:
        src_tag = f'<span class="tag tag-info">{e["src"]}</span>' if e["src"] == "PC" else f'<span class="tag tag-warn">{e["src"]}</span>'
        fail_rows += f'<tr><td>{e["batch"]}</td><td>{src_tag}</td><td style="font-weight:600">{e["jira"]}</td><td><span class="tag tag-fail">分析失败</span></td><td style="color:var(--muted)">{e["error"][:80]}</td><td>{e["dur"]}</td></tr>\n'

    # 结论
    conclusions = [
        f"<strong>{date_str} 共 {total_batches} 个批次</strong>，PC {len(pc)} 个 + 线上 {len(on)} 个，总提交 <strong>{total_bugs} 个 Bug</strong>",
        f"<strong>多维表格分析成功 {total_ok} 个</strong>（匹配 {total_match}，成功率 <strong>{rate}%</strong>）",
    ]
    if pc_bugs > 0:
        conclusions.append(f"<strong>PC 来源</strong>：{pc_bugs} 个 Bug，分析成功率 <strong>{pc_rate}%</strong>（{pc_ok}/{pc_match}）")
    if on_bugs > 0:
        conclusions.append(f"<strong>线上来源</strong>：{on_bugs} 个 Bug，分析成功率 <strong>{on_rate}%</strong>（{on_ok}/{on_match}）")
    if all_durations:
        conclusions.append(f"<strong>分析耗时均值 {fmt_dur(avg_dur)}</strong>，最短 {fmt_dur(min_dur)}，最长 {fmt_dur(max_dur)}")
    if all_errors:
        conclusions.append(f"<strong>{len(all_errors)} 个失败</strong>记录")

    conclusion_html = "\n    ".join(f"<li>{c}</li>" for c in conclusions)
    now = datetime.now().strftime("%Y-%m-%d %H:%M")

    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>每日测试综合报告 · {date_str}</title>
<script src="https://cdn.jsdelivr.net/npm/echarts@5/dist/echarts.min.js"></script>
<style>
:root{{--bg:#0f1117;--card:#1a1d2e;--border:#2a2d3e;--text:#e2e8f0;--muted:#8892a8;--accent:#6366f1;--green:#22c55e;--red:#ef4444;--orange:#f59e0b;--blue:#3b82f6;--cyan:#06b6d4;--purple:#a78bfa}}
*{{margin:0;padding:0;box-sizing:border-box}}
body{{font-family:-apple-system,'Segoe UI','PingFang SC','Microsoft YaHei',sans-serif;background:var(--bg);color:var(--text);line-height:1.7;padding:20px}}
.container{{max-width:1400px;margin:0 auto}}
h1{{font-size:26px;font-weight:700;background:linear-gradient(135deg,#6366f1,#a78bfa);-webkit-background-clip:text;background-clip:text;-webkit-text-fill-color:transparent}}
.subtitle{{color:var(--muted);font-size:13px;margin:4px 0 24px}}
.grid-2{{display:grid;grid-template-columns:1fr 1fr;gap:16px}}
.grid-4{{display:grid;grid-template-columns:repeat(4,1fr);gap:12px}}
@media(max-width:1000px){{.grid-2,.grid-4{{grid-template-columns:1fr}}}}
.card{{background:var(--card);border:1px solid var(--border);border-radius:12px;padding:18px}}
.card-label{{font-size:11px;color:var(--muted);text-transform:uppercase;letter-spacing:.5px}}
.card-value{{font-size:28px;font-weight:700;margin:4px 0}}
.card-sub{{font-size:11px;color:var(--muted)}}
.section{{margin:28px 0}}
.section-title{{font-size:16px;font-weight:600;margin-bottom:14px;display:flex;align-items:center;gap:8px}}
.section-title::before{{content:'';display:inline-block;width:4px;height:18px;background:var(--accent);border-radius:2px}}
.chart-box{{background:var(--card);border:1px solid var(--border);border-radius:12px;padding:16px;margin-bottom:20px}}
.chart-title{{font-size:14px;font-weight:600;margin-bottom:10px}}
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
.bg-green{{background:var(--green)}}.bg-red{{background:var(--red)}}.bg-orange{{background:var(--orange)}}.bg-blue{{background:var(--blue)}}
.conclusion{{background:linear-gradient(135deg,rgba(99,102,241,.08),rgba(167,139,250,.05));border:1px solid rgba(99,102,241,.25);border-radius:12px;padding:20px;margin-top:24px}}
.conclusion h3{{font-size:15px;color:var(--accent);margin-bottom:12px}}
.conclusion li{{margin:6px 0;font-size:13px;line-height:1.7}}
.table-wrap{{max-height:500px;overflow:auto;border-radius:8px;border:1px solid var(--border)}}
.batch-header{{display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:8px}}
.batch-meta{{font-size:11px;color:var(--muted)}}
</style>
</head>
<body>
<div class="container">

<h1>每日测试综合报告 · {date_str}</h1>
<p class="subtitle">数据来源：批次 CSV · 生成时间：{now}</p>

<!-- 顶部概览 -->
<div class="grid-4">
  <div class="card"><div class="card-label">总批次数</div><div class="card-value cyan">{total_batches}</div><div class="card-sub">PC: {len(pc)}个 · 线上: {len(on)}个</div></div>
  <div class="card"><div class="card-label">总提交 Bug</div><div class="card-value blue">{total_bugs}</div><div class="card-sub">PC: {pc_bugs}个 · 线上: {on_bugs}个</div></div>
  <div class="card"><div class="card-label">分析成功</div><div class="card-value green">{total_ok}</div><div class="card-sub">总匹配 {total_match} / 成功率 {rate}%</div></div>
  <div class="card"><div class="card-label">分析耗时均值</div><div class="card-value purple">{fmt_dur(avg_dur)}</div><div class="card-sub">最短 {fmt_dur(min_dur)} · 最大 {fmt_dur(max_dur)}</div></div>
</div>

<!-- PC vs 线上 -->
<div class="section">
  <div class="section-title">PC vs 线上分析结果汇总</div>
  <div class="grid-2">
    <div class="card">
      <div class="batch-header"><div><span class="tag tag-info">PC</span></div><div class="batch-meta">{len(pc)} 批次 · jira_analyze</div></div>
      <div class="grid-4" style="margin-top:12px">
        <div><div class="card-label">提交数</div><div style="font-size:22px;font-weight:700">{pc_bugs}</div></div>
        <div><div class="card-label">成功</div><div style="font-size:22px;font-weight:700" class="green">{pc_ok}</div></div>
        <div><div class="card-label">失败</div><div style="font-size:22px;font-weight:700" class="red">{pc_fail}</div></div>
        <div><div class="card-label">成功率</div><div style="font-size:22px;font-weight:700" {"class=\"green\"" if pc_rate>=70 else "class=\"orange\""}>{pc_rate}%</div></div>
      </div>
    </div>
    <div class="card">
      <div class="batch-header"><div><span class="tag tag-warn">线上</span></div><div class="batch-meta">{len(on)} 批次 · parseFullTicket</div></div>
      <div class="grid-4" style="margin-top:12px">
        <div><div class="card-label">提交数</div><div style="font-size:22px;font-weight:700">{on_bugs}</div></div>
        <div><div class="card-label">成功</div><div style="font-size:22px;font-weight:700" class="green">{on_ok}</div></div>
        <div><div class="card-label">失败</div><div style="font-size:22px;font-weight:700" class="red">{on_fail}</div></div>
        <div><div class="card-label">成功率</div><div style="font-size:22px;font-weight:700" {"class=\"green\"" if on_rate>=70 else "class=\"orange\""}>{on_rate}%</div></div>
      </div>
    </div>
  </div>
</div>

<!-- 图表区 -->
<div class="section">
  <div class="section-title">图表分析</div>
  <div class="chart-box">
    <div class="chart-title">每批次提交成功 vs 多维表格分析成功（柱状对比）</div>
    <div id="chart_submit_vs_analysis" style="height:380px"></div>
  </div>
  <div class="grid-2">
    <div class="chart-box">
      <div class="chart-title">每批次分析成功率</div>
      <div id="chart_success_rate" style="height:340px"></div>
    </div>
    <div class="chart-box">
      <div class="chart-title">每批次平均分析耗时（分钟）</div>
      <div id="chart_avg_duration" style="height:340px"></div>
    </div>
  </div>
  <div class="chart-box">
    <div class="chart-title">所有批次分析耗时分布（秒）</div>
    <div id="chart_duration_hist" style="height:300px"></div>
  </div>
</div>

<!-- 批次详情表 -->
<div class="section">
  <div class="section-title">批次详情（CSV + 多维表格验证）</div>
  <div class="table-wrap">
  <table>
    <thead><tr>
      <th>#</th><th>批次名称</th><th>执行时间</th><th>来源</th><th>提交</th><th>提交成功</th>
      <th>表格匹配</th><th>分析成功</th><th>分析失败</th><th>未找到</th>
      <th>成功率</th><th>平均耗时</th><th>最大耗时</th><th>状态</th>
    </tr></thead>
    <tbody id="batchTableBody"></tbody>
  </table>
  </div>
</div>

<!-- 失败详情 -->
<div class="section">
  <div class="section-title">失败详情</div>
  <div class="table-wrap">
  <table>
    <thead><tr><th>批次</th><th>来源</th><th>Jira号</th><th>失败分类</th><th>错误信息</th><th>分析耗时</th></tr></thead>
    <tbody>
      {fail_rows if fail_rows else '<tr><td colspan="6" style="text-align:center;color:var(--muted)">无失败记录</td></tr>'}
    </tbody>
  </table>
  </div>
</div>

<!-- 结论 -->
<div class="conclusion">
  <h3>核心结论</h3>
  <ol>
    {conclusion_html}
  </ol>
</div>

</div>

<script>
const batchData = {js_data};

// 图1: 提交成功 vs 分析成功
const chart1 = echarts.init(document.getElementById('chart_submit_vs_analysis'));
chart1.setOption({{
  tooltip:{{trigger:'axis'}},
  legend:{{data:['提交成功','分析成功','分析失败'],textStyle:{{color:'#8892a8'}}}},
  grid:{{left:50,right:20,bottom:60,top:40}},
  xAxis:{{type:'category',data:batchData.map(b=>b.name),axisLabel:{{rotate:35,color:'#8892a8',fontSize:10}},axisLine:{{lineStyle:{{color:'#2a2d3e'}}}}}},
  yAxis:{{type:'value',name:'Bug数',nameTextStyle:{{color:'#8892a8'}},axisLabel:{{color:'#8892a8'}},splitLine:{{lineStyle:{{color:'#1e2030'}}}}}},
  series:[
    {{name:'提交成功',type:'bar',data:batchData.map(b=>b.submitOk),itemStyle:{{color:'#3b82f6'}},barGap:'10%'}},
    {{name:'分析成功',type:'bar',data:batchData.map(b=>b.btOk),itemStyle:{{color:'#22c55e'}}}},
    {{name:'分析失败',type:'bar',data:batchData.map(b=>b.btFail),itemStyle:{{color:'#ef4444'}}}}
  ]
}});

// 图2: 每批次成功率
const chart2 = echarts.init(document.getElementById('chart_success_rate'));
const rateData = batchData.map(b => b.btMatch > 0 ? Math.round(b.btOk / b.btMatch * 100) : 0);
chart2.setOption({{
  tooltip:{{trigger:'axis',formatter:p=>`${{p[0].name}}<br/>成功率: ${{p[0].value}}%`}},
  grid:{{left:45,right:15,bottom:60,top:20}},
  xAxis:{{type:'category',data:batchData.map(b=>b.name),axisLabel:{{rotate:40,color:'#8892a8',fontSize:9}},axisLine:{{lineStyle:{{color:'#2a2d3e'}}}}}},
  yAxis:{{type:'value',max:100,axisLabel:{{formatter:'{{value}}%',color:'#8892a8'}},splitLine:{{lineStyle:{{color:'#1e2030'}}}}}},
  series:[{{type:'bar',data:rateData.map(v=>({{value:v,itemStyle:{{color:v>=70?'#22c55e':v>=50?'#f59e0b':'#ef4444'}}}})),barWidth:'60%'}}]
}});

// 图3: 平均耗时
const chart3 = echarts.init(document.getElementById('chart_avg_duration'));
chart3.setOption({{
  tooltip:{{trigger:'axis',formatter:p=>`${{p[0].name}}<br/>平均: ${{p[0].value?p[0].value.toFixed(1):'-'}}min<br/>最大: ${{p[1]&&p[1].value?p[1].value.toFixed(1):'-'}}min`}},
  grid:{{left:45,right:15,bottom:60,top:30}},
  xAxis:{{type:'category',data:batchData.map(b=>b.name),axisLabel:{{rotate:40,color:'#8892a8',fontSize:9}},axisLine:{{lineStyle:{{color:'#2a2d3e'}}}}}},
  yAxis:{{type:'value',name:'分钟',nameTextStyle:{{color:'#8892a8'}},axisLabel:{{color:'#8892a8'}},splitLine:{{lineStyle:{{color:'#1e2030'}}}}}},
  series:[
    {{name:'平均耗时',type:'bar',data:batchData.map(b=>b.avgDur>0?+(b.avgDur/60).toFixed(1):null),itemStyle:{{color:'#a78bfa'}},barGap:'10%',barWidth:'40%'}},
    {{name:'最大耗时',type:'line',data:batchData.map(b=>b.maxDur>0?+(b.maxDur/60).toFixed(1):null),lineStyle:{{color:'#ef4444',width:2}},symbol:'circle',symbolSize:6,itemStyle:{{color:'#ef4444'}}}}
  ]
}});

// 图4: 耗时直方图
const chart4 = echarts.init(document.getElementById('chart_duration_hist'));
const allDurations = {js_durations};
const bins = [0,120,300,600,900,1200,1500];
const binLabels = ['<2min','2-5min','5-10min','10-15min','15-20min','20min+'];
const binCounts = new Array(binLabels.length).fill(0);
allDurations.forEach(d=>{{for(let i=0;i<bins.length;i++){{if(i===bins.length-1){{if(d>=bins[i])binCounts[i]++;}}else if(d>=bins[i]&&d<bins[i+1]){{binCounts[i]++;break;}}}}}});
const binColors = ['#22c55e','#22c55e','#3b82f6','#3b82f6','#f59e0b','#ef4444'];
chart4.setOption({{
  tooltip:{{trigger:'axis'}},
  grid:{{left:45,right:15,bottom:30,top:20}},
  xAxis:{{type:'category',data:binLabels,axisLabel:{{color:'#8892a8'}},axisLine:{{lineStyle:{{color:'#2a2d3e'}}}}}},
  yAxis:{{type:'value',name:'Bug数',nameTextStyle:{{color:'#8892a8'}},axisLabel:{{color:'#8892a8'}},splitLine:{{lineStyle:{{color:'#1e2030'}}}}}},
  series:[{{type:'bar',data:binCounts.map((v,i)=>({{value:v,itemStyle:{{color:binColors[i]}}}})),barWidth:'65%'}}]
}});

// 批次详情表
const tbody = document.getElementById('batchTableBody');
batchData.forEach((b,i)=>{{
  const rate = b.btMatch > 0 ? (b.btOk/b.btMatch*100).toFixed(1) : '-';
  const rateNum = parseFloat(rate);
  const rateClass = rateNum>=70?'tag-ok':rateNum>=50?'tag-warn':'tag-fail';
  const statusTag = b.btMiss > 3 ? '<span class="tag tag-warn">分析中</span>' : b.submitOk===0 ? '<span class="tag tag-fail">提交失败</span>' : rateNum>=70 ? '<span class="tag tag-ok">良好</span>' : rate==='-' ? '<span class="tag tag-warn">待分析</span>' : '<span class="tag tag-warn">偏低</span>';
  const avgMin = b.avgDur>0 ? (b.avgDur/60).toFixed(1)+'min' : '-';
  const maxMin = b.maxDur>0 ? (b.maxDur/60).toFixed(1)+'min' : '-';
  tbody.innerHTML += `<tr>
    <td>${{i+1}}</td>
    <td><strong>${{b.name}}</strong></td>
    <td>${{b.exec}}</td>
    <td><span class="tag ${{b.src==='PC'?'tag-info':'tag-warn'}}">${{b.src}}</span></td>
    <td>${{b.total}}</td>
    <td class="${{b.submitOk>0?'green':'red'}}">${{b.submitOk}}/${{b.submitOk+b.submitFail}}</td>
    <td>${{b.btMatch}}/${{b.total}}</td>
    <td class="green">${{b.btOk}}</td>
    <td class="red">${{b.btFail}}</td>
    <td>${{b.btMiss>0?'<span class="orange">'+b.btMiss+'</span>':'0'}}</td>
    <td><span class="tag ${{rateClass}}">${{rate}}${{rate!=='-'?'%':''}}</span></td>
    <td>${{avgMin}}</td>
    <td>${{maxMin}}</td>
    <td>${{statusTag}}</td>
  </tr>`;
}});

window.addEventListener('resize',()=>{{chart1.resize();chart2.resize();chart3.resize();chart4.resize();}});
</script>
</body>
</html>"""

    return html


def main():
    date_str = sys.argv[1] if len(sys.argv) > 1 else datetime.now().strftime("%Y-%m-%d")
    print(f"收集 {date_str} 的每日数据...")

    batches = collect_daily_data(date_str)
    if not batches:
        print(f"未找到 {date_str} 的任何批次数据")
        sys.exit(1)

    print(f"找到 {len(batches)} 个批次文件")

    batch_stats = []
    all_errors = []
    all_durations = []
    for b in batches:
        stat = analyze_batch(b)
        batch_stats.append(stat)
        all_errors.extend(stat["errors"])
        all_durations.extend(stat["durations"])
        print(f"  [{stat['src']}] {stat['name']} ({stat['total']} 行)")

    html = generate_html(date_str, batch_stats, all_errors, all_durations)

    os.makedirs(REPORTS_DIR, exist_ok=True)
    out_path = os.path.join(REPORTS_DIR, f"daily_report_{date_str}.html")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html)

    print(f"\n报告已生成: {out_path}")
    print(f"文件大小: {len(html)} 字符, {html.count(chr(10))} 行")


if __name__ == "__main__":
    main()
