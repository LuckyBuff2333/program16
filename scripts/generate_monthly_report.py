#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""月度复盘报告生成器（按 timestudy/2026-09_ai_analysis_report_v3.html 格式）

用法: python scripts/generate_monthly_report.py [年月]
默认: 当前月 (格式: 2026-10)
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
    if not os.path.exists(path):
        return []
    return list(csv.DictReader(open(path, encoding="utf-8-sig")))


def _clean_row(r):
    return {k.replace("\ufeff", ""): v.strip() for k, v in r.items()}


def collect_monthly_data(year_month):
    """收集指定月份所有批次数据，按日期和来源分组"""
    doc_base = os.path.join(PROJECT_ROOT, "docs")
    unan_dir = os.path.join(PROJECT_ROOT, "data", "unanalyzed")
    daily_data = defaultdict(lambda: {"PC": [], "线上": []})

    # 1. docs/日期/batch_*.csv
    if os.path.isdir(doc_base):
        for date_dir in sorted(os.listdir(doc_base)):
            if not date_dir.startswith(year_month):
                continue
            date_path = os.path.join(doc_base, date_dir)
            if not os.path.isdir(date_path):
                continue
            for f in sorted(os.listdir(date_path)):
                if f.startswith("batch_") and f.endswith(".csv"):
                    rows = [_clean_row(r) for r in _read_csv(os.path.join(date_path, f))]
                    daily_data[date_dir]["PC"].extend(rows)

    # 2. data/unanalyzed/prod_batch_日期_*.csv
    if os.path.isdir(unan_dir):
        for f in sorted(os.listdir(unan_dir)):
            if not f.startswith("prod_batch_") or not f.endswith(".csv"):
                continue
            parts = f.replace("prod_batch_", "").split("_")
            if len(parts) < 2:
                continue
            date_str = parts[0]
            if not date_str.startswith(year_month):
                continue
            rows = [_clean_row(r) for r in _read_csv(os.path.join(unan_dir, f))]
            daily_data[date_str]["线上"].extend(rows)

    return daily_data


def analyze_month(daily_data):
    """分析月度统计"""
    pc_total = 0
    pc_ok = 0
    pc_fail = 0
    pc_unmatch = 0
    on_total = 0
    on_ok = 0
    on_fail = 0
    on_unmatch = 0
    pc_daily = defaultdict(lambda: {"ok": 0, "fail": 0})
    on_daily = defaultdict(lambda: {"ok": 0, "fail": 0})
    pc_errors = defaultdict(int)
    on_errors = defaultdict(int)

    for date_str, sources in sorted(daily_data.items()):
        for r in sources["PC"]:
            pc_total += 1
            status = r.get("分析状态", r.get("执行结果", ""))
            error = r.get("错误信息", "")
            if status in ("成功", "已分析"):
                pc_ok += 1
                pc_daily[date_str]["ok"] += 1
            elif status in ("错误", "失败"):
                pc_fail += 1
                pc_daily[date_str]["fail"] += 1
                err_key = _classify_error(error)
                pc_errors[err_key] += 1
            else:
                pc_unmatch += 1

        for r in sources["线上"]:
            on_total += 1
            status = r.get("分析状态", r.get("执行结果", ""))
            error = r.get("错误信息", "")
            if status in ("成功", "已分析"):
                on_ok += 1
                on_daily[date_str]["ok"] += 1
            elif status in ("错误", "失败"):
                on_fail += 1
                on_daily[date_str]["fail"] += 1
                err_key = _classify_error(error)
                on_errors[err_key] += 1
            else:
                on_unmatch += 1

    return {
        "pc_total": pc_total, "pc_ok": pc_ok, "pc_fail": pc_fail, "pc_unmatch": pc_unmatch,
        "on_total": on_total, "on_ok": on_ok, "on_fail": on_fail, "on_unmatch": on_unmatch,
        "pc_rate": round(pc_ok / pc_total * 100, 1) if pc_total > 0 else 0,
        "on_rate": round(on_ok / on_total * 100, 1) if on_total > 0 else 0,
        "pc_daily": dict(pc_daily), "on_daily": dict(on_daily),
        "pc_errors": dict(pc_errors), "on_errors": dict(on_errors),
    }


def _classify_error(error):
    """错误分类"""
    if not error:
        return "未知原因"
    e = error.lower()
    if "no space" in e or "磁盘" in e:
        return "磁盘空间不足"
    if "超时" in e or "timeout" in e or "timed out" in e:
        return "分析超时"
    if "时间过滤后日志为空" in e:
        return "触发时间不准"
    if "未找到有效" in e or "没有找到" in e:
        return "日志文件缺失"
    if "无gmlogger" in e or "gmlogger" in e:
        return "无日志附件"
    if "服务" in e and "报错" in e:
        return "服务端报错"
    if "llm" in e or "模型" in e or "api" in e:
        return "AI模型调用失败"
    return "其他"


def generate_html(year_month, stats, daily_data):
    """生成月度复盘报告 HTML"""
    pc_t = stats["pc_total"]
    pc_o = stats["pc_ok"]
    pc_f = stats["pc_fail"]
    pc_u = stats["pc_unmatch"]
    pc_r = stats["pc_rate"]
    on_t = stats["on_total"]
    on_o = stats["on_ok"]
    on_f = stats["on_fail"]
    on_u = stats["on_unmatch"]
    on_r = stats["on_rate"]
    total = pc_t + on_t
    total_ok = pc_o + on_o
    total_rate = round(total_ok / total * 100, 1) if total > 0 else 0

    # 所有错误类型
    all_err_keys = sorted(set(list(stats["pc_errors"].keys()) + list(stats["on_errors"].keys())))
    # 每日趋势数据
    all_days = sorted(set(list(stats["pc_daily"].keys()) + list(stats["on_daily"].keys())))
    pc_days = sorted(stats["pc_daily"].keys())
    on_days = sorted(stats["on_daily"].keys())

    now = datetime.now().strftime("%Y-%m-%d")
    month_cn = f"{year_month[:4]}年{int(year_month[5:7])}月"

    # 进度条
    pc_prog_ok = round(pc_o / pc_t * 100, 1) if pc_t > 0 else 0
    pc_prog_fail = round(pc_f / pc_t * 100, 1) if pc_t > 0 else 0
    pc_prog_unmatch = round(pc_u / pc_t * 100, 1) if pc_t > 0 else 0
    on_prog_ok = round(on_o / on_t * 100, 1) if on_t > 0 else 0
    on_prog_fail = round(on_f / on_t * 100, 1) if on_t > 0 else 0
    on_prog_unmatch = round(on_u / on_t * 100, 1) if on_t > 0 else 0

    # 错误条目 HTML
    def make_error_items(err_key, pc_count, on_count):
        is_pc = pc_count > 0
        is_on = on_count > 0
        tags = ""
        if is_pc:
            tags += '<span class="tag tag-pc">PC</span> '
        if is_on:
            tags += '<span class="tag tag-online">线上</span> '
        mode = "PC" if is_pc and not is_on else "线上" if is_on and not is_pc else "共同"
        bg_class = "analysis-bg" if err_key in ("触发时间不准", "日志文件缺失", "无日志附件", "AI模型调用失败") else "exec-bg"
        tag_class = "tag-analysis" if bg_class == "analysis-bg" else "tag-exec"
        tag_label = "🔬 分析问题" if bg_class == "analysis-bg" else "🔧 执行问题"
        total_count = pc_count + on_count
        return f"""
    <div class="err-sec">
        <div class="err-hdr {bg_class}"><span class="tag {tag_class}">{tag_label}</span><h3>{err_key} <span class="badge">{total_count} 条</span></h3>{tags}</div>
        <div class="err-body">
            <p>PC: {pc_count} 条 · 线上: {on_count} 条</p>
        </div>
    </div>"""

    error_html = ""
    for k in sorted(all_err_keys, key=lambda x: -(stats["pc_errors"].get(x, 0) + stats["on_errors"].get(x, 0))):
        error_html += make_error_items(k, stats["pc_errors"].get(k, 0), stats["on_errors"].get(k, 0))

    # JS 数据
    pc_days_js = json.dumps([d[5:] for d in pc_days])
    pc_ok_js = json.dumps([stats["pc_daily"][d]["ok"] for d in pc_days])
    pc_fail_js = json.dumps([stats["pc_daily"][d]["fail"] for d in pc_days])
    on_days_js = json.dumps([d[5:] for d in on_days])
    on_ok_js = json.dumps([stats["on_daily"][d]["ok"] for d in on_days])
    on_fail_js = json.dumps([stats["on_daily"][d]["fail"] for d in on_days])

    err_cats = json.dumps(all_err_keys, ensure_ascii=False)
    pc_err_js = json.dumps([stats["pc_errors"].get(k, 0) for k in all_err_keys])
    on_err_js = json.dumps([stats["on_errors"].get(k, 0) for k in all_err_keys])

    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>{month_cn} AI日志分析复盘报告（PC/线上分维度）</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0"></script>
<style>
*{{margin:0;padding:0;box-sizing:border-box}}
body{{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI','PingFang SC',sans-serif;background:#f0f2f5;color:#333;line-height:1.7}}
.ctn{{max-width:1480px;margin:0 auto;padding:24px}}
.hdr{{background:linear-gradient(135deg,#0f0c29,#302b63,#24243e);color:#fff;padding:44px 40px;border-radius:16px;margin-bottom:28px;position:relative;overflow:hidden}}
.hdr::after{{content:'';position:absolute;top:-40%;right:-5%;width:360px;height:360px;background:radial-gradient(circle,rgba(102,126,234,0.12),transparent);border-radius:50%}}
.hdr h1{{font-size:2.2em;margin-bottom:8px;position:relative;z-index:1}}
.hdr .sub{{opacity:.78;font-size:1em;position:relative;z-index:1}}
.card{{background:#fff;border-radius:14px;padding:26px;margin-bottom:24px;box-shadow:0 1px 6px rgba(0,0,0,.05);border:1px solid #e8ecf1}}
.card h2{{font-size:1.3em;margin-bottom:18px;padding-bottom:12px;border-bottom:2px solid #f0f2f5;display:flex;align-items:center;gap:10px}}
.ico{{width:30px;height:30px;border-radius:8px;display:flex;align-items:center;justify-content:center;font-size:1em}}
.split{{display:grid;grid-template-columns:1fr 1fr;gap:20px}}
@media(max-width:900px){{.split,.chart-row{{grid-template-columns:1fr}}}}
.mode-card{{border-radius:12px;padding:22px;position:relative;overflow:hidden}}
.mode-card.pc{{background:linear-gradient(135deg,#e3f2fd,#bbdefb);border:1px solid #90caf9}}
.mode-card.online{{background:linear-gradient(135deg,#fce4ec,#f8bbd0);border:1px solid #f48fb1}}
.mode-card .mode-label{{font-size:1.3em;font-weight:700;margin-bottom:12px}}
.mode-card.pc .mode-label{{color:#1565c0}}
.mode-card.online .mode-label{{color:#c62828}}
.mode-card .mode-num{{font-size:2.6em;font-weight:800;line-height:1.1}}
.mode-card.pc .mode-num{{color:#1976d2}}
.mode-card.online .mode-num{{color:#d32f2f}}
.mode-card .mode-sub{{font-size:.88em;color:#555;margin-top:6px}}
.mode-card .mode-row{{display:flex;justify-content:space-between;padding:4px 0;font-size:.88em;border-bottom:1px solid rgba(0,0,0,.06)}}
.mode-card .mode-row:last-child{{border:none}}
.tag{{display:inline-block;padding:2px 10px;border-radius:10px;font-size:.76em;font-weight:600;letter-spacing:.3px}}
.tag-pc{{background:#e3f2fd;color:#1565c0}}
.tag-online{{background:#fce4ec;color:#c62828}}
.tag-exec{{background:#e8eaf6;color:#3949ab}}
.tag-analysis{{background:#fce4ec;color:#c62828}}
.tag-ok{{background:#d4edda;color:#155724}}
.tag-err{{background:#f8d7da;color:#721c24}}
.tag-warn{{background:#fff3cd;color:#856404}}
.chart-row{{display:grid;grid-template-columns:1fr 1fr;gap:20px}}
.chart-box{{position:relative;height:320px}}
.err-sec{{margin:14px 0;border-radius:10px;overflow:hidden;border:1px solid #e8ecf1}}
.err-hdr{{padding:14px 18px;display:flex;align-items:center;gap:10px}}
.err-hdr.exec-bg{{background:linear-gradient(135deg,#e8eaf6,#c5cae9)}}
.err-hdr.analysis-bg{{background:linear-gradient(135deg,#fce4ec,#f8bbd0)}}
.err-hdr h3{{font-size:1em;flex:1}}
.err-hdr .badge{{background:rgba(0,0,0,.07);padding:2px 10px;border-radius:10px;font-size:.83em;font-weight:600}}
.err-body{{padding:14px 18px;background:#fff;font-size:.92em}}
.err-body ul{{margin:6px 0 0 18px}}
.err-body li{{margin:3px 0;color:#4a5568}}
.rec{{background:linear-gradient(135deg,#e3f2fd,#bbdefb);border-radius:12px;padding:20px;margin:14px 0;border-left:4px solid #1976d2}}
.rec h4{{color:#0d47a1;margin-bottom:8px;font-size:1em}}
.rec ul{{margin:0 0 0 18px}}
.rec li{{margin:5px 0;color:#1565c0;font-size:.9em}}
table{{width:100%;border-collapse:collapse;font-size:.86em}}
th,td{{padding:9px 12px;text-align:left;border-bottom:1px solid #f0f2f5}}
th{{background:#f8fafc;font-weight:600;color:#475569}}
tr:hover{{background:#f8fafc}}
.legend{{display:flex;gap:16px;flex-wrap:wrap;margin:10px 0;font-size:.86em}}
.legend-item{{display:flex;align-items:center;gap:5px}}
.legend-dot{{width:12px;height:12px;border-radius:3px}}
.footer{{text-align:center;padding:28px;color:#94a3b8;font-size:.86em}}
.progress{{display:flex;height:26px;border-radius:8px;overflow:hidden;margin:6px 0}}
.progress div{{display:flex;align-items:center;justify-content:center;color:#fff;font-size:.78em;font-weight:600}}
</style>
</head>
<body>
<div class="ctn">
<div class="hdr">
    <h1>📊 {month_cn} AI日志分析复盘报告</h1>
    <p class="sub">PC / 线上 分维度统计 · 报告周期 {year_month} · 生成 {now} · 数据源: 本地 CSV 批次文件</p>
</div>

<!-- 1. PC/线上分栏 -->
<div class="card">
    <h2><span class="ico" style="background:#e8eaf6">📈</span>总体概况（PC / 线上分别统计）</h2>
    <div class="split">
        <div class="mode-card pc">
            <div class="mode-label">💻 PC 执行</div>
            <div class="mode-num">{pc_r}%</div>
            <div class="mode-sub">成功率（{pc_o} / {pc_t}）</div>
            <div style="margin-top:12px">
                <div class="mode-row"><span>总记录</span><span><strong>{pc_t}</strong> 条</span></div>
                <div class="mode-row"><span>分析成功</span><span style="color:#2e7d32"><strong>{pc_o}</strong></span></div>
                <div class="mode-row"><span>分析失败</span><span style="color:#c62828"><strong>{pc_f}</strong></span></div>
                <div class="mode-row"><span>待分析/未匹配</span><span style="color:#f57f17">{pc_u}</span></div>
            </div>
            <div class="progress" style="margin-top:10px">
                <div style="width:{pc_prog_ok}%;background:linear-gradient(90deg,#42a5f5,#1976d2)">{pc_o} 成功</div>
                <div style="width:{pc_prog_fail}%;background:linear-gradient(90deg,#ef5350,#c62828)">{pc_f if pc_f else ''}</div>
                <div style="width:{pc_prog_unmatch}%;background:#feca57">{pc_u if pc_u else ''}</div>
            </div>
        </div>
        <div class="mode-card online">
            <div class="mode-label">🌐 线上执行</div>
            <div class="mode-num">{on_r}%</div>
            <div class="mode-sub">成功率（{on_o} / {on_t}）</div>
            <div style="margin-top:12px">
                <div class="mode-row"><span>总记录</span><span><strong>{on_t}</strong> 条</span></div>
                <div class="mode-row"><span>分析成功</span><span style="color:#2e7d32"><strong>{on_o}</strong></span></div>
                <div class="mode-row"><span>分析失败</span><span style="color:#c62828"><strong>{on_f}</strong></span></div>
                <div class="mode-row"><span>待分析/未匹配</span><span style="color:#f57f17">{on_u}</span></div>
            </div>
            <div class="progress" style="margin-top:10px">
                <div style="width:{on_prog_ok}%;background:linear-gradient(90deg,#ef5350,#c62828)">{on_o} 成功</div>
                <div style="width:{on_prog_fail}%;background:linear-gradient(90deg,#ff7043,#d84315)">{on_f if on_f else ''}</div>
                <div style="width:{on_prog_unmatch}%;background:#feca57">{on_u if on_u else ''}</div>
            </div>
        </div>
    </div>
</div>

<!-- 2. PC vs 线上对比 -->
<div class="card">
    <h2><span class="ico" style="background:#fff3e0">⚖️</span>PC vs 线上 对比</h2>
    <div class="chart-row">
        <div class="chart-box"><canvas id="typeCompare"></canvas></div>
        <div>
            <table>
                <thead><tr><th>维度</th><th>💻 PC</th><th>🌐 线上</th></tr></thead>
                <tbody>
                    <tr><td>总记录数</td><td>{pc_t}</td><td>{on_t}</td></tr>
                    <tr><td>成功率</td><td><strong style="color:#2e7d32">{pc_r}%</strong></td><td><strong style="color:{'#2e7d32' if on_r>=50 else '#c62828'}">{on_r}%</strong></td></tr>
                    <tr><td>分析成功</td><td>{pc_o}</td><td>{on_o}</td></tr>
                    <tr><td>分析失败</td><td>{pc_f}</td><td>{on_f}</td></tr>
                    <tr><td>待分析</td><td>{pc_u}</td><td>{on_u}</td></tr>
                </tbody>
            </table>
        </div>
    </div>
</div>

<!-- 3. 每日趋势 -->
<div class="chart-row">
    <div class="card">
        <h2><span class="ico" style="background:#e3f2fd">💻</span>PC 每日执行趋势</h2>
        <div class="chart-box"><canvas id="pcChart"></canvas></div>
    </div>
    <div class="card">
        <h2><span class="ico" style="background:#fce4ec">🌐</span>线上 每日执行趋势</h2>
        <div class="chart-box"><canvas id="onChart"></canvas></div>
    </div>
</div>

<!-- 4. 错误类型对比 -->
<div class="card">
    <h2><span class="ico" style="background:#f3e5f5">📊</span>错误类型 PC / 线上对比</h2>
    <div id="errBars"></div>
    <div class="legend" style="margin-top:10px">
        <div class="legend-item"><div class="legend-dot" style="background:#1976d2"></div>💻 PC</div>
        <div class="legend-item"><div class="legend-dot" style="background:#c62828"></div>🌐 线上</div>
    </div>
</div>

<!-- 5. 错误详细分析 -->
<div class="card">
    <h2><span class="ico" style="background:#fce4ec">🔍</span>错误类型详细分析</h2>
    {error_html if error_html else '<p style="color:#94a3b8;text-align:center">暂无错误记录</p>'}
</div>

<!-- 6. 修复建议 -->
<div class="card">
    <h2><span class="ico" style="background:#e3f2fd">🛠️</span>修复建议</h2>
    <div class="rec">
        <h4>🔬 P1 - 触发时间提取优化 <span class="tag tag-pc">PC</span> <span class="tag tag-online">线上</span></h4>
        <ul>
            <li>优先从 Jira 描述提取，降低视频文件名依赖</li>
            <li>支持更多时间格式和时间合理性校验</li>
        </ul>
    </div>
    <div class="rec">
        <h4>🔧 P1 - 分析超时重试 <span class="tag tag-pc">PC</span></h4>
        <ul>
            <li>异步分析增加轮询重试（最多3次）</li>
            <li>超时阈值 15min → 25min</li>
        </ul>
    </div>
    <div style="margin-top:14px;padding:14px;background:#f0fdf4;border-radius:8px;font-size:.88em;border:1px solid #bbf7d0">
        <strong>📊 当前状态：</strong>PC 成功率 <strong>{pc_r}%</strong>，线上 <strong>{on_r}%</strong>，综合 <strong>{total_rate}%</strong>
    </div>
</div>

<div class="footer"><p>Bug文档沉淀工具 · AI日志分析复盘 · PC/线上分维度 · {now}</p></div>
</div>

<script>
const PC_DAYS={pc_days_js};
const PC_OK={pc_ok_js};
const PC_FAIL={pc_fail_js};
const ON_DAYS={on_days_js};
const ON_OK={on_ok_js};
const ON_FAIL={on_fail_js};

function mkBarChart(id,labels,ok,fail,c1,c2){{
    new Chart(document.getElementById(id),{{type:'bar',data:{{labels,datasets:[
        {{label:'成功',data:ok,backgroundColor:c1,borderWidth:0,stack:'s'}},
        {{label:'失败',data:fail,backgroundColor:c2,borderWidth:0,stack:'s'}}
    ]}},options:{{responsive:true,maintainAspectRatio:false,plugins:{{legend:{{position:'top'}}}},scales:{{x:{{stacked:true,ticks:{{maxRotation:45}}}},y:{{stacked:true,beginAtZero:true}}}}}}}});
}}
mkBarChart('pcChart',PC_DAYS,PC_OK,PC_FAIL,'rgba(66,165,245,.75)','rgba(239,83,80,.65)');
mkBarChart('onChart',ON_DAYS,ON_OK,ON_FAIL,'rgba(239,83,80,.75)','rgba(255,112,67,.65)');

// 执行问题vs分析问题对比
new Chart(document.getElementById('typeCompare'),{{type:'bar',data:{{
    labels:['💻 PC','🌐 线上'],
    datasets:[
        {{label:'分析成功',data:[{pc_o},{on_o}],backgroundColor:'rgba(76,175,80,.75)',borderWidth:0}},
        {{label:'分析失败',data:[{pc_f},{on_f}],backgroundColor:'rgba(239,83,80,.65)',borderWidth:0}},
        {{label:'待分析',data:[{pc_u},{on_u}],backgroundColor:'rgba(254,202,87,.65)',borderWidth:0}}
    ]}},options:{{responsive:true,maintainAspectRatio:false,plugins:{{legend:{{position:'top'}}}},scales:{{y:{{beginAtZero:true}}}}}}}});

// 错误类型对比 bar
const errCats={err_cats};
const pcErr={pc_err_js};
const onErr={on_err_js};
let html='';
for(let i=0;i<errCats.length;i++){{
    const total=pcErr[i]+onErr[i];
    if(total===0)continue;
    const max=Math.max(...pcErr.map((a,j)=>a+onErr[j]));
    html+=`<div style="display:flex;align-items:center;gap:8px;margin:5px 0">
        <div style="width:140px;font-size:.83em;text-align:right;flex-shrink:0">${{errCats[i]}}</div>
        <div style="flex:1;height:24px;background:#f0f2f5;border-radius:5px;overflow:hidden;display:flex">
            <div style="width:${{pcErr[i]/max*100}}%;height:100%;background:linear-gradient(90deg,#42a5f5,#1976d2);display:flex;align-items:center;padding:0 6px;font-size:.75em;color:#fff;font-weight:600;min-width:18px">${{pcErr[i]||''}}</div>
            <div style="width:${{onErr[i]/max*100}}%;height:100%;background:linear-gradient(90deg,#ef5350,#c62828);display:flex;align-items:center;padding:0 6px;font-size:.75em;color:#fff;font-weight:600;min-width:18px">${{onErr[i]||''}}</div>
        </div>
        <div style="font-size:.82em;color:#64748b;flex-shrink:0;width:70px">共${{total}}</div>
    </div>`;
}}
document.getElementById('errBars').innerHTML=html;
</script>
</body>
</html>"""

    return html


def main():
    year_month = sys.argv[1] if len(sys.argv) > 1 else datetime.now().strftime("%Y-%m")
    print(f"收集 {year_month} 的月度数据...")

    daily_data = collect_monthly_data(year_month)
    if not daily_data:
        print(f"未找到 {year_month} 的任何批次数据")
        sys.exit(1)

    total_files = sum(len(v["PC"]) + len(v["线上"]) for v in daily_data.values())
    print(f"找到 {len(daily_data)} 天数据，共 {total_files} 条记录")

    stats = analyze_month(daily_data)
    html = generate_html(year_month, stats, daily_data)

    os.makedirs(REPORTS_DIR, exist_ok=True)
    out_path = os.path.join(REPORTS_DIR, f"monthly_report_{year_month}.html")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html)

    print(f"\n报告已生成: {out_path}")
    print(f"PC: {stats['pc_total']} 条, 成功 {stats['pc_ok']}, 成功率 {stats['pc_rate']}%")
    print(f"线上: {stats['on_total']} 条, 成功 {stats['on_ok']}, 成功率 {stats['on_rate']}%")
    print(f"文件大小: {len(html)} 字符, {html.count(chr(10))} 行")


if __name__ == "__main__":
    main()
