from pathlib import Path

from src.rag.indexer import NovelRAGIndexer, discover_txt_files, split_novel_text
from src.rag.service import build_rag_query, format_rag_references, resolve_rag_config


class _MemoryLogger:
    def __init__(self):
        self.messages = []

    def info(self, message: str):
        self.messages.append(message)


def test_resolve_rag_config_defaults():
    config = resolve_rag_config({"paths": {}})
    assert config["enabled"] is False
    assert config["embedding_model"] == "embedding-3"
    assert config["embedding_batch_size"] == 64
    assert config["source_dir"] == "data/rag/source_txt"


def test_build_rag_query_contains_plan_and_highlights():
    plan = {
        "title": "皇城夜雨",
        "goal": "主角试探使臣",
        "beats": ["对峙", "试探"],
        "conflicts": ["话术博弈"],
    }
    contributions = {
        "于皓": {
            "highlights": [
                {"content": "他翻了个白眼，嘟囔道。"},
                {"content": "指尖敲在桌沿，声音很轻。"},
            ]
        }
    }
    query = build_rag_query(plan, contributions)
    assert "皇城夜雨" in query
    assert "主角试探使臣" in query
    assert "翻了个白眼，嘟囔道" in query
    assert "动作+对话表达" in query


def test_format_rag_references():
    text = format_rag_references(
        [
            {
                "file_name": "示例.txt",
                "chunk_index": 2,
                "text": "翻了个白眼，嘟囔道。",
            }
        ]
    )
    assert "示例.txt#2" in text
    assert "翻了个白眼" in text


def test_split_novel_text_and_discover_files(tmp_path: Path):
    source_dir = tmp_path / "rag_source"
    source_dir.mkdir(parents=True, exist_ok=True)
    (source_dir / "a.txt").write_text("甲" * 200 + "\n\n" + "乙" * 200, encoding="utf-8")
    (source_dir / "b.md").write_text("ignore", encoding="utf-8")

    files = discover_txt_files(source_dir)
    assert [path.name for path in files] == ["a.txt"]

    chunks = split_novel_text(
        "甲" * 300,
        chunk_size_chars=120,
        chunk_overlap_chars=20,
        min_chunk_chars=40,
    )
    assert len(chunks) >= 2
    assert all(len(chunk) >= 40 for chunk in chunks)


def test_split_novel_text_filters_ps_and_prefers_chapter_paragraph_chunks():
    source = """
第一卷 笼中雀 第一章 惊蛰

    二月二，龙抬头。

    宋集薪翻了个白眼，嘟囔道：“你猜？”

    ps1: 公众号更新
    -------------

第一卷 笼中雀 第二章 开门

    陈平安推开门，缩了缩脖子。
"""
    chunks = split_novel_text(
        source,
        chunk_size_chars=120,
        chunk_overlap_chars=20,
        min_chunk_chars=20,
    )
    merged = "\n\n".join(chunks)
    assert "第一章 惊蛰" in merged
    assert "第二章 开门" in merged
    assert "ps1:" not in merged
    assert "-------------" not in merged
    assert "翻了个白眼，嘟囔道" in merged


def test_split_novel_text_filters_scraped_online_novel_noise():
    source = """
第1章 雨夜，刀，伞【新书求月票】
==========================================

第1章 雨夜，刀，伞【新书求月票】

楚槐序戴上【游戏头盔】，然后睁开眼睛。

（ps：新书起航，求月票~）

(本章完)

第2章 其实我是男模【新书求月票】
==========================================
"""
    chunks = split_novel_text(
        source,
        chunk_size_chars=120,
        chunk_overlap_chars=20,
        min_chunk_chars=20,
    )
    merged = "\n\n".join(chunks)
    # 章节标题保留一份，去掉抓取噪声行。
    assert merged.count("第1章 雨夜，刀，伞【新书求月票】") == 1
    assert "==========================================" not in merged
    assert "（ps：新书起航，求月票~）" not in merged
    assert "(本章完)" not in merged


def test_rag_indexer_progress_logs_when_no_txt_files(tmp_path: Path):
    source_dir = tmp_path / "empty_source"
    source_dir.mkdir(parents=True, exist_ok=True)
    logger = _MemoryLogger()
    indexer = NovelRAGIndexer(
        vector_db_dir=tmp_path / "chroma",
        collection_name="test_collection",
        embed_model=object(),
        logger=logger,
    )

    result = indexer.build_from_txt_dir(
        source_dir=source_dir,
        rebuild=True,
        chunk_size_chars=120,
        chunk_overlap_chars=20,
        min_chunk_chars=20,
    )

    assert result["indexed_files"] == 0
    assert any("开始构建索引" in message for message in logger.messages)
    assert any("扫描完成 txt_files=0" in message for message in logger.messages)
    assert any("未找到可入库的 txt 文件" in message for message in logger.messages)
