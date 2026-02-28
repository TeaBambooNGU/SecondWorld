from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict

import yaml
from dotenv import load_dotenv


def load_yaml(path: str | Path) -> Dict[str, Any]:
    return yaml.safe_load(Path(path).read_text(encoding="utf-8"))


def load_text(path: str | Path) -> str:
    return Path(path).read_text(encoding="utf-8")


def load_env() -> None:
    root_env = Path(".env")
    config_env = Path("config/.env")
    if root_env.exists():
        load_dotenv(root_env)
    elif config_env.exists():
        load_dotenv(config_env)
    _enable_langsmith_tracing()


def _enable_langsmith_tracing() -> None:
    api_key = os.getenv("LANGSMITH_API_KEY")
    tracing = os.getenv("LANGSMITH_TRACING")
    if api_key and not tracing:
        os.environ["LANGSMITH_TRACING"] = "true"


def _normalize_provider(value: Any) -> str:
    if not value:
        return "deepseek"
    normalized = str(value).strip().lower()
    if normalized == "chatgpt":
        return "openai"
    return normalized


def _first_non_empty(mapping: Dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if key not in mapping:
            continue
        value = mapping[key]
        if value is None:
            continue
        if isinstance(value, str) and not value.strip():
            continue
        return value
    return None


def _resolve_model_name(
    provider: str,
    api_block: Dict[str, Any],
    provider_config: Dict[str, Any],
) -> str | None:
    if provider == "anthropic":
        model_name = _first_non_empty(api_block, "model_name", "modelName")
        if model_name is None:
            model_name = _first_non_empty(provider_config, "model_name", "modelName")
        if model_name is None:
            models = provider_config.get("models")
            if isinstance(models, list) and models:
                first = models[0]
                if isinstance(first, dict):
                    model_name = _first_non_empty(first, "model_name", "modelName")
        if isinstance(model_name, str) and model_name.strip():
            return model_name.strip()
        return None

    model = _first_non_empty(api_block, "model")
    if model is None:
        model = _first_non_empty(provider_config, "model")
    if model is None:
        models = provider_config.get("models")
        if isinstance(models, list) and models:
            first = models[0]
            if isinstance(first, str) and first.strip():
                model = first.strip()
            elif isinstance(first, dict):
                model = _first_non_empty(first, "id", "model")
    if isinstance(model, str) and model.strip():
        return model.strip()
    return None


def _default_api_key_env(provider: str) -> str:
    defaults = {
        "deepseek": "DEEPSEEK_API_KEY",
        "openai": "OPENAI_API_KEY",
        "anthropic": "ANTHROPIC_API_KEY",
    }
    return defaults.get(provider, f"{provider.upper()}_API_KEY")


def resolve_api_config(project_config: Dict[str, Any]) -> Dict[str, Any]:
    api_block = project_config.get("api") or {}
    if not isinstance(api_block, dict):
        raise RuntimeError("配置错误: api 必须是对象")
    providers = project_config.get("providers") or {}
    if not isinstance(providers, dict):
        raise RuntimeError("配置错误: providers 必须是对象")

    raw_provider = api_block.get("provider")
    provider = _normalize_provider(raw_provider)
    has_explicit_provider = raw_provider is not None and str(raw_provider).strip() != ""
    provider_config: Dict[str, Any] = {}
    if providers:
        if provider in providers:
            provider_config = providers[provider] or {}
        elif not has_explicit_provider and len(providers) == 1:
            first_provider = next(iter(providers.keys()))
            provider = _normalize_provider(first_provider)
            provider_config = providers[first_provider] or {}
        elif not has_explicit_provider:
            available = ", ".join(sorted(str(item) for item in providers.keys()))
            raise RuntimeError(f"配置错误: 未指定有效 api.provider，可选值: {available}")
        if not isinstance(provider_config, dict):
            raise RuntimeError(f"配置错误: providers.{provider} 必须是对象")

    model = _resolve_model_name(provider, api_block, provider_config)
    if not model:
        if provider == "anthropic":
            raise RuntimeError(
                f"配置错误: 未找到 provider={provider} 的 model_name，请在 api.model_name 或 providers.{provider}.model_name 配置"
            )
        raise RuntimeError(f"配置错误: 未找到 provider={provider} 的模型 id，请在 api.model 或 providers.{provider}.model 配置")

    base_url = _first_non_empty(api_block, "base_url", "baseUrl")
    if base_url is None:
        base_url = _first_non_empty(provider_config, "base_url", "baseUrl")

    api_key_env = _first_non_empty(api_block, "api_key_env", "apiKeyEnv")
    if api_key_env is None:
        api_key_env = _first_non_empty(provider_config, "api_key_env", "apiKeyEnv")
    if api_key_env is None:
        api_key_env = _default_api_key_env(provider)

    timeout_sec = _first_non_empty(api_block, "timeout_sec", "timeoutSec")
    if timeout_sec is None:
        timeout_sec = _first_non_empty(provider_config, "timeout_sec", "timeoutSec")
    if timeout_sec is None:
        timeout_sec = 120

    max_retries = _first_non_empty(api_block, "max_retries", "maxRetries")
    if max_retries is None:
        max_retries = _first_non_empty(provider_config, "max_retries", "maxRetries")
    if max_retries is None:
        max_retries = 3

    stream = _first_non_empty(api_block, "stream")
    if stream is None:
        stream = _first_non_empty(provider_config, "stream")
    if stream is None:
        stream = False

    thinking = _first_non_empty(api_block, "thinking")
    if thinking is None:
        thinking = _first_non_empty(provider_config, "thinking")
    if thinking is not None and not isinstance(thinking, dict):
        raise RuntimeError("配置错误: thinking 必须是对象")

    api_type = _first_non_empty(provider_config, "api")

    return {
        "provider": provider,
        "model": model,
        "base_url": str(base_url or "").rstrip("/"),
        "api_key_env": str(api_key_env),
        "timeout_sec": int(timeout_sec),
        "max_retries": int(max_retries),
        "stream": bool(stream),
        "thinking": thinking,
        "api_type": api_type,
    }


def get_api_key(api_config: Dict[str, Any]) -> str:
    api_env = str(api_config.get("api_key_env", "")).strip()
    if not api_env:
        raise RuntimeError("配置错误: 缺少 api_key_env")
    api_key = os.getenv(api_env)
    if not api_key:
        raise RuntimeError(f"Missing API key in env var: {api_env}")
    return api_key
