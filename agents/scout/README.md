# Scout Agent

**侦察兵** — 根据 Commander 的 `task_config` 做广域 OSINT 搜索，产出**种子 URL 列表**。

## 在流水线中的位置

```
Commander (task_config) → Scout (种子 URL) → Miner (深度挖掘)
                              ↑
                    Curator 补搜时可二次调用
```

Scout 负责**横向铺开**：从开放网络快速锁定值得深挖的站点入口，不做页面级 DFS。

## 职责

- 将宏观任务扩展为多条搜索 query（`PlanningNode`）
- 通过 **Tavily API** 执行真实搜索（`tavily_only=True`，不接受伪造 URL）
- 黑名单过滤（对接 `DataMemoryCenter`）
- 按 `relevance_score` 裁剪种子 URL 数量（`max_seed_urls`）
- 支持 HITL / Curator 语义补丁（`semantic_patch`）

## 目录结构

```text
scout/
├── agent.py              # 主入口 ScoutAgent
├── run.py                # CLI 独立测试
├── nodes/
│   ├── planning_node.py  # LLM 查询扩展
│   ├── search_node.py    # 执行 Tavily 搜索
│   └── base_node.py
├── tools/
│   └── web_search.py     # ScoutWebSearchTool
├── llms/
├── prompts/
└── state/
```

## 核心流程

1. **规划**：`PlanningNode` 根据任务 + Commander 配置生成 query 列表  
   - LLM 不可用时，回退 `scout_plan_from_commander_queries()`
2. **搜索**：`SearchNode` / `ScoutWebSearchTool` 逐条 query 调 Tavily
3. **过滤**：仅保留 `source=tavily` 的结果，剔除黑名单域名
4. **裁剪**：超过 `max_seed_urls` 时按相关性保留 Top-N

## 输入与输出

| 方向 | 内容 |
|------|------|
| **输入** | `task`（任务描述）、`config`（含 `scout_config` / `search_queries`）、`session_id` |
| **输出** | `List[str]` — HTTP(S) 种子 URL |

## Skill 集成

读取 `skills/<id>/rules/scout_search.yaml`（`utils/scout_skill.py`）：

| 字段 | 用途 |
|------|------|
| `prompt_append` | 注入 Scout 规划 Prompt |
| `site_preferences` | 站点偏好 / 域名加权 |
| `tier_distribution` | L1–L4 查询 tier 配比 |
| `noise_rewrite_rules` | 噪声 query 改写规则 |
| `language_strategy` | 多语言搜索策略 |

`search_discovery.yaml` 中的 `authoritative_sites` 可与 Scout 站点偏好合并（Miner L2/L3 也会用到）。

## 环境变量

| 变量 | 说明 |
|------|------|
| `TAVILY_API_KEY` | Tavily 搜索 API（必需） |
| `MA4CD_SCOUT_MODEL` | 规划阶段 LLM |
| `MA4CD_SKILL` | 领域 Skill |

`scout_config` 内常见键：`max_concurrent`、`results_per_query`、`max_seed_urls`、`search_depth`。

## 独立运行

```bash
python agents/scout/run.py "基因组开放数据库" --session-id test-001
python agents/scout/run.py "蛋白质数据集" --json --limit 10
```

需配置 `OPENAI_API_KEY`、`OPENAI_BASE_URL` 与 `TAVILY_API_KEY`。

## 相关代码

- 主流水线 Scout 阶段：`main_workflow.py`
- Curator 补搜：`utils/session_collab.py`、`utils/curator_supplement.py`
- Prompt 契约：`utils/prompt_contracts.py` → `scout_max_seed_urls`、`scout_results_per_query`
