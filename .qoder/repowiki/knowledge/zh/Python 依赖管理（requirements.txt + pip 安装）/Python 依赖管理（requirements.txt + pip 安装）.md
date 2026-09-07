---
kind: dependency_management
name: Python 依赖管理（requirements.txt + pip 安装）
category: dependency_management
scope:
    - '**'
source_files:
    - requirements.txt
    - README.md
    - src/clients/base.py
    - src/core/similarity.py
    - src/core/report.py
    - src/config.py
    - src/db.py
    - tests/conftest.py
---

## 1. 使用的系统/方案

本项目采用 Python 生态中最基础的依赖管理方式：通过根目录的 `requirements.txt` 声明第三方包，使用 `pip install -r requirements.txt` 进行安装。没有使用 `pyproject.toml`、`setup.py`、`Pipfile`、`poetry.lock`、`conda.yaml` 等更现代的锁定或打包工具，也没有 vendoring（`vendor/` 目录）、私有 PyPI 源配置或 Docker 镜像中的依赖层隔离。

## 2. 关键文件与包

- **依赖声明文件**：`requirements.txt`（根目录），共 8 个第三方依赖，全部使用 `>=` 宽松版本约束：
  - `requests>=2.31.0`：HTTP 客户端，被 `src/clients/base.py` 用于 `http_get` / `http_post`
  - `SQLAlchemy>=2.0.0`：ORM，被 `src/db.py` 连接 SQLite/MySQL 数据库
  - `pandas>=2.1.0`：报表生成，被 `src/core/report.py` 输出 CSV 结论表
  - `scikit-learn>=1.3.0`：TF-IDF 相似性计算，被 `src/core/similarity.py` 调用 `TfidfVectorizer`
  - `PyYAML>=6.0`：配置文件解析，被 `src/config.py` 读取 `config/config.yaml`
  - `jieba>=0.42.1`：中文分词，被 `src/core/similarity.py` 参与文本相似度
  - `pytest>=7.4.0`：测试框架，被 `tests/` 下所有用例及根 `conftest.py` 使用
  - `allure-pytest>=2.13.0`：测试报告插件，配合 `--alluredir=allure-results` 生成 Allure 结果

- **运行入口**：`README.md` 中“环境准备”章节明确指示 `pip install -r requirements.txt` 作为唯一安装步骤。

## 3. 架构与约定

- **集中式单文件声明**：所有依赖集中在根级 `requirements.txt`，项目内无子模块各自维护依赖清单的模式。
- **最小化依赖集**：仅引入业务必需的网络请求、数据库、数据处理、NLP、测试四类库，未引入 web 框架、异步框架等额外组件。
- **运行时导入与声明一致**：通过扫描源码可确认每个 `requirements.txt` 中的包都有对应 import 点（如 `sklearn.feature_extraction.text.TfidfVectorizer`、`yaml`、`pandas`、`requests`、`sqlalchemy`、`pytest`、`allure_pytest`），不存在未使用的幽灵依赖。
- **无锁文件**：仓库未提交 `requirements.lock`、`pipenv.lock`、`poetry.lock` 等锁定文件，依赖版本以 `>=` 形式向上开放，由安装时解析最新兼容版本。
- **无虚拟环境管理**：仓库未包含 `.venv/`、`venv/`、`env/` 等虚拟环境目录；依赖安装由使用者在本地环境中执行。
- **无私有源/认证**：`requirements.txt` 中未出现 `-i`、`--index-url`、`--extra-index-url`、`--trusted-host` 等 pip 参数，也未见 `.piprc`、`pip.conf` 等配置文件，默认从 PyPI 官方源拉取。

## 4. 约定与约束

- **版本约束风格**：统一使用 `>=X.Y.Z` 的最低版本约束，不固定上限，允许 pip 在安装时选择满足条件的最新版本。
- **安装命令约定**：遵循 README 中的约定，通过 `pip install -r requirements.txt` 一次性安装全部依赖，包括开发依赖（pytest、allure-pytest）与生产依赖混放在同一文件中。
- **测试依赖与生产依赖未分离**：pytest 和 allure-pytest 与业务依赖并列声明，未使用 `requirements-dev.txt` 或 pyproject 的 optional dependency 分组。
- **外部接口通过 mock 降级**：`config/config.yaml` 中的 `ai_log_api`、`jira_api`、`knowledge_base_api` 支持设置 `mock: true`，使项目在无真实网络依赖的情况下仍可运行测试与演示流程。
- **数据持久化使用内置 SQLite**：默认 `database.url` 指向根目录 `data/app.db`，无需额外数据库服务即可运行，降低部署依赖面。

## 5. 风险与建议（基于现状观察）

- 缺少 lock 文件可能导致不同环境间依赖版本漂移，建议后续引入 `pip-tools`（`requirements.in` + `pip-compile`）或 `poetry` 以固化依赖树。
- 开发与生产依赖混合，建议在拆分 `requirements-dev.txt` 或使用现代打包工具实现依赖分组。
- 未使用虚拟环境隔离，建议结合 `python -m venv .venv` 与 `.gitignore` 排除虚拟环境目录。