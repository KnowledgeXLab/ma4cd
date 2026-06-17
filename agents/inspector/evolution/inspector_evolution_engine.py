from __future__ import annotations
import os
import json
import re
import time
import random
import hashlib
from typing import Dict, Any, List, Optional, TYPE_CHECKING, Tuple
from loguru import logger

from agents.inspector.memory.managers.memory_manager import InspectorMemoryManager

# 🚀 尝试导入大模型客户端，赋予引擎真正的“大脑”
try:
    from agents.inspector.llms.inspector_llm import InspectorLLM
except ImportError:
    InspectorLLM = None
    logger.warning("⚠️ 未找到 InspectorLLM，进化引擎将降级为纯逻辑规则模式。")


class InspectorEvolutionEngine:
    """
    🧬 Inspector 智能进化引擎 (LLM Reflection 版 - 深度信任大模型)
    
    核心职能：
    1. 【生存适应】: 捕获底层错误 (如 400 频控)，硬逻辑保护系统。
    2. 【语义反思】: 接入大模型，深度分析被拒绝的数据，总结垃圾特征。
    3. 【红线防御】: 依赖 LLM 思维链保护 L4 实体资产，杜绝硬编码误杀。
    4. 【经验沉淀】: 将进化后的参数持久化到 DNA 记忆中。
    """

    # 🛡️ 仅保留最基础的技术后缀保护，防止大模型幻觉导致爬虫网络请求瘫痪
    # 所有语义级别的保护全部移交大模型 Prompt 控制
    GENERAL_PROTECTED_EXTENSIONS = {'.html', '.htm', '.php', '.asp', '.aspx', '.jsp', '.xml'}

    def __init__(self, memory_manager: InspectorMemoryManager):
        self.memory_manager = memory_manager
        self.current_config = self.memory_manager.get_current_config()
        self.generation = getattr(self.memory_manager, 'dna', {}).get("generation", 0)
        
        # 🚀 实例化 LLM 大脑
        self.llm = InspectorLLM() if InspectorLLM else None
        
        logger.info(f"🧠 InspectorEvolutionEngine (LLM驱动版) 觉醒 | 当前代数: Gen {self.generation}")

    def _get_default_config(self) -> dict:
        return {
            'generation': 0,
            'min_confidence': 0.6,
            'batch_size': 20,
            'strict_mode': False,
            'banned_extensions': ['.css', '.js', '.png', '.jpg', '.ico', '.woff'],
            'banned_keywords': ['login', 'signin', 'subscribe', 'cart'],
            'task_profiles': {},
            'user_override_rules': ""
        }

    def _llm_reflect_on_garbage(
        self,
        rejected_items: List[Dict],
        passed_items: Optional[List[Dict]] = None,
        mission_context: Optional[Dict[str, Any]] = None
    ) -> Dict:
        """
        🧠 核心大模型反思逻辑：分析任务语义 + 正负样本，提取“任务-线索相关性”规律。
        """
        if not self.llm or not rejected_items:
            return {}

        mission_context = mission_context or {}
        passed_items = passed_items or []

        # 采样最多 10 条拒绝 + 5 条通过，防止 Token 爆炸
        reject_size = min(10, len(rejected_items))
        pass_size = min(5, len(passed_items))
        reject_samples = random.sample(rejected_items, reject_size) if reject_size > 0 else []
        pass_samples = random.sample(passed_items, pass_size) if pass_size > 0 else []

        clean_rejected_samples = [
            {
                "url": i.get("url"),
                "title": i.get("title", ""),
                "reason": i.get("reason", ""),
            }
            for i in reject_samples
        ]
        clean_passed_samples = [
            {
                "url": i.get("url"),
                "title": i.get("title", ""),
                "inspector_reason": i.get("inspector_reason", i.get("reason", "")),
                "level": i.get("level", ""),
            }
            for i in pass_samples
        ]

        human_request = str(mission_context.get("human_request", "")).strip()
        commander_intent = str(mission_context.get("commander_core_intent", "")).strip()
        specific_targets = mission_context.get("specific_targets", [])

        # 🔥 核心重构：注入 MA4CD 全局视野，下达强力 L4 保护指令与强制思维链
        prompt = f"""
        你现在是数据审计系统的“全局进化反思大脑” (Evolutionary Reflection Engine)。
        我们的系统致力于挖掘全球高价值数据线索，分为四个同等重要的层级：
        - L1/L2: 大型数字枢纽与数据门户
        - L3: 独立的在线数字数据库
        - L4: 物理/私有资产线索 (Physical Assets) —— 极度珍贵！包括实体档案馆藏、历史观测记录、未数字化手稿、需要发邮件联系获取的私有数据。

        【当前任务语义】
        - Human Request: {human_request}
        - Commander Core Intent: {commander_intent}
        - Specific Targets: {json.dumps(specific_targets, ensure_ascii=False)}

        以下是上一轮质量审计中被系统【拒绝淘汰】的 {reject_size} 个样本：
        {json.dumps(clean_rejected_samples, ensure_ascii=False, indent=2)}

        以下是上一轮被系统【通过入库】的 {pass_size} 个样本（用于对比相关性）：
        {json.dumps(clean_passed_samples, ensure_ascii=False, indent=2)}

        请你深度思考：在上述任务语义下，哪些拒绝样本是“任务无关噪声”，哪些是“可能被误拒”的相关线索？
        请基于任务-线索配对关系提取建议，输出必须“任务作用域(task-scoped)”。

        ⚠️【致命红线：L4 保护指令 (The L4 Protection Directive)】⚠️：
        你提取的黑名单关键词，绝对不能包含任何可能指向 L4 物理资产或获取门槛的词汇！
        例如：严禁将 `archive`, `history`, `collection`, `finding-aid`, `manuscript`, `contact`, `about` 等词汇列入黑名单。一旦封杀这些词，系统将彻底对真实世界的物理数据致盲！
        你的目标是提取真正的“无效噪音”，例如：表单操作(login, register)、商业行为(cart, pricing)、纯技术接口(api-docs)、或法律免责声明(privacy, terms)等。
        
        请严格以 JSON 格式输出，必须包含你的逻辑思考过程：
        {{
            "reflection_summary": "对本次垃圾数据的共性总结（不超过100字）",
            "thought_process": "思维链：仔细审查你准备加入黑名单的词汇，论证它们是否会误伤 L4 实体/档案馆藏资源？如果会，必须剔除。",
            "task_relevance_observation": "任务相关性判断摘要（包含可能误拒线索类型）",
            "new_banned_keywords": ["发现的纯粹业务噪音词1", "噪音词2"],
            "new_banned_extensions": [".发现的无用后缀"],
            "suggested_threshold_delta": 0.0
        }}
        """
        
        try:
            logger.info("🧠 正在请求 LLM 对淘汰数据进行深度反思与 DNA 蒸馏...")
            if hasattr(self.llm, "invoke_json"):
                result = self.llm.invoke_json(prompt, system_message="你是系统全局进化反思专家")
            else:
                result = self.llm.invoke(prompt, require_json=True)
            return result if isinstance(result, dict) else {}
        except Exception as e:
            logger.warning(f"⚠️ LLM 反思失败: {e}")
            return {}

    @staticmethod
    def _extract_reason_code(reason: str) -> str:
        raw = str(reason or "").strip()
        if not raw:
            return "UNKNOWN"
        m = re.match(r"^\[(.*?)\]", raw)
        token = m.group(1).strip() if m else raw.split(":", 1)[0].strip()
        token = re.sub(r"\s+", "_", token)
        token = re.sub(r"[^\w\u4e00-\u9fff]+", "_", token).strip("_")
        return token[:64] if token else "UNKNOWN"

    @staticmethod
    def _reason_error_type(item: Dict[str, Any]) -> str:
        reason = str(item.get("reason", "")).lower()
        if item.get("_exclude_from_evolution"):
            return "INFRA_TRANSIENT"
        if any(k in reason for k in ["基础设施异常", "timeout", "timed out", "connection", "bad gateway", "502", "503", "504"]):
            return "INFRA_TRANSIENT"
        if any(k in reason for k in ["topic mismatch", "not relevant", "unrelated", "跨领域", "主题不符"]):
            return "TOPIC_MISMATCH"
        if any(k in reason for k in ["硬约束", "llm复核拦截", "高准确率拦截", "规则拦截"]):
            return "RULE_OR_REVIEW_BLOCK"
        if any(k in reason for k in ["pre-filter", "banned extension", "banned keyword", "match evolved banned keyword"]):
            return "PREFILTER_BLOCK"
        return "OTHER"

    @staticmethod
    def _mission_keywords(mission_context: Dict[str, Any]) -> List[str]:
        targets = mission_context.get("specific_targets", [])
        if isinstance(targets, list):
            target_text = " ".join([str(t) for t in targets if str(t).strip()])
        else:
            target_text = str(targets or "")
        raw = " ".join([
            str(mission_context.get("human_request", "") or ""),
            str(mission_context.get("commander_core_intent", "") or ""),
            target_text
        ]).lower()
        tokens = re.findall(r"[\u4e00-\u9fff]{2,}|[a-z0-9][a-z0-9_\-]{2,}", raw)
        stop = {
            "please", "around", "related", "about", "with", "for", "the", "and", "that",
            "this", "from", "into", "through", "mission", "request", "core", "intent",
            "target", "targets", "data", "dataset", "线索", "相关", "方向", "任务", "围绕", "挖掘"
        }
        dedup: List[str] = []
        seen = set()
        for t in tokens:
            if t in stop:
                continue
            if t not in seen:
                seen.add(t)
                dedup.append(t)
        return dedup[:40]

    @staticmethod
    def _item_text(item: Dict[str, Any]) -> str:
        return " ".join([
            str(item.get("url", "") or ""),
            str(item.get("title", "") or ""),
            str(item.get("reason", "") or ""),
            str(item.get("inspector_reason", "") or ""),
            str(item.get("snippet", "") or ""),
        ]).lower()

    @classmethod
    def _is_task_aligned(cls, item: Dict[str, Any], task_keywords: List[str]) -> bool:
        if not task_keywords:
            return True
        text = cls._item_text(item)
        return any(k in text for k in task_keywords)

    def _compute_relevance_diagnostics(
        self,
        mission_context: Dict[str, Any],
        passed_items: List[Dict[str, Any]],
        rejected_items: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        task_keywords = self._mission_keywords(mission_context)
        tp_like = fp_like = tn_like = fn_like = 0
        reason_code_stats: Dict[str, int] = {}
        error_type_stats: Dict[str, int] = {}

        for item in passed_items or []:
            aligned = self._is_task_aligned(item, task_keywords)
            if aligned:
                tp_like += 1
            else:
                fp_like += 1

        for item in rejected_items or []:
            aligned = self._is_task_aligned(item, task_keywords)
            if aligned:
                fn_like += 1
            else:
                tn_like += 1
            code = self._extract_reason_code(str(item.get("reason", "")))
            reason_code_stats[code] = reason_code_stats.get(code, 0) + 1
            err_t = self._reason_error_type(item)
            error_type_stats[err_t] = error_type_stats.get(err_t, 0) + 1

        total = tp_like + fp_like + tn_like + fn_like
        relevance_consistency = (tp_like + tn_like) / total if total > 0 else 0.0
        false_accept_rate = fp_like / (tp_like + fp_like) if (tp_like + fp_like) > 0 else 0.0
        false_reject_rate = fn_like / (tn_like + fn_like) if (tn_like + fn_like) > 0 else 0.0
        dominant_error_type = ""
        if error_type_stats:
            dominant_error_type = max(error_type_stats.items(), key=lambda kv: kv[1])[0]

        return {
            "task_keywords_count": len(task_keywords),
            "task_keywords": task_keywords,
            "tp_like": tp_like,
            "fp_like": fp_like,
            "tn_like": tn_like,
            "fn_like": fn_like,
            "relevance_consistency_rate": round(relevance_consistency, 4),
            "false_accept_rate": round(false_accept_rate, 4),
            "false_reject_rate": round(false_reject_rate, 4),
            "reason_code_stats": reason_code_stats,
            "error_type_stats": error_type_stats,
            "dominant_error_type": dominant_error_type,
        }

    @staticmethod
    def _normalize_mission_context(mission_context: Any) -> Dict[str, Any]:
        if isinstance(mission_context, dict):
            normalized = dict(mission_context)
            targets = normalized.get("specific_targets", [])
            if not isinstance(targets, list):
                targets = [targets] if targets else []
            normalized["specific_targets"] = targets
            return normalized
        text = str(mission_context or "").strip()
        if not text:
            return {}
        return {"human_request": text}

    @staticmethod
    def _task_fingerprint(mission_context: Dict[str, Any]) -> str:
        human = str(mission_context.get("human_request", "")).strip().lower()
        core = str(mission_context.get("commander_core_intent", "")).strip().lower()
        targets = mission_context.get("specific_targets", [])
        target_text = ",".join(sorted([str(t).strip().lower() for t in targets if str(t).strip()]))
        raw = f"{human}|{core}|{target_text}"
        if not raw.strip("|"):
            return ""
        return hashlib.md5(raw.encode("utf-8")).hexdigest()[:16]

    @staticmethod
    def _dedup_keep_order(values: List[str]) -> List[str]:
        out: List[str] = []
        seen = set()
        for v in values or []:
            s = str(v).strip()
            if not s:
                continue
            if s in seen:
                continue
            seen.add(s)
            out.append(s)
        return out

    def _ensure_task_profile(
        self,
        config: Dict[str, Any],
        mission_context: Dict[str, Any]
    ) -> Tuple[str, Optional[Dict[str, Any]]]:
        fp = self._task_fingerprint(mission_context)
        if not fp:
            return "", None
        profiles = config.setdefault("task_profiles", {})
        profile = profiles.get(fp)
        if not isinstance(profile, dict):
            profile = {
                "min_confidence": float(config.get("min_confidence", 0.6)),
                "banned_keywords": [],
                "banned_extensions": [],
                "last_updated": time.time(),
                "human_request": str(mission_context.get("human_request", "")).strip(),
            }
            profiles[fp] = profile
        profile.setdefault("banned_keywords", [])
        profile.setdefault("banned_extensions", [])
        profile.setdefault("min_confidence", float(config.get("min_confidence", 0.6)))
        profile["last_updated"] = time.time()
        return fp, profile

    def get_runtime_config(self, mission_context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        运行时配置视图：
        - 全局基线配置 + 任务 profile 局部覆盖
        - 任务级黑名单只在当前任务生效，不污染全局基因
        """
        try:
            base = json.loads(json.dumps(self.current_config))
        except Exception:
            base = dict(self.current_config)

        base.setdefault("banned_keywords", [])
        base.setdefault("banned_extensions", [])
        base.setdefault("task_profiles", {})

        mission_context = self._normalize_mission_context(mission_context)
        fp = self._task_fingerprint(mission_context)
        profile = None
        if fp:
            profile = base.get("task_profiles", {}).get(fp)

        if isinstance(profile, dict):
            merged_kws = self._dedup_keep_order(
                list(base.get("banned_keywords", [])) + list(profile.get("banned_keywords", []))
            )
            merged_exts = self._dedup_keep_order(
                list(base.get("banned_extensions", [])) + list(profile.get("banned_extensions", []))
            )
            base["banned_keywords"] = merged_kws
            base["banned_extensions"] = merged_exts
            try:
                base["min_confidence"] = float(profile.get("min_confidence", base.get("min_confidence", 0.6)))
            except Exception:
                pass
            base["task_fingerprint"] = fp
            base["task_scope_applied"] = True
        else:
            base["task_fingerprint"] = fp
            base["task_scope_applied"] = False

        return base

    def _build_task_result_snapshot(
        self,
        mission_context: Dict[str, Any],
        metrics: Dict[str, Any],
        passed_items: List[Dict[str, Any]],
        rejected_items: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        total_reviewed = int(metrics.get("total_reviewed", 0))
        pass_count = int(metrics.get("pass_count", 0))
        reject_count = int(metrics.get("reject_count", 0))
        pass_rate = float(pass_count / total_reviewed) if total_reviewed > 0 else 0.0
        avg_topology_pass = 0.0
        pass_topology_scores = [
            float(i.get("topology_score", 0.0))
            for i in (passed_items or [])
            if isinstance(i, dict)
        ]
        if pass_topology_scores:
            avg_topology_pass = sum(pass_topology_scores) / len(pass_topology_scores)

        relevance_diag = self._compute_relevance_diagnostics(
            mission_context=mission_context,
            passed_items=passed_items or [],
            rejected_items=rejected_items or []
        )

        return {
            "timestamp": time.time(),
            "task_fingerprint": self._task_fingerprint(mission_context),
            "human_request": str(mission_context.get("human_request", "")).strip(),
            "commander_core_intent": str(mission_context.get("commander_core_intent", "")).strip(),
            "specific_targets": mission_context.get("specific_targets", []),
            "total_reviewed": total_reviewed,
            "pass_count": pass_count,
            "reject_count": reject_count,
            "pass_rate": round(pass_rate, 4),
            "cleanup_rate": float(metrics.get("cleanup_rate", 0.0)),
            "avg_topology_score_passed": round(avg_topology_pass, 4),
            "task_relevance_consistency": float(relevance_diag.get("relevance_consistency_rate", 0.0)),
            "false_accept_rate": float(relevance_diag.get("false_accept_rate", 0.0)),
            "false_reject_rate": float(relevance_diag.get("false_reject_rate", 0.0)),
            "dominant_error_type": relevance_diag.get("dominant_error_type", ""),
            "reason_code_stats": relevance_diag.get("reason_code_stats", {}),
            "error_type_stats": relevance_diag.get("error_type_stats", {}),
        }

    def evolve(self, 
               human_feedback: str = "", 
               error_log: str = "", 
               metrics: Dict = None,
               rejected_items: List[Dict] = None,
               passed_items: List[Dict] = None,
               mission_context: Optional[Dict[str, Any]] = None) -> Dict:
        """
        🔥 进化主逻辑 (融合了硬逻辑防御 + LLM语义反思)
        """
        try:
            next_config = json.loads(json.dumps(self.current_config))
        except Exception:
            next_config = self.current_config.copy()

        metrics = metrics or {}
        rejected_items = rejected_items or []
        passed_items = passed_items or []
        mission_context = self._normalize_mission_context(mission_context)
        task_fp, task_profile = self._ensure_task_profile(next_config, mission_context)
        mutation_reasons = []

        # =========================================================
        # 🛡️ 路径 A: 硬逻辑防御 (底层系统保护，LLM无法干预)
        # =========================================================
        if error_log:
            error_lower = error_log.lower()
            if "400" in error_lower or "content_filter" in error_lower or "too many requests" in error_lower:
                old_batch = next_config.get("batch_size", 20)
                new_batch = max(1, int(old_batch / 2))
                if new_batch != old_batch:
                    next_config["batch_size"] = new_batch
                    mutation_reasons.append(f"触发风控/限流，Batch降级: {old_batch}->{new_batch}")

        # =========================================================
        # 🧠 路径 B: LLM 自我反思与规律提取
        # =========================================================
        if rejected_items and len(rejected_items) > 0:
            reflection_result = self._llm_reflect_on_garbage(
                rejected_items=rejected_items,
                passed_items=passed_items,
                mission_context=mission_context
            )
            
            if reflection_result:
                summary = reflection_result.get("reflection_summary", "")
                thought = reflection_result.get("thought_process", "")
                relevance_observation = reflection_result.get("task_relevance_observation", "")
                
                if summary: logger.info(f"🪞 Inspector 反思感悟: {summary}")
                if thought: logger.debug(f"🤔 Inspector 思维链: {thought}")
                if relevance_observation: logger.info(f"🎯 Inspector 任务相关性观察: {relevance_observation}")
                
                target_exts = (
                    task_profile.setdefault("banned_extensions", [])
                    if isinstance(task_profile, dict)
                    else next_config.setdefault("banned_extensions", [])
                )

                target_kws = (
                    task_profile.setdefault("banned_keywords", [])
                    if isinstance(task_profile, dict)
                    else next_config.setdefault("banned_keywords", [])
                )

                scope_tag = f"task:{task_fp}" if task_fp else "global"

                # 吸收新后缀（默认任务作用域；若无任务上下文才退回全局）
                new_exts = reflection_result.get("new_banned_extensions", [])
                if new_exts:
                    current_exts = set([str(e).strip() for e in target_exts if str(e).strip()])
                    added_exts = [
                        str(e).strip() for e in new_exts
                        if str(e).strip()
                        and str(e).strip() not in current_exts
                        and str(e).strip().lower() not in self.GENERAL_PROTECTED_EXTENSIONS
                    ]
                    if added_exts:
                        target_exts.extend(added_exts)
                        mutation_reasons.append(f"[{scope_tag}] LLM提取新禁忌后缀: {added_exts}")
                    elif new_exts:
                        logger.debug(f"🛡️ 拒绝了 LLM 提议的危险后缀: {new_exts}")

                # 吸收新关键词（默认任务作用域；若无任务上下文才退回全局）
                new_kws = reflection_result.get("new_banned_keywords", [])
                if new_kws:
                    current_kws = set([str(k).strip() for k in target_kws if str(k).strip()])
                    added_kws = [
                        str(k).strip() for k in new_kws
                        if str(k).strip() and str(k).strip() not in current_kws
                    ]
                    if added_kws:
                        target_kws.extend(added_kws)
                        mutation_reasons.append(f"[{scope_tag}] LLM提取新黑名单关键词: {added_kws}")
                
                # 动态调节阈值（任务作用域优先）
                delta = reflection_result.get("suggested_threshold_delta", 0.0)
                if delta != 0.0:
                    old_conf = float(
                        task_profile.get("min_confidence", next_config.get("min_confidence", 0.6))
                        if isinstance(task_profile, dict)
                        else next_config.get("min_confidence", 0.6)
                    )
                    new_conf = max(0.1, min(0.95, old_conf + float(delta)))
                    if isinstance(task_profile, dict):
                        task_profile["min_confidence"] = float(f"{new_conf:.2f}")
                    else:
                        next_config["min_confidence"] = float(f"{new_conf:.2f}")
                    mutation_reasons.append(f"[{scope_tag}] LLM微调阈值: {old_conf}->{new_conf}")

        # =========================================================
        # 📌 路径 B2: 任务-结果样本沉淀 + 结果驱动微调
        # =========================================================
        snapshot = self._build_task_result_snapshot(
            mission_context=mission_context,
            metrics=metrics,
            passed_items=passed_items,
            rejected_items=rejected_items
        )
        if snapshot.get("total_reviewed", 0) > 0:
            self.memory_manager.append_task_result_snapshot(snapshot)

            total_reviewed = int(snapshot.get("total_reviewed", 0))
            false_accept_rate = float(snapshot.get("false_accept_rate", 0.0))
            false_reject_rate = float(snapshot.get("false_reject_rate", 0.0))
            relevance_consistency = float(snapshot.get("task_relevance_consistency", 0.0))
            dominant_error_type = str(snapshot.get("dominant_error_type", "")).strip() or "UNKNOWN"
            reason_code_stats = snapshot.get("reason_code_stats", {}) or {}

            old_conf = float(
                task_profile.get("min_confidence", next_config.get("min_confidence", 0.6))
                if isinstance(task_profile, dict)
                else next_config.get("min_confidence", 0.6)
            )
            threshold_delta = 0.0

            # 核心：按“任务相关性一致率 + 误判类型”进行监督式微调
            if total_reviewed >= 20:
                if (false_accept_rate - false_reject_rate) > 0.15:
                    # 误接收偏高：提高阈值
                    threshold_delta = +0.03
                elif (false_reject_rate - false_accept_rate) > 0.15:
                    # 误拒绝偏高：降低阈值
                    threshold_delta = -0.03
                elif relevance_consistency < 0.55:
                    # 相关性一致率偏低，按主导误判类型做小幅校正
                    if dominant_error_type in {"TOPIC_MISMATCH", "OTHER"}:
                        threshold_delta = +0.01
                    elif dominant_error_type in {"RULE_OR_REVIEW_BLOCK", "PREFILTER_BLOCK"}:
                        threshold_delta = -0.01

            if abs(threshold_delta) > 1e-9:
                new_conf = max(0.1, min(0.95, old_conf + threshold_delta))
                if abs(new_conf - old_conf) >= 1e-6:
                    if isinstance(task_profile, dict):
                        task_profile["min_confidence"] = float(f"{new_conf:.2f}")
                    else:
                        next_config["min_confidence"] = float(f"{new_conf:.2f}")
                    scope_tag = f"task:{task_fp}" if task_fp else "global"
                    mutation_reasons.append(
                        f"[{scope_tag}] 相关性监督校正: min_confidence {old_conf}->{new_conf} "
                        f"(rel_consistency={relevance_consistency:.2f}, fa={false_accept_rate:.2f}, "
                        f"fr={false_reject_rate:.2f}, dominant_error={dominant_error_type}, "
                        f"reasons={reason_code_stats})"
                    )

        # =========================================================
        # 👤 路径 C: 人类指令覆盖 (最高优先级)
        # =========================================================
        if human_feedback:
            feedback_lower = human_feedback.lower()
            found_exts = re.findall(r'(\.[a-z0-9]{2,4})\b', feedback_lower)
            if found_exts:
                current_bans = set(next_config.get("banned_extensions", []))
                new_bans = [ext for ext in found_exts if ext not in current_bans]
                if new_bans:
                    next_config["banned_extensions"].extend(new_bans)
                    mutation_reasons.append(f"人类强制禁令: {new_bans}")
                    
            if len(human_feedback) > 10 and not found_exts:
                timestamp = time.strftime("%m-%d")
                rule = f"[{timestamp}] {human_feedback}"
                next_config["user_override_rules"] = (next_config.get("user_override_rules", "") + "\n" + rule).strip()
                mutation_reasons.append("注入人类长期规则")

        # =========================================================
        # 💾 执行突变与持久化
        # =========================================================
        if mutation_reasons:
            self.generation += 1
            reason_str = " | ".join(mutation_reasons)
            self.current_config = next_config
            self.memory_manager.evolve_dna(next_config, reason_str)
            logger.success(f"✅ Inspector 进化成功 (Gen {self.generation}): {reason_str}")
            return next_config
        
        logger.info("💤 环境稳定，Inspector 保持现有基因配置。")
        return self.current_config

    def get_config(self) -> Dict:
        return self.current_config
