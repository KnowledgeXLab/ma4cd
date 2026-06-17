#!/usr/bin/env python3
"""Scout Agent 快速验证：检查导入与核心 API 是否存在。"""
import sys
from pathlib import Path

project_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(project_root))


def quick_verification() -> bool:
    print("Scout Agent 快速验证")
    print("=" * 50)

    try:
        from agents.scout.agent import ScoutAgent
    except ImportError as e:
        print(f"导入 ScoutAgent 失败: {e}")
        return False

    print("导入 ScoutAgent 成功")

    scout = ScoutAgent()
    print("创建 ScoutAgent 实例成功")

    if not hasattr(scout, "run"):
        print("缺少 run() 方法")
        return False
    print("run() 方法存在")

    if not hasattr(scout, "apply_amendment"):
        print("缺少 apply_amendment() 方法")
        return False
    print("apply_amendment() 方法存在")

    print("\n核心 API 验证完成（未发起真实网络请求）")
    print("完整联调请运行: python agents/scout/run.py \"你的任务描述\"")
    return True


if __name__ == "__main__":
    raise SystemExit(0 if quick_verification() else 1)
