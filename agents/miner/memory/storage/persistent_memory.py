import os
import sqlite3
import json
import time
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional
from pathlib import Path
from loguru import logger

class PersistentMemoryStorage:
    """
    长期记忆存储 - 使用 SQLite 数据库
    修复版：确保表结构完整，打通进化回路
    """
    
    def __init__(self, db_path: str = "memory_data/persistent_memory.db"):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_database()
        logger.info(f"PersistentMemoryStorage 核心已激活: {db_path}")
    
    def _get_conn(self):
        """统一的连接获取方法"""
        return sqlite3.connect(self.db_path)

    def _init_database(self):
        """初始化所有必要的数据库表"""
        with self._get_conn() as conn:
            cursor = conn.cursor()
            
            # 1. 网站宏观知识表
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
            
            # 2. 策略进化史 (进化的关键！)
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

            # 4. 进化日志 (Global Config)
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS evolution_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT,
                    details TEXT
                )
            ''')
            
            conn.commit()

    # --- 进化数据读写核心 ---

    def store_strategy_evolution(self, domain: str, strategy_config: Dict, performance_score: float):
        """存储一次进化结果"""
        try:
            with self._get_conn() as conn:
                cursor = conn.cursor()
                # 获取当前最高版本号
                cursor.execute("SELECT MAX(version) FROM strategy_evolution WHERE domain = ?", (domain,))
                current_v = cursor.fetchone()[0] or 0
                new_v = current_v + 1
                
                now = datetime.now().isoformat()
                cursor.execute('''
                    INSERT INTO strategy_evolution 
                    (domain, strategy_name, version, strategy_config, performance_score, created_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                ''', (domain, "universal_miner", new_v, json.dumps(strategy_config), performance_score, now))
                
                # 同时存入 evolution_logs 供 get_latest_evolution_config 调用
                log_details = json.dumps({"evolved_strategies": strategy_config, "domain": domain})
                cursor.execute("INSERT INTO evolution_logs (timestamp, details) VALUES (?, ?)", (now, log_details))
                
                conn.commit()
                logger.success(f"🧬 进化基因已入库: {domain} v{new_v} (Score: {performance_score})")
        except Exception as e:
            logger.error(f"存储策略进化失败: {e}")

    def get_latest_strategy(self, domain: str) -> Optional[Dict[str, Any]]:
        """获取该域名最新的进化策略"""
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

    # --- 基础知识存储 ---

    def store_website_knowledge(self, domain: str, site_profile: Dict, strategies_used: Dict, success: bool, l3_count: int):
        try:
            with self._get_conn() as conn:
                cursor = conn.cursor()
                now = datetime.now().isoformat()
                cursor.execute('''
                    INSERT INTO website_knowledge (domain, site_profile, strategies_used, success_count, avg_l3_count, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                    ON CONFLICT(domain) DO UPDATE SET
                    site_profile=excluded.site_profile,
                    success_count=success_count + 1,
                    avg_l3_count=(avg_l3_count + excluded.avg_l3_count)/2.0,
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
                cursor.execute("SELECT visit_count, efficiency FROM path_intelligence WHERE domain=? AND path_url=?", (domain, path_url))
                row = cursor.fetchone()
                if row:
                    new_visits = row[0] + 1
                    new_eff = (row[1] * row[0] + (1.0 if found_count > 0 else 0.0)) / new_visits
                    cursor.execute("UPDATE path_intelligence SET visit_count=?, efficiency=?, last_visited=? WHERE domain=? AND path_url=?",
                                 (new_visits, new_eff, now, domain, path_url))
                else:
                    cursor.execute("INSERT INTO path_intelligence (domain, path_url, visit_count, efficiency, last_visited) VALUES (?, ?, 1, ?, ?)",
                                 (domain, path_url, 1.0 if found_count > 0 else 0.0, now))
                conn.commit()
        except Exception as e:
            logger.error(f"更新路径效率失败: {e}")

    def save_session_snapshot(self, session_id: str, domain: str, data: dict):
            """
            💾 保存全量运行快照至 SQL 数据库
            """
            try:
                # 1. 确保表结构存在 (session_id, domain, timestamp, full_data)
                # 如果你的初始化里没有建这个表，这里会自动创建一个
                query_create = """
                CREATE TABLE IF NOT EXISTS session_snapshots (
                    session_id TEXT PRIMARY KEY,
                    domain TEXT,
                    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                    full_data TEXT
                )
                """
                
                # 2. 执行写入
                # 注意：data 需要转换为 JSON 字符串存储
                with sqlite3.connect(self.db_path) as conn:
                    cursor = conn.cursor()
                    cursor.execute(query_create)
                    
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
                
                logger.success(f"🗄️ Session 快照已存入数据库: {session_id}")
                return True
            except Exception as e:
                logger.error(f"❌ 数据库快照保存失败: {e}")
                return False