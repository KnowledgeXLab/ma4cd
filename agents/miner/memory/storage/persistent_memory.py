# memory/storage/persistent_memory.py
import sqlite3
import json
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional
from pathlib import Path
from loguru import logger


class PersistentMemoryStorage:
    """
    长期记忆存储 - 使用 SQLite 数据库
    存储跨任务的知识积累和策略进化
    """
    
    def __init__(self, db_path: str = "memory_data/persistent_memory.db"):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        
        # 初始化数据库
        self._init_database()
        
        logger.info(f"PersistentMemoryStorage 初始化完成: {db_path}")
    
    def _init_database(self):
        """初始化数据库表"""
        
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            
            # 网站知识表
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS website_knowledge (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    domain TEXT NOT NULL,
                    site_profile TEXT NOT NULL,
                    strategies_used TEXT,
                    success_count INTEGER DEFAULT 0,
                    failure_count INTEGER DEFAULT 0,
                    avg_l3_count REAL DEFAULT 0.0,
                    avg_execution_time REAL DEFAULT 0.0,
                    last_success_at TEXT,
                    last_failure_at TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(domain)
                )
            ''')
            
            # 策略进化表
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS strategy_evolution (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    strategy_name TEXT NOT NULL,
                    version INTEGER NOT NULL,
                    strategy_config TEXT NOT NULL,
                    performance_score REAL DEFAULT 0.0,
                    usage_count INTEGER DEFAULT 0,
                    success_rate REAL DEFAULT 0.0,
                    created_at TEXT NOT NULL,
                    is_active BOOLEAN DEFAULT 1,
                    UNIQUE(strategy_name, version)
                )
            ''')
            
            # 学习事件表
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS learning_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    domain TEXT NOT NULL,
                    context_data TEXT NOT NULL,
                    result_data TEXT NOT NULL,
                    execution_time REAL NOT NULL,
                    created_at TEXT NOT NULL
                )
            ''')
            
            # 性能指标表 - 修复主键问题
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS performance_metrics (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    metric_name TEXT NOT NULL,
                    metric_value REAL NOT NULL,
                    context TEXT,
                    recorded_at TEXT NOT NULL
                )
            ''')
            
            # 模式识别表
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS pattern_recognition (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    pattern_type TEXT NOT NULL,
                    pattern_data TEXT NOT NULL,
                    confidence REAL NOT NULL,
                    usage_count INTEGER DEFAULT 0,
                    success_rate REAL DEFAULT 0.0,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
            ''')
            
            # 创建索引
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_website_domain ON website_knowledge(domain)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_strategy_name ON strategy_evolution(strategy_name)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_learning_session ON learning_events(session_id)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_performance_metric ON performance_metrics(metric_name)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_pattern_type ON pattern_recognition(pattern_type)')
            
            conn.commit()
    
    def store_website_knowledge(self, domain: str, site_profile: Dict, 
                               strategies_used: Dict, success: bool, 
                               l3_count: int, execution_time: float):
        """存储网站知识"""
        
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                
                now = datetime.now().isoformat()
                
                # 检查是否已存在
                cursor.execute('SELECT * FROM website_knowledge WHERE domain = ?', (domain,))
                existing = cursor.fetchone()
                
                if existing:
                    # 更新现有记录
                    old_success = existing[4]  # success_count
                    old_failure = existing[5]  # failure_count
                    old_avg_l3 = existing[6]   # avg_l3_count
                    old_avg_time = existing[7] # avg_execution_time
                    
                    if success:
                        new_success = old_success + 1
                        new_failure = old_failure
                        last_success_at = now
                        last_failure_at = existing[9]
                    else:
                        new_success = old_success
                        new_failure = old_failure + 1
                        last_success_at = existing[8]
                        last_failure_at = now
                    
                    total_attempts = new_success + new_failure
                    
                    # 计算新的平均值
                    if success and new_success > 0:
                        new_avg_l3 = ((old_avg_l3 * old_success) + l3_count) / new_success
                        new_avg_time = ((old_avg_time * old_success) + execution_time) / new_success
                    else:
                        new_avg_l3 = old_avg_l3
                        new_avg_time = old_avg_time
                    
                    cursor.execute('''
                        UPDATE website_knowledge 
                        SET site_profile = ?, strategies_used = ?, success_count = ?, 
                            failure_count = ?, avg_l3_count = ?, avg_execution_time = ?,
                            last_success_at = ?, last_failure_at = ?, updated_at = ?
                        WHERE domain = ?
                    ''', (
                        json.dumps(site_profile), json.dumps(strategies_used),
                        new_success, new_failure, new_avg_l3, new_avg_time,
                        last_success_at, last_failure_at, now, domain
                    ))
                else:
                    # 插入新记录
                    success_count = 1 if success else 0
                    failure_count = 0 if success else 1
                    avg_l3 = l3_count if success else 0.0
                    avg_time = execution_time if success else 0.0
                    last_success_at = now if success else None
                    last_failure_at = now if not success else None
                    
                    cursor.execute('''
                        INSERT INTO website_knowledge 
                        (domain, site_profile, strategies_used, success_count, failure_count,
                         avg_l3_count, avg_execution_time, last_success_at, last_failure_at,
                         created_at, updated_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ''', (
                        domain, json.dumps(site_profile), json.dumps(strategies_used),
                        success_count, failure_count, avg_l3, avg_time,
                        last_success_at, last_failure_at, now, now
                    ))
                
                conn.commit()
                logger.debug(f"网站知识已存储: {domain} (成功: {success})")
                
        except Exception as e:
            logger.error(f"存储网站知识失败: {e}")
    
    def get_website_knowledge(self, domain: str) -> Optional[Dict[str, Any]]:
        """获取网站知识"""
        
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute('SELECT * FROM website_knowledge WHERE domain = ?', (domain,))
                row = cursor.fetchone()
                
                if row:
                    return {
                        'domain': row[1],
                        'site_profile': json.loads(row[2]),
                        'strategies_used': json.loads(row[3]) if row[3] else {},
                        'success_count': row[4],
                        'failure_count': row[5],
                        'avg_l3_count': row[6],
                        'avg_execution_time': row[7],
                        'success_rate': row[4] / (row[4] + row[5]) if (row[4] + row[5]) > 0 else 0,
                        'last_success_at': row[8],
                        'last_failure_at': row[9],
                        'created_at': row[10],
                        'updated_at': row[11]
                    }
                
                return None
                
        except Exception as e:
            logger.error(f"获取网站知识失败: {e}")
            return None
    
    def find_similar_websites(self, site_profile: Dict, limit: int = 5) -> List[Dict[str, Any]]:
        """查找相似网站"""
        
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    SELECT * FROM website_knowledge 
                    WHERE success_count > 0 
                    ORDER BY success_count DESC, avg_l3_count DESC 
                    LIMIT ?
                ''', (limit * 2,))  # 获取更多候选，然后筛选
                
                rows = cursor.fetchall()
                similar_sites = []
                
                target_type = site_profile.get('institutional_type', '')
                target_scale = site_profile.get('estimated_scale', '')
                
                for row in rows:
                    stored_profile = json.loads(row[2])
                    
                    # 计算相似度
                    similarity = 0.0
                    if stored_profile.get('institutional_type') == target_type:
                        similarity += 0.5
                    if stored_profile.get('estimated_scale') == target_scale:
                        similarity += 0.3
                    if stored_profile.get('language_hints') == site_profile.get('language_hints'):
                        similarity += 0.2
                    
                    if similarity > 0.3:  # 相似度阈值
                        similar_sites.append({
                            'domain': row[1],
                            'similarity': similarity,
                            'success_count': row[4],
                            'avg_l3_count': row[6],
                            'success_rate': row[4] / (row[4] + row[5]) if (row[4] + row[5]) > 0 else 0,
                            'site_profile': stored_profile,
                            'strategies_used': json.loads(row[3]) if row[3] else {}
                        })
                
                # 按相似度排序
                similar_sites.sort(key=lambda x: (x['similarity'], x['success_rate']), reverse=True)
                return similar_sites[:limit]
                
        except Exception as e:
            logger.error(f"查找相似网站失败: {e}")
            return []
    
    def store_strategy_evolution(self, strategy_name: str, version: int, 
                               strategy_config: Dict, performance_score: float):
        """存储策略进化"""
        
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                
                now = datetime.now().isoformat()
                
                cursor.execute('''
                    INSERT OR REPLACE INTO strategy_evolution 
                    (strategy_name, version, strategy_config, performance_score, 
                     usage_count, success_rate, created_at, is_active)
                    VALUES (?, ?, ?, ?, 0, 0.0, ?, 1)
                ''', (
                    strategy_name, version, json.dumps(strategy_config),
                    performance_score, now
                ))
                
                conn.commit()
                logger.debug(f"策略进化已存储: {strategy_name} v{version}")
                
        except Exception as e:
            logger.error(f"存储策略进化失败: {e}")
    
    def get_latest_strategy(self, strategy_name: str) -> Optional[Dict[str, Any]]:
        """获取最新策略"""
        
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    SELECT * FROM strategy_evolution 
                    WHERE strategy_name = ? AND is_active = 1 
                    ORDER BY version DESC LIMIT 1
                ''', (strategy_name,))
                
                row = cursor.fetchone()
                if row:
                    return {
                        'strategy_name': row[1],
                        'version': row[2],
                        'strategy_config': json.loads(row[3]),
                        'performance_score': row[4],
                        'usage_count': row[5],
                        'success_rate': row[6],
                        'created_at': row[7]
                    }
                
                return None
                
        except Exception as e:
            logger.error(f"获取最新策略失败: {e}")
            return None
    
    def record_learning_event(self, session_id: str, event_type: str, 
                            domain: str, context_data: Dict, result_data: Dict, 
                            execution_time: float):
        """记录学习事件"""
        
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                
                cursor.execute('''
                    INSERT INTO learning_events 
                    (session_id, event_type, domain, context_data, result_data, 
                     execution_time, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                ''', (
                    session_id, event_type, domain,
                    json.dumps(context_data), json.dumps(result_data),
                    execution_time, datetime.now().isoformat()
                ))
                
                conn.commit()
                logger.debug(f"学习事件已记录: {event_type} - {domain}")
                
        except Exception as e:
            logger.error(f"记录学习事件失败: {e}")
    
    def record_performance_metric(self, metric_name: str, metric_value: float, 
                                context: str = None):
        """记录性能指标"""
        
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                
                cursor.execute('''
                    INSERT INTO performance_metrics 
                    (metric_name, metric_value, context, recorded_at)
                    VALUES (?, ?, ?, ?)
                ''', (
                    metric_name, metric_value, context, datetime.now().isoformat()
                ))
                
                conn.commit()
                logger.debug(f"性能指标已记录: {metric_name} = {metric_value}")
                
        except Exception as e:
            logger.error(f"记录性能指标失败: {e}")
    
    def get_performance_trends(self, metric_name: str, days: int = 7) -> List[Dict[str, Any]]:
        """获取性能趋势"""
        
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                
                since_date = (datetime.now() - timedelta(days=days)).isoformat()
                
                cursor.execute('''
                    SELECT metric_value, recorded_at FROM performance_metrics 
                    WHERE metric_name = ? AND recorded_at >= ? 
                    ORDER BY recorded_at
                ''', (metric_name, since_date))
                
                rows = cursor.fetchall()
                return [
                    {'value': row[0], 'recorded_at': row[1]}
                    for row in rows
                ]
                
        except Exception as e:
            logger.error(f"获取性能趋势失败: {e}")
            return []
    
    def get_stats(self) -> Dict[str, Any]:
        """获取统计信息"""
        
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                
                # 网站知识统计
                cursor.execute('SELECT COUNT(*), SUM(success_count), SUM(failure_count) FROM website_knowledge')
                website_stats = cursor.fetchone()
                
                # 策略统计
                cursor.execute('SELECT COUNT(*), MAX(version) FROM strategy_evolution WHERE is_active = 1')
                strategy_stats = cursor.fetchone()
                
                # 学习事件统计
                cursor.execute('SELECT COUNT(*) FROM learning_events WHERE created_at >= ?', 
                             ((datetime.now() - timedelta(days=7)).isoformat(),))
                recent_events = cursor.fetchone()[0]
                
                return {
                    'website_knowledge': {
                        'total_websites': website_stats[0] or 0,
                        'total_successes': website_stats[1] or 0,
                        'total_failures': website_stats[2] or 0,
                        'avg_success_rate': (website_stats[1] or 0) / max((website_stats[1] or 0) + (website_stats[2] or 0), 1)
                    },
                    'strategy_evolution': {
                        'unique_strategies': strategy_stats[0] or 0,
                        'max_version': strategy_stats[1] or 0
                    },
                    'learning_events': {
                        'recent_events': recent_events
                    }
                }
                
        except Exception as e:
            logger.error(f"获取统计信息失败: {e}")
            return {}
    
    def clear_old_data(self, days: int = 30):
        """清理旧数据"""
        
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                
                cutoff_date = (datetime.now() - timedelta(days=days)).isoformat()
                
                # 清理旧的学习事件
                cursor.execute('DELETE FROM learning_events WHERE created_at < ?', (cutoff_date,))
                
                # 清理旧的性能指标
                cursor.execute('DELETE FROM performance_metrics WHERE recorded_at < ?', (cutoff_date,))
                
                conn.commit()
                logger.info(f"已清理 {days} 天前的旧数据")
                
        except Exception as e:
            logger.error(f"清理旧数据失败: {e}")
