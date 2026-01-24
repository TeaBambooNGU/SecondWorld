from src.prompting import build_director_draft_prompt, build_director_plan_prompt, compose_style_guide
from src.utils import build_agent_profile


def test_build_director_plan_prompt():
    outline = {"series": {"title": "Test"}, "chapters": []}
    chapter = {"id": "0001", "title": "Test Chapter"}
    style = "Style"
    messages = build_director_plan_prompt(
        outline=outline,
        chapter=chapter,
        style_guide=style,
        previous_summary=None,
        max_agents=4,
        chapter_min_chars=2000,
        chapter_max_chars=4000,
    )
    assert isinstance(messages, list)
    assert messages[0]["role"] == "system"
    assert "strict JSON" in messages[1]["content"]


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
    user_content = messages[1]["content"]
    assert "暗线参考" in user_content
    assert "暗线示例" in user_content
    assert "foreshadowing" not in user_content


def test_build_director_draft_prompt_includes_examples():
    plan = {"chapter_id": "0001", "title": "Test Chapter"}
    contributions = {"agent": "贡献"}
    examples = [
        {"paragraph": "示例段落", "traits": ["节奏紧凑", "对话有张力"]},
    ]
    messages = build_director_draft_prompt(
        plan=plan,
        contributions=contributions,
        style_guide="Style",
        chapter_min_chars=2000,
        chapter_max_chars=4000,
        draft_examples=examples,
    )
    user_content = messages[1]["content"]
    assert "示例段落" in user_content
    assert "节奏紧凑" in user_content
    assert "对话有张力" in user_content


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
