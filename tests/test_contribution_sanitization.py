from src.langchain_pipeline import LangChainPipeline


def test_sanitize_contribution_removes_sensory_anchor():
    pipeline = LangChainPipeline.__new__(LangChainPipeline)
    pipeline.logger = None
    contribution = {
        "agent_id": "于皓",
        "name": "于皓",
        "highlights": [
            {
                "sequence": 1,
                "content": "于皓盯着后门没说话。",
                "sensory_anchor": "脚下像踩冷豆腐。",
            },
            {
                "sequence": 2,
                "content": "张福海抬手示意他别动。",
            },
        ],
    }

    sanitized = pipeline._sanitize_contribution(contribution)

    assert "sensory_anchor" not in sanitized["highlights"][0]
    assert sanitized["highlights"][0]["content"] == "于皓盯着后门没说话。"
    assert sanitized["highlights"][1]["content"] == "张福海抬手示意他别动。"

