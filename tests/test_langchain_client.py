from src.langchain_client import LangChainClient


def test_normalize_provider_defaults_to_deepseek():
    assert LangChainClient._normalize_provider(None) == "deepseek"
    assert LangChainClient._normalize_provider(" OpenAI ") == "openai"
    assert LangChainClient._normalize_provider("chatgpt") == "openai"
    assert LangChainClient._normalize_provider("Anthropic") == "anthropic"


def test_build_llm_with_class_uses_base_url_and_api_key():
    class DummyModel:
        def __init__(
            self,
            *,
            model,
            api_key,
            base_url,
            timeout,
            max_retries,
            temperature,
            top_p,
            streaming,
            callbacks=None,
        ):
            self.model = model
            self.api_key = api_key
            self.base_url = base_url
            self.timeout = timeout
            self.max_retries = max_retries
            self.temperature = temperature
            self.top_p = top_p
            self.streaming = streaming
            self.callbacks = callbacks

    client = LangChainClient(
        {
            "provider": "openai",
            "base_url": "https://example.com",
            "model": "gpt-test",
            "timeout_sec": 30,
            "max_retries": 5,
        },
        api_key="secret",
    )

    llm = client._build_llm_with_class(
        DummyModel,
        temperature=0.3,
        top_p=0.8,
        top_k=None,
        streaming=False,
        callbacks=["cb"],
    )

    assert llm.model == "gpt-test"
    assert llm.api_key == "secret"
    assert llm.base_url == "https://example.com"
    assert llm.timeout == 30
    assert llm.max_retries == 5
    assert llm.temperature == 0.3
    assert llm.top_p == 0.8
    assert llm.streaming is False
    assert llm.callbacks == ["cb"]


def test_build_llm_with_class_supports_anthropic_model_name_and_thinking():
    class DummyAnthropicModel:
        def __init__(
            self,
            *,
            model_name,
            api_key,
            base_url,
            timeout,
            max_retries,
            temperature,
            top_p,
            thinking,
            streaming,
        ):
            self.model_name = model_name
            self.api_key = api_key
            self.base_url = base_url
            self.timeout = timeout
            self.max_retries = max_retries
            self.temperature = temperature
            self.top_p = top_p
            self.thinking = thinking
            self.streaming = streaming

    client = LangChainClient(
        {
            "provider": "anthropic",
            "base_url": "https://code.ppchat.vip",
            "model": "claude-opus-4-6",
            "timeout_sec": 45,
            "max_retries": 2,
            "thinking": {"type": "adaptive"},
        },
        api_key="proxy-key",
    )

    llm = client._build_llm_with_class(
        DummyAnthropicModel,
        temperature=0.2,
        top_p=0.9,
        top_k=20,
        streaming=True,
        callbacks=None,
        model_field="model_name",
        api_key_field="api_key",
        base_url_field="base_url",
    )

    assert llm.model_name == "claude-opus-4-6"
    assert llm.api_key == "proxy-key"
    assert llm.base_url == "https://code.ppchat.vip"
    assert llm.timeout == 45
    assert llm.max_retries == 2
    assert llm.temperature == 0.2
    assert llm.top_p == 0.9
    assert llm.thinking == {"type": "adaptive"}
    assert llm.streaming is True


def test_build_llm_with_class_omits_sampling_params_when_none():
    class DummyModel:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

    client = LangChainClient(
        {
            "provider": "openai",
            "base_url": "https://example.com",
            "model": "gpt-test",
        },
        api_key="secret",
    )

    llm = client._build_llm_with_class(
        DummyModel,
        temperature=None,
        top_p=None,
        top_k=None,
        streaming=False,
        callbacks=None,
    )

    assert llm.kwargs["model"] == "gpt-test"
    assert llm.kwargs["api_key"] == "secret"
    assert llm.kwargs["base_url"] == "https://example.com"
    assert "temperature" not in llm.kwargs
    assert "top_p" not in llm.kwargs
    assert "top_k" not in llm.kwargs
