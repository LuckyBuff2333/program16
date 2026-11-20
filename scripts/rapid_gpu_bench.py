"""RapidOCR GPU 基准测试 - 在 20 个缓存帧上测试 GPU 加速效果
注意：运行前需通过 shell 设置 LD_LIBRARY_PATH（动态链接器不支持中文路径）
"""
import sys, os, glob, time, json, re, tempfile, yaml
import numpy as np

PROJ = "/home/ai-agent-ladt/文档/program16"
sys.path.insert(0, PROJ)

from rapidocr_onnxruntime import RapidOCR
import cv2

# 加载配置（绝对路径）
cfg_path = os.path.join(PROJ, "models", "ppocrv5", "rapidocr_v5.yaml")
with open(cfg_path, encoding="utf-8") as f:
    ycfg = yaml.safe_load(f)
model_dir = os.path.join(PROJ, "models", "ppocrv5")
for sec, fname in [("Det", "det.onnx"), ("Cls", "cls.onnx"), ("Rec", "rec.onnx")]:
    if sec in ycfg:
        ycfg[sec]["model_path"] = os.path.join(model_dir, fname)
        ycfg[sec]["use_cuda"] = True
if "Rec" in ycfg:
    ycfg["Rec"]["rec_keys_path"] = os.path.join(model_dir, "ppocrv5_dict.txt")

tmp_cfg = os.path.join(tempfile.gettempdir(), "rapidocr_gpu_test.yaml")
with open(tmp_cfg, "w", encoding="utf-8") as f:
    yaml.dump(ycfg, f, default_flow_style=False, allow_unicode=True)

engine = RapidOCR(config_path=tmp_cfg)

# 检测 provider
try:
    providers = engine.text_detector.net.get_providers()
    is_gpu = any("CUDA" in p for p in providers)
except:
    providers, is_gpu = [], False
mode = "CUDA GPU" if is_gpu else "CPU"
print(f"RapidOCR PP-OCRv5 模式: {mode}")
print(f"Det providers: {providers}")

ROI_REGIONS = [
    ("right_clock", 0.55, 0.10, 0.95, 0.55), ("right_upper", 0.44, 0.00, 1.00, 0.46),
    ("top_bar", 0.00, 0.00, 1.00, 0.17), ("center_right", 0.50, 0.32, 1.00, 0.73),
    ("right_lower", 0.58, 0.60, 1.00, 1.00), ("left_upper", 0.00, 0.00, 0.50, 0.48),
    ("left_lower", 0.00, 0.38, 0.60, 1.00),
]
TIME_RE = re.compile(r"(\d{1,2}[.:]\d{2}(?:[.:]\d{2})?)")

# 加载缓存帧
cache_dir = os.path.join(PROJ, "_verify_tmp", "trocr_compare_cache")
npy_files = sorted(glob.glob(os.path.join(cache_dir, "*.npy")))
print(f"加载 {len(npy_files)} 个缓存帧")

# 预热
engine(np.random.randint(0, 255, (128, 256, 3), dtype=np.uint8))
print("预热完成\n")

hits, total_t, results = 0, 0.0, []
print(f"{'='*70}")
print(f"  RapidOCR PP-OCRv5 {mode} 基准测试（{len(npy_files)} 帧）")
print(f"{'='*70}")

for fpath in npy_files:
    jira = os.path.splitext(os.path.basename(fpath))[0]
    img = np.load(fpath)
    h, w = img.shape[:2]

    t0 = time.perf_counter()
    full_r = engine(img)
    items = []
    if full_r and full_r[0]:
        for e in full_r[0]:
            items.append({"text": str(e[1]), "conf": float(e[2])})
    for name, rx1, ry1, rx2, ry2 in ROI_REGIONS:
        x1, y1, x2, y2 = int(w*rx1), int(h*ry1), int(w*rx2), int(h*ry2)
        if x2-x1 < 40 or y2-y1 < 12:
            continue
        raw = img[y1:y2, x1:x2]
        ch, cw = raw.shape[:2]
        enlarged = cv2.resize(raw, (int(cw*3), int(ch*3)), interpolation=cv2.INTER_CUBIC)
        gray = cv2.cvtColor(enlarged, cv2.COLOR_BGR2GRAY)
        gray = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8,8)).apply(gray)
        gray = cv2.GaussianBlur(gray, (3,3), 0)
        sharp = cv2.addWeighted(gray, 1.6, cv2.GaussianBlur(gray, (0,0), 3), -0.6, 0)
        crop = cv2.cvtColor(sharp, cv2.COLOR_GRAY2BGR)
        r = engine(crop)
        if r and r[0]:
            for e in r[0]:
                items.append({"text": str(e[1]), "conf": float(e[2])})
    elapsed = time.perf_counter() - t0

    times = []
    for it in items:
        m = TIME_RE.search(it["text"])
        if m:
            times.append(m.group(1))
    hit = len(times) > 0
    if hit:
        hits += 1
    total_t += elapsed
    conf = float(np.mean([i["conf"] for i in items])) if items else 0
    t_str = ", ".join(times[:2]) if times else "-"
    mark = "✓" if hit else "✗"
    print(f"  {jira:<14} {mark} | {len(items):>3}条 | 时间:{t_str:<20} | conf={conf:.3f} | {elapsed:.3f}s")
    results.append({"jira": jira, "hit": hit, "times": times, "items": len(items),
                     "conf": conf, "elapsed": round(elapsed, 4)})

n = len(results)
avg_t = total_t / n if n else 0
avg_c = sum(r["conf"] for r in results) / n if n else 0
print(f"\n{'─'*70}")
print(f"  RapidOCR {mode} 汇总: {n} 个样本")
print(f"  命中率:   {hits}/{n} ({hits/n*100:.1f}%)")
print(f"  平均耗时: {avg_t:.3f}s (最快 {min(r['elapsed'] for r in results):.3f}s, 最慢 {max(r['elapsed'] for r in results):.3f}s)")
print(f"  平均置信: {avg_c:.3f}")
print(f"  对比 CPU:  8.857s → {avg_t:.3f}s ({8.857/avg_t:.1f}x 提速)")

out = os.path.join(PROJ, "reports", "rapid_ocr_gpu_result.json")
with open(out, "w", encoding="utf-8") as f:
    json.dump({"engine": "RapidOCR PP-OCRv5", "mode": mode, "total": n, "hits": hits,
               "avg_time": round(avg_t, 4), "avg_conf": round(avg_c, 4), "details": results},
              f, ensure_ascii=False, indent=2)
print(f"  结果已保存: {out}")
