import sys
import os
import asyncio
import json
import time
import argparse
from typing import List, Dict, Any, Union, Optional
from datetime import datetime
from loguru import logger
from utils.prompt_contracts import extract_query_texts
from utils.session_collab import (
    build_curator_supplement_task,
    curator_scout_loop_enabled,
    get_session_collab,
    session_collab_enabled,
)
from utils.curator_skill import build_curator_gap_seed_urls, get_curator_max_rounds
from utils.pipeline_checkpoint import (
    PHASE_COMMANDER_DONE,
    PHASE_COMPLETED,
    PHASE_FAILED_SCOUT,
    PHASE_FLYWHEEL,
    PHASE_PENDING,
    PHASE_REPORT_PENDING,
    PHASE_SCOUT_DONE,
    PipelineCheckpointStore,
    ROUND_STEP_INSPECTOR,
    ROUND_STEP_MINER,
    is_resumable_checkpoint,
    new_checkpoint_payload,
    pipeline_checkpoint_enabled,
)

# =============================================================================
# 🛠️ 路径环境修复 (保持原样)
# =============================================================================
project_root = os.path.dirname(os.path.abspath(__file__))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

# 防止模块路径冲突
sys.path = [p for p in sys.path if not p.endswith(('miner', 'inspector', 'scout', 'commander', 'curator'))]

import utils.env  # noqa: F401  # loads project root `.env` before agents read env vars
from utils.skill_loader import get_active_skill_id, set_active_skill
from utils.runtime_profile import apply_env_defaults_non_overriding


def _is_truthy(v: str) -> bool:
    return str(v).strip().lower() in ("1", "true", "yes", "on")


def _assert_safe_runtime_path():
    """
    防误跑护栏：
    - 默认禁止从回收站路径执行（常见于误用旧副本）
    - 可通过 MA4CD_ALLOW_TRASH_RUN=1 显式放开
    """
    allow_trash = _is_truthy(os.getenv("MA4CD_ALLOW_TRASH_RUN", "0"))
    file_path = os.path.abspath(__file__)
    cwd_path = os.path.abspath(os.getcwd())

    suspicious_tokens = (
        "/.local/share/trash/",
        "/trash/files/",
    )
    file_l = file_path.lower()
    cwd_l = cwd_path.lower()
    suspicious = any(tok in file_l for tok in suspicious_tokens) or any(tok in cwd_l for tok in suspicious_tokens)

    if suspicious and not allow_trash:
        raise RuntimeError(
            "检测到从回收站路径运行 MA4CD，这会导致代码版本错乱。"
            f"当前文件路径: {file_path} | 当前工作目录: {cwd_path}。"
            "请切换到 /home/zhuyao/Documents/ma4cd 后重试；如确需在该路径运行，请设置 MA4CD_ALLOW_TRASH_RUN=1。"
        )

# =============================================================================
# 📦 核心组件导入 (新增 Curator)
# =============================================================================
try:
    from agents.commander.agent import CommanderAgent
    from agents.scout.agent import ScoutAgent
    from agents.miner.agent import UniversalMinerAgent
    from agents.inspector.agent import InspectorAgent
    from agents.curator.agent import CuratorAgent # 🔥 导入数据总馆长
    from utils.feedback_manager import FeedbackManager
    from utils.report_generator import ReportGenerator 
    from data_memory_center.manager import DataMemoryCenter
    
    # 导入统一记忆管理器的获取函数
    from agents.miner.memory.managers.memory_manager import get_unified_memory
except ImportError as e:
    print(f"❌ 核心组件导入失败! 错误信息: {e}")
    sys.exit(1)

# =============================================================================
# 🧠 MA4CD 工作流引擎 (Session & Dynamic Feedback Loop Optimized)
# =============================================================================
class MA4CDPipeline:
    def __init__(self):
        _assert_safe_runtime_path()
        logger.remove()
        logger.add(sys.stderr, format="<green>{time:HH:mm:ss}</green> | <level>{message}</level>")
        logger.info(f"📍 Runtime 路径校验通过 | file={os.path.abspath(__file__)} | cwd={os.path.abspath(os.getcwd())}")
        
        logger.info("🚀 正在初始化 MA4CD 系统 (Evolution Mode)...")
        skill_id = get_active_skill_id()
        if skill_id:
            logger.info(f"🧩 已加载 Skill: {skill_id}")
            applied = apply_env_defaults_non_overriding()
            if applied:
                logger.info(f"🧪 Skill runtime defaults applied (non-overriding): {len(applied)} vars")
        try:
            self.commander = CommanderAgent(model_name=os.getenv("MA4CD_COMMANDER_MODEL", "deepseek-chat"))
            self.scout = ScoutAgent()
            self.miner = UniversalMinerAgent()
            self.inspector = InspectorAgent()
            self.curator = CuratorAgent() # 🔥 初始化总馆长
            self.feedback_manager = FeedbackManager()
            self.last_stats = {"scout": 0, "miner": 0, "inspector": 0}
            
            # 初始化记忆管理器单例
            self.memory_manager = get_unified_memory()
            try:
                self.data_center = DataMemoryCenter()
            except Exception as dc_err:
                logger.warning(f"⚠️ DataMemoryCenter 初始化失败，历史回查功能降级: {dc_err}")
                self.data_center = None
            
            os.makedirs(os.path.join(project_root, "reports"), exist_ok=True)
            logger.success("✅ 所有 Agent (Commander, Scout, Miner, Inspector, Curator) 初始化完成。")
        except Exception as e:
            logger.error(f"❌ 系统初始化崩溃: {e}")
            raise e

    def _flatten_and_extract_urls(self, items: Any) -> List[str]:
        """展平 Scout 结果并提取有效 URL"""
        urls = []
        if isinstance(items, list):
            for item in items:
                urls.extend(self._flatten_and_extract_urls(item))
        elif isinstance(items, dict):
            target = items.get('url') or items.get('link') or items.get('href')
            if target and isinstance(target, str):
                urls.append(target)
        elif isinstance(items, str):
            urls.append(items)
        return urls

    def _flatten_results(self, items: Any) -> List[Dict]:
        """展平 Miner 和 Inspector 的结果列表"""
        flat_list = []
        if isinstance(items, list):
            for item in items:
                flat_list.extend(self._flatten_results(item))
        elif isinstance(items, dict):
            flat_list.append(items)
        return flat_list

    @staticmethod
    def _collect_current_run_urls(
        scout_urls: List[str],
        miner_items: List[Dict[str, Any]],
        audited_items: List[Dict[str, Any]],
    ) -> set[str]:
        """收集本轮已覆盖 URL，用于过滤历史回查中的重复展示。"""
        covered = set()
        for u in scout_urls or []:
            if isinstance(u, str) and u.startswith("http"):
                covered.add(u.strip())
        for bucket in (miner_items or [], audited_items or []):
            for item in bucket:
                if isinstance(item, dict):
                    u = str(item.get("url", "")).strip()
                    if u.startswith("http"):
                        covered.add(u)
        return covered

    def _show_historical_related_clues(self, query_text: str, clues: List[Dict[str, Any]]):
        """在控制台展示历史相关线索。"""
        print("\n" + "═" * 70)
        print("🗃️ [历史相关线索回查]")
        print("═" * 70)
        print(f"🔎 主题词: {query_text}")
        if not clues:
            print("ℹ️ 未检索到历史相关线索（或已被本轮结果完全覆盖）。")
            print("═" * 70 + "\n")
            return

        print(f"✅ 命中 {len(clues)} 条历史线索：")
        for idx, c in enumerate(clues, 1):
            level = c.get("level", "N/A")
            title = str(c.get("title", "Unknown") or "Unknown").strip()
            url = c.get("url", "")
            sim = float(c.get("similarity", 0.0) or 0.0)
            print(f"{idx}. [{level}] {title} | sim={sim:.2f}")
            print(f"   {url}")
        print("═" * 70 + "\n")

    def _init_session_collab(
        self,
        session_id: str,
        run_id: str,
        user_requirement: str,
    ):
        if not session_collab_enabled():
            return None, None
        bus, board = get_session_collab(session_id)
        board.update(
            session_id=session_id,
            run_id=run_id,
            intent=user_requirement,
            phase=PHASE_PENDING,
        )
        bus.publish(
            "pipeline.session_started",
            {"run_id": run_id, "intent": user_requirement},
            agent="pipeline",
        )
        return bus, board

    def _collab_publish(self, bus, event_type: str, payload: dict, agent: str = "pipeline"):
        if bus:
            bus.publish(event_type, payload, agent=agent)

    async def _curator_scout_supplement(
        self,
        session_id: str,
        user_requirement: str,
        scout_run_config: Dict[str, Any],
        curator_report: Dict[str, Any],
        bus,
        board,
        seen_urls: set,
    ) -> List[str]:
        """Curator 盲区驱动 Scout 战术补搜（受 env 与配额限制）。"""
        if not curator_scout_loop_enabled():
            return []
        gaps = curator_report.get("strategic_gaps") or []
        if not gaps:
            return []
        if not curator_report.get("yield_status", {}).get("can_continue", True):
            return []

        max_urls = int(os.getenv("MA4CD_CURATOR_SCOUT_MAX_URLS", "5") or 5)
        directives = str(curator_report.get("next_directives") or "")

        self._collab_publish(
            bus,
            "curator.scout_supplement_start",
            {"gaps": gaps[:8], "directives": directives[:500]},
            agent="curator",
        )

        supplement_task = build_curator_supplement_task(user_requirement, gaps, directives)
        try:
            from utils.curator_supplement import get_scout_prompt_append
            skill_patch = get_scout_prompt_append()
        except Exception:
            skill_patch = ""
        patch = (
            "[Curator Tactical Supplement] Prioritize database/portal URLs for gaps: "
            + "; ".join(str(g) for g in gaps[:5])
        )
        if skill_patch:
            patch = patch + "\n\n" + skill_patch
        self.scout.apply_amendment({"system_prompt_append": patch})

        loop = asyncio.get_running_loop()
        try:
            scout_raw = await loop.run_in_executor(
                None,
                self.scout.run,
                supplement_task,
                scout_run_config,
                session_id,
            )
        except Exception as e:
            logger.warning(f"⚠️ Curator→Scout 补搜失败: {e}")
            self._collab_publish(
                bus, "curator.scout_supplement_failed", {"error": str(e)}, agent="scout",
            )
            return []

        new_urls = [
            u for u in self._flatten_and_extract_urls(scout_raw)
            if isinstance(u, str) and u.startswith("http") and u not in seen_urls
        ]
        try:
            from utils.curator_supplement import rank_priority_urls
            new_urls = rank_priority_urls(new_urls)
        except Exception:
            pass
        new_urls = new_urls[:max_urls]
        for u in new_urls:
            seen_urls.add(u)

        if board:
            board.append_scout_urls(new_urls, source="curator_loop")
            board.update(
                gaps=gaps,
                directives=directives,
                yield_status=curator_report.get("yield_status"),
            )

        self._collab_publish(
            bus,
            "scout.curator_supplement_done",
            {"urls": new_urls, "count": len(new_urls)},
            agent="scout",
        )
        if new_urls:
            logger.info(f"🔭 [Curator→Scout] 战术补搜新增 {len(new_urls)} 个 URL")
        return new_urls

    def _curator_gap_seed_supplement(
        self,
        curator_report: Dict[str, Any],
        seen_urls: set,
    ) -> List[str]:
        """Scout 补搜无产出时，用 skill 门户种子 URL 触发 Miner 第二轮。"""
        gaps = curator_report.get("strategic_gaps") or []
        if not gaps:
            return []
        if not curator_report.get("yield_status", {}).get("can_continue", True):
            return []
        max_urls = int(os.getenv("MA4CD_CURATOR_SCOUT_MAX_URLS", "8") or 8)
        seeds = build_curator_gap_seed_urls(
            gaps,
            str(curator_report.get("next_directives") or ""),
            seen_urls,
            max_urls=max_urls,
        )
        if seeds:
            logger.info(f"🌱 [Curator→Miner] 盲区门户种子补挖 {len(seeds)} 个 URL")
        return seeds

    async def _run_pipeline_once(
        self,
        user_requirement: str,
        raise_on_error: bool = False,
        show_history_related: bool = False,
        history_per_level: int = 5,
        history_max_total: int = 20,
        history_include_current_run: bool = True,
        *,
        resume: bool = True,
        clear_checkpoint: bool = False,
    ):
        """执行单次全自动链路 (支持 L2 动态反哺、Curator 熔断与 phase 级断点续跑)"""
        ckpt_enabled = pipeline_checkpoint_enabled() and resume
        ckpt_store = PipelineCheckpointStore(user_requirement)

        if clear_checkpoint:
            ckpt_store.clear()
            logger.info("🗑️ 已清除本任务 pipeline checkpoint")

        existing = ckpt_store.load() if ckpt_enabled else {}
        resuming = ckpt_enabled and is_resumable_checkpoint(existing, user_requirement)

        if resuming:
            session_id = existing["session_id"]
            run_id = existing.get("run_id") or f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{session_id[:4]}"
            phase = existing.get("phase", PHASE_PENDING)
            round_counter = int(existing.get("round_counter") or 1)
            artifacts = dict(existing.get("artifacts") or {})
            self.last_stats = dict(artifacts.get("last_stats") or {"scout": 0, "miner": 0, "inspector": 0})
            logger.info(f"🧷 断点续跑 | phase={phase} round={round_counter} session={session_id[:8]}...")
        else:
            self.last_stats = {"scout": 0, "miner": 0, "inspector": 0}
            phase = PHASE_PENDING
            round_counter = 1
            artifacts = {}
            session_id = self.memory_manager.start_session({
                "task_intent": user_requirement,
                "start_time": datetime.now().isoformat(),
            })
            run_id = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{session_id[:4]}"

        checkpoint_payload = lambda p, rc=round_counter, art=artifacts: new_checkpoint_payload(
            user_requirement, session_id, run_id, phase=p, round_counter=rc, artifacts=art,
        )

        def persist_checkpoint(p: str, rc: Optional[int] = None):
            if not ckpt_enabled:
                return
            artifacts["last_stats"] = dict(self.last_stats)
            ckpt_store.save(checkpoint_payload(p, rc if rc is not None else round_counter, artifacts))

        logger.info(f"🟢 [Pipeline Start] Session ID: {session_id} | 任务: {user_requirement}")

        event_bus, mission_board = self._init_session_collab(session_id, run_id, user_requirement)
        seen_session_urls: set = set()

        try:
            if resuming:
                session_id = self.memory_manager.start_session(
                    {"task_intent": user_requirement, "start_time": datetime.now().isoformat()},
                    session_id=session_id,
                )
                os.environ["MA4CD_REUSE_ACTIVE_SESSION"] = "1"

            # --- Phase 1: Commander ---
            if phase == PHASE_PENDING:
                logger.info("\n🔵 [Phase 1] Commander: 战略规划")
                cmd_result = await self.commander.run(
                    user_requirement, history_reports=[], session_id=session_id,
                )
                artifacts["commander_result"] = cmd_result
                phase = PHASE_COMMANDER_DONE
                persist_checkpoint(phase)
                self._collab_publish(
                    event_bus,
                    "commander.plan_done",
                    {"core_intent": cmd_result.get("core_intent") if isinstance(cmd_result, dict) else None},
                    agent="commander",
                )
            else:
                cmd_result = artifacts.get("commander_result") or {}
                logger.info("⏩ 跳过 Commander（checkpoint）")

            task_config = cmd_result.get("task_config", {}) if isinstance(cmd_result, dict) else {}
            scout_config = task_config.get("scout_config", task_config) if isinstance(task_config, dict) else {}
            specific_targets = extract_query_texts(task_config.get("search_queries", [])) if isinstance(task_config, dict) else []
            scout_run_config = task_config if isinstance(task_config, dict) else {}
            if isinstance(scout_config, dict):
                scout_run_config = {**scout_run_config, "scout_config": scout_config}

            if mission_board and isinstance(cmd_result, dict):
                mission_board.update(
                    phase=phase,
                    core_intent=cmd_result.get("core_intent", ""),
                    rubric=task_config.get("scoring_rubric", {}) if isinstance(task_config, dict) else {},
                    specific_targets=specific_targets,
                )

            # --- Phase 2: Scout ---
            scout_urls: List[str] = []
            if phase in (PHASE_PENDING, PHASE_COMMANDER_DONE):
                logger.info("\n🟡 [Phase 2] Scout: OSINT 广域侦察")
                loop = asyncio.get_running_loop()
                scout_raw = await loop.run_in_executor(
                    None, self.scout.run, user_requirement, scout_run_config, session_id,
                )
                scout_urls = list(set([
                    u for u in self._flatten_and_extract_urls(scout_raw) if u.startswith("http")
                ]))
                artifacts["scout_urls"] = scout_urls
                self.last_stats["scout"] = len(scout_urls)
                if not scout_urls:
                    logger.warning("📍 Scout 锁定 0 个有效站点，流水线提前终止。")
                    if ckpt_enabled:
                        ckpt_store.save(checkpoint_payload(PHASE_FAILED_SCOUT, round_counter, artifacts))
                    self.memory_manager.end_session(session_id)
                    return []
                phase = PHASE_SCOUT_DONE
                persist_checkpoint(phase)
                for u in scout_urls:
                    seen_session_urls.add(u)
                if mission_board:
                    mission_board.append_scout_urls(scout_urls, source="initial_scout")
                    mission_board.update(phase=phase)
                self._collab_publish(
                    event_bus,
                    "scout.urls_found",
                    {"count": len(scout_urls), "sample": scout_urls[:5]},
                    agent="scout",
                )
                logger.success(f"📍 Scout 最终锁定 {len(scout_urls)} 个高价值目标站点")
            elif phase in (PHASE_SCOUT_DONE, PHASE_FLYWHEEL, PHASE_REPORT_PENDING):
                scout_urls = list(artifacts.get("scout_urls") or [])
                self.last_stats["scout"] = len(scout_urls)
                for u in scout_urls:
                    seen_session_urls.add(u)
                logger.info(f"⏩ 跳过 Scout（checkpoint）| {len(scout_urls)} 个 URL")
            else:
                scout_urls = list(artifacts.get("scout_urls") or [])

            if not scout_urls and phase not in (PHASE_REPORT_PENDING,):
                logger.warning("📍 无可用 Scout URL，流水线终止。")
                if ckpt_enabled:
                    ckpt_store.save(checkpoint_payload(PHASE_FAILED_SCOUT, round_counter, artifacts))
                self.memory_manager.end_session(session_id)
                return []

            enhanced_mission_context = {
                "human_request": user_requirement,
                "commander_core_intent": cmd_result.get(
                    "core_intent",
                    task_config.get("core_intent", "N/A") if isinstance(task_config, dict) else "N/A",
                ) if isinstance(cmd_result, dict) else "N/A",
                "specific_targets": specific_targets,
                "task_config": task_config,
                "scoring_rubric": task_config.get("scoring_rubric", {}) if isinstance(task_config, dict) else {},
                "session_id": session_id,
                "run_id": run_id,
            }

            total_miner_assets: List[Dict] = list(artifacts.get("total_miner_assets") or [])
            total_audited_items: List[Dict] = list(artifacts.get("total_audited_items") or [])
            MAX_ROUNDS = get_curator_max_rounds(3)

            # --- Phase 3–4.5: Miner ↔ Inspector ↔ Curator 飞轮（单 URL / 批次内可续）---
            if phase in (PHASE_SCOUT_DONE, PHASE_FLYWHEEL):
                if phase == PHASE_SCOUT_DONE:
                    current_urls_to_mine = list(scout_urls)
                    round_counter = 1
                    artifacts.pop("round_step", None)
                    artifacts.pop("round_urls", None)
                    artifacts.pop("round_miner_done_urls", None)
                    artifacts.pop("round_miner_assets", None)
                    artifacts.pop("inspector_artifacts", None)
                    artifacts.pop("inspector_done_urls", None)
                    artifacts.pop("inspector_round_passed", None)
                    artifacts.pop("inspector_round_rejected", None)
                else:
                    current_urls_to_mine = list(artifacts.get("round_urls") or artifacts.get("next_mine_urls") or [])
                    round_step_resume = artifacts.get("round_step")
                    if round_step_resume == ROUND_STEP_INSPECTOR:
                        logger.info(f"⏩ 飞轮续跑 | round={round_counter} 从 Inspector 批次续审")
                    elif round_step_resume == ROUND_STEP_MINER:
                        done_n = len(artifacts.get("round_miner_done_urls") or [])
                        logger.info(
                            f"⏩ 飞轮续跑 | round={round_counter} Miner 续挖 "
                            f"({done_n}/{len(current_urls_to_mine)} 已完成)"
                        )
                    elif not current_urls_to_mine:
                        logger.warning("⏩ 飞轮断点无待挖 URL，进入报告阶段")
                        phase = PHASE_REPORT_PENDING

                while current_urls_to_mine and phase != PHASE_REPORT_PENDING:
                    if round_counter > MAX_ROUNDS:
                        logger.warning(f"🛑 [安全制动] 已达到最大挖掘深度 (MAX_ROUNDS={MAX_ROUNDS})。")
                        break

                    logger.info(f"\n🔄 --- [开始 第 {round_counter} 轮挖掘与审计] ---")
                    round_urls = list(current_urls_to_mine)
                    artifacts["round_urls"] = round_urls
                    round_step = artifacts.get("round_step", ROUND_STEP_MINER)

                    miner_assets: List[Dict] = []

                    if round_step == ROUND_STEP_MINER:
                        done_urls_set = set(artifacts.get("round_miner_done_urls") or [])
                        miner_assets_acc: List[Dict] = list(artifacts.get("round_miner_assets") or [])
                        pending_mine = [u for u in round_urls if u not in done_urls_set]

                        logger.info(
                            f"🟠 [Phase 3 - Round {round_counter}] Miner: "
                            f"待挖 {len(pending_mine)}/{len(round_urls)}"
                        )

                        async def _on_miner_url(url: str, assets: List[Dict]) -> None:
                            if assets:
                                miner_assets_acc.extend(assets)
                            done_urls_set.add(url)
                            artifacts["round_miner_assets"] = miner_assets_acc
                            artifacts["round_miner_done_urls"] = list(done_urls_set)
                            artifacts["round_step"] = ROUND_STEP_MINER
                            artifacts["round_urls"] = round_urls
                            persist_checkpoint(PHASE_FLYWHEEL, round_counter)

                        await self.miner.mine_urls(
                            round_urls,
                            user_query=user_requirement,
                            session_id=session_id,
                            resume_batch=bool(done_urls_set),
                            on_url_complete=_on_miner_url,
                        )
                        miner_assets = list(artifacts.get("round_miner_assets") or miner_assets_acc)

                        if not miner_assets and pending_mine:
                            logger.warning(f"⛏️ 第 {round_counter} 轮挖掘未发现深层数据线索。")
                            artifacts.pop("round_step", None)
                            break

                        logger.info(f"⛏️ 第 {round_counter} 轮提取资产: {len(miner_assets)}")
                        if mission_board:
                            mission_board.update(
                                miner_stats={
                                    "round": round_counter,
                                    "assets": len(miner_assets),
                                    "total_assets": len(total_miner_assets) + len(miner_assets),
                                },
                            )
                        self._collab_publish(
                            event_bus,
                            "miner.round_done",
                            {"round": round_counter, "assets": len(miner_assets)},
                            agent="miner",
                        )
                        artifacts["inspector_artifacts"] = miner_assets
                        artifacts["round_step"] = ROUND_STEP_INSPECTOR
                        if not artifacts.get("inspector_done_urls"):
                            artifacts["inspector_done_urls"] = []
                            artifacts["inspector_round_passed"] = []
                            artifacts["inspector_round_rejected"] = []
                        persist_checkpoint(PHASE_FLYWHEEL, round_counter)
                    else:
                        miner_assets = list(artifacts.get("inspector_artifacts") or artifacts.get("round_miner_assets") or [])
                        logger.info(f"⏩ 跳过 Miner（本轮已完成）| 资产 {len(miner_assets)} 条")

                    if not miner_assets:
                        break

                    logger.info(f"🟢 [Phase 4 - Round {round_counter}] Inspector: 质量审计与入库")
                    inspector_resume = {
                        "done_urls": artifacts.get("inspector_done_urls") or [],
                        "passed": artifacts.get("inspector_round_passed") or [],
                        "rejected": artifacts.get("inspector_round_rejected") or [],
                    }

                    async def _on_inspector_progress(
                        done: List[str], passed: List[Dict], rejected: List[Dict],
                    ) -> None:
                        artifacts["inspector_done_urls"] = done
                        artifacts["inspector_round_passed"] = passed
                        artifacts["inspector_round_rejected"] = rejected
                        artifacts["round_step"] = ROUND_STEP_INSPECTOR
                        artifacts["inspector_artifacts"] = miner_assets
                        persist_checkpoint(PHASE_FLYWHEEL, round_counter)

                    final_assets_raw = await self.inspector.process(
                        miner_assets,
                        user_query=enhanced_mission_context,
                        session_id=session_id,
                        resume_state=inspector_resume,
                        on_progress=_on_inspector_progress,
                    )

                    audited_items = [f for f in self._flatten_results(final_assets_raw) if isinstance(f, dict)]
                    total_miner_assets.extend(miner_assets)
                    total_audited_items.extend(audited_items)
                    logger.success(f"🏆 第 {round_counter} 轮审计完成！本轮入库: {len(audited_items)} 条")

                    if mission_board:
                        mission_board.update(
                            inspector_stats={
                                "round": round_counter,
                                "audited": len(audited_items),
                                "total_audited": len(total_audited_items),
                            },
                        )
                    self._collab_publish(
                        event_bus,
                        "inspector.round_done",
                        {"round": round_counter, "audited": len(audited_items)},
                        agent="inspector",
                    )

                    for k in (
                        "round_step", "round_miner_done_urls", "round_miner_assets",
                        "inspector_artifacts", "inspector_done_urls",
                        "inspector_round_passed", "inspector_round_rejected",
                    ):
                        artifacts.pop(k, None)

                    try:
                        if hasattr(self.miner, "ingest_inspector_supervision"):
                            supervision_payload = []
                            if hasattr(self.inspector, "get_miner_supervision_payload"):
                                supervision_payload = self.inspector.get_miner_supervision_payload() or []
                            self.miner.ingest_inspector_supervision(
                                miner_assets, audited_items, inspector_supervision=supervision_payload,
                            )
                    except Exception as fb_err:
                        logger.warning(f"⚠️ Miner 监督反馈回写失败（忽略）: {fb_err}")

                    logger.info(f"\n🏛️ [Phase 4.5 - Round {round_counter}] Curator: Session 流量盘点与战略纠偏")
                    curator_report = await self.curator.evaluate_session(
                        session_id=session_id,
                        commander_intent=cmd_result.get("core_intent", user_requirement)
                        if isinstance(cmd_result, dict) else user_requirement,
                    )
                    can_continue = curator_report.get("yield_status", {}).get("can_continue", True)
                    gaps = curator_report.get("strategic_gaps", [])
                    directives = curator_report.get("next_directives", "")
                    if mission_board:
                        mission_board.update(
                            gaps=gaps,
                            directives=directives,
                            yield_status=curator_report.get("yield_status"),
                            phase=PHASE_FLYWHEEL,
                        )
                    self._collab_publish(
                        event_bus,
                        "curator.round_evaluated",
                        {
                            "round": round_counter,
                            "can_continue": can_continue,
                            "gaps": gaps[:8] if gaps else [],
                        },
                        agent="curator",
                    )
                    if not can_continue:
                        stop_reason = curator_report.get("yield_status", {}).get("stop_reason", "UNKNOWN")
                        logger.error(f"🛑 收到 Curator 熔断指令！原因: {stop_reason}")
                        artifacts["curator_stopped"] = True
                        artifacts["curator_stop_reason"] = stop_reason
                        break

                    if gaps and directives:
                        print("\n" + "═" * 70)
                        print("🏛️ [CURATOR 战略督导看板]")
                        print("═" * 70)
                        print("⚠️ 发现学科/数据盲区: \n" + "\n".join([f"  - {g}" for g in gaps]))
                        print("-" * 70)
                        print(f"💡 下一步战略指导: \n  {directives}")
                        print("═" * 70 + "\n")

                    curator_supplement_urls: List[str] = []
                    supplemented_rounds = set(artifacts.get("curator_scout_rounds") or [])
                    if (
                        can_continue
                        and gaps
                        and round_counter not in supplemented_rounds
                    ):
                        supplemented_rounds.add(round_counter)
                        artifacts["curator_scout_rounds"] = list(supplemented_rounds)
                        curator_supplement_urls = await self._curator_scout_supplement(
                            session_id,
                            user_requirement,
                            scout_run_config,
                            curator_report,
                            event_bus,
                            mission_board,
                            seen_session_urls,
                        )
                        if not curator_supplement_urls:
                            curator_supplement_urls = self._curator_gap_seed_supplement(
                                curator_report,
                                seen_session_urls,
                            )
                            for u in curator_supplement_urls:
                                seen_session_urls.add(u)

                    l2_tasks: List[str] = []
                    if hasattr(self.inspector, "state") and self.inspector.state:
                        l2_tasks = self.inspector.state.get_and_clear_remine_queue()

                    artifacts["total_miner_assets"] = total_miner_assets
                    artifacts["total_audited_items"] = total_audited_items

                    if l2_tasks:
                        current_urls_to_mine = l2_tasks[:3]
                        artifacts["next_mine_urls"] = current_urls_to_mine
                        artifacts["pending_l2_all"] = l2_tasks
                        round_counter += 1
                        phase = PHASE_FLYWHEEL
                        persist_checkpoint(phase, round_counter)
                        self._collab_publish(
                            event_bus,
                            "inspector.l2_enqueued",
                            {"count": len(l2_tasks), "mining": len(current_urls_to_mine)},
                            agent="inspector",
                        )
                        logger.info(
                            f"🚨 触发反向挖掘！Inspector 发现 {len(l2_tasks)} 个 L2 母站 "
                            f"(截取前 {len(current_urls_to_mine)} 个)。"
                        )
                    elif curator_supplement_urls:
                        current_urls_to_mine = curator_supplement_urls
                        artifacts["next_mine_urls"] = current_urls_to_mine
                        round_counter += 1
                        phase = PHASE_FLYWHEEL
                        persist_checkpoint(phase, round_counter)
                        logger.info(
                            f"🔭 [Curator→Miner] 触发战术补挖 {len(current_urls_to_mine)} 个 URL"
                        )
                    else:
                        logger.info("✅ 质检完毕，无新增 L2 溯源深挖任务，挖掘循环结束。")
                        current_urls_to_mine = []
                        artifacts.pop("next_mine_urls", None)
                        break
            elif phase == PHASE_REPORT_PENDING:
                total_miner_assets = list(artifacts.get("total_miner_assets") or [])
                total_audited_items = list(artifacts.get("total_audited_items") or [])
                logger.info("⏩ 跳过飞轮（checkpoint 已完成挖掘）")

            self.last_stats["miner"] = len(total_miner_assets)
            self.last_stats["inspector"] = len(total_audited_items)
            artifacts["total_miner_assets"] = total_miner_assets
            artifacts["total_audited_items"] = total_audited_items

            logger.info(
                f"\n🏁 Pipeline 挖掘总计: 找到资产 {len(total_miner_assets)} "
                f"-> 成功入库 {len(total_audited_items)}"
            )

            phase = PHASE_REPORT_PENDING
            persist_checkpoint(phase, round_counter)

            if show_history_related:
                logger.info("🗃️ [历史回查] 正在检索历史库中与主题词相关的线索...")
                historical_clues: List[Dict[str, Any]] = []
                if self.data_center and hasattr(self.data_center, "query_related_clues"):
                    try:
                        effective_max_total = 0 if int(history_max_total) <= 0 else max(history_max_total * 3, history_max_total)
                        raw_hits = self.data_center.query_related_clues(
                            query_text=user_requirement,
                            per_level=max(10, int(history_per_level)),
                            max_total=effective_max_total,
                            extra_keywords=specific_targets,
                            enable_lexical_scan=True,
                        )
                        if history_include_current_run:
                            historical_clues = raw_hits
                        else:
                            covered_urls = self._collect_current_run_urls(
                                scout_urls, total_miner_assets, total_audited_items,
                            )
                            for item in raw_hits:
                                u = str(item.get("url", "")).strip()
                                if u and u not in covered_urls:
                                    historical_clues.append(item)
                                if int(history_max_total) > 0 and len(historical_clues) >= history_max_total:
                                    break
                    except Exception as hist_err:
                        logger.warning(f"⚠️ 历史回查失败: {hist_err}")
                else:
                    logger.warning("⚠️ DataMemoryCenter 不可用，无法展示历史相关线索。")
                self._show_historical_related_clues(user_requirement, historical_clues)

            logger.info("\n📝 [Phase 5] Report Generator: 正在生成全局报告...")
            try:
                report_engine = ReportGenerator(run_id=run_id)
                inspector_debug = {}
                try:
                    if hasattr(self.inspector, "get_last_rejection_summary"):
                        inspector_debug = {"rejection_summary": self.inspector.get_last_rejection_summary()}
                except Exception:
                    inspector_debug = {}
                await report_engine.generate_all_reports(
                    user_query=user_requirement,
                    commander_plan=cmd_result if isinstance(cmd_result, dict) else {},
                    scout_urls=scout_urls,
                    miner_items=total_miner_assets,
                    audited_items=total_audited_items,
                    inspector_debug=inspector_debug,
                )
            except Exception as report_err:
                logger.error(f"⚠️ 报告生成失败: {report_err}")

            if ckpt_enabled:
                ckpt_store.save(checkpoint_payload(PHASE_COMPLETED, round_counter, artifacts))
                ckpt_store.clear()
                logger.info("✅ Pipeline 完成，checkpoint 已清除")

            if mission_board:
                mission_board.update(phase=PHASE_COMPLETED)
            self._collab_publish(
                event_bus,
                "pipeline.completed",
                {
                    "scout": self.last_stats.get("scout", 0),
                    "miner": self.last_stats.get("miner", 0),
                    "inspector": self.last_stats.get("inspector", 0),
                },
            )

            self.memory_manager.end_session(session_id)
            return total_audited_items

        except KeyboardInterrupt:
            if ckpt_enabled and session_id:
                try:
                    artifacts["last_stats"] = dict(self.last_stats)
                    persist_checkpoint(phase, round_counter)
                    logger.warning(f"💾 中断已保存 checkpoint（phase={phase}）")
                except Exception as save_err:
                    logger.warning(f"checkpoint 保存失败: {save_err}")
            raise
        except Exception as e:
            if ckpt_enabled and session_id:
                try:
                    artifacts["last_stats"] = dict(self.last_stats)
                    persist_checkpoint(phase, round_counter)
                    logger.warning(f"💾 已保存 pipeline checkpoint（phase={phase}），可续跑")
                except Exception as save_err:
                    logger.warning(f"checkpoint 保存失败: {save_err}")
            else:
                if session_id:
                    self.memory_manager.end_session(session_id)
            logger.error(f"❌ 链路运行中断: {e}")
            import traceback
            logger.error(traceback.format_exc())
            self.last_stats = {"scout": 0, "miner": 0, "inspector": 0}
            if raise_on_error:
                raise
            return []

    async def start_interactive_session(
        self,
        initial_query: str,
        *,
        resume: bool = True,
        clear_checkpoint: bool = False,
    ):
        """交互循环与 Agent DNA 进化反馈 (保持原样)"""
        current_query = initial_query
        agent_instances = {
            "Commander": self.commander, 
            "Scout": self.scout,
            "Miner": self.miner, 
            "Inspector": self.inspector,
            "Curator": self.curator
        }
        
        while True:
            hist_choice = input("🗃️ 本轮是否展示历史库中“与主题词相关的全部线索”？(y/N): ").strip().lower()
            show_history_related = hist_choice in ("y", "yes", "1", "true")
            await self._run_pipeline_once(
                current_query,
                show_history_related=show_history_related,
                history_max_total=0,  # 0 表示历史回查全量展示
                history_include_current_run=True,
                resume=resume,
                clear_checkpoint=clear_checkpoint if current_query == initial_query else False,
            )
            
            print("\n" + "░"*60)
            print(f"📊 统计汇总: Scout({self.last_stats['scout']}) -> Miner({self.last_stats['miner']}) -> Inspector({self.last_stats['inspector']})")
            
            feedback_map = {}
            for agent_name in ["Commander", "Scout", "Miner", "Inspector"]:
                fb = input(f"👮 [{agent_name}] 建议 (输入'exit'退出，或回车跳过): ").strip()
                if fb.lower() in ['exit', 'quit', 'q']: return 
                if fb: feedback_map[agent_name] = fb

            if not feedback_map:
                user_choice = input("\n👉 输入 'exit' 退出，或输入新指令继续挖掘: ").strip()
                if user_choice.lower() in ['exit', 'quit', 'q']: return 
                if user_choice: current_query = user_choice
                continue

            logger.info("🧠 正在解析专家反馈并驱动系统进化...")
            try:
                instructions = await self.feedback_manager.parse_structured_feedback(feedback_map, current_query)
                if instructions:
                    for instr in instructions:
                        target = instr.get("target_agent")
                        amendments = instr.get("amendments", {})
                        agent_instance = agent_instances.get(target)
                        if agent_instance and hasattr(agent_instance, 'apply_amendment'):
                            agent_instance.apply_amendment(amendments)
                    logger.success("🚀 DNA 已更新，Agent 已吸收反馈进入下一轮。")
            except Exception as fe:
                logger.error(f"❌ 进化失败: {fe}")

    async def close(self):
        """资源清理"""
        logger.info("🧹 正在清理系统资源...")
        if hasattr(self.miner, 'close'): await self.miner.close()
        if hasattr(self.inspector, 'close'): await self.inspector.close()


async def main(query, resume: bool = True, clear_checkpoint: bool = False, skill: Optional[str] = None):
    if skill:
        set_active_skill(skill)
    pipeline = MA4CDPipeline()
    try:
        await pipeline.start_interactive_session(
            query, resume=resume, clear_checkpoint=clear_checkpoint,
        )
    except KeyboardInterrupt:
        print("\n✅ 系统安全中断。")
    except Exception as e:
        logger.error(f"❌ 发生致命错误: {e}")
    finally:
        await pipeline.close()
        await asyncio.sleep(0.250) 
        os._exit(0)

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("query", nargs="?", default="寻找基因组学的研究数据")
    parser.add_argument(
        "--no-resume",
        action="store_true",
        help="忽略 pipeline checkpoint，从头执行",
    )
    parser.add_argument(
        "--clear-checkpoint",
        action="store_true",
        help="清除本任务 checkpoint 后执行",
    )
    parser.add_argument(
        "--skill",
        default=os.getenv("MA4CD_SKILL", "").strip() or None,
        help="启用领域 Skill 包（如 protein-research），等价于 MA4CD_SKILL",
    )
    args = parser.parse_args()
    asyncio.run(main(
        args.query,
        resume=not args.no_resume,
        clear_checkpoint=args.clear_checkpoint,
        skill=args.skill,
    ))
