from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict

from .embeddings import LlamaIndexZhipuEmbedding
from .indexer import NovelRAGIndexer
from .retriever import NovelRAGRetriever


def resolve_rag_config(project_config: Dict[str, Any]) -> Dict[str, Any]:
    rag = project_config.get("rag") or {}
    paths = project_config.get("paths") or {}

    return {
        "enabled": bool(rag.get("enabled", False)),
        "embedding_model": str(rag.get("embedding_model") or "embedding-3"),
        "embedding_batch_size": max(1, min(int(rag.get("embedding_batch_size", 64)), 64)),
        "chunk_size_chars": max(int(rag.get("chunk_size_chars", 420)), 80),
        "chunk_overlap_chars": max(int(rag.get("chunk_overlap_chars", 80)), 0),
        "min_chunk_chars": max(int(rag.get("min_chunk_chars", 80)), 1),
        "retriever_top_k": max(int(rag.get("retriever_top_k", 6)), 1),
        "max_reference_chars": max(int(rag.get("max_reference_chars", 1600)), 0),
        "vector_db_dir": str(paths.get("rag_vector_db_dir") or "data/rag/chroma"),
        "source_dir": str(paths.get("rag_source_dir") or "data/rag/source_txt"),
        "collection": str(paths.get("rag_collection") or "novel_style_cases"),
    }


def build_rag_query(plan: Dict[str, Any], contributions: Dict[str, Any]) -> str:
    beats = plan.get("beats") if isinstance(plan.get("beats"), list) else []
    conflicts = plan.get("conflicts") if isinstance(plan.get("conflicts"), list) else []
    highlight_samples: list[str] = []
    for contribution in contributions.values():
        if not isinstance(contribution, dict):
            continue
        highlights = contribution.get("highlights")
        if not isinstance(highlights, list):
            continue
        for item in highlights:
            if isinstance(item, dict):
                text = str(item.get("content") or "").strip()
            else:
                text = str(item).strip()
            if text:
                highlight_samples.append(text)
            if len(highlight_samples) >= 8:
                break
        if len(highlight_samples) >= 8:
            break

    lines = [
        f"章节标题: {plan.get('title')}",
        f"章节目标: {plan.get('goal')}",
        f"节拍要点: {'；'.join(str(item) for item in beats[:6])}",
        f"核心冲突: {'；'.join(str(item) for item in conflicts[:6])}",
    ]
    if highlight_samples:
        lines.append("角色片段样本:")
        lines.extend(f"- {item}" for item in highlight_samples)
    lines.append("请检索更口语化、更有人味的玄幻网文写法样例，优先动作+对话表达。")
    return "\n".join(lines)


def format_rag_references(results: list[Dict[str, Any]]) -> str:
    if not results:
        return ""
    lines = []
    for idx, item in enumerate(results, start=1):
        file_name = str(item.get("file_name") or "unknown.txt")
        chunk_index = item.get("chunk_index")
        source = f"{file_name}#{chunk_index}" if chunk_index else file_name
        lines.append(f"[参考{idx}] 来源: {source}")
        lines.append(str(item.get("text") or "").strip())
        lines.append("")
    return "\n".join(lines).strip()


def _build_embed_model(rag_config: Dict[str, Any]) -> LlamaIndexZhipuEmbedding:
    if not os.getenv("ZHIPUAI_API_KEY"):
        raise RuntimeError("Missing API key in env var: ZHIPUAI_API_KEY")
    return LlamaIndexZhipuEmbedding(
        model_name=rag_config["embedding_model"],
        batch_size=rag_config["embedding_batch_size"],
    )


def build_rag_index(
    *,
    project_config: Dict[str, Any],
    source_dir: str | None,
    rebuild: bool,
    logger=None,
) -> Dict[str, Any]:
    rag_config = resolve_rag_config(project_config)
    resolved_source_dir = Path(source_dir) if source_dir else Path(rag_config["source_dir"])
    embed_model = _build_embed_model(rag_config)
    indexer = NovelRAGIndexer(
        vector_db_dir=rag_config["vector_db_dir"],
        collection_name=rag_config["collection"],
        embed_model=embed_model,
        logger=logger,
    )
    return indexer.build_from_txt_dir(
        source_dir=resolved_source_dir,
        rebuild=rebuild,
        chunk_size_chars=rag_config["chunk_size_chars"],
        chunk_overlap_chars=rag_config["chunk_overlap_chars"],
        min_chunk_chars=rag_config["min_chunk_chars"],
    )


def retrieve_rag_examples(
    *,
    project_config: Dict[str, Any],
    query: str,
) -> list[Dict[str, Any]]:
    rag_config = resolve_rag_config(project_config)
    if not rag_config["enabled"]:
        return []
    embed_model = _build_embed_model(rag_config)
    retriever = NovelRAGRetriever(
        vector_db_dir=rag_config["vector_db_dir"],
        collection_name=rag_config["collection"],
        embed_model=embed_model,
    )
    return retriever.retrieve(
        query=query,
        top_k=rag_config["retriever_top_k"],
        max_reference_chars=rag_config["max_reference_chars"],
    )
