# Miner Agent

**矿工** — 对 Scout 给出的种子 URL 做**深度拓扑挖掘**（DFS），高召回产出候选数据资产链接。

## 在流水线中的位置

```
Scout (种子 URL) → Miner (候选资产) → Inspector (审计入库)
                        ↑
              Inspector 监督 / Curator 指令 / 进化引擎反馈
```

Miner 专注**纵向深挖**：页面浏览、链接提取、结构判定、轨迹反思；**语义分级与入库由 Inspector 负责**。

## 职责

- 并发 DFS 遍历站点，提取下载/API/FTP 等数据容器线索
- `StructureNode` 判定页面拓扑（DIRECTORY / DATASET / …）
- `ExtractNode` 抽取 L3/L4 候选
- `ReflectionNode` 防死循环、低产出反思
- `MinerReportNode` 生成本轮挖掘 Markdown 报告
- **统一记忆**：工作记忆、会话记忆、Chroma 向量库、Redis 后端（可配置）
- **进化引擎**：根据成功/失败样本调整 URL 剪枝与路径效率（`MemoryBasedEvolutionEngine`）

## 目录结构

```text
miner/
├── agent.py              # 主入口 UniversalMinerAgent
├── run.py                # 单 URL CLI 测试
├── nodes/
│   ├── structure_node.py # 页面拓扑与下钻决策
│   ├── extract_node.py   # 资产线索提取
│   ├── reflection_node.py
│   └── report_node.py
├── tools/
│   ├── browse_page.py    # Playwright 页面抓取
│   ├── search_engine.py  # 站内 / 权威站搜索
│   ├── l2_analyzer.py    # L2 门户分析
│   ├── l3_detector.py / l4_miner.py
│   ├── url_classifier.py / blacklist_manager.py
│   └── metadata_enhancer.py
├── memory/
│   ├── managers/memory_manager.py
│   ├── storage/          # working / session / persistent
│   └── backends/         # Redis 等
├── evolution/
│   └── miner_evolution_engine.py
├── llms/miner_llm.py     # 大小模型路由（小脑/大脑）
├── prompts/prompt.py
└── state/miner_state.py
```

## 核心流程（单 URL）

1. 启动 session，绑定 `WorkingMemory` 轨迹
2. Playwright 打开页面 → 提取链接与正文
3. `StructureNode`（LLM）决定继续下钻或输出候选
4. `ExtractNode` 结构化资产字段
5. `ReflectionNode` 检测循环 / 低价值分支
6. 候选经排序、去重后输出给 Inspector
7. 可选触发进化学习（带批次/域名冷却）

## 输入与输出

| 方向 | 内容 |
|------|------|
| **输入** | `urls: List[str]`、`user_query`、`session_id`、可选 `runtime_instruction` |
| **输出** | 候选资产列表（含 `url`、`title`、`level` 提示、`domain` 等），写入 session 与向量记忆 |

## Skill 集成

| Rule 文件 | 加载器 | 用途 |
|-----------|--------|------|
| `miner_signals.yaml` | `utils/miner_signals.py` | 领域关键词、负向词、搜索模板 |
| `miner_heuristics.yaml` | `utils/miner_heuristics.py` | URL 剪枝、进化门控 |
| `miner_evolve_domains.yaml` | `skill_loader` | 可信 / 噪声域名 |
| `miner_prompts.yaml` | `utils/miner_prompts.py` | 各 Node Prompt 追加块 |
| `search_discovery.yaml` | `utils/search_discovery.py` | 权威站定向搜索、L2/L3 查询模板 |

引擎代码**不含**领域站点列表；全部在 Skill YAML 中配置。

## 环境变量

| 变量 | 说明 |
|------|------|
| `MA4CD_MINER_SMALL_MODEL` | 轻量结构判定模型 |
| `MA4CD_MINER_BIG_MODEL` | 复杂提取 / 反思模型 |
| `MA4CD_MINER_CONCURRENCY` | 并发深挖数 |
| `MA4CD_POSITIVE_EVOLVE_*` | 正向进化触发阈值 |
| `MA4CD_SKILL` | 领域 Skill |

需安装 Playwright Chromium：`python -m playwright install chromium`

## 独立运行

```bash
python agents/miner/run.py --url https://www.ebi.ac.uk --query "组学数据库"
python agents/miner/run.py --case 1
```

## 相关代码

- 主流水线 Miner 阶段：`main_workflow.py`
- 数据记忆中心：`data_memory_center/`
- Inspector 监督回传：Miner 读取 `inspector` 的 domain + reason_code 统计
