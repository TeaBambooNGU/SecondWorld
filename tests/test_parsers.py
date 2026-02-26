import json

from src.parsers import parse_json_with_repair
from src.utils import extract_json


def test_extract_json_prefers_fenced_json_block():
    content = """
前置说明
```json
{
  "chapter_id": "0003",
  "meta": {"key": "value"}
}
```
后置说明
"""
    extracted = extract_json(content)
    assert extracted is not None
    parsed = json.loads(extracted)
    assert parsed["chapter_id"] == "0003"
    assert parsed["meta"]["key"] == "value"


def test_parse_json_with_repair_handles_unescaped_quotes_in_value():
    content = """```json
{
  "chapter_id": "0003",
  "title": "夜探锦灰阁",
  "goal": "打手在门口说了句"没动静"后离开",
  "beats": [],
  "cast": [],
  "conflicts": [],
  "pacing_notes": "紧绷推进",
  "word_target": 3500
}
```"""
    parsed = parse_json_with_repair(
        content,
        llm=None,
        schema_hint="",
        max_attempts=0,
    )
    assert parsed is not None
    assert parsed["goal"] == '打手在门口说了句"没动静"后离开'
