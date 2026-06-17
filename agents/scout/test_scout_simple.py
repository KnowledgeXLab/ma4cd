#!/usr/bin/env python3
"""兼容入口：从项目根目录运行 Scout smoke test。"""
import sys
from pathlib import Path

project_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(project_root))

from agents.scout.test_scout import quick_verification

if __name__ == "__main__":
    raise SystemExit(0 if quick_verification() else 1)
