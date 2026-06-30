# MA4CD

MA4CD 是一个面向数据资产发现的多智能体流水线项目，用来从开放网络中识别、深挖、审计并沉淀高价值数据资源。

当前代码主链路由以下角色组成：

- `Commander`：把用户需求拆成搜索与挖掘计划
- `Scout`：执行广域侦察，锁定候选站点
- `Miner`：对候选站点做深度挖掘，识别资产
- `Inspector`：对挖掘结果做审计、去重、入库
- `Curator`：站在 session 维度监控 ROI、盲区和熔断条件
- `ReportGenerator`：生成运行报告

## 目录概览

```text
ma4cd/
├── agents/                # 多智能体实现
│   ├── commander/
│   ├── scout/
│   ├── miner/
│   ├── inspector/
│   └── curator/
├── data_memory_center/    # ChromaDB 分层存储与黑名单
├── memory/                # 部分策略/程序性记忆
├── memory_data/           # session、reflection、DNA 等运行记忆
├── reports/               # 历史报告
├── output/                # 输出产物
├── logs/                  # 运行日志
├── main_workflow.py       # 推荐入口
```

## 核心流程

推荐从 [main_workflow.py]理解项目：

1. `Commander` 为用户需求生成 `task_config`
2. `Scout` 产出候选 URL
3. `Miner` 并发深挖 URL，并结合工作记忆避免重复踩坑
4. `Inspector` 审计结果并写入 `DataMemoryCenter`
5. `Curator` 依据 session 数据判断是否继续深挖
6. `ReportGenerator` 输出最终报告

## 环境要求

- Python 3.10+
- 建议使用 Linux/macOS
- 需要联网访问目标站点与 OpenAI 兼容接口
- 首次使用 Playwright 时需要额外安装浏览器

## 安装

```bash
python -m venv .venv
source .venv/bin/activate
pip install -U pip
pip install -r requirements.txt
python -m playwright install chromium
cp .env.example .env   # 填入 API Key 与 Base URL
```

如果你的目标站点有较强反爬限制，也建议安装：

```bash
pip install playwright-stealth
```

## 环境变量

项目里的多个 LLM 客户端默认读取以下环境变量：

```bash
export OPENAI_API_KEY="your-api-key"
export OPENAI_BASE_URL="https://your-openai-compatible-endpoint"
export MA4CD_COMMANDER_MODEL="deepseek-chat"
export MA4CD_SCOUT_MODEL="deepseek-chat"
export MA4CD_MINER_SMALL_MODEL="deepseek-chat"
export MA4CD_MINER_BIG_MODEL="deepseek-chat"
export MA4CD_INSPECTOR_MODEL="deepseek-chat"
export MA4CD_CURATOR_MODEL="deepseek-chat"
```

兼容写法：

```bash
export MA4CD_LLM_API_KEY="your-api-key"
export MA4CD_LLM_BASE_URL="https://your-openai-compatible-endpoint"
```

说明：

- `OPENAI_API_KEY`：必需
- `OPENAI_BASE_URL`：对本项目也基本视为必需，因为代码明显按“OpenAI 兼容中转站”方式编写
- 现在代码同时兼容 `OPENAI_*` 和 `MA4CD_LLM_*` 两套变量名
- 当前默认推荐模型：全链路优先使用 `deepseek-chat`
- 当前默认降本策略：`Miner` 的 `small_model` 和 `big_model` 都默认走 `deepseek-chat`
- 如果后续需要给少数高难推理分支加一点能力，可以只把 `MA4CD_MINER_BIG_MODEL` 单独切成 `deepseek-reasoner`

## 运行方式

### 1. 交互式主流程，以下都是例子

```bash
python main_workflow.py "寻找一下蛋白质的研究数据"
```

这会启动完整链路，并在每轮结束后允许你给各个 Agent 提交人工修正反馈。

推荐先复制 `.env.example` 为 `.env` 并填好密钥。若 `OPENAI_BASE_URL` 未配置，而当前供应商又不支持 `deepseek-chat` 这种模型名，启动时会出现模型不存在或路由失败。

### 2. 单 Agent 联调

```bash
# Scout 广域侦察
python agents/scout/run.py "蛋白质研究开放数据"

# Miner 单 URL 深挖（预设用例 1 = 世界银行）
python agents/miner/run.py --case 1
python agents/miner/run.py --url "https://data.worldbank.org/" --query "世界银行开放数据"
```

### 5. Redis 记忆后端（可选）

默认 `MA4CD_MEMORY_BACKEND=file` 使用本地 JSON/SQLite。多 worker 去重可启用 Redis：

```bash
# 需本地 Redis: docker run -d -p 6379:6379 redis:7
export MA4CD_MEMORY_BACKEND=redis
export MA4CD_REDIS_URL=redis://localhost:6379/0
python main_workflow.py "寻找蛋白质研究数据"
```

接入范围：`Coordination`（URL 去重/锁）→ `Session` → `Working`（轨迹）→ 关闭时归档至 SQLite。

## 存储与产物

以下目录为**运行时产物**，已在 `.gitignore` 中忽略，首次运行会自动创建：

- `data_memory_center/`：L1/L2/L3/L4 分层 ChromaDB（`l1_db` … `l4_db` 等子目录）
- `memory_data/sessions/`：session 级运行记录
- `memory_data/reflections/`：反思结果
- `reports/`：各轮或各任务报告
- `output/`：额外输出目录
- `logs/`：运行日志

清理本地历史产物（保留目录骨架）：

```bash
find reports -mindepth 1 -delete
rm -rf memory_data/sessions/* memory_data/reflections/* memory_data/chroma_db
rm -rf data_memory_center/{l1,l2,l3,l4}_db blacklist_db inspector_internal_db miner_memory
rm -rf logs/* output/*
```

## 依赖说明

`requirements.txt` 已补充当前代码中明确使用到的主要第三方依赖，包括：

- `openai`
- `chromadb`
- `langgraph`
- `pydantic`
- `loguru`
- `aiohttp`
- `requests`
- `beautifulsoup4`
- `playwright`
- `html2text`
- `tqdm`
- `pandas`

## Smoke Test

不发起网络请求，仅验证核心模块可导入：

```bash
python agents/scout/test_scout.py
python -c "from tests.test_smoke_imports import test_core_agents_importable, test_data_memory_center_importable; test_core_agents_importable(); test_data_memory_center_importable(); print('ok')"
python tests/memory/test_redis_backend_integration.py
```

若已安装 pytest，也可运行：

```bash
python -m pytest tests/test_smoke_imports.py -q
```

## 当前已知限制

- 实际跑通全链路仍取决于 API 端点、Playwright 浏览器环境与目标网站可访问性
- 若使用 DeepSeek 或其他 OpenAI 兼容供应商，务必同时配置 `OPENAI_BASE_URL`；仅设置 `OPENAI_API_KEY` 往往不够
- `.env` 含密钥，请勿提交到版本库（已加入 `.gitignore`）

## 推荐阅读顺序

如果你准备继续维护这个项目，建议按下面顺序看代码：

1. [main_workflow.py](main_workflow.py)
2. [agents/miner/agent.py](agents/miner/agent.py)
3. [agents/inspector/agent.py](agents/inspector/agent.py)
4. [data_memory_center/manager.py](data_memory_center/manager.py)
5. `agents/miner/nodes/` 与 `agents/miner/tools/`
