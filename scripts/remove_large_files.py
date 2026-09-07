"""从 git 追踪中移除大文件和非必要文件"""
import subprocess
import os

os.chdir(r"d:\program16")

# 要移除的目录和文件
paths = [
    "build/",
    "dist/",
    "tools/models/",
    "tools/jdk-17.0.20+8-jre/",
    "tools/jre17.zip",
    "allure-results/",
    "allure-report/",
    "logs/",
    "data/",
    "__pycache__/",
    "src/web/__pycache__/",
    ".idea/",
    ".pytest_cache/",
    "src/__pycache__/",
    "src/clients/__pycache__/",
    "src/core/__pycache__/",
    "tests/__pycache__/",
]

for path in paths:
    if path.endswith("/"):
        result = subprocess.run(
            ["git", "rm", "-r", "--cached", path],
            capture_output=True, text=True, cwd=r"d:\program16"
        )
    else:
        result = subprocess.run(
            ["git", "rm", "--cached", path],
            capture_output=True, text=True, cwd=r"d:\program16"
        )
    if result.returncode == 0:
        lines = result.stdout.strip().split("\n")
        print(f"[OK] {path}: {len(lines)} files removed")
    else:
        # 可能不在 git 中或不存在
        pass

# 验证
result = subprocess.run(
    ["git", "ls-files"],
    capture_output=True, text=True, cwd=r"d:\program16"
)
count = len([l for l in result.stdout.strip().split("\n") if l])
print(f"\nRemaining tracked files: {count}")
