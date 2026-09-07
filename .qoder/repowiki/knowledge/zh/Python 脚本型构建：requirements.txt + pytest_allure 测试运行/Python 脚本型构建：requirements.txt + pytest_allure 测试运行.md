---
kind: build_system
name: Python 脚本型构建：requirements.txt + pytest/allure 测试运行
category: build_system
scope:
    - '**'
source_files:
    - requirements.txt
    - README.md
    - conftest.py
    - tests/conftest.py
    - config/config.yaml
---

## 1. 使用的系统/方法

本项目是一个纯 Python 工具，**没有 Makefile、Dockerfile、CI 流水线或打包脚本**。构建与运行完全依赖 Python 生态的原生命令：
- 依赖安装：`pip install -r requirements.txt`
- 程序入口：`python -m src.main <command>`（analyze / retry / store / report / audit）
- 测试执行：`python -m pytest tests --alluredir=allure-results`
- Allure 报告查看：`allure serve allure-results`

所有构建、测试、运行步骤均通过 README.md 中的命令行片段直接描述，未封装为独立脚本。

## 2. 关键文件

- `requirements.txt`：声明全部运行时与测试依赖（requests、SQLAlchemy、pandas、scikit-learn、PyYAML、jieba、pytest、allure-pytest），是唯一的依赖清单。
- `README.md`：唯一文档化的“构建/运行”说明，包含环境准备、配置编辑、CLI 用法、测试与 Allure 报告命令。
- `conftest.py`（根目录）：在测试前将项目根加入 `sys.path`，使 `tests` 能直接 `import src.*`，是测试运行的前置约定。
- `tests/conftest.py`：测试夹具，配合 Pytest 提供共享 fixture。
- `config/config.yaml`：运行时配置（数据库 URL、AI/Jira/知识库 API、相似性阈值、抽查参数等），由 CLI 读取。

## 3. 架构与约定

- **无包管理/打包层**：项目不是可分发的 Python 包（无 `setup.py`、`pyproject.toml`、`MANIFEST.in`），而是以 `src/` 作为可导入模块的脚本式工程。
- **单入口 CLI**：所有功能通过 `src/main.py` 暴露子命令，构建产物就是 Python 源码本身，无需编译或生成二进制。
- **测试即验证**：测试套件基于 pytest + allure-pytest，测试结果输出到 `allure-results/` 目录，由 Allure 命令行渲染报告；没有独立的 lint、类型检查或覆盖率阶段。
- **配置驱动**：外部接口地址、数据库连接串、阈值等均从 `config/config.yaml` 读取，支持 mock 模式切换，便于本地测试与真实环境复用同一份代码。

## 4. 约定与约束

- 依赖版本使用 `>=` 宽松约束（如 `pytest>=7.4.0`），未锁定精确版本，也未提供 `Pipfile`/`poetry.lock` 等锁文件。
- 运行前必须执行 `pip install -r requirements.txt`，否则无法导入依赖。
- 测试必须从仓库根目录执行 `python -m pytest tests ...`，因为根 `conftest.py` 会修改 `sys.path`；在其他目录执行可能找不到 `src` 包。
- 测试报告输出路径固定为 `allure-results`，需通过 `--alluredir=allure-results` 指定，再由 `allure serve` 查看。
- 不存在自动化发布、容器化或 CI 集成——README 明确标注知识入库为“纯手工”，整个工具链保持最小化脚本形态。