# agents/curator/nodes/strategic_node.py

import logging
from typing import Dict, Any
from agents.curator.state.curator_state import CuratorState
from agents.curator.llms import create_curator_llm
from agents.curator.prompts import STRATEGIC_SYSTEM_PROMPT

logger = logging.getLogger("curator.strategic")

async def strategic_node(state: CuratorState) -> Dict[str, Any]:
    """
    战略推演节点：
    读取当前的流量快照和资产标题，召唤大模型根据“学科链条”推演盲区，
    并生成给下级智能体（Commander/Scout/Miner）的明确搜寻指令。
    """
    logger.info(">>> Node: Strategic (学科链条与全局战略推演) 🧠")
    
    # 1. 从 State 中提取上下文情报
    intent = state.get("commander_intent", "未定义宏观意图")
    metrics = state.get("flow_metrics", {})
    extracted_titles = metrics.get("extracted_titles", [])
    
    # 限制标题数量，防止 Token 溢出（取前 30 个最具代表性的标题即可）
    if extracted_titles:
        titles_summary = "\n".join([f"- {title}" for title in extracted_titles[:30]])
    else:
        titles_summary = "本轮未提取到带有明确标题的高价值资产。"
    
    # 2. 组装给大模型的动态 User Prompt
    user_prompt = f"""
    [当前宏观指令]: 
    {intent}
    
    [本轮流量特征]:
    - 总页面嗅探数: {metrics.get('total_requests', 0)}
    - 成功提取核心资产数: {metrics.get('total_assets_found', 0)}
    
    [本轮已捕获资产的标题快照]:
    {titles_summary}
    """
    
    # 3. 实例化轻量级且自带 JSON 修复能力的 Curator LLM
    # 战略推演需要一定的逻辑能力，默认使用 gpt-4o-mini 或你配置的模型
    llm = create_curator_llm()
    
    try:
        # 4. 召唤大模型进行推演 (直接返回安全的 Dict)
        logger.debug("正在请求 LLM 进行学科链条推演...")
        response_dict = await llm.ainvoke_json(
            system_prompt=STRATEGIC_SYSTEM_PROMPT,
            user_prompt=user_prompt,
            temperature=0.4 # 略微调高温度，允许一定的发散性战略联想
        )
        
        # 5. 安全提取预期字段 (带兜底默认值)
        gaps = response_dict.get("strategic_gaps", [])
        directives = response_dict.get("next_directives", "建议扩大搜索范围，保持当前挖掘策略。")
        
        if gaps:
            logger.info(f"💡 发现学科盲区: {gaps[0]} ...等 (共 {len(gaps)} 项)")
            logger.info(f"🗣️ 下达战略指令: {directives}")
        else:
            logger.warning("⚠️ 大模型未能成功提取到具体的战略盲区。")
            
        return {
            "strategic_gaps": gaps,
            "next_directives": directives
        }
        
    except Exception as e:
        logger.error(f"❌ 战略推演节点崩溃: {e}")
        # 终极容错：确保即使出错，图流转也能继续，不会卡死整个系统
        return {
            "strategic_gaps": ["[ERROR] 战略推演引擎故障，无法分析链条"],
            "next_directives": "系统推理出现波动，建议暂时回退至广度优先搜索策略，避免陷入局部最优。"
        }