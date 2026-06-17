import os
import sys
import json
import csv
import gc
import asyncio
import traceback
from dataclasses import dataclass, asdict
from datetime import datetime
from typing import Dict, List, Any, Set

from loguru import logger


project_root = os.path.dirname(os.path.abspath(__file__))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from main_workflow import MA4CDPipeline
from utils.batch_checkpoint import BatchCheckpointStore


@dataclass
class Mission:
    idx: int
    cn: str
    en: str
    category: str


MISSIONS: List[Mission] = [
    Mission(1, "地地导弹总体", "Surface-to-Surface Missile System Engineering", "总体技术"),
    Mission(2, "防空导弹总体", "Air Defense Missile System Engineering", "总体技术"),
    Mission(3, "飞航导弹总体", "Cruise Missile System Engineering", "总体技术"),
    Mission(4, "火箭总体", "Rocket System Engineering", "总体技术"),
    Mission(5, "航天器总体", "Spacecraft System Engineering", "总体技术"),
    Mission(6, "固体推进技术", "Solid Propulsion Technology", "推进技术"),
    Mission(7, "液体推进技术", "Liquid Propulsion Technology", "推进技术"),
    Mission(8, "惯性技术", "Inertial Technology", "导航制导与控制技术"),
    Mission(9, "伺服技术", "Servo Technology", "导航制导与控制技术"),
    Mission(10, "计算机硬件", "Computer Hardware", "计算机技术"),
    Mission(11, "电子技术", "Electronics Technology", "电子与通信技术"),
    Mission(12, "通信技术", "Communication Technology", "电子与通信技术"),
    Mission(13, "材料与制造技术", "Materials and Manufacturing Technology", "材料与制造技术"),
    Mission(14, "热环境与热防护技术", "Thermal Environment and Thermal Protection Technology", "环境工程"),
    Mission(15, "力学环境工程", "Mechanical Environment Engineering", "环境工程"),
    Mission(16, "电磁环境工程", "Electromagnetic Environment Engineering", "环境工程"),
    Mission(17, "测试技术", "Testing Technology", "测试技术"),
    Mission(18, "空气动力学", "Aerodynamics", "空气动力学"),
    Mission(19, "轨道动作技术", "Orbital Maneuvering Technology", "航天特种技术"),
    Mission(20, "弹头与突防技术", "Warhead and Penetration Technology", "其他航天技术"),
    Mission(21, "地面支持与发射技术", "Ground Support and Launch Technology", "其他航天技术"),
    Mission(22, "航天火工品", "Aerospace Pyrotechnics", "其他航天技术"),
    Mission(23, "项目管理", "Project Management", "管理"),
    Mission(24, "质量管理", "Quality Management", "管理"),
    Mission(25, "可靠性管理", "Reliability Management", "管理"),
    Mission(26, "供应链管理", "Supply Chain Management", "管理"),
]


def build_query(m: Mission) -> str:
    return (
        f"请围绕航天技术方向，挖掘“{m.cn} / {m.en}”相关的高价值数据线索。"
        "目标优先级：L1/L2 门户入口、L3 数据库入口、L4 线下/受限资产证据。"
        "避免泛新闻与单篇文章，优先技术报告、数据库、机构目录、标准/手册索引。"
    )


class AerospaceBatchRunner:
    def __init__(self):
        resume_dir = os.getenv("MA4CD_BATCH_RESUME_DIR", "").strip()
        if resume_dir:
            self.output_dir = resume_dir if os.path.isabs(resume_dir) else os.path.join(project_root, resume_dir)
            run_tag = os.path.basename(os.path.normpath(self.output_dir))
            self.run_id = run_tag.replace("batch26_", "")
        else:
            self.run_id = datetime.now().strftime("%Y%m%d_%H%M%S")
            self.output_dir = os.path.join(project_root, "reports", f"batch26_{self.run_id}")
        os.makedirs(self.output_dir, exist_ok=True)

        self.checkpoint_path = os.path.join(self.output_dir, "checkpoint.json")
        self.batch_id = f"batch26_{self.run_id}"
        self._checkpoint = BatchCheckpointStore(self.batch_id, self.checkpoint_path)
        self.summary_json_path = os.path.join(self.output_dir, "summary.json")
        self.summary_csv_path = os.path.join(self.output_dir, "summary.csv")
        self.summary_md_path = os.path.join(self.output_dir, "summary.md")

        self.cooldown_sec = int(os.getenv("MA4CD_BATCH_COOLDOWN", "12"))
        self.deep_cooldown_sec = int(os.getenv("MA4CD_BATCH_FAIL_COOLDOWN", "30"))

        self.results: List[Dict[str, Any]] = []
        self.done_ids: Set[int] = set()
        self._load_checkpoint()

    def _is_effective_success(self, row: Dict[str, Any]) -> bool:
        """真实成功判定：状态成功且生成了报告目录。"""
        if row.get("status") != "success":
            return False
        report_dirs = row.get("report_dirs", [])
        return isinstance(report_dirs, list) and len(report_dirs) > 0

    def _reports_snapshot(self) -> Set[str]:
        reports_root = os.path.join(project_root, "reports")
        if not os.path.exists(reports_root):
            return set()
        return {
            d for d in os.listdir(reports_root)
            if os.path.isdir(os.path.join(reports_root, d))
        }

    def _load_checkpoint(self):
        try:
            payload = self._checkpoint.load()
            if not payload:
                return
            self.results = payload.get("results", [])
            # done_ids 以 results 为准重算，避免历史误判 success 导致无法补跑
            self.done_ids = {
                int(r.get("idx")) for r in self.results
                if isinstance(r, dict) and self._is_effective_success(r)
            }
            logger.info(f"🧷 已加载断点：完成 {len(self.done_ids)} / 26")
        except Exception as e:
            logger.warning(f"⚠️ 断点读取失败，将重新开始: {e}")
            self.results = []
            self.done_ids = set()

    def _save_checkpoint(self):
        payload = {
            "run_id": self.run_id,
            "saved_at": datetime.now().isoformat(),
            "done_ids": sorted(list(self.done_ids)),
            "results": self.results
        }
        self._checkpoint.save(payload)

    def _append_result(self, row: Dict[str, Any]):
        self.results = [r for r in self.results if r.get("idx") != row.get("idx")]
        self.results.append(row)
        self.results.sort(key=lambda x: int(x.get("idx", 0)))
        idx = int(row["idx"])
        if self._is_effective_success(row):
            self.done_ids.add(idx)
        else:
            # 失败或不完整任务允许下次继续补跑
            self.done_ids.discard(idx)
        self._save_checkpoint()

    def _write_summaries(self):
        with open(self.summary_json_path, "w", encoding="utf-8") as f:
            json.dump(self.results, f, ensure_ascii=False, indent=2)

        fieldnames = [
            "idx", "category", "cn", "en", "status", "duration_sec",
            "audited_assets", "scout_count", "miner_count", "inspector_count",
            "report_dirs", "error", "started_at", "finished_at", "query"
        ]
        with open(self.summary_csv_path, "w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
            writer.writeheader()
            for r in self.results:
                row = dict(r)
                row["report_dirs"] = "; ".join(row.get("report_dirs", []))
                writer.writerow(row)

        ok = [r for r in self.results if self._is_effective_success(r)]
        fail = [r for r in self.results if not self._is_effective_success(r)]
        md_lines = [
            f"# MA4CD 航天 26 任务批跑汇总 ({self.run_id})",
            "",
            f"- 总任务数: {len(MISSIONS)}",
            f"- 已完成: {len(self.results)}",
            f"- 成功: {len(ok)}",
            f"- 失败: {len(fail)}",
            "",
            "## 任务明细",
            "",
            "| # | 分类 | 任务 | 状态 | 审计入库 | Scout | Miner | Inspector | 耗时(s) | 报告目录 |",
            "|---:|---|---|---|---:|---:|---:|---:|---:|---|",
        ]
        for r in self.results:
            task_label = f"{r.get('cn', '')} / {r.get('en', '')}"
            dirs = "<br>".join(r.get("report_dirs", [])) if r.get("report_dirs") else "-"
            md_lines.append(
                f"| {r.get('idx')} | {r.get('category')} | {task_label} | {r.get('status')} | "
                f"{r.get('audited_assets', 0)} | {r.get('scout_count', 0)} | {r.get('miner_count', 0)} | "
                f"{r.get('inspector_count', 0)} | {r.get('duration_sec', 0)} | {dirs} |"
            )
        if fail:
            md_lines.extend(["", "## 失败任务", ""])
            for r in fail:
                md_lines.append(
                    f"- `{r.get('idx')}` {r.get('cn')} / {r.get('en')}: `{r.get('error', '')}`"
                )
        with open(self.summary_md_path, "w", encoding="utf-8") as f:
            f.write("\n".join(md_lines))

    async def run(self):
        logger.info(f"🚀 启动批量任务：航天技术 26 任务 | 输出目录: {self.output_dir}")
        pipeline = MA4CDPipeline()
        try:
            for m in MISSIONS:
                if m.idx in self.done_ids:
                    logger.info(f"⏭️ 跳过已完成任务 {m.idx}/26: {m.cn}")
                    continue

                logger.info("=" * 80)
                logger.info(f"▶️ [{m.idx}/26] 开始: {m.category} | {m.cn} / {m.en}")
                query = build_query(m)
                before_dirs = self._reports_snapshot()
                started = datetime.now()

                row: Dict[str, Any] = {
                    "idx": m.idx,
                    "category": m.category,
                    "cn": m.cn,
                    "en": m.en,
                    "query": query,
                    "started_at": started.isoformat(),
                    "status": "failed",
                    "duration_sec": 0,
                    "audited_assets": 0,
                    "scout_count": 0,
                    "miner_count": 0,
                    "inspector_count": 0,
                    "report_dirs": [],
                    "error": "",
                }

                try:
                    assets = await pipeline._run_pipeline_once(query, raise_on_error=True)
                    after_dirs = self._reports_snapshot()
                    new_dirs = sorted(list(after_dirs - before_dirs))

                    duration = int((datetime.now() - started).total_seconds())
                    row.update({
                        "duration_sec": duration,
                        "audited_assets": len(assets) if isinstance(assets, list) else 0,
                        "scout_count": pipeline.last_stats.get("scout", 0),
                        "miner_count": pipeline.last_stats.get("miner", 0),
                        "inspector_count": pipeline.last_stats.get("inspector", 0),
                        "report_dirs": [os.path.join("reports", d) for d in new_dirs],
                        "finished_at": datetime.now().isoformat(),
                    })

                    # 报告目录是任务真正跑通的硬信号；无报告则判为失败，避免“假成功”
                    if not new_dirs:
                        row.update({
                            "status": "failed",
                            "error": "pipeline_finished_without_reports",
                        })
                        logger.error(
                            f"❌ [{m.idx}/26] 失败 | 流水线返回但未生成报告目录 | "
                            f"Scout/Miner/Inspector: {row['scout_count']}/{row['miner_count']}/{row['inspector_count']} | "
                            f"耗时: {duration}s"
                        )
                    else:
                        row.update({"status": "success"})
                        logger.success(
                            f"✅ [{m.idx}/26] 完成 | 入库: {row['audited_assets']} | "
                            f"Scout/Miner/Inspector: {row['scout_count']}/{row['miner_count']}/{row['inspector_count']} | "
                            f"耗时: {duration}s"
                        )
                except Exception as e:
                    duration = int((datetime.now() - started).total_seconds())
                    row.update({
                        "status": "failed",
                        "duration_sec": duration,
                        "error": str(e),
                        "finished_at": datetime.now().isoformat(),
                    })
                    logger.error(f"❌ [{m.idx}/26] 失败: {e}")
                    logger.debug(traceback.format_exc())

                self._append_result(row)
                try:
                    self._write_summaries()
                except Exception as e:
                    logger.error(f"⚠️ 汇总写入失败（不中断批跑）: {e}")
                gc.collect()

                sleep_sec = self.cooldown_sec if row["status"] == "success" else self.deep_cooldown_sec
                logger.info(f"⏳ 冷却 {sleep_sec}s 后进入下一任务...")
                await asyncio.sleep(sleep_sec)

        except KeyboardInterrupt:
            logger.warning("🛑 检测到中断，已保存断点，可稍后继续。")
        finally:
            await pipeline.close()
            try:
                self._write_summaries()
            except Exception as e:
                logger.error(f"⚠️ 最终汇总写入失败: {e}")
            logger.info("🏁 批量任务结束。")
            logger.info(f"📊 汇总 JSON: {self.summary_json_path}")
            logger.info(f"📊 汇总 CSV : {self.summary_csv_path}")
            logger.info(f"📊 汇总 MD  : {self.summary_md_path}")


if __name__ == "__main__":
    runner = AerospaceBatchRunner()
    asyncio.run(runner.run())
