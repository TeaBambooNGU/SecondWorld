from __future__ import annotations

import inspect
from typing import Any, Dict, Iterable, List
from langchain_core.messages import BaseMessage


class LangChainClient:
    def __init__(self, api_config: Dict[str, Any], api_key: str) -> None:
        self.provider = self._normalize_provider(api_config.get("provider"))
        self.base_url = str(api_config.get("base_url", "")).rstrip("/")
        self.model = api_config.get("model")
        self.api_key = api_key
        self.timeout_sec = api_config.get("timeout_sec", 120)
        self.max_retries = api_config.get("max_retries", 3)

    @staticmethod
    def _normalize_provider(value: Any) -> str:
        if not value:
            return "deepseek"
        return str(value).strip().lower()

    def build_llm(
        self,
        *,
        temperature: float,
        top_p: float,
        streaming: bool,
        callbacks: list[Any] | None = None,
    ) -> Any:
        if self.provider == "deepseek":
            return self._build_deepseek_llm(
                temperature=temperature,
                top_p=top_p,
                streaming=streaming,
                callbacks=callbacks,
            )
        if self.provider == "openai":
            return self._build_openai_llm(
                temperature=temperature,
                top_p=top_p,
                streaming=streaming,
                callbacks=callbacks,
            )
        raise RuntimeError(f"不支持的模型类型: {self.provider}")

    def _build_deepseek_llm(
        self,
        *,
        temperature: float,
        top_p: float,
        streaming: bool,
        callbacks: list[Any] | None,
    ) -> Any:
        try:
            from langchain_deepseek import ChatDeepSeek
        except ImportError as exc:
            raise RuntimeError("缺少依赖: langchain-deepseek") from exc
        return self._build_llm_with_class(
            ChatDeepSeek,
            temperature=temperature,
            top_p=top_p,
            streaming=streaming,
            callbacks=callbacks,
        )

    def _build_openai_llm(
        self,
        *,
        temperature: float,
        top_p: float,
        streaming: bool,
        callbacks: list[Any] | None,
    ) -> Any:
        try:
            from langchain_openai import ChatOpenAI
        except ImportError as exc:
            raise RuntimeError("缺少依赖: langchain-openai") from exc
        return self._build_llm_with_class(
            ChatOpenAI,
            temperature=temperature,
            top_p=top_p,
            streaming=streaming,
            callbacks=callbacks,
        )

    def _build_llm_with_class(
        self,
        model_class,
        *,
        temperature: float,
        top_p: float,
        streaming: bool,
        callbacks: list[Any] | None,
    ) -> Any:
        kwargs = {
            "model": self.model,
            "api_key": self.api_key,
            "base_url": self.base_url or None,
            "timeout": self.timeout_sec,
            "max_retries": self.max_retries,
            "temperature": temperature,
            "top_p": top_p,
            "streaming": streaming,
            "callbacks": callbacks,
        }
        signature = inspect.signature(model_class)
        has_kwargs = any(
            param.kind == inspect.Parameter.VAR_KEYWORD
            for param in signature.parameters.values()
        )
        if has_kwargs:
            return model_class(**kwargs)
        filtered = {key: value for key, value in kwargs.items() if key in signature.parameters}
        return model_class(**filtered)


def format_messages(messages: Iterable[BaseMessage]) -> str:
    blocks: List[str] = []
    for message in messages:
        role = getattr(message, "type", "unknown")
        content = getattr(message, "content", "")
        blocks.append(f"[{role}]\n{content}")
    return "\n\n".join(blocks)
