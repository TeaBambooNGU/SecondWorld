from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Optional

from .config_loader import get_api_key, load_env, load_text, load_yaml
from .deepseek_client import DeepSeekClient
from .prompting import (
    build_agent_contribution_prompt,
    build_director_draft_prompt,
    build_director_final_prompt,
    build_director_plan_prompt,
    build_director_revision_prompt,
    build_post_check_prompt,
    compose_style_guide,
)
from .utils import (
    FileLogger,
    build_agent_profile,
    extract_json,
    load_json,
    now_iso,
    save_json,
    slugify,
)


class ChapterPipeline:
    def __init__(
        self,
        project_path: str = "config/project.yaml",
        logger: FileLogger | None = None,
    ) -> None:
        load_env()
        self.project_path = project_path
        self.project = load_yaml(project_path)
        self.api_key = get_api_key(self.project)
        api = self.project["api"]
        self.logger = logger
        self.client = DeepSeekClient(
            base_url=api["base_url"],
            api_key=self.api_key,
            model=api["model"],
            timeout_sec=api.get("timeout_sec", 120),
            max_retries=api.get("max_retries", 3),
        )

    def run_plan(self, chapter_id: str | None = None) -> Dict[str, Any]:
        outline = self._load_outline()
        chapter = self._select_chapter(outline, chapter_id)
        shared_style = self._load_style_guide_shared()
        style_guide = self._compose_style_guide("director", shared_style, stage="plan")
        state = self._load_state()
        previous_summary = self._previous_summary(state)
        generation = self.project["generation"]

        self._log_info(f"开始生成计划 chapter={chapter.get('id')} title={chapter.get('title')}")
        messages = build_director_plan_prompt(
            outline=outline,
            chapter=chapter,
            style_guide=style_guide,
            previous_summary=previous_summary,
            max_agents=generation["max_agents_per_chapter"],
            chapter_min_chars=generation["chapter_min_chars"],
            chapter_max_chars=generation["chapter_max_chars"],
        )
        self._log_trace("计划-提示词", self._format_messages(messages))
        response = self.client.chat(
            messages,
            temperature=generation["temperature"],
            top_p=generation["top_p"],
            stream=False,
        )
        self._log_trace("计划-响应(原文)", response)
        plan = self._parse_json_response(response)
        if not plan:
            self._log_info("计划解析失败")
            raise RuntimeError("Failed to parse chapter plan JSON.")
        self._save_plan(plan)
        self._log_trace("计划-解析后", json.dumps(plan, ensure_ascii=False, indent=2))
        self._log_info(f"计划生成完成 chapter={plan.get('chapter_id')} title={plan.get('title')}")
        return plan

    def run_chapter(
        self,
        chapter_id: str | None = None,
        stream_override: Optional[bool] = None,
        force: bool = False,
    ) -> Dict[str, Any]:
        outline = self._load_outline()
        chapter = self._select_chapter(outline, chapter_id)
        shared_style = self._load_style_guide_shared()
        state = self._load_state()
        previous_summary = self._previous_summary(state)
        generation = self.project["generation"]
        api = self.project["api"]

        plan = self._load_plan(chapter["id"])
        if plan:
            self._log_info(f"使用已有计划 chapter={chapter.get('id')} title={chapter.get('title')}")
        else:
            self._log_info(f"未找到计划，开始生成 chapter={chapter.get('id')} title={chapter.get('title')}")
            plan = self.run_plan(chapter["id"])

        contributions = {}
        versions: list[Dict[str, Any]] = []
        agents = self._resolve_agents(plan, chapter)
        self._log_info(
            "本章参与Agent: "
            + ", ".join(f"{agent.get('id')}({agent.get('name')})" for agent in agents)
        )
        for agent in agents:
            style_guide = self._compose_style_guide(
                agent["id"],
                shared_style,
                component_ids=agent,
            )
            messages = build_agent_contribution_prompt(
                agent=agent,
                plan=plan,
                style_guide=style_guide,
                previous_summary=previous_summary,
            )
            self._log_info(f"Agent贡献开始 id={agent.get('id')} name={agent.get('name')}")
            self._log_trace(
                f"Agent-{agent.get('id')}-提示词",
                self._format_messages(messages),
            )
            response = self.client.chat(
                messages,
                temperature=generation["temperature"],
                top_p=generation["top_p"],
                stream=False,
            )
            contributions[agent["id"]] = response.strip()
            self._log_trace(f"Agent-{agent.get('id')}-响应", response.strip())
            self._log_info(
                f"Agent贡献完成 id={agent.get('id')} 字数={len(response.strip())}"
            )

        stream = api.get("stream", False) if stream_override is None else stream_override
        style_guide = self._compose_style_guide("director", shared_style, stage="draft")
        messages = build_director_draft_prompt(
            plan=plan,
            contributions=contributions,
            style_guide=style_guide,
            chapter_min_chars=generation["chapter_min_chars"],
            chapter_max_chars=generation["chapter_max_chars"],
        )
        self._log_trace("成稿-提示词", self._format_messages(messages))

        output_path = self._chapter_output_path(plan)
        if output_path.exists() and not force:
            raise RuntimeError(f"Chapter file exists: {output_path}")

        self._log_info(f"开始生成章节成稿 stream={stream}")
        draft = self._write_draft(output_path, messages, generation, stream)
        self._log_trace("成稿-正文", draft)
        versions.append(self._archive_draft(output_path, draft, stage="draft"))
        self._log_info(f"章节成稿生成完成 字数={len(draft)} 输出={output_path}")

        post_messages = build_post_check_prompt(plan, draft)
        self._log_trace("修订-复核-提示词", self._format_messages(post_messages))
        post_response = self.client.chat(
            post_messages,
            temperature=generation["temperature"],
            top_p=generation["top_p"],
            stream=False,
        )
        self._log_trace("修订-复核-响应(原文)", post_response)
        post_check = self._parse_json_response(post_response) or {}
        self._log_trace("修订-复核-解析后", json.dumps(post_check, ensure_ascii=False, indent=2))

        if generation.get("max_turns", 1) > 1 and post_check.get("suggestions"):
            style_guide = self._compose_style_guide("director", shared_style, stage="revision")
            revision_messages = build_director_revision_prompt(
                plan=plan,
                draft=draft,
                post_check=post_check,
                style_guide=style_guide,
                chapter_min_chars=generation["chapter_min_chars"],
                chapter_max_chars=generation["chapter_max_chars"],
            )
            self._log_trace("修订-改稿-提示词", self._format_messages(revision_messages))
            draft = self._write_draft(output_path, revision_messages, generation, stream)
            self._log_trace("修订-改稿-正文", draft)
            versions.append(self._archive_draft(output_path, draft, stage="revision"))

        style_guide = self._compose_style_guide("director", shared_style, stage="final")
        final_messages = build_director_final_prompt(
            plan=plan,
            draft=draft,
            style_guide=style_guide,
            chapter_min_chars=generation["chapter_min_chars"],
            chapter_max_chars=generation["chapter_max_chars"],
        )
        self._log_trace("终审-提示词", self._format_messages(final_messages))
        draft = self._write_draft(output_path, final_messages, generation, stream)
        self._log_trace("终审-正文", draft)
        versions.append(self._archive_draft(output_path, draft, stage="final"))
        self._log_info(f"终审完成 字数={len(draft)} 输出={output_path}")

        state = self._update_state(state, plan, output_path, post_check, versions)
        self._save_state(state)
        return {"plan": plan, "draft_path": str(output_path), "post_check": post_check}

    def _write_draft(
        self,
        output_path: Path,
        messages,
        generation: Dict[str, Any],
        stream: bool,
    ) -> str:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        if stream:
            chunks = []
            with output_path.open("w", encoding="utf-8") as handle:
                for chunk in self.client.chat(
                    messages,
                    temperature=generation["temperature"],
                    top_p=generation["top_p"],
                    stream=True,
                ):
                    handle.write(chunk)
                    handle.flush()
                    chunks.append(chunk)
            return "".join(chunks)

        draft = self.client.chat(
            messages,
            temperature=generation["temperature"],
            top_p=generation["top_p"],
            stream=False,
        )
        output_path.write_text(draft, encoding="utf-8")
        return draft

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

    def _parse_json_response(self, response: str) -> Dict[str, Any] | None:
        json_text = extract_json(response)
        if not json_text:
            return None
        try:
            return json.loads(json_text)
        except json.JSONDecodeError:
            return None

    def _update_state(
        self,
        state: Dict[str, Any],
        plan: Dict[str, Any],
        output_path: Path,
        post_check: Dict[str, Any],
        versions: list[Dict[str, Any]] | None,
    ) -> Dict[str, Any]:
        chapters = state.setdefault("chapters", {})
        chapter_id = plan.get("chapter_id", "0000")
        existing_versions = chapters.get(chapter_id, {}).get("versions", [])
        merged_versions = existing_versions + (versions or [])
        chapters[chapter_id] = {
            "title": plan.get("title"),
            "file": str(output_path),
            "summary": post_check.get("summary"),
            "issues": post_check.get("issues", []),
            "suggestions": post_check.get("suggestions", []),
            "pacing_score": post_check.get("pacing_score"),
            "versions": merged_versions,
            "updated_at": now_iso(),
        }
        return state

    def _log_info(self, message: str) -> None:
        if self.logger:
            self.logger.info(message)

    def _log_trace(self, title: str, content: str) -> None:
        if self.logger:
            self.logger.trace_block(title, content)

    def _format_messages(self, messages) -> str:
        blocks = []
        for message in messages:
            role = message.get("role", "unknown")
            content = message.get("content", "")
            blocks.append(f"[{role}]\n{content}")
        return "\n\n".join(blocks)
