import pandas as pd
import base64
import hashlib
import os
from pathlib import Path

# ==================== 解密函数（官方原版） ====================
def derive_key(password: str, length: int) -> bytes:
    """用 canary 作为密码生成 XOR key"""
    hasher = hashlib.sha256()
    hasher.update(password.encode('utf-8'))
    key = hasher.digest()
    return (key * (length // len(key) + 1))[:length]

def decrypt(ciphertext_b64: str, password: str) -> str:
    """官方 XOR + base64 解密"""
    if not ciphertext_b64 or not password:
        return ""
    encrypted = base64.b64decode(ciphertext_b64)
    key = derive_key(password, len(encrypted))
    decrypted = bytes(a ^ b for a, b in zip(encrypted, key))
    return decrypted.decode('utf-8', errors='ignore')

# ==================== 下载 + 解密主流程 ====================
def download_and_decrypt_browsecomp(output_dir: str = "data/browsecomp"):
    os.makedirs(output_dir, exist_ok=True)
    csv_url = "https://openaipublic.blob.core.windows.net/simple-evals/browse_comp_test_set.csv"
    
    print("正在下载 BrowseComp 测试集...")
    df = pd.read_csv(csv_url)
    print(f"下载完成，共 {len(df)} 条题目")
    
    decrypted_data = []
    for idx, row in df.iterrows():
        problem = decrypt(row.get("problem", ""), row.get("canary", ""))
        answer = decrypt(row.get("answer", ""), row.get("canary", ""))
        
        decrypted_data.append({
            "id": idx,
            "question": problem,
            "ground_truth": answer,
            "canary": row.get("canary", "")  # 保留用于调试
        })
    
    # 保存解密后的 JSON（推荐格式）
    output_path = Path(output_dir) / "browsecomp_decrypted.json"
    pd.DataFrame(decrypted_data).to_json(output_path, orient="records", force_ascii=False, indent=2)
    
    print(f"✅ 解密完成！已保存到 {output_path}")
    print(f"前3条预览：")
    for item in decrypted_data[:3]:
        print(f"  Q: {item['question'][:80]}...")
    
    return output_path

# 一键运行
if __name__ == "__main__":
    download_and_decrypt_browsecomp()