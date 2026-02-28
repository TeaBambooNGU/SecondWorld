import src.rag.retriever as retriever_module


class _DummyRetriever:
    def retrieve(self, _query):
        return []


class _DummyIndex:
    def __init__(self):
        self.calls = []

    def as_retriever(self, **kwargs):
        self.calls.append(kwargs)
        return _DummyRetriever()


def test_build_mmr_vector_store_kwargs_clamps_values():
    kwargs = retriever_module._build_mmr_vector_store_kwargs(
        mmr_lambda=2.0,
        mmr_prefetch_factor=0.3,
    )
    assert kwargs["mmr_threshold"] == 1.0
    assert kwargs["mmr_prefetch_factor"] == 1.0


def test_normalize_modes_alias_and_deduplicate():
    modes = retriever_module._normalize_modes(["dense", "mmr", "MMR", "unknown"])
    assert modes == ["default", "mmr"]


def test_build_route_retrievers_builds_default_and_mmr():
    index = _DummyIndex()
    retrievers = retriever_module._build_route_retrievers(
        index=index,
        retrieval_modes=["default", "mmr"],
        top_k=6,
        mmr_lambda=0.65,
        mmr_prefetch_factor=4.0,
    )

    assert len(retrievers) == 2
    assert index.calls[0]["vector_store_query_mode"] == "default"
    assert index.calls[0]["similarity_top_k"] == 6
    assert index.calls[1]["vector_store_query_mode"] == "mmr"
    assert index.calls[1]["similarity_top_k"] == 6
    assert index.calls[1]["vector_store_kwargs"]["mmr_threshold"] == 0.65
