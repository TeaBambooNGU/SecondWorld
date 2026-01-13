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
    system = style_guide
    user = (
        "Create a chapter plan in strict JSON with the following keys:\n"
        "chapter_id, title, goal, beats (list), cast (list of agent ids), "
        "conflicts (list), pacing_notes, word_target.\n\n"
        f"Word target must be between {chapter_min_chars} and {chapter_max_chars} characters. "
        f"Cast size should be <= {max_agents}.\n\n"
        f"Series outline:\n{outline_summary}\n\n"
        f"Chapter seed:\n{chapter}\n\n"
    )
    if previous_summary:
        user += f"Previous chapter summary:\n{previous_summary}\n\n"
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
        f"Agent profile:\n{agent}\n\n"
        f"Chapter plan:\n{plan}\n\n"
        "Provide 6-10 bullet points: actions, dialogue snippets, conflict points, "
        "and sensory details. Avoid summary or narration."
    )
    if previous_summary:
        user += f"\nPrevious chapter summary:\n{previous_summary}\n"
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
) -> List[Dict[str, str]]:
    system = style_guide
    user = (
        f"Chapter plan:\n{plan}\n\n"
        f"Agent contributions:\n{contributions}\n\n"
        "Write a complete chapter in Markdown without code fences. "
        "Do not include a summary section. "
        f"Target length: {chapter_min_chars}-{chapter_max_chars} Chinese characters.\n\n"
    )
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]


def build_post_check_prompt(
    plan: Dict[str, Any],
    draft: str,
) -> List[Dict[str, str]]:
    system = (
        "You are an editor reviewing a chapter draft for conflicts, pacing, and style. "
        "Respond in strict JSON and write in Chinese."
    )
    user = (
        "Return strict JSON with keys: summary, issues (list), suggestions (list), pacing_score (1-10).\n\n"
        f"Chapter plan:\n{plan}\n\n"
        f"Draft:\n{draft}\n"
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
        "You are an editor removing overused web-novel words. "
        "Write in Chinese and keep the original meaning."
    )
    user = (
        "Remove any forbidden terms from the draft. "
        "If direct deletion harms meaning, rewrite the sentence to preserve meaning. "
        "Do not add new plot, characters, or emotional embellishment. "
        "Output the full chapter in Markdown without code fences.\n\n"
        f"Forbidden terms:\n{forbidden_terms}\n\n"
        f"Draft:\n{draft}\n"
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
        f"Editor notes:\\n{post_check}\\n\\n"
        f"Draft to revise:\\n{draft}\\n\\n"
        "Revise the draft to address issues and suggestions. "
        "Output the full revised chapter in Markdown without code fences. "
        f"Target length: {chapter_min_chars}-{chapter_max_chars} Chinese characters.\\n\\n"
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
        f"Chapter plan:\n{plan}\n\n"
        f"Draft to finalize:\n{draft}\n\n"
        "Fix physical and spatial inconsistencies, unreachable actions, and unclear sensation sources. "
        "Do not add new plot, characters, or emotional embellishment. "
        "Output the full chapter in Markdown without code fences. "
        f"Target length: {chapter_min_chars}-{chapter_max_chars} Chinese characters.\n\n"
    )
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]
