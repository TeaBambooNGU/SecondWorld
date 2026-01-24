from __future__ import annotations

from typing import Any, Dict, List


def validate_plan(
    plan: Dict[str, Any],
    *,
    min_chars: int,
    max_chars: int,
    max_agents: int,
) -> List[str]:
    errors: List[str] = []
    required = ["chapter_id", "title", "goal", "beats", "cast", "conflicts", "pacing_notes", "word_target"]
    for key in required:
        if key not in plan:
            errors.append(f"缺少字段: {key}")
    if not isinstance(plan.get("beats"), list):
        errors.append("beats 必须为 list")
    if not isinstance(plan.get("cast"), list):
        errors.append("cast 必须为 list")
    if not isinstance(plan.get("conflicts"), list):
        errors.append("conflicts 必须为 list")
    word_target = plan.get("word_target")
    if isinstance(word_target, (int, float)):
        if not (min_chars <= int(word_target) <= max_chars):
            errors.append("word_target 超出范围")
    else:
        errors.append("word_target 必须为数字")
    cast = plan.get("cast") or []
    if isinstance(cast, list) and len(cast) > max_agents:
        errors.append("cast 数量超出限制")
    return errors


def validate_post_check(post_check: Dict[str, Any]) -> List[str]:
    errors: List[str] = []
    required = ["summary", "issues", "suggestions", "pacing_score"]
    for key in required:
        if key not in post_check:
            errors.append(f"缺少字段: {key}")
    if not isinstance(post_check.get("issues"), list):
        errors.append("issues 必须为 list")
    if not isinstance(post_check.get("suggestions"), list):
        errors.append("suggestions 必须为 list")
    score = post_check.get("pacing_score")
    if isinstance(score, (int, float)):
        if not (1 <= float(score) <= 10):
            errors.append("pacing_score 必须在 1-10")
    else:
        errors.append("pacing_score 必须为数字")
    return errors


def validate_contribution(contribution: Dict[str, Any]) -> List[str]:
    errors: List[str] = []
    required = ["agent_id", "name", "highlights"]
    for key in required:
        if key not in contribution:
            errors.append(f"缺少字段: {key}")
    highlights = contribution.get("highlights")
    if not isinstance(highlights, list):
        errors.append("highlights 必须为 list")
    else:
        if not (6 <= len(highlights) <= 10):
            errors.append("highlights 数量需在 6-10 之间")
    return errors


def validate_draft_length(draft: str, *, min_chars: int, max_chars: int) -> List[str]:
    errors: List[str] = []
    length = len(draft.strip())
    if length < min_chars:
        errors.append("正文长度不足")
    if length > max_chars:
        errors.append("正文长度超出上限")
    return errors
