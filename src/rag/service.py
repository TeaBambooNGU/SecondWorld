from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any, Dict

from .embeddings import LlamaIndexZhipuEmbedding
from .indexer import NovelRAGIndexer
from .retriever import NovelRAGRetriever


def resolve_rag_config(project_config: Dict[str, Any]) -> Dict[str, Any]:
    rag = project_config.get("rag") or {}
    paths = project_config.get("paths") or {}
    vector_store = _resolve_vector_store(rag.get("vector_store"))
    milvus = rag.get("milvus") if isinstance(rag.get("milvus"), dict) else {}
    retriever_top_k = max(int(rag.get("retriever_top_k", 6)), 1)
    mmr_lambda = float(rag.get("mmr_lambda", 0.65))
    mmr_prefetch_factor = float(rag.get("mmr_prefetch_factor", 4.0))
    fusion_num_queries = max(int(rag.get("fusion_num_queries", 1)), 1)

    return {
        "enabled": bool(rag.get("enabled", False)),
        "vector_store": vector_store,
        "embedding_model": str(rag.get("embedding_model") or "embedding-3"),
        "embedding_batch_size": max(1, min(int(rag.get("embedding_batch_size", 64)), 64)),
        "chunk_size_chars": max(int(rag.get("chunk_size_chars", 420)), 80),
        "chunk_overlap_chars": max(int(rag.get("chunk_overlap_chars", 80)), 0),
        "min_chunk_chars": max(int(rag.get("min_chunk_chars", 80)), 1),
        "retriever_top_k": retriever_top_k,
        "retrieval_modes": _resolve_retrieval_modes(rag.get("retrieval_modes")),
        "fusion_num_queries": fusion_num_queries,
        "fusion_use_async": bool(rag.get("fusion_use_async", False)),
        "mmr_lambda": min(max(mmr_lambda, 0.0), 1.0),
        "mmr_prefetch_factor": max(mmr_prefetch_factor, 1.0),
        "max_reference_chars": max(int(rag.get("max_reference_chars", 1600)), 0),
        "vector_db_dir": str(paths.get("rag_vector_db_dir") or "data/rag/chroma"),
        "source_dir": str(paths.get("rag_source_dir") or "data/rag/source_txt"),
        "collection": str(paths.get("rag_collection") or "novel_style_cases"),
        "milvus_uri": str(milvus.get("uri") or "http://127.0.0.1:19530"),
        "milvus_token": str(milvus.get("token") or ""),
        "milvus_db_name": str(milvus.get("db_name") or "default"),
        "milvus_consistency_level": str(milvus.get("consistency_level") or "Session"),
        "milvus_dim": _to_optional_int(milvus.get("dim")),
        "milvus_use_async_client": bool(milvus.get("use_async_client", False)),
    }


def _resolve_vector_store(value: Any) -> str:
    normalized = str(value or "chroma").strip().lower()
    aliases = {
        "local": "chroma",
        "chromadb": "chroma",
    }
    normalized = aliases.get(normalized, normalized)
    if normalized not in {"chroma", "milvus"}:
        raise RuntimeError(f"配置错误: rag.vector_store 仅支持 chroma 或 milvus，当前值={value}")
    return normalized


def _to_optional_int(value: Any) -> int | None:
    if value in (None, ""):
        return None
    resolved = int(value)
    if resolved <= 0:
        return None
    return resolved


def _resolve_retrieval_modes(raw_modes: Any) -> list[str]:
    if isinstance(raw_modes, str):
        modes = [part.strip() for part in raw_modes.split(",")]
    elif isinstance(raw_modes, list):
        modes = [str(item).strip() for item in raw_modes]
    else:
        modes = []
    normalized: list[str] = []
    seen: set[str] = set()
    for mode in modes:
        lowered = mode.lower()
        if lowered in {"similarity", "dense", "vector"}:
            lowered = "default"
        if lowered in {"default", "mmr"} and lowered not in seen:
            normalized.append(lowered)
            seen.add(lowered)
    if not normalized:
        return ["default", "mmr"]
    return normalized


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

    compact_beats = [_compact_plan_item(item, max_chars=48) for item in beats]
    compact_conflicts = [_compact_plan_item(item, max_chars=42) for item in conflicts]
    compact_beats = [item for item in compact_beats if item][:4]
    compact_conflicts = [item for item in compact_conflicts if item][:4]

    lines = [
        f"章节标题: {_compact_text(plan.get('title'), max_chars=32)}",
        f"章节目标: {_compact_text(plan.get('goal'), max_chars=120)}",
    ]
    if compact_beats:
        lines.append(f"关键节拍: {'；'.join(compact_beats)}")
    if compact_conflicts:
        lines.append(f"核心冲突: {'；'.join(compact_conflicts)}")
    if highlight_samples:
        lines.append("角色语言样本:")
        lines.extend(f"- {_compact_text(item, max_chars=56)}" for item in highlight_samples[:4])
    lines.append("检索目标: 口语化、动作+对话、情绪张力、短句节奏。")
    return "\n".join(lines)


def _compact_text(value: Any, *, max_chars: int) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    if len(text) <= max_chars:
        return text
    if max_chars <= 1:
        return text[:max_chars]
    return f"{text[: max_chars - 1].rstrip()}…"


def _compact_plan_item(item: Any, *, max_chars: int) -> str:
    if isinstance(item, str):
        return _compact_text(item, max_chars=max_chars)
    if not isinstance(item, dict):
        return _compact_text(item, max_chars=max_chars)
    sequence = _compact_text(item.get("sequence"), max_chars=12)
    content = _compact_text(item.get("content"), max_chars=max_chars)
    if sequence and content:
        return f"{sequence}:{content}"
    if content:
        return content
    summary = _compact_text(item.get("summary"), max_chars=max_chars)
    if summary:
        return summary
    return ""


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
        vector_store=rag_config["vector_store"],
        vector_db_dir=rag_config["vector_db_dir"],
        collection_name=rag_config["collection"],
        embed_model=embed_model,
        milvus_uri=rag_config["milvus_uri"],
        milvus_token=rag_config["milvus_token"],
        milvus_db_name=rag_config["milvus_db_name"],
        milvus_consistency_level=rag_config["milvus_consistency_level"],
        milvus_dim=rag_config["milvus_dim"],
        milvus_use_async_client=rag_config["milvus_use_async_client"],
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
    logger=None,
) -> list[Dict[str, Any]]:
    rag_config = resolve_rag_config(project_config)
    if not rag_config["enabled"]:
        return []
    embed_model = _build_embed_model(rag_config)
    retriever = NovelRAGRetriever(
        vector_store=rag_config["vector_store"],
        vector_db_dir=rag_config["vector_db_dir"],
        collection_name=rag_config["collection"],
        embed_model=embed_model,
        milvus_uri=rag_config["milvus_uri"],
        milvus_token=rag_config["milvus_token"],
        milvus_db_name=rag_config["milvus_db_name"],
        milvus_consistency_level=rag_config["milvus_consistency_level"],
        milvus_dim=rag_config["milvus_dim"],
        milvus_use_async_client=rag_config["milvus_use_async_client"],
    )
    return retriever.retrieve(
        query=query,
        top_k=rag_config["retriever_top_k"],
        retrieval_modes=rag_config["retrieval_modes"],
        fusion_num_queries=rag_config["fusion_num_queries"],
        fusion_use_async=rag_config["fusion_use_async"],
        mmr_lambda=rag_config["mmr_lambda"],
        mmr_prefetch_factor=rag_config["mmr_prefetch_factor"],
        max_reference_chars=rag_config["max_reference_chars"],
        logger=logger,
    )
