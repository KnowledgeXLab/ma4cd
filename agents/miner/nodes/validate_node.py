import json
import time
import asyncio
from typing import Dict, Any, List
from loguru import logger
from state.miner_state import MinerState
# 适配新的异步单例模式
from llms import get_miner_llm

class ValidateNode:
    """
    ValidateNode (异步并发增强版)
    职责：
    1. 验证 L3 候选：区分独立子库 (L3) 和 目录导航 (L2)。
    2. 挽救机制：将误判的链接降级为 L2，加入递归队列。
    """
    def __init__(self):
        # 获取支持异步的 LLM 客户端
        self.llm = get_miner_llm()
        # 批处理大小 (避免 Prompt 过长)
        self.batch_size = 20

    async def execute(self, state: MinerState) -> MinerState:
        start_time = time.time()
        
        structured_data = getattr(state, "structured_data", {})
        candidates = structured_data.get("candidate_subportals", [])

        # 如果没有输入，直接返回（但不报错，因为可能在上一环节只发现了纯 L2）
        if not candidates:
            logger.info("ValidateNode 无待验证候选")
            state.mined_items = []
            state.downgraded_l2_directories = []
            # 保持 True，以免阻断流程中已有的 L2
            state.is_valid = True 
            return state

        logger.info(f"ValidateNode 开始验证 {len(candidates)} 个候选链接")

        try:
            # --- 1. 分流处理 (信任链策略) ---
            auto_approved = []
            to_verify = []

            for cand in candidates:
                # 只有极高置信度且 URL 特征明显的才免检
                # 比如包含 /database/, /search/ 且分数极高
                score = cand.get("confidence", 0.0)
                url = cand.get("url", "").lower()
                
                # 更加严格的免检逻辑，防止把 L2 混成 L3
                is_obvious_l3 = any(k in url for k in ['/db/', 'database', 'search', 'query'])
                
                if score >= 0.95 and is_obvious_l3:
                    cand['validation_source'] = "auto_high_confidence"
                    auto_approved.append(cand)
                else:
                    to_verify.append(cand)

            logger.info(f"✅ 自动通过: {len(auto_approved)} | 🧐 需 LLM 验证: {len(to_verify)}")

            # --- 2. 异步批量验证 ---
            verified_l3 = []
            downgraded_l2 = []

            if to_verify:
                # 切分批次
                batches = [to_verify[i : i + self.batch_size] for i in range(0, len(to_verify), self.batch_size)]
                
                # 创建并发任务
                tasks = [self._verify_batch_with_llm(batch) for batch in batches]
                results = await asyncio.gather(*tasks)

                # 聚合结果
                for res in results:
                    verified_l3.extend(res.get("valid_l3", []))
                    downgraded_l2.extend(res.get("downgraded_l2", []))

            # --- 3. 结果整合 ---
            final_l3_list = auto_approved + verified_l3
            
            # 构造 L3 输出项 (Standardized Output)
            mined_items = []
            for sub in final_l3_list:
                mined_items.append({
                    "url": sub.get("url"),
                    "title": sub.get("title", "Unknown L3"),
                    "confidence": sub.get("confidence", 0.9),
                    "reason": sub.get("reason", "Validation Passed"),
                    "source_clue_url": state.current_clue.get("url"),
                    "likely_level": "L3"
                })

            # 构造 L2 输出项 (URL List)
            # 去重：确保 L2 不在 L3 列表中，也不重复
            l3_urls = set(item["url"] for item in mined_items)
            unique_l2 = []
            seen_l2 = set()
            
            for item in downgraded_l2:
                u = item.get("url")
                if u and u not in l3_urls and u not in seen_l2:
                    unique_l2.append(u)
                    seen_l2.add(u)

            # 更新 State
            state.mined_items = mined_items
            state.downgraded_l2_directories = unique_l2
            
            state.validation_summary = {
                "input_count": len(candidates),
                "l3_confirmed": len(mined_items),
                "l2_downgraded": len(unique_l2)
            }
            
            # 只要有产出（无论是 L3 还是新的递归路径 L2），都视为有效
            state.is_valid = len(mined_items) > 0 or len(unique_l2) > 0
            state.validate_duration = time.time() - start_time
            
            logger.info(f"ValidateNode 产出: 🎯 L3={len(mined_items)}, 🔄 降级L2={len(unique_l2)}")

        except Exception as e:
            logger.error(f"ValidateNode 致命错误: {e}")
            import traceback
            logger.error(traceback.format_exc())
            state.error = str(e)
            state.is_valid = False

        return state

    async def _verify_batch_with_llm(self, batch: List[Dict]) -> Dict[str, List]:
        """
        处理单个批次的 LLM 验证，使用 ainvoke_json 保证稳定性
        """
        if not batch: return {}

        # 简化的 Prompt，聚焦于分类
        prompt_text = f"""
        你是一位极其严谨的数据资产审核员。
        请对以下候选 URL 进行分类验证。
        
        待验证列表:
        {json.dumps(batch, ensure_ascii=False)}

        【分类定义】
        1. **Valid L3 (独立子库)**: 
           - 这是一个**最终目的地**。
           - 页面上有搜索框、下载按钮、数据表格或具体的 Dataset 描述。
           - 例子: "GenBank Search", "COVID-19 Dataset Download", "US Census Data Tool".
        
        2. **Downgraded L2 (目录/列表)**:
           - 这是一个**中间页**。
           - 页面主要是一堆链接的列表 (List of Links)。
           - 你必须点击进去才能看到数据。
           - 例子: "All Resources A-Z", "Browse by Topic", "List of Journals".
           
        3. **Discard (无效)**:
           - 登录、注册、关于我们、博客文章、PDF文件链接。

        请返回 JSON:
        {{
            "valid_l3": [ {{"url": "...", "title": "...", "reason": "..."}} ],
            "downgraded_l2": [ {{"url": "...", "title": "...", "reason": "这是一个分类列表页"}} ]
        }}
        """

        try:
            # 使用 MinerLLMClient 的强力 JSON 模式
            result = await self.llm.ainvoke_json(
                system_prompt=prompt_text,
                user_prompt="请分类上述链接，严格区分 L3(工具/数据) 和 L2(目录)。",
                temperature=0.0
            )
            return result
            
        except Exception as e:
            logger.warning(f"Batch 验证失败: {e}")
            return {"valid_l3": [], "downgraded_l2": []}
