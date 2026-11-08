# -*- coding: utf-8 -*-
"""OCR 时间提取核心函数单元测试（黄金测试集）

覆盖 src/services/server_legacy.py 中 OCR 时间提取链路上的全部纯函数与模块级正则：

    normalize_datetime_text    全角冒号/分号、破折号、冒号旁空格归一化（文本与 OCR 两条路径共享）
    _preprocess_ocr_datetime   年份纠错、日期与纯数字时间粘连拆分、竖线分隔符、全角归一化
    _fix_ocr_char_confusion    O→0 / I,l,L→1 / Z,z→2 / S→5 / B→8，带 40% 数字密度门槛
    _fix_ocr_missing_colon     逗号代冒号（10,12）、孤立 4 位数字补冒号（1435）
    _valid_ocr_time            HH:MM[:SS] 有效性校验
    _normalize_ocr_time        两位年份扩展、点号/逗号/分号转冒号、6 位数字时间
    _OCR_*_RE（5 个正则）       匹配边界与拒绝边界
    _resolve_12h_ambiguity     12/24 小时制歧义消解（gmlogger 锚点 → 参考池 → 原值）
    _vote_from_texts           多帧投票（同一 HH:MM ≥2 次 + 参考池容差校验）

设计约束：
1. 全部为纯函数级测试，不初始化 OCR 引擎、不访问网络/磁盘/数据库，可在 CI 独立运行；
2. 用例分三类组织：正常场景、边界场景、已知缺陷（xfail 标注或特征化断言 + 注释说明）；
3. 所有断言值均以实现的真实行为校准，"已知缺陷/已知宽松行为"用例会显式标注，
   便于后续修复源码时定位需要同步更新的用例。
"""
from datetime import datetime

import pytest

from src.clients.jira_client import _parse_datetime_string
from src.core.text_utils import normalize_datetime_text
from src.services import server_legacy as sl

# ── 公共测试数据 ──────────────────────────────────────────────────────────────
DATE_TUPLE = (2026, 10, 27)              # _resolve_12h_ambiguity 使用的 (年, 月, 日)
GM_REF_DATE = datetime(2026, 10, 27)     # 仅提供日期、不含时刻的 gmlogger 参考
TOL_5MIN = 300                           # 参考池命中容差（秒），与生产 _match_tolerance 一致


@pytest.fixture
def inject_parse_fn(monkeypatch):
    """向 server_legacy 模块命名空间注入 _parse_datetime_string。

    背景：_vote_from_texts 内部按全局名引用 _parse_datetime_string，但该名称只在
    若干调用方函数体内以 `from src.clients.jira_client import _parse_datetime_string`
    做局部导入，server_legacy 的模块级命名空间里并不存在它。
    本 fixture 用 monkeypatch 临时补齐该全局名，使投票算法本身可以被独立验证；
    测试结束后自动撤销，不污染其他用例。
    """
    monkeypatch.setattr(sl, "_parse_datetime_string", _parse_datetime_string, raising=False)
    return _parse_datetime_string


def _run_ocr_pipeline(raw: str) -> dict:
    """按生产顺序执行 OCR 文本预处理链路，返回各级中间结果。

    生产顺序（见 server_legacy._extract_video_time 主流程）：
        _fix_ocr_missing_colon → _fix_ocr_char_confusion → _preprocess_ocr_datetime
        → _OCR_TIME_FULL_RE / _OCR_TIME_ONLY_RE / _OCR_RELATIVE_DATE_TIME_RE
    """
    step1 = sl._fix_ocr_missing_colon(raw)
    step2 = sl._fix_ocr_char_confusion(step1)
    step3 = sl._preprocess_ocr_datetime(step2)
    m_full = sl._OCR_TIME_FULL_RE.search(step3)
    m_only = sl._OCR_TIME_ONLY_RE.search(step3)
    m_rel = sl._OCR_RELATIVE_DATE_TIME_RE.search(step3)
    full_raw = m_full.group(1) if m_full else ""
    return {
        "missing_colon": step1,
        "char_confusion": step2,
        "preprocessed": step3,
        "full_raw": full_raw,
        "full_normalized": sl._normalize_ocr_time(full_raw) if full_raw else "",
        "only_raw": m_only.group(1) if m_only else "",
        "relative": (m_rel.group(1), m_rel.group(2)) if m_rel else None,
    }


# ══════════════════════════════════════════════════════════════════════════════
# 1. normalize_datetime_text —— 全角/异常分隔符归一化
# ══════════════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("raw,expected", [
    # ── 全角冒号 → 半角冒号 ──
    ("11：30", "11:30"),
    ("2026-10-27 17：15", "2026-10-27 17:15"),
    ("2026-10-27 17：15：00", "2026-10-27 17:15:00"),
    # ── 全角/半角分号在数字间 → 冒号 ──
    ("8；44", "8:44"),
    ("8;44", "8:44"),
    ("14；57：30", "14:57:30"),
    ("2026-10-27 17；15", "2026-10-27 17:15"),
    # ── 冒号旁空格去除 ──
    ("14: 57", "14:57"),
    ("14 :57", "14:57"),
    ("14 : 57", "14:57"),
    # ── em-dash / en-dash / 全角横线 → 空格（日期与时间分割）──
    ("2026-10-27——17:15", "2026-10-27 17:15"),
    ("2026-10-27–17:15", "2026-10-27 17:15"),
    ("2026-10-27―17:15", "2026-10-27 17:15"),
    ("2026-10-27－17:15", "2026-10-27 17:15"),
    # ── 中文标签后的全角冒号补空格，避免与独立时间正则冲突 ──
    ("测试时间：11：30", "测试时间: 11:30"),
    ("触发时间：2026-10-27 17：15", "触发时间: 2026-10-27 17:15"),
    # ── 正常半角文本保持不变 ──
    ("2026-10-27 17:15", "2026-10-27 17:15"),
    ("2026-10-27 17:15:00", "2026-10-27 17:15:00"),
    ("14:35", "14:35"),
    ("无时间文本", "无时间文本"),
    ("", ""),
])
def test_normalize_datetime_text(raw, expected):
    """全角归一化：冒号、分号、破折号、冒号旁空格"""
    assert normalize_datetime_text(raw) == expected


@pytest.mark.parametrize("raw", [
    "11：30", "8；44", "14；57：30", "14: 57", "2026-10-27——17:15",
    "测试时间：11：30", "2026-10-27 17:15:00",
])
def test_normalize_datetime_text_idempotent(raw):
    """归一化必须幂等：重复调用不应产生二次变形"""
    once = normalize_datetime_text(raw)
    assert normalize_datetime_text(once) == once


def test_normalize_datetime_text_enables_relative_regex():
    """全角冒号文本归一化后才能被相对日期正则命中（两条链路的协作契约）"""
    raw = "昨天17：15"
    assert sl._OCR_RELATIVE_DATE_TIME_RE.search(raw) is None      # 归一化前不命中
    normalized = normalize_datetime_text(raw)
    m = sl._OCR_RELATIVE_DATE_TIME_RE.search(normalized)
    assert m is not None and (m.group(1), m.group(2)) == ("昨天", "17:15")


# ══════════════════════════════════════════════════════════════════════════════
# 2. _preprocess_ocr_datetime —— OCR 日期时间预处理
# ══════════════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("raw,expected", [
    # ── 年份纠错：3000~9999 → 2000 + y%1000（首位 2 被 OCR 误识别）──
    ("6024-01-22 17:24", "2024-01-22 17:24"),
    ("3000-01-01 10:00", "2000-01-01 10:00"),
    ("8026-10-27 17:15", "2026-10-27 17:15"),
    ("2999-01-01 10:00", "2999-01-01 10:00"),      # 边界：< 3000 不改写
    ("2026-10-27 17:15", "2026-10-27 17:15"),      # 正常年份不改写
    # 已知宽松行为：9999 → 2000+999 = 2999，落在非法年份区间但实现如此
    ("9999-12-31 23:59", "2999-12-31 23:59"),
    # ── 日期与纯数字时间粘连拆分 ──
    ("2024-01-22172440", "2024-01-22 17:24:40"),   # 6 位 → HH:MM:SS
    ("6024-01-22172440", "2024-01-22 17:24:40"),   # 年份纠错 + 粘连拆分叠加
    ("2026-10-271724", "2026-10-27 17:24"),        # 4 位 → HH:MM
    ("2026-10-2717244", "2026-10-27 17:24"),       # 已知有损：5 位只取前 4 位，末位丢弃
    # ── 竖线分隔符（OCR 常把日期与时间间的空格识别成 | ）──
    ("2026-10-27|17:15", "2026-10-27 17:15"),
    ("2026-10-27 | 17:15", "2026-10-27 17:15"),
    ("2026-10-27｜17:15", "2026-10-27 17:15"),     # 全角竖线
    ("2026-10-27|17:15:00", "2026-10-27 17:15:00"),
    # ── 全角归一化（内部委托 normalize_datetime_text）──
    ("2026-10-27 17：15", "2026-10-27 17:15"),
    ("2026-10-27——17：15", "2026-10-27 17:15"),
    ("2026-10-27 17；15", "2026-10-27 17:15"),
    # ── 非法日期保护：月/日越界时不拆分，避免把垃圾数字误当时间 ──
    ("2026-13-45172440", "2026-13-45172440"),
    ("2026-00-10172440", "2026-00-10172440"),
    # ── 尾部数字超过 6 位不拆分（(?<!\\d) 保护，避免误切长数字串）──
    ("2026-10-271724401", "2026-10-271724401"),
    # ── 越界时间不拆分（HH>23 / MM>59）──
    ("2026-10-27254060", "2026-10-27254060"),
    # ── 已规范文本 / 无关文本原样返回 ──
    ("2026-10-27 17:15:00", "2026-10-27 17:15:00"),
    ("abc", "abc"),
    ("", ""),
])
def test_preprocess_ocr_datetime(raw, expected):
    """OCR 日期时间预处理：年份纠错、粘连拆分、竖线分隔符、全角归一化"""
    assert sl._preprocess_ocr_datetime(raw) == expected


@pytest.mark.parametrize("raw", [
    "2026-10-27 17:15",
    "2024-01-22 17:24:40",
    "6024-01-22172440",
    "2026-10-27|17:15",
    "2026-10-27 17：15",
])
def test_preprocess_ocr_datetime_idempotent(raw):
    """预处理幂等：二次调用不再变形（可安全用于重试链路）"""
    once = sl._preprocess_ocr_datetime(raw)
    assert sl._preprocess_ocr_datetime(once) == once


@pytest.mark.parametrize("raw,expected", [
    ("026-10-27 17:15", "2026-10-27 17:15"),      # 3 位年份补全
    ("2026-10-2717:15", "2026-10-27 17:15"),      # 含冒号的日期时间粘连拆分
])
def test_preprocess_ocr_datetime_known_gaps(raw, expected):
    """已修复：3位年份补全与含冒号粘连拆分"""
    assert sl._preprocess_ocr_datetime(raw) == expected


def test_preprocess_concat_datetime_still_extractable_end_to_end():
    """含冒号的粘连已被预处理拆分，完整链路可直接提取正确时间"""
    result = _run_ocr_pipeline("2026-10-2717:15")
    assert result["preprocessed"] == "2026-10-27 17:15"       # 预处理已拆分
    assert result["full_raw"] == "2026-10-27 17:15"           # 正则直接命中
    assert result["full_normalized"] == "2026-10-27 17:15"    # 已规范无需额外处理
    parsed = _parse_datetime_string(result["full_normalized"])
    assert parsed is not None and parsed[0] == "2026-10-27 17:15:00"


# ══════════════════════════════════════════════════════════════════════════════
# 3. _fix_ocr_char_confusion —— 字符混淆修复（带数字密度门槛）
# ══════════════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("raw,expected", [
    # ── O/o → 0 ──
    ("1O:3O", "10:30"),
    ("1o:3o", "10:30"),
    ("O1:30", "01:30"),
    ("14:3O", "14:30"),
    ("1O:30", "10:30"),
    # ── I/l/L → 1 ──
    ("1I:30", "11:30"),
    ("1l:3O", "11:30"),
    ("L2:30", "12:30"),
    ("I0:30", "10:30"),
    # ── Z/z → 2 ──
    ("1Z:30", "12:30"),
    ("1z:3O", "12:30"),
    ("Z0:15", "20:15"),
    # ── S → 5（仅大写 S 在正则字符类中，小写 s 不参与匹配）──
    ("1S:30", "15:30"),
    ("1S:3O", "15:30"),
    ("2S:45", "25:45"),
    # ── B → 8（仅大写 B）──
    ("1B:30", "18:30"),
    ("1B:3O", "18:30"),
    ("B0:15", "80:15"),       # 只做字符映射，不做时间有效性判断
    # ── 带秒的三段式 ──
    ("14:30:2O", "14:30:20"),
    ("1O:3O:25", "10:30:25"),
    # ── 点号 / 逗号同样被当作时间分隔符处理 ──
    ("1O.3O", "10.30"),
    ("1O,3O", "10,30"),
    # ── 嵌在中文文本中的时间片段也能修复 ──
    ("时间1O:3O结束", "时间10:30结束"),
    ("状态栏14:3O电量8O", "状态栏14:30电量8O"),   # "8O" 不匹配时间模式，保持原样
])
def test_fix_ocr_char_confusion_repairs(raw, expected):
    """字符混淆修复：O→0 / I,l,L→1 / Z,z→2 / S→5 / B→8"""
    assert sl._fix_ocr_char_confusion(raw) == expected


@pytest.mark.parametrize("raw", [
    # ── 正常数字文本不应被改动 ──
    "14:30",
    "10:30",
    "23:59:59",
    "14:30:25",
    "2026-10-27 17:15:00",
    "2026-10-27 17:15",
    "00:00",
    # ── 非时间结构不应被改动 ──
    "abc 1.23 def",          # 版本号：无字母混淆，替换后等价
    "Version 1.2.3",         # 分隔符后不足 2 位，正则不匹配
    "2O26-1O-27",            # 日期用 '-' 分隔，不在时间分隔符字符类中，避免污染日期
    "9:5",                   # 分隔符后只有 1 位，正则不匹配
    "Please review",         # 纯英文文本，无分隔符
    "",
])
def test_fix_ocr_char_confusion_noop(raw):
    """正常文本与非时间结构保持不变"""
    assert sl._fix_ocr_char_confusion(raw) == raw


@pytest.mark.parametrize("raw,digit_count,total", [
    # 数字密度 = 实际数字字符数 / 匹配片段长度，< 0.4 判定为乱码并跳过替换
    ("OI:OB", 0, 5),          # 0.00
    ("OO:OO", 0, 5),          # 0.00
    ("Il:SB", 0, 5),          # 0.00
    ("L2:SB", 1, 5),          # 0.20
    ("SB:1O", 1, 5),          # 0.20
    ("2O:3O:4O", 0, 8),       # 0.00
    ("1O:3O:2O", 3, 8),       # 0.375
    ("1O:SB:ZZ", 1, 8),       # 0.125
])
def test_fix_ocr_char_confusion_density_gate_rejects(raw, digit_count, total):
    """数字密度门槛：密度 < 0.4 的片段视为乱码，不做替换"""
    assert digit_count / total < 0.4          # 前置条件自校验，防止用例数据漂移
    assert sl._fix_ocr_char_confusion(raw) == raw


@pytest.mark.parametrize("raw,expected,digit_count,total", [
    ("1B:3O", "18:30", 2, 5),        # 0.40 —— 恰好等于门槛，仍执行替换
    ("1O:3O", "10:30", 2, 5),        # 0.40
    ("14:3O", "14:30", 3, 5),        # 0.60
    ("14:30:2O", "14:30:20", 5, 8),  # 0.625
    ("1O:3O:25", "10:30:25", 5, 8),  # 0.625
])
def test_fix_ocr_char_confusion_density_gate_accepts(raw, expected, digit_count, total):
    """数字密度门槛边界：密度 ≥ 0.4 时正常替换"""
    assert digit_count / total >= 0.4
    assert sl._fix_ocr_char_confusion(raw) == expected


def test_ocr_char_map_contents():
    """混淆映射表内容固定：新增映射必须同步更新黄金测试集"""
    assert sl._OCR_CHAR_MAP == {
        "O": "0", "o": "0",
        "I": "1", "l": "1", "L": "1",
        "Z": "2", "z": "2",
        "S": "5", "s": "5",
        "B": "8",
    }


def test_fix_ocr_char_confusion_lowercase_s_not_in_pattern():
    """特征化断言：小写 s/b 虽在映射表中，但不在正则字符类内，因此不会被修复"""
    assert sl._fix_ocr_char_confusion("1s:3O") == "1s:3O"
    assert sl._fix_ocr_char_confusion("1b:3O") == "1b:3O"
    # 对应的大写形式可以被修复
    assert sl._fix_ocr_char_confusion("1S:3O") == "15:30"


# ══════════════════════════════════════════════════════════════════════════════
# 4. _valid_ocr_time —— 时间有效性校验
# ══════════════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("raw", [
    "14:30", "14:30:25", "23:59", "00:00", "0:00", "07:05",
    "23:59:59", "00:00:00", "1:2", "14:59", "9:05", "12:00",
])
def test_valid_ocr_time_accepts(raw):
    """有效时间：小时 0-23、分钟 0-59、秒 0-59"""
    assert sl._valid_ocr_time(raw) is True


@pytest.mark.parametrize("raw", [
    # ── 小时越界 ──
    "25:00", "24:00", "99:99", "-1:30",
    # ── 分钟越界 ──
    "14:60", "14:99", "0060",
    # ── 秒越界 ──
    "14:30:60", "23:59:60",
    # ── 格式非法 ──
    "abc", "14", "", "14:", "1e:30", "1O:3O", ":", "14-30",
])
def test_valid_ocr_time_rejects(raw):
    """无效时间：越界数值、非法字符、缺失分段"""
    assert sl._valid_ocr_time(raw) is False


@pytest.mark.parametrize("raw", [
    " 14:30",      # 整体 strip 后仍为有效时间
    "14:30 ",      # 整体 strip 后仍为有效时间
])
def test_valid_ocr_time_strips_outer_whitespace(raw):
    """整体空白被 strip 处理，不影响有效性判断"""
    assert sl._valid_ocr_time(raw) is True


@pytest.mark.parametrize("raw", [
    "+1:30",       # 正号被 isdigit() 拒绝
])
def test_valid_ocr_time_rejects_plus_sign(raw):
    """已修复：+号不再被容忍，严格 isdigit 校验拒绝非纯数字段"""
    assert sl._valid_ocr_time(raw) is False


@pytest.mark.parametrize("raw", [
    "14:30:25:30",
    "14:30:25:99",
])
def test_valid_ocr_time_rejects_more_than_three_parts(raw):
    """已修复：超过 3 段的时间字符串视为无效"""
    assert sl._valid_ocr_time(raw) is False


# ══════════════════════════════════════════════════════════════════════════════
# 5. OCR 正则匹配覆盖度
# ══════════════════════════════════════════════════════════════════════════════

# ── 5.1 _OCR_TIME_FULL_RE：完整日期 + 时间 ──────────────────────────────────

@pytest.mark.parametrize("raw,expected", [
    ("2026-10-27 17:15:00", "2026-10-27 17:15:00"),
    ("2026-10-27 17:15", "2026-10-27 17:15"),
    ("2026/10/27 17:15", "2026/10/27 17:15"),          # 斜杠日期
    ("2026/10/27 17:15:30", "2026/10/27 17:15:30"),
    ("2026-1-2 7:05", "2026-1-2 7:05"),                 # 单位数月/日/时
    ("2026-10-2717:15:00", "2026-10-2717:15:00"),       # 日期与时间粘连（分隔符可选）
    ("2026-10-2717:15", "2026-10-2717:15"),
    ("2026-10-27.17:15", "2026-10-27.17:15"),           # 点号分隔
    ("2026-10-27,17:15", "2026-10-27,17:15"),           # 逗号分隔
    ("2026-10-27-17:15", "2026-10-27-17:15"),           # 横线分隔
    ("2026-10-27;17:15", "2026-10-27;17:15"),           # 分号分隔（回溯匹配）
    ("前缀 2026-10-27 17:15 后缀", "2026-10-27 17:15"),  # 夹在中文文本中
    ("1026-10-27 17:15", "1026-10-27 17:15"),           # 4 位年份即可，不校验取值范围
])
def test_ocr_time_full_re_matches(raw, expected):
    """_OCR_TIME_FULL_RE 匹配完整日期时间"""
    m = sl._OCR_TIME_FULL_RE.search(raw)
    assert m is not None, f"应当匹配: {raw!r}"
    assert m.group(1) == expected


@pytest.mark.parametrize("raw", [
    "17:15",                 # 只有时间，无日期
    "2026-10-27",            # 只有日期，无时间
    "26-10-27 17:15",        # 2 位年份不匹配（需先经 _normalize_ocr_time 扩展）
    "2026-10-27 17",         # 时间不足 HH:MM
    "2026-10-27 1:2",        # 分钟不足 2 位
    "无时间",
    "",
])
def test_ocr_time_full_re_rejects(raw):
    """_OCR_TIME_FULL_RE 拒绝边界：缺日期、缺时间、年份位数不足"""
    assert sl._OCR_TIME_FULL_RE.search(raw) is None, f"不应匹配: {raw!r}"


def test_ocr_time_full_re_does_not_validate_calendar():
    """特征化断言：正则只做结构匹配，月/日合法性由 _preprocess_ocr_datetime 把关"""
    m = sl._OCR_TIME_FULL_RE.search("2026-13-45 17:15")
    assert m is not None and m.group(1) == "2026-13-45 17:15"
    # 但预处理阶段会因月份越界拒绝拆分粘连数字
    assert sl._preprocess_ocr_datetime("2026-13-45172440") == "2026-13-45172440"


# ── 5.2 _OCR_TIME_ONLY_RE：仅时间 ───────────────────────────────────────────

@pytest.mark.parametrize("raw,expected", [
    ("17:15", ["17:15"]),
    ("17:15:00", ["17:15:00"]),
    ("9:05", ["9:05"]),
    ("00:00", ["00:00"]),
    ("23:59", ["23:59"]),
    ("14,35", ["14,35"]),                     # 逗号分隔（EasyOCR 常见误识别）
    ("10.26", ["10.26"]),                     # 点号分隔
    ("10;26", ["10;26"]),                     # 分号分隔
    ("2026-10-27 17:15:00", ["17:15:00"]),    # 从完整日期时间中取出时间部分
    ("12:34 56:78", ["12:34", "56:78"]),      # 多个候选全部返回（56:78 由 _valid_ocr_time 过滤）
    ("10:20:30:40", ["10:20:30"]),            # 四段串只取前三段
    ("14:35:22 extra", ["14:35:22"]),
    ("a14:35", ["14:35"]),                    # 前置字母不阻断
    ("14:35a", ["14:35"]),                    # 后置字母不阻断
    ("-14:35", ["14:35"]),
    ("14:35-", ["14:35"]),
])
def test_ocr_time_only_re_matches(raw, expected):
    """_OCR_TIME_ONLY_RE 匹配仅时间片段"""
    assert [m.group(1) for m in sl._OCR_TIME_ONLY_RE.finditer(raw)] == expected


@pytest.mark.parametrize("raw", [
    "12345678",            # 长数字串：不切出子串
    "117:15",              # 前置数字阻断（(?<!\\d)）
    "17:159",              # 后置数字阻断（(?!\\d)）
    "2026-10-2717:15",     # 粘连日期时间：整体被前置数字阻断，不产生 "7:15" 之类假匹配
    "1O:30",               # 含字母混淆：需先经 _fix_ocr_char_confusion
    "版本1.2.3",            # 分隔符两侧位数不足
    "1:2",                 # 分钟不足 2 位
    "无时间",
    "",
])
def test_ocr_time_only_re_rejects(raw):
    """_OCR_TIME_ONLY_RE 拒绝边界：长数字串子串、前后数字粘连、字母混淆"""
    assert [m.group(1) for m in sl._OCR_TIME_ONLY_RE.finditer(raw)] == []


# ── 5.3 _OCR_BARE_TIME_RE：无分隔符 4 位数字 ────────────────────────────────

@pytest.mark.parametrize("raw,expected", [
    ("1435", [("14", "35")]),
    ("0930", [("09", "30")]),
    ("2400", [("24", "00")]),
    ("2026", [("20", "26")]),                 # 正则层不判年份，年份保护在 _fix_ocr_missing_colon
    ("时间1435", [("14", "35")]),              # 前置中文不阻断
    ("(1435)", [("14", "35")]),
    ("[1435]", [("14", "35")]),
    ("1435 1620", [("14", "35"), ("16", "20")]),
    ("1435\t1620", [("14", "35"), ("16", "20")]),
    ("1435，1620", [("14", "35"), ("16", "20")]),   # 全角逗号不阻断
])
def test_ocr_bare_time_re_matches(raw, expected):
    """_OCR_BARE_TIME_RE 匹配独立 4 位数字"""
    assert [(m.group(1), m.group(2)) for m in sl._OCR_BARE_TIME_RE.finditer(raw)] == expected


@pytest.mark.parametrize("raw", [
    "14356",              # 5 位数字：后置数字阻断
    "143",                # 不足 4 位
    "abc1435",            # 前置字母阻断
    "1435abc",            # 后置字母阻断
    "a1435",
    "1435.mp4",           # 后置 '.' 阻断（文件名场景）
    "1435/2",             # 后置 '/' 阻断（路径场景）
    "1435-2",             # 后置 '-' 阻断（日期场景）
    "/1435",              # 前置 '/' 阻断
    "2026-10-271435",     # 粘连在日期后：前置数字阻断
    "",
])
def test_ocr_bare_time_re_rejects(raw):
    """_OCR_BARE_TIME_RE 拒绝边界：位数不足/超长、字母数字路径符号包围"""
    assert [(m.group(1), m.group(2)) for m in sl._OCR_BARE_TIME_RE.finditer(raw)] == []


# ── 5.4 _OCR_COMMA_TIME_RE：逗号代冒号 ──────────────────────────────────────

@pytest.mark.parametrize("raw,expected", [
    ("14,35", [("14", "35")]),
    ("10,12", [("10", "12")]),
    ("0,00", [("0", "00")]),
    ("25,70", [("25", "70")]),      # 正则不校验取值，合法性由 _fix_ocr_missing_colon 把关
    ("a14,35", [("14", "35")]),     # 前置字母不阻断
    ("时间14,35", [("14", "35")]),
    # 已知回溯行为：三段逗号串中第一段被 (?![\\d,.]) 拒绝，只命中后两段
    ("14,35,22", [("35", "22")]),
])
def test_ocr_comma_time_re_matches(raw, expected):
    """_OCR_COMMA_TIME_RE 匹配逗号代冒号的时间"""
    assert [(m.group(1), m.group(2)) for m in sl._OCR_COMMA_TIME_RE.finditer(raw)] == expected


@pytest.mark.parametrize("raw", [
    "14,350",        # 后置数字阻断
    "114,35",        # 前置数字阻断
    "14,35.",        # 后置 '.' 阻断
    "14,35,",        # 后置 ',' 阻断
    "1435",          # 无逗号
    "14:35",         # 已是冒号
    "14,",           # 逗号后不足 2 位
    ",35",           # 逗号前无数字
    "",
])
def test_ocr_comma_time_re_rejects(raw):
    """_OCR_COMMA_TIME_RE 拒绝边界：前后数字/标点粘连、位数不足"""
    assert [(m.group(1), m.group(2)) for m in sl._OCR_COMMA_TIME_RE.finditer(raw)] == []


# ── 5.5 _OCR_RELATIVE_DATE_TIME_RE：中文相对日期 + 时间 ─────────────────────

@pytest.mark.parametrize("raw,expected", [
    ("昨天 17:15", ("昨天", "17:15")),
    ("今天14:30", ("今天", "14:30")),
    ("前天 9:05", ("前天", "9:05")),
    ("大前天23:59:59", ("大前天", "23:59:59")),
    ("昨天-17:15", ("昨天", "17:15")),
    ("昨天  17:15", ("昨天", "17:15")),          # 多空格
    ("昨天8;44", ("昨天", "8;44")),              # 分号分隔符也在字符类中
    ("昨天17.15", ("昨天", "17.15")),
    ("记录昨天 17:15 发生", ("昨天", "17:15")),   # 夹在句子中
    ("大前天 00:00", ("大前天", "00:00")),
])
def test_ocr_relative_date_time_re_matches(raw, expected):
    """_OCR_RELATIVE_DATE_TIME_RE 匹配中文相对日期 + 时间"""
    m = sl._OCR_RELATIVE_DATE_TIME_RE.search(raw)
    assert m is not None, f"应当匹配: {raw!r}"
    assert (m.group(1), m.group(2)) == expected


@pytest.mark.parametrize("raw", [
    "明天 17:15",        # 不在支持列表（昨天/今天/前天/大前天）
    "昨天下午5点",        # 中文口语时间，非 HH:MM
    "前天下午三点",
    "昨天",              # 只有相对日期，缺时间
    "昨天17：15",        # 全角冒号未归一化（须先经 normalize_datetime_text）
    "17:15",             # 只有时间，缺相对日期
    "",
])
def test_ocr_relative_date_time_re_rejects(raw):
    """_OCR_RELATIVE_DATE_TIME_RE 拒绝边界：不支持的相对词、缺时间、全角冒号未归一化"""
    assert sl._OCR_RELATIVE_DATE_TIME_RE.search(raw) is None


# ══════════════════════════════════════════════════════════════════════════════
# 6. _fix_ocr_missing_colon —— 冒号丢失修复
# ══════════════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("raw,expected", [
    # ── 孤立 4 位数字补冒号（时间上下文）──
    ("1435", "14:35"),
    ("0930", "09:30"),
    ("2359", "23:59"),
    ("0000", "00:00"),
    ("时间1435", "时间14:35"),
    ("1435 1620", "14:35 16:20"),
    ("(1435)", "(14:35)"),
    # ── 逗号代冒号 ──
    ("10,12", "10:12"),
    ("14,35", "14:35"),
    ("0,00", "0:00"),
    ("截图14,35完成", "截图14:35完成"),
])
def test_fix_ocr_missing_colon_repairs(raw, expected):
    """冒号丢失修复：孤立 4 位数字与逗号代冒号"""
    assert sl._fix_ocr_missing_colon(raw) == expected


@pytest.mark.parametrize("raw,expected", [
    # ── 非时间上下文（字母包围、文件名、路径）不修复 ──
    ("abc1435def", "abc1435def"),
    ("1435.mp4", "1435.mp4"),
    ("VID_20261014_113000", "VID_20261014_113000"),
    ("14356", "14356"),
    ("143", "143"),
    # ── 年份区间 1900-2099 保护 ──
    ("2026", "2026"),
    ("1935", "1935"),
    ("2099", "2099"),
    ("1900", "1900"),       # 保护区间下边界，同样原样返回
    # ── 越界时间不修复 ──
    ("2400", "2400"),         # 小时 24 越界
    ("0060", "0060"),         # 分钟 60 越界
    ("2360", "2360"),
    ("1899", "1899"),         # 不在年份保护区间，但分钟 99 越界
    ("25,70", "25,70"),       # 逗号形式同样校验取值
    # ── 正则拒绝的粘连形态 ──
    ("14,350", "14,350"),
    ("114,35", "114,35"),
    ("14,35.", "14,35."),
    # ── 已规范文本不变 ──
    ("14:35", "14:35"),
    ("2026-10-27 17:15", "2026-10-27 17:15"),
    ("2026-10-2717:15", "2026-10-2717:15"),
    ("", ""),
])
def test_fix_ocr_missing_colon_skips(raw, expected):
    """非时间上下文、年份区间、越界取值均不修复"""
    assert sl._fix_ocr_missing_colon(raw) == expected


def test_fix_ocr_missing_colon_year_guard_boundary():
    """年份保护区间边界：[1900, 2099] 内保持原样，区间外按时间处理"""
    assert sl._fix_ocr_missing_colon("1899") == "1899"    # 区间外，但分钟 99 越界 → 原样
    assert sl._fix_ocr_missing_colon("1900") == "1900"    # 区间内 → 保护
    assert sl._fix_ocr_missing_colon("2099") == "2099"    # 区间内 → 保护
    assert sl._fix_ocr_missing_colon("2100") == "21:00"   # 区间外且时间合法 → 补冒号


# ══════════════════════════════════════════════════════════════════════════════
# 7. _normalize_ocr_time —— OCR 时间规范化（预处理链路的后半段）
# ══════════════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("raw,expected", [
    # ── 两位年份扩展 ──
    ("26-10-20 11:30", "2026-10-20 11:30"),
    ("26-10-20", "2026-10-20"),
    ("05-10-20 11:30", "2005-10-20 11:30"),
    ("00-01-01 00:00", "2000-01-01 00:00"),
    # ── 年份纠错（3000~9999）──
    ("6024-01-22 17:24", "2024-01-22 17:24"),
    # ── 点号/逗号/分号 → 冒号 ──
    ("10.26.39", "10:26:39"),
    ("10,26", "10:26"),
    ("10;26", "10:26"),
    ("17.24.40", "17:24:40"),
    # ── 独立 6 位数字时间 ──
    ("172440", "17:24:40"),
    ("093000", "09:30:00"),
    # ── 日期与时间粘连 / 点号分隔 ──
    ("2024-01-22172440", "2024-01-22 17:24:40"),
    ("2026-01-09.14:02", "2026-01-09 14:02"),
    ("2026-01-0914:02", "2026-01-09 14:02"),
    ("2026-10-2717:15", "2026-10-27 17:15"),
    # ── 非法日期/越界时间不动 ──
    ("2026-13-45172440", "2026-13-45172440"),
    ("254060", "254060"),
    # ── 已规范文本不变 ──
    ("2026-10-27 17:15", "2026-10-27 17:15"),
    ("2026-10-27 17:15:00", "2026-10-27 17:15:00"),
    ("17:24:40", "17:24:40"),
    ("", ""),
])
def test_normalize_ocr_time(raw, expected):
    """OCR 时间规范化：两位年份扩展、分隔符统一、粘连拆分"""
    assert sl._normalize_ocr_time(raw) == expected


# ══════════════════════════════════════════════════════════════════════════════
# 8. _resolve_12h_ambiguity —— 12/24 小时制歧义消解
# ══════════════════════════════════════════════════════════════════════════════

def test_resolve_12h_no_reference_keeps_original():
    """无任何参考时保留 OCR 原始值"""
    ts, dt = sl._resolve_12h_ambiguity(
        "09:15:00", DATE_TUPLE, [], None, _parse_datetime_string)
    assert ts == "2026-10-27 09:15:00"
    assert dt == datetime(2026, 10, 27, 9, 15)


def test_resolve_12h_gmlogger_anchor_converts_am_to_pm():
    """gmlogger 文件名时间锚点：上午值与锚点相差过大 → 转 +12h"""
    gm_ref = datetime(2026, 10, 27, 23, 20)     # 与 23:30 相差 10 分钟（≤30 分钟阈值）
    ts, dt = sl._resolve_12h_ambiguity(
        "11:30:00", DATE_TUPLE, [], gm_ref, _parse_datetime_string)
    assert ts == "2026-10-27 23:30:00"
    assert dt == datetime(2026, 10, 27, 23, 30)


def test_resolve_12h_gmlogger_anchor_converts_pm_to_am():
    """小时 ≥ 12 时反向尝试 -12h（兼容时区偏移）"""
    gm_ref = datetime(2026, 10, 27, 11, 20)
    ts, dt = sl._resolve_12h_ambiguity(
        "23:30:00", DATE_TUPLE, [], gm_ref, _parse_datetime_string)
    assert ts == "2026-10-27 11:30:00"
    assert dt == datetime(2026, 10, 27, 11, 30)


def test_resolve_12h_gmlogger_anchor_keeps_close_original():
    """原值已落在 gmlogger 锚点 ±30 分钟内 → 不转换"""
    gm_ref = datetime(2026, 10, 27, 11, 35)
    ts, _ = sl._resolve_12h_ambiguity(
        "11:30:00", DATE_TUPLE, [], gm_ref, _parse_datetime_string)
    assert ts == "2026-10-27 11:30:00"


def test_resolve_12h_ref_pool_hit_converts():
    """参考池命中备选值（±5 分钟）→ 转换"""
    ref_pool = [datetime(2026, 10, 27, 23, 32)]
    ts, dt = sl._resolve_12h_ambiguity(
        "11:30:00", DATE_TUPLE, ref_pool, None, _parse_datetime_string)
    assert ts == "2026-10-27 23:30:00"
    assert dt == datetime(2026, 10, 27, 23, 30)


def test_resolve_12h_ref_pool_hit_keeps_original():
    """参考池命中原值 → 保留原值"""
    ref_pool = [datetime(2026, 10, 27, 11, 32)]
    ts, _ = sl._resolve_12h_ambiguity(
        "11:30:00", DATE_TUPLE, ref_pool, None, _parse_datetime_string)
    assert ts == "2026-10-27 11:30:00"


def test_resolve_12h_ref_pool_accepts_tuple_entries():
    """参考池兼容 (字符串, datetime) 元组形式"""
    ref_pool = [("2026-10-27 23:32:00", datetime(2026, 10, 27, 23, 32))]
    ts, _ = sl._resolve_12h_ambiguity(
        "11:30:00", DATE_TUPLE, ref_pool, None, _parse_datetime_string)
    assert ts == "2026-10-27 23:30:00"


def test_resolve_12h_gmlogger_takes_precedence_over_ref_pool():
    """gmlogger 锚点优先级高于参考池：锚点命中原值时不再看参考池"""
    gm_ref = datetime(2026, 10, 27, 11, 35)                    # 原值接近锚点
    ref_pool = [datetime(2026, 10, 27, 23, 32)]                # 参考池却命中备选值
    ts, _ = sl._resolve_12h_ambiguity(
        "11:30:00", DATE_TUPLE, ref_pool, gm_ref, _parse_datetime_string)
    assert ts == "2026-10-27 11:30:00"


def test_resolve_12h_gmlogger_closer_wins_when_neither_within_threshold():
    """锚点与两个候选都超出 30 分钟阈值时，退回“谁更近取谁”的兜底规则"""
    gm_ref = datetime(2026, 10, 27, 20, 0)     # 距 11:30 为 8.5h，距 23:30 为 3.5h
    ts, _ = sl._resolve_12h_ambiguity(
        "11:30:00", DATE_TUPLE, [], gm_ref, _parse_datetime_string)
    assert ts == "2026-10-27 23:30:00"


def test_resolve_12h_equidistant_keeps_original():
    """两个候选与锚点等距时保留原值（不做无依据的转换）"""
    gm_ref = datetime(2026, 10, 27, 17, 30)    # 距 11:30 与 23:30 均为 6h
    ts, _ = sl._resolve_12h_ambiguity(
        "11:30:00", DATE_TUPLE, [], gm_ref, _parse_datetime_string)
    assert ts == "2026-10-27 11:30:00"


@pytest.mark.parametrize("raw", ["99:99:99", "", "25:00:00", "abc"])
def test_resolve_12h_unparsable_returns_none(raw):
    """无法解析的时间返回 None，由调用方走兜底分支"""
    assert sl._resolve_12h_ambiguity(
        raw, DATE_TUPLE, [], None, _parse_datetime_string) is None


def test_resolve_12h_noon_boundary_keeps_original():
    """12:00 属于 hour >= 12 分支，备选值为 00:00；无参考时保留原值"""
    ts, dt = sl._resolve_12h_ambiguity(
        "12:00:00", DATE_TUPLE, [], None, _parse_datetime_string)
    assert ts == "2026-10-27 12:00:00"
    assert dt == datetime(2026, 10, 27, 12, 0)


def test_resolve_12h_pads_single_digit_date_tuple():
    """日期元组按 %04d-%02d-%02d 补零"""
    ts, dt = sl._resolve_12h_ambiguity(
        "9:05:00", (2026, 1, 2), [], None, _parse_datetime_string)
    assert ts == "2026-01-02 09:05:00"
    assert dt == datetime(2026, 1, 2, 9, 5)


# ══════════════════════════════════════════════════════════════════════════════
# 9. _vote_from_texts —— 多帧投票
# ══════════════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("texts", [
    [],                                        # 空帧列表
    [(0, ""), (1, "")],                        # 全空文本
    [(0, None), (1, None)],                    # None 文本
    [(0, "abc"), (1, "无时间")],                # 无时间片段
    [(0, "14:35")],                            # 仅 1 帧命中，票数不足
    [(0, "25:00"), (1, "25:00")],              # 时间越界，被 _valid_ocr_time 过滤
    [(0, "99:99"), (1, "99:99")],
])
def test_vote_from_texts_returns_empty_without_parse_fn(texts):
    """提前返回分支：不触及日期解析，无需注入全局 parse_fn"""
    assert sl._vote_from_texts(texts, [datetime(2026, 10, 27, 14, 35)], GM_REF_DATE, TOL_5MIN) == ("", 0)


def test_vote_from_texts_no_date_reference(inject_parse_fn):
    """参考池与 gmlogger 日期都缺失时无法补全日期 → 放弃"""
    texts = [(0, "14:35"), (1, "14:35")]
    assert sl._vote_from_texts(texts, [], None, TOL_5MIN) == ("", 0)


def test_vote_from_texts_majority_wins(inject_parse_fn):
    """同一 HH:MM 出现 ≥2 次即采用，票数返回出现次数"""
    texts = [(0, "14:35"), (1, "14:35"), (2, "14:36")]
    ref_pool = [datetime(2026, 10, 27, 14, 35)]
    assert sl._vote_from_texts(texts, ref_pool, GM_REF_DATE, TOL_5MIN) == ("2026-10-27 14:35", 2)


def test_vote_from_texts_highest_count_selected(inject_parse_fn):
    """多候选并存时取票数最高者"""
    texts = [(0, "10:30"), (1, "10:30"), (2, "10:30"), (3, "11:00"), (4, "11:00")]
    ref_pool = [datetime(2026, 10, 27, 10, 30)]
    assert sl._vote_from_texts(texts, ref_pool, GM_REF_DATE, TOL_5MIN) == ("2026-10-27 10:30", 3)


def test_vote_from_texts_uses_gmlogger_date_when_pool_empty(inject_parse_fn):
    """参考池为空时用 gmlogger 日期补全，并跳过容差校验"""
    texts = [(0, "14:35"), (1, "14:35")]
    assert sl._vote_from_texts(texts, [], GM_REF_DATE, TOL_5MIN) == ("2026-10-27 14:35", 2)


def test_vote_from_texts_rejects_outside_tolerance(inject_parse_fn):
    """投票结果必须落在参考池容差内，否则整体放弃"""
    texts = [(0, "14:35"), (1, "14:35")]
    ref_pool = [datetime(2026, 10, 27, 20, 0)]         # 相差 5.5 小时
    assert sl._vote_from_texts(texts, ref_pool, GM_REF_DATE, TOL_5MIN) == ("", 0)


def test_vote_from_texts_tolerance_is_inclusive(inject_parse_fn):
    """容差为闭区间：恰好等于 tol 也算命中；tol=0 时只接受完全相等"""
    texts = [(0, "10:30"), (1, "10:30")]
    exact_pool = [datetime(2026, 10, 27, 10, 35)]      # 相差 300 秒
    assert sl._vote_from_texts(texts, exact_pool, GM_REF_DATE, 300) == ("2026-10-27 10:30", 2)
    assert sl._vote_from_texts(texts, exact_pool, GM_REF_DATE, 0) == ("", 0)


def test_vote_from_texts_applies_char_confusion_fix(inject_parse_fn):
    """投票前先做字符混淆修复：1O:3O → 10:30"""
    texts = [(0, "1O:3O"), (1, "1O:3O")]
    ref_pool = [datetime(2026, 10, 27, 10, 30)]
    assert sl._vote_from_texts(texts, ref_pool, GM_REF_DATE, TOL_5MIN) == ("2026-10-27 10:30", 2)


def test_vote_from_texts_applies_missing_colon_fix(inject_parse_fn):
    """投票前先做冒号补全：1435 → 14:35"""
    texts = [(0, "1435"), (1, "1435")]
    ref_pool = [datetime(2026, 10, 27, 14, 35)]
    assert sl._vote_from_texts(texts, ref_pool, GM_REF_DATE, TOL_5MIN) == ("2026-10-27 14:35", 2)


def test_vote_from_texts_applies_comma_fix(inject_parse_fn):
    """投票前先做逗号代冒号修复：10,30 → 10:30"""
    texts = [(0, "10,30"), (1, "10,30")]
    ref_pool = [datetime(2026, 10, 27, 10, 30)]
    assert sl._vote_from_texts(texts, ref_pool, GM_REF_DATE, TOL_5MIN) == ("2026-10-27 10:30", 2)


def test_vote_from_texts_scans_all_matches_per_frame(inject_parse_fn):
    """单帧内扫描全部时间匹配，避免视频计数器 00:00 遮挡真实时钟"""
    texts = [(0, "00:00 10:30 00:00"), (1, "00:00 10:30 00:00")]
    ref_pool = [datetime(2026, 10, 27, 10, 30)]
    # 00:00 得 4 票 > 10:30 得 2 票，但 00:00 不在容差内 → 整体放弃（当前实现的已知局限）
    assert sl._vote_from_texts(texts, ref_pool, GM_REF_DATE, TOL_5MIN) == ("", 0)


def test_vote_from_texts_missing_module_level_parse_fn():
    """缺陷已修复：函数内部局部导入 _parse_datetime_string，未注入全局 parse_fn 时投票仍能返回结果"""
    assert not hasattr(sl, "_parse_datetime_string")
    texts = [(0, "14:35"), (1, "14:35")]
    ref_pool = [datetime(2026, 10, 27, 14, 35)]
    assert sl._vote_from_texts(texts, ref_pool, GM_REF_DATE, TOL_5MIN) == ("2026-10-27 14:35", 2)


def test_vote_from_texts_normalizes_fullwidth_colon(inject_parse_fn):
    """缺陷已修复：投票前调用 normalize_datetime_text，全角冒号的时间文本可参与投票"""
    ref_pool = [datetime(2026, 10, 27, 10, 30)]
    assert sl._vote_from_texts(
        [(0, "10：30"), (1, "10：30")], ref_pool, GM_REF_DATE, TOL_5MIN
    ) == ("2026-10-27 10:30", 2)


@pytest.mark.parametrize("texts", [
    [(0, "10:30:00"), (1, "10:30")],           # 带秒与不带秒被当作两个不同候选，各自只有 1 票
])
def test_vote_from_texts_known_gaps(inject_parse_fn, texts):
    """特征化断言：记录投票链路当前仍未覆盖的归一化场景"""
    ref_pool = [datetime(2026, 10, 27, 10, 30)]
    assert sl._vote_from_texts(texts, ref_pool, GM_REF_DATE, TOL_5MIN) == ("", 0)


def test_vote_from_texts_tie_breaks_by_insertion_order(inject_parse_fn):
    """特征化断言：票数相同时 Counter 按首次出现顺序取胜者"""
    ref_pool = [datetime(2026, 10, 27, 10, 30)]
    # "10:30" 先出现 → 平票时胜出并通过容差校验
    assert sl._vote_from_texts(
        [(0, "10:30 00:00"), (1, "10:30 00:00")], ref_pool, GM_REF_DATE, TOL_5MIN
    ) == ("2026-10-27 10:30", 2)
    # "00:00" 先出现 → 平票时胜出，但不在容差内 → 放弃
    assert sl._vote_from_texts(
        [(0, "00:00 10:30"), (1, "00:00 10:30")], ref_pool, GM_REF_DATE, TOL_5MIN
    ) == ("", 0)


def test_vote_from_texts_accepts_tuple_ref_pool(inject_parse_fn):
    """缺陷已修复：参考池兼容 (str, datetime) 元组元素，与 _resolve_12h_ambiguity 一致"""
    ref_pool = [("2026-10-27 10:30:00", datetime(2026, 10, 27, 10, 30))]
    assert sl._vote_from_texts(
        [(0, "10:30"), (1, "10:30")], ref_pool, GM_REF_DATE, TOL_5MIN
    ) == ("2026-10-27 10:30", 2)


# ══════════════════════════════════════════════════════════════════════════════
# 10. 端到端流水线（生产调用顺序）
# ══════════════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("raw,expected_prepared,expected_full", [
    ("6024-01-22172440", "2024-01-22 17:24:40", "2024-01-22 17:24:40"),
    ("2024-01-22172440", "2024-01-22 17:24:40", "2024-01-22 17:24:40"),
    ("2026-10-27|17:15", "2026-10-27 17:15", "2026-10-27 17:15"),
    ("截图时间 2026-10-27 17；15", "截图时间 2026-10-27 17:15", "2026-10-27 17:15"),
    ("2026-10-27——17：15", "2026-10-27 17:15", "2026-10-27 17:15"),
    ("2026-10-2717:15", "2026-10-27 17:15", "2026-10-27 17:15"),
])
def test_pipeline_full_datetime(raw, expected_prepared, expected_full):
    """完整日期时间：预处理 → 正则 → 规范化 → 可解析"""
    result = _run_ocr_pipeline(raw)
    assert result["preprocessed"] == expected_prepared
    assert result["full_raw"] == expected_full
    normalized = result["full_normalized"]
    parsed = _parse_datetime_string(normalized)
    assert parsed is not None, f"规范化后应可解析: {normalized!r}"
    assert parsed[1].year >= 2000 and parsed[1].year < 3000


@pytest.mark.parametrize("raw,expected_prepared,expected_time", [
    ("1O:3O", "10:30", "10:30"),
    ("1435", "14:35", "14:35"),
    ("0930", "09:30", "09:30"),
    ("14,35", "14:35", "14:35"),
    ("1O.3O", "10.30", "10:30"),      # 点号分隔由 _normalize_ocr_time 统一为冒号
    ("状态栏 14:35 电量80", "状态栏 14:35 电量80", "14:35"),
    ("14:30:2O", "14:30:20", "14:30:20"),
])
def test_pipeline_time_only(raw, expected_prepared, expected_time):
    """仅时间：预处理 → 正则 → 规范化 → 有效性校验"""
    result = _run_ocr_pipeline(raw)
    assert result["preprocessed"] == expected_prepared
    assert result["full_raw"] == ""                      # 无日期，完整正则不命中
    normalized = sl._normalize_ocr_time(result["only_raw"])
    assert normalized == expected_time
    assert sl._valid_ocr_time(normalized) is True


@pytest.mark.parametrize("raw,expected_word,expected_time", [
    ("昨天17：15", "昨天", "17:15"),
    ("昨天 17:15", "昨天", "17:15"),
    ("今天14:30", "今天", "14:30"),
    ("前天8；44", "前天", "8:44"),
    ("大前天23:59:59", "大前天", "23:59:59"),
])
def test_pipeline_relative_date(raw, expected_word, expected_time):
    """中文相对日期：全角归一化后才能被相对日期正则命中"""
    result = _run_ocr_pipeline(raw)
    assert result["relative"] == (expected_word, expected_time)
    normalized = sl._normalize_ocr_time(result["relative"][1])
    assert normalized == expected_time
    assert sl._valid_ocr_time(normalized) is True


@pytest.mark.parametrize("raw", [
    "版本 1.2.3",
    "Please review the log",
    "无时间信息",
    "",
    "2O26-1O-27",          # 日期部分含字母混淆，链路不会把它误当时间
])
def test_pipeline_rejects_non_time_text(raw):
    """非时间文本：三级预处理后仍无任何正则命中"""
    result = _run_ocr_pipeline(raw)
    assert result["full_raw"] == ""
    assert result["only_raw"] == ""
    assert result["relative"] is None


def test_pipeline_preserves_valid_input():
    """已规范输入经过完整链路后保持不变（幂等性保障）"""
    raw = "2026-10-27 17:15:00"
    result = _run_ocr_pipeline(raw)
    assert result["missing_colon"] == raw
    assert result["char_confusion"] == raw
    assert result["preprocessed"] == raw
    assert result["full_raw"] == raw
    assert result["full_normalized"] == raw
    assert result["only_raw"] == "17:15:00"
