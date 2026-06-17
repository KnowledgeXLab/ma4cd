"""最小 smoke test：验证核心模块可导入。"""


def test_core_agents_importable():
    from agents.commander.agent import CommanderAgent
    from agents.scout.agent import ScoutAgent
    from agents.miner.agent import UniversalMinerAgent
    from agents.inspector.agent import InspectorAgent
    from agents.curator.agent import CuratorAgent

    assert CommanderAgent is not None
    assert ScoutAgent is not None
    assert UniversalMinerAgent is not None
    assert InspectorAgent is not None
    assert CuratorAgent is not None


def test_data_memory_center_importable():
    from data_memory_center.manager import DataMemoryCenter

    assert DataMemoryCenter is not None
