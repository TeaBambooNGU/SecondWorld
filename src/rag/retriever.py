from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List

import chromadb
from llama_index.core import VectorStoreIndex
from llama_index.core.retrievers import QueryFusionRetriever
from llama_index.core.retrievers.fusion_retriever import FUSION_MODES
from llama_index.vector_stores.chroma import ChromaVectorStore


class NovelRAGRetriever:
    def __init__(
        self,
        *,
        vector_db_dir: str | Path,
        collection_name: str,
        embed_model,
    ) -> None:
        self.vector_db_dir = Path(vector_db_dir)
        self.collection_name = collection_name
        self.embed_model = embed_model

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
    ) -> List[Dict[str, Any]]:
        if not query.strip():
            return []
        if not self.vector_db_dir.exists():
            return []

        client = chromadb.PersistentClient(path=str(self.vector_db_dir))
        collection = client.get_or_create_collection(self.collection_name)
        if collection.count() == 0:
            return []

        top_k = max(1, int(top_k))
        fusion_num_queries = max(1, int(fusion_num_queries))

        vector_store = ChromaVectorStore(chroma_collection=collection)
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

        fusion = QueryFusionRetriever(
            retrievers=retrievers,
            similarity_top_k=top_k,
            num_queries=fusion_num_queries,
            mode=FUSION_MODES.RECIPROCAL_RANK,
            use_async=bool(fusion_use_async),
            verbose=False,
        )
        try:
            nodes = fusion.retrieve(query)
        except Exception:
            # 融合流程异常时退化为第一路检索，避免中断主流程。
            nodes = retrievers[0].retrieve(query)

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
