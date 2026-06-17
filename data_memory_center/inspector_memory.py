import sqlite3
import hashlib
import json
import logging
import os
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Union

# 尝试导入 ChromaDB
try:
    import chromadb
    CHROMA_AVAILABLE = True
except ImportError:
    CHROMA_AVAILABLE = False

logger = logging.getLogger("inspector.memory")

class InspectorMemoryManager:
    def __init__(self, storage_root=None):
        """
        初始化 Inspector 的三层记忆系统
        """
        # 如果未指定路径，默认在当前文件的同级目录下创建一个 inspector_internal_db 文件夹
        if storage_root is None:
            current_dir = os.path.dirname(os.path.abspath(__file__))
            self.storage_root = os.path.join(current_dir, "inspector_internal_db")
        else:
            self.storage_root = storage_root

        # 确保目录存在
        if not os.path.exists(self.storage_root):
            os.makedirs(self.storage_root)

        # 定义存储路径
        self.db_path = os.path.join(self.storage_root, "inspector_cache.db")
        self.chroma_path = os.path.join(self.storage_root, "inspector_rag_db")

        # 初始化 L1/L2
        self._init_sql_tables()

        # 初始化 L3 (RAG)
        self.chroma_client = None
        self.collection = None
        if CHROMA_AVAILABLE:
            try:
                self.chroma_client = chromadb.PersistentClient(path=self.chroma_path)
                self.collection = self.chroma_client.get_or_create_collection(name="inspector_cases")
                logger.info(f"✅ Inspector L3 Memory (RAG) ready at {self.chroma_path}")
            except Exception as e:
                logger.error(f"❌ ChromaDB init failed: {e}")
        else:
            logger.warning("⚠️ ChromaDB not installed. L3 Memory disabled.")

    def _get_conn(self):
        return sqlite3.connect(self.db_path)

    def _init_sql_tables(self):
        with self._get_conn() as conn:
            # L1: 缓存表 (Url Hash -> Result)
            conn.execute('''
                CREATE TABLE IF NOT EXISTS cache_l1 (
                    url_hash TEXT PRIMARY KEY,
                    url TEXT,
                    result_json TEXT,
                    updated_at DATETIME
                )
            ''')
            # L2: 规则表 (Rule Text -> Active Status)
            conn.execute('''
                CREATE TABLE IF NOT EXISTS rules_l2 (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    rule_text TEXT,
                    is_active BOOLEAN DEFAULT 1,
                    created_at DATETIME
                )
            ''')
        logger.info(f"✅ Inspector L1/L2 Memory (SQLite) ready at {self.db_path}")

    # ==========================================
    # L1: 判决档案 (Cache Layer) - 极速去重
    # ==========================================
    
    def check_l1_cache(self, url: str, expiry_days=7) -> Optional[Dict]:
        """检查 URL 是否在有效期内已审过"""
        if not url: return None
        url_hash = hashlib.md5(url.strip().lower().encode()).hexdigest()
        
        try:
            with self._get_conn() as conn:
                cursor = conn.execute("SELECT result_json, updated_at FROM cache_l1 WHERE url_hash=?", (url_hash,))
                row = cursor.fetchone()
                
            if row:
                result_json, updated_str = row
                updated_at = datetime.fromisoformat(updated_str)
                # 检查过期
                if datetime.now() - updated_at < timedelta(days=expiry_days):
                    res = json.loads(result_json)
                    res['is_cached'] = True # 标记为缓存
                    return res
        except Exception as e:
            logger.warning(f"Cache check failed: {e}")
        return None

    def save_l1_cache(self, url: str, result_dict: Dict):
        """保存审计结果到缓存"""
        if not url: return
        url_hash = hashlib.md5(url.strip().lower().encode()).hexdigest()
        now = datetime.now().isoformat()
        
        try:
            with self._get_conn() as conn:
                conn.execute(
                    "INSERT OR REPLACE INTO cache_l1 (url_hash, url, result_json, updated_at) VALUES (?, ?, ?, ?)",
                    (url_hash, url, json.dumps(result_dict, ensure_ascii=False), now)
                )
        except Exception as e:
            logger.error(f"Cache save failed: {e}")

    # ==========================================
    # L2: 司法解释 (Rules Layer) - 强制指令
    # ==========================================

    def add_l2_rule(self, rule_text: str):
        """添加一条新的人类规则"""
        try:
            with self._get_conn() as conn:
                exists = conn.execute("SELECT 1 FROM rules_l2 WHERE rule_text = ?", (rule_text,)).fetchone()
                if not exists:
                    conn.execute(
                        "INSERT INTO rules_l2 (rule_text, is_active, created_at) VALUES (?, 1, ?)",
                        (rule_text, datetime.now().isoformat())
                    )
                    logger.info(f"📝 L2 Rule Added: {rule_text}")
        except Exception as e:
            logger.error(f"Rule add failed: {e}")

    def get_l2_rules_prompt(self) -> str:
        """获取所有激活的规则，拼接成 Prompt"""
        try:
            with self._get_conn() as conn:
                cursor = conn.execute("SELECT rule_text FROM rules_l2 WHERE is_active=1")
                rules = [f"- {row[0]}" for row in cursor.fetchall()]
            
            if not rules:
                return ""
            return "【Human Mandatory Rules (MUST FOLLOW)】\n" + "\n".join(rules)
        except Exception:
            return ""

    # ==========================================
    # L3: 判例库 (RAG Layer) - 智能类比
    # ==========================================

    def add_l3_case(self, item_summary: str, verdict: str, reason: str, is_human: bool = False):
        """
        存入一个判例
        """
        if not self.collection: return

        # 简单清洗
        item_summary = str(item_summary)[:1000] # 限制长度
        doc_id = hashlib.md5(item_summary.encode()).hexdigest()
        
        try:
            self.collection.upsert(
                ids=[doc_id],
                documents=[item_summary],
                metadatas=[{
                    "verdict": verdict,
                    "reason": reason,
                    "is_human": is_human,
                    "timestamp": datetime.now().isoformat()
                }]
            )
            tag = "[Human Fix]" if is_human else "[Auto]"
            logger.info(f"🧠 L3 Case Learned {tag}: {verdict}")
        except Exception as e:
            logger.error(f"Failed to add L3 case: {e}")

    def get_l3_precedents_prompt(self, current_summary: str, n_results=3) -> str:
        """检索最相似的历史判例"""
        if not self.collection: return ""

        try:
            results = self.collection.query(
                query_texts=[current_summary[:1000]],
                n_results=n_results
            )
        except Exception:
            return ""

        if not results or not results['documents'] or not results['documents'][0]:
            return ""

        prompt = "【Similar Past Cases (For Reference)】\n"
        found_any = False
        
        for i in range(len(results['documents'][0])):
            doc = results['documents'][0][i]
            meta = results['metadatas'][0][i]
            
            doc_snippet = doc[:80].replace("\n", " ")
            
            prompt += f"- Case: \"{doc_snippet}...\"\n"
            prompt += f"  -> Historical Verdict: {meta['verdict']}\n"
            prompt += f"  -> Reason: {meta['reason']}\n"
            found_any = True
            
        return prompt if found_any else ""
