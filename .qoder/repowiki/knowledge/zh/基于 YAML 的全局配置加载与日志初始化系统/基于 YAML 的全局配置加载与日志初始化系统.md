---
kind: configuration_system
name: 基于 YAML 的全局配置加载与日志初始化系统
category: configuration_system
scope:
    - '**'
source_files:
    - config/config.yaml
    - src/config.py
    - src/db.py
    - src/main.py
    - src/clients/jira_client.py
    - src/clients/kb_client.py
    - src/core/similarity.py
    - src/core/doc_generator.py
    - src/core/report.py
---

## 1. 使用的系统与方案

本项目采用 **纯 Python + PyYAML** 的轻量级配置方案：所有运行时参数集中存放在 `config/config.yaml`，通过 `src/config.py` 中的单例式全局缓存模块在进程内统一加载、复用。没有引入 `pydantic-settings`、`dynaconf`、`.env` 或环境变量覆盖等外部依赖。

## 2. 关键文件

- `config/config.yaml`：唯一的外部配置源，包含数据库、AI 接口、Jira、知识库、相似性阈值、审计抽样、输出路径等全部配置项。
- `src/config.py`：配置加载器（`load_config`）、输出目录解析器（`get_path`）与日志初始化器（`setup_logger`）。
- `src/db.py`：使用 `PROJECT_ROOT` 和 `load_config()` 解析 SQLite 相对路径并建表。
- `src/main.py`：CLI 入口，启动时调用 `db.init_db()` 完成数据库初始化。
- 各业务模块（`clients/jira_client.py`、`clients/kb_client.py`、`core/similarity.py`、`core/doc_generator.py`、`core/report.py`、`core/filter.py` 等）均通过 `from src.config import load_config, setup_logger` 消费配置。

## 3. 架构与设计约定

### 3.1 配置加载流程
- `PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))` 指向仓库根目录。
- 默认配置文件路径固定为 `config/config.yaml`。
- `_CONFIG` 为模块级全局变量，`load_config()` 首次加载后缓存到该变量，后续调用直接返回缓存，避免重复 IO。
- 支持传入自定义 `config_path` 用于测试场景覆盖。

### 3.2 配置结构分层
`config.yaml` 按子系统分块组织：
- `database.url` / `database.table_name`：SQLite 默认 `sqlite:///data/app.db`，注释给出 MySQL 连接串示例；表名由 `table_name` 控制。
- `ai_log_api.*`：mock 开关、URL、超时、字段映射（`bugid_field`、`trigger_time_field`）。
- `jira_api.*`：mock 开关、URL、超时、认证（`username`、`token`）。
- `knowledge_base_api.*`：mock 开关、URL、超时、字段映射。
- `similarity.threshold`（0~1）、`root_cause_hit_ratio`：相似度判定阈值。
- `audit.sample_count`、`audited_file`、`report_file`、`kb_table`、各列名映射：控制随机抽查行为。
- `output.doc_dir`、`report_dir`、`log_dir`：相对项目根的相对路径。

### 3.3 路径解析约定
- `get_path(key)` 从 `cfg["output"][key]` 取相对路径，拼接 `PROJECT_ROOT` 转为绝对路径，并用 `os.makedirs(..., exist_ok=True)` 确保目录存在。
- `db.init_db()` 对 `sqlite:///` 开头的 URL 做特殊处理：若为相对路径则基于 `PROJECT_ROOT` 解析为绝对路径后再创建 engine。

### 3.4 日志体系
- `setup_logger(name)` 在每个模块中独立调用，每个 logger 名称对应一个命名空间（如 `main`、`http`、`jira`、`kb`、`doc_gen`、`filter`、`report`、`similarity`、`db`）。
- 每个 logger 同时输出到控制台（StreamHandler）和按日期归档的文件（`logs/app_YYYY-MM-DD.log`），格式为 `%(asctime)s [%(levelname)s] %(name)s - %(message)s`。
- 已添加过 handler 的 logger 会直接返回，避免重复追加。

## 4. 约定与约束

- **单一配置源**：所有运行期配置必须写在 `config/config.yaml`，代码中不硬编码 URL、阈值、路径等可变值。
- **Mock 开关模式**：对外部 API（AI、Jira、知识库）统一提供 `mock: true/false` 开关，开发调试默认开启 mock。
- **相对路径约定**：`output.*` 下的路径一律相对于项目根；SQLite 数据文件放在 `data/`，文档在 `docs/`，报表在 `reports/`，日志在 `logs/`。
- **配置即 schema**：`db.py` 中 SQLAlchemy 模型 `BugRecord.__tablename__` 直接从 `cfg["database"]["table_name"]` 读取，新增/修改表名必须在配置中同步。
- **审计表可配**：`audit.kb_table` 及 `bugid_column`、`trigger_time_column`、`root_cause_column`、`process_column` 允许对接不同知识库表结构，无需改代码。
- **无环境变量覆盖**：当前实现未读取任何环境变量，也未支持 `.env` 文件；如需环境隔离需自行扩展 `load_config`。
- **进程内单例**：`_CONFIG` 是全局字典，同一进程中多次导入共享同一份配置；测试中可通过传入 `config_path` 注入不同配置。

## 5. 使用方式

- CLI 命令（`python -m src.main analyze|retry|store|report|audit`）启动时自动加载配置。
- 各子模块通过 `load_config()["jira_api"]`、`load_config()["similarity"]`、`load_config()["audit"]` 等键访问对应配置段。
- 输出路径通过 `get_path("doc_dir"|"report_dir"|"log_dir")` 获取并确保目录存在。
- 日志通过 `setup_logger("模块名")` 获取已初始化的 logger 实例。