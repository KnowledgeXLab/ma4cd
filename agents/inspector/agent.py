import sys
import os
import asyncio
import logging
import re
from urllib.parse import urlparse, urlunparse
from typing import TypedDict, Dict, List, Any, Optional, Callable, Awaitable, Union
from langgraph.graph import StateGraph, END
from tqdm import tqdm

# --- 路径修复 ---
current_file = os.path.abspath(__file__)
inspector_dir = os.path.dirname(current_file)
agents_dir = os.path.dirname(inspector_dir)
project_root = os.path.dirname(agents_dir)

if project_root not in sys.path:
    sys.path.insert(0, project_root)

# 导入组件
from agents.inspector.memory.managers.memory_manager import InspectorMemoryManager
from agents.inspector.evolution.inspector_evolution_engine import InspectorEvolutionEngine

# 🔥 持久化状态机（File / Redis 由工厂选择）
try:
    from agents.inspector.backends.factory import get_inspector_state
except ImportError as e:
    logging.error(f"❌ 导入 get_inspector_state 失败: {e}")
    get_inspector_state = None

# 🟢 全局去重器
try:
    from agents.inspector.tools.global_deduplicator import GlobalDeduplicator
except ImportError:
    GlobalDeduplicator = None

# 🔥 导入核心节点 
try:
    from agents.inspector.nodes.quality_score_node import quality_score_node
    from agents.inspector.nodes.commit_node import commit_node
except ImportError as e:
    logging.critical(f"❌ 无法导入核心节点: {e}")
    raise e

logger = logging.getLogger("inspector.agent")

# --- 1. 定义 LangGraph State (🔥 重命名为 InspectorGraphState 避免冲突) ---
class InspectorGraphState(TypedDict, total=False):
    miner_output: Dict[str, Any]       
    user_query: Any                    
    current_config: Dict[str, Any]     
    audited_results: List[Dict]        
    rejected_items: List[Dict]         
    statistics: Dict[str, Any]         
    human_feedback: str
    is_final_batch: bool
    rejection_summary: Dict[str, Any]
    # 🔥 [新增] 将持久化状态机传入图节点，供节点内部调用 add_to_remine_queue
    shared_state: Any 

# --- 2. Agent 主类 ---
class InspectorAgent:
    def __init__(self):
        self.memory = InspectorMemoryManager()
        self.evolution_engine = InspectorEvolutionEngine(self.memory)
        self.global_deduplicator = GlobalDeduplicator() if GlobalDeduplicator else None
        
        # 🔥 状态机：默认 global，每次 process 时 bind_session
        self.state = get_inspector_state() if get_inspector_state else None
        # 仅用于 Miner 共享监督通道：domain + reason_code + pass_rate
        self._last_miner_supervision: List[Dict[str, Any]] = []
        # 用于报告的可解释性统计（跨 batch 聚合）
        self._last_rejection_summary: Dict[str, Any] = {}
        
        self.dna_config = self.evolution_engine.get_config()
        self.app = self._build_workflow()
        
        logger.info(f"🚀 Inspector Agent 就绪 | 代数: Gen {self.dna_config.get('generation', 0)}")

    def get_last_rejection_summary(self) -> Dict[str, Any]:
        """Return aggregated rejection explainability summary from last run."""
        return dict(self._last_rejection_summary or {})

    @staticmethod
    def _normalize_reason_code(reason: str) -> str:
        raw = str(reason or "").strip()
        if not raw:
            return "UNKNOWN"
        m = re.match(r"^\[(.*?)\]", raw)
        token = m.group(1) if m else raw.split(":", 1)[0]
        token = re.sub(r"[^A-Za-z0-9]+", "_", token).strip("_").upper()
        return token[:64] if token else "UNKNOWN"

    def _build_miner_supervision_payload(
        self,
        miner_items: List[Dict[str, Any]],
        passed_items: List[Dict[str, Any]],
        rejected_items: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        miner_by_domain: Dict[str, int] = {}
        pass_by_domain: Dict[str, int] = {}
        reject_by_domain: Dict[str, int] = {}
        reason_by_domain: Dict[str, Dict[str, int]] = {}

        for item in miner_items or []:
            u = str(item.get("url", "") or "")
            d = (urlparse(u).netloc or "unknown").lower()
            miner_by_domain[d] = miner_by_domain.get(d, 0) + 1

        for item in passed_items or []:
            u = str(item.get("url", "") or "")
            d = (urlparse(u).netloc or "unknown").lower()
            pass_by_domain[d] = pass_by_domain.get(d, 0) + 1

        for item in rejected_items or []:
            u = str(item.get("url", "") or "")
            d = (urlparse(u).netloc or "unknown").lower()
            reject_by_domain[d] = reject_by_domain.get(d, 0) + 1
            rc = self._normalize_reason_code(item.get("reason", "UNKNOWN"))
            bucket = reason_by_domain.setdefault(d, {})
            bucket[rc] = bucket.get(rc, 0) + 1

        domains = set(miner_by_domain) | set(pass_by_domain) | set(reject_by_domain)
        payload: List[Dict[str, Any]] = []
        for d in sorted(domains):
            miner_cnt = int(miner_by_domain.get(d, 0))
            pass_cnt = int(pass_by_domain.get(d, 0))
            reject_cnt = int(reject_by_domain.get(d, 0))
            reviewed = max(miner_cnt, pass_cnt + reject_cnt)
            pass_rate = (float(pass_cnt) / reviewed) if reviewed > 0 else None
            payload.append({
                "domain": d,
                "reviewed_count": reviewed,
                "pass_count": pass_cnt,
                "reject_count": reject_cnt,
                "pass_rate": pass_rate,
                "reason_breakdown": reason_by_domain.get(d, {})
            })
        return payload

    def get_miner_supervision_payload(self) -> List[Dict[str, Any]]:
        return list(self._last_miner_supervision or [])

    def _build_workflow(self):
        # 🔥 使用重命名后的 InspectorGraphState
        workflow = StateGraph(InspectorGraphState)
        
        workflow.add_node("quality_score", quality_score_node)
        workflow.add_node("commit_data", commit_node)
        
        workflow.set_entry_point("quality_score")
        workflow.add_edge("quality_score", "commit_data")
        workflow.add_edge("commit_data", END)
        
        return workflow.compile()

    def _flatten_artifacts(self, artifacts: List[Any]) -> List[Dict]:
        cleaned = []
        for item in artifacts:
            if isinstance(item, list):
                cleaned.extend(self._flatten_artifacts(item))
            elif isinstance(item, dict):
                cleaned.append(item)
        return cleaned

    def _clean_invalid_paths(self, raw_url: str) -> str:
        # 你原来的优秀清洗逻辑保持不变
        if not raw_url:
            return ""
            
        url = raw_url.strip().split('#')[0]
        try:
            parsed = urlparse(url)
            path = parsed.path
            original_path_lower = path.lower()
            
            index_suffixes = ['/index.html', '/index.php', '/index']
            for suffix in index_suffixes:
                if original_path_lower.endswith(suffix):
                    path = path[:-len(suffix)]
                    break 
            
            current_path_lower = path.lower().rstrip('/')
            if not current_path_lower:
                current_path_lower = '/'
                
            exact_invalid_paths = [
                '/', '/home', '/en', '/zh', '/en-us', '/about', '/contact', '/search'
            ]
            
            if current_path_lower in exact_invalid_paths:
                path = '' 
                parsed = parsed._replace(query='')
                
            parsed = parsed._replace(path=path)
            clean_url = urlunparse(parsed).rstrip('/')
            
            return clean_url if clean_url else raw_url 
            
        except Exception as e:
            logger.debug(f"⚠️ URL 清洗解析异常 {raw_url}: {e}")
            return url.rstrip('/')

    async def process(
        self,
        artifacts: List[Any],
        user_query: Any = "",
        session_id: str = None,
        *,
        resume_state: Optional[Dict[str, Any]] = None,
        on_progress: Optional[
            Callable[[List[str], List[Dict], List[Dict]], Union[None, Awaitable[None]]]
        ] = None,
    ) -> List[Dict[str, Any]]:
        self._last_miner_supervision = []
        if self.state and session_id and hasattr(self.state, "bind_session"):
            self.state.bind_session(session_id)
        elif self.state is None and get_inspector_state:
            self.state = get_inspector_state(session_id)
        if not artifacts:
            self._last_miner_supervision = []
            return []

        artifacts = self._flatten_artifacts(artifacts)
        total_input = len(artifacts)
        if total_input == 0:
            self._last_miner_supervision = []
            return []

        resume_state = resume_state or {}
        done_urls: set = set(resume_state.get("done_urls") or [])
        all_final_results: List[Dict] = list(resume_state.get("passed") or [])
        all_rejected_results: List[Dict] = list(resume_state.get("rejected") or [])
        if done_urls:
            logger.info(f"⏩ Inspector 续审：已完成 {len(done_urls)} 条，剩余待审")

        async def _notify_progress() -> None:
            if not on_progress:
                return
            result = on_progress(list(done_urls), list(all_final_results), list(all_rejected_results))
            if asyncio.iscoroutine(result):
                await result

        mission_context = user_query if isinstance(user_query, dict) else {"human_request": str(user_query or "")}
        runtime_config = self.evolution_engine.get_runtime_config(mission_context)
        self.dna_config = runtime_config

        batch_size = self.dna_config.get("batch_size", 50)
        logger.info(f"🎬 [Session: {session_id}] Inspector 启动 | 总量: {total_input} | 批次: {batch_size}")

        seen_urls_in_batch = set()

        pbar = tqdm(total=total_input, desc="🧐 质量审计中", unit="link", colour="green")
        if done_urls:
            pbar.update(min(len(done_urls), total_input))

        global_stats = {
            "mission_id": "MA4CD_MISSION",
            "session_id": session_id,
            "total_miner_items": total_input,
            "processed_count": len(done_urls),
            "full_passed_accumulator": list(all_final_results),
            "full_rejected_accumulator": list(all_rejected_results),
            "global_commit_stats": {"L1": 0, "L2": 0, "L3": 0, "L4": 0, "Blacklist": 0, "Duplicate": 0, "Error": 0}
        }
        # reset per-run explainability aggregation
        self._last_rejection_summary = {"total_rejected": 0, "buckets": {}, "top_samples": {}}

        for i in range(0, total_input, batch_size):
            batch_items = artifacts[i : i + batch_size]
            is_final_batch = (i + batch_size) >= total_input

            fresh_items = []
            for item in batch_items:
                raw_url = item.get('url')
                if not raw_url:
                    continue

                url = self._clean_invalid_paths(raw_url)
                item['url'] = url

                if url in done_urls:
                    continue

                if url in seen_urls_in_batch:
                    continue
                seen_urls_in_batch.add(url)

                is_dup = False
                if self.global_deduplicator:
                    try:
                        if asyncio.iscoroutinefunction(self.global_deduplicator.is_duplicate):
                            is_dup = await self.global_deduplicator.is_duplicate(url)
                        else:
                            is_dup = self.global_deduplicator.is_duplicate(url)
                    except Exception as e:
                        logger.debug(f"is_duplicate check failed: {e}")

                if is_dup:
                    logger.debug(f"🗑️ 全局去重拦截跳过: {url}")
                    done_urls.add(url)
                    continue

                past = self.memory.consult_past_experience(url)
                is_fresh = True

                if past:
                    status = getattr(past, 'status', "") if not isinstance(past, dict) else past.get('status', "")
                    if status == "PASS":
                        from agents.inspector.tools.quality_gates import prefilter_item
                        ok, gate_reason = prefilter_item(item, user_query=user_query)
                        if ok:
                            all_final_results.append(item)
                            done_urls.add(url)
                            is_fresh = False
                        else:
                            logger.debug(
                                f"♻️ 历史 PASS 未通过结构闸门，重新审计: {url} | {gate_reason}"
                            )
                    else:
                        logger.debug(f"♻️ 发现历史 FAIL 记录，移交最新版 LLM 重新审计: {url}")

                if is_fresh:
                    fresh_items.append(item)

            skipped_in_batch = len(batch_items) - len(fresh_items)
            if skipped_in_batch > 0 and not fresh_items:
                global_stats["processed_count"] = global_stats.get("processed_count", 0) + len(batch_items)
                pbar.update(len(batch_items))
                await _notify_progress()
                if not is_final_batch:
                    continue

            current_count = global_stats.get("processed_count", 0)
            global_stats["processed_count"] = current_count + len(batch_items)

            pbar.update(len(batch_items))

            if not fresh_items and not is_final_batch:
                await _notify_progress()
                continue

            current_state: InspectorGraphState = {
                "miner_output": {"l3_candidates": fresh_items},
                "user_query": user_query,
                "current_config": runtime_config,
                "audited_results": [],
                "rejected_items": [],
                "statistics": global_stats,
                "human_feedback": "",
                "is_final_batch": is_final_batch,
                "shared_state": self.state
            }

            try:
                final_output = await self.app.ainvoke(current_state)

                passed = final_output.get("audited_results", [])
                rejected = final_output.get("rejected_items", [])
                batch_rejection_summary = final_output.get("rejection_summary", {}) if isinstance(final_output, dict) else {}
                if not (batch_rejection_summary.get("buckets") or {}) and rejected:
                    try:
                        from agents.inspector.nodes.quality_score_node import summarize_rejections
                        batch_rejection_summary = summarize_rejections(rejected)
                    except Exception:
                        pass

                returned_stats = final_output.get("statistics", {})
                global_stats.update(returned_stats)

                for item in passed:
                    self.memory.memorize_audit_result({"url": item.get('url'), "status": "PASS", "metadata": item})
                    u = item.get("url")
                    if u:
                        done_urls.add(u)

                for item in rejected:
                    reason = str(item.get('reason', '')).upper()
                    soft_noise_keywords = ["TOPIC MISMATCH", "TOPIC", "NOT RELEVANT", "UNRELATED"]
                    is_soft_noise = any(kw in reason for kw in soft_noise_keywords)

                    if is_soft_noise:
                        logger.debug(f"🛡️ [防污染保护] 发现跨领域线索，本次丢弃但不进全局黑名单: {item.get('url')}")
                    else:
                        self.memory.memorize_audit_result({"url": item.get('url'), "status": "FAIL", "metadata": item})
                    u = item.get("url")
                    if u:
                        done_urls.add(u)

                all_final_results.extend(passed)
                all_rejected_results.extend(rejected)

                # aggregate rejection explainability
                try:
                    agg = self._last_rejection_summary
                    agg["total_rejected"] = int(agg.get("total_rejected", 0) or 0) + int(batch_rejection_summary.get("total_rejected", 0) or len(rejected))
                    buckets = agg.get("buckets") if isinstance(agg.get("buckets"), dict) else {}
                    for k, v in (batch_rejection_summary.get("buckets") or {}).items():
                        buckets[k] = int(buckets.get(k, 0) or 0) + int(v or 0)
                    agg["buckets"] = buckets
                    top = agg.get("top_samples") if isinstance(agg.get("top_samples"), dict) else {}
                    for b, items in (batch_rejection_summary.get("top_samples") or {}).items():
                        if b not in top:
                            top[b] = []
                        if isinstance(items, list):
                            for it in items:
                                if len(top[b]) >= 5:
                                    break
                                if isinstance(it, dict):
                                    top[b].append(it)
                    agg["top_samples"] = top
                    self._last_rejection_summary = agg
                except Exception:
                    pass
                await _notify_progress()

            except Exception as e:
                logger.error(f"❌ 批次流水线崩溃: {e}")
                await _notify_progress()
                raise

        pbar.close()

        hard_rejected = [
            r for r in all_rejected_results
            if not (isinstance(r, dict) and r.get("_exclude_from_evolution"))
        ]

        # 仅输出共享监督通道，不共享 Inspector 策略细节
        self._last_miner_supervision = self._build_miner_supervision_payload(
            miner_items=artifacts,
            passed_items=all_final_results,
            rejected_items=hard_rejected
        )
        actionable_reviewed = len(all_final_results) + len(hard_rejected)
        cleanup_rate = (actionable_reviewed - len(all_final_results)) / actionable_reviewed if actionable_reviewed > 0 else 0
        evolve_metrics = {
            "cleanup_rate": cleanup_rate,
            "total_reviewed": actionable_reviewed,
            "pass_count": len(all_final_results),
            "reject_count": len(hard_rejected),
        }
        self.dna_config = self.evolution_engine.evolve(
            metrics=evolve_metrics,
            rejected_items=hard_rejected,
            passed_items=all_final_results,
            mission_context=mission_context
        )
        self.dna_config = self.evolution_engine.get_runtime_config(mission_context)

        logger.info(f"✅ 审计全部完成 | 最终有效数据: {len(all_final_results)} | 进化至 Gen {self.evolution_engine.generation}")
        return all_final_results

if __name__ == "__main__":
    # 测试代码保持不变
    pass
