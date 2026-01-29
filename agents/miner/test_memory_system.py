import sqlite3

# 替换为你的数据库路径
db_path = "memory_data/persistent_memory.db"
conn = sqlite3.connect(db_path)
cursor = conn.cursor()

# 检查进化记录表
try:
    cursor.execute("SELECT domain, generation, quality_score FROM evolution_history ORDER BY id DESC LIMIT 5")
    rows = cursor.fetchall()
    print("=== 数据库中的进化记录 ===")
    for row in rows:
        print(f"域名: {row[0]} | 代数: {row[1]} | 分数: {row[2]}")
except Exception as e:
    print(f"查询失败: {e}")

conn.close()