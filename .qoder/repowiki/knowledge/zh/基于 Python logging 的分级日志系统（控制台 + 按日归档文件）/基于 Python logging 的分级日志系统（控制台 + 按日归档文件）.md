---
kind: logging_system
name: 基于 Python logging 的分级日志系统（控制台 + 按日归档文件）
category: logging_system
scope:
    - '**'
source_files:
    - src/config.py
    - src/main.py
    - src/pipeline.py
    - src/clients/base.py
    - src/core/doc_generator.py
    - src/db.py
---

## 1. 使用的系统与框架

本项目使用 Python 标准库 `logging` 模块作为唯一日志框架，未引入第三方日志库（如 loguru、structlog）。所有业务与工具代码通过统一的 `setup_logger(name)` 工厂函数获取 logger，实现集中式配置。

## 2. 核心文件与位置

- **日志初始化与配置**：`src/config.py` 中的 `setup_logger(name: str = "bug_doc_tool") -> logging.Logger`，负责创建 logger、设置级别、注册 handler。
- **各模块 logger 实例**：
  - CLI 入口：`src/main.py` → `logger = setup_logger("main")`
  - 流水线编排：`src/pipeline.py` → `setup_logger("pipeline")`
  - 文档生成：`src/core/doc_generator.py` → `setup_logger("doc_gen")`
  - 过滤/相似性/报告：`src/core/filter.py`、`src/core/similarity.py`、`src/core/report.py` 分别以 `filter`、`similarity`、`report` 为命名空间。
  - 数据库访问：`src/db.py` → `setup_logger("db")`
  - HTTP 客户端基类：`src/clients/base.py` → `setup_logger("http")`
  - Jira/Knowledge Base 客户端：`src/clients/jira_client.py`、`src/clients/kb_client.py` 分别使用 `jira`、`kb` 命名空间。
- **日志输出目录**：由 `config.yaml` 中 `output.log_dir` 指定，默认位于项目根下的 `logs/` 目录；文件命名为 `app_YYYY-MM-DD.log`。

## 3. 架构与约定

### 3.1 Logger 生命周期管理
`setup_logger` 内部对已存在的 logger 做了幂等保护：若 `logger.handlers` 非空则直接返回已有实例，避免重复添加 handler。每个模块在模块顶层调用一次 `setup_logger(模块名)`，形成“一模块一 logger”的命名空间隔离。

### 3.2 输出双通道
- **控制台输出**：`StreamHandler`，格式为 `%(asctime)s [%(levelname)s] %(name)s - %(message)s`，便于开发调试时直接在终端看到结构化日志。
- **文件输出**：`FileHandler`，写入 `logs/app_YYYY-MM-DD.log`，文件名按运行日期自动切换，实现按日归档。编码固定为 `utf-8`。

### 3.3 日志级别策略
全局默认级别为 `logging.INFO`。错误路径统一使用 `logger.error(...)` 记录，例如：
- `base.py` 中 HTTP 请求失败重试时记录 `POST/GET ... 第 N 次请求失败`。
- `main.py` 中命令执行异常捕获后记录 `命令执行失败: <exception>`。
成功流程使用 `logger.info(...)` 记录关键节点，如文档生成完成、步骤提取数量等。

### 3.4 结构化字段约定
当前日志采用 `logging.Formatter` 提供的标准字段：`asctime`、`levelname`、`name`、`message`。`name` 即传入 `setup_logger` 的模块级命名空间（如 `http`、`jira`、`doc_gen`），用于区分来源模块。未使用自定义字段或 JSON 结构化日志。

### 3.5 与 stdout/stderr 的关系
CLI 的 `print()` 仅用于向用户展示简短结果（如报表路径、命令完成提示），这些输出走 `stdout` 而非日志系统；真正的错误信息通过 `sys.stderr` 打印并配合 `logger.error` 落盘，保证可观测性与可追溯性分离。

## 4. 约定与约束

- **必须通过 `setup_logger(name)` 获取 logger**：所有模块均从 `src.config` 导入并使用该工厂，禁止直接 `logging.getLogger()` 裸用。
- **logger 命名遵循“功能域”粒度**：每个子模块/子包使用独立名称（`main`、`pipeline`、`doc_gen`、`filter`、`similarity`、`report`、`db`、`http`、`jira`、`kb`），便于按来源筛选日志。
- **日志级别统一为 INFO**：未在配置中暴露级别开关，所有 logger 固定 `setLevel(logging.INFO)`。
- **文件日志按自然日滚动**：每次启动都写入 `app_YYYY-MM-DD.log`，不会自动清理旧日志文件（依赖外部轮转策略）。
- **幂等初始化**：重复调用 `setup_logger` 不会重复注册 handler，适合模块级单例模式。
- **Windows 控制台编码兼容**：`main.py` 在 Windows 平台将 stdout/stderr 重设为 UTF-8，确保中文日志不乱码。

## 5. 观察到的局限

- 无按大小滚动的日志切割（如 `RotatingFileHandler`），长期运行可能产生大文件。
- 无日志级别动态调整能力（无法运行时切换 DEBUG/INFO/WARNING）。
- 日志格式为纯文本，未采用 JSON 结构化输出，不利于机器解析与聚合分析。
- 未集成集中式日志收集（如 ELK、Loki），仅落盘到本地 `logs/` 目录。