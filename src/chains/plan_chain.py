from __future__ import annotations

from langchain_core.output_parsers import StrOutputParser


def build_plan_chain(prompt, llm):
    return prompt | llm | StrOutputParser()
