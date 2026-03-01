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
    world_references: str | None = None,
    chapter_context: str | None = None,
) -> ChatPromptTemplate:
    outline_summary = {key: value for key, value in outline.items() if key != "chapters"}
    foreshadowing = chapter.get("foreshadowing")
    chapter_seed = {key: value for key, value in chapter.items() if key != "foreshadowing"}
    system = style_guide
    user = (
        "请用严格 JSON 输出章节计划，包含以下键：\n"
        "chapter_id, title, goal, beats (list), cast (list of agent ids), "
        "conflicts (list), pacing_notes, word_target。\n\n"
        "请先在内部预演 3 个不同计划版本, 然后从3个版本中择优输出最终版本（仅输出最终 JSON）。\n\n"
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
    user = _append_chapter_context(user, chapter_context)
    user = _append_world_references(user, world_references)
    user = _inject_role_consistency_anchors(user)
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
        "highlights 需以动作、对话片段与冲突推进为主，避免总结或旁白。\n"
        "感官细节仅在自然且能推进节拍时再写，可省略；禁止为了堆砌氛围硬加比喻。\n"
        "不要输出 sensory_anchor 等拆分字段，感官信息若存在请并入 content。\n"
        "每条 highlight 都必须是可被镜头捕捉的片段，禁止解释角色意图或总结因果。\n"
        "禁止出现“不是……是……”“因为……所以……”“说明/意味着/本质上/其实”等解释腔。\n"
        "如需表达判断，只能通过角色对白、停顿和动作反应间接呈现。"
    )
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
    world_references: str | None = None,
    rag_references: str | None = None,
) -> ChatPromptTemplate:
    system = style_guide
    user = (
        f"章节计划：\n{plan}\n\n"
        f"角色贡献：\n{contributions}\n\n"
        "写作时可重组和改写角色贡献，不要逐句照抄 highlights。\n"
        "若 highlights 含解释性句子（如“不是……是……”“说明……”“意味着……”），"
        "必须改写成动作、对白或感官反应，禁止原句入文。\n"
        "感官描写是可选项：若不自然或不推动情节，直接删掉，不要硬写。\n"
        "请用 Markdown 写出完整章节，不要使用代码围栏。"
        "不要包含总结段落。"
        "请先在内部预演3个不同成稿版本, 从3个版本中择优输出最终版本（只输出最终正文）。"
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
    user = _append_world_references(user, world_references)
    user = _append_rag_references(user, rag_references)
    user = _inject_role_consistency_anchors(user)
    system = escape_prompt_template(system)
    user = escape_prompt_template(user)
    return ChatPromptTemplate.from_messages(
        [
            ("system", system),
            ("user", user),
        ]
    )


def build_chapter_plot_summary_prompt(
    *,
    chapter_id: str,
    chapter_title: str,
    chapter_text: str,
) -> ChatPromptTemplate:
    system = (
        "你是剧情梳理助手。"
        "你的任务是提炼章节剧情摘要，只保留关键事件、因果与角色动机变化。"
        "输出纯文本，不要代码围栏，不要分点。"
    )
    user = (
        f"章节ID：{chapter_id}\n"
        f"章节标题：{chapter_title}\n\n"
        "请输出 150-260 字剧情摘要，要求：\n"
        "1) 仅描述剧情事实与关键因果。\n"
        "2) 不加入评价、建议或改写指令。\n"
        "3) 不新增原文不存在的信息。\n\n"
        f"章节正文：\n{chapter_text}\n"
    )
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
    user = _inject_role_consistency_anchors(user)
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
    world_references: str | None = None,
) -> ChatPromptTemplate:
    system = "你是一名网络小说（玄幻类型）的编辑，审阅章节草稿的冲突、节奏与风格问题。请用严格 JSON 回复，并使用中文。"
    user = (
        "请返回严格 JSON，包含键：summary, issues (list), suggestions (list), pacing_score (1-10)。\n\n"
        f"章节计划：\n{plan}\n\n"
        f"草稿：\n{draft}\n"
    )
    user = _append_world_references(user, world_references)
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
    user = _inject_role_consistency_anchors(user)
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
    user = _inject_role_consistency_anchors(user)
    system = escape_prompt_template(system)
    user = escape_prompt_template(user)
    return ChatPromptTemplate.from_messages(
        [
            ("system", system),
            ("user", user),
        ]
    )


def build_world_material_selector_prompt(
    *,
    chapter: Dict[str, Any],
    plan: Dict[str, Any],
    materials: List[Dict[str, Any]],
    remaining_budget_chars: int,
    batch_index: int,
    batch_total: int,
) -> ChatPromptTemplate:
    material_blocks: List[str] = []
    for index, material in enumerate(materials, start=1):
        name = str(material.get("material_name") or "").strip()
        text = str(material.get("material_text") or "")
        if not name:
            continue
        material_blocks.append(
            "\n".join(
                [
                    f"### 文件{index}: {name}",
                    text,
                ]
            )
        )
    materials_text = "\n\n".join(material_blocks)
    system = (
        "你是世界观素材筛选 Agent。"
        "你的任务是判断每份素材是否适合当前章节，并决定迁移全篇或节选。"
        "输出必须是严格 JSON，不要输出代码围栏。"
    )
    user = (
        "请输出严格 JSON，字段为：\n"
        "decisions(list)，其中每一项都包含："
        "material_name (string), use (bool), mode (full|excerpt|skip), selected_text (string), reason (string)。\n\n"
        "规则：\n"
        "1) 必须为当前批次中的每个文件都返回一条 decision，material_name 必须与输入文件名完全一致。\n"
        "2) 如果素材对当前章节无帮助，use=false, mode=skip。\n"
        "3) 如果整篇都相关，mode=full；selected_text 可留空。\n"
        "4) 如果仅部分相关，mode=excerpt，并在 selected_text 放入可直接迁移的原文片段。\n"
        "5) selected_text 必须来自原素材，不可改写，不可虚构。\n"
        "6) 优先保留世界观规则、势力关系、修炼体系、关键禁忌、地理设定。\n\n"
        f"当前章节信息：\n{chapter}\n\n"
        f"章节计划：\n{plan}\n\n"
        f"当前批次：{batch_index}/{batch_total}\n"
        f"剩余预算字符数：{remaining_budget_chars}\n\n"
        f"素材原文：\n{materials_text}\n"
    )
    system = escape_prompt_template(system)
    user = escape_prompt_template(user)
    return ChatPromptTemplate.from_messages(
        [
            ("system", system),
            ("user", user),
        ]
    )


def _append_world_references(user_prompt: str, world_references: str | None) -> str:
    if not world_references:
        return user_prompt
    references = world_references.strip()
    if not references:
        return user_prompt
    return (
        f"{user_prompt}"
        "可选世界观参考（来自工程缓存，按需使用；允许直接引用设定内容，禁止生造设定）：\n"
        f"{references}\n\n"
    )


def _append_chapter_context(user_prompt: str, chapter_context: str | None) -> str:
    if not chapter_context:
        return user_prompt
    context = chapter_context.strip()
    if not context:
        return user_prompt
    return (
        f"{user_prompt}"
        "已生成章节连续性参考（必须保持设定与因果一致，不得与既有剧情冲突）：\n"
        f"{context}\n\n"
    )


def _append_rag_references(user_prompt: str, rag_references: str | None) -> str:
    if not rag_references:
        return user_prompt
    references = rag_references.strip()
    if not references:
        return user_prompt
    return (
        f"{user_prompt}"
        "知识库行文参考（学习表达与措辞节奏；禁止整句照抄，禁止复用原情节）：\n"
        f"{references}\n\n"
        "请优先参考这些片段中的动作动词、语气词、口语化短句与对话节奏来改写成稿。\n\n"
    )


def _inject_role_consistency_anchors(user_prompt: str) -> str:
    middle_anchor = (
        "执行要求（角色锚点-中段确认）："
        "请在内部再次确认你仍严格遵守 system 中定义的角色与规则；"
        "该确认不得写入最终输出。\n"
    )
    tail_anchor = (
        "执行要求（角色锚点-结尾再注入）："
        "在给出最终答案前，再次进行同样自检，确保不因后文信息产生角色偏移；"
        "不要输出自检过程。\n"
    )
    head, sep, tail = user_prompt.partition("\n\n")
    if sep:
        return f"{head}\n\n{middle_anchor}\n{tail.rstrip()}\n\n{tail_anchor}"
    return f"{middle_anchor}\n{user_prompt.rstrip()}\n\n{tail_anchor}"
