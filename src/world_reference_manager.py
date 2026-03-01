from __future__ import annotations

import fnmatch
import re
from pathlib import Path
from typing import Any, Callable, Dict, List

from .utils import save_json

SUPPORTED_EXTENSIONS = {".md", ".txt"}
DEFAULT_SELECTOR_BATCH_CHARS = 24000


class WorldReferenceManager:
    def __init__(
        self,
        *,
        materials_dir: str | Path,
        cache_root: str | Path,
        exclude_patterns: List[str] | None = None,
        logger=None,
    ) -> None:
        self.materials_dir = Path(materials_dir)
        self.cache_root = Path(cache_root)
        self.exclude_patterns = [str(item).strip() for item in (exclude_patterns or []) if str(item).strip()]
        self.logger = logger

    def build_reference_pack(
        self,
        *,
        chapter_id: str,
        chapter: Dict[str, Any],
        plan: Dict[str, Any],
        selector: Callable[[Dict[str, Any]], Dict[str, Any] | List[Dict[str, Any]]],
        budget_chars: int,
        selector_batch_chars: int = DEFAULT_SELECTOR_BATCH_CHARS,
    ) -> Dict[str, Any]:
        if not self.materials_dir.exists():
            self._log(f"世界观素材目录不存在，跳过: {self.materials_dir}")
            return {"entries": [], "prompt_context": "", "manifest_path": None}

        files = self._discover_material_files()
        if not files:
            self._log(f"世界观素材目录为空，跳过: {self.materials_dir}")
            return {"entries": [], "prompt_context": "", "manifest_path": None}

        keywords = self._build_keywords(plan, chapter)
        ranked_materials = self._rank_materials(files, keywords)
        if not ranked_materials:
            return {"entries": [], "prompt_context": "", "manifest_path": None}

        chapter_cache_dir = self.cache_root / chapter_id
        chapter_cache_dir.mkdir(parents=True, exist_ok=True)

        selected_entries: List[Dict[str, Any]] = []
        used_chars = 0

        batches = self._split_material_batches(
            ranked_materials,
            max(2000, int(selector_batch_chars)),
        )

        for batch_index, batch in enumerate(batches, start=1):
            if selected_entries and used_chars >= budget_chars:
                break

            payload = {
                "chapter": chapter,
                "plan": plan,
                "remaining_budget_chars": max(budget_chars - used_chars, 0),
                "batch_index": batch_index,
                "batch_total": len(batches),
                "materials": [
                    {
                        "material_name": material["name"],
                        "material_path": material["path"],
                        "material_text": material["text"],
                    }
                    for material in batch
                ],
            }
            decisions = selector(payload)
            decision_map = self._normalize_decisions(decisions)

            for material in batch:
                normalized = decision_map.get(
                    material["name"],
                    {
                        "use": False,
                        "mode": "skip",
                        "selected_text": "",
                        "reason": "",
                    },
                )
                if not normalized["use"] or normalized["mode"] == "skip":
                    continue

                content = material["text"] if normalized["mode"] == "full" else normalized["selected_text"]
                content = content.strip()
                if not content:
                    continue

                if selected_entries and used_chars + len(content) > budget_chars:
                    remaining = budget_chars - used_chars
                    if remaining <= 0:
                        break
                    content = content[:remaining].strip()
                    if not content:
                        break

                index = len(selected_entries) + 1
                cache_file = chapter_cache_dir / f"{index:02d}_{material['name']}"
                cache_file.write_text(content, encoding="utf-8")

                entry = {
                    "index": index,
                    "source_path": material["path"],
                    "cache_path": str(cache_file),
                    "mode": normalized["mode"],
                    "score": material["score"],
                    "chars": len(content),
                    "reason": normalized["reason"],
                }
                selected_entries.append(entry)
                used_chars += len(content)

        manifest_path = chapter_cache_dir / "manifest.json"
        manifest = {
            "chapter_id": chapter_id,
            "materials_dir": str(self.materials_dir),
            "budget_chars": budget_chars,
            "used_chars": used_chars,
            "entries": selected_entries,
        }
        save_json(manifest_path, manifest)

        prompt_context = self._build_prompt_context(selected_entries)
        return {
            "entries": selected_entries,
            "prompt_context": prompt_context,
            "manifest_path": str(manifest_path),
        }

    def _discover_material_files(self) -> List[Path]:
        files: List[Path] = []
        # 仅扫描素材目录的当前层级，不递归进入子目录。
        for path in sorted(self.materials_dir.iterdir()):
            if not path.is_file():
                continue
            if path.suffix.lower() not in SUPPORTED_EXTENSIONS:
                continue
            if self._is_excluded(path.name):
                continue
            files.append(path)
        return files

    def _is_excluded(self, file_name: str) -> bool:
        normalized_name = file_name.casefold()
        for pattern in self.exclude_patterns:
            # 使用大小写不敏感匹配，避免 CLAUDE.md 无法过滤 Claude.md。
            if fnmatch.fnmatchcase(normalized_name, pattern.casefold()):
                return True
        return False

    def _build_keywords(self, plan: Dict[str, Any], chapter: Dict[str, Any]) -> List[str]:
        candidates: List[str] = []
        fields = [
            chapter.get("title"),
            chapter.get("summary"),
            plan.get("title"),
            plan.get("goal"),
            plan.get("pacing_notes"),
        ]
        for value in fields:
            if isinstance(value, str):
                candidates.extend(_tokenize(value))

        for item in plan.get("beats", []):
            if isinstance(item, str):
                candidates.extend(_tokenize(item))
        for item in plan.get("conflicts", []):
            if isinstance(item, str):
                candidates.extend(_tokenize(item))
        for item in plan.get("cast", []):
            if isinstance(item, str):
                candidates.extend(_tokenize(item))
        deduped: List[str] = []
        seen: set[str] = set()
        for token in candidates:
            if token in seen:
                continue
            seen.add(token)
            deduped.append(token)
        return deduped

    def _rank_materials(self, files: List[Path], keywords: List[str]) -> List[Dict[str, Any]]:
        ranked: List[Dict[str, Any]] = []
        for file_path in files:
            text = file_path.read_text(encoding="utf-8")
            score = _score_text(file_path.name + "\n" + text, keywords)
            ranked.append(
                {
                    "name": file_path.name,
                    "path": str(file_path),
                    "text": text,
                    "score": score,
                }
            )
        ranked.sort(key=lambda item: (item["score"], -len(item["name"])), reverse=True)
        return ranked

    def _split_material_batches(
        self,
        materials: List[Dict[str, Any]],
        max_batch_chars: int,
    ) -> List[List[Dict[str, Any]]]:
        batches: List[List[Dict[str, Any]]] = []
        current: List[Dict[str, Any]] = []
        current_chars = 0
        for material in materials:
            estimated_chars = len(material["name"]) + len(material["text"]) + 200
            if current and current_chars + estimated_chars > max_batch_chars:
                batches.append(current)
                current = []
                current_chars = 0
            current.append(material)
            current_chars += estimated_chars
        if current:
            batches.append(current)
        return batches

    def _normalize_decisions(
        self,
        decisions: Dict[str, Any] | List[Dict[str, Any]] | None,
    ) -> Dict[str, Dict[str, Any]]:
        if isinstance(decisions, dict):
            raw_items = decisions.get("decisions")
        else:
            raw_items = decisions
        if not isinstance(raw_items, list):
            return {}
        normalized_map: Dict[str, Dict[str, Any]] = {}
        for item in raw_items:
            if not isinstance(item, dict):
                continue
            name = str(item.get("material_name") or "").strip()
            if not name:
                continue
            normalized_map[name] = self._normalize_decision(item)
        return normalized_map

    def _normalize_decision(self, decision: Dict[str, Any] | None) -> Dict[str, Any]:
        if not isinstance(decision, dict):
            return {
                "use": False,
                "mode": "skip",
                "selected_text": "",
                "reason": "",
            }
        use = bool(decision.get("use"))
        mode = str(decision.get("mode") or "skip").strip().lower()
        if mode not in {"full", "excerpt", "skip"}:
            mode = "skip"
        selected_text = str(decision.get("selected_text") or "")
        reason = str(decision.get("reason") or "")
        return {
            "use": use,
            "mode": mode,
            "selected_text": selected_text,
            "reason": reason,
        }

    def _build_prompt_context(self, entries: List[Dict[str, Any]]) -> str:
        if not entries:
            return ""
        blocks: List[str] = []
        for entry in entries:
            cache_path = Path(entry["cache_path"])
            content = cache_path.read_text(encoding="utf-8").strip()
            if not content:
                continue
            blocks.append(
                "\n".join(
                    [
                        f"[素材{entry['index']}] 文件: {cache_path.name}",
                        f"来源: {entry['source_path']}",
                        f"模式: {entry['mode']}",
                        content,
                    ]
                )
            )
        return "\n\n".join(blocks)

    def _log(self, message: str) -> None:
        if self.logger:
            self.logger.info(message)


def _tokenize(text: str) -> List[str]:
    tokens = [token.strip() for token in re.split(r"[\s,，。！？；：、()（）【】\[\]《》<>\-_/]+", text)]
    filtered: List[str] = []
    for token in tokens:
        if len(token) < 2:
            continue
        filtered.append(token)
    return filtered


def _score_text(text: str, keywords: List[str]) -> int:
    if not keywords:
        return 0
    score = 0
    for keyword in keywords:
        if not keyword:
            continue
        occurrences = text.count(keyword)
        if occurrences > 0:
            score += min(occurrences, 5)
    return score
