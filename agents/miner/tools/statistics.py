# agents/miner/tools/statistics.py

import json
import os
import time
from datetime import datetime
from typing import Dict, Any, List
from loguru import logger

class DetailedStatistics:
    """
    📊 矿工任务统计与可视化报告引擎
    功能：
    1. 统计挖掘产出质量
    2. 记录进化过程快照
    3. 生成人类可读的 Markdown 报告
    """
    def __init__(self, output_dir: str = "agents/miner/output"):
        self.output_dir = output_dir
        if not os.path.exists(self.output_dir):
            os.makedirs(self.output_dir)
            logger.info(f"📁 创建输出目录: {self.output_dir}")

    def generate_report(self, state: Any, duration: float) -> str:
        """
        根据 MinerState 生成最终可视化报告
        """
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        domain = getattr(state, "domain", "unknown_domain")
        run_id = getattr(state, "run_id", "manual_run")
        
        # 1. 提取关键指标
        final_items = getattr(state, "final_items", [])
        l3_count = len(state.structured_data.get("l3_candidates", [])) if hasattr(state, "structured_data") else 0
        quality_score = state.reflection_result.get("quality_score", 0.0) if hasattr(state, "reflection_result") else 0.0
        
        # 2. 构造文件名
        filename = f"miner_report_{domain}_{timestamp}.md"
        filepath = os.path.join(self.output_dir, filename)

        # 3. 编写 Markdown 内容
        report_content = [
            f"# 🛡️ 数据挖掘任务报告: {domain}",
            f"\n> **任务 ID**: `{run_id}` | **执行状态**: ✅ 成功\n",
            "---",
            "### 📈 核心执行指标",
            f"- **总耗时**: `{duration:.2f}s`",
            f"- **质量得分**: `{quality_score:.2f}`",
            f"- **原始线索提取 (L3)**: `{l3_count}` 条",
            f"- **最终去重记录 (L4)**: `{len(final_items)}` 条",
            f"- **当前进化代数**: `Gen {getattr(state, 'evolution_config', {}).get('generation', 'Unknown')}`",
            "\n---",
            "### 🧠 进化基因快照 (Evolution Overrides)",
            "本轮执行应用了以下进化策略补丁："
        ]

        # 注入进化补丁详情
        overrides = getattr(state, "prompt_overrides", {}).get("structure_node", {})
        if overrides:
            report_content.append("```json")
            report_content.append(json.dumps(overrides, indent=2, ensure_ascii=False))
            report_content.append("```")
        else:
            report_content.append("*本轮未触发特殊提示词偏移*")

        report_content.append("\n---")
        report_content.append("### 💎 识别到的真实 L3 数据库入口")
        report_content.append("| 资源名称 | 真实 URL | 判定置信度 | 判定理由 |")
        report_content.append("| :--- | :--- | :--- | :--- |")

        # 填充 L3 真实入口 (确保路径真实)
        l3_candidates = state.structured_data.get("l3_candidates", []) if hasattr(state, "structured_data") else []
        for item in l3_candidates:
            title = item.get("title", "Unknown")
            url = item.get("url", "#")
            conf = item.get("confidence", 0.0)
            reason = item.get("reason", "N/A")
            report_content.append(f"| {title} | [{url}]({url}) | `{conf}` | {reason} |")

        report_content.append("\n---")
        report_content.append("### 📝 反思记录 (Reflection)")
        issues = state.reflection_result.get("issues", []) if hasattr(state, "reflection_result") else []
        if issues:
            for issue in issues:
                report_content.append(f"- ⚠️ {issue}")
        else:
            report_content.append("- ✅ 本轮挖掘无显著异常")

        # 4. 写入文件
        try:
            with open(filepath, "w", encoding="utf-8") as f:
                f.write("\n".join(report_content))
            logger.success(f"📊 可视化报告已生成: {filepath}")
            return filepath
        except Exception as e:
            logger.error(f"❌ 报告文件写入失败: {e}")
            return ""

    def save_raw_data(self, state: Any, run_id: str) -> str:
        """
        保存原始运行记忆 (JSON)，用于后续复盘
        """
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"raw_memory_{run_id}_{timestamp}.json"
        filepath = os.path.join(self.output_dir, filename)
        
        raw_data = {
            "run_id": run_id,
            "timestamp": time.time(),
            "final_items": getattr(state, "final_items", []),
            "structured_data": getattr(state, "structured_data", {}),
            "reflection": getattr(state, "reflection_result", {}),
            "prompt_overrides": getattr(state, "prompt_overrides", {})
        }
        
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(raw_data, f, ensure_ascii=False, indent=2)
        
        return filepath