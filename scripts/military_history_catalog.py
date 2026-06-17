"""
军事史 / 技术发展史 — MA4CD 任务目录（与用户提供的分类表一致）
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Literal

CategoryKind = Literal["war", "tech"]


@dataclass(frozen=True)
class MilitaryHistoryTask:
    """单条挖掘任务元数据。"""

    task_id: str
    domain_zh: str
    domain_en: str
    category_zh: str
    category_en: str
    category_kind: CategoryKind
    subtopic: str
    query: str

    def to_dict(self) -> dict:
        return asdict(self)


# fmt: off
MILITARY_HISTORY_CATALOG: tuple[MilitaryHistoryTask, ...] = (
    # ── 战争史 / History of Warfare ──────────────────────────────────────────
    MilitaryHistoryTask(
        "ancient_classic_battles", "军事历史", "Military History",
        "战争史", "History of Warfare", "war", "古代经典战役",
        "搜索古代经典战役的军事史料、战史档案、战役数据库与研究机构门户",
    ),
    MilitaryHistoryTask(
        "ww1_major_battles", "军事历史", "Military History",
        "战争史", "History of Warfare", "war", "一战重大战役",
        "搜索第一次世界大战重大战役的军事史档案、战史数据库与研究数据容器",
    ),
    MilitaryHistoryTask(
        "ww2_major_battles", "军事历史", "Military History",
        "战争史", "History of Warfare", "war", "二战重大战役",
        "搜索第二次世界大战重大战役的军事历史档案、战史数据库与解密文件门户",
    ),
    MilitaryHistoryTask(
        "korean_war", "军事历史", "Military History",
        "战争史", "History of Warfare", "war", "朝鲜战争",
        "搜索朝鲜战争军事历史档案、战史数据库与研究机构门户",
    ),
    MilitaryHistoryTask(
        "vietnam_war", "军事历史", "Military History",
        "战争史", "History of Warfare", "war", "越南战争",
        "搜索越南战争军事史档案、口述史、战报数据库与开放研究门户",
    ),
    MilitaryHistoryTask(
        "middle_east_wars", "军事历史", "Military History",
        "战争史", "History of Warfare", "war", "中东战争",
        "搜索中东战争军事历史档案与冲突研究数据门户",
    ),
    MilitaryHistoryTask(
        "iran_iraq_war", "军事历史", "Military History",
        "战争史", "History of Warfare", "war", "两伊战争",
        "搜索两伊战争军事史档案、战报与数据库门户",
    ),
    MilitaryHistoryTask(
        "falklands_war", "军事历史", "Military History",
        "战争史", "History of Warfare", "war", "马岛战争",
        "搜索马岛战争（福克兰战争）军事史档案与研究数据",
    ),
    MilitaryHistoryTask(
        "gulf_war", "军事历史", "Military History",
        "战争史", "History of Warfare", "war", "海湾战争",
        "搜索海湾战争军事历史档案、作战记录与数据库门户",
    ),
    MilitaryHistoryTask(
        "kosovo_war", "军事历史", "Military History",
        "战争史", "History of Warfare", "war", "科索沃战争",
        "搜索科索沃战争军事史档案与空中作战研究数据门户",
    ),
    MilitaryHistoryTask(
        "afghanistan_war", "军事历史", "Military History",
        "战争史", "History of Warfare", "war", "阿富汗战争",
        "搜索阿富汗战争军事历史档案与开源情报数据库",
    ),
    MilitaryHistoryTask(
        "iraq_war", "军事历史", "Military History",
        "战争史", "History of Warfare", "war", "伊拉克战争",
        "搜索伊拉克战争军事史档案、作战报告与数据库门户",
    ),
    MilitaryHistoryTask(
        "chechen_wars", "军事历史", "Military History",
        "战争史", "History of Warfare", "war", "车臣战争",
        "搜索车臣战争军事历史档案、战史研究与冲突数据门户",
    ),
    MilitaryHistoryTask(
        "russia_ukraine_war", "军事历史", "Military History",
        "战争史", "History of Warfare", "war", "俄乌战争",
        "搜索俄乌战争军事史开源情报、档案与冲突事件数据库",
    ),
    # ── 技术发展史 / History of Technological Development ────────────────────
    MilitaryHistoryTask(
        "tank_evolution", "军事历史", "Military History",
        "技术发展史", "History of Technological Development", "tech", "坦克进化史",
        "搜索坦克装甲车辆发展史史料、技术档案与博物馆数据库",
    ),
    MilitaryHistoryTask(
        "aircraft_carrier_history", "军事历史", "Military History",
        "技术发展史", "History of Technological Development", "tech", "航空母舰发展史",
        "搜索航空母舰发展史军事技术史档案、舰艇数据库与博物馆门户",
    ),
    MilitaryHistoryTask(
        "precision_guided_weapons", "军事历史", "Military History",
        "技术发展史", "History of Technological Development", "tech", "精确制导武器发展",
        "搜索精确制导武器发展历程技术档案、试验报告与研究数据库",
    ),
    MilitaryHistoryTask(
        "uav_history", "军事历史", "Military History",
        "技术发展史", "History of Technological Development", "tech", "无人机发展史",
        "搜索军用无人机发展史技术史料、档案与数据库门户",
    ),
)
# fmt: on

TASK_BY_ID = {t.task_id: t for t in MILITARY_HISTORY_CATALOG}
TASK_BY_SUBTOPIC = {t.subtopic: t for t in MILITARY_HISTORY_CATALOG}
