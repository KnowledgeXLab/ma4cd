"""
URL 分级器 (LLM 驱动版) - 将 URL 智能分类为 L1/L2/L3/L4 层级
严格遵循通用场景，无领域硬编码。已加入 task_context 主题对齐校验。
"""

import sys
import os
import aiohttp
from bs4 import BeautifulSoup
from typing import Dict, Optional, Any
from loguru import logger

# 引入项目根目录以支持绝对路径导入
current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.abspath(os.path.join(current_dir, "../../../"))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

# 导入你写好的 MinerLLMClient
try:
    from agents.miner.llms.miner_llm import MinerLLMClient as MinerLLM
except ImportError:
    logger.warning("未能导入 MinerLLM，请确保 LLM 接口可用。")
    MinerLLM = None

class URLClassifier:
    """基于大模型的 URL 层级与主题语义分类器"""
    
    def __init__(self):
        self.session: Optional[aiohttp.ClientSession] = None
        self.llm = MinerLLM() if MinerLLM else None
        
        # 增加通用 User-Agent 伪装，降低 403 拦截率
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.5'
        }

    # 🌟 修复核心：增加 task_context 和 **kwargs 兼容接口
    async def classify_url(self, url: str, task_context: str = "", **kwargs) -> Dict[str, Any]:
        """分类单个 URL，完全依赖真实的网页内容、任务上下文和大模型语义判断"""
        if not self.session:
            self.session = aiohttp.ClientSession(headers=self.headers)
            
        try:
            # 1. 获取真实网页内容 (绝不使用假数据)
            content_text = await self._fetch_and_clean_content(url)
            if not content_text:
                return {"url": url, "tier": "UNKNOWN", "confidence": 0.0, "reason": "无法获取或解析网页真实内容 (可能被拦截或死链)"}

            # 2. 构建包含“全局任务上下文”的 Prompt
            system_prompt = self._build_system_prompt()
            truncated_content = content_text[:15000] 
            
            user_prompt = f"分析以下目标：\nURL: {url}\n\n"
            if task_context:
                user_prompt += f"【🚨 全局核心任务 (最高判断标准)】：\n{task_context}\n\n"
                user_prompt += "特别注意：请严格核对网页内容是否与上述任务匹配。如果领域、国家或主题明显不符，请果断判定为 UNKNOWN！\n\n"
                
            user_prompt += f"【网页真实文本片段】:\n{truncated_content}\n\n请严格按照 System Prompt 的定义输出 JSON 结果。"
            
            # 3. 调用大模型进行判断
            result = await self.llm.ainvoke_json(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                temperature=0.1 # 保持极低温度，客观定级
            )
            
            if "error" in result:
                 return {
                     "url": url, 
                     "tier": "UNKNOWN", 
                     "confidence": 0.0, 
                     "reason": f"LLM 响应解析异常: {result.get('raw', '')[:50]}"
                 }
                 
            # 4. 数据格式归一化清洗 (保证下游不出错)
            tier = str(result.get("tier", "UNKNOWN")).upper()
            if tier not in ["L1", "L2", "L3", "L4"]:
                tier = "UNKNOWN"
                
            result["tier"] = tier
            result["url"] = url
            return result
            
        except Exception as e:
            logger.error(f"❌ LLM URL分类失败 {url}: {e}")
            return {
                "url": url,
                "tier": "UNKNOWN",
                "confidence": 0.0,
                "reason": f"System Error: {str(e)}"
            }

    def _build_system_prompt(self) -> str:
        """核心定义，直接喂给大模型"""
        return """你是一个全球数据线索挖掘系统中的高级分类专家。
你的任务是分析提供的 URL 及其网页文本内容，并结合给定的【全局核心任务】（如果有），将其严格归类为以下层级之一。
该系统适用于所有科研、医疗、经济、社会领域，请保持客观、通用的语义判断。

【层级严格定义】：
- L1 (枢纽/门户): 机构、组织、政府或大型综合性网站的顶级主页。流量分发中心，通常不包含具体数据。
- L2 (聚合搜索页): 数据库门户、目录页或搜索聚合页。特征是包含搜索框、筛选器或大量指向具体数据的列表，自身并非单一数据集。
- L3 (数字数据集): 存在于互联网上的具体、独立的数字形态数据集。特征是页面内包含可直接获取或申请下载的数字文件（如CSV、JSON、数据库导出包等）或数字 API 端点。
- L4 (物理资产线索): 仅存在于现实物理世界中的数据资源线索。特征是页面提供的是实体资源的元数据（如：馆藏号、索书号、博物馆地址、线下借阅指南、生物标本存放地等），在互联网上【没有】其对应的数字内容文件可供下载。
- UNKNOWN (跑题/无效): 网页内容与用户的【全局核心任务】无关，或者是无意义的登录页(Login)、纯新闻稿、帮助文档(FAQ)、空白页。

请仔细甄别 L3 和 L4 的区别：如果有数字文件下载/获取，就是 L3；如果是纯物理实体的信息记录，则是 L4。

输出格式必须为原生 JSON 对象：
{
    "tier": "L1|L2|L3|L4|UNKNOWN",
    "confidence": 0.95,
    "reason": "简要说明你分类的理由。如果是跑题，请明确指出为何与任务不符。",
    "evidence": ["支持判断的页面关键短语1", "支持判断的页面关键短语2"]
}
"""

    async def _fetch_and_clean_content(self, url: str) -> str:
        """真实抓取网页并提取纯文本，去除无用标签"""
        try:
            async with self.session.get(url, timeout=15) as response:
                # 遇到封锁或死链直接返回空
                if response.status >= 400:
                    logger.warning(f"真实访问失败 {url}, HTTP {response.status}")
                    return ""
                
                html = await response.text()
                soup = BeautifulSoup(html, 'html.parser')
                
                # 去除脚本和样式，保留纯粹的语义文本供 LLM 阅读
                for script in soup(["script", "style", "noscript", "meta", "link"]):
                    script.decompose()
                
                text = soup.get_text(separator=' ', strip=True)
                return text
        except Exception as e:
            logger.error(f"抓取页面内容异常 {url}: {e}")
            return ""

    async def close(self):
        """关闭 HTTP 会话"""
        if self.session:
            await self.session.close()
            self.session = None