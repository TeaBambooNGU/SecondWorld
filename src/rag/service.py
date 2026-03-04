from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any, Callable, Dict

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
        "hyde_enabled": bool(rag.get("hyde_enabled", False)),
        "hyde_max_chars": max(int(rag.get("hyde_max_chars", 420)), 80),
        "hyde_style_profile": _resolve_hyde_style_profile(rag.get("hyde_style_profile")),
        "hyde_target_length": min(max(int(rag.get("hyde_target_length", 220)), 120), 600),
        "hyde_require_dialogue_ratio": _clamp_float(rag.get("hyde_require_dialogue_ratio"), default=0.3),
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


def _resolve_hyde_style_profile(raw_profile: Any) -> str:
    normalized = str(raw_profile or "balanced").strip().lower()
    aliases = {
        "balance": "balanced",
        "mixed": "balanced",
        "平衡": "balanced",
        "dialog": "dialogue",
        "对话": "dialogue",
        "action-heavy": "action",
        "动作": "action",
    }
    normalized = aliases.get(normalized, normalized)
    if normalized not in {"balanced", "dialogue", "action"}:
        return "balanced"
    return normalized


def _clamp_float(value: Any, *, default: float) -> float:
    if value in (None, ""):
        return default
    try:
        resolved = float(value)
    except (TypeError, ValueError):
        return default
    return min(max(resolved, 0.0), 1.0)


def build_rag_query(plan: Dict[str, Any], contributions: Dict[str, Any]) -> str:
    beats = plan.get("beats") if isinstance(plan.get("beats"), list) else []
    conflicts = plan.get("conflicts") if isinstance(plan.get("conflicts"), list) else []
    highlight_samples = _collect_highlight_samples(contributions, max_samples=8)

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


def build_hyde_context(plan: Dict[str, Any], contributions: Dict[str, Any]) -> str:
    conflicts = plan.get("conflicts") if isinstance(plan.get("conflicts"), list) else []
    compact_conflicts = [_compact_plan_item(item, max_chars=36) for item in conflicts]
    compact_conflicts = [item for item in compact_conflicts if item][:3]
    beats = plan.get("beats") if isinstance(plan.get("beats"), list) else []
    compact_beats = [_compact_plan_item(item, max_chars=30) for item in beats]
    compact_beats = [item for item in compact_beats if item][:3]

    role_names = [name for name in contributions.keys() if str(name).strip()]
    role_names = [str(name).strip() for name in role_names][:4]
    highlight_samples = [_compact_text(item, max_chars=38) for item in _collect_highlight_samples(contributions, max_samples=4)]
    highlight_samples = [item for item in highlight_samples if item]

    lines: list[str] = []
    if compact_conflicts:
        lines.append(f"冲突类型: {'；'.join(compact_conflicts)}")
    goal = _compact_text(plan.get("goal"), max_chars=60)
    if goal:
        lines.append(f"剧情目标: {goal}")
    if compact_beats:
        lines.append(f"关键推进: {'；'.join(compact_beats)}")
    if role_names:
        if len(role_names) >= 2:
            lines.append(f"人物关系: {'、'.join(role_names)}同场交锋")
        else:
            lines.append(f"人物关系: {role_names[0]}主导当前场景")
    if highlight_samples:
        lines.append("语气线索:")
        lines.extend(f"- {sample}" for sample in highlight_samples)
    return "\n".join(lines).strip()


def _collect_highlight_samples(contributions: Dict[str, Any], *, max_samples: int) -> list[str]:
    samples: list[str] = []
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
                samples.append(text)
            if len(samples) >= max_samples:
                return samples
    return samples


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


def build_hyde_query(
    *,
    query: str,
    llm: Any | None,
    max_chars: int,
    style_profile: str,
    target_length: int,
    dialogue_ratio: float,
    context_hint: str = "",
    logger: Callable[[str], None] | None = None,
) -> str:
    if not query.strip():
        return ""
    if llm is None:
        if logger:
            logger("RAG HyDE 跳过: 未传入生成LLM")
        return ""
    style_instruction = _build_hyde_style_instruction(style_profile)
    dialogue_percent = int(min(max(dialogue_ratio, 0.0), 1.0) * 100)
    prompt = (
        "你是中文小说写作检索助手。请根据检索需求，先写一段“可能出现在目标语料中的片段”，"
        "用于向量检索召回。只输出片段正文，不要解释、不要编号、不要 Markdown。\n"
        "要求：\n"
        f"1) 目标长度约 {target_length} 字（允许上下浮动 40 字）。\n"
        "2) 必须包含动作、对话或心理细节中的至少两类。\n"
        "3) 不要照抄需求原句。\n\n"
        f"风格档位: {style_profile}\n"
        f"风格要求: {style_instruction}\n"
        f"对白占比建议: 至少 {dialogue_percent}%（可通过短对白句实现）\n\n"
        f"章节上下文:\n{context_hint or '无'}\n\n"
        f"检索需求：\n{query}\n\n"
        "请直接输出片段："
    )
    try:
        raw = llm.invoke(prompt)
    except Exception as exc:
        if logger:
            logger(f"RAG HyDE 生成失败，降级为原始 query: {exc}")
        return ""
    text = _extract_llm_text(raw)
    cleaned = _sanitize_hyde_text(text, max_chars=max_chars)
    if not cleaned and logger:
        logger("RAG HyDE 生成为空，降级为原始 query")
    return cleaned


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
    llm: Any | None = None,
    hyde_context: str = "",
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
    per_query_budget = _resolve_per_query_budget(
        max_reference_chars=rag_config["max_reference_chars"],
        hyde_enabled=rag_config["hyde_enabled"],
    )
    base_results = retriever.retrieve(
        query=query,
        top_k=rag_config["retriever_top_k"],
        retrieval_modes=rag_config["retrieval_modes"],
        fusion_num_queries=rag_config["fusion_num_queries"],
        fusion_use_async=rag_config["fusion_use_async"],
        mmr_lambda=rag_config["mmr_lambda"],
        mmr_prefetch_factor=rag_config["mmr_prefetch_factor"],
        max_reference_chars=per_query_budget,
        logger=logger,
        llm=llm,
    )
    if not rag_config["hyde_enabled"]:
        return _merge_reference_results(
            [],
            base_results,
            max_reference_chars=rag_config["max_reference_chars"],
        )

    hyde_query = build_hyde_query(
        query=query,
        llm=llm,
        max_chars=rag_config["hyde_max_chars"],
        style_profile=rag_config["hyde_style_profile"],
        target_length=rag_config["hyde_target_length"],
        dialogue_ratio=rag_config["hyde_require_dialogue_ratio"],
        context_hint=hyde_context,
        logger=logger,
    )
    if not hyde_query:
        return _merge_reference_results(
            [],
            base_results,
            max_reference_chars=rag_config["max_reference_chars"],
        )
    if logger:
        logger(f"RAG HyDE 假设片段:\n{hyde_query}")

    hyde_results = retriever.retrieve(
        query=hyde_query,
        top_k=rag_config["retriever_top_k"],
        retrieval_modes=rag_config["retrieval_modes"],
        fusion_num_queries=rag_config["fusion_num_queries"],
        fusion_use_async=rag_config["fusion_use_async"],
        mmr_lambda=rag_config["mmr_lambda"],
        mmr_prefetch_factor=rag_config["mmr_prefetch_factor"],
        max_reference_chars=per_query_budget,
        logger=logger,
        llm=llm,
    )
    merged = _merge_reference_results(
        base_results,
        hyde_results,
        max_reference_chars=rag_config["max_reference_chars"],
    )
    if logger:
        logger(
            f"RAG HyDE 合并完成 base_hits={len(base_results)} hyde_hits={len(hyde_results)} merged_hits={len(merged)}"
        )
    return merged


def _resolve_per_query_budget(*, max_reference_chars: int, hyde_enabled: bool) -> int:
    if max_reference_chars <= 0:
        return 0
    if not hyde_enabled:
        return max_reference_chars
    return max_reference_chars * 2


def _merge_reference_results(
    primary: list[Dict[str, Any]],
    secondary: list[Dict[str, Any]],
    *,
    max_reference_chars: int,
) -> list[Dict[str, Any]]:
    merged: list[Dict[str, Any]] = []
    seen: set[str] = set()
    total_chars = 0
    budget = max(int(max_reference_chars), 0)
    for item in [*primary, *secondary]:
        text = str(item.get("text") or "").strip()
        if not text or text in seen:
            continue
        if budget > 0 and merged and total_chars + len(text) > budget:
            break
        merged.append(item)
        seen.add(text)
        total_chars += len(text)
    return merged


def _build_hyde_style_instruction(style_profile: str) -> str:
    profile = _resolve_hyde_style_profile(style_profile)
    if profile == "dialogue":
        return "高密度对白推进冲突，句子短促，穿插动作反应，避免大段说明。"
    if profile == "action":
        return "动作链清晰连贯，细节有触感，配少量对白点火情绪。"
    return "动作、对白、心理描写均衡，节奏紧凑，避免解释腔。"


def _extract_llm_text(raw: Any) -> str:
    if isinstance(raw, str):
        return raw
    content = getattr(raw, "content", None)
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
                continue
            if isinstance(item, dict):
                text = item.get("text")
                if isinstance(text, str):
                    parts.append(text)
                continue
            text = getattr(item, "text", None)
            if isinstance(text, str):
                parts.append(text)
        return "\n".join(part for part in parts if part.strip())
    return str(raw or "")


def _sanitize_hyde_text(text: str, *, max_chars: int) -> str:
    cleaned = str(text or "").strip()
    if cleaned.startswith("```") and cleaned.endswith("```"):
        lines = cleaned.splitlines()
        if len(lines) >= 3:
            cleaned = "\n".join(lines[1:-1]).strip()
        else:
            cleaned = cleaned.strip("`").strip()
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    cleaned = cleaned.strip()
    if len(cleaned) > max_chars:
        cleaned = _compact_text(cleaned, max_chars=max_chars)
    return cleaned
