import time
from openai import OpenAI
from config import settings


class LLMClient:
    """统一 LLM 客户端，支持 Mimo 和 DeepSeek provider 切换。"""

    PROVIDER_CONFIG = {
        "mimo": {
            "base_url": settings.mimo_base_url,
            "api_key": settings.mimo_api_key,
            "model": settings.mimo_model,
        },
        "deepseek": {
            "base_url": settings.deepseek_base_url,
            "api_key": settings.deepseek_api_key,
            "model": settings.deepseek_model,
        },
    }

    def __init__(self, provider: str | None = None):
        self.provider = provider or settings.primary_provider
        if self.provider not in self.PROVIDER_CONFIG:
            raise ValueError(f"不支持的 provider: {self.provider}，可选: mimo / deepseek")

        cfg = self.PROVIDER_CONFIG[self.provider]
        self.model = cfg["model"]
        self.client = OpenAI(api_key=cfg["api_key"], base_url=cfg["base_url"])

    def _get_fallback_client(self) -> "LLMClient":
        """切换到备用 provider。"""
        fallback = "deepseek" if self.provider == "mimo" else "mimo"
        return LLMClient(fallback)

    def chat(
        self,
        messages: list[dict],
        temperature: float = 0.3,
        max_tokens: int = 4096,
        json_mode: bool = False,
    ) -> dict:
        """
        调用 LLM 聊天接口，带重试和自动降级。
        返回 {"content": str, "usage": {"prompt_tokens": int, "completion_tokens": int, "total_tokens": int}}
        失败时抛出 RuntimeError。
        """
        last_error = None
        providers_to_try = [self.provider] + (
            ["deepseek"] if self.provider == "mimo" else ["mimo"]
        )

        for attempt, prov in enumerate(providers_to_try):
            client = self if prov == self.provider else self._get_fallback_client()
            for retry in range(settings.max_retries):
                try:
                    kwargs = {
                        "model": client.model,
                        "messages": messages,
                        "temperature": temperature,
                        "max_tokens": max_tokens,
                    }
                    if json_mode:
                        kwargs["response_format"] = {"type": "json_object"}

                    resp = client.client.chat.completions.create(**kwargs)
                    usage = {
                        "prompt_tokens": resp.usage.prompt_tokens if resp.usage else 0,
                        "completion_tokens": resp.usage.completion_tokens if resp.usage else 0,
                        "total_tokens": resp.usage.total_tokens if resp.usage else 0,
                    }
                    return {"content": resp.choices[0].message.content, "usage": usage}

                except Exception as e:
                    last_error = e
                    if retry < settings.max_retries - 1:
                        time.sleep(2 ** retry)
                    else:
                        break  # 当前 provider 重试耗尽，尝试降级

        raise RuntimeError(f"LLM 调用失败，已尝试所有 provider: {last_error}")

    def chat_with_lint_context(
        self,
        code: str,
        lint_results: str,
        system_prompt: str,
        extra_context: str = "",
    ) -> dict:
        """发送代码 + lint 结果给 LLM 进行审查。返回 {"content": str, "usage": dict}。"""
        user_content = f"""## 待审查代码
```python
{code}
```

## 静态分析工具结果
{lint_results if lint_results else "无静态分析结果"}"""
        if extra_context:
            user_content += f"""

{extra_context}"""
        user_content += """

请按 JSON 格式输出审查结果。"""
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ]
        return self.chat(messages, temperature=0.3, max_tokens=4096, json_mode=True)


# 全局单例
def get_llm_client(provider: str | None = None) -> LLMClient:
    return LLMClient(provider)
