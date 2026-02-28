from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime

from .config_loader import load_env, load_yaml
from .langchain_pipeline import LangChainPipeline
from .rag.service import build_rag_index
from .utils import FileLogger, load_json


class _StdoutProgressLogger:
    def info(self, message: str) -> None:
        print(message, flush=True)


def _resolve_default_chapter_id(config_path: str) -> str:
    project = load_yaml(config_path)
    outline = load_yaml(project["paths"]["outline"])
    chapters = outline.get("chapters", [])
    if not chapters:
        raise RuntimeError("No chapters found in outline.")
    state = load_json(project["paths"]["state_path"], {"chapters": {}})
    completed = state.get("chapters", {})
    for chapter in chapters:
        if chapter["id"] not in completed:
            return chapter["id"]
    return chapters[-1]["id"]


def _default_trace_log_path(config_path: str, chapter_id: str | None) -> str:
    resolved_chapter_id = chapter_id or _resolve_default_chapter_id(config_path)
    timestamp = datetime.now().strftime("%Y-%m-%d_%H:%M:%S")
    return f"logs/trace_{resolved_chapter_id}_{timestamp}.log"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Multi-agent novel drafting CLI")
    parser.add_argument(
        "--config",
        default="config/project.yaml",
        help="Path to project config YAML",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    plan_parser = subparsers.add_parser("plan", help="Generate a chapter plan")
    plan_parser.add_argument("--chapter", help="Chapter id to plan")
    plan_parser.add_argument(
        "--trace",
        action="store_true",
        help="Write full prompt/response trace to a log file",
    )
    plan_parser.add_argument(
        "--log-file",
        default=None,
        help="Path to trace log file (default: logs/trace_{chapter}_{YYYY-MM-DD_HH:mm:ss}.log when --trace is set)",
    )

    chapter_parser = subparsers.add_parser("chapter", help="Generate a chapter draft")
    chapter_parser.add_argument("--chapter", help="Chapter id to draft")
    chapter_parser.add_argument("--no-stream", action="store_true", help="Disable streaming output")
    chapter_parser.add_argument("--force", action="store_true", help="Overwrite existing draft")
    chapter_parser.add_argument(
        "--trace",
        action="store_true",
        help="Write full prompt/response trace to a log file",
    )
    chapter_parser.add_argument(
        "--log-file",
        default=None,
        help="Path to trace log file (default: logs/trace_{chapter}_{YYYY-MM-DD_HH:mm:ss}.log when --trace is set)",
    )

    rag_parser = subparsers.add_parser("rag-index", help="Build novel knowledge-base vector index")
    rag_parser.add_argument(
        "--source-dir",
        default=None,
        help="Directory containing txt novels for indexing (default: paths.rag_source_dir)",
    )
    rag_parser.add_argument(
        "--rebuild",
        action="store_true",
        help="Rebuild collection from scratch before indexing",
    )

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    logger = None
    if getattr(args, "trace", False):
        log_file = args.log_file or _default_trace_log_path(args.config, args.chapter)
        logger = FileLogger(log_file, trace=True)
        logger.info(f"启动命令: {args.command} chapter={getattr(args, 'chapter', None)}")
        logger.info(f"配置路径: {args.config}")

    if args.command == "rag-index":
        load_env()
        project = load_yaml(args.config)
        progress_logger = _StdoutProgressLogger()
        result = build_rag_index(
            project_config=project,
            source_dir=args.source_dir,
            rebuild=args.rebuild,
            logger=progress_logger,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    pipeline = LangChainPipeline(project_path=args.config, logger=logger)

    if args.command == "plan":
        plan = pipeline.run_plan(chapter_id=args.chapter)
        print(json.dumps(plan, ensure_ascii=False, indent=2))
        return 0

    if args.command == "chapter":
        stream_override = None if not args.no_stream else False
        result = pipeline.run_chapter(
            chapter_id=args.chapter,
            stream_override=stream_override,
            force=args.force,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    parser.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
