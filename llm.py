import os
import time

from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()


def resolve_config():
    if os.getenv("DEEPSEEK_API_KEY"):
        return (
            os.getenv("DEEPSEEK_API_KEY"),
            os.getenv("LLM_BASE_URL") or "https://api.deepseek.com",
            os.getenv("LLM_MODEL") or "deepseek-chat",
        )

    if os.getenv("DASHSCOPE_API_KEY"):
        return (
            os.getenv("DASHSCOPE_API_KEY"),
            os.getenv("LLM_BASE_URL")
            or "https://dashscope.aliyuncs.com/compatible-mode/v1",
            os.getenv("LLM_MODEL") or "qwen-plus",
        )

    if os.getenv("OPENAI_API_KEY"):
        return (
            os.getenv("OPENAI_API_KEY"),
            os.getenv("OPENAI_BASE_URL") or "https://api.openai.com/v1",
            os.getenv("MODEL") or "gpt-4o-mini",
        )

    if os.getenv("LLM_API_KEY"):
        base_url = os.getenv("LLM_BASE_URL")
        model = os.getenv("LLM_MODEL")
        if not base_url or not model:
            raise SystemExit(
                "使用 LLM_API_KEY 时，必须同时设置 LLM_BASE_URL 和 LLM_MODEL"
            )
        return os.getenv("LLM_API_KEY"), base_url, model

    raise SystemExit(
        "没有找到 API Key。请在 .env 中选择一种配置："
        "DEEPSEEK_API_KEY、DASHSCOPE_API_KEY、OPENAI_API_KEY 或 LLM_API_KEY。"
    )


API_KEY, BASE_URL, MODEL = resolve_config()
client = OpenAI(api_key=API_KEY, base_url=BASE_URL)


def chat(messages, tools=None, retries=3):
    last_error = None

    for attempt in range(retries):
        try:
            kwargs = {
                "model": MODEL,
                "messages": messages,
                "temperature": 0.2,
            }
            if tools:
                kwargs["tools"] = tools
                kwargs["tool_choice"] = "auto"

            response = client.chat.completions.create(**kwargs)
            content = response.choices[0].message.content
            if not content:
                raise RuntimeError("模型返回了空内容")
            return content
        except Exception as exc:
            last_error = exc
            if attempt < retries - 1:
                time.sleep(2 ** attempt)

    raise RuntimeError(f"LLM 调用失败，已重试 {retries} 次：{last_error}")