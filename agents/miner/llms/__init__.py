# agents/miner/llms/__init__.py

from .miner_llm import MinerLLMClient, create_miner_llm

__all__ = ["MinerLLMClient", "create_miner_llm"]

_default_client = None

def get_miner_llm(force_new=False, **kwargs):
    global _default_client
    if _default_client is None or force_new:
        _default_client = create_miner_llm(**kwargs)
    return _default_client