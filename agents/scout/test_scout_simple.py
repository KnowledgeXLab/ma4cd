# 创建 Scout Agent
from llms.base import LLMClient
from agent import ScoutAgent

# 创建 LLM 客户端（需要根据实际实现）
class SimpleLLM(LLMClient):
    def invoke(self, system_prompt, user_prompt, **kwargs):
        return "模拟响应"

# 创建 Scout Agent
llm = SimpleLLM()
scout = ScoutAgent(
    llm_client=llm,
    output_dir="./artifacts/scout",
    max_concurrent_searches=2,
    search_max_steps=3
)

# 执行完整任务
result = scout.run(
    task="查找机器学习最新研究",
    country_code="us",
    task_type="research"
)

# 或者快速搜索
results = scout.quick_search(
    query="Python数据分析",
    country_code="cn",
    num_results=5
)