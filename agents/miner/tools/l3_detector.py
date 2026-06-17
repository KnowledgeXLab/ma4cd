"""
L3 数据集检测器 (LLM 驱动版)
专注于通过大模型验证目标页面是否真正包含可获取的【数字形式数据集】或【在线查询系统】。
"""

import sys
import os
from bs4 import BeautifulSoup
from typing import Dict, Any, Optional
from loguru import logger

current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.abspath(os.path.join(current_dir, "../../../"))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

try:
    from agents.miner.llms.miner_llm import MinerLLMClient as MinerLLM
    from agents.miner.tools.browse_page import BrowsePageTool
except ImportError as e:
    logger.warning(f"未能导入依赖: {e}，请确保 LLM 和抓取工具可用。")
    MinerLLM = None
    BrowsePageTool = None

class L3DatasetDetector:
    """基于大模型的 L3 数字数据集确诊器"""
    
    def __init__(self):
        self.llm = MinerLLM() if MinerLLM else None
        # 🚀 弃用裸奔的 aiohttp，引入带有隐身衣和 JS 渲染能力的 BrowsePageTool
        self.browser = BrowsePageTool(headless=True, max_retries=1)
        
        self.system_prompt = """
        你是一个严谨的数据资产审计员。你的唯一任务是判断目标网页是否是一个真实的【L3 级独立子库/数字数据集】。
        
        【判断准则】（必须满足其一）：
        1. 是数字文件库：页面提供可以直接下载的数字文件（如 CSV, JSON, ZIP, 数据集压缩包等）或 API 获取指南。
        2. 是在线检索系统：页面提供了一个【专门针对特定数据集合】的在线查询/搜索界面（Interactive Database/Search Form），允许用户通过检索词在线筛选并查看结构化数据。
        
        【排除准则】（绝不能判定为 L3）：
        1. 拒绝物理线索 (L4)：如果该页面仅仅是一张物理档案、博物馆藏品的信息登记页，且【必须线下访问或发邮件申请】，没有任何附带的数字资料，请判定为非 L3。
        2. 拒绝普通文章/聚合页：如果这是一个普通的维基百科文章、新闻报道，或是罗列了无数个不同网站的纯导航目录，请判定为非 L3。

        输出格式必须为原生 JSON 对象：
        {
            "is_l3": true 或 false,
            "level": "L3" (如果是) 或 "Junk" (如果不是),
            "confidence": 0.0到1.0的浮点数,
            "evidence": ["列出页面中证实或证伪其为数字数据集/在线查询系统的关键原话或元素"],
            "reason": "详细解释你为何做出这个判定"
        }
        """

    async def detect(self, url: str, html_content: str = None) -> Dict[str, Any]:
        """
        通过大模型检测是否为真实的 L3 数字数据集
        """
        content_text = ""
        
        # 1. 提取内容 (优先使用传入的 html，否则使用强大的浏览器抓取)
        if html_content:
            content_text = self._extract_text_from_html(html_content)
        else:
            try:
                # 🚀 使用 BrowsePageTool，自带防 403 和 JS 等待
                browse_res = await self.browser.browse_resilient(url=url, use_js=True)
                if not browse_res.get("success"):
                    # 🔴 核心修复 1：明确抛出 error 字段，触发上层的免杀跳过，绝不无脑拉黑！
                    return {"error": f"抓取失败: {browse_res.get('error')}", "url": url}
                
                html_content = browse_res.get("html", "")
                content_text = self._extract_text_from_html(html_content)
            except Exception as e:
                # 🔴 核心修复：网络级崩溃也要走免杀通道
                return {"error": f"抓取异常: {str(e)}", "url": url}

        if not content_text:
             # 如果页面真的空空如也，这确实是垃圾，正常返回
            return self._fallback_junk_response(url, "页面无可用文本内容")

        # 2. 请求大模型审计 (截取文本以适应窗口)
        truncated_content = content_text[:12000]
        prompt = f"请验证以下网页内容是否属于可数字获取的 L3 数据集或在线查询系统：\nURL: {url}\n\n内容:\n{truncated_content}\n\n请输出 JSON。"

        try:
            # 调用 MinerLLMClient 封装好的 ainvoke_json
            result = await self.llm.ainvoke_json(
                system_prompt=self.system_prompt,
                user_prompt=prompt
            )
            
            # 🔴 核心修复 2：兼容 LLM 返回的 error，直接向上传递，触发免杀！
            if "error" in result:
                return {"error": f"LLM 响应异常: {result.get('error')}", "url": url}
            
            # 数据格式补全，对齐 ma4cd agent 流转需要
            result["url"] = url
            result["is_valuable"] = result.get("is_l3", False)
            result["details"] = {"llm_audit_passed": True}
            
            return result
            
        except Exception as e:
            logger.error(f"L3 大模型检测失败 {url}: {e}")
            return {"error": f"LLM 调用抛出异常: {str(e)}", "url": url}

    def _extract_text_from_html(self, html: str) -> str:
        """从 HTML 中剥离脚本和样式，提取纯文本"""
        try:
            soup = BeautifulSoup(html, 'html.parser')
            for script in soup(["script", "style", "noscript", "svg"]):
                script.decompose()
            return soup.get_text(separator=' ', strip=True)
        except Exception:
            return ""

    def _fallback_junk_response(self, url: str, reason: str) -> Dict[str, Any]:
        """只有在确认页面无价值时才返回的 Junk 判定 (不含 error)"""
        return {
            "url": url,
            "level": "Junk",
            "is_valuable": False,
            "is_l3": False,
            "confidence": 0.0,
            "reason": reason,
            "evidence": []
        }

    async def close(self):
        # BrowsePageTool 会自行管理生命周期，无需额外清理
        pass

# 单例导出
l3_detector = L3DatasetDetector()