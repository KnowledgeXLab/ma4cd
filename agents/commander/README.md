# Commander Agent

**指挥官** — 把用户的自然语言需求转化为可执行的 `task_config`（搜索计划、评分标准、Scout 运行参数）。

## 在流水线中的位置

```
用户任务 → Commander → Scout → Miner → Inspector → Curator → Report
              ↑___________________________（Curator 补搜 / HITL 修正可回流）
```

Commander 是整条 MA4CD 链路的**规划起点**：不直接爬网，只产出结构化任务配置，供 Scout 与后续 Agent 消费。

## 职责

- 解析用户意图，生成 JSON 格式的 `task_config`
- 输出 `search_queries`（带 tier / language 等元数据）、`scoring_rubric`、`scout_config`
- 支持 **HITL 人类修正**：`apply_amendment()` 可注入 `system_prompt_append`
- 与 **Skill** 联动：注入领域战术指引与默认 Scout 参数（不硬编码领域词汇）

## 目录结构

```text
commander/
├── agent.py              # 主入口 CommanderAgent
├── llms/
│   └── commander_llm.py  #（可选）专用 LLM 封装
├── nodes/
│   ├── planning_node.py
│   └── reflection_node.py
├── prompts/
│   └── planning_prompts.py   # 系统身份与规划 Prompt
└── state/
    └── commander_state.py
```

## 核心流程

1. 组装 System Prompt（身份 + Skill 战术块 + 人类修正）
2. 调用 LLM，经 `invoke_json_contract` 约束输出 JSON
3. `normalize_commander_task_config()` 规范化字段
4. `apply_commander_skill_defaults()` 合并 Skill 中的 `scout_config` / rubric 默认值
5. 失败时最多重试 3 次

## 输入与输出

| 方向 | 内容 |
|------|------|
| **输入** | `user_request`（字符串）、可选 `history_reports`、`session_id` |
| **输出** | `task_config` 字典，典型字段：`core_intent`、`search_queries`、`scoring_rubric`、`scout_config` |

## Skill 集成

激活 `MA4CD_SKILL` 后，读取 `skills/<id>/rules/commander_task.yaml`：

| 字段 | 用途 |
|------|------|
| `core_intent_template` | 核心意图模板 |
| `planning_guidance` | 注入规划 Prompt 的战术指引 |
| `sub_discipline_hints` | 子领域拆解参考 |
| `seed_query_examples` | 种子查询示例 |
| `scout_config` | Scout 并发、深度、每 query 结果数等 |

加载逻辑：`utils/commander_skill.py`

## 环境变量

| 变量 | 说明 |
|------|------|
| `MA4CD_COMMANDER_MODEL` | 规划模型（默认 `deepseek-chat`） |
| `OPENAI_API_KEY` / `OPENAI_BASE_URL` | LLM 接口 |
| `MA4CD_SKILL` | 领域 Skill ID |

## 独立运行

通常通过主流水线调用：

```bash
python main_workflow.py --skill protein-research "寻找蛋白质开放数据"
```

Commander 在 `MA4CDPipeline` 初始化时自动执行，无单独 `run.py`。

## 相关代码

- 主流水线：`main_workflow.py`
- Prompt 契约：`utils/prompt_contracts.py` → `normalize_commander_task_config`
- Skill 框架：`skills/README.md`
