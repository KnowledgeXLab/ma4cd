import json
import os
from typing import Optional, List, Dict
from agents.miner.memory.models.memory_models import MemorySchema, AuditEntry

class PersistentMemory:
    """
    负责记忆的物理存储 (JSON 形式)。
    优化了 IO 性能，支持单条/批量写入。
    """
    
    def __init__(self, storage_path: str = "data/audit_memory.json"):
        self.storage_path = storage_path
        os.makedirs(os.path.dirname(self.storage_path), exist_ok=True)
        self.data = self._load()

    def _load(self) -> MemorySchema:
        """加载数据，增加容错处理"""
        if os.path.exists(self.storage_path):
            try:
                with open(self.storage_path, 'r', encoding='utf-8') as f:
                    content = f.read()
                    if not content.strip(): # 处理空文件的情况
                        return MemorySchema()
                    return MemorySchema(**json.loads(content))
            except (json.JSONDecodeError, Exception) as e:
                print(f"⚠️ [Storage] 加载记忆文件失败 ({e})，将初始化新库。")
                return MemorySchema()
        return MemorySchema()

    def save(self):
        """持久化到磁盘"""
        try:
            with open(self.storage_path, 'w', encoding='utf-8') as f:
                # 兼容 Pydantic v1 (.json()) 和 v2 (.model_dump_json())
                if hasattr(self.data, 'model_dump_json'):
                    f.write(self.data.model_dump_json(indent=4))
                else:
                    f.write(self.data.json(ensure_ascii=False, indent=4))
        except Exception as e:
            print(f"❌ [Storage] 保存失败: {e}")

    def update_entry(self, entry: AuditEntry, auto_save: bool = True):
        """
        更新单条记录。
        :param auto_save: 是否立即写入磁盘。批量操作时建议设为 False。
        """
        self.data.entries[entry.url] = entry
        if auto_save:
            self.save()

    def bulk_update(self, entries: List[AuditEntry]):
        """
        🔥 [新增] 批量更新。
        只在内存中更新所有数据，最后统一执行一次 IO 写入。
        """
        for entry in entries:
            self.data.entries[entry.url] = entry
        self.save() # 1000条数据只写一次盘

    def get_entry(self, url: str) -> Optional[AuditEntry]:
        """获取单条记录"""
        return self.data.entries.get(url)

    def get_all(self) -> List[AuditEntry]:
        """
        🔥 [新增] 获取所有记录。
        支持 MemoryManager 的 get_recent_failures 调用。
        """
        return list(self.data.entries.values())