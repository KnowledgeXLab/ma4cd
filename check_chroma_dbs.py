import chromadb
import os

def inspect_chromadb(db_path, db_name):
    print(f"\n" + "="*70)
    print(f"🔍 正在检查金库: {db_name}")
    print(f"📂 物理路径: {db_path}")
    print("="*70)
    
    if not os.path.exists(db_path):
        print(f"⚠️ 路径不存在，可能是该层级还没写入过数据，跳过...")
        return

    try:
        # 连接本地持久化的 ChromaDB
        client = chromadb.PersistentClient(path=db_path)
        collections = client.list_collections()
        
        if not collections:
            print("📭 该数据库已创建，但目前没有 Collection (数据集合)。")
            return
            
        for collection_obj in collections:
            # 兼容不同版本 ChromaDB 的返回值类型
            col_name = collection_obj.name if hasattr(collection_obj, 'name') else collection_obj
            print(f"\n📁 集合 (Collection): {col_name}")
            
            collection = client.get_collection(name=col_name)
            
            # 💡 核心优化 1：使用 count() 秒级获取总数
            total_items = collection.count()
            print(f"📊 总沉淀线索/记忆数: {total_items} 条")
            
            if total_items == 0:
                continue
                
            # 💡 核心优化 2：拉取前 3 条，并且强制包含 metadatas 和 documents(正文)
            data = collection.get(limit=3, include=['metadatas', 'documents'])
            
            print("👀 核心预览 (前 3 条):")
            for i in range(len(data['ids'])):
                item_id = data['ids'][i]
                metadata = data['metadatas'][i] if data['metadatas'] and data['metadatas'][i] else {}
                document = data['documents'][i] if data['documents'] and data['documents'][i] else "无正文"
                
                print(f"  [{i+1}] ID: {item_id}")
                
                # 🔮 分支判断：是通过 URL 判断这是“资产库”还是“心智库”
                if 'url' in metadata:
                    # ==========================================
                    # 模式 A：这是 L1~L4 实体资产库 (Data Center)
                    # ==========================================
                    if 'title' in metadata:
                        print(f"      🏷️ Title: {metadata.get('title')}")
                    print(f"      🔗 URL: {metadata.get('url')}")
                    if 'level' in metadata:
                        print(f"      ⭐ Level: {metadata.get('level')}")
                    if 'description' in metadata:
                        desc = str(metadata.get('description'))[:80].replace('\n', ' ')
                        print(f"      📝 Desc: {desc}...")
                else:
                    # ==========================================
                    # 模式 B：这是 Evolution_DNA 心智反思库 (Mind DB)
                    # ==========================================
                    # 1. 动态打印所有心智专属的 Metadata (比如 domain, score, timestamp 等)
                    for k, v in metadata.items():
                        print(f"      🏷️ Meta [{k}]: {v}")
                    
                    # 2. 打印大模型写下的反思正文 (截取前 150 字防止刷屏)
                    doc_snippet = str(document)[:150].replace('\n', ' ')
                    print(f"      🧠 DNA 反思: {doc_snippet}...")
                    
                print("      " + "-"*40)
                
    except Exception as e:
        print(f"❌ 读取数据库失败: {e}")

if __name__ == "__main__":
    base_dir = "data_memory_center"
    
    # 将“资产金库”和“智能体心智库”统一纳入盘点雷达
    dbs = {
        "L1_Hub (顶级枢纽)": os.path.join(base_dir, "l1_db", "chroma_db"),
        "L2_Portal (二级入口)": os.path.join(base_dir, "l2_db", "chroma_db"),
        "L3_Database (独立数据库)": os.path.join(base_dir, "l3_db", "chroma_db"),
        "L4_Asset (底层核心资产)": os.path.join(base_dir, "l4_db", "chroma_db"),
        "Evolution_DNA (智能体进化基因库)": os.path.join("memory_data", "chroma_db") 
    }
    
    print("🚀 启动 MA4CD 数据资产与心智盘点程序...")
    for name, path in dbs.items():
        inspect_chromadb(path, name)
    print("\n🎉 盘点完成！")