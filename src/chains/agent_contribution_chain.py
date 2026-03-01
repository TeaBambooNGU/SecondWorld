from __future__ import annotations

from langchain_core.output_parsers import StrOutputParser


def build_agent_contribution_chain(prompt, llm):
    return prompt | llm | StrOutputParser()
