import sys
import os
# 当前文件在 nodes/ → 向上 1 级到 miner
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

import asyncio
import json
import time
from typing import Any
from loguru import logger

from llms.miner_llm import create_miner_llm
from tools.browse_page import BrowsePageTool
from prompts.prompt import SYSTEM_PROMPT_EXTRACT_PLAN


class ExtractNode:
    """
    提取节点类
    独立运行，不依赖 seaf 框架
    """

    def __init__(self):
        self.llm = create_miner_llm()
        self.browse_tool = BrowsePageTool()

    async def execute(self, state: Any) -> Any:
        """
        执行提取逻辑（异步版本，因为 browse_tool 是 async）
        输入：state 对象（包含 task, current_clue 等）
        输出：更新后的 state 对象
        """
        start_time = time.time()

        current_clue = getattr(state, "current_clue", {})
        if not current_clue or "url" not in current_clue:
            state.error = "无有效线索 URL"
            state.is_valid = False
            state.extract_duration = time.time() - start_time
            logger.error(f"无有效线索 URL: {getattr(current_clue, 'url', '未知')}")
            return state

        url = current_clue["url"]
        title = current_clue.get("title", "未知标题")
        snippet = current_clue.get("snippet", "")
        tier = current_clue.get("tier", "tier1")

        logger.info(f"ExtractNode 开始处理门户: {url} (Tier: {tier})")

        plan_result = None

        try:
            # 1. 使用 LLM 生成提取规划
            plan_prompt = SYSTEM_PROMPT_EXTRACT_PLAN.format(
                task=getattr(state, "task", "未知任务"),
                url=url,
                title=title,
                snippet=snippet,
                tier=tier
            )

            # 打印原始请求（调试用）
            logger.debug(f"发送给 LLM 的 planning prompt: {plan_prompt[:500]}...")

            plan_result = self.llm.invoke_json(
                system_prompt=plan_prompt,
                user_prompt = (
                    "请严格只输出一个有效的 JSON 对象。输出必须从 '{' 开始，到 '}' 结束。"
                    "不要有任何换行、空格、前缀、后缀、引号开头、解释文字、代码块。"
                    "不要有 ```json 或任何 markdown。直接输出 JSON。"
                ),
                temperature=0.0,
                max_tokens=800
            )

            # 打印 LLM 返回的原始结果（调试用）
            logger.debug(f"LLM 返回的 plan_result (raw): {plan_result}")

            if "error" in plan_result:
                raise ValueError(f"规划生成失败: {plan_result['error']}")

            logger.debug(f"提取规划结果: {json.dumps(plan_result, ensure_ascii=False, indent=2)}")

        except Exception as plan_e:
            logger.warning(f"规划生成失败，使用默认规划: {str(plan_e)}")
            plan_result = {
                "strategy_summary": "默认提取策略（LLM 失败兜底）",
                "keywords": ["数据", "统计", "年鉴", "指标", "查询", "数据库", "thống kê", "dữ liệu"],
                "negative_keywords": ["About Us", "Contact", "News", "Blog", "Login", "首页", "登录"],
                "browse_instructions": "提取所有与数据、统计、数据库、年鉴、指标相关的导航栏和链接，忽略 About Us、Contact、News、Blog、Login 等非数据页面。判断是否是独立子库（有搜索框或数据界面）。",
                "expected_link_count": 20,
                "max_depth": 2,
                "tier_adjust": "无"
            }

        # 2. 从规划中取出关键参数
        instructions = plan_result.get("browse_instructions", "")
        negative_keywords = plan_result.get("negative_keywords", [])

        if negative_keywords:
            instructions += f"必须忽略以下栏目：{', '.join(negative_keywords)}"

        if not instructions:
            instructions = "提取所有与数据、统计、数据库、年鉴、指标相关的导航栏和链接，忽略非数据页面。"

        # 3. 调用 browse_page 工具（异步调用）
        try:
            logger.info(f"开始调用 browse_tool: {url}")
            logger.debug(f"使用指令: {instructions}")
            
            # 增强错误处理的异步调用
            browse_result = await asyncio.wait_for(
                self.browse_tool(
                    url=url,
                    instructions=instructions,
                    use_js=True,
                    timeout=60  # 减少超时时间
                ),
                timeout=120  # 外层超时保护
            )
            
            logger.debug(f"browse_tool 返回结果类型: {type(browse_result)}")
            logger.debug(f"browse_result 内容: {browse_result}")

            # 检查返回结果的有效性
            if browse_result is None:
                raise Exception("browse_tool 返回 None")
            
            # 处理不同的返回格式
            success = False
            error_msg = "未知错误"
            
            if hasattr(browse_result, "success"):
                success = browse_result.success
                error_msg = getattr(browse_result, "error", "页面访问失败")
            elif isinstance(browse_result, dict):
                success = browse_result.get("success", False)
                error_msg = browse_result.get("error", "页面访问失败")
            else:
                # 如果返回的是其他格式，尝试转换
                try:
                    if hasattr(browse_result, '__dict__'):
                        result_dict = browse_result.__dict__
                        success = result_dict.get("success", False)
                        error_msg = result_dict.get("error", "页面访问失败")
                except:
                    success = False
                    error_msg = f"无法解析 browse_result: {type(browse_result)}"

            if not success:
                raise Exception(f"页面访问失败: {error_msg}")

            logger.info(f"页面访问成功: {url}")

            # 4. 安全地提取数据
            try:
                if hasattr(browse_result, "html"):
                    state.extracted_content = browse_result.html or ""
                elif isinstance(browse_result, dict):
                    state.extracted_content = browse_result.get("html", "")
                else:
                    state.extracted_content = ""

                if hasattr(browse_result, "all_links"):
                    state.raw_links = browse_result.all_links or []
                elif isinstance(browse_result, dict):
                    state.raw_links = browse_result.get("all_links", [])
                else:
                    state.raw_links = []

                # nav_links 可能不存在，使用 all_links 作为备选
                if hasattr(browse_result, "nav_links"):
                    state.nav_links = browse_result.nav_links or state.raw_links
                elif isinstance(browse_result, dict):
                    state.nav_links = browse_result.get("nav_links", state.raw_links)
                else:
                    state.nav_links = state.raw_links

                # 构建 metadata
                metadata = {"extract_plan": plan_result}
                
                if hasattr(browse_result, "title"):
                    metadata["title"] = browse_result.title or title
                elif isinstance(browse_result, dict):
                    metadata["title"] = browse_result.get("title", title)
                else:
                    metadata["title"] = title

                if hasattr(browse_result, "description"):
                    metadata["description"] = browse_result.description or ""
                elif isinstance(browse_result, dict):
                    metadata["description"] = browse_result.get("description", "")
                else:
                    metadata["description"] = ""

                if hasattr(browse_result, "html_length"):
                    metadata["html_length"] = browse_result.html_length or 0
                elif isinstance(browse_result, dict):
                    metadata["html_length"] = browse_result.get("html_length", 0)
                else:
                    metadata["html_length"] = len(state.extracted_content)

                state.metadata = metadata
                state.is_valid = True
                state.extract_duration = time.time() - start_time

                logger.info(f"ExtractNode 完成: {url}，提取到 {len(state.raw_links)} 个链接")

            except Exception as data_e:
                logger.error(f"数据提取异常: {str(data_e)}")
                # 即使数据提取失败，也尝试设置基本信息
                state.extracted_content = ""
                state.raw_links = []
                state.nav_links = []
                state.metadata = {"extract_plan": plan_result, "title": title}
                state.is_valid = False
                state.error = f"数据提取失败: {str(data_e)}"
                state.extract_duration = time.time() - start_time

        except asyncio.TimeoutError:
            error_msg = f"页面访问超时: {url}"
            logger.error(error_msg)
            state.error = error_msg
            state.is_valid = False
            state.extract_duration = time.time() - start_time

        except Exception as e:
            error_msg = f"browse_page 执行异常: {url} - {str(e)}"
            logger.error(error_msg)
            state.error = error_msg
            state.is_valid = False
            state.extract_duration = time.time() - start_time

        return state
