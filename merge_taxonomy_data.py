#!/usr/bin/env python3
"""
将 batch_taxonomy_20260602_104809.json 中的数据按照
taxonomy_batch_seq201_332_passed_urls.csv 的格式合并导出全量表
"""

import json
import csv
from pathlib import Path

# 文件路径
project_root = Path("/home/zhuyao/Documents/ma4cd_now")
csv_input = project_root / "reports" / "taxonomy_batch_seq201_332_passed_urls.csv"
json_input = project_root / "reports" / "batch_taxonomy_20260602_104809.json"
csv_output = project_root / "reports" / "taxonomy_batch_seq201_337_passed_urls.csv"

# 读取已有 CSV 数据
existing_rows = []
with open(csv_input, 'r', encoding='utf-8') as f:
    reader = csv.DictReader(f)
    for row in reader:
        existing_rows.append(row)

print(f"已读取 CSV: {len(existing_rows)} 行")

# 读取 JSON 数据
with open(json_input, 'r', encoding='utf-8') as f:
    json_data = json.load(f)

print(f"JSON 中有 {len(json_data['tasks'])} 个任务")

# 转换 JSON 数据为 CSV 行
new_rows = []
for task in json_data['tasks']:
    seq = task['seq']
    l2_zh = task['l2_zh']
    kw_zh = task['kw_zh']

    for url_index, url in enumerate(task['passed_urls'], start=1):
        new_rows.append({
            'seq': seq,
            'l2_zh': l2_zh,
            'kw_zh': kw_zh,
            'url_index': url_index,
            'url': url
        })

print(f"JSON 转换为 {len(new_rows)} 行")

# 合并数据
all_rows = existing_rows + new_rows
print(f"合并后总计: {len(all_rows)} 行")

# 写入新的 CSV
with open(csv_output, 'w', encoding='utf-8', newline='') as f:
    fieldnames = ['seq', 'l2_zh', 'kw_zh', 'url_index', 'url']
    writer = csv.DictWriter(f, fieldnames=fieldnames)

    writer.writeheader()
    writer.writerows(all_rows)

print(f"✓ 已导出全量表: {csv_output}")
print(f"  - 原 CSV (seq 201-332): {len(existing_rows)} 行")
print(f"  - 新 JSON (seq 333-337): {len(new_rows)} 行")
print(f"  - 全量合并: {len(all_rows)} 行")
