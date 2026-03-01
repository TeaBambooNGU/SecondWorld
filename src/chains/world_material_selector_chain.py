from __future__ import annotations

from langchain_core.output_parsers import StrOutputParser


def build_world_material_selector_chain(prompt, llm):
    return prompt | llm | StrOutputParser()
