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

from src.config import PROJECT_ROOT, load_config, setup_logger

logger = setup_logger("attachment_guard")

# ── 限额 ──
MAX_ATTACHMENT_BYTES = 500 * 1024 * 1024        # 单个附件下载硬上限 500MB
MAX_RAR_VOLUME_BYTES = 2 * 1024 * 1024 * 1024   # rar 分卷总量上限 2GB
MAX_BUG_ATTACH_BYTES = 3 * 1024 * 1024 * 1024   # 单个 bug 的附件总预算 3GB
MIN_FREE_DISK_BYTES = 5 * 1024 * 1024 * 1024    # 下载前要求的最小可用磁盘 5GB
MAX_SINGLE_ENTRY_BYTES = 2 * 1024 * 1024 * 1024  # 解压单个条目上限 2GB（7z/rar 需整条目落盘）
MAX_MEDIA_BYTES = 1024 * 1024 * 1024            # 视频/图片附件上限 1GB（录屏常超 500MB，单独放宽）

# 附件与视频缓存：data/media_cache/（专用目录，不与其他程序共享）
CACHE_DIR = os.path.join(PROJECT_ROOT, "data", "media_cache", "attachments")
VIDEO_CACHE_DIR = os.path.join(PROJECT_ROOT, "data", "media_cache", "videos")
PROJECT_TEMP_DIR = os.path.join(PROJECT_ROOT, "data", "media_cache")  # 项目专用临时目录，不影响系统 /tmp
CACHE_TTL_SECONDS = 7 * 24 * 60 * 60            # 缓存有效期 7 天，超过自动删除
MAX_CACHE_BYTES = 5 * 1024 * 1024 * 1024        # 缓存目录总量上限 5GB（超出按最旧删除）
_CLEANUP_INTERVAL = 7 * 24 * 60 * 60            # 维护清理间隔 7 天，仅在启动时执行
_CLEANUP_TS_FILE = os.path.join(PROJECT_ROOT, "data", ".last_maintenance_ts")


class AttachmentLimitError(RuntimeError):
    """附件超出限额（体积/预算/磁盘空间）"""


class AttachmentBudget:
    """按 bug 的附件体积预算（线程安全）

    - begin_batch()：新的批量任务开始时重置
    - begin_bug(bugid)：开始处理某个 bug 时重置该 bug 计数
    - charge(n, bugid)：下载到 n 字节后记账，单 bug 超预算抛 AttachmentLimitError
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._bug_used = {}
        self._batch_used = 0

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

    def charge(self, size: int, bugid: str = "", ignore_limit: bool = False):
        size = max(0, int(size or 0))
        with self._lock:
            self._batch_used += size
            if ignore_limit:
                if bugid:
                    self._bug_used[bugid] = self._bug_used.get(bugid, 0) + size
                return
            if bugid:
                used = self._bug_used.get(bugid, 0) + size
                self._bug_used[bugid] = used
                if used > MAX_BUG_ATTACH_BYTES:
                    raise AttachmentLimitError(
                        f"bugid={bugid} 附件总量超过 {MAX_BUG_ATTACH_BYTES // 1024 // 1024 // 1024}GB，已中止")


BUDGET = AttachmentBudget()


def begin_batch() -> None:
    """标记一个新批次开始（重置批次计数）。

    适用于"一次请求内部循环处理多个 bug"的批量端点（时间批量提取等）。
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


def _read_last_maintenance_ts() -> float:
    """读取上次维护时间戳"""
    try:
        if os.path.isfile(_CLEANUP_TS_FILE):
            return float(open(_CLEANUP_TS_FILE).read().strip())
    except (OSError, ValueError):
        pass
    return 0.0


def _write_last_maintenance_ts() -> None:
    """写入当前维护时间戳"""
    try:
        os.makedirs(os.path.dirname(_CLEANUP_TS_FILE), exist_ok=True)
        with open(_CLEANUP_TS_FILE, "w") as f:
            f.write(str(time.time()))
    except OSError:
        pass


def cleanup_stale_temp(hours: int = 24) -> int:
    """清理项目专用临时目录中超过 hours 的残留目录

    仅清理 PROJECT_TEMP_DIR（data/_temp/），不触碰系统 /tmp 或其他程序的文件。
    """
    if not os.path.isdir(PROJECT_TEMP_DIR):
        return 0
    now = time.time()
    removed = 0
    for name in os.listdir(PROJECT_TEMP_DIR):
        path = os.path.join(PROJECT_TEMP_DIR, name)
        try:
            if os.path.isdir(path) and now - os.path.getmtime(path) > hours * 3600:
                shutil.rmtree(path, ignore_errors=True)
                removed += 1
        except OSError:
            continue
    if removed:
        logger.info("已清理项目临时目录 %d 个残留目录", removed)
    return removed


def maintenance() -> None:
    """启动时维护：清理过期缓存与残留临时目录。

    仅在启动时执行一次，每 7 天触发一次（通过时间戳文件记录上次执行时间）。
    距上次清理不足 7 天则跳过。
    """
    now = time.time()
    last_ts = _read_last_maintenance_ts()
    if now - last_ts < _CLEANUP_INTERVAL:
        logger.info("距上次维护不足 %d 天，跳过清理", _CLEANUP_INTERVAL // 86400)
        return
    _write_last_maintenance_ts()
    prune_cache()
    cleanup_stale_temp()


_DOWNLOAD_SEM = None
_DOWNLOAD_SEM_LOCK = threading.Lock()


def _get_download_sem():
    """全局下载并发信号量（默认 3，可通过 params.diag_download_concurrency 或 params.download_concurrency 配置）"""
    global _DOWNLOAD_SEM
    if _DOWNLOAD_SEM is None:
        with _DOWNLOAD_SEM_LOCK:
            if _DOWNLOAD_SEM is None:
                n = 3
                try:
                    params = load_config().get("params", {})
                    # 优先读取 diag_download_concurrency，回退到 download_concurrency（保持 config.yaml 向后兼容）
                    n = max(1, int(params.get("diag_download_concurrency", params.get("download_concurrency", 3))))
                except Exception:
                    pass
                _DOWNLOAD_SEM = threading.Semaphore(n)
    return _DOWNLOAD_SEM


def stream_download(url: str, headers: dict, dest_path: str, timeout=60,
                    bugid: str = "", max_bytes: int = MAX_ATTACHMENT_BYTES,
                    filename: str = "", use_cache: bool = True,
                    stop_event=None, deadline_seconds: int = 0,
                    ignore_limit: bool = False):
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
        BUDGET.charge(cached_size, bugid, ignore_limit=ignore_limit)
        return cached_size

    os.makedirs(os.path.dirname(dest_path) or ".", exist_ok=True)
    written = 0
    started = time.time()
    _sem = _get_download_sem()
    try:
        with _sem:
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
                        BUDGET.charge(len(chunk), bugid, ignore_limit=ignore_limit)
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
