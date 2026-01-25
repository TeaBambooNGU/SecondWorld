from src.langchain_client import LangChainClient


def test_normalize_provider_defaults_to_deepseek():
    assert LangChainClient._normalize_provider(None) == "deepseek"
    assert LangChainClient._normalize_provider(" OpenAI ") == "openai"
