"""
Scout Agent 专用的 LLM 客户端
基于 QueryEngine 设计，但更轻量
"""

import os
import sys
from datetime import datetime
from typing import Any, Dict, Optional, Generator, List
from loguru import logger
from utils.env import get_llm_api_key, get_llm_base_url, normalize_model_for_endpoint

# 添加 utils 目录到路径
current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(os.path.dirname(current_dir))
utils_dir = os.path.join(project_root, "utils")
if utils_dir not in sys.path:
    sys.path.append(utils_dir)

try:
    from retry_helper import with_retry, LLM_RETRY_CONFIG
except ImportError:
    # 备用的装饰器实现
    def with_retry(config=None):
        def decorator(func):
            return func
        return decorator
    
    LLM_RETRY_CONFIG = {
        "max_retries": 3,
        "delay": 1.0,
        "backoff": 2.0,
        "exceptions": (Exception,)
    }

try:
    from openai import OpenAI, OpenAIError, APIConnectionError, RateLimitError, Timeout
    HAS_OPENAI = True
except ImportError:
    HAS_OPENAI = False
    logger.warning("OpenAI 库未安装，请运行 `pip install openai`")


class LLMClient:
    """
    Scout Agent 专用 LLM 客户端
    专注于搜索任务，提供稳定的 API 调用
    """
    
    def __init__(
        self,
        api_key: str,
        model_name: str = "deepseek-chat",
        base_url: Optional[str] = None,
        timeout: float = 30.0,
        max_retries: int = 3
    ):
        """
        初始化 LLM 客户端
        
        Args:
            api_key: API 密钥
            model_name: 模型名称
            base_url: API 基础 URL（支持 OpenAI 兼容接口）
            timeout: 请求超时时间（秒）
            max_retries: 最大重试次数
        """
        if not api_key:
            raise ValueError("LLM API key is required.")
        if not model_name:
            raise ValueError("Model name is required.")
        
        self.api_key = api_key
        self.base_url = get_llm_base_url(base_url)
        resolved_model, fallback_reason = normalize_model_for_endpoint(model_name, self.base_url)
        self.model_name = resolved_model
        self.timeout = timeout
        self.max_retries = max_retries
        
        # 检查 OpenAI 库是否安装
        if not HAS_OPENAI:
            raise ImportError("OpenAI 库未安装，请运行 `pip install openai`")
        
        # 初始化客户端
        client_kwargs: Dict[str, Any] = {
            "api_key": api_key,
            "max_retries": 0,  # 重试由装饰器处理
        }
        if self.base_url:
            client_kwargs["base_url"] = self.base_url
        
        try:
            self.client = OpenAI(**client_kwargs)
            if fallback_reason:
                logger.warning(f"⚙️ [模型兼容] Scout 模型自动回退: {fallback_reason}")
            logger.info(f"LLMClient 初始化成功: {self.model_name} @ {self.base_url or 'OpenAI'}")
        except Exception as e:
            logger.error(f"LLMClient 初始化失败: {e}")
            raise
    
    def _build_messages(
        self,
        system_prompt: str = "",
        user_prompt: str = "",
        include_time: bool = True
    ) -> List[Dict[str, str]]:
        """
        构建消息列表
        
        Args:
            system_prompt: 系统提示词
            user_prompt: 用户提示词
            include_time: 是否包含时间信息
            
        Returns:
            消息列表
        """
        messages = []
        
        if system_prompt and system_prompt.strip():
            messages.append({
                "role": "system",
                "content": system_prompt.strip()
            })
        
        if include_time:
            current_time = datetime.now().strftime("%Y年%m月%d日 %H时%M分")
            time_prefix = f"当前时间是 {current_time}。"
            user_content = f"{time_prefix}\n{user_prompt}" if user_prompt else time_prefix
        else:
            user_content = user_prompt
        
        if user_content.strip():
            messages.append({
                "role": "user",
                "content": user_content.strip()
            })
        
        return messages
    
    @with_retry(LLM_RETRY_CONFIG)
    def invoke(
        self,
        system_prompt: str = "",
        user_prompt: str = "",
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        include_time: bool = True,
        **kwargs
    ) -> str:
        """
        同步调用 LLM
        
        Args:
            system_prompt: 系统提示词
            user_prompt: 用户提示词
            temperature: 温度参数
            max_tokens: 最大 token 数
            include_time: 是否包含时间信息
            **kwargs: 其他参数
            
        Returns:
            LLM 响应文本
        """
        try:
            # 构建消息
            messages = self._build_messages(system_prompt, user_prompt, include_time)
            
            # 准备请求参数
            request_params: Dict[str, Any] = {
                "model": self.model_name,
                "messages": messages,
                "temperature": temperature,
            }
            
            if max_tokens:
                request_params["max_tokens"] = max_tokens
            
            # 添加额外参数
            allowed_keys = {"top_p", "presence_penalty", "frequency_penalty", "stream"}
            for key, value in kwargs.items():
                if key in allowed_keys and value is not None:
                    request_params[key] = value
            
            # 执行请求
            response = self.client.chat.completions.create(
                **request_params,
                timeout=self.timeout
            )
            
            # 提取响应
            if response.choices and response.choices[0].message.content:
                content = response.choices[0].message.content.strip()
                logger.debug(f"LLM 响应长度: {len(content)} 字符")
                return content
            else:
                logger.warning("LLM 返回空响应")
                return ""
                
        except (APIConnectionError, RateLimitError, Timeout) as e:
            logger.error(f"LLM 请求网络错误: {e}")
            raise
        except OpenAIError as e:
            logger.error(f"OpenAI API 错误: {e}")
            raise
        except Exception as e:
            logger.error(f"LLM 调用未知错误: {e}")
            raise
    
    def stream_invoke(
        self,
        system_prompt: str = "",
        user_prompt: str = "",
        temperature: float = 0.7,
        include_time: bool = True,
        **kwargs
    ) -> Generator[str, None, None]:
        """
        流式调用 LLM
        
        Args:
            system_prompt: 系统提示词
            user_prompt: 用户提示词
            temperature: 温度参数
            include_time: 是否包含时间信息
            **kwargs: 其他参数
            
        Yields:
            响应文本块
        """
        try:
            # 构建消息
            messages = self._build_messages(system_prompt, user_prompt, include_time)
            
            # 准备请求参数（强制 stream=True）
            request_params: Dict[str, Any] = {
                "model": self.model_name,
                "messages": messages,
                "temperature": temperature,
                "stream": True,
            }
            
            # 添加额外参数
            allowed_keys = {"top_p", "presence_penalty", "frequency_penalty"}
            for key, value in kwargs.items():
                if key in allowed_keys and value is not None:
                    request_params[key] = value
            
            # 执行流式请求
            stream = self.client.chat.completions.create(
                **request_params,
                timeout=self.timeout
            )
            
            # 逐步返回响应
            for chunk in stream:
                if chunk.choices and chunk.choices[0].delta.content is not None:
                    yield chunk.choices[0].delta.content
                    
        except Exception as e:
            logger.error(f"流式调用失败: {str(e)}")
            raise
    
    @with_retry(LLM_RETRY_CONFIG)
    def stream_invoke_to_string(
        self,
        system_prompt: str = "",
        user_prompt: str = "",
        temperature: float = 0.7,
        include_time: bool = True,
        **kwargs
    ) -> str:
        """
        流式调用并拼接为完整字符串
        
        Args:
            system_prompt: 系统提示词
            user_prompt: 用户提示词
            temperature: 温度参数
            include_time: 是否包含时间信息
            **kwargs: 其他参数
            
        Returns:
            完整的响应字符串
        """
        try:
            # 收集所有块（以字节形式避免 UTF-8 截断问题）
            byte_chunks = []
            
            for chunk in self.stream_invoke(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                temperature=temperature,
                include_time=include_time,
                **kwargs
            ):
                byte_chunks.append(chunk.encode('utf-8'))
            
            # 拼接所有字节并解码
            if byte_chunks:
                full_content = b''.join(byte_chunks).decode('utf-8', errors='replace')
                logger.debug(f"流式响应总长度: {len(full_content)} 字符")
                return full_content
            else:
                return ""
                
        except Exception as e:
            logger.error(f"流式调用转字符串失败: {str(e)}")
            raise
    
    def invoke_json(
        self,
        system_prompt: str = "",
        user_prompt: str = "",
        temperature: float = 0.3,
        include_time: bool = True,
        **kwargs
    ) -> Dict[str, Any]:
        """
        调用 LLM 并强制返回 JSON 格式
        
        Args:
            system_prompt: 系统提示词
            user_prompt: 用户提示词
            temperature: 温度参数（通常较低以保证 JSON 稳定性）
            include_time: 是否包含时间信息
            **kwargs: 其他参数
            
        Returns:
            JSON 解析后的字典
        """
        try:
            # 修改系统提示词以确保 JSON 输出
            json_system_prompt = (
                f"{system_prompt}\n\n"
                "重要：你必须以有效的 JSON 格式输出。不要包含其他解释性文本。"
            )
            
            response = self.invoke(
                system_prompt=json_system_prompt,
                user_prompt=user_prompt,
                temperature=temperature,
                max_tokens=2000,
                include_time=include_time,
                **kwargs
            )
            
            # 尝试提取 JSON
            json_str = self._extract_json_from_response(response)
            
            import json as json_module
            return json_module.loads(json_str)
            
        except Exception as e:
            logger.error(f"JSON 调用失败: {e}")
            return {"error": str(e), "raw_response": response}
    
    def _extract_json_from_response(self, response: str) -> str:
        """
        从响应中提取 JSON 字符串
        
        Args:
            response: LLM 原始响应
            
        Returns:
            提取的 JSON 字符串
        """
        import json as json_module
        
        # 尝试直接解析
        try:
            json_module.loads(response)
            return response
        except:
            pass
        
        # 尝试提取 JSON 部分
        json_start = response.find('{')
        json_end = response.rfind('}') + 1
        
        if json_start != -1 and json_end > json_start:
            json_str = response[json_start:json_end]
            try:
                json_module.loads(json_str)
                return json_str
            except:
                pass
        
        # 如果都失败，返回包装后的 JSON
        return json_module.dumps({"content": response}, ensure_ascii=False)
    
    def get_model_info(self) -> Dict[str, Any]:
        """
        获取模型信息
        
        Returns:
            模型信息字典
        """
        return {
            "model": self.model_name,
            "api_base": self.base_url or "https://api.openai.com/v1",
            "timeout": self.timeout,
            "max_retries": self.max_retries
        }
    
    def test_connection(self) -> bool:
        """
        测试连接是否正常
        
        Returns:
            连接是否成功
        """
        try:
            # 发送一个简单的测试请求
            response = self.invoke(
                system_prompt="你是一个测试助手。",
                user_prompt="请回复 'OK'。",
                temperature=0.1,
                max_tokens=10
            )
            
            if response and "OK" in response.upper():
                logger.info("LLM 连接测试成功")
                return True
            else:
                logger.warning(f"LLM 连接测试返回异常: {response}")
                return False
                
        except Exception as e:
            logger.error(f"LLM 连接测试失败: {e}")
            return False


# 快速使用的工厂函数
def create_llm_client(
    api_key: Optional[str] = None,
    model_name: str = "deepseek-chat",
    base_url: Optional[str] = None
) -> LLMClient:
    """
    快速创建 LLM 客户端
    
    Args:
        api_key: API 密钥（默认从环境变量读取）
        model_name: 模型名称
        base_url: API 基础 URL
        
    Returns:
        LLMClient 实例
    """
    # 从环境变量获取 API key
    if api_key is None:
        api_key = get_llm_api_key()
    if base_url is None:
        base_url = get_llm_base_url()
    
    if not api_key:
        raise ValueError(
            "API key 未提供。请提供 api_key 参数或设置 OPENAI_API_KEY / MA4CD_LLM_API_KEY 环境变量"
        )
    
    return LLMClient(
        api_key=api_key,
        model_name=model_name,
        base_url=base_url
    )


# 测试代码
if __name__ == "__main__":
    # 测试客户端
    print("=== LLMClient 测试 ===")
    
    # 1. 从环境变量获取 API key
    api_key = get_llm_api_key()
    
    if not api_key:
        print("警告: 未设置可用 API key 环境变量，跳过真实测试")
        print("请设置环境变量: export OPENAI_API_KEY='your-key' 或 export MA4CD_LLM_API_KEY='your-key'")
        
        # 模拟测试
        class MockLLMClient:
            def invoke(self, **kwargs):
                return '{"test": "success"}'
        
        client = MockLLMClient()
        response = client.invoke(system_prompt="测试", user_prompt="你好")
        print(f"模拟响应: {response}")
        
    else:
        try:
            # 真实测试
            client = LLMClient(api_key=api_key, model_name="deepseek-chat")
            
            # 测试连接
            if client.test_connection():
                print("✓ 连接测试成功")
                
                # 测试普通调用
                response = client.invoke(
                    system_prompt="你是一个搜索规划助手。",
                    user_prompt="帮我规划'人工智能'的搜索任务",
                    temperature=0.3
                )
                print(f"✓ 普通调用成功，响应长度: {len(response)}")
                
                # 测试 JSON 调用
                json_response = client.invoke_json(
                    system_prompt="输出 JSON 格式的搜索规划",
                    user_prompt="人工智能",
                    temperature=0.3
                )
                print(f"✓ JSON 调用成功，响应: {json_response}")
                
            else:
                print("✗ 连接测试失败")
                
        except Exception as e:
            print(f"✗ 测试失败: {e}")
