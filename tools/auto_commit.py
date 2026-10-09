#!/usr/bin/env python3
"""文件变更自动提交工具

监听项目文件变更，自动执行 git add + commit。
支持防抖（合并短时间内多次修改）、忽略规则、提交消息模板。

用法:
    python tools/auto_commit.py                    # 默认监控 src/ config/ data/
    python tools/auto_commit.py --push              # 提交后自动推送
    python tools/auto_commit.py --interval 30        # 防抖间隔 30 秒（默认 15 秒）
    python tools/auto_commit.py --watch src,config   # 自定义监控目录
"""
import argparse
import os
import re
import subprocess
import sys
import time
import threading
from datetime import datetime
from pathlib import Path

try:
    from watchdog.observers import Observer
    from watchdog.events import FileSystemEventHandler
except ImportError:
    print("❌ 需要安装 watchdog: pip install watchdog")
    sys.exit(1)

# git status porcelain 行解析：XY + 空格分隔 + PATH
_STATUS_RE = re.compile(r'^(.{2}) ?(.+)$')


def _parse_status_line(line: str):
    """解析 git status --porcelain 行，返回 (status, filepath)"""
    m = _STATUS_RE.match(line)
    if not m:
        return None, None
    status = m.group(1).strip()
    path_part = m.group(2)
    # 重命名时格式为 "ORIG -> NEW"，取新路径
    if ' -> ' in path_part:
        path_part = path_part.split(' -> ', 1)[1]
    return status, path_part.strip()


# ──── 配置 ────
PROJECT_ROOT = Path(__file__).resolve().parent.parent
GIT_AUTHOR = "2063795530 <2063795530@qq.com>"
DEFAULT_WATCH_DIRS = ["src", "config", "data", "timestudy", "reports", "scripts"]
DEFAULT_DEBOUNCE_SEC = 15  # 防抖间隔（秒），合并该窗口内的所有变更为一次提交

# 忽略的文件/目录模式（正则）
IGNORE_PATTERNS = [
    r'\.git/',
    r'__pycache__/',
    r'\.pyc$',
    r'\.idea/',
    r'\.qoder/',
    r'\.pytest_cache/',
    r'allure-results/',
    r'allure-report/',
    r'node_modules/',
    r'\.venv/',
    r'logs/',
    r'dist/',
    r'build/',
    r'\.egg-info/',
    # auto_commit.py 仅在 watch 模式下忽略（防止递归提交）
    # 大文件 / 临时文件
    r'\.(zip|rar|7z|tar|gz|exe|bin|mp4|avi|mov)$',
    r'\.swp$',
    r'~$',
]
_ignore_re = [re.compile(p, re.IGNORECASE) for p in IGNORE_PATTERNS]


def _should_ignore(path: str) -> bool:
    """判断路径是否应被忽略"""
    rel = os.path.relpath(path, PROJECT_ROOT)
    return any(r.search(rel) for r in _ignore_re)


class ChangeCollector(FileSystemEventHandler):
    """收集文件变更事件，支持防抖"""

    def __init__(self, debounce_sec: int = DEFAULT_DEBOUNCE_SEC):
        super().__init__()
        self.debounce_sec = debounce_sec
        self._pending: dict[str, str] = {}  # path → event_type
        self._lock = threading.Lock()
        self._timer: threading.Timer | None = None

    def _schedule_commit(self):
        """重置防抖计时器"""
        if self._timer:
            self._timer.cancel()
        self._timer = threading.Timer(self.debounce_sec, self._do_commit)
        self._timer.daemon = True
        self._timer.start()

    def on_any_event(self, event):
        if event.is_directory:
            return
        path = event.src_path
        if _should_ignore(path):
            return
        # watch 模式下忽略自身，防止递归提交
        if os.path.abspath(path) == os.path.abspath(__file__):
            return
        rel = os.path.relpath(path, PROJECT_ROOT)
        with self._lock:
            self._pending[rel] = event.event_type
            self._schedule_commit()

    def _do_commit(self):
        """执行 git add + commit"""
        with self._lock:
            if not self._pending:
                return
            changes = dict(self._pending)
            self._pending.clear()

        # 分类变更
        created = [p for p, t in changes.items() if t == "created"]
        modified = [p for p, t in changes.items() if t == "modified"]
        deleted = [p for p, t in changes.items() if t == "deleted"]
        moved = [p for p, t in changes.items() if t == "moved"]
        other = [p for p, t in changes.items() if t not in ("created", "modified", "deleted", "moved")]

        # 过滤掉不存在的文件（可能是临时文件已被删除）
        existing = [p for p in changes if os.path.exists(os.path.join(PROJECT_ROOT, p))]
        if not existing and not deleted:
            return

        # 构建提交消息
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        total = len(changes)
        parts = []
        if created:
            parts.append(f"+{len(created)}新建")
        if modified:
            parts.append(f"~{len(modified)}修改")
        if deleted:
            parts.append(f"-{len(deleted)}删除")
        if moved:
            parts.append(f"→{len(moved)}移动")
        summary = " ".join(parts) if parts else f"{total}变更"

        # 提取主要修改的文件名（最多显示3个）
        main_files = list(changes.keys())[:3]
        file_list = ", ".join(Path(f).name for f in main_files)
        if len(changes) > 3:
            file_list += f" 等{total}个文件"

        commit_msg = f"auto: {summary} ({file_list}) [{now}]"

        # 执行 git 命令
        try:
            # git add 所有变更文件
            add_files = [p for p in changes if not _should_ignore(os.path.join(PROJECT_ROOT, p))]
            if not add_files and not deleted:
                return

            cwd = str(PROJECT_ROOT)

            # 添加存在的文件
            if existing:
                subprocess.run(
                    ["git", "add", "--"] + [os.path.join(cwd, f) for f in existing],
                    cwd=cwd, capture_output=True, timeout=10
                )

            # 添加已删除的文件
            if deleted:
                for f in deleted:
                    full = os.path.join(cwd, f)
                    if not os.path.exists(full):
                        subprocess.run(
                            ["git", "rm", "--cached", "--", full],
                            cwd=cwd, capture_output=True, timeout=10
                        )

            # 检查是否有暂存内容
            result = subprocess.run(
                ["git", "diff", "--cached", "--name-only"],
                cwd=cwd, capture_output=True, text=True, timeout=10
            )
            if not result.stdout.strip():
                return  # 无暂存变更

            # 提交
            result = subprocess.run(
                ["git", "commit", "--author", GIT_AUTHOR, "-m", commit_msg],
                cwd=cwd, capture_output=True, text=True, timeout=15
            )
            if result.returncode == 0:
                print(f"  ✅ {commit_msg}")
                # 如果启用了推送，异步执行
                if _auto_push:
                    threading.Thread(target=_do_push, daemon=True).start()
            else:
                print(f"  ❌ 提交失败: {result.stderr.strip()[:200]}")

        except subprocess.TimeoutExpired:
            print("  ⏰ git 命令超时")
        except Exception as e:
            print(f"  ❌ 提交异常: {e}")


# ──── 推送 ────
_auto_push = False


def _do_push():
    """异步推送到远程"""
    try:
        result = subprocess.run(
            ["git", "push"],
            cwd=str(PROJECT_ROOT), capture_output=True, text=True, timeout=60
        )
        if result.returncode == 0:
            print("  📤 推送成功")
        else:
            print(f"  ⚠️ 推送失败: {result.stderr.strip()[:150]}")
    except Exception as e:
        print(f"  ⚠️ 推送异常: {e}")


# ──── 入口 ────
def main():
    global _auto_push
    parser = argparse.ArgumentParser(description="文件变更自动提交工具")
    parser.add_argument("--push", action="store_true", help="提交后自动推送到远程")
    parser.add_argument("--interval", type=int, default=DEFAULT_DEBOUNCE_SEC,
                        help=f"防抖间隔秒数（默认 {DEFAULT_DEBOUNCE_SEC}）")
    parser.add_argument("--watch", type=str, default=",".join(DEFAULT_WATCH_DIRS),
                        help="监控目录，逗号分隔（默认 src,config,data,timestudy,reports,scripts）")
    parser.add_argument("--once", action="store_true", help="立即提交当前变更然后退出（不监听）")
    args = parser.parse_args()

    _auto_push = args.push
    watch_dirs = [d.strip() for d in args.watch.split(",") if d.strip()]

    # 验证目录
    valid_dirs = []
    for d in watch_dirs:
        full = os.path.join(PROJECT_ROOT, d)
        if os.path.isdir(full):
            valid_dirs.append(full)
        else:
            print(f"  ⚠️ 目录不存在，跳过: {d}")

    if not valid_dirs:
        print("❌ 无有效监控目录")
        sys.exit(1)

    # 确保 git 可用
    try:
        subprocess.run(["git", "status"], cwd=str(PROJECT_ROOT),
                        capture_output=True, timeout=5)
    except Exception:
        print("❌ 当前目录不是 git 仓库或 git 不可用")
        sys.exit(1)

    if args.once:
        # 一次性提交模式
        print("📦 执行一次性提交...")
        collector = ChangeCollector(debounce_sec=0)
        # 收集当前未暂存的变更
        result = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=str(PROJECT_ROOT), capture_output=True, text=True, timeout=10
        )
        for line in result.stdout.strip().split("\n"):
            if not line:
                continue
            status, filepath = _parse_status_line(line)
            if not filepath:
                continue
            full = os.path.join(PROJECT_ROOT, filepath)
            if _should_ignore(full):
                continue
            event_map = {"M": "modified", "A": "created", "D": "deleted",
                         "R": "moved", "?": "created"}
            collector._pending[filepath] = event_map.get(status, "modified")
        if collector._pending:
            collector._do_commit()
            if _auto_push:
                _do_push()
        else:
            print("  ℹ️ 无变更")
        return

    # 持续监听模式
    collector = ChangeCollector(debounce_sec=args.interval)
    observer = Observer()
    for d in valid_dirs:
        observer.schedule(collector, d, recursive=True)

    observer.start()
    dir_names = ", ".join(os.path.basename(d) for d in valid_dirs)
    print(f"👀 自动提交已启动 | 监控: {dir_names} | 防抖: {args.interval}s | 推送: {'是' if _auto_push else '否'}")
    print(f"   按 Ctrl+C 停止")

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n⏹️  停止监听...")
        observer.stop()
        # 提交剩余的变更
        if collector._pending:
            print("📦 提交剩余变更...")
            collector._do_commit()
    observer.join()
    print("👋 已退出")


if __name__ == "__main__":
    main()
