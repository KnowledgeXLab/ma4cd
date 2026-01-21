# agents/miner/nodes/validate_node.py
"""
Miner Agent 的 ValidateNode
职责：
1. 接收 structure_node 输出的候选子库列表
2. 对每个候选进行严格 L3 验证
3. 应用 Negative Logic、高光例外、confidence 打分
4. 决定最终分裂出的 L3 子线索（mined_items）
5. 如果产出太少或失败，标记整体失败（供反思）
"""

import json
import time
from typing import Dict, Any, List
from loguru import logger

from state.miner_state import MinerState
from llms.miner_llm import create_miner_llm
from prompts.prompt import SYSTEM_PROMPT_VALIDATION  # 从 prompt.py 导入


class ValidateNode:
    """
    验证节点类
    负责对候选子库进行最终 L3 判断 + 分裂决策
    """

    def __init__(self):
        self.llm = create_miner_llm()  # 用于最终验证

        # L3 必须满足的特征（至少 2 条）
        self.l3_required_features = [
            "独立名称或 Logo",
            "专用搜索框或数据筛选器",
            "路径明显不同（非首页子路径）",
            "包含数据表格、API 接口、批量下载入口"
        ]

        # 高光例外关键词（强制提升为 L3）
        self.highlight_keywords = [
            "AlphaFold", "GPT", "CRISPR", "mRNA", "DeepMind", "量子计算",
            "固态电池", "锂电池", "新能源", "核聚变"  # 可根据任务扩展
        ]

        # 最小线索阈值（如果少于这个数，整体失败）
        self.min_split_threshold = 1  # 降低阈值，避免过于严格

    async def execute(self, state: MinerState) -> MinerState:
        """
        执行验证逻辑（异步版本）
        输入：state 对象（包含 structured_data、candidate_subportals 等）
        输出：更新后的 state 对象
        """
        start_time = time.time()

        # 用属性访问（不再用 .get）
        structured_data = getattr(state, "structured_data", {})
        candidates = structured_data.get("candidate_subportals", [])  # candidates 是 dict，所以 .get 保留

        if not candidates:
            state.error = "无候选子库进行验证"
            state.is_valid = False
            state.validate_duration = time.time() - start_time  # 用属性赋值
            return state

        logger.info(f"ValidateNode 开始验证 {len(candidates)} 个候选子库")

        try:
            # 1. 准备验证提示词
            candidates_json = json.dumps(candidates, ensure_ascii=False, indent=2)

            prompt = SYSTEM_PROMPT_VALIDATION.format(
                candidates_json=candidates_json
            )

            # 2. 调用 LLM 进行严格验证（改进版本）
            try:
                response = self.llm.invoke(
                    prompt + "请严格输出 JSON 格式，从 { 开始到 } 结束，不要有任何其他内容。",
                    temperature=0.1,
                    max_tokens=2000
                )
                
                logger.debug(f"LLM 验证原始响应: {response}")
                
                # 解析 JSON（与 structure_node 相同的逻辑）
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
                        validation_result = json.loads(json_str)
                        logger.info("LLM 验证成功")
                    else:
                        raise ValueError("无法找到有效的 JSON 结构")
                else:
                    raise ValueError(f"LLM 返回类型错误: {type(response)}")
                    
            except Exception as e:
                logger.warning(f"LLM 验证失败，使用规则验证: {str(e)}")
                # 规则兜底验证
                validation_result = self._rule_based_validation(candidates)

            logger.debug(f"验证结果: {json.dumps(validation_result, ensure_ascii=False, indent=2)}")

            # 3. 提取有效子库
            valid_subportals = validation_result.get("valid_subportals", [])
            discarded = validation_result.get("discarded", [])
            overall_confidence = validation_result.get("overall_confidence", 0.0)
            reason_summary = validation_result.get("reason_summary", "")

            # 4. 生成 mined_items（最终输出的 L3 子线索）
            mined_items = []
            for sub in valid_subportals:
                # 降低阈值，confidence >= 0.5 即可
                if sub.get("confidence", 0.0) >= 0.5:
                    mined_items.append({
                        "url": sub["url"],
                        "title": sub["title"],
                        "confidence": sub["confidence"],
                        "reason": sub.get("reason", "验证通过"),
                        "source_clue_url": state.current_clue["url"],  # current_clue 是 dict，用 []
                        "likely_level": "L3"
                    })

            # 5. 更新 state（全部用属性赋值）
            state.mined_items = mined_items
            state.validation_summary = {
                "valid_count": len(valid_subportals),
                "discarded_count": len(discarded),
                "overall_confidence": overall_confidence,
                "reason_summary": reason_summary
            }
            state.is_valid = len(mined_items) >= self.min_split_threshold
            state.validate_duration = time.time() - start_time

            if not state.is_valid:
                state.error = f"产出子线索过少（{len(mined_items)} < {self.min_split_threshold}），需反思优化"

            logger.info(f"ValidateNode 完成: 验证出 {len(mined_items)} 个 L3 子库")

        except Exception as e:
            logger.error(f"ValidateNode 执行失败: {str(e)}")
            import traceback
            logger.error(f"详细错误: {traceback.format_exc()}")
            state.error = str(e)
            state.is_valid = False
            state.validate_duration = time.time() - start_time

        return state

    def _rule_based_validation(self, candidates: List[Dict]) -> Dict[str, Any]:
        """
        规则兜底验证（当 LLM 失败时使用）
        """
        valid_subportals = []
        discarded = []
        
        for candidate in candidates:
            confidence = candidate.get("confidence", 0.0)
            title = candidate.get("title", "")
            url = candidate.get("url", "")
            
            # 简单规则：confidence > 0.5 且不是明显的噪音
            noise_indicators = ["about", "contact", "news", "login", "help", "关于", "联系", "新闻", "登录", "帮助"]
            is_noise = any(noise.lower() in title.lower() for noise in noise_indicators)
            
            if confidence > 0.5 and not is_noise:
                valid_subportals.append({
                    "url": url,
                    "title": title,
                    "confidence": confidence,
                    "reason": f"规则验证通过 (confidence: {confidence})"
                })
            else:
                discarded.append({
                    "url": url,
                    "reason": f"规则过滤: confidence={confidence}, is_noise={is_noise}"
                })
        
        return {
            "valid_subportals": valid_subportals,
            "discarded": discarded,
            "overall_confidence": sum(s["confidence"] for s in valid_subportals) / len(valid_subportals) if valid_subportals else 0.0,
            "reason_summary": f"规则验证: {len(valid_subportals)} 个通过，{len(discarded)} 个被过滤"
        }


# 简单测试（可选）
if __name__ == "__main__":
    import asyncio
    from state.miner_state import MinerState

    async def test():
        # 模拟 state 对象（从 structure_node 输出）
        test_state = MinerState(task="挖掘越南统计数据")
        test_state.current_clue = {"url": "https://www.gso.gov.vn/"}
        test_state.structured_data = {
            "candidate_subportals": [
                {"url": "https://www.gso.gov.vn/en/px-web/?pxid=E0201", "title": "工业统计门户", "confidence": 0.85},
                {"url": "https://www.gso.gov.vn/about-us", "title": "关于我们", "confidence": 0.2}
            ]
        }

        node = ValidateNode()
        updated_state = await node.execute(test_state)

        print("验证结果：")
        print(f"mined_items: {updated_state.mined_items}")
        print(f"is_valid: {updated_state.is_valid}")

    asyncio.run(test())
