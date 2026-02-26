from langchain_core.prompts import ChatPromptTemplate

from src.prompting import (
    build_agent_contribution_prompt,
    build_chapter_plot_summary_prompt,
    build_director_draft_prompt,
    build_director_final_prompt,
    build_director_plan_prompt,
    build_director_revision_prompt,
    build_draft_length_fix_prompt,
    build_post_check_prompt,
    build_world_material_selector_prompt,
    compose_style_guide,
)
from src.utils import build_agent_profile


def _assert_role_anchors(user_content: str):
    assert "角色锚点-中段确认" in user_content
    assert "角色锚点-结尾再注入" in user_content
    assert user_content.rstrip().endswith("不要输出自检过程。")


def test_build_director_plan_prompt():
    outline = {"series": {"title": "Test"}, "chapters": []}
    chapter = {"id": "0001", "title": "Test Chapter"}
    style = "Style"
    prompt = build_director_plan_prompt(
        outline=outline,
        chapter=chapter,
        style_guide=style,
        previous_summary=None,
        max_agents=4,
        chapter_min_chars=2000,
        chapter_max_chars=4000,
    )
    assert isinstance(prompt, ChatPromptTemplate)
    messages = prompt.format_messages()
    assert messages[0].type == "system"
    assert "严格 JSON" in messages[1].content


def test_build_director_plan_prompt_allows_style_guide_braces():
    outline = {"series": {"title": "Test"}, "chapters": []}
    chapter = {"id": "0001", "title": "Test Chapter"}
    style = "系统指令包含 {花括号} 字样"
    prompt = build_director_plan_prompt(
        outline=outline,
        chapter=chapter,
        style_guide=style,
        previous_summary=None,
        max_agents=4,
        chapter_min_chars=2000,
        chapter_max_chars=4000,
    )
    messages = prompt.format_messages()
    assert "{花括号}" in messages[0].content


def test_build_director_plan_prompt_includes_foreshadowing_reference():
    outline = {"series": {"title": "Test"}, "chapters": []}
    chapter = {
        "id": "0001",
        "title": "Test Chapter",
        "summary": "Seed",
        "foreshadowing": "暗线示例",
    }
    messages = build_director_plan_prompt(
        outline=outline,
        chapter=chapter,
        style_guide="Style",
        previous_summary=None,
        max_agents=4,
        chapter_min_chars=2000,
        chapter_max_chars=4000,
    )
    user_content = messages.format_messages()[1].content
    assert "暗线参考" in user_content
    assert "暗线示例" in user_content
    assert "foreshadowing" not in user_content


def test_build_director_plan_prompt_includes_chapter_context_and_world_references():
    outline = {"series": {"title": "Test"}, "chapters": []}
    chapter = {"id": "0004", "title": "Test Chapter"}
    prompt = build_director_plan_prompt(
        outline=outline,
        chapter=chapter,
        style_guide="Style",
        previous_summary=None,
        max_agents=4,
        chapter_min_chars=2000,
        chapter_max_chars=4000,
        world_references="素材A\\n素材B",
        chapter_context="【第0001章·全文】\n正文A",
    )
    user_content = prompt.format_messages()[1].content
    assert "已生成章节连续性参考" in user_content
    assert "第0001章" in user_content
    assert "可选世界观参考" in user_content
    assert "素材A" in user_content
    _assert_role_anchors(user_content)


def test_build_director_draft_prompt_includes_examples():
    plan = {"chapter_id": "0001", "title": "Test Chapter"}
    contributions = {"agent": "贡献"}
    examples = [
        {"paragraph": "示例段落", "traits": ["节奏紧凑", "对话有张力"]},
    ]
    prompt = build_director_draft_prompt(
        plan=plan,
        contributions=contributions,
        style_guide="Style",
        chapter_min_chars=2000,
        chapter_max_chars=4000,
        draft_examples=examples,
    )
    user_content = prompt.format_messages()[1].content
    assert "示例段落" in user_content
    assert "节奏紧凑" in user_content
    assert "对话有张力" in user_content


def test_build_director_draft_prompt_includes_world_references():
    plan = {"chapter_id": "0001", "title": "Test Chapter"}
    contributions = {"agent": "贡献"}
    prompt = build_director_draft_prompt(
        plan=plan,
        contributions=contributions,
        style_guide="Style",
        chapter_min_chars=2000,
        chapter_max_chars=4000,
        world_references="素材A\\n素材B",
    )
    user_content = prompt.format_messages()[1].content
    assert "可选世界观参考" in user_content
    assert "素材A" in user_content
    _assert_role_anchors(user_content)


def test_build_director_draft_prompt_requires_rewrite_of_explanatory_highlights():
    plan = {"chapter_id": "0001", "title": "Test Chapter"}
    contributions = {"agent": "贡献"}
    prompt = build_director_draft_prompt(
        plan=plan,
        contributions=contributions,
        style_guide="Style",
        chapter_min_chars=2000,
        chapter_max_chars=4000,
    )
    user_content = prompt.format_messages()[1].content
    assert "不要逐句照抄 highlights" in user_content
    assert "禁止原句入文" in user_content
    assert "若不自然或不推动情节，直接删掉" in user_content


def test_build_agent_contribution_prompt_blocks_explanatory_sentences():
    prompt = build_agent_contribution_prompt(
        agent={"id": "于皓", "name": "于皓"},
        plan={"chapter_id": "0001", "title": "Test Chapter"},
        style_guide="Style",
        previous_summary=None,
    )
    user_content = prompt.format_messages()[1].content
    assert "感官细节仅在自然且能推进节拍时再写，可省略" in user_content
    assert "不要输出 sensory_anchor 等拆分字段" in user_content
    assert "禁止出现“不是……是……”" in user_content
    assert "通过角色对白、停顿和动作反应间接呈现" in user_content


def test_build_post_check_prompt_includes_world_references():
    prompt = build_post_check_prompt(
        plan={"chapter_id": "0001", "title": "Test Chapter"},
        draft="草稿",
        world_references="参考片段",
    )
    user_content = prompt.format_messages()[1].content
    assert "可选世界观参考" in user_content
    assert "参考片段" in user_content


def test_build_chapter_plot_summary_prompt():
    prompt = build_chapter_plot_summary_prompt(
        chapter_id="0001",
        chapter_title="标题",
        chapter_text="正文",
    )
    user_content = prompt.format_messages()[1].content
    assert "剧情摘要" in user_content
    assert "章节ID：0001" in user_content
    assert "章节正文" in user_content


def test_build_revision_and_final_prompt_do_not_include_world_references_block():
    revision_prompt = build_director_revision_prompt(
        draft="草稿",
        post_check={"issues": [], "suggestions": []},
        style_guide="Style",
        chapter_min_chars=2000,
        chapter_max_chars=4000,
    )
    final_prompt = build_director_final_prompt(
        draft="草稿",
        style_guide="Style",
        chapter_min_chars=2000,
        chapter_max_chars=4000,
    )
    revision_user_content = revision_prompt.format_messages()[1].content
    final_user_content = final_prompt.format_messages()[1].content
    assert "可选世界观参考" not in revision_user_content
    assert "可选世界观参考" not in final_user_content
    _assert_role_anchors(revision_user_content)
    _assert_role_anchors(final_user_content)


def test_build_world_material_selector_prompt():
    prompt = build_world_material_selector_prompt(
        chapter={"id": "0001", "title": "章节"},
        plan={"goal": "测试目标"},
        materials=[
            {"material_name": "世界观.md", "material_text": "素材正文"},
            {"material_name": "势力.md", "material_text": "势力正文"},
        ],
        remaining_budget_chars=1000,
        batch_index=1,
        batch_total=2,
    )
    user_content = prompt.format_messages()[1].content
    assert "decisions(list)" in user_content
    assert "当前批次：1/2" in user_content
    assert "世界观.md" in user_content
    assert "势力.md" in user_content


def test_compose_style_guide():
    agent_style = "# Agent\nA"
    shared_style = "# Shared\nB"
    combined = compose_style_guide(agent_style, shared_style)
    assert combined == "# Agent\nA\n\n# Shared\nB"


def test_build_agent_profile_keeps_component_ids_and_traits():
    agent = {
        "id": "主角",
        "personality_id": "坚韧内敛",
        "background_id": "宗门出身",
        "identity_id": "宗门弟子",
        "traits": ["不愿求人", "痛感迟滞"],
    }
    profile = build_agent_profile(agent, None, None, None)
    assert profile["traits"] == ["不愿求人", "痛感迟滞"]
    assert profile["personality_id"] == "坚韧内敛"
    assert profile["background_id"] == "宗门出身"
    assert profile["identity_id"] == "宗门弟子"


def test_build_agent_profile_drops_empty_traits():
    agent = {"id": "暴烈型", "archetype": "暴烈型", "traits": []}
    profile = build_agent_profile(agent, None, None, None)
    assert "traits" not in profile


def test_build_draft_length_fix_prompt_contains_targets():
    plan = {"chapter_id": "0001", "title": "Test Chapter"}
    prompt = build_draft_length_fix_prompt(
        plan=plan,
        draft="示例正文",
        style_guide="Style",
        chapter_min_chars=2000,
        chapter_max_chars=4000,
        mode="expand",
    )
    user_content = prompt.format_messages()[1].content
    assert "目标字数：2000-4000 字" in user_content
    assert "补写" in user_content
    _assert_role_anchors(user_content)
