"""
RapidOCR PP-OCRv5 正确率测试：
从飞书多维表格查 20 条成功记录 → JIRA 找视频 → 下载首帧 → GPU OCR 识别时间
"""
import os, sys, time, json, re, tempfile, shutil, glob
import numpy as np
import cv2
import requests

PROJ_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJ_ROOT)

MAX_JIRAS = 20
CACHE_DIR = os.path.join(PROJ_ROOT, "_verify_tmp", "rapid_test_cache")
TIME_RE = re.compile(r'(\d{1,2}[.:]\d{2}(?:[.:]\d{2})?)')

ROI_REGIONS = [
    ("right_clock",  0.55, 0.10, 0.95, 0.55),
    ("right_upper",  0.44, 0.00, 1.00, 0.46),
    ("top_bar",      0.00, 0.00, 1.00, 0.17),
    ("center_right", 0.50, 0.32, 1.00, 0.73),
    ("right_lower",  0.58, 0.60, 1.00, 1.00),
    ("left_upper",   0.00, 0.00, 0.50, 0.48),
    ("left_lower",   0.00, 0.38, 0.60, 1.00),
]


def _bitable_text(val):
    if val is None:
        return ""
    if isinstance(val, list):
        if not val:
            return ""
        first = val[0]
        if isinstance(first, dict) and "text" in first:
            return "".join(seg.get("text", "") for seg in val)
        if isinstance(first, str):
            return ", ".join(val)
        return json.dumps(val, ensure_ascii=False)
    if isinstance(val, dict):
        return val.get("value", json.dumps(val, ensure_ascii=False))
    return str(val)


def query_successful_jiras():
    """从飞书多维表格查询分析成功的 Jira"""
    from src.config import load_config
    from src.clients import feishu_client
    cfg = load_config().get("feishu_bitable", {})
    app_token, table_id = cfg.get("app_token", ""), cfg.get("table_id", "")
    if not app_token or not table_id:
        print("[ERROR] 飞书 app_token/table_id 未配置")
        return []
    print("[飞书] 查询多维表格...")
    records = feishu_client.list_bitable_records(app_token, table_id, page_size=500)
    print(f"[飞书] 获取 {len(records)} 条记录")
    success, seen = [], set()
    for rec in records:
        fields = rec.get("fields", {})
        jira_no = _bitable_text(fields.get("jira号", "")).strip()
        result = _bitable_text(fields.get("分析结果", "")).strip()
        if not jira_no or jira_no in seen or result != "成功":
            continue
        success.append(jira_no)
        seen.add(jira_no)
    print(f"[飞书] 分析成功: {len(success)} 个 Jira")
    return success


def find_jiras_with_videos(jira_list, target=MAX_JIRAS):
    """从 JIRA 列表中筛选含视频附件的工单"""
    from src.config import load_config
    cfg = load_config().get("jira_api", {})
    jira_token = cfg.get("token", "")
    jira_base = cfg.get("url", "").replace("/rest/api/2/issue", "")
    headers = {"Authorization": f"Bearer {jira_token}", "Accept": "application/json"}
    results = []
    for i, jira_no in enumerate(jira_list):
        if len(results) >= target:
            break
        if (i + 1) % 10 == 0:
            print(f"[JIRA] 检查: {i+1}/{len(jira_list)}, 已找到 {len(results)} 个含视频")
        try:
            resp = requests.get(f"{jira_base}/rest/api/2/issue/{jira_no}",
                                headers=headers, timeout=15, verify=False)
            if resp.status_code != 200:
                continue
            for att in resp.json().get("fields", {}).get("attachment", []):
                fname = att.get("filename", "")
                if fname.lower().endswith((".mp4", ".avi", ".mov", ".mkv", ".wmv", ".flv")):
                    results.append((jira_no, att.get("content", ""), fname))
                    break
        except Exception:
            continue
    print(f"[JIRA] 共找到 {len(results)} 个含视频的 Jira")
    return results


def download_first_frame(video_url, jira_token):
    """下载视频并提取首帧"""
    import av
    tmp_dir = tempfile.mkdtemp()
    try:
        vpath = os.path.join(tmp_dir, "v.bin")
        resp = requests.get(video_url, headers={"Authorization": f"Bearer {jira_token}"},
                            timeout=120, verify=False, stream=True)
        if resp.status_code != 200:
            return None
        with open(vpath, "wb") as f:
            for chunk in resp.iter_content(chunk_size=8192):
                f.write(chunk)
        container = av.open(vpath)
        for frame in container.decode(container.streams.video[0]):
            img = frame.to_ndarray(format="bgr24")
            container.close()
            return img
        container.close()
    except Exception:
        return None
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)
    return None


def get_roi_crops(frame):
    """ROI 区域裁剪 + 3x 放大 + CLAHE"""
    h, w = frame.shape[:2]
    crops = []
    for name, rx1, ry1, rx2, ry2 in ROI_REGIONS:
        x1, y1, x2, y2 = int(w*rx1), int(h*ry1), int(w*rx2), int(h*ry2)
        if x2-x1 < 40 or y2-y1 < 12:
            continue
        raw = frame[y1:y2, x1:x2]
        ch, cw = raw.shape[:2]
        enlarged = cv2.resize(raw, (int(cw*3), int(ch*3)), interpolation=cv2.INTER_CUBIC)
        gray = cv2.cvtColor(enlarged, cv2.COLOR_BGR2GRAY)
        gray = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8)).apply(gray)
        gray = cv2.GaussianBlur(gray, (3, 3), 0)
        sharp = cv2.addWeighted(gray, 1.6, cv2.GaussianBlur(gray, (0, 0), 3), -0.6, 0)
        crops.append((name, cv2.cvtColor(sharp, cv2.COLOR_GRAY2BGR)))
    return crops


def main():
    import warnings, yaml
    warnings.filterwarnings("ignore")
    import urllib3
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

    from src.config import load_config
    from rapidocr_onnxruntime import RapidOCR

    # ── 1. 准备样本 ──
    print("=" * 60)
    print("  RapidOCR PP-OCRv5 正确率测试（GPU 模式）")
    print("=" * 60)

    success_jiras = query_successful_jiras()
    if not success_jiras:
        print("[ERROR] 无成功记录")
        return
    video_jiras = find_jiras_with_videos(success_jiras[:200], target=MAX_JIRAS)
    if not video_jiras:
        print("[ERROR] 无含视频工单")
        return

    jira_token = load_config().get("jira_api", {}).get("token", "")
    os.makedirs(CACHE_DIR, exist_ok=True)

    # ── 2. 下载/加载帧 ──
    print(f"\n── 准备 {MAX_JIRAS} 个视频首帧 ──")
    samples = []
    for idx, (jira_no, video_url, vname) in enumerate(video_jiras):
        cache_path = os.path.join(CACHE_DIR, f"{jira_no}.npy")
        if os.path.exists(cache_path):
            img = np.load(cache_path)
            print(f"  [{idx+1}] {jira_no} 缓存命中")
        else:
            print(f"  [{idx+1}] {jira_no} 下载视频...", end=" ")
            img = download_first_frame(video_url, jira_token)
            if img is None:
                print("失败，跳过")
                continue
            np.save(cache_path, img)
            print(f"{img.shape[1]}x{img.shape[0]}")
        samples.append((jira_no, vname, img))
    if not samples:
        print("[ERROR] 无有效帧")
        return
    print(f"\n共 {len(samples)} 个有效样本\n")

    # ── 3. 初始化 RapidOCR ──
    cfg_path = os.path.join(PROJ_ROOT, "models", "ppocrv5", "rapidocr_v5.yaml")
    with open(cfg_path, encoding="utf-8") as f:
        ycfg = yaml.safe_load(f)
    model_dir = os.path.join(PROJ_ROOT, "models", "ppocrv5")
    for sec, fname in [("Det", "det.onnx"), ("Cls", "cls.onnx"), ("Rec", "rec.onnx")]:
        if sec in ycfg:
            ycfg[sec]["model_path"] = os.path.join(model_dir, fname)
            ycfg[sec]["use_cuda"] = True
    if "Rec" in ycfg:
        ycfg["Rec"]["rec_keys_path"] = os.path.join(model_dir, "ppocrv5_dict.txt")
    tmp_cfg = os.path.join(tempfile.gettempdir(), "rapidocr_test.yaml")
    with open(tmp_cfg, "w", encoding="utf-8") as f:
        yaml.dump(ycfg, f, default_flow_style=False, allow_unicode=True)

    engine = RapidOCR(config_path=tmp_cfg)
    # 检测 GPU
    try:
        det_sess = engine.text_detector
        for attr in ["session", "sess", "net"]:
            obj = getattr(det_sess, attr, None)
            if obj and hasattr(obj, "get_providers"):
                ps = obj.get_providers()
                break
        else:
            ps = []
    except Exception:
        ps = []
    is_gpu = any("CUDA" in p for p in ps)
    mode = "CUDA GPU" if is_gpu else "CPU"
    print(f"[引擎] RapidOCR PP-OCRv5 ({mode})")

    # 预热
    engine(np.random.randint(0, 255, (128, 256, 3), dtype=np.uint8))
    print("  预热完成\n")

    # ── 4. 运行测试 ──
    n = len(samples)
    hits, total_t, total_conf = 0, 0.0, 0.0
    results = []

    print(f"{'='*60}")
    print(f"  测试 {n} 个视频首帧 · {mode}")
    print(f"{'='*60}")

    for idx, (jira_no, vname, img) in enumerate(samples):
        crops = get_roi_crops(img)
        t0 = time.perf_counter()
        # 全帧识别
        full_r = engine(img)
        items = []
        if full_r and full_r[0]:
            for e in full_r[0]:
                items.append({"text": str(e[1]), "conf": float(e[2])})
        # ROI 区域
        for rname, crop in crops:
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
        total_conf += conf

        t_str = ", ".join(times[:3]) if times else "-"
        mark = "✓" if hit else "✗"
        print(f"  [{idx+1:>2}] {jira_no:<14} {mark} | {len(items):>3}条 | {t_str:<25} | conf={conf:.3f} | {elapsed:.3f}s")
        results.append({"jira": jira_no, "video": vname, "hit": hit, "times": times,
                         "items": len(items), "conf": round(conf, 4), "elapsed": round(elapsed, 4)})

    # ── 5. 汇总 ──
    avg_t = total_t / n if n else 0
    avg_c = total_conf / n if n else 0
    print(f"\n{'─'*60}")
    print(f"  汇总: {n} 个样本 · {mode}")
    if n:
        print(f"  命中率:   {hits}/{n} ({hits/n*100:.1f}%)")
        print(f"  平均耗时: {avg_t:.3f}s (最快 {min(r['elapsed'] for r in results):.3f}s, 最慢 {max(r['elapsed'] for r in results):.3f}s)")
        print(f"  平均置信: {avg_c:.3f}")

    out = os.path.join(PROJ_ROOT, "reports", "rapid_ocr_test_result.json")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        json.dump({"engine": "RapidOCR PP-OCRv5", "mode": mode, "total": n,
                    "hits": hits, "avg_time": round(avg_t, 4), "avg_conf": round(avg_c, 4),
                    "details": results}, f, ensure_ascii=False, indent=2)
    print(f"  结果已保存: {out}")


if __name__ == "__main__":
    main()
