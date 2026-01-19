# ma4cd/agents/scout/run.py
import asyncio
import os
import sys
import argparse
import json
import time
import shutil
from datetime import datetime
from pathlib import Path
from loguru import logger

# 项目根路径
project_root = Path(__file__).resolve().parents[2]
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from core.agent_llm import AgentLLM
from agents.scout.agent import ScoutAgent
from tools.web_search import WebSearchTool

logger.remove()
logger.add(sys.stderr, format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{message}</cyan>")
logger.add("logs/scout_run_{time:YYYYMMDD}.log", rotation="1 day", level="INFO")

def parse_args():
    parser = argparse.ArgumentParser(description="Scout Agent 测试运行脚本")
    parser.add_argument("task", nargs="?", default="君士坦丁堡陷落", help="要执行的任务描述")
    parser.add_argument("--country", default="us", help="国家代码，用于 Tier 策略 (e.g. us, cn, la)")
    parser.add_argument("--max-steps", type=int, default=8, help="每个子任务最大搜索步数")
    parser.add_argument("--no-cache", action="store_true", help="禁用缓存")
    parser.add_argument("--clean", action="store_true", help="清空 artifacts 目录")
    parser.add_argument("--full", action="store_true", help="打印所有线索")
    return parser.parse_args()

async def main():
    args = parse_args()
    task = args.task.strip()
    country_code = args.country.lower()
    max_steps = args.max_steps
    enable_cache = not args.no_cache

    if args.clean:
        shutil.rmtree("./artifacts/scout", ignore_errors=True)
        Path("./artifacts/scout").mkdir(parents=True, exist_ok=True)
        print("✅ artifacts 目录已清空")

    print("=" * 80)
    print("MA4CD Scout Agent 快速测试运行")
    print("=" * 80)
    print(f"任务：{task}")
    print(f"国家代码：{country_code}")
    print(f"最大步数/子任务：{max_steps}")
    print(f"缓存：{'启用' if enable_cache else '禁用'}")
    print("-" * 80)

    # 1. 读取环境变量
    api_key = os.getenv("OPENAI_API_KEY")
    base_url = os.getenv("OPENAI_BASE_URL")

    if not api_key or not base_url:
        print("错误：缺少 OPENAI_API_KEY 或 OPENAI_BASE_URL")
        sys.exit(1)

    print(f"API 配置：")
    print(f"  Base URL: {base_url}")
    print(f"  API Key : {api_key[:8]}...（已隐藏）")
    print("-" * 80)

    # 2. 创建 LLM
    try:
        llm = AgentLLM(
            api_key=api_key,
            model_name="gpt-4o-mini",
            base_url=base_url,
            default_temperature=0.5,
            default_max_tokens=2000
        )
        print("LLM 初始化成功")
    except Exception as e:
        logger.error(f"LLM 初始化失败: {str(e)}")
        sys.exit(1)

    # 3. 创建 Scout Agent
    try:
        scout = ScoutAgent(
            llm_client=llm,  # 匹配你的 agent.py 参数
            output_dir="./artifacts/scout",
            max_concurrent_searches=3,
            search_max_steps=max_steps,
            enable_cache=enable_cache
        )
        print("Scout Agent 初始化成功")
    except Exception as e:
        logger.error(f"Scout Agent 初始化失败: {str(e)}")
        sys.exit(1)

    # 4. 执行任务
    print("\n" + "=" * 80)
    print(f"开始执行任务：{task}")
    print("=" * 80)

    start_time = time.time()
    try:
        result = scout.run(task, country_code=country_code)  # ← 加 country_code 参数

        exec_time = time.time() - start_time

        print("\n" + "=" * 80)
        print("执行结果摘要")
        print("=" * 80)
        print(f"任务：{result.get('task', '未知')}")
        print(f"线索数量：{result.get('clues_count', 0)}")
        print(f"子任务数量：{result.get('subtasks_count', 0)}")
        print(f"成功率：{result.get('success_rate', 0):.1%}")
        print(f"执行耗时：{exec_time:.2f} 秒")

        # 5. 打印线索
        clues = result.get('all_clues', result.get('clues', []))
        if len(clues) > 0:
            print(f"\n显示 {len(clues)} 条线索（按相关性排序）：")
            print("=" * 120)
            
            # 按相关性排序（如果有 score/relevance_score）
            try:
                sorted_clues = sorted(clues, key=lambda x: x.relevance_score if hasattr(x, 'relevance_score') else x.metadata.get('relevance_score', 0) if hasattr(x, 'metadata') else 0, reverse=True)
            except:
                sorted_clues = clues
                print("📊 未排序（部分线索缺少相关度信息）")
            
            for i, clue in enumerate(sorted_clues if args.full else sorted_clues[:10], 1):
                # 判断 clue 类型
                if isinstance(clue, dict):
                    title = clue.get('title', clue.get('name', '无标题')).strip()
                    url = clue.get('url', clue.get('link', ''))
                    source = clue.get('source', clue.get('engine', '未知'))
                    relevance = clue.get('relevance_score', clue.get('score', 0))
                    snippet = clue.get('snippet', clue.get('description', ''))[:150] + '...' if len(clue.get('snippet', '')) > 150 else clue.get('snippet', '')
                else:
                    # Clue 对象（dataclass 或 class）
                    title = getattr(clue, 'title', '无标题').strip()
                    url = getattr(clue, 'url', '')
                    source = getattr(clue, 'source', '未知')
                    relevance = getattr(clue, 'relevance_score', 0)
                    snippet = getattr(clue, 'snippet', '')[:150] + '...' if len(getattr(clue, 'snippet', '')) > 150 else getattr(clue, 'snippet', '')
                
                # 跳过无效线索
                if not url:
                    continue
                
                # 打印
                print(f"[{i:3d}] {title}")
                print(f" 📍 URL: {url}")
                print(f" 🏷️ 来源: {source}")
                if relevance > 0:
                    print(f" ⭐ 相关度: {relevance}/10")
                if snippet:
                    print(f" 📝 摘要: {snippet}")
                print("-" * 120)
        else:
            print("\n⚠️ 没有找到任何线索")
            print("建议：")
            print("1. 检查 web_search 返回数据")
            print("2. 尝试英文查询：'solid state battery dataset filetype:csv'")
            print("3. 查看日志：logs/scout_run_*.log")

        # 6. 显示保存文件
        artifact_dir = Path("./artifacts/scout")
        if artifact_dir.exists():
            runs = list(artifact_dir.glob("run_*.json"))
            if runs:
                latest = max(runs, key=lambda p: p.stat().st_mtime)
                print(f"\n📂 详细结果已保存至：{latest.name}")
                print(f"查看完整文件：cat {latest}")

    except Exception as e:
        logger.error(f"任务运行失败: {str(e)}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(main())