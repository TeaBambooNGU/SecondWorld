from pathlib import Path

from src.rag.indexer import NovelRAGIndexer, discover_txt_files, split_novel_text
from src.rag.service import (
    build_hyde_context,
    build_hyde_query,
    build_rag_query,
    format_rag_references,
    resolve_rag_config,
    retrieve_rag_examples,
)


class _MemoryLogger:
    def __init__(self):
        self.messages = []

    def info(self, message: str):
        self.messages.append(message)


class _DummyAIMessage:
    def __init__(self, content):
        self.content = content


class _DummyLLM:
    def __init__(self, response):
        self.response = response
        self.prompts: list[str] = []

    def invoke(self, prompt: str):
        self.prompts.append(prompt)
        return self.response


def test_resolve_rag_config_defaults():
    config = resolve_rag_config({"paths": {}})
    assert config["enabled"] is False
    assert config["vector_store"] == "chroma"
    assert config["embedding_model"] == "embedding-3"
    assert config["embedding_batch_size"] == 64
    assert config["retriever_top_k"] == 6
    assert config["retrieval_modes"] == ["default", "mmr"]
    assert config["fusion_num_queries"] == 1
    assert config["fusion_use_async"] is False
    assert config["mmr_lambda"] == 0.65
    assert config["mmr_prefetch_factor"] == 4.0
    assert config["hyde_enabled"] is False
    assert config["hyde_max_chars"] == 420
    assert config["hyde_style_profile"] == "balanced"
    assert config["hyde_target_length"] == 220
    assert config["hyde_require_dialogue_ratio"] == 0.3
    assert config["source_dir"] == "data/rag/source_txt"
    assert config["milvus_uri"] == "http://127.0.0.1:19530"
    assert config["milvus_db_name"] == "default"
    assert config["milvus_dim"] is None


def test_resolve_rag_config_milvus_values():
    config = resolve_rag_config(
        {
            "rag": {
                "vector_store": "milvus",
                "milvus": {
                    "uri": "http://127.0.0.1:19530",
                    "token": "root:Milvus",
                    "db_name": "secondworld",
                    "consistency_level": "Strong",
                    "dim": 1024,
                    "use_async_client": True,
                },
            },
            "paths": {},
        }
    )
    assert config["vector_store"] == "milvus"
    assert config["milvus_uri"] == "http://127.0.0.1:19530"
    assert config["milvus_token"] == "root:Milvus"
    assert config["milvus_db_name"] == "secondworld"
    assert config["milvus_consistency_level"] == "Strong"
    assert config["milvus_dim"] == 1024
    assert config["milvus_use_async_client"] is True


def test_resolve_rag_config_fusion_num_queries_min_one():
    config = resolve_rag_config(
        {
            "rag": {
                "fusion_num_queries": 0,
            },
            "paths": {},
        }
    )
    assert config["fusion_num_queries"] == 1


def test_resolve_rag_config_modes_fallback_to_default_and_mmr():
    config = resolve_rag_config(
        {
            "rag": {
                "retrieval_modes": ["unknown", "dense", "mmr", "mmr"],
            },
            "paths": {},
        }
    )
    assert config["retrieval_modes"] == ["default", "mmr"]


def test_resolve_rag_config_hyde_min_chars():
    config = resolve_rag_config(
        {
            "rag": {
                "hyde_enabled": True,
                "hyde_max_chars": 30,
                "hyde_style_profile": "动作",
                "hyde_target_length": 900,
                "hyde_require_dialogue_ratio": 2.0,
            },
            "paths": {},
        }
    )
    assert config["hyde_enabled"] is True
    assert config["hyde_max_chars"] == 80
    assert config["hyde_style_profile"] == "action"
    assert config["hyde_target_length"] == 600
    assert config["hyde_require_dialogue_ratio"] == 1.0


def test_build_rag_query_contains_plan_and_highlights():
    plan = {
        "title": "皇城夜雨",
        "goal": "主角试探使臣",
        "beats": [
            {
                "sequence": "开场场面",
                "content": "于皓在雨夜里被带去看账，情绪紧绷。",
                "detail_anchors": ["青砖", "雨声"],
            },
            "试探",
        ],
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
    assert "动作+对话" in query
    assert "detail_anchors" not in query


def test_build_hyde_query_strips_fence_and_clamps_length():
    llm = _DummyLLM(_DummyAIMessage("```text\n" + "甲" * 120 + "\n```"))
    hyde_query = build_hyde_query(
        query="章节目标：对峙与试探",
        llm=llm,
        max_chars=90,
        style_profile="dialogue",
        target_length=200,
        dialogue_ratio=0.4,
        context_hint="冲突类型: 试探博弈",
    )
    assert "```" not in hyde_query
    assert len(hyde_query) <= 90
    assert llm.prompts
    assert "风格档位: dialogue" in llm.prompts[0]
    assert "冲突类型: 试探博弈" in llm.prompts[0]


def test_build_hyde_context_contains_conflict_relation_and_tone():
    plan = {
        "goal": "潜入后试探底线",
        "conflicts": ["身份暴露风险", "话术博弈"],
        "beats": [{"content": "雨夜对峙"}, "压低声线探口风"],
    }
    contributions = {
        "于皓": {"highlights": [{"content": "他笑了笑，敲了两下桌面。"}]},
        "柳七": {"highlights": [{"content": "“你想问什么？”柳七挑眉。"}]},
    }
    context = build_hyde_context(plan, contributions)
    assert "冲突类型:" in context
    assert "人物关系: 于皓、柳七同场交锋" in context
    assert "语气线索:" in context


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


def test_retrieve_rag_examples_merges_hyde_results(monkeypatch):
    class _DummyRetriever:
        calls: list[str] = []

        def __init__(self, **_kwargs):
            pass

        def retrieve(self, **kwargs):
            query = kwargs["query"]
            self.calls.append(query)
            if len(self.calls) == 1:
                return [{"text": "主检索片段", "file_name": "a.txt", "chunk_index": 1}]
            return [{"text": "HyDE检索片段", "file_name": "b.txt", "chunk_index": 2}]

    monkeypatch.setattr("src.rag.service._build_embed_model", lambda _config: object())
    monkeypatch.setattr("src.rag.service.NovelRAGRetriever", _DummyRetriever)
    llm = _DummyLLM("他压低声音笑了一下，手指轻轻敲着桌沿。")

    results = retrieve_rag_examples(
        project_config={"rag": {"enabled": True, "hyde_enabled": True, "max_reference_chars": 300}, "paths": {}},
        query="章节目标：对话博弈，语气克制",
        llm=llm,
        hyde_context="冲突类型: 试探",
    )
    assert len(results) == 2
    assert results[0]["text"] == "主检索片段"
    assert results[1]["text"] == "HyDE检索片段"


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
        vector_store="chroma",
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
