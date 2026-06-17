import os
import json
from datetime import datetime
from collections import defaultdict, Counter
import logging

logger = logging.getLogger("inspector.tools.report")

class ReportGenerator:
    def __init__(self, run_id: str = None, output_dir: str = "reports"):
        self.run_id = run_id or datetime.now().strftime("%Y%m%d_%H%M%S")
        self.output_dir = os.path.abspath(output_dir)
        os.makedirs(self.output_dir, exist_ok=True)
        self.report_path = os.path.join(self.output_dir, f"MA4CD_Inventory_{self.run_id}.md")

    def generate(self, passed_items: list, rejected_items: list, global_stats: dict) -> str:
        """
        生成严格按照 4 大维度划分的 Markdown 资产报告
        """
        logger.info(f"📄 正在生成最终资产审计报告，包含 {len(passed_items)} 条有效线索...")
        
        # --- 数据预处理与四维统计 ---
        level_groups = {"L1": [], "L2": [], "L3": [], "L4": [], "UNKNOWN": []}
        morphology_counter = Counter()
        channel_counter = Counter()
        region_counter = Counter()

        for item in passed_items:
            # 提取 4 大核心维度标签 (带默认值兜底)
            level = str(item.get("level", "UNKNOWN")).upper()
            morphology = str(item.get("morphology", "Unknown Format"))
            channel = str(item.get("channel", "Unknown Channel"))
            region = str(item.get("region", "Global"))

            # 分发到对应的 Level 组
            if level in level_groups:
                level_groups[level].append(item)
            else:
                level_groups["UNKNOWN"].append(item)

            # 统计其他三个维度
            morphology_counter[morphology] += 1
            channel_counter[channel] += 1
            region_counter[region] += 1

        # --- 组装 Markdown 报告 ---
        md_lines = []
        md_lines.append(f"# 🛡️ MA4CD 全球数据资产挖掘报告 (Executive Inventory)\n")
        md_lines.append(f"> **任务 ID**: `{self.run_id}`")
        md_lines.append(f"> **生成时间**: `{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}`")
        md_lines.append(f"> **有效资产总数**: `{len(passed_items)}` 条\n")
        md_lines.append(f"---\n")

        # ==========================================
        # 维度统计板块
        # ==========================================
        md_lines.append("## 📊 第一部分：四维资产统计透视\n")
        
        # 维度 1 & 2
        md_lines.append("### 1. 线索等级 (L1-L4) 与 数据形态分布")
        md_lines.append("| 线索等级 (Level) | 数量 | 占比 | | 数据形态 (Morphology) | 数量 | 占比 |")
        md_lines.append("| :--- | :--- | :--- | :--- | :--- | :--- | :--- |")
        
        # 动态对齐两个表格的行数
        levels_list = [(k, len(v)) for k, v in level_groups.items() if len(v) > 0]
        morph_list = morphology_counter.most_common()
        max_rows = max(len(levels_list), len(morph_list))
        
        for i in range(max_rows):
            l_str = f"| **{levels_list[i][0]}** | {levels_list[i][1]} | {levels_list[i][1]/len(passed_items)*100:.1f}% " if i < len(levels_list) else "| - | - | - "
            m_str = f"| {morph_list[i][0]} | {morph_list[i][1]} | {morph_list[i][1]/len(passed_items)*100:.1f}% |" if i < len(morph_list) else "| - | - | - |"
            md_lines.append(l_str + "| " + m_str)
        md_lines.append("\n")

        # 维度 3 & 4
        md_lines.append("### 2. 国家/地区 与 来源渠道分布 (Top 5)")
        md_lines.append("| 国家与地区 (Region) | 数量 | | 核心来源渠道 (Channel) | 数量 |")
        md_lines.append("| :--- | :--- | :--- | :--- | :--- |")
        
        reg_list = region_counter.most_common(5)
        chan_list = channel_counter.most_common(5)
        max_rows_rc = max(len(reg_list), len(chan_list))
        
        for i in range(max_rows_rc):
            r_str = f"| {reg_list[i][0]} | {reg_list[i][1]} " if i < len(reg_list) else "| - | - "
            c_str = f"| {chan_list[i][0]} | {chan_list[i][1]} |" if i < len(chan_list) else "| - | - |"
            md_lines.append(r_str + "| " + c_str)
        md_lines.append("\n---\n")

        # ==========================================
        # 资产明细板块 (严格按 L1-L4 划分)
        # ==========================================
        md_lines.append("## 💎 第二部分：核心资产明细清单\n")
        md_lines.append("> 资产已严格按照业务定义的 L1 (枢纽) 至 L4 (物理资产) 降序排列。\n\n")

        # 定义 L1-L4 的展示元数据 (对应你的截图)
        level_definitions = {
            "L1": ("枢纽级 (Hub)", "综合性托管平台，包含海量异构数据的托管平台。"),
            "L2": ("门户/套件 (Portal/Suite)", "同一机构发布的、同质化的数据集入口。"),
            "L3": ("独立数据库 (Sub-Database)", "特定领域的专业数据，功能独立、结构独特。"),
            "L4": ("私有/实体资产 (Asset)", "存在于物理世界、内网或需申请的库中（影子信息/联系人）。")
        }

        # 按层级依次渲染表格
        for level in ["L1", "L2", "L3", "L4"]:
            items_in_level = level_groups[level]
            if not items_in_level:
                continue
            
            title, desc = level_definitions[level]
            md_lines.append(f"### 🚀 【{level}】 {title}")
            md_lines.append(f"*{desc}*\n")
            md_lines.append(f"**共计发现 {len(items_in_level)} 条资产：**\n")
            
            # 表头 (融合了另外三个维度)
            md_lines.append("| 资源标题与链接 | 数据形态 | 国家/地区 | 来源渠道 | 简述/审计说明 |")
            md_lines.append("| :--- | :--- | :--- | :--- | :--- |")
            
            for item in items_in_level:
                # 安全提取字段
                title = str(item.get("title") or item.get("name") or "未命名资产").replace("|", "\|").replace("\n", " ")
                url = item.get("url", "#")
                morph = str(item.get("morphology", "-")).replace("|", "\|")
                reg = str(item.get("region", "-")).replace("|", "\|")
                chan = str(item.get("channel", "-")).replace("|", "\|")
                
                # 提取摘要或验证说明
                audit = item.get("audit_response", {})
                if isinstance(audit, dict):
                    desc = audit.get("justification") or audit.get("summary") or item.get("description") or "-"
                else:
                    desc = item.get("description") or "-"
                
                # 截断过长的描述防止表格撑爆
                desc = str(desc).replace("|", "\|").replace("\n", " ")
                if len(desc) > 80: desc = desc[:77] + "..."
                
                # 生成 Markdown 表格行
                md_lines.append(f"| [{title}]({url}) | `{morph}` | {reg} | {chan} | {desc} |")
            
            md_lines.append("\n")

        # 写入文件
        try:
            with open(self.report_path, 'w', encoding='utf-8') as f:
                f.write("\n".join(md_lines))
            logger.info(f"✅ 新版四维结构化报告已生成: {self.report_path}")
            return self.report_path
        except Exception as e:
            logger.error(f"❌ 报告写入失败: {e}")
            return "Failed to generate report"