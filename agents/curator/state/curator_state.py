# agents/curator/state/curator_state.py

from typing import TypedDict, Dict, Any, List

class CuratorState(TypedDict):
    """
    Curator (总馆长) 智能体的流式状态总线。
    该状态在 LangGraph 的三个核心节点之间流转，记录系统的流量健康度与战略推演结果。
    """
    
    # ==========================================
    # 📥 初始输入 (由外部 main_workflow 注入)
    # ==========================================
    session_id: str                 # 当前需要监控和盘点的 Session ID
    commander_intent: str           # 指挥官下发的宏观战略指令 (例如: "挖掘南美洲地理与经济数据")
    
    # ==========================================
    # 📡 节点 1 产出: Flow Discovery Node
    # ==========================================
    flow_metrics: Dict[str, Any]    
    """
    流量特征打点数据 (纯 Python 解析 Session JSON 获得，无大模型消耗)。
    包含字段示例:
    - total_requests: int
    - status_200: int
    - status_403: int
    - status_404: int
    - total_assets_found: int (当前 session 存入 L3/L4 的数量)
    """

    # ==========================================
    # ⚖️ 节点 2 产出: Output Synthesis Node
    # ==========================================
    yield_status: Dict[str, Any]    
    """
    产出研判与熔断器状态 (ROI 计算)。
    包含字段示例:
    - yield_rate: float (产出率 = 资产数 / 总请求数)
    - block_rate: float (封锁率 = 403 / 总请求数)
    - can_continue: bool (是否触发了熔断。若 False，图流转将直接走向 END)
    - stop_reason: str (触发熔断的具体原因，如 "HIGH_BLOCK_RATE_403")
    """

    # ==========================================
    # 🧠 节点 3 产出: Strategic Node
    # ==========================================
    strategic_gaps: List[str]       
    """
    学科链条/维度盲区分析 (由 LLM 推演得出)。
    示例: ["极度缺乏国家级的人口普查原始数据集", "缺少实时的经济地理 API 接口"]
    """
    
    next_directives: str            
    """
    给系统下一轮的调整建议/具体指令 (由 LLM 结合 flow_metrics 与战略意图生成)。
    示例: "建议 Scout 优先使用西班牙语检索，并指示 Miner 重点挖掘带有 Censo 关键词的虚拟路径。"
    """