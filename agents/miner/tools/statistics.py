# miner/tools/statistics.py
"""
详细统计报告生成器
"""

import time
from typing import List, Dict, Any
from datetime import datetime, timedelta
from collections import Counter, defaultdict
from loguru import logger

class DetailedStatistics:
    """详细统计报告生成器"""
    
    def __init__(self, mined_items: List[dict], invalid_urls: List[dict], 
                 start_time: float, end_time: float):
        self.mined_items = mined_items
        self.invalid_urls = invalid_urls
        self.start_time = start_time
        self.end_time = end_time
        self.duration = end_time - start_time
    
    def generate_report(self) -> Dict[str, Any]:
        """生成完整的统计报告"""
        
        return {
            "summary": self._generate_summary(),
            "performance": self._generate_performance_stats(),
            "quality": self._generate_quality_stats(),
            "classification": self._generate_classification_stats(),
            "errors": self._generate_error_stats(),
            "recommendations": self._generate_recommendations(),
            "detailed_breakdown": self._generate_detailed_breakdown()
        }
    
    def _generate_summary(self) -> Dict:
        """生成摘要统计"""
        
        total_processed = len(self.mined_items) + len(self.invalid_urls)
        success_rate = len(self.mined_items) / total_processed if total_processed > 0 else 0
        
        return {
            "total_urls_processed": total_processed,
            "successful_extractions": len(self.mined_items),
            "failed_extractions": len(self.invalid_urls),
            "success_rate": round(success_rate, 3),
            "processing_duration": round(self.duration, 2),
            "average_time_per_url": round(self.duration / total_processed, 2) if total_processed > 0 else 0,
            "timestamp": datetime.now().isoformat()
        }
    
    def _generate_performance_stats(self) -> Dict:
        """生成性能统计"""
        
        processing_times = []
        for item in self.mined_items:
            if 'processing_time' in item:
                processing_times.append(item['processing_time'])
        
        if processing_times:
            avg_time = sum(processing_times) / len(processing_times)
            min_time = min(processing_times)
            max_time = max(processing_times)
        else:
            avg_time = min_time = max_time = 0
        
        return {
            "average_processing_time": round(avg_time, 2),
            "min_processing_time": round(min_time, 2),
            "max_processing_time": round(max_time, 2),
            "total_processing_time": round(self.duration, 2),
            "throughput_urls_per_second": round(len(self.mined_items) / self.duration, 2) if self.duration > 0 else 0
        }
    
    def _generate_quality_stats(self) -> Dict:
        """生成质量统计"""
        
        quality_scores = []
        confidence_scores = []
        
        for item in self.mined_items:
            if 'quality_score' in item:
                quality_scores.append(item['quality_score'])
            if 'confidence' in item:
                confidence_scores.append(item['confidence'])
        
        return {
            "quality_metrics": {
                "average_quality_score": round(sum(quality_scores) / len(quality_scores), 3) if quality_scores else 0,
                "quality_distribution": self._calculate_distribution(quality_scores),
                "high_quality_items": len([s for s in quality_scores if s >= 0.8]),
                "low_quality_items": len([s for s in quality_scores if s < 0.5])
            },
            "confidence_metrics": {
                "average_confidence": round(sum(confidence_scores) / len(confidence_scores), 3) if confidence_scores else 0,
                "confidence_distribution": self._calculate_distribution(confidence_scores),
                "high_confidence_items": len([s for s in confidence_scores if s >= 0.8]),
                "low_confidence_items": len([s for s in confidence_scores if s < 0.5])
            }
        }
    
    def _generate_classification_stats(self) -> Dict:
        """生成分类统计"""
        
        # 按层级统计
        tier_counts = Counter()
        domain_counts = Counter()
        source_counts = Counter()
        
        for item in self.mined_items:
            tier = item.get('tier', 'unknown')
            tier_counts[tier] += 1
            
            # 提取域名
            url = item.get('url', '')
            if url:
                from urllib.parse import urlparse
                domain = urlparse(url).netloc
                domain_counts[domain] += 1
            
            source = item.get('source', 'unknown')
            source_counts[source] += 1
        
        return {
            "tier_distribution": dict(tier_counts),
            "top_domains": dict(domain_counts.most_common(10)),
            "source_distribution": dict(source_counts),
            "classification_accuracy": self._calculate_classification_accuracy()
        }
    
    def _generate_error_stats(self) -> Dict:
        """生成错误统计"""
        
        error_types = Counter()
        error_domains = Counter()
        
        for invalid in self.invalid_urls:
            error_type = invalid.get('error_type', 'UNKNOWN')
            error_types[error_type] += 1
            
            url = invalid.get('url', '')
            if url:
                from urllib.parse import urlparse
                domain = urlparse(url).netloc
                error_domains[domain] += 1
        
        return {
            "error_type_distribution": dict(error_types),
            "most_problematic_domains": dict(error_domains.most_common(5)),
            "total_errors": len(self.invalid_urls),
            "error_rate": round(len(self.invalid_urls) / (len(self.mined_items) + len(self.invalid_urls)), 3) if (len(self.mined_items) + len(self.invalid_urls)) > 0 else 0,
            "common_error_patterns": self._identify_error_patterns()
        }
    
    def _generate_recommendations(self) -> List[str]:
        """生成改进建议"""
        
        recommendations = []
        
        # 基于成功率的建议
        success_rate = len(self.mined_items) / (len(self.mined_items) + len(self.invalid_urls)) if (len(self.mined_items) + len(self.invalid_urls)) > 0 else 0
        
        if success_rate < 0.5:
            recommendations.append("成功率较低，建议检查URL质量和网络连接")
        
        # 基于性能的建议
        if self.duration > 300:  # 5分钟
            recommendations.append("处理时间较长，建议优化并发处理或增加超时设置")
        
        # 基于错误类型的建议
        error_types = Counter(invalid.get('error_type', 'UNKNOWN') for invalid in self.invalid_urls)
        
        if error_types.get('TIMEOUT', 0) > len(self.invalid_urls) * 0.3:
            recommendations.append("超时错误较多，建议增加超时时间或检查网络状况")
        
        if error_types.get('DNS_RESOLUTION_FAILED', 0) > 0:
            recommendations.append("DNS解析失败，建议检查域名有效性")
        
        # 基于质量的建议
        quality_scores = [item.get('quality_score', 0) for item in self.mined_items if 'quality_score' in item]
        if quality_scores and sum(quality_scores) / len(quality_scores) < 0.6:
            recommendations.append("数据质量偏低，建议优化提取算法或增加验证步骤")
        
        return recommendations
    
    def _generate_detailed_breakdown(self) -> Dict:
        """生成详细分解统计"""
        
        return {
            "hourly_performance": self._calculate_hourly_performance(),
            "domain_analysis": self._analyze_domains(),
            "tier_quality_correlation": self._analyze_tier_quality(),
            "processing_bottlenecks": self._identify_bottlenecks()
        }
    
    def _calculate_distribution(self, values: List[float]) -> Dict:
        """计算数值分布"""
        
        if not values:
            return {}
        
        ranges = {
            "0.0-0.2": 0,
            "0.2-0.4": 0,
            "0.4-0.6": 0,
            "0.6-0.8": 0,
            "0.8-1.0": 0
        }
        
        for value in values:
            if value < 0.2:
                ranges["0.0-0.2"] += 1
            elif value < 0.4:
                ranges["0.2-0.4"] += 1
            elif value < 0.6:
                ranges["0.4-0.6"] += 1
            elif value < 0.8:
                ranges["0.6-0.8"] += 1
            else:
                ranges["0.8-1.0"] += 1
        
        return ranges
    
    def _calculate_classification_accuracy(self) -> float:
        """计算分类准确性（简化版）"""
        
        # 这里可以基于已知的正确分类来计算准确性
        # 简化版本：基于置信度来估算
        
        high_confidence_items = len([item for item in self.mined_items 
                                   if item.get('confidence', 0) >= 0.8])
        
        if len(self.mined_items) == 0:
            return 0.0
        
        return round(high_confidence_items / len(self.mined_items), 3)
    
    def _identify_error_patterns(self) -> List[str]:
        """识别错误模式"""
        
        patterns = []
        
        # 分析错误消息中的常见模式
        error_messages = [invalid.get('error_message', '') for invalid in self.invalid_urls]
        
        # 简单的模式识别
        if any('timeout' in msg.lower() for msg in error_messages):
            patterns.append("网络超时问题")
        
        if any('ssl' in msg.lower() or 'certificate' in msg.lower() for msg in error_messages):
            patterns.append("SSL证书问题")
        
        if any('404' in msg for msg in error_messages):
            patterns.append("页面不存在")
        
        return patterns
    
    def _calculate_hourly_performance(self) -> Dict:
        """计算每小时性能（简化版）"""
        
        # 简化版本：只返回总体性能
        return {
            "total_hours": round(self.duration / 3600, 2),
            "urls_per_hour": round(len(self.mined_items) / (self.duration / 3600), 2) if self.duration > 0 else 0
        }
    
    def _analyze_domains(self) -> Dict:
        """分析域名表现"""
        
        domain_stats = defaultdict(lambda: {"success": 0, "failure": 0, "total_time": 0})
        
        # 统计成功的域名
        for item in self.mined_items:
            url = item.get('url', '')
            if url:
                from urllib.parse import urlparse
                domain = urlparse(url).netloc
                domain_stats[domain]["success"] += 1
                domain_stats[domain]["total_time"] += item.get('processing_time', 0)
        
        # 统计失败的域名
        for invalid in self.invalid_urls:
            url = invalid.get('url', '')
            if url:
                from urllib.parse import urlparse
                domain = urlparse(url).netloc
                domain_stats[domain]["failure"] += 1
        
        # 计算成功率
        result = {}
        for domain, stats in domain_stats.items():
            total = stats["success"] + stats["failure"]
            result[domain] = {
                "success_rate": round(stats["success"] / total, 3) if total > 0 else 0,
                "total_processed": total,
                "avg_processing_time": round(stats["total_time"] / stats["success"], 2) if stats["success"] > 0 else 0
            }
        
        return dict(sorted(result.items(), key=lambda x: x[1]["success_rate"], reverse=True)[:10])
    
    def _analyze_tier_quality(self) -> Dict:
        """分析层级与质量的关联"""
        
        tier_quality = defaultdict(list)
        
        for item in self.mined_items:
            tier = item.get('tier', 'unknown')
            quality = item.get('quality_score', 0)
            if quality > 0:
                tier_quality[tier].append(quality)
        
        result = {}
        for tier, qualities in tier_quality.items():
            if qualities:
                result[tier] = {
                    "average_quality": round(sum(qualities) / len(qualities), 3),
                    "count": len(qualities),
                    "min_quality": round(min(qualities), 3),
                    "max_quality": round(max(qualities), 3)
                }
        
        return result
    
    def _identify_bottlenecks(self) -> List[str]:
        """识别处理瓶颈"""
        
        bottlenecks = []
        
        # 分析处理时间
        processing_times = [item.get('processing_time', 0) for item in self.mined_items if 'processing_time' in item]
        
        if processing_times:
            avg_time = sum(processing_times) / len(processing_times)
            slow_items = [t for t in processing_times if t > avg_time * 2]
            
            if len(slow_items) > len(processing_times) * 0.2:
                bottlenecks.append("20%以上的URL处理时间过长")
        
        # 分析错误率
        total_processed = len(self.mined_items) + len(self.invalid_urls)
        error_rate = len(self.invalid_urls) / total_processed if total_processed > 0 else 0
        
        if error_rate > 0.3:
            bottlenecks.append("错误率过高，可能存在系统性问题")
        
        return bottlenecks
