# Inspector Agent

**质检员** — 对 Miner 产出的候选链接做**质量审计、去重、分级入库**，是数据进入 `DataMemoryCenter` 的守门人。

## 在流水线中的位置

```
Miner (候选资产) → Inspector (审计) → DataMemoryCenter (ChromaDB 分层存储)
                         ↓
                   拒绝桶统计 / Miner 监督回传 / 运行报告
```

Inspector 承担**语义裁判**：判断链接是否为真实数据容器、应归入 L1–L4 哪一层、是否应拉黑或重挖。

## 职责

- 批量审计 Miner 输出（默认 batch_size=50，带 tqdm 进度）
- **质量评分**：规则门控 + LLM 审计协议 + Skill 兜底规则（`inspector_fallback_audit`）
- **全局去重**：`GlobalDeduplicator` 跨 session 去重
- **入库提交**：`commit_node` 写入 L1/L2/L3/L4 层
- **拒绝可解释性**：`rejection_buckets` 聚合拒绝原因
- **进化引擎**：`InspectorEvolutionEngine` 调整审计阈值与 Prompt DNA
- **状态持久化**：File / Redis 后端（`backends/factory.py`），支持断点续审
- 向 Miner 回传按域名的通过率监督信号

## 目录结构

```text
inspector/
├── agent.py              # 主入口 InspectorAgent（LangGraph）
├── nodes/
│   ├── quality_score_node.py  # 评分 + 通过/拒绝
│   ├── commit_node.py         # 入库 + 报告片段
│   ├── audit_l3_node.py
│   ├── optimization_node.py
│   └── reflection_node.py
├── tools/
│   ├── browse_page.py         # 审计时二次抓页
│   ├── data_validator.py      # 规则校验 + fallback audit
│   ├── quality_gates.py       # 噪声域/路径门控
│   ├── global_deduplicator.py
│   └── report_generator.py    # Inspector 侧报告工具
├── llms/inspector_llm.py
├── prompts/inspector_prompt.py
├── memory/                    # 审计记忆
├── evolution/inspector_evolution_engine.py
├── feedback_loop/             # Prompt 优化、策略调整
├── backends/                  # Redis / 文件状态机
└── config/inspector_config.yaml
```

## 核心流程（LangGraph）

```
quality_score_node → commit_node → END
```

`InspectorAgent.process()` 在外层按 batch 循环，支持 `resume_state` 续审与 `on_progress` 回调。

### quality_score_node

- URL 清洗（junk path 过滤）
- Playwright 抓页（失败时降级规则审计）
- `DataValidator` + `InspectorLLM` 联合打分
- 输出 `audited_results` / `rejected_items` / `rejection_summary`

### commit_node

- 写入 `DataMemoryCenter`（L1–L4）
- 更新全局统计（Duplicate、Blacklist、Error 等）
- 可选触发 `ReportGenerator` 片段

## 输入与输出

| 方向 | 内容 |
|------|------|
| **输入** | `artifacts`（Miner 候选列表）、`user_query`、`session_id`、可选 `resume_state` |
| **输出** | 通过审计的资产列表；副作用：ChromaDB 入库、拒绝统计、L2 重挖队列 |

## Skill 集成

| Rule 文件 | 加载器 | 用途 |
|-----------|--------|------|
| `inspector_quality_gates.yaml` | `quality_gates.py` | 噪声 host/path、可信域、词表 |
| `inspector_audit.yaml` | `utils/inspector_audit.py` | LLM 审计协议、阈值 |
| `inspector_fallback_audit.yaml` | `utils/inspector_fallback_audit.py` | LLM 不可用时的规则打分 |
| `rejection_buckets.yaml` | `utils/rejection_buckets.py` | 拒绝原因分桶标签 |
| `report_taxonomy.yaml` | `utils/report_taxonomy.py` | 五维分类码本、host 强制归类 |

## 环境变量

| 变量 | 说明 |
|------|------|
| `MA4CD_INSPECTOR_MODEL` | 审计 LLM |
| `MA4CD_INSPECTOR_STRICT` | 严格模式 |
| `MA4CD_INSPECTOR_MIN_SCORE` | 最低通过分 |
| `MA4CD_SKILL` | 领域 Skill |

Redis 后端相关变量见 `agents/inspector/backends/` 与 `.env.example`。

## 独立运行

Inspector 通常由 `main_workflow.py` 批量调用。`agents/inspector/run.py` 当前为空，建议使用主流水线或单元测试：

```bash
python -m unittest tests.test_new_skill_packs -v
```

## 常见日志说明

- `net::ERR_ABORTED; maybe frame was detached?` — Playwright 单 URL 导航被站点中断，**单条失败**，不阻断整批审计
- `Future exception was never retrieved` — asyncio 后台 Future 未消费，多为关页时 `goto` 仍在进行，属噪音警告

## 相关代码

- 全局报告：`utils/report_generator.py`（流水线最终报告）
- 数据存储：`data_memory_center/`
- Skill 框架：`skills/README.md`
