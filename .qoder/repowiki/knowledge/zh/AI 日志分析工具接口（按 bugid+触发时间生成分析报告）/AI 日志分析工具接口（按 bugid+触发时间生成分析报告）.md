---
kind: external_dependency
name: AI 日志分析工具接口（按 bugid+触发时间生成分析报告）
slug: ai-log-analysis-api
category: external_dependency
category_hints:
    - sdk_real_api
scope:
    - '**'
source_files:
    - config/config.yaml
    - src/clients/base.py
---

### AI 日志分析工具接口
- 角色：根据传入的 bugid（可选 trigger_time）调用外部 AI 日志分析服务，获取分析报告内容并据此生成 `docs/YYYY-MM-DD/bugid.md`。
- 集成点：`config/config.yaml` 的 `ai_log_api` 段配置 `url`、`timeout`、`bugid_field`、`trigger_time_field`；默认 `mock: true`，接入真实服务时关闭 mock 并填入实际地址与字段映射。
- 稳定用法：以 bugid + 触发时间为入参，返回报告文本；失败不中断整批，单条失败记录进结论表格供人工处理。
- 注意：触发时间用于精准定位日志窗口，是保证分析准确性的关键入参。