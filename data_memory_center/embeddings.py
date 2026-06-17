import openai
from typing import List

class EmbeddingGenerator:
    def __init__(self, api_key: str):
        self.client = openai.OpenAI(api_key=api_key)
    
    async def generate_embedding(self, text: str) -> List[float]:
        """生成文本向量"""
        response = await self.client.embeddings.create(
            model="text-embedding-ada-002",
            input=text
        )
        return response.data[0].embedding
