from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, List

import chromadb
from llama_index.core import StorageContext, VectorStoreIndex
from llama_index.core.schema import TextNode
from llama_index.vector_stores.chroma import ChromaVectorStore

CHAPTER_TITLE_RE = re.compile(
    r"^第[一二三四五六七八九十百零〇0-9]+(?:卷|部|篇|章|回|节).*$"
)
POSTSCRIPT_RE = re.compile(r"^ps\d*[\s:：].*$", re.IGNORECASE)
SEPARATOR_RE = re.compile(r"^[-_=*—]{3,}$")
PAREN_POSTSCRIPT_RE = re.compile(r"^[（(]\s*ps\d*[\s:：].*[)）]\s*$", re.IGNORECASE)
CHAPTER_END_RE = re.compile(r"^[（(]?\s*本章完\s*[)）]?$")


def split_novel_text(
    text: str,
    *,
    chunk_size_chars: int,
    chunk_overlap_chars: int,
    min_chunk_chars: int,
) -> List[str]:
    cleaned = _clean_novel_text(text)
    if not cleaned:
        return []

    chunk_size_chars = max(int(chunk_size_chars), 80)
    chunk_overlap_chars = max(int(chunk_overlap_chars), 0)
    min_chunk_chars = max(int(min_chunk_chars), 1)

    chapter_blocks = _split_into_chapter_blocks(cleaned)
    chunks: List[str] = []
    for block in chapter_blocks:
        chunks.extend(
            _chunk_single_block(
                block,
                chunk_size_chars=chunk_size_chars,
                chunk_overlap_chars=chunk_overlap_chars,
                min_chunk_chars=min_chunk_chars,
            )
        )
    return _dedupe_chunks(chunks)


def discover_txt_files(source_dir: str | Path) -> List[Path]:
    base = Path(source_dir)
    if not base.exists():
        return []
    files = [path for path in base.rglob("*") if path.is_file() and path.suffix.lower() == ".txt"]
    files.sort()
    return files


def read_novel_text(path: str | Path) -> str:
    file_path = Path(path)
    for encoding in ("utf-8", "utf-8-sig", "gb18030"):
        try:
            return file_path.read_text(encoding=encoding)
        except UnicodeDecodeError:
            continue
    return file_path.read_text(encoding="utf-8", errors="ignore")


def _clean_novel_text(text: str) -> str:
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    kept_lines: List[str] = []
    previous_non_empty = ""
    for raw_line in normalized.split("\n"):
        line = raw_line.strip()
        if not line:
            kept_lines.append("")
            continue
        if POSTSCRIPT_RE.match(line):
            continue
        if PAREN_POSTSCRIPT_RE.match(line):
            continue
        if SEPARATOR_RE.match(line):
            continue
        if CHAPTER_END_RE.match(line):
            continue
        # 有些来源会把章节标题重复一遍（标题行 + 同标题行），这里做相邻去重。
        if _is_chapter_title(line) and line == previous_non_empty:
            continue
        kept_lines.append(line)
        previous_non_empty = line

    cleaned = "\n".join(kept_lines)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned).strip()
    return cleaned


def _is_chapter_title(line: str) -> bool:
    if not line:
        return False
    return bool(CHAPTER_TITLE_RE.match(line))


def _split_into_chapter_blocks(text: str) -> List[str]:
    blocks: List[str] = []
    current_lines: List[str] = []
    for raw_line in text.split("\n"):
        line = raw_line.strip()
        if _is_chapter_title(line):
            if current_lines:
                block = "\n".join(current_lines).strip()
                if block:
                    blocks.append(block)
            current_lines = [line]
            continue
        if line:
            current_lines.append(line)
        else:
            if current_lines and current_lines[-1] != "":
                current_lines.append("")
    if current_lines:
        block = "\n".join(current_lines).strip()
        if block:
            blocks.append(block)
    return blocks or [text]


def _chunk_single_block(
    text: str,
    *,
    chunk_size_chars: int,
    chunk_overlap_chars: int,
    min_chunk_chars: int,
) -> List[str]:
    paragraphs = [part.strip() for part in re.split(r"\n\s*\n", text) if part.strip()]
    if not paragraphs:
        return []

    chunks: List[str] = []
    current: List[str] = []
    current_len = 0

    for paragraph in paragraphs:
        if len(paragraph) > chunk_size_chars:
            if current:
                chunk = "\n\n".join(current).strip()
                if len(chunk) >= min_chunk_chars:
                    chunks.append(chunk)
                current = []
                current_len = 0
            chunks.extend(
                _split_long_paragraph(
                    paragraph,
                    chunk_size_chars=chunk_size_chars,
                    chunk_overlap_chars=chunk_overlap_chars,
                    min_chunk_chars=min_chunk_chars,
                )
            )
            continue

        addition = len(paragraph) + (2 if current else 0)
        if current and current_len + addition > chunk_size_chars:
            chunk = "\n\n".join(current).strip()
            if len(chunk) >= min_chunk_chars:
                chunks.append(chunk)

            if chunk_overlap_chars > 0:
                overlap_parts: List[str] = []
                overlap_len = 0
                for old in reversed(current):
                    overlap_parts.insert(0, old)
                    overlap_len += len(old) + 2
                    if overlap_len >= chunk_overlap_chars:
                        break
                current = overlap_parts
                current_len = len("\n\n".join(current))
            else:
                current = []
                current_len = 0

        current.append(paragraph)
        current_len = len("\n\n".join(current))

    if current:
        tail = "\n\n".join(current).strip()
        if len(tail) >= min_chunk_chars:
            chunks.append(tail)
        elif chunks:
            merged = f"{chunks[-1]}\n\n{tail}".strip()
            chunks[-1] = merged
    return chunks


def _dedupe_chunks(chunks: List[str]) -> List[str]:
    seen: set[str] = set()
    deduped: List[str] = []
    for chunk in chunks:
        text = chunk.strip()
        if not text:
            continue
        if text in seen:
            continue
        seen.add(text)
        deduped.append(text)
    return deduped


def _split_long_paragraph(
    paragraph: str,
    *,
    chunk_size_chars: int,
    chunk_overlap_chars: int,
    min_chunk_chars: int,
) -> List[str]:
    step = max(chunk_size_chars - chunk_overlap_chars, 1)
    slices: List[str] = []
    for start in range(0, len(paragraph), step):
        piece = paragraph[start : start + chunk_size_chars].strip()
        if not piece:
            continue
        if len(piece) < min_chunk_chars and slices:
            break
        slices.append(piece)
    return slices


class NovelRAGIndexer:
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
        logger=None,
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
        self.logger = logger
        if self.vector_store not in {"chroma", "milvus"}:
            raise RuntimeError(f"配置错误: 不支持的向量库类型 {self.vector_store}")

    def build_from_txt_dir(
        self,
        *,
        source_dir: str | Path,
        rebuild: bool,
        chunk_size_chars: int,
        chunk_overlap_chars: int,
        min_chunk_chars: int,
    ) -> Dict[str, Any]:
        self._log(
            f"[RAG] 开始构建索引 source_dir={source_dir} rebuild={rebuild} collection={self.collection_name} store={self.vector_store}"
        )
        txt_files = discover_txt_files(source_dir)
        self._log(f"[RAG] 扫描完成 txt_files={len(txt_files)}")
        if not txt_files:
            self._log("[RAG] 未找到可入库的 txt 文件，任务结束")
            result = {
                "indexed_files": 0,
                "indexed_chunks": 0,
                "vector_store": self.vector_store,
                "collection": self.collection_name,
                "source_dir": str(source_dir),
                "message": "未找到可入库的 txt 文件",
            }
            if self.vector_store == "chroma":
                result["vector_db_dir"] = str(self.vector_db_dir)
            else:
                result["milvus_uri"] = self.milvus_uri
                result["milvus_db_name"] = self.milvus_db_name
            return result

        nodes: List[TextNode] = []
        total_files = len(txt_files)
        for idx, file_path in enumerate(txt_files, start=1):
            self._log(f"[RAG] 处理文件 {idx}/{total_files}: {file_path.name}")
            text = read_novel_text(file_path)
            chunks = split_novel_text(
                text,
                chunk_size_chars=chunk_size_chars,
                chunk_overlap_chars=chunk_overlap_chars,
                min_chunk_chars=min_chunk_chars,
            )
            self._log(f"[RAG] 切分完成 {file_path.name} chunks={len(chunks)}")
            for index, chunk in enumerate(chunks, start=1):
                nodes.append(
                    TextNode(
                        text=chunk,
                        metadata={
                            "source_path": str(file_path),
                            "file_name": file_path.name,
                            "chunk_index": index,
                        },
                    )
                )
        self._log(f"[RAG] 语料切分汇总 files={total_files} chunks={len(nodes)}")

        vector_store, before_count = self._build_vector_store(rebuild=rebuild)
        storage_context = StorageContext.from_defaults(vector_store=vector_store)
        self._log(f"[RAG] 写入前向量条数 before_count={before_count}")
        if nodes:
            VectorStoreIndex(
                nodes=nodes,
                storage_context=storage_context,
                embed_model=self.embed_model,
                show_progress=True,
            )
        after_count = self._count_entities(vector_store)
        self._log(f"[RAG] 写入完成 after_count={after_count} 新增={max(after_count - before_count, 0)}")
        result = {
            "indexed_files": len(txt_files),
            "indexed_chunks": len(nodes),
            "vector_store": self.vector_store,
            "collection": self.collection_name,
            "source_dir": str(source_dir),
            "before_count": before_count,
            "after_count": after_count,
            "rebuild": rebuild,
        }
        if self.vector_store == "chroma":
            result["vector_db_dir"] = str(self.vector_db_dir)
        else:
            result["milvus_uri"] = self.milvus_uri
            result["milvus_db_name"] = self.milvus_db_name
        return result

    def _log(self, message: str) -> None:
        if self.logger:
            self.logger.info(message)

    def _build_vector_store(self, *, rebuild: bool):
        if self.vector_store == "chroma":
            self.vector_db_dir.mkdir(parents=True, exist_ok=True)
            client = chromadb.PersistentClient(path=str(self.vector_db_dir))
            if rebuild:
                try:
                    client.delete_collection(self.collection_name)
                    self._log(f"[RAG] 已重建集合 collection={self.collection_name}")
                except Exception:
                    self._log(f"[RAG] 集合不存在，跳过重建 collection={self.collection_name}")
            collection = client.get_or_create_collection(self.collection_name)
            return ChromaVectorStore(chroma_collection=collection), int(collection.count())

        try:
            from llama_index.vector_stores.milvus import MilvusVectorStore
        except ImportError as exc:
            raise RuntimeError("缺少依赖: 请安装 llama-index-vector-stores-milvus 与 pymilvus") from exc

        vector_store = MilvusVectorStore(
            uri=self.milvus_uri,
            token=self.milvus_token,
            db_name=self.milvus_db_name,
            collection_name=self.collection_name,
            overwrite=bool(rebuild),
            dim=self.milvus_dim,
            consistency_level=self.milvus_consistency_level,
            use_async_client=self.milvus_use_async_client,
        )
        if rebuild:
            self._log(f"[RAG] 已重建集合 collection={self.collection_name}")
        return vector_store, self._count_entities(vector_store)

    def _count_entities(self, vector_store: Any) -> int:
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
