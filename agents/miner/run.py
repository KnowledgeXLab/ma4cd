# run.py
import asyncio
import sys
import os

# 添加项目根目录到 Python 路径
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)
print(f"在 sys.path 中添加项目根目录: {project_root}")

from agent import MinerAgent

async def main():
    """测试 Miner Agent"""
    
    # 创建 Miner Agent 实例
    miner = MinerAgent()
    
    # 测试用例 1: 世界银行开放数据 (结构清晰，容易识别子库)
    test_input_worldbank = {
        "task": "挖掘世界银行开放数据子数据库",
        "clues": [
            {
                "url": "https://data.worldbank.org/",
                "title": "World Bank Open Data",
                "snippet": "Free and open access to global development data",
                "tier": "tier1",
                "likely_level": "L2"
            }
        ]
    }
    
    # 测试用例 2: 美国人口普查局 (多个独立数据库)
    test_input_census = {
        "task": "挖掘美国人口普查局数据子数据库",
        "clues": [
            {
                "url": "https://data.census.gov/",
                "title": "U.S. Census Bureau Data",
                "snippet": "Official statistics from the U.S. Census Bureau",
                "tier": "tier1", 
                "likely_level": "L2"
            }
        ]
    }
    
    # 测试用例 3: 欧盟统计局 (Eurostat)
    test_input_eurostat = {
        "task": "挖掘欧盟统计局数据子数据库",
        "clues": [
            {
                "url": "https://ec.europa.eu/eurostat/data/database",
                "title": "Eurostat Database",
                "snippet": "European statistics database with comprehensive data",
                "tier": "tier1",
                "likely_level": "L2"
            }
        ]
    }
    
    # 测试用例 4: 联合国数据 (UN Data)
    test_input_undata = {
        "task": "挖掘联合国数据子数据库",
        "clues": [
            {
                "url": "http://data.un.org/",
                "title": "UN Data",
                "snippet": "United Nations statistical databases",
                "tier": "tier1",
                "likely_level": "L2"
            }
        ]
    }
    
    # 测试用例 5: 经合组织数据 (OECD)
    test_input_oecd = {
        "task": "挖掘经合组织数据子数据库",
        "clues": [
            {
                "url": "https://data.oecd.org/",
                "title": "OECD Data",
                "snippet": "OECD statistics and data",
                "tier": "tier1",
                "likely_level": "L2"
            }
        ]
    }
    
    # 测试用例 6: 中国国家统计局 (原测试)
    test_input_china = {
        "task": "挖掘中国国家统计公开数据集",
        "clues": [
            {
                "url": "https://data.stats.gov.cn/",
                "title": "国家数据",
                "snippet": "中华人民共和国国家统计局官方数据门户",
                "tier": "tier1",
                "likely_level": "L2"
            }
        ]
    }
    
    # 选择要测试的用例
    print("可用的测试用例:")
    print("1. 世界银行开放数据 (推荐)")
    print("2. 美国人口普查局")
    print("3. 欧盟统计局 Eurostat")
    print("4. 联合国数据")
    print("5. 经合组织 OECD")
    print("6. 中国国家统计局 (原测试)")
    
    choice = input("请选择测试用例 (1-6, 默认1): ").strip() or "1"
    
    test_cases = {
        "1": ("世界银行开放数据", test_input_worldbank),
        "2": ("美国人口普查局", test_input_census), 
        "3": ("欧盟统计局", test_input_eurostat),
        "4": ("联合国数据", test_input_undata),
        "5": ("经合组织数据", test_input_oecd),
        "6": ("中国国家统计局", test_input_china)
    }
    
    if choice not in test_cases:
        choice = "1"
    
    test_name, test_input = test_cases[choice]
    
    print(f"开始测试: {test_name}")
    print(f"测试 URL: {test_input['clues'][0]['url']}")
    print("=" * 80)
    
    # 运行 Miner Agent - 使用正确的参数格式
    result = await miner.run(test_input)
    
    # 输出结果
    print("=" * 80)
    print("Miner Agent 完整运行结果")
    print("=" * 80)
    
    import json
    print(json.dumps(result, indent=2, ensure_ascii=False))
    
    # 分析结果
    if result.get("mined_count", 0) > 0:
        print(f"✅ 成功挖掘出 {result['mined_count']} 个 L3 子库:")
        for i, item in enumerate(result.get("mined_items", []), 1):
            print(f"  {i}. {item['title']} (confidence: {item['confidence']})")
            print(f"     URL: {item['url']}")
            print(f"     理由: {item['reason']}")
    else:
        print(f"❌ 挖掘失败: {result.get('error', '未知错误')}")
        
        # 提供调试建议
        print("🔧 调试建议:")
        print("1. 检查网站是否可访问")
        print("2. 查看 ValidateNode 的判断逻辑是否过于严格")
        print("3. 考虑使用规则验证模式")
        
        # 如果是中国统计局，提供特定建议
        if choice == "6":
            print("4. 中国统计局的问题可能是 ValidateNode 把数据查询系统误判为 'L2 spam'")
            print("5. 建议修改 ValidateNode 使用规则验证，或优化 LLM prompt")

if __name__ == "__main__":
    asyncio.run(main())
