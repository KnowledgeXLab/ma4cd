# ma4cd/prompts/scout_prompts.py
"""
Scout Agent 专用提示词与 Schema 定义
专为广域线索侦察设计：快速搜索、粗略筛选、产出初步 URL 线索列表
"""

import json


# ======================================
# JSON Schema 定义（纯 Python 对象）
# ======================================

output_schema_scout_plan = {
    "type": "array",
    "items": {
        "type": "object",
        "properties": {
            "search_query": {"type": "string"},
            "tier": {"type": "string", "enum": ["tier1", "tier2", "tier3"]},
            "description": {"type": "string"},
            "expected_sources": {
                "type": "array",
                "items": {"type": "string"}
            }
        },
        "required": ["search_query", "tier", "description"]
    },
    "description": "搜索计划列表，最多 8 项，每项为一个独立的搜索方向"
}

output_schema_search_decision = {
    "type": "object",
    "properties": {
        "search_query": {"type": "string"},
        "search_tool": {"type": "string"},
        "reasoning": {"type": "string"},
        "start_date": {"type": "string", "description": "YYYY-MM-DD，仅部分工具需要"},
        "end_date": {"type": "string", "description": "YYYY-MM-DD，仅部分工具需要"}
    },
    "required": ["search_query", "search_tool", "reasoning"]
}

output_schema_clues = {
    "type": "array",
    "items": {
        "type": "object",
        "properties": {
            "url": {"type": "string"},
            "title": {"type": "string"},
            "snippet": {"type": "string"},
            "source": {"type": "string"},
            "tier": {"type": "string"},
            "relevance_score": {"type": "integer", "minimum": 0, "maximum": 10},
            "data_type_hint": {
                "type": "string",
                "description": "线索指向的数据形态提示，如 'dataset', 'database', 'report', 'portal'"
            }
        },
        "required": ["url", "title", "relevance_score"]
    },
    "description": "从搜索结果中提取的高潜力数据线索列表"
}

output_schema_scout_reflect = {
    "type": "object",
    "properties": {
        "need_more": {"type": "boolean"},
        "reason": {"type": "string"},
        "missing_aspects": {
            "type": "array",
            "items": {"type": "string"},
            "description": "当前遗漏的领域、Tier、来源类型等"
        },
        "suggested_next_queries": {
            "type": "array",
            "items": {"type": "string"},
            "description": "建议的补充搜索关键词"
        }
    },
    "required": ["need_more", "reason"]
}


# ======================================
# 提示词模板（使用 f-string 动态插入 schema，避免转义冲突）
# ======================================

# 搜索规划提示词
def get_scout_plan_prompt(user_task: str) -> str:
    schema_text = json.dumps(output_schema_scout_plan, indent=2, ensure_ascii=False)
    return f"""
你是一位全球数据线索侦察兵（Scout Agent）。
当前任务：{user_task}

你的目标：快速规划广域搜索策略，覆盖尽可能多的潜在数据源（L1枢纽、L2门户、L3独立库、L4资产线索）。
优先考虑：
- 高价值平台：HuggingFace、Zenodo、Figshare、Data.gov、GitHub、PubMed、World Bank、Kaggle 等
- 多语言、多国家覆盖（51个国家/地区）
- 不同数据形态：数据集、数据库、报告、API、门户

输出一个搜索计划列表（最多8项），每项包括：
- search_query：精确搜索关键词（支持 site:、filetype:、inurl: 等高级语法）
- tier：优先级（tier1/tier2/tier3）
- description：这条搜索的意图和预期发现类型
- expected_sources：可能命中的平台/网站类型

严格按照以下 JSON Schema 输出：
{schema_text}

只返回 JSON 对象，无任何解释或额外文本。
"""

# 单次搜索决策提示词
def get_scout_search_decision_prompt(subtask_description: str, query: str, tier: str) -> str:
    schema_text = json.dumps(output_schema_search_decision, indent=2, ensure_ascii=False)
    return f"""
你正在执行广域线索搜索子任务。
当前子任务描述：{subtask_description}
查询关键词：{query}
Tier：{tier}

可用工具（优先选择广域搜索工具）：
- web_search：通用网页搜索，支持 site:、filetype: 等（最常用）
- x_keyword_search：X/Twitter 关键词搜索（找实时分享的链接）
- github_search：GitHub 仓库/数据集搜索
- browse_page：浏览单个 URL，提取链接或简单摘要（仅浅层用）
- x_semantic_search：X 语义搜索
- url_validator：快速验证 URL 是否有效

任务：
1. 选择 1 个最合适的工具（优先 web_search）
2. 制定精确的 search_query（可加 site:、filetype:pdf、inurl:dataset 等）
3. 说明 reasoning（为什么选这个工具/查询）
4. 如果需要时间范围，指定 start_date / end_date（YYYY-MM-DD）

输出严格 JSON：
{schema_text}

只返回 JSON，无其他文字。
"""

# 线索提取提示词
def get_scout_extract_clues_prompt() -> str:
    schema_text = json.dumps(output_schema_clues, indent=2, ensure_ascii=False)
    return f"""
你从搜索结果中提取高潜力数据线索。
输入：搜索 query + 原始搜索结果列表

任务：
- 只提取包含潜在数据资源的 URL（数据集、数据库、报告、门户、API 等）
- 过滤掉无关、低质、广告、死链
- 为每条线索打分（relevance_score 0-10）
- 尽量保留 source（平台名）、tier、data_type_hint（dataset/database/report/portal 等）
- 最多保留 30 条

输出 JSON 数组：
{schema_text}

只返回 JSON，无其他文字。
"""

# 反思提示词
def get_scout_reflect_prompt(clues_count: int) -> str:
    schema_text = json.dumps(output_schema_scout_reflect, indent=2, ensure_ascii=False)
    return f"""
当前已收集线索数量：{clues_count} 条

反思任务：
- 当前搜索是否足够广？覆盖了哪些 Tier、国家、数据形态？
- 是否有明显遗漏（例如某个领域、来源类型、语言）？
- 命中率如何？哪些关键词/工具效果好？
- 是否需要补充搜索？

如果需要继续，输出 need_more: true，并给出 missing_aspects 和 suggested_next_queries
否则输出 need_more: false 和 reason

输出 JSON：
{schema_text}

只返回 JSON，无其他文字。
"""


# ======================================
# 导出函数（推荐使用这些函数动态生成提示词，避免转义问题）
# ======================================

__all__ = [
    "output_schema_scout_plan",
    "output_schema_search_decision",
    "output_schema_clues",
    "output_schema_scout_reflect",
    "get_scout_plan_prompt",
    "get_scout_search_decision_prompt",
    "get_scout_extract_clues_prompt",
    "get_scout_reflect_prompt",
]