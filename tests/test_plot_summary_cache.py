import json
from pathlib import Path

import src.langchain_pipeline as langchain_pipeline_module
from src.langchain_pipeline import LangChainPipeline


def _new_pipeline(tmp_path: Path) -> LangChainPipeline:
    pipeline = LangChainPipeline.__new__(LangChainPipeline)
    pipeline.logger = None
    pipeline.project = {
        "paths": {
            "state_path": str(tmp_path / "state.json"),
            "plot_summary_cache_path": str(tmp_path / "chapter_plot_summaries.json"),
        }
    }
    return pipeline


def test_build_chapter_context_reads_latest_three_full_then_summary(tmp_path):
    pipeline = _new_pipeline(tmp_path)
    chapters_dir = tmp_path / "chapters"
    chapters_dir.mkdir(parents=True, exist_ok=True)
    state = {"chapters": {}}
    outline = {"chapters": []}

    for index in range(1, 7):
        chapter_id = f"{index:04d}"
        outline["chapters"].append({"id": chapter_id, "title": f"标题{index}"})
        if index == 6:
            continue
        chapter_path = chapters_dir / f"{chapter_id}.md"
        chapter_path.write_text(f"正文{chapter_id}", encoding="utf-8")
        state["chapters"][chapter_id] = {
            "title": f"标题{index}",
            "file": str(chapter_path),
        }

    called_ids = []

    def fake_summary(*, chapter_id, **kwargs):
        called_ids.append(chapter_id)
        return f"摘要{chapter_id}"

    pipeline._get_or_create_plot_summary = fake_summary  # type: ignore[method-assign]

    context = pipeline._build_chapter_context(
        outline=outline,
        current_chapter_id="0006",
        state=state,
        generation={},
    )

    assert "【第0001章·标题1·剧情摘要】" in context
    assert "摘要0001" in context
    assert "【第0002章·标题2·剧情摘要】" in context
    assert "摘要0002" in context
    assert "【第0003章·标题3·全文】" in context
    assert "正文0003" in context
    assert "【第0004章·标题4·全文】" in context
    assert "正文0004" in context
    assert "【第0005章·标题5·全文】" in context
    assert "正文0005" in context
    assert called_ids == ["0001", "0002"]


def test_get_or_create_plot_summary_reuses_file_cache(tmp_path):
    pipeline = _new_pipeline(tmp_path)
    Path(pipeline.project["paths"]["state_path"]).write_text(
        json.dumps({"chapters": {}}),
        encoding="utf-8",
    )
    chapter_path = tmp_path / "0004.md"
    chapter_path.write_text("章节正文", encoding="utf-8")

    counter = {"calls": 0}

    def fake_summarize(*, chapter_id, chapter_title, chapter_text, generation):
        counter["calls"] += 1
        return f"生成摘要-{chapter_id}-{chapter_title}-{len(chapter_text)}"

    pipeline._summarize_plot_for_chapter = fake_summarize  # type: ignore[method-assign]

    summary1 = pipeline._get_or_create_plot_summary(
        chapter_id="0004",
        chapter_title="第四章",
        chapter_path=chapter_path,
        generation={},
    )
    summary2 = pipeline._get_or_create_plot_summary(
        chapter_id="0004",
        chapter_title="第四章",
        chapter_path=chapter_path,
        generation={},
    )

    cache_path = Path(pipeline.project["paths"]["plot_summary_cache_path"])
    cache_data = json.loads(cache_path.read_text(encoding="utf-8"))
    assert summary1 == summary2
    assert counter["calls"] == 1
    assert cache_data["0004"]["summary"] == summary1
    assert cache_data["0004"]["source"] == "llm_generated"


def test_get_or_create_plot_summary_ignores_state_summary_and_generates(tmp_path):
    pipeline = _new_pipeline(tmp_path)
    Path(pipeline.project["paths"]["state_path"]).write_text(
        json.dumps(
            {
                "chapters": {
                    "0002": {
                        "title": "第二章",
                        "summary": "这是旧状态里的摘要",
                    }
                }
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    chapter_path = tmp_path / "0002.md"
    chapter_path.write_text("章节正文", encoding="utf-8")

    counter = {"calls": 0}

    def fake_summarize(*, chapter_id, chapter_title, chapter_text, generation):
        counter["calls"] += 1
        return f"生成摘要-{chapter_id}-{chapter_title}-{len(chapter_text)}"

    pipeline._summarize_plot_for_chapter = fake_summarize  # type: ignore[method-assign]

    summary = pipeline._get_or_create_plot_summary(
        chapter_id="0002",
        chapter_title="第二章",
        chapter_path=chapter_path,
        generation={},
    )
    cache_path = Path(pipeline.project["paths"]["plot_summary_cache_path"])
    cache_data = json.loads(cache_path.read_text(encoding="utf-8"))

    assert counter["calls"] == 1
    assert summary == "生成摘要-0002-第二章-4"
    assert cache_data["0002"]["source"] == "llm_generated"


def test_build_rag_references_logs_query_and_results(tmp_path, monkeypatch):
    pipeline = _new_pipeline(tmp_path)
    logs: list[str] = []
    pipeline._log_info = logs.append  # type: ignore[method-assign]

    monkeypatch.setattr(langchain_pipeline_module, "resolve_rag_config", lambda _: {"enabled": True})
    monkeypatch.setattr(langchain_pipeline_module, "build_rag_query", lambda *_args, **_kwargs: "测试query")
    monkeypatch.setattr(
        langchain_pipeline_module,
        "retrieve_rag_examples",
        lambda *_args, **_kwargs: [{"text": "命中片段", "file_name": "a.txt", "chunk_index": 1}],
    )
    monkeypatch.setattr(langchain_pipeline_module, "format_rag_references", lambda _results: "参考片段内容")

    result = pipeline._build_rag_references(plan={}, contributions={})

    assert result == "参考片段内容"
    assert "RAG 检索 query:\n测试query" in logs
    assert "RAG 检索结果:\n参考片段内容" in logs
    assert "RAG 检索完成，命中片段数=1" in logs


def test_build_rag_references_logs_empty_results(tmp_path, monkeypatch):
    pipeline = _new_pipeline(tmp_path)
    logs: list[str] = []
    pipeline._log_info = logs.append  # type: ignore[method-assign]

    monkeypatch.setattr(langchain_pipeline_module, "resolve_rag_config", lambda _: {"enabled": True})
    monkeypatch.setattr(langchain_pipeline_module, "build_rag_query", lambda *_args, **_kwargs: "测试query")
    monkeypatch.setattr(langchain_pipeline_module, "retrieve_rag_examples", lambda *_args, **_kwargs: [])

    result = pipeline._build_rag_references(plan={}, contributions={})

    assert result == ""
    assert "RAG 检索 query:\n测试query" in logs
    assert "RAG 检索结果: []" in logs
    assert "RAG 检索无结果，跳过知识库参考" in logs
