import json
import os
from typing import Dict, Any, Optional, List, Set
from datetime import datetime

class InspectorState:
    """
    负责维护和持久化验证状态，并管理跨 Agent 协同的任务队列。
    防止重复检测相同的 URL，记录检测历史，并缓存需要下发给 Miner 的深挖任务。
    """

    def __init__(self, storage_path: str = "inspector_state.json"):
        self.storage_path = storage_path
        self._bound_session_id = "global"
        
        # 内存状态初始化
        self.reports: Dict[str, Any] = {}
        self.remine_queue: Set[str] = set() # 使用 set 天然去重
        
        # 加载历史状态
        self._load_state()

    def bind_session(self, session_id: Optional[str]) -> None:
        """File 模式兼容接口；remine 仍用全局 JSON 文件。"""
        if session_id:
            self._bound_session_id = session_id

    @property
    def session_id(self) -> str:
        return self._bound_session_id

    def _load_state(self):
        """从磁盘加载现有状态，并兼容旧版本数据结构"""
        if os.path.exists(self.storage_path):
            try:
                with open(self.storage_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    
                    # 兼容性检查：如果存在 'reports' 键，说明是新版结构
                    if "reports" in data or "remine_queue" in data:
                        self.reports = data.get("reports", {})
                        self.remine_queue = set(data.get("remine_queue", []))
                    else:
                        # 如果是旧版扁平结构，进行内存迁移
                        print("🔄 正在将旧版 Inspector State 迁移至新版结构...")
                        self.reports = data
                        self.remine_queue = set()
            except Exception as e:
                print(f"⚠️ Error loading state file: {e}")
                self.reports = {}
                self.remine_queue = set()
        else:
            self.reports = {}
            self.remine_queue = set()

    def save_state(self):
        """将当前状态 (报告 + 待挖队列) 保存到磁盘"""
        try:
            # 将 set 转换为 list 以便 JSON 序列化
            export_data = {
                "reports": self.reports,
                "remine_queue": list(self.remine_queue)
            }
            with open(self.storage_path, 'w', encoding='utf-8') as f:
                json.dump(export_data, f, indent=4, ensure_ascii=False)
        except Exception as e:
            print(f"⚠️ Error saving state file: {e}")

    def get_cached_result(self, url: str) -> Optional[Dict[str, Any]]:
        """检查该 URL 是否已经验证过"""
        return self.reports.get(url)

    def update_state(self, url: str, report: Dict[str, Any]):
        """
        更新验证结果。
        将 DataValidator 返回的 report 存入状态表。
        """
        self.reports[url] = {
            "status": report.get("status"),
            "score": report.get("metrics", {}).get("ai_score"),
            "risk_level": report.get("metrics", {}).get("risk_level"),
            "analysis": report.get("analysis"),
            "last_check": datetime.now().isoformat()
        }
        # 实时保存，防止崩溃丢失数据
        self.save_state()

    # ================= 新增：跨 Agent 协同队列管理 =================

    def add_to_remine_queue(self, l2_url: str):
        """
        将溯源发现的 L2 链接加入待深挖队列。
        """
        if l2_url not in self.remine_queue:
            self.remine_queue.add(l2_url)
            print(f"📥 [Inspector State] 已将 L2 溯源母站加入深挖队列: {l2_url}")
            self.save_state()

    def get_and_clear_remine_queue(self) -> List[str]:
        """
        获取当前所有需要被 Miner 重新挖掘的 L2 链接，并清空队列。
        供 Main Workflow 调度使用。
        """
        if not self.remine_queue:
            return []
            
        urls_to_mine = list(self.remine_queue)
        self.remine_queue.clear() # 提取后清空，避免下次重复派发
        self.save_state()
        print(f"📤 [Inspector State] 已释放 {len(urls_to_mine)} 个 L2 深挖任务给 Miner。")
        return urls_to_mine

    # ===============================================================

    def get_summary(self) -> Dict[str, int]:
        """获取当前验证统计摘要"""
        summary = {"PASS": 0, "FAIL": 0, "REVIEW": 0, "ERROR": 0}
        for item in self.reports.values():
            status = item.get("status", "ERROR")
            summary[status] = summary.get(status, 0) + 1
            
        # 也可以在 summary 里带上待挖队列的数量，方便监控
        summary["PENDING_L2_MINES"] = len(self.remine_queue)
        return summary