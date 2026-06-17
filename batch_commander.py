import sys
import os
import asyncio
import json
import gc
from datetime import datetime
from loguru import logger

# 确保能导入 ma4cd 目录下的模块
project_root = os.path.dirname(os.path.abspath(__file__))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

# 导入你刚刚写的 Pipeline
from main_workflow import MA4CDPipeline

# =============================================================================
# 🌍 战役配置矩阵 (请在这里补全你的 51 个国家/地区)
# =============================================================================
COUNTRIES = {
    # 示例：先放 5 个国家作为第一梯队先锋测试
    "United States": {"code": "us", "name_cn": "美国"},
    "United Kingdom": {"code": "gb", "name_cn": "英国"},
    "Sweden": {"code": "se", "name_cn": "瑞典"},
    "Japan": {"code": "jp", "name_cn": "日本"},
    "Brazil": {"code": "br", "name_cn": "巴西"}
    # ⬇️ 请在这里继续向下粘贴剩余的 46 个国家...
}

# 🔬 四大核心挖掘领域
DOMAINS = {
    "Science": "科学与基础研究 (Science & Fundamental Research)",
    "Medicine": "医学与公共卫生 (Medicine & Public Health)",
    "Economy": "宏观经济与金融 (Macroeconomics & Finance)",
    "Society": "人文与社会科学 (Humanities & Social Sciences)"
}

# 💾 断点续传记录文件
CHECKPOINT_FILE = os.path.join(project_root, "batch_checkpoint.json")

# =============================================================================
# 🛡️ 战役调度核心逻辑
# =============================================================================
class BatchCommander:
    def __init__(self):
        self.checkpoint = self._load_checkpoint()
        
    def _load_checkpoint(self) -> dict:
        if os.path.exists(CHECKPOINT_FILE):
            try:
                with open(CHECKPOINT_FILE, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                logger.error(f"⚠️ 读取断点文件失败，将重新开始: {e}")
        return {}

    def _save_checkpoint(self):
        with open(CHECKPOINT_FILE, "w", encoding="utf-8") as f:
            json.dump(self.checkpoint, f, indent=4, ensure_ascii=False)

    def _generate_mission_prompt(self, country_en: str, country_code: str, domain_en: str) -> str:
        """
        🧬 动态生成高度定制化的 Commander Prompt
        强调地理限制和领域聚焦，直接指挥系统挖掘 L1-L4 资产。
        """
        return (
            f"Please thoroughly discover and map high-value data assets related to '{domain_en}' "
            f"specifically located in, published by, or highly relevant to '{country_en}'. "
            f"Target country code constraint for Search: {country_code}. "
            "You must locate L1/L2 Hubs, L3 Digital Databases, and L4 Physical/Offline Archival clues. "
            "Exclude single papers and generic news."
        )

    async def execute_global_campaign(self):
        total_tasks = len(COUNTRIES) * len(DOMAINS)
        
        logger.info("="*60)
        logger.info(f"🌍 MA4CD 全球数据源挖掘战役启动 | 总任务量: {total_tasks}")
        logger.info("="*60)

        # 初始化你的业务管道 (只初始化一次，复用模型和 DB 连接)
        pipeline = MA4CDPipeline()
        
        task_counter = 0

        try:
            for country_en, info in COUNTRIES.items():
                country_code = info["code"]
                country_cn = info["name_cn"]

                for domain_en, domain_cn in DOMAINS.items():
                    task_counter += 1
                    mission_id = f"{country_code}_{domain_en.lower()}"

                    # 1. 断点续传：检查是否已经成功跑过
                    if mission_id in self.checkpoint and self.checkpoint[mission_id].get("status") == "success":
                        logger.success(f"⏩ [断点跳过] 任务已完成: {country_cn} - {domain_cn} ({task_counter}/{total_tasks})")
                        continue

                    prompt = self._generate_mission_prompt(country_en, country_code, domain_en)
                    
                    logger.info("-" * 50)
                    logger.info(f"▶️ [开始任务] {country_cn} ({country_code}) - {domain_cn} | 进度: {task_counter}/{total_tasks}")
                    logger.info(f"📝 Prompt: {prompt}")

                    try:
                        # ==========================================
                        # 🚀 核心：调用你的流水线单次执行方法
                        # ==========================================
                        results = await pipeline._run_pipeline_once(user_requirement=prompt)
                        
                        asset_count = len(results) if results else 0
                        
                        # 记录成功状态
                        self.checkpoint[mission_id] = {
                            "status": "success",
                            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                            "assets_found": asset_count
                        }
                        self._save_checkpoint()
                        
                        logger.success(f"✅ [任务达成] {country_cn} - {domain_cn} 入库资产: {asset_count} 条")

                        # 🛡️ 核心防御 1：强制 API 冷却 (Rate Limit 保护)
                        # 防止 OpenAI 报 429 错误，同时让 ChromaDB 的 SQLite 有时间落盘
                        cooling_time = 45 
                        logger.info(f"⏳ 强制冷却 {cooling_time} 秒，释放 API 额度与数据库锁...")
                        await asyncio.sleep(cooling_time)

                    except Exception as e:
                        logger.error(f"❌ [任务崩溃] {country_cn} - {domain_cn}: {e}")
                        import traceback
                        logger.error(traceback.format_exc())
                        
                        # 记录失败状态，但不中断整个循环
                        self.checkpoint[mission_id] = {
                            "status": "failed",
                            "error": str(e),
                            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                        }
                        self._save_checkpoint()
                        
                        # 🛡️ 核心防御 2：崩溃后深度冷却
                        logger.info("⏳ 遭遇异常，深度冷却 60 秒后继续下一任务...")
                        await asyncio.sleep(60)
                    
                    finally:
                        # 🛡️ 核心防御 3：内存强制回收
                        # 清理 Playwright/Miner 可能遗留的无效内存对象
                        gc.collect()

        except KeyboardInterrupt:
            logger.warning("\n🚨 接收到用户中断信号，正在保存断点并退出战役...")
        except Exception as global_e:
            logger.critical(f"💥 战役发生致命异常，被迫终止: {global_e}")
        finally:
            await pipeline.close()
            await asyncio.sleep(1)
            logger.info("🏁 战役指挥官已下线。请检查 batch_checkpoint.json 和 reports 目录。")

if __name__ == "__main__":
    commander = BatchCommander()
    asyncio.run(commander.execute_global_campaign())