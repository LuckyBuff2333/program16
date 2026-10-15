#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""从日报 HTML 提取批次数据，重建 CSV 并生成批次报告 HTML

用法:
  python scripts/gen_batch_from_daily.py <日报html路径> [批次名]

示例:
  python scripts/gen_batch_from_daily.py reports/daily_report_2026-10-13.html
  python scripts/gen_batch_from_daily.py reports/daily_report_2026-10-13.html batch_192628
"""
import csv
import os
import re
import sys
from datetime import datetime

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def parse_daily_html(html_path):
    """从日报 HTML 中提取 batchData JS 数组和失败详情"""
    with open(html_path, encoding="utf-8") as f:
        html = f.read()

    # 提取日期
    date_match = re.search(r'title>每日测试综合报告\s*·\s*([\d-]+)', html)
    date_str = date_match.group(1) if date_match else ""

    # 提取 batchData JS 数组
    bd_match = re.search(r'const batchData\s*=\s*\[(.*?)\];', html, re.DOTALL)
    if not bd_match:
        print("未找到 batchData 数组")
        return date_str, [], []

    # 解析每条记录
    batches = []
    for m in re.finditer(
        r'\{name:"([^"]+)",exec:"([^"]+)",src:"([^"]+)",total:(\d+),'
        r'submitOk:(\d+),submitFail:(\d+),btMatch:(\d+),btOk:(\d+),'
        r'btFail:(\d+),btMiss:(\d+),avgDur:(\d+),maxDur:(\d+)\}',
        bd_match.group(1)
    ):
        batches.append({
            "name": m.group(1), "exec": m.group(2), "src": m.group(3),
            "total": int(m.group(4)), "submitOk": int(m.group(5)),
            "submitFail": int(m.group(6)), "btMatch": int(m.group(7)),
            "btOk": int(m.group(8)), "btFail": int(m.group(9)),
            "btMiss": int(m.group(10)), "avgDur": int(m.group(11)),
            "maxDur": int(m.group(12)),
        })

    # 提取失败详情: {batch_name: [{jira, cat, msg, dur}]}
    failures = {}
    for m in re.finditer(
        r'<tr><td>(batch_\d+|prod_batch_\d+|auto_add_\d+)</td>'
        r'<td>.*?>(PC|线上|自动)</span></td>'
        r'<td[^>]*>(VCU-\d+)</td>'
        r'<td>.*?>([^<]+)</span></td>'
        r'<td[^>]*>([^<]+)</td>'
        r'<td>([^<]*)</td></tr>',
        html
    ):
        bname = m.group(1)
        failures.setdefault(bname, []).append({
            "jira": m.group(3), "cat": m.group(4),
            "msg": m.group(5), "dur": m.group(6),
        })

    # 提取结论中的 pending jira（如 "VCU-555145、VCU-555159"）
    pending = []
    pend_match = re.search(r'尚在分析中.*?（([^）]+)）', html)
    if pend_match:
        pending = re.findall(r'VCU-\d+', pend_match.group(1))

    return date_str, batches, failures, pending


def generate_csv_and_report(date_str, batch, failures, pending, output_base):
    """为单个批次生成 CSV 和 HTML 报告"""
    name = batch["name"]
    date_dir = os.path.join(output_base, date_str)
    os.makedirs(date_dir, exist_ok=True)

    # ── 1. 重建 CSV ──
    csv_path = os.path.join(date_dir, f"{name}.csv")
    rows = []
    fail_jiras = {f["jira"]: f for f in failures.get(name, [])}
    ok_count = batch["submitOk"]
    fail_count = batch["submitFail"]
    exec_time = f"2026-{date_str[5:]} {batch['exec'].split(' ')[1]}" if ' ' in batch['exec'] else batch['exec']

    # 生成 CSV 行
    # 已知失败的 jira
    for jid, finfo in fail_jiras.items():
        rows.append({
            "jira号": jid, "执行结果": "失败", "报告长度": "0",
            "备注": finfo["msg"][:80], "触发时间": "",
            "执行时间": exec_time, "分析并发数": "10", "下载并发数": "4",
            "模型": "deepseek-v-pro", "触发来源": "PC" if batch["src"] == "PC" else "线上",
        })
    # pending 的 jira
    for jid in pending:
        rows.append({
            "jira号": jid, "执行结果": "成功", "报告长度": "0",
            "备注": "分析任务已启动，正在后台处理中", "触发时间": "",
            "执行时间": exec_time, "分析并发数": "10", "下载并发数": "4",
            "模型": "deepseek-v-pro", "触发来源": "PC" if batch["src"] == "PC" else "线上",
        })
    # 其余成功的用占位
    known_count = len(rows)
    remaining = batch["total"] - known_count
    for i in range(remaining):
        rows.append({
            "jira号": f"VCU-(batch#{i+1})", "执行结果": "成功", "报告长度": "0",
            "备注": "分析任务已启动，正在后台处理中", "触发时间": "",
            "执行时间": exec_time, "分析并发数": "10", "下载并发数": "4",
            "模型": "deepseek-v-pro", "触发来源": "PC" if batch["src"] == "PC" else "线上",
        })

    with open(csv_path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=[
            "jira号", "执行结果", "报告长度", "备注", "触发时间",
            "执行时间", "分析并发数", "下载并发数", "模型", "触发来源"
        ])
        writer.writeheader()
        writer.writerows(rows)
    print(f"  CSV: {csv_path} ({len(rows)} 行)")

    # ── 2. 生成批次报 HTML（含多维表格分析数据） ──
    html_path = os.path.join(date_dir, f"{name}.html")
    html = _build_enriched_html(batch, failures.get(name, []), pending, date_str)
    with open(html_path, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"  HTML: {html_path} ({len(html)} 字符)")
    return csv_path, html_path


def _build_enriched_html(batch, fail_details, pending, date_str):
    """生成包含多维表格分析结果的增强版批次报 HTML"""
    name = batch["name"]
    src = batch["src"]
    src_tag = "tag-info" if src == "PC" else "tag-warn"
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    total = batch["total"]
    submit_ok = batch["submitOk"]
    submit_fail = batch["submitFail"]
    bt_match = batch["btMatch"]
    bt_ok = batch["btOk"]
    bt_fail = batch["btFail"]
    bt_miss = batch["btMiss"]
    avg_dur = batch["avgDur"]
    max_dur = batch["maxDur"]
    rate = round(bt_ok / bt_match * 100, 1) if bt_match else 0
    rate_class = "green" if rate >= 80 else ("orange" if rate >= 60 else "red")

    # 失败归类
    fail_cats = {}
    for fd in fail_details:
        cat = fd["cat"]
        fail_cats.setdefault(cat, []).append(fd)

    fail_cats_json_parts = []
    for cat, fds in fail_cats.items():
        fail_cats_json_parts.append(f'{{name:"{cat}",value:{len(fds)}}}')
    fail_cats_json = "[" + ",".join(fail_cats_json_parts) + "]"

    # 失败详情行
    fail_rows_html = ""
    for fd in fail_details:
        fail_rows_html += f"""<tr>
      <td style="font-weight:600">{fd['jira']}</td>
      <td><span class="tag tag-fail">{fd['cat']}</span></td>
      <td style="color:var(--muted)">{fd['msg']}</td>
      <td>{fd['dur']}</td>
    </tr>"""

    # pending 行
    pending_html = ""
    if pending:
        pending_items = "、".join(pending)
        pending_html = f"""
<div class="card" style="border-left:3px solid var(--orange);margin-top:12px">
  <div class="card-label">分析中（待出结果）</div>
  <div class="card-value orange" style="font-size:18px">{len(pending)} 个</div>
  <div class="card-sub">{pending_items}</div>
</div>"""

    submit_rate = round(submit_ok / total * 100, 1) if total else 0
    avg_min = round(avg_dur / 60, 1) if avg_dur else 0
    max_min = round(max_dur / 60, 1) if max_dur else 0

    h = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>批次执行报告 · {name}</title>
<script src="https://cdn.jsdelivr.net/npm/echarts@5/dist/echarts.min.js"></script>
<style>
:root{{--bg:#0f1117;--card:#1a1d2e;--border:#2a2d3e;--text:#e2e8f0;--muted:#8892a8;--accent:#6366f1;--green:#22c55e;--red:#ef4444;--orange:#f59e0b;--blue:#3b82f6;--cyan:#06b6d4;--purple:#a78bfa}}
*{{margin:0;padding:0;box-sizing:border-box}}
body{{font-family:-apple-system,'Segoe UI','PingFang SC','Microsoft YaHei',sans-serif;background:var(--bg);color:var(--text);line-height:1.7;padding:20px}}
.container{{max-width:1400px;margin:0 auto}}
h1{{font-size:26px;font-weight:700;background:linear-gradient(135deg,#6366f1,#a78bfa);-webkit-background-clip:text;background-clip:text;-webkit-text-fill-color:transparent}}
.subtitle{{color:var(--muted);font-size:13px;margin:4px 0 24px}}
.grid-2{{display:grid;grid-template-columns:1fr 1fr;gap:16px}}
.grid-3{{display:grid;grid-template-columns:1fr 1fr 1fr;gap:16px}}
.grid-4{{display:grid;grid-template-columns:repeat(4,1fr);gap:12px}}
@media(max-width:1000px){{.grid-2,.grid-3,.grid-4{{grid-template-columns:1fr}}}}
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
.bar{{height:6px;border-radius:3px;background:#2a2d3e;overflow:hidden;position:relative}}
.green{{color:var(--green)}}.red{{color:var(--red)}}.orange{{color:var(--orange)}}.blue{{color:var(--blue)}}.cyan{{color:var(--cyan)}}.purple{{color:var(--purple)}}
.bg-green{{background:var(--green)}}.bg-red{{background:var(--red)}}.bg-blue{{background:var(--blue)}}
.conclusion{{background:linear-gradient(135deg,rgba(99,102,241,.08),rgba(167,139,250,.05));border:1px solid rgba(99,102,241,.25);border-radius:12px;padding:20px;margin-top:24px}}
.conclusion h3{{font-size:15px;color:var(--accent);margin-bottom:12px}}
.conclusion li{{margin:6px 0;font-size:13px;line-height:1.7}}
.table-wrap{{max-height:500px;overflow:auto;border-radius:8px;border:1px solid var(--border)}}
.batch-header{{display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:8px}}
.batch-meta{{font-size:11px;color:var(--muted)}}
.footer{{text-align:center;color:var(--muted);font-size:11px;padding:24px 0}}
</style>
</head>
<body>
<div class="container">

<h1>批次执行报告 · {name}</h1>
<p class="subtitle">数据来源：日报 HTML + 多维表格分析结果 · 生成时间：{now}</p>

<!-- ========== 顶部概览 ========== -->
<div class="grid-4">
  <div class="card"><div class="card-label">提交总数</div><div class="card-value blue">{total}</div>
    <div class="card-sub">来源: {src}</div></div>
  <div class="card"><div class="card-label">提交成功</div><div class="card-value green">{submit_ok}</div>
    <div class="card-sub">提交成功率 {submit_rate}%</div></div>
  <div class="card"><div class="card-label">多维表格分析成功</div><div class="card-value green">{bt_ok}</div>
    <div class="card-sub">匹配 {bt_match} / 成功率 {rate}%</div></div>
  <div class="card"><div class="card-label">分析耗时均值</div><div class="card-value purple">{avg_min}min</div>
    <div class="card-sub">最大 {max_min}min</div></div>
</div>

<!-- ========== 批次配置 + 多维表格汇总 ========== -->
<div class="section">
  <div class="section-title">批次信息 & 多维表格分析</div>
  <div class="grid-2">
    <div class="card">
      <div class="batch-header">
        <div><span class="tag {src_tag}">{src}</span></div>
        <div class="batch-meta">{name} · {batch['exec']}</div>
      </div>
      <div class="grid-4" style="margin-top:12px">
        <div><div class="card-label">提交数</div><div style="font-size:22px;font-weight:700">{total}</div></div>
        <div><div class="card-label">成功</div><div style="font-size:22px;font-weight:700" class="green">{submit_ok}</div></div>
        <div><div class="card-label">失败</div><div style="font-size:22px;font-weight:700" class="red">{submit_fail}</div></div>
        <div><div class="card-label">提交成功率</div><div style="font-size:22px;font-weight:700" class="green">{submit_rate}%</div></div>
      </div>
    </div>
    <div class="card">
      <div class="batch-header">
        <div>多维表格验证</div>
        <div class="batch-meta">匹配 {bt_match} / 总 {total}</div>
      </div>
      <div class="grid-4" style="margin-top:12px">
        <div><div class="card-label">表格匹配</div><div style="font-size:22px;font-weight:700" class="blue">{bt_match}</div></div>
        <div><div class="card-label">分析成功</div><div style="font-size:22px;font-weight:700" class="green">{bt_ok}</div></div>
        <div><div class="card-label">分析失败</div><div style="font-size:22px;font-weight:700" class="red">{bt_fail}</div></div>
        <div><div class="card-label">未匹配</div><div style="font-size:22px;font-weight:700" class="orange">{bt_miss}</div></div>
      </div>
      {pending_html}
    </div>
  </div>
</div>

<!-- ========== 图表区 ========== -->
<div class="section">
  <div class="section-title">图表分析</div>

  <div class="grid-2">
    <!-- 图1：提交 & 分析结果 -->
    <div class="chart-box">
      <div class="chart-title">提交 & 多维表格分析结果</div>
      <div id="chart_result" style="height:320px"></div>
    </div>
    <!-- 图2：分析结果饼图 -->
    <div class="chart-box">
      <div class="chart-title">多维表格分析分布</div>
      <div id="chart_analysis_pie" style="height:320px"></div>
    </div>
  </div>

  <!-- 图3：耗时 -->
  <div class="chart-box">
    <div class="chart-title">分析耗时统计</div>
    <div id="chart_duration" style="height:280px"></div>
  </div>
</div>

<!-- ========== 失败详情 ========== -->
"""
    if fail_details:
        h += f"""<div class="section">
  <div class="section-title">分析失败详情</div>
  <div class="table-wrap">
  <table>
    <thead><tr><th>Jira号</th><th>失败分类</th><th>错误信息</th><th>分析耗时</th></tr></thead>
    <tbody>{fail_rows_html}</tbody>
  </table>
  </div>
</div>
"""

    # 失败归类卡片
    if fail_cats:
        h += """<div class="section"><div class="section-title">失败归类</div><div style="display:flex;gap:12px;flex-wrap:wrap">"""
        for cat, fds in sorted(fail_cats.items(), key=lambda x: -len(x[1])):
            jiras = ", ".join(f["jira"] for f in fds[:5])
            h += f"""<div class="card" style="border-top:3px solid var(--red);min-width:180px">
  <div class="card-label">{cat}</div>
  <div class="card-value red" style="font-size:20px">{len(fds)}</div>
  <div class="card-sub">{jiras}</div>
</div>"""
        h += "</div></div>"

    # 结论
    h += f"""
<div class="conclusion">
  <h3>核心结论</h3>
  <ol>
    <li><strong>{name}</strong> 共提交 <strong>{total}</strong> 个 Bug，提交成功率 <strong>{submit_rate}%</strong>（{submit_ok}/{total}）</li>
    <li>多维表格匹配 <strong>{bt_match}</strong> 个，分析成功 <strong>{bt_ok}</strong> 个，成功率 <strong>{rate}%</strong></li>"""
    if bt_fail > 0:
        fail_desc = "、".join(f'{c}({len(f)}个)' for c, f in fail_cats.items())
        h += f'\n    <li>分析失败 <strong>{bt_fail}</strong> 个：{fail_desc}</li>'
    if bt_miss > 0:
        h += f'\n    <li>未匹配多维表格 <strong>{bt_miss}</strong> 个（可能尚在分析中）</li>'
    if pending:
        h += f'\n    <li>尚在分析中：<strong>{"、".join(pending)}</strong>，后续成功率可能提升</li>'
    h += f"""
    <li>分析耗时均值 <strong>{avg_min}min</strong>，最大 <strong>{max_min}min</strong></li>
  </ol>
</div>

<div class="footer">Bug文档沉淀工具 · 批次执行报告 · {name} · {now}</div>
</div><!-- container -->

<script>
// ===== 图1: 提交 & 分析结果 =====
const chart1 = echarts.init(document.getElementById('chart_result'));
chart1.setOption({{
  tooltip:{{trigger:'axis'}},
  legend:{{data:['提交成功','分析成功','分析失败','未匹配'],textStyle:{{color:'#8892a8'}}}},
  grid:{{left:50,right:20,bottom:30,top:40}},
  xAxis:{{type:'category',data:['{name}'],axisLabel:{{color:'#8892a8'}},axisLine:{{lineStyle:{{color:'#2a2d3e'}}}}}},
  yAxis:{{type:'value',name:'Bug数',nameTextStyle:{{color:'#8892a8'}},axisLabel:{{color:'#8892a8'}},splitLine:{{lineStyle:{{color:'#1e2030'}}}}}},
  series:[
    {{name:'提交成功',type:'bar',data:[{submit_ok}],itemStyle:{{color:'#3b82f6'}}}},
    {{name:'分析成功',type:'bar',data:[{bt_ok}],itemStyle:{{color:'#22c55e'}}}},
    {{name:'分析失败',type:'bar',data:[{bt_fail}],itemStyle:{{color:'#ef4444'}}}},
    {{name:'未匹配',type:'bar',data:[{bt_miss}],itemStyle:{{color:'#f59e0b'}}}}
  ]
}});

// ===== 图2: 多维表格分析饼图 =====
const chart2 = echarts.init(document.getElementById('chart_analysis_pie'));
chart2.setOption({{
  tooltip:{{trigger:'item',formatter:'{{b}}: {{c}} ({{d}}%)'}},
  legend:{{bottom:10,textStyle:{{color:'#8892a8'}}}},
  series:[{{
    type:'pie',radius:['40%','70%'],center:['50%','45%'],
    label:{{color:'#e2e8f0',fontSize:12}},
    data:[
      {{value:{bt_ok},name:'分析成功',itemStyle:{{color:'#22c55e'}}}},
      {{value:{bt_fail},name:'分析失败',itemStyle:{{color:'#ef4444'}}}},
      {{value:{bt_miss},name:'未匹配',itemStyle:{{color:'#f59e0b'}}}}
    ]
  }}]
}});

// ===== 图3: 耗时统计 =====
const chart3 = echarts.init(document.getElementById('chart_duration'));
chart3.setOption({{
  tooltip:{{trigger:'axis'}},
  grid:{{left:50,right:20,bottom:30,top:30}},
  xAxis:{{type:'category',data:['平均耗时','最大耗时'],axisLabel:{{color:'#8892a8'}},axisLine:{{lineStyle:{{color:'#2a2d3e'}}}}}},
  yAxis:{{type:'value',name:'分钟',nameTextStyle:{{color:'#8892a8'}},axisLabel:{{color:'#8892a8'}},splitLine:{{lineStyle:{{color:'#1e2030'}}}}}},
  series:[{{
    type:'bar',barWidth:'45%',
    data:[
      {{value:{avg_min},itemStyle:{{color:'#a78bfa'}}}},
      {{value:{max_min},itemStyle:{{color:'#ef4444'}}}}
    ],
    label:{{show:true,position:'top',color:'#e2e8f0',formatter:p=>p.value+'min'}}
  }}]
}});

window.addEventListener('resize',()=>{{chart1.resize();chart2.resize();chart3.resize()}});
</script>
</body>
</html>"""
    return h


def main():
    if len(sys.argv) < 2:
        print("用法: python scripts/gen_batch_from_daily.py <日报html路径> [批次名]")
        sys.exit(1)

    html_path = sys.argv[1]
    target = sys.argv[2] if len(sys.argv) > 2 else None

    if not os.path.isabs(html_path):
        html_path = os.path.join(PROJECT_ROOT, html_path)

    date_str, batches, failures, pending = parse_daily_html(html_path)
    print(f"日报日期: {date_str}")
    print(f"提取到 {len(batches)} 个批次, {len(failures)} 个有失败详情的批次")

    if not batches:
        print("未找到批次数据")
        sys.exit(1)

    output_base = os.path.join(PROJECT_ROOT, "reports")
    generated = []

    for batch in batches:
        if target and batch["name"] != target:
            continue
        print(f"\n处理: [{batch['src']}] {batch['name']} (总{batch['total']}, 成功{batch['submitOk']}, 失败{batch['submitFail']})")
        csv_p, html_p = generate_csv_and_report(date_str, batch, failures, pending, output_base)
        generated.append((batch["name"], csv_p, html_p))

    if not generated:
        print(f"未找到匹配 '{target}' 的批次")
        sys.exit(1)

    print(f"\n共生成 {len(generated)} 个批次报告")


if __name__ == "__main__":
    main()
