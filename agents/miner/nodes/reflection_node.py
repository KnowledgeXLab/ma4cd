'''
import time
import json
from typing import Dict, Any, List
from loguru import logger
from dataclasses import dataclass

from state.miner_state import MinerState
from llms.miner_llm import create_miner_llm

@dataclass
class ReflectionResult:
    """反思结果数据结构"""
    quality_score: float
    issues_found: List[str]
    recommendations: List[str]
    needs_human_review: bool
    confidence_adjustment: float
    classification_feedback: List[Dict]
    memory_guidance: Dict

class ReflectionNode:
    """
    基于记忆的反思节点
    """
    
    def __init__(self):
        self.llm = create_miner_llm()
        
        # 简化的反思提示模板
        self.reflection_prompt = """
你是一个数据挖掘质量评估专家。请对以下挖掘结果进行反思和评估：

## 原始任务
{task}

## 处理的线索
URL: {url}
标题: {title}
预期级别: {expected_level}

## 挖掘结果
成功率: {success_rate}
产出数量: {mined_count}
挖掘项目:
{mined_items}

## 请评估以下方面：

1. **分级准确性**: 挖掘出的项目是否真的是L3级别的数据资源？
2. **质量评分**: 给出0-1的质量分数
3. **发现的问题**: 列出具体的质量问题
4. **改进建议**: 如何提高挖掘质量
5. **人工审核**: 是否需要人工审核

请以JSON格式回复：
```json
{{
    "quality_score": 0.8,
    "classification_accuracy": 0.9,
    "issues_found": ["问题1", "问题2"],
    "recommendations": ["建议1", "建议2"],
    "needs_human_review": false,
    "confidence_adjustment": 0.1,
    "detailed_feedback": [
        {{
            "item_url": "具体URL",
            "original_classification": "L3",
            "suggested_classification": "L2",
            "reason": "原因说明"
        }}
    ]
}}
"""
        
        logger.info("ReflectionNode 初始化完成")  # ✅ 正确在 __init__ 方法内

    async def execute(self, state: MinerState) -> MinerState:
        """执行反思评估"""
        
        logger.info("开始执行反思评估...")
        start_time = time.time()
        
        try:
            # 1. 准备反思数据
            reflection_data = self._prepare_reflection_data(state)
            
            # 2. 执行LLM反思
            reflection_result = await self._perform_llm_reflection(reflection_data)
            
            # 3. 处理反思结果
            processed_result = self._process_reflection_result(reflection_result)
            
            # 4. 更新状态
            state.reflection_result = processed_result
            state.quality_score = processed_result.quality_score
            
            # 5. 根据反思结果调整挖掘项目
            if processed_result.quality_score < 0.6:
                state = self._apply_quality_adjustments(state, processed_result)
            
            state.is_valid = True
            logger.success(f"反思评估完成，质量分数: {processed_result.quality_score:.2f}")
            
        except Exception as e:
            logger.error(f"反思评估失败: {e}")
            state.error = f"反思评估失败: {str(e)}"
            state.is_valid = False
            
            # 创建默认反思结果
            state.reflection_result = ReflectionResult(
                quality_score=0.5,
                issues_found=[f"反思评估异常: {str(e)}"],
                recommendations=["建议人工检查"],
                needs_human_review=True,
                confidence_adjustment=0.0,
                classification_feedback=[],
                memory_guidance={}
            )
        
        finally:
            state.reflection_duration = time.time() - start_time
        
        return state

    def _prepare_reflection_data(self, state: MinerState) -> Dict:
        """准备反思数据"""
        
        current_clue = state.current_clue or {}
        mined_items = state.mined_items or []
        
        # 格式化挖掘项目
        mined_items_text = ""
        for i, item in enumerate(mined_items, 1):
            mined_items_text += f"{i}. {item.get('title', '无标题')}\n"
            mined_items_text += f"   URL: {item.get('url', '无URL')}\n"
            mined_items_text += f"   类型: {item.get('type', '未知')}\n"
            mined_items_text += f"   置信度: {item.get('confidence', 0):.2f}\n\n"
        
        return {
            'task': state.task,
            'url': current_clue.get('url', ''),
            'title': current_clue.get('title', ''),
            'expected_level': current_clue.get('likely_level', 'L2'),
            'success_rate': 1.0 if state.is_valid else 0.0,
            'mined_count': len(mined_items),
            'mined_items': mined_items_text or "无挖掘结果"
        }

    async def _perform_llm_reflection(self, reflection_data: Dict) -> Dict:
        """执行LLM反思"""
        
        prompt = self.reflection_prompt.format(**reflection_data)
        
        response = await self.llm.agenerate(
            prompt=prompt,
            max_tokens=1000,
            temperature=0.3
        )
        
        # 解析JSON响应
        try:
            content = response.get('content', '{}')
            # 提取JSON部分
            json_start = content.find('{')
            json_end = content.rfind('}') + 1
            if json_start != -1 and json_end > json_start:
                json_content = content[json_start:json_end]
                return json.loads(json_content)
            else:
                raise ValueError("未找到有效的JSON响应")
                
        except Exception as e:
            logger.error(f"解析反思结果失败: {e}")
            # 返回默认结果
            return {
                "quality_score": 0.5,
                "classification_accuracy": 0.5,
                "issues_found": ["LLM响应解析失败"],
                "recommendations": ["建议人工检查"],
                "needs_human_review": True,
                "confidence_adjustment": 0.0,
                "detailed_feedback": []
            }

    def _process_reflection_result(self, llm_result: Dict) -> ReflectionResult:
        """处理反思结果"""
        
        return ReflectionResult(
            quality_score=max(0.0, min(1.0, llm_result.get('quality_score', 0.5))),
            issues_found=llm_result.get('issues_found', []),
            recommendations=llm_result.get('recommendations', []),
            needs_human_review=llm_result.get('needs_human_review', False),
            confidence_adjustment=llm_result.get('confidence_adjustment', 0.0),
            classification_feedback=llm_result.get('detailed_feedback', []),
            memory_guidance={}  # 简化版本暂时为空
        )

    def _apply_quality_adjustments(self, state: MinerState, reflection: ReflectionResult) -> MinerState:
        """根据反思结果调整挖掘项目"""
        
        if not state.mined_items:
            return state
        
        adjusted_items = []
        
        for item in state.mined_items:
            adjusted_item = item.copy()
            
            # 应用置信度调整
            original_confidence = adjusted_item.get('confidence', 0.5)
            adjusted_confidence = original_confidence + reflection.confidence_adjustment
            adjusted_item['confidence'] = max(0.0, min(1.0, adjusted_confidence))
            
            # 根据分类反馈调整
            item_url = item.get('url', '')
            for feedback in reflection.classification_feedback:
                if feedback.get('item_url') == item_url:
                    if feedback.get('suggested_classification'):
                        adjusted_item['suggested_level'] = feedback['suggested_classification']
                        adjusted_item['adjustment_reason'] = feedback.get('reason', '')
            
            # 添加质量标记
            if reflection.quality_score < 0.4:
                adjusted_item['quality_flag'] = 'low_quality'
            elif reflection.quality_score > 0.8:
                adjusted_item['quality_flag'] = 'high_quality'
            
            adjusted_items.append(adjusted_item)
        
        state.mined_items = adjusted_items
        return state
'''


import time
from typing import Dict, Any, List, Optional
from loguru import logger
from dataclasses import dataclass
import json

from llms.miner_llm import MinerLLMClient
from memory.storage.session_memory import SessionMemory
from state.miner_state import MinerState

class ReflectionNode:
    """
    ReflectionNode
    - 对本次挖掘结果进行结构化反思
    - 永远不允许中断主流程
    - 只产出「可被机器使用」的反思结果
    """

    def __init__(self):
        self.llm = MinerLLMClient()

    # ==========================================================
    # 主入口
    # ==========================================================

    async def execute(self, state: Any) -> Any:
        logger.info("🧠 ReflectionNode 开始反思本次挖掘结果")

        try:
            prompt = self._build_reflection_prompt(state)

            # 调用 LLM 进行反思处理
            raw_response = await self.llm.ainvoke_json(
                system_prompt="你是一个挖掘结果反思器，请输出严格 JSON",
                user_prompt=prompt,
                temperature=0.2,
            )

            logger.debug(f"Raw Reflection Response: {raw_response}")

            reflection = self._safe_parse_json(raw_response)

            if not reflection:
                logger.warning("⚠️ ReflectionNode 未生成有效反思结果，已跳过")
                state.reflection_result = {}
                state.is_valid = True
                return state

            # 可见性：打印反思内容
            logger.success("🪞 Reflection 内容如下：")
            logger.success(json.dumps(reflection, ensure_ascii=False, indent=2))

            # 只写入 state，不直接操作 memory（避免接口不一致）
            state.reflection_result = reflection
            state.is_valid = True

            logger.success("✅ ReflectionNode 反思完成")
            return state

        except Exception as e:
            # ReflectionNode 永远不能影响主流程
            logger.error(f"❌ ReflectionNode 失败，已降级忽略: {e}")
            state.reflection_result = {}
            state.is_valid = True
            return state

    # ==========================================================
    # Prompt 构建
    # ==========================================================

    def _build_reflection_prompt(self, state: Any) -> str:
            """
            [修复] 增加对多种可能字段的检索，防止信息丢失
            """
            # 1. 尝试多个可能存储结果的字段
            items = getattr(state, "final_items", [])
            if not items:
                items = getattr(state, "mined_results", [])
            if not items:
                # 兼容一些直接挂在 data 下的结构
                items = getattr(state, "data", [])
                
            # 确保 items 是列表
            if not isinstance(items, list):
                items = []

            # 2. 尝试获取域名 (兼容 current_clue 或直接属性)
            domain = getattr(state, "domain", None)
            if not domain and hasattr(state, "current_clue"):
                # 尝试从线索中提取域名
                clue = state.current_clue
                if isinstance(clue, dict):
                    domain = clue.get("domain", "unknown")
            
            domain = domain or "unknown"
            duration = getattr(state, "total_duration", "未知")

            # [新增] 提取 L3 候选者数量作为参考，这能帮助 LLM 判断挖掘深度
            structured_data = getattr(state, "structured_data", {})
            l3_count = len(structured_data.get("l3_candidates", [])) if isinstance(structured_data, dict) else 0

            return f"""
    你刚完成了一次数据挖掘任务，请对结果进行反思。

    【基本信息】
    - 目标域名: {domain}
    - 发现 L3 入口数: {l3_count}
    - 最终抓取数据行数: {len(items)}
    - 总耗时: {duration} 秒

    【反思任务】
    请评估本次挖掘的质量。如果入口很多但结果为 0，通常意味着爬虫被反爬了或者解析规则失效。
    如果结果很多，请评估数据的结构化程度。

    请严格输出 JSON：
    {{
    "quality_score": 0~1 之间的小数,
    "issues": ["问题描述"],
    "strategy_adjustments": {{
        "structure": {{ "focus": "建议关注的特征", "ignore": "建议忽略的模式" }},
        "dfs": {{ "depth_change": "增加/减少", "reason": "原因" }}
    }}
    }}
    """.strip()

    # ==========================================================
    # JSON 安全解析（这是之前出问题最多的地方）
    # ==========================================================

    def _safe_parse_json(self, data: Any) -> Optional[Dict]:
        """
        允许：
        - dict（直接返回）
        - str（尝试 json.loads）
        拒绝：
        - 其他任何类型
        """

        if not data:
            return None

        # 1️⃣ 已经是 dict（你日志里已经出现过）
        if isinstance(data, dict):
            return data

        # 2️⃣ 是字符串，尝试解析
        if isinstance(data, str):
            try:
                return json.loads(data)
            except Exception as e:
                logger.error("❌ ReflectionNode JSON 解析失败，已忽略该次反思")
                logger.debug(f"JSON 原始内容: {data}")
                logger.debug(f"解析错误: {e}")
                return None

        # 3️⃣ 其他类型一律拒绝
        logger.error(f"❌ ReflectionNode 无法处理的返回类型: {type(data)}")
        return None

    # ==========================================================
    # Reflection 完成后的应用
    # ==========================================================

    def apply_reflection_result(self, state: MinerState) -> None:
        """
        根据 ReflectionNode 输出的结果调整挖掘策略或模型设置
        """
        # 获取反思结果
        reflection = state.reflection_result

        # 如果反思结果有效，应用调整
        if reflection:
            # 质量分数
            quality_score = reflection.get("quality_score", 0)
            logger.info(f"🧠 质量分数：{quality_score:.2f}")

            # 问题反馈
            issues = reflection.get("issues", [])
            if issues:
                logger.info("🧠 问题反馈：")
                for issue in issues:
                    logger.info(f"   - {issue}")

            # 策略调整
            strategy_adjustments = reflection.get("strategy_adjustments", {})
            if strategy_adjustments:
                structure_adjustments = strategy_adjustments.get("structure", {})
                dfs_adjustments = strategy_adjustments.get("dfs", {})

                if structure_adjustments:
                    logger.info("🧠 结构调整建议：")
                    for key, value in structure_adjustments.items():
                        logger.info(f"   - {key}: {value}")

                if dfs_adjustments:
                    logger.info("🧠 深度搜索策略调整建议：")
                    for key, value in dfs_adjustments.items():
                        logger.info(f"   - {key}: {value}")

            # 应用策略调整（伪代码，根据你的需求实现）
            self._apply_structure_adjustments(structure_adjustments)
            self._apply_dfs_adjustments(dfs_adjustments)

    def _apply_structure_adjustments(self, adjustments: Dict[str, str]) -> None:
        """
        应用结构调整策略
        """
        for key, value in adjustments.items():
            # 实际的调整代码逻辑
            logger.info(f"应用结构调整: {key} -> {value}")

    def _apply_dfs_adjustments(self, adjustments: Dict[str, str]) -> None:
        """
        应用深度搜索策略调整
        """
        for key, value in adjustments.items():
            # 实际的调整代码逻辑
            logger.info(f"应用深度搜索策略调整: {key} -> {value}")
