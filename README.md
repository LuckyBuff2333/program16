# Bug 文档沉淀工具

基于 AI 日志分析工具的 Bug 文档沉淀与故障分析闭环工具，实现「bugid 去重 → AI 分析生成文档 → Jira 报错原因/评论比对 → 每日结论报表 → 知识库手工入库」的完整流程。

**重要约定：工具运行结果不写入数据库，只按规范生成文档与每日 CSV 结论表格；是否通过接口推入知识库由开发手工执行 store 命令决定，该步骤不做自动化。**

## 流程说明

1. **bugid 去重**：上游传入的 bugid 与数据库 `bug_records` 表只读比对，已存在的过滤，新的进入分析（表数据由外部维护，工具不写入）
2. **AI 日志分析**：bugid（含可选触发时间）传入 AI 日志分析工具接口，提取返回的报告内容生成文档（`docs/日期/bugid.md`）
3. **结果比对**：调用 Jira RESTAPI 提取报错原因与评论区评论（评论经 Agent 过滤提取日志分析步骤），与文档做根因与步骤双重相似性比对，结论写入每日 CSV 报表（`reports/日期_daily.csv`，同日多次运行按 bugid 覆盖合并）
4. **知识入库（纯手工）**：开发确认分析正确后手工执行 `store` 命令，将对应 bug 的分析文档推入知识库接口；失败的由开发手工执行 `retry` 重新分析，直至正确后自行决定入库
5. **随机抽查复核（audit）**：从数据库已入库表随机抽取 30 个 bugid（自动排除历史已抽查过的），带触发时间重新调用 AI 日志分析工具，新结果与库中已存的根因分析/分析流程字段做相似性对比，对比结果生成人工审核表格；每次抽查的 bugid 均记录在 `reports/audited_bugids.csv` 中供追溯

## 环境准备

```bash
pip install -r requirements.txt
```

## 配置说明

编辑 `config/config.yaml`：

- `database.url`：数据库连接串，默认 SQLite 开箱即用，可切换 MySQL
- `ai_log_api` / `jira_api` / `knowledge_base_api`：三个外部接口配置，`mock: true` 时使用内置样例数据，接入真实接口时改为 `false` 并填写 `url` 与入参字段名映射
- `similarity.threshold`：步骤相似性判定阈值；`root_cause_hit_ratio`：根因关键词命中比例阈值
- `audit`：随机抽查配置，`sample_count` 默认抽样数（30）；`kb_table` 及各字段名映射对接真实库时按实际表结构修改

## 使用方式

```bash
# 分析 bugid 列表（步骤1~3，--trigger-time 可选，可多次指定）
# 结果只生成文档与 CSV 结论报表，不写入数据库
python -m src.main analyze BUG-1001 BUG-1002 --trigger-time "BUG-1001=2026-08-12 10:00:00"

# 失败 bug 重新分析（开发手工触发，直至正确），结论报表按 bugid 覆盖更新
python -m src.main retry BUG-1001

# 开发确认分析正确后，手工将分析文档推入知识库（是否入库自行判断，无自动拦截）
python -m src.main store BUG-1001

# 查看当日结论报表路径（默认当天）
python -m src.main report --date 2026-08-12

# 随机抽查：从数据库抽 30 个已入库 bugid 重新分析，与库存储字段对比生成人工审核表格
# 已抽查过的 bugid 自动排除（记录在 reports/audited_bugids.csv），--count 可调整抽样数
python -m src.main audit
python -m src.main audit --count 20

# 启动前端可视化页面（默认端口 8060，自动打开浏览器）
python -m src.main web
python -m src.main web --port 8080
```

## 前端页面（python -m src.main web）

基于 Vue 3 + Element Plus + Flask 的可视化页面，顶部切换两个页面：

**线上流程页面**（三个页签）：

- **流程可视化**：端到端流程图（去重 → AI 分析 → Jira 比对 → 结论报表 → 手工入库 + 抽查复核分支）、今日统计卡片、执行分析/重试/入库/抽查操作面板、今日结论报表
- **接口设置**：AI 日志分析工具、Jira RESTAPI、知识库入库三个接口的 Mock 开关、地址、超时与字段映射，以及比对阈值/抽查参数，保存后写回 config/config.yaml 立即生效
- **数据看板**：按日期查询每日结论报表、抽查审核表格、已抽查记录

**流程功能测试页面**（左侧工具栏 3 项）：

1. **AI 日志分析与结论文档生成**：输入 bugid 单点调用 AI 分析接口，展示文档路径、根因结论、分析步骤与完整报告
2. **评论提取与对比**：展示 Jira 原始评论、过滤后提取步骤、报错原因，以及与文档的根因/步骤双重对比得分与结论
3. **数据库随机抽查**：执行抽样复核并展示审核表格与已抽查记录

## 测试与 Allure 报告

```bash
# 运行测试并生成 Allure 结果
python -m pytest tests --alluredir=allure-results

# 临时服务方式查看报告（需安装 allure 命令行工具，新终端生效）
allure serve allure-results

# 或生成静态报告到 allure-report/ 目录，直接打开 index.html 即可
allure generate allure-results -o allure-report --clean
```

> 本机 Allure CLI 已部署在 `tools/allure-2.45.0`，依赖同目录 `tools/jdk-17.0.20+8-jre`（用户环境变量 JAVA_HOME 与 Path 已配置，已打开的终端需重启后生效）。若终端无法识别 `allure` 命令，可直接使用项目根目录的启动器：`.\allure-serve.bat`（临时服务）或 `.\allure-serve.bat generate`（静态报告），无需环境变量。

## 目录结构

```
config/config.yaml     全局配置
src/main.py            CLI 入口（analyze/retry/store/report/audit/web）
src/pipeline.py        主流程编排（结果不写库，只出文档与结论报表）
src/db.py              数据库层（bugid 只读去重、抽查候选池与库存储字段只读查询）
src/clients/           外部接口客户端（AI 分析、Jira、知识库，支持 mock）
src/core/              核心处理（评论过滤、相似性比对、文档生成、报表、随机抽查复核）
src/web/               前端可视化页面（Flask API + Vue3/Element Plus 单页）
tests/                 pytest 测试用例
docs/                  运行期生成的分析文档（按日期分文件夹）
reports/               每日结论报表、抽查审核表格 audit_comparison.csv、已抽查记录 audited_bugids.csv
logs/                  运行日志
```
