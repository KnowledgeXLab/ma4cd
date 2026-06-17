"""
Miner Agent 的核心状态类 (增强版)
优化特性：
1. 属性映射：解决 Node 节点访问 current_url 等字段的兼容性问题。
2. DFS 适配：支持 L3 独立子库拆分与 L4 影子资产信息存储。
3. 拓扑对齐：严格遵循《线索定义》分级标准。
4. 🚀 并发安全：新增 processing_urls 锁，彻底解决多路并发导致的重复挖掘穿透问题。
5. 🛡️ 异常熔断：新增域名级惩罚和软重试计数，防止死磕 403 防火墙和超时误杀。
"""

from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional, Set, TYPE_CHECKING
import time
from urllib.parse import urlparse

if TYPE_CHECKING:
    from agents.miner.memory.backends.base import CoordinationBackend

@dataclass
class MinerState:
    """
    Miner 的运行时状态
    - 兼容 ReAct 循环与 DFS 深度优先搜索逻辑
    - 支持自进化 DNA 记忆注入
    """

    # =========================================================================
    # 1. 核心数据字段 (存储层)
    # =========================================================================
    task: str = ""                              # 整体任务描述
    task_id: str = ""                           # 唯一任务 ID
    
    # 当前处理的线索
    current_clue: Dict[str, Any] = field(default_factory=dict)  # 包含 url, domain, tier 等
    
    # 待处理线索队列 (用于 DFS 压栈)
    pending_clues: List[Dict[str, Any]] = field(default_factory=list)

    # 提取与结构化数据
    extracted_content: str = ""                 # 网页全文内容
    raw_links: List[Dict[str, Any]] = field(default_factory=list)     # 原始链接池
    nav_links: List[Dict[str, Any]] = field(default_factory=list)     # 导航栏链接
    structured_data: Dict[str, Any] = field(default_factory=dict)     # 包含 l3_candidates, l4_clues 等
    metadata: Dict[str, Any] = field(default_factory=dict)            # 页面元数据 (Title, Desc)

    # 最终产出 (对齐 L1-L4 标准)
    mined_items: List[Dict[str, Any]] = field(default_factory=list)   # 存储已验证的 L3/L4 资产线索

    # 🧬 进化与反思相关
    reflection_result: Optional[Any] = None     # 反思节点输出
    quality_score: float = 0.5                 # 质量分 (0.0-1.0)
    reflection_duration: float = 0.0           # 反思耗时
    evolution_generation: int = 0              # 进化代数
    needs_human_review: bool = False           # 是否需要人工干预
    confidence_adjustments: Dict[str, float] = field(default_factory=dict) 
    classification_feedback: List[Dict[str, Any]] = field(default_factory=list)
    
    # 执行状态与性能监控
    is_valid: bool = False                      # 当前步骤成功标识
    error: Optional[str] = None                 # 错误追踪
    step_start_time: float = 0.0                # 计时器开始
    step_duration: float = 0.0                  # 节点耗时
    total_retries: int = 0                      # 整体任务重试计数
    split_count: int = 0                        # 子线索分裂计数

    # =========================================================================
    # 🚀 2. 新增：并发排他锁与异常熔断器 (Engineering Controls)
    # =========================================================================
    visited_urls: Set[str] = field(default_factory=set)       # 已完成挖掘的 URL 集合 (绝对去重)
    processing_urls: Set[str] = field(default_factory=set)    # 正在挖掘中的 URL 集合 (并发排他锁)
    
    domain_fail_counts: Dict[str, int] = field(default_factory=dict)  # 域名连续失败次数 {domain: count}
    url_retry_counts: Dict[str, int] = field(default_factory=dict)    # 单 URL 软重试次数 {url: count}
    MAX_DOMAIN_FAILS: int = 2   # 同一域名连续报错 2 次，触发域名级熔断
    MAX_URL_RETRIES: int = 3    # 单个 URL 允许的超时重试次数

    # Redis 协调层（可选）：多 worker 去重 / 锁
    coordination: Any = field(default=None, repr=False)
    session_id: str = field(default="")

    @staticmethod
    def _clean_url(url: str) -> str:
        return url.split('#')[0].rstrip('/')

    # =========================================================================
    # 🌟 3. 映射属性 (Property Layer)
    # =========================================================================

    @property
    def current_url(self) -> str:
        """解决 'MinerState' object has no attribute 'current_url' 的映射修复"""
        return self.current_clue.get("url", "")

    @property
    def current_domain(self) -> str:
        """快速获取当前域名"""
        domain = self.current_clue.get("domain")
        if not domain and self.current_url:
            try:
                domain = urlparse(self.current_url).netloc
            except:
                domain = "unknown"
        return domain or "unknown"

    @property
    def current_page_title(self) -> str:
        """获取页面标题 (优先从 Metadata 取)"""
        return self.metadata.get("title") or self.current_clue.get("title", "Unknown Page")

    @property
    def l4_shadow_count(self) -> int:
        """统计具有影子特征(Physical/Private)的线索数量"""
        return sum(1 for item in self.mined_items if item.get("level") == "L4")

    # =========================================================================
    # 4. 逻辑控制与锁机制方法
    # =========================================================================

    def acquire_processing_lock(self, url: str) -> bool:
        clean_url = self._clean_url(url)
        if self.coordination and self.session_id:
            if self.coordination.is_visited(self.session_id, clean_url):
                return False
            return self.coordination.try_acquire_processing(self.session_id, clean_url)
        if clean_url in self.visited_urls or clean_url in self.processing_urls:
            return False
        self.processing_urls.add(clean_url)
        return True

    def release_processing_lock(self, url: str, success: bool = True):
        clean_url = self._clean_url(url)
        if self.coordination and self.session_id:
            self.coordination.release_processing(self.session_id, clean_url)
            if success:
                self.coordination.mark_visited(self.session_id, clean_url)
            return
        if clean_url in self.processing_urls:
            self.processing_urls.remove(clean_url)
        if success:
            self.visited_urls.add(clean_url)

    def is_domain_banned(self, domain: str) -> bool:
        if not domain or domain == "unknown":
            return False
        if self.coordination and self.session_id:
            return self.coordination.get_domain_fail(self.session_id, domain) >= self.MAX_DOMAIN_FAILS
        return self.domain_fail_counts.get(domain, 0) >= self.MAX_DOMAIN_FAILS

    def record_domain_failure(self, domain: str):
        if not domain or domain == "unknown":
            return
        if self.coordination and self.session_id:
            self.coordination.incr_domain_fail(self.session_id, domain)
            return
        self.domain_fail_counts[domain] = self.domain_fail_counts.get(domain, 0) + 1

    def should_retry_url(self, url: str) -> bool:
        clean_url = self._clean_url(url)
        if self.coordination and self.session_id:
            current_retries = self.coordination.incr_url_retry(self.session_id, clean_url)
            return current_retries <= self.MAX_URL_RETRIES
        current_retries = self.url_retry_counts.get(clean_url, 0)
        if current_retries < self.MAX_URL_RETRIES:
            self.url_retry_counts[clean_url] = current_retries + 1
            return True
        return False

    def update_duration(self):
        """更新当前步骤耗时统计"""
        if self.step_start_time > 0:
            self.step_duration = time.time() - self.step_start_time
            self.step_start_time = 0.0

    def start_step(self):
        """初始化节点开始时间"""
        self.step_start_time = time.time()
        self.error = None
        self.is_valid = False

    def get_reflection_summary(self) -> Dict[str, Any]:
        """获取用于自进化引擎的摘要数据"""
        return {
            'quality_score': self.quality_score,
            'needs_human_review': self.needs_human_review,
            'evolution_generation': self.evolution_generation,
            'l4_found': self.l4_shadow_count
        }

    def to_dict(self) -> Dict[str, Any]:
        """序列化 state，包括计算出的影子资产信息"""
        data = {
            "task": self.task,
            "current_url": self.current_url, # 显式包含映射属性
            "current_clue": self.current_clue,
            "raw_links_count": len(self.raw_links),
            "mined_items_count": len(self.mined_items),
            "l4_shadow_count": self.l4_shadow_count,
            "quality_score": self.quality_score,
            "is_valid": self.is_valid,
            "error": self.error,
            "step_duration": self.step_duration,
            # 将 Set 转化为 List 以便正常 JSON 序列化
            "visited_urls_count": len(self.visited_urls),
            "processing_urls_count": len(self.processing_urls)
        }
        return data

    @classmethod
    def from_dict(cls, data: Dict[str, Any]):
        state = cls()
        for key, value in data.items():
            if hasattr(state, key) and key not in ["current_url", "visited_urls", "processing_urls"]:
                setattr(state, key, value)
        return state

    def copy_for_reflection(self):
        """为 ReflectionNode 创建深度克隆的数据快照"""
        reflection_state = MinerState()
        reflection_state.task = self.task
        reflection_state.current_clue = self.current_clue.copy() if self.current_clue else {}
        reflection_state.mined_items = [item.copy() for item in self.mined_items]
        reflection_state.structured_data = self.structured_data.copy()
        reflection_state.metadata = self.metadata.copy()
        reflection_state.evolution_generation = self.evolution_generation
        return reflection_state

    def merge_reflection_result(self, reflection_state):
        """将审计结果合并回主状态流"""
        if hasattr(reflection_state, 'reflection_result'):
            self.reflection_result = reflection_state.reflection_result
            self.quality_score = getattr(reflection_state, 'quality_score', 0.5)