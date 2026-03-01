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
        self.thinking = api_config.get("thinking")

    @staticmethod
    def _normalize_provider(value: Any) -> str:
        if not value:
            return "deepseek"
        normalized = str(value).strip().lower()
        if normalized == "chatgpt":
            return "openai"
        return normalized

    def build_llm(
        self,
        *,
        temperature: float | None,
        top_p: float | None,
        top_k: int | None = None,
        streaming: bool,
        callbacks: list[Any] | None = None,
    ) -> Any:
        if self.provider == "deepseek":
            return self._build_deepseek_llm(
                temperature=temperature,
                top_p=top_p,
                top_k=top_k,
                streaming=streaming,
                callbacks=callbacks,
            )
        if self.provider == "openai":
            return self._build_openai_llm(
                temperature=temperature,
                top_p=top_p,
                top_k=top_k,
                streaming=streaming,
                callbacks=callbacks,
            )
        if self.provider == "anthropic":
            return self._build_anthropic_llm(
                temperature=temperature,
                top_p=top_p,
                top_k=top_k,
                streaming=streaming,
                callbacks=callbacks,
            )
        raise RuntimeError(f"不支持的模型类型: {self.provider}")

    def _build_deepseek_llm(
        self,
        *,
        temperature: float | None,
        top_p: float | None,
        top_k: int | None,
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
            top_k=top_k,
            streaming=streaming,
            callbacks=callbacks,
        )

    def _build_openai_llm(
        self,
        *,
        temperature: float | None,
        top_p: float | None,
        top_k: int | None,
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
            top_k=top_k,
            streaming=streaming,
            callbacks=callbacks,
        )

    def _build_anthropic_llm(
        self,
        *,
        temperature: float | None,
        top_p: float | None,
        top_k: int | None,
        streaming: bool,
        callbacks: list[Any] | None,
    ) -> Any:
        try:
            from langchain_anthropic import ChatAnthropic
        except ImportError as exc:
            raise RuntimeError("缺少依赖: langchain-anthropic，请先执行 `uv add langchain-anthropic`") from exc
        return self._build_llm_with_class(
            ChatAnthropic,
            temperature=temperature,
            top_p=top_p,
            top_k=top_k,
            streaming=streaming,
            callbacks=callbacks,
            model_field="model_name",
            api_key_field="api_key",
            base_url_field="base_url",
        )

    def _build_llm_with_class(
        self,
        model_class,
        *,
        temperature: float | None,
        top_p: float | None,
        top_k: int | None,
        streaming: bool,
        callbacks: list[Any] | None,
        model_field: str = "model",
        api_key_field: str = "api_key",
        base_url_field: str = "base_url",
    ) -> Any:
        signature = inspect.signature(model_class)
        explicit_parameters = {
            key
            for key, param in signature.parameters.items()
            if param.kind not in (inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD)
        }
        has_var_kwargs = any(
            param.kind == inspect.Parameter.VAR_KEYWORD
            for param in signature.parameters.values()
        )
        allow_opaque_fields = has_var_kwargs and not explicit_parameters

        def is_supported(field_name: str) -> bool:
            if field_name in explicit_parameters:
                return True
            return allow_opaque_fields

        kwargs: Dict[str, Any] = {}
        if is_supported(model_field):
            kwargs[model_field] = self.model

        for key, value in (
            ("timeout", self.timeout_sec),
            ("max_retries", self.max_retries),
            ("temperature", temperature),
            ("top_p", top_p),
            ("thinking", self.thinking),
            ("streaming", streaming),
        ):
            if value is None:
                continue
            if is_supported(key):
                kwargs[key] = value

        if callbacks is not None and is_supported("callbacks"):
            kwargs["callbacks"] = callbacks

        if top_k is not None and is_supported("top_k"):
            kwargs["top_k"] = top_k

        if is_supported(api_key_field):
            kwargs[api_key_field] = self.api_key

        base_url_value = self.base_url or None
        if base_url_value and is_supported(base_url_field):
            kwargs[base_url_field] = base_url_value

        return model_class(**kwargs)


def format_messages(messages: Iterable[BaseMessage]) -> str:
    blocks: List[str] = []
    for message in messages:
        role = getattr(message, "type", "unknown")
        content = getattr(message, "content", "")
        blocks.append(f"[{role}]\n{content}")
    return "\n\n".join(blocks)
