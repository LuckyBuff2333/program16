#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""pan_scan.py — 日志包泛解析执行器（log-review-pan-scan 技能（泛解析阶段））

域定向广扫：以复核缺口关键词为中心，在原始日志包全语料上提取知识素材
（判读是目标驱动深挖，本工具是无目标广扫——产出"构成性知识"素材）。

子命令：
  fetch  下载登记 + 解包 + 语料概况
         python3 pan_scan.py fetch --case-id VCU-410425 --url <u1> [--url <u2>...] [--root var]
  scan   多关键词组扫描：命中计数 + TAG 分桶 + 数字归一化去重样本
         python3 pan_scan.py scan --case-dir var/dl_VCU-410425 \
             --kw "宠物模式|petmode|PetMode" --kw "ExtendMode|extend_mode" \
             [--top 15] [--out pan_materials.md]

产出是**素材清单**不是知识件：入库前须过知识沉淀视角纪律
（应有态三禁令 / "这句话在系统正常运行时也成立吗"自检），见 SKILL.md 第四阶段。
"""
import argparse
import os
import re
import subprocess
import sys

LOG_EXT = (".log", ".txt")
GZ_EXT = (".log.gz", ".txt.gz", ".gz")
SKIP_DIRS = {"Calibration", "tombstones"}          # 二进制/转储分区，泛解析默认跳过
MAX_HITS_PER_FILE = 5000                            # 单文件命中上限（防大语料爆内存）
TAG_RE = re.compile(
    r"^\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d{3}\s+\d+\s+\d+\s+[VDIWEF]\s+(\S+?):")
NORM_RE = re.compile(r"\d{2,}")


def sh(cmd, **kw):
    return subprocess.run(cmd, capture_output=True, text=True, **kw)


# ---------- fetch ----------

def do_fetch(args):
    case_dir = os.path.join(args.root, "dl_" + args.case_id)
    raw = os.path.join(case_dir, "raw")
    unpack = os.path.join(case_dir, "unpack")
    os.makedirs(raw, exist_ok=True)
    os.makedirs(unpack, exist_ok=True)

    for i, url in enumerate(args.url, 1):
        name = url.rstrip("/").split("?")[0].split("/")[-1] or f"part{i}.bin"
        dest = os.path.join(raw, name)
        if os.path.exists(dest) and os.path.getsize(dest) > 0:
            print(f"[skip] 已存在 {name} ({os.path.getsize(dest)}B)")
            continue
        print(f"[get] {name} ...")
        r = sh(["curl", "-sS", "-o", dest, url], timeout=3600)
        if r.returncode != 0:
            sys.exit(f"[FAIL] 下载失败 {name}: {r.stderr[:200]}")
        print(f"      {os.path.getsize(dest)}B")

    # 解包（薄分发：rar→7z / tar.gz|tgz→tar / zip→7z；分卷 rar 传 part1 即可）
    for name in sorted(os.listdir(raw)):
        src = os.path.join(raw, name)
        low = name.lower()
        if low.endswith(".rar"):
            r = sh(["7z", "x", "-y", f"-o{unpack}", src], timeout=3600)
        elif low.endswith((".tar.gz", ".tgz")):
            r = sh(["tar", "-xzf", src, "-C", unpack], timeout=3600)
        elif low.endswith(".zip"):
            r = sh(["7z", "x", "-y", f"-o{unpack}", src], timeout=3600)
        else:
            continue
        # rar 分卷只解一次（part2 与 part1 同名前缀）
        if low.endswith(".rar") and ".part2" in low:
            continue
        ok = r.returncode == 0
        print(f"[{'unpack ok' if ok else 'unpack ERR'}] {name}"
              + ("" if ok else f"：{r.stderr[-200:]}"))
        if low.endswith(".rar") and ".part1" in low:
            break

    n_file, n_log, n_gz, others = 0, 0, 0, {}
    for dirpath, dirnames, filenames in os.walk(unpack):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for f in filenames:
            n_file += 1
            if f.endswith(GZ_EXT):
                n_gz += 1
            elif f.endswith(LOG_EXT):
                n_log += 1
            else:
                ext = os.path.splitext(f)[1] or "(无扩展名)"
                others[ext] = others.get(ext, 0) + 1
    print(f"\n[语料概况] 文件总数 {n_file}（.gz {n_gz} / 明文日志 {n_log}）")
    top = sorted(others.items(), key=lambda x: -x[1])[:8]
    print("[其他类型 top8] " + " ".join(f"{k}:{v}" for k, v in top))
    print(f"[case-dir] {case_dir}")


# ---------- scan ----------

def iter_log_files(root):
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for f in sorted(filenames):
            p = os.path.join(dirpath, f)
            if f.endswith(GZ_EXT):
                yield p, "gz"
            elif f.endswith(LOG_EXT):
                yield p, "plain"


def grep_file(path, kind, pattern):
    cmd = (["zgrep", "-a", "-E", "-m", str(MAX_HITS_PER_FILE), pattern, path]
           if kind == "gz" else
           ["grep", "-a", "-E", "-m", str(MAX_HITS_PER_FILE), pattern, path])
    r = sh(cmd)
    if r.returncode not in (0, 1):
        return None                                   # 文件级错误（如损坏）跳过
    return [l for l in (r.stdout or "").splitlines() if l]


def norm(line):
    """数字归一化 + 截断，用于样本去重（保留形态、折叠计数）"""
    return NORM_RE.sub("N", line)[:240]


def extract_tag(line):
    m = TAG_RE.match(line)
    return m.group(1) if m else "(非Android行/无TAG)"


def do_scan(args):
    if not os.path.isdir(args.case_dir):
        sys.exit(f"[FAIL] 目录不存在: {args.case_dir}")
    groups = args.kw
    combined = "|".join(f"(?:{g})" for g in groups)
    group_res = {g: {"hits": 0, "files": set(), "tags": {}, "samples": {}}
                 for g in groups}
    group_re = {g: re.compile(g) for g in groups}

    n_files = 0
    for path, kind in iter_log_files(args.case_dir):
        lines = grep_file(path, kind, combined)
        if not lines:
            continue
        n_files += 1
        for line in lines:
            for g in groups:
                if group_re[g].search(line):
                    res = group_res[g]
                    res["hits"] += 1
                    res["files"].add(path)
                    tag = extract_tag(line)
                    res["tags"][tag] = res["tags"].get(tag, 0) + 1
                    s = norm(line)
                    res["samples"][s] = res["samples"].get(s, 0) + 1

    out = [f"# 泛解析素材清单\n\n- case-dir: `{args.case_dir}`\n"
           f"- 关键词组: {len(groups)} | 扫描文件: {n_files}（跳过 {SKIP_DIRS}）\n"
           f"- 生成: 本清单为**素材**非知识件，入库前须过知识沉淀视角纪律（应有态三禁令）\n"]
    for g in groups:
        res = group_res[g]
        out.append(f"\n## 组 `{g}`\n\n- 命中 **{res['hits']}** 行 / {len(res['files'])} 文件\n")
        out.append("### TAG 分桶 top20\n\n| TAG | 行数 |\n|---|---|\n")
        for tag, c in sorted(res["tags"].items(), key=lambda x: -x[1])[:20]:
            out.append(f"| {tag} | {c} |\n")
        out.append(f"\n### 去重样本 top{args.top}（数字归一化）\n\n```\n")
        for s, c in sorted(res["samples"].items(), key=lambda x: -x[1])[:args.top]:
            out.append(f"[x{c}] {s}\n")
        out.append("```\n")

    text = "".join(out)
    if args.out:
        path = args.out if os.path.isabs(args.out) else os.path.join(args.case_dir, args.out)
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
        print(f"[OK] 素材清单落盘 {path}（{len(text)} 字符）")
    else:
        print(text)


def main():
    ap = argparse.ArgumentParser(description="日志包泛解析（域定向广扫）")
    sub = ap.add_subparsers(dest="cmd", required=True)

    f = sub.add_parser("fetch", help="下载登记 + 解包 + 语料概况")
    f.add_argument("--case-id", required=True)
    f.add_argument("--url", action="append", required=True)
    f.add_argument("--root", default="var")

    s = sub.add_parser("scan", help="多关键词组扫描")
    s.add_argument("--case-dir", required=True)
    s.add_argument("--kw", action="append", required=True,
                   help="关键词组（正则，可多次）")
    s.add_argument("--top", type=int, default=15)
    s.add_argument("--out", default=None, help="落盘文件名（默认打印 stdout）")

    args = ap.parse_args()
    (do_fetch if args.cmd == "fetch" else do_scan)(args)


if __name__ == "__main__":
    main()
