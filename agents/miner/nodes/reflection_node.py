import sys
import os
import json
import time
from typing import Dict, Any, Optional
from loguru import logger

current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.abspath(os.path.join(current_dir, "../../../"))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

try:
    from agents.miner.llms.miner_llm import MinerLLMClient
    from agents.miner.state.miner_state import MinerState
except ImportError:
    pass

class ReflectionNode:
    """
    ReflectionNode (纯拓扑防卡死雷达版)
    🌟 核心逻辑：只管 DFS 是否陷入循环，绝不干涉语义。正常死链给予中性评分以保护顶级域名。
    """
    def __init__(self):
        self.llm = MinerLLMClient()
        logger.info("🪞 ReflectionNode 初始化完成 (纯拓扑防卡死雷达模式就绪)")

    @staticmethod
    def _clip(v: float, low: float, high: float) -> float:
        return max(low, min(high, float(v)))

    @staticmethod
    def _safe_float(v: Any, default: float = 0.0) -> float:
        try:
            return float(v)
        except Exception:
            return float(default)

    def _calibrate_quality_score(
        self,
        reflection: Dict[str, Any],
        clean_action: str,
        topology_state: str,
        is_denied: bool,
        structured_data: Dict[str, Any],
        candidate_assets_count: int,
        explore_targets_count: int,
    ) -> float:
        """
        对 LLM 给出的 quality_score 做工程校准，避免评分长期饱和在 0.9。
        """
        raw = self._clip(self._safe_float(reflection.get("quality_score", 0.6), 0.6), 0.0, 1.0)
        topology_score = self._clip(self._safe_float(structured_data.get("topology_score", 0.5), 0.5), 0.0, 1.0)
        signal_density = self._clip((candidate_assets_count + 0.5 * explore_targets_count) / 20.0, 0.0, 1.0)

        # 压缩原始评分振幅，降低“恒高分”倾向
        compressed_raw = 0.5 + (raw - 0.5) * 0.45
        blended = 0.50 * compressed_raw + 0.35 * topology_score + 0.15 * signal_density

        if "loop" in topology_state or "trap" in topology_state:
            return 0.10
        if is_denied:
            return round(self._clip(blended, 0.25, 0.45), 3)
        if clean_action == "stop":
            stop_score = 0.30 + 0.40 * topology_score + 0.15 * signal_density
            return round(self._clip(stop_score, 0.25, 0.62), 3)

        # explore / deepen：允许较高分，但设置上限 0.85 防止过饱和
        boost = 0.06 if clean_action == "deepen" else 0.0
        return round(self._clip(blended + boost, 0.45, 0.85), 3)

    async def execute(self, state: MinerState) -> MinerState:
        logger.info(f"🧠 ReflectionNode 开始反思拓扑效率: {state.current_url}")

        raw_links = getattr(state, "raw_links", [])
        is_denied = getattr(state, "is_access_denied", False)
        
        try:
            dynamic_alert = getattr(state, "error_message", None)
            system_prompt = self._build_system_prompt()
            user_prompt = self._build_reflection_prompt(state, dynamic_alert, raw_links, is_denied)

            reflection = await self.llm.ainvoke_json(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                temperature=0.1, 
            )

            if not reflection:
                logger.warning("⚠️ ReflectionNode 未生成有效反思结果，使用默认值")
                reflection = {"topology_state": "DeadEnd", "dfs_action": "stop", "quality_score": 0.5}

            raw_action = str(reflection.get("dfs_action", "stop")).lower()
            topology_state = str(reflection.get("topology_state", "DeadEnd")).lower()
            
            clean_action = "stop"
            if "explore" in raw_action: clean_action = "explore"
            elif "deepen" in raw_action: clean_action = "deepen"

            # 初始化防御性 DNA
            if "distilled_dna" not in reflection:
                reflection["distilled_dna"] = {"new_blacklist_keywords": [], "logic_correction": ""}

            structured_data = getattr(state, "structured_data", {})
            explore_targets = structured_data.get("exploration_targets", []) or []
            candidate_assets = structured_data.get("candidate_assets", []) or []

            # 🌟 [终极护栏]：基于拓扑状态的动态评分与黑名单管控
            if is_denied:
                logger.info(f"🛡️ 探测到高墙限制 ({state.current_url})，停止深挖。给予中性评分保护域名。")
                clean_action = "stop"
                reflection["distilled_dna"]["new_blacklist_keywords"] = []
                
            elif "loop" in topology_state or "trap" in topology_state:
                logger.error(f"🚫 确认为爬虫陷阱或无限循环！准备熔断并记录特征！")
                clean_action = "stop"
                
            elif clean_action == "stop":
                logger.info(f"🛑 拓扑分支正常到达尽头 (单页/死链/文档)，安全回溯。")
                reflection["distilled_dna"]["new_blacklist_keywords"] = [] # 正常死胡同绝不提取黑名单

            # 统一评分校准（去饱和）
            state.quality_score = self._calibrate_quality_score(
                reflection=reflection,
                clean_action=clean_action,
                topology_state=topology_state,
                is_denied=is_denied,
                structured_data=structured_data,
                candidate_assets_count=len(candidate_assets),
                explore_targets_count=len(explore_targets),
            )

            reflection["dfs_action"] = clean_action
            state.reflection_result = reflection

            logger.success(f"✅ ReflectionNode 审计完成 | 拓扑健康度: {state.quality_score} | 建议操作: {clean_action}")
            return state

        except Exception as e:
            logger.error(f"❌ ReflectionNode 执行失败: {e}")
            state.reflection_result = {}
            state.quality_score = 0.5 # 异常时也给中性分，保护域名
            return state

    def _build_system_prompt(self) -> str:
        from utils.miner_prompts import append_to_prompt
        base = """你是一个“DFS 爬虫防卡死雷达”。
你的唯一任务是观察当前页面的链接结构，判断爬虫是否陷入了无限循环（如无限日历翻页）、遇到了物理死胡同（如单篇文档、404报错），还是找到了宽广的数据目录。

### 🚨 拓扑状态与动作标准
1. **Healthy (健康导航)**：发现大量指向子目录或数据资产的链接。 -> 动作: `explore` / `deepen`
2. **DeadEnd (正常尽头)**：这是一篇没有下钻链接的文章、一个直接的 PDF/CSV 链接，或者 404 错误页。 -> 动作: `stop` (这很正常，不需要惩罚)
3. **InfiniteLoop (爬虫陷阱)**：页面充斥着互相跳转的无效链接、无限的按月/按日翻页组件。 -> 动作: `stop` (这是危险的，需要惩罚)

### 🎚️ 评分标尺（避免恒高）
- 0.1~0.3: 明确陷阱/高度无效结构
- 0.4~0.6: 普通页面或正常尽头
- 0.7~0.85: 明显可继续下钻的目录/资产入口
- 除非证据极强，不要给 0.9 以上

### 📤 输出格式 (必须是严格的 JSON)
{
    "topology_state": "Healthy | DeadEnd | InfiniteLoop",
    "dfs_action": "explore | deepen | stop",
    "quality_score": 0.8, 
    "distilled_dna": {
        "new_blacklist_keywords": ["⚠️ 极度危险操作！只有在 topology_state 为 InfiniteLoop 时，才能提取导致循环的路径特征（如 '/calendar/', '?sort='）。只要是 DeadEnd 或 Healthy，这里必须是空列表 [] !!"],
        "logic_correction": "给爬虫引擎的简短防卡死建议"
    }
}
"""
        return append_to_prompt(base, "reflection_append")

    def _build_reflection_prompt(self, state: MinerState, dynamic_alert: Optional[str], raw_links: list, is_denied: bool) -> str:
        structured_data = getattr(state, "structured_data", {})
        explore_targets = structured_data.get("exploration_targets", [])
        candidate_assets = structured_data.get("candidate_assets", [])
        
        sample_links = raw_links[:20] if raw_links else ["暂无原始链接数据，请基于当前 URL 推断"]

        prompt = f"""
【拓扑结构快照】
- 当前扫描 URL: {state.current_url}
- 遭遇防爬虫/权限拦截: {"是" if is_denied else "否"}
- StructureNode 判定的页面类型: {structured_data.get('page_type', 'Unknown')}
- 提取到的潜在资产终点数: {len(candidate_assets)}
- 提取到的有效下钻目录数: {len(explore_targets)}
"""
        
        if dynamic_alert:
            prompt += f"\n🚨 **爬虫网络异常告警**: \n{dynamic_alert}\n"

        prompt += f"""
【页面原始链接样本分析 (最多 20 条)】
{json.dumps(sample_links, ensure_ascii=False, indent=2)}

请基于纯物理拓扑进行评估：
1. 爬虫现在卡在无限翻页的循环陷阱里了吗？(如果是，设定为 InfiniteLoop)
2. 爬虫是正常撞到了分支的尽头 (如独立文档、新闻底层页、网络 404) 吗？(如果是，设定为 DeadEnd，绝不提取黑名单)
3. 还是这里大有可为？(如果是，设定为 Healthy)
"""
        return prompt.strip()
