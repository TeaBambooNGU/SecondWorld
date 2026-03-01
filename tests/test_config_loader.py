import pytest

from src.config_loader import get_api_key, resolve_api_config


def test_resolve_api_config_keeps_legacy_api_block():
    project = {
        "api": {
            "provider": "deepseek",
            "base_url": "https://api.deepseek.com",
            "model": "deepseek-reasoner",
            "api_key_env": "DEEPSEEK_API_KEY",
            "timeout_sec": 150,
            "max_retries": 4,
            "stream": True,
        }
    }

    api = resolve_api_config(project)
    assert api["provider"] == "deepseek"
    assert api["base_url"] == "https://api.deepseek.com"
    assert api["model"] == "deepseek-reasoner"
    assert api["api_key_env"] == "DEEPSEEK_API_KEY"
    assert api["timeout_sec"] == 150
    assert api["max_retries"] == 4
    assert api["stream"] is True


def test_resolve_api_config_supports_provider_catalog_and_camel_case():
    project = {
        "providers": {
            "anthropic": {
                "baseUrl": "https://code.ppchat.vip",
                "api": "anthropic-messages",
                "model_name": "claude-opus-4-6",
                "thinking": {"type": "adaptive"},
                "models": [
                    {"model_name": "claude-opus-4-6", "name": "Claude Opus 4.6"},
                    {"model_name": "claude-haiku-4-5-20251001", "name": "Claude Sonnet 4.5"},
                ],
            }
        }
    }

    api = resolve_api_config(project)
    assert api["provider"] == "anthropic"
    assert api["base_url"] == "https://code.ppchat.vip"
    assert api["model"] == "claude-opus-4-6"
    assert api["api_key_env"] == "ANTHROPIC_API_KEY"
    assert api["thinking"] == {"type": "adaptive"}
    assert api["api_type"] == "anthropic-messages"


def test_resolve_api_config_prefers_legacy_api_when_provider_not_in_catalog():
    project = {
        "api": {
            "provider": "deepseek",
            "base_url": "https://api.deepseek.com",
            "model": "deepseek-reasoner",
            "api_key_env": "DEEPSEEK_API_KEY",
        },
        "providers": {
            "anthropic": {
                "baseUrl": "https://code.ppchat.vip",
                "model_name": "claude-opus-4-6",
                "models": [{"model_name": "claude-opus-4-6"}],
            }
        },
    }

    api = resolve_api_config(project)
    assert api["provider"] == "deepseek"
    assert api["base_url"] == "https://api.deepseek.com"
    assert api["model"] == "deepseek-reasoner"
    assert api["api_key_env"] == "DEEPSEEK_API_KEY"


def test_get_api_key_reads_env_only(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "proxy-key")
    api = {"api_key_env": "ANTHROPIC_API_KEY"}
    assert get_api_key(api) == "proxy-key"

    monkeypatch.delenv("ANTHROPIC_API_KEY")
    with pytest.raises(RuntimeError, match="Missing API key in env var: ANTHROPIC_API_KEY"):
        get_api_key(api)


def test_resolve_api_config_supports_openai_proxy_provider():
    project = {
        "api": {"provider": "openai"},
        "providers": {
            "openai": {
                "baseUrl": "https://code.ppchat.vip/v1",
                "api": "openai-completions",
                "model": "gpt-5.2-codex",
                "apiKeyEnv": "OPENAI_API_KEY",
                "models": [{"id": "gpt-5.2-codex"}],
            }
        },
    }

    api = resolve_api_config(project)
    assert api["provider"] == "openai"
    assert api["base_url"] == "https://code.ppchat.vip/v1"
    assert api["model"] == "gpt-5.2-codex"
    assert api["api_key_env"] == "OPENAI_API_KEY"
    assert api["api_type"] == "openai-completions"


def test_resolve_api_config_maps_chatgpt_to_openai():
    project = {
        "api": {"provider": "chatgpt"},
        "providers": {
            "openai": {
                "baseUrl": "https://code.ppchat.vip/v1",
                "model": "gpt-5.2-codex",
            }
        },
    }

    api = resolve_api_config(project)
    assert api["provider"] == "openai"
    assert api["model"] == "gpt-5.2-codex"
