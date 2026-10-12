"""快速测试：帧差法裁剪 + PaddleOCR 识别时钟"""
import os
import sys, tempfile, logging
sys.path.insert(0, '.')
logging.basicConfig(level=logging.INFO, format='%(levelname)s %(message)s')
logger = logging.getLogger(__name__)

import numpy as np
import cv2

# 1. 下载视频
from src.web.server import load_config, _extract_video_frames_gpu
cfg = load_config().get('jira_api', {})
headers = {}
token = cfg.get('token', '')
if token:
    headers['Authorization'] = f"Bearer {token}"

import httpx
from src.clients.jira_client import fetch_issue
issue = fetch_issue('VCU-548720')
attachments = issue.get('fields', {}).get('attachment', [])
videos = [a for a in attachments if (a.get('filename', '') or '').lower().endswith(('.mp4', '.mov', '.avi'))]
video_url = videos[0]['content']

tmp_dir = tempfile.mkdtemp()
video_path = os.path.join(tmp_dir, 'video.bin')
logger.info("下载视频...")
with httpx.stream('GET', video_url, headers=headers, timeout=120, verify=False, follow_redirects=True) as resp:
    with open(video_path, 'wb') as f:
        for chunk in resp.iter_bytes(chunk_size=1024*1024):
            f.write(chunk)
logger.info("下载完成")

# 2. 提取前6帧
frames = _extract_video_frames_gpu(video_path, positions=[0,1,2,3,4,5], use_gpu=True)
logger.info("提取了 %d 帧", len(frames))

# 3. 帧差法定位时钟区域
sorted_frames = sorted(frames, key=lambda x: x[0])
h, w = sorted_frames[0][1].shape[:2]

diff_accum = np.zeros((h, w), dtype=np.float32)
pair_count = 0
for i in range(len(sorted_frames) - 1):
    gray1 = cv2.cvtColor(sorted_frames[i][1], cv2.COLOR_BGR2GRAY).astype(np.float32)
    gray2 = cv2.cvtColor(sorted_frames[i+1][1], cv2.COLOR_BGR2GRAY).astype(np.float32)
    diff = cv2.absdiff(gray1, gray2)
    _, mask = cv2.threshold(diff, 50, 255, cv2.THRESH_BINARY)
    diff_accum += mask.astype(np.float32)
    pair_count += 1
diff_accum /= pair_count

change_thresh = max(50.0, diff_accum.max() * 0.5)
_, binary_mask = cv2.threshold(diff_accum, change_thresh, 255, cv2.THRESH_BINARY)
binary_mask = binary_mask.astype(np.uint8)
kernel_clean = np.ones((5, 5), np.uint8)
binary_mask = cv2.morphologyEx(binary_mask, cv2.MORPH_OPEN, kernel_clean)
binary_mask = cv2.morphologyEx(binary_mask, cv2.MORPH_CLOSE, kernel_clean)

num_labels, labels, stats, centroids = cv2.connectedComponentsWithStats(binary_mask)
if num_labels > 1:
    areas = stats[1:, cv2.CC_STAT_AREA]
    best_label = int(np.argmax(areas)) + 1
    x1 = int(stats[best_label, cv2.CC_STAT_LEFT])
    y1 = int(stats[best_label, cv2.CC_STAT_TOP])
    bw = int(stats[best_label, cv2.CC_STAT_WIDTH])
    bh = int(stats[best_label, cv2.CC_STAT_HEIGHT])
    x2 = x1 + bw
    y2 = y1 + bh
    logger.info("最大连通域: bbox=[%d,%d,%d,%d] area=%d", x1, y1, x2, y2, stats[best_label, cv2.CC_STAT_AREA])

# 紧凑 padding
pad = 15
x1, y1 = max(0, x1-pad), max(0, y1-pad)
x2, y2 = min(w, x2+pad), min(h, y2+pad)
crop_w, crop_h = x2-x1, y2-y1
logger.info("裁剪区域: x=[%d,%d] y=[%d,%d] (%dx%d)", x1, x2, y1, y2, crop_w, crop_h)

# 用最后一帧（质量好）裁剪 + 增强
ref_frame = sorted_frames[-1][1]
clock_roi_color = ref_frame[y1:y2, x1:x2]  # 彩色 ROI（给 PaddleOCR）
gray_roi = cv2.cvtColor(clock_roi_color, cv2.COLOR_BGR2GRAY)
enlarged = cv2.resize(gray_roi, (crop_w*3, crop_h*3), interpolation=cv2.INTER_CUBIC)
binary = cv2.adaptiveThreshold(enlarged, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 15, 5)
kernel = np.array([[-1,-1,-1],[-1,9,-1],[-1,-1,-1]], dtype=np.float32)
sharpened_gray = cv2.filter2D(binary, -1, kernel)

# 彩色放大版（给 PaddleOCR 用）
color_enlarged = cv2.resize(clock_roi_color, (crop_w*3, crop_h*3), interpolation=cv2.INTER_CUBIC)

# 保存裁剪图片供查看
cv2.imwrite('logs/vcu548720_roi_paddle.jpg', color_enlarged)
cv2.imwrite('logs/vcu548720_roi_sharpened.jpg', sharpened_gray)
logger.info("ROI 图片已保存")

# 4. RapidOCR 多场景对比测试
from rapidocr_onnxruntime import RapidOCR
engine = RapidOCR()

test_cases = [
    ('彩色放大图 3x', color_enlarged),
    ('灰度放大图 3x', cv2.cvtColor(sharpened_gray, cv2.COLOR_GRAY2BGR)),
    ('原始彩色 ROI（不放大）', clock_roi_color),
    ('最后一帧全图', ref_frame),
]

for name, img in test_cases:
    print(f"\n=== RapidOCR: {name} ({img.shape[1]}x{img.shape[0]}) ===")
    result, elapse = engine(img)
    if result:
        for i, (bbox, text, conf) in enumerate(result):
            print(f"  [{i}] {text} (conf={conf})")
    else:
        print("  (无结果)")
    print(f"  耗时: {elapse}")

# 5. 对比 EasyOCR
logger.info("EasyOCR 识别中...")
from src.web.server import _get_ocr_reader, _ocr_readtext
reader = _get_ocr_reader()
easy_results = _ocr_readtext(reader, sharpened_gray)
print("\n=== EasyOCR 结果 ===")
for r in easy_results:
    text = r[1] if len(r) > 1 else ''
    conf = r[2] if len(r) > 2 else 1.0
    print(f"  {text} (conf={conf:.3f})")

# 清理
import shutil
shutil.rmtree(tmp_dir, ignore_errors=True)
logger.info("测试完成")
