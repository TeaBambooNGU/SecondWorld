from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List

import chromadb
from llama_index.core import VectorStoreIndex
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

        vector_store = ChromaVectorStore(chroma_collection=collection)
        index = VectorStoreIndex.from_vector_store(
            vector_store=vector_store,
            embed_model=self.embed_model,
        )
        retriever = index.as_retriever(similarity_top_k=max(1, int(top_k)))
        nodes = retriever.retrieve(query)

        results: List[Dict[str, Any]] = []
        seen: set[str] = set()
        total_chars = 0
        budget = max(int(max_reference_chars), 0)

        for item in nodes:
            node = getattr(item, "node", None)
            if node is None:
                continue
            text = getattr(node, "text", "") or ""
            text = text.strip()
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
