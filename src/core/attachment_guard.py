"""附件下载守卫：体积上限、磁盘水位、按 bug/批次预算、附件缓存与临时目录清理

背景：时间批量提取与问题排查会为每个 bug 下载多个压缩包附件（zip/tar/7z/rar 分卷），
原先只有"按附件 size 元数据预检"和"连续失败熔断"，一旦 Jira 返回的 size 缺失、
或 rar 分卷总量很大，就可能把磁盘写满（进而导致数据库/日志写入失败）。

本模块提供统一的下载入口与限额，供这些链路共用：
- 单附件硬上限（下载过程中按字节判断，不依赖元数据）
- rar 分卷总量上限
- 单 bug / 单批次附件总预算
- 下载前磁盘可用空间检查
- 附件内容缓存（同一附件在 TTL 内只下载一次）
- 过期临时目录清理
"""
import hashlib
import os
import shutil
import threading
import time

from src.config import PROJECT_ROOT, setup_logger

logger = setup_logger("attachment_guard")

# ── 限额（与"分析三"的建议值一致）──
MAX_ATTACHMENT_BYTES = 500 * 1024 * 1024        # 单个附件下载硬上限 500MB
MAX_RAR_VOLUME_BYTES = 2 * 1024 * 1024 * 1024   # rar 分卷总量上限 2GB
MAX_BUG_ATTACH_BYTES = 3 * 1024 * 1024 * 1024   # 单个 bug 的附件总预算 3GB
MAX_BATCH_ATTACH_BYTES = 20 * 1024 * 1024 * 1024  # 单批次附件总预算 20GB
MIN_FREE_DISK_BYTES = 5 * 1024 * 1024 * 1024    # 下载前要求的最小可用磁盘 5GB
MAX_SINGLE_ENTRY_BYTES = 2 * 1024 * 1024 * 1024  # 解压单个条目上限 2GB（7z/rar 需整条目落盘）
MAX_MEDIA_BYTES = 1024 * 1024 * 1024            # 视频/图片附件上限 1GB（录屏常超 500MB，单独放宽）

# 附件缓存：data/cache/attachments（data/* 已被 .gitignore 忽略）
CACHE_DIR = os.path.join(PROJECT_ROOT, "data", "cache", "attachments")
CACHE_TTL_SECONDS = 24 * 60 * 60                # 缓存有效期 24 小时
MAX_CACHE_BYTES = 5 * 1024 * 1024 * 1024        # 缓存目录总量上限 5GB（超出按最旧删除）
_TEMP_CLEAN_INTERVAL = 60 * 60                  # 过期临时目录清理间隔 1 小时


class AttachmentLimitError(RuntimeError):
    """附件超出限额（体积/预算/磁盘空间）"""


class AttachmentBudget:
    """按 bug 与时间窗口的附件体积预算（线程安全）

    - begin_batch()：新的批量任务开始时重置（可选，不调用也存在兜底窗口）
    - begin_bug(bugid)：开始处理某个 bug 时重置该 bug 计数
    - charge(n, bugid)：下载到 n 字节后记账，超预算抛 AttachmentLimitError

    为什么用"滚动窗口"而不是严格的批次边界：批量入口有 4 处（时间提取 x2、诊断、回归），
    逐个接线容易漏；用 6 小时滚动窗口做总量兜底，行为等价且不会因为漏改而失效。
    """

    WINDOW_SECONDS = 6 * 3600

    def __init__(self):
        self._lock = threading.Lock()
        self._bug_used = {}
        self._batch_used = 0
        self._window_used = 0
        self._window_start = time.time()

    def begin_batch(self):
        with self._lock:
            self._batch_used = 0
            self._bug_used = {}

    def begin_bug(self, bugid: str):
        with self._lock:
            if bugid:
                self._bug_used[bugid] = 0

    def used(self, bugid: str = "") -> int:
        with self._lock:
            return self._bug_used.get(bugid, 0) if bugid else self._batch_used

    def window_used(self) -> int:
        with self._lock:
            return self._window_used

    def _roll_window_locked(self):
        now = time.time()
        if now - self._window_start > self.WINDOW_SECONDS:
            self._window_start = now
            self._window_used = 0

    def charge(self, size: int, bugid: str = ""):
        size = max(0, int(size or 0))
        with self._lock:
            self._batch_used += size
            self._roll_window_locked()
            self._window_used += size
            if self._window_used > MAX_BATCH_ATTACH_BYTES:
                raise AttachmentLimitError(
                    f"近 {self.WINDOW_SECONDS // 3600} 小时附件下载总量超过 "
                    f"{MAX_BATCH_ATTACH_BYTES // 1024 // 1024 // 1024}GB，已中止（请分批处理）")
            if bugid:
                used = self._bug_used.get(bugid, 0) + size
                self._bug_used[bugid] = used
                if used > MAX_BUG_ATTACH_BYTES:
                    raise AttachmentLimitError(
                        f"bugid={bugid} 附件总量超过 {MAX_BUG_ATTACH_BYTES // 1024 // 1024 // 1024}GB，已中止")


BUDGET = AttachmentBudget()


def begin_batch() -> None:
    """标记一个新批次开始（重置批次计数）。

    适用于"一次请求内部循环处理多个 bug"的批量端点（时间批量提取等）；
    诊断这类由前端逐 bug 发多个请求的场景没有服务端批次边界，靠滚动窗口兜底。
    """
    BUDGET.begin_batch()


def filter_large_entries(names, size_map: dict, limit: int = MAX_SINGLE_ENTRY_BYTES,
                         label: str = "压缩包"):
    """过滤掉超过单条目上限的条目（7z/rar 必须整条目落盘，超大条目会直接占满磁盘）

    :return: (保留的条目列表, 被跳过的条目列表)
    """
    kept, skipped = [], []
    for name in names or []:
        if (size_map.get(name) or 0) > limit:
            skipped.append(name)
        else:
            kept.append(name)
    if skipped:
        logger.warning("%s内 %d 个条目超过 %dMB，已跳过: %s",
                       label, len(skipped), limit // 1024 // 1024, skipped[:3])
    return kept, skipped


def ensure_disk_space(path: str, min_free: int = MIN_FREE_DISK_BYTES) -> None:
    """下载前检查磁盘可用空间，不足则抛 AttachmentLimitError"""
    target = path if os.path.isdir(path) else (os.path.dirname(path) or ".")
    try:
        free = shutil.disk_usage(target).free
    except OSError:
        return  # 拿不到磁盘信息时不阻断
    if free < min_free:
        raise AttachmentLimitError(
            f"磁盘可用空间不足（剩余 {free / 1024 / 1024 / 1024:.1f}GB "
            f"< 要求 {min_free / 1024 / 1024 / 1024:.0f}GB），已跳过附件下载")


def _cache_key(url: str, filename: str) -> str:
    """缓存键：附件 URL 在 Jira 中是稳定的（附件内容不可变），按 URL 去重即可"""
    digest = hashlib.sha1(url.encode("utf-8")).hexdigest()[:20]
    ext = os.path.splitext(filename or "")[1][:10]
    return f"{digest}{ext}"


def _cache_lookup(url: str, filename: str, dest_path: str) -> bool:
    """命中未过期缓存时复制到目标路径并返回 True"""
    if not url:
        return False
    cache_path = os.path.join(CACHE_DIR, _cache_key(url, filename))
    try:
        if not os.path.isfile(cache_path):
            return False
        if time.time() - os.path.getmtime(cache_path) > CACHE_TTL_SECONDS:
            return False
        os.makedirs(os.path.dirname(dest_path) or ".", exist_ok=True)
        shutil.copy2(cache_path, dest_path)
        logger.info("附件缓存命中: %s -> %s", os.path.basename(cache_path), os.path.basename(dest_path))
        return True
    except OSError as e:
        logger.warning("附件缓存读取失败（将重新下载）: %s", e)
        return False


def _cache_store(url: str, filename: str, src_path: str) -> None:
    """把下载好的附件写入缓存（失败不影响主流程）"""
    if not url:
        return
    try:
        os.makedirs(CACHE_DIR, exist_ok=True)
        cache_path = os.path.join(CACHE_DIR, _cache_key(url, filename))
        shutil.copy2(src_path, cache_path)
    except OSError as e:
        logger.warning("附件缓存写入失败（忽略）: %s", e)


def prune_cache(ttl_seconds: int = CACHE_TTL_SECONDS) -> int:
    """清理过期缓存 + 控制总容量，返回删除数量"""
    if not os.path.isdir(CACHE_DIR):
        return 0
    removed = 0
    now = time.time()
    alive = []
    for name in os.listdir(CACHE_DIR):
        path = os.path.join(CACHE_DIR, name)
        try:
            if not os.path.isfile(path):
                continue
            if now - os.path.getmtime(path) > ttl_seconds:
                os.remove(path)
                removed += 1
            else:
                alive.append((os.path.getmtime(path), os.path.getsize(path), path))
        except OSError:
            continue
    # 容量上限：按修改时间从旧到新删，直到回落到上限以内
    total = sum(size for _, size, _ in alive)
    if total > MAX_CACHE_BYTES:
        for _, size, path in sorted(alive):
            if total <= MAX_CACHE_BYTES:
                break
            try:
                os.remove(path)
                total -= size
                removed += 1
            except OSError:
                continue
    if removed:
        logger.info("已清理附件缓存 %d 个（当前占用 %.0fMB）",
                    removed, max(total, 0) / 1024 / 1024)
    return removed


_last_temp_clean = 0.0


def cleanup_stale_temp(root: str = None, hours: int = 24) -> int:
    """清理残留的临时目录（进程被强杀时 TemporaryDirectory 不会自动清理）

    只清理本项目临时目录下、名字以 _diag_/tmp 开头且超过 hours 的目录，1 小时内最多执行一次。
    """
    global _last_temp_clean
    now = time.time()
    if now - _last_temp_clean < _TEMP_CLEAN_INTERVAL:
        return 0
    _last_temp_clean = now
    import tempfile
    root = root or tempfile.gettempdir()
    if not os.path.isdir(root):
        return 0
    removed = 0
    for name in os.listdir(root):
        if not (name.startswith("tmp") or name.startswith("_diag_")):
            continue
        path = os.path.join(root, name)
        try:
            if os.path.isdir(path) and now - os.path.getmtime(path) > hours * 3600:
                shutil.rmtree(path, ignore_errors=True)
                removed += 1
        except OSError:
            continue
    if removed:
        logger.info("已清理残留临时目录 %d 个", removed)
    return removed


_last_prune = 0.0
_PRUNE_INTERVAL = 10 * 60  # 缓存清理间隔 10 分钟


def maintenance() -> None:
    """例行维护：清理过期缓存与残留临时目录（内部有节流，可放心频繁调用）"""
    global _last_prune
    now = time.time()
    if now - _last_prune > _PRUNE_INTERVAL:
        _last_prune = now
        prune_cache()
    cleanup_stale_temp()


def stream_download(url: str, headers: dict, dest_path: str, timeout=60,
                    bugid: str = "", max_bytes: int = MAX_ATTACHMENT_BYTES,
                    filename: str = "", use_cache: bool = True,
                    stop_event=None, deadline_seconds: int = 0):
    """流式下载到目标路径：体积上限 + 磁盘水位 + 预算记账 + 附件缓存

    :param stop_event: 可选的取消事件，置位时中止下载（抛 TimeoutError("用户停止")）
    :param deadline_seconds: 可选的下载总时长上限（秒），超时抛 TimeoutError
    :return: 实际写入字节数
    :raises AttachmentLimitError: 超过体积上限 / 预算 / 磁盘不足
    """
    import httpx

    filename = filename or os.path.basename(dest_path)
    maintenance()
    ensure_disk_space(dest_path)

    if use_cache and _cache_lookup(url, filename, dest_path):
        try:
            cached_size = os.path.getsize(dest_path)
        except OSError:
            cached_size = 0
        BUDGET.charge(cached_size, bugid)
        return cached_size

    os.makedirs(os.path.dirname(dest_path) or ".", exist_ok=True)
    written = 0
    started = time.time()
    try:
        with httpx.stream("GET", url, headers=headers, timeout=timeout,
                          verify=False, follow_redirects=True) as resp:
            resp.raise_for_status()
            with open(dest_path, "wb") as out:
                for chunk in resp.iter_bytes(chunk_size=1024 * 1024):
                    if stop_event is not None and stop_event.is_set():
                        raise TimeoutError("用户停止")
                    if deadline_seconds and (time.time() - started) > deadline_seconds:
                        raise TimeoutError(f"下载超时({deadline_seconds}s)")
                    written += len(chunk)
                    if written > max_bytes:
                        raise AttachmentLimitError(
                            f"附件超过 {max_bytes // 1024 // 1024}MB 上限"
                            f"（已下载 {written / 1024 / 1024:.1f}MB），已中止")
                    # 边下边记账：让单 bug/单批次预算能及时生效
                    BUDGET.charge(len(chunk), bugid)
                    out.write(chunk)
        if use_cache:
            _cache_store(url, filename, dest_path)
        return written
    except Exception:
        # 失败时删除半成品，避免占住磁盘
        try:
            if os.path.exists(dest_path):
                os.remove(dest_path)
        except OSError:
            pass
        raise
