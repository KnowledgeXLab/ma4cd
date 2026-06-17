import logging
import json
from typing import Dict, Any, List, TypedDict
from datetime import datetime

# 复用之前的 LLM 模块
# 如果运行报错找不到模块，记得在文件头加 sys.path.append(...)
import sys
import os
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
sys.path.append(parent_dir)

from llms.inspector_llm import InspectorLLM

logger = logging.getLogger("inspector.nodes.optimization")

# 定义 State 结构 (保持一致)
class InspectorState(TypedDict):
    miner_output: Dict[str, Any]
    current_config: Dict[str, float]
    audited_results: List[Dict]
    rejected_items: List[Dict]
    statistics: Dict[str, Any]

async def optimization_node(state: InspectorState) -> Dict[str, Any]:
    """
    Inspector 的进化节点 (Evolution Node)。
    
    职责：
    1. 分析本轮审查的统计数据 (Statistics)。
    2. 如果发现异常 (如通过率过低/过高)，调用 LLM 反思当前的评分策略。
    3. 生成新的权重配置 (Weights)，写入 State，影响后续的评分逻辑。
    """
    logger.info(">>> Node: Start Self-Optimization & Reflection")

    stats = state.get("statistics", {})
    current_config = state.get("current_config", {})
    current_weights = current_config.get("weights", {
        # 默认权重作为参考
        "scientific_value": 0.4,
        "data_utility": 0.3, 
        "metadata_quality": 0.2,
        "source_authority": 0.1
    })

    # 1. 简单规则判断是否需要进化
    # 如果处理数量太少，不具备统计意义，直接跳过
    total_processed = stats.get("total", 0)
    if total_processed < 5:
        logger.info("Not enough data to optimize. Skipping.")
        return {} # 返回空字典表示 State 无更新

    pass_rate_str = stats.get("pass_rate", "0%").strip('%')
    try:
        pass_rate = float(pass_rate_str)
    except:
        pass_rate = 0.0

    # 触发进化的条件 (例如：通过率 < 10% 或 > 90%，或者 rejected 数量很多)
    needs_optimization = False
    trigger_reason = ""

    if pass_rate < 10.0:
        needs_optimization = True
        trigger_reason = "Pass rate is suspiciously low (<10%). Requirements might be too strict."
    elif pass_rate > 90.0:
        needs_optimization = True
        trigger_reason = "Pass rate is suspiciously high (>90%). We might be letting garbage in."
    
    if not needs_optimization:
        logger.info(f"Pass rate {pass_rate}% is within normal range. No optimization needed.")
        return {}

    # 2. 调用 LLM 进行策略调整 (Meta-Reasoning)
    logger.info(f"Triggering Optimization: {trigger_reason}")
    
    llm = InspectorLLM(model=os.getenv("MA4CD_INSPECTOR_MODEL", "deepseek-chat"), temperature=0.0)
    
    # 提取拒绝原因摘要
    rejected_samples = state.get("rejected_items", [])[:5] # 只看前5个被拒的
    reject_reasons = [item.get("reason", "unknown") for item in rejected_samples]

    prompt = f"""
    You are the Strategy Optimizer for a Data Inspector Agent.
    
    Current Situation:
    - Trigger: {trigger_reason}
    - Current Pass Rate: {pass_rate}%
    - Recent Reject Reasons: {json.dumps(reject_reasons)}
    - Current Weights: {json.dumps(current_weights)}
    
    Task:
    Analyze if the current scoring weights are unbalanced. 
    - If pass rate is too low, maybe 'scientific_value' or 'metadata_quality' is weighted too heavily for this batch of data.
    - If pass rate is too high, maybe we need to increase the weight of 'scientific_value' to be stricter.
    
    Output JSON:
    {{
        "analysis": "Short thought process...",
        "new_weights": {{
            "scientific_value": float (0.0-1.0),
            "data_utility": float (0.0-1.0),
            "metadata_quality": float (0.0-1.0),
            "source_authority": float (0.0-1.0)
        }},
        "adjustment_reason": "Why did you change the weights?"
    }}
    Ensure new_weights sum to approximately 1.0.
    """

    try:
        # 使用 LLM 决策
        result = llm.invoke(prompt, require_json=True)
        
        new_weights = result.get("new_weights")
        reason = result.get("adjustment_reason")
        
        if new_weights:
            logger.info(f"Strategy Evolved! Reason: {reason}")
            logger.info(f"New Weights: {new_weights}")
            
            # 3. 更新 State
            # 注意：我们将新配置放入 'current_config'，下一轮 quality_score_node 会读取它
            return {
                "current_config": {
                    "weights": new_weights,
                    "last_updated": datetime.now().isoformat(),
                    "update_reason": reason
                }
            }
            
    except Exception as e:
        logger.error(f"Optimization failed: {e}")
    
    return {} # 失败则不更新

# 单元测试
if __name__ == "__main__":
    import asyncio
    
    async def test_opt():
        # 模拟一个非常严格的场景 (通过率 0%)
        mock_state = {
            "statistics": {"total": 10, "pass_rate": "0%"},
            "rejected_items": [{"reason": "Low metadata score"}, {"reason": "Low metadata score"}],
            "current_config": {"weights": {"scientific_value": 0.4, "metadata_quality": 0.4, "data_utility": 0.1, "source_authority": 0.1}}
        }
        
        print("Running Optimization Node...")
        changes = await optimization_node(mock_state)
        print(json.dumps(changes, indent=2))

    asyncio.run(test_opt())
