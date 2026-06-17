import json
from urllib.parse import urljoin # 🌟 引入 urljoin
from typing import Dict
from loguru import logger
from agents.miner.llms.miner_llm import MinerLLMClient
from agents.miner.tools.browse_page import BrowsePageTool

class L4RecordMiner:
    """
    L4RecordMiner (深层资产深度嗅探器 - 严谨版)
    已修复：严格对齐 L3/L4 物理世界定义、修复相对路径陷阱、优化文本截取。
    """
    def __init__(self, max_depth: int = 1):
        self.llm = MinerLLMClient()
        self.max_depth = max_depth
        self.browse_tool = BrowsePageTool() 

    async def mine_l4_records(self, url: str) -> Dict:
        logger.info(f"⛏️ [L4Miner] 正在嗅探影子线索 (LLM Mode): {url}")
        
        browse_res = await self.browse_tool.browse_resilient(url=url, use_js=True)
        if not browse_res.get("success"):
            logger.warning(f"[L4Miner] 页面加载失败，无法嗅探: {url}")
            return {"l3_sub_databases": [], "total_found": 0}

        all_links = browse_res.get("all_links", [])
        # 🌟 修复 3：优先使用清洗后的文本或 markdown，避免喂给大模型一堆 JS/CSS 源码
        page_text = browse_res.get("markdown", browse_res.get("text", browse_res.get("html", "")))
        
        md_links = []
        seen = set()
        for l in all_links:
            raw_href = l.get("url", "")
            text = l.get("text", "").strip()
            
            if not raw_href or len(raw_href) > 300: continue
            
            # 🌟 修复 2：将相对路径 (如 /docs/1.pdf) 转换为绝对路径 (https://...)
            absolute_href = urljoin(url, raw_href)
            
            if absolute_href in seen: continue
            seen.add(absolute_href)
            md_links.append(f"- [{text}]({absolute_href})")
            
        links_text = "\n".join(md_links[:150]) 
        # 截取前 12000 字符，因为纯文本信息密度更高
        text_snippet = page_text[:12000] 

        return await self._llm_classify_and_extract(text_snippet, links_text, url)

    async def _llm_classify_and_extract(self, page_text: str, links_text: str, base_url: str) -> Dict:
        # 🌟 修复 1：重写 Prompt，严格对齐 L3(数字) 和 L4(物理) 的定义！
        system_prompt = """你是一个顶级的数据寻宝专家。你的任务是从网页文本和链接中，找出高价值的“底层数据资产”。

【资产严格分类定义】(极度重要)：
- L3 (数字资产/独立数据库)：可以直接在互联网上访问、检索或下载的数字形态数据。例如：特定的子数据库入口、高级检索界面、直接的下载链接（如 PDF, CSV, ZIP, JSON 文件）。
- L4 (物理实体线索)：【仅】存在于现实物理世界中的资源线索。例如：线下档案馆的实体卷宗指南、博物馆未数字化的馆藏目录、实体生物标本的线下存放地址、需要写信或打电话去线下申请的机密数据。如果在网上能直接下载，【绝对不是 L4】！

输出严格的 JSON：
{
    "extracted_assets": [
        {
            "title": "资产或数据集的清晰名称",
            "url": "对应链接的完整URL",
            "level": "L3 或者 L4",
            "reason": "为什么提取它（必须说明是提供数字下载，还是物理馆藏线索）"
        }
    ]
}"""
        
        user_prompt = f"基础URL: {base_url}\n\n【页面纯文本内容】:\n{page_text}\n\n【页面包含的链接】:\n{links_text}\n\n请提取深层资产，如果没有则返回空列表。"

        try:
            response = await self.llm.ainvoke_json(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                temperature=0.1,
                use_big_brain=True
            )
            
            # 兼容 LLM 返回可能带有 error 的情况
            if isinstance(response, dict) and "error" in response:
                logger.error(f"❌ [L4Miner] LLM 拒绝响应: {response.get('error')}")
                return {"l3_sub_databases": [], "total_found": 0}
                
            parsed = response if isinstance(response, dict) else json.loads(response)
            extracted = parsed.get("extracted_assets", [])
            
            results = []
            for item in extracted:
                if item.get("url") and item.get("level") in ["L3", "L4"]:
                    results.append({
                        "title": item.get("title", "Unknown Asset"),
                        "url": item["url"],
                        "level": item["level"]
                    })
            
            logger.success(f"🎯 [L4Miner] 成功提取 {len(results)} 条深层线索！")
            return {
                "l3_sub_databases": results,
                "total_found": len(results)
            }
            
        except Exception as e:
            logger.error(f"❌ [L4Miner] 解析失败或异常: {e}")
            return {"l3_sub_databases": [], "total_found": 0}