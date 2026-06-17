import asyncio
import hashlib
import logging
import json
import os
import sys
import re
from urllib.parse import urlparse, urlunparse
from typing import Dict, Any, List, Optional, TypedDict
from dataclasses import dataclass
from concurrent.futures import ThreadPoolExecutor

# ==========================================
# 🔥 动态路径修复 
# ==========================================
current_file_path = os.path.abspath(__file__)
inspector_node_dir = os.path.dirname(current_file_path)
inspector_dir = os.path.dirname(inspector_node_dir)
agents_dir = os.path.dirname(inspector_dir)
project_root = os.path.dirname(agents_dir)

if project_root not in sys.path:
    sys.path.insert(0, project_root)

logger = logging.getLogger("inspector.nodes.quality_score")

try:
    from agents.inspector.llms.inspector_llm import InspectorLLM
    from agents.inspector.prompts.inspector_prompt import InspectorPrompt
    from agents.inspector.tools.data_validator import DataValidator
except ImportError as e_abs:
    logger.error(f"❌ 严重导入错误: {e_abs}")
    class InspectorLLM: 
        def invoke(self, *args, **kwargs): return {}
    class DataValidator: 
        def __init__(self, *args): pass
        def validate_dataset_link(self, **k): return {}

@dataclass
class ScoreResult:
    total_score: float
    is_passed: bool
    reason: str
    suggested_level: str
    content_type: str
    raw_report: Dict[str, Any]


def bucket_rejection_reason(reason: Any) -> str:
    from utils.rejection_buckets import bucket_rejection_reason as _skill_bucket
    return _skill_bucket(reason)


def summarize_rejections(rejected_items: List[Dict[str, Any]]) -> Dict[str, Any]:
    from utils.rejection_buckets import summarize_rejections as _skill_summarize
    return _skill_summarize(rejected_items)

class InspectorState(TypedDict):
    miner_output: Dict[str, Any]
    current_config: Dict[str, Any]
    audited_results: List[Dict]
    rejected_items: List[Dict]
    statistics: Dict[str, Any]
    user_query: Any
    # 🔥 [新增] 接收来自 agent.py 传入的持久化状态机
    shared_state: Any 

class URLRouterUtility:
    # 使用通用正则匹配无效虚拟路径：忽略大小写，匹配指定模式作为独立路径或前缀
    # 涵盖: 默认/index类, 语言类(en, zh等), 导航类(about, contact), 功能类(search)
    JUNK_PATH_PATTERN = re.compile(
        r'^/(home|index(\.[a-z]+)?|en(-[a-z]+)?|zh(-[a-z]+)?|about|contact|search)/?$', 
        re.IGNORECASE
    )

    @staticmethod
    def clean_junk_paths(url: str) -> str:
        """通用清洗无效虚拟链接，返回清洗后的 URL"""
        try:
            parsed = urlparse(url)
            path = parsed.path
            
            # 如果路径只包含这些无效词汇或 '/'
            if path == '/' or URLRouterUtility.JUNK_PATH_PATTERN.match(path):
                parsed = parsed._replace(path='') # 清空无效路径
                parsed = parsed._replace(query='') # 无效路径通常附带的参数也无用
                
            clean_url = urlunparse(parsed).rstrip('/')
            return clean_url if clean_url else url.rstrip('/')
        except Exception:
            return url.rstrip('/')

    @staticmethod
    def has_virtual_path(url: str) -> bool:
        """判断 URL (通常是清洗后) 是否还包含实质性的虚拟链接"""
        try:
            parsed = urlparse(url)
            # 如果有查询参数 (?id=123) 或者是实质性路径 (如 /missions, /dataset)
            path = parsed.path.strip('/')
            return bool(path or parsed.query)
        except:
            return False

    @staticmethod
    def extract_base_url(url: str) -> str:
        """提取纯净的根域名，用于溯源"""
        try:
            parsed = urlparse(url)
            return f"{parsed.scheme}://{parsed.netloc}"
        except:
            return url.rstrip('/')

    @staticmethod
    def is_root_url(url: str) -> bool:
        """根入口判断：仅 scheme + host，无 path/query/fragment"""
        try:
            parsed = urlparse(url)
            path = parsed.path.strip("/")
            return bool(parsed.scheme and parsed.netloc) and (not path) and (not parsed.query) and (not parsed.fragment)
        except Exception:
            return False


class TierGuard:
    """
    L1-L4 分级一致性约束：
    - 优先使用 LLM 显式证据字段
    - 仅保留最小结构约束，避免过度硬编码
    """
    BINARY_EXTS = (".pdf", ".csv", ".json", ".zip", ".gz", ".xlsx", ".xls", ".txt", ".xml")

    @staticmethod
    def _safe_float(v: Any, default: float = 0.0) -> float:
        try:
            return float(v)
        except Exception:
            return default

    @classmethod
    def has_binary_suffix(cls, url: str) -> bool:
        path = urlparse((url or "").lower()).path
        return any(path.endswith(ext) for ext in cls.BINARY_EXTS)

    @classmethod
    def llm_claims_database_entry(cls, report: Dict[str, Any], content_type: str) -> bool:
        evidence = report.get("evidence_signals", {}) if isinstance(report, dict) else {}
        if isinstance(evidence, dict) and evidence.get("is_database_entry_link") is True:
            return True
        return "sub_database" in str(content_type).lower() or "database" in str(content_type).lower()

    @classmethod
    def llm_claims_physical_asset(cls, report: Dict[str, Any], content_type: str) -> bool:
        evidence = report.get("evidence_signals", {}) if isinstance(report, dict) else {}
        if isinstance(evidence, dict) and evidence.get("is_physical_asset_evidence") is True:
            return cls._safe_float(evidence.get("physical_only_confidence", 0.0), 0.0) >= 0.5
        return "physical_asset" in str(content_type).lower()


class QualityScoringEngine:
    def __init__(self, llm, config: Dict[str, Any] = None):
        self.llm = llm
        self.config = config or {}
        
        try:
            min_conf = float(self.config.get("min_confidence", 0.6))
            self.validator = DataValidator(self.llm, score_threshold=min_conf)
            self.min_confidence = min_conf
        except Exception as e:
            logger.error(f"Validator init failed: {e}")
            self.validator = None
            self.min_confidence = float(self.config.get("min_confidence", 0.6))
            
        self.seen_hashes = set()
        max_workers = int(os.getenv("MA4CD_INSPECTOR_MAX_WORKERS", str(self.config.get("max_workers", 6))))
        self.executor = ThreadPoolExecutor(max_workers=max(1, max_workers))

    @staticmethod
    def _is_infra_transient_error(rep: Dict[str, Any]) -> bool:
        if not isinstance(rep, dict):
            return False
        text = " ".join([
            str(rep.get("error", "")),
            str(rep.get("analysis", "")),
            str(rep.get("intent_analysis", "")),
            str(rep.get("status", "")),
        ]).lower()
        markers = ["system_memory_overloaded", "bad gateway", "502", "503", "504", "timeout", "timed out", "connection"]
        return any(m in text for m in markers)

    def _compute_fingerprint(self, data: Dict[str, Any]) -> str:
        raw = f"{data.get('url', '').strip().lower()}"
        return hashlib.md5(raw.encode()).hexdigest()

    @staticmethod
    def _mission_text(user_query: Any) -> str:
        if isinstance(user_query, dict):
            human = str(user_query.get("human_request", "")).strip()
            core = str(user_query.get("commander_core_intent", "")).strip()
            targets = user_query.get("specific_targets", [])
            targets_text = ", ".join([str(t) for t in targets]) if isinstance(targets, list) else str(targets)
            parts = [
                f"Human Request: {human}" if human else "",
                f"Commander Core Intent: {core}" if core else "",
                f"Specific Targets: {targets_text}" if targets_text else ""
            ]
            return "\n".join([p for p in parts if p]).strip()
        return str(user_query or "").strip()

    @staticmethod
    def _safe_float(v: Any, default: float = 0.0) -> float:
        try:
            return float(v)
        except Exception:
            return default

    def _apply_miner_prior(self, item: Dict[str, Any], score: float) -> float:
        """
        Use miner topology priors as weak Bayesian hints.
        Miner is high-recall, so these priors nudge but never dominate relevance.
        """
        candidate_type = str(item.get("candidate_type", "")).strip().lower()
        topology_score = self._safe_float(item.get("topology_score", 0.5), 0.5)

        type_bias = {
            "asset_hint": 0.08,
            "entry": 0.00,
            "exploration_target": -0.08,
            "legacy_l3_candidate": 0.03,
            "legacy_l4_clue": 0.03
        }.get(candidate_type, 0.00)

        # topology_score in [0,1] contributes at most +/-0.1
        topo_bias = max(-0.10, min(0.10, (topology_score - 0.5) * 0.2))
        adjusted = score + type_bias + topo_bias
        return max(0.0, min(1.0, adjusted))

    def dynamic_pre_filter(self, item: Dict, user_query: Any = "") -> bool:
        """
        通用预过滤：
        - 结构质量闸门（噪声域/叶子页/任务不对齐）
        - 配置驱动过滤（由进化/反馈产生）
        """
        from agents.inspector.tools.quality_gates import prefilter_item

        ok, reason = prefilter_item(item, user_query=user_query)
        if not ok:
            item["_filter_reason"] = reason
            return False

        url = item.get("url", "").lower()
        title = item.get("title", "").lower()
        
        evolved_junk = self.config.get("banned_keywords", [])
        evolved_exts = self.config.get("banned_extensions", [])

        for word in evolved_junk:
            if not word: continue
            word_lower = word.lower()
            pattern = re.compile(rf'(/|\b|_|-){re.escape(word_lower)}(/|\b|_|-|\?|#|$)')
            if pattern.search(url) or pattern.search(title):
                item["_filter_reason"] = f"Match evolved banned keyword: {word}"
                return False
        
        for ext in evolved_exts:
            if ext and url.endswith(ext.lower()):
                item["_filter_reason"] = f"Match banned extension: {ext}"
                return False
                
        return True

    async def evaluate_batch_v2(self, batch_items: List[Dict], is_traceback: bool = False, user_query: Any = "") -> List[ScoreResult]:
        loop = asyncio.get_running_loop()
        futures = []
        
        for item in batch_items:
            fp = self._compute_fingerprint(item)
            if fp in self.seen_hashes:
                f = loop.create_future()
                f.set_result({"status": "REJECT", "analysis": "Batch Duplicate", "level": "Noise", "is_valid": False, "score": 0})
                futures.append(f)
                continue
            self.seen_hashes.add(fp)
            
            if self.validator:
                shadow_info = item.get("shadow_info", {})
                
                if item.get("level") == "L4" or shadow_info:
                    shadow_text = f"[L4 PHYSICAL ASSET CLUE]: Threshold: {shadow_info.get('access_threshold', '')} | Evidence: {shadow_info.get('evidence', '')}."
                else:
                    shadow_text = ""
                    
                miner_reason = f"[Miner Judgment]: {item.get('reason', '')}" if item.get('reason') else ""
                
                content_sources = [
                    item.get("snippet", ""),
                    item.get("extracted_content", ""),
                    item.get("page_content", ""),
                    shadow_text,
                    miner_reason
                ]
                combined_content = "\n".join([s for s in content_sources if s]).strip()

                if is_traceback and not combined_content:
                    combined_content = "[System Note]: This is a stripped Base URL extracted from a valid dataset. Please evaluate if this domain acts as an L1/L2 Hub based on the URL structure."

                futures.append(loop.run_in_executor(
                    self.executor,
                    lambda i=item, c=combined_content, uq=user_query: self.validator.validate_dataset_link(
                        url=i.get('url', ''),
                        title=i.get('title', 'Root Domain Traceback' if is_traceback else ''),
                        description=i.get('description', i.get('snippet', '')),
                        page_content=c,
                        user_query=uq,
                        candidate_type=i.get('candidate_type', ''),
                        topology_score=i.get('topology_score', 0.0)
                    )
                ))
            else:
                f = loop.create_future()
                f.set_result({"status": "ERROR", "analysis": "Validator Missing", "is_valid": False, "score": 0})
                futures.append(f)

        async def safe_execute(fut, url):
            try:
                return await asyncio.wait_for(fut, timeout=45.0)
            except asyncio.TimeoutError:
                logger.warning(f"⏱️ 全局强制熔断 (超时45s): {url}")
                return {"status": "ERROR", "analysis": "Global Timeout", "level": "Noise", "is_valid": False, "score": 0}
            except Exception as e:
                return {"status": "ERROR", "analysis": f"Error: {str(e)}", "level": "Noise", "is_valid": False, "score": 0}

        safe_futures = [safe_execute(futures[idx], batch_items[idx].get('url', '')) for idx in range(len(batch_items))]
        raw_reports = await asyncio.gather(*safe_futures)
        
        results = []
        for idx, rep in enumerate(raw_reports):
            if not isinstance(rep, dict): rep = {}
            
            raw_score = rep.get("score", rep.get("metrics", {}).get("ai_score", 0))
            try: total_score = float(raw_score)
            except: total_score = 0.0
            total_score = self._apply_miner_prior(batch_items[idx], total_score)

            suggested_level = str(rep.get("level", "Noise")).strip().upper()
            kill_check = str(rep.get("step1_kill_check", "No")).upper()
            status = str(rep.get("status", "")).upper()
            action = str(rep.get("action", "")).upper()
            is_valid_ai = bool(rep.get("is_valid", False))
            min_conf = float(getattr(self, "min_confidence", self.config.get("min_confidence", 0.6)))

            if suggested_level == "NOISE" or "YES" in kill_check:
                is_passed = False
                total_score = min(total_score, 0.3)
            elif action in ("HARD_BLACKLIST", "SOFT_IGNORE"):
                is_passed = False
            elif status in ("REJECT", "FAIL", "ERROR"):
                is_passed = False
            elif status == "PASS":
                is_passed = is_valid_ai and total_score >= min_conf
            elif status == "REVIEW":
                is_passed = total_score >= min_conf + 0.05 and is_valid_ai
            else:
                is_passed = (
                    is_valid_ai
                    and total_score >= min_conf
                    and suggested_level in ("L1", "L2", "L3", "L4")
                )

            reason = rep.get("intent_analysis", rep.get("reason", rep.get("analysis", "No reason provided by LLM")))
            content_type = rep.get("content_type", rep.get("metrics", {}).get("content_type", "unknown"))
            
            results.append(ScoreResult(
                total_score=total_score, is_passed=is_passed, reason=reason,
                suggested_level=suggested_level, content_type=content_type, raw_report=rep
            ))
        return results

    async def verify_tier_claim(self, item: Dict[str, Any], claimed_level: str, user_query: Any = "") -> Dict[str, Any]:
        """
        二次仲裁：仅对 L3/L4 进行模型复核，减少规则硬编码依赖。
        """
        level = str(claimed_level).upper()
        if level not in ("L3", "L4"):
            return {"supports_claim": True, "reason": "No secondary verification required."}

        url = item.get("url", "")
        title = item.get("title", "")
        description = item.get("description", item.get("snippet", ""))
        content = "\n".join([
            str(item.get("snippet", "")),
            str(item.get("extracted_content", "")),
            str(item.get("page_content", "")),
            str(item.get("reason", "")),
        ])[:3000]

        prompt = (
            "You are a strict tier consistency judge for MA4CD.\n"
            "Given one URL, decide whether the claimed tier is defensible.\n"
            "Rules:\n"
            "1) L3 means a sub-database ENTRY LINK, not a data file, article, or generic content page.\n"
            "2) L4 means online EVIDENCE of physical/offline/restricted data assets, not open digital data itself.\n"
            "Return JSON only with fields:\n"
            "{supports_claim: bool, is_database_entry_link: bool, is_physical_asset_evidence: bool, confidence: 0-1, reason: str}\n\n"
            f"Claimed tier: {level}\n"
            f"URL: {url}\n"
            f"Title: {title}\n"
            f"Description: {description}\n"
            f"Context: {content}\n"
        )

        system_message = "You must output strict JSON."
        mission_text = self._mission_text(user_query)
        if mission_text:
            system_message += f"\nMission context:\n{mission_text}"

        loop = asyncio.get_running_loop()

        def _invoke():
            try:
                if hasattr(self.llm, "invoke"):
                    return self.llm.invoke(prompt=prompt, system_message=system_message, require_json=True)
            except Exception as e:
                return {"supports_claim": False, "confidence": 0.0, "reason": f"LLM verification failed: {e}"}
            return {"supports_claim": False, "confidence": 0.0, "reason": "LLM verifier unavailable"}

        res = await loop.run_in_executor(self.executor, _invoke)
        if not isinstance(res, dict):
            return {"supports_claim": False, "confidence": 0.0, "reason": "Invalid verifier output"}
        return res


async def quality_score_node(state: InspectorState) -> Dict[str, Any]:
    logger.info(">>> Node: Quality Scoring (Tier Routing & Traceback Mode) 🚀")

    current_config = state.get("current_config", {})
    miner_output = state.get("miner_output", {})
    user_query = state.get("user_query", "")
    
    # 🔥 [新增] 提取 shared_state 用于反哺
    shared_state = state.get("shared_state") 

    all_raw = []
    if isinstance(miner_output, dict):
        all_raw.extend(miner_output.get("l3_candidates", []))
        all_raw.extend(miner_output.get("l4_clues", []))
    elif isinstance(miner_output, list):
        all_raw = miner_output
    
    if not all_raw:
        return {"audited_results": [], "rejected_items": [], "statistics": state.get("statistics", {})}

    try:
        llm = InspectorLLM() 
        engine = QualityScoringEngine(llm, config=current_config)
    except Exception as e:
        logger.error(f"Engine Init Error: {e}")
        return {"audited_results": [], "rejected_items": [], "statistics": state.get("statistics", {})}

    clean_candidates = []
    rejected_items = []
    for i in all_raw:
        raw_url = i.get("url", "")
        cleaned_url = URLRouterUtility.clean_junk_paths(raw_url)
        i["url"] = cleaned_url 
        
        if engine.dynamic_pre_filter(i, user_query=user_query):
            clean_candidates.append(i)
        else:
            rejected_items.append({
                "url": i.get("url"), 
                "reason": i.get("_filter_reason", "Pre-filter"),
                "title": i.get("title")
            })

    BATCH_SIZE = int(os.getenv("MA4CD_INSPECTOR_BATCH_SIZE", str(current_config.get("batch_size", 6))))
    BATCH_SIZE = max(1, BATCH_SIZE)
    batches = [clean_candidates[i:i + BATCH_SIZE] for i in range(0, len(clean_candidates), BATCH_SIZE)]
    audited_results = []
    traceback_candidates = []
    
    logger.info(f"📦 开始 Phase 1 (LLM定性与严格路由): {len(batches)} 批次 | 已预拦截: {len(rejected_items)}")
    
    for batch_idx, batch in enumerate(batches, 1):
        results = await engine.evaluate_batch_v2(batch, is_traceback=False, user_query=user_query)
        
        for idx, res in enumerate(results):
            original = batch[idx]
            url = original.get("url", "")
            
            has_vpath = URLRouterUtility.has_virtual_path(url)
            raw_report = res.raw_report if isinstance(res.raw_report, dict) else {}
            
            enriched = original.copy()
            enriched.update({
                "inspector_score": res.total_score,
                "inspector_reason": res.reason,
                "level": res.suggested_level,
                "content_type": res.content_type,
                "audit_response": raw_report
            })
            candidate_type = str(original.get("candidate_type", "")).strip().lower()
            if engine._is_infra_transient_error(raw_report):
                rejected_items.append({
                    "url": url,
                    "reason": f"[基础设施异常] 上游服务拥堵或超时，暂不作为语义拒绝: {raw_report.get('analysis', raw_report.get('error', ''))}",
                    "score": res.total_score,
                    "title": original.get("title"),
                    "audit_response": raw_report,
                    "_exclude_from_evolution": True
                })
                continue

            # =================================================================
            # 🔒 强一致性硬约束层：防止 L1/L2/L3/L4 漂移
            # =================================================================
            if not res.is_passed:
                rejected_items.append({
                    "url": url,
                    "reason": f"[规则拦截] 模型未通过审计或触发 kill-check: {res.reason}",
                    "score": res.total_score,
                    "title": original.get("title"),
                    "audit_response": raw_report
                })
                continue

            from agents.inspector.tools.quality_gates import post_llm_gate

            gate_ok, gate_reason = post_llm_gate(
                original,
                suggested_level=res.suggested_level,
                total_score=res.total_score,
                status=str(raw_report.get("status", "")),
                raw_report=raw_report,
                user_query=user_query,
                min_confidence=float(getattr(engine, "min_confidence", current_config.get("min_confidence", 0.6))),
            )
            if not gate_ok:
                rejected_items.append({
                    "url": url,
                    "reason": gate_reason,
                    "score": res.total_score,
                    "title": original.get("title"),
                    "audit_response": raw_report,
                })
                continue

            if res.suggested_level in ["L1", "L2"]:
                if has_vpath or (not URLRouterUtility.is_root_url(url)):
                    rejected_items.append({
                        "url": url,
                        "reason": f"[硬约束] {res.suggested_level} 必须是根入口 URL（无虚拟路径/参数）",
                        "score": res.total_score,
                        "title": original.get("title"),
                        "audit_response": raw_report
                    })
                    continue

            if res.suggested_level == "L3":
                if candidate_type == "exploration_target":
                    rejected_items.append({
                        "url": url,
                        "reason": "[高准确率拦截] exploration_target 仅代表可深挖，不直接作为 L3 最终资产",
                        "score": res.total_score,
                        "title": original.get("title"),
                        "audit_response": raw_report
                    })
                    continue
                if not has_vpath:
                    rejected_items.append({
                        "url": url,
                        "reason": "[硬约束] L3 必须是子库入口链接，通常应具备虚拟路径",
                        "score": res.total_score,
                        "title": original.get("title"),
                        "audit_response": raw_report
                    })
                    continue
                if TierGuard.has_binary_suffix(url):
                    rejected_items.append({
                        "url": url,
                        "reason": "[硬约束] L3 不能是数据文件直链，必须是子数据库入口链接",
                        "score": res.total_score,
                        "title": original.get("title"),
                        "audit_response": raw_report
                    })
                    continue
                if not TierGuard.llm_claims_database_entry(raw_report, res.content_type):
                    verify = await engine.verify_tier_claim(original, "L3", user_query=user_query)
                    if not verify.get("supports_claim", False):
                        rejected_items.append({
                            "url": url,
                            "reason": f"[LLM复核拦截] L3 主张未被二次模型支持: {verify.get('reason', 'No reason')}",
                            "score": res.total_score,
                            "title": original.get("title"),
                            "audit_response": raw_report
                        })
                        continue
                    # 证据回填：让下游闸门/报告能看到复核结论
                    try:
                        evidence = raw_report.get("evidence_signals", {})
                        if not isinstance(evidence, dict):
                            evidence = {}
                        evidence["is_database_entry_link"] = True
                        if "confidence" in verify:
                            evidence["secondary_verification_confidence"] = verify.get("confidence")
                        raw_report["evidence_signals"] = evidence
                    except Exception:
                        pass

            if res.suggested_level == "L4":
                if candidate_type == "exploration_target":
                    rejected_items.append({
                        "url": url,
                        "reason": "[高准确率拦截] exploration_target 不足以直接判定 L4，需要资产线索型候选",
                        "score": res.total_score,
                        "title": original.get("title"),
                        "audit_response": raw_report
                    })
                    continue
                if TierGuard.has_binary_suffix(url):
                    rejected_items.append({
                        "url": url,
                        "reason": "[硬约束] L4 不是数字文件直链，必须是物理/线下资产证据链接",
                        "score": res.total_score,
                        "title": original.get("title"),
                        "audit_response": raw_report
                    })
                    continue
                if not TierGuard.llm_claims_physical_asset(raw_report, res.content_type):
                    verify = await engine.verify_tier_claim(original, "L4", user_query=user_query)
                    if not verify.get("supports_claim", False):
                        rejected_items.append({
                            "url": url,
                            "reason": f"[LLM复核拦截] L4 主张未被二次模型支持: {verify.get('reason', 'No reason')}",
                            "score": res.total_score,
                            "title": original.get("title"),
                            "audit_response": raw_report
                        })
                        continue
                    # 证据回填：让下游闸门/报告能看到复核结论
                    try:
                        evidence = raw_report.get("evidence_signals", {})
                        if not isinstance(evidence, dict):
                            evidence = {}
                        evidence["is_physical_asset_evidence"] = True
                        if "confidence" in verify:
                            evidence["secondary_verification_confidence"] = verify.get("confidence")
                        # 在缺省情况下给一个较保守的 physical_only_confidence
                        if evidence.get("physical_only_confidence") is None:
                            evidence["physical_only_confidence"] = float(verify.get("confidence", 0.6) or 0.6)
                        raw_report["evidence_signals"] = evidence
                    except Exception:
                        pass

            # 第一步：优先判定是否为 L4
            if res.suggested_level == "L4" and res.is_passed:
                audited_results.append(enriched)
                logger.debug(f"🎯 [路由] 命中 L4 实体资产: {url}")
                continue
                
            # 第二步：非 L4 且【存在虚拟链接】
            if has_vpath:
                if res.suggested_level == "L3" and res.is_passed:
                    audited_results.append(enriched)
                    logger.debug(f"✅ [路由] 命中 L3 独立库: {url}")
                    
                    base_url = URLRouterUtility.extract_base_url(url)
                    traceback_candidates.append({"url": base_url, "title": "Base Portal Traceback"})
                else:
                    reject_reason = f"[规则拦截] URL存在虚拟路径，但LLM判定非L3 ({res.suggested_level}). 理由: {res.reason}"
                    rejected_items.append({"url": url, "reason": reject_reason, "score": res.total_score, "title": original.get("title"), "audit_response": raw_report})
                    
            # 第三步：非 L4 且【不存在虚拟链接 (已达根部)】
            else:
                if res.suggested_level in ["L1", "L2"] and res.is_passed:
                    audited_results.append(enriched)
                    logger.debug(f"🏛️ [路由] 命中 {res.suggested_level} 枢纽/门户: {url}")
                    
                    # 🔥 [新增核心逻辑 1]：如果是直接发现的 L2，加入 Miner 深挖队列
                    if res.suggested_level == "L2" and shared_state:
                        logger.info(f"🔄 发现原生 L2 母站，加入待深挖队列: {url}")
                        shared_state.add_to_remine_queue(url)
                        
                else:
                    reject_reason = f"[规则拦截] URL无虚拟路径，但LLM判定非L1/L2枢纽 ({res.suggested_level}). 理由: {res.reason}"
                    rejected_items.append({"url": url, "reason": reject_reason, "score": res.total_score, "title": original.get("title"), "audit_response": raw_report})

    # ==========================================
    # 🔍 Phase 2: 根链接溯源检测
    # ==========================================
    if traceback_candidates:
        unique_bases = {item['url']: item for item in traceback_candidates}.values()
        trace_batches = [list(unique_bases)[i:i + BATCH_SIZE] for i in range(0, len(unique_bases), BATCH_SIZE)]
        
        logger.info(f"🔍 开始 Phase 2 (溯源根链接): 共 {len(unique_bases)} 个候选枢纽需要确权")
        
        for batch in trace_batches:
            trace_results = await engine.evaluate_batch_v2(batch, is_traceback=True, user_query=user_query)
            for idx, res in enumerate(trace_results):
                original = batch[idx]
                url = original.get("url", "")
                
                if res.is_passed and res.suggested_level in ["L1", "L2"]:
                    if not URLRouterUtility.is_root_url(url):
                        logger.debug(f"⚠️ [溯源拦截] L1/L2 必须为根入口，跳过: {url}")
                        continue
                    from agents.inspector.tools.quality_gates import post_llm_gate as _post_gate

                    raw_tb = res.raw_report if isinstance(res.raw_report, dict) else {}
                    tb_ok, tb_reason = _post_gate(
                        original,
                        suggested_level=res.suggested_level,
                        total_score=res.total_score,
                        status=str(raw_tb.get("status", "")),
                        raw_report=raw_tb,
                        user_query=user_query,
                        min_confidence=float(getattr(engine, "min_confidence", current_config.get("min_confidence", 0.6))),
                    )
                    if not tb_ok:
                        logger.debug(f"⚠️ [溯源闸门] 拒绝: {url} | {tb_reason}")
                        continue
                    enriched = original.copy()
                    enriched.update({
                        "inspector_score": res.total_score,
                        "inspector_reason": f"Traceback Validated: {res.reason}",
                        "level": res.suggested_level,
                        "content_type": res.content_type,
                        "is_traceback": True
                    })
                    audited_results.append(enriched)
                    
                    # 🔥 [新增核心逻辑 2]：如果是溯源发现的 L2，加入 Miner 深挖队列
                    if res.suggested_level == "L2" and shared_state:
                        logger.info(f"🔄 溯源确认 L2 母站，加入待深挖队列: {url}")
                        shared_state.add_to_remine_queue(url)
                        
                else:
                    logger.debug(f"⚠️ [溯源放弃] 根链接被LLM拒绝或判级不符要求 ({res.suggested_level}): {url}")

    stats = state.get("statistics", {}).copy()
    stats.update({
        "batch_total": len(all_raw), 
        "tracebacks_attempted": len(traceback_candidates),
        "batch_passed": len(audited_results), 
        "batch_rejected": len(rejected_items)
    })
    logger.info(f"🎉 质量审计 & 路由分发完成. 本批次产出(含溯源): {len(audited_results)} | 拒绝: {len(rejected_items)}")

    # ==========================================
    # 📌 Explainability: rejection bucketing + samples
    # ==========================================
    rejection_summary = summarize_rejections(rejected_items)

    return {
        "audited_results": audited_results,
        "rejected_items": rejected_items,
        "statistics": stats,
        "rejection_summary": rejection_summary,
    }
