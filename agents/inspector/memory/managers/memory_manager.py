import os
import json
import time
from typing import Optional, List, Dict, Any
from loguru import logger

# 假设你的基础模型和存储类路径如下
from agents.inspector.memory.models.memory_models import AuditEntry, MemorySchema
from agents.inspector.memory.storage.persistent_memory import PersistentMemory

class InspectorMemoryManager:
    """
    🧠 Inspector 核心记忆管理器
    
    职责划分：
    1. 【Layer 2 - 审计历史】: 记录 URL 审计结果，用于去重和防重复劳动。
    2. 【Layer 3 - 进化基因】: 记录策略配置(DNA)、代数和进化日志，实现跨任务进化。
    """

    def __init__(self, root_path: str = "memory_data"):
        self.root_path = root_path
        os.makedirs(self.root_path, exist_ok=True)

        # 路径定义
        self.history_path = os.path.join(self.root_path, "inspector_history.json")
        self.dna_path = os.path.join(self.root_path, "inspector_dna.json")

        # 1. 初始化持久化存储（左脑：审计记录）
        self.history_storage = PersistentMemory(self.history_path)
        
        # 2. 加载进化基因（右脑：策略配置）
        self.dna = self._load_dna()
        
        logger.info(f"🧠 InspectorMemoryManager 初始化完成 | 当前代数: Gen {self.dna['generation']}")

    # =========================================================================
    # 🧬 Part 1: 进化基因管理 (Evolution DNA - Layer 3)
    # =========================================================================

    def _load_dna(self) -> Dict:
        """从磁盘加载 DNA 配置文件，若不存在则生成初始基因"""
        if os.path.exists(self.dna_path):
            try:
                with open(self.dna_path, 'r', encoding='utf-8') as f:
                    content = f.read()
                    if content.strip():
                        loaded = json.loads(content)
                        # 兼容老版本 DNA：补齐任务-结果进化必需字段
                        loaded.setdefault("task_result_history", [])
                        loaded.setdefault("task_outcome_index", {})
                        loaded.setdefault("last_task_fingerprint", "")
                        cfg = loaded.setdefault("config", {})
                        if not isinstance(cfg, dict):
                            cfg = {}
                            loaded["config"] = cfg
                        cfg.setdefault("task_profiles", {})
                        return loaded
            except Exception as e:
                logger.error(f"加载 DNA 失败: {e}")
        
        # 🌱 初始基因池
        return {
            "generation": 0,
            "last_updated": time.time(),
            "evolution_logs": ["Gen 0: System Initialization"],
            "task_result_history": [],
            "task_outcome_index": {},
            "last_task_fingerprint": "",
            "config": {
                "min_confidence": 0.6,
                "batch_size": 20,
                "strict_mode": False,
                "banned_extensions": [".css", ".js", ".png", ".jpg", ".ico", ".woff"],
                "banned_keywords": ["login", "signin", "subscribe"],
                "task_profiles": {},
                "user_override_rules": "" # 长期记忆的用户指令
            }
        }

    def get_current_config(self) -> Dict:
        """获取当前生效的配置基因"""
        return self.dna.get("config", {})

    def evolve_dna(self, new_config: Dict, reason: str):
        """
        🔥 持久化进化结果
        由 EvolutionEngine 调用，将计算出的新参数写入 DNA 记忆。
        """
        self.dna["generation"] += 1
        self.dna["last_updated"] = time.time()
        self.dna["config"] = new_config
        
        # 记录进化履历
        timestamp = time.strftime('%Y-%m-%d %H:%M:%S')
        log_entry = f"Gen {self.dna['generation']} [{timestamp}]: {reason}"
        self.dna.setdefault("evolution_logs", []).append(log_entry)
        
        self._save_dna()
        logger.success(f"💾 [Memory] 进化基因已固化至 DNA: {reason}")

    def _save_dna(self):
        """物理写入 DNA 文件"""
        try:
            with open(self.dna_path, 'w', encoding='utf-8') as f:
                json.dump(self.dna, f, indent=4, ensure_ascii=False)
        except Exception as e:
            logger.error(f"写入 DNA 文件失败: {e}")

    def append_task_result_snapshot(self, snapshot: Dict[str, Any], max_items: int = 200):
        """
        记录结构化“任务-结果”样本，用于后续 Inspector 进化。
        """
        if not isinstance(snapshot, dict) or not snapshot:
            return

        history = self.dna.setdefault("task_result_history", [])
        history.append(snapshot)
        if len(history) > max_items:
            self.dna["task_result_history"] = history[-max_items:]

        fp = str(snapshot.get("task_fingerprint", "")).strip()
        if fp:
            self.dna["last_task_fingerprint"] = fp
            index = self.dna.setdefault("task_outcome_index", {})
            stats = index.get(fp, {"runs": 0, "total_reviewed": 0, "total_passed": 0})
            stats["runs"] = int(stats.get("runs", 0)) + 1
            stats["total_reviewed"] = int(stats.get("total_reviewed", 0)) + int(snapshot.get("total_reviewed", 0))
            stats["total_passed"] = int(stats.get("total_passed", 0)) + int(snapshot.get("pass_count", 0))
            stats["last_precision"] = float(snapshot.get("pass_rate", 0.0))
            stats["last_updated"] = snapshot.get("timestamp", time.time())
            index[fp] = stats

        self.dna["last_updated"] = time.time()
        self._save_dna()

    # =========================================================================
    # 📝 Part 2: 审计历史管理 (Audit History - Layer 2)
    # =========================================================================

    def consult_past_experience(self, url: str) -> Optional[AuditEntry]:
        """查重：咨询过去的审计经验"""
        return self.history_storage.get_entry(url)

    def memorize_audit_result(self, report: dict):
        """记账：将新的审计结果转化为记忆碎片"""
        try:
            # 兼容性解析
            metrics = report.get('metrics', {})
            metadata = report.get('metadata', {})
            
            entry = AuditEntry(
                url=report.get('url'),
                title=metadata.get('title', 'Unknown'),
                status=report.get('status', 'ERROR'),
                score=float(metrics.get('ai_score', 0.0)),
                reason=report.get('analysis', 'No analysis provided'),
                metadata=metadata,
                timestamp=time.time()
            )
            # 存入底层历史库
            self.history_storage.update_entry(entry)
        except Exception as e:
            logger.warning(f"⚠️ 审计结果存入记忆失败: {e}")

    def get_recent_failures(self, limit: int = 50) -> List[AuditEntry]:
        """获取最近的失败案例，供自我反思逻辑使用"""
        all_entries = self.history_storage.get_all()
        failures = [e for e in all_entries if e.status == "FAIL"]
        return failures[-limit:]
