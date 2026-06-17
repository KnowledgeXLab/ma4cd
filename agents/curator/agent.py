import sys
import os
import logging
from typing import Dict, Any

# ==========================================
# 🔥 动态路径修复 (保持与其他 Agent 一致)
# ==========================================
current_file = os.path.abspath(__file__)
curator_dir = os.path.dirname(current_file)
agents_dir = os.path.dirname(curator_dir)
project_root = os.path.dirname(agents_dir)

if project_root not in sys.path:
    sys.path.insert(0, project_root)

from langgraph.graph import StateGraph, END
from agents.curator.state.curator_state import CuratorState
from agents.curator.nodes import flow_discovery_node, output_synthesis_node, strategic_node

logger = logging.getLogger("curator.agent")

class CuratorAgent:
    """
    总馆长 (Curator) 智能体。
    负责在不增加底层数据库读写负担的前提下，通过流式解析 Session 记忆，
    实时监控系统健康度 (ROI/风控)，并在必要时召唤大模型进行学科链条的战略推演。
    """
    def __init__(self):
        self.app = self._build_workflow()
        logger.info("🏛️ Curator Agent (总馆长) 初始化完成，流式监控引擎已就绪。")

    def _should_continue(self, state: CuratorState) -> str:
        """
        条件路由函数：检查 Output Synthesis Node 输出的熔断信号。
        如果 can_continue 为 True，走向战略推演；否则走向 END 终止流程。
        """
        can_continue = state.get("yield_status", {}).get("can_continue", True)
        if can_continue:
            return "strategic_node"
        else:
            stop_reason = state.get("yield_status", {}).get("stop_reason", "UNKNOWN")
            logger.warning(f"🛑 Curator 路由拦截：系统触发熔断 [{stop_reason}]，跳过战略推演，直接结束当前盘点。")
            return END

    def _build_workflow(self):
        """构建 Curator 的流式有向无环图 (DAG)"""
        workflow = StateGraph(CuratorState)
        
        # 1. 注册节点 (注意 strategic_node 是 async 的，LangGraph 会自动处理)
        workflow.add_node("flow_discovery", flow_discovery_node)
        workflow.add_node("output_synthesis", output_synthesis_node)
        workflow.add_node("strategic_node", strategic_node)
        
        # 2. 设置入口点
        workflow.set_entry_point("flow_discovery")
        
        # 3. 定义边：流量探勘 -> 产出研判
        workflow.add_edge("flow_discovery", "output_synthesis")
        
        # 4. 🔥 定义条件路由：产出研判 -> 战略推演 OR 结束
        workflow.add_conditional_edges(
            "output_synthesis",
            self._should_continue,
            {
                "strategic_node": "strategic_node",
                END: END
            }
        )
        
        # 5. 定义边：战略推演 -> 结束
        workflow.add_edge("strategic_node", END)
        
        return workflow.compile()

    async def evaluate_session(self, session_id: str, commander_intent: str) -> Dict[str, Any]:
        """
        对外暴露的核心接口。
        传入当前 Session ID 和宏观指令，返回完整的盘点状态字典。
        """
        logger.info(f"\n🔍 [CURATOR] 开始对 Session [{session_id[:8]}...] 进行深度盘点")
        
        initial_state: CuratorState = {
            "session_id": session_id,
            "commander_intent": commander_intent,
            "flow_metrics": {},
            "yield_status": {},
            "strategic_gaps": [],
            "next_directives": ""
        }
        
        try:
            # 触发 LangGraph 流转
            final_state = await self.app.ainvoke(initial_state)
            
            # 打印精简的战报摘要
            gaps = final_state.get("strategic_gaps", [])
            yield_info = final_state.get("yield_status", {})
            if yield_info.get("can_continue") and gaps:
                logger.info(f"🎯 Curator 战报生成完毕 | 发现盲区: {len(gaps)} 处 | 建议: {final_state.get('next_directives')}")
            
            return final_state
            
        except Exception as e:
            logger.error(f"❌ Curator 盘点执行失败: {e}")
            return initial_state

# ==========================================
# 🧪 快速测试入口
# ==========================================
if __name__ == "__main__":
    import asyncio
    
    async def run_test():
        # 实例化总馆长
        curator = CuratorAgent()
        
        # 模拟调用 (确保你的 memory_data/sessions 目录下有这个 JSON 文件才能读出数据)
        mock_session_id = "test_session_id_here" 
        mock_intent = "寻找美国西进运动的底层物理证据与人口迁徙数据库"
        
        result = await curator.evaluate_session(mock_session_id, mock_intent)
        print("\n=== 最终 State 输出 ===")
        import json
        print(json.dumps(result, indent=2, ensure_ascii=False))

    asyncio.run(run_test())