import os
import json
import asyncio
import re
from datetime import datetime
from collections import Counter
from urllib.parse import urlparse
from loguru import logger
import sys

# 尝试导入大模型客户端，用于通过 Prompt 生成报告
try:
    from agents.miner.llms.miner_llm import MinerLLMClient
except ImportError:
    logger.error("❌ 无法导入 MinerLLMClient，请检查环境路径。")
    sys.exit(1)


class ReportGenerator:
    """
    全链路 LLM 驱动报告生成器 (LLM-Driven Report Generator)
    升级版：采用 Map-Reduce 架构，大模型仅负责语义分类，Python 负责绝对精准的数学统计与排版。
    """
    def __init__(self, run_id: str = "MA4CD_MISSION"):
        self.run_id = run_id
        self.timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.base_dir = os.path.join("reports", f"{self.timestamp}_{self.run_id}")
        os.makedirs(self.base_dir, exist_ok=True)
        
        # 实例化大模型客户端
        report_timeout = float(os.getenv("MA4CD_REPORT_TIMEOUT", "180"))
        self.llm = MinerLLMClient(timeout=report_timeout) 
        logger.info(f"📝 ReportGenerator 初始化完成，输出目录: {self.base_dir}")

    def _save_md(self, filename: str, content: str) -> str:
        """持久化保存 Markdown 文件"""
        path = os.path.join(self.base_dir, filename)
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(content)
            logger.success(f"📄 报告已保存: {path}")
            return path
        except Exception as e:
            logger.error(f"❌ 报告保存失败 {filename}: {e}")
            return "Save Failed"

    @staticmethod
    def _extract_commander_context(commander_plan: dict) -> dict:
        """
        兼容 cmd_result / task_config 两种结构，避免 Scout 报告读取到空 Commander 片段。
        """
        if not isinstance(commander_plan, dict):
            return {
                "core_intent": "",
                "search_queries": [],
                "constraints": [],
                "positive_signals": [],
                "negative_signals": []
            }

        task_config = commander_plan.get("task_config", {})
        if not isinstance(task_config, dict):
            task_config = {}

        search_queries = task_config.get("search_queries", commander_plan.get("search_queries", []))
        if not isinstance(search_queries, list):
            search_queries = []

        scoring = task_config.get("scoring_rubric", commander_plan.get("scoring_rubric", {}))
        if not isinstance(scoring, dict):
            scoring = {}

        constraints = task_config.get("constraints", commander_plan.get("constraints", []))
        if not isinstance(constraints, list):
            constraints = []

        return {
            "core_intent": commander_plan.get("core_intent", task_config.get("core_intent", "")),
            "search_queries": search_queries,
            "constraints": constraints,
            "positive_signals": scoring.get("positive_signals", []),
            "negative_signals": scoring.get("negative_signals", []),
        }

    @staticmethod
    def _split_urls_for_scout_reporting(urls: list) -> tuple[list, list]:
        """
        将 URL 分为“容器入口型”与“叶子资产型”，避免把单篇 PDF/论文页当高价值主目标。
        """
        file_exts = (
            ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".csv", ".zip", ".gz",
            ".rar", ".7z", ".ppt", ".pptx", ".txt", ".xml", ".json"
        )
        leaf_patterns = (
            "/doi/", "/abs/", "/article/", "/articles/", "/news/", "/press-release/",
            "/publication/", "/publications/"
        )
        container_markers = (
            "database", "databases", "repository", "archive", "archives", "catalog",
            "library", "portal", "dataset", "datasets", "search", "index", "collections",
            "data", "standards"
        )

        container_urls = []
        leaf_urls = []

        for raw in urls or []:
            u = str(raw or "").strip()
            if not u.startswith("http"):
                continue
            l = u.lower()
            parsed = urlparse(l)
            path = parsed.path or ""

            is_leaf = path.endswith(file_exts) or any(p in l for p in leaf_patterns)
            is_container = any(m in l for m in container_markers)

            if is_leaf and not is_container:
                leaf_urls.append(u)
            else:
                container_urls.append(u)

        # 去重保序
        def uniq(seq):
            seen = set()
            out = []
            for x in seq:
                if x not in seen:
                    seen.add(x)
                    out.append(x)
            return out

        return uniq(container_urls), uniq(leaf_urls)

    @staticmethod
    def _validate_scout_report(report_md: str, commander_ctx: dict) -> list[str]:
        """
        报告质量闸门：
        1) 禁止出现“Commander 片段为空 []”这种断层叙述（当上下文实际存在时）
        2) 禁止把单篇 PDF/DOI/论文详情页写入“高价值 URL 列表”
        """
        issues = []
        txt = str(report_md or "")
        txt_l = txt.lower()

        if commander_ctx.get("search_queries"):
            if ("片段为空" in txt) or ("无法直接解析其具体的战略目标" in txt) or ("(`[]`)" in txt):
                issues.append("commander_context_missing_statement")

        high_value_match = re.search(
            r"(高价值\s*url\s*列表[\s\S]{0,5000})",
            txt,
            flags=re.IGNORECASE
        )
        high_block = high_value_match.group(1).lower() if high_value_match else txt_l
        if re.search(r"\.pdf(\b|`)|/doi/|arxiv\.org/abs|单篇", high_block, flags=re.IGNORECASE):
            issues.append("single_pdf_or_article_in_high_value_list")

        return issues

    @staticmethod
    def _build_scout_report_fallback(commander_ctx: dict, scout_urls: list) -> str:
        """
        无模型兜底：确保不违反 Commander 约束和任务语义一致性。
        """
        container_urls, leaf_urls = ReportGenerator._split_urls_for_scout_reporting(scout_urls)

        # 域名频次
        domains = []
        for u in scout_urls:
            try:
                d = urlparse(str(u)).netloc.lower()
                if d:
                    domains.append(d)
            except Exception:
                continue
        domain_counter = Counter(domains).most_common(12)

        lines = []
        lines.append("# Scout 侦察报告（规则兜底版）")
        lines.append("")
        lines.append("## 1. 对 Commander 意图的响应说明")
        lines.append("")
        lines.append(f"- **核心意图**：{commander_ctx.get('core_intent', '') or '未提供'}")
        lines.append(f"- **搜索查询数量**：{len(commander_ctx.get('search_queries', []) or [])}")
        lines.append("- **一致性约束**：单篇论文/单篇报告/PDF 直链不作为高价值主目标，仅作为入口线索。")
        lines.append("")
        lines.append("## 2. 捕获站点的宏观域名分布")
        lines.append("")
        if domain_counter:
            lines.append("| 域名 | 频次 |")
            lines.append("|:---|---:|")
            for d, c in domain_counter:
                lines.append(f"| `{d}` | {c} |")
        else:
            lines.append("- 无可统计域名。")
        lines.append("")
        lines.append("## 3. 高价值入口型 URL（容器优先）")
        lines.append("")
        lines.append("> 仅展示疑似门户/数据库/目录入口，不展示单篇 PDF/论文详情页。")
        lines.append("")
        for i, u in enumerate(container_urls[:20], 1):
            lines.append(f"{i}. {u}")
        if not container_urls:
            lines.append("- 本轮未发现明显容器入口。")
        lines.append("")
        lines.append("## 4. 叶子资产线索（不计入高价值主清单）")
        lines.append("")
        for i, u in enumerate(leaf_urls[:15], 1):
            lines.append(f"{i}. {u}")
        if not leaf_urls:
            lines.append("- 无叶子资产线索。")

        return "\n".join(lines)

    async def generate_commander_report(self, user_query: str, commander_plan: dict) -> str:
        """1. 指挥官报告：解析人类命令的结果"""
        logger.info("🧠 正在请求大模型生成 Commander 战略报告...")
        sys_prompt = "你是一位高级战略分析师。你的任务是将 Commander Agent 生成的原始 JSON 规划，转化为一份专业、易读的 Markdown 战略报告。"
        user_prompt = f"""
请根据以下人类原始需求和 Commander 的解析结果，生成一份 Markdown 报告。
报告需重点展示：
1. 人类核心意图的解析。
2. 战略目标的拆解。
3. 下发的具体子任务和执行策略。

人类原始需求："{user_query}"
Commander 原始解析结果：
```json
{json.dumps(commander_plan, ensure_ascii=False, indent=2)}
```
请输出纯 Markdown 内容。
"""
        report_md = await self.llm.ainvoke(system_prompt=sys_prompt, user_prompt=user_prompt, use_big_brain=True)
        return self._save_md("1_Commander_Strategy_Report.md", report_md)

    async def generate_scout_report(self, commander_plan: dict, scout_urls: list) -> str:
        """2. 侦察兵报告：理解指挥官意图及广域搜寻结果"""
        logger.info("🛰️ 正在请求大模型生成 Scout 侦察报告...")
        commander_ctx = self._extract_commander_context(commander_plan)
        container_urls, leaf_urls = self._split_urls_for_scout_reporting(scout_urls)

        sys_prompt = """你是一位 OSINT (开源情报) 侦察专家。你需要分析 Scout Agent 提供的目标 URL 列表，展示它如何贯彻 Commander 的战略意图。

硬约束：
1) 如果输入里已经有 Commander 上下文，严禁写“Commander 片段为空 []”或类似语句。
2) 单篇论文、单篇新闻、PDF 直链、DOI/ABS 页面属于“叶子资产线索”，不能进入“高价值 URL 主清单”。
3) 高价值 URL 主清单必须优先选择数据库入口/门户入口/目录索引等“容器型”链接。
"""
        user_prompt = f"""
请根据 Commander 的战略意图，分析 Scout 实际捕获的目标 URL 列表。
生成一份 Markdown 报告，需包含：
1. 对 Commander 意图的响应说明。
2. 捕获站点的宏观域名分布分析（发现了哪些高频域名，代表了什么机构）。
3. 真实锁定的高价值 URL 列表展示。
4. 叶子资产线索附录（单篇 PDF/论文/新闻仅放这里，不计入高价值主清单）。

Commander 战略上下文（非空时必须直接使用，不允许忽略）：
```json
{json.dumps(commander_ctx, ensure_ascii=False, indent=2)}
```

Scout 实际捕获的“容器入口候选 URL”（优先用于高价值主清单，截取前 80 条）：
```json
{json.dumps(container_urls[:80], ensure_ascii=False, indent=2)}
```
Scout 实际捕获的“叶子资产 URL”（仅附录展示，截取前 80 条）：
```json
{json.dumps(leaf_urls[:80], ensure_ascii=False, indent=2)}
```
Scout 实际捕获的真实 URL 列表（原始，截取前 100 条）：
```json
{json.dumps(scout_urls[:100], ensure_ascii=False, indent=2)}
```
请输出纯 Markdown 内容。
"""
        report_md = await self.llm.ainvoke(system_prompt=sys_prompt, user_prompt=user_prompt, use_big_brain=True)

        # 输出闸门：发现关键冲突则启用无模型兜底，保证报告不再自相矛盾
        issues = self._validate_scout_report(report_md, commander_ctx)
        if issues:
            logger.warning(f"⚠️ Scout 报告触发一致性闸门: {issues}，已启用规则兜底重写。")
            report_md = self._build_scout_report_fallback(commander_ctx, scout_urls)

        return self._save_md("2_Scout_Intel_Report.md", report_md)

    async def generate_miner_report(self, miner_items: list) -> str:
        """3. 矿工报告：深网挖掘的拓扑结果"""
        logger.info("⛏️ 正在请求大模型生成 Miner 挖掘报告...")
        sys_prompt = "你是一位深网数据挖掘专家。请将 Miner Agent 挖掘出的网页拓扑节点，整理成一份结构化的挖掘清单。"
        user_prompt = f"""
请分析 Miner 挖掘到的原始节点数据，生成一份 Markdown 报告。
重点列出挖掘到的具体链接、节点类型（如 List, Directory, Asset）及其拓扑潜力，无需进行语义真伪判定。

Miner 挖掘到的真实节点样本（截取前 150 条以控制上下文）：
```json
{json.dumps(miner_items[:150], ensure_ascii=False, indent=2)}
```
请输出纯 Markdown 内容。
"""
        report_md = await self.llm.ainvoke(system_prompt=sys_prompt, user_prompt=user_prompt, use_big_brain=True)
        return self._save_md("3_Miner_Excavation_Report.md", report_md)

    async def generate_inspector_report(self, audited_items: list, inspector_debug: dict | None = None) -> str:
        """4. 督察员报告：五维深度聚合报告 (分批精准打标 + Python统计排版)"""
        logger.info("🧐 开始高精度五维审计分析 (分批并行处理中)...")
        
        if not audited_items:
            return self._save_md("4_Inspector_Final_5D_Report.md", "# 暂无有效高价值资产\n\n本次挖掘未收获符合标准的资产。")

        # --- 第一步：定义强制结构化输出的分类法则（skill: report_taxonomy.yaml）---
        try:
            from utils.report_taxonomy import build_inspector_taxonomy_system_prompt, dimension_label_map
            sys_prompt = build_inspector_taxonomy_system_prompt()
            dimension_maps = dimension_label_map()
        except Exception:
            taxonomy_rules = """
【分类大纲 Codebook】
1. 领域维度: 科学与智能, 医学与健康, 经济与产业, 人文与社会, 未知
2. 数据形态: Structured, Textual, Multimedia, Model/Code, Knowledge, 未知
3. 渠道来源: 政府机构, 国际组织, 垂直领域公司, 行业媒体, 数据服务公司, 咨询公司, 研究机构, 行业组织, 开源/社交平台, 未知
4. 国家梯队: 第一梯队, 第二梯队, 第三梯队, 未知
5. 线索级别: L1/L2, L3, L4, 未知
"""
            sys_prompt = f"""你是一位极其严苛的首席数据资产审计官。
你需要对传入的 JSON 数据列表进行五维打标。

{taxonomy_rules}

【🔴 核心铁律】：
1. 必须输出且仅输出一个合法的 JSON 数组，严禁包含 ```json 代码块等任何 Markdown 修饰符！
2. JSON 对象必须完全遵循以下 Keys，并且 Values 必须严格从《分类大纲》中对应的选项里【一字不差】地提取：
[
  {{
    "url": "保留原始URL不变",
    "domain_dim": "选1个",
    "format_dim": "选1个",
    "source_dim": "选1个",
    "region_dim": "选1个",
    "level_dim": "选1个",
    "optimized_title": "根据URL或原标题，重写一个15字以内的专业机构或数据库背景介绍，严禁使用Traceback/Unknown等词"
  }}
]
3. 严禁胡乱归类！例如：nih.gov / cdc.gov 必须是“医学与健康”及“政府机构”。"""
            dimension_maps = {
                "domain": "领域维度",
                "format": "数据形态维度",
                "source": "渠道来源维度",
                "region": "国家和地区维度",
                "level": "L1~L4线索分级维度",
            }

        # --- 第二步：切片批处理 (Batching) 避免上下文崩溃 ---
        batch_size = 10
        all_analyzed_results = []
        
        for i in range(0, len(audited_items), batch_size):
            batch_items = audited_items[i : i + batch_size]
            
            # 简化上下文，精简 Token，帮助模型集中注意力
            simplified_batch = [
                {
                    "url": item.get("url", ""), 
                    "raw_title": item.get("title", "Unknown Page"), 
                    "level": item.get("level", "未知")
                } 
                for item in batch_items
            ]
            
            user_prompt = f"请对以下 {len(batch_items)} 条数据进行精准五维打标，仅返回 JSON 数组：\n{json.dumps(simplified_batch, ensure_ascii=False)}"
            
            try:
                # 强制使用低温度，保障输出稳定性和一致性
                llm_response = await self.llm.ainvoke(
                    system_prompt=sys_prompt, 
                    user_prompt=user_prompt, 
                    temperature=0.0, 
                    use_big_brain=True
                )
                
                # 强力清洗可能存在的 markdown 符号
                cleaned_response = llm_response.replace("```json", "").replace("```", "").strip()
                
                # 如果模型开头加了其他废话，尝试截取 [] 内部内容
                if not cleaned_response.startswith("["):
                    start_idx = cleaned_response.find("[")
                    end_idx = cleaned_response.rfind("]") + 1
                    if start_idx != -1 and end_idx != -1:
                        cleaned_response = cleaned_response[start_idx:end_idx]

                batch_result = json.loads(cleaned_response)
                
                if isinstance(batch_result, list):
                    all_analyzed_results.extend(batch_result)
                else:
                    raise ValueError("JSON 返回的不是 List 类型")
                    
            except Exception as e:
                logger.error(f"❌ 批次 {i//batch_size + 1} 大模型解析失败: {e}")
                # 兜底容错机制：绝不让一条报错毁掉整个报告
                for item in batch_items:
                    row = {
                        "url": item.get("url", ""),
                        "domain_dim": "未知",
                        "format_dim": "未知",
                        "source_dim": "未知",
                        "region_dim": "未知",
                        "level_dim": item.get("level", "未知"),
                        "optimized_title": item.get("title", "未命名资源"),
                    }
                    try:
                        from utils.report_taxonomy import match_host_hints
                        hints = match_host_hints(str(row.get("url") or ""))
                        if hints:
                            for k, v in hints.items():
                                if v:
                                    row[k] = v
                    except Exception:
                        pass
                    all_analyzed_results.append(row)

        try:
            from utils.report_taxonomy import enforce_host_hints_on_results
            all_analyzed_results = enforce_host_hints_on_results(all_analyzed_results)
        except Exception:
            pass

        # --- 第三步：Python 绝对精确统计 (永不幻觉) ---
        logger.info("🧮 正在用 Python 进行精确维度统计排版...")
        
        # 使用 Counter 进行精准计数
        stats = {
            "domain": Counter(item.get("domain_dim", "未知") for item in all_analyzed_results),
            "format": Counter(item.get("format_dim", "未知") for item in all_analyzed_results),
            "source": Counter(item.get("source_dim", "未知") for item in all_analyzed_results),
            "region": Counter(item.get("region_dim", "未知") for item in all_analyzed_results),
            "level": Counter(item.get("level_dim", "未知") for item in all_analyzed_results)
        }

        total_assets = len(all_analyzed_results)

        # --- 第四步：构建 Markdown 排版 ---
        md_lines = [
            "# 高价值资产深度审计报告",
            "",
            f"> **执行摘要**：本次行动共计成功萃取高价值数据线索 **{total_assets}** 条。所有维度统计均由底层引擎精确计算，确保 100% 无死角对齐。",
            "",
            "## 📊 数据概览盘点",
            ""
        ]

        for dict_key, cn_name in dimension_maps.items():
            md_lines.append(f"### 按【{cn_name}】分类")
            counter = stats[dict_key]
            # 按数量降序排列
            for name, count in counter.most_common():
                percentage = (count / total_assets) * 100 if total_assets > 0 else 0
                md_lines.append(f"- **{name}**: {count} 条 ({percentage:.1f}%)")
            md_lines.append("")

        # --- Optional: rejection explainability appendix ---
        if isinstance(inspector_debug, dict) and inspector_debug.get("rejection_summary"):
            rs = inspector_debug.get("rejection_summary") or {}
            buckets = rs.get("buckets") or {}
            bucket_labels = rs.get("bucket_labels") or {}
            top_samples = rs.get("top_samples") or {}
            md_lines.append("---")
            md_lines.append("## 🧯 拒绝原因分桶统计（Explainability）")
            md_lines.append("")
            md_lines.append(f"- **总拒绝数**：{int(rs.get('total_rejected', 0) or 0)}")
            md_lines.append("")
            if isinstance(buckets, dict) and buckets:
                md_lines.append("| 分桶 | 说明 | 数量 |")
                md_lines.append("|:---|:---|---:|")
                for k, v in buckets.items():
                    label = bucket_labels.get(k, k) if isinstance(bucket_labels, dict) else k
                    md_lines.append(f"| `{k}` | {label} | {int(v)} |")
                md_lines.append("")
            if isinstance(top_samples, dict) and top_samples:
                md_lines.append("### Top 样本（每桶最多 5 条）")
                md_lines.append("")
                for b, items in top_samples.items():
                    md_lines.append(f"#### `{b}`")
                    md_lines.append("")
                    if not isinstance(items, list) or not items:
                        md_lines.append("- （空）")
                        md_lines.append("")
                        continue
                    for i, it in enumerate(items[:5], 1):
                        url = str((it or {}).get("url", "")).strip()
                        title = str((it or {}).get("title", "")).strip()
                        reason = str((it or {}).get("reason", "")).strip()
                        score = (it or {}).get("score", None)
                        score_txt = "" if score is None else f" | score={score}"
                        md_lines.append(f"{i}. {title}{score_txt}")
                        md_lines.append(f"   - URL: {url}")
                        md_lines.append(f"   - Reason: {reason}")
                    md_lines.append("")

        md_lines.append("---")
        md_lines.append("## 📜 核心资产明细大表")
        md_lines.append("")
        md_lines.append("| 序号 | 优化后资源名称 | URL | 领域 | 形态 | 来源 | 梯队 | 级别 |")
        md_lines.append("|:---:|:---|:---|:---|:---|:---|:---|:---|")
        
        for idx, item in enumerate(all_analyzed_results, 1):
            title = item.get('optimized_title', '未知').replace('|', '&#124;') # 防止表格崩溃
            url = item.get('url', '')
            domain = item.get('domain_dim', '未知')
            fmt = item.get('format_dim', '未知')
            src = item.get('source_dim', '未知')
            reg = item.get('region_dim', '未知')
            lvl = item.get('level_dim', '未知')
            
            md_lines.append(f"| {idx} | **{title}** | [访问链接]({url}) | {domain} | {fmt} | {src} | {reg} | **{lvl}** |")

        final_md = "\n".join(md_lines)
        return self._save_md("4_Inspector_Final_5D_Report.md", final_md)

    async def generate_all_reports(
        self,
        user_query: str,
        commander_plan: dict,
        scout_urls: list,
        miner_items: list,
        audited_items: list,
        inspector_debug: dict | None = None,
    ):
        """外部统一调用接口：异步生成四份报告"""
        logger.info("🖨️ 开始并发生成 4 份 Agent 专属报告...")
        try:
            # 考虑到 API 速率限制，使用 await 串行生成最为稳妥
            await self.generate_commander_report(user_query, commander_plan)
            await self.generate_scout_report(commander_plan, scout_urls)
            await self.generate_miner_report(miner_items)
            await self.generate_inspector_report(audited_items, inspector_debug=inspector_debug)
            logger.success(f"🎉 4 份 Agent 报告已全部生成完毕！请查看 {self.base_dir} 目录。")
        except Exception as e:
            logger.error(f"❌ 报告聚合生成过程中发生错误: {e}")
