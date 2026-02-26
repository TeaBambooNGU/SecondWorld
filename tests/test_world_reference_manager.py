import json
from pathlib import Path

from src.validators import (
    validate_world_material_selection,
    validate_world_material_selection_batch,
)
from src.world_reference_manager import WorldReferenceManager


def test_world_reference_manager_builds_cache_pack_with_batch_selector(tmp_path: Path):
    source_dir = tmp_path / "materials"
    cache_dir = tmp_path / "cache"
    source_dir.mkdir()

    file_a = source_dir / "世界观修炼体系.md"
    file_b = source_dir / "家族设定.md"
    file_a.write_text("修炼体系\n境界一\n境界二", encoding="utf-8")
    file_b.write_text("家族关系\n这一段是关键设定", encoding="utf-8")

    def selector(payload):
        decisions = []
        for material in payload["materials"]:
            if material["material_name"] == "世界观修炼体系.md":
                decisions.append(
                    {
                        "material_name": material["material_name"],
                        "use": True,
                        "mode": "full",
                        "selected_text": "",
                        "reason": "整篇相关",
                    }
                )
            else:
                decisions.append(
                    {
                        "material_name": material["material_name"],
                        "use": True,
                        "mode": "excerpt",
                        "selected_text": "这一段是关键设定",
                        "reason": "只需要核心片段",
                    }
                )
        return {"decisions": decisions}

    manager = WorldReferenceManager(materials_dir=source_dir, cache_root=cache_dir)
    pack = manager.build_reference_pack(
        chapter_id="0001",
        chapter={"id": "0001", "title": "测试章节"},
        plan={"goal": "涉及修炼与家族", "beats": ["修炼", "家族"]},
        selector=selector,
        budget_chars=2000,
        selector_batch_chars=10000,
    )

    assert len(pack["entries"]) == 2
    assert "世界观修炼体系" in pack["prompt_context"]

    manifest_path = Path(pack["manifest_path"])
    assert manifest_path.exists()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["chapter_id"] == "0001"
    assert len(manifest["entries"]) == 2


def test_world_reference_manager_splits_batches_when_content_is_large(tmp_path: Path):
    source_dir = tmp_path / "materials"
    cache_dir = tmp_path / "cache"
    source_dir.mkdir()

    for idx in range(1, 5):
        (source_dir / f"素材{idx}.md").write_text("修炼" * 1200, encoding="utf-8")

    batch_sizes = []

    def selector(payload):
        batch_sizes.append(len(payload["materials"]))
        decisions = []
        for material in payload["materials"]:
            decisions.append(
                {
                    "material_name": material["material_name"],
                    "use": True,
                    "mode": "excerpt",
                    "selected_text": material["material_text"][:100],
                    "reason": "保留片段",
                }
            )
        return {"decisions": decisions}

    manager = WorldReferenceManager(materials_dir=source_dir, cache_root=cache_dir)
    pack = manager.build_reference_pack(
        chapter_id="0002",
        chapter={"id": "0002", "title": "测试章节"},
        plan={"goal": "测试批次切分", "beats": ["修炼"]},
        selector=selector,
        budget_chars=5000,
        selector_batch_chars=3000,
    )

    assert len(batch_sizes) > 1
    assert len(pack["entries"]) >= 1


def test_validate_world_material_selection_and_batch():
    errors = validate_world_material_selection(
        {
            "use": True,
            "mode": "excerpt",
            "selected_text": "片段",
            "reason": "相关",
        }
    )
    assert errors == []

    batch_errors = validate_world_material_selection_batch(
        {
            "decisions": [
                {
                    "material_name": "世界观.md",
                    "use": True,
                    "mode": "excerpt",
                    "selected_text": "片段",
                    "reason": "相关",
                }
            ]
        }
    )
    assert batch_errors == []

    bad = validate_world_material_selection_batch(
        {
            "decisions": [
                {
                    "material_name": "",
                    "use": "yes",
                    "mode": "unknown",
                    "selected_text": 1,
                    "reason": 2,
                }
            ]
        }
    )
    assert bad


def test_discover_material_files_applies_exclude_patterns_and_no_recursion(tmp_path: Path):
    source_dir = tmp_path / "materials"
    cache_dir = tmp_path / "cache"
    nested_dir = source_dir / "tmpNote"
    source_dir.mkdir()
    nested_dir.mkdir()

    (source_dir / "CLAUDE.md").write_text("x", encoding="utf-8")
    (source_dir / "AGENTS.md").write_text("x", encoding="utf-8")
    (source_dir / "当前问题.md").write_text("x", encoding="utf-8")
    (source_dir / "提示语修正.md").write_text("x", encoding="utf-8")
    (source_dir / "文本分布优化器.md").write_text("x", encoding="utf-8")
    (source_dir / "第九卷设定.md").write_text("x", encoding="utf-8")
    (source_dir / "世界观修炼体系.md").write_text("保留", encoding="utf-8")
    (nested_dir / "世界观地图.md").write_text("子目录内容", encoding="utf-8")

    manager = WorldReferenceManager(
        materials_dir=source_dir,
        cache_root=cache_dir,
        exclude_patterns=[
            "CLAUDE.md",
            "AGENTS.md",
            "*第*卷*.md",
            "当前问题.md",
            "提示语修正.md",
            "文本分布优化器.md",
        ],
    )
    files = manager._discover_material_files()
    names = [path.name for path in files]

    assert names == ["世界观修炼体系.md"]
