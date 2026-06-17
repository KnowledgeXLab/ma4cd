import logging
from typing import Dict, Any
from agents.curator.state.curator_state import CuratorState

logger = logging.getLogger("curator.synthesis")

def output_synthesis_node(state: CuratorState) -> Dict[str, Any]:
    logger.info(">>> Node: Output Synthesis (ROI 研判与熔断控制) ⚖️")
    
    metrics = state.get("flow_metrics", {})
    
    # 基础指标提取
    total_req = max(metrics.get("total_requests", 0), 1) # 防止除零
    assets = metrics.get("total_assets_found", 0)
    blocks_403 = metrics.get("status_403", 0)
    deads_404 = metrics.get("status_404", 0)
    
    # 效能计算
    yield_rate = assets / total_req
    block_rate = blocks_403 / total_req
    dead_rate = deads_404 / total_req
    
    yield_status = {
        "yield_rate": round(yield_rate, 4),
        "block_rate": round(block_rate, 4),
        "dead_rate": round(dead_rate, 4),
        "can_continue": True,
        "stop_reason": "ALL_CLEAR"
    }
    
    # ==========================================
    # 🛑 动态熔断规则 (可根据实战情况调整阈值)
    # ==========================================
    if block_rate > 0.35 and total_req > 10:
        yield_status["can_continue"] = False
        yield_status["stop_reason"] = "HIGH_BLOCK_RATE_403"
        logger.warning(f"🚨 触发风控熔断: 403 封锁率达 {block_rate*100:.1f}%！当前目标可能具备极强反爬措施。")
        
    elif dead_rate > 0.5 and total_req > 10:
        yield_status["can_continue"] = False
        yield_status["stop_reason"] = "DEAD_END_404"
        logger.warning(f"🚨 触发死链熔断: 404 死链率达 {dead_rate*100:.1f}%！该 L2 目录可能已废弃。")
        
    elif total_req > 30 and assets == 0:
        yield_status["can_continue"] = False
        yield_status["stop_reason"] = "LOW_ROI_ZERO_YIELD"
        logger.warning("🚨 触发效能熔断: 连续请求无产出，当前分支为数据荒漠。")
        
    else:
        logger.info(f"✅ 通道健康 | 产出率: {yield_rate*100:.1f}% | 系统可继续推演。")

    return {"yield_status": yield_status}