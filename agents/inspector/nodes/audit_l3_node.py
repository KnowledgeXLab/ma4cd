import logging
from typing import Dict, Any, Optional
from urllib.parse import urlparse

# ==========================================
# 🔥 路径修复：使用绝对路径导入
# ==========================================
try:
    from agents.inspector.llms.inspector_llm import InspectorLLM
    from agents.inspector.memory.managers.memory_manager import MemoryManager
    from agents.inspector.prompts.inspector_prompt import InspectorPrompt
    from agents.inspector.tools.data_validator import DataValidator
    from agents.inspector.state.inspector_state import InspectorState  # ✅ 新增导入 State
except ImportError:
    class InspectorLLM: pass
    class MemoryManager: 
        def consult_past_experience(self, u): return None
        def memorize_audit_result(self, r): pass
    class InspectorPrompt: pass
    class DataValidator:
        def __init__(self, _): pass
        def validate_dataset_link(self, **k): return {}
    class InspectorState:
        def add_to_remine_queue(self, u): pass

logger = logging.getLogger(__name__)

class AuditL3Node:
    """
    L3 审计节点：执行深度链接分析（包含 L2 溯源反哺机制 v3.0）
    """
    def __init__(self, llm: InspectorLLM, memory: MemoryManager, state: InspectorState):
        self.llm = llm
        self.memory = memory
        self.state = state  # ✅ 挂载状态机，用于跨 Agent 通信
        self.validator = DataValidator(self.llm)

    def _extract_base_url(self, url: str) -> str:
        """
        辅助方法：截断虚拟路径，提取母站根域名/核心入口。
        例如：https://worldbank.org/data/123 -> https://worldbank.org
        """
        try:
            parsed = urlparse(url)
            # 基础截断：只保留 scheme 和 netloc (如 https://domain.com)
            # 注意：某些 L2 可能带有第一级 path（如 gov.cn/data），这里可以根据实际业务微调
            base_url = f"{parsed.scheme}://{parsed.netloc}"
            return base_url
        except Exception as e:
            logger.warning(f"URL 解析失败 {url}: {e}")
            return url

    def process_task(self, task: Dict[str, Any]) -> Dict[str, Any]:
        """
        对单个任务进行审计，并执行智能溯源
        """
        url = task.get("url")
        if not url:
            return {
                "task_id": task.get("task_id"), 
                "url": None, 
                "report": {"status": "ERROR", "analysis": "Missing URL"}
            }

        logger.info(f"🚀 Auditing URL: {url} (ID: {task.get('task_id')})")

        # 1. 记忆检索 (Memory Lookup)
        try:
            past_record = self.memory.consult_past_experience(url)
            if past_record:
                status = past_record.get('status', 'Unknown') if isinstance(past_record, dict) else getattr(past_record, 'status', 'Unknown')
                score = past_record.get('score', 0) if isinstance(past_record, dict) else getattr(past_record, 'score', 0)
                reason = past_record.get('reason', '') if isinstance(past_record, dict) else getattr(past_record, 'reason', '')

                logger.info(f"✅ Memory Hit for {url}. Status: {status}")
                return {
                    "task_id": task["task_id"],
                    "url": url,
                    "report": {"status": status, "metrics": {"ai_score": score}, "analysis": reason, "from_cache": True}
                }
        except Exception as e:
            logger.warning(f"Memory lookup failed: {e}")

        # 2. 执行核心 AI 审计
        try:
            page_content = ""
            try:
                from agents.inspector.tools.browse_page import BrowsePageTool
                page_content = BrowsePageTool(url, max_length=3500)
            except ImportError:
                try:
                    from agents.miner.tools.browse_page import BrowsePageTool
                    page_content = BrowsePageTool(url, max_length=3500)
                except Exception:
                    pass

            # 验证当前链接
            report = self.validator.validate_dataset_link(
                url=url,
                title=task.get("title", ""),
                description=task.get("desc", ""),
                page_content=page_content,
                user_query=task.get("user_query", "")
            )
            
            # 3. 记忆持久化 (Memorization) 当前链接
            if self.memory:
                self.memory.memorize_audit_result(report)
            
            current_level = report.get('level', 'UNKNOWN')
            logger.info(f"✅ Audit completed for {url} → Level: {current_level}")

            # ==========================================
            # 🔄 4. 核心新增：L3 溯源与 L2 反哺逻辑
            # ==========================================
            if current_level == "L3":
                base_url = self._extract_base_url(url)
                
                # 如果截断后的母站和当前 L3 不是同一个链接，则进行溯源判定
                if base_url and base_url != url:
                    logger.info(f"🔍 触发溯源：L3 子库 [{url}] 提取母站 -> [{base_url}]")
                    
                    # 检查母站是否已经在记忆中（防止重复查大模型浪费 Token）
                    base_past_record = self.memory.consult_past_experience(base_url)
                    
                    if not base_past_record:
                        # 用大模型鉴定母站级别（不需要深入抓取 content，仅判断架构）
                        base_report = self.validator.validate_dataset_link(
                            url=base_url, title="", description="", page_content="", user_query=task.get("user_query", "")
                        )
                        base_level = base_report.get('level', 'UNKNOWN')
                        
                        # 记录母站鉴定结果入库
                        if self.memory:
                            self.memory.memorize_audit_result(base_report)
                    else:
                        base_level = base_past_record.get('level', 'UNKNOWN') if isinstance(base_past_record, dict) else getattr(base_past_record, 'level', 'UNKNOWN')

                    logger.info(f"🏛️ 母站 [{base_url}] 级别判定为: {base_level}")

                    # 🎯 如果母站是 L2，加入待深挖队列！
                    if base_level == "L2":
                        self.state.add_to_remine_queue(base_url)
            # ==========================================

            return {
                "task_id": task["task_id"],
                "url": url,
                "report": report
            }

        except Exception as e:
            logger.error(f"Audit failed for {url}: {str(e)}")
            return {
                "task_id": task["task_id"],
                "url": url,
                "report": {"status": "ERROR", "level": "Error", "analysis": str(e), "metrics": {"ai_score": 0}}
            }