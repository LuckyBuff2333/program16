---
kind: external_dependency
name: Jira REST API 客户端（报错原因与评论提取）
slug: jira-rest-api
category: external_dependency
category_hints:
    - sdk_real_api
    - auth_protocol
scope:
    - '**'
source_files:
    - config/config.yaml
    - src/clients/jira_client.py
---

### Jira REST API
- 角色：通过 bugid 调用 Jira REST API 拉取 issue 的报错原因与评论区评论，评论经 Agent 过滤后作为「分析步骤」参与相似性比对。
- 集成点：`config/config.yaml` 的 `jira_api` 段配置 `url`、`bugid_field`、认证字段 `username`/`token`；默认 `mock: true` 使用内置样例数据，接入真实环境需改为 `false` 并填写地址与凭据。
- 稳定用法：以 bugid 为入参查询 issue，返回结构中的报错原因与 comments 列表；评论需经 `core/filter.py` 的 `_agent_filter` 过滤后再用于步骤比对。
- 注意：认证字段在配置中预留但未强制校验，对接真实 Jira 时需确保 token/用户名正确。