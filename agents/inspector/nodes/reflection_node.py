import json
import logging
import asyncio
import re
from typing import Dict, List, Any

logger = logging.getLogger("inspector.reflection")

class ReflectionNode:
    def __init__(self, llm_client):
        self.llm = llm_client
        # 限制并发数，防止瞬间把 LLM 的 Rate Limit 打爆
        self.semaphore = asyncio.Semaphore(5) 

    async def execute(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """
        执行反思逻辑 (并发版)
        """
        candidates = state.get("classified_items", [])
        rejected_history = state.get("rejected_items", [])
        
        # 分离出“需要反思”和“直接通过”的项
        to_reflect_tasks = []
        direct_pass_items = []
        
        logger.info(f"🤔 Reflection Node 启动 | 输入总量: {len(candidates)} 条")

        for item in candidates:
            # --- 规则筛选逻辑 ---
            
            # 1. L4 硬核文件，直接放行
            if item.get("level") == "L4":
                item['reflection_status'] = "Skipped (L4 Asset)"
                direct_pass_items.append(item)
                continue

            score = item.get("inspector_score", 0)
            level = item.get("level", "UNKNOWN")

            # 2. 触发反思的条件
            # 策略：门户(L1/L2)必查，L3分数中等(6.0-8.0)的查
            should_reflect = (level in ["L1", "L2"]) or (6.0 <= score <= 8.0)

            if should_reflect:
                # 放入待执行任务列表
                to_reflect_tasks.append(self._process_single_item(item))
            else:
                item['reflection_status'] = "Skipped (High Confidence)"
                direct_pass_items.append(item)

        # --- 并发执行反思 ---
        logger.info(f"⚡ 触发并发反思: {len(to_reflect_tasks)} 条任务")
        
        reflected_results = []
        if to_reflect_tasks:
            # 并发执行所有反思任务
            reflected_results = await asyncio.gather(*to_reflect_tasks)

        # --- 结果归拢 ---
        final_audited = direct_pass_items
        final_rejected = []

        for res in reflected_results:
            if res.get('is_valid_asset'): # 使用更明确的 key
                final_audited.append(res)
            else:
                final_rejected.append(res)

        total_rejected = rejected_history + final_rejected
        
        logger.info(f"✅ 反思结束 | 最终通过: {len(final_audited)} | 拦截驳回: {len(final_rejected)}")
        
        return {
            "audited_results": final_audited,
            "rejected_items": total_rejected
        }

    async def _process_single_item(self, item: Dict) -> Dict:
        """
        包装单个 item 的反思过程，用于并发调用
        """
        async with self.semaphore: # 限制并发量
            critique = await self._perform_critique(item)
        
        if critique['is_valid']:
            # 反思通过：加分奖励
            item['reflection_status'] = "Passed"
            item['reflection_reason'] = critique['reason']
            # 稍微加分，但不超过 10 分
            current_score = item.get("inspector_score", 0)
            item['inspector_score'] = min(10.0, current_score + 0.5)
            item['is_valid_asset'] = True
        else:
            # 反思驳回：降分并标记
            logger.warning(f"🚫 [反思拦截] {item.get('title')} | {critique['reason']}")
            item['reflection_status'] = "Rejected"
            item['reject_reason'] = f"Reflection: {critique['reason']}"
            item['inspector_score'] = 2.0 
            item['is_valid_asset'] = False
            
        return item

    async def _perform_critique(self, item: Dict) -> Dict:
        """调用 LLM 进行批判"""
        prompt = self._generate_dynamic_prompt(item)
        
        try:
            # 假设你的 client 已经封装好了 raw string -> json 的转换
            # 如果没有，建议在这里加一层 cleaning
            res = await self.llm.invoke_json(prompt)
            
            # 再次防御性检查
            if not isinstance(res, dict):
                # 尝试解析 text
                if hasattr(res, 'content'): res = json.loads(self._clean_json_str(res.content))
                else: raise ValueError("Invalid LLM response format")

            return {
                "is_valid": res.get("is_valid", False),
                "reason": res.get("reason", "No reason provided")
            }
        except Exception as e:
            logger.error(f"反思 LLM 调用失败: {e}")
            # 出错时策略：默认放行，但标记 Error
            return {"is_valid": True, "reason": "Reflection Skipped (System Error)"}

    def _clean_json_str(self, text: str) -> str:
        """清洗 Markdown 格式的 JSON 字符串"""
        text = text.strip()
        if text.startswith("```"):
            text = re.sub(r"^```json\s*", "", text)
            text = re.sub(r"\s*```$", "", text)
        return text

    def _generate_dynamic_prompt(self, item: Dict) -> str:
        level = item.get("level", "L3")
        title = item.get("title", "Unknown")
        desc = item.get("description", "")[:400] # 稍微增加上下文长度

        # 核心：利用思维链 (CoT) 的轻量版，要求 LLM 先判断性质再下结论
        
        common_criteria = """
        【通用驳回标准】
        1. 登录墙/付费墙：如果不登录完全看不到任何数据元数据，驳回。
        2. 纯新闻/博客：如果是"某公司发布了新数据"的新闻稿，驳回。
        3. 空壳页面：只有标题没有内容的占位符页面，驳回。
        """

        if level in ["L1", "L2"]:
            # 针对门户：防止把“公司首页”当成“数据门户”
            role_prompt = f"""
            角色：严格的数据门户审计员。
            任务：验证该 URL 是否为真正的"数据存储库/门户"。
            
            {common_criteria}
            
            【门户专属驳回标准】
            - 如果这只是一个组织的"关于我们"或"主页"，没有数据搜索/浏览入口 -> 驳回。
            - 如果这是一个软件产品的营销页面，而不是数据下载站 -> 驳回。
            """
        else:
            # 针对数据集：防止把“介绍文章”当成“数据本身”
            role_prompt = f"""
            角色：严格的科研数据审计员。
            任务：验证该 URL 是否为具体的"数据获取页面"。
            
            {common_criteria}
            
            【数据集专属驳回标准】
            - 如果页面只是在谈论数据的重要性，但没给下载链接或API -> 驳回。
            - 如果这是一个PDF报告的浏览页，而不是源数据 -> 驳回。
            """

        return f"""
        {role_prompt}

        [待审资产]
        标题: {title}
        描述: {desc}
        预判等级: {level}

        请以 JSON 格式输出结论：
        {{
            "is_valid": true/false,
            "reason": "简短中文理由，指出具体触犯了哪条驳回标准，或确认为有效资产"
        }}
        """