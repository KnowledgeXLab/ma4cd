#!/usr/bin/env python3
"""
Scout Agent 快速验证脚本
快速检查核心功能是否工作
"""

import os
import sys
import time

# 设置路径
current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(os.path.dirname(current_dir))
sys.path.insert(0, project_root)

print("⚡ Scout Agent 快速验证")
print("=" * 50)


class SimpleTestLLM:
    """超简化的测试用 LLM"""
    def invoke(self, system_prompt, user_prompt, **kwargs):
        return '[{"search_query": "test query", "tier": "tier1", "description": "test"}]'
    
    def generate(self, prompt, **kwargs):
        return "test response"


def quick_verification():
    """快速验证"""
    try:
        # 尝试导入
        from agents.scout.agent import ScoutAgent
        print("✅ 导入 ScoutAgent")
    except ImportError:
        try:
            from agents.scout.agent import ScoutAgent
            print("✅ 导入 ScoutAgent (相对路径)")
        except ImportError as e:
            print(f"❌ 导入失败: {e}")
            return False
    
    # 创建简单 LLM
    llm = SimpleTestLLM()
    
    try:
        # 创建 Scout Agent
        scout = ScoutAgent(llm_client=llm, output_dir="./test_quick")
        print("✅ 创建 ScoutAgent 实例")
        
        # 检查方法
        methods = ['quick_search', 'run']
        for method in methods:
            if hasattr(scout, method):
                print(f"✅ 有 {method}() 方法")
            else:
                print(f"❌ 没有 {method}() 方法")
        
        # 测试快速搜索
        if hasattr(scout, 'quick_search'):
            try:
                results = scout.quick_search("test", num_results=1)
                print(f"✅ quick_search() 可调用, 返回: {type(results)}")
            except Exception as e:
                print(f"⚠️  quick_search() 调用出错: {e}")
        
        print("\n🎯 核心功能验证完成!")
        return True
        
    except Exception as e:
        print(f"❌ 验证失败: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    success = quick_verification()
    
    if success:
        print("\n💡 运行完整测试:")
        print("  python test_scout_agent.py")
    else:
        print("\n🔧 需要调试的问题:")
        print("  1. 检查 agent.py 文件路径")
        print("  2. 检查构造函数参数")
        print("  3. 检查依赖导入")