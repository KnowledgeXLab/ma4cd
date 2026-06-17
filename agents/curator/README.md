# Curator Agent

**总馆长** — 在 **Session 维度**监控整条流水线的 ROI、产出率与盲区，决定是否继续飞轮、以及向 Commander/Scout/Miner 下达补搜指令。

## 在流水线中的位置

```
Miner → Inspector → Curator (盘点) ──→ 继续 / 熔断
                         │
                         ├── 战略盲区 (strategic_gaps)
                         └── 补搜指令 → Scout / Miner 下一轮
```

Curator **不直接爬网、不入库**；它读 Session 记忆做元认知判断，是 MA4CD 的**控制平面**。

## 职责

- 流式解析 `memory_data/sessions/<session_id>.json`，统计流量健康度
- 评估产出率、403/404 比例、是否触发熔断（`yield_status`）
- LLM 战略推演：根据已捕获资产标题发现学科链条盲区
- 输出 `next_directives` 与 `strategic_gaps`，供主流水线驱动补搜
- 与 Skill 联动：链条维度、门户种子 URL、熔断规则、补搜 prompt

## 目录结构

```text
curator/
├── agent.py              # 主入口 CuratorAgent（LangGraph）
├── nodes/
│   ├── flow_discovery_node.py    # Session 流量探勘
│   ├── output_synthesis_node.py  # 产出研判 + 熔断信号
│   └── strategic_node.py         # LLM 战略推演（async）
├── llms/                 # create_curator_llm
├── prompts/              # STRATEGIC_SYSTEM_PROMPT
└── state/curator_state.py
```

## 核心流程（LangGraph DAG）

```
flow_discovery → output_synthesis ──can_continue?──→ strategic_node → END
                              └── false ──→ END（熔断）
```

### flow_discovery_node

从 Session JSON 提取：请求数、403/404 特征、已入库资产标题列表。

### output_synthesis_node

计算 `yield_status`（`can_continue`、`stop_reason`），决定是否进入战略推演。

### strategic_node

调用 Curator LLM，输出 `strategic_gaps` 与 `next_directives`（给下游 Agent 的搜寻建议）。

## 输入与输出

| 方向 | 内容 |
|------|------|
| **输入** | `session_id`、`commander_intent` |
| **输出** | `CuratorState` 字典，含 `flow_metrics`、`yield_status`、`strategic_gaps`、`next_directives` |

## 与主流水线的协作

- `MA4CD_CURATOR_SCOUT_LOOP=1`（可在 `runtime_profile.yaml` 默认开启）时，Curator 盲区会触发 **Scout 补搜** + Miner 二轮深挖
- `utils/session_collab.py`：`build_curator_supplement_task()`、`curator_scout_loop_enabled()`
- `utils/curator_supplement.py`：补搜 query 种子、优先站点排序

## Skill 集成

| Rule 文件 | 加载器 | 用途 |
|-----------|--------|------|
| `curator_chain_model.yaml` | `utils/curator_skill.py` | 链条维度、熔断规则、`portal_seeds`、`max_rounds` |
| `curator_supplement.yaml` | `utils/curator_supplement.py` | 补搜优先站、gap query、`scout_prompt_append` |
| `runtime_profile.yaml` | `utils/runtime_profile.py` | 非覆盖式 env 默认（如开启 Curator 循环） |

## 环境变量

| 变量 | 说明 |
|------|------|
| `MA4CD_CURATOR_SCOUT_LOOP` | 是否启用 Curator→Scout 补搜闭环 |
| `MA4CD_CURATOR_MODEL` | 战略推演 LLM（若已配置） |
| `MA4CD_SKILL` | 领域 Skill |

## 独立运行

```bash
python agents/curator/agent.py
```

模块内 `__main__` 提供异步测试入口；需存在对应 Session JSON 才有真实指标。

主流水线调用：

```python
final_state = await curator.evaluate_session(session_id, commander_intent)
```

## 相关代码

- 飞轮逻辑：`main_workflow.py` 中 Curator 阶段与多轮循环
- Session 协作：`utils/session_collab.py`
- Skill 框架：`skills/README.md`
