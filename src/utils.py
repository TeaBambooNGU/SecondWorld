from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict


def read_text(path: str | Path) -> str:
    return Path(path).read_text(encoding="utf-8")


def write_text(path: str | Path, content: str) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def ensure_dir(path: str | Path) -> Path:
    path = Path(path)
    path.mkdir(parents=True, exist_ok=True)
    return path


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def slugify(value: str) -> str:
    value = value.lower()
    value = re.sub(r"[^a-z0-9\-\s]", "", value)
    value = re.sub(r"[\s\-]+", "-", value).strip("-")
    return value or "chapter"


def extract_json(text: str) -> str | None:
    candidates: list[str] = []

    fenced_blocks = re.findall(r"```(?:json|JSON)\s*([\s\S]*?)```", text)
    for block in fenced_blocks:
        candidate = _extract_balanced_json_object(block)
        if candidate:
            candidates.append(candidate)

    generic_blocks = re.findall(r"```\s*([\s\S]*?)```", text)
    for block in generic_blocks:
        candidate = _extract_balanced_json_object(block)
        if candidate:
            candidates.append(candidate)

    candidates.extend(_extract_balanced_json_objects(text))

    if not candidates:
        return None
    return candidates[-1]


def _extract_balanced_json_object(text: str) -> str | None:
    objects = _extract_balanced_json_objects(text)
    if not objects:
        return None
    return objects[0]


def _extract_balanced_json_objects(text: str) -> list[str]:
    objects: list[str] = []
    depth = 0
    start: int | None = None
    in_string = False
    escaped = False

    for idx, char in enumerate(text):
        if in_string:
            if escaped:
                escaped = False
                continue
            if char == "\\":
                escaped = True
                continue
            if char == '"':
                in_string = False
            continue

        if char == '"':
            in_string = True
            continue
        if char == "{":
            if depth == 0:
                start = idx
            depth += 1
            continue
        if char == "}" and depth > 0:
            depth -= 1
            if depth == 0 and start is not None:
                objects.append(text[start : idx + 1])
                start = None

    return objects


def extract_forbidden_terms(text: str) -> list[str]:
    terms: list[str] = []
    in_list = False
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if "不要使用的高频网文词" in stripped:
            in_list = True
            continue
        if in_list and stripped.startswith("#"):
            break
        if not in_list:
            continue
        if not stripped.startswith("-"):
            continue
        content = stripped.lstrip("-").strip()
        if not content:
            continue
        parts = re.split(r"[、,，;；]+", content)
        for part in parts:
            term = part.strip().strip("、,，;；。.")
            if term:
                terms.append(term)
    seen: set[str] = set()
    deduped: list[str] = []
    for term in terms:
        if term in seen:
            continue
        seen.add(term)
        deduped.append(term)
    return deduped


def find_forbidden_terms(text: str, terms: list[str]) -> list[str]:
    hits: list[str] = []
    for term in terms:
        if term and term in text:
            hits.append(term)
    return list(dict.fromkeys(hits))


def escape_prompt_template(text: str) -> str:
    return text.replace("{", "{{").replace("}", "}}")


def load_json(path: str | Path, default: Any) -> Any:
    path = Path(path)
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def save_json(path: str | Path, data: Any) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def build_agent_profile(
    agent: Dict[str, Any],
    personality: Dict[str, Any] | None,
    background: Dict[str, Any] | None,
    identity: Dict[str, Any] | None,
) -> Dict[str, Any]:
    profile = {
        "id": agent.get("id"),
        "name": agent.get("id"),
        "type": agent.get("type"),
        "archetype": agent.get("archetype"),
        "personality_id": agent.get("personality_id"),
        "background_id": agent.get("background_id"),
        "identity_id": agent.get("identity_id"),
        "traits": agent.get("traits"),
        "personality": personality or {},
        "background": background or {},
        "identity": identity or {},
    }
    return _clean_dict(profile)


def _clean_dict(data: Dict[str, Any]) -> Dict[str, Any]:
    cleaned: Dict[str, Any] = {}
    for key, value in data.items():
        if value is None:
            continue
        if isinstance(value, str) and not value.strip():
            continue
        if isinstance(value, list) and not value:
            continue
        if isinstance(value, dict) and not value:
            continue
        cleaned[key] = value
    return cleaned


class FileLogger:
    def __init__(self, path: str | Path, trace: bool = False) -> None:
        self.path = Path(path)
        self.trace = trace
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def info(self, message: str) -> None:
        self._write(f"[{now_iso()}] INFO {message}\n")

    def trace_block(self, title: str, content: str) -> None:
        if not self.trace:
            return
        block = f"\n===== {title} =====\n{content}\n===== END {title} =====\n"
        self._write(block)

    def _write(self, content: str) -> None:
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(content)
