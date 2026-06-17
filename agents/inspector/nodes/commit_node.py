import logging
import os
import sys
import asyncio
import json
from typing import Dict, Any, List, TypedDict
from urllib.parse import urlparse

# --- 路径环境保持不变 ---
current_file = os.path.abspath(__file__)
nodes_dir = os.path.dirname(current_file)
inspector_dir = os.path.dirname(nodes_dir)
agents_dir = os.path.dirname(inspector_dir)
root_dir = os.path.dirname(agents_dir) 
if root_dir not in sys.path: sys.path.append(root_dir)

from data_memory_center.manager import DataMemoryCenter
from agents.inspector.tools.report_generator import ReportGenerator

try:
    from agents.inspector.tools.global_deduplicator import GlobalDeduplicator
except ImportError:
    GlobalDeduplicator = None
    
logger = logging.getLogger("inspector.nodes.commit")

# --- 单例模式缓存 ---
_GLOBAL_DM_INSTANCE = None
_GLOBAL_DEDUPLICATOR_INSTANCE = None

def get_memory_center():
    global _GLOBAL_DM_INSTANCE
    if _GLOBAL_DM_INSTANCE is None: _GLOBAL_DM_INSTANCE = DataMemoryCenter()
    return _GLOBAL_DM_INSTANCE

def get_deduplicator():
    global _GLOBAL_DEDUPLICATOR_INSTANCE
    if _GLOBAL_DEDUPLICATOR_INSTANCE is None and GlobalDeduplicator is not None:
        _GLOBAL_DEDUPLICATOR_INSTANCE = GlobalDeduplicator()
    return _GLOBAL_DEDUPLICATOR_INSTANCE

async def commit_node(state: Dict[str, Any]) -> Dict[str, Any]:
    logger.info(">>> Node: Deep Data Commit & Multi-Dimensional Fix")

    current_audited = state.get("audited_results", [])
    current_rejected = state.get("rejected_items", [])
    stats = state.get("statistics", {}).copy()
    mission_id = stats.get("mission_id", "MA4CD_MISSION")
    
    # 状态初始化
    if "full_passed_accumulator" not in stats: stats["full_passed_accumulator"] = []
    if "full_rejected_accumulator" not in stats: stats["full_rejected_accumulator"] = []
    if "global_commit_stats" not in stats:
        stats["global_commit_stats"] = {
            "L1": 0, "L2": 0, "L3": 0, "L4": 0,
            "Blacklist": 0, "SoftIgnore": 0, "Duplicate": 0, "Error": 0,
            "gen": stats.get("gen", 0)
        }
    
    batch_commit_stats = {"L1": 0, "L2": 0, "L3": 0, "L4": 0, "Blacklist": 0, "SoftIgnore": 0, "Duplicate": 0, "Error": 0}
    passed_urls_this_batch = set()

    dm = get_memory_center()
    deduplicator = get_deduplicator()

    for item in current_audited:
        url = item.get("url", "").strip()
        if not url: continue

        # 1. 🌟 暴力数据清洗与解析 🌟
        audit_raw = item.get("audit_response", {})
        
        # 核心修复：如果 audit_response 是字符串，强行解析它
        if isinstance(audit_raw, str):
            try:
                audit_raw = json.loads(audit_raw)
            except:
                audit_raw = {}

        tags = audit_raw.get("four_dimensional_analysis", {})
        
        # 强制提取分值
        try:
            raw_score = audit_raw.get("score") or item.get("score") or 0.0
            item["score"] = float(raw_score)
        except:
            item["score"] = 0.5

        # 标签兜底采用通用值，避免领域硬编码
        level = str(item.get("level", audit_raw.get("level", "L3"))).upper()
        item["level"] = level
        item["domain"] = tags.get("domain") or "N/A"
        item["channel"] = tags.get("source_channel") or urlparse(url).netloc
        item["region"] = tags.get("region") or "N/A"
        
        # 物理形态逻辑兜底
        morph = tags.get("data_morphology")
        item["morphology"] = morph or "N/A"

        # 2. 累加器注入 (在查重之前，保证出现在本次报告中)
        stats["full_passed_accumulator"].append(item)

        # 3. 入库查重逻辑
        is_dup = False
        if deduplicator:
            is_dup = await deduplicator.is_duplicate(url) if asyncio.iscoroutinefunction(deduplicator.is_duplicate) else deduplicator.is_duplicate(url)
        
        if is_dup:
            batch_commit_stats["Duplicate"] += 1
            passed_urls_this_batch.add(url)
            continue

        try:
            # 同步元数据并路由入库
            if "metadata" not in item: item["metadata"] = {}
            item["metadata"].update({"domain": item["domain"], "region": item["region"], "score": item["score"]})
            
            if level == "L1": dm.add_l1_hub(item)
            elif level == "L2": dm.add_l2_portal(item)
            elif level == "L3": dm.add_l3_dataset(item)
            elif level == "L4": dm.add_l4_record(item)
            
            batch_commit_stats[level] += 1
            passed_urls_this_batch.add(url)
            if deduplicator:
                for m in ['add_record', 'add', 'insert']:
                    if hasattr(deduplicator, m): getattr(deduplicator, m)(url); break

        except Exception as e:
            logger.error(f"Commit Fail: {e}")
            batch_commit_stats["Error"] += 1

    # --- 拒绝项处理：仅对模型明确 HARD_BLACKLIST 的链接执行全局拉黑 ---
    for item in current_rejected:
        url = item.get("url", "").strip()
        if not url or url in passed_urls_this_batch: continue

        audit_raw = item.get("audit_response", {})
        if isinstance(audit_raw, str):
            try:
                audit_raw = json.loads(audit_raw)
            except Exception:
                audit_raw = {}

        action = str(audit_raw.get("action", "")).upper()
        should_blacklist = action == "HARD_BLACKLIST"

        try:
            if should_blacklist:
                dm.add_blacklist(url=url, reason=item.get('reason', 'Noise'), source="inspector")
                batch_commit_stats["Blacklist"] += 1
            else:
                batch_commit_stats["SoftIgnore"] += 1
            stats["full_rejected_accumulator"].append(item)
        except: pass

    for k, v in batch_commit_stats.items():
        stats["global_commit_stats"][k] = stats["global_commit_stats"].get(k, 0) + v

    is_final = state.get("is_final_batch") or stats.get("is_final_batch") or state.get("is_final")
    if is_final:
        logger.info(f"🏁 Final Flag. Generating report for {len(stats['full_passed_accumulator'])} items...")
        try:
            rg = ReportGenerator(run_id=mission_id)
            stats["report_file"] = rg.generate(stats["full_passed_accumulator"], stats["full_rejected_accumulator"], stats["global_commit_stats"])
            logger.info(f"🏆 Report Created: {stats['report_file']}")
        except Exception as e:
            logger.error(f"Report Gen Failed: {e}")

    out: Dict[str, Any] = {
        "statistics": stats,
        "audited_results": current_audited,
        "rejected_items": current_rejected,
    }
    if state.get("rejection_summary"):
        out["rejection_summary"] = state.get("rejection_summary")
    return out
