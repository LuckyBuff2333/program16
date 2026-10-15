#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""单批次执行报告生成器（完全仿照 daily_report 格式）

从批次 CSV + 多维表格分析结果生成独立 HTML 报告。

用法:
  python scripts/gen_batch_report.py [日期]         # 生成该日期所有批次报告
  python scripts/gen_batch_report.py [日期] [批次名] # 仅生成指定批次报告

输出: reports/{日期}/{batch_name}_{日期}.html
"""
import csv
import json
import os
import re
import sys
from datetime import datetime

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPORTS_DIR = os.path.join(PROJECT_ROOT, "reports")

# 确保能导入 src 模块
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)


# ─── CSV 读取 ───

def _read_csv(path):
    if not os.path.exists(path):
        return []
    return list(csv.DictReader(open(path, encoding="utf-8-sig")))


def _clean_row(r):
    return {(k.replace("\ufeff", "").strip()): (v.strip() if isinstance(v, str) else v)
            for k, v in r.items()}


def collect_batches(date_str):
    batches = []
    doc_dir = os.path.join(PROJECT_ROOT, "docs", date_str)
    if os.path.isdir(doc_dir):
        for f in sorted(os.listdir(doc_dir)):
            if f.endswith(".csv") and (f.startswith("batch_") or f.startswith("prod_batch_")):
                rows = _read_csv(os.path.join(doc_dir, f))
                if rows:
                    src = "线上" if f.startswith("prod_batch_") else "PC"
                    batches.append((f.replace(".csv", ""), src, [_clean_row(r) for r in rows]))
    unan_dir = os.path.join(PROJECT_ROOT, "data", "unanalyzed")
    if os.path.isdir(unan_dir):
        for f in sorted(os.listdir(unan_dir)):
            if f.startswith("prod_batch_") and date_str in f and f.endswith(".csv"):
                rows = _read_csv(os.path.join(unan_dir, f))
                if rows:
                    batches.append((f.replace(".csv", ""), "线上", [_clean_row(r) for r in rows]))
    return batches


# ─── 多维表格查询 ───

def _query_bitable(jira_ids):
    """从多维表格查询 jira_ids 的分析结果，返回 {jira_no: [flat_records]}"""
    from src.clients import feishu_client
    from src.config import load_config
    cfg = load_config().get("feishu_bitable", {})
    app_token, table_id = cfg.get("app_token", ""), cfg.get("table_id", "")
    bugid_field = cfg.get("bugid_field", "jira号")
    if not app_token or not table_id:
        return {}
    records = feishu_client.list_bitable_records(app_token, table_id)
    bt_map = {}
    id_set = set(jira_ids)
    for rec in records:
        fields = rec.get("fields", {})
        val = fields.get(bugid_field, "")
        jk = ""
        if isinstance(val, list):
            jk = " ".join(str(v.get("text", "") if isinstance(v, dict) else v) for v in val).strip()
        elif isinstance(val, str):
            jk = val.strip()
        if jk and jk in id_set:
            flat = {}
            for k, v in fields.items():
                if isinstance(v, dict) and "link" in v:
                    flat[k] = str(v.get("link", ""))
                elif isinstance(v, list):
                    flat[k] = " ".join(str(x.get("text", "") if isinstance(x, dict) else x) for x in v)
                else:
                    flat[k] = str(v) if v else ""
            bt_map.setdefault(jk, []).append(flat)
    return bt_map


def _parse_dur_sec(raw):
    if not raw:
        return 0
    s = str(raw).strip()
    m = re.match(r"(\d+)\s*分\s*(\d+)\s*秒?", s)
    if m:
        return float(m.group(1)) * 60 + float(m.group(2))
    m = re.match(r"(\d+)\s*分$", s)
    if m:
        return float(m.group(1)) * 60
    try:
        return float(s.replace("s", "").replace("秒", "").strip())
    except ValueError:
        return 0


def _classify_failure(err_info):
    err = (err_info or "").strip()
    if any(c in err for c in ("504", "502", "503", "500", "Gateway")):
        return "上游jira卡住问题"
    if re.search(r"第\d+轮.*调用失败", err):
        return "模型调用失败"
    if "no space" in err.lower():
        return "磁盘空间不足"
    if "日志为空" in err or "日志过滤" in err or "gmlogger" in err.lower():
        return "日志过滤逻辑"
    return "待开发排查"


# ─── 数据组装 ───

def build_batch_data(batch_name, source, rows, bt_map):
    """组装一个批次的完整数据（CSV + 多维表格交叉），结构与日报 batchData 一致"""
    jira_ids = [r.get("jira号", "") for r in rows]
    total = len(rows)
    submit_ok = sum(1 for r in rows if r.get("执行结果", "") not in ("失败", ""))
    submit_fail = total - submit_ok
    exec_time = ""
    model = ""
    for r in rows:
        if not exec_time:
            exec_time = r.get("执行时间", "")
        if not model:
            model = r.get("模型", "")
    src = source
    for r in rows:
        ts = r.get("触发来源", "")
        if ts:
            src = ts
            break

    # 逐条匹配多维表格
    bt_ok = bt_fail = bt_miss = 0
    durations = []
    jira_details = []
    fail_details = []

    for br in rows:
        jid = br.get("jira号", "")
        bt_recs = bt_map.get(jid, [])
        d = {
            "jira": jid,
            "trigger_time": br.get("触发时间", ""),
            "exec_result": br.get("执行结果", ""),
            "bt_result": "",
            "fail_cat": "",
            "err_msg": "",
            "total_dur": 0,
            "analysis_dur": 0,
        }
        if bt_recs:
            exec_t = br.get("执行时间", "")
            candidates = [r for r in bt_recs if r.get("分析完成时间", "") and r["分析完成时间"] >= exec_t]
            if not candidates:
                candidates = bt_recs
            candidates.sort(key=lambda x: x.get("分析完成时间", ""))
            success_recs = [r for r in candidates if r.get("分析结果", "") == "成功"]
            bf = success_recs[0] if success_recs else candidates[-1]
            result = bf.get("分析结果", "")
            d["bt_result"] = result
            d["total_dur"] = _parse_dur_sec(bf.get("总耗时", ""))
            d["analysis_dur"] = _parse_dur_sec(bf.get("分析耗时", ""))
            d["err_msg"] = (bf.get("错误信息", "") or "")[:80]
            if d["analysis_dur"] > 0:
                durations.append(d["analysis_dur"])
            if result == "成功":
                bt_ok += 1
            else:
                bt_fail += 1
                d["fail_cat"] = _classify_failure(d["err_msg"])
                fail_details.append(d)
        else:
            bt_miss += 1
            d["bt_result"] = "分析中"
        jira_details.append(d)

    bt_match = bt_ok + bt_fail
    rate = round(bt_ok / bt_match * 100, 1) if bt_match else 0
    avg_dur = round(sum(durations) / len(durations)) if durations else 0
    max_dur = max(durations) if durations else 0
    min_dur = min(durations) if durations else 0

    return {
        "name": batch_name,
        "exec": exec_time[:16],
        "src": src,
        "model": model or "deepseek-v-pro",
        "total": total,
        "submitOk": submit_ok,
        "submitFail": submit_fail,
        "btMatch": bt_match,
        "btOk": bt_ok,
        "btFail": bt_fail,
        "btMiss": bt_miss,
        "avgDur": avg_dur,
        "maxDur": max_dur,
        "minDur": min_dur,
        "rate": rate,
        "durations": [round(d) for d in durations],
        "jira_details": jira_details,
        "fail_details": fail_details,
    }


# ─── HTML 生成（完全仿照 daily_report 结构）───

_CSS = """:root{--bg:#0f1117;--card:#1a1d2e;--border:#2a2d3e;--text:#e2e8f0;--muted:#8892a8;--accent:#6366f1;--green:#22c55e;--red:#ef4444;--orange:#f59e0b;--blue:#3b82f6;--cyan:#06b6d4;--purple:#a78bfa}
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:-apple-system,'Segoe UI','PingFang SC','Microsoft YaHei',sans-serif;background:var(--bg);color:var(--text);line-height:1.7;padding:20px}
.container{max-width:1400px;margin:0 auto}
h1{font-size:26px;font-weight:700;background:linear-gradient(135deg,#6366f1,#a78bfa);-webkit-background-clip:text;background-clip:text;-webkit-text-fill-color:transparent}
.subtitle{color:var(--muted);font-size:13px;margin:4px 0 24px}
.grid-2{display:grid;grid-template-columns:1fr 1fr;gap:16px}
.grid-3{display:grid;grid-template-columns:1fr 1fr 1fr;gap:16px}
.grid-4{display:grid;grid-template-columns:repeat(4,1fr);gap:12px}
@media(max-width:1000px){.grid-2,.grid-3,.grid-4{grid-template-columns:1fr}}
.card{background:var(--card);border:1px solid var(--border);border-radius:12px;padding:18px}
.card-label{font-size:11px;color:var(--muted);text-transform:uppercase;letter-spacing:.5px}
.card-value{font-size:28px;font-weight:700;margin:4px 0}
.card-sub{font-size:11px;color:var(--muted)}
.section{margin:28px 0}
.section-title{font-size:16px;font-weight:600;margin-bottom:14px;display:flex;align-items:center;gap:8px}
.section-title::before{content:'';display:inline-block;width:4px;height:18px;background:var(--accent);border-radius:2px}
.chart-box{background:var(--card);border:1px solid var(--border);border-radius:12px;padding:16px;margin-bottom:20px}
.chart-title{font-size:14px;font-weight:600;margin-bottom:10px}
table{width:100%;border-collapse:collapse;font-size:12px}
th,td{padding:8px 10px;text-align:left;border-bottom:1px solid var(--border)}
th{color:var(--muted);font-weight:600;font-size:11px;text-transform:uppercase;letter-spacing:.3px;position:sticky;top:0;background:var(--card)}
tr:hover{background:rgba(99,102,241,.06)}
.tag{display:inline-block;padding:2px 8px;border-radius:4px;font-size:10px;font-weight:600}
.tag-ok{background:rgba(34,197,94,.15);color:var(--green)}
.tag-fail{background:rgba(239,68,68,.15);color:var(--red)}
.tag-warn{background:rgba(245,158,11,.15);color:var(--orange)}
.tag-info{background:rgba(59,130,246,.15);color:var(--blue)}
.bar{height:6px;border-radius:3px;background:#2a2d3e;overflow:hidden;position:relative}
.bar-fill{height:100%;border-radius:3px;transition:width .3s}
.green{color:var(--green)}.red{color:var(--red)}.orange{color:var(--orange)}.blue{color:var(--blue)}.cyan{color:var(--cyan)}.purple{color:var(--purple)}
.bg-green{background:var(--green)}.bg-red{background:var(--red)}.bg-orange{background:var(--orange)}.bg-blue{background:var(--blue)}
.conclusion{background:linear-gradient(135deg,rgba(99,102,241,.08),rgba(167,139,250,.05));border:1px solid rgba(99,102,241,.25);border-radius:12px;padding:20px;margin-top:24px}
.conclusion h3{font-size:15px;color:var(--accent);margin-bottom:12px}
.conclusion li{margin:6px 0;font-size:13px;line-height:1.7}
.table-wrap{max-height:500px;overflow:auto;border-radius:8px;border:1px solid var(--border)}
.batch-header{display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:8px}
.batch-meta{font-size:11px;color:var(--muted)}"""


def generate_html(b, gen_date):
    """生成与 daily_report 完全一致的 HTML 结构"""
    name, src = b["name"], b["src"]
    src_tag = "tag-info" if src == "PC" else "tag-warn"
    rate_class = "green" if b["rate"] >= 80 else ("orange" if b["rate"] >= 60 else "red")
    src_api = {"PC": "jira_analyze", "线上": "parseFullTicket"}.get(src, "parseFullTicket")

    # JS 数据（与日报 batchData 结构完全一致）
    batch_js = (
        f'{{name:"{name}",exec:"{b["exec"][5:]}",src:"{src}",'
        f'total:{b["total"]},submitOk:{b["submitOk"]},submitFail:{b["submitFail"]},'
        f'btMatch:{b["btMatch"]},btOk:{b["btOk"]},btFail:{b["btFail"]},btMiss:{b["btMiss"]},'
        f'avgDur:{b["avgDur"]},maxDur:{b["maxDur"]}}}'
    )

    # Jira 详情 JSON
    jiras_json = json.dumps(b["jira_details"], ensure_ascii=False)
    # 耗时数组
    all_dur_json = json.dumps(b["durations"])

    # 失败详情 HTML（与日报失败详情表结构一致）
    fail_rows = ""
    for fd in b["fail_details"]:
        fail_rows += (
            f'<tr><td>{name}</td>'
            f'<td><span class="tag {src_tag}">{src}</span></td>'
            f'<td style="font-weight:600">{fd["jira"]}</td>'
            f'<td><span class="tag tag-fail">{fd["fail_cat"]}</span></td>'
            f'<td style="color:var(--muted)">{fd["err_msg"]}</td>'
            f'<td>{round(fd["analysis_dur"])}s</td></tr>\n'
        )

    # 结论（与日报结论格式一致）
    conclusion = []
    conclusion.append(
        f'<li><strong>{name}</strong>（{b["exec"]}）共提交 <strong>{b["total"]} 个 Bug</strong>，'
        f'来源 <strong>{src}</strong>，提交成功 {b["submitOk"]}/{b["total"]}</li>'
    )
    conclusion.append(
        f'<li><strong>多维表格分析成功 {b["btOk"]} 个</strong>'
        f'（匹配 {b["btMatch"]}，成功率 <strong>{b["rate"]}%</strong>）'
        + (f'，{b["btMiss"]} 个分析中待出结果' if b["btMiss"] else '') + '</li>'
    )
    if b["btFail"] > 0:
        cats = {}
        for fd in b["fail_details"]:
            cats[fd["fail_cat"]] = cats.get(fd["fail_cat"], 0) + 1
        cat_desc = "、".join(f'{c}({n}个)' for c, n in cats.items())
        conclusion.append(f'<li><strong>{b["btFail"]} 个分析失败</strong>：{cat_desc}</li>')
    if b["durations"]:
        too_long = sum(1 for d in b["durations"] if d > 900)
        pct = round(too_long / len(b["durations"]) * 100, 1)
        conclusion.append(
            f'<li><strong>分析耗时均值 {round(b["avgDur"]/60,1)}min</strong>'
            f'（{b["btMatch"]} 个已出结果），最短 {b["minDur"]}s，'
            f'最长 {round(b["maxDur"]/60,1)}min'
            + (f'；{too_long} 个超过 15 分钟阈值（{pct}%）' if too_long else '') + '</li>'
        )
    if b["rate"] >= 80:
        conclusion.append('<li>整体表现 <strong class="green">良好</strong></li>')
    elif b["rate"] >= 50:
        conclusion.append('<li>整体表现 <strong class="orange">一般</strong>，建议排查失败原因</li>')
    else:
        conclusion.append('<li>整体表现 <strong class="red">偏差</strong>，需要重点关注失败项</li>')
    conclusion_html = "\n    ".join(conclusion)

    # 待分析数
    pending_note = f' · 待分析 {b["btMiss"]}' if b["btMiss"] else ""

    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>批次执行报告 · {name}</title>
<script src="https://cdn.jsdelivr.net/npm/echarts@5/dist/echarts.min.js"></script>
<style>
{_CSS}
</style>
</head>
<body>
<div class="container">

<h1>批次执行报告 · {name}</h1>
<p class="subtitle">数据来源：批次 CSV + 多维表格分析结果 · 生成时间：{gen_date}</p>

<!-- ========== 顶部概览 ========== -->
<div class="grid-4">
  <div class="card"><div class="card-label">批次名称</div><div class="card-value cyan" style="font-size:18px">{name}</div><div class="card-sub">{src}</div></div>
  <div class="card"><div class="card-label">总提交 Bug</div><div class="card-value blue">{b["total"]}</div><div class="card-sub">提交成功 {b["submitOk"]} 个</div></div>
  <div class="card"><div class="card-label">多维表格分析成功</div><div class="card-value green">{b["btOk"]}</div><div class="card-sub">总匹配 {b["btMatch"]} / 成功率 {b["rate"]}%</div></div>
  <div class="card"><div class="card-label">分析耗时均值</div><div class="card-value purple">{round(b["avgDur"]/60,1)}min</div><div class="card-sub">最短 {b["minDur"]}s · 最大 {round(b["maxDur"]/60,1)}min</div></div>
</div>

<!-- ========== 批次信息 + 多维表格汇总 ========== -->
<div class="section">
  <div class="section-title">批次分析结果汇总（多维表格验证）</div>
  <div class="grid-2">
    <div class="card">
      <div class="batch-header">
        <div><span class="tag {src_tag}">{src}</span></div>
        <div class="batch-meta">1 批次 · {src_api} · {b["model"]}</div>
      </div>
      <div class="grid-4" style="margin-top:12px">
        <div><div class="card-label">提交数</div><div style="font-size:22px;font-weight:700">{b["total"]}</div></div>
        <div><div class="card-label">成功</div><div style="font-size:22px;font-weight:700" class="green">{b["btOk"]}</div></div>
        <div><div class="card-label">失败</div><div style="font-size:22px;font-weight:700" class="red">{b["btFail"]}</div></div>
        <div><div class="card-label">成功率</div><div style="font-size:22px;font-weight:700" class="{rate_class}">{b["rate"]}%</div></div>
      </div>
      <div style="margin-top:10px;font-size:12px;color:var(--muted)">耗时: 均 {b["avgDur"]}s({round(b["avgDur"]/60,1)}min) · 最大 {b["maxDur"]}s({round(b["maxDur"]/60,1)}min){pending_note}</div>
    </div>
    <div class="card">
      <div class="batch-header">
        <div>执行信息</div>
        <div class="batch-meta">{b["exec"]}</div>
      </div>
      <div class="grid-4" style="margin-top:12px">
        <div><div class="card-label">提交成功</div><div style="font-size:22px;font-weight:700" class="green">{b["submitOk"]}</div></div>
        <div><div class="card-label">提交失败</div><div style="font-size:22px;font-weight:700" class="red">{b["submitFail"]}</div></div>
        <div><div class="card-label">表格匹配</div><div style="font-size:22px;font-weight:700" class="blue">{b["btMatch"]}</div></div>
        <div><div class="card-label">未匹配</div><div style="font-size:22px;font-weight:700" class="orange">{b["btMiss"]}</div></div>
      </div>
      <div style="margin-top:10px;font-size:12px;color:var(--muted)">模型: {b["model"]}</div>
    </div>
  </div>
</div>

<!-- ========== 图表区 ========== -->
<div class="section">
  <div class="section-title">图表分析</div>

  <!-- 图1：提交成功 vs 分析成功（与日报图1同结构） -->
  <div class="chart-box">
    <div class="chart-title">提交成功 vs 多维表格分析成功（柱状对比）</div>
    <div id="chart_submit_vs_analysis" style="height:380px"></div>
  </div>

  <div class="grid-2">
    <!-- 图2：分析成功率（与日报图2同结构） -->
    <div class="chart-box">
      <div class="chart-title">分析成功率（多维表格匹配后）</div>
      <div id="chart_success_rate" style="height:340px"></div>
    </div>
    <!-- 图3：平均分析耗时（与日报图3同结构） -->
    <div class="chart-box">
      <div class="chart-title">平均分析耗时（分钟）</div>
      <div id="chart_avg_duration" style="height:340px"></div>
    </div>
  </div>

  <!-- 图4：耗时分布直方图（与日报图4同结构） -->
  <div class="chart-box">
    <div class="chart-title">分析耗时分布（秒）</div>
    <div id="chart_duration_hist" style="height:300px"></div>
  </div>
</div>

<!-- ========== Jira 详情表（与日报批次详情表同结构） ========== -->
<div class="section">
  <div class="section-title">Jira 详情（CSV + 多维表格验证）</div>
  <div class="table-wrap">
  <table>
    <thead>
      <tr>
        <th>#</th>
        <th>Jira号</th>
        <th>触发时间</th>
        <th>提交</th>
        <th>分析结果</th>
        <th>失败分类</th>
        <th>错误信息</th>
        <th>分析耗时</th>
        <th>状态</th>
      </tr>
    </thead>
    <tbody id="jiraTableBody"></tbody>
  </table>
  </div>
</div>

<!-- ========== 失败详情（与日报失败详情完全一致） ========== -->
<div class="section">
  <div class="section-title">失败详情</div>
  <div class="table-wrap">
  <table>
    <thead><tr><th>批次</th><th>来源</th><th>Jira号</th><th>失败分类</th><th>错误信息</th><th>分析耗时</th></tr></thead>
    <tbody>
      {fail_rows}
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
const batchData = [{batch_js}];
const jiras = {jiras_json};
const allDurations = {all_dur_json};

// ===== 图1: 提交成功 vs 分析成功（与日报完全一致） =====
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

// ===== 图2: 分析成功率（与日报完全一致） =====
const chart2 = echarts.init(document.getElementById('chart_success_rate'));
const rateData = batchData.map(b => b.btMatch > 0 ? Math.round(b.btOk / b.btMatch * 100) : 0);
chart2.setOption({{
  tooltip:{{trigger:'axis',formatter:p=>`${{p[0].name}}<br/>成功率: ${{p[0].value}}%`}},
  grid:{{left:45,right:15,bottom:60,top:20}},
  xAxis:{{type:'category',data:batchData.map(b=>b.name),axisLabel:{{rotate:40,color:'#8892a8',fontSize:9}},axisLine:{{lineStyle:{{color:'#2a2d3e'}}}}}},
  yAxis:{{type:'value',max:100,axisLabel:{{formatter:'{{value}}%',color:'#8892a8'}},splitLine:{{lineStyle:{{color:'#1e2030'}}}}}},
  series:[{{type:'bar',data:rateData.map(v=>({{value:v,itemStyle:{{color:v>=70?'#22c55e':v>=50?'#f59e0b':'#ef4444'}}}})),barMaxWidth:40}}]
}});

// ===== 图3: 平均耗时（与日报完全一致） =====
const chart3 = echarts.init(document.getElementById('chart_avg_duration'));
chart3.setOption({{
  tooltip:{{trigger:'axis',formatter:p=>`${{p[0].name}}<br/>平均: ${{p[0].value?p[0].value.toFixed(1):'-'}}min<br/>最大: ${{p[1]&&p[1].value?p[1].value.toFixed(1):'-'}}min`}},
  grid:{{left:45,right:15,bottom:60,top:30}},
  xAxis:{{type:'category',data:batchData.map(b=>b.name),axisLabel:{{rotate:40,color:'#8892a8',fontSize:9}},axisLine:{{lineStyle:{{color:'#2a2d3e'}}}}}},
  yAxis:{{type:'value',name:'分钟',nameTextStyle:{{color:'#8892a8'}},axisLabel:{{color:'#8892a8'}},splitLine:{{lineStyle:{{color:'#1e2030'}}}}}},
  series:[
    {{name:'平均耗时',type:'bar',data:batchData.map(b=>b.avgDur>0?+(b.avgDur/60).toFixed(1):null),itemStyle:{{color:'#a78bfa'}},barGap:'10%',barMaxWidth:40}},
    {{name:'最大耗时',type:'line',data:batchData.map(b=>b.maxDur>0?+(b.maxDur/60).toFixed(1):null),lineStyle:{{color:'#ef4444',width:2}},symbol:'circle',symbolSize:6,itemStyle:{{color:'#ef4444'}}}}
  ]
}});

// ===== 图4: 耗时分布直方图（与日报完全一致） =====
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

// ===== Jira 详情表（与日报 batchTableBody 结构一致） =====
const tbody = document.getElementById('jiraTableBody');
jiras.forEach((j,i)=>{{
  const execTag = j.exec_result !== '失败' ? '<span class="tag tag-ok">成功</span>' : '<span class="tag tag-fail">失败</span>';
  const btTag = j.bt_result === '成功' ? '<span class="tag tag-ok">成功</span>' : j.bt_result === '失败' ? '<span class="tag tag-fail">失败</span>' : '<span class="tag tag-warn">分析中</span>';
  const rateNum = {b["rate"]};
  const statusTag = j.bt_result === '成功' ? '<span class="tag tag-ok">正常</span>' : j.bt_result === '失败' ? '<span class="tag tag-fail">异常</span>' : '<span class="tag tag-warn">待分析</span>';
  const durStr = j.analysis_dur > 0 ? j.analysis_dur + 's' : '—';
  tbody.innerHTML += `<tr>
    <td>${{i+1}}</td>
    <td style="font-weight:600">${{j.jira}}</td>
    <td style="font-size:11px">${{j.trigger_time||'—'}}</td>
    <td>${{execTag}}</td>
    <td>${{btTag}}</td>
    <td>${{j.fail_cat?'<span class="tag tag-fail">'+j.fail_cat+'</span>':'—'}}</td>
    <td style="font-size:11px;color:var(--muted);max-width:250px;overflow:hidden;text-overflow:ellipsis">${{j.err_msg||'—'}}</td>
    <td>${{durStr}}</td>
    <td>${{statusTag}}</td>
  </tr>`;
}});

// 响应式
window.addEventListener('resize',()=>{{chart1.resize();chart2.resize();chart3.resize();chart4.resize()}});
</script>
</body>
</html>"""
    return html


# ─── 入口 ───

def main():
    date_str = sys.argv[1] if len(sys.argv) > 1 else datetime.now().strftime("%Y-%m-%d")
    target_batch = sys.argv[2] if len(sys.argv) > 2 else None
    print(f"收集 {date_str} 的批次数据...")
    batches = collect_batches(date_str)
    if not batches:
        print(f"未找到 {date_str} 的批次 CSV")
        sys.exit(1)
    print(f"找到 {len(batches)} 个批次:")
    for name, src, rows in batches:
        print(f"  [{src}] {name} ({len(rows)} 行)")

    # 查多维表格
    all_jira_ids = []
    for _, _, rows in batches:
        all_jira_ids.extend(r.get("jira号", "") for r in rows)
    print("查询多维表格分析结果...")
    bt_map = _query_bitable(all_jira_ids)
    print(f"匹配到 {len(bt_map)} 个 Jira 的多维表格记录")

    gen_date = datetime.now().strftime("%Y-%m-%d %H:%M")
    out_dir = os.path.join(REPORTS_DIR, date_str)
    os.makedirs(out_dir, exist_ok=True)
    generated = []
    for name, src, rows in batches:
        if target_batch and target_batch != name:
            continue
        b = build_batch_data(name, src, rows, bt_map)
        html = generate_html(b, gen_date)
        out_path = os.path.join(out_dir, f"{name}_{date_str}.html")
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(html)
        generated.append((name, out_path, len(html)))
        print(f"  ✓ {out_path} ({len(html)} 字符)")
        print(f"    提交{b['submitOk']}/{b['total']} | 分析成功{b['btOk']} 失败{b['btFail']} 未匹配{b['btMiss']} | 成功率{b['rate']}%")
    if not generated:
        print(f"未找到匹配 '{target_batch}' 的批次")
        sys.exit(1)
    print(f"\n共生成 {len(generated)} 个批次报告，输出: {out_dir}")


if __name__ == "__main__":
    main()
