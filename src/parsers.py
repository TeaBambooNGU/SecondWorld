from __future__ import annotations

import json
from typing import Any, Dict

from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate

from .utils import extract_json


_FIX_PROMPT = ChatPromptTemplate.from_messages(
    [
        (
            "system",
            "你是 JSON 修复器，只输出严格 JSON，不要解释。",
        ),
        (
            "user",
            "请将以下内容修复为严格 JSON。必须只输出 JSON。\n\n"
            "期望结构/字段说明：\n{schema_hint}\n\n"
            "原始内容：\n{content}\n",
        ),
    ]
)


def _try_parse_json(text: str) -> Dict[str, Any] | None:
    json_text = extract_json(text)
    if not json_text:
        return None
    parsed = _load_json_dict(json_text)
    if parsed:
        return parsed

    repaired_text = _escape_unescaped_quotes_in_strings(json_text)
    if repaired_text == json_text:
        return None
    return _load_json_dict(repaired_text)


def _load_json_dict(text: str) -> Dict[str, Any] | None:
    try:
        value = json.loads(text)
    except json.JSONDecodeError:
        return None
    if not isinstance(value, dict):
        return None
    return value


def _escape_unescaped_quotes_in_strings(text: str) -> str:
    chars: list[str] = []
    in_string = False
    escaped = False

    for idx, char in enumerate(text):
        if not in_string:
            chars.append(char)
            if char == '"':
                in_string = True
            continue

        if escaped:
            chars.append(char)
            escaped = False
            continue
        if char == "\\":
            chars.append(char)
            escaped = True
            continue
        if char == '"':
            next_char = _next_non_whitespace_char(text, idx + 1)
            if next_char in {",", "}", "]", ":"} or next_char is None:
                chars.append(char)
                in_string = False
            else:
                chars.append('\\"')
            continue
        if char == "\n":
            chars.append("\\n")
            continue
        if char == "\r":
            chars.append("\\r")
            continue
        chars.append(char)

    return "".join(chars)


def _next_non_whitespace_char(text: str, start: int) -> str | None:
    for idx in range(start, len(text)):
        char = text[idx]
        if not char.isspace():
            return char
    return None


def repair_json_text(llm, content: str, schema_hint: str) -> str:
    chain = _FIX_PROMPT | llm | StrOutputParser()
    return chain.invoke({"content": content, "schema_hint": schema_hint})


def parse_json_with_repair(
    content: str,
    *,
    llm,
    schema_hint: str,
    max_attempts: int = 2,
) -> Dict[str, Any] | None:
    current = content
    for attempt in range(max_attempts + 1):
        parsed = _try_parse_json(current)
        if parsed:
            return parsed
        if attempt >= max_attempts:
            break
        current = repair_json_text(llm, current, schema_hint)
    return None
