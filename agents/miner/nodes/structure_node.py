# agents/miner/nodes/structure_node.py
"""
Miner Agent 的 StructureNode
职责：
1. 接收 extract_node 输出的原始链接列表（raw_links / nav_links）
2. 清洗、分类、去重、打分
3. 构建简化的"导航目录树"
4. 初步识别 L3 子库候选（confidence > 0.6）
5. 为 validate_node 准备结构化候选列表
"""

import json
import time
from typing import Dict, Any, List
from urllib.parse import urlparse, urljoin
from loguru import logger

from state.miner_state import MinerState
from llms.miner_llm import create_miner_llm


class StructureNode:
    """
    结构化节点 - 将原始链接整理为可判断的目录结构
    """

    def __init__(self):
        self.llm = create_miner_llm()  # 用于更智能的分类（可选降级为规则）

        # L3 子库高价值关键词（可扩展）
        self.l3_keywords = [
            "database", "数据查询", "指标查询", "统计年鉴", "普查", "年鉴", "时间序列",
            "数据下载", "批量下载", "api", "open data", "数据接口", "数据中心", "数据门户",
            "工业统计", "人口普查", "经济指标", "企业库", "企业名录", "月度数据", "季度数据", 
            "年度数据", "部门数据", "普查数据"
        ]

        # 噪音关键词（Negative Logic）
        self.noise_keywords = [
            "about", "contact", "news", "blog", "login", "register", "sitemap", "privacy",
            "terms", "help", "faq", "公告", "通知", "新闻", "动态", "关于我们", "联系我们",
            "登录", "注册", "首页", "帮助"
        ]

    async def execute(self, state: MinerState) -> MinerState:
        """
        执行结构化整理（异步版本）
        """
        start_time = time.time()

        # 用属性访问（不再用 .get）
        raw_links = getattr(state, "raw_links", [])
        nav_links = getattr(state, "nav_links", [])
        all_links = list({link["url"]: link for link in (raw_links + nav_links)}.values())  # 合并去重

        if not all_links:
            state.error = "无可用链接进行结构化分析"
            state.is_valid = False
            state.structure_duration = time.time() - start_time
            return state

        logger.info(f"StructureNode 开始处理 {len(all_links)} 个链接")

        try:
            # 1. 基础清洗与打分
            cleaned_links = []
            for link in all_links:
                url = link["url"]
                text = link.get("text", "").strip()
                if not text or len(text) < 2:
                    continue

                # Negative Logic 过滤
                if any(noise.lower() in text.lower() for noise in self.noise_keywords):
                    logger.debug(f"过滤噪音链接: {text}")
                    continue

                # 关键词匹配打分
                matched = [kw for kw in self.l3_keywords if kw.lower() in text.lower()]
                base_score = len(matched) * 0.3
                
                # 额外加分规则
                if "查询" in text or "database" in url.lower() or "data" in url.lower():
                    base_score += 0.4
                if "easyquery" in url.lower():  # 统计局特有的查询接口
                    base_score += 0.5
                if "年鉴" in text or "年报" in text:
                    base_score += 0.3  # 年鉴也是有价值的
                if "统计" in text:
                    base_score += 0.2

                confidence = min(1.0, max(0.0, base_score))

                cleaned_links.append({
                    "url": url,
                    "text": text,
                    "confidence": round(confidence, 3),
                    "matched_keywords": matched,
                    "path_depth": len(urlparse(url).path.split("/")) - 1
                })

            # 按 confidence 排序
            cleaned_links.sort(key=lambda x: x["confidence"], reverse=True)
            
            logger.info(f"清洗后保留 {len(cleaned_links)} 个有效链接")

            # 2. 构建简易目录树（层级结构）
            metadata = getattr(state, "metadata", {})
            directory_tree = {
                "level": 0,
                "node": metadata.get("title", "根门户") if isinstance(metadata, dict) else "根门户",
                "url": state.current_clue["url"],
                "children": []
            }

            # 简单层级分组（基于路径相似度）
            for link in cleaned_links[:30]:  # 只取前 30 个高分链接建树
                path_parts = [p for p in urlparse(link["url"]).path.split("/") if p]
                current = directory_tree
                for part in path_parts[:-1]:
                    child = next((c for c in current["children"] if c["node"] == part), None)
                    if not child:
                        child = {"level": current["level"] + 1, "node": part, "url": "", "children": []}
                        current["children"].append(child)
                    current = child
                # 叶子节点
                current["children"].append({
                    "level": current["level"] + 1,
                    "node": link["text"] or path_parts[-1] if path_parts else "未知",
                    "url": link["url"],
                    "confidence": link["confidence"]
                })

            # 3. LLM 辅助判断 L3 子库候选（智能层）
            candidate_subportals = []
            if len(cleaned_links) > 0:
                links_json = json.dumps(cleaned_links[:20], ensure_ascii=False)  # 前 20 个

                try:
                    # 构建完整的提示词
                    from prompts.prompt import SYSTEM_PROMPT_STRUCTURE
                    
                    prompt = SYSTEM_PROMPT_STRUCTURE.format(
                        links_json=links_json
                    )
                    
                    # 使用更简单的调用方式
                    response = self.llm.invoke(
                        prompt + "\n请严格输出 JSON 格式，从 { 开始到 } 结束，不要有任何其他内容。",
                        temperature=0.1,
                        max_tokens=1500
                    )
                    
                    logger.debug(f"LLM 原始响应: {response}")
                    
                    # 尝试解析 JSON
                    if isinstance(response, str):
                        # 清理响应，提取 JSON 部分
                        response = response.strip()
                        if response.startswith('```json'):
                            response = response.replace('```json', '').replace('```', '').strip()
                        elif response.startswith('```'):
                            response = response.replace('```', '').strip()
                        
                        # 找到第一个 { 和最后一个 }
                        start_idx = response.find('{')
                        end_idx = response.rfind('}')
                        
                        if start_idx != -1 and end_idx != -1 and end_idx > start_idx:
                            json_str = response[start_idx:end_idx+1]
                            analysis = json.loads(json_str)
                            candidate_subportals = analysis.get("potential_subportals", [])
                            logger.info(f"LLM 识别出 {len(candidate_subportals)} 个 L3 子库候选")
                        else:
                            raise ValueError("无法找到有效的 JSON 结构")
                    else:
                        raise ValueError(f"LLM 返回类型错误: {type(response)}")
                        
                except Exception as e:
                    logger.warning(f"LLM 结构化分析失败，使用规则候选: {str(e)}")
                    # 规则兜底：confidence > 0.6 的直接入选
                    candidate_subportals = [
                        {
                            "url": link["url"],
                            "title": link["text"],
                            "confidence": link["confidence"],
                            "reason": f"规则匹配 (关键词: {', '.join(link['matched_keywords']) if link['matched_keywords'] else '基础规则'})"
                        }
                        for link in cleaned_links if link["confidence"] > 0.6
                    ]
                    
                    # 如果规则兜底也没有结果，降低阈值
                    if not candidate_subportals:
                        candidate_subportals = [
                            {
                                "url": link["url"],
                                "title": link["text"],
                                "confidence": link["confidence"],
                                "reason": "降级规则匹配"
                            }
                            for link in cleaned_links[:5] if link["confidence"] > 0.3
                        ]

            logger.info(f"最终识别出 {len(candidate_subportals)} 个 L3 子库候选")

            # 4. 更新 state（全部用属性赋值）
            state.structured_data = {
                "directory_tree": directory_tree,
                "candidate_subportals": candidate_subportals,
                "filtered_links_count": len(cleaned_links),
                "top_candidates_count": len(candidate_subportals),
                "reason_summary": f"提取 {len(all_links)} → 清洗后 {len(cleaned_links)} → 最终识别 {len(candidate_subportals)} 个 L3 候选"
            }
            state.is_valid = len(candidate_subportals) > 0
            state.structure_duration = time.time() - start_time

            logger.info(f"StructureNode 完成: 识别出 {len(candidate_subportals)} 个 L3 子库候选")
            
            # 打印前几个候选用于调试
            for i, candidate in enumerate(candidate_subportals[:3]):
                logger.debug(f"候选 {i+1}: {candidate['title']} (confidence: {candidate['confidence']})")

        except Exception as e:
            logger.error(f"StructureNode 执行失败: {str(e)}")
            import traceback
            logger.error(f"详细错误: {traceback.format_exc()}")
            state.error = str(e)
            state.is_valid = False
            state.structure_duration = time.time() - start_time

        return state


# 简单测试
if __name__ == "__main__":
    import asyncio
    from state.miner_state import MinerState

    async def test():
        # 模拟测试数据
        test_state = MinerState(task="测试结构化")
        test_state.current_clue = {"url": "https://data.stats.gov.cn/", "title": "国家数据"}
        test_state.raw_links = [
            {"url": "https://data.stats.gov.cn/easyquery.htm?cn=A01", "text": "月度数据", "confidence": 0.0},
            {"url": "https://data.stats.gov.cn/easyquery.htm?cn=B01", "text": "季度数据", "confidence": 0.0},
            {"url": "https://data.stats.gov.cn/login.htm", "text": "登录", "confidence": 0.0}
        ]
        test_state.metadata = {"title": "国家统计局数据门户"}

        node = StructureNode()
        result_state = await node.execute(test_state)

        print("结构化结果：")
        print(json.dumps(result_state.structured_data, ensure_ascii=False, indent=2))

    asyncio.run(test())
