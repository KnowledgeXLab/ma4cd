import logging
import requests
import re
import sys
import os
from typing import Dict, Any, Optional
from datetime import datetime
from requests.adapters import HTTPAdapter
from urllib.parse import urlparse

# =============================================================================
# 🔥 动态路径修复 (严格遵循无假路径原则)
# =============================================================================
current_file = os.path.abspath(__file__)                         
tools_dir = os.path.dirname(current_file)                        
inspector_dir = os.path.dirname(tools_dir)                       
agents_dir = os.path.dirname(inspector_dir)                      
project_root = os.path.dirname(agents_dir)                       

if project_root not in sys.path:
    sys.path.insert(0, project_root)

logger = logging.getLogger(__name__)

try:
    from agents.inspector.llms.inspector_llm import InspectorLLM
    from agents.inspector.prompts.inspector_prompt import InspectorPrompt
except ImportError as e:
    logger.critical(f"❌ 导入失败！当前 sys.path[0]: {sys.path[0]}")
    raise ImportError(f"无法导入 InspectorLLM...\n错误详情: {e}")

class DataValidator:
    """
    通用数据验证引擎：实现“所见即所得”的审计。
    🔥 终极优化版：支持 Commander 任务指令强对齐，支持 L4 影子信息。
    """
    def __init__(self, llm_instance: InspectorLLM, score_threshold: float = 0.6):
        self.llm = llm_instance
        self.score_threshold = score_threshold
        
        self.session = requests.Session()
        
        adapter = HTTPAdapter(pool_connections=50, pool_maxsize=50, max_retries=1)
        self.session.mount('http://', adapter)
        self.session.mount('https://', adapter)
        
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        })

    @staticmethod
    def _normalize_mission_context(user_query: Any = "") -> Dict[str, Any]:
        if isinstance(user_query, dict):
            return user_query
        raw = str(user_query or "").strip()
        return {"human_request": raw} if raw else {}

    @staticmethod
    def _mission_text(mission_context: Dict[str, Any]) -> str:
        if not mission_context:
            return ""
        human = str(mission_context.get("human_request", "")).strip()
        core = str(mission_context.get("commander_core_intent", "")).strip()
        targets = mission_context.get("specific_targets", [])
        targets_text = ", ".join([str(t) for t in targets]) if isinstance(targets, list) else str(targets or "").strip()
        parts = [
            f"Human Request: {human}" if human else "",
            f"Commander Core Intent: {core}" if core else "",
            f"Specific Targets: {targets_text}" if targets_text else ""
        ]
        return "\n".join([p for p in parts if p]).strip()

    def fetch_page_text(self, url: str) -> str:
        """兜底抓取：仅当上游没有提供 page_content 时才触发"""
        try:
            lower_url = url.lower()
            if lower_url.endswith(('.pdf', '.csv', '.zip', '.gz', '.xls', '.xlsx', '.json', '.h5', '.rds', '.xml', '.png', '.jpg')):
                return f"[Binary/Media File Detected] Filename: {url.split('/')[-1]}"

            response = self.session.get(url, timeout=(3.05, 8), stream=False)
            
            if response.status_code != 200:
                return f"Error: HTTP Status {response.status_code}"

            html = response.text[:100000] 
            
            # 清除脚本/样式/头部与注释，再做纯文本提取
            text = re.sub(r'<(script|style|head|title).*?>.*?</\1>', '', html, flags=re.DOTALL | re.IGNORECASE)
            text = re.sub(r'<!--.*?-->', ' ', text, flags=re.DOTALL)
            text = re.sub(r'<[^>]+>', ' ', text)
            text = re.sub(r'\s+', ' ', text).strip()
            
            return text[:2500]
            
        except Exception as e:
            logger.warning(f"❌ 兜底抓取失败 {url}: {str(e)[:50]}")
            return f"Error: Could not fetch page content ({type(e).__name__})."

    @staticmethod
    def _is_llm_unavailable_error(error_msg: str) -> bool:
        """
        识别“鉴权/额度/网关不可用”类错误，触发规则兜底判定。
        """
        msg = str(error_msg or "").lower()
        markers = [
            "401", "403", "429", "unauthorized", "authentication", "invalid token",
            "invalid api key", "insufficient_quota", "quota", "rate limit",
            "无效的令牌", "鉴权", "权限", "api key", "access denied"
        ]
        return any(m in msg for m in markers)

    @staticmethod
    def _safe_tokenize(text: str) -> list[str]:
        return [t for t in re.split(r"[^a-z0-9_]+", (text or "").lower()) if t]

    def _fallback_rule_audit(
        self,
        url: str,
        title: str,
        description: str,
        page_content: str,
        mission_context: Dict[str, Any],
        candidate_type: str = "",
        topology_score: float = 0.0,
        llm_error: str = "",
    ) -> Dict[str, Any]:
        """
        LLM 不可用时的规则兜底审计：
        - 保证输出结构与主链路一致
        - 对明显数据库入口给出可通过判定（L2/L3）
        - 对明显噪声给出拒绝判定（Noise）
        """
        parsed = urlparse(url or "")
        path = (parsed.path or "").lower()
        has_vpath = bool(path.strip("/")) or bool(parsed.query)
        is_binary = bool(re.search(r"\.(pdf|csv|zip|gz|xls|xlsx|json|xml|txt|h5|hdf5)(?:$|[?#])", url.lower()))

        haystack = "\n".join([
            str(url or ""),
            str(title or ""),
            str(description or ""),
            str(page_content or "")[:2500],
            str(mission_context.get("human_request", "") or ""),
            str(mission_context.get("commander_core_intent", "") or ""),
            ",".join([str(x) for x in (mission_context.get("specific_targets", []) or [])]),
        ]).lower()
        tokens = set(self._safe_tokenize(haystack))

        from utils.inspector_fallback_audit import compute_fallback_score

        score, pos_hits, mission_hits, neg_hits = compute_fallback_score(
            haystack=haystack,
            tokens=tokens,
            mission_text=self._mission_text(mission_context),
            topology_score=topology_score,
            is_binary=is_binary,
        )
        if score >= self.score_threshold and not is_binary:
            level = "L3" if has_vpath else "L2"
            action = "KEEP"
            is_valid = True
            status = "PASS"
            step1_kill = "No"
            content_type = "sub_database"
            reason = (
                f"Rule fallback pass (LLM unavailable): data_signals={pos_hits}, "
                f"mission_hits={mission_hits}, noise_hits={neg_hits}, has_vpath={has_vpath}"
            )
            evidence_signals = {
                "is_database_entry_link": True,
                "is_physical_asset_evidence": False,
                "physical_only_confidence": 0.0
            }
        else:
            level = "NOISE"
            action = "SOFT_IGNORE"
            is_valid = False
            status = "FAIL"
            step1_kill = "Yes"
            content_type = "noise"
            reason = (
                f"Rule fallback reject (LLM unavailable): data_signals={pos_hits}, "
                f"mission_hits={mission_hits}, noise_hits={neg_hits}, binary={is_binary}"
            )
            evidence_signals = {
                "is_database_entry_link": False,
                "is_physical_asset_evidence": False,
                "physical_only_confidence": 0.0
            }

        return {
            "url": url,
            "timestamp": datetime.now().isoformat(),
            "status": status,
            "action": action,
            "is_valid": is_valid,
            "score": score,
            "level": level,
            "intent_analysis": reason,
            "step1_kill_check": step1_kill,
            "metrics": {"ai_score": score, "content_type": content_type},
            "analysis": f"{reason}; llm_error={llm_error[:160]}",
            "content_type": content_type,
            "candidate_type": candidate_type,
            "topology_score": topology_score,
            "evidence_signals": evidence_signals,
            "four_dimensional_analysis": {},
            "dna_patch": {},
            "metadata": {"title": title, "snippet": (page_content or "")[:150] + "..."}
        }

    # 🌟 核心突破：接收 user_query 参数！
    def validate_dataset_link(
        self,
        url: str,
        title: str,
        description: str,
        page_content: Optional[str] = None,
        user_query: Any = "",
        candidate_type: str = "",
        topology_score: float = 0.0
    ) -> Dict:

        # Degrade matrix: allow rules-only runs to keep pipeline alive during outages.
        try:
            from utils.llm_budgeter import rules_only
            if rules_only("inspector"):
                if not page_content:
                    page_content = self.fetch_page_text(url)
                mission_context = self._normalize_mission_context(user_query)
                return self._fallback_rule_audit(
                    url=url,
                    title=title,
                    description=description,
                    page_content=page_content or "",
                    mission_context=mission_context,
                    candidate_type=candidate_type,
                    topology_score=topology_score,
                    llm_error="rules_only_mode",
                )
        except Exception:
            pass
        
        if not page_content:
            page_content = self.fetch_page_text(url)
            
        mission_context = self._normalize_mission_context(user_query)
        mission_text = self._mission_text(mission_context)

        prompt = InspectorPrompt.get_audit_prompt(
            url,
            title,
            description,
            page_content,
            user_query=user_query if isinstance(user_query, str) else "",
            mission_context=mission_context,
            candidate_type=candidate_type,
            topology_score=topology_score
        )
        
        # 🌟 杀手锏：将 Commander 的指令编织成最高系统指令！
        system_msg = "You are a stringent Data Auditor."
        if mission_text:
            system_msg += f"\n\n【🚨 CRITICAL MISSION / 全局核心任务】\n当前系统的唯一目标是寻找与以下结构化任务高度相关的数据：\n{mission_text}\n\n"
            system_msg += "【执行铁律】：你必须严格审查这条数据是否与上述核心任务在国家、主题、领域上高度匹配。如果该数据虽然结构完美，但【明显跑题】或【毫无关联】，请立即在 step1_kill_check 中输出 Yes，并将 level 强制评为 Noise！"
        
        try:
            if hasattr(self.llm, "invoke_json"):
                # 带着任务军规去审批
                result = self.llm.invoke_json(prompt, system_message=system_msg)
            else:
                result = self.llm.invoke(prompt=prompt, system_message=system_msg, require_json=True)
        except Exception as e:
            err = str(e)
            if self._is_llm_unavailable_error(err):
                logger.warning(f"⚠️ Inspector LLM 不可用，启用规则兜底审计: {err[:120]}")
                return self._fallback_rule_audit(
                    url=url,
                    title=title,
                    description=description,
                    page_content=page_content or "",
                    mission_context=mission_context,
                    candidate_type=candidate_type,
                    topology_score=topology_score,
                    llm_error=err
                )
            return self._generate_error_report(url, err)

        if isinstance(result, dict) and "error" in result:
            err = str(result.get("error", ""))
            if self._is_llm_unavailable_error(err):
                logger.warning(f"⚠️ Inspector LLM 返回错误对象，启用规则兜底审计: {err[:120]}")
                return self._fallback_rule_audit(
                    url=url,
                    title=title,
                    description=description,
                    page_content=page_content or "",
                    mission_context=mission_context,
                    candidate_type=candidate_type,
                    topology_score=topology_score,
                    llm_error=err
                )
            return self._generate_error_report(url, err)

        raw_score = result.get("score", 0.0)
        try:
            score = float(raw_score)
        except (ValueError, TypeError):
            score = 0.0
            
        if score > 1.0:
            score = score / 100.0

        action = str(result.get("action", "")).upper()
        is_valid_ai = bool(result.get("is_valid", False))
        level = str(result.get("level", "NOISE")).upper()
        content_type = result.get("content_type", "unknown")
        evidence_signals = result.get("evidence_signals", {})
        four_dimensional_analysis = result.get("four_dimensional_analysis", {})
        dna_patch = result.get("dna_patch", {})
        
        intent_analysis = result.get("intent_analysis", "")
        step1_kill_check = result.get("step1_kill_check", "No")
        analysis_reason = result.get("reason", result.get("level_reasoning", "No reason provided"))

        status = "FAIL"
        if action == "HARD_BLACKLIST":
            status = "REJECT"
        elif action == "SOFT_IGNORE":
            status = "FAIL"
        elif action == "KEEP":
            if is_valid_ai and score >= self.score_threshold:
                status = "PASS"
            elif is_valid_ai and score >= 0.4:
                status = "REVIEW"
            else:
                status = "FAIL"
        else:
            if is_valid_ai:
                if score >= self.score_threshold:
                    status = "PASS"
                elif score >= 0.4:
                    status = "REVIEW"
                else:
                    status = "FAIL"
            else:
                status = "REJECT"

        return {
            "url": url,
            "timestamp": datetime.now().isoformat(),
            "status": status,
            "action": action or "UNKNOWN",
            "is_valid": is_valid_ai,  
            "score": score,           
            "level": level,
            "intent_analysis": intent_analysis,   
            "step1_kill_check": step1_kill_check, 
            "metrics": {"ai_score": score, "content_type": content_type},
            "analysis": analysis_reason,
            "content_type": content_type,
            "candidate_type": candidate_type,
            "topology_score": topology_score,
            "evidence_signals": evidence_signals if isinstance(evidence_signals, dict) else {},
            "four_dimensional_analysis": four_dimensional_analysis if isinstance(four_dimensional_analysis, dict) else {},
            "dna_patch": dna_patch if isinstance(dna_patch, dict) else {},
            "metadata": {"title": title, "snippet": page_content[:150] + "..."}
        }

    def _generate_error_report(self, url: str, error_msg: str) -> Dict:
        return {
            "url": url,
            "status": "ERROR",
            "level": "Error",
            "step1_kill_check": "Yes", 
            "intent_analysis": f"Error occurred: {error_msg}",
            "analysis": f"LLM validation failed: {error_msg}",
            "metrics": {"ai_score": 0}
        }
