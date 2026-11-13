"""从 server_legacy.py 已有的时间策略定义中提取字符集，生成时间专用 OCR 字典。

策略来源：
  - _OCR_CHAR_MAP：OCR 混淆字母（O→0, I→1, Z→2, S→5, B→8）
  - _OCR_MONTH_MAP：英文月份缩写（含 OCR 误读变体 qan, qct, riov 等）
  - 正则分隔符：: . , ; / - 及全角变体
  - 中文时间字：年月日时分秒 + 相对日期（昨天今天等）+ AM/PM + 标签关键字
  - 全角归一化：：；——|｜

非时间字符全部替换为 CTC 空白（dict 第 0 行），使识别模型只输出时间相关字符。
"""
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

def main():
    # ── 1. 从已有策略定义中提取时间字符集 ──

    # 数字
    chars = set("0123456789")

    # 时间/日期分隔符（含全角变体，来自 normalize_datetime_text + 正则）
    chars.update(":;.,/-")
    chars.update("：；")          # 全角冒号、中文分号（normalize_datetime_text 归一化）
    chars.update("—–")          # 破折号/横线（normalize_datetime_text 替换为空格）
    chars.update("|｜")         # 竖线分隔（2026-10-26|19:39:17）

    # _OCR_CHAR_MAP 中的混淆字母（O→0, I/l/L→1, Z→2, S→5, B→8）
    ocr_char_map_keys = "OoIiLlZzSsBb"
    chars.update(ocr_char_map_keys)

    # _OCR_MONTH_MAP 中所有字母（英文月份缩写 + OCR 误读变体）
    month_keys = [
        'jan', 'feb', 'mar', 'apr', 'may', 'jun', 'jul', 'aug',
        'sep', 'oct', 'nov', 'dec',
        'january', 'february', 'march', 'april', 'june', 'july',
        'august', 'september', 'october', 'november', 'december',
        'qan', 'qct', '0ct', '0et',   # OCR 误读（0 已在数字中）
        'nou', 'riov',                  # 11 月误读
        'deo', 'jar', 'jari',           # 12/1 月误读
        'mau', 'jur',                   # 5/6 月误读
        'seq', 'auq', 'teb',            # 9/8/2 月误读
    ]
    for key in month_keys:
        chars.update(key)
        chars.update(key.upper())

    # AM/PM
    chars.update("AaPpMm")

    # 英文星期缩写（Mon, Tue, Wed, Thu, Fri, Sat, Sun）
    weekday_keys = ['mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun',
                    'monday', 'tuesday', 'wednesday', 'thursday',
                    'friday', 'saturday', 'sunday']
    for key in weekday_keys:
        chars.update(key)
        chars.update(key.upper())

    # 中文时间关键字（来自 _is_ocr_time_related_text + _preprocess_ocr_datetime）
    # 年月日时分秒（_preprocess_ocr_datetime 中 \d{4}\s*年\s*\d{1,2}\s*月\s*\d{1,2}\s*日）
    chars.update("年月日时分秒")
    # 星期/周（星期一、周二、周三、周日、周六）
    chars.update("星期周二三四五六日天")
    # 相对日期（_is_ocr_time_related_text: 昨天|今天|前天|大前天）
    chars.update("昨天今前大")
    # 上下午/凌晨/中午（_is_ocr_time_related_text: 上午|下午|晚上|凌晨|中午）
    chars.update("上下晚凌中")
    # 时间标签（_is_ocr_time_related_text: 触发时间|发生时间|问题时间|时间:|日期:）
    chars.update("触发间期问题")

    # 空格（日期时间之间的分隔）
    chars.add(" ")

    print(f"时间字符集共 {len(chars)} 个字符:")
    # 分类打印
    digits = sorted(c for c in chars if c.isdigit())
    ascii_letters = sorted(c for c in chars if c.isascii() and c.isalpha())
    cn_chars = sorted(c for c in chars if '\u4e00' <= c <= '\u9fff')
    puncts = sorted(c for c in chars if not c.isalnum() and not ('\u4e00' <= c <= '\u9fff'))
    print(f"  数字({len(digits)}): {''.join(digits)}")
    print(f"  字母({len(ascii_letters)}): {''.join(ascii_letters)}")
    print(f"  中文({len(cn_chars)}): {''.join(cn_chars)}")
    print(f"  标点/符号({len(puncts)}): {''.join(repr(c) for c in puncts)}")

    # ── 2. 读取原始字典，非时间字符替换为 CTC 空白 ──
    src_path = os.path.join(ROOT, "models", "ppocrv5", "ppocrv5_dict.txt")
    dst_path = os.path.join(ROOT, "models", "ppocrv5", "ppocrv5_time_dict.txt")

    with open(src_path, "r", encoding="utf-8") as f:
        lines = f.readlines()

    # 第 0 行是 CTC 空白字符
    blank = lines[0]
    kept_count = 0
    masked_count = 0
    for i, line in enumerate(lines):
        ch = line.rstrip('\n')
        if ch in chars or i == 0:
            kept_count += 1
        else:
            lines[i] = blank
            masked_count += 1

    with open(dst_path, "w", encoding="utf-8") as f:
        f.writelines(lines)

    print(f"\n生成完成: {dst_path}")
    print(f"  原始字符数: {len(lines)}")
    print(f"  保留: {kept_count}, 屏蔽为空白: {masked_count}")


if __name__ == "__main__":
    main()
