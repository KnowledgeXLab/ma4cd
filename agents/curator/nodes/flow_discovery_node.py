import os
import json
import logging
from typing import Dict, Any, List
from agents.curator.state.curator_state import CuratorState

logger = logging.getLogger("curator.flow")

def get_project_root():
    current_dir = os.path.dirname(os.path.abspath(__file__))
    return os.path.dirname(os.path.dirname(os.path.dirname(current_dir)))

def flow_discovery_node(state: CuratorState) -> Dict[str, Any]:
    logger.info(">>> Node: Flow Discovery (流量健康度探勘) 📡")
    session_id = state.get("session_id")
    
    # 构造动态路径
    project_root = get_project_root()
    session_file_path = os.path.join(project_root, "memory_data", "sessions", f"{session_id}.json")
    
    flow_metrics = {
        "total_requests": 0,
        "status_200": 0,
        "status_403": 0,
        "status_404": 0,
        "total_assets_found": 0,
        "extracted_titles": [] # 核心：将挖到的标题透传给下游，供大模型分析学科链条
    }
    
    if os.path.exists(session_file_path):
        try:
            with open(session_file_path, 'r', encoding='utf-8') as f:
                session_data = json.load(f)
            
            # 暴力/模糊嗅探器：无论底层怎么存，我们提取特征
            session_str = json.dumps(session_data, ensure_ascii=False)
            
            # 1. 统计状态码特征
            flow_metrics["status_403"] = session_str.count("403") + session_str.count("Forbidden")
            flow_metrics["status_404"] = session_str.count("404") + session_str.count("Not Found")
            
            # 2. 精确统计事件
            events = session_data.get("events", [])
            flow_metrics["total_requests"] = len(events) if events else session_str.count('"url":')
            
            # 3. 提取成功入库的资产特征 (假设存在 extracted_items 或类似字段)
            extracted = session_data.get("extracted_items", [])
            if isinstance(extracted, list):
                flow_metrics["total_assets_found"] = len(extracted)
                for item in extracted:
                    if isinstance(item, dict) and item.get("title"):
                        flow_metrics["extracted_titles"].append(item.get("title"))
                        
        except Exception as e:
            logger.error(f"❌ 解析 Session JSON 失败: {e}")
    else:
        logger.warning(f"⚠️ 找不到 Session 文件: {session_file_path}，使用默认空流量指标。")
        
    logger.info(f"📊 流量快照 | 请求数: {flow_metrics['total_requests']} | 403拦截: {flow_metrics['status_403']} | 产出资产: {flow_metrics['total_assets_found']}")
    
    return {"flow_metrics": flow_metrics}