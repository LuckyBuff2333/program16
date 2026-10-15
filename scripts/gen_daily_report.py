#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""日报 HTML 生成器（完全仿照 daily_report 格式）

从批次 CSV + 多维表格分析结果生成每日综合报告。

用法:
  python scripts/gen_daily_report.py              # 生成今天
  python scripts/gen_daily_report.py 2026-10-13   # 生成指定日期

输出: reports/{日期}/daily_report_{日期}.html
"""
import csv
import json
import os
import re
import sys
from datetime import datetime
from collections import defaultdict

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPORTS_DIR = os.path.join(PROJECT_ROOT, "reports")
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)


# ─── 复用 gen_batch_report 的工具函数 ───

from scripts.gen_batch_report import (
    collect_batches, _query_bitable, _parse_dur_sec, _classify_failure,
    _CSS, _read_csv, _clean_row,
)


# ─── 日报数据组装 ───

def build_daily_data(date_str):
    """收集日期内所有批次 + 多维表格交叉，返回日报结构化数据"""
    batches = collect_batches(date_str)
    if not batches:
        return None

    # 收集所有 jira 号
    all_jira_ids = []
    for _, _, rows in batches:
        all_jira_ids.extend(r.get("jira号", "") for r in rows)
    bt_map = _query_bitable(all_jira_ids)

    # 逐批次组装数据（与日报 batchData 数组结构一致）
    batch_list = []
    all_durations = []
    for name, src, rows in batches:
        jira_ids = [r.get("jira号", "") for r in rows]
        total = len(rows)
        submit_ok = sum(1 for r in rows if r.get("执行结果", "") not in ("失败", ""))
        submit_fail = total - submit_ok
        exec_time = ""
        for r in rows:
            if not exec_time:
                exec_time = r.get("执行时间", "")
        # 多维表格匹配
        bt_ok = bt_fail = bt_miss = 0
        durations = []
        fail_items = []
        for br in rows:
            jid = br.get("jira号", "")
            bt_recs = bt_map.get(jid, [])
            if bt_recs:
                exec_t = br.get("执行时间", "")
                candidates = [r for r in bt_recs if r.get("分析完成时间", "") and r["分析完成时间"] >= exec_t]
                if not candidates:
                    candidates = bt_recs
                candidates.sort(key=lambda x: x.get("分析完成时间", ""))
                success_recs = [r for r in candidates if r.get("分析结果", "") == "成功"]
                bf = success_recs[0] if success_recs else candidates[-1]
                result = bf.get("分析结果", "")
                dur = _parse_dur_sec(bf.get("分析耗时", ""))
                if dur > 0:
                    durations.append(dur)
                    all_durations.append(dur)
                if result == "成功":
                    bt_ok += 1
                else:
                    bt_fail += 1
                    err = (bf.get("错误信息", "") or "")[:80]
                    cat = _classify_failure(err)
                    fail_items.append({"jira": jid, "src": src, "cat": cat, "err": err, "dur": round(dur)})
            else:
                bt_miss += 1
        bt_match = bt_ok + bt_fail
        avg_dur = round(sum(durations) / len(durations)) if durations else 0
        max_dur = max(durations) if durations else 0
        # 来源覆盖
        actual_src = src
        for r in rows:
            ts = r.get("触发来源", "")
            if ts:
                actual_src = ts
                break
        batch_list.append({
            "name": name,
            "exec": exec_time[5:16] if len(exec_time) > 5 else exec_time,
            "src": actual_src,
            "total": total,
            "submitOk": submit_ok,
            "submitFail": submit_fail,
            "btMatch": bt_match,
            "btOk": bt_ok,
            "btFail": bt_fail,
            "btMiss": bt_miss,
            "avgDur": avg_dur,
            "maxDur": max_dur,
            "fail_items": fail_items,
        })

    # 汇总统计
    total_submit = sum(b["total"] for b in batch_list)
    total_ok = sum(b["submitOk"] for b in batch_list)
    total_bt_match = sum(b["btMatch"] for b in batch_list)
    total_bt_ok = sum(b["btOk"] for b in batch_list)
    total_bt_fail = sum(b["btFail"] for b in batch_list)
    total_bt_miss = sum(b["btMiss"] for b in batch_list)
    rate = round(total_bt_ok / total_bt_match * 100, 1) if total_bt_match else 0
    avg_dur_all = round(sum(all_durations) / len(all_durations)) if all_durations else 0
    max_dur_all = max(all_durations) if all_durations else 0
    min_dur_all = min(all_durations) if all_durations else 0
    too_long = sum(1 for d in all_durations if d > 900)
    pc_batches = [b for b in batch_list if b["src"] == "PC"]
    online_batches = [b for b in batch_list if b["src"] != "PC"]
    # PC 汇总
    pc_submit = sum(b["submitOk"] for b in pc_batches)
    pc_bt_ok = sum(b["btOk"] for b in pc_batches)
    pc_bt_fail = sum(b["btFail"] for b in pc_batches)
    pc_bt_match = sum(b["btMatch"] for b in pc_batches)
    pc_rate = round(pc_bt_ok / pc_bt_match * 100, 1) if pc_bt_match else 0
    pc_durs = []
    for b in pc_batches:
        for fi in b.get("fail_items", []):
            pc_durs.append(fi["dur"])
    # 线上汇总
    online_submit = sum(b["submitOk"] for b in online_batches)
    online_bt_ok = sum(b["btOk"] for b in online_batches)
    online_bt_fail = sum(b["btFail"] for b in online_batches)
    online_bt_match = sum(b["btMatch"] for b in online_batches)
    online_rate = round(online_bt_ok / online_bt_match * 100, 1) if online_bt_match else 0
    # 所有失败详情
    all_failures = []
    for b in batch_list:
        all_failures.extend(b.get("fail_items", []))

    return {
        "date": date_str,
        "batches": batch_list,
        "all_durations": [round(d) for d in all_durations],
        "total_submit": total_submit,
        "total_ok": total_ok,
        "total_bt_match": total_bt_match,
        "total_bt_ok": total_bt_ok,
        "total_bt_fail": total_bt_fail,
        "total_bt_miss": total_bt_miss,
        "rate": rate,
        "avg_dur": avg_dur_all,
        "max_dur": max_dur_all,
        "min_dur": min_dur_all,
        "too_long": too_long,
        "pc_batches": len(pc_batches),
        "online_batches": len(online_batches),
        "pc_submit": pc_submit, "pc_bt_ok": pc_bt_ok, "pc_bt_fail": pc_bt_fail,
        "pc_bt_match": pc_bt_match, "pc_rate": pc_rate,
        "online_submit": online_submit, "online_bt_ok": online_bt_ok,
        "online_bt_fail": online_bt_fail, "online_bt_match": online_bt_match,
        "online_rate": online_rate,
        "all_failures": all_failures,
    }


# ─── HTML 生成 ───

def generate_daily_html(d, gen_date):
    """生成与 daily_report_2026-10-13.html 完全一致的 HTML"""
    date_str = d["date"]
    # batchData JS 数组
    bd_items = []
    for b in d["batches"]:
        bd_items.append(
            f'  {{name:"{b["name"]}",exec:"{b["exec"]}",src:"{b["src"]}",'
            f'total:{b["total"]},submitOk:{b["submitOk"]},submitFail:{b["submitFail"]},'
            f'btMatch:{b["btMatch"]},btOk:{b["btOk"]},btFail:{b["btFail"]},btMiss:{b["btMiss"]},'
            f'avgDur:{b["avgDur"]},maxDur:{b["maxDur"]}}}'
        )
    batch_data_js = "[\n" + ",\n".join(bd_items) + "\n]"
    all_dur_js = json.dumps(d["all_durations"])

    # 失败详情行
    fail_rows_html = ""
    for f in d["all_failures"]:
        src_tag = "tag-info" if f["src"] == "PC" else "tag-warn"
        fail_rows_html += (
            f'      <tr><td>{f.get("batch","")}</td>'
            f'<td><span class="tag {src_tag}">{f["src"]}</span></td>'
            f'<td style="font-weight:600">{f["jira"]}</td>'
            f'<td><span class="tag tag-fail">{f["cat"]}</span></td>'
            f'<td style="color:var(--muted)">{f["err"]}</td>'
            f'<td>{f["dur"]}s</td></tr>\n'
        )
    # 修正失败详情中的批次名
    fail_rows_html = ""
    for b in d["batches"]:
        for f in b.get("fail_items", []):
            src_tag = "tag-info" if f["src"] == "PC" else "tag-warn"
            fail_rows_html += (
                f'      <tr><td>{b["name"]}</td>'
                f'<td><span class="tag {src_tag}">{f["src"]}</span></td>'
                f'<td style="font-weight:600">{f["jira"]}</td>'
                f'<td><span class="tag tag-fail">{f["cat"]}</span></td>'
                f'<td style="color:var(--muted)">{f["err"]}</td>'
                f'<td>{f["dur"]}s</td></tr>\n'
            )

    # 结论
    conclusion = []
    conclusion.append(
        f'<li><strong>{date_str} 共 {len(d["batches"])} 个批次</strong>，'
        f'PC {d["pc_batches"]} 个 + 线上 {d["online_batches"]} 个，'
        f'总提交 <strong>{d["total_submit"]} 个 Bug</strong>，去重后匹配 {d["total_bt_match"]} 个 Jira</li>'
    )
    conclusion.append(
        f'<li><strong>多维表格分析成功 {d["total_bt_ok"]} 个</strong>'
        f'（匹配 {d["total_bt_match"]}，成功率 <strong>{d["rate"]}%</strong>）'
        + (f'，{d["total_bt_miss"]} 个分析中待出结果' if d["total_bt_miss"] else '') + '</li>'
    )
    if d["pc_batches"]:
        conclusion.append(
            f'<li><strong>PC 来源</strong>：{d["pc_submit"]} 个 Bug，'
            f'分析成功率 <strong>{d["pc_rate"]}%</strong>（{d["pc_bt_ok"]}/{d["pc_bt_match"]}）'
            + (f'，{d["pc_bt_fail"]} 个失败' if d["pc_bt_fail"] else '') + '</li>'
        )
    if d["online_batches"]:
        conclusion.append(
            f'<li><strong>线上来源</strong>：{d["online_submit"]} 个 Bug，'
            f'分析成功率 <strong>{d["online_rate"]}%</strong>（{d["online_bt_ok"]}/{d["online_bt_match"]}）'
            + (f'，{d["online_bt_fail"]} 个失败' if d["online_bt_fail"] else '') + '</li>'
        )
    if d["all_durations"]:
        too_long_pct = round(d["too_long"] / len(d["all_durations"]) * 100, 1)
        conclusion.append(
            f'<li><strong>分析耗时均值 {round(d["avg_dur"]/60,1)}min</strong>'
            f'（{d["total_bt_match"]} 个已出结果），最短 {d["min_dur"]}s，'
            f'最长 {round(d["max_dur"]/60,1)}min'
            + (f'；{d["too_long"]} 个超过 15 分钟阈值（{too_long_pct}%）' if d["too_long"] else '') + '</li>'
        )
    if d["all_failures"]:
        cats = defaultdict(int)
        for f in d["all_failures"]:
            cats[f["cat"]] += 1
        cat_desc = "、".join(f'{c}({n}个)' for c, n in cats.items())
        conclusion.append(f'<li><strong>{len(d["all_failures"])} 个分析失败</strong>：{cat_desc}</li>')
    conclusion_html = "\n    ".join(conclusion)

    # PC/线上汇总卡片
    pc_card = ""
    if d["pc_batches"]:
        pc_avg = round(sum(b["avgDur"] for b in d["batches"] if b["src"]=="PC" and b["avgDur"]>0)/(sum(1 for b in d["batches"] if b["src"]=="PC" and b["avgDur"]>0) or 1))
        pc_max = max((b["maxDur"] for b in d["batches"] if b["src"]=="PC" and b["maxDur"]>0), default=0)
        pc_pending = sum(b["btMiss"] for b in d["batches"] if b["src"]=="PC")
        pc_card = f"""    <div class="card">
      <div class="batch-header">
        <div><span class="tag tag-info">PC</span></div>
        <div class="batch-meta">{d["pc_batches"]} 批次 · jira_analyze</div>
      </div>
      <div class="grid-4" style="margin-top:12px">
        <div><div class="card-label">提交数</div><div style="font-size:22px;font-weight:700">{d["pc_submit"]}</div></div>
        <div><div class="card-label">成功</div><div style="font-size:22px;font-weight:700" class="green">{d["pc_bt_ok"]}</div></div>
        <div><div class="card-label">失败</div><div style="font-size:22px;font-weight:700" class="red">{d["pc_bt_fail"]}</div></div>
        <div><div class="card-label">成功率</div><div style="font-size:22px;font-weight:700" class="{"green" if d["pc_rate"]>=70 else "orange"}">{d["pc_rate"]}%</div></div>
      </div>
      <div style="margin-top:10px;font-size:12px;color:var(--muted)">耗时: 均 {pc_avg}s({round(pc_avg/60,1)}min) · 最大 {pc_max}s({round(pc_max/60,1)}min){" · 待分析 "+str(pc_pending) if pc_pending else ""}</div>
    </div>"""
    online_card = ""
    if d["online_batches"]:
        on_avg = round(sum(b["avgDur"] for b in d["batches"] if b["src"]!="PC" and b["avgDur"]>0)/(sum(1 for b in d["batches"] if b["src"]!="PC" and b["avgDur"]>0) or 1))
        on_max = max((b["maxDur"] for b in d["batches"] if b["src"]!="PC" and b["maxDur"]>0), default=0)
        on_pending = sum(b["btMiss"] for b in d["batches"] if b["src"]!="PC")
        online_card = f"""    <div class="card">
      <div class="batch-header">
        <div><span class="tag tag-warn">线上</span></div>
        <div class="batch-meta">{d["online_batches"]} 批次 · parseFullTicket</div>
      </div>
      <div class="grid-4" style="margin-top:12px">
        <div><div class="card-label">提交数</div><div style="font-size:22px;font-weight:700">{d["online_submit"]}</div></div>
        <div><div class="card-label">成功</div><div style="font-size:22px;font-weight:700" class="green">{d["online_bt_ok"]}</div></div>
        <div><div class="card-label">失败</div><div style="font-size:22px;font-weight:700" class="red">{d["online_bt_fail"]}</div></div>
        <div><div class="card-label">成功率</div><div style="font-size:22px;font-weight:700" class="{"green" if d["online_rate"]>=70 else "orange"}">{d["online_rate"]}%</div></div>
      </div>
      <div style="margin-top:10px;font-size:12px;color:var(--muted)">耗时: 均 {on_avg}s({round(on_avg/60,1)}min) · 最大 {on_max}s({round(on_max/60,1)}min){" · 待分析 "+str(on_pending) if on_pending else ""}</div>
    </div>"""

    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>每日测试综合报告 · {date_str}</title>
<script src="https://cdn.jsdelivr.net/npm/echarts@5/dist/echarts.min.js"></script>
<style>
{_CSS}
</style>
</head>
<body>
<div class="container">

<h1>每日测试综合报告 · {date_str}</h1>
<p class="subtitle">数据来源：批次 CSV + 多维表格分析结果 · 生成时间：{gen_date}</p>

<!-- ========== 顶部概览 ========== -->
<div class="grid-4">
  <div class="card"><div class="card-label">总批次数</div><div class="card-value cyan">{len(d["batches"])}</div><div class="card-sub">PC: {d["pc_batches"]}个 · 线上: {d["online_batches"]}个</div></div>
  <div class="card"><div class="card-label">总提交 Bug</div><div class="card-value blue">{d["total_submit"]}</div><div class="card-sub">PC: {d["pc_submit"]}个 · 线上: {d["online_submit"]}个</div></div>
  <div class="card"><div class="card-label">多维表格分析成功</div><div class="card-value green">{d["total_bt_ok"]}</div><div class="card-sub">总匹配 {d["total_bt_match"]} / 成功率 {d["rate"]}%</div></div>
  <div class="card"><div class="card-label">分析耗时均值</div><div class="card-value purple">{round(d["avg_dur"]/60,1)}min</div><div class="card-sub">最短 {d["min_dur"]}s · 最大 {round(d["max_dur"]/60,1)}min</div></div>
</div>

<!-- ========== PC vs 线上汇总 ========== -->
<div class="section">
  <div class="section-title">PC vs 线上分析结果汇总（多维表格 · 按来源分组）</div>
  <div class="grid-2">
{pc_card}
{online_card}
  </div>
</div>

<!-- ========== 图表区 ========== -->
<div class="section">
  <div class="section-title">图表分析</div>

  <div class="chart-box">
    <div class="chart-title">每批次提交成功 vs 多维表格分析成功（柱状对比）</div>
    <div id="chart_submit_vs_analysis" style="height:380px"></div>
  </div>

  <div class="grid-2">
    <div class="chart-box">
      <div class="chart-title">每批次分析成功率（多维表格匹配后）</div>
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

<!-- ========== 批次详情表 ========== -->
<div class="section">
  <div class="section-title">批次详情（CSV + 多维表格验证）</div>
  <div class="table-wrap">
  <table>
    <thead>
      <tr>
        <th>#</th><th>批次名称</th><th>执行时间</th><th>来源</th>
        <th>提交</th><th>提交成功</th><th>表格匹配</th><th>分析成功</th>
        <th>分析失败</th><th>未找到</th><th>成功率</th><th>平均耗时</th>
        <th>最大耗时</th><th>状态</th>
      </tr>
    </thead>
    <tbody id="batchTableBody"></tbody>
  </table>
  </div>
</div>

<!-- ========== 失败详情 ========== -->
<div class="section">
  <div class="section-title">失败详情</div>
  <div class="table-wrap">
  <table>
    <thead><tr><th>批次</th><th>来源</th><th>Jira号</th><th>失败分类</th><th>错误信息</th><th>分析耗时</th></tr></thead>
    <tbody>
{fail_rows_html}
    </tbody>
  </table>
  </div>
</div>

<!-- ========== 结论 ========== -->
<div class="conclusion">
  <h3>核心结论</h3>
  <ol>
    {conclusion_html}
  </ol>
</div>

</div><!-- container -->

<script>
const batchData = {batch_data_js};
const allDurations = {all_dur_js};

// ===== 图1: 提交成功 vs 分析成功 =====
const chart1 = echarts.init(document.getElementById('chart_submit_vs_analysis'));
chart1.setOption({{
  tooltip:{{trigger:'axis'}},
  legend:{{data:['提交成功','分析成功(多维表格)','分析失败'],textStyle:{{color:'#8892a8'}}}},
  grid:{{left:50,right:20,bottom:60,top:40}},
  xAxis:{{type:'category',data:batchData.map(b=>b.name),axisLabel:{{rotate:35,color:'#8892a8',fontSize:10}},axisLine:{{lineStyle:{{color:'#2a2d3e'}}}}}},
  yAxis:{{type:'value',name:'Bug数',nameTextStyle:{{color:'#8892a8'}},axisLabel:{{color:'#8892a8'}},splitLine:{{lineStyle:{{color:'#1e2030'}}}}}},
  series:[
    {{name:'提交成功',type:'bar',data:batchData.map(b=>b.submitOk),itemStyle:{{color:'#3b82f6'}},barGap:'10%',barMaxWidth:40}},
    {{name:'分析成功(多维表格)',type:'bar',data:batchData.map(b=>b.btOk),itemStyle:{{color:'#22c55e'}},barMaxWidth:40}},
    {{name:'分析失败',type:'bar',data:batchData.map(b=>b.btFail),itemStyle:{{color:'#ef4444'}},barMaxWidth:40}}
  ]
}});

// ===== 图2: 每批次成功率 =====
const chart2 = echarts.init(document.getElementById('chart_success_rate'));
const rateData = batchData.map(b => b.btMatch > 0 ? Math.round(b.btOk / b.btMatch * 100) : 0);
chart2.setOption({{
  tooltip:{{trigger:'axis',formatter:p=>`${{p[0].name}}<br/>成功率: ${{p[0].value}}%`}},
  grid:{{left:45,right:15,bottom:60,top:20}},
  xAxis:{{type:'category',data:batchData.map(b=>b.name),axisLabel:{{rotate:40,color:'#8892a8',fontSize:9}},axisLine:{{lineStyle:{{color:'#2a2d3e'}}}}}},
  yAxis:{{type:'value',max:100,axisLabel:{{formatter:'{{value}}%',color:'#8892a8'}},splitLine:{{lineStyle:{{color:'#1e2030'}}}}}},
  series:[{{type:'bar',data:rateData.map(v=>({{value:v,itemStyle:{{color:v>=70?'#22c55e':v>=50?'#f59e0b':'#ef4444'}}}})),barWidth:'60%'}}]
}});

// ===== 图3: 平均耗时 =====
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

// ===== 图4: 耗时直方图 =====
const chart4 = echarts.init(document.getElementById('chart_duration_hist'));
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

// ===== 批次详情表 =====
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

window.addEventListener('resize',()=>{{chart1.resize();chart2.resize();chart3.resize();chart4.resize()}});
</script>
</body>
</html>"""
    return html


# ─── 入口 ───

def main():
    date_str = sys.argv[1] if len(sys.argv) > 1 else datetime.now().strftime("%Y-%m-%d")
    print(f"生成 {date_str} 日报...")
    d = build_daily_data(date_str)
    if not d:
        print(f"未找到 {date_str} 的批次数据")
        sys.exit(1)
    gen_date = datetime.now().strftime("%Y-%m-%d %H:%M")
    html = generate_daily_html(d, gen_date)
    out_dir = os.path.join(REPORTS_DIR, date_str)
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, f"daily_report_{date_str}.html")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"✓ {out_path} ({len(html)} 字符)")
    print(f"  {len(d['batches'])} 个批次 | 总提交 {d['total_submit']} | "
          f"分析成功 {d['total_bt_ok']} 失败 {d['total_bt_fail']} 未匹配 {d['total_bt_miss']} | "
          f"成功率 {d['rate']}%")


if __name__ == "__main__":
    main()
