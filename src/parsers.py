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
    try:
        value = json.loads(json_text)
    except json.JSONDecodeError:
        return None
    if not isinstance(value, dict):
        return None
    return value


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
