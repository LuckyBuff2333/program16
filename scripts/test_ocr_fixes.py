# -*- coding: utf-8 -*-
""""OCR 时间提取 + 文件名回退 + 字符混淆修正 + 数字混淆纠正 综合测试"""
import re
from datetime import datetime

_OCR_TIME_FULL_RE = re.compile(r'(\d{4}[/-]\d{1,2}[/-]\d{1,2}[\s.,\-]?\d{1,2}[.:,]\d{2}(?:[.:,]\d{2})?)')
_OCR_TIME_ONLY_RE = re.compile(r'(?<!\d)(\d{1,2}[.:,]\d{2}(?:[.:,]\d{2})?)(?!\d)')
_OCR_BARE_TIME_RE = re.compile(r'(?<![a-zA-Z0-9\-/.])(\d{2})(\d{2})(?![a-zA-Z0-9\-/.])')
_OCR_COMMA_TIME_RE = re.compile(r'(?<!\d)(\d{1,2}),(\d{2})(?![\d,.])')
_OCR_CHAR_MAP = {'O': '0', 'o': '0', 'I': '1', 'l': '1', 'L': '1', 'Z': '2', 'z': '2', 'S': '5', 's': '5', 'B': '8'}


def _fix_ocr_char_confusion(text):
    def _fix_time_like(m):
        return ''.join(_OCR_CHAR_MAP.get(ch, ch) for ch in m.group(0))
    text = re.sub(r'[OoIlLZzSB0-9]{1,2}[.:,][OoIlLZzSB0-9]{2}(?:[.:,][OoIlLZzSB0-9]{2})?', _fix_time_like, text)
    return text


def _correct_ocr_by_reference(time_str, ref_dt):
    """参照 gmlogger 时间纠正 OCR 数字混淆"""
    m = re.match(r'(\d{2}):(\d{2})(?::(\d{2}))?', time_str)
    if not m or ref_dt is None:
        return time_str
    hh_str, mm_str = m.group(1), m.group(2)
    ss = m.group(3) or "00"
    ocr_digits = [int(hh_str[0]), int(hh_str[1]), int(mm_str[0]), int(mm_str[1])]
    ocr_hh = ocr_digits[0] * 10 + ocr_digits[1]
    ref_minutes = ref_dt.hour * 60 + ref_dt.minute
    ocr_minutes = ocr_digits[0] * 600 + ocr_digits[1] * 60 + ocr_digits[2] * 10 + ocr_digits[3]
    if abs(ocr_minutes - ref_minutes) <= 5:
        return time_str
    best = None
    best_diff_count = 5
    best_time_diff = 9999
    for offset in range(-5, 6):
        cand_min = (ref_minutes + offset) % 1440
        ch, cm = divmod(cand_min, 60)
        if ch > 23:
            continue
        cand_digits = [ch // 10, ch % 10, cm // 10, cm % 10]
        diff_count = sum(1 for i in range(4) if cand_digits[i] != ocr_digits[i])
        if diff_count == 0:
            continue
        hour_diff = abs(ch - ocr_hh)
        is_12h_confusion = 10 <= hour_diff <= 14
        max_diff = 3 if is_12h_confusion else 1
        if diff_count > max_diff:
            continue
        time_diff = abs(offset)
        if diff_count < best_diff_count or (diff_count == best_diff_count and time_diff < best_time_diff):
            best = f"{ch:02d}:{cm:02d}:{ss}"
            best_diff_count = diff_count
            best_time_diff = time_diff
    return best if best and best != time_str else time_str


def _parse_video_filename_time(filename):
    name = filename.rsplit('.', 1)[0] if '.' in filename else filename
    if re.match(r'^[0-9a-fA-F]{20,}$', name):
        return ""
    m = re.search(r'(\d{1,2})[点時时](\d{1,2})(?:[分]?)(\d{1,2})?', name)
    if m:
        hh, mm = int(m.group(1)), int(m.group(2))
        ss = int(m.group(3)) if m.group(3) else 0
        if 0 <= hh <= 23 and 0 <= mm <= 59 and 0 <= ss <= 59:
            return f"{hh:02d}:{mm:02d}:{ss:02d}"
    m = re.search(r'(?<!\d)([01]\d|2[0-3])([0-5]\d)([0-5]\d)(?!\d)', name)
    if m:
        return f"{m.group(1)}:{m.group(2)}:{m.group(3)}"
    m = re.search(r'(?<!\d)([01]\d|2[0-3])([0-5]\d)(?!\d)', name)
    if m:
        return f"{m.group(1)}:{m.group(2)}:00"
    m = re.search(r'(?<!\d)([01]\d|2[0-3])[-_]([0-5]\d)(?:[-_]([0-5]\d))?(?!\d)', name)
    if m:
        ss = m.group(3) or "00"
        return f"{m.group(1)}:{m.group(2)}:{ss}"
    return ""


def _fix_ocr_missing_colon(text):
    def _fix_comma(m):
        hh, mm = int(m.group(1)), int(m.group(2))
        if 0 <= hh <= 23 and 0 <= mm <= 59:
            return f"{m.group(1)}:{m.group(2)}"
        return m.group(0)
    text = _OCR_COMMA_TIME_RE.sub(_fix_comma, text)
    def _try_insert_colon(m):
        hh, mm = int(m.group(1)), int(m.group(2))
        full = int(m.group(0))
        if 1900 <= full <= 2099:
            return m.group(0)
        if 0 <= hh <= 23 and 0 <= mm <= 59:
            return f"{m.group(1)}:{m.group(2)}"
        return m.group(0)
    return _OCR_BARE_TIME_RE.sub(_try_insert_colon, text)


def _preprocess_ocr_datetime(text):
    def _fix_year(m):
        y = int(m.group(0))
        if 3000 <= y <= 9999:
            return str(2000 + y % 1000)
        return m.group(0)
    text = re.sub(r'\b(\d{4})(?=[/-])', _fix_year, text)
    def _split_date_digits(m):
        date_part, digits = m.group(1), m.group(2)
        parts = re.split(r'[/-]', date_part)
        if len(parts) == 3:
            try:
                mo, day = int(parts[1]), int(parts[2])
                if not (1 <= mo <= 12 and 1 <= day <= 31):
                    return m.group(0)
            except ValueError:
                return m.group(0)
        if len(digits) >= 6:
            hh, mm, ss = int(digits[0:2]), int(digits[2:4]), int(digits[4:6])
            if 0 <= hh <= 23 and 0 <= mm <= 59 and 0 <= ss <= 59:
                return f"{date_part} {hh:02d}:{mm:02d}:{ss:02d}"
        if len(digits) >= 4:
            hh, mm = int(digits[0:2]), int(digits[2:4])
            if 0 <= hh <= 23 and 0 <= mm <= 59:
                return f"{date_part} {hh:02d}:{mm:02d}"
        return m.group(0)
    text = re.sub(r'(\d{4}[/-]\d{1,2}[/-]\d{1,2})(\d{4,6})(?!\d)', _split_date_digits, text)
    return text


def _normalize_ocr_time(text):
    def _fix_year(m):
        y = int(m.group(0))
        if 3000 <= y <= 9999:
            return str(2000 + y % 1000)
        return m.group(0)
    text = re.sub(r'\b(\d{4})(?=[/-])', _fix_year, text)
    def _split_date_digits(m):
        date_part, digits = m.group(1), m.group(2)
        parts = re.split(r'[/-]', date_part)
        if len(parts) == 3:
            try:
                mo, day = int(parts[1]), int(parts[2])
                if not (1 <= mo <= 12 and 1 <= day <= 31):
                    return m.group(0)
            except ValueError:
                return m.group(0)
        if len(digits) >= 6:
            hh, mm, ss = int(digits[0:2]), int(digits[2:4]), int(digits[4:6])
            if 0 <= hh <= 23 and 0 <= mm <= 59 and 0 <= ss <= 59:
                return f"{date_part} {hh:02d}:{mm:02d}:{ss:02d}"
        if len(digits) >= 4:
            hh, mm = int(digits[0:2]), int(digits[2:4])
            if 0 <= hh <= 23 and 0 <= mm <= 59:
                return f"{date_part} {hh:02d}:{mm:02d}"
        return m.group(0)
    text = re.sub(r'(\d{4}[/-]\d{1,2}[/-]\d{1,2})(\d{4,6})(?!\d)', _split_date_digits, text)
    text = re.sub(r'(\d{4}[/-]\d{1,2}[/-]\d{1,2})[.,](\d{1,2}[.:,]\d{2})', r'\1 \2', text)
    text = re.sub(r'(\d{4}[/-]\d{1,2}[/-]\d{1,2})(\d{1,2}[.:,]\d{2})', r'\1 \2', text)
    text = re.sub(r'(\d{1,2})[.,](\d{2})(?:[.,](\d{2}))?',
                  lambda m: f"{m.group(1)}:{m.group(2)}" + (f":{m.group(3)}" if m.group(3) else ""), text)
    return text


def extract_time(ocr_text):
    fixed = _fix_ocr_missing_colon(ocr_text)
    fixed = _fix_ocr_char_confusion(fixed)
    fixed = _preprocess_ocr_datetime(fixed)
    m = _OCR_TIME_FULL_RE.search(fixed)
    if m:
        return _normalize_ocr_time(m.group(1))
    m2 = _OCR_TIME_ONLY_RE.search(fixed)
    if m2:
        return _normalize_ocr_time(m2.group(1))
    return "NO MATCH"


print("=" * 70)
print("1. 视频文件名时间提取测试")
print("=" * 70)
fn_tests = [
    ("14点02.mp4", "14:02:00"),
    ("1010语音错误.mp4", "10:10:00"),
    ("20260928-163807.mp4", "16:38:07"),
    ("IMG_8784.MOV", ""),
    ("导航设置无 3D 车模.MP4", ""),
    ("08aa2049aa5ae952c69314861a90b8d3.mp4", ""),
    ("1501.mp4", "15:01:00"),
    ("20260602-172828.mp4", "17:28:28"),
    ("VID_20260922_170256.mp4", "17:02:56"),
    ("飞书20260929-140019.mp4", "14:00:19"),
    ("907ed2bd5869d23efa0ddb30cb1eed26.mp4", ""),
    ("LCC+.mp4", ""),
]
all_pass = True
for fn, expected in fn_tests:
    result = _parse_video_filename_time(fn)
    ok = result == expected
    if not ok:
        all_pass = False
    print(f"  [{'PASS' if ok else 'FAIL'}] {fn:45s} -> {result:12s} (expected: {expected})")

print()
print("=" * 70)
print("2. OCR 字符混淆修正测试")
print("=" * 70)
char_tests = [
    ("ZO:LI X 0 ((45)", "20:11 X 0 ((45)"),
    ("10.10 atan KCC", "10.10 atan KCC"),
    ("OI:2S test", "01:25 test"),
]
for text, expected in char_tests:
    result = _fix_ocr_char_confusion(text)
    ok = result == expected
    if not ok:
        all_pass = False
    print(f"  [{'PASS' if ok else 'FAIL'}] {text:30s} -> {result:30s} (expected: {expected})")

print()
print("=" * 70)
print("3. 综合提取测试（OCR + 字符混淆 + 预处理）")
print("=" * 70)
combined_tests = [
    # 标准格式
    ("2026-09-18 13:42", "2026-09-18 13:42"),
    # 逗号作为冒号
    ("10,10 Maen AcC", "10:10"),
    ("10,12 PRESS HERE", "10:12"),
    # 年份修正 + 无分隔符
    ("6024-01-22172440", "2024-01-22 17:24:40"),
    # 字符混淆 ZO:LI → 20:11
    ("ZO:LI X 0 ((45)", "20:11"),
    # 点号时间
    ("2026-09-18 13.42 10", "2026-09-18 13:42"),
    # 真实日志OCR文本
    ("RMMING PT] Touch sciecn lalercy test 10,10 Maen AcC Key door PtMd", "10:10"),
    ("17224 weg Anf 0f##% 6024-01-22172440 6 MSTNEm", "2024-01-22 17:24:40"),
]
for ocr_text, expected in combined_tests:
    result = extract_time(ocr_text)
    ok = result == expected
    if not ok:
        all_pass = False
    print(f"  [{'PASS' if ok else 'FAIL'}] {ocr_text[:55]:55s} -> {result:25s} (expected: {expected})")

print()
print("=" * 70)
print("4. 数字混淆纠正测试（参照gmlogger时间）")
print("=" * 70)
ref_tests = [
    # (OCR时间, 参考时间, 预期纠正结果)
    ("19:19:00", datetime(2025, 7, 14, 7, 9, 57), "07:09:00"),  # VCU-220821: 12h偏移允许3位差异, 纠正为最接近的
    ("07:10:00", datetime(2025, 7, 14, 7, 9, 57), "07:10:00"),  # 已经正确，无需纠正
    ("16:20:00", datetime(2025, 6, 25, 16, 20, 30), "16:20:00"),  # 已经正确
    ("18:42:00", datetime(2025, 8, 13, 16, 15, 0), "18:42:00"),  # 无候选满足≤1位差异，不纠正
    ("09:09:00", datetime(2025, 7, 9, 10, 10, 0), "09:09:00"),  # 小时09→10变2位差异，超出普通场景阈值，不纠正
    ("15:00:00", datetime(2025, 7, 14, 7, 9, 57), "15:00:00"),  # 无候选满足≤1位差异，不纠正
]
for ocr_time, ref_dt, expected in ref_tests:
    result = _correct_ocr_by_reference(ocr_time, ref_dt)
    ok = result == expected
    if not ok:
        all_pass = False
    print(f"  [{'PASS' if ok else 'FAIL'}] OCR:{ocr_time:12s} ref:{ref_dt.hour:02d}:{ref_dt.minute:02d}  -> {result:12s} (expected: {expected})")

print()
print("=" * 70)
print("ALL PASS!" if all_pass else "SOME TESTS FAILED")
print("=" * 70)
