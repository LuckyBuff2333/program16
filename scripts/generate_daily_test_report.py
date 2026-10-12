#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""综合测试报告生成器 v2

支持两种报告类型：
1. 单次执行报告 - 单个批次的完整测试报告
2. 持续执行聚合报告 - 将同一持续执行会话的多批次聚合为一份报告

报告结构：
  ① 测试基础信息（环境/模型/日期）
  ② 报告汇总（成功率/总耗时/总分析时间）
  ③ 失败归类分析
  ④ PC vs 线上来源对比
  ⑤ 各批次/轮次详情
"""
import json
import os
import re
import math
from datetime import datetime
from collections import defaultdict, OrderedDict

REPORTS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "reports")
ANALYSIS_DATA = os.path.join(REPORTS_DIR, "batch_analysis_data_10-10_to_10-11.json")
WALLCLOCK_DATA = os.path.join(REPORTS_DIR, "batch_wallclock_data_10-10_to_10-11.json")
OUTPUT_PATH = os.path.join(REPORTS_DIR, "daily_test_report_10-10_to_10-11.html")

# ────────────────────────────── 工具函数 ──────────────────────────────


def load_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def fmt_dur(sec):
    if not sec or sec == 0:
        return "—"
    sec = int(sec)
    h, rem = divmod(sec, 3600)
    m, s = divmod(rem, 60)
    if h > 0:
        return f"{h}h{m:02d}m{s:02d}s"
    return f"{m}m{s:02d}s" if m else f"{s}s"


def fmt_min(minutes):
    if not minutes or minutes == 0:
        return "—"
    h, m = divmod(int(minutes), 60)
    return f"{h}h{m:02d}m" if h else f"{m}m"


def pct(a, b):
    return round(a / b * 100, 1) if b else 0


def rate_color(r):
    return "#22c55e" if r >= 80 else ("#f59e0b" if r >= 60 else "#ef4444")


# ────────────────────────────── 数据加载与分组 ──────────────────────────────


def load_and_group():
    """加载数据并按持续执行会话分组"""
    analysis = load_json(ANALYSIS_DATA)
    wallclock = load_json(WALLCLOCK_DATA)
    batches = analysis.get("batches", [])
    wc_map = {w["name"]: w for w in wallclock.get("batches", [])}

    # 识别持续执行组：bot_pc_rN 模式
    cont_re = re.compile(r"(bot_pc_r\d+)")
    groups = OrderedDict()  # {group_key: [batch,...]}
    singles = []

    for b in batches:
        name = b.get("name", "")
        m = cont_re.search(name)
        if m:
            # 持续执行：用日期+bot前缀作为组key
            folder = b.get("folder", "")
            gkey = f"{folder}_bot_continuous"
            groups.setdefault(gkey, []).append(b)
        else:
            singles.append(b)

    # 将 wallclock 数据附加到每个 batch
    for b in batches:
        wc = wc_map.get(b["name"], {})
        b["wc"] = wc

    return analysis, batches, groups, singles


# ────────────────────────────── 聚合统计 ──────────────────────────────


def agg_batches(bl):
    """聚合一组 batch 的统计数据"""
    total = sum(b["submit_total"] for b in bl)
    submit_ok = sum(b["submit_success"] for b in bl)
    submit_fail = sum(b["submit_fail"] for b in bl)
    bt_m = sum(b.get("bt_matched", 0) for b in bl)
    bt_s = sum(b.get("bt_success", 0) for b in bl)
    bt_f = sum(b.get("bt_fail", 0) for b in bl)
    bt_nf = sum(b.get("bt_not_found", 0) for b in bl)
    all_durs = [d for b in bl for d in b.get("durations", [])]
    avg_d = sum(all_durs) / len(all_durs) if all_durs else 0
    max_d = max(all_durs) if all_durs else 0
    min_d = min(all_durs) if all_durs else 0
    # P50/P95
    sorted_d = sorted(all_durs)
    p50 = sorted_d[len(sorted_d) // 2] if sorted_d else 0
    p95_idx = int(len(sorted_d) * 0.95)
    p95 = sorted_d[min(p95_idx, len(sorted_d) - 1)] if sorted_d else 0
    total_dur = sum(all_durs)
    # wallclock 聚合
    wc_list = [b.get("wc", {}) for b in bl if b.get("wc")]
    wc_total = sum(w.get("wall_clock_sec", 0) for w in wc_list)
    return {
        "count": len(bl),
        "total": total,
        "submit_ok": submit_ok,
        "submit_fail": submit_fail,
        "bt_m": bt_m, "bt_s": bt_s, "bt_f": bt_f, "bt_nf": bt_nf,
        "rate": pct(bt_s, bt_m),
        "avg_d": round(avg_d, 1),
        "max_d": round(max_d, 1),
        "min_d": round(min_d, 1),
        "p50": round(p50, 1),
        "p95": round(p95, 1),
        "total_dur": round(total_dur, 1),
        "wc_total": wc_total,
    }


# ────────────────────────────── HTML 模板 ──────────────────────────────


def build_css():
    return """<style>
:root{--bg:#0f1117;--card:#1a1d2e;--border:#2a2d3e;--text:#e2e8f0;--muted:#8892a8;
  --accent:#6366f1;--green:#22c55e;--red:#ef4444;--orange:#f59e0b;--blue:#3b82f6;--cyan:#06b6d4;--purple:#a78bfa}
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:-apple-system,'Segoe UI','PingFang SC','Microsoft YaHei',sans-serif;
  background:var(--bg);color:var(--text);line-height:1.7;padding:24px}
.container{max-width:1360px;margin:0 auto}
h1{font-size:28px;font-weight:700;background:linear-gradient(135deg,#6366f1,#a78bfa);
  -webkit-background-clip:text;background-clip:text;-webkit-text-fill-color:transparent}
.subtitle{color:var(--muted);font-size:13px;margin-bottom:28px}
/* --- 信息表 --- */
.info-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:0;
  background:var(--card);border:1px solid var(--border);border-radius:12px;overflow:hidden;margin-bottom:22px}
.info-item{padding:14px 18px;border-right:1px solid var(--border);border-bottom:1px solid var(--border)}
.info-label{font-size:10px;color:var(--muted);text-transform:uppercase;letter-spacing:.5px}
.info-val{font-size:15px;font-weight:600;margin-top:2px}
/* --- KPI --- */
.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(165px,1fr));gap:12px;margin-bottom:22px}
.card{background:var(--card);border:1px solid var(--border);border-radius:12px;padding:16px;position:relative;overflow:hidden}
.card::before{content:'';position:absolute;top:0;left:0;right:0;height:3px}
.card.g::before{background:var(--green)}.card.r::before{background:var(--red)}
.card.b::before{background:var(--blue)}.card.o::before{background:var(--orange)}
.card.c::before{background:var(--cyan)}.card.p::before{background:var(--purple)}
.card-label{font-size:10px;color:var(--muted);text-transform:uppercase;letter-spacing:.5px}
.card-value{font-size:26px;font-weight:700;margin:2px 0}
.card-sub{font-size:11px;color:var(--muted)}
/* --- 通用 --- */
.green{color:var(--green)}.red{color:var(--red)}.orange{color:var(--orange)}
.blue{color:var(--blue)}.cyan{color:var(--cyan)}.purple{color:var(--purple)}
.section{background:var(--card);border:1px solid var(--border);border-radius:12px;padding:24px;margin-bottom:22px}
.section h2{font-size:16px;font-weight:600;margin-bottom:14px;display:flex;align-items:center;gap:8px}
.dot{width:8px;height:8px;border-radius:50%;background:var(--accent);display:inline-block}
.chart-box{width:100%;height:420px}
.chart-sm{width:100%;height:340px}
.chart-lg{width:100%;height:480px}
table{width:100%;border-collapse:collapse;font-size:13px}
th,td{padding:9px 12px;text-align:left;border-bottom:1px solid var(--border)}
th{color:var(--muted);font-weight:500;font-size:11px;text-transform:uppercase;letter-spacing:.5px}
tr:last-child td{border-bottom:none}
.badge{display:inline-block;padding:2px 10px;border-radius:999px;font-size:11px;font-weight:600}
.b-green{background:rgba(34,197,94,.12);color:var(--green)}
.b-red{background:rgba(239,68,68,.12);color:var(--red)}
.b-orange{background:rgba(245,158,11,.12);color:var(--orange)}
.b-gray{background:rgba(136,146,168,.12);color:var(--muted)}
.b-blue{background:rgba(59,130,246,.12);color:var(--blue)}
.b-cyan{background:rgba(6,182,212,.12);color:var(--cyan)}
.b-purple{background:rgba(167,139,250,.12);color:var(--purple)}
.grid-2{display:grid;grid-template-columns:1fr 1fr;gap:22px}
.grid-3{display:grid;grid-template-columns:1fr 1fr 1fr;gap:14px}
@media(max-width:900px){.grid-2,.grid-3{grid-template-columns:1fr}}
/* --- 对比条 --- */
.cmp-row{display:flex;gap:12px;margin-bottom:22px;flex-wrap:wrap}
.cmp-item{flex:1;min-width:140px;background:var(--card);border:1px solid var(--border);
  border-radius:10px;padding:14px;text-align:center}
.cmp-lbl{font-size:10px;color:var(--muted);text-transform:uppercase;margin-bottom:4px}
.cmp-val{font-size:20px;font-weight:700}
.cmp-sub{font-size:11px;color:var(--muted);margin-top:2px}
/* --- 进度条 --- */
.prog-wrap{margin:8px 0}
.prog-bar{height:8px;border-radius:4px;background:#1e2030;overflow:hidden}
.prog-fill{height:100%;border-radius:4px;transition:width .3s}
.prog-label{font-size:11px;color:var(--muted);display:flex;justify-content:space-between;margin-top:3px}
/* --- 结论 --- */
.conclusion{background:linear-gradient(135deg,rgba(99,102,241,.06),rgba(167,139,250,.06));
  border:1px solid rgba(99,102,241,.2);border-radius:12px;padding:24px;margin-bottom:24px}
.conclusion h2{color:#a78bfa;margin-bottom:10px}
.conclusion ul{padding-left:20px}
.conclusion li{margin-bottom:6px}
.conclusion strong{color:var(--orange)}
.footer{text-align:center;color:var(--muted);font-size:11px;padding:20px 0}
</style>"""


def build_info_grid(items):
    """items: [(label, value, color?), ...]"""
    cells = ""
    for lbl, val, *rest in items:
        color = rest[0] if rest else ""
        style = f" style=\"color:{color}\"" if color else ""
        cells += f'<div class="info-item"><div class="info-label">{lbl}</div><div class="info-val"{style}>{val}</div></div>\n'
    return f'<div class="info-grid">{cells}</div>'


def build_cards(items):
    """items: [(label, value, sub, color_class), ...]"""
    html = '<div class="cards">'
    for lbl, val, sub, cc in items:
        html += f'<div class="card {cc}"><div class="card-label">{lbl}</div>'
        html += f'<div class="card-value">{val}</div>'
        html += f'<div class="card-sub">{sub}</div></div>'
    html += '</div>'
    return html


def build_progress_bar(success, fail, nf, total):
    """构建成功/失败/未找到的进度条可视化"""
    if not total:
        return '<div class="prog-wrap"><div class="prog-bar"><div class="prog-fill" style="width:100%;background:#4b5563"></div></div><div class="prog-label"><span>无数据</span></div></div>'
    sw = pct(success, total)
    fw = pct(fail, total)
    nw = pct(nf, total)
    return f"""<div class="prog-wrap">
<div class="prog-bar">
  <div class="prog-fill" style="width:{sw}%;background:var(--green);display:inline-block"></div>
  <div class="prog-fill" style="width:{fw}%;background:var(--red);display:inline-block"></div>
  <div class="prog-fill" style="width:{nw}%;background:#4b5563;display:inline-block"></div>
</div>
<div class="prog-label">
  <span><span style="color:var(--green)">■</span> 成功 {sw}%</span>
  <span><span style="color:var(--red)">■</span> 失败 {fw}%</span>
  <span><span style="color:#4b5563">■</span> 未找到 {nw}%</span>
</div></div>"""


# ────────────────────────────── 报告主体 ──────────────────────────────


def generate_report():
    analysis_data, all_batches, groups, singles = load_and_group()
    daily_stats = analysis_data.get("daily_stats", {})
    bitable_total = analysis_data.get("bitable_total", 0)

    # 总体聚合
    overall = agg_batches(all_batches)
    pc_batches = [b for b in all_batches if b.get("source") != "线上"]
    ol_batches = [b for b in all_batches if b.get("source") == "线上"]
    pc_agg = agg_batches(pc_batches)
    ol_agg = agg_batches(ol_batches)

    # 日期范围
    dates = sorted(set(b.get("folder", "") for b in all_batches))
    date_range = f"{dates[0]} ~ {dates[-1]}" if len(dates) > 1 else dates[0]
    first_exec = min(b.get("exec_time", b.get("wc", {}).get("exec_start", "")) for b in all_batches)
    last_exec = max(b.get("exec_time", b.get("wc", {}).get("exec_start", "")) for b in all_batches)

    # 模型
    models = set(b.get("model", "") for b in all_batches if b.get("model"))
    model_str = " / ".join(models) if models else "—"

    # ===== HTML 开始 =====
    h = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>每日测试综合报告 · {date_range}</title>
<script src="https://cdn.jsdelivr.net/npm/echarts@5/dist/echarts.min.js"></script>
{build_css()}
</head>
<body>
<div class="container">
  <h1>每日测试综合报告</h1>
  <p class="subtitle">覆盖日期：{date_range} · 生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M')}</p>

  <!-- ① 测试基础信息 -->
  <div class="section">
    <h2><span class="dot" style="background:var(--blue)"></span>测试基础信息</h2>
    {build_info_grid([
        ("测试日期范围", date_range),
        ("AI 模型", model_str),
        ("总批次数", f"{overall['count']} 批"),
        ("总提交 Bug", f"{overall['total']} 个"),
        ("多维表格匹配", f"{overall['bt_m']} 个"),
        ("多维表格总记录", f"{bitable_total} 条"),
        ("持续执行会话", f"{len(groups)} 组"),
        ("单次执行批次", f"{len(singles)} 批"),
        ("触发来源", f"PC {pc_agg['count']}批 · 线上 {ol_agg['count']}批"),
        ("执行时间跨度", f"{first_exec[:16]} ~ {last_exec[:16]}"),
    ])}
  </div>

  <!-- ② 报告汇总 KPI -->
  <div class="section">
    <h2><span class="dot" style="background:var(--green)"></span>报告汇总</h2>
    {build_cards([
        ("分析成功率", f"{overall['rate']}%", f"{overall['bt_s']} / {overall['bt_m']}", "g"),
        ("分析成功", overall['bt_s'], f"占比 {pct(overall['bt_s'], overall['bt_m'])}%", "g"),
        ("分析失败", overall['bt_f'], f"占比 {pct(overall['bt_f'], overall['bt_m'])}%", "r"),
        ("未找到结果", overall['bt_nf'], f"占比 {pct(overall['bt_nf'], overall['bt_m'])}%", "o"),
        ("平均分析耗时", fmt_dur(overall['avg_d']), f"P95: {fmt_dur(overall['p95'])}", "c"),
        ("总分析时间", fmt_dur(overall['total_dur']), f"所有批次累计", "b"),
        ("总墙钟时间", fmt_dur(overall['wc_total']), "含等待/排队", "p"),
        ("最快 / 最慢", f"{fmt_dur(overall['min_d'])} / {fmt_dur(overall['max_d'])}", "单条 Bug 耗时", "b"),
    ])}
    {build_progress_bar(overall['bt_s'], overall['bt_f'], overall['bt_nf'], overall['bt_m'])}
  </div>

  <!-- ③ PC vs 线上来源对比 -->
  <div class="section">
    <h2><span class="dot" style="background:var(--cyan)"></span>触发来源对比：PC vs 线上</h2>
    <div class="cmp-row">
      <div class="cmp-item" style="border-top:3px solid var(--blue)">
        <div class="cmp-lbl">PC 批次</div><div class="cmp-val blue">{pc_agg['count']} 批</div>
        <div class="cmp-sub">提交 {pc_agg['total']} · 匹配 {pc_agg['bt_m']}</div>
      </div>
      <div class="cmp-item" style="border-top:3px solid var(--green)">
        <div class="cmp-lbl">PC 成功率</div><div class="cmp-val green">{pc_agg['rate']}%</div>
        <div class="cmp-sub">{pc_agg['bt_s']} 成功 / {pc_agg['bt_f']} 失败</div>
      </div>
      <div class="cmp-item" style="border-top:3px solid var(--cyan)">
        <div class="cmp-lbl">PC 平均耗时</div><div class="cmp-val cyan">{fmt_dur(pc_agg['avg_d'])}</div>
        <div class="cmp-sub">P95 {fmt_dur(pc_agg['p95'])}</div>
      </div>
      <div class="cmp-item" style="border-top:3px solid var(--orange)">
        <div class="cmp-lbl">线上 批次</div><div class="cmp-val orange">{ol_agg['count']} 批</div>
        <div class="cmp-sub">提交 {ol_agg['total']} · 匹配 {ol_agg['bt_m']}</div>
      </div>
      <div class="cmp-item" style="border-top:3px solid var(--red)">
        <div class="cmp-lbl">线上 成功率</div><div class="cmp-val red">{ol_agg['rate']}%</div>
        <div class="cmp-sub">{ol_agg['bt_s']} 成功 / {ol_agg['submit_fail']} 提交失败</div>
      </div>
      <div class="cmp-item" style="border-top:3px solid var(--purple)">
        <div class="cmp-lbl">线上 平均耗时</div><div class="cmp-val purple">{fmt_dur(ol_agg['avg_d']) if ol_agg['avg_d'] else '—'}</div>
        <div class="cmp-sub">{'502错误无有效数据' if ol_agg['submit_fail']>ol_agg['submit_ok'] else '正常'}</div>
      </div>
    </div>
    <div class="grid-2">
      <div id="chartSrcPie" class="chart-sm"></div>
      <div id="chartSrcDaily" class="chart-sm"></div>
    </div>
  </div>
"""

    # ===== ④ 单次执行批次报告 =====
    if singles:
        h += """  <!-- ④ 单次执行批次报告 -->\n"""
        h += '  <div class="section">\n'
        h += '    <h2><span class="dot" style="background:var(--orange)"></span>单次执行批次</h2>\n'
        for b in singles:
            wc = b.get("wc", {})
            src = b.get("source", "PC")
            src_badge = "b-red" if src == "线上" else "b-blue"
            label = b.get("name", "").split("(")[0].strip().replace("批量执行 ", "")
            a = agg_batches([b])
            h += f"""    <div style="border:1px solid var(--border);border-radius:10px;padding:18px;margin-bottom:16px">
      <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:12px">
        <div style="font-size:15px;font-weight:600">{label} <span class="badge {src_badge}">{src}</span></div>
        <div style="font-size:12px;color:var(--muted)">{b.get('exec_time','')[:19]}</div>
      </div>
      {build_info_grid([
          ("提交总数", b.get('submit_total', 0)),
          ("提交成功", b.get('submit_success', 0), "#22c55e"),
          ("提交失败", b.get('submit_fail', 0), "#ef4444" if b.get('submit_fail', 0) > 0 else ""),
          ("多维表格匹配", a['bt_m']),
          ("分析成功", a['bt_s'], "#22c55e"),
          ("分析失败", a['bt_f'], "#ef4444" if a['bt_f'] > 0 else ""),
          ("成功率", f"{a['rate']}%", rate_color(a['rate'])),
          ("平均耗时", fmt_dur(a['avg_d'])),
          ("墙钟时间", fmt_dur(wc.get('wall_clock_sec', 0))),
          ("最慢单条", fmt_dur(a['max_d'])),
      ])}
      {build_progress_bar(a['bt_s'], a['bt_f'], a['bt_nf'], a['bt_m'])}
    </div>\n"""
        h += '  </div>\n'

    # ===== ⑤ 持续执行聚合报告 =====
    for gkey, g_batches in groups.items():
        g_agg = agg_batches(g_batches)
        g_pc = agg_batches([b for b in g_batches if b.get("source") != "线上"])
        g_ol = agg_batches([b for b in g_batches if b.get("source") == "线上"])
        folder = g_batches[0].get("folder", "")
        first_t = min(b.get("exec_time", "")[:19] for b in g_batches)
        last_t = max(b.get("exec_time", "")[:19] for b in g_batches)

        h += f"""  <!-- ⑤ 持续执行聚合报告: {gkey} -->
  <div class="section">
    <h2><span class="dot" style="background:var(--purple)"></span>持续执行聚合报告 · {folder}（{g_agg['count']} 轮）</h2>
    {build_info_grid([
        ("执行日期", folder),
        ("持续轮数", f"{g_agg['count']} 轮"),
        ("执行时间", f"{first_t} ~ {last_t}"),
        ("总提交 Bug", g_agg['total']),
        ("多维表格匹配", g_agg['bt_m']),
        ("触发来源", f"PC {g_pc['count']}批 · 线上 {g_ol['count']}批"),
        ("AI 模型", g_batches[0].get('model', '—')),
    ])}
    {build_cards([
        ("成功率", f"{g_agg['rate']}%", f"{g_agg['bt_s']}/{g_agg['bt_m']}", "g"),
        ("分析成功", g_agg['bt_s'], f"占比 {pct(g_agg['bt_s'], g_agg['bt_m'])}%", "g"),
        ("分析失败", g_agg['bt_f'], f"占比 {pct(g_agg['bt_f'], g_agg['bt_m'])}%", "r"),
        ("未找到", g_agg['bt_nf'], f"占比 {pct(g_agg['bt_nf'], g_agg['bt_m'])}%", "o"),
        ("平均分析耗时", fmt_dur(g_agg['avg_d']), f"P50 {fmt_dur(g_agg['p50'])} · P95 {fmt_dur(g_agg['p95'])}", "c"),
        ("总分析时间", fmt_dur(g_agg['total_dur']), "所有轮次累计", "b"),
        ("总墙钟时间", fmt_dur(g_agg['wc_total']), "含排队等待", "p"),
        ("最快 / 最慢", f"{fmt_dur(g_agg['min_d'])} / {fmt_dur(g_agg['max_d'])}", "单条 Bug", "b"),
    ])}
    {build_progress_bar(g_agg['bt_s'], g_agg['bt_f'], g_agg['bt_nf'], g_agg['bt_m'])}

    <!-- 每轮详情表 -->
    <h2 style="margin-top:20px"><span class="dot" style="background:var(--cyan)"></span>各轮次详情</h2>
    <table>
      <thead><tr>
        <th>轮次</th><th>执行时间</th><th>提交</th><th>匹配</th>
        <th>成功</th><th>失败</th><th>未找到</th><th>成功率</th>
        <th>平均耗时</th><th>最慢</th><th>墙钟</th>
      </tr></thead>
      <tbody>"""
        for i, b in enumerate(g_batches, 1):
            wc = b.get("wc", {})
            ba = agg_batches([b])
            rc = rate_color(ba['rate'])
            h += f"""<tr>
  <td style="font-weight:600">R{i}</td>
  <td style="font-size:12px">{b.get('exec_time','')[:19]}</td>
  <td>{b['submit_total']}</td>
  <td>{ba['bt_m']}</td>
  <td style="color:#22c55e;font-weight:700">{ba['bt_s']}</td>
  <td style="color:#ef4444">{ba['bt_f']}</td>
  <td style="color:#8892a8">{ba['bt_nf']}</td>
  <td style="color:{rc};font-weight:700">{ba['rate']}%</td>
  <td>{fmt_dur(ba['avg_d'])}</td>
  <td>{fmt_dur(ba['max_d'])}</td>
  <td>{fmt_dur(wc.get('wall_clock_sec',0))}</td>
</tr>"""
        h += f"""</tbody></table>
    <!-- 持续执行图表 -->
    <div class="grid-2" style="margin-top:18px">
      <div id="chart_{gkey}_rate" class="chart-sm"></div>
      <div id="chart_{gkey}_stack" class="chart-sm"></div>
    </div>
  </div>
"""

    # ===== ⑥ 失败归类分析 =====
    # 从 daily_stats 获取失败数据
    fail_total = sum(ds.get("fail", 0) for ds in daily_stats.values())
    success_total = sum(ds.get("success", 0) for ds in daily_stats.values())
    all_total = sum(ds.get("total", 0) for ds in daily_stats.values())

    # 构建失败来源分布
    source_totals = {}
    for ds in daily_stats.values():
        for src, cnt in ds.get("sources", {}).items():
            source_totals[src] = source_totals.get(src, 0) + cnt

    h += f"""  <!-- ⑥ 失败归类分析 -->
  <div class="section">
    <h2><span class="dot" style="background:var(--red)"></span>失败归类分析</h2>
    <div class="cmp-row">
      <div class="cmp-item" style="border-top:3px solid var(--green)">
        <div class="cmp-lbl">分析成功</div><div class="cmp-val green">{success_total}</div>
        <div class="cmp-sub">占比 {pct(success_total, all_total)}%</div>
      </div>
      <div class="cmp-item" style="border-top:3px solid var(--red)">
        <div class="cmp-lbl">分析失败</div><div class="cmp-val red">{fail_total}</div>
        <div class="cmp-sub">占比 {pct(fail_total, all_total)}%</div>
      </div>
      <div class="cmp-item" style="border-top:3px solid var(--orange)">
        <div class="cmp-lbl">未找到结果</div><div class="cmp-val orange">{overall['bt_nf']}</div>
        <div class="cmp-sub">多维表格无对应记录</div>
      </div>
      <div class="cmp-item" style="border-top:3px solid var(--blue)">
        <div class="cmp-lbl">提交失败</div><div class="cmp-val blue">{overall['submit_fail']}</div>
        <div class="cmp-sub">502/网络错误等</div>
      </div>
    </div>
    <!-- 每日失败分类表 -->
    <table>
      <thead><tr><th>日期</th><th>总Bug</th><th>成功</th><th>失败</th><th>成功率</th><th>平均耗时</th><th>触发来源构成</th></tr></thead>
      <tbody>"""
    for d, ds in sorted(daily_stats.items()):
        src_str = " · ".join(f"{k}: {v}" for k, v in ds.get("sources", {}).items())
        rc = rate_color(ds.get("success_rate", 0))
        h += f"""<tr>
  <td style="font-weight:600">{d}</td><td>{ds['total']}</td>
  <td style="color:#22c55e">{ds['success']}</td><td style="color:#ef4444">{ds['fail']}</td>
  <td style="color:{rc};font-weight:700">{ds['success_rate']}%</td>
  <td>{fmt_dur(ds.get('avg_duration',0))}</td>
  <td style="font-size:12px;color:#8892a8">{src_str}</td>
</tr>"""
    h += """</tbody></table>
    <div class="grid-2" style="margin-top:18px">
      <div id="chartFailType" class="chart-sm"></div>
      <div id="chartSourceDist" class="chart-sm"></div>
    </div>
  </div>
"""

    # ===== ⑦ 全量批次明细表 =====
    h += """  <!-- ⑦ 全量批次明细 -->
  <div class="section">
    <h2><span class="dot"></span>全量批次执行明细</h2>
    <table>
      <thead><tr>
        <th>#</th><th>批次名称</th><th>来源</th><th>提交</th><th>成功</th><th>失败</th>
        <th>匹配</th><th>分析成功</th><th>分析失败</th><th>成功率</th><th>平均耗时</th><th>墙钟</th>
      </tr></thead>
      <tbody>"""
    for i, b in enumerate(all_batches, 1):
        wc = b.get("wc", {})
        ba = agg_batches([b])
        src = b.get("source", "PC")
        src_badge = "b-red" if src == "线上" else "b-blue"
        label = b.get("name", "").split("(")[0].strip().replace("批量执行 ", "").replace("线上", "")
        rc = rate_color(ba['rate'])
        h += f"""<tr>
  <td>{i}</td><td style="font-size:12px">{label}</td>
  <td><span class="badge {src_badge}">{src}</span></td>
  <td>{b['submit_total']}</td>
  <td style="color:#22c55e">{b['submit_success']}</td>
  <td style="color:#ef4444">{b['submit_fail']}</td>
  <td>{ba['bt_m']}</td>
  <td style="color:#22c55e;font-weight:700">{ba['bt_s']}</td>
  <td style="color:#ef4444">{ba['bt_f']}</td>
  <td style="color:{rc};font-weight:700">{ba['rate']}%</td>
  <td>{fmt_dur(ba['avg_d'])}</td>
  <td>{fmt_dur(wc.get('wall_clock_sec',0))}</td>
</tr>"""
    h += "</tbody></table></div>\n"

    # ===== ⑧ 结论 =====
    h += """  <div class="conclusion">
    <h2>分析结论</h2>
    <ul>"""
    h += f"<li>本报告覆盖 <strong>{date_range}</strong>，共 <strong>{overall['count']} 个批次</strong>（{overall['total']} 个Bug），整体成功率 <strong>{overall['rate']}%</strong></li>"
    if ol_agg['count'] > 0 and ol_agg['submit_fail'] > ol_agg['submit_ok']:
        h += f"<li><strong>线上批次</strong>：{ol_agg['count']}批共{ol_agg['total']}个Bug，提交失败{ol_agg['submit_fail']}个（502 Bad Gateway），成功率 <strong>{ol_agg['rate']}%</strong></li>"
    h += f"<li><strong>PC批次</strong>：{pc_agg['count']}批，成功率 <strong>{pc_agg['rate']}%</strong>，平均耗时 {fmt_dur(pc_agg['avg_d'])}，P95 {fmt_dur(pc_agg['p95'])}</li>"
    for gkey, gb in groups.items():
        ga = agg_batches(gb)
        h += f"<li>持续执行会话（{gb[0].get('folder','')}）：<strong>{ga['count']}轮</strong>，成功率 {ga['rate']}%，总分析时间 {fmt_dur(ga['total_dur'])}</li>"
    h += f"<li>失败主因：分析失败 {fail_total} 个（{pct(fail_total, all_total)}%），未找到 {overall['bt_nf']} 个，提交失败 {overall['submit_fail']} 个</li>"
    h += "<li>建议：① 排查线上 502 错误根因；② 关注低成功率批次（R1 36%）的并发策略；③ 优化 P95 长尾耗时</li>"
    h += """</ul></div>
  <div class="footer">Bug文档沉淀工具 · 每日测试综合报告 · """ + date_range + " · " + datetime.now().strftime('%Y-%m-%d') + """</div>
</div>
"""

    # ===== ECharts 脚本 =====
    h += _build_charts(all_batches, groups, pc_agg, ol_agg, daily_stats, source_totals)
    h += "</body></html>"
    return h


def _build_charts(all_batches, groups, pc_agg, ol_agg, daily_stats, source_totals):
    """构建 ECharts 图表脚本"""
    dates = sorted(daily_stats.keys())
    ds_success = [daily_stats[d]["success"] for d in dates]
    ds_fail = [daily_stats[d]["fail"] for d in dates]

    # 来源分布饼图数据
    src_pie = json.dumps([{"value": v, "name": k} for k, v in source_totals.items()])

    script = f"""<script>
var C={{green:'#22c55e',red:'#ef4444',orange:'#f59e0b',blue:'#3b82f6',purple:'#a78bfa',gray:'#4b5563',cyan:'#06b6d4'}};
var charts=[];
function mk(id,opt){{var el=document.getElementById(id);if(!el)return null;
  var c=echarts.init(el,'dark');c.setOption(opt);charts.push(c);return c}}
var darkBase={{backgroundColor:'transparent',
  textStyle:{{color:'#8892a8'}},
  tooltip:{{trigger:'axis',axisPointer:{{type:'shadow'}}}}}};

// 来源饼图
mk('chartSrcPie',Object.assign({{}},darkBase,{{
  tooltip:{{trigger:'item',formatter:'{{b}}: {{c}} ({{d}}%)'}},
  legend:{{top:0,textStyle:{{color:'#8892a8',fontSize:11}}}},
  title:{{text:'触发来源构成',left:'center',top:0,textStyle:{{color:'#e2e8f0',fontSize:14}}}},
  series:[{{type:'pie',radius:['35%','65%'],center:['50%','55%'],
    label:{{color:'#e2e8f0',fontSize:12}},
    data:{src_pie}
  }}]
}}));

// 每日 PC/线上分布
mk('chartSrcDaily',Object.assign({{}},darkBase,{{
  legend:{{top:0,textStyle:{{color:'#8892a8',fontSize:11}}}},
  grid:{{left:50,right:20,top:45,bottom:35}},
  xAxis:{{type:'category',data:{json.dumps(dates)},axisLine:{{lineStyle:{{color:'#2a2d3e'}}}},axisLabel:{{color:'#8892a8'}}}},
  yAxis:{{type:'value',splitLine:{{lineStyle:{{color:'#1e2030'}}}},axisLabel:{{color:'#8892a8'}}}},
  series:[
    {{name:'成功',type:'bar',stack:'t',barWidth:40,data:{json.dumps(ds_success)},itemStyle:{{color:C.green}}}},
    {{name:'失败',type:'bar',stack:'t',data:{json.dumps(ds_fail)},itemStyle:{{color:C.red}}}}
  ]
}}));

// 失败归类图
mk('chartFailType',Object.assign({{}},darkBase,{{
  legend:{{top:0,textStyle:{{color:'#8892a8',fontSize:11}}}},
  grid:{{left:50,right:20,top:45,bottom:35}},
  xAxis:{{type:'category',data:{json.dumps(dates)},axisLine:{{lineStyle:{{color:'#2a2d3e'}}}},axisLabel:{{color:'#8892a8'}}}},
  yAxis:{{type:'value',splitLine:{{lineStyle:{{color:'#1e2030'}}}},axisLabel:{{color:'#8892a8'}}}},
  series:[
    {{name:'成功',type:'bar',stack:'t',barWidth:50,data:{json.dumps(ds_success)},itemStyle:{{color:C.green}}}},
    {{name:'失败',type:'bar',stack:'t',data:{json.dumps(ds_fail)},itemStyle:{{color:C.red}}}}
  ]
}}));

// 来源分布
mk('chartSourceDist',Object.assign({{}},darkBase,{{
  tooltip:{{trigger:'item',formatter:'{{b}}: {{c}} ({{d}}%)'}},
  legend:{{top:0,textStyle:{{color:'#8892a8',fontSize:11}}}},
  title:{{text:'触发来源占比',left:'center',top:0,textStyle:{{color:'#e2e8f0',fontSize:14}}}},
  series:[{{type:'pie',radius:['35%','65%'],center:['50%','55%'],
    label:{{color:'#e2e8f0',fontSize:12}},
    data:{src_pie}
  }}]
}}));
"""

    # 持续执行组的图表
    for gkey, g_batches in groups.items():
        labels = []
        success_list = []
        fail_list = []
        nf_list = []
        rates = []
        for i, b in enumerate(g_batches, 1):
            labels.append(f"R{i}")
            ba = agg_batches([b])
            success_list.append(ba['bt_s'])
            fail_list.append(ba['bt_f'])
            nf_list.append(ba['bt_nf'])
            rates.append(ba['rate'])

        script += f"""
// 持续执行 {gkey} 成功率趋势
mk('chart_{gkey}_rate',Object.assign({{}},darkBase,{{
  grid:{{left:50,right:20,top:30,bottom:40}},
  xAxis:{{type:'category',data:{json.dumps(labels)},axisLine:{{lineStyle:{{color:'#2a2d3e'}}}},axisLabel:{{color:'#8892a8'}}}},
  yAxis:{{type:'value',max:100,splitLine:{{lineStyle:{{color:'#1e2030'}}}},axisLabel:{{color:'#8892a8',formatter:'{{value}}%'}}}},
  series:[{{name:'成功率',type:'line',smooth:true,data:{json.dumps(rates)},
    lineStyle:{{color:C.cyan,width:2}},itemStyle:{{color:C.cyan}},
    areaStyle:{{color:{{type:'linear',x:0,y:0,x2:0,y2:1,
      colorStops:[{{offset:0,color:'rgba(6,182,212,.3)'}},{{offset:1,color:'rgba(6,182,212,0)'}}]}}}},
    markLine:{{silent:true,data:[{{yAxis:80,label:{{formatter:'目标80%',color:C.green,fontSize:10,position:'insideEndTop'}},
      lineStyle:{{color:C.green,type:'dashed',opacity:.5}}}}]}}
  }}]
}}));

// 持续执行 {gkey} 堆叠柱状图
mk('chart_{gkey}_stack',Object.assign({{}},darkBase,{{
  legend:{{top:0,textStyle:{{color:'#8892a8',fontSize:11}}}},
  grid:{{left:50,right:20,top:45,bottom:40}},
  xAxis:{{type:'category',data:{json.dumps(labels)},axisLine:{{lineStyle:{{color:'#2a2d3e'}}}},axisLabel:{{color:'#8892a8'}}}},
  yAxis:{{type:'value',splitLine:{{lineStyle:{{color:'#1e2030'}}}},axisLabel:{{color:'#8892a8'}}}},
  series:[
    {{name:'成功',type:'bar',stack:'t',barWidth:24,data:{json.dumps(success_list)},itemStyle:{{color:C.green}},
     label:{{show:true,color:'#fff',fontSize:10,formatter:function(p){{return p.value>0?p.value:''}}}}}},
    {{name:'失败',type:'bar',stack:'t',data:{json.dumps(fail_list)},itemStyle:{{color:C.red}},
     label:{{show:true,color:'#fff',fontSize:10,formatter:function(p){{return p.value>0?p.value:''}}}}}},
    {{name:'未找到',type:'bar',stack:'t',data:{json.dumps(nf_list)},itemStyle:{{color:C.gray}},
     label:{{show:true,color:'#fff',fontSize:10,formatter:function(p){{return p.value>0?p.value:''}}}}}}
  ]
}}));
"""

    script += "\nwindow.addEventListener('resize',function(){charts.forEach(function(c){c.resize()})});\n</script>"
    return script


# ────────────────────────────── 入口 ──────────────────────────────


def main():
    html = generate_report()
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"报告已生成: {OUTPUT_PATH}")
    print(f"文件大小: {len(html)} 字符, {html.count(chr(10))} 行")


if __name__ == "__main__":
    main()
