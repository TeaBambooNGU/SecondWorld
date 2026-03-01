from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Dict, List

import chromadb
from llama_index.core import VectorStoreIndex
from llama_index.core.retrievers import QueryFusionRetriever
from llama_index.core.retrievers.fusion_retriever import FUSION_MODES
from llama_index.vector_stores.chroma import ChromaVectorStore


class NovelRAGRetriever:
    def __init__(
        self,
        *,
        vector_store: str,
        vector_db_dir: str | Path,
        collection_name: str,
        embed_model,
        milvus_uri: str | None = None,
        milvus_token: str = "",
        milvus_db_name: str = "default",
        milvus_consistency_level: str = "Session",
        milvus_dim: int | None = None,
        milvus_use_async_client: bool = False,
    ) -> None:
        self.vector_store = str(vector_store or "chroma").strip().lower()
        self.vector_db_dir = Path(vector_db_dir)
        self.collection_name = collection_name
        self.embed_model = embed_model
        self.milvus_uri = str(milvus_uri or "http://127.0.0.1:19530")
        self.milvus_token = milvus_token
        self.milvus_db_name = milvus_db_name
        self.milvus_consistency_level = milvus_consistency_level
        self.milvus_dim = milvus_dim
        self.milvus_use_async_client = bool(milvus_use_async_client)
        if self.vector_store not in {"chroma", "milvus"}:
            raise RuntimeError(f"配置错误: 不支持的向量库类型 {self.vector_store}")

    def retrieve(
        self,
        *,
        query: str,
        top_k: int,
        retrieval_modes: list[str],
        fusion_num_queries: int,
        fusion_use_async: bool,
        mmr_lambda: float,
        mmr_prefetch_factor: float,
        max_reference_chars: int,
        logger: Callable[[str], None] | None = None,
        llm: Any | None = None,
    ) -> List[Dict[str, Any]]:
        if not query.strip():
            return []

        vector_store = self._build_vector_store()
        if self._count_entities(vector_store) == 0:
            return []

        top_k = max(1, int(top_k))
        fusion_num_queries = max(1, int(fusion_num_queries))
        if fusion_num_queries > 1 and llm is None:
            if logger:
                logger("RAG Query 改写跳过: 未传入改写LLM，降级 fusion_num_queries=1")
            fusion_num_queries = 1

        index = VectorStoreIndex.from_vector_store(
            vector_store=vector_store,
            embed_model=self.embed_model,
        )
        retrievers = _build_route_retrievers(
            index=index,
            retrieval_modes=retrieval_modes,
            top_k=top_k,
            mmr_lambda=mmr_lambda,
            mmr_prefetch_factor=mmr_prefetch_factor,
        )
        if not retrievers:
            return []

        fusion = _LoggedQueryFusionRetriever(
            retrievers=retrievers,
            llm=llm,
            similarity_top_k=top_k,
            num_queries=fusion_num_queries,
            mode=FUSION_MODES.RECIPROCAL_RANK,
            use_async=bool(fusion_use_async),
            verbose=False,
        )
        try:
            nodes = fusion.retrieve(query)
        except Exception as exc:
            # 融合流程异常时退化为第一路检索，避免中断主流程。
            if logger:
                logger(f"RAG QueryFusion 检索失败，回退基础检索: {exc}")
            nodes = retrievers[0].retrieve(query)
        if logger:
            _log_generated_queries(logger, fusion.generated_queries)

        results: List[Dict[str, Any]] = []
        seen: set[str] = set()
        total_chars = 0
        budget = max(int(max_reference_chars), 0)

        for item in nodes:
            node = getattr(item, "node", None)
            if node is None:
                continue
            text = str(getattr(node, "text", "") or "").strip()
            if not text:
                continue
            if text in seen:
                continue
            if budget > 0 and results and total_chars + len(text) > budget:
                break
            metadata = getattr(node, "metadata", {}) or {}
            results.append(
                {
                    "text": text,
                    "score": getattr(item, "score", None),
                    "source_path": metadata.get("source_path"),
                    "file_name": metadata.get("file_name"),
                    "chunk_index": metadata.get("chunk_index"),
                }
            )
            seen.add(text)
            total_chars += len(text)
        return results

    def _build_vector_store(self):
        if self.vector_store == "chroma":
            if not self.vector_db_dir.exists():
                return None
            client = chromadb.PersistentClient(path=str(self.vector_db_dir))
            collection = client.get_or_create_collection(self.collection_name)
            return ChromaVectorStore(chroma_collection=collection)

        try:
            from llama_index.vector_stores.milvus import MilvusVectorStore
        except ImportError as exc:
            raise RuntimeError("缺少依赖: 请安装 llama-index-vector-stores-milvus 与 pymilvus") from exc

        return MilvusVectorStore(
            uri=self.milvus_uri,
            token=self.milvus_token,
            db_name=self.milvus_db_name,
            collection_name=self.collection_name,
            overwrite=False,
            dim=self.milvus_dim,
            consistency_level=self.milvus_consistency_level,
            use_async_client=self.milvus_use_async_client,
        )

    def _count_entities(self, vector_store: Any) -> int:
        if vector_store is None:
            return 0
        if self.vector_store == "chroma":
            chroma_collection = getattr(vector_store, "_collection", None)
            if chroma_collection is None:
                return 0
            try:
                return int(chroma_collection.count())
            except Exception:
                return 0

        client = getattr(vector_store, "client", None)
        if client is None:
            return 0
        try:
            stats = client.get_collection_stats(collection_name=self.collection_name)
        except Exception:
            return 0
        if not isinstance(stats, dict):
            return 0
        for key in ("row_count", "num_rows", "count"):
            value = stats.get(key)
            if value is None:
                continue
            try:
                return int(value)
            except (TypeError, ValueError):
                continue
        return 0


class _LoggedQueryFusionRetriever(QueryFusionRetriever):
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.generated_queries: list[str] = []

    def _get_queries(self, original_query: str):  # type: ignore[override]
        queries = super()._get_queries(original_query)
        self.generated_queries = [str(item.query_str or "").strip() for item in queries if str(item.query_str or "").strip()]
        return queries


def _log_generated_queries(logger: Callable[[str], None], generated_queries: list[str]) -> None:
    if not generated_queries:
        return
    lines = ["RAG Query 改写结果:"]
    lines.extend(f"{idx}. {query}" for idx, query in enumerate(generated_queries, start=1))
    logger("\n".join(lines))


def _build_route_retrievers(
    *,
    index: VectorStoreIndex,
    retrieval_modes: list[str],
    top_k: int,
    mmr_lambda: float,
    mmr_prefetch_factor: float,
) -> list[Any]:
    retrievers: list[Any] = []
    normalized_modes = _normalize_modes(retrieval_modes)
    if not normalized_modes:
        normalized_modes = ["default", "mmr"]

    for mode in normalized_modes:
        try:
            if mode == "mmr":
                retriever = index.as_retriever(
                    vector_store_query_mode="mmr",
                    similarity_top_k=top_k,
                    vector_store_kwargs=_build_mmr_vector_store_kwargs(
                        mmr_lambda=mmr_lambda,
                        mmr_prefetch_factor=mmr_prefetch_factor,
                    ),
                )
            else:
                retriever = index.as_retriever(
                    vector_store_query_mode="default",
                    similarity_top_k=top_k,
                )
        except Exception:
            continue
        retrievers.append(retriever)
    return retrievers


def _normalize_modes(modes: list[str]) -> list[str]:
    resolved: list[str] = []
    seen: set[str] = set()
    for raw in modes:
        mode = str(raw or "").strip().lower()
        if mode in {"similarity", "vector", "dense"}:
            mode = "default"
        if mode in {"default", "mmr"} and mode not in seen:
            resolved.append(mode)
            seen.add(mode)
    return resolved


def _build_mmr_vector_store_kwargs(*, mmr_lambda: float, mmr_prefetch_factor: float) -> Dict[str, Any]:
    return {
        "mmr_threshold": min(max(float(mmr_lambda), 0.0), 1.0),
        "mmr_prefetch_factor": max(float(mmr_prefetch_factor), 1.0),
    }
