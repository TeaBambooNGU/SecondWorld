from __future__ import annotations

from typing import Any, Dict, List

from langchain_core.prompts import ChatPromptTemplate

from src.utils import escape_prompt_template


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
) -> ChatPromptTemplate:
    outline_summary = {key: value for key, value in outline.items() if key != "chapters"}
    foreshadowing = chapter.get("foreshadowing")
    chapter_seed = {key: value for key, value in chapter.items() if key != "foreshadowing"}
    system = style_guide
    user = (
        "请用严格 JSON 输出章节计划，包含以下键：\n"
        "chapter_id, title, goal, beats (list), cast (list of agent ids), "
        "conflicts (list), pacing_notes, word_target。\n\n"
        "请先在内部预演 6 个不同计划版本, 放弃前3个版本, 从后3个版本中择优输出最终版本（仅输出最终 JSON）。\n\n"
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
    system = escape_prompt_template(system)
    user = escape_prompt_template(user)
    return ChatPromptTemplate.from_messages(
        [
            ("system", system),
            ("user", user),
        ]
    )


def build_agent_contribution_prompt(
    agent: Dict[str, Any],
    plan: Dict[str, Any],
    style_guide: str,
    previous_summary: str | None,
) -> ChatPromptTemplate:
    system = style_guide
    user = (
        "请用严格 JSON 输出角色贡献，包含以下键：\n"
        "agent_id, name, highlights (list, 6-10 条)。\n\n"
        f"角色资料：\n{agent}\n\n"
        f"章节计划：\n{plan}\n\n"
        "highlights 需包含动作、对话片段、冲突点与感官细节，避免总结或旁白。"
    )
    if previous_summary:
        user += f"\n上一章摘要：\n{previous_summary}\n"
    system = escape_prompt_template(system)
    user = escape_prompt_template(user)
    return ChatPromptTemplate.from_messages(
        [
            ("system", system),
            ("user", user),
        ]
    )


def build_director_draft_prompt(
    plan: Dict[str, Any],
    contributions: Dict[str, Any],
    style_guide: str,
    chapter_min_chars: int,
    chapter_max_chars: int,
    draft_examples: List[Dict[str, Any]] | None = None,
) -> ChatPromptTemplate:
    system = style_guide
    user = (
        f"章节计划：\n{plan}\n\n"
        f"角色贡献：\n{contributions}\n\n"
        "请用 Markdown 写出完整章节，不要使用代码围栏。"
        "不要包含总结段落。"
        "请先在内部预演 6 个不同成稿版本, 放弃前3个版本, 从后3个版本择优输出最终版本（只输出最终正文）。"
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
    system = escape_prompt_template(system)
    user = escape_prompt_template(user)
    return ChatPromptTemplate.from_messages(
        [
            ("system", system),
            ("user", user),
        ]
    )


def build_draft_length_fix_prompt(
    plan: Dict[str, Any],
    draft: str,
    style_guide: str,
    chapter_min_chars: int,
    chapter_max_chars: int,
    mode: str,
) -> ChatPromptTemplate:
    system = style_guide
    if mode == "expand":
        instruction = "请补写遗漏节拍与场景，使字数达到范围，不新增角色或支线。"
    else:
        instruction = "请压缩冗余与重复内容，使字数回到范围，不删减关键节拍。"
    user = (
        f"章节计划：\n{plan}\n\n"
        f"当前草稿：\n{draft}\n\n"
        f"目标字数：{chapter_min_chars}-{chapter_max_chars} 字。\n"
        f"{instruction}\n\n"
        "输出完整章节，使用 Markdown，不要代码围栏。\n"
    )
    system = escape_prompt_template(system)
    user = escape_prompt_template(user)
    return ChatPromptTemplate.from_messages(
        [
            ("system", system),
            ("user", user),
        ]
    )


def build_post_check_prompt(
    plan: Dict[str, Any],
    draft: str,
) -> ChatPromptTemplate:
    system = "你是一名网络小说（玄幻类型）的编辑，审阅章节草稿的冲突、节奏与风格问题。请用严格 JSON 回复，并使用中文。"
    user = (
        "请返回严格 JSON，包含键：summary, issues (list), suggestions (list), pacing_score (1-10)。\n\n"
        f"章节计划：\n{plan}\n\n"
        f"草稿：\n{draft}\n"
    )
    system = escape_prompt_template(system)
    user = escape_prompt_template(user)
    return ChatPromptTemplate.from_messages(
        [
            ("system", system),
            ("user", user),
        ]
    )


def build_anti_ai_cleanup_prompt(
    draft: str,
    forbidden_terms: List[str],
    draft_examples: List[Dict[str, Any]] | None = None,
) -> ChatPromptTemplate:
    system = (
        "你是一位资深的语言风格转换与文本润色专家，擅长将 AI 生成文本改写为更接近人类写作的自然表达。"
        "你能识别 AI 文本中的模板化语言、重复用语、情感缺失与逻辑生硬，并通过重写提升口语化与个性化。"
        "关键原则：关注语义熵（词汇分布多样性）。目标语义熵 ≥ 0.72，低于 0.38 视为过度可预测。"
        "自检公式：H = -Σ p(w)·log p(w)（p(w) 为词或短语的相对频率）。"
        "低熵信号：高频词密度过高、句式/段落起手高度同构、连接词过度统一、节奏持续单一。"
        "若低熵，必须通过改写句式、打散节奏、切换叙述视角与表达路径来提升多样性，禁止只做同义词替换。"
        "允许适度情感增强，但不得新增剧情、角色或世界观信息，不得改变原有事件顺序与事实含义。"
        "必须移除禁用词，禁用词不得出现在最终文本中。"
    )
    user = (
        "任务：对全文进行人类化改写，降低 AI 痕迹并提升自然度。"
        "请先识别模板化语言、重复词汇/句式、机械衔接与单一节奏，再进行全篇重写。"
        "写作节奏需具备变化：长短句交替、动作/对话/心理描写穿插、快慢段落对比。"
        "保持原意与逻辑连贯性，允许适度情感增强，但不新增剧情或角色。"
        "输出完整章节，使用 Markdown，不要代码围栏，不要附加说明，也不要提及熵值或改写过程。\n\n"
        f"禁用词：\n{forbidden_terms}\n\n"
        f"草稿：\n{draft}\n"
    )
    if draft_examples:
        user += "\n人类写作节奏模板（学习特点，禁止直接复用原句或情节）：\n"
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
    system = escape_prompt_template(system)
    user = escape_prompt_template(user)
    return ChatPromptTemplate.from_messages(
        [
            ("system", system),
            ("user", user),
        ]
    )


def build_director_revision_prompt(
    draft: str,
    post_check: Dict[str, Any],
    style_guide: str,
    chapter_min_chars: int,
    chapter_max_chars: int,
) -> ChatPromptTemplate:
    system = style_guide
    user = (
        f"编辑意见：\n{post_check}\n\n"
        f"待修订草稿：\n{draft}\n\n"
        "请根据问题与建议修订草稿。"
        "输出完整修订稿，使用 Markdown，不要代码围栏。"
        f"目标字数：{chapter_min_chars}-{chapter_max_chars} 字。\n\n"
    )
    system = escape_prompt_template(system)
    user = escape_prompt_template(user)
    return ChatPromptTemplate.from_messages(
        [
            ("system", system),
            ("user", user),
        ]
    )


def build_director_final_prompt(
    draft: str,
    style_guide: str,
    chapter_min_chars: int,
    chapter_max_chars: int,
) -> ChatPromptTemplate:
    system = style_guide
    user = (
        f"待定稿草稿：\n{draft}\n\n"
        "修正物理与空间不一致、不可达动作与感官来源不清的问题。"
        "不要新增剧情、角色或情感渲染。"
        "输出完整章节，使用 Markdown，不要代码围栏。"
        f"目标字数：{chapter_min_chars}-{chapter_max_chars} 字。\n\n"
    )
    system = escape_prompt_template(system)
    user = escape_prompt_template(user)
    return ChatPromptTemplate.from_messages(
        [
            ("system", system),
            ("user", user),
        ]
    )
