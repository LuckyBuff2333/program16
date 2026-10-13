"""多 OCR 引擎对比测试：VCU-548720 第0帧 "9:46" 识别
方案对比：
  1. EasyOCR（当前方案）全帧 vs ROI裁剪
  2. RapidOCR 全帧 vs ROI裁剪
  3. PaddleOCR PP-OCRv4 全帧 vs ROI裁剪
  4. ROI 增强策略：放大3x/5x + 二值化 + 锐化
  5. 帧差法自动定位时钟区域
"""
import os, sys, tempfile, time, logging, shutil
sys.path.insert(0, '.')
logging.basicConfig(level=logging.INFO, format='%(levelname)s %(name)s %(message)s')
logger = logging.getLogger('ocr_test')

import numpy as np
import cv2

# ─── 1. 下载视频并提取帧 ───
from src.web.server import load_config, _extract_video_frames_gpu
from src.clients.jira_client import fetch_issue
import httpx

cfg = load_config().get('jira_api', {})
headers = {}
token = cfg.get('token', '')
if token:
    headers['Authorization'] = f"Bearer {token}"

logger.info("获取 VCU-548720 附件信息...")
issue = fetch_issue('VCU-548720')
attachments = issue.get('fields', {}).get('attachment', [])
videos = [a for a in attachments if (a.get('filename', '') or '').lower().endswith(('.mp4', '.mov', '.avi'))]
if not videos:
    logger.error("未找到视频附件！")
    sys.exit(1)

video_url = videos[0]['content']
video_label = videos[0].get('filename', 'video')
logger.info("视频: %s", video_label)

tmp_dir = tempfile.mkdtemp()
video_path = os.path.join(tmp_dir, 'video.bin')
logger.info("下载视频...")
with httpx.stream('GET', video_url, headers=headers, timeout=120, verify=False, follow_redirects=True) as resp:
    with open(video_path, 'wb') as f:
        for chunk in resp.iter_bytes(chunk_size=1024*1024):
            f.write(chunk)
logger.info("下载完成, 大小: %.1fMB", os.path.getsize(video_path) / 1024 / 1024)

# 提取前6帧用于帧差法
logger.info("提取帧...")
frames = _extract_video_frames_gpu(video_path, positions=[0, 1, 2, 3, 4, 5], use_gpu=True) or []
if not frames:
    logger.error("无法提取帧！")
    sys.exit(1)

sorted_frames = sorted(frames, key=lambda x: x[0])
ref_frame = sorted_frames[0][1]  # 第0帧（封面）
h, w = ref_frame.shape[:2]
logger.info("提取了 %d 帧, 第0帧尺寸: %dx%d", len(frames), w, h)

# 保存原始第0帧
os.makedirs('logs', exist_ok=True)
cv2.imwrite('logs/vcu548720_frame0.png', ref_frame)

# ─── 2. 帧差法定位时钟 ROI ───
logger.info("=== 帧差法定位时钟区域 ===")
diff_accum = np.zeros((h, w), dtype=np.float32)
pair_count = 0
for i in range(len(sorted_frames) - 1):
    gray1 = cv2.cvtColor(sorted_frames[i][1], cv2.COLOR_BGR2GRAY).astype(np.float32)
    gray2 = cv2.cvtColor(sorted_frames[i+1][1], cv2.COLOR_BGR2GRAY).astype(np.float32)
    diff = cv2.absdiff(gray1, gray2)
    _, mask = cv2.threshold(diff, 50, 255, cv2.THRESH_BINARY)
    diff_accum += mask.astype(np.float32)
    pair_count += 1
diff_accum /= max(pair_count, 1)

roi_bbox = None
if diff_accum.max() >= 10:
    change_thresh = max(50.0, diff_accum.max() * 0.5)
    _, binary_mask = cv2.threshold(diff_accum, change_thresh, 255, cv2.THRESH_BINARY)
    binary_mask = binary_mask.astype(np.uint8)
    kernel = np.ones((5, 5), np.uint8)
    binary_mask = cv2.morphologyEx(binary_mask, cv2.MORPH_OPEN, kernel)
    binary_mask = cv2.morphologyEx(binary_mask, cv2.MORPH_CLOSE, kernel)
    
    num_labels, labels, stats, centroids = cv2.connectedComponentsWithStats(binary_mask)
    if num_labels > 1:
        areas = stats[1:, cv2.CC_STAT_AREA]
        best_label = int(np.argmax(areas)) + 1
        best_area = int(stats[best_label, cv2.CC_STAT_AREA])
        if best_area > 50:
            x1 = int(stats[best_label, cv2.CC_STAT_LEFT])
            y1 = int(stats[best_label, cv2.CC_STAT_TOP])
            bw = int(stats[best_label, cv2.CC_STAT_WIDTH])
            bh = int(stats[best_label, cv2.CC_STAT_HEIGHT])
            pad = 15
            x1, y1 = max(0, x1 - pad), max(0, y1 - pad)
            x2 = min(w, x1 + bw + 2*pad)
            y2 = min(h, y1 + bh + 2*pad)
            roi_bbox = (x1, y1, x2, y2)
            logger.info("帧差法 ROI: x=[%d,%d] y=[%d,%d] (%dx%d) area=%d",
                       x1, x2, y1, y2, x2-x1, y2-y1, best_area)

# ─── 3. 准备各种图像变体 ───
logger.info("=== 准备图像变体 ===")
test_images = {}

# A. 全帧原始
test_images['A_全帧原始'] = ref_frame.copy()

# B. 帧差法 ROI 裁剪（如果有）
if roi_bbox:
    x1, y1, x2, y2 = roi_bbox
    roi_color = ref_frame[y1:y2, x1:x2]
    test_images['B_帧差ROI原始'] = roi_color.copy()
    
    # C. ROI 放大3x
    cw, ch = x2-x1, y2-y1
    roi_3x = cv2.resize(roi_color, (cw*3, ch*3), interpolation=cv2.INTER_CUBIC)
    test_images['C_帧差ROI_3x'] = roi_3x
    
    # D. ROI 放大5x
    roi_5x = cv2.resize(roi_color, (cw*5, ch*5), interpolation=cv2.INTER_CUBIC)
    test_images['D_帧差ROI_5x'] = roi_5x
    
    # E. ROI 灰度+二值化+锐化 (当前帧差法方案)
    gray_roi = cv2.cvtColor(roi_color, cv2.COLOR_BGR2GRAY)
    enlarged = cv2.resize(gray_roi, (cw*3, ch*3), interpolation=cv2.INTER_CUBIC)
    binary = cv2.adaptiveThreshold(enlarged, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                                    cv2.THRESH_BINARY, 15, 5)
    kernel_sharp = np.array([[-1,-1,-1],[-1,9,-1],[-1,-1,-1]], dtype=np.float32)
    sharpened = cv2.filter2D(binary, -1, kernel_sharp)
    test_images['E_帧差ROI_3x_二值化锐化'] = sharpened
    
    # F. ROI 彩色放大3x + CLAHE对比度增强
    lab = cv2.cvtColor(roi_3x, cv2.COLOR_BGR2LAB)
    l, a, b = cv2.split(lab)
    clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8, 8))
    cl = clahe.apply(l)
    enhanced = cv2.merge([cl, a, b])
    enhanced_bgr = cv2.cvtColor(enhanced, cv2.COLOR_LAB2BGR)
    test_images['F_帧差ROI_3x_CLAHE'] = enhanced_bgr
    
    cv2.imwrite('logs/vcu548720_roi.png', roi_color)
    cv2.imwrite('logs/vcu548720_roi_3x.png', roi_3x)
    cv2.imwrite('logs/vcu548720_roi_sharpened.png', sharpened)
    cv2.imwrite('logs/vcu548720_roi_clahe.png', enhanced_bgr)
else:
    logger.warning("帧差法未定位到时钟区域，跳过 ROI 相关测试")

# G. 全帧放大2x（模拟 canvas_size 增大效果）
test_images['G_全帧_2x'] = cv2.resize(ref_frame, (w*2, h*2), interpolation=cv2.INTER_CUBIC)

# ─── 4. OCR 引擎测试 ───
results_summary = []

def run_test(engine_name, engine_fn, img_name, img):
    """运行单个测试并记录结果"""
    t0 = time.time()
    try:
        results = engine_fn(img)
        elapsed = time.time() - t0
        texts = []
        for r in results:
            if isinstance(r, (list, tuple)):
                text = r[1] if len(r) > 1 else str(r)
                conf = r[2] if len(r) > 2 else 0
                texts.append(f"{text}({conf:.2f})")
            else:
                texts.append(str(r))
        all_text = " | ".join(texts) if texts else "(空)"
        # 检查是否包含 9:46 或 9.46
        found_946 = any(t for t in texts if '9' in t and ('46' in t or '4 6' in t))
        results_summary.append({
            'engine': engine_name, 'image': img_name,
            'found_946': found_946, 'elapsed': elapsed,
            'texts': all_text, 'shape': f"{img.shape[1]}x{img.shape[0]}"
        })
        status = "✓ 9:46" if found_946 else "✗"
        logger.info("[%s] %s @ %s (%s) → %s [%.2fs]", 
                   status, engine_name, img_name, img.shape[1],
                   all_text[:120], elapsed)
    except Exception as e:
        elapsed = time.time() - t0
        results_summary.append({
            'engine': engine_name, 'image': img_name,
            'found_946': False, 'elapsed': elapsed,
            'texts': f"ERROR: {e}", 'shape': f"{img.shape[1]}x{img.shape[0]}"
        })
        logger.error("[%s] %s @ %s → ERROR: %s [%.2fs]",
                    engine_name, img_name, e, elapsed)

# --- 4a. EasyOCR ---
logger.info("\n========== EasyOCR 测试 ==========")
from src.web.server import _get_ocr_reader, _ocr_readtext
easy_reader = _get_ocr_reader()

if easy_reader:
    for img_name, img in test_images.items():
        run_test('EasyOCR', lambda i: _ocr_readtext(easy_reader, i), img_name, img)
else:
    logger.warning("EasyOCR 不可用，跳过")

# --- 4b. RapidOCR ---
logger.info("\n========== RapidOCR 测试 ==========")
from rapidocr_onnxruntime import RapidOCR
rapid_engine = RapidOCR()

for img_name, img in test_images.items():
    run_test('RapidOCR', lambda i: (rapid_engine(i)[0] or []), img_name, img)

# --- 4c. PaddleOCR PP-OCRv4 ---
logger.info("\n========== PaddleOCR PP-OCRv4 测试 ==========")
try:
    from paddleocr import PaddleOCR
    paddle_engine = PaddleOCR(use_angle_cls=True, lang='ch', use_gpu=True,
                              show_log=False, use_doc_orientation_classify=False,
                              use_doc_unwarping=False, use_textline_orientation=False)
    
    def paddle_ocr_fn(img):
        # PaddleOCR v4 新版接口
        try:
            result = paddle_engine.ocr(img, cls=True)
            if result and result[0]:
                return [(r[0], r[1][0], r[1][1]) for r in result[0]]
        except:
            # 回退到 predict 接口
            try:
                result = paddle_engine.predict(img)
                items = []
                for r in result:
                    if hasattr(r, 'rec_texts'):
                        for j, txt in enumerate(r.rec_texts):
                            conf = r.rec_scores[j] if hasattr(r, 'rec_scores') else 0
                            items.append((None, txt, conf))
                    elif isinstance(r, dict) and 'rec_text' in r:
                        items.append((None, r['rec_text'], r.get('rec_score', 0)))
                return items
            except Exception as e2:
                logger.warning("PaddleOCR predict 也失败: %s", e2)
        return []
    
    for img_name, img in test_images.items():
        run_test('PaddleOCR', paddle_ocr_fn, img_name, img)
except Exception as e:
    logger.error("PaddleOCR 初始化失败: %s", e)

# ─── 5. 汇总报告 ───
print("\n" + "="*100)
print(f"{'引擎':<15} {'图像变体':<30} {'尺寸':<12} {'找到9:46':<10} {'耗时(s)':<10} OCR结果")
print("="*100)
for r in results_summary:
    status = "✓ YES" if r['found_946'] else "✗ NO"
    print(f"{r['engine']:<15} {r['image']:<30} {r['shape']:<12} {status:<10} {r['elapsed']:<10.2f} {r['texts'][:80]}")

# 高亮成功方案
print("\n=== 成功识别 9:46 的方案 ===")
successes = [r for r in results_summary if r['found_946']]
if successes:
    for r in successes:
        print(f"  ✓ {r['engine']} @ {r['image']} ({r['shape']}) → {r['texts'][:80]} [{r['elapsed']:.2f}s]")
else:
    print("  (无方案成功识别 9:46)")

# 清理
shutil.rmtree(tmp_dir, ignore_errors=True)
logger.info("测试完成，原始帧和 ROI 图片保存在 logs/vcu548720_*.png")
