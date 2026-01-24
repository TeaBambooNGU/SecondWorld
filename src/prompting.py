from __future__ import annotations

from typing import Any, Dict, List


def compose_style_guide(agent_style: str, shared_style: str) -> str:
    parts = [agent_style.strip(), shared_style.strip()]
    return "\n\n".join(part for part in parts if part)


def build_director_plan_prompt(
    outline: Dict[str, Any],
    chapter: Dict[str, Any],
    style_guide: str,
    previous_summary: str | None,
    max_agents: int,
    chapter_min_chars: int,
    chapter_max_chars: int,
) -> List[Dict[str, str]]:
    outline_summary = {key: value for key, value in outline.items() if key != "chapters"}
    foreshadowing = chapter.get("foreshadowing")
    chapter_seed = {key: value for key, value in chapter.items() if key != "foreshadowing"}
    system = style_guide
    user = (
        "请用严格 JSON 输出章节计划，包含以下键：\n"
        "chapter_id, title, goal, beats (list), cast (list of agent ids), "
        "conflicts (list), pacing_notes, word_target。\n\n"
        "请先在内部预演 3 个不同计划版本，择优输出最终版本（仅输出最终 JSON）。\n\n"
        f"字数目标必须在 {chapter_min_chars} 到 {chapter_max_chars} 之间，"
        f"出场角色数量需 <= {max_agents}。\n\n"
        f"系列大纲：\n{outline_summary}\n\n"
        f"章节要素：\n{chapter_seed}\n\n"
    )
    if foreshadowing:
        user += (
            "暗线参考（仅供背景参考，不得在计划 JSON 或正文中直写）:\n"
            f"{foreshadowing}\n\n"
        )
    if previous_summary:
        user += f"上一章摘要：\n{previous_summary}\n\n"
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]


def build_agent_contribution_prompt(
    agent: Dict[str, Any],
    plan: Dict[str, Any],
    style_guide: str,
    previous_summary: str | None,
) -> List[Dict[str, str]]:
    system = style_guide
    user = (
        f"角色资料：\n{agent}\n\n"
        f"章节计划：\n{plan}\n\n"
        "提供 6-10 条要点：动作、对话片段、冲突点与感官细节。"
        "避免总结或旁白。"
    )
    if previous_summary:
        user += f"\n上一章摘要：\n{previous_summary}\n"
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]


def build_director_draft_prompt(
    plan: Dict[str, Any],
    contributions: Dict[str, str],
    style_guide: str,
    chapter_min_chars: int,
    chapter_max_chars: int,
    draft_examples: List[Dict[str, Any]] | None = None,
) -> List[Dict[str, str]]:
    system = style_guide
    user = (
        f"章节计划：\n{plan}\n\n"
        f"角色贡献：\n{contributions}\n\n"
        "请用 Markdown 写出完整章节，不要使用代码围栏。"
        "不要包含总结段落。"
        "请先在内部预演 3 个不同成稿版本，择优输出最终版本（只输出最终正文）。"
        f"目标字数：{chapter_min_chars}-{chapter_max_chars} 字。\n\n"
    )
    if draft_examples:
        user += "示例文章段落（学习特点，禁止直接复用原句或情节）：\n"
        index = 1
        for example in draft_examples:
            paragraph = str(example.get("paragraph", "")).strip()
            traits = example.get("traits") or []
            if not paragraph and not traits:
                continue
            user += f"{index}. 段落:\n{paragraph}\n"
            if traits:
                traits_text = "、".join(str(item).strip() for item in traits if str(item).strip())
                if traits_text:
                    user += f"   学习特点: {traits_text}\n"
            user += "\n"
            index += 1
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]


def build_post_check_prompt(
    plan: Dict[str, Any],
    draft: str,
) -> List[Dict[str, str]]:
    system = (
        "你是一名编辑，审阅章节草稿的冲突、节奏与风格问题。"
        "请用严格 JSON 回复，并使用中文。"
    )
    user = (
        "请返回严格 JSON，包含键：summary, issues (list), suggestions (list), pacing_score (1-10)。\n\n"
        f"章节计划：\n{plan}\n\n"
        f"草稿：\n{draft}\n"
    )
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]


def build_anti_ai_cleanup_prompt(
    draft: str,
    forbidden_terms: List[str],
) -> List[Dict[str, str]]:
    system = (
        "你是一名编辑，负责移除过度使用的网文词汇。"
        "用中文写作并保持原意。"
    )
    user = (
        "请从草稿中移除任何禁用词。"
        "如果直接删除会破坏语义，请改写句子以保留含义。"
        "不要新增剧情、角色或情感渲染。"
        "输出完整章节，使用 Markdown，不要代码围栏。\n\n"
        f"禁用词：\n{forbidden_terms}\n\n"
        f"草稿：\n{draft}\n"
    )
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]


def build_director_revision_prompt(
    plan: Dict[str, Any],
    draft: str,
    post_check: Dict[str, Any],
    style_guide: str,
    chapter_min_chars: int,
    chapter_max_chars: int,
) -> List[Dict[str, str]]:
    system = style_guide
    user = (
        f"编辑意见：\\n{post_check}\\n\\n"
        f"待修订草稿：\\n{draft}\\n\\n"
        "请根据问题与建议修订草稿。"
        "输出完整修订稿，使用 Markdown，不要代码围栏。"
        f"目标字数：{chapter_min_chars}-{chapter_max_chars} 字。\\n\\n"
    )
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]


def build_director_final_prompt(
    plan: Dict[str, Any],
    draft: str,
    style_guide: str,
    chapter_min_chars: int,
    chapter_max_chars: int,
) -> List[Dict[str, str]]:
    system = style_guide
    user = (
        f"待定稿草稿：\n{draft}\n\n"
        "修正物理与空间不一致、不可达动作与感官来源不清的问题。"
        "不要新增剧情、角色或情感渲染。"
        "输出完整章节，使用 Markdown，不要代码围栏。"
        f"目标字数：{chapter_min_chars}-{chapter_max_chars} 字。\n\n"
    )
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]
