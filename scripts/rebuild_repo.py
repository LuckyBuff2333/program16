"""重建干净的 git 仓库（无历史大文件）"""
import subprocess
import os

os.chdir(r"d:\program16")

def run(cmd, **kwargs):
    r = subprocess.run(cmd, capture_output=True, text=True, cwd=r"d:\program16", **kwargs)
    if r.stdout: print(r.stdout.strip()[:500])
    if r.stderr: print(r.stderr.strip()[:500])
    return r.returncode

# 1. 创建孤儿分支
print("=== Creating orphan branch ===")
run(["git", "checkout", "--orphan", "clean-master"])

# 2. 添加当前所有文件
print("=== Adding files ===")
run(["git", "add", "-A"])
# 排除含密钥的配置文件
run(["git", "rm", "--cached", "config/config.yaml"])

# 3. 提交
print("=== Committing ===")
run(["git", "commit", "-m", "initial commit: AI log analysis tool"])

# 4. 删除旧 master，重命名
print("=== Renaming branch ===")
run(["git", "branch", "-D", "master"])
run(["git", "branch", "-m", "clean-master", "master"])

# 5. 验证
print("=== Verification ===")
run(["git", "log", "--oneline"])
run(["git", "count-objects", "-vH"])
