from __future__ import annotations

from typing import List

from langchain_community.embeddings import ZhipuAIEmbeddings
from llama_index.core.base.embeddings.base import BaseEmbedding
from llama_index.core.bridge.pydantic import Field, PrivateAttr


class BatchedZhipuAIEmbeddings(ZhipuAIEmbeddings):
    batch_size: int = 64

    def embed_documents(self, texts):
        all_embeddings = []
        safe_batch_size = min(int(self.batch_size), 64)
        safe_batch_size = max(safe_batch_size, 1)
        for i in range(0, len(texts), safe_batch_size):
            batch = texts[i : i + safe_batch_size]
            all_embeddings.extend(super().embed_documents(batch))
        return all_embeddings


class LlamaIndexZhipuEmbedding(BaseEmbedding):
    batch_size: int = Field(default=64, ge=1, le=64)

    _embedder: BatchedZhipuAIEmbeddings = PrivateAttr()

    def __init__(
        self,
        *,
        model_name: str = "embedding-3",
        batch_size: int = 64,
        **kwargs,
    ) -> None:
        safe_batch_size = max(1, min(int(batch_size), 64))
        super().__init__(
            model_name=model_name,
            embed_batch_size=safe_batch_size,
            **kwargs,
        )
        self.batch_size = safe_batch_size
        self._embedder = BatchedZhipuAIEmbeddings(
            model=model_name,
            batch_size=safe_batch_size,
        )

    @classmethod
    def class_name(cls) -> str:
        return "zhipu_batched_embedding"

    def _get_query_embedding(self, query: str) -> List[float]:
        return self._embedder.embed_query(query)

    def _get_text_embedding(self, text: str) -> List[float]:
        vectors = self._embedder.embed_documents([text])
        return vectors[0]

    def _get_text_embeddings(self, texts: List[str]) -> List[List[float]]:
        if not texts:
            return []
        return self._embedder.embed_documents(texts)

    async def _aget_query_embedding(self, query: str) -> List[float]:
        return self._get_query_embedding(query)

    async def _aget_text_embedding(self, text: str) -> List[float]:
        return self._get_text_embedding(text)
