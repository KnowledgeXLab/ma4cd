import os
import sqlite3
import json
import time
import sys
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional, Union
from pathlib import Path
from loguru import logger

# Redis 读缓存（可选）
try:
    from agents.miner.memory.backends.redis_aux import (
        _MISS,
        get_persistent_read_cache,
    )
except ImportError:
    _MISS = object()
    get_persistent_read_cache = lambda: None  # type: ignore

# 1. 路径修正
current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.abspath(os.path.join(current_dir, "../../../../"))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

class PersistentMemoryStorage:
    """
    长期记忆存储 - 使用 SQLite 数据库
    [高并发生产级优化版] 适配 Memory 1 (择优进化) + Memory 3 (精准指导)
    """
    
    def __init__(self, db_path: str = "memory_data/persistent_memory.db"):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._read_cache = get_persistent_read_cache()
        self._init_database()
        logger.info(f"PersistentMemoryStorage 核心已激活: {self.db_path}")
    
    def _get_conn(self):
        """
        🔥 [增强并发版] 统一的连接获取方法
        加入超时重试机制与 WAL 日志模式，防范多 Agent 并发时的 database is locked
        """
        conn = sqlite3.connect(self.db_path, timeout=10.0)
        # 开启 WAL 模式 (Write-Ahead Logging)，支持读写并发
        conn.execute('PRAGMA journal_mode=WAL;')
        return conn

    def _init_database(self):
        """初始化所有必要的数据库表"""
        with self._get_conn() as conn:
            cursor = conn.cursor()
            
            # 1. 网站宏观知识表 (Memory 2)
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS website_knowledge (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    domain TEXT UNIQUE,
                    site_profile TEXT,
                    strategies_used TEXT,
                    success_count INTEGER DEFAULT 0,
                    avg_l3_count REAL DEFAULT 0.0,
                    updated_at TEXT
                )
            ''')
            
            # 2. 策略进化史 (Memory 1)
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS strategy_evolution (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    domain TEXT,
                    strategy_name TEXT,
                    version INTEGER,
                    strategy_config TEXT,
                    performance_score REAL,
                    created_at TEXT,
                    is_active INTEGER DEFAULT 1
                )
            ''')
            
            # 3. 路径智能表 (DFS 权重)
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS path_intelligence (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    domain TEXT,
                    path_url TEXT,
                    visit_count INTEGER DEFAULT 0,
                    efficiency REAL DEFAULT 0.0,
                    last_visited TEXT,
                    UNIQUE(domain, path_url)
                )
            ''')

            # 3.5 监督反馈表（来自 Inspector 的客观通过率）
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS domain_supervision (
                    domain TEXT PRIMARY KEY,
                    total_miner_items INTEGER DEFAULT 0,
                    total_passed_items INTEGER DEFAULT 0,
                    total_rejected_items INTEGER DEFAULT 0,
                    rolling_pass_rate REAL DEFAULT 0.0,
                    last_updated TEXT
                )
            ''')

            # 3.6 监督反馈原因码（共享通道：domain + reason_code + count）
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS domain_supervision_reasons (
                    domain TEXT NOT NULL,
                    reason_code TEXT NOT NULL,
                    reject_count INTEGER DEFAULT 0,
                    last_updated TEXT,
                    PRIMARY KEY (domain, reason_code)
                )
            ''')

            # 4. 进化日志
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS evolution_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT,
                    details TEXT
                )
            ''')
            
            # 5. Session 快照表
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS session_snapshots (
                    session_id TEXT PRIMARY KEY,
                    domain TEXT,
                    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                    full_data TEXT
                )
            """)

            # 6. 人类指导表 - 增加 target_agent
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS human_instructions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    domain TEXT,           -- 'GLOBAL' 或特定域名
                    target_agent TEXT,     -- 'Miner', 'Commander', 'ALL'
                    instruction TEXT,
                    created_at TEXT,
                    is_active INTEGER DEFAULT 1
                )
            ''')
            
            conn.commit()

    # =========================================================
    # 🧠 Memory 3: 人类指导 (Layer 3)
    # =========================================================

    def add_human_instruction(self, instruction: str, domain: str = "GLOBAL", target_agent: str = "Miner"):
        """存储一条人类指令，支持指定 Agent"""
        try:
            with self._get_conn() as conn:
                cursor = conn.cursor()
                now = datetime.now().isoformat()
                cursor.execute(
                    "INSERT INTO human_instructions (domain, target_agent, instruction, created_at) VALUES (?, ?, ?, ?)",
                    (domain, target_agent, instruction, now)
                )
                conn.commit()
                logger.success(f"💾 指令已持久化: [{domain} -> {target_agent}] {instruction[:20]}...")
                cache = self._read_cache or get_persistent_read_cache()
                if cache:
                    cache.invalidate_instructions(domain)
        except Exception as e:
            logger.error(f"存储指令失败: {e}")

    def get_active_instructions(self, domain: str, agent_name: str = "Miner") -> List[str]:
        """
        获取有效指令
        逻辑：(指定域名 OR 全局) AND (指定Agent OR 全员)
        """
        cache = self._read_cache or get_persistent_read_cache()
        if cache:
            hit = cache.get_instructions(domain, agent_name)
            if hit is not _MISS:
                return hit or []
        try:
            with self._get_conn() as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    SELECT instruction FROM human_instructions 
                    WHERE is_active=1 
                    AND (domain=? OR domain='GLOBAL')
                    AND (target_agent=? OR target_agent='ALL')
                    ORDER BY created_at DESC
                ''', (domain, agent_name))
                result = [row[0] for row in cursor.fetchall()]
            if cache:
                cache.set_instructions(domain, agent_name, result)
            return result
        except Exception as e:
            logger.error(f"读取指令失败: {e}")
            return []

    # =========================================================
    # 🧬 Memory 1: 策略进化 (Layer 1)
    # =========================================================

    def store_strategy_evolution(
        self,
        domain: str,
        strategy_config: Dict,
        performance_score: float,
        is_active: bool = True
    ):
        """存储一次进化结果，支持灰度/回滚（is_active=0 视为影子策略）"""
        try:
            with self._get_conn() as conn:
                cursor = conn.cursor()
                # 获取当前最高版本号
                cursor.execute("SELECT MAX(version) FROM strategy_evolution WHERE domain = ?", (domain,))
                row = cursor.fetchone()
                current_v = row[0] if row and row[0] else 0
                new_v = current_v + 1
                
                now = datetime.now().isoformat()
                if is_active:
                    # 同域名历史 active 策略降级为非激活
                    cursor.execute(
                        "UPDATE strategy_evolution SET is_active = 0 WHERE domain = ? AND is_active = 1",
                        (domain,)
                    )

                cursor.execute('''
                    INSERT INTO strategy_evolution 
                    (domain, strategy_name, version, strategy_config, performance_score, created_at, is_active)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                ''', (
                    domain,
                    "universal_miner",
                    new_v,
                    json.dumps(strategy_config),
                    performance_score,
                    now,
                    1 if is_active else 0
                ))
                
                # 同时也记一条日志
                log_details = json.dumps({"evolved_strategies": strategy_config, "domain": domain})
                cursor.execute("INSERT INTO evolution_logs (timestamp, details) VALUES (?, ?)", (now, log_details))
                
                conn.commit()
                mode = "ACTIVE" if is_active else "SHADOW"
                logger.success(f"🧬 进化基因已入库: {domain} v{new_v} [{mode}] (Score: {performance_score:.2f})")
                cache = self._read_cache or get_persistent_read_cache()
                if cache:
                    cache.invalidate_domain(domain)
        except Exception as e:
            logger.error(f"存储策略进化失败: {e}")

    def get_latest_strategy(self, domain: str) -> Optional[Dict[str, Any]]:
        """获取该域名【最新时间】的策略 (用于版本连续性)"""
        try:
            with self._get_conn() as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    SELECT strategy_config, version, performance_score 
                    FROM strategy_evolution 
                    WHERE domain = ? 
                    ORDER BY version DESC LIMIT 1
                ''', (domain,))
                row = cursor.fetchone()
                if row:
                    return {
                        'config': json.loads(row[0]),
                        'version': row[1],
                        'score': row[2]
                    }
            return None
        except Exception as e:
            logger.error(f"获取最新策略失败: {e}")
            return None

    def get_best_strategy(self, domain: str) -> Optional[Dict[str, Any]]:
        """获取该域名【历史最高分】的策略"""
        cache = self._read_cache or get_persistent_read_cache()
        if cache:
            hit = cache.get_strategy(domain, "best")
            if hit is not _MISS:
                return hit
        try:
            with self._get_conn() as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    SELECT strategy_config, version, performance_score 
                    FROM strategy_evolution 
                    WHERE domain = ? 
                    ORDER BY performance_score DESC, version DESC LIMIT 1
                ''', (domain,))
                row = cursor.fetchone()
                result = None
                if row:
                    result = {
                        'config': json.loads(row[0]),
                        'version': row[1],
                        'score': row[2]
                    }
            if cache:
                cache.set_strategy(domain, "best", result)
            return result
        except Exception as e:
            logger.error(f"获取最佳策略失败: {e}")
            return None

    def get_latest_active_strategy(self, domain: str) -> Optional[Dict[str, Any]]:
        """获取该域名当前激活策略（用于运行时加载）"""
        cache = self._read_cache or get_persistent_read_cache()
        if cache:
            hit = cache.get_strategy(domain, "active")
            if hit is not _MISS:
                return hit
        try:
            with self._get_conn() as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    SELECT strategy_config, version, performance_score
                    FROM strategy_evolution
                    WHERE domain = ? AND is_active = 1
                    ORDER BY version DESC
                    LIMIT 1
                ''', (domain,))
                row = cursor.fetchone()
                result = None
                if row:
                    result = {
                        'config': json.loads(row[0]),
                        'version': row[1],
                        'score': row[2]
                    }
            if cache:
                cache.set_strategy(domain, "active", result)
            return result
        except Exception as e:
            logger.error(f"获取激活策略失败: {e}")
            return None

    def get_latest_evolution_config(self) -> Dict:
        """全局进化配置加载入口"""
        try:
            with self._get_conn() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT details FROM evolution_logs ORDER BY timestamp DESC LIMIT 1")
                row = cursor.fetchone()
                if row:
                    data = json.loads(row[0])
                    return data.get('evolved_strategies', {})
            return {}
        except Exception as e:
            logger.error(f"查询进化日志失败: {e}")
            return {}

    # =========================================================
    # 📚 Memory 2: 网站知识 & 路径智能 (Layer 2)
    # =========================================================

    def record_extraction(self, session_id: str, domain: str, url: str, 
                          site_profile: Dict, strategy_used: Dict, 
                          success: bool, l3_candidates: List, 
                          execution_time: float, error_message: str = None):
        """记录一次完整的挖掘结果 (更新 website_knowledge)"""
        try:
            l3_count = len(l3_candidates)
            self.store_website_knowledge(domain, site_profile, strategy_used, success, l3_count)
            logger.info(f"💾 提取记录已归档: {domain} | L3 found: {l3_count}")
        except Exception as e:
            logger.error(f"记录提取结果失败: {e}")

    def store_website_knowledge(self, domain: str, site_profile: Dict, strategies_used: Dict, success: bool, l3_count: int):
        try:
            with self._get_conn() as conn:
                cursor = conn.cursor()
                now = datetime.now().isoformat()
                
                # 🔥 [修复] 补上 strategies_used=excluded.strategies_used，防止进化策略更新丢失
                cursor.execute('''
                    INSERT INTO website_knowledge (domain, site_profile, strategies_used, success_count, avg_l3_count, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                    ON CONFLICT(domain) DO UPDATE SET
                    site_profile=excluded.site_profile,
                    strategies_used=excluded.strategies_used,  
                    success_count=success_count + excluded.success_count,
                    avg_l3_count=(avg_l3_count * success_count + excluded.avg_l3_count) / (success_count + 1),
                    updated_at=excluded.updated_at
                ''', (domain, json.dumps(site_profile), json.dumps(strategies_used), 1 if success else 0, float(l3_count), now))
                conn.commit()
        except Exception as e:
            logger.error(f"存储网站知识失败: {e}")

    def update_path_efficiency(self, domain: str, path_url: str, found_count: int):
        try:
            with self._get_conn() as conn:
                cursor = conn.cursor()
                now = datetime.now().isoformat()
                efficiency_val = 1.0 if found_count > 0 else 0.0
                
                # 🔥 [修复] 采用原子操作 UPSERT 代替 SELECT+IF/ELSE，彻底解决高并发条件下的死锁和 Unique 崩溃
                cursor.execute('''
                    INSERT INTO path_intelligence (domain, path_url, visit_count, efficiency, last_visited)
                    VALUES (?, ?, 1, ?, ?)
                    ON CONFLICT(domain, path_url) DO UPDATE SET
                    visit_count = visit_count + 1,
                    efficiency = (efficiency * visit_count + excluded.efficiency) / (visit_count + 1),
                    last_visited = excluded.last_visited
                ''', (domain, path_url, efficiency_val, now))
                conn.commit()
        except Exception as e:
            logger.error(f"更新路径效率失败: {e}")

    def get_top_path_efficiency(self, domain: str, limit: int = 200) -> List[Dict[str, Any]]:
        """读取该域名高效率路径（用于下一轮路径优先级排序）"""
        try:
            with self._get_conn() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    '''
                    SELECT path_url, efficiency, visit_count, last_visited
                    FROM path_intelligence
                    WHERE domain = ?
                    ORDER BY efficiency DESC, visit_count DESC
                    LIMIT ?
                    ''',
                    (domain, int(limit))
                )
                rows = cursor.fetchall()
                return [
                    {
                        "path_url": r[0],
                        "efficiency": float(r[1] or 0.0),
                        "visit_count": int(r[2] or 0),
                        "last_visited": r[3]
                    }
                    for r in rows
                ]
        except Exception as e:
            logger.error(f"读取路径效率失败: {e}")
            return []

    def record_domain_supervision(
        self,
        domain: str,
        miner_items: int,
        passed_items: int,
        rejected_items: int,
        reason_breakdown: Optional[Dict[str, int]] = None
    ):
        """记录来自 Inspector 的客观反馈（监督信号）"""
        try:
            miner_items = max(0, int(miner_items))
            passed_items = max(0, int(passed_items))
            rejected_items = max(0, int(rejected_items))
            now = datetime.now().isoformat()

            with self._get_conn() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    '''
                    INSERT INTO domain_supervision
                    (domain, total_miner_items, total_passed_items, total_rejected_items, rolling_pass_rate, last_updated)
                    VALUES (?, ?, ?, ?, ?, ?)
                    ON CONFLICT(domain) DO UPDATE SET
                        total_miner_items = total_miner_items + excluded.total_miner_items,
                        total_passed_items = total_passed_items + excluded.total_passed_items,
                        total_rejected_items = total_rejected_items + excluded.total_rejected_items,
                        rolling_pass_rate = CAST(total_passed_items + excluded.total_passed_items AS REAL) /
                                            CASE WHEN (total_miner_items + excluded.total_miner_items) > 0
                                                 THEN (total_miner_items + excluded.total_miner_items)
                                                 ELSE 1 END,
                        last_updated = excluded.last_updated
                    ''',
                    (
                        domain,
                        miner_items,
                        passed_items,
                        rejected_items,
                        (float(passed_items) / miner_items) if miner_items > 0 else 0.0,
                        now
                    )
                )

                reason_breakdown = reason_breakdown or {}
                for raw_code, raw_cnt in reason_breakdown.items():
                    reason_code = str(raw_code or "").strip().upper()
                    if not reason_code:
                        continue
                    inc = max(0, int(raw_cnt))
                    if inc <= 0:
                        continue
                    cursor.execute(
                        '''
                        INSERT INTO domain_supervision_reasons (domain, reason_code, reject_count, last_updated)
                        VALUES (?, ?, ?, ?)
                        ON CONFLICT(domain, reason_code) DO UPDATE SET
                            reject_count = reject_count + excluded.reject_count,
                            last_updated = excluded.last_updated
                        ''',
                        (domain, reason_code, inc, now)
                    )
                conn.commit()
                cache = self._read_cache or get_persistent_read_cache()
                if cache:
                    cache.invalidate_domain(domain)
        except Exception as e:
            logger.error(f"记录监督反馈失败 ({domain}): {e}")

    def get_domain_supervision(self, domain: str) -> Dict[str, Any]:
        """读取域名监督统计（客观 pass_rate）"""
        cache = self._read_cache or get_persistent_read_cache()
        if cache:
            hit = cache.get_supervision(domain)
            if hit is not _MISS:
                return hit
        try:
            with self._get_conn() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    '''
                    SELECT total_miner_items, total_passed_items, total_rejected_items, rolling_pass_rate, last_updated
                    FROM domain_supervision
                    WHERE domain = ?
                    ''',
                    (domain,)
                )
                row = cursor.fetchone()
                if not row:
                    result = {
                        "domain": domain,
                        "reviewed_count": 0,
                        "pass_count": 0,
                        "reject_count": 0,
                        "pass_rate": None,
                        "last_updated": None,
                        "reason_breakdown": {},
                    }
                else:
                    total_miner = int(row[0] or 0)
                    pass_count = int(row[1] or 0)
                    reject_count = int(row[2] or 0)
                    pass_rate = float(row[3]) if row[3] is not None else (float(pass_count) / total_miner if total_miner > 0 else None)
                    cursor.execute(
                        '''
                        SELECT reason_code, reject_count
                        FROM domain_supervision_reasons
                        WHERE domain = ?
                        ORDER BY reject_count DESC
                        LIMIT 32
                        ''',
                        (domain,)
                    )
                    reason_rows = cursor.fetchall()
                    reason_breakdown = {
                        str(r[0]): int(r[1] or 0)
                        for r in reason_rows
                    }
                    result = {
                        "domain": domain,
                        "reviewed_count": total_miner,
                        "pass_count": pass_count,
                        "reject_count": reject_count,
                        "pass_rate": pass_rate,
                        "last_updated": row[4],
                        "reason_breakdown": reason_breakdown,
                    }
            if cache:
                cache.set_supervision(domain, result)
            return result
        except Exception as e:
            logger.error(f"读取监督反馈失败 ({domain}): {e}")
            return {
                "domain": domain,
                "reviewed_count": 0,
                "pass_count": 0,
                "reject_count": 0,
                "pass_rate": None,
                "last_updated": None,
                "reason_breakdown": {}
            }

    def save_session_snapshot(self, session_id: str, domain: str, data: dict):
        """💾 保存全量运行快照"""
        try:
            # 🔥 [修复] 移除裸连 sqlite3.connect，统一调用增强版的 _get_conn
            with self._get_conn() as conn:
                cursor = conn.cursor()
                query_insert = """
                INSERT OR REPLACE INTO session_snapshots (session_id, domain, full_data)
                VALUES (?, ?, ?)
                """
                cursor.execute(query_insert, (
                    session_id, 
                    domain, 
                    json.dumps(data, ensure_ascii=False)
                ))
                conn.commit()
            return True
        except Exception as e:
            logger.error(f"❌ 数据库快照保存失败: {e}")
            return False
