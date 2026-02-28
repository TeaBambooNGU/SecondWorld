from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Dict, Optional

from .chains import (
    build_agent_contribution_chain,
    build_anti_ai_cleanup_chain,
    build_draft_chain,
    build_final_chain,
    build_plan_chain,
    build_post_check_chain,
    build_revision_chain,
    build_world_material_selector_chain,
)
from .config_loader import get_api_key, load_env, load_text, load_yaml, resolve_api_config
from .langchain_client import LangChainClient, format_messages
from .parsers import parse_json_with_repair
from .prompting import (
    build_agent_contribution_prompt,
    build_anti_ai_cleanup_prompt,
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
from .rag.service import build_rag_query, format_rag_references, retrieve_rag_examples, resolve_rag_config
from .utils import (
    FileLogger,
    build_agent_profile,
    extract_forbidden_terms,
    find_forbidden_terms,
    load_json,
    now_iso,
    save_json,
    slugify,
)
from .validators import (
    validate_contribution,
    validate_draft_length,
    validate_plan,
    validate_post_check,
    validate_world_material_selection_batch,
)
from .world_reference_manager import WorldReferenceManager

DEFAULT_WORLD_MATERIALS_DIR = "/Users/teabamboo/Documents/NGU_Notes/我的小说"


class LangChainPipeline:
    def __init__(
        self,
        project_path: str = "config/project.yaml",
        logger: FileLogger | None = None,
    ) -> None:
        load_env()
        self.project_path = project_path
        self.project = load_yaml(project_path)
        self.api = resolve_api_config(self.project)
        self.api_key = get_api_key(self.api)
        self.logger = logger
        self.client = LangChainClient(self.api, self.api_key)

    def run_plan(self, chapter_id: str | None = None) -> Dict[str, Any]:
        plan, _ = self._run_plan_with_world_references(chapter_id=chapter_id)
        return plan

    def _run_plan_with_world_references(self, chapter_id: str | None = None) -> tuple[Dict[str, Any], str]:
        outline = self._load_outline()
        chapter = self._select_chapter(outline, chapter_id)
        shared_style = self._load_style_guide_shared()
        style_guide = self._compose_style_guide("director", shared_style, stage="plan")
        state = self._load_state()
        previous_summary = self._previous_summary(state)
        generation = self.project["generation"]
        plan_seed = self._build_plan_seed(chapter)
        world_references = self._prepare_world_references(
            chapter=chapter,
            plan=plan_seed,
            generation=generation,
        )
        chapter_context = self._build_chapter_context(
            outline=outline,
            current_chapter_id=str(chapter.get("id") or ""),
            state=state,
            generation=generation,
        )

        self._log_info(f"开始生成计划 chapter={chapter.get('id')} title={chapter.get('title')}")
        prompt = build_director_plan_prompt(
            outline=outline,
            chapter=chapter,
            style_guide=style_guide,
            previous_summary=previous_summary,
            max_agents=generation["max_agents_per_chapter"],
            chapter_min_chars=generation["chapter_min_chars"],
            chapter_max_chars=generation["chapter_max_chars"],
            world_references=world_references,
            chapter_context=chapter_context,
        )
        llm = self._build_llm(
            temperature=generation.get("temperature"),
            top_p=generation.get("top_p"),
            top_k=generation.get("top_k"),
        )
        chain = build_plan_chain(prompt, llm)
        raw = self._invoke_chain(chain, prompt, stage="计划")
        plan = self._parse_plan(raw, generation)
        if not plan:
            self._log_info("计划解析失败")
            raise RuntimeError("Failed to parse chapter plan JSON.")
        self._save_plan(plan)
        self._log_trace("计划-解析后", json.dumps(plan, ensure_ascii=False, indent=2))
        self._log_info(f"计划生成完成 chapter={plan.get('chapter_id')} title={plan.get('title')}")
        return plan, world_references

    def run_chapter(
        self,
        chapter_id: str | None = None,
        stream_override: Optional[bool] = None,
        force: bool = False,
    ) -> Dict[str, Any]:
        outline = self._load_outline()
        chapter = self._select_chapter(outline, chapter_id)
        shared_style = self._load_style_guide_shared()
        draft_examples = self._load_draft_examples()
        state = self._load_state()
        previous_summary = self._previous_summary(state)
        generation = self.project["generation"]
        api = self.api

        plan, world_references = self._resolve_plan_and_world_references(
            chapter=chapter,
            generation=generation,
        )

        contributions = self._collect_contributions(
            plan=plan,
            chapter=chapter,
            shared_style=shared_style,
            previous_summary=previous_summary,
        )

        stream = api.get("stream", False) if stream_override is None else stream_override
        style_guide = self._compose_style_guide("director", shared_style, stage="draft")
        prompt = build_director_draft_prompt(
            plan=plan,
            contributions=contributions,
            style_guide=style_guide,
            chapter_min_chars=generation["chapter_min_chars"],
            chapter_max_chars=generation["chapter_max_chars"],
            draft_examples=draft_examples,
            world_references=world_references,
            rag_references=self._build_rag_references(plan=plan, contributions=contributions),
        )
        output_path = self._chapter_output_path(plan)
        if output_path.exists() and not force:
            raise RuntimeError(f"Chapter file exists: {output_path}")

        self._log_info(f"开始生成章节成稿 stream={stream}")
        draft, versions = self._generate_draft_versions(
            plan=plan,
            prompt=prompt,
            style_guide=style_guide,
            output_path=output_path,
            generation=generation,
            stream=stream,
        )

        post_check = self._post_check(plan, draft, generation, world_references=world_references)

        if generation.get("max_turns", 1) > 1 and post_check.get("suggestions"):
            style_guide = self._compose_style_guide("director", shared_style, stage="revision")
            revision_prompt = build_director_revision_prompt(
                draft=draft,
                post_check=post_check,
                style_guide=style_guide,
                chapter_min_chars=generation["chapter_min_chars"],
                chapter_max_chars=generation["chapter_max_chars"],
            )
            draft = self._rewrite_draft(
                prompt=revision_prompt,
                output_path=output_path,
                generation=generation,
                stream=stream,
                stage="修订-改稿",
                chain_builder=build_revision_chain,
            )
            self._log_trace("修订-改稿-正文", draft)
            versions.append(self._archive_draft(output_path, draft, stage="revision"))

        forbidden_terms = extract_forbidden_terms(shared_style)
        if forbidden_terms:
            matched_terms = find_forbidden_terms(draft, forbidden_terms)
            if matched_terms:
                self._log_info(f"反AI审核命中高频词: {', '.join(matched_terms)}")
                self._log_trace("修订-反AI-命中词", ", ".join(matched_terms))
                cleanup_prompt = build_anti_ai_cleanup_prompt(
                    draft=draft,
                    forbidden_terms=matched_terms,
                    draft_examples=draft_examples,
                )
                draft = self._rewrite_draft(
                    prompt=cleanup_prompt,
                    output_path=output_path,
                    generation=generation,
                    stream=stream,
                    stage="修订-反AI",
                    chain_builder=build_anti_ai_cleanup_chain,
                )
                self._log_trace("修订-反AI-正文", draft)
            else:
                self._log_info("反AI审核未命中高频词，跳过清理")
        else:
            self._log_info("反AI审核规则为空，跳过清理")

        style_guide = self._compose_style_guide("director", shared_style, stage="final")
        final_prompt = build_director_final_prompt(
            draft=draft,
            style_guide=style_guide,
            chapter_min_chars=generation["chapter_min_chars"],
            chapter_max_chars=generation["chapter_max_chars"],
        )
        draft = self._rewrite_draft(
            prompt=final_prompt,
            output_path=output_path,
            generation=generation,
            stream=stream,
            stage="终审",
            chain_builder=build_final_chain,
        )
        self._log_trace("终审-正文", draft)
        versions.append(self._archive_draft(output_path, draft, stage="final"))
        self._log_info(f"终审完成 字数={len(draft)} 输出={output_path}")

        plot_summary = self._ensure_plot_summary_cached(
            chapter_id=str(plan.get("chapter_id") or chapter.get("id") or "0000"),
            chapter_title=str(plan.get("title") or chapter.get("title") or "chapter"),
            chapter_text=draft,
            generation=generation,
        )

        state = self._update_state(state, plan, output_path, post_check, versions, plot_summary)
        self._save_state(state)
        return {"plan": plan, "draft_path": str(output_path), "post_check": post_check}

    def _resolve_plan_and_world_references(
        self,
        *,
        chapter: Dict[str, Any],
        generation: Dict[str, Any],
    ) -> tuple[Dict[str, Any], str]:
        plan = self._load_plan(chapter["id"])
        if plan:
            self._log_info(f"使用已有计划 chapter={chapter.get('id')} title={chapter.get('title')}")
            world_references = self._prepare_world_references(
                chapter=chapter,
                plan=plan,
                generation=generation,
            )
            return plan, world_references

        self._log_info(f"未找到计划，开始生成 chapter={chapter.get('id')} title={chapter.get('title')}")
        plan, world_references = self._run_plan_with_world_references(chapter_id=chapter["id"])
        return plan, world_references

    def _generate_draft_versions(
        self,
        *,
        plan: Dict[str, Any],
        prompt,
        style_guide: str,
        output_path: Path,
        generation: Dict[str, Any],
        stream: bool,
    ) -> tuple[str, list[Dict[str, Any]]]:
        versions: list[Dict[str, Any]] = []
        draft = self._rewrite_draft(
            prompt=prompt,
            output_path=output_path,
            generation=generation,
            stream=stream,
            stage="成稿",
            chain_builder=build_draft_chain,
        )
        self._log_trace("成稿-正文", draft)
        length_errors = validate_draft_length(
            draft,
            min_chars=generation["chapter_min_chars"],
            max_chars=generation["chapter_max_chars"],
        )
        if length_errors:
            self._log_info(f"成稿字数未达标: {'; '.join(length_errors)}")
            mode = "expand" if any("不足" in item for item in length_errors) else "compress"
            fix_prompt = build_draft_length_fix_prompt(
                plan=plan,
                draft=draft,
                style_guide=style_guide,
                chapter_min_chars=generation["chapter_min_chars"],
                chapter_max_chars=generation["chapter_max_chars"],
                mode=mode,
            )
            draft = self._rewrite_draft(
                prompt=fix_prompt,
                output_path=output_path,
                generation=generation,
                stream=stream,
                stage="成稿-补写" if mode == "expand" else "成稿-压缩",
                chain_builder=build_draft_chain,
            )
            self._log_trace("成稿-正文", draft)
            followup_errors = validate_draft_length(
                draft,
                min_chars=generation["chapter_min_chars"],
                max_chars=generation["chapter_max_chars"],
            )
            if followup_errors:
                self._log_info(f"成稿字数仍未达标: {'; '.join(followup_errors)}")
        versions.append(self._archive_draft(output_path, draft, stage="draft"))
        self._log_info(f"章节成稿生成完成 字数={len(draft)} 输出={output_path}")
        return draft, versions

    def _rewrite_draft(
        self,
        *,
        prompt,
        output_path: Path,
        generation: Dict[str, Any],
        stream: bool,
        stage: str,
        chain_builder,
    ) -> str:
        if stream:
            try:
                llm = self._build_llm(
                    temperature=generation.get("temperature"),
                    top_p=generation.get("top_p"),
                    top_k=generation.get("top_k"),
                    streaming=True,
                )
                chain = chain_builder(prompt, llm)
                return self._stream_chain_to_file(chain, prompt, output_path, stage)
            except Exception:
                self._log_info("流式失败，回退为非流式")
        llm = self._build_llm(
            temperature=generation.get("temperature"),
            top_p=generation.get("top_p"),
            top_k=generation.get("top_k"),
            streaming=False,
        )
        chain = chain_builder(prompt, llm)
        result = self._invoke_chain(chain, prompt, stage=stage, response_title=None)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(result, encoding="utf-8")
        return result

    def _post_check(
        self,
        plan: Dict[str, Any],
        draft: str,
        generation: Dict[str, Any],
        world_references: str | None = None,
    ) -> Dict[str, Any]:
        post_prompt = build_post_check_prompt(plan, draft, world_references=world_references)
        llm = self._build_llm(
            temperature=generation.get("temperature"),
            top_p=generation.get("top_p"),
            top_k=generation.get("top_k"),
        )
        chain = build_post_check_chain(post_prompt, llm)
        raw = self._invoke_chain(chain, post_prompt, stage="修订-复核")
        post_check = self._parse_post_check(raw)
        if post_check is None:
            post_check = {}
        self._log_trace("修订-复核-解析后", json.dumps(post_check, ensure_ascii=False, indent=2))
        return post_check

    def _build_plan_seed(self, chapter: Dict[str, Any]) -> Dict[str, Any]:
        raw_cast = chapter.get("cast_hint")
        raw_beats = chapter.get("beats")
        raw_conflicts = chapter.get("conflicts")
        return {
            "chapter_id": str(chapter.get("id") or ""),
            "title": chapter.get("title"),
            "goal": chapter.get("summary") or chapter.get("goal"),
            "beats": raw_beats if isinstance(raw_beats, list) else [],
            "cast": raw_cast if isinstance(raw_cast, list) else [],
            "conflicts": raw_conflicts if isinstance(raw_conflicts, list) else [],
            "pacing_notes": chapter.get("pacing_notes") or chapter.get("rhythm"),
        }

    def _collect_contributions(
        self,
        *,
        plan: Dict[str, Any],
        chapter: Dict[str, Any],
        shared_style: str,
        previous_summary: str | None,
    ) -> Dict[str, Any]:
        generation = self.project["generation"]
        agents = self._resolve_agents(plan, chapter)
        self._log_info(
            "本章参与Agent: "
            + ", ".join(f"{agent.get('id')}({agent.get('name')})" for agent in agents)
        )
        concurrency = max(1, int(generation.get("agent_concurrency", 1)))
        contributions: Dict[str, Any] = {}
        if concurrency == 1 or len(agents) <= 1:
            for agent in agents:
                contribution = self._run_agent_contribution(
                    agent=agent,
                    plan=plan,
                    shared_style=shared_style,
                    previous_summary=previous_summary,
                    generation=generation,
                )
                contributions[agent["id"]] = contribution
            return contributions

        with ThreadPoolExecutor(max_workers=concurrency) as executor:
            futures = {
                executor.submit(
                    self._run_agent_contribution,
                    agent=agent,
                    plan=plan,
                    shared_style=shared_style,
                    previous_summary=previous_summary,
                    generation=generation,
                ): agent
                for agent in agents
            }
            for future in as_completed(futures):
                agent = futures[future]
                contribution = future.result()
                contributions[agent["id"]] = contribution
        return contributions

    def _run_agent_contribution(
        self,
        *,
        agent: Dict[str, Any],
        plan: Dict[str, Any],
        shared_style: str,
        previous_summary: str | None,
        generation: Dict[str, Any],
    ) -> Dict[str, Any]:
        style_guide = self._compose_style_guide(
            agent["id"],
            shared_style,
            component_ids=agent,
        )
        prompt = build_agent_contribution_prompt(
            agent=agent,
            plan=plan,
            style_guide=style_guide,
            previous_summary=previous_summary,
        )
        llm = self._build_llm(
            temperature=generation.get("temperature"),
            top_p=generation.get("top_p"),
            top_k=generation.get("top_k"),
        )
        chain = build_agent_contribution_chain(prompt, llm)
        self._log_info(f"Agent贡献开始 id={agent.get('id')} name={agent.get('name')}")
        raw = self._invoke_chain(chain, prompt, stage=f"Agent-{agent.get('id')}", response_title="响应")
        contribution = self._parse_contribution(raw)
        if not contribution:
            raise RuntimeError(f"Agent贡献解析失败: {agent.get('id')}")
        contribution = self._sanitize_contribution(contribution)
        self._log_info(
            f"Agent贡献完成 id={agent.get('id')} 字数={len(raw.strip())}"
        )
        return contribution

    def _sanitize_contribution(self, contribution: Dict[str, Any]) -> Dict[str, Any]:
        highlights = contribution.get("highlights")
        if not isinstance(highlights, list):
            return contribution
        sanitized_highlights = []
        removed_sensory_anchor = 0
        for highlight in highlights:
            if not isinstance(highlight, dict):
                sanitized_highlights.append(highlight)
                continue
            cleaned_highlight = {}
            for key, value in highlight.items():
                if key == "sensory_anchor":
                    removed_sensory_anchor += 1
                    continue
                cleaned_highlight[key] = value
            sanitized_highlights.append(cleaned_highlight)
        if removed_sensory_anchor:
            self._log_info(f"Agent贡献清洗: 移除 sensory_anchor 字段 {removed_sensory_anchor} 条")
        sanitized = dict(contribution)
        sanitized["highlights"] = sanitized_highlights
        return sanitized

    def _parse_plan(self, raw: str, generation: Dict[str, Any]) -> Dict[str, Any] | None:
        hint = (
            "字段: chapter_id, title, goal, beats(list), cast(list), conflicts(list), "
            "pacing_notes, word_target(数字)。"
            f"word_target 必须在 {generation['chapter_min_chars']} 到 {generation['chapter_max_chars']} 之间，"
            f"cast 数量 <= {generation['max_agents_per_chapter']}。"
        )
        return self._parse_json(raw, hint, lambda value: validate_plan(
            value,
            min_chars=generation["chapter_min_chars"],
            max_chars=generation["chapter_max_chars"],
            max_agents=generation["max_agents_per_chapter"],
        ))

    def _parse_post_check(self, raw: str) -> Dict[str, Any] | None:
        hint = "字段: summary, issues(list), suggestions(list), pacing_score(1-10)。"
        return self._parse_json(raw, hint, validate_post_check)

    def _parse_contribution(self, raw: str) -> Dict[str, Any] | None:
        hint = "字段: agent_id, name, highlights(list, 6-10 条)。"
        return self._parse_json(raw, hint, validate_contribution)

    def _parse_world_material_selection_batch(self, raw: str) -> Dict[str, Any] | None:
        hint = (
            "字段: decisions(list)。"
            "decisions 每项字段: material_name(string), use(bool), mode(full|excerpt|skip), selected_text(string), reason(string)。"
        )
        return self._parse_json(raw, hint, validate_world_material_selection_batch)

    def _parse_json(self, raw: str, schema_hint: str, validator) -> Dict[str, Any] | None:
        repair_llm = self._build_llm(temperature=0, top_p=1, top_k=None)
        current = raw
        for attempt in range(3):
            parsed = parse_json_with_repair(
                current,
                llm=repair_llm,
                schema_hint=schema_hint,
                max_attempts=1,
            )
            if not parsed:
                current = raw
                continue
            errors = validator(parsed)
            if not errors:
                return parsed
            schema_hint = f"{schema_hint}\n校验错误: {'; '.join(errors)}"
            current = json.dumps(parsed, ensure_ascii=False)
        return None

    def _prepare_world_references(
        self,
        *,
        chapter: Dict[str, Any],
        plan: Dict[str, Any],
        generation: Dict[str, Any],
    ) -> str:
        paths = self.project.get("paths", {})
        materials_dir = paths.get("world_materials_dir") or DEFAULT_WORLD_MATERIALS_DIR
        raw_exclude_patterns = paths.get("world_materials_exclude_patterns") or []
        exclude_patterns = raw_exclude_patterns if isinstance(raw_exclude_patterns, list) else []
        chapter_id = str(plan.get("chapter_id") or chapter.get("id") or "unknown")
        budget_chars = max(int(generation.get("chapter_max_chars", 3000)) * 4, 8000)
        selector_batch_chars = max(int(generation.get("world_selector_batch_chars", 150000)), 2000)
        manager = WorldReferenceManager(
            materials_dir=materials_dir,
            cache_root="data/world_refs",
            exclude_patterns=exclude_patterns,
            logger=self.logger,
        )

        def selector(payload: Dict[str, Any]) -> Dict[str, Any]:
            prompt = build_world_material_selector_prompt(
                chapter=payload["chapter"],
                plan=payload["plan"],
                materials=payload["materials"],
                remaining_budget_chars=int(payload.get("remaining_budget_chars", budget_chars)),
                batch_index=int(payload.get("batch_index", 1)),
                batch_total=int(payload.get("batch_total", 1)),
            )
            llm = self._build_llm(
                temperature=0.3,
                top_p=0.9,
                top_k=generation.get("top_k"),
            )
            chain = build_world_material_selector_chain(prompt, llm)
            stage = f"素材筛选-批次{payload.get('batch_index', 1)}"
            raw = self._invoke_chain(chain, prompt, stage=stage, response_title="响应")
            parsed = self._parse_world_material_selection_batch(raw)
            if parsed is None:
                self._log_info(f"素材筛选解析失败，跳过批次: {payload.get('batch_index', 1)}")
                return {"decisions": []}
            return parsed

        pack = manager.build_reference_pack(
            chapter_id=chapter_id,
            chapter=chapter,
            plan=plan,
            selector=selector,
            budget_chars=budget_chars,
            selector_batch_chars=selector_batch_chars,
        )
        entries = pack.get("entries", [])
        if entries:
            self._log_info(
                f"世界观素材筛选完成 chapter={chapter_id} selected={len(entries)} manifest={pack.get('manifest_path')}"
            )
        else:
            self._log_info(f"世界观素材筛选完成 chapter={chapter_id} selected=0")
        return str(pack.get("prompt_context") or "")

    def _build_chapter_context(
        self,
        *,
        outline: Dict[str, Any],
        current_chapter_id: str,
        state: Dict[str, Any],
        generation: Dict[str, Any],
    ) -> str:
        chapters = outline.get("chapters", [])
        if not chapters or not current_chapter_id:
            return ""
        ordered_previous_ids: list[str] = []
        for chapter in chapters:
            chapter_id = str(chapter.get("id") or "")
            if not chapter_id:
                continue
            if chapter_id == current_chapter_id:
                break
            ordered_previous_ids.append(chapter_id)
        generated_chapters: list[tuple[str, str, Path]] = []
        state_chapters = state.get("chapters", {})
        for chapter_id in ordered_previous_ids:
            chapter_state = state_chapters.get(chapter_id)
            if not isinstance(chapter_state, dict):
                continue
            file_value = chapter_state.get("file")
            if not file_value:
                continue
            chapter_path = Path(str(file_value))
            if not chapter_path.exists():
                continue
            chapter_title = str(chapter_state.get("title") or chapter_id)
            generated_chapters.append((chapter_id, chapter_title, chapter_path))
        if not generated_chapters:
            return ""

        lines: list[str] = ["读取策略：紧邻当前章节的前3章使用全文，其余章节使用剧情摘要。"]
        full_count = 3
        full_start_index = max(len(generated_chapters) - full_count, 0)
        for index, (chapter_id, chapter_title, chapter_path) in enumerate(generated_chapters):
            if index >= full_start_index:
                chapter_text = chapter_path.read_text(encoding="utf-8").strip()
                if not chapter_text:
                    continue
                lines.append(f"【第{chapter_id}章·{chapter_title}·全文】")
                lines.append(chapter_text)
                lines.append("")
                continue
            plot_summary = self._get_or_create_plot_summary(
                chapter_id=chapter_id,
                chapter_title=chapter_title,
                chapter_path=chapter_path,
                generation=generation,
            )
            if not plot_summary:
                continue
            lines.append(f"【第{chapter_id}章·{chapter_title}·剧情摘要】")
            lines.append(plot_summary)
            lines.append("")
        context = "\n".join(lines).strip()
        if context:
            self._log_info(
                f"章节连续性上下文构建完成 current={current_chapter_id} generated={len(generated_chapters)}"
            )
        return context

    def _invoke_chain(self, chain, prompt, *, stage: str, response_title: str | None = "响应(原文)") -> str:
        messages = prompt.format_messages()
        self._log_trace(f"{stage}-提示词", format_messages(messages))
        result = chain.invoke({})
        if response_title:
            self._log_trace(f"{stage}-{response_title}", result)
        return result

    def _stream_chain_to_file(self, chain, prompt, output_path: Path, stage: str) -> str:
        messages = prompt.format_messages()
        self._log_trace(f"{stage}-提示词", format_messages(messages))
        output_path.parent.mkdir(parents=True, exist_ok=True)
        chunks: list[str] = []
        with output_path.open("w", encoding="utf-8") as handle:
            for chunk in chain.stream({}):
                handle.write(chunk)
                handle.flush()
                chunks.append(chunk)
        return "".join(chunks)

    def _archive_draft(
        self,
        output_path: Path,
        draft: str,
        stage: str,
    ) -> Dict[str, Any]:
        history_dir = output_path.parent / "history"
        history_dir.mkdir(parents=True, exist_ok=True)
        label = self._next_version_label(history_dir, output_path, stage)
        history_path = history_dir / f"{output_path.stem}_{label}{output_path.suffix}"
        history_path.write_text(draft, encoding="utf-8")
        return {"path": str(history_path), "label": label, "stage": stage, "created_at": now_iso()}

    def _next_version_label(
        self,
        history_dir: Path,
        output_path: Path,
        stage: str,
    ) -> str:
        labels = self._collect_version_labels(history_dir, output_path)
        if stage == "revision":
            index = sum(1 for label in labels if label.startswith("修订")) + 1
            return f"修订{self._to_chinese_number(index)}"
        if stage == "final":
            index = sum(1 for label in labels if label.startswith("终审")) + 1
            if index == 1:
                return "终审"
            return f"终审{self._to_chinese_number(index)}"
        index = sum(1 for label in labels if label.startswith("成稿")) + 1
        if index == 1:
            return "成稿"
        return f"成稿{self._to_chinese_number(index)}"

    def _collect_version_labels(self, history_dir: Path, output_path: Path) -> list[str]:
        if not history_dir.exists():
            return []
        prefix = f"{output_path.stem}_"
        labels: list[str] = []
        for path in history_dir.glob(f"{output_path.stem}_*{output_path.suffix}"):
            stem = path.stem
            if stem.startswith(prefix):
                label = stem[len(prefix) :]
                if label:
                    labels.append(label)
        return labels

    def _to_chinese_number(self, value: int) -> str:
        digits = {
            0: "零",
            1: "一",
            2: "二",
            3: "三",
            4: "四",
            5: "五",
            6: "六",
            7: "七",
            8: "八",
            9: "九",
            10: "十",
        }
        if value <= 10:
            return digits.get(value, str(value))
        if value < 20:
            return f"十{digits[value - 10]}"
        tens, ones = divmod(value, 10)
        tens_part = f"{digits[tens]}十"
        if ones == 0:
            return tens_part
        return f"{tens_part}{digits[ones]}"

    def _load_agents(self) -> Dict[str, Any]:
        return load_yaml(self.project["paths"]["agents"])

    def _load_outline(self) -> Dict[str, Any]:
        return load_yaml(self.project["paths"]["outline"])

    def _load_style_guide_shared(self) -> str:
        return load_text(self.project["paths"]["style_guide_shared"])

    def _load_draft_examples(self) -> list[Dict[str, Any]]:
        path = self.project.get("paths", {}).get("style_guide_draft_examples")
        if not path:
            self._log_info("未配置成稿示例段落路径")
            return []
        try:
            draft_data = load_yaml(path)
        except FileNotFoundError:
            self._log_info(f"未找到成稿示例段落文件: {path}")
            return []
        if not isinstance(draft_data, dict):
            self._log_info(f"成稿示例段落配置格式错误: {path}")
            return []
        examples = draft_data.get("examples", [])
        if not isinstance(examples, list):
            self._log_info(f"成稿示例段落配置格式错误: {path}")
            return []
        return examples

    def _load_style_guide_agent(self, agent_id: str, stage: str | None = None) -> str:
        agents_dir = Path(self.project["paths"]["style_guide_agents_dir"])
        if stage:
            stage_path = agents_dir / agent_id / f"{stage}.md"
            if not stage_path.exists():
                self._log_info(f"未找到Agent阶段提示语文件: {stage_path}")
                return ""
            return load_text(stage_path)
        path = agents_dir / f"{agent_id}.md"
        if not path.exists():
            self._log_info(f"未找到Agent提示语文件: {path}")
            return ""
        return load_text(path)

    def _load_style_guide_component(self, component_type: str, component_id: str | None) -> str:
        if not component_id:
            return ""
        base_dir = Path(self.project["paths"]["style_guide_components_dir"])
        path = base_dir / component_type / f"{component_id}.md"
        if not path.exists():
            self._log_info(f"未找到组件提示语文件: {path}")
            return ""
        return load_text(path)

    def _compose_style_guide(
        self,
        agent_id: str,
        shared_style: str,
        component_ids: Dict[str, Any] | None = None,
        stage: str | None = None,
    ) -> str:
        parts = [self._load_style_guide_agent(agent_id, stage=stage)]
        if component_ids:
            parts.append(
                self._load_style_guide_component(
                    "personality",
                    component_ids.get("personality_id"),
                )
            )
            parts.append(
                self._load_style_guide_component(
                    "background",
                    component_ids.get("background_id"),
                )
            )
            parts.append(
                self._load_style_guide_component(
                    "identity",
                    component_ids.get("identity_id"),
                )
            )
        agent_style = "\n\n".join(part for part in parts if part)
        return compose_style_guide(agent_style, shared_style)

    def _load_state(self) -> Dict[str, Any]:
        return load_json(self.project["paths"]["state_path"], {"chapters": {}})

    def _save_state(self, state: Dict[str, Any]) -> None:
        save_json(self.project["paths"]["state_path"], state)

    def _select_chapter(self, outline: Dict[str, Any], chapter_id: str | None) -> Dict[str, Any]:
        chapters = outline.get("chapters", [])
        if not chapters:
            raise RuntimeError("No chapters found in outline.")
        if chapter_id:
            for chapter in chapters:
                if chapter["id"] == chapter_id:
                    return chapter
            raise RuntimeError(f"Chapter id not found: {chapter_id}")
        state = self._load_state()
        completed = state.get("chapters", {})
        for chapter in chapters:
            if chapter["id"] not in completed:
                return chapter
        return chapters[-1]

    def _previous_summary(self, state: Dict[str, Any]) -> str | None:
        if not state.get("chapters"):
            return None
        last_id = sorted(state["chapters"].keys())[-1]
        return state["chapters"][last_id].get("summary")

    def _resolve_agents(self, plan: Dict[str, Any], chapter: Dict[str, Any]) -> list[Dict[str, Any]]:
        agents_config = self._load_agents()
        agents = {}
        for agent in agents_config.get("agents", []):
            profile = self._build_agent_profile(agent)
            agents[agent["id"]] = profile
        extras = {}
        for extra in agents_config.get("extras", []):
            profile = self._build_agent_profile(extra)
            extras[extra["id"]] = profile
        cast_ids = plan.get("cast") or chapter.get("cast_hint") or []
        resolved = []
        for cid in cast_ids:
            if cid in agents:
                resolved.append(agents[cid])
            elif cid in extras:
                resolved.append(extras[cid])
        if not resolved:
            resolved = list(agents.values())[: self.project["generation"]["max_agents_per_chapter"]]
        return resolved

    def _build_agent_profile(
        self,
        agent: Dict[str, Any],
    ) -> Dict[str, Any]:
        return build_agent_profile(agent, None, None, None)

    def _chapter_output_path(self, plan: Dict[str, Any]) -> Path:
        output_dir = Path(self.project["paths"]["output_dir"])
        title = plan.get("title", "chapter")
        slug = slugify(title)
        return output_dir / f"{plan.get('chapter_id','0000')}_{slug}.md"

    def _save_plan(self, plan: Dict[str, Any]) -> None:
        plans_dir = Path(self.project["paths"]["plans_dir"])
        plans_dir.mkdir(parents=True, exist_ok=True)
        plan_path = plans_dir / f"{plan.get('chapter_id','0000')}.json"
        plan_path.write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")

    def _load_plan(self, chapter_id: str) -> Dict[str, Any] | None:
        plans_dir = Path(self.project["paths"]["plans_dir"])
        plan_path = plans_dir / f"{chapter_id}.json"
        if not plan_path.exists():
            return None
        return json.loads(plan_path.read_text(encoding="utf-8"))

    def _update_state(
        self,
        state: Dict[str, Any],
        plan: Dict[str, Any],
        output_path: Path,
        post_check: Dict[str, Any],
        versions: list[Dict[str, Any]] | None,
        plot_summary: str | None,
    ) -> Dict[str, Any]:
        chapters = state.setdefault("chapters", {})
        chapter_id = plan.get("chapter_id", "0000")
        existing_versions = chapters.get(chapter_id, {}).get("versions", [])
        merged_versions = existing_versions + (versions or [])
        chapters[chapter_id] = {
            "title": plan.get("title"),
            "file": str(output_path),
            "summary": post_check.get("summary"),
            "plot_summary": plot_summary or post_check.get("summary"),
            "issues": post_check.get("issues", []),
            "suggestions": post_check.get("suggestions", []),
            "pacing_score": post_check.get("pacing_score"),
            "versions": merged_versions,
            "updated_at": now_iso(),
        }
        return state

    def _plot_summary_cache_path(self) -> Path:
        paths = self.project.get("paths", {})
        cache_path = paths.get("plot_summary_cache_path") or "data/chapter_plot_summaries.json"
        return Path(str(cache_path))

    def _load_plot_summary_cache(self) -> Dict[str, Any]:
        data = load_json(self._plot_summary_cache_path(), {})
        if isinstance(data, dict):
            return data
        return {}

    def _save_plot_summary_cache(self, cache: Dict[str, Any]) -> None:
        save_json(self._plot_summary_cache_path(), cache)

    def _ensure_plot_summary_cached(
        self,
        *,
        chapter_id: str,
        chapter_title: str,
        chapter_text: str,
        generation: Dict[str, Any],
    ) -> str | None:
        chapter_id = str(chapter_id)
        cache = self._load_plot_summary_cache()
        cached = self._extract_cached_summary(cache, chapter_id)
        if cached:
            return cached
        generated = self._summarize_plot_for_chapter(
            chapter_id=chapter_id,
            chapter_title=chapter_title,
            chapter_text=chapter_text,
            generation=generation,
        )
        if not generated:
            return None
        cache[chapter_id] = {
            "summary": generated,
            "source": "llm_generated",
            "updated_at": now_iso(),
        }
        self._save_plot_summary_cache(cache)
        self._log_info(f"剧情摘要已写入缓存 chapter={chapter_id}")
        return generated

    def _get_or_create_plot_summary(
        self,
        *,
        chapter_id: str,
        chapter_title: str,
        chapter_path: Path,
        generation: Dict[str, Any],
    ) -> str | None:
        chapter_id = str(chapter_id)
        cache = self._load_plot_summary_cache()
        cached = self._extract_cached_summary(cache, chapter_id)
        if cached:
            return cached

        chapter_text = chapter_path.read_text(encoding="utf-8").strip()
        if not chapter_text:
            return None
        generated = self._summarize_plot_for_chapter(
            chapter_id=chapter_id,
            chapter_title=chapter_title,
            chapter_text=chapter_text,
            generation=generation,
        )
        if not generated:
            return None
        cache[chapter_id] = {
            "summary": generated,
            "source": "llm_generated",
            "updated_at": now_iso(),
        }
        self._save_plot_summary_cache(cache)
        self._log_info(f"剧情摘要已写入缓存 chapter={chapter_id}")
        return generated

    def _extract_cached_summary(self, cache: Dict[str, Any], chapter_id: str) -> str | None:
        entry = cache.get(chapter_id)
        if isinstance(entry, str) and entry.strip():
            return entry.strip()
        if isinstance(entry, dict):
            summary = entry.get("summary")
            if isinstance(summary, str) and summary.strip():
                return summary.strip()
        return None

    def _summarize_plot_for_chapter(
        self,
        *,
        chapter_id: str,
        chapter_title: str,
        chapter_text: str,
        generation: Dict[str, Any],
    ) -> str | None:
        prompt = build_chapter_plot_summary_prompt(
            chapter_id=chapter_id,
            chapter_title=chapter_title,
            chapter_text=chapter_text,
        )
        llm = self._build_llm(
            temperature=0.3,
            top_p=0.9,
            top_k=generation.get("top_k"),
            streaming=False,
        )
        chain = build_draft_chain(prompt, llm)
        raw = self._invoke_chain(chain, prompt, stage=f"剧情摘要-{chapter_id}", response_title="响应")
        summary = raw.strip()
        if not summary:
            return None
        if summary.startswith("```") and summary.endswith("```"):
            summary = summary.strip("`").strip()
        return summary

    def _build_rag_references(
        self,
        *,
        plan: Dict[str, Any],
        contributions: Dict[str, Any],
    ) -> str:
        rag_config = resolve_rag_config(self.project)
        if not rag_config.get("enabled"):
            return ""
        try:
            query = build_rag_query(plan, contributions)
            results = retrieve_rag_examples(
                project_config=self.project,
                query=query,
            )
        except Exception as exc:
            self._log_info(f"RAG 检索失败，跳过知识库参考: {exc}")
            return ""
        if not results:
            self._log_info("RAG 检索无结果，跳过知识库参考")
            return ""
        references = format_rag_references(results)
        if references:
            self._log_info(f"RAG 检索完成，命中片段数={len(results)}")
        return references

    def _build_llm(
        self,
        *,
        temperature: float | None,
        top_p: float | None,
        top_k: int | None,
        streaming: bool = False,
    ):
        return self.client.build_llm(
            temperature=temperature,
            top_p=top_p,
            top_k=top_k,
            streaming=streaming,
        )

    def _log_info(self, message: str) -> None:
        if self.logger:
            self.logger.info(message)

    def _log_trace(self, title: str, content: str) -> None:
        if self.logger:
            self.logger.trace_block(title, content)
