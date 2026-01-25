from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict

import yaml
from dotenv import load_dotenv


def load_yaml(path: str | Path) -> Dict[str, Any]:
    return yaml.safe_load(Path(path).read_text(encoding="utf-8"))


def load_text(path: str | Path) -> str:
    return Path(path).read_text(encoding="utf-8")


def load_env() -> None:
    root_env = Path(".env")
    config_env = Path("config/.env")
    if root_env.exists():
        load_dotenv(root_env)
    elif config_env.exists():
        load_dotenv(config_env)
    _enable_langsmith_tracing()


def _enable_langsmith_tracing() -> None:
    api_key = os.getenv("LANGSMITH_API_KEY")
    tracing = os.getenv("LANGSMITH_TRACING")
    if api_key and not tracing:
        os.environ["LANGSMITH_TRACING"] = "true"


def get_api_key(project_config: Dict[str, Any]) -> str:
    api_env = project_config["api"]["api_key_env"]
    api_key = os.getenv(api_env)
    if not api_key:
        raise RuntimeError(f"Missing API key in env var: {api_env}")
    return api_key
