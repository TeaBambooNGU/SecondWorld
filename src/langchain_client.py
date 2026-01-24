from __future__ import annotations

from typing import Any, Dict, Iterable, List

from langchain_openai import ChatOpenAI
from langchain_core.messages import BaseMessage


class LangChainClient:
    def __init__(self, api_config: Dict[str, Any], api_key: str) -> None:
        self.base_url = str(api_config.get("base_url", "")).rstrip("/")
        self.model = api_config.get("model")
        self.api_key = api_key
        self.timeout_sec = api_config.get("timeout_sec", 120)
        self.max_retries = api_config.get("max_retries", 3)

    def build_llm(
        self,
        *,
        temperature: float,
        top_p: float,
        streaming: bool,
        callbacks: list[Any] | None = None,
    ) -> ChatOpenAI:
        return ChatOpenAI(
            model=self.model,
            api_key=self.api_key,
            base_url=self.base_url,
            timeout=self.timeout_sec,
            max_retries=self.max_retries,
            temperature=temperature,
            top_p=top_p,
            streaming=streaming,
            callbacks=callbacks,
        )


def format_messages(messages: Iterable[BaseMessage]) -> str:
    blocks: List[str] = []
    for message in messages:
        role = getattr(message, "type", "unknown")
        content = getattr(message, "content", "")
        blocks.append(f"[{role}]\n{content}")
    return "\n\n".join(blocks)
