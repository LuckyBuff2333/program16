"""
GLM-OCR FP16 GPU 基准测试：复用 RapidOCR 缓存帧，对比识别率
"""
import os, sys, time, json, re, tempfile, shutil
import numpy as np
import cv2
import requests

PROJ_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJ_ROOT)

MAX_JIRAS = 20
# 复用 RapidOCR 缓存帧
CACHE_DIR = os.path.join(PROJ_ROOT, "_verify_tmp", "rapid_test_cache")
TIME_RE = re.compile(r'(\d{1,2}[.:]\d{2}(?:[.:]\d{2})?)')


def _bitable_text(val):
    if val is None:
        return ""
    if isinstance(val, list):
        parts = []
        for item in val:
            if isinstance(item, dict):
                parts.append(item.get("text", "") or str(item.get("value", "")))
            else:
                parts.append(str(item))
        return " ".join(parts)
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


def main():
    import warnings
    warnings.filterwarnings("ignore")
    import urllib3
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    import torch

    from src.config import load_config

    print(f"{'='*60}")
    print(f"  GLM-OCR FP16 GPU 基准测试")
    print(f"  GPU: {torch.cuda.get_device_name(0) if torch.cuda.is_available() else 'N/A'}")
    print(f"{'='*60}")

    # ── 1. 准备样本 ──
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
    n = len(samples)
    print(f"\n共 {n} 个有效样本")

    # ── 3. 初始化 GLM-OCR ──
    print("\n── 初始化 GLM-OCR (FP16 + torch.compile + SDPA) ──")
    from src.services.glm_ocr import ocr_text
    # 预热（触发模型加载+编译）
    dummy = np.random.randint(0, 255, (256, 256, 3), dtype=np.uint8)
    t0 = time.perf_counter()
    ocr_text(dummy, max_new_tokens=8)
    print(f"  模型加载+编译: {time.perf_counter()-t0:.1f}s")

    # ── 4. 运行测试 ──
    print(f"\n{'='*60}")
    print(f"  测试 {n} 个视频首帧 · GLM-OCR FP16 GPU")
    print(f"{'='*60}")

    hits, total_t = 0, 0.0
    results = []

    for idx, (jira_no, vname, img) in enumerate(samples):
        if torch.cuda.is_available():
            torch.cuda.synchronize()
        t0 = time.perf_counter()
        # GLM-OCR 全帧识别
        text = ocr_text(img, max_new_tokens=64)
        if torch.cuda.is_available():
            torch.cuda.synchronize()
        elapsed = time.perf_counter() - t0

        # 匹配时间
        found_times = TIME_RE.findall(text) if text else []
        hit = len(found_times) > 0
        if hit:
            hits += 1
        total_t += elapsed

        t_str = ", ".join(found_times[:3]) if found_times else "-"
        mark = "✓" if hit else "✗"
        print(f"  [{idx+1:>2}] {jira_no:<14} {mark} | {t_str:<25} | {elapsed:.3f}s")
        results.append({"jira": jira_no, "video": vname, "hit": hit,
                         "times": found_times[:5], "text": (text or "")[:200],
                         "elapsed": round(elapsed, 4)})

    # ── 5. 汇总 ──
    avg_t = total_t / n if n else 0
    print(f"\n{'─'*60}")
    print(f"  汇总: {n} 个样本 · GLM-OCR FP16 GPU")
    if n:
        print(f"  命中率:   {hits}/{n} ({hits/n*100:.1f}%)")
        print(f"  平均耗时: {avg_t:.3f}s (最快 {min(r['elapsed'] for r in results):.3f}s, 最慢 {max(r['elapsed'] for r in results):.3f}s)")
        if torch.cuda.is_available():
            print(f"  显存:     {torch.cuda.memory_allocated()/1024**3:.2f} GB")

    out = os.path.join(PROJ_ROOT, "reports", "glm_ocr_benchmark.json")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        json.dump({"engine": "GLM-OCR", "mode": "FP16 GPU + torch.compile + SDPA",
                    "total": n, "hits": hits,
                    "hit_rate": round(hits/n*100, 1) if n else 0,
                    "avg_time": round(avg_t, 4),
                    "details": results}, f, ensure_ascii=False, indent=2)
    print(f"  结果已保存: {out}")


if __name__ == "__main__":
    main()
