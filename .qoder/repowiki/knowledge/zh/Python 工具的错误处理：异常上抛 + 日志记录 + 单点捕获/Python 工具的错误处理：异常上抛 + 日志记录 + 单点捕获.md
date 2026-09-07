---
kind: error_handling
name: Python 工具的错误处理：异常上抛 + 日志记录 + 单点捕获
category: error_handling
scope:
    - '**'
source_files:
    - src/clients/base.py
    - src/pipeline.py
    - src/main.py
    - src/core/doc_generator.py
    - src/db.py
---

## 1. 整体方案

该仓库是一个 Python CLI 工具（`bug-doc-tool`），没有引入第三方错误框架。错误处理采用“自底向上”的三层模式：
- **底层/IO 层**：在 `src/clients/base.py`、`src/db.py`、`src/core/doc_generator.py` 等模块内部用 `try/except Exception` 捕获具体异常，通过 `setup_logger` 获取的 logger 记录结构化错误日志，然后选择重新抛出或返回默认值。
- **流程编排层**：`src/pipeline.py` 对单个 bugid 的分析调用使用 `try/except Exception` 包裹，失败时不中断整个批处理，而是将错误信息写入结果字典并继续处理下一个 bugid。
- **CLI 入口层**：`src/main.py` 的 `main()` 函数在最外层 `try/except Exception` 中统一捕获所有未处理异常，记录到日志并通过 `sys.exit(1)` 退出，同时把错误消息打印到 stderr。

代码中没有自定义异常类型、没有错误码枚举、没有 `panic/recover`（Python 无此概念）、也没有中间件机制——这是一个典型的脚本型工具的轻量级错误处理风格。

## 2. 关键文件与职责

| 文件 | 错误处理职责 |
|---|---|
| `src/clients/base.py` | HTTP 客户端重试与失败上报；每次请求失败记录 `logger.error`，重试耗尽后统一 `raise RuntimeError(...)` |
| `src/pipeline.py` | 批量分析容错：单个 bugid 失败仅记录日志并追加 `status="failed"` 的结果条目，不影响其他 bugid |
| `src/main.py` | CLI 顶层兜底：捕获所有子命令异常，输出到 stderr 并以 exit code 1 终止 |
| `src/core/doc_generator.py` | 文件 I/O 语义化错误：找不到文档时 `raise FileNotFoundError(...)`，附带明确提示 |
| `src/db.py` | 数据库查询失败时 `logger.error` 后 `raise` 原异常；空记录场景用 `logger.warning` 返回默认值 |
| `src/config.py`（被多处 import） | 提供 `setup_logger(name)` 构造带命名空间的 logger，是统一的日志出口 |

## 3. 架构约定与设计决策

- **异常上抛策略**：业务层（如 `doc_generator.find_latest_document`、`main._parse_trigger_times`）直接 raise Python 内置异常（`FileNotFoundError`、`ValueError`），由上层决定如何处理；基础设施层（HTTP、DB）先记日志再 raise，保证可观测性。
- **批量容错**：`pipeline.run_pipeline` 显式声明“单个 bug 失败不中断整体流程”，这是本项目的核心约束——分析流水线必须尽可能产出部分成功的 CSV 报表。
- **重试模型**：仅在 HTTP 客户端层实现固定次数重试（`DEFAULT_RETRIES = 3`），其他层不自行重试；失败后由调用方决定是否 retry（CLI 提供 `retry` 子命令供人工触发）。
- **日志即错误载体**：所有异常路径都通过 `logger.error("...", e)` 记录，包含上下文（如 `bugid=`、URL、attempt 序号），便于定位；人类可读的错误消息通过 `print(..., file=sys.stderr)` 或 CSV 的 `error_msg` 字段暴露给调用者。
- **无全局错误处理器**：没有注册 `sys.excepthook`、没有全局 try/except 包装每个函数，错误传播依赖 Python 默认的异常冒泡。

## 4. 观察到的约定与约束

- **HTTP 层**：`http_post` / `http_get` 必须捕获 `Exception` 并记录 `logger.error`，重试耗尽后必须 `raise RuntimeError`，禁止吞掉异常。
- **Pipeline 层**：`_analyze_single` 的调用必须被 `try/except Exception` 包裹，失败结果必须包含 `status="failed"` 和截断后的 `error_msg`（`str(e)[:1000]`）。
- **CLI 层**：`main()` 是唯一允许 `sys.exit(1)` 的位置；子命令本身不应直接调用 `sys.exit`。
- **文件 I/O**：缺失资源应 `raise FileNotFoundError` 并附带说明（如“请先执行 analyze 生成”），而不是返回 None 或空字符串。
- **参数校验**：非法参数（如 `--trigger-time` 格式错误）应 `raise ValueError` 并给出期望格式提示。
- **数据库层**：只读查询失败时先 `logger.error` 再 `raise`，空记录用 `logger.warning` 并返回默认结构体，避免上层误判为异常。

## 5. 不适用项

- 不存在自定义异常类层次结构（如 `class XxxError(Exception): ...`）。
- 不存在错误码常量或错误响应对象。
- 不存在基于装饰器的中间件式错误拦截。
- 不存在 `try/finally` 资源清理之外的恢复逻辑。

总体而言，该仓库的错误处理是“日志优先、异常上抛、单点兜底”的实用主义风格，适合小型 CLI 工具，但缺乏细粒度的错误分类与可恢复性设计。