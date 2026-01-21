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