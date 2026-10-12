import sys, os, json, logging
sys.path.insert(0, '.')
logging.basicConfig(level=logging.INFO, format='%(levelname)s %(name)s %(message)s')
from src.web.server import _troubleshoot_diagnose_impl
result = _troubleshoot_diagnose_impl(
    bugid='VCU-548720',
    err_msg='时间过滤后日志为空（0行），无法进行分析。请检查问题时间（2026-09-17 14:59:37）是否正确',
    problem_time='2026-09-17 14:59:37',
    done_time='2026-09-29 21:06:53',
    force=True
)
print()
print('=== RESULT ===')
print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
