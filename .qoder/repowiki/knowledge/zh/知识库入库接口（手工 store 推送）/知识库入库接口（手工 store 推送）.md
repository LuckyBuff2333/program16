---
kind: external_dependency
name: 知识库入库接口（手工 store 推送）
slug: knowledge-base-api
category: external_dependency
category_hints:
    - sdk_real_api
    - client_constraint
scope:
    - '**'
source_files:
    - config/config.yaml
    - src/clients/kb_client.py
---

### 知识库接口
- 角色：接收开发手工执行的 `store <bugid>` 命令，将对应 bug 的分析文档推送到团队知识库；工具不做自动拦截，是否入库完全由执行人判断。
- 集成点：`config/config.yaml` 的 `knowledge_base_api` 段配置 `url`、`bugid_field`、`content_field`；默认 `mock: true`，接入真实库时关闭 mock 并填写目标地址。
- 稳定用法：按 bugid 查找该 bug 最新生成的分析文档（`docs/YYYY-MM-DD/bugid.md`），将其内容作为 `content` 字段提交到知识库接口。
- 约束：此接口仅在 `store` 子命令下被调用，analyze/retry/report 流程不会触发写入。